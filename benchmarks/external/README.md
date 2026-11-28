# External inference benchmark

This is the repeatable performance benchmark for the supported `pgm` entrypoint. It runs every committed external input against libDAI junction tree and loopy belief propagation. Synthetic models are used by the correctness tests, not by this performance suite.

The committed inputs comprise **61 exposed regression tasks** in two historical groups: `old55` (INPUT_MANIFEST.json) and `former_eval6` (HOLDOUT_FREEZE.json; prospective only in the v1 campaign at `3283cfd`). `INPUT_MANIFEST.json` and `HOLDOUT_FREEZE.json` bind their original model/evidence bytes and preserve their separate roles. The former evaluation tasks were selected before that campaign using a fixed hash rule and the available prior-exposure records. They are now exposed; incomplete older records also prevent an absolute never-seen claim about their original selection. Input files use content-based directories to prevent accidental benchmark-name dispatch.

**Exposure update, 27 November 2026:** the complete campaign at `3283cfd` has now scored all 61 tasks. The original manifests preserve their roles in that experiment; all 61 are exposed regression inputs for subsequent development. `EXPOSURE_HISTORY.json` records the transition. Reusing the six under the `eval` command does not create new unseen evidence. A later prospective claim requires a separately selected and frozen external cohort.

The latest scored result is [performance round 2](../../documentation/performance/round2/REPORT.md): 732 cells, 52 automatic completions in both repeats, preservation of the 51-task same-round baseline union and all 50 previous automatic completions, with all predeclared release gates passed. Broad speed dominance over libDAI is **not established**: on 31 mutual completions the median automatic/JT wall-time ratio is 8.389. The accepted default remains unchanged. The later layout migration has qualification and frozen-evidence replay; it is not another scored performance run.

Earlier consolidation evidence remains at [acceptance and limitations](../../documentation/consolidation/ACCEPTANCE.md) and [the step-2 packet](../../documentation/consolidation/step2/START_HERE.md). Its original identity failure, separately labelled comparator replay and 18 overhead flags remain historical records. No later result rewrites them.
## Prerequisites

Use the installed project environment with Python 3.12, NumPy, gmpy2, psutil and SciPy. The current run's exact dependency versions are captured at freeze time. Before freezing:

1. Run `run_performance.py setup`: it builds and warms the native contraction, stream and heat-bath kernels of every arm's root outside any timed cell (set `CC` and `CXX` explicitly to the qualified compilers; `PGM_NATIVE_CACHE` is optional and pinned at freeze), then smokes all six arms on the committed tiny fixture under the strict supervisor and retains the evidence under `<run>/setup/`.
2. Build the repository's `benchmarks/external/comparators/libdai/libdai_mar.cpp` driver against official libDAI 0.3.2. Set `PGM_LIBDAI` to that executable. Its default path is `benchmarks/external/comparators/libdai/libdai_mar`. Current build and independent tiny-Fraction qualification commands are `comparators/libdai/build.sh` and `comparators/libdai/qualify.py`; both require fresh output directories. Set `PGM_LIBDAI_QUALIFICATION` to the resulting `LIBDAI_QUALIFICATION.json`. Historical source URLs, archive hashes and comparator records remain under `provenance/`.
3. Commit the implementation and benchmark definitions. The freeze refuses uncommitted source. Current native build outputs live outside the package. The four host-specific overlays permitted by the older checkouts remain an explicit compatibility exception; every executed native artifact and its build record is frozen separately.

The comparator binary is not committed. A previously qualified build may be reused only with its recorded source and binary hashes and compatible host libraries. Compilation, installation and numerical qualification are setup costs, separate from scored inference time.

## Run

A new scored experiment needs its own committed declaration before setup and freeze. The current runner uses the full 61-input, six-arm, two-repeat design from `PERFORMANCE_ROUND2_PLAN.md`: BASE_ACCEPTED and BASE_EXPERIMENTAL at `f664ee7`, current PGM_ACCEPTED and PGM_AUTOMATIC, LIBDAI_JT and LIBDAI_BP. The scored ceiling is 14,640 supervisor seconds. Each cell receives 20 seconds and 3 GiB; PGM receives a 19.5-second internal allowance, epsilon 1/200 and per-request delta 1/1,000,000.

From the repository root, after committing the new declaration and implementation:

```bash
export CC=/absolute/path/to/qualified/clang CXX=/absolute/path/to/qualified/clang++
export PGM_LIBDAI=/absolute/path/to/qualified/libdai_mar
export PGM_LIBDAI_QUALIFICATION=/absolute/path/to/LIBDAI_QUALIFICATION.json
export PGM_PERFORMANCE_BASELINE_ROOT=/absolute/path/to/detached-f664ee7-checkout
export PGM_PERFORMANCE_RUN_DIR=/absolute/path/to/new-run-directory

python benchmarks/external/run_performance.py setup
python benchmarks/external/run_performance.py freeze
python benchmarks/external/run_performance.py run
python benchmarks/external/run_performance.py analyze
```

The interpreter executing the runner is recorded and used for all Python arms. Native setup is separate from scored inference. Existing completed cells may be resumed only under their identical freeze; an incomplete launch requires explicit receipt reconciliation. Never edit a frozen source while it runs or overwrite an older packet. The output contains the freeze, every cell output and launch record, receipts, `ANALYSIS.json`, `PAIRS.csv` and `REPORT.md`.

To replay the accepted round-2 evidence after a source-layout change, without inference:

```bash
python benchmarks/external/replay_frozen.py --run-dir /path/to/extracted/performance_run_2 --output-dir /path/to/new-replay
```

This restores the exact frozen source into an isolated worktree and checks all input/reference/analyzer hashes, blocks creator-checkout reads, and requires all three reports to match byte for byte. The frozen commit must be available in local Git history or the supplied bundle. `run_suite.py` and `analyze_suite.py` retain explicit support for the older step-2 protocol and pinned checkouts; their historical plans and scored records are not the current performance verdict.

## Interpret

Read `PERFORMANCE_ROUND2_PLAN.md` and the round-2 report before interpreting the latest results. The step-2 plans and explicitly labelled amendments govern their historical campaigns. `PROTOCOL.md` preserves the original three-arm campaign's historical protocol. Completion requires both repeats to finish and pass the independent inventory, binding, guarantee-label and probability-geometry checks. Historical cohort labels do not make current tasks unseen. A libDAI point answer or BP convergence is not a certified epsilon answer. Memory refusals have no latency denominator. Timeouts support only censored lower bounds.

`reference/` contains compact historical reports and accepted-engine cell summaries, not a large copy of the prior raw campaign. Those results are historical coverage references, not same-round controlled timings. The selected cohort alone cannot establish universal dominance or scaling laws. The benchmark retains failures and losses alongside wins.

`provenance/` preserves the original data selection/conversion scripts, public source locations, archive hashes, comparator build/qualification records and this round's holdout exclusion procedure. The old recovery scripts are archival records and may contain creator-workstation paths; normal execution uses only the committed inputs and relative manifest paths. No private records repository is needed to run this suite.
