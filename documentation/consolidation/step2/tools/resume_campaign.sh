#!/bin/sh
# OPERATOR resume guard for the frozen campaign (not part of the frozen harness; it changes no harness file).
# Waits until no campaign driver / phase process is alive, moves aside any run folder that has NO terminal receipt (an
# interrupted in-flight cell is preserved as <job>.interrupted.<utc>, never silently deleted), then resumes the frozen phases
# serially (resumable by design: cells with a receipt are skipped) and analyses.  Every action is logged.
# usage: resume_campaign.sh <venv python> <libdai_mar> <ref 7f28259> <ref 3283cfd> <run dir> [CC] [CXX]
set -u
export PGM_BENCH_PY="$1" PGM_LIBDAI="$2" PGM_BENCH_REFERENCE_ROOT="$3" PGM_BENCH_EXPERIMENTAL_REF_ROOT="$4" PGM_BENCH_RUN_DIR="$5"
export CC="${6:-/usr/bin/clang}" CXX="${7:-/usr/bin/clang++}"
unset PYTHONPATH PGM_NATIVE_CACHE
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"; cd "$REPO" || exit 2
LOG="$PGM_BENCH_RUN_DIR/CAMPAIGN_OPERATOR.log"
echo "resume guard started $(date -u +%Y-%m-%dT%H:%M:%SZ) pid $$" >> "$LOG"
while pgrep -f "run_campaign.sh" > /dev/null || pgrep -f "run_suite.py (primary|eval)" > /dev/null || pgrep -f "analyze_suite.py" > /dev/null; do sleep 10; done
echo "driver gone $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
"$PGM_BENCH_PY" - "$PGM_BENCH_RUN_DIR" >> "$LOG" 2>&1 <<'PYEOF'
import json, os, sys, time
from pathlib import Path
R = Path(sys.argv[1]); receipts = {json.loads(l)["job"] for l in (R / "RECEIPTS.jsonl").read_text().splitlines() if l.strip() and json.loads(l).get("kind") == "RECEIPT"} if (R / "RECEIPTS.jsonl").exists() else set()
for d in sorted((R / "runs").glob("*")):
    if d.is_dir() and ".interrupted." not in d.name and d.name not in receipts:
        target = d.with_name(d.name + ".interrupted." + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
        d.rename(target); print("OPERATOR: preserved receipt-less interrupted cell folder", d.name, "->", target.name)
print("resume check done; receipts:", len(receipts))
PYEOF
step() { name="$1"; shift; echo "## $name $(date -u +%Y-%m-%dT%H:%M:%SZ): $*" >> "$LOG"; "$@" >> "$PGM_BENCH_RUN_DIR/$name.log" 2>&1; rc=$?; echo "exit $rc $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"; }
step 2_primary "$PGM_BENCH_PY" benchmarks/external/run_suite.py primary
step 3_eval "$PGM_BENCH_PY" benchmarks/external/run_suite.py eval
step 4_analyze "$PGM_BENCH_PY" benchmarks/external/analyze_suite.py
echo "resume guard finished $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
