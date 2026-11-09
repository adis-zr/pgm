"""Full-panel applicability accounting for the BIDI kernel (READ-ONLY source checks; no inference): for all 46 accessible cases + 2
inaccessible slots: structural eligibility (binary, pairwise, bipartite), source-range qualification (binary64 normal range with the
factor-two margin), implementation-size limits (m, n <= 60; k <= 12), estimated computational volume (2^min(m,n) configurations and the
analytic per-configuration operation count), the precision contract (delta <= 1/2), and selection into the four-case pilot. A case not
selected is not a failure; a failed range predicate is not a structural impossibility; a capped inspection is UNKNOWN.
    python -m bidi.census_applicability D"""
from __future__ import annotations
import os, sys, json, time, math
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U
from bidi import recognize as RZ, executor as EX

CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08"); SELECTED = {"DBN_11", "DBN_12", "DBN_15", "DBN_16"}; MAX_FILE_BYTES = 50 * 1024 * 1024


def main(D):
    man = json.load(open(os.path.join(CENSUS_D, "CENSUS_MANIFEST.json"))); rows = []
    for c in man["cases"]:
        mp = os.path.join(HERE, c["model_path"]); ep = os.path.join(HERE, c["evidence_path"]); row = {"case": c["case"], "family": c["family"], "accessible": True, "selected_into_pilot": c["case"] in SELECTED, "raw_model_sha256": c["raw_model_sha256"]}
        t = time.monotonic()
        if os.path.getsize(mp) > MAX_FILE_BYTES:
            row.update({"structural": "UNKNOWN", "reason": "inspection capped (file size)"}); rows.append(row); continue
        try:
            m = U.read_model(mp); m.check(); ev = U.read_evidence(ep); plan = RZ.recognize(mp, ep)
            row["variables"] = m.nvars; row["factors"] = len(m.factors); row["max_card"] = max(m.card); row["max_arity"] = max(len(f.scope) for f in m.factors); row["n_evidence"] = len(ev)
            if plan["kind"] != RZ.PLAN_KIND:
                row.update({"structural": "NOT_ELIGIBLE", "reason": plan["reason"], "range": "NOT_EVALUATED", "size_limits": "NOT_EVALUATED"}); rows.append(row); continue
            S = EX.validate_structure(m, ev, plan); rb = EX.range_bounds(S); mm, nn = S["m"], S["n"]
            row.update({"structural": "ELIGIBLE", "sides": [mm, nn], "pair_factors": len(S["psi"]), "complete_bipartite": len(S["psi"]) == mm * nn, "owned": S["owned"]})
            if rb["all_zero_factor"]:
                row["range"] = "ZERO_EVIDENCE_STRUCTURAL"
            else:
                row["log2_L"] = EX.log2_fr(rb["L"]); row["log2_2v_U"] = EX.log2_fr(rb["upper_2v_U"])
                try:
                    EX.check_binary64_range(rb); row["range"] = "BINARY64_NORMAL_OK"
                except EX.Refuse as ex:
                    row["range"] = "BINARY64_RANGE_FAIL"; row["range_reason"] = ex.reason
            row["size_limits"] = "OK" if (mm <= 60 and nn <= 60) else "EXCEEDS_KERNEL_LIMITS"
            P = 1
            while P < nn + 1:
                P <<= 1
            k = min(3, nn); dl = EX.depth_labels(mm, nn, k, P, S["kappa"] == 1); row["depth_e"] = dl["e"]
            try:
                EX.certificate_delta(dl["e"]); row["precision"] = "DELTA_OK"; row["delta"] = float(Fr(dl["e"]) / 2 ** 53)
            except EX.Refuse as ex:
                row["precision"] = "DELTA_FAIL"; row["precision_reason"] = ex.reason
            logP = int(math.log2(P)); ops = (2 * mm + 1) * logP + 7 * mm + 1 + (mm + 1 + (nn - k) + 2 * mm)
            row["estimated_volume"] = {"configurations": 2 ** nn, "ops_per_configuration": ops, "total_ops": ops * 2 ** nn, "log10_total_ops": math.log10(ops * 2 ** nn) if ops else None}
        except Exception as ex:
            row.update({"structural": "UNKNOWN", "reason": "inspection error: %s: %s" % (type(ex).__name__, ex)})
        row["inspection_s"] = time.monotonic() - t; rows.append(row)
    for s in man.get("inaccessible_slots", []):
        rows.append({"case": s.get("case") if isinstance(s, dict) else str(s), "accessible": False, "structural": "UNKNOWN", "reason": "inaccessible slot (source not available)", "selected_into_pilot": False})
    summary = {"accessible": sum(1 for r in rows if r.get("accessible")), "inaccessible": sum(1 for r in rows if not r.get("accessible")), "structurally_eligible": sorted(r["case"] for r in rows if r.get("structural") == "ELIGIBLE"), "not_eligible": sum(1 for r in rows if r.get("structural") == "NOT_ELIGIBLE"), "unknown": sum(1 for r in rows if r.get("structural") == "UNKNOWN"),
               "eligible_and_range_ok": sorted(r["case"] for r in rows if r.get("structural") == "ELIGIBLE" and r.get("range") == "BINARY64_NORMAL_OK"), "selected": sorted(SELECTED), "not_eligible_reasons": {}}
    for r in rows:
        if r.get("structural") == "NOT_ELIGIBLE":
            key = r["reason"].split("(")[0].strip(); summary["not_eligible_reasons"][key] = summary["not_eligible_reasons"].get(key, 0) + 1
    json.dump({"rule": "structural eligibility (binary, pairwise, bipartite) / source-range (binary64 normal with factor-two margin) / size limits / precision (delta <= 1/2) / estimated volume are SEPARATE predicates; eligibility does not promise affordable completion; a case not selected is not a failure; UNKNOWN is not absence", "summary": summary, "rows": rows}, open(os.path.join(D, "APPLICABILITY_CENSUS.json"), "w"), indent=1)
    print(json.dumps(summary))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
