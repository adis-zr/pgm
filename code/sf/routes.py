"""Producers: S_h (sparse join radius h), F_k (streaming Fourier contraction, section 5), E (exact pair / distance-histogram contraction
with packed XOR/popcount and row aggregation; antipodal reversal when symmetry is verified), W (exact degree-filtered Walsh contraction),
PI (r = 0 endpoint). Exact integer arithmetic: every reported quantity is an integer or a Fraction; the common unnormalized scale is
A0 B0 v^n for pair sums and A0 B0 v^k for degree-k contractions. Each producer returns a record with exact interval endpoints (Fractions)
for every coordinate plus the integers the checker must reproduce."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import time
import numpy as np
from sf import core as C


def _popcount(a):
    return np.bitwise_count(a)


def _signs(masks, S):
    """chi_S(x) = prod_{j in S} x_j over an array of masks, with x_j = +1 iff bit j is set: (-1)^(number of CLEAR bits of x inside S)
    = (-1)^(|S| - popcount(mask & S)) (int8). The set-bit parity alone would be chi_S times (-1)^|S|."""
    pS = bin(int(S)).count("1")
    return 1 - 2 * (((np.bitwise_count(masks & np.uint64(S)).astype(np.int64) + pS) & 1)).astype(np.int8)


def subsets_up_to(n, k):
    """All subset masks with |S| <= k, grouped by degree, deterministic order (increasing degree, then increasing mask)."""
    out = {0: [0]}
    for d in range(1, k + 1):
        cur = []
        def rec(start, left, acc):
            if left == 0:
                cur.append(acc); return
            for j in range(start, n - left + 1):
                rec(j + 1, left - 1, acc | (1 << j))
        rec(0, d, 0)
        out[d] = cur
    return out


def interval_from_counts(Nint, Rint, Uint):
    """[N/(R+U), (N+U)/(R+U)] (section 2)."""
    den = Rint + Uint
    return Fr(Nint, den), Fr(Nint + Uint, den)


# ------------------------------------------------------------------ S_h
def route_S(law, r, h, deadline=None):
    t0 = time.monotonic(); n = law.n; u, v = C.uv(r)
    kap = [C.kappa_int(n, u, v, d) for d in range(n + 1)]
    bd = dict(zip(law.B_rows, law.B_w))
    Pint = 0; Rint = 0; Nint = [0] * n; pairs = 0
    for x, a in zip(law.A_rows, law.A_w):
        nbrs = [(x, 0)]
        if h >= 1:
            nbrs += [(x ^ (1 << j), 1) for j in range(n)]
        for y, d in nbrs:
            b = bd.get(y)
            if b is None:
                continue
            w = a * b; pairs += 1; Pint += w; wk = w * kap[d]; Rint += wk
            xx = x; i = 0
            while xx:
                if xx & 1:
                    Nint[i] += wk
                xx >>= 1; i += 1
        if deadline is not None:
            deadline()
    t1 = time.monotonic()
    A0B0 = law.A0 * law.B0
    if Rint <= 0:
        return {"route": "S%d" % h, "status": "REJECT", "reason": "retained mass R_h = 0 (empty retained pair set): the sparse route cannot certify; at r = 1 the law is undefined", "pairs": pairs, "wall": {"construction": t1 - t0}}
    Uint = (A0B0 - Pint) * kap[h + 1] if h < n else 0
    iv = [interval_from_counts(Nint[i], Rint, Uint) for i in range(n)]
    t2 = time.monotonic()
    return {"route": "S%d" % h, "status": "OK", "h": h, "pairs_retained": pairs, "P_int": Pint, "R_int": Rint, "U_int": Uint, "N_int": Nint, "scale": "A0 B0 v^n", "A0B0": A0B0,
            "rho": Fr(Uint, Rint + Uint), "intervals": iv, "max_bits": max(Rint.bit_length(), Uint.bit_length()),
            "wall": {"construction": t1 - t0, "certificate": t2 - t1}}


# ------------------------------------------------------------------ F_k (streaming; section 5)
def route_F(law, r, k, symmetric, deadline=None):
    t0 = time.monotonic(); n = law.n; u, v = C.uv(r); k = min(k, n)
    subs = subsets_up_to(n, k)
    Y = law.Y; bw = np.array(law.B_w, dtype=np.int64)
    # beta_S integers for |S| <= k (vectorized over y per subset)
    beta = {}
    for d in range(k + 1):
        for S in subs[d]:
            beta[S] = int(np.dot(_signs(Y, S).astype(np.int64), bw))
        if deadline is not None:
            deadline()
    t1 = time.monotonic()
    # g_k(x) integers: Σ_S u^|S| v^(k-|S|) beta_S chi_S(x), vectorized over x per subset; object dtype if the bound exceeds int64
    X = law.X
    bound = sum(abs(beta[S]) * u ** d * v ** (k - d) for d in range(k + 1) for S in subs[d])
    use_obj = bound.bit_length() >= 62
    g = np.zeros(law.mA, dtype=object if use_obj else np.int64)
    for d in range(k + 1):
        cd = u ** d * v ** (k - d)
        for S in subs[d]:
            coef = cd * beta[S]
            if coef == 0:
                continue
            s = _signs(X, S)
            if use_obj:
                g += np.array([coef] * law.mA, dtype=object) * s.astype(object)
            else:
                g += np.int64(coef) * s.astype(np.int64)
        if deadline is not None:
            deadline()
    aw = np.array(law.A_w, dtype=object if use_obj else np.int64)
    gl = g.tolist(); awl = law.A_w
    Zk = sum(int(a) * int(gg) for a, gg in zip(awl, gl))
    Mk = [0] * n
    for x, a, gg in zip(law.A_rows, awl, gl):
        ag = int(a) * int(gg); xx = x; i = 0
        while i < n:
            Mk[i] += ag if (xx & 1) else -ag
            xx >>= 1; i += 1
    t2 = time.monotonic()
    scale = law.A0 * law.B0 * v ** k
    rec = {"route": "F%d" % k, "k": k, "N_k": sum(len(subs[d]) for d in subs), "Zk_int": Zk, "Mk_int": Mk, "scale": "A0 B0 v^k", "scale_int": scale, "beta_int": {str(S): b for S, b in beta.items()} if law.mA <= 512 else None,
           "object_dtype": use_obj, "max_bits": max(abs(Zk).bit_length(), max(abs(m).bit_length() for m in Mk)), "symmetric_used": bool(symmetric)}
    if Zk <= 0:
        rec.update({"status": "REFUSE", "reason": "Z_k <= 0: the ratio certificate refuses", "wall": {"construction": t1 - t0, "evaluation": t2 - t1}}); return rec
    if symmetric and n % 2 == 0:
        ez, em = C.eta_parity(n, k, Fr(u, v)); rec["tails"] = "parity-refined (verified antipodal symmetry)"
    else:
        ez = em = C.tau(n, k, Fr(u, v)); rec["tails"] = "generic"
    Zq = Fr(Zk, scale)
    e = (ez + em) / (2 * Zq)
    iv = []
    for i in range(n):
        c = Fr(Zk + Mk[i], 2 * Zk)
        iv.append((max(Fr(0), c - e), min(Fr(1), c + e)))
    t3 = time.monotonic()
    rec.update({"status": "OK", "eta_Z": ez, "eta_M": em, "Z_k": Zq, "radius": e, "intervals": iv, "wall": {"construction": t1 - t0, "evaluation": t2 - t1, "certificate": t3 - t2}})
    return rec


# ------------------------------------------------------------------ E (exact pair / histogram contraction; row aggregation; antipodal reversal)
def route_E(law, r, symmetric, deadline=None, chunk=512):
    t0 = time.monotonic(); n = law.n; u, v = C.uv(r)
    kap = [C.kappa_int(n, u, v, d) for d in range(n + 1)]
    Y = law.Y; bw = np.array(law.B_w, dtype=np.float64)
    assert law.B0 < (1 << 53)
    rows = law.A_rows; aw = law.A_w
    # with VERIFIED symmetry, histogram one row of each antipodal pair; the antipode's histogram is the reversal d -> n-d
    if symmetric:
        idx = {x: i for i, x in enumerate(rows)}; todo = []; seen = set()
        for x in rows:
            if x in seen:
                continue
            todo.append(x); seen.add(x); seen.add(law.full ^ x)
    else:
        todo = rows
    X = np.array(todo, dtype=np.uint64); hist = {}
    for s in range(0, len(todo), chunk):
        xs = X[s:s + chunk]
        D = _popcount(xs[:, None] ^ Y[None, :]).astype(np.int64)                    # (chunk, mB) distances
        ids = (np.arange(len(xs), dtype=np.int64)[:, None] * (n + 1) + D).ravel()
        cnt = np.bincount(ids, weights=np.broadcast_to(bw, D.shape).ravel(), minlength=len(xs) * (n + 1)).reshape(len(xs), n + 1)
        for j, x in enumerate(todo[s:s + chunk]):
            hist[x] = [int(round(c)) for c in cnt[j]]
        if deadline is not None:
            deadline()
    t1 = time.monotonic()
    Zint = 0; Nint = [0] * n; rowmass = {}
    for x, a in zip(rows, aw):
        if x in hist:
            hm = sum(hist[x][d] * kap[d] for d in range(n + 1))
        else:
            hx = hist[law.full ^ x]; hm = sum(hx[n - d] * kap[d] for d in range(n + 1))
        rowmass[x] = hm; ahm = a * hm; Zint += ahm
        xx = x; i = 0
        while xx:
            if xx & 1:
                Nint[i] += ahm
            xx >>= 1; i += 1
    t2 = time.monotonic()
    if Zint <= 0:
        return {"route": "E", "status": "REJECT", "reason": "Z = 0: the law is undefined (r = 1 with empty intersection)", "wall": {"construction": t1 - t0, "evaluation": t2 - t1}}
    iv = [(Fr(Nint[i], Zint), Fr(Nint[i], Zint)) for i in range(n)]
    return {"route": "E", "status": "OK", "Z_int": Zint, "N_int": Nint, "scale": "A0 B0 v^n", "rows_histogrammed": len(todo), "symmetric_halving": bool(symmetric), "max_bits": Zint.bit_length(),
            "intervals": iv, "exact": True, "wall": {"construction": t1 - t0, "evaluation": t2 - t1, "certificate": 0.0}}


# ------------------------------------------------------------------ W (exact degree-filtered Walsh contraction)
def fwht_int64(a):
    """In-place-style iterative Walsh-Hadamard transform (unnormalized) on an int64 array of length 2^n."""
    h = 1; m = a.shape[0]
    while h < m:
        a = a.reshape(-1, 2, h)
        x, y = a[:, 0, :].copy(), a[:, 1, :]
        a[:, 0, :] = x + y; a[:, 1, :] = x - y
        a = a.reshape(m); h *= 2
    return a


def route_W(law, r, deadline=None):
    t0 = time.monotonic(); n = law.n; u, v = C.uv(r); m = 1 << n
    bvec = np.zeros(m, dtype=np.int64); bvec[law.Y.astype(np.int64)] = np.array(law.B_w, dtype=np.int64)
    Wb = fwht_int64(bvec.copy())                                        # beta_S integers for ALL S
    pc = _popcount(np.arange(m, dtype=np.uint64)).astype(np.int64)
    Xi = law.X.astype(np.int64); aw = np.array(law.A_w, dtype=np.int64)
    bits = np.array([[(x >> i) & 1 for i in range(n)] for x in law.A_rows], dtype=np.int64)   # (mA, n)
    Tagg = []; Tagg_i = []
    t1 = time.monotonic()
    for d in range(n + 1):
        Td = fwht_int64(np.where(pc == d, Wb, 0).astype(np.int64))       # T_d(x) = Σ_{|S|=d} beta_S chi_S(x), exact int64 (|T_d| <= C(n,d) B0)
        tx = Td[Xi]                                                        # at the rows of A
        Tagg.append(int(np.dot(aw, tx)))
        Tagg_i.append([int(np.dot(aw * bits[:, i], tx)) for i in range(n)])
        if deadline is not None:
            deadline()
    t2 = time.monotonic()
    Zint = sum(u ** d * v ** (n - d) * Tagg[d] for d in range(n + 1))
    Nint = [sum(u ** d * v ** (n - d) * Tagg_i[d][i] for d in range(n + 1)) for i in range(n)]
    if Zint <= 0:
        return {"route": "W", "status": "REJECT", "reason": "Z = 0", "wall": {"construction": t1 - t0, "evaluation": t2 - t1}}
    iv = [(Fr(Nint[i], Zint), Fr(Nint[i], Zint)) for i in range(n)]
    return {"route": "W", "status": "OK", "Z_int": Zint, "N_int": Nint, "scale": "A0 B0 v^n", "transforms": n + 2, "max_bits": Zint.bit_length(), "intervals": iv, "exact": True,
            "wall": {"construction": t1 - t0, "evaluation": t2 - t1, "certificate": 0.0}}


# ------------------------------------------------------------------ PI (r = 0)
def route_PI(law):
    t0 = time.monotonic()
    num = law.pi_plus_int()
    iv = [(Fr(num[i], law.A0), Fr(num[i], law.A0)) for i in range(law.n)]
    return {"route": "PI", "status": "OK", "N_int": num, "Z_int": law.A0, "scale": "A0", "intervals": iv, "exact": True, "max_bits": law.A0.bit_length(), "wall": {"construction": time.monotonic() - t0, "evaluation": 0.0, "certificate": 0.0}}


def run_route(law, r, route, params, symmetric, deadline=None):
    if route == "PI":
        return route_PI(law)
    if route[0] == "S":
        return route_S(law, r, params.get("h", int(route[1])), deadline)
    if route[0] == "F":
        return route_F(law, r, params.get("k", int(route[1])), symmetric, deadline)
    if route == "E":
        return route_E(law, r, symmetric, deadline)
    if route == "W":
        return route_W(law, r, deadline)
    raise ValueError(route)
