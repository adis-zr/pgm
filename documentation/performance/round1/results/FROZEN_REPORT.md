# Untuned runtime performance — exposed external regression

Validity: **FAIL**. Completeness: **PASS**. 732/732 cells; 4595.728 supervised seconds.

| Arm | Both-repeat completions | One-repeat only |
|---|---:|---:|
| BASE_ACCEPTED | 40 | 0 |
| PGM_ACCEPTED | 40 | 0 |
| BASE_EXPERIMENTAL | 48 | 2 |
| PGM_AUTOMATIC | 50 | 1 |
| LIBDAI_JT | 32 | 1 |
| LIBDAI_BP | 61 | 0 |

Same-host preservation:

- accepted: **PASS**, baseline 40, candidate 40; losses []; gains [].
- automatic: **FAIL**, baseline 51, candidate 50; losses ['DIABETES', 'ObjectDetection_39']; gains ['Pedigree_12'].

| Comparison | Mutual tasks | Median candidate/comparator wall | Faster in both repeats | Slower in both repeats | Confirmed cost flags |
|---|---:|---:|---:|---:|---:|
| accepted_preservation | 40 | 0.987 | 16 | 4 | 0 |
| automatic_vs_experimental | 48 | 0.994 | 19 | 12 | 0 |
| automatic_vs_accepted | 38 | 1.022 | 15 | 19 | 8 |
| accepted_vs_jt | 24 | 12.098 | 4 | 20 | 19 |
| automatic_vs_jt | 31 | 6.460 | 7 | 22 | 21 |
| accepted_vs_bp_points | 40 | 47.906 | 0 | 40 | 40 |
| automatic_vs_bp_points | 50 | 43.666 | 1 | 49 | 49 |

Historical completion targets (separate host):

- accepted: retained 40/45; candidate losses ['DBN_11', 'DBN_14', 'ObjectDetection_24', 'Segmentation_13', 'linkage_13']; same-host baseline historical losses ['DBN_11', 'DBN_14', 'ObjectDetection_24', 'Segmentation_13', 'linkage_13'].
- experimental: retained 50/54; candidate losses ['DIABETES', 'ObjectDetection_24', 'ObjectDetection_39', 'linkage_13']; same-host baseline historical losses ['BN_13', 'DIABETES', 'ObjectDetection_24', 'ObjectDetection_39', 'Pedigree_12', 'linkage_13'].

Published coordinate instances: 421809; JT comparisons: 165660; exclusions after allowance: 0; deterministic conflicts: 0.

Limitations:

- All 61 tasks are exposed regression inputs; none is an unseen evaluation.
- JT agreement is numerical agreement with a 5e-10 serialization allowance, not an independent proof of every large marginal.
- BP output and convergence do not certify epsilon accuracy.
- Timeouts and missing outputs are censored; no speed ratio uses a failed task.
- Size-group comparisons are descriptive on mutual completions, not a scaling theorem.
- Phase timings are diagnostic and not necessarily disjoint; end-to-end supervised wall is authoritative.

Validation issues:

- Raw artifact or contract faults
