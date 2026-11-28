# Consolidation acceptance — 27 November 2026

**Decision: ACCEPTED FOR MERGE. Cleanup and preservation are complete within the declared scope.** Keep the default `accepted` policy and the explicit opt-in `experimental` policy. Broad speed dominance is the next development phase; no policy promotion or rate tuning is part of this acceptance.

This decision follows independent review of `0fe5f9cfcdb759c95c71cc76e537fd7b5727911b`, its committed raw archives, and a narrow local process-exit polling repair recorded below. It supersedes the promotion hold for the consolidated implementation. It does not rewrite any original experiment gate, failed attempt, identity incident or overhead flag.

## Preservation and numerical evidence

The full original matrix has 732 unique cells and terminal receipts, with 4,130.231398 seconds charged. The repaired-runtime supplement has 245 unique cells and receipts, with 1,626.105870 seconds charged against its predeclared 4,900-second ceiling.

| Check | Independent result |
|---|---|
| Accepted versus pinned accepted | 45 identical both-repeat completions; retained in supplement |
| Experimental versus pinned experimental | 54 identical both-repeat completions; retained in supplement |
| Historical accepted | 29/29 retained |
| Historical experimental | 47/47 retained; all 122 original input bindings verified |
| Original published coordinate instances | 468,324; no geometry, inventory, binding or risk faults |
| Supplement published coordinate instances | 233,228; no geometry, inventory, binding or risk faults |
| Cross-campaign interval consistency | 60,325 task-coordinate groups; no deterministic or PAC disjoint intersections |
| Agreement with available JT results | 178,836 coordinate comparisons; no exclusion after the frozen 5e-10 serialization allowance |
| Active PGM native/source/build artifacts | 41 original and 22 supplement artifacts match frozen hashes |

The raw audit reconstructs inventories from the actual UAI/evidence bytes and reads original result files with exact rational endpoint geometry. It checks publication labels, positive-mass witnesses, request risk accounting, launch bindings and terminal receipts. It is not an independent proof of exact truth containment on every large model. The JT comparison is numerical agreement under the explicitly recorded serialization allowance. PAC consistency is diagnostic and does not change per-request confidence semantics.

The historical experimental extract is now committed under `benchmarks/external/reference/`; no inference rerun was used to recover it. The seven current-host gains shared by the pinned old experimental implementation are not attributed to consolidation.

## Repairs and qualification

The supplied cleanup-publication injection now refuses with zero rows and intact inventory. Stale process registrations no longer signal the controlled unrelated sleeper, established terminal cleanup closes ownership, and positively identified orphaned workers still receive cleanup. The exact wheel inventory mutation, unresolved-cleanup validator mutation, scoped incident checks and per-arm frozen-closure checks pass.

The independent runtime review found one additional ordinary exit race in the newly added cleanup polling helper: a killed process could disappear between `pid_exists`, `Process` and `status`, raising `psutil.NoSuchProcess`. This was fixed locally to retain process objects, treat disappearance as cleaned, retain denied inspection as unresolved, and respect the existing bounded wait. Two focused regression tests accompany it. The targeted runtime/shim/qualification/validator selection passed **37 tests** after the fix; a separate overlapping harness/validator selection passed **21 tests**, with two compiler-dependent cases excluded. These counts must not be added together.

The shipped full native qualification of the committed upstream repair is retained separately (109 tests, native oracle and carried suites). This independent review did not rebuild the Mac binaries or rerun that entire native qualification. The local polling fix changes no inference algorithm, policy, certificate formula, rate or request budget. The 245-cell supplement was executed before this final small polling fix; its affected exit-race branch is covered by the new focused controls, not claimed to have been benchmarked anew.

## Incident disposition and cost decision

The original `DBN_11 / LIBDAI_BP / r1` keeps `identity_ok=false`; the original campaign's strict validity remains FAIL. The compact record cannot mechanically establish the transient documentation-only change. A separately named clean replay in the supplement completed in about 1.902 seconds with valid output, identity and cleanup. This supplemental observation resolves the missing clean comparator observation for acceptance. The incident is explicitly adjudicated; the old record is never silently changed to PASS.

The **18 accepted/reference overhead flags are accepted as known costs for the consolidation baseline**. They remain measured end-to-end regressions under the frozen rule, not erased by explanation. The outside-worker timer includes input-dependent work. General reduction of inspection, imports, startup, publication and enforcement overhead belongs to the next performance phase, while preserving the same contract.

Experimental completes all 25 JT successes and 29 additional tasks. On mutual completions it is faster on 11 and slower on 14 in both repeats, with median PGM/JT wall ratio about 1.336; individual wins reach about 28.17x and 23.03x. These data support coverage and substantial individual gains. They do not establish broad latency dominance or a scaling theorem. All 61 current external inputs are exposed regression tasks; unseen evaluation requires a new prospective cohort.

## Repository closeout

`BRANCH_ARCHIVE.json` records the five non-main remote branch tips reviewed before cleanup. Every tip is an ancestor of the reviewed consolidation head, with no unique commits outside it. Fast-forwarding main preserves all that history; deleting those obsolete branch names does not delete methods or research commits. The baseline tag is `consolidation-baseline-2026-11-27`.

Push/merge execution and local workstation cleanup must be reported separately from this acceptance decision. The review workspace initially lacked an authenticated GitHub write credential; a failed write-access check changed no remote reference. The accompanying handoff supplies the exact incremental commit bundle and guarded merge/cleanup instructions for an authenticated checkout. Do not delete a workstation worktree containing uncommitted or untracked user work, or a branch that advanced beyond the archived tip.

The root README and benchmark README describe the canonical layout, accepted default, experimental opt-in, current preservation evidence and the correct six-arm ceiling. Historical freezes, reports, manifests, failures and archives remain unchanged. The next goal is one general untuned implementation with broad end-to-end advantages over libDAI, measured on the full external suite.

Independent reports and machine-readable audit results are under `final_review/`. Original and supplement archives remain under `step2/archive/` with their original hashes.
