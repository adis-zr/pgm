"""DGP10 QUERY RESPONSE, part 1: the CHECKED conditional-response certificate (theory sections 4-6; brief sections 5-6; FROZEN_EXPERIMENT_SPEC section 5). Inputs: the checked spectral gap lower bound g of the random-scan chain
(spectral_witness), the active variable count n after canonicalization, the observer snapshots of heatbath_native (per queried site the latest COMPLETED local checkpoint: count M = M_j, the fixed center C, the uint128 sums
first_lo / first_hi / second_hi over the Q32 enclosures of the EXACT conditionals), the request risk delta and the inventory sizes n_q (queried active variables) and Q (queried active coordinates).
  * eta = n g / (1 + n g): the proved lower bound of the gap of the selected-site observation chain (theory section 4; exact rational from the exact g lower bound; increasing in g).
  * risks (section 6): beta = delta / 2 once (the deterministic burn-in coupling of the whole future path; charged by the runner), raw occupation family delta / 4 (the runner's revised global plan), moment family delta / 8 and mean
    family delta / 8 with the summable checkpoint weights w_j = 1 / (j (j + 1)): delta_m(i, j) = delta w_j / (8 n_q) per variable, delta_b(i, a, j) = delta w_j / (8 Q) per coordinate (its two tails inside the scalar test).
  * per snapshot (section 5): B = max(C^2, (S - C)^2) / S^2; y_upper = second_hi / (M S^2) (an upper bound of the observed average of Y = (r - c)^2 over the M visits); mean_lo = first_lo / (M S), mean_hi = first_hi / (M S).
    MOMENT: the floating PROPOSER searches U in [y_upper, B] (normalized to [0, 1]) and the 81 frozen rational tilts -s = -eta alpha for the smallest U whose two-state lower-tail bound M [log rho(p = U / B, -s) + s y_upper / B] <= log
    delta_m holds in binary64; the EXACT CHECKER (checked_tilt = the packet's reference_checked_tilt.py, byte-identical, exact Fractions, outward exp / log enclosures, sqrt-free PSD root check) verifies the proposed (U, s, rho_up); a
    failed check widens U (never clamps a too-small U into a success) and after the frozen retries falls back to the deterministic U = B (support mode, no statistical test). MEAN: v = min(U B, 1 / 4) (C = 1: the centered
    response has |Z| <= 1), the two-point majorant {-v, 1} with probability v / (1 + v) on 1, positive tilt t = eta alpha chosen by the proposer, the checker verifies rho_up and RETURNS the radius R with M [log rho - t R] <= log
    (delta_b / 2) (outward). Interval [mean_lo - R, mean_hi + R] cap [0, 1].
  * grouping (brief section 4): coordinates are grouped by (eta, M_j, j, C, B) = (j, k); one moment bound / one radius per group from the MAXIMUM of the per-category square averages in the group (conservative under the per-variable
    allocation: a lower-tail event for the maximum implies the lower-tail event of a category attaining the true maximum); each coordinate keeps its own mean interval.
  * intersection with the raw occupation interval of the same coordinate (both families covered by the shared allocation); an empty intersection is a typed CONFLICT for the variable (no invented coordinate).
Nothing floating authorizes publication: every published U / R is the checker's own returned value; a check that cannot be completed (refusal, deadline) leaves the family unavailable for that group."""
import math
from fractions import Fraction as F
import coarse_envelope as CE
import checked_tilt as CT
S = 1 << 32
ALPHAS = sorted(set([F(2) ** k * (1 + F(j, 8)) for k in range(-6, 4) for j in range(8)] + [F(16)])); assert len(ALPHAS) == 81
ALPHAS_F = [float(a) for a in ALPHAS]
MOMENT_RETRIES = 6; MOMENT_WIDEN = F(257, 256); RHO_MARGIN = F(1 + 2 ** -40); CHECK_BITS = 80
PROFILE = dict(eta='eta = n g / (1 + n g) (exact rational from the exact gap lower bound; theory section 4)', center='C = round(2^32 / k), ties to the smaller integer', B='max(C^2, (S - C)^2) / S^2', tilts='81 exact rationals alpha = 2^k (1 + j / 8), k = -6..3, j = 0..7, plus 16; moment tilt -eta alpha on the normalized observable Y / B in [0, 1]; mean tilt +eta alpha on the centered response (C = 1)',
               moment='proposer: bisection over U in [y_upper, B] x the 81 tilts in binary64; checker: checked_tilt.verify_moment_upper(M, eta, 1, y / B, U / B, -s, delta_m, rho = rho_float (1 + 2^-40)); %d retries widening U by %s; fallback U = B (deterministic)' % (MOMENT_RETRIES, str(MOMENT_WIDEN)),
               mean='v = min(U, 1 / 4); support {-v, 1}, p = v / (1 + v); proposer picks the tilt minimizing the binary64 radius; checker: checked_tilt.verify_mean_radius(M, eta, v, 1, t, rho_up, delta_b) returns the outward radius', risks='beta = delta / 2 (burn-in, once); raw delta / 4 (global checkpoints, w_j); moment delta w_j / (8 n_q) per variable; mean delta w_j / (8 Q) per coordinate (two tails inside)',
               grouping='by (j, k): max of per-category square averages; one U / R per group; own mean interval per coordinate', intersection='raw cap response per coordinate; empty -> typed CONFLICT for the variable', checker_bits=CHECK_BITS, reference='checked_tilt.py = dgp10_theory/reference_checked_tilt.py (byte-identical copy; sha256 in FREEZE.json)')


def eta_lower(g_lower, n):
    """the proved lower bound of the observation-chain gap: eta = n g / (1 + n g), exact, increasing in g (so a lower bound of g gives a lower bound of eta)"""
    g = F(g_lower); n = int(n)
    if not (0 < g < 1) or n < 1: raise ValueError('gap / n outside the valid range')
    return (n * g) / (1 + n * g)


def weight(j): return F(1, j * (j + 1))


def risk_allocation(delta, n_q, Q, j):
    """the per-variable moment allowance and the per-coordinate mean allowance at local checkpoint j (1-based)"""
    delta = F(delta); w = weight(j); return dict(w_j=w, delta_m=delta * w / (8 * n_q), delta_b=delta * w / (8 * Q))


def total_risk(delta, J_raw, J_local):
    """beta + raw + moment + mean totals over EVERY declared checkpoint (any completed prefix is covered): must be <= delta"""
    delta = F(delta); sr = sum(weight(j) for j in range(1, J_raw + 1)); sl = sum(weight(j) for j in range(1, J_local + 1))
    return delta / 2 + (delta / 4) * sr + (delta / 8) * sl + (delta / 8) * sl


def B_of(C, S_=S): C = int(C); return F(max(C * C, (S_ - C) * (S_ - C)), S_ * S_)


# ---------------------------------------------------------------- the floating PROPOSER (never authorizes anything)
def _rho_f(eta, z0, z1, p1, t):
    lam = 1.0 - eta; d0 = (lam + eta * (1.0 - p1)) * math.exp(t * z0); d1 = (lam + eta * p1) * math.exp(t * z1); off2 = eta * eta * p1 * (1.0 - p1) * math.exp(t * (z0 + z1))
    return 0.5 * (d0 + d1) + math.sqrt(0.25 * (d0 - d1) ** 2 + off2)


def propose_moment(M, eta_f, y_f, delta_m_f):
    """-> (U_norm, alpha_index, rho_float) for the smallest normalized U in [y, 1] whose best-tilt lower-tail bound meets log delta_m in binary64, or None when even U -> 1 fails (then the deterministic support bound applies)"""
    ld = math.log(delta_m_f)
    def best(U):
        b = (math.inf, None, None)
        for ix, al in enumerate(ALPHAS_F):
            s = eta_f * al; r = _rho_f(eta_f, 0.0, 1.0, U, -s); v = M * (math.log(r) + s * y_f)
            if v < b[0]: b = (v, ix, r)
        return b
    hi = min(1.0, max(y_f, 1e-300)); hb = best(1.0 - 1e-9)
    if hb[0] > ld: return None
    lo = y_f; hi = 1.0 - 1e-9; last = (hi, hb[1], hb[2])
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi: break
        b = best(mid)
        if b[0] <= ld: hi = mid; last = (mid, b[1], b[2])
        else: lo = mid
    return last


def propose_mean(M, eta_f, v_f, delta_b_f):
    """-> (alpha_index, rho_float, R_float) minimizing the binary64 radius over the 81 tilts (C = 1: support {-v, 1}, p = v / (1 + v))"""
    pen = math.log(2.0 / delta_b_f); b = (math.inf, None, None)
    for ix, al in enumerate(ALPHAS_F):
        t = eta_f * al; r = _rho_f(eta_f, -v_f, 1.0, v_f / (1.0 + v_f), t); R = (math.log(r) + pen / M) / t
        if R < b[0]: b = (R, ix, r)
    return b[1], b[2], b[0]


def _dyadic_up(x, bits=60):
    """a dyadic Fraction >= x (binary64 x -> exact), then widened by RHO_MARGIN"""
    q = F(x) * RHO_MARGIN; n = -((-q.numerator * (1 << bits)) // q.denominator); return F(n, 1 << bits)


# ---------------------------------------------------------------- the CHECKED certificate of one group
def certify_group(M, eta, y_norm, B, delta_m, delta_b, clock=None, deadline=None, bits=CHECK_BITS):
    """one group (same M, eta, center, B): -> dict(moment=dict(U_norm, U (= U_norm B), alpha, tilt, rho, mode, proof, attempts), mean=dict(v, alpha, tilt, rho, R, proof), available (bool), reason). Every accepted scalar is the
    checker's; the proposer only chooses candidates. `deadline` (monotonic) bounds the checker through checked_tilt.Budget."""
    M = int(M); eta = F(eta); y_norm = F(y_norm); B = F(B); delta_m = F(delta_m); delta_b = F(delta_b); out = dict(M=M, eta=str(eta), y_upper_norm=str(y_norm), B=str(B), delta_m=str(delta_m), delta_b=str(delta_b), available=False, reason=None)
    if y_norm > 1: y_norm = F(1)
    bud = lambda: CT.Budget(deadline=deadline)
    try:
        if clock is not None: clock.poll('response certificate: moment proposal')
        eta_f = float(eta); prop = propose_moment(M, eta_f, float(y_norm), float(delta_m)); attempts = []; mom = None
        if prop is not None:
            U_f, ix, rho_f = prop; U = F(U_f)
            if U < y_norm: U = y_norm
            for k in range(MOMENT_RETRIES + 1):
                if clock is not None: clock.poll('response certificate: moment check %d' % k)
                if U >= 1: break
                t = -eta * ALPHAS[ix]; rho_up = _dyadic_up(rho_f)
                res = CT.verify_moment_upper(M, eta, F(1), y_norm, U, t, delta_m, rho=rho_up, bits=bits, budget=bud())
                attempts.append(dict(k=k, U_norm=str(U), alpha=str(ALPHAS[ix]), accepted=bool(res.get('accepted')), reason=res.get('reason') or res.get('refusal')))
                if res.get('accepted'): mom = dict(U_norm=U, U=U * B, alpha=ALPHAS[ix], tilt=t, rho=rho_up, mode='checked', proof=res); break
                if res.get('refusal') == 'DEADLINE': raise CE.Refused('DEADLINE', 'response certificate: moment check expired')
                U = min(F(1), U * MOMENT_WIDEN); rho_f = _rho_f(eta_f, 0.0, 1.0, float(U), float(-eta * ALPHAS[ix]))
        if mom is None: mom = dict(U_norm=F(1), U=B, alpha=None, tilt=None, rho=None, mode='support (deterministic U = B)', proof=dict(accepted=True, mode='support'))
        mom['attempts'] = attempts
        # the mean certificate at v = min(U, 1/4) with C = 1
        if clock is not None: clock.poll('response certificate: mean proposal')
        v = min(mom['U'], F(1, 4)); ix2, rho2_f, R_f = propose_mean(M, eta_f, float(v), float(delta_b)); t2 = eta * ALPHAS[ix2]; rho2 = _dyadic_up(rho2_f)
        res2 = CT.verify_mean_radius(M, eta, v, F(1), t2, rho2, delta_b, bits=bits, budget=bud())
        if not res2.get('accepted'):
            if res2.get('refusal') == 'DEADLINE': raise CE.Refused('DEADLINE', 'response certificate: mean check expired')
            # one widening retry of rho (the proposer's eigenvalue may sit under the outward exp bounds)
            rho2 = rho2 * F(1 + 2 ** -20); res2 = CT.verify_mean_radius(M, eta, v, F(1), t2, rho2, delta_b, bits=bits, budget=bud())
            if not res2.get('accepted'): out.update(moment=_rec(mom), mean=dict(accepted=False, proof=res2), reason='mean certificate not verified'); return out
        R = F(res2['radius_upper']); out.update(moment=_rec(mom), mean=dict(v=str(v), alpha=str(ALPHAS[ix2]), tilt=str(t2), rho=str(rho2), R=str(R), R_float=float(R), R_float_proposed=R_f, proof=res2), R=R, available=True); return out
    except CE.Refused as e:
        out.update(reason='%s: %s' % (e.kind, str(e.reason)[:120]), refusal=e.kind); return out


def _rec(m): return dict(U_norm=str(m['U_norm']), U=str(m['U']), U_float=float(m['U']), alpha=(str(m['alpha']) if m['alpha'] is not None else None), tilt=(str(m['tilt']) if m['tilt'] is not None else None), rho=(str(m['rho']) if m['rho'] is not None else None), mode=m['mode'], proof=m['proof'], attempts=m.get('attempts'))


def response_intervals(snapshots, eta, delta, n_q, Q, clock=None, deadline=None):
    """the whole response certificate: snapshots = heatbath_native observer_snapshots() (sites with j None are skipped: no completed local checkpoint); -> dict(groups=[...], per_site={site: dict(j, M, group, coords=[(lo, hi, mean_lo, mean_hi, R)])},
    counts, unavailable=[sites])"""
    eta = F(eta); delta = F(delta); groups = {}; order = []
    for s in snapshots:
        if s['j'] is None: continue
        key = (s['j'], s['k'])
        if key not in groups: groups[key] = dict(j=s['j'], k=s['k'], M=s['count'], C=s['center'], B=B_of(s['center']), sites=[], y_max=F(0)); order.append(key)
        g = groups[key]; assert g['M'] == s['count'] and g['C'] == s['center']; g['sites'].append(s['site'])
        for a in range(s['k']): y = F(s['second_hi'][a], s['count'] * S * S) / g['B']; g['y_max'] = max(g['y_max'], y)
    certs = {}; checks = 0
    for key in sorted(order, key=lambda k_: -groups[k_]['j']):                                  # the largest counts first (the most informative groups are certified first inside the tail)
        g = groups[key]; al = risk_allocation(delta, n_q, Q, g['j']); c = certify_group(g['M'], eta, g['y_max'], g['B'], al['delta_m'], al['delta_b'], clock=clock, deadline=deadline); checks += 1 + len(c.get('moment', {}).get('attempts') or [])
        c.update(j=g['j'], k=g['k'], C=g['C'], sites=list(g['sites']), n_sites=len(g['sites']), w_j=str(al['w_j'])); certs[key] = c
        if c.get('refusal') == 'DEADLINE': break
    per_site = {}; unavailable = []
    for s in snapshots:
        if s['j'] is None: unavailable.append(dict(site=s['site'], reason='no completed local checkpoint (visits %d < M_1)' % s['count'])); continue
        c = certs.get((s['j'], s['k']))
        if c is None or not c.get('available'): unavailable.append(dict(site=s['site'], reason=(c or {}).get('reason') or 'group not certified (tail exhausted)')); continue
        R = c['R']; coords = []
        for a in range(s['k']):
            ml = F(s['first_lo'][a], s['count'] * S); mh = F(s['first_hi'][a], s['count'] * S); lo = max(F(0), ml - R); hi = min(F(1), mh + R); coords.append(dict(lo=lo, hi=hi, mean_lo=ml, mean_hi=mh, R=R, arith_width=mh - ml, y_upper=F(s['second_hi'][a], s['count'] * S * S)))
        per_site[s['site']] = dict(j=s['j'], M=s['count'], group=[s['j'], s['k']], coords=coords)
    return dict(groups=[{k: (str(v) if isinstance(v, F) else v) for k, v in dict(certs[key], y_max=str(groups[key]['y_max'])).items() if k != 'R'} | dict(R=str(certs[key].get('R'))) for key in order if key in certs], per_site=per_site, unavailable=unavailable, n_groups=len(order), n_certified=sum(1 for c in certs.values() if c.get('available')), checker_calls=checks, eta=str(eta))


def intersect_boxes(raw_box, resp_coords):
    """per variable: raw rows [(lo, hi)] cap response coords -> (box [(lo, hi)], conflict (bool))"""
    out = []; conflict = False
    for (rl, rh), c in zip(raw_box, resp_coords):
        lo = max(rl, c['lo']); hi = min(rh, c['hi'])
        if lo > hi: conflict = True; lo, hi = rl, rh                                              # a typed conflict: the variable publishes nothing new (the caller records it); the raw interval is kept for the record
        out.append((lo, hi))
    return out, conflict
