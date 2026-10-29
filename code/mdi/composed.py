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


def admit(restricted, regions, coarse, rds, queries, ctx: A.Ctx, eps,
          t_level=None, deadline=None):
    """BOUNDED admission: recognize a mode, fit the residual, choose Q and
    charge its rounding energy -- WITHOUT evaluating the law.

    The pipeline ran the full composed inference during discovery just to find
    out whether the candidate was usable, so an UNSELECTED candidate incurred
    its entire inference cost. Everything here is bounded by the coarse model's
    local structure; the expensive contraction happens only after selection.

    Returns a dict the executor consumes, or raises Declined.
    """
    t_level = t_level if t_level is not None else K.level_radius(1)
    cm, projected = coarse_cell_model(restricted, regions, coarse, rds)
    rc = M.restrict(cm, {})
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
    remaining = allow - total_fit_tv
    if remaining <= 0:
        raise Declined("the coarse fit has already consumed the %s collective "
                       "allowance; no rounding budget remains" % allow)
    tries = K.CAPS["dyadic_Q_tries"]
    qchoices = [1 << (16 * j) for j in range(tries)]
    chosen_Q, rounding_tv, attempts = None, None, []
    for Q in qchoices:
        kq = CO.round_features(cand, rc.free, Q)
        D = CO.rounding_energy_bound(cand, rc.free, kq, Q)
        tv = D if D < 1 else Fr(1)
        attempts.append({"Q": Q, "rounding_energy": str(D), "tv": str(tv),
                         "admissible": bool(tv <= remaining)})
        if tv <= remaining:
            chosen_Q, rounding_tv = Q, tv
            break
    if chosen_Q is None:
        raise Declined(
            "no Q in the declared menu %s meets the remaining rounding "
            "allowance %s; the smallest rounding energy was %s. This candidate "
            "is DECLINED rather than published with an uncharged error."
            % (qchoices, remaining, attempts[-1]["rounding_energy"]
               if attempts else "n/a"))
    kept = list(getattr(res, "kept", ()) or ())
    return {"cm": cm, "projected": projected, "rc": rc, "cand": cand,
            "res": res, "can": can, "kept": kept, "Q": chosen_Q,
            "rounding_tv": rounding_tv, "fit_tv": fit_tv,
            "total_fit_tv": total_fit_tv + rounding_tv,
            "t_level": t_level, "Q_menu": qchoices, "Q_attempts": attempts,
            "admission_only": True}


def run(restricted, regions, coarse, rds, queries, ctx: A.Ctx, eps,
        t_level=None, deadline=None, admission=None):
    """Coarsen, fit a CATEGORICAL mode on the cells, evaluate, restore markers.

    Returns (intervals, meta) where the intervals are ORIGINAL-variable
    enclosures with every transformation error added.
    """
    if admission is not None:
        # reuse the BOUNDED admission already paid for during discovery, so
        # the expensive evaluation below happens exactly once, after selection
        cm = admission["cm"]
        rc = admission["rc"]
        cand = admission["cand"]
        res = admission["res"]
        can = admission["can"]
        kept = admission["kept"]
        chosen_Q = admission["Q"]
        rounding_tv = admission["rounding_tv"]
        fit_tv = admission["fit_tv"]
        total_fit_tv = admission["total_fit_tv"]
        t_level = admission["t_level"]
        qchoices = admission["Q_menu"]
        attempts = admission["Q_attempts"]
        allow = K.RADII["collective_fit_and_rounding"]
        return _evaluate(restricted, regions, coarse, rds, queries, ctx, eps,
                         cm, rc, cand, res, can, kept, chosen_Q, rounding_tv,
                         fit_tv, total_fit_tv, t_level, qchoices, attempts,
                         deadline)
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
    # ---- choose Q from the DECLARED bounded menu and CHARGE its rounding
    # energy. Q was hard-wired to 1, which on features [0, 1/2, 1] collapses
    # the middle value to 0: the middle-state probability came out
    # 0.125633960799 against an exact 0.253500354120, while the publication
    # claimed a radius of about 7.84e-13 and all nine intervals missed the
    # truth. The rounding energy on that candidate is 6.75 and was never
    # charged. A valid response is to DECLINE when no admissible Q meets the
    # remaining allowance; forcing a pass is not.
    remaining = allow - total_fit_tv
    if remaining <= 0:
        raise Declined("the coarse fit has already consumed the %s collective "
                       "allowance; no rounding budget remains" % allow)
    # The declared cap bounds the NUMBER of rounding denominators tried, not
    # their values. A menu of 1, 2, 4 spans only the coarsest dyadic grids and
    # cannot represent a feature whose rounding energy must fall below a
    # ~1e-10 allowance, so the candidate declined for want of resolution
    # rather than on its merits. The menu stays at `dyadic_Q_tries` entries
    # and is chosen geometrically so the finest grid is actually reachable.
    tries = K.CAPS["dyadic_Q_tries"]
    qchoices = [1 << (16 * j) for j in range(tries)]      # 1, 2^16, 2^32
    chosen_Q = None
    rounding_tv = None
    attempts = []
    for Q in qchoices:
        kq = CO.round_features(cand, rc.free, Q)
        D = CO.rounding_energy_bound(cand, rc.free, kq, Q)
        # an energy bound D on the log-weight gives a TV bound 1 - exp(-D),
        # itself bounded above by D
        tv = D if D < 1 else Fr(1)
        attempts.append({"Q": Q, "rounding_energy": str(D), "tv": str(tv),
                         "admissible": bool(tv <= remaining)})
        if tv <= remaining:
            chosen_Q, rounding_tv = Q, tv
            break
    if chosen_Q is None:
        raise Declined(
            "no Q in the declared menu %s meets the remaining rounding "
            "allowance %s; the smallest rounding energy was %s. This candidate "
            "is DECLINED rather than published with an uncharged error."
            % (qchoices, remaining, attempts[-1]["rounding_energy"]
               if attempts else "n/a"))
    kept = list(getattr(res, "kept", ()) or ())
    return _evaluate(restricted, regions, coarse, rds, queries, ctx, eps,
                     cm, rc, cand, res, can, kept, chosen_Q, rounding_tv,
                     fit_tv, total_fit_tv + rounding_tv, t_level, qchoices,
                     attempts, deadline)


def _evaluate(restricted, regions, coarse, rds, queries, ctx, eps,
              cm, rc, cand, res, can, kept, chosen_Q, rounding_tv, fit_tv,
              total_fit_tv, t_level, qchoices, attempts, deadline):
    """The expensive half: evaluate the coarse law and restore markers.

    Separated from admission so an UNSELECTED candidate never pays for it.
    """
    # Evaluate the coarse law. A PRODUCT residual goes to the product DP; a
    # residual that retains interacting pairs goes to the GENERAL-residual DP on
    # a validated elimination schedule, which is exactly the case E.5 exists
    # for. Declining here would make the composed route unreachable whenever
    # the coarse interactions are not fully removable.
    #
    # res.kept is carried into BOTH branches. It was dropped entirely before,
    # and it can hold zero constraints and higher-arity interactions whose
    # omission silently changes the law.
    if can.is_product() and not kept:
        acc, marks, _ = CO.statistic_dp(list(rc.free), rc.card, can.unary, {},
                                        [], cand, chosen_Q, set(rc.free))
        (Zlo, Zhi), cell_mk = CO.dp_root_combine(acc, marks, cand, chosen_Q,
                                                 ctx)
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
        # Every RETAINED residual factor, resolved from its INDEX into the
        # coarse factor list. res.kept holds integer indices; treating them as
        # Factor objects made `getattr(kf, "scope", ())` return () for an int,
        # so `if not sc: continue` SKIPPED every retained factor. On four
        # binary variables with a ternary constraint forcing X0 = 1 the
        # producer published X0 = 0 in [.01727, .01732] although its true
        # probability is exactly ZERO, and all eight intervals missed.
        #
        # Ownership is exclusive by construction in build_residual (a
        # zero-bearing unary is owned by res_unary and is NOT retained), so
        # consuming these cannot double-count.
        for ki, kf in enumerate(kept):
            if isinstance(kf, int):
                if not (0 <= kf < len(rc.factors)):
                    raise Declined(
                        "retained residual factor index %d is out of range "
                        "for %d coarse factors" % (kf, len(rc.factors)))
                kfac = rc.factors[kf]
            elif hasattr(kf, "scope") and hasattr(kf, "table"):
                kfac = kf
            else:
                raise Declined(
                    "retained residual entry %d has type %s, which is neither "
                    "a factor index nor a factor; the candidate DECLINES "
                    "rather than silently dropping it"
                    % (ki, type(kf).__name__))
            sc = tuple(kfac.scope)
            if not sc:
                raise Declined("a retained residual factor has an empty scope")
            if len(sc) > 3:
                raise Declined(
                    "a retained residual factor over %d variables cannot be "
                    "consumed by this evaluator; the candidate DECLINES rather "
                    "than dropping it" % len(sc))
            facs.append(M.Factor(scope=sc,
                                 card=tuple(rc.card[v] for v in sc),
                                 table=[Fr(x) for x in kfac.table],
                                 origin=-3000 - ki))
        rm = M.Model(nvars=cm.nvars, card=list(cm.card), factors=facs)
        rm.validate()
        rr = M.restrict(rm, {})
        sel = PP.choose_plan(rr.free, rr.card, rr.factors, 64,
                             K.RESOURCES["arm_rss_bytes"])
        if sel["chosen"] is None:
            raise Declined("no ordering fits the coarse residual graph")
        rpl, _rest = sel["chosen"]
        try:
            (Zlo, Zhi), cell_mk, _gm = G.run(rpl, rr.factors, rr.card, cand,
                                             chosen_Q, set(rc.free), ctx,
                                             deadline=deadline)
        except G.Declined as e:
            # the general-residual DP's own refusal is this candidate's
            # refusal: never fall through to a path that drops its factors
            raise Declined("general-residual evaluation declined: %s" % e)
        # Report the ACTUAL statistic support from the DP's metadata. A dummy
        # acc = {0: Fr(1)} reported statistic_support = 1 where the real
        # support on the repaired four-variable control is 8, and that false
        # count fed pricing and admission.
        _sup = None
        if isinstance(_gm, dict):
            _sup = (_gm.get("total_statistic_support")
                    or _gm.get("distinct_statistics")
                    or _gm.get("support"))
        acc = {k: Fr(1) for k in range(int(_sup))} if _sup else {0: Fr(1)}
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
            "Q": chosen_Q, "Q_menu": qchoices, "Q_attempts": attempts,
            "rounding_tv_charged": str(rounding_tv),
            "retained_residual_factors": len(kept),
            "mode_kind": cand.kind, "mode_sign": cand.signs[0],
            "fit_tv": str(fit_tv), "residual_tv": str(total_fit_tv),
            "regional_radius": str(t_level),
            "statistic_support": len(acc), "evaluator": evaluator,
            "kept_coarse_pairs": len(can.kept_pairs),
            "dropped_coarse_pairs": len(can.dropped_pairs),
            "total_radius": str(t_level + total_fit_tv)}
    return out, meta
