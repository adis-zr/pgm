"""ONE PARTITION for exact work and sampling (manuscript §4-§6; distribution_algorithm.txt; algorithm_referee.txt).
Cells are partial assignments of the COMPILED variables. Three typed bounds per open cell (never exchanged):
  L_C <= b_C <= B_C (integrated mass), E_C (pointwise proposal cap: w(x)/s_C(x) <= E_C with s_C uniform on the N_C completions => E_C = N_C prod max_a),
  [l_Cj, u_Cj] (POINTWISE query range on the cell; ratio queries carry the range of h - c g per candidate from pointwise ranges of h and g).
Resolved cells: exact b_C, n_Cj (and d_Cj for ratio denominators). Deterministic query bounds = roots of F^-/F^+ (§5). Ratio stream (§6.1) and fixed-candidate signed
residual stream (§6.2) with record-before-resolve, one draw in flight, predictable weights b_t = (U*/U_t)^2, rho = U*^2/4 (ratio) / (E*/E_t)^2, rho = E*^2 (signed).
All statistics are exact Fractions; the transcendental boundary is enclosed outward (numerics.boundary_upper)."""
import random, sys
from fractions import Fraction as F
sys.set_int_max_str_digits(0)
from itertools import product
from math import prod
import numerics as NM
from math import lcm, gcd

FRONTIER_VERSION = 'cqr-frontier-v1.4 (2026-11-17: the split order is a VALIDATED permutation of the compiled variables (duplicate / missing / out-of-range / non-integer orders are refused at construction); split / carve premises enforced structurally; a ratio draw charges every query lookup)'
FRONTIER_ORDER_POLICY = 'canonical'          # the REGISTERED producer policy: the split order is the identity permutation of the compiled variables (solve.py constructs it; checker.py binds a certificate to it)


class FrontierStructureError(ValueError):
    """a frontier operation would break the partition (eighth review, CQR-R7-01): an order that is not a permutation of the compiled variables, a cell whose prefix is not a prefix
    of the order, a split on an already assigned variable. Typed: internal callers cannot silently build overlapping cells; the checker turns it into a refusal"""


def canonical_order(n): return list(range(n))


def order_problem(order, n):
    """None if `order` is a permutation of range(n) given as a list / tuple of Python ints (bool excluded); otherwise the reason (the data-boundary validation of CQR-R7-01)"""
    if not isinstance(order, (list, tuple)): return 'order is not a sequence (%s)' % type(order).__name__
    if len(order) != n: return 'order has %d entries for %d compiled variables' % (len(order), n)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in order): return 'order contains a non-integer entry'
    if any(not (0 <= v < n) for v in order): return 'order contains an out-of-range variable index'
    if len(set(order)) != n:
        dup = sorted({v for v in order if order.count(v) > 1}); return 'order repeats variable(s) %s (not a permutation: cells would overlap)' % dup[:6]
    return None


def draw_categorical(rng, weights):
    """UNBIASED exact draw of an index with probability weights[i] / sum: scale the rationals to integers (lcm of denominators) and use randrange (getrandbits with rejection)"""
    D = 1
    for w in weights: D = lcm(D, w.denominator)
    ints = [int(w * D) for w in weights]; g = 0
    for x in ints: g = gcd(g, x)
    if g > 1: ints = [x // g for x in ints]                        # reduced integer weights: the draw is PATH-INVARIANT under any positive rational rescaling of all weights
    tot = sum(ints); pick = rng.randrange(tot); acc = 0
    for i, wi in enumerate(ints):
        acc += wi
        if pick < acc: return i
    return len(ints) - 1


def dyadic_weight(x):
    """the largest power of two <= x (x > 0): a PREDICTABLE positive weight (any positive predictable b_t is valid; dyadic weights bound the bit growth of the statistics)"""
    x = F(x); e = x.numerator.bit_length() - x.denominator.bit_length()
    w = F(1 << e) if e >= 0 else F(1, 1 << -e)
    while w > x: w /= 2
    while 2 * w <= x: w *= 2
    return w


class Cell:
    """a PREFIX cell: the first `depth` variables of the fixed split order are assigned `states`; every split / carve extends the prefix, so the partition is a prefix
    tree (compact; the dict view is built on demand). pm / pn = products of the per-view integer maxima / minima (E = N pm, L = N pn)."""
    __slots__ = ('states', 'N', 'E', 'L', 'B', 'qlo', 'qhi', 'id', 'pm', 'pn', '_fr', 'hkey', 'hval')
    def __init__(self, states, N, E, L, B, qlo, qhi, cid, pm, pn, fr): self.states, self.N, self.E, self.L, self.B, self.qlo, self.qhi, self.id, self.pm, self.pn, self._fr = states, N, E, L, B, qlo, qhi, cid, pm, pn, fr; self.hkey = None; self.hval = None
    @property
    def assign(self): return {self._fr.order[i]: s for i, s in enumerate(self.states)}
    @property
    def depth(self): return len(self.states)


class Frontier:
    def __init__(self, cards, views, queries, work, order=None):
        self.cards = list(cards); self.views = views; self.queries = queries; self.work = work; self.n = len(cards); self.service = None        # service(op): controller hook ticked inside bounded scans (second review R3)
        pb = order_problem(order, self.n) if order is not None else None
        if pb: raise FrontierStructureError('frontier order refused: ' + pb)
        self.order = list(order) if order is not None else canonical_order(self.n)      # fixed structural split order: a VALIDATED permutation (the producer uses the canonical one)
        for v in views: v.refresh()
        for q in queries:
            for v in ([q['f']] if q['kind'] == 'expectation' else [q['h'], q['g']]): v.refresh()
        # INTEGER WEIGHT UNITS: w_int(x) = prod_a ivals_a(x) = w(x) * scale_den (scale_den = prod of the table denominators; recorded; cancels in every ratio; the
        # normalizer contract converts explicitly). Query j is integerized with qden_j (lcm over its tables): f = f_int / qden_j (one qden for h and g of a ratio query).
        self.scale_den = 1
        for v in views: self.scale_den *= v.den
        self.qden = []
        for q in queries:
            if q['kind'] == 'expectation': self.qden.append(q['f'].den)
            else:
                d = lcm(q['h'].den, q['g'].den); self.qden.append(d)
        self.mass_i = 0; self.num_i = [0] * len(queries); self.den_i = [0] * len(queries); self.resolved_cells = 0; self.resolved_ids = set()
        self.touch = {v: [i for i, vw in enumerate(views) if v in vw.scope] for v in range(self.n)}          # views whose extrema can change when v is assigned
        self.qtouch = {v: [j for j, q in enumerate(queries) if v in (set(q['f'].scope) if q['kind'] == 'expectation' else set(q['h'].scope) | set(q['g'].scope))] for v in range(self.n)}
        self.next_id = 0; root = self._make_cell({}); self.open = {root.id: root}; self.splits = 0; self.closures = 0; self.history = []
        self.sumE = root.E; self.sumL = root.L; self.sumB = root.B            # incremental aggregates over the open cells (updated by split / close / prune)
        self.det_lo = [F(0)] * len(queries); self.det_hi = [F(1)] * len(queries)          # kept intersection of every proved deterministic interval
        self.undefined = [False] * len(queries)

    # ---- cell construction (universal bounds (3))
    def _make_cell(self, assign, parent=None, var=None):
        """universal bounds (3). parent given: only the views / queries touching `var` are rescanned; untouched extrema are inherited exactly (same cell restriction on them)"""
        d = len(assign)
        if any(self.order[i] not in assign for i in range(d)): raise FrontierStructureError('cell prefix %s is not a prefix of the split order' % sorted(assign)[:8])       # a prefix cell assigns EXACTLY the first d variables of the order
        states = tuple(assign[self.order[i]] for i in range(d))
        free_n = self.n - len(states); N = 1
        for i in range(len(states), self.n): N *= self.cards[self.order[i]]
        svc = self.service
        if parent is None:
            pm = 1; pn = 1
            for k_, v in enumerate(self.views):
                if svc is not None and (k_ & 255) == 255: svc('cell_bounds')               # controller service (incl. the wall deadline) inside the root cell's full scan (CQR-S1-05)
                lo, hi = v.extrema_i(self.cards, assign, self.work); pm *= hi; pn *= lo
            qlo = []; qhi = []
            for q in self.queries:
                if q['kind'] == 'expectation': lo, hi = q['f'].extrema(self.cards, assign, self.work); qlo.append((lo,)); qhi.append((hi,))
                else: hl, hh = q['h'].extrema(self.cards, assign, self.work); gl, gh = q['g'].extrema(self.cards, assign, self.work); qlo.append((hl, gl)); qhi.append((hh, gh))
        else:
            pm = parent.pm; pn = parent.pn; passign = parent.assign
            for k_, i in enumerate(self.touch[var]):
                if svc is not None and (k_ & 255) == 255: svc('cell_bounds')
                v = self.views[i]; plo, phi = v.extrema_i(self.cards, passign, self.work); clo, chi = v.extrema_i(self.cards, assign, self.work)
                pm = (pm // phi) * chi if phi else 0                      # phi == 0 => the parent cap is 0 (the child is pruned below)
                if pn: pn = (pn // plo) * clo                             # parent minima all positive: exact division
            if parent.pn == 0:                                            # some parent minimum was 0: recompute the product of child minima from scratch (exact)
                pn = 1
                for v in self.views:
                    pn *= v.extrema_i(self.cards, assign, self.work)[0]
                    if not pn: break
            qlo = list(parent.qlo); qhi = list(parent.qhi)
            for j in self.qtouch[var]:
                q = self.queries[j]
                if q['kind'] == 'expectation': lo, hi = q['f'].extrema(self.cards, assign, self.work); qlo[j] = (max(lo, parent.qlo[j][0]),); qhi[j] = (min(hi, parent.qhi[j][0]),)
                else: hl, hh = q['h'].extrema(self.cards, assign, self.work); gl, gh = q['g'].extrema(self.cards, assign, self.work); qlo[j] = (max(hl, parent.qlo[j][0]), max(gl, parent.qlo[j][1])); qhi[j] = (min(hh, parent.qhi[j][0]), min(gh, parent.qhi[j][1]))
        E = F(N * pm); L = F(N * pn); B = E
        c = Cell(states, N, E, L, B, tuple(qlo), tuple(qhi), self.next_id, pm, pn, self); self.next_id += 1; self.work.cells += 1
        return c

    # ---- resolved totals as exact Fractions in integer weight units (mass) and query units (numerators / denominators = sum w_int f)
    @property
    def resolved_mass(self): return F(self.mass_i)
    @property
    def resolved_num(self): return [F(self.num_i[j], self.qden[j]) for j in range(len(self.queries))]
    @property
    def resolved_den(self): return [F(self.den_i[j], self.qden[j]) for j in range(len(self.queries))]

    # ---- aggregates (incremental; one unit each)
    def U(self): self.work.cells += 1; return self.sumE
    def Zlo(self): self.work.cells += 1; return F(self.mass_i) + self.sumL
    def Zhi(self): self.work.cells += 1; return F(self.mass_i) + self.sumB

    # ---- progress operations
    def split(self, cid):
        c = self.open.pop(cid)
        if c.depth >= self.n: self.open[cid] = c; return self.close(cid)
        var = self.order[c.depth]; kids = []; passign = c.assign
        if var in passign or len(passign) != c.depth: raise FrontierStructureError('split of cell %d on variable %d which its prefix already assigns' % (cid, var))      # premise: the child extends the parent by ONE new variable
        self.sumE -= c.E; self.sumL -= c.L; self.sumB -= c.B
        for s in range(self.cards[var]):
            a = dict(passign); a[var] = s; k = self._make_cell(a, parent=c, var=var)
            if k.depth != c.depth + 1 or k.states[:c.depth] != c.states: raise FrontierStructureError('child of cell %d does not extend its parent by one variable' % cid)
            if k.B == 0: self.history.append(dict(op='prune_zero', cell=k.id, parent=cid)); continue
            self.open[k.id] = k; kids.append(k.id); self.sumE += k.E; self.sumL += k.L; self.sumB += k.B
        self.splits += 1; self.history.append(dict(op='split', cell=cid, var=var, children=kids)); return kids

    def close(self, cid):
        """exact closure by enumeration of the cell's completions (charged per evaluation); returns the exact (b, n_j, d_j)"""
        c = self.open[cid]; free = self.order[c.depth:]; b = 0; K = len(self.queries); nj = [0] * K; dj = [0] * K
        x = dict(c.assign); views = self.views; cards = self.cards; qs = self.queries; qd = self.qden; ent = 0; pend = 0; svc = self.service; ROOM = 1024
        if svc is not None and c.N > 4096: svc('enter:frontier_close')
        # the enumeration is charged per unit (one view lookup / one query lookup = an entry; one assignment = an evaluation) and SERVICED as soon as ROOM units are pending
        # (fourth review, CQR-R3-04: the service interval is bounded in charged units, every unit kind counted); nothing is mutated before the scan completes, so a stop inside
        # it leaves the frontier unchanged (the entries pending at the stop are charged first)
        def post(k, ev=0):
            nonlocal ent, pend
            ent += k; pend += k + ev
            if pend >= ROOM and svc is not None: k_ = ent; ent = 0; pend = 0; self.work.entries += k_; svc('frontier_close')      # charged BEFORE the service point (exactly once)
        try:
            for xs in product(*(range(cards[v]) for v in free)):
                for v, s in zip(free, xs): x[v] = s
                w = 1
                for vw in views:
                    w *= vw.at_i(cards, x); post(1)
                    if not w: break
                self.work.evals += 1; post(0, 1)
                if not w: continue
                b += w
                for j in range(K):
                    q = qs[j]                                      # each lookup is charged AFTER it completed (sixth review, CQR-R5-03); a ratio query is two lookups
                    if q['kind'] == 'expectation': nj[j] += w * q['f'].at_i(cards, x) * (qd[j] // q['f'].den); post(1)
                    else: nj[j] += w * q['h'].at_i(cards, x) * (qd[j] // q['h'].den); post(1); dj[j] += w * q['g'].at_i(cards, x) * (qd[j] // q['g'].den); post(1)
        finally: self.work.entries += ent; ent = 0           # the completed tail is charged on every exit (a stop inside the scan loses no performed work)
        self.open.pop(cid); self.sumE -= c.E; self.sumL -= c.L; self.sumB -= c.B          # the cell leaves the frontier only when its enumeration COMPLETED (an interruption inside the scan leaves the frontier unchanged)
        self._add_resolved(cid, b, nj, dj); self.closures += 1; self.history.append(dict(op='close', cell=cid, mass=str(b))); return b, nj, dj

    def _add_resolved(self, cid, b, nj, dj):
        assert cid not in self.resolved_ids, 'duplicate resolution'
        self.resolved_ids.add(cid); self.mass_i += b; self.resolved_cells += 1
        for j in range(len(self.queries)): self.num_i[j] += nj[j]; self.den_i[j] += dj[j]

    def carve_point(self, cid, x):
        """carve an evaluated full assignment x out of open cell cid: split along the unassigned variables retaining siblings; close the singleton exactly (record-first is the caller's duty)"""
        cur = cid
        while True:
            c = self.open[cur]
            if c.depth >= self.n: return self.close(cur)
            var = self.order[c.depth]; kids = self.split(cur)
            cur = next((k for k in kids if self.open[k].states[-1] == x[var]), None)
            if cur is None: return None      # the point's child was pruned (zero cap): its weight is zero; nothing to resolve

    # ---- deterministic query bounds (§5): roots of F^- / F^+ ; keeps the intersection with every previous interval
    def deterministic_bounds(self, deadline=None):
        import time as _t
        if self.service is not None: self.service('enter:deterministic_bounds')
        cells = list(self.open.values()); Zlo = self.Zlo(); self.work.ratops += len(cells) * max(1, len(self.queries)) * max(1, len(cells).bit_length())
        out = []
        rn = self.resolved_num; rd = self.resolved_den; rm = self.resolved_mass
        for j, q in enumerate(self.queries):
            if deadline is not None and (j & 7) == 7 and _t.monotonic() >= deadline: raise TimeoutError('deterministic bounds: deadline')
            if self.service is not None and j and (j * max(1, len(cells))) % 1024 < max(1, len(cells)): self.service('deterministic_bounds')
            A = rm if q['kind'] == 'expectation' else rd[j]; a = rn[j]
            if q['kind'] == 'expectation': items = [(c.L, c.B, c.qlo[j][0], c.qhi[j][0]) for c in cells]
            else:
                # denominator mass of a cell: between L_C * gl and B_C * gh; numerator between L_C*hl and B_C*hh; the ratio bound uses the relaxed independent description
                items = [(c.L * c.qlo[j][1], c.B * c.qhi[j][1], (c.qlo[j][0] / c.qhi[j][1]) if c.qhi[j][1] else F(0), (c.qhi[j][0] / c.qlo[j][1]) if c.qlo[j][1] else F(1)) for c in cells]
                items = [(l, u, min(max(lo, F(0)), F(1)), min(max(hi, F(0)), F(1))) for l, u, lo, hi in items]
            Dlo = A + sum(it[0] for it in items)
            if Dlo <= 0:
                out.append((self.det_lo[j], self.det_hi[j])); continue
            lo = _root(a, A, items, lower=True, deadline=deadline); hi = _root(a, A, items, lower=False, deadline=deadline)
            lo = max(lo, self.det_lo[j], F(0)); hi = min(hi, self.det_hi[j], F(1))
            if lo > hi: raise AssertionError('deterministic interval inconsistency (defect)')
            self.det_lo[j] = lo; self.det_hi[j] = hi; out.append((lo, hi))
        if self.service is not None: self.service('leave:deterministic_bounds')
        return out

    # ---- sampling laws
    def ratio_law(self):
        self.work.cells += len(self.open); cells = [c for c in self.open.values() if c.E > 0]; U = self.sumE
        return cells, U

    def signed_law(self, cand, key=None):
        """a_C = E_C h_C with h_C = max_j range of (f_j - c_j) [expectation] or (h_j - c_j g_j) [ratio] over the POINTWISE ranges; h_C depends only on the cell's ranges and the
        candidate: cached per cell under `key` (the epoch id; the candidate is fixed within an epoch) -- the result is identical to the uncached computation"""
        cells = []; E = F(0); K = len(self.queries); self.work.ratops += len(self.open) * (1 if key is not None else max(1, K)); n_ = 0
        for c in self.open.values():
            n_ += 1
            if self.service is not None and (n_ & 1023) == 1023: self.service('signed_law')          # controller service (incl. the wall deadline) inside the long scan (CQR-S1-05)
            if c.E == 0: continue
            if key is not None and c.hkey == key: h = c.hval
            else:
                h = F(0)
                for j, q in enumerate(self.queries):
                    cj = cand[j]
                    if q['kind'] == 'expectation':
                        lo = c.qlo[j][0]; hi = c.qhi[j][0]; d1 = lo - cj; d2 = hi - cj
                        if d1 < 0: d1 = -d1
                        if d2 < 0: d2 = -d2
                        if d1 > h: h = d1
                        if d2 > h: h = d2
                    else:
                        hl, gl = c.qlo[j]; hh, gh = c.qhi[j]
                        for d in (hl - cj * gh, hh - cj * gl, hl - cj * gl, hh - cj * gh):
                            if d < 0: d = -d
                            if d > h: h = d
                if key is not None: c.hkey = key; c.hval = h
            if h > 0: a = c.E * h; cells.append((c, a)); E += a
        return cells, E

    def draw_point(self, rng, cell):
        x = cell.assign
        for v in self.order[cell.depth:]: x[v] = rng.randrange(self.cards[v])
        return x

    def weight_and_queries(self, x):
        """(w_int as a Fraction in integer weight units, [(f_j, g_j)] exact query values)"""
        w = 1
        for vw in self.views:
            w *= vw.at_i(self.cards, x); self.work.entries += 1
            if not w: break
        self.work.evals += 1
        fq = []
        for q in self.queries:                                     # every lookup charged AFTER it completed: one per expectation query, TWO per ratio query (eighth review audit)
            if q['kind'] == 'expectation': fq.append((q['f'].at(self.cards, x), F(1))); self.work.entries += 1
            else: h = q['h'].at(self.cards, x); self.work.entries += 1; g = q['g'].at(self.cards, x); self.work.entries += 1; fq.append((h, g))
        return F(w), fq

    def record(self):
        return dict(version=FRONTIER_VERSION, scale_den=str(self.scale_den), qden=[str(d) for d in self.qden], open_cells=len(self.open), resolved_cells=self.resolved_cells, splits=self.splits, closures=self.closures, resolved_mass=str(self.resolved_mass),
                    resolved_num=[str(x) for x in self.resolved_num], resolved_den=[str(x) for x in self.resolved_den], U=str(self.U()), Zlo=str(self.Zlo()), Zhi=str(self.Zhi()),
                    open_summary=dict(count=len(self.open), max_depth=max((c.depth for c in self.open.values()), default=0)), order=self.order, order_policy=FRONTIER_ORDER_POLICY)


def _root(a, A, items, lower, deadline=None):
    """root of F^-(theta) (lower=True) or F^+(theta) on [0,1]: F(theta) = a - theta A + sum_C m_C(theta) (r_C - theta) with r_C = l_C (lower) / u_C (upper) and
    m_C = L_C if r_C >= theta else B_C (lower) / m_C = B_C if r_C >= theta else L_C (upper). Piecewise linear, strictly decreasing when the total lower mass is positive.
    O(|F| log |F|): sort the breakpoints r_C once and sweep with running intercept / slope sums (manuscript §5)."""
    # cells sorted by breakpoint ascending; left of its breakpoint a cell uses its 'high-side' mass (L for lower, B for upper), right of it the other
    import time as _t
    rows = sorted(((it[2] if lower else it[3]), it[0], it[1]) for it in items)      # (r, L, B)
    # initial state theta <= min r: every cell uses mass_hi = (L if lower else B)
    inter = a; slope = A
    for k_, (r, L, B) in enumerate(rows):
        if deadline is not None and (k_ & 1023) == 1023 and _t.monotonic() >= deadline: raise TimeoutError('root sweep: deadline')      # interior wall check (structured review CQR-S1-05)
        m = L if lower else B; inter += m * r; slope += m
    def val(theta, inter, slope): return inter - theta * slope
    prev = F(0)
    if val(prev, inter, slope) <= 0: return F(0)
    for i, (r, L, B) in enumerate(rows):
        if deadline is not None and (i & 1023) == 1023 and _t.monotonic() >= deadline: raise TimeoutError('root sweep: deadline')
        # piece [prev, r] (clipped to [0,1]) uses the current sums
        hi = min(r, F(1))
        if hi > prev and slope > 0:
            root = inter / slope
            if prev <= root <= hi: return root
        if r >= 1: break
        # pass the breakpoint: cell switches mass
        m_old = L if lower else B; m_new = B if lower else L; inter += (m_new - m_old) * r; slope += (m_new - m_old); prev = max(prev, r)
    if slope > 0:
        root = inter / slope
        if prev <= root <= 1: return root
    return F(1) if val(F(1), inter, slope) > 0 else prev


class RatioStream:
    """§6.1 full-support stream: T_t = A_t + W_t, Y_tj = a_tj + W_t f_j(x_t) (expectation) / numerator a_h + W h and denominator a_g + W g (ratio); all-time intervals (5)"""
    def __init__(self, K, delta_ratio, U_star, rng):
        self.K = K; self.alpha = delta_ratio / max(1, K); self.U_star = F(U_star); self.rho = self.U_star * self.U_star / 4; self.rng = rng
        self.H = F(0); self.Hb = F(0); self.Hj = [F(0)] * K; self.G = [F(0)] * K; self.V = F(0); self.t = 0; self.stopped = None; self.in_flight = None; self.records = []
    def launch(self, fr):
        cells, U = fr.ratio_law()
        if U == 0 or self.stopped: return None
        chosen = cells[draw_categorical(self.rng, [c.E for c in cells])]
        x = fr.draw_point(self.rng, chosen)
        self.in_flight = dict(cell=chosen.id, E=chosen.E, N=chosen.N, U=U, A=fr.resolved_mass, a=list(fr.resolved_num), d=list(fr.resolved_den), x=x, b=dyadic_weight((self.U_star / U) ** 2))
        return self.in_flight
    def complete(self, fr, w, fq):
        s = self.in_flight; self.in_flight = None; q = s['E'] / s['U'] / s['N']; W = w / q
        assert W <= s['U'], 'importance weight exceeds the cap (certificate defect)'
        b = s['b']; self.t += 1; self.H += b * (s['A'] + W); self.Hb += b
        for j in range(self.K):
            fj, gj = fq[j]; self.G[j] += b * (s['a'][j] + W * fj); self.Hj[j] += b * ((s['A'] + W) if gj == 1 and fr.queries[j]['kind'] == 'expectation' else (s['d'][j] + W * gj))
        self.V += b * b * s['U'] * s['U'] / 4; fr.work.note_bits(self.G[0] if self.K else self.H); fr.work.ratops += 3 * self.K + 3
        self.records.append(dict(t=self.t, cell=s['cell'], U=str(s['U']), W=str(W), b=str(b), x={str(k): v for k, v in s['x'].items()}))
        return W
    def intervals(self):
        if self.H <= 0 or self.alpha <= 0: return None          # zero risk: no statistical boundary is defined (sixth review, CQR-R5-01); never a zero radius
        B = NM.boundary_upper(self.rho, self.V, self.alpha); out = []
        for j in range(self.K):
            Hj = self.Hj[j]
            if Hj <= 0: out.append((F(0), F(1))); continue
            c = self.G[j] / Hj; r = B / Hj; out.append((max(F(0), c - r), min(F(1), c + r)))
        return out
    def Z_interval(self):
        """all-time interval for Z (integer weight units): center H/Hb, radius B/Hb (T_t has conditional range width U_t => V = sum b^2 U^2 / 4)"""
        if self.Hb <= 0 or self.alpha <= 0: return None
        B = NM.boundary_upper(self.rho, self.V, self.alpha); return (max(F(0), (self.H - B) / self.Hb), (self.H + B) / self.Hb)
    def record(self): return dict(t=self.t, H=str(self.H), Hb=str(self.Hb), Hj=[str(x) for x in self.Hj], G=[str(x) for x in self.G], V=str(self.V), rho=str(self.rho), alpha=str(self.alpha), U_star=str(self.U_star), stopped=self.stopped, draws=self.records)


class SignedStream:
    """§6.2 fixed-candidate signed-residual validation epoch: Y_j = (a_j - c_j D_j) + w (f_j - c_j g_j) / (p_C s_C); all-time intervals; publish when I_tj in [-tau_j L_j, tau_j L_j]"""
    def __init__(self, cand, K, delta_e, E_star, rng, epoch):
        self.cand = list(cand); self.K = K; self.alpha = delta_e / max(1, K); self.E_star = F(E_star); self.rho = self.E_star * self.E_star; self.rng = rng; self.epoch = epoch
        self.H = F(0); self.G = [F(0)] * K; self.V = F(0); self.t = 0; self.in_flight = None; self.records = []; self.retired = None
    def launch(self, fr):
        cells, E = fr.signed_law(self.cand, key=('epoch', self.epoch))
        if E == 0: return 'E_ZERO'
        c, a = cells[draw_categorical(self.rng, [a for _, a in cells])]; x = fr.draw_point(self.rng, c)
        rn = fr.resolved_num; rd = fr.resolved_den; rm = fr.resolved_mass; d = [rn[j] - self.cand[j] * (rm if fr.queries[j]['kind'] == 'expectation' else rd[j]) for j in range(self.K)]
        self.in_flight = dict(cell=c.id, p=a / E, N=c.N, E=E, d=d, x=x, b=dyadic_weight((self.E_star / E) ** 2)); return self.in_flight
    def complete(self, fr, w, fq):
        s = self.in_flight; self.in_flight = None; b = s['b']; self.t += 1; self.H += b
        for j in range(self.K):
            fj, gj = fq[j]; R = w * (fj - self.cand[j] * gj) / (s['p'] / s['N']); assert abs(R) <= s['E'], 'signed contribution exceeds E (certificate defect)'
            self.G[j] += b * (s['d'][j] + R)
        self.V += b * b * s['E'] * s['E']; fr.work.note_bits(self.G[0] if self.K else self.H); fr.work.ratops += 3 * self.K + 3
        self.records.append(dict(t=self.t, cell=s['cell'], E=str(s['E']), b=str(b), x={str(k): v for k, v in s['x'].items()}))
    def intervals(self):
        if self.H <= 0 or self.alpha <= 0: return None          # zero risk: no statistical boundary (the E = 0 deterministic residual test is unaffected)
        B = NM.boundary_upper(self.rho, self.V, self.alpha)
        return [((self.G[j] - B) / self.H, (self.G[j] + B) / self.H) for j in range(self.K)]
    def record(self): return dict(epoch=self.epoch, candidate=[str(c) for c in self.cand], t=self.t, H=str(self.H), G=[str(x) for x in self.G], V=str(self.V), rho=str(self.rho), alpha=str(self.alpha), E_star=str(self.E_star), draws=self.records, retired=self.retired)
