# Secondary external test: current research switchboard

The existing DGP9 INCUMBENT configuration on main `7f28259a4869a2c684d506b51072b04bb0ce4783` was tested separately after the primary campaign. The accepted default remains v2.13.2. This follow-up was selected after early primary outcomes; it is not a retrospectively added primary arm.

Recorded secondary cells: 110/110; shared scored charge across primary, extended and secondary: 3254.506 / 8000 s. Qualification: 9 controls, pass=True.

All 55 inputs and both replicates use the fixed existing configuration. No benchmark-specific route, rate or engine change was made. The historical46 panel was reconstructed from its selector; a complete old frozen hash manifest was unavailable, so this is not a claim that every historical byte binding has been recovered.

## Coverage

| Cohort | Inputs | Accepted PGM | Research UNIFIED | JT | UNIFIED gains over PGM | UNIFIED losses to PGM |
|---|---:|---:|---:|---:|---:|---:|
| external_extension | 9 | 7 | 5 | 3 | 0 | 2 |
| historical46 | 46 | 22 | 27 | 25 | 7 | 2 |

Every count requires completion in both replicates. PGM/UNIFIED certificates and JT point outputs remain distinct guarantees. The nine extension inputs are previously exposed successes, not holdouts.

### external_extension

Gains over accepted PGM: none. Losses to accepted PGM: ObjectDetection_43, mastermind_03_08_04-0003.
UNIFIED-only against JT: mastermind_03_08_05-0003, or_chain_186.fg, or_chain_209.fg. JT-only against UNIFIED: DBN_14.
Incomplete replicate agreement: {"LIBDAI_BP": [], "LIBDAI_JT": [], "PGM": [], "UNIFIED": []}.
Post hoc coverage diagnostic: UNIFIED covers 5 of 8 tasks in the PGM/JT union. This union is not an implemented arm or a performance claim.

### historical46

Gains over accepted PGM: ANDES, CSP_12, Grids_11, Grids_14, Pedigree_12, Segmentation_12, Segmentation_13. Losses to accepted PGM: BN_31, CSP_13.
UNIFIED-only against JT: BN_12, BN_15, CSP_11, ObjectDetection_34, Promedus_37. JT-only against UNIFIED: DBN_11, Pedigree_11, Pedigree_13.
Incomplete replicate agreement: {"LIBDAI_BP": [], "LIBDAI_JT": [], "PGM": [], "UNIFIED": []}.
Post hoc coverage diagnostic: UNIFIED covers 27 of 32 tasks in the PGM/JT union. This union is not an implemented arm or a performance claim.

## Timing and the large-speedup claim

UNIFIED ran in a later phase. Its timing comparisons with primary PGM/JT reuse same-host, same-input results but are not interleaved paired trials. Each table row reports both replicate ratios; there are only two observations, with no confidence interval or population claim. Replicate drift must remain visible.

| Cohort | Task | Comparator | Median comparator / UNIFIED | Replicate 1 | Replicate 2 | UNIFIED time spread | Comparator time spread |
|---|---|---|---:|---:|---:|---:|---:|
| historical46 | Promedus_12 | LIBDAI_JT | 10.808× | 10.772× | 10.851× | 1.189× | 1.180× |
| external_extension | Alchemy_11 | LIBDAI_JT | 1.061× | 1.049× | 1.072× | 1.108× | 1.133× |
| historical46 | ObjectDetection_56 | LIBDAI_JT | 0.850× | 0.894× | 0.809× | 1.078× | 1.024× |
| historical46 | CSP_12 | LIBDAI_JT | 0.333× | 0.352× | 0.314× | 1.064× | 1.194× |
| historical46 | BARLEY | LIBDAI_JT | 0.295× | 0.288× | 0.302× | 1.012× | 1.039× |
| historical46 | Grids_11 | LIBDAI_JT | 0.221× | 0.168× | 0.275× | 1.011× | 1.623× |
| external_extension | Promedus_36 | LIBDAI_JT | 0.206× | 0.229× | 0.183× | 1.020× | 1.224× |
| historical46 | Grids_14 | LIBDAI_JT | 0.150× | 0.158× | 0.142× | 1.063× | 1.176× |
| historical46 | DIABETES | LIBDAI_JT | 0.144× | 0.152× | 0.135× | 1.025× | 1.099× |
| historical46 | WATER | LIBDAI_JT | 0.131× | 0.151× | 0.111× | 1.021× | 1.331× |
| historical46 | ANDES | LIBDAI_JT | 0.130× | 0.105× | 0.155× | 1.014× | 1.456× |
| historical46 | Promedus_33 | LIBDAI_JT | 0.091× | 0.094× | 0.087× | 1.138× | 1.049× |
| historical46 | ASIA | LIBDAI_JT | 0.081× | 0.088× | 0.075× | 1.182× | 1.002× |
| historical46 | ALARM | LIBDAI_JT | 0.069× | 0.072× | 0.066× | 1.004× | 1.089× |
| historical46 | MILDEW | LIBDAI_JT | 0.062× | 0.067× | 0.057× | 1.008× | 1.159× |
| historical46 | INSURANCE | LIBDAI_JT | 0.056× | 0.056× | 0.056× | 1.120× | 1.118× |
| historical46 | HAILFINDER | LIBDAI_JT | 0.056× | 0.055× | 0.056× | 1.018× | 1.052× |
| historical46 | CHILD | LIBDAI_JT | 0.053× | 0.068× | 0.038× | 1.035× | 1.842× |
| historical46 | Segmentation_11 | LIBDAI_JT | 0.050× | 0.040× | 0.060× | 1.034× | 1.454× |
| historical46 | Pedigree_12 | LIBDAI_JT | 0.047× | 0.058× | 0.035× | 1.023× | 1.713× |

Time spread is maximum/minimum elapsed time across the two replicates. Ratios above one favor UNIFIED. All pairs, including losses and missing results, appear in SECONDARY_PAIRS.csv.

- At least 20× against JT in **both** replicate comparisons: measured none; timeout-only lower bounds none.
- At least 100× against JT in **both** replicate comparisons: measured none; timeout-only lower bounds none.

A ratio of medians alone never establishes the threshold. Memory forecast refusals and memory kills have no speedup denominator. Censored bounds use the 20-second timeout, not cleanup overrun. These fresh results cannot establish or refute a historical 20×–100× comparison whose original paired receipts and exact execution policy have not been recovered.

Confirmed overhead versus accepted PGM (both replicates above 1.25× and +0.1 s): mastermind_03_08_05-0003, WATER.

## Validity and route evidence

Independent artifact recheck: 0 issues; 0 missing expected cells. Published coordinates examined: 62004; result files with validation faults: 0; largest endpoint radius: 0.005.
Original-coordinate interval disagreements against accepted PGM: 0, of which 0 compare two deterministic enclosures. JT points outside UNIFIED intervals after 5e-10 serialization allowance: 0.
Largest point deviation versus PGM: 0.0044218214; versus JT: 3.5695982e-09. These are solver-agreement diagnostics, not independent exact-error measurements. PAC confidence remains per request.

Successful-cell representation counts: `{"approx(identity)": 2, "identity": 40, "layered_contraction": 2, "no_named_native_representation": 8, "refine1(identity)": 2, "refine2(identity)": 2, "signed_evidence_expansion": 12}`. Successful-cell guarantee counts: `{"DETERMINISTIC": 56, "EXACT": 2, "PAC": 6}`.

## Interpretation

This follow-up distinguishes the accepted block-contraction/PAC entrypoint from the research planner that explicitly prices native identity and quotient solves. A gain can establish a dispatch or representation advantage already present on main; it does not turn the research arm into the accepted default or establish a general dense-cyclic inference result. A regression remains visible even if the hindsight union would hide it. The full primary comparison is preserved in REPORT.md.
