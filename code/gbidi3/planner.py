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
import itertools
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
PLANNER_CONSTANTS = {"TWO_AXIS_JOINT_MAX": TWO_AXIS_JOINT_MAX, "BLOCK_ENTRIES": BLOCK_ENTRIES, "MAX_DEMAND_PASSES": MAX_DEMAND_PASSES, "SPARSE_MIN_ZERO_FRACTION": "1/4", "CACHE_WHEN_READS_EXCEED_VOLUME": True, "ROW_INSPECTION_CAP": 1_000_000, "METADATA_UPDATE_CAP": 3_000_000}


def prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


# ---------------------------------------------------------------------------------------------------------------- intermediate (mutable) plan
class Bucket:
    """one region node before emission: eliminated variables, owned factors, child buckets, boundary scope"""
    __slots__ = ("bid", "elim", "fids", "children", "scope", "card", "storage", "demand", "views", "support", "bag_support", "support_prov", "demand_prov", "prov", "consumer", "cost", "reads", "stored", "two_axis", "fused_from", "sparse_rows", "raw_scope_card", "core_card", "notes")

    def __init__(self, bid, elim, fids, children, scope, card):
        self.bid = bid; self.elim = list(elim); self.fids = list(fids); self.children = list(children); self.scope = tuple(scope); self.card = tuple(card); self.raw_scope_card = tuple(card); self.core_card = tuple(card)
        self.storage = IR.DENSE; self.demand = "FULL"; self.views = {}; self.support = None; self.bag_support = None; self.support_prov = "NOT_COMPUTED"; self.demand_prov = "FULL"; self.prov = {}; self.consumer = None; self.cost = None; self.reads = 1; self.stored = None; self.two_axis = False; self.fused_from = []; self.sparse_rows = None; self.notes = []

    def volume(self):
        return prod(self.core_card)

    def elim_volume(self, dom):
        return prod(len(dom[v]) for v in self.elim)


class Plan:
    """the planner's result for one candidate order: buckets + emitted IR program + cost totals + mechanism record"""
    def __init__(self, order_name, order):
        self.order_name = order_name; self.order = list(order); self.buckets = []; self.roots = []; self.program = None; self.totals = {}; self.mechanisms = {"views": {"compressed_axes": 0, "checked_no_op": 0, "skipped": 0}, "demand": {"restricted_nodes": 0, "entries_saved": 0, "passes": 0, "skipped": 0}, "fusion": {"merged": 0, "declined": 0, "candidates": 0}, "two_axis": {"chosen": 0, "declined": 0, "ineligible": 0}, "sparse": {"nodes": 0}, "downgrades": {"to_stream": 0, "to_cache": 0}}
        self.discovery_stop = None; self.node_of_bucket = {}; self.notes = []


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
    def __init__(self, view, cfg, clock):
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
        hypergraph after conditioning on this bucket's variable, see the module docstring), then the frozen two-axis cutset rule applied top-down
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
        if self.cfg["two_axis"]:
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
        return roots

    def _new_bucket(self, elim, fids, children, scope, card, plan):
        b = Bucket(self.next_bid, elim, fids, children, scope, card); self.next_bid += 1; plan.buckets.append(b)
        for c in children:
            c.consumer = b
        return b

    # ------------------------------------------------------------------ zero rows of a source along an axis (exact; cached)
    def _rows_zero(self, fid, k):
        key = (fid, k); z = self._zero_rows.get(key)
        if z is None:
            tab = self.ftable[fid]; card = self.fcard[fid]; st = [1] * len(card); acc = 1
            for j in range(len(card) - 1, -1, -1):
                st[j] = acc; acc *= card[j]
            z = []
            for a in range(card[k]):
                z.append(all(tab[i] == 0 for i in range(len(tab)) if (i // st[k]) % card[k] == a))
            self._zero_rows[key] = z
        return z

    def _rows_along(self, fid, k):
        tab = self.ftable[fid]; card = self.fcard[fid]; st = [1] * len(card); acc = 1
        for j in range(len(card) - 1, -1, -1):
            st[j] = acc; acc *= card[j]
        return [tuple(tab[i] for i in range(len(tab)) if (i // st[k]) % card[k] == a) for a in range(card[k])]

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
                        kk = self.fscope[f].index(w); rows = self._rows_along(f, kk); self.clock.spend_rows(len(self.ftable[f])); ops += 1
                        groups = {}
                        for a, row in enumerate(rows):
                            piv = next((z for z in row if z != 0), None)
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
            tab = self.ftable[f]; arr = np.array([x != 0 for x in tab], dtype=bool).reshape(self.fcard[f]); self.clock.spend_rows(len(tab)); out.append((tuple(pos[v] for v in self.fscope[f]), arr))
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
    def fusion_pass(self, plan):
        merged_set = set()
        for b in list(plan.buckets):
            p = b.consumer
            if p is None or b not in p.children:
                continue
            self.clock.check_optional(); plan.mechanisms["fusion"]["candidates"] += 1
            base = _price_pair(self, b, p); merged = _price_merged(self, b, p)
            if merged < base:
                # merge: p eliminates b.elim + p.elim; owns b.fids + p.fids; children = p.children - b + b.children
                p.elim = list(b.elim) + list(p.elim); p.fids = list(b.fids) + list(p.fids); p.children = [c for c in p.children if c is not b] + list(b.children)
                for c in b.children:
                    c.consumer = p
                p.fused_from.append(b.bid); p.prov["fusion"] = "FUSION_PRICE"; plan.buckets.remove(b); plan.mechanisms["fusion"]["merged"] += 1
                p.views = {}; p.core_card = p.raw_scope_card; p.support = None; p.bag_support = None; p.support_prov = "RECOMPUTE_AFTER_FUSION"; p.demand = "FULL"; p.demand_prov = "FULL_AFTER_FUSION"
                for c in p.children:
                    c.demand = "FULL"; c.demand_prov = "FULL_AFTER_FUSION"
                merged_set.add(p)
            else:
                plan.mechanisms["fusion"]["declined"] += 1
        return merged_set

    # ------------------------------------------------------------------ storage decisions under the caps
    def storage_pass(self, plan, bytes_per_entry, caps):
        value_cap = caps["value_cache_blocks"]; index_cap = caps["source_ir_maps_output"] // 2
        for b in plan.buckets:
            b.stored = b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand))
            b.storage = IR.DENSE
            # SPARSE candidate: REDUCE(MUL) with a zero-bearing source operand, no compressed axes, and a cheaper join price
            if not b.views and b.fids:
                zf = [(f, sum(1 for x in self.ftable[f] if x != 0)) for f in b.fids]; zf = [(f, nz) for f, nz in zf if nz < len(self.ftable[f])]
                if zf:
                    f, nz = min(zf, key=lambda t: t[1] / max(1, len(self.ftable[t[0]])))
                    frac = Fr(nz, len(self.ftable[f]))
                    if frac <= Fr(3, 4) and b.demand == "FULL":
                        bag = list(b.elim) + list(b.scope); free = [v for v in bag if v not in self.fscope[f]]; joined = nz * prod(len(self.dom[v]) for v in free)
                        dense_rows = b.volume() * b.elim_volume(self.dom)
                        if joined < dense_rows:
                            b.storage = IR.SPARSE; b.sparse_rows = min(b.volume(), joined); plan.mechanisms["sparse"]["nodes"] += 1; b.prov["storage"] = "SPARSE_JOIN_PRICE"
        # memory: downgrade the largest non-root stored buckets until the reserved peak fits
        def reserved():
            tot = 0
            for b in plan.buckets:
                if b.storage == IR.DENSE:
                    tot += b.stored * bytes_per_entry + (len(b.demand) * 48 if b.demand not in ("FULL", "EMPTY") else 0)
                elif b.storage == IR.SPARSE:
                    tot += (b.sparse_rows or b.volume()) * (bytes_per_entry + 56)
            return tot
        while reserved() > value_cap:
            cands = [b for b in plan.buckets if b.consumer is not None and b.storage in (IR.DENSE, IR.SPARSE)]
            if not cands:
                break
            b = max(cands, key=lambda q: (q.stored * bytes_per_entry if q.storage == IR.DENSE else (q.sparse_rows or q.volume()) * (bytes_per_entry + 56), -q.bid))
            b.storage = IR.STREAM; b.prov["storage"] = "DOWNGRADED_TO_STREAM_MEMORY"; plan.mechanisms["downgrades"]["to_stream"] += 1
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
    if b.storage == IR.DENSE:
        return (b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand))) * ev
    if b.storage == IR.SPARSE:
        return (b.sparse_rows if b.sparse_rows is not None else b.volume()) * ev
    return b.reads * ev


def _ops(b):
    return len(b.fids) + len(b.elim) + len(b.children)


def _price_pair(B, b, p):
    """whole-path price of b materialized (stored) + p consuming it (forward + reverse rows x per-row work)"""
    kb = _ops(b); kp = _ops(p); rows_b = b.volume() * b.elim_volume(B.dom); rows_p = p.volume() * p.elim_volume(B.dom)
    return rows_b * (5 * kb + 5) + rows_p * (5 * kp + 5)


def _price_merged(B, b, p):
    kp = _ops(p) + _ops(b) - 1; rows = p.volume() * p.elim_volume(B.dom) * b.elim_volume(B.dom)
    if p.bag_support is not None:
        frac = Fr(int(p.bag_support.sum()), max(1, p.bag_support.size)); rows = int(rows * frac) + 1                 # rows with a zero operand are skipped by the kernel
    return rows * (5 * kp + 5)


def totals(B, plan, bytes_per_entry):
    _compute_reads(B, plan); fwd = 0; rev = 0; ideal = 0; stored_entries = 0; mem = 0
    for b in plan.buckets:
        k = _ops(b); ev = b.elim_volume(B.dom); rows = _rows_of(b, ev)
        fwd += rows * (2 * k + 1); rev += rows * (3 * k + 4); ideal += b.volume() * ev * (2 * k + 1)
        if b.storage == IR.DENSE:
            st = b.volume() if b.demand == "FULL" else (0 if b.demand == "EMPTY" else len(b.demand)); stored_entries += st; mem += st * bytes_per_entry + (len(b.demand) * 48 if b.demand not in ("FULL", "EMPTY") else 0)
        elif b.storage == IR.SPARSE:
            st = b.sparse_rows if b.sparse_rows is not None else b.volume(); stored_entries += st; mem += st * (bytes_per_entry + 56)
    mem += sum(len(B.dom[v]) for v in B.dom) * bytes_per_entry
    return {"cold_work_proxy": fwd + rev, "forward_proxy": fwd, "reverse_proxy": rev, "ideal_reuse_proxy": ideal, "stored_entries": stored_entries, "peak_reserved_bytes_estimate": mem, "buckets": len(plan.buckets), "streamed": sum(1 for b in plan.buckets if b.storage in (IR.STREAM, IR.CACHE)), "sparse": sum(1 for b in plan.buckets if b.storage == IR.SPARSE), "max_bucket_volume": max((b.volume() * b.elim_volume(B.dom) for b in plan.buckets), default=0)}


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
        n = P.reduce(m, set(b.elim), reps=reps, storage=b.storage, demand=b.demand, prov=dict(b.prov, bucket=b.bid, support=b.support_prov, demand=b.demand_prov, two_axis=b.two_axis, fused_from=list(b.fused_from)))
        node_of[b.bid] = n.nid
    for r in plan.roots:
        if r.bid in node_of:
            P.roots.append(node_of[r.bid])
    plan.program = P; plan.node_of_bucket = node_of; return P


# ---------------------------------------------------------------------------------------------------------------- entry point
def plan(view, cfg, clock, bytes_per_entry, caps=None):
    """returns (chosen Plan, candidates record). view = TrustedReduced.proposal_view(); cfg = ARMS[arm]."""
    caps = caps or CAPS; B = Builder(view, cfg, clock); dom = B.dom; scopes = [B.fscope[f] for f in sorted(B.factors)]
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
        pl = Plan(name, order); pl.roots = B.build(order, pl)
        # optional discovery (one shared allowance; a stop keeps the conservative baseline)
        try:
            if cfg["views"]:
                B.views_pass(pl)
            if cfg["demand_masks"] or cfg["fusion"]:
                B.support_pass(pl)
            if cfg["demand_masks"]:
                B.demand_pass(pl)
            if cfg["fusion"]:
                merged = B.fusion_pass(pl)
                if merged:
                    if cfg["views"]:
                        B.views_pass(pl, only=merged)                    # class maps of the merged buckets on the final topology
                    B.support_pass(pl)
                    if cfg["demand_masks"]:
                        B.demand_pass(pl)
        except PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                raise
            pl.discovery_stop = {"kind": ex.kind, "reason": ex.reason}
            for b in pl.buckets:                 # a partial pass must not leave half-updated structure: views are per bucket atomic; demand stays conservative
                pass
        pl.mechanisms["views"]["compressed_axes"] = sum(len(b.views) for b in pl.buckets)          # recount on the FINAL topology (fusion resets merged buckets)
        B.storage_pass(pl, bytes_per_entry, caps)
        try:
            emit(B, pl)
        except IR.IRError as ex:
            cands.append({"candidate": idx, "order": name, "state": "NOT_REPRESENTABLE", "reason": ex.reason, "order_info": info, "mechanisms": pl.mechanisms, "discovery_stop": pl.discovery_stop}); continue
        big = [n for n in pl.program.nodes if n.volume > IR.INT64_MAX or (n.kind == IR.REDUCE and prod(pl.program.nodes[n.children[0]].card) > IR.INT64_MAX)]
        if big:
            cands.append({"candidate": idx, "order": name, "state": "NOT_REPRESENTABLE", "reason": "node %d: volume exceeds int64 (symbolic domain too large for an indexed route)" % big[0].nid, "order_info": info, "mechanisms": pl.mechanisms, "discovery_stop": pl.discovery_stop}); continue
        pl.totals = totals(B, pl, bytes_per_entry)
        plans.append(pl); cands.append({"candidate": idx, "order": name, "state": "COMPLETE", "order_info": info, "simulation_updates": B.sim_updates, "totals": pl.totals, "mechanisms": pl.mechanisms, "discovery_stop": pl.discovery_stop})
    if not plans:
        raise PlanStop("NOT_REPRESENTABLE", "no complete representable candidate order: %s" % [(c.get("order"), c.get("state"), (c.get("reason") or "")[:80]) for c in cands])
    best = min(range(len(plans)), key=lambda i: (plans[i].totals["cold_work_proxy"], plans[i].totals["peak_reserved_bytes_estimate"], i))
    k = 0
    for c in cands:
        if c.get("state") == "COMPLETE":
            c["chosen"] = (k == best); k += 1
        else:
            c["chosen"] = False
    return plans[best], cands
