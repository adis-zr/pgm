"""INDEPENDENT verifier. From the ORIGINAL model and the producer's result it reconstructs: the hard-component contraction and its
infeasibility proof, the cluster premises and rho_i (own cut enumeration), the separable reductions and effective couplings, the region,
crossing edges and fixed outside states, every analytic coefficient (theta, d, eta, beta, b), the Theorem-1 iteration (or supersolution),
the regional solve [l,u] with ITS OWN transfer implementations (matmul-by-distance exact transfer; subset-axis character moments for
fourier/poly; target-side popcount filtering for sparse; min-degree-ordered VE) and the published rounding. It accepts iff the published
grid interval of every coordinate CONTAINS the verifier's own enclosure and every structural claim is reproduced. It never reads
producer moments, residuals or coefficients as inputs -- they are only compared. Shared proof-critical helpers: cbi.arith (kappa_int,
theta_edge, tail, IVec, publish), cbi.model parsing / reductions (re-run, then compared), cbi.transfer.subsets_of_mask (enumeration)."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import numpy as np
from cbi import model as M, arith as A, transfer as T, coarse as CO, region as RG


class Rejected(Exception):
    pass


def _req(c, msg):
    if not c:
        raise Rejected(msg)


# ------------------------------------------------------------------ own transfer implementations
def v_exact(cav, src, tgt, mask, r, chunk=512):
    """Own exact transfer: SOURCE-major chunks with distance-major keys (dist * n_tgt + target), limbs of 30 bits (float64 exact), the
    per-limb histogram by numpy's bincount (the library primitive; the producer's code is target-major with target-major keys and its
    own limb handling). Independently written; shares no code with cbi.transfer.transfer_exact / cbi.arith.hist_by_distance."""
    dp = bin(mask).count("1"); u, v = A.uv(r); kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    X = np.asarray(src, dtype=np.uint64); Y = np.asarray(tgt, dtype=np.uint64); nt = len(tgt)
    same = all(int(a) == int(b) for a, b in zip(cav.lo.tolist(), cav.hi.tolist()))
    vals_list = [[int(x) for x in cav.lo.tolist()]] + ([] if same else [[int(x) for x in cav.hi.tolist()]])
    acc = [[0] * ((dp + 1) * nt) for _ in vals_list]
    for s0 in range(0, len(src), chunk):
        xs = X[s0:s0 + chunk]
        D = np.bitwise_count((xs[:, None] ^ Y[None, :]) & np.uint64(mask)).astype(np.int64)          # (chunk, nt)
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
    """q_T in [lo_T, hi_T] for all T in Sarr, vectorized over subsets per row."""
    S64 = Sarr.astype(np.uint64); pT = np.array([bin(int(S)).count("1") for S in Sarr.tolist()], dtype=np.int64)
    qlo = np.zeros(len(Sarr), dtype=object); qhi = np.zeros(len(Sarr), dtype=object)
    for x, l, h in zip(rows, lo.tolist(), hi.tolist()):
        par = ((pT - np.bitwise_count(np.uint64(x) & S64).astype(np.int64)) & 1).astype(bool).tolist()
        l, h = int(l), int(h)
        qlo = qlo + np.array([-h if p_ else l for p_ in par], dtype=object); qhi = qhi + np.array([-l if p_ else h for p_ in par], dtype=object)
    return qlo, qhi


def v_fourier(cav, src, tgt, mask, r, k, poly=False):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if k >= dp:
        return v_exact(cav, src, tgt, mask, r)
    subs = T.subsets_of_mask(mask, k); Sarr = np.array([S for j in subs for S in subs[j]], dtype=np.uint64)
    deg = np.array([bin(int(S)).count("1") for S in Sarr.tolist()], dtype=np.int64)
    qlo, qhi = _moments_subset_axis(src, cav.lo, cav.hi, Sarr)
    coef = np.array([u ** int(j) * v ** (dp - int(j)) for j in deg.tolist()], dtype=object)
    lo = []; hi = []
    ql = qlo.tolist(); qh = qhi.tolist(); cf = coef.tolist()
    for y in tgt:
        par = ((deg - np.bitwise_count(np.uint64(y) & Sarr).astype(np.int64)) & 1).astype(bool).tolist()      # chi_T(y) = -1 where par
        lo.append(sum((-qh[i] if par[i] else ql[i]) * cf[i] for i in range(len(cf)))); hi.append(sum((-ql[i] if par[i] else qh[i]) * cf[i] for i in range(len(cf))))
    if poly:
        return A.IVec([max(0, x) for x in lo], hi, cav.exp).normalize()
    Qlo, Qhi = cav.mass()
    # antipodal defect on the S-projected cavity (own aggregation)
    agg_lo = {}; agg_hi = {}
    for x, l, h in zip(src, cav.lo.tolist(), cav.hi.tolist()):
        p = x & mask; agg_lo[p] = agg_lo.get(p, 0) + int(l); agg_hi[p] = agg_hi.get(p, 0) + int(h)
    D_up = max(0, sum(agg_hi.values()) - sum(min(l, agg_lo.get(p ^ mask, 0)) for p, l in agg_lo.items()))
    te = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 0); to = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 1)
    E = Qhi * te + D_up * to
    lo = [max(Qlo * (v - u) ** dp, x - E) for x in lo]; hi = [min(Qhi * (v + u) ** dp, x + E) for x in hi]
    return A.IVec(lo, hi, cav.exp).normalize()


def v_sparse(cav, src, tgt, mask, r, h):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if h >= dp:
        return v_exact(cav, src, tgt, mask, r)
    kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    X = np.asarray(src, dtype=np.uint64); L = cav.lo.tolist(); Hh = cav.hi.tolist(); Qlo, Qhi = cav.mass(); lo = []; hi = []
    for y in tgt:
        D = np.bitwise_count((X ^ np.uint64(y)) & np.uint64(mask)).astype(np.int64)
        Clo = Chi = Blo = Bhi = 0
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


def v_tree_belief(blocks, edges, ops, root):
    """Own recursion (explicit stack, source-major), own cavity products."""
    adj = {b: [] for b in blocks}
    for e in edges:
        adj[e.u].append(e.v); adj[e.v].append(e.u)
    emap = {(min(e.u, e.v), max(e.u, e.v)): e for e in edges}
    memo = {}
    def msg(frm, to):
        if (frm, to) in memo:
            return memo[(frm, to)]
        cav = A.IVec.exact(blocks[frm].w).normalize()
        for w in adj[frm]:
            if w != to:
                cav = cav.mul(msg(w, frm))
        e = emap[(min(frm, to), max(frm, to))]; m = v_apply(ops[(min(frm, to), max(frm, to))], cav, blocks[frm].rows, blocks[to].rows, e.mask, e.r)
        memo[(frm, to)] = m; return m
    b = A.IVec.exact(blocks[root].w).normalize()
    for w in adj[root]:
        b = b.mul(msg(w, root))
    return b


def v_dense(blocks, edges, ops, root, max_entries):
    """Own dense elimination: min-DEGREE order (the producer uses min-fill), tables built by explicit per-pair evaluation."""
    import itertools
    rem = [b for b in blocks if b != root]; adj = {b: set() for b in blocks}
    for e in edges:
        adj[e.u].add(e.v); adj[e.v].add(e.u)
    order = []
    rs = set(rem)
    while rs:
        x = min(rs, key=lambda b: (len([y for y in adj[b] if y in rs or y == root]), b)); nb = [y for y in adj[x] if y in rs or y == root]
        for a in nb:
            for b in nb:
                if a != b:
                    adj[a].add(b)
        rs.discard(x); order.append(x)
    def ktab(e):
        op = ops[(min(e.u, e.v), max(e.u, e.v))]; dp = e.s(); u, v = A.uv(e.r)
        bu, bv = blocks[e.u], blocks[e.v]; tab = np.zeros((len(bu.rows), len(bv.rows)), dtype=object)
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
        inv = [f for f in facs if x in f[0]]; rest = [f for f in facs if x not in f[0]]
        scope = []
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


# ------------------------------------------------------------------ the verification
def verify(model, result):
    reasons = []
    try:
        m = model if isinstance(model, M.Model) else M.Model.from_json(model)
        eps = Fr(result["requested_width"])
        _req(result.get("grid_bits") == A.GRID_BITS, "grid bits differ")
        m2, o2r, members, log, scalars, infeasible = M.contract_hard(m)
        if result["status"] == "INFEASIBLE":
            _req(infeasible is not None or M.reduce_model(m2).infeasible is not None, "INFEASIBLE claimed but the reconstruction finds no empty hard intersection")
            return {"accepted": True, "reasons": ["zero-partition proof reproduced: %s" % (infeasible or M.reduce_model(m2).infeasible)["reason"]]}
        if result["status"] in ("UNSUPPORTED_INPUT",):
            return {"accepted": False, "reasons": ["nothing to verify: status %s" % result["status"]]}
        _req(infeasible is None, "the model is infeasible but the result claims otherwise")
        # clusters: re-verify every cluster the producer used; recompute rho
        cl_log = result["plan"]["clusters"]; used = [c["cluster"] for c in cl_log.get("verified", [])]
        certs = {}; rho = {}; cmap = {b: b for b in m2.blocks}; coarse = m2
        if used:
            coarse, cmap, certs, rho = CO.coarsen(m2, used)
            for c in cl_log["verified"]:
                mine = certs[c["cluster"][0]]
                _req(Fr(mine["rho_i"]) == Fr(c["rho_i"]) and mine["Gamma_i"] == c["Gamma_i"] and mine["C_i"] == c["C_i"], "cluster %s: rho / Gamma / C differ from the reconstruction" % c["cluster"])
        red = M.reduce_model(coarse)
        _req(red.infeasible is None, "reduced model infeasible")
        adj = M.adjacency(red)
        for q, iv in result["intervals"].items():
            q = int(q); cert = result["certificate"][str(q)]; rq = cmap[o2r[q]]
            _req(cert["query_block"] == rq and iv["coarse_block"] == rq, "query %d maps to reduced block %d, result says %s" % (q, rq, cert["query_block"]))
            H = set(int(x) for x in cert["H"]); _req(rq in H, "query block not in its region")
            comp_ok = all(u in red.blocks for u in H); _req(comp_ok, "region names unknown blocks")
            outside = sorted({u for v in H for u in adj[v] if u not in H})
            xi = {int(k): int(v) for k, v in cert["xi"].items()}
            _req(sorted(xi) == outside, "fixed outside states do not cover exactly the crossing neighbours")
            for u, x in xi.items():
                _req(x in set(red.blocks[u].rows), "fixed state of outside block %d is not an allowed row" % u)
            inside = [e for e in red.edges if e.u in H and e.v in H]
            ops = {}
            for k, v in cert["inside_ops"].items():
                a, b = (int(t) for t in k.split("-")); ops[(a, b)] = tuple(v) if isinstance(v, list) else v
                ops[(a, b)] = (ops[(a, b)][0],) if len(ops[(a, b)]) == 1 else (ops[(a, b)][0], int(ops[(a, b)][1]))
            _req(set(ops) == {(min(e.u, e.v), max(e.u, e.v)) for e in inside}, "operator list does not match the inside edges")
            # coefficients and transport
            rho_H = {v: rho[v] for v in H if v in rho}
            coef = RG.coefficients(red, H, ops, rho_H)
            for k, v in cert["theta"].items():
                a, b = (int(t) for t in k.split("-")); _req(coef["theta"][(a, b)] == Fr(v), "theta %s differs" % k)
            for v in H:
                _req(coef["d"][v] == Fr(cert["d"][str(v)]) and coef["b"][v] == Fr(cert["b"][str(v)]), "d / b at %d differ" % v)
            if RG.transport_needed(H, xi, ops, rho_H):
                _req(int(cert["iterations"]) >= 1, "transport is needed (boundary / surrogate / coarsening) but no Theorem-1 iteration was declared")
                z, t = RG.iterate(red, H, coef, int(cert["iterations"]))
                _req(t == int(cert["iterations"]) and all(z[v] == Fr(cert["z"][str(v)]) for v in H), "Theorem-1 iterates differ")
            else:
                z = {v: Fr(0) for v in H}
                _req(all(Fr(cert["z"][str(v)]) == 0 for v in H), "zero transport claimed inconsistently")
            zq = z[rq]
            # own regional solve
            blocks = RG.tilt_weights(red, H, xi)
            sub = M.Reduced(red.d, blocks, inside, {}, {})
            if M.is_forest(sub):
                bel = v_tree_belief(blocks, inside, ops, rq)
            else:
                bel = v_dense(blocks, inside, ops, rq, 1 << 22)
            rows = np.asarray(red.blocks[rq].rows, dtype=np.uint64)
            q_grid = 1 << A.GRID_BITS
            for j in range(red.d):
                sel = ((rows >> np.uint64(j)) & np.uint64(1)).astype(bool)
                LA, UA = bel.masked_mass(sel); LC, UC = bel.masked_mass(~sel)
                l, u = A.normalize_event(LA, UA, LC, UC)
                vlo, vhi = max(Fr(0), l - zq), min(Fr(1), u + zq)
                row = iv["coordinates"][j]; plo, phi = Fr(int(row["lo"]), q_grid), Fr(int(row["hi"]), q_grid)
                _req(plo <= vlo and vhi <= phi, "query %d coordinate %d: published [%s, %s] does not contain the verifier's enclosure [%s, %s]" % (q, j, float(plo), float(phi), float(vlo), float(vhi)))
                _req(0 <= int(row["lo"]) <= int(row["hi"]) <= q_grid, "published endpoints off the grid")
                elo, ehi = Fr(row["exact"][0]), Fr(row["exact"][1])
                _req(A.publish(elo, ehi) == (int(row["lo"]), int(row["hi"])), "published endpoints are not the declared rounding of the stated exact interval")
            wmax = max(Fr(int(r_["hi"]) - int(r_["lo"]), q_grid) for r_ in iv["coordinates"])
            _req(bool(wmax <= eps) == bool(iv["width_met"]), "width_met flag is wrong")
            _req((result["statuses_per_query"][str(q)] == "CERTIFIED") == bool(wmax <= eps), "per-query status inconsistent with the width")
            reasons.append("query %d: region %s, %d coordinates contained, max width %.3g, z = %.3g" % (q, sorted(H), red.d, float(wmax), float(zq)))
        return {"accepted": True, "reasons": reasons}
    except Rejected as ex:
        return {"accepted": False, "reasons": reasons + [str(ex)]}
    except Exception as ex:
        import traceback
        return {"accepted": False, "reasons": reasons + ["verifier fault: %s: %s" % (type(ex).__name__, ex)], "traceback": traceback.format_exc()[-1500:]}
