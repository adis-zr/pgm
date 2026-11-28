# Untuned switchboard: implementation and full external benchmark

The implementation finds a real dispatch omission and repairs it without changing the accepted default. It recovers a new exact completion and large improvements on two existing portfolio cases. **It does not establish broad speed dominance over libDAI, and the automatic policy is not ready for default promotion.**

This is a review branch on consolidation baseline `f664ee7aa06851c77e9876cea409d4a04a9e4b21`. The measured engine is `d33d40aec7a05ec43cd52ff2793e544f9edc4cf0`. Later changes contain analysis portability, tests and records only; no measured algorithm was altered after outcomes were observed. Nothing was pushed to the user's remote or merged into main.

## What changed

The new opt-in `policy="automatic"` applies the existing physical-work and memory admission rule for higher-arity exact contraction to binary factors too. It retains the existing quarter-budget allowance, fallback order, rates and risk allocations. Earlier forest, bipartite and pairwise branches retain precedence. There are no input-name rules or fitted thresholds. The old experimental policy and accepted default remain available.

Lazy public imports and exact lexical fast paths reduce common runtime work. New diagnostic fields expose dispatch, inspection, parsing and execution costs; they are assembled before the authoritative final timestamp. Numerical backends, native kernels and publication/cleanup acceptance rules are unchanged. See [IMPLEMENTATION.md](IMPLEMENTATION.md).

## The frozen experiment

All 61 committed external tasks, six arms, two fresh-process repeats: **732/732 cells**, **4,595.728 supervised seconds** of a 14,640-second ceiling. Each cell has a 20-second outer contract and 3 GiB sampled process-tree RSS cap; PGM receives 19.5 seconds, epsilon 0.005 and request delta 1e-6. The parent and candidate run on the same Linux host with the same interpreter and qualified native toolchain. All inputs are exposed regression tasks. This is not an unseen evaluation or a same-machine reproduction of the earlier Mac results.

| Arm | Completes in both repeats | Completes in only one |
|---|---:|---:|
| Parent accepted | 40 | 0 |
| Candidate accepted, still default | 40 | 0 |
| Parent experimental | 48 | 2 |
| Candidate automatic | 50 | 1 |
| libDAI junction tree | 32 | 1 |
| libDAI BP point output | 61 | 0 |

BP produces point estimates without the requested error certificate; its output count is not certified coverage. JT is a numerical exact-method comparator, checked with its retained serialization allowance. Coverage comparisons also differ in guarantee strength: PGM can complete deterministically or with a PAC certificate while JT computes numerical exact marginals.

## Gains and preservation limits

Against the parent experimental policy, automatic preserves all 48 both-repeat completions and has no confirmed cost flags on their mutual completions. The substantive new completion is **Pedigree_12**, exact in 0.446 and 0.438 seconds; the parent portfolio times out in both repeats. **BN_13** also changes from one-repeat to both-repeat completion, on the same block route; that is a near-cutoff timing observation.

| Task | Parent experimental median | Automatic median | Improvement against parent portfolio |
|---|---:|---:|---:|
| Pedigree_11 | 15.181 s | 0.481 s | 31.55× |
| ANDES | 10.337 s | 1.548 s | 6.68× |
| WIN95PTS | 0.410 s | 0.210 s | 1.95× |

These are improvements over our previous portfolio, not the corresponding libDAI speedups. The median automatic/parent-experimental ratio across 48 mutual completions is 0.994. Candidate accepted preserves the parent's 40 tasks, has a median ratio of 0.987 and no confirmed cost flags. Small ratios near one should not be overstated with two repeats.

The stronger union gate **fails**. Parent accepted plus parent experimental cover 51 tasks. Automatic misses **ObjectDetection_39** in both repeats and **DIABETES** in one repeat, while adding Pedigree_12. Both losses follow the inherited quotient-before-block sequence, which spends time before the method that completes in accepted. They are not instances of the new binary-contraction branch. DIABETES is threshold-sensitive: old experimental also completes only one repeat, in the opposite repeat. The accepted policy completes both tasks twice. We have not yet produced one policy that combines all available wins.

## The comparison with libDAI

Automatic completes 19 tasks that JT does not complete in both repeats, while JT completes DIABETES, which automatic does not reliably complete. On the 31 mutual completions, automatic is faster in both repeats on **seven**, slower in both on **22**, and mixed on two. Its median wall-time ratio is **6.46× slower than JT**. There are 21 confirmed cost flags against JT.

The existing structural advantages remain visible: automatic is about 5.38× faster on DBN_14, 5.35× on Promedus_12, 5.23× on mastermind_03_08_04-0003 and 4.81× on DBN_11, with substantially lower measured RSS on those cases. Conversely, JT is much faster on numerous easy cases, including ANDES despite our improvement there. This run does not reproduce a broad 20–100× advantage.

The two mutually completed tasks above 1,000 variables favor PGM, but two heterogeneous cases do not establish a scaling law. Full family and size tables, memory results and every pair are in [results/ANALYSIS.json](results/ANALYSIS.json) and [results/PAIRS.csv](results/PAIRS.csv). Failed cells are censored, never assigned a synthetic speedup.

## Qualification and the validity failure

Before the freeze: 200 tests passed, one skipped, 39 subtests passed; DGP10 controls 12/12; libDAI tiny exact-reference qualification 11/11; same-host parent/candidate parity was identical. Historical Mac parity had ten last-bit spectral differences on two fixtures, retained separately. The lexical audit matched parent metadata across all 61 inputs and 1,914,150 entries; previous experimental plans matched on identical metadata. Seven post-run analysis-path/dispatch test cases were added; the focused harness/analysis suite passes 26/26.

All 732 source identities and receipt bindings pass. The audit checks 421,809 published coordinate instances: no geometry, inventory, binding or witness faults, no deterministic or PAC cross-arm conflict, and no JT exclusion in 165,660 coordinate comparisons. No result publishes rows after its authoritative deadline check. These checks do not turn comparator agreement into an independent proof of every marginal.

**The original frozen campaign validity verdict remains FAIL**, for exactly three records:

1. DBN_12 / LIBDAI_JT / repeat 2 and DBN_15 / LIBDAI_JT / repeat 1 were killed at timeout, leaving only a four-byte `MAR` header. The strict analyzer counts their truncated outputs as artifact faults. Neither is accepted or used in a finite latency ratio.
2. Grids_15 / PGM_ACCEPTED / repeat 2 reports an internal final time of 19.502556 seconds against 19.5 seconds. It returns DEADLINE/NONE with zero of 800 rows, cleans up successfully and finishes inside the outer 20-second contract. This is a 2.56 ms internal deadline failure with successful publication suppression, not a wrong marginal.

No scoring cell was rerun or relabelled. We have not weakened the frozen validity gate after observing these events. Promotion remains on hold for both validity and union preservation.

## Portable evidence and next implementation target

The full raw archive contains every cell, launch, stdout/stderr, result, receipt, ownership record, freeze, setup qualification and executed native artifact. The original analysis is preserved. A post-run amendment only resolves recorded source paths against a restored checkout; hashes still authenticate the inputs. Recomputed analysis, pair table and frozen report are byte-identical. Original absolute execution paths are retained as provenance. Linux timings must not be represented as Mac timings; a new host needs a new setup and freeze.

The next bounded implementation target is scheduling the existing methods under one construction account, so unsuccessful quotient exploration cannot consume the time needed by a completing primary route. Candidate construction, parsing and discarded work must count in that decision. The current evidence does not justify new graph-specific thresholds, further kernel tuning or a claim that dense-cycle mathematics is the immediate blocker for this external-suite objective. A future selection rule needs its own frozen full-suite test and genuinely unseen holdout before a generalization claim.

Keep `accepted` as the default. Import this branch for review and reproduce the evidence before choosing any promotion. The returned bundle contains both the frozen implementation commit and the report/portability commit; it requires the consolidation baseline already present in the user's repository.
