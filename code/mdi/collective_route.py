"""Collective-route ADMISSION on a Marked model (spec §6, §7.1-7.3, §8).

Recognize a mode from the ACTUAL factor tables (never from metadata), build
the certified residual, choose the evaluator and its parameters from the
remaining allowance, and return a serializable collective record. Nothing
here evaluates the law: that happens after selection, in the executor, from
the persisted record.

Radii (all exact rationals, all charged):
  fit_tv        = tanh(nu/2) bound on TV(original law, residual x modes)
  rounding_tv   = tanh(Delta/2) with Delta the §7.1 rounding energy (statistic)
  quadrature_tv = the GF3 lattice total bound (gaussian / fourier)
The collective allowance (0.0005) covers fit + rounding; the Gaussian
quadrature has its own 0.0005. A record whose radii do not fit is DECLINED
with the concrete numbers, not published with an uncharged error.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import (model as M, config as K, modes as MD, residual as RS,
                 collective as CO, marked as MK, arith as A)


class Declined(Exception):
    pass


ROUND_BITS = 40


def fit_certificate(law, resid, cand, card, free, ctx, log_enclose=None):
    """The producer's gauge-invariant uniform log-error bound nu (§6).

    Delta(z) = log W(z) - log W'(z) over the common support, with W the law
    and W' = residual x exp(modes). Every pair term (law pair, residual pair,
    mode term G_ij) is gauge-fixed at reference state 0,

        h(a,b) = l(a,b) - l(a,0) - l(0,b) + l(0,0),

    its rank-one leftovers l(a,0)-l(0,0) and l(0,b)-l(0,0) are pushed into
    the endpoint unary terms (together with the unary law/residual logs and
    the diagonal mode term D_i), and nu is the sum over scopes of HALF the
    range of each term. Then |Delta(z) - c| <= nu for a constant c, so
    TV(P, P') <= tanh(nu/2) <= nu/2.

    Without gauge fixing the per-scope deviations are not invariants: the
    residual's canonical unaries absorb rank-one pieces of exp(-G), so a
    naive per-pair bound reports the whole mode energy as error (TV "<= 1"
    on a mean-field fixture whose true fit error is 1e-11).

    Hard-zero and higher-arity factors must be reproduced exactly in the
    residual (they cancel); a mismatch is a Declined, not an error term.
    """
    logf = log_enclose or (lambda q: MD._log_enclose(Fr(q), ctx))
    un_law = {v: [Fr(1)] * card[v] for v in free}
    un_res = {v: [Fr(1)] * card[v] for v in free}
    pr_law, pr_res = {}, {}
    other_law, other_res = [], []

    def _pair_in(store, f):
        i, j = f.scope
        di, dj = card[i], card[j]
        if i < j:
            key, tbl = (i, j), [Fr(x) for x in f.table]
        else:
            key = (j, i)
            tbl = [Fr(0)] * (di * dj)
            for a in range(di):
                for b in range(dj):
                    tbl[b * di + a] = Fr(f.table[a * dj + b])
        cur = store.get(key)
        store[key] = tbl if cur is None else [x * y for x, y in zip(cur, tbl)]

    for f in law:
        if len(f.scope) == 1:
            v = f.scope[0]
            for a in range(card[v]):
                un_law[v][a] *= Fr(f.table[a])
        elif len(f.scope) == 2 and all(Fr(x) > 0 for x in f.table):
            _pair_in(pr_law, f)
        else:
            other_law.append((tuple(f.scope), [Fr(x) for x in f.table]))
    for f in resid:
        if len(f.scope) == 1:
            v = f.scope[0]
            for a in range(card[v]):
                un_res[v][a] *= Fr(f.table[a])
        elif len(f.scope) == 2 and all(Fr(x) > 0 for x in f.table):
            _pair_in(pr_res, f)
        else:
            other_res.append((tuple(f.scope), [Fr(x) for x in f.table]))
    for o in other_law:
        if o not in other_res:
            raise Declined("retained factor on %s is not reproduced exactly in "
                           "the residual" % (o[0],))
        other_res.remove(o)
    if other_res:
        raise Declined("the residual carries %d factor(s) no law factor justifies"
                       % len(other_res))

    def G(i, j, a, b):
        acc = Fr(0)
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            fj = cand.features[k].get(j)
            if fi is None or fj is None:
                continue
            acc += cand.signs[k] * cand.gammas[k] * Fr(fi[a]) * Fr(fj[b])
        return acc

    def D(i, a):
        acc = Fr(0)
        for k in range(cand.rank):
            fi = cand.features[k].get(i)
            if fi is None:
                continue
            acc += cand.signs[k] * cand.gammas[k] * Fr(fi[a]) * Fr(fi[a])
        return acc / 2

    coupled = set(pr_law) | set(pr_res)
    for k in range(cand.rank):
        vs = [v for v, f in cand.features[k].items() if any(Fr(x) != 0 for x in f)]
        for x in range(len(vs)):
            for y in range(x + 1, len(vs)):
                coupled.add(tuple(sorted((vs[x], vs[y]))))
    nu = Fr(0)
    left = {v: [(Fr(0), Fr(0))] * card[v] for v in free}      # rank-one leftovers
    for (i, j) in sorted(coupled):
        di, dj = card[i], card[j]
        P = pr_law.get((i, j))
        Q = pr_res.get((i, j))
        ell = {}
        for a in range(di):
            for b in range(dj):
                lo = hi = -G(i, j, a, b)
                if P is not None:
                    l, h = logf(P[a * dj + b])
                    lo += l
                    hi += h
                if Q is not None:
                    l, h = logf(Q[a * dj + b])
                    lo -= h
                    hi -= l
                ell[(a, b)] = (lo, hi)
        l00 = ell[(0, 0)]
        hmin = hmax = Fr(0)
        for a in range(di):
            for b in range(dj):
                if a == 0 or b == 0:
                    continue                      # exactly zero after fixing
                la, lb = ell[(a, 0)], ell[(0, b)]
                lab = ell[(a, b)]
                hlo = lab[0] - la[1] - lb[1] + l00[0]
                hhi = lab[1] - la[0] - lb[0] + l00[1]
                hmin = min(hmin, hlo)
                hmax = max(hmax, hhi)
        nu += (hmax - hmin) / 2
        for a in range(di):
            la = ell[(a, 0)]
            cur = left[i][a]
            left[i][a] = (cur[0] + la[0] - l00[1], cur[1] + la[1] - l00[0])
        for b in range(dj):
            lb = ell[(0, b)]
            cur = left[j][b]
            left[j][b] = (cur[0] + lb[0] - l00[1], cur[1] + lb[1] - l00[0])
    for v in free:
        lo_all = hi_all = None
        for a in range(card[v]):
            if (un_law[v][a] == 0) != (un_res[v][a] == 0):
                raise Declined("unary support of variable %d differs between the "
                               "law and the residual at state %d" % (v, a))
            if un_law[v][a] == 0:
                continue
            l, h = logf(un_law[v][a])
            rl, rh = logf(un_res[v][a])
            d = D(v, a)
            lo = l - rh - d + left[v][a][0]
            hi = h - rl - d + left[v][a][1]
            lo_all = lo if lo_all is None else min(lo_all, lo)
            hi_all = hi if hi_all is None else max(hi_all, hi)
        if lo_all is None:
            raise Declined("variable %d has no supported state" % v)
        nu += (hi_all - lo_all) / 2
    return nu


def _residual_marked(marked: MK.Marked, res, can, kept) -> MK.Marked:
    """The Marked model whose factors are the certified residual b(z):
    canonical unaries (owning every original unary and absorbed gauge),
    retained interacting pairs, retained hard-zero / higher-arity factors.
    Masses and markers are carried over unchanged: g = N/M is the fixed query
    observable (§7.1), multiplied into the new represented weight."""
    facs = []
    for v in marked.free():
        facs.append(M.Factor(scope=(v,), card=(marked.card[v],),
                             table=[Fr(x) for x in can.unary[v]],
                             origin=-10000 - v))
    for (i, j), tbl in sorted(can.kept_pairs.items()):
        facs.append(M.Factor(scope=(i, j), card=(marked.card[i], marked.card[j]),
                             table=[Fr(x) for x in tbl], origin=-20000 - len(facs)))
    law = marked.law_factors()
    for ki, fi in enumerate(kept):
        kf = law[fi]
        facs.append(M.Factor(scope=tuple(kf.scope), card=tuple(kf.card),
                             table=[Fr(x) for x in kf.table],
                             origin=-30000 - ki))
    # the masses are ALREADY inside the law factors the residual was fitted
    # to (law_factors includes them), so the residual marked model carries
    # unit masses and the payload g is re-expressed against the original
    # owner masses, which the caller keeps on `marked`.
    out = MK.Marked(card=dict(marked.card), factors=facs,
                    owner=dict(marked.owner),
                    marks={k: list(v) for k, v in marked.marks.items()},
                    mass={v: list(marked.mass[v]) for v in marked.card},
                    orig_card=dict(marked.orig_card), level=marked.level,
                    certificate=dict(marked.certificate), mass_absorbed=True)
    return out


def admit(marked: MK.Marked, ctx: A.Ctx, deadline=None, prefer=None):
    """Bounded admission. Returns (record_dict, residual_marked) or raises
    Declined with the concrete reason.

    `prefer` optionally names an evaluator ("statistic" | "gaussian" |
    "fourier"); by default the statistic DP is tried first for every rank
    and the quadrature evaluators for rank 1 of the matching sign.
    """
    law = marked.law_factors()
    free = marked.free()
    cands, info = MD.propose_modes(free, law, marked.card)
    if not cands:
        raise Declined("no collective mode recognized from the factor tables: %s"
                       % info.get("declined", info))
    allow = K.RADII["collective_fit_and_rounding"]
    errors = []
    for cand in cands:
        if deadline is not None:
            deadline()
        try:
            res = MD.build_residual(free, law, marked.card, cand, ctx,
                                    round_bits=ROUND_BITS)
        except (MD.Declined, Exception) as e:
            errors.append("%s: residual declined: %s" % (cand.kind, e))
            continue
        fit_tv = MD.tv_from_nu(res.nu)
        if fit_tv > allow:
            errors.append("%s: fit TV %s exceeds the %s allowance"
                          % (cand.kind, fit_tv, allow))
            continue
        # drop tiny interactions within what remains of the SAME allowance
        drop_budget = 2 * (allow - fit_tv)
        can = RS.canonicalize(res.unary, res.pairs, marked.card, ctx, drop_budget)
        total_fit = RS.tv_from_total_nu(res.nu, can.nu_extra)
        if total_fit > allow:
            errors.append("%s: residual TV %s exceeds the allowance" % (cand.kind, total_fit))
            continue
        kept = list(res.kept)
        # `res.kept` indexes marked.law_factors(); masses are unary and never
        # retained (res_unary owns them), so the indices are consistent
        rmk = _residual_marked(marked, res, can, kept)
        # the RECORDED certificate is the canonical gauge-invariant bound on
        # the residual actually emitted, not the fitter's internal tally
        try:
            nu = fit_certificate(law, rmk.factors, cand, marked.card, free, ctx)
        except Declined as e:
            errors.append("%s: certificate: %s" % (cand.kind, e))
            continue
        total_fit = K.tanh_upper(nu)
        if total_fit > allow:
            errors.append("%s: canonical fit TV %s exceeds the %s allowance"
                          % (cand.kind, total_fit, allow))
            continue
        # ---- evaluator choice from the REMAINING allowance. With `prefer`
        # ONLY that evaluator is tried, so its decline is reported as its own
        # (a silent fallback to another evaluator hid the Gaussian route's
        # refusal entirely); without it the statistic DP is tried first.
        remaining = allow - total_fit
        order = [prefer] if prefer else ["statistic", "gaussian", "fourier"]
        for ev in order:
            if ev == "statistic":
                if remaining <= 0:
                    errors.append("%s: no rounding allowance remains" % cand.kind)
                    continue
                tries = K.CAPS["dyadic_Q_tries"]
                menu = [1 << (16 * j) for j in range(tries)]
                attempts = []
                chosen = None
                for Q in menu:
                    kq = CO.round_features(cand, free, Q)
                    D = CO.rounding_energy_bound(cand, free, kq, Q)
                    tv = K.tanh_upper(D)       # TV <= tanh(Delta/2)
                    attempts.append({"Q": Q, "rounding_energy": str(D),
                                     "tv": str(tv), "admissible": bool(tv <= remaining)})
                    if tv <= remaining:
                        chosen = (Q, tv)
                        break
                if chosen is None:
                    errors.append("%s: no Q in %s meets the remaining %s"
                                  % (cand.kind, menu, remaining))
                    continue
                Q, rtv = chosen
                return {"evaluator": "statistic",
                        "candidate": cand, "Q": Q, "delta": None,
                        "fit_tv": total_fit, "rounding_tv": rtv,
                        "quadrature_tv": Fr(0), "precision": ctx.p,
                        "round_bits": ROUND_BITS, "kept_factors": kept,
                        "dropped_pairs": [[i, j] for i, j, _r in can.dropped_pairs],
                        "drop_budget": drop_budget,
                        "Q_attempts": attempts, "mode_info": info,
                        "fit_detail": res.detail}, rmk
            if ev in ("gaussian", "fourier"):
                if cand.rank != 1:
                    errors.append("%s: quadrature needs rank 1, got %d"
                                  % (cand.kind, cand.rank))
                    continue
                if (ev == "gaussian") != (cand.signs[0] > 0):
                    errors.append("%s: the %s identity needs a %s mode, the "
                                  "recognized sign is %+d"
                                  % (cand.kind, ev,
                                     "positive" if ev == "gaussian" else "negative",
                                     cand.signs[0]))
                    continue
                qallow = K.RADII["gaussian_quadrature"]
                Rk = Fr(0)
                for f in cand.features[0].values():
                    Rk += max(abs(Fr(x)) for x in f)
                # the quadrature delta IS the GF3 TV radius: the coarsest
                # dyadic delta within the allowance whose lattice constructs.
                # The node count is not capped here; it enters the complete
                # price (nodes times the per-node contraction) and the byte
                # and wall budgets decide admission, as §7.2 asks.
                chosen = None
                tried = []
                d = qallow
                for _ in range(4):
                    try:
                        lat = (CO.gf_lattice(cand.gammas[0], Rk, d) if ev == "gaussian"
                               else CO.fourier_lattice(cand.gammas[0], Rk, d))
                    except CO.Declined as e:
                        tried.append({"delta": str(d), "declined": str(e)})
                        d /= 2
                        continue
                    tried.append({"delta": str(d), "nodes": lat["nodes"],
                                  "total_bound": str(lat["total_bound"])})
                    if Fr(lat["total_bound"]) <= qallow:
                        chosen = (d, lat)
                        break
                    d /= 2
                if chosen is None:
                    errors.append("%s: no %s lattice within the %s quadrature "
                                  "allowance (%s)" % (cand.kind, ev, qallow, tried[-1]))
                    continue
                d, lat = chosen
                return {"evaluator": ev, "candidate": cand, "Q": None,
                        "delta": d, "fit_tv": total_fit, "rounding_tv": Fr(0),
                        "quadrature_tv": Fr(lat["total_bound"]),
                        "precision": ctx.p, "round_bits": ROUND_BITS,
                        "kept_factors": kept,
                        "dropped_pairs": [[i, j] for i, j, _r in can.dropped_pairs],
                        "drop_budget": drop_budget, "lattice_attempts": tried,
                        "nodes": lat["nodes"], "mode_info": info,
                        "fit_detail": res.detail}, rmk
    raise Declined("every recognized mode declined: " + "; ".join(errors[:4]))


def total_radius(coll) -> Fr:
    """Every transformation radius of a collective record, summed."""
    return Fr(coll["fit_tv"]) + Fr(coll["rounding_tv"]) + Fr(coll["quadrature_tv"])


def rebuild_residual(marked: MK.Marked, coll, ctx: A.Ctx):
    """Rebuild the residual Marked model from a PARSED collective record and
    the current marked model, re-deriving the fit certificate from the
    factor tables. Used by the executor (fresh process) and by the checker
    (independent reconstruction). Raises Declined if the record's radii are
    not covered by the recomputed certificate."""
    law = marked.law_factors()
    free = marked.free()
    cand = coll["candidate"]
    res = MD.build_residual(free, law, marked.card, cand, ctx,
                            round_bits=coll["round_bits"])
    can = RS.canonicalize(res.unary, res.pairs, marked.card, ctx,
                          Fr(coll["drop_budget"]))
    rmk = _residual_marked(marked, res, can, list(res.kept))
    nu = fit_certificate(law, rmk.factors, cand, marked.card, free, ctx)
    total_fit = K.tanh_upper(nu)
    if total_fit > Fr(coll["fit_tv"]):
        raise Declined("the recomputed fit TV %s exceeds the recorded %s"
                       % (total_fit, coll["fit_tv"]))
    if sorted(res.kept) != sorted(coll["kept_factors"]):
        raise Declined("the recomputed retained-factor set %s differs from the "
                       "recorded %s" % (sorted(res.kept), sorted(coll["kept_factors"])))
    if sorted([list(p) for p in [(i, j) for i, j, _r in can.dropped_pairs]]) != \
            sorted([list(p) for p in coll["dropped_pairs"]]):
        raise Declined("the recomputed dropped-pair set differs from the record")
    if coll["evaluator"] == "statistic":
        kq = CO.round_features(cand, free, coll["Q"])
        D = CO.rounding_energy_bound(cand, free, kq, coll["Q"])
        if K.tanh_upper(D) > Fr(coll["rounding_tv"]):
            raise Declined("the recomputed rounding TV %s exceeds the recorded %s"
                           % (K.tanh_upper(D), coll["rounding_tv"]))
    else:
        Rk = Fr(0)
        for f in cand.features[0].values():
            Rk += max(abs(Fr(x)) for x in f)
        lat = (CO.gf_lattice(cand.gammas[0], Rk, coll["delta"])
               if coll["evaluator"] == "gaussian"
               else CO.fourier_lattice(cand.gammas[0], Rk, coll["delta"]))
        if Fr(lat["total_bound"]) > Fr(coll["quadrature_tv"]):
            raise Declined("the recomputed lattice bound %s exceeds the recorded %s"
                           % (lat["total_bound"], coll["quadrature_tv"]))
    return rmk, res, can
