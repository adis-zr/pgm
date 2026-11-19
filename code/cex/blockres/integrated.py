"""INTEGRATED block-contraction inference (round 3, 19 Nov 2026; overseer decision of the same date). One method, not four fixes:
  * exact integer block contraction (reused from blockres.py) -> SCALED BINARY64 tables with rigorous relative-error accounting (Lemma F in NOTE.md section 6);
  * mini-bucket proposal built from the SAME float tables (max mini-buckets = cap, sum mini-bucket = sampling law), sampled in the log domain; z(x) / q(x) <= U_cap;
  * ONE shared stream: every draw updates every query; the certificate is the DIRECT identity test  E_q[ X (f_j - m) ] = (Z / U_cap)(mu_j - m)  with X = W / U_cap in [0, 1],
    through a time-uniform predictable-plug-in EMPIRICAL-BERNSTEIN confidence sequence (Waudby-Smith & Ramdas 2020, Thm 2) per query at risk delta / K; the confidence set
    for mu_j is {m in [0, 1] : 0 in CS_t(m)}, solved from the quadratic in m; no separate normalizer lower bound; the positive-mass witness is preserved (X > 0 observed
    => z > 0 exactly, because every float carries a relative-error bound < 1);
  * interior queries recovered by replaying each block's elimination in the float representation (larger byte cap than the exact-integer path allowed);
  * stopping bounds evaluated in batches (vectorized over queries);
  * a proposal-cap ladder judged by construction time + measured time to certification.
Numerical bias of the float path (weights, responses, the realized sampling law vs the analysed law, truncation of probabilities below 2^-900) is bounded and added to
the certificate as an explicit widening eps_num (recorded). Every published interval contains mu_j with probability >= 1 - delta simultaneously over all queries.
"""
import sys, os, json, time, argparse, random, resource, math
from fractions import Fraction as F
from math import prod, inf, log2, frexp, ldexp
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
import blockres as BR
from blockres import tnow, Deadline, lg

VERSION = 'blockres-integrated-v1 (2026-11-19 round 3)'
U = 2.0 ** -53                       # unit roundoff of binary64
RANGE_BITS = 900                     # a nonzero float entry below 2^-RANGE_BITS of its table maximum => the float path is REFUSED (no subnormals, no silent zeros)
MIN_BITS = 64                        # exact int -> float conversion keeps at least this many significant bits of every nonzero entry, else REFUSED
PROB_TRUNC_LOG2 = -900               # conditional probabilities below 2^PROB_TRUNC_LOG2 (relative to the row maximum) are set to 0: missed mass <= U * n_vars * 2^-900
FLOAT_BYTE_CAP = 256 << 20
EPS_NUM_LOG2 = -30                   # explicit widening of every certificate for ALL float effects (derived in NOTE.md section 6; the actual bound is recorded per run)


class RangeRefused(Exception): pass


# ---------------------------------------------------------------- scaled binary64 tables with relative-error bounds
class FT:
    """arr ~ M * 2^e with max(M) in [1, 2) (or all zero); every entry: exact in [M (1 - rho), M (1 + rho)] * 2^e; rho is an upper bound (rounded up)"""
    __slots__ = ('scope', 'M', 'e', 'rho', 'interior', 'facs')
    def __init__(self, scope, M, e, rho, interior=(), facs=frozenset()): self.scope = tuple(scope); self.M = M; self.e = e; self.rho = rho; self.interior = list(interior); self.facs = facs


def _rescale(P, e, rho):
    """divide by the power of two below the max (exact), check the dynamic range, return FT pieces"""
    m = float(P.max()) if P.size else 0.0
    if m == 0.0: return P, 0, rho
    k = frexp(m)[1] - 1; P = P * ldexp(1.0, -k)                      # exact scaling
    nz = P[P > 0]
    if nz.size and float(nz.min()) < ldexp(1.0, -RANGE_BITS): raise RangeRefused('dynamic range of a float table exceeds 2^%d' % RANGE_BITS)
    return P, e + k, rho


def ft_from_int(fn, cards):
    """exact integer table -> FT; refuses if any nonzero entry would keep < MIN_BITS significant bits"""
    flat = np.asarray(fn.arr, dtype=object).reshape(-1).tolist(); nmax = max((int(v) for v in flat), default=0)
    if nmax == 0: return FT(fn.scope, np.zeros(np.asarray(fn.arr).shape, dtype=float), 0, 0.0, fn.interior, fn.facs)
    k = max(0, nmax.bit_length() - 1000)                                                              # shift so that every shifted entry is < 2^1000 (float(int) then rounds correctly)
    if k:
        for n in flat:                                                                                 # a dropped tail must be < 2^-MIN_BITS of the entry: n >> k keeps >= MIN_BITS bits
            if n and n.bit_length() - k < MIN_BITS: raise RangeRefused('exact entry with %d significant bits after the shift (< %d)' % (n.bit_length() - k, MIN_BITS))
    M = np.array([float(n >> k) for n in flat], dtype=float).reshape(np.asarray(fn.arr).shape)
    rho = U + (2.0 ** (-(MIN_BITS - 1)) if k else 0.0)                                                # truncation of the dropped bits (if any) + one rounding (rounded up)
    M, e, rho = _rescale(M, k, rho); return FT(fn.scope, M, e, rho, fn.interior, fn.facs)


def ft_product(fts, cards):
    union = tuple(sorted(set().union(*(set(f.scope) for f in fts)))); P = None; e = 0; r = 1.0
    for f in fts:
        a = f.M.reshape([cards[v] if v in f.scope else 1 for v in union]); P = a if P is None else P * a; e += f.e; r *= (1.0 + f.rho)
    r *= (1.0 + U) ** max(0, len(fts) - 1); return union, P, e, r - 1.0


def ft_eliminate(bucket, v, cards, agg='sum'):
    union, P, e, rho = ft_product(bucket, cards); ax = union.index(v); n = cards[v]
    if agg == 'sum': R = P.sum(axis=ax); rho = (1.0 + rho) * (1.0 + U) ** max(0, n - 1) - 1.0        # any summation order of nonnegative terms
    elif agg == 'max': R = P.max(axis=ax)
    else: R = P.min(axis=ax)
    scope = tuple(u for u in union if u != v); R = np.asarray(R, dtype=float).reshape([cards[u] for u in scope]) if scope else np.asarray(R, dtype=float).reshape(())
    R, e, rho = _rescale(R, e, rho * (1.0 + 2 ** -40) + 2 ** -60)                                    # rho itself rounded up
    return FT(scope, R, e, rho, [u for f in bucket for u in f.interior] + [v], frozenset().union(*(f.facs for f in bucket)))


def recover_query_table_float(block_ft, x, cards, trace_ft, trace_var, step_of, deadline, stats):
    """g_bx over block.scope + (x,) in float: replay the block's elimination from the cached prefix at x's step with x retained; None if a table exceeds FLOAT_BYTE_CAP"""
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
    P = np.moveaxis(P, union.index(x), -1); P, e, rho = _rescale(np.ascontiguousarray(P), e, rho); return FT(tuple(u for u in union if u != x) + (x,), P, e, rho)


# ---------------------------------------------------------------- mini-bucket proposal in float (same partition rule as blockres.MBProposal; max mini-buckets = cap)
class MBFloat:
    def __init__(self, blocks, cards, cap, deadline):
        self.cards = cards; live = [FT(b.scope, b.M, b.e, b.rho) for b in blocks]; steps = []; logU = 0.0; rhoU = 0.0; order = []
        vars_ = sorted({v for f in live for v in f.scope})
        while vars_:
            if tnow() >= deadline: raise Deadline('mb_float')
            best = None
            for v in vars_:
                nb = set().union(*(set(f.scope) for f in live if v in f.scope)) - {v}; size = prod(cards[u] for u in nb) if nb else 1
                if best is None or size < best[0]: best = (size, v)
            v = best[1]; order.append(v); vars_.remove(v); bucket = [f for f in live if v in f.scope]; live = [f for f in live if v not in f.scope]
            if not bucket: logU += log2(cards[v]); steps.append((v, None)); continue
            bucket.sort(key=lambda f: -len(f.scope)); groups = []
            for f in bucket:
                for g in groups:
                    u = g[0] | set(f.scope)
                    if prod(cards[x] for x in u) <= cap: g[0] = u; g[1].append(f); break
                else: groups.append([set(f.scope), [f]])
            for gi, (u, members) in enumerate(groups):
                R = ft_eliminate(members, v, cards, 'sum' if gi == 0 else 'max')
                if R.scope: live.append(R)
                else:
                    if float(R.M) == 0.0: logU = -inf
                    else: logU += log2(float(R.M)) + R.e
                    rhoU = (1 + rhoU) * (1 + R.rho) - 1
            steps.append((v, groups[0][1]))
        self.steps = steps; self.order = order; self.logU = logU; self.rhoU = rhoU
        self.logU_cap = (logU + log2(1.0 + rhoU) + 2 ** -40) if logU > -inf else -inf            # U_cap >= U_exact: an upper bound on every weight
        self.max_table = max((f.M.size for _, q1 in steps if q1 for f in q1), default=0)

    def sample(self, rng, pos):
        """returns (s tuple in separator order, log2 q(s)); log-domain conditionals; probabilities below 2^PROB_TRUNC_LOG2 of the row max are truncated to 0"""
        x = {}; logq = 0.0; cards = self.cards; trunc = False
        for v, q1 in reversed(self.steps):
            n = cards[v]
            if q1 is None: x[v] = rng.randrange(n); logq -= log2(n); continue
            L = np.zeros(n)
            for a in range(n):
                x[v] = a; la = 0.0
                for f in q1:
                    m = float(f.M[tuple(x[u] for u in f.scope)])
                    if m == 0.0: la = -inf; break
                    la += log2(m) + f.e
                L[a] = la
            Lmax = L.max()
            if Lmax == -inf: x[v] = rng.randrange(n); logq -= log2(n); continue             # every completion of this row has z = 0: the weight will be 0
            p = np.exp2(L - Lmax); small = p < ldexp(1.0, PROB_TRUNC_LOG2);
            if small.any(): p[small] = 0.0; trunc = True
            tot = float(p.sum()); c = np.cumsum(p); r = rng.random() * tot; a = int(np.searchsorted(c, r, side='right')); a = min(a, n - 1)
            while p[a] == 0.0: a -= 1
            x[v] = a; logq += log2(float(p[a])) - log2(tot)
        return tuple(x[v] for v in pos), logq, trunc


# ---------------------------------------------------------------- the direct empirical-Bernstein marginal certificate (one stream, all queries)
class Certificate:
    """per query j: time-uniform PrPl-EB confidence sequence (Waudby-Smith & Ramdas 2020, Theorem 2) for the mean of Y_t(m) = X_t (f_jt - m) in [-1, 1]:
         0 in CS_t(m)  <=>  |A_j - m B_j| <= 2 log(2/alpha) + 2 sum_i psi_E(lambda_i) (a_i - m b_i)^2 + Lambda_j eps_num
       with A = sum lambda X f, B = sum lambda X, a_i = X_i f_i - SA_{i-1}/i, b_i = X_i - SB_{i-1}/i (plug-in running means), psi_E(l) = (-ln(1-l) - l)/4,
       lambda_i predictable in [0, 1/2] from the running variance at the running estimate. The confidence set for mu_j is the convex hull of {m in [0,1]: inequality}."""
    def __init__(self, K, alpha, eps_num):
        self.K = K; self.alpha = alpha; self.log_term = 2.0 * math.log(2.0 / alpha); self.eps_num = eps_num; self.t = 0
        z = lambda: np.zeros(K); self.SA = z(); self.SB = 0.0; self.SXX = 0.0; self.SXXf = z(); self.SXXff = z(); self.A = z(); self.B = z(); self.Lam = z(); self.P = z(); self.Q = z(); self.R = z()
        self.lam_max = 0.9                     # any predictable lambda in [0,1) is valid; psi_E diverges at 1
    def lam(self):
        """predictable lambda_t per query from the running variance of Y at the running estimate m_hat (any predictable lambda in [0,1) is valid)"""
        t = self.t
        if t < 2: return np.full(self.K, 0.25)
        mhat = np.where(self.SB > 0, np.clip(self.SA / max(self.SB, 1e-300), 0.0, 1.0), 0.5)
        mean = (self.SA - mhat * self.SB) / t; var = (self.SXXff - 2 * mhat * self.SXXf + mhat * mhat * self.SXX) / t - mean * mean
        var = np.maximum(var, 1e-12)
        return np.minimum(self.lam_max, np.sqrt(self.log_term / (var * t * math.log(t + 1.0))))
    def update(self, X, f):
        """X scalar in [0,1], f vector in [0,1]"""
        t1 = self.t + 1; lam = self.lam(); psi = (-np.log1p(-lam) - lam) / 4.0
        a = X * f - self.SA / t1; b = X - self.SB / t1
        self.A += lam * X * f; self.B += lam * X; self.Lam += lam; self.P += psi * a * a; self.Q += psi * a * b; self.R += psi * b * b
        self.SA += X * f; self.SB += X; self.SXX += X * X; self.SXXf += X * X * f; self.SXXff += X * X * f * f; self.t = t1
    def sets(self):
        """confidence set per query = convex hull of {m in [0,1] : g+(m) >= 0 and g-(m) >= 0}, g+-(m) = 2R m^2 + (+-B - 4Q) m + (c + 2P -+ A); each {g >= 0} is [0,1] minus
        an open root interval (R >= 0); the hull is computed from the roots with outward rounding. (nan, nan) marks an empty set (impossible at the truth; recorded)."""
        c0 = self.log_term + self.Lam * self.eps_num; out_lo = np.zeros(self.K); out_hi = np.ones(self.K); wid = 1.0 + 2 ** -30
        for j in range(self.K):
            A, B, P, Q, R = self.A[j], self.B[j], self.P[j] * wid, self.Q[j], self.R[j] * wid; cj = c0[j] * wid
            allowed = [(0.0, 1.0)]                                                   # list of closed intervals, intersected progressively
            for sgn in (1.0, -1.0):
                aq = 2 * R; bq = sgn * B - 4 * Q; cq = cj + 2 * P - sgn * A           # g(m) = aq m^2 + bq m + cq >= 0
                if aq > 0:
                    disc = bq * bq - 4 * aq * cq
                    if disc <= 0: continue                                          # g >= 0 everywhere
                    r = math.sqrt(disc) * (1 + 2 ** -40); r1 = (-bq - r) / (2 * aq); r2 = (-bq + r) / (2 * aq)       # excluded OPEN interval (r1, r2), widened inward (kept set grows)
                    excl = (r1, r2)
                elif bq != 0:
                    root = -cq / bq; excl = (root, inf) if bq < 0 else (-inf, root)
                else:
                    if cq < 0: allowed = []; break
                    continue
                new = []
                for lo, hi in allowed:
                    if excl[1] <= lo or excl[0] >= hi: new.append((lo, hi)); continue
                    if excl[0] > lo: new.append((lo, min(hi, excl[0])))
                    if excl[1] < hi: new.append((max(lo, excl[1]), hi))
                allowed = new
            if not allowed: out_lo[j] = np.nan; out_hi[j] = np.nan; continue
            out_lo[j] = max(0.0, min(lo for lo, _ in allowed) - 2 ** -45); out_hi[j] = min(1.0, max(hi for _, hi in allowed) + 2 ** -45)
        return out_lo, out_hi



class ZCertificate:
    """PrPl-EB confidence sequence (same theorem) for E[X] = Z / U_cap directly: the WMB-IS-style finite-sample normalizer bound from the SAME draws (baseline comparison; not used for publication)"""
    def __init__(self, alpha): self.log_term = math.log(2.0 / alpha); self.t = 0; self.S = 0.0; self.S2 = 0.0; self.A = 0.0; self.Lam = 0.0; self.V = 0.0
    def update(self, X):
        t1 = self.t + 1; var = max(self.S2 / max(1, self.t) - (self.S / max(1, self.t)) ** 2, 1e-12) if self.t >= 2 else 0.25
        lam = min(0.9, math.sqrt(2 * self.log_term / (var * t1 * math.log(t1 + 1.0)))); psi = (-math.log1p(-lam) - lam) / 4.0; mu_hat = (0.5 + self.S) / t1
        self.A += lam * X; self.Lam += lam; self.V += psi * 4.0 * (X - mu_hat) ** 2; self.S += X; self.S2 += X * X; self.t = t1
    def interval(self):
        if self.Lam <= 0: return (0.0, 1.0)
        c = self.A / self.Lam; r = (self.log_term + self.V) / self.Lam * (1 + 2 ** -30); return (max(0.0, c - r), min(1.0, c + r))

# ---------------------------------------------------------------- the integrated solve
def solve(model_path, budget, seed=1, table_cap=1 << 18, enum_cap=1 << 16, eps=F(1, 200), delta=F(1, 10 ** 6), mb_cap=4096, construct_share=0.5, batch_s=0.5, force_approx=False):
    t_start = tnow(); deadline = t_start + budget; ph = {}; rng = random.Random(seed); stats = dict(elim_work=0, eliminations=0, query_work=0)
    out = dict(version=VERSION, seed=seed, budget_s=budget, table_cap=table_cap, enum_cap=enum_cap, mb_cap=mb_cap, epsilon=str(eps), delta=str(delta), phases_s=ph, mechanism={}, outcome=None, answers=None)
    t0 = tnow(); model, binding = BR.core.read_uai(model_path); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); out['binding'] = binding; ph['read'] = tnow() - t0
    queries = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K = len(queries); qix = {q: j for j, q in enumerate(queries)}; out['K'] = K
    ans = {}; pending = {}; failed = []
    def publish(j, lo, hi, point, g): ans[j] = dict(lo=lo, hi=hi, point=point, guarantee=g)
    def finish_(oc, witness=None):
        out['outcome'] = oc
        if witness: ans.update(pending)
        out['positive_mass_witness'] = witness; return BR.finish(out, t_start, queries, ans, failed)
    try:
        # ---- exact integer construction (blockres)
        t0 = tnow(); fns, const, scale, mult, factorless = BR.integerize(model); ph['integerize'] = tnow() - t0
        if const == 0: return finish_('ZERO_EVIDENCE')
        for x in factorless:
            for v in range(cards[x]): pending[qix[(x, v)]] = dict(lo=F(1, cards[x]), hi=F(1, cards[x]), point=F(1, cards[x]), guarantee='EXACT')
        cdead = min(deadline, t_start + construct_share * budget); t0 = tnow(); trace = []; order = []
        live = BR.contract(fns, cards, table_cap, cdead, stats, trace, order); ph['contract'] = tnow() - t0; step_of = {v: i for i, (v, _) in enumerate(trace)}
        const_fns = [f for f in live if not f.scope]; live = [f for f in live if f.scope]
        for f in const_fns: const *= int(f.arr)
        if const == 0: return finish_('ZERO_EVIDENCE')
        S = sorted({v for f in live for v in f.scope})
        out['mechanism'].update(blocks=len(live), separator_vars=len(S), eliminated_vars=len(order), elim_work=stats['elim_work'], const_blocks=len(const_fns), factorless=len(factorless), N_S_log2=float(sum(log2(cards[v]) for v in S)))
        for b in const_fns:                                               # constant blocks: exact ratios of exact replays (cheap; int path)
            gb = int(b.arr)
            if gb == 0: continue
            bl = BR.Block(0, b, cards)
            for x in b.interior:
                r = BR.recover_query_table(bl, x, cards, table_cap * cards[x], trace, step_of, cdead, stats)
                if r is None: failed.append(x); continue
                for v in range(cards[x]): val = F(int(r[v]), gb); pending[qix[(x, v)]] = dict(lo=val, hi=val, point=val, guarantee='EXACT')
        if not live: return finish_('EXACT' if len(pending) == K else 'PARTIAL_EXACT', witness=True)
        # ---- exact separator enumeration when affordable (identical to blockres)
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
                k = id(f)
                if k not in cache: cache[k] = ft_from_int(f, cards)
                return cache[k]
            blocks = [conv(f) for f in live]; trace_var = {}; trace_ft = []
            for st, (v, snap) in enumerate(trace): trace_var[st] = v; trace_ft.append([conv(f) for f in snap])
        except RangeRefused as e:
            out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['float_convert'] = tnow() - t0
        # ---- interior query tables (float replay; cheapest first)
        t0 = tnow(); qtabs = {i: [] for i in range(len(blocks))}; recovered = 0; skipped = []
        todo = sorted(((len([u for u in b.interior if step_of[u] > step_of[x]]), i, x) for i, b in enumerate(blocks) for x in b.interior))
        for _, i, x in todo:
            if tnow() >= cdead: skipped.append(x); continue
            try: r = recover_query_table_float(blocks[i], x, cards, trace_ft, trace_var, step_of, cdead, stats)
            except Deadline: skipped.append(x); continue
            except RangeRefused as e: failed.append(x); continue
            if r is None: failed.append(x); continue
            qtabs[i].append((x, r)); recovered += 1
        failed += skipped; ph['query_tables'] = tnow() - t0
        out['mechanism'].update(interior_queries_recovered=recovered, interior_queries_failed=len(failed) - len(skipped), interior_queries_skipped_window=len(skipped), query_work=stats['query_work'])
        # per block: stacked query columns (x, v) -> (M_Q, e_Q, rho_Q) aligned with the block table
        pos = {v: i for i, v in enumerate(S)}; qcols = []; qblock = []; qM = []; qe = []; qrho = []
        for i, b in enumerate(blocks):
            for x, r in qtabs[i]:
                for v in range(cards[x]): qcols.append((x, v)); qblock.append(i); qM.append(r.M[..., v]); qe.append(r.e); qrho.append(r.rho)
        sep_q = [(x, v) for (x, v) in queries if x in pos]; qidx_sep = {(x, v): None for (x, v) in sep_q}
        sq = sep_q + qcols; Kq = len(sq); qmap = {q: qix[q] for q in sq}
        # ---- mini-bucket proposal (float)
        t0 = tnow()
        try: mbp = MBFloat(blocks, cards, mb_cap, deadline)
        except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['mb_construct'] = tnow() - t0
        out['mechanism'].update(mb_cap=mb_cap, mb_logU=mbp.logU, mb_logU_cap=mbp.logU_cap, mb_rhoU=mbp.rhoU, mb_max_table=mbp.max_table, Kq=Kq, sep_queries=len(sep_q), interior_query_cols=len(qcols))
        if mbp.logU == -inf: return finish_('ZERO_EVIDENCE')                  # Z <= U = 0 exactly (float zeros are exact zeros: no truncation inside tables)
        # ---- numerical widening: weights (blocks + proposal), responses, law mismatch, truncation
        rho_z = prod(1.0 + b.rho for b in blocks) * (1.0 + U) ** len(blocks) - 1.0
        rho_q = len(S) * (2.0 ** -40)                                        # log-domain conditionals: |log2 error| per step <= ~2^-40 (1000 u on |L| <= 1000) -> relative
        rho_W = (1.0 + rho_z) * (1.0 + rho_q) * (1.0 + mbp.rhoU) * (1.0 + 2 ** -40) - 1.0
        rho_f = max([2.0 * r for r in qrho] + [0.0]) + max([b.rho for b in blocks]) + 4 * U
        eps_num = rho_W + rho_f + len(S) * 2.0 ** -50 + len(S) * 2.0 ** PROB_TRUNC_LOG2 + 2.0 ** -40
        out['mechanism'].update(rho_z=rho_z, rho_W=rho_W, rho_f=rho_f, eps_num=eps_num, eps_num_log2=log2(eps_num))
        logU_cap = mbp.logU_cap + log2(1.0 + rho_W)                             # X = W_float / U_cap <= 1 for every draw (asserted)
        alpha = float(delta) / Kq; cert = Certificate(Kq, alpha, eps_num); zcert = ZCertificate(float(delta))
        # ---- the shared stream
        witness = False; draws = 0; zero_draws = 0; trunc_draws = 0; pub = {}; trace_rows = []; t_draw = 0.0; t_cert = 0.0; next_chk = tnow() + batch_s; logz_sum_max = -inf; sumX = 0.0
        bM = [b.M for b in blocks]; be = [b.e for b in blocks]; bidx = [tuple(pos[v] for v in b.scope) for b in blocks]
        qM_arr = qM; qb = qblock; qe_arr = [int(x) for x in qe]; nq = len(qcols)
        sep_var_pos = [pos[x] for (x, v) in sep_q]; sep_val = np.array([v for (x, v) in sep_q], dtype=int)
        while tnow() < deadline and len(pub) < Kq:
            t0 = tnow(); s, logq, trunc = mbp.sample(rng, S)
            # z(s) in the log domain; exact zero if any block entry is zero
            logz = 0.0; gval = []
            for i in range(len(blocks)):
                m = float(bM[i][tuple(s[p] for p in bidx[i])]); gval.append(m)
                if m == 0.0: logz = -inf; break
                logz += log2(m) + be[i]
            draws += 1; trunc_draws += trunc
            if logz == -inf: X = 0.0; f = np.zeros(Kq); zero_draws += 1
            else:
                witness = True; logX = logz - logq - logU_cap
                assert logX <= 2 ** -30, 'importance weight exceeds the mini-bucket cap (certificate defect): log2 X = %r' % logX
                X = min(1.0, 2.0 ** logX); sumX += X
                f = np.zeros(Kq)
                if sep_q: f[:len(sep_q)] = (np.array([s[p] for p in sep_var_pos]) == sep_val).astype(float)
                for c in range(nq):
                    i = qb[c]; idx = tuple(s[p] for p in bidx[i]); g = gval[i]
                    f[len(sep_q) + c] = min(1.0, float(qM_arr[c][idx]) * ldexp(1.0, qe_arr[c] - be[i]) / g) if g > 0 else 0.0
            cert.update(X, f); zcert.update(X); t_draw += tnow() - t0
            if tnow() >= next_chk:
                t0 = tnow(); lo, hi = cert.sets(); width = hi - lo
                for j in range(Kq):
                    if j in pub or not np.isfinite(width[j]): continue
                    if width[j] <= 2 * float(eps): pub[j] = (F(float(lo[j])), F(float(hi[j])), 'PAC_EB')
                w = width[np.isfinite(width)]
                trace_rows.append(dict(t=round(tnow() - t_start, 2), draws=draws, zero_draws=zero_draws, X_mean=(sumX / max(1, draws)), median_width=(float(np.median(w)) if w.size else None), p90_width=(float(np.percentile(w, 90)) if w.size else None), min_width=(float(w.min()) if w.size else None), published=len(pub)))
                t_cert += tnow() - t0; next_chk = tnow() + max(batch_s, 3 * (tnow() - t0))
        t0 = tnow(); lo, hi = cert.sets(); width = hi - lo
        for j in range(Kq):
            if j in pub or not np.isfinite(width[j]): continue
            if width[j] <= 2 * float(eps): pub[j] = (F(float(lo[j])), F(float(hi[j])), 'PAC_EB')
        t_cert += tnow() - t0; w = width[np.isfinite(width)]
        # extrapolation (diagnostic): EB width ~ 1/sqrt(t) -> draws needed for the median / p90 query, at the measured per-draw cost
        per_draw = t_draw / max(1, draws); med = float(np.median(w)) if w.size else None; p90 = float(np.percentile(w, 90)) if w.size else None
        # regime-aware extrapolation from the EB formula: needed radius on E[Y] is r = (Z/U_cap) eps (Z/U_cap estimated by X_mean, DIAGNOSTIC); draws needed =
        # max( 2 ln(2/alpha) / (lambda_max r)  [log-dominated, 1/t],  2 ln(2/alpha) sigma^2 / r^2  [variance-dominated, 1/sqrt t] ) with sigma^2 the measured running variance of Y at m_hat
        t_ = cert.t; mhat = np.where(cert.SB > 0, np.clip(cert.SA / max(cert.SB, 1e-300), 0, 1), 0.5); meanY = (cert.SA - mhat * cert.SB) / t_
        varY = np.maximum((cert.SXXff - 2 * mhat * cert.SXXf + mhat * mhat * cert.SXX) / t_ - meanY * meanY, 0.0); sig2_med = float(np.median(varY)) if varY.size else None; sig2_p90 = float(np.percentile(varY, 90)) if varY.size else None
        r_needed = (sumX / max(1, draws)) * float(eps); L = math.log(2.0 / alpha)
        def need(sig2): return (max(2 * L / (cert.lam_max * r_needed), 2 * L * sig2 / (r_needed * r_needed)) if (r_needed > 0 and sig2 is not None) else None)
        need_med = need(sig2_med); need_p90 = need(sig2_p90)
        regime = ('no positive draw' if r_needed <= 0 else ('log-dominated' if (sig2_med is not None and 2 * L / (cert.lam_max * r_needed) >= 2 * L * sig2_med / (r_needed ** 2)) else 'variance-dominated'))
        out['mechanism'].update(X2_mean=cert.SXX / max(1, draws), sigma2_Y_median=sig2_med, sigma2_Y_p90=sig2_p90, r_needed=r_needed, log_term=2 * L, regime=regime)
        out['mechanism'].update(draws=draws, zero_draws=zero_draws, truncated_prob_draws=trunc_draws, X_mean=sumX / max(1, draws), log2_Zhat_over_Ucap_DIAGNOSTIC=(log2(sumX / draws) if sumX > 0 else None), ms_per_draw=1000 * per_draw, cert_evals=len(trace_rows) + 1, cert_s=t_cert,
                                median_width=med, p90_width=p90, min_width=(float(w.min()) if w.size else None), published=len(pub), published_by=BR._count([g for _, _, g in pub.values()]),
                                extrapolated_draws_median_query=need_med, extrapolated_s_median_query=(need_med * per_draw if need_med else None), extrapolated_draws_p90_query=need_p90, extrapolated_s_p90_query=(need_p90 * per_draw if need_p90 else None),
                                X_underflow_note='X below 2^-1074 is stored as 0.0: bias <= 2^-1074 per draw, inside eps_num')
        zi = zcert.interval(); out['mechanism'].update(Z_over_Ucap_EB_interval=zi, Z_EB_log2_width=(log2(zi[1] - zi[0]) if zi[1] > zi[0] else None), Z_EB_relative_width=((zi[1] - zi[0]) / zi[0] if zi[0] > 0 else None), Z_EB_log2_lower=(log2(zi[0]) + logU_cap if zi[0] > 0 else None), Z_EB_log2_upper=(log2(zi[1]) + logU_cap if zi[1] > 0 else None))
        ph.update(stream=t_draw, certificate=t_cert); out['trace'] = trace_rows
        if witness:
            ans.update(pending)
            for j, q in enumerate(sq):
                if j in pub: lo_, hi_, g = pub[j]; publish(qmap[q], lo_, hi_, (lo_ + hi_) / 2, g)
        else: out['withheld_without_witness'] = len(pub) + len(pending)
        out['positive_mass_witness'] = witness
        return finish_('COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL', witness=witness)
    except Deadline as e:
        out['deadline_phase'] = str(e); return finish_('DEADLINE')
    except AssertionError as e:
        out['error'] = str(e); return finish_('CERTIFICATE_DEFECT')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=20.0); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--table-cap', type=int, default=1 << 18); ap.add_argument('--enum-cap', type=int, default=1 << 16); ap.add_argument('--mb-cap', type=int, default=4096); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--force-approx', action='store_true')
    a = ap.parse_args()
    out = solve(a.input, a.budget, seed=a.seed, table_cap=a.table_cap, enum_cap=a.enum_cap, eps=F(a.epsilon), delta=F(a.delta), mb_cap=a.mb_cap, force_approx=a.force_approx)
    out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), phases={k: round(v, 3) for k, v in out['phases_s'].items()},
                                   mech={k: (round(m[k], 3) if isinstance(m.get(k), float) else m.get(k)) for k in ('blocks', 'separator_vars', 'N_S_log2', 'mb_cap', 'mb_logU', 'mb_max_table', 'interior_queries_recovered', 'interior_queries_failed', 'eps_num_log2', 'draws', 'zero_draws', 'ms_per_draw', 'X_mean', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'median_width', 'p90_width', 'min_width', 'published', 'X2_mean', 'sigma2_Y_median', 'r_needed', 'regime', 'extrapolated_draws_median_query', 'extrapolated_s_median_query', 'extrapolated_s_p90_query', 'Z_EB_relative_width')}), default=str))


if __name__ == '__main__': main()
