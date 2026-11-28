#!/usr/bin/env python3
"""Recompute the untuned-runtime campaign from raw artifacts and terminal receipts.

The existing result readers remain the independent publication boundary. Historical
Mac coverage is reported separately from the controlled same-host comparison. BP
is a point-only diagnostic; missing/timeout cells never become latency denominators.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction as F
import json
from pathlib import Path
import statistics

import run_suite as h

ALLOWANCE = F(5, 10_000_000_000)
PUBLIC_ARMS = ("BASE_ACCEPTED", "PGM_ACCEPTED", "BASE_EXPERIMENTAL", "PGM_AUTOMATIC")
PAIRS = {
    "accepted_preservation": ("PGM_ACCEPTED", "BASE_ACCEPTED"),
    "automatic_vs_experimental": ("PGM_AUTOMATIC", "BASE_EXPERIMENTAL"),
    "automatic_vs_accepted": ("PGM_AUTOMATIC", "BASE_ACCEPTED"),
    "accepted_vs_jt": ("PGM_ACCEPTED", "LIBDAI_JT"),
    "automatic_vs_jt": ("PGM_AUTOMATIC", "LIBDAI_JT"),
    "accepted_vs_bp_points": ("PGM_ACCEPTED", "LIBDAI_BP"),
    "automatic_vs_bp_points": ("PGM_AUTOMATIC", "LIBDAI_BP"),
}


def median(values):
    return statistics.median(values) if values else None


def complete_sets(rows, tasks, arms, replicates):
    bykey = {(r["task"], r["arm"], r["replicate"]): r for r in rows}
    return {arm: sorted(name for name in tasks if all(
        bykey.get((name, arm, rep), {}).get("complete_within_contract") is True
        for rep in replicates)) for arm in arms}


def compare_pair(rows, tasks, replicates, candidate, comparator):
    """Only both-repeat mutual completions receive wall or RSS ratios."""
    bykey = {(r["task"], r["arm"], r["replicate"]): r for r in rows}
    sets = complete_sets(rows, tasks, [candidate, comparator], replicates)
    a, b = set(sets[candidate]), set(sets[comparator])
    pairs = []
    for name in sorted(a & b):
        aa = [bykey[name, candidate, r] for r in replicates]
        bb = [bykey[name, comparator, r] for r in replicates]
        aw = [r["wall_s"] for r in aa]; bw = [r["wall_s"] for r in bb]
        ratios = [x / y for x, y in zip(aw, bw)]
        differences = [x - y for x, y in zip(aw, bw)]
        pairs.append(dict(task=name, candidate_walls=aw, comparator_walls=bw,
                          ratios_per_repeat=ratios, differences_s=differences,
                          ratio_of_medians=median(aw) / median(bw),
                          speedup_of_medians=median(bw) / median(aw),
                          faster_every_repeat=all(x < 1 for x in ratios),
                          slower_every_repeat=all(x > 1 for x in ratios),
                          cost_flag=all(x > 1.25 for x in ratios) and all(x > 0.1 for x in differences),
                          candidate_peak_rss_bytes=[r.get("peak_rss_bytes") for r in aa],
                          comparator_peak_rss_bytes=[r.get("peak_rss_bytes") for r in bb]))
    return dict(candidate=candidate, comparator=comparator, mutual_both=sorted(a & b),
                candidate_only=sorted(a - b), comparator_only=sorted(b - a),
                neither=sorted(set(tasks) - a - b), per_task=pairs,
                median_wall_ratio=median([p["ratio_of_medians"] for p in pairs]),
                faster_every_repeat=sum(p["faster_every_repeat"] for p in pairs),
                slower_every_repeat=sum(p["slower_every_repeat"] for p in pairs),
                cost_flags=[p["task"] for p in pairs if p["cost_flag"]],
                interpretation=("Point-only BP comparison; this is not equal-guarantee inference."
                                if comparator == "LIBDAI_BP" else "End-to-end ratio on both-repeat mutual completions only."))


def preservation_decisions(sets, missing=()):
    out = {}
    comparisons = {
        "accepted": ("PGM_ACCEPTED", ["BASE_ACCEPTED"]),
        "automatic": ("PGM_AUTOMATIC", ["BASE_ACCEPTED", "BASE_EXPERIMENTAL"]),
    }
    for policy, (candidate, baselines) in comparisons.items():
        if candidate not in sets or any(base not in sets for base in baselines): continue
        baseline_set = set().union(*(set(sets[base]) for base in baselines))
        candidate_set = set(sets[candidate]); losses = sorted(baseline_set - candidate_set)
        out[policy] = dict(decision="INCOMPLETE" if missing else "FAIL" if losses else "PASS",
                           baseline_count=len(baseline_set), candidate_count=len(candidate_set),
                           baseline_arms=baselines, losses=losses, gains=sorted(candidate_set - baseline_set))
    return out


def interval_conflicts(published):
    grouped = defaultdict(list)
    for (task, arm, rep), rows in published.items():
        for coordinate, row in rows.items():
            grouped[task, coordinate].append(dict(arm=arm, replicate=rep,
                lo=row["lo"], hi=row["hi"], label=row["label"]))
    deterministic, pac = [], []
    for (task, coordinate), entries in sorted(grouped.items()):
        det = [e for e in entries if not e["label"].startswith("PAC")]
        if det and max(F(e["lo"]) for e in det) > min(F(e["hi"]) for e in det):
            deterministic.append(dict(task=task, coordinate=coordinate, entries=det))
        if any(e["label"].startswith("PAC") for e in entries) and max(F(e["lo"]) for e in entries) > min(F(e["hi"]) for e in entries):
            pac.append(dict(task=task, coordinate=coordinate, entries=entries))
    return deterministic, pac


def _source_path(frozen, original, relative=None):
    """Resolve recorded source locations under this checkout without rewriting evidence.

    Relative paths must stay inside the restored repository. Original absolute
    paths remain a fallback when no restored counterpart exists. Callers retain
    the frozen SHA256 checks; resolving a filename never authenticates its bytes.
    """
    original = Path(original)
    if relative is None and not original.is_absolute():
        relative = original
    if relative is None:
        old_root = (frozen.get("roots", {}).get("candidate", {}) or {}).get("path")
        if old_root:
            try:
                relative = original.relative_to(Path(old_root))
            except ValueError:
                pass
    if relative is None:
        return original
    relative = Path(relative)
    restored_root = h.REPO.resolve()
    relocated = (restored_root / relative).resolve()
    if relative.is_absolute() or not relocated.is_relative_to(restored_root):
        raise ValueError("Frozen source path escapes the restored repository")
    return relocated if relocated.is_file() or not original.is_file() else original


def _relocate_task(task, frozen=None):
    task = dict(task)
    for key in ("model", "evidence"):
        task[key] = str(_source_path(frozen or {}, task[key], task.get(key + "_relative")))
    return task


def _historical(frozen, sets, issues):
    ref = frozen.get("historical_reference")
    if not ref:
        return dict(status="NOT_EVALUABLE", reason="No hash-bound historical reference in freeze")
    path = _source_path(frozen, ref["path"])
    if not path.is_file() or h.sha(path) != ref["sha256"]:
        issues.append("Historical reference missing or changed")
        return dict(status="INVALID_REFERENCE")
    old = json.loads(path.read_text())["complete_both"]
    result = dict(status="RECORDED_SEPARATELY", source_sha256=ref["sha256"],
                  interpretation="Historical completion targets on another host; this is not the same-host regression gate.", policies={})
    for policy in ("ACCEPTED", "EXPERIMENTAL"):
        prior = set(old["PGM_" + policy]); current = set(sets.get("PGM_ACCEPTED" if policy == "ACCEPTED" else "PGM_AUTOMATIC", []))
        baseline = set(sets.get("BASE_" + policy, []))
        result["policies"][policy.lower()] = dict(previous_count=len(prior), previous=sorted(prior),
            retained=sorted(prior & current), lost=sorted(prior - current),
            baseline_retained=sorted(prior & baseline), baseline_lost=sorted(prior - baseline),
            gained=sorted(current - prior))
    return result


def analyze(root):
    root = Path(root)
    frozen = json.loads((root / "FREEZE.json").read_text())
    tasks = {t["name"]: _relocate_task(t, frozen) for t in frozen["tasks"]}
    arms = frozen["arms"]; reps = frozen["replicates"]
    expected = {(name, arm, rep) for name in tasks for arm in arms for rep in reps}
    rows = [json.loads(p.read_text()) for p in sorted((root / "runs").glob("*/cell.json"))]
    keys = [(r["task"], r["arm"], r["replicate"]) for r in rows]
    issues = []
    if len(set(keys)) != len(keys): issues.append("Duplicate scored cell keys")
    if len({r["job"] for r in rows}) != len(rows): issues.append("Duplicate cell jobs")
    missing = sorted(expected - set(keys)); extra = sorted(set(keys) - expected)
    if extra: issues.append("Unexpected scored cell keys")
    terminal = h.receipts(root / "RECEIPTS.jsonl")
    byreceipt = defaultdict(list)
    for r in terminal: byreceipt[r["job"]].append(r)
    extra_receipts = sorted(set(byreceipt) - {r["job"] for r in rows})
    if extra_receipts: issues.append("Terminal receipts without a scored cell")
    published = {}; points = {}; raw_results = {}; faults = []
    coordinates = 0
    for row in rows:
        key = (row["task"], row["arm"], row["replicate"])
        if key not in expected:
            row["complete_within_contract"] = False
            continue
        task = tasks[row["task"]]; folder = root / "runs" / row["job"]
        receipts = byreceipt.get(row["job"], [])
        receipt = receipts[0] if len(receipts) == 1 else {}
        if len(receipts) != 1: issues.append("Expected exactly one terminal receipt: " + row["job"])
        if "receipt_jid" in row and row["receipt_jid"] != receipt.get("jid"):
            issues.append("Cell/receipt incarnation disagreement: " + row["job"])
        for relative, digest in (row.get("artifact_sha256") or {}).items():
            artifact = (folder / relative).resolve()
            if not artifact.is_relative_to(folder.resolve()) or not artifact.is_file() or h.sha(artifact) != digest:
                issues.append("Recorded cell artifact changed: %s %s" % (row["job"], relative))
        for rk, ck in (("wall_s", "wall_s"), ("outcome", "receipt_outcome"), ("returncode", "returncode"), ("peak_tree_rss_bytes", "peak_rss_bytes")):
            if row.get(ck) != receipt.get(rk): issues.append("Cell/receipt disagreement: %s %s" % (row["job"], ck))
        if row.get("identity_ok") is not True: issues.append("Cell source identity failed: " + row["job"])
        if (receipt.get("cleanup_unresolved") is not False or receipt.get("group_empty_at_receipt") is not True
                or receipt.get("nested_groups_live_at_receipt") != 0):
            issues.append("Unresolved or unspecified cleanup: " + row["job"])
        try:
            input_ok = all(h.sha(task[k]) == task[k + "_sha256"] == row.get(k + "_sha256") for k in ("model", "evidence"))
        except OSError:
            input_ok = False
        if not input_ok: issues.append("Input binding failed: " + row["job"])
        output = folder / ("result.json" if row["arm"] in PUBLIC_ARMS else "output.MAR")
        checked = dict(output_valid=False, contract_valid=False, all_queries_returned=False)
        if output.exists():
            try:
                checked = h.check_pgm(output, task, frozen["contracts"].get(row["arm"]), frozen["budget_s"]) if row["arm"] in PUBLIC_ARMS else h.check_libdai(folder, task)
                if not checked["output_valid"] or not checked["contract_valid"]:
                    faults.append(dict(job=row["job"], validation_faults=checked.get("validation_faults"), contract_faults=checked.get("contract_faults")))
                if row["arm"] in PUBLIC_ARMS:
                    raw_results[key] = json.loads(output.read_text())
                    published[key] = checked["published_rows"]
                    coordinates += checked["published"]
                elif checked["output_valid"]:
                    points[key] = h.read_mar(output, task)
                for field in ("output_valid", "contract_valid", "all_queries_returned"):
                    if row.get(field) != checked.get(field): issues.append("Recomputed artifact differs: %s %s" % (row["job"], field))
            except Exception as exc:
                faults.append(dict(job=row["job"], error=repr(exc)))
        elif receipt.get("outcome") == "COMPLETED" and receipt.get("returncode") == 0:
            issues.append("Successful child has no output: " + row["job"])
        complete = bool(input_ok and row.get("identity_ok") is True and checked.get("output_valid")
                        and checked.get("contract_valid") and checked.get("all_queries_returned")
                        and len(receipts) == 1 and receipt.get("outcome") == "COMPLETED" and receipt.get("returncode") == 0
                        and 0 < receipt.get("wall_s", float("inf")) <= frozen["budget_s"] and receipt.get("cleanup_unresolved") is False
                        and receipt.get("group_empty_at_receipt") is True and receipt.get("nested_groups_live_at_receipt") == 0)
        if complete != row.get("complete_within_contract"):
            issues.append("Recomputed completion differs: " + row["job"])
        row["complete_within_contract"] = complete
        row["converged_within_contract"] = complete and (row["arm"] != "LIBDAI_BP" or checked.get("converged") is True)
    bykey = {(r["task"], r["arm"], r["replicate"]): r for r in rows}
    jt_comparisons = []; bp_errors = []
    for key, pub in published.items():
        name, arm, rep = key
        jtkey = next(((name, "LIBDAI_JT", r) for r in [rep] + [r for r in reps if r != rep]
                      if bykey.get((name, "LIBDAI_JT", r), {}).get("complete_within_contract")), None)
        if jtkey is None: continue
        jt = points.get(jtkey, {}); outside = 0; maximum = F(0); compared = 0
        for coordinate, row in pub.items():
            coord = tuple(map(int, coordinate.split(":")))
            if coord not in jt: continue
            point = F(str(jt[coord])); distance = max(F(row["lo"]) - point, point - F(row["hi"]), F(0))
            maximum = max(maximum, distance); outside += distance > ALLOWANCE; compared += 1
        jt_comparisons.append(dict(task=name, arm=arm, replicate=rep, coordinates=compared,
                                   outside_after_allowance=outside, max_distance=float(maximum)))
        if outside: issues.append("Published interval excludes JT point: %s %s r%s" % key)
    for (name, arm, rep), bp in points.items():
        if arm != "LIBDAI_BP" or not bykey.get((name, arm, rep), {}).get("complete_within_contract"): continue
        jt = points.get((name, "LIBDAI_JT", rep))
        if not jt or not bykey.get((name, "LIBDAI_JT", rep), {}).get("complete_within_contract"): continue
        distances = [abs(v - jt[k]) for k, v in bp.items() if k in jt]
        bp_errors.append(dict(task=name, replicate=rep, max_absolute_error=max(distances, default=0),
                              converged=bykey[name, arm, rep].get("converged_within_contract")))
    det, pac = interval_conflicts(published)
    if det: issues.append("Deterministic interval conflicts")
    if faults: issues.append("Raw artifact or contract faults")
    sets = complete_sets(rows, tasks, arms, reps)
    pairs = {name: compare_pair(rows, tasks, reps, *arms_) for name, arms_ in PAIRS.items() if all(a in arms for a in arms_)}
    preservation = preservation_decisions(sets, missing)
    historical = _historical(frozen, sets, issues)
    route_counts = {}; dispatch_counts = {}; phases = {}; outcomes = {}; scaling = {}; families = {}
    for arm in arms:
        armrows = [r for r in rows if r["arm"] == arm]
        outcomes[arm] = dict(Counter(r.get("solver_outcome") or r.get("receipt_outcome", "UNKNOWN") for r in armrows))
        counts = Counter(); dispatches = Counter(); timings = defaultdict(list)
        for key, raw in raw_results.items():
            if key[1] != arm: continue
            for attempt in raw.get("attempts", []):
                counts[(attempt.get("backend", "unknown"), attempt.get("outcome", "unknown"))] += 1
            for choice in raw.get("dispatch", []):
                dispatches[(choice.get("backend", "unknown"), choice.get("reason", "unknown"),
                            choice.get("structural_route", "auto"), bool(choice.get("attempted")))] += 1
            metrics = dict(raw.get("phase_timings") or raw.get("phase_times_s") or raw.get("timing") or raw.get("timings") or {})
            metrics.setdefault("inspection_s", (raw.get("planning") or {}).get("inspection_s", (raw.get("planning") or {}).get("seconds")))
            metrics.setdefault("controller_s", raw.get("wall_s"))
            attempts = raw.get("attempts") or []
            metrics.setdefault("attempts_s", sum(a.get("wall_s", 0) or 0 for a in attempts))
            workers = [a.get("worker_wall_s") for a in attempts]
            if workers and all(isinstance(x, (int, float)) for x in workers): metrics.setdefault("workers_s", sum(workers))
            for field in ("source_parse_s", "adapter_s", "normalization_s"):
                values = [(a.get("worker_timings") or {}).get(field) for a in attempts]
                if values and all(isinstance(value, (int, float)) for value in values):
                    metrics["workers_" + field] = sum(values)
            for name, value in metrics.items():
                if isinstance(value, (int, float)): timings[name].append(value)
        route_counts[arm] = [dict(backend=k[0], outcome=k[1], cells=v) for k, v in sorted(counts.items())]
        dispatch_counts[arm] = [dict(backend=k[0], reason=k[1], structural_route=k[2], attempted=k[3], choices=v)
                                for k, v in sorted(dispatches.items())]
        phases[arm] = {k: dict(count=len(v), median_s=median(v), total_s=sum(v)) for k, v in sorted(timings.items())}
    for name, pair in pairs.items():
        groups = defaultdict(list)
        family_groups = defaultdict(list)
        for row in pair["per_task"]:
            task = tasks[row["task"]]
            n = (task.get("structure") or {}).get("variables")
            if n is None:
                try: n = len(h.metadata(task)[0])
                except (OSError, ValueError, StopIteration): pass
            size = "unknown" if n is None else "1-100" if n <= 100 else "101-1000" if n <= 1000 else "1001+"
            groups[size].append(row["ratio_of_medians"])
            family_groups[task.get("family") or "unclassified"].append(row["ratio_of_medians"])
        scaling[name] = {k: dict(mutual_tasks=len(v), median_wall_ratio=median(v)) for k, v in sorted(groups.items())}
        families[name] = {k: dict(mutual_tasks=len(v), median_wall_ratio=median(v)) for k, v in sorted(family_groups.items())}
    charge = sum(r["wall_s"] for r in terminal)
    if charge > frozen["scored_ceiling_s"]: issues.append("Scored ceiling exceeded")
    full = not missing and not extra and len(rows) == len(expected) and len(terminal) == len(expected)
    result = dict(schema="UNTUNED_RUNTIME_ANALYSIS_V1", freeze_sha256=h.sha(root / "FREEZE.json"),
                  expected_cells=len(expected), recorded_cells=len(rows), terminal_receipts=len(terminal),
                  missing_cells=missing, extra_cells=extra, extra_receipts=extra_receipts,
                  validation_issues=sorted(set(issues)), artifact_faults=faults,
                  validity="FAIL" if issues else "PASS" if full else "INCOMPLETE", completeness="PASS" if full else "INCOMPLETE",
                  charge_s=charge, scored_ceiling_s=frozen["scored_ceiling_s"], complete_both=sets,
                  one_replicate_only={a: sorted(t for t in tasks if sum(bykey.get((t, a, r), {}).get("complete_within_contract", False) for r in reps) == 1) for a in arms},
                  bp_converged_both=sorted(t for t in tasks if all(bykey.get((t, "LIBDAI_BP", r), {}).get("converged_within_contract") for r in reps)),
                  same_host_preservation=preservation, historical_reference=historical, pairs=pairs,
                  geometry=dict(published_coordinate_instances=coordinates, jt_coordinate_comparisons=sum(r["coordinates"] for r in jt_comparisons), jt_outside=sum(r["outside_after_allowance"] for r in jt_comparisons)),
                  jt_agreement=jt_comparisons, deterministic_conflicts=det, pac_conflicts=pac, bp_vs_jt=bp_errors,
                  outcome_counts=outcomes, attempt_counts=route_counts, dispatch_counts=dispatch_counts, phase_timing=phases,
                  scaling_by_variable_count=scaling, comparisons_by_family=families, jt_serialization_allowance=str(ALLOWANCE),
                  limitations=["All 61 tasks are exposed regression inputs; none is an unseen evaluation.",
                               "JT agreement is numerical agreement with a 5e-10 serialization allowance, not an independent proof of every large marginal.",
                               "BP output and convergence do not certify epsilon accuracy.",
                               "Timeouts and missing outputs are censored; no speed ratio uses a failed task.",
                               "Size-group comparisons are descriptive on mutual completions, not a scaling theorem.",
                               "Phase timings are diagnostic and not necessarily disjoint; end-to-end supervised wall is authoritative."])
    return frozen, rows, result


def write_report(root, result):
    root = Path(root)
    (root / "ANALYSIS.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    fields = ["pair", "candidate", "comparator", "task", "ratio_of_medians", "speedup_of_medians", "faster_every_repeat", "slower_every_repeat", "cost_flag"]
    with (root / "PAIRS.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for name, pair in result["pairs"].items():
            for row in pair["per_task"]:
                writer.writerow({k: dict(pair=name, candidate=pair["candidate"], comparator=pair["comparator"], **row).get(k) for k in fields})
    lines = ["# Untuned runtime performance — exposed external regression", "",
             f"Validity: **{result['validity']}**. Completeness: **{result['completeness']}**. "
             f"{result['recorded_cells']}/{result['expected_cells']} cells; {result['charge_s']:.3f} supervised seconds.", "",
             "| Arm | Both-repeat completions | One-repeat only |", "|---|---:|---:|"]
    for arm, tasks in result["complete_both"].items(): lines.append(f"| {arm} | {len(tasks)} | {len(result['one_replicate_only'][arm])} |")
    lines += ["", "Same-host preservation:", ""]
    for policy, d in result["same_host_preservation"].items():
        lines.append(f"- {policy}: **{d['decision']}**, baseline {d['baseline_count']}, candidate {d['candidate_count']}; losses {d['losses']}; gains {d['gains']}.")
    lines += ["", "| Comparison | Mutual tasks | Median candidate/comparator wall | Faster in both repeats | Slower in both repeats | Confirmed cost flags |",
              "|---|---:|---:|---:|---:|---:|"]
    for name, p in result["pairs"].items():
        ratio = "—" if p["median_wall_ratio"] is None else f"{p['median_wall_ratio']:.3f}"
        lines.append(f"| {name} | {len(p['mutual_both'])} | {ratio} | {p['faster_every_repeat']} | {p['slower_every_repeat']} | {len(p['cost_flags'])} |")
    lines += ["", "Historical completion targets (separate host):", ""]
    for policy, d in result["historical_reference"].get("policies", {}).items():
        lines.append(f"- {policy}: retained {len(d['retained'])}/{d['previous_count']}; candidate losses {d['lost']}; same-host baseline historical losses {d['baseline_lost']}.")
    lines += ["", f"Published coordinate instances: {result['geometry']['published_coordinate_instances']}; JT comparisons: {result['geometry']['jt_coordinate_comparisons']}; exclusions after allowance: {result['geometry']['jt_outside']}; deterministic conflicts: {len(result['deterministic_conflicts'])}.", "", "Limitations:", ""]
    lines += ["- " + text for text in result["limitations"]]
    if result["validation_issues"]:
        lines += ["", "Validation issues:", ""] + ["- " + text for text in result["validation_issues"]]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    _, _, result = analyze(args.run_dir); write_report(args.run_dir, result)
    print(json.dumps({k: result[k] for k in ("validity", "completeness", "recorded_cells", "charge_s", "same_host_preservation")}))
    return 0 if result["validity"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
