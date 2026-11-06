"""INDEPENDENT verifier. From the ORIGINAL model and the producer's result it reconstructs, with ITS OWN code: the hard-component contraction
(own union-find / intersection), every used cluster's premises and rho_i (own connectivity, own intersection, own C_i, own exhaustive cut
enumeration, own Omega over the ORIGINAL supports of the seam members), the original-law influence thetas (own exp2L products over original
supports), the simplified computational graph (own fusion / absorption), the region, its influence crossing set, the fixed outside states,
d / eta / beta / b, the Theorem-1 iteration, the regional solve (own transfers: distance-major bincount exact transfer, subset-axis character
moments, min-degree VE), and the published rounding. Accepts iff every requested query is present with a per-query status consistent with
its width, every published interval CONTAINS the verifier's own enclosure, and every structural claim is reproduced. Shared proof-critical
helpers (listed): cbi.arith.kappa_int / tail / IVec / publish / normalize_event, the JSON parser cbi.model.Model.from_json, and the
constants in cbi.coarse (R_STRONG, MAX_CLUSTER) and cbi.transfer.surrogate_eta (the eta formula)."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
from itertools import combinations
import numpy as np
from cbi import model as M, arith as A, transfer as T, coarse as CO


class Rejected(Exception):
    pass


def _req(c, msg):
    if not c:
        raise Rejected(msg)


# ------------------------------------------------------------------ own reductions
def v_contract_hard(m):
    """Own union-find over r = 1 edges; returns (blocks, edges(full masks, parallel fused), o2r, infeasible)."""
    rep = {b: b for b in m.blocks}
    def root(x):
        while rep[x] != x:
            x = rep[x]
        return x
    for e in m.edges:
        if e.r == 1:
            a, b = root(e.u), root(e.v)
            if a != b:
                rep[max(a, b)] = min(a, b)
    o2r = {b: root(b) for b in m.blocks}
    groups = {}
    for b, r_ in o2r.items():
        groups.setdefault(r_, []).append(b)
    blocks = {}
    for r_, mem in groups.items():
        mem = sorted(mem)
        if len(mem) == 1:
            blocks[r_] = M.Block(r_, list(m.blocks[r_].rows), list(m.blocks[r_].w)); continue
        inter = set(m.blocks[mem[0]].rows)
        for b in mem[1:]:
            inter &= set(m.blocks[b].rows)
        if not inter:
            return None, None, o2r, mem
        rows = sorted(inter); w = []
        for z in rows:
            p = 1
            for b in mem:
                p *= dict(zip(m.blocks[b].rows, m.blocks[b].w))[z]
            w.append(p)
        blocks[r_] = M.Block(r_, rows, w)
    acc = {}
    for e in m.edges:
        a, b = o2r[e.u], o2r[e.v]
        if a == b:
            continue
        k = (min(a, b), max(a, b)); acc.setdefault(k, []).append(Fr(e.r))
    edges = []
    for k, rs in sorted(acc.items()):
        r_ = rs[0]
        for s_ in rs[1:]:
            r_ = (r_ + s_) / (1 + r_ * s_)
        edges.append(M.Edge(k[0], k[1], r_, (1 << m.d) - 1))
    return blocks, edges, o2r, None


def _vary(rows):
    o = 0; a = (1 << 63) - 1
    for x in rows:
        o |= x; a &= x
    return o & ~a


def v_cluster(blocks, edges, C):
    """Own Theorem-3 certificate: returns rho_i (Fraction), the coarse rows and weights; raises Rejected on a failed premise."""
    C = sorted(C); cs = set(C)
    _req(2 <= len(C) <= CO.MAX_CLUSTER, "cluster size")
    internal = [e for e in edges if e.u in cs and e.v in cs]; leaving = [e for e in edges if (e.u in cs) != (e.v in cs)]
    _req(all(e.r < 1 for e in internal), "hard edge inside a cluster")
    seen = {C[0]}; stack = [C[0]]
    while stack:
        x = stack.pop()
        for e in internal:
            for y in ((e.v,) if e.u == x else ((e.u,) if e.v == x else ())):
                if y not in seen:
                    seen.add(y); stack.append(y)
    _req(seen == cs, "cluster not connected internally")
    inter = set(blocks[C[0]].rows)
    for v in C[1:]:
        inter &= set(blocks[v].rows)
    _req(bool(inter), "empty intersection")
    rows = sorted(inter); wd = {v: dict(zip(blocks[v].rows, blocks[v].w)) for v in C}; tot = {v: sum(blocks[v].w) for v in C}
    Ci = Fr(0); w = []
    for z in rows:                                            # ARBITRARY-PRECISION products (Python ints / Fractions; never a fixed-width reduction)
        pq = Fr(1); pw = 1
        for v in C:
            pq *= Fr(wd[v][z], tot[v]); pw *= int(wd[v][z])
        Ci += pq; w.append(pw)
    gamma = Fr(0)
    for k in range(len(C) - 1):
        for sub in combinations(C[1:], k):
            S = set(sub) | {C[0]}
            prod = Fr(1)
            for e in internal:
                if (e.u in S) != (e.v in S):
                    prod *= (1 - e.r) / (1 + e.r)
            gamma = max(gamma, prod)
    expO = Fr(1)
    for e in leaving:
        u = e.u if e.u in cs else e.v
        expO *= ((1 + e.r) / (1 - e.r)) ** bin(e.mask & _vary(blocks[u].rows)).count("1")      # ORIGINAL support of the seam member
    x = (1 - Ci) / Ci * gamma * expO
    return x / (1 + x), rows, w, {"C_i": Ci, "Gamma_i": gamma, "expOmega": expO}


def v_influence(blocks, edges, cmap, rho):
    vary = {b: _vary(blk.rows) for b, blk in blocks.items()}; acc = {}
    for e in edges:
        a, b = cmap[e.u], cmap[e.v]
        if a == b or e.r == 0:
            continue
        s = bin(vary[e.u] & vary[e.v] & e.mask).count("1")
        if s == 0:
            continue
        k = (min(a, b), max(a, b))
        if e.r >= 1:
            acc[k] = None
        elif acc.get(k, Fr(1)) is not None:
            acc[k] = acc.get(k, Fr(1)) * ((1 + e.r) / (1 - e.r)) ** s
    theta = {k: (Fr(1) if E is None else (E - 1) / (E + 1)) for k, E in acc.items()}
    adj = {n: {} for n in set(cmap.values())}
    for (a, b), th in theta.items():
        adj[a][b] = th; adj[b][a] = th
    return theta, adj


def v_computational(blocks, edges, d):
    """Own simplification of Q: separable absorption (tilts multiplied in as integers), edge masks = coordinates varying on both sides."""
    full = (1 << d) - 1; vary = {b: _vary(blk.rows) for b, blk in blocks.items()}; cval = {b: blk.rows[0] & ~vary[b] for b, blk in blocks.items()}
    out_blocks = {b: M.Block(b, list(blk.rows), list(blk.w)) for b, blk in blocks.items()}; out_edges = []
    for e in edges:
        if e.r == 0:
            continue
        both = vary[e.u] & vary[e.v] & e.mask; u_, v_ = e.r.numerator, e.r.denominator
        for side, other in ((e.u, e.v), (e.v, e.u)):
            only = vary[side] & ~vary[other] & e.mask
            if only:
                blk = out_blocks[side]; nw = []
                for x, w in zip(blk.rows, blk.w):
                    f = 1
                    for j in range(d):
                        if (only >> j) & 1:
                            f *= v_ + u_ * (1 if (x >> j) & 1 else -1) * (1 if (cval[other] >> j) & 1 else -1)
                    nw.append(w * f)
                out_blocks[side] = M.Block(blk.id, blk.rows, nw)
        if both:
            out_edges.append(M.Edge(e.u, e.v, e.r, both))
    return out_blocks, out_edges


# ------------------------------------------------------------------ own transfer implementations
def v_exact(cav, src, tgt, mask, r, chunk=512):
    dp = bin(mask).count("1"); u, v = A.uv(r); kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    X = np.asarray(src, dtype=np.uint64); Y = np.asarray(tgt, dtype=np.uint64); nt = len(tgt)
    same = all(int(a) == int(b) for a, b in zip(cav.lo.tolist(), cav.hi.tolist()))
    vals_list = [[int(x) for x in cav.lo.tolist()]] + ([] if same else [[int(x) for x in cav.hi.tolist()]])
    acc = [[0] * ((dp + 1) * nt) for _ in vals_list]
    for s0 in range(0, len(src), chunk):
        xs = X[s0:s0 + chunk]
        D = np.bitwise_count((xs[:, None] ^ Y[None, :]) & np.uint64(mask)).astype(np.int64)
        key = (D * nt + np.arange(nt, dtype=np.int64)[None, :]).ravel()
        for vi, vals in enumerate(vals_list):
            vs = vals[s0:s0 + chunk]; nl = max(1, (max(vs).bit_length() + 29) // 30)
            for li in range(nl):
                limb = np.array([(x >> (30 * li)) & ((1 << 30) - 1) for x in vs], dtype=np.float64)
                h = np.bincount(key, weights=np.repeat(limb, nt), minlength=(dp + 1) * nt)
                nz = np.flatnonzero(h); a = acc[vi]
                for kk, sv in zip(nz.tolist(), h[nz].tolist()):
                    a[kk] += int(sv) << (30 * li)
    def fin(a):
        return [sum(a[dd * nt + i] * kap[dd] for dd in range(dp + 1)) for i in range(nt)]
    lo = fin(acc[0]); hi = lo if same else fin(acc[1])
    return A.IVec(lo, list(hi), cav.exp).normalize()


def _moments_subset_axis(rows, lo, hi, Sarr):
    S64 = Sarr.astype(np.uint64); pT = np.array([bin(int(S)).count("1") for S in Sarr.tolist()], dtype=np.int64)
    qlo = np.zeros(len(Sarr), dtype=object); qhi = np.zeros(len(Sarr), dtype=object)
    for x, l, h in zip(rows, lo.tolist(), hi.tolist()):
        par = ((pT - np.bitwise_count(np.uint64(x) & S64).astype(np.int64)) & 1).astype(bool).tolist(); l, h = int(l), int(h)
        qlo = qlo + np.array([-h if p_ else l for p_ in par], dtype=object); qhi = qhi + np.array([-l if p_ else h for p_ in par], dtype=object)
    return qlo, qhi


def v_fourier(cav, src, tgt, mask, r, k, poly=False):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if k >= dp:
        return v_exact(cav, src, tgt, mask, r)
    subs = T.subsets_of_mask(mask, k); Sarr = np.array([S for j in subs for S in subs[j]], dtype=np.uint64)
    deg = np.array([bin(int(S)).count("1") for S in Sarr.tolist()], dtype=np.int64)
    qlo, qhi = _moments_subset_axis(src, cav.lo, cav.hi, Sarr)
    cf = [u ** int(j) * v ** (dp - int(j)) for j in deg.tolist()]; ql = qlo.tolist(); qh = qhi.tolist(); lo = []; hi = []
    for y in tgt:
        par = ((deg - np.bitwise_count(np.uint64(y) & Sarr).astype(np.int64)) & 1).astype(bool).tolist()
        lo.append(sum((-qh[i] if par[i] else ql[i]) * cf[i] for i in range(len(cf)))); hi.append(sum((-ql[i] if par[i] else qh[i]) * cf[i] for i in range(len(cf))))
    if poly:
        return A.IVec([max(0, x) for x in lo], hi, cav.exp).normalize()
    Qlo, Qhi = cav.mass(); agg_lo = {}; agg_hi = {}
    for x, l, h in zip(src, cav.lo.tolist(), cav.hi.tolist()):
        p = x & mask; agg_lo[p] = agg_lo.get(p, 0) + int(l); agg_hi[p] = agg_hi.get(p, 0) + int(h)
    D_up = max(0, sum(agg_hi.values()) - sum(min(l, agg_lo.get(p ^ mask, 0)) for p, l in agg_lo.items()))
    te = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 0); to = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 1)
    E = Qhi * te + D_up * to
    return A.IVec([max(Qlo * (v - u) ** dp, x - E) for x in lo], [min(Qhi * (v + u) ** dp, x + E) for x in hi], cav.exp).normalize()


def v_sparse(cav, src, tgt, mask, r, h):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if h >= dp:
        return v_exact(cav, src, tgt, mask, r)
    kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    X = np.asarray(src, dtype=np.uint64); L = cav.lo.tolist(); Hh = cav.hi.tolist(); Qlo, Qhi = cav.mass(); lo = []; hi = []
    for y in tgt:
        D = np.bitwise_count((X ^ np.uint64(y)) & np.uint64(mask)).astype(np.int64); Clo = Chi = Blo = Bhi = 0
        for i in np.nonzero(D <= h)[0].tolist():
            Clo += L[i] * kap[int(D[i])]; Chi += Hh[i] * kap[int(D[i])]; Blo += L[i]; Bhi += Hh[i]
        lo.append(Clo + kap[dp] * (Qlo - Blo)); hi.append(Chi + kap[h + 1] * (Qhi - Bhi))
    return A.IVec(lo, hi, cav.exp).normalize()


def v_apply(op, cav, src, tgt, mask, r):
    k = op[0]
    if k == "exact":
        return v_exact(cav, src, tgt, mask, r)
    if k == "fourier":
        return v_fourier(cav, src, tgt, mask, r, int(op[1]))
    if k == "poly":
        return v_fourier(cav, src, tgt, mask, r, int(op[1]), poly=True)
    if k == "sparse":
        return v_sparse(cav, src, tgt, mask, r, int(op[1]))
    raise Rejected("unknown operator %r" % (op,))


def v_forest_all_beliefs(blocks, edges, ops):
    """Own two-pass schedule over every component of a forest: inward to each component's smallest node, outward with prefix / suffix
    products. Returns {node: IVec}. Independent of cbi.tree (different traversal order and cavity assembly)."""
    adj = {b: [] for b in blocks}
    for e in edges:
        adj[e.u].append(e.v); adj[e.v].append(e.u)
    emap = {(min(e.u, e.v), max(e.u, e.v)): e for e in edges}
    def send(frm, to, cav):
        e = emap[(min(frm, to), max(frm, to))]; return v_apply(ops[(min(frm, to), max(frm, to))], cav, blocks[frm].rows, blocks[to].rows, e.mask, e.r)
    msg = {}; out = {}; seen = set()
    for root in sorted(blocks):
        if root in seen:
            continue
        order = []; stack = [(root, None)]
        while stack:
            x, p = stack.pop(); seen.add(x); order.append((x, p))
            for w in sorted(adj[x], reverse=True):
                if w != p:
                    stack.append((w, x))
        for x, p in reversed(order):
            if p is not None:
                cav = A.IVec.exact(blocks[x].w).normalize()
                for w in adj[x]:
                    if w != p:
                        cav = cav.mul(msg[(w, x)])
                msg[(x, p)] = send(x, p, cav)
        for x, p in order:
            nb = sorted(adj[x]); inc = [msg[(w, x)] for w in nb]
            suf = [A.ones(len(blocks[x].rows))] * (len(nb) + 1)
            for i in range(len(nb) - 1, -1, -1):
                suf[i] = inc[i].mul(suf[i + 1])
            pre = A.IVec.exact(blocks[x].w).normalize(); out[x] = pre.mul(suf[0])
            for i, w in enumerate(nb):
                if (x, w) not in msg:
                    msg[(x, w)] = send(x, w, pre.mul(suf[i + 1]))
                pre = pre.mul(inc[i])
    return out


def v_tree_belief(blocks, edges, ops, root):
    adj = {b: [] for b in blocks}
    for e in edges:
        adj[e.u].append(e.v); adj[e.v].append(e.u)
    emap = {(min(e.u, e.v), max(e.u, e.v)): e for e in edges}
    order = []; stack = [(root, None)]
    while stack:
        x, p = stack.pop(); order.append((x, p))
        for w in adj[x]:
            if w != p:
                stack.append((w, x))
    msg = {}
    for x, p in reversed(order):
        if p is None:
            continue
        cav = A.IVec.exact(blocks[x].w).normalize()
        for w in adj[x]:
            if w != p:
                cav = cav.mul(msg[(w, x)])
        e = emap[(min(x, p), max(x, p))]; msg[(x, p)] = v_apply(ops[(min(x, p), max(x, p))], cav, blocks[x].rows, blocks[p].rows, e.mask, e.r)
    b = A.IVec.exact(blocks[root].w).normalize()
    for w in adj[root]:
        b = b.mul(msg[(w, root)])
    return b


def v_dense(blocks, edges, ops, root, max_entries):
    rem = [b for b in blocks if b != root]; adj = {b: set() for b in blocks}
    for e in edges:
        adj[e.u].add(e.v); adj[e.v].add(e.u)
    order = []; rs = set(rem)
    while rs:
        x = min(rs, key=lambda b: (len([y for y in adj[b] if y in rs or y == root]), b)); nb = [y for y in adj[x] if y in rs or y == root]
        for a in nb:
            for b in nb:
                if a != b:
                    adj[a].add(b)
        rs.discard(x); order.append(x)
    def ktab(e):
        op = ops[(min(e.u, e.v), max(e.u, e.v))]; dp = e.s(); u, v = A.uv(e.r); bu, bv = blocks[e.u], blocks[e.v]; tab = np.zeros((len(bu.rows), len(bv.rows)), dtype=object)
        if op[0] == "poly" and int(op[1]) < dp:
            subs = T.subsets_of_mask(e.mask, int(op[1]))
            for i, x in enumerate(bu.rows):
                for j, y in enumerate(bv.rows):
                    tab[i, j] = sum(u ** s * v ** (dp - s) * sum((-1) ** ((s - bin(x & S).count("1")) & 1) * (-1) ** ((s - bin(y & S).count("1")) & 1) for S in subs[s]) for s in subs)
        else:
            _req(op[0] in ("exact", "poly"), "dense regional solve with a non-exact operator %r" % (op,))
            for i, x in enumerate(bu.rows):
                for j, y in enumerate(bv.rows):
                    tab[i, j] = A.kappa_int(dp, u, v, bin((x ^ y) & e.mask).count("1"))
        return tab
    facs = [((b,), np.array(blk.w, dtype=object)) for b, blk in blocks.items()] + [((e.u, e.v), ktab(e)) for e in edges]
    for x in order:
        inv = [f for f in facs if x in f[0]]; rest = [f for f in facs if x not in f[0]]; scope = []
        for s, _ in inv:
            for y in s:
                if y not in scope:
                    scope.append(y)
        size = 1
        for y in scope:
            size *= len(blocks[y].rows)
        _req(size <= max_entries, "verifier dense table %d exceeds the limit" % size)
        acc = np.ones(tuple(len(blocks[y].rows) for y in scope), dtype=object)
        for s, t in inv:
            idx = [slice(None) if y in s else None for y in scope]; perm = [s.index(y) for y in scope if y in s]
            acc = acc * (np.transpose(t, perm) if len(s) > 1 else t)[tuple(idx)]
        summed = acc.sum(axis=scope.index(x)); ns = tuple(y for y in scope if y != x)
        rest.append((ns, summed) if ns else ((), summed)); facs = rest
    out = np.array(blocks[root].w, dtype=object) * 0 + 1; sc = 1
    for s, t in facs:
        if s == (root,):
            out = out * t
        elif s == ():
            sc *= int(t)
    return A.IVec.exact([int(x) * sc for x in out.tolist()])


def _parse_op(v, dp):
    _req(isinstance(v, (list, tuple)) and v and v[0] in ("exact", "poly", "fourier", "sparse"), "unknown operator %r" % (v,))
    if v[0] == "exact":
        _req(len(v) == 1, "exact takes no parameter"); return ("exact",)
    _req(len(v) == 2 and isinstance(v[1], int) and not isinstance(v[1], bool) and v[1] >= 0, "operator %r: parameter must be a nonnegative integer" % (v,))
    return (v[0], int(v[1]))


# ------------------------------------------------------------------ the verification
def verify(model, result):
    reasons = []
    try:
        m = (model if isinstance(model, M.Model) else M.Model.from_json(model)).validate()
        eps = Fr(result["requested_width"]); _req(result.get("grid_bits") == A.GRID_BITS, "grid bits differ")
        req = result.get("requested_queries"); _req(isinstance(req, list) and req, "requested query set missing from the result")
        req = sorted(int(q) for q in req); _req(all(q in m.blocks for q in req), "requested queries name unknown blocks")
        blocks, edges, o2r, bad = v_contract_hard(m)
        if result["status"] == "INFEASIBLE":
            _req(bad is not None, "INFEASIBLE claimed but every hard component has a nonempty intersection"); return {"accepted": True, "reasons": ["zero-partition proof reproduced: hard component %s has an empty intersection" % bad]}
        if result["status"] == "UNSUPPORTED_INPUT":
            return {"accepted": False, "reasons": ["nothing to verify: status UNSUPPORTED_INPUT"]}
        _req(bad is None, "model infeasible but the result claims otherwise")
        _req(result["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "RESOURCE_LIMIT"), "unknown status")
        sps = result.get("statuses_per_query") or {}
        _req(sorted(int(q) for q in sps) == req, "per-query statuses do not cover exactly the requested queries")
        _req(sorted(int(q) for q in result.get("intervals", {})) == [q for q in req if sps[str(q)] != "RESOURCE_LIMIT"], "interval records do not match the per-query statuses")
        vals = list(sps.values()); agg = "CERTIFIED" if all(v == "CERTIFIED" for v in vals) else ("VALID_BUT_TOO_WIDE" if any(v == "VALID_BUT_TOO_WIDE" for v in vals) else "RESOURCE_LIMIT")
        _req(result["status"] == agg, "aggregate status %s inconsistent with per-query statuses" % result["status"])
        # clusters used (per system)
        used = [sorted(int(x) for x in c["cluster"]) for c in (result["plan"]["clusters"].get("verified") or [])]
        # the certificate clusters must form a PARTITION of a subset of the contracted blocks: known ids, no duplicate member, pairwise disjoint,
        # 2..MAX_CLUSTER members each (the producer rejects overlaps; the checker enforces the premise independently)
        flat = [x for C in used for x in C]
        _req(all(x in blocks for x in flat), "a certificate cluster names an unknown or non-representative block")
        _req(len(flat) == len(set(flat)), "certificate clusters overlap or repeat a member: not a partition")
        _req(all(2 <= len(C) <= CO.MAX_CLUSTER and len(set(C)) == len(C) for C in used), "certificate cluster size / duplicate member")
        systems = {}
        if used:
            cmap = {b: b for b in blocks}; rho = {}; cblocks = dict(blocks)
            for C in used:
                r_i, rows, w, info = v_cluster(blocks, edges, C)
                rep = min(C)
                for v in C:
                    cmap[v] = rep
                    if v != rep:
                        cblocks.pop(v, None)
                cblocks[rep] = M.Block(rep, rows, w); rho[rep] = r_i
                mine = next(c for c in result["plan"]["clusters"]["verified"] if c["cluster"] == C)
                _req(Fr(mine["rho_i"]) == r_i, "cluster %s: rho_i %s differs from the verifier's %s" % (C, mine["rho_i"], r_i))
                _req(Fr(mine["C_i"]) == info["C_i"] and Fr(mine["Gamma_i"]) == info["Gamma_i"] and Fr(mine["expOmega_i"]) == info["expOmega"], "cluster %s: C_i / Gamma_i / expOmega_i differ from the verifier's" % C)
            acc = {}
            for e in edges:
                a, b = cmap[e.u], cmap[e.v]
                if a != b:
                    acc.setdefault((min(a, b), max(a, b)), []).append(e.r)
            cedges = []
            for k, rs in sorted(acc.items()):
                r_ = rs[0]
                for s_ in rs[1:]:
                    r_ = (r_ + s_) / (1 + r_ * s_)
                cedges.append(M.Edge(k[0], k[1], r_, (1 << m.d) - 1))
            theta, iadj = v_influence(blocks, edges, cmap, rho); rb, re_ = v_computational(cblocks, cedges, m.d)
            systems["coarse"] = (cmap, rho, theta, iadj, rb, re_)
        theta0, iadj0 = v_influence(blocks, edges, {b: b for b in blocks}, {}); rb0, re0 = v_computational(blocks, edges, m.d)
        systems["plain"] = ({b: b for b in blocks}, {}, theta0, iadj0, rb0, re0)
        q_grid = 1 << A.GRID_BITS
        proofs = result.get("proofs") or {}; verified = {}            # proof id -> {node: (belief IVec, z Fraction)}
        def verify_proof(pid):
            if pid in verified:
                return verified[pid]
            pr = proofs[pid]; sysk = pr.get("system"); _req(sysk in systems, "proof %s: unknown system %r" % (pid, sysk))
            cmap, rho, theta, iadj, rb, re_ = systems[sysk]
            H = set(int(x) for x in pr["H"]); _req(all(v in rb for v in H), "proof %s: region names unknown nodes" % pid)
            cadj = {b: {} for b in rb}
            for e in re_:
                cadj[e.u][e.v] = e; cadj[e.v][e.u] = e
            outside_comp = sorted({u for v in H for u in cadj[v] if u not in H}); xi = {int(k): int(v) for k, v in pr["xi"].items()}
            _req(sorted(xi) == outside_comp, "proof %s: fixed outside states do not cover exactly the computational crossing neighbours" % pid)
            for u, x in xi.items():
                _req(x in set(rb[u].rows), "fixed state %d of block %d is not an allowed row" % (x, u))
            inside = [e for e in re_ if e.u in H and e.v in H]
            ops = {}
            for k, v in pr["inside_ops"].items():
                a, b = (int(t) for t in k.split("-")); ops[(a, b)] = _parse_op(v, 0)
            _req(set(ops) == {(min(e.u, e.v), max(e.u, e.v)) for e in inside}, "proof %s: operator list does not match the inside edges" % pid)
            # transport on the influence system with the DYADIC upward-rounded recurrence (own replay)
            crossing = any(u not in H for v in H for u in iadj[v])
            needed = crossing or any(op[0] == "poly" for op in ops.values()) or any(rho.get(v, Fr(0)) > 0 for v in H)
            B = int(pr["z_grid_bits"]); qB = 1 << B
            if needed:
                d = {v: sum((th for u, th in iadj[v].items() if u not in H), Fr(0)) for v in H}; b = {}
                for v in H:
                    etas = []
                    for u, e in cadj[v].items():
                        if u in H:
                            op = ops[(min(u, v), max(u, v))]
                            if op[0] == "poly":
                                et = T.surrogate_eta(e.s(), e.r, int(op[1])); _req(et is not None, "poly operator with eta >= 1"); etas.append(et)
                    beta = min(Fr(1), sum((et / (1 - et) for et in etas), Fr(0)) / 2); rv = rho.get(v, Fr(0)); b[v] = rv + (1 - rv) * beta
                ceil_ = lambda x: -((-Fr(x) * qB).numerator // (-Fr(x) * qB).denominator)
                th = {k: ceil_(v) for k, v in theta.items() if k[0] in H and k[1] in H}; c = {v: ceil_(d[v] + b[v]) for v in H}
                T_ = int(pr["iterations"]); _req(T_ >= 1, "proof %s: transport needed but no iteration declared" % pid)
                z = {v: qB for v in H}
                for _ in range(T_):
                    z2 = {}
                    for v in H:
                        acc = c[v] * qB
                        for u in iadj[v]:
                            if u in H:
                                acc += th[(min(u, v), max(u, v))] * z[u]
                        z2[v] = min(qB, -((-acc) // qB))
                    z = z2
                _req(all(int(pr["z_grid"][str(v)]) == z[v] for v in H), "proof %s: dyadic Theorem-1 iterates differ" % pid)
                for k, v in (pr.get("theta") or {}).items():
                    a_, b_ = (int(t) for t in k.split("-")); _req(theta.get((a_, b_)) == Fr(v), "proof %s: theta %s differs" % (pid, k))
                for v in H:
                    if "d" in pr:
                        _req(Fr(pr["d"][str(v)]) == d[v] and Fr(pr["b"][str(v)]) == b[v], "proof %s: declared d / b at %d differ from the reconstruction" % (pid, v))
                    if "rho" in pr and rho.get(v, Fr(0)) > 0:
                        _req(Fr(pr["rho"][str(v)]) == rho[v], "proof %s: declared rho at %d differs" % (pid, v))
            else:
                z = {v: 0 for v in H}; _req(all(int(pr["z_grid"][str(v)]) == 0 for v in H), "proof %s: zero transport claimed inconsistently" % pid)
            # own regional solve: tilts, then batched forest (all nodes) or dense (one root)
            tb = {}
            for v in H:
                blk = rb[v]; ws = list(blk.w)
                for u, e in cadj[v].items():
                    if u not in H:
                        dp = e.s(); un, vn = A.uv(e.r); ws = [w * A.kappa_int(dp, un, vn, bin((x ^ xi[u]) & e.mask).count("1")) for x, w in zip(blk.rows, ws)]
                tb[v] = M.Block(v, list(blk.rows), ws)
            forest = M.is_forest(M.Reduced(m.d, tb, inside, {}, {}))
            nodes = {int(k): v for k, v in pr["nodes"].items()}; _req(all(n in H for n in nodes), "proof %s: a listed node is outside the region" % pid)
            if forest:
                bel_all = v_forest_all_beliefs(tb, inside, ops) if pr.get("kind") == "forest_batched" else {n: v_tree_belief(tb, inside, ops, n) for n in nodes}
            else:
                _req(all(op[0] in ("exact", "poly") for op in ops.values()), "cyclic region with an enclosure operator cannot be verified by dense elimination")
                bel_all = {n: v_dense(tb, inside, ops, n, 1 << 22) for n in nodes}
            verified[pid] = {n: (bel_all[n], Fr(z[n], qB)) for n in nodes}
            return verified[pid]
        for q in req:
            if sps[str(q)] == "RESOURCE_LIMIT":
                continue
            iv = result["intervals"][str(q)]; cert = result["certificate"][str(q)]
            pid = cert.get("proof"); _req(pid in proofs, "query %d: unknown proof %r" % (q, pid))
            sysk = proofs[pid].get("system"); cmap = systems[sysk][0]; node = cmap[o2r[q]]
            _req(cert.get("node") == node and iv.get("node") == node, "query %d maps to node %d, result says %s" % (q, node, cert.get("node")))
            nodes = verify_proof(pid); _req(node in nodes, "query %d: its node is not covered by proof %s" % (q, pid))
            bel, zq = nodes[node]
            rows = np.asarray(systems[sysk][4][node].rows, dtype=np.uint64)
            for j in range(m.d):
                sel = ((rows >> np.uint64(j)) & np.uint64(1)).astype(bool)
                LA, UA = bel.masked_mass(sel); LC, UC = bel.masked_mass(~sel); l, u = A.normalize_event(LA, UA, LC, UC)
                vlo, vhi = max(Fr(0), l - zq), min(Fr(1), u + zq)
                row = iv["coordinates"][j]; plo, phi = Fr(int(row["lo"]), q_grid), Fr(int(row["hi"]), q_grid)
                _req(0 <= int(row["lo"]) <= int(row["hi"]) <= q_grid, "published endpoints off the grid")
                _req(plo <= vlo and vhi <= phi, "query %d coordinate %d: published [%s, %s] does not contain the verifier's enclosure [%s, %s]" % (q, j, float(plo), float(phi), float(vlo), float(vhi)))
                _req(A.publish(Fr(row["exact"][0]), Fr(row["exact"][1])) == (int(row["lo"]), int(row["hi"])), "published endpoints are not the declared rounding of the stated exact interval")
            _req(len(iv["coordinates"]) == m.d, "coordinate coverage")
            wmax = max(Fr(int(r_["hi"]) - int(r_["lo"]), q_grid) for r_ in iv["coordinates"])
            _req(Fr(iv["max_width"]) == wmax and bool(wmax <= eps) == bool(iv["width_met"]) and (sps[str(q)] == "CERTIFIED") == bool(wmax <= eps), "width / status fields inconsistent")
            reasons.append("query %d: proof %s (%s), node %d, %d coordinates contained, max width %.3g, z = %.3g" % (q, pid, proofs[pid].get("kind"), node, m.d, float(wmax), float(zq)))
        reasons.append("%d proofs verified once for %d queries" % (len(verified), len([q for q in req if sps[str(q)] != "RESOURCE_LIMIT"])))
        return {"accepted": True, "reasons": reasons}
    except Rejected as ex:
        return {"accepted": False, "reasons": reasons + [str(ex)]}
    except Exception as ex:
        import traceback
        return {"accepted": False, "reasons": reasons + ["verifier fault: %s: %s" % (type(ex).__name__, ex)], "traceback": traceback.format_exc()[-1500:]}
