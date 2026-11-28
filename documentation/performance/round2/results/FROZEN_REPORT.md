# Untuned runtime performance — exposed external regression

Validity: **PASS**. Completeness: **PASS**. 732/732 cells; 4543.441 supervised seconds.

| Arm | Both-repeat completions | One-repeat only |
|---|---:|---:|
| BASE_ACCEPTED | 40 | 0 |
| PGM_ACCEPTED | 40 | 0 |
| BASE_EXPERIMENTAL | 49 | 1 |
| PGM_AUTOMATIC | 52 | 0 |
| LIBDAI_JT | 31 | 3 |
| LIBDAI_BP | 61 | 0 |

Same-host preservation:

- accepted: **PASS**, baseline 40, candidate 40; losses []; gains [].
- automatic: **PASS**, baseline 51, candidate 52; losses []; gains ['Pedigree_12'].

| Comparison | Mutual tasks | Median candidate/comparator wall | Faster in both repeats | Slower in both repeats | Confirmed cost flags |
|---|---:|---:|---:|---:|---:|
| accepted_preservation | 40 | 0.987 | 12 | 4 | 0 |
| automatic_vs_experimental | 49 | 0.981 | 27 | 8 | 0 |
| automatic_vs_accepted | 40 | 0.999 | 18 | 16 | 5 |
| accepted_vs_jt | 23 | 12.696 | 3 | 20 | 19 |
| automatic_vs_jt | 31 | 8.389 | 6 | 22 | 22 |
| accepted_vs_bp_points | 40 | 46.960 | 0 | 40 | 40 |
| automatic_vs_bp_points | 52 | 46.346 | 1 | 51 | 51 |

Historical completion targets (separate host):

- accepted: retained 40/45; candidate losses ['DBN_11', 'DBN_14', 'ObjectDetection_24', 'Segmentation_13', 'linkage_13']; same-host baseline historical losses ['DBN_11', 'DBN_14', 'ObjectDetection_24', 'Segmentation_13', 'linkage_13'].
- experimental: retained 52/54; candidate losses ['ObjectDetection_24', 'linkage_13']; same-host baseline historical losses ['DIABETES', 'ObjectDetection_24', 'ObjectDetection_39', 'Pedigree_12', 'linkage_13'].

Release gates:

| Gate | Decision |
|---|---|
| strict_validity | PASS |
| full_matrix | PASS |
| accepted_preservation | PASS |
| automatic_union_preservation | PASS |
| previous_automatic50 | PASS |
| accepted_preservation_cost | PASS |
| automatic_vs_experimental_cost | PASS |

Release: **ELIGIBLE**. Previous automatic target: 50/50 retained; losses [].

Censored resource-killed comparator outputs: 5. Typed late empty deadline refusals: 1. Both are nonanswers; neither contributes a completion or latency ratio.

Partial-coordinate diagnostics:

- accepted_preservation: 0 gained and 0 lost coordinate instances across 42 cells with at least one incomplete arm. Separate from completion preservation.
- automatic_vs_experimental: 11716 gained and 15 lost coordinate instances across 23 cells with at least one incomplete arm. Separate from completion preservation.
- automatic_vs_accepted: 9208 gained and 0 lost coordinate instances across 42 cells with at least one incomplete arm. Separate from completion preservation.

Published coordinate instances: 424891; JT comparisons: 165996; exclusions after allowance: 0; deterministic conflicts: 0.

Limitations:

- All 61 tasks are exposed regression inputs; none is an unseen evaluation.
- JT agreement is numerical agreement with a 5e-10 serialization allowance, not an independent proof of every large marginal.
- BP output and convergence do not certify epsilon accuracy.
- Timeouts and missing outputs are censored; no speed ratio uses a failed task.
- Size-group comparisons are descriptive on mutual completions, not a scaling theorem.
- Phase timings are diagnostic and not necessarily disjoint; end-to-end supervised wall is authoritative.
