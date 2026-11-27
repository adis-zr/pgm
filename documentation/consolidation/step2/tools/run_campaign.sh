#!/bin/sh
# The frozen step-2 campaign exactly as declared in STEP2_AMENDMENT_1: setup -> freeze -> primary (old55) -> eval (former_eval6)
# -> analyze, serially, under the strict supervisor.  Every command and its exit code is logged; nothing is changed between phases.
# usage: run_campaign.sh <venv python> <libdai_mar> <reference checkout 7f28259> <experimental-ref checkout 3283cfd> <run dir> [CC] [CXX]
set -u
export PGM_BENCH_PY="$1" PGM_LIBDAI="$2" PGM_BENCH_REFERENCE_ROOT="$3" PGM_BENCH_EXPERIMENTAL_REF_ROOT="$4" PGM_BENCH_RUN_DIR="$5"
export CC="${6:-/usr/bin/clang}" CXX="${7:-/usr/bin/clang++}"
unset PYTHONPATH PGM_NATIVE_CACHE
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"; cd "$REPO" || exit 2
mkdir -p "$PGM_BENCH_RUN_DIR"; LOG="$PGM_BENCH_RUN_DIR/CAMPAIGN_COMMANDS.log"
step() { name="$1"; shift; echo "## $name $(date -u +%Y-%m-%dT%H:%M:%SZ): $*" >> "$LOG"; "$@" > "$PGM_BENCH_RUN_DIR/$name.log" 2>&1; rc=$?; echo "exit $rc $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"; echo "$name exit $rc"; return $rc; }
git -C "$REPO" rev-parse HEAD > "$PGM_BENCH_RUN_DIR/ENGINE_COMMIT.txt"; git -C "$REPO" status --porcelain > "$PGM_BENCH_RUN_DIR/GIT_STATUS_AT_START.txt"
step 0_setup "$PGM_BENCH_PY" benchmarks/external/run_suite.py setup || exit 3
step 1_freeze "$PGM_BENCH_PY" benchmarks/external/run_suite.py freeze || exit 4
step 2_primary "$PGM_BENCH_PY" benchmarks/external/run_suite.py primary
step 3_eval "$PGM_BENCH_PY" benchmarks/external/run_suite.py eval
step 4_analyze "$PGM_BENCH_PY" benchmarks/external/analyze_suite.py
echo "campaign finished $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
