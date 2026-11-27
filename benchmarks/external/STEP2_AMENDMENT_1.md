# STEP2_AMENDMENT_1 -- committed pre-run amendment of the step-2 external preservation experiment (27 Nov 2026)

The step-2 plan frozen with consolidation step 1 (`STEP2_PLAN.md` v1, four arms, 488 cells) had **no scored execution**. The
independent review (`REVIEW_VERDICT.md`, `BENCHMARK_REVIEW.md` B1-B7) found its freeze unable to resolve the relocated native
artifacts, no executed accepted reference, no executable full-portfolio oracle and no cost gate. This amendment supersedes
that plan **before any scored cell**. Nothing in the inference mathematics, the scheduling policies, the cost rates or the
benchmark inputs changed.

## What changed

1. **Native resources are resolved from each arm's owning implementation** (`run_suite.native_probe`): the new layout through
   `pgm.runtime.resources` (honouring `PGM_NATIVE_CACHE`, pinned at freeze and passed to every cell explicitly), the pinned
   checkouts through their own modules. The artifacts actually loaded (source, build record, build target, content-addressed
   binary) are verified and hashed per arm; stale cache files are listed, not used. `CC` **and** `CXX` are required, resolved to
   absolute paths, hashed and version-recorded. Compilation happens only in `setup`; `freeze` refuses a stale or missing build.
2. **Executed pinned accepted reference `PGM_REFERENCE`**: the accepted standalone engine of `7f28259a4869a2c684d506b51072b04bb0ce4783`
   in a detached checkout with its own import root (`PYTHONPATH=<reference>/code`), the historical invocation
   `integrated.py --budget 19.5 --seed REP --epsilon 1/200 --delta 1/1000000 --schedule targeted --route auto --proposal mb`,
   read by a dedicated legacy reader (argv and recorded schedule / route / proposal checked; internal `USABLE_BYTES = 2560 MiB`
   and `PROCESS_HEADROOM_BYTES = 160 MiB` verified in the source and recorded, not rewritten). Its source closure and active native
   builds are frozen separately. The new package is never imported into that arm.
3. **Executed pinned experimental reference `PGM_EXPERIMENTAL_REF`**: the scored public implementation of
   `3283cfde40fe277e218987954b01b3ed94f4a712` in its own detached checkout (`python -m pgm`, its single policy), declared as the
   sixth arm **before any scored outcome**: the matrix is **61 tasks x 6 arms x 2 repeats = 732 cells**.
4. **Historical experimental extract: unavailable.** The brief asks for a hashed extract of the 122 scored `3283cfd` PGM cells
   (47 both-repeat completions). Those raw cells (`CELLS.jsonl` / `ANALYSIS.json`, analysis sha256
   `45d954bb3c4d68e8804a42041bd90c6f79a668dccb61f2692b7bfb8b6fe52d6f` per `EXPOSURE_HISTORY.json`) were never committed and are
   present neither in this checkout, nor in the records repository, nor in the review packet. The gate
   `historical_experimental_preservation` is therefore **NOT EVALUABLE** in this run; no target rows are invented from task names
   or summary counts. The executed `PGM_EXPERIMENTAL_REF` arm supplies the same-round, same-host experimental comparator instead.
5. **Explicit pairs** (`FREEZE.pairs`): `same_round_accepted` (PGM_ACCEPTED vs PGM_REFERENCE), `same_round_experimental`
   (PGM_EXPERIMENTAL vs PGM_EXPERIMENTAL_REF), `accepted_vs_experimental`, and each result arm vs LIBDAI_JT. No positional
   assumption remains in the analyzer.
6. **Arm contracts validated on every cell** (`run_suite.check_pgm`): policy / version / configuration (accepted: schedule
   targeted, proposal mb, table_cap 2^18, enum_cap 2^16, mb_cap 2^24, batch 1024, crosscheck) / allowed backends / prospective risk
   allocations (= share x requested delta; accepted: block 1 x delta; experimental: 0, 1/2, 1/4, 1/4 x delta) / epsilon / delta /
   `hard_deadline_respected` / terminal attempts; the legacy reference by argv and recorded fields. Publication geometry,
   original inventory, binding, positive mass, simplex and label coherence as before. Every published coordinate of every result
   arm is checked against the libDAI JT point wherever a valid JT point exists, partial outputs included. Deterministic interval
   compatibility is checked across arms and repeats; PAC conflicts are reported separately with their per-request interpretation.
   Mutation controls (`tests/test_benchmark_validator.py`): wrong policy, wrong version, invalid risk, late publication, backend
   outside the policy, wrong configuration, unresolved attempt, bad geometry, legacy schedule mismatch, deterministic conflict and
   JT exclusion are all rejected.
7. **GATES.json** with separate decisions: `validity`, `completeness` (INCOMPLETE when any declared cell is missing or the
   ceiling stops the run), `historical_accepted_preservation` (PGM_ACCEPTED vs the 29 historical completions of `7f28259`),
   `reference_reproduction` (PGM_REFERENCE vs its own historical cells; a loss is a reproduction failure, never attributed to
   the new wrapper), `same_round_accepted_preservation`, `historical_experimental_preservation` (NOT EVALUABLE, see 4),
   `same_round_experimental_preservation`, `paired_overhead`, and the derived `promotion_decision`.
8. **Cost criterion adopted prospectively**: a task is FLAGGED when PGM_ACCEPTED is slower than PGM_REFERENCE in both repeats by
   more than 1.25x **and** more than 0.1 s on same-round mutual completions. A flag holds default promotion pending a recorded
   explanation; it is not a validity failure. All paired walls, ratios and differences are reported. Old experimental timings stay
   descriptive; same-host attribution uses the executed pinned arms only.
9. **Ceiling declared before scoring**: 14,640 s = 732 cells x 20 s, the maximum possible charge, so exhaustion cannot silently
   omit costly inputs (the v1 8,000 s covered 366 cells). Exhaustion returns `BUDGET_STOP.json` / INCOMPLETE.
10. **Exposure wording**: all 61 inputs are exposed regression inputs; `old55` / `former_eval6` are historical groups
    (`FREEZE.tasks[*].historical_group`, `exposure_status`). The original selection manifests are unchanged.
11. **Setup evidence retained**: `setup` builds and warms every kernel of every root outside any timed cell, then runs the
    committed tiny fixture `tests/parity/fixtures/asym2.uai` through all six arms under the strict supervisor into
    `<run>/setup/` (receipts, launch records, outputs kept). `freeze` requires that record. The comparator binary present on
    this host was qualified on this host (`provenance/LIBDAI_QUALIFICATION_HOST_2026-11-27.json`, 11/11; the archived Linux
    qualification covers a different binary).
12. **Gates and promotion**: `accepted` becomes the shipped default on `main` only with validity PASS, completeness PASS,
    historical accepted preservation PASS, same-round accepted preservation PASS and no unexplained cost flag. Gains are reported,
    never forbidden. No scheduling, cost-rate, model-specific or mathematical change is permitted during the frozen run; a validity
    defect requires a new recorded amendment and preservation of the superseded cells.

## Executable sequence

```bash
export PGM_BENCH_PY=<venv>/bin/python PGM_LIBDAI=<qualified libdai_mar> CC=/usr/bin/clang CXX=/usr/bin/clang++
export PGM_BENCH_REFERENCE_ROOT=<detached checkout at 7f28259> PGM_BENCH_EXPERIMENTAL_REF_ROOT=<detached checkout at 3283cfd>
export PGM_BENCH_RUN_DIR=<run dir>            # PGM_NATIVE_CACHE optional; whatever is set at freeze is pinned for every cell
$PGM_BENCH_PY benchmarks/external/run_suite.py setup
$PGM_BENCH_PY benchmarks/external/run_suite.py freeze
$PGM_BENCH_PY benchmarks/external/run_suite.py primary     # old55
$PGM_BENCH_PY benchmarks/external/run_suite.py eval        # former_eval6
$PGM_BENCH_PY benchmarks/external/analyze_suite.py
```
