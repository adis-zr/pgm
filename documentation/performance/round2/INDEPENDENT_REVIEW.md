# Independent performance round 2 review

Recommendation: **ELIGIBLE opt-in implementation; default promotion separate**.

Frozen engine `f14d407f50024ee29c5e8ae6bad52705bc01ec4e`; 732 unique cells and receipts; 4543.441443 charged seconds.
Checked 488 PGM result files and 424891 published coordinate instances. Errors: 0; deterministic conflicts: 0; PAC conflicts (diagnostic): 0; JT exclusions: 0 across 165996 comparisons.

| Gate | Independent result |
|---|---|
| validity | PASS |
| complete_matrix | PASS |
| accepted_preservation | PASS |
| automatic_union_preservation | PASS |
| previous_automatic50 | PASS |
| accepted_cost | PASS |
| automatic_cost | PASS |

| Arm | Both-repeat completions |
|---|---:|
| BASE_ACCEPTED | 40 |
| PGM_ACCEPTED | 40 |
| BASE_EXPERIMENTAL | 49 |
| PGM_AUTOMATIC | 52 |
| LIBDAI_JT | 31 |
| LIBDAI_BP | 61 |

Automatic retains union 51 and prior50; union gains: ['Pedigree_12'].
Automatic/JT median latency ratio: 8.389125; mutual tasks 31; faster both 6; slower both 22.
Automatic/accepted confirmed cost flags: ['BARLEY', 'BN_31', 'CSP_13', 'MILDEW', 'Promedus_37'].
Partial coordinates lost versus same-round experimental: 15; 1qt9 prior automatic comparison: [{'task': '1qt9', 'replicate': 1, 'previous_published': 15, 'current_published': 0}, {'task': '1qt9', 'replicate': 2, 'previous_published': 15, 'current_published': 0}].
Censored comparator results: 5. Typed late empty deadline refusals: [{'job': '1aie__BASE_EXPERIMENTAL__r1', 'wall_s': 19.530538330000127, 'outer_wall_s': 19.650858465000056}].

Caveats:

- All 61 tasks are exposed; no unseen generalization claim.
- Same-host completion preservation is empirical, not a universal preservation guarantee.
- Automatic has cost regressions against accepted even when its matched experimental comparison passes.
- JT comparison is numerical agreement within 5e-10, not a proof of every large marginal.
- Broad latency dominance over libDAI is not established; BP is an uncertified point comparator.
- Observed 1qt9 partial answers are lost despite passing completion preservation.
- Raw geometry and receipt validation do not independently reprove the algorithms or PAC theorems.
