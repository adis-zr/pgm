"""REGION_SURROGATE (Theorem 1): a query region H of the reduced graph, one fixed allowed state per outside neighbour block, crossing
factors retained EXACTLY as unary tilts, one kernel per inside edge (exact, or the positive degree-k truncation K~_k with
(1-eta)K <= K~ <= (1+eta)K), the regional law Q solved exactly (tree messages with exact / poly operators, else dense VE within the
priced limit), and the transport certificate: A_vu <= theta_e = tanh(s_e atanh r_e) on TRUE kernels, d_v = sum over crossing edges,
b_v <= rho_v + (1-rho_v) beta_v with beta_v <= tanh((1/2) sum_e atanh eta_e) (rational upper bound), F(z) = min(1, d+b+A z),
z^(0) = 1 iterated T times (every iterate valid) or a checked supersolution F(z) <= z. Published interval: [l - z_v, u + z_v] clipped."""
from __future__ import annotations
from fractions import Fraction as Fr
from cbi import model as M, arith as A, transfer as T, tree as TR, exact as EX


class SurrogateError(ValueError):
    """The requested truncation is not a positive surrogate kernel (eta >= 1)."""


def fixed_outside_state(block):
    """Deterministic allowed state: the first row of maximal weight."""
    i = max(range(len(block.rows)), key=lambda i: (block.w[i], -i))
    return block.rows[i]


def tilt_weights(red, H, xi):
    """Region blocks with crossing factors multiplied in as exact unary tilts (integers; scalar v^d' per crossing edge dropped)."""
    adj = M.adjacency(red); out = {}
    for v in H:
        blk = red.blocks[v]; ws = list(blk.w)
        for u, e in adj[v].items():
            if u in H:
                continue
            x_u = xi[u]; dp = e.s(); un, vn = A.uv(e.r)
            for i, x in enumerate(blk.rows):
                dd = bin((x ^ x_u) & e.mask).count("1")
                ws[i] = ws[i] * A.kappa_int(dp, un, vn, dd)
        out[v] = M.Block(v, list(blk.rows), ws)
    return out


def coefficients(infl, red, H, inside_ops):
    """Transport coefficients on the ORIGINAL-LAW influence system `infl` (never on the simplified graph): theta from original supports,
    d_v = sum of theta over influence edges leaving H (whether or not the solver kept them), beta_v from the surrogate etas of the
    COMPUTATIONAL inside edges (the approximated kernels), b_v = rho_v + (1 - rho_v) beta_v."""
    cadj = M.adjacency(red)
    eta = {}; beta = {}; b = {}; d = {}
    for v in H:
        d[v] = sum((th for u, th in infl.adj[v].items() if u not in H), Fr(0))
        etas = []
        for u, e in cadj.get(v, {}).items():
            if u in H:
                k = (min(u, v), max(u, v)); op = inside_ops[k]
                if op[0] == "poly":
                    et = T.surrogate_eta(e.s(), e.r, int(op[1]))
                    if et is None:
                        raise SurrogateError("degree-%d truncation is not a positive surrogate on edge %s" % (int(op[1]), (u, v)))
                    etas.append(et); eta[k] = et
                else:
                    eta[k] = Fr(0)
        beta[v] = A.tanh_half_sum_atanh(etas)
        rv = infl.rho.get(v, Fr(0)); b[v] = rv + (1 - rv) * beta[v]
    theta = {k: th for k, th in infl.theta.items() if k[0] in H or k[1] in H}
    return {"theta": theta, "d": d, "beta": beta, "b": b, "eta": eta}


def F_apply(infl, H, coef, z):
    out = {}
    for v in H:
        s_ = coef["d"][v] + coef["b"][v]
        for u, th in infl.adj[v].items():
            if u in H:
                s_ += th * z[u]
        out[v] = min(Fr(1), s_)
    return out


def iterate(infl, H, coef, T_max=64, tol=Fr(1, 2 ** 64)):
    z = {v: Fr(1) for v in H}; t = 0
    while t < T_max:
        z2 = F_apply(infl, H, coef, z); t += 1
        if all(z[v] - z2[v] <= tol for v in H):
            z = z2; break
        z = z2
    return z, t


def check_supersolution(infl, H, coef, z):
    Fz = F_apply(infl, H, coef, z)
    return all(Fz[v] <= z[v] for v in H), Fz


def transport_needed(infl, H, inside_ops):
    """Theorem 1 is needed iff an ORIGINAL-LAW influence edge leaves H (boundary replacement, even if the solver absorbed that edge),
    some inside kernel is a surrogate, or some node of H carries a retention defect. Otherwise the regional enclosure encloses the exact
    law of the whole influence component and z = 0."""
    crossing = any(u not in H for v in H for u in infl.adj[v])
    return crossing or any(op[0] == "poly" for op in inside_ops.values()) or any(infl.rho.get(v, Fr(0)) > 0 for v in H)


def solve_region(red, H, xi, inside_ops, query_block, max_entries=1 << 20, deadline=None):
    """Exact solve of Q (tilted region) for the query block's row belief: tree messages when the region graph is a forest, else dense VE
    with the surrogate / exact kernel tables. Returns (IVec belief or exact marginal ints, info)."""
    blocks = tilt_weights(red, H, xi)
    edges = [e for e in red.edges if e.u in H and e.v in H]
    sub = M.Reduced(red.d, blocks, edges, {}, {})
    if M.is_forest(sub):
        ops = {(min(e.u, e.v), max(e.u, e.v)): inside_ops[(min(e.u, e.v), max(e.u, e.v))] for e in edges}
        ts = TR.TreeSolver(blocks, edges, ops, deadline=deadline)
        bel = ts.belief(query_block)
        return bel, {"regional_solver": "tree", "messages": {"%d->%d" % k: v for k, v in ts.minfo.items()}}
    # dense VE with explicit kernel tables (exact kernels or the truncated polynomial kernels)
    tabs = []
    for e in edges:
        op = inside_ops[(min(e.u, e.v), max(e.u, e.v))]
        if op[0] == "exact":
            tabs.append(e)
        else:
            tabs.append(("poly", e, int(op[1])))
    marg, info = _ve_with_poly(blocks, tabs, query_block, max_entries, deadline)
    return A.IVec.exact(marg), {"regional_solver": "dense_ve", **info}


def _ve_with_poly(blocks, tabs, keep, max_entries, deadline=None):
    """Dense VE where some edge tables are the truncated polynomial kernels (exact integers at scale v^d')."""
    import numpy as np
    edges = [t if isinstance(t, M.Edge) else t[1] for t in tabs]
    worst, order = EX.price(blocks, edges, keep)
    if worst > max_entries:
        raise EX.TooLarge("largest intermediate table %d entries exceeds the limit %d" % (worst, max_entries))
    facs = [((b,), np.array(blk.w, dtype=object)) for b, blk in blocks.items()]
    for t in tabs:
        if isinstance(t, M.Edge):
            facs.append(((t.u, t.v), EX._kernel_table(blocks[t.u], blocks[t.v], t.mask, t.r)))
        else:
            _, e, k = t; dp = e.s(); u, v = A.uv(e.r); subs = T.subsets_of_mask(e.mask, k)
            X = np.asarray(blocks[e.u].rows, dtype=np.uint64); Y = np.asarray(blocks[e.v].rows, dtype=np.uint64)
            tab = np.zeros((len(X), len(Y)), dtype=object)
            for j in range(k + 1):
                c = u ** j * v ** (dp - j)
                for S in subs[j]:
                    cx = T.chi(X, S).astype(object); cy = T.chi(Y, S).astype(object)
                    tab = tab + c * np.outer(cx, cy)
            facs.append(((e.u, e.v), tab))
    # eliminate
    for x in order:
        if deadline is not None:
            deadline()
        inv = [f for f in facs if x in f[0]]; rest = [f for f in facs if x not in f[0]]
        scope = []
        for s, _ in inv:
            for y in s:
                if y not in scope:
                    scope.append(y)
        shape = tuple(len(blocks[y].rows) for y in scope)
        acc = np.ones(shape, dtype=object)
        for s, t in inv:
            idx = [slice(None) if y in s else None for y in scope]; perm = [s.index(y) for y in scope if y in s]
            tt = np.transpose(t, perm) if len(s) > 1 else t
            acc = acc * tt[tuple(idx)]
        summed = acc.sum(axis=scope.index(x)); nscope = tuple(y for y in scope if y != x)
        rest.append((nscope, summed) if nscope else ((), summed)); facs = rest
    out = np.array(blocks[keep].w, dtype=object) * 0 + 1; scalar = 1
    for s, t in facs:
        if s == (keep,):
            out = out * t
        elif s == ():
            scalar *= int(t)
    return [int(x) * scalar for x in out.tolist()], {"largest_table_entries": worst, "order": order}


def certify(infl, red, H, xi, inside_ops, query_block, T_max=64, max_entries=1 << 20, deadline=None):
    """REGION certificate: regional enclosure [l,u] of Q (computational graph `red`, fixed outside states xi, operators), transport radius
    from the influence system, published (unrounded) intervals [l - z, u + z]."""
    coef = coefficients(infl, red, H, inside_ops)
    if transport_needed(infl, H, inside_ops):
        z, t = iterate(infl, H, coef, T_max)
    else:
        z, t = {v: Fr(0) for v in H}, 0
    bel, info = solve_region(red, H, xi, inside_ops, query_block, max_entries, deadline)
    lu = TR.coordinate_intervals(bel, red.blocks[query_block].rows, red.d)
    zq = z[query_block]
    pub = [(max(Fr(0), l - zq), min(Fr(1), u + zq)) for l, u in lu]
    return {"H": sorted(H), "xi": {str(k): v for k, v in xi.items()}, "inside_ops": {"%d-%d" % k: list(v) for k, v in inside_ops.items()},
            "theta": {"%d-%d" % k: str(v) for k, v in coef["theta"].items()}, "d": {str(k): str(v) for k, v in coef["d"].items()},
            "beta": {str(k): str(v) for k, v in coef["beta"].items()}, "b": {str(k): str(v) for k, v in coef["b"].items()}, "eta": {"%d-%d" % k: str(v) for k, v in coef["eta"].items()},
            "rho": {str(k): str(v) for k, v in infl.rho.items() if k in H and v > 0}, "z": {str(k): str(v) for k, v in z.items()}, "iterations": t, "z_query": str(zq),
            "transport": ("theorem1_iteration" if t > 0 else "none (exact law of the whole influence component; enclosure operators only)"),
            "regional_lu": [[str(l), str(u)] for l, u in lu], "intervals_exact": pub, "solver_info": info, "query_block": query_block}
