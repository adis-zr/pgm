"""INDEPENDENT checkers: reconstruct the law, query coverage, normalization, claimed symmetry, moments / retained pairs / histograms,
residual bounds and final endpoints from the RAW input rows; never accept producer values on trust. Separate code paths from
sf.routes: S via sorted-array intersection and set membership; F via the section-3 moment identity (alpha_S for |S| <= k+1,
beta_S for |S| <= k, contracted per degree; the producer uses the section-5 streaming form); E via the TRANSPOSED accumulation
(loop over y, vectorized over x, with the coordinate split done by bit masks); W via the pair reconstruction (frozen). Tails via
math.comb (the producer's tails are compared exactly).
ARITHMETIC DOMAIN (sixth adversarial review, 15 Nov 2026, F02): weights are positive integers of ARBITRARY size; every fixed-width (int64 / float64) accumulation in this
checker is executed only while a PRE-OPERATION bound proves every intermediate in range (the sum of the weights accumulated so far), else exact Python integers are used;
the zero-order moments must reconcile with the exact totals (a necessary cross-check, never the proof).
PREMISE CHECKS (fifth adversarial review, 14 Nov 2026, R01): every bound is accepted only inside the domain its reconstruction actually covers -- the sparse route's
radius must be one of SPARSE_RADII (distances 0 and 1 are enumerated; nothing deeper is reconstructed) and the omitted-region bound is derived from the RECONSTRUCTED
retained set; the spectral degree must lie in 0..n; the route label must name the declared parameter. Out-of-domain parameters are refused, never coerced."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import numpy as np
from . import core as C


class CheckFailure(Exception):
    pass


def _req(cond, msg):
    if not cond:
        raise CheckFailure(msg)


def _kappa(n, u, v, d):
    return (v + u) ** (n - d) * (v - u) ** d


def _common(law, rec, r, claimed_symmetric):
    """Shared obligations: coverage, normalization, symmetry claim, grid publication of every interval."""
    n = law.n
    _req(len(rec["intervals"]) == n, "query coverage: %d intervals for n = %d" % (len(rec["intervals"]), n))
    _req(law.A0 == sum(law.A_w) and law.B0 == sum(law.B_w), "normalization totals differ")
    sym, how = law.antipodal()
    _req(bool(claimed_symmetric) == sym, "symmetry claim (%s) differs from the reconstruction (%s: %s)" % (claimed_symmetric, sym, how))
    pub = rec["published"]
    _req(len(pub) == n, "published rows missing")
    for i, ((lo, hi), (lg, hg)) in enumerate(zip(rec["intervals"], pub)):
        lo, hi = Fr(lo), Fr(hi)
        _req(0 <= lo <= hi <= 1, "coordinate %d: exact endpoints not ordered in [0,1]" % i)
        elg, ehg = C.publish(lo, hi)
        _req(int(lg) == elg and int(hg) == ehg, "coordinate %d: published grid endpoints are not the outward rounding of the exact interval" % i)
        _req(0 <= lg <= hg <= (1 << C.GRID_BITS), "coordinate %d: published endpoints off the grid / unordered" % i)
    return sym


SPARSE_RADII = (0, 1)          # the IMPLEMENTED reconstruction depth: this checker enumerates retained pairs at Hamming distance 0 (sorted intersection) and 1 (XOR
                               # neighbours) and nothing deeper; a certificate whose omitted-region bound presumes a deeper enumeration is OUTSIDE the proof it can
                               # reconstruct and is REFUSED (fifth review R01: route S1 with a declared h = n would set U = 0 without covering the omitted pairs)


def check_S(law, r, rec, claimed_symmetric):
    sym = _common(law, rec, r, claimed_symmetric)
    n = law.n; u, v = C.uv(r)
    # ---- PREMISES of the sparse bound (checked BEFORE any arithmetic): the radius must be one this checker reconstructs completely, the route label must name that
    # radius, and the record must declare it as a non-negative integer (a negative, fractional, intermediate or >= n radius is refused, never coerced)
    h_raw = rec.get("h"); route = str(rec.get("route", ""))
    _req(isinstance(h_raw, (int, str)) and not isinstance(h_raw, bool) and str(h_raw).strip().lstrip("-").isdigit(), "S: radius h is not an integer record (%r)" % (h_raw,))
    h = int(h_raw)
    _req(h in SPARSE_RADII, "S: declared radius h = %d is outside the reconstructed radius domain %s (this checker enumerates distances 0..1 only; a bound for h = %d is not reconstructible)" % (h, SPARSE_RADII, h))
    _req(route == "S%d" % h, "S: route label %r does not name the declared radius h = %d" % (route, h))
    A = np.array(law.A_rows, dtype=np.uint64); B = np.array(law.B_rows, dtype=np.uint64)
    aw = dict(zip(law.A_rows, law.A_w)); bset = set(law.B_rows); bw = dict(zip(law.B_rows, law.B_w))
    # radius 0 via sorted intersection; radius 1 via XOR neighbours tested against a set
    inter = np.intersect1d(A, B)
    P = 0; R = 0; N = [0] * n; pairs = 0
    kap = [_kappa(n, u, v, d) for d in range(n + 1)]
    for x in inter.tolist():
        w = aw[x] * bw[x]; P += w; R += w * kap[0]; pairs += 1
        for i in range(n):
            if (x >> i) & 1:
                N[i] += w * kap[0]
    if h >= 1:
        for x, a in aw.items():
            for j in range(n):
                y = x ^ (1 << j)
                if y in bset:
                    w = a * bw[y]; P += w; R += w * kap[1]; pairs += 1
                    for i in range(n):
                        if (x >> i) & 1:
                            N[i] += w * kap[1]
    # ---- the omitted-region bound is DERIVED from the reconstructed retained set: every omitted pair has distance >= h + 1 (the enumeration above is complete through
    # distance h), kappa is non-increasing in the distance, hence U = (A0 B0 - P_reconstructed) * kappa_{h+1}; when h >= n (only n = 1, h = 1 inside SPARSE_RADII) every
    # pair has been enumerated and U = 0 is exact
    U = (law.A0 * law.B0 - P) * kap[h + 1] if h < n else 0
    _req(int(rec["P_int"]) == P and int(rec["R_int"]) == R and int(rec["U_int"]) == U, "S%d: retained mass / omitted bound differ from the reconstruction" % h)
    _req([int(x) for x in rec["N_int"]] == N, "S%d: numerators differ" % h)
    _req(R > 0, "S%d: R = 0" % h)
    for i in range(n):
        lo, hi = Fr(N[i], R + U), Fr(N[i] + U, R + U)
        _req(Fr(rec["intervals"][i][0]) == lo and Fr(rec["intervals"][i][1]) == hi, "S%d: interval %d differs" % (h, i))
    return {"ok": True, "pairs": pairs, "symmetry_reconstructed": sym}


def _subsets(n, k):
    out = {0: [0]}
    for d in range(1, k + 1):
        cur = []
        def rec(start, left, acc):
            if left == 0:
                cur.append(acc); return
            for j in range(start, n - left + 1):
                rec(j + 1, left - 1, acc | (1 << j))
        rec(0, d, 0); out[d] = cur
    return out


INT64_SAFE = 1 << 62          # the checker's fixed-width accumulation is used only while a PRE-OPERATION bound (the sum of the weights added since the last flush) proves every entry in range


def _moments_rowwise(masks, weights, Sarr):
    """Σ_x w(x) chi_S(x) for every S in Sarr, vectorized over SUBSETS per row (the opposite axis from the producer). EXACT for arbitrary positive integer weights:
    `pending` is the sum of the weights accumulated in the int64 buffer since its last flush, hence a bound on |every entry|; BEFORE adding w the buffer is flushed to
    exact Python integers unless pending + w < 2^62; a single weight >= 2^62 is added to the exact accumulator directly (never to the int64 buffer)."""
    acc = np.zeros(len(Sarr), dtype=object)
    S64 = Sarr.astype(np.uint64)
    tmp = np.zeros(len(Sarr), dtype=np.int64); pending = 0
    pS = np.array([bin(int(S)).count("1") for S in Sarr.tolist()], dtype=np.int64)        # |S|
    for x, w in zip(masks, weights):
        par = ((pS - np.bitwise_count(np.uint64(x) & S64).astype(np.int64)) & 1)           # CLEAR bits of x inside S: chi_S(x) = (-1)^par
        sg = (1 - 2 * par)
        if w >= INT64_SAFE:
            if pending: acc += tmp.astype(object); tmp[:] = 0; pending = 0
            acc += int(w) * sg.astype(object); continue
        if pending + w >= INT64_SAFE:
            acc += tmp.astype(object); tmp[:] = 0; pending = 0
        tmp += np.int64(w) * sg; pending += w
    acc += tmp.astype(object)
    return acc


def check_F(law, r, rec, claimed_symmetric):
    sym = _common(law, rec, r, claimed_symmetric)
    n = law.n; u, v = C.uv(r); k_raw = rec.get("k")
    _req(isinstance(k_raw, (int, str)) and not isinstance(k_raw, bool) and str(k_raw).strip().lstrip("-").isdigit(), "F: degree k is not an integer record (%r)" % (k_raw,))
    k = int(k_raw); _req(0 <= k <= n, "F: degree k = %d outside 0..n (n = %d)" % (k, n)); _req(str(rec.get("route", "")) == "F%d" % k, "F: route label %r does not name the declared degree k = %d" % (rec.get("route"), k))
    subs_k1 = _subsets(n, min(k + 1, n)); subs_k = {d: subs_k1[d] for d in range(k + 1)}
    Sk1 = np.array([S for d in subs_k1 for S in subs_k1[d]], dtype=np.uint64); Sk = np.array([S for d in subs_k for S in subs_k[d]], dtype=np.uint64)
    alpha = dict(zip(Sk1.tolist(), (int(x) for x in _moments_rowwise(law.A_rows, law.A_w, Sk1))))
    beta = dict(zip(Sk.tolist(), (int(x) for x in _moments_rowwise(law.B_rows, law.B_w, Sk))))
    _req(alpha[0] == law.A0 and beta[0] == law.B0, "F%d: zero-order moments (%d, %d) do not reconcile with the exact totals (%d, %d)" % (k, alpha[0], beta[0], law.A0, law.B0))      # NECESSARY cross-check (the bound above is the proof)
    # section-3 identities: Z_k = Σ_{|S|<=k} r^|S| alpha_S beta_S ; M_{i,k} = Σ_{|S|<=k} r^|S| alpha_{S Δ {i}} beta_S  (scale A0 B0 v^k)
    Zk = 0; Mk = [0] * n
    for d in range(k + 1):
        cd = u ** d * v ** (k - d)
        for S in subs_k[d]:
            b = beta[S]
            if b == 0:
                continue
            Zk += cd * alpha[S] * b
            for i in range(n):
                Mk[i] += cd * alpha[S ^ (1 << i)] * b
    _req(int(rec["Zk_int"]) == Zk, "F%d: Z_k differs from the moment reconstruction" % k)
    _req([int(x) for x in rec["Mk_int"]] == Mk, "F%d: M_{i,k} differ" % k)
    _req(Zk > 0, "F%d: Z_k <= 0 must refuse" % k)
    if sym and n % 2 == 0:
        ez = sum((comb(n, d) * Fr(u, v) ** d for d in range(k + 1, n + 1) if d % 2 == 0), Fr(0)); em = sum((comb(n, d) * Fr(u, v) ** d for d in range(k + 1, n + 1) if d % 2 == 1), Fr(0))
        if sym:
            for S, a in alpha.items():
                if bin(S).count("1") % 2 == 1:
                    _req(a == 0, "verified symmetry but an odd moment alpha_S is nonzero (S = %d)" % S)
    else:
        ez = em = sum((comb(n, d) * Fr(u, v) ** d for d in range(k + 1, n + 1)), Fr(0))
    _req(Fr(rec["eta_Z"]) == ez and Fr(rec["eta_M"]) == em, "F%d: residual bounds differ" % k)
    scale = law.A0 * law.B0 * v ** k; Zq = Fr(Zk, scale); e = (ez + em) / (2 * Zq)
    for i in range(n):
        c = Fr(Zk + Mk[i], 2 * Zk); lo, hi = max(Fr(0), c - e), min(Fr(1), c + e)
        _req(Fr(rec["intervals"][i][0]) == lo and Fr(rec["intervals"][i][1]) == hi, "F%d: interval %d differs" % (k, i))
    return {"ok": True, "moments": len(alpha) + len(beta), "symmetry_reconstructed": sym}


def _pair_reconstruction(law, r, chunk=256):
    """TRANSPOSED exact accumulation: loop over y-chunks, vectorized over ALL x; per-y distance histograms split by each x-coordinate."""
    n = law.n; u, v = C.uv(r)
    kap = [_kappa(n, u, v, d) for d in range(n + 1)]
    X = law.X; Y = law.Y; Z = 0; N = [0] * n
    # the per-y distance histograms of the A weights (and of the A weights restricted to each set coordinate) are EXACT for arbitrary weights: every partial sum is bounded by
    # A0, so float64 bincount is used only when A0 < 2^53, int64 scatter-add when A0 < 2^62, else Python integers (bound decided BEFORE the accumulation)
    if law.A0 < (1 << 53): mode = 'float64'
    elif law.A0 < INT64_SAFE: mode = 'int64'
    else: mode = 'object'
    for s in range(0, law.mB, chunk):
        ys = Y[s:s + chunk]; bws = law.B_w[s:s + chunk]; ny = len(ys)
        D = np.bitwise_count(ys[:, None] ^ X[None, :]).astype(np.int64)                                 # (chunk, mA)
        if mode == 'float64':
            aw = np.array(law.A_w, dtype=np.float64); bits = np.array([[(x >> i) & 1 for i in range(n)] for x in law.A_rows], dtype=np.float64)
            ids = (np.arange(ny)[:, None] * (n + 1) + D).ravel()
            tot = np.bincount(ids, weights=np.broadcast_to(aw, D.shape).ravel(), minlength=ny * (n + 1)).reshape(ny, n + 1)
            per_i = [np.bincount(ids, weights=np.broadcast_to(aw * bits[:, i], D.shape).ravel(), minlength=ny * (n + 1)).reshape(ny, n + 1) for i in range(n)]
            T = [[int(round(tot[j, d])) for d in range(n + 1)] for j in range(ny)]; P = [[[int(round(per_i[i][j, d])) for d in range(n + 1)] for i in range(n)] for j in range(ny)]
        elif mode == 'int64':
            aw = np.array(law.A_w, dtype=np.int64); rows_idx = np.repeat(np.arange(ny), D.shape[1]); dv = D.ravel()
            tot = np.zeros((ny, n + 1), dtype=np.int64); np.add.at(tot, (rows_idx, dv), np.tile(aw, ny)); T = tot.tolist(); P = []
            for j in range(ny): P.append([])
            for i in range(n):
                awi = np.array([a if (x >> i) & 1 else 0 for x, a in zip(law.A_rows, law.A_w)], dtype=np.int64); pi = np.zeros((ny, n + 1), dtype=np.int64); np.add.at(pi, (rows_idx, dv), np.tile(awi, ny)); pl = pi.tolist()
                for j in range(ny): P[j].append(pl[j])
        else:
            T = []; P = []
            for j in range(ny):
                h = [0] * (n + 1); hi_ = [[0] * (n + 1) for _ in range(n)]
                for xi, (x, a) in enumerate(zip(law.A_rows, law.A_w)):
                    d = int(D[j, xi]); h[d] += a
                    for i in range(n):
                        if (x >> i) & 1: hi_[i][d] += a
                T.append(h); P.append(hi_)
        for j, b in enumerate(bws):
            Z += b * sum(T[j][d] * kap[d] for d in range(n + 1))
            for i in range(n):
                N[i] += b * sum(P[j][i][d] * kap[d] for d in range(n + 1))
    return Z, N


def check_exact(law, r, rec, claimed_symmetric):
    """E and W: exact totals and every numerator reconciled against the transposed pair reconstruction."""
    sym = _common(law, rec, r, claimed_symmetric)
    Z, N = _pair_reconstruction(law, r)
    _req(int(rec["Z_int"]) == Z, "%s: Z differs from the pair reconstruction" % rec["route"])
    _req([int(x) for x in rec["N_int"]] == N, "%s: numerators differ" % rec["route"])
    for i in range(law.n):
        _req(Fr(rec["intervals"][i][0]) == Fr(N[i], Z) == Fr(rec["intervals"][i][1]), "%s: interval %d is not the exact point" % (rec["route"], i))
    return {"ok": True, "symmetry_reconstructed": sym, "checker": "transposed exact pair reconstruction"}


def check_PI(law, r, rec, claimed_symmetric):
    sym = _common(law, rec, r, claimed_symmetric)
    _req(Fr(r) == 0, "PI route only at r = 0")
    num = [0] * law.n
    for x, a in zip(law.A_rows, law.A_w):
        for i in range(law.n):
            if (x >> i) & 1:
                num[i] += a
    _req([int(x) for x in rec["N_int"]] == num and int(rec["Z_int"]) == law.A0, "PI: marginals differ")
    for i in range(law.n):
        _req(Fr(rec["intervals"][i][0]) == Fr(num[i], law.A0) == Fr(rec["intervals"][i][1]), "PI: interval %d" % i)
    return {"ok": True, "symmetry_reconstructed": sym}


def check(law, r, rec, claimed_symmetric):
    route = rec["route"]
    if route == "PI":
        return check_PI(law, r, rec, claimed_symmetric)
    if route[0] == "S":
        return check_S(law, r, rec, claimed_symmetric)
    if route[0] == "F":
        return check_F(law, r, rec, claimed_symmetric)
    if route in ("E", "W"):
        return check_exact(law, r, rec, claimed_symmetric)
    raise ValueError(route)
