"""General positive-contribution PAC engine -- candidate v2 (repair after the adversarial review of 13 Nov 2026; theory QUERY_AWARE_PAC_THEORY_2026-11-12 §3-8, 11).

One component (a nonnegative rational factor model over its free variables, no evidence left) is estimated as follows.
  * CUTSET + TEMPLATE (frozen generic policy, `choose_cutset`): variables are conditioned greedily, by the planner's scopes-only forecast, until the residual
    contraction of the remaining variables is forecast to fit the per-trial work target and the peak-bag memory target; every candidate evaluation is charged.
    The residual template (free scopes, elimination order) is built ONCE; per-trial lowering reuses cached converted slices. A typed numerical stop raised while
    converting a source value (cex_executor.Stop RANGE) is translated into the common typed contribution stop (never a FAULT, never a dropped draw).
  * PROPOSAL (`Tree`): the conditional tree of certified factor-max cell bounds u_C = m_C prod_a M_a(C) (exact rationals; the child-sum inequality holds
    exactly). RESOLVED REGION (theory §3, §6; review F01): a leaf cell whose exact contribution enclosure has been computed is inserted ONCE into the disjoint
    resolved region D (duplicate insertion is refused); its bound u_leaf is removed from every ancestor's effective weight w(node) = u(node) - sum of resolved
    leaf bounds below it, so a resolved cell is never drawn again and the residual envelope is U_t = w(root) = U_root - sum resolved u. At a reached prefix the
    child s is drawn with probability w(C_s)/sum_s w(C_s) by an unbiased integer draw on exact common-denominator weights (the implemented law IS the recorded
    law); telescoping gives q(leaf) >= u_leaf/U_t, hence B0(leaf)/q(leaf) <= U_t and (point mode) W(x)/Q(x) <= U_t. Both inequalities are re-checked EXACTLY on
    every trial. A prefix with zero effective weight ends the trial with a legitimate ZERO residual contribution. U_t = 0 (complete cover) ends the stream: the
    answer is then DETERMINISTIC from the resolved enclosures (delta = 0); U_root = 0 is a proof of zero mass.
  * TRIAL (theory §3): T_t = A_t + r_t, Y_tj = a_tj + r_t f_j with (A_t, a_tj) the resolved totals BEFORE the trial (predictable). Integrated mode evaluates the
    leaf cell rigorously (cex.pac.contrib: compiled kernel with enclosures, or exact enumeration for tiny cells) and uses B0(leaf)/q, Bj(leaf)/q, then (if the
    stream resolves) inserts the cell into D between trials; point mode draws a uniform completion x inside the leaf (separate RNG stream) and uses W(x)/Q(x)
    with W(x) exact (no resolution: a point does not evaluate a cell). The matched ablation runs BOTH modes with resolution OFF so the residual region is held
    fixed (02 "hold a cutset, conditional tree proposal, residual region and numerical contract fixed").
  * STATISTICS: dimensionless by the FIXED predictable scale U_root (T' = T/U_root in [0,1] because A_t <= resolved bounds and r_t <= U_t; lambda_t = U_root^-2
    constant; rho = 1/(4 U_root^2)); accumulated as DIRECTED binary64 bounds (cex.pac.rig: lower sums of lower bounds, upper sums of upper bounds; no
    multiplicative error label; underflow handled by the directed neighbour rule, so a positive value is enclosed by [0, 2^-1074] rather than asserted zero).
    The exact statistics are enclosed; an enclosure too wide to certify yields a typed refusal, never an optimistic certificate.
  * CERTIFIERS (one global delta ledger per job: delta_range = delta/2, delta_var = delta/2; per-coordinate alpha = family delta / K_total over ALL coordinates
    of the job that may be sampled): (i) ratio mixture certificate (§4) with the constant predictable weight; (ii) variance-sensitive certificate (§8) with the
    predeclared dyadic lambda_l, omega_l, l = 1..16, inverted as CERTIFIED OUTER SETS: per (l, sign) the rejected theta-set is an open interval whose endpoints are
    certified by EXACT rational evaluation of the concave lower-bound quadratic (`rig.shrunk_rejection`); nonconvex accepted sets are kept as interval lists.
  * PUBLICATION (§11): hull per row from whichever certifier is narrower per ROW (each family has its own allowance), exact rational simplex feasibility,
    greedy rational point, then the frozen pipeline's outward decimal publication + verify_output. The canonical DESIGN RECORD (effective cutset / order after
    forcing, mode, exact U_root, lambda / rho rule, K, alphas, l values, resolution flag, seeds) and the SUFFICIENT STATISTICS (all directed accumulators) are
    returned for the independent re-verification of the certificate by the gate (`hulls_from_record`).
  * DEADLINE: checked before every trial and before every terminal return; an unfinished trial is abandoned (the all-prefix event covers the completed prefix);
    any failed trial (typed kernel / conversion stop) TERMINATES the stream (never an omitted sample followed by another draw).
Guarantee/outcome fields are separate: guarantee in {DETERMINISTIC, PAC, NONE}; status in {PUBLISHED, PROVED_ZERO_EVIDENCE, DEADLINE, MEMORY, NUMERICAL_RANGE_OR_PRECISION,
INVALID_PLAN_OR_CERTIFICATE, TOO_WIDE}."""
import sys, os, math, time, hashlib, json, random
from fractions import Fraction as F
from itertools import product
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)
if HERE not in sys.path: sys.path.insert(0, HERE)
import rig, contrib
ENGINE_VERSION = 'pac-engine-v4 (2026-11-13 repair 3: directed rebase of the resolved totals, deterministic-statistical intersection, replayable design)'

# ---------------- FROZEN POLICY CONSTANTS (recorded in the freeze; never tuned after scoring)
POLICY = dict(
    engine_version=ENGINE_VERSION,
    work_target_units_per_trial=2 * 10 ** 6,   # planner scalar-forecast units the residual template may cost per trial
    peak_bag_rows_max=1 << 20,                 # residual peak bag (dense rows) must fit 1M doubles = 8 MB
    forced_min_cutset=1,                       # P1 (forced PAC): at least one conditioned variable so the stream is genuinely stochastic even when the whole component fits the trial target
    max_cutset=96, candidate_pool=24,          # greedy conditioning: at most 96 conditioned variables
    exact_leaf_max_completions=1 << 12,        # leaves with <= 4096 completions are enumerated exactly (rational) instead of calling the kernel
    variance_l_values=list(range(1, 17)),      # predeclared dyadic family members computed
    rho_rule='1/(4 U_root^2): rho = 1/4 in the dimensionless units (04_BENCHMARK_DEFAULTS confidence.rho); fixed before the stream',
    lambda_rule='U_root^-2, constant predictable weight (theory §4: any positive predictable weight is valid; U_t <= U_root so V <= n/4 in dimensionless units)',
    stream_scale='U_root (fixed): T_t/U_root in [0,1]; directed binary64 accumulators (cex.pac.rig)',
    resolve_evaluated_cells=True,              # integrated mode (P1 / H1): every evaluated leaf is inserted once into the resolved region between trials
    epsilon=F(1, 200), decimal_margin=F(2, 10 ** 8),
    prng='python random.Random (Mersenne Twister 19937) seeded by an int derived from the job seed string; unbiased integer draws by randrange (rejection on getrandbits); the theorem assumes ideal independent unbiased bits -- a separate assumption from seed reproducibility',
    gate_units_per_second={'support': 3.1e8, 'stream': 3.6e8, 'dag': 5.5e5, 'forest': 1e7},   # H1 deterministic gate: route forecast / rate <= gate_fraction * remaining budget (medians observed in the frozen v1.4 campaigns; prior information only)
    gate_fraction=0.85,
    ablation_cutset_time_cap=None)


class EngineStop(Exception):
    def __init__(self, outcome, reason, stats=None):
        super().__init__('%s: %s' % (outcome, reason)); self.outcome = outcome; self.reason = reason; self.stats = dict(stats or {})


def seed_int(*parts):
    return int.from_bytes(hashlib.sha256('\x1f'.join(str(p) for p in parts).encode()).digest()[:16], 'big')


def _frac_str(x): return '%d/%d' % (x.numerator, x.denominator)


# ---------------- cutset selection (scopes + forecasts only)
def choose_cutset(model, deadline=None, policy=POLICY, budget_fraction=0.1):
    """FROZEN generic policy (scopes + planner forecasts only): condition greedily on the free variable with the largest total volume of incident multi-variable
    factors (after removing already conditioned variables), repricing the residual with the frozen planner after every step, until the residual forecast fits the
    per-trial work target and the peak bag fits the memory target, or the cutset cap / the selection time cap (10 % of the remaining budget) is reached. Every
    pricing is charged; a planner timeout is a typed DEADLINE. budget_fraction=None: deterministic selection (ablation arms), no selection time cap."""
    import planning
    if budget_fraction is None: deadline = None
    cards = model['cards']; n = len(cards); cut = []; trace = []; t0 = time.monotonic()
    cap_t = None if deadline is None else t0 + budget_fraction * max(0.0, deadline - t0)
    def residual(cutset):
        cs = set(cutset); free = [v for v in range(n) if v not in cs]
        if not free: return [], dict(scalar_forecast=0, peak_bag=0)
        idx = {v: i for i, v in enumerate(free)}; rm = dict(cards=[cards[v] for v in free], factors=[dict(scope=tuple(idx[v] for v in f['scope'] if v not in cs), values=None) for f in model['factors'] if any(v not in cs for v in f['scope'])])
        try: order, st = planning.order_and_price(rm, deadline=cap_t)
        except TimeoutError: return None, None
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
        batch = max(1, len(cut) // 4)
        picks = sorted(vol, key=lambda u: (-vol[u], u))[:min(batch, policy['max_cutset'] - len(cut))]
        order2, st2 = residual(cut + picks)
        if order2 is None: stopped = 'selection time cap (pricing)'; break
        cut += picks; order, st = order2, st2; trace.append(dict(step=len(cut), chosen=picks[:4], batch=len(picks), forecast=st['scalar_forecast'], peak_bag=st['peak_bag']))
    return dict(cutset=cut, order=order, residual_forecast=st['scalar_forecast'], residual_peak_bag=st['peak_bag'], trace=trace[-8:], steps=len(trace), stopped=stopped, selection_s=time.monotonic() - t0, fits=(st['scalar_forecast'] <= policy['work_target_units_per_trial'] and st['peak_bag'] <= policy['peak_bag_rows_max']))


# ---------------- the proposal tree of factor-max cell bounds with an EXPLICIT FRONTIER (candidate v3; review R01)
class Tree:
    """exact factor-max envelope on partial-assignment cells of `model` (no evidence; cells assign cutset variables in the fixed cutset order), with an explicit
    unresolved FRONTIER. Node = prefix (tuple of states in cutset order). Bounds: u(node) = m_node * prod_a M_a(node) (exact rationals; the child-sum inequality
    sum_s u(child_s) <= u(node) holds exactly). Effective residual bound w(node):
        leaf:            w = 0 if resolved (its exact contribution is in the resolved totals) else u(leaf)   [u(leaf) = 0 is a proved-zero leaf];
        expanded node:   w = sum over children of w(child)                                                   (children expanded or not);
        unexpanded node: w = u(node).
    Every w is a valid upper bound on the residual (unresolved) mass under the node, and w(node) <= u(node). The draw at a node uses the children's w values
    (exact unbiased integer draw on common-denominator weights); when a node is reached it is EXPANDED (its children's bounds are computed, deterministically from
    the model) and its w is refreshed. Telescoping: along a drawn path q(leaf) = prod w(child_k)/S_k with S_k = sum of the children's w <= w(parent_k), hence
    q(leaf) >= w(leaf)/w(root) = u(leaf)/U_t with U_t := w(root) (proposal domination; re-checked exactly on every trial by the engine).
    Resolution and expansion change only FUTURE trials (predictable design); historical trials keep their laws. U_t = 0 <=> no unresolved positive support
    remains (every reachable positive leaf is resolved and every reached subtree with zero children is closed) -- independent of the slack U_root - sum u(leaf).
    The frontier state is reproducible from (model, cutset, resolved leaves, expanded zero prefixes); `rebuild` lets a checker re-derive U_t."""
    def __init__(self, model, cutset, deadline=None):
        import numpy as np
        self.m = model; self.cards = model['cards']; self.n = len(self.cards); self.cut = list(cutset); self.pos = {v: i for i, v in enumerate(self.cut)}
        self.factors = [(tuple(f['scope']), f['values']) for f in model['factors']]
        self.free_count = math.prod(self.cards[v] for v in range(self.n) if v not in self.pos)
        self.levels = []; self.cut_scope = []; self.touch = {v: [] for v in self.cut}; self.denoms = []
        for a, (sc, vals) in enumerate(self.factors):
            if deadline is not None and a % 16 == 0 and time.monotonic() >= deadline: raise EngineStop('DEADLINE', 'proposal tree construction')
            arr = np.empty(len(vals), dtype=object)
            for i, w in enumerate(vals): arr[i] = w if isinstance(w, F) else F(w)
            arr = arr.reshape([self.cards[v] for v in sc]) if sc else arr.reshape(())
            cs = sorted([v for v in sc if v in self.pos], key=lambda v: self.pos[v]); fr = [v for v in sc if v not in self.pos]
            perm = [sc.index(v) for v in cs] + [sc.index(v) for v in fr]; arr = arr.transpose(perm) if sc else arr
            top = arr
            for _ in fr: top = top.max(axis=-1)
            top = np.asarray(top, dtype=object)
            D = 1
            for x in arr.reshape(-1): D = D * x.denominator // math.gcd(D, x.denominator)
            topi = np.vectorize(lambda x: int(x * D), otypes=[object])(top) if top.size else top
            levels = [None] * (len(cs) + 1); levels[len(cs)] = topi; cur = topi
            for i in range(len(cs) - 1, -1, -1): cur = np.asarray(cur.max(axis=-1), dtype=object); levels[i] = cur
            self.levels.append(levels); self.cut_scope.append(cs); self.denoms.append(D)
            for i, v in enumerate(cs): self.touch[v].append((a, i))
        self.root_max = [F(int(self.levels[a][0].reshape(-1)[0]), self.denoms[a]) for a in range(len(self.factors))]
        self.nums = []
        for a, (sc, vals) in enumerate(self.factors):
            D = self.denoms[a]; row = []
            for w in vals:
                q = (w if isinstance(w, F) else F(w)) * D; assert q.denominator == 1, 'integer table'; row.append(q.numerator)
            self.nums.append(row)
        self.Dprod = math.prod(self.denoms, start=1)
        self.u_root = F(self.free_count * math.prod(self.cards[v] for v in self.cut)) * math.prod(self.root_max, start=F(1))
        # frontier state
        self.resolved = set(); self.resolved_count = 0
        self.children = {}            # expanded node prefix -> list of (u_child, per-factor new maxima dict) per child state
        self.w = {(): self.u_root}    # effective residual bound per known node (root always present)
        self.U_t = self.u_root
    # ---- bounds
    def node_bounds(self, prefix):
        """exact (u(prefix), per-factor current maxima) by walking the stored tables along the prefix"""
        cur = {a: int(self.levels[a][0].reshape(-1)[0]) for a in range(len(self.factors))}; u = self.u_root; assign = {}
        for k, s_ in enumerate(prefix):
            v = self.cut[k]; f = F(1, self.cards[v])
            for a, i in self.touch[v]:
                lv = self.levels[a][i + 1]; pre = tuple(assign[x] for x in self.cut_scope[a][:i]); nv = int(lv[pre + (s_,)])
                if nv == 0: f = F(0); cur[a] = 0; continue
                f *= F(nv, cur[a]); cur[a] = nv
            u = u * f; assign[v] = s_
        return u, cur, assign
    def _expand(self, prefix, assign, cur, u_prefix):
        """compute the children of a node once (deterministic from the model); store; return the list of (u_child, new maxima)"""
        if prefix in self.children: return self.children[prefix]
        v = self.cut[len(prefix)]; c = self.cards[v]; kids = []
        for s_ in range(c):
            f = F(1, c); new = {}
            for a, i in self.touch[v]:
                lv = self.levels[a][i + 1]; pre = tuple(assign[x] for x in self.cut_scope[a][:i]); nv = int(lv[pre + (s_,)]); new[a] = nv
                if nv == 0: f = F(0); break
                f *= F(nv, cur[a])
            kids.append((u_prefix * f, new))
        self.children[prefix] = kids
        for s_, (us, _) in enumerate(kids):
            ch = prefix + (s_,)
            if ch not in self.w: self.w[ch] = F(0) if ch in self.resolved else us
        self._refresh(prefix)
        return kids
    def _refresh(self, prefix):
        """w(node) := sum of the children's w (node expanded); propagate to the root (U_t = w(root))"""
        kids = self.children.get(prefix)
        if kids is None: return
        total = F(0)
        for s_ in range(len(kids)): total += self.w[prefix + (s_,)]
        self.w[prefix] = total
        if prefix: self._refresh(prefix[:-1])
        else: self.U_t = total
    def child_weights(self, prefix, assign, cur, u_prefix, v):
        """effective weights w(child) of the children assigning v at the (expanded) prefix; returns (weights, [(u_child, new maxima)])"""
        kids = self._expand(prefix, assign, cur, u_prefix)
        return [self.w[prefix + (s_,)] for s_ in range(len(kids))], kids
    # ---- resolved region
    def _expand_path(self, prefix):
        """expand every node from the root to (and including, if internal) `prefix`; returns (u(prefix), maxima, assign)"""
        cur = {a: int(self.levels[a][0].reshape(-1)[0]) for a in range(len(self.factors))}; u = self.u_root; assign = {}
        for k in range(len(prefix)):
            kids = self._expand(prefix[:k], assign, cur, u); us, new = kids[prefix[k]]; u = us; cur = dict(cur); cur.update(new); assign[self.cut[k]] = prefix[k]
        if len(prefix) < len(self.cut): self._expand(prefix, assign, cur, u)
        return u, cur, assign
    def resolve(self, leaf, u_leaf):
        """insert the leaf cell (tuple of states in cutset order) into the resolved region ONCE; refuses duplicates; its ancestors are expanded and refreshed"""
        leaf = tuple(leaf)
        if leaf in self.resolved: raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'duplicate insertion of a resolved cell %s' % (leaf,))
        if len(leaf) != len(self.cut): raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'resolved cell is not a leaf of the cutset tree')
        u, cur, assign = self._expand_path(leaf)
        if u != u_leaf: raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'resolved cell bound differs from the tree bound')
        self.resolved.add(leaf); self.resolved_count += 1; self.w[leaf] = F(0)
        if leaf: self._refresh(leaf[:-1])
        else: self.U_t = F(0)
        assert self.U_t >= 0
    def draw_leaf(self, rng):
        """one path from the root in cutset order under the current frontier; exact weighted integer draws; returns (assign, q, zero_terminal, trans, u_leaf)"""
        assign = {}; q = F(1); trans = []; prefix = (); cur = {a: int(self.levels[a][0].reshape(-1)[0]) for a in range(len(self.factors))}; u = self.u_root
        for v in self.cut:
            ws, kids = self.child_weights(prefix, assign, cur, u, v)
            for w in ws: assert w >= 0, 'negative effective weight'
            D = 1
            for w in ws: D = D * w.denominator // math.gcd(D, w.denominator)
            wi = [int(w * D) for w in ws]; W = sum(wi)
            if W == 0: return assign, q, True, trans, F(0)        # a reached node with no residual support (now closed and propagated): a legitimate zero residual trial
            k = rng.randrange(W); acc = 0
            for s_, x in enumerate(wi):
                acc += x
                if k < acc:
                    assign[v] = s_; q *= F(x, W); trans.append((v, s_, x, W)); u = kids[s_][0]
                    for a, nv in kids[s_][1].items(): cur[a] = nv
                    prefix = prefix + (s_,); break
        return assign, q, False, trans, u
    def point_weight(self, assign_full):
        num = 1
        for (sc, _), nums in zip(self.factors, self.nums):
            i = 0
            for v in sc: i = i * self.cards[v] + assign_full[v]
            num *= nums[i]
            if num == 0: return F(0)
        return F(num, self.Dprod)
    def frontier_record(self):
        """the frontier state sufficient for an exact re-derivation: resolved leaves + the expanded internal nodes that are not ancestors of a resolved leaf
        (ancestors of resolved leaves are implied); zero prefixes (expanded nodes whose children all have bound 0) are listed for inspection"""
        implied = set()
        for l in self.resolved:
            for k in range(len(l)): implied.add(l[:k])
        extra = sorted(p for p in self.children if p not in implied)
        zero = sorted(p for p, kids in self.children.items() if all(us == 0 for us, _ in kids))
        return dict(resolved_leaves=[list(l) for l in sorted(self.resolved)], extra_expanded=[list(p) for p in extra], zero_prefixes=[list(p) for p in zero], U_t=_frac_str(self.U_t), U_root=_frac_str(self.u_root), expanded_nodes=len(self.children))
    @staticmethod
    def rebuild(model, cutset, resolved_leaves, extra_expanded, deadline=None):
        """checker: re-derive the frontier (hence U_t) from the recorded resolved leaves and extra expanded nodes; expansion is deterministic from the model"""
        T = Tree(model, cutset, deadline)
        for leaf in resolved_leaves:
            u, _, _ = T.node_bounds(tuple(leaf)); T.resolve(tuple(leaf), u)
        for p in extra_expanded:
            if len(p) < len(T.cut): T._expand_path(tuple(p))
        return T


# ---------------- RESOLVED TOTALS in the component's own scale (block floating point; candidate v3; review R03 / R02)
class Totals:
    """rigorous directed enclosures of the resolved mass A and the per-coordinate resolved numerators a_j in the COMPONENT'S scale, independent of the statistical
    scale U_root: block floating point = binary64 directed mantissas times 2^E with ONE shared exponent E (candidate v4; review R01 of 13 Nov 2026).
    INVARIANT (for every coordinate j and for the denominator, after every insertion and every rebase):   lo_j * 2^E  <=  sum over resolved cells of n_j(cell)  <=  hi_j * 2^E
    with lo_j, hi_j finite nonnegative binary64 values (and hi_j > 0 whenever some inserted upper contribution was positive).
      * insertion: each exact rational contribution x is divided EXACTLY by 2^E (rational arithmetic), then rounded to binary64 DOWN (lower) / UP (upper) by
        rig.df_lo / df_hi (nearest conversion, one ulp step in the needed direction when inexact; a positive value below 2^-1074 rounds up to 2^-1074 and down to 0);
        the accumulators are then added with directed rounding (rig.add_lo / add_hi, numpy nextafter). Both steps are monotone outward: the invariant is preserved.
      * rebase E -> E' (E' > E, when a new cell is far larger than the current scale): every accumulator x is replaced by  rd(x * 2^(E-E'))  (lower)  or
        ru(x * 2^(E-E'))  (upper), computed with math.ldexp / numpy.ldexp (correctly rounded to nearest) followed by an EXACTNESS test (ldexp back by E'-E
        reproduces x exactly iff no rounding occurred; the back-scaling is exact because the result is <= x and in range) and ONE ulp step in the needed direction
        when inexact; a positive upper value that underflows to 0 becomes 2^-1074 (nextafter(0, +inf)); a lower value never goes below 0. Since x * 2^(E-E') is
        the exact scaled value, rd/ru enclose it: the invariant holds for EVERY exponent gap (including gaps beyond 1074 and subnormal results); coordinates
        untouched by later sparse updates keep their positive upper bounds. Nothing in the rebase ever uses an ordinary (round-to-nearest) multiplication.
      * the scaled values shrink under a rebase, so no overflow can occur there; an upper accumulator reaching +inf under insertion is a typed NUMERICAL_RANGE_OR_PRECISION stop.
    The exact rational mass enclosure (A_exact_lo/hi) is kept as well (scalar, cheap). Per-cell records (leaf, B0 enclosure) are retained for the checker, which
    re-derives every contribution by deterministic replay (compiled-kernel boundary) and re-enumerates affordable cells independently."""
    def __init__(self, tot):
        import numpy as np
        self.np = np; self.E = None; self.tot = tot; self.A_lo = 0.0; self.A_hi = 0.0; self.a_lo = np.zeros(tot); self.a_hi = np.zeros(tot); self.A_exact_lo = F(0); self.A_exact_hi = F(0); self.cells = []; self.rebases = 0
    def _conv(self, x, up):
        q = x / self.scale
        return rig.df_hi(q) if up else rig.df_lo(q)
    @staticmethod
    def _scale_down_scalar(x, k, up):
        """rd / ru of x * 2^k for a nonnegative binary64 x and an integer k <= 0 (directed, exact when representable)"""
        if x == 0.0: return 0.0
        y = math.ldexp(x, k)
        if math.ldexp(y, -k) == x: return y                                   # exact (no rounding occurred)
        return math.nextafter(y, rig.INF) if up else max(0.0, math.nextafter(y, -rig.INF))
    def _scale_down_vec(self, arr, k, up):
        np = self.np; y = np.ldexp(arr, k); exact = (np.ldexp(y, -k) == arr) | (arr == 0.0)
        stepped = np.nextafter(y, rig.INF) if up else np.maximum(np.nextafter(y, -rig.INF), 0.0)
        return np.where(exact, y, stepped)
    def _rebase(self, Enew):
        if self.E is not None:
            k = self.E - Enew; assert k < 0, 'rebase only to a larger exponent'
            if k < -2200: k_eff = -2200                                            # every scaled value is then below 2^-1074: lower -> 0, positive upper -> 2^-1074 (ldexp handles any k, this only keeps k in a safe int range)
            else: k_eff = k
            self.A_lo = self._scale_down_scalar(self.A_lo, k_eff, False); self.A_hi = self._scale_down_scalar(self.A_hi, k_eff, True)
            self.a_lo = self._scale_down_vec(self.a_lo, k_eff, False); self.a_hi = self._scale_down_vec(self.a_hi, k_eff, True); self.rebases += 1
        self.E = Enew; self.scale = F(2) ** Enew
    def add_cell(self, leaf, B0lo, B0hi, rows_lo, rows_hi, idx):
        """rows_lo / rows_hi: lists of exact Fractions aligned with idx (coordinate indices); the cell's B0 enclosure exact Fractions"""
        if B0hi > 0:
            e = B0hi.numerator.bit_length() - B0hi.denominator.bit_length()
            if self.E is None: self._rebase(e)
            elif e > self.E + 600: self._rebase(e)
        elif self.E is None: self._rebase(0)
        self.A_lo = rig.add_lo(self.A_lo, self._conv(B0lo, False)); self.A_hi = rig.add_hi(self.A_hi, self._conv(B0hi, True))
        np = self.np
        if idx:
            lo = np.fromiter((self._conv(x, False) for x in rows_lo), dtype=np.float64, count=len(idx)); hi = np.fromiter((self._conv(x, True) for x in rows_hi), dtype=np.float64, count=len(idx))
            self.a_lo[idx] = np.maximum(np.nextafter(self.a_lo[idx] + lo, -rig.INF), 0.0); self.a_hi[idx] = np.nextafter(self.a_hi[idx] + hi, rig.INF)
            if not np.all(np.isfinite(self.a_hi)): raise EngineStop('NUMERICAL_RANGE_OR_PRECISION', 'resolved totals overflow')
        self.A_exact_lo += B0lo; self.A_exact_hi += B0hi
        self.cells.append((tuple(leaf), B0lo, B0hi))
    def bounds(self, U_t, cards, off):
        """deterministic enclosures of every coordinate from the resolved totals and the residual envelope U_t (exact rational arithmetic on the dyadic mantissas):
        N_j in [a_lo_j, a_hi_j + U_t], Z in [A_lo, A_hi + U_t]  =>  p_j in [a_lo_j/(A_hi + U_t), min(1, (a_hi_j + U_t)/A_lo)]  (needs A_lo > 0)"""
        if self.E is None: return None
        Alo = F(self.A_lo) * self.scale; Ahi = F(self.A_hi) * self.scale
        if Alo <= 0: return None
        Ut = F(U_t); rows = []
        for v in range(len(cards)):
            row = []
            for s_ in range(cards[v]):
                j = off[v] + s_; lo = F(float(self.a_lo[j])) * self.scale; hi = F(float(self.a_hi[j])) * self.scale
                row.append((max(F(0), lo / (Ahi + Ut)), min(F(1), (hi + Ut) / Alo)))
            rows.append(row)
        return rows
    @staticmethod
    def bounds_from_record(rec, U_t, cards, off):
        """checker: deterministic rows from a (verified) resolved-totals record and a (rebuilt) U_t -- the same arithmetic as `bounds`"""
        if rec.get('E') is None: return None
        scale = F(2) ** int(rec['E']); Alo = F(float(rec['A_lo'])) * scale; Ahi = F(float(rec['A_hi'])) * scale
        if Alo <= 0: return None
        Ut = F(U_t); rows = []
        for v in range(len(cards)):
            row = []
            for s_ in range(cards[v]):
                j = off[v] + s_; lo = F(float(rec['a_lo'][j])) * scale; hi = F(float(rec['a_hi'][j])) * scale
                row.append((max(F(0), lo / (Ahi + Ut)), min(F(1), (hi + Ut) / Alo)))
            rows.append(row)
        return rows
    def record(self):
        return dict(E=self.E, rebases=self.rebases, A_lo=self.A_lo, A_hi=self.A_hi, a_lo=[float(x) for x in self.a_lo], a_hi=[float(x) for x in self.a_hi], A_exact_lo=_frac_str(self.A_exact_lo), A_exact_hi=_frac_str(self.A_exact_hi), cells=[dict(leaf=list(l), B0_lo=_frac_str(lo), B0_hi=_frac_str(hi)) for l, lo, hi in self.cells],
                    representation='block floating point: directed binary64 mantissas x 2^E, directed insertion and DIRECTED rebase (ldexp + exactness test + one ulp outward); invariant lo*2^E <= exact <= hi*2^E')


# ---------------- residual template: lowering with cached slices (reuses cex_executor.convert; typed stops translated)
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
        self.sem = hashlib.sha256(json.dumps({'cards': self.cards, 'cutset': sorted(self.cut), 'order_free': [self.free[i] for i in self.order], 'template': 'pac-conditional-v2'}).encode()).hexdigest()
        self.tot = sum(self.cards[v] for v in self.free); self.lib = X.load(X.build(deadline))
    def _convert(self, w, shift):
        try: return self.X.convert(w, shift)
        except self.X.Stop as e: raise contrib.CellStop(e.kind, 'source conversion: ' + e.reason, dict(e.stats))
    def _lower_values(self, newsc, data):
        X = self.X; vol = len(data); nz = sum(1 for w in data if w != 0)
        if nz == 0: return None
        shift = -X.floor_log2(max(data)); lab = 0; dense = nz >= self.thr * vol
        if dense:
            dv = []
            for w in data: x, l = self._convert(w, shift); dv.append(x); lab = max(lab, l)
            return (newsc, 0, None, dv, lab, -shift)
        keys = []; dv = []
        for k, w in enumerate(data):
            if w != 0: x, l = self._convert(w, shift); keys.append(k); dv.append(x); lab = max(lab, l)
        return (newsc, 1, keys, dv, lab, -shift)
    def _np_src(self, src):
        import numpy as np
        sc, mode, keys, dv, lab, exp2 = src
        w = [len(sc)] + list(sc) + [mode, len(dv)] + (list(keys) if mode == 1 else []) + [lab, exp2]
        return np.asarray(w, dtype=np.int64), np.asarray(dv, dtype=np.float64)
    def lower(self, assign):
        import numpy as np
        if not hasattr(self, '_fixed_np'):
            parts = [self._np_src(s_) for s_ in self.fixed_src]; self._fixed_np = (np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, np.int64), np.concatenate([p[1] for p in parts]) if parts else np.zeros(0, np.float64))
            self._head = np.asarray([self.X.PLAN_FORMAT, len(self.free)] + [self.cards[v] for v in self.free] + [len(self.free)] + self.order, dtype=np.int64)
        wparts = [self._fixed_np[0]]; vparts = [self._fixed_np[1]]; scalars = []; nsrc = len(self.fixed_src)
        for a, sc, cutpart, newsc in self.var_fac:
            key = (a, tuple(assign[v] for v in cutpart))
            if key not in self.cache:
                if self.deadline is not None and time.monotonic() >= self.deadline: raise contrib.CellStop('DEADLINE', 'template slice construction')
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


def cell_contribution_rows(cards, cut, assign, B0, rows_c, off):
    """the per-coordinate contribution rows of one resolved cell in the component scale, in the canonical coordinate order used by Totals / Stream:
    cut variables contribute the cell mass to their assigned state; free variables contribute the leaf's per-state enclosures. Returns (idx, rows_lo, rows_hi).
    Shared by run_component (producer) and gate.verify_cover (checker) so that a replay re-accumulates exactly the producer's inputs."""
    idx = []; rows_lo = []; rows_hi = []
    for v in range(len(cards)):
        if v in assign: idx.append(off[v] + assign[v]); rows_lo.append(B0[0]); rows_hi.append(B0[1])
        elif rows_c is not None:
            for s_, (lo, hi) in enumerate(rows_c[v]): idx.append(off[v] + s_); rows_lo.append(lo); rows_hi.append(hi)
    return idx, rows_lo, rows_hi


def exact_cell(model, assign, deadline):
    r = contrib.cell_exact(model, assign, deadline, max_completions=POLICY['exact_leaf_max_completions'])
    free = [v for v in range(len(model['cards'])) if v not in assign]
    return r['B0'], {v: r['B'][v] for v in free}, {}


# ---------------- the stream: DIMENSIONLESS statistics in DIRECTED binary64 (no error labels), both certifiers, resolved totals
class Stream:
    """All increments are scaled by 1/U_root: T' = T/U_root in [0,1], Y'_j = Y_j/U_root. lambda_t = U_root^-2 and rho = 1/(4 U_root^2) give, in these units,
    B' = sum T', C'_j = sum Y'_j, V' <= n/4, rho' = 1/4, radius = b(V', alpha)/B' with b(V, alpha) = sqrt((1/4 + V) log((1/4 + V)/(alpha^2/4))).
    Every increment enters as a pair of binary64 DIRECTED bounds [lo, hi] of the exact increment; accumulators: lower = directed-down sum of lower bounds,
    upper = directed-up sum of upper bounds (rig.add_lo / add_hi, numpy nextafter). Squares and products of nonnegative bounds likewise directed.
    The five sums a_j, b, c_j, d_j, e of the variance certificate and the resolved totals A', a'_j are kept the same way."""
    def __init__(self, cards, cutset, U, delta_range_c, delta_var_c, K_total, l_values):
        import numpy as np
        self.np = np; self.cards = cards; self.n = len(cards); self.off = [0]
        for c in cards: self.off.append(self.off[-1] + c)
        self.tot = self.off[-1]; self.U = F(U); self.alpha_r = F(delta_range_c) / K_total; self.alpha_v = F(delta_var_c) / K_total; self.K = K_total; self.l_values = list(l_values)
        self.t = 0; self.positive_trials = 0; self.zero_trials = 0
        z = lambda: np.zeros(self.tot); self.a_lo = z(); self.a_hi = z(); self.c_lo = z(); self.c_hi = z(); self.d_lo = z(); self.d_hi = z()
        self.b_lo = 0.0; self.b_hi = 0.0; self.e_lo = 0.0; self.e_hi = 0.0
        self.A_lo = 0.0; self.A_hi = 0.0; self.ra_lo = z(); self.ra_hi = z()          # resolved totals (dimensionless): A'/U_root and a'_j/U_root
        self.A_exact_lo = F(0); self.A_exact_hi = F(0)                                 # exact rational enclosure of the resolved mass (scalar, cheap)
    # ---- directed helpers (numpy)
    def _vlo(self, x): return self.np.maximum(self.np.nextafter(x, -rig.INF), 0.0)
    def _vhi(self, x):
        y = self.np.nextafter(x, rig.INF)
        if not self.np.all(self.np.isfinite(y)): raise EngineStop('NUMERICAL_RANGE_OR_PRECISION', 'upper accumulator overflow')
        return y
    # ---- increments
    def add_residual(self, rlo, rhi, Ylo_res, Yhi_res):
        """one trial: residual contribution r' in [rlo, rhi] (floats, directed), residual per-coordinate Y' bounds (numpy arrays over all coordinates, directed);
        the resolved totals BEFORE the trial are added (T = A + r, Y = a + r f)"""
        np = self.np
        Tlo = rig.add_lo(self.A_lo, rlo); Thi = rig.add_hi(self.A_hi, rhi)
        Ylo = self._vlo(self.ra_lo + Ylo_res); Yhi = self._vhi(self.ra_hi + Yhi_res)
        self.t += 1
        self.b_lo = rig.add_lo(self.b_lo, Tlo); self.b_hi = rig.add_hi(self.b_hi, Thi)
        self.e_lo = rig.add_lo(self.e_lo, rig.mul_lo(Tlo, Tlo)); self.e_hi = rig.add_hi(self.e_hi, rig.mul_hi(Thi, Thi))
        self.a_lo = self._vlo(self.a_lo + Ylo); self.a_hi = self._vhi(self.a_hi + Yhi)
        self.c_lo = self._vlo(self.c_lo + self._vlo(Ylo * Ylo)); self.c_hi = self._vhi(self.c_hi + self._vhi(Yhi * Yhi))
        self.d_lo = self._vlo(self.d_lo + self._vlo(Ylo * Tlo)); self.d_hi = self._vhi(self.d_hi + self._vhi(Yhi * Thi))
        if rhi > 0: self.positive_trials += 1
        else: self.zero_trials += 1
    def add_zero(self):
        """a zero residual contribution (proved zero prefix): T = A_t, Y = a_t"""
        self.add_residual(0.0, 0.0, self.np.zeros(self.tot), self.np.zeros(self.tot))
    def resolve_add(self, B0lo, B0hi, rows_lo, rows_hi, B0_exact_lo, B0_exact_hi):
        """insert a resolved cell's dimensionless enclosure into the resolved totals (between trials)"""
        self.A_lo = rig.add_lo(self.A_lo, B0lo); self.A_hi = rig.add_hi(self.A_hi, B0hi)
        self.ra_lo = self._vlo(self.ra_lo + rows_lo); self.ra_hi = self._vhi(self.ra_hi + rows_hi)
        self.A_exact_lo += B0_exact_lo; self.A_exact_hi += B0_exact_hi
    # ---- exact enclosures of the exact statistics (dyadic floats -> exact rationals)
    def _enc(self, lo, hi): return (F(float(lo)), F(float(hi)))
    def record(self):
        """the sufficient statistics (directed accumulators) as exact dyadic rationals in string form, plus the stream constants: enough to recompute both certificates"""
        fl = lambda arr: [float(x) for x in arr]
        return dict(n=self.t, positive_trials=self.positive_trials, zero_trials=self.zero_trials, U_root=_frac_str(self.U), K=self.K, alpha_range=_frac_str(self.alpha_r), alpha_variance=_frac_str(self.alpha_v), l_values=self.l_values, cards=list(self.cards),
                    b_lo=self.b_lo, b_hi=self.b_hi, e_lo=self.e_lo, e_hi=self.e_hi, a_lo=fl(self.a_lo), a_hi=fl(self.a_hi), c_lo=fl(self.c_lo), c_hi=fl(self.c_hi), d_lo=fl(self.d_lo), d_hi=fl(self.d_hi),
                    A_lo=self.A_lo, A_hi=self.A_hi, ra_lo=fl(self.ra_lo), ra_hi=fl(self.ra_hi), A_exact_lo=_frac_str(self.A_exact_lo), A_exact_hi=_frac_str(self.A_exact_hi),
                    representation='directed binary64 accumulators (lower = directed-down sum of directed-down increments; upper mirror); dimensionless by U_root')
    def range_hulls(self):
        return range_hulls_from(self.record())
    def variance_sets(self, only=None):
        return variance_sets_from(self.record(), only)


# ---------------- certificate recomputation from a RECORD (shared by the engine and the independent gate replay)
def range_hulls_from(R):
    """certificate (i) from a sufficient-statistics record: p_j in [ (C'lo - b)/B'hi , (C'hi + b)/B'lo ] with b = b(n/4, alpha_r) rounded up; needs B'lo > 0"""
    n = R['n']; alpha_r = F(R['alpha_range']); cards = R['cards']
    b = rig.range_boundary_up(F(1, 4), F(n, 4), alpha_r); Blo, Bhi = F(float(R['b_lo'])), F(float(R['b_hi']))
    if Blo <= 0: return None, b
    hulls = {}; off = 0
    for v in range(len(cards)):
        row = []
        for s_ in range(cards[v]):
            Clo, Chi = F(float(R['a_lo'][off + s_])), F(float(R['a_hi'][off + s_]))
            lo = (Clo - b) / Bhi if Clo - b >= 0 else (Clo - b) / Blo; hi = (Chi + b) / Blo
            row.append((max(F(0), lo), min(F(1), hi)))
        hulls[v] = row; off += cards[v]
    return hulls, b


def variance_sets_from(R, only=None):
    """certificate (ii) from a record: per coordinate the accepted set [0,1] minus the union over (l, sign) of CERTIFIED rejection intervals; `only` restricts to variables"""
    cards = R['cards']; alpha_v = F(R['alpha_variance']); K = R['K']; blo, bhi = F(float(R['b_lo'])), F(float(R['b_hi'])); elo, ehi = F(float(R['e_lo'])), F(float(R['e_hi']))
    tests = []
    for l in R['l_values']:
        lam = F(1, 2 ** l); omega_lo = F(6) / (F(98696044011, 10 ** 10) * l * l); L = rig.log_threshold_up(1, alpha_v, omega_lo); plo, phi = rig.psi(lam); tests.append((lam, L, plo, phi))
    out = {}; off = 0
    for v in range(len(cards)):
        if only is not None and v not in only: off += cards[v]; continue
        rows = []
        for s_ in range(cards[v]):
            j = off + s_; alo, ahi = F(float(R['a_lo'][j])), F(float(R['a_hi'][j])); clo, chi = F(float(R['c_lo'][j])), F(float(R['c_hi'][j])); dlo, dhi = F(float(R['d_lo'][j])), F(float(R['d_hi'][j])); rejected = []
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
        out[v] = rows; off += cards[v]
    return out


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


def _intersect(seg, det):
    """closed interval intersection; None when empty"""
    lo = max(seg[0], det[0]); hi = min(seg[1], det[1])
    return (lo, hi) if lo <= hi else None


def hulls_from_record(R, eps=POLICY['epsilon'], margin=POLICY['decimal_margin'], det_rows=None):
    """independent replay of the publication predicate from a record: per row the narrower certified hull with a feasible simplex point; returns
    (ok, rows {v: [(lo,hi)]}, points, chosen certifier per row, widths, boundary, variance sets, composition). The gate calls this with the certificate's recorded
    statistics and with the deterministic rows it has itself re-derived.
    COMPOSITION (02_IMPLEMENTATION_REQUIREMENTS line 52; candidate v4): when proved deterministic bounds det_rows[v][s] = [dlo, dhi] are supplied, every statistical
    outer set is INTERSECTED with them before the simplex feasibility check: range hull -> hull ∩ det; variance set -> each accepted segment ∩ det, empty segments
    dropped, then the outer hull of the remaining segments (the documented conservative point). Risk: on the event E of the time-uniform statistical guarantee
    (P(E^c) <= delta over the whole job) the statistical set contains p_j; the deterministic bound contains p_j surely; hence their intersection and its outer hull
    contain p_j on E -- the simultaneous risk allocation is unchanged. An EMPTY intersection at some coordinate (p_j outside one of two sets that should both
    contain it: the statistical event failed, or a defect) makes the row unpublishable and is reported as composition 'EMPTY_INTERSECTION' with the coordinate;
    the caller turns it into the typed diagnostic outcome INTERSECTION_EMPTY (never an optimistic publication, never a silently dropped run)."""
    cards = R['cards']; n = len(cards); rh, bU = range_hulls_from(R); rows_r = {}; pts = {}; chosen = {}; ok = True; widths = dict(range={}, variance={}, deterministic={}, intersection={}); comp = dict(used='statistical_only' if det_rows is None else 'intersection_with_deterministic', empty=[], standalone_statistical_ok={}, standalone_deterministic_ok={})
    need_var = []
    def det_of(v, s_): return (F(det_rows[v][s_][0]), F(det_rows[v][s_][1])) if det_rows is not None else None
    for v in range(n):
        best = None
        if det_rows is not None:
            wd = max(F(det_rows[v][s_][1]) - F(det_rows[v][s_][0]) for s_ in range(cards[v])); widths['deterministic'][v] = float(wd); comp['standalone_deterministic_ok'][v] = bool(wd <= 2 * eps - 2 * margin and feasible_point([det_of(v, s_) for s_ in range(cards[v])], eps - margin) is not None)
        if rh is not None and all(h is not None for h in rh[v]):
            w0 = max(hi - lo for lo, hi in rh[v]); widths['range'][v] = float(w0); comp['standalone_statistical_ok'][v] = bool(w0 <= 2 * eps - 2 * margin and feasible_point(rh[v], eps - margin) is not None)
            hull = list(rh[v])
            if det_rows is not None:
                hull = [_intersect(h, det_of(v, s_)) for s_, h in enumerate(hull)]
                if any(h is None for h in hull): comp['empty'].append(dict(variable=v, certifier='range')); hull = None
            if hull is not None:
                w = max(hi - lo for lo, hi in hull); widths['intersection'][v] = float(w)
                if w <= 2 * eps - 2 * margin:
                    p = feasible_point(hull, eps - margin)
                    if p is not None: best = (w, 'range', hull, p)
        if best is None: need_var.append(v)
        else: chosen[v] = 'range'; rows_r[v] = best[2]; pts[v] = best[3]
    vsets = variance_sets_from(R, set(need_var)) if need_var else {}
    for v in need_var:
        best = None; segs_v = vsets[v]
        hv0 = [((iv[0][0], iv[-1][1]) if iv else None) for iv in segs_v]
        if all(h is not None for h in hv0):
            w0 = max(hi - lo for lo, hi in hv0); widths['variance'][v] = float(w0); comp['standalone_statistical_ok'][v] = comp['standalone_statistical_ok'].get(v, False) or bool(w0 <= 2 * eps - 2 * margin and feasible_point(hv0, eps - margin) is not None)
        if det_rows is not None:
            segs_v = [[x for x in (_intersect(seg, det_of(v, s_)) for seg in iv) if x is not None] for s_, iv in enumerate(segs_v)]
        hv = [((iv[0][0], iv[-1][1]) if iv else None) for iv in segs_v]
        if all(h is not None for h in hv):
            w = max(hi - lo for lo, hi in hv); widths['intersection'][v] = min(widths['intersection'].get(v, float('inf')), float(w))
            if w <= 2 * eps - 2 * margin:
                p = feasible_point(hv, eps - margin)
                if p is not None: best = (w, 'variance', hv, p)
        elif det_rows is not None and all(h is not None for h in hv0): comp['empty'].append(dict(variable=v, certifier='variance'))
        if best is None: ok = False
        else: chosen[v] = 'variance'; rows_r[v] = best[2]; pts[v] = best[3]
    if comp['empty']: comp['used'] = 'EMPTY_INTERSECTION'; ok = False
    return ok, rows_r, pts, chosen, widths, bU, vsets, comp


# ---------------- publication
def feasible_point(hulls, eps):
    """hulls: list of (l_j, u_j) per state of one row; returns the exact simplex point or None (theory §11 feasibility conditions)"""
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


def _deterministic_rows_publish(rows, n, eps, margin):
    """rows {v: [(lo,hi)]} exact enclosures -> (ok, intervals, points) with the same feasibility predicate as the PAC hulls"""
    ivs = []; pts = []
    for v in range(n):
        w = max(hi - lo for lo, hi in rows[v])
        if w > 2 * eps - 2 * margin: return False, None, None
        p = feasible_point(rows[v], eps - margin)
        if p is None: return False, None, None
        ivs.append(list(rows[v])); pts.append(p)
    return True, ivs, pts


# ---------------- REPLAY (candidate v4; review R03): the checker re-executes the recorded design on the bound component model
def replay_component(comp, design, n_trials, K_total, cap_bytes=3 * 1024 ** 3, rss_entry=0, deadline=None, policy=POLICY):
    """deterministic replay of a recorded PAC design for exactly n_trials trials: the same seeds, cutset, order, mode, resolution policy and frozen engine code
    reproduce the draw sequence (PRNG), every leaf evaluation (exact enumeration or the compiled kernel, both deterministic for fixed inputs), every resolution
    transition and the directed accumulation; the resulting sufficient statistics / frontier / resolved totals must EQUAL the certificate's. The replay derives the
    statistics from the SOURCE MODEL and the design, not from the certificate's numbers: statistics impossible under the recorded law cannot be reproduced.
    Cost = the production cost of the recorded trials (charged to the checker); a deadline turns an unaffordable replay into a typed UNVERIFIABLE result."""
    pol = dict(policy); pol['epsilon'] = F(design['epsilon'])          # the task epsilon is a TASK parameter (bound to the manifest by the gate); every other policy constant is the frozen one
    return run_component(comp, deadline, int(design['seed_tree']), int(design['seed_point']), design['mode'], F(design['delta_range']), F(design['delta_variance']), K_total, cap_bytes, rss_entry, pol, fixed_cutset=list(design['cutset']), fixed_order=list(design['order_free']), max_trials=int(n_trials), resolve=bool(design.get('resolve')), replay_exact_trials=True)


def design_binding_failures(design, policy, seed, component_index, task_epsilon, engine_version=None):
    """the recorded design must be the FROZEN policy's (never the certificate's own description) with the TASK epsilon and the seeds DERIVED from the cell seed: returns the mismatches"""
    bad = []
    want = dict(lambda_rule=policy['lambda_rule'], rho_rule=policy['rho_rule'], stream_scale=policy['stream_scale'], prng=policy['prng'], l_values=list(policy['variance_l_values']), exact_leaf_max_completions=policy['exact_leaf_max_completions'], epsilon=_frac_str(F(task_epsilon)), decimal_margin=_frac_str(policy['decimal_margin']), engine_version=engine_version or ENGINE_VERSION, seed_tree=str(seed_int(seed, 'tree', component_index)), seed_point=str(seed_int(seed, 'point', component_index)))
    for k, v in want.items():
        if design.get(k) != v: bad.append('design.%s differs from the frozen policy / derived task seed' % k)
    if design.get('mode') not in ('point', 'conditional'): bad.append('design.mode invalid')
    if design.get('mode') == 'point' and design.get('resolve'): bad.append('point mode cannot resolve')
    return bad


# ---------------- one component
def deterministic_rows(T, U_t, cards, off):
    return T.bounds(U_t, cards, off)


def run_component(comp, deadline, seed_tree, seed_point, mode, delta_range_c, delta_var_c, K_total, cap_bytes, rss_entry, policy=POLICY, trace=None, fixed_cutset=None, fixed_order=None, max_trials=None, forced=False, resolve=None, tree_factory=None, replay_exact_trials=False):
    """comp: reduced component model (no evidence). Returns dict(status, guarantee, intervals/points per component variable, stats incl. the canonical design record,
    the frontier record, the resolved totals and the sufficient statistics). mode in {'conditional', 'point'}; resolve: insert evaluated cells into the resolved
    region (default: policy for conditional mode; never for point mode); fixed_cutset/fixed_order: the matched ablation's shared law. tree_factory: qualification hook.
    Publication paths, checked at every certification point in this order: (1) DETERMINISTIC from the resolved totals and the residual envelope U_t (delta = 0;
    complete cover is the special case U_t = 0; partial covers publish as soon as the deterministic enclosures meet the task); (2) PAC from the statistical hulls.
    A deterministic publication never spends delta; the statistical stream is unchanged by it."""
    t0 = time.monotonic(); cards = comp['cards']; n = len(cards); eps = policy['epsilon']; st = dict(phase='cutset', engine_version=ENGINE_VERSION); trace = trace if trace is not None else []
    Tree_ = tree_factory or Tree
    if resolve is None: resolve = bool(policy['resolve_evaluated_cells']) and mode == 'conditional'
    if mode == 'point': resolve = False
    def check(where):
        if deadline is not None and time.monotonic() >= deadline: raise EngineStop('DEADLINE', where, st)
    check('entry')
    if not comp['factors']:
        rows = [[(F(1, c), F(1, c)) for _ in range(c)] for c in cards]
        st.update(route='uniform_factorless_component', trials_completed=0, wall_s=time.monotonic() - t0, design=dict(cutset=[], order_free=list(range(n)), mode=mode, U_root='0/1', note='no factors: uniform law'))
        return dict(status='PUBLISHED', guarantee='DETERMINISTIC', intervals=rows, points=[[F(1, c)] * c for c in cards], certifier_per_row=['exact'] * n, widths={}, stats=st)
    if fixed_cutset is None:
        cs = choose_cutset(comp, deadline, policy); cut = cs['cutset']; order_free = cs['order']; st['cutset_selection'] = cs
        if forced and not cut and n > 0 and math.prod(cards) > policy['exact_leaf_max_completions']:
            vol = {}
            for f in comp['factors']:
                w = math.prod(cards[v] for v in f['scope'])
                for v in f['scope']: vol[v] = vol.get(v, 0) + w
            v0 = max(range(n), key=lambda v: (vol.get(v, 0), -v)); cut = [v0]; order_free = [v for v in order_free if v != v0]; st['forced_min_cutset'] = [v0]
    else:
        cut = list(fixed_cutset); order_free = list(fixed_order); st['cutset_selection'] = dict(fixed_by_ablation=True)
    check('after cutset selection')
    if mode == 'conditional' and not cut: resolve = True
    st['phase'] = 'tree'; tree = Tree_(comp, cut, deadline); U = tree.u_root
    st['U_root_log10'] = (math.log10(U.numerator) - math.log10(U.denominator)) if U > 0 else None; st['U_root_bits'] = (U.numerator.bit_length(), U.denominator.bit_length())
    design = dict(cutset=list(cut), order_free=list(order_free), mode=mode, resolve=resolve, U_root=_frac_str(U), lambda_rule=policy['lambda_rule'], rho_rule=policy['rho_rule'], stream_scale=policy['stream_scale'], K_total=K_total, delta_range=_frac_str(F(delta_range_c)), delta_variance=_frac_str(F(delta_var_c)), alpha_range=_frac_str(F(delta_range_c) / K_total), alpha_variance=_frac_str(F(delta_var_c) / K_total), l_values=list(policy['variance_l_values']), seed_tree=str(seed_tree), seed_point=str(seed_point), prng=policy['prng'], epsilon=_frac_str(eps), decimal_margin=_frac_str(policy['decimal_margin']), exact_leaf_max_completions=policy['exact_leaf_max_completions'], engine_version=ENGINE_VERSION)
    st['design'] = design
    if U == 0:
        check('zero root bound terminal')
        return dict(status='PROVED_ZERO_EVIDENCE', guarantee='DETERMINISTIC', stats=dict(st, proof='every cell bound is zero at the root: some factor has only zero entries compatible with the root cell', frontier=tree.frontier_record(), wall_s=time.monotonic() - t0))
    free_leaf = [v for v in range(n) if v not in tree.pos]
    try:
        tmpl = Template(comp, cut, order_free, deadline=deadline) if (mode == 'conditional' and free_leaf and tree.free_count > policy['exact_leaf_max_completions']) else None
    except contrib.CellStop as e:
        raise EngineStop({'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'RANGE': 'NUMERICAL_RANGE_OR_PRECISION', 'REPRESENTATION': 'MEMORY'}.get(e.kind, 'INVALID_PLAN_OR_CERTIFICATE'), 'template construction: ' + e.reason, st)
    check('after template construction')
    design['template_semantic'] = tmpl.sem if tmpl else None; design['leaf_completions'] = tree.free_count; design['leaf_evaluator'] = 'compiled_kernel' if tmpl else ('exact_enumeration' if free_leaf else 'point_product')
    try: rig.fp_selfcheck()
    except (rig.RangeStop, AssertionError) as e: raise EngineStop('NUMERICAL_RANGE_OR_PRECISION', 'binary64 environment self-check failed: %s' % e, st)
    S = Stream(cards, cut, U, delta_range_c, delta_var_c, K_total, policy['variance_l_values']); T = Totals(S.tot); rng_t = random.Random(seed_tree); rng_p = random.Random(seed_point)
    st['phase'] = 'stream'; trials = 0; kernel_s = 0.0; last_check = None; publish = None; term = None; counters_tot = {}; last_cert_t = time.monotonic(); det_dirty = False
    np = S.np
    def to_dimless(x):
        q = x / U
        return rig.df_lo(q), rig.df_hi(q)
    def certify_det():
        """deterministic publication from the resolved totals and U_t (delta = 0)"""
        rows = T.bounds(tree.U_t, cards, S.off)
        if rows is None: return None
        ok, ivs, pts = _deterministic_rows_publish({v: rows[v] for v in range(n)}, n, eps, policy['decimal_margin'])
        return (ivs, pts, rows) if ok else None
    def certify_pac():
        """statistical certification COMPOSED with the proved deterministic bounds of the resolved region (when A_lo > 0): hull ∩ det before feasibility (R04)"""
        det = T.bounds(tree.U_t, cards, S.off) if tree.resolved_count > 0 else None
        return hulls_from_record(S.record(), eps, policy['decimal_margin'], det_rows=det)
    while True:
        if deadline is not None and time.monotonic() >= deadline: term = 'DEADLINE'; break
        if det_dirty:
            # the resolved state changed: deterministic bounds first (closure when U_t = 0 is the special case where they are exact up to the enclosures)
            det_dirty = False; tc = time.monotonic(); dr = certify_det(); st['certify_det_s'] = st.get('certify_det_s', 0.0) + time.monotonic() - tc
            if dr is not None: publish = ('DETERMINISTIC', dr); term = 'DETERMINISTIC_BOUNDS' if tree.U_t > 0 else 'COVER_COMPLETE'; break
            if tree.U_t == 0: term = 'COVER_COMPLETE'; break
        if max_trials is not None and trials >= max_trials: term = 'MAX_TRIALS'; break
        if not replay_exact_trials and trials > 0 and ((trials & (trials - 1)) == 0 or trials % 65536 == 0 or (time.monotonic() - last_cert_t) > max(0.5, 0.1 * (deadline - time.monotonic()) if deadline else 0.5)):
            tc = time.monotonic(); ok, rows, pts, chosen, widths, bU, vsets, comp_ = certify_pac(); st['certify_s'] = st.get('certify_s', 0.0) + time.monotonic() - tc; last_check = dict(trial=trials, widths=widths, chosen=chosen, composition=comp_['used']); last_cert_t = time.monotonic()
            if comp_['used'] == 'EMPTY_INTERSECTION': term = 'INTERSECTION_EMPTY'; st['empty_intersection'] = comp_['empty']; break
            if ok: publish = ('PAC', (rows, pts, chosen, widths, vsets, comp_)); term = 'CERTIFIED'; break
        # ---- one trial: predictable design (frontier fixed before the draw), fresh draw
        U_t = tree.U_t
        assign, q, zero_terminal, trans, u_leaf = tree.draw_leaf(rng_t); trials += 1
        if zero_terminal:
            S.add_zero()
            if tree.U_t < U_t: det_dirty = True                       # a reached zero subtree closed: the residual envelope dropped (frontier propagation)
            if tree.U_t == 0: det_dirty = True
            continue
        if not (q * U_t >= u_leaf): raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'proposal law: q U_t < u_leaf (telescoping inequality violated)', st)
        try:
            if mode == 'point':
                full = dict(assign)
                for v in free_leaf: full[v] = rng_p.randrange(cards[v])
                w = tree.point_weight(full)
                if not (w * tree.free_count <= u_leaf): raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'envelope violated (point): W(x) m_leaf > u_leaf', st)
                r = w * tree.free_count / q
                rlo, rhi = to_dimless(r); Ylo = np.zeros(S.tot); Yhi = np.zeros(S.tot)
                idx = [S.off[v] + full[v] for v in range(n)]; Ylo[idx] = rlo; Yhi[idx] = rhi
                S.add_residual(rlo, rhi, Ylo, Yhi)
            else:
                tk = time.monotonic()
                if tmpl is None: B0, rows_c, ctr = exact_cell(comp, assign, deadline)
                else: B0, rows_c, ctr = kernel_cell(tmpl, assign, deadline, cap_bytes, rss_entry)
                kernel_s += time.monotonic() - tk
                for k, x in ctr.items(): counters_tot[k] = counters_tot.get(k, 0) + x
                if B0[0] > u_leaf: raise EngineStop('INVALID_PLAN_OR_CERTIFICATE', 'envelope violated (conditional): B0_lo(leaf) = %s > u_leaf = %s' % (float(B0[0]), float(u_leaf)), st)
                rlo, rhi = to_dimless(B0[0] / q)[0], to_dimless(B0[1] / q)[1]
                Ylo = np.zeros(S.tot); Yhi = np.zeros(S.tot); idx, rows_lo, rows_hi = cell_contribution_rows(cards, cut, assign, B0, rows_c, S.off)
                for j, lo, hi in zip(idx, rows_lo, rows_hi): Ylo[j] = to_dimless(lo / q)[0]; Yhi[j] = to_dimless(hi / q)[1]     # cut coordinates carry (B0 lo, hi)/q = (rlo, rhi)
                S.add_residual(rlo, rhi, Ylo, Yhi)
                if resolve:
                    leaf = tuple(assign[v] for v in cut)
                    tree.resolve(leaf, u_leaf)                                      # frontier: leaf closed, ancestors refreshed (predictable for the next trial)
                    T.add_cell(leaf, B0[0], B0[1], rows_lo, rows_hi, idx)           # component-scale resolved totals
                    b0lo, _ = to_dimless(B0[0]); _, b0hi = to_dimless(B0[1]); Rlo = np.zeros(S.tot); Rhi = np.zeros(S.tot)
                    for j, lo, hi in zip(idx, rows_lo, rows_hi): Rlo[j] = to_dimless(lo)[0]; Rhi[j] = to_dimless(hi)[1]
                    S.resolve_add(b0lo, b0hi, Rlo, Rhi, B0[0], B0[1])               # dimensionless resolved totals for the statistical stream (T = A + r)
                    det_dirty = True
        except contrib.CellStop as e:
            term = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'RANGE': 'NUMERICAL_RANGE_OR_PRECISION', 'REPRESENTATION': 'MEMORY'}.get(e.kind, 'INVALID_PLAN_OR_CERTIFICATE'); st['trial_failure'] = dict(trial=trials, kind=e.kind, reason=e.reason[:200]); trials -= 1; break
        except rig.RangeStop as e:
            term = 'NUMERICAL_RANGE_OR_PRECISION'; st['trial_failure'] = dict(trial=trials, kind='RANGE', reason=str(e)[:200]); trials -= 1; break
        except EngineStop as e:
            if e.outcome == 'DEADLINE': term = 'DEADLINE'; trials -= 1; break
            if e.outcome == 'NUMERICAL_RANGE_OR_PRECISION': term = 'NUMERICAL_RANGE_OR_PRECISION'; st['trial_failure'] = dict(trial=trials, kind='RANGE', reason=e.reason[:200]); trials -= 1; break
            raise
    # ---- terminal
    st['sufficient_statistics'] = S.record(); st['resolved_cells'] = tree.resolved_count; st['frontier'] = tree.frontier_record(); st['resolved_totals'] = T.record(); st['U_t_over_U_root'] = float(tree.U_t / U) if U else None
    st['Z_estimate_over_U'] = (float(S.b_lo) / S.t) if S.t else None; st['Z_estimate_note'] = 'sample average of the lower accumulator; an ESTIMATE, not a certified ratio; U_root is gauge dependent'
    st['trials_per_second'] = (S.t / max(1e-9, time.monotonic() - t0))
    st.update(trials_completed=S.t, positive_trials=S.positive_trials, zero_trials=S.zero_trials, kernel_s=kernel_s, counters=counters_tot, terminal=term, wall_s=time.monotonic() - t0, K_total=K_total)
    # deterministic bounds are tried at EVERY terminal (also DEADLINE / failed trial): acquired exact information is never discarded
    if publish is None and (det_dirty or term in ('DEADLINE', 'MAX_TRIALS', 'MEMORY', 'NUMERICAL_RANGE_OR_PRECISION', 'INVALID_PLAN_OR_CERTIFICATE', 'COVER_COMPLETE')) and tree.resolved_count > 0:
        dr = certify_det()
        if dr is not None: publish = ('DETERMINISTIC', dr); st['terminal_deterministic_bounds'] = True
    if term == 'COVER_COMPLETE' and publish is None:
        check('complete cover terminal')
        if T.A_exact_hi == 0: return dict(status='PROVED_ZERO_EVIDENCE', guarantee='DETERMINISTIC', stats=dict(st, proof='complete exact cover (frontier closed) with total mass 0'))
        return dict(status='NUMERICAL_RANGE_OR_PRECISION', guarantee='NONE', stats=dict(st, note='complete exact cover but the enclosure of the resolved totals is too wide for publication at eps (cell enclosures / block-floating rounding)'))
    if publish is None and S.t > 0 and term not in ('CERTIFIED', 'INTERSECTION_EMPTY'):
        tc = time.monotonic(); ok, rows, pts, chosen, widths, bU, vsets, comp_ = certify_pac(); st['certify_s'] = st.get('certify_s', 0.0) + time.monotonic() - tc; last_check = dict(trial=S.t, widths=widths, chosen=chosen, composition=comp_['used'])
        if comp_['used'] == 'EMPTY_INTERSECTION': term = 'INTERSECTION_EMPTY'; st['empty_intersection'] = comp_['empty']
        elif ok: publish = ('PAC', (rows, pts, chosen, widths, vsets, comp_))
    st['last_check'] = last_check
    if publish is None:
        if S.positive_trials == 0 and S.t > 0: st['note'] = 'no positive sample observed; NOT a zero-evidence claim'
        if S.t > 0 and S.b_hi > 0 and S.b_lo == 0: st['stream_scale_underflow'] = 'the lower denominator accumulator is 0 while the upper is positive: the dimensionless statistics underflow binary64 at this U_root (numerical width, not statistical width)'
        return dict(status=term if term not in ('CERTIFIED', 'MAX_TRIALS', 'DETERMINISTIC_BOUNDS', None) else 'TOO_WIDE', guarantee='NONE', stats=st)      # INTERSECTION_EMPTY is a typed diagnostic outcome (never a publication)
    check('publication terminal')
    kind, payload = publish
    if kind == 'DETERMINISTIC':
        ivs, pts, rows = payload; st['route'] = 'exact_cover_complete' if tree.U_t == 0 else 'deterministic_partial_cover_bounds'; st['deterministic_widths'] = {v: float(max(hi - lo for lo, hi in rows[v])) for v in range(n)}
        return dict(status='PUBLISHED', guarantee='DETERMINISTIC', intervals=ivs, points=pts, certifier_per_row=[st['route']] * n, widths=dict(deterministic=st['deterministic_widths']), stats=st)
    rows, pts, chosen, widths, vsets, comp_ = payload; st['publication_composition'] = comp_; st['route'] = 'pac_statistical' + ('_intersected_with_deterministic' if comp_['used'] == 'intersection_with_deterministic' else '')
    return dict(status='PUBLISHED', guarantee='PAC', intervals=[rows[v] for v in range(n)], points=[pts[v] for v in range(n)], certifier_per_row=[chosen[v] for v in range(n)], widths=widths, variance_sets_nonconvex=[[len(vsets[v][s]) > 1 for s in range(cards[v])] if v in vsets else [False] * cards[v] for v in range(n)], stats=st)
