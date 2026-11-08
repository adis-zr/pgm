"""AGGREGATE_DP_V1 producer: deterministic weighted-min-fill bucket PROGRAM over the reduced model, source-certified
response VIEWS (class maps + exact scales per axis, intersected and multiplied inductively), and the numerical executor
(forward core evaluation in three execution formats of ONE recurrence -- dense batched blocks, native sparse supported
rows, lazy per-entry conditioning -- plus the shared backward pass that returns every marker derivative).

Producer arithmetic: nonnegative downward-rounded MPFR points (gmpy2 contexts from mdi.arith.Ctx, REUSED primitives) with
ONE conservative error-depth label E per node / adjoint node (mdi.arith invariant (1-u)^E v <= vhat <= v, u = 2^(1-p)).
Exact rationals decide every structural identity; they never enter the numeric hot loop.

The program is immutable once planned; `plan_record()` is what the independent checker (adp/checker.py) replays with its
own code. Nothing numeric is trusted across that boundary.
"""
from __future__ import annotations
import sys, time, hashlib, json, heapq
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import numpy as np
import gmpy2
from gmpy2 import mpfr
from mdi import arith as A                       # REUSED: directed MPFR contexts / error-depth algebra (accepted pin, read-only)
from adp import source as SRC

# ----------------------------------------------------------------------------------------------------- frozen settings
DEFAULTS = {
    "precision_ladder": [64, 128, 256, 512, 1024, 2048],
    "plan_work_cap": 3_000_000,            # candidate-score evaluations (neighbour-pair visits) before the order is finished in id order
    "dense_core_cap_entries": 1 << 23,     # a node whose OUTPUT core has at most this many entries is materialised (dense format)
    "dense_bag_cap_entries": 1 << 19,      # bag rows (x, c) evaluated per streamed chunk (transient product arrays; deadline polled per chunk)
    "sparse_rows_cap": 1 << 23,            # joined relation rows (x, c) before a sparse attempt is abandoned (charged, lazy fallback)
    "lazy_cache_entries": 1 << 20,         # bounded per-entry memo of the lazy format (entries), FIFO eviction + recompute
    "value_bytes_cap": int(1.5 * (1 << 30)),    # producer resident core values (every retained node; mpfr object + pointer per entry)
    "adjoint_bytes_cap": int(1.0 * (1 << 30)),  # producer resident adjoints (frontier: released after each node's reverse step)
    "scratch_bytes_cap": int(0.75 * (1 << 30)), # transient bag / join arrays of one operation
    "checker_value_bytes_cap": int(2.0 * (1 << 30)),  # checker resident lo+hi enclosures (two arrays per node)
    "source_reduction_wall_fraction": 0.3, # of the cell deadline; a cap leaves a valid partially reduced model
    "rules": list(SRC.ALL_RULES),
    "views": True, "sparse": True, "memo": True, "batched": True,
}


class Stop(Exception):
    """Typed resource stop: (kind, detail). Paid work stays recorded by the caller."""
    def __init__(self, kind, detail=""):
        super().__init__("%s: %s" % (kind, detail)); self.kind = kind; self.detail = detail


class NumericStop(Stop):
    pass


def mpfr_bytes(p):
    return 8 + sys.getsizeof(mpfr(1, p))


# ----------------------------------------------------------------------------------------------------- ordering
def weighted_min_fill(scopes, dom, work_cap):
    """Deterministic weighted min-fill on the primal graph: key = (sum over missing neighbour pairs of |D_i||D_j|,
    |D_v| prod_{u in N(v)} |D_u|, v). Scores are recomputed only for vertices within distance 2 of the eliminated vertex
    (exact: a fill edge joins two neighbours of v, so only their neighbours' fill sums change). When `work_cap`
    neighbour-pair visits are exhausted, the remaining variables follow in ascending id order (recorded)."""
    adj = {v: set() for v in dom}
    for sc in scopes:
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    work = 0
    def score(v):
        nonlocal work
        nb = sorted(adj[v]); fill = 0; bagp = len(dom[v])
        for i in range(len(nb)):
            bagp *= len(dom[nb[i]])
            for j in range(i + 1, len(nb)):
                work += 1
                if nb[j] not in adj[nb[i]]:
                    fill += len(dom[nb[i]]) * len(dom[nb[j]])
        return (fill, bagp, v)
    heap = []; cur = {}
    for v in sorted(dom):
        cur[v] = score(v); heapq.heappush(heap, (cur[v], v))
    order = []; alive = set(dom); capped_at = None
    while alive:
        if work > work_cap:
            capped_at = len(order); order.extend(sorted(alive)); break
        key, v = heapq.heappop(heap)
        if v not in alive or key != cur[v]:
            continue
        order.append(v); alive.discard(v); nb = adj[v]
        for a in nb:
            for b in nb:
                if a != b:
                    adj[a].add(b)
        for a in nb:
            adj[a].discard(v)
        touched = set(nb)
        for a in nb:
            touched |= adj[a]
        for u in touched:
            if u in alive:
                cur[u] = score(u); heapq.heappush(heap, (cur[u], u))
    return order, {"work": work, "capped_at": capped_at}


# ----------------------------------------------------------------------------------------------------- views
class View:
    """Class structure of one axis (variable w, positions 0..n-1 of dom[w]): cls[a] = class index (-1 = certified zero
    row), reps[c] = representative position (min member), ratio[a] = exact f(a) / f(rep) (Fraction; 1 for zero rows)."""
    __slots__ = ("cls", "reps", "ratio")

    def __init__(self, cls, reps, ratio):
        self.cls = cls; self.reps = reps; self.ratio = ratio

    @staticmethod
    def identity(n, zero_positions=()):
        z = set(zero_positions); reps = [a for a in range(n) if a not in z]; idx = {a: i for i, a in enumerate(reps)}
        return View([idx.get(a, -1) for a in range(n)], reps, [Fr(1)] * n)

    def key(self):
        return (tuple(self.cls), tuple("%d/%d" % (r.numerator, r.denominator) for r in self.ratio))

    def record(self):
        return {"cls": list(self.cls), "reps": list(self.reps), "ratio": ["%d/%d" % (r.numerator, r.denominator) for r in self.ratio]}


def source_view(f, k):
    sigs = f.row_signatures(k); groups = {}; cls = []; reps = []; ratio = []
    for a, (rep, rat, zero) in enumerate(sigs):
        if zero:
            cls.append(-1); ratio.append(Fr(1)); continue
        if rep not in groups:
            groups[rep] = len(reps); reps.append(rep)
        cls.append(groups[rep]); ratio.append(rat)
    return View(cls, reps, ratio)


def intersect_views(views, n):
    """Outgoing view of axis w from the incoming views (all inputs containing w): states equivalent iff every input puts
    them in the same class; zero if ANY input has a zero row; scale = product of the inputs' ratios a : common rep."""
    groups = {}; cls = [None] * n; reps = []; ratio = [Fr(1)] * n
    for a in range(n):
        sig = tuple(v.cls[a] for v in views)
        if any(c == -1 for c in sig):
            cls[a] = -1; continue
        if sig not in groups:
            groups[sig] = len(reps); reps.append(a)
        cls[a] = groups[sig]
    for a in range(n):
        if cls[a] >= 0:
            r = reps[cls[a]]; q = Fr(1)
            for v in views:
                q *= v.ratio[a] / v.ratio[r]
            ratio[a] = q
    return View(cls, reps, ratio)


# ----------------------------------------------------------------------------------------------------- program
class Node:
    __slots__ = ("nid", "v", "inputs", "scope", "views", "parent", "comp", "radix", "size", "bag", "fmt", "rank")

    def __init__(self, nid, v):
        self.nid = nid; self.v = v; self.inputs = []; self.scope = (); self.views = {}; self.parent = None; self.comp = None
        self.radix = (); self.size = 1; self.bag = 1; self.fmt = None; self.rank = 0


class Program:
    """Immutable bucket program over a reduced model R. Inputs of a node: ("F", fid) source factor or ("M", nid) message."""

    def __init__(self, R, cfg, deadline=None):
        self.R = R; self.cfg = cfg; self.dom = R.dom; self.vars = sorted(R.dom)
        self.fac = {f.fid: f for f in R.factors}
        t0 = time.monotonic()
        self.order, self.order_info = weighted_min_fill([f.scope for f in R.factors], R.dom, cfg["plan_work_cap"])
        self.plan_order_s = time.monotonic() - t0
        pos = {v: i for i, v in enumerate(self.order)}
        # source views (per factor, per axis) -- or identity views when response classes are disabled
        self.fviews = {}
        for f in R.factors:
            for k, w in enumerate(f.scope):
                if cfg["views"]:
                    self.fviews[f.fid, w] = source_view(f, k)
                else:
                    sigs = f.row_signatures(k); self.fviews[f.fid, w] = View.identity(f.card[k], [a for a, s in enumerate(sigs) if s[2]])
        # buckets
        live = {("F", f.fid): f.scope for f in R.factors}
        self.nodes = []; self.node_of_var = {}
        for v in self.order:
            if deadline is not None and time.monotonic() > deadline:
                raise Stop("DEADLINE", "planning")
            nd = Node(len(self.nodes), v); nd.inputs = sorted([ref for ref, sc in live.items() if v in sc], key=lambda r: (r[0], r[1]))
            scope = set()
            for ref in nd.inputs:
                scope |= set(live.pop(ref))
            scope.discard(v); nd.scope = tuple(sorted(scope, key=lambda w: pos[w]))     # earliest-later variable first
            for w in nd.scope:
                incoming = [self.view_of(ref, w) for ref in nd.inputs if w in self.scope_of(ref)]
                vw = intersect_views(incoming, len(self.dom[w]))
                if not cfg["views"]:                                       # identity partitions, zero rows still certified zero
                    vw = View.identity(len(self.dom[w]), [a for a in range(len(self.dom[w])) if vw.cls[a] == -1])
                nd.views[w] = vw
            nd.radix = tuple(len(nd.views[w].reps) for w in nd.scope); nd.size = SRC.prod(nd.radix); nd.bag = nd.size * len(self.dom[v])
            live[("M", nd.nid)] = nd.scope
            self.nodes.append(nd); self.node_of_var[v] = nd.nid
        for nd in self.nodes:
            if nd.scope:
                nd.parent = self.node_of_var[nd.scope[0]]
        # components = root forests; rank = depth from a root (dependency rank decreases on every recursive request)
        self.roots = [nd.nid for nd in self.nodes if nd.parent is None]
        comp = {}
        for nd in self.nodes:
            comp[nd.nid] = nd.nid if nd.parent is None else None
        for nd in reversed(self.nodes):
            if nd.parent is not None:
                nd.comp = comp[nd.parent] if comp[nd.parent] is not None else None
        for nd in self.nodes:                                                      # resolve in elimination order (parents later)
            pass
        for nd in reversed(self.nodes):
            comp[nd.nid] = nd.nid if nd.parent is None else comp[nd.parent]
        for nd in self.nodes:
            nd.comp = comp[nd.nid]
        self.components = sorted(set(comp.values()))
        # execution formats (frozen rule; recorded)
        for nd in self.nodes:
            if not cfg["batched"]:
                nd.fmt = "lazy"
            elif cfg["sparse"] and self.any_zero(nd):
                nd.fmt = "sparse"                                  # complete upward support: rows only where some assignment is positive
            elif nd.size <= cfg["dense_core_cap_entries"]:
                nd.fmt = "dense"
            else:
                nd.fmt = "lazy"
        self.plan_s = time.monotonic() - t0

    # --- structure helpers
    def scope_of(self, ref):
        return self.fac[ref[1]].scope if ref[0] == "F" else self.nodes[ref[1]].scope

    def view_of(self, ref, w):
        return self.fviews[ref[1], w] if ref[0] == "F" else self.nodes[ref[1]].views[w]

    def any_zero(self, nd):
        for ref in nd.inputs:
            if ref[0] == "F":
                if any(t == 0 for t in self.fac[ref[1]].table):
                    return True
            else:
                ch = self.nodes[ref[1]]
                if ch.fmt == "sparse" or any(-1 in vw.cls for vw in ch.views.values()):
                    return True
        return False

    def plan_record(self):
        return {"order": list(self.order), "order_info": self.order_info, "plan_s": self.plan_s,
                "nodes": [{"nid": nd.nid, "v": nd.v, "inputs": [list(r) for r in nd.inputs], "scope": list(nd.scope), "parent": nd.parent, "comp": nd.comp,
                           "radix": list(nd.radix), "size": nd.size, "bag": nd.bag, "fmt": nd.fmt, "views": {str(w): nd.views[w].record() for w in nd.scope}} for nd in self.nodes],
                "source_views": {"%d:%d" % (fid, w): vw.record() for (fid, w), vw in sorted(self.fviews.items())},
                "roots": self.roots, "components": self.components}

    def structure_hash(self):
        h = hashlib.sha256(); h.update(json.dumps(self.order).encode())
        for nd in self.nodes:
            h.update(json.dumps([nd.inputs, nd.scope, nd.fmt, {str(w): nd.views[w].key() for w in nd.scope}], default=str).encode())
        return h.hexdigest()


# ----------------------------------------------------------------------------------------------------- numeric state
class Core:
    """Values of one node's core. dense: vals over all size entries (flat, mixed radix); sparse: sorted int64 keys + vals;
    lazy: dict key -> value (bounded). E = conservative error depth of every value; `uses` counts parent lookups."""
    __slots__ = ("fmt", "keys", "vals", "E", "zmask", "bytes", "lazy", "adj", "adjE", "rows_rel", "stats")

    def __init__(self, fmt):
        self.fmt = fmt; self.keys = None; self.vals = None; self.E = 0; self.zmask = None; self.bytes = 0; self.lazy = None; self.adj = None; self.adjE = 0; self.rows_rel = None; self.stats = {}


class Executor:
    """Forward + backward numeric execution of a Program at precision p (producer points, RNDD)."""

    def __init__(self, prog, p, cfg, deadline=None, counters=None):
        self.P = prog; self.p = p; self.cfg = cfg; self.deadline = deadline; self.ctx = A.Ctx(p); self.D = self.ctx.D
        gmpy2.set_context(self.D)                                        # process-global RNDD context at precision p (set again on every entry)
        self.cores = {}; self.markers = {}; self.markerE = {}; self.bytes_vals = 0; self.bytes_adj = 0; self.mp = mpfr_bytes(p)
        self.c = counters if counters is not None else {}
        for k in ("entries_computed", "bag_rows", "forward_mults", "forward_adds", "reverse_mults", "reverse_adds", "lookups", "lazy_evals", "lazy_hits", "lazy_evictions", "lazy_recomputes",
                  "sparse_attempts", "sparse_abandoned", "dense_blocks", "sparse_nodes", "lazy_nodes", "peak_scratch_bytes", "support_rows", "support_dense_equiv"):
            self.c.setdefault(k, 0)
        self.ftab = {}                                                   # fid -> object array of downward source values (E=1 for positive, 0 for zero)
        self.fzero = {}
        for f in prog.R.factors:
            arr = np.empty(len(f.table), dtype=object)
            for i, t in enumerate(f.table):
                arr[i] = self.ctx.down(t)
            self.ftab[f.fid] = arr; self.fzero[f.fid] = np.fromiter((t == 0 for t in f.table), dtype=bool, count=len(f.table))
        self.scale_cache = {}; self.spec_cache = {}

    # --- helpers
    def tick(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise Stop("DEADLINE", "numeric execution")

    def mp_scale(self, q):
        """downward mpfr of an exact positive rational scale (E contribution 1 unless q == 1)."""
        k = (q.numerator, q.denominator)
        x = self.scale_cache.get(k)
        if x is None:
            x = self.ctx.down(q); self.scale_cache[k] = x
        return x

    def input_states(self, nd, ref):
        """Precomputed gather spec of input `ref` at node nd, one entry per axis of the input's scope:
        source factor:  ("x", stride) | ("f", w, reps, stride)             -- indexed by STATE position (output rep state)
        child message:  ("x", cls_x, scale_x | None, zero_x | None, stride) | ("m", w, cls_in, scale | None, stride)
        where cls_* map bag coordinates to the child's class index, scale_* are object arrays of downward mpfr ratios (None if all 1)."""
        key = (nd.nid, ref)
        spec = self.spec_cache.get(key)
        if spec is not None:
            return spec
        sc = self.P.scope_of(ref); spec = []
        if ref[0] == "F":
            st = SRC.strides_of(self.P.fac[ref[1]].card)
            for k, w in enumerate(sc):
                spec.append(("x", st[k]) if w == nd.v else ("f", w, np.array(nd.views[w].reps, dtype=np.int64), st[k]))
            spec = ("F", spec, 0)
        else:
            ch = self.P.nodes[ref[1]]; nscale = 0
            for k, w in enumerate(sc):
                vw_in = ch.views[w]; st = ch_stride(ch, k)
                if w == nd.v:
                    cls = np.array([max(c, 0) for c in vw_in.cls], dtype=np.int64); zero = np.array([c < 0 for c in vw_in.cls], dtype=bool)
                    scale = (np.array([self.mp_scale(vw_in.ratio[a]) if vw_in.cls[a] >= 0 else mpfr(0) for a in range(len(vw_in.cls))], dtype=object) if any(q != 1 for q in vw_in.ratio) else None)
                    spec.append(("x", cls, scale, zero if zero.any() else None, st))
                else:
                    reps = nd.views[w].reps; cls_in = np.array([vw_in.cls[a] for a in reps], dtype=np.int64); rat = [vw_in.ratio[a] for a in reps]
                    scale = np.array([self.mp_scale(q) for q in rat], dtype=object) if any(q != 1 for q in rat) else None
                    spec.append(("m", w, cls_in, scale, st))
                nscale += 1 if spec[-1][2] is not None else 0
            spec = ("M", spec, nscale)
        self.spec_cache[key] = spec
        return spec

    # --- forward
    def forward(self):
        gmpy2.set_context(self.D); self.rootvals = None
        for nd in self.P.nodes:
            self.tick(); t = time.monotonic()
            if nd.fmt == "dense":
                self.forward_dense(nd)
            elif nd.fmt == "sparse":
                self.forward_sparse(nd)
            else:
                self.forward_lazy_node(nd)
            self.cores[nd.nid].stats["forward_s"] = time.monotonic() - t
        self.rootvals = self.root_values()

    def gather_inputs(self, nd, x_idx, c_keys):
        """For bag rows (x position array, output flat key array): per input (values object array, E, exact-zero mask)."""
        decode = self.decode_keys(nd, c_keys); out = []; Es = []; zs = []
        for ref in nd.inputs:
            kind, spec, nscale = self.input_states(nd, ref)
            flat = np.zeros(len(c_keys), dtype=np.int64)
            if kind == "F":
                for item in spec:
                    if item[0] == "x":
                        flat += x_idx * item[1]
                    else:
                        flat += item[2][decode[item[1]]] * item[3]
                vals = self.ftab[ref[1]][flat]; E = 1; zero = self.fzero[ref[1]][flat]
            else:
                core = self.cores[ref[1]]; scale = None; xzero = None
                for item in spec:
                    if item[0] == "x":
                        _, cls, sc, zx, st = item; flat += cls[x_idx] * st
                        if sc is not None:
                            s = sc[x_idx]; scale = s if scale is None else scale * s
                        if zx is not None:
                            xzero = zx[x_idx]
                    else:
                        _, w, cls_in, sc, st = item; ci = decode[w]; flat += cls_in[ci] * st
                        if sc is not None:
                            s = sc[ci]; scale = s if scale is None else scale * s
                vals, zero = self.lookup(core, flat); E = core.E
                if scale is not None:
                    vals = vals * scale; E += 2 * nscale; self.c["forward_mults"] += len(vals) * nscale
                if xzero is not None:
                    zero = zero | xzero
                self.c["lookups"] += len(flat)
            out.append(vals); Es.append(E); zs.append(zero)
        return out, Es, zs

    def decode_keys(self, nd, keys):
        out = {}; rem = keys
        for w, r in zip(reversed(nd.scope), reversed(nd.radix)):            # last scope variable varies fastest
            out[w] = rem % r; rem = rem // r
        return out

    def lookup(self, core, flat):
        """(values, exact-zero mask) of core entries at flat keys. Missing sparse rows are PROVED zeros (complete support)."""
        if core.fmt == "dense":
            if len(core.vals) == 0:                                      # a node whose output view has NO positive class: identically zero
                return np.full(len(flat), mpfr(0), dtype=object), np.ones(len(flat), dtype=bool)
            return core.vals[flat], core.zmask[flat]
        if core.fmt == "sparse":
            if len(core.keys) == 0:
                return np.full(len(flat), mpfr(0), dtype=object), np.ones(len(flat), dtype=bool)
            pos = np.searchsorted(core.keys, flat); pos_c = np.minimum(pos, len(core.keys) - 1); hit = core.keys[pos_c] == flat
            out = np.full(len(flat), mpfr(0), dtype=object); out[hit] = core.vals[pos_c[hit]]; return out, ~hit
        uniq, inv = np.unique(flat, return_inverse=True); vals = np.empty(len(uniq), dtype=object); zero = np.zeros(len(uniq), dtype=bool)
        for i, k in enumerate(uniq):
            vals[i], zero[i] = self.eval_lazy(core, int(k))
        return vals[inv], zero[inv]

    def product_sum(self, nd, vals, Es, zs, n):
        """term = prod_j vals_j over the n bag rows (exact zero mask = any input zero). Source-factor inputs are folded first into F
        (they need no adjoint); message inputs follow. Returns (term, E, zero, F, EF, msg_positions)."""
        fac = [j for j, ref in enumerate(nd.inputs) if ref[0] == "F"]; msg = [j for j, ref in enumerate(nd.inputs) if ref[0] == "M"]
        if not vals:
            one = np.full(n, mpfr(1), dtype=object); self.c["bag_rows"] += n
            return one, 0, np.zeros(n, dtype=bool), one, 0, msg
        zero = zs[0].copy()
        for z2 in zs[1:]:
            zero |= z2
        if fac:
            F = vals[fac[0]]; EF = Es[fac[0]]
            for j in fac[1:]:
                F = F * vals[j]; EF = EF + Es[j] + 1; self.c["forward_mults"] += n
        else:
            F = None; EF = 0
        term = F; E = EF
        for j in msg:
            if term is None:
                term = vals[j]; E = Es[j]
            else:
                term = term * vals[j]; E = E + Es[j] + 1; self.c["forward_mults"] += n
        self.c["bag_rows"] += n
        return term, E, zero, F, EF, msg

    def forward_dense(self, nd):
        """The dense format: the output core (size entries) is materialised; the bag (size x |D_v| rows) is streamed in chunks of at
        most `dense_bag_cap_entries` rows so the transient product array is bounded (reserve-before-allocate against the scratch cap)."""
        v = nd.v; nx = len(self.P.dom[v]); size = nd.size
        if size * self.mp + self.bytes_vals > self.cfg["value_bytes_cap"]:
            raise Stop("VALUE_CAP", "core of node %d (%d entries) does not fit the resident value cap" % (nd.nid, size))
        chunk = max(1, self.cfg["dense_bag_cap_entries"] // nx)
        if chunk * nx * (8 * 4 + self.mp) > self.cfg["scratch_bytes_cap"]:
            chunk = max(1, self.cfg["scratch_bytes_cap"] // (nx * (8 * 4 + self.mp)))
        out = np.empty(size, dtype=object); zout = np.empty(size, dtype=bool); Emax = 0
        for lo in range(0, size, chunk):
            self.tick(); hi = min(size, lo + chunk); m = hi - lo
            c_keys = np.tile(np.arange(lo, hi, dtype=np.int64), nx); x_idx = np.repeat(np.arange(nx, dtype=np.int64), m)
            vals, Es, zs = self.gather_inputs(nd, x_idx, c_keys)
            term, E, zero, _, _, _ = self.product_sum(nd, vals, Es, zs, len(c_keys))
            out[lo:hi] = np.add.reduce(term.reshape(nx, m), axis=0) if nx > 1 else term
            zout[lo:hi] = zero.reshape(nx, m).all(axis=0); Emax = max(Emax, E); self.c["dense_blocks"] += 1
        self.c["forward_adds"] += (nx - 1) * size; self.c["entries_computed"] += size
        core = Core("dense"); core.vals = out; core.zmask = zout; core.E = Emax + (nx - 1); core.bytes = size * self.mp
        self.commit(nd, core)

    def commit(self, nd, core):
        self.bytes_vals += core.bytes; self.c["peak_scratch_bytes"] = max(self.c["peak_scratch_bytes"], self.bytes_vals)
        if self.bytes_vals > self.cfg["value_bytes_cap"]:
            raise Stop("VALUE_CAP", "resident core values %d bytes exceed the cap" % self.bytes_vals)
        self.cores[nd.nid] = core

    # --- sparse: native join of complete input supports in bag coordinates, projected over x
    def input_relation(self, nd, ref):
        """Complete support of input `ref` as rows over (x position | output class indices of its scope vars), int64 columns in the
        order of `cols` (list of 'x' or w). Source factor: positive entries, restricted to rep states. Message: its support rows lifted
        to every output class mapping to each child class."""
        sc = self.P.scope_of(ref); cols = ["x" if w == nd.v else w for w in sc]
        if ref[0] == "F":
            f = self.P.fac[ref[1]]; pos = np.flatnonzero(~self.fzero[ref[1]]); st = SRC.strides_of(f.card)
            coords = [(pos // st[k]) % f.card[k] for k in range(len(sc))]           # state positions
            keep = np.ones(len(pos), dtype=bool); outc = []
            for k, w in enumerate(sc):
                if w == nd.v:
                    outc.append(coords[k]); continue
                vw = nd.views[w]; cls = np.array(vw.cls, dtype=np.int64); isrep = np.zeros(len(vw.cls), dtype=bool); isrep[vw.reps] = True
                keep &= isrep[coords[k]]; outc.append(cls[coords[k]])
            return cols, np.stack([c[keep] for c in outc], axis=1) if len(pos) else np.zeros((0, len(sc)), dtype=np.int64)
        ch = self.P.nodes[ref[1]]; core = self.cores[ch.nid]
        keys = core.keys if core.fmt == "sparse" else (np.flatnonzero(~core.zmask) if core.fmt == "dense" else None)
        if keys is None:
            raise Stop("SPARSE_INPUT_LAZY", "child %d has a lazy core: no complete support available" % ch.nid)
        rows = np.stack([((keys // ch_stride(ch, k)) % ch.radix[k]) for k in range(len(sc))], axis=1) if len(keys) else np.zeros((0, len(sc)), dtype=np.int64)
        # lift each child class to the output classes mapping to it (for w in nd.scope) / to x positions (for nd.v)
        for k, w in enumerate(sc):
            vw_in = ch.views[w]
            if w == nd.v:
                lift = [[] for _ in vw_in.reps]
                for a, c in enumerate(vw_in.cls):
                    if c >= 0:
                        lift[c].append(a)
            else:
                vw_out = nd.views[w]; lift = [[] for _ in vw_in.reps]
                for c_out, r in enumerate(vw_out.reps):
                    lift[vw_in.cls[r]].append(c_out)
            counts = np.array([len(l) for l in lift], dtype=np.int64); rep = counts[rows[:, k]]
            total = int(rep.sum())
            if total > self.cfg["sparse_rows_cap"]:
                raise Stop("SPARSE_ROWS_CAP", "lifting child %d along %s" % (ch.nid, w))
            flat_lift = np.concatenate([np.array(l, dtype=np.int64) for l in lift]) if total else np.zeros(0, dtype=np.int64)
            offs = np.concatenate([[0], np.cumsum(counts)[:-1]])
            idx = np.repeat(np.arange(len(rows)), rep)
            within = np.arange(total) - np.repeat(np.cumsum(rep) - rep, rep)
            newcol = flat_lift[offs[rows[idx, k]] + within]
            rows = rows[idx]; rows[:, k] = newcol
        return cols, rows

    def join(self, cols_a, A_, cols_b, B_, cap, radix):
        shared = [c for c in cols_a if c in cols_b]; only_b = [c for c in cols_b if c not in cols_a]
        if not shared:
            n = len(A_) * len(B_)
            if n > cap:
                raise Stop("SPARSE_ROWS_CAP", "cross product %d rows" % n)
            ia = np.repeat(np.arange(len(A_)), len(B_)); ib = np.tile(np.arange(len(B_)), len(A_))
            return cols_a + only_b, np.concatenate([A_[ia], B_[ib][:, [cols_b.index(c) for c in only_b]]], axis=1) if n else np.zeros((0, len(cols_a) + len(only_b)), dtype=np.int64)
        rad = [radix[c] for c in shared]
        ka = encode_radix(A_[:, [cols_a.index(c) for c in shared]], rad); kb = encode_radix(B_[:, [cols_b.index(c) for c in shared]], rad)
        ordb = np.argsort(kb, kind="stable"); kbs = kb[ordb]
        lo = np.searchsorted(kbs, ka, side="left"); hi = np.searchsorted(kbs, ka, side="right"); cnt = hi - lo; n = int(cnt.sum())
        if n > cap:
            raise Stop("SPARSE_ROWS_CAP", "join %d rows" % n)
        ia = np.repeat(np.arange(len(A_)), cnt); within = np.arange(n) - np.repeat(np.cumsum(cnt) - cnt, cnt); ib = ordb[np.repeat(lo, cnt) + within]
        out = np.concatenate([A_[ia], B_[ib][:, [cols_b.index(c) for c in only_b]]], axis=1) if n else np.zeros((0, len(cols_a) + len(only_b)), dtype=np.int64)
        return cols_a + only_b, out

    def forward_sparse(self, nd):
        self.c["sparse_attempts"] += 1; cap = self.cfg["sparse_rows_cap"]
        try:
            rels = [self.input_relation(nd, ref) for ref in nd.inputs]
            rels.sort(key=lambda cr: len(cr[1]))
            radix = {"x": len(self.P.dom[nd.v])}; radix.update({w: len(nd.views[w].reps) for w in nd.scope})
            cols, rows = rels[0]
            for c2, r2 in rels[1:]:
                self.tick(); cols, rows = self.join(cols, rows, c2, r2, cap, radix)
            # every bag variable must be present; an input-free variable (impossible here: nd.v is in every input's scope) -- scope vars absent from
            # all inputs cannot exist since scope = union of input scopes
            if rows.nbytes > self.cfg["scratch_bytes_cap"]:
                raise Stop("SCRATCH_CAP", "sparse relation %d bytes" % rows.nbytes)
        except Stop as ex:
            if ex.kind in ("SPARSE_ROWS_CAP", "SPARSE_INPUT_LAZY", "SCRATCH_CAP"):
                self.c["sparse_abandoned"] += 1; nd.fmt = "lazy"; self.P.nodes[nd.nid].fmt = "lazy"
                self.forward_lazy_node(nd, abandoned=str(ex)); return
            raise
        x_idx = rows[:, cols.index("x")]; sc_cols = [cols.index(w) for w in nd.scope]
        c_keys = encode_radix(rows[:, sc_cols], nd.radix) if nd.scope else np.zeros(len(rows), dtype=np.int64)
        order = np.argsort(c_keys, kind="stable"); c_keys = c_keys[order]; x_idx = x_idx[order]
        self.c["support_rows"] += len(rows); self.c["support_dense_equiv"] += nd.bag
        if True:
            vals, Es, zs = self.gather_inputs(nd, x_idx, c_keys)
            term, E, zero, _, _, _ = self.product_sum(nd, vals, Es, zs, len(c_keys))
            if zero.any():
                raise Stop("FAULT", "a joined support row evaluated to an exact zero (join not a product of positive inputs)")
            if len(c_keys):
                starts = np.flatnonzero(np.r_[True, c_keys[1:] != c_keys[:-1]]); out = np.add.reduceat(term, starts); keys = c_keys[starts]
                seg = np.diff(np.r_[starts, len(c_keys)]); self.c["forward_adds"] += int((seg - 1).sum()); Emax_add = int(seg.max()) - 1
            else:
                out = np.zeros(0, dtype=object); keys = np.zeros(0, dtype=np.int64); Emax_add = 0
        core = Core("sparse"); core.keys = keys; core.vals = np.asarray(out, dtype=object).reshape(-1); core.E = E + Emax_add; core.bytes = len(keys) * (8 + self.mp)
        core.rows_rel = (x_idx, c_keys)                                           # retained for the backward pass (same rows revisited)
        core.stats["rows"] = int(len(rows)); core.stats["out_rows"] = int(len(keys)); core.stats["dense_equiv"] = nd.bag
        self.c["entries_computed"] += len(keys); self.c["sparse_nodes"] += 1
        self.commit(nd, core)

    # --- lazy per-entry conditioning (the universal fallback; also ablations A4 / A5)
    def forward_lazy_node(self, nd, abandoned=None):
        core = Core("lazy"); core.lazy = {}; core.E = None; core.stats["abandoned_sparse"] = abandoned; self.cores[nd.nid] = core; self.c["lazy_nodes"] += 1
        core.stats["node"] = nd.nid
        if nd.parent is None:                                                  # a root: its single entry is demanded now
            self.eval_lazy(core, 0)

    def eval_lazy(self, core, key):
        """Eval(node, key): exhaustive sum over the eliminated variable with every input looked up through its view (recursive
        requests only descend to children, so dependency rank strictly decreases). Memoized in a bounded FIFO dict."""
        nd = self.P.nodes[core.stats["node"]]
        if self.cfg["memo"]:
            hit = core.lazy.get(key)
            if hit is not None:
                self.c["lazy_hits"] += 1; return hit[0], hit[2]
        self.tick(); self.c["lazy_evals"] += 1
        nx = len(self.P.dom[nd.v]); c_keys = np.full(nx, key, dtype=np.int64); x_idx = np.arange(nx, dtype=np.int64)
        vals, Es, zs = self.gather_inputs(nd, x_idx, c_keys)
        term, E, zero, _, _, _ = self.product_sum(nd, vals, Es, zs, nx)
        tot = term[0]
        for t in term[1:]:
            tot = tot + t
        z = bool(zero.all())
        E = E + (nx - 1); self.c["forward_adds"] += nx - 1; self.c["entries_computed"] += 1
        if core.E is None or E > core.E:
            core.E = E
        if self.cfg["memo"]:
            if len(core.lazy) >= self.cfg["lazy_cache_entries"]:
                core.lazy.pop(next(iter(core.lazy))); self.c["lazy_evictions"] += 1
            core.lazy[key] = (tot, E, z)
        return tot, z

    # --- backward
    def backward(self):
        """Reverse elimination order; one scalar adjoint per resident core entry; division-free sibling products; every lookup
        contributes adjoint x scale to the child's core entry; marker(v, x) += adjoint x product of all inputs."""
        gmpy2.set_context(self.D)
        for v in self.P.vars:
            self.markers[v] = np.full(len(self.P.dom[v]), mpfr(0), dtype=object); self.markerE[v] = 0
        for r in self.P.roots:
            core = self.cores[r]; self.seed(core, 0, mpfr(1), 0)
        for nd in reversed(self.P.nodes):
            self.tick(); t = time.monotonic(); core = self.cores[nd.nid]
            if core.fmt == "lazy":
                self.backward_lazy(nd, core)
            else:
                self.backward_block(nd, core)
            core.stats["backward_s"] = time.monotonic() - t
            if core.adj is not None and core.fmt != "lazy":
                self.bytes_adj -= len(core.vals) * self.mp
            core.adj = None                                               # frontier release: every parent contribution has been consumed
            if not self.cfg.get("keep_values_after_reverse", False):
                self.bytes_vals -= core.bytes; core.vals = None; core.keys = None; core.lazy = None; core.rows_rel = None   # its own step was the last reader

    def seed(self, core, key, val, E):
        if core.fmt == "lazy":
            core.adj = core.adj or {}; cur = core.adj.get(key)
            core.adj[key] = ((cur[0] + val) if cur else val, max(E, cur[1] if cur else 0) + (1 if cur else 0))
        else:
            if len(core.vals) == 0:
                return
            if core.adj is None:
                core.adj = np.full(len(core.vals), mpfr(0), dtype=object); core.adjE = 0
                self.bytes_adj += len(core.vals) * self.mp
                if self.bytes_adj > self.cfg["adjoint_bytes_cap"]:
                    raise Stop("ADJOINT_CAP", "resident adjoints %d bytes exceed the cap" % self.bytes_adj)
            if core.fmt == "sparse":
                idx = int(np.searchsorted(core.keys, key))
                if idx >= len(core.keys) or core.keys[idx] != key:
                    return                                                 # proved-zero root entry: identically zero polynomial, no derivatives
            else:
                idx = key
            core.adj[idx] = core.adj[idx] + val; core.adjE = max(core.adjE, E) + 1

    def backward_block(self, nd, core):
        if core.adj is None:
            return                                                         # nothing demanded (cannot happen for a reachable node)
        nx = len(self.P.dom[nd.v])
        if core.fmt == "dense":
            size = nd.size; chunk = max(1, self.cfg["dense_bag_cap_entries"] // nx)
            for lo in range(0, size, chunk):
                self.tick(); hi = min(size, lo + chunk); m = hi - lo
                c_keys = np.tile(np.arange(lo, hi, dtype=np.int64), nx); x_idx = np.repeat(np.arange(nx, dtype=np.int64), m); adj_rows = np.tile(core.adj[lo:hi], nx)
                self.backward_rows(nd, core, x_idx, c_keys, adj_rows, dense_shape=(nx, m))
            return
        x_idx, c_keys = core.rows_rel; pos = np.searchsorted(core.keys, c_keys); adj_rows = core.adj[pos]
        self.backward_rows(nd, core, x_idx, c_keys, adj_rows, dense_shape=None)

    def backward_rows(self, nd, core, x_idx, c_keys, adj_rows, dense_shape):
        """Reverse kernel over the SAME bag rows as the forward sum: marker(v, x) += adj * prod(all inputs); message input j receives
        adj * (product of all other inputs) through division-free prefix / suffix products over the message inputs (factor inputs are
        folded into one base product; they carry no adjoint)."""
        nx = len(self.P.dom[nd.v]); n = len(c_keys)
        vals, Es, zs = self.gather_inputs(nd, x_idx, c_keys)
        _, _, _, F, EF, msg = self.product_sum(nd, vals, Es, zs, n)
        base = adj_rows if F is None else adj_rows * F; Ebase = core.adjE + (0 if F is None else EF + 1); self.c["reverse_mults"] += (0 if F is None else n)
        r = len(msg); pre = [base]; Epre = [Ebase]
        for j in msg:
            pre.append(pre[-1] * vals[j]); Epre.append(Epre[-1] + Es[j] + 1)
        self.c["reverse_mults"] += n * r
        full = pre[r]; mk = self.markers[nd.v]
        if dense_shape is not None:
            mk_add = np.add.reduce(full.reshape(dense_shape), axis=1)
            for x in range(nx):
                mk[x] = mk[x] + mk_add[x]
        else:
            np.add.at(mk, x_idx, full)
        self.c["reverse_adds"] += n
        self.markerE[nd.v] = max(self.markerE[nd.v], Epre[r] + n + 1)
        suf = None; Esuf = 0
        for i in range(r - 1, -1, -1):
            j = msg[i]; contrib = pre[i] if suf is None else pre[i] * suf; Ec = Epre[i] + (0 if suf is None else Esuf + 1)
            if suf is not None:
                self.c["reverse_mults"] += n
            self.push_child(nd, nd.inputs[j], x_idx, c_keys, contrib, Ec)
            if i > 0:
                suf = vals[j] if suf is None else suf * vals[j]; Esuf = Es[j] if Esuf == 0 and suf is vals[j] else Esuf + Es[j] + 1
                if suf is not vals[j]:
                    self.c["reverse_mults"] += n

    def push_child(self, nd, ref, x_idx, c_keys, contrib, E):
        """contrib is the adjoint of the LOOKED-UP value (scale x core entry): the core entry receives contrib x scale. Rows whose
        lookup is a proved zero polynomial (zero class along x, or outside a complete sparse support) carry no derivative."""
        ch = self.P.nodes[ref[1]]; ccore = self.cores[ch.nid]; _, spec, nscale = self.input_states(nd, ref); decode = self.decode_keys(nd, c_keys)
        flat = np.zeros(len(c_keys), dtype=np.int64); scale = None; zero = None
        for item in spec:
            if item[0] == "x":
                _, cls, sc, zx, st = item; flat += cls[x_idx] * st
                if sc is not None:
                    s = sc[x_idx]; scale = s if scale is None else scale * s
                if zx is not None:
                    zero = zx[x_idx]
            else:
                _, w, cls_in, sc, st = item; ci = decode[w]; flat += cls_in[ci] * st
                if sc is not None:
                    s = sc[ci]; scale = s if scale is None else scale * s
        if scale is not None:
            contrib = contrib * scale; self.c["reverse_mults"] += len(contrib) * nscale; E += 2 * nscale
        if zero is not None:
            keep = ~zero; flat = flat[keep]; contrib = contrib[keep]
        if ccore.fmt == "lazy":
            ccore.adj = ccore.adj or {}
            for kk, cv in zip(flat.tolist(), contrib):
                cur = ccore.adj.get(kk); ccore.adj[kk] = ((cur[0] + cv) if cur else cv, (max(cur[1], E) + 1) if cur else E)
                if len(ccore.adj) > self.cfg["lazy_cache_entries"]:
                    kk2, (dv, dE) = ccore.adj.popitem(); self.pullback_lazy(ch, ccore, kk2, dv, dE)      # flush ONE pending delta; consumed exactly once
            return
        if ccore.fmt == "dense":
            if len(ccore.vals) == 0:
                return
            idx = flat
        else:
            if len(ccore.keys) == 0:
                return
            idx = np.searchsorted(ccore.keys, flat); idx_c = np.minimum(idx, len(ccore.keys) - 1); ok = ccore.keys[idx_c] == flat
            self.c["reverse_dropped_zero_rows"] = self.c.get("reverse_dropped_zero_rows", 0) + int((~ok).sum())
            idx = idx_c[ok]; contrib = contrib[ok]                      # a missing row is a PROVED zero polynomial: no derivatives to collect
        if len(idx) == 0:
            return
        if ccore.adj is None:
            ccore.adj = np.full(len(ccore.vals), mpfr(0), dtype=object); ccore.adjE = 0; self.bytes_adj += len(ccore.vals) * self.mp
            if self.bytes_adj > self.cfg["adjoint_bytes_cap"]:
                raise Stop("ADJOINT_CAP", "resident adjoints %d bytes exceed the cap" % self.bytes_adj)
        np.add.at(ccore.adj, idx, contrib); self.c["reverse_adds"] += len(idx)
        ccore.adjE = max(ccore.adjE, E) + len(idx) + 1                 # conservative: up to len(idx) sequential additions into one entry

    def backward_lazy(self, nd, core):
        if not core.adj:
            return
        while core.adj:
            key, (dv, dE) = core.adj.popitem(); self.pullback_lazy(nd, core, key, dv, dE)

    def pullback_lazy(self, nd, core, key, alpha, E):
        """Pullback(node, key, alpha): revisit the eliminated states of this entry, recomputing input values (through their caches or
        recursively), accumulate marker(v, x) and push child contributions. No gradient side effects elsewhere; a flushed delta is
        consumed exactly once."""
        self.tick(); nx = len(self.P.dom[nd.v]); c_keys = np.full(nx, key, dtype=np.int64); x_idx = np.arange(nx, dtype=np.int64)
        adj_rows = np.full(nx, alpha, dtype=object)
        class _A: pass
        tmp = _A(); tmp.adjE = E
        self.backward_rows(nd, tmp, x_idx, c_keys, adj_rows, dense_shape=None)

    # --- results
    def root_values(self):
        if getattr(self, "rootvals", None) is not None:
            return self.rootvals
        out = {}
        for r in self.P.roots:
            core = self.cores[r]
            if core.fmt == "lazy":
                z = core.lazy[0][0] if (core.lazy and 0 in core.lazy) else self.eval_lazy(core, 0)[0]; E = core.E
            elif core.fmt == "dense":
                z = core.vals[0] if len(core.vals) else mpfr(0); E = core.E
            else:
                z = core.vals[0] if len(core.keys) and core.keys[0] == 0 else mpfr(0); E = core.E
            out[r] = (z, E)
        return out

    def enclosures(self):
        """Producer's provisional N1 enclosures of every reduced singleton P(y = s): exact Fractions [lo, hi] from the downward
        points and the depth labels (mdi.arith.marginal_interval with L = lam(E_max, p))."""
        roots = self.root_values(); out = {}; Emax = 0
        for v in self.P.vars:
            Emax = max(Emax, self.markerE.get(v, 0))
        for r, (z, E) in roots.items():
            Emax = max(Emax, E)
        L = A.lam(Emax, self.p)
        for v in self.P.vars:
            mk = self.markers[v]; tot = A.exact_fr(mk[0])
            for x in mk[1:]:
                tot += A.exact_fr(x)
            row = []
            for a in range(len(mk)):
                Aq = A.exact_fr(mk[a]); C = tot - Aq
                if Aq == 0 and C == 0:
                    row.append(None); continue
                row.append(A.marginal_interval(Aq, C, L))
            out[v] = row
        return out, roots, Emax


def ch_stride(ch, k):
    s = 1
    for r in ch.radix[k + 1:]:
        s *= r
    return s


def encode_radix(cols, radix):
    key = np.zeros(len(cols), dtype=np.int64)
    for j, r in enumerate(radix):
        key = key * r + cols[:, j]
    return key
