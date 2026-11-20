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
T_PROCESS_START = time.monotonic()
from fractions import Fraction as F
from math import prod, inf, log2, frexp, ldexp, nextafter
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
import blockres as BR
from blockres import tnow, Deadline, lg

VERSION = 'blockres-integrated-v2.3 (2026-11-19 round 8: root derivatives = products of the other scalar roots (disconnected components); a requested executor cross-check must succeed and cover every published separator coordinate; dyadic 2^-52 outward compaction of deterministic enclosures; coherent guarantee labels; v2.2 round 7: split census; EXACT ROUTE for unsplit constructions = shared backward differential + per-block retained VE, deterministic intervals, existing certified executor as independent cross-check of the separator marginals; v2.1 round 5: power-of-two exponents cancelled exactly before any float log; widening from the actual tracked log magnitudes; v2 round 4: exact-rational error bounds, product underflow pre-check, conservative inversion, batch loop, lambda schedules)'
UF = F(1, 1 << 53); U = 2.0 ** -53
RANGE_BUDGET = 1000                  # bits: sum of operand ranges allowed in ONE product (its smallest nonzero entry stays >= 2^-1000 of its max: normal, nonzero)
RANGE_BITS = 900                     # a table whose smallest nonzero entry is below 2^-900 of its maximum is refused outright
MIN_BITS = 64
PROB_TRUNC_LOG2 = -900
FLOAT_BYTE_CAP = 256 << 20


class RangeRefused(Exception): pass


def rup(x, bits=200):
    """round a nonnegative Fraction UP onto the 2^-bits grid: keeps every tracked bound an upper bound while bounding its size (the WMB power-sum bounds square per level otherwise)"""
    x = F(x); q = 1 << bits; return F(-((-x * q).numerator // (-x * q).denominator), q) if x > 0 else F(0)


def up(x): return nextafter(x, inf)
def dn(x): return nextafter(x, -inf)
def fup(fr): return up(float(fr))


# ---------------------------------------------------------------- scaled binary64 tables: entry in [M (1 - rho), M (1 + rho)] 2^e; rho EXACT; R = dynamic range in bits
class FT:
    __slots__ = ('scope', 'M', 'e', 'rho', 'R', 'interior', 'facs', 'tag')
    def __init__(self, scope, M, e, rho, interior=(), facs=frozenset()):
        self.scope = tuple(scope); self.M = M; self.e = e; self.rho = rup(rho); self.interior = list(interior); self.facs = facs; self.tag = None
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
        self.cards = cards; live = [FT(b.scope, b.M, b.e, b.rho) for b in blocks]
        for i, f in enumerate(live): f.tag = 'blk:%d' % i
        self.inputs = list(live); steps = []; logU_f = 0.0; E_U = 0; n_scalar = 0; rhoU = F(0); order = []; vars_ = sorted({v for f in live for v in f.scope}); self.max_range_sum = 0; self.group_record = []
        self.splits = 0; self.split_steps = []; self.fwd = []; self.scalars = []          # fwd: (v, bucket, message) for every step (meaningful as an exact elimination only when splits == 0)
        while vars_:
            if tnow() >= deadline: raise Deadline('mb_float')
            best = None
            for v in vars_:
                nb = set().union(*(set(f.scope) for f in live if v in f.scope)) - {v}; size = prod(cards[u] for u in nb) if nb else 1
                if best is None or size < best[0]: best = (size, v)
            v = best[1]; order.append(v); vars_.remove(v); bucket = [f for f in live if v in f.scope]; live = [f for f in live if v not in f.scope]
            if not bucket: logU_f += log2(cards[v]); n_scalar += 1; steps.append((v, None)); self.scalars.append(FT((), np.array(float(cards[v])), 0, F(0))); self.group_record.append([]); continue
            bucket.sort(key=lambda f: -len(f.scope)); groups = []
            for f in bucket:
                for g in groups:
                    u = g[0] | set(f.scope)
                    if prod(cards[x] for x in u) <= cap: g[0] = u; g[1].append(f); break
                else: groups.append([set(f.scope), [f]])
            if len(groups) > 1: self.splits += len(groups) - 1; self.split_steps.append((v, [len(g[1]) for g in groups]))
            self.group_record.append([[f_sig(f) for f in g[1]] for g in groups])
            for gi, (u, members) in enumerate(groups):
                self.max_range_sum = max(self.max_range_sum, sum(f.R for f in members)); R = ft_eliminate(members, v, cards, 'sum' if gi == 0 else 'max'); R.tag = 'msg:%d:%d' % (len(steps), gi)
                if gi == 0: self.fwd.append((v, list(members), R))
                if R.scope: live.append(R)
                else:
                    if float(R.M) == 0.0: logU_f = -inf
                    else: logU_f += log2(float(R.M)); E_U += R.e; n_scalar += 1          # float part in [0, 1) per scalar; the exponent stays an exact integer
                    rhoU = (1 + rhoU) * (1 + R.rho) - 1
                    self.scalars.append(R)
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



# ---------------------------------------------------------------- WEIGHTED mini-bucket proposal (Liu / Fisher / Ihler 2015; Lou / Dechter / Ihler 2019), round 8
W_MIN = 0.05                        # bounded positive weights: every power 1 / w is <= 20 (a controlled numerical domain); the (1, 0, ...) limit is the old max construction (separate arm)
WMB_GRID = [(0.5, 0.5), (0.3, 0.7), (0.7, 0.3), (0.15, 0.85), (0.85, 0.15)]          # the FIXED weight-optimization policy for split buckets: 2 groups -> this grid; m groups -> equal weights then one coordinate pass over the grid pairs


def _powsum_log(L, w):
    """row-wise: log2 ( sum_x 2^(L_x / w) )^w = Lmax + w log2 sum_x 2^((L_x - Lmax) / w) for L (..., n) with -inf allowed; returns (log2 M, log2 p over x) where log2 p_x = (L_x - Lmax)/w - log2 sum"""
    Lmax = L.max(axis=-1, keepdims=True); dead = ~np.isfinite(Lmax)
    Lm = np.where(dead, 0.0, Lmax); A = (L - Lm) / w; P = np.exp2(np.where(np.isfinite(A), A, -inf)); S = P.sum(axis=-1, keepdims=True)
    logS = np.log2(np.where(S > 0, S, 1.0)); logM = Lm + w * logS; logM = np.where(dead, -inf, logM)
    logp = np.where(np.isfinite(A), A - logS, -inf); return logM[..., 0], logp, dead[..., 0]


class WMBFloat:
    """weighted mini-bucket elimination over the separator model: per bucket, mini-buckets r with weights w_r (sum 1); messages M_r = (sum_x F_r^(1/w_r))^(w_r) stored as FT (mantissa, exponent,
    exact rho bound from the log-domain error analysis); proposal q_i(x | later) = sum_r w_r p_r(x | y_r) with p_r = F_r^(1/w_r) / sum_a F_a^(1/w_r) (the FULL mixture row is normalized and sampled by one CDF).
    Bound: Hoelder gives sum_x prod_r F_r <= prod_r M_r; weighted AM-GM gives prod_r F_r / M_r = prod_r p_r^(w_r) <= q_i; telescoping over steps: z / q <= U = product of the scalar messages.
    The partition (groups) and the elimination order are TAKEN FROM a reference MBFloat (held fixed for the matched comparison)."""
    def __init__(self, ref, blocks, cards, deadline, opt_s=3.0):
        self.cards = cards; self.ref = ref; t0 = tnow(); self.groups_per_step = []; self.weights = []; self.steps = []; self.scalars = []; self.rho_steps = []; self.max_q = 0
        # replay the reference partition: rebuild buckets from the reference's recorded group structure (same order, same member assignment by scope signature)
        ins = [FT(b.scope, b.M, b.e, b.rho) for b in blocks]
        for i, f in enumerate(ins): f.tag = 'blk:%d' % i                                   # the same tags as the reference pass, so the recorded partition replays exactly
        live = {id(f): f for f in ins}; self.inputs = ins
        order = ref.order; self.order = order; ref_groups = ref.group_record            # list per step: list of groups, each a list of member scope-signatures (scope tuple, source tag)
        for step_i, (v, groups_sig) in enumerate(zip(order, ref_groups)):
            if tnow() >= deadline: raise Deadline('wmb')
            bucket = [f for f in live.values() if v in f.scope]
            for f in bucket: live.pop(id(f))
            if not bucket: self.steps.append((v, None)); self.scalars.append(FT((), np.array(float(cards[v])), 0, F(0))); continue
            # assign members to the reference groups by scope signature (tags: 'blk:i' or 'msg:step:r')
            by_sig = {}
            for f in bucket: by_sig.setdefault(f_sig(f), []).append(f)
            groups = []
            for gs in groups_sig:
                g = []
                for sg in gs:
                    if not by_sig.get(sg): raise RangeRefused('wmb: partition replay mismatch at step %d' % step_i)
                    g.append(by_sig[sg].pop())
                groups.append(g)
            if any(by_sig.values()): raise RangeRefused('wmb: unassigned members at step %d' % step_i)
            m = len(groups); w = [1.0 / m] * m
            # per-group log tables of the product (log domain; exponents cancel inside a group's power sum only up to the group's exponent sum, kept exactly)
            glog = []; gE = []; grho = []; gunion = []
            for g in groups:
                union, P, e, rho = ft_product_log(g, cards); glog.append(P); gE.append(e); grho.append(rho); gunion.append(union)
            # weight optimization (fixed policy): minimize the bucket's total log2 bound sum_r log2 M_r (summed over y) over the grid, bounded by opt_s
            if m > 1 and tnow() - t0 < opt_s:
                best = None
                cands = [tuple(w)] + ([wg for wg in WMB_GRID] if m == 2 else [])
                for wc in cands:
                    tot = 0.0
                    for r in range(m):
                        ax = gunion[r].index(v); Lr = np.moveaxis(glog[r], ax, -1); logM, _, dead = _powsum_log(Lr, wc[r]); tot += float(np.where(np.isfinite(logM), logM, 0.0).sum())
                    if best is None or tot < best[0]: best = (tot, wc)
                w = list(best[1])
            self.weights.append(w); self.groups_per_step.append(groups)
            # messages
            step_tabs = []
            for r, g in enumerate(groups):
                ax = gunion[r].index(v); Lr = np.moveaxis(glog[r], ax, -1); logM, _, dead = _powsum_log(Lr, w[r]); nsc = tuple(u for u in gunion[r] if u != v)
                # rho of M_r from the log-domain error (NOTE section 10): abs log2 error d_M = d_L (1 + 1/w) + u (|L|/w + 3) + 1.45 (4u + (n-1)u) w + u(log2 n + 1) w ; relative 1.45 d_M (1 + d_M)
                n = cards[v]; Rsum = sum(f.R for f in g); d_L = F(grho[r]) * F(145, 100) + UF * (len(g) + 1) * (Rsum + len(g))
                # log2 M = Lmax + w log2 sum_x 2^((L_x - Lmax) / w): the log-sum-exp is 1-Lipschitz in every argument, so an absolute input error d_L / w becomes <= d_L / w in the log-sum and
                # <= d_L after the multiplication by w (NO amplification across levels); the float operations add: (L - Lmax) and / w on magnitudes <= Rsum / w, exp2 (4u rel), the sum ((n - 1) u rel),
                # log2 (u (|log S| + 1)), the product by w, and the final addition of Lmax
                wr = F(w[r]); mag = F(Rsum) / wr + int(n).bit_length() + 2; L2 = F(145, 100)
                d_M = d_L + UF * (Rsum + 2) + UF * mag + wr * (L2 * (4 * UF + (n - 1) * UF) + UF * (mag + 1)) + UF * (mag + 2) + UF * (Rsum + mag + 2)
                rhoM = rup(F(145, 100) * d_M * (1 + d_M)); self.rho_steps.append(rhoM)
                Mfl = np.where(np.isfinite(logM), np.exp2(logM - np.floor(np.where(np.isfinite(logM), logM, 0.0))), 0.0); Efl = np.where(np.isfinite(logM), np.floor(np.where(np.isfinite(logM), logM, 0.0)), 0.0)
                # store as FT with a COMMON exponent per table: shift mantissas by (E - Emax) exactly (powers of two), refuse if the range would leave the normal domain
                if np.isfinite(logM).any():
                    Emax = int(Efl[np.isfinite(logM)].max()); sh = np.where(np.isfinite(logM), Efl - Emax, 0.0)
                    if sh.min() < -900: raise RangeRefused('wmb: message dynamic range exceeds 2^900')
                    Mtab = Mfl * np.exp2(sh); etot = Emax + gE[r]
                else: Mtab = np.zeros_like(Mfl); etot = 0
                R = FT(nsc, np.ascontiguousarray(Mtab.reshape([cards[u] for u in nsc])) if nsc else np.asarray(Mtab).reshape(()), etot, rhoM); R.tag = 'msg:%d:%d' % (step_i, r)
                if nsc: live[id(R)] = R
                else: self.scalars.append(R)
                step_tabs.append((g, gunion[r], ax, w[r]))
            self.steps.append((v, step_tabs)); self.max_q = max(self.max_q, m)
        self.opt_s = tnow() - t0
        self.logU_f = sum(log2(float(r.M)) for r in self.scalars if float(r.M) > 0) if all(float(r.M) > 0 for r in self.scalars) else -inf; self.E_U = sum(r.e for r in self.scalars); self.n_scalar = len(self.scalars)
        self.logU = (self.logU_f + self.E_U) if self.logU_f > -inf else -inf; self.rhoU = prod((1 + r.rho) for r in self.scalars) * (1 + UF) ** len(self.scalars) - 1
        self.splits = sum(len(g) - 1 for g in self.groups_per_step); self.max_range_sum = ref.max_range_sum; self.max_table = ref.max_table; self.max_q1 = ref.max_q1
        # precompute per-step log tables of the group members for the sampler
        self.prep = []
        for v, tabs in self.steps:
            if tabs is None: self.prep.append((v, None)); continue
            comps = []
            for g, union, ax, wr in tabs:
                mem = []
                for f in g:
                    with np.errstate(divide='ignore'): LM = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape(-1)
                    strides = {}; s_ = 1
                    for u in reversed(f.scope): strides[u] = s_; s_ *= cards[u]
                    mem.append((LM, strides, f.scope))
                comps.append((mem, wr))
            self.prep.append((v, comps))
        self.step_ranges = [[f.R for g, _, _, _ in tabs for f in g] if tabs else [] for _, tabs in self.steps]

    def sample_batch(self, rng, B, pos):
        n_sep = len(pos); S = np.zeros((B, n_sep), dtype=np.int64); logq = np.zeros(B); zero_row = np.zeros(B, dtype=bool); cards = self.cards
        for v, comps in reversed(self.prep):
            n = cards[v]; pv = pos[v]
            if comps is None: S[:, pv] = rng.integers(0, n, size=B); logq -= log2(n); continue
            qrow = np.zeros((B, n)); dead_any = np.zeros(B, dtype=bool)
            for mem, wr in comps:
                L = np.zeros((B, n))
                for LM, strides, scope in mem:
                    base = np.zeros(B, dtype=np.int64)
                    for u in scope:
                        if u != v: base += S[:, pos[u]] * strides[u]
                    L += LM[base[:, None] + np.arange(n)[None, :] * strides[v]]
                _, logp, dead = _powsum_log(L, wr); p = np.where(np.isfinite(logp), np.exp2(np.where(np.isfinite(logp), logp, -2000.0)), 0.0); qrow += wr * p; dead_any |= dead
            qrow[qrow < ldexp(1.0, PROB_TRUNC_LOG2)] = 0.0; qrow[dead_any] = 1.0 / n
            tot = qrow.sum(axis=1); c = np.cumsum(qrow, axis=1); r = rng.random(B) * tot; a = np.minimum((c <= r[:, None]).sum(axis=1), n - 1)
            pa = qrow[np.arange(B), a]; bad = pa == 0.0
            if bad.any(): a[bad] = qrow[bad].argmax(axis=1); pa = qrow[np.arange(B), a]
            S[:, pv] = a; logq += np.log2(pa) - np.log2(tot); zero_row |= dead_any
        return S, logq, zero_row


def f_sig(f): return (f.scope, getattr(f, 'tag', None))


def ft_product_log(fts, cards):
    """log2 of the product of FTs over the union scope (no underflow possible): returns (union, log2 P (with -inf at zeros), exponent sum, rho of the product of mantissas)"""
    union = tuple(sorted(set().union(*(set(f.scope) for f in fts)))); L = None; e = 0; r = F(1)
    for f in fts:
        with np.errstate(divide='ignore'): lm = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape([cards[v] if v in f.scope else 1 for v in union])
        L = lm if L is None else L + lm; e += f.e; r *= (1 + f.rho)
    return union, np.broadcast_to(L, [cards[v] for v in union]).copy(), e, r * (1 + UF) ** max(0, len(fts) - 1) - 1

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
    if isinstance(mbp, WMBFloat): return numerical_widening_wmb(blocks, mbp, qrhos, n_sep, maxcard, E_tot)
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



# ---------------------------------------------------------------- EXACT ROUTE for unsplit constructions (round 7): shared backward pass = the arithmetic-circuit differential
def ft_scalar_product(fts):
    M = 1.0; e = 0; r = F(1)
    for f in fts: M *= float(f.M); e += f.e; r *= (1 + f.rho)
    if M == 0.0: return FT((), np.array(0.0), 0, F(0))
    k = frexp(M)[1] - 1; return FT((), np.array(M * ldexp(1.0, -k)), e + k, r * (1 + UF) ** max(0, len(fts) - 1) - 1)


def backward_derivatives(mbp, cards, deadline):
    """D[id(f)] = dZ/df over f.scope for every input block table of an UNSPLIT mini-bucket pass: D(final scalars) = 1; at step (v, bucket, R): D_f = sum_{union minus scope f} D_R x prod_{g in bucket, g != f} g
    (zero-safe: prefix / suffix products, no division). Every product is range-pre-checked and every rho exact (the same lemma as the forward pass)."""
    roots = mbp.scalars; m = len(roots)
    if any(float(r.M) == 0.0 for r in roots): raise RangeRefused('backward: a zero scalar root (Z = 0 must be reported as ZERO_EVIDENCE before any normalized publication)')
    pre = [None] * m; suf = [None] * m; acc = None
    for i in range(m): pre[i] = acc; acc = roots[i] if acc is None else ft_scalar_product([acc, roots[i]])
    acc = None
    for i in range(m - 1, -1, -1): suf[i] = acc; acc = roots[i] if acc is None else ft_scalar_product([acc, roots[i]])
    D = {}
    for i, r in enumerate(roots):                                  # dZ / dr_i = prod_{j != i} r_j: the differential of the FINAL product of roots (disconnected components)
        parts = [x for x in (pre[i], suf[i]) if x is not None]; D[id(r)] = ft_scalar_product(parts) if parts else FT((), np.array(1.0), 0, F(0))
    for v, bucket, R in reversed(mbp.fwd):
        if tnow() >= deadline: raise Deadline('backward')
        DR = D.get(id(R))
        if DR is None: raise RangeRefused('backward: a message without a consumer derivative (internal)')
        union = tuple(sorted(set().union(*(set(f.scope) for f in bucket)))); k = len(bucket)
        if sum(f.R for f in bucket) + DR.R > RANGE_BUDGET: raise RangeRefused('backward product of %d tables could underflow (range bits %d > %d)' % (k + 1, sum(f.R for f in bucket) + DR.R, RANGE_BUDGET))
        A = [f.M.reshape([cards[u] if u in f.scope else 1 for u in union]) for f in bucket]; DRa = DR.M.reshape([cards[u] if u in DR.scope else 1 for u in union])
        pre = [None] * k; suf = [None] * k; acc = None
        for i in range(k): pre[i] = acc; acc = A[i] if acc is None else acc * A[i]
        acc = None
        for i in range(k - 1, -1, -1): suf[i] = acc; acc = A[i] if acc is None else acc * A[i]
        full = [cards[u] for u in union]
        for i, f in enumerate(bucket):
            P = DRa
            if pre[i] is not None: P = P * pre[i]
            if suf[i] is not None: P = P * suf[i]
            P = np.broadcast_to(P, full)                                   # a single-factor bucket: the derivative is DR tiled along the eliminated variable (prod over an empty set = 1)
            e = DR.e + sum(g.e for j, g in enumerate(bucket) if j != i); rho = (1 + DR.rho) * prod((1 + g.rho) for j, g in enumerate(bucket) if j != i) * (1 + UF) ** k - 1
            axes = tuple(ai for ai, u in enumerate(union) if u not in f.scope); nsum = prod(cards[union[ai]] for ai in axes) if axes else 1
            Df = P.sum(axis=axes) if axes else P; rho = (1 + rho) * (1 + UF) ** max(0, nsum - 1) - 1
            Df = np.asarray(Df, dtype=float).reshape([cards[u] for u in f.scope]) if f.scope else np.asarray(Df, dtype=float).reshape(())
            Df, e = _rescale(np.ascontiguousarray(Df), e); D[id(f)] = FT(f.scope, Df, e, rho)
    return D


def ve_retain(fts, cards, keep, deadline, byte_cap):
    """float variable elimination of every variable except `keep` (greedy min-size), range-pre-checked, rho-exact; returns FT over (keep,) or None if a table would exceed byte_cap"""
    live = list(fts); vars_ = sorted({u for f in live for u in f.scope} - {keep})
    while vars_:
        if tnow() >= deadline: raise Deadline('ve_retain')
        best = None
        for v in vars_:
            nb = set().union(*(set(f.scope) for f in live if v in f.scope)) - {v}; size = prod(cards[u] for u in nb) if nb else 1
            if best is None or size < best[0]: best = (size, v)
        size, v = best
        if size * cards[v] * 8 > byte_cap: return None
        bucket = [f for f in live if v in f.scope]; live = [f for f in live if v not in f.scope]
        if bucket: live.append(ft_eliminate(bucket, v, cards, 'sum'))
        vars_.remove(v)
    union, P, e, rho = ft_product(live, cards)
    if set(union) != {keep}: raise RangeRefused('ve_retain: unexpected scope %s' % (union,))
    P, e = _rescale(np.asarray(P, dtype=float).reshape([cards[keep]]), e); return FT((keep,), P, e, rho)


def interval_ratio(N, v, Z):
    """exact rational enclosure of N[v] 2^eN / Z 2^eZ from the float values and exact rho bounds; (lo, hi) within [0, 1]"""
    n = F(float(N.M.reshape(-1)[v])) * F(2) ** N.e; z = F(float(Z.M)) * F(2) ** Z.e
    if n == 0: return F(0), F(0)
    lo = n * (1 - N.rho) / (z * (1 + Z.rho)); hi = n * (1 + N.rho) / (z * (1 - Z.rho)); return max(F(0), lo), min(F(1), hi)


def executor_crosscheck(blocks_int, S, order, deadline, cap_bytes):
    """the existing certified executor (cex/newarm/cex_executor.py) on the discovered SEPARATOR model (exact rational block tables, renumbered) and the discovered elimination order;
    returns dict(status, rows (per separator variable: list of (lo, hi) Fractions) or None, stats subset)"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
    import cex_executor as NCEX
    ren = {v: i for i, v in enumerate(S)}; cards_s = [BLOCK_CARDS[v] for v in S]
    model = dict(cards=cards_s, evidence={}, factors=[dict(scope=tuple(ren[v] for v in f.scope), values=[F(int(x)) for x in np.asarray(f.arr, dtype=object).reshape(-1).tolist()]) for f in blocks_int])
    t0 = tnow()
    try: r = NCEX.execute(model, [ren[v] for v in order], deadline=deadline, cap_bytes=cap_bytes)
    except NCEX.Stop as e: return dict(status='STOP:' + str(getattr(e, 'kind', '?')), reason=str(getattr(e, 'reason', e))[:200], wall_s=tnow() - t0)
    except Exception as e: return dict(status='ERROR', reason=repr(e)[:200], wall_s=tnow() - t0)
    return dict(status=r['status'], rows=r.get('intervals'), wall_s=tnow() - t0, max_width=(r.get('stats') or {}).get('max_width_float'), kernel_s=(r.get('stats') or {}).get('kernel_s'))


BLOCK_CARDS = None


def numerical_widening_wmb(blocks, mbp, qrhos, n_sep, maxcard, E_tot):
    """WMB sampler (NOTE section 10): per step, each of m mixture components computes a row log-sum L (as the MB sampler), divides by w_r (<= 1/W_MIN), exp2, normalizes, and the components are
    mixed with weights w_r; the analysed law is the float mixture row normalized by its float sum. The cap: the exact identity prod_r F_r / M_r <= q_i holds for the EXACT power sums of the
    stored tables; each stored message M_r carries rho_M (tracked), and the implemented components p_r vs the exact p_r carry the same log-domain error as the MB rows times (1 / w_r)."""
    u = UF; L2 = F(145, 100); WI = F(1) / F(W_MIN)
    def logerr(mag): return u * (F(mag) + 1)
    rho_tab = prod((1 + b.rho) for b in blocks) - 1
    d_cap = F(0); d_impl = F(0); mag_logq = F(0)
    for Rs in mbp.step_ranges:
        if not Rs: mag_logq += F(int(maxcard).bit_length()); continue
        SR = sum(Rs); q1 = len(Rs)
        dL = sum(logerr(R) for R in Rs) + u * (q1 + 1) * (SR + q1)
        dA = dL * WI + u * (F(SR) * WI + 2)                                                # the row argument L / w (magnitude <= SR / W_MIN)
        rel_p = L2 * dA * (1 + dA) + 4 * u; rel_cond = 2 * rel_p + (maxcard - 1) * u
        rel_mix = rel_cond + mbp.max_q * u + (maxcard - 1) * u + 4 * u                       # weighting by w_r, summing m components, the row normalization
        d_cap += rel_mix / F(69, 100)
        d_impl += logerr(901) + logerr(int(maxcard).bit_length() + 1) + u * (mag_logq + 910)
        mag_logq += 901 + int(maxcard).bit_length() + 1
    rho_msgs = prod((1 + r) for r in mbp.rho_steps) - 1 if mbp.rho_steps else F(0)        # every stored message's power-sum error enters the telescoping cap once
    SRb = sum(b.R for b in blocks); nb = len(blocks); d_z = sum(logerr(b.R) for b in blocks) + u * nb * (SRb + nb)
    d_U = u * mbp.n_scalar * (mbp.n_scalar + int(maxcard).bit_length() + 2) + logerr(1) * mbp.n_scalar
    max_mag = max(SRb + nb, mag_logq, mbp.n_scalar + 2, abs(E_tot)); d_fin = 4 * u * (SRb + nb + mag_logq + mbp.n_scalar + 2 + abs(E_tot))
    d_total = d_z + d_impl + d_U + d_fin; rho_X = L2 * d_total * (1 + d_total)
    rho_cap = (1 + rho_tab) * (1 + L2 * d_cap * (1 + d_cap)) * (1 + rho_msgs) * (1 + mbp.rhoU) * (1 + rho_X) - 1
    rho_f = max([2 * r for r in qrhos] + [F(0)]) + max([b.rho for b in blocks]) + 4 * UF
    law = 4 * n_sep * F(maxcard + 2, 1 << 53); trunc = n_sep * F(1, 1 << 900)
    return dict(rho_X=rho_X, rho_cap=rho_cap, rho_f=rho_f, law=law, trunc=trunc, eps_num=2 * rho_X + rho_f + law + trunc, delta_log_total=d_total, max_log_mag=max_mag)

# ---------------------------------------------------------------- the integrated solve
def solve(model_path, budget, seed=1, table_cap=1 << 18, enum_cap=1 << 16, eps=F(1, 200), delta=F(1, 10 ** 6), mb_cap=1 << 24, construct_share=0.5, batch=1024, check_s=0.5, force_approx=False, schedule='baseline', route='auto', construct_only=False, crosscheck=True, proposal='mb', opt_s=3.0):
    global BLOCK_CARDS
    t_start = tnow(); deadline = t_start + budget; ph = {}; rng = np.random.default_rng(seed); stats = dict(elim_work=0, eliminations=0, query_work=0)
    out = dict(version=VERSION, seed=seed, budget_s=budget, table_cap=table_cap, enum_cap=enum_cap, mb_cap=mb_cap, batch=batch, schedule=schedule, route_requested=route, proposal=proposal, epsilon=str(eps), delta=str(delta), phases_s=ph, mechanism={}, outcome=None, answers=None)
    t0 = tnow(); model, binding = BR.core.read_uai(model_path); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); out['binding'] = binding; ph['read'] = tnow() - t0
    queries = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K = len(queries); qix = {q: j for j, q in enumerate(queries)}; out['K'] = K
    ans = {}; pending = {}; failed = []
    def publish(j, lo, hi, point, g): ans[j] = dict(lo=lo, hi=hi, point=point, guarantee=g)
    def finish_(oc, witness=None):
        out['outcome'] = oc
        if witness: ans.update(pending)
        out['positive_mass_witness'] = witness; res = BR.finish(out, t_start, queries, ans, failed)
        gs = {r['guarantee'] for r in res.get('answers') or []}
        if gs and gs <= {'EXACT', 'DETERMINISTIC'}: res['guarantee'] = 'DETERMINISTIC' if 'DETERMINISTIC' in gs else 'EXACT'
        elif gs and 'NOT_PUBLISHED' not in gs: res['guarantee'] = 'PAC'
        return res
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
        out['mechanism'].update(mb_cap=mb_cap, mb_logU=mbp.logU, mb_max_table=mbp.max_table, mb_max_range_sum_bits=mbp.max_range_sum, block_max_range_bits=max(b.R for b in blocks), Kq=Kq, sep_queries=len(sep_q), interior_query_cols=len(qcols),
                                mb_splits=mbp.splits, mb_split_steps=mbp.split_steps[:12], mb_unsplit=(mbp.splits == 0))
        if mbp.logU == -inf: return finish_('ZERO_EVIDENCE')
        if construct_only: out['outcome'] = 'CONSTRUCT_ONLY'; return BR.finish(out, t_start, queries, {}, failed)
        # ---- EXACT ROUTE: an unsplit mini-bucket pass is exact bucket elimination on the separator model; recover every marginal from one shared backward pass
        if mbp.splits == 0 and route in ('auto', 'exact'):
            t0 = tnow(); exact_note = None
            try:
                Zft = ft_scalar_product(mbp.scalars)
                if float(Zft.M) == 0.0: return finish_('ZERO_EVIDENCE')
                D = backward_derivatives(mbp, cards, deadline); Dblk = [D[id(fi)] for fi in mbp.inputs]
                pub_exact = {}; blockfac = {i: [conv(f) for f in fns if f.facs <= live[i].facs] for i in range(len(blocks))}
                # separator variables: N(x = v) = sum_{s_b : s_b[x] = v} g_b(s_b) D_b(s_b) for the smallest block containing x
                for x in S:
                    bi = min((i for i, b in enumerate(blocks) if x in b.scope), key=lambda i: blocks[i].M.size); b = blocks[bi]
                    union, P, e, rho = ft_product([b, Dblk[bi]], cards); axes = tuple(ai for ai, u in enumerate(union) if u != x); nsum = prod(cards[union[ai]] for ai in axes) if axes else 1
                    Nx = P.sum(axis=axes) if axes else P; rho = (1 + rho) * (1 + UF) ** max(0, nsum - 1) - 1; Nx, e = _rescale(np.asarray(Nx, dtype=float).reshape([cards[x]]), e); Nft = FT((x,), Nx, e, rho)
                    for v in range(cards[x]):
                        lo, hi = interval_ratio(Nft, v, Zft)
                        if hi - lo <= 2 * eps: pub_exact[qix[(x, v)]] = (lo, hi)
                # interior variables: block model = the block's original factors + D_b; eliminate everything but x
                unrec = []
                for i, b in enumerate(blocks):
                    for x in b.interior:
                        if tnow() >= deadline: raise Deadline('exact_interior')
                        Nft = ve_retain(blockfac[i] + [Dblk[i]], cards, x, deadline, FLOAT_BYTE_CAP)
                        if Nft is None: unrec.append(x); continue
                        for v in range(cards[x]):
                            lo, hi = interval_ratio(Nft, v, Zft)
                            if hi - lo <= 2 * eps: pub_exact[qix[(x, v)]] = (lo, hi)
                ph['exact_route'] = tnow() - t0
                xc = None
                if crosscheck:
                    BLOCK_CARDS = cards; t0 = tnow(); xc = executor_crosscheck(live, S, mbp.order, deadline, 3 * 1024 ** 3); ph['executor_crosscheck'] = tnow() - t0; dis = 0; cmp_ = 0; need = 0; missing = 0
                    rows_ = xc.get('rows')
                    for si, x in enumerate(S):
                        for v in range(cards[x]):
                            j = qix[(x, v)]
                            if j not in pub_exact: continue
                            need += 1
                            if not rows_ or rows_[si] is None or len(rows_[si]) <= v: missing += 1; continue
                            cmp_ += 1; lo, hi = pub_exact[j]; xlo, xhi = rows_[si][v]
                            if hi < xlo or xhi < lo: dis += 1
                    xc = dict(xc, required=need, compared=cmp_, missing=missing, disjoint=dis); xc.pop('rows', None)
                    # a REQUESTED cross-check must succeed (CERTIFIED), cover every published separator coordinate, and agree; anything else is a typed failure of the route
                    if xc['status'] != 'CERTIFIED' or missing or cmp_ != need: exact_note = 'CROSSCHECK_FAILED'; out['mechanism']['exact_route'] = dict(status='CROSSCHECK_FAILED: %s (required %d, compared %d, missing %d)' % (xc['status'], need, cmp_, missing), crosscheck=xc)
                    elif dis: exact_note = 'INVESTIGATE'; out['mechanism']['exact_route'] = dict(status='INVESTIGATE: executor disagrees on %d separator coordinates' % dis, crosscheck=xc)
                if exact_note is None:
                    # A3: compact every outward enclosure onto the dyadic grid Q = 2^52 with exact integer arithmetic (L = floor(Q lo) / Q <= lo, H = ceil(Q hi) / Q >= hi), recheck the width
                    Q = 1 << 52; compact = {}; too_wide = 0
                    for j, (lo, hi) in pub_exact.items():
                        L = F(math.floor(lo * Q), Q); H = F(-((-hi * Q).numerator // (-hi * Q).denominator), Q) if hi < 1 else F(1); L = max(F(0), L); H = min(F(1), H)
                        if H - L <= 2 * eps: compact[j] = (L, H)
                        else: too_wide += 1
                    out['mechanism'].update(route='exact', exact_route=dict(status='OK', published=len(compact), too_wide_after_compaction=too_wide, unrecovered_interior=len(unrec), Z_log2=lg(F(float(Zft.M)) * F(2) ** Zft.e), rho_Z=fup(Zft.rho), crosscheck=xc, compaction='dyadic grid 2^-52, outward'))
                    ans.update(pending)
                    for j, (L, H) in compact.items(): publish(j, L, H, (L + H) / 2, 'DETERMINISTIC')
                    failed += unrec; out['positive_mass_witness'] = True
                    return finish_('COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL', witness=True)
            except RangeRefused as e: out['mechanism']['exact_route'] = dict(status='REFUSED: ' + str(e)); ph['exact_route'] = tnow() - t0
            if route == 'exact': return finish_('EXACT_ROUTE_UNAVAILABLE' if exact_note is None else 'EXACT_ROUTE_' + exact_note)
            out['mechanism']['exact_route_fallback'] = 'PAC route after the exact route did not publish (%s)' % (exact_note or 'refused')
            # otherwise fall through to the PAC route (sampling retained where exact completion is unavailable)
        out['mechanism']['route'] = 'pac'
        if proposal == 'wmb':                                             # candidate: weighted mini-buckets on the SAME partition and order (frozen before any draw)
            t0 = tnow()
            try: wmbp = WMBFloat(mbp, blocks, cards, deadline, opt_s=opt_s)
            except RangeRefused as e: out['refusal'] = str(e); out['mechanism']['wmb'] = dict(status='REFUSED: ' + str(e)); return finish_('NUMERIC_RANGE_REFUSED')
            ph['wmb_construct'] = tnow() - t0
            if wmbp.logU == -inf: return finish_('ZERO_EVIDENCE')
            # selection by CONSTRUCTION information only (the certified bound): the proposal with the smaller log U is frozen before any draw; a cap always belongs to its own proposal
            use_wmb = wmbp.logU < mbp.logU
            out['mechanism'].update(wmb=dict(status='OK', opt_s=wmbp.opt_s, weights=[w for w in wmbp.weights if len(w) > 1][:12], logU_mb=mbp.logU, logU_wmb=wmbp.logU, bound_tightening_log2=(mbp.logU - wmbp.logU) if (mbp.logU > -inf and wmbp.logU > -inf) else None, rhoU=fup(wmbp.rhoU), selected=('wmb' if use_wmb else 'mb (weighted bound not smaller)')))
            if use_wmb: mbp = wmbp                                      # the stream below uses mbp.sample_batch / logU_f / E_U / rhoU / step_ranges / max_q1 of the FROZEN selected proposal
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
        witness = False; draws = 0; zero_draws = 0; pub = {}; trace_rows = []; t_loop = 0.0; t_cert = 0.0; next_chk = tnow() + check_s; sumX = 0.0; maxlogX = -inf; sumX2 = 0.0; maxX = 0.0
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
            cert.update_batch(X, f); zcert.update_batch(X); draws += B; zero_draws += int(zero.sum()); sumX += float(X.sum()); sumX2 += float((X * X).sum()); maxX = max(maxX, float(X.max())); t_loop += tnow() - t0
            if tnow() >= next_chk: check_publish(); next_chk = tnow() + check_s
        width = check_publish(); unpub = [j for j in range(Kq) if j not in pub]; wf = width[unpub]; wf = wf[np.isfinite(wf)]
        zi = zcert.interval(); per_draw = t_loop / max(1, draws); total = t_loop + t_cert
        ess = (sumX * sumX / sumX2) if sumX2 > 0 else 0.0
        var_resid, _ = cert.variance()
        out['mechanism'].update(sum_X=sumX, sum_X2=sumX2, max_X=maxX, zero_weight_fraction=zero_draws / max(1, draws), ESS=ess, ESS_per_s=ess / max(1e-9, t_loop), largest_share=(maxX / sumX if sumX > 0 else None), draws_per_s=draws / max(1e-9, t_loop),
                                response_residual_variance_median=float(np.median(var_resid)), response_residual_variance_p90=float(np.percentile(var_resid, 90)), proposal_used=proposal)
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
    ap.add_argument('--force-approx', action='store_true'); ap.add_argument('--batch', type=int, default=1024); ap.add_argument('--schedule', default='baseline', choices=['baseline', 'targeted']); ap.add_argument('--route', default='auto', choices=['auto', 'pac', 'exact']); ap.add_argument('--construct-only', action='store_true'); ap.add_argument('--no-crosscheck', action='store_true'); ap.add_argument('--proposal', default='mb', choices=['mb', 'wmb']); ap.add_argument('--opt-s', type=float, default=3.0)
    a = ap.parse_args()
    out = solve(a.input, a.budget, seed=a.seed, table_cap=a.table_cap, enum_cap=a.enum_cap, eps=F(a.epsilon), delta=F(a.delta), mb_cap=a.mb_cap, force_approx=a.force_approx, batch=a.batch, schedule=a.schedule, route=a.route, construct_only=a.construct_only, crosscheck=not a.no_crosscheck, proposal=a.proposal, opt_s=a.opt_s)
    out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    t_ser = time.monotonic(); os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    json.dump(dict(solver_wall_s=out['wall_s'], serialize_s=time.monotonic() - t_ser, in_process_total_s=time.monotonic() - T_PROCESS_START, result_bytes=os.path.getsize(a.output), note='the SUPERVISOR receipt is the scored end-to-end measurement'), open(a.output + '.timing.json', 'w'), indent=1)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), phases={k: round(v, 3) for k, v in out['phases_s'].items()},
                                   mech={k: (round(m[k], 4) if isinstance(m.get(k), float) else m.get(k)) for k in ('blocks', 'separator_vars', 'mb_cap', 'mb_logU', 'mb_splits', 'mb_unsplit', 'route', 'exact_route', 'wmb', 'ESS', 'largest_share', 'zero_weight_fraction', 'max_X', 'draws_per_s', 'mb_max_range_sum_bits', 'eps_num_log2', 'rho_X', 'E_tot', 'delta_log_total', 'draws', 'ms_per_draw', 'X_mean', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'max_log2_X_observed', 'published', 'remaining', 'max_remaining_width', 'median_remaining_width', 'lam_last_median', 'schedule', 'extrapolated_s_max_width', 'extrapolated_s_median_width', 'Z_EB_relative_width', 'interior_queries_recovered', 'interior_queries_failed')}), default=str))


if __name__ == '__main__': main()
