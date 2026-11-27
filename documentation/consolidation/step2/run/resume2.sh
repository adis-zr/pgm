#!/bin/sh
set -u
export PGM_BENCH_PY=/Users/adis/Workspace/pgm/code/.venv/bin/python PGM_LIBDAI=/Users/adis/Workspace/pgm/code/bench/libdai/libdai_mar PGM_BENCH_REFERENCE_ROOT=/Users/adis/Workspace/pgm-ref-7f28259 PGM_BENCH_EXPERIMENTAL_REF_ROOT=/Users/adis/Workspace/pgm-ref-3283cfd PGM_BENCH_RUN_DIR=/Users/adis/Workspace/pgm-consolidate/benchmark_runs/step2-preservation-v1 CC=/usr/bin/clang CXX=/usr/bin/clang++
unset PYTHONPATH PGM_NATIVE_CACHE
cd /Users/adis/Workspace/pgm-consolidate || exit 2
LOG="$PGM_BENCH_RUN_DIR/CAMPAIGN_OPERATOR.log"
step() { name="$1"; shift; echo "## $name (resume 2) $(date -u +%Y-%m-%dT%H:%M:%SZ): $*" >> "$LOG"; "$@" >> "$PGM_BENCH_RUN_DIR/$name.log" 2>&1; rc=$?; echo "exit $rc $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"; }
step 2_primary "$PGM_BENCH_PY" benchmarks/external/run_suite.py primary
step 3_eval "$PGM_BENCH_PY" benchmarks/external/run_suite.py eval
step 4_analyze "$PGM_BENCH_PY" benchmarks/external/analyze_suite.py
echo "resume 2 finished $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
