"""Exact-integer block contraction (bounded-width partial variable elimination over the evidence-restricted, integerized model) and its bookkeeping, as used by
integrated.py (the frozen engine) and the control suites: Fn / integerize / contract / recover_query_table (exact integer tables, elimination trace, per-variable replay),
Block / Separator (the exact prefix-cell enumeration route for small separators: cell bounds, mass, closing), mb_bounds (mini-bucket bounds on a cell), finish (result rows).
The round 1-8 block-contraction SOLVER arms that used to live here (deterministic refinement, ratio / signed streams, the v1 mini-bucket arm, the CLI) were removed in the
21 Nov 2026 cleanup; they remain in git history (commit 03f7d76 and earlier) and their results in pgm-records rounds 1-8. See NOTE.md for the mathematics."""
import sys, os, time, resource, math
from fractions import Fraction as F
from math import prod, lcm, inf
from itertools import product as iproduct
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (os.path.join(CODE, 'cex', 'newarm'), os.path.join(CODE, 'cex', 'cqr')):
    if p not in sys.path: sys.path.insert(0, p)
import core                                   # shared UAI reader (cex/newarm): re-exported as blockres.core for integrated.py and the control suites

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
        self.mass = 0; self.num = np.zeros(self.K, dtype=object); self.resolved_cells = 0; self.splits = 0; self.closures = 0; self.next_id = 0; self.cell_ops = 0; self.witness = False     # witness: some z(s) > 0 was EVALUATED (exact fact => Z > 0)
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
        g = [int(b.G[tuple(s[self.pos[v]] for v in b.scope)]) for b in self.blocks]; z = (prod(g) if g else 1)
        if z: self.witness = True
        return z, g

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















def lg(x):
    """log2 of a positive rational of any size (math.log2 accepts arbitrary ints); None for x <= 0"""
    x = F(x)
    return (math.log2(x.numerator) - math.log2(x.denominator)) if x > 0 else None




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




