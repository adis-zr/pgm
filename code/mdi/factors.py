"""Typed factor interface (spec §4, §5.3 compactness).

Two factor types share one access protocol -- `scope`, `card`, `strides()`,
`size()`, `at(assignment)`, `table[flat]`, `origin`:

  * `model.Factor`      : a DENSE input table (the original UAI bytes).
  * `ProjectedFactor`   : an EXACT PROJECTED VIEW of an original table over the
                          current (cell) variables. It stores the original table
                          by reference plus, per current variable, an integer
                          offset per state. Nothing is expanded: entry `(c_1,
                          ..., c_k)` is `base.table[offsets[1][c_1] + ... +
                          offsets[k][c_k]]`.

A view at the next scale is obtained by COMPOSING offset maps -- summing the
child offsets selected by each parent cell's representative -- never by
expanding the intermediate cell product. The `table` attribute of a view is a
`LazyTable`: `len` and integer indexing work, iteration is refused loudly, and
`materialize(cap)` is the only way to obtain a dense list (for the bounded
collective recognizer).
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
from mdi import model as M


class ViewError(ValueError):
    pass


def _strides(card):
    st = [1] * len(card)
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc
        acc *= card[k]
    return tuple(st)


class LazyTable:
    """entry[flat] = base[sum_k offsets[k][digit_k(flat)]]; optional `lift`
    maps the exact entry into another algebra on read."""
    __slots__ = ("card", "st", "offsets", "base", "n", "lift")

    def __init__(self, card, offsets, base, lift=None):
        self.card = tuple(card)
        self.st = _strides(self.card)
        self.offsets = [list(o) for o in offsets]
        self.base = base
        n = 1
        for c in self.card:
            n *= c
        self.n = n
        self.lift = lift

    def __len__(self):
        return self.n

    def __getitem__(self, flat):
        if not isinstance(flat, int):
            raise TypeError("a projected view supports integer indexing only")
        if not (0 <= flat < self.n):
            raise IndexError(flat)
        off = 0
        rem = flat
        for k in range(len(self.card)):
            d, rem = divmod(rem, self.st[k])
            off += self.offsets[k][d]
        v = self.base[off]
        return v if self.lift is None else self.lift(v)

    def at_digits(self, digits):
        off = 0
        for k, d in enumerate(digits):
            off += self.offsets[k][d]
        v = self.base[off]
        return v if self.lift is None else self.lift(v)

    def __iter__(self):
        raise ViewError("a projected view is not enumerated implicitly; use "
                        "materialize(cap) for a bounded dense copy")

    def materialize(self, cap):
        if self.n > cap:
            raise ViewError("materializing a %d-entry projected view exceeds "
                            "the %d-entry cap" % (self.n, cap))
        return [self[i] for i in range(self.n)]


@dataclass
class ProjectedFactor:
    scope: tuple                  # CURRENT variable ids
    card: tuple
    offsets: dict                 # current var -> [int offset per state]
    base: object                  # the original dense M.Factor
    origin: int = -1
    scale: Fr = Fr(1)
    table: object = field(default=None, repr=False)

    def __post_init__(self):
        self.scope = tuple(self.scope)
        self.card = tuple(self.card)
        if self.table is None:
            self.table = LazyTable(self.card, [self.offsets[v] for v in self.scope],
                                   self.base.table)

    def strides(self):
        return _strides(self.card)

    def size(self):
        n = 1
        for c in self.card:
            n *= c
        return n

    def at(self, assign: dict):
        off = 0
        for v in self.scope:
            off += self.offsets[v][assign[v]]
        return self.base.table[off]

    @staticmethod
    def from_dense(f, origin=None):
        """The identity view of a dense factor: offsets are the strides."""
        st = f.strides()
        offs = {v: [a * st[k] for a in range(f.card[k])] for k, v in enumerate(f.scope)}
        return ProjectedFactor(scope=tuple(f.scope), card=tuple(f.card), offsets=offs,
                               base=f, origin=f.origin if origin is None else origin,
                               scale=getattr(f, "scale", Fr(1)))

    def compose(self, region_of, reps, bpos, ncell):
        """The view over the NEXT scale's cell variables.

        `region_of[v]` is the new variable (region index) holding current
        variable v; `reps[i]` lists region i's cell representatives (tuples
        over region i's boundary order); `bpos[i][v]` is v's position in that
        order; `ncell[i]` the number of cells. The new offset of region i at
        cell c is the SUM of this view's offsets at the representative's
        states -- maps compose, nothing is expanded.
        """
        new_vars = sorted({region_of[v] for v in self.scope})
        offs = {}
        for i in new_vars:
            mine = [v for v in self.scope if region_of[v] == i]
            col = []
            for c in range(ncell[i]):
                rep = reps[i][c]
                o = 0
                for v in mine:
                    if v not in bpos[i]:
                        raise ViewError("variable %d of factor %d is not on the "
                                        "boundary of region %d" % (v, self.origin, i))
                    o += self.offsets[v][rep[bpos[i][v]]]
                col.append(o)
            offs[i] = col
        return ProjectedFactor(scope=tuple(new_vars), card=tuple(ncell[i] for i in new_vars),
                               offsets=offs, base=self.base, origin=self.origin,
                               scale=self.scale)

    def map_entries(self):
        """Offset-map storage: one integer per state per current variable."""
        return sum(len(o) for o in self.offsets.values())


def is_view(f) -> bool:
    return isinstance(f, ProjectedFactor)


def as_view(f) -> ProjectedFactor:
    return f if is_view(f) else ProjectedFactor.from_dense(f)


def dense_table(f, cap):
    """A bounded dense copy of any factor's table (for the recognizer)."""
    if is_view(f):
        return f.table.materialize(cap)
    if len(f.table) > cap:
        raise ViewError("a %d-entry dense table exceeds the %d-entry cap"
                        % (len(f.table), cap))
    return [Fr(x) for x in f.table]


def densify(f, cap, origin=None):
    """A dense M.Factor copy of a view (bounded), or the factor itself."""
    if not is_view(f):
        return f
    return M.Factor(scope=tuple(f.scope), card=tuple(f.card), table=dense_table(f, cap),
                    origin=f.origin if origin is None else origin, scale=f.scale)
