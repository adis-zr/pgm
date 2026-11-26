"""DGP7 RESIDUAL_JOINT, part 2: the FLOATING proposal side (theory sections 4-5; brief sections 4-5) -- window planning, context weights, the local table F, the water-filling row solver and the bounded joint fit. Nothing here is a
certificate fact: every quantity is advisory and the selected actual candidate is recomputed and certified by check_residual.local_kernel. Frozen profile (brief section 4): the DGP6 G1 parent rule (select_g1, family volume 4,096) frozen per
request; active windows A of 2 or 4 consecutive sampling-order variables; region R = A + old / target families + selected atom scopes with |R| states <= 65,536; <= 16 atoms per window (greedy by stored score, stable ids, contained atoms
first); every atom touches A and contains no later-sampled variable; R \\ A precedes A; <= 8 windows per transaction ranked by retained score / frozen predicted work (ties: position, length, ids); WHOLE_MODEL_REGION labelled. Context
weights: the exact normalized proposal product when C is parent-closed in the CURRENT DAG, else 1,024 fresh ancestral draws from the current proposal (a separate advisory RNG; (count + 1 / N_C) / 1,025); frozen per candidate; uniform
weights only as a labelled negative diagnostic. Objective G_nu = sum_c nu(c) sum_a F^2 / q'_A under the common pointwise cap kappa_fit = kappa_publish / (1 + 2^-20); rows by water filling theta = max(l, sqrt(A / lambda)) with a monotone
lambda solve; <= 8 sweeps in sampling order; the best completed FEASIBLE iterate; exact D = 2^40 quantization (global_optimize.quantize_rows_exact); candidate quantities recomputed for the ACTUAL counts; ranking by (G_new / G_ref) (d_new /
d_current) < 0.99. The unrestricted conditional q* = F / Z_c gives the optimistic headroom K* = max_c Z_c, T2* = Z_c^2 (never installed)."""
import math, itertools, hashlib
import numpy as np
import coarse_envelope as CE
import joint_proposal as JP, joint_optimize as JO, global_optimize as GO
from joint_proposal import vol_of, D, D_BITS, Conditional, Proposal
from residual_max_envelope import log2_up
PROFILE_RESIDUAL = dict(window_sizes=(2, 4), max_region=65536, max_atoms_per_window=16, max_windows=8, sweeps=8, max_transactions=2, context_samples=1024, cap_margin=1.1, fit_reserve=2 ** -20, promote_ratio=0.99, V_family=4096, same_law_min_gain=0.01, fit_share=0.40,
                        # FROZEN affine time blocks (seconds) fitted on the development panel (dgp7_rates.py; controls/dev/rates_panel_3.json: 68 synthetic windows, volumes to 65,536, active 2 / 4, atoms 1-16, cardinalities 2-32; nonnegative least squares x the 90th-percentile observed / predicted ratio): setup + per-cell floating + per-cell compact (kernel) + per context draw + output preparation
                        t_setup_s=0.0408088, t_float_cell_s=5.04861e-08, t_compact_cell_s=6.767e-07, t_context_sample_s=8.3234e-07, t_output_s=0.002)
LN2 = math.log(2.0)


def freeze_target_parents(prop, pairs, cards, V_family=4096):
    """the DGP6 G1 parent map (frozen per request); alias G0 when no extension is legal"""
    parents, rec = GO.select_g1(prop, pairs, cards, V_family); return parents, rec


def predicted_work_s(vol, n_active, n_atoms, p=PROFILE_RESIDUAL):
    """the frozen scheduling heuristic for one window: setup + floating fit (sweeps x active x cells) + kernel (2 passes x cells x (active + atoms) compact ops) + output"""
    return p['t_setup_s'] + p['t_float_cell_s'] * vol * (p['sweeps'] * n_active + n_atoms + 4) + p['t_compact_cell_s'] * vol * (2 + n_active + n_atoms) + p['t_output_s']


def plan_windows(state, prop, parents_target, cards, order, profile=PROFILE_RESIDUAL):
    """-> (windows ranked and limited to max_windows, excluded list). Each window: A, R (sampling-order sorted), C, atoms (ids), vol, score, predicted_work_s, whole_model_region, bank_version, target_parents"""
    pos = {v: i for i, v in enumerate(order)}; n = len(order); live = sorted(state.live_atoms(), key=lambda a: (-a.score, a.aid)); cands = []; excluded = []
    for size in profile['window_sizes']:
        for i in range(0, n - size + 1):
            A = order[i:i + size]; last = pos[A[-1]]
            R = set(A)
            for v in A: R |= set(prop.conds[v].parents) | set(parents_target[v])
            if any(pos[x] >= pos[A[0]] for x in R if x not in A): excluded.append(dict(A=A, why='a parent does not precede the window (should not happen: parents are earlier)')); continue
            base_vol = vol_of(tuple(R), cards)
            if base_vol > profile['max_region']: excluded.append(dict(A=A, why='families alone exceed the region cap (%d)' % base_vol)); continue
            elig = [a for a in live if (set(a.axes) & set(A)) and max(pos[x] for x in a.axes) <= last]
            chosen = []; Rcur = set(R)
            for a in sorted(elig, key=lambda a: (not set(a.axes) <= Rcur, -a.score, a.aid)):                     # contained atoms first, then by score
                if len(chosen) >= profile['max_atoms_per_window']: break
                u = Rcur | set(a.axes)
                if vol_of(tuple(u), cards) <= profile['max_region']: chosen.append(a); Rcur = u
            if not chosen: excluded.append(dict(A=A, why='no compatible atom (touching A, no later variable, inside the region cap)')); continue
            Rs = tuple(sorted(Rcur, key=lambda x: pos[x])); vol = vol_of(Rs, cards); score = sum(a.score for a in chosen); work = predicted_work_s(vol, len(A), len(chosen), profile)
            cands.append(dict(A=list(A), R=list(Rs), C=[x for x in Rs if x not in A], atoms=[a.aid for a in chosen], vol=vol, score=score, predicted_work_s=work, rank_key=(-(score / max(work, 1e-9)), pos[A[0]], len(A), tuple(a.aid for a in chosen)), whole_model_region=(len(Rs) == len(cards)), bank_version=state.version, target_parents={v: tuple(parents_target[v]) for v in A}, max_vol=profile['max_region']))
    # merge duplicate (A, atoms) specifications by identity
    seen = {}; uniq = []
    for w in cands:
        k = (tuple(w['A']), tuple(w['atoms']))
        if k in seen: continue
        seen[k] = True; uniq.append(w)
    uniq.sort(key=lambda w: w['rank_key'])
    for w in uniq[profile['max_windows']:]: excluded.append(dict(A=w['A'], atoms=w['atoms'], why='ranked beyond the %d-window limit (score / work %.3g)' % (profile['max_windows'], -w['rank_key'][0])))
    return uniq[:profile['max_windows']], excluded


def region_assignments(R, cards):
    """(vol, |R|) int array of every assignment of the region (row-major over R)"""
    sizes = [cards[x] for x in R]; grids = np.indices(sizes).reshape(len(R), -1).T if R else np.zeros((1, 0), dtype=np.int64); return grids.astype(np.int64)


def row_and_state(cond, asg, rpos):
    row = np.zeros(asg.shape[0], dtype=np.int64)
    for p_ in cond.parents: row += asg[:, rpos[p_]] * cond.pstrides[p_]
    return row, asg[:, rpos[cond.z]]


def context_weights(prop, C, cards, order, rng, asg, rpos, n_samples=1024, mode='auto'):
    """-> (nu over the region assignments (per-assignment weight of its context), record). mode 'auto': exact when C is parent-closed in the CURRENT DAG else sampled; 'uniform' = the labelled negative diagnostic"""
    import check_residual as CR
    if not C: return np.ones(asg.shape[0]), dict(mode='empty_context')
    cstr = CE.strides([cards[x] for x in C]); ckey = np.zeros(asg.shape[0], dtype=np.int64)
    for j, x in enumerate(C): ckey += asg[:, rpos[x]] * cstr[j]
    nC = vol_of(tuple(C), cards)
    if mode == 'uniform': return np.full(asg.shape[0], 1.0 / nC), dict(mode='uniform (negative diagnostic)', N_C=nC)
    if CR.parent_closed(prop, C):
        lp = np.zeros(asg.shape[0])
        for c in C:
            cond = prop.conds[c]; row, st = row_and_state(cond, asg, rpos); lp += np.log(cond.counts[row, st].astype(float)) - D_BITS * LN2
        p = np.exp(lp)                                                                                   # the exact proposal product per assignment (the SAME value for every assignment sharing the context)
        # normalize over distinct contexts (sum over contexts of p(c) = 1 up to float; use the floating normalization)
        tot = np.bincount(ckey, weights=p, minlength=nC); dist = np.zeros(nC); dist[:] = tot / max(tot.sum(), 1e-300) if False else tot          # tot already holds p(c) x (#assignments per context) -> divide
        per_ctx_count = np.bincount(ckey, minlength=nC).astype(float); dist = np.where(per_ctx_count > 0, tot / np.maximum(per_ctx_count, 1), 0.0); dist = dist / max(dist.sum(), 1e-300)
        return dist[ckey], dict(mode='exact (parent-closed in the current DAG)', N_C=nC, normalization=float(dist.sum()))
    X, _ = prop.sample(rng, n_samples); key = np.zeros(n_samples, dtype=np.int64)
    for j, x in enumerate(C): key += X[:, x] * cstr[j]
    cnt = np.bincount(key, minlength=nC).astype(float); dist = (cnt + 1.0 / nC) / (n_samples + 1.0); return dist[ckey], dict(mode='sampled (%d advisory draws from the current proposal; (count + 1 / N_C) / (n + 1))' % n_samples, N_C=nC, distinct_contexts_seen=int((cnt > 0).sum()))


def local_table(prop, window, atoms, cards, asg, rpos):
    """log F(s) = log q_A,old(s) + sum_j log rho_j(s) over the region assignments (floats; -inf preserved); also log q_A,old and the per-atom logs"""
    A = window['A']; lq = np.zeros(asg.shape[0])
    for v in A:
        cond = prop.conds[v]; row, st = row_and_state(cond, asg, rpos); lq += np.log(cond.counts[row, st].astype(float)) - D_BITS * LN2
    lr = np.zeros(asg.shape[0])
    for a in atoms:
        idx = [rpos[x] for x in a.axes]; flat = np.zeros(asg.shape[0], dtype=np.int64); st = CE.strides([cards[x] for x in a.axes])
        for j, x in enumerate(a.axes): flat += asg[:, idx[j]] * st[j]
        vals = np.array([(x[0] * LN2 + math.log(x[1])) if x[1] else -np.inf for x in a.arr.reshape(-1)]); lr += vals[flat]
    return lq + lr, lq


def waterfill(Acoef, lower, incumbent):
    """single-row form (controls / references): see waterfill_rows"""
    th, info = waterfill_rows(np.asarray(Acoef, dtype=float)[None, :], np.asarray(lower, dtype=float)[None, :], np.asarray(incumbent, dtype=float)[None, :])
    if info['infeasible_rows']: return None, 'infeasible: sum of lower bounds %.6g > 1' % float(np.maximum(lower, 0.0).sum())
    return th[0], ('zero coefficients: incumbent allocation kept' if info['zero_rows'] else 'ok')


def waterfill_rows(coef, lower, incumbent, iters=120):
    """ROW-VECTORIZED water filling: per row r minimize sum_a A_ra / theta_ra s.t. theta_ra >= l_ra, sum_a theta_ra = 1 -> theta_ra = max(l_ra, sqrt(A_ra / lambda_r)) with lambda_r by a monotone bisection in log lambda
    (scale-free: A is normalized per row); an infeasible row (sum l > 1) keeps its incumbent; a zero-coefficient row keeps a feasible allocation of its incumbent (l + the remaining mass in the incumbent's proportions);
    -> (theta (R, k), info)"""
    coef = np.asarray(coef, dtype=float); lower = np.maximum(np.asarray(lower, dtype=float), 0.0); inc = np.maximum(np.asarray(incumbent, dtype=float), 0.0); R, k = coef.shape
    if not np.isfinite(coef).all(): raise ValueError('non-finite water-fill coefficients')
    slack = 1.0 - lower.sum(axis=1); infeasible = slack < -1e-12; amax = coef.max(axis=1); zero = amax <= 0.0
    th = inc / np.maximum(inc.sum(axis=1, keepdims=True), 1e-300)                                                                            # default: the incumbent
    zr = zero & ~infeasible
    if zr.any(): th[zr] = lower[zr] + np.maximum(slack[zr], 0.0)[:, None] * th[zr]
    act = ~zero & ~infeasible
    if act.any():
        A = coef[act] / amax[act][:, None]; L = lower[act]; lo = np.full(A.shape[0], -80.0); hi = np.full(A.shape[0], 80.0)
        for _ in range(iters):
            mid = 0.5 * (lo + hi); g = np.maximum(L, np.sqrt(A * np.exp(-mid)[:, None])).sum(axis=1); up = g > 1.0; lo = np.where(up, mid, lo); hi = np.where(up, hi, mid)
        t = np.maximum(L, np.sqrt(A * np.exp(-hi)[:, None])); t = t / t.sum(axis=1, keepdims=True); t = np.maximum(t, L); t = t / t.sum(axis=1, keepdims=True); th[act] = t
    return th, dict(infeasible_rows=int(infeasible.sum()), zero_rows=int(zr.sum()), active_rows=int(act.sum()))


def fit_window(prop, window, atoms, cards, order, nu_mode, rng, kappa_seed, profile=PROFILE_RESIDUAL, clock=None, deadline=None):
    """the bounded joint fit of one window: returns dict(status, conds_new (quantized Conditionals on the target parents), G_ref, G_new_float, G_new_actual, K_float_ref, K_float_new_actual, sweeps, rows_changed, headroom, context, seconds)"""
    t0 = CE.tnow(); A = list(window['A']); R = list(window['R']); C = list(window['C']); rpos = {x: i for i, x in enumerate(R)}; asg = region_assignments(R, cards); vol = asg.shape[0]
    nu, crec = context_weights(prop, C, cards, order, rng, asg, rpos, profile['context_samples'], mode=nu_mode)
    logF, lq_old = local_table(prop, window, atoms, cards, asg, rpos); fin = np.isfinite(logF); K_ref_float = float(np.exp((logF - lq_old)[fin]).max()) if fin.any() else 0.0
    kappa_publish = min(profile['cap_margin'] * K_ref_float, kappa_seed); kappa_fit = kappa_publish / (1.0 + profile['fit_reserve']); log_kappa = math.log(max(kappa_fit, 1e-300))      # Cmax = min(1.1 B_ref, 1.1 initial_seed_cap) in envelope units (B_ref from the FLOAT K_ref: the exact gate is the kernel's)
    # the current block law on the TARGET parents (replicated rows): per active variable a (R_rows x k) probability table
    tp = window['target_parents']; rows = {}; rowidx = {}; stidx = {}
    for v in A:
        cond_t = prop.conds[v] if tuple(prop.conds[v].parents) == tuple(tp[v]) else prop.conds[v].replicate(tuple(tp[v]), cards); th = cond_t.counts.astype(float) / float(D); rows[v] = th
        row = np.zeros(vol, dtype=np.int64)
        for p_ in cond_t.parents: row += asg[:, rpos[p_]] * cond_t.pstrides[p_]
        rowidx[v] = row; stidx[v] = asg[:, rpos[v]]
    def log_qA(rows_):
        lq = np.zeros(vol)
        for v in A: lq += np.log(np.maximum(rows_[v][rowidx[v], stidx[v]], 1e-300))
        return lq
    def objective(rows_):
        lq = log_qA(rows_); val = np.where(fin, np.exp(2 * logF - lq), 0.0); G = float((nu * val).sum()); K = float(np.exp((logF - lq)[fin]).max()) if fin.any() else 0.0; return G, K
    G_ref, K_ref = objective(rows); incumbent_feasible = (K_ref <= kappa_fit * (1 + 1e-9))
    # the optimistic unrestricted headroom q* = F / Z_c (never installed)
    if C:
        cstr = CE.strides([cards[x] for x in C]); ckey = np.zeros(vol, dtype=np.int64)
        for j, x in enumerate(C): ckey += asg[:, rpos[x]] * cstr[j]
        Z = np.bincount(ckey, weights=np.where(fin, np.exp(logF), 0.0), minlength=vol_of(tuple(C), cards)); Kstar = float(Z.max()); T2star = float((np.bincount(np.arange(Z.size), weights=np.zeros(Z.size)) + Z ** 2).max()); Gstar = float(sum(nu[ckey == c].mean() * Z[c] ** 2 if (ckey == c).any() else 0.0 for c in range(Z.size))) if Z.size <= 4096 else None
    else: Z = np.array([float(np.where(fin, np.exp(logF), 0.0).sum())]); Kstar = float(Z[0]); T2star = float(Z[0] ** 2); Gstar = T2star
    headroom = dict(K_star=Kstar, log2_K_star=(math.log2(Kstar) if Kstar > 0 else -math.inf), T2_star_max=T2star, G_star=Gstar, log2_G_ref_over_G_star=((math.log2(G_ref / Gstar)) if (Gstar and Gstar > 0 and G_ref > 0) else None), note='the UNRESTRICTED conditional optimum q* = F / Z_c: an optimistic headroom bound; never installed when outside G1 / full support')
    if not incumbent_feasible: return dict(status='INCUMBENT_INFEASIBLE_UNDER_FIT_CAP', G_ref=G_ref, K_float_ref=K_ref, kappa_fit=kappa_fit, kappa_publish=kappa_publish, context=crec, headroom=headroom, seconds=CE.tnow() - t0, note='the stricter fitting constraint excludes the current block law: no changed-law fitting (same-law compression only)')
    best = dict(rows={v: rows[v].copy() for v in A}, G=G_ref, K=K_ref, sweep=0); cur = {v: rows[v].copy() for v in A}; sweeps_done = 0; progress = True; infeasible_rows = 0; zero_rows = 0
    for sweep in range(profile['sweeps']):
        if deadline is not None and CE.tnow() >= deadline: break
        if not progress: break
        progress = False
        for v in A:
            if clock is not None: clock.poll('fit sweep %d variable %d' % (sweep, v))
            lq_minus = np.zeros(vol)
            for w in A:
                if w != v: lq_minus += np.log(np.maximum(cur[w][rowidx[w], stidx[w]], 1e-300))
            k = cards[v]; nrows = cur[v].shape[0]; key = rowidx[v] * k + stidx[v]
            coef = np.bincount(key, weights=np.where(fin, nu * np.exp(2 * logF - lq_minus), 0.0), minlength=nrows * k).reshape(nrows, k)
            lb = np.full(nrows * k, 0.0); lbv = np.where(fin, np.exp(logF - lq_minus - log_kappa), 0.0); np.maximum.at(lb, key, lbv); lb = lb.reshape(nrows, k)
            new, winfo = waterfill_rows(coef, lb, cur[v]); infeasible_rows += winfo['infeasible_rows']; zero_rows += winfo['zero_rows']; cur[v] = new
        sweeps_done = sweep + 1; G, K = objective(cur)
        if math.isfinite(G) and K <= kappa_fit * (1 + 1e-9) and G < best['G'] * (1 - 1e-6): best = dict(rows={v: cur[v].copy() for v in A}, G=G, K=K, sweep=sweeps_done); progress = True
    if best['sweep'] == 0: return dict(status='NO_IMPROVEMENT', G_ref=G_ref, G_new_float=G_ref, K_float_ref=K_ref, sweeps=sweeps_done, infeasible_rows=infeasible_rows, zero_rows=zero_rows, context=crec, headroom=headroom, kappa_fit=kappa_fit, kappa_publish=kappa_publish, seconds=CE.tnow() - t0)
    # exact quantization of the best feasible iterate -> actual counts -> recompute for the ACTUAL law
    conds_new = {}; changed = 0
    for v in A:
        counts = GO.quantize_rows_exact(best['rows'][v], cards[v]); conds_new[v] = Conditional(v, tuple(tp[v]), counts, cards); base = prop.conds[v] if tuple(prop.conds[v].parents) == tuple(tp[v]) else prop.conds[v].replicate(tuple(tp[v]), cards); changed += int(not np.array_equal(counts, base.counts))
    rows_act = {v: conds_new[v].counts.astype(float) / float(D) for v in A}; G_act, K_act = objective(rows_act)
    return dict(status=('CANDIDATE' if changed else 'QUANTIZED_TO_INCUMBENT'), conds_new=conds_new, rows_changed=changed, G_ref=G_ref, G_new_float=best['G'], G_new_actual=G_act, K_float_ref=K_ref, K_float_new=best['K'], K_float_new_actual=K_act, kappa_fit=kappa_fit, kappa_publish=kappa_publish, feasible_actual=(K_act <= kappa_publish * (1 + 1e-12)), sweeps=sweeps_done, best_sweep=best['sweep'], infeasible_rows=infeasible_rows, zero_rows=zero_rows, context=crec, headroom=headroom, proxy_ratio_G=(G_act / G_ref if G_ref > 0 else None), seconds=CE.tnow() - t0)


def work_proxy(prop, conds_new, arity_sum, K):
    """d_new / d_current from the frozen physical per-draw work proxy with the ACTUAL represented parents"""
    conds = dict(prop.conds); conds.update(conds_new or {}); newp = Proposal(prop.cards, conds, prop.order, prop.B, prop.S, dict(kind='proxy')); return newp.work(arity_sum, K) / prop.work(arity_sum, K)
