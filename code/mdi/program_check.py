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
from mdi import (model as M, config as K, regions as R, marked as MK,
                 regional_check as RC, collective_route as CR,
                 collective_jt as CJ, dense_be as DB, arith as A, program as PG)


class CheckError(Exception):
    pass


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
    lfactors = []
    for f in marked.factors:
        rs = sorted({region_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        cards = tuple(ncell[i] for i in rs)
        n = 1
        for c in cards:
            n *= c
        if n > K.CAPS["aggregated_kernel_entries"]:
            return None, ["a lifted crossing over regions %s needs %d entries, "
                          "above the cap" % (rs, n)]
        tab = []
        for combo in itertools.product(*[range(c) for c in cards]):
            a = {}
            for k, i in enumerate(rs):
                region, boundary, pc = verified[i]
                rep = pc.cells[combo[k]].rep
                for kk, v in enumerate(boundary):
                    a[v] = rep[kk]
            tab.append(Fr(f.at(a)))
        lfactors.append(M.Factor(scope=tuple(rs), card=cards, table=tab,
                                 origin=f.origin))
    lifted = MK.Marked(card={i: ncell[i] for i in range(len(regs))},
                       factors=lfactors, owner=lowner, marks=lmarks, mass=lmass,
                       orig_card=dict(marked.orig_card), level=marked.level + 1)
    try:
        lifted.check_identity()
    except MK.MarkedError as e:
        return None, ["the verified witness violates the marker identity: %s" % e]
    return lifted, {"t_level": t_level, "deletion": own_del, "R_level": own_rho}


# ------------------------------------------------- own fit certificate

def _log_pair(q: Fr, ctx):
    with ctx.D:
        lo = gmpy2.log(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    with ctx.U:
        hi = gmpy2.log(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
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
    law = marked.law_factors()
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


# --------------------------------------------------------------- the check

def verify_program(r, queries, prog, published, eps, deadline=None, budget=None):
    """Verify a parsed program's publication. `published` holds ONLY the
    requested variables' rows. Returns (ok, failures, meta)."""
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
    marked = MK.Marked.from_restricted(r, queries)
    radius = Fr(0)
    meta = {"scales": [], "independent_enclosure": True}
    for k, sc in enumerate(prog["scales"]):
        lifted, info = verify_scale(marked, sc, deadline=deadline, budget=budget)
        if lifted is None:
            return False, ["scale %d: %s" % (k + 1, p) for p in info], \
                {"certificate_rejected": True}
        radius += info["t_level"] + info["deletion"]
        meta["scales"].append({kk: str(vv) for kk, vv in info.items()})
        marked = lifted
    coll = prog["collective"]
    if coll is None:
        tables = [(tuple(f.scope), [Fr(x) for x in f.table])
                  for f in marked.law_factors()]
        touched = {v for f in marked.factors for v in f.scope}
        for v in marked.free():
            if v not in touched and not any(x != 1 for x in marked.mass[v]):
                tables.append(((v,), [Fr(1)] * marked.card[v]))
        charge = None
        if budget is not None:
            charge = lambda n: budget.charge("local_mass_entries", n,
                                             "checker dense contraction")
        try:
            Z, counts, jt = DB.exact_marginals(tables, marked.card, deadline=deadline,
                                               charge=charge)
        except DB.DenseError as e:
            return False, ["the checker's own contraction refused: %s" % e], None
        rows = MK.read_original(marked, Z, counts)
        meta["method"] = "checker-owned dense junction tree, exact rationals"
    else:
        ctx = A.Ctx(coll["precision"] + 16)
        try:
            rmk, res, can = CR.rebuild_residual(marked, coll, A.Ctx(coll["precision"]))
        except (CR.Declined, Exception) as e:
            return False, ["the collective record does not rebuild: %s" % e], None
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
            # the checker's own lattice bound for the record's delta
            cand = coll["candidate"]
            Rk = Fr(0)
            for f in cand.features[0].values():
                Rk += max(abs(Fr(x)) for x in f)
            try:
                lat = (CO.gf_lattice(cand.gammas[0], Rk, coll["delta"])
                       if coll["evaluator"] == "gaussian"
                       else CO.fourier_lattice(cand.gammas[0], Rk, coll["delta"]))
            except CO.Declined as e:
                return False, ["the checker cannot construct the record's lattice: %s" % e], None
            if Fr(lat["total_bound"]) > Fr(coll["quadrature_tv"]):
                return False, ["the checker's own lattice bound %s exceeds the "
                               "recorded %s" % (lat["total_bound"], coll["quadrature_tv"])], None
            meta["own_quadrature_tv"] = str(lat["total_bound"])
        charge = None
        if budget is not None:
            charge = lambda n: budget.charge("local_mass_entries", n,
                                             "checker dense collective evaluation")
        try:
            (Zlo, Zhi), counts, cmeta = CJ.evaluate(rmk, coll, ctx, engine="dense",
                                                    deadline=deadline, charge=charge)
        except (CJ.Declined, DB.DenseError) as e:
            return False, ["the checker's own collective evaluation refused: %s" % e], None
        if Zlo <= 0:
            return False, ["the checker's own collective total is not positive"], None
        rows = {}
        for v in rmk.queries():
            rr = []
            for a in range(rmk.orig_card[v]):
                lo, hi = counts[v][a]
                rr.append((max(Fr(0), lo / Zhi), min(Fr(1), hi / Zlo)))
            rows[v] = rr
        radius += CR.total_radius(coll)
        meta["method"] = "checker-owned dense %s evaluation" % coll["evaluator"]
        meta["collective"] = {k: v for k, v in cmeta.items() if k != "lattice"}
    meta["checker_radius"] = str(radius)
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
                fails.append("variable %d state %d: publication [%s, %s] does NOT "
                             "contain the independent enclosure [%s, %s]"
                             % (v, s, lo, hi, clo, chi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: width exceeds eps" % (v, s))
    return (not fails), fails, meta
