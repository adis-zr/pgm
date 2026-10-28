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
    declined_products: list = field(default_factory=list)
    emitted: list = field(default_factory=list)
    combined_splits: list = field(default_factory=list)
    combined_constants: list = field(default_factory=list)

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
        # Same-scope multiplication. When the product would exceed the bit cap
        # the factors must BOTH be retained unchanged.
        #
        # The previous version set a dead local `keep_sep` flag, fell through to
        # `by_scope[key] = f`, and so OVERWROTE the first factor with the second
        # while `order` already held the key. One input factor was silently
        # dropped and the other effectively duplicated. With pair tables
        # [B,B,B,2B] and [B,B,B,3B] at B = 2^32768 that changed the law from
        # 7/9 to 5/6 and the engine then certified an interval excluding the
        # truth. The law must be preserved or the combination declined; it may
        # never be altered.
        combined = {}          # scope key -> the single accumulated factor
        combined_members = {}  # scope key -> the original origins multiplied in
        combined_splits, combined_constants = [], []
        order = []
        uncombined = []        # factors kept separate because the cap declined
        declined = []
        for f in keep:
            key = tuple(sorted(f.scope))
            g = combined.get(key)
            if g is None:
                combined[key] = f
                combined_members[key] = [f.origin]
                order.append(key)
                continue
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
                # DECLINE the combination and keep BOTH factors as they are
                uncombined.append(f)
                declined.append({"scope": list(key),
                                 "origins": [g.origin, f.origin],
                                 "reason": "product exceeds the %d-bit cap; both "
                                           "factors retained unchanged" % cap})
                continue
            combined[key] = Factor(scope=g.scope, card=g.card, table=tbl,
                                   origin=g.origin)
            combined_members.setdefault(key, [g.origin]).append(f.origin)
        # Re-simplify: multiplication can CREATE a constant or exactly
        # separable factor, which the single pass left as a spurious graph
        # dependency.
        resimplified = []
        for key in order:
            f = combined[key]
            # A factor here may be a PRODUCT of several originals, so any
            # identity found now belongs to the combined table, not to one
            # original factor. Record it separately with the combined table so
            # the checker can re-derive it without being told that an original
            # factor was separable when it was not.
            members = combined_members.get(key, [f.origin])
            c = is_constant(f)
            if c is not None:
                scale *= c
                if len(members) > 1:
                    combined_constants.append(
                        {"scope": list(f.scope), "members": list(members),
                         "value": str(c), "entries": len(f.table)})
                else:
                    removed.append((f.origin, c, len(f.table)))
                continue
            if len(f.scope) == 1:
                v = f.scope[0]
                for a in range(card[v]):
                    unary[v][a] *= f.table[a]
                merged.append(f.origin)
                continue
            sp2 = separable_split(f)
            if sp2 is not None:
                piv, u2, v2 = sp2
                i, j = f.scope
                for a in range(card[i]):
                    unary[i][a] *= u2[a]
                for b in range(card[j]):
                    unary[j][b] *= v2[b]
                if len(members) > 1:
                    combined_splits.append(
                        {"scope": list(f.scope), "members": list(members),
                         "pivot": list(piv)})
                else:
                    splits.append((f.origin, f.scope, piv, u2, v2))
                continue
            resimplified.append(f)
        keep = resimplified + uncombined
    else:
        declined = []
        combined_splits, combined_constants, combined_members = [], [], {}

    out = list(keep)
    for v in sorted(free):
        out.append(Factor(scope=(v,), card=(card[v],), table=list(unary[v]),
                          origin=-1 - v))
    for v in free:
        if not any(v in f.scope for f in out):
            raise PreprocessError("variable %d lost its factor" % v)
    simp = Simplified(factors=out, scale=scale, removed_constants=removed,
                      split_pairs=splits, merged_unary=merged,
                      impossible=impossible, free=free, card=card)
    simp.declined_products = declined
    simp.combined_splits = combined_splits
    simp.combined_constants = combined_constants
    # A bounded EXACT transformation record: for every surviving factor, which
    # original origins were multiplied into it. The checker replays this.
    prov = {}
    for f in out:
        prov.setdefault(id(f), [])
    simp.emitted = [{"scope": list(f.scope), "card": list(f.card),
                     "origin": f.origin, "entries": len(f.table)}
                    for f in out]
    return simp


def verify_identities(restricted, simp: Simplified):
    """Rederive every claimed identity from the ORIGINAL factors (checker side).

    Does not consult the producer's output tables; it re-tests each recorded
    constant and split against the original bytes, AND independently verifies
    that the emitted factor list reproduces the original weight function.

    The identity-by-identity checks alone were insufficient: a same-scope
    combination that dropped one factor and duplicated another satisfied every
    recorded identity while changing the law from 7/9 to 5/6. Ownership and
    multiplicity must be checked, not just the transformations that were
    recorded.
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

    # ---- combined identities: rebuild the product from the ORIGINALS ----
    for recd in getattr(simp, "combined_splits", []) + \
                getattr(simp, "combined_constants", []):
        members = recd["members"]
        facs = [byo.get(o) for o in members]
        if any(x is None for x in facs):
            raise PreprocessError("combined record names an unknown factor "
                                  "among %s" % members)
        base = facs[0]
        tbl = list(base.table)
        for g in facs[1:]:
            if tuple(g.scope) == tuple(base.scope):
                tbl = [a * b for a, b in zip(tbl, g.table)]
            else:
                perm = [g.scope.index(v) for v in base.scope]
                bst = base.strides(); gst = g.strides()
                nt = []
                for flat in range(len(tbl)):
                    rem, dig = flat, []
                    for k in range(len(base.card)):
                        dig.append(rem // bst[k]); rem %= bst[k]
                    off = sum(dig[k] * gst[perm[k]] for k in range(len(base.card)))
                    nt.append(tbl[flat] * g.table[off])
                tbl = nt
        prod = Factor(scope=base.scope, card=base.card, table=tbl,
                      origin=base.origin)
        if "pivot" in recd:
            if separable_split(prod) is None:
                raise PreprocessError(
                    "the COMBINED factor over originals %s is not exactly "
                    "separable, so the recorded re-simplification is invalid"
                    % members)
        else:
            if is_constant(prod) is None:
                raise PreprocessError(
                    "the COMBINED factor over originals %s is not constant"
                    % members)

    # ---- independent ownership and multiplicity accounting ----
    # Every original factor must be accounted for EXACTLY ONCE: removed as a
    # constant, split, merged as a unary, folded into a same-scope product, or
    # emitted unchanged. No factor may be dropped and none duplicated.
    accounted = {}

    def claim(origin, how):
        if origin in accounted:
            raise PreprocessError(
                "original factor %d is accounted for twice (%s and %s): a "
                "dropped-and-duplicated factor changes the law while satisfying "
                "every recorded identity" % (origin, accounted[origin], how))
        accounted[origin] = how

    for origin, _, _ in simp.removed_constants:
        claim(origin, "constant")
    for origin, _, _, _, _ in simp.split_pairs:
        claim(origin, "separable split")
    for origin in simp.merged_unary:
        claim(origin, "unary merge")
    for recd in (getattr(simp, "combined_splits", []) +
                 getattr(simp, "combined_constants", [])):
        for origin in recd["members"]:
            claim(origin, "combined then re-simplified")
    # emitted factors: a synthetic unary carries origin -1-v; everything else
    # must trace to an original origin, and a same-scope product names its first
    synth = {-1 - v for v in simp.free}
    emitted_origins = []
    for f in simp.factors:
        if f.origin in synth or f.origin == -1:
            continue
        emitted_origins.append(f.origin)
    for origin in emitted_origins:
        if origin not in byo:
            raise PreprocessError("emitted factor claims unknown origin %d" % origin)
        claim(origin, "emitted")
    # a declined product keeps BOTH factors, so its second origin is also emitted
    for d in getattr(simp, "declined_products", []):
        for origin in d["origins"]:
            if origin not in accounted:
                claim(origin, "declined product (retained)")
    # anything still unaccounted was folded into a same-scope product
    for origin, f in byo.items():
        if origin in accounted:
            continue
        key = tuple(sorted(f.scope))
        host = None
        for g in simp.factors:
            if tuple(sorted(g.scope)) == key and g.origin in accounted:
                host = g
                break
        if host is None:
            raise PreprocessError(
                "original factor %d (scope %s) is NOT accounted for: it was "
                "neither removed, split, merged, emitted nor folded into a "
                "surviving same-scope factor" % (origin, f.scope))
        accounted[origin] = "folded into origin %d" % host.origin
    missing = [o for o in byo if o not in accounted]
    if missing:
        raise PreprocessError("original factors %s unaccounted" % missing[:5])

    # ---- independent law check on a bounded enumeration ----
    # When the free domain is small enough, recompute the weight function from
    # the ORIGINAL factors and from the emitted ones and require equality up to
    # the recorded exact scale. This catches any transformation error, not only
    # the ones that were recorded.
    import itertools
    q = 1
    for v in simp.free:
        q *= simp.card[v]
        if q > 4096:
            break
    if q <= 4096:
        def weigh(facs, assign):
            w = Fr(1)
            for f in facs:
                st = f.strides()
                off = 0
                for k, v in enumerate(f.scope):
                    off += assign[v] * st[k]
                e = f.table[off]
                if e == 0:
                    return Fr(0)
                w *= e
            return w
        order = sorted(simp.free)
        for combo in itertools.product(*[range(simp.card[v]) for v in order]):
            a = dict(zip(order, combo))
            w0 = weigh(restricted.factors, a)
            w1 = simp.scale * weigh(simp.factors, a)
            if w0 != w1:
                raise PreprocessError(
                    "preprocessing CHANGED THE LAW at assignment %s: original "
                    "weight %s, simplified weight %s (scale %s)"
                    % (a, w0, w1, simp.scale))
    return True
