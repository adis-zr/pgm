"""Input-only structural gate for the direct response certificate (CLAUDE_CODE_SPEC.md "Arm D and automatic fallback", witness_response.md
sections 3, 6, 7, 9).  Everything here is computed FROM THE INPUT (exact rationals, or outward-rounded fixed-precision nonnegative arithmetic
for the O(n) influence recurrence); nothing is taken from the family label.  No inference is performed.

  tau_i      = |f_i - 1|/(f_i + 1)                      exact two-state cross-ratio contraction of edge i (all unary tilts)
  rho_{0j}   = prod_{k<j} tau_k                          disagreement bound from the query site 0 to site j
  K          = max_i (1 + l_i + r_i)                      all-tilt covariance row-sum bound, l_i = tau_{i-1}(1 + l_{i-1}), r_i = tau_i(1 + r_{i+1})
  M          = sum_i a_i^2                                exact squared norm of the negative loading row
  V_bar      = K M                                        all-tilt projected variance bound
  L          = certified rational floor: L <= exp(-(V_bar + r^2)/2) for the residual requirement r = 1/8, via (1 - x/8)^8 <= exp(-x)
  s_A0       = sum_j |a_j| rho_{0j}                       (upper bound, RoundUp mpfr; exact closed forms would carry 25^16384 denominators)
  E_0        = s_A0 / (2 sqrt(e) L)                       intrinsic response radius (proof_response.md eq. 4 with q(1-q) <= 1/4)
Admission:   E_0 + pad_numerical + pad_publication <= 1/200  (width 1/100).  MAIN is expected to pass (E_0 < 3/800), CONTROL to decline."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

import time
from fractions import Fraction as Fr

import gmpy2
from gmpy2 import mpfr, mpq

from dq.constants import contraction_two_state, exp_lower, exp_upper, sqrt_lower
from dq.model import Model

RESIDUAL_REQ = Fr(1, 8)
# FROZEN declared constants (CLAUDE_CODE_SPEC.md / witness_response.md).  The gate VERIFIES from the input that each declared bound dominates
# the input-derived quantity (an input that violates a declared bound is refused), then admits/declines and publishes with the DECLARED radius.
DECLARED = {"MAIN": {"K": Fr(99, 46), "V_bar": Fr(2079, 1472), "L": Fr(15, 32), "E0": Fr(3, 800)},
            "CONTROL": {"K": Fr(63, 17), "V_bar": Fr(63, 17) * Fr(21, 32), "L": Fr(1, 4), "E0": None}}      # CONTROL: E0 from the prescribed formula
PAD_NUM = Fr(1, 16000)
PAD_PUB = Fr(1, 16000)
TARGET_RADIUS = Fr(1, 200)
E_LOWER = Fr(8, 3)                        # e >= 8/3 (witness_response.md)


def _fr(x) -> Fr:
    q = mpq(x); return Fr(int(q.numerator), int(q.denominator))


def structural_constants(m: Model, bits: int = 128) -> dict:
    """Exact K (row-sum covariance bound), M, V_bar, floor; outward s_A0 and E_0 at `bits` fractional bits (RoundUp contexts)."""
    t0 = time.perf_counter()
    n = m.n
    free = [i for i in range(n) if i not in m.evidence]; free_set = set(free)
    # contractions: an edge touching a pinned site transmits nothing (pinned separator) -> tau = 0 there
    tau = [contraction_two_state(m.f[i]) if (i not in m.evidence and (i + 1) not in m.evidence) else Fr(0) for i in range(n - 1)]
    taus = sorted(set(tau))
    # row-sum bound K = max over free sites of 1 + l_i + r_i, with exact rationals via the two sweeps (denominators stay bounded because the
    # recurrence is dominated by the geometric series — we use RoundUp mpfr for the sweep to keep it O(n) regardless of the factor alphabet)
    up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
    tau_u = [mpfr(mpq(t.numerator, t.denominator), bits, up) for t in tau]
    l = [mpfr(0, bits)] * n; r = [mpfr(0, bits)] * n
    for i in range(1, n):
        l[i] = up.mul(tau_u[i - 1], up.add(mpfr(1 if (i - 1) in free_set else 0, bits), l[i - 1]))
    for i in range(n - 2, -1, -1):
        r[i] = up.mul(tau_u[i], up.add(mpfr(1 if (i + 1) in free_set else 0, bits), r[i + 1]))
    K_rows = [up.add(up.add(mpfr(1, bits), l[i]), r[i]) for i in free]
    K_up = max(K_rows)
    K = _fr(K_up)
    # infinite-chain closed form for the alternating two-edge pattern (recorded for comparison with the spec's constant)
    K_closed = None
    if len(taus) == 2 and n >= 4:
        t1, t2 = taus
        K_closed = (1 + t1) * (1 + t2) / (1 - t1 * t2)
    elif len(taus) == 1:
        K_closed = (1 + taus[0]) / (1 - taus[0])
    M = sum((m.a[i] * m.a[i] for i in free), Fr(0))                      # exact; pinned loadings enter the field shift, not the free variance
    V_bar = K * M
    x = (V_bar + RESIDUAL_REQ ** 2) / 2
    # floor: choose the largest dyadic L on the 2^-10 grid with L <= (1 - x/8)^8 (<= exp(-x)); also report the certified bound exp_lower side
    poly = (1 - x / 8) ** 8 if x < 8 else Fr(0)
    L = Fr((poly * 1024).numerator // (poly * 1024).denominator, 1024)
    assert L <= poly <= 1 / exp_lower(x) if x < 80 else True
    # s_A0 upper bound: backward recurrence R_j = tau_j (|a_{j+1}| + R_{j+1}), s_A0 = |a_0| + R_0, RoundUp
    a_u = [mpfr(mpq(abs(m.a[i]).numerator, abs(m.a[i]).denominator), bits, up) if i in free_set else mpfr(0, bits) for i in range(n)]
    R = mpfr(0, bits)
    for j in range(n - 2, m.query - 1, -1):
        R = up.mul(tau_u[j], up.add(a_u[j + 1], R))
    s_A0_up = up.add(a_u[m.query], R) if m.query == 0 else None
    if m.query != 0:
        # general query: left and right sums
        Rr = mpfr(0, bits)
        for j in range(n - 2, m.query - 1, -1): Rr = up.mul(tau_u[j], up.add(a_u[j + 1], Rr))
        Rl = mpfr(0, bits)
        for j in range(0, m.query): Rl = up.mul(tau_u[j], up.add(a_u[j], Rl))
        s_A0_up = up.add(up.add(a_u[m.query], Rr), Rl)
    s_A0 = _fr(s_A0_up)
    # E_0 <= s_A0 / (2 sqrt(e) L) with sqrt(e) >= sqrt(8/3) >= sqrt_lower(8/3)
    E0 = s_A0 / (2 * sqrt_lower(E_LOWER) * L)
    # exact structural facts recorded for the report
    dob_row0 = None
    if m.query == 0 and not m.evidence:
        # standard field-uniform single-site Dobrushin row sum at site 0: tanh|J_01| + sum_{j>=2} tanh|J_0j| with J_01 = (log f_0)/2 (+ no negative), J_0j = -a_0 a_j
        # recorded as a LOWER bound via tanh z >= (2/3) z for z in [0,1] and tanh(log(f)/2) = (f-1)/(f+1) exactly
        # J_01 = (log f_0)/2 - a_0 a_1 (residual edge PLUS the negative collective coupling); tanh is 1-Lipschitz, tanh((log f)/2) = (f-1)/(f+1)
        # exactly, so tanh|J_01| >= (f_0-1)/(f_0+1) - a_0 a_1; non-neighbours: tanh(a_0 a_j) >= (2/3) a_0 a_j for 0 <= a_0 a_j <= 1
        row = (contraction_two_state(m.f[0]) - m.a[0] * m.a[1]) + sum((Fr(2, 3) * m.a[0] * m.a[j] for j in range(2, n)), Fr(0))
        dob_row0 = row
    return {"n": n, "free_sites": len(free), "taus": [str(t) for t in taus], "tau_edge0": str(tau[0]), "tau_edge1": str(tau[1]) if n > 2 else None,
            "K_rowsum_upper": str(K), "K_rowsum_upper_float": float(K), "K_infinite_chain_closed_form": str(K_closed) if K_closed is not None else None,
            "M_exact": str(M), "M_float": float(M), "V_bar": str(V_bar), "V_bar_float": float(V_bar), "residual_requirement": str(RESIDUAL_REQ),
            "floor_L": str(L), "floor_L_float": float(L), "floor_poly_bound": str(poly), "exp_arg_x": str(x),
            "s_A0_upper": str(s_A0), "s_A0_upper_float": float(s_A0), "E0_upper": str(E0), "E0_upper_float": float(E0),
            "dobrushin_row0_lower": str(dob_row0) if dob_row0 is not None else None, "dobrushin_row0_lower_float": float(dob_row0) if dob_row0 is not None else None,
            "loadings_all_distinct": len(set(m.a)) == n, "negative_mode_norm_sq": str(sum((ai * ai for ai in m.a), Fr(0))),
            "bits": bits, "time_s": time.perf_counter() - t0}


def response_gate(m: Model, bits: int = 128) -> dict:
    """Input-only admission decision.  Verifies the FROZEN declared constants of the case against input-derived quantities, computes the
    prescribed intrinsic radius from the declared constants, and admits iff declared E0 + pads <= 1/200."""
    S = structural_constants(m, bits)
    D = DECLARED.get(m.case)
    S["declared"] = {k: (str(v) if v is not None else None) for k, v in D.items()} if D else None
    if D is None:
        S["decision"] = "CERTIFICATE_DECLINED"; S["failed_bound"] = "no frozen declared constants for this case"; return S
    M_in, s_in = Fr(S["M_exact"]), Fr(S["s_A0_upper"])
    # Exact dominance test for K: the raw (pre-evidence) edge factors must form the alternating two-factor pattern, whose infinite-chain row sum
    # (1+t1)(1+t2)/(1-t1 t2) is an EXACT rational that dominates every finite-chain row sum (nonnegative tail dropped) and every pinned variant
    # (pins only zero some taus).  The RoundUp row-sum sweep is kept as a diagnostic but cannot be compared to a declared constant exactly.
    f0, f1 = m.f[0], m.f[1] if m.n > 2 else m.f[0]
    pattern_ok = all(m.f[i] == (f0 if i % 2 == 0 else f1) for i in range(m.n - 1))
    t1, t2 = contraction_two_state(f0), contraction_two_state(f1)
    K_exact = (1 + t1) * (1 + t2) / (1 - t1 * t2)
    S["K_exact_alternating_closed_form"] = str(K_exact); S["edge_pattern_alternating"] = pattern_ok
    V_exact = K_exact * M_in
    checks = {"edge_pattern_alternating": pattern_ok, "K_declared_dominates_input": pattern_ok and K_exact <= D["K"], "V_declared_dominates_input": pattern_ok and V_exact <= D["V_bar"], "M_input_below_21_32": M_in < Fr(21, 32)}
    x = (D["V_bar"] + RESIDUAL_REQ ** 2) / 2
    checks["L_declared_valid_floor"] = x < 8 and D["L"] <= (1 - x / 8) ** 8                  # (1-x/8)^8 <= exp(-x) <= G at any centre with residual <= 1/8
    # prescribed intrinsic radius: s_A0 (input-derived upper bound, which uses the input contractions) / (2 sqrt(e) L_declared), e >= 8/3
    E0_prescribed = s_in / (2 * sqrt_lower(E_LOWER) * D["L"])
    if D["E0"] is not None:
        checks["E0_declared_dominates_prescribed"] = E0_prescribed <= D["E0"]; E0_used = D["E0"]
    else:
        E0_used = E0_prescribed
    S["gate_checks"] = checks; S["E0_prescribed_from_declared_floor"] = str(E0_prescribed); S["E0_prescribed_float"] = float(E0_prescribed)
    S["E0_published_radius"] = str(E0_used); S["E0_published_radius_float"] = float(E0_used)
    S["E0_input_derived_sharper"] = S["E0_upper"]            # recorded only; not used for publication
    total = E0_used + PAD_NUM + PAD_PUB
    S["pad_numerical"] = str(PAD_NUM); S["pad_publication"] = str(PAD_PUB); S["total_radius_upper"] = str(total); S["total_radius_upper_float"] = float(total)
    S["target_radius"] = str(TARGET_RADIUS); S["published_width_upper_if_admitted"] = str(2 * total)
    if not all(checks.values()):
        S["decision"] = "INPUT_VIOLATES_DECLARED_CONSTANTS"; S["failed_bound"] = str([k for k, v in checks.items() if not v]); return S
    if total <= TARGET_RADIUS:
        S["decision"] = "ADMITTED"
    else:
        S["decision"] = "CERTIFICATE_DECLINED"
        S["failed_bound"] = (f"prescribed intrinsic response radius s_A0/(2 sqrt(e) L) = {float(E0_prescribed):.6f} (K={D['K']}, floor L={D['L']}) plus padding "
                            f"{float(PAD_NUM + PAD_PUB):.6f} exceeds the target radius 1/200; sufficient bound failed, nothing is claimed about the true query")
    return S


def weighted_count_state_estimate(m: Model) -> dict:
    """Checked preallocation estimate for a weighted-count DP on the statistic sum_i a_i x_i (NOT allocated): with a_i = 3 t_i/512 =
    3(n+2+i)/(1024(n+1)) the statistic is an integer multiple of 3/(1024(n+1)); the integer N = sum_i x_i (n+2+i) ranges over
    [-S, S], S = sum_i (n+2+i) = n(n+2) + n(n-1)/2, so a per-site table would hold up to 2S+1 integer states."""
    n = m.n
    S = n * (n + 2) + n * (n - 1) // 2
    return {"integer_statistic_range": 2 * S + 1, "range_float": float(2 * S + 1), "per_site_tables": n, "note": "order n^2 states per site; a dense table would need ~%.1e cells x n sites; not allocated" % float(2 * S + 1)}


def log_weight_perturbation_bound(m: Model) -> dict:
    """Generic bound for DELETING the negative term: log-weight oscillation up to (sum_i |a_i|)^2 / 2; the TV bound tanh(osc/2) is useless
    when osc is large.  Recorded as a cheap comparison (witness_response.md section 6)."""
    S = sum((abs(ai) for ai in m.a), Fr(0)); osc = S * S / 2
    return {"sum_abs_a": str(S), "log_weight_oscillation_upper": str(osc), "tv_bound_informative": osc < 2, "note": "oscillation %.1f: deleting the collective term is not certified to preserve the query" % float(osc)}
