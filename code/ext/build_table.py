"""Assemble the nine-cell machine-readable result table."""
from __future__ import annotations
import os, sys, json, glob

RD = "runs/ext_2026-10-28"
PROBLEMS = [("EXT-01", "Grids_11"), ("EXT-02", "Pedigree_11"), ("EXT-03", "Promedus_12")]
ORDER = {"Grids_11": ["ARB", "IJGP", "ours"],
         "Pedigree_11": ["IJGP", "ours", "ARB"],
         "Promedus_12": ["ours", "ARB", "IJGP"]}
PAPER_T1 = {"Grids_11": {"merlin_ijgp": 0.039, "arb": 1.253},
            "Pedigree_11": {"merlin_ijgp": 0.128, "arb": 0.795},
            "Promedus_12": {"merlin_ijgp": 0.185, "arb": 1.483}}
IBIA20 = {"Grids_11": 0.166, "Pedigree_11": 5e-7, "Promedus_12": 0.242}
KEY = {"ARB": "arb", "IJGP": "merlin", "ours": "ours"}


def load(p):
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    rows = []
    for eid, prob in PROBLEMS:
        for meth in ORDER[prob]:
            k = KEY[meth]
            rec = load(os.path.join(RD, "%s_%s_record.json" % (k, prob)))
            sc = load(os.path.join(RD, "%s_%s_score.json" % (k, prob)))
            r = {"cell": "%s/%s" % (eid, meth), "problem_id": eid, "problem": prob,
                 "method": meth, "invocation_order_index": ORDER[prob].index(meth) + 1}
            if rec is None:
                r["outcome"] = "NOT_RUN"
                r["reason"] = "no record file"
                rows.append(r); continue
            r["outcome"] = rec.get("outcome")
            r["elapsed_s"] = rec.get("elapsed_s")
            r["peak_tree_rss_kib"] = rec.get("peak_tree_rss_kib")
            r["returncode"] = rec.get("returncode")
            r["threads_declared"] = rec.get("threads_declared", 6)
            if meth == "ours":
                r["outcome"] = rec["outcome"]
                r["reason"] = "; ".join(b["category"] for b in rec["blockers"])
                r["n_blocking_reasons"] = len(rec["blockers"])
                r["certificate"] = rec["certificate"]
                r["max_hellinger"] = None
                r["mean_hellinger"] = None
                r["max_coord_abs_error"] = None
                r["neg_log2_max_hellinger"] = None
                r["stages"] = rec.get("stages")
            else:
                if sc and "error" not in sc:
                    r["max_hellinger"] = sc["max_hellinger"]
                    r["mean_hellinger"] = sc["mean_hellinger"]
                    r["max_coord_abs_error"] = sc["max_coord_abs_error"]
                    r["neg_log2_max_hellinger"] = sc["neg_log2_max_hellinger"]
                    r["unobserved_scored"] = sc["unobserved_scored"]
                    r["validation_issues"] = sc["n_validation_issues"]
                    r["point_output"] = sc["point_output"]
                    if r["outcome"] == "COMPLETED":
                        r["outcome"] = "UNCERTIFIED_OUTPUT"
                else:
                    r["reason"] = (sc or {}).get("error", "not scored")
                r["certificate"] = {
                    "coverage_of_requested_coordinates": 0.0,
                    "max_interval_width": None,
                    "independent_checker_status": "NOT_APPLICABLE (baseline produces point "
                                                  "estimates, no interval certificate)",
                    "guarantee_class": "NONE. ARB is MCMC: its convergence diagnostics do "
                                       "NOT imply finite-sample coverage. IJGP is "
                                       "approximate message passing with no error bound at "
                                       "this i-bound."}
            r["paper_table1_neg_log2"] = PAPER_T1[prob].get(
                "arb" if meth == "ARB" else "merlin_ijgp") if meth != "ours" else None
            rows.append(r)
    tbl = {"generated": __import__("time").strftime("%Y-%m-%dT%H:%M:%S%z"),
           "cells_planned": 9, "cells_present": len(rows),
           "published_anchors": {
               "note": "Paper-reported values. NOT measurements on our machine.",
               "paper_table1_neg_log2_max_hellinger": PAPER_T1,
               "ibia20_max_hellinger_from_supplement": IBIA20,
               "ibia_caveat": "IBIA's runnable MAR implementation was not verified during "
                              "selection and was NOT reimplemented. Its stronger published "
                              "result is retained here and is not compared as a measurement."},
           "rows": rows}
    json.dump(tbl, open(os.path.join(RD, "RESULT_TABLE.json"), "w"), indent=2)
    print("%-18s %-6s %-22s %10s %9s %9s" % ("cell", "ord", "outcome", "elapsed_s", "maxH", "-log2"))
    for r in rows:
        print("%-18s %-6s %-22s %10s %9s %9s" % (
            r["cell"], r.get("invocation_order_index"), r["outcome"],
            ("%.2f" % r["elapsed_s"]) if r.get("elapsed_s") is not None else "-",
            ("%.6f" % r["max_hellinger"]) if r.get("max_hellinger") is not None else "-",
            ("%.3f" % r["neg_log2_max_hellinger"]) if r.get("neg_log2_max_hellinger") is not None else "-"))


if __name__ == "__main__":
    main()
