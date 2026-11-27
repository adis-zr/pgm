# Step 2: external preservation regression of the consolidated package (FROZEN PLAN, ready to run)

Status: frozen with consolidation step 1 (branch `consolidate/production-layout`). Nothing in this plan has been executed.
No performance or holdout campaign ran during step 1; the synthetic fixtures of step 1 are correctness tests only.

## Question

Does the consolidated package preserve the known result on the external inputs? The reference is the accepted engine
v2.13.2 at `7f28259` (`reference/previous_accepted_cells.json`: 27 / 29 accepted-engine completions were retained by the
scored implementation `3283cfd`; DIABETES and ObjectDetection_43 were lost; Pedigree_12 is a further coverage gap). All 61
external inputs are already exposed (`EXPOSURE_HISTORY.json`); there is no holdout left, so step 2 is a regression, not a
prospective evaluation, and must be reported as such.

## Arms (one frozen package, explicit policy per arm; same 20 s outer contract, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6)

| arm | command | role |
|---|---|---|
| accepted reference | historical cells of engine `7f28259` (`reference/previous_accepted_cells.json`; not re-run) | the preservation target |
| `PGM_ACCEPTED` | `python -m pgm ... --policy accepted` | the accepted engine through the common contract (DEFAULT policy); must retain the reference completions |
| `PGM_EXPERIMENTAL` | `python -m pgm ... --policy experimental` | the frozen `structural-portfolio-1` of `3283cfd` under the new layout; must reproduce its 27 / 29 (DIABETES, ObjectDetection_43 lost) |
| `LIBDAI_JT` | qualified libDAI junction tree (`provenance/LIBDAI_*`) | exact comparator (geometry agreement) |
| `LIBDAI_BP` | qualified libDAI loopy BP | point comparator (convergence recorded) |

Cells: 61 tasks x 4 arms x 2 replicates = 488 (the 55 `exposed_regression` tasks in phase `primary`, the 6 former holdout
tasks in phase `eval`; both phases are regression now). Scored ceiling 8000 s per the frozen harness; the ceiling may be
raised ONLY in the freeze record before any cell runs.

## Acceptance (decided before execution)

1. `PGM_ACCEPTED` retains every task in `prior_complete_both` of the reference (29 tasks; `ANALYSIS.json.prior_accepted_comparison.per_arm.PGM_ACCEPTED.lost == []`). Any loss is a preservation regression of the common contract (controller / worker / publication), to be diagnosed, not re-tuned.
2. `PGM_EXPERIMENTAL` reproduces the scored portfolio: retained set equal to `3283cfd`'s (27 / 29; lost exactly {DIABETES, ObjectDetection_43}) and the same completion set on the remaining inputs. Differences are layout regressions (the arithmetic is byte-identical; a difference can only come from the request-level boundaries) and block default promotion.
3. Geometry: zero faulty published artifacts; every published enclosure contains the JT point within the serialization allowance (`jt_agreement` per arm); no certificate conflict.
4. Default promotion (`accepted` becomes the shipped default on main) requires 1 and 3; `experimental` stays selectable only. No new rates, per-instance exceptions, model-name routing or spectral / certificate change may be introduced to meet 1-3.

## Commands (run on the qualified host; all paths relative to the repository root)

```bash
# 0. environment: the frozen interpreter, the qualified comparator, the qualified C compiler
export PGM_BENCH_PY=/path/to/venv/bin/python PGM_LIBDAI=/path/to/code/bench/libdai/libdai_mar CC=clang
export PGM_BENCH_RUN_DIR=$PWD/benchmark_runs/step2-preservation-v1
# 1. build the native kernels during setup (never inside a timed cell) and warm the caches
PYTHONPATH=src:code $PGM_BENCH_PY -m pgm.build
# 2. smoke: one task through every arm BEFORE freezing (no scoring; deleted afterwards)
PYTHONPATH=src:code $PGM_BENCH_PY -m pgm --input benchmarks/external/inputs/<one task>.uai --output /tmp/smoke_acc.json --budget 19.5 --memory-mib 3072 --seed 1 --epsilon 1/200 --delta 1/1000000 --policy accepted
PYTHONPATH=src:code $PGM_BENCH_PY -m pgm --input benchmarks/external/inputs/<one task>.uai --output /tmp/smoke_exp.json --budget 19.5 --memory-mib 3072 --seed 1 --epsilon 1/200 --delta 1/1000000 --policy experimental
# 3. freeze (records engine commit, every tracked file hash, the active host builds, both policies, the harness hashes)
$PGM_BENCH_PY benchmarks/external/run_suite.py freeze
# 4. execute (resumable; one terminal receipt per cell; stops at the scored ceiling)
$PGM_BENCH_PY benchmarks/external/run_suite.py primary
$PGM_BENCH_PY benchmarks/external/run_suite.py eval
# 5. analyse (recomputes completion / geometry from raw artifacts; per-arm prior comparison; REPORT.md)
$PGM_BENCH_PY benchmarks/external/analyze_suite.py
```

Outputs: `FREEZE.json`, `RECEIPTS.jsonl`, `CELLS.jsonl`, `runs/*/`, `ANALYSIS.json`, `PAIRS.csv`, `REPORT.md` under
`$PGM_BENCH_RUN_DIR`. Charge every cell; keep failed and timed-out cells in coverage; memory refusals never enter a
speedup denominator.

## What this plan does not do

No per-task tuning, no hindsight backend selection, no repair of the three coverage gaps (DIABETES, ObjectDetection_43,
Pedigree_12), no dense-graph experiment, no learned proposer, no new rate files. The harness change of step 1 is limited
to running the public entrypoint under an explicit `--policy` per arm and analysing each public arm against the
comparators and the reference.
