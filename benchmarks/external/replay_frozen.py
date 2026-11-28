#!/usr/bin/env python3
"""Replay the accepted performance packet using its frozen source, after layout changes.

No inference is run. The raw packet and archived reports remain read-only. A new
isolated git worktree is retained below OUTPUT/source for inspection. The old
round-2 replay helper checks every input, reference, and imported analyzer hash,
blocks reads from the creator's source roots, and compares all three reports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ("run_suite.py", "analyze_performance.py", "benchmark_validity.py")
HELPER = "documentation/performance/round2/portability/replay_analysis.py"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_commit(frozen):
    if frozen.get("schema") != "PGM_UNTUNED_PERFORMANCE_2":
        raise ValueError("This entry replays performance round 2; use the pinned historical entry for other protocols")
    commit = frozen["roots"]["candidate"]["commit"]
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Freeze must name a full candidate commit id")
    return commit


def verify_sources(checkout, frozen):
    actual = {}
    for name in MODULES:
        actual[name] = sha(checkout / "benchmarks/external" / name)
        if actual[name] != frozen["harness_files"][name]:
            raise ValueError("Frozen analyzer dependency mismatch: " + name)
    return actual


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--repository", default=ROOT, type=Path)
    parser.add_argument("--expected-dir", type=Path)
    args = parser.parse_args(argv)
    run = args.run_dir.resolve(); output = args.output_dir.resolve(); repo = args.repository.resolve()
    if output.exists() or output.is_relative_to(run) or output.is_relative_to(repo):
        parser.error("Use a new output directory outside the packet and repository")
    output.mkdir(parents=True)
    receipt = dict(replay_ok=False, run_dir=str(run), repository=str(repo))
    try:
        frozen = json.loads((run / "FREEZE.json").read_text())
        commit = source_commit(frozen)
        source = output / "source"
        # git resolves the commit itself; no branch name, remote access, or mutable
        # source tree is accepted as a substitute for the frozen identity.
        command = ["git", "-C", str(repo), "worktree", "add", "--detach", str(source), commit]
        created = subprocess.run(command, capture_output=True, text=True)
        (output / "RESTORE.log").write_text(created.stdout + created.stderr)
        if created.returncode:
            raise RuntimeError("Frozen commit unavailable; fetch the supplied history/bundle before replay")
        receipt.update(source_commit=commit, source=str(source), sources=verify_sources(source, frozen))
        helper = ROOT / HELPER
        receipt["helper_sha256"] = sha(helper)
        child = [sys.executable, str(helper), "--code-checkout", str(source), "--run-dir", str(run), "--output-dir", str(output / "analysis")]
        if args.expected_dir: child += ["--expected-dir", str(args.expected_dir.resolve())]
        result = subprocess.run(child, capture_output=True, text=True)
        (output / "REPLAY.log").write_text(result.stdout + result.stderr)
        receipt.update(command=child, replay_exit_code=result.returncode)
        replay = json.loads((output / "analysis/REPLAY_RECEIPT.json").read_text())
        receipt["replay_ok"] = replay.get("replay_ok") is True
        code = result.returncode if receipt["replay_ok"] else 2
    except Exception as error:
        receipt["error"] = repr(error)
        code = 2
    (output / "RESTORE_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"replay_ok": receipt["replay_ok"], "exit_code": code, "output": str(output), "error": receipt.get("error")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
