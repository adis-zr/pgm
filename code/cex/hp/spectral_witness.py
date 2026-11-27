"""DGP8 SPECTRAL_HEATBATH, part 1: the CHECKED spectral witness (brief sections 1-2; theory sections 4). For a strictly positive pairwise categorical model after canonicalization, build the full centered-one-hot log-interaction
matrix A (phi_i(a) = e_a - 1 / k_i; pair block P_i log(F_ij) P_j with P_i = I - 11^T / k_i; factors on the same pair ADDED; diagonal variable blocks zero; log W = c + sum_i h_i + (1/2) phi^T A phi) as an INTERVAL matrix [A_lo, A_hi]
that provably contains the exact A: every log of a positive rational factor value is enclosed by exact rational arithmetic (binary reduction x = 2^k m with m in [7/10, 7/5), log m = 2 atanh((m - 1) / (m + 1)) by the odd series with a
proved geometric tail bound, log 2 = 2 atanh(1 / 3) likewise; results floored / ceiled to the dyadic grid 2^-GRID_BITS), the centering is exact rational interval arithmetic, the endpoints are converted to binary64 OUTWARD. A floating
eigensolver PROPOSES l <= lambda_min, u >= lambda_max (advisory); the PROOF is the outward interval Cholesky of A_int - l I and u I - A_int (round-to-nearest binary64 with every operation widened by WIDEN x ulp relative + an absolute
floor; inclusion monotonicity makes a completed factorization with strictly positive pivot LOWER bounds a proof that every real symmetric matrix in the interval hull -- in particular the exact A -- is positive definite). Eligibility
w = u - l < 2 (w computed upward), m = 1 - w / 2 (downward), g = m / n (downward). A failed pivot, w >= 2, a hard zero, a factor of arity >= 3 -> typed refusal (RefusedSpectral) of THIS route only. Every array is admitted before
allocation under the shared CE.Budget; loops poll the clock. Nothing floating is a certificate here except through the interval proof; the eigensolver output is recorded as a proposal."""
import math, time, functools
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
GRID_BITS = 80; SERIES_TERMS = 16; LOG2_TERMS = 48; WIDEN = 4; U53 = 2.0 ** -53; TINY = 1e-290
PROFILE = dict(grid_bits=GRID_BITS, series_terms=SERIES_TERMS, log2_terms=LOG2_TERMS, widen_ulps=WIDEN, proposal_margin_rel=1e-9, proposal_margin_abs=1e-12, eligibility_width=2, reduction_interval=('7/10', '7/5'), arithmetic='exact Fractions for the log enclosures and the centering; binary64 round-to-nearest with 4-ulp outward widening for the interval Cholesky; endpoints converted outward')


class RefusedSpectral(Exception):
    def __init__(self, kind, reason): super().__init__(kind, reason); self.kind = kind; self.reason = reason


# ---------------------------------------------------------------- rigorous logarithm enclosures (exact rationals)
def _floor_grid(x, bits=GRID_BITS): return F(math.floor(x * (1 << bits)), 1 << bits)
def _ceil_grid(x, bits=GRID_BITS): return F(math.ceil(x * (1 << bits)), 1 << bits)


def _atanh_series_enclosure(y, terms):
    """2 atanh(y) = 2 sum_{j>=0} y^(2j+1) / (2j+1) for |y| < 1 (exact partial sum; tail |R| <= 2 |y|^(2J+1) / ((2J+1)(1 - y^2)) for the first omitted index J); -> (lo, hi) exact Fractions"""
    assert abs(y) < 1
    s = F(0); p = y; y2 = y * y
    for j in range(terms):
        s += p / (2 * j + 1); p *= y2
    J = terms; tail = 2 * abs(y) ** (2 * J + 1) / ((2 * J + 1) * (1 - y2)); s2 = 2 * s
    return s2 - tail, s2 + tail


_LOG2 = None
def log2_enclosure():
    """rigorous enclosure of ln 2 = 2 atanh(1/3)"""
    global _LOG2
    if _LOG2 is None:
        lo, hi = _atanh_series_enclosure(F(1, 3), LOG2_TERMS); _LOG2 = (_floor_grid(lo, GRID_BITS + 16), _ceil_grid(hi, GRID_BITS + 16))
    return _LOG2


def log_enclosure(x):
    """-> (lo, hi) exact dyadic Fractions with lo <= ln x <= hi for a positive rational x (memoized per value): x = 2^k m, m in [7/10, 7/5) -> |y| = |(m - 1) / (m + 1)| <= 7/27 < 0.26; ln x = k ln 2 + 2 atanh(y);
    16 terms give a tail below 2 x 0.26^33 / 33 < 1e-19 (the enclosure width is what it is -- recorded as log_width_max; never assumed)"""
    return _log_enclosure_cached(F(x))


@functools.lru_cache(maxsize=1 << 20)
def _log_enclosure_cached(x):
    if x <= 0: raise RefusedSpectral('HARD_ZERO', 'logarithm of a non-positive factor value')
    k = 0; m = x
    while m >= F(7, 5): m /= 2; k += 1
    while m < F(7, 10): m *= 2; k -= 1
    lo_m, hi_m = _atanh_series_enclosure((m - 1) / (m + 1), SERIES_TERMS); L2lo, L2hi = log2_enclosure()
    if k >= 0: lo = k * L2lo + lo_m; hi = k * L2hi + hi_m
    else: lo = k * L2hi + lo_m; hi = k * L2lo + hi_m
    return _floor_grid(lo), _ceil_grid(hi)


def to_float_outward(lo, hi):
    """exact rational endpoints -> binary64 endpoints enclosing them"""
    flo = float(lo); fhi = float(hi)
    if F(flo) > lo: flo = math.nextafter(flo, -math.inf)
    if F(fhi) < hi: fhi = math.nextafter(fhi, math.inf)
    return flo, fhi


# ---------------------------------------------------------------- the interval matrix A
def build_interaction(M, budget, clock):
    """M = coarse_envelope.Canon (cards, psi, factors=[(scope, values)]). -> dict(A_lo, A_hi (D x D float arrays), offsets, D, n, pairs, blocks, log_width_max, matrix_width_max, h (advisory float unary fields), bytes, seconds).
    Raises RefusedSpectral('ARITY' | 'HARD_ZERO')."""
    t0 = CE.tnow(); cards = list(M.cards); n = len(cards); off = [0]
    for k in cards: off.append(off[-1] + k)
    D = off[-1]
    for sc, vals in M.factors:
        if len(sc) >= 3: raise RefusedSpectral('ARITY', 'a factor of arity %d is outside the pairwise class' % len(sc))
        if any(F(v) <= 0 for v in vals): raise RefusedSpectral('HARD_ZERO', 'a factor value is zero: the log interaction is undefined (hard zero)')
    for i in range(n):
        if any(F(v) <= 0 for v in M.psi[i]): raise RefusedSpectral('HARD_ZERO', 'a unary weight is zero (hard zero)')
    need = 2 * 8 * D * D + 8 * D * 2 + 64 * len(M.factors); budget.charge(need, 'spectral witness: interval matrix %d x %d + unary fields' % (D, D)); owned = need
    try:
        A_lo = np.zeros((D, D)); A_hi = np.zeros((D, D)); h = np.zeros(D); lw_max = F(0); mw_max = 0.0; pairs = {}; nblocks = 0
        for i in range(n):
            for a in range(cards[i]):
                lo, hi = log_enclosure(M.psi[i][a]); h[off[i] + a] += float((lo + hi) / 2)
        for fi, (sc, vals) in enumerate(M.factors):
            clock.poll('spectral witness: factor %d' % fi)
            if len(sc) == 1:
                i = sc[0]
                for a in range(cards[i]):
                    lo, hi = log_enclosure(vals[a]); h[off[i] + a] += float((lo + hi) / 2)
                continue
            i, j = sc; ki, kj = cards[i], cards[j]
            L = [[log_enclosure(vals[a * kj + b]) for b in range(kj)] for a in range(ki)]
            for a in range(ki):
                for b in range(kj): lw_max = max(lw_max, L[a][b][1] - L[a][b][0])
            # row / column / grand means as exact intervals; centered entry C_ab = L_ab - rowmean_a - colmean_b + grand (every term an interval; subtraction swaps endpoints)
            row = [(sum(L[a][b][0] for b in range(kj)) / kj, sum(L[a][b][1] for b in range(kj)) / kj) for a in range(ki)]
            col = [(sum(L[a][b][0] for a in range(ki)) / ki, sum(L[a][b][1] for a in range(ki)) / ki) for b in range(kj)]
            grand = (sum(r[0] for r in row) / ki, sum(r[1] for r in row) / ki)
            for a in range(ki):
                for b in range(kj):
                    clo = L[a][b][0] - row[a][1] - col[b][1] + grand[0]; chi = L[a][b][1] - row[a][0] - col[b][0] + grand[1]
                    flo, fhi = to_float_outward(clo, chi); A_lo[off[i] + a, off[j] + b] += flo; A_hi[off[i] + a, off[j] + b] += fhi
                    A_lo[off[j] + b, off[i] + a] += flo; A_hi[off[j] + b, off[i] + a] += fhi
                mw = max(float(chi - clo) for b in range(kj) for clo, chi in [(L[a][b][0] - row[a][1] - col[b][1] + grand[0], L[a][b][1] - row[a][0] - col[b][0] + grand[1])]); mw_max = max(mw_max, mw)
            # the row / column means move into the unary fields (advisory floats for x0 selection; the certificate never uses h)
            for a in range(ki): h[off[i] + a] += float((row[a][0] + row[a][1]) / 2)
            for b in range(kj): h[off[j] + b] += float((col[b][0] + col[b][1]) / 2)
            key = (min(i, j), max(i, j)); pairs[key] = pairs.get(key, 0) + 1; nblocks += 1
        # the accumulated sums of several blocks on one pair were added in float: widen each accumulated entry by the number of blocks x ulp (outward)
        for (i, j), cnt in pairs.items():
            if cnt > 1:
                sl = (slice(off[i], off[i + 1]), slice(off[j], off[j + 1])); A_lo[sl] -= cnt * U53 * np.abs(A_lo[sl]) + TINY; A_hi[sl] += cnt * U53 * np.abs(A_hi[sl]) + TINY
                sl2 = (slice(off[j], off[j + 1]), slice(off[i], off[i + 1])); A_lo[sl2] -= cnt * U53 * np.abs(A_lo[sl2]) + TINY; A_hi[sl2] += cnt * U53 * np.abs(A_hi[sl2]) + TINY
        return dict(A_lo=A_lo, A_hi=A_hi, offsets=off, D=D, n=n, cards=cards, pairs=len(pairs), blocks=nblocks, log_width_max=float(lw_max), matrix_width_max=float(mw_max), h=h, bytes=owned, seconds=CE.tnow() - t0)
    except BaseException:
        budget.release(owned); raise


# ---------------------------------------------------------------- outward interval arithmetic on binary64 (documented rounding: nearest, then widened by WIDEN ulps relative + TINY absolute)
def _wlo(x): return x - WIDEN * U53 * np.abs(x) - TINY
def _whi(x): return x + WIDEN * U53 * np.abs(x) + TINY
def iv_add(alo, ahi, blo, bhi): return _wlo(alo + blo), _whi(ahi + bhi)
def iv_sub(alo, ahi, blo, bhi): return _wlo(alo - bhi), _whi(ahi - blo)
def iv_mul(alo, ahi, blo, bhi):
    p1 = alo * blo; p2 = alo * bhi; p3 = ahi * blo; p4 = ahi * bhi
    return _wlo(np.minimum(np.minimum(p1, p2), np.minimum(p3, p4))), _whi(np.maximum(np.maximum(p1, p2), np.maximum(p3, p4)))
def iv_sq(alo, ahi):
    both = np.where((alo <= 0) & (ahi >= 0), 0.0, np.minimum(alo * alo, ahi * ahi)); return _wlo(both), _whi(np.maximum(alo * alo, ahi * ahi))
def iv_div_pos(alo, ahi, blo, bhi):
    """a / b with b > 0 (blo > 0)"""
    q1 = alo / blo; q2 = alo / bhi; q3 = ahi / blo; q4 = ahi / bhi
    return _wlo(np.minimum(np.minimum(q1, q2), np.minimum(q3, q4))), _whi(np.maximum(np.maximum(q1, q2), np.maximum(q3, q4)))
def iv_sqrt_pos(alo, ahi): return _wlo(np.sqrt(alo)), _whi(np.sqrt(ahi))


def interval_cholesky_pd(M_lo, M_hi, clock, budget=None, tag=''):
    """outward interval Cholesky of the symmetric interval matrix [M_lo, M_hi]: returns dict(ok, min_pivot_lower, failed_column, seconds). ok = True PROVES that every symmetric real matrix inside the interval is positive definite
    (inclusion monotonicity: the real Cholesky recursion of any member stays inside the computed intervals, and every pivot interval has a strictly positive lower bound, so the member's Cholesky exists)."""
    t0 = CE.tnow(); D = M_lo.shape[0]; owned = 0
    if budget is not None: owned = budget.charge(2 * 8 * D * D + 4096, 'interval Cholesky factors %d x %d %s' % (D, D, tag))
    try:
        L_lo = np.zeros((D, D)); L_hi = np.zeros((D, D)); minpiv = math.inf
        for j in range(D):
            if (j & 15) == 15: clock.poll('interval Cholesky column %d %s' % (j, tag))
            if j:
                slo, shi = iv_sq(L_lo[j, :j], L_hi[j, :j]); ssum_lo = float(slo.sum()); ssum_hi = float(shi.sum()); ssum_lo -= j * U53 * ssum_hi + TINY; ssum_hi += j * U53 * ssum_hi + TINY          # nonnegative terms: the summation rounding is bounded by the sum itself
                dlo, dhi = iv_sub(M_lo[j, j], M_hi[j, j], ssum_lo, ssum_hi); dlo = float(dlo); dhi = float(dhi)
            else: dlo, dhi = float(M_lo[j, j]), float(M_hi[j, j])
            if not (dlo > 0): return dict(ok=False, min_pivot_lower=float(min(minpiv, dlo)), failed_column=j, seconds=CE.tnow() - t0)
            minpiv = min(minpiv, dlo); ljj_lo, ljj_hi = iv_sqrt_pos(np.array(dlo), np.array(dhi)); L_lo[j, j] = ljj_lo; L_hi[j, j] = ljj_hi
            if j + 1 < D:
                if j:
                    plo, phi = iv_mul(L_lo[j + 1:, :j], L_hi[j + 1:, :j], L_lo[j, :j][None, :], L_hi[j, :j][None, :]); s_lo = plo.sum(axis=1); s_hi = phi.sum(axis=1)
                    asum = np.abs(plo).sum(axis=1) + np.abs(phi).sum(axis=1); s_lo = s_lo - j * U53 * asum - TINY; s_hi = s_hi + j * U53 * asum + TINY           # summation rounding of j terms bounded against the SUM OF ABSOLUTE terms (mixed signs)
                    nlo, nhi = iv_sub(M_lo[j + 1:, j], M_hi[j + 1:, j], s_lo, s_hi)
                else: nlo, nhi = M_lo[j + 1:, j].copy(), M_hi[j + 1:, j].copy()
                qlo, qhi = iv_div_pos(nlo, nhi, np.array(ljj_lo), np.array(ljj_hi)); L_lo[j + 1:, j] = qlo; L_hi[j + 1:, j] = qhi
        return dict(ok=True, min_pivot_lower=float(minpiv), failed_column=None, seconds=CE.tnow() - t0, max_factor_width=float(np.max(L_hi - L_lo)))
    finally:
        if owned: budget.release(owned)


def propose_bounds(A_lo, A_hi):
    """advisory: floating eigenvalues of the midpoint matrix, widened by the matrix radius and a relative margin -> proposed (l, u)"""
    mid = 0.5 * (A_lo + A_hi); rad = float(np.max(np.sum(0.5 * (A_hi - A_lo), axis=1))); ev = np.linalg.eigvalsh(mid); lmin = float(ev[0]); lmax = float(ev[-1]); scale = max(abs(lmin), abs(lmax), 1.0)
    marg = rad + PROFILE['proposal_margin_rel'] * scale + PROFILE['proposal_margin_abs']
    return dict(lambda_min_float=lmin, lambda_max_float=lmax, radius_norm=rad, l=lmin - marg, u=lmax + marg, margin=marg)


def certify(M, budget, clock, l=None, u=None):
    """the full witness: build the interval matrix, propose (l, u) unless given, PROVE lambda_min(A) >= l and lambda_max(A) <= u by two interval Cholesky runs, compute w / m / g outward. -> dict (never raises on ineligibility: `eligible` False
    with `refusal`); raises RefusedSpectral only for the class violations (arity / hard zero) and CE.Refused / Deadline from admission / polls."""
    t0 = CE.tnow(); built = build_interaction(M, budget, clock); owned = built['bytes']
    try:
        D = built['D']; n = built['n']; prop = propose_bounds(built['A_lo'], built['A_hi'])
        l = prop['l'] if l is None else float(l); u = prop['u'] if u is None else float(u)
        if not (l <= 0.0 <= u): return dict(eligible=False, refusal=dict(kind='SPECTRAL_BOUNDS', reason='proposed bounds do not bracket zero (trace A = 0 forces lambda_min <= 0 <= lambda_max)'), proposal=prop, dimension=D, n=n, seconds=CE.tnow() - t0, bytes=owned, **_strip(built))
        t1 = CE.tnow(); I = np.eye(D)
        low = interval_cholesky_pd(_wlo(built['A_lo'] - l * I), _whi(built['A_hi'] - l * I), clock, budget, 'A - lI')                       # A - l I: the shift acts on the DIAGONAL only (l <= 0 -> exact in binary64 up to the entry rounding, widened inside)
        high = interval_cholesky_pd(_wlo(u * I - built['A_hi']), _whi(u * I - built['A_lo']), clock, budget, 'uI - A'); t_ver = CE.tnow() - t1
        # w = u - l rounded UP; m = 1 - w / 2 rounded DOWN; g = m / n rounded DOWN (exact dyadics via Fractions of the floats)
        wF = F(u) - F(l); mF = 1 - wF / 2; gF = mF / n
        w_up = math.nextafter(float(wF), math.inf) if F(float(wF)) < wF else float(wF); m_dn = math.nextafter(float(mF), -math.inf) if F(float(mF)) > mF else float(mF); g_dn = math.nextafter(float(gF), -math.inf) if F(float(gF)) > gF else float(gF)
        ok = bool(low['ok'] and high['ok']); elig = ok and (wF < 2)
        ref = None
        if not low['ok']: ref = dict(kind='SPECTRAL_PROOF', reason='A - lI not proved positive definite (pivot lower bound %.3e at column %s): the proposal is refused near an unresolved boundary' % (low['min_pivot_lower'], low['failed_column']))
        elif not high['ok']: ref = dict(kind='SPECTRAL_PROOF', reason='uI - A not proved positive definite (pivot lower bound %.3e at column %s)' % (high['min_pivot_lower'], high['failed_column']))
        elif wF >= 2: ref = dict(kind='SPECTRAL_WIDTH', reason='checked width %.6f >= 2: the spectral condition does not hold (not a statement about mixing)' % float(wF))
        return dict(eligible=elig, refusal=ref, l=l, u=u, width=float(w_up), width_exact=str(wF), margin_m=(m_dn if elig else float(m_dn)), gap_g=(g_dn if elig else None), m_exact=str(mF), g_exact=str(gF), dimension=D, n=n, proposal=prop, proof=dict(lower=low, upper=high, seconds_verify=t_ver), seconds=CE.tnow() - t0, seconds_construct=built['seconds'], bytes=owned, **_strip(built))
    finally:
        budget.release(owned)


def _strip(built): return dict(pairs=built['pairs'], blocks=built['blocks'], log_width_max=built['log_width_max'], matrix_width_max=built['matrix_width_max'], h=built['h'], offsets=built['offsets'], cards=built['cards'])


def witness_record(w):
    """the JSON-safe record of a certify() result (arrays dropped)"""
    out = {k: v for k, v in w.items() if k not in ('h', 'offsets', 'cards')}
    if 'proposal' in out: out['proposal'] = {k: v for k, v in out['proposal'].items()}
    return out
