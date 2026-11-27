"""DGP10 Phase B: the EXACT ORACLE / REFERENCE GATE (FROZEN_EXPERIMENT_SPEC section 6 Phase B; brief section 8 item 3). Small finite models whose full target and transition law are enumerated EXACTLY (Fractions): independent variables,
coupled binary / categorical pairs and cycles, a repeated factor on one pair, extreme legal scales (2^-600 entries), a null-move-heavy model, mixed cardinalities with a nonconstant conditional. Per model: (1) the exact target, the
exact conditional projections, the Poisson-response identity f - (I - P)(n f) = q and the response-mean identity E q = pi(X_i = a) (exact); (2) the selected-site observation chain K_i = p Q (A + p Q)^-1 Q built INDEPENDENTLY on the
outside configurations: stochastic, stationary, reversible, PSD (exact LDL^T of Pi K), and the DOMINATION K_i <= (1 - eta) I + eta Pi_i in the pi-Loewner order (exact LDL^T) with the PRODUCTION eta = n g / (1 + n g) from the checked
spectral witness g (the proved gap inequality, theory section 4); (3) the actual production observer on the native kernel: the Q32 enclosures contain the exact conditionals at every visited state (differential), the committed visit
count equals the recorded updates of the site (incl. null moves), the quantized certificate (response_certificate on the kernel's own snapshots at a nontrivial allowance delta = 1e-3) contains the TRUE marginal, is nonvacuous
(radius < 1/2 and below the raw occupation radius on the same trajectory) on the correlated models and near-zero-variance on the independent model; (4) the finite-chain moment-generating function of the normalized squared
observable and of the centered response at tilts of the frozen grid, computed in 60-digit mpmath from the exact observation chain, lies below the CHECKED majorant rho^M for M = 1..24 (NUMERICAL diagnostic, labelled); (5) the scalar
checker: the packet's 11 self-test checks, mutation rejections (lowered rho, lowered radius, U below the observed mean, wrong tilt sign, reversed interval, expired budget) and the degenerate inputs (eta = 1, tiny eta, U = 0, U = B,
p = 0 / 1, constant conditional, tiny delta). Exact rational algebra and numerical diagnostics are labelled distinctly. usage: dgp10_oracle.py OUT.json"""
import sys, os, json, time, math, random, itertools
from fractions import Fraction as F
from types import SimpleNamespace
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'), os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')]
import coarse_envelope as CE, spectral_witness as SW, heatbath_exact as HX, heatbath_native as HN, markov_certificate as MC, response_certificate as RC, checked_tilt as CT
R = {}; T0 = time.time()


def model(name, cards, unaries, edges, scale=F(1)):
    """a tiny pairwise model as the canonical Canon-like namespace (cards, psi, factors=[(scope, values)]); edges = [(i, j, table)] (a repeated (i, j) is a repeated factor)"""
    psi = [[F(v) * scale for v in row] for row in unaries]; factors = [((i, j), [F(v) * scale for v in itertools.chain.from_iterable(tab)]) for (i, j, tab) in edges]
    return SimpleNamespace(name=name, cards=list(cards), psi=psi, factors=factors, orig_of=list(range(len(cards))), fixed_rows={}, scalar=F(1), zero_mass=False)


MODELS = [model('n2_binary_correlated_weak_symmetric', [2, 2], [[1, 1], [1, 1]], [(0, 1, [[6, 5], [5, 6]])]),
          model('n3_binary_cycle_weak_symmetric', [2, 2, 2], [[1, 1], [1, 1], [1, 1]], [(0, 1, [[6, 5], [5, 6]]), (1, 2, [[5, 6], [6, 5]]), (0, 2, [[6, 5], [5, 6]])]),
          model('n2_card3_weak_symmetric_circulant', [3, 3], [[1, 1, 1], [1, 1, 1]], [(0, 1, [[6, 5, 5], [5, 6, 5], [5, 5, 6]])]),
          model('n4_binary_weak_asymmetric_unaries', [2, 2, 2, 2], [[2, 3], [3, 2], [1, 1], [5, 4]], [(0, 1, [[6, 5], [5, 6]]), (1, 2, [[5, 6], [6, 5]]), (2, 3, [[6, 5], [5, 6]]), (0, 3, [[6, 5], [5, 6]])]),
          model('n3_binary_independent', [2, 2, 2], [[1, 3], [2, 5], [4, 1]], []),
          model('n2_binary_repeated_weak_factor', [2, 2], [[1, 1], [1, 1]], [(0, 1, [[6, 5], [5, 6]]), (0, 1, [[7, 6], [6, 7]])]),
          model('n3_mixed_card_2_3_4_weak', [2, 3, 4], [[1, 1], [1, 1, 1], [1, 1, 1, 1]], [(0, 1, [[6, 5, 5], [5, 6, 6]]), (1, 2, [[6, 5, 5, 6], [5, 6, 5, 5], [5, 5, 6, 5]])]),
          model('n2_binary_weak_extreme_scale_2^-600', [2, 2], [[1, 1], [1, 1]], [(0, 1, [[6, 5], [5, 6]])], scale=F(1, 2 ** 600)),
          model('n2_binary_weak_null_move_heavy', [2, 2], [[50, 1], [1, 50]], [(0, 1, [[6, 5], [5, 6]])])]
SYMMETRIC = {'n2_binary_correlated_weak_symmetric', 'n3_binary_cycle_weak_symmetric', 'n2_card3_weak_symmetric_circulant', 'n2_binary_repeated_weak_factor', 'n3_mixed_card_2_3_4_weak', 'n2_binary_weak_extreme_scale_2^-600'}   # uniform unaries + symmetric tables: marginals near 1/k (the frozen centers), the nonvacuity models


def rec(name, ok, **kw):
    R[name] = dict(ok=bool(ok), **kw); print(json.dumps({name: {k: v for k, v in R[name].items() if k in ('ok', 'summary')}}, default=str)[:300], flush=True)


# ---------------------------------------------------------------- exact algebra
def enumerate_target(m):
    states = list(itertools.product(*[range(k) for k in m.cards])); W = []
    for x in states:
        w = F(1)
        for i, row in enumerate(m.psi): w *= row[x[i]]
        for (i, j), vals in m.factors: w *= vals[x[i] * m.cards[j] + x[j]]
        W.append(w)
    Z = sum(W); return states, [w / Z for w in W]


def ldl_psd(A):
    """exact LDL^T of a symmetric Fraction matrix; -> (psd, min pivot); a zero pivot requires a zero row / column (then skipped)"""
    n = len(A); A = [list(r) for r in A]; minp = None
    for j in range(n):
        d = A[j][j]
        if d < 0: return False, d
        minp = d if minp is None else min(minp, d)
        if d == 0:
            if any(A[i][j] != 0 for i in range(j + 1, n)): return False, d
            continue
        for i in range(j + 1, n):
            l = A[i][j] / d
            for k in range(j + 1, n): A[i][k] -= l * A[j][k]
    return True, minp


def mmul(A, B_): return [[sum(A[i][k] * B_[k][j] for k in range(len(B_))) for j in range(len(B_[0]))] for i in range(len(A))]
def inverse(A):
    n = len(A); M_ = [list(r) + [F(int(i == j)) for j in range(n)] for i, r in enumerate(A)]
    for c in range(n):
        p = next(i for i in range(c, n) if M_[i][c] != 0); M_[c], M_[p] = M_[p], M_[c]; d = M_[c][c]; M_[c] = [v / d for v in M_[c]]
        for i in range(n):
            if i != c and M_[i][c] != 0:
                f = M_[i][c]; M_[i] = [a - f * b for a, b in zip(M_[i], M_[c])]
    return [r[n:] for r in M_]


def exact_algebra(m, eta):
    states, pi = enumerate_target(m); n = len(m.cards); hbm = HX.HeatBathModel(m); S = len(states); idx = {x: t for t, x in enumerate(states)}
    # conditional projections Q_i (S x S) and P = (1/n) sum Q_i
    Qs = []
    for i in range(n):
        Q = [[F(0)] * S for _ in range(S)]
        for t, x in enumerate(states):
            q = HX.conditional_exact(hbm, list(x), i)
            for a in range(m.cards[i]): y = list(x); y[i] = a; Q[t][idx[tuple(y)]] = q[a]
        Qs.append(Q)
    P = [[sum(Qs[i][s][t] for i in range(n)) / n for t in range(S)] for s in range(S)]
    ok = True; checks = {}
    checks['P_stochastic_stationary_reversible'] = all(sum(r) == 1 for r in P) and all(sum(pi[s] * P[s][t] for s in range(S)) == pi[t] for t in range(S)) and all(pi[s] * P[s][t] == pi[t] * P[t][s] for s in range(S) for t in range(S)); ok &= checks['P_stochastic_stationary_reversible']
    # Poisson response identity and response-mean identity, exact
    pid = True; mid = True; cond_var_lt = True; nonconst = 0
    for i in range(n):
        for a in range(m.cards[i]):
            f = [F(int(x[i] == a)) for x in states]; q = [sum(Qs[i][s][t] * f[t] for t in range(S)) for s in range(S)]; Pf = [sum(P[s][t] * f[t] for t in range(S)) for s in range(S)]
            resid = [f[s] - n * (f[s] - Pf[s]) for s in range(S)]; pid &= (resid == q); mean_f = sum(pi[s] * f[s] for s in range(S)); mid &= (sum(pi[s] * q[s] for s in range(S)) == mean_f)
            vq = sum(pi[s] * (q[s] - mean_f) ** 2 for s in range(S)); vf = mean_f - mean_f ** 2; cond_var_lt &= (vq <= vf); nonconst += int(vq > 0)
    checks['poisson_identity_exact'] = pid; checks['response_mean_identity_exact'] = mid; checks['conditional_variance_le_indicator'] = cond_var_lt; checks['nonconstant_conditionals'] = nonconst; ok &= pid and mid and cond_var_lt
    # the observation chain per site on the OUTSIDE configurations; domination by (1 - eta) I + eta Pi with the production eta
    dom_ok = True; psd_ok = True; gaps = []
    for i in range(n):
        outs = sorted({x[:i] + x[i + 1:] for x in states}); oidx = {o: u for u, o in enumerate(outs)}; U_ = len(outs); p = F(1, n)
        A = [[F(int(s == t)) - P[s][t] for t in range(S)] for s in range(S)]; Bm = [[A[s][t] + p * Qs[i][s][t] for t in range(S)] for s in range(S)]; Binv = inverse(Bm); L = mmul(mmul(Qs[i], Binv), Qs[i])
        K = [[F(0)] * U_ for _ in range(U_)]; pio = [F(0)] * U_
        for s, x in enumerate(states):
            u = oidx[x[:i] + x[i + 1:]]; pio[u] += pi[s]
            if K[u][0] == 0 and all(v == 0 for v in K[u]):
                for t, y in enumerate(states): K[u][oidx[y[:i] + y[i + 1:]]] += p * L[s][t]
        stoch = all(sum(r) == 1 for r in K); stat = all(sum(pio[u] * K[u][v] for u in range(U_)) == pio[v] for v in range(U_)); rev = all(pio[u] * K[u][v] == pio[v] * K[v][u] for u in range(U_) for v in range(U_))
        PiK = [[pio[u] * K[u][v] for v in range(U_)] for u in range(U_)]; psd, _ = ldl_psd(PiK)
        Khat = [[(1 - eta) * F(int(u == v)) + eta * pio[v] for v in range(U_)] for u in range(U_)]; D_ = [[pio[u] * (Khat[u][v] - K[u][v]) for v in range(U_)] for u in range(U_)]; dom, minpiv = ldl_psd(D_)
        psd_ok &= (stoch and stat and rev and psd); dom_ok &= dom; gaps.append(dict(site=i, outside_states=U_, stochastic=stoch, stationary=stat, reversible=rev, psd=psd, dominated_by_eta_proxy=dom))
    checks['observation_chain_stochastic_stationary_reversible_psd'] = psd_ok; checks['observation_chain_dominated_by_(1-eta)I+eta_Pi_exact'] = dom_ok; ok &= psd_ok and dom_ok
    return ok, checks, dict(states=S, pi=pi, Qs=Qs, P=P, per_site=gaps)


# ---------------------------------------------------------------- the production observer + certificate on the tiny model
def production_run(m, alg, eta, seed=11, delta=F(1, 1000), steps=None):
    hbm = HX.HeatBathModel(m); n = hbm.n; B = CE.Budget(64 << 20); clk = CE.Clock(time.monotonic() + 60, {}); plan = HN.local_checkpoint_plan(); centers = [HN.center_for(k) for k in hbm.cards]
    ch = HN.NativeChain(hbm, [0] * n, seed, clk, budget=B, observer=dict(sites=list(range(n)), centers=centers, plan=plan)); S_ = 1 << 32
    # differential enclosure check at random states
    rng = random.Random(seed); viol = 0; widths = []
    for _ in range(400):
        ch.run(1); x = ch.state(); i = rng.randrange(n); L, U = ch.observe_inspect(i); q = HX.conditional_exact(hbm, x, i)
        for a in range(hbm.cards[i]):
            if not (F(L[a], S_) <= q[a] <= F(U[a], S_)): viol += 1
            widths.append(U[a] - L[a])
    ch.run(2000); ch.set_recording(); ch.observer_start(); total = steps or (n * 3 * 16384 + 7); ch.run(total); occ = ch.flush(); st = ch.observer_state(); snaps = ch.observer_snapshots(); cnt = ch.counters()
    visits_sum = sum(ch.observer_current(q)['count'] for q in range(n)); once = (visits_sum == total) and (st['committed'] == total)
    eta_ = F(eta); n_q = n; Q = sum(hbm.cards); rc_ = RC.response_intervals(snaps, eta_, delta, n_q, Q)
    # truth, coverage, nonvacuity (vs the raw occupation radius at the same recorded count under the raw allocation delta/4 w_1 of the global checkpoint j=1 -- the tiny comparison)
    g_prod = eta_ / (n * (1 - eta_)) if eta_ < 1 else F(1, 2); delta_raw_1 = delta / 4 / 2                                   # the raw occupation family's first global checkpoint allowance (delta / 4) x w_1
    states_ = alg['states']; pi_ = alg['pi']; cov = True; radii = []; raw_r = float(MC.radius_upper(total, Q, delta_raw_1, g_prod)); raw_cov = True
    for i in range(n):
        ps = rc_['per_site'].get(i)
        for a in range(hbm.cards[i]):
            tr = sum(pi_[s] for s, x in enumerate(states_) if x[i] == a); praw = F(occ[i][a], total); raw_cov &= (abs(praw - tr) <= F(raw_r))
            if ps is None: continue
            c = ps['coords'][a]; cov &= (c['lo'] <= tr <= c['hi']); radii.append(float(c['hi'] - c['lo']) / 2)
    ch.close()
    return dict(enclosure_violations=viol, enclosure_width_units_max=(max(widths) if widths else None), observed_once=once, committed=st['committed'], steps=total, null_moves=cnt['null_moves'], exact_fallbacks=cnt['exact_fallbacks'], observer_valid=st['valid'], snapshots_sites=sum(1 for s in snaps if s['j'] is not None), groups=rc_['n_groups'], certified=rc_['n_certified'],
                coverage_true_marginals=cov, raw_coverage=raw_cov, response_radius_max=(max(radii) if radii else None), raw_radius_same_trajectory=raw_r, nonvacuous=(bool(radii) and max(radii) < 0.5 and max(radii) < raw_r), groups_record=[{k: g_[k] for k in ('j', 'k', 'M', 'available', 'reason')} | dict(U=(g_.get('moment') or {}).get('U_float'), mode=(g_.get('moment') or {}).get('mode'), R=(g_.get('mean') or {}).get('R_float')) for g_ in rc_['groups']], live_after_close=B.live, snapshots=snaps, eta=str(eta_))


# ---------------------------------------------------------------- the numerical MGF diagnostic (mpmath; labelled)
def mgf_diagnostic(m, alg, eta, snaps_rec, Ms=range(1, 25)):
    import mpmath as mp; mp.mp.dps = 60; n = len(m.cards); out = []; ok = True
    for i in range(n):
        states = alg['states']; pi = alg['pi']; outs = sorted({x[:i] + x[i + 1:] for x in states}); oidx = {o: u for u, o in enumerate(outs)}; U_ = len(outs); p = F(1, n); S = len(states)
        A = [[F(int(s == t)) - alg['P'][s][t] for t in range(S)] for s in range(S)]; Bm = [[A[s][t] + p * alg['Qs'][i][s][t] for t in range(S)] for s in range(S)]; L = mmul(mmul(alg['Qs'][i], inverse(Bm)), alg['Qs'][i])
        K = [[F(0)] * U_ for _ in range(U_)]; pio = [F(0)] * U_; done = set()
        for s, x in enumerate(states):
            u = oidx[x[:i] + x[i + 1:]]; pio[u] += pi[s]
            if u not in done:
                done.add(u)
                for t, y in enumerate(states): K[u][oidx[y[:i] + y[i + 1:]]] += p * L[s][t]
        hbm = HX.HeatBathModel(m); k = m.cards[i]; C = HN.center_for(k); c = F(C, 1 << 32); Bc = RC.B_of(C)
        for a in range(k):
            # the observable per outside configuration: q_a(x_-i) exactly; Y = (q - c)^2 / B in [0, 1]; Z = q - E q (centered)
            qv = []
            for o in outs:
                x = list(o[:i]) + [0] + list(o[i:]); qv.append(HX.conditional_exact(hbm, x, i)[a])
            mean_q = sum(pio[u] * qv[u] for u in range(U_)); Y = [(v - c) ** 2 / Bc for v in qv]; Z = [v - mean_q for v in qv]; EY = sum(pio[u] * Y[u] for u in range(U_)); vZ = sum(pio[u] * Z[u] ** 2 for u in range(U_))
            for (obs, tilt_sign, label, par) in ((Y, -1, 'moment', EY), (Z, +1, 'mean', vZ)):
                for al in (RC.ALPHAS[0], RC.ALPHAS[40], RC.ALPHAS[-1]):
                    t = F(eta) * al * tilt_sign
                    if label == 'moment': rho = CT.two_point_rho_upper(F(eta), F(0), F(1), (EY if EY <= 1 else F(1)), t)                                      # the majorant at the TRUE mean p = E Y (Bernoulli with the same mean)
                    else:
                        v = min(vZ, F(1, 4)); rho = CT.two_point_rho_upper(F(eta), -v, F(1), v / (1 + v), t)
                    Dm = mp.matrix(U_, U_); Km = mp.matrix(U_, U_)
                    for u in range(U_):
                        Dm[u, u] = mp.e ** (mp.mpf(t.numerator) / t.denominator * (mp.mpf(obs[u].numerator) / obs[u].denominator))
                        for v_ in range(U_): Km[u, v_] = mp.mpf(K[u][v_].numerator) / K[u][v_].denominator
                    pim = mp.matrix([[mp.mpf(pio[u].numerator) / pio[u].denominator for u in range(U_)]]); one = mp.matrix([[1]] * U_); T = Km * Dm; cur = pim * Dm; worst = -mp.inf
                    for M in Ms:
                        mgf = (cur * one)[0]; bound = (mp.mpf(rho.numerator) / rho.denominator) ** M; ratio = mp.log(mgf) - M * mp.log(mp.mpf(rho.numerator) / rho.denominator); worst = max(worst, ratio); cur = cur * T
                    good = worst <= mp.mpf('1e-40'); ok &= bool(good); out.append(dict(site=i, state=a, family=label, alpha=str(al), rho=float(rho), max_log_mgf_minus_M_log_rho=float(worst), ok=bool(good)))
    return ok, out


# ---------------------------------------------------------------- scalar checker mutations
def scalar_checks():
    st = CT.self_test(); checks = dict(st['checks']); eta = F(1, 4); v = F(1, 100); c = F(1); t = F(1, 10); p1 = v / (v + c * c); rho = CT.two_point_rho_upper(eta, -v / c, c, p1, t)
    good = CT.verify_mean_radius(10 ** 6, eta, v, c, t, rho, F(1, 10 ** 6)); R_ = F(good['radius_upper'])
    checks['mut_lowered_rho_rejected'] = not CT.verify_mean_radius(10 ** 6, eta, v, c, t, rho * F(999, 1000), F(1, 10 ** 6))['accepted']
    checks['mut_lowered_radius_rejected'] = not CT.verify_mean_radius(10 ** 6, eta, v, c, t, rho, F(1, 10 ** 6), radius=R_ * F(99, 100))['accepted']
    mom = CT.verify_moment_upper(10 ** 6, eta, F(1), F(1, 100), F(1, 50), F(-1, 10), F(1, 10 ** 6)); checks['moment_valid_accepted'] = mom['accepted']
    checks['mut_U_below_observed_mean_rejected'] = not CT.verify_moment_upper(10 ** 6, eta, F(1), F(1, 100), F(1, 200), F(-1, 10), F(1, 10 ** 6))['accepted']
    checks['mut_positive_tilt_for_moment_refused'] = not CT.verify_moment_upper(10 ** 6, eta, F(1), F(1, 100), F(1, 50), F(1, 10), F(1, 10 ** 6))['accepted']
    checks['mut_negative_tilt_for_mean_refused'] = not CT.verify_mean_radius(10 ** 6, eta, v, c, -t, rho, F(1, 10 ** 6))['accepted']
    try: CT.Interval(F(1), F(0)); checks['reversed_interval_refused'] = False
    except AssertionError: checks['reversed_interval_refused'] = True
    checks['expired_budget_refuses'] = not CT.verify_mean_radius(10 ** 6, eta, v, c, t, rho, F(1, 10 ** 6), budget=CT.Budget(deadline=time.monotonic() - 1))['accepted']
    checks['eta_one_accepts_valid'] = CT.verify_mean_radius(10 ** 6, F(1), v, c, t, CT.two_point_rho_upper(F(1), -v / c, c, p1, t), F(1, 10 ** 6))['accepted']
    checks['tiny_eta_accepts_valid'] = CT.verify_mean_radius(10 ** 6, F(1, 10 ** 6), v, c, t, CT.two_point_rho_upper(F(1, 10 ** 6), -v / c, c, p1, t), F(1, 10 ** 6))['accepted']
    checks['U_zero_is_a_rejection_not_a_crash'] = not CT.verify_moment_upper(10 ** 6, eta, F(1), F(1, 100), F(0), F(-1, 10), F(1, 10 ** 6))['accepted']
    checks['U_equal_B_support_mode'] = CT.verify_moment_upper(10 ** 6, eta, F(1), F(1, 100), F(1), F(-1, 10), F(1, 10 ** 6)).get('mode') == 'support'
    checks['p_zero_moment_y_zero_U_small_accepted_at_large_tilt'] = CT.verify_moment_upper(10 ** 6, eta, F(1), F(0), F(1, 10 ** 4), -eta * 16, F(1, 10 ** 6))['accepted']
    checks['p_zero_moment_y_zero_U_small_rejected_at_small_tilt'] = not CT.verify_moment_upper(10 ** 6, eta, F(1), F(0), F(1, 10 ** 4), F(-1, 10), F(1, 10 ** 6))['accepted']
    checks['constant_observable_zero_radius'] = CT.verify_mean_radius(1, eta, 0, 0, 1, 1, F(1, 100), radius=0)['accepted']
    checks['tiny_delta_accepts_with_larger_radius'] = F(CT.verify_mean_radius(10 ** 6, eta, v, c, t, rho, F(1, 10 ** 12))['radius_upper']) > R_
    checks['near_one_rho_handled'] = isinstance(CT.verify_mean_radius(10 ** 6, F(1, 10 ** 9), v, c, F(1, 10 ** 9), F(1) + F(1, 10 ** 30), F(1, 10 ** 6)).get('accepted'), bool)
    checks['M_too_large_refused'] = not CT.verify_mean_radius(1 << 63, eta, v, c, t, rho, F(1, 10 ** 6))['accepted']
    checks['proposer_grid_81_exact_rationals'] = (len(RC.ALPHAS) == 81 and all(isinstance(a, F) for a in RC.ALPHAS) and RC.ALPHAS[0] == F(1, 64) and RC.ALPHAS[-1] == 16)
    return all(checks.values()), checks


def main():
    out_path = sys.argv[1]; per_model = {}; all_ok = True
    sc_ok, sc = scalar_checks(); rec('scalar_checker_reference_and_mutations', sc_ok, checks=sc, summary='%d / %d' % (sum(sc.values()), len(sc))); all_ok &= sc_ok
    for m in MODELS:
        t0 = time.time(); B = CE.Budget(64 << 20); clk = CE.Clock(time.monotonic() + 60, {}); W = SW.certify(m, B, clk, policy=SW.POLICY_REVISED); g = F(W['g_exact']) if W['eligible'] else None; SW.release_retained(W, B)
        if g is None: per_model[m.name] = dict(ok=False, reason='spectral witness refused: %s' % W.get('refusal')); all_ok = False; continue
        n = len(m.cards); eta = RC.eta_lower(g, n); states, pi = enumerate_target(m)
        ok1, checks, alg = exact_algebra(m, eta); alg['states'] = states
        pr = production_run(m, alg, eta); ok2 = (pr['enclosure_violations'] == 0 and pr['observed_once'] and pr['observer_valid'] and pr['coverage_true_marginals'] and pr['live_after_close'] == 0 and (pr['nonvacuous'] or m.name not in SYMMETRIC))
        ok3, mg = mgf_diagnostic(m, alg, eta, pr['snapshots'])
        per_model[m.name] = dict(ok=bool(ok1 and ok2 and ok3), g_lower=str(g), g_float=float(g), eta=str(eta), eta_float=float(eta), exact_algebra=dict(ok=ok1, **checks), production_observer=dict({k: v for k, v in pr.items() if k != 'snapshots'}, ok=ok2), mgf_diagnostic=dict(ok=ok3, kind='NUMERICAL (mpmath 60 digits): log E_pi exp(t sum Z_s) - M log rho <= 0 for M = 1..24 at three grid tilts per family / coordinate; not a proof', worst=max(x['max_log_mgf_minus_M_log_rho'] for x in mg), n=len(mg)), seconds=time.time() - t0)
        rec(m.name, per_model[m.name]['ok'], summary='exact %s; observer %s (viol %d, once %s, cover %s, r_resp %s vs r_raw %.4f); mgf %s; %.1fs' % (ok1, ok2, pr['enclosure_violations'], pr['observed_once'], pr['coverage_true_marginals'], ('%.4f' % pr['response_radius_max']) if pr['response_radius_max'] else None, pr['raw_radius_same_trajectory'], ok3, time.time() - t0)); all_ok &= per_model[m.name]['ok']
    nonvac = [n_ for n_, r_ in per_model.items() if (r_.get('production_observer') or {}).get('nonvacuous')]
    res = dict(all_ok=bool(all_ok and len(nonvac) >= 3), models=per_model, scalar=R['scalar_checker_reference_and_mutations'], nonvacuous_models=nonvac, nonvacuity_rule='the certified response radius (delta = 1e-3; local snapshot M_j; per-site allowances) is below 1/2 AND below the raw occupation radius on the same trajectory (delta / 8 at the first global checkpoint) on at least three of the symmetric weak models', gate='PASS' if (all_ok and len(nonvac) >= 3) else 'FAIL', labels=dict(exact='Fraction algebra: target, projections, Poisson / response-mean identities, observation chain, PSD and eta-domination (LDL^T)', production='the native observer and the checked certificate on the kernel\'s own snapshots at delta = 1e-3; coverage of the true marginal on the run; nonvacuity vs the raw radius on the same trajectory', numerical='mpmath MGF diagnostic (labelled)'), wall_s=round(time.time() - T0, 2), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(res, open(out_path, 'w'), indent=1, default=str); print(json.dumps(dict(gate=res['gate'], all_ok=res['all_ok'], nonvacuous=nonvac, wall_s=res['wall_s'])))
    sys.exit(0 if res['all_ok'] else 1)


if __name__ == '__main__': main()
