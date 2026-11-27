"""DGP8 SPECTRAL_HEATBATH, part 1 (DGP9 REPAIRED): the CHECKED spectral witness (brief sections 1-2; theory sections 4). For a strictly positive pairwise categorical model after canonicalization, build the full centered-one-hot log-interaction
matrix A (phi_i(a) = e_a - 1 / k_i; pair block P_i log(F_ij) P_j with P_i = I - 11^T / k_i; factors on the same pair ADDED; diagonal variable blocks zero; log W = c + sum_i h_i + (1/2) phi^T A phi) as an INTERVAL matrix [A_lo, A_hi]
that provably contains the exact A: every log of a positive rational factor value is enclosed by exact rational arithmetic (binary reduction x = 2^k m with m in [7/10, 7/5) by BIT LENGTH, log m = 2 atanh((m - 1) / (m + 1)) by the odd
series with a proved geometric tail bound, log 2 = 2 atanh(1 / 3) likewise; results floored / ceiled to the dyadic grid 2^-GRID_BITS), the centering is exact rational interval arithmetic, EVERY pair block is accumulated EXACTLY in
rationals (repeated factors on one pair are added as exact intervals: DGP9 repair of the review's RV2 -- the DGP8 code added binary64 endpoints and widened by a multiple of the FINAL sum, which is invalid under cancellation) and the
endpoints are converted to binary64 OUTWARD once. A floating eigensolver PROPOSES l <= lambda_min, u >= lambda_max (advisory); the PROOF is the outward interval Cholesky of A_int - l I and u I - A_int (round-to-nearest binary64 with
every operation widened by WIDEN x ulp relative + an absolute floor; inclusion monotonicity makes a completed factorization with strictly positive pivot LOWER bounds a proof that every real symmetric matrix in the interval hull -- in
particular the exact A -- is positive definite). Eligibility w = u - l < 2 (w computed upward), m = 1 - w / 2 (downward), g = m / n (downward). DGP9 mechanism change A (policy 'revised'): the proposal may be widened by a FROZEN short
geometric sequence of extra endpoint margins, each attempt re-running the UNCHANGED proofs; retries stop at the first success, when the width cannot qualify, or when the sequence is exhausted. Ownership (review RV6): the rational-log
cache is REQUEST-SCOPED and charged; the exact block accumulators, the eigensolver temporaries, the shifted matrices and the Cholesky factors are admitted before allocation; the retained arrays (h, offsets, cards) stay charged to the
caller until it releases `retained_bytes`; the clock is polled at entry, inside the positivity scans, the unary logs, every block and the conversions. Nothing floating is a certificate here except through the interval proof.
DGP10 (DGP9 independent review F9-2 / F9-3; carried repair contract sections 1-2): EVERY reservation of this module runs inside ONE `reservation.Txn` per `certify` call -- the exact block accumulators, the request-scoped log cache
chunks, the eigensolver workspace, the shifted interval matrices and the Cholesky factors are TRANSACTION-OWNED temporaries (rolled back on any exception, released at scope exit), the retained fields (h / offsets / cards) are
TRANSFERRED to an explicit `reservation.Owner` returned in the record (`W['owner']`) and released by `release_retained`, which also DROPS the retained arrays from the record; `_prove` admits the shifted matrices BEFORE allocating
them and never allocates an identity matrix (the shift is applied in place on admitted copies). Live charge after any failure equals the caller's entry charge exactly (probe_resource_failures: 352 / 131,072 / 1,096 B leaks)."""
import math, time
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import reservation as RV
GRID_BITS = 80; SERIES_TERMS = 16; LOG2_TERMS = 48; WIDEN = 4; U53 = 2.0 ** -53; TINY = 1e-290
CACHE_ENTRY_BYTES = 512; CACHE_CHUNK = 256; FRACTION_BYTES = 200
POLICY_FIXED = dict(name='fixed', extra_margins=[0.0])                                                                   # DGP8: ONE proposal, no retry
POLICY_REVISED = dict(name='revised', extra_margins=[0.0, 1e-8, 4e-8, 1.6e-7, 6.4e-7])                                   # DGP9 mechanism change A: E0 = 1e-8, R = 4, K = 4 extra attempts (frozen in FREEZE.json before scoring)
PROFILE = dict(grid_bits=GRID_BITS, series_terms=SERIES_TERMS, log2_terms=LOG2_TERMS, widen_ulps=WIDEN, proposal_margin_rel=1e-9, proposal_margin_abs=1e-12, eligibility_width=2, reduction_interval=('7/10', '7/5'), policies=dict(fixed=POLICY_FIXED, revised=POLICY_REVISED),
               arithmetic='exact Fractions for the log enclosures, the centering AND the per-pair accumulation (repeated factors added exactly); ONE outward binary64 conversion per entry; binary64 round-to-nearest with 4-ulp outward widening for the interval Cholesky', cache='request-scoped, charged %d B per entry in chunks of %d' % (CACHE_ENTRY_BYTES, CACHE_CHUNK))


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
    """rigorous enclosure of ln 2 = 2 atanh(1/3) (a module constant: one value, computed once)"""
    global _LOG2
    if _LOG2 is None:
        lo, hi = _atanh_series_enclosure(F(1, 3), LOG2_TERMS); _LOG2 = (_floor_grid(lo, GRID_BITS + 16), _ceil_grid(hi, GRID_BITS + 16))
    return _LOG2


def _log_enclosure_exact(x):
    """-> (lo, hi) exact dyadic Fractions with lo <= ln x <= hi for a positive rational x: x = 2^k m, m in [7/10, 7/5) (k from the BIT LENGTHS of numerator / denominator, then at most two corrective steps -- no long loop of
    halvings for huge or tiny values) -> |y| = |(m - 1) / (m + 1)| <= 7/27 < 0.26; ln x = k ln 2 + 2 atanh(y); 16 terms give a tail below 2 x 0.26^33 / 33 < 1e-19 (the enclosure width is what it is -- recorded; never assumed)"""
    x = F(x)
    if x <= 0: raise RefusedSpectral('HARD_ZERO', 'logarithm of a non-positive factor value')
    k = x.numerator.bit_length() - x.denominator.bit_length(); m = x / (F(2) ** k) if k >= 0 else x * (F(2) ** (-k))
    while m >= F(7, 5): m /= 2; k += 1
    while m < F(7, 10): m *= 2; k -= 1
    lo_m, hi_m = _atanh_series_enclosure((m - 1) / (m + 1), SERIES_TERMS); L2lo, L2hi = log2_enclosure()
    if k >= 0: lo = k * L2lo + lo_m; hi = k * L2hi + hi_m
    else: lo = k * L2hi + lo_m; hi = k * L2lo + hi_m
    return _floor_grid(lo), _ceil_grid(hi)


class LogCache:
    """request-scoped memo of log enclosures, CHARGED to the shared constructor account in chunks (CACHE_ENTRY_BYTES per entry) and released by its owner (`release`); polled every chunk"""
    def __init__(self, budget=None, clock=None, tag='rational-log cache', txn=None):
        self.map = {}; self.budget = budget; self.clock = clock; self.owned = 0; self.admitted_entries = 0; self.tag = tag; self.hits = 0; self.misses = 0; self.txn = txn; self.tokens = []
    def get(self, x):
        x = F(x); v = self.map.get(x)
        if v is not None: self.hits += 1; return v
        if len(self.map) >= self.admitted_entries:
            if self.clock is not None: self.clock.poll('%s (%d entries)' % (self.tag, len(self.map)))
            if self.txn is not None: self.tokens.append(self.txn.reserve(CACHE_ENTRY_BYTES * CACHE_CHUNK, '%s chunk' % self.tag)); self.owned += CACHE_ENTRY_BYTES * CACHE_CHUNK          # DGP10: a TRANSACTION-owned temporary (rolled back with the constructor)
            elif self.budget is not None: self.owned += self.budget.charge(CACHE_ENTRY_BYTES * CACHE_CHUNK, '%s chunk' % self.tag)
            self.admitted_entries += CACHE_CHUNK
        v = _log_enclosure_exact(x); self.map[x] = v; self.misses += 1; return v
    def release(self):
        if self.txn is not None:
            for t in self.tokens:
                if t.state == 'TXN': self.txn.release(t)
            self.tokens = []
        elif self.owned and self.budget is not None: self.budget.release(self.owned)
        self.owned = 0; self.map.clear(); self.admitted_entries = 0
    def record(self): return dict(entries=len(self.map), hits=self.hits, misses=self.misses, bytes_charged=self.owned)


def log_enclosure(x, cache=None):
    """-> (lo, hi) exact dyadic Fractions with lo <= ln x <= hi; memoized through the caller's request-scoped cache when given (no process-global cache: review RV6)"""
    return cache.get(x) if cache is not None else _log_enclosure_exact(x)


def to_float_outward(lo, hi):
    """exact rational endpoints -> binary64 endpoints enclosing them"""
    flo = float(lo); fhi = float(hi)
    if F(flo) > lo: flo = math.nextafter(flo, -math.inf)
    if F(fhi) < hi: fhi = math.nextafter(fhi, math.inf)
    return flo, fhi


def log_div_ln2_outward(lo, hi):
    """[lo, hi] enclosing a natural log -> exact rational enclosure of the base-2 value (sign-aware division by the ln 2 enclosure)"""
    L2lo, L2hi = log2_enclosure()
    return (lo / L2hi if lo >= 0 else lo / L2lo), (hi / L2lo if hi >= 0 else hi / L2hi)


# ---------------------------------------------------------------- the interval matrix A
def build_interaction(M, budget, clock, cache=None, txn=None):
    """M = coarse_envelope.Canon (cards, psi, factors=[(scope, values)]). -> dict(A_lo, A_hi (D x D float arrays), offsets, D, n, cards, pairs, blocks, log_width_max, matrix_width_max, h (advisory float unary fields), bytes (the
    retained charge of A_lo / A_hi / h: a TRANSACTION-owned token `token` when a txn is given -- the caller transfers or releases it), seconds, cache record). Raises RefusedSpectral('ARITY' | 'HARD_ZERO'). Every pair block is
    accumulated as EXACT rational intervals and converted outward ONCE. DGP10: every reservation goes through the transaction (an own transaction is opened when none is given: then the matrix charge is released at return as before)."""
    t0 = CE.tnow(); clock.poll('spectral witness: entry'); cards = list(M.cards); n = len(cards); off = [0]
    for k in cards: off.append(off[-1] + k)
    D = off[-1]; own_cache = cache is None; own_txn = txn is None
    if own_txn: txn = RV.Txn(budget, clock, 'spectral build'); txn.__enter__()
    if own_cache: cache = LogCache(budget, clock, txn=txn)
    checked = 0
    for sc, vals in M.factors:
        if len(sc) >= 3: raise RefusedSpectral('ARITY', 'a factor of arity %d is outside the pairwise class' % len(sc))
        for v in vals:
            if F(v) <= 0: raise RefusedSpectral('HARD_ZERO', 'a factor value is zero: the log interaction is undefined (hard zero)')
            checked += 1
            if (checked & 255) == 255: clock.poll('spectral witness: positivity scan (%d values)' % checked)
    for i in range(n):
        for v in M.psi[i]:
            if F(v) <= 0: raise RefusedSpectral('HARD_ZERO', 'a unary weight is zero (hard zero)')
            checked += 1
            if (checked & 255) == 255: clock.poll('spectral witness: positivity scan (%d values)' % checked)
    # admission: the retained arrays (A_lo, A_hi, h) + the EXACT per-pair accumulators (two Fractions per entry of every distinct pair block) + per-factor exact tables (one block at a time)
    pair_entries = {}
    for sc, vals in M.factors:
        if len(sc) == 2: key = (min(sc), max(sc)); pair_entries[key] = cards[sc[0]] * cards[sc[1]]
    acc_entries = sum(pair_entries.values()); max_block = max([cards[i] * cards[j] for (i, j) in pair_entries] + [1])
    need = 2 * 8 * D * D + 8 * D + 64 * len(M.factors); temp = 2 * FRACTION_BYTES * acc_entries + 2 * FRACTION_BYTES * (max_block + 2 * max([max(cards[i], cards[j]) for (i, j) in pair_entries] + [1])) + 4096
    try:
        tok_need = txn.reserve(need, 'spectral witness: interval matrix %d x %d + unary fields' % (D, D)); owned = need
        tok_temp = txn.reserve(temp, 'spectral witness: exact block accumulators (%d entries) + one block of log enclosures' % acc_entries)
        A_lo = np.zeros((D, D)); A_hi = np.zeros((D, D)); h = np.zeros(D); lw_max = F(0); mw_max = F(0); acc = {}; nblocks = 0; done = 0
        for i in range(n):
            for a in range(cards[i]):
                lo, hi = log_enclosure(M.psi[i][a], cache); h[off[i] + a] += float((lo + hi) / 2); done += 1
                if (done & 63) == 63: clock.poll('spectral witness: unary logs (%d)' % done)
        for fi, (sc, vals) in enumerate(M.factors):
            clock.poll('spectral witness: factor %d' % fi)
            if len(sc) == 1:
                i = sc[0]
                for a in range(cards[i]):
                    lo, hi = log_enclosure(vals[a], cache); h[off[i] + a] += float((lo + hi) / 2)
                continue
            i, j = sc; ki, kj = cards[i], cards[j]
            L = [[log_enclosure(vals[a * kj + b], cache) for b in range(kj)] for a in range(ki)]
            for a in range(ki):
                for b in range(kj): lw_max = max(lw_max, L[a][b][1] - L[a][b][0])
            # row / column / grand means as exact intervals; centered entry C_ab = L_ab - rowmean_a - colmean_b + grand (every term an interval; subtraction swaps endpoints)
            row = [(sum(L[a][b][0] for b in range(kj)) / kj, sum(L[a][b][1] for b in range(kj)) / kj) for a in range(ki)]
            col = [(sum(L[a][b][0] for a in range(ki)) / ki, sum(L[a][b][1] for a in range(ki)) / ki) for b in range(kj)]
            grand = (sum(r[0] for r in row) / ki, sum(r[1] for r in row) / ki)
            key = (min(i, j), max(i, j)); blk = acc.get(key)
            if blk is None: blk = acc[key] = [[[F(0), F(0)] for _ in range(cards[key[1]])] for _ in range(cards[key[0]])]
            flip = (i != key[0])                                                                                 # the factor's (i, j) orientation vs the canonical (min, max) block
            for a in range(ki):
                for b in range(kj):
                    clo = L[a][b][0] - row[a][1] - col[b][1] + grand[0]; chi = L[a][b][1] - row[a][0] - col[b][0] + grand[1]; mw_max = max(mw_max, chi - clo)
                    cell = blk[b][a] if flip else blk[a][b]; cell[0] += clo; cell[1] += chi                     # EXACT accumulation (repeated factors on one pair)
                if (a & 15) == 15: clock.poll('spectral witness: block (%d, %d) row %d' % (i, j, a))
            # the row / column means move into the unary fields (advisory floats for x0 selection; the certificate never uses h)
            for a in range(ki): h[off[i] + a] += float((row[a][0] + row[a][1]) / 2)
            for b in range(kj): h[off[j] + b] += float((col[b][0] + col[b][1]) / 2)
            nblocks += 1
        # ONE outward conversion per accumulated entry (symmetric placement)
        done = 0
        for (i, j), blk in acc.items():
            for a in range(cards[i]):
                for b in range(cards[j]):
                    flo, fhi = to_float_outward(blk[a][b][0], blk[a][b][1]); A_lo[off[i] + a, off[j] + b] = flo; A_hi[off[i] + a, off[j] + b] = fhi; A_lo[off[j] + b, off[i] + a] = flo; A_hi[off[j] + b, off[i] + a] = fhi; done += 1
                    if (done & 255) == 255: clock.poll('spectral witness: outward conversion (%d entries)' % done)
        acc = None; txn.release(tok_temp)
        rec = dict(A_lo=A_lo, A_hi=A_hi, offsets=off, D=D, n=n, cards=cards, pairs=len(pair_entries), blocks=nblocks, log_width_max=float(lw_max), matrix_width_max=float(mw_max), h=h, bytes=owned, token=tok_need, seconds=CE.tnow() - t0, cache=cache.record(), exact_accumulation=True)
        if own_cache: cache.release()
        if own_txn: txn.release(tok_need); rec['token'] = None; txn.__exit__(None, None, None)                   # a standalone call (controls): the matrix charge is released at return (the arrays are returned uncharged, as before)
        return rec
    except BaseException as e:
        if own_txn: txn.__exit__(type(e), e, e.__traceback__)
        raise


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
        clock.poll('interval Cholesky entry %s' % tag); L_lo = np.zeros((D, D)); L_hi = np.zeros((D, D)); minpiv = math.inf
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


def propose_bounds(A_lo, A_hi, budget=None, clock=None, txn=None):
    """advisory: floating eigenvalues of the midpoint matrix, widened by the matrix radius and a relative margin -> proposed (l, u). The midpoint matrix and the eigensolver workspace are ADMITTED before allocation (review RV6) as a
    transaction-owned temporary (DGP10: rolled back on any exception; the 1,096 B retained charge of the review's fixture is a transferred token of the same transaction)."""
    D = A_lo.shape[0]; own = txn is None
    if own: txn = RV.Txn(budget, clock, 'eigenvalue proposal'); txn.__enter__()
    try:
        if clock is not None: clock.poll('eigenvalue proposal')
        tok = txn.reserve(3 * 8 * D * D + 64 * 8 * D + 4096, 'eigenvalue proposal: midpoint matrix + eigensolver workspace %d x %d' % (D, D))
        mid = 0.5 * (A_lo + A_hi); rad = float(np.max(np.sum(0.5 * (A_hi - A_lo), axis=1))); ev = np.linalg.eigvalsh(mid); lmin = float(ev[0]); lmax = float(ev[-1]); scale = max(abs(lmin), abs(lmax), 1.0)
        marg = rad + PROFILE['proposal_margin_rel'] * scale + PROFILE['proposal_margin_abs']; mid = None; ev = None; txn.release(tok)
        if own: txn.__exit__(None, None, None)
        return dict(lambda_min_float=lmin, lambda_max_float=lmax, radius_norm=rad, l=lmin - marg, u=lmax + marg, margin=marg)
    except BaseException as e:
        if own: txn.__exit__(type(e), e, e.__traceback__)
        raise


def _shifted(A, s, sign, lo_side):
    """sign x (A - s I) widened outward (lo_side: lower endpoint, else upper) on an ADMITTED copy, in place: no identity matrix, one D x D temporary for |x| (admitted by the caller)"""
    M = A.copy() if sign > 0 else -A; idx = np.arange(A.shape[0]); M[idx, idx] -= sign * s
    if lo_side: M -= WIDEN * U53 * np.abs(M); M -= TINY
    else: M += WIDEN * U53 * np.abs(M); M += TINY
    return M


def _prove(built, l, u, clock, budget, txn=None):
    """both proofs at the given (l, u); DGP10 (review F9-3): the shifted interval matrices (two D x D arrays + one D x D temporary for the outward widening) are ADMITTED BEFORE any allocation and no identity matrix is ever built;
    the charge is a transaction-owned temporary (rolled back on any exception) when a txn is given"""
    D = built['D']; own = txn is None
    if own: txn = RV.Txn(budget, clock, 'spectral proof'); txn.__enter__()
    try:
        tok = txn.reserve(3 * 8 * D * D + 4096, 'shifted interval matrices %d x %d' % (D, D)); t1 = CE.tnow()
        low = interval_cholesky_pd(_shifted(built['A_lo'], l, +1, True), _shifted(built['A_hi'], l, +1, False), clock, budget, 'A - lI')                       # the shift acts on the DIAGONAL only (widened inside)
        high = interval_cholesky_pd(_shifted(built['A_hi'], u, -1, True), _shifted(built['A_lo'], u, -1, False), clock, budget, 'uI - A')
        txn.release(tok)
        if own: txn.__exit__(None, None, None)
        return low, high, CE.tnow() - t1
    except BaseException as e:
        if own: txn.__exit__(type(e), e, e.__traceback__)
        raise


def certify(M, budget, clock, l=None, u=None, policy=None):
    """the full witness: build the interval matrix, propose (l, u) unless given, PROVE lambda_min(A) >= l and lambda_max(A) <= u by two interval Cholesky runs (under `policy` the proposal is widened by the frozen extra margins
    until a proof succeeds or the width cannot qualify), compute w / m / g outward. -> dict (never raises on ineligibility: `eligible` False with `refusal`); raises RefusedSpectral only for the class violations (arity / hard zero)
    and CE.Refused / Deadline from admission / polls. The returned record keeps `retained_bytes` CHARGED (h / offsets / cards): the caller releases them (`release_retained`)."""
    t0 = CE.tnow(); policy = policy or POLICY_FIXED
    with RV.Txn(budget, clock, 'spectral witness') as txn:
        cache = LogCache(budget, clock, txn=txn); built = build_interaction(M, budget, clock, cache, txn=txn); owned = built['bytes']; cache_rec = cache.record(); cache.release()
        D = built['D']; n = built['n']; retained = 8 * D + 40 * (2 * n + 1) + 1024; tok_ret = txn.reserve(retained, 'spectral witness: retained advisory fields / offsets / cards'); owner = RV.Owner(budget, 'spectral witness retained fields')
        def done(rec):
            """the successful return: the retained token is TRANSFERRED to the owner (the matrix token is released: A_lo / A_hi are not retained), the owner travels with the record"""
            txn.release(built['token']); txn.transfer(tok_ret, owner); rec['owner'] = owner; return rec
        prop = propose_bounds(built['A_lo'], built['A_hi'], budget, clock, txn=txn)
        l0 = prop['l'] if l is None else float(l); u0 = prop['u'] if u is None else float(u)
        if not (l0 <= 0.0 <= u0): return done(dict(eligible=False, refusal=dict(kind='SPECTRAL_BOUNDS', reason='proposed bounds do not bracket zero (trace A = 0 forces lambda_min <= 0 <= lambda_max)'), proposal=prop, policy=policy['name'], attempts=[], dimension=D, n=n, seconds=CE.tnow() - t0, bytes=owned, retained_bytes=retained, cache=cache_rec, **_strip(built)))
        attempts = []; low = high = None; l_used = u_used = None; t_ver = 0.0; stop = None
        for k, e in enumerate(policy['extra_margins']):
            lk = l0 - e; uk = u0 + e
            if F(uk) - F(lk) >= 2:
                stop = 'width cannot qualify at extra margin %g (u - l = %.9f >= 2)' % (e, uk - lk); break
            lo_, hi_, dt = _prove(built, lk, uk, clock, budget, txn=txn); t_ver += dt
            attempts.append(dict(attempt=k, extra_margin=e, l=lk, u=uk, width_float=uk - lk, lower_ok=lo_['ok'], upper_ok=hi_['ok'], min_pivot_lower=min(lo_['min_pivot_lower'], hi_['min_pivot_lower']), seconds=dt, gap_g_float=((1 - (uk - lk) / 2) / n)))
            low, high, l_used, u_used = lo_, hi_, lk, uk
            if lo_['ok'] and hi_['ok']: break
        if low is None:
            w0 = F(u0) - F(l0); w0_up = math.nextafter(float(w0), math.inf) if F(float(w0)) < w0 else float(w0)                 # the PROPOSED width (no proof was attempted: the width test alone refuses); reported as `width` for the refusal record, flagged unproved
            return done(dict(eligible=False, refusal=dict(kind='SPECTRAL_WIDTH', reason=stop or 'no proof attempt'), l=l0, u=u0, width=w0_up, width_proved=False, width_proposal_float=u0 - l0, width_exact=str(w0), margin_m=float(1 - w0 / 2), gap_g=None, proposal=prop, policy=policy['name'], attempts=attempts, dimension=D, n=n, seconds=CE.tnow() - t0, bytes=owned, retained_bytes=retained, cache=cache_rec, **_strip(built)))
        l, u = l_used, u_used
        # w = u - l rounded UP; m = 1 - w / 2 rounded DOWN; g = m / n rounded DOWN (exact dyadics via Fractions of the floats)
        wF = F(u) - F(l); mF = 1 - wF / 2; gF = mF / n
        w_up = math.nextafter(float(wF), math.inf) if F(float(wF)) < wF else float(wF); m_dn = math.nextafter(float(mF), -math.inf) if F(float(mF)) > mF else float(mF); g_dn = math.nextafter(float(gF), -math.inf) if F(float(gF)) > gF else float(gF)
        ok = bool(low['ok'] and high['ok']); elig = ok and (wF < 2)
        ref = None
        if not low['ok']: ref = dict(kind='SPECTRAL_PROOF', reason='A - lI not proved positive definite (pivot lower bound %.3e at column %s) after %d attempt(s)%s' % (low['min_pivot_lower'], low['failed_column'], len(attempts), ('; ' + stop) if stop else ''))
        elif not high['ok']: ref = dict(kind='SPECTRAL_PROOF', reason='uI - A not proved positive definite (pivot lower bound %.3e at column %s) after %d attempt(s)%s' % (high['min_pivot_lower'], high['failed_column'], len(attempts), ('; ' + stop) if stop else ''))
        elif wF >= 2: ref = dict(kind='SPECTRAL_WIDTH', reason='checked width %.6f >= 2: the spectral condition does not hold (not a statement about mixing)' % float(wF))
        return done(dict(eligible=elig, refusal=ref, l=l, u=u, width=float(w_up), width_exact=str(wF), margin_m=(m_dn if elig else float(m_dn)), gap_g=(g_dn if elig else None), m_exact=str(mF), g_exact=str(gF), dimension=D, n=n, proposal=prop, policy=policy['name'], attempts=attempts, proof=dict(lower=low, upper=high, seconds_verify=t_ver), seconds=CE.tnow() - t0, seconds_construct=built['seconds'], bytes=owned, retained_bytes=retained, cache=cache_rec, **_strip(built)))


def release_retained(W, budget):
    """the caller's release of the retained witness fields (idempotent): DGP10 (review F9-3) the owner's token is closed AND the retained arrays / lists are DROPPED from the record (h / offsets / cards -> None), so no alias of the
    released data survives through the record; returns the bytes released"""
    n = 0; owner = W.get('owner')
    if owner is not None: n = owner.close(); W['owner'] = None
    elif W.get('retained_bytes'): n = W['retained_bytes']; budget.release(n)
    if W.get('retained_bytes'): W['retained_bytes'] = 0; W['retained_released'] = True
    for k in ('h', 'offsets', 'cards', 'A_lo', 'A_hi'): W[k] = None
    return n


def _strip(built): return dict(pairs=built['pairs'], blocks=built['blocks'], log_width_max=built['log_width_max'], matrix_width_max=built['matrix_width_max'], h=built['h'], offsets=built['offsets'], cards=built['cards'])


def witness_record(w):
    """the JSON-safe record of a certify() result (arrays dropped)"""
    out = {k: v for k, v in w.items() if k not in ('h', 'offsets', 'cards', 'owner', 'token')}
    if 'proposal' in out: out['proposal'] = {k: v for k, v in out['proposal'].items()}
    return out
