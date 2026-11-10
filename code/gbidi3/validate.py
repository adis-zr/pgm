"""Independent validation of an UNTRUSTED planner proposal (gbidi3.ir.Program) against the IMMUTABLE trusted reduced source (gbidi3.trusted.TrustedReduced).
Returns the VALIDATED EXECUTABLE REPRESENTATION `Validated`: the only object gbidi3.ir.flatten, the executor, the serializer and the decoder consume
(brief §5: never validate R and execute P.fac). Checks, each with a precise typed reason (Invalid):
  structure   acyclic topological order, child ids, axis / cardinality consistency per kind, projections total, demand lists sorted / unique / in range,
              storage legal for the kind, SPARSE only on REDUCE(MUL) without compressed axes (kernel representability), int64 bounds;
  sources     every SOURCE names a trusted occurrence or a DERIVED table registered with a finite witness that is re-checked ENTRYWISE here:
              product split f(raw) = u(axis) * g(rest) on every entry incl. zeros, additive split f = u + w on every entry;
  coverage    gbidi3.ir.coverage: occurrence / marker multiplicity, elimination after marking, aligned ADD operands, disjoint MUL operands;
  roots       scalar roots covering every effective occurrence exactly once and every reduced variable's marker and elimination exactly once;
  views       every compressed REDUCE axis: reps[c] in class c with ratio 1; for every raw state a != rep: EVERY operand of the REDUCE's MUL that
              contains the axis has rows a and rep proportional (SOURCE: entrywise on the TRUSTED table; message operand: a GATHER whose class map puts
              a and rep in one class, ratio = ratio[a]/ratio[rep]); declared ratio[a] == product of operand ratios; product-zero states (an operand
              with an all-zero row at a AND at rep) may share a class with any ratio; one zero and one nonzero row -> rejected (C01/C04);
              every GATHER expanding a compressed axis copies exactly the REDUCE's (cls, ratio); a GATHER on an uncompressed axis is the identity;
  constant    at most one CONSTANT node, equal to the trusted scale, a root; then the executor applies scale 1 (never twice).
Validation reads complete source witnesses; it never reconstructs a dense intermediate to check a lawful streamed representation."""
from __future__ import annotations
import time, copy
from fractions import Fraction as Fr
from gbidi3 import ir as IR
from gbidi3.trusted import TrustedReduced, Invalid, TFactor


class Validated:
    """trusted payload + validated program structure. `table(fid)` / `scope_positions(fid)` / `var_position(v)` serve the flattener."""
    __slots__ = ("T", "P", "factor_order", "tables", "scopes", "record", "scale_applied_by")

    def __init__(self, T, P, factor_order, tables, scopes, record, scale_applied_by):
        self.T = T; self.P = P; self.factor_order = tuple(factor_order); self.tables = tables; self.scopes = scopes; self.record = record; self.scale_applied_by = scale_applied_by

    def table(self, fid):
        return self.tables[fid]

    def scope_positions(self, fid):
        return tuple(self.T.var_pos[v] for v in self.scopes[fid])

    def var_position(self, v):
        return self.T.var_pos[v]


def _strides(card):
    st = [1] * len(card); acc = 1
    for k in range(len(card) - 1, -1, -1):
        st[k] = acc; acc *= card[k]
    return st


def _rows_along(table, card, k):
    st = _strides(card); out = []
    for a in range(card[k]):
        out.append(tuple(table[i] for i in range(len(table)) if (i // st[k]) % card[k] == a))
    return out


def _check_product_split(parent, u, g, axis_k):
    """parent(raw) == u[raw_k] * g(rest) on EVERY entry (zeros included)"""
    card = parent.card; st = _strides(card); rest_card = card[:axis_k] + card[axis_k + 1:]; rst = _strides(rest_card)
    if len(u) != card[axis_k] or len(g) != IR.prod(rest_card):
        raise Invalid("derived split of factor %d: table sizes do not match" % parent.fid)
    for i in range(len(parent.table)):
        a = (i // st[axis_k]) % card[axis_k]; rest = 0; j = 0
        for k in range(len(card)):
            if k == axis_k:
                continue
            rest += ((i // st[k]) % card[k]) * rst[j]; j += 1
        if parent.table[i] != u[a] * g[rest]:
            raise Invalid("derived split of factor %d: entry %d is %s but u*g gives %s" % (parent.fid, i, parent.table[i], u[a] * g[rest]))


def _tree_coverage(P, T, all_occ, reduced_vars, tick):
    """linear-time coverage check for a TREE program (every non-root node has exactly one consumer, no ADD, no derived tables):
    (1) every effective occurrence is a SOURCE leaf exactly once and every reduced variable a MARKER leaf exactly once; the CONSTANT (if any) is a root;
    (2) every reduced variable is eliminated by exactly one REDUCE; (3) every node whose axes contain v (SOURCE scopes, MARKER(v), intermediates) is a strict
    descendant of the REDUCE eliminating v (DFS intervals), so all v-dependent operands and v's marker are multiplied in before v is summed out and no
    sibling operand of another branch mentions v; (4) roots are scalar. With (1)-(4) each root equals the sum over its eliminated variables of the product
    of its leaves, each exactly once (brief proof notes P1, P2, P7)."""
    src = {}; mk = {}
    for n in P.nodes:
        if n.kind == IR.SOURCE:
            if n.fid in src:
                raise Invalid("occurrence %s appears in two SOURCE leaves" % (n.fid,))
            src[n.fid] = n.nid
        elif n.kind == IR.MARKER:
            if n.var in mk:
                raise Invalid("marker of variable %s appears twice" % n.var)
            mk[n.var] = n.nid
    if set(src) != set(all_occ):
        raise Invalid("leaves cover occurrences %s; expected %s (missing %s, extra %s)" % (sorted(src, key=str)[:6], sorted(all_occ, key=str)[:6], sorted(set(all_occ) - set(src), key=str)[:6], sorted(set(src) - set(all_occ), key=str)[:6]))
    if set(mk) != set(reduced_vars):
        raise Invalid("markers do not cover every reduced variable exactly once (missing %s)" % sorted(set(reduced_vars) - set(mk))[:6])
    elim_node = {}
    for n in P.nodes:
        if n.kind == IR.REDUCE:
            child = P.nodes[n.children[0]]
            for k, r in enumerate(n.rmap):
                if r < 0:
                    v = child.axes[k]
                    if v in elim_node:
                        raise Invalid("variable %s is eliminated twice" % v)
                    elim_node[v] = n.nid
    if set(elim_node) != set(reduced_vars):
        raise Invalid("eliminations do not cover every reduced variable exactly once (missing %s)" % sorted(set(reduced_vars) - set(elim_node))[:6])
    for r in P.roots:
        if P.nodes[r].axes:
            raise Invalid("root %d is not scalar" % r)
    # DFS intervals over the forest (iterative)
    pre = [0] * len(P.nodes); post = [0] * len(P.nodes); t = 0
    for r in P.roots:
        stack = [(r, 0)]
        while stack:
            nid, state = stack.pop()
            if state == 0:
                pre[nid] = t; t += 1; stack.append((nid, 1)); stack.extend((c, 0) for c in reversed(P.nodes[nid].children))
            else:
                post[nid] = t; t += 1
            tick()
    def inside(a, b):
        return pre[b] < pre[a] and post[a] < post[b]
    for n in P.nodes:
        for v in n.axes:
            e = elim_node[v]
            if n.nid == e or not inside(n.nid, e):
                raise Invalid("node %d mentions variable %s outside the subtree of the REDUCE (%d) that eliminates it" % (n.nid, v, e))
        tick()
    for v, m in mk.items():
        if not inside(m, elim_node[v]):
            raise Invalid("marker of variable %s is not inside the subtree of its REDUCE" % v)


def validate(P, T, deadline=None, poll_every=4096):
    if not isinstance(T, TrustedReduced):
        raise Invalid("validation requires the immutable TrustedReduced snapshot")
    if not isinstance(P, IR.Program):
        raise Invalid("proposal is not an IR program")
    t0 = time.monotonic(); checks = [0]
    def tick(n=1):
        checks[0] += n
        if deadline is not None and checks[0] % poll_every < n and time.monotonic() > deadline:
            raise Invalid("DEADLINE during plan validation")
    dom = T.dom; trusted = {f.fid: f for f in T.factors}
    # ---------------------------------------------------------------- derived tables (finite witnesses re-checked entrywise)
    tables = {f.fid: f.table for f in T.factors}; scopes = {f.fid: f.scope for f in T.factors}; cards = {f.fid: f.card for f in T.factors}
    occ_of = {}; effective = set(trusted); additive_parent = {}
    for dfid, d in P.derived.items():
        if dfid in trusted:
            raise Invalid("derived table id %s collides with a trusted occurrence" % (dfid,))
        parent = d.get("parent")
        if parent not in trusted:
            raise Invalid("derived table %s names unknown parent %s" % (dfid, parent))
        pf = trusted[parent]
        if d["kind"] == "product_split":
            k = d["axis_k"]
            if not (0 <= k < len(pf.scope)):
                raise Invalid("derived split axis out of range")
            u = tuple(Fr(x) for x in d["u"]); g = tuple(Fr(x) for x in d["g"])
            if any(x < 0 for x in u) or any(x < 0 for x in g):
                raise Invalid("derived split with a negative table")
            _check_product_split(pf, u, g, k); tick(len(pf.table))
            if d["part"] == "u":
                tables[dfid] = u; scopes[dfid] = (pf.scope[k],); cards[dfid] = (pf.card[k],)
            elif d["part"] == "g":
                tables[dfid] = g; scopes[dfid] = pf.scope[:k] + pf.scope[k + 1:]; cards[dfid] = pf.card[:k] + pf.card[k + 1:]
            else:
                raise Invalid("derived split part must be u or g")
            occ_of[dfid] = dfid; effective.discard(parent); effective.add(dfid)
        elif d["kind"] == "additive_split":
            parts = [tuple(Fr(x) for x in t) for t in d["parts"]]
            if any(len(t) != len(pf.table) for t in parts) or any(x < 0 for t in parts for x in t):
                raise Invalid("additive split of factor %d malformed" % parent)
            for i in range(len(pf.table)):
                if sum(t[i] for t in parts) != pf.table[i]:
                    raise Invalid("additive split of factor %d: entry %d does not sum to the source" % (parent, i))
            tick(len(pf.table))
            j = d["index"]
            if not (0 <= j < len(parts)):
                raise Invalid("additive split index")
            tables[dfid] = parts[j]; scopes[dfid] = pf.scope; cards[dfid] = pf.card; occ_of[dfid] = dfid; additive_parent[dfid] = parent
        else:
            raise Invalid("unknown derived witness kind %r" % d["kind"])
    # ---------------------------------------------------------------- structure per node
    seen_const = []; reduced_vars = set(dom)
    for pos_i, n in enumerate(P.nodes):
        if n.nid != pos_i:
            raise Invalid("node ids are not positional")
        for a, c in zip(n.axes, n.card):
            if a not in dom:
                raise Invalid("node %d: axis %s is not a reduced variable" % (n.nid, a))
            compressed = n.kind == IR.REDUCE and n.reps is not None and any(r is not None and n.rmap[i] == n.axes.index(a) for i, r in enumerate(n.reps))
            if not compressed and c != len(dom[a]):
                raise Invalid("node %d: axis %s has cardinality %d but the reduced domain has %d" % (n.nid, a, c, len(dom[a])))
        if len(set(n.axes)) != len(n.axes):
            raise Invalid("node %d repeats an axis" % n.nid)
        if n.volume > IR.INT64_MAX:
            raise Invalid("node %d: volume exceeds int64" % n.nid)
        if n.storage not in IR.STORAGE_CODE:
            raise Invalid("node %d: unknown storage" % n.nid)
        if n.kind in (IR.SOURCE, IR.MARKER, IR.CONSTANT) and n.storage != IR.STREAM:
            raise Invalid("node %d: leaves are STREAM" % n.nid)
        if n.demand != "FULL":
            if n.storage != IR.DENSE:
                raise Invalid("node %d: a demand hint requires DENSE storage" % n.nid)
            if n.demand != "EMPTY":
                dl = list(n.demand)
                if any(not isinstance(x, int) or not (0 <= x < n.volume) for x in dl) or sorted(set(dl)) != dl:
                    raise Invalid("node %d: demand list must be sorted, unique, inside the volume" % n.nid)
        if n.kind == IR.SOURCE:
            if n.fid not in tables:
                raise Invalid("node %d names unknown factor %s" % (n.nid, n.fid))
            if n.axes != tuple(scopes[n.fid]) or n.card != tuple(cards[n.fid]):
                raise Invalid("node %d: SOURCE axes %s / cards %s differ from the trusted factor %s" % (n.nid, n.axes, n.card, n.fid))
            for a, c in zip(n.axes, n.card):
                if len(dom[a]) != c:
                    raise Invalid("node %d: axis %s cardinality %d != reduced domain %d" % (n.nid, a, c, len(dom[a])))
        elif n.kind == IR.MARKER:
            if n.var not in dom or n.axes != (n.var,) or n.card != (len(dom[n.var]),):
                raise Invalid("node %d: MARKER malformed" % n.nid)
        elif n.kind == IR.CONSTANT:
            if Fr(n.value) != T.scale or n.axes:
                raise Invalid("node %d: the only admissible CONSTANT is the trusted scale %s (got %s)" % (n.nid, T.scale, n.value))
            seen_const.append(n.nid)
        elif n.kind == IR.GATHER:
            child = P.nodes[n.children[0]]
            for k, g in enumerate(n.gaxes):
                if not isinstance(g, dict) or "out_pos" not in g:
                    raise Invalid("node %d: gather axis descriptor malformed" % n.nid)
                if g["out_pos"] < 0 or g["out_pos"] >= len(n.axes):
                    raise Invalid("node %d: gather out_pos out of range" % n.nid)
            if len(set(g["out_pos"] for g in n.gaxes)) != len(n.gaxes):
                raise Invalid("node %d: gather reads one output axis twice" % n.nid)
            for a, c in zip(n.axes, n.card):
                if len(dom[a]) != c:
                    raise Invalid("node %d: gather output axis %s cardinality %d != reduced domain %d" % (n.nid, a, c, len(dom[a])))
            # compressed child axes must be expanded with the child's own class witness; uncompressed axes are identities
            if child.kind == IR.REDUCE:
                for k, g in enumerate(n.gaxes):                                                  # k = CHILD axis; its class witness sits at the MUL axis m with child.rmap[m] == k
                    m = next((i for i, r in enumerate(child.rmap) if r == k), None); rep = child.reps[m] if m is not None else None
                    if rep is not None:
                        if g.get("cls") is None or tuple(g["cls"]) != tuple(rep[1]) or tuple(Fr(x) for x in g["ratio"]) != tuple(Fr(x) for x in rep[2]):
                            raise Invalid("node %d: gather axis %s does not carry the producer's class witness" % (n.nid, n.axes[g["out_pos"]]))
                    elif g.get("cls") is not None:
                        raise Invalid("node %d: class map on an uncompressed axis %s" % (n.nid, n.axes[g["out_pos"]]))
            elif any(g.get("cls") is not None for g in n.gaxes):
                raise Invalid("node %d: class map on a non-REDUCE child" % n.nid)
        elif n.kind == IR.ADD:
            if len(n.children) < 1:
                raise Invalid("node %d: empty ADD" % n.nid)
        elif n.kind == IR.MUL:
            if len(n.children) < 1 or len(n.proj) != len(n.children):
                raise Invalid("node %d: MUL malformed" % n.nid)
            for ci, c in enumerate(n.children):
                ch = P.nodes[c]
                if len(n.proj[ci]) != len(ch.axes) or len(set(n.proj[ci])) != len(n.proj[ci]):
                    raise Invalid("node %d: operand %d projection is not total / injective" % (n.nid, ci))
            covered = set(p for pr in n.proj for p in pr)
            if covered != set(range(len(n.axes))):
                raise Invalid("node %d: output axis not produced by any operand" % n.nid)
            if n.storage == IR.SPARSE:
                raise Invalid("node %d: SPARSE storage is a REDUCE(MUL) representation" % n.nid)
        elif n.kind == IR.REDUCE:
            child = P.nodes[n.children[0]]
            if len(n.rmap) != len(child.axes) or len(n.reps) != len(child.axes):
                raise Invalid("node %d: REDUCE map length" % n.nid)
            kept = [r for r in n.rmap if r >= 0]
            if sorted(kept) != list(range(len(n.axes))):
                raise Invalid("node %d: REDUCE kept axes are not a bijection onto the output" % n.nid)
            if n.storage == IR.SPARSE:
                if child.kind != IR.MUL:
                    raise Invalid("node %d: SPARSE requires a MUL child" % n.nid)
                if any(r is not None for r in n.reps):
                    raise Invalid("node %d: SPARSE REDUCE cannot carry compressed axes" % n.nid)
            if len([r for r in n.rmap if r < 0]) > 64:
                raise Invalid("node %d: more than 64 eliminated axes in one REDUCE" % n.nid)
        else:
            raise Invalid("node %d: unknown kind %s" % (n.nid, n.kind))
        tick()
    if len(seen_const) > 1:
        raise Invalid("more than one CONSTANT node")
    scale_applied_by = "node" if seen_const else "executor"
    if seen_const and seen_const[0] not in P.roots:
        raise Invalid("the scale CONSTANT must be a root")
    # ---------------------------------------------------------------- coverage and roots
    all_occ = set(effective)
    cons = P.consumers(); is_tree = all(len(cons[n.nid]) == (0 if n.nid in P.roots else 1) for n in P.nodes) and not any(n.kind == IR.ADD for n in P.nodes) and not P.derived
    if is_tree:
        _tree_coverage(P, T, all_occ, reduced_vars, tick)                                            # linear-time check (the planner's programs are trees)
        cov = None
    else:
        try:
            cov = IR.coverage(P, occ_of, additive_parent)                                            # exact set-based coverage for shared / additive programs
        except IR.IRError as ex:
            raise Invalid("coverage: %s" % ex.reason)
    try:
        if cov is None:
            pass
        elif seen_const:
            IR.check_roots(P, cov, all_occ, reduced_vars)
        else:
            O = set(); M = set(); E = set()
            for r in P.roots:
                n = P.nodes[r]; c = cov[r]
                if n.axes:
                    raise Invalid("root %d is not scalar" % r)
                if O & c.O or M & c.M or E & c.E:
                    raise Invalid("roots overlap in coverage")
                O |= c.O; M |= c.M; E |= c.E
            if O != all_occ:
                raise Invalid("roots cover occurrences %s; expected %s (missing %s, extra %s)" % (sorted(O, key=str)[:6], sorted(all_occ, key=str)[:6], sorted(all_occ - O, key=str)[:6], sorted(O - all_occ, key=str)[:6]))
            if M != reduced_vars or E != reduced_vars:
                raise Invalid("roots do not cover every reduced variable's marker and elimination exactly once (markers missing %s, eliminations missing %s)" % (sorted(reduced_vars - M)[:6], sorted(reduced_vars - E)[:6]))
    except IR.IRError as ex:
        raise Invalid("roots: %s" % ex.reason)
    if len(set(P.roots)) != len(P.roots):
        raise Invalid("duplicate root")
    # ---------------------------------------------------------------- view witnesses (compressed REDUCE axes) proven entrywise against TRUSTED tables
    view_entries = 0; view_checks = 0
    for n in P.nodes:
        if n.kind != IR.REDUCE or all(r is None for r in n.reps):
            continue
        child = P.nodes[n.children[0]]
        if child.kind != IR.MUL:
            raise Invalid("node %d: compressed axes require a MUL child" % n.nid)
        for k, rep in enumerate(n.reps):
            if rep is None:
                continue
            w = child.axes[k]; nraw = child.card[k]; reps, cls, ratio = tuple(int(x) for x in rep[0]), tuple(int(x) for x in rep[1]), tuple(Fr(x) for x in rep[2])
            if len(cls) != nraw or len(ratio) != nraw or not reps or any(not (0 <= c < len(reps)) for c in cls) or any(not (0 <= r < nraw) for r in reps) or any(q < 0 for q in ratio):
                raise Invalid("node %d axis %s: malformed class witness" % (n.nid, w))
            for c, r in enumerate(reps):
                if cls[r] != c or ratio[r] != 1:
                    raise Invalid("node %d axis %s: representative %d is not in its class with ratio 1" % (n.nid, w, r))
            # operands of the MUL containing w
            frows = []; mviews = []
            for ci, cn in enumerate(child.children):
                op = P.nodes[cn]
                if w not in op.axes:
                    continue
                pos_in_op = op.axes.index(w)
                if op.kind == IR.SOURCE:
                    frows.append(_rows_along(tables[op.fid], cards[op.fid], pos_in_op)); view_entries += len(tables[op.fid])
                elif op.kind == IR.GATHER and op.gaxes and any(g["out_pos"] == pos_in_op and g.get("cls") is not None for g in op.gaxes):
                    g = next(g for g in op.gaxes if g["out_pos"] == pos_in_op); mviews.append((tuple(g["cls"]), tuple(Fr(x) for x in g["ratio"])))
                elif op.kind == IR.MARKER:
                    continue                                                    # the marker is 1 at every state: proportional with ratio 1
                else:
                    raise Invalid("node %d axis %s: operand %d is neither a trusted table nor a class-expanded message along the axis" % (n.nid, w, ci))
            if not frows and not mviews and not any(P.nodes[cn].kind == IR.MARKER and w in P.nodes[cn].axes for cn in child.children):
                raise Invalid("node %d axis %s: no operand contains the axis" % (n.nid, w))
            zero = [any(all(x == 0 for x in rows[a]) for rows in frows) for a in range(nraw)]
            for a in range(nraw):
                r = reps[cls[a]]
                if a == r:
                    continue
                tick()
                if zero[a] or zero[r]:
                    if not (zero[a] and zero[r]):
                        raise Invalid("node %d axis %s: state %d merged with state %d but only one complete product is zero" % (n.nid, w, a, r))
                    for mc, _ in mviews:
                        if mc[a] != mc[r]:
                            raise Invalid("node %d axis %s: zero states %d and %d separated by a message operand" % (n.nid, w, a, r))
                    continue
                q = Fr(1)
                for rows in frows:
                    ra, rr = rows[a], rows[r]; j = next(i for i, x in enumerate(rr) if x != 0); qi = ra[j] / rr[j]
                    if any(ra[i] != qi * rr[i] for i in range(len(rr))):
                        raise Invalid("node %d axis %s: rows of states %d and %d are not proportional" % (n.nid, w, a, r))
                    q *= qi; view_checks += len(rr)
                for mc, mr in mviews:
                    if mc[a] != mc[r]:
                        raise Invalid("node %d axis %s: states %d and %d merged but a message operand separates them" % (n.nid, w, a, r))
                    q *= mr[a] / mr[r]
                if ratio[a] != q:
                    raise Invalid("node %d axis %s: ratio of state %d is %s, inputs give %s" % (n.nid, w, a, ratio[a], q))
    # ---------------------------------------------------------------- done
    factor_order = sorted(tables)
    P = copy.deepcopy(P)                                                                   # the EXECUTABLE representation is a frozen copy: a later mutation of the planner's object cannot reach execution (C20)
    rec = {"status": "VALID", "nodes": len(P.nodes), "roots": len(P.roots), "effective_occurrences": len(all_occ), "derived_tables": len(P.derived), "view_entries_inspected": view_entries, "entrywise_checks": view_checks, "checks": checks[0], "trusted_content_sha256": T.content_hash, "scale_applied_by": scale_applied_by, "seconds": time.monotonic() - t0}
    return Validated(T, P, factor_order, tables, scopes, rec, scale_applied_by)
