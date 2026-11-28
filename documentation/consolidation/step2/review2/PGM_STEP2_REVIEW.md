# Independent review: consolidation repairs and step 2

Reviewed remote branch `consolidate/production-layout` at `d45a1367101ff5d68597684aa29c1cecced76fd9`, frozen engine `f74f7f3da84cade7ac2bc6776087790a0c698a73`. Remote main remained `d6d751d5a13cb48d0d8175df744ba2f95eef1b9f`. The source checkout stayed clean. No inference benchmark was rerun or solver source edited in this review.

**Decision: retain the consolidation and its measured preservation result. Hold merge for two reproduced cleanup defects. Resolve the remaining evidence and analyzer issues in the same bounded pass. There is no reason to restart the architecture or repeat all 732 cells solely because of the documentation incident.**

## What the evidence establishes

The committed compact cells and full supervisor receipts contain exactly 732 unique expected cells, with no missing or duplicate identities. Their times, exits, outcomes and RSS records agree. The charge recomputes to **4,130.231398 seconds**. Frozen and amended analyses preserve the same completion sets and paired measurements.

| Arm | Both-repeat completions / 61 |
|---|---:|
| Pinned accepted reference | 45 |
| Consolidated accepted | 45 |
| Pinned experimental reference | 54 |
| Consolidated experimental | 54 |
| libDAI junction tree | 25 |
| libDAI BP | 60 point-output completions; not certified inference completions |

Accepted preserves the 29 historical successes and all 45 same-round reference successes. Experimental preserves all 54 same-round reference successes. These are substantive evidence that the extracted implementations retained their coverage.

I recovered the original `3283cfd` campaign from the earlier evidence packet. Its `ANALYSIS.json` SHA-256 is exactly the prerequisite named in the submitted plan: `45d954bb3c4d68e8804a42041bd90c6f79a668dccb61f2692b7bfb8b6fe52d6f`. All 122 PGM seed-cell model/evidence identities match the current suite. **All 47 historical experimental successes are retained.** The supplied `results/HISTORICAL_3283CFD_122_CELLS.json` and comparison close NOT_EVALUABLE by analysis, without new inference. The seven additional successes also occur in the pinned experimental reference on this host, so they are not new algorithmic gains from consolidation.

R2 compatibility shims, R4 dependency classification, R5 fixture isolation, and the single exact-reader definition are substantively repaired. Targeted local repair tests passed; one selection reported 28 passes and two native-setup failures because Clang is unavailable here. A separate overlapping runtime/shim/qualification/CBI selection reported 33 passes and one private-fixture skip. Do not add those counts or describe this as an independent rerun of the entire 99-test native qualification.

## Merge blockers: cleanup must govern publication and ownership

**1. Final cleanup failure does not revoke the returned answer.** In `src/pgm/runtime/attempts.py`, the `(result, record)` return is evaluated before `finally`. The finalizer can then set the record to `CLEANUP_UNRESOLVED` while leaving the already-selected result intact. `switchboard.solve` consumes that result without rejecting the conflicting terminal attempt state. A bounded injection through the actual switchboard returns **COMPLETE with two published rows while its attempt says CLEANUP_UNRESOLVED**. The benchmark reader also accepts this combination because it rejects only `NOT_STARTED` among unresolved attempt labels.

Required repair: stage the candidate result, finish all cleanup and final accounting, and only then make the acceptance/return decision. Unresolved ownership must suppress success and rows from that attempt. Make the public switchboard and analyzer enforce the same terminal condition. Preserve the existing hard deadline and inventory behavior. Evidence: `runtime/PROBE_RESULTS.json`, `runtime/probe_repairs.py`, `gates/ANALYSIS_BOUNDARIES.json`.

**2. The process-group identity check accepts the normal reuse direction.** `_identity_members` treats `created >= recorded_spawn - 5` as proof of ownership. A newer unrelated process reusing an old numeric group ID satisfies that test. `kill_owned` also scans and signals recorded groups even when its own receipt already establishes terminal cleanup. A controlled disposable sleeper, under a deliberately stale registration simulating identifier reuse, is killed both with and without such a terminal receipt. This is not an observation of actual OS identifier reuse or collateral termination in the benchmark.

Required repair: use recorded process-incarnation identity and invocation ownership, not merely a lower bound on creation time. Do not signal stale/unverifiable identities. Avoid rescanning and signalling groups after valid terminal cleanup is established. Do not kill a whole group containing unverified members. Retain bounded cleanup for a supervisor that dies before its owned worker. The probe cleans up only its own processes on exit.

## Qualification and analysis corrections

- The improved wheel gate still validates counts rather than the exact original coordinate set. Mutating every state key in its passing block receipt to zero leaves PASS. Require exact expected keys, uniqueness and the actual geometry/inventory predicates; add this negative control. This is a gate defect, not evidence that the archived wheel outputs were duplicated.
- `validity_excluding_operator_identity_incident` excludes every issue beginning with the identity-failure prefix. It is not restricted to the one disclosed job. Injected unrelated accepted/reference identity failures still yield PASS for that field. Scope any adjudication to the exact job and evidence; all other identity failures must remain failures.
- The freeze records external reference roots, but the per-cell identity check does not recheck their source closures. Add before/after checks for the actual arm's own frozen reference and native artifacts. There is no evidence those references changed in this campaign.
- Amendment 2 reasonably distinguishes the legacy solver's work allowance from the outer 20-second delivery contract for the recorded non-completions. It changes no completion count. However, four of the 16 reclassified cells publish partial coordinates (1qt9: 31, MUNIN1: 903, both repeats). Rename “non-publishing” to “non-completing.” The implementation also waives the old internal-wall rule for COMPLETE outputs, broader than the amendment's description. Restrict the exception to the stated statuses or explicitly specify the broader contract prospectively. Keep the original analyzer outputs.

## The operator incident

The committed evidence shows one failed post-cell identity check, `exposed_regression__DBN_11__LIBDAI_BP__r1`, and an abort before the next cell. The tracked-document-only attribution is in the operator log; the compact records do not preserve a changed-file hash diff proving that transient scope. Restoring the final tree does not by itself prove what changed in flight.

Retain the original validity FAIL. Inspect any raw closure evidence that can establish the scope; otherwise run **one separately labelled clean supplemental replay** of the affected cell under the original contract. Do not overwrite its failed identity or call the original campaign pristine. This incident does not by itself require another whole-matrix run.

## What the benchmark says about the product

Experimental completes every JT success and 29 additional tasks. On the 25 mutual completions it is faster in both repeats on 11 and slower in both on 14; median PGM/JT wall ratio is **1.336**. Large real gains include approximately **28.17x on Promedus_37**, **23.03x on Promedus_12**, and **5.34x on CSP_12**. This supports broad coverage and substantial gains on particular families, not broad latency dominance or a scaling theorem. BP's point outputs are a separate accuracy comparison.

The 18 accepted/reference cost flags reproduce. Accepted's median wall ratio is **1.090**; for the 26 mutual tasks with reference median time above two seconds it is **1.048**. The decomposition supports wrapper overhead as a major contributor, but “entirely fixed” is too strong: controller-minus-worker ranges about **0.141 to 0.864 seconds**, and exact parsing occurs inside the worker timer. The stated 0.03–0.15-second worker difference describes the flagged-task medians, not all 45 mutual tasks. Keep the measured end-to-end costs. There is no reason to introduce per-instance tuning or make all 18 flags disappear before acknowledging preservation. General reduction of duplicate inspection, process startup, imports and redundant cleanup belongs in the later performance pass, with the same guarantees.

## Scope and next action

The full current raw result/launch/native archive is not in the repository or available among the supplied files here. I independently checked compact/receipt consistency, source changes and bounded probes, and recovered the historical result set. I did **not** independently validate all 468,324 coordinate geometries or rerun the full raw analyzer. The aggregate count agrees with the summaries; their zero geometry/JT-exclusion claims remain producer-checked until the raw archive is supplied.

Follow `CLAUDE_STEP2_BOUNDED_COMPLETION.md`: fix cleanup and gates, incorporate the recovered extract, preserve/reconcile the incident, make the raw packet available, and confirm the changed public runtime over the full existing task set. Do not use another broad theory round, recalibrate policies, or discard the successful preservation evidence. Main stays unchanged until the actual runtime blockers and raw-evidence check are closed.
