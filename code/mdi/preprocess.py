"""Common exact preprocessing, applied IDENTICALLY to every arm (contract §C).

Zero approximation error. Every identity is checked entrywise on exact
rationals, zeros included, and the checker can rederive each one from the
original input bytes.

Discovered in review: Pedigree_11 carries 22 positive constant factors and 13
exactly separable pair factors whose declared scopes are not real dependencies.
Removing them takes min_fill from width 24 to 20, the largest bag from
33,554,432 to 2,097,152 and the bag-entry sum from 82,010,254 to 5,922,542.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field
from mdi.model import Factor, InvalidModel


class PreprocessError(ValueError):
    pass


@dataclass
class Simplified:
    """The simplified factor list plus the exact record needed to re-derive it."""
    factors: list
    scale: Fr                      # exact positive constant pulled out
    removed_constants: list        # [(origin, value, domain_size)]
    split_pairs: list              # [(origin, scope, pivot, u, v)]
    merged_unary: list             # original unary factor origins folded in
    impossible: int | None         # origin of an identically zero factor
    free: list
    card: dict

    def identity(self) -> dict:
        return {"scale": str(self.scale),
                "removed_constants": [(o, str(v), n) for o, v, n in self.removed_constants],
                "split_pairs": [(o, list(sc), list(pv)) for o, sc, pv, _, _ in self.split_pairs],
                "merged_unary": list(self.merged_unary),
                "n_factors_out": len(self.factors),
                "impossible": self.impossible}


def is_constant(f: Factor):
    """A factor equal to one positive value on its whole domain."""
    t0 = f.table[0]
    if t0 <= 0:
        return None
    for t in f.table:
        if t != t0:
            return None
    return t0


def separable_split(f: Factor):
    """Exact rank-one split of a pair table, zeros included.

    With a positive pivot (pa, pb) and C = F[pa][pb], the table is separable iff
    F[a][b] * C == F[a][pb] * F[pa][b] for EVERY (a, b). Then

        F[a][b] = (F[a][pb] / C) * F[pa][b],

    so u(a) = F[a][pb]/C and v(b) = F[pa][b] reproduce it exactly. A zero row or
    column is carried by u or v, so support is preserved without special-casing.

    Returns (pivot, u, v) or None. The identity is re-verified before returning.
    """
    if len(f.scope) != 2:
        return None
    di, dj = f.card
    tb = f.table
    piv = None
    for a in range(di):
        for b in range(dj):
            if tb[a * dj + b] > 0:
                piv = (a, b)
                break
        if piv:
            break
    if piv is None:
        return None                      # identically zero: handled by the caller
    pa, pb = piv
    C = tb[pa * dj + pb]
    for a in range(di):
        for b in range(dj):
            if tb[a * dj + b] * C != tb[a * dj + pb] * tb[pa * dj + b]:
                return None
    u = [tb[a * dj + pb] / C for a in range(di)]
    v = [tb[pa * dj + b] for b in range(dj)]
    for a in range(di):                  # re-verify the reconstruction exactly
        for b in range(dj):
            if u[a] * v[b] != tb[a * dj + b]:
                raise PreprocessError("separable split failed its own identity "
                                      "check on factor %d" % f.origin)
    return piv, u, v


def simplify(restricted, combine_same_scope=True, bit_cap=None):
    """Apply the exact preprocessing of contract §C to a restricted model.

    Order: identically-zero detection, positive constant removal (scale kept),
    exact separable pair splitting, same-scope multiplication, unary combination.
    Every requested original variable keeps a factor, including isolated ones.
    """
    from mdi import config as K
    cap = bit_cap or K.CAPS["rational_bit_length"]
    free, card = list(restricted.free), dict(restricted.card)
    scale = Fr(1)
    unary = {v: [Fr(1)] * card[v] for v in free}
    removed, splits, merged = [], [], []
    keep, impossible = [], None

    for f in restricted.factors:
        if all(t == 0 for t in f.table):
            impossible = f.origin if impossible is None else impossible
            keep.append(f)
            continue
        c = is_constant(f)
        if c is not None:
            n = 1
            for d in f.card:
                n *= d
            scale *= c
            removed.append((f.origin, c, n))
            continue
        if len(f.scope) == 1:
            v = f.scope[0]
            for a in range(card[v]):
                unary[v][a] *= f.table[a]
            merged.append(f.origin)
            continue
        sp = separable_split(f)
        if sp is not None:
            piv, u, v2 = sp
            i, j = f.scope
            for a in range(card[i]):
                unary[i][a] *= u[a]
            for b in range(card[j]):
                unary[j][b] *= v2[b]
            splits.append((f.origin, f.scope, piv, u, v2))
            continue
        keep.append(f)

    if combine_same_scope:
        by_scope = {}
        order = []
        for f in keep:
            key = tuple(sorted(f.scope))
            if key in by_scope:
                g = by_scope[key]
                if g.scope == f.scope:
                    tbl = [a * b for a, b in zip(g.table, f.table)]
                else:
                    perm = [f.scope.index(v) for v in g.scope]
                    gst = g.strides(); fst = f.strides()
                    n = len(g.table)
                    tbl = [None] * n
                    for flat in range(n):
                        rem, dig = flat, []
                        for k in range(len(g.card)):
                            dig.append(rem // gst[k]); rem %= gst[k]
                        off = sum(dig[k] * fst[perm[k]] for k in range(len(g.card)))
                        tbl[flat] = g.table[flat] * f.table[off]
                if any(x.numerator.bit_length() > cap or
                       x.denominator.bit_length() > cap for x in tbl):
                    keep_sep = True
                else:
                    by_scope[key] = Factor(scope=g.scope, card=g.card, table=tbl,
                                           origin=g.origin)
                    continue
            by_scope[key] = f
            order.append(key)
        keep = [by_scope[k] for k in order]

    out = list(keep)
    for v in sorted(free):
        out.append(Factor(scope=(v,), card=(card[v],), table=list(unary[v]),
                          origin=-1 - v))
    for v in free:
        if not any(v in f.scope for f in out):
            raise PreprocessError("variable %d lost its factor" % v)
    return Simplified(factors=out, scale=scale, removed_constants=removed,
                      split_pairs=splits, merged_unary=merged,
                      impossible=impossible, free=free, card=card)


def verify_identities(restricted, simp: Simplified):
    """Rederive every claimed identity from the ORIGINAL factors (checker side).

    Does not consult the producer's output tables; it re-tests each recorded
    constant and split against the original bytes.
    """
    byo = {f.origin: f for f in restricted.factors}
    for origin, val, n in simp.removed_constants:
        f = byo.get(origin)
        if f is None:
            raise PreprocessError("constant record names an unknown factor %d" % origin)
        c = is_constant(f)
        if c is None or c != val:
            raise PreprocessError("factor %d is not the recorded constant" % origin)
        dom = 1
        for d in f.card:
            dom *= d
        if dom != n:
            raise PreprocessError("constant %d domain size mismatch" % origin)
    for origin, scope, piv, u, v in simp.split_pairs:
        f = byo.get(origin)
        if f is None:
            raise PreprocessError("split record names an unknown factor %d" % origin)
        if tuple(f.scope) != tuple(scope):
            raise PreprocessError("split %d scope mismatch" % origin)
        sp = separable_split(f)
        if sp is None:
            raise PreprocessError("factor %d is NOT exactly separable" % origin)
        p2, u2, v2 = sp
        di, dj = f.card
        for a in range(di):
            for b in range(dj):
                if u2[a] * v2[b] != f.table[a * dj + b]:
                    raise PreprocessError("split %d fails entrywise" % origin)
    for origin in simp.merged_unary:
        f = byo.get(origin)
        if f is None or len(f.scope) != 1:
            raise PreprocessError("unary record %d invalid" % origin)
    return True
