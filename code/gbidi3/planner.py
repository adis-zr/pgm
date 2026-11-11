"""Deterministic planner of GENERAL_BIDI_COMPLETE_V3 (brief §6-§12). UNTRUSTED: everything it emits is re-derived by gbidi3.validate against the
trusted snapshot before execution. It works on a proposal VIEW (plain tuples) and emits a gbidi3.ir.Program.

Structure. A region is a set of interior variables with an elimination order; the planner picks a CUTSET at the region's top (the LAST remaining
variable of the order, or the last TWO when their joint domain is <= 4,096: frozen local rule, tie toward one), splits the residual factor hypergraph
into connected components, and recurses. The regions are built from ONE bucket-elimination simulation along the order: the children of the bucket of x
(the buckets whose message is consumed at x) are exactly the connected components of the residual hypergraph after conditioning on x and the region's
boundary (a factor joining two sibling subtrees would place one subtree's variable in the other's bag, making it an ancestor, contradiction); so the
bucket tree IS the region tree and is compiled once per order, never per cutset assignment. The emitted node is REDUCE_D( MUL( MARKER(v) for v in D, SOURCE(f) for every factor fully inside D + boundary,
one child node per residual component ) ). With every component root DENSE this is exactly bucket elimination along the order (the bucket program is
one candidate); a STREAM component root is recursive conditioning (recomputed per cutset assignment); mixtures are chosen under the memory caps. Topology
is compiled once per region (nodes), never per cutset assignment.

Mechanisms (independently switchable, brief §7): V response views (classes of a boundary axis whose rows are proportional in EVERY operand: the REDUCE
stores representatives, the consumer expands through GATHER(cls, ratio); joint key = common REFINEMENT of the operand partitions); D1/D2 demand masks
(a DENSE node stores only the core entries some supported consumer row reads; supports from source zeros joined over the consumer's bag rows under the
row cap; UNKNOWN = FULL); D3 fusion (merge a message REDUCE into its consumer's REDUCE when the whole-path price, forward + reverse + regeneration, is lower
under the consumer's support/demand; recorded FUSION_PRICE; distinct from the TWO_AXIS cutset rule which is a cold-volume comparison). Storage per node:
DENSE (blocks), SPARSE (REDUCE(MUL) with a zero-bearing operand when the join price is lower), STREAM (recompute), CACHE (stream + bounded LRU for repeated
reads). Memory caps: nodes are downgraded DENSE/SPARSE -> STREAM/CACHE, largest first, until the reserved peak fits; roots stay stored.

Cost (brief §12): lexicographic (cold complete-work proxy, peak reserved bytes, stable candidate id). One source-entry inspection, gather, scalar add /
multiply and output-coordinate update each count one unit; STREAM children are priced with ZERO memo hits (child cost x parent reads); the reverse pass
is priced as prefix/suffix + scatter per row; ideal-reuse counts are reported separately. These are ranking proxies, not time predictions."""
from __future__ import annotations
import itertools, copy
from fractions import Fraction as Fr
import numpy as np
from gbidi3 import ir as IR
from gbidi3.clock import Clock, PlanStop, TWO_AXIS_JOINT_MAX, MAX_DEMAND_PASSES, BLOCK_ENTRIES
from gbidi3 import orders as ORD
from gbidi3.memory import CAPS

COMMON_RULES = ("exclude", "constants", "separate", "alias", "quotient")      # shared by GENERAL and PLAIN (adp.source, pinned)
ARMS = {
    "GENERAL_BIDI_COMPLETE_V3": {"views": True, "demand_masks": True, "fusion": True, "general_planner": True, "two_axis": True, "orders": ("original_id", "min_volume", "min_fill")},
    "NATIVE_PLAIN_COMPLETE_V3": {"views": False, "demand_masks": False, "fusion": False, "general_planner": False, "two_axis": False, "orders": ("min_volume",)},
    "A1_NO_DEMAND_MASKS": {"views": True, "demand_masks": False, "fusion": True, "general_planner": True, "two_axis": True, "orders": ("original_id", "min_volume", "min_fill")},
    "A2_NO_FUSION": {"views": True, "demand_masks": True, "fusion": False, "general_planner": True, "two_axis": True, "orders": ("original_id", "min_volume", "min_fill")},
    "A3_NO_RESPONSE_VIEWS": {"views": False, "demand_masks": True, "fusion": True, "general_planner": True, "two_axis": True, "orders": ("original_id", "min_volume", "min_fill")},
}
PLANNER_CONSTANTS = {"TWO_AXIS_JOINT_MAX": TWO_AXIS_JOINT_MAX, "BLOCK_ENTRIES": BLOCK_ENTRIES, "MAX_DEMAND_PASSES": MAX_DEMAND_PASSES, "SPARSE_STORAGE_RULE": "SPARSE iff the SPARSE_DRIVER_POLICY minimum (support x free-axis volume over every SOURCE operand and complete sparse child) < stored (demand-restricted) entries x eliminated volume; ties DENSE; no density threshold (the delivered 1/4 .. 3/4 zero-fraction gate is withdrawn, fourth review A)", "CACHE_WHEN_READS_EXCEED_VOLUME": True, "ROW_INSPECTION_CAP": 1_000_000, "METADATA_UPDATE_CAP": 3_000_000}


def prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


# ---------------------------------------------------------------------------------------------------------------- intermediate (mutable) plan
class Bucket:
    """one region node before emission: eliminated variables, owned factors, child buckets, boundary scope"""
    __slots__ = ("bid", "elim", "fids", "children", "scope", "card", "storage", "demand", "views", "support", "bag_support", "support_prov", "demand_prov", "prov", "consumer", "cost", "reads", "stored", "two_axis", "fused_from", "sparse_rows", "sparse_joined", "sparse_driver", "raw_scope_card", "core_card", "notes")

    def __init__(self, bid, elim, fids, children, scope, card):
        self.bid = bid; self.elim = list(elim); self.fids = list(fids); self.children = list(children); self.scope = tuple(scope); self.card = tuple(card); self.raw_scope_card = tuple(card); self.core_card = tuple(card)
        self.storage = IR.DENSE; self.demand = "FULL"; self.views = {}; self.support = None; self.bag_support = None; self.support_prov = "NOT_COMPUTED"; self.demand_prov = "FULL"; self.prov = {}; self.consumer = None; self.cost = None; self.reads = 1; self.stored = None; self.two_axis = False; self.fused_from = []; self.sparse_rows = None; self.sparse_joined = None; self.sparse_driver = -1; self.notes = []

    def volume(self):
        return prod(self.core_card)

    def clone(self):
        """shallow structural copy (lists / dicts / provenance copied; supports shared read-only); consumer / children links remapped by Plan.clone"""
        b = Bucket(self.bid, self.elim, self.fids, [], self.scope, self.card); b.raw_scope_card = self.raw_scope_card; b.core_card = self.core_card; b.storage = self.storage; b.demand = self.demand if isinstance(self.demand, str) else tuple(self.demand)
        b.views = dict(self.views); b.support = self.support; b.bag_support = self.bag_support; b.support_prov = self.support_prov; b.demand_prov = self.demand_prov; b.prov = dict(self.prov); b.cost = self.cost; b.reads = self.reads; b.stored = self.stored
        b.two_axis = self.two_axis; b.fused_from = list(self.fused_from); b.sparse_rows = self.sparse_rows; b.sparse_joined = self.sparse_joined; b.sparse_driver = self.sparse_driver; b.notes = list(self.notes); return b

    def elim_volume(self, dom):
        return prod(len(dom[v]) for v in self.elim)


class Plan:
    """the planner's result for one candidate order: buckets + emitted IR program + cost totals + mechanism record"""
    def __init__(self, order_name, order):
        self.order_name = order_name; self.order = list(order); self.buckets = []; self.roots = []; self.program = None; self.totals = {}; self.mechanisms = {"views": {"compressed_axes": 0, "checked_no_op": 0, "skipped": 0}, "demand": {"restricted_nodes": 0, "entries_saved": 0, "passes": 0, "skipped": 0}, "fusion": {"merged": 0, "declined": 0, "candidates": 0}, "two_axis": {"chosen": 0, "declined": 0, "ineligible": 0}, "sparse": {"nodes": 0}, "downgrades": {"to_stream": 0, "to_cache": 0}}
        self.discovery_stop = None; self.node_of_bucket = {}; self.notes = []; self.fusion_decisions = []; self.variant = "plain"; self.pos = {}; self.cutset_variant = "one_axis"

    def clone(self):
        """ITERATIVE copy of the plan (no recursion: a 50,000-bucket chain of consumer back-links overflows copy.deepcopy); the program is not copied (re-emitted)"""
        q = Plan(self.order_name, self.order); by = {}
        for b in self.buckets:
            c = b.clone(); by[b.bid] = c; q.buckets.append(c)
        for b in self.buckets:
            c = by[b.bid]; c.children = [by[k.bid] for k in b.children]; c.consumer = by[b.consumer.bid] if b.consumer is not None else None
        q.roots = [by[r.bid] for r in self.roots]; q.mechanisms = copy.deepcopy(self.mechanisms); q.discovery_stop = copy.deepcopy(self.discovery_stop); q.notes = list(self.notes); q.fusion_decisions = [dict(d) for d in self.fusion_decisions]; q.variant = self.variant; q.pos = dict(self.pos); q.cutset_variant = self.cutset_variant; return q


# ---------------------------------------------------------------------------------------------------------------- bucket / region construction
def _components(vars_set, scopes):
    """connected components of the hypergraph (vars, scopes restricted to vars); returns list of (set of vars, list of scope indices)"""
    parent = {v: v for v in vars_set}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for sc in scopes:
        vs = [v for v in sc if v in parent]
        for i in range(1, len(vs)):
            a, b = find(vs[0]), find(vs[i])
            if a != b:
                parent[max(a, b)] = min(a, b)
    comps = {}
    for v in vars_set:
        comps.setdefault(find(v), set()).add(v)
    return [comps[k] for k in sorted(comps)]


class Builder:
    def __init__(self, view, cfg, clock, ledger=None):
        self.ledger = ledger
        self.dom = view["dom"]; self.factors = {f[0]: f for f in view["factors"]}; self.scale = view["scale"]; self.cfg = cfg; self.clock = clock; self.next_bid = 0
        self.fscope = {fid: tuple(f[1]) for fid, f in self.factors.items()}; self.fcard = {fid: tuple(f[2]) for fid, f in self.factors.items()}; self.ftable = {fid: f[3] for fid, f in self.factors.items()}
        self._zero_rows = {}; self.sim = None; self.sim_updates = 0

    def simulate(self, order):
        """ONE bucket-elimination simulation along `order` (metadata only; indexed by variable so the cost is linear in the total scope size touched):
        sim[v] = (bag frozenset, operand count, bag volume, owned factor ids, child message ids); messages are indexed like factors."""
        index = {v: set() for v in self.dom}; scope_of = {}; owner_fids = {}
        for f in sorted(self.factors):
            sc = set(self.fscope[f])
            if sc:
                scope_of[("F", f)] = sc
                for v in sc:
                    index[v].add(("F", f))
        sim = {}; msg_of = {}
        for v in order:
            items = sorted(index[v], key=str); bag = {v}; fids = []; kids = []
            for it in items:
                bag |= scope_of[it]
                (fids if it[0] == "F" else kids).append(it[1])
                for u in scope_of[it]:
                    if u != v:
                        index[u].discard(it)
                self.clock.tick(len(scope_of[it])); self.sim_updates += len(scope_of[it])
            index[v] = set(); msc = bag - {v}; mid = ("M", v); scope_of[mid] = msc
            for u in msc:
                index[u].add(mid)
            sim[v] = (frozenset(bag), len(items) + 1, prod(len(self.dom[u]) for u in bag), fids, kids); msg_of[v] = msc; self.clock.tick(1); self.sim_updates += 1
        self.sim = sim; return sim

    def build(self, order, plan):
        """bucket tree along `order` (children = the buckets whose message is consumed here; they are exactly the connected components of the residual
        hypergraph after conditioning on this bucket's variable, see the module docstring). CONDITIONING ORDER POLICY (global, amendment 5): the region
        tree conditions on variables in the REVERSE of the elimination order -- the last eliminated variable is the outermost cutset, its bucket's children
        are the residual components, recursively; the cutset of a region is therefore its top bucket's eliminated variable(s), never chosen per case.
        Then the frozen two-axis cutset rule applied top-down
        (iteratively): the LAST child in the order of a region may be merged into the region's top bucket when their joint domain is <= 4,096 and the
        cold estimate (two top buckets separately vs the joint bucket) favours it. Returns the root buckets."""
        self.simulate(order); pos = {v: i for i, v in enumerate(order)}; bucket_of = {}
        for v in order:
            bag, ops, vol, fids, kids = self.sim[v]; scope = tuple(sorted(bag - {v})); card = tuple(len(self.dom[u]) for u in scope)
            children = [bucket_of[u] for u in sorted(kids, key=lambda u: pos[u])]
            b = self._new_bucket([v], fids, children, scope, card, plan); b.prov["cutset"] = "ONE_AXIS"; bucket_of[v] = b
        roots = [bucket_of[v] for v in order if not (self.sim[v][0] - {v})]
        for f in sorted(self.factors):                                                        # scope-free factors (rules = []): one scalar root bucket each
            if not self.fscope[f]:
                roots.append(self._new_bucket([], [f], [], (), (), plan))
        plan.pos = pos; return roots

    def apply_two_axis(self, plan):
        """the frozen two-axis cutset rule applied top-down to a one-axis tree (the LOCAL eligibility / cold pre-estimate of brief section 10). The result is
        a SEPARATE complete candidate: plan() keeps the one-axis tree too, runs the same discovery / storage on both and ranks them by the ONE whole-path
        cost (review F3): the local pre-estimate never discards the cheaper complete representation."""
        pos = plan.pos; roots = plan.roots
        if True:
            stack = list(roots)
            while stack:
                b = stack.pop(); self.clock.tick(1)
                if b.children and len(b.elim) == 1:
                    y_b = max(b.children, key=lambda c: pos[c.elim[-1]]); x = b.elim[0]; y = y_b.elim[-1]
                    if len(y_b.elim) == 1 and len(self.dom[x]) * len(self.dom[y]) <= TWO_AXIS_JOINT_MAX:
                        bx, ox, vx, _, _ = self.sim[x]; by, oy, vy, _, _ = self.sim[y]; joint = bx | by; vj = prod(len(self.dom[u]) for u in joint)
                        w1, m1 = vx * ox + vy * oy, prod(len(self.dom[u]) for u in bx - {x}) + prod(len(self.dom[u]) for u in by - {y})
                        w2, m2 = vj * (ox + oy - 1), prod(len(self.dom[u]) for u in joint - {x, y}); self.clock.tick(2)
                        if (w2, m2) < (w1, m1):
                            b.elim = [y, x]; b.fids = list(y_b.fids) + list(b.fids); b.children = [c for c in b.children if c is not y_b] + list(y_b.children)
                            for c in y_b.children:
                                c.consumer = b
                            b.scope = tuple(sorted(joint - {x, y})); b.card = tuple(len(self.dom[u]) for u in b.scope); b.raw_scope_card = b.card; b.core_card = b.card
                            b.prov["cutset"] = "TWO_AXIS_POLICY"; b.two_axis = True; plan.buckets.remove(y_b); plan.mechanisms["two_axis"]["chosen"] += 1
                        else:
                            plan.mechanisms["two_axis"]["declined"] += 1
                    elif len(y_b.elim) == 1:
                        plan.mechanisms["two_axis"]["ineligible"] += 1
                stack.extend(b.children)
        return plan.mechanisms["two_axis"]["chosen"]

    def _new_bucket(self, elim, fids, children, scope, card, plan):
        b = Bucket(self.next_bid, elim, fids, children, scope, card); self.next_bid += 1; plan.buckets.append(b)
        for c in children:
            c.consumer = b
        return b

    # ------------------------------------------------------------------ zero rows of a source along an axis (exact; cached)
    def _reserve(self, nbytes, what):
        if self.ledger is not None:
            self.ledger.reserve("source_ir_maps_output", nbytes, what)

    def _rows_zero(self, fid, k):
        key = (fid, k); z = self._zero_rows.get(key)
        if z is None:
            rows = self._rows_along(fid, k); z = [all(x == 0 for x in r) for r in rows]; self._zero_rows[key] = z
        return z

    def _rows_along(self, fid, k):
        """rows_along(fid, k)[a] = the table entries with axis k at position a, in the flat order of the other axes: ONE strided traversal of the table
        (each entry visited once), rows reserved BEFORE they are built, the optional clock charged per entry and polled every POLL_UNITS (review E6)"""
        tab = self.ftable[fid]; card = self.fcard[fid]; n = len(tab); st = [1] * len(card); acc = 1
        for j in range(len(card) - 1, -1, -1):
            st[j] = acc; acc *= card[j]
        self._reserve(8 * n + 72 * card[k] + 64, "response rows of factor %s axis %d" % (fid, k))
        self.clock.spend_rows(n)
        stride = st[k]; block = stride * card[k]; rows = [[] for _ in range(card[k])]
        i = 0
        while i < n:                                                                    # walk the table in (outer, a, inner) order: inner = stride entries per row of state a
            base = i
            for a in range(card[k]):
                rows[a].extend(tab[base + a * stride: base + (a + 1) * stride])
            i += block; self.clock.tick(block, optional=True)
        return [tuple(r) for r in rows]

    # ------------------------------------------------------------------ V: response views (classes of a boundary axis)
    def views_pass(self, plan, only=None):
        """for every bucket (children before parents) and every boundary axis: classes of raw states whose rows are proportional in EVERY operand containing
        the axis; recorded as (reps, cls, ratio) with ratio[a] = product of operand ratios. All axes of a bucket are computed, then committed atomically."""
        for b in sorted(plan.buckets, key=lambda q: q.bid):          # children are created BEFORE their parent in the region recursion: ascending bid = children first
            if only is not None and b not in only:
                continue
            self.clock.check_optional(); views = {}
            for k, w in enumerate(b.scope):
                n = len(self.dom[w]); sigs = [[] for _ in range(n)]; ratio = [Fr(1)] * n; zero = [False] * n; ok = True; ops = 0
                for f in b.fids:
                    if w in self.fscope[f]:
                        kk = self.fscope[f].index(w); rows = self._rows_along(f, kk); ops += 1
                        groups = {}; self._reserve(8 * len(self.ftable[f]) + 160 * len(rows), "row signatures of factor %s axis %d" % (f, w))
                        for a, row in enumerate(rows):
                            piv = next((z for z in row if z != 0), None); self.clock.tick(len(row), optional=True)
                            if piv is None:
                                zero[a] = True; sigs[a].append(("Z",)); continue
                            key = tuple(z / piv for z in row); rep, base = groups.setdefault(key, (a, piv)); sigs[a].append(("R", rep)); ratio[a] *= piv / base
                for c in b.children:
                    if w in c.scope:
                        ops += 1
                        cv = c.views.get(w)
                        if cv is None:
                            ok = False; break                           # an uncompressed child axis separates every state
                        reps_c, cls_c, ratio_c = cv
                        for a in range(n):
                            sigs[a].append(("C", cls_c[a])); ratio[a] *= Fr(ratio_c[a]) / Fr(ratio_c[reps_c[cls_c[a]]])
                if not ok or ops == 0:
                    continue
                classes = {}
                for a in range(n):
                    if zero[a]:
                        classes.setdefault(("ZERO",), []).append(a)
                    else:
                        classes.setdefault(tuple(sigs[a]), []).append(a)
                if len(classes) == n:
                    plan.mechanisms["views"]["checked_no_op"] += 1; continue
                reps = []; cls = [0] * n; rat = [Fr(0)] * n
                for mem in sorted(classes.values(), key=lambda m: m[0]):
                    r = mem[0]; ci = len(reps); reps.append(r)
                    for a in mem:
                        cls[a] = ci; rat[a] = Fr(1) if zero[a] else ratio[a] / ratio[r]
                views[w] = (tuple(reps), tuple(cls), tuple(rat))
            if views:
                b.views = views; b.core_card = tuple(len(views[w][0]) if w in views else len(self.dom[w]) for w in b.scope); plan.mechanisms["views"]["compressed_axes"] += len(views); b.prov["views"] = "COMPRESSED"
            else:
                b.prov["views"] = "CHECKED_NO_OP" if b.scope else "SCALAR"

    # ------------------------------------------------------------------ R2 / D1 / D2: supports and demand (exact zero joins under the row cap)
    def _operand_supports(self, b):
        """per operand of the bucket's MUL: (axes in bucket bag order, boolean numpy array over those axes) or None (FULL / UNKNOWN)"""
        bag = list(b.elim) + list(b.scope); pos = {v: i for i, v in enumerate(bag)}; out = []
        for f in b.fids:
            tab = self.ftable[f]; self._reserve(len(tab) + 112, "support mask of factor %s" % f); self.clock.spend_rows(len(tab)); arr = np.array([x != 0 for x in tab], dtype=bool).reshape(self.fcard[f]); out.append((tuple(pos[v] for v in self.fscope[f]), arr))
        for c in b.children:
            if c.support is not None:
                out.append((tuple(pos[v] for v in c.scope), c.support))
            else:
                out.append(None)
        return bag, out

    def support_pass(self, plan):
        """conservative support of every bucket (children first): bag_support over (elim + scope) = AND of the operand supports (source zeros; children's
        supports; an UNKNOWN operand contributes all-true), support over the RAW scope = OR over the eliminated axes. Capped -> UNKNOWN (None)."""
        for b in sorted(plan.buckets, key=lambda q: q.bid):          # children first
            self.clock.check_optional(); bag = list(b.elim) + list(b.scope); bag_vol = prod(len(self.dom[v]) for v in bag)
            if bag_vol > self.clock.remaining_rows():
                b.support = None; b.bag_support = None; b.support_prov = "SKIPPED_ROW_CAP"; plan.mechanisms["demand"]["skipped"] += 1; continue
            self._reserve(bag_vol + 112, "bag support of bucket %d" % b.bid)
            bag, ops = self._operand_supports(b); shape = tuple(len(self.dom[v]) for v in bag); sup = np.ones(shape, dtype=bool); unknown = 0
            for o in ops:
                if o is None:
                    unknown += 1; continue
                axes, arr = o; order_idx = np.argsort(axes); view = np.transpose(arr, order_idx); sorted_axes = sorted(axes)
                sh = [shape[i] if i in sorted_axes else 1 for i in range(len(shape))]; sup &= view.reshape(sh)
            self.clock.spend_rows(bag_vol); nel = len(b.elim)
            b.bag_support = sup; proj = sup.any(axis=tuple(range(nel))) if nel else sup
            b.support = np.ascontiguousarray(proj) if b.scope else proj.reshape(()); b.support_prov = "EXACT_JOIN_OF_KNOWN_OPERAND_SUPPORTS" + ("_%d_UNKNOWN_OPERANDS" % unknown if unknown else "")

    def demand_pass(self, plan):
        """DENSE storage demand (core indices) of every non-root bucket = union over consumers of the core indices read by supported consumer rows;
        uses the consumer's support (over its raw bag) when known; otherwise FULL. Runs at most MAX_DEMAND_PASSES times (monotone)."""
        passes = 0
        while passes < MAX_DEMAND_PASSES:
            passes += 1; changed = False
            for b in sorted(plan.buckets, key=lambda q: -q.bid):             # parents first: a restricted consumer restricts its children in the same pass
                self.clock.check_optional()
                if b.consumer is None:
                    b.demand = "FULL"; b.demand_prov = "ROOT_FULL"; continue
                p = b.consumer
                if p.bag_support is None and p.demand == "FULL":
                    b.demand_prov = "FULL_CONSUMER_SUPPORT_UNKNOWN"; continue
                bag = list(p.elim) + list(p.scope); bag_card = tuple(len(self.dom[v]) for v in bag); bag_vol = prod(bag_card)
                if bag_vol > self.clock.remaining_rows():
                    b.demand_prov = "SKIPPED_ROW_CAP"; plan.mechanisms["demand"]["skipped"] += 1; continue
                self._reserve(bag_vol * (8 * len(bag_card) + 10) + 256, "demand digits of bucket %d" % b.bid)
                rows = p.bag_support.reshape(bag_vol) if p.bag_support is not None else np.ones(bag_vol, dtype=bool)
                if p.demand != "FULL":
                    # only consumer rows whose OWN core output index is demanded by its consumer
                    keep = np.zeros(bag_vol, dtype=bool); idx_all = np.arange(bag_vol); dig = _digits_array(idx_all, bag_card)
                    out_core = _core_index(dig, bag, p.scope, p.views, self.dom); keep[np.isin(out_core, np.array(list(p.demand) if p.demand != "EMPTY" else [], dtype=np.int64))] = True; rows = rows & keep
                self.clock.spend_rows(bag_vol)
                idx = np.nonzero(rows)[0]
                if len(idx) == bag_vol and b.demand == "FULL" and b.demand_prov != "FULL":
                    b.demand_prov = "FULL"; continue
                dig = _digits_array(idx, bag_card); core = _core_index(dig, bag, b.scope, b.views, self.dom)
                dem = np.unique(core); vol = b.volume()
                if len(dem) >= vol:
                    if b.demand != "FULL":
                        pass
                    b.demand_prov = "CHECKED_NO_OP"; continue
                new = tuple(int(x) for x in dem)
                if b.demand == "FULL" or (b.demand != "EMPTY" and set(new) < set(b.demand)):
                    b.demand = new if new else "EMPTY"; b.demand_prov = "RESTRICTED"; changed = True
            plan.mechanisms["demand"]["passes"] = passes
            if not changed:
                break
        for b in plan.buckets:
            if b.demand not in ("FULL", "EMPTY"):
                plan.mechanisms["demand"]["restricted_nodes"] += 1; plan.mechanisms["demand"]["entries_saved"] += b.volume() - len(b.demand)

    # ------------------------------------------------------------------ D3: fusion (merge a message into its consumer) by whole-path price
    def fusion_pass(self, plan, bytes_per_entry, caps):
        """D3: merge a message bucket into its consumer when the ONE whole-path cost of the whole plan (totals(): forward + reverse rows x per-row work,
        every visited tuple incl. rejected zero rows, under the storage decisions the caps allow) strictly decreases (review D1-D2). Each merge is applied
        tentatively and REVERTED when not cheaper; the unfused complete plan is retained by plan() as a separate candidate."""
        merged_set = set()
        for b in list(plan.buckets):
            p = b.consumer
            if p is None or b not in p.children:
                continue
            self.clock.check_optional(); plan.mechanisms["fusion"]["candidates"] += 1
            before = _whole_path_cost(self, plan, bytes_per_entry, caps)
            undo = self._merge(b, p, plan)
            after = _whole_path_cost(self, plan, bytes_per_entry, caps)
            cheaper = after["cold_work_proxy"] is not None and before["cold_work_proxy"] is not None and after["cold_work_proxy"] < before["cold_work_proxy"]   # UNKNOWN on either side: keep the unfused (declared rule)
            plan.fusion_decisions.append({"child": b.bid, "consumer": p.bid, "cost_unfused": before["cold_work_proxy"], "cost_fused": after["cold_work_proxy"], "merged": cheaper})
            if cheaper:
                p.prov["fusion"] = "FUSION_WHOLE_PATH_COST"; plan.mechanisms["fusion"]["merged"] += 1; merged_set.add(p)
            else:
                undo(); plan.mechanisms["fusion"]["declined"] += 1
        return merged_set

    def _merge(self, b, p, plan):
        """merge bucket b into its consumer p; returns an undo closure restoring every mutated field"""
        saved = {"p_elim": list(p.elim), "p_fids": list(p.fids), "p_children": list(p.children), "p_views": dict(p.views), "p_core": p.core_card, "p_support": p.support, "p_bag": p.bag_support, "p_sprov": p.support_prov, "p_demand": p.demand, "p_dprov": p.demand_prov, "p_fused": list(p.fused_from), "p_prov": dict(p.prov), "kids": [(c, c.demand, c.demand_prov) for c in p.children + b.children], "idx": plan.buckets.index(b)}
        p.elim = list(b.elim) + list(p.elim); p.fids = list(b.fids) + list(p.fids); p.children = [c for c in p.children if c is not b] + list(b.children)
        for c in b.children:
            c.consumer = p
        p.fused_from.append(b.bid); plan.buckets.remove(b)
        p.views = {}; p.core_card = p.raw_scope_card; p.support = None; p.bag_support = None; p.support_prov = "RECOMPUTE_AFTER_FUSION"; p.demand = "FULL"; p.demand_prov = "FULL_AFTER_FUSION"
        for c in p.children:
            c.demand = "FULL"; c.demand_prov = "FULL_AFTER_FUSION"
        def undo():
            p.elim = saved["p_elim"]; p.fids = saved["p_fids"]; p.children = saved["p_children"]; p.views = saved["p_views"]; p.core_card = saved["p_core"]; p.support = saved["p_support"]; p.bag_support = saved["p_bag"]; p.support_prov = saved["p_sprov"]; p.demand = saved["p_demand"]; p.demand_prov = saved["p_dprov"]; p.fused_from = saved["p_fused"]; p.prov = saved["p_prov"]
            for c in b.children:
                c.consumer = b
            for c, d, dp in saved["kids"]:
                c.demand = d; c.demand_prov = dp
            plan.buckets.insert(saved["idx"], b)
        return undo

    # ------------------------------------------------------------------ ONE sparse-driver contract (gbidi3.ir.SPARSE_DRIVER_POLICY) priced by the planner, written into the emitted REDUCE, executed by the kernel
    def _sparse_choice(self, b):
        """(operand index, joined rows, support, label) of the cheapest sparse driver of bucket b in EMITTED operand order [sources..., markers..., children...], or None.
        Candidates: every SOURCE operand (support = nonzero entries; a fully positive source is a candidate too) and every child bucket that is itself SPARSE
        (support = its planned retained rows, an ESTIMATE the kernel replaces by the exact count); cost = support x volume of the bag axes the candidate leaves
        free = the joined rows the kernel will visit, rejected zero products included; minimal cost, ties -> lowest operand index. A viewed child is wrapped in a
        GATHER at emission and is therefore not a candidate (the kernel sees a GATHER operand)."""
        bag = list(b.elim) + list(b.scope); best = None
        for i, f in enumerate(b.fids):
            nz = sum(1 for x in self.ftable[f] if x != 0); free = prod(len(self.dom[v]) for v in bag if v not in self.fscope[f]); cost = nz * free
            if best is None or cost < best[1]:
                best = (i, cost, nz, "SOURCE %s (support %d x free %d)" % (f, nz, free))
        base = len(b.fids) + len(b.elim)
        for j, c in enumerate(b.children):
            if c.storage == IR.SPARSE and not c.views and c.sparse_rows is not None:
                free = prod(len(self.dom[v]) for v in bag if v not in c.scope); cost = c.sparse_rows * free
                if best is None or cost < best[1]:
                    best = (base + j, cost, c.sparse_rows, "SPARSE child bucket %d (planned rows %d x free %d)" % (c.bid, c.sparse_rows, free))
        return best

    # ------------------------------------------------------------------ storage decisions under the caps
    def storage_pass(self, plan, bytes_per_entry, caps):
        """storage decision of every bucket from scratch (idempotent; re-run by the whole-path cost evaluation after every tentative rewrite)"""
        value_cap = caps["value_cache_blocks"]; index_cap = caps["source_ir_maps_output"] // 2
        plan.mechanisms["sparse"]["nodes"] = 0; plan.mechanisms["downgrades"] = {"to_stream": 0, "to_cache": 0}
        for b in plan.buckets:
            b.stored = b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand))
            b.storage = IR.DENSE; b.sparse_rows = None; b.sparse_joined = None; b.sparse_driver = -1; b.prov.pop("storage", None); b.prov.pop("sparse_driver", None)
            # SPARSE candidate: REDUCE(MUL) without compressed axes whose cheapest driver under SPARSE_DRIVER_POLICY visits fewer rows than the DENSE alternative
            if not b.views and (b.fids or any(c.storage == IR.SPARSE for c in b.children)):
                ch = self._sparse_choice(b)
                if ch is not None:
                    drv, joined, supp, label = ch; dense_rows = b.stored * b.elim_volume(self.dom)   # the DENSE alternative visits stored (demand-restricted) entries x eliminated volume
                    if joined < dense_rows:
                        b.storage = IR.SPARSE; b.sparse_rows = min(b.volume(), joined); b.sparse_joined = joined; b.sparse_driver = drv; plan.mechanisms["sparse"]["nodes"] += 1; b.prov["storage"] = "SPARSE_JOIN_PRICE"; b.prov["sparse_driver"] = label
        # memory: downgrade the largest non-root stored buckets until the reserved peak fits
        def reserved():
            tot = 0
            for b in plan.buckets:
                if b.storage == IR.DENSE:
                    tot += b.stored * bytes_per_entry + 24 * ((b.stored + BLOCK_ENTRIES - 1) // BLOCK_ENTRIES)    # the kernel reserves bl * bytes + sizeof(std::vector) per block (materialize_dense)
                elif b.storage == IR.SPARSE:
                    tot += (b.sparse_rows or b.volume()) * (bytes_per_entry + 56)
            return tot
        while reserved() > value_cap:
            cands = [b for b in plan.buckets if b.consumer is not None and b.storage in (IR.DENSE, IR.SPARSE)] or [b for b in plan.buckets if b.storage in (IR.DENSE, IR.SPARSE)]   # non-roots first; then roots (a scalar root block that does not fit is streamed by the PLAN, not left to a kernel downgrade)
            if not cands:
                break
            b = max(cands, key=lambda q: (q.stored * bytes_per_entry if q.storage == IR.DENSE else (q.sparse_rows or q.volume()) * (bytes_per_entry + 56), -q.bid))
            was_sparse = b.storage == IR.SPARSE; b.storage = IR.STREAM; b.sparse_driver = -1; b.prov["storage"] = "DOWNGRADED_TO_STREAM_MEMORY"; plan.mechanisms["downgrades"]["to_stream"] += 1
            p = b.consumer
            if was_sparse and p is not None and p.storage == IR.SPARSE:                        # the consumer may have planned THIS child as its driver: re-run the policy on the remaining candidates (the plan never leaves a dangling driver)
                ch = self._sparse_choice(p)
                if ch is not None and ch[1] < p.stored * p.elim_volume(self.dom):
                    p.sparse_driver, p.sparse_joined, _, p.prov["sparse_driver"] = ch[0], ch[1], ch[2], ch[3]; p.sparse_rows = min(p.volume(), ch[1])
                else:
                    p.storage = IR.DENSE; p.sparse_rows = None; p.sparse_joined = None; p.sparse_driver = -1; p.prov["storage"] = "DENSE_AFTER_CHILD_DOWNGRADE"; plan.mechanisms["sparse"]["nodes"] -= 1
        # CACHE for streamed buckets that are read more often than their volume (bounded reuse: the LRU holds at most half of the remaining value category)
        _compute_reads(self, plan)
        for b in plan.buckets:
            if b.storage == IR.STREAM and b.reads > b.volume():
                b.storage = IR.CACHE; plan.mechanisms["downgrades"]["to_cache"] += 1; b.prov["storage"] = "STREAM_WITH_LRU"


def _digits_array(idx, card):
    d = np.empty((len(idx), len(card)), dtype=np.int64); x = idx.copy()
    for k in range(len(card) - 1, -1, -1):
        d[:, k] = x % card[k]; x //= card[k]
    return d


def _core_index(dig, bag, scope, views, dom):
    """core index of the node (scope, views) read by consumer bag rows `dig` (digits over bag)"""
    pos = {v: i for i, v in enumerate(bag)}; core = np.zeros(dig.shape[0], dtype=np.int64)
    for w in scope:
        raw = dig[:, pos[w]]
        if w in views:
            reps, cls, _ = views[w]; c = np.array(cls, dtype=np.int64)[raw]; n = len(reps)
        else:
            c = raw; n = len(dom[w])
        core = core * n + c
    return core


# ---------------------------------------------------------------------------------------------------------------- cost model
def _compute_reads(B, plan):
    """reads of each bucket = its consumer's evaluated rows (stored entries x eliminated volume for a materialized consumer; the consumer's own reads x its
    eliminated volume for a streamed consumer); roots are read once. Parents before children (descending bid)."""
    for b in plan.buckets:
        b.reads = 1
    for b in sorted(plan.buckets, key=lambda q: -q.bid):
        ev = b.elim_volume(B.dom); rows = _rows_of(b, ev)
        for c in b.children:
            c.reads = rows


def _rows_of(b, ev):
    """MUL rows the executor VISITS for bucket b in ONE forward VALUE evaluation of all its stored / requested indices (used by the CACHE decision and the
    forward prediction): DENSE = stored entries x eliminated volume; SPARSE = the JOINED rows (driver nonzeros x free volume, every visited row INCLUDING
    the ones rejected as zero products: kernel counter sparse_rows_joined); STREAM / CACHE = consumer reads x eliminated volume"""
    if b.storage == IR.DENSE:
        return (b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand))) * ev
    if b.storage == IR.SPARSE:
        return b.sparse_joined if b.sparse_joined is not None else b.volume() * ev
    return b.reads * ev


COUNT_BOUND = 1 << 62                    # count arithmetic beyond this is UNKNOWN (the candidate is ranked after every known one by a deterministic rule)


def _streamed(b):
    return b.storage in (IR.STREAM, IR.CACHE)                                            # cold: zero memo hits outside explicit retention (CACHE counts as STREAM)


def cold_recurrences(B, plan):
    """COMPOSITIONAL cold recurrences of the kernel's actual frame schedule (review F2 / B2). Frames at a bucket come in three modes: VALUE (mode 0),
    PULLBACK (mode 1) and combined VALUE+PULLBACK (mode 2). One frame at one output index of bucket b visits ev_b MUL rows (one per eliminated tuple).
    For each row, the kernel reads stored / leaf operands directly; a STREAMED child operand costs a nested frame per row:
      VALUE row      -> every streamed child gets a VALUE frame;
      PULLBACK row / combined row -> every streamed child but the LAST (operand order) gets a VALUE frame (its value is needed for the prefix / suffix
                        weights: the backward-phase VALUE RECONSTRUCTION) and then a PULLBACK frame; the last streamed child gets ONE combined frame.
    Frame multiplicities (number of frames of each mode at each bucket, forward and reverse separately) are propagated top-down from the entry points:
      forward: every stored entry of a materialized bucket is one VALUE frame; a streamed root is one VALUE frame (Z);
      reverse: a streamed root is one VALUE frame (the root value is recomputed) + one PULLBACK frame; every stored entry (DENSE) is drained by one
               PULLBACK frame; a SPARSE bucket's retained rows are drained through the support-indexed pullback (its joined nonzero rows, no tuple loop).
    rows(b, mode) = frames(b, mode) x ev_b (SPARSE: joined rows). Rows are the quantities the kernel counts (reduce_terms / reverse_value_terms /
    combined_terms / reverse_tuples / sparse_reverse_rows); ops weight them per row with the bucket's operand count k. Ideal reuse (every CACHE read a hit)
    is reported separately. Any count beyond COUNT_BOUND makes the proxy UNKNOWN (None)."""
    _compute_reads(B, plan)
    order = sorted(plan.buckets, key=lambda q: -q.bid)                                   # parents before children
    f0 = {b.bid: 0 for b in plan.buckets}; r0 = dict(f0); r1 = dict(f0); r2 = dict(f0)   # frame multiplicities: forward VALUE, reverse VALUE, reverse PULLBACK, reverse combined
    rows = {}
    for b in plan.buckets:
        ev = b.elim_volume(B.dom)
        if b.storage == IR.SPARSE:
            st = b.sparse_rows if b.sparse_rows is not None else b.volume(); rows[b.bid] = (st, b.sparse_joined if b.sparse_joined is not None else st * ev, ev)
        elif b.storage == IR.DENSE:
            st = b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand)); rows[b.bid] = (st, st * ev, ev)
        else:
            rows[b.bid] = (0, None, ev)
    # entry points
    for b in plan.buckets:
        st, _, ev = rows[b.bid]
        if b.storage in (IR.DENSE, IR.SPARSE):
            f0[b.bid] += 1 if b.storage == IR.SPARSE else st                            # SPARSE: one join (all outputs at once); DENSE: one VALUE frame per stored entry
            r1[b.bid] += st                                                               # every stored entry drained once (sparse: its retained rows through the support-indexed pull)
        if b.consumer is None and _streamed(b):
            f0[b.bid] += 1; r0[b.bid] += 1; r1[b.bid] += 1                              # streamed root: Z in forward, value recomputed in reverse, then its pullback
    def frame_rows(b, m, frames):
        st, joined, ev = rows[b.bid]
        if b.storage == IR.SPARSE:
            return joined if frames else 0                                                # the join visits its joined rows once (forward); the drain revisits the nonzero ones (bounded by joined)
        return frames * ev
    per = {}; unknown = False
    for b in order:
        # the EMITTED MUL operands are [sources..., markers..., children in order] (emit()); a child with a response view is wrapped in a STREAM GATHER, so the
        # kernel sees it as an UNRESOLVED operand even when its bucket is retained (third review P-R2): the "last unresolved operand" that receives the combined
        # frame is the last child that is streamed OR viewed; a retained viewed child's wrapper frames do lookups (no REDUCE rows at the child)
        S = [c for c in b.children if _streamed(c) or c.views]
        rf0 = frame_rows(b, 0, f0[b.bid]); rr0 = frame_rows(b, 0, r0[b.bid]); rr1 = frame_rows(b, 1, r1[b.bid]); rr2 = frame_rows(b, 2, r2[b.bid])
        if b.storage == IR.SPARSE:
            rr1 = min(rows[b.bid][1], rows[b.bid][1])                                      # support-indexed drain: at most the joined rows
        wrapper_rows = (rf0 + rr0 + rr1 + rr2) * sum(1 for c in b.children if c.views)             # GATHER wrapper visits (index + ratio work) per row per viewed child
        per[b.bid] = {"fwd_value_rows": rf0, "rev_value_rows": rr0, "rev_pull_rows": rr1, "rev_combined_rows": rr2, "k": _ops(b), "ev": rows[b.bid][2], "stored": rows[b.bid][0], "streamed": _streamed(b), "wrapper_rows": wrapper_rows}
        if any(x > COUNT_BOUND for x in (rf0, rr0, rr1, rr2)):
            unknown = True; rf0, rr0, rr1, rr2 = (min(x, COUNT_BOUND + 1) for x in (rf0, rr0, rr1, rr2))   # count arithmetic beyond the declared bound: the proxy is UNKNOWN (clamped, every bucket still recorded)
        # nested frames: VALUE rows -> VALUE frame per STREAMED child (a retained viewed child is a lookup through its wrapper); PULLBACK / combined rows -> VALUE +
        # PULLBACK for every unresolved operand but the last, combined for the last -- rows arise only at STREAMED children
        for c in S:
            if _streamed(c):
                f0[c.bid] += rf0; r0[c.bid] += rr0
        pull_rows = rr1 + rr2
        if S:
            for c in S[:-1]:
                if _streamed(c):
                    r0[c.bid] += pull_rows; r1[c.bid] += pull_rows
            if _streamed(S[-1]):
                r2[S[-1].bid] += pull_rows
    return (None if unknown else {"frames": {"f0": f0, "r0": r0, "r1": r1, "r2": r2}}), per


def _ops(b):
    return len(b.fids) + len(b.elim) + len(b.children)


def _whole_path_cost(B, plan, bytes_per_entry, caps):
    """the ONE cost used for rewrite decisions AND final ranking: storage decided under the caps, then totals() of the whole plan"""
    B.storage_pass(plan, bytes_per_entry, caps); return totals(B, plan, bytes_per_entry)


def totals(B, plan, bytes_per_entry):
    """the ONE whole-path cost proxy (units: primitive operations; a consistent conservative proxy, not predicted seconds) from the compositional cold
    recurrences (cold_recurrences): per bucket with k operands, VALUE rows x (2k + 1) [k reads / lookups + k multiplies + 1 accumulate], PULLBACK rows x
    (3k + 4) [k reads + 2k prefix / suffix multiplies + scatter + deliveries], combined rows x (3k + 5); backward-phase VALUE reconstruction rows are
    included as VALUE rows; materialization = stored entries x 2 + demand-list index entries x 2 + sparse index rows x 2 + sparse driver discovery (support scan of every
    SOURCE operand + the driver's row pass); construction = every source entry scanned once + 8 per bucket; publication = 4 per original state. Fusion decisions, the one-/two-axis comparison and the final ranking use this SAME
    number (reviews D2 / F3). `predicted` carries the row quantities the kernel counts. UNKNOWN (cold_work_proxy None) when a count exceeds COUNT_BOUND."""
    rec, per = cold_recurrences(B, plan); fwd = 0; rev = 0; ideal = 0; stored_entries = 0; mem = 0; mat = 0
    pred = {"forward_rows": 0, "reverse_value_rows": 0, "reverse_pull_rows": 0, "reverse_combined_rows": 0, "sparse_pull_rows": 0, "dense_entries": 0, "sparse_rows": 0, "sparse_joined": 0, "sparse_driver_scans": 0, "stream_rows": 0}
    construction = sum(len(B.ftable[f]) for f in B.factors) + 8 * len(plan.buckets)
    publication = 4 * sum(len(B.dom[v]) for v in B.dom) + 64
    for b in plan.buckets:
        q = per[b.bid]; k = q["k"]
        fwd += q["fwd_value_rows"] * (2 * k + 1); rev += q["rev_value_rows"] * (2 * k + 1) + q["rev_pull_rows"] * (3 * k + 4) + q["rev_combined_rows"] * (3 * k + 5) + 3 * q.get("wrapper_rows", 0)
        pred["forward_rows"] += q["fwd_value_rows"]; pred["reverse_value_rows"] += q["rev_value_rows"]; pred["reverse_combined_rows"] += q["rev_combined_rows"]
        if b.storage == IR.SPARSE:
            pred["sparse_pull_rows"] += q["rev_pull_rows"]
        else:
            pred["reverse_pull_rows"] += q["rev_pull_rows"]
        ideal += (q["stored"] if b.storage in (IR.DENSE, IR.SPARSE, IR.CACHE) else 0) * q["ev"] * (2 * k + 1)
        if b.storage == IR.DENSE:
            st = q["stored"]; stored_entries += st; mem += st * bytes_per_entry + (len(b.demand) * 48 if b.demand not in ("FULL", "EMPTY") else 0); mat += 2 * st + (2 * len(b.demand) if b.demand not in ("FULL", "EMPTY") else 0); pred["dense_entries"] += st
        elif b.storage == IR.SPARSE:
            st = q["stored"]; stored_entries += st; mem += st * (bytes_per_entry + 56) + (b.sparse_joined or st) * 8; mat += 4 * st + (b.sparse_joined or st); pred["sparse_rows"] += st; pred["sparse_joined"] += (b.sparse_joined or st)
            # driver discovery (fourth review A): the kernel scans EVERY SOURCE operand of the sparse MUL once for its support (sparse_driver_scans, counted as source reads), then
            # collects the driver's rows in a second pass over the driver (a SOURCE driver: its whole table, counted as source reads; a SPARSE child driver: its retained rows)
            scans = sum(len(B.ftable[f]) for f in b.fids); base = len(b.fids) + len(b.elim); drv = b.sparse_driver
            driver_pass = len(B.ftable[b.fids[drv]]) if 0 <= drv < len(b.fids) else ((b.children[drv - base].sparse_rows or 0) if drv >= base and drv - base < len(b.children) else 0)
            mat += scans + driver_pass; pred["sparse_driver_scans"] += scans
        else:
            pred["stream_rows"] += q["fwd_value_rows"]
    mem += sum(len(B.dom[v]) for v in B.dom) * bytes_per_entry
    cold = (fwd + rev + mat + construction + publication) if rec is not None else None
    if cold is not None and cold > COUNT_BOUND:
        cold = None
    return {"cold_work_proxy": cold, "forward_proxy": fwd, "reverse_proxy": rev, "materialization_proxy": mat, "predicted": pred, "construction_proxy": construction, "publication_proxy": publication, "ideal_reuse_proxy": ideal, "stored_entries": stored_entries, "peak_reserved_bytes_estimate": mem, "buckets": len(plan.buckets), "streamed": sum(1 for b in plan.buckets if _streamed(b)), "sparse": sum(1 for b in plan.buckets if b.storage == IR.SPARSE), "max_bucket_volume": max((b.volume() * b.elim_volume(B.dom) for b in plan.buckets), default=0),
            "cost_model": "compositional cold VALUE / PULLBACK / combined recurrences v3 over the EMITTED operand schedule (GATHER wrappers of viewed children are unresolved operands; reverse-phase value reconstruction included)",
            "assumptions": "CONDITIONAL exact row-class prediction: exact under no memo (cache) hits, no runtime downgrades, no early drains, pending slots fit, and the written sparse drivers executed (sparse_driver_deviation 0); exact-zero row skips can only reduce the visited rows below the prediction; a planned SPARSE child's support is an estimate (exact at run time; sparse_driver_policy_differs counts a run-time disagreement, the written driver is still executed). OUTSIDE these assumptions no upper bound is claimed: the deviations are counted by the kernel (downgrades, early_flushes, cache_hits, sparse_driver_deviation) and reported with the record. UNKNOWN when a count exceeds COUNT_BOUND", "unknown": cold is None}


# ---------------------------------------------------------------------------------------------------------------- emission to the IR
def emit(B, plan):
    """emit the IR program: buckets in ascending bid (children before parents, since a child is created before its consumer); no recursion"""
    P = IR.Program(); node_of = {}; src_nodes = {}; marker_nodes = {}
    def src(fid):
        if fid not in src_nodes:
            src_nodes[fid] = P.source(fid, B.fscope[fid], B.fcard[fid])
        return src_nodes[fid]
    def marker(v):
        if v not in marker_nodes:
            marker_nodes[v] = P.marker(v, len(B.dom[v]))
        return marker_nodes[v]
    for b in sorted(plan.buckets, key=lambda q: q.bid):
        ops = [src(f) for f in b.fids] + [marker(v) for v in b.elim]
        for c in b.children:
            cn = P.nodes[node_of[c.bid]]
            if c.views:
                gaxes = []
                for k, w in enumerate(cn.axes):
                    if w in c.views:
                        reps, cls, ratio = c.views[w]; gaxes.append({"out_pos": k, "cls": tuple(cls), "ratio": tuple(ratio)})
                    else:
                        gaxes.append({"out_pos": k})
                cn = P.gather(cn, cn.axes, tuple(len(B.dom[w]) for w in cn.axes), gaxes, prov={"expands": c.bid})
            ops.append(cn)
        if not ops:
            continue
        axes = list(b.elim) + list(b.scope); card = [len(B.dom[v]) for v in axes]
        m = P.mul(ops, axes=axes, card=card)
        reps = {w: v for w, v in b.views.items()} if b.views else None
        n = P.reduce(m, set(b.elim), reps=reps, storage=b.storage, demand=(b.demand if b.storage == IR.DENSE else "FULL"), driver=(b.sparse_driver if b.storage == IR.SPARSE else -1), prov=dict(b.prov, bucket=b.bid, support=b.support_prov, demand=(b.demand_prov if b.storage == IR.DENSE else "FULL_NON_DENSE_STORAGE"), two_axis=b.two_axis, fused_from=list(b.fused_from)))
        node_of[b.bid] = n.nid
    for r in plan.roots:
        if r.bid in node_of:
            P.roots.append(node_of[r.bid])
    plan.program = P; plan.node_of_bucket = node_of; return P


# ---------------------------------------------------------------------------------------------------------------- entry point
def plan(view, cfg, clock, bytes_per_entry, caps=None, ledger=None):
    """returns (chosen Plan, candidates record). view = TrustedReduced.proposal_view(); cfg = ARMS[arm]. Every candidate order yields a complete plan;
    when fusion merges, the UNFUSED complete plan is retained as a separate candidate so the final ranking (the same whole-path cost) can choose it."""
    caps = caps or CAPS; B = Builder(view, cfg, clock, ledger=ledger); dom = B.dom; scopes = [B.fscope[f] for f in sorted(B.factors)]
    if ledger is not None:
        ledger.reserve("source_ir_maps_output", 1024 * len(dom) + 64 * sum(len(B.fscope[f]) for f in B.factors) + 4096, "planner candidates (buckets, orders, adjacency)")
    cands = []; plans = []
    names = list(cfg["orders"]) if cfg["general_planner"] else ["min_volume"]
    orders = []
    for name in names:                                                         # construction priority: original-id (never capped) first, then min-volume, then min-fill
        try:
            o, info = ORD.ORDER_FN[name](dom, scopes, clock); orders.append((name, o, dict(info, state="COMPLETE")))
        except PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                raise
            orders.append((name, None, {"name": name, "state": "ORDER_INCOMPLETE_" + ex.kind, "reason": ex.reason}))
    if not any(o is not None for _, o, _ in orders):
        orders.append(("original_id", sorted(dom), {"name": "original_id", "state": "COMPLETE", "fallback": "original-order baseline after heuristic cap exhaustion"}))
    for idx, (name, order, info) in enumerate(orders):
        if order is None:
            cands.append({"candidate": idx, "order": name, "state": info.get("state"), "reason": info.get("reason")}); continue
        base = Plan(name, order); base.roots = B.build(order, base); alternatives = [base]
        if cfg["two_axis"]:
            if ledger is not None:
                ledger.reserve("source_ir_maps_output", 2048 * len(base.buckets) + 4096, "two-axis alternative plan (bucket copies; reserved BEFORE the copy)")
            two = base.clone(); two.cutset_variant = "two_axis"
            if B.apply_two_axis(two):
                alternatives.append(two)                                            # the one-axis tree STAYS a complete candidate; the two-axis tree is a second one
                m2 = two.mechanisms["two_axis"]; base.mechanisms["two_axis"] = {"chosen": 0, "declined": m2["chosen"] + m2["declined"], "ineligible": m2["ineligible"], "alternative_merges": m2["chosen"], "declined_by": "whole-path ranking of the complete one-axis and two-axis candidates"}
            else:
                base.mechanisms["two_axis"] = dict(two.mechanisms["two_axis"])      # nothing merged: record the declined / ineligible counts on the only candidate
        for pl in alternatives:
          unfused = None
          # optional discovery (one shared allowance; a stop keeps the conservative baseline)
          try:
              if cfg["views"]:
                  B.views_pass(pl)
              if cfg["demand_masks"] or cfg["fusion"]:
                  B.support_pass(pl)
              if cfg["demand_masks"]:
                  B.demand_pass(pl)
              if cfg["fusion"]:
                  if ledger is not None:
                      ledger.reserve("source_ir_maps_output", 2048 * len(pl.buckets) + 4096, "retained UNFUSED candidate plan (bucket copies; reserved BEFORE the copy)")
                  unfused = pl.clone()                                             # the complete UNFUSED plan is retained as its own candidate (iterative copy)
                  merged = B.fusion_pass(pl, bytes_per_entry, caps)
                  if merged:
                      if cfg["views"]:
                          B.views_pass(pl, only=merged)
                      B.support_pass(pl)
                      if cfg["demand_masks"]:
                          B.demand_pass(pl)
                      final = _whole_path_cost(B, pl, bytes_per_entry, caps); base = _whole_path_cost(B, unfused, bytes_per_entry, caps)
                      pl.fusion_decisions.append({"final": True, "cost_unfused": base["cold_work_proxy"], "cost_fused_after_rediscovery": final["cold_work_proxy"], "fused_is_cheaper": (final["cold_work_proxy"] is not None and base["cold_work_proxy"] is not None and final["cold_work_proxy"] < base["cold_work_proxy"]), "note": "the ranking below uses these SAME totals; the unfused plan is a retained candidate"})
                  else:
                      unfused = None
          except PlanStop as ex:
              if ex.kind == "CELL_DEADLINE":
                  raise
              pl.discovery_stop = {"kind": ex.kind, "reason": ex.reason}
          for variant, q in (("fused" if unfused is not None else "plain", pl),) + ((("unfused", unfused),) if unfused is not None else ()):
              variant = variant if pl.cutset_variant == "one_axis" else variant + "+two_axis"
              q.mechanisms["views"]["compressed_axes"] = sum(len(b.views) for b in q.buckets)
              B.storage_pass(q, bytes_per_entry, caps)
              try:
                  emit(B, q)
              except IR.IRError as ex:
                  cands.append({"candidate": idx, "order": name, "variant": variant, "state": "NOT_REPRESENTABLE", "reason": ex.reason, "order_info": info, "mechanisms": q.mechanisms, "discovery_stop": q.discovery_stop}); continue
              big = [n for n in q.program.nodes if n.volume > IR.INT64_MAX or (n.kind == IR.REDUCE and prod(q.program.nodes[n.children[0]].card) > IR.INT64_MAX)]
              if big:
                  cands.append({"candidate": idx, "order": name, "variant": variant, "state": "NOT_REPRESENTABLE", "reason": "node %d: volume exceeds int64 (symbolic domain too large for an indexed route)" % big[0].nid, "order_info": info, "mechanisms": q.mechanisms, "discovery_stop": q.discovery_stop}); continue
              q.totals = totals(B, q, bytes_per_entry); q.variant = variant
              plans.append(q); cands.append({"candidate": idx, "order": name, "variant": variant, "cutset": pl.cutset_variant, "state": "COMPLETE" if q.totals.get("cold_work_proxy") is not None else "COMPLETE_UNKNOWN_COST", "order_info": info, "simulation_updates": B.sim_updates, "totals": q.totals, "mechanisms": q.mechanisms, "fusion_decisions": q.fusion_decisions, "discovery_stop": q.discovery_stop})
    if not plans:
        raise PlanStop("NOT_REPRESENTABLE", "no complete representable candidate order: %s" % [(c.get("order"), c.get("state"), (c.get("reason") or "")[:80]) for c in cands])
    # ranking by the ONE whole-path cost; a candidate whose cost is UNKNOWN (count arithmetic beyond the declared bound) ranks after every known one; if every
    # cost is UNKNOWN the DETERMINISTIC rule is: first complete candidate in construction priority (original-id order, one-axis, unfused)
    def key(i):
        t = plans[i].totals; c = t.get("cold_work_proxy")
        return (1, 0, 0, i) if c is None else (0, c, t["peak_reserved_bytes_estimate"], i)
    best = min(range(len(plans)), key=key)
    k = 0
    for c in cands:
        if c.get("state") in ("COMPLETE", "COMPLETE_UNKNOWN_COST"):
            c["chosen"] = (k == best); k += 1
        else:
            c["chosen"] = False
    return plans[best], cands
