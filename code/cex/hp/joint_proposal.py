"""DGP5 joint conditional construction, part 1: the direct fine-variable proposal (theory note DGP5_JOINT_CONSTRUCTION_THEORY.md sections 3, 13; brief CLAUDE_DGP5_JOINT_CONSTRUCTION_SPEC.md sections 3-5).
A proposal is an acyclic product of EXPLICIT conditionals q(x) = prod_i theta_i(x_i | u_i): each conditional stores its variable z, its ordered parents u (all sampled before z), POSITIVE integer counts summing to
D = 2^40 per parent row and the integer cumulative counts; sampling draws ONE uniform integer in [0, D) per variable and looks the state up in the integer CDF; the analyzed density is EXACTLY the product of the
selected count / D terms read from the SAME immutable counts (no floating CDF, no nearby guide).
Seed (brief section 5, lemma L5): bounded SUM / MAX mini-bucket elimination of the exact nonnegative fine target W_0 (unaries + factors of the parent canonical model, WITHOUT its scalar) in the admitted guarded
elimination order; at each eliminated z the bucket is grouped (decreasing physical volume, stable id; greedy smallest admissible union; BOTH the volume cap V_seed = 1,024 and the fan-in 16; group 0 = the first
created); group 0 keeps its joint upward product P(z, u) and forms the upward SUM message M(u) >= sum_z P; every other group forms an upward MAX message; group 0 is normalized into the actual conditional by the
EXACT-FLOOR count rule c_z = 1 + floor((D - k) P_z / M) (bit-length comparison first; a ratio below one has floor zero; the remaining shift is bounded by the count grid and the significand widths), the leftover
D - sum c distributed by full cycles over the state id plus the final prefix; M = 0 -> positive near-uniform counts; k >= D refused. Row inequality P_z <= M theta_z D / (D - k); telescoping over the elimination
gives W_0(x) <= U prod_z D / (D - k_z) q_seed(x) with U = the product of every final scalar message (a checked zero U is the zero-target terminal). Arithmetic = the DGP4 compact upward dyadics (residual_max_envelope:
128-bit normalized mantissas, exact group products <= 2,048 bits, ONE upward rounding per output entry, guarded comparisons, bounded sums). Memory: every table / count array is charged to the constructor account
BEFORE allocation and owned by the compile object until released (refusal) or transferred (commit); scans poll at entry, exit and every 256 entries."""
import math, itertools, hashlib, time
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import residual_max_envelope as RM
from residual_max_envelope import MBITS, ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, lead, log2_up

D_BITS = 40; D = 1 << D_BITS
PROFILE_PRODUCTION = dict(V_seed=1024, V_coef=4096, V_family=4096, fanin=16, mantissa_bits=128, D_bits=40, pilot_draws=1024, pilot_batch=256, max_attempts=2, frontier_points=17, bisections=64, promotion_margin=0.01,
                          offer_min_work_s=8.0, allowance_frac=0.20, allowance_max_s=4.0, reserve_frac=0.10, seed_frac=0.50, pilot_frac=0.65, owned_cap_bytes=64 << 20)
ENTRY_BYTES = RM.ENTRY_BYTES; COUNT_BYTES = 16                                     # counts + cumulative counts (int64 each) per family entry


class RefusedJoint(Exception):
    def __init__(self, kind, reason): super().__init__(kind, reason); self.kind = kind; self.reason = reason


# ---------------------------------------------------------------- tables over FINE variables (axes = sorted variable ids); entries = compact (e, m)
class JTable:
    __slots__ = ('axes', 'arr', 'tid', 'origin', 'bytes')
    def __init__(self, axes, arr, tid, origin):
        self.axes = tuple(axes); self.arr = arr; self.tid = tid; self.origin = origin; self.bytes = ENTRY_BYTES * int(arr.size) + 128
        assert tuple(sorted(self.axes)) == self.axes and len(set(self.axes)) == len(self.axes) and arr.ndim == len(self.axes), (self.axes, arr.shape)
    def volume(self): return int(self.arr.size)


def vol_of(axes, cards): return math.prod(cards[v] for v in axes) if axes else 1
def broadcast(T, axes, cards): return T.arr.reshape([cards[v] if v in T.axes else 1 for v in axes])
_mul = RM._mul; _norm = RM._norm


def product_exact(tables, axes, cards):
    """exact (unnormalized) product of the tables over the union axes (object array of (e, m) with mantissas <= fan-in x 128 bits)"""
    acc = None
    for T in tables:
        v = broadcast(T, axes, cards); acc = v if acc is None else _mul(acc, v)
    shape = [cards[v] for v in axes]
    if acc is None: out = np.empty(shape, dtype=object); out.fill((0, 1)); return out
    return np.broadcast_to(acc, shape).copy() if acc.shape != tuple(shape) else acc


def max_over(arr, axes, drop):
    """MAX of upward-normalized entries over the axis ids in `drop` (lexicographic (e, m) order == numeric order on normalized entries). ALWAYS returns an object ndarray (0-d when every axis is dropped: numpy's reduce of a
    1-d object array yields a bare Python tuple, which the DGP5 validity amendment 1 wraps back into a 0-d array -- a scalar MAX message of a saturated bucket crashed the n64 clique / CSP_11 SEED and JOINT cells)"""
    out = arr; cur = list(axes)
    for a in sorted(drop, reverse=True):
        k = cur.index(a); out = np.maximum.reduce(out, axis=k) if out.shape[k] > 1 else out.reshape([s for i, s in enumerate(out.shape) if i != k]); cur.pop(k)
        if not isinstance(out, np.ndarray): sc = np.empty((), dtype=object); sc[()] = out; out = sc
    return out, tuple(cur)


def sum_over_up(arr, axes, drop):
    """UPWARD sum (bounded-shift compact sum) of normalized entries over the axis ids in `drop`"""
    out = arr; cur = list(axes)
    for a in sorted(drop, reverse=True):
        k = cur.index(a); mv = np.moveaxis(out, k, -1); flat = mv.reshape(-1, mv.shape[-1]); res = np.empty(flat.shape[0], dtype=object)
        for i in range(flat.shape[0]): res[i] = sum_up(list(flat[i]))
        out = res.reshape(mv.shape[:-1]); cur.pop(k)
    return out, tuple(cur)


def convert_up(vals, power=1):
    """upward compact entries of exact nonnegative rationals (power 2 = the squared target factors of the a-pass)"""
    out = np.empty(len(vals), dtype=object)
    for i, x in enumerate(vals): out[i] = from_fraction_up(F(x) ** power if power != 1 else F(x))
    return out


def source_tables(M_par, budget, clock, owned, V=None, power=1):
    """compact upward tables of every target factor of the parent canonical model (unaries psi_v + factors; the scalar is OWNED SEPARATELY and never enters W_0); physical volume checked BEFORE allocation; charged"""
    cards = list(M_par.cards); tabs = []; tid = 0
    for v in range(len(cards)):
        if V is not None and cards[v] > V: raise RefusedJoint('VOLUME', 'unary of variable %d (%d entries) exceeds the volume cap %d' % (v, cards[v], V))
        owned[0] += budget.charge(ENTRY_BYTES * cards[v] + 128, 'joint source unary %d' % v); clock.poll('before joint source unary %d' % v)
        arr = convert_up(M_par.psi[v], power).reshape([cards[v]]); tabs.append(JTable((v,), arr, tid, ('unary', v))); tid += 1
    for fi, (sc, vals) in enumerate(M_par.factors):
        sc = tuple(sc); axes = tuple(sorted(sc)); vol = vol_of(axes, cards)
        if V is not None and vol > V: raise RefusedJoint('VOLUME', 'factor %d (%d entries) exceeds the volume cap %d (refused before allocation)' % (fi, vol, V))
        owned[0] += budget.charge(ENTRY_BYTES * vol + 128, 'joint source factor %d (%d entries)' % (fi, vol)); clock.poll('before joint source factor %d' % fi)
        arr = convert_up(vals, power).reshape([cards[v] for v in sc])
        if axes != sc: arr = np.transpose(arr, [sc.index(v) for v in axes])                       # row-major over the factor's own scope order -> sorted axes (R1 semantics)
        tabs.append(JTable(axes, arr, tid, ('factor', fi))); tid += 1
    return tabs


# ---------------------------------------------------------------- explicit conditionals (positive integer counts summing to D) and proposals
class Conditional:
    """theta(z | u): parents in SAMPLING order (every parent is sampled before z); counts shape (prod cards[parents], card z) row-major over the parents in that order; cum = cumulative counts; immutable once committed"""
    __slots__ = ('z', 'parents', 'counts', 'cum', 'pstrides', 'bytes', 'sha256')
    def __init__(self, z, parents, counts, cards):
        self.z = int(z); self.parents = tuple(int(p) for p in parents); self.counts = np.ascontiguousarray(counts, dtype=np.int64); k = cards[self.z]
        assert self.counts.shape == (vol_of(self.parents, cards), k), (self.counts.shape, self.parents, k)
        assert (self.counts >= 1).all() and (self.counts.sum(axis=1) == D).all(), 'a conditional row is not a positive integer law summing to D'
        self.cum = np.cumsum(self.counts, axis=1); self.counts.setflags(write=False); self.cum.setflags(write=False); self.bytes = COUNT_BYTES * int(self.counts.size) + 256
        st = {}; s_ = 1
        for p in reversed(self.parents): st[p] = s_; s_ *= cards[p]
        self.pstrides = st; self.sha256 = hashlib.sha256(repr((self.z, self.parents, self.counts.shape)).encode() + self.counts.tobytes()).hexdigest()
    def row_index(self, X):
        """row of the parent assignment for draws X (B, n) -> (B,)"""
        idx = np.zeros(X.shape[0], dtype=np.int64)
        for p in self.parents: idx += X[:, p] * self.pstrides[p]
        return idx
    def family_volume(self): return int(self.counts.size)
    def theta_exact(self, row, a): return F(int(self.counts[row, a]), D)
    def replicate(self, new_parents, cards, budget=None):
        """row replication across added parents (lemma L4): the SAME law on the larger context; new_parents must contain the old parents. DGP6 repair (finding 3): with `budget` the counts + cumulative arrays are
        CHARGED before allocation (a zero-headroom expansion refuses MEMORY before any array exists); the charge is owned by the returned Conditional's `bytes` (the caller releases it with the table)"""
        assert set(self.parents) <= set(new_parents)
        n_new = vol_of(new_parents, cards) * cards[self.z]
        if budget is not None: budget.charge(COUNT_BYTES * n_new + 256, 'replicated conditional of %d (%d entries)' % (self.z, n_new))
        new = np.empty((vol_of(new_parents, cards), cards[self.z]), dtype=np.int64); st = {}; s_ = 1
        for p in reversed(new_parents): st[p] = s_; s_ *= cards[p]
        for idx, asg in enumerate(itertools.product(*[range(cards[p]) for p in new_parents])):
            old = sum(self.pstrides[p] * asg[i] for i, p in enumerate(new_parents) if p in self.pstrides); new[idx] = self.counts[old]
        return Conditional(self.z, new_parents, new, cards)


def quantize_row(weights, k):
    """nonnegative finite weights -> positive integer counts summing to D (the single-row form of joint_optimize.quantize_rows; malformed rows rejected)"""
    import joint_optimize as JO
    if k >= D: raise RefusedJoint('RANGE', 'cardinality %d >= D' % k)
    w = np.asarray([float(x) for x in weights], dtype=float)
    if (not np.isfinite(w).all()) or (w < 0).any(): raise RefusedJoint('MALFORMED', 'a proposed row carries a negative or non-finite weight')
    cnt, ok = JO.quantize_rows(w[None, :], k)
    if not ok[0]: raise RefusedJoint('MALFORMED', 'quantization failed to produce a positive law summing to D')
    return [int(x) for x in cnt[0]]


def floor_ratio_counts(P_row, M, k):
    """the seed count rule with the EXACT floor of the compact ratio: c_z = 1 + floor((D - k) P_z / M) for M > 0 (P_z <= M); leftovers by full cycles over the state id then the final prefix"""
    if k >= D: raise RefusedJoint('RANGE', 'cardinality %d >= D' % k)
    if M[1] == 0:                                                                                  # a zero row: every P_z is zero (M is an upward sum): a positive near-uniform law
        base = D // k; rem = D - base * k; return [base + (1 if i < rem else 0) for i in range(k)], True
    eM, mM = M; counts = []
    for P in P_row:
        if P[1] == 0: counts.append(1); continue
        eP, mP = P; num = (eP, mP * (D - k))                                                      # (D - k) P_z as an exact pair (mantissa <= 168 bits)
        if not ge_exact(num, M): counts.append(1); continue                                      # ratio < 1 -> floor 0 (bit-length comparison; no huge shift)
        sh = eP - eM                                                                               # (D - k) m_P 2^sh / m_M with the shift BOUNDED: ratio in [1, D) -> -sh <= 168 (bits of the numerator mantissa)
        if sh >= 0: q = (mP * (D - k) << sh) // mM
        else: q = (mP * (D - k)) // (mM << (-sh))
        if q > D - k: raise CE.Defect('seed count rule: floor exceeds D - k (P_z > M?)')
        counts.append(1 + int(q))
    s = sum(counts)
    if s > D: raise CE.Defect('seed count rule: initial counts exceed D')
    rem = D - s; full, pre = divmod(rem, k)
    for i in range(k): counts[i] += full + (1 if i < pre else 0)
    assert sum(counts) == D and all(c >= 1 for c in counts); return counts, False


# ---------------------------------------------------------------- the bounded SUM / MAX elimination engine (seed and witness passes share it)
class JointCompile:
    """mode 'seed': group 0 -> family table + SUM message + conditional; others MAX. mode 'max': every group MAX (the b-pass). mode 'sum': group 0 SUM, others MAX (the a-pass). `retain` = variables never eliminated
    (the family F of a witness pass). Every output is admitted before allocation; every stage is checked independently (check_joint.check_stage) before commit; consumed inputs are released at commit; refusal /
    interruption releases everything owned."""
    def __init__(self, cards, sources, order, V, fanin, budget, clock, mode, retain=(), owned=None, trace=None):
        self.cards = list(cards); self.active = list(sources); self.order = [v for v in order if v not in set(retain)]; self.V = int(V); self.fanin = int(fanin); self.budget = budget; self.clock = clock; self.mode = mode; self.retain = tuple(retain)
        self.owned = owned if owned is not None else [0]; self.next_tid = (max(T.tid for T in sources) + 1) if sources else 0; self.plan = []; self.stages_done = 0; self.max_splits = 0; self.work_cells = 0; self.peak_owned = 0; self.checker_receipts = []
        self.conditionals = {}; self.scalars = []; self.trace = trace if trace is not None else []; self.zero_rows = 0; self.k_values = []; self.consumed_messages = 0; self.absent_sum_scalars = []
    def _bump(self): self.peak_owned = max(self.peak_owned, self.owned[0])
    def release_all(self):
        if self.owned[0]: self.budget.release(self.owned[0]); self.owned[0] = 0
    def transfer(self):
        n = self.owned[0]; self.owned[0] = 0; return n
    def _release_table(self, T): self.budget.release(T.bytes); self.owned[0] -= T.bytes
    def _groups(self, bucket):
        bucket = sorted(bucket, key=lambda T: (-T.volume(), T.tid)); groups = []
        for T in bucket:
            best = None
            for gi, (axes, mem) in enumerate(groups):
                u = tuple(sorted(set(axes) | set(T.axes))); vol = vol_of(u, self.cards)
                if vol <= self.V and len(mem) < self.fanin and (best is None or vol < best[0]): best = (vol, gi, u)
            if best is None:
                if T.volume() > self.V: raise RefusedJoint('VOLUME', 'an individual table (%s, %d entries) exceeds the volume cap %d' % (T.origin, T.volume(), self.V))
                groups.append((T.axes, [T]))
            else: groups[best[1]] = (best[2], groups[best[1]][1] + [T])
        return bucket, groups
    def stage(self, v):
        import check_joint as CJ
        bucket = [T for T in self.active if v in T.axes]
        if not bucket:
            if self.mode == 'sum': k = from_fraction_up(F(self.cards[v])); self.scalars.append(k); self.absent_sum_scalars.append(v)      # a variable absent from every live factor: SUM contracts to its cardinality
            if self.mode == 'seed': raise CE.Defect('seed: variable %d has no active table (every variable carries its unary)' % v)
            self.plan.append(dict(v=v, groups=[], note='no active table carries the variable')); self.stages_done += 1; return
        bucket, groups = self._groups(bucket)
        part = RM.check_partition([T.tid for T in bucket], [[T.tid for T in mem] for _, mem in groups])
        if not part['ok']: raise CE.Defect('joint stage %d: %s' % (v, part['why']))
        if len(groups) > 1: self.max_splits += len(groups) - 1
        out_bytes = sum(ENTRY_BYTES * vol_of([a for a in u if a != v], self.cards) + 128 for u, _ in groups); fam = (ENTRY_BYTES * vol_of(groups[0][0], self.cards) + COUNT_BYTES * vol_of(groups[0][0], self.cards) + 256) if self.mode == 'seed' else 0
        peak_extra = max(ENTRY_BYTES * vol_of(u, self.cards) * 2 for u, _ in groups)
        self.owned[0] += self.budget.charge(out_bytes + fam + peak_extra, 'joint stage %d outputs + family + workspace' % v); self._bump(); self.budget.release(peak_extra); self.owned[0] -= peak_extra
        outs = []; rec = dict(v=v, groups=[], mode=self.mode); cond = None; charged_now = out_bytes + fam
        try:
            inv = [T.tid for T in self.active]
            for gi, (u, mem) in enumerate(groups):
                self.clock.poll('before joint group %d of variable %d' % (gi, v)); P = _norm(product_exact(mem, u, self.cards)); self.work_cells += vol_of(u, self.cards) * len(mem)
                agg = 'max'
                if (self.mode == 'seed' or self.mode == 'sum') and gi == 0: agg = 'sum'
                if agg == 'sum': R, raxes = sum_over_up(P, u, [v])
                else: R, raxes = max_over(P, u, [v])
                T = JTable(raxes, R, self.next_tid, ('sum_message' if agg == 'sum' else 'max_message', v, tuple(t.tid for t in mem))); self.next_tid += 1
                receipt = CJ.check_stage(mem, T, v, self.cards, agg, self.clock, inventory=inv, bucket_ids=[t.tid for t in bucket], P=(P if agg == 'sum' else None)); self.checker_receipts.append(receipt)
                if not receipt['ok']: raise CE.Defect('joint stage checker rejected group %d of variable %d: %s' % (gi, v, receipt.get('why')))
                if self.mode == 'seed' and gi == 0:
                    parents = tuple(a for a in u if a != v); k = self.cards[v]; zi = u.index(v); Pm = np.moveaxis(P, zi, -1).reshape(-1, k); Mf = R.reshape(-1); counts = np.empty((Pm.shape[0], k), dtype=np.int64); zr = 0
                    for ri in range(Pm.shape[0]):
                        c, zero = floor_ratio_counts(list(Pm[ri]), Mf[ri], k); counts[ri] = c; zr += int(zero)
                        if (ri & 255) == 255: self.clock.poll('in the seed count rule of variable %d' % v)
                    cond = Conditional(v, parents, counts, self.cards); crec = CJ.check_seed_rows(Pm, Mf, counts, k, self.clock); self.checker_receipts.append(crec)
                    if not crec['ok']: raise CE.Defect('seed row check rejected variable %d: %s' % (v, crec.get('why')))
                    self.zero_rows += zr; self.k_values.append(k); rec['family'] = dict(z=v, parents=list(parents), volume=int(counts.size), zero_rows=zr)
                outs.append(T); rec['groups'].append(dict(inputs=[t.tid for t in mem], input_origins=[str(t.origin) for t in mem], union_axes=list(u), output=T.tid, output_axes=list(raxes), agg=agg, volume=int(P.size), consumed_messages=sum(1 for t in mem if t.origin[0].endswith('message'))))
        except BaseException:
            for T in outs: self._release_table(T)
            rest = max(0, charged_now - sum(T.bytes for T in outs)); self.budget.release(rest); self.owned[0] -= rest; raise
        rest = max(0, charged_now - sum(T.bytes for T in outs) - (cond.bytes if cond is not None else 0)); self.budget.release(rest); self.owned[0] -= rest
        for T in bucket: self.active.remove(T); self._release_table(T)
        for T in outs:
            if T.axes: self.active.append(T)
            else: self.scalars.append(T.arr.reshape(-1)[0]); self._release_table(T)
        if cond is not None: self.conditionals[v] = cond
        self.consumed_messages += sum(g['consumed_messages'] for g in rec['groups']); self.plan.append(rec); self.stages_done += 1
    def run(self, deadline_fn=None):
        for v in self.order:
            if deadline_fn is not None and deadline_fn(): raise RefusedJoint('ALLOWANCE', 'joint %s pass: the phase deadline arrived before variable %d (%d of %d stages)' % (self.mode, v, self.stages_done, len(self.order)))
            self.stage(v)
        return self
    def scalar_product(self):
        """U = the upward product of every scalar message (exact zero if any is zero)"""
        U = (0, 1)
        for k in self.scalars:
            if k[1] == 0: return ZERO
            U = norm_up(*mul_exact(U, k))
        return norm_up(*U) if U[1] else ZERO
    def retained_product(self):
        """witness passes: the final product of every remaining table over the retained family F, formed as a CHAIN of checked product steps of fan-in <= 16 (every intermediate retained table admitted before allocation,
        checked against the exact product of its inputs with the exact-once inventory, consumed inputs released at commit); the scalar messages enter the last step"""
        import check_joint as CJ
        Fax = tuple(sorted(self.retain)); bad = [T for T in self.active if not set(T.axes) <= set(Fax)]
        if bad: raise CE.Defect('retained product: a live table carries an eliminated variable: %s' % [(T.tid, T.axes) for T in bad])
        vol = vol_of(Fax, self.cards)
        if vol > self.V: raise RefusedJoint('VOLUME', 'the retained family (%d entries) exceeds the volume cap %d' % (vol, self.V))
        self.clock.poll('before the retained product'); steps = 0
        while True:
            live = sorted(self.active, key=lambda T: (-T.volume(), T.tid)); step_fanin = max(2, min(self.fanin, 16)); chunk = live[:step_fanin]; last = (len(live) <= step_fanin); uax = tuple(sorted(set(a for T in chunk for a in T.axes)))      # at least TWO tables per step (a chain of one-table steps would re-wrap forever: amendment 1 / D54)
            if last and uax != Fax: raise CE.Defect('retained product: the live tables cover %s, not the family %s' % (uax, Fax))      # every family variable carries its unary source: the final union IS F
            axes_out = Fax if last else uax; vol_out = vol_of(axes_out, self.cards)
            charge = ENTRY_BYTES * vol_out * 2 + 128; self.owned[0] += self.budget.charge(charge, 'retained family product step %d (%d entries)' % (steps, vol_out)); self._bump()
            try:
                P = _norm(product_exact(chunk, axes_out, self.cards))
                scal = list(self.scalars) if last else []
                for k in scal: sk = np.empty((), dtype=object); sk[()] = k; P = _norm(_mul(P, sk))
                T = JTable(axes_out, P, self.next_tid, ('retained', 'F' if last else 'partial', tuple(t.tid for t in chunk))); self.next_tid += 1
                receipt = CJ.check_stage(chunk, T, None, self.cards, 'product', self.clock, inventory=[t.tid for t in self.active], scalars=scal); self.checker_receipts.append(receipt)
                if not receipt['ok']: raise CE.Defect('retained product checker (step %d): %s' % (steps, receipt.get('why')))
            except BaseException:
                self.budget.release(charge); self.owned[0] -= charge; raise
            self.budget.release(ENTRY_BYTES * vol_out); self.owned[0] -= ENTRY_BYTES * vol_out
            for T_old in chunk: self.active.remove(T_old); self._release_table(T_old)
            self.active.append(T); self.work_cells += vol_out * max(1, len(chunk)); steps += 1
            if last: self.retained_steps = steps; return T
    def record(self):
        return dict(mode=self.mode, V=self.V, fanin=self.fanin, stages_done=self.stages_done, stages_total=len(self.order), max_splits=self.max_splits, work_cells=self.work_cells, consumed_messages=self.consumed_messages, peak_owned_bytes=self.peak_owned, zero_rows=self.zero_rows,
                    checker=dict(stages_checked=len(self.checker_receipts), all_ok=all(r['ok'] for r in self.checker_receipts), cells_checked=sum(r.get('cells', 0) for r in self.checker_receipts)), plan=self.plan, absent_sum_scalars=self.absent_sum_scalars,
                    plan_sha256=hashlib.sha256(repr((self.order, [(p.get('v'), [(g['inputs'], g['union_axes'], g['agg']) for g in p.get('groups', [])]) for p in self.plan], self.V, self.fanin, self.mode, self.retain)).encode()).hexdigest())


# ---------------------------------------------------------------- the seed: compile -> conditionals + cap
class Proposal:
    """an immutable proposal law: conditionals keyed by variable, the sampling order (reverse elimination), cap B (compact, W_0 units) with its provenance, the best checked second-moment witness S (compact, W_0^2 units)"""
    def __init__(self, cards, conds, sampling_order, B, S, provenance, predecessor=None):
        self.cards = list(cards); self.conds = dict(conds); self.order = list(sampling_order); self.B = B; self.S = S; self.provenance = provenance; self.predecessor = predecessor
        for v in self.order:
            c = self.conds[v]; pos = {w: i for i, w in enumerate(self.order)}
            assert all(pos[p] < pos[v] for p in c.parents), 'a parent is sampled after its child'
        self.bytes = sum(c.bytes for c in self.conds.values()); self.sha256 = hashlib.sha256(repr((self.order, [(v, self.conds[v].sha256) for v in self.order], self.B, self.S)).encode()).hexdigest()
    def log2_B(self): return log2_up(self.B) if self.B[1] else -math.inf
    def log2_S(self): return log2_up(self.S) if self.S[1] else -math.inf
    def work(self, n_target_factors_arity_sum, K):
        """the frozen relative per-draw work proxy: 1 + sum_target_factors (arity + 1) + sum_conditionals (parents + ceil log2 card + 2) + original query count"""
        return 1 + n_target_factors_arity_sum + sum(len(c.parents) + math.ceil(math.log2(self.cards[c.z])) + 2 for c in self.conds.values()) + K
    def sample(self, rng, B):
        """B draws: X (B, n) int64 and log2 q (B,) float = sum_v log2 count_v (the exact -40 n is carried separately by the stream); ONE integer uniform in [0, D) per variable, integer CDF lookup"""
        n = len(self.cards); X = np.zeros((B, n), dtype=np.int64); logc = np.zeros(B)
        for v in self.order:
            c = self.conds[v]; rows = c.row_index(X); u = rng.integers(0, D, size=B, dtype=np.int64); cum = c.cum[rows]; a = (cum <= u[:, None]).sum(axis=1); a = np.minimum(a, self.cards[v] - 1)
            X[:, v] = a; logc += np.log2(c.counts[rows, a].astype(float))
        return X, logc
    def logq_bits(self, X):
        """log2 q(X) of given assignments (the SAME float operations as sample: sum of log2 counts) and the exact rational q"""
        B = X.shape[0]; logc = np.zeros(B); qx = [F(1)] * B
        for v in self.order:
            c = self.conds[v]; rows = c.row_index(X); cnt = c.counts[rows, X[:, v]]; logc += np.log2(cnt.astype(float))
            for i in range(B): qx[i] *= F(int(cnt[i]), D)
        return logc, qx
    def q_exact(self, x):
        q = F(1)
        for v in self.order:
            c = self.conds[v]; row = sum(c.pstrides[p] * x[p] for p in c.parents); q *= F(int(c.counts[row, x[v]]), D)
        return q
    def record(self):
        return dict(sha256=self.sha256, order=self.order, conditionals=[dict(z=v, parents=list(self.conds[v].parents), volume=self.conds[v].family_volume(), counts_sha256=self.conds[v].sha256) for v in self.order], log2_B_W0=self.log2_B(), log2_S_W0sq=self.log2_S(), B=(self.B[0], str(self.B[1])), S=(self.S[0], str(self.S[1])), bytes=self.bytes, provenance=self.provenance, predecessor=self.predecessor)


def compile_seed(M_par, order, profile, budget, clock, deadline_fn=None, trace=None):
    """the checked seed proposal on the parent canonical model; returns (Proposal, record). Raises RefusedJoint / CE.Refused / CE.Defect with every owned byte released; on success the Proposal's conditionals are owned by
    the caller (their bytes are left charged: `owned_bytes` in the record)"""
    owned = [0]; cards = list(M_par.cards); t0 = CE.tnow()
    try:
        srcs = source_tables(M_par, budget, clock, owned, V=profile['V_seed']); comp = JointCompile(cards, srcs, order, profile['V_seed'], profile['fanin'], budget, clock, 'seed', owned=owned, trace=trace); comp.run(deadline_fn)
        if comp.active: raise CE.Defect('seed: live tables remain after the elimination: %s' % [(T.tid, T.axes) for T in comp.active])
        U = comp.scalar_product(); zero = (U[1] == 0)
        # the cap: U x prod_z D / (D - k_z), rounded upward
        B = U
        for k in comp.k_values:
            if not zero: B = norm_up(*mul_exact(B, from_fraction_up(F(D, D - k))))
        order_s = list(reversed(order)); conds = comp.conditionals
        if set(conds) != set(cards and range(len(cards))): raise CE.Defect('seed: a variable has no conditional')
        S0 = norm_up(*mul_exact(B, B)) if not zero else ZERO
        prop = Proposal(cards, conds, order_s, B, S0, dict(kind='seed', U=(U[0], str(U[1])), log2_U=(log2_up(U) if U[1] else -math.inf), D_over_D_minus_k_bits=sum(math.log2(D / (D - k)) for k in comp.k_values), zero_U=zero, V=profile['V_seed'], fanin=profile['fanin'], plan_sha256=comp.record()['plan_sha256']))
        rec = comp.record(); rec.update(seconds=CE.tnow() - t0, owned_bytes=owned[0], proposal=prop.record(), zero_U=zero)
        return prop, rec, owned[0]
    except BaseException:
        if owned[0]: budget.release(owned[0]); owned[0] = 0
        raise
