"""DGP5 joint conditional construction, part 3: family selection, the finite cap / moment frontier, quantization, scoring, promotion and payback (theory note sections 2, 4, 6; brief sections 6-7).
Scores (frozen): Z_proxy = mean over the ODD-id fit half of W_0 / q_seed (HEURISTIC; log2 form); eta = eps Z_proxy / 6; H(q, B, S) = S + eta B (log-sum-exp in log2); work(q) = 1 + sum_target_factors (arity + 1) +
sum_conditionals (parents + ceil log2 card + 2) + K; d_hat(q) = d_seed work(q) / work(q_seed); J(q) = d_hat(q) H(q). CAP_ONLY scores d_hat x B, MOMENT_ONLY d_hat x S (strategy ablations). Frontier: C_min = max_u sum_z
b, C_max = max(C_min, 4 B_current), 17 affine points incl. the endpoints, + B_current when feasible, + the unconstrained moment endpoint (theta proportional to sqrt a); each nominal C solved per row by the clipped
square-root normalization theta = max(b / C, sqrt(a / lambda_u)) with <= 64 safeguarded bisections on lambda_u (FLOATING ADVISORY ONLY); rows quantized to positive integer counts summing to D; every actual law gets a
fresh cap / moment calculation (joint_witness.witnesses_of). Promotion: the smallest checked J (ties: current epoch, smaller cap, smaller retained family, stable frontier index) at >= 1 % below the incumbent's J;
the unchanged law is an explicit candidate with S_ref = min(S_current, sum a / theta_current, B_tight^2) on BOTH sides and its CONSUMED cap as baseline; the same-law tighter-cap candidate (B_tight = min(B_current,
max b / theta_current)) is a real candidate. Payback: J_selected / J_incumbent_comparable < T_after / T_before (ratio 1 when the old epoch is kept)."""
import math, itertools
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import residual_max_envelope as RM
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, lead, log2_up
from pgm.algorithms.quotient import joint_proposal as JP
from pgm.algorithms.quotient import joint_witness as JW
from pgm.algorithms.quotient.joint_proposal import D, D_BITS, Conditional, Proposal, RefusedJoint, vol_of

ZERO_BITS = 64.0                                                                           # a factor with a structural zero contributes 64 bits to every pair it contains


def lg_bounded(q):
    """float log2 of a positive Fraction from bit lengths + the leading 53 bits of numerator and denominator (never float(huge))"""
    n, d = q.numerator, q.denominator; sn = max(0, n.bit_length() - 53); sd = max(0, d.bit_length() - 53); return (sn - sd) + math.log2(n >> sn) - math.log2(d >> sd)


def log2_range(vals):
    """positive log-range of a factor's entries in bits (bounded log2); None when a structural zero is present"""
    pos = [F(x) for x in vals if x > 0]
    if len(pos) < len(vals): return None
    if not pos: return 0.0
    return max(0.0, lg_bounded(max(pos) / min(pos)))


def interaction_scores(M_par, budget, clock):
    """pair -> sum over target factors containing both variables of the positive log-range (64 bits for a factor with a structural zero); charged (one float per pair) and polled; ordering only, never a proof"""
    n = len(M_par.cards); pairs = {}; charged = budget.charge(8 * sum(len(sc) * (len(sc) - 1) // 2 for sc, _ in M_par.factors) + 64, 'joint interaction scores')
    try:                                                                                      # DGP6 repair (finding 2): exception-safe ownership -- an interrupted scan releases its charge (2,272 B orphaned before)
        for fi, (sc, vals) in enumerate(M_par.factors):
            r = log2_range(vals); r = ZERO_BITS if r is None else r
            for u, v in itertools.combinations(sorted(set(sc)), 2): pairs[(u, v)] = pairs.get((u, v), 0.0) + r
            if (fi & 255) == 255: clock.poll('in the interaction scores')
    except BaseException: budget.release(charged); raise
    return pairs, charged


def score_of(pairs, u, v): return pairs.get((min(u, v), max(u, v)), 0.0)


def rank_expansions(prop, pairs, cards, V_family, exclude_vars=()):
    """per conditional z: its highest-score earlier-sampled variable outside its parents (ties: lower id) whose family stays <= V_family; ranked by added score / added entries, then variable id"""
    pos = {v: i for i, v in enumerate(prop.order)}; cands = []
    for z in prop.order:
        if z in exclude_vars: continue
        c = prop.conds[z]; earlier = [w for w in prop.order if pos[w] < pos[z] and w not in c.parents]
        if not earlier: continue
        best = None
        for w in earlier:
            sc = score_of(pairs, z, w); vol = vol_of(tuple(c.parents) + (w,), cards) * cards[z]
            if vol > V_family: continue
            if best is None or sc > best[0] or (sc == best[0] and w < best[1]): best = (sc, w, vol)
        if best is None: continue
        sc, w, vol = best; added = vol - c.family_volume(); cands.append(dict(z=z, add=w, score=sc, added_entries=added, ratio=(sc / added if added > 0 else math.inf), new_parents=tuple(sorted(c.parents + (w,), key=lambda p: pos[p])), volume=vol))
    cands.sort(key=lambda d: (-d['ratio'], d['z'])); return cands


def choose_retune(prop, pairs, cards, exclude_vars=()):
    """no admissible expansion: the conditional with the largest parent-interaction score / family entries, then variable id; no interactions anywhere -> the lowest variable id"""
    best = None
    for z in prop.order:
        if z in exclude_vars: continue
        c = prop.conds[z]; sc = sum(score_of(pairs, z, p) for p in c.parents); r = sc / c.family_volume()
        if best is None or r > best[0] or (r == best[0] and z < best[1]): best = (r, z)
    if best is None: return None
    return dict(z=best[1], add=None, score=best[0], new_parents=tuple(prop.conds[best[1]].parents), retune=True)


# ---------------------------------------------------------------- the frontier (floating advisory rows -> quantized actual laws); VECTORIZED over the parent rows
def _rows_solve(bf, af, C, bisections):
    """theta = max(b / C, sqrt(a / lam_u)) with lam_u normalizing each row (floats, all rows at once); C = inf -> the moment endpoint; rows with every a = 0 take the floors + a uniform remainder;
    returns (theta (R, k), feasible (R,) bool)"""
    R, k = bf.shape; floor = (bf / C) if C != math.inf else np.zeros_like(bf); fs = floor.sum(axis=1); feas = fs <= 1.0 + 1e-12
    pos = af > 0; anyp = pos.any(axis=1); sq = np.sqrt(np.where(pos, af, 0.0)); rem = np.maximum(1e-300, 1.0 - fs)
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'): lam_c = np.where(anyp, np.minimum((sq.sum(axis=1) / rem) ** 2, 1e290), 1.0)
    lam_c = np.where(np.isfinite(lam_c) & (lam_c > 0), lam_c, 1.0); lo = lam_c / 4.0; hi = lam_c * 4.0
    def total(lam):
        with np.errstate(over='ignore', divide='ignore', invalid='ignore'): return np.where(pos, np.maximum(floor, sq / np.sqrt(lam)[:, None]), floor).sum(axis=1)
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        for _ in range(64):
            m = total(lo) < 1.0
            if not m.any(): break
            lo = np.where(m, np.maximum(lo / 4.0, 1e-300), lo)
        for _ in range(64):
            m = total(hi) > 1.0
            if not m.any(): break
            hi = np.where(m, np.minimum(hi * 4.0, 1e300), hi)
        for _ in range(bisections):
            mid = np.sqrt(lo) * np.sqrt(hi); t = total(mid); lo = np.where(t > 1.0, mid, lo); hi = np.where(t > 1.0, hi, mid)
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'): th = np.where(pos, np.maximum(floor, sq / np.sqrt(hi)[:, None]), floor)
    uni = ~anyp
    if uni.any(): th[uni] = floor[uni] + (rem[uni] / k)[:, None]
    t = th.sum(axis=1); feas &= t > 0; th = th / np.where(t > 0, t, 1.0)[:, None]; return th, feas


def quantize_rows(th, k):
    """nonnegative finite weights (R, k) -> positive integer counts summing to D per row (vectorized): one count per state; the remaining D - k by floors of the normalized weights then the deterministic largest-remainder
    rule (ties -> the lower state index); rows with a negative / non-finite weight are rejected (None mask); an all-zero row becomes near-uniform"""
    th = np.asarray(th, dtype=float); R_, kk = th.shape; assert kk == k
    bad = ~np.isfinite(th).all(axis=1) | (th < 0).any(axis=1); w = np.where(np.isfinite(th) & (th >= 0), th, 0.0); tot = w.sum(axis=1); zero = tot <= 0; w = np.where(zero[:, None], 1.0, w); tot = np.where(zero, float(k), tot)
    Rm = D - k; shares = Rm * (w / tot[:, None]); floors = np.minimum(np.floor(shares), Rm).astype(np.int64); left = Rm - floors.sum(axis=1); frac = shares - floors
    order = np.argsort(-frac, axis=1, kind='stable'); rank = np.empty_like(order); np.put_along_axis(rank, order, np.arange(k)[None, :].repeat(R_, 0), axis=1)
    bump = (rank < np.maximum(left, 0)[:, None]).astype(np.int64); counts = 1 + floors + bump
    neg = left < 0                                                                              # a float artifact: the floors overshoot by |left| units -> remove one unit from the largest counts
    for r in np.nonzero(neg)[0]:
        for i in np.argsort(-counts[r], kind='stable')[: -int(left[r])]: counts[r, i] -= 1
    ok = (counts.sum(axis=1) == D) & (counts >= 1).all(axis=1) & ~bad; return counts, ok


def _logs(arr):
    """float log2 of a compact table (exponent exact + log2 mantissa); -inf for zero"""
    out = np.full(arr.shape, -np.inf)
    for idx, (e, m) in np.ndenumerate(arr):
        if m: out[idx] = e + math.log2(m)
    return out


def frontier_laws(pk, prop, cards, profile, mode, B_current):
    """every candidate conditional of the family (quantized): the affine cap grid (17 points C_min..C_max), B_current when feasible, the moment endpoint; mode 'cap_only' / 'moment_only' use their single rows;
    returns [(label, Conditional | None, nominal_log2_C)]; a malformed / infeasible candidate is recorded with None"""
    lb = _logs(pk.b); la = _logs(pk.a); k = cards[pk.z]; rows = pk.b.shape[0]; out = []; shift_b = np.nanmax(lb[np.isfinite(lb)]) if np.isfinite(lb).any() else 0.0; shift_a = np.nanmax(la[np.isfinite(la)]) if np.isfinite(la).any() else 0.0
    bf = np.where(np.isfinite(lb), np.exp2(lb - shift_b), 0.0); af = np.where(np.isfinite(la), np.exp2(la - shift_a), 0.0)
    def quantize(th, label, nominal, feas=None):
        if feas is not None and not feas.all(): out.append((label + ':INFEASIBLE', None, nominal)); return
        cnt, ok = quantize_rows(th, k)
        if not ok.all(): out.append((label + ':REJECTED:MALFORMED', None, nominal)); return
        try: out.append((label, Conditional(pk.z, pk.parents, cnt, cards), nominal))
        except AssertionError: out.append((label + ':REJECTED:INVALID', None, nominal))
    if mode == 'cap_only': quantize(bf, 'cap_only_b_rows', None); return out
    if mode == 'moment_only': quantize(np.sqrt(af), 'moment_only_sqrt_a_rows', None); return out
    log2_Cmin = (log2_up(pk.Cmin) if pk.Cmin[1] else -math.inf); log2_Bcur = (log2_up(B_current) if B_current[1] else -math.inf); log2_Cmax = max(log2_Cmin, log2_Bcur + 2.0)
    ratio = 2.0 ** min(1000.0, log2_Cmax - log2_Cmin); grid = [log2_Cmin + math.log2(1.0 + (ratio - 1.0) * i / (profile['frontier_points'] - 1)) for i in range(profile['frontier_points'])]      # DGP6 repair (finding 7): the DGP5 brief specified 17 AFFINE points in C between C_min and C_max; the frozen DGP5 utility used a geometric grid in log2 C -- corrected here as an amendment of the DGP5 replay utility ONLY (the DGP6 global optimizer has no cap grid)
    if log2_Bcur >= log2_Cmin and all(abs(g - log2_Bcur) > 1e-9 for g in grid): grid.append(log2_Bcur)
    for gi, lc in enumerate(grid):
        C = 2.0 ** min(1000.0, lc - shift_b); th, feas = _rows_solve(bf, af, C, profile['bisections']); quantize(th, 'frontier_%02d' % gi, lc, feas)
    th, feas = _rows_solve(bf, af, math.inf, profile['bisections']); quantize(th, 'moment_endpoint', None, feas)
    return out


# ---------------------------------------------------------------- scores
def log2_add(x, y):
    if x == -math.inf: return y
    if y == -math.inf: return x
    m = max(x, y); return m + math.log2(1.0 + 2.0 ** (min(x, y) - m))


def H_log2(log2_S, log2_B, log2_eta, mode='joint'):
    """log2 H: joint = S + eta B; cap_only = B; moment_only = S"""
    if mode == 'cap_only': return log2_B
    if mode == 'moment_only': return log2_S
    return log2_add(log2_S, log2_eta + log2_B)


def work_of(prop, arity_sum, K): return prop.work(arity_sum, K)


def select(cands, incumbent, margin):
    """cands / incumbent: dicts with log2_J, is_current, log2_B, family_volume, index; the smallest J wins (ties: current epoch, smaller cap, smaller family, stable index); promotion only when the winner is not the
    incumbent and J_win <= (1 - margin) J_incumbent"""
    allc = [incumbent] + [c for c in cands if c.get('log2_J') is not None]
    win = min(allc, key=lambda c: (c['log2_J'], 0 if c.get('is_current') else 1, c['log2_B'], c['family_volume'], c['index']))
    promoted = (not win.get('is_current')) and win['log2_J'] <= incumbent['log2_J'] + math.log2(1.0 - margin)
    return win, promoted


def payback(log2_J_committed, log2_J_incumbent, T_before, T_after):
    """J_committed / J_incumbent < T_after / T_before (ratio 1 when the old epoch is kept): True = the construction time was repaid by the forecast improvement"""
    if T_before <= 0: return False, dict(reason='T_before <= 0')
    ratio_J = 2.0 ** (log2_J_committed - log2_J_incumbent); ratio_T = max(0.0, T_after) / T_before
    return ratio_J < ratio_T, dict(ratio_J=ratio_J, ratio_T=ratio_T, T_before=T_before, T_after=T_after)
