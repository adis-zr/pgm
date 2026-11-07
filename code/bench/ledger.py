"""Budget reconciliation (spec section 7): every top-level supervised job once, by scope, against the 28,800 s envelope and its allocation.
    python bench/ledger.py SWEEP_DIR  -> BUDGET_LEDGER.json"""
import os, sys, json
ALLOC = {"setup (acquisition, builds, wrapper smoke)": 3600.0, "repair/adapter regression + saved-panel replay": 1800.0, "breadth": 7680.0, "depth": 11520.0, "reference": 2400.0, "diagnostics": 1200.0, "packaging/closeout": 600.0}


def main(S):
    setup = [json.loads(l) for l in open(os.path.join(S, "SETUP_LEDGER.jsonl"))]
    cells = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))] if os.path.exists(os.path.join(S, "CELLS_LEDGER.jsonl")) else []
    refs = [json.loads(l) for l in open(os.path.join(S, "REFERENCE_LEDGER.jsonl"))] if os.path.exists(os.path.join(S, "REFERENCE_LEDGER.jsonl")) else []
    rp = os.path.join(S, "repair_2026-11-07", "REPAIR_LEDGER.jsonl"); repair = [json.loads(l) for l in open(rp)] if os.path.exists(rp) else []
    # ---- the campaign total = EVERY nonnested top-level receipt exactly once (stage supervisors are the receipts for their cells)
    scope_of = {"setup_acquisition": "setup (acquisition, builds, wrapper smoke)", "setup_builds": "setup (acquisition, builds, wrapper smoke)", "repair_regression": "repair/adapter regression + saved-panel replay",
                "breadth_stage_supervisor": "breadth", "depth_stage_supervisor": "depth", "diagnostics_supervisor": "diagnostics", "packaging": "packaging/closeout", "reference": "reference"}
    sc = {k: 0.0 for k in ALLOC}; receipts = []
    for j in setup + refs:
        k = scope_of.get(j["scope"]); assert k is not None, "unmapped scope %r" % j["scope"]
        sc[k] += j["wall_s"]; receipts.append({"job": j["job"], "scope": j["scope"], "wall_s": j["wall_s"], "outcome": j["outcome"]})
    total = sum(sc.values())
    # ---- nested detail: cells inside the stage supervisors (NOT added to the total)
    nested = {"breadth_cells_s": 0.0, "breadth_amendment_rerun_cells_s": 0.0, "depth_cells_s": 0.0, "diagnostic_cells_s": 0.0}
    for r in cells:
        w = r.get("supervisor_wall_s", 0.0) or 0.0; lab = r.get("label")
        if lab is None:
            nested[("breadth" if r["stage"] == "breadth" else "depth") + "_cells_s"] += w
        elif str(lab).startswith("amendment"):
            nested["breadth_amendment_rerun_cells_s"] += w
        else:
            nested["diagnostic_cells_s"] += w
    # ---- the separate prospective REPAIR ledger (review of 7 Nov 2026): 1,800 s allowance from the unspent campaign envelope
    rep_total = sum(j["wall_s"] for j in repair)
    # ---- the DIAGNOSTIC campaign (7 Nov 2026): nonnested receipts = DIAG_LEDGER jobs (census, controls, overhead) + every diagnostic cell row
    # (the family runner is not a receipt; its cells are) -- 22,000 s ceiling; aggregate ceiling 28,800 s over campaign + repairs + diagnostics
    dp = os.path.join(S, "diag_2026-11-07", "DIAG_LEDGER.jsonl"); diag_jobs = [json.loads(l) for l in open(dp)] if os.path.exists(dp) else []
    dcp = os.path.join(S, "diag_2026-11-07", "DIAG_CELLS_LEDGER.jsonl"); diag_cells = [json.loads(l) for l in open(dcp)] if os.path.exists(dcp) else []
    dscope = {}
    for j in diag_jobs:
        dscope[j["scope"]] = dscope.get(j["scope"], 0.0) + j["wall_s"]
    dfam = {}
    for r in diag_cells:
        dfam[r.get("family_code")] = dfam.get(r.get("family_code"), 0.0) + (r.get("supervisor_wall_s") or 0.0)
    diag_total = sum(dscope.values()) + sum(dfam.values())
    aggregate = total + rep_total + diag_total
    out = {"envelope_s": 28800.0, "aggregate_ceiling_rule": "campaign (nonnested receipts) + repair receipts + diagnostic receipts (DIAG_LEDGER jobs + diagnostic cell rows) <= 28,800 s; diagnostic receipts alone <= 22,000 s",
           "aggregate_charged_s": round(aggregate, 6), "aggregate_remaining_s": round(28800.0 - aggregate, 6),
           "diagnostic_2026-11-07": {"ceiling_s": 22000.0, "charged_s": round(diag_total, 6), "by_scope_jobs": {k: round(v, 3) for k, v in dscope.items()}, "by_family_cells": {k: round(v, 3) for k, v in dfam.items()}, "cells": len(diag_cells), "jobs": len(diag_jobs),
                                     "family_caps_s": {"A": 6440, "B": 2760, "C": 6440, "D": 2280, "E": 240}, "closeout_reserve_s": 1200}, "allocation_s": ALLOC, "charged_s": {k: round(v, 6) for k, v in sc.items()}, "nonnested_receipts": len(receipts), "total_charged_s": round(total, 9),
           "remaining_s_after_campaign_and_repairs": round(28800.0 - total - rep_total, 6), "nested_cell_sums_s_not_added": {k: round(v, 3) for k, v in nested.items()},
           "accounting_rule": "every top-level supervised receipt in SETUP_LEDGER.jsonl and REFERENCE_LEDGER.jsonl counted exactly once (spawn-to-reap of its process tree); cells run INSIDE a stage supervisor are nested detail and are not added again",
           "repair_ledger_2026-11-07": {"allowance_s": 1800.0, "charged_s": round(rep_total, 6), "receipts": len(repair), "jobs": [{"job": j["job"], "wall_s": round(j["wall_s"], 3), "outcome": j["outcome"]} for j in repair]},
           "over_allocation": {k: round(v - ALLOC[k], 1) for k, v in sc.items() if v > ALLOC[k]}, "receipts": receipts}
    json.dump(out, open(os.path.join(S, "BUDGET_LEDGER.json"), "w"), indent=1); print(json.dumps({k: out[k] for k in ("charged_s", "nonnested_receipts", "total_charged_s", "aggregate_charged_s", "aggregate_remaining_s", "over_allocation")}, indent=1)); print("repair ledger: %.3f s of 1800 in %d receipts | diagnostic: %.3f s of 22000 (%d jobs + %d cells)" % (rep_total, len(repair), diag_total, len(diag_jobs), len(diag_cells)))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
