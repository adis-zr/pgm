# Step 2 external preservation regression -- START HERE

Branch `consolidate/production-layout`; frozen engine commit `f74f7f3da84cade7ac2bc6776087790a0c698a73`; FREEZE schema `CONSOLIDATION_EXTERNAL_V3` (STEP2_AMENDMENT_1); pinned references `7f28259` (PGM_REFERENCE, accepted standalone engine) and `3283cfd` (PGM_EXPERIMENTAL_REF, scored public implementation). Host `macOS-26.6.2-arm64-arm-64bit`, `Apple clang version 15.0.0 (clang-1500.0.40.1)`.

Read in this order: `REPAIRS.md` (before / after evidence for the step-1 review R1-R5 / B1-B7 AND the step-2 review's cleanup, incarnation and gate repairs), `../../../benchmarks/external/STEP2_AMENDMENT_1.md` (pre-run amendment), `STEP2_AMENDMENT_2.md` (post-run analysis amendment, rev 2), `STEP2_SUPPLEMENT_1.md` (the declared 245-cell confirmation of the changed runtime), `run/REPORT.md` and `run/GATES.json` (original run, rev-2 analysis; frozen and rev-1 outputs preserved beside them), `run/INCIDENTS.json` (the exact adjudicated incident), `run/ANALYSIS.json` / `run/PAIRS.csv` (every paired measurement), `run/FREEZE.json`, `run/setup/SETUP.json`, `supplement/` (the supplement's FREEZE / GATES / ANALYSIS / REPORT / compact cells), `RUN_ARCHIVE.json` (the UNCHANGED original raw archive by sha256, the separate post-run records archive and the supplement archive), `review2/` (the independent review's documents and probes).

## Gates

| gate | decision |
|---|---|
| validity | FAIL |
| completeness | PASS |
| historical_accepted_preservation | PASS |
| reference_reproduction | PASS |
| same_round_accepted_preservation | PASS |
| historical_experimental_preservation | PASS |
| same_round_experimental_preservation | PASS |
| paired_overhead | FLAGGED |
| validity_with_adjudicated_incidents_set_aside | PASS |
| promotion_decision | HOLD |

Recorded 732/732 cells; charged 4130 s of the declared 14640 s ceiling; validation issues 1; artifact faults 0; published coordinate instances 468324; deterministic conflicts 0; PAC conflicts 0; cost flags 18.

## Both-repeat completions on all 61 exposed inputs

| arm | completions |
|---|---:|
| PGM_REFERENCE | 45 |
| PGM_ACCEPTED | 45 |
| PGM_EXPERIMENTAL | 54 |
| PGM_EXPERIMENTAL_REF | 54 |
| LIBDAI_JT | 25 |
| LIBDAI_BP | 60 |

## Comparisons

- **same_round_accepted** (PGM_ACCEPTED vs PGM_REFERENCE): mutual 45; candidate-only none; comparator-only none; median wall ratio on mutual 1.09.
- **same_round_experimental** (PGM_EXPERIMENTAL vs PGM_EXPERIMENTAL_REF): mutual 54; candidate-only none; comparator-only none; median wall ratio on mutual 1.001.
- **accepted_vs_experimental** (PGM_ACCEPTED vs PGM_EXPERIMENTAL): mutual 45; candidate-only none; comparator-only ANDES, CSP_12, DBN_12, DBN_15, DBN_16, MUNIN1, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 0.996.
- **jt_vs_reference** (PGM_REFERENCE vs LIBDAI_JT): mutual 20; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only ANDES, CSP_12, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 3.065.
- **jt_vs_accepted** (PGM_ACCEPTED vs LIBDAI_JT): mutual 20; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only ANDES, CSP_12, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 3.318.
- **jt_vs_experimental** (PGM_EXPERIMENTAL vs LIBDAI_JT): mutual 25; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only none; median wall ratio on mutual 1.336.
- **jt_vs_experimental_ref** (PGM_EXPERIMENTAL_REF vs LIBDAI_JT): mutual 25; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only none; median wall ratio on mutual 1.409.

## Historical accepted completions (29 at 7f28259)

- PGM_REFERENCE: retained 29/29; lost none; gained BN_13, DBN_11, DBN_14, Grids_11, Grids_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_ACCEPTED: retained 29/29; lost none; gained BN_13, DBN_11, DBN_14, Grids_11, Grids_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_EXPERIMENTAL: retained 29/29; lost none; gained ANDES, BN_13, CSP_12, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, Grids_11, Grids_14, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Pedigree_11, Pedigree_12, Pedigree_13, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_EXPERIMENTAL_REF: retained 29/29; lost none; gained ANDES, BN_13, CSP_12, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, Grids_11, Grids_14, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Pedigree_11, Pedigree_12, Pedigree_13, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.

## Paired overhead (adopted criterion: both repeats > 1.25x and > 0.1 s slower than PGM_REFERENCE)

Flagged tasks: 18 of 45 same-round mutual completions: BN_31, Promedus_33, Promedus_12, Promedus_37, ASIA, CHILD, INSURANCE, WATER, MILDEW, ALARM, HAILFINDER, WIN95PTS, mastermind_03_08_04-0003, mastermind_03_08_05-0003, or_chain_186.fg, Promedus_36, Promedus_18, blockmap_10_01-0009. Outside-worker time per request (controller wall minus worker wall: lexical inspection, supervised worker spawn, interpreter + package import, publication; the exact parse runs INSIDE the worker timer) = median 0.190 s over the mutual completions (min 0.146, max 0.844). This is a timer decomposition, not an isolated kernel attribution: the outside-worker amount includes input-dependent inspection and serialization, and worker / standalone timers cover different boundaries.

| task | reference receipt s | accepted receipt s | difference s | fixed overhead s | accepted worker s | reference internal s |
|---|---:|---:|---:|---:|---:|---:|
| MILDEW | 2.506 | 3.358 | 0.852 | 0.809 | 2.491 | 2.396 |
| blockmap_10_01-0009 | 0.338 | 0.805 | 0.466 | 0.430 | 0.323 | 0.174 |
| mastermind_03_08_05-0003 | 1.584 | 1.997 | 0.413 | 0.358 | 1.589 | 1.443 |
| mastermind_03_08_04-0003 | 1.009 | 1.313 | 0.303 | 0.267 | 0.986 | 0.885 |
| BN_31 | 0.281 | 0.526 | 0.245 | 0.220 | 0.252 | 0.173 |
| or_chain_186.fg | 0.686 | 0.910 | 0.224 | 0.205 | 0.647 | 0.569 |
| Promedus_37 | 0.261 | 0.470 | 0.209 | 0.203 | 0.212 | 0.144 |
| Promedus_12 | 0.161 | 0.358 | 0.197 | 0.193 | 0.107 | 0.057 |
| Promedus_33 | 0.143 | 0.333 | 0.190 | 0.188 | 0.089 | 0.042 |
| Promedus_36 | 0.161 | 0.341 | 0.180 | 0.190 | 0.095 | 0.048 |
| WATER | 0.202 | 0.366 | 0.164 | 0.171 | 0.132 | 0.096 |
| Promedus_18 | 0.300 | 0.457 | 0.158 | 0.160 | 0.240 | 0.188 |
| WIN95PTS | 0.201 | 0.357 | 0.155 | 0.160 | 0.145 | 0.108 |
| HAILFINDER | 0.212 | 0.364 | 0.153 | 0.168 | 0.146 | 0.108 |
| INSURANCE | 0.222 | 0.371 | 0.149 | 0.163 | 0.156 | 0.119 |
| ALARM | 0.119 | 0.267 | 0.148 | 0.154 | 0.056 | 0.022 |
| CHILD | 0.119 | 0.250 | 0.131 | 0.146 | 0.047 | 0.014 |
| ASIA | 0.118 | 0.245 | 0.127 | 0.153 | 0.042 | 0.009 |

Every paired wall, ratio and difference is in `run/PAIRS.csv` (pair `same_round_accepted`) and `run/ANALYSIS.json` (`overhead_decomposition`). The 18 flags are real end-to-end latency regressions under the adopted rule and remain reported; the decomposition supports wrapper overhead as a major contributor on the flagged (cheap) tasks, where the flagged-task MEDIAN worker-versus-reference-internal difference is small, but across all mutual tasks individual differences reach several tenths of a second (e.g. BN_12, BN_13, a DBN_14 repeat). No rate or scheduler was changed; reducing duplicated boundary work is the next performance task.

## Amendments and incidents

- `STEP2_AMENDMENT_1` (pre-run, committed): the six-arm matrix, executed pinned references, owner-resolved natives, contracts, explicit pairs, GATES, ceiling 14,640 s.
- `STEP2_AMENDMENT_2` (post-run analysis only; `../../../benchmarks/external/STEP2_AMENDMENT_2.md`): the legacy internal-wall rule became a diagnostic (16 non-completing PGM_REFERENCE cells reclassified; frozen-analyzer outputs preserved as `run/*.frozen_analyzer_v1.*`), and the operator identity incident is recorded: during the run the operator edited a tracked documentation file, the harness identity guard aborted before cell 115, the in-flight comparator cell `DBN_11 LIBDAI_BP r1` carries `identity_ok = false`, the edit was reverted byte-for-byte and the run resumed under the same freeze (`run/CAMPAIGN_OPERATOR.log`). The frozen `validity` gate keeps that failure; `validity_excluding_operator_identity_incident` reports the same predicate with it set aside.

## Limitations

- Historical experimental preservation: the gate was NOT EVALUABLE at run time (extract absent; outputs preserved as `run/*.frozen_analyzer_v1.*` and `run/*.amendment2_rev1.*`); the independent review recovered the scored 3283cfd cells (`benchmarks/external/reference/HISTORICAL_3283CFD_122_CELLS.json`, source ANALYSIS sha 45d954bb..., bound by hash) and the current analysis computes it (see the gate table above). The seven current-host gains also occur in the pinned 3283cfd arm: they are host effects, not consolidation gains.
- Same-host, same-round comparisons attribute differences to the implementation layer; they do not establish universal dominance, scaling or unseen generalization (all 61 inputs are exposed).
- `main` is unchanged; promotion of the accepted default follows the `promotion_decision` gate and the review of this packet.

## STEP2_SUPPLEMENT_1 (the changed public runtime on the full suite; original run immutable)

| gate | decision |
|---|---|
| validity | PASS |
| completeness | PASS (245/245) |
| preservation_vs_original PGM_ACCEPTED | PASS (target 45, supplement 45, lost none, gained none) |
| preservation_vs_original PGM_EXPERIMENTAL | PASS (target 54, supplement 54, lost none, gained none) |
| replay_cells | PASS |
| supplement_decision | PASS |

Charged 1626 s of the declared 4,900 s; records under `supplement/`. Wall times of different run periods are descriptive only.
