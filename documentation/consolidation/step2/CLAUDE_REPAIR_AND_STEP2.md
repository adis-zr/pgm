# Claude Code: bounded repair, then the preservation experiment

Continue from `consolidate/production-layout` at `f21b2d30899f50b2223cc91351c23784e7b00d7d`. Read the accompanying `REVIEW_VERDICT.md` and the three detailed reviews. Preserve the production extraction, accepted default and frozen experimental scheduling policy. Main remains unchanged during this work.

This is one implementation-and-experiment pass. Repair the concrete runtime/qualification/preflight findings, commit and qualify them, freeze the amended full external experiment, and run it. Do not stop for another report-only closeout if those bounded gates pass. Do not rewrite the mathematical algorithms or tune the scheduler to rescue benchmark outcomes.

## A. Repair the runtime boundaries

**R1:** reconcile durable ownership whenever a valid terminal receipt cannot establish cleanup, including when the supervisor has already exited or has been killed. Restrict cleanup to this invocation's registered groups and descendants. Check the recorded ownership/identity; do not indiscriminately signal unrelated or stale reused process groups. Bound cleanup, report unresolved ownership and prevent success if it cannot be established. The supplied probe kills only the supervisor, calls the real cleanup helper and checks its registered child; it must invert from leaked to cleaned, and must also clean its own resources on every probe exit.

**R2:** prevent source-checkout compatibility shims from silently selecting an unrelated installed `pgm`. Preserve their intended module-object alias behavior. Prove the behavior in fresh subprocesses with an older/conflicting importable package and with no installed package. Bind to the checkout's own implementation or fail explicitly on an incompatible already-loaded package. Preserve installed public API behavior; do not restore a global production `sys.path` bridge.

## B. Make qualification enforce its claims

**R3:** the wheel test must require success and the expected output/route for every required command; a dictionary-shaped refusal is not success. Check original inventory, geometry and expected guarantee, not only COMPLETE labels. Return nonzero on FAIL and have the combined qualification propagate it. Exercise the installed native bipartite stream using the existing tiny fixture, and require its native execution. Exercise tiny CBI/SF solve-and-checker round trips. Actually build/load a kernel under the cache override and verify its recorded location/identity. Add negative controls that corrupt worker status, policy, native build/cache results and the final verdict.

**R4:** remove static record references as a sufficient reason to label a failure BLOCKED. Use actual, validated missing-dependency evidence or a declared dependency preflight. A RuntimeError/assertion failure with available inputs remains FAILED. Unexpected FAILED/TIMEOUT outcomes must fail required qualification; legitimately absent historical evidence remains explicitly BLOCKED. Do not fabricate the missing original fixtures or weaken assertions.

**R5:** move CBI's private counterexample load into a fixture used only by its dependent test. Run the other 22 CBI tests unchanged. Correct the H4/CBI path-override documentation and implement explicit usable overrides if needed. Report collection failures separately from collected blocked tests. Correct the overall qualification status, wheel campaign-code wording, and the scope of the single-parser claim. Keep unavailable specialists honestly labelled.

Run the affected small controls and the final combined qualification from committed source. Preserve failures and superseded receipts. The archived Mac witness constants can differ at rounding scale on Linux; compare reference and candidate on the same qualified host rather than weakening exact same-host parity or treating a host difference as a code defect.

## C. Amend the unexecuted step-2 plan and its harness

Commit an explicit `STEP2_AMENDMENT_1`. The old plan had no scored execution; do not say the amended plan was the original freeze.

Resolve native resources from their owning implementation, including `PGM_NATIVE_CACHE`, and freeze the artifacts actually loaded by each worker. Include source/flags/compiler/architecture/binary identities and resolve both CC and CXX. Qualify freeze preparation with all stale old-path artifacts absent. Ensure no compilation happens inside a scored call. Keep smoke fixtures and receipts as setup evidence instead of deleting them.

Add an independently executed `PGM_REFERENCE` from pinned accepted commit `7f28259a4869a2c684d506b51072b04bb0ce4783`, in a detached source/import root. Its historical invocation is:

```text
PYTHONPATH=<reference>/code <python> <reference>/code/cex/blockres/integrated.py
  --input MODEL --output RESULT --budget 19.5 --seed REPEAT
  --epsilon 1/200 --delta 1/1000000
  --schedule targeted --route auto --proposal mb
```

Verify the reference and its defaults against the archived accepted invocation. Do not import the new public package or new alias shims into that arm. Keep its raw result and analyze it through a dedicated legacy reader. Freeze its source closure and active native builds separately. Use the same outer 20-second, 3-GiB process-tree contract, exact input/evidence bytes, seeds and dependency environment. Internal policy limits must be recorded, not silently rewritten.

The minimum matrix is PGM_REFERENCE, PGM_ACCEPTED, PGM_EXPERIMENTAL, LIBDAI_JT and LIBDAI_BP: 61 tasks, two repeats, **610 cells**. If adding a same-round pinned experimental reference, declare that sixth arm and **732 cells** before any scored outcome. Do not change the matrix midway through the experiment. Name all comparison pairs explicitly; the current analyzer assumes the first two PGM arms are the two public policies.

Add a compact, hashed extract of the previous 122 PGM seed-cells from scored `3283cfd`, binding all model/evidence hashes and the 47 both-repeat completions. The previous evidence packet supplies them. The required comparison is no lost prior success, with gained/lost/one-repeat sets reported. The old 27/29 accepted subset alone cannot test preservation of the full experimental portfolio. If evidence bytes are unavailable, report that exact prerequisite and recover it before scoring; do not invent target rows from task names.

Validate requested policy/version/configuration and allowed backends, epsilon/delta, risk allocations, publication geometry, inventory, identity, deadlines and terminal cleanup per arm. Check published partial rows against JT wherever valid JT coordinates exist. Check cross-arm/cross-repeat deterministic compatibility; report PAC conflicts with their per-request interpretation. Mutation controls must show wrong policy, invalid risk, late publication and conflicting intervals are rejected by the analyzer.

Write a machine-readable GATES result with separate validity, completeness, historical accepted preservation, same-round accepted preservation, historical experimental preservation and paired-overhead decisions. If the pinned reference itself misses a historical success, record a reference-reproduction failure rather than automatically blame the new wrapper. Old experimental timings remain descriptive unless its old code runs on the same host. New gains are not a failure solely because the old run lacked them.

Freeze the cost criterion prospectively. The review proposes flagging a task when the new accepted API is both over 1.25× and over 0.1 seconds slower than the same-round reference in both repeats; it is not a previously agreed gate. Make the adopted threshold and its effect on promotion explicit in the amendment. Report all paired measurements. Broad libDAI dominance is not a step-2 requirement.

Update all normative plan/protocol/README/freeze/report wording consistently. All 61 inputs are exposed; old55 and former-eval6 are historical groups, not current unseen evaluation. Retain original selection manifests unchanged. Declare the full matrix and compute ceiling before scoring. If the ceiling is exhausted, return INCOMPLETE rather than silently omit costly inputs or raise it after seeing outcomes.

## D. Execute and return

Once required repair controls, clean installation, reference setup and harness mutation/preflight checks pass, freeze the committed implementation and run the entire declared matrix serially under the existing supervisor. Keep every raw output, failed attempt, timeout, launch identity and terminal receipt. No scheduling, cost-rate, model-specific or mathematical changes during the frozen run. An actual validity defect requires a new recorded amendment and preservation of the superseded cells.

Return one packet: before/after repair evidence, honest qualification, amended protocol, exact executed code/build identities, complete raw benchmark logs, independent gate recomputation, historical and same-round comparisons, cost flags, remaining limitations, branch head and push status. Main remains untouched until the preservation result is reviewed. This pass should answer whether the consolidated accepted API preserves its implementation under the common contract while keeping the experimental portfolio's existing capabilities visible.
