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
    rec = run_native([DQCHECK, input_path, kernel_out, "--center", cstr, "--fbits", str(fbits), "--freq-h", gridh, "--J", str(gridJ), "--progress", progress_path or os.path.join(out_dir, "checker_progress.txt")],
                     out_dir, journal, deadline_s, rss_cap, {"phase": "checker_kernel", "arm": arm, "fbits": fbits}, progress_path=progress_path or os.path.join(out_dir, "checker_progress.txt"), monitor=monitor)
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
    C["checks"]["residual_strictly_below_witness"] = rC_abs_upper < r_w
    C["checks"]["residual_witness_equals_requirement"] = r_w == Fr(W["residual_requirement"])
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
        accP = box(qC[0])[0], box(qC[1])[1]; one = box(Fr(1)); accM = (dn.sub(one[0], accP[1]), up.sub(one[1], accP[0]))
        phases_ok = True; overlap_ok = True
        for fk, fP in zip(K["complex"]["frequencies"], F["frequencies"]):
            k = fk["k"]; w = k * hF
            phC = {s: ((fx(fk[s]["re"][0]), fx(fk[s]["re"][1])), (fx(fk[s]["im"][0]), fx(fk[s]["im"][1]))) for s in ("phi_plus", "phi_minus")}
            phP = {s: ((fx(fP[s]["re"][0]), fx(fP[s]["re"][1])), (fx(fP[s]["im"][0]), fx(fP[s]["im"][1]))) for s in ("phi_plus", "phi_minus")}
            for s in phC:
                if not (phC[s][0][0] <= phP[s][0][1] and phP[s][0][0] <= phC[s][0][1] and phC[s][1][0] <= phP[s][1][1] and phP[s][1][0] <= phC[s][1][1]): overlap_ok = False
            # weight 2 exp(-w^2/2) and phase e^{-i w c}: Re[(re + i im)(cos(-wc) + i sin(-wc))] = re cos(wc) + im sin(wc)
            wsq = -(w * w) / 2; wt = (dn.exp(box(wsq)[0]), up.exp(box(wsq)[1])); wt = (dn.mul(wt[0], 2), up.mul(wt[1], 2))
            ang = box(w * c); cs = (min(dn.cos(ang[0]), dn.cos(ang[1])), max(up.cos(ang[0]), up.cos(ang[1]))); sn = (min(dn.sin(ang[0]), dn.sin(ang[1])), max(up.sin(ang[0]), up.sin(ang[1])))
            if int((float(w * c) * 2 / 3.141592653589793)) != int((float(w * c) * 2 / 3.141592653589793) + 1e-9): phases_ok = phases_ok  # (angle widths are ~1e-30; the exact enclosure is the min/max of endpoint values unless a critical point lies inside)
            import math
            if math.floor(float(ang[0]) / (math.pi / 2)) != math.floor(float(ang[1]) / (math.pi / 2)): phases_ok = False       # would need the extremum fix; angles here have width < 1e-20 so this never triggers unless the centre is corrupt
            for s, acc_name in (("phi_plus", "P"), ("phi_minus", "M")):
                re_box = (box(phC[s][0][0])[0], box(phC[s][0][1])[1]); im_box = (box(phC[s][1][0])[0], box(phC[s][1][1])[1])
                term = add(mul(re_box, cs), mul(im_box, sn)); term = mul(term, wt)
                if acc_name == "P": accP = add(accP, term)
                else: accM = add(accM, term)
        accP = mul(accP, pref); accM = mul(accM, pref)
        GP = (_fr(accP[0]), _fr(accP[1])); GM = (_fr(accM[0]), _fr(accM[1]))
        C["Ghat_plus_checker"] = [str(v) for v in GP]; C["Ghat_minus_checker"] = [str(v) for v in GM]
        C["checks"]["phi_enclosures_overlap"] = overlap_ok; C["checks"]["phase_angles_without_interior_extremum"] = phases_ok
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
