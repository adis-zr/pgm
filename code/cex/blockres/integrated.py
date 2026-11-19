"""INTEGRATED block-contraction inference, v2 (round 4, 19 Nov 2026). Repairs after the overseer's reproduction of two numerical defects in v1:
  (1) relative-error bounds are EXACT RATIONALS (Fraction), never float expressions that absorb u = 2^-53 into 1.0; they become floats only by rounding UP at the point of use;
  (2) every product of float tables is PRE-CHECKED: the sum of the operands' dynamic ranges (bits from the maximum down to the smallest nonzero entry) must stay within
      1000 bits, so no positive product can underflow; a violation REFUSES the float path (typed NUMERIC_RANGE_REFUSED) before any information is lost. A float zero is
      therefore always an exact zero (ZERO_EVIDENCE from U = 0 stays exact);
  (3) the confidence-set inversion is conservative: accumulators are widened by their exact accumulation bound as a function of the ACTUAL draw count t (no fixed horizon),
      the quadratic feasibility is evaluated with outward-rounded float arithmetic, and the excluded root intervals are shrunk by bisection on the upper-bounded function;
  (4) the complete streaming loop (proposal draws, weights, query responses, certificate updates) is BATCH-VECTORIZED with the certificate's predictable quantities fixed per
      batch (any predictable choice is valid), and two predictable lambda schedules are selectable: 'baseline' (1 / sqrt(t log t)) and 'targeted'
      (lambda = 2 E[X] eps / (v + 2 E[X] eps), the overseer's accuracy-targeted heuristic; validity from predictability alone).
Mathematics as in NOTE.md sections 5-6; the widening terms are now derived from the tracked exact bounds (section 7)."""
import sys, os, json, time, argparse, random, resource, math
from fractions import Fraction as F
from math import prod, inf, log2, frexp, ldexp, nextafter
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
import blockres as BR
from blockres import tnow, Deadline, lg

VERSION = 'blockres-integrated-v2.1 (2026-11-19 round 5: power-of-two exponents cancelled exactly before any float log; widening from the actual tracked log magnitudes; v2 round 4: exact-rational error bounds, product underflow pre-check, conservative inversion, batch loop, lambda schedules)'
UF = F(1, 1 << 53); U = 2.0 ** -53
RANGE_BUDGET = 1000                  # bits: sum of operand ranges allowed in ONE product (its smallest nonzero entry stays >= 2^-1000 of its max: normal, nonzero)
RANGE_BITS = 900                     # a table whose smallest nonzero entry is below 2^-900 of its maximum is refused outright
MIN_BITS = 64
PROB_TRUNC_LOG2 = -900
FLOAT_BYTE_CAP = 256 << 20


class RangeRefused(Exception): pass


def up(x): return nextafter(x, inf)
def dn(x): return nextafter(x, -inf)
def fup(fr): return up(float(fr))


# ---------------------------------------------------------------- scaled binary64 tables: entry in [M (1 - rho), M (1 + rho)] 2^e; rho EXACT; R = dynamic range in bits
class FT:
    __slots__ = ('scope', 'M', 'e', 'rho', 'R', 'interior', 'facs')
    def __init__(self, scope, M, e, rho, interior=(), facs=frozenset()):
        self.scope = tuple(scope); self.M = M; self.e = e; self.rho = F(rho); self.interior = list(interior); self.facs = facs
        nz = M[M > 0]; self.R = (int(math.ceil(-log2(float(nz.min())))) + 1) if nz.size else 0


def _rescale(P, e):
    m = float(P.max()) if P.size else 0.0
    if m == 0.0: return P, 0
    k = frexp(m)[1] - 1; P = P * ldexp(1.0, -k)
    nz = P[P > 0]
    if nz.size and float(nz.min()) < ldexp(1.0, -RANGE_BITS): raise RangeRefused('table dynamic range exceeds 2^%d' % RANGE_BITS)
    return P, e + k


def ft_from_int(fn, cards):
    flat = np.asarray(fn.arr, dtype=object).reshape(-1).tolist(); nmax = max((int(v) for v in flat), default=0); shape = np.asarray(fn.arr).shape
    if nmax == 0: return FT(fn.scope, np.zeros(shape, dtype=float), 0, F(0), fn.interior, fn.facs)
    k = max(0, nmax.bit_length() - 1000)
    if k:
        for n in flat:
            if n and n.bit_length() - k < MIN_BITS: raise RangeRefused('an exact entry would keep %d < %d significant bits' % (n.bit_length() - k, MIN_BITS))
    M = np.array([float(n >> k) for n in flat], dtype=float).reshape(shape)
    rho = UF + (F(1, 1 << (MIN_BITS - 1)) if k else F(0))
    M, e = _rescale(M, k); return FT(fn.scope, M, e, rho, fn.interior, fn.facs)


def ft_product(fts, cards):
    rb = sum(f.R for f in fts)
    if rb > RANGE_BUDGET: raise RangeRefused('a product of %d tables could underflow (range bits %d > %d)' % (len(fts), rb, RANGE_BUDGET))
    union = tuple(sorted(set().union(*(set(f.scope) for f in fts)))); P = None; e = 0; r = F(1)
    for f in fts:
        a = f.M.reshape([cards[v] if v in f.scope else 1 for v in union]); P = a if P is None else P * a; e += f.e; r *= (1 + f.rho)
    r *= (1 + UF) ** max(0, len(fts) - 1); return union, P, e, r - 1


def ft_eliminate(bucket, v, cards, agg='sum'):
    union, P, e, rho = ft_product(bucket, cards); ax = union.index(v); n = cards[v]
    if agg == 'sum': R = P.sum(axis=ax); rho = (1 + rho) * (1 + UF) ** max(0, n - 1) - 1
    elif agg == 'max': R = P.max(axis=ax)
    else: R = P.min(axis=ax)
    scope = tuple(u for u in union if u != v); R = np.asarray(R, dtype=float).reshape([cards[u] for u in scope]) if scope else np.asarray(R, dtype=float).reshape(())
    R, e = _rescale(R, e); return FT(scope, R, e, rho, [u for f in bucket for u in f.interior] + [v], frozenset().union(*(f.facs for f in bucket)))


def recover_query_table_float(block_ft, x, cards, trace_ft, trace_var, step_of, deadline, stats):
    i = step_of[x]; live = [f for f in trace_ft[i] if f.facs <= block_ft.facs]
    for st in sorted(step_of[u] for u in block_ft.interior if step_of[u] > i):
        if tnow() >= deadline: raise Deadline('recover_float')
        v = trace_var[st]; bucket = [f for f in live if v in f.scope]
        if not bucket: continue
        live = [f for f in live if v not in f.scope]; nb = set().union(*(set(f.scope) for f in bucket)) - {v}; sz = prod(cards[u] for u in nb) if nb else 1
        if sz * cards[v] * 8 > FLOAT_BYTE_CAP: return None
        live.append(ft_eliminate(bucket, v, cards)); stats['query_work'] += sz * cards[v] * len(bucket)
    union, P, e, rho = ft_product(live, cards)
    assert set(union) == set(block_ft.scope) | {x}, (union, block_ft.scope, x)
    P = np.moveaxis(P, union.index(x), -1); P, e = _rescale(np.ascontiguousarray(P), e); return FT(tuple(u for u in union if u != x) + (x,), P, e, rho)


# ---------------------------------------------------------------- mini-bucket proposal in float with a batch sampler
class MBFloat:
    def __init__(self, blocks, cards, cap, deadline):
        self.cards = cards; live = [FT(b.scope, b.M, b.e, b.rho) for b in blocks]; steps = []; logU_f = 0.0; E_U = 0; n_scalar = 0; rhoU = F(0); order = []; vars_ = sorted({v for f in live for v in f.scope}); self.max_range_sum = 0
        while vars_:
            if tnow() >= deadline: raise Deadline('mb_float')
            best = None
            for v in vars_:
                nb = set().union(*(set(f.scope) for f in live if v in f.scope)) - {v}; size = prod(cards[u] for u in nb) if nb else 1
                if best is None or size < best[0]: best = (size, v)
            v = best[1]; order.append(v); vars_.remove(v); bucket = [f for f in live if v in f.scope]; live = [f for f in live if v not in f.scope]
            if not bucket: logU_f += log2(cards[v]); n_scalar += 1; steps.append((v, None)); continue
            bucket.sort(key=lambda f: -len(f.scope)); groups = []
            for f in bucket:
                for g in groups:
                    u = g[0] | set(f.scope)
                    if prod(cards[x] for x in u) <= cap: g[0] = u; g[1].append(f); break
                else: groups.append([set(f.scope), [f]])
            for gi, (u, members) in enumerate(groups):
                self.max_range_sum = max(self.max_range_sum, sum(f.R for f in members)); R = ft_eliminate(members, v, cards, 'sum' if gi == 0 else 'max')
                if R.scope: live.append(R)
                else:
                    if float(R.M) == 0.0: logU_f = -inf
                    else: logU_f += log2(float(R.M)); E_U += R.e; n_scalar += 1          # float part in [0, 1) per scalar; the exponent stays an exact integer
                    rhoU = (1 + rhoU) * (1 + R.rho) - 1
            steps.append((v, groups[0][1]))
        self.steps = steps; self.order = order; self.rhoU = rhoU; self.logU_f = logU_f; self.E_U = E_U; self.logU = (logU_f + E_U) if logU_f > -inf else -inf; self.n_scalar = n_scalar
        self.max_table = max((f.M.size for _, q1 in steps if q1 for f in q1), default=0); self.max_q1 = max((len(q1) for _, q1 in steps if q1), default=0)
        self.prep = []
        for v, q1 in steps:
            if q1 is None: self.prep.append((v, None)); continue
            tabs = []
            for f in q1:
                with np.errstate(divide='ignore'): LM = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape(-1)       # log2 M only: |LM| <= R_f; the exponent cancels in the row normalization
                strides = {}; s_ = 1
                for u in reversed(f.scope): strides[u] = s_; s_ *= cards[u]
                tabs.append((LM, strides, f.scope))
            self.prep.append((v, tabs))
        self.step_ranges = [[f.R for f in q1] if q1 else [] for _, q1 in steps]

    def logq_given(self, S, pos):
        """implemented log2 q(S) for given assignments S (B, n_sep): the SAME float operations as sample_batch, deterministic; also returns the analysed q as exact Fractions"""
        B = S.shape[0]; logq = np.zeros(B); q_an = [F(1)] * B; cards = self.cards
        for v, tabs in reversed(self.prep):
            n = cards[v]; pv = pos[v]
            if tabs is None: logq -= log2(n); q_an = [q / n for q in q_an]; continue
            L = np.zeros((B, n))
            for LM, strides, scope in tabs:
                base = np.zeros(B, dtype=np.int64)
                for u in scope:
                    if u != v: base += S[:, pos[u]] * strides[u]
                L += LM[base[:, None] + np.arange(n)[None, :] * strides[v]]
            Lmax = L.max(axis=1); dead = ~np.isfinite(Lmax)
            p = np.exp2(L - np.where(dead, 0.0, Lmax)[:, None]); p[p < ldexp(1.0, PROB_TRUNC_LOG2)] = 0.0; p[dead] = 1.0 / n
            tot = p.sum(axis=1); a = S[:, pv]; pa = p[np.arange(B), a]
            logq += np.log2(np.where(pa > 0, pa, 1.0)) - np.log2(tot); logq[pa == 0] = -inf
            for i in range(B): q_an[i] = q_an[i] * (F(float(pa[i])) / sum(F(float(x)) for x in p[i].tolist()))
        return logq, q_an


    def sample_batch(self, rng, B, pos):
        """B draws: S (B, n_sep) in separator order, log2 q (B,), zero_row (B,) = a row every completion of which has z = 0 (uniform draw, weight 0)"""
        n_sep = len(pos); S = np.zeros((B, n_sep), dtype=np.int64); logq = np.zeros(B); zero_row = np.zeros(B, dtype=bool); cards = self.cards
        for v, tabs in reversed(self.prep):
            n = cards[v]; pv = pos[v]
            if tabs is None: S[:, pv] = rng.integers(0, n, size=B); logq -= log2(n); continue
            L = np.zeros((B, n))
            for LM, strides, scope in tabs:
                base = np.zeros(B, dtype=np.int64)
                for u in scope:
                    if u != v: base += S[:, pos[u]] * strides[u]
                L += LM[base[:, None] + np.arange(n)[None, :] * strides[v]]
            Lmax = L.max(axis=1); dead = ~np.isfinite(Lmax)
            p = np.exp2(L - np.where(dead, 0.0, Lmax)[:, None]); p[p < ldexp(1.0, PROB_TRUNC_LOG2)] = 0.0; p[dead] = 1.0 / n
            tot = p.sum(axis=1); c = np.cumsum(p, axis=1); r = rng.random(B) * tot; a = np.minimum((c <= r[:, None]).sum(axis=1), n - 1)
            pa = p[np.arange(B), a]; bad = pa == 0.0
            if bad.any(): a[bad] = p[bad].argmax(axis=1); pa = p[np.arange(B), a]
            S[:, pv] = a; logq += np.log2(pa) - np.log2(tot); zero_row |= dead
        return S, logq, zero_row


# ---------------------------------------------------------------- the certificate: batch updates, conservative inversion
class Certificate:
    def __init__(self, K, alpha, eps_num, eps, schedule):
        self.K = K; self.alpha = alpha; self.log_term = 2.0 * math.log(2.0 / alpha); self.eps_num = eps_num; self.eps = eps; self.schedule = schedule; self.t = 0; self.lam_max = 0.9
        z = lambda: np.zeros(K); self.SA = z(); self.SB = 0.0; self.SXX = 0.0; self.SXXf = z(); self.SXXff = z(); self.A = z(); self.B = z(); self.Lam = z(); self.Psi = z(); self.P = z(); self.Q = z(); self.Qabs = z(); self.R = z()
    def variance(self):
        t = max(1, self.t); mhat = np.where(self.SB > 0, np.clip(self.SA / max(self.SB, 1e-300), 0.0, 1.0), 0.5)
        mean = (self.SA - mhat * self.SB) / t; var = (self.SXXff - 2 * mhat * self.SXXf + mhat * mhat * self.SXX) / t - mean * mean
        return np.maximum(var, 1e-14), mhat
    def lam(self):
        if self.t < 2: return np.full(self.K, 0.25)
        var, _ = self.variance()
        if self.schedule == 'targeted':
            EX = max(self.SB / self.t, 1e-300); g = 2 * EX * self.eps; return np.clip(g / (var + g), 1e-4, self.lam_max)
        return np.clip(np.sqrt(self.log_term / (var * self.t * math.log(self.t + 1.0))), 1e-4, self.lam_max)
    def update_batch(self, X, f):
        B = X.shape[0]; lam = self.lam(); psi = (-np.log1p(-lam) - lam) / 4.0; t1 = self.t + 1
        Xf = X[:, None] * f; a = Xf - (self.SA / t1)[None, :]; b = (X - self.SB / t1)[:, None]
        self.A += lam * Xf.sum(axis=0); self.B += lam * X.sum(); self.Lam += B * lam; self.Psi += B * psi
        self.P += psi * (a * a).sum(axis=0); ab = a * b; self.Q += psi * ab.sum(axis=0); self.Qabs += psi * np.abs(ab).sum(axis=0); self.R += psi * (b * b).sum(axis=0)
        self.SA += Xf.sum(axis=0); self.SB += X.sum(); self.SXX += (X * X).sum(); self.SXXf += (X[:, None] * Xf).sum(axis=0); self.SXXff += (Xf * Xf).sum(axis=0); self.t += B
    def sets(self):
        """conservative [lo_j, hi_j] containing {m in [0,1] : 0 in CS_t(m)}; nan = empty (recorded, never published)"""
        t = self.t; acc = up(up((t + 2) * U) * (1 + 2 ** -40)); eps = self.eps_num; K = self.K
        A_up = self.A * (1 + acc); B_up = self.B * (1 + acc); P_up = self.P * (1 + acc); R_up = self.R * (1 + acc); Lam_up = self.Lam * (1 + acc); Psi_up = self.Psi * (1 + acc); Qerr = self.Qabs * acc * (1 + acc)
        c_up = np.nextafter(np.nextafter(self.log_term * (1 + 2 ** -45) + np.nextafter(Lam_up * eps, inf) + np.nextafter(8 * eps * Psi_up, inf), inf), inf)
        lo = np.zeros(K); hi = np.ones(K)
        for j in range(K):
            A, B = self.A[j], self.B[j]; Aerr = up(A_up[j] - A); Berr = up(B_up[j] - B); aq = up(2 * R_up[j]); kept = []
            if B <= 0: continue
            m0 = min(1.0, max(0.0, A / B))
            for side in (-1.0, 1.0):                                  # side -1: m <= m0 where A - mB >= 0 ; side +1: m >= m0
                bq = up(up(up(-4 * self.Q[j]) + up(4 * Qerr[j])) + up(-side * B + Berr)); cq = up(up(up(c_up[j] + 2 * P_up[j]) + side * A) + Aerr)
                rlo, rhi = (0.0, m0) if side < 0 else (m0, 1.0)
                if rhi < rlo: continue
                ex = _excluded(aq, bq, cq, rlo, rhi)
                if ex is None: kept.append((rlo, rhi))
                else:
                    if ex[0] > rlo: kept.append((rlo, ex[0]))
                    if ex[1] < rhi: kept.append((ex[1], rhi))
            if not kept: lo[j] = np.nan; hi[j] = np.nan; continue
            lo[j] = max(0.0, dn(min(k[0] for k in kept))); hi[j] = min(1.0, up(max(k[1] for k in kept)))
        return lo, hi


def _h_up(aq, bq, cq, m):
    """upper bound of aq m^2 + bq m + cq (aq >= 0, m >= 0), outward rounding at every operation"""
    return up(up(up(up(aq * m) * m) + up(bq * m)) + cq)


def _excluded(aq, bq, cq, lo, hi):
    """open sub-interval of [lo, hi] where h_up < 0 (a SUBSET of the true excluded interval of the convex quadratic); None if nothing is excluded"""
    if aq > 0:
        disc = bq * bq - 4 * aq * cq
        if disc <= 0: return None
        r = math.sqrt(disc); r1 = (-bq - r) / (2 * aq); r2 = (-bq + r) / (2 * aq)
    elif bq != 0:
        root = -cq / bq; r1, r2 = (root, inf) if bq < 0 else (-inf, root)
    else: return (lo, hi) if cq < 0 else None
    a, b = max(lo, r1), min(hi, r2)
    if b <= a: return None
    mid = (a + b) / 2
    if _h_up(aq, bq, cq, mid) >= 0: return None
    def bisect(x_ok, x_bad):
        for _ in range(64):
            xm = (x_ok + x_bad) / 2
            if _h_up(aq, bq, cq, xm) >= 0: x_ok = xm
            else: x_bad = xm
        return x_ok
    left = bisect(lo, mid) if _h_up(aq, bq, cq, lo) >= 0 else lo
    right = bisect(hi, mid) if _h_up(aq, bq, cq, hi) >= 0 else hi
    return (left, right)


class ZCertificate:
    """PrPl-EB confidence sequence for E[X] = Z / U_cap from the same draws (WMB-IS-style baseline; batch form; reported, not used)"""
    def __init__(self, alpha): self.log_term = math.log(2.0 / alpha); self.t = 0; self.S = 0.0; self.S2 = 0.0; self.A = 0.0; self.Lam = 0.0; self.V = 0.0
    def update_batch(self, X):
        B = X.shape[0]; t = max(1, self.t); var = max(self.S2 / t - (self.S / t) ** 2, 1e-12) if self.t >= 2 else 0.25
        lam = min(0.9, math.sqrt(2 * self.log_term / (var * (self.t + 1) * math.log(self.t + 2.0)))); psi = (-math.log1p(-lam) - lam) / 4.0; mu_hat = (0.5 + self.S) / (self.t + 1)
        self.A += lam * X.sum(); self.Lam += B * lam; self.V += psi * 4.0 * ((X - mu_hat) ** 2).sum(); self.S += X.sum(); self.S2 += (X * X).sum(); self.t += B
    def interval(self):
        if self.Lam <= 0: return (0.0, 1.0)
        acc = (self.t + 2) * U * 2; c = self.A / self.Lam; r = (self.log_term + self.V * (1 + acc)) / self.Lam * (1 + acc); return (max(0.0, c - r), min(1.0, c + r))


# ---------------------------------------------------------------- numerical widening (NOTE.md section 8): exact Fractions from the ACTUAL tracked magnitudes, rounded up once
def numerical_widening(blocks, mbp, qrhos, n_sep, maxcard, E_tot):
    """Every float log2 value in the loop is log2 of a scaled mantissa (|value| <= the table's range bits R) or a sum of such; power-of-two exponents are exact integers
    combined once as E_tot. Errors are accumulated as ABSOLUTE log2 errors (Fractions) and converted to relative errors by 2^d - 1 <= 1.45 d (1 + d) for d <= 1/4."""
    u = UF; L2 = F(145, 100)
    def logerr(mag): return u * (F(mag) + 1)                                                       # |fl(log2 x) - log2 x| <= u |log2 x| + u for a correctly rounded-to-nearest log2 within 1 ulp
    # (a) tables vs exact integers
    rho_tab = prod((1 + b.rho) for b in blocks) - 1
    # (b) the proposal rows: float p_a vs the exact products of the float tables (enters the CAP), and the implemented log2 q vs the analysed law (enters eps_num)
    d_cap = F(0); d_impl = F(0); mag_logq = F(0)
    for Rs in mbp.step_ranges:
        if not Rs: mag_logq += F(int(maxcard).bit_length()); continue
        SR = sum(Rs); q1 = len(Rs)
        dL = sum(logerr(R) for R in Rs) + u * (q1 + 1) * (SR + q1)                                  # row log-sum: per-lookup log errors + (q1 + 1) roundings on partial sums of magnitude <= SR + q1
        rel_p = L2 * dL * (1 + dL) + 4 * u                                                           # exp2 of the row argument (libm exp2 assumed within 2 ulps), relative
        rel_cond = 2 * rel_p + (maxcard - 1) * u                                                     # p_a / tot vs exact: both carry rel_p, the float sum adds (n-1) u
        d_cap += rel_cond / F(69, 100)                                                               # relative -> log2 absolute (1 / ln 2 <= 1.45; also log2(1 + r) <= 1.45 r)
        d_impl += logerr(901) + logerr(int(maxcard).bit_length() + 1) + u * (mag_logq + 910)         # implemented log2 p_a - log2 tot (|log2 p_a| <= 901 by truncation, |log2 tot| <= log2 n) + the running-sum rounding
        mag_logq += 901 + int(maxcard).bit_length() + 1
    # (c) z: sum over blocks of log2 M_b (|.| <= R_b), nb - 1 roundings on partial sums
    SRb = sum(b.R for b in blocks); nb = len(blocks); d_z = sum(logerr(b.R) for b in blocks) + u * nb * (SRb + nb)
    # (d) U: float part = sum of log2 of scalar mantissas in [1, 2) plus log2 of cardinalities, n_scalar roundings
    d_U = u * mbp.n_scalar * (mbp.n_scalar + int(maxcard).bit_length() + 2) + logerr(1) * mbp.n_scalar
    # (e) the final combination (logz - logq - logU_f) + E_tot: three subtractions / additions on magnitudes <= the listed bounds
    max_mag = max(SRb + nb, mag_logq, mbp.n_scalar + 2, abs(E_tot)) ; d_fin = 4 * u * (SRb + nb + mag_logq + mbp.n_scalar + 2 + abs(E_tot))
    d_total = d_z + d_impl + d_U + d_fin                                                              # implemented log2 X vs analysed log2 X (absolute, log2 units)
    rho_X = L2 * d_total * (1 + d_total)                                                              # relative error of the implemented X vs the analysed X
    rho_cap = (1 + rho_tab) * (1 + L2 * d_cap * (1 + d_cap)) * (1 + mbp.rhoU) * (1 + rho_X) - 1       # z_exact / (q_an U) <= 1 + rho_cap: tables, rows, scalar messages, implementation
    rho_f = max([2 * r for r in qrhos] + [F(0)]) + max([b.rho for b in blocks]) + 4 * UF
    law = 4 * n_sep * F(maxcard + 2, 1 << 53); trunc = n_sep * F(1, 1 << 900)
    return dict(rho_X=rho_X, rho_cap=rho_cap, rho_f=rho_f, law=law, trunc=trunc, eps_num=2 * rho_X + rho_f + law + trunc, delta_log_total=d_total, max_log_mag=max_mag)


# ---------------------------------------------------------------- the integrated solve
def solve(model_path, budget, seed=1, table_cap=1 << 18, enum_cap=1 << 16, eps=F(1, 200), delta=F(1, 10 ** 6), mb_cap=1 << 24, construct_share=0.5, batch=1024, check_s=0.5, force_approx=False, schedule='baseline'):
    t_start = tnow(); deadline = t_start + budget; ph = {}; rng = np.random.default_rng(seed); stats = dict(elim_work=0, eliminations=0, query_work=0)
    out = dict(version=VERSION, seed=seed, budget_s=budget, table_cap=table_cap, enum_cap=enum_cap, mb_cap=mb_cap, batch=batch, schedule=schedule, epsilon=str(eps), delta=str(delta), phases_s=ph, mechanism={}, outcome=None, answers=None)
    t0 = tnow(); model, binding = BR.core.read_uai(model_path); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); out['binding'] = binding; ph['read'] = tnow() - t0
    queries = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K = len(queries); qix = {q: j for j, q in enumerate(queries)}; out['K'] = K
    ans = {}; pending = {}; failed = []
    def publish(j, lo, hi, point, g): ans[j] = dict(lo=lo, hi=hi, point=point, guarantee=g)
    def finish_(oc, witness=None):
        out['outcome'] = oc
        if witness: ans.update(pending)
        out['positive_mass_witness'] = witness; return BR.finish(out, t_start, queries, ans, failed)
    try:
        t0 = tnow(); fns, const, scale, mult, factorless = BR.integerize(model); ph['integerize'] = tnow() - t0
        if const == 0: return finish_('ZERO_EVIDENCE')
        for x in factorless:
            for v in range(cards[x]): pending[qix[(x, v)]] = dict(lo=F(1, cards[x]), hi=F(1, cards[x]), point=F(1, cards[x]), guarantee='EXACT')
        cdead = min(deadline, t_start + construct_share * budget); t0 = tnow(); trace = []; order = []
        live = BR.contract(fns, cards, table_cap, cdead, stats, trace, order); ph['contract'] = tnow() - t0; step_of = {v: i for i, (v, _) in enumerate(trace)}
        const_fns = [f for f in live if not f.scope]; live = [f for f in live if f.scope]
        for f in const_fns: const *= int(f.arr)
        if const == 0: return finish_('ZERO_EVIDENCE')
        S = sorted({v for f in live for v in f.scope}); out['mechanism'].update(blocks=len(live), separator_vars=len(S), eliminated_vars=len(order), elim_work=stats['elim_work'], const_blocks=len(const_fns), factorless=len(factorless), N_S_log2=float(sum(log2(cards[v]) for v in S)))
        for b in const_fns:
            gb = int(b.arr)
            if gb == 0: continue
            bl = BR.Block(0, b, cards)
            for x in b.interior:
                r = BR.recover_query_table(bl, x, cards, table_cap * cards[x], trace, step_of, cdead, stats)
                if r is None: failed.append(x); continue
                for v in range(cards[x]): val = F(int(r[v]), gb); pending[qix[(x, v)]] = dict(lo=val, hi=val, point=val, guarantee='EXACT')
        if not live: return finish_('EXACT' if len(pending) == K else 'PARTIAL_EXACT', witness=True)
        N_S = prod(cards[v] for v in S)
        if N_S <= enum_cap and not force_approx:
            blocks_i = [BR.Block(i, f, cards) for i, f in enumerate(live)]; fac_fns = {next(iter(f.facs)): f for f in fns}
            for b in blocks_i:
                tabs = []
                for x in b.interior:
                    r = BR.recover_query_table(b, x, cards, table_cap * cards[x], trace, step_of, cdead, stats)
                    if r is None: failed.append(x); continue
                    tabs.append((x, r))
                b.set_queries(tabs, cards)
            inter = {x for b in blocks_i for x in b.interior if x not in set(failed)}; sq = [(x, v) for (x, v) in queries if x in set(S) or x in inter]; qmap = {q: qix[q] for q in sq}
            sep = BR.Separator(blocks_i, cards, S, sq, 'block', fac_fns, deadline); t0 = tnow(); sep.close(next(iter(sep.open))); ph['enumerate'] = tnow() - t0; Z = sep.mass
            if Z == 0: return finish_('ZERO_EVIDENCE')
            for j, q in enumerate(sq): r = F(int(sep.num[j]), Z); publish(qmap[q], r, r, r, 'EXACT')
            out['Z'] = str(F(Z * const * mult, scale)); return finish_('EXACT' if len(ans) + len(pending) == K else 'PARTIAL_EXACT', witness=True)
        # ---- float representation
        t0 = tnow()
        try:
            cache = {}
            def conv(f):
                if id(f) not in cache: cache[id(f)] = ft_from_int(f, cards)
                return cache[id(f)]
            blocks = [conv(f) for f in live]; trace_var = {}; trace_ft = []
            for st, (v, snap) in enumerate(trace): trace_var[st] = v; trace_ft.append([conv(f) for f in snap])
        except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['float_convert'] = tnow() - t0
        t0 = tnow(); qtabs = {i: [] for i in range(len(blocks))}; recovered = 0; skipped = []
        todo = sorted(((len([u for u in b.interior if step_of[u] > step_of[x]]), i, x) for i, b in enumerate(blocks) for x in b.interior))
        for _, i, x in todo:
            if tnow() >= cdead: skipped.append(x); continue
            try: r = recover_query_table_float(blocks[i], x, cards, trace_ft, trace_var, step_of, cdead, stats)
            except Deadline: skipped.append(x); continue
            except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
            if r is None: failed.append(x); continue
            qtabs[i].append((x, r)); recovered += 1
        failed += skipped; ph['query_tables'] = tnow() - t0
        out['mechanism'].update(interior_queries_recovered=recovered, interior_queries_failed=len(failed) - len(skipped), interior_queries_skipped_window=len(skipped), query_work=stats['query_work'])
        pos = {v: i for i, v in enumerate(S)}; sep_q = [(x, v) for (x, v) in queries if x in pos]
        blockQ = []; qcols = []
        for i, b in enumerate(blocks):
            cols = []; mats = []; es = []; rhos = []
            for x, r in qtabs[i]:
                for v in range(cards[x]): cols.append((x, v)); mats.append(r.M[..., v].reshape(-1)); es.append(r.e); rhos.append(r.rho)
            if cols:
                Q = np.stack([mats[c] * ldexp(1.0, es[c] - b.e) for c in range(len(cols))], axis=1)       # exact power-of-two alignment to the block exponent
                nzq = Q[Q > 0]
                if not np.all(np.isfinite(Q)) or (nzq.size and float(nzq.min()) < ldexp(1.0, -1000)): out['refusal'] = 'query-table alignment leaves the normal range'; return finish_('NUMERIC_RANGE_REFUSED')
                blockQ.append((i, Q, rhos)); qcols += cols
            else: blockQ.append((i, None, []))
        sq = sep_q + qcols; Kq = len(sq); qmap = {q: qix[q] for q in sq}; qrhos = [r for _, _, rs in blockQ for r in rs]
        t0 = tnow()
        try: mbp = MBFloat(blocks, cards, mb_cap, deadline)
        except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['mb_construct'] = tnow() - t0
        out['mechanism'].update(mb_cap=mb_cap, mb_logU=mbp.logU, mb_max_table=mbp.max_table, mb_max_range_sum_bits=mbp.max_range_sum, block_max_range_bits=max(b.R for b in blocks), Kq=Kq, sep_queries=len(sep_q), interior_query_cols=len(qcols))
        if mbp.logU == -inf: return finish_('ZERO_EVIDENCE')
        E_z = sum(b.e for b in blocks); E_tot = E_z - mbp.E_U                                     # EXACT integer: every power-of-two scale cancels here, never inside a float log
        if abs(E_tot) >= 1 << 50: out['refusal'] = 'exponent sum %d too large for an exact float' % E_tot; return finish_('NUMERIC_RANGE_REFUSED')
        wid = numerical_widening(blocks, mbp, qrhos, len(S), max(cards), E_tot); eps_num = fup(wid['eps_num']); rho_X = fup(wid['rho_X']); rho_cap = fup(wid['rho_cap'])
        if wid['delta_log_total'] > F(1, 4): out['refusal'] = 'log-domain error budget %s too large' % float(wid['delta_log_total']); return finish_('NUMERIC_RANGE_REFUSED')
        out['mechanism'].update(eps_num=eps_num, eps_num_log2=log2(eps_num), rho_X=rho_X, rho_cap=rho_cap, rho_f=fup(wid['rho_f']), mb_rhoU=fup(mbp.rhoU), E_tot=E_tot, delta_log_total=float(wid['delta_log_total']), max_log_magnitude=float(wid['max_log_mag']))
        logU_capf = up(mbp.logU_f + up(log2(1.0 + rho_cap)) + 2 ** -40)                           # float part of the cap (small magnitude); the exponent part is E_tot, exact
        cap_tol = up(log2(1.0 + 2 * rho_X)) + 2 ** -40                                             # the implemented X may exceed the analysed X <= 1 only by its proved relative error
        alpha = float(delta) / Kq; cert = Certificate(Kq, alpha, eps_num, float(eps), schedule); zcert = ZCertificate(float(delta))
        bLM = []; bstr = []; bscope = []; bMflat = []
        for b in blocks:
            with np.errstate(divide='ignore'): bLM.append(np.where(b.M > 0, np.log2(np.maximum(b.M, 1e-300)), -inf).reshape(-1))        # log2 M only
            strides = {}; s_ = 1
            for u in reversed(b.scope): strides[u] = s_; s_ *= cards[u]
            bstr.append(strides); bscope.append(b.scope); bMflat.append(b.M.reshape(-1))
        sep_pos = np.array([pos[x] for (x, v) in sep_q], dtype=np.int64); sep_val = np.array([v for (x, v) in sep_q], dtype=np.int64)
        witness = False; draws = 0; zero_draws = 0; pub = {}; trace_rows = []; t_loop = 0.0; t_cert = 0.0; next_chk = tnow() + check_s; sumX = 0.0; maxlogX = -inf
        def flat_index(Sb, i):
            idx = np.zeros(Sb.shape[0], dtype=np.int64)
            for u in bscope[i]: idx += Sb[:, pos[u]] * bstr[i][u]
            return idx
        def check_publish():
            nonlocal t_cert
            t0 = tnow(); lo, hi = cert.sets(); width = hi - lo
            for j in range(Kq):
                if j in pub or not np.isfinite(width[j]): continue
                if width[j] <= 2 * float(eps): pub[j] = (F(float(lo[j])), F(float(hi[j])), 'PAC_EB')
            unpub = np.array([j for j in range(Kq) if j not in pub], dtype=int); w = width[unpub] if unpub.size else np.zeros(0); wf = w[np.isfinite(w)]
            trace_rows.append(dict(t=round(tnow() - t_start, 2), draws=draws, zero_draws=zero_draws, X_mean=(sumX / max(1, draws)), published=len(pub), remaining=int(unpub.size), max_remaining_width=(float(wf.max()) if wf.size else 0.0), median_remaining_width=(float(np.median(wf)) if wf.size else 0.0), empty_sets=int((~np.isfinite(w)).sum())))
            t_cert += tnow() - t0; return width
        while tnow() < deadline and len(pub) < Kq:
            t0 = tnow(); Sb, logq, zero_row = mbp.sample_batch(rng, batch, pos); B = Sb.shape[0]
            logz = np.zeros(B); gv = []
            for i in range(len(blocks)):
                idx = flat_index(Sb, i); logz += bLM[i][idx]; gv.append(bMflat[i][idx])
            zero = ~np.isfinite(logz) | zero_row; logX = np.where(zero, -2000.0, (logz - logq - logU_capf) + float(E_tot)); mx = float(logX[~zero].max()) if (~zero).any() else -inf
            assert mx <= cap_tol, 'importance weight exceeds the mini-bucket cap beyond its proved error bound (certificate defect): log2 X = %r > %r' % (mx, cap_tol)
            X = np.where(zero, 0.0, np.minimum(1.0, np.exp2(logX))); maxlogX = max(maxlogX, mx)
            if (X > 0).any(): witness = True
            f = np.zeros((B, Kq))
            if len(sep_q): f[:, :len(sep_q)] = (Sb[:, sep_pos] == sep_val[None, :]).astype(float)
            col = len(sep_q)
            for i, Q, rhos in blockQ:
                if Q is None: continue
                idx = flat_index(Sb, i); g = gv[i]; Kb = Q.shape[1]
                with np.errstate(divide='ignore', invalid='ignore'): ratio = np.where(g[:, None] > 0, Q[idx] / np.where(g > 0, g, 1.0)[:, None], 0.0)
                f[:, col:col + Kb] = np.clip(ratio, 0.0, 1.0); col += Kb
            cert.update_batch(X, f); zcert.update_batch(X); draws += B; zero_draws += int(zero.sum()); sumX += float(X.sum()); t_loop += tnow() - t0
            if tnow() >= next_chk: check_publish(); next_chk = tnow() + check_s
        width = check_publish(); unpub = [j for j in range(Kq) if j not in pub]; wf = width[unpub]; wf = wf[np.isfinite(wf)]
        zi = zcert.interval(); per_draw = t_loop / max(1, draws); total = t_loop + t_cert
        out['mechanism'].update(draws=draws, zero_draws=zero_draws, X_mean=sumX / max(1, draws), log2_Zhat_over_Ucap_DIAGNOSTIC=(log2(sumX / draws) if sumX > 0 else None), max_log2_X_observed=maxlogX, ms_per_draw=1000 * per_draw, cert_evals=len(trace_rows), cert_s=t_cert,
                                published=len(pub), remaining=len(unpub), max_remaining_width=(float(wf.max()) if wf.size else 0.0), median_remaining_width=(float(np.median(wf)) if wf.size else 0.0),
                                Z_over_Ucap_EB_interval=zi, Z_EB_relative_width=((zi[1] - zi[0]) / zi[0] if zi[0] > 0 else None), lam_last_median=float(np.median(cert.lam())), schedule=schedule,
                                extrapolated_s_max_width=((total * (float(wf.max()) / (2 * float(eps))) ** 2) if wf.size else 0.0), extrapolated_s_median_width=((total * (float(np.median(wf)) / (2 * float(eps))) ** 2) if wf.size else 0.0))
        ph.update(stream=t_loop, certificate=t_cert); out['trace'] = trace_rows
        if witness:
            ans.update(pending)
            for j, q in enumerate(sq):
                if j in pub: lo_, hi_, g = pub[j]; publish(qmap[q], lo_, hi_, (lo_ + hi_) / 2, g)
        else: out['withheld_without_witness'] = len(pub) + len(pending)
        return finish_('COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL', witness=witness)
    except Deadline as e:
        out['deadline_phase'] = str(e); return finish_('DEADLINE')
    except AssertionError as e:
        out['error'] = str(e); return finish_('CERTIFICATE_DEFECT')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=20.0); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--table-cap', type=int, default=1 << 18); ap.add_argument('--enum-cap', type=int, default=1 << 16); ap.add_argument('--mb-cap', type=int, default=1 << 24); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000')
    ap.add_argument('--force-approx', action='store_true'); ap.add_argument('--batch', type=int, default=1024); ap.add_argument('--schedule', default='baseline', choices=['baseline', 'targeted'])
    a = ap.parse_args()
    out = solve(a.input, a.budget, seed=a.seed, table_cap=a.table_cap, enum_cap=a.enum_cap, eps=F(a.epsilon), delta=F(a.delta), mb_cap=a.mb_cap, force_approx=a.force_approx, batch=a.batch, schedule=a.schedule)
    out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), phases={k: round(v, 3) for k, v in out['phases_s'].items()},
                                   mech={k: (round(m[k], 4) if isinstance(m.get(k), float) else m.get(k)) for k in ('blocks', 'separator_vars', 'mb_cap', 'mb_logU', 'mb_max_range_sum_bits', 'eps_num_log2', 'rho_X', 'E_tot', 'delta_log_total', 'draws', 'ms_per_draw', 'X_mean', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'max_log2_X_observed', 'published', 'remaining', 'max_remaining_width', 'median_remaining_width', 'lam_last_median', 'schedule', 'extrapolated_s_max_width', 'extrapolated_s_median_width', 'Z_EB_relative_width', 'interior_queries_recovered', 'interior_queries_failed')}), default=str))


if __name__ == '__main__': main()
