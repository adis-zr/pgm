# External inference benchmark

This is the repeatable performance benchmark for the supported `pgm` entrypoint. It runs every committed external input against libDAI junction tree and loopy belief propagation. Synthetic models are used by the correctness tests, not by this performance suite.

The committed inputs comprise **61 exposed regression tasks** in two historical groups: `old55` (INPUT_MANIFEST.json) and `former_eval6` (HOLDOUT_FREEZE.json; prospective only in the v1 campaign at `3283cfd`). `INPUT_MANIFEST.json` and `HOLDOUT_FREEZE.json` bind their original model/evidence bytes and preserve their separate roles. The former evaluation tasks were selected before that campaign using a fixed hash rule and the available prior-exposure records. They are now exposed; incomplete older records also prevent an absolute never-seen claim about their original selection. Input files use content-based directories to prevent accidental benchmark-name dispatch.

**Exposure update, 27 November 2026:** the complete campaign at `3283cfd` has now scored all 61 tasks. The original manifests preserve their roles in that experiment; all 61 are exposed regression inputs for subsequent development. `EXPOSURE_HISTORY.json` records the transition. Reusing the six under the `eval` command does not create new unseen evidence. A later prospective claim requires a separately selected and frozen external cohort.

The current consolidation evidence comprises the six-arm 732-cell step-2 run and a 245-cell supplement of the repaired public runtime plus one comparator replay. Accepted retains 45 same-round reference completions; experimental retains 54, including all 47 historical experimental successes. The original campaign's one documentation-edit identity failure remains recorded; its comparator cell has a separately labelled valid replay. The 18 accepted/reference overhead flags remain reported. See [acceptance and limitations](../../documentation/consolidation/ACCEPTANCE.md) and [the complete step-2 packet](../../documentation/consolidation/step2/START_HERE.md). Older 366-cell results and their original holds remain historical evidence, not the current preservation verdict.

## Prerequisites

Use the installed project environment with Python 3.12, NumPy, gmpy2, psutil and SciPy. The current run's exact dependency versions are captured at freeze time. Before freezing:

1. Run `run_suite.py setup`: it builds and warms the native contraction, stream and heat-bath kernels of every arm's root outside any timed cell (set `CC` and `CXX` explicitly to the qualified compilers; `PGM_NATIVE_CACHE` is optional and pinned at freeze), then smokes all six arms on the committed tiny fixture under the strict supervisor and retains the evidence under `<run>/setup/`.
2. Build the repository's `code/bench/libdai/libdai_mar.cpp` driver against official libDAI 0.3.2. Set `PGM_LIBDAI` to that executable. Its default path is `code/bench/libdai/libdai_mar`. Comparator source, compiler flags, source URLs and the independent tiny-Fraction qualification are documented under `provenance/`.
3. Commit the implementation and benchmark definitions. The freeze refuses uncommitted source. Only the four tracked host-specific contraction/stream binary and build-record overlays are allowed to differ from git; their bytes are explicitly frozen. The active ignored heat-bath build and all active native cache copies are frozen too.

The comparator binary is not committed. A previously qualified build may be reused only with its recorded source and binary hashes and compatible host libraries. Compilation, installation and numerical qualification are setup costs, separate from scored inference time.

## Run

From the repository root, with the project interpreter active:

```bash
export CC=/absolute/path/to/qualified/clang CXX=/absolute/path/to/qualified/clang++
export PGM_LIBDAI=/absolute/path/to/qualified/libdai_mar
export PGM_BENCH_REFERENCE_ROOT=<detached checkout at 7f28259> PGM_BENCH_EXPERIMENTAL_REF_ROOT=<detached checkout at 3283cfd>
export PGM_BENCH_RUN_DIR="$PWD/benchmark_runs/external-new-run"

python benchmarks/external/run_suite.py setup
python benchmarks/external/run_suite.py freeze
python benchmarks/external/run_suite.py primary
python benchmarks/external/run_suite.py eval
python benchmarks/external/analyze_suite.py
```

`PGM_BENCH_PY` may select a different project interpreter explicitly; otherwise the scripts use their own `sys.executable`. `PGM_BENCH_RUN_DIR` defaults to `benchmark_runs/consolidation-v1`. Choose a new directory for a new experiment. A freeze is never overwritten. Existing completed cells may be resumed only under the identical freeze; an incomplete launch requires explicit receipt reconciliation.

The two historical-cohort phases use the same committed implementation and policies. There are **732 cells**: 61 inputs × six arms (PGM_REFERENCE, PGM_ACCEPTED, PGM_EXPERIMENTAL, PGM_EXPERIMENTAL_REF, LIBDAI_JT, LIBDAI_BP) × two fresh-process repeats. Each receives **20 seconds and 3 GiB** under a zero-grace supervisor sampling process-tree RSS every 10 ms. PGM receives a 19.5-second internal allowance, epsilon 1/200 and per-request delta 1/1,000,000. The step-2 scored ceiling is **14,640 supervisor seconds**, fixed in `STEP2_AMENDMENT_1.md`. A new experiment needs its own committed declaration and freeze; do not edit a frozen source while it runs. The separate 245-cell supplement has its own 4,900-second ceiling in `STEP2_SUPPLEMENT_1.md`.

The output directory contains `FREEZE.json`, `CELLS.jsonl`, `RECEIPTS.jsonl`, all individual `runs/` outputs/logs, `ANALYSIS.json`, `GATES.json`, `PAIRS.csv` and `REPORT.md`. It is ignored by git. Preserve a complete run packet for review; do not overwrite an older experiment's files.

## Interpret

Read `STEP2_PLAN.md`, `STEP2_AMENDMENT_1.md` and the explicitly labelled later amendments before interpreting current results. `PROTOCOL.md` preserves the original three-arm campaign's historical protocol. Completion requires both repeats to finish and pass the independent inventory, binding, guarantee-label and probability-geometry checks. Historical cohort labels do not make current tasks unseen. A libDAI point answer or BP convergence is not a certified epsilon answer. Memory refusals have no latency denominator. Timeouts support only censored lower bounds.

`reference/` contains compact historical reports and accepted-engine cell summaries, not a large copy of the prior raw campaign. Those results are historical coverage references, not same-round controlled timings. The selected cohort alone cannot establish universal dominance or scaling laws. The benchmark retains failures and losses alongside wins.

`provenance/` preserves the original data selection/conversion scripts, public source locations, archive hashes, comparator build/qualification records and this round's holdout exclusion procedure. The old recovery scripts are archival records and may contain creator-workstation paths; normal execution uses only the committed inputs and relative manifest paths. No private records repository is needed to run this suite.
