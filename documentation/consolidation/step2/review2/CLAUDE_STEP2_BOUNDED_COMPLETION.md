# Claude Code: finish consolidation with bounded runtime repairs

Start at `consolidate/production-layout`, `d45a1367101ff5d68597684aa29c1cecced76fd9`. Read `PGM_STEP2_REVIEW.md` and the three detailed reviews in this packet. Main remains unchanged. Keep the accepted and experimental policies, mathematical algorithms, rates and the 61-task suite unchanged.

The architecture and measured preservation are retained. This pass fixes concrete runtime/gate defects, resolves the already-existing evidence, and qualifies the changed runtime. Do not restart the 732-cell campaign merely to repair its report. Do not turn this into DGP11 or per-instance performance tuning.

## 1. Make acceptance follow final cleanup

Repair `runtime.attempts.run_attempt` so no candidate can be returned until its final cleanup result and final timing/accounting are known. A `finally` block that mutates the record after `return result, record` is not an acceptance guard. Use a staged candidate and a single explicit terminal acceptance decision after cleanup; preserve exception handling and deadline behavior.

Any unresolved owned process must prevent success/publication from that attempt. The switchboard must reject a candidate whose terminal attempt state or cleanup record contradicts success. The benchmark reader must reject the same contradiction. Do not hide unresolved ownership by relabelling it as harmless refusal while publishing its rows.

Invert the supplied public probe: it currently returns COMPLETE/two rows with CLEANUP_UNRESOLVED. Test the successful cleanup path as well as failure at the last cleanup boundary. Keep inventory on refusal and account for cleanup in wall time.

## 2. Repair process incarnation checks

The current lower-bound condition on creation time does not distinguish a new process reusing an old PID/PGID. Store and validate the actual process incarnation and its invocation ownership. Use suitable stable OS handles where available; otherwise require recorded creation identity plus a validated ownership chain and fail closed when identity cannot be established. Do not indiscriminately signal an entire group containing unverified members.

A valid terminal receipt establishing that the owned tree is empty must prevent later signalling based on stale registrations. Continue to clean a positively identified orphaned worker when its supervisor dies first. Explicitly cover: original dead-supervisor fixture; stale record pointing to a newer controlled process; already-established terminal cleanup; missing/malformed identity; caller's own group; unresolved cleanup. Do not use an artificial future spawn timestamp as the only identifier-reuse test. Every probe must clean its own disposable processes.

## 3. Tighten the small gates in the same pass

- Wheel qualification: require the exact expected coordinate key set and uniqueness, not equal lengths/counts alone. Reject the supplied duplicate-state mutation. Retain native execution, cache and specialist checks already repaired.
- Analyzer: reject successful/public results with CLEANUP_UNRESOLVED or unresolved cleanup evidence. Test this independently of top-level labels.
- Incident adjudication: any exception applies only to the named job and recorded evidence; injecting a different identity failure must fail. Preserve original strict validity FAIL. Prefer a separately labelled supplement to an implicit blanket waiver.
- Freeze guard: recheck each arm's actual pinned source/native closure before and after execution, including both external reference checkouts. Save changed path/hash details on mismatch. This is not permission to change reference code or to relabel old evidence.
- Amendment 2: correct non-publishing to non-completing; four cells have partial coordinates. Restrict the legacy internal-wall diagnostic exception to the documented non-completing statuses, or explicitly define any broader prospective rule. A post-run status/contract change must not silently broaden COMPLETE acceptance. Preserve frozen and amended analyzer outputs.
- Report qualification counts from the exact executed checkout. Keep legitimately private inputs BLOCKED. No replacement synthetic fixtures for missing historical evidence.

Run and retain before/after probes, targeted tests, same-host parity, and the required clean-wheel/native checks from committed source. Record all failed setup attempts honestly.

## 4. Close the missing historical gate without inference

This packet supplies `results/HISTORICAL_3283CFD_122_CELLS.json`, its comparison and recovery script. Original analysis hash is `45d954bb3c4d68e8804a42041bd90c6f79a668dccb61f2692b7bfb8b6fe52d6f`, exactly the prerequisite in STEP2_PLAN. Verify its source hashes and all current model/evidence identities, commit the extract to the reference directory, and recompute the gate.

Expected observation from the preserved records: both experimental arms retain all 47 historical successes, with seven gains shared by the pinned reference. Do not invent new outputs or claim those gains were caused by the refactor. Keep the previous NOT_EVALUABLE report and append the resolved analysis.

## 5. Reconcile the identity incident and expose the evidence

Keep `DBN_11 / LIBDAI_BP / r1` with identity_ok=false and retain the operator log. If the raw records mechanically establish that only documentation outside all execution closures changed, provide that exact evidence. The current narrative and final clean tree are not sufficient to prove the transient diff.

Otherwise execute one separately named, clean supplemental replay of that cell under the original 20-second/3-GiB contract and comparator build, without overwriting the original. Label the aggregate as adjudicated/supplemented; do not change the original campaign validity to PASS.

Make `PGM_STEP2_RUN_2026-11-27_f74f7f3.zip` and its identity manifest available for independent review, not merely named by a local workstation path. It should match SHA-256 `4f088a35c5ee28ac97596a96ab6df3de713fba648b7999721acf14558a76d11c`. Preserve all raw cells/launches/receipts/native identities and allow raw analyzer replay. Do not repackage it in place or change its claimed hash. Supply any additional replay/repair records separately.

## 6. Confirm the changed runtime without redoing unchanged comparators

After committed qualification, declare a prospective supplement running both repaired public policies on all 61 existing inputs in both original repeats: **244 cells**, under the existing accuracy, seed, memory and time contracts. The original 732-cell data remain immutable. Declare the 4,900-second execution ceiling before this supplement (244 x 20 plus one 20-second incident replay); setup/qualification are separate and reported. Do not raise it retrospectively or silently omit hard cases.

Require no loss from the recorded 45 accepted and 54 experimental completions, plus full original-inventory/publication and terminal-cleanup checks. Retain all failures. If a discrepancy requires a matched rerun of the corresponding old arm to distinguish host variation, declare that bounded diagnostic with a budget before execution and keep it separate from the preservation verdict. Do not call old/new wall ratios from different run periods a newly randomized causal cost result.

The 18 original cost flags remain reported. Their explanation does not make them disappear, but the current consolidation task does not require per-instance speed optimization. Preserve all end-to-end costs. Broad speed dominance and general runtime overhead reduction are the next performance task, after this runtime is qualified.

Return one packet with the fixes, inverted probes, exact qualification, recovered historical gate, incident disposition, unchanged original archive identity, raw evidence, and supplemental preservation. Push the review branch and stop for review; do not merge main or change the default policy based on hindsight benchmark selection.
