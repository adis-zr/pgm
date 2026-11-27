"""Assemble the step-2 return packet from the frozen run directory: copy the authoritative records (FREEZE, CELLS, RECEIPTS,
ANALYSIS, GATES, PAIRS, REPORT, setup record + receipts, campaign logs, BUDGET_STOP if any) into documentation/consolidation/
step2/run/, archive the COMPLETE raw run directory (every cell's result / launch / logs / receipts) as a zip with its sha256,
and write START_HERE.md with the gate decisions.  usage: write_packet.py RUN_DIR ARCHIVE_PATH"""
import hashlib, json, os, shutil, sys, time, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]; OUT = REPO / "documentation/consolidation/step2"


def sha(p):
    with open(p, "rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    run = Path(sys.argv[1]).resolve(); archive = Path(sys.argv[2]).resolve(); dest = OUT / "run"; dest.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in ("FREEZE.json", "CELLS.jsonl", "RECEIPTS.jsonl", "ANALYSIS.json", "GATES.json", "PAIRS.csv", "REPORT.md", "ANALYSIS.frozen_analyzer_v1.json", "GATES.frozen_analyzer_v1.json", "REPORT.frozen_analyzer_v1.md", "PAIRS.frozen_analyzer_v1.csv",
                 "BUDGET_STOP.json", "PRIMARY_RETURN.json", "EVAL_RETURN.json", "CAMPAIGN_COMMANDS.log", "CAMPAIGN_OPERATOR.log", "ENGINE_COMMIT.txt", "GIT_STATUS_AT_START.txt", "0_setup.log", "1_freeze.log", "2_primary.log", "3_eval.log", "4_analyze.log", "resume2.sh", "resume_guard.out", "resume2.out"):
        if (run / name).exists(): shutil.copy(run / name, dest / name); copied[name] = sha(dest / name)
    # the full CELLS.jsonl (every published row of every cell, ~60 MB) stays in the raw archive; the repository copy is the compact per-cell record
    full = dest / "CELLS.jsonl"
    if full.exists():
        with (dest / "CELLS_COMPACT.jsonl").open("w") as out:
            for line in full.read_text().splitlines():
                if line.strip():
                    row = json.loads(line); row.pop("published_rows", None); out.write(json.dumps(row, default=str) + "\n")
        copied["CELLS_COMPACT.jsonl"] = sha(dest / "CELLS_COMPACT.jsonl"); copied["CELLS.jsonl"] = copied["CELLS.jsonl"] + " (full file only in the raw archive)"; full.unlink()
    (dest / "setup").mkdir(exist_ok=True)
    for name in ("SETUP.json", "SETUP_RECEIPTS.jsonl"):
        if (run / "setup" / name).exists(): shutil.copy(run / "setup" / name, dest / "setup" / name); copied["setup/" + name] = sha(dest / "setup" / name)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(run.rglob("*")):
            if p.is_file(): z.write(p, p.relative_to(run.parent))
    members = len(zipfile.ZipFile(archive).namelist())
    ident = dict(archive=str(archive), sha256=sha(archive), bytes=archive.stat().st_size, members=members, run_dir=str(run), copied=copied, written_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    (OUT / "RUN_ARCHIVE.json").write_text(json.dumps(ident, indent=1) + "\n")
    f = json.loads((run / "FREEZE.json").read_text()); gates = json.loads((run / "GATES.json").read_text()) if (run / "GATES.json").exists() else {}
    an = json.loads((run / "ANALYSIS.json").read_text()) if (run / "ANALYSIS.json").exists() else {}
    g = an.get("groups", {}).get("all61", {}).get("complete_both", {})
    lines = ["# Step 2 external preservation regression -- START HERE", "",
             f"Branch `consolidate/production-layout`; frozen engine commit `{f['engine_commit']}`; FREEZE schema `{f['schema']}` ({f['amendment']}); pinned references `{f['old_reference_engine'][:7]}` (PGM_REFERENCE, accepted standalone engine) and `{f['roots']['PGM_EXPERIMENTAL_REF']['commit'][:7]}` (PGM_EXPERIMENTAL_REF, scored public implementation). Host `{f['platform']}`, `{f['compilers']['CC_version']}`.", "",
             "Read in this order: `REPAIRS.md` (before / after evidence for R1-R5 and B1-B7), `../../../benchmarks/external/STEP2_AMENDMENT_1.md` (the committed pre-run amendment), `run/REPORT.md` and `run/GATES.json` (results), `run/ANALYSIS.json` / `run/PAIRS.csv` (every paired measurement), `run/FREEZE.json` (every identity: source files, active native artifacts per arm, pinned root closures, compilers, dependencies), `run/setup/SETUP.json` (builds, warm caches, the six-arm smoke), `RUN_ARCHIVE.json` (the complete raw run directory archive with its sha256).", "",
             "## Gates", "", "| gate | decision |", "|---|---|"] + [f"| {k} | {v['decision']} |" for k, v in gates.items()] + ["",
             f"Recorded {an.get('recorded_cells')}/{an.get('expected_cells')} cells; charged {an.get('charge_s', 0):.0f} s of the declared {f['scored_ceiling_s']} s ceiling; validation issues {len(an.get('validation_issues', []))}; artifact faults {len(an.get('artifact_faults', []))}; published coordinate instances {an.get('geometry', {}).get('published_coordinate_instances')}; deterministic conflicts {len(an.get('deterministic_conflicts', []))}; PAC conflicts {len(an.get('pac_conflicts', []))}; cost flags {len(an.get('cost_flags', []))}.", "",
             "## Both-repeat completions on all 61 exposed inputs", "", "| arm | completions |", "|---|---:|"] + [f"| {a} | {len(v)} |" for a, v in g.items()] + ["",
             "## Comparisons", ""]
    for pname, p in an.get("pairs", {}).items():
        lines.append(f"- **{pname}** ({p['candidate']} vs {p['comparator']}): mutual {len(p['mutual_both'])}; candidate-only {', '.join(p['candidate_only']) or 'none'}; comparator-only {', '.join(p['comparator_only']) or 'none'}; median wall ratio on mutual {p['median_ratio_on_mutual'] if p['median_ratio_on_mutual'] is None else round(p['median_ratio_on_mutual'], 3)}.")
    lines += ["", "## Historical accepted completions (29 at 7f28259)", ""]
    for arm, hh in an.get("historical_accepted29", {}).items(): lines.append(f"- {arm}: retained {len(hh['retained'])}/29; lost {', '.join(hh['lost']) or 'none'}; gained {', '.join(hh['gained']) or 'none'}; one-repeat-only {', '.join(hh['one_repeat_only']) or 'none'}.")
    flags = an.get("cost_flags", []); dec = an.get("overhead_decomposition", [])
    import statistics
    ov = [statistics.median(d["common_contract_overhead_s"]) for d in dec if d.get("common_contract_overhead_s")]
    lines += ["", "## Paired overhead (adopted criterion: both repeats > 1.25x and > 0.1 s slower than PGM_REFERENCE)", "",
              f"Flagged tasks: {len(flags)} of {len(dec)} same-round mutual completions: {', '.join(x['task'] for x in flags) or 'none'}. Median common-contract overhead per request (controller wall minus worker wall: lexical inspection, supervised worker spawn, interpreter + package import, exact parse) = {statistics.median(ov):.3f} s over the mutual completions (min {min(ov):.3f}, max {max(ov):.3f})." if ov else "No paired measurement.",
              "", "| task | reference receipt s | accepted receipt s | difference s | fixed overhead s | accepted worker s | reference internal s |", "|---|---:|---:|---:|---:|---:|---:|"]
    for d in sorted(dec, key=lambda d: -statistics.median(d["differences_s"])):
        if d["task"] in {x["task"] for x in flags} and d.get("common_contract_overhead_s"):
            lines.append(f"| {d['task']} | {statistics.median(d['receipt_walls']['comparator']):.3f} | {statistics.median(d['receipt_walls']['candidate']):.3f} | {statistics.median(d['differences_s']):.3f} | {statistics.median(d['common_contract_overhead_s']):.3f} | {statistics.median([x or 0 for x in d['candidate_worker_wall_s']]):.3f} | {statistics.median(d['comparator_internal_wall_s']):.3f} |")
    lines += ["", "Every paired wall, ratio and difference is in `run/PAIRS.csv` (pair `same_round_accepted`) and `run/ANALYSIS.json` (`overhead_decomposition`). The flags hold default promotion pending the reviewer's reading of this decomposition; no rate or scheduler was changed.", "",
              "## Amendments and incidents", "",
              "- `STEP2_AMENDMENT_1` (pre-run, committed): the six-arm matrix, executed pinned references, owner-resolved natives, contracts, explicit pairs, GATES, ceiling 14,640 s.",
              "- `STEP2_AMENDMENT_2` (post-run analysis only; `../../../benchmarks/external/STEP2_AMENDMENT_2.md`): the legacy internal-wall rule became a diagnostic (16 non-completing PGM_REFERENCE cells reclassified; frozen-analyzer outputs preserved as `run/*.frozen_analyzer_v1.*`), and the operator identity incident is recorded: during the run the operator edited a tracked documentation file, the harness identity guard aborted before cell 115, the in-flight comparator cell `DBN_11 LIBDAI_BP r1` carries `identity_ok = false`, the edit was reverted byte-for-byte and the run resumed under the same freeze (`run/CAMPAIGN_OPERATOR.log`). The frozen `validity` gate keeps that failure; `validity_excluding_operator_identity_incident` reports the same predicate with it set aside.",
              "", "## Limitations", "",
              "- The historical experimental preservation gate is NOT EVALUABLE: the scored 3283cfd cell extract is absent on this host (the exact prerequisite is named in `STEP2_PLAN.json`); the executed pinned 3283cfd arm is the same-round experimental comparator.",
              "- Same-host, same-round comparisons attribute differences to the implementation layer; they do not establish universal dominance, scaling or unseen generalization (all 61 inputs are exposed).",
              "- `main` is unchanged; promotion of the accepted default follows the `promotion_decision` gate and the review of this packet."]
    (OUT / "START_HERE.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(archive=ident["archive"], sha256=ident["sha256"], members=members, gates={k: v["decision"] for k, v in gates.items()})))


if __name__ == "__main__": main()
