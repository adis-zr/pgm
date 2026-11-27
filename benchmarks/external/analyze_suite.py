#!/usr/bin/env python3
"""Recompute completion/geometry and libDAI comparisons from frozen raw artifacts."""

from __future__ import annotations
import csv, json, statistics
from fractions import Fraction as F
from pathlib import Path
import run_suite as h

ROOT = h.ROOT
ALLOW = 5e-10


def main():
    f = h.relocate_frozen_tasks(json.loads((ROOT / "FREEZE.json").read_text()))
    tasks = {t["name"]: t for t in f["tasks"]}
    rows = [
        json.loads(x)
        for x in (ROOT / "CELLS.jsonl").read_text().splitlines()
        if x.strip()
    ]
    expected = {
        (t["name"], arm, r)
        for t in f["tasks"]
        for arm in f["arms"]
        for r in f["replicates"]
    }
    observed = [(r["task"], r["arm"], r["replicate"]) for r in rows]
    issues = []
    if len(set(observed)) != len(observed):
        issues.append("Duplicate scored cell keys")
    missing = sorted(expected - set(observed))
    extra = sorted(set(observed) - expected)
    if extra:
        issues.append("Unexpected cell keys")
    checks = []
    geometry = {
        "published_coordinate_instances": 0,
        "faulty_published_results": 0,
        "max_endpoint_radius": 0.0,
    }
    jt_diag = []
    bp_diag = []
    bykey = {key: r for key, r in zip(observed, rows)}
    terminal = h.receipts(ROOT / "RECEIPTS.jsonl")
    receipt_index = {}
    for receipt in terminal:
        receipt_index.setdefault(receipt["job"], []).append(receipt)
    for r in rows:
        folder = ROOT / "runs" / r["job"]
        task = tasks[r["task"]]
        owned = receipt_index.get(r["job"], [])
        if len(owned) != 1:
            issues.append("Expected exactly one terminal receipt: " + r["job"])
            receipt = {}
        else:
            receipt = owned[0]
            for cell_key, receipt_key in (
                ("wall_s", "wall_s"),
                ("returncode", "returncode"),
                ("receipt_outcome", "outcome"),
                ("peak_rss_bytes", "peak_tree_rss_bytes"),
            ):
                if r.get(cell_key) != receipt.get(receipt_key):
                    issues.append(
                        "Cell/receipt disagreement: " + r["job"] + " " + cell_key
                    )
        checked = {"output_valid": False, "all_queries_returned": False}
        output_exists = (
            folder / ("result.json" if r["arm"] == "PGM" else "output.MAR")
        ).exists()
        if output_exists:
            try:
                checked = (
                    h.check_pgm(folder / "result.json", task)
                    if r["arm"] == "PGM"
                    else h.check_libdai(folder, task)
                )
                if r["arm"] == "PGM":
                    geometry["published_coordinate_instances"] += checked["published"]
                    geometry["max_endpoint_radius"] = max(
                        geometry["max_endpoint_radius"], checked["max_published_radius"]
                    )
                    if not checked["output_valid"]:
                        geometry["faulty_published_results"] += 1
                        checks.append(
                            {"job": r["job"], "faults": checked["validation_faults"]}
                        )
                for key in ("output_valid", "all_queries_returned"):
                    if r.get(key) != checked[key]:
                        issues.append(
                            "Analysis disagrees with cell " + r["job"] + " " + key
                        )
            except Exception as e:
                checks.append({"job": r["job"], "error": repr(e)})
        input_ok = all(
            h.sha(task[key]) == task[key + "_sha256"] for key in ("model", "evidence")
        )
        if not input_ok:
            issues.append("Input changed " + r["job"])
        if not r.get("identity_ok", False):
            issues.append("Cell source identity failed " + r["job"])
        completed = bool(
            input_ok
            and r.get("identity_ok", False)
            and checked["all_queries_returned"]
            and receipt.get("outcome") == "COMPLETED"
            and receipt.get("wall_s", float("inf")) <= f["budget_s"]
        )
        if completed != r.get("complete_within_contract", False):
            issues.append("Recomputed completion disagrees with cell " + r["job"])
        r["complete_within_contract"] = completed
        r["converged_within_contract"] = completed and (
            r["arm"] != "LIBDAI_BP" or checked.get("converged", False)
        )
        # Timing tables use the authoritative receipt, not the copied cell summary.
        if receipt:
            r["wall_s"] = receipt["wall_s"]
            r["receipt_outcome"] = receipt["outcome"]
    groups = {}
    pairs = []
    for cohort in ["historical46", "external_extension", "prospective_external_eval"]:
        tt = [t for t in f["tasks"] if t["historical_cohort"] == cohort]
        if not tt:
            continue
        sets = {}
        one_rep = {}
        converged = {}
        for arm in f["arms"]:
            sets[arm] = sorted(
                t["name"]
                for t in tt
                if all(
                    bykey.get((t["name"], arm, rep), {}).get(
                        "complete_within_contract", False
                    )
                    for rep in f["replicates"]
                )
            )
            one_rep[arm] = sorted(
                t["name"]
                for t in tt
                if sum(
                    bykey.get((t["name"], arm, rep), {}).get(
                        "complete_within_contract", False
                    )
                    for rep in f["replicates"]
                )
                == 1
            )
            converged[arm] = sorted(
                t["name"]
                for t in tt
                if all(
                    bykey.get((t["name"], arm, rep), {}).get(
                        "converged_within_contract", False
                    )
                    for rep in f["replicates"]
                )
            )
        mutual = sorted(set(sets["PGM"]) & set(sets["LIBDAI_JT"]))
        cohortpairs = []
        for t in tt:
            row = {
                "task": t["name"],
                "cohort": cohort,
                "pgm_complete_both": t["name"] in sets["PGM"],
                "jt_complete_both": t["name"] in sets["LIBDAI_JT"],
                "bp_complete_both": t["name"] in sets["LIBDAI_BP"],
            }
            for arm in f["arms"]:
                rr = [bykey.get((t["name"], arm, r), {}) for r in f["replicates"]]
                for i, x in enumerate(rr, 1):
                    row[f"{arm}_r{i}_wall_s"] = x.get("wall_s")
                    row[f"{arm}_r{i}_status"] = x.get(
                        "solver_outcome", x.get("receipt_outcome")
                    )
                if len(rr) == 2 and all(x.get("complete_within_contract") for x in rr):
                    row[arm + "_median_s"] = statistics.median(x["wall_s"] for x in rr)
            if t["name"] in mutual:
                row["JT_over_PGM_median"] = (
                    row["LIBDAI_JT_median_s"] / row["PGM_median_s"]
                )
                for rep in f["replicates"]:
                    row[f"JT_over_PGM_r{rep}"] = (
                        bykey[t["name"], "LIBDAI_JT", rep]["wall_s"]
                        / bykey[t["name"], "PGM", rep]["wall_s"]
                    )
                cohortpairs.append(row["JT_over_PGM_median"])
            if row["pgm_complete_both"] and not row["jt_complete_both"]:
                timeout_reps = [
                    rep
                    for rep in f["replicates"]
                    if bykey.get((t["name"], "LIBDAI_JT", rep), {}).get(
                        "receipt_outcome"
                    )
                    == "TIMEOUT_KILL"
                ]
                if len(timeout_reps) == 2:
                    row["JT_timeout_lower_bound_both"] = min(
                        f["budget_s"] / bykey[t["name"], "PGM", rep]["wall_s"]
                        for rep in timeout_reps
                    )
            pairs.append(row)
        groups[cohort] = {
            "inputs": len(tt),
            "complete_both": sets,
            "one_replicate_only": one_rep,
            "converged_both": converged,
            "mutual_pgm_jt": mutual,
            "pgm_only_vs_jt": sorted(set(sets["PGM"]) - set(sets["LIBDAI_JT"])),
            "jt_only_vs_pgm": sorted(set(sets["LIBDAI_JT"]) - set(sets["PGM"])),
            "median_task_JT_over_PGM": (
                statistics.median(cohortpairs) if cohortpairs else None
            ),
        }
    for t in f["tasks"]:
        for rep in f["replicates"]:
            pg = bykey.get((t["name"], "PGM", rep), {})
            jt = bykey.get((t["name"], "LIBDAI_JT", rep), {})
            bp = bykey.get((t["name"], "LIBDAI_BP", rep), {})
            if pg.get("complete_within_contract") and jt.get(
                "complete_within_contract"
            ):
                out = json.loads(
                    (ROOT / "runs" / pg["job"] / "result.json").read_text()
                )
                p = h.read_mar(ROOT / "runs" / jt["job"] / "output.MAR", t)
                outside = 0
                coords = 0
                maxdistance = 0.0
                for r in out["answers"]:
                    key = (r.get("variable", r.get("var")), r["state"])
                    lo = float(F(str(r["lo"])))
                    hi = float(F(str(r["hi"])))
                    x = p[key]
                    dist = max(lo - x, x - hi, 0.0)
                    maxdistance = max(maxdistance, dist)
                    outside += dist > ALLOW
                    coords += 1
                jt_diag.append(
                    {
                        "task": t["name"],
                        "replicate": rep,
                        "coordinates": coords,
                        "outside_after_serialization_allowance": outside,
                        "max_distance": maxdistance,
                    }
                )
            if bp.get("complete_within_contract") and jt.get(
                "complete_within_contract"
            ):
                a = h.read_mar(ROOT / "runs" / bp["job"] / "output.MAR", t)
                b = h.read_mar(ROOT / "runs" / jt["job"] / "output.MAR", t)
                delta = max(abs(a[k] - b[k]) for k in a)
                bp_diag.append(
                    {
                        "task": t["name"],
                        "replicate": rep,
                        "max_point_difference": delta,
                        "within_epsilon": delta <= float(h.EPS) + 2 * ALLOW,
                    }
                )
    old = json.loads(h.REFERENCE.read_text())["cells"]
    prior = {
        r["task"]
        for r in old
        if r["arm"] == "PGM"
        and r["budget_s"] == 20
        and all(
            any(
                s["task"] == r["task"]
                and s["arm"] == "PGM"
                and s["budget_s"] == 20
                and s["replicate"] == rep
                and s["complete_within_contract"]
                for s in old
            )
            for rep in (1, 2)
        )
    }
    new = set().union(
        *(
            set(g["complete_both"]["PGM"])
            for key, g in groups.items()
            if key != "prospective_external_eval"
        )
    )
    prior_comparison = {
        "caveat": "Historical previous execution on same input hashes and20s contract, not a same-round controlled baseline arm; no paired latency claim.",
        "prior_complete_both": sorted(prior),
        "retained": sorted(prior & new),
        "lost": sorted(prior - new),
        "gained": sorted(new - prior),
    }
    charges = h.receipts(ROOT / "RECEIPTS.jsonl")
    result = {
        "schema": "CONSOLIDATION_EXTERNAL_ANALYSIS_V1",
        "engine_commit": f["engine_commit"],
        "freeze_sha256": h.sha(ROOT / "FREEZE.json"),
        "expected_cells": len(expected),
        "recorded_cells": len(rows),
        "missing_cells": missing,
        "validation_issues": issues,
        "artifact_faults": checks,
        "geometry": geometry,
        "groups": groups,
        "pairs": pairs,
        "prior_accepted_comparison": prior_comparison,
        "jt_agreement": jt_diag,
        "bp_jt_agreement": bp_diag,
        "point_serialization_allowance": ALLOW,
        "charge_s": sum(r["wall_s"] for r in charges),
        "terminal_receipts": len(charges),
        "reported_certificates_are_not_exact_oracle_validation": True,
    }
    h.dump(ROOT / "ANALYSIS.json", result)
    fields = sorted({k for r in pairs for k in r})
    with (ROOT / "PAIRS.csv").open("w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        w.writerows(pairs)
    lines = [
        "# Consolidated public API external benchmark",
        "",
        f"Engine `{f['engine_commit']}`. Recorded{len(rows)}/{len(expected)} cells; charged{result['charge_s']:.3f}s /{f['scored_ceiling_s']}s.",
        "",
        "One frozen public entrypoint,20 seconds end to end,3 GiB sampled process-tree RSS,epsilon0.005 and per-request delta1e-6. Every completion count requires both repeats. PGM deterministic/PAC certificates and libDAI point output have different assurance contracts.",
        "",
        "| Cohort | Inputs | PGM | JT | BP points | BP converged |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, g in groups.items():
        lines.append(
            f"| {name} | {g['inputs']} | {len(g['complete_both']['PGM'])} | {len(g['complete_both']['LIBDAI_JT'])} | {len(g['complete_both']['LIBDAI_BP'])} | {len(g['converged_both']['LIBDAI_BP'])} |"
        )
    lines += [
        "",
        "The55 previously executed inputs are exposed regression tasks. Prospective evaluation tasks were selected by a frozen family-balanced hash rule after excluding model hashes in available prior records. This is not a claim that they were never encountered in unavailable historical records, and it is not unseen-family evaluation. Neither cohort contains synthetic performance tests.",
        "",
        f"Historical accepted-engine completions retained:{len(prior&new)}/{len(prior)}. Lost:{', '.join(sorted(prior-new)) or 'none'}. Gained:{', '.join(sorted(new-prior)) or 'none'}. This is a historical coverage comparison, not a controlled same-round latency comparison.",
        "",
        "## Timing and failures",
        "",
    ]
    measured = sorted(
        (p for p in pairs if "JT_over_PGM_median" in p),
        key=lambda p: p["JT_over_PGM_median"],
        reverse=True,
    )
    lines += [
        "| Input | Cohort | PGM median s | JT median s | JT/PGM | Repeat1 | Repeat2 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for p in measured:
        lines.append(
            f"| {p['task']} | {p['cohort']} | {p['PGM_median_s']:.4f} | {p['LIBDAI_JT_median_s']:.4f} | {p['JT_over_PGM_median']:.3f} | {p['JT_over_PGM_r1']:.3f} | {p['JT_over_PGM_r2']:.3f} |"
        )
    for name, g in groups.items():
        lines += [
            "",
            f"{name}: PGM-only vs JT: {', '.join(g['pgm_only_vs_jt']) or 'none'}. JT-only vs PGM: {', '.join(g['jt_only_vs_pgm']) or 'none'}. One-repeat-only cases: {json.dumps(g['one_replicate_only'])}.",
        ]
    lines += [
        "",
        "Ratios above one favor PGM. Memory refusals have no speedup denominator. Timeouts provide only explicitly censored lower bounds. The full pair table retains failures. Two repeats do not establish population confidence intervals.",
        "",
        f"Independent artifact checks: {len(issues)} identity/scoring issues; {len(checks)} faulty published artifacts; {geometry['published_coordinate_instances']} published coordinate instances, maximum endpoint radius{geometry['max_endpoint_radius']:.9g}. JT points outside PGM enclosures after the explicit{ALLOW} serialization allowance: {sum(d['outside_after_serialization_allowance'] for d in jt_diag)}. BP agrees with JT to epsilon in{sum(d['within_epsilon'] for d in bp_diag)}/{len(bp_diag)} paired cells. These are agreement diagnostics, not independent exact truth or empirical validation of delta1e-6.",
        "",
        "This campaign measures the public implementation on external inputs. A pass does not establish universal dominance, an instance-optimality theorem, or broad scaling behavior from one task per family. H4 and other synthetic/natively supplied specialist fixtures remain correctness/mechanism evidence outside external performance totals.",
    ]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "recorded_cells": len(rows),
                "expected_cells": len(expected),
                "validation_issues": len(issues),
                "artifact_faults": len(checks),
                "charge_s": result["charge_s"],
                "coverage": {
                    name: {a: len(v) for a, v in g["complete_both"].items()}
                    for name, g in groups.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
