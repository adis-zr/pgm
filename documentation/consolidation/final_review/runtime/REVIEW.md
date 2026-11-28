# Bounded completion runtime review

Reviewed committed source `0fe5f9cfcdb759c95c71cc76e537fd7b5727911b`, including repair `9966821`. No solver benchmark was rerun. The initial checkout was clean. This reviewer then made the narrow local polling fix authorized by the parent; it is not yet committed by this reviewer.

## Prior merge blockers are repaired

- `runtime/attempts.py:255–303` stages a result, performs final cleanup and accounting, and applies a terminal acceptance predicate before returning it. `switchboard.py:44–47,77–80` independently rejects contradictory cleanup/outcome records. The original injected final-cleanup failure now returns CLEANUP_UNRESOLVED, zero rows, and intact inventory; the positive path passes.
- `runtime/attempts.py:83–122` identifies the recorded leader by PID/creation time and other members by parent chains. `kill_owned:164` only scans if a terminal receipt has not established cleanup. The supplied stale registrations leave both disposable sleepers alive. New controls cover a recorded older incarnation, missing/malformed identity, dead-supervisor cleanup and verified descendants. No actual OS PID reuse was induced or needed for these boundary controls.
- Wheel qualification requires the fixture's exact key set and uniqueness. The original duplicate-state mutation now fails.
- The benchmark validator rejects a published success behind unresolved cleanup, scopes incident adjudication to named records, and restricts the legacy internal-time diagnostic to non-completing outcomes. The relevant mutation tests pass.

`OLD_PROBES_ON_REPAIR.json` retains the direct inversion of the prior independent probes. The selected runtime, compatibility, qualification and benchmark-validator suite initially passed **35 tests** (`TARGETED_TESTS.log`). This is a targeted check, not a rerun of all 109/native controls.

## One ordinary process-exit race fixed locally

The newly introduced `_kill_pids_and_wait` expression at the reviewed commit's `attempts.py:135` separately called `pid_exists`, `Process`, and `status`. A process disappearing between those reads could raise `psutil.NoSuchProcess`, escaping the cleanup helper and the public switchboard's exception types. A synthetic no-signal probe reproduces the exception (`POLL_EXIT_RACE.json`). This is a typed-cleanup defect, not a numerical inference finding or an observed scored-cell crash.

The parent authorized a local fix to avoid another handoff round. The helper now retains `psutil.Process` objects, signals individually through their guarded kill method, treats NoSuchProcess as gone, treats AccessDenied/PermissionError as unresolved, and polls the same captured process identities within the original bounded wait. Two focused controls cover disappearance at Process construction/status and denied construction/status. No algorithm, rate, policy or budget was changed.

After that local fix the same selected suite passes **37 tests** (`TARGETED_TESTS_AFTER_POLL_FIX.log`). The race probe returns an empty unresolved list (`POLL_EXIT_RACE_AFTER.json`), and all original inversions remain true (`OLD_PROBES_AFTER_POLL_FIX.json`). All test sleeper processes were cleaned up.

Modified source files, for the parent to commit:

- `src/pgm/runtime/attempts.py`
- `tests/test_runtime_ownership.py`

## Runtime disposition

No remaining reproduced blocker within this scoped review after the local polling fix. The original cleanup/publication and stale-registration defects are closed by executable controls. This review does not claim a formal proof against every possible OS scheduling or identifier-reuse race, and does not replace the independent raw benchmark audit assigned to the other reviewer. The native mathematics and production policies were not changed.
