# Step 2 external preservation regression (STEP2_AMENDMENT_1)

Engine `f74f7f3da84cade7ac2bc6776087790a0c698a73`; pinned references `7f28259` (PGM_REFERENCE) and `3283cfd` (PGM_EXPERIMENTAL_REF). Recorded 732/732 cells; charged 4130.2 s / 14640 s.

All 61 inputs are exposed regression inputs (old55 / former_eval6 are historical groups). One outer contract: 20 s, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6, two fresh-process repeats, serial execution.

## Gates

| gate | decision |
|---|---|
| validity | FAIL |
| completeness | PASS |
| historical_accepted_preservation | PASS |
| reference_reproduction | PASS |
| same_round_accepted_preservation | PASS |
| historical_experimental_preservation | NOT_EVALUABLE |
| same_round_experimental_preservation | PASS |
| paired_overhead | FLAGGED |
| promotion_decision | HOLD |

## Both-repeat completions

| group | inputs | PGM_REFERENCE | PGM_ACCEPTED | PGM_EXPERIMENTAL | PGM_EXPERIMENTAL_REF | LIBDAI_JT | LIBDAI_BP |
|---|---:|---:|---:|---:|---:|---:|---:|
| old55 | 55 | 39 | 39 | 48 | 48 | 25 | 54 |
| former_eval6 | 6 | 6 | 6 | 6 | 6 | 0 | 6 |
| all61 | 61 | 45 | 45 | 54 | 54 | 25 | 60 |

## Explicit pairs

- **same_round_accepted** (PGM_ACCEPTED vs PGM_REFERENCE): mutual 45; candidate-only none; comparator-only none; median wall ratio on mutual 1.09.
- **same_round_experimental** (PGM_EXPERIMENTAL vs PGM_EXPERIMENTAL_REF): mutual 54; candidate-only none; comparator-only none; median wall ratio on mutual 1.001.
- **accepted_vs_experimental** (PGM_ACCEPTED vs PGM_EXPERIMENTAL): mutual 45; candidate-only none; comparator-only ANDES, CSP_12, DBN_12, DBN_15, DBN_16, MUNIN1, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 0.996.
- **jt_vs_reference** (PGM_REFERENCE vs LIBDAI_JT): mutual 20; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only ANDES, CSP_12, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 3.065.
- **jt_vs_accepted** (PGM_ACCEPTED vs LIBDAI_JT): mutual 20; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only ANDES, CSP_12, Pedigree_11, Pedigree_12, Pedigree_13; median wall ratio on mutual 3.318.
- **jt_vs_experimental** (PGM_EXPERIMENTAL vs LIBDAI_JT): mutual 25; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only none; median wall ratio on mutual 1.336.
- **jt_vs_experimental_ref** (PGM_EXPERIMENTAL_REF vs LIBDAI_JT): mutual 25; candidate-only Alchemy_11, BN_12, BN_13, BN_15, BN_31, CSP_11, CSP_13, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_34, ObjectDetection_39, ObjectDetection_43, ObjectDetection_56, Promedus_18, blockmap_10_01-0009, fs-07, linkage_13, mastermind_03_08_04-0003, mastermind_03_08_05-0003, mastermind_05_08_03-0002, or_chain_186.fg, or_chain_188.fg, or_chain_209.fg; comparator-only none; median wall ratio on mutual 1.409.

## Historical accepted-engine completions (29 at 7f28259, 20 s)

- PGM_REFERENCE: retained 29/29; lost none; gained BN_13, DBN_11, DBN_14, Grids_11, Grids_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_ACCEPTED: retained 29/29; lost none; gained BN_13, DBN_11, DBN_14, Grids_11, Grids_14, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_EXPERIMENTAL: retained 29/29; lost none; gained ANDES, BN_13, CSP_12, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, Grids_11, Grids_14, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Pedigree_11, Pedigree_12, Pedigree_13, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.
- PGM_EXPERIMENTAL_REF: retained 29/29; lost none; gained ANDES, BN_13, CSP_12, DBN_11, DBN_12, DBN_14, DBN_15, DBN_16, Grids_11, Grids_14, MUNIN1, ObjectDetection_24, ObjectDetection_30, ObjectDetection_39, Pedigree_11, Pedigree_12, Pedigree_13, Promedus_18, Segmentation_12, Segmentation_13, blockmap_10_01-0009, fs-07, linkage_13, mastermind_05_08_03-0002, or_chain_188.fg; one-repeat-only none.

## Paired overhead (PGM_ACCEPTED / PGM_REFERENCE on same-round mutual completions)

| task | group | accepted walls | reference walls | ratios | differences s |
|---|---|---|---|---|---|
| BN_12 | old55 | [6.905, 6.898] | [6.207, 6.208] | [1.112, 1.111] | [0.698, 0.69] |
| BN_13 | old55 | [10.645, 10.6] | [9.892, 9.88] | [1.076, 1.073] | [0.753, 0.72] |
| BN_15 | old55 | [7.595, 7.614] | [7.454, 7.474] | [1.019, 1.019] | [0.141, 0.14] |
| BN_31 | old55 | [0.543, 0.509] | [0.282, 0.281] | [1.928, 1.809] | [0.262, 0.227] |
| Grids_11 | old55 | [8.152, 8.166] | [7.932, 7.831] | [1.028, 1.043] | [0.22, 0.336] |
| Grids_14 | old55 | [10.286, 10.293] | [10.003, 9.915] | [1.028, 1.038] | [0.283, 0.379] |
| Promedus_33 | old55 | [0.316, 0.351] | [0.143, 0.143] | [2.213, 2.452] | [0.173, 0.208] |
| Promedus_12 | old55 | [0.364, 0.353] | [0.159, 0.163] | [2.283, 2.168] | [0.204, 0.19] |
| Promedus_37 | old55 | [0.464, 0.477] | [0.26, 0.261] | [1.781, 1.825] | [0.203, 0.215] |
| CSP_11 | old55 | [4.461, 4.477] | [4.29, 4.284] | [1.04, 1.045] | [0.171, 0.193] |
| CSP_13 | old55 | [6.361, 5.871] | [6.16, 5.639] | [1.033, 1.041] | [0.2, 0.233] |
| DBN_11 | old55 | [10.395, 10.214] | [10.131, 10.833] | [1.026, 0.943] | [0.264, -0.619] |
| ObjectDetection_34 | old55 | [5.755, 5.74] | [5.423, 5.416] | [1.061, 1.06] | [0.332, 0.324] |
| ObjectDetection_56 | old55 | [5.802, 5.769] | [5.639, 5.444] | [1.029, 1.06] | [0.163, 0.325] |
| ObjectDetection_39 | old55 | [7.439, 7.429] | [7.184, 6.617] | [1.035, 1.123] | [0.255, 0.812] |
| ObjectDetection_24 | old55 | [11.455, 11.428] | [11.229, 10.63] | [1.02, 1.075] | [0.226, 0.798] |
| Segmentation_11 | old55 | [5.546, 5.56] | [5.294, 5.284] | [1.048, 1.052] | [0.252, 0.276] |
| Segmentation_12 | old55 | [9.777, 9.758] | [9.434, 9.409] | [1.036, 1.037] | [0.343, 0.349] |
| Segmentation_16 | old55 | [8.05, 7.872] | [7.619, 7.561] | [1.057, 1.041] | [0.432, 0.312] |
| Segmentation_13 | old55 | [11.472, 11.406] | [11.101, 11.091] | [1.033, 1.028] | [0.371, 0.315] |
| ASIA | old55 | [0.259, 0.232] | [0.123, 0.113] | [2.111, 2.045] | [0.136, 0.118] |
| CHILD | old55 | [0.256, 0.245] | [0.123, 0.115] | [2.084, 2.12] | [0.133, 0.129] |
| INSURANCE | old55 | [0.394, 0.348] | [0.22, 0.225] | [1.795, 1.546] | [0.175, 0.123] |
| WATER | old55 | [0.356, 0.375] | [0.203, 0.201] | [1.758, 1.865] | [0.154, 0.174] |
| MILDEW | old55 | [3.349, 3.368] | [2.514, 2.498] | [1.332, 1.348] | [0.835, 0.87] |
| ALARM | old55 | [0.259, 0.275] | [0.121, 0.117] | [2.136, 2.339] | [0.138, 0.157] |
| BARLEY | old55 | [6.086, 6.077] | [5.66, 5.661] | [1.075, 1.074] | [0.426, 0.417] |
| HAILFINDER | old55 | [0.369, 0.36] | [0.204, 0.22] | [1.808, 1.639] | [0.165, 0.14] |
| WIN95PTS | old55 | [0.369, 0.345] | [0.203, 0.2] | [1.822, 1.721] | [0.166, 0.144] |
| DIABETES | old55 | [12.923, 12.816] | [11.805, 11.799] | [1.095, 1.086] | [1.118, 1.017] |
| Alchemy_11 | old55 | [1.686, 1.689] | [1.468, 1.475] | [1.148, 1.145] | [0.218, 0.214] |
| DBN_14 | old55 | [10.421, 10.963] | [10.037, 10.111] | [1.038, 1.084] | [0.385, 0.852] |
| mastermind_03_08_04-0003 | old55 | [1.308, 1.318] | [1.006, 1.012] | [1.299, 1.302] | [0.301, 0.306] |
| ObjectDetection_43 | old55 | [6.321, 6.311] | [6.074, 6.103] | [1.041, 1.034] | [0.246, 0.208] |
| mastermind_03_08_05-0003 | old55 | [2.008, 1.987] | [1.6, 1.568] | [1.255, 1.267] | [0.408, 0.419] |
| or_chain_186.fg | old55 | [0.913, 0.907] | [0.691, 0.68] | [1.321, 1.334] | [0.222, 0.227] |
| or_chain_209.fg | old55 | [3.031, 3.019] | [2.768, 2.783] | [1.095, 1.085] | [0.264, 0.236] |
| linkage_13 | old55 | [8.639, 8.711] | [8.227, 8.25] | [1.05, 1.056] | [0.412, 0.461] |
| Promedus_36 | old55 | [0.326, 0.355] | [0.161, 0.16] | [2.026, 2.214] | [0.165, 0.195] |
| ObjectDetection_30 | former_eval6 | [5.745, 5.749] | [5.641, 5.546] | [1.018, 1.037] | [0.104, 0.204] |
| Promedus_18 | former_eval6 | [0.453, 0.461] | [0.298, 0.302] | [1.524, 1.527] | [0.156, 0.159] |
| blockmap_10_01-0009 | former_eval6 | [0.802, 0.808] | [0.339, 0.338] | [2.365, 2.392] | [0.463, 0.47] |
| fs-07 | former_eval6 | [6.335, 6.301] | [6.154, 6.143] | [1.029, 1.026] | [0.181, 0.158] |
| mastermind_05_08_03-0002 | former_eval6 | [2.254, 2.263] | [1.957, 1.942] | [1.152, 1.165] | [0.297, 0.321] |
| or_chain_188.fg | former_eval6 | [9.219, 9.26] | [8.789, 8.773] | [1.049, 1.056] | [0.43, 0.487] |

Cost flags (a task is FLAGGED when PGM_ACCEPTED is slower than PGM_REFERENCE in BOTH repeats by more than 1.25x AND more than 0.1 s (paired, same-round mutual completions)): BN_31, Promedus_33, Promedus_12, Promedus_37, ASIA, CHILD, INSURANCE, WATER, MILDEW, ALARM, HAILFINDER, WIN95PTS, mastermind_03_08_04-0003, mastermind_03_08_05-0003, or_chain_186.fg, Promedus_36, Promedus_18, blockmap_10_01-0009.

Independent checks: 1 identity / scoring issues; 16 faulty artifacts; 468324 published coordinate instances; max endpoint radius 5.000e-03; JT containment checked on 180 (arm, task, repeat) outputs incl. partial ones with 0 excluded coordinates; deterministic conflicts 0; PAC conflicts 0.

Historical experimental preservation (the 47-task 3283cfd portfolio set) is NOT EVALUABLE without the hashed extract of the scored 3283cfd cells; the same-round pinned 3283cfd arm is the executed experimental comparator. This campaign measures preservation on exposed inputs; it establishes no universal dominance, scaling or unseen generalization claim.
