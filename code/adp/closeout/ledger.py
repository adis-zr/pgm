"""Budget ledger of the AGGREGATE_DP_2026-11-07 campaign: every nonnested top-level receipt exactly once.
Receipts: QUALIFICATION_LEDGER.jsonl (bench/charge.py jobs: tests, packet-control replays), CELLS_LEDGER.jsonl (every cell: the
supervisor's spawn-to-reap wall of the fresh process tree incl. the checker child), CLOSEOUT_LEDGER.jsonl (scoring / report /
packaging jobs). Stage runners are not receipts (their cells are). Lost receipts are reported as UNRESOLVED (no exact total).
Ceiling: 28,800 s (new, separate from the historical campaign); cell allowance 23,920 s; closeout reserve 1,200 s.
    python adp/ledger.py D -> D/BUDGET_LEDGER.json"""
import os, sys, json, collections
CEILING = 28800.0; CELLS_ALLOW = 23920.0; STAGES = {"P20": 4600.0, "P120": 11040.0, "ABL": 4600.0, "REP": 3680.0}


def load(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def main(D):
    q = load(os.path.join(D, "QUALIFICATION_LEDGER.jsonl")); c = load(os.path.join(D, "CELLS_LEDGER.jsonl")); z = load(os.path.join(D, "CLOSEOUT_LEDGER.jsonl"))
    unresolved = [r for r in c if r.get("supervisor_wall_s") is None and r.get("status") not in ("UNAVAILABLE", "NOT_RUN_BUDGET")]
    by_stage = collections.defaultdict(float); by_arm = collections.defaultdict(float); n_stage = collections.Counter()
    for r in c:
        w = r.get("supervisor_wall_s") or 0.0; by_stage[r["stage"]] += w; by_arm[r["arm"] if r["arm"] != "AGGREGATE_DP_V1" else r.get("config_key", r["arm"])] += w; n_stage[r["stage"]] += 1
    qt = sum(j["wall_s"] for j in q); ct = sum(by_stage.values()); zt = sum(j["wall_s"] for j in z); total = qt + ct + zt
    out = {"ceiling_s": CEILING, "cell_allowance_s": CELLS_ALLOW, "closeout_reserve_s": 1200.0, "rule": "every top-level receipt once (qualification jobs + cell supervisor walls + closeout jobs); stage runners are not receipts; nested children (checker process) are inside their cell's receipt",
           "qualification_s": round(qt, 3), "qualification_jobs": [{"job": j["job"], "wall_s": round(j["wall_s"], 3), "outcome": j["outcome"]} for j in q],
           "cells_s": round(ct, 3), "cells_by_stage_s": {k: round(v, 3) for k, v in by_stage.items()}, "cells_by_stage_n": dict(n_stage), "stage_allowances_s": STAGES, "over_stage_allowance": {k: round(v - STAGES[k], 1) for k, v in by_stage.items() if v > STAGES.get(k, 0)},
           "cells_by_arm_s": {k: round(v, 3) for k, v in by_arm.items()}, "closeout_s": round(zt, 3), "closeout_jobs": [{"job": j["job"], "wall_s": round(j["wall_s"], 3), "outcome": j["outcome"]} for j in z],
           "total_charged_s": (round(total, 3) if not unresolved else None), "total_status": ("EXACT" if not unresolved else "UNRESOLVED: %d cell receipts lack a wall" % len(unresolved)), "remaining_s": (round(CEILING - total, 3) if not unresolved else None),
           "within_ceiling": (total <= CEILING) if not unresolved else None, "unresolved_receipts": [r.get("cell_id") for r in unresolved]}
    json.dump(out, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1); print(json.dumps({k: out[k] for k in ("qualification_s", "cells_s", "cells_by_stage_s", "closeout_s", "total_charged_s", "remaining_s", "within_ceiling", "total_status")}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
