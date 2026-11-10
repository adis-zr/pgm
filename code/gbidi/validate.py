"""Independent validation of an UNTRUSTED planner proposal against the caller-bound reduced model (review F2 / SB-01; brief §1, numerics §7).

The planner (gbidi.plan) is not trusted. Before any numerical execution this module re-derives from the reduced model R (shared qualified reductions
of adp.source, whose decoder is validated separately) everything the kernel will execute and checks the proposal against it:
  * node set = exactly the reduced variables, each eliminated once; x_card = |dom[x]|;
  * SOURCE OWNERSHIP: every reduced factor occurrence with a nonempty scope is an input of exactly one node, the bucket of its earliest variable in
    the proposal's order; no factor is dropped, duplicated or moved; no scope-free factor remains unaccounted (R.scale carries the folded constants);
  * MESSAGE OWNERSHIP: every non-root node is an input of exactly one node (its consumer = bucket of the earliest remaining variable of its scope);
    roots have empty scope and no consumer; consumers follow their inputs in the order;
  * SCOPES: node scope == union of input scopes minus x (sorted); radix / core volume consistent with the views;
  * VIEW IDENTITIES: for every node, axis w and class with representative r, every member a satisfies, for EVERY input containing w, row_a == q_i row_r
    ENTRYWISE over the input's other axes (source tables inspected directly; a message input through its already-validated child view), and the
    node's ratio[a] equals the product of the q_i (an input with an all-zero row makes the entry zero on both sides: any ratio is exact then);
  * STORAGE SETS ("demand"): sorted, unique, inside the core volume; roots are stored FULL (one entry). Storage decisions do not affect the answer
    (the kernel streams any read outside the stored set), so they are only checked for well-formedness.
A failed check is a typed REJECTED refusal of the proposal, not a resource stop. Inspection work is charged inside the cell deadline (poll).
Not validated here (trusted, qualified elsewhere): the reductions + decoder (adp.source), the kernel arithmetic, the publisher, the point verifier."""
from __future__ import annotations
import time
from fractions import Fraction as Fr
from adp.engine import View


class Invalid(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


def _rows_along(f, k):
    """rows of factor f along axis k: list over positions a of a tuple over the other axes (flat order)"""
    import numpy as np
    arr = np.array(f.table, dtype=object).reshape(f.card); return [tuple(x) for x in np.moveaxis(arr, k, 0).reshape(f.card[k], -1)]


def validate(P, R, deadline=None):
    t0 = time.monotonic(); entries = 0; checks = 0
    def poll():
        if deadline is not None and time.monotonic() > deadline:
            raise Invalid("DEADLINE during plan validation")
    dom = R.dom; fac = {f.fid: f for f in R.factors}; nodes = P.nodes
    # 1. node set
    xs = [nd.x for nd in nodes]
    if sorted(xs) != sorted(dom) or len(set(xs)) != len(xs):
        raise Invalid("node set is not the reduced variable set")
    pos = {nd.x: i for i, nd in enumerate(nodes)}
    for nd in nodes:
        if nd.nid != pos[nd.x] or nd.x_card != len(dom[nd.x]):
            raise Invalid("node %d: id / cardinality mismatch" % nd.nid)
    # 2. source ownership
    owner = {}
    for nd in nodes:
        for kind, ref in nd.inputs:
            if kind == "F":
                if ref not in fac:
                    raise Invalid("node %d names unknown factor %s" % (nd.nid, ref))
                if ref in owner:
                    raise Invalid("factor %d owned twice (nodes %d, %d)" % (ref, owner[ref], nd.nid))
                owner[ref] = nd.nid; f = fac[ref]
                if not f.scope or min(f.scope, key=lambda v: pos[v]) != nd.x:
                    raise Invalid("factor %d is not in the bucket of its earliest variable" % ref)
            elif kind != "M":
                raise Invalid("unknown input kind %r" % kind)
    for f in R.factors:
        if f.scope and f.fid not in owner:
            raise Invalid("factor %d (origin %s) is not owned by any node: a source occurrence was dropped" % (f.fid, f.origin))
        if not f.scope:
            raise Invalid("scope-free factor %d remains in the reduced model (it must be folded into the scale)" % f.fid)
    # 3. message ownership + scopes
    consumers = {}
    for nd in nodes:
        sc = set()
        for kind, ref in nd.inputs:
            if kind == "M":
                if not (0 <= ref < nd.nid):
                    raise Invalid("node %d consumes message %s which does not precede it" % (nd.nid, ref))
                if ref in consumers:
                    raise Invalid("message %d consumed twice" % ref)
                consumers[ref] = nd.nid; sc |= set(nodes[ref].scope)
            else:
                sc |= set(fac[ref].scope)
        sc.discard(nd.x)
        if tuple(sorted(sc)) != tuple(nd.scope):
            raise Invalid("node %d: scope %s != union of inputs minus x %s" % (nd.nid, nd.scope, tuple(sorted(sc))))
        if nd.x in sc or any(w not in dom for w in nd.scope):
            raise Invalid("node %d: scope contains x or a non-reduced variable" % nd.nid)
    roots = set(P.roots)
    for nd in nodes:
        if nd.scope:
            exp = pos[min(nd.scope, key=lambda v: pos[v])]
            if consumers.get(nd.nid) != exp or nd.consumer != exp or nd.nid in roots:
                raise Invalid("node %d: consumer must be node %d (bucket of its earliest remaining variable)" % (nd.nid, exp))
        else:
            if nd.nid in consumers or nd.consumer is not None or nd.nid not in roots:
                raise Invalid("node %d has an empty scope and must be a root" % nd.nid)
            if not nd.materialize or nd.demand != "FULL":
                raise Invalid("root %d must be stored FULL" % nd.nid)
    if len(roots) != len(P.roots) or any(nodes[r].scope for r in roots):
        raise Invalid("root list malformed")
    # 4. views (entrywise identities) + radix / core / storage sets
    for nd in nodes:
        if tuple(nd.radix) != tuple(len(nd.views[w].reps) for w in nd.scope):
            raise Invalid("node %d: radix inconsistent with views" % nd.nid)
        core = 1
        for r_ in nd.radix:
            core *= r_
        if nd.core_entries != core:
            raise Invalid("node %d: core volume inconsistent" % nd.nid)
        if nd.demand != "FULL":
            d = list(nd.demand)
            if any(not (0 <= q < core) for q in d) or any(d[i] >= d[i + 1] for i in range(len(d) - 1)):
                raise Invalid("node %d: stored set not sorted / unique / inside the core" % nd.nid)
        for w in nd.scope:
            v = nd.views[w]; n = len(dom[w])
            if len(v.cls) != n or len(v.ratio) != n or not v.reps or any(not (0 <= c < len(v.reps)) for c in v.cls) or any(not (0 <= r < n) for r in v.reps):
                raise Invalid("node %d axis %d: malformed view" % (nd.nid, w))
            for c, r in enumerate(v.reps):
                if v.cls[r] != c or v.ratio[r] != 1:
                    raise Invalid("node %d axis %d: representative %d is not in its class with ratio 1" % (nd.nid, w, r))
            if all(v.cls[a] == a for a in range(n)) and all(q == 1 for q in v.ratio):
                continue                                                                      # identity view: nothing to prove
            # inputs containing w
            frows = []; mviews = []
            for kind, ref in nd.inputs:
                if kind == "F":
                    f = fac[ref]
                    if w in f.scope:
                        frows.append(_rows_along(f, f.scope.index(w))); entries += len(f.table)
                else:
                    c = nodes[ref]
                    if w in c.scope:
                        mviews.append(c.views[w])
            poll()
            for a in range(n):
                r = v.reps[v.cls[a]]
                if a == r:
                    continue
                zero = False; q = Fr(1)
                for rows in frows:
                    ra, rr = rows[a], rows[r]
                    if all(x == 0 for x in rr):
                        if any(x != 0 for x in ra):
                            raise Invalid("node %d axis %d: state %d merged with zero-row state %d but its row is nonzero" % (nd.nid, w, a, r))
                        zero = True; continue
                    j = next(i for i, x in enumerate(rr) if x != 0); qi = ra[j] / rr[j]
                    if any(ra[i] != qi * rr[i] for i in range(len(rr))):
                        raise Invalid("node %d axis %d: rows of states %d and %d are not proportional" % (nd.nid, w, a, r))
                    q *= qi; checks += len(rr)
                for cv in mviews:
                    if cv.cls[a] != cv.cls[r]:
                        raise Invalid("node %d axis %d: states %d and %d are merged but a message input separates them" % (nd.nid, w, a, r))
                    q *= cv.ratio[a] / cv.ratio[r]
                if not frows and not mviews:
                    raise Invalid("node %d axis %d: no input contains the axis" % (nd.nid, w))
                if not zero and v.ratio[a] != q:
                    raise Invalid("node %d axis %d: ratio of state %d is %s, inputs give %s" % (nd.nid, w, a, v.ratio[a], q))
            poll()
    return {"status": "VALID", "nodes": len(nodes), "factors_owned": len(owner), "messages_owned": len(consumers), "roots": len(roots), "view_entries_inspected": entries, "entrywise_checks": checks, "seconds": time.monotonic() - t0}
