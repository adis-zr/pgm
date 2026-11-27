# External benchmark of the accepted engine

Main `7f28259a4869a2c684d506b51072b04bb0ce4783`; accepted PGM v2.13.2, historical targeted schedule; Linux x86-64 host build. This report analyzes executed artifacts, not inferred historical timings.

Primary cells: 330/330. Extended cells: 20/20. Scored receipt charge: 2077.386 s of 8000 s.

## Coverage and timing

A task completes only when both fresh-process replicates complete within the wall contract. PGM completion carries its reported numerical/PAC guarantee; libDAI completion is point output. BP convergence does not certify epsilon accuracy.

| Cohort | Budget | Tasks | PGM | JT | BP points | BP converged | Mutual PGM/JT | Median JT/PGM time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| external_extension | 20 s | 9 | 7 | 3 | 9 | 8 | 2 | 0.490× |
| historical46 | 20 s | 46 | 22 | 25 | 46 | 43 | 15 | 0.072× |
| extended_confirmation | 120 s | 5 | 5 | 2 | — | — | 2 | 1.123× |

Ratios above one favor PGM. These are medians across task-specific ratios of the two-replicate wall-time medians, restricted to mutual completions; failures and one-sided completions are separately listed. Only two observations are available: individual ratios and time spreads remain visible, with no confidence interval or population claim. The extension is selected from known successes. The 120-second phase is an outcome-selected confirmation cohort, not a broad coverage estimate.

The historical46 cohort was reconstructed using the original selector. The complete original frozen input manifest was unavailable; this report does not claim that all46 historical input hashes were matched.

### external_extension (20 s)

PGM-only against JT: ObjectDetection_43, mastermind_03_08_04-0003, mastermind_03_08_05-0003, or_chain_186.fg, or_chain_209.fg. JT-only against PGM: DBN_14.
On mutual completions, PGM is faster on 0 and slower on 2 tasks.

Failure classes (cell counts, including both replicates):

- PGM: `{"COMPLETE": 14, "DEADLINE": 4}`. One-replicate-only tasks: none.
- LIBDAI_JT: `{"ADMISSION_REFUSED": 12, "COMPLETE": 6}`. One-replicate-only tasks: none.
- LIBDAI_BP: `{"COMPLETE": 18}`. One-replicate-only tasks: none.
### historical46 (20 s)

PGM-only against JT: BN_12, BN_15, BN_31, CSP_11, CSP_13, ObjectDetection_34, Promedus_37. JT-only against PGM: ANDES, CSP_12, DBN_11, Grids_11, Grids_14, Pedigree_11, Pedigree_12, Pedigree_13, Segmentation_12, Segmentation_13.
On mutual completions, PGM is faster on 1 and slower on 14 tasks.

Failure classes (cell counts, including both replicates):

- PGM: `{"COMPLETE": 44, "DEADLINE": 26, "DEADLINE_PARTIAL": 16, "NUMERIC_RANGE_REFUSED": 6}`. One-replicate-only tasks: none.
- LIBDAI_JT: `{"ADMISSION_REFUSED": 40, "COMPLETE": 50, "TIMEOUT": 2}`. One-replicate-only tasks: none.
- LIBDAI_BP: `{"COMPLETE": 92}`. One-replicate-only tasks: none.
### extended_confirmation (120 s)

PGM-only against JT: DBN_12, DBN_15, DBN_16. JT-only against PGM: none.
On mutual completions, PGM is faster on 1 and slower on 1 tasks.

Failure classes (cell counts, including both replicates):

- PGM: `{"COMPLETE": 10}`. One-replicate-only tasks: none.
- LIBDAI_JT: `{"ADMISSION_REFUSED": 6, "COMPLETE": 4}`. One-replicate-only tasks: none.

## The 20×–100× claim

- At least 20× in both matched replicates: measured none; censored lower bounds none.
- At least 100× in both matched replicates: measured none; censored lower bounds none.

A measured claim requires both JT and PGM to finish in both replicates. A censored claim uses the declared timeout divided by PGM elapsed time; memory admissions/refusals, memory kills and numeric failures never supply a speedup denominator. A result absent here does not disprove an older result under a different engine, host, route or contract. The original paired timing receipts were not recovered, so historical attribution remains separate.

Largest measured current-run speedups:

| Cohort | Task | Budget | PGM median s | JT median s | JT/PGM | Replicate1 | Replicate2 |
|---|---|---:|---:|---:|---:|---:|---:|
| historical46 | Promedus_12 | 20 | 0.3050 | 2.9669 | 9.729× | 10.177× | 9.248× |
| extended_confirmation | CSP_13 | 120 | 14.2047 | 26.9739 | 1.899× | 1.973× | 1.825× |
| external_extension | Alchemy_11 | 20 | 3.4651 | 2.8337 | 0.818× | 0.756× | 0.882× |
| historical46 | WATER | 20 | 0.3274 | 0.2216 | 0.677× | 0.771× | 0.582× |
| historical46 | ObjectDetection_56 | 20 | 13.6553 | 8.7164 | 0.638× | 0.639× | 0.637× |
| extended_confirmation | DBN_11 | 120 | 29.9591 | 10.3776 | 0.346× | 0.336× | 0.357× |
| external_extension | Promedus_36 | 20 | 0.3157 | 0.0512 | 0.162× | 0.207× | 0.128× |
| historical46 | BARLEY | 20 | 11.1255 | 1.7596 | 0.158× | 0.157× | 0.159× |
| historical46 | Promedus_33 | 20 | 0.2660 | 0.0249 | 0.094× | 0.092× | 0.095× |
| historical46 | ASIA | 20 | 0.1718 | 0.0150 | 0.087× | 0.087× | 0.087× |
| historical46 | ALARM | 20 | 0.1964 | 0.0147 | 0.075× | 0.077× | 0.073× |
| historical46 | MILDEW | 20 | 3.9843 | 0.2856 | 0.072× | 0.077× | 0.067× |
| historical46 | CHILD | 20 | 0.1771 | 0.0111 | 0.062× | 0.079× | 0.045× |
| historical46 | WIN95PTS | 20 | 0.3451 | 0.0151 | 0.044× | 0.044× | 0.043× |
| historical46 | HAILFINDER | 20 | 0.3545 | 0.0146 | 0.041× | 0.041× | 0.042× |

## Validation and accuracy diagnostics

Independent artifact review examined 75710 PGM published coordinates from 120 result files. Geometry/label/inventory/binding faults: 0; scoring disagreements with frozen cell records: 0. Largest published endpoint radius: 0.0049998549; largest complete-row point-sum deviation: 0.029626274. Point-sum deviation is descriptive: the accepted point contract is coordinatewise.
Same-input, same-replicate successful PGM/JT comparisons: 38, 24640 coordinates. JT points outside PGM enclosures after the explicit 5e-10 serialization allowance: 0.
BP/JT paired point comparisons: 56; 14 have all-coordinate difference at most epsilon plus the two serialized-point allowances. This is empirical agreement with a binary64 exact algorithm, not independently certified truth.
BP-to-PGM enclosure distances are also retained per cell in ANALYSIS.json. They give conditional error bounds if the PGM enclosures hold; PAC risk is per request and is not silently pooled across the campaign. Disjoint PGM replicate enclosures are listed separately.

Campaign validation issues: 0; missing expected cells: 0. See ANALYSIS.json for every issue and PAIRS.csv for all tasks, including losses.

## Interpretation

This measures the whole accepted automatic engine under one frozen policy. Successful exact structural routes and PAC routes are kept in the same end-to-end accounting. It can establish practical external coverage and speedups without establishing a universal smooth-runtime or instance-optimality theorem. It does not test the unintegrated heat-bath/DGP10 work or demonstrate a new general solution for dense frustrated models.

The API is Python with compiled native execution. Dependencies and compilation are setup costs, not steady-install call time. All parsing, planning, solving, recovery, serialization and cleanup are charged. The common outer cap is 3 GiB, with unchanged 2,560 MiB usable memory inside PGM and a 3 GiB JT forecast ceiling. Full raw outputs, receipt outcomes and source/binary/input identities are retained.
