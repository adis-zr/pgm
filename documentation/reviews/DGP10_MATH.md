# DGP10 mathematical and proof-to-code review

Reviewed the attached frozen implementation `13c43024d671b36a6d9262583bfbdaf9762183d8`, its normative theory note, `PROOF_TO_CODE.md`, response arithmetic checker, observer, spectral witness, and publication path. The attached code and scored records were not edited. A small publication-contract repair was separately applied to the current consolidation checkout at the parent's request.

## Verdict

The response-construction mathematics is coherent under the stated positive-model, checked-gap and exact-chain assumptions. I did not find a counterexample to the selected-site gap, finite-time two-state certificate, or the reuse of the same observations for the upper moment and the mean. The mechanism gains can be retained, subject to the independent record/resource reviews. This is not a fresh proof of every inherited spectral-gap lemma, a formal verification of the library, or a rerun of the campaign.

One reproducible production-contract mismatch was found: conflicted raw/response boxes could still publish their raw points. It does not establish an incorrect archived marginal or invalidate the raw certificate's separately budgeted event. It should be repaired before the route is exposed through the consolidated public API.

## Mathematical checks

1. **Response identity.** Uniform random scan satisfies `(I-P)(n f_ia)=f_ia-Pi_i f_ia`; the conditional response therefore has the original marginal as its stationary mean. Observing only selected sites is legitimate because every committed selected-site update is recorded, including null moves and exact fallbacks. The local clock is part of the theorem, rather than an iid approximation.

2. **Selected-site gap.** On outside-coordinate functions the trace kernel is `p Q (A+pQ)^-1 Q`, with `p=1/n`, `A=I-P`. On the centered subspace, `A >= gI`, inverse operator monotonicity and compression give `K <= p/(g+p) I`. This produces the exact rational lower gap `eta=ng/(1+ng)` used by `response_certificate.eta_lower`. Reversibility and PSD follow from the compressed positive inverse.

3. **Finite-time MGF.** The proof uses spectral domination for a single tilted operator and then its norm; it does not incorrectly raise a Loewner inequality to a matrix power. The stationary endpoint vector contributes `E exp(tZ) <= rho` because the sticky proxy dominates the constant projection. Thus the power `rho^M`, rather than `rho^(M-1)` without an endpoint, is appropriate.

4. **Moment inversion and data-dependent variance.** The negative-tilt endpoint proxy bounds the lower-tail rejection region for a proposed upper population moment. Predetermined tilt choices give nested threshold events in the same scalar sample average. The checked mean radii are monotone in the variance majorant; when the random upper moment covers its population value, the selected radius is at least the best fixed true-variance radius over the predetermined grid. This supports reuse of observations without an extra grid-sized union bound. It does not authorize a newly fitted observable or center on the same trajectory.

5. **Grouping and risk.** Taking maxima of observed category moments is conservative for each member's inversion. Per-variable moment allocations and per-coordinate mean allocations, together with finite local/global checkpoint unions and one burn-in coupling event, cover the adaptive last-checkpoint choice. For `J_raw=J_local=64`, the implemented total is `129/130` of the requested delta. No iid assumption is used for the response samples.

6. **Arithmetic.** The full two-state root is retained at endpoint probabilities. Exact Fraction operations, outward exp/log bounds and the PSD determinant test make scalar acceptance independent of the floating proposal. The implemented variance is `min(U_physical,1/4)` as required. The opening module prose has a minor inconsistent `U B` wording, while the PROFILE, implementation and normative theory use the physical upper moment correctly.

## M1 — conflict boxes can publish despite the declared withholding policy

**Location in frozen code:** `code/cex/hp/spectral_heatbath_run.py:194-196`; publication through `markov_certificate.rows_from_boxes`. The theory section 6, runner PROFILE and response-certificate prose require a conflict variable to publish no points, retaining the raw enclosure only.

When `intersect_boxes` reports an empty raw/response intersection, the runner appends the raw box to the list passed to `rows_from_boxes`. If that raw box is already narrow enough, its points publish normally. The conflict is diagnostic only.

**Reproducer:** `math_probes/review_math.py`, output `math_probes/MATH_PROBES.json`. A binary raw box `[499/1000,501/1000]` for both states, contradicted by response intervals around `.70/.30`, yields `conflict=true` and **two published raw rows** at epsilon `1/200`; the frozen conflict contract requires zero.

**Scope:** this is a fail-closed publication-contract mismatch, not a proof that the raw statistical guarantee is false. Both families have allocated risk. Scanning the 33 archived response-result files under `runs/` found zero recorded conflicts, so no scored result is shown to depend on this branch.

**Repair in the consolidation checkout:**

- `markov_certificate.rows_from_boxes(..., withheld_variables=())` accepts original variable ids whose boxes remain enclosures but never enter point publication.
- The runner's `publish_response_boxes` passes conflict ids into that boundary.
- Default/no-conflict behavior remains unchanged, including publication statistics and point policy counts.
- `tests/test_dgp10_response_conflict.py` has three passing tests: whole-variable withholding with nontrivial original ids and an unaffected second variable; exact no-conflict equality; wide conflict without duplicate enclosures.
- Inherited D100's twenty raw-box equivalence trials pass.

No probability formula, risk allocation, sampler, center, tilt grid or scored artifact changed.

## Bounded checks executed

- Re-executed the supplied exact-rational scalar checker's 11 self-tests: all pass.
- Independent 90-digit mpmath differential for eight exp and five log inputs, including ±64 and logarithms of 10^±100: all 13 values lie inside the exact returned intervals. These are numerical corroboration, not a proof of every input.
- Re-executed exact finite-model algebra on the binary pair, binary three-cycle and ternary pair, using each production checked spectral gap: response/mean identities, stationarity, reversibility, PSD and trace-kernel domination all pass. Saved in `math_probes/EXACT_TRACE_CHECKS.json`.
- Replayed all 28 available archived response-group scalar certificates through the frozen exact checker: every moment upper bound, physical/normalized-unit relation, variance clamp and mean radius verifies. Saved in `math_probes/ARCHIVED_SCALAR_REPLAY.json`; this validates the scalar implications from the archived inputs, not independently the source trajectory.
- Three new publication tests and inherited D100 pass in the consolidation environment.
- No benchmark or native sampling campaign was run by this review. Probe computation was under a few seconds. One initial D100 wrapper used a dict lookup on the control module's list and failed after D100 itself printed PASS; rerunning the corrected wrapper confirmed the twenty trials. This wrapper error changed no engine or scored record.

## Interpretation correction delegated to the record audit

The theory return's `moment inflation U/y` is dimensionally inconsistent when `U` is physical and `y_max` is normalized by `B`. I flagged this to the record reviewer, who confirmed the analyzer bug and recalculated all 28 scored group records in `MOMENT_DIAGNOSTIC_CORRECTION.json`. The correct quantity is `U/(B*y_max)`. This changes the exposed card-4 clique's heuristic bottleneck label under the analyzer's own threshold; it changes no interval, radius or completion gate. The consolidated review should retain that distinction.
