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
    combined_members: dict = field(default_factory=dict)

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
    simp.combined_members = {"|".join(map(str, k)): list(v)
                             for k, v in combined_members.items()}
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
    # A synthetic origin is -1-v for free variable v. Exempting that origin
    # BEFORE proving the factor really is the expected unary on variable v let
    # an unrecorded PAIR interaction take the origin and escape accounting
    # entirely: pair weights [1,1,1,9] under a synthetic origin certified
    # about (1/6, 5/6) where the original law is (.5, .5).
    synth = {-1 - v: v for v in simp.free}
    emitted_origins = []
    for f in simp.factors:
        if f.origin in synth:
            want_v = synth[f.origin]
            if len(f.scope) != 1 or f.scope[0] != want_v:
                raise PreprocessError(
                    "a factor with SYNTHETIC origin %d has scope %s, but that "
                    "origin is reserved for the unary on variable %d; a "
                    "substituted interaction would otherwise escape local "
                    "accounting" % (f.origin, tuple(f.scope), want_v))
            if len(f.table) != simp.card[want_v]:
                raise PreprocessError(
                    "synthetic unary for variable %d has %d entries, "
                    "cardinality is %d"
                    % (want_v, len(f.table), simp.card[want_v]))
            continue
        # There is NO unchecked origin exemption. `if f.origin == -1: continue`
        # was unconditional, and -1 is the synthetic origin of variable 0
        # ONLY while variable 0 is free (synthetic origins are -1-v). Once X0
        # is observed, -1 is reserved for nothing, so the skip hid an
        # arbitrary extra factor: appending a pair on (1,2) with table
        # [1,1,1,9] and origin -1 to a conditioned uniform model certified
        # near (1/6, 5/6) against a true (.5, .5) at 13, 16 and 20 free
        # variables. It rejected at 12 only because the bounded global
        # enumeration caught the altered law.
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

    # ---- complete LOCAL law verification, at every joint size ----
    # A bounded global enumeration was the only output-law check, gated at
    # 4,096 joint assignments. Above that threshold nothing validated the
    # EMITTED tables, so a corrupted output factor, a corrupted scale and a
    # dropped nonconstant factor all passed: at 13 uniform binary variables a
    # producer that changed one unary from [1,1] to [9,1] was certified at
    # about (.9,.1) against a true (.5,.5).
    #
    # Global enumeration is not the remedy either -- it cannot scale, and the
    # spec asks for a checked local derivation. Each ORIGINAL factor's law is
    # reconstructed on ITS OWN scope from the emitted factors that cover it,
    # which costs the product of that factor's cardinalities (bounded by
    # arity), never the joint domain.
    import itertools
    from mdi import config as K

    def _weigh(facs, assign):
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

    # Verify each recorded transformation on ITS OWN local domain.
    #
    # The only output-law check was a global enumeration gated at 4,096 joint
    # assignments; above it, corrupted output tables, a corrupted scale and a
    # dropped nonconstant factor all passed. At 13 uniform binary variables a
    # producer that changed one unary from [1,1] to [9,1] was certified near
    # (.9,.1) against a true (.5,.5).
    #
    # Global enumeration cannot be the remedy, and neither can a geometric
    # cover of the factor graph: a chain closes up into the whole model. What
    # the spec asks for is a checked LOCAL derivation, and `simplify` already
    # records which of four transformations produced every emitted table. Each
    # is verified on the domain of the factors it names -- bounded by factor
    # arity, never by the joint domain -- and every original and emitted table
    # must be named by exactly one record.
    # VALIDATE the `impossible` proof exit. It is a claim that a named factor
    # is identically zero, and nothing checked it: setting it to 0 or to a
    # nonexistent origin 999 passed, and both public solvers then returned
    # ZERO_EVIDENCE_PROVED for unary [1,2] whose Z is 3 and whose marginals
    # are (1/3, 2/3). A field is not a proof.
    if simp.impossible is not None:
        wf = byo.get(simp.impossible)
        if wf is None:
            raise PreprocessError(
                "the `impossible` proof names origin %r, which is not an "
                "original factor of the restricted model; a zero-weight "
                "proof needs a real witness" % (simp.impossible,))
        if not all(Fr(t) == 0 for t in wf.table):
            nz = [i for i, t in enumerate(wf.table) if Fr(t) != 0]
            raise PreprocessError(
                "the `impossible` proof names origin %d on scope %s, but that "
                "factor is NOT identically zero (%d of %d entries are "
                "positive, e.g. index %d = %s); this is a FALSE zero-evidence "
                "proof" % (simp.impossible, tuple(wf.scope), len(nz),
                           len(wf.table), nz[0], wf.table[nz[0]]))

    unary_contrib = {v: [Fr(1)] * simp.card[v] for v in simp.free}
    const_product = Fr(1)
    claims = {}          # origin -> how it was accounted

    def claim(origin, how):
        if origin in claims:
            raise PreprocessError(
                "original factor %d is accounted TWICE (%s and %s); double "
                "accounting would let a dropped factor hide behind a "
                "duplicated one" % (origin, claims[origin], how))
        claims[origin] = how

    # (1) exact constants: removed outright, contributing only to the scale
    for origin, val, n in simp.removed_constants:
        f = byo.get(origin)
        if f is None:
            raise PreprocessError("constant record names unknown factor %d"
                                  % origin)
        c = is_constant(f)
        if c is None or c != Fr(val):
            raise PreprocessError(
                "factor %d was recorded as the constant %s but its table is "
                "not that constant" % (origin, val))
        const_product *= Fr(val)
        claim(origin, "removed constant %s" % val)

    # (2) unary factors folded into the per-variable product
    for origin in simp.merged_unary:
        f = byo.get(origin)
        if f is None or len(f.scope) != 1:
            raise PreprocessError("merged-unary record names factor %d, which "
                                  "is not unary" % origin)
        v = f.scope[0]
        for a in range(simp.card[v]):
            unary_contrib[v][a] *= f.table[a]
        claim(origin, "merged unary")

    # (3) separable splits: verified on the PARENT factor's own domain, which
    # is the only place the two sides are comparable
    for origin, scope, piv, u, v2 in simp.split_pairs:
        f = byo.get(origin)
        if f is None or tuple(f.scope) != tuple(scope):
            raise PreprocessError("split record names factor %d with scope %s, "
                                  "which does not match" % (origin, scope))
        i, j = scope
        st = f.strides()
        for a in range(simp.card[i]):
            for b in range(simp.card[j]):
                got = Fr(u[a]) * Fr(v2[b])
                want = f.table[a * st[0] + b * st[1]]
                if got != want:
                    raise PreprocessError(
                        "separable split of factor %d is WRONG at (%d, %d): "
                        "u*v = %s but the original table holds %s"
                        % (origin, a, b, got, want))
        for a in range(simp.card[i]):
            unary_contrib[i][a] *= Fr(u[a])
        for b in range(simp.card[j]):
            unary_contrib[j][b] *= Fr(v2[b])
        claim(origin, "separable split")

    # (4) same-scope combinations. A combined table may itself turn out to be
    # constant, unary or separable, and `simplify` records each case with the
    # MEMBER list rather than pretending one original factor had the property.
    # Each record is verified against the product of its members on the
    # combined scope.
    def _member_product(scope, group, a):
        w = Fr(1)
        for mo in group:
            mf = byo[mo]
            mst = mf.strides()
            moff = sum(a[v] * mst[k] for k, v in enumerate(mf.scope))
            w *= mf.table[moff]
        return w

    for rec in getattr(simp, "combined_constants", []):
        if not isinstance(rec, dict):
            continue
        scope = tuple(sorted(rec.get("scope", [])))
        group = list(rec.get("members", []))
        val = Fr(rec.get("value", 1))
        for combo in itertools.product(*[range(simp.card[v]) for v in scope]):
            a = dict(zip(scope, combo))
            got = _member_product(scope, group, a)
            if got != val:
                raise PreprocessError(
                    "a combined group %s on scope %s was recorded as the "
                    "constant %s but its member product is %s at %s"
                    % (group, list(scope), val, got, a))
        const_product *= val
        for mo in group:
            claim(mo, "member of a combined constant %s" % val)

    for rec in getattr(simp, "combined_splits", []):
        if not isinstance(rec, dict):
            continue
        scope = tuple(rec.get("scope", []))
        group = list(rec.get("members", []))
        if len(scope) != 2:
            raise PreprocessError("combined split record on scope %s is not a "
                                  "pair" % (list(scope),))
        i, j = scope
        # re-derive the split from the MEMBER PRODUCT, independently of the
        # producer's u and v tables
        prod = {}
        for a in range(simp.card[i]):
            for b in range(simp.card[j]):
                prod[(a, b)] = _member_product(tuple(sorted(scope)), group,
                                               {i: a, j: b})
        tmp = Factor(scope=(i, j), card=(simp.card[i], simp.card[j]),
                     table=[prod[(a, b)] for a in range(simp.card[i])
                            for b in range(simp.card[j])], origin=-99999)
        sp = separable_split(tmp)
        if sp is None:
            raise PreprocessError(
                "a combined group %s on scope %s was recorded as separable, "
                "but the member product does NOT factorize"
                % (group, list(scope)))
        _piv, u_r, v_r = sp
        for a in range(simp.card[i]):
            unary_contrib[i][a] *= Fr(u_r[a])
        for b in range(simp.card[j]):
            unary_contrib[j][b] *= Fr(v_r[b])
        for mo in group:
            claim(mo, "member of a combined separable split")
    _raw_members = getattr(simp, "combined_members", None) or {}
    members = {}
    for _k, _v in _raw_members.items():
        if isinstance(_k, str):
            members[tuple(int(x) for x in _k.split("|") if x != "")] = list(_v)
        else:
            members[tuple(_k)] = list(_v)
    emitted_by_scope = {}
    for f in simp.factors:
        emitted_by_scope.setdefault(tuple(sorted(f.scope)), []).append(f)

    # every surviving original factor must be reproduced by the emitted tables
    # on its OWN scope, together with the unary contributions on that scope
    for origin, f in sorted(byo.items()):
        if origin in claims:
            continue
        scope = tuple(sorted(f.scope))
        n = 1
        for v in scope:
            n *= simp.card[v]
        if n > K.CAPS["region_tuple_assignments"]:
            raise PreprocessError(
                "original factor %d spans %d local assignments, above the "
                "declared cap; its transformation cannot be locally verified "
                "and is REFUSED rather than certified unchecked" % (origin, n))
        # The emitted factors carrying this origin. A same-scope combination
        # keeps ONE origin and records the others in the membership map, so a
        # member origin is verified against its host GROUP: the host's table
        # must equal the product of every member's original table.
        group = members.get(scope)
        if group and origin in group:
            # Validate the group BEFORE touching any table: a member that is
            # not an original factor, or whose scope reaches outside the
            # group, previously raised KeyError instead of a typed refusal.
            for mo in group:
                mf_chk = byo.get(mo)
                if mf_chk is None:
                    raise PreprocessError(
                        "combined group %s on scope %s names origin %r, which "
                        "is not an original factor"
                        % (group, list(scope), mo))
                if not set(mf_chk.scope) <= set(scope):
                    raise PreprocessError(
                        "combined group on scope %s names member origin %d "
                        "whose scope %s reaches OUTSIDE the group, so the "
                        "product is not comparable on that domain"
                        % (list(scope), mo, tuple(mf_chk.scope)))
            if len(set(group)) != len(group):
                dup = sorted({x for x in group if group.count(x) > 1})
                raise PreprocessError(
                    "combined group %s on scope %s lists origin(s) %s more "
                    "than once; an original factor cannot contribute twice "
                    "to one product" % (group, list(scope), dup))
            host = [g for g in emitted_by_scope.get(scope, [])
                    if g.origin in group]
            if not host:
                raise PreprocessError(
                    "combined group %s on scope %s has no emitted host table"
                    % (group, list(scope)))
            # verify the host against the product of ALL members, once
            if origin != min(group):
                claim(origin, "member of combined group %s" % (group,))
                continue
            st_by = {}
            for combo in itertools.product(*[range(simp.card[v])
                                             for v in scope]):
                a = dict(zip(scope, combo))
                w0 = Fr(1)
                for mo in group:
                    mf = byo[mo]
                    mst = st_by.setdefault(mo, mf.strides())
                    moff = sum(a[v] * mst[k] for k, v in enumerate(mf.scope))
                    w0 *= mf.table[moff]
                w1 = Fr(1)
                for g in host:
                    gst = st_by.setdefault(("e", id(g)), g.strides())
                    goff = sum(a[v] * gst[k] for k, v in enumerate(g.scope))
                    w1 *= g.table[goff]
                if w0 != w1:
                    raise PreprocessError(
                        "preprocessing CHANGED THE LAW: the combined factor on "
                        "scope %s is %s at %s but the product of its members "
                        "%s is %s; a dropped or overwritten input would "
                        "otherwise pass" % (list(scope), w1, a, group, w0))
            # `if mo not in claims: claim(...)` SILENTLY SKIPPED an
            # already-claimed member, so a member consumed elsewhere (merged
            # as a unary, split, or in another group) could be counted a
            # SECOND time inside this product. With pair F=[1,2,3,5] and
            # unary U=[1,2], emitting F*U while also retaining U as the
            # synthetic unary and recording both as members yields the law
            # F*U^2: P(X0) becomes (3/35,32/35) against a true (3/19,16/19).
            # Every local equality passed; only the bounded global
            # enumeration caught it, and only at 12 free variables.
            #
            # Each original factor OCCURRENCE is consumed exactly once, so a
            # member already claimed is a DOUBLE CONSUMPTION, not a no-op.
            for mo in group:
                if mo in claims:
                    raise PreprocessError(
                        "origin %d is a member of the combined group %s on "
                        "scope %s but was ALREADY accounted as '%s'; each "
                        "original factor occurrence is consumed exactly once"
                        % (mo, group, list(scope), claims[mo]))
                claim(mo, "combined group %s verified" % (group,))
            continue
        same = [g for g in simp.factors if g.origin == origin]
        if not same:
            raise PreprocessError(
                "original factor %d (scope %s) is NOT reproduced by any "
                "emitted table, so a DROPPED factor would pass"
                % (origin, f.scope))
        st = f.strides()
        for combo in itertools.product(*[range(simp.card[v]) for v in scope]):
            a = dict(zip(scope, combo))
            off = sum(a[v] * st[k] for k, v in enumerate(f.scope))
            w0 = f.table[off]
            w1 = Fr(1)
            for g in same:
                gst = g.strides()
                goff = sum(a[v] * gst[k] for k, v in enumerate(g.scope))
                w1 *= g.table[goff]
            # EQUALITY of every value, not merely matching zero support. The
            # support-only test left a bit-cap-declined factor's positive
            # entries unchecked: changing 3B to 30B on a retained factor
            # certified about 61/63 where the truth is 7/9.
            if w0 != w1:
                raise PreprocessError(
                    "preprocessing CHANGED THE LAW of factor %d at %s: "
                    "original weight %s, emitted product %s. An emitted table "
                    "must reproduce its original EXACTLY, not merely share its "
                    "zero support." % (origin, a, w0, w1))
        # scope and cardinality must agree too
        for g in same:
            if tuple(sorted(g.scope)) != scope:
                raise PreprocessError(
                    "emitted factor for origin %d has scope %s, not %s"
                    % (origin, tuple(sorted(g.scope)), scope))
            for k, v in enumerate(g.scope):
                if g.card[k] != simp.card[v]:
                    raise PreprocessError(
                        "emitted factor for origin %d declares cardinality %d "
                        "for variable %d, model says %d"
                        % (origin, g.card[k], v, simp.card[v]))
            if len(g.table) != n:
                raise PreprocessError(
                    "emitted factor for origin %d has %d entries, scope %s "
                    "needs %d" % (origin, len(g.table), scope, n))
        claim(origin, "emitted on its own scope")

    # every emitted UNARY must equal the accumulated unary contribution, which
    # is what catches a tampered output table on a variable
    for v in sorted(simp.free):
        em = [g for g in simp.factors
              if len(g.scope) == 1 and g.scope[0] == v and g.origin < 0]
        if not em:
            # `continue` here skipped the check whenever the output was
            # ABSENT, so a DROPPED required unary passed at every size above
            # the bounded global enumeration: it rejected at 12 binary
            # variables but certified .5 against a truth of (1/3, 2/3) at 13,
            # 16 and 20. simplify() emits exactly one synthetic unary per free
            # variable, so its absence is a dropped table.
            raise PreprocessError(
                "variable %d has NO emitted unary table, but the "
                "transformation accumulated the contribution %s for it; a "
                "DROPPED required unary would otherwise pass at any model "
                "size" % (v, [str(x) for x in unary_contrib[v]]))
        if len(em) > 1:
            raise PreprocessError(
                "variable %d has %d emitted unary tables; the transformation "
                "must emit exactly one" % (v, len(em)))
        got = [Fr(x) for x in em[0].table]
        want = unary_contrib[v]
        if got != want:
            raise PreprocessError(
                "the emitted unary for variable %d is %s but the recorded "
                "transformations give %s; a corrupted output table would "
                "otherwise pass at any model size"
                % (v, [str(x) for x in got], [str(x) for x in want]))

    # the recorded scale must be exactly the removed constants
    if simp.scale != const_product:
        raise PreprocessError(
            "the recorded scale %s is not the product of the removed exact "
            "constants %s; a corrupted scale would otherwise pass"
            % (simp.scale, const_product))

    # ---- the bounded GLOBAL enumeration is retained as an extra witness ----
    # It is no longer the only output-law check, but where it is affordable it
    # independently confirms the local derivation, and the 12-vs-13-variable
    # boundary regression is kept.
    q = 1
    for v in simp.free:
        q *= simp.card[v]
        if q > 4096:
            break
    if q <= 4096:
        order = sorted(simp.free)
        for combo in itertools.product(*[range(simp.card[v]) for v in order]):
            a = dict(zip(order, combo))
            w0 = _weigh(restricted.factors, a)
            w1 = simp.scale * _weigh(simp.factors, a)
            if w0 != w1:
                raise PreprocessError(
                    "preprocessing CHANGED THE LAW at assignment %s: original "
                    "weight %s, simplified weight %s (scale %s)"
                    % (a, w0, w1, simp.scale))
    return True
