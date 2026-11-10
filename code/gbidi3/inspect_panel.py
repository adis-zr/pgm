"""Uniform READ-ONLY source / plan inspection over all 46 accessible cases + the 2 inaccessible slots (brief §21): production policy entry points
(gbidi3.executor.plan_only with the cell clock semantics: one hard deadline = budget, one optional allowance), no numerical inference, typed statuses,
capped / unknown states preserved. Fields are fixed by this module BEFORE any outcome. Both GENERAL_BIDI_COMPLETE_V3 and NATIVE_PLAIN_COMPLETE_V3 are
inspected at the 20 s policy (the plan is the same at 120 s except for the optional allowance = 1 s in both cases).
    python -m gbidi3.inspect_panel RUN_DIR [budget_s]"""
from __future__ import annotations
import os, sys, json, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from gbidi3 import executor as EX, pilot as PI

FIELDS = ["case", "family", "arm", "status", "reason", "source_stats", "reductions", "plan_candidates", "clock", "plan_validation", "plan_totals", "plan_order", "mechanisms", "node_kinds", "storage_counts", "binary64_admission", "flat_program_words", "memory_ledger", "phases_s"]


def main(D, budget_s=20.0):
    man_c = json.load(open(os.path.join(PI.CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man_c["cases"]}
    rows = []; t0 = time.monotonic()
    for case in PI.inventory():
        cs = cases[case]; mp = os.path.join(HERE, cs["model_path"]); ep = os.path.join(HERE, cs["evidence_path"])
        for arm in ("GENERAL_BIDI_COMPLETE_V3", "NATIVE_PLAIN_COMPLETE_V3"):
            r = EX.plan_only(arm, mp, ep, budget_s)
            row = {"case": case, "family": cs["family"], "arm": arm, "status": r.get("status"), "reason": r.get("reason"), "source_stats": r.get("source_stats"), "reductions": r.get("reductions"), "plan_candidates": r.get("plan_candidates"), "clock": r.get("clock"), "plan_validation": r.get("plan_validation"), "plan_totals": (r.get("plan") or {}).get("totals"), "plan_order": (r.get("plan") or {}).get("order"), "mechanisms": r.get("mechanisms"), "binary64_admission": r.get("binary64_admission"), "flat_program_words": r.get("flat_program_words"), "memory_ledger": r.get("memory_ledger"), "phases_s": r.get("phases_s"), "plan_stop": r.get("plan_stop")}
            nt = (r.get("plan") or {}).get("node_table") or []
            row["node_kinds"] = {k: sum(1 for n in nt if n["kind"] == k) for k in ("SOURCE", "MARKER", "CONSTANT", "GATHER", "ADD", "MUL", "REDUCE")} if nt else None
            row["storage_counts"] = {k: sum(1 for n in nt if n["kind"] == "REDUCE" and n["storage"] == k) for k in ("DENSE", "SPARSE", "STREAM", "CACHE")} if nt else None
            rows.append(row); print(json.dumps({"case": case, "arm": arm, "status": row["status"], "order": row["plan_order"], "totals": row["plan_totals"], "mech": row["mechanisms"]}, default=str), flush=True)
    for c, f in PI.UNAVAILABLE:
        rows.append({"case": c, "family": f, "arm": None, "status": "INPUT_UNAVAILABLE", "reason": "inventory shortfall (3 of 4 available in the frozen 48-slot selection)"})
    out = {"pass": PI.PASS, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "budget_s": budget_s, "fields": FIELDS, "note": "READ-ONLY inspection through production entry points (plan_only); no numerical inference; capped states are UNKNOWN not absence", "rows": rows, "wall_s": time.monotonic() - t0}
    json.dump(out, open(os.path.join(D, "PANEL_INSPECTION.json"), "w"), indent=1, default=str); print(json.dumps({"rows": len(rows), "wall_s": round(out["wall_s"], 2)}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 20.0)
