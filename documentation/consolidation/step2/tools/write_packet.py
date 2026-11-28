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
                 "ANALYSIS.amendment2_rev1.json", "GATES.amendment2_rev1.json", "REPORT.amendment2_rev1.md", "PAIRS.amendment2_rev1.csv", "INCIDENTS.json",
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
    previous = json.loads((OUT / "RUN_ARCHIVE.json").read_text()) if (OUT / "RUN_ARCHIVE.json").exists() else {}
    if archive.exists() and previous.get("sha256") == sha(archive):
        # the ORIGINAL raw archive is never repackaged in place: its bytes and claimed hash stay; post-run records go to a SEPARATE archive
        members = previous["members"]; archive_sha = previous["sha256"]; archive_bytes = previous["bytes"]
        post = archive.with_name(archive.stem + "_POSTRUN_RECORDS.zip")
        with zipfile.ZipFile(post, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("INCIDENTS.json", "CAMPAIGN_OPERATOR.log", "ANALYSIS.json", "GATES.json", "REPORT.md", "PAIRS.csv", "ANALYSIS.amendment2_rev1.json", "GATES.amendment2_rev1.json", "REPORT.amendment2_rev1.md", "PAIRS.amendment2_rev1.csv"):
                if (run / name).exists(): z.write(run / name, Path(run.name) / name)
            for q in sorted((run / "natives").rglob("*")):
                if q.is_file(): z.write(q, q.relative_to(run.parent))
        postrun = dict(archive=str(post), sha256=sha(post), bytes=post.stat().st_size, members=len(zipfile.ZipFile(post).namelist()), note="records added to the original run directory AFTER its raw archive was taken (incident record, operator-log clarification, amendment-2 rev-1 and rev-2 analyzer outputs, executed native artifacts); the original archive is unchanged")
    else:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(run.rglob("*")):
                if p.is_file(): z.write(p, p.relative_to(run.parent))
        members = len(zipfile.ZipFile(archive).namelist()); archive_sha = sha(archive); archive_bytes = archive.stat().st_size; postrun = None
    ident = dict(archive=str(archive), sha256=archive_sha, bytes=archive_bytes, members=members, run_dir=str(run), copied=copied, written_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), postrun_records_archive=postrun, repository_copy="documentation/consolidation/step2/archive/" + archive.name)
    sup_dir = Path(os.environ.get("PGM_SUPPLEMENT_RUN_DIR", "")) if os.environ.get("PGM_SUPPLEMENT_RUN_DIR") else None
    if sup_dir and sup_dir.is_dir():
        sup_zip = archive.with_name("PGM_STEP2_SUPPLEMENT_RUN_" + sup_dir.name + ".zip")
        with zipfile.ZipFile(sup_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for q in sorted(sup_dir.rglob("*")):
                if q.is_file(): z.write(q, q.relative_to(sup_dir.parent))
            for extra in sorted(sup_dir.parent.glob(sup_dir.name + ".attempt*")):
                for q in sorted(extra.rglob("*")):
                    if q.is_file(): z.write(q, q.relative_to(sup_dir.parent))
        ident["supplement_archive"] = dict(archive=str(sup_zip), sha256=sha(sup_zip), bytes=sup_zip.stat().st_size, members=len(zipfile.ZipFile(sup_zip).namelist()), note="the complete raw supplement run directory (every cell, launch, log, receipt, setup) plus the refused first attempt directory")
    (OUT / "RUN_ARCHIVE.json").write_text(json.dumps(ident, indent=1) + "\n")
    f = json.loads((run / "FREEZE.json").read_text()); gates = json.loads((run / "GATES.json").read_text()) if (run / "GATES.json").exists() else {}
    an = json.loads((run / "ANALYSIS.json").read_text()) if (run / "ANALYSIS.json").exists() else {}
    g = an.get("groups", {}).get("all61", {}).get("complete_both", {})
    lines = ["# Step 2 external preservation regression -- START HERE", "",
             f"Branch `consolidate/production-layout`; frozen engine commit `{f['engine_commit']}`; FREEZE schema `{f['schema']}` ({f['amendment']}); pinned references `{f['old_reference_engine'][:7]}` (PGM_REFERENCE, accepted standalone engine) and `{f['roots']['PGM_EXPERIMENTAL_REF']['commit'][:7]}` (PGM_EXPERIMENTAL_REF, scored public implementation). Host `{f['platform']}`, `{f['compilers']['CC_version']}`.", "",
             "Read in this order: `REPAIRS.md` (before / after evidence for the step-1 review R1-R5 / B1-B7 AND the step-2 review's cleanup, incarnation and gate repairs), `../../../benchmarks/external/STEP2_AMENDMENT_1.md` (pre-run amendment), `STEP2_AMENDMENT_2.md` (post-run analysis amendment, rev 2), `STEP2_SUPPLEMENT_1.md` (the declared 245-cell confirmation of the changed runtime), `run/REPORT.md` and `run/GATES.json` (original run, rev-2 analysis; frozen and rev-1 outputs preserved beside them), `run/INCIDENTS.json` (the exact adjudicated incident), `run/ANALYSIS.json` / `run/PAIRS.csv` (every paired measurement), `run/FREEZE.json`, `run/setup/SETUP.json`, `supplement/` (the supplement's FREEZE / GATES / ANALYSIS / REPORT / compact cells), `RUN_ARCHIVE.json` (the UNCHANGED original raw archive by sha256, the separate post-run records archive and the supplement archive), `review2/` (the independent review's documents and probes).", "",
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
              f"Flagged tasks: {len(flags)} of {len(dec)} same-round mutual completions: {', '.join(x['task'] for x in flags) or 'none'}. Outside-worker time per request (controller wall minus worker wall: lexical inspection, supervised worker spawn, interpreter + package import, publication; the exact parse runs INSIDE the worker timer) = median {statistics.median(ov):.3f} s over the mutual completions (min {min(ov):.3f}, max {max(ov):.3f}). This is a timer decomposition, not an isolated kernel attribution: the outside-worker amount includes input-dependent inspection and serialization, and worker / standalone timers cover different boundaries." if ov else "No paired measurement.",
              "", "| task | reference receipt s | accepted receipt s | difference s | fixed overhead s | accepted worker s | reference internal s |", "|---|---:|---:|---:|---:|---:|---:|"]
    for d in sorted(dec, key=lambda d: -statistics.median(d["differences_s"])):
        if d["task"] in {x["task"] for x in flags} and d.get("common_contract_overhead_s"):
            lines.append(f"| {d['task']} | {statistics.median(d['receipt_walls']['comparator']):.3f} | {statistics.median(d['receipt_walls']['candidate']):.3f} | {statistics.median(d['differences_s']):.3f} | {statistics.median(d['common_contract_overhead_s']):.3f} | {statistics.median([x or 0 for x in d['candidate_worker_wall_s']]):.3f} | {statistics.median(d['comparator_internal_wall_s']):.3f} |")
    lines += ["", "Every paired wall, ratio and difference is in `run/PAIRS.csv` (pair `same_round_accepted`) and `run/ANALYSIS.json` (`overhead_decomposition`). The 18 flags are real end-to-end latency regressions under the adopted rule and remain reported; the decomposition supports wrapper overhead as a major contributor on the flagged (cheap) tasks, where the flagged-task MEDIAN worker-versus-reference-internal difference is small, but across all mutual tasks individual differences reach several tenths of a second (e.g. BN_12, BN_13, a DBN_14 repeat). No rate or scheduler was changed; reducing duplicated boundary work is the next performance task.", "",
              "## Amendments and incidents", "",
              "- `STEP2_AMENDMENT_1` (pre-run, committed): the six-arm matrix, executed pinned references, owner-resolved natives, contracts, explicit pairs, GATES, ceiling 14,640 s.",
              "- `STEP2_AMENDMENT_2` (post-run analysis only; `../../../benchmarks/external/STEP2_AMENDMENT_2.md`): the legacy internal-wall rule became a diagnostic (16 non-completing PGM_REFERENCE cells reclassified; frozen-analyzer outputs preserved as `run/*.frozen_analyzer_v1.*`), and the operator identity incident is recorded: during the run the operator edited a tracked documentation file, the harness identity guard aborted before cell 115, the in-flight comparator cell `DBN_11 LIBDAI_BP r1` carries `identity_ok = false`, the edit was reverted byte-for-byte and the run resumed under the same freeze (`run/CAMPAIGN_OPERATOR.log`). The frozen `validity` gate keeps that failure; `validity_excluding_operator_identity_incident` reports the same predicate with it set aside.",
              "", "## Limitations", "",
              "- Historical experimental preservation: the gate was NOT EVALUABLE at run time (extract absent; outputs preserved as `run/*.frozen_analyzer_v1.*` and `run/*.amendment2_rev1.*`); the independent review recovered the scored 3283cfd cells (`benchmarks/external/reference/HISTORICAL_3283CFD_122_CELLS.json`, source ANALYSIS sha 45d954bb..., bound by hash) and the current analysis computes it (see the gate table above). The seven current-host gains also occur in the pinned 3283cfd arm: they are host effects, not consolidation gains.",
              "- Same-host, same-round comparisons attribute differences to the implementation layer; they do not establish universal dominance, scaling or unseen generalization (all 61 inputs are exposed).",
              "- `main` is unchanged; promotion of the accepted default follows the `promotion_decision` gate and the review of this packet."]
    sup = Path(os.environ.get("PGM_SUPPLEMENT_RUN_DIR", "")) if os.environ.get("PGM_SUPPLEMENT_RUN_DIR") else None
    if sup and (sup / "GATES.json").exists():
        sg = json.loads((sup / "GATES.json").read_text()); sa = json.loads((sup / "ANALYSIS.json").read_text()); (OUT / "supplement").mkdir(exist_ok=True)
        for name in ("FREEZE.json", "RECEIPTS.jsonl", "ANALYSIS.json", "GATES.json", "REPORT.md", "SUPPLEMENT_RETURN.json", "BUDGET_STOP.json", "CAMPAIGN_COMMANDS.log"):
            if (sup / name).exists(): shutil.copy(sup / name, OUT / "supplement" / name)
        if (sup / "CELLS.jsonl").exists():
            with (OUT / "supplement" / "CELLS_COMPACT.jsonl").open("w") as out:
                for line in (sup / "CELLS.jsonl").read_text().splitlines():
                    if line.strip(): row = json.loads(line); row.pop("published_rows", None); out.write(json.dumps(row, default=str) + "\n")
        if (sup / "setup" / "SETUP.json").exists(): (OUT / "supplement" / "setup").mkdir(exist_ok=True); shutil.copy(sup / "setup" / "SETUP.json", OUT / "supplement" / "setup" / "SETUP.json")
        lines += ["", "## STEP2_SUPPLEMENT_1 (the changed public runtime on the full suite; original run immutable)", "", "| gate | decision |", "|---|---|",
                  f"| validity | {sg['validity']['decision']} |", f"| completeness | {sg['completeness']['decision']} ({sg['completeness']['recorded_cells']}/{sg['completeness']['expected_cells']}) |"] + \
                 [f"| preservation_vs_original {a} | {v['decision']} (target {v['target']}, supplement {v['supplement']}, lost {', '.join(v['lost']) or 'none'}, gained {', '.join(v['gained']) or 'none'}) |" for a, v in sg["preservation_vs_original"].items()] + \
                 [f"| replay_cells | {sg['replay_cells']['decision']} |", f"| supplement_decision | {sg['supplement_decision']['decision']} |", "", f"Charged {sa['charge_s']:.0f} s of the declared 4,900 s; records under `supplement/`. Wall times of different run periods are descriptive only."]
    (OUT / "START_HERE.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(archive=ident["archive"], sha256=ident["sha256"], members=members, postrun=(ident.get("postrun_records_archive") or {}).get("sha256"), supplement=(ident.get("supplement_archive") or {}).get("sha256"), gates={k: v["decision"] for k, v in gates.items()})))


if __name__ == "__main__": main()
