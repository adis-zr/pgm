"""Independent validation of an UNTRUSTED planner proposal against an IMMUTABLE trusted reduced source, producing the VALIDATED EXECUTABLE
REPRESENTATION that the numerical code consumes (closeout of the third review, V2-V1: validation and execution must read the SAME payload).

  TrustedReduced(R)  -- a deep, frozen copy of the shared reductions' result (dom, factors with tables, scale, decoder, hashes) taken BEFORE the
                        planner runs; `unchanged(R)` detects an in-place mutation of the live object during planning.
  validate(P, T)     -- re-derives from T everything the kernel will execute and checks the proposal against it: node set, SOURCE OWNERSHIP (every
                        nonempty-scope trusted factor owned exactly once by the bucket of its earliest variable; no scope-free factor left),
                        MESSAGE OWNERSHIP / consumer structure, SCOPES, radix / core volume, storage-set well-formedness, and EVERY non-identity view
                        identity entrywise against the TRUSTED tables (rows proportional; ratio = product of the input ratios; a state whose complete
                        product is zero -- any input with an all-zero row -- may be merged with other product-zero states with any ratio).
                        Returns Validated: the trusted tables / scale / decoder / domains plus the validated plan structure (views, storage sets,
                        materialization). gbidi.executor.flatten_program and reference_stream consume ONLY a Validated / TrustedReduced object;
                        P.fac / P.R are never serialized.
A failed check is a typed REJECTED refusal of the proposal, not a resource stop. Not validated here (trusted, qualified elsewhere): the
reductions + decoder (adp.source), the kernel arithmetic, the publisher, the point verifier."""
from __future__ import annotations
import time, hashlib
from fractions import Fraction as Fr


class Invalid(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


class TFactor:
    __slots__ = ("fid", "scope", "card", "table", "origin", "_rows")

    def __init__(self, f):
        self.fid = int(f.fid); self.scope = tuple(int(v) for v in f.scope); self.card = tuple(int(c) for c in f.card); self.table = tuple(Fr(x) for x in f.table); self.origin = str(f.origin); self._rows = {}
        if len(self.table) != _prod(self.card) or len(self.scope) != len(self.card) or any(x < 0 for x in self.table):
            raise Invalid("trusted factor %d malformed" % self.fid)

    def rows_along(self, k):
        r = self._rows.get(k)
        if r is None:
            import numpy as np
            arr = np.array(self.table, dtype=object).reshape(self.card); r = [tuple(x) for x in np.moveaxis(arr, k, 0).reshape(self.card[k], -1)]; self._rows[k] = r
        return r


def _prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


class TrustedReduced:
    """frozen copy of adp.source.Reduced: the only source of tables / scale / decoder for execution"""
    def __init__(self, R):
        self.nvars = int(R.nvars); self.orig_card = tuple(int(c) for c in R.orig_card); self.dom = {int(v): tuple(int(s) for s in d) for v, d in R.dom.items()}
        self.factors = tuple(sorted((TFactor(f) for f in R.factors), key=lambda f: f.fid)); self.scale = Fr(R.scale); self.zero_proof = R.zero_proof
        self.dec = {int(v): tuple((("C", Fr(e[1])) if e[0] == "C" else ("V", int(e[1]), int(e[2]), Fr(e[3]))) for e in es) for v, es in R.dec.items()}
        for v, es in self.dec.items():
            for e in es:
                if e[0] == "V" and (e[1] not in self.dom or e[2] not in self.dom[e[1]]):
                    raise Invalid("decoder of variable %d references a non-reduced state" % v)
        self.content_hash = self._hash()

    def _hash(self):
        h = hashlib.sha256()
        for v in sorted(self.dom):
            h.update(("D%d:%s;" % (v, ",".join(map(str, self.dom[v])))).encode())
        for f in self.factors:
            h.update(("F%d:%s:%s:%s;" % (f.fid, ",".join(map(str, f.scope)), ",".join(map(str, f.card)), ",".join("%d/%d" % (x.numerator, x.denominator) for x in f.table))).encode())
        h.update(("S%d/%d;" % (self.scale.numerator, self.scale.denominator)).encode())
        for v in sorted(self.dec):
            h.update(("X%d:%s;" % (v, "|".join(":".join(map(str, e)) for e in self.dec[v]))).encode())
        return h.hexdigest()

    def unchanged(self, R):
        """the LIVE reduced object still has exactly the snapshot's content (detects an in-place mutation by the planner)"""
        try:
            return TrustedReduced(R).content_hash == self.content_hash
        except Exception:
            return False


class VNode:
    __slots__ = ("nid", "x", "x_card", "inputs", "scope", "views", "radix", "core_entries", "consumer", "materialize", "demand")


class Validated:
    """the executable representation: trusted payload + validated structure"""
    __slots__ = ("T", "nodes", "roots", "record")

    def __init__(self, T, nodes, roots, record):
        self.T = T; self.nodes = nodes; self.roots = roots; self.record = record


def validate(P, T, deadline=None):
    if not isinstance(T, TrustedReduced):
        raise Invalid("validation requires the immutable TrustedReduced snapshot")
    t0 = time.monotonic(); entries = 0; checks = 0
    def poll():
        if deadline is not None and time.monotonic() > deadline:
            raise Invalid("DEADLINE during plan validation")
    dom = T.dom; fac = {f.fid: f for f in T.factors}; nodes = P.nodes
    xs = [nd.x for nd in nodes]
    if sorted(xs) != sorted(dom) or len(set(xs)) != len(xs):
        raise Invalid("node set is not the reduced variable set")
    pos = {nd.x: i for i, nd in enumerate(nodes)}
    for nd in nodes:
        if nd.nid != pos[nd.x] or nd.x_card != len(dom[nd.x]):
            raise Invalid("node %d: id / cardinality mismatch" % nd.nid)
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
    for f in T.factors:
        if f.scope and f.fid not in owner:
            raise Invalid("factor %d (origin %s) is not owned by any node: a source occurrence was dropped" % (f.fid, f.origin))
        if not f.scope:
            raise Invalid("scope-free factor %d remains in the reduced model (it must be folded into the scale)" % f.fid)
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
    vnodes = []
    for nd in nodes:
        if tuple(nd.radix) != tuple(len(nd.views[w].reps) for w in nd.scope):
            raise Invalid("node %d: radix inconsistent with views" % nd.nid)
        core = _prod(nd.radix)
        if nd.core_entries != core:
            raise Invalid("node %d: core volume inconsistent" % nd.nid)
        if nd.demand != "FULL":
            d = [int(q) for q in nd.demand]
            if any(not (0 <= q < core) for q in d) or any(d[i] >= d[i + 1] for i in range(len(d) - 1)):
                raise Invalid("node %d: stored set not sorted / unique / inside the core" % nd.nid)
        vviews = {}
        for w in nd.scope:
            v = nd.views[w]; n = len(dom[w])
            if len(v.cls) != n or len(v.ratio) != n or not v.reps or any(not (0 <= c < len(v.reps)) for c in v.cls) or any(not (0 <= r < n) for r in v.reps):
                raise Invalid("node %d axis %d: malformed view" % (nd.nid, w))
            cls = tuple(int(c) for c in v.cls); reps = tuple(int(r) for r in v.reps); ratio = tuple(Fr(q) for q in v.ratio)
            if any(q < 0 for q in ratio):
                raise Invalid("node %d axis %d: negative view ratio" % (nd.nid, w))
            for c, r in enumerate(reps):
                if cls[r] != c or ratio[r] != 1:
                    raise Invalid("node %d axis %d: representative %d is not in its class with ratio 1" % (nd.nid, w, r))
            vviews[w] = (cls, reps, ratio)
            if all(cls[a] == a for a in range(n)) and all(q == 1 for q in ratio):
                continue
            frows = []; mviews = []
            for kind, ref in nd.inputs:
                if kind == "F":
                    f = fac[ref]
                    if w in f.scope:
                        frows.append(f.rows_along(f.scope.index(w))); entries += len(f.table)
                else:
                    c = nodes[ref]
                    if w in c.scope:
                        mviews.append(c.views[w])
            if not frows and not mviews:
                raise Invalid("node %d axis %d: no input contains the axis" % (nd.nid, w))
            poll()
            zero = [any(all(x == 0 for x in rows[a]) for rows in frows) for a in range(n)]          # complete product of state a is zero (any input with an all-zero row)
            for a in range(n):
                r = reps[cls[a]]
                if a == r:
                    continue
                if zero[a] or zero[r]:
                    if not (zero[a] and zero[r]):
                        raise Invalid("node %d axis %d: state %d merged with state %d but only one complete product is zero" % (nd.nid, w, a, r))
                    for cv in mviews:
                        if cv.cls[a] != cv.cls[r]:
                            raise Invalid("node %d axis %d: zero states %d and %d separated by a message input" % (nd.nid, w, a, r))
                    continue                                                                  # both complete products are zero: any ratio is exact
                q = Fr(1)
                for rows in frows:
                    ra, rr = rows[a], rows[r]; j = next(i for i, x in enumerate(rr) if x != 0); qi = ra[j] / rr[j]
                    if any(ra[i] != qi * rr[i] for i in range(len(rr))):
                        raise Invalid("node %d axis %d: rows of states %d and %d are not proportional" % (nd.nid, w, a, r))
                    q *= qi; checks += len(rr)
                for cv in mviews:
                    if cv.cls[a] != cv.cls[r]:
                        raise Invalid("node %d axis %d: states %d and %d are merged but a message input separates them" % (nd.nid, w, a, r))
                    q *= Fr(cv.ratio[a]) / Fr(cv.ratio[r])
                if ratio[a] != q:
                    raise Invalid("node %d axis %d: ratio of state %d is %s, inputs give %s" % (nd.nid, w, a, ratio[a], q))
            poll()
        vn = VNode(); vn.nid = nd.nid; vn.x = nd.x; vn.x_card = nd.x_card; vn.inputs = tuple((k, int(r)) for k, r in nd.inputs); vn.scope = tuple(nd.scope); vn.views = vviews; vn.radix = tuple(nd.radix); vn.core_entries = core; vn.consumer = nd.consumer; vn.materialize = bool(nd.materialize); vn.demand = "FULL" if nd.demand == "FULL" else tuple(int(q) for q in nd.demand)
        vnodes.append(vn)
    rec = {"status": "VALID", "nodes": len(nodes), "factors_owned": len(owner), "messages_owned": len(consumers), "roots": len(roots), "view_entries_inspected": entries, "entrywise_checks": checks, "trusted_content_sha256": T.content_hash, "seconds": time.monotonic() - t0}
    return Validated(T, tuple(vnodes), tuple(int(r) for r in P.roots), rec)
