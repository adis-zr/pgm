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
import sys, os, json, time, argparse, random, resource, math, itertools
T_PROCESS_START = time.monotonic()
from fractions import Fraction as F
from math import prod, inf, log2, frexp, ldexp, nextafter
sys.set_int_max_str_digits(0)
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path: sys.path.insert(0, HERE)
import blockres as BR
import support_closure as SC
import signed_evidence as SE
import layered_contraction as LC
from blockres import tnow, Deadline, lg

VERSION = 'blockres-integrated-v2.12.1 (2026-11-23 round 20b admission closeout: the layered constructor forecasts the PHYSICAL graph the executor lowers (every retained evidence-restricted source scope incl. scoped constants, the full bucket order incl. one-state / factorless / observed buckets) instead of its recognition graph; cooperative deadline polls inside the exact RREF / matrix construction / local-cost / order loops with storage admission before dense exact structures and early refusal of hopeless candidates; no change to arithmetic, query recovery, dispatch or the selected target order; v2.12 round 20: CERTIFIED LAYERED CONTRACTION (layered_contraction.py): local blocks joined by matching binary channels are recognised on the ORIGINAL evidence-restricted model by exact rational predicates and an exact affine chain alignment (bounded sign search, two validated proposals: all-local cores / residuals confined to a folded terminal pair), compiled into a complete elimination order with a primal-graph volume certificate, admitted by a conservative live-state and work forecast against the memory policy headroom and the remaining deadline, and executed by the EXISTING certified native executor (compiled nonnegative bucket contraction + zero-safe all-singleton reverse, reciprocal-envelope labels, exact N / Z enclosure); every original row published as an outward 2^-52 compaction (DETERMINISTIC; EXACT for point enclosures), Z as an enclosure from the kernel normalizer label; typed refusals fall back; a refusal at the global deadline returns DEADLINE; --no-layered-contraction = the v2.11.2 comparator path; v2.11.2 round 19b closeout: final deadline guards in the signed route -- polled while validating the original rows, after the answer finalization before success is returned, and at the end of recognition; the typed refusal returns DEADLINE with nothing published; no arithmetic / output / policy change; v2.11.1 round 19b bounded-execution repair: the evidence-expansion estimate covers the simultaneous live state of both phases (plan matrix, per-subset arrays with integer limbs, signed accumulators at global-denominator bits, prefix temporaries, numerator mapping, original rows) and admits by max; deadline polled inside chain walks, the coefficient matrix, root loops, prefix walks, row building, with final guards; headroom computed from the current RSS in bytes (psutil; ru_maxrss converted per platform); a refusal at the global deadline returns DEADLINE without fallback work; v2.11 round 19: SIGNED EVIDENCE EXPANSION as an exact algebraic operator (signed_evidence.py): the independent-root noisy-OR chain family is recognised on the ORIGINAL model before closure (0.1 s allowance), executed right after closure under the remaining deadline and a 256 MiB / headroom workspace budget, and finalised directly on the original queries (outward dyadic 2^-40 enclosures, DETERMINISTIC; no closure decoder / scalar); typed refusals fall back to the existing route; --no-evidence-expansion = the R18 comparator path; v2.10.1 round 18 bounds fix: the closure allowance runs from the closure start, the deadline is polled at entry and per factor while materialising the support rows; v2.10: EXACT SUPPORT CLOSURE before the partition -- generalized arc consistency + batched factor-implied bijection quotient + weight-preserving substitution to a fixed point (support_closure.py), bounded by a 0.5 s allowance and a 128 MiB live-byte ceiling with a typed fallback to the original model; the engine runs on the reduced model and every ORIGINAL requested coordinate is decoded (fixed -> EXACT 1/0, outside the image -> EXACT 0, alias -> its representative row), nothing published without the positive-mass witness, the original denominator kept; --no-support-closure = the frozen v2.9.4 path; v2.9.4 round 17: response-cache charge measures the retained objects (sys.getsizeof + payload + dict growth), the optional cache is allotted from the capacity left after the mandatory plan and never enters cap admission, the cache helper polls the deadline at entry; v2.9.3 round 16: shared-block responses reused ACROSS batches (byte-budgeted cache keyed by the full boundary assignment; same deterministic value and envelope; failures never cached; counted in the memory plan); v2.9.2 round 15: raw reverse outputs consumed as each rescaled derivative is made (no second retained output set); blocks whose dense precomputation window expired take the shared representation instead of being skipped (all requested queries eligible); v2.9.1 round 14: reverse pass releases a message mantissa at its CONSUMER step (proved lifetime invariant; v2.9 released at its own step, so mantissa and derivative coexisted), memory plan simulates the implemented lifetimes incl. transient member outputs; v2.9 round 13: exact route executes under the contract for unsplit constructions: tiled reverse step (TILE_BUDGET), forward tables released after use with a deterministic rebuild for the PAC fallback, trace-simulated reverse live bytes in the memory plan; shared path: explicit fixed workspace term, deadline polled at entry and per factor gather, checked exponent conversion (no clamp); v2.8 round 12 repair: shared recovery under the FT range lemma (per-sample range bits, product pre-checks, finite checks, static preflight, typed refusal preserving the completed prefix); trace-simulated live-bytes bound and microbatch policy; deadline polled inside the shared forward / backward; active-row + unique-boundary evaluation; executor cross-check under a joint host budget; v2.7.1: a deadline inside a shared-response batch abandons only that batch and reports the retained draws / certificate state; the backward pass keeps message mantissas (v2.7 freed them and broke the PAC fallback after a refused exact route: CSP_13 crash); v2.7 round 11 post-freeze RESOURCE patch: forward mantissas released as their log tables are built; backward derivatives and consumed messages freed per step; exact-route peak estimate in the memory policy (typed skip); v2.6 round 11: guarded deterministic ratios + validated publication (F1); compact root allowance (F2); exact route before any PAC preparation; process-wide memory policy (dry-run planner, cap ladder, usable 2.5 GiB, lazy sampler tables, forward messages released); shared block recovery for both routes (exact: one backward per block seeded by D_b; PAC: batched clamped-boundary responses when dense tables do not fit); batch size under the policy; v2.5 round 10: compact conservative error bounds everywhere (no exact powers / long exact products); byte-budgeted interior-query recovery with in-place stacking (typed RESOURCE skips); interior deadline check in the backward pass; v2.4 round 9: incremental scalar products; WMB weights as exact Fractions summing to 1 within the admitted domain (> 20 groups rejected); pass-through envelope + float-only message error with domain-checked conversions; proposal selection by CERTIFIED caps; v2.3 round 8: root derivatives = products of the other scalar roots (disconnected components); a requested executor cross-check must succeed and cover every published separator coordinate; dyadic 2^-52 outward compaction of deterministic enclosures; coherent guarantee labels; v2.2 round 7: split census; EXACT ROUTE for unsplit constructions = shared backward differential + per-block retained VE, deterministic intervals, existing certified executor as independent cross-check of the separator marginals; v2.1 round 5: power-of-two exponents cancelled exactly before any float log; widening from the actual tracked log magnitudes; v2 round 4: exact-rational error bounds, product underflow pre-check, conservative inversion, batch loop, lambda schedules)'
UF = F(1, 1 << 53); U = 2.0 ** -53
RANGE_BUDGET = 1000                  # bits: sum of operand ranges allowed in ONE product (its smallest nonzero entry stays >= 2^-1000 of its max: normal, nonzero)
RANGE_BITS = 900                     # a table whose smallest nonzero entry is below 2^-900 of its maximum is refused outright
MIN_BITS = 64
PROB_TRUNC_LOG2 = -900
FLOAT_BYTE_CAP = 256 << 20
PROCESS_HEADROOM_BYTES = 160 << 20      # process overhead / numpy headroom reserved in the memory plan (measured 105-242 MiB on the panel)
CAP_LADDER = (1 << 22, 1 << 20, 1 << 18, 1 << 16, 1 << 14, 1 << 12, 1 << 10)
USABLE_BYTES = 2560 << 20               # usable ceiling of the 3 GiB contract for the process-wide memory plan (module-level so a control can inject a smaller limit)
TILE_BUDGET = 256 << 20                 # workspace budget of ONE tiled reverse step of the exact route ((2k + 3) tile-sized arrays)
RESPONSE_CACHE_BUDGET = 64 << 20        # MAXIMUM retained bytes of shared-block responses reused across batches; the per-solve allowance is min(this, the capacity left after the mandatory plan) and 0 when no block is shared: the OPTIONAL cache never lowers the proposal cap or refuses a route
BATCH_BUDGET = 384 << 20                # ONE budget for everything allocated per batch in the stream: the response matrix + certificate temporaries + the shared-block workspace (chunked)
LAYERED_CONTRACTION_DEFAULT = True      # round 20: the certified layered-contraction constructor (local blocks joined by matching binary channels -> a checked elimination order run by the existing certified native executor); frozen-path suites set it False
LAYERED_RECOGNITION_S = 1.0             # recognition allowance of the layered constructor (also bounded by the global deadline); charged
LAYERED_BYTE_CAP = 1536 << 20           # ceiling of the layered route's forecast live state (also bounded by USABLE_BYTES - current RSS); the executor's own kernel cap is the hard bound
EVIDENCE_EXPANSION_DEFAULT = True       # round 19: the signed evidence-expansion operator (exact inclusion-exclusion for the recognised independent-root noisy-OR chain family); frozen-path suites set it False
EVIDENCE_RECOGNITION_S = 0.1            # recognition allowance (also bounded by the global deadline); charged
EVIDENCE_WORKSPACE_BUDGET = 256 << 20   # ceiling of the operator's incremental retained state; also bounded by the headroom left under USABLE_BYTES
SUPPORT_CLOSURE_DEFAULT = True          # the production default; the frozen-path control suites set it False (they exercise the comparator path)
SUPPORT_CLOSURE_SHARE_S = 0.5           # declared allowance of the OPTIONAL exact support closure, measured from its own start, inside the worker budget (charged either way; refusal -> original model)
SUPPORT_CLOSURE_BYTE_CEILING = 128 << 20  # ceiling of its additional live workspace estimate (rows, maps, decoder, rewritten tables)
RECOVERY_BYTE_BUDGET = 512 << 20          # total bytes of RETAINED recovered query tables (stacked per block); beyond it the remaining interior queries are typed RESOURCE (NOT_PUBLISHED), never a memory kill


class RangeRefused(Exception): pass


def rup(x, bits=200):
    """round a nonnegative Fraction UP onto the 2^-bits grid: keeps every tracked bound an upper bound while bounding its size (the WMB power-sum bounds square per level otherwise)"""
    x = F(x); q = 1 << bits; return F(-((-x * q).numerator // (-x * q).denominator), q) if x > 0 else F(0)


# ---------------------------------------------------------------- compact conservative error bounds (round 10): never an exact power or a long exact product
def pow1pu(k):
    """upper bound of (1 + u)^k - 1 for k >= 0: (1 + u)^k <= e^(k u) <= 1 + k u + (k u)^2 for k u <= 1 (refused beyond); a small Fraction regardless of k"""
    x = F(max(0, int(k))) * UF
    if x > 1: raise RangeRefused('rounding count %d too large for the compact bound' % k)
    return x + x * x


def comb(*rhos):
    """upper bound of prod (1 + rho_i) - 1: with S = sum rho_i <= 1, prod (1 + rho_i) <= e^S <= 1 + S + S^2 (refused beyond); rounded up onto the 2^-200 grid"""
    S = F(0)
    for r in rhos: S += F(r)
    if S < 0: raise RangeRefused('negative error bound')
    if S > 1: raise RangeRefused('accumulated relative error %s too large' % float(S))
    return rup(S + S * S)


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
    union = tuple(sorted(set().union(*(set(f.scope) for f in fts)))); P = None; e = 0
    for f in fts:
        a = f.M.reshape([cards[v] if v in f.scope else 1 for v in union]); P = a if P is None else P * a; e += f.e
    return union, P, e, comb(*[f.rho for f in fts], pow1pu(len(fts) - 1))


def ft_eliminate(bucket, v, cards, agg='sum'):
    union, P, e, rho = ft_product(bucket, cards); ax = union.index(v); n = cards[v]
    if agg == 'sum': R = P.sum(axis=ax); rho = comb(rho, pow1pu(n - 1))
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
def mb_plan(scopes, cards, cap):
    """DRY RUN of the mini-bucket partition on scopes only (no tables): returns dict(forward_bytes, log_bytes, max_table, splits, steps, peak_step_bytes) for the memory policy"""
    live = [(tuple(sc), None) for sc in scopes]; vars_ = sorted({v for sc, _ in live for v in sc}); fwd = 0; logs = 0; mx = 0; splits = 0; steps = 0; peak = 0
    created = {}; consumed = {}; rec = []; scalar_steps = set()            # message lifetimes (message id = creation step) for the reverse-pass live-bytes simulation
    while vars_:
        best = None
        for v in vars_:
            nb = set().union(*(set(sc) for sc, _ in live if v in sc)) - {v}; size = prod(cards[u] for u in nb) if nb else 1
            if best is None or size < best[0]: best = (size, v)
        v = best[1]; vars_.remove(v); bucket = [t for t in live if v in t[0]]; live = [t for t in live if v not in t[0]]; steps += 1
        if not bucket: continue
        bucket.sort(key=lambda t: -len(t[0])); groups = []
        for sc, mid in bucket:
            for g in groups:
                u = g[0] | set(sc)
                if prod(cards[x] for x in u) <= cap: g[0] = u; g[1].append((sc, mid)); break
            else: groups.append([set(sc), [(sc, mid)]])
        splits += len(groups) - 1
        for gi, (u, members) in enumerate(groups):
            usz = prod(cards[x] for x in u); msz = usz // cards[v]; peak = max(peak, usz * 8 * 2); mx = max(mx, msz); si = len(rec)
            for sc, mid in members:
                if mid is not None: consumed[mid] = si
            nsc = tuple(x for x in sorted(u) if x != v); created[si] = msz if nsc else 1; rec.append((si, len(members), usz, [mid for _, mid in members if mid is not None], [prod(cards[x] for x in sc) for sc, _ in members])); scalar_steps.add(si) if not nsc else None   # a scalar message is a 0-d array: one entry
            fwd += created[si] * 8
            if nsc: live.append((nsc, si))
            if gi == 0: logs += sum(prod(cards[x] for x in sc) * 8 for sc, _ in members)
    # reverse pass, IMPLEMENTED lifetimes (round 14): a message's mantissa is released right after its CONSUMER's reverse step has used it; its derivative is created at that same step and
    # popped at its own reverse step. So at reverse step s (steps > s processed): message m with c(m) <= s < k(m) has only D alive, m with k(m) <= s has only M alive, m with c(m) > s has
    # neither -> the persistent payload is the prefix sum of message sizes up to s (maximal at the start = all forward tables). TRANSIENT at step s: the members' derivative outputs
    # (member sizes; their mantissas are still alive) + the rescale copy of the largest member + the derivative of R itself (DR, alive, created at its consumer). Simulated per step.
    # a SCALAR message (0-d root) is never released and its derivative (8 bytes, from the root product) is alive from the start until its own step: both are counted.
    rev_live = 0; pref = sum(created.values()) + len(scalar_steps)
    for si, k, usz, mids, msizes in reversed(rec):
        rev_live = max(rev_live, (pref + sum(msizes) + max(msizes + [0])) * 8); pref -= 1 if si in scalar_steps else created[si]                      # a scalar's derivative is popped at its step; its mantissa stays
    return dict(forward_bytes=fwd, log_bytes=logs, max_table=mx, splits=splits, steps=steps, peak_step_bytes=peak, reverse_live_bytes=rev_live, max_k=max([k for _, k, _, _, _ in rec] + [1]))


def memory_plan(scopes, cards, mb_cap, base_bytes):
    """the process-wide plan: the requested cap first (2^24 maximum), then the fixed ladder downwards; planned peak during construction = base + forward messages + one step's product
    workspace (x2 for the max copy); during PAC = base + sampler logs (the forward tables are released as they are built) + the dense recovery budget + the per-batch budget
    (response matrix + certificate temporaries + shared workspace). Returns (cap_used or None, plan or None, the caps tried with their planned peaks)."""
    tried = []
    for cap_try in [mb_cap] + [c for c in CAP_LADDER if c < mb_cap]:
        pl = mb_plan(scopes, cards, cap_try)
        construct_peak = base_bytes + pl['forward_bytes'] + pl['peak_step_bytes']; pac_peak = base_bytes + pl['log_bytes'] + min(RECOVERY_BYTE_BUDGET, 1 << 62) + BATCH_BUDGET
        tried.append(dict(cap=cap_try, construct_peak=construct_peak, pac_peak=pac_peak, splits=pl['splits'], fits=(construct_peak <= USABLE_BYTES and pac_peak <= USABLE_BYTES)))
        if tried[-1]['fits']: return cap_try, pl, tried
    return None, None, tried


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
                    self.scalars.append(R)
            steps.append((v, groups[0][1]))
        rhoU = comb(*[r.rho for r in self.scalars], pow1pu(len(self.scalars)))                      # ONE bounded-size combination of the scalar-root allowances (F2)
        self.steps = steps; self.order = order; self.rhoU = rhoU; self.logU_f = logU_f; self.E_U = E_U; self.logU = (logU_f + E_U) if logU_f > -inf else -inf; self.n_scalar = n_scalar
        self.max_table = max((f.M.size for _, q1 in steps if q1 for f in q1), default=0); self.max_q1 = max((len(q1) for _, q1 in steps if q1), default=0)
        self.prep = None                                     # sampler log tables are built LAZILY (prepare_sampler), only when the PAC route is taken
        self.step_ranges = [[f.R for f in q1] if q1 else [] for _, q1 in steps]

    def prepare_sampler(self, release_forward=True):
        """build the per-step log2 tables of the summed mini-bucket members for the batch sampler, INTERLEAVED with the release of forward message mantissas: a message that is only a
        max-group member is released at once (never sampled); a summed member's mantissa is released right after its log table is built, so the forward tables and the log tables
        never coexist in full (peak ~ max(forward, logs) + one table)"""
        if self.prep is not None: return
        self.prep = []; cards = self.cards; inputs = {id(f) for f in self.inputs}
        if release_forward:
            summed = {id(f) for _, q1 in self.steps if q1 for f in q1}
            for v, bucket, R in self.fwd:
                for f in bucket:
                    if id(f) not in inputs and id(f) not in summed and f.scope: f.M = None          # max-group members: not needed by any later computation
        for v, q1 in self.steps:
            if q1 is None: self.prep.append((v, None)); continue
            tabs = []
            for f in q1:
                with np.errstate(divide='ignore'): LM = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape(-1)
                strides = {}; s_ = 1
                for u in reversed(f.scope): strides[u] = s_; s_ *= cards[u]
                tabs.append((LM, strides, f.scope))
                if release_forward and id(f) not in inputs and f.scope: f.M = None                   # released right after its log table exists
            self.prep.append((v, tabs))
        if release_forward: self.fwd = []

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
W_MIN = F(1, 20)                    # admitted weight domain: every weight is an EXACT Fraction >= 1/20 (so 1 / w <= 20); weights of a bucket sum to 1 EXACTLY; buckets with more than 20 groups are REJECTED (typed) -> max proposal
WMB_GRID = [(F(1, 2), F(1, 2)), (F(3, 10), F(7, 10)), (F(7, 10), F(3, 10)), (F(3, 20), F(17, 20)), (F(17, 20), F(3, 20))]      # the FIXED weight policy for 2-group buckets; m groups -> equal weights 1/m


def rel_from_log(d):
    """2^d - 1 <= 1.45 d (1 + d) for 0 <= d <= 1/4 (domain CHECKED, never assumed)"""
    d = F(d)
    if d < 0 or d > F(1, 4): raise RangeRefused('log-error %s outside the proved conversion domain [0, 1/4]' % float(d))
    return F(145, 100) * d * (1 + d)


def log_from_rel(r):
    """log2(1 + r) <= 1.45 r for 0 <= r <= 1 (domain CHECKED)"""
    r = F(r)
    if r < 0 or r > 1: raise RangeRefused('relative error %s outside the proved conversion domain [0, 1]' % float(r))
    return F(145, 100) * r


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
            m = len(groups)
            if m > 1 and F(1, m) < W_MIN: raise RangeRefused('wmb: %d groups in one bucket exceed the admitted weight domain (w >= %s)' % (m, W_MIN))
            w = [F(1, m)] * m
            glog = []; gE = []; grho = []; gunion = []
            for g in groups:
                union, P, e, rho = ft_product_log(g, cards); glog.append(P); gE.append(e); grho.append(rho); gunion.append(union)
            if m > 1 and tnow() - t0 < opt_s:                       # FIXED policy: equal weights, and for two groups the best of the grid by the bucket's total raw log2 bound
                best = None
                for wc in ([tuple(w)] + (WMB_GRID if m == 2 else [])):
                    assert sum(wc) == 1 and all(x >= W_MIN for x in wc)
                    tot = 0.0
                    for r in range(m):
                        ax = gunion[r].index(v); Lr = np.moveaxis(glog[r], ax, -1); logM, _, dead = _powsum_log(Lr, float(wc[r])); tot += float(np.where(np.isfinite(logM), logM, 0.0).sum())
                    if best is None or tot < best[0]: best = (tot, wc)
                w = list(best[1])
            self.weights.append(w); self.groups_per_step.append(groups)
            # messages
            step_tabs = []
            for r, g in enumerate(groups):
                wf = float(w[r]); ax = gunion[r].index(v); Lr = np.moveaxis(glog[r], ax, -1); logM, _, dead = _powsum_log(Lr, wf); nsc = tuple(u for u in gunion[r] if u != v)
                # NOTE section 11. The weighted power sum is positively homogeneous: the inputs' multiplicative envelope (1 +- grho) passes through EXACTLY (no conversion). The FLOAT
                # operations add an absolute log2 error d_M: member log2 lookups u(R + 1) each, the row log-sum u(q + 1)(SR + q), the subtraction of Lmax u(SR + 2), the division by the
                # float weight u (mag + 1) with mag = SR / w + log2 n + 2 (w itself rounded: + u mag), exp2 (4u rel) and the row sum ((n - 1) u rel) converted to log, the log2 of the sum
                # u (log2 n + 2), the multiplication by w (u (mag + 1)) and the final addition of Lmax (u (SR + mag + 2)). rho_float = rel_from_log(d_M) (domain checked).
                n = cards[v]; Rsum = sum(f.R for f in g); q = len(g); mag = F(Rsum) / w[r] + int(n).bit_length() + 2
                d_M = sum(UF * (f.R + 1) for f in g) + UF * (q + 1) * (Rsum + q) + UF * (Rsum + 2) + 2 * UF * (mag + 1) + log_from_rel(4 * UF + (n - 1) * UF) * w[r] + UF * (int(n).bit_length() + 2) * w[r] + UF * (mag + 1) + UF * (Rsum + mag + 2)
                rho_float = rup(rel_from_log(d_M)); self.rho_steps.append(rho_float)
                rhoM = comb(grho[r], rho_float)                                                  # envelope relative to the exact power sum of EXACT inputs: pass-through times the float error
                Mfl = np.where(np.isfinite(logM), np.exp2(logM - np.floor(np.where(np.isfinite(logM), logM, 0.0))), 0.0); Efl = np.where(np.isfinite(logM), np.floor(np.where(np.isfinite(logM), logM, 0.0)), 0.0)
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
        self.logU = (self.logU_f + self.E_U) if self.logU_f > -inf else -inf; self.rhoU = comb(*[r.rho for r in self.scalars], pow1pu(len(self.scalars)))   # pass-through envelope of U vs the exact weighted bound
        self.splits = sum(len(g) - 1 for g in self.groups_per_step); self.max_range_sum = ref.max_range_sum; self.max_table = ref.max_table; self.max_q1 = ref.max_q1
        # precompute per-step log tables of the group members for the sampler
        self.prep = []
        for v, tabs in self.steps:
            if tabs is None: self.prep.append((v, None)); continue
            comps = []
            for g, union, ax, wr in tabs:
                wr = float(wr); mem = []
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
    union = tuple(sorted(set().union(*(set(f.scope) for f in fts)))); L = None; e = 0
    for f in fts:
        with np.errstate(divide='ignore'): lm = np.where(f.M > 0, np.log2(np.maximum(f.M, 1e-300)), -inf).reshape([cards[v] if v in f.scope else 1 for v in union])
        L = lm if L is None else L + lm; e += f.e
    return union, np.broadcast_to(L, [cards[v] for v in union]).copy(), e, comb(*[f.rho for f in fts], pow1pu(len(fts) - 1))


# ---------------------------------------------------------------- SHARED all-query recovery (round 11): per block, one batched forward / backward pass with the sampled boundary clamped
class SharedBlock:
    """block b: original (evidence-restricted) factors as FTs over (boundary vars in b.scope) U (interior vars); interior elimination order = the block's recorded order.
    responses(S_batch, deadline) -> (f (B, K_b) conditional responses P(x = a | boundary = s_b) for every interior query column, root mantissa / exponent (B,)).
    NUMERICAL DISCIPLINE (round 12, the same lemma as the FT kernel): every live array carries per-sample RANGE BITS R (its smallest nonzero entry is >= 2^-R of its row maximum,
    rows rescaled to a maximum in [1, 2)); before EVERY product the per-sample sum of the operands' R must be <= RANGE_BUDGET (so no positive product can round to zero),
    else the batch is refused (RangeRefused); row maxima are checked finite after every rescale; the final ratio is formed with an exact power-of-two ldexp and a response
    above 1 + tolerance is a certificate defect. A data-independent PREFLIGHT at construction refuses a block whose restricted original factors alone exceed the budget.
    MEMORY: the forward product P is NOT stored (it is rebuilt from the prefix products in the backward pass); derivatives are computed only for messages (never for original
    factors) and dropped once consumed; `bytes_per_sample` is a trace-simulated bound on the simultaneously live arrays + per-step workspace, used by the chunking policy."""
    def __init__(self, blk, fac_fts, interior_order, cards, pos):
        self.cards = cards; self.pos = pos; self.bvars = tuple(blk.scope); self.order = [v for v in interior_order]; self.facs = []
        bset = set(self.bvars)
        for f in fac_fts:
            bv = tuple(u for u in f.scope if u in bset); iv = tuple(u for u in f.scope if u not in bset)
            M = f.M.reshape([cards[u] for u in f.scope]); perm = [f.scope.index(u) for u in bv] + [f.scope.index(u) for u in iv]
            M2 = np.ascontiguousarray(np.transpose(M, perm)).reshape(prod(cards[u] for u in bv) if bv else 1, prod(cards[u] for u in iv) if iv else 1)
            self.facs.append(dict(bv=bv, iv=iv, M2=M2, e=f.e, rho=f.rho, R=f.R))
        self.cols = [(x, a) for x in self.order for a in range(cards[x])]
        # ---- trace simulation (scopes only): operation count for the error bound, static range preflight, per-sample live-bytes bound
        nmul = 0; nsum = 0; live = [(set(f['iv']), prod(cards[u] for u in f['iv']) if f['iv'] else 1, f['R'], None) for f in self.facs]      # (scope, size, static R or None for messages, creation step)
        nfac_floats = sum(sz for _, sz, _, _ in live); msgs = []; steps = []; mu = 1; fwd_peak = 0
        for si, v in enumerate(self.order):
            bucket = [t for t in live if v in t[0]]; live = [t for t in live if v not in t[0]]
            if not bucket: continue
            u = set().union(*(t[0] for t in bucket)); usz = prod(cards[x] for x in u); mu = max(mu, usz); k = len(bucket)
            rstat = sum(t[2] for t in bucket if t[2] is not None)
            if rstat > RANGE_BUDGET: raise RangeRefused('shared block preflight: the restricted original factors of one elimination step span %d range bits > %d (interior variable %d)' % (rstat, RANGE_BUDGET, v))
            nmul += 2 * (k + 1); nsum += cards[v] + usz
            for t in bucket:
                if t[3] is not None: msgs[t[3]]['consumed'] = si
            nsc = u - {v}; msz = prod(cards[x] for x in nsc) if nsc else 1; msgs.append(dict(size=msz, created=si, consumed=None)); live.append((nsc, msz, None, len(msgs) - 1))
            steps.append(dict(si=si, k=k, usz=usz, v=v))
            fwd_peak = max(fwd_peak, nfac_floats + sum(m['size'] for m in msgs) + 2 * usz)                                  # all restricted factors + all messages so far + P and its rescale copy
        self.rho_f = comb(*[f['rho'] for f in self.facs], pow1pu(nmul + nsum + 4))
        self.rho_f = comb(self.rho_f, self.rho_f, F(1, 1 << 1000))        # numerator and denominator each carry the bound; + the absolute 2^-1021 of a subnormal / underflowed final ratio
        self.tol = 2.0 * fup(self.rho_f) + 2.0 ** -40                    # a response above 1 + tol is a defect (the true conditional probability is <= 1)
        self.max_union = mu
        bwd_peak = 0; msg_total = sum(m['size'] for m in msgs)
        for st in reversed(steps):
            si = st['si']; crossing = sum(m['size'] for m in msgs if m['created'] <= si and (m['consumed'] is None or m['consumed'] > si))    # derivatives alive at this backward step
            ws = (2 * st['k'] + 5) * st['usz'] + cards[st['v']]                                                                               # prefix / suffix (k each), P, full, Pm, Dm + rescale copy, Nv
            bwd_peak = max(bwd_peak, nfac_floats + msg_total + crossing + ws)
        self.bytes_per_sample = 8 * (max(fwd_peak, bwd_peak) + len(self.cols) + 6 * len(self.facs) + 16)                                   # ARRAY PAYLOAD per sample (+ the response row, index / exponent / range arrays)
        self.fixed_workspace_bytes = (16 << 10) + (1 << 10) * (len(self.facs) + 6 * len(steps) + len(self.cols))                        # allocation overhead that does not scale with B: array objects, views, dicts / lists (reviewer: 7.9 KiB at one variable, 35 KiB over the payload on a 40-step chain)
    def _restricted(self, f, Sb):
        if f['bv']: idx = np.zeros(Sb.shape[0], dtype=np.int64)
        else:
            dims = tuple(self.cards[u] for u in f['iv'])
            return np.broadcast_to(f['M2'][0].reshape(dims), (Sb.shape[0],) + dims) if f['iv'] else np.broadcast_to(f['M2'][0, 0], (Sb.shape[0],))
        s_ = 1
        for u in reversed(f['bv']): idx += Sb[:, self.pos[u]] * s_; s_ *= self.cards[u]
        R = f['M2'][idx]; return R.reshape((Sb.shape[0],) + tuple(self.cards[u] for u in f['iv'])) if f['iv'] else R.reshape(Sb.shape[0])
    @staticmethod
    def _rescale(A, E):
        """per-sample power-of-two rescaling: A (B, ...) -> mantissas with row max in [1, 2) (zero rows stay zero), E (B,) += exponents (exact); returns the per-sample range bits R
        (smallest nonzero entry >= 2^-R of the row max; 0 for a zero row); refuses non-finite rows"""
        flat = A.reshape(A.shape[0], -1); m = flat.max(axis=1)
        if not np.all(np.isfinite(m)): raise RangeRefused('shared block: a non-finite value appeared in a batched table')
        nz = m > 0; k = np.zeros(A.shape[0]); k[nz] = np.floor(np.log2(m[nz])); sc = np.exp2(-k); out = (flat * sc[:, None])
        mn = np.where(out > 0, out, inf).min(axis=1); R = np.zeros(A.shape[0], dtype=np.int64); fin = np.isfinite(mn); R[fin] = np.ceil(-np.log2(mn[fin])).astype(np.int64) + 1
        return out.reshape(A.shape), E + k, R
    @staticmethod
    def _check_range(Rs, where):
        tot = Rs[0].copy()
        for r in Rs[1:]: tot = tot + r
        if tot.size and int(tot.max()) > RANGE_BUDGET: raise RangeRefused('shared block %s: a product of %d batched tables could underflow (range bits %d > %d on %d of %d samples)' % (where, len(Rs), int(tot.max()), RANGE_BUDGET, int((tot > RANGE_BUDGET).sum()), tot.size))
    def responses(self, Sb, deadline=inf):
        if tnow() >= deadline: raise Deadline('shared_entry')
        B = Sb.shape[0]; cards = self.cards; live = []; msg_ids = set()
        for f in self.facs:
            if tnow() >= deadline: raise Deadline('shared_gather')
            A = np.array(self._restricted(f, Sb), dtype=float); E = np.full(B, float(f['e'])); A, E, R = self._rescale(A, E); live.append([f['iv'], A, E, R])
        steps = []
        for v in self.order:
            if tnow() >= deadline: raise Deadline('shared_forward')
            bucket = [t for t in live if v in t[0]]; live = [t for t in live if v not in t[0]]
            if not bucket: continue
            union = tuple(sorted(set().union(*(set(t[0]) for t in bucket)))); self._check_range([t[3] for t in bucket], 'forward')
            P = None; E = np.zeros(B)
            for sc, A, Ea, _ in bucket:
                P = (A.reshape((B,) + tuple(cards[u] if u in sc else 1 for u in union)) if P is None else P * A.reshape((B,) + tuple(cards[u] if u in sc else 1 for u in union))); E = E + Ea
            P = np.broadcast_to(P, (B,) + tuple(cards[u] for u in union)); ax = 1 + union.index(v); Msg = P.sum(axis=ax); del P
            Msg, Em, Rm = self._rescale(Msg, E); nsc = tuple(u for u in union if u != v); ent = [nsc, Msg, Em, Rm]; msg_ids.add(id(Msg))
            steps.append((v, bucket, union, E, ent)); live.append(ent)
        # root (per sample): product of the remaining scalars (range-checked)
        if live: self._check_range([t[3] for t in live], 'root')
        root = np.ones(B); Esum = np.zeros(B)
        for sc, A, Ea, _ in live: root = root * A.reshape(B); Esum = Esum + Ea
        root, Er, Rr = self._rescale(root.reshape(B, 1), Esum.copy()); root = root.reshape(B)
        # backward: D for every remaining scalar, from the root (derivative 1 per sample times the OTHER remaining scalars: zero-safe prefix / suffix)
        D = {}; k = len(live)
        if k:
            pre = [None] * k; suf = [None] * k; acc = None
            for i in range(k): pre[i] = acc; acc = live[i][1].reshape(B) if acc is None else acc * live[i][1].reshape(B)
            acc = None
            for i in range(k - 1, -1, -1): suf[i] = acc; acc = live[i][1].reshape(B) if acc is None else acc * live[i][1].reshape(B)
            for i in range(k):
                if id(live[i][1]) not in msg_ids: continue                                        # derivatives are needed only for MESSAGES (seeds of earlier steps), never for original factors
                d = np.ones(B)
                if pre[i] is not None: d = d * pre[i]
                if suf[i] is not None: d = d * suf[i]
                d, Ed, Rd = self._rescale(d.reshape(B, 1), Esum - live[i][2]); D[id(live[i][1])] = (d.reshape(B), Ed, Rd)       # exponent of prod_{j != i} m_j
            del pre, suf
        f = np.zeros((B, len(self.cols))); ci = {c: j for j, c in enumerate(self.cols)}; rootpos = root > 0; rsafe = np.where(rootpos, root, 1.0)
        while steps:
            if tnow() >= deadline: raise Deadline('shared_backward')
            v, bucket, union, E, ent = steps.pop(); Msg = ent[1]
            DR, Ed, Rd = D.pop(id(Msg), (None, None, None))
            if DR is None: DR = np.ones(B); Ed = np.zeros(B); Rd = np.ones(B, dtype=np.int64)
            self._check_range([t[3] for t in bucket] + [Rd], 'backward')
            nsc = tuple(u for u in union if u != v)
            DRb = DR.reshape((B,) + tuple(1 for _ in union)) if DR.ndim == 1 else DR.reshape((B,) + tuple(cards[u] if u in nsc else 1 for u in union))
            k = len(bucket); As = [t[1].reshape((B,) + tuple(cards[u] if u in t[0] else 1 for u in union)) for t in bucket]
            pre = [None] * k; suf = [None] * k; acc = None
            for i in range(k): pre[i] = acc; acc = As[i] if acc is None else acc * As[i]
            P = acc; acc = None                                                                   # P = the full bucket product (rebuilt, not stored)
            for i in range(k - 1, -1, -1): suf[i] = acc; acc = As[i] if acc is None else acc * As[i]
            full = np.broadcast_to(P * DRb, (B,) + tuple(cards[u] for u in union)); del P
            axes = tuple(1 + i for i, u in enumerate(union) if u != v); Nv = full.sum(axis=axes) if axes else full; Nv = Nv.reshape(B, cards[v]); del full
            ex = E + Ed - Er                                                                       # exact integer exponents (E, Ed, Er hold integers far below 2^53)
            if not np.all(np.abs(ex) < 2.0 ** 30): raise RangeRefused('shared block: exponent difference outside the admitted domain')
            ex = ex.astype(np.int64)
            assert int(ex.max(initial=-1)) <= 1023, 'shared conditional response exponent %d > 1023: N_v / r >= 2^-1001 by the range lemma, so a true ratio <= 1 cannot need it (certificate defect)' % int(ex.max())
            val = np.ldexp(Nv / rsafe[:, None], np.maximum(ex, -2200)[:, None]); val = np.where(rootpos[:, None], val, 0.0)   # ex < -2200 gives exactly 0 for any mantissa < 2^80: the floor is value-preserving; an underflow in the ratio is an ABSOLUTE error <= 2^-1021, inside rho_f
            assert np.all(np.isfinite(val)) and float(val.max(initial=0.0)) <= 1.0 + self.tol, 'shared conditional response exceeds 1 beyond its error bound (certificate defect): max %r' % float(val.max())
            for a in range(cards[v]): f[:, ci[(v, a)]] = np.clip(val[:, a], 0.0, 1.0)
            for i, (sc, A, Ea, Ra) in enumerate(bucket):
                if id(A) not in msg_ids or not sc: continue                                       # only messages need a derivative
                Pm = DRb
                if pre[i] is not None: Pm = Pm * pre[i]
                if suf[i] is not None: Pm = Pm * suf[i]
                Pm = np.broadcast_to(Pm, (B,) + tuple(cards[u] for u in union)); axes = tuple(1 + i_ for i_, u in enumerate(union) if u not in sc)
                Dm = Pm.sum(axis=axes) if axes else np.array(Pm); Dm = Dm.reshape((B,) + tuple(cards[u] for u in sc)); Dm, Edm, Rdm = self._rescale(Dm, (E - Ea) + Ed); D[id(A)] = (Dm, Edm, Rdm)
            del pre, suf, As, DRb
        return f, root, Er

def cache_entry_bytes(key, row, n_before):
    """conservative charge for ONE retained cache entry: the owning ndarray object + payload, the key tuple and its int objects (sys.getsizeof, so platform-aware), plus the dictionary's
    share: CPython dicts grow by doubling into a new table while the old one is still alive, so each entry is charged 2 x (3 x 8 bytes of index + entry) x 2 (new + old table at the
    growth transient) = 96 bytes, and the first entry of a map carries the empty dict (sys.getsizeof({}))"""
    return sys.getsizeof(row) + row.nbytes + sys.getsizeof(key) + sum(sys.getsizeof(k) for k in key) + 96 + (sys.getsizeof({}) if n_before == 0 else 0)


def evaluate_shared(sb, Sb, act, chunk, deadline, cache):
    """responses of shared block `sb` for the ACTIVE rows `act` of the sampled batch Sb: each DISTINCT boundary assignment is evaluated once (microbatches of `chunk`) and scattered back;
    with `cache` = dict(entries={block: {boundary tuple: response row}}, bytes=int, budget=int) a boundary already evaluated in an EARLIER batch is reused (round 16): the response is
    the same deterministic function value f_b(s) with the same block-constant envelope rho_f, so reuse changes no certificate quantity; a refusal / deadline raised by the computation
    propagates before anything is stored (failures are never cached); insertion stops when the budget is reached (no eviction). Returns (fb (B, K_b) zero on inactive rows, stats)."""
    if tnow() >= deadline: raise Deadline('shared_entry')                                   # polled at entry: an all-hit call obeys the deadline like a miss (round 17)
    B = Sb.shape[0]; Kb = len(sb.cols); fb = np.zeros((B, Kb)); st = dict(active=int(act.size), unique=0, hits=0, misses=0, chunks=0)
    if not act.size: return fb, st
    bcols = [sb.pos[u] for u in sb.bvars]; uniq, inv = np.unique(Sb[act][:, bcols], axis=0, return_inverse=True); st['unique'] = int(uniq.shape[0]); fu = np.zeros((uniq.shape[0], Kb))
    ent = cache['entries'].setdefault(id(sb), {}) if cache is not None else None; todo = []
    for r in range(uniq.shape[0]):
        key = tuple(uniq[r].tolist()) if ent is not None else None
        if ent is not None and key in ent: fu[r] = ent[key]; st['hits'] += 1
        else: todo.append(r)
    st['misses'] = len(todo)
    if todo:
        if tnow() >= deadline: raise Deadline('shared_cache_miss')
        Su = np.zeros((len(todo), Sb.shape[1]), dtype=np.int64); Su[:, bcols] = uniq[todo]; fm = np.zeros((len(todo), Kb))
        for c0 in range(0, len(todo), chunk): fm[c0:c0 + chunk] = sb.responses(Su[c0:c0 + chunk], deadline)[0]; st['chunks'] += 1
        fu[todo] = fm
        if ent is not None:
            for j, r in enumerate(todo):
                key = tuple(uniq[r].tolist()); row = fm[j].copy()
                per = cache_entry_bytes(key, row, len(ent))                                        # the RETAINED objects (array object + payload, tuple, its ints, dict capacity incl. the growth transient), measured per entry
                if cache['bytes'] + per > cache['budget']: break
                ent[key] = row; cache['bytes'] += per
    fb[act] = fu[inv.reshape(-1)]; return fb, st


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
    rho_tab = comb(*[b.rho for b in blocks])
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
    """product of FT scalars with an EXACT power-of-two rescale after every multiplication (mantissa kept in [1, 2): no binary64 overflow for any number of factors), exponents as exact
    integers, one rounding (1 + u) per multiplication in the exact rho; empty product = 1; an exact zero factor gives the exact zero"""
    M = 1.0; e = 0; rhos = []; n = 0
    for f in fts:
        m = float(f.M)
        if m == 0.0: return FT((), np.array(0.0), 0, F(0))
        M *= m; n += 1; e += f.e; rhos.append(f.rho); k = frexp(M)[1] - 1; M = M * ldexp(1.0, -k); e += k
    return FT((), np.array(M), e, comb(*rhos, pow1pu(n - 1)))


def tiled_member_derivatives(DRa, As, union, cards, scopes, want, tile_budget, deadline, phase='backward_tile'):
    """{i: sum_{union minus scope_i} DRa x prod_{j != i} A_j} for i in want, over TILES of the leading union axes so that (2k + 3) tile-sized arrays fit tile_budget bytes.
    DRa / As are broadcast-shaped over `union` (size 1 along absent axes); scopes[i] are sorted tuples (as every FT scope), so a member's variables appear in union order and the
    leading / trailing split of its scope follows the union's. The sum over the leading axes outside scope_i is ACCUMULATED across tiles; the rounding bound pow1pu(nsum - 1) holds
    for any summation order of nonnegative terms."""
    full = [cards[u] for u in union]; n = len(union); k = len(As); tile_entries = max(1, tile_budget // ((2 * k + 3) * 8)); m = 0; rest = prod(full)
    while m < n and rest > tile_entries: rest //= full[m]; m += 1
    outs = {i: np.zeros([cards[u] for u in scopes[i]]) for i in want}
    for lead in itertools.product(*(range(c) for c in full[:m])):
        if tnow() >= deadline: raise Deadline(phase)
        def sl(A): return A[tuple(lead[a] if A.shape[a] > 1 else 0 for a in range(m))]
        DRt = sl(DRa); At = [sl(A) for A in As]; pre = [None] * k; suf = [None] * k; acc = None
        for i in range(k): pre[i] = acc; acc = At[i] if acc is None else acc * At[i]
        acc = None
        for i in range(k - 1, -1, -1): suf[i] = acc; acc = At[i] if acc is None else acc * At[i]
        for i in want:
            P = DRt
            if pre[i] is not None: P = P * pre[i]
            if suf[i] is not None: P = P * suf[i]
            P = np.broadcast_to(P, full[m:]); axes = tuple(a - m for a in range(m, n) if union[a] not in scopes[i]); part = P.sum(axis=axes) if axes else P
            oidx = tuple(lead[a] for a in range(m) if union[a] in scopes[i]); outs[i][oidx] += np.asarray(part).reshape([cards[u] for u in union[m:] if u in scopes[i]])
        del DRt, At, pre, suf
    return outs


def backward_derivatives(mbp, cards, deadline, release=False, tile_budget=None):
    """D[id(f)] = dZ/df over f.scope for every input block table of an UNSPLIT mini-bucket pass: D(final scalars) = 1; at step (v, bucket, R): D_f = sum_{union minus scope f} D_R x prod_{g in bucket, g != f} g
    (zero-safe: prefix / suffix products, no division). Every product is range-pre-checked and every rho exact (the same lemma as the forward pass). Round 13: the step's products are
    TILED (tiled_member_derivatives, workspace <= tile_budget) and, with release=True, a message's mantissa is freed right after its CONSUMER step has used it (round 14; its only reader
    in the reverse walk), so a message's mantissa and its derivative never coexist beyond that step; the forward tables are then gone and a PAC fallback must rebuild the construction."""
    roots = mbp.scalars; m = len(roots)
    if any(float(r.M) == 0.0 for r in roots): raise RangeRefused('backward: a zero scalar root (Z = 0 must be reported as ZERO_EVIDENCE before any normalized publication)')
    pre = [None] * m; suf = [None] * m; acc = None
    for i in range(m): pre[i] = acc; acc = roots[i] if acc is None else ft_scalar_product([acc, roots[i]])
    acc = None
    for i in range(m - 1, -1, -1): suf[i] = acc; acc = roots[i] if acc is None else ft_scalar_product([acc, roots[i]])
    D = {}; inputs_ids = {id(f) for f in mbp.inputs}
    for i, r in enumerate(roots):                                  # dZ / dr_i = prod_{j != i} r_j: the differential of the FINAL product of roots (disconnected components)
        parts = [x for x in (pre[i], suf[i]) if x is not None]; D[id(r)] = ft_scalar_product(parts) if parts else FT((), np.array(1.0), 0, F(0))
    for v, bucket, R in reversed(mbp.fwd):
        if tnow() >= deadline: raise Deadline('backward')
        DR = D.get(id(R))
        if DR is None: raise RangeRefused('backward: a message without a consumer derivative (internal)')
        union = tuple(sorted(set().union(*(set(f.scope) for f in bucket)))); k = len(bucket)
        if sum(f.R for f in bucket) + DR.R > RANGE_BUDGET: raise RangeRefused('backward product of %d tables could underflow (range bits %d > %d)' % (k + 1, sum(f.R for f in bucket) + DR.R, RANGE_BUDGET))
        A = [f.M.reshape([cards[u] if u in f.scope else 1 for u in union]) for f in bucket]; DRa = DR.M.reshape([cards[u] if u in DR.scope else 1 for u in union])
        outs = tiled_member_derivatives(DRa, A, union, cards, [f.scope for f in bucket], list(range(k)), tile_budget or TILE_BUDGET, deadline)
        for i, f in enumerate(bucket):
            e = DR.e + sum(g.e for j, g in enumerate(bucket) if j != i); rho = comb(DR.rho, *[g.rho for j, g in enumerate(bucket) if j != i], pow1pu(k))
            axes = tuple(ai for ai, u in enumerate(union) if u not in f.scope); nsum = prod(cards[union[ai]] for ai in axes) if axes else 1; rho = comb(rho, pow1pu(nsum - 1))
            raw = outs.pop(i); Df = np.asarray(raw, dtype=float).reshape([cards[u] for u in f.scope]) if f.scope else np.asarray(raw, dtype=float).reshape(())
            Df, e = _rescale(np.ascontiguousarray(Df), e); del raw                                      # the raw output is CONSUMED as soon as its rescaled copy exists (round 15): raw outputs and rescaled derivatives never accumulate together beyond one member
            D[id(f)] = FT(f.scope, Df, e, rho); del Df
        del A, DRa, outs
        if release:
            for f in bucket:
                if id(f) not in inputs_ids and f.scope: f.M = None         # the member's only reader in the reverse walk was this step (its consumer); its derivative now carries it
        if id(R) not in inputs_ids: D.pop(id(R), None)                     # the derivative of R has no further consumer
    return D



def block_numerators_exact(fac_fts, order, Db, cards, deadline):
    """EXACT ROUTE shared recovery for one block: forward FT elimination of the block's interior variables in `order` (boundary variables retained), then one backward pass seeded
    by the outward message D_b over the block's boundary scope. At the step eliminating v: N_v(a) = sum over (union minus v) of [prod bucket] x D_R  (zero-safe; no division).
    Returns {v: FT over (v,)} numerators; every bound through comb / pow1pu."""
    live = list(fac_fts); steps = []
    for v in order:
        if tnow() >= deadline: raise Deadline('block_forward')
        bucket = [f for f in live if v in f.scope]
        if not bucket: continue
        live = [f for f in live if v not in f.scope]; R = ft_eliminate(bucket, v, cards, 'sum'); steps.append((v, bucket, R)); live.append(R)
    # remaining functions are over boundary variables only; their product is g_b. Root derivatives: D_r = sum_{b.scope minus scope r} Db x prod_{others}
    D = {}; k = len(live); bsc = Db.scope
    if k:
        As = [f.M.reshape([cards[u] if u in f.scope else 1 for u in bsc]) for f in live]; Dm = Db.M.reshape([cards[u] for u in bsc])
        pre = [None] * k; suf = [None] * k; acc = None
        for i in range(k): pre[i] = acc; acc = As[i] if acc is None else acc * As[i]
        acc = None
        for i in range(k - 1, -1, -1): suf[i] = acc; acc = As[i] if acc is None else acc * As[i]
        for i, f in enumerate(live):
            if tnow() >= deadline: raise Deadline('block_root_derivatives')
            P = Dm
            if pre[i] is not None: P = P * pre[i]
            if suf[i] is not None: P = P * suf[i]
            P = np.broadcast_to(P, [cards[u] for u in bsc]); axes = tuple(ai for ai, u in enumerate(bsc) if u not in f.scope); nsum = prod(cards[bsc[ai]] for ai in axes) if axes else 1
            Df = P.sum(axis=axes) if axes else P; e = Db.e + sum(g.e for j, g in enumerate(live) if j != i); rho = comb(Db.rho, *[g.rho for j, g in enumerate(live) if j != i], pow1pu(k), pow1pu(nsum - 1))
            Df = np.asarray(Df, dtype=float).reshape([cards[u] for u in f.scope]) if f.scope else np.asarray(Df, dtype=float).reshape(()); Df, e = _rescale(np.ascontiguousarray(Df), e); D[id(f)] = FT(f.scope, Df, e, rho)
    out = {}
    for v, bucket, R in reversed(steps):
        if tnow() >= deadline: raise Deadline('block_backward')
        DR = D.get(id(R))
        if DR is None: raise RangeRefused('block backward: message without a consumer derivative (internal)')
        union = tuple(sorted(set().union(*(set(f.scope) for f in bucket)))); k = len(bucket)
        if sum(f.R for f in bucket) + DR.R > RANGE_BUDGET: raise RangeRefused('block backward product could underflow (range bits %d > %d)' % (sum(f.R for f in bucket) + DR.R, RANGE_BUDGET))
        As = [f.M.reshape([cards[u] if u in f.scope else 1 for u in union]) for f in bucket]; DRa = DR.M.reshape([cards[u] if u in DR.scope else 1 for u in union]); full = [cards[u] for u in union]
        P = DRa
        for A in As: P = P * A
        P = np.broadcast_to(P, full); ax = tuple(ai for ai, u in enumerate(union) if u != v); nsum = prod(cards[union[ai]] for ai in ax) if ax else 1
        Nv = P.sum(axis=ax) if ax else P; e = DR.e + sum(f.e for f in bucket); rho = comb(DR.rho, *[f.rho for f in bucket], pow1pu(k), pow1pu(nsum - 1))
        Nv, e = _rescale(np.ascontiguousarray(np.asarray(Nv, dtype=float).reshape([cards[v]])), e); out[v] = FT((v,), Nv, e, rho)
        pre = [None] * k; suf = [None] * k; acc = None
        for i in range(k): pre[i] = acc; acc = As[i] if acc is None else acc * As[i]
        acc = None
        for i in range(k - 1, -1, -1): suf[i] = acc; acc = As[i] if acc is None else acc * As[i]
        for i, f in enumerate(bucket):
            if id(f) in D or not f.scope: continue
            if tnow() >= deadline: raise Deadline('block_backward')
            Pm = DRa
            if pre[i] is not None: Pm = Pm * pre[i]
            if suf[i] is not None: Pm = Pm * suf[i]
            Pm = np.broadcast_to(Pm, full); axes = tuple(ai for ai, u in enumerate(union) if u not in f.scope); nsum2 = prod(cards[union[ai]] for ai in axes) if axes else 1
            Dm = Pm.sum(axis=axes) if axes else Pm; e2 = DR.e + sum(g.e for j, g in enumerate(bucket) if j != i); rho2 = comb(DR.rho, *[g.rho for j, g in enumerate(bucket) if j != i], pow1pu(k), pow1pu(nsum2 - 1))
            Dm = np.asarray(Dm, dtype=float).reshape([cards[u] for u in f.scope]); Dm, e2 = _rescale(np.ascontiguousarray(Dm), e2); D[id(f)] = FT(f.scope, Dm, e2, rho2)
    return out

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
    """exact rational enclosure of N[v] 2^eN / (Z 2^eZ) from the float values and exact rho bounds, or None when it cannot be established:
    the denominator's LOWER endpoint z (1 - rho_Z) must be strictly positive (a positive-mass witness does not make the numerical enclosure's lower endpoint positive);
    a zero numerator is the exact zero only because float zeros are exact zeros; the result always satisfies 0 <= lo <= hi <= 1"""
    if Z.rho >= 1: return None                                                  # denominator enclosure reaches zero: UNRESOLVED (never ZERO_EVIDENCE, never a division)
    n = F(float(N.M.reshape(-1)[v])) * F(2) ** N.e; z = F(float(Z.M)) * F(2) ** Z.e
    if z <= 0: return None
    zlo = z * (1 - Z.rho); zhi = z * (1 + Z.rho)
    if zlo <= 0: return None
    if n == 0: return F(0), F(0)
    if N.rho >= 1: return F(0), F(1)                                            # numerator enclosure reaches zero from above: unresolved but valid
    lo = max(F(0), n * (1 - N.rho) / zhi); hi = min(F(1), n * (1 + N.rho) / zlo)
    if not (F(0) <= lo <= hi <= F(1)): return None
    return lo, hi


def valid_publication(lo, hi, eps):
    """exact acceptance test applied at EVERY publication boundary: 0 <= lo <= hi <= 1 and width <= 2 eps"""
    return isinstance(lo, F) and isinstance(hi, F) and F(0) <= lo <= hi <= F(1) and hi - lo <= 2 * eps


def compact_outward(lo, hi, Q=1 << 52):
    """outward dyadic compaction: L = floor(Q lo) / Q <= lo, H = ceil(Q hi) / Q >= hi, clipped to [0, 1]"""
    L = max(F(0), F(math.floor(lo * Q), Q)); H = min(F(1), F(-((-hi * Q).numerator // (-hi * Q).denominator), Q)); return L, H


def executor_crosscheck(blocks_int, S, order, deadline, cap_bytes):
    """the existing certified executor (cex/newarm/cex_executor.py) on the discovered SEPARATOR model (exact rational block tables, renumbered) and the discovered elimination order;
    returns dict(status, rows (per separator variable: list of (lo, hi) Fractions) or None, stats subset)"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
    import cex_executor as NCEX
    ren = {v: i for i, v in enumerate(S)}; cards_s = [BLOCK_CARDS[v] for v in S]
    model = dict(cards=cards_s, evidence={}, factors=[dict(scope=tuple(ren[v] for v in f.scope), values=[F(int(x)) for x in np.asarray(f.arr, dtype=object).reshape(-1).tolist()]) for f in blocks_int])
    t0 = tnow()
    try: r = NCEX.execute(model, [ren[v] for v in order], deadline=deadline, cap_bytes=cap_bytes, host_reserved_bytes=NCEX.rss_bytes())     # joint budget: the executor may use only what the host's peak leaves under the cap
    except NCEX.Stop as e: return dict(status='STOP:' + str(getattr(e, 'kind', '?')), reason=str(getattr(e, 'reason', e))[:200], wall_s=tnow() - t0)
    except Exception as e: return dict(status='ERROR', reason=repr(e)[:200], wall_s=tnow() - t0)
    return dict(status=r['status'], rows=r.get('intervals'), wall_s=tnow() - t0, max_width=(r.get('stats') or {}).get('max_width_float'), kernel_s=(r.get('stats') or {}).get('kernel_s'))


BLOCK_CARDS = None


def numerical_widening_wmb(blocks, mbp, qrhos, n_sep, maxcard, E_tot):
    """WMB cap chain (NOTE section 11): z_exact <= prod_b g_b (1 + rho_b) [tables]; Hoelder / AM-GM hold for the EXACT power sums of the STORED tables at every level; each stored message is
    within (1 +- rho_float) of the exact power sum of its stored inputs, so prod over messages (1 + rho_float) enters once; the sampler's float rows vs the exact normalized power rows of
    the stored tables (rel_rows); the implemented X vs the analysed X (rho_X). All conversions are domain-checked; a violation refuses the candidate."""
    u = UF
    def logerr(mag): return u * (F(mag) + 1)
    rho_tab = comb(*[b.rho for b in blocks])
    d_cap_rows = F(0); d_impl = F(0); mag_logq = F(0); wi = 1 / W_MIN
    for Rs in mbp.step_ranges:
        if not Rs: mag_logq += F(int(maxcard).bit_length()); continue
        SR = sum(Rs); q1 = len(Rs)
        dL = sum(logerr(R) for R in Rs) + u * (q1 + 1) * (SR + q1); dA = dL * wi + u * (F(SR) * wi + 2)
        rel_p = rel_from_log(dA) + 4 * u; rel_cond = 2 * rel_p + (maxcard - 1) * u
        rel_mix = rel_cond + mbp.max_q * u + (maxcard - 1) * u + 4 * u
        d_cap_rows += log_from_rel(rel_mix)
        d_impl += logerr(901) + logerr(int(maxcard).bit_length() + 1) + u * (mag_logq + 910); mag_logq += 901 + int(maxcard).bit_length() + 1
    rho_msgs = comb(*mbp.rho_steps) if mbp.rho_steps else F(0)
    SRb = sum(b.R for b in blocks); nb = len(blocks); d_z = sum(logerr(b.R) for b in blocks) + u * nb * (SRb + nb)
    d_U = u * mbp.n_scalar * (mbp.n_scalar + int(maxcard).bit_length() + 2) + logerr(1) * mbp.n_scalar
    max_mag = max(SRb + nb, mag_logq, mbp.n_scalar + 2, abs(E_tot)); d_fin = 4 * u * (SRb + nb + mag_logq + mbp.n_scalar + 2 + abs(E_tot))
    d_total = d_z + d_impl + d_U + d_fin; rho_X = rel_from_log(d_total)
    rho_cap = comb(rho_tab, rel_from_log(d_cap_rows), rho_msgs, rho_X)
    if rho_cap > F(1, 2): raise RangeRefused('wmb: certified cap widening %s exceeds the admitted domain' % float(rho_cap))
    rho_f = max([2 * r for r in qrhos] + [F(0)]) + max([b.rho for b in blocks]) + 4 * UF
    law = 4 * n_sep * F(maxcard + 2, 1 << 53); trunc = n_sep * F(1, 1 << 900)
    return dict(rho_X=rho_X, rho_cap=rho_cap, rho_f=rho_f, law=law, trunc=trunc, eps_num=2 * rho_X + rho_f + law + trunc, delta_log_total=d_total, max_log_mag=max_mag, rho_msgs=rho_msgs, d_cap_rows=d_cap_rows)


# ---------------------------------------------------------------- the integrated solve
def solve(model_path, budget, seed=1, table_cap=1 << 18, enum_cap=1 << 16, eps=F(1, 200), delta=F(1, 10 ** 6), mb_cap=1 << 24, construct_share=0.5, batch=1024, check_s=0.5, force_approx=False, schedule='baseline', route='auto', construct_only=False, crosscheck=True, proposal='mb', opt_s=3.0, support_closure=None, evidence_expansion=None, layered_contraction=None):
    global BLOCK_CARDS
    t_start = tnow(); deadline = t_start + budget; ph = {}; rng = np.random.default_rng(seed); stats = dict(elim_work=0, eliminations=0, query_work=0)
    out = dict(version=VERSION, seed=seed, budget_s=budget, table_cap=table_cap, enum_cap=enum_cap, mb_cap=mb_cap, batch=batch, schedule=schedule, route_requested=route, proposal=proposal, epsilon=str(eps), delta=str(delta), phases_s=ph, mechanism={}, outcome=None, answers=None)
    t0 = tnow(); model, binding = BR.core.read_uai(model_path); cards = model['cards']; n = len(cards); ev = model.get('evidence', {}); out['binding'] = binding; ph['read'] = tnow() - t0
    queries_orig = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K_orig = len(queries_orig); out['K'] = K_orig
    cards_orig, ev_orig = cards, ev; model_orig = model; closure = None; ans = {}; pending = {}; failed = []        # the closure returns a NEW reduced model; the original object stays intact for the original-bound constructors
    # ---- SIGNED EVIDENCE EXPANSION, step 1 (round 19): recognise the family on the ORIGINAL model before closure; the checked plan is immutable (closure may rewrite the model)
    if evidence_expansion is None: evidence_expansion = EVIDENCE_EXPANSION_DEFAULT
    se_plan = None; se_rec = dict(status='DISABLED')
    if evidence_expansion and route in ('auto', 'exact') and not force_approx and not construct_only:
        t0 = tnow()
        try: se_plan = SE.recognize(model, queries_orig, binding, min(deadline, t0 + EVIDENCE_RECOGNITION_S)); se_rec = dict(status='RECOGNIZED', recognition_s=se_plan.recognition_s, **SE.estimate(se_plan))
        except SE.NotApplicable as e: se_rec = dict(status='NOT_APPLICABLE: ' + str(e)[:160], recognition_s=tnow() - t0)
        except SE.RecognitionRefused as e: se_rec = dict(status='RECOGNITION_REFUSED: ' + str(e)[:160], recognition_s=tnow() - t0)
        ph['evidence_recognition'] = tnow() - t0
    elif evidence_expansion: se_rec = dict(status='SKIPPED: route %s / force_approx %s / construct_only %s' % (route, force_approx, construct_only))
    out['mechanism']['evidence_expansion'] = se_rec
    # ---- CERTIFIED LAYERED CONTRACTION, step 1 (round 20): recognise local blocks joined by matching binary channels on the ORIGINAL (evidence-restricted) model before closure; the plan is a
    # complete elimination order with a volume certificate; only when no signed plan was recognised (the signed route is the established first choice for its family)
    if layered_contraction is None: layered_contraction = LAYERED_CONTRACTION_DEFAULT
    lc_plan = None; lc_rec = dict(status='DISABLED')
    if layered_contraction and se_plan is None and route in ('auto', 'exact') and not force_approx and not construct_only:
        t0 = tnow()
        try: lc_plan = LC.recognize(model, min(deadline, t0 + LAYERED_RECOGNITION_S), binding); lc_rec = dict(status='RECOGNIZED', recognition_s=lc_plan.recognition_s, structure=lc_plan.structure, volume=lc_plan.volume, volume_recognition=lc_plan.volume_recognition)
        except LC.NotApplicable as e: lc_rec = dict(status='NOT_APPLICABLE: ' + str(e)[:200], recognition_s=tnow() - t0)
        except LC.RecognitionRefused as e: lc_rec = dict(status='RECOGNITION_REFUSED: ' + str(e)[:200], recognition_s=tnow() - t0)
        ph['layered_recognition'] = tnow() - t0
    elif layered_contraction: lc_rec = dict(status='SKIPPED: signed plan %s / route %s / force_approx %s / construct_only %s' % (se_plan is not None, route, force_approx, construct_only))
    out['mechanism']['layered_contraction'] = lc_rec
    # ---- EXACT SUPPORT CLOSURE (round 18): optional, bounded, BEFORE integerization and any partition / memory plan; the original model is kept on a typed refusal
    if support_closure is None: support_closure = SUPPORT_CLOSURE_DEFAULT
    if support_closure:
        t0 = tnow()
        try:
            cl = SC.compile_closure(model, min(deadline, t0 + SUPPORT_CLOSURE_SHARE_S), SUPPORT_CLOSURE_BYTE_CEILING); out['mechanism']['support_closure'] = cl['stats']      # the allowance runs from the closure's own start (v2.10 anchored it at worker start, so a slow read consumed it)
            if not cl['identity']: closure = cl; model = cl['reduced_model']; cards = model['cards']; n = len(cards); ev = {}
        except SC.ZeroEvidence as e:
            out['mechanism']['support_closure'] = dict(status='ZERO_EVIDENCE: ' + str(e)[:160], seconds=tnow() - t0); ph['support_closure'] = tnow() - t0
            out['outcome'] = 'ZERO_EVIDENCE'; out['positive_mass_witness'] = None; return BR.finish(out, t_start, queries_orig, {}, [])
        except SC.ClosureRefused as e: out['mechanism']['support_closure'] = dict(status='SKIPPED: ' + str(e)[:160], seconds=tnow() - t0)
        ph['support_closure'] = tnow() - t0
    else: out['mechanism']['support_closure'] = dict(status='DISABLED')
    queries = [(x, v) for x in range(n) if x not in ev for v in range(cards[x])]; K = len(queries); qix = {q: j for j, q in enumerate(queries)}; out['effective_K'] = K
    def publish(j, lo, hi, point, g): ans[j] = dict(lo=lo, hi=hi, point=point, guarantee=g)
    def finish_(oc, witness=None):
        out['outcome'] = oc
        if witness: ans.update(pending)
        out['positive_mass_witness'] = witness
        if closure is None: res = BR.finish(out, t_start, queries, ans, failed)
        else:                                                                                   # decode every ORIGINAL requested coordinate (the denominator stays K_orig)
            t1 = tnow(); ans_o, failed_o = SC.decode_rows(closure, cards_orig, ev_orig, queries_orig, qix, ans, failed, witness); ph['decode_original_queries'] = tnow() - t1
            if 'Z' in out: out['Z_reduced'] = out['Z']; out['Z'] = str(F(out['Z']) * closure['scalar'])
            out['effective_published'] = len(ans); res = BR.finish(out, t_start, queries_orig, ans_o, failed_o)
        res['K'] = K_orig
        gs = {r['guarantee'] for r in res.get('answers') or []}
        if gs and gs <= {'EXACT', 'DETERMINISTIC'}: res['guarantee'] = 'DETERMINISTIC' if 'DETERMINISTIC' in gs else 'EXACT'
        elif gs and 'NOT_PUBLISHED' not in gs: res['guarantee'] = 'PAC'
        return res
    def finish_expansion_(masses):
        """the ORIGINAL-bound signed plan's finalizer: the masses refer to the original model and original queries, so the closure decoder and scalar are NOT applied (a type boundary, not a label)"""
        rows = SE.dyadic_rows(masses, queries_orig, deadline=deadline)
        for j, r_ in rows.items():
            if (j & 255) == 0 and tnow() >= deadline: raise SE.DeadlineRefused('deadline while validating original answers (nothing published)')
            if not (valid_publication(r_['lo'], r_['hi'], eps) and r_['lo'] <= r_['point'] <= r_['hi']): raise AssertionError('evidence-expansion row %d fails the exact acceptance test' % j)
        out['Z'] = str(F(masses.Znum, masses.D)); out['outcome'] = 'COMPLETE'; out['positive_mass_witness'] = True; out['mechanism']['route'] = 'signed_evidence_expansion'
        res = BR.finish(out, t_start, queries_orig, rows, []); res['K'] = K_orig; res['guarantee'] = 'EXACT' if all(r_['guarantee'] == 'EXACT' for r_ in rows.values()) else 'DETERMINISTIC'
        if tnow() >= deadline: raise SE.DeadlineRefused('deadline after finalizing original answers (nothing published)')
        return res
    # ---- SIGNED EVIDENCE EXPANSION, step 2: execute the checked original-bound plan immediately after closure, under the remaining global deadline and the memory policy's headroom
    if se_plan is not None:
        t0 = tnow(); rss_now = SE.rss_bytes_now(); budget_ws = max(0, min(EVIDENCE_WORKSPACE_BUDGET, USABLE_BYTES - rss_now))          # joint headroom in BYTES on this platform (current RSS; ru_maxrss is KiB on Linux)
        try:
            masses = SE.execute(se_plan, deadline, budget_ws, n_queries=K_orig); ph['evidence_expansion'] = tnow() - t0
            se_rec.update(status='APPLIED', workspace_budget_bytes=budget_ws, rss_at_admission_bytes=rss_now, **masses.stats); t1 = tnow(); res = finish_expansion_(masses); ph['evidence_output'] = tnow() - t1; return res
        except SE.ZeroEvidence as e:
            ph['evidence_expansion'] = tnow() - t0; se_rec.update(status='ZERO_EVIDENCE: ' + str(e)); out['outcome'] = 'ZERO_EVIDENCE'; out['positive_mass_witness'] = False; out['mechanism']['route'] = 'signed_evidence_expansion'
            return BR.finish(out, t_start, queries_orig, {}, [])                                      # exact Znum = 0: no normalised publication, including fixed-state rows
        except (SE.ResourceRefused, SE.DeadlineRefused) as e:
            ph['evidence_expansion'] = tnow() - t0; se_rec.update(status=('RESOURCE_REFUSED: ' if isinstance(e, SE.ResourceRefused) else 'DEADLINE_REFUSED: ') + str(e)[:160], workspace_budget_bytes=budget_ws)   # typed; state released; the existing route continues with the remaining budget
            masses = None
            if tnow() >= deadline: out['deadline_phase'] = 'evidence_expansion'; out['positive_mass_witness'] = None; out['outcome'] = 'DEADLINE'; return BR.finish(out, t_start, queries_orig, {}, [])   # global budget exhausted: the established deadline outcome, no fallback work
        except SE.InvariantFailure as e:
            ph['evidence_expansion'] = tnow() - t0; se_rec.update(status='INVARIANT_FAILURE: ' + str(e)[:160]); out['error'] = 'evidence expansion invariant failure: ' + str(e); out['outcome'] = 'CERTIFICATE_DEFECT'; out['positive_mass_witness'] = None
            return BR.finish(out, t_start, queries_orig, {}, [])                                      # an implementation defect to investigate, never hidden behind the fallback
        se_plan = None
    # ---- CERTIFIED LAYERED CONTRACTION, step 2: execute the checked order on the ORIGINAL model through the existing certified executor, right after closure, under the remaining global deadline
    # and a forecast admitted against the memory policy's headroom; every row is the executor's enclosure, compacted outward on the 2^-52 grid; Z is an ENCLOSURE (never an exact point)
    if lc_plan is not None:
        t0 = tnow(); rss_now = SE.rss_bytes_now(); budget_b = max(0, min(LAYERED_BYTE_CAP, USABLE_BYTES - rss_now)); fc = LC.forecast(lc_plan, deadline - t0); lc_rec.update(forecast=fc, byte_budget=budget_b, rss_at_admission_bytes=rss_now)
        try:
            if fc['forecast_bytes'] > budget_b: raise LC.ResourceRefused('forecast live state %d B > budget %d B' % (fc['forecast_bytes'], budget_b))
            if fc['forecast_kernel_s'] > fc['remaining_s']: raise LC.ResourceRefused('forecast kernel time %.1f s > remaining %.1f s' % (fc['forecast_kernel_s'], fc['remaining_s']))
            R = LC.execute(lc_plan, model_orig, deadline, USABLE_BYTES, rss_now); ph['layered_execution'] = tnow() - t0; t1 = tnow()     # the plan is bound to the ORIGINAL model (the closure's reduced model is a different object)
            rows = {}; n_exact = 0; trivial = set(lc_plan.singletons) | set(lc_plan.factorless)
            for j, (x, v) in enumerate(queries_orig):
                if (j & 255) == 255 and tnow() >= deadline: raise LC.ExecutorRefused('DEADLINE', 'deadline while compacting the original rows (nothing published)')
                lo, hi = R.intervals[x][v]; pt = R.points[x][v]
                if x in trivial:                                                                       # one-state / factorless variables: EXACTLY 1 / uniform by definition; the executor's enclosure must agree
                    ex = F(1, cards_orig[x])
                    if not (lo <= ex <= hi): raise AssertionError('layered row %d: trivial exact value outside the executor enclosure' % j)
                    lo = hi = pt = ex
                if lo == hi: L, H = lo, hi; g = 'EXACT'
                else:
                    L, H = compact_outward(lo, hi); g = 'DETERMINISTIC'
                    if not (L <= lo and H >= hi): raise AssertionError('layered row %d: compaction does not enclose' % j)
                if not (valid_publication(L, H, eps) and L <= pt <= H): raise AssertionError('layered row %d fails the exact acceptance test' % j)
                rows[j] = dict(lo=L, hi=H, point=pt, guarantee=g); n_exact += g == 'EXACT'
            st = R.stats
            lc_rec.update(status='APPLIED', executor=dict(build_s=st.get('build_s'), lowering_s=st.get('lowering_s'), kernel_s=st.get('kernel_s'), enclosure_s=st.get('enclosure_s'), max_label_K=st.get('max_label_K'), Z_label=R.Z_label, max_width=st.get('max_width_float'), kernel_peak_logical_bytes=(st.get('counters') or {}).get('peak_logical_bytes'), forward_rows=(st.get('counters') or {}).get('forward_rows'), reverse_rows=(st.get('counters') or {}).get('reverse_rows'), max_live_message_entries=(st.get('counters') or {}).get('max_live_message_entries'), sources_dense=st.get('sources_dense'), sources_sparse=st.get('sources_sparse'), scalar_factors_cancelled=st.get('scalar_factors_cancelled'), host_budget_peak_bytes=st.get('host_budget_peak_bytes')), certificate=R.certificate, exact_rows=n_exact, deterministic_rows=len(rows) - n_exact)
            out['Z_enclosure'] = dict(lo=str(R.Z_lo), hi=str(R.Z_hi), point_binary64_derived=str(R.Z_point), label_K=R.Z_label, note='[Zhat (1 - K u), Zhat / (1 - K u)] from the kernel normalizer triple x the cancelled scalars; NOT an exact rational Z')
            out['Z_log2'] = lg(R.Z_point); out['outcome'] = 'COMPLETE'; out['positive_mass_witness'] = True; out['mechanism']['route'] = 'layered_contraction'
            res = BR.finish(out, t_start, queries_orig, rows, []); res['K'] = K_orig; res['guarantee'] = 'EXACT' if n_exact == len(rows) else 'DETERMINISTIC'; ph['layered_output'] = tnow() - t1
            if tnow() >= deadline: raise LC.ExecutorRefused('DEADLINE', 'deadline after finalizing the original rows (nothing published)')
            return res
        except LC.ZeroEvidence as e:
            ph['layered_execution'] = tnow() - t0; lc_rec.update(status='ZERO_EVIDENCE: ' + str(e)[:160]); out['outcome'] = 'ZERO_EVIDENCE'; out['positive_mass_witness'] = False; out['mechanism']['route'] = 'layered_contraction'
            return BR.finish(out, t_start, queries_orig, {}, [])
        except (LC.ResourceRefused, LC.ExecutorRefused) as e:
            ph['layered_execution'] = tnow() - t0; lc_rec.update(status=('RESOURCE_REFUSED: ' if isinstance(e, LC.ResourceRefused) else 'EXECUTOR_REFUSED ') + str(e)[:200]); R = None; rows = None   # typed; state released; the existing route continues
            if tnow() >= deadline: out['deadline_phase'] = 'layered_contraction'; out['positive_mass_witness'] = None; out['outcome'] = 'DEADLINE'; return BR.finish(out, t_start, queries_orig, {}, [])
        except AssertionError as e:
            ph['layered_execution'] = tnow() - t0; lc_rec.update(status='CERTIFICATE_DEFECT: ' + str(e)[:160]); out['error'] = 'layered contraction: ' + str(e); out['outcome'] = 'CERTIFICATE_DEFECT'; out['positive_mass_witness'] = None
            return BR.finish(out, t_start, queries_orig, {}, [])
        lc_plan = None
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
        if not live: out['Z'] = str(F(const * mult, scale)); return finish_('EXACT' if len(pending) == K else 'PARTIAL_EXACT', witness=True)     # fully contracted: Z = the product of the constant blocks x the factorless multiplicity / the integerization scale
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
        # ---- float representation of the blocks and the elimination trace (needed by both routes)
        t0 = tnow()
        try:
            cache = {}
            def conv(f):
                if id(f) not in cache: cache[id(f)] = ft_from_int(f, cards)
                return cache[id(f)]
            blocks = [conv(f) for f in live]; trace_var = {}; trace_ft = []
            for st, (v, snap) in enumerate(trace): trace_var[st] = v; trace_ft.append([conv(f) for f in snap])
        except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['float_convert'] = tnow() - t0; pos = {v: i for i, v in enumerate(S)}; sep_q = [(x, v) for (x, v) in queries if x in pos]
        base_bytes = sum(f.M.nbytes for f in cache.values()) + sum(f.arr.size * 48 for f in fns) + PROCESS_HEADROOM_BYTES          # live FTs + integer factors + process overhead / numpy headroom
        # ---- MEMORY POLICY (one process-wide plan before any large array): usable ceiling 2.5 GiB of the 3 GiB contract
        USABLE = USABLE_BYTES; cap_used, plan, tried = memory_plan([b.scope for b in blocks], cards, mb_cap, base_bytes)
        out['mechanism'].update(memory_policy=dict(usable_bytes=USABLE, base_bytes=base_bytes, cap_requested=mb_cap, cap_used=cap_used, ladder_tried=tried))
        if plan is None: out['refusal'] = 'no mini-bucket cap in the ladder fits the memory policy (tried %s)' % [t['cap'] for t in tried]; return finish_('MEMORY_POLICY_REFUSED')
        out['mechanism']['memory_policy'].update(planned_forward_bytes=plan['forward_bytes'], planned_log_bytes=plan['log_bytes'], planned_peak_step_bytes=plan['peak_step_bytes'], planned_splits=plan['splits'])
        # ---- mini-bucket construction (forward only; no sampler tables, no PAC query tables yet)
        t0 = tnow()
        try: mbp = MBFloat(blocks, cards, cap_used, deadline)
        except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
        ph['mb_construct'] = tnow() - t0
        out['mechanism'].update(mb_cap=cap_used, mb_logU=mbp.logU, mb_max_table=mbp.max_table, mb_max_range_sum_bits=mbp.max_range_sum, block_max_range_bits=max(b.R for b in blocks), sep_queries=len(sep_q),
                                mb_splits=mbp.splits, mb_split_steps=mbp.split_steps[:12], mb_unsplit=(mbp.splits == 0), mb_forward_bytes_actual=sum(R.M.nbytes for _, _, R in mbp.fwd))
        if mbp.logU == -inf: return finish_('ZERO_EVIDENCE')
        if construct_only: out['outcome'] = 'CONSTRUCT_ONLY'; return BR.finish(out, t_start, queries, {}, failed)
        blockfac = {i: [conv(f) for f in fns if f.facs <= live[i].facs] for i in range(len(blocks))}
        iorder = {i: [trace_var[st] for st in sorted(step_of[u] for u in live[i].interior)] for i in range(len(blocks))}
        fwd_actual = sum(R.M.nbytes for _, _, R in mbp.fwd if R.M is not None); exact_peak = base_bytes + plan['reverse_live_bytes'] + TILE_BUDGET + sum(b.M.nbytes for b in blocks) + (64 << 20)   # simulated reverse live payload (persistent + transient) + one tiled step's scratch + block derivatives + headroom
        out['mechanism']['memory_policy'].update(exact_route_peak_estimate=exact_peak, exact_route_fits=(exact_peak <= USABLE))
        # ---- EXACT ROUTE first (unsplit): needs the forward messages, not the sampler tables or PAC query tables; only when its estimated peak fits the policy
        if mbp.splits == 0 and route in ('auto', 'exact') and exact_peak > USABLE:
            out['mechanism']['exact_route'] = dict(status='MEMORY_POLICY_SKIPPED: estimated peak %d MiB > usable %d MiB' % (exact_peak >> 20, USABLE >> 20))
            if route == 'exact': return finish_('EXACT_ROUTE_MEMORY_POLICY_SKIPPED')
        if mbp.splits == 0 and route in ('auto', 'exact') and exact_peak <= USABLE:
            t0 = tnow(); exact_note = None
            try:
                Zft = ft_scalar_product(mbp.scalars); unresolved = 0
                if float(Zft.M) == 0.0: return finish_('ZERO_EVIDENCE')
                if Zft.rho >= 1: raise RangeRefused('normalizer enclosure reaches zero (rho_Z = %s): deterministic ratios unresolved' % float(Zft.rho))
                D = backward_derivatives(mbp, cards, deadline, release=True); Dblk = [D[id(fi)] for fi in mbp.inputs]; pub_exact = {}; ph['exact_backward'] = tnow() - t0
                for x in S:
                    if tnow() >= deadline: raise Deadline('exact_separator')
                    bi = min((i for i, b in enumerate(blocks) if x in b.scope), key=lambda i: blocks[i].M.size); b = blocks[bi]
                    union, P, e, rho = ft_product([b, Dblk[bi]], cards); axes = tuple(ai for ai, u in enumerate(union) if u != x); nsum = prod(cards[union[ai]] for ai in axes) if axes else 1
                    Nx = P.sum(axis=axes) if axes else P; rho = comb(rho, pow1pu(nsum - 1)); Nx, e = _rescale(np.asarray(Nx, dtype=float).reshape([cards[x]]), e); Nft = FT((x,), Nx, e, rho)
                    for v in range(cards[x]):
                        r_ = interval_ratio(Nft, v, Zft)
                        if r_ is not None and valid_publication(r_[0], r_[1], eps): pub_exact[qix[(x, v)]] = r_
                        else: unresolved += 1
                # interior variables: ONE shared forward / backward pass per block seeded by D_b (replaces the per-variable retained elimination)
                unrec = []
                for i, b in enumerate(blocks):
                    if not live[i].interior: continue
                    try: Ns = block_numerators_exact(blockfac[i], iorder[i], Dblk[i], cards, deadline)
                    except RangeRefused as e: unrec += list(live[i].interior); out['mechanism'].setdefault('exact_block_refusals', []).append(str(e)[:120]); continue
                    for x in live[i].interior:
                        Nft = Ns.get(x)
                        if Nft is None: unrec.append(x); continue
                        for v in range(cards[x]):
                            r_ = interval_ratio(Nft, v, Zft)
                            if r_ is not None and valid_publication(r_[0], r_[1], eps): pub_exact[qix[(x, v)]] = r_
                            else: unresolved += 1
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
                    if xc['status'] != 'CERTIFIED' or missing or cmp_ != need: exact_note = 'CROSSCHECK_FAILED'; out['mechanism']['exact_route'] = dict(status='CROSSCHECK_FAILED: %s (required %d, compared %d, missing %d)' % (xc['status'], need, cmp_, missing), crosscheck=xc)
                    elif dis: exact_note = 'INVESTIGATE'; out['mechanism']['exact_route'] = dict(status='INVESTIGATE: executor disagrees on %d separator coordinates' % dis, crosscheck=xc)
                if exact_note is None:
                    compact = {}; too_wide = 0
                    for j, (lo, hi) in pub_exact.items():
                        L, H = compact_outward(lo, hi)
                        if L <= lo and H >= hi and valid_publication(L, H, eps): compact[j] = (L, H)
                        else: too_wide += 1
                    out['mechanism'].update(route='exact', response_representation='shared_block_backward', exact_route=dict(status='OK', published=len(compact), too_wide_after_compaction=too_wide, unresolved_ratios=unresolved, unrecovered_interior=len(unrec), Z_log2=lg(F(float(Zft.M)) * F(2) ** Zft.e), rho_Z=fup(Zft.rho), crosscheck=xc, compaction='dyadic grid 2^-52, outward'))
                    ans.update(pending)
                    for j, (L, H) in compact.items(): publish(j, L, H, (L + H) / 2, 'DETERMINISTIC')
                    failed += unrec; out['positive_mass_witness'] = True
                    return finish_('COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL', witness=True)
            except RangeRefused as e: out['mechanism']['exact_route'] = dict(status='REFUSED: ' + str(e)); ph['exact_route'] = tnow() - t0
            if route == 'exact': return finish_('EXACT_ROUTE_UNAVAILABLE' if exact_note is None else 'EXACT_ROUTE_' + exact_note)
            out['mechanism']['exact_route_fallback'] = 'PAC route after the exact route did not publish (%s)' % (exact_note or 'refused')
            if any(R.M is None for _, _, R in mbp.fwd):                   # the exact route released the forward tables: rebuild the (deterministic) construction for the PAC route
                t0 = tnow()
                try: mbp = MBFloat(blocks, cards, cap_used, deadline)
                except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
                ph['mb_rebuild_for_pac'] = tnow() - t0; out['mechanism']['mb_rebuilt_for_pac'] = True
        out['mechanism']['route'] = 'pac'
        E_z = sum(b.e for b in blocks); E_tot = E_z - mbp.E_U
        if abs(E_tot) >= 1 << 50: out['refusal'] = 'exponent sum %d too large for an exact float' % E_tot; return finish_('NUMERIC_RANGE_REFUSED')
        # ---- PAC preparation (only now): recovery representation per block by the memory policy, then the sampler tables (forward messages released)
        t0 = tnow(); recovered = 0; skipped = []; bytes_used = 0; blockQ = []; qcols = []; qrhos = []; shared_blocks = 0; dense_blocks = 0; range_refused = []; window_to_shared = 0
        order_blocks = sorted(range(len(blocks)), key=lambda i: blocks[i].M.size * sum(cards[x] for x in live[i].interior))         # cheapest dense tables first
        for i in order_blocks:
            b = blocks[i]; interior = list(live[i].interior)
            if not interior: blockQ.append((i, None, [], None)); continue
            need = b.M.size * sum(cards[x] for x in interior) * 8
            if bytes_used + need <= RECOVERY_BYTE_BUDGET:                                      # DENSE precomputed responses (fast lookups) when they fit the budget
                Q = np.zeros((b.M.size, sum(cards[x] for x in interior)), dtype=float); cols = []; rhos = []; c0 = 0; okb = True
                for x in sorted(interior, key=lambda x: len([u for u in interior if step_of[u] > step_of[x]])):
                    if tnow() >= cdead: okb = False; break
                    try: r = recover_query_table_float(b, x, cards, trace_ft, trace_var, step_of, cdead, stats)
                    except Deadline: okb = False; break
                    except RangeRefused as e: out['refusal'] = str(e); return finish_('NUMERIC_RANGE_REFUSED')
                    if r is None: okb = False; break
                    scale_ = ldexp(1.0, r.e - b.e)
                    for v in range(cards[x]):
                        col = r.M[..., v].reshape(-1) * scale_; pos_ = col[col > 0]
                        if not np.all(np.isfinite(col)) or (pos_.size and float(pos_.min()) < ldexp(1.0, -1000)): out['refusal'] = 'query-table alignment leaves the normal range'; return finish_('NUMERIC_RANGE_REFUSED')
                        Q[:, c0] = col; cols.append((x, v)); rhos.append(r.rho); c0 += 1
                    del r; recovered += 1
                if okb: blockQ.append((i, Q, rhos, None)); qcols += cols; qrhos += rhos; bytes_used += need; dense_blocks += 1; continue
                del Q                                                                           # dense did not complete (deadline / range): fall back to the shared path for this block
            if tnow() >= cdead: window_to_shared += 1                                       # round 15: the optional dense precomputation has consumed its window; the block keeps ALL its queries through the shared representation (construction is a scopes-only simulation)
            try: sb = SharedBlock(live[i], blockfac[i], iorder[i], cards, pos)
            except RangeRefused as e: skipped += interior; range_refused.append('block %d: %s' % (i, str(e)[:160])); continue
            blockQ.append((i, None, [sb.rho_f] * len(sb.cols), sb)); qcols += sb.cols; qrhos += [sb.rho_f] * len(sb.cols); shared_blocks += 1; recovered += len(interior)
        failed += skipped; ph['query_tables'] = tnow() - t0
        if range_refused: out['mechanism']['shared_blocks_range_refused'] = range_refused; out['refusal'] = 'shared recovery refused %d block(s) by the range preflight: %s' % (len(range_refused), range_refused[0])
        out['mechanism'].update(interior_queries_recovered=recovered, interior_queries_failed=0, interior_queries_skipped_window=len(skipped), interior_queries_resource_skipped=0, blocks_window_to_shared=window_to_shared, recovery_bytes_retained=bytes_used, recovery_byte_budget=RECOVERY_BYTE_BUDGET, query_work=stats['query_work'],
                                response_representation=('dense' if shared_blocks == 0 else ('shared' if dense_blocks == 0 else 'mixed')), dense_blocks=dense_blocks, shared_blocks=shared_blocks)
        sq = sep_q + qcols; Kq = len(sq); qmap = {q: qix[q] for q in sq}
        out['mechanism'].update(Kq=Kq, interior_query_cols=len(qcols))
        # batch size under the memory policy: the shared path's per-batch workspace is B x largest union table; the certificate batch is B x Kq
        max_union = max([sb.max_union for _, _, _, sb in blockQ if sb is not None] + [1]); max_bps = max([sb.bytes_per_sample for _, _, _, sb in blockQ if sb is not None] + [0]); fixed_ws = max([sb.fixed_workspace_bytes for _, _, _, sb in blockQ if sb is not None] + [0])
        cert_per_draw = Kq * 8 * 7                                                                  # the response row + the certificate's per-batch temporaries (Xf, a, b, a*a, ab, |ab|)
        batch_used = batch
        while batch_used > 1 and batch_used * cert_per_draw + fixed_ws + min(batch_used, 1) * max_bps > BATCH_BUDGET: batch_used //= 2
        if batch_used * cert_per_draw + fixed_ws + max_bps > BATCH_BUDGET: out['refusal'] = 'even one draw per batch exceeds the batch budget (certificate %d B + shared workspace %d + %d B per draw > %d B)' % (cert_per_draw, fixed_ws, max_bps, BATCH_BUDGET); return finish_('MEMORY_POLICY_REFUSED')
        chunk = max(1, min(batch_used, (BATCH_BUDGET - batch_used * cert_per_draw - fixed_ws) // max(1, max_bps)))   # shared blocks are evaluated in microbatches of `chunk` distinct active boundary rows
        out['mechanism'].update(batch_requested=batch, batch_used=batch_used, shared_max_union=max_union, shared_bytes_per_sample_max=max_bps, shared_fixed_workspace_bytes=fixed_ws, shared_chunk=chunk, batch_budget_bytes=BATCH_BUDGET)
        t0 = tnow(); mbp.prepare_sampler(release_forward=True); ph['sampler_prep'] = tnow() - t0
        if proposal == 'wmb':                                             # QUARANTINED candidate (controls only; the frozen panel runs proposal=mb): weighted mini-buckets on the SAME partition and order, selection by CERTIFIED caps
            t0 = tnow(); wrec = dict(requested='wmb')
            try:
                wmbp = WMBFloat(mbp, blocks, cards, deadline, opt_s=opt_s); wrec.update(construct_s=tnow() - t0, opt_s=wmbp.opt_s, weights=[[str(x) for x in w] for w in wmbp.weights if len(w) > 1][:12], splits=wmbp.splits)
                if wmbp.logU == -inf: return finish_('ZERO_EVIDENCE')
                E_w = sum(b.e for b in blocks) - wmbp.E_U
                wid_m = numerical_widening(blocks, mbp, qrhos, len(S), max(cards), E_tot); wid_w = numerical_widening(blocks, wmbp, qrhos, len(S), max(cards), E_w)
                if wid_w['delta_log_total'] > F(1, 4): raise RangeRefused('wmb: log-domain error budget %s too large' % float(wid_w['delta_log_total']))
                cap_m = mbp.logU_f + math.log2(1.0 + fup(wid_m['rho_cap'])); cap_w = wmbp.logU_f + math.log2(1.0 + fup(wid_w['rho_cap'])); dE = wmbp.E_U - mbp.E_U
                if abs(dE) >= 1 << 50: raise RangeRefused('wmb: exponent difference too large to compare')
                diff = (cap_w - cap_m) + float(dE)
                wrec.update(raw_logU_mb=mbp.logU, raw_logU_wmb=wmbp.logU, raw_diff_log2=(wmbp.logU - mbp.logU), rho_cap_mb=fup(wid_m['rho_cap']), rho_cap_wmb=fup(wid_w['rho_cap']), certified_diff_log2=diff, rho_msgs_wmb=fup(wid_w['rho_msgs']))
                use_wmb = diff < 0; wrec.update(selected=('wmb' if use_wmb else 'mb'), reason=('certified weighted cap smaller' if use_wmb else 'certified weighted cap not smaller'))
                if use_wmb: mbp = wmbp; E_tot = E_z - mbp.E_U
            except RangeRefused as e: wrec.update(selected='mb', status='WMB INELIGIBLE: ' + str(e))
            out['mechanism']['wmb'] = wrec; ph['wmb_construct'] = tnow() - t0
        wid = numerical_widening(blocks, mbp, qrhos, len(S), max(cards), E_tot); eps_num = fup(wid['eps_num']); rho_X = fup(wid['rho_X']); rho_cap = fup(wid['rho_cap'])
        if wid['delta_log_total'] > F(1, 4): out['refusal'] = 'log-domain error budget %s too large' % float(wid['delta_log_total']); return finish_('NUMERIC_RANGE_REFUSED')
        out['mechanism'].update(eps_num=eps_num, eps_num_log2=log2(eps_num), rho_X=rho_X, rho_cap=rho_cap, rho_f=fup(wid['rho_f']), mb_rhoU=fup(mbp.rhoU), E_tot=E_tot, delta_log_total=float(wid['delta_log_total']), max_log_magnitude=float(wid['max_log_mag']))
        logU_capf = up(mbp.logU_f + up(log2(1.0 + rho_cap)) + 2 ** -40); cap_tol = up(log2(1.0 + 2 * rho_X)) + 2 ** -40
        alpha = float(delta) / Kq; cert = Certificate(Kq, alpha, eps_num, float(eps), schedule); zcert = ZCertificate(float(delta))
        bLM = []; bstr = []; bscope = []; bMflat = []
        for b in blocks:
            with np.errstate(divide='ignore'): bLM.append(np.where(b.M > 0, np.log2(np.maximum(b.M, 1e-300)), -inf).reshape(-1))
            strides = {}; s_ = 1
            for u in reversed(b.scope): strides[u] = s_; s_ *= cards[u]
            bstr.append(strides); bscope.append(b.scope); bMflat.append(b.M.reshape(-1))
        sep_pos = np.array([pos[x] for (x, v) in sep_q], dtype=np.int64); sep_val = np.array([v for (x, v) in sep_q], dtype=np.int64)
        witness = False; draws = 0; zero_draws = 0; pub = {}; trace_rows = []; t_loop = 0.0; t_cert = 0.0; next_chk = tnow() + check_s; sumX = 0.0; maxlogX = -inf; sumX2 = 0.0; maxX = 0.0
        last_width = np.full(Kq, inf); abandoned = 0; shared_rows = dict(draws=0, active=0, unique=0, chunks=0, cache_hits=0, cache_misses=0); t_shared = 0.0; stream_refusal = None
        pac_peak_planned = base_bytes + plan['log_bytes'] + min(RECOVERY_BYTE_BUDGET, 1 << 62) + BATCH_BUDGET; cache_allow = (max(0, min(RESPONSE_CACHE_BUDGET, USABLE - pac_peak_planned)) if shared_blocks else 0)   # optional: from the capacity the mandatory plan leaves
        rcache = dict(entries={}, bytes=0, budget=cache_allow); out['mechanism']['response_cache_budget_bytes'] = cache_allow
        class BatchCut(Exception): pass
        def flat_index(Sb, i):
            idx = np.zeros(Sb.shape[0], dtype=np.int64)
            for u in bscope[i]: idx += Sb[:, pos[u]] * bstr[i][u]
            return idx
        def check_publish():
            nonlocal t_cert
            t0 = tnow(); lo, hi = cert.sets(); width = hi - lo
            for j in range(Kq):
                if j in pub or not np.isfinite(width[j]): continue
                L_, H_ = F(float(lo[j])), F(float(hi[j]))
                if valid_publication(L_, H_, eps): pub[j] = (L_, H_, 'PAC_EB')
            unpub = np.array([j for j in range(Kq) if j not in pub], dtype=int); w = width[unpub] if unpub.size else np.zeros(0); wf = w[np.isfinite(w)]
            trace_rows.append(dict(t=round(tnow() - t_start, 2), draws=draws, zero_draws=zero_draws, X_mean=(sumX / max(1, draws)), published=len(pub), remaining=int(unpub.size), max_remaining_width=(float(wf.max()) if wf.size else 0.0), median_remaining_width=(float(np.median(wf)) if wf.size else 0.0), empty_sets=int((~np.isfinite(w)).sum())))
            t_cert += tnow() - t0; return width
        while tnow() < deadline and len(pub) < Kq:
          try:
            t0 = tnow(); Sb, logq, zero_row = mbp.sample_batch(rng, batch_used, pos); B = Sb.shape[0]
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
            for i, Q, rhos, sb in blockQ:
                if Q is None and sb is None: continue
                if Q is not None:
                    idx = flat_index(Sb, i); g = gv[i]; Kb = Q.shape[1]
                    with np.errstate(divide='ignore', invalid='ignore'): ratio = np.where(g[:, None] > 0, Q[idx] / np.where(g > 0, g, 1.0)[:, None], 0.0)
                    f[:, col:col + Kb] = np.clip(ratio, 0.0, 1.0); col += Kb
                else:
                    # shared path: responses only for ACTIVE rows (X > 0): every certificate term involving the response carries X f or X^2 f, so any bounded response (0 here) stands on
                    # zero-weight rows; among the active rows each DISTINCT boundary assignment is evaluated once and scattered back (the Rao-Blackwellized response is unchanged);
                    # every original draw, including the zero-weight ones, still enters the certificate with the batch's predictable parameters
                    if tnow() >= deadline: raise BatchCut()
                    Kb = len(sb.cols); act = np.nonzero(X > 0)[0]; ts = tnow()
                    fb, stt = evaluate_shared(sb, Sb, act, chunk, deadline, rcache); f[act, col:col + Kb] = fb[act]
                    shared_rows['unique'] += stt['unique']; shared_rows['chunks'] += stt['chunks']; shared_rows['cache_hits'] += stt['hits']; shared_rows['cache_misses'] += stt['misses']
                    shared_rows['draws'] += B; shared_rows['active'] += int(act.size); t_shared += tnow() - ts; col += Kb
            cert.update_batch(X, f); zcert.update_batch(X); draws += B; zero_draws += int(zero.sum()); sumX += float(X.sum()); sumX2 += float((X * X).sum()); maxX = max(maxX, float(X.max())); t_loop += tnow() - t0
            if tnow() >= next_chk: last_width = check_publish(); next_chk = tnow() + check_s
          except (BatchCut, Deadline) as e: abandoned += 1; out['deadline_phase'] = 'shared_responses (%s): the batch in flight at the deadline was abandoned; %d completed batches retained' % (str(e) or 'between blocks', draws // max(1, batch_used)); break
          except RangeRefused as e: abandoned += 1; stream_refusal = str(e); break                   # typed numerical refusal of THIS batch; the certificate holds only completed batches, whose publications stand
        width = check_publish() if not abandoned else last_width; unpub = [j for j in range(Kq) if j not in pub]
        assert all(valid_publication(l_, h_, eps) for l_, h_, _ in pub.values()), 'a PAC publication failed the exact acceptance test (certificate defect)'; wf = width[unpub]; wf = wf[np.isfinite(wf)]
        zi = zcert.interval(); per_draw = t_loop / max(1, draws); total = t_loop + t_cert
        ess = (sumX * sumX / sumX2) if sumX2 > 0 else 0.0
        var_resid, _ = cert.variance()
        out['mechanism'].update(sum_X=sumX, sum_X2=sumX2, max_X=maxX, zero_weight_fraction=zero_draws / max(1, draws), ESS=ess, ESS_per_s=ess / max(1e-9, t_loop), largest_share=(maxX / sumX if sumX > 0 else None), draws_per_s=draws / max(1e-9, t_loop),
                                response_residual_variance_median=float(np.median(var_resid)), response_residual_variance_p90=float(np.percentile(var_resid, 90)), proposal_used=proposal)
        shared_rows['cache_entries'] = sum(len(e) for e in rcache['entries'].values()); shared_rows['cache_bytes'] = rcache['bytes']
        out['mechanism'].update(abandoned_batches=abandoned, shared_rows=shared_rows, shared_active_fraction=(shared_rows['active'] / shared_rows['draws'] if shared_rows['draws'] else None), shared_unique_per_active=(shared_rows['unique'] / shared_rows['active'] if shared_rows['active'] else None), shared_responses_s=t_shared, draws=draws, zero_draws=zero_draws, X_mean=sumX / max(1, draws), log2_Zhat_over_Ucap_DIAGNOSTIC=(log2(sumX / draws) if sumX > 0 else None), max_log2_X_observed=maxlogX, ms_per_draw=1000 * per_draw, cert_evals=len(trace_rows), cert_s=t_cert,
                                published=len(pub), remaining=len(unpub), max_remaining_width=(float(wf.max()) if wf.size else (None if unpub else 0.0)), median_remaining_width=(float(np.median(wf)) if wf.size else (None if unpub else 0.0)),
                                Z_over_Ucap_EB_interval=zi, Z_EB_relative_width=((zi[1] - zi[0]) / zi[0] if zi[0] > 0 else None), lam_last_median=float(np.median(cert.lam())), schedule=schedule,
                                extrapolated_s_max_width=((total * (float(wf.max()) / (2 * float(eps))) ** 2) if wf.size else 0.0), extrapolated_s_median_width=((total * (float(np.median(wf)) / (2 * float(eps))) ** 2) if wf.size else 0.0))
        ph.update(stream=t_loop, certificate=t_cert); out['trace'] = trace_rows
        if witness:
            ans.update(pending)
            for j, q in enumerate(sq):
                if j in pub: lo_, hi_, g = pub[j]; publish(qmap[q], lo_, hi_, (lo_ + hi_) / 2, g)
        else: out['withheld_without_witness'] = len(pub) + len(pending)
        if stream_refusal: out['refusal'] = 'shared recovery refused a batch: ' + stream_refusal; return finish_('NUMERIC_RANGE_REFUSED', witness=witness)
        if range_refused: return finish_('NUMERIC_RANGE_REFUSED', witness=witness)
        return finish_('COMPLETE' if len(ans) == K else 'DEADLINE_PARTIAL', witness=witness)
    except Deadline as e:
        out['deadline_phase'] = str(e); return finish_('DEADLINE')
    except AssertionError as e:
        out['error'] = str(e); return finish_('CERTIFICATE_DEFECT')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--input', required=True); ap.add_argument('--output', required=True); ap.add_argument('--budget', type=float, default=20.0); ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--table-cap', type=int, default=1 << 18); ap.add_argument('--enum-cap', type=int, default=1 << 16); ap.add_argument('--mb-cap', type=int, default=1 << 24); ap.add_argument('--epsilon', default='1/200'); ap.add_argument('--delta', default='1/1000000')
    ap.add_argument('--force-approx', action='store_true'); ap.add_argument('--no-support-closure', action='store_true', help='disable the exact support closure (with --no-evidence-expansion this is the v2.9.4 path)'); ap.add_argument('--no-evidence-expansion', action='store_true', help='disable the signed evidence-expansion operator only (= the accepted R18 comparator path when the closure stays enabled)'); ap.add_argument('--no-layered-contraction', action='store_true', help='disable the certified layered-contraction constructor only (= the accepted v2.11.2 comparator path)'); ap.add_argument('--batch', type=int, default=1024); ap.add_argument('--schedule', default='baseline', choices=['baseline', 'targeted']); ap.add_argument('--route', default='auto', choices=['auto', 'pac', 'exact']); ap.add_argument('--construct-only', action='store_true'); ap.add_argument('--no-crosscheck', action='store_true'); ap.add_argument('--proposal', default='mb', choices=['mb', 'wmb']); ap.add_argument('--opt-s', type=float, default=3.0)
    a = ap.parse_args()
    out = solve(a.input, a.budget, seed=a.seed, table_cap=a.table_cap, enum_cap=a.enum_cap, eps=F(a.epsilon), delta=F(a.delta), mb_cap=a.mb_cap, force_approx=a.force_approx, batch=a.batch, schedule=a.schedule, route=a.route, construct_only=a.construct_only, crosscheck=not a.no_crosscheck, proposal=a.proposal, opt_s=a.opt_s, support_closure=not a.no_support_closure, evidence_expansion=not a.no_evidence_expansion, layered_contraction=not a.no_layered_contraction)
    out['input'] = os.path.abspath(a.input); out['argv'] = sys.argv[1:]
    t_ser = time.monotonic(); os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True); json.dump(out, open(a.output, 'w'), indent=1, default=str)
    json.dump(dict(solver_wall_s=out['wall_s'], serialize_s=time.monotonic() - t_ser, in_process_total_s=time.monotonic() - T_PROCESS_START, result_bytes=os.path.getsize(a.output), note='the SUPERVISOR receipt is the scored end-to-end measurement'), open(a.output + '.timing.json', 'w'), indent=1)
    m = out['mechanism']; print(json.dumps(dict(outcome=out['outcome'], guarantee=out.get('guarantee'), published=out.get('published'), K=out.get('K'), wall_s=round(out['wall_s'], 3), phases={k: round(v, 3) for k, v in out['phases_s'].items()},
                                   mech={k: (round(m[k], 4) if isinstance(m.get(k), float) else m.get(k)) for k in ('blocks', 'separator_vars', 'mb_cap', 'mb_logU', 'mb_splits', 'mb_unsplit', 'route', 'exact_route', 'wmb', 'ESS', 'largest_share', 'zero_weight_fraction', 'max_X', 'draws_per_s', 'mb_max_range_sum_bits', 'eps_num_log2', 'rho_X', 'E_tot', 'delta_log_total', 'draws', 'ms_per_draw', 'X_mean', 'log2_Zhat_over_Ucap_DIAGNOSTIC', 'max_log2_X_observed', 'published', 'remaining', 'max_remaining_width', 'median_remaining_width', 'lam_last_median', 'schedule', 'extrapolated_s_max_width', 'extrapolated_s_median_width', 'Z_EB_relative_width', 'interior_queries_recovered', 'interior_queries_failed')}), default=str))


if __name__ == '__main__': main()
