# Independent review of step-2 results and overhead

Reviewed branch head `d45a1367101ff5d68597684aa29c1cecced76fd9`; scored engine `f74f7f3da84cade7ac2bc6776087790a0c698a73`. No source changes or solver runs were made by this reviewer.

## Scope and positive findings

I recomputed the set arithmetic and timing statistics from committed `CELLS_COMPACT.jsonl`, `FREEZE.json` and all terminal `RECEIPTS.jsonl` records rather than relying on the report's tables. There are exactly 732 expected, unique cell keys and 732 unique terminal receipts. Every compact cell's elapsed time, exit code, receipt outcome and peak RSS agrees with its receipt. Charge sums to 4,130.23139837796 seconds.

Both-repeat completion counts and every reported paired median ratio reproduce:

| Arm | Both-repeat completed tasks |
|---|---:|
| Pinned accepted reference | 45 |
| New accepted API | 45 |
| Pinned experimental reference | 54 |
| New experimental API | 54 |
| libDAI JT | 25 |
| libDAI BP output | 60 |

The accepted pair has identical completion sets and labels; the experimental pair also has identical completion sets and labels. The same-round experimental layout timing ratio is 1.0012477 on the 54 shared completions. Its new/old latency variation is bidirectional (11 tasks faster in both repeats, 15 slower in both, 28 mixed), consistent with preservation rather than an algorithmic speed claim.

The experimental result strictly contains both the 45-task accepted set and the 25-task JT set. The nine extra completions over accepted are ANDES, CSP_12, DBN_12, DBN_15, DBN_16, MUNIN1, Pedigree_11, Pedigree_12, Pedigree_13. This is real same-round evidence that the portfolio recovers valuable methods; it is not an outcome that should be obscured by the cleanup hold.

The accepted completed tasks split into 10 EXACT, 25 DETERMINISTIC, 10 PAC labels; experimental splits into 8 EXACT, 36 DETERMINISTIC, 10 PAC labels. These are the declared output guarantees, not independent exact-oracle validation of all large tasks. libDAI entries are POINT_ONLY; BP's 60 outputs (56 converged in both repeats) are not 60 certified answers.

## Historical experimental preservation is recoverable now

The parent reviewer recovered the original scored `3283cfde40fe277e218987954b01b3ed94f4a712` evidence archive. I extracted its 122 PGM seed-cells, bound them to original source hashes, and compared every model/evidence hash with the current 61-task freeze. All 122 match.

All **47 historical both-repeat experimental completions are retained** by both new experimental and pinned experimental arms. The seven extra current-host completions are BN_13, DIABETES, ObjectDetection_24, ObjectDetection_39, ObjectDetection_43, Pedigree_12 and linkage_13. Since the pinned old implementation also completes all seven, these are not new algorithmic gains from consolidation.

The supplied `HISTORICAL_3283CFD_122_CELLS.json` and `HISTORICAL_3283CFD_COMPARISON.json` close the missing-data prerequisite without any solver rerun. Integrate them as a labelled analysis addition; preserve the original NOT_EVALUABLE report as historical. The extraction script is included. Do not use old/Linux versus current/Mac timings as causal speed ratios.

## Eighteen overhead flags are real, but attribution is overstated

All 18 flags reproduce under the adopted rule: both repeats exceed 1.25x and +0.1 seconds relative to the pinned accepted reference. Accepted is slower in both repeats on 44/45 mutual completions; DBN_11 is mixed. The task-median latency ratio is 1.08994. Restricting descriptively to the 26 tasks whose reference median exceeds two seconds gives 1.04791, matching the reported approximately 1.05.

The controller-minus-worker decomposition is useful, but is not a causal proof that the regressions are *entirely fixed overhead*. The request-level outside-worker amount spans 0.14086–0.86449 seconds, with median 0.19037; across task medians the extrema are the reported approximately 0.146–0.844. MILDEW is flagged at approximately +0.852 seconds, of which the recorded controller-minus-worker component is approximately 0.809 seconds. Input-dependent inspection and serialization are not constant-time costs.

`documentation/consolidation/step2/START_HERE.md:54` also includes “exact parse” in controller-minus-worker overhead. The exact `load_bound` call occurs after the worker clock begins (`src/pgm/backends/worker.py:37`–44), so its time is inside worker time, not in that difference. The difference includes operations outside the worker timer; it does not separate each category's cost. The `candidate_inspection_s` values in the current decomposition are null.

The statement “engine time inside the worker is within 0.03–0.15 seconds of the reference” is accurate only for the task medians of the 18 flagged cases. Across all 45 mutual tasks, BN_12 differs by about +0.566/+0.572 seconds and BN_13 by +0.635/+0.600; a DBN_14 repeat differs by +0.755. Worker and standalone solver timers also cover different boundaries, so call this a timer decomposition, not isolated kernel attribution. This reporting correction changes no validity, completion or frozen overhead gate.

Recommended engineering target: a single canonical parse and one enforcement boundary around a request, with measured inspection/import/parse/execute/publication components. Do not bypass deadlines, memory enforcement or per-request isolation just to remove the flag. No per-instance tuning is required to attack duplicated boundary work.

## libDAI conclusion: broad coverage and substantial individual wins, not broad latency dominance yet

On the 25 tasks completed by both experimental and JT, experimental is faster in both repeats on 11 and slower in both on 14. Median experimental/JT time is **1.33552**. Real substantial speedups include:

| Task | Experimental median s | JT median s | JT / experimental |
|---|---:|---:|---:|
| Promedus_37 | 0.5854 | 16.4925 | 28.17x |
| Promedus_12 | 0.3933 | 9.0588 | 23.03x |
| CSP_12 | 0.4580 | 2.4450 | 5.34x |
| WATER | 0.3238 | 1.2323 | 3.81x |
| Grids_14 | 2.2236 | 7.6650 | 3.45x |
| Grids_11 | 2.2301 | 7.6714 | 3.44x |

The experimental arm supplies 29 additional completions where JT does not complete under this contract, and loses none of JT's 25. This coverage difference is the strongest current external result. It must not be converted into fabricated finite speed ratios for JT memory refusals or timeouts. The varying external graph families are also not a controlled scaling curve.

A descriptive latency-coverage view (tasks successful in both repeats and within the displayed observed threshold in both) is:

| Observed threshold | Experimental | Accepted | JT |
|---|---:|---:|---:|
| 0.1 s | 0 | 0 | 6 |
| 0.5 s | 11 | 12 | 8 |
| 1 s | 18 | 15 | 9 |
| 2 s | 25 | 17 | 15 |
| 5 s | 35 | 22 | 20 |
| 10 s | 42 | 38 | 24 |
| 20 s | 54 | 45 | 25 |

These thresholds summarize the existing 20-second runs; they are not new experiments with shorter request budgets.

## Validation scope that must remain explicit

The repository ships compact cells and analytical summaries, but does not contain the current run's raw per-cell coordinate artifacts. `RUN_ARCHIVE.json` identifies their separate 39.22 MB archive. Therefore this review independently verifies counts, receipt agreement, sets and aggregate arithmetic; it does **not** independently replay all 468,324 coordinate enclosures or the 180 JT comparison outputs.

The 468,324 published-coordinate total matches the sum of committed compact counts. The analyzer reports 180 JT comparison outputs totaling 119,224 coordinate instances, all with zero exclusions after the 5e-10 serialization allowance. All 180 happen to be complete outputs (`partial:false`); the code supports partial-output comparisons but this campaign does not exercise that branch. Zero conflicts in the analytical artifact is not an independent check of the unavailable raw intervals.

The only compact identity failure is DBN_11 / LIBDAI_BP / repeat 1, explaining BP's one-repeat-only task. It does not change any PGM or JT completion set. Protocol and source-identity adjudication belongs to the separate gate review; this result review does not silently waive that failure.

## Included reproducible evidence

- `recompute_results.py`, `RECOMPUTED_RESULTS.json`: current compact/receipt arithmetic.
- `recover_historical_experimental.py`: immutable old-record extraction and comparison.
- `HISTORICAL_3283CFD_122_CELLS.json`: 122 old PGM cells, input hashes and provenance.
- `HISTORICAL_3283CFD_COMPARISON.json`: current-versus-historical preservation, by matching identities.

The source checkout remains unchanged.
