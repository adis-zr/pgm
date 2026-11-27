# Independent DGP10 evidence review

Scope: the supplied frozen source archive, raw DGP10 cell/result files, manifests, receipts, freeze and declared gates. No benchmark or inference stream was rerun. The audit independently reconstructs answer geometry, query inventories, completion counts and radius summaries; it does not independently prove the Markov concentration theorem or every runtime path.

**Evidence verdict: retain the response-accuracy and completion results, with a correction to the moment diagnostic and explicit qualifications on novelty, cost and preservation.** The mechanism has a real measured gain on its admitted dense synthetic families. It has not yet been tested as a preserving general switchboard or against libDAI.

## Verified from the raw artifacts

The archive hashes match the supplied identity records. All frozen arm-file hashes match the supplied code. Every recorded launch/completion arm identity agrees with that freeze, including cells launched from harness-amendment commits. The independent audit found **174 cells**:

| Phase | INCUMBENT_R complete / cells | HB_R complete / cells | RESPONSE complete / cells |
|---|---:|---:|---:|
| Exposed main | 4/24 | 4/24 | 13/24 |
| Fresh | 2/14 | 1/14 | 4/14 |
| Preservation 24 | 24/24 | — | — |
| Preservation 18 | 18/18 | — | — |
| Preservation 13 | 13/13 | — | — |

Five additional RESPONSE_SCREEN development cells account for the remaining cells. The preservation cohorts can overlap; their cell counts are not a claim of 55 distinct models.

The audit parsed the shipped UAI model/evidence files and checked the original nonobserved coordinate inventory. It examined **35,372 published coordinate instances**: 32,428 incumbent, 640 HB_R and 2,304 RESPONSE. Exact Fraction checks found zero endpoint-order, endpoint-radius, exact-label, simplex-box, inventory, count or publication-deadline-flag faults. All archived radius summaries agree with a recount over the full original query inventory. Maximum published endpoint radius is 0.005. Thirty-three response risk records declare totals no greater than the requested delta. These are consistency checks, not an empirical proof of a one-in-a-million probability event or truth containment on non-enumerable models.

The four principal partial-accuracy comparisons are reproduced exactly:

| Anchor / seed | HB_R worst radius | RESPONSE worst radius | RESPONSE / HB_R |
|---|---:|---:|---:|
| n64 card4 ER / 0 | 0.0259457410 | 0.0062479708 | 0.240809 |
| n64 card4 ER / 1 | 0.0258912806 | 0.0072545978 | 0.280195 |
| n64 card4 clique / 0 | 0.0560161161 | 0.0197545612 | 0.352659 |
| n64 card4 clique / 1 | 0.0559790188 | 0.0197654609 | 0.353087 |

Thus the frozen twofold partial-accuracy gate passes on both anchors in both seeds. The wider-than-epsilon confidence enclosures are informative partial results, not completed epsilon answers.

## E1 — Incorrect units in the moment-inflation diagnostic (repaired)

`code/cex/hp/dgp10_analyze.py`, originally line 77, divides physical moment bound `U` by `y_max`, but `y_max` is a sample statistic for the normalized observable `Y/B`. The intended physical inflation is

`U / (B * y_max)`.

The faulty ratio understates inflation by B: B=1/4 on binary models and B=9/16 on the tested card4 models. This is an analysis-only error: the inference implementation's moment bound and its checked mean radius already use physical U.

The live consolidation analyzer now obtains B from the raw result rather than guessing from cardinality, computes the physical ratio, and reports the diagnostic unavailable when B is absent. Four regression tests fail on the prior analyzer and pass after the repair. They cover binary conversion, card4 bottleneck classification, missing scale and propagation of B from raw results.

The separately written `CORRECTED_DIAGNOSTICS.json` changes 28 ratios. Two classification labels change under the analyzer's own existing rule:

| Cell | Archived inflation | Corrected inflation | Archived label | Corrected label |
|---|---:|---:|---|---|
| exposed n64 card4 clique, seed0 | 1.698117 | 3.018874 | gap | moment_conservatism |
| exposed n64 card4 clique, seed1 | 1.696307 | 3.015657 | gap | moment_conservatism |

For context, binary ER seed0 changes from 0.263715 to 1.054861; card4 ER seed0 changes from 0.957729 to 1.702629. These ratios compare a checked population bound with an empirical upper statistic; they do not measure true population slack exactly. The bottleneck labels are diagnostics, not impossibility proofs.

No certificate, published answer, radius, completion gate or scored cell changes. All 1,855 original record files were hashed before and after the correction and remain identical. The corrected diagnostic must accompany the next theory discussion; an assertion that only the gap limits the exposed card4 clique is not supported by the corrected analysis.

## E2 — The 0.97 cost median mixes two different comparators

The nine cost observations consist of five RESPONSE/HB_R pairs and four RESPONSE/INCUMBENT_R pairs. These are seed-cells, not nine distinct models. The respective medians are:

- RESPONSE / HB_R: **0.969933**, on five cells, both routes generally sampling until their respective stopping times.
- RESPONSE / INCUMBENT_R: **1.585390**, on four cells, range **1.512187–1.627095**. Every one meets the overhead flag.

The pooled 0.97 median is arithmetically correct but is not evidence that the new route is cost-neutral relative to the incumbent. The report's detailed rows expose this; future summaries should keep the comparator populations separate. No benchmark rerun is needed to make that distinction.

## E3 — Completion novelty and preservation need their stated comparator

RESPONSE completes six main inputs and two fresh inputs in both seeds. INCUMBENT_R completes two main inputs and one fresh input. HB_R completes two main inputs in both seeds and no fresh input in both seeds.

The six reported binary gains are gains relative to incumbent failures. One of those, `dg_n64_c2_er50_half__eval9`, had already completed both seeds under DGP9 HB_REVISED; it is preservation plus tighter accuracy, not a first project completion. Two ER inputs are also completed in both seeds by same-round HB_R. The four remaining both-seed gains over same-round HB_R are the three binary clique inputs and the fresh binary ER input.

The preservation counts 24/24, 18/18 and 13/13 concern **INCUMBENT_R only**. RESPONSE preserves the three archived successful HB seed-cells and improves the exposed passing n32 cases, but refuses the fresh n32 card4 ER in both seeds while INCUMBENT_R completes it. This is not an undisclosed failure—the fresh table lists it—but it prevents treating standalone RESPONSE as a preserving replacement. SELECT was not implemented or scored.

## Exposure and generalization

The source freeze is timestamped 08:14:00Z; the fresh input generation record is 08:14:02Z. The seven fresh inputs have their own hashes, generator tag and seed rule, and are reported separately from twelve exposed inputs. RESPONSE rates were frozen at 08:24:09Z from five exposed screen runs before scored main/fresh cells. The historical `__eval9` inputs are properly labelled exposed in DGP10.

This supports a limited fresh-within-generator generalization claim. It is not an unseen external benchmark result. All DGP10 inputs are now exposed for later development; their filenames containing `eval` do not make them future holdouts. The next consolidation performance campaign should use the external suite with declared exposed regression and unseen-evaluation partitions, and keep these synthetic inputs as mathematical/correctness controls.

## Receipt and packaging scope

All 174 scored/screen cells have matching terminal receipts. The shipped ledger contains 316 unique terminal receipt IDs and 2,867.870 seconds through packaging. The external closure declares the final 327 receipts and 2,936.406 seconds, adding the final packaging completion and post-archive validation/restore work. The attachment carries hashes and summary entries for post-archive files rather than all those final file bytes, so this review independently confirms the scored-cell receipts and shipped ledger, while treating the external final closure as an attested continuation. Both figures remain below the declared 6,000-second ceiling.

The stale earlier archive identity embedded in START_HERE is superseded by the supplied external identity/closure manifests; it does not alter any scored inference result. No further closeout-only experiment is warranted on that basis.

## Files produced by this review

- `audit_evidence.py`, `EVIDENCE_AUDIT.json`: independent raw recount; zero faults after applying the declared nonobserved-variable query contract.
- `MOMENT_DIAGNOSTIC_CORRECTION.json`: independent physical-unit correction for all 28 executed scored response groups.
- `recompute_diagnostics.py`, `CORRECTED_DIAGNOSTICS.json`, `CORRECTION_VALIDATION.json`: correction through the repaired analyzer, separately labelled, with archived-file immutability check.
- `ANALYSIS_UNITS_BEFORE.txt`, `ANALYSIS_UNITS_AFTER.txt`: focused regression receipts.
- Live source changes: `pgm-consolidation/code/cex/hp/dgp10_analyze.py` and `pgm-consolidation/tests/test_dgp10_analysis_units.py`.

The positive scientific result survives these qualifications. The appropriate next action is consolidation of a useful certified response backend under a preserving selector, not another round claiming generic inference progress from these synthetic results alone.
