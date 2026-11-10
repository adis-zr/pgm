"""GENERAL_BIDI_V2 planner (repair of 9-10 Nov 2026): exact finite indexed IR over the SHARED reduced model; up to three metadata-only elimination
orders under ONE shared metadata cap and ONE shared optional-discovery wall; a cheap REPRESENTABLE BASELINE (identity views, FULL storage, no fusion)
is chosen BEFORE any optional discovery and can never be lost; optional discovery (exact response views, bounded support joins, complete-consumer
storage restriction, consumer fusion) is transactional per node and recorded with typed provenance (applied / checked no-op / skipped by row cap /
skipped by wall / not attempted); every candidate is checked for executability on the native kernel (int64 core volumes, allocation sizes) before
it can be selected; fusion is priced on the COMPLETE all-query path including reverse-time primal regeneration (the kernel's combined frame removes
the regeneration for the last streamed input of a row; the price reflects exactly that). Metadata only: nothing here allocates a value table.

Semantic object: the marked polynomial of the REDUCED model (adp.source.Reduced), whose decoder gives every ORIGINAL (variable, state) numerator as
eta * N_reduced(y, s) or eta * Z. The planner is UNTRUSTED: gbidi.validate re-derives ownership, scopes, consumer structure and every view identity
from the reduced model before execution; storage sets ("demand") and materialization flags are STORAGE decisions only (the kernel streams any read
outside the stored set and never treats absence as zero), so a wrong proposal there changes work, not the answer.

Program (bucket TREE; NOT a shared DAG -- see NOT_IMPLEMENTED in gbidi/executor.py): node x owns the eliminated variable x (its raw marker) and the
source factors / messages whose earliest remaining variable is x; output = sum_x prod inputs over the remaining scope, stored over CORE classes
(views) of that scope; its single consumer is the bucket of the earliest remaining variable of its scope, or a component root (scalar).
"""
from __future__ import annotations
import os, sys, math, time, collections
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from adp.engine import View, source_view, intersect_views

COMMON_RULES = ("exclude", "constants", "separate", "alias", "quotient")
COMMON_RULES_NOTE = ("shared qualified source reductions of adp.source (evidence restriction as exact indicator -> decoder C; pinned/constant factors -> scalar; exclude: a state "
                     "whose row is identically zero in some factor owns only zero monomials and is removed (decoder C 0); fix: a single remaining state (decoder C eta); separate: exact "
                     "entrywise rank-1 split of a table (no marker involved); alias: a factor whose support is a bijection u<->w makes every nonzero monomial carry x_w = sigma(x_u): w is "
                     "removed and its markers transported to u's states (decoder V u inv[s]); quotient: states of v whose rows are proportional in EVERY factor containing v are merged "
                     "with rho weights and unary W; the merged state's marker is the LINEAR program (sum_a rho_a lambda_{v,a})/W_r, which is 1 at lambda=1 and whose derivatives are the "
                     "decoder eta_a = rho_a/W_r. All are exact polynomial identities (GB-02 R1); the decoder is the original-query restoration. Validated against the brute-force oracle "
                     "on the ORIGINAL model with every rule firing (tests/test_gbidi.py) and by the reviewer's 463 independent exact decoder controls (R2 §3).")
METADATA_UPDATE_CAP = 3_000_000; ROW_INSPECTION_CAP = 1_000_000; POLL_UNITS = 4096
INT64_MAX = 2 ** 63 - 1; INT32_MAX = 2 ** 31 - 1
CAPS = {"source_ir_maps_output": 2 << 30, "value_cache": 2 << 30, "reverse_pinned": 1 << 30, "pending_adjoints": 512 << 20, "frames_scratch_publication": 512 << 20}
EXTERNAL_RSS_GIB = 8.0
NOT_IMPLEMENTED = {"shared_dag_multi_consumer_nodes": "every message has exactly ONE consumer (bucket tree); additive consumers of one node are not representable",
                   "recursive_conditioning_component_decomposition": "no cutset / residual-component schedule; the generic streamed evaluation is the only bounded alternative",
                   "two_axis_conditioning": "not implemented (TWO_AXIS_JOINT_MAX unused)",
                   "sparse_bag_row_contraction": "support joins restrict the STORED set; numerical loops still visit every eliminated state (rows with an exact-zero input are skipped)",
                   "bounded_output_blocks": "a stored node is allocated whole (reserved before allocation); the bounded alternative is streaming (zero memo), not 1,024-entry blocks",
                   "value_cache_lru_checkpoints": "no production cache / eviction policy: a node is either stored whole or streamed; eviction + regeneration is exercised only by the qualification hook",
                   "specialized_bipartite_component_kernel": "optional; not integrated",
                   "demand_passes": "ONE monotone support/demand pass (not three)",
                   "python_side_memory_accounting": "the five internal categories cover the NATIVE route (IR, source values + conversion temporaries, stored values, index maps, numerators + root scratch, pending adjoints, frames + scratch + export) and the exact fallback (tables, accumulators, odometer, product, export); Python-side storage (input bytes, Fraction tables, the planner's numpy support masks, records) is NOT charged: the external sampled process-tree RSS (8 GiB) is the only bound on it; GMP/MPFR allocation failure is not catchable (GMP aborts): the caps bound what the kernel asks GMP for",
                   "polling_quantum": "the deadline is checked within 4,096 charged primitive units PLUS one indivisible MPFR/GMP primitive (a single multiprecision operation is not interruptible); the external supervisor remains the backstop"}


class PlanStop(Exception):
    def __init__(self, kind, reason):
        super().__init__(reason); self.kind = kind; self.reason = reason


def prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


class Inspect:
    """the SHARED optional-discovery allowance (row-inspection cap + optional wall) AND the cell's hard cancellation deadline. Optional phases
    (spend, tick(optional=True)) are stopped by either limit; MANDATORY construction (tick(optional=False)) is stopped only by the hard deadline.
    Clocks are checked every POLL_UNITS charged units (not calls)."""
    def __init__(self, cap, deadline=None, hard_deadline=None):
        self.cap = cap; self.used = 0; self.deadline = deadline; self.hard_deadline = hard_deadline; self._since = 0; self.expired = False

    def check_clock(self, optional=True):
        now = time.monotonic()
        if self.hard_deadline is not None and now > self.hard_deadline:
            raise PlanStop("CELL_DEADLINE", "cell deadline reached during planning")
        if optional and self.deadline is not None and now > self.deadline:
            self.expired = True; raise PlanStop("DISCOVERY_WALL", "optional discovery wall exhausted")

    def spend(self, n=1):
        self.used += n; self._since += n
        if self.used > self.cap:
            raise PlanStop("ROW_INSPECTION_CAP", "row inspection cap %d exhausted" % self.cap)
        if self._since >= POLL_UNITS:
            self._since = 0; self.check_clock(optional=True)

    def tick(self, n=1, optional=True):
        """time-only charge (metadata work): checks the clocks every POLL_UNITS units without consuming rows"""
        self._since += n
        if self._since >= POLL_UNITS:
            self._since = 0; self.check_clock(optional=optional)

    def remaining(self):
        return max(0, self.cap - self.used)


class Budget:
    """the SHARED metadata-update cap across every heuristic order; `optional` selects which clock governs the construction"""
    def __init__(self, cap, inspect, optional):
        self.cap = cap; self.used = 0; self.inspect = inspect; self.optional = optional

    def spend(self, n=1):
        self.used += n
        if self.used > self.cap:
            raise PlanStop("METADATA_CAP", "metadata update cap %d exhausted" % self.cap)
        self.inspect.tick(n, optional=self.optional)


# ------------------------------------------------------------------------------------------------------------------- elimination orders (metadata only)
def order_original(dom, scopes, B):
    return sorted(dom), {"name": "original_id", "complete": True, "updates": 0}


def _greedy(dom, scopes, score_fn, name, B):
    """generic greedy elimination with lexicographic original-id ties; every adjacency insertion / removal and every scored pair is one metadata update."""
    adj = {v: set() for v in dom}
    for sc in scopes:
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b); B.spend()
    order = []; alive = set(dom)
    while alive:
        best = None
        for v in sorted(alive):
            s = score_fn(v, adj, dom, B)
            if best is None or s < best[0]:
                best = (s, v)
        v = best[1]; order.append(v); nb = adj[v]
        for a in nb:
            for b in nb:
                if a != b and b not in adj[a]:
                    adj[a].add(b); B.spend()
            adj[a].discard(v); B.spend()
        alive.discard(v); del adj[v]
    return order, {"name": name, "complete": True, "updates": B.used}


def order_min_fill(dom, scopes, B):
    def fill(v, adj, dom, B):
        nb = sorted(adj[v]); f = 0
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                if nb[j] not in adj[nb[i]]:
                    f += 1
            B.spend(len(nb) - i - 1)
        return f
    return _greedy(dom, scopes, fill, "min_fill", B)


def order_min_volume(dom, scopes, B):
    def vol(v, adj, dom, B):
        B.spend(len(adj[v]) + 1); return prod(len(dom[w]) for w in adj[v]) * len(dom[v])          # prospective bag cardinality volume
    return _greedy(dom, scopes, vol, "min_prospective_bag_volume", B)


ORDER_FN = {"original": order_original, "min_fill": order_min_fill, "min_volume": order_min_volume}
CONSTRUCTION_ORDER = ["original", "min_volume", "min_fill"]        # cheap first: a cheap good baseline exists before the expensive heuristic spends the wall
MANDATORY_ORDERS = ("original", "min_volume")                       # constructed under the metadata cap only (never wall-gated): GENERAL's baseline is never worse than PLAIN's fixed order


# ------------------------------------------------------------------------------------------------------------------- IR
_IDENTITY = {}


def identity_view(n):
    v = _IDENTITY.get(n)
    if v is None:
        v = View(list(range(n)), list(range(n)), [Fr(1)] * n); _IDENTITY[n] = v
    return v


class Node:
    """bucket of reduced variable x: inputs ("F", fid) / ("M", nid); output over scope (sorted remaining vars) stored by CORE classes."""
    __slots__ = ("nid", "x", "inputs", "scope", "views", "view_prov", "consumer", "component", "radix", "core_entries", "dense_entries", "x_card", "fused", "fused_by", "demand", "demand_prov", "support", "support_prov", "_support_out", "_support_out_bag", "materialize", "downgrade", "cost", "notes")

    def __init__(self, nid, x):
        self.nid = nid; self.x = x; self.inputs = []; self.scope = (); self.views = {}; self.view_prov = {}; self.consumer = None; self.component = None; self.radix = (); self.core_entries = 1; self.dense_entries = 1; self.x_card = 1
        self.fused = False; self.fused_by = None; self.demand = "FULL"; self.demand_prov = "FULL_MANDATORY"; self.support = None; self.support_prov = "NOT_ATTEMPTED"; self._support_out = None; self._support_out_bag = None; self.materialize = True; self.downgrade = None; self.cost = {}; self.notes = []

    def bag_rows_core(self):
        return self.core_entries * self.x_card

    def stored_entries(self):
        return self.core_entries if self.demand == "FULL" else len(self.demand)


class Program:
    def __init__(self, R, order, order_info, cfg, inspect, index):
        self.R = R; self.dom = R.dom; self.order = order; self.order_info = order_info; self.cfg = cfg; self.fac = {f.fid: f for f in R.factors}; self.inspect = inspect; self.index = index
        self.nodes = []; self.roots = []; self.unconsumed_scalars = []; self.discovery_stop = None; self._view_cache = {}
        self.mechanisms = {"views": {"state": "DISABLED" if not cfg["views"] else "ENABLED", "offered_axes": 0, "compressed_axes": 0, "checked_no_op_axes": 0, "skipped_axes": 0, "zero_row_axes": 0},
                           "demand": {"state": "DISABLED" if not cfg["demand_masks"] else "ENABLED", "nodes_restricted": 0, "entries_not_stored": 0, "nodes_checked_no_op": 0, "nodes_consumer_support_unknown": 0, "support_exhaustive_nodes": 0, "support_skipped_row_cap_nodes": 0, "support_skipped_wall_nodes": 0, "support_memory_nodes": 0, "support_not_attempted_nodes": 0},
                           "fusion": {"state": "DISABLED" if not cfg["fusion"] else "ENABLED", "edges_offered": 0, "edges_fused_by_policy": 0, "edges_declined_by_policy": 0, "edges_fused_by_memory": 0}}
        self._build(); self.restore_mandatory()

    # ---------------------------------------------------------------- bucket construction (metadata only)
    def _build(self):
        pos = {v: i for i, v in enumerate(self.order)}; pending = collections.defaultdict(list)
        for f in self.R.factors:
            if not f.scope:
                self.unconsumed_scalars.append(f.fid); continue
            pending[min(f.scope, key=lambda v: pos[v])].append(("F", f.fid))
        for x in self.order:
            nd = Node(len(self.nodes), x); nd.inputs = list(pending.pop(x, [])); sc = set()
            for kind, ref in nd.inputs:
                sc |= set(self.fac[ref].scope if kind == "F" else self.nodes[ref].scope)
            sc.discard(x); nd.scope = tuple(sorted(sc)); nd.x_card = len(self.dom[x]); nd.dense_entries = prod(len(self.dom[w]) for w in nd.scope)
            self.nodes.append(nd)
            if nd.scope:
                pending[min(nd.scope, key=lambda v: pos[v])].append(("M", nd.nid))
            else:
                self.roots.append(nd.nid)
        for nd in self.nodes:
            for kind, ref in nd.inputs:
                if kind == "M":
                    self.nodes[ref].consumer = nd.nid
        for r in self.roots:
            stack = [r]
            while stack:
                n = stack.pop(); self.nodes[n].component = r; stack += [ref for kind, ref in self.nodes[n].inputs if kind == "M"]
            self.inspect.tick(1, optional=False)

    def restore_mandatory(self):
        """the mandatory program: identity views, FULL storage, no fusion, every node materialized (then memory downgrades)."""
        for nd in self.nodes:
            nd.views = {w: identity_view(len(self.dom[w])) for w in nd.scope}; nd.view_prov = {w: "IDENTITY_MANDATORY" for w in nd.scope}
            nd.radix = tuple(len(self.dom[w]) for w in nd.scope); nd.core_entries = nd.dense_entries
            nd.support = None; nd.support_prov = "NOT_ATTEMPTED"; nd._support_out = None; nd._support_out_bag = None; nd.demand = "FULL"; nd.demand_prov = "FULL_MANDATORY"
            nd.fused = False; nd.fused_by = None; nd.materialize = True; nd.downgrade = None; nd.notes = []
        self.discovery_stop = None
        for m in self.mechanisms.values():
            for k in m:
                if k != "state":
                    m[k] = 0
        self._price(decide_fusion=False)

    # ---------------------------------------------------------------- optional discovery (transactional per node; typed provenance)
    def optional_discovery(self):
        try:
            if self.cfg["views"]:
                self._views()
            self._supports_and_demand()
        except PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                raise
            self.discovery_stop = ex.kind
            for nd in self.nodes:                                                                 # provenance of what was never reached
                for w in nd.scope:
                    if nd.view_prov.get(w) == "IDENTITY_MANDATORY" and self.cfg["views"]:
                        nd.view_prov[w] = "SKIPPED_" + ("WALL" if ex.kind == "DISCOVERY_WALL" else "ROW_CAP"); self.mechanisms["views"]["skipped_axes"] += 1
                if nd.support_prov == "NOT_ATTEMPTED":
                    nd.support_prov = "SKIPPED_" + ("WALL" if ex.kind == "DISCOVERY_WALL" else "ROW_CAP")
        self._finish_support_provenance(); self._price(decide_fusion=self.cfg["fusion"])

    def _source_view(self, f, k):
        key = (f.fid, k)
        if key not in self._view_cache:
            self.inspect.spend(len(f.table)); self._view_cache[key] = source_view(f, k)
        return self._view_cache[key]

    def _views(self):
        for nd in self.nodes:
            new = {}; prov = {}
            for w in nd.scope:                                                                   # compute every axis first; commit the node atomically (SB-02)
                n = len(self.dom[w]); self.mechanisms["views"]["offered_axes"] += 1; vs = []
                for kind, ref in nd.inputs:
                    if kind == "F":
                        f = self.fac[ref]
                        if w in f.scope:
                            vs.append(self._source_view(f, f.scope.index(w)))
                    else:
                        c = self.nodes[ref]
                        if w in c.scope:
                            vs.append(c.views[w])
                self.inspect.spend(n * max(1, len(vs)))
                v = intersect_views(vs, n)
                if any(c == -1 for c in v.cls):                                                  # a zero row along w in some input: that raw state's whole row is 0 -> explicit zero class
                    z = [a for a in range(n) if v.cls[a] == -1]; v = View([c if c >= 0 else len(v.reps) for c in v.cls], v.reps + [z[0]], v.ratio); prov[w] = "ZERO_ROW_CLASS"
                else:
                    prov[w] = "COMPRESSED" if len(v.reps) < n else "CHECKED_NO_OP"
                new[w] = v
            nd.views = new; nd.view_prov = prov; nd.radix = tuple(len(nd.views[w].reps) for w in nd.scope); nd.core_entries = prod(nd.radix)
            for w in nd.scope:
                self.mechanisms["views"]["compressed_axes" if prov[w] == "COMPRESSED" else "checked_no_op_axes" if prov[w] == "CHECKED_NO_OP" else "zero_row_axes"] += 1

    def _supports_and_demand(self):
        """Support: conservative superset of each node's nonzero output core entries by an exact vectorized join of source zero masks and child
        supports over the bag (radix + x) when the bag fits the REMAINING row budget (else typed SKIPPED_ROW_CAP). Storage restriction ("demand"):
        a message's stored set = core entries read by SOME supported row of its single consumer; FULL when the consumer's support is unknown.
        Entries outside the stored set are never requested by a supported row; if a row outside the support set requests one, the kernel streams it
        (GB-03 soundness does not depend on this analysis)."""
        for nd in self.nodes:
            if nd.bag_rows_core() <= self.inspect.remaining():
                self.inspect.spend(nd.bag_rows_core())
                try:
                    nd._support_out, nd.support = self._join_support(nd); nd.support_prov = "EXHAUSTIVE"
                except MemoryError:
                    nd.support = None; nd._support_out = None; nd.support_prov = "MEMORY"
            else:
                nd.support_prov = "SKIPPED_ROW_CAP"
            self.inspect.tick(1, optional=True)
        if not self.cfg["demand_masks"]:
            for nd in self.nodes:
                nd.demand_prov = "FULL_MANDATORY"
            return
        for nd in self.nodes:
            if nd.consumer is None:
                nd.demand_prov = "ROOT_FULL"; continue
            c = self.nodes[nd.consumer]
            if c._support_out_bag is None:
                nd.demand_prov = "FULL_CONSUMER_SUPPORT_UNKNOWN"; self.mechanisms["demand"]["nodes_consumer_support_unknown"] += 1; continue
            dem = self._demand_from_consumer(c, nd); own = nd.core_entries if nd._support_out is None else int(nd._support_out.sum())
            if len(dem) < nd.core_entries:
                nd.demand = dem; nd.demand_prov = "RESTRICTED"; self.mechanisms["demand"]["nodes_restricted"] += 1; self.mechanisms["demand"]["entries_not_stored"] += max(0, own - len(dem))
            else:
                nd.demand_prov = "CHECKED_NO_OP"; self.mechanisms["demand"]["nodes_checked_no_op"] += 1

    def _finish_support_provenance(self):
        m = self.mechanisms["demand"]
        for k in list(m):
            if k.startswith("support_"):
                m[k] = 0
        for nd in self.nodes:
            m["support_%s_nodes" % {"EXHAUSTIVE": "exhaustive", "SKIPPED_ROW_CAP": "skipped_row_cap", "SKIPPED_WALL": "skipped_wall", "MEMORY": "memory", "NOT_ATTEMPTED": "not_attempted"}[nd.support_prov]] += 1

    def _gather_index_lists(self, nd, scope_vars, cls_fn):
        lists = []; axes = []
        for w in scope_vars:
            if w == nd.x:
                lists.append(np.array([cls_fn(w, a) for a in range(nd.x_card)], dtype=np.int64)); axes.append(len(nd.scope))
            else:
                k = nd.scope.index(w); lists.append(np.array([cls_fn(w, raw) for raw in nd.views[w].reps], dtype=np.int64)); axes.append(k)
        return lists, axes

    def _broadcast_input(self, nd, arr, lists, axes):
        g = arr[np.ix_(*lists)] if lists else arr; shape = [1] * (len(nd.scope) + 1)
        perm = sorted(range(len(axes)), key=lambda i: axes[i]); g = np.transpose(g, perm) if len(perm) > 1 else g
        for i in perm:
            shape[axes[i]] = len(lists[i])
        return g.reshape(shape)

    def _join_support(self, nd):
        mask = np.ones(tuple(nd.radix) + (nd.x_card,), dtype=bool)
        for kind, ref in nd.inputs:
            if kind == "F":
                f = self.fac[ref]; arr = np.array([x != 0 for x in f.table], dtype=bool).reshape(f.card); lists, axes = self._gather_index_lists(nd, f.scope, lambda w, raw: raw)
            else:
                c = self.nodes[ref]
                if c._support_out is None:
                    continue
                arr = c._support_out.reshape(tuple(c.radix)); lists, axes = self._gather_index_lists(nd, c.scope, lambda w, raw, c=c: c.views[w].cls[raw])
            mask &= self._broadcast_input(nd, arr, lists, axes)
        nd._support_out_bag = mask; out = mask.any(axis=-1).reshape(-1); return out, int(mask.sum())

    def _demand_from_consumer(self, c, nd):
        idx = np.zeros(tuple(c.radix) + (c.x_card,), dtype=np.int64); stride = 1
        lists, axes = self._gather_index_lists(c, nd.scope, lambda w, raw: nd.views[w].cls[raw])
        for k in range(len(nd.scope) - 1, -1, -1):
            idx = idx + self._broadcast_input(c, lists[k] * stride, [np.arange(len(lists[k]))], [axes[k]]); stride *= nd.radix[k]
        return np.unique(idx[c._support_out_bag]).tolist()

    # ---------------------------------------------------------------- pricing (complete all-query path), fusion, memory caps
    def _price(self, decide_fusion):
        """Per node: stored entries = demand ∩ support; rows = stored x |D_x|; a VALUE row costs 2k (gather + multiply per input); a PULLBACK row costs
        3k+2 (prefix/suffix, numerator, scatter). Fusion (bottom-up, in elimination order so a fused child's EFFECTIVE per-row costs are known):
        fuse c into its consumer n iff the complete fused cost  n.rows x |D_c| x (per_row(c) [forward regeneration] + per_row_rev(c) + regen_rev)
        is <= the complete stored cost  c.rows x (per_row(c) + per_row_rev(c)) + stored entries, where regen_rev = per_row(c) unless c is the LAST
        STREAMED message input of n (the kernel's combined frame regenerates it once for both its value and its pullback). This is an operation-count
        PROXY of the static plan (storage-set misses change which inputs are unresolved per row at run time); indexing / hashing / publication are
        not counted. Reviewer's F4 control: it prices the actual extra arithmetic of fusion instead of asserting 'no extra arithmetic'."""
        bpe = self.cfg["bytes_per_entry"]
        for nd in self.nodes:
            if nd._support_out is not None and nd.demand != "FULL":
                dem = np.array(nd.demand, dtype=np.int64); nd.demand = dem[nd._support_out[dem]].tolist(); ent = len(nd.demand)
            elif nd._support_out is not None and nd.consumer is not None:                        # roots are always stored FULL (one entry; an all-zero support there is Z = 0, which the kernel computes)
                ent = int(nd._support_out.sum())
                if ent < nd.core_entries:
                    nd.demand = np.flatnonzero(nd._support_out).tolist(); nd.demand_prov = nd.demand_prov if nd.demand_prov == "RESTRICTED" else "SUPPORT_RESTRICTED"
            else:
                ent = nd.core_entries if nd.demand == "FULL" else len(nd.demand)
            rows = ent * nd.x_card; k = len(nd.inputs)
            nd.cost = {"entries": ent, "rows": rows, "per_row": 2 * k, "per_row_rev": 3 * k + 2, "bytes_values": ent * bpe, "bytes_index": (ent * 48 if nd.demand != "FULL" else 0), "bytes_adjoint": ent * bpe}
            nd.materialize = True; nd.fused = False; nd.fused_by = None; nd.downgrade = None
        self.mechanisms["fusion"]["edges_offered"] = self.mechanisms["fusion"]["edges_fused_by_policy"] = self.mechanisms["fusion"]["edges_declined_by_policy"] = self.mechanisms["fusion"]["edges_fused_by_memory"] = 0
        self._recompute_eff(decide_fusion=decide_fusion)

    def _recompute_eff(self, decide_fusion=False):
        for nd in self.nodes:
            k = len(nd.inputs); per_row = nd.cost["per_row"]; per_row_rev = nd.cost["per_row_rev"]; msgs = [ref for kind, ref in nd.inputs if kind == "M"]
            streamed = [ref for ref in msgs if self.nodes[ref].fused]
            for ref in msgs:
                c = self.nodes[ref]
                if c.fused:
                    regen_rev = 0 if ref == streamed[-1] else c.cost["eff_per_row"]                 # the kernel's combined frame regenerates the LAST STREAMED input once for value + pullback
                    per_row += c.x_card * c.cost["eff_per_row"]; per_row_rev += c.x_card * (c.cost["eff_per_row_rev"] + regen_rev)
            nd.cost["eff_per_row"] = per_row; nd.cost["eff_per_row_rev"] = per_row_rev; nd.cost["eff_fwd"] = nd.cost["rows"] * per_row; nd.cost["eff_rev"] = nd.cost["rows"] * per_row_rev
            if decide_fusion and nd.consumer is not None:
                c = self.nodes[nd.consumer]; cm = [ref for kind, ref in c.inputs if kind == "M" and (self.nodes[ref].fused or ref == nd.nid)]; self.mechanisms["fusion"]["edges_offered"] += 1
                regen_rev = 0 if cm[-1] == nd.nid else per_row                                        # price AS IF fused: nd would be the last streamed input iff no later message input of c is streamed
                fused_cost = c.cost["rows"] * nd.x_card * (per_row + per_row_rev + regen_rev); stored_cost = nd.cost["eff_fwd"] + nd.cost["eff_rev"] + nd.cost["entries"]
                nd.cost["fusion_price"] = {"fused": fused_cost, "stored": stored_cost}
                if fused_cost <= stored_cost:
                    nd.fused = True; nd.materialize = False; nd.fused_by = "POLICY"; self.mechanisms["fusion"]["edges_fused_by_policy"] += 1
                else:
                    self.mechanisms["fusion"]["edges_declined_by_policy"] += 1

    def apply_memory_caps(self, caps):
        """at most ONE precompiled downgrade per node: a stored node whose values + index + adjoint do not fit the remaining category caps becomes
        streamed (zero memo). Roots are always stored (one entry). Returns the downgraded node ids."""
        vals = caps["value_cache"]; idxb = caps["source_ir_maps_output"]; adjb = caps["pending_adjoints"]; used_v = used_i = used_a = 0; down = []
        for nd in self.nodes:                                                                        # roots FIRST (always stored; one entry each): their bytes count against the caps the other nodes see
            if nd.consumer is None and nd.materialize:
                used_v += nd.cost["bytes_values"]; used_a += nd.cost["bytes_adjoint"]
        for nd in sorted(self.nodes, key=lambda n: -n.cost["bytes_values"]):
            if not nd.materialize or nd.consumer is None:
                continue
            if used_v + nd.cost["bytes_values"] > vals or used_i + nd.cost["bytes_index"] > idxb or used_a + nd.cost["bytes_adjoint"] > adjb:
                nd.materialize = False; nd.fused = True; nd.fused_by = "MEMORY"; nd.downgrade = "MATERIALIZED_TO_STREAM"; down.append(nd.nid); self.mechanisms["fusion"]["edges_fused_by_memory"] += 1
            else:
                used_v += nd.cost["bytes_values"]; used_i += nd.cost["bytes_index"]; used_a += nd.cost["bytes_adjoint"]
        self._recompute_eff(); return down

    def representable(self):
        """executability on the native kernel: every core volume, stored allocation and index fits int64 / int32; else the typed reason."""
        for nd in self.nodes:
            if nd.core_entries > INT64_MAX:
                return "node %d (x=%d): core volume %s exceeds int64" % (nd.nid, nd.x, "2^%.1f" % math.log2(nd.core_entries))
            if any(r > INT32_MAX for r in nd.radix) or nd.x_card > INT32_MAX or len(nd.inputs) > INT32_MAX:
                return "node %d: radix / cardinality exceeds int32" % nd.nid
            if nd.materialize and nd.cost["entries"] * self.cfg["bytes_per_entry"] > INT64_MAX:
                return "node %d: stored allocation exceeds int64" % nd.nid
        return None

    def totals(self):
        fwd = sum(nd.cost["eff_fwd"] for nd in self.nodes if not nd.fused); rev = sum(nd.cost["eff_rev"] for nd in self.nodes if not nd.fused)
        vals = sum(nd.cost["bytes_values"] for nd in self.nodes if nd.materialize); idx = sum(nd.cost["bytes_index"] for nd in self.nodes if nd.materialize); adj = sum(nd.cost["bytes_adjoint"] for nd in self.nodes if nd.materialize)
        ideal = sum(nd.cost["rows"] * (nd.cost["per_row"] + nd.cost["per_row_rev"]) for nd in self.nodes); construction = sum(len(f.table) for f in self.fac.values()) + sum(nd.cost["entries"] for nd in self.nodes if nd.materialize) + 3 * len(self.roots) + 2
        return {"cold_work_proxy": fwd + rev + construction, "cold_work_values": fwd, "cold_work_reverse": rev, "cold_work_construction": construction, "ideal_reuse_lower": ideal, "bytes_values": vals, "bytes_index": idx, "bytes_adjoint": adj, "peak_reserved_bytes": vals + idx + adj,
                "nodes": len(self.nodes), "roots": len(self.roots), "fused": sum(1 for nd in self.nodes if nd.fused), "fused_by_policy": sum(1 for nd in self.nodes if nd.fused_by == "POLICY"), "fused_by_memory": sum(1 for nd in self.nodes if nd.fused_by == "MEMORY"),
                "planned_dense_entries": sum(nd.dense_entries for nd in self.nodes), "planned_core_entries": sum(nd.core_entries for nd in self.nodes), "stored_entries": sum(nd.cost["entries"] for nd in self.nodes if nd.materialize), "bag_rows": sum(nd.cost["rows"] for nd in self.nodes),
                "proxy_note": "operation-count PROXY of the implemented schedule (value rows x 2k, pullback rows x (3k+2), fused regeneration, source conversion, stored allocation, roots); not a time prediction; indexing / hashing / publication are not counted"}

    def record(self):
        return {"order": self.order_info, "candidate_index": self.index, "discovery_stop": self.discovery_stop,
                "nodes": [{"nid": nd.nid, "x": nd.x, "x_card": nd.x_card, "scope": list(nd.scope), "radix": list(nd.radix), "dense_entries": nd.dense_entries, "core_entries": nd.core_entries, "inputs": [list(i) for i in nd.inputs], "consumer": nd.consumer,
                           "support": (None if nd._support_out is None else int(nd._support_out.sum())), "support_prov": nd.support_prov, "stored": ("FULL" if nd.demand == "FULL" else len(nd.demand)), "demand_prov": nd.demand_prov, "materialize": nd.materialize, "fused": nd.fused, "fused_by": nd.fused_by, "downgrade": nd.downgrade,
                           "cost": nd.cost, "views": {str(w): len(nd.views[w].reps) for w in nd.scope}, "view_prov": {str(w): nd.view_prov[w] for w in nd.scope}, "notes": nd.notes} for nd in self.nodes],
                "roots": self.roots, "unconsumed_scalars": self.unconsumed_scalars, "totals": self.totals(), "mechanisms": self.mechanisms}


def plan(R, cfg, deadline=None, caps=None, hard_deadline=None):
    """Baseline-first candidate construction; returns (chosen Program, candidate table).
    `deadline` = the SHARED optional-discovery allowance (rows + wall); `hard_deadline` = the cell's cancellation deadline.
    1. MANDATORY orders (original, min_volume) under the shared metadata cap and the HARD deadline only; min_fill under the optional allowance too;
    2. the MANDATORY program of every complete order, memory caps applied, representability checked -> the BASELINE is the cheapest representable
       mandatory program (chosen before any optional work; never lost); 3. optional discovery per candidate (cheapest mandatory first) under the
       REMAINING optional allowance; a candidate whose optional result is not representable falls back to its mandatory program;
    4. rank complete representable candidates by (cold-work proxy, peak bytes, candidate index). Every candidate's state / reason is recorded."""
    caps = caps or CAPS; scopes = [f.scope for f in R.factors if f.scope]; inspect = Inspect(ROW_INSPECTION_CAP, deadline, hard_deadline); table = []; cands = []
    B_mand = Budget(METADATA_UPDATE_CAP, inspect, optional=False); B_opt = Budget(METADATA_UPDATE_CAP, inspect, optional=True); B_opt.used = 0
    wanted = list(cfg["orders"]); names = [n for n in CONSTRUCTION_ORDER if n in wanted]
    for name in names:
        idx = wanted.index(name); row = {"candidate": idx, "order": name, "mandatory_order": name in MANDATORY_ORDERS}
        try:
            B = B_mand if name in MANDATORY_ORDERS else B_opt; B_opt.used = B_mand.used = max(B_mand.used, B_opt.used)                      # ONE shared metadata cap
            if name not in MANDATORY_ORDERS:
                inspect.check_clock(optional=True)
            order, info = ORDER_FN[name](R.dom, scopes, B); row["order_updates"] = B.used
            P = Program(R, order, info, cfg, inspect, idx); P.apply_memory_caps(caps); rep = P.representable()
            row.update({"mandatory_totals": P.totals(), "mandatory_representable": rep is None, "mandatory_not_representable_reason": rep}); cands.append((P, row))
        except PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                raise
            row.update({"state": "ORDER_INCOMPLETE_" + ex.kind, "reason": ex.reason, "metadata_updates": max(B_mand.used, B_opt.used)})
            if ex.kind == "DISCOVERY_WALL":
                inspect.expired = True
        table.append(row)
    base = sorted([(P.totals()["cold_work_proxy"], P.totals()["peak_reserved_bytes"], P.index, P) for P, row in cands if P.representable() is None], key=lambda t: (t[0], t[1], t[2]))
    if not base:
        for P, row in cands:
            row["state"] = "NOT_REPRESENTABLE"
        detail = "; ".join("%s: %s" % (r["order"], r.get("mandatory_not_representable_reason") or r.get("state")) for r in table)
        raise PlanStop("NOT_REPRESENTABLE" if cands else "METADATA_CAP", ("no complete candidate order yields an executable program on this kernel: " if cands else "no candidate order completed under the metadata cap: ") + detail)
    baseline = base[0][3]; baseline_row = next(r for P, r in cands if P is baseline); baseline_row["baseline"] = True
    for P, row in sorted(cands, key=lambda pr: (pr[0].totals()["cold_work_proxy"], pr[0].index)):
        if inspect.expired or (deadline is not None and time.monotonic() > deadline):
            for nd in P.nodes:                                                                   # typed provenance: optional discovery never started for this candidate
                nd.support_prov = "SKIPPED_WALL"
                if cfg["views"]:
                    nd.view_prov = {w: "SKIPPED_WALL" for w in nd.scope}
                if cfg["demand_masks"] and nd.consumer is not None:
                    nd.demand_prov = "FULL_SKIPPED_WALL"
            P._finish_support_provenance(); P.discovery_stop = "DISCOVERY_WALL"
            row["state"] = "COMPLETE_MANDATORY_ONLY"; row["discovery"] = "DISCOVERY_WALL_EXHAUSTED_BEFORE_START"; row["totals"] = P.totals(); row["representable"] = P.representable() is None; continue
        if not (cfg["views"] or cfg["demand_masks"] or cfg["fusion"]):
            row["state"] = "COMPLETE_MANDATORY_ONLY"; row["discovery"] = "NO_OPTIONAL_MECHANISM_ENABLED"; row["totals"] = P.totals(); row["representable"] = P.representable() is None; continue
        P.optional_discovery(); down = P.apply_memory_caps(caps); rep = P.representable()
        if rep is not None:
            row["optional_not_representable_reason"] = rep; P.restore_mandatory(); down = P.apply_memory_caps(caps); row["state"] = "COMPLETE_MANDATORY_ONLY"
        else:
            row["state"] = "COMPLETE"
        row.update({"totals": P.totals(), "downgrades": down, "discovery_stop": P.discovery_stop, "representable": P.representable() is None})
    ok = [(P.totals()["cold_work_proxy"], P.totals()["peak_reserved_bytes"], P.index, P) for P, row in cands if P.representable() is None]
    ok.sort(key=lambda t: (t[0], t[1], t[2])); chosen = ok[0][3]
    for P, row in cands:
        row["chosen"] = P is chosen
    return chosen, table
