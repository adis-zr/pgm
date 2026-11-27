# Step 2: external preservation regression of the consolidated package (v2 = STEP2_AMENDMENT_1)

Status: the v1 plan (four arms, 488 cells) was frozen with consolidation step 1 and had NO scored execution; it is superseded by
`STEP2_AMENDMENT_1.md` BEFORE any scored cell. This document is the amended normative plan; `STEP2_PLAN.json` is its
machine-readable form read by the harness at freeze.

## Question

Does the consolidated package preserve the known result on the external inputs? The reference is the accepted engine
v2.13.2 at `7f28259` (`reference/previous_accepted_cells.json`: 27 / 29 accepted-engine completions were retained by the
scored implementation `3283cfd`; DIABETES and ObjectDetection_43 were lost; Pedigree_12 is a further coverage gap). All 61
external inputs are already exposed (`EXPOSURE_HISTORY.json`); there is no holdout left, so step 2 is a regression, not a
prospective evaluation, and must be reported as such.

## Arms (one frozen package per arm; same 20 s outer contract, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6, two repeats, serial)

| arm | what runs | role |
|---|---|---|
| `PGM_REFERENCE` | the accepted standalone engine of pinned `7f28259` in a detached checkout, historical invocation (`integrated.py --budget 19.5 --seed REP --epsilon 1/200 --delta 1/1000000 --schedule targeted --route auto --proposal mb`), own import root | EXECUTED accepted reference (same round, same host) |
| `PGM_ACCEPTED` | `python -m pgm ... --policy accepted` | the accepted engine through the new common contract (DEFAULT policy) |
| `PGM_EXPERIMENTAL` | `python -m pgm ... --policy experimental` | the frozen `structural-portfolio-1` under the new layout |
| `PGM_EXPERIMENTAL_REF` | the scored public implementation of pinned `3283cfd` in a detached checkout (`python -m pgm`, its single policy) | EXECUTED experimental reference (same round, same host) |
| `LIBDAI_JT` | qualified libDAI junction tree (`provenance/LIBDAI_QUALIFICATION_HOST_2026-11-27.json`) | exact comparator (geometry agreement) |
| `LIBDAI_BP` | qualified libDAI loopy BP | point comparator (convergence recorded) |

Cells: 61 tasks x 6 arms x 2 replicates = **732**; phase `primary` runs the `old55` group, phase `eval` the `former_eval6` group;
both are exposed regression inputs. Declared ceiling 14,640 s (= 732 x 20 s, the maximum possible charge); exhaustion returns
INCOMPLETE. Historical cells of `7f28259` (`reference/previous_accepted_cells.json`, 29 both-repeat completions) remain a
coverage target; the 3283cfd extract required for the historical experimental target is unavailable on this host (see the
amendment, item 4).

## Explicit comparison pairs

`same_round_accepted` (PGM_ACCEPTED vs PGM_REFERENCE), `same_round_experimental` (PGM_EXPERIMENTAL vs PGM_EXPERIMENTAL_REF),
`accepted_vs_experimental`, and each result arm vs LIBDAI_JT.

## Gates (decided before execution; `GATES.json`)

1. **validity**: every recorded cell has one terminal receipt, identity_ok, valid output (inventory, geometry, labels, witness,
   simplex, binding) and a valid arm contract (policy / version / configuration / allowed backends / risk allocations / epsilon /
   delta / deadline / terminal attempts); every published coordinate contains the JT point wherever a valid JT point exists
   (partial outputs included); no deterministic interval conflict across arms or repeats.
2. **completeness**: all 732 cells recorded within the ceiling.
3. **historical_accepted_preservation**: PGM_ACCEPTED loses none of the 29 historical completions.
4. **reference_reproduction**: PGM_REFERENCE vs its own historical cells (a loss is a reproduction failure of the reference).
5. **same_round_accepted_preservation**: PGM_ACCEPTED loses no PGM_REFERENCE both-repeat completion.
6. **historical_experimental_preservation**: NOT EVALUABLE without the hashed 3283cfd extract (prerequisite named).
7. **same_round_experimental_preservation**: PGM_EXPERIMENTAL loses no PGM_EXPERIMENTAL_REF both-repeat completion.
8. **paired_overhead**: FLAGGED when PGM_ACCEPTED is slower than PGM_REFERENCE in both repeats by more than 1.25x and more than
   0.1 s; a flag holds promotion pending explanation.
9. **promotion_decision**: ELIGIBLE only with 1, 2, 3, 5 PASS and no unexplained flag. Gains are reported, never forbidden.

## Commands

See `STEP2_AMENDMENT_1.md` (setup -> freeze -> primary -> eval -> analyze). Setup evidence (builds, warm caches, the six-arm
smoke on the committed tiny fixture) is retained under `<run>/setup/`.

## What this plan does not do

No per-task tuning, no hindsight backend selection, no repair of the three coverage gaps (DIABETES, ObjectDetection_43,
Pedigree_12), no dense-graph experiment, no learned proposer, no new rate files. The harness changes of the amendment are limited to arm definitions, resource resolution, validation and analysis; no inference, scheduling or rate code is touched.
