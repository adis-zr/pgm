# Repair pass before step 2: before / after evidence

Review inputs (copied here): `REVIEW_VERDICT.md`, `CODE_REVIEW.md`, `STRUCTURE_REVIEW.md`, `BENCHMARK_REVIEW.md`, the brief
`CLAUDE_REPAIR_AND_STEP2.md`. The reviewer's probes are under `repair_evidence/before/`; the same probes and the new
controls on the repaired source are under `repair_evidence/after/`. Commits: `047b0d1` (R1-R5), `74f3c94` (amendment),
`f74f7f3` (qualification receipts).

| finding | before (reviewer evidence) | after (this pass) |
|---|---|---|
| R1 supervisor dies first, registered worker leaks | `before/RUNTIME_OWNERSHIP.json`: supervisor rc -9, child alive after `kill_owned`, `leaked: true` | `after/RUNTIME_OWNERSHIP.json`: same probe, `leaked: false`; `kill_owned` reconciles the durable SPAWNED / registry groups with an identity check (spawn time), refuses a reused pgid and the caller's own group, reports `unresolved` -> attempt outcome `CLEANUP_UNRESOLVED` (never success). `tests/test_runtime_ownership.py` (4) |
| R2 shims import any installed `pgm` first | `before/SHIM.stderr`: `ModuleNotFoundError: No module named 'pgm.algorithms'` from an older editable install | shims put their own checkout's `src` first and refuse an already-imported foreign `pgm` explicitly; `tests/test_compat_shims.py` (4): conflicting package earlier on sys.path, foreign package already imported, `-I` script entry, alias identity |
| R3 wheel gate fail-open | `before/STRUCTURE_PREDICATE_PROBES.json`: all four workers failing still PASS; cache / capability checks not in the predicate; no nonzero exit | `verdict()` requires exit 0 + expected outcome / inventory / guarantee / backend / route for every required probe; forced native STREAM on bip4; CBI + SF solve-and-check; cqr typed UNAVAILABLE; build + load under `PGM_NATIVE_CACHE` with location and identity verified; exit 1 on FAIL; 20 negative controls (`tests/test_qualification_tools.py`); `after/clean_wheel_relocation_strict_gate.json`: PASS, `failures: []` |
| R4 classifier hides failures behind static references | `before/BLOCKED_CLASSIFIER_PROBE.json`: injected RuntimeError classified BLOCKED when `static=['RECORDS']` | BLOCKED only on a dependency PREFLIGHT (declared private paths absent) or validated missing-path evidence; FAILED otherwise and the driver exits 1; `after/BLOCKED_CONTROLS_preflight_classifier.json`: 39 PORTABLE / 51 BLOCKED, every BLOCKED by `declared dependency absent (preflight)`; classifier regression in `tests/test_qualification_tools.py` |
| R5 CBI collection error hides 22 tests; H4 packet errors; wrong override docs | 1 collection error + 5 H4 failures; `PGM_RECORDS_ROOT` claimed | CBI packet is a fixture of its one dependent test (22 run, 1 BLOCKED skip; `CBI_COUNTEREXAMPLES`); H4 packet tests skip BLOCKED naming the path (`H4A_PACKET`); qualification reports blocked / collection errors / failed separately; `overall` status requires every required step |
| B1 freeze reads deleted `code/cex/newarm` paths; cache override unfrozen | `before/FREEZE_PATH_PROBE.json`: `RuntimeError: Build the heat-bath kernel during setup before freezing` on a correct build | `run_suite.native_probe` resolves per arm from the owning implementation (incl. `PGM_NATIVE_CACHE`, pinned and passed to every cell), verifies and hashes the loaded artifacts; `tests/test_benchmark_harness.py` covers both settings |
| B2-B7 | no executed reference; no full oracle; positional pairs; no gate record | `STEP2_AMENDMENT_1.md`: PGM_REFERENCE (7f28259) and PGM_EXPERIMENTAL_REF (3283cfd) executed; explicit pairs; contracts; GATES; cost criterion; 732 cells; ceiling 14,640 s; `tests/test_benchmark_validator.py` (13 mutation controls) |

Duplicate exact reader: `pgm.algorithms.structural.core.read_uai` now **is** `pgm.model.uai.read_uai` (one definition; parity
IDENTICAL after the change). Same-host comparison: the parity reference and the candidate were regenerated on this host; the
archived Mac witness constants are not compared against another platform.

## Review 2 (bounded completion): before / after

Inputs: `review2/PGM_STEP2_REVIEW.md`, `review2/runtime/REVIEW.md`, `review2/gates/GATE_REVIEW.md`, `review2/results/RESULTS_REVIEW.md`,
the brief `review2/CLAUDE_STEP2_BOUNDED_COMPLETION.md`. Commits `9966821` (repairs), `7d5e270` (qualification receipts), `2bb9631`
(raw archive), then the supplement run and this packet.

| finding | before (reviewer evidence) | after (this pass) |
|---|---|---|
| final cleanup failure still published success | `review2/runtime/PROBE_RESULTS.json` `final_cleanup`: `outcome COMPLETE, published 2, attempt CLEANUP_UNRESOLVED` | `run_attempt` stages the candidate and decides ONCE after final cleanup; controller refuses inconsistent candidates; `repair_evidence/after2/PROBE_REPAIRS_INVERTED.json` `final_cleanup`: `outcome CLEANUP_UNRESOLVED, published 0`; tests: final-boundary inversion, successful path, first-cleanup failure |
| creation-time lower bound accepted the normal direction of pgid reuse; receipts did not close ownership | `stale_without_receipt` / `stale_with_terminal_receipt`: unrelated newer sleeper killed (rc -9) | process INCARNATION (pid + creation time) recorded by the supervisor and verified per member; parent-chain verification; only verified pids signalled individually; a valid terminal receipt closes ownership; missing / malformed identity fails closed: both probes now `killed: false`; tests: stale newer process, receipt closure, missing identity, mixed group, own group, dead-supervisor fixture |
| wheel gate validated counts, not the coordinate set | `wheel_inventory.duplicated_state_keys: PASS` | exact fixture inventory (unique keys, cardinalities) bound from the committed fixtures via the exact reader: `FAIL` on the duplicate-state mutation; 3 new negative controls |
| benchmark reader accepted CLEANUP_UNRESOLVED behind success | `review2/gates/ANALYSIS_BOUNDARIES.json` `cleanup_unresolved_attempt_reader: contract_valid true` | terminal-cleanup contract fault for CLEANUP_UNRESOLVED / unresolved cleanup evidence; test `test_reader_rejects_published_success_behind_unresolved_cleanup` |
| incident-excluding predicate excluded any identity failure | `exception_validity: PASS` with two unrelated identity failures | exact allowlist `INCIDENTS.json` (job, kind, evidence, disposition); `validity_with_adjudicated_incidents_set_aside`; unrelated failures keep FAIL (test) |
| reference closures frozen once, not rechecked per cell | — | `arm_closure_ok` before and after every cell for the arm's own pinned source + natives, mismatch details saved |
| amendment-2 wording / rule | "non-publishing" (four cells publish partial rows); legacy late COMPLETE accepted | "non-completing"; the exception restricted to non-completing statuses; completing status past the allowance is a fault; rev-1 outputs preserved |
| historical experimental gate NOT_EVALUABLE | prerequisite absent | the review's recovered extract (`reference/HISTORICAL_3283CFD_122_CELLS.json`, source ANALYSIS sha `45d954bb...`, hash-bound) -> PASS 47/47 for both experimental arms; seven shared current-host gains |
| raw archive named by a workstation path | — | `archive/PGM_STEP2_RUN_2026-11-27_f74f7f3.zip` committed unchanged (sha `4f088a35...`); post-run records and the supplement run archived separately |
| incident disposition | narrative only | `INCIDENTS.json`; operator log clarified by an appended entry; one clean supplemental replay of `DBN_11 / LIBDAI_BP / r1` under STEP2_SUPPLEMENT_1 (identity_ok, valid); the original cell and the original campaign validity unchanged |

Supplement (`STEP2_SUPPLEMENT_1`, declared before execution): 245/245 cells, 1,626 s of the 4,900 s ceiling, validity PASS,
no loss from the recorded 45 / 54 completion sets (no gains either), replay cell valid. The first attempt's freeze was refused
because the raw archive was still an untracked file (`supplement/attempt1-freeze-refused/`); it was committed and the
supplement re-launched from a clean declaration.
