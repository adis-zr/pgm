#!/usr/bin/env python3
"""Replay a frozen external campaign from a relocated checkout, without inference.

The archived freeze, raw outputs, receipts and expected reports are read-only.
Exit 0: replay matches and campaign validity PASS. Exit 1: replay matches and
campaign validity is FAIL/INCOMPLETE (the original negative verdict is retained).
Exit 2: replay/provenance mismatch. See REPLAY_RECEIPT.json for the distinction.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-checkout", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-dir", type=Path, help="Default: RUN_DIR/frozen_analysis when present, else RUN_DIR")
    args = parser.parse_args(argv)
    code = args.code_checkout.expanduser().resolve()
    run = args.run_dir.expanduser().resolve()
    output = args.output_dir.expanduser().resolve()
    expected = (args.expected_dir or (run / "frozen_analysis" if (run / "frozen_analysis").is_dir() else run)).expanduser().resolve()
    if output.is_relative_to(run) or output.is_relative_to(code):
        parser.error("Use a new output directory outside the archived run and source checkout")
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory must be empty; no prior replay is overwritten")
    output.mkdir(parents=True, exist_ok=True)
    receipt = dict(replay_ok=False, code_checkout=str(code), run_dir=str(run), expected_dir=str(expected), output_dir=str(output))
    try:
        frozen = json.loads((run / "FREEZE.json").read_text())
        old_roots = [Path(root["path"]).resolve() for root in frozen["roots"].values()]
        if any(code.is_relative_to(root) for root in old_roots):
            raise ValueError("Use a genuinely relocated checkout for this test")
        if any(run.is_relative_to(root) for root in old_roots):
            raise ValueError("The archived run must be outside the old source roots")
        report_names = ("ANALYSIS.json", "PAIRS.csv", "REPORT.md")
        protected = {str(run / name): sha(run / name) for name in ("FREEZE.json", "RECEIPTS.jsonl")}
        protected.update({str(expected / name): sha(expected / name) for name in report_names})
        scripts = code / "benchmarks/external"
        if sha(scripts / "run_suite.py") != frozen["harness_files"]["run_suite.py"]:
            raise ValueError("Restored result-reader bytes differ from the frozen reader")
        receipt["sources"] = {name: sha(scripts / name) for name in ("run_suite.py", "analyze_performance.py")}
        receipt["replay_script_sha256"] = sha(__file__)
        receipt["freeze_sha256"] = protected[str(run / "FREEZE.json")]
        blocked = []
        def deny_creator_source_reads(event, arguments):
            if event != "open" or not arguments:
                return
            path = arguments[0]
            if isinstance(path, (str, bytes, os.PathLike)):
                resolved = Path(os.fsdecode(path)).resolve()
                if any(resolved.is_relative_to(root) for root in old_roots):
                    blocked.append(str(resolved))
                    raise PermissionError("Creator source checkout is unavailable during replay: " + str(resolved))
        sys.addaudithook(deny_creator_source_reads)
        # Do not accidentally reuse an analyzer imported from the creator's root.
        for name in ("analyze_performance", "run_suite"):
            sys.modules.pop(name, None)
        sys.path.insert(0, str(scripts))
        os.chdir(output)
        analyzer = importlib.import_module("analyze_performance")
        if analyzer.h.REPO.resolve() != code:
            raise ValueError("Analyzer reader is bound to another checkout")
        if not hasattr(analyzer, "_source_path"):
            raise ValueError("Use the final analysis-portability commit, which supplies the checked source resolver")
        bindings = []
        for task in frozen["tasks"]:
            resolved = analyzer._relocate_task(task, frozen)
            for key in ("model", "evidence"):
                path = Path(resolved[key]).resolve()
                if not path.is_relative_to(code) or sha(path) != task[key + "_sha256"]:
                    raise ValueError("Relocated input binding failed: " + task["name"] + " " + key)
                bindings.append(dict(task=task["name"], field=key, path=str(path.relative_to(code)), sha256=task[key + "_sha256"]))
        reference = frozen["historical_reference"]
        historical = analyzer._source_path(frozen, reference["path"]).resolve()
        if not historical.is_relative_to(code) or sha(historical) != reference["sha256"]:
            raise ValueError("Relocated historical reference failed its original hash")
        receipt.update(relocated_input_files=len(bindings), input_bindings=bindings,
                       historical_reference=dict(path=str(historical.relative_to(code)), sha256=reference["sha256"]),
                       creator_roots_unavailable_for_reads=[str(root) for root in old_roots])
        _, rows, result = analyzer.analyze(run)
        analyzer.write_report(output, result)
        comparisons = {name: dict(expected_sha256=sha(expected / name), replay_sha256=sha(output / name),
                                  identical=(expected / name).read_bytes() == (output / name).read_bytes()) for name in report_names}
        unchanged = all(sha(path) == digest for path, digest in protected.items())
        receipt.update(report_comparison=comparisons, protected_evidence_unchanged=unchanged,
                       blocked_creator_read_attempts=blocked, recorded_cells=len(rows),
                       original_campaign_validity=result["validity"], original_campaign_completeness=result["completeness"],
                       analysis_exit_code=0 if result["validity"] == "PASS" else 1)
        receipt["replay_ok"] = bool(unchanged and not blocked and all(value["identical"] for value in comparisons.values())
                                  and len(bindings) == 2 * len(frozen["tasks"]))
        exit_code = receipt["analysis_exit_code"] if receipt["replay_ok"] else 2
    except Exception as error:
        receipt["error"] = repr(error)
        exit_code = 2
    (output / "REPLAY_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt.get(key) for key in ("replay_ok", "relocated_input_files", "recorded_cells", "original_campaign_validity", "original_campaign_completeness", "analysis_exit_code", "error")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
