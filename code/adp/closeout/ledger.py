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
    q = load(os.path.join(D, "QUALIFICATION_LEDGER.jsonl")); c = load(os.path.join(D, "CELLS_LEDGER.jsonl")); z = load(os.path.join(D, "CLOSEOUT_LEDGER.jsonl")); rr = load(os.path.join(D, "review_2026-11-08", "REVIEW_REPAIR_LEDGER.jsonl"))
    unresolved = [r for r in c if r.get("supervisor_wall_s") is None and r.get("status") not in ("UNAVAILABLE", "NOT_RUN_BUDGET")]
    by_stage = collections.defaultdict(float); by_arm = collections.defaultdict(float); n_stage = collections.Counter()
    for r in c:
        w = r.get("supervisor_wall_s") or 0.0; by_stage[r["stage"]] += w; by_arm[r["arm"] if r["arm"] != "AGGREGATE_DP_V1" else r.get("config_key", r["arm"])] += w; n_stage[r["stage"]] += 1
    qt = sum(j["wall_s"] for j in q); ct = sum(by_stage.values()); zt = sum(j["wall_s"] for j in z); rt = sum((j["wall_s"] or 0.0) for j in rr); total = qt + ct + zt + rt
    rr_unres = [j for j in rr if j.get("wall_s") is None]; rt_est = sum((j["wall_s"] if j.get("wall_s") is not None else (j.get("wall_s_estimate") or 0.0)) for j in rr)
    out = {"ceiling_s": CEILING, "cell_allowance_s": CELLS_ALLOW, "closeout_reserve_s": 1200.0, "rule": "every top-level receipt once (qualification jobs + cell supervisor walls + closeout jobs); stage runners are not receipts; nested children (checker process) are inside their cell's receipt",
           "qualification_s": round(qt, 3), "qualification_jobs": [{"job": j["job"], "wall_s": round(j["wall_s"], 3), "outcome": j["outcome"]} for j in q],
           "cells_s": round(ct, 3), "cells_by_stage_s": {k: round(v, 3) for k, v in by_stage.items()}, "cells_by_stage_n": dict(n_stage), "stage_allowances_s": STAGES, "over_stage_allowance": {k: round(v - STAGES[k], 1) for k, v in by_stage.items() if v > STAGES.get(k, 0)},
           "cells_by_arm_s": {k: round(v, 3) for k, v in by_arm.items()}, "closeout_s": round(zt, 3), "closeout_jobs": [{"job": j["job"], "wall_s": round(j["wall_s"], 3), "outcome": j["outcome"]} for j in z],
           "review_repair_s": round(rt, 3), "review_repair_jobs": [{"job": j["job"], "wall_s": (round(j["wall_s"], 3) if j.get("wall_s") is not None else None), "wall_s_estimate": j.get("wall_s_estimate"), "outcome": j["outcome"]} for j in rr],
           "written_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()), "authority": "this file in the repository is the authoritative total; prose figures are labelled 'as of <job>'; a packaged copy cannot contain the receipt of the job that writes it",
           "total_charged_s": (round(total, 3) if not (unresolved or rr_unres) else None), "total_lower_bound_s": round(total, 3), "total_with_estimates_s": round(qt + ct + zt + rt_est, 3),
           "total_status": ("EXACT" if not (unresolved or rr_unres) else "UNRESOLVED: %d cell receipts lack a wall; %d review-repair receipts lost (estimated %.0f s)" % (len(unresolved), len(rr_unres), sum((j.get("wall_s_estimate") or 0.0) for j in rr_unres))),
           "remaining_s": (round(CEILING - total, 3) if not (unresolved or rr_unres) else None), "remaining_s_with_estimates": round(CEILING - (qt + ct + zt + rt_est), 3),
           "within_ceiling": (qt + ct + zt + rt_est) <= CEILING, "unresolved_receipts": [r.get("cell_id") for r in unresolved] + [j["job"] for j in rr_unres]}
    json.dump(out, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1); print(json.dumps({k: out[k] for k in ("qualification_s", "cells_s", "cells_by_stage_s", "closeout_s", "total_charged_s", "remaining_s", "within_ceiling", "total_status")}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
