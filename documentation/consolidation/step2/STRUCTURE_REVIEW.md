# Step-1 structure and packaging review

Reviewed: `f21b2d3`, detached checkout `/workspace/scratch/226d1e4428b0/pgm-step1-review`. Scope: production relocation, packaging, specialist interfaces, dependency-closure evidence and qualification claims. No external benchmark, native build, installation or inference campaign was run. Source was not edited. Two small probes evaluate the exact shipped qualification predicates on archived or synthetic negative records; their receipts accompany this report.

## Recommendation

Keep the architecture and the extraction. The 47-module relocation has the claimed narrow diff, the production import separation is substantial, and the specialist limitations are mostly disclosed correctly. Before treating step 1 as qualified, repair the fail-open qualification predicates and expose the portable CBI tests currently lost to a collection error. These are bounded qualification repairs, not a reason to rewrite the algorithms or start another theory round.

This review found no demonstrated wrong marginal or newly broken numerical specialist implementation. It also cannot infer preservation from missing tests or import-only probes.

## Findings requiring action

### STR-1 — The clean-wheel qualification can pass when every direct backend fails

**Priority: P2, qualification blocker.** `documentation/consolidation/step1/tools/clean_wheel_relocation_test.py:68–70` only requires each direct worker's `result` to be a dictionary. It does not require worker return code zero, `COMPLETE`, all requested rows, expected guarantees, or the intended mechanism. The capability, native-build-location and cache-override checks do not participate in the verdict. `main()` also exits normally after writing `FAIL` (`:71–77`).

Independent reproduction uses the exact AST of the shipped `ok` expression, with no solver execution:

| Receipt given to the actual predicate | Verdict predicate |
|---|---|
| Archived final receipt | `True` |
| Same receipt, all four direct workers changed to exit 1 and dictionary-shaped `REFUSED` outputs | `True` |
| Same receipt, capability/native-location/cache probes changed to exit 1 | `True` |

Receipt: `STRUCTURE_PREDICATE_PROBES.json`.

The archived workers did in fact report `COMPLETE`; this finding does **not** relabel those completed runs as failures. The problem is that the reusable gate will accept a future packaging regression. Coverage is also narrower than the wording suggests: the final receipt explicitly records `stream_lib_exists: false`. The wheel test uses a two-variable forest for structural execution, so it does not execute or build the relocated bipartite-stream kernel. Its specialist checks only import CBI/SF and inspect callable attributes; no specialist solve/checker round trip runs there. The cache test prints a directory rather than building/loading a kernel through the override.

**Minimal repair:** make the gate assert command success and the expected output/branch for every required probe, and return nonzero on `FAIL`. Add a tiny forced stream case from the already committed `bip4.uai` fixture and assert its native execution. Exercise a tiny CBI and SF solve/checker pair through their new public facades. Verify actual build/load provenance under the override if that behavior remains a qualification claim. No new benchmark corpus is needed.

### STR-2 — Missing-record classification can conceal a real control regression

**Priority: P2, qualification blocker.** `documentation/consolidation/step1/tools/run_inherited_controls.py:82–85` marks any unsuccessful control `BLOCKED` whenever its source references a records-rooted constant, regardless of the actual failure. The `static` set proves a potential dependency, not that the failure was caused by an unavailable dependency. This also applies when the caller supplies `--records-root` containing the files. The script has no nonzero failure exit for unexpected `FAILED`/`TIMEOUT` results.

Evaluating the exact shipped classifier on an injected `RuntimeError: injected new regression`, with no missing-file evidence, yields `BLOCKED` if `static=['RECORDS']` and `FAILED` if `static=[]`. Receipt: `BLOCKED_CLASSIFIER_PROBE.json`.

I inspected the archived 51 blocked records rather than assuming they are concealed regressions. Forty-six name an absent record path. The remaining five are also consistent with absent inputs: D12 explicitly records missing structural fixtures; D71 finds zero archived windows; D80's runner records `FileNotFoundError`; D87's record-dependent runner produces no mechanism data; D90 records all three recovered reference files absent. Thus the archived evidence supports the stated missing-input limitation. It does not establish that those controls would pass with inputs present, and the current classifier cannot reliably detect a new defect behind such a control.

**Minimal repair:** distinguish an explicit missing dependency from an arbitrary failed control. Keep static dependencies as diagnostic metadata only. Validate structured `missing`/`present:false` records and actual missing paths, or preflight the declared dependency list. Return a failing status for unexpected control failures/timeouts. Add one negative classifier regression showing that a runtime/assertion failure in a records-dependent control remains `FAILED` when its dependency exists. Do not manufacture missing reference fixtures or label them passed.

### STR-3 — The CBI collection error suppresses 22 portable tests in addition to the missing-fixture test

**Priority: P2, specialist qualification gap.** `code/tests/test_cbi_conformance.py:256` loads `counterexamples.json` at module import. If that private file is absent, pytest cannot collect **any of the module's 23 test functions**, not merely the one counterexample-dependent test. The `CE` object is used only by `test_review_counterexamples_contained_and_verified` (`:259` onward). The other 22 functions have not been exercised by the recorded specialist-conformance run even though this single import-time dependency need not block them.

The six reported specialist issues are genuinely absent fixtures in the archived log: five H4 test failures and one CBI **module collection error**. However, saying “6 specialist conformance tests blocked” materially understates the coverage lost. Both test files are unchanged from `f8197e6`; this is an inherited qualification defect, not proof of a new mathematical regression.

`START_HERE.md:53` also overstates recovery by saying the blocked tests run unchanged with `PGM_RECORDS_ROOT`. The H4 tests use `H4A_PACKET` (`code/tests/test_h4a_review2.py:15`), and the CBI fixture path is fixed under the checkout's `code/runs/...` tree (`test_cbi_conformance.py:256`). Neither consults `PGM_RECORDS_ROOT`.

**Minimal repair:** load the private CBI counterexample packet only inside a fixture used by the dependent test, record that test as blocked if unavailable, and run the remaining CBI conformance tests unchanged. Document and support the actual H4/CBI record-location overrides. Report missing tests separately from collection failures and from any subsequently exposed failures; do not weaken the assertions.

## Claims independently checked and retained

- **The 304-line relocation claim is accurate for the relocation stage.** For each of the 47 module mappings in `PATH_MAP.json`, I compared the old path at `302ee54` with the final canonical file. Total: 156 removed and 148 added lines. The diff consists of qualified-import rewrites, removed `sys.path` setup and native resource/cache/build-record locations. The native cache helpers are new behavior covered by that last category. The figure must not be generalized to the entire step-1 change: the preceding common-model/adapter/response-callable extraction is a separate semantic boundary.
- **The production package has genuine ownership boundaries.** The four algorithm families are under `pgm.algorithms`, the worker imports explicit adapters, the controller owns common policy/publication, and the retained script paths are alias shims. I found no active production import of CQR/CBI/SF/H4 or a campaign runner in the inspected closure. The `check_global`, `check_joint` and `check_residual` modules under `pgm.algorithms.quotient` are runtime certificate checkers; their names do not make them campaign scripts.
- **The package-data list includes the required production sources/rates.** The recorded wheel includes contraction/stream C++ sources and build records, the heat-bath C source, and both phase-rate files. It excludes host `.so`/`.dylib` binaries. The archived response worker's `PAC` completion is nonvacuous evidence that a response execution can run in the clean installed environment; it is not just a canonical exact shortcut.
- **Specialist boundaries are substantially honest.** CBI and SF retain explicit structured-input APIs; CQR is explicitly checkout-only and unavailable from the wheel; H4 is reference-only and reports missing host kernels. No automatic H4 recognizer or general CQR-to-singleton conversion is claimed. The wrappers are mostly thin calls preserving the existing signatures. Import tests alone are weaker than conformance, as noted above.
- **No performance or general preservation claim is established in step 1.** The packet correctly leaves the external preservation regression to step 2. The six previously prospective benchmark tasks have already been observed and must remain regression inputs.

## Wording and gate corrections

These should be corrected with the qualification repairs; they do not require a new architecture.

1. `START_HERE.md` says the wheel has “no campaign code,” then correctly discloses an exception later. The recorded wheel contains, for example, `cbi/experiment.py`, `cbi/score.py`, `sf/runner.py`, `sf/report.py`, `h4a/run.py` and `h4a/report.py`. Say “no campaign code in the production inference dependency closure; specialist helper scripts remain packaged.” There is no need to delete these scripts to fix the claim.
2. `QUALIFICATION.json` sets `all_commands_exit_zero: true` although it records specialist-conformance exit 1. The generator in `qualify_step1.sh` deliberately excludes two steps from that calculation. Rename the field to describe its scope and add an honest overall status with blocked/error counts. The shell currently logs exit codes but does not fail the combined qualification when a required command fails.
3. The closure manifest's “no code-tree modules” field follows only resolvable `pgm.*` imports. This is useful migration metadata, not an independent general dependency auditor. Keep the source inspection and clean-install execution evidence alongside it, and do not treat that empty list alone as proof that every possible dynamic/runtime dependency is covered.

## Scope and suggested next action

Repair STR-1/2's gates, isolate the missing-fixture CBI test for STR-3, and rerun the affected small qualification checks plus the combined qualification. Keep genuine missing references explicitly blocked. Then proceed to the already frozen step-2 external preservation experiment. This review does not call for another algorithm rewrite, a larger synthetic performance campaign, or restoration of every private historical record before the new production structure can be useful.
