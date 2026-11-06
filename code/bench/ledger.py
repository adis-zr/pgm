"""Budget reconciliation (spec section 7): every top-level supervised job once, by scope, against the 28,800 s envelope and its allocation.
    python bench/ledger.py SWEEP_DIR  -> BUDGET_LEDGER.json"""
import os, sys, json
ALLOC = {"setup (acquisition, builds, wrapper smoke)": 3600.0, "repair/adapter regression + saved-panel replay": 1800.0, "breadth": 7680.0, "depth": 11520.0, "reference": 2400.0, "diagnostics": 1200.0, "packaging/closeout": 600.0}


def main(S):
    setup = [json.loads(l) for l in open(os.path.join(S, "SETUP_LEDGER.jsonl"))]
    cells = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))] if os.path.exists(os.path.join(S, "CELLS_LEDGER.jsonl")) else []
    refs = [json.loads(l) for l in open(os.path.join(S, "REFERENCE_LEDGER.jsonl"))] if os.path.exists(os.path.join(S, "REFERENCE_LEDGER.jsonl")) else []
    sc = {k: 0.0 for k in ALLOC}; detail = {}
    for j in setup:
        if j["scope"] in ("setup_acquisition", "setup_builds"):
            sc["setup (acquisition, builds, wrapper smoke)"] += j["wall_s"]
        elif j["scope"] == "repair_regression":
            sc["repair/adapter regression + saved-panel replay"] += j["wall_s"]
        elif j["scope"].endswith("_stage_supervisor"):
            detail.setdefault("stage_supervisor_outer_walls_s (NOT added: the cells inside are charged individually; the difference is scheduling / reaping overhead)", {})[j["job"]] = j["wall_s"]
        elif j["scope"] == "packaging":
            sc["packaging/closeout"] += j["wall_s"]
        else:
            detail.setdefault("other_setup_scopes", {})[j["job"]] = j["wall_s"]
    for r in cells:
        w = r.get("supervisor_wall_s", 0.0) or 0.0
        if r.get("label") is not None and str(r["label"]).startswith("amendment"):
            sc[r["stage"]] += w                                   # amended reruns of primary cells are charged to their stage
        elif r.get("label") is not None:
            sc["diagnostics"] += w
        elif r["stage"] == "breadth":
            sc["breadth"] += w
        elif r["stage"] == "depth":
            sc["depth"] += w
    for j in refs:
        sc["reference"] += j.get("wall_s", 0.0) or 0.0
    # reaping overhead = supervisor outer wall - sum of cell walls, per stage
    ov = {}
    for k, v in (detail.get("stage_supervisor_outer_walls_s (NOT added: the cells inside are charged individually; the difference is scheduling / reaping overhead)") or {}).items():
        st = "breadth" if "breadth" in k else "depth" if "depth" in k else k
        ov[k] = {"outer_wall_s": v, "cells_sum_s": sc.get(st, 0.0), "overhead_s": v - sc.get(st, 0.0)}
    total = sum(sc.values()) + sum(o["overhead_s"] for o in ov.values() if o["overhead_s"] > 0)
    out = {"envelope_s": 28800.0, "allocation_s": ALLOC, "charged_s": {k: round(v, 2) for k, v in sc.items()}, "stage_overheads": ov, "total_charged_incl_overheads_s": round(total, 2), "remaining_s": round(28800.0 - total, 2),
           "counts": {"setup_jobs": len(setup), "cells": len(cells), "reference_jobs": len(refs)}, "accounting_rule": "each top-level supervised job once (spawn-to-reap of its process tree); stage supervisors are not added on top of their cells, only their scheduling / reaping overhead is",
           "over_allocation": {k: round(v - ALLOC[k], 1) for k, v in sc.items() if v > ALLOC[k]}}
    json.dump(out, open(os.path.join(S, "BUDGET_LEDGER.json"), "w"), indent=1); print(json.dumps({k: out[k] for k in ("charged_s", "total_charged_incl_overheads_s", "remaining_s", "over_allocation")}, indent=1))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
