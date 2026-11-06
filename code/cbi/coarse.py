"""COARSE_REGION (Theorem 3): strong-island coarsening with a boundary-uniform retention certificate. Clusters come from hints
(model.meta["cluster_hints"]) or the automatic rule (connected components of edges with r >= R_STRONG, size <= MAX_CLUSTER). For each
nontrivial cluster the library VERIFIES from the supports and couplings: connectivity by internal edges; a nonempty support
intersection; C_i = sum_{z in intersection} prod_v pi_v(z) > 0; Gamma_i = max over ALL nontrivial internal cuts S (enumerated
exactly, 2^(|C|-1) - 1 cuts) of prod_{e in cut} t_e, t_e = (1-r_e)/(1+r_e); exp(Omega_i) = prod_{e leaving} ((1+r)/(1-r))^(s_e) with
s_e the coordinates of the seam kernel that vary over the intersection rows; alpha_i = ((1-C_i)/C_i) Gamma_i;
rho_i = alpha e^Omega / (1 + alpha e^Omega). The coarse law: one block per cluster (intersection rows, product weights; internal kernels
at aligned states are scalars), crossing edges re-pointed and fused by (A) at full masks, then separable absorption."""
from __future__ import annotations
from fractions import Fraction as Fr
from itertools import combinations
from cbi import model as M

R_STRONG = Fr(1) - Fr(1, 2 ** 8)
MAX_CLUSTER = 8


def propose_clusters(model: M.Model, hints=None, o2r=None):
    """hints name ORIGINAL block ids; they are mapped through the hard contraction (o2r), deduplicated, trivial (< 2 members) clusters dropped;
    overlapping mapped clusters are rejected explicitly."""
    if hints:
        try:
            raw = [[int(x) for x in c] for c in hints]
        except (TypeError, ValueError):
            raise M.UnsupportedInput("cluster hints must be lists of block ids")
        o2r = o2r or {b: b for b in model.blocks}
        if any(x not in o2r for c in raw for x in c):
            raise M.UnsupportedInput("cluster hints name unknown original block ids")
        cl = [sorted(set(o2r[x] for x in c)) for c in raw]
        cl = [c for c in cl if len(c) >= 2]
        flat = [x for c in cl for x in c]
        if len(flat) != len(set(flat)):
            raise M.UnsupportedInput("cluster hints overlap after the hard contraction: they must partition a subset of the blocks")
        if any(len(c) > MAX_CLUSTER or len(c) < 2 for c in cl):
            raise M.UnsupportedInput("cluster hints must have 2..%d blocks each (exact cut enumeration is 2^(|C|-1) - 1 cuts)" % MAX_CLUSTER)
        return cl, "hints"
    parent = {b: b for b in model.blocks}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for e in model.edges:
        if e.r >= R_STRONG and e.r < 1:
            a, b = find(e.u), find(e.v)
            if a != b:
                parent[max(a, b)] = min(a, b)
    comps = {}
    for b in model.blocks:
        comps.setdefault(find(b), []).append(b)
    cl = [sorted(c) for c in comps.values() if 1 < len(c) <= MAX_CLUSTER]
    return cl, "automatic (components of edges with r >= %s, size <= %d)" % (R_STRONG, MAX_CLUSTER)


def verify_cluster(model: M.Model, C, deadline=None):
    """Returns the certificate dict (rho_i etc.) or raises ValueError with the failed premise."""
    C = sorted(C); cs = set(C); d = model.d
    if len(C) > MAX_CLUSTER:
        raise ValueError("cluster has %d > %d blocks" % (len(C), MAX_CLUSTER))
    internal = [e for e in model.edges if e.u in cs and e.v in cs]; leaving = [e for e in model.edges if (e.u in cs) != (e.v in cs)]
    if len(C) < 2:
        raise ValueError("cluster must have at least two blocks")
    if any(e.r == 1 for e in internal):
        raise ValueError("cluster contains a hard edge: contract hard components first")
    # connectivity by internal edges
    adj = {v: set() for v in C}
    for e in internal:
        adj[e.u].add(e.v); adj[e.v].add(e.u)
    seen = {C[0]}; stack = [C[0]]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if y not in seen:
                seen.add(y); stack.append(y)
    if seen != cs:
        raise ValueError("cluster is not connected by its internal edges")
    inter = set(model.blocks[C[0]].rows)
    for v in C[1:]:
        inter &= set(model.blocks[v].rows)
    if not inter:
        raise ValueError("empty support intersection: no retained state (G_i impossible)")
    rows = sorted(inter)
    idx = {v: model.blocks[v].index() for v in C}; A0 = {v: sum(model.blocks[v].w) for v in C}
    Ci = Fr(0); w = []
    for z in rows:
        p = Fr(1); pw = 1
        for v in C:
            p *= Fr(model.blocks[v].w[idx[v][z]], A0[v]); pw *= model.blocks[v].w[idx[v][z]]
        Ci += p; w.append(pw)
    # Gamma over all nontrivial cuts (vertex C[0] on the S side)
    t = {}
    for e in internal:
        t[(e.u, e.v)] = (1 - e.r) / (1 + e.r)
    others = C[1:]; gamma = Fr(0); worst_cut = None
    for k in range(0, len(others)):
        for sub in combinations(others, k):
            if deadline is not None:
                deadline()
            S = set(sub) | {C[0]}
            if len(S) == len(C):
                continue
            prod = Fr(1)
            for (a, b), te in t.items():
                if (a in S) != (b in S):
                    prod *= te
            if prod > gamma:
                gamma = prod; worst_cut = sorted(S)
    alpha = (1 - Ci) / Ci * gamma
    # exp(Omega): for every seam e = (u, v) with u in C, the kernel coordinates varying on the ORIGINAL support of u (retained AND
    # discarded states of the cluster member): the boundary likelihood ratio between ANY original internal state and any retained
    # state is at most prod_e ((1+r_e)/(1-r_e))^{s_e}. (CORRECTED 6 Nov 2026: the first version counted only the intersection rows.)
    expO = Fr(1); seams = []
    for e in leaving:
        u = e.u if e.u in cs else e.v
        blk = model.blocks[u]; o = 0; a_ = (1 << 63) - 1
        for x in blk.rows:
            o |= x; a_ &= x
        s = bin(e.mask & (o & ~a_)).count("1")
        expO *= ((1 + e.r) / (1 - e.r)) ** s; seams.append({"edge": [e.u, e.v], "r": str(e.r), "varying_coords_original_support": s})
    x = alpha * expO; rho = x / (1 + x)
    return {"cluster": C, "rows": len(rows), "C_i": str(Ci), "Gamma_i": str(gamma), "worst_cut": worst_cut, "cuts_enumerated": 2 ** (len(C) - 1) - 1,
            "alpha_i": str(alpha), "expOmega_i": str(expO), "seams": seams, "rho_i": str(rho), "rho_i_float": float(rho),
            "internal_edges": [[e.u, e.v, str(e.r)] for e in internal], "coarse_rows": rows, "coarse_weights": w}


def coarsen(model: M.Model, clusters, deadline=None):
    """Coarse Model (full masks) + mapping original(contracted) block -> coarse block + per-cluster certificates (rho_i)."""
    certs = {}; cmap = {b: b for b in model.blocks}
    blocks = {b: M.Block(b, list(blk.rows), list(blk.w)) for b, blk in model.blocks.items()}
    for C in clusters:
        cert = verify_cluster(model, C, deadline); rid = C[0]; certs[rid] = cert
        for v in C:
            cmap[v] = rid
            if v != rid:
                del blocks[v]
        blocks[rid] = M.Block(rid, cert["coarse_rows"], cert["coarse_weights"])
    pend = {}
    for e in model.edges:
        a, b = cmap[e.u], cmap[e.v]
        if a == b:
            continue
        pend.setdefault((min(a, b), max(a, b)), []).append(e.r)
    edges = []; full = (1 << model.d) - 1
    for (a, b), rs in sorted(pend.items()):
        r = rs[0]
        for s in rs[1:]:
            r, _ = M.fuse_parallel(r, s, model.d)
        edges.append(M.Edge(a, b, r, full))
    coarse = M.Model(model.d, blocks, edges, dict(model.meta))
    rho = {rid: Fr(c["rho_i"]) for rid, c in certs.items()}
    return coarse, cmap, certs, rho
