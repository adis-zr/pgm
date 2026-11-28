"""Compiled factor / query VIEWS (manuscript §3.3 'compact linear-map factor views'; reduction note §2.3).
  * kind 'table'  : an explicit rational table over compiled categorical variables (scope, values row-major).
  * kind 'affine' : g(y, x_c) evaluated at y = U z (over GF(2)), where z are compiled binary variables (the affine parametrization x_B = c + B z of the eliminated
                    binary block), x_c are compiled categorical variables, and g is an explicit table over rho = rank(U) bits + the categorical axes. The view NEVER
                    expands to a table over every z column: `scope` lists the z columns that appear (nonzero columns of U) plus the categorical axes.
Both kinds support exact point evaluation, exact extrema over a CELL (a partial assignment of compiled variables), and exact summation over a cell (enumeration).
GF(2) rows are Python ints (bit i = column i)."""
from fractions import Fraction as F
from itertools import product
from math import prod, lcm


def gf2_rank_basis(rows):
    """row-reduce a list of GF(2) row vectors (ints); returns (rank, basis list of pivot rows in echelon form)"""
    basis = []
    for r in rows:
        for b in basis:
            if r ^ b < r: r ^= b
        if r: basis.append(r); basis.sort(reverse=True)
    return len(basis), basis


def gf2_reduce(r, basis):
    for b in basis:
        if r ^ b < r: r ^= b
    return r


def gf2_span(basis):
    """all 2^rank vectors of the span (rank is small by construction: bounded by the local table's bit count)"""
    out = [0]
    for b in basis: out = out + [x ^ b for x in out]
    return out


VIEW_STORAGE_RULE = ('a View OWNS an IMMUTABLE tuple `values` (and, for affine views, an immutable tuple `urows`); the constructor BORROWS the tuple it is given without traversing it '
                     '(the stored object IS the argument: a scope-only transformation such as renumbering shares storage and reads nothing), and REFUSES mutable storage (a list) with a '
                     'TypeError -- a builder produces its table in scratch storage under the operator meter (every produced entry charged as it is produced) and freezes it ONCE into the '
                     'view\'s owned tuple; no code path mutates a view\'s values (ninth adversarial review, CQR-R8-01). `den` / `ivals` are per-view derived caches set by refresh().')


class View:
    __slots__ = ('kind', 'scope', 'values', 'cat_scope', 'zcols', 'urows', 'rho', 'ycards', 'den', 'ivals')
    def __init__(self, kind, scope, values, cat_scope=None, zcols=None, urows=None):
        if not isinstance(values, tuple): raise TypeError('View storage must be an immutable tuple owned by the view (got %s): freeze the builder\'s scratch list once with tuple(...)' % type(values).__name__)
        self.kind = kind; self.scope = tuple(scope); self.values = values                 # BORROWED, never traversed here (VIEW_STORAGE_RULE)
        if kind == 'affine':
            # urows: rho GF(2) rows over the compiled z variables (bit position = index into zcols); g indexed row-major by (y bits as a rho-tuple, then cat axes)
            if not isinstance(urows, tuple): raise TypeError('affine urows must be an immutable tuple')
            self.cat_scope = tuple(cat_scope); self.zcols = tuple(zcols); self.urows = urows; self.rho = len(urows)
        else: self.cat_scope = self.scope; self.zcols = (); self.urows = (); self.rho = 0
        self.den = None; self.ivals = None

    def refresh(self):
        """integerize: ivals = values * den (den = lcm of the denominators); the true table = ivals / den. Call after the compiler has finished mutating `values`."""
        self.den = lcm(*[F(v).denominator for v in self.values]) if self.values else 1
        self.ivals = [int(F(v) * self.den) for v in self.values]; return self

    def at_i(self, cards, x):
        """integer value (= value * den) at a full assignment"""
        if self.kind == 'table':
            i = 0
            for v in self.scope: i = i * cards[v] + x[v]
            return self.ivals[i]
        i = self._y_of(x)
        for v in self.cat_scope: i = i * cards[v] + x[v]
        return self.ivals[i]

    def extrema_i(self, cards, cell, work=None):
        lo, hi = self.extrema(cards, cell, work)
        return int(lo * self.den), int(hi * self.den)

    def size(self): return len(self.values)

    # ---- indexing
    def _y_of(self, x):
        y = 0
        for i, row in enumerate(self.urows):
            bit = 0; r = row; k = 0
            while r:
                if r & 1 and x[self.zcols[k]]: bit ^= 1
                r >>= 1; k += 1
            y = (y << 1) | bit
        return y

    def at(self, cards, x):
        if self.kind == 'table':
            i = 0
            for v in self.scope: i = i * cards[v] + x[v]
            return self.values[i]
        i = self._y_of(x)
        for v in self.cat_scope: i = i * cards[v] + x[v]
        return self.values[i]

    def _rows_for_cat(self, cards, cell):
        """iterate the categorical index parts compatible with a cell (dict var -> state); yields (index multiplier path) via product"""
        axes = [(range(cards[v]) if v not in cell else (cell[v],)) for v in self.cat_scope]
        return axes

    def attainable_y(self, cell):
        """the set of y values attainable under a partial z assignment: U_assigned z_assigned + span(unassigned columns of U)"""
        base = 0; cols_free = []
        for i, row in enumerate(self.urows):
            bit = 0; r = row; k = 0
            while r:
                if r & 1:
                    zc = self.zcols[k]
                    if zc in cell:
                        if cell[zc]: bit ^= 1
                r >>= 1; k += 1
            base = (base << 1) | bit
        # free-column vectors: for each unassigned z column, the column of U as a rho-bit vector
        for k, zc in enumerate(self.zcols):
            if zc in cell: continue
            col = 0
            for i, row in enumerate(self.urows): col = (col << 1) | ((row >> k) & 1)
            if col: cols_free.append(col)
        _, basis = gf2_rank_basis(cols_free)
        return [base ^ s for s in gf2_span(basis)]

    def extrema(self, cards, cell, work=None):
        """(min, max) of the view over all compiled assignments compatible with the cell; charged as entries read"""
        lo = None; hi = None
        if self.kind == 'table':
            axes = [(range(cards[v]) if v not in cell else (cell[v],)) for v in self.scope]
            for xs in product(*axes):
                i = 0
                for v, s in zip(self.scope, xs): i = i * cards[v] + s
                w = self.values[i]
                if work is not None: work.entries += 1
                if lo is None or w < lo: lo = w
                if hi is None or w > hi: hi = w
            return lo, hi
        ys = self.attainable_y(cell); axes = [(range(cards[v]) if v not in cell else (cell[v],)) for v in self.cat_scope]
        for y in ys:
            for xs in product(*axes):
                i = y
                for v, s in zip(self.cat_scope, xs): i = i * cards[v] + s
                w = self.values[i]
                if work is not None: work.entries += 1
                if lo is None or w < lo: lo = w
                if hi is None or w > hi: hi = w
        return lo, hi

    def to_json(self):
        d = dict(kind=self.kind, scope=list(self.scope), values=[str(v) for v in self.values])
        if self.kind == 'affine': d.update(cat_scope=list(self.cat_scope), zcols=list(self.zcols), urows=[str(r) for r in self.urows])
        return d

    @staticmethod
    def from_json(d):
        vals = tuple(F(v) for v in d['values'])
        if d['kind'] == 'affine': return View('affine', d['scope'], vals, cat_scope=d['cat_scope'], zcols=d['zcols'], urows=tuple(int(r) for r in d['urows']))
        return View('table', d['scope'], vals)

    def table_json(self): return dict(scope=list(self.scope), values=[str(v) for v in self.values])


def weight_at(views, cards, x, work=None):
    w = F(1)
    for v in views:
        w *= v.at(cards, x)
        if work is not None: work.entries += 1
        if not w: return w
    return w
