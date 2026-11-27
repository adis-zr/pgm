#!/usr/bin/env python3
"""Recompute completion / geometry / contract validity from the frozen raw artifacts and decide the GATES (STEP2_AMENDMENT_1).

Every comparison pair is EXPLICIT (FREEZE.pairs).  Validity re-runs the independent readers on every artifact, checks the
arm contracts, checks every published coordinate of every result arm against the libDAI JT point wherever a valid JT point
exists (partial outputs included), and checks deterministic interval compatibility across arms and repeats (PAC conflicts are
reported separately with their per-request interpretation).  GATES.json carries separate decisions: validity, completeness,
historical accepted preservation, same-round accepted preservation, historical experimental preservation (NOT EVALUABLE
without the hashed 3283cfd extract), same-round experimental preservation, paired overhead (cost flags).  Missing cells,
unresolved receipts or identity failures leave the campaign INCOMPLETE / INVALID rather than looking like a clean pass.
Usage: analyze_suite.py [RUN_DIR]  (default: the configured PGM_BENCH_RUN_DIR)
"""
from __future__ import annotations
import csv, json, statistics, sys
from fractions import Fraction as F
from pathlib import Path
import run_suite as h

ALLOW = 5e-10


def load_run(root):
    f = h.relocate_frozen_tasks(json.loads((root / "FREEZE.json").read_text()))
    rows = [json.loads(x) for x in (root / "CELLS.jsonl").read_text().splitlines() if x.strip()] if (root / "CELLS.jsonl").exists() else []
    return f, rows


def both(bykey, name, arm, reps, key="complete_within_contract"):
    return all(bykey.get((name, arm, r), {}).get(key, False) for r in reps)


def analyze(root):
    f, rows = load_run(root)
    tasks = {t["name"]: t for t in f["tasks"]}; arms = f["arms"]; reps = f["replicates"]; pairs = f["pairs"]
    expected = {(t["name"], a, r) for t in f["tasks"] for a in arms for r in reps}
    observed = [(r["task"], r["arm"], r["replicate"]) for r in rows]
    issues = []; identity_failures = []
    if len(set(observed)) != len(observed): issues.append("Duplicate scored cell keys")
    missing = sorted(expected - set(observed)); extra = sorted(set(observed) - expected)
    if extra: issues.append("Unexpected cell keys: %d" % len(extra))
    bykey = {key: r for key, r in zip(observed, rows)}
    receipt_index = {}
    for receipt in h.receipts(root / "RECEIPTS.jsonl"): receipt_index.setdefault(receipt["job"], []).append(receipt)
    geometry = dict(published_coordinate_instances=0, faulty_published_results=0, contract_faulty_results=0, max_endpoint_radius=0.0)
    checks = []; published_rows = {}; reclassified = []
    for r in rows:
        folder = root / "runs" / r["job"]; task = tasks[r["task"]]; owned = receipt_index.get(r["job"], [])
        if len(owned) != 1: issues.append("Expected exactly one terminal receipt: " + r["job"]); receipt = {}
        else:
            receipt = owned[0]
            for ck, rk in (("wall_s", "wall_s"), ("returncode", "returncode"), ("receipt_outcome", "outcome"), ("peak_rss_bytes", "peak_tree_rss_bytes")):
                if r.get(ck) != receipt.get(rk): issues.append("Cell/receipt disagreement: " + r["job"] + " " + ck)
        checked = dict(output_valid=False, contract_valid=False, all_queries_returned=False)
        output = folder / ("result.json" if h.is_pgm(r["arm"]) else "output.MAR")
        if output.exists():
            try:
                checked = h.check_pgm(output, task, f["contracts"].get(r["arm"]), f["budget_s"]) if h.is_pgm(r["arm"]) else h.check_libdai(folder, task)
                if h.is_pgm(r["arm"]):
                    geometry["published_coordinate_instances"] += checked["published"]; geometry["max_endpoint_radius"] = max(geometry["max_endpoint_radius"], checked["max_published_radius"])
                    if not checked["output_valid"]: geometry["faulty_published_results"] += 1; checks.append(dict(job=r["job"], faults=checked["validation_faults"]))
                    if not checked["contract_valid"]: geometry["contract_faulty_results"] += 1; checks.append(dict(job=r["job"], contract_faults=checked["contract_faults"]))
                    published_rows[(r["task"], r["arm"], r["replicate"])] = checked["published_rows"]
                for key in ("output_valid", "all_queries_returned", "contract_valid"):
                    if r.get(key) != checked.get(key):
                        # STEP2_AMENDMENT_2: a cell-time contract fault consisting ONLY of the superseded internal-wall rule on a non-publishing
                        # legacy cell is a documented reclassification, recorded rather than counted as a disagreement
                        if key == "contract_valid" and checked.get("contract_valid") and (r.get("contract_faults") == ["internal wall exceeds the allowance"]):
                            reclassified.append(r["job"]); r["contract_valid"] = True
                        else:
                            issues.append("Analysis disagrees with cell " + r["job"] + " " + key)
            except Exception as e:
                checks.append(dict(job=r["job"], error=repr(e)))
        input_ok = all(h.sha(task[k]) == task[k + "_sha256"] for k in ("model", "evidence"))
        if not input_ok: issues.append("Input changed " + r["job"])
        if not r.get("identity_ok", False):
            issues.append("Cell source identity failed " + r["job"]); identity_failures.append(r["job"])
        if receipt.get("cleanup_unresolved") is True: issues.append("Unresolved cleanup " + r["job"])
        completed = bool(input_ok and r.get("identity_ok", False) and checked.get("all_queries_returned") and checked.get("contract_valid", True) and receipt.get("outcome") == "COMPLETED" and receipt.get("wall_s", float("inf")) <= f["budget_s"] and receipt.get("cleanup_unresolved") is not True)
        if completed != r.get("complete_within_contract", False): issues.append("Recomputed completion disagrees with cell " + r["job"])
        r["complete_within_contract"] = completed; r["converged_within_contract"] = completed and (r["arm"] != "LIBDAI_BP" or checked.get("converged", False))
        r["published_now"] = checked.get("published"); r["label_now"] = checked.get("guarantee")
        if receipt: r["wall_s"] = receipt["wall_s"]; r["receipt_outcome"] = receipt["outcome"]
    # ---- JT containment for EVERY published coordinate of every result arm where a valid JT point exists (partial outputs included)
    jt_points = {}
    for t in f["tasks"]:
        for rep in reps:
            jt = bykey.get((t["name"], "LIBDAI_JT", rep), {})
            if jt.get("complete_within_contract"):
                try: jt_points[(t["name"], rep)] = h.read_mar(root / "runs" / jt["job"] / "output.MAR", t)
                except Exception as e: issues.append("JT output unreadable " + jt["job"] + " " + repr(e))
    jt_diag = []
    for (name, arm, rep), prow in published_rows.items():
        pts = jt_points.get((name, rep)) or jt_points.get((name, reps[0]))
        if not pts or not prow: continue
        outside = 0; maxd = 0.0
        for key, rr in prow.items():
            v, a = map(int, key.split(":")); x = pts.get((v, a))
            if x is None: continue
            lo, hi = float(F(rr["lo"])), float(F(rr["hi"])); d = max(lo - x, x - hi, 0.0); maxd = max(maxd, d); outside += d > ALLOW
        jt_diag.append(dict(task=name, arm=arm, replicate=rep, coordinates=len(prow), outside_after_serialization_allowance=outside, max_distance=maxd, partial=(bykey[(name, arm, rep)].get("published_now") != bykey[(name, arm, rep)].get("K"))))
        if outside: issues.append("Published enclosure excludes the JT point: %s %s r%d (%d coordinates)" % (name, arm, rep, outside))
    # ---- deterministic interval compatibility across result arms and repeats; PAC conflicts reported separately
    det_conflicts = []; pac_conflicts = []
    for name in tasks:
        per_coord = {}
        for (n, arm, rep), prow in published_rows.items():
            if n != name: continue
            for key, rr in prow.items(): per_coord.setdefault(key, []).append((arm, rep, F(rr["lo"]), F(rr["hi"]), rr["label"]))
        for key, entries in per_coord.items():
            det = [e for e in entries if not e[4].startswith("PAC")]
            if det:
                lo = max(e[2] for e in det); hi = min(e[3] for e in det)
                if lo > hi: det_conflicts.append(dict(task=name, coordinate=key, entries=[(e[0], e[1], str(e[2]), str(e[3]), e[4]) for e in det]))
            lo_all = max(e[2] for e in entries); hi_all = min(e[3] for e in entries)
            if lo_all > hi_all and any(e[4].startswith("PAC") for e in entries):
                pac_conflicts.append(dict(task=name, coordinate=key, entries=[(e[0], e[1], str(e[2]), str(e[3]), e[4]) for e in entries], interpretation="PAC enclosures hold with probability >= 1 - delta per request; a disjoint pair is evidence to investigate, not a certificate defect of either request"))
    if det_conflicts: issues.append("Deterministic interval conflicts: %d" % len(det_conflicts))
    # ---- completion sets per arm and group
    groups = {}
    result_arms = [a for a in arms if h.is_pgm(a)]
    for group in ("old55", "former_eval6", "all61"):
        tt = [t for t in f["tasks"] if group == "all61" or t.get("historical_group") == group]
        sets = {a: sorted(t["name"] for t in tt if both(bykey, t["name"], a, reps)) for a in arms}
        one_rep = {a: sorted(t["name"] for t in tt if sum(bykey.get((t["name"], a, r), {}).get("complete_within_contract", False) for r in reps) == 1) for a in arms}
        converged = {a: sorted(t["name"] for t in tt if both(bykey, t["name"], a, reps, "converged_within_contract")) for a in arms}
        groups[group] = dict(inputs=len(tt), complete_both=sets, one_replicate_only=one_rep, converged_both=converged)
    # ---- explicit pairs
    pair_results = {}
    for pname, (cand, comp) in pairs.items():
        A = set(groups["all61"]["complete_both"][cand]); B = set(groups["all61"]["complete_both"][comp])
        per_task = []
        for t in f["tasks"]:
            n = t["name"]; row = dict(task=n, group=t.get("historical_group"), candidate_both=n in A, comparator_both=n in B)
            if n in A and n in B:
                wa = [bykey[(n, cand, r)]["wall_s"] for r in reps]; wb = [bykey[(n, comp, r)]["wall_s"] for r in reps]
                row.update(candidate_walls=wa, comparator_walls=wb, candidate_median=statistics.median(wa), comparator_median=statistics.median(wb), ratio_median=statistics.median(wa) / statistics.median(wb),
                           ratios_per_repeat=[a / b for a, b in zip(wa, wb)], differences_per_repeat=[a - b for a, b in zip(wa, wb)])
            per_task.append(row)
        pair_results[pname] = dict(candidate=cand, comparator=comp, mutual_both=sorted(A & B), candidate_only=sorted(A - B), comparator_only=sorted(B - A), neither=sorted(set(tasks) - A - B),
                                   median_ratio_on_mutual=(statistics.median([r["ratio_median"] for r in per_task if "ratio_median" in r]) if (A & B) else None), per_task=per_task)
    # ---- cost flags (adopted criterion): same-round accepted pair only; with the overhead decomposition of every mutual completion
    cc = f.get("cost_criterion") or {}; flags = []; decomposition = []
    sr = pair_results.get("same_round_accepted")
    if sr:
        cand, comp = sr["candidate"], sr["comparator"]
        for row in sr["per_task"]:
            if "ratios_per_repeat" not in row: continue
            dec = dict(task=row["task"], group=row["group"], receipt_walls=dict(candidate=row["candidate_walls"], comparator=row["comparator_walls"]), ratios=row["ratios_per_repeat"], differences_s=row["differences_per_repeat"])
            try:
                acc = [json.loads((root / "runs" / bykey[(row["task"], cand, r)]["job"] / "result.json").read_text()) for r in reps]
                ref = [json.loads((root / "runs" / bykey[(row["task"], comp, r)]["job"] / "result.json").read_text()) for r in reps]
                dec.update(candidate_controller_wall_s=[a.get("wall_s") for a in acc], candidate_worker_wall_s=[((a.get("attempts") or [{}])[0].get("worker_wall_s")) for a in acc],
                           candidate_attempt_wall_s=[((a.get("attempts") or [{}])[0].get("wall_s")) for a in acc], candidate_inspection_s=[(a.get("planning") or {}).get("seconds") for a in acc],
                           comparator_internal_wall_s=[b.get("wall_s") for b in ref],
                           common_contract_overhead_s=[(a.get("wall_s") or 0) - (((a.get("attempts") or [{}])[0].get("worker_wall_s")) or 0) for a in acc])
            except Exception as e:
                dec["decomposition_error"] = repr(e)
            decomposition.append(dec)
            if all(x > 1.25 for x in row["ratios_per_repeat"]) and all(d > 0.1 for d in row["differences_per_repeat"]):
                flags.append(dict(task=row["task"], ratios=row["ratios_per_repeat"], differences_s=row["differences_per_repeat"], common_contract_overhead_s=dec.get("common_contract_overhead_s"), candidate_worker_wall_s=dec.get("candidate_worker_wall_s"), comparator_internal_wall_s=dec.get("comparator_internal_wall_s")))
    # ---- historical comparisons
    old = json.loads(h.REFERENCE.read_text())["cells"]
    prior29 = {r["task"] for r in old if r["arm"] == "PGM" and r["budget_s"] == 20 and all(any(s["task"] == r["task"] and s["arm"] == "PGM" and s["budget_s"] == 20 and s["replicate"] == rep and s["complete_within_contract"] for s in old) for rep in (1, 2))}
    hist = {}
    for arm in result_arms:
        new = set(groups["all61"]["complete_both"][arm])
        hist[arm] = dict(retained=sorted(prior29 & new), lost=sorted(prior29 - new), gained=sorted(new - prior29), one_repeat_only=groups["all61"]["one_replicate_only"][arm])
    # ---- gates
    recorded = len(rows); complete_matrix = (not missing and not extra and recorded == len(expected))
    budget_stop = (root / "BUDGET_STOP.json").exists()
    def gate(decision, **kw): return dict(decision=decision, **kw)
    def pair(name): return pair_results.get(name) or dict(comparator_only=None, candidate_only=None, mutual_both=[], median_ratio_on_mutual=None, per_task=[])
    def hist_of(arm): return hist.get(arm) or dict(retained=None, lost=None, gained=None, one_repeat_only=None)
    def pres(p): return "NOT_EVALUABLE" if p["comparator_only"] is None else ("PASS" if not p["comparator_only"] else "FAIL")
    gates = dict(
        validity=gate("PASS" if (not issues and not checks and geometry["faulty_published_results"] == 0 and geometry["contract_faulty_results"] == 0 and not det_conflicts) else "FAIL", issues=issues, artifact_faults=checks, deterministic_conflicts=len(det_conflicts), pac_conflicts=len(pac_conflicts)),
        completeness=gate("PASS" if complete_matrix and not budget_stop else "INCOMPLETE", expected_cells=len(expected), recorded_cells=recorded, missing_cells=len(missing), budget_stop=budget_stop),
        historical_accepted_preservation=gate(("NOT_EVALUABLE" if hist_of("PGM_ACCEPTED")["lost"] is None else "PASS" if not hist_of("PGM_ACCEPTED")["lost"] else "FAIL"), prior_complete_both=sorted(prior29), **hist_of("PGM_ACCEPTED")),
        reference_reproduction=gate(("NOT_EVALUABLE" if hist_of("PGM_REFERENCE")["lost"] is None else "PASS" if not hist_of("PGM_REFERENCE")["lost"] else "REFERENCE_REPRODUCTION_FAILURE"), note="the pinned 7f28259 engine executed here versus its own historical cells; a loss here is a host / timing / reproduction issue of the reference, not evidence against the new wrapper", **hist_of("PGM_REFERENCE")),
        same_round_accepted_preservation=gate(pres(pair("same_round_accepted")), lost_vs_reference=pair("same_round_accepted")["comparator_only"], gained_vs_reference=pair("same_round_accepted")["candidate_only"], mutual=len(pair("same_round_accepted")["mutual_both"])),
        historical_experimental_preservation=gate("NOT_EVALUABLE", prerequisite=(f.get("prior_experimental_extract") or {}).get("prerequisite"), note="requires the hashed extract of the 122 scored 3283cfd PGM cells; not present on this host; no target rows invented", historical_accepted29_view=hist_of("PGM_EXPERIMENTAL")),
        same_round_experimental_preservation=gate(pres(pair("same_round_experimental")), lost_vs_pinned_3283cfd=pair("same_round_experimental")["comparator_only"], gained_vs_pinned_3283cfd=pair("same_round_experimental")["candidate_only"], mutual=len(pair("same_round_experimental")["mutual_both"])),
        paired_overhead=gate("FLAGGED" if flags else "PASS", criterion=cc.get("rule"), flags=flags, effect=cc.get("effect"), median_ratio_accepted_over_reference=pair("same_round_accepted")["median_ratio_on_mutual"]),
    )
    gates["validity"]["amendment_2_reclassified_non_publishing_legacy_cells"] = reclassified
    gates["validity"]["identity_failures"] = identity_failures
    gates["validity_excluding_operator_identity_incident"] = gate("PASS" if (not [i for i in issues if not i.startswith("Cell source identity failed")] and not checks and geometry["faulty_published_results"] == 0 and geometry["contract_faulty_results"] == 0 and not det_conflicts) else "FAIL",
                                                                    note="the same validity predicate with the recorded operator identity incident (CAMPAIGN_OPERATOR.log) set aside; the frozen `validity` gate above keeps it; the reviewer decides")
    gates["promotion_decision"] = gate("HOLD" if not (gates["validity"]["decision"] == "PASS" and gates["completeness"]["decision"] == "PASS" and gates["historical_accepted_preservation"]["decision"] == "PASS" and gates["same_round_accepted_preservation"]["decision"] == "PASS" and not flags) else "ELIGIBLE",
                                       rule=(f.get("gates") or {}).get("promotion") if isinstance(f.get("gates"), dict) else None)
    charges = h.receipts(root / "RECEIPTS.jsonl")
    result = dict(schema="CONSOLIDATION_EXTERNAL_ANALYSIS_V3", engine_commit=f["engine_commit"], freeze_sha256=h.sha(root / "FREEZE.json"), expected_cells=len(expected), recorded_cells=recorded, missing_cells=missing,
                  validation_issues=issues, artifact_faults=checks, geometry=geometry, groups=groups, pairs=pair_results, historical_accepted29=hist, jt_agreement=jt_diag, deterministic_conflicts=det_conflicts, pac_conflicts=pac_conflicts,
                  cost_flags=flags, overhead_decomposition=decomposition, point_serialization_allowance=ALLOW, charge_s=sum(r["wall_s"] for r in charges), terminal_receipts=len(charges), gates=gates,
                  reported_certificates_are_not_exact_oracle_validation=True)
    return f, rows, result


def report(f, result):
    g = result["groups"]; arms = f["arms"]; gates = result["gates"]
    lines = ["# Step 2 external preservation regression (STEP2_AMENDMENT_1)", "",
             f"Engine `{f['engine_commit']}`; pinned references `{f['old_reference_engine'][:7]}` (PGM_REFERENCE) and `{f['roots']['PGM_EXPERIMENTAL_REF']['commit'][:7]}` (PGM_EXPERIMENTAL_REF). Recorded {result['recorded_cells']}/{result['expected_cells']} cells; charged {result['charge_s']:.1f} s / {f['scored_ceiling_s']} s.", "",
             "All 61 inputs are exposed regression inputs (old55 / former_eval6 are historical groups). One outer contract: 20 s, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6, two fresh-process repeats, serial execution.", "",
             "## Gates", "", "| gate | decision |", "|---|---|"] + [f"| {k} | {v['decision']} |" for k, v in gates.items()] + ["",
             "## Both-repeat completions", "", "| group | inputs | " + " | ".join(arms) + " |", "|---|---:|" + "---:|" * len(arms)]
    for name, gg in g.items(): lines.append(f"| {name} | {gg['inputs']} | " + " | ".join(str(len(gg["complete_both"][a])) for a in arms) + " |")
    lines += ["", "## Explicit pairs", ""]
    for pname, p in result["pairs"].items():
        lines.append(f"- **{pname}** ({p['candidate']} vs {p['comparator']}): mutual {len(p['mutual_both'])}; candidate-only {', '.join(p['candidate_only']) or 'none'}; comparator-only {', '.join(p['comparator_only']) or 'none'}; median wall ratio on mutual {p['median_ratio_on_mutual'] if p['median_ratio_on_mutual'] is None else round(p['median_ratio_on_mutual'], 3)}.")
    lines += ["", "## Historical accepted-engine completions (29 at 7f28259, 20 s)", ""]
    for arm, hh in result["historical_accepted29"].items(): lines.append(f"- {arm}: retained {len(hh['retained'])}/29; lost {', '.join(hh['lost']) or 'none'}; gained {', '.join(hh['gained']) or 'none'}; one-repeat-only {', '.join(hh['one_repeat_only']) or 'none'}.")
    lines += ["", "## Paired overhead (PGM_ACCEPTED / PGM_REFERENCE on same-round mutual completions)", "", "| task | group | accepted walls | reference walls | ratios | differences s |", "|---|---|---|---|---|---|"]
    for row in result["pairs"]["same_round_accepted"]["per_task"]:
        if "ratios_per_repeat" in row: lines.append(f"| {row['task']} | {row['group']} | {[round(x, 3) for x in row['candidate_walls']]} | {[round(x, 3) for x in row['comparator_walls']]} | {[round(x, 3) for x in row['ratios_per_repeat']]} | {[round(x, 3) for x in row['differences_per_repeat']]} |")
    lines += ["", f"Cost flags ({(f.get('cost_criterion') or {}).get('rule')}): {', '.join(x['task'] for x in result['cost_flags']) or 'none'}.", "",
              f"Independent checks: {len(result['validation_issues'])} identity / scoring issues; {len(result['artifact_faults'])} faulty artifacts; {result['geometry']['published_coordinate_instances']} published coordinate instances; max endpoint radius {result['geometry']['max_endpoint_radius']:.3e}; JT containment checked on {len(result['jt_agreement'])} (arm, task, repeat) outputs incl. partial ones with {sum(x['outside_after_serialization_allowance'] for x in result['jt_agreement'])} excluded coordinates; deterministic conflicts {len(result['deterministic_conflicts'])}; PAC conflicts {len(result['pac_conflicts'])}.", "",
              "Historical experimental preservation (the 47-task 3283cfd portfolio set) is NOT EVALUABLE without the hashed extract of the scored 3283cfd cells; the same-round pinned 3283cfd arm is the executed experimental comparator. This campaign measures preservation on exposed inputs; it establishes no universal dominance, scaling or unseen generalization claim."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    root = Path(argv[0]).resolve() if argv else h.ROOT
    f, rows, result = analyze(root)
    h.dump(root / "ANALYSIS.json", result); h.dump(root / "GATES.json", result["gates"])
    fields = sorted({k for p in result["pairs"].values() for r in p["per_task"] for k in r})
    with (root / "PAIRS.csv").open("w", newline="") as out:
        w = csv.DictWriter(out, fieldnames=["pair"] + fields); w.writeheader()
        for pname, p in result["pairs"].items():
            for r in p["per_task"]: w.writerow(dict(pair=pname, **{k: r.get(k) for k in fields}))
    (root / "REPORT.md").write_text(report(f, result))
    print(json.dumps(dict(recorded=result["recorded_cells"], expected=result["expected_cells"], gates={k: v["decision"] for k, v in result["gates"].items()}, charge_s=round(result["charge_s"], 1))))
    return 0 if result["gates"]["validity"]["decision"] == "PASS" and result["gates"]["completeness"]["decision"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
