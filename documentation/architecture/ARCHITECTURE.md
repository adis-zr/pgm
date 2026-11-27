# Architecture after consolidation step 1

```
src/pgm/
  api.py            infer(request) -> InferenceResult            contracts.py   InferenceRequest / InferenceResult
  __main__.py       the CLI (output-commit guard)                 registry.py    capability registry (statuses)
  policies/         accepted.py (DEFAULT) | experimental.py       <- explicit public scheduling policies (candidates, risk shares, record)
  switchboard.py    the controller: bounded inspection -> policy candidates -> supervised attempts -> publication
  model/uai.py      ONE input boundary: exact reader, binding, original inventory, BoundModel, typed source refusals
  planning/         features.py: streamed lexical inspector + optional min-product forecast (bounded, read-only facts)
  runtime/          attempts.py (supervised attempt), supervise.py (owned-tree supervisor), supervision.py (zero-grace entry),
                    resources.py (explicit native cache / build-record locations), build.py
  validation/       publication.py: normalize / suppress / staged write (worker); accepted_row / merge_row / assemble (controller)
  backends/         base.py (AdapterContext, memory policy) | structural.py | block.py | quotient.py | response.py | worker.py
  algorithms/       structural/ (10 modules + cex_kernel.cpp, stream_kernel.cpp, build records, tracked host binaries)
                    block/ (6 modules = the accepted engine)   quotient/ (23 modules + PHASE_RATES[_R1].json, lp_worker)
                    response/ (7 modules + heatbath_native.c)
  specialists/      _bridge.py (the only residual path manipulation) | cqr.py | cbi.py | sf.py | h4a.py
tests/              portable public / repair / regression / boundary / specialist tests; parity/ (pinned reference + comparator)
benchmarks/external/ run_suite.py (arms PGM_ACCEPTED / PGM_EXPERIMENTAL / LIBDAI_JT / LIBDAI_BP), analyze_suite.py, STEP2_PLAN.*
research/           README.md + CLASSIFICATION.json (every tracked file classified)
code/               historical layout: alias shims at the 47 relocated paths, campaign tooling, specialists, frozen snapshots, evidence
documentation/      architecture/, reviews/, consolidation/step1/ (manifest, path map, capability matrix, blocked controls, qualification)
```

## Request flow

1. `infer` validates the immutable request (`policy` is validated separately from `mode`).
2. The controller samples the start, derives the work deadline (budget minus the reserved publication tail), inspects the
   source once lexically (`pgm.planning.features`: hashes, cardinalities, original inventory, scopes, structural facts; the
   optional physical forecast only when the policy needs it) and asks the policy for its candidate attempts.
3. Each attempt runs `python -m pgm.backends.worker` under `python -m pgm.supervision` (the owned-tree supervisor, grace 0)
   with the absolute deadline, the attempt's PAC share, the explicit configuration and the expected binding.  The worker
   parses the source EXACTLY ONCE (`pgm.model.uai.load_bound`), refuses a binding mismatch typed, fixes the original
   inventory before any backend can refuse, dispatches to the adapter, normalizes the result through the common publication
   boundary and commits with the staged late-suppression payload.  Parsing is charged to the request.
4. The controller re-checks every row in exact rationals (`accepted_row`), merges by label / width with the conflict rule,
   assembles the per-variable box against the simplex, takes the one authoritative final timestamp and suppresses late
   answers.  Cleanup receipts precede every acceptance.

## Dependency direction

`api -> switchboard -> policies / planning / runtime / validation`; `worker -> model / validation / backends -> algorithms`.
`pgm.algorithms.*` import each other by fully qualified name (block -> structural; quotient -> block, structural; response ->
quotient, structural) and never import `pgm.backends`, `pgm.specialists`, campaign code or the frozen snapshots (verified
by a subprocess test and by the after-closure in `MIGRATION_MANIFEST.json`: 77 modules / 16,286 lines from the five process
entrypoints, none under `code/`).  The specialists are reached only through `pgm.specialists._bridge`.

## Native resources

Sources, strict-FP flags and build records live with the owning implementation.  Binaries are content-addressed under
`$PGM_NATIVE_CACHE`, else `native_cache/` beside the module when writable (the checkout behaviour), else
`~/.cache/pgm/native_cache`.  The wheel ships sources and records only (no `.so` / `.dylib`, no caches); kernels are built
on the host on first use (`python -m pgm.build` builds them during setup, never inside a timed request).

## Compatibility

Historical module paths (`code/cex/{newarm,blockres,hp}/*.py`, `code/gbidi/supervise.py`) are alias shims returning the
canonical module object; running one as a script re-executes the canonical module as `__main__`.  `pgm.supervision`,
`pgm.build`, `pgm.backends.worker.{normalize_result, read_inventory, write_result, AdapterRefused}` and the switchboard
names `run_attempt / candidate_plan / POLICY_VERSION / NATIVE_ROWS_PER_SECOND / RISK_SHARES` are retained.

The remaining parse besides the worker's exact parse is the controller's lexical inspection (it never constructs a model);
both are charged to the request and there is no persistent cache.  See `documentation/consolidation/step1/` for the manifest,
path map, capability matrix, blocked controls and qualification receipts; `CONSOLIDATION.md` and `CAPABILITIES.md` are the
pre-step-1 contract and inventory, kept as records.
