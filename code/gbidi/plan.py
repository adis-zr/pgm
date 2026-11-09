"""GENERAL_BIDI_V1 planner: exact finite indexed IR over the SHARED reduced model, three metadata-only elimination programs, exact response
storage views (proportional marker-free source rows; common refinement across operands; raw markers outside the view), bounded conservative
support, complete-consumer backward demand (union over consumers, FULL when unknown), per-edge consumer fusion pricing, memory-category
accounting and a conservative cold-work proxy. Metadata only: nothing here allocates a value table.

Semantic object: the marked polynomial of the REDUCED model (adp.source.Reduced), whose decoder gives every ORIGINAL (variable, state) numerator
as eta * N_reduced(y, s) or eta * Z. The marked interpretation of the shared reductions (evidence indicator, pinned/const scale, exclude = zero
polynomial removed, fix, separate = exact entrywise rank-1 identity, alias = diagonal support identity with marker transport, quotient = class
marker program (sum_a rho_a lambda_{v,a}) / W_r) is recorded in COMMON_RULES_NOTE and validated against the brute-force oracle in qualification.

Bucket program (REGION macro of SUM o MUL o GATHER): node x owns the eliminated variable x (its raw marker) and the source factors / messages
whose earliest remaining variable is x; output = sum_x prod inputs over the remaining scope, stored over CORE classes (views) of that scope; its
single consumer is the bucket of the earliest remaining variable of its scope, or the component root (scalar). Every source occurrence and every
reduced-variable marker is owned by exactly one bucket.
"""
from __future__ import annotations
import os, sys, math, time, itertools, collections
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from adp import source as SRC
from adp.engine import View, source_view, intersect_views

COMMON_RULES = ("exclude", "constants", "separate", "alias", "quotient")
COMMON_RULES_NOTE = ("shared qualified source reductions of adp.source (evidence restriction as exact indicator -> decoder C; pinned/constant factors -> scalar; exclude: a state "
                     "whose row is identically zero in some factor owns only zero monomials and is removed (decoder C 0); fix: a single remaining state (decoder C eta); separate: exact "
                     "entrywise rank-1 split of a table (no marker involved); alias: a factor whose support is a bijection u<->w makes every nonzero monomial carry x_w = sigma(x_u): w is "
                     "removed and its markers transported to u's states (decoder V u inv[s]); quotient: states of v whose rows are proportional in EVERY factor containing v are merged "
                     "with rho weights and unary W; the merged state's marker is the LINEAR program (sum_a rho_a lambda_{v,a})/W_r, which is 1 at lambda=1 and whose derivatives are the "
                     "decoder eta_a = rho_a/W_r. All are exact polynomial identities (GB-02 R1); the decoder is the original-query restoration. Validated in tests/test_gbidi.py against the "
                     "brute-force oracle on the ORIGINAL model with every rule firing.")
METADATA_UPDATE_CAP = 3_000_000; ROW_INSPECTION_CAP = 1_000_000; DEMAND_PASSES = 3; BLOCK_ENTRIES = 1024; POLL_OPS = 4096; TWO_AXIS_JOINT_MAX = 4096
CAPS = {"source_ir_maps_output": 2 << 30, "value_cache": 2 << 30, "reverse_pinned": 1 << 30, "pending_adjoints": 512 << 20, "frames_scratch_publication": 512 << 20}
EXTERNAL_RSS_GIB = 8.0


class PlanStop(Exception):
    def __init__(self, kind, reason):
        super().__init__(reason); self.kind = kind; self.reason = reason


def prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


# ------------------------------------------------------------------------------------------------------------------- elimination orders (metadata only)
class Budget:
    def __init__(self, cap):
        self.cap = cap; self.used = 0

    def spend(self, n=1):
        self.used += n
        if self.used > self.cap:
            raise PlanStop("METADATA_CAP", "metadata update cap %d exhausted" % self.cap)


def order_original(dom, scopes):
    return sorted(dom), {"name": "original_id", "complete": True, "updates": 0}


def _greedy(dom, scopes, score_fn, name):
    """generic greedy elimination with lexicographic original-id ties; every adjacency / score update is one metadata update."""
    B = Budget(METADATA_UPDATE_CAP); adj = {v: set() for v in dom}
    for sc in scopes:
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b); B.spend()
    order = []; alive = set(dom)
    try:
        while alive:
            best = None
            for v in sorted(alive):
                s = score_fn(v, adj, dom); B.spend()
                if best is None or s < best[0]:
                    best = (s, v)
            v = best[1]; order.append(v); nb = adj[v]
            for a in nb:
                for b in nb:
                    if a != b and b not in adj[a]:
                        adj[a].add(b); B.spend()
                adj[a].discard(v); B.spend()
            alive.discard(v); del adj[v]
    except PlanStop:
        return None, {"name": name, "complete": False, "updates": B.used, "cap": METADATA_UPDATE_CAP}
    return order, {"name": name, "complete": True, "updates": B.used}


def order_min_fill(dom, scopes):
    def fill(v, adj, dom):
        nb = sorted(adj[v]); f = 0
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                if nb[j] not in adj[nb[i]]:
                    f += 1
        return f
    return _greedy(dom, scopes, fill, "min_fill")


def order_min_volume(dom, scopes):
    def vol(v, adj, dom):
        return prod(len(dom[w]) for w in adj[v]) * len(dom[v])          # prospective bag cardinality volume (current scopes)
    return _greedy(dom, scopes, vol, "min_prospective_bag_volume")


# ------------------------------------------------------------------------------------------------------------------- IR
class Node:
    """bucket of reduced variable x: inputs ("F", fid) / ("M", nid); output over scope (sorted remaining vars) stored by CORE classes."""
    __slots__ = ("nid", "x", "inputs", "scope", "views", "consumer", "component", "radix", "core_entries", "dense_entries", "bag_rows", "x_card", "fused", "demand", "support", "_support_out", "_support_out_bag", "materialize", "downgrade", "cost", "depth", "range", "notes")

    def bag_rows_core(self):
        return self.core_entries * self.x_card

    def __init__(self, nid, x):
        self.nid = nid; self.x = x; self.inputs = []; self.scope = (); self.views = {}; self.consumer = None; self.component = None; self.radix = (); self.core_entries = 1; self.dense_entries = 1; self.bag_rows = 1; self.x_card = 1
        self.fused = False; self.demand = None; self.support = None; self._support_out = None; self._support_out_bag = None; self.materialize = True; self.downgrade = None; self.cost = {}; self.depth = {}; self.range = {}; self.notes = []


class Program:
    def __init__(self, R, order, order_info, cfg, inspect_budget):
        self.R = R; self.dom = R.dom; self.order = order; self.order_info = order_info; self.cfg = cfg; self.fac = {f.fid: f for f in R.factors}; self.inspect = inspect_budget
        self.nodes = []; self.roots = []; self.unconsumed_scalars = []; self.mechanisms = {"views": {"offered_axes": 0, "compressed_axes": 0, "state": "DISABLED" if not cfg["views"] else "APPLIED"}, "demand": {"nodes_with_explicit_demand": 0, "entries_skipped_by_demand": 0, "state": "DISABLED" if not cfg["demand_masks"] else "APPLIED"}, "fusion": {"edges_offered": 0, "edges_fused_by_policy": 0, "edges_fused_by_memory": 0, "state": "DISABLED" if not cfg["fusion"] else "APPLIED"}}
        self._view_cache = {}
        self._build(); self._identity_views(); self._supports_and_demand(optional=False); self._price_and_choose()

    def optional_discovery(self):
        """OPTIONAL phase under the shared discovery wall / row-inspection cap: exact response views (if enabled), bounded support joins and
        complete-consumer demand (if enabled); then re-price. A PlanStop inside leaves the mandatory program (identity views / FULL demand) in place."""
        try:
            if self.cfg["views"]:
                self._views()
            self._supports_and_demand(optional=True)
        except PlanStop as ex:
            self.mechanisms["discovery_stop"] = ex.kind
        self._price_and_choose()

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
            sc.discard(x); nd.scope = tuple(sorted(sc)); nd.x_card = len(self.dom[x]); nd.dense_entries = prod(len(self.dom[w]) for w in nd.scope); nd.bag_rows = nd.dense_entries * nd.x_card
            self.nodes.append(nd)
            if nd.scope:
                pending[min(nd.scope, key=lambda v: pos[v])].append(("M", nd.nid))
            else:
                self.roots.append(nd.nid)
        for nd in self.nodes:
            for kind, ref in nd.inputs:
                if kind == "M":
                    self.nodes[ref].consumer = nd.nid
        # components = trees of nodes ending at a root
        for r in self.roots:
            stack = [r]
            while stack:
                n = stack.pop(); self.nodes[n].component = r
                stack += [ref for kind, ref in self.nodes[n].inputs if kind == "M"]

    # ---------------------------------------------------------------- views: identity (mandatory) / exact response views (mechanism 3, optional)
    def _identity_views(self):
        for nd in self.nodes:
            for w in nd.scope:
                n = len(self.dom[w]); nd.views[w] = View(list(range(n)), list(range(n)), [Fr(1)] * n)
            nd.radix = tuple(len(nd.views[w].reps) for w in nd.scope); nd.core_entries = prod(nd.radix)

    def _source_view(self, f, k):
        key = (f.fid, k)
        if key not in self._view_cache:
            self.inspect.spend(len(f.table)); self._view_cache[key] = source_view(f, k)
        return self._view_cache[key]

    def _views(self):
        for nd in self.nodes:
            for w in nd.scope:
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
                v = intersect_views(vs, n)
                if any(c == -1 for c in v.cls):                                            # a zero row along w in some input: that raw state's whole row is 0 -> explicit zero class
                    v = View([c if c >= 0 else max(v.cls) + 1 for c in v.cls], v.reps + [next(a for a in range(n) if v.cls[a] == -1)], v.ratio); nd.notes.append("zero row along %d" % w)
                nd.views[w] = v
                if len(v.reps) < n:
                    self.mechanisms["views"]["compressed_axes"] += 1
            nd.radix = tuple(len(nd.views[w].reps) for w in nd.scope); nd.core_entries = prod(nd.radix)

    # ---------------------------------------------------------------- bounded support / complete-consumer demand (mechanisms 1 + 2)
    def _supports_and_demand(self, optional):
        """Support: conservative superset of each node's nonzero output core entries, by an exact vectorized join of source zero masks and child
        supports over the bag (radix + x) when the bag fits the row-inspection budget; else FULL (UNKNOWN). Demand: for a message, the set of its core
        entries read by SOME support row of its single consumer (union over all consumer rows; a message has one consumer in a bucket tree); FULL when
        the consumer's support is unknown. Entries outside demand ∩ support are never requested: every consumer row reading them has a proved-zero
        sibling, so their complete contribution (and all marker derivatives) is zero (GB-03)."""
        for nd in self.nodes:
            nd.support = "FULL"; nd._support_out = None; nd.demand = "FULL"
        if not optional:
            return
        for nd in self.nodes:
            if nd.bag_rows_core() <= self.inspect.remaining():
                self.inspect.spend(nd.bag_rows_core())
                try:
                    nd._support_out, nd.support = self._join_support(nd)
                except MemoryError:
                    nd.support = "FULL"; nd._support_out = None; nd.notes.append("support join: memory")
        if not self.cfg["demand_masks"]:
            return
        for nd in self.nodes:
            if nd.consumer is None:
                continue
            c = self.nodes[nd.consumer]
            if c.support == "FULL":
                continue
            dem = self._demand_from_consumer(c, nd); nd.demand = dem; self.mechanisms["demand"]["nodes_with_explicit_demand"] += 1
            own = nd.core_entries if nd._support_out is None else int(nd._support_out.sum()); self.mechanisms["demand"]["entries_skipped_by_demand"] += max(0, own - len(dem))

    def _gather_index_lists(self, nd, scope_vars, cls_fn):
        """for each var w of an input (child or factor), the list of its index per NODE grid axis (node scope classes -> representative raw -> input index)
        plus the x axis (last). Returns (index lists aligned with the input's axes, the node-grid axis each input axis maps to)."""
        lists = []; axes = []
        for w in scope_vars:
            if w == nd.x:
                lists.append(np.array([cls_fn(w, a) for a in range(nd.x_card)], dtype=np.int64)); axes.append(len(nd.scope))
            else:
                k = nd.scope.index(w); lists.append(np.array([cls_fn(w, raw) for raw in nd.views[w].reps], dtype=np.int64)); axes.append(k)
        return lists, axes

    def _broadcast_input(self, nd, arr, lists, axes):
        """gather arr (indexed by the input's own axes) onto the node bag grid (radix + (x_card,))"""
        g = arr[np.ix_(*lists)] if lists else arr                                   # shape: product over input axes of list lengths, in the input's axis order
        shape = [1] * (len(nd.scope) + 1)
        perm = sorted(range(len(axes)), key=lambda i: axes[i]); g = np.transpose(g, perm) if len(perm) > 1 else g
        for i in perm:
            shape[axes[i]] = len(lists[i])
        return g.reshape(shape)

    def _join_support(self, nd):
        """exact conservative support of nd's bag rows (grid radix + x): AND of every source input's nonzero mask and every child's output support
        gathered onto the grid; the output support is the OR over x. Keeps the bag mask for the demand projection."""
        mask = np.ones(tuple(nd.radix) + (nd.x_card,), dtype=bool)
        for kind, ref in nd.inputs:
            if kind == "F":
                f = self.fac[ref]; arr = np.array([x != 0 for x in f.table], dtype=bool).reshape(f.card)
                lists, axes = self._gather_index_lists(nd, f.scope, lambda w, raw: raw)
            else:
                c = self.nodes[ref]
                if c._support_out is None:
                    continue
                arr = c._support_out.reshape(tuple(c.radix)); lists, axes = self._gather_index_lists(nd, c.scope, lambda w, raw, c=c: c.views[w].cls[raw])
            mask &= self._broadcast_input(nd, arr, lists, axes)
        nd._support_out_bag = mask
        out = mask.any(axis=-1).reshape(-1)
        return out, int(mask.sum())

    def _demand_from_consumer(self, c, nd):
        """core indices of child nd read by the SUPPORTED bag rows of its consumer c: build the child-index grid over c's bag (sum of per-axis
        class indices times the child's strides), select the supported rows, unique."""
        if c._support_out_bag is None:
            return "FULL"
        idx = np.zeros(tuple(c.radix) + (c.x_card,), dtype=np.int64); stride = 1
        lists, axes = self._gather_index_lists(c, nd.scope, lambda w, raw: nd.views[w].cls[raw])
        for k in range(len(nd.scope) - 1, -1, -1):
            idx = idx + self._broadcast_input(c, lists[k] * stride, [np.arange(len(lists[k]))], [axes[k]]); stride *= nd.radix[k]
        return np.unique(idx[c._support_out_bag]).tolist()

    # ---------------------------------------------------------------- fusion pricing, memory, cost proxy
    def _price_and_choose(self):
        """Per node: entries actually requested (demand ∩ support), rows = entries x |D_x|, materialized forward work = rows x 2k (k inputs: one gather
        + one multiply each), reverse work = rows x (3k+2) (prefix/suffix + adjoint scatter). Fusion decision per edge, BOTTOM-UP in elimination order
        so a fused child's EFFECTIVE per-row cost (including its own fused subtree, zero memo) is known: fuse child c into its consumer n iff
        re-evaluating c's entry once per consumer row costs no more than materializing it (n.rows x |D_c| x eff_per_row(c) <= c.eff_fwd + c.entries).
        A single-consumer message read bijectively (consumer rows == child entries) is therefore fused (no extra arithmetic, no storage); a child
        read many times is not."""
        bpe = self.cfg["bytes_per_entry"]
        for nd in self.nodes:
            if nd._support_out is not None and nd.demand != "FULL":
                dem = np.array(nd.demand, dtype=np.int64); nd.demand = dem[nd._support_out[dem]].tolist()                 # demand ∩ support: the materialized set
                ent = len(nd.demand)
            elif nd._support_out is not None:
                ent = int(nd._support_out.sum()); nd.demand = np.flatnonzero(nd._support_out).tolist() if ent < nd.core_entries else "FULL"
            else:
                ent = nd.core_entries if nd.demand == "FULL" else len(nd.demand)
            rows = ent * nd.x_card; k = len(nd.inputs)
            nd.cost = {"entries": ent, "rows": rows, "fwd_work": rows * 2 * k, "rev_work": rows * (3 * k + 2), "bytes_values": ent * bpe, "bytes_index": (ent * 16 if nd.demand != "FULL" else 0), "bytes_adjoint": ent * bpe}
            nd.materialize = True; nd.fused = False; nd.downgrade = None
        self.mechanisms["fusion"]["edges_offered"] = 0; self.mechanisms["fusion"]["edges_fused_by_policy"] = 0
        self._recompute_eff(decide_fusion=self.cfg["fusion"])

    def _recompute_eff(self, decide_fusion=False):
        """bottom-up effective costs under the current fused flags (optionally deciding policy fusion edge by edge)."""
        for nd in self.nodes:                                                            # elimination order: every message input has a smaller nid
            k = len(nd.inputs); per_row = 2 * k; per_row_rev = 3 * k + 2
            for kind, ref in nd.inputs:
                if kind == "M" and self.nodes[ref].fused:
                    c = self.nodes[ref]; per_row += c.x_card * c.cost["eff_per_row"]; per_row_rev += c.x_card * c.cost["eff_per_row_rev"]
            nd.cost["eff_per_row"] = per_row; nd.cost["eff_per_row_rev"] = per_row_rev; nd.cost["eff_fwd"] = nd.cost["rows"] * per_row; nd.cost["eff_rev"] = nd.cost["rows"] * per_row_rev
            if decide_fusion and nd.consumer is not None:
                c = self.nodes[nd.consumer]; self.mechanisms["fusion"]["edges_offered"] += 1
                if c.cost["rows"] * nd.x_card * per_row <= nd.cost["eff_fwd"] + nd.cost["entries"]:
                    nd.fused = True; nd.materialize = False; self.mechanisms["fusion"]["edges_fused_by_policy"] += 1

    def totals(self):
        fwd = sum(nd.cost["eff_fwd"] for nd in self.nodes if not nd.fused); rev = sum(nd.cost["eff_rev"] for nd in self.nodes if not nd.fused)
        vals = sum(nd.cost["bytes_values"] for nd in self.nodes if nd.materialize); idx = sum(nd.cost["bytes_index"] for nd in self.nodes if nd.materialize); adj = sum(nd.cost["bytes_adjoint"] for nd in self.nodes if nd.materialize)
        ideal = sum(nd.cost["fwd_work"] + nd.cost["rev_work"] for nd in self.nodes)
        return {"cold_work_proxy": fwd + rev, "ideal_reuse_lower": ideal, "bytes_values": vals, "bytes_index": idx, "bytes_adjoint": adj, "peak_reserved_bytes": vals + idx + adj, "nodes": len(self.nodes), "roots": len(self.roots), "fused": sum(1 for nd in self.nodes if nd.fused), "planned_dense_entries": sum(nd.dense_entries for nd in self.nodes), "planned_core_entries": sum(nd.core_entries for nd in self.nodes), "demanded_entries_all_nodes": sum(nd.cost["entries"] for nd in self.nodes), "materialized_entries": sum(nd.cost["entries"] for nd in self.nodes if nd.materialize), "bag_rows": sum(nd.cost["rows"] for nd in self.nodes)}

    def apply_memory_caps(self, caps):
        """at most ONE precompiled downgrade per region: a materialized node whose values + index + adjoint do not fit the remaining category caps
        becomes streamed (fused into its consumer, zero memo). Recorded as a memory downgrade, distinct from policy fusion. Root nodes cannot be
        fused; a root that does not fit is a typed resource stop (its scope is empty: entries = 1, so this never triggers)."""
        vals = caps["value_cache"]; idxb = caps["source_ir_maps_output"]; adjb = caps["reverse_pinned"]; used_v = used_i = used_a = 0; down = []
        for nd in sorted(self.nodes, key=lambda n: -n.cost["bytes_values"]):
            if not nd.materialize:
                continue
            if nd.consumer is None:
                used_v += nd.cost["bytes_values"]; used_a += nd.cost["bytes_adjoint"]; continue                 # a root has ONE entry; it is always materialized (the kernel's own reserve decides)
            if used_v + nd.cost["bytes_values"] > vals or used_i + nd.cost["bytes_index"] > idxb or used_a + nd.cost["bytes_adjoint"] > adjb:
                nd.materialize = False; nd.fused = True; nd.downgrade = "MATERIALIZED_TO_STREAM"; down.append(nd.nid); self.mechanisms["fusion"]["edges_fused_by_memory"] += 1
            else:
                used_v += nd.cost["bytes_values"]; used_i += nd.cost["bytes_index"]; used_a += nd.cost["bytes_adjoint"]
        self._recompute_eff(); return down

    def record(self):
        return {"order": self.order_info, "nodes": [{"nid": nd.nid, "x": nd.x, "x_card": nd.x_card, "scope": list(nd.scope), "radix": list(nd.radix), "dense_entries": nd.dense_entries, "core_entries": nd.core_entries, "bag_rows": nd.bag_rows, "inputs": [list(i) for i in nd.inputs], "consumer": nd.consumer,
                                                   "support": ("FULL" if nd._support_out is None else int(nd._support_out.sum())), "demand": ("FULL" if nd.demand == "FULL" else len(nd.demand)), "materialize": nd.materialize, "fused": nd.fused, "downgrade": nd.downgrade, "cost": nd.cost, "views": {str(w): len(nd.views[w].reps) for w in nd.scope}, "notes": nd.notes} for nd in self.nodes],
                "roots": self.roots, "unconsumed_scalars": self.unconsumed_scalars, "totals": self.totals(), "mechanisms": self.mechanisms}


class Inspect:
    """row-inspection budget AND the shared optional-discovery wall (checked every 4096 spends): either limit ends optional discovery."""
    def __init__(self, cap, deadline=None):
        self.cap = cap; self.used = 0; self.deadline = deadline; self._n = 0

    def spend(self, n=1):
        self.used += n; self._n += 1
        if self.used > self.cap:
            raise PlanStop("ROW_INSPECTION_CAP", "row inspection cap %d exhausted" % self.cap)
        if self.deadline is not None and (self._n & 4095) == 0 and time.monotonic() > self.deadline:
            raise PlanStop("DISCOVERY_WALL", "optional discovery wall exhausted")

    def remaining(self):
        return max(0, self.cap - self.used)


def plan(R, cfg, deadline=None):
    """Build the candidate programs under the frozen policy and rank them (cold work proxy, peak reserved bytes, candidate index). Returns the
    chosen Program and the candidate table. cfg: views / demand_masks / fusion flags; orders: ["original","min_fill","min_volume"] or ["min_volume"]."""
    scopes = [f.scope for f in R.factors if f.scope]; cands = []; table = []; inspect = Inspect(ROW_INSPECTION_CAP, deadline)
    for i, name in enumerate(cfg["orders"]):
        if deadline is not None and time.monotonic() > deadline:
            table.append({"candidate": i, "order": name, "state": "DISCOVERY_WALL_EXHAUSTED"}); continue
        order, info = {"original": order_original, "min_fill": order_min_fill, "min_volume": order_min_volume}[name](R.dom, scopes)
        if order is None:
            table.append({"candidate": i, "order": name, "state": "INCOMPLETE_METADATA_CAP", "info": info}); continue
        try:
            P = Program(R, order, info, cfg, inspect)                                            # mandatory: identity views, FULL demand, no fusion yet
            P.optional_discovery()                                                               # optional, capped: views / supports / demand, then pricing + fusion
            down = P.apply_memory_caps(CAPS); t = P.totals()
            cands.append((t["cold_work_proxy"], t["peak_reserved_bytes"], i, P)); table.append({"candidate": i, "order": name, "state": "COMPLETE", "totals": t, "downgrades": down, "discovery_stop": P.mechanisms.get("discovery_stop")})
        except PlanStop as ex:
            table.append({"candidate": i, "order": name, "state": "PLAN_STOP_" + ex.kind, "reason": ex.reason})
    if not cands:
        # the original-id order with FULL demand / identity views always exists (no optional discovery needed): rebuild it without optional scans
        order, info = order_original(R.dom, scopes); cfg2 = dict(cfg, views=False, demand_masks=False, fusion=False); P = Program(R, order, info, cfg2, Inspect(0)); P._price_and_choose(); P.apply_memory_caps(CAPS)
        table.append({"candidate": "fallback", "order": "original_id_identity_full", "state": "COMPLETE", "totals": P.totals()}); return P, table
    cands.sort(key=lambda c: (c[0], c[1], c[2])); return cands[0][3], table
