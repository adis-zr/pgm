"""Validated model, JSON I/O and the EXACT reductions: parallel-edge fusion (A), hard-component contraction (r = 1; empty support
intersection is an INFEASIBLE proof), separable-coordinate absorption (coordinates constant on one endpoint's support become exact unary
tilts; coordinates constant on both become scalars; an edge with no coordinate varying on both sides is removed), and the mapping of the
original blocks / queries onto the reduced graph. Every statement here is exact; weights stay positive integers (absorbed tilts are
multiplied by their denominators, the dropped positive scalars are recorded)."""
from __future__ import annotations
from fractions import Fraction as Fr
from dataclasses import dataclass, field
import json, hashlib
import numpy as np

BIT_CONVENTION = "coordinate j (0-based, j < d) <-> bit j of the state mask; bit set <-> x_j = +1"
MAX_D = 62


class UnsupportedInput(ValueError):
    pass


@dataclass
class Block:
    id: int
    rows: list                   # unique int masks
    w: list                      # positive ints (same length)

    def index(self):
        return {x: i for i, x in enumerate(self.rows)}

    def varying_mask(self):
        o = 0; a = (1 << 63) - 1
        for x in self.rows:
            o |= x; a &= x
        return o & ~a


@dataclass
class Edge:
    u: int
    v: int
    r: Fr
    mask: int                    # coordinates the kernel acts on (full mask d before absorption)

    def s(self):
        return bin(self.mask).count("1")


@dataclass
class Model:
    d: int
    blocks: dict                 # INTERNAL id (0..n-1, canonical) -> Block
    edges: list                  # Edge (internal ids)
    meta: dict = field(default_factory=dict)
    ext_ids: list = None         # internal id i <-> external id ext_ids[i]; a checked bijection (external ids may be negative / sparse)

    def __post_init__(self):
        if self.ext_ids is None:
            self.ext_ids = sorted(self.blocks)

    def ext(self, i):
        return self.ext_ids[i]

    def internal(self, e):
        try:
            return self._int_of[e]
        except AttributeError:
            self._int_of = {x: i for i, x in enumerate(self.ext_ids)}; return self._int_of[e]

    @staticmethod
    def from_json(obj):
        d = int(obj["d"])
        if not (1 <= d <= MAX_D):
            raise UnsupportedInput("d must be in 1..%d" % MAX_D)
        # canonical internal ids: external ids (any integers, negative or sparse) are sorted and relabelled 0..n-1; the map is kept and
        # published with every result (no signed-id string parsing anywhere: hyphenated keys only ever carry internal nonnegative ids)
        raw_ids = []
        for b in obj["blocks"]:
            x = b.get("id")
            if isinstance(x, bool) or not isinstance(x, int):
                raise UnsupportedInput("block id %r is not an integer" % (x,))
            raw_ids.append(x)
        if len(set(raw_ids)) != len(raw_ids):
            raise UnsupportedInput("duplicate block id %d" % next(x for x in raw_ids if raw_ids.count(x) > 1))
        ext_ids = sorted(raw_ids); int_of = {x: i for i, x in enumerate(ext_ids)}
        blocks = {}
        for b in obj["blocks"]:
            bid = int_of[b["id"]]
            rows, ws, seen = [], [], set()
            wlist = b.get("weights")
            if wlist is None:
                wlist = [1] * len(b["rows"])
            if len(wlist) != len(b["rows"]):
                raise UnsupportedInput("block %d: %d weights for %d rows (lengths must match; no silent truncation or defaults)" % (bid, len(wlist), len(b["rows"])))
            for x, w in zip(b["rows"], wlist):
                if isinstance(x, bool) or not isinstance(x, int):
                    raise UnsupportedInput("block %d: row %r is not an integer mask" % (bid, x))
                if not (0 <= x < (1 << d)):
                    raise UnsupportedInput("block %d: row %d outside [0, 2^d)" % (bid, x))
                if x in seen:
                    raise UnsupportedInput("block %d: duplicate row %d (combine rows before supplying the model)" % (bid, x))
                try:
                    w = Fr(w)
                except (ValueError, ZeroDivisionError, TypeError):
                    raise UnsupportedInput("block %d: weight %r is not a rational" % (bid, w))
                if w <= 0:
                    raise UnsupportedInput("block %d: non-positive weight %s" % (bid, w))
                seen.add(x); rows.append(x); ws.append(w)
            if not rows:
                raise UnsupportedInput("block %d has an empty support" % bid)
            den = 1
            for w in ws:
                den = den * w.denominator // np.gcd(den, w.denominator) if False else den * w.denominator // __import__("math").gcd(den, w.denominator)
            blocks[bid] = Block(bid, rows, [int(w * den) for w in ws])          # rational weights scaled to integers (a positive scalar)
        edges = []
        for e in obj["edges"]:
            if any(isinstance(e.get(k), bool) or not isinstance(e.get(k), int) for k in ("u", "v")):
                raise UnsupportedInput("edge endpoints must be integer block ids")
            if e["u"] not in int_of or e["v"] not in int_of:
                raise UnsupportedInput("edge (%d,%d) references an unknown block" % (e["u"], e["v"]))
            u, v = int_of[e["u"]], int_of[e["v"]]
            if u == v:
                raise UnsupportedInput("self-loop edge on block %d is not supported" % u)
            try:
                r = Fr(e["r"])
            except (ValueError, ZeroDivisionError, TypeError, KeyError):
                raise UnsupportedInput("edge (%d,%d): coupling %r is not a rational" % (u, v, e.get("r")))
            if not (0 <= r <= 1):
                raise UnsupportedInput("edge (%d,%d): coupling %s outside [0,1]" % (u, v, r))
            if e.get("kernel", "product") != "product":
                raise UnsupportedInput("edge (%d,%d): only the full-coordinate product kernel is supported" % (u, v))
            if "coordinate_map" in e:
                raise UnsupportedInput("coordinate maps between blocks are not supported in this first backend")
            edges.append(Edge(u, v, r, (1 << d) - 1))
        for k in obj:
            if k not in ("d", "blocks", "edges", "meta", "bit_convention", "name"):
                raise UnsupportedInput("unsupported top-level field %r" % k)
        meta = dict(obj.get("meta") or {})
        if meta.get("cluster_hints") is not None:                      # hints name EXTERNAL ids: mapped once here
            try:
                meta["cluster_hints"] = [[int_of[int(x)] for x in c] for c in meta["cluster_hints"]]
            except (KeyError, TypeError, ValueError):
                raise UnsupportedInput("cluster hints must be lists of existing block ids")
        return Model(d, blocks, edges, meta, ext_ids)

    @staticmethod
    def load(path):
        data = open(path, "rb").read()
        m = Model.from_json(json.loads(data)); m.meta["sha256"] = hashlib.sha256(data).hexdigest(); m.meta["path"] = path
        return m

    def validate(self):
        """Re-check a Model object supplied directly (not through from_json): same contract."""
        if not (1 <= self.d <= MAX_D):
            raise UnsupportedInput("d must be in 1..%d" % MAX_D)
        if sorted(self.blocks) != list(range(len(self.blocks))):
            raise UnsupportedInput("internal block ids must be canonical 0..n-1 (use Model.from_json for external ids)")
        if not (isinstance(self.ext_ids, list) and len(self.ext_ids) == len(self.blocks) and len(set(self.ext_ids)) == len(self.ext_ids)
                and all(isinstance(x, int) and not isinstance(x, bool) for x in self.ext_ids)):
            raise UnsupportedInput("external id map must be a bijection onto the blocks")
        for bid, b in self.blocks.items():
            if b.id != bid or not b.rows or len(b.rows) != len(b.w) or len(set(b.rows)) != len(b.rows):
                raise UnsupportedInput("block %s: inconsistent id / rows / weights or duplicate rows" % bid)
            if any((isinstance(x, bool) or not isinstance(x, int) or not (0 <= x < (1 << self.d))) for x in b.rows):
                raise UnsupportedInput("block %s: a row is not an integer mask in [0, 2^d)" % bid)
            if any((not isinstance(w, int) or isinstance(w, bool) or w <= 0) for w in b.w):
                raise UnsupportedInput("block %s: weights must be positive integers" % bid)
        for e in self.edges:
            try:
                e.r = Fr(e.r)
            except (ValueError, ZeroDivisionError, TypeError):
                raise UnsupportedInput("edge (%s,%s): coupling %r is not a rational" % (e.u, e.v, e.r))
            if e.u not in self.blocks or e.v not in self.blocks or e.u == e.v or not (0 <= e.r <= 1) or e.mask != (1 << self.d) - 1:
                raise UnsupportedInput("edge (%s,%s): unknown block, self-loop, coupling outside [0,1] or a non-full mask" % (e.u, e.v))
        return self

    def to_json(self):
        """External ids are restored (the canonical relabelling is invisible in the serialized form; sha256 is over this form)."""
        meta = {k: v for k, v in self.meta.items() if k not in ("sha256", "path")}
        if meta.get("cluster_hints") is not None:
            meta["cluster_hints"] = [[self.ext_ids[x] for x in c] for c in meta["cluster_hints"]]
        return {"d": self.d, "bit_convention": BIT_CONVENTION, "blocks": [{"id": self.ext_ids[b.id], "rows": list(b.rows), "weights": list(b.w)} for b in self.blocks.values()],
                "edges": [{"u": self.ext_ids[e.u], "v": self.ext_ids[e.v], "r": str(e.r)} for e in self.edges], "meta": meta}

    def sha256(self):
        return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ------------------------------------------------------------------ reductions
def fuse_parallel(r1, r2, d):
    """(A): K_r K_s = (1+rs)^d K_{(r+s)/(1+rs)}; returns (r, scalar)."""
    r1, r2 = Fr(r1), Fr(r2)
    return (r1 + r2) / (1 + r1 * r2), (1 + r1 * r2) ** d


@dataclass
class Reduced:
    d: int
    blocks: dict                 # reduced id -> Block (weights incl. absorbed exact tilts)
    edges: list                  # Edge with masks (coordinates varying on both endpoints)
    orig_to_red: dict            # original block id -> reduced block id
    members: dict                # reduced id -> list of original ids (hard component)
    log: list = field(default_factory=list)
    infeasible: dict | None = None
    scalars: list = field(default_factory=list)      # dropped positive scalars (as strings) -- irrelevant for marginals


def contract_hard(model: Model, deadline=None):
    """Stage 1+2 as a MODEL (full masks): hard components contracted, internal edges dropped as scalars, parallel edges fused by (A).
    Returns (Model, orig_to_red, members, log, scalars, infeasible). `deadline` (callable raising) is polled per block / edge loop."""
    red = _reduce(model, absorb=False, deadline=deadline)
    if red.infeasible:
        return None, red.orig_to_red, red.members, red.log, red.scalars, red.infeasible
    m2 = Model(model.d, {b: Block(b, list(blk.rows), list(blk.w)) for b, blk in red.blocks.items()}, [Edge(e.u, e.v, e.r, e.mask) for e in red.edges], dict(model.meta))
    return m2, red.orig_to_red, red.members, red.log, red.scalars, None


def reduce_model(model: Model, deadline=None) -> Reduced:
    return _reduce(model, absorb=True, deadline=deadline)


def _poll(deadline, counter):
    counter[0] += 1
    if deadline is not None and counter[0] % 64 == 0:
        deadline()


def _reduce(model: Model, absorb=True, deadline=None) -> Reduced:
    d = model.d; full = (1 << d) - 1
    log = []; scalars = []; _cnt = [0]
    # --- hard components (r = 1) by union-find
    parent = {b: b for b in model.blocks}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    hard = [e for e in model.edges if e.r == 1]
    for e in hard:
        a, b = find(e.u), find(e.v)
        if a != b:
            parent[max(a, b)] = min(a, b)
    comps = {}
    for b in model.blocks:
        comps.setdefault(find(b), []).append(b)
    blocks = {}; orig_to_red = {}; members = {}
    for root, mem in sorted(comps.items()):
        _poll(deadline, _cnt)
        mem = sorted(mem); rid = mem[0]
        for b in mem:
            orig_to_red[b] = rid
        members[rid] = mem
        if len(mem) == 1:
            blk = model.blocks[rid]; blocks[rid] = Block(rid, list(blk.rows), list(blk.w)); continue
        inter = set(model.blocks[mem[0]].rows)
        for b in mem[1:]:
            inter &= set(model.blocks[b].rows)
        if not inter:
            return Reduced(d, {}, [], orig_to_red, members, log, infeasible={"reason": "hard component %s has an empty support intersection: every configuration violates a hard equality, Z = 0" % mem, "component": mem})
        idx = {b: model.blocks[b].index() for b in mem}
        rows = sorted(inter); w = []
        for z in rows:
            p = 1
            for b in mem:
                p *= model.blocks[b].w[idx[b][z]]
            w.append(p)
        blocks[rid] = Block(rid, rows, w)
        log.append({"hard_component": mem, "intersection_rows": len(rows), "scalar_per_hard_edge": "2^%d" % d})
    # --- re-point edges, drop internal ones (hard edges: scalar 2^d each incl. redundant cycle edges; soft internal edges: K_r(z,z) = (1+r)^d scalar)
    pend = {}
    for e in model.edges:
        a, b = orig_to_red[e.u], orig_to_red[e.v]
        if a == b:
            scalars.append("2^%d" % d if e.r == 1 else "(1+%s)^%d" % (e.r, d)); continue
        key = (min(a, b), max(a, b))
        pend.setdefault(key, []).append(e.r)
    edges = []
    for (a, b), rs in sorted(pend.items()):
        r = rs[0]
        for s in rs[1:]:
            r, sc = fuse_parallel(r, s, d); scalars.append(str(sc))
        if len(rs) > 1:
            log.append({"parallel_edges_fused": [a, b], "couplings": [str(x) for x in rs], "fused_r": str(r)})
        edges.append(Edge(a, b, r, full))
    if not absorb:
        return Reduced(d, blocks, edges, orig_to_red, members, log, None, scalars)
    # --- separable coordinates: constant on one side -> exact unary tilt on the other; constant on both -> scalar; none varying on both -> edge removed
    vary = {rid: blk.varying_mask() for rid, blk in blocks.items()}
    const_val = {}
    for rid, blk in blocks.items():
        const_val[rid] = blk.rows[0] & ~vary[rid]           # the constant bits' values
    out_edges = []
    for e in edges:
        _poll(deadline, _cnt)
        if e.r == 0:
            log.append({"edge_removed": [e.u, e.v], "reason": "r = 0 (constant kernel)"}); continue
        both = vary[e.u] & vary[e.v]
        only_u = vary[e.u] & ~vary[e.v]; only_v = vary[e.v] & ~vary[e.u]; neither = full & ~vary[e.u] & ~vary[e.v]
        u_, v_ = e.r.numerator, e.r.denominator
        for side, other, m in ((e.u, e.v, only_u), (e.v, e.u, only_v)):
            if m:
                blk = blocks[side]; cvals = const_val[other]
                newws = []
                for x, w in zip(blk.rows, blk.w):
                    f = 1
                    for j in range(d):
                        if (m >> j) & 1:
                            xj = 1 if (x >> j) & 1 else -1; cj = 1 if (cvals >> j) & 1 else -1
                            f *= (v_ + u_ * xj * cj)
                    newws.append(w * f)
                blocks[side] = Block(blk.id, blk.rows, newws); scalars.append("1/%d^%d" % (v_, bin(m).count("1")))
                log.append({"absorbed_unary": {"edge": [e.u, e.v], "into_block": side, "coordinates": bin(m).count("1")}})
        if neither:
            scalars.append("prod over %d constant-constant coordinates of (1 + r c_u c_v)" % bin(neither).count("1"))
        if both:
            out_edges.append(Edge(e.u, e.v, e.r, both))
        else:
            log.append({"edge_removed": [e.u, e.v], "reason": "no coordinate varies on both endpoint supports (separable)"})
    return Reduced(d, blocks, out_edges, orig_to_red, members, log, None, scalars)


def adjacency(red: Reduced):
    adj = {b: {} for b in red.blocks}
    for e in red.edges:
        adj[e.u][e.v] = e; adj[e.v][e.u] = e
    return adj


def components(red: Reduced):
    adj = adjacency(red); seen = set(); comps = []
    for b in red.blocks:
        if b in seen:
            continue
        stack = [b]; comp = []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x); stack.extend(adj[x])
        comps.append(sorted(comp))
    return comps


def is_forest(red: Reduced):
    comps = components(red)
    return len(red.edges) == len(red.blocks) - len(comps)
