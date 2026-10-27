"""Independent checker (CLAUDE_CODE_SPEC.md "Independent checking").  Separate entry point; its own numerical execution (build/dqcheck,
written separately, opposite sweep order) with no reuse of producer messages; the same exact input and stored centre.

Shared with the producer (declared): dq.model (exact generator/parser), native/dqinput.hpp (exact parser), native/mpiv.hpp (directed
MPFR primitive), dq.constants / dq.gate / dq.fourier_consts / dq.publish (exact scalar rules).  NOT shared: every chain contraction and
all aggregation arithmetic below is executed again here.

Verifies (1) exact input identity and hash, evidence handling, original normalisation; (2) contractions, loading/variance bounds, floor,
scalar inequalities; (3) stored centre residual and query enclosure with strict witness slack (four-error principle); (4) Arm F: all
nonzero frequencies, coefficients/phases, analytic and arithmetic errors, stored count witnesses; (5) exact/outward aggregation of the stored
witnesses and the published width/containment.  The checker verifies the STORED outward bounds; it never substitutes wider ones."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

import hashlib
import json
import os
import time
from fractions import Fraction as Fr

import gmpy2
from gmpy2 import mpfr, mpq

from dq.model import parse_canonical
from dq.gate import structural_constants, PAD_NUM, PAD_PUB, TARGET_RADIUS
from dq.fourier_consts import GRIDS, E_NUM, PAD_NUM_F, PAD_PUB_F, verify_declared_delta
from dq.publish import fx, publish_direct, marker_ratio, G64
from dq.supervisor import run_native, PhaseClock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DQCHECK = os.path.join(ROOT, "build", "dqcheck")
Q0_RAW_ERROR = Fr(1, 10 ** 7)
RESIDUAL_FROZEN = Fr(1, 8)                      # the proved residual requirement: bound explicitly here, not read from the witness
# proof domain D* of amendments/NUMERICAL_PROOF_REPAIR.md section 4 and the closed-form ceiling S_max = 48 n 2^-P
DOMAIN = {"n_max": 2 ** 16, "P_min": 96, "h_abs_max": Fr(1, 3), "a_max": Fr(1, 128), "c_abs_max": Fr(64), "f_min": Fr(1), "f_max": Fr(9), "w_abs_max": Fr(4)}
def S_max(n: int, P: int) -> Fr: return Fr(48 * n, 2 ** P)


def in_domain(m, c: Fr, P: int, w_max: Fr) -> dict:
    return {"n_le_2^16": m.n <= DOMAIN["n_max"], "P_ge_96": P >= DOMAIN["P_min"], "h_abs_le_1/3": all(abs(h) <= DOMAIN["h_abs_max"] for h in m.h), "a_in_(0,1/128]": all(0 < a <= DOMAIN["a_max"] for a in m.a),
            "c_abs_le_64": abs(c) <= DOMAIN["c_abs_max"], "f_in_[1,9]": all(DOMAIN["f_min"] <= f <= DOMAIN["f_max"] for f in m.f), "w_abs_le_4": w_max <= DOMAIN["w_abs_max"]}


def cos_sin_box(lo: Fr, hi: Fr, bits: int = 256):
    """Rigorous enclosure of cos and sin over the exact rational interval [lo, hi]: directed endpoint values plus +-1 at every critical point
    m*pi/2 that can lie inside, tested with the RATIONAL bounds PI_LOWER < pi < PI_UPPER (no floats)."""
    from dq.constants import PI_LOWER, PI_UPPER
    dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
    def box(q): return gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, dn), gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, up)
    L, H = box(lo), box(hi)
    # cos/sin are not monotone, so each endpoint's value must be enclosed from BOTH of its directed roundings (amendment 4; the previous
    # version used one rounding per direction and failed for non-dyadic endpoints)
    pts = [L[0], L[1], H[0], H[1]]
    cl = min(dn.cos(t) for t in pts); ch = max(up.cos(t) for t in pts); sl = min(dn.sin(t) for t in pts); sh = max(up.sin(t) for t in pts)
    def _floor(q): return q.numerator // q.denominator
    m0 = min(_floor(2 * lo / PI_UPPER), _floor(2 * lo / PI_LOWER)) - 1; m1 = max(-_floor(-2 * hi / PI_LOWER), -_floor(-2 * hi / PI_UPPER)) + 1
    crit = []
    for mm in range(m0, m1 + 1):
        a1 = mm * (PI_LOWER if mm >= 0 else PI_UPPER) / 2; a2 = mm * (PI_UPPER if mm >= 0 else PI_LOWER) / 2        # exact rational bounds on m pi/2
        if a2 >= lo and a1 <= hi:
            crit.append(mm); r4 = mm % 4
            if r4 == 0: ch = mpfr(1)
            if r4 == 2: cl = mpfr(-1)
            if r4 == 1: sh = mpfr(1)
            if r4 == 3: sl = mpfr(-1)
    return (cl, ch), (sl, sh), crit


def _fr(x):
    q = mpq(x); return Fr(int(q.numerator), int(q.denominator))


def _within(inner, outer):
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def check_arm(arm: str, input_path: str, witness: dict, out_dir: str, journal, deadline_s: float, rss_cap: int, fbits: int, monitor=None, progress_path=None) -> dict:
    """witness: the producer's result JSON (dict).  Returns a verdict dict with every check named."""
    t0 = time.monotonic(); C = {"arm": arm, "checks": {}, "phases": []}; input_path = os.path.abspath(input_path); out_dir = os.path.abspath(out_dir)
    pc = PhaseClock("check_input_identity")
    # (1) exact input identity: reparse + regenerate + hash
    try:
        m = parse_canonical(input_path)
    except Exception as e:  # noqa: BLE001
        C["checks"]["input_regenerates"] = False; C["reason"] = f"input does not regenerate: {e!r}"; C["verdict"] = "REJECTED"; return C
    C["checks"]["input_regenerates"] = True
    # amendment 4: both native kernels compute the marginal of SITE 0 only; any other query label (even if input and witness agree) is refused before numerical work
    C["checks"]["query_is_site_0"] = (m.query == 0 and witness.get("query") == 0)
    if not C["checks"]["query_is_site_0"]:
        C["failed_checks"] = ["query_is_site_0"]; C["verdict"] = "REJECTED"; C["reason"] = f"kernels compute site 0; input/witness query = {m.query}/{witness.get('query')}"; C["phases"].append(pc.stop()); return C
    h = hashlib.sha256(open(input_path, "rb").read()).hexdigest()
    C["checks"]["input_hash_matches_witness"] = (h == witness.get("input_sha256"))
    C["checks"]["query_and_evidence_match"] = (m.query == witness.get("query") and {str(k): v for k, v in m.evidence.items()} == witness.get("evidence", {}))
    C["checks"]["original_n_in_normalisation"] = (m.n == witness.get("n"))     # loadings carry (3/4)sqrt(2/n) with the ORIGINAL n; regenerated above
    C["phases"].append(pc.stop())
    # (2) structural constants recomputed from the input at higher precision (RoundUp -> no larger than the producer's)
    pc = PhaseClock("check_structural")
    S = structural_constants(m, bits=192)
    W = witness["gate"]                      # the producer's gate record (declared + input-derived constants)
    C["structural_recomputed"] = {k: S[k] for k in ("K_rowsum_upper", "M_exact", "V_bar", "floor_L", "s_A0_upper", "E0_upper", "taus")}
    C["checks"]["K_witness_is_upper_bound"] = Fr(S["K_rowsum_upper"]) <= Fr(W["K_rowsum_upper"])
    C["checks"]["M_exact_matches"] = Fr(S["M_exact"]) == Fr(W["M_exact"])
    C["checks"]["V_bar_witness_is_upper_bound"] = Fr(S["V_bar"]) <= Fr(W["V_bar"])
    # floor: L_w <= (1 - x/8)^8 <= exp(-x) with x = (V_w + r^2)/2 computed from the WITNESS V (which is >= true V)
    x = (Fr(W["V_bar"]) + Fr(W["residual_requirement"]) ** 2) / 2
    C["checks"]["floor_witness_valid"] = x < 8 and Fr(W["floor_L"]) <= (1 - x / 8) ** 8
    C["checks"]["s_A0_witness_is_upper_bound"] = Fr(S["s_A0_upper"]) <= Fr(W["s_A0_upper"])
    C["checks"]["E0_witness_is_upper_bound"] = Fr(S["E0_upper"]) <= Fr(W["E0_upper"])
    C["checks"]["contractions_match"] = S["taus"] == W["taus"]
    from dq.gate import DECLARED, E_LOWER, RESIDUAL_REQ as RREQ
    from dq.constants import sqrt_lower
    D = DECLARED.get(m.case); C["checks"]["case_has_declared_constants"] = D is not None
    if D is not None:
        xw = (D["V_bar"] + RREQ ** 2) / 2
        from dq.constants import contraction_two_state
        f0, f1 = m.f[0], (m.f[1] if m.n > 2 else m.f[0]); pattern_ok = all(m.f[i] == (f0 if i % 2 == 0 else f1) for i in range(m.n - 1))
        t1, t2 = contraction_two_state(f0), contraction_two_state(f1); K_exact = (1 + t1) * (1 + t2) / (1 - t1 * t2)
        C["checks"]["edge_pattern_alternating"] = pattern_ok
        C["checks"]["declared_K_dominates_recomputed"] = pattern_ok and K_exact <= D["K"]
        C["checks"]["declared_V_dominates_recomputed"] = pattern_ok and K_exact * Fr(S["M_exact"]) <= D["V_bar"]
        C["checks"]["rowsum_sweep_consistent_with_closed_form"] = Fr(S["K_rowsum_upper"]) <= K_exact + Fr(1, 2 ** 100)   # RoundUp sweep exceeds the exact value only by rounding
        C["checks"]["declared_floor_valid"] = xw < 8 and D["L"] <= (1 - xw / 8) ** 8
        E0p = Fr(S["s_A0_upper"]) / (2 * sqrt_lower(E_LOWER) * D["L"])
        C["checks"]["declared_E0_dominates_recomputed"] = (D["E0"] is None) or (E0p <= D["E0"])
        C["checks"]["witness_published_radius_is_declared"] = (arm != "D") or (Fr(W["E0_published_radius"]) == (D["E0"] if D["E0"] is not None else E0p))
    C["phases"].append(pc.stop())
    # (3) stored centre + residual + query enclosure: rerun the kernel at the CHECKER precision
    cstr = witness["center"]["c"]
    gridJ = witness["fourier"]["J"] if arm == "F" else 0
    gridh = witness["fourier"]["h"] if arm == "F" else "1"
    kernel_out = os.path.join(out_dir, "checker_kernel.json")
    native_deadline = deadline_s - (time.monotonic() - t0)                 # amendment 3/4: Python check time already spent is subtracted; an expired deadline refuses the kernel
    if native_deadline <= 0:
        C["verdict"] = "CHECKER_INCOMPLETE"; C["reason"] = "checker deadline expired before the kernel"; C["phases"].append(pc.stop()); return C
    rec = run_native([DQCHECK, input_path, kernel_out, "--center", cstr, "--fbits", str(fbits), "--freq-h", gridh, "--J", str(gridJ), "--progress", progress_path or os.path.join(out_dir, "checker_progress.txt")],
                     out_dir, journal, native_deadline, rss_cap, {"phase": "checker_kernel", "arm": arm, "fbits": fbits}, progress_path=progress_path or os.path.join(out_dir, "checker_progress.txt"), monitor=monitor)
    C["kernel"] = {k: rec.get(k) for k in ("exit_code", "kill_reason", "wall_s", "cpu_s", "cpu_over_wall", "peak_rss_bytes")}
    if rec["exit_code"] != 0:
        C["verdict"] = "REJECTED" if rec["kill_reason"] is None else "CHECKER_INCOMPLETE"; C["reason"] = f"checker kernel exit {rec['exit_code']} ({rec['kill_reason']})"; return C
    K = json.load(open(kernel_out))
    pc = PhaseClock("check_aggregate")
    C["checks"]["center_on_2e-64_grid"] = (fx(cstr) * G64).denominator == 1
    qC = (fx(K["q0"][0]), fx(K["q0"][1])); qP = (fx(witness["final"]["q0"][0]), fx(witness["final"]["q0"][1]))
    rC = (fx(K["residual"][0]), fx(K["residual"][1])); rP = (fx(witness["final"]["residual"][0]), fx(witness["final"]["residual"][1]))
    rC_abs_upper = fx(K["residual_abs"][1])
    C["q0_checker"] = [str(v) for v in qC]; C["residual_checker"] = [str(v) for v in rC]; C["residual_abs_upper_checker"] = str(rC_abs_upper)
    C["checks"]["q0_checker_raw_error_ok"] = (qC[1] - qC[0]) / 2 <= Q0_RAW_ERROR
    C["checks"]["q0_producer_raw_error_ok"] = (qP[1] - qP[0]) / 2 <= Q0_RAW_ERROR
    C["checks"]["q0_enclosures_overlap"] = qC[0] <= qP[1] and qP[0] <= qC[1]
    # four-error principle: checker's enclosure must lie inside the producer's enclosure padded by the stored numerical padding
    padN = Fr(witness["published"]["pad_numerical"])
    C["checks"]["q0_checker_within_producer_padded_witness"] = _within(qC, (qP[0] - padN, qP[1] + padN))
    C["checks"]["residual_enclosures_overlap"] = rC[0] <= rP[1] and rP[0] <= rC[1]
    r_w = Fr(witness["final"]["residual_witness"])
    C["checks"]["residual_witness_is_frozen_1/8"] = (r_w == RESIDUAL_FROZEN) and (Fr(W["residual_requirement"]) == RESIDUAL_FROZEN)      # amendment 2: bound to the proved constant
    C["checks"]["residual_strictly_below_frozen_1/8"] = rC_abs_upper < RESIDUAL_FROZEN                                                     # independent of any witness field
    C["checks"]["residual_strictly_below_witness"] = rC_abs_upper < r_w
    pub = witness["published"]; plo, phi = Fr(pub["lo"]), Fr(pub["hi"])
    C["checks"]["published_width_le_contract"] = (phi - plo) <= Fr(1, 100)
    if arm == "D":
        # aggregation of the stored witnesses reproduces the publication exactly
        rep = publish_direct(qP[0], qP[1], Fr(W["E0_published_radius"]), padN)
        C["checks"]["aggregation_reproduces_publication"] = (Fr(rep["lo"]), Fr(rep["hi"])) == (plo, phi)
        C["checks"]["pad_numerical_ge_four_raw_errors"] = padN >= 4 * Q0_RAW_ERROR
        C["checks"]["publication_rounding_le_pad"] = Fr(pub["pad_publication"]) >= Fr(1, G64)
        # containment: the checker's INDEPENDENT enclosure (its q0 +- its own E0 upper bound) inside the publication
        E0c = Fr(S["E0_upper"]); ind = (qC[0] - E0c, qC[1] + E0c)      # checker's own (input-derived) radius: sharper than the declared one, so containment is a real test
        C["independent_enclosure"] = [str(ind[0]), str(ind[1])]
        C["checks"]["independent_enclosure_contained_in_publication"] = _within(ind, (plo, phi))
        C["checks"]["gate_admission_consistent"] = (Fr(W["E0_published_radius"]) + padN + Fr(pub["pad_publication"]) <= TARGET_RADIUS)
    else:
        F = witness["fourier"]; g = GRIDS[m.case]
        C["checks"]["grid_is_frozen"] = Fr(F["h"]) == g["h"] and int(F["J"]) == g["J"] and Fr(F["delta_declared"]) == g["delta_declared"]
        dd = verify_declared_delta(m.case, Fr(W["V_bar"]))
        C["fourier_delta_recomputed"] = dd; C["checks"]["declared_analytic_radius_dominates_recomputed"] = dd["declared_dominates"] and Fr(F["delta_declared"]) >= Fr(dd["alias_plus_truncation"])
        C["checks"]["floor_gt_2eta"] = Fr(W["floor_L"]) > 2 * (Fr(F["delta_declared"]) + Fr(F["pad_numerical"]))
        # re-aggregate the finite Fourier counts from the CHECKER's phi enclosures with exact/directed arithmetic (independent of the C++ aggregation)
        bits = 256; dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
        def box(q: Fr): return gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, dn), gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, up)
        def mul(a, b):
            c = [dn.mul(a[0], b[0]), dn.mul(a[0], b[1]), dn.mul(a[1], b[0]), dn.mul(a[1], b[1])]; d = [up.mul(a[0], b[0]), up.mul(a[0], b[1]), up.mul(a[1], b[0]), up.mul(a[1], b[1])]; return min(c), max(d)
        def add(a, b): return dn.add(a[0], b[0]), up.add(a[1], b[1])
        hF = Fr(F["h"]); c = fx(cstr)
        pi = (dn.const_pi(), up.const_pi()); pref = (dn.div(box(hF)[0], up.sqrt(up.mul(pi[1], 2))), up.div(box(hF)[1], dn.sqrt(dn.mul(pi[0], 2))))
        J_frozen = int(g["J"])
        # amendment 2: frequency completeness — native kernel output AND witness must carry exactly k = 1..J, no more, no fewer, in order
        kN = [f["k"] for f in K["complex"]["frequencies"]]; kW = [f["k"] for f in F["frequencies"]]
        C["checks"]["frequency_arrays_complete_1..J"] = (kN == list(range(1, J_frozen + 1))) and (kW == list(range(1, J_frozen + 1))) and int(K["complex"]["J"]) == J_frozen
        if not C["checks"]["frequency_arrays_complete_1..J"]:
            C["failed_checks"] = [k for k, v in C["checks"].items() if v is False]; C["verdict"] = "REJECTED"; C["reason"] = "frequency arrays incomplete/misordered"; C["phases"].append(pc.stop()); return C
        # amendment 1: proof domain and closed-form ceiling for the complex-pass error; the kernel's propagated s must not exceed it
        Pbits = int(K["mpfr_prec"]); Pprod = int(witness["center"]["mpfr_prec"]); n_ = m.n
        dom = in_domain(m, c, min(Pbits, Pprod), J_frozen * hF); C["numerical_domain"] = dom; C["checks"]["numerical_proof_domain"] = all(dom.values())
        Smax_c = S_max(n_, Pbits); Smax_p = S_max(n_, Pprod)
        C["checks"]["kernel_propagated_s_le_ceiling"] = all(fx(f["propagated_relative_error_s"]) <= Smax_c for f in K["complex"]["frequencies"])
        C["checks"]["producer_propagated_s_le_ceiling"] = all(fx(f["propagated_relative_error_s"]) <= Smax_p for f in F["frequencies"])
        C["ceilings"] = {"S_max_checker": str(Smax_c), "S_max_producer": str(Smax_p)}
        # T_lo >= 1 after the exact scaling (the real total has exponent 1 or 0); the component expansion S_max covers |g(+)+g(-)| <= T
        accP = box(qC[0])[0], box(qC[1])[1]; one = box(Fr(1)); accM = (dn.sub(one[0], accP[1]), up.sub(one[1], accP[0]))
        overlap_ok = True; crit_all = []
        wid_c = box(Smax_c); wid_p = box(Smax_p)
        for fk, fP in zip(K["complex"]["frequencies"], F["frequencies"]):
            k = fk["k"]; w = k * hF
            phC = {s_: ((fx(fk[s_]["re"][0]) - Smax_c, fx(fk[s_]["re"][1]) + Smax_c), (fx(fk[s_]["im"][0]) - Smax_c, fx(fk[s_]["im"][1]) + Smax_c)) for s_ in ("phi_plus", "phi_minus")}
            phP = {s_: ((fx(fP[s_]["re"][0]) - Smax_p, fx(fP[s_]["re"][1]) + Smax_p), (fx(fP[s_]["im"][0]) - Smax_p, fx(fP[s_]["im"][1]) + Smax_p)) for s_ in ("phi_plus", "phi_minus")}
            for s_ in phC:
                if not (phC[s_][0][0] <= phP[s_][0][1] and phP[s_][0][0] <= phC[s_][0][1] and phC[s_][1][0] <= phP[s_][1][1] and phP[s_][1][0] <= phC[s_][1][1]): overlap_ok = False
            wsq = -(w * w) / 2; wt = (dn.exp(box(wsq)[0]), up.exp(box(wsq)[1])); wt = (dn.mul(wt[0], 2), up.mul(wt[1], 2))
            ang = w * c                                                       # exact rational (w = k h with h in {1, 3/4}; c on the 2^-64 grid)
            cs, sn, crit = cos_sin_box(ang, ang); crit_all += [(k, mm) for mm in crit]
            for s_, acc_name in (("phi_plus", "P"), ("phi_minus", "M")):
                re_box = (box(phC[s_][0][0])[0], box(phC[s_][0][1])[1]); im_box = (box(phC[s_][1][0])[0], box(phC[s_][1][1])[1])
                term = add(mul(re_box, cs), mul(im_box, sn)); term = mul(term, wt)
                if acc_name == "P": accP = add(accP, term)
                else: accM = add(accM, term)
        C["phase_critical_points_inside"] = crit_all; phases_ok = True     # a critical point inside widens the enclosure rigorously (+-1); no rejection needed
        accP = mul(accP, pref); accM = mul(accM, pref)
        GP = (_fr(accP[0]), _fr(accP[1])); GM = (_fr(accM[0]), _fr(accM[1]))
        C["Ghat_plus_checker"] = [str(v) for v in GP]; C["Ghat_minus_checker"] = [str(v) for v in GM]
        C["checks"]["phi_enclosures_overlap"] = overlap_ok; C["checks"]["phase_enclosure_rigorous"] = phases_ok
        C["checks"]["count_arithmetic_error_le_E_NUM"] = (GP[1] - GP[0]) / 2 <= E_NUM and (GM[1] - GM[0]) / 2 <= E_NUM
        GPp = (fx(F["Ghat_plus"][0]), fx(F["Ghat_plus"][1])); GMp = (fx(F["Ghat_minus"][0]), fx(F["Ghat_minus"][1]))
        C["checks"]["producer_count_arithmetic_error_le_E_NUM"] = (GPp[1] - GPp[0]) / 2 <= E_NUM and (GMp[1] - GMp[0]) / 2 <= E_NUM
        padF = Fr(F["pad_numerical"]); C["checks"]["fourier_pad_ge_four_errors"] = padF >= 4 * E_NUM
        C["checks"]["counts_checker_within_producer_padded_witness"] = _within(GP, (GPp[0] - padF, GPp[1] + padF)) and _within(GM, (GMp[0] - padF, GMp[1] + padF))
        eta = Fr(F["delta_declared"]) + padF
        rep = marker_ratio(GPp[0], GPp[1], GMp[0], GMp[1], eta)
        C["checks"]["aggregation_reproduces_publication"] = (Fr(rep["lo"]), Fr(rep["hi"])) == (plo, phi)
        # containment: checker's independent interval from ITS counts with eta_c = recomputed analytic delta (no padding) must lie inside the publication
        eta_c = Fr(dd["alias_plus_truncation"])
        ind = marker_ratio(GP[0], GP[1], GM[0], GM[1], eta_c); C["independent_enclosure"] = [ind["lo"], ind["hi"]]
        C["checks"]["independent_enclosure_contained_in_publication"] = _within((Fr(ind["lo"]), Fr(ind["hi"])), (plo, phi))
    C["phases"].append(pc.stop())
    hard = [k for k, v in C["checks"].items() if v is False]
    C["failed_checks"] = hard; C["verdict"] = "VERIFIED" if not hard else "REJECTED"; C["time_s"] = time.monotonic() - t0
    return C
