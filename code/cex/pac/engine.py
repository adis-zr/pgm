"""General positive-contribution PAC engine (handoff 02/03; theory QUERY_AWARE_PAC_THEORY_2026-11-12 sections 3-8, 11).

One component (a nonnegative rational factor model over its free variables, no evidence left) is estimated as follows.
  * CUTSET + TEMPLATE (frozen generic policy, `choose_cutset`): variables are conditioned greedily, by the planner's scopes-only forecast, until the residual
    contraction of the remaining variables is forecast to fit the per-trial work target and the peak-bag memory target; every candidate evaluation is charged
    (it happens inside the run). The residual template (free scopes, elimination order) is built ONCE; per-trial lowering reuses cached converted slices.
  * PROPOSAL (`Tree`): the conditional tree of certified factor-max cell bounds (02 "General proposal with an executable envelope"): for a cell C with m_C
    completions, u_C = m_C * prod_a M_a(C) with M_a(C) the exact max of factor a over its compatible entries (exact rationals, so the child-sum inequality
    sum_s u_{C_s} <= u_C holds EXACTLY; no rounding inflation is needed). At a reached prefix the child s is drawn with probability u_{C_s}/S(C), S(C) = sum of the
    child bounds, by an UNBIASED INTEGER DRAW on the exact common-denominator weights (the implemented law IS the recorded law). q(leaf) = product of transitions;
    telescoping: q(leaf) >= u_leaf/u_root, hence B0(leaf)/q(leaf) <= u_root =: U (envelope, fixed for the stream). A prefix with S(C) = 0 ends the trial with a
    legitimate ZERO contribution (kept in the stream). U = 0 at the root is a PROOF of zero mass (every completion has a zero factor) -> deterministic ZERO_EVIDENCE.
  * TRIAL: integrated mode evaluates the leaf cell exactly/rigorously (cex.pac.contrib: compiled kernel with enclosures, or exact enumeration for tiny cells) and
    uses B0(leaf)/q, Bj(leaf)/q; point mode draws a uniform completion x inside the leaf (separate RNG stream) and uses W(x)/Q(x), Q(x) = q(leaf)/m_leaf, with
    W(x) exact. Both have W/Q <= U. All trials of one stream share A_t = 0 (no resolved region in this first pass; the theory's identities hold with A = 0).
  * CERTIFIERS (one global delta ledger: delta_range = delta/2, delta_var = delta/2; per-coordinate alpha = family delta / K over ALL stochastic coordinates of
    the job): (i) the ratio mixture certificate (theory section 4) with lambda_t = U^-2 (predictable, constant here), rho fixed before the stream, b rounded UP;
    (ii) the variance-sensitive certificate (section 8) with the predeclared dyadic lambda_l = 2^-l, omega_l = 6/(pi^2 l^2), l = 1..16, inverted as CERTIFIED
    OUTER SETS: for each (l, sign) the rejected theta-set is an open interval between the roots of a concave quadratic whose coefficients are OUTER-rounded from the
    interval-valued statistics (the rejected interval is SHRUNK by rounding the roots outward), intersected over l and signs; nonconvex results are kept as a list
    of intervals and the outer hull is published. Statistics accumulate as 128-bit outward-rounded mpfr intervals (cex.pac.rig).
  * PUBLICATION (section 11): hulls [l_j, u_j] per coordinate from whichever certifier is narrower per ROW (both are valid on their own allowances; selecting per
    row is covered because each family has its own delta); exact rational simplex feasibility (c_j in [max(l_j, u_j - eps), min(u_j, l_j + eps)], lower sum <= 1
    <= upper sum), greedy rational point, then the frozen pipeline's outward decimal publication + verify_output. Decimal rounding margin 2e-8 is reserved.
  * DEADLINE: checked before every trial and before every terminal return; an unfinished trial is abandoned (the all-prefix event covers the completed prefix);
    any failed trial (kernel typed stop) TERMINATES the stream (never an omitted sample followed by another draw); the completed prefix is then certified or refused.
Guarantee/outcome fields are separate: guarantee_type in {DETERMINISTIC, PAC, NONE}; outcome in {PUBLISHED, PROVED_ZERO_EVIDENCE, DEADLINE, MEMORY, NUMERICAL_RANGE_OR_PRECISION,
INVALID_PLAN_OR_CERTIFICATE, UNSUPPORTED_TASK_ADAPTER}."""
import sys, os, math, time, hashlib, json, random
from fractions import Fraction as F
from itertools import product
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
if HERE not in sys.path: sys.path.insert(0, HERE)
import rig, contrib
from rig import IV

# ---------------- FROZEN POLICY CONSTANTS (recorded in the freeze; never tuned after scoring)
POLICY = dict(
    work_target_units_per_trial=2 * 10 ** 6,   # planner scalar-forecast units the residual template may cost per trial (~5-15 ms at the frozen arm's 1.3e8-6.6e8 units/s: a PAC stream needs thousands of trials)
    peak_bag_rows_max=1 << 20,                 # residual peak bag (dense rows) must fit 1M doubles = 8 MB
    forced_min_cutset=1,                       # P1 (forced PAC): at least one conditioned variable so the stream is genuinely stochastic even when the whole component fits the trial target
    max_cutset=96, candidate_pool=24,          # greedy conditioning: at most 96 conditioned variables; per step the 24 variables with the largest incident factor volume are priced
    exact_leaf_max_completions=1 << 12,        # leaves with <= 4096 completions are enumerated exactly (rational) instead of calling the kernel
    variance_l_values=list(range(1, 17)),      # predeclared dyadic family members computed
    rho_rule='1/(4 U^2) in the common target scale (04_BENCHMARK_DEFAULTS confidence.rho); fixed before the stream',
    epsilon=F(1, 200), decimal_margin=F(2, 10 ** 8),
    prng='python random.Random (Mersenne Twister 19937) seeded by an int derived from the job seed string; unbiased integer draws by randrange (rejection on getrandbits); the theorem assumes ideal independent unbiased bits -- a separate assumption from seed reproducibility',
    gate_units_per_second={'support': 3.1e8, 'stream': 3.6e8, 'dag': 5.5e5},   # H1 deterministic gate: route forecast / rate <= gate_fraction * remaining budget. Rates = the MEDIAN observed in the frozen v1.4 campaigns per route (support: median 3.1e8 forecast units/s over 13 completed components, range 1.3e8-6.6e8; stream: 3.6e8 (DBN); dag: BARLEY 5.52e7 forecast completed in ~99 s at 120 s) -- prior information only, frozen before scoring; a wrong estimate costs the budget, never correctness
    gate_fraction=0.85,
    ablation_cutset_time_cap=None)             # A0/A1: the cutset selection runs WITHOUT a selection time cap (deterministic given the model) so both arms share the same law; the overall deadline still applies


class EngineStop(Exception):
    def __init__(self, outcome, reason, stats=None):
        super().__init__('%s: %s' % (outcome, reason)); self.outcome = outcome; self.reason = reason; self.stats = dict(stats or {})


def seed_int(*parts):
    return int.from_bytes(hashlib.sha256('\x1f'.join(str(p) for p in parts).encode()).digest()[:16], 'big')


# ---------------- cutset selection (scopes + forecasts only)
def choose_cutset(model, deadline=None, policy=POLICY, budget_fraction=0.1):
    if budget_fraction is None: deadline = None                        # deterministic selection (ablation arms): no selection time cap; the caller's overall deadline is checked after selection
    """FROZEN generic policy (scopes + planner forecasts only): condition greedily on the free variable with the largest total volume of incident multi-variable
    factors (after removing already conditioned variables), repricing the residual with the frozen planner after every step, until the residual forecast fits the
    per-trial work target and the peak bag fits the memory target, or the cutset cap / the selection time cap (10 % of the remaining budget) is reached. Every
    pricing is charged; a planner timeout is a typed DEADLINE."""
    import planning
    cards = model['cards']; n = len(cards); cut = []; trace = []; t0 = time.monotonic()
    cap_t = None if deadline is None else t0 + budget_fraction * max(0.0, deadline - t0)
    def residual(cutset):
        cs = set(cutset); free = [v for v in range(n) if v not in cs]
        if not free: return [], dict(scalar_forecast=0, peak_bag=0)
        idx = {v: i for i, v in enumerate(free)}; rm = dict(cards=[cards[v] for v in free], factors=[dict(scope=tuple(idx[v] for v in f['scope'] if v not in cs), values=None) for f in model['factors'] if any(v not in cs for v in f['scope'])])
        try: order, st = planning.order_and_price(rm, deadline=cap_t)
        except TimeoutError: return None, None                         # the pricing straddled the selection cap: the caller keeps the last priced cutset
        return [free[i] for i in order], st
    order, st = residual(cut)
    if order is None: raise EngineStop('DEADLINE', 'cutset selection: pricing the full component exceeded the selection time cap')
    trace.append(dict(step=0, forecast=st['scalar_forecast'], peak_bag=st['peak_bag'])); stopped = None
    while (st['scalar_forecast'] > policy['work_target_units_per_trial'] or st['peak_bag'] > policy['peak_bag_rows_max']) and len(cut) < policy['max_cutset']:
        if cap_t is not None and time.monotonic() >= cap_t: stopped = 'selection time cap'; break
        cs = set(cut); vol = {}
        for f in model['factors']:
            vv = [v for v in f['scope'] if v not in cs]
            if len(vv) >= 2:
                w = math.prod(cards[v] for v in vv)
                for v in vv: vol[v] = vol.get(v, 0) + w
        if not vol: break
        batch = max(1, len(cut) // 4)                                   # geometric batching: O(log n) repricings
        picks = sorted(vol, key=lambda u: (-vol[u], u))[:min(batch, policy['max_cutset'] - len(cut))]
        order2, st2 = residual(cut + picks)
        if order2 is None: stopped = 'selection time cap (pricing)'; break
        cut += picks; order, st = order2, st2; trace.append(dict(step=len(cut), chosen=picks[:4], batch=len(picks), forecast=st['scalar_forecast'], peak_bag=st['peak_bag']))
    return dict(cutset=cut, order=order, residual_forecast=st['scalar_forecast'], residual_peak_bag=st['peak_bag'], trace=trace[-8:], steps=len(trace), stopped=stopped, selection_s=time.monotonic() - t0, fits=(st['scalar_forecast'] <= policy['work_target_units_per_trial'] and st['peak_bag'] <= policy['peak_bag_rows_max']))


# ---------------- the proposal tree of factor-max cell bounds (exact rationals; prefix-max tables precomputed once per job)
class Tree:
    """exact factor-max envelope on partial-assignment cells of `model` (no evidence; cells assign cutset variables in the fixed cutset order).
    For factor a with cutset-scope variables c_1..c_k (in cutset order) the table levels_a[i] holds, for every assignment of c_1..c_i, the EXACT maximum of the
    factor over all compatible entries (free scope variables and c_{i+1}..c_k unassigned). Child-sum inequality holds exactly (no rounding anywhere)."""
    def __init__(self, model, cutset, deadline=None):
        import numpy as np
        self.m = model; self.cards = model['cards']; self.n = len(self.cards); self.cut = list(cutset); self.pos = {v: i for i, v in enumerate(self.cut)}
        self.factors = [(tuple(f['scope']), f['values']) for f in model['factors']]
        self.free_count = math.prod(self.cards[v] for v in range(self.n) if v not in self.pos)
        self.levels = []; self.cut_scope = []; self.touch = {v: [] for v in self.cut}
        for a, (sc, vals) in enumerate(self.factors):
            if deadline is not None and a % 16 == 0 and time.monotonic() >= deadline: raise EngineStop('DEADLINE', 'proposal tree construction')
            arr = np.empty(len(vals), dtype=object)
            for i, w in enumerate(vals): arr[i] = w if isinstance(w, F) else F(w)
            arr = arr.reshape([self.cards[v] for v in sc]) if sc else arr.reshape(())
            cs = sorted([v for v in sc if v in self.pos], key=lambda v: self.pos[v]); fr = [v for v in sc if v not in self.pos]
            perm = [sc.index(v) for v in cs] + [sc.index(v) for v in fr]; arr = arr.transpose(perm) if sc else arr
            top = arr
            for _ in fr: top = top.max(axis=-1)                      # exact max over the free scope variables -> array over the cutset scope vars
            top = np.asarray(top, dtype=object)                       # 0-d or k-d object array over the cutset-scope variables (cutset order)
            D = 1
            for x in arr.reshape(-1): D = D * x.denominator // math.gcd(D, x.denominator)     # common denominator of ALL entries of factor a (the maxima are entries, so they divide it too)
            assert all((x * D).denominator == 1 for x in arr.reshape(-1))
            topi = np.vectorize(lambda x: int(x * D), otypes=[object])(top) if top.size else top        # exact integer table (common denominator D_a per factor; cancels in every transition ratio)
            levels = [None] * (len(cs) + 1); levels[len(cs)] = topi; cur = topi
            for i in range(len(cs) - 1, -1, -1): cur = np.asarray(cur.max(axis=-1), dtype=object); levels[i] = cur
            self.levels.append(levels); self.cut_scope.append(cs); self.denoms = getattr(self, 'denoms', []) + [D]
            for i, v in enumerate(cs): self.touch[v].append((a, i))
        self.root_max = [F(int(self.levels[a][0].reshape(-1)[0]), self.denoms[a]) for a in range(len(self.factors))]
        # exact integer representation of every factor's entries for fast point weights: W(x) = prod_a num_a(x) / prod_a D_a
        self.nums = []
        for a, (sc, vals) in enumerate(self.factors):
            D = self.denoms[a]; row = []
            for w in vals:
                q = (w if isinstance(w, F) else F(w)) * D; assert q.denominator == 1, 'integer table'; row.append(q.numerator)
            self.nums.append(row)
        self.Dprod = math.prod(self.denoms, start=1)
        self.u_root = self.free_count * math.prod(self.cards[v] for v in self.cut) * math.prod(self.root_max, start=F(1))
    def _child_weights(self, assign, v):
        """for the children assigning v: w_s = prod over factors touching v of M_a(prefix + s) (the untouched factors are common to all children and cancel)"""
        c = self.cards[v]; w = [1] * c
        for a, i in self.touch[v]:
            cs = self.cut_scope[a]; lv = self.levels[a][i + 1]; pre = tuple(assign[u] for u in cs[:i])
            for s_ in range(c): w[s_] *= int(lv[pre + (s_,)])
        return w
    def draw_leaf(self, rng):
        """one path from the root in cutset order; exact weighted integer draws; returns (assign, q, zero_terminal, transitions)"""
        assign = {}; q = F(1); trans = []
        for v in self.cut:
            wi = self._child_weights(assign, v); W = sum(wi)
            if W == 0: return assign, q, True, trans                       # proved zero-mass prefix: a legitimate zero trial
            k = rng.randrange(W); acc = 0
            for s_, x in enumerate(wi):
                acc += x
                if k < acc: assign[v] = s_; q *= F(x, W); trans.append((v, s_, x, W)); break
        return assign, q, False, trans
    def point_weight(self, assign_full):
        num = 1
        for (sc, _), nums in zip(self.factors, self.nums):
            i = 0
            for v in sc: i = i * self.cards[v] + assign_full[v]
            num *= nums[i]
            if num == 0: return F(0)
        return F(num, self.Dprod)


# ---------------- residual template: lowering with cached slices (reuses cex_executor.convert; hash computed once per template)
class Template:
    def __init__(self, model, cutset, order_free, dense_fill_threshold=0.25, deadline=None):
        import cex_executor as X
        self.deadline = deadline
        self.X = X; self.m = model; self.cards = model['cards']; self.n = len(self.cards); self.cut = set(cutset); self.free = [v for v in range(self.n) if v not in self.cut]
        self.idx = {v: i for i, v in enumerate(self.free)}; self.order = [self.idx[v] for v in order_free]; self.thr = dense_fill_threshold
        self.fixed_src = []; self.var_fac = []; self.cache = {}
        for a, f in enumerate(model['factors']):
            if deadline is not None and a % 16 == 0 and time.monotonic() >= deadline: raise EngineStop('DEADLINE', 'template construction')
            sc = tuple(f['scope']); cutpart = tuple(v for v in sc if v in self.cut); newsc = tuple(self.idx[v] for v in sc if v not in self.cut)
            if not cutpart:
                if newsc: self.fixed_src.append(self._lower_values(newsc, [x if isinstance(x, F) else F(x) for x in f['values']]))
                else: raise ValueError('scalar factor in a component (should have been cancelled upstream)')
            else: self.var_fac.append((a, sc, cutpart, newsc))
        self.sem = hashlib.sha256(json.dumps({'cards': self.cards, 'cutset': sorted(self.cut), 'order_free': [self.free[i] for i in self.order], 'template': 'pac-conditional-v1'}).encode()).hexdigest()
        self.tot = sum(self.cards[v] for v in self.free); self.lib = X.load(X.build(deadline))
    def _lower_values(self, newsc, data):
        """one source's plan words from exact values (dense/sparse per fill threshold; exact power-of-two scale; convert with checked labels)"""
        X = self.X; vol = len(data); nz = sum(1 for w in data if w != 0)
        if nz == 0: return None
        shift = -X.floor_log2(max(data)); lab = 0; dense = nz >= self.thr * vol
        if dense:
            dv = []
            for w in data: x, l = X.convert(w, shift); dv.append(x); lab = max(lab, l)
            return (newsc, 0, None, dv, lab, -shift)
        keys = []; dv = []
        for k, w in enumerate(data):
            if w != 0: x, l = X.convert(w, shift); keys.append(k); dv.append(x); lab = max(lab, l)
        return (newsc, 1, keys, dv, lab, -shift)
    def _np_src(self, src):
        import numpy as np
        sc, mode, keys, dv, lab, exp2 = src
        w = [len(sc)] + list(sc) + [mode, len(dv)] + (list(keys) if mode == 1 else []) + [lab, exp2]
        return np.asarray(w, dtype=np.int64), np.asarray(dv, dtype=np.float64)
    def lower(self, assign):
        """plan words + values (numpy int64 / float64 arrays) for the leaf cell `assign`; returns (words, vals, scalars, zero) with the removed exact scalars"""
        import numpy as np
        if not hasattr(self, '_fixed_np'):
            parts = [self._np_src(s_) for s_ in self.fixed_src]; self._fixed_np = (np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, np.int64), np.concatenate([p[1] for p in parts]) if parts else np.zeros(0, np.float64))
            self._head = np.asarray([self.X.PLAN_FORMAT, len(self.free)] + [self.cards[v] for v in self.free] + [len(self.free)] + self.order, dtype=np.int64)
        wparts = [self._fixed_np[0]]; vparts = [self._fixed_np[1]]; scalars = []; nsrc = len(self.fixed_src)
        for a, sc, cutpart, newsc in self.var_fac:
            key = (a, tuple(assign[v] for v in cutpart))
            if key not in self.cache:
                if self.deadline is not None and time.monotonic() >= self.deadline: raise EngineStop('DEADLINE', 'template slice construction')
                f = self.m['factors'][a]; data = []
                for t, w in zip(product(*(range(self.cards[v]) for v in sc)), f['values']):
                    if all(t[i] == assign[v] for i, v in enumerate(sc) if v in self.cut): data.append(w if isinstance(w, F) else F(w))
                if not newsc: self.cache[key] = ('scalar', data[0])
                else:
                    low = self._lower_values(newsc, data); self.cache[key] = ('src', None if low is None else self._np_src(low))
            kind, val = self.cache[key]
            if kind == 'scalar':
                if val == 0: return None, None, None, True
                scalars.append(val)
            else:
                if val is None: return None, None, None, True
                wparts.append(val[0]); vparts.append(val[1]); nsrc += 1
        words = np.concatenate([self._head, np.asarray([nsrc], dtype=np.int64)] + wparts); vals = np.concatenate(vparts) if vparts else np.zeros(1, np.float64)
        return words, vals, scalars, False


def kernel_cell(tmpl, assign, deadline, cap_bytes, rss_entry):
    """integrated leaf evaluation through the frozen kernel; returns (B0 interval, {free var: [intervals]}, counters) in the component's scale"""
    import ctypes as C, numpy as np
    X = tmpl.X; words, vals, scalars, zero = tmpl.lower(assign)
    if zero: return (F(0), F(0)), None, {}
    scale = math.prod(scalars, start=F(1)); lib = tmpl.lib; nn = len(tmpl.free); tot = tmpl.tot
    N = np.zeros(tot); NE = np.zeros(nn, np.int64); NL = np.zeros(nn, np.int64); Z = np.zeros(1); ZM = np.zeros(2, np.int64); CT = np.zeros(len(X.COUNTERS), np.uint64); RS = C.create_string_buffer(256)
    if len(vals) == 0: vals = np.zeros(1)
    kcap = max(1, cap_bytes - rss_entry - int(words.nbytes) - int(vals.nbytes) - tot * 8 - 65536)
    P = lambda a, t: a.ctypes.data_as(C.POINTER(t))
    with X._KERNEL_LOCK:
        rc = lib.cex_run(P(words, C.c_int64), len(words), P(vals, C.c_double), len(vals), kcap, float('inf') if deadline is None else deadline, tmpl.thr, P(N, C.c_double), P(NE, C.c_int64), P(NL, C.c_int64), P(Z, C.c_double), P(ZM, C.c_int64), P(CT, C.c_uint64), len(X.COUNTERS), RS, 256)
    counters = {k: int(CT[i]) for i, k in enumerate(X.COUNTERS)}
    if rc == 7: return (F(0), F(0)), None, counters
    if rc != 0: raise contrib.CellStop(X.STOPS.get(rc, 'FAULT'), RS.value.decode(errors='replace'), dict(counters=counters))
    B0 = contrib.envelope(F(float(Z[0])) * F(2) ** int(ZM[0]) * scale, int(ZM[1])); rows = {}; off = 0
    for i, v in enumerate(tmpl.free):
        c = tmpl.cards[v]; e2 = F(2) ** int(NE[i]) * scale; lab = int(NL[i]); rows[v] = [contrib.envelope(F(float(N[off + a])) * e2, lab) for a in range(c)]; off += c
    return B0, rows, counters


def exact_cell(model, assign, deadline):
    r = contrib.cell_exact(model, assign, deadline, max_completions=POLICY['exact_leaf_max_completions'])
    free = [v for v in range(len(model['cards'])) if v not in assign]
    return r['B0'], {v: r['B'][v] for v in free}, {}


# ---------------- the stream: DIMENSIONLESS statistics with rigorous float accumulation (reciprocal-envelope labels), both certifiers
U_F = F(1, 2 ** 53)
class Stream:
    """All increments are scaled by 1/U: T' = T/U in [0,1], Y'_j = Y_j/U. With lambda_t = U^-2 and rho = 1/(4 U^2) the ratio theorem reads, in these units,
    B' = sum T', C'_j = sum Y'_j, V' = n/4, rho' = 1/4, radius = b(V', alpha)/B' with b(V, alpha) = sqrt((1/4 + V) log((1/4 + V)/(alpha^2/4))).
    Each exact increment t lies in a known enclosure [lo, hi] (point mode: lo = hi = exact r/U; conditional mode: the kernel's enclosure / (U q)). The two float
    accumulators per statistic hold sum fl(lo) and sum fl(hi) (nonnegative terms, nearest rounding): with a = 1 - u, a^(n+c) sum lo <= acc_lo and acc_hi <= a^-(n+c) sum hi
    where n = number of additions and c the per-term conversion label (<= 3). The exact rational enclosure of the exact statistic is then
    [acc_lo (1 - E u), acc_hi / (1 - E u)] with E = n + c (Bernoulli), E u < 1/2 enforced. Squares and products of nonnegative enclosures: [lo lo', hi hi']."""
    def __init__(self, cards, cutset, U, delta_range_c, delta_var_c, K_total, l_values):
        import numpy as np
        self.np = np; self.cards = cards; self.n = len(cards); self.off = [0]; 
        for c in cards: self.off.append(self.off[-1] + c)
        self.tot = self.off[-1]; self.U = F(U); self.alpha_r = F(delta_range_c) / K_total; self.alpha_v = F(delta_var_c) / K_total; self.K = K_total; self.l_values = list(l_values)
        self.t = 0; self.conv_label = 3; self.positive_trials = 0; self.zero_trials = 0
        z = lambda: np.zeros(self.tot); self.a_lo = z(); self.a_hi = z(); self.c_lo = z(); self.c_hi = z(); self.d_lo = z(); self.d_hi = z()
        self.b_lo = 0.0; self.b_hi = 0.0; self.e_lo = 0.0; self.e_hi = 0.0
    # ---- increments
    def add_point(self, r_over_U, idx):
        """point mode: T' = r/U exactly (one conversion), Y'_j = T' on the sampled state idx[v] of every variable, 0 elsewhere"""
        x = float(r_over_U); self.t += 1
        self.b_lo += x; self.b_hi += x; x2 = x * x; self.e_lo += x2; self.e_hi += x2
        self.a_lo[idx] += x; self.a_hi[idx] += x; self.c_lo[idx] += x2; self.c_hi[idx] += x2; self.d_lo[idx] += x2; self.d_hi[idx] += x2
        if x > 0: self.positive_trials += 1
        else: self.zero_trials += 1
    def add_zero(self):
        self.t += 1; self.zero_trials += 1
    def add_interval(self, Tlo, Thi, Ylo, Yhi):
        """conditional mode: T' in [Tlo, Thi] (floats, outer), Y'_j in [Ylo_j, Yhi_j] (numpy float arrays over all coordinates, outer; assigned states carry T')"""
        self.t += 1
        self.b_lo += Tlo; self.b_hi += Thi; self.e_lo += Tlo * Tlo; self.e_hi += Thi * Thi
        self.a_lo += Ylo; self.a_hi += Yhi; self.c_lo += Ylo * Ylo; self.c_hi += Yhi * Yhi; self.d_lo += Ylo * Tlo; self.d_hi += Yhi * Thi
        if Thi > 0: self.positive_trials += 1
        else: self.zero_trials += 1
    # ---- exact enclosures of the exact statistics
    def _enc(self, lo, hi, extra=0):
        E = self.t + self.conv_label + extra; d = E * U_F
        if d >= F(1, 2): raise EngineStop('NUMERICAL_RANGE_OR_PRECISION', 'accumulation label too large (E=%d)' % E)
        return (F(float(lo)) * (1 - d), F(float(hi)) / (1 - d))
    def range_hulls(self):
        """certificate (i) in dimensionless units: p_j in [ (C'lo - b)/B'hi , (C'hi + b)/B'lo ] with b = b(n/4, alpha_r) rounded up; needs B'lo > 0"""
        b = rig.range_boundary_up(F(1, 4), F(self.t, 4), self.alpha_r); Blo, Bhi = self._enc(self.b_lo, self.b_hi)
        if Blo <= 0: return None, b
        hulls = {}
        for v in range(self.n):
            row = []
            for s_ in range(self.cards[v]):
                j = self.off[v] + s_; Clo, Chi = self._enc(self.a_lo[j], self.a_hi[j])
                lo = (Clo - b) / Bhi if Clo - b >= 0 else (Clo - b) / Blo; hi = (Chi + b) / Blo
                row.append((max(F(0), lo), min(F(1), hi)))
            hulls[v] = row
        return hulls, b
    def variance_sets(self):
        """certificate (ii): per coordinate the accepted set [0,1] minus the union over (l, sign) of SHRUNK rejection intervals (certified outer sets)"""
        out = {}; blo, bhi = self._enc(self.b_lo, self.b_hi); elo, ehi = self._enc(self.e_lo, self.e_hi, 1)
        tests = []
        for l in self.l_values:
            lam = F(1, 2 ** l); omega_lo = F(6) / (F(98696044011, 10 ** 10) * l * l); L = rig.log_threshold_up(1, self.alpha_v, omega_lo); plo, phi = rig.psi(lam); tests.append((lam, L, plo, phi))
        for v in range(self.n):
            rows = []
            for s_ in range(self.cards[v]):
                j = self.off[v] + s_; alo, ahi = self._enc(self.a_lo[j], self.a_hi[j]); clo, chi = self._enc(self.c_lo[j], self.c_hi[j], 1); dlo, dhi = self._enc(self.d_lo[j], self.d_hi[j], 1); rejected = []
                for lam, L, plo, phi in tests:
                    for sign in (1, -1):
                        # LOWER bound of g(theta) = sign*lam*(a - theta b) - psi*(c - 2 theta d + theta^2 e) over the statistic enclosures, theta in [0,1]; rejected where g > L
                        if sign == 1: A2 = -phi * ehi; A1 = -lam * bhi + 2 * plo * dlo; A0 = lam * alo - phi * chi
                        else: A2 = -phi * ehi; A1 = lam * blo + 2 * plo * dlo; A0 = -lam * ahi - phi * chi
                        if A2 == 0:
                            if A1 == 0: continue
                            r0 = (L - A0) / A1; rejected.append((r0, F(1)) if A1 > 0 else (F(0), r0)); continue
                        rj = rig.shrunk_rejection(A2, A1, A0 - L)
                        if rj is not None: rejected.append(rj)
                rows.append(_subtract(F(0), F(1), rejected))
            out[v] = rows
        return out
    def variance_hulls(self):
        sets = self.variance_sets(); hulls = {}
        for v in range(self.n):
            hulls[v] = [((iv[0][0], iv[-1][1]) if iv else None) for iv in sets[v]]
        return hulls, sets


def _subtract(lo, hi, rejected):
    """[lo, hi] minus the union of OPEN intervals -> list of closed disjoint intervals (may be empty or nonconvex)"""
    segs = [(lo, hi)]
    for a, b in rejected:
        new = []
        for x, y in segs:
            if b <= x or a >= y: new.append((x, y)); continue
            if a > x: new.append((x, a))
            if b < y: new.append((b, y))
        segs = new
    return segs


# ---------------- publication
def feasible_point(hulls, eps):
    """hulls: list of (l_j, u_j) per state of one row; returns the exact simplex point or None (theory section 11 feasibility conditions)"""
    lows = []; ups = []
    for l, u in hulls:
        a = max(l, u - eps); b = min(u, l + eps)
        if a > b: return None
        lows.append(a); ups.append(b)
    if sum(lows) > 1 or sum(ups) < 1: return None
    pts = list(lows); left = 1 - sum(pts)
    for j in range(len(pts)):
        take = min(left, ups[j] - pts[j]); pts[j] += take; left -= take
    assert left == 0; return pts


# ---------------- one component
def run_component(comp, deadline, seed_tree, seed_point, mode, delta_range_c, delta_var_c, K_total, cap_bytes, rss_entry, policy=POLICY, trace=None, fixed_cutset=None, fixed_order=None, max_trials=None, forced=False):
    """comp: reduced component model (no evidence). Returns dict(status, hulls/points per component variable, stats). mode in {'conditional', 'point'}.
    seed_tree drives the proposal tree; seed_point the uniform completion inside the leaf (point mode). fixed_cutset/fixed_order: the matched ablation's shared law."""
    t0 = time.monotonic(); cards = comp['cards']; n = len(cards); eps = policy['epsilon']; st = dict(phase='cutset'); trace = trace if trace is not None else []
    if fixed_cutset is None:
        cs = choose_cutset(comp, deadline, policy); cut = cs['cutset']; order_free = cs['order']; st['cutset'] = cs
        if forced and not cut and n > 0 and math.prod(cards) > policy['exact_leaf_max_completions']:
            vol = {}
            for f in comp['factors']:
                w = math.prod(cards[v] for v in f['scope'])
                for v in f['scope']: vol[v] = vol.get(v, 0) + w
            v0 = max(range(n), key=lambda v: (vol.get(v, 0), -v)); cut = [v0]; order_free = [v for v in order_free if v != v0]; st['cutset']['forced_min_cutset'] = [v0]
    else:
        cut = list(fixed_cutset); order_free = list(fixed_order); st['cutset'] = dict(cutset=cut, order=order_free, fixed_by_ablation=True)
    if deadline is not None and time.monotonic() >= deadline: raise EngineStop('DEADLINE', 'after cutset selection', st)
    st['phase'] = 'tree'; tree = Tree(comp, cut, deadline); U = tree.u_root; st['U_root_log10'] = (math.log10(U.numerator) - math.log10(U.denominator)) if U > 0 else None; st['U_root_float'] = float(U) if 0 < U < F(10 ** 300) else ('inf' if U > 0 else 0.0); st['U_root_bits'] = (U.numerator.bit_length(), U.denominator.bit_length())
    if U == 0:
        return dict(status='PROVED_ZERO_EVIDENCE', guarantee='DETERMINISTIC', stats=dict(st, proof='every cell bound is zero at the root: some factor has only zero entries compatible with the root cell'))
    free_leaf = [v for v in range(n) if v not in tree.pos]
    if not cut and tree.free_count <= policy['exact_leaf_max_completions']:
        # the whole component is one exactly evaluated cell: U_t = 0 case of the theory -> deterministic answer (delta = 0), never a stochastic certificate
        r = contrib.cell_exact(comp, {}, deadline); Z0 = r['B0'][0]
        if Z0 == 0: return dict(status='PROVED_ZERO_EVIDENCE', guarantee='DETERMINISTIC', stats=dict(st, proof='exact enumeration of the component: total mass 0'))
        rows = [[(x[0] / Z0, x[0] / Z0) for x in r['B'][v]] for v in range(n)]
        return dict(status='PUBLISHED', guarantee='DETERMINISTIC', intervals=rows, points=[[lo for lo, _ in row] for row in rows], certifier_per_row=['exact'] * n, widths={}, stats=dict(st, route='exact_enumeration_full_component', trials_completed=0, wall_s=time.monotonic() - t0))
    tmpl = Template(comp, cut, order_free, deadline=deadline) if (mode == 'conditional' and free_leaf and tree.free_count > policy['exact_leaf_max_completions']) else None
    if deadline is not None and time.monotonic() >= deadline: raise EngineStop('DEADLINE', 'after template construction', st)
    st['template'] = dict(semantic=tmpl.sem if tmpl else None, free_vars=len(free_leaf), leaf_completions=tree.free_count, cutset_size=len(cut), order_free=order_free, mode=mode)
    S = Stream(cards, cut, U, delta_range_c, delta_var_c, K_total, policy['variance_l_values']); rng_t = random.Random(seed_tree); rng_p = random.Random(seed_point)
    st['conversion_note'] = 'point mode: r/U converted once (nearest, correctly rounded int/int division); conditional mode: kernel enclosure endpoints / (U q) converted (nearest) and the upper endpoint widened by 2^-50 (covers the float division rounding); accumulation label E = trials + 3 (+1 for squares)'
    st['phase'] = 'stream'; trials = 0; kernel_s = 0.0; last_check = None; publish = None; term = None; counters_tot = {}; last_cert_t = time.monotonic()
    def certify():
        rh, bU = S.range_hulls(); vh, vsets = S.variance_hulls(); rows_r = {}; rows_v = {}; chosen = {}; pts = {}; ok = True; widths = dict(range={}, variance={})
        for v in range(n):
            best = None
            for name, H in (('range', rh), ('variance', vh)):
                if H is None or H[v] is None or any(h is None for h in H[v]): continue
                w = max(hi - lo for lo, hi in H[v]); widths[name][v] = float(w)
                if w <= 2 * eps - 2 * policy['decimal_margin']:
                    p = feasible_point(H[v], eps - policy['decimal_margin'])
                    if p is not None and (best is None or w < best[0]): best = (w, name, H[v], p)
            if best is None: ok = False
            else: chosen[v] = best[1]; rows_r[v] = best[2]; pts[v] = best[3]
        return ok, rows_r, pts, chosen, widths, bU, vsets
    while True:
        if deadline is not None and time.monotonic() >= deadline: term = 'DEADLINE'; break
        if max_trials is not None and trials >= max_trials: term = 'MAX_TRIALS'; break
        if trials > 0 and ((trials & (trials - 1)) == 0 or trials % 65536 == 0 or (time.monotonic() - last_cert_t) > max(0.5, 0.1 * (deadline - time.monotonic()) if deadline else 0.5)):   # certification check at powers of two, every 65,536 trials, and at least every 10 % of the remaining budget (charged)
            tc = time.monotonic(); ok, rows, pts, chosen, widths, bU, vsets = certify(); st.setdefault('certify_s', 0.0); st['certify_s'] += time.monotonic() - tc; last_check = dict(trial=trials, widths=widths, chosen=chosen); last_cert_t = time.monotonic()
            if ok: publish = (rows, pts, chosen, widths, vsets); term = 'CERTIFIED'; break
        # ---- one trial: predictable design (tree fixed), fresh draw
        assign, q, zero_terminal, trans = tree.draw_leaf(rng_t); trials += 1
        if zero_terminal: S.add_zero(); continue
        try:
            if mode == 'point':
                full = dict(assign)
                for v in free_leaf: full[v] = rng_p.randrange(cards[v])
                w = tree.point_weight(full); r = w * tree.free_count / q          # W(x)/Q(x), Q(x) = q/m_leaf
                if r > U: raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'envelope violated (point): r = %s > U = %s' % (float(r), float(U)), st)
                S.add_point(r / U, [S.off[v] + full[v] for v in range(n)])
            else:
                tk = time.monotonic()
                if tmpl is None: B0, rows_c, ctr = exact_cell(comp, assign, deadline)
                else: B0, rows_c, ctr = kernel_cell(tmpl, assign, deadline, cap_bytes, rss_entry)
                kernel_s += time.monotonic() - tk
                for k, x in ctr.items(): counters_tot[k] = counters_tot.get(k, 0) + x
                if B0[0] > U * q * (1 + F(1, 10 ** 6)): raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'envelope violated (conditional): B0/q = %s > U = %s' % (float(B0[0] / q), float(U)), st)
                Uq = U * q; Tlo = float(B0[0] / Uq); Thi = min(1.0, float(B0[1] / Uq) * (1 + 2 ** -50))
                Ylo = S.np.zeros(S.tot); Yhi = S.np.zeros(S.tot)
                for v in range(n):
                    if v in assign: Ylo[S.off[v] + assign[v]] = Tlo; Yhi[S.off[v] + assign[v]] = Thi
                    elif rows_c is not None:
                        for s_, (lo, hi) in enumerate(rows_c[v]): j = S.off[v] + s_; Ylo[j] = float(lo / Uq); Yhi[j] = min(1.0, float(hi / Uq) * (1 + 2 ** -50))
                S.add_interval(Tlo, Thi, Ylo, Yhi)
        except contrib.CellStop as e:
            term = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'RANGE': 'NUMERICAL_RANGE_OR_PRECISION', 'REPRESENTATION': 'MEMORY'}.get(e.kind, 'INVALID_PLAN_OR_CERTIFICATE'); st['trial_failure'] = dict(trial=trials, kind=e.kind, reason=e.reason[:200]); trials -= 1; break   # the unfinished trial is abandoned; the stream ENDS here
        except EngineStop as e:
            if e.outcome == 'DEADLINE': term = 'DEADLINE'; trials -= 1; break
            raise
    # ---- terminal: certify the completed prefix (unless already certified)
    if publish is None and S.t > 0 and term != 'CERTIFIED':
        tc = time.monotonic(); ok, rows, pts, chosen, widths, bU, vsets = certify(); st['certify_s'] = st.get('certify_s', 0.0) + time.monotonic() - tc; last_check = dict(trial=S.t, widths=widths, chosen=chosen)
        if ok: publish = (rows, pts, chosen, widths, vsets)
    st['Z_estimate_over_U'] = (float(S.b_lo) / S.t) if S.t else None; st['trials_per_second'] = (S.t / max(1e-9, time.monotonic() - t0))
    st.update(trials_completed=S.t, positive_trials=S.positive_trials, zero_trials=S.zero_trials, kernel_s=kernel_s, counters=counters_tot, terminal=term, last_check=last_check, wall_s=time.monotonic() - t0, lambda_rule='U^-2 (constant: U fixed for the stream); statistics kept dimensionless (T/U, Y/U) so rho = 1/4 and V = n/4 in those units', alpha_range=str(S.alpha_r), alpha_variance=str(S.alpha_v), K_total=K_total)
    if publish is None:
        if S.positive_trials == 0 and S.t > 0: st['note'] = 'no positive sample observed; NOT a zero-evidence claim'
        return dict(status=term if term not in ('CERTIFIED', 'MAX_TRIALS', None) else 'TOO_WIDE', guarantee='NONE', stats=st)
    rows, pts, chosen, widths, vsets = publish
    return dict(status='PUBLISHED', guarantee='PAC', intervals=[rows[v] for v in range(n)], points=[pts[v] for v in range(n)], certifier_per_row=[chosen[v] for v in range(n)], widths=widths, variance_sets_nonconvex=[[len(vsets[v][s]) > 1 for s in range(cards[v])] for v in range(n)], stats=st)
