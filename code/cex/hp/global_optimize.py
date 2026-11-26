"""DGP6 global construction, part 2: graph selection (G0 / G1), the bounded two-phase L-BFGS-B over the floating circuits, the affine probability segment, quantization and selection (brief sections 1-3).
G1: for every variable independently (from the ORIGINAL seed graph G0) the earlier-sampled non-parent with the highest interaction score / added entries (stable id ties) whose enlarged table has <= 4,096 entries;
rows replicated exactly (G1 initially IS the seed law); aliased to G0 when no extension is legal. Optimizer: parameters = sampling-order variables x lexicographic parent rows x child states; init log(count) - max;
box [-40 ln 2, 0]; two warm-started phases p = 16, 64 (maxiter 12, maxls 8, maxcor 3, <= 16 joint evaluations each, hard total 32; the counter AND the clock enforced before every evaluation); the best finite completed
iterate per phase; the endpoint = the p = 64 best else the p = 16 best. Segment theta(lambda) = (1 - lambda) theta_seed + lambda theta_opt at lambda = 0, 1/16, ..., 1 scored forward-only under the ORIGINAL (hard MAX)
floating circuits (<= 17 evaluations) with the same eta and the graph's d_hat; the lowest finite proxy J. Quantization: exact normalization of the binary64 row, 1 + floor((D - k) p_a) EXACTLY, residual by stable state id."""
import math, time
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import joint_proposal as JP, joint_optimize as JO
from joint_proposal import D, D_BITS, Conditional, Proposal, vol_of, RefusedJoint
import global_circuit as GC
LN2 = math.log(2.0); LO = -D_BITS * LN2; HI = 0.0
PHASES = ((16, 16), (64, 16)); MAXITER = 12; MAXLS = 8; MAXCOR = 3; HARD_TOTAL = 32; SEGMENT_POINTS = 17; V_FAMILY = 4096


class OptimizerExpired(Exception): pass


def select_g1(prop, pairs, cards, V_family=V_FAMILY):
    """G1 parent sets from G0: per variable the best legal extension (score / added entries, then id); returns (parents dict, record); alias flag when nothing is legal"""
    pos = {v: i for i, v in enumerate(prop.order)}; parents = {}; rec = []
    for z in prop.order:
        c = prop.conds[z]; earlier = [w for w in prop.order if pos[w] < pos[z] and w not in c.parents]; best = None
        for w in earlier:
            vol = vol_of(tuple(c.parents) + (w,), cards) * cards[z]
            if vol > V_family: continue
            sc = JO.score_of(pairs, z, w); added = vol - c.family_volume(); ratio = (sc / added) if added > 0 else math.inf
            if best is None or ratio > best[0] or (ratio == best[0] and w < best[1]): best = (ratio, w, sc, vol)
        if best is None: parents[z] = tuple(c.parents); rec.append(dict(z=z, added=None, reason=('no earlier variable' if not earlier else 'no legal extension <= %d entries' % V_family)))
        else: parents[z] = tuple(sorted(c.parents + (best[1],), key=lambda p: pos[p])); rec.append(dict(z=z, added=best[1], score=best[2], ratio=best[0], volume=best[3]))
    alias = all(r['added'] is None for r in rec); return parents, dict(alias_G0=alias, extensions=rec, n_extended=sum(1 for r in rec if r['added'] is not None), total_entries=sum(vol_of(parents[z], cards) * cards[z] for z in prop.order))


def replicate_graph(prop, parents, cards, budget=None):
    """the SAME law on the G1 contexts (rows replicated; each replicated table admitted BEFORE allocation when a budget is given; exception-safe: a refusal midway releases every table already replicated); returns Proposal
    (B / S copied: the law is identical); the replicated tables' bytes are owned by the caller (sum of c.bytes over the tables that are not the originals)"""
    conds = {}; fresh = []
    try:
        for z in prop.order:
            c = prop.conds[z]
            if tuple(c.parents) == tuple(parents[z]): conds[z] = c
            else: conds[z] = c.replicate(tuple(parents[z]), cards, budget=budget); fresh.append(conds[z])
        return Proposal(cards, conds, prop.order, prop.B, prop.S, dict(prop.provenance, graph='G1', replicated=True), predecessor=None)
    except BaseException:
        if budget is not None:
            for c in fresh: budget.release(c.bytes)
        raise


def quantize_rows_exact(th_rows, k):
    """rows of binary64 probabilities -> positive counts summing to D per row: EXACT normalization of the rationals represented by the finite binary64 entries (x = num / 2^e via as_integer_ratio, aligned to the row's
    largest power-of-two denominator in integers), c_a = 1 + floor((D - k) p_a) computed EXACTLY in integer arithmetic, the residual D - sum c allocated by stable state id (one unit each from state 0 upward)"""
    th = np.asarray(th_rows, dtype=float)
    if not np.isfinite(th).all() or (th < 0).any(): raise RefusedJoint('MALFORMED', 'a row has a negative or non-finite probability')
    out = np.empty((th.shape[0], k), dtype=np.int64); Dk = D - k
    for r in range(th.shape[0]):
        ratios = [float(x).as_integer_ratio() for x in th[r]]; emax = max(d.bit_length() for _, d in ratios) - 1          # every denominator is 2^e_a; align to 2^emax
        nums = [n << (emax - (d.bit_length() - 1)) for n, d in ratios]; tot = sum(nums)
        if tot == 0: nums = [1] * k; tot = k
        c = [1 + (Dk * n_) // tot for n_ in nums]; left = D - sum(c)
        if left < 0: raise CE.Defect('quantization: floors exceed D')
        for i in range(left): c[i % k] += 1
        out[r] = c
    assert (out.sum(axis=1) == D).all() and (out >= 1).all(); return out


def logits_to_rows(FC, t, v):
    off, R, k = FC.row_slices[v]; tr = t[off:off + R * k].reshape(R, k); m = tr.max(axis=1, keepdims=True); e = np.exp(tr - m); return e / e.sum(axis=1, keepdims=True)


def rows_to_logits(FC, rows_by_v):
    t = np.zeros(FC.n_params)
    for v, rows in rows_by_v.items():
        off, R, k = FC.row_slices[v]; lr = np.log(np.maximum(rows, 1e-300)); t[off:off + R * k] = (lr - lr.max(axis=1, keepdims=True)).reshape(-1)
    return t


class BoundedLBFGS:
    """two warm-started phases of L-BFGS-B on the floating objective; the evaluation counter and the clock are checked BEFORE each circuit evaluation (a request beyond the cap or past the deadline raises OptimizerExpired and
    the phase keeps its best finite COMPLETED iterate); cached identical requests are served without evaluating (counted as cache hits, not evaluations)"""
    def __init__(self, FB, FS, log_eta, mode, deadline, hard_total=HARD_TOTAL):
        self.FB = FB; self.FS = FS; self.log_eta = log_eta; self.mode = mode; self.deadline = deadline; self.hard_total = hard_total; self.evals = 0; self.cache_hits = 0; self.trace = []; self.best = {}; self.phase = None; self.phase_evals = 0; self.phase_cap = 0; self.p = None; self._last = None
    def _f(self, t):
        key = t.tobytes()
        if self._last is not None and self._last[0] == key: self.cache_hits += 1; return self._last[1], self._last[2]
        if self.evals >= self.hard_total or self.phase_evals >= self.phase_cap: raise OptimizerExpired('evaluation cap (phase %d / total %d)' % (self.phase_evals, self.evals))
        if CE.tnow() >= self.deadline: raise OptimizerExpired('deadline before an evaluation')
        o = GC.objective(self.FB, self.FS, t, self.log_eta, self.p, self.mode); self.evals += 1; self.phase_evals += 1; f = float(o['f']); g = np.asarray(o['g'], dtype=float)
        self.trace.append(dict(phase=self.phase, p=self.p, eval=self.evals, f=f, logB=o['logB'], logS=o['logS'], gnorm=float(np.abs(g).max()) if g.size else 0.0, t_s=round(CE.tnow(), 3)))
        if math.isfinite(f) and (self.phase not in self.best or f < self.best[self.phase]['f']): self.best[self.phase] = dict(f=f, t=t.copy(), logB=o['logB'], logS=o['logS'], gap=GC.box_gap(f, g, t), eval=self.evals)
        self._last = (key, f, g); return f, g
    def run(self, t0):
        from scipy.optimize import minimize, Bounds
        t = t0.copy(); rec = []; bounds = Bounds(np.full(t.size, LO), np.full(t.size, HI))                          # arrays, never a Python list of n tuples
        for pi, (p, cap) in enumerate(PHASES):
            self.phase = pi; self.p = p; self.phase_evals = 0; self.phase_cap = cap; self._last = None; status = None; t_start = CE.tnow()
            try:
                r = minimize(self._f, t, jac=True, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=MAXITER, maxls=MAXLS, maxcor=MAXCOR, maxfun=10 ** 6)); status = dict(success=bool(r.success), message=str(r.message)[:80], nit=int(r.nit), nfev=int(r.nfev))
            except OptimizerExpired as e: status = dict(success=False, message='EXPIRED: ' + str(e)[:60], expired=True)
            best = self.best.get(pi); rec.append(dict(phase=pi, p=p, evaluations=self.phase_evals, cache_hits=self.cache_hits, status=status, best_f=(best['f'] if best else None), best_logB=(best['logB'] if best else None), best_logS=(best['logS'] if best else None), best_gap=(best['gap'] if best else None), seconds=CE.tnow() - t_start, delta_smoothing=max(self.FB.delta_smoothing(p), self.FS.delta_smoothing(p))))
            if best is None: break
            t = best['t'].copy()
            if status.get('expired') and CE.tnow() >= self.deadline: break
        endpoint = self.best.get(1) or self.best.get(0); return endpoint, rec


def segment_scores(FB, FS, t_seed, t_opt, log_eta, log_dhat, mode, deadline, points=SEGMENT_POINTS):
    """forward-only scores of theta(lambda) under the ORIGINAL hard-MAX circuits at lambda = i / (points - 1); -> list of dicts; the lowest finite proxy J selected (lambda = 0 is the seed law on this graph)"""
    rows_seed = {v: logits_to_rows(FB, t_seed, v) for v in FB.plan.order}; rows_opt = {v: logits_to_rows(FB, t_opt, v) for v in FB.plan.order}; out = []
    for i in range(points):
        if CE.tnow() >= deadline: out.append(dict(i=i, lam=i / (points - 1), censored='deadline')); continue
        lam = i / (points - 1); rows = {v: (1 - lam) * rows_seed[v] + lam * rows_opt[v] for v in FB.plan.order}; t = rows_to_logits(FB, rows)
        lB, _ = FB.forward(t, None); lS, _ = FS.forward(t, None); H = (lB if mode == 'cap_only' else lS if mode == 'moment_only' else np.logaddexp(lS, log_eta + lB)); out.append(dict(i=i, lam=lam, logB=float(lB), logS=float(lS), logH=float(H), logJ=float(H) + log_dhat))
    fin = [x for x in out if 'logJ' in x and math.isfinite(x['logJ'])]; best = min(fin, key=lambda x: (x['logJ'], x['i'])) if fin else None
    return out, best, (rows_seed, rows_opt)


def quantize_segment(FB, rows_seed, rows_opt, lam, cards, order, parents, budget=None, clock=None):
    """the actual quantized law at lambda: one Conditional per variable (each admitted BEFORE its arrays exist when a budget is given; exception-safe: a refusal midway releases every table already built)"""
    conds = {}
    try:
        for v in order:
            rows = (1 - lam) * rows_seed[v] + lam * rows_opt[v]; k = cards[v]
            if clock is not None: clock.poll('quantization of %d' % v)
            if budget is not None: budget.charge(JP.COUNT_BYTES * rows.size + 256, 'candidate conditional of %d' % v)
            try: conds[v] = Conditional(v, tuple(parents[v]), quantize_rows_exact(rows, k), cards)
            except BaseException:
                if budget is not None: budget.release(JP.COUNT_BYTES * rows.size + 256)
                raise
        return conds
    except BaseException:
        if budget is not None:
            for c in conds.values(): budget.release(c.bytes)
        raise
