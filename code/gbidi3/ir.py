"""Canonical indexed IR of GENERAL_BIDI_COMPLETE_V3 (brief §3, §4, §6) and its COVERAGE calculus.

A node is an indexed nonnegative polynomial in the original-state markers. Kinds (kernel3.cpp executes exactly these):
  SOURCE(fid)             exact source-factor occurrence (or a DERIVED table bound to an occurrence by a checked finite identity); axes = its scope
  MARKER(var)             the reduced variable's marker lambda_(var, state): value 1 at every state, pullback -> N[var][state]
  CONSTANT(value)         explicitly bound nonnegative rational; the ONLY constant a V3 program may contain is the trusted scale (checked)
  GATHER(child, gaxes)    total bounds-checked coordinate map: permutation / broadcast of axes and response-class expansion (cls map + exact ratio)
  ADD(children)           pointwise sum of aligned nodes with identical coverage (alternative evaluations of one polynomial, e.g. a checked source split)
  MUL(children, proj)     pointwise product with explicit per-child axis projection onto the output axes
  REDUCE(child, map, reps) sum over the eliminated child axes; the kept axes keep their order; a kept axis may be COMPRESSED: its output index is a class
                          of raw states read at the class REPRESENTATIVE (reps map), consumers expand it through GATHER(cls, ratio)
LINEAR is lowered to GATHER/MUL/REDUCE; REGION (general conditioning, brief §10) is lowered to REDUCE over the cutset of MUL(markers of the cutset,
fully instantiated factors, one sub-DAG per residual component): gbidi3.planner builds it, this module only represents and checks it.

COVERAGE (what makes "P is preserved AS A POLYNOMIAL" finitely checkable): every node carries
  A  free axes (reduced variable ids, in axis order; a compressed axis is (var, class count)),
  O  the SET of source occurrence ids it multiplies (a derived split table counts as its parent occurrence; "SCALE" is the trusted scale),
  M  the set of variables whose marker it has multiplied in,
  E  the set of variables summed out inside it.
Rules: SOURCE A=scope O={fid}; MARKER A={v} M={v}; CONSTANT O={SCALE}; GATHER inherits O/M/E (broadcast axes add free axes, class expansion needs the
child's reps witness on that axis); ADD children have identical (A, O, M, E); MUL children have pairwise disjoint O, M, E and no child eliminates a variable
another child mentions (E_i disjoint from A_j, E_j); REDUCE eliminates X subset of A(child) with X subset of M(child) (a marker must be multiplied in before its
variable is summed out), A = A(child) minus X, E = E(child) + X. A root is scalar; the roots' O / M / E are disjoint and together cover every trusted
occurrence + SCALE, and every reduced variable (markers and eliminations). By induction each node equals the sum over its eliminated variables of the
product of its covered occurrences and markers, each exactly once (proof note P1/P2/P7 of the brief)."""
from __future__ import annotations
from fractions import Fraction as Fr

SOURCE, MARKER, CONSTANT, GATHER, ADD, MUL, REDUCE = "SOURCE", "MARKER", "CONSTANT", "GATHER", "ADD", "MUL", "REDUCE"
KIND_CODE = {SOURCE: 0, MARKER: 1, CONSTANT: 2, GATHER: 3, ADD: 4, MUL: 5, REDUCE: 6}
STREAM, DENSE, SPARSE, CACHE = "STREAM", "DENSE", "SPARSE", "CACHE"
STORAGE_CODE = {STREAM: 0, DENSE: 1, SPARSE: 2, CACHE: 3}
SCALE = "SCALE"
INT64_MAX = (1 << 63) - 1


class IRError(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


def prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


class Node:
    """immutable semantic identity (nid, kind, axes, card, children, payload) + mutable storage decision (storage, demand) + provenance"""
    __slots__ = ("nid", "kind", "axes", "card", "children", "fid", "var", "value", "gaxes", "proj", "rmap", "reps", "storage", "demand", "prov", "witness", "notes", "cost", "driver")

    def __init__(self, nid, kind, axes, card, children=(), fid=None, var=None, value=None, gaxes=None, proj=None, rmap=None, reps=None, storage=STREAM, demand="FULL", prov=None, witness=None, driver=-1):
        self.nid = nid; self.kind = kind; self.axes = tuple(axes); self.card = tuple(int(c) for c in card); self.children = tuple(children); self.fid = fid; self.var = var; self.value = value
        self.gaxes = gaxes; self.proj = proj; self.rmap = rmap; self.reps = reps; self.storage = storage; self.demand = demand; self.prov = prov or {}; self.witness = witness; self.notes = []; self.cost = None
        self.driver = int(driver) if driver is not None else -1                        # SPARSE REDUCE only: the MUL operand index that DRIVES the join (the planner's priced choice under SPARSE_DRIVER_POLICY), -1 = policy at run time
        if len(self.axes) != len(self.card) or any(c < 1 for c in self.card):
            raise IRError("node %d: axes / cardinalities malformed" % nid)
        if prod(self.card) > INT64_MAX:
            raise IRError("node %d: volume exceeds int64 (symbolic domain too large for an indexed route)" % nid)
        nch = len(self.children)
        if (kind in (SOURCE, MARKER, CONSTANT) and nch != 0) or (kind in (GATHER, REDUCE) and nch != 1) or (kind in (ADD, MUL) and nch < 1):
            raise IRError("node %d: %s with %d children" % (nid, kind, nch))

    @property
    def volume(self):
        return prod(self.card)

    def __repr__(self):
        return "Node(%d,%s,axes=%s,card=%s,children=%s,%s)" % (self.nid, self.kind, self.axes, self.card, self.children, self.storage)


class Program:
    """nodes in topological order (every child precedes its consumers); roots are scalar nodes whose product is Z"""
    def __init__(self):
        self.nodes = []; self.roots = []; self.derived = {}       # derived[fid] = (parent_fid, table) for checked split tables (SOURCE nodes may reference them)

    def add(self, kind, axes, card, **kw):
        n = Node(len(self.nodes), kind, axes, card, **kw)
        for c in n.children:
            if not (0 <= c < n.nid):
                raise IRError("node %d: child %d does not precede it" % (n.nid, c))
        self.nodes.append(n); return n

    def source(self, fid, scope, card, **kw):
        return self.add(SOURCE, scope, card, fid=fid, **kw)

    def marker(self, var, card, **kw):
        return self.add(MARKER, (var,), (card,), var=var, **kw)

    def constant(self, value, **kw):
        return self.add(CONSTANT, (), (), value=Fr(value), **kw)

    def gather(self, child, axes, card, gaxes, **kw):
        """gaxes: per CHILD axis a dict {out_pos: int|-1, fixed: int, cls: tuple|None, ratio: tuple|None}"""
        return self.add(GATHER, axes, card, children=(child.nid,), gaxes=tuple(gaxes), **kw)

    def addn(self, children, **kw):
        c0 = children[0]
        return self.add(ADD, c0.axes, c0.card, children=tuple(c.nid for c in children), **kw)

    def mul(self, children, axes=None, card=None, **kw):
        """output axes = union of the children's axes in first-appearance order unless given; proj derived from variable identity"""
        if axes is None:
            axes = []; cards = {}
            for c in children:
                for a, k in zip(c.axes, c.card):
                    if a not in cards:
                        axes.append(a); cards[a] = k
                    elif cards[a] != k:
                        raise IRError("MUL: axis %s with cardinalities %d and %d" % (a, cards[a], k))
            card = [cards[a] for a in axes]
        pos = {a: i for i, a in enumerate(axes)}
        proj = tuple(tuple(pos[a] for a in c.axes) for c in children)
        return self.add(MUL, axes, card, children=tuple(c.nid for c in children), proj=proj, **kw)

    def reduce(self, child, elim, reps=None, **kw):
        """elim: set of child axes (variables) to sum out; reps: optional {axis: (reps tuple, cls tuple, ratio tuple)} compression of kept axes"""
        elim = set(elim); axes = []; card = []; rmap = []; rp = []
        for a, k in zip(child.axes, child.card):
            if a in elim:
                rmap.append(-1); rp.append(None)
            else:
                rmap.append(len(axes)); axes.append(a)
                if reps and a in reps:
                    card.append(len(reps[a][0])); rp.append(reps[a])
                else:
                    card.append(k); rp.append(None)
        if len(elim) != sum(1 for r in rmap if r < 0):
            raise IRError("REDUCE: eliminated axis not in the child")
        return self.add(REDUCE, axes, card, children=(child.nid,), rmap=tuple(rmap), reps=tuple(rp), **kw)


    def consumers(self):
        """nid -> list of (consumer nid, child position)"""
        cons = {n.nid: [] for n in self.nodes}
        for n in self.nodes:
            for i, c in enumerate(n.children):
                cons[c].append((n.nid, i))
        return cons



SPARSE_DRIVER_POLICY = ("candidates = every SOURCE operand of the MUL (support = its nonzero entries, scanned) and every operand that is a COMPLETE sparse node (support = its retained rows); "
                        "cost(candidate) = support x product of the cardinalities of the MUL axes the candidate does NOT cover (= the joined rows the kernel visits, rejected zero products included); "
                        "choose the minimal cost, ties -> the lowest operand index; the planner prices exactly this quantity and writes its choice into REDUCE.driver; the kernel executes the written "
                        "driver when that operand's support is available at run time, otherwise it applies the same policy to the available candidates and counts sparse_driver_deviation (a resource "
                        "downgrade of a planned sparse child is the only cause); when the written driver is available but the run-time policy would prefer another operand (the planner's child support was "
                        "an estimate) the written driver is still executed and sparse_driver_policy_differs is counted")


def sparse_driver_cost(mul_card, operand_proj, support):
    """joined rows visited when `operand` drives the join: support x volume of the MUL axes it leaves free"""
    covered = set(operand_proj); free = 1
    for p, c in enumerate(mul_card):
        if p not in covered:
            free *= c
    return support * free


# ---------------------------------------------------------------------------------------------------------------- local semantics (unconditional, every program)
def local_semantics(P, dom, tick=lambda n=1: None):
    """Complete LOCAL kind / type / map validation of every node of an UNTRUSTED proposal, independent of any global coverage route (review R1a).
    Checks every mutable field: kind, children (ints, precede the node, arity per kind), axes (reduced variables, distinct), cardinalities (positive ints;
    = reduced domain unless the axis is a compressed REDUCE output), storage / demand, MUL projections (total, injective, child.axes[k] == axes[proj[k]]
    with equal cardinality), REDUCE maps (kept axes a bijection onto the output with child.axes[k] == axes[rmap[k]]; cardinality equal or compressed
    through a representative map of the output size), GATHER descriptors (one per child axis, out_pos in range and distinct, n.axes[out_pos] ==
    child.axes[k]; identity axes have equal cardinality and NO ratio or an all-one ratio of the exact size; class maps need a ratio of the exact size),
    ADD operands aligned. Raises IRError with the node id and the violated rule."""
    for pos, n in enumerate(P.nodes):
        if not isinstance(n, Node) or n.nid != pos:
            raise IRError("node %d: ids are not positional" % pos)
        if n.kind not in KIND_CODE:
            raise IRError("node %d: unknown kind %r" % (n.nid, n.kind))
        if not isinstance(n.children, tuple) or any(not isinstance(c, int) or isinstance(c, bool) or not (0 <= c < n.nid) for c in n.children):
            raise IRError("node %d: children must be node ids that precede it" % n.nid)
        nch = len(n.children)
        if (n.kind in (SOURCE, MARKER, CONSTANT) and nch != 0) or (n.kind in (GATHER, REDUCE) and nch != 1) or (n.kind in (ADD, MUL) and nch < 1):
            raise IRError("node %d: %s with %d children" % (n.nid, n.kind, nch))
        if not isinstance(n.axes, tuple) or not isinstance(n.card, tuple) or len(n.axes) != len(n.card) or len(set(n.axes)) != len(n.axes):
            raise IRError("node %d: axes / cardinalities malformed" % n.nid)
        if any(not isinstance(c, int) or isinstance(c, bool) or c < 1 for c in n.card):
            raise IRError("node %d: cardinalities must be positive ints" % n.nid)
        if prod(n.card) > INT64_MAX:
            raise IRError("node %d: volume exceeds int64" % n.nid)
        if n.storage not in STORAGE_CODE:
            raise IRError("node %d: unknown storage" % n.nid)
        for k, (a, c) in enumerate(zip(n.axes, n.card)):
            if a not in dom:
                raise IRError("node %d: axis %s is not a reduced variable" % (n.nid, a))
            compressed = n.kind == REDUCE and n.reps is not None and any(r is not None and n.rmap[i] == k for i, r in enumerate(n.reps))
            if not compressed and c != len(dom[a]):
                raise IRError("node %d: axis %s has cardinality %d but the reduced domain has %d" % (n.nid, a, c, len(dom[a])))
        if n.kind == SOURCE:
            pass
        elif n.kind == MARKER:
            if n.var not in dom or n.axes != (n.var,) or n.card != (len(dom[n.var]),):
                raise IRError("node %d: MARKER malformed" % n.nid)
        elif n.kind == CONSTANT:
            if n.axes:
                raise IRError("node %d: CONSTANT must be scalar" % n.nid)
        elif n.kind == GATHER:
            child = P.nodes[n.children[0]]
            if not isinstance(n.gaxes, tuple) or len(n.gaxes) != len(child.axes):
                raise IRError("node %d: GATHER needs exactly one descriptor per child axis" % n.nid)
            seen = set()
            for k, g in enumerate(n.gaxes):
                if not isinstance(g, dict) or not isinstance(g.get("out_pos"), int) or isinstance(g.get("out_pos"), bool):
                    raise IRError("node %d: gather descriptor malformed" % n.nid)
                op = g["out_pos"]
                if not (0 <= op < len(n.axes)) or op in seen:
                    raise IRError("node %d: gather out_pos out of range or repeated" % n.nid)
                seen.add(op)
                if n.axes[op] != child.axes[k]:
                    raise IRError("node %d: gather axis %d reads variable %s but child axis %d is %s" % (n.nid, op, n.axes[op], k, child.axes[k]))
                extra = set(g) - {"out_pos", "cls", "ratio", "fixed"}
                if extra:
                    raise IRError("node %d: unknown gather fields %s" % (n.nid, sorted(extra)))
                if g.get("fixed") not in (None, 0):
                    raise IRError("node %d: fixed-slice gathers are not accepted" % n.nid)
                cls = g.get("cls"); ratio = g.get("ratio")
                if cls is None:
                    if n.card[op] != child.card[k]:
                        raise IRError("node %d: identity gather axis %s cardinality %d != %d" % (n.nid, n.axes[op], n.card[op], child.card[k]))
                    if ratio is not None and (len(ratio) != n.card[op] or any(Fr(r) != 1 for r in ratio)):
                        raise IRError("node %d: an identity gather carries a non-unit weight on axis %s (unproved coefficient)" % (n.nid, n.axes[op]))
                else:
                    if len(cls) != n.card[op] or any(not isinstance(x, int) or isinstance(x, bool) or not (0 <= x < child.card[k]) for x in cls):
                        raise IRError("node %d: class map of axis %s malformed" % (n.nid, n.axes[op]))
                    if ratio is None or len(ratio) != n.card[op] or any(Fr(r) < 0 for r in ratio):
                        raise IRError("node %d: class ratios of axis %s malformed" % (n.nid, n.axes[op]))
            if len(n.axes) != len(n.gaxes):
                raise IRError("node %d: gather output axes must be exactly the child axes (no broadcast in this round)" % n.nid)
        elif n.kind == ADD:
            for ch in n.children:
                c = P.nodes[ch]
                if c.axes != n.axes or c.card != n.card:
                    raise IRError("node %d: ADD operand %d is not aligned" % (n.nid, ch))
        elif n.kind == MUL:
            if not isinstance(n.proj, tuple) or len(n.proj) != len(n.children):
                raise IRError("node %d: MUL projections malformed" % n.nid)
            covered = set()
            for ci, ch in enumerate(n.children):
                c = P.nodes[ch]; pr = n.proj[ci]
                if not isinstance(pr, tuple) or len(pr) != len(c.axes) or len(set(pr)) != len(pr) or any(not isinstance(x, int) or isinstance(x, bool) or not (0 <= x < len(n.axes)) for x in pr):
                    raise IRError("node %d: operand %d projection is not a total injective map into the output axes" % (n.nid, ci))
                for k, x in enumerate(pr):
                    if n.axes[x] != c.axes[k] or n.card[x] != c.card[k]:
                        raise IRError("node %d: operand %d axis %d (%s, %d) is mapped to output axis %d (%s, %d)" % (n.nid, ci, k, c.axes[k], c.card[k], x, n.axes[x], n.card[x]))
                covered |= set(pr)
            if covered != set(range(len(n.axes))):
                raise IRError("node %d: output axis not produced by any operand" % n.nid)
        elif n.kind == REDUCE:
            c = P.nodes[n.children[0]]
            if not isinstance(n.rmap, tuple) or not isinstance(n.reps, tuple) or len(n.rmap) != len(c.axes) or len(n.reps) != len(c.axes):
                raise IRError("node %d: REDUCE maps malformed" % n.nid)
            kept = [r for r in n.rmap if r != -1]
            if sorted(kept) != list(range(len(n.axes))) or any(not isinstance(r, int) or isinstance(r, bool) or r < -1 for r in n.rmap):
                raise IRError("node %d: REDUCE kept axes are not a bijection onto the output" % n.nid)
            drv = getattr(n, "driver", -1)
            if not isinstance(drv, int) or isinstance(drv, bool) or drv < -1 or (drv >= 0 and (c.kind != MUL or drv >= len(c.children))):
                raise IRError("node %d: sparse driver %r is not an operand index of the MUL child" % (n.nid, drv))
            if drv >= 0 and n.storage != SPARSE:
                raise IRError("node %d: a sparse driver is declared on a non-SPARSE REDUCE" % n.nid)
            for k, r in enumerate(n.rmap):
                if r < 0:
                    if n.reps[k] is not None:
                        raise IRError("node %d: representative map on an eliminated axis" % n.nid)
                    continue
                if n.axes[r] != c.axes[k]:
                    raise IRError("node %d: kept axis %d is variable %s but the child axis is %s" % (n.nid, r, n.axes[r], c.axes[k]))
                rep = n.reps[k]
                if rep is None:
                    if n.card[r] != c.card[k]:
                        raise IRError("node %d: kept axis %s cardinality mismatch" % (n.nid, c.axes[k]))
                else:
                    if not isinstance(rep, tuple) or len(rep) != 3 or len(rep[0]) != n.card[r] or len(rep[1]) != c.card[k] or len(rep[2]) != c.card[k] or any(not isinstance(x, int) or isinstance(x, bool) or not (0 <= x < c.card[k]) for x in rep[0]):
                        raise IRError("node %d: representative map of axis %s malformed" % (n.nid, c.axes[k]))
        tick()
    if not isinstance(P.roots, list) or any(not isinstance(r, int) or isinstance(r, bool) or not (0 <= r < len(P.nodes)) for r in P.roots) or len(set(P.roots)) != len(P.roots):
        raise IRError("roots malformed or duplicated")
    for r in P.roots:
        if P.nodes[r].axes:
            raise IRError("root %d is not scalar" % r)


def coordinate_domains(P, dom):
    """COORDINATE-DOMAIN typing of every axis of every node (review F1 / A2): an axis is in RAW space (coordinates = reduced states of the variable) or in a
    CLASS space identified by the exact (representatives, class map, ratio) witness of the REDUCE that compressed it. The type of each output axis is derived
    from the operands: SOURCE / MARKER axes are RAW; a REDUCE output axis is the class space of its witness if compressed, else its child's type; a GATHER with
    a class map on an axis EXPANDS that axis to RAW (the map must equal the child's class space witness exactly; an identity gather keeps the child's type);
    a MUL output axis takes the type of its operands, which must all AGREE (raw-with-raw or the identical class space; a raw MARKER / SOURCE multiplied
    against a class-space axis is the F1 defect); ADD operands must agree axis by axis. A trivial witness (identity representatives, identity class map,
    all-one ratios) is normalized to RAW. Returns {nid: tuple(type per axis)} where a type is "RAW" or ("CLS", reps, cls, ratio); raises IRError."""
    T = {}
    def canon(rep):
        reps, cls, ratio = tuple(int(x) for x in rep[0]), tuple(int(x) for x in rep[1]), tuple(Fr(x) for x in rep[2])
        if reps == tuple(range(len(cls))) and cls == tuple(range(len(cls))) and all(q == 1 for q in ratio):
            return "RAW"                                                                       # proved trivial identity map: raw coordinates
        return ("CLS", reps, cls, ratio)
    for n in P.nodes:
        if n.kind in (SOURCE, MARKER):
            T[n.nid] = tuple("RAW" for _ in n.axes)
        elif n.kind == CONSTANT:
            T[n.nid] = ()
        elif n.kind == REDUCE:
            ct = T[n.children[0]]; out = [None] * len(n.axes)
            for k, r in enumerate(n.rmap):
                if r < 0:
                    if ct[k] != "RAW":
                        raise IRError("node %d: eliminates axis %s in CLASS coordinates (an eliminated axis must be raw: its marker lives in raw space)" % (n.nid, P.nodes[n.children[0]].axes[k]))
                    continue
                if n.reps[k] is not None:
                    if ct[k] != "RAW":
                        raise IRError("node %d: compresses axis %s that is already in CLASS coordinates (nested compression is not a proved witness)" % (n.nid, P.nodes[n.children[0]].axes[k]))
                    out[r] = canon(n.reps[k])
                else:
                    out[r] = ct[k]
            T[n.nid] = tuple(out)
        elif n.kind == GATHER:
            ct = T[n.children[0]]; out = [None] * len(n.axes)
            for k, g in enumerate(n.gaxes):
                op = g["out_pos"]
                if g.get("cls") is not None:
                    if ct[k] == "RAW":
                        raise IRError("node %d: class-expanding gather on axis %s whose child coordinates are already raw" % (n.nid, n.axes[op]))
                    _, reps, cls, ratio = ct[k]
                    if tuple(int(x) for x in g["cls"]) != cls or tuple(Fr(x) for x in g["ratio"]) != ratio:
                        raise IRError("node %d: gather axis %s does not expand exactly the class space of its child (witness mismatch)" % (n.nid, n.axes[op]))
                    out[op] = "RAW"
                else:
                    out[op] = ct[k]                                                             # identity reindexing keeps the coordinate domain (raw stays raw, class stays class)
            T[n.nid] = tuple(out)
        elif n.kind == ADD:
            t0 = T[n.children[0]]
            for ch in n.children[1:]:
                if T[ch] != t0:
                    raise IRError("node %d: ADD operands disagree in coordinate domains (raw vs class space on some axis)" % n.nid)
            T[n.nid] = t0
        elif n.kind == MUL:
            out = [None] * len(n.axes)
            for ci, ch in enumerate(n.children):
                ct = T[ch]
                for k, x in enumerate(n.proj[ci]):
                    if out[x] is None:
                        out[x] = ct[k]
                    elif out[x] != ct[k]:
                        raise IRError("node %d: operand %d reads axis %s in %s coordinates but another operand uses %s coordinates (a class-space message consumed as raw states)" % (n.nid, ci, n.axes[x], "RAW" if ct[k] == "RAW" else "CLASS", "RAW" if out[x] == "RAW" else "CLASS"))
            T[n.nid] = tuple(out)
        else:
            raise IRError("node %d: unknown kind" % n.nid)
    for r in P.roots:
        if any(t != "RAW" for t in T[r]):
            raise IRError("root %d carries a class-space axis" % r)
    return T


def marked_axes_below(P):
    """marked_axes_below[nid] = the variables that are AXES of node nid and whose MARKER occurs inside its subtree (a marker, once multiplied in, stays an
    axis until the REDUCE that eliminates it; after that no node above mentions the variable, enforced by the coverage rules). Linear in the total arity of
    the program (a set of size <= len(axes) per node), unlike a per-node set of ALL markers below, which is quadratic on a deep chain."""
    below = {}
    for n in P.nodes:
        if n.kind == MARKER:
            s = frozenset((n.var,))
        elif n.kind == REDUCE:
            kept = set(n.axes); s = frozenset(v for v in below[n.children[0]] if v in kept)
        else:
            s = frozenset()
            for c in n.children:
                s |= below[c]
            if n.kind != ADD:
                s = frozenset(v for v in s if v in set(n.axes)) if n.kind == GATHER else s
        below[n.nid] = s
    return below


# ---------------------------------------------------------------------------------------------------------------- coverage calculus
class Coverage:
    __slots__ = ("A", "O", "M", "E")

    def __init__(self, A, O, M, E):
        self.A = tuple(A); self.O = frozenset(O); self.M = frozenset(M); self.E = frozenset(E)

    def same(self, other):
        return self.A == other.A and self.O == other.O and self.M == other.M and self.E == other.E


def coverage(P, occurrence_of_derived=None, additive_parent=None):
    """compute the coverage of every node; raises IRError on a violated rule. occurrence_of_derived maps a derived fid to the occurrence atom it stands
    for (a product-split part is its own atom; an additive-split part keeps its own id as atom); additive_parent maps an additive part id to its parent."""
    occ = occurrence_of_derived or {}; cov = {}; additive_parent = additive_parent or {}; additive_parts = {}
    for part, par in additive_parent.items():
        additive_parts.setdefault(par, set()).add(part)
    for n in P.nodes:
        if n.kind == SOURCE:
            cov[n.nid] = Coverage(n.axes, {occ.get(n.fid, n.fid)}, (), ())
        elif n.kind == MARKER:
            if n.axes != (n.var,):
                raise IRError("node %d: marker axes %s != (%s,)" % (n.nid, n.axes, n.var))
            cov[n.nid] = Coverage(n.axes, (), {n.var}, ())
        elif n.kind == CONSTANT:
            cov[n.nid] = Coverage((), {SCALE}, (), ())
        elif n.kind == GATHER:
            c = cov[n.children[0]]
            cov[n.nid] = Coverage(n.axes, c.O, c.M, c.E)                  # local map semantics are enforced by local_semantics()
        elif n.kind == ADD:
            cs = [cov[c] for c in n.children]
            for ch in n.children:
                if P.nodes[ch].axes != n.axes or P.nodes[ch].card != n.card:
                    raise IRError("node %d: ADD operand %d is not aligned" % (n.nid, ch))
            for c in cs[1:]:
                if c.A != cs[0].A or c.M != cs[0].M or c.E != cs[0].E:
                    raise IRError("node %d: ADD operands differ in axes / markers / eliminations" % n.nid)
            # the operands' occurrence sets must differ EXACTLY by the distinct additive parts of ONE parent occurrence, all parts present once
            common = frozenset.intersection(*[c.O for c in cs]); diffs = [c.O - common for c in cs]
            if any(len(d) != 1 for d in diffs):
                raise IRError("node %d: ADD operands must differ by exactly one additive part each (identical operands would double a polynomial)" % n.nid)
            parts = [next(iter(d)) for d in diffs]; parents = {additive_parent.get(p) for p in parts}
            if None in parents or len(parents) != 1 or len(set(parts)) != len(parts) or set(parts) != additive_parts[next(iter(parents))]:
                raise IRError("node %d: ADD operands are not the complete set of additive parts of one source occurrence" % n.nid)
            cov[n.nid] = Coverage(n.axes, common | {next(iter(parents))}, cs[0].M, cs[0].E)
        elif n.kind == MUL:
            O = set(); M = set(); E = set(); mentioned = []
            for i, ch in enumerate(n.children):
                c = cov[ch]; child = P.nodes[ch]
                if O & c.O:
                    raise IRError("node %d: occurrence %s multiplied twice (operand %d)" % (n.nid, sorted(O & c.O, key=str)[0], i))
                if M & c.M:
                    raise IRError("node %d: marker of variable %s multiplied twice (operand %d)" % (n.nid, sorted(M & c.M)[0], i))
                if E & c.E:
                    raise IRError("node %d: variable %s eliminated in two operands" % (n.nid, sorted(E & c.E)[0]))
                O |= c.O; M |= c.M; E |= c.E; mentioned.append((set(c.A) | c.E | c.M))
                if len(n.proj[i]) != len(child.axes) or any(n.axes[n.proj[i][k]] != child.axes[k] or n.card[n.proj[i][k]] != child.card[k] for k in range(len(child.axes))):
                    raise IRError("node %d: operand %d projection does not match its axes" % (n.nid, i))
            for i, ch in enumerate(n.children):
                for j, ch2 in enumerate(n.children):
                    if i != j and (cov[ch].E & mentioned[j]):
                        raise IRError("node %d: variable %s eliminated in operand %d is mentioned by operand %d" % (n.nid, sorted(cov[ch].E & mentioned[j])[0], i, j))
            if any(E & set(n.axes)):
                raise IRError("node %d: an eliminated variable is a free axis" % n.nid)
            cov[n.nid] = Coverage(n.axes, O, M, E)
        elif n.kind == REDUCE:
            c = cov[n.children[0]]; child = P.nodes[n.children[0]]; X = set()
            for k, r in enumerate(n.rmap):
                if r < 0:
                    X.add(child.axes[k])
                elif n.axes[r] != child.axes[k]:
                    raise IRError("node %d: reduce keeps axis %d as variable %s but the child axis is %s" % (n.nid, r, n.axes[r], child.axes[k]))
                elif n.reps[k] is None and n.card[r] != child.card[k]:
                    raise IRError("node %d: kept axis %s cardinality mismatch" % (n.nid, child.axes[k]))
                elif n.reps[k] is not None and (len(n.reps[k][0]) != n.card[r] or any(not (0 <= x < child.card[k]) for x in n.reps[k][0])):
                    raise IRError("node %d: representative map of axis %s malformed" % (n.nid, child.axes[k]))
            if not X <= c.M:
                raise IRError("node %d: variable %s is summed out before its marker was multiplied in" % (n.nid, sorted(X - c.M)[0]))
            cov[n.nid] = Coverage(n.axes, c.O, c.M, c.E | X)
        else:
            raise IRError("node %d: unknown kind %s" % (n.nid, n.kind))
    return cov


def check_roots(P, cov, all_occurrences, all_vars):
    """the roots' coverages are disjoint and together cover every occurrence (+SCALE) and every reduced variable's marker and elimination"""
    O = set(); M = set(); E = set()
    for r in P.roots:
        n = P.nodes[r]; c = cov[r]
        if n.axes:
            raise IRError("root %d is not scalar" % r)
        if O & c.O or M & c.M or E & c.E:
            raise IRError("roots overlap in coverage")
        O |= c.O; M |= c.M; E |= c.E
    want = set(all_occurrences) | {SCALE}
    if O != want:
        missing = want - O; extra = O - want
        raise IRError("roots cover occurrences %s; missing %s extra %s" % (sorted(O, key=str)[:8], sorted(missing, key=str)[:8], sorted(extra, key=str)[:8]))
    if M != set(all_vars) or E != set(all_vars):
        raise IRError("roots do not cover every reduced variable's marker and elimination (markers missing %s, eliminations missing %s)" % (sorted(set(all_vars) - M)[:8], sorted(set(all_vars) - E)[:8]))
    return True


# ---------------------------------------------------------------------------------------------------------------- flat serialization for kernel3 (consumes a Validated object only)
def program_bytes_bound(P):
    """host bytes of one copy of program P (nodes, axis tuples, projections, maps, demand lists, derived witnesses) from metadata only"""
    b = 1024 + 64 * len(P.roots)
    for n in P.nodes:
        b += 1024 + 48 * (len(n.axes) + len(n.card)) + 16 * len(n.children)
        if n.kind == MUL:
            b += 16 * sum(len(pr) for pr in n.proj)
        elif n.kind == REDUCE:
            b += 16 * len(n.rmap) + sum(96 + 24 * len(r[0]) + 24 * len(r[1]) + 160 * len(r[2]) for r in n.reps if r is not None)
        elif n.kind == GATHER:
            b += sum(160 + (24 * len(g["cls"]) if g.get("cls") is not None else 0) + (160 * len(g["ratio"]) if g.get("ratio") is not None else 0) for g in n.gaxes)
        if isinstance(n.demand, (list, tuple)):
            b += 40 * len(n.demand)
        if n.prov:
            b += 400
    for d in (P.derived or {}).values():
        b += 400 + 160 * sum(len(t) for t in (d.get("parts") or [])) + 160 * (len(d.get("u") or ()) + len(d.get("g") or ()))
    return b


def flatten_bytes_bound(V):
    """upper bound on the host bytes of flatten(V) + the ctypes arrays built from it (computed from metadata BEFORE anything is built)"""
    T = V.T; P = V.P; words = 4 + T.nvars_reduced + 2
    for fid in V.factor_order:
        words += 4 + len(V.scopes[fid])
    for n in P.nodes:
        words += 8 + 2 * len(n.axes) + len(n.children) + (len(n.demand) if isinstance(n.demand, (list, tuple)) else 0)
        if n.kind == GATHER:
            words += 4 * len(n.gaxes) + sum(2 * len(g["cls"]) for g in n.gaxes if g.get("cls") is not None)
        elif n.kind == MUL:
            words += sum(len(pr) for pr in n.proj)
        elif n.kind == REDUCE:
            words += 2 * len(n.rmap) + 1 + sum(len(r[0]) for r in n.reps if r is not None)
    nvals = sum(len(V.tables[fid]) for fid in V.factor_order) + sum(len(g["ratio"]) for n in P.nodes if n.kind == GATHER for g in n.gaxes if g.get("ratio") is not None) + 2
    return 8 * words * 2 + 160 * nvals + 4096                                        # int64 list + ctypes copy; value strings "num/den" (proxy 160 B incl. list slot and encoded copy)


def flatten(V, deadline=None):
    """V: gbidi3.validate.Validated. Returns (prog int64 list, value strings, nfac, nratio, nconst). Value strings: factor tables (trusted + derived),
    then every ratio table, then constants, then the trusted scale (kernel `scale`; the CONSTANT node value is checked equal to it by the validator).
    Polls the ONE deadline every 4,096 emitted words / strings."""
    import time as _t
    emitted = [0]
    def tick(n=1):
        emitted[0] += n
        if deadline is not None and emitted[0] % 4096 < n and _t.monotonic() > deadline:
            raise IRError("DEADLINE during flattening")
    T = V.T; P = V.P; prog = [3, T.nvars_reduced]; prog += [len(T.dom_of(v)) for v in T.reduced_vars]
    fac_index = {}; qs = []; fdesc = []
    for fid in V.factor_order:
        tab = V.table(fid); scope = V.scope_positions(fid); fac_index[fid] = len(fdesc); fdesc.append((scope, len(tab), len(qs))); qs.extend("%d/%d" % (q.numerator, q.denominator) for q in tab); tick(len(tab))
    prog.append(len(fdesc))
    for scope, ent, off in fdesc:
        prog += [len(scope)] + list(scope) + [ent, off]
    cls_pool = []; ratio_pool = []
    def put_cls(xs):
        off = len(cls_pool); cls_pool.extend(int(x) for x in xs); return off
    def put_ratio(rs):
        off = len(ratio_pool); ratio_pool.extend(rs); return off
    node_words = []
    for n in P.nodes:
        tick(); w = [KIND_CODE[n.kind], len(n.axes)]
        for a, k in zip(n.axes, n.card):
            w += [V.var_position(a), k]
        dk = 0 if n.demand == "FULL" else (2 if n.demand == "EMPTY" or (isinstance(n.demand, (list, tuple)) and len(n.demand) == 0) else 1)
        dl = [] if dk != 1 else sorted(set(int(x) for x in n.demand))
        w += [STORAGE_CODE[n.storage], dk, len(dl)] + dl
        if n.kind == SOURCE:
            w.append(fac_index[n.fid])
        elif n.kind == MARKER:
            w.append(V.var_position(n.var))
        elif n.kind == CONSTANT:
            w.append(0)
        elif n.kind == GATHER:
            w.append(n.children[0])
            for g in n.gaxes:
                w += [g["out_pos"], g.get("fixed", 0) or 0, put_cls(g["cls"]) if g.get("cls") is not None else -1, put_ratio(g["ratio"]) if g.get("ratio") is not None else -1]
        elif n.kind == ADD:
            w += [len(n.children)] + list(n.children)
        elif n.kind == MUL:
            w += [len(n.children)] + list(n.children)
            for pr in n.proj:
                w += list(pr)
        elif n.kind == REDUCE:
            w.append(n.children[0])
            for k, r in enumerate(n.rmap):
                w += [r, put_cls(n.reps[k][0]) if (r >= 0 and n.reps[k] is not None) else -1]
            w.append(int(getattr(n, "driver", -1)))                                       # the priced sparse driver (operand index of the MUL) or -1
        node_words.append(w)
    prog += [len(cls_pool)] + cls_pool
    prog.append(len(P.nodes))
    for w in node_words:
        prog += w
    prog += [len(P.roots)] + list(P.roots)
    nfac = len(qs)
    qs.extend("%d/%d" % (Fr(r).numerator, Fr(r).denominator) for r in ratio_pool); nratio = len(ratio_pool)
    consts = [n.value for n in P.nodes if n.kind == CONSTANT]
    qs.extend("%d/%d" % (q.numerator, q.denominator) for q in consts); nconst = len(consts)
    if V.scale_applied_by == "executor":
        qs.append("%d/%d" % (T.scale.numerator, T.scale.denominator))
    else:
        qs.append("1/1")                                                            # the CONSTANT root node carries the scale; the kernel must not apply it twice
    for x in prog:
        if not (-INT64_MAX - 1 <= int(x) <= INT64_MAX):
            raise IRError("program word outside int64")
    return [int(x) for x in prog], qs, nfac, nratio, nconst


# ---------------------------------------------------------------------------------------------------------------- exact Fraction evaluator (qualification aid; NOT the oracle)
def exact_eval(V, cap_entries=200000):
    """evaluate every node entrywise in exact rationals at markers = 1 and return (Z, {nid: {idx: value}}); raises IRError above cap_entries total"""
    T = V.T; P = V.P; vals = {}; total = 0
    def digits(card, idx):
        d = [0] * len(card)
        for k in range(len(card) - 1, -1, -1):
            d[k] = idx % card[k]; idx //= card[k]
        return d
    def compose(card, d):
        idx = 0
        for k in range(len(card)):
            idx = idx * card[k] + d[k]
        return idx
    for n in P.nodes:
        total += n.volume
        if total > cap_entries:
            raise IRError("exact_eval cap")
        out = {}
        if n.kind == SOURCE:
            tab = V.table(n.fid)
            for i in range(n.volume):
                out[i] = tab[i]
        elif n.kind == MARKER:
            for i in range(n.volume):
                out[i] = Fr(1)
        elif n.kind == CONSTANT:
            out[0] = Fr(n.value)
        elif n.kind == GATHER:
            c = P.nodes[n.children[0]]; cv = vals[c.nid]
            for i in range(n.volume):
                d = digits(n.card, i); cd = []; sc = Fr(1)
                for k, g in enumerate(n.gaxes):
                    raw = d[g["out_pos"]]
                    if g.get("cls") is not None:
                        cd.append(g["cls"][raw]); sc *= Fr(g["ratio"][raw])
                    else:
                        cd.append(raw)
                out[i] = sc * cv[compose(c.card, cd)]
        elif n.kind == ADD:
            for i in range(n.volume):
                out[i] = sum(vals[c][i] for c in n.children)
        elif n.kind == MUL:
            for i in range(n.volume):
                d = digits(n.card, i); v = Fr(1)
                for ci, c in enumerate(n.children):
                    cn = P.nodes[c]; v *= vals[c][compose(cn.card, [d[p] for p in n.proj[ci]])]
                out[i] = v
        elif n.kind == REDUCE:
            c = P.nodes[n.children[0]]; cv = vals[c.nid]; elim = [k for k, r in enumerate(n.rmap) if r < 0]; ev = prod(c.card[k] for k in elim)
            for i in range(n.volume):
                d = digits(n.card, i); s = Fr(0)
                for t in range(ev):
                    tt = t; cd = [0] * len(c.card)
                    for k in reversed(elim):
                        cd[k] = tt % c.card[k]; tt //= c.card[k]
                    for k, r in enumerate(n.rmap):
                        if r >= 0:
                            cd[k] = n.reps[k][0][d[r]] if n.reps[k] is not None else d[r]
                    s += cv[compose(c.card, cd)]
                out[i] = s
        vals[n.nid] = out
    Z = Fr(T.scale)
    for r in P.roots:
        Z *= vals[r][0]
    return Z, vals
