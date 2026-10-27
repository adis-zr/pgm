"""Saved-record recomputation (no kernel replay): from the archived witness/kernel JSON of runs/dq_pilot_2026-10-26,
(1) re-aggregate every Fourier/fallback publication from the saved CHECKER phi rectangles widened by the closed-form ceiling S_max
    (amendment 1) and verify containment in the published interval, reporting the margin;
(2) verify all centre updates with the endpoint criterion max(|d - g_lo|, |d - g_hi|) <= 1/4096, d = (c - c_next)/(2/5);
(3) verify every saved phase angle w*c is an exact dyadic and lies > 0.02 rad from any critical point m*pi/2 (rational pi bounds);
(4) recompute the medians of the MAIN pairs both ways (paired ratios; ratio of arm medians) and the CONTROL overhead."""
import glob, json, os, statistics, sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from dq.publish import fx, marker_ratio
from dq.checker import S_max, cos_sin_box
from dq.constants import PI_LOWER, PI_UPPER
import gmpy2
from gmpy2 import mpfr, mpq

RUN = os.path.join(ROOT, "runs", "dq_pilot_2026-10-26")
S = json.load(open(os.path.join(RUN, "campaign_state.json")))
res = {"publications": [], "center_updates": {"count": 0, "max_update_error": "0"}, "phases": [], "timing": {}}
bits = 256; dn = gmpy2.context(precision=bits, round=gmpy2.RoundDown); up = gmpy2.context(precision=bits, round=gmpy2.RoundUp)
def box(q): return gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, dn), gmpy2.mpfr(mpq(q.numerator, q.denominator), bits, up)
def mul(a, b):
    c = [dn.mul(a[0], b[0]), dn.mul(a[0], b[1]), dn.mul(a[1], b[0]), dn.mul(a[1], b[1])]; d = [up.mul(a[0], b[0]), up.mul(a[0], b[1]), up.mul(a[1], b[0]), up.mul(a[1], b[1])]; return min(c), max(d)
def add(a, b): return dn.add(a[0], b[0]), up.add(a[1], b[1])
def _fr(x): q = mpq(x); return Fr(int(q.numerator), int(q.denominator))
maxerr = Fr(0); nupd = 0
for wpath in sorted(glob.glob(os.path.join(RUN, "cells", "*", "witness.json")) + glob.glob(os.path.join(RUN, "cells", "*", "fallback", "witness.json"))):
    W = json.load(open(wpath)); cell = os.path.relpath(os.path.dirname(wpath), os.path.join(RUN, "cells"))
    # (2) centre updates
    for it in W["center"]["iterations"]:
        c, cn = fx(it["c"]), fx(it["c_next"]); d = (c - cn) / Fr(2, 5); glo, ghi = fx(it["grad"][0]), fx(it["grad"][1])
        err = max(abs(d - glo), abs(d - ghi)); maxerr = max(maxerr, err); nupd += 1
        assert err <= Fr(1, 4096), (cell, it["iter"], float(err))
    if W["arm"] != "F": continue
    # (1) re-aggregate from the saved CHECKER kernel rectangles (checker_fb128/checker_kernel.json) widened by S_max(n, P_checker)
    kpath = os.path.join(os.path.dirname(wpath), "checker_fb128", "checker_kernel.json"); K = json.load(open(kpath))
    n = W["n"]; P = int(K["mpfr_prec"]); Sm = S_max(n, P); c = fx(W["center"]["c"]); hF = Fr(W["fourier"]["h"]); J = int(W["fourier"]["J"])
    assert [f["k"] for f in K["complex"]["frequencies"]] == list(range(1, J + 1))
    q0 = (fx(K["q0"][0]), fx(K["q0"][1])); accP = box(q0[0])[0], box(q0[1])[1]; one = box(Fr(1)); accM = (dn.sub(one[0], accP[1]), up.sub(one[1], accP[0]))
    pi = (dn.const_pi(), up.const_pi()); pref = (dn.div(box(hF)[0], up.sqrt(up.mul(pi[1], 2))), up.div(box(hF)[1], dn.sqrt(dn.mul(pi[0], 2))))
    for fk in K["complex"]["frequencies"]:
        k = fk["k"]; w = k * hF; ang = w * c
        assert (ang * 2 ** 64).denominator == 1 or (ang * 2 ** 66).denominator == 1, "angle not an exact dyadic"
        # (3) distance to the nearest critical point, with rational pi bounds
        m_near = round(float(2 * ang / PI_LOWER)); dist = min(abs(ang - m_near * PI_LOWER / 2), abs(ang - m_near * PI_UPPER / 2), abs(ang - (m_near + 1) * PI_LOWER / 2), abs(ang - (m_near - 1) * PI_UPPER / 2))
        cs, sn, crit = cos_sin_box(ang, ang); assert not crit
        res["phases"].append({"cell": cell, "k": k, "angle": str(ang), "distance_to_critical_lower": float(dist)})
        wsq = -(w * w) / 2; wt = (dn.exp(box(wsq)[0]), up.exp(box(wsq)[1])); wt = (dn.mul(wt[0], 2), up.mul(wt[1], 2))
        for s_, nm in (("phi_plus", "P"), ("phi_minus", "M")):
            re = (fx(fk[s_]["re"][0]) - Sm, fx(fk[s_]["re"][1]) + Sm); im = (fx(fk[s_]["im"][0]) - Sm, fx(fk[s_]["im"][1]) + Sm)
            term = mul(add(mul((box(re[0])[0], box(re[1])[1]), cs), mul((box(im[0])[0], box(im[1])[1]), sn)), wt)
            if nm == "P": accP = add(accP, term)
            else: accM = add(accM, term)
    accP = mul(accP, pref); accM = mul(accM, pref); GP = (_fr(accP[0]), _fr(accP[1])); GM = (_fr(accM[0]), _fr(accM[1]))
    delta = Fr(W["fourier"]["delta_recomputed_from_input"]["alias_plus_truncation"])
    ind = marker_ratio(GP[0], GP[1], GM[0], GM[1], delta); plo, phi = Fr(W["published"]["lo"]), Fr(W["published"]["hi"])
    margin = min(Fr(ind["lo"]) - plo, phi - Fr(ind["hi"]))
    res["publications"].append({"cell": cell, "published": [str(plo), str(phi)], "independent_widened": [ind["lo"], ind["hi"]], "contained": plo <= Fr(ind["lo"]) and Fr(ind["hi"]) <= phi, "margin": str(margin), "margin_float": float(margin), "S_max_used": str(Sm), "count_halfwidths": [str((GP[1] - GP[0]) / 2), str((GM[1] - GM[0]) / 2)]})
    assert plo <= Fr(ind["lo"]) and Fr(ind["hi"]) <= phi, cell
res["center_updates"] = {"count": nupd, "max_update_error": str(maxerr), "max_update_error_float": float(maxerr), "budget": "1/4096", "all_within": maxerr <= Fr(1, 4096)}
# (4) timing medians
cells = {c["cell"]: c for c in S["cells"]}
D = [cells[f"MAIN_pair{i}_D"]["complete_wall_s"] for i in (1, 2, 3)]; F = [cells[f"MAIN_pair{i}_F"]["complete_wall_s"] for i in (1, 2, 3)]
res["timing"] = {"D": D, "F": F, "paired_ratios": [d / f for d, f in zip(D, F)], "median_paired_ratio": statistics.median([d / f for d, f in zip(D, F)]), "ratio_of_medians": statistics.median(D) / statistics.median(F),
                 "control_overhead": [cells[f"CONTROL_pair{i}_AUTO"]["complete_wall_s"] / cells[f"CONTROL_pair{i}_F"]["complete_wall_s"] for i in (1, 2, 3)]}
res["timing"]["median_control_overhead"] = statistics.median(res["timing"]["control_overhead"])
json.dump(res, open(os.path.join(RUN, "amendments", "saved_record_recomputation.json"), "w"), indent=1)
print(json.dumps({"publications_contained": all(p["contained"] for p in res["publications"]), "min_margin": min(p["margin_float"] for p in res["publications"]), "center_updates": res["center_updates"], "phases": len(res["phases"]), "min_phase_distance": min(p["distance_to_critical_lower"] for p in res["phases"]), "timing": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in res["timing"].items() if "median" in k}}, indent=1, default=str))
