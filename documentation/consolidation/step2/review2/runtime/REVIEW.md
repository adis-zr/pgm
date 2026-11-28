# Runtime and qualification repair review

Reviewed source: `d45a1367101ff5d68597684aa29c1cecced76fd9`, particularly repair `047b0d1` relative to `f21b2d3`. No source files changed. No external benchmark was executed. The attached probe performs bounded checks and cleans up every process it starts.

## Positive checks

- Independently ran `tests/test_runtime_ownership.py`, `tests/test_compat_shims.py`, `tests/test_qualification_tools.py`, and `code/tests/test_cbi_conformance.py`: **33 passed, 1 skipped in 3.20 s**. The only skipped case is the explicitly absent private CBI counterexample packet. This includes the original supervisor-killed-first inversion, foreign-package shim controls, and the new wheel negative controls.
- R2 now binds source-checkout shims to the checkout's own canonical package before importing it, explicitly rejects an already-imported foreign package, and preserves module-object aliasing. The inspected behavior and fresh-process controls support this repair.
- R4 now tests actual absence of declared private dependencies before using BLOCKED. A static RECORDS reference by itself no longer suffices when all required paths exist. Unexpected errors with available inputs remain failures.
- R5 isolates the CBI private fixture to its dependent test; the 22 portable CBI tests run. H4's blocked fixture checks and override names are explicit.
- The structural parser body was removed and `read_uai` imported from `pgm.model.uai`; the duplicate reader finding is repaired.
- The wheel gate now checks command exits, expected outcomes/routes/native execution and cache use, and exits nonzero on its FAIL verdict. This is a substantial repair even though one invariant below remains incomplete.

## Remaining findings

### P2 — R1 final cleanup can fail while the public result still publishes success

Locations: `src/pgm/runtime/attempts.py:233–242`; `src/pgm/switchboard.py:69–76`.

`run_attempt` evaluates `return result, record` before executing `finally`. If that final cleanup reports unresolved ownership, the finalizer mutates `record['outcome']` but does not revoke the already-selected non-null result. The switchboard only treats `result is None` as refusal; it then publishes from the worker result and overwrites the request outcome from it.

The attached injection follows the actual `run_attempt` and `switchboard.solve` path. It supplies a valid, exact two-coordinate worker result and a successful first cleanup, then makes the authoritative final cleanup report one unresolved group. Observed output:

```text
request outcome: COMPLETE
published: 2
attempt outcome: CLEANUP_UNRESOLVED
cleanup_final.unresolved: nonempty
```

This is an actual fail-open control-flow defect, introduced in the new final-cleanup handling. The probe injects the cleanup failure; it does not establish that a benchmark cell encountered this condition or that any marginal is numerically wrong.

Required repair: finalize cleanup before choosing the return value, and prevent any unresolved attempt from yielding publishable rows. Also make the controller reject inconsistent result/terminal-attempt state as defense in depth. Add the final-boundary regression above.

### P2 — R1's timestamp inequality does not reject the normal direction of PGID reuse

Locations: `src/pgm/runtime/attempts.py:80–95,117–128`; launch records in `runtime/supervise.py:144–145`.

`_identity_members` treats `created >= recorded_spawn - 5` as ownership. A newer unrelated process reusing a stale numeric PGID satisfies that inequality. The current control checks an older process against a future spawn time, which covers the opposite direction. The recorded leader PID is not checked against a recorded process birth identity. `receipt_established` is recorded but does not bypass any reconciliation/signalling.

The bounded probe uses only its own disposable sleeper, with a deliberately stale registration referring to its numeric PGID. This **simulates**, rather than forcing the operating system to perform, identifier reuse. The newer sleeper is killed with return code -9 both without a terminal receipt and when the supplied receipt already establishes cleanup. No unrelated real process is targeted. There is no evidence of actual PID reuse or collateral termination in the archived benchmark.

Required repair: retain and verify a launch identity that distinguishes PID incarnations, reject stale/mismatching ownership before signalling, and use a valid terminal cleanup receipt to close ownership rather than repeatedly treating its old registrations as live authority. When ownership cannot be established safely, report uncertainty instead of signalling an unrelated group. Include newer-PGID reuse and a closed-attempt receipt in the controls. A mixed group containing a refused member must not be sent wholesale to `kill_group_and_wait`, which signals all group members.

### P2 — R3 wheel gate still checks inventory size rather than original coordinate identity

Locations: `documentation/consolidation/step1/tools/clean_wheel_relocation_test.py:37–47,65–68`.

The new gate checks row count against K but never compares `(variable,state)` keys to the fixture's original inventory or checks key uniqueness. Mutating every state key to zero in its own passing worker-block receipt keeps the count and numerical values unchanged; `verdict()` still returns PASS. Thus an omitted original coordinate replaced by a duplicate is not detected.

Required repair: bind expected coordinates/cards/evidence to the fixed test input and require exactly those unique keys before geometric checks. Do not reconstruct the expected inventory from the returned rows. This is a qualification gap, not evidence that the actual installed worker returned duplicates.

## Receipt wording

The committed combined qualification receipt names source `74f3c94`, reports **98 passed plus 39 subtests**, and specialist conformance **55 passed, 7 skipped**. Its `blocked.specialist_tests` is 3 because it counts aggregated pytest skip lines; those lines represent 1+3+2=6 private-blocked test instances. This does not change its successful portable execution but should not be confused with independently executed qualification at a later source identity. A later campaign-driver control can explain the user-facing total of 99; that scope should be named.

## Evidence

- `PROBE_RESULTS.json`: observed newer-group signalling, final cleanup failure with published success, duplicate-state wheel PASS.
- `probe_repairs.py`: complete bounded reproducer; stdlib plus psutil, no native solver required.
- `REPAIR_TESTS.log`: independent affected-test execution.

The practical recommendation is a narrow runtime fix and inventory assertion, not a new mathematical review or wholesale refactor. None of these probes changes the existing benchmark counts by itself.
