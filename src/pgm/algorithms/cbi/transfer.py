"""Transfer operators on cavity ENCLOSURES (IVec over the source block's rows -> IVec over the target block's rows) for one edge with
coupling r = u/v acting on the coordinate mask S (d' = |S|). Every output is a rigorous enclosure of the exact message
m(y) = sum_x q(x) K_r^S(x,y) up to the positive scalar v^d' (dropped; marginals are scale-free).
  exact   : per-target distance histograms (limb-split exact bincount) x kappa_d                      -- exact up to the dyadic rounding
  sparse_h: all source rows within Hamming radius h of y are enumerated (every distance through h), omitted mass bounded by
            kappa_{d'} (below) and kappa_{h+1} (above)                                                  -- Part I §9
  fourier_k: degree-k character expansion of the S-projected cavity; residual E = Q tau_even + D tau_odd with the antipodal defect D
            measured on the ACTUAL cavity; lower >= Q (1-r)^d', upper <= Q (1+r)^d'                   -- Part I §9
Signed intermediate rows are kept as intervals; nonnegativity of the final enclosure is enforced by the proved caps."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import itertools
import numpy as np
from . import arith as A


def mask_bits(mask):
    return [j for j in range(mask.bit_length()) if (mask >> j) & 1]


def subsets_of_mask(mask, k):
    """Subset masks T ⊆ mask with |T| <= k, grouped by size."""
    bits = mask_bits(mask); out = {0: [0]}
    for j in range(1, k + 1):
        out[j] = [sum(1 << b for b in c) for c in itertools.combinations(bits, j)] if j <= len(bits) else []
    return out


def chi(masks, T):
    """chi_T(x) over a uint64 array: (-1)^(clear bits of x inside T)."""
    pT = bin(int(T)).count("1")
    return 1 - 2 * ((pT - np.bitwise_count(masks & np.uint64(T)).astype(np.int64)) & 1)


def transfer_exact(cav, src_rows, tgt_rows, mask, r, deadline=None):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    Hlo = A.hist_by_distance(src_rows, cav.lo.tolist(), tgt_rows, mask, dp, deadline=deadline)
    same = all(int(a) == int(b) for a, b in zip(cav.lo.tolist(), cav.hi.tolist()))
    Hhi = Hlo if same else A.hist_by_distance(src_rows, cav.hi.tolist(), tgt_rows, mask, dp, deadline=deadline)
    lo = [sum(h[dd] * kap[dd] for dd in range(dp + 1)) for h in Hlo]
    hi = lo if same else [sum(h[dd] * kap[dd] for dd in range(dp + 1)) for h in Hhi]
    return A.IVec(lo, list(hi), cav.exp).normalize(), {"operator": "exact", "pairs": len(src_rows) * len(tgt_rows)}


def transfer_sparse(cav, src_rows, tgt_rows, mask, r, h, deadline=None):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if h >= dp:
        return transfer_exact(cav, src_rows, tgt_rows, mask, r, deadline=deadline)
    kap = [A.kappa_int(dp, u, v, dd) for dd in range(dp + 1)]
    flips = subsets_of_mask(mask, h)                      # EVERY distance 0..h is enumerated
    Qlo, Qhi = cav.mass(); lo = []; hi = []; looked = 0
    L = cav.lo.tolist(); Hh = cav.hi.tolist()
    # AGGREGATE the cavity per S-projected state ONCE (rows differing only outside S share a projection): one (lo, hi) per projection
    agg = {}
    for i, x in enumerate(src_rows):
        p = x & mask; a = agg.get(p)
        agg[p] = (L[i], Hh[i]) if a is None else (a[0] + L[i], a[1] + Hh[i])
    for t, y in enumerate(tgt_rows):
        if deadline is not None and (t & 255) == 0:
            deadline()
        yp = y & mask; Clo = Chi = Blo = Bhi = 0
        for dd in range(h + 1):
            kd = kap[dd]
            for f in flips[dd]:
                a = agg.get(yp ^ f)
                if a is not None:
                    looked += 1; Clo += a[0] * kd; Chi += a[1] * kd; Blo += a[0]; Bhi += a[1]
        lo.append(Clo + kap[dp] * (Qlo - Blo)); hi.append(Chi + kap[h + 1] * (Qhi - Bhi))
    return A.IVec(lo, hi, cav.exp).normalize(), {"operator": "sparse", "h": h, "lookups": looked, "flip_masks": sum(len(flips[j]) for j in flips), "projected_states": len(agg)}


def antipodal_defect_upper(cav, src_rows, mask):
    """D <= Q_hi - sum_{p in S-projected support} min(lo(p), lo(p ^ S)) (projection aggregates rows sharing their S bits)."""
    agg_lo = {}; agg_hi = {}
    for i, x in enumerate(src_rows):
        p = x & mask; agg_lo[p] = agg_lo.get(p, 0) + int(cav.lo[i]); agg_hi[p] = agg_hi.get(p, 0) + int(cav.hi[i])
    Qhi = sum(agg_hi.values()); s = 0
    for p, l in agg_lo.items():
        s += min(l, agg_lo.get(p ^ mask, 0))
    return max(0, Qhi - s), {"projected_rows": len(agg_lo), "exact_antipodal": (Qhi - s) == 0 and all(int(a) == int(b) for a, b in zip(cav.lo.tolist(), cav.hi.tolist()))}


def transfer_fourier(cav, src_rows, tgt_rows, mask, r, k, deadline=None):
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if k >= dp:
        return transfer_exact(cav, src_rows, tgt_rows, mask, r, deadline=deadline)
    subs = subsets_of_mask(mask, k)
    X = np.asarray(src_rows, dtype=np.uint64); Y = np.asarray(tgt_rows, dtype=np.uint64)
    lo_arr = cav.lo; hi_arr = cav.hi
    Qlo, Qhi = cav.mass()
    hlo = np.array([0] * len(tgt_rows), dtype=object); hhi = np.array([0] * len(tgt_rows), dtype=object)
    nfeat = 0
    for j in range(k + 1):
        c = u ** j * v ** (dp - j)
        for T in subs[j]:
            nfeat += 1
            if deadline is not None and (nfeat & 63) == 0:
                deadline()
            sx = chi(X, T)
            pos = sx > 0
            qlo = int(lo_arr[pos].sum()) - int(hi_arr[~pos].sum()); qhi = int(hi_arr[pos].sum()) - int(lo_arr[~pos].sum())
            sy = chi(Y, T) > 0
            # term r^|T| chi_T(y) q_T with q_T in [qlo, qhi]: lower = c*qlo where chi=+1, -c*qhi where chi=-1 (Python ints, no C long)
            a_lo, a_hi, b_lo, b_hi = c * qlo, c * qhi, -c * qhi, -c * qlo
            tlo = np.array([a_lo if p_ else b_lo for p_ in sy.tolist()], dtype=object); thi = np.array([a_hi if p_ else b_hi for p_ in sy.tolist()], dtype=object)
            hlo = hlo + tlo; hhi = hhi + thi
    D_up, dinfo = antipodal_defect_upper(cav, src_rows, mask)
    te = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 0)
    to = sum(comb(dp, j) * u ** j * v ** (dp - j) for j in range(k + 1, dp + 1) if j % 2 == 1)
    E = Qhi * te + D_up * to                                   # Q tau_even + D tau_odd, scaled by v^d'
    cap_lo = Qlo * (v - u) ** dp; cap_hi = Qhi * (v + u) ** dp
    lo = [max(cap_lo, int(x) - E) for x in hlo.tolist()]; hi = [min(cap_hi, int(x) + E) for x in hhi.tolist()]
    return A.IVec(lo, hi, cav.exp).normalize(), {"operator": "fourier", "k": k, "features": nfeat, "residual_scaled": str(E), "antipodal_defect_upper": str(D_up), **dinfo}


def transfer_poly(cav, src_rows, tgt_rows, mask, r, k, deadline=None):
    """EXACT transfer of the degree-k truncated kernel K~_k = sum_{|T|<=k} r^|T| chi_T(x) chi_T(y) (the REGION_SURROGATE factor):
    no residual term; the enclosure only carries the dyadic rounding of the cavity. Scaled by v^d' like the others."""
    dp = bin(mask).count("1"); u, v = A.uv(r)
    if k >= dp:
        return transfer_exact(cav, src_rows, tgt_rows, mask, r, deadline=deadline)
    subs = subsets_of_mask(mask, k)
    X = np.asarray(src_rows, dtype=np.uint64); Y = np.asarray(tgt_rows, dtype=np.uint64)
    hlo = np.array([0] * len(tgt_rows), dtype=object); hhi = np.array([0] * len(tgt_rows), dtype=object); nfeat = 0
    for j in range(k + 1):
        c = u ** j * v ** (dp - j)
        for T in subs[j]:
            nfeat += 1
            if deadline is not None and (nfeat & 63) == 0:
                deadline()
            pos = chi(X, T) > 0
            qlo = int(cav.lo[pos].sum()) - int(cav.hi[~pos].sum()); qhi = int(cav.hi[pos].sum()) - int(cav.lo[~pos].sum())
            sy = chi(Y, T) > 0
            a_lo, a_hi, b_lo, b_hi = c * qlo, c * qhi, -c * qhi, -c * qlo
            hlo = hlo + np.array([a_lo if p_ else b_lo for p_ in sy.tolist()], dtype=object); hhi = hhi + np.array([a_hi if p_ else b_hi for p_ in sy.tolist()], dtype=object)
    lo = [max(0, int(x)) for x in hlo.tolist()]; hi = [int(x) for x in hhi.tolist()]          # the surrogate kernel is positive (eta < 1 checked by the caller)
    return A.IVec(lo, hi, cav.exp).normalize(), {"operator": "poly", "k": k, "features": nfeat}


def surrogate_eta(dp, r, k):
    """(1-eta) K <= K~_k <= (1+eta) K with eta = tau_k / (1-r)^d'; None when eta >= 1 (the truncation is not a positive surrogate)."""
    r = Fr(r)
    if k >= dp:
        return Fr(0)
    t = A.tail(dp, k, r); lo = (1 - r) ** dp
    return None if t >= lo else t / lo


class Deadline(Exception):
    pass


def validate_op(op, dp):
    """Operator domain: kind in {exact, poly, fourier, sparse}; degree / radius a nonnegative int; poly only with eta < 1."""
    if not isinstance(op, (tuple, list)) or not op or op[0] not in ("exact", "poly", "fourier", "sparse"):
        raise ValueError("unknown operator %r" % (op,))
    if op[0] == "exact":
        if len(op) != 1:
            raise ValueError("exact takes no parameter")
        return ("exact",)
    if len(op) != 2 or isinstance(op[1], bool) or not isinstance(op[1], int) or op[1] < 0:
        raise ValueError("operator %r needs one nonnegative integer parameter" % (op,))
    return (op[0], int(op[1]))


def apply(op, cav, src_rows, tgt_rows, mask, r, deadline=None):
    op = validate_op(op, bin(mask).count("1"))
    if deadline is not None:
        deadline()
    kind = op[0]
    if kind == "poly":
        return transfer_poly(cav, src_rows, tgt_rows, mask, r, int(op[1]), deadline=deadline)
    if kind == "exact":
        return transfer_exact(cav, src_rows, tgt_rows, mask, r, deadline=deadline)
    if kind == "sparse":
        return transfer_sparse(cav, src_rows, tgt_rows, mask, r, int(op[1]), deadline=deadline)
    if kind == "fourier":
        return transfer_fourier(cav, src_rows, tgt_rows, mask, r, int(op[1]), deadline=deadline)
    raise ValueError(op)


def work_estimate(op, m_src, m_tgt, dp):
    if op[0] == "exact":
        return m_src * m_tgt
    N = sum(comb(dp, j) for j in range(int(op[1]) + 1))
    return m_tgt * N if op[0] == "sparse" else (m_src + m_tgt) * N          # fourier and poly
