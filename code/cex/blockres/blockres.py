"""BLOCK CONTRACTION FOR RESIDUAL INFERENCE -- experimental backend (19 Nov 2026; overseer brief of the same date). See NOTE.md for the mathematics.

Construction = ONE bounded-width partial variable elimination over the evidence-restricted, integerized model: a variable is eliminated only while the
resulting table has <= table_cap entries (a small declared ladder: cap, then 4 cap if the first level was cheap; every intermediate product also bounded in BYTES). Surviving functions g_b are exact
INTEGER tables over the separator S (union of surviving scopes); Y_b = variables eliminated into block b (a partition of the original factors into blocks is
induced: every original factor is absorbed into exactly one surviving function). z(s) = prod_b g_b(s_b) exactly.
Queries: all original singleton marginals. Separator x: f(s) = 1{s_x = v}. Interior x of block b: g_bx(s_b, v) = sum_{y_b minus x} w_b, recovered by replaying
the block's own elimination from the cached prefix with x retained; integrated numerator at s = g_bx(s_b, v) prod_{a != b} g_a(s_a) (an integer).
Inference on S: prefix cells over a fixed separator order. Per open cell C (N_C completions) the typed bounds
   mass      L_C = N_C prod_b min_C g_b  <=  sum_{s in C} z(s)  <=  B_C = N_C prod_b max_C g_b                       (exact integers)
   query     rho_lo <= g_bx(s_b, v) / g_b(s_b) <= rho_hi over the SUPPORT inside C (interior); 1{..} or [0, 1] (separator)   (outward floats -> rationals)
   residual  |g_bx(s_b, v) - c g_b(s_b)| <= H_bj(C), joint max over the cell slice (in-block cancellation exposed)        (outward floats -> rationals)
drive (i) deterministic refinement (roots of F^-/F^+, cqr/frontier._root), (ii) a full-support ratio stream over SEPARATOR assignments (cell ~ B_C, s uniform
in C, importance weight z(s) N_C U / B_C <= U), (iii) a fixed-candidate signed-residual stream (cell ~ a_C = N_C max_j cap_j, |R_j| <= E; cells with a_C = 0
omitted lawfully; the Z lower bound is the deterministic one or the ratio stream's own interval).
ABLATION (--bounds factorwise): identical partition, evaluator (exact integers), controller, laws and risk allocation; only the open-cell bounds are the OLD
factorwise ones: max_C g_b -> N_{Y_b} prod_{phi in b} max_C phi (interiors free), interior query ranges [0, 1], residual cap max^old * max(c, 1 - c).
"""
import sys, os, json, time, argparse, random, resource, math
from fractions import Fraction as F
from math import prod, lcm, inf
from itertools import product as iproduct
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), os.path.join(CODE, 'cex', 'cqr')):
    if p not in sys.path: sys.path.insert(0, p)
import core                                   # shared UAI reader (cex/newarm)
import numerics as NM                         # outward enclosures of the normal-mixture boundary (cex/cqr)
from frontier import draw_categorical, dyadic_weight, _root     # exact categorical draw, predictable dyadic weights, root sweep (cex/cqr)

VERSION = 'blockres-v1 (2026-11-19 experiment)'
U53 = 2.0 ** -53


class Deadline(Exception): pass


def tnow(): return time.monotonic()


# ---------------------------------------------------------------- exact tables (numpy object arrays of Python ints)
BYTE_CAP = 192 << 20          # bound on the bytes of ONE intermediate product table (exact integers): entries x card x bits / 8


class Fn:
    __slots__ = ('scope', 'arr', 'facs', 'interior', 'bits')
    def __init__(self, scope, arr, facs, interior):
        self.scope = tuple(scope); self.arr = arr; self.facs = frozenset(facs); self.interior = list(interior)
        self.bits = max((int(v).bit_length() for v in np.asarray(arr, dtype=object).reshape(-1).tolist()), default=1)


def _align(fn, union, cards): return fn.arr.reshape([cards[v] if v in fn.scope else 1 for v in union])


def _product(fns, cards):
    union = tuple(sorted(set().union(*(set(f.scope) for f in fns)))); P = None
    for f in fns:
        a = _align(f, union, cards); P = a if P is None else P * a
    return union, P


def _eliminate(bucket, v, cards):
    union, P = _product(bucket, cards); ax = union.index(v); res = P.sum(axis=ax); scope = tuple(u for u in union if u != v)
    if not scope: res = np.array(res, dtype=object).reshape(())
    return Fn(scope, res, frozenset().union(*(f.facs for f in bucket)), [u for f in bucket for u in f.interior] + [v])


def integerize(model):
    """evidence-restricted integer factors; returns (fns, const, scale, factorless multiplicity, factorless vars) -- const = 0 means ZERO_EVIDENCE"""
    cards = model['cards']; ev = model.get('evidence', {}); n = len(cards); fns = []; const = 1; scale = 1
    for k, f in enumerate(model['factors']):
        sc = tuple(f['scope']); d = lcm(*[F(v).denominator for v in f['values']]) if f['values'] else 1; scale *= d
        arr = np.array([int(F(v) * d) for v in f['values']], dtype=object).reshape([cards[v] for v in sc])
        perm = sorted(range(len(sc)), key=lambda i: sc[i]); arr = np.transpose(arr, perm); ssc = tuple(sc[i] for i in perm)
        arr = arr[tuple(ev[v] if v in ev else slice(None) for v in ssc)]; keep = tuple(v for v in ssc if v not in ev)
        if not keep: const *= int(arr); continue
        fns.append(Fn(keep, arr, [k], []))
    touched = {v for f in fns for v in f.scope}; mult = 1; factorless = []
    for v in range(n):
        if v not in ev and v not in touched: mult *= cards[v]; factorless.append(v)
    return fns, const, scale, mult, factorless


def contract(fns, cards, table_cap, deadline, stats, trace, order):
    """bounded-width partial VE (min-size greedy): eliminate the variable with the smallest resulting table while that table has <= table_cap entries.
    trace[step] = (v, live snapshot BEFORE the step) for the query-table replay; order = elimination order so far (appended)."""
    live = {i: f for i, f in enumerate(fns)}; nid = len(fns); vf = {}
    for i, f in live.items():
        for v in f.scope: vf.setdefault(v, set()).add(i)
    def nbsize(v):
        nb = set().union(*(live[i].scope for i in vf[v])) - {v}; return prod(cards[u] for u in nb) if nb else 1
    def nbbytes(v, s):
        bits = sum(live[i].bits for i in vf[v]) + cards[v].bit_length(); return s * cards[v] * (bits // 8 + 40)
    size = {v: nbsize(v) for v in vf}
    while True:
        if tnow() >= deadline: raise Deadline('contract')
        best = None
        for v, s in size.items():
            if s <= table_cap and (best is None or s < best[0]) and nbbytes(v, s) <= BYTE_CAP: best = (s, v)
        if best is None: break
        s, v = best; ids = sorted(vf[v]); bucket = [live[i] for i in ids]
        trace.append((v, [live[i] for i in sorted(live)])); order.append(v)
        new = _eliminate(bucket, v, cards)
        for i in ids:
            for u in live[i].scope: vf[u].discard(i)
            del live[i]
        del vf[v]; del size[v]; live[nid] = new
        for u in new.scope: vf[u].add(nid)
        nid += 1
        for u in new.scope: size[u] = nbsize(u)
        stats['elim_work'] += s * cards[v] * len(bucket); stats['eliminations'] += 1
    return [live[i] for i in sorted(live)]


def recover_query_table(block, x, cards, cap, trace, step_of, deadline, stats):
    """g_bx over block.scope + (x,): replay the block's own elimination from the cached prefix at x's step, with x retained (same order). None if a table would exceed cap."""
    i = step_of[x]; facs = block.facs; live = [f for f in trace[i][1] if f.facs <= facs]
    later = sorted((step_of[u] for u in block.interior if step_of[u] > i), key=int)
    for st in later:
        if tnow() >= deadline: raise Deadline('recover')
        v = trace[st][0]; bucket = [f for f in live if v in f.scope]
        if not bucket: continue
        live = [f for f in live if v not in f.scope]; nb = set().union(*(set(f.scope) for f in bucket)) - {v}
        sz = prod(cards[u] for u in nb) if nb else 1
        if sz > cap or sz * cards[v] * ((sum(f.bits for f in bucket) + cards[v].bit_length()) // 8 + 40) > BYTE_CAP: return None
        live.append(_eliminate(bucket, v, cards)); stats['query_work'] += sz * cards[v] * len(bucket)
    union, P = _product(live, cards)
    assert set(union) == set(block.scope) | {x}, (union, block.scope, x)
    return np.moveaxis(P, union.index(x), -1)


# ---------------------------------------------------------------- outward float mantissas for the ratio / residual BOUNDS (NOTE.md, Lemma N)
def _mant(arr, k):
    """(upper, lower) float arrays with arr[i] in [lower[i], upper[i]] * 2^k; exact zeros stay exactly zero in both; int -> float is correctly rounded"""
    flat = np.asarray(arr, dtype=object).reshape(-1).tolist(); z = np.array([n == 0 for n in flat], dtype=bool)
    sh = [n >> k for n in flat]                                   # floor(n / 2^k) <= n / 2^k < floor + 1 ; both fit a float (k chosen so that n >> k < 2^1000)
    lo = np.maximum(0.0, np.nextafter(np.array([float(n) for n in sh], dtype=float), -inf)); up = np.nextafter(np.array([float(n + 1) for n in sh], dtype=float), inf)
    return np.where(z, 0.0, up).reshape(arr.shape), np.where(z, 0.0, lo).reshape(arr.shape)


class Block:
    __slots__ = ('bid', 'scope', 'G', 'k', 'GU', 'GL', 'interior', 'Q', 'QU', 'QL', 'qcols', 'facs', 'NY')
    def __init__(self, bid, fn, cards):
        self.bid = bid; self.scope = fn.scope; self.G = fn.arr; self.interior = list(fn.interior); self.facs = fn.facs
        mx = max((int(v).bit_length() for v in self.G.reshape(-1).tolist()), default=1); self.k = max(0, mx - 1000)
        self.GU, self.GL = _mant(self.G, self.k); self.qcols = []; self.Q = None; self.QU = None; self.QL = None
        self.NY = prod(cards[v] for v in self.interior) if self.interior else 1
    def set_queries(self, tabs, cards):
        if not tabs: return
        cols = []; mats = []
        for x, arr in tabs:
            for v in range(cards[x]): cols.append((x, v)); mats.append(arr[..., v])
        self.Q = np.stack(mats, axis=-1); self.qcols = cols; self.QU, self.QL = _mant(self.Q, self.k)


# ---------------------------------------------------------------- separator frontier
class Cell:
    __slots__ = ('states', 'N', 'mx', 'mn', 'B', 'L', 'E', 'rlo', 'rhi', 'id', 'hkey', 'hval')


class Separator:
    def __init__(self, blocks, cards, order, queries, bounds, fac_fns, deadline, mb_cap=0):
        self.mb_cap = mb_cap; self.blocks = blocks; self.cards = cards; self.order = list(order); self.pos = {v: i for i, v in enumerate(order)}; self.queries = queries; self.bounds = bounds; self.deadline = deadline
        self.n = len(order); self.K = len(queries); self.touch = {v: [b.bid for b in blocks if v in b.scope] for v in order}
        self.qindex = {(x, v): j for j, (x, v) in enumerate(queries)}
        self.sep_cols = {}                                   # separator var -> list of query indices by state (None if not queried)
        for x in order: self.sep_cols[x] = [self.qindex.get((x, a)) for a in range(cards[x])]
        self.block_of = {}
        self.bounds_only = not queries; self.qidx = {}; self.old = {}; self.rcap = {}; self.rkey = {}; self.rtiny = {}      # PER-SEPARATOR state (blocks are shared, never mutated)
        for b in blocks:
            self.qidx[b.bid] = np.array([self.qindex[c] for c in b.qcols], dtype=int) if (b.qcols and not self.bounds_only) else None
            if not self.bounds_only:
                for ci, c in enumerate(b.qcols): self.block_of[self.qindex[c]] = (b.bid, ci)
        if bounds == 'factorwise':
            for b in blocks:                                 # original factors projected to S by max / min over their interior variables (exact ints)
                self.old[b.bid] = []
                for i in sorted(b.facs):
                    f = fac_fns[i]; keepS = tuple(v for v in f.scope if v in self.pos); axes = tuple(ai for ai, v in enumerate(f.scope) if v not in self.pos)
                    mx = f.arr.max(axis=axes) if axes else f.arr; mn = f.arr.min(axis=axes) if axes else f.arr
                    if not keepS: mx = np.array(mx, dtype=object).reshape(()); mn = np.array(mn, dtype=object).reshape(())
                    self.old[b.bid].append((keepS, mx, mn))
        self.mass = 0; self.num = np.zeros(self.K, dtype=object); self.resolved_cells = 0; self.splits = 0; self.closures = 0; self.next_id = 0; self.cell_ops = 0
        self.open = {}; root = self._cell(()); self.open[root.id] = root; self.sumB = root.B; self.sumL = root.L; self.sumE = root.E
        self.det_lo = [F(0)] * self.K; self.det_hi = [F(1)] * self.K

    def _slice(self, scope, states): return tuple(states[self.pos[v]] if self.pos[v] < len(states) else slice(None) for v in scope)

    def _block_bounds(self, b, states):
        """(max, min) of g_b over the cell as exact ints; factorwise: the old product-of-extrema bound with the interior multiplicity"""
        if self.bounds == 'block':
            g = np.asarray(b.G[self._slice(b.scope, states)], dtype=object).reshape(-1); self.cell_ops += g.size
            return int(g.max()), int(g.min())
        mx = b.NY; mn = b.NY
        for keepS, amx, amn in self.old[b.bid]:
            sl = self._slice(keepS, states); self.cell_ops += 1
            mx *= int(np.asarray(amx[sl], dtype=object).max()) if keepS else int(amx); mn *= int(np.asarray(amn[sl], dtype=object).min()) if keepS else int(amn)
        return mx, mn

    def _rho_ranges(self, b, states):
        """per query column of block b: (rho_lo, rho_hi) rational bounds of g_bx / g_b over the SUPPORT inside the cell (factorwise: [0, 1])"""
        if b.Q is None or self.bounds_only: return [], []
        Kb = len(b.qcols)
        if self.bounds == 'factorwise': return [F(0)] * Kb, [F(1)] * Kb
        sl = self._slice(b.scope, states); gu = np.asarray(b.GU[sl]).reshape(-1); gl = np.asarray(b.GL[sl]).reshape(-1); qu = np.asarray(b.QU[sl]).reshape(-1, Kb); ql = np.asarray(b.QL[sl]).reshape(-1, Kb); self.cell_ops += qu.size
        m = gu > 0
        if not m.any(): return [F(0)] * Kb, [F(0)] * Kb
        gu = gu[m]; gl = gl[m]; qu = qu[m]; ql = ql[m]
        with np.errstate(divide='ignore', invalid='ignore'):
            lo = ql / gu[:, None]; lo = np.where(np.isfinite(lo), lo, 0.0); lo = np.maximum(0.0, lo * (1 - 4 * U53)).min(axis=0)
            hi = qu / gl[:, None]; hi = np.where(np.isfinite(hi), hi, 1.0); hi = np.minimum(1.0, hi * (1 + 4 * U53) + 2 * U53).max(axis=0)
        return [F(float(x)) for x in lo], [F(float(x)) for x in hi]

    def _cell(self, states, parent=None, var=None):
        c = Cell(); c.states = states; c.id = self.next_id; self.next_id += 1; c.hkey = None; c.hval = None
        c.N = prod(self.cards[self.order[i]] for i in range(len(states), self.n))
        if parent is None:
            c.mx = []; c.mn = []; c.rlo = {}; c.rhi = {}
            for b in self.blocks:
                if tnow() >= self.deadline: raise Deadline('cell_bounds')
                mx, mn = self._block_bounds(b, states); c.mx.append(mx); c.mn.append(mn); lo, hi = self._rho_ranges(b, states); c.rlo[b.bid] = lo; c.rhi[b.bid] = hi
        else:
            c.mx = list(parent.mx); c.mn = list(parent.mn); c.rlo = dict(parent.rlo); c.rhi = dict(parent.rhi)
            for bid in self.touch[var]:
                if tnow() >= self.deadline: raise Deadline('cell_bounds')
                b = self.blocks[bid]; mx, mn = self._block_bounds(b, states); c.mx[bid] = mx; c.mn[bid] = mn; lo, hi = self._rho_ranges(b, states); c.rlo[bid] = lo; c.rhi[bid] = hi
        c.E = c.N * prod(c.mx); c.B = c.E; c.L = c.N * prod(c.mn)
        if self.mb_cap and self.bounds == 'block':
            try:
                ub = mb_bounds(self.blocks, self.cards, self.pos, states, self.order, self.mb_cap, self.deadline, True); lb = mb_bounds(self.blocks, self.cards, self.pos, states, self.order, self.mb_cap, self.deadline, False)
                if ub < c.B: c.B = ub
                if lb > c.L: c.L = lb
            except Deadline: raise
        return c

    # ---- exact contributions at a full separator assignment
    def evaluate(self, s):
        """(z, g) with g the block values at s (exact ints)"""
        g = [int(b.G[tuple(s[self.pos[v]] for v in b.scope)]) for b in self.blocks]
        return (prod(g) if g else 1), g

    def add_contrib(self, s, z, g, coef, acc):
        """acc[j] += coef * (integrated numerator_j at s) / z ... i.e. acc += coef * z * f_j(s): separator indicators get coef*z; interior columns get coef * (z / g_b) * Q_b[s_b]"""
        for x in self.order:
            j = self.sep_cols[x][s[self.pos[x]]]
            if j is not None: acc[j] += coef * z
        for b in self.blocks:
            qi = self.qidx[b.bid]
            if b.Q is None or qi is None or g[b.bid] == 0: continue
            row = b.Q[tuple(s[self.pos[v]] for v in b.scope)]; o = coef * (z // g[b.bid])
            acc[qi] += o * row

    def close(self, cid):
        """resolve a cell exactly by enumerating its separator completions (small N only)"""
        c = self.open[cid]; free = self.order[len(c.states):]; mass = 0; num = np.zeros(self.K, dtype=object)
        for tail in iproduct(*(range(self.cards[v]) for v in free)):
            if tnow() >= self.deadline: raise Deadline('close')                          # the cell stays OPEN; nothing partial is committed
            s = c.states + tail; z, g = self.evaluate(s)
            if z == 0: continue
            mass += z; self.add_contrib(s, z, g, 1, num)
        self.open.pop(cid); self.sumB -= c.B; self.sumL -= c.L; self.sumE -= c.E; self.mass += mass; self.num += num
        self.closures += 1; self.resolved_cells += 1

    def split(self, cid):
        c = self.open[cid]; var = self.order[len(c.states)]
        children = [self._cell(c.states + (a,), c, var) for a in range(self.cards[var])]        # a Deadline here leaves the parent open: the partition stays valid
        self.open.pop(cid); self.sumB -= c.B; self.sumL -= c.L; self.sumE -= c.E
        for ch in children: self.open[ch.id] = ch; self.sumB += ch.B; self.sumL += ch.L; self.sumE += ch.E
        self.splits += 1

    def Zlo(self): return F(self.mass + self.sumL)
    def Zhi(self): return F(self.mass + self.sumB)

    def query_range(self, c, j):
        x, v = self.queries[j]
        if j in self.block_of:
            bid, ci = self.block_of[j]; return c.rlo[bid][ci], c.rhi[bid][ci]
        p = self.pos[x]
        if p < len(c.states): return (F(1), F(1)) if c.states[p] == v else (F(0), F(0))
        return F(0), F(1)

    def deterministic(self, js, deadline):
        """intersect the kept deterministic intervals with the roots of F^- / F^+ for the queries js"""
        cells = list(self.open.values()); A = F(self.mass); LB = [(F(c.L), F(c.B)) for c in cells]
        for j in js:
            if tnow() >= deadline: raise Deadline('det')
            items = [LB[i] + self.query_range(c, j) for i, c in enumerate(cells)]
            a = F(int(self.num[j])); lo = _root(a, A, items, True); hi = _root(a, A, items, False)
            if lo > self.det_lo[j]: self.det_lo[j] = lo
            if hi < self.det_hi[j]: self.det_hi[j] = hi

    def epoch_tables(self, cand, key):
        """per block and epoch: Rcap_b(s_b) = max over the block's query columns of an OUTWARD float bound on |q_col(s_b) - c_col g_b(s_b)| (units 2^k_b); one pass per epoch"""
        for b in self.blocks:
            qi = self.qidx[b.bid]
            if b.Q is None or qi is None: self.rcap[b.bid] = None; self.rkey[b.bid] = key; continue
            if self.rkey.get(b.bid) == key: continue
            Kb = len(b.qcols); qu = b.QU.reshape(-1, Kb); ql = b.QL.reshape(-1, Kb); gu = b.GU.reshape(-1); gl = b.GL.reshape(-1)
            cf = np.array([float(cand[j]) for j in qi.tolist()]); clo = np.maximum(0.0, cf * (1 - 4 * U53)); chi = cf * (1 + 4 * U53)
            r = np.maximum(np.maximum(qu - clo[None, :] * gl[:, None], chi[None, :] * gu[:, None] - ql), 0.0) + 4 * U53 * (qu + gu[:, None])
            self.rcap[b.bid] = r.max(axis=1).reshape(b.G.shape); self.rkey[b.bid] = key; self.rtiny[b.bid] = 1e-9 * (float(qu.max()) + float(gu.max()))

    def residual_caps(self, c, cand, key):
        """a_C = N_C * max_j cap_j with cap_j >= max_{s in C} |z(s) (f_j(s) - c_j)|; cached per (cell, epoch). Exact zeros are decided exactly (typed), never by a tiny float."""
        if c.hkey == key: return c.hval
        self.epoch_tables(cand, key)                       # no-op when this epoch's tables exist
        best = F(0); pm = prod(c.mx)
        for x in self.order:                               # separator queries: z(s) |1{..} - c|
            for j in self.sep_cols[x]:
                if j is None: continue
                lo, hi = self.query_range(c, j); d = max(abs(lo - cand[j]), abs(hi - cand[j])); t = pm * d
                if t > best: best = t
        for b in self.blocks:
            qi = self.qidx[b.bid]
            if b.Q is None or qi is None or c.mx[b.bid] == 0: continue
            others = F(pm, c.mx[b.bid]); sl = self._slice(b.scope, c.states)
            if self.bounds == 'block':
                rc = np.asarray(self.rcap[b.bid][sl]); h = float(rc.max()); self.cell_ops += rc.size
                if h <= self.rtiny[b.bid]:                  # negligible float cap: decide EXACTLY whether the residual vanishes identically on the slice
                    G = np.asarray(b.G[sl], dtype=object).reshape(-1); Q = np.asarray(b.Q[sl], dtype=object).reshape(-1, len(b.qcols)); ex = F(0)
                    for ci, j in enumerate(qi.tolist()):
                        cj = cand[j]; d = cj.denominator; nmr = cj.numerator
                        e = max(abs(int(q) * d - nmr * int(g)) for q, g in zip(Q[:, ci].tolist(), G.tolist())); ex = max(ex, F(e, d))
                    t = ex * others; self.cell_ops += G.size * len(b.qcols)
                else: t = F(h) * (1 << b.k) * others
            else:
                t = c.mx[b.bid] * max(max(cand[j], 1 - cand[j]) for j in qi.tolist()) * others
            if t > best: best = t
        c.hkey = key; c.hval = c.N * best; return c.hval

    def residual_cap_query(self, c, j, cj):
        """inspection helper (controls): the cap of query j alone on cell c for candidate value cj (same arithmetic as residual_caps)"""
        cand = [F(0)] * self.K; cand[j] = cj; x, v = self.queries[j]
        if j not in self.block_of:
            lo, hi = self.query_range(c, j); return c.N * prod(c.mx) * max(abs(lo - cj), abs(hi - cj))
        bid, ci = self.block_of[j]; b = self.blocks[bid]; sl = self._slice(b.scope, c.states); G = np.asarray(b.G[sl], dtype=object).reshape(-1); Qc = np.asarray(b.Q[sl], dtype=object).reshape(-1, len(b.qcols))[:, ci]
        ex = max(abs(int(q) * cj.denominator - cj.numerator * int(g)) for q, g in zip(Qc.tolist(), G.tolist())); others = F(prod(c.mx), c.mx[bid]) if c.mx[bid] else F(0)
        return c.N * F(ex, cj.denominator) * others



# ---------------------------------------------------------------- mini-bucket integrated bounds on a cell (the one focused correction; Dechter & Rish style, prior art)
def mb_bounds(blocks, cards, pos, states, order, cap, deadline, upper=True):
    """integer bound on sum_{s in C} prod_b g_b(s_b): eliminate the FREE separator variables in order; a bucket whose joint scope exceeds cap is split greedily into
    mini-buckets; one mini-bucket is summed over v, the others are max-ed (upper) / min-ed (lower). Exact when no split happens."""
    fns = []
    for b in blocks:
        sl = tuple(states[pos[v]] if pos[v] < len(states) else slice(None) for v in b.scope); arr = np.asarray(b.G[sl], dtype=object); sc = tuple(v for v in b.scope if pos[v] >= len(states))
        fns.append((sc, arr.reshape([cards[v] for v in sc]) if sc else arr.reshape(())))
    const = 1
    for v in order[len(states):]:
        if tnow() >= deadline: raise Deadline('mb')
        bucket = [f for f in fns if v in f[0]]; fns = [f for f in fns if v not in f[0]]
        if not bucket: const *= cards[v]; continue
        bucket.sort(key=lambda f: -len(f[0])); groups = []
        for sc, arr in bucket:
            placed = False
            for g in groups:
                u = g[0] | set(sc)
                if prod(cards[x] for x in u) <= cap: g[0] = u; g[1].append((sc, arr)); placed = True; break
            if not placed: groups.append([set(sc), [(sc, arr)]])
        for gi, (u, members) in enumerate(groups):
            union = tuple(sorted(u)); P = None
            for sc, arr in members:
                a = arr.reshape([cards[x] if x in sc else 1 for x in union]); P = a if P is None else P * a
            ax = union.index(v)
            if gi == 0: R = P.sum(axis=ax)
            else: R = P.max(axis=ax) if upper else P.min(axis=ax)
            nsc = tuple(x for x in union if x != v)
            if nsc: fns.append((nsc, R))
            else: const *= int(R)
    for sc, arr in fns: const *= int(arr)
    return const

# ---------------------------------------------------------------- streams over SEPARATOR assignments
class RatioStream:
    """cell ~ B_C, s uniform in C: W = z(s) N_C U / B_C <= U. T = A + W (mean Z), Y_j = a_j + W f_j (mean N_j); Y_j - mu_j T has range width U -> V += b^2 U^2 / 4.
    alpha is the per-interval risk (K query intervals + 1 Z interval share the stream's risk by a union bound)."""
    def __init__(self, K, alpha, U_star):
        self.K = K; self.alpha = alpha; self.U_star = F(U_star); self.rho = self.U_star * self.U_star / 4; self.H = F(0); self.Hb = F(0); self.G = np.array([F(0)] * K, dtype=object); self.V = F(0); self.t = 0
    def draw(self, sep, rng):
        cells = [c for c in sep.open.values() if c.E > 0]; U = sep.sumE
        if U == 0 or not cells: return None
        c = cells[draw_categorical(rng, [F(c.E) for c in cells])]; s = c.states + tuple(rng.randrange(sep.cards[v]) for v in sep.order[len(c.states):])
        b = dyadic_weight((self.U_star / U) ** 2); z, g = sep.evaluate(s); W = F(z * c.N * U, c.E)
        assert W <= U, 'importance weight exceeds the cap (certificate defect)'
        self.t += 1; self.H += b * (sep.mass + W); self.Hb += b; self.G += b * sep.num
        if z: sep.add_contrib(s, z, g, F(b * c.N * U, c.E), self.G)
        self.V += b * b * U * U / 4; return W
    def intervals(self):
        if self.H <= 0: return None
        B = NM.boundary_upper(self.rho, self.V, self.alpha)
        return [(max(F(0), (self.G[j] - B) / self.H), min(F(1), (self.G[j] + B) / self.H)) for j in range(self.K)]
    def Z_interval(self):
        if self.Hb <= 0: return None
        B = NM.boundary_upper(self.rho, self.V, self.alpha); return max(F(0), (self.H - B) / self.Hb), (self.H + B) / self.Hb


class SignedStream:
    """fixed candidate c: cell ~ a_C, s uniform in C: R_j = z(s)(f_j(s) - c_j) N_C E / a_C, |R_j| <= E. Y_j = d_j + R_j has mean S_j = N_j - c_j Z; V += b^2 E^2"""
    def __init__(self, cand, K, alpha, E_star, epoch):
        self.cand = np.array(list(cand), dtype=object); self.K = K; self.alpha = alpha; self.E_star = F(E_star); self.rho = self.E_star * self.E_star; self.epoch = epoch; self.H = F(0); self.G = np.array([F(0)] * K, dtype=object); self.V = F(0); self.t = 0
    def draw(self, sep, rng):
        key = ('epoch', self.epoch); cells = []; E = F(0); sep.epoch_tables(self.cand, key)
        for c in sep.open.values():
            if tnow() >= sep.deadline: raise Deadline('signed_law')
            a = sep.residual_caps(c, self.cand, key)
            if a > 0: cells.append((c, a)); E += a
        if E == 0: return 'E_ZERO'
        c, a = cells[draw_categorical(rng, [a for _, a in cells])]; s = c.states + tuple(rng.randrange(sep.cards[v]) for v in sep.order[len(c.states):])
        b = dyadic_weight((self.E_star / E) ** 2); z, g = sep.evaluate(s); self.t += 1; self.H += b
        R = np.array([F(0)] * self.K, dtype=object)
        if z: sep.add_contrib(s, z, g, F(c.N * E, a), R)
        R = R - self.cand * F(z * c.N * E, a)
        assert all(abs(r) <= E for r in R.tolist()), 'signed contribution exceeds E (certificate defect)'
        self.G += b * (sep.num - self.cand * sep.mass + R); self.V += b * b * E * E; return E
    def intervals(self):
        if self.H <= 0: return None
        B = NM.boundary_upper(self.rho, self.V, self.alpha); return [((self.G[j] - B) / self.H, (self.G[j] + B) / self.H) for j in range(self.K)]


# ---------------------------------------------------------------- controller
def solve(model_path, budget, bounds='block', seed=1, table_cap=1 << 16, enum_cap=1 << 16, force_approx=False, eps=F(1, 200), delta=F(1, 10 ** 6), construct_share=0.45, cell_max=512, close_n=8, ladder=True, mb_cap=0):
    t_start = tnow(); deadline = t_start + budget; ph = {}; rng = random.Random(seed); stats = dict(elim_work=0, eliminations=0, query_work=0)
    out = dict(version=VERSION, bounds=bounds, mb_cap=mb_cap, seed=seed, budget_s=budget, table_cap=table_cap, enum_cap=enum_cap, epsilon=str(eps), delta=str(delta), phases_s=ph, mechanism={}, outcome=None, answers=None)
    t0 = tnow(); model, binding = core.read_uai(model_path); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); out['binding'] = binding; ph['read'] = tnow() - t0
    queries = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K = len(queries); qix = {q: j for j, q in enumerate(queries)}; out['K'] = K
    ans = {}
    def publish(j, lo, hi, point, g): ans[j] = dict(lo=lo, hi=hi, point=point, guarantee=g)
    failed = []
    try:
        t0 = tnow(); fns, const, scale, mult, factorless = integerize(model); ph['integerize'] = tnow() - t0
        if const == 0: out['outcome'] = 'ZERO_EVIDENCE'; return finish(out, t_start, queries, ans, failed)
        for x in factorless:
            for v in range(cards[x]): publish(qix[(x, v)], F(1, cards[x]), F(1, cards[x]), F(1, cards[x]), 'EXACT')
        # ---- construction: bounded-width partial VE with a two-level ladder
        cdead = min(deadline, t_start + construct_share * budget); t0 = tnow(); trace = []; order = []
        live = contract(fns, cards, table_cap, cdead, stats, trace, order); cap_used = table_cap
        if ladder and any(f.scope for f in live) and tnow() - t0 < (cdead - t0) / 3:
            try: live = contract(live, cards, table_cap * 4, cdead, stats, trace, order); cap_used = table_cap * 4
            except Deadline: pass                            # the first level's result stands (its functions are unchanged objects inside `trace`)
        ph['contract'] = tnow() - t0; step_of = {v: i for i, (v, _) in enumerate(trace)}
        if ph['contract'] >= cdead - t0 - 1e-9 and cap_used == table_cap: pass
        const_fns = [f for f in live if not f.scope]; live = [f for f in live if f.scope]
        for f in const_fns: const *= int(f.arr)
        if const == 0: out['outcome'] = 'ZERO_EVIDENCE'; return finish(out, t_start, queries, ans, failed)
        S = sorted({v for f in live for v in f.scope})
        out['mechanism'].update(blocks=len(live), separator_vars=len(S), eliminated_vars=len(order), table_cap_used=cap_used, elim_work=stats['elim_work'], eliminations=stats['eliminations'], const_blocks=len(const_fns), factorless=len(factorless),
                                block_scopes=sorted([len(f.scope) for f in live], reverse=True)[:12], block_table_sizes=sorted([int(f.arr.size) for f in live], reverse=True)[:12], block_interiors=sorted([len(f.interior) for f in live], reverse=True)[:12])
        blocks = [Block(i, f, cards) for i, f in enumerate(live)]; cblocks = [Block(len(blocks) + i, f, cards) for i, f in enumerate(const_fns)]
        # ---- interior query tables
        t0 = tnow(); recovered = 0; fac_fns = {next(iter(f.facs)): f for f in fns}; rdead = (cdead if not force_approx else deadline)
        # cheapest first: the replay cost of x is the work of the block's steps AFTER x's step; later-eliminated variables are cheaper
        todo = sorted(((len([u for u in b.interior if step_of[u] > step_of[x]]), b.bid, x) for b in blocks + cblocks for x in b.interior))
        tabs = {b.bid: [] for b in blocks + cblocks}; skipped = []
        for _, bid, x in todo:
            b = (blocks + cblocks)[bid]
            if tnow() >= rdead: skipped.append(x); continue
            try: r = recover_query_table(b, x, cards, cap_used * cards[x], trace, step_of, rdead, stats)
            except Deadline: skipped.append(x); continue
            if r is None: failed.append(x); continue
            tabs[bid].append((x, r)); recovered += 1
        failed += skipped
        for b in blocks + cblocks: b.set_queries(tabs[b.bid], cards)
        ph['query_tables'] = tnow() - t0; out['mechanism'].update(interior_queries_recovered=recovered, interior_queries_failed=len(failed), interior_queries_skipped_window=len(skipped), query_work=stats['query_work'], query_table_cells=int(sum(b.Q.size for b in blocks + cblocks if b.Q is not None)))
        for b in cblocks:                                    # constant blocks: exact ratios
            gb = int(b.G)
            if b.Q is None or gb == 0: continue
            for ci, (x, v) in enumerate(b.qcols): r = F(int(b.Q[ci]), gb); publish(qix[(x, v)], r, r, r, 'EXACT')
        if not blocks:
            out['outcome'] = 'EXACT' if len(ans) == K else 'PARTIAL_EXACT'; out['Z'] = str(F(const * mult, scale)); return finish(out, t_start, queries, ans, failed)
        # ---- separator order: most blocks touched first, then largest cardinality
        Sset = set(S); sorder = sorted(S, key=lambda v: (-sum(1 for b in blocks if v in b.scope), -cards[v], v))
        inter = {x for b in blocks for x in b.interior if x not in set(failed)}
        sq = [(x, v) for (x, v) in queries if x in Sset or x in inter]; qmap = {q: qix[q] for q in sq}
        t0 = tnow(); sep = Separator(blocks, cards, sorder, sq, bounds, fac_fns, deadline, mb_cap=mb_cap); ph['frontier_init'] = tnow() - t0
        root = next(iter(sep.open.values()))
        out['mechanism'].update(N_S_log2=lg(root.N), root_B_log2=lg(root.B), root_L_log2=lg(root.L), root_E_log2=lg(root.E), mb_cap=mb_cap)
        try:
            other = Separator(blocks, cards, sorder, [], 'factorwise' if bounds == 'block' else 'block', fac_fns, deadline); ro = next(iter(other.open.values()))
            out['mechanism']['root_B_other_log2'] = lg(ro.B); out['mechanism']['other_bounds'] = other.bounds
        except Exception as e: out['mechanism']['root_B_other_error'] = repr(e)
        # ---- exact separator enumeration when affordable
        if root.N <= enum_cap and not force_approx:
            t0 = tnow(); sep.close(root.id); ph['enumerate'] = tnow() - t0; Z = sep.mass
            if Z == 0: out['outcome'] = 'ZERO_EVIDENCE'; return finish(out, t_start, queries, ans, failed)
            for j, q in enumerate(sq): r = F(int(sep.num[j]), Z); publish(qmap[q], r, r, r, 'EXACT')
            out['Z'] = str(F(Z * const * mult, scale)); out['outcome'] = 'EXACT' if len(ans) == K else 'PARTIAL_EXACT'; return finish(out, t_start, queries, ans, failed)
        # ---- approximate separator inference
        Kq = len(sq); alpha_r = delta / 2 / (Kq + 1); ratio = RatioStream(Kq, alpha_r, root.E); signed = None; epoch = 0; epoch_draws = 0; epoch_len = 64
        pub = {}; det_t = tnow(); det_every = 1.0; it = 0; t_sig = t_det = t_rat = t_split = 0.0; ratio_draws = signed_draws = epochs = 0; residual_det = 0; trace_u = []
        def try_publish(iv, g):
            for j in range(Kq):
                if j in pub: continue
                lo = max(iv[j][0], sep.det_lo[j]); hi = min(iv[j][1], sep.det_hi[j])
                if hi - lo <= 2 * eps: pub[j] = (lo, hi, g)
        def refine():
            cid = max(sep.open, key=lambda i: sep.open[i].B); c = sep.open[cid]
            if c.N <= close_n: sep.close(cid)
            else: sep.split(cid)
        t0 = tnow()
        while len(sep.open) < 16 and tnow() < deadline and sep.open: refine()
        t_split += tnow() - t0
        while tnow() < deadline and len(pub) < Kq:
            it += 1
            if tnow() - det_t >= det_every:
                t0 = tnow(); det_t = t0
                unpub = [j for j in range(Kq) if j not in pub]
                if len(sep.open) * len(unpub) <= 400000: sep.deterministic(unpub, deadline); try_publish([(sep.det_lo[j], sep.det_hi[j]) for j in range(Kq)], 'DETERMINISTIC')
                iv = ratio.intervals()
                if iv is not None: try_publish(iv, 'PAC')
                zi = ratio.Z_interval(); trace_u.append(dict(t=round(tnow() - t_start, 2), open_cells=len(sep.open), Zlo_log2=lg(sep.Zlo()), Zhi_log2=lg(sep.Zhi()), U_log2=lg(sep.sumE), Zhat_log2=(lg(ratio.H / ratio.Hb) if ratio.Hb > 0 and ratio.H > 0 else None), ratio_Z_width_log2=(lg(zi[1] - zi[0]) if zi else None), ratio_draws=ratio_draws, signed_draws=signed_draws, published=len(pub)))
                t_det += tnow() - t0; det_every = max(1.0, 3 * (tnow() - t0))
            t0 = tnow(); W = ratio.draw(sep, rng); ratio_draws += 1; t_rat += tnow() - t0
            if W is None:
                if sep.sumE == 0 and sep.mass == 0: out['outcome'] = 'ZERO_EVIDENCE'; return finish(out, t_start, queries, ans, failed)
                break
            t0 = tnow()
            if signed is None and ratio.t >= 16 and len(pub) < Kq and ratio.H > 0:
                iv = ratio.intervals(); epoch += 1; epochs += 1
                cand = [min(F(1), max(F(0), (max(iv[j][0], sep.det_lo[j]) + min(iv[j][1], sep.det_hi[j])) / 2)) for j in range(Kq)]
                alpha_e = delta / (2 * epoch * (epoch + 1)) / Kq; key = ('epoch', epoch); sep.epoch_tables(cand, key); Etot = sum((sep.residual_caps(c, cand, key) for c in sep.open.values()), F(0))
                if Etot == 0:                                 # the residual is PROVABLY zero on every open cell: S_j = resolved residual exactly (deterministic residual test)
                    Z_lo = sep.Zlo()
                    for j in range(Kq):
                        if j in pub: continue
                        Sj = F(int(sep.num[j])) - cand[j] * sep.mass
                        if Z_lo > 0 and abs(Sj) <= eps * Z_lo: pub[j] = (cand[j] - eps, cand[j] + eps, 'DETERMINISTIC_RESIDUAL'); residual_det += 1
                    signed = None
                else: signed = SignedStream(cand, Kq, alpha_e, Etot, epoch); epoch_draws = 0
            if signed is not None:
                r = signed.draw(sep, rng); signed_draws += 1; epoch_draws += 1
                if r == 'E_ZERO': signed = None
                elif epoch_draws % 16 == 0:
                    iv = signed.intervals(); zi = ratio.Z_interval(); Z_lo = max(sep.Zlo(), zi[0] if zi else F(0))
                    if Z_lo > 0:
                        for j in range(Kq):
                            if j in pub: continue
                            lo, hi = iv[j]
                            if -eps * Z_lo <= lo and hi <= eps * Z_lo: pub[j] = (signed.cand[j] - eps, signed.cand[j] + eps, 'PAC_SIGNED')
                    if epoch_draws >= epoch_len * (2 ** (epoch - 1)): signed = None
            t_sig += tnow() - t0
            if it % 4 == 0 and len(sep.open) < cell_max and sep.open:
                t0 = tnow(); refine(); t_split += tnow() - t0
        iv = ratio.intervals()
        if iv is not None: try_publish(iv, 'PAC')
        for j, q in enumerate(sq):
            if j in pub: lo, hi, g = pub[j]; publish(qmap[q], lo, hi, (lo + hi) / 2, g)
        ph.update(refine_split=t_split, ratio_stream=t_rat, signed_stream=t_sig, deterministic=t_det)
        ws = sorted(float(sep.det_hi[j] - sep.det_lo[j]) for j in range(Kq))
        out['mechanism'].update(open_cells=len(sep.open), splits=sep.splits, closures=sep.closures, ratio_draws=ratio_draws, signed_draws=signed_draws, epochs=epochs, residual_det=residual_det, cell_ops=sep.cell_ops,
                                U_final_log2=lg(sep.sumE), sumB_final_log2=lg(sep.sumB), Zlo_log2=lg(sep.Zlo()), Zhi_log2=lg(sep.Zhi()), resolved_mass_frac_of_Zhi=(float(F(sep.mass) / sep.Zhi()) if sep.Zhi() > 0 else None),
                                ratio_V_log2=lg(ratio.V), Zhat_log2_DIAGNOSTIC=(lg(ratio.H / ratio.Hb) if ratio.Hb > 0 and ratio.H > 0 else None), median_ratio_width=(sorted(float(hi - lo) for lo, hi in iv)[Kq // 2] if iv else None), median_det_width=ws[Kq // 2], min_det_width=ws[0],
                                published=len(pub), published_by=_count([g for _, _, g in pub.values()]))
        out['trace'] = trace_u; out['outcome'] = 'COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL'
        return finish(out, t_start, queries, ans, failed)
    except Deadline as e:
        try:
            for j, q in enumerate(sq):                                   # certified publications made before the interrupt stand (sq / qmap / pub exist only in the approximate stage)
                if j in pub: lo, hi, g = pub[j]; publish(qmap[q], lo, hi, (lo + hi) / 2, g)
        except NameError: pass
        out['outcome'] = 'DEADLINE'; out['deadline_phase'] = str(e); return finish(out, t_start, queries, ans, failed)
    except AssertionError as e:
        out['outcome'] = 'CERTIFICATE_DEFECT'; out['error'] = str(e); return finish(out, t_start, queries, ans, failed)


def lg(x):
    """log2 of a positive rational of any size (math.log2 accepts arbitrary ints); None for x <= 0"""
    x = F(x)
    return (math.log2(x.numerator) - math.log2(x.denominator)) if x > 0 else None


def _count(xs):
    d = {}
    for x in xs: d[x] = d.get(x, 0) + 1
    return d


def finish(out, t_start, queries=None, ans=None, failed=None):
    out['wall_s'] = tnow() - t_start; out['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if queries is not None:
        rows = []
        for j, (x, v) in enumerate(queries):
            a = ans.get(j)
            rows.append(dict(var=x, state=v, lo=str(a['lo']), hi=str(a['hi']), point=str(a['point']), guarantee=a['guarantee']) if a else dict(var=x, state=v, guarantee='NOT_PUBLISHED'))
        out['answers'] = rows; out['published'] = sum(1 for r in rows if r['guarantee'] != 'NOT_PUBLISHED'); out['unrecovered_interior_vars'] = failed or []
        gs = {r['guarantee'] for r in rows}
        out['guarantee'] = 'EXACT' if gs <= {'EXACT'} else ('DETERMINISTIC' if gs <= {'EXACT', 'DETERMINISTIC', 'DETERMINISTIC_RESIDUAL'} else ('PAC' if 'NOT_PUBLISHED' not in gs else 'PARTIAL'))
        if out['outcome'] == 'COMPLETE' and out['guarantee'] == 'PARTIAL': out['outcome'] = 'DEADLINE_PARTIAL'
        ws = [float(F(r['hi']) - F(r['lo'])) for r in rows if r['guarantee'] != 'NOT_PUBLISHED']; out['max_width'] = max(ws) if ws else None
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=20.0)
    ap.add_argument('--bounds', default='block', choices=['block', 'factorwise']); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--table-cap', type=int, default=1 << 16)
    ap.add_argument('--enum-cap', type=int, default=1 << 16); ap.add_argument('--force-approx', action='store_true'); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000'); ap.add_argument('--no-ladder', action='store_true'); ap.add_argument('--mb-cap', type=int, default=0, help='mini-bucket integrated cell bounds with this table cap (0 = off); deterministic route only')
    a = ap.parse_args()
    out = solve(a.input, a.budget, bounds=a.bounds, seed=a.seed, table_cap=a.table_cap, enum_cap=a.enum_cap, force_approx=a.force_approx, eps=F(a.epsilon), delta=F(a.delta), ladder=not a.no_ladder, mb_cap=a.mb_cap)
    out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), phases={k: round(v, 3) for k, v in out['phases_s'].items()},
                                   mech={k: m.get(k) for k in ('blocks', 'separator_vars', 'eliminated_vars', 'table_cap_used', 'N_S_log2', 'root_E_log2', 'root_B_log2', 'root_B_other_log2', 'Zhat_log2_DIAGNOSTIC', 'Zlo_log2', 'Zhi_log2', 'published_by', 'median_det_width', 'median_ratio_width', 'ratio_draws', 'signed_draws', 'splits')}), default=str))


if __name__ == '__main__': main()
