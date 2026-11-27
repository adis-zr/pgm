"""DGP6 global construction, part 1: the FIXED scalar witness circuits (theory sections 1-4; brief sections 1, 4a). For a frozen proposal graph (parent sets, sampling order) over the parent canonical model M_par the
CircuitPlan is built from STRUCTURE ONLY: sources = every unary / factor of W_0 (power 1 for the cap circuit B, power 2 for the moment circuit S) + ONE reciprocal leaf per conditional; the DGP5 mini-bucket plan
(buckets in the frozen elimination order, groups by decreasing volume / stable id / smallest admissible union, union volume <= 4,096, fan-in <= 16); per eliminated variable the cap circuit MAXes every group while the
moment circuit SUMs group 0 and MAXes the others (the accepted SUM / MAX splitting inequality); every scalar message is a factor of the closure product. Nodes (topologically ordered): source / reciprocal leaves, product
(exact multiplicity: each input once), reduce (SUM | MAX over one axis), closure (product of every scalar). The plan records axis maps, expected raw-source roles, work and peak-storage counts; no numeric quantity enters it.
Evaluation: (i) FLOATING, in log space over the same plan (reciprocal leaves = LSE(row logits) - selected logit, products = sums, SUM = logsumexp, MAX = max or the p-norm upper surrogate LSE(p x) / p inside the optimizer)
with a retained forward tape and a reverse pass whose row-logit gradient is theta sum_s d_s - d_z (rows sum to zero; repeated leaf uses accumulate; all-zero reductions stay -inf with zero adjoint; never NaN from -inf - -inf);
returns log B, log S, the objective and the gradient -- NEVER a certificate. (ii) COMPACT upward (certification) over the SAME plan from the ACTUAL counts with the repaired residual_max_envelope arithmetic (independent
source binding in check_global). Units: W_0 canonical (the external scalar separate); W_int = scale_F W_0 -> B x scale_F, S x scale_F^2. Smoothing inflation Delta (natural log) propagated structurally: leaves 0, product sum,
SUM max, smoothed MAX max + ln(m) / p; B / S combined by max (a floating diagnostic of the COMPILED objective only)."""
import math, itertools, hashlib
from fractions import Fraction as F
import numpy as np
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.quotient import residual_max_envelope as RM
from pgm.algorithms.quotient.residual_max_envelope import ZERO, norm_up, from_fraction_up, to_fraction, mul_exact, ge_exact, sum_up, lead, log2_up
from pgm.algorithms.quotient import joint_proposal as JP
from pgm.algorithms.quotient.joint_proposal import D, D_BITS, vol_of, RefusedJoint

LN2 = math.log(2.0); V_UNION = 4096; FANIN = 16; ENTRY_F = 8; ENTRY_C = RM.ENTRY_BYTES


class CircuitPlan:
    """immutable: graph (cards, order, parents per variable), the source inventory (role, key, axes, power), the node list, work / peak counts, a structural sha256"""
    def __init__(self, cards, sampling_order, parents, factors_scopes, power, order_elim, V=V_UNION, fanin=FANIN, clock=None, budget=None):
        # DGP7 repair R3 + DGP9 repair (original DGP7 finding F4a / F4b): the clock is POLLED AT ENTRY before any allocation; the plan's metadata (node dicts, stage records, the structural hash) is ADMITTED before any node is built
        # (a bounded estimate: sources + <= 4 nodes per eliminated variable per group, 512 B each) and the construction is POLLED once per eliminated variable; the charge STAYS with the plan while it is reachable (the DGP8
        # code released it in `finally` on success while the plan remained live): the owner releases it through `release()` when it drops the plan; a failed construction releases it here
        if clock is not None: clock.poll('circuit plan construction entry')
        n_ = len(cards); self._meta_estimate = 512 * (2 * n_ + len(factors_scopes) + 4 * n_ * max(1, fanin)); self._budget = budget; self._charged = budget.charge(self._meta_estimate, 'circuit plan metadata') if budget is not None else 0
        try: self._build(cards, sampling_order, parents, factors_scopes, power, order_elim, V, fanin, clock)
        except BaseException:
            if budget is not None and self._charged: budget.release(self._charged); self._charged = 0
            raise
    def release(self):
        """the owner drops the plan: its metadata charge returns to the shared account (idempotent)"""
        if self._charged and self._budget is not None: self._budget.release(self._charged)
        n = self._charged; self._charged = 0; return n
    close = release                                                                                                      # DGP10: the reservation.Txn adoption interface (idempotent)
    @property
    def closed(self): return self._charged == 0
    @property
    def charged_bytes(self): return self._charged
    def _build(self, cards, sampling_order, parents, factors_scopes, power, order_elim, V, fanin, clock):
        self.cards = list(cards); self.order = list(sampling_order); self.parents = {int(v): tuple(parents[v]) for v in parents}; self.power = int(power); self.V = int(V); self.fanin = int(fanin); self.kind = 'cap' if power == 1 else 'moment'
        n = len(cards); nodes = []; live = []                                                   # live: (node id, axes)
        # ---- sources: unaries, factors (sorted axes), reciprocals (sorted parents + z)
        for v in range(n): nodes.append(dict(op='source', role='unary', key=v, axes=(v,), power=power)); live.append((len(nodes) - 1, (v,)))
        for fi, sc in enumerate(factors_scopes): axes = tuple(sorted(sc)); nodes.append(dict(op='source', role='factor', key=fi, axes=axes, power=power, scope=tuple(sc))); live.append((len(nodes) - 1, axes))
        for v in self.order: axes = tuple(sorted(self.parents[v] + (v,))); nodes.append(dict(op='source', role='reciprocal', key=v, axes=axes, power=1, layout=self.parents[v] + (v,))); live.append((len(nodes) - 1, axes))
        self.n_sources = len(nodes); work = 0; scalars = []; self.stages = []
        # peak storage (entries) with LAZILY materialized sources: a source lives only inside the product that consumes it; the live frontier = intermediate messages not yet consumed
        frontier = 0; peak = 0; self.red_input_entries = 0; frontier_b = 0; peak_b = 0
        for v in order_elim:
            if clock is not None: clock.poll('circuit plan construction (variable %d)' % v)
            bucket = [(nid, ax) for nid, ax in live if v in ax]
            if not bucket:
                if power == 2: nodes.append(dict(op='const_card', value=cards[v], axes=())); scalars.append(len(nodes) - 1)      # a variable absent from every live factor contributes its cardinality to a SUM
                self.stages.append(dict(v=v, groups=[], note='absent')); continue
            bucket.sort(key=lambda t: (-vol_of(t[1], cards), t[0])); groups = []
            for nid, ax in bucket:
                best = None
                for gi, (gax, mem) in enumerate(groups):
                    u = tuple(sorted(set(gax) | set(ax))); vol = vol_of(u, cards)
                    if vol <= V and len(mem) < fanin and (best is None or vol < best[0]): best = (vol, gi, u)
                if best is None:
                    if vol_of(ax, cards) > V: raise RefusedJoint('VOLUME', 'a table of %d entries exceeds the union cap %d' % (vol_of(ax, cards), V))
                    groups.append((ax, [(nid, ax)]))
                else: groups[best[1]] = (best[2], groups[best[1]][1] + [(nid, ax)])
            stage = dict(v=v, groups=[]); outs = []
            for gi, (u, mem) in enumerate(groups):
                agg = 'sum' if (power == 2 and gi == 0) else 'max'
                nodes.append(dict(op='product', inputs=[nid for nid, _ in mem], axes=u)); pid = len(nodes) - 1; work += vol_of(u, cards) * len(mem)
                raxes = tuple(a for a in u if a != v); nodes.append(dict(op='reduce', agg=agg, input=pid, axis=v, axes=raxes, m=cards[v])); rid = len(nodes) - 1; work += vol_of(u, cards); self.red_input_entries += vol_of(u, cards)
                stage['groups'].append(dict(inputs=[nid for nid, _ in mem], union=u, product=pid, reduce=rid, agg=agg, out_axes=raxes))
                src_in = sum(vol_of(ax, cards) for nid, ax in mem if nodes[nid]['op'] == 'source'); peak = max(peak, frontier + src_in + vol_of(u, cards) + vol_of(raxes, cards))
                src_b = sum(ENTRY_C * vol_of(ax, cards) + 128 for nid, ax in mem if nodes[nid]['op'] == 'source'); peak_b = max(peak_b, frontier_b + src_b + (2 * ENTRY_C * vol_of(u, cards) + 128) + (ENTRY_C * vol_of(raxes, cards) + 128))      # DGP7 repair R3: the symbolic peak uses the SAME per-node admission rule as compact_evaluate / certify
                if raxes: outs.append((rid, raxes))
                else: scalars.append(rid)
            live = [(nid, ax) for nid, ax in live if v not in ax] + outs; frontier = sum(vol_of(ax, cards) for nid, ax in live if nodes[nid]['op'] != 'source'); frontier_b = sum(ENTRY_C * vol_of(ax, cards) + 128 for nid, ax in live if nodes[nid]['op'] != 'source'); self.stages.append(stage)
        if live: raise CE.Defect('circuit plan: tables remain after the elimination: %s' % [ax for _, ax in live])
        nodes.append(dict(op='closure', inputs=list(scalars))); self.closure = len(nodes) - 1; self.nodes = nodes; self.work_cells = work; self.peak_entries = peak; self.peak_bytes_symbolic = peak_b; self.n_params = sum(vol_of(self.parents[v], cards) * cards[v] for v in self.order)
        self.max_splits = max([len(st['groups']) - 1 for st in self.stages if st.get('groups')] + [0]); self.n_reductions = sum(len(st.get('groups', [])) for st in self.stages)
        if clock is not None: clock.poll('circuit plan hash')
        self.sha256 = self.structural_sha256()
    def structural_sha256(self):
        """the structural identity: cards, sampling order, parents, every node's op / role / key / axes / inputs / aggregation / eliminated axis / constant, power, caps (no numeric quantity)"""
        return hashlib.sha256(repr((self.cards, self.order, sorted(self.parents.items()), [(nd['op'], nd.get('role'), nd.get('key'), nd.get('axes'), nd.get('inputs'), nd.get('input'), nd.get('agg'), nd.get('axis'), nd.get('value')) for nd in self.nodes], self.power, self.V, self.fanin)).encode()).hexdigest()
    def n_source_cells(self, cards): return sum(vol_of(nd['axes'], cards) for nd in self.nodes if nd['op'] == 'source')
    def float_tape_bytes(self):
        """the retained forward tape (softmax weights of every reduction = its product's volume; the reciprocal rows' logits + LSE = 2 n_params; the live frontier of products / messages) + the reverse adjoint frontier (freed
        progressively: <= 2 x the peak frontier) + the parameter vector; counted per 8-byte entry"""
        return ENTRY_F * (self.red_input_entries + 3 * self.n_params + 3 * self.peak_entries) + 64 * len(self.nodes)
    def compact_peak_bytes(self): return self.peak_bytes_symbolic + 128 * len(self.nodes)                                                   # R3: the symbolic simultaneous ownership (admission rule) + per-node metadata slack
    def record(self): return dict(kind=self.kind, power=self.power, V=self.V, fanin=self.fanin, n_sources=self.n_sources, n_nodes=len(self.nodes), n_reductions=self.n_reductions, max_splits=self.max_splits, work_cells=self.work_cells, peak_entries=self.peak_entries, n_params=self.n_params, float_tape_bytes=self.float_tape_bytes(), compact_peak_bytes=self.compact_peak_bytes(), sha256=self.sha256, stages=[dict(v=s['v'], groups=[(g['agg'], len(g['inputs']), vol_of(g['union'], self.cards)) for g in s.get('groups', [])]) for s in self.stages])


def build_plans(M_par, prop_order, parents, order_elim, V=V_UNION, fanin=FANIN, budget=None, clock=None):
    """the cap plan (power 1) and the moment plan (power 2) of one frozen graph (DGP7 repair R3: admitted + polled when a budget / clock is given). DGP10 (DGP9 independent review F9-2): the two plans are constructed SEQUENTIALLY
    inside ONE reservation transaction -- the first plan is ADOPTED by the transaction, so a refusal / deadline while constructing the second closes the first INSIDE this constructor (its metadata charge returns to the shared
    account) before the exception propagates; the caller never owns a tuple that was not returned (probe_partial_plan_ownership: the 135,168 B orphan)"""
    from pgm.algorithms.quotient import reservation as RV
    cards = list(M_par.cards); scopes = [tuple(sc) for sc, _ in M_par.factors]
    with RV.Txn(budget, clock, 'global two-plan construction') as txn:
        p1 = CircuitPlan(cards, prop_order, parents, scopes, 1, order_elim, V, fanin, clock=clock, budget=budget); txn.adopt(p1)
        p2 = CircuitPlan(cards, prop_order, parents, scopes, 2, order_elim, V, fanin, clock=clock, budget=budget)
        txn.adopted = []                                                                                                 # both constructed: the transaction hands them to the caller (no rollback scope remains)
    return p1, p2


# ---------------------------------------------------------------- the FLOATING evaluator (log space; forward tape + reverse)
def _bcast(arr, axes, union, cards): return arr.reshape([cards[a] if a in axes else 1 for a in union])


class FloatCircuit:
    """log-space evaluation of one plan at row logits; `source_logs` = {('unary', v) | ('factor', fi): log table over its sorted axes (power applied), ...}; reciprocal leaves from the logits; the tape is retained for reverse"""
    def __init__(self, plan, source_logs, cards):
        self.plan = plan; self.cards = list(cards); self.src = source_logs; self.n = len(cards)
        self.row_slices = {}; off = 0
        for v in plan.order: R = vol_of(plan.parents[v], cards); k = cards[v]; self.row_slices[v] = (off, R, k); off += R * k
        self.n_params = off; self.n_consumers = [0] * len(plan.nodes)                                               # a leaf / message may feed several products (repeated uses accumulate adjoints): its value is dropped after its LAST consumer
        for nd in plan.nodes:
            for j in (nd.get('inputs') or ([nd['input']] if nd['op'] == 'reduce' else [])): self.n_consumers[j] += 1
    def logits_from_counts(self, prop):
        """the parameter vector t = log(count) - max log(count) per row (the brief's initialization; every entry in [-40 ln 2, 0])"""
        t = np.zeros(self.n_params)
        for v in self.plan.order:
            off, R, k = self.row_slices[v]; c = prop.conds[v]; lc = np.log(c.counts.astype(float)); t[off:off + R * k] = (lc - lc.max(axis=1, keepdims=True)).reshape(-1)
        return t
    def forward(self, t, p_smooth=None, keep_hard_inputs=False):
        """-> (log value of the closure, tape); p_smooth None = exact MAX; else the p-norm upper surrogate LSE(p x) / p for every MAX reduction. Every node's value is dropped once its single consumer has used it (sources are
        consumed exactly once in these plans); the tape retains only what the reverse pass needs: the softmax weights of every reduction, the reciprocal rows' logits / LSE (and, for a hard MAX with keep_hard_inputs, the
        tie masks)"""
        P = self.plan; cards = self.cards; vals = [None] * len(P.nodes); aux = [None] * len(P.nodes); left = list(self.n_consumers)
        def used(j):
            left[j] -= 1
            if left[j] <= 0: vals[j] = None
        for i, nd in enumerate(P.nodes):
            op = nd['op']
            if op == 'source':
                if nd['role'] == 'reciprocal':
                    v = nd['key']; off, R, k = self.row_slices[v]; tr = t[off:off + R * k].reshape(R, k); m = tr.max(axis=1, keepdims=True); lse = m + np.log(np.exp(tr - m).sum(axis=1, keepdims=True)); rec = lse - tr      # log(1 / theta) = LSE(row) - t
                    layout = nd['layout']; axes = nd['axes']; arr = rec.reshape([cards[a] for a in layout]); perm = [layout.index(a) for a in axes]; vals[i] = np.ascontiguousarray(np.transpose(arr, perm)); aux[i] = dict(lse=lse, tr=tr, layout=layout, perm=perm)
                else: vals[i] = self.src[(nd['role'], nd['key'])]
            elif op == 'const_card': vals[i] = np.array(math.log(nd['value']))
            elif op == 'product':
                u = nd['axes']; acc = np.zeros([cards[a] for a in u])
                for j in nd['inputs']: acc = acc + _bcast(vals[j], P.nodes[j]['axes'], u, cards); used(j)
                vals[i] = acc
            elif op == 'reduce':
                x = vals[nd['input']]; ax = P.nodes[nd['input']]['axes'].index(nd['axis']); used(nd['input'])
                with np.errstate(invalid='ignore', over='ignore'):
                    m = np.max(x, axis=ax, keepdims=True); fin = np.isfinite(m); m0 = np.where(fin, m, 0.0)
                    if nd['agg'] == 'sum' or p_smooth is not None:
                        pp = 1.0 if nd['agg'] == 'sum' else float(p_smooth); w = np.exp(pp * (x - m0)); s_ = w.sum(axis=ax, keepdims=True); out = np.where(fin, m0 + np.log(np.where(s_ > 0, s_, 1.0)) / pp, -np.inf); aux[i] = dict(w=np.where(fin, w / np.where(s_ > 0, s_, 1.0), 0.0), ax=ax)
                    else:
                        out = m; hit = (x == m) & fin; cnt = hit.sum(axis=ax, keepdims=True); aux[i] = dict(w=np.where(hit, 1.0 / np.maximum(cnt, 1), 0.0), ax=ax, hard=True)                      # ties split equally (a subgradient)
                vals[i] = np.squeeze(out, axis=ax) if out.ndim else out
            elif op == 'closure': vals[i] = np.array(sum(float(vals[j]) for j in nd['inputs']))
        return float(vals[P.closure]), dict(aux=aux, t=t)
    def reverse(self, tape, upstream=1.0):
        """adjoint of the closure log value (scaled by `upstream`) w.r.t. every row logit: dlog/dt (rows sum to zero); repeated uses accumulate; -inf nodes get zero adjoint (the softmax weights of an all -inf fibre are 0);
        adjoints are freed as soon as they are propagated"""
        P = self.plan; cards = self.cards; aux = tape['aux']; adj = {P.closure: float(upstream)}; g = np.zeros(self.n_params)
        for i in range(len(P.nodes) - 1, -1, -1):
            nd = P.nodes[i]; a_i = adj.pop(i, None)
            if a_i is None: continue
            op = nd['op']
            if op == 'closure':
                for j in nd['inputs']: adj[j] = adj.get(j, 0.0) + a_i
            elif op == 'reduce':
                j = nd['input']; ax = aux[i]['ax']; ai = np.asarray(a_i, dtype=float); ai_e = np.expand_dims(ai, ax) if np.ndim(ai) else ai; contrib = ai_e * aux[i]['w']; adj[j] = (adj[j] + contrib) if j in adj else contrib
            elif op == 'product':
                u = nd['axes']; ai = np.asarray(a_i, dtype=float)
                for j in nd['inputs']:
                    jax = P.nodes[j]['axes']; red = tuple(k for k, a in enumerate(u) if a not in jax); c = ai.sum(axis=red) if red else ai; c = c.reshape([cards[a] for a in jax]); adj[j] = (adj[j] + c) if j in adj else c
            elif op == 'source' and nd['role'] == 'reciprocal':
                v = nd['key']; off, R, k = self.row_slices[v]; ax_ = aux[i]; inv = np.argsort(ax_['perm']); d_layout = np.transpose(np.asarray(a_i, dtype=float), inv).reshape(R, k)      # back to the (parents..., z) layout
                tr = ax_['tr']; lse = ax_['lse']; theta = np.exp(tr - lse); g[off:off + R * k] += (theta * d_layout.sum(axis=1, keepdims=True) - d_layout).reshape(-1)        # theta_z sum_s d_s - d_z
        return g
    def delta_smoothing(self, p_smooth):
        """structural smoothing inflation (natural log) of this plan at p: leaves 0; product sum; SUM max; smoothed MAX max + ln(m) / p"""
        P = self.plan; dl = [0.0] * len(P.nodes)
        for i, nd in enumerate(P.nodes):
            if nd['op'] == 'product': dl[i] = sum(dl[j] for j in nd['inputs'])
            elif nd['op'] == 'reduce': dl[i] = dl[nd['input']] + (math.log(nd['m']) / p_smooth if nd['agg'] == 'max' and p_smooth else 0.0)
            elif nd['op'] == 'closure': dl[i] = sum(dl[j] for j in nd['inputs'])
        return dl[P.closure]


def source_logs(M_par, power):
    """float log tables of W_0's unaries and factors over sorted axes (power applied); -inf for zero entries; a DIAGNOSTIC / optimizer quantity (the compact certifier re-derives the exact values)"""
    cards = list(M_par.cards); out = {}
    for v in range(len(cards)):
        with np.errstate(divide='ignore'): out[('unary', v)] = power * np.log(np.array([float(x) if x > 0 else 0.0 for x in M_par.psi[v]]))
    for fi, (sc, vals) in enumerate(M_par.factors):
        sc = tuple(sc); axes = tuple(sorted(sc)); arr = np.array([float(x) if x > 0 else 0.0 for x in vals]).reshape([cards[v] for v in sc])
        if axes != sc: arr = np.transpose(arr, [sc.index(v) for v in axes])
        with np.errstate(divide='ignore'): out[('factor', fi)] = power * np.log(np.ascontiguousarray(arr))
    return out


def objective(FB, FS, t, log_eta, p_smooth, mode='joint'):
    """f_p(t) = log(S + eta B) (natural log) with its gradient; mode 'cap_only' -> log B; 'moment_only' -> log S; returns dict(f, g, logB, logS, evals=1)"""
    lB, tB = FB.forward(t, p_smooth); lS, tS = FS.forward(t, p_smooth)
    if mode == 'cap_only': return dict(f=lB, g=FB.reverse(tB, 1.0), logB=lB, logS=lS)
    if mode == 'moment_only': return dict(f=lS, g=FS.reverse(tS, 1.0), logB=lB, logS=lS)
    a = lS; b = log_eta + lB; m = max(a, b)
    if not math.isfinite(m): return dict(f=m, g=np.zeros_like(t), logB=lB, logS=lS)
    wS = math.exp(a - m); wB = math.exp(b - m); f = m + math.log(wS + wB); wS /= (wS + wB); wB = 1.0 - wS
    return dict(f=f, g=FS.reverse(tS, wS) + FB.reverse(tB, wB), logB=lB, logS=lS)


def box_gap(f, g, t, lo=-D_BITS * LN2, hi=0.0):
    """the supporting-hyperplane bound L_p = f + g . (s - t) with s the box minimizer of the linear form (a floating DIAGNOSTIC of the compiled objective)"""
    s = np.where(g >= 0, lo, hi); return float(f + float(np.dot(g, s - t)))


# ---------------------------------------------------------------- the COMPACT producer evaluation over the same plan (actual counts)
def _node_bytes(plan, i, cards):
    nd = plan.nodes[i]; return ENTRY_C * vol_of(nd.get('axes', ()), cards) * (2 if nd['op'] == 'product' else 1) + 128


def materialize_source(nd, M_par, prop, cards, A, clock, tag=''):
    """the compact upward table of one source leaf over its sorted axes from the target (W_0^power) or the actual counts (D / c)"""
    axes = nd['axes']; arr = np.empty([cards[a] for a in axes], dtype=object)
    if nd['role'] == 'unary':
        for a_ in range(cards[nd['key']]): x = F(M_par.psi[nd['key']][a_]) ** nd['power']; arr[a_] = A.conv(x) if x > 0 else ZERO
    elif nd['role'] == 'factor':
        sc, vals_ = M_par.factors[nd['key']]; sc = tuple(sc); st = CE.strides([cards[v] for v in sc])
        for k_, idx in enumerate(itertools.product(*[range(cards[a]) for a in axes])):
            x = F(vals_[sum(st[j] * idx[axes.index(v)] for j, v in enumerate(sc))]) ** nd['power']; arr[idx] = A.conv(x) if x > 0 else ZERO
            if (k_ & 255) == 255: clock.poll('in circuit source %s' % tag)
    else:
        c = prop.conds[nd['key']]
        for k_, idx in enumerate(itertools.product(*[range(cards[a]) for a in axes])):
            row = sum(c.pstrides[p_] * idx[axes.index(p_)] for p_ in c.parents) if c.parents else 0; arr[idx] = from_fraction_up(F(D, int(c.counts[row, idx[axes.index(c.z)]])))
            if (k_ & 255) == 255: clock.poll('in circuit reciprocal %s' % tag)
    return arr


def compact_evaluate(plan, M_par, prop, budget, clock):
    """upward compact value of the closure at the ACTUAL counts over the structural plan: sources materialized LAZILY inside the product that consumes them (exact rationals of W_0^power; D / c for a reciprocal), products exact
    then normalized upward, SUM via the bounded upward sum, MAX by exact order, closure = exact product normalized upward. Every node is admitted before allocation (when a budget is given) and every consumed input is dropped
    + released right after its product / reduction, so the live set never exceeds the plan's lazy-source peak. Returns (value (e, m), record). The INDEPENDENT certifier (check_global.certify) re-derives the same plan."""
    cards = list(M_par.cards); A = RM.Arith('compact'); vals = {}; charged = {}; owned = 0; peak_owned = 0; t0 = CE.tnow(); cells = 0
    def admit(i, n_):
        nonlocal owned, peak_owned
        if budget is not None: budget.charge(n_, 'circuit node %d (%s)' % (i, plan.nodes[i]['op'])); charged[i] = n_; owned += n_; peak_owned = max(peak_owned, owned)      # DGP7 repair R3: the ACTUAL simultaneous ownership is measured and reconciled with the plan's symbolic peak
    def drop(j):
        nonlocal owned
        vals[j] = None
        if j in charged: budget.release(charged[j]); owned -= charged.pop(j)
    try:
        for i, nd in enumerate(plan.nodes):
            op = nd['op']
            if op == 'source': continue                                                                       # lazy: built inside its consuming product
            if op == 'const_card': vals[i] = np.array(from_fraction_up(F(nd['value'])), dtype=object).reshape(())
            elif op == 'product':
                u = nd['axes']; vol = vol_of(u, cards); clock.poll('before circuit product %d' % i)
                for j in nd['inputs']:
                    if plan.nodes[j]['op'] == 'source': admit(j, ENTRY_C * vol_of(plan.nodes[j]['axes'], cards) + 128); vals[j] = materialize_source(plan.nodes[j], M_par, prop, cards, A, clock, str(j)); cells += vals[j].size
                admit(i, ENTRY_C * vol * 2 + 128); acc = None
                for j in nd['inputs']:
                    v_ = _bcast(vals[j], plan.nodes[j]['axes'], u, cards); acc = v_ if acc is None else A.mul(acc, v_)
                vals[i] = A.norm(np.broadcast_to(acc, [cards[a] for a in u]).copy()); cells += vol * len(nd['inputs'])
                for j in nd['inputs']: drop(j)
            elif op == 'reduce':
                x = vals[nd['input']]; ax = plan.nodes[nd['input']]['axes'].index(nd['axis']); admit(i, ENTRY_C * vol_of(nd['axes'], cards) + 128); clock.poll('before circuit reduce %d' % i)      # R3: the reduce output is what stays live (its input is dropped right after)
                if nd['agg'] == 'max': out = np.maximum.reduce(x, axis=ax) if x.shape[ax] > 1 else x.reshape([s_ for k_, s_ in enumerate(x.shape) if k_ != ax])
                else:
                    mv = np.moveaxis(x, ax, -1); flat = mv.reshape(-1, mv.shape[-1]); res = np.empty(flat.shape[0], dtype=object)
                    for r in range(flat.shape[0]):
                        res[r] = sum_up(list(flat[r]))
                        if (r & 255) == 255: clock.poll('in circuit reduce %d' % i)
                    out = res.reshape(mv.shape[:-1])
                if not isinstance(out, np.ndarray): sc_ = np.empty((), dtype=object); sc_[()] = out; out = sc_
                vals[i] = out; cells += int(x.size); drop(nd['input'])
            elif op == 'closure':
                val = (0, 1)
                for j in nd['inputs']:
                    x = vals[j].reshape(-1)[0] if isinstance(vals[j], np.ndarray) else vals[j]
                    if x[1] == 0: val = ZERO; break
                    val = norm_up(*mul_exact(val, x))
                vals[i] = val
        res = vals[plan.closure]
        sym = plan.compact_peak_bytes()
        if budget is not None and peak_owned > sym: raise CE.Defect('compact circuit: the actual simultaneous ownership %d B exceeds the plan\'s symbolic peak %d B' % (peak_owned, sym))
        return res, dict(seconds=CE.tnow() - t0, cells=cells, log2=(log2_up(res) if res[1] else -math.inf), peak_owned_bytes=peak_owned, symbolic_peak_bytes=sym, peak_reconciled=(budget is None or peak_owned <= sym))
    finally:
        if owned > 0 and budget is not None: budget.release(owned)
