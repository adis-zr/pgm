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
                 collective as CO, marked as MK, arith as A, factors as FX)


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
    law = [FX.densify(f, K.CAPS["aggregated_kernel_entries"])
           for f in marked.law_factors()]
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


def choose_Q(cand, free, remaining, tries=None):
    """Spec §7.1: at most `dyadic_Q_tries` dyadic Q values chosen FROM the
    proved rounding bound. The bound Delta(Q) is cheap, so it is evaluated on
    the dyadic ladder; the attempts recorded are the smallest admissible Q and
    its two coarser neighbours (the ones that decide it is the smallest). The
    coarsest admissible grid is what the DP then solves."""
    tries = tries or K.CAPS["dyadic_Q_tries"]
    ladder = []
    for j in range(0, 40):
        Q = 1 << j
        kq = CO.round_features(cand, free, Q)
        D = CO.rounding_energy_bound(cand, free, kq, Q)
        tv = K.tanh_upper(D)
        ladder.append((Q, D, tv, tv <= remaining))
        if tv <= remaining:
            break
    chosen = next((x for x in ladder if x[3]), None)
    attempts = ladder[-tries:]
    out = [{"Q": Q, "rounding_energy": str(D), "tv": str(tv), "admissible": ok}
           for Q, D, tv, ok in attempts]
    if chosen is None:
        return None, None, out
    return chosen[0], chosen[2], out


def lattice_for(cand, k, delta):
    """The GF3 lattice of mode k at TV radius delta (positive: gf_lattice;
    negative: the oscillatory fourier_lattice)."""
    Rk = Fr(0)
    for f in cand.features[k].values():
        Rk += max(abs(Fr(x)) for x in f)
    if cand.signs[k] > 0:
        return CO.gf_lattice(cand.gammas[k], Rk, delta)
    return CO.fourier_lattice(cand.gammas[k], Rk, delta)


def gf_forecast(cand, qallow, num_eps):
    """§7.2 feasibility forecast for Gaussian/Fourier/mixed integration.

    Positive coordinates: each needs a lattice whose GF3 total bound fits its
    share of the quadrature allowance (a TV radius on the law, since
    exp(+gS^2/2) >= 1 makes the absolute lattice error a relative one).

    Negative coordinates: the lattice error is an ABSOLUTE error on a count
    whose true value may be as small as L = exp(-Y_max) times the positive
    mass. It is not a probability radius; it enters the sharp marker-ratio
    enclosure, whose worst-case width is 2*delta/L. The forecast therefore
    needs delta_neg <= L * num_eps / 4 (half the numerical width, for the
    two-sided ratio), which can force an unaffordable node count -- that is
    reported as a decline BEFORE any evaluation.

    Returns (per-mode delta list, lattices, node product, meta) or raises
    Declined.
    """
    pos = [k for k in range(cand.rank) if cand.signs[k] > 0]
    neg = [k for k in range(cand.rank) if cand.signs[k] < 0]
    deltas = [None] * cand.rank
    lats = [None] * cand.rank
    meta = {"positive_modes": len(pos), "negative_modes": len(neg)}
    if pos:
        share = Fr(qallow) / len(pos)
        for k in pos:
            d = share
            lat = None
            for _ in range(4):
                try:
                    lat = CO.gf_lattice(cand.gammas[k], _R(cand, k), d)
                except CO.Declined:
                    lat = None
                if lat is not None and Fr(lat["total_bound"]) <= share:
                    break
                d /= 2
            if lat is None or Fr(lat["total_bound"]) > share:
                raise Declined("positive mode %d: no GF lattice within its %s share "
                               "of the quadrature allowance" % (k, share))
            deltas[k] = d
            lats[k] = lat
    if neg:
        Ymax = Fr(0)
        for k in neg:
            Ymax += cand.gammas[k] * _R(cand, k) * _R(cand, k) / 2
        L_lo = CO._exp_lower(-Ymax)          # exp(-Ymax), a rational LOWER bound
        if L_lo <= 0:
            raise Declined("the negative-response lower bound exp(-%s) underflows "
                           "the rational enclosure" % Ymax)
        meta["Y_max"] = str(Ymax)
        meta["L_lower"] = str(L_lo)
        need = L_lo * Fr(num_eps) / (4 * len(neg))
        for k in neg:
            d = need
            try:
                lat = CO.fourier_lattice(cand.gammas[k], _R(cand, k), d)
            except CO.Declined as e:
                raise Declined("negative mode %d: the oscillatory lattice at the "
                               "required delta %s is unavailable (%s)" % (k, d, e))
            deltas[k] = d
            lats[k] = lat
    nodes = 1
    for lat in lats:
        nodes *= lat["nodes"]
    meta["nodes_per_mode"] = [lat["nodes"] for lat in lats]
    meta["tensor_nodes"] = nodes
    return deltas, lats, nodes, meta


def _R(cand, k):
    Rk = Fr(0)
    for f in cand.features[k].values():
        Rk += max(abs(Fr(x)) for x in f)
    return Rk


def admit(marked: MK.Marked, ctx: A.Ctx, deadline=None, prefer=None,
          num_eps=None):
    """Bounded admission. Returns a LIST of admissible collective records
    (record_dict, residual_marked) -- one per (certified candidate, applicable
    evaluator) -- or raises Declined with every concrete reason.

    Every candidate of the §6 menu is certified by the gauge-invariant fit
    certificate on the residual actually emitted; a certified representation
    is then offered to EVERY evaluator that applies to it: the statistic DP
    (any rank), and Gaussian / Fourier / mixed integration (rank 1 positive /
    rank 1 negative / mixed signs) when the §7.2 forecast is affordable.
    `prefer` restricts to one evaluator and reports its own decline.
    """
    free = marked.free()
    try:
        law = [FX.densify(f, K.CAPS["aggregated_kernel_entries"])
               for f in marked.law_factors()]
    except FX.ViewError as e:
        raise Declined("the collective recognizer needs bounded explicit "
                       "tables: %s" % e)
    cands, info = MD.propose_modes(free, law, marked.card)
    if not cands:
        raise Declined("no collective mode recognized from the factor tables: %s"
                       % info.get("declined", info))
    allow = K.RADII["collective_fit_and_rounding"]
    qallow = K.RADII["gaussian_quadrature"]
    num_eps = Fr(num_eps) if num_eps is not None else \
        (K.MAX_WIDTH - 2 * (allow + qallow) - K.PUBLICATION_RESERVE)
    errors = []
    out = []
    seen_keys = set()
    for cand in cands:
        if deadline is not None:
            deadline()
        try:
            res = MD.build_residual(free, law, marked.card, cand, ctx,
                                    round_bits=ROUND_BITS)
        except Exception as e:
            errors.append("%s: residual declined: %s" % (cand.kind, e))
            continue
        fit_tv0 = MD.tv_from_nu(res.nu)
        if fit_tv0 > allow:
            errors.append("%s: fit TV %s exceeds the %s allowance" % (cand.kind, fit_tv0, allow))
            continue
        drop_budget = 2 * (allow - fit_tv0)
        can = RS.canonicalize(res.unary, res.pairs, marked.card, ctx, drop_budget)
        kept = list(res.kept)
        rmk = _residual_marked(marked, res, can, kept)
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
        remaining = allow - total_fit
        base = {"candidate": cand, "fit_tv": total_fit, "precision": ctx.p,
                "round_bits": ROUND_BITS, "kept_factors": kept,
                "dropped_pairs": [[i, j] for i, j, _r in can.dropped_pairs],
                "drop_budget": drop_budget, "mode_info": info,
                "fit_detail": res.detail}
        evaluators = [prefer] if prefer else ["statistic", "gaussian", "fourier", "mixed"]
        for ev in evaluators:
            if ev == "statistic":
                if remaining <= 0:
                    errors.append("%s: no rounding allowance remains" % cand.kind)
                    continue
                Q, rtv, attempts = choose_Q(cand, free, remaining)
                if Q is None:
                    errors.append("%s: no dyadic Q meets the remaining %s"
                                  % (cand.kind, remaining))
                    continue
                rec = dict(base, evaluator="statistic", Q=Q, delta=None,
                           rounding_tv=rtv, quadrature_tv=Fr(0),
                           Q_attempts=attempts)
                key = ("statistic", cand.kind, cand.rank)
                if key not in seen_keys:
                    seen_keys.add(key)
                    out.append((rec, rmk))
                continue
            want_pos = [k for k in range(cand.rank) if cand.signs[k] > 0]
            want_neg = [k for k in range(cand.rank) if cand.signs[k] < 0]
            if ev == "gaussian" and (want_neg or cand.rank != 1):
                errors.append("%s: Gaussian needs a single positive mode (signs %s)"
                              % (cand.kind, cand.signs))
                continue
            if ev == "fourier" and (want_pos or cand.rank != 1):
                errors.append("%s: Fourier needs a single negative mode (signs %s)"
                              % (cand.kind, cand.signs))
                continue
            if ev == "mixed" and not (want_pos and want_neg):
                errors.append("%s: mixed integration needs both signs (signs %s)"
                              % (cand.kind, cand.signs))
                continue
            try:
                deltas, lats, nodes, fmeta = gf_forecast(cand, qallow, num_eps)
            except Declined as e:
                errors.append("%s/%s: %s" % (cand.kind, ev, e))
                continue
            qtv = sum((Fr(lats[k]["total_bound"]) for k in want_pos), Fr(0))
            rec = dict(base, evaluator=ev, Q=None,
                       delta=(deltas[0] if cand.rank == 1 else None),
                       deltas=[str(d) for d in deltas], rounding_tv=Fr(0),
                       quadrature_tv=qtv, nodes=nodes, forecast=fmeta,
                       negative_deltas=[str(deltas[k]) for k in want_neg])
            key = (ev, cand.kind, cand.rank)
            if key not in seen_keys:
                seen_keys.add(key)
                out.append((rec, rmk))
    if not out:
        raise Declined("every recognized mode declined: " + "; ".join(errors[:6]))
    for rec, _ in out:
        rec["declines"] = errors[:8]
    return out


def total_radius(coll) -> Fr:
    """Every transformation radius of a collective record, summed."""
    return Fr(coll["fit_tv"]) + Fr(coll["rounding_tv"]) + Fr(coll["quadrature_tv"])


def rebuild_residual(marked: MK.Marked, coll, ctx: A.Ctx):
    """Rebuild the residual Marked model from a PARSED collective record and
    the current marked model, re-deriving the fit certificate from the
    factor tables. Used by the executor (fresh process) and by the checker
    (independent reconstruction). Raises Declined if the record's radii are
    not covered by the recomputed certificate."""
    free = marked.free()
    try:
        law = [FX.densify(f, K.CAPS["aggregated_kernel_entries"])
               for f in marked.law_factors()]
    except FX.ViewError as e:
        raise Declined("the residual rebuild needs bounded explicit tables: %s" % e)
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
        deltas = coll.get("deltas") or [coll["delta"]]
        qtv = Fr(0)
        for k in range(cand.rank):
            lat = lattice_for(cand, k, Fr(deltas[k]))
            if cand.signs[k] > 0:
                qtv += Fr(lat["total_bound"])
        if qtv > Fr(coll["quadrature_tv"]):
            raise Declined("the recomputed positive lattice bound %s exceeds the "
                           "recorded %s" % (qtv, coll["quadrature_tv"]))
    return rmk, res, can
