# Consolidation step 1 -- START HERE

Branch `consolidate/production-layout` (review branch; `main` unchanged pending the step-2 preservation review).  Base:
`consolidate/public-api` at `f8197e6` (scored implementation `3283cfd`).  Brief: `CLAUDE_STEP1_CODE_CONSOLIDATION_2026-11-27.md`
(sha256 `3a3dfda213ae645e9ab3ebbb9f29ff2334261c442f056ee9f81c2d34bfec8cce`).  Date: 27 Nov 2026.

## What was done (commits in the order the brief requires)

| commit | content |
|---|---|
| 1/5 `c5b7708` | policy / default ownership: `pgm.policies.accepted` (DEFAULT, the accepted engine with its benchmarked configuration recorded explicitly) and `pgm.policies.experimental` (`structural-portfolio-1` verbatim); `InferenceRequest.policy`, `--policy`; every result records policy + version + record + risk allocations |
| 2/5 `302ee54` | common boundaries: `pgm.model.uai` (one exact input boundary; binding checked across the worker boundary), `pgm.planning` package, `pgm.runtime` (attempts / supervision / build), `pgm.validation.publication`; the monolithic worker split into explicit adapters; callable response solver (no `sys.argv`); parse / infer seam of the accepted engine |
| 3/5 `eb71a50` | the four production closures relocated to `pgm.algorithms.{structural,block,quotient,response}` + `pgm.runtime.supervise`; fully qualified imports; alias shims at the 47 historical paths; explicit native cache / build-record locations; legacy path bridge deleted |
| 4/5 `ed8c676` | research / specialist organization: `pgm.specialists` (cqr / cbi / sf / h4a, explicit APIs), registry statuses (selectable / specialist / reference / historical / unfinished), `research/CLASSIFICATION.json` for every tracked file |
| 5/5 `181583e` | packaging (wheel; clean-venv relocation PASS), inherited controls classified portable / blocked, harness policy arms, frozen step-2 plan, machine-readable manifest / path map / capability matrix |
| 6 | this documentation packet (START_HERE, ARCHITECTURE, API / policy specification, deletion / move inventory, README) |
| 7 `f21b2d3` | the first combined qualification receipts (reviewed) |
| repair `047b0d1` | review repairs R1-R5 (see `../step2/REPAIRS.md`) |
| amendment `74f3c94` | STEP2_AMENDMENT_1 (executed pinned references, owner-resolved natives, contracts, GATES) |
| receipts `f74f7f3` | the enforcing combined qualification at the first repaired state |
| step 2 `d45a136` | the executed 732-cell preservation regression |
| review-2 repairs `9966821` / receipts `7d5e270` | staged terminal acceptance, process-incarnation ownership, exact gates, recovered historical gate; qualification at that clean commit (`qualification/06_final/`, `SOURCE_COMMIT.txt`) |

## Read in this order

1. `PUBLIC_API_AND_POLICIES.md` -- the one API / CLI, guarantee modes (unchanged), the two policies, the INTENTIONAL behavior
   changes (default policy) separated from the arithmetic-preserving extraction.
2. `../../architecture/ARCHITECTURE.md` -- the layout, request flow, dependency direction, native resources, compatibility.
3. `MIGRATION_MANIFEST.json` (machine-readable: closures before / after, path map, shims, deletions, unfinished, policies),
   `PATH_MAP.json`, `CAPABILITY_MATRIX.json`, `DELETIONS_AND_MOVES.md`, `../../../research/CLASSIFICATION.json`.
4. `qualification/06_final/QUALIFICATION.json` -- the combined qualification at the final source state (commands, exit codes,
   source identity, wheel hash) with raw logs beside it; per-stage receipts in `qualification/02_boundaries`, `03_algorithms`,
   `04_research`, `05_packaging` (focused checks after each extraction; failed attempts are preserved in the logs).
5. `BLOCKED_CONTROLS.md` -- the inherited D1-D90 controls: 39 portable, 51 blocked, each with its missing private dependency.
6. `../../../benchmarks/external/STEP2_PLAN.md` -- the frozen, ready-to-run step-2 external preservation regression (not executed).

## Qualification summary (final state; details and raw logs in `qualification/06_final/`)

| check | result |
|---|---|
| portable tests (`tests/`) | 109 passed, 39 subtests (53 at `f8197e6` + 56 new: policy contract, boundaries, specialists / registry, runtime ownership, shim binding, qualification-tool negative controls, harness validator mutation controls, harness preflight) |
| characterization parity vs `tests/parity/reference_f8197e6.json` | IDENTICAL (16 deterministic cases: exact rational bounds / points / labels, bindings, witnesses, refusals, Z enclosures, ledger identity, risk; 2 wall-limited invariants; 2 fixed-work 75,000-step native response prefixes) -- after commit 2, commit 3 and at the final state |
| relocation diff | 304 changed lines across 47 modules, every one an import / `sys.path` / resource-location line |
| DGP10 new controls (`check_dgp10.py`) | 12 / 12 |
| native response oracle (`dgp10_oracle.py`) | PASS (9 models, 7 nonvacuous, scalar checker reference + mutations) |
| inherited D1-D90 | 39 portable / 51 BLOCKED by a dependency PREFLIGHT (repair R4: a declared private-record path absent on this host, named per control); a failure with its dependencies present stays FAILED and fails the qualification |
| specialist conformance (`code/tests`) | all tests collect (repair R5): the CBI counterexample packet is a fixture of its one dependent test (22 other CBI tests run); the 5 H4 packet tests are BLOCKED skips naming the absent private file; overrides `CBI_COUNTEREXAMPLES` / `H4A_PACKET` (not `PGM_RECORDS_ROOT`) |
| wheel | `pgm_certified-0.2.0-py3-none-any.whl` (sha in `qualification/06_final/WHEEL_SHA256.txt`); contents listed; no host binaries; no campaign code in the production inference dependency closure (the cbi / sf / h4a specialist packages ship whole, including their small helper scripts) |
| clean-wheel relocation | PASS under the ENFORCING gate (repair R3): fresh venv outside the repo, `python -I`; both policies COMPLETE with the expected inventory / guarantee / backend; all four adapters COMPLETE with the expected route, the bipartite STREAM kernel forced and natively executed; tiny CBI and SF solve-and-check round trips; h4a availability report; cqr typed UNAVAILABLE; a kernel built and loaded under `$PGM_NATIVE_CACHE` with its location and identity verified; negative controls in `tests/test_qualification_tools.py` |
| production isolation | the after-closure from the five process entrypoints (77 modules / 16,286 lines) contains no module under `code/`, no specialist, no campaign code (subprocess test + manifest) |

No external benchmark cell was run; no performance or holdout campaign; the three coverage gaps were not repaired.

## Unresolved / unfinished (also in `pgm.registry.CAPABILITIES["unfinished"]`)

- **Step 2 not run**: default promotion of `accepted` on `main` waits for the preservation regression (`STEP2_PLAN.md`).
- **51 inherited controls blocked** on private record inputs (`BLOCKED_CONTROLS.md`); they run unchanged when `PGM_RECORDS_ROOT`
  points at the records checkout. The specialist tests need their own overrides: `CBI_COUNTEREXAMPLES` (1 test) and `H4A_PACKET`
  (5 tests). None of these has been shown to pass with the inputs present on this host.
- **Specialist bridge**: `pgm.specialists._bridge` appends the `code/` tree for cbi / sf / h4a / cqr -- the only residual path
  manipulation; production inference never imports it.
- **CQR packaging**: checkout-only (bare sibling imports inside `code/cex/cqr`).
- **H4 kernels**: host-built executables under `code/build`; the wheel reports them missing.
- **Wheel exception**: cbi / sf / h4a ship whole, including their small campaign helper scripts.
- **Controller lexical pass**: the one remaining parse besides the worker's exact parse (documented; both charged). The exact
  reader is defined once (`pgm.model.uai`; the structural core re-exports it).

## Reproduce

```bash
git clone <origin> pgm && cd pgm && git checkout consolidate/production-layout
python3.12 -m venv .venv && .venv/bin/pip install -e . pytest
.venv/bin/python -m pytest tests/                                   # portable suite
PYTHONPATH=src:code .venv/bin/python tests/parity/generate_reference.py /tmp/parity.json && .venv/bin/python tests/parity/compare.py /tmp/parity.json
sh documentation/consolidation/step1/tools/qualify_step1.sh .venv/bin/python <build venv python> /tmp/qualify   # the combined qualification
```
