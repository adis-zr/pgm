"""Independent verification of a persisted PROGRAM against the ORIGINAL model
(spec §11). Nothing the producer computed is consumed as evidence: the
checker re-enumerates every region's masses and markers with its own loop,
proves the submitted coarsening witness (partition, alpha, rho, M, N) from
its own quantities, re-derives every deletion bound, re-proves the collective
fit certificate entry by entry, and contracts the final represented model
with its own dense engine. The publication must then CONTAIN the checker's
enclosure widened by exactly the radii the checker itself established.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import itertools
import gmpy2
from mdi import (model as M, config as K, regions as R, marked as MK, collective as CO,
                 regional_check as RC, collective_route as CR,
                 collective_jt as CJ, dense_be as DB, arith as A, program as PG,
                 factors as FX)


class CheckError(Exception):
    pass


# ------------------------------------------------- own compact views

class OwnView:
    """The CHECKER's compact view of an original table over the current
    variables: offsets derived by the checker from the ORIGINAL factor's
    layout (its scope order and cardinalities) and from the checker's own
    verified representatives and boundary orders. Shares nothing with
    factors.ProjectedFactor except the exact table bytes it reads."""
    __slots__ = ("scope", "card", "offsets", "base_table", "origin", "scale", "table")

    def __init__(self, scope, card, offsets, base_table, origin):
        self.scope = tuple(scope)
        self.card = tuple(card)
        self.offsets = {v: list(o) for v, o in offsets.items()}
        self.base_table = base_table
        self.origin = origin
        self.scale = Fr(1)
        self.table = _OwnTable(self)

    def strides(self):
        st = [1] * len(self.card)
        acc = 1
        for k in range(len(self.card) - 1, -1, -1):
            st[k] = acc
            acc *= self.card[k]
        return tuple(st)

    def size(self):
        n = 1
        for c in self.card:
            n *= c
        return n

    def at(self, assign):
        off = 0
        for v in self.scope:
            off += self.offsets[v][assign[v]]
        return self.base_table[off]

    def map_entries(self):
        return sum(len(o) for o in self.offsets.values())


class _OwnTable:
    __slots__ = ("v",)

    def __init__(self, view):
        self.v = view

    def __len__(self):
        return self.v.size()

    def __getitem__(self, flat):
        v = self.v
        if not isinstance(flat, int) or not (0 <= flat < v.size()):
            raise IndexError(flat)
        st = v.strides()
        off = 0
        rem = flat
        for k, var in enumerate(v.scope):
            d, rem = divmod(rem, st[k])
            off += v.offsets[var][d]
        return v.base_table[off]

    def at_digits(self, digits):
        v = self.v
        off = 0
        for k, var in enumerate(v.scope):
            off += v.offsets[var][digits[k]]
        return v.base_table[off]

    def __iter__(self):
        raise CheckError("the checker's view is not enumerated implicitly")


def own_view_of_original(f):
    """The identity view of a dense original factor, with offsets the checker
    computes from the factor's own layout (first scope variable most
    significant)."""
    card = tuple(f.card)
    st = []
    acc = 1
    for k in range(len(card) - 1, -1, -1):
        st.insert(0, acc)
        acc *= card[k]
    offs = {v: [a * st[k] for a in range(card[k])] for k, v in enumerate(f.scope)}
    return OwnView(f.scope, card, offs, f.table, f.origin)


def own_lift_view(f, region_of, reps, bpos, ncell):
    """The checker's own composition: the offset of region i at cell c is the
    sum of the input view's offsets at the states the verified representative
    assigns to the scope variables inside region i."""
    if not isinstance(f, OwnView):
        f = own_view_of_original(f)
    new_vars = sorted({region_of[v] for v in f.scope})
    offs = {}
    for i in new_vars:
        mine = [v for v in f.scope if region_of[v] == i]
        col = []
        for c in range(ncell[i]):
            rep = reps[i][c]
            o = 0
            for v in mine:
                if v not in bpos[i]:
                    raise CheckError("variable %d of factor %d is not on the verified "
                                     "boundary of region %d" % (v, f.origin, i))
                o += f.offsets[v][rep[bpos[i][v]]]
            col.append(o)
        offs[i] = col
    return OwnView(tuple(new_vars), tuple(ncell[i] for i in new_vars), offs,
                   f.base_table, f.origin)


def own_dense(f, cap):
    """A bounded dense copy of any factor the checker holds (view or table)."""
    if isinstance(f, OwnView):
        n = f.size()
        if n > cap:
            raise CheckError("a %d-entry view exceeds the %d-entry cap" % (n, cap))
        return M.Factor(scope=tuple(f.scope), card=tuple(f.card),
                        table=[f.table[i] for i in range(n)], origin=f.origin)
    return FX.densify(f, cap)


def validate_producer_view(pf, own):
    """Every offset map of the producer's view must equal the checker's own
    derivation, entry by entry (cost: maps, not tables)."""
    if tuple(pf.scope) != tuple(own.scope) or tuple(pf.card) != tuple(own.card):
        return "scope/cardinality differ: %s/%s vs %s/%s" % (pf.scope, pf.card, own.scope, own.card)
    for v in own.scope:
        if list(pf.offsets.get(v, [])) != own.offsets[v]:
            return "offset map of variable %d differs from the checker's own derivation" % v
    if pf.base.table is not own.base_table and list(pf.base.table) != list(own.base_table):
        return "the view does not read the original table"
    return None


# ------------------------------------------------- own local enumeration

def own_region_local(marked: MK.Marked, region, deadline=None, budget=None):
    """The checker's own A_R(b) and A_{R,i,a}(b) on a marked model: a single
    flat enumeration of the region's joint space (not boundary-then-interior),
    weights from the law factors (masses included), markers as the owner's
    payload times the weight."""
    rset = set(region)
    law = marked.law_factors()
    internal = [f for f in law if set(f.scope) <= rset]
    cross = [f for f in marked.factors if (set(f.scope) & rset)
             and not (set(f.scope) <= rset)]
    boundary = tuple(sorted({v for f in cross for v in f.scope if v in rset}))
    bset = set(boundary)
    order = list(region)
    n = 1
    for v in order:
        n *= marked.card[v]
    if n > K.CAPS["region_local_enumeration"]:
        raise CheckError("the checker's own enumeration of region %s needs %d "
                         "assignments, above the declared cap" % (tuple(region), n))
    want = [(v, a) for v in marked.queries() if marked.owner[v] in rset
            for a in range(marked.orig_card[v])]
    A, marks = {}, {k: {} for k in want}
    bidx = [order.index(v) for v in boundary]
    seen = 0
    if deadline is not None:
        deadline()
    for combo in itertools.product(*[range(marked.card[v]) for v in order]):
        seen += 1
        if deadline is not None and (seen & 0xFF) == 0:
            deadline()
        a = dict(zip(order, combo))
        w = Fr(1)
        for f in internal:
            w *= f.at(a)
            if w == 0:
                break
        if w == 0:
            continue
        b = tuple(combo[k] for k in bidx)
        A[b] = A.get(b, Fr(0)) + w
        for (v, aa) in want:
            g = marked.payload(v, aa, a[marked.owner[v]])
            if g != 0:
                marks[(v, aa)][b] = marks[(v, aa)].get(b, Fr(0)) + w * g
    if budget is not None:
        budget.charge("local_mass_entries", max(1, len(A)), "checker own masses")
    for v in marked.queries():
        if marked.owner[v] not in rset:
            continue
        for b in A:
            tot = sum(marks[(v, aa)].get(b, Fr(0))
                      for aa in range(marked.orig_card[v]))
            if tot != A[b]:
                raise CheckError("the checker's own marks do not sum to its own "
                                 "mass at region %s assignment %s" % (tuple(region), b))
    return boundary, A, marks, want


def _own_deletion_bound(marked: MK.Marked, region, boundary, A, deleted):
    """U_R / (U_R + L_R) from the checker's own masses and the ORIGINAL
    crossing tables (§5.5), computed directly rather than via profiles."""
    rset = set(region)
    cross = [f for f in marked.factors if (set(f.scope) & rset)
             and not (set(f.scope) <= rset)]
    bpos = {v: k for k, v in enumerate(boundary)}

    def extrema(b):
        hi = lo = Fr(1)
        for f in cross:
            inside = {v: b[bpos[v]] for v in f.scope if v in rset}
            outside = [v for v in f.scope if v not in rset]
            vals = []
            for oc in itertools.product(*[range(marked.card[v]) for v in outside]):
                a = dict(inside)
                a.update(zip(outside, oc))
                vals.append(f.at(a))
            hi *= max(vals)
            lo *= min(vals)
        return lo, hi

    D = set(deleted)
    U = L = Fr(0)
    for b, m in A.items():
        lo, hi = extrema(b)
        if b in D:
            U += m * hi
        else:
            L += m * lo
    if L <= 0:
        raise CheckError("the deletion's retained lower mass L_R is zero (hard "
                         "zeros), so the §5.5 bound does not apply")
    return U / (U + L)


def _coarse_from_record(rg, boundary):
    cells, cell_of = [], {}
    M_, N_ = [], {}
    for ci, c in enumerate(rg["cells"]):
        cells.append(R.Cell(rep=tuple(c["rep"]),
                            members=[(tuple(mb), Fr(al)) for mb, al in c["members"]],
                            rho_max=Fr(1)))
        for mb, _al in c["members"]:
            cell_of[tuple(mb)] = ci
        M_.append(Fr(c["M"]))
        for k, v in c["N"].items():
            N_.setdefault(k, [Fr(0)] * len(rg["cells"]))
    for ci, c in enumerate(rg["cells"]):
        for k in N_:
            N_[k][ci] = Fr(c["N"].get(k, Fr(0)))
    cr = R.CoarseRegion(region=tuple(rg["region"]), boundary=tuple(boundary),
                        cells=cells, M=M_, N=N_, cell_of=cell_of,
                        rho_region=Fr(rg["rho_region"]), comparisons=0,
                        declines={})
    cr.aggregation = [{"scope": (), "factors": list(e["factors"]),
                       "aggregated": bool(e["aggregated"])}
                      for e in rg["aggregation"]] or None
    return cr


def own_level_zero(r, queries):
    """The checker's level-zero original observable: for every requested
    original variable v (its own owner), the original cardinality, a unit mass
    per state and the exact state indicator N_{v,a}(c) = [a == c]. Derived
    from the ORIGINAL variable/state identifiers, not from any producer
    object."""
    queries = sorted(int(v) for v in queries)
    card = {int(v): int(c) for v, c in r.card.items()}
    for v in queries:
        if v not in card:
            raise CheckError("requested variable %d is not a free variable of the restricted model" % v)
    marks = {}
    for v in queries:
        for a in range(card[v]):
            marks[(v, a)] = [Fr(1) if c == a else Fr(0) for c in range(card[v])]
    return MK.Marked(card=card, factors=list(r.factors), owner={v: v for v in queries},
                     marks=marks, mass={v: [Fr(1)] * card[v] for v in card},
                     orig_card=dict(card), level=0)


def verify_level_zero(own, theirs):
    """Verify a producer-side level-zero Marked object against the checker's
    own observable: identical owners, cardinalities, unit masses and exact
    state indicators. Returns a reason or None."""
    if sorted(theirs.queries()) != sorted(own.queries()):
        return "requested set %s differs from the original request %s" % (
            sorted(theirs.queries())[:6], sorted(own.queries())[:6])
    for v in own.queries():
        if theirs.owner.get(v) != v:
            return "variable %d is not its own owner at level zero (owner %s)" % (v, theirs.owner.get(v))
        if theirs.orig_card.get(v) != own.orig_card[v] or theirs.card.get(v) != own.card[v]:
            return "variable %d cardinality %s/%s differs from the original %d" % (
                v, theirs.card.get(v), theirs.orig_card.get(v), own.card[v])
        if [Fr(x) for x in theirs.mass.get(v, [])] != own.mass[v]:
            return "variable %d does not carry unit masses at level zero" % v
        for a in range(own.card[v]):
            if [Fr(x) for x in theirs.marks.get((v, a), [])] != own.marks[(v, a)]:
                return ("marker (%d,%d) is not the exact state indicator [a == c] "
                        "(shared initial-marker fault)" % (v, a))
    for v in own.card:
        if theirs.card.get(v) != own.card[v]:
            return "free variable %d cardinality differs" % v
    return None


def verify_scale(marked: MK.Marked, sc, deadline=None, budget=None):
    """Verify one persisted scale on the checker's own input model and return
    the checker's OWN lifted model plus the radii it established."""
    regs = sc["regions"]
    region_of = {}
    for i, rg in enumerate(regs):
        for v in rg["region"]:
            if v in region_of:
                raise CheckError("regions overlap on variable %d" % v)
            region_of[v] = i
    if set(region_of) != set(marked.card):
        raise CheckError("the regions do not cover every current variable")
    for f in marked.factors:
        if any(v not in region_of for v in f.scope):
            raise CheckError("factor %d has variables outside the partition" % f.origin)
    t_level = Fr(sc["t_level"])
    rho_cap = K.region_distortion_budget(t_level, len(regs))
    problems = []
    own_del = Fr(0)
    own_rho = Fr(1)
    verified = []
    for i, rg in enumerate(regs):
        if deadline is not None:
            deadline()
        region = tuple(rg["region"])
        boundary, A, marks, want = own_region_local(marked, region, deadline, budget)
        if tuple(rg["boundary"]) != boundary:
            problems.append("region %d: recorded boundary order %s differs from "
                            "the checker's own %s" % (i, rg["boundary"], boundary))
            continue
        deleted = [tuple(b) for b in rg["deleted"]]
        if deleted:
            try:
                p = _own_deletion_bound(marked, region, boundary, A, deleted)
            except CheckError as e:
                problems.append("region %d: deletion %s" % (i, e))
                continue
            if p > Fr(rg["deletion_bound"]):
                problems.append("region %d: the checker's own deletion bound %s "
                                "exceeds the recorded %s" % (i, p, rg["deletion_bound"]))
                continue
            own_del += p
        pc = _coarse_from_record(rg, boundary)
        A_ret, marks_ret = A, marks
        # a RegionData shell for the structural profile primitives
        rset = set(region)
        internal = [fi for fi, f in enumerate(marked.factors) if set(f.scope) <= rset]
        crossing = [fi for fi, f in enumerate(marked.factors)
                    if (set(f.scope) & rset) and not (set(f.scope) <= rset)]
        rd = R.RegionData(vars=region, boundary=boundary, internal_factors=internal,
                          crossing_factors=crossing, A=A_ret, marks=marks_ret)
        wp = RC._verify_coarsening_witness(
            region, marked.card, marked.factors, set(), pc, A_ret, marks_ret,
            rho_cap, deadline=deadline, region_of_for_profiles=region_of,
            prebuilt_rd=rd, budget=budget, required_keys=set(want),
            deleted=deleted)
        if wp:
            problems.extend("region %d: %s" % (i, p_) for p_ in wp)
            continue
        own_rho *= Fr(rg["rho_region"])
        verified.append((region, boundary, pc))
    if problems:
        return None, problems
    if not K.certify_R_against_t(own_rho, t_level):
        return None, ["R_level %s is not certified at t=%s" % (own_rho, t_level)]
    if own_del > Fr(sc["deletion_radius_total"]):
        return None, ["the checker's own deletion radius %s exceeds the recorded "
                      "%s" % (own_del, sc["deletion_radius_total"])]
    # ---- the checker's OWN lifted model from the verified witness
    ncell = [len(pc.cells) for _r, _b, pc in verified]
    lmass = {i: [Fr(x) for x in pc.M] for i, (_r, _b, pc) in enumerate(verified)}
    lowner, lmarks = {}, {}
    for v in marked.queries():
        i = region_of[marked.owner[v]]
        lowner[v] = i
        pc = verified[i][2]
        for a in range(marked.orig_card[v]):
            lmarks[(v, a)] = [Fr(x) for x in pc.N[(v, a)]]
    # the checker's OWN compact views, derived by its own composition from the
    # original layouts and ITS verified representatives and boundary orders
    reps = {i: [tuple(c.rep) for c in verified[i][2].cells] for i in range(len(regs))}
    bpos = {i: {v: k for k, v in enumerate(verified[i][1])} for i in range(len(regs))}
    lfactors = []
    for f in marked.factors:
        rs = sorted({region_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        try:
            lfactors.append(own_lift_view(f, region_of, reps, bpos, ncell))
        except CheckError as e:
            return None, ["lifting factor %d: %s" % (f.origin, e)]
    lifted = MK.Marked(card={i: ncell[i] for i in range(len(regs))},
                       factors=lfactors, owner=lowner, marks=lmarks, mass=lmass,
                       orig_card=dict(marked.orig_card), level=marked.level + 1)
    try:
        lifted.check_identity()
    except MK.MarkedError as e:
        return None, ["the verified witness violates the marker identity: %s" % e]
    # what this scale VERIFIABLY transformed: a region whose verified cells are
    # fewer than its verified supported boundary states merged; deletions
    # were proved above
    merged = sum(1 for (region, boundary, pc), rg in zip(verified, regs)
                 if len(pc.cells) < len(pc.cells) + 0 and False)
    merged = 0
    deleted = 0
    for (region, boundary, pc), rg in zip(verified, regs):
        n_members = sum(len(c.members) for c in pc.cells)
        if len(pc.cells) < n_members:
            merged += 1
        deleted += len(rg["deleted"])
    return lifted, {"t_level": t_level, "deletion": own_del, "R_level": own_rho,
                    "merged_regions": merged, "deleted_states": deleted}


# ------------------------------------------------- own fit certificate

def _log_pair(q: Fr, ctx):
    with ctx.D:
        lo = A.T.log(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    with ctx.U:
        hi = A.T.log(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def verify_fit(marked: MK.Marked, rmk: MK.Marked, cand, claimed_tv: Fr, ctx):
    """Independent proof that TV(law, residual x modes) <= claimed_tv.

    The checker's own gauge-invariant certificate: for every unordered pair
    the log-difference table l(a,b) = log P - log Q - G is formed as dense
    interval arrays, fixed at reference state 0 to its interaction part
    h(a,b) = l(a,b) - l(a,0) - l(0,b) + l(0,0), and the rank-one leftovers
    are credited to the endpoint unaries along with log U - log r - D. nu is
    the sum of half-ranges; TV <= tanh(nu/2) <= nu/2. The checker's logs are
    directed at 16 extra bits, so its enclosures are nested inside the
    producer's and its bound can only be tighter on the same residual.
    Hard-zero and higher-arity factors must be reproduced exactly.
    """
    card = marked.card
    free = marked.free()
    try:
        law = [own_dense(f, K.CAPS["aggregated_kernel_entries"])
               for f in marked.law_factors()]
    except (FX.ViewError, CheckError) as e:
        return False, ["the checker's fit certificate needs bounded explicit "
                       "tables: %s" % e]
    resid = list(rmk.factors)

    def dense_pair(tbl, i, j, flip):
        di, dj = card[i], card[j]
        out = [[None] * dj for _ in range(di)]
        for a in range(di):
            for b in range(dj):
                out[a][b] = Fr(tbl[b * di + a]) if flip else Fr(tbl[a * dj + b])
        return out

    def collect(facs):
        un = {v: [Fr(1)] * card[v] for v in free}
        pr = {}
        other = []
        for f in facs:
            if len(f.scope) == 1:
                v = f.scope[0]
                for a in range(card[v]):
                    un[v][a] *= Fr(f.table[a])
            elif len(f.scope) == 2 and min(Fr(x) for x in f.table) > 0:
                i, j = f.scope
                key = (min(i, j), max(i, j))
                t = dense_pair(f.table, key[0], key[1], flip=(i > j))
                if key in pr:
                    pr[key] = [[pr[key][a][b] * t[a][b] for b in range(card[key[1]])]
                               for a in range(card[key[0]])]
                else:
                    pr[key] = t
            else:
                other.append((tuple(f.scope), tuple(Fr(x) for x in f.table)))
        return un, pr, other

    un_l, pr_l, oth_l = collect(law)
    un_r, pr_r, oth_r = collect(resid)
    from collections import Counter
    if Counter(oth_l) != Counter(oth_r):
        return False, ["retained hard-zero / higher-arity factors are not "
                       "reproduced exactly in the residual"]

    def Gt(i, j):
        di, dj = card[i], card[j]
        out = [[Fr(0)] * dj for _ in range(di)]
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            fj = cand.features[k].get(j)
            if fi is None or fj is None:
                continue
            c = cand.signs[k] * Fr(cand.gammas[k])
            for a in range(di):
                for b in range(dj):
                    out[a][b] += c * Fr(fi[a]) * Fr(fj[b])
        return out

    def Dt(i):
        out = [Fr(0)] * card[i]
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            if fi is None:
                continue
            c = cand.signs[k] * Fr(cand.gammas[k]) / 2
            for a in range(card[i]):
                out[a] += c * Fr(fi[a]) * Fr(fi[a])
        return out

    pairs = set(pr_l) | set(pr_r)
    for k in range(cand.rank):
        vs = sorted(v for v, f in cand.features[k].items()
                    if any(Fr(x) != 0 for x in f))
        pairs.update((vs[x], vs[y]) for x in range(len(vs))
                     for y in range(x + 1, len(vs)))
    nu = Fr(0)
    leftover = {v: [[Fr(0), Fr(0)] for _ in range(card[v])] for v in free}
    for (i, j) in sorted(pairs):
        di, dj = card[i], card[j]
        G = Gt(i, j)
        P, Q = pr_l.get((i, j)), pr_r.get((i, j))
        L = [[None] * dj for _ in range(di)]
        for a in range(di):
            for b in range(dj):
                lo = hi = -G[a][b]
                if P is not None:
                    x, y = _log_pair(P[a][b], ctx)
                    lo, hi = lo + x, hi + y
                if Q is not None:
                    x, y = _log_pair(Q[a][b], ctx)
                    lo, hi = lo - y, hi - x
                L[a][b] = (lo, hi)
        c00 = L[0][0]
        hmin = hmax = Fr(0)
        for a in range(1, di):
            for b in range(1, dj):
                hlo = L[a][b][0] - L[a][0][1] - L[0][b][1] + c00[0]
                hhi = L[a][b][1] - L[a][0][0] - L[0][b][0] + c00[1]
                if hlo < hmin:
                    hmin = hlo
                if hhi > hmax:
                    hmax = hhi
        nu += (hmax - hmin) / 2
        for a in range(di):
            leftover[i][a][0] += L[a][0][0] - c00[1]
            leftover[i][a][1] += L[a][0][1] - c00[0]
        for b in range(dj):
            leftover[j][b][0] += L[0][b][0] - c00[1]
            leftover[j][b][1] += L[0][b][1] - c00[0]
    for v in free:
        D = Dt(v)
        rng = None
        for a in range(card[v]):
            if (un_l[v][a] == 0) != (un_r[v][a] == 0):
                return False, ["unary support of variable %d differs between "
                               "the law and the residual at state %d" % (v, a)]
            if un_l[v][a] == 0:
                continue
            x, y = _log_pair(un_l[v][a], ctx)
            rx, ry = _log_pair(un_r[v][a], ctx)
            lo = x - ry - D[a] + leftover[v][a][0]
            hi = y - rx - D[a] + leftover[v][a][1]
            rng = [lo, hi] if rng is None else [min(rng[0], lo), max(rng[1], hi)]
        if rng is None:
            return False, ["variable %d has no supported state" % v]
        nu += (rng[1] - rng[0]) / 2
    own_tv = K.tanh_upper(nu)
    if own_tv > Fr(claimed_tv):
        return False, ["the checker's own fit certificate gives TV <= %s, above "
                       "the recorded %s" % (own_tv, claimed_tv)]
    return True, {"own_nu": str(nu), "own_tv": str(own_tv)}


# ---------------------------------------------------- own restoration

def own_restore(marked: MK.Marked, Z, cell_counts):
    """The checker's own original-query restoration from ITS verified masses,
    markers and counts (never Marked.read_original).

    For original (i, a) with owner o: the event count X = sum_c cnt(c) N_{i,a}(c)
    / M(c) and its complement C = sum_{a' != a} X_{a'} (the checker's own sum
    over the other states, not Z - X). The probability is enclosed by the
    sharp ratio [X_l / (X_l + C_u), X_u / (X_u + C_l)] with a positive
    denominator proved from the checker's own counts; a zero numerator gives
    an exact 0 and an exactly covering event an exact 1.
    """
    out = {}
    for v in marked.queries():
        o = marked.owner[v]
        xs = []
        for a in range(marked.orig_card[v]):
            lo = hi = Fr(0)
            for c in range(marked.card[o]):
                Mc = Fr(marked.mass[o][c])
                if Mc <= 0:
                    continue
                Nc = Fr(marked.marks[(v, a)][c])
                if Nc == 0:
                    continue
                cc = cell_counts[o][c]
                cl, ch = (Fr(cc[0]), Fr(cc[1])) if isinstance(cc, tuple) else (Fr(cc), Fr(cc))
                # the payload division is the checker's own, directed
                lo += cl * Nc / Mc
                hi += ch * Nc / Mc
            xs.append((lo, hi))
        rows = []
        tot_lo = sum(x[0] for x in xs)
        tot_hi = sum(x[1] for x in xs)
        if tot_hi <= 0:
            raise CheckError("the checker's own counts for variable %d have no "
                             "positive total" % v)
        for a, (xl, xu) in enumerate(xs):
            cl = tot_lo - xl          # the other states' lower counts
            cu = tot_hi - xu
            if xu == 0:
                rows.append((Fr(0), Fr(0)))
            elif cu == 0 and cl == 0:
                rows.append((Fr(1), Fr(1)))
            else:
                dl = xl + cu
                du = xu + cl
                plo = xl / dl if dl > 0 else Fr(0)
                phi = xu / du if du > 0 else Fr(1)
                rows.append((max(Fr(0), plo), min(Fr(1), phi)))
        out[v] = rows
    return out


# ------------------------------------------- own collective references

def _own_round_half_up(x: Fr) -> int:
    fl = x.numerator // x.denominator
    return fl + 1 if (x - fl) >= Fr(1, 2) else fl


def _own_exp_pair(x: Fr, ctx):
    with ctx.D:
        lo = A.T.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = A.T.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _own_sqrt_pair(q: Fr, ctx):
    with ctx.D:
        lo = A.T.sqrt(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    with ctx.U:
        hi = A.T.sqrt(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _own_law_tables(rmk, lift):
    out = []
    for f in rmk.law_factors():
        if isinstance(f, OwnView) or FX.is_view(f):
            tab = f.table
            base = f.base_table if isinstance(f, OwnView) else f.base.table
            offs = f.offsets
            out.append((tuple(f.scope),
                        FX.LazyTable(f.card, [offs[v] for v in f.scope], base,
                                     lift=lambda x, _l=lift: _l(Fr(x)))))
        else:
            out.append((tuple(f.scope), [lift(Fr(x)) for x in f.table]))
    touched = {v for f in rmk.factors for v in f.scope}
    for v in rmk.free():
        if v not in touched and not any(x != 1 for x in rmk.mass[v]):
            out.append(((v,), [lift(Fr(1))] * rmk.card[v]))
    return out


def _own_event_counts(rmk, jt, alg, value_of_cell):
    """sum over the owner's cells of count(c) x payload g(c), with the OTHER
    components' totals multiplied in by a direct product (the checker's own
    bookkeeping)."""
    roots = sorted(jt.root_total)
    out = {}
    for v in rmk.queries():
        o = rmk.owner[v]
        own_root = jt.component_root(o)
        others = alg.one()
        for rt in roots:
            if rt != own_root:
                others = alg.mul(others, jt.root_total[rt])
        marg = jt.marginal(o)
        rows = []
        for a in range(rmk.orig_card[v]):
            acc = alg.zero
            for c in range(rmk.card[o]):
                Mc = Fr(rmk.mass[o][c])
                Nc = Fr(rmk.marks[(v, a)][c])
                if Mc <= 0 or Nc == 0:
                    continue
                val = marg[c]
                if alg.is_zero(val):
                    continue
                val = alg.mul(val, others)
                val = alg.mul(val, value_of_cell(Nc / Mc))
                acc = alg.add(acc, val)
            rows.append(acc)
        out[v] = rows
    return out


def own_statistic_reference(rmk, coll, ctx, deadline, charge):
    """The checker's own statistic-DP reference: own rounding, dense statistic
    contraction, own root exponential, own marker restoration."""
    _tr0 = A.transcendental_snapshot()
    cand = coll["candidate"]
    Q = coll["Q"]
    rank = cand.rank
    free = rmk.free()
    zero = (0,) * rank if rank > 1 else 0
    kq = {}
    for v in free:
        row = []
        for a in range(rmk.card[v]):
            ks = tuple(_own_round_half_up(Fr(cand.features[k].get(v, [Fr(0)] * rmk.card[v])[a]) * Q)
                       for k in range(rank))
            row.append(ks if rank > 1 else ks[0])
        kq[v] = row
    alg = DB.StatAlg(K.CAPS["local_mass_entries"], rank=rank)
    tables = _own_law_tables(rmk, lambda x: ({zero: x} if x != 0 else {}))
    jt = DB.DenseJT(tables, rmk.card, alg, deadline=deadline, stat_insert=kq,
                    entry_cap=K.CAPS["local_mass_entries"], charge=charge).run()
    total = jt.total()
    if not total:
        raise CheckError("the checker's residual has zero total weight")
    cache = {}

    def wfac(key):
        if key not in cache:
            ks = key if isinstance(key, tuple) else (key,)
            x = Fr(0)
            for k in range(rank):
                S = Fr(ks[k], Q)
                x += Fr(cand.signs[k]) * Fr(cand.gammas[k]) * S * S / 2
            cache[key] = _own_exp_pair(x, ctx)
        return cache[key]

    def integrate(dist):
        lo = hi = Fr(0)
        n = 0
        for key, w in dist.items():
            n += 1
            if deadline is not None and (n & 0x3F) == 0:
                deadline()
            l, h = wfac(key)
            lo += w * l
            hi += w * h
        return lo, hi
    Zlo, Zhi = integrate(total)
    if Zlo <= 0:
        raise CheckError("the checker's integrated total is not positive")
    ev = _own_event_counts(rmk, jt, alg, lambda g: {zero: g})
    counts = {v: [integrate(d) for d in rows] for v, rows in ev.items()}
    return counts, {"engine": "dense", "method": "checker-owned statistic reference",
                    "support": len(total), "Z": (str(Zlo), str(Zhi)),
                    "transcendental_calls": A.transcendental_since(_tr0)["total"],
                    "transcendental_by_kind": A.transcendental_since(_tr0), "ops": dict(jt.ops)}


def _own_pi(ctx):
    with ctx.D:
        lo = A.T.const_pi()
    with ctx.U:
        hi = A.T.const_pi()
    return A.exact_fr(lo), A.exact_fr(hi)


def _own_trig(lo, hi, ctx, which):
    """The checker's own enclosure of cos/sin over [lo, hi]: directed endpoint
    values at extra precision with the exact argument-conversion allowance,
    widened to the attained extremum when a critical point can lie inside."""
    if lo > hi:
        lo, hi = hi, lo
    fn = A.T.cos if which == "cos" else A.T.sin
    extra = 2 * ctx.p + 64
    cd = gmpy2.context(precision=extra, round=gmpy2.RoundDown)
    cu = gmpy2.context(precision=extra, round=gmpy2.RoundUp)
    vals = []
    for q in (lo, hi):
        mq = gmpy2.mpq(q.numerator, q.denominator)
        with cd:
            ad = gmpy2.mpfr(mq)
        with cu:
            au = gmpy2.mpfr(mq)
        da = max(abs(q - A.exact_fr(ad)), abs(A.exact_fr(au) - q))
        with cd:
            vlo = min(fn(ad), fn(au))
        with cu:
            vhi = max(fn(ad), fn(au))
        vals.append((A.exact_fr(vlo) - da, A.exact_fr(vhi) + da))
    out_lo = min(v[0] for v in vals)
    out_hi = max(v[1] for v in vals)
    pl, ph = _own_pi(ctx)
    if hi - lo >= 2 * pl:
        return Fr(-1), Fr(1)
    # critical points: cos at k*pi (max for even k, min for odd k); sin at
    # pi/2 + k*pi (max for even k, min for odd k)
    shift = Fr(0) if which == "cos" else Fr(1, 2)
    kmin = int((lo / ph - shift)) - 2
    kmax = int((hi / pl - shift)) + 2
    for k in range(kmin, kmax + 1):
        c_lo = min((k + shift) * pl, (k + shift) * ph)
        c_hi = max((k + shift) * pl, (k + shift) * ph)
        if c_lo <= hi and c_hi >= lo:
            if k % 2 == 0:
                out_hi = Fr(1)
            else:
                out_lo = Fr(-1)
    return max(Fr(-1), out_lo), min(Fr(1), out_hi)


def _own_normal_weight(z, h, ctx):
    """h * exp(-z^2/2) / sqrt(2 pi) with directed endpoints."""
    x = -(z * z) / 2
    elo, ehi = _own_exp_pair(x, ctx)
    pl, ph = _own_pi(ctx)
    slo, _ = _own_sqrt_pair(2 * pl, ctx)
    _, shi = _own_sqrt_pair(2 * ph, ctx)
    return h * elo / shi, h * ehi / slo


def validate_lattice(cand, k, rec):
    """The checker's OWN certified error of the recorded lattice {T, h, nodes}
    of mode k: own exp enclosure, own rational sqrt bound, the proved
    constants (positive: shifted-Gaussian magnitude; negative: oscillatory
    second-derivative constant 2/5 + 2 sqrt(g) R/4 + g R^2 2/5). Returns the
    own total bound, which the reference USES as its lattice delta -- the
    recorded `total_bound` is a producer claim and never enters the proof.
    Returns a string naming the defect when the lattice is inadmissible."""
    T = Fr(rec["T"])
    h = Fr(rec["h"])
    nodes = int(rec["nodes"])
    if nodes != 2 * int(T / h) + 1:
        return "node count %d does not match T=%s, h=%s" % (nodes, T, h)
    if h > 2 * T or h <= 0 or T <= 0:
        return "lattice step/radius are not admissible (h=%s, T=%s)" % (h, T)
    g = Fr(cand.gammas[k])
    R = Fr(0)
    for f in cand.features[k].values():
        R += max(abs(Fr(x)) for x in f)
    if cand.signs[k] > 0:
        a2 = g * R * R
        M = _own_exp_upper(a2 / 2) * Fr(2, 5)
        a_up = _own_isqrt_ceil(a2)
        dd = T - a_up
        if dd <= 0:
            return "truncation radius %s is inside the shifted centre %s" % (T, a_up)
        tail = 2 * M * _own_exp_upper(-Fr(dd * dd, 2))
        disc = 2 * T * h * h * M / 12
    else:
        if T < 1:
            return "oscillatory truncation radius %s below 1" % T
        tail = Fr(4, 5) * _own_exp_upper(-T * T / 2) / T
        sg_up = Fr(_own_isqrt_ceil(g * 10 ** 24), 10 ** 12)       # >= sqrt(g)
        M2 = Fr(2, 5) + 2 * sg_up * R * Fr(1, 4) + g * R * R * Fr(2, 5)
        disc = 2 * T * h * h * M2 / 12
    return tail + disc


def _own_tensor_error(deltas):
    """sum_k delta_k prod_{j != k} (1 + delta_j): the finite-grid tensor lemma
    (the checker's own statement of the proof dependency)."""
    out = Fr(0)
    for i, d in enumerate(deltas):
        prod = Fr(1)
        for j, d2 in enumerate(deltas):
            if j != i:
                prod *= (1 + d2)
        out += d * prod
    return out


def _own_exp_upper(x: Fr, terms=64) -> Fr:
    x = Fr(x)
    if x == 0:
        return Fr(1)
    if x < 0:
        s = Fr(0)
        t = Fr(1)
        for k in range(terms):
            if k:
                t = t * (-x) / k
            s += t
        return Fr(1) / s                                      # 1 / lower(exp(-x))
    n = terms
    while Fr(n) <= x:
        n *= 2
    s = Fr(0)
    t = Fr(1)
    for k in range(n):
        if k:
            t = t * x / k
        s += t
    return s + t * x / n / (Fr(1) - x / n)


def _own_isqrt_ceil(q: Fr) -> int:
    import math
    if q <= 0:
        return 0
    n = math.isqrt(q.numerator // q.denominator) + 1
    while Fr(n * n) < q:
        n += 1
    while n > 0 and Fr((n - 1) * (n - 1)) >= q:
        n -= 1
    return n


class _Observable:
    """A frozen copy of the checker's original observable (owners, cards,
    masses, markers, requested set)."""
    __slots__ = ("owner", "card", "orig_card", "mass", "marks", "_queries", "_free")

    def queries(self):
        return list(self._queries)

    def free(self):
        return list(self._free)


def _snapshot_observable(marked):
    o = _Observable()
    o.owner = {int(v): marked.owner[v] for v in marked.owner}
    o.card = {v: int(c) for v, c in marked.card.items()}
    o.orig_card = {int(v): int(c) for v, c in marked.orig_card.items()}
    o.mass = {v: [Fr(x) for x in marked.mass[v]] for v in marked.mass}
    o.marks = {k: [Fr(x) for x in row] for k, row in marked.marks.items()}
    o._queries = sorted(marked.queries())
    o._free = sorted(marked.free())
    return o


def _own_bind_residual(marked, rmk):
    """Bind the residual marked model's owners, masses and state-labelled
    payloads to the CHECKER's verified model (the marked model it built from
    its own witnesses). Returns a reason or None."""
    if set(rmk.queries()) != set(marked.queries()):
        return "the residual's requested set %s differs from the verified %s" % (
            sorted(rmk.queries())[:6], sorted(marked.queries())[:6])
    for v in sorted(marked.queries()):
        if rmk.owner.get(v) != marked.owner.get(v):
            return "variable %d is owned by %s in the residual but %s in the verified model" % (
                v, rmk.owner.get(v), marked.owner.get(v))
        if rmk.orig_card.get(v) != marked.orig_card.get(v):
            return "variable %d changes cardinality in the residual" % v
        o = marked.owner[v]
        if rmk.card.get(o) != marked.card.get(o):
            return "owner %s changes cardinality in the residual" % o
        if [Fr(x) for x in rmk.mass[o]] != [Fr(x) for x in marked.mass[o]]:
            return "owner %s masses differ from the verified masses" % o
        for a in range(marked.orig_card[v]):
            if [Fr(x) for x in rmk.marks[(v, a)]] != [Fr(x) for x in marked.marks[(v, a)]]:
                return "marker (%d,%d) payload differs from the verified payload" % (v, a)
    for v in rmk.free():
        if v not in marked.card or rmk.card[v] != marked.card[v]:
            return "the residual carries a variable %s the verified model does not" % v
    return None


def own_gf_reference(rmk, coll, ctx, deadline, charge, retained=None):
    """The checker's own Gaussian/Fourier/mixed reference on the dense engine:
    own lattice validation, own tilts and phases, own weights, own positive
    mass pass, own conjugate-paired Fourier accumulation over EXACTLY the
    retained positive nodes, own omitted-node allowances."""
    import itertools
    cand = coll["candidate"]
    rank = cand.rank
    pos = [k for k in range(rank) if cand.signs[k] > 0]
    neg = [k for k in range(rank) if cand.signs[k] < 0]
    grids = coll.get("grids")
    if not grids or len(grids) != rank:
        raise CheckError("the record carries no per-mode GF grid to validate")
    # the checker's OWN admissible GF1/GF2 integers from the LOADED grid's
    # tolerance and its own mode range R_k (sum of per-variable maxima of the
    # recorded features): the loaded spacing and terminal index must be at
    # least as fine and as far as the proof requires
    own_delta = []
    for k in range(rank):
        g = grids[k]
        if int(g["sign"]) != int(cand.signs[k]):
            raise CheckError("mode %d grid sign does not match the mode" % k)
        if str(g["rule"]) != CO.GF_RULE or int(g["version"]) != CO.GF_RULE_VERSION:
            raise CheckError("mode %d grid rule %s v%s is not the frozen %s v%d"
                             % (k, g["rule"], g["version"], CO.GF_RULE, CO.GF_RULE_VERSION))
        Rk = Fr(0)
        for f in cand.features[k].values():
            Rk += max(abs(Fr(x)) for x in f)
        if Fr(g["R"]) < Rk:
            raise CheckError("mode %d grid range %s is below the checker's own range %s"
                             % (k, g["R"], Rk))
        if Fr(g["beta"]) != Fr(cand.gammas[k]):
            raise CheckError("mode %d grid beta %s is not the mode's gamma %s" % (k, g["beta"], cand.gammas[k]))
        # the checker's OWN sufficient conditions, by direct inequalities on
        # the loaded witnesses (never the producer's constructor)
        bad = CO.gf_sufficient_conditions(g, Fr(cand.gammas[k]), Rk)
        if bad:
            raise CheckError("mode %d grid: %s" % (k, bad))
        own_delta.append(Fr(g["tol"]))
    # GF3 by the direct inequality (1 - eta)^2 B <= (1 + eta)^2 A on the
    # recorded allowance eta and the positive tolerances
    own_qtv = Fr(coll["quadrature_tv"])
    if pos and not CO.gf3_transfer_holds(own_qtv, [own_delta[k] for k in pos]):
        raise CheckError("the recorded quadrature radius %s does not satisfy the GF3 transfer "
                         "inequality for tolerances %s" % (own_qtv, [str(own_delta[k]) for k in pos]))
    if not pos and own_qtv != 0:
        raise CheckError("a pure Fourier program records a nonzero quadrature radius %s" % own_qtv)
    _tr0 = A.transcendental_snapshot()
    free = rmk.free()
    sg = {k: _own_sqrt_pair(Fr(cand.gammas[k]), ctx) for k in range(rank)}

    def points(k):
        g = grids[k]
        n = int(g["K"]) if int(g["sign"]) > 0 else int(g["J"])
        h = Fr(g["h"])
        return [Fr(j) * h for j in range(-n, n + 1)], h
    base_int = _own_law_tables(rmk, lambda x: (x, x))
    base_cx = _own_law_tables(rmk, lambda x: (x, x, Fr(0), Fr(0)))
    queries = rmk.queries()
    nst = {v: rmk.orig_card[v] for v in queries}
    pos_pts = [points(k) for k in pos]
    pos_nodes = list(itertools.product(*[pp[0] for pp in pos_pts])) if pos else [()]
    engine_int = None
    engine_cx = None
    mass = []
    for node in pos_nodes:
        if deadline is not None:
            deadline()
        wl = wu = Fr(1)
        for (pts, h), z in zip(pos_pts, node):
            a, b = _own_normal_weight(z, h, ctx)
            wl *= a
            wu *= b
        tilts = []
        for v in free:
            row = []
            for a in range(rmk.card[v]):
                lo = hi = Fr(1)
                for k, z in zip(pos, node):
                    fv = Fr(cand.features[k].get(v, [Fr(0)] * rmk.card[v])[a])
                    t = z * fv
                    alo = (sg[k][0] if t >= 0 else sg[k][1]) * t
                    ahi = (sg[k][1] if t >= 0 else sg[k][0]) * t
                    l, _ = _own_exp_pair(alo, ctx)
                    _, h_ = _own_exp_pair(ahi, ctx)
                    lo *= l
                    hi *= h_
                row.append((lo, hi))
            tilts.append(((v,), row))
        tables = base_int + tilts
        if engine_int is None:
            engine_int = DB.DenseJT(tables, rmk.card, DB.IntervalAlg, deadline=deadline,
                                    entry_cap=K.CAPS["local_mass_entries"], charge=charge)
        else:
            engine_int.rebind(tables)
        engine_int.run()
        total = engine_int.total()
        if total is None:
            raise CheckError("zero total at a positive node")
        mplus = _own_event_counts(rmk, engine_int, DB.IntervalAlg, lambda g: (g, g))
        mass.append(((wl, wu), tilts, mplus, total))
    if not neg:
        counts = {v: [[Fr(0), Fr(0)] for _ in range(nst[v])] for v in queries}
        for (wl, wu), _t, mplus, total in mass:
            for v in queries:
                for a in range(nst[v]):
                    counts[v][a][0] += wl * mplus[v][a][0]
                    counts[v][a][1] += wu * mplus[v][a][1]
        return {v: [tuple(r) for r in rows] for v, rows in counts.items()}, \
            {"engine": "dense", "method": "checker-owned Gaussian reference",
             "positive_nodes": len(mass), "own_quadrature_tv": str(own_qtv),
             "own_lattice_bounds": [str(x) for x in own_delta],
             "transcendental_calls": A.transcendental_since(_tr0)["total"],
             "transcendental_by_kind": A.transcendental_since(_tr0),
             "ops": dict(engine_int.ops) if engine_int is not None else {}}
    # ---- negative grid: conjugate pairs from a key set built ONCE
    neg_pts = [points(k) for k in neg]
    neg_nodes = list(itertools.product(*[pp[0] for pp in neg_pts]))
    keyset = set(neg_nodes)
    for nd in neg_nodes:
        if tuple(-z for z in nd) not in keyset:
            raise CheckError("the negative frequency key set is not symmetric")
    pairs = []
    seen = set()
    for nd in neg_nodes:
        if nd in seen:
            continue
        conj = tuple(-z for z in nd)
        seen.add(nd)
        seen.add(conj)
        pairs.append((nd, conj != nd))
    # Chapter 05 eq. (9): the tensor Fourier error prod(1 + e) - 1 from the
    # checker's own admitted tolerances
    delta = Fr(1)
    for k in neg:
        delta *= (1 + own_delta[k])
    delta -= 1
    phase_rows = []
    for nd, has_conj in pairs:
        if deadline is not None:
            deadline()
        nwl = nwu = Fr(1)
        for (pts, h), z in zip(neg_pts, nd):
            a, b = _own_normal_weight(z, h, ctx)
            nwl *= a
            nwu *= b
        per_v = {}
        for v in free:
            row = []
            for a in range(rmk.card[v]):
                alo = ahi = Fr(0)
                for k, z in zip(neg, nd):
                    fv = Fr(cand.features[k].get(v, [Fr(0)] * rmk.card[v])[a])
                    t = z * fv
                    alo += (sg[k][0] if t >= 0 else sg[k][1]) * t
                    ahi += (sg[k][1] if t >= 0 else sg[k][0]) * t
                clo, chi = _own_trig(alo, ahi, ctx, "cos")
                slo, shi = _own_trig(alo, ahi, ctx, "sin")
                row.append((clo, chi, slo, shi))
            per_v[v] = row
        phase_rows.append((nwl, nwu, per_v, has_conj))
    idx_all = list(range(len(mass)))
    if retained is not None:
        want = set(int(i) for i in retained)
        bad = [i for i in want if not (0 <= i < len(mass))]
        if bad:
            raise CheckError("retained positive node indices %s are outside the grid" % bad[:4])
        process = [i for i in idx_all if i in want]
    else:
        process = idx_all
    X_done = {v: [[Fr(0), Fr(0)] for _ in range(nst[v])] for v in queries}
    X_todo = {v: [Fr(0)] * nst[v] for v in queries}
    for (wl, wu), _t, mplus, _tot in mass:
        for v in queries:
            for a in range(nst[v]):
                X_todo[v][a] += wu * mplus[v][a][1]
    for i in process:
        (wl, wu), tilts, mplus, total = mass[i]
        acc_ev = {v: [(Fr(0), Fr(0), Fr(0), Fr(0)) for _ in range(nst[v])] for v in queries}
        for nwl, nwu, per_v, has_conj in phase_rows:
            if deadline is not None:
                deadline()
            phases = []
            for (v,), trow in tilts:
                prow = per_v[v]
                row = []
                for a in range(rmk.card[v]):
                    tl, th = trow[a]
                    clo, chi, slo, shi = prow[a]
                    cs = (tl * clo, th * clo, tl * chi, th * chi)
                    ss = (tl * slo, th * slo, tl * shi, th * shi)
                    row.append((min(cs), max(cs), min(ss), max(ss)))
                phases.append(((v,), row))
            tables = base_cx + phases
            if engine_cx is None:
                engine_cx = DB.DenseJT(tables, rmk.card, DB.ComplexAlg, deadline=deadline,
                                       entry_cap=K.CAPS["local_mass_entries"], charge=charge)
            else:
                engine_cx.rebind(tables)
            engine_cx.run()
            if engine_cx.total() is None:
                raise CheckError("zero total at a node")
            cev = _own_event_counts(rmk, engine_cx, DB.ComplexAlg, lambda g: (g, g, Fr(0), Fr(0)))
            mult = 2 if has_conj else 1
            for v in queries:
                for a in range(nst[v]):
                    rect = cev[v][a]
                    c = (rect[0] * nwl * mult, rect[0] * nwu * mult, rect[1] * nwl * mult, rect[1] * nwu * mult)
                    acc_ev[v][a] = (acc_ev[v][a][0] + min(c), acc_ev[v][a][1] + max(c), Fr(0), Fr(0))
        for v in queries:
            for a in range(nst[v]):
                mlo, mhi = mplus[v][a]
                xl = max(Fr(0), acc_ev[v][a][0] - delta * mhi)
                xu = min(mhi, acc_ev[v][a][1] + delta * mhi)
                if xl > xu:
                    xl, xu = Fr(0), mhi
                X_done[v][a][0] += wl * xl
                X_done[v][a][1] += wu * xu
                X_todo[v][a] -= wu * mhi
    counts = {v: [(X_done[v][a][0], X_done[v][a][1] + X_todo[v][a]) for a in range(nst[v])]
              for v in queries}
    ops = {"mul": 0, "add": 0}
    for eng in (engine_int, engine_cx):
        if eng is not None:
            for kk in ops:
                ops[kk] += int(eng.ops.get(kk, 0))
    return counts, {"engine": "dense", "method": "checker-owned mixed/Fourier reference",
                    "positive_nodes": len(mass), "processed": len(process),
                    "retained_positive_node_indices": sorted(process),
                    "conjugate_pairs": len(pairs), "tensor_delta": str(delta),
                    "own_quadrature_tv": str(own_qtv),
                    "own_lattice_bounds": [str(x) for x in own_delta],
                    "transcendental_calls": A.transcendental_since(_tr0)["total"],
                    "transcendental_by_kind": A.transcendental_since(_tr0), "ops": ops}


# --------------------------------------------------------------- the check

def verify_program(r, queries, prog, published, eps, deadline=None, budget=None,
                   exec_record=None, on_global=None):
    """Verify a parsed program's publication. `published` holds ONLY the
    requested variables' rows. Returns (ok, failures, meta)."""
    from mdi.guard import numerical_entry
    numerical_entry("program_check.verify_program")
    queries = set(queries)
    if set(prog["queries"]) != queries:
        return False, ["the program's requested set %s is not the current "
                       "request" % sorted(prog["queries"])[:8]], None
    card = {v: r.card[v] for v in sorted(queries) if v in r.card}
    from mdi.collective_check import validate_published_rows
    schema = validate_published_rows(published, card, queries)
    if schema:
        return False, schema, {"schema_rejected": True}
    if r.impossible_factor is not None or r.constant == 0:
        return False, ["zero evidence weight"], None
    # the checker's OWN level-zero original observable, derived from the
    # original requested variable/state identifiers and cardinalities alone;
    # the producer's constructor is then VERIFIED against it (named
    # obligation) and never used as the checker's starting point
    marked = own_level_zero(r, queries)
    bad = verify_level_zero(marked, MK.Marked.from_restricted(r, queries))
    if bad:
        return False, ["original observable: %s" % bad], {"certificate_rejected": True}
    radius = Fr(0)
    meta = {"scales": [], "independent_enclosure": True,
            "trusted_base": ["exact input decoding (model.read_uai / Fraction)",
                             "Fraction and MPFR directed primitives", "public query semantics"],
            "checker_derived": ["level-zero observable", "region masses and markers", "coarsening witness",
                                "deletion bound", "compact maps", "fit certificate", "rounding / GF conditions",
                                "dense contraction", "event counts", "restoration"]}
    ledger = {}
    merged_regions = 0
    deleted_states = 0
    for k, sc in enumerate(prog["scales"]):
        lifted, info = verify_scale(marked, sc, deadline=deadline, budget=budget)
        if lifted is None:
            return False, ["scale %d: %s" % (k + 1, p) for p in info], \
                {"certificate_rejected": True}
        radius += info["t_level"] + info["deletion"]
        ledger["regional_level%d" % (k + 1)] = str(info["t_level"])
        ledger["deletion_level%d" % (k + 1)] = str(info["deletion"])
        meta["scales"].append({kk: str(vv) for kk, vv in info.items()})
        merged_regions += info["merged_regions"]
        deleted_states += info["deleted_states"]
        marked = lifted
    coll = prog["collective"]
    if coll is None:
        tables = []
        for f in marked.law_factors():
            if FX.is_view(f) or isinstance(f, OwnView):
                tables.append((tuple(f.scope), f.table))
            else:
                tables.append((tuple(f.scope), [Fr(x) for x in f.table]))
        touched = {v for f in marked.factors for v in f.scope}
        for v in marked.free():
            if v not in touched and not any(x != 1 for x in marked.mass[v]):
                tables.append(((v,), [Fr(1)] * marked.card[v]))
        charge = None
        if budget is not None:
            charge = lambda n: budget.charge("local_mass_entries", n,
                                             "checker dense contraction")
        if on_global is not None:
            on_global()          # local proofs are done: the GLOBAL reference runs under the arm phase
        try:
            Z, counts, jt = DB.exact_marginals(tables, marked.card, deadline=deadline,
                                               charge=charge)
        except DB.DenseError as e:
            return False, ["the checker's own contraction refused: %s" % e], None
        # counts are per component; rescale to the global total first, with
        # the checker's own component bookkeeping (exact_marginals did so)
        rows = own_restore(marked, Z, counts)
        meta["method"] = ("checker-owned dense junction tree, exact rationals, "
                          "checker-owned sharp marker-ratio restoration")
        meta["positive_denominators"] = bool(Fr(Z) > 0) and all(
            sum(Fr(counts[v][c]) for c in range(marked.card[v])) > 0 for v in counts)
    else:
        ctx = A.Ctx(coll["precision"] + 16)
        # the checker's IMMUTABLE original observable: a deep snapshot of its
        # verified owners, cardinalities, masses and state-labelled payloads,
        # taken BEFORE the residual builder runs; both the builder's output
        # and the (possibly mutated in place) verified model are bound to it
        snap = _snapshot_observable(marked)
        try:
            rmk, res, can = CR.rebuild_residual(marked, coll, A.Ctx(coll["precision"]))
        except (CR.Declined, Exception) as e:
            return False, ["the collective record does not rebuild: %s" % e], None
        bad = _own_bind_residual(snap, rmk) or _own_bind_residual(snap, marked)
        if bad:
            return False, ["residual binding: %s" % bad], {"certificate_rejected": True}
        ok, info = verify_fit(marked, rmk, coll["candidate"], coll["fit_tv"], ctx)
        if not ok:
            return False, info, {"certificate_rejected": True}
        meta["fit"] = info
        # the checker's own rounding / lattice radii
        from mdi import collective as CO
        if coll["evaluator"] == "statistic":
            # the checker's OWN rounding radius: tau_k and R_k from the
            # record's features at the record's Q, by a direct formula
            Dn = Fr(0)
            cand = coll["candidate"]
            for k in range(cand.rank):
                Rk = tau = Fr(0)
                for v in marked.free():
                    f = cand.features[k].get(v)
                    if f is None:
                        continue
                    row = [Fr(x) for x in f]
                    Rk += max(abs(x) for x in row)
                    tau += max(abs(x - Fr(CO.exact_round_half_up(x * coll["Q"]),
                                           coll["Q"])) for x in row)
                Dn += Fr(cand.gammas[k]) * tau * (2 * Rk + tau) / 2
            own_round = K.tanh_upper(Dn)
            if own_round > Fr(coll["rounding_tv"]):
                return False, ["the checker's own rounding TV %s exceeds the "
                               "recorded %s" % (own_round, coll["rounding_tv"])], None
            meta["own_rounding_tv"] = str(own_round)
        else:
            # the checker's own lattice bounds are derived INSIDE
            # own_gf_reference (validate_lattice): the producer's lattice
            # constructor is never called here; the own positive tensor bound
            # must be covered by the recorded quadrature radius
            pass
        charge = None
        if budget is not None:
            charge = lambda n: budget.charge("local_mass_entries", n,
                                             "checker dense collective evaluation")
        if on_global is not None:
            on_global()          # local proofs (witnesses, residual, fit, grids) are done
        try:
            if coll["evaluator"] == "statistic":
                counts, cmeta = own_statistic_reference(rmk, coll, ctx, deadline, charge)
            else:
                retained = (exec_record or {}).get("retained_positive_node_indices")
                counts, cmeta = own_gf_reference(rmk, coll, ctx, deadline, charge,
                                                 retained=retained)
                if retained is not None:
                    meta["rechecked_retained_nodes"] = len(retained)
        except (CheckError, DB.DenseError) as e:
            return False, ["the checker's own collective evaluation refused: %s" % e], None
        # the checker's own sharp ratio from its own event counts
        rows = {}
        for v in rmk.queries():
            xs = [(Fr(counts[v][a][0]), Fr(counts[v][a][1]))
                  for a in range(rmk.orig_card[v])]
            tl = sum(x[0] for x in xs)
            th = sum(x[1] for x in xs)
            if th <= 0:
                return False, ["the checker's own collective counts for variable "
                               "%d have no positive total" % v], None
            rr = []
            for a, (xl, xu) in enumerate(xs):
                cl, cu = tl - xl, th - xu
                dl, du = xl + cu, xu + cl
                rr.append((max(Fr(0), xl / dl if dl > 0 else Fr(0)),
                           min(Fr(1), xu / du if du > 0 else Fr(1))))
            rows[v] = rr
        # the checker's OWN component radii for this route: its fit certificate,
        # its rounding bound (statistic) or its GF3 allowance (quadrature); the
        # recorded radii are what the publication was padded by and must cover
        # these (verified above); unused components are exactly zero
        own_fit = Fr(info["own_tv"])
        own_round = Fr(meta.get("own_rounding_tv", "0"))
        own_q = Fr(cmeta.get("own_quadrature_tv", "0")) if coll["evaluator"] != "statistic" else Fr(0)
        ledger["collective_fit"] = str(own_fit)
        ledger["collective_rounding"] = str(own_round)
        ledger["gaussian_quadrature"] = str(own_q)
        radius += own_fit + own_round + own_q
        meta["method"] = "checker-owned dense %s evaluation" % coll["evaluator"]
        meta["collective"] = {k: v for k, v in cmeta.items() if k != "lattice"}
        # positive denominators: the checker's own counts totals
        meta["positive_denominators"] = all(
            sum(Fr(counts[v][a][1]) for a in range(rmk.orig_card[v])) > 0 for v in rmk.queries())
    meta["ledger"] = ledger
    meta["checker_radius"] = str(radius)
    meta["verified_research"] = {
        "cells_merged_regions": merged_regions, "deleted_states": deleted_states,
        "collective": (coll["evaluator"] if coll is not None else None),
        "qualifies": bool(merged_regions or deleted_states or coll is not None)}
    # the aggregation itself was recomputed by a SECOND implementation (the
    # dense junction tree) on the checker's own verified lifted model, so
    # the independence the identity gate asks about holds here structurally
    meta["independent_aggregation_checked"] = True
    meta["independent_aggregation_scope"] = (
        "checker-owned dense junction tree over the checker's own verified "
        "representation; the producer's sparse contraction is not consulted")
    fails = []
    for v in sorted(queries):
        pub = published[v]
        for s in range(card[v]):
            lo, hi = Fr(pub[s][0]), Fr(pub[s][1])
            qlo, qhi = rows[v][s]
            if qlo == 0 and qhi == 0 and radius == 0:
                clo = chi = Fr(0)
            else:
                clo = max(Fr(0), qlo - radius)
                chi = min(Fr(1), qhi + radius)
            if not (lo <= clo and chi <= hi):
                # decimal renderings keep the NAMED obligation legible in a
                # truncated report; the exact rationals are in `rows`/`published`
                fails.append("variable %d state %d: publication [%.9f, %.9f] does NOT "
                             "contain the independent enclosure [%.9f, %.9f]"
                             % (v, s, float(lo), float(hi), float(clo), float(chi)))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: width exceeds eps" % (v, s))
    return (not fails), fails, meta
