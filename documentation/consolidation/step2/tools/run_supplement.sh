#!/bin/sh
# STEP2_SUPPLEMENT_1 exactly as declared: setup -> freeze-supplement -> supplement -> analyze, serially, under the strict supervisor;
# the original run directory is read-only input (its FREEZE / ANALYSIS bind the preservation targets).
# usage: run_supplement.sh <venv python> <libdai_mar> <ref 7f28259> <ref 3283cfd> <original run dir> <supplement run dir> [CC] [CXX]
set -u
export PGM_BENCH_PY="$1" PGM_LIBDAI="$2" PGM_BENCH_REFERENCE_ROOT="$3" PGM_BENCH_EXPERIMENTAL_REF_ROOT="$4" PGM_BENCH_SUPPLEMENT_OF="$5" PGM_BENCH_RUN_DIR="$6"
export CC="${7:-/usr/bin/clang}" CXX="${8:-/usr/bin/clang++}"
unset PYTHONPATH PGM_NATIVE_CACHE
REPO="$(cd "$(dirname "$0")/../../../.." && pwd)"; cd "$REPO" || exit 2
mkdir -p "$PGM_BENCH_RUN_DIR"; LOG="$PGM_BENCH_RUN_DIR/CAMPAIGN_COMMANDS.log"
step() { name="$1"; shift; echo "## $name $(date -u +%Y-%m-%dT%H:%M:%SZ): $*" >> "$LOG"; "$@" > "$PGM_BENCH_RUN_DIR/$name.log" 2>&1; rc=$?; echo "exit $rc $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"; echo "$name exit $rc"; return $rc; }
git -C "$REPO" rev-parse HEAD > "$PGM_BENCH_RUN_DIR/ENGINE_COMMIT.txt"; git -C "$REPO" status --porcelain > "$PGM_BENCH_RUN_DIR/GIT_STATUS_AT_START.txt"
step 0_setup "$PGM_BENCH_PY" benchmarks/external/run_suite.py setup || exit 3
step 1_freeze_supplement "$PGM_BENCH_PY" benchmarks/external/run_suite.py freeze-supplement || exit 4
step 2_supplement "$PGM_BENCH_PY" benchmarks/external/run_suite.py supplement
step 3_analyze "$PGM_BENCH_PY" benchmarks/external/analyze_suite.py "$PGM_BENCH_RUN_DIR"
echo "supplement finished $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
