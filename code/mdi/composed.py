"""Categorical coarse-plus-collective composition (contract §E.7).

Coarsen the fixed evidence-conditioned law first, with its proved
original-to-lifted error. Then fit modes on the CATEGORICAL cell variables of
that fixed coarse law and evaluate them. Original query payloads remain the
bounded observables g = N/M, and the transformation errors ADD.

This sequence does not require the coarsening approximation to remain valid
under a Gaussian tilt: coarsening is not reapplied at tilted nodes.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import (model as M, config as K, compact as CP, modes as MD,
                 collective as CO, residual as RS, arith as A, regions as R)


class Declined(Exception):
    pass


def coarse_cell_model(restricted, regions, coarse, rds):
    """The coarse model as a CATEGORICAL factor graph over cell variables."""
    ncell = [len(c.cells) for c in coarse]
    projected, _ = CP.project_crossings(restricted, regions, coarse, rds)
    facs = []
    for i in range(len(regions)):
        facs.append(M.Factor(scope=(i,), card=(ncell[i],),
                             table=[Fr(x) for x in coarse[i].M],
                             origin=-(i + 1)))
    for pc in projected:
        rs = tuple(pc.regions)
        cards = tuple(ncell[i] for i in rs)
        n = 1
        for c in cards:
            n *= c
        if n > K.CAPS["aggregated_kernel_entries"]:
            raise Declined("a coarse crossing factor needs %d entries, above "
                           "the declared cap" % n)
        st = [1] * len(cards)
        acc = 1
        for k in range(len(cards) - 1, -1, -1):
            st[k] = acc
            acc *= cards[k]
        tab = []
        for flat in range(n):
            rem, dig = flat, []
            for k in range(len(cards)):
                dig.append(rem // st[k])
                rem %= st[k]
            tab.append(pc.value({rs[k]: dig[k] for k in range(len(rs))}))
        facs.append(M.Factor(scope=rs, card=cards, table=tab, origin=-1000))
    cm = M.Model(nvars=len(regions), card=list(ncell), factors=facs)
    cm.validate()
    return cm, projected


def run(restricted, regions, coarse, rds, queries, ctx: A.Ctx, eps,
        t_level=None, deadline=None):
    """Coarsen, fit a CATEGORICAL mode on the cells, evaluate, restore markers.

    Returns (intervals, meta) where the intervals are ORIGINAL-variable
    enclosures with every transformation error added.
    """
    t_level = t_level if t_level is not None else K.level_radius(1)
    cm, projected = coarse_cell_model(restricted, regions, coarse, rds)
    rc = M.restrict(cm, {})

    # fit a mode on the CATEGORICAL cell variables
    cands, info = MD.propose_modes(rc.free, rc.factors, rc.card)
    if not cands:
        raise Declined("no collective mode on the coarse cells: %s"
                       % info.get("declined", info))
    cand = cands[0]
    res = MD.build_residual(rc.free, rc.factors, rc.card, cand, ctx)
    allow = K.RADII["collective_fit_and_rounding"]
    fit_tv = MD.tv_from_nu(res.nu)
    if fit_tv > allow:
        raise Declined("coarse mode fit TV %s exceeds the %s allowance"
                       % (fit_tv, allow))
    can = RS.canonicalize(res.unary, res.pairs, rc.card, ctx,
                          2 * (allow - fit_tv))
    total_fit_tv = RS.tv_from_total_nu(res.nu, can.nu_extra)
    if total_fit_tv > allow:
        raise Declined("coarse residual TV %s exceeds the allowance"
                       % total_fit_tv)
    # Evaluate the coarse law. A PRODUCT residual goes to the product DP; a
    # residual that retains interacting pairs goes to the GENERAL-residual DP on
    # a validated elimination schedule, which is exactly the case E.5 exists
    # for. Declining here would make the composed route unreachable whenever
    # the coarse interactions are not fully removable.
    if can.is_product():
        acc, marks, _ = CO.statistic_dp(list(rc.free), rc.card, can.unary, {},
                                        [], cand, 1, set(rc.free))
        (Zlo, Zhi), cell_mk = CO.dp_root_combine(acc, marks, cand, 1, ctx)
        evaluator = "product_statistic_dp"
    else:
        from mdi import plan as PP, gendp as G
        facs = []
        for v in sorted(rc.free):
            facs.append(M.Factor(scope=(v,), card=(rc.card[v],),
                                 table=[Fr(x) for x in can.unary[v]],
                                 origin=-1 - v))
        for (i, j), tbl in sorted(can.kept_pairs.items()):
            facs.append(M.Factor(scope=(i, j),
                                 card=(rc.card[i], rc.card[j]),
                                 table=[Fr(x) for x in tbl], origin=-2000))
        rm = M.Model(nvars=cm.nvars, card=list(cm.card), factors=facs)
        rm.validate()
        rr = M.restrict(rm, {})
        sel = PP.choose_plan(rr.free, rr.card, rr.factors, 64,
                             K.RESOURCES["arm_rss_bytes"])
        if sel["chosen"] is None:
            raise Declined("no ordering fits the coarse residual graph")
        rpl, _rest = sel["chosen"]
        (Zlo, Zhi), cell_mk, _gm = G.run(rpl, rr.factors, rr.card, cand, 1,
                                         set(rc.free), ctx, deadline=deadline)
        acc = {0: Fr(1)}
        evaluator = "general_residual_dp"
    if Zlo <= 0:
        raise Declined("coarse collective evaluation gave a nonpositive total")

    # restore ORIGINAL markers through the payloads g = N/M
    out = {}
    for v in sorted(queries):
        ri = next((i for i, reg in enumerate(regions) if v in reg), None)
        if ri is None:
            continue
        cr = coarse[ri]
        nst = len({k[1] for k in cr.N if k[0] == v})
        rows = []
        for s in range(nst):
            lo = hi = Fr(0)
            for ci in range(len(cr.cells)):
                Mc = Fr(cr.M[ci])
                if Mc <= 0:
                    continue
                g = Fr(cr.N[(v, s)][ci]) / Mc      # the fixed observable
                clo, chi = cell_mk.get((ri, ci), (Fr(0), Fr(0)))
                lo += Fr(clo) * g
                hi += Fr(chi) * g
            qlo = lo / Zhi if Zhi > 0 else Fr(0)
            qhi = hi / Zlo if Zlo > 0 else Fr(1)
            # every transformation error ADDS
            total = t_level + total_fit_tv
            rows.append((max(Fr(0), qlo - total), min(Fr(1), qhi + total)))
        out[v] = rows
    meta = {"coarse_vars": cm.nvars, "coarse_cards": list(cm.card),
            "mode_kind": cand.kind, "mode_sign": cand.signs[0],
            "fit_tv": str(fit_tv), "residual_tv": str(total_fit_tv),
            "regional_radius": str(t_level),
            "statistic_support": len(acc), "evaluator": evaluator,
            "kept_coarse_pairs": len(can.kept_pairs),
            "dropped_coarse_pairs": len(can.dropped_pairs),
            "total_radius": str(t_level + total_fit_tv)}
    return out, meta
