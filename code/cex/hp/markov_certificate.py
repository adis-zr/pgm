"""DGP8 SPECTRAL_HEATBATH, part 3 (DGP9 REPAIRED): the separate MARKOV confidence certificate (brief section 4; theory section 4 'Complete finite-time confidence statement'). Never fed to the accepted IID importance-sampling code. Inputs:
the checked gap g (lower bound), the deterministic x0, the request delta. (1) p0: p(x0) >= W(x0) / Z_U with Z_U = (prod_i k_i)(prod_f max f) -- log W(x0) from the exact rational W(x0) with a rigorous LOWER log enclosure, log Z_U with
rigorous UPPER enclosures (spectral_witness.log_enclosure), so log p0 is a proved lower bound (never binary64 overflow / underflow: everything is exact rational until the end). (2) burn-in t: the smallest integer with
(1/2) sqrt(1 / p0 - 1)(1 - g)^t <= beta, computed outward. (3) radius at a checkpoint with N recorded states, Q indicators and its own delta_j: r = sqrt((2 - g) ln(2 Q / delta_j) / (2 N g)) rounded UP (rational arithmetic with the
upper log enclosure; the square root rounded up); the stationary Leon-Perron inequality + the union bound; the burn-in coupling costs beta; beta + sum_j delta_j <= delta_route. (4) Checkpoint plans are PREDETERMINED before sampling:
policy 'fixed' (DGP8): J = 4 geometric checkpoints N_j = ceil(N_max / 2^(J - j)) to the frozen-rate N_max, delta_j = delta_sample / 4; policy 'revised' (DGP9 mechanism change B): a FINITE increasing sequence N_j = ceil(rho_N^(j - 1) N_1),
j = 1..J_max, with SUMMABLE risks delta_j = delta_sample / (j (j + 1)) (the sum over ALL j is < delta_sample, so any prefix of completed checkpoints is covered by the union bound and the last COMPLETED checkpoint publishes
validly; a deadline-selected count never publishes). (5) Rows (DGP9 repair of the review's RV4): per CANONICAL VARIABLE the accepted epsilon-safe J-box point policy (coarse_envelope.epsilon_safe_points): the row box
[max(0, p_a - r), min(1, p_a + r)] must meet the simplex (sum lo <= 1 <= sum hi), every width <= 2 eps, the points are the J-box normalized / midpoint points, and the endpoint radius max(pt - lo, hi - pt) <= eps is VERIFIED for every
row; the whole variable publishes or none of its rows (the points need the row); wider intervals are enclosures, never completed answers."""
import math
from fractions import Fraction as F
import spectral_witness as SW
PROFILE = dict(beta_share='delta_route / 2', policies=dict(fixed=dict(checkpoints_J=4, checkpoint_rule='N_j = ceil(N_max / 2^(J - j)), j = 1..J (geometric to the frozen-rate N_max; frozen before sampling)', delta_j_rule='delta_sample / J (equal split)'),
                                                        revised=dict(J_max=64, checkpoint_rule='N_j = ceil(rho_N^(j - 1) N_1), j = 1..J_max (finite, increasing; N_1 and rho_N frozen from development cost data before scoring)', delta_j_rule='delta_sample / (j (j + 1)) (summable: sum_j < delta_sample)')),
               concentration='Leon-Perron (2004) Theorem 1 eq. (3) for the stationary reversible chain + union bound over the Q indicators and over the DECLARED checkpoints; the whole post-burn-in path coupled within TV <= beta', rounding='exact rationals with rigorous log enclosures; square roots rounded up',
               publication='accepted epsilon-safe J-box points per variable (coarse_envelope.epsilon_safe_points); endpoint radius <= eps and simplex feasibility verified after point selection')


def _sqrt_up(q):
    """an upper bound of sqrt(q) for a nonnegative Fraction, as a Fraction (via integer square roots)"""
    if q <= 0: return F(0)
    SCALE = 1 << 120; num = q.numerator * SCALE * SCALE // q.denominator + 1; r = math.isqrt(num) + 1; return F(r, SCALE)


def log_Z_upper(hbm, cache=None):
    """ln Z_U = sum_i ln k_i + sum_f ln max f (UPPER enclosure, exact Fraction); the unary weights are inside the per-variable products (max over the unary row included)"""
    tot = F(0)
    for i, k in enumerate(hbm.cards): tot += SW.log_enclosure(F(k), cache)[1] + SW.log_enclosure(max(hbm.psi[i]), cache)[1]
    for (_, _, _, _, vals) in hbm.pairs: tot += SW.log_enclosure(max(vals), cache)[1]
    return tot


def log_W_lower(hbm, x, cache=None):
    """ln W(x) >= sum of the LOWER log enclosures of the selected unary and pair values (each a small rational log; never a logarithm of the huge product)"""
    tot = F(0)
    for i in range(hbm.n): tot += SW.log_enclosure(hbm.psi[i][x[i]], cache)[0]
    for (i, j, ki, kj, vals) in hbm.pairs: tot += SW.log_enclosure(vals[x[i] * kj + x[j]], cache)[0]
    return tot


def log_p0_lower(hbm, x0, cache=None):
    """ln p(x0) >= ln W(x0) - ln Z_U (both sides rigorous exact Fractions); returns (bound, ln W(x0) lower)"""
    lw = log_W_lower(hbm, x0, cache); return lw - log_Z_upper(hbm, cache), lw


def choose_x0(hbm):
    """deterministic initial state: per variable the argmax of the unary weight (ties -> the smallest state id)"""
    return [max(range(k), key=lambda a: (hbm.psi[i][a], -a)) for i, k in enumerate(hbm.cards)]


def burn_in_steps(log_p0_lo, g_lo, beta):
    """the smallest t with (1/2) sqrt(1 / p0 - 1)(1 - g)^t <= beta, outward: since 1 / p0 - 1 < 1 / p0, it suffices that t >= [ln(2 beta) + (1/2) ln p0] / ln(1 - g) (both negative); the numerator uses the LOWER endpoints
    (ln(2 beta) lower, ln p0 lower), the denominator the UPPER (less negative) endpoint of ln(1 - g) -> t is an upper bound of the exact requirement"""
    g = F(g_lo); beta = F(beta); lp = F(log_p0_lo)
    if not (0 < g < 1): raise ValueError('gap must lie in (0, 1)')
    num = SW.log_enclosure(2 * beta)[0] + lp / 2; den = SW.log_enclosure(1 - g)[1]
    if den >= 0: raise ValueError('ln(1 - g) enclosure not negative')
    if num >= 0: return 0, dict(note='the initial TV bound (1/2) sqrt(1 / p0 - 1) is already below beta', log_num_lower=float(num), log_den_upper=float(den))
    t = math.ceil(num / den); return int(max(t, 0)), dict(log_num_lower=float(num), log_den_upper=float(den), rule='t = ceil([ln(2 beta) + ln(p0) / 2] / ln(1 - g)) with 1 / p0 - 1 < 1 / p0')


def radius_upper(N, Q, delta_j, g_lo):
    """r = sqrt((2 - g) ln(2 Q / delta_j) / (2 N g)) rounded UP as a Fraction (g = the gap LOWER bound; a smaller g gives a larger r)"""
    g = F(g_lo); N = int(N); Q = int(Q); d = F(delta_j)
    if N <= 0: return F(1)
    L = SW.log_enclosure(2 * Q / d)[1]; q = (2 - g) * L / (2 * N * g); r = _sqrt_up(q); r = F(math.ceil(r * (1 << 64)), 1 << 64)      # rounded UP to the dyadic grid 2^-64 (readable rows; still an upper bound)
    return min(F(1), r)


def checkpoint_plan(N_max, J=4):
    """policy 'fixed' (DGP8): the geometric checkpoint sequence N_j = ceil(N_max / 2^(J - j)), j = 1..J (strictly increasing, >= 1)"""
    N_max = max(int(N_max), 1); plan = []
    for j in range(1, J + 1):
        Nj = max(1, -(-N_max // (2 ** (J - j))))
        if plan and Nj <= plan[-1]: Nj = plan[-1] + 1
        plan.append(Nj)
    return plan


def checkpoint_plan_revised(N_1, rho_N, J_max):
    """policy 'revised' (DGP9 mechanism change B): N_j = ceil(rho_N^(j - 1) N_1), j = 1..J_max (finite, strictly increasing integers; declared before sampling)"""
    N_1 = max(int(N_1), 1); rho = F(rho_N); plan = []; cur = F(N_1)
    for j in range(J_max):
        Nj = max(1, math.ceil(cur))
        if plan and Nj <= plan[-1]: Nj = plan[-1] + 1
        plan.append(Nj); cur = cur * rho
    return plan


def checkpoint_risks(policy, delta_sample, J):
    """the per-checkpoint risks of a declared plan of length J: fixed -> delta_sample / J each (sum = delta_sample); revised -> delta_sample / (j (j + 1)) (sum over j = 1..J is delta_sample J / (J + 1) < delta_sample)"""
    ds = F(delta_sample)
    if policy == 'fixed': return [ds / J] * J
    return [ds / (j * (j + 1)) for j in range(1, J + 1)]


def rows_from_counts(occ, N, r, eps, orig_of, fixed_rows):
    """-> (published rows {(var, state): (lo, hi, point, 'PAC_MARKOV')}, enclosures [(var, state, lo, hi)], stats) over the ORIGINAL query inventory: canonical variable i -> original var orig_of[i]; fixed / factorless rows come exactly
    from canonicalization (fixed_rows). Per canonical variable: the interval [p_a - r, p_a + r] clipped to [0, 1] for every state; the variable PUBLISHES iff every width <= 2 eps, the row box meets the simplex and the accepted
    epsilon-safe points (coarse_envelope.epsilon_safe_points) satisfy lo <= pt <= hi and max(pt - lo, hi - pt) <= eps on EVERY row (verified after selection); otherwise every row of the variable is an enclosure."""
    from coarse_envelope import epsilon_safe_points
    pub = {}; enc = []; widths = []; N = int(N); r = F(r); eps = F(eps); st = dict(variables=0, variables_published=0, point_policy_counts={}, simplex_violations=0, endpoint_violations=0)
    for i, row in enumerate(occ):
        v = orig_of[i] if orig_of is not None else i; st['variables'] += 1
        box = []
        for a, c in enumerate(row):
            p = F(int(c), N) if N > 0 else F(1, 2); lo = max(F(0), p - r); hi = min(F(1), p + r); widths.append(float(hi - lo)); box.append((lo, hi, 'PAC_MARKOV'))
        s_lo = sum(b[0] for b in box); s_hi = sum(b[1] for b in box); meets = (s_lo <= 1 <= s_hi)
        if not meets: st['simplex_violations'] += 1
        ok = meets and all(b[1] - b[0] <= 2 * eps for b in box) and all(F(0) <= b[0] <= b[1] <= F(1) for b in box)
        pts = None
        if ok:
            pts, policy = epsilon_safe_points(box, eps); st['point_policy_counts'][policy] = st['point_policy_counts'].get(policy, 0) + 1
            ok = all(b[0] <= p_ <= b[1] and max(p_ - b[0], b[1] - p_) <= eps for b, p_ in zip(box, pts))
            if not ok: st['endpoint_violations'] += 1
        if ok:
            st['variables_published'] += 1
            for a, (b, p_) in enumerate(zip(box, pts)): pub[(v, a)] = (b[0], b[1], p_, 'PAC_MARKOV')
        else:
            for a, b in enumerate(box): enc.append((v, a, b[0], b[1]))
    return pub, enc, dict(st, max_width=(max(widths) if widths else None), radius=float(r))
