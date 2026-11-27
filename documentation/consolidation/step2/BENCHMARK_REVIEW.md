# Step 1 review: Step 2 benchmark readiness

Reviewed `f21b2d3` against `f8197e6`, including the frozen Step 2 plan, runner, analyzer, build locations and retained historical evidence. This was a static/read-only review: no inference, benchmark, compilation, source edit or scored-data change was performed.

**Verdict: do not start Step 2 as written.** The four-arm extension is useful, but its freeze currently cannot resolve the moved native artifacts. After that mechanical fix, it still lacks the executed pinned accepted reference requested by the brief, the complete experimental preservation oracle, and a cost-preservation gate. It can generate descriptive four-arm results; it cannot support the promised attribution that any loss is caused by the new common contract or layout.

## Blocking findings

### B1 — Freeze still reads deleted native locations

`benchmarks/external/run_suite.py:84` sets `base = REPO / "code/cex/newarm"`; lines 85–93 read `cex_build.json`, `stream_build.json`, kernel sources and libraries from there. At `f21b2d3` those files are tracked only under `src/pgm/algorithms/structural/`. The setup command builds them there (`src/pgm/runtime/build.py:8–11`; structural modules bind build locations beside the new implementation). `freeze()` calls `host_files(warm=True)` at line 294. Thus a clean, correctly built checkout fails before it can freeze. Old residual files on a workstation would mask the defect and could warm caches from the wrong artifact location.

**Required amendment:** resolve the structural source/build/cache paths from the actual owning implementation. Verify source, flags, binary hash and actual cache file before freeze. Add a lightweight harness qualification that exercises `host_files()` and freeze preparation with the old `code/cex/newarm` artifact files absent; use a temporary run directory and no solver.

The new runtime also supports `PGM_NATIVE_CACHE` (`src/pgm/runtime/resources.py:20–36`), while the benchmark always hashes module-local build/cache paths. `run_cell()` inherits this variable without freezing or overriding it. A local freeze could therefore hash one set while a worker uses another cache or compiles during its timed call. Either freeze the resolved active resource paths and pass the pinned cache setting to every cell, or explicitly reject/unset cache overrides for this source-checkout campaign. Do not silently copy an archival foreign-host library and treat it as a newly qualified host build.

### B2 — No executed accepted-reference arm

The plan explicitly substitutes historical cells for the accepted-reference run (`STEP2_PLAN.md:18`, four arms at lines 24–25; `run_suite.py:334`). Those cells are valid historical coverage targets, but they do not measure the current host, dependencies, timing drift or wrapper overhead. Therefore the statements “any loss is a preservation regression of the common contract” (plan line 30) and “a difference can only come from request-level boundaries” (line 31) are not justified.

**Required amendment:** add `PGM_REFERENCE`, running the unmodified accepted standalone engine from pinned `7f28259a4869a2c684d506b51072b04bb0ce4783`, in its own detached checkout and subprocess import root. Run it on the same 61 inputs, both repeats, interleaved under the same outer 20 s / 3 GiB supervisor. This makes **61 × 5 × 2 = 610 cells**, with 550 old55 and 60 former-eval cells. The reference remains distinct from `PGM_ACCEPTED`, which runs the new common API.

The historical command is recoverable from the previous packet's `results/run_benchmark.py:108–111`:

```text
PYTHONPATH=<reference>/code <python> <reference>/code/cex/blockres/integrated.py
  --input M --output R --budget 19.5 --seed REP --epsilon 1/200 --delta 1/1000000
  --schedule targeted --route auto --proposal mb
```

Freeze the reference checkout commit, executed Python source closure, wrapper/normalizer source, all active native build files, interpreter/dependencies and launch environment separately. Preserve its raw legacy result and normalize it only for independent analysis. Do not import the new `pgm` package into the reference worker. Preserve the accepted 2,560 MiB internal usable ceiling and the shared 3 GiB outer limit; do not silently change its numerical or memory policy to resemble the new controller.

Retain both questions: historical known successes (29) and **same-round reference successes**. If the old reference itself loses a historical completion, report a baseline reproduction failure; do not automatically attribute that loss to the new API. If new accepted fails while same-round reference succeeds, that is direct common-contract preservation evidence.

### B3 — Full experimental preservation and cost gates have no executable oracle

The analyzer compares both public arms only with the historical accepted 29 (`analyze_suite.py:276–310`). It neither loads nor hashes the scored `3283cfd` 61-input results. The plan says the experimental arm must retain the same complete set “elsewhere,” but the repository supplies no machine-readable 47-task target, no evaluated gate for it, and no comparable prior policy/attempt bindings. Losing DBN_14, MUNIN1, any former-eval completion, or another recovered structural success would not change the exposed `27/29` check. Requiring the *old losses* to persist is also the wrong preservation predicate: an unexpected gain should be reported and investigated, not forced away.

**Required amendment:** ship a compact, hashed extract of the 122 PGM cells from `3283cfd`, with task/model/evidence identity, repeat, completion, guarantee and route/attempt summary. Validate every binding against the current input manifest. Gate on **zero losses from its 47 both-repeat successes**, reporting the exact gained/lost sets and one-repeat cases. Preserve the 41/55 and 6/6 cohort distinction as historical provenance, although all 61 are now exposed. Investigate route or deterministic-output differences separately from host-sensitive wall-limited outcomes. For strict causal layout latency attribution, add a same-round pinned `3283cfd` reference as an optional sixth arm; otherwise keep its old timings descriptive only.

There is also **no accepted-public/reference cost comparison or cost acceptance gate**. The analyzer computes only JT/public ratios. Retaining completion near the 20-second ceiling can conceal severe overhead on cheap tasks. Proposed pre-run amendment: calculate paired `public/reference` wall ratios and absolute differences on same-round mutual completions, flag a task only when **both repeats exceed 1.25× and +0.1 s**, and hold default promotion on any such flag pending explanation. This is a proposed explicit gate, not a claim that it was in the submitted freeze. Keep all paired values visible, without after-the-fact tuning. No historical timing should masquerade as a current paired trial.

### B4 — Declared validation gates exceed what the analyzer checks

`check_pgm()` records `policy` and `policy_version` (`run_suite.py:206–207`) without checking them against the requested arm. It does not verify the policy configuration, prospective risk shares, requested epsilon/delta or `hard_deadline_respected`. The analyzer checks JT containment only when the entire PGM request completes (`analyze_suite.py:232–235`), so it does not implement the plan's “every published enclosure” condition for partial outputs. There is no cross-public-arm or cross-repeat interval-conflict check. The analyzer emits issues but has no unified pass/fail gate record and exits normally even if gates fail.

**Required amendment:** pass the frozen expected arm contract to the checker and assert:

- exact policy/version/configuration matches, allowed backends, and accepted full-delta versus experimental allocated shares;
- request epsilon/delta, row/aggregate guarantee coherence, nonnegative total prospective risk within delta;
- no published late rows, successful accepted terminal cleanup, unique complete start/terminal inventories, and no unresolved attempts;
- all published coordinates are checked against JT whenever JT has a valid corresponding point, even when PGM is partial;
- deterministic interval intersections across reference/public arms and repeats; PAC conflicts separately identified with their per-request risk interpretation.

Write `GATES.json` with separate validity, historical preservation, same-round preservation, experimental preservation, cost and completeness decisions. Missing cells, unresolved receipts or unqualified builds must leave the campaign incomplete rather than looking like a completed clean pass. Smoke-test the validator with deliberately wrong policy/risk/deadline metadata and a conflicting interval; this requires only handcrafted artifacts, not external solver execution.

## Other corrections before freezing

### B5 — Exposure and protocol provenance conflict

The Step 2 plan correctly states all 61 are exposed. However the still-normative `PROTOCOL.md` describes three arms, a prospective cohort and keeping selected contents from implementation; `run_suite.py:355` repeats the prospective claim; the generated report at `analyze_suite.py:355` again presents the six as prospective. `README.md:38` still says 366 cells / three arms. It also points at the deleted heat-bath build path at line 15. These are not innocuous when the freeze hashes all these files as the experiment's protocol.

Amend all current normative text consistently: old55 and former_eval6 are two **exposed regression cohorts**. Keep original manifest split names and original selection facts as immutable historical provenance, but add current `exposure_status` to the new freeze/report. Freeze the Step 2 plan and acceptance spec hashes explicitly. The corrected plan must supersede the unexecuted one by a committed amendment, not claim it was run verbatim.

### B6 — Setup instruction deletes evidence and is not executable as shown

`STEP2_PLAN.md:43` asks for smoke outputs to be deleted afterwards; lines 44–45 use a placeholder UAI path and exercise only the two public policies despite “every arm.” Setup is separate from scoring, but its failures, commands and receipts should be retained. Use a committed tiny exact fixture for wrapper/binary correctness, include all executed arms, and retain the qualification outputs and identities. Do not run an arbitrary external benchmark task unsupervised and erase its outcome.

Set both `CC` and `CXX` explicitly to resolved host paths during setup, then freeze their recorded versions and binary identities. The plan exposes only CC, while the structural builds use CXX and the stream record currently omits the compiler identity (`stream_float.py:48`). Capture that provenance in the harness setup manifest without modifying inference formulas. Absolute frozen host paths are acceptable execution identities; fresh-host reproduction needs new qualified host builds and a new freeze. Artifact-only replay should use the archived binary bytes solely for hashing.

### B7 — Pair labels become wrong when the missing reference arm is added naively

`analyze_suite.py:221–223` assumes the first two PGM arms are accepted and experimental, and line 262 uses the first PGM arm as the BP/JT-loop guard. Adding `PGM_REFERENCE` to the generic PGM list without updating these assumptions will suppress or mislabel comparisons. Name comparison pairs explicitly. Normalize old-reference outputs using their own reader, preserving the public output reader for the new API. Similarly update expected cell counts, per-arm checks and report headings rather than changing the arm list alone.

## What is sound and should remain

The runner retains serial fresh-process execution, reversed arm ordering, fixed input bytes, one common external resource contract, before/after source and comparator hashes, and separately recorded refusals. The analyzer correctly restricts measured JT speed ratios to mutual completions and uses only true timeout outcomes for censored bounds. Memory-admission failures do not acquire a speedup denominator. Public exact/deterministic/PAC guarantees remain distinct from libDAI point output. No new synthetic performance panel or benchmark-name routing is needed.

The existing historical evidence should remain visible. At `3283cfd`, the single public policy completed 41/55 plus 6/6, retained accepted 27/29 and research 30/32, and preserved the selected legacy 7/7. The historical union of those prior methods is 41 exposed tasks, of which the new arm retained 38 and replaced three losses with three gains. That union is a coverage target only, never an executed selector or a latency arm. Gaps are DIABETES, ObjectDetection_43 and Pedigree_12. Keep these distinctions in Step 2 rather than reducing the whole library's recovery objective to 29 accepted completions.

## Executable pre-run amendment sequence

1. Commit a `STEP2_AMENDMENT_1` and revised plan/runner/analyzer covering B1–B7. Do not change scheduling constants, benchmark inputs or inference mathematics. Record that the original plan had no scored execution.
2. Create a detached pinned accepted-reference checkout. Declare `PGM_BENCH_REFERENCE_ROOT`, its exact commit and source/build manifest. Add the reference arm to the common supervisor; do not rewrite the reference engine or use a new public worker to impersonate it.
3. Add the compact `3283cfd` result extract and the separately identified historical research/legacy coverage targets. Bind them by model/evidence hash and source artifact hash.
4. Build/qualify all host binaries outside timed cells with explicit CC/CXX. Retain supervised tiny qualification evidence for all five arms. Exercise freeze preparation without the old artifact paths and exercise deliberately failing analyzer fixtures. Verify no active build/cache lies outside the freeze inventory.
5. Freeze committed source, both code roots, five arm commands/configurations, 61 input bindings, both repeats, the 610-cell expected matrix, current exposure labels, risk/latency gates, dependency/host identities, and a prospective compute ceiling. The existing 8,000 seconds may be kept if consciously budgeted; if exhausted, report the full experiment incomplete rather than choose a cheaper subset after outcomes.
6. Execute the full frozen matrix serially. Keep historical and same-round preservation separate, and require all gate records before promotion. Report per-arm geometry, completion, all paired timings, resource failures and generalization limitations. No per-instance rescue or rate adjustment is permitted during the frozen run.

After those amendments, Step 2 can test whether the clean API preserves the accepted implementation and recovered portfolio behavior. It still cannot establish universal smooth-runtime behavior, broad scaling from graph size, or unseen generalization from these now-exposed inputs.
