# DGP10 implementation review

Reviewed frozen code `13c43024d671b36a6d9262583bfbdaf9762183d8`, with the uploaded archive left unchanged. This review covers reservation ownership, runner refusal/finalization paths, native heat-bath allocation and the exact-fallback admission. The mathematical response certificate is reviewed separately.

## Findings reproduced

### CR1 — Certificate-setup log cache is not released on refusal (P2, fixed in consolidation working tree)

Source: `code/cex/hp/spectral_heatbath_run.py:107–109`, with finalization at lines 61–65 and 224–226.

The request-scoped `SW.LogCache(B, wclock, 'certificate log cache')` is outside the new spectral-witness reservation transaction. Its only `release()` call is the successful end of setup. A deadline, memory refusal or another exception after the cache has acquired a chunk skips that release. The runner's finalizer closes the chain and spectral witness, but has no reference to this cache owner.

A two-variable model and a deadline injected immediately after the first real charged certificate-cache entry give:

- canonical charge: 656 B;
- final live charge: 131,728 B;
- orphan: **131,072 B**;
- `constructor_live_ledger_identity: false`;
- typed DEADLINE, zero rows published.

This is a remaining resource-accounting defect, not evidence of a wrong archived marginal. It matters when this standalone constructor is reused under a shared switchboard budget. The archived 174 cells did not exercise this exit.

Reproduce: `python dgp10_review/probes/probe_certificate_cache.py`. Raw result: `probes/CERTIFICATE_CACHE_RESULT.json`.

Repair applied to the live consolidation repository: wrap certificate setup in `try/finally: cache.release()`. `tests/test_dgp10_cache_cleanup.py` exercises DEADLINE, MEMORY and unexpected-exception exits after a genuine charged allocation and requires zero publications and the ledger restored to canonical charge. All three subcases pass. No archived file was changed.

### CR2 — Exact-fallback memory estimate omits common-denominator growth (P2, fixed in consolidation working tree)

Source: `code/cex/hp/heatbath_native.py:178–181`, used by `_resolve()` at lines 270 onward; `heatbath_exact.integerize` and `decide_exact`.

The former estimate is proportional to `k * b`, where `b` bounds a conditional weight's numerator-plus-denominator bits and `k` is cardinality. Clearing unrelated denominators can require `k*b` bits **per integer weight**. The integer and cumulative rows therefore require order `k^2*b` storage. The old multiplier does not bound that growth.

A deterministic 64-state row of nearly-one positive fractions with pairwise-coprime 1,025-bit denominators gives:

- old admitted fallback estimate: **82,944 B**;
- independently traced peak for `integerize` alone: **588,012 B** (7.09×);
- largest cleared integer: 65,537 bits;
- inputs allocated before tracing; weights construction, cumulative sums and refinement excluded from this peak.

The entries fit the accepted per-rational bit range and nearly-one weights do not require an extreme native range. This is a resource-admission defect; no incorrect sample law or archived answer is demonstrated.

Reproduce: `python dgp10_review/probes/probe_fallback_admission.py`. Raw result: `probes/FALLBACK_ADMISSION_RESULT.json`.

Repair applied to the live consolidation repository: bound the common denominator, cleared integer row, cumulative sums, bounded refinement temporaries and state copies explicitly. The same fixture is now charged 2,807,672 B; a 100,000 B budget refuses before `weights_exact`, with ledger live zero. `tests/test_dgp10_fallback_admission.py` checks the traced materialization and admission order. The larger estimate affects only ambiguous native draws that enter the exact fallback; it leaves native resolved draws and all probability calculations unchanged. It can correctly introduce MEMORY refusals for high-cardinality/high-bit fallback work.

## Additional finding reproduced

### CR3 — Native allocation failure does not return safely (P2, fixed in consolidation working tree)

Source: `heatbath_native.c:57–72` and `100–112`.

`hb_create` immediately dereferences the result of `calloc` and copies into several unchecked `malloc` results. The observer constructor does the same. Python checks a null context / negative observer return, but the C functions can segfault before returning those values when an actual allocation fails. Charge admission is not a guarantee that the operating system allocator succeeds. Both constructors were reproduced in isolated child processes with their first allocator returning NULL: both exited with signal 11, before Python could receive a typed refusal. See `probes/probe_native_allocation_failure.py` and `probes/NATIVE_ALLOCATION_BEFORE.json`. No actual system-memory exhaustion was induced.

Repair applied to the live C source: check every allocation, free partially constructed contexts/observer arrays, return NULL or error -4, and leave an observer-failed context reusable. Additional small admission checks reject invalid dimensions/offsets before indexed allocation. No transition, random-bit, observer-arithmetic or certificate formula changed. `tests/test_heatbath_allocation_failure.py` sweeps all 21 context and 15 observer allocation ordinals; every failure returns safely, leaves no orphan allocation, and the observer can be retried successfully on the same context. The allocator-control translation unit is compiled at -O0 only to test failure paths; it is not a production arithmetic build or performance measurement. The strict Clang 19 production rebuild and DGP10 D91–D102 numerical controls subsequently passed; this is bounded qualification, not a benchmark rerun. The `hb_bytes` count now also includes the small dummy zero-pair allocations, so successful byte accounting remains explicit.

## Positive observations and scope limits

- The new shared transaction rolls back transaction-owned reservations in the tested constructor-refusal paths; successful native ownership is explicitly closed by the runner.
- Observer snapshots are taken only at completed predeclared local counts, with separate ongoing sums. The host obtains immutable snapshots between synchronous kernel calls.
- Exact fallback commits the pending observation only with the committed transition; inspection refuses while a decision's workspace is pending.
- The staged output encodes intended and suppressed payloads before the final sample. Physical replacement/write still occurs after that sample, so timely **delivery** continues to rely on the outer supervised receipt. The library API must retain that distinction.
- The runner still samples to its deadline rather than stopping once all requested rows meet tolerance; that disclosed performance behavior is not a correctness defect.
- These are bounded review probes, not an independent rerun of the complete Mac campaign. No scored data was modified or relabelled.


## Qualification of the repaired live tree

All five qualification commands completed in **49.813 s** in the Linux consolidation environment, with individual timeouts and captured stdout/stderr. Raw commands, outcomes and durations are in `qualification/RECEIPTS.json`. The frozen campaign archive remains unchanged.

- **Strict production build passed:** Clang 19.1.7 with the existing strict floating-point flags. Source SHA-256 `af6ba910827dd126c47f8ed94eb6f58b43701c72c70596e2f2fac8c809fd08d4`; generated binary SHA-256 `44550994fa5f4c8c27b8b4e5018fdd0d6875e331d404c376197611ba96fca4f0`.
- **D91–D102: 12/12 pass.** This includes matched observer-on/off random trajectory checks, exact conditional/gauge differentials, actual RESPONSE end-to-end and exact-fallback execution, and staged publication checks. The checked-tilt reference is the copy shipped inside the DGP10 harness packet, explicitly supplied by environment path.
- **New review regressions: 10/10 test methods pass.** These include the three cache exception cases, the high-cardinality fallback cap refusal, all 36 context/observer allocator failure positions, the mathematical response conflict controls and analysis-unit regressions supplied by the other reviewers.
- **Inherited D1–D90: incomplete qualification, 39/90 pass.** The remaining 51 do not exercise their intended branches in this relocated checkout: 46 directly raise `FileNotFoundError` on hardcoded original workstation fixture paths; D12 lacks three historical models; D71 has zero archived scored windows; D80 and D87 launch against missing model paths; D90 lacks its hardcoded recovered-reference directory. The suite's process exit code is zero despite `all_ok: false`; no all-suite success is claimed. See `qualification/INHERITED_BLOCKERS.json`.

No additional engine failure was observed in these bounded qualification runs. Restoring or explicitly relocating the historical fixtures/references is required before claiming the inherited 90 controls pass on this checkout. No benchmark performance result was produced or inferred.


### Final portable accepted-engine qualification

After the Linux native builds were warmed with the actual consolidation Clang 19 toolchain, the additional accepted controls passed in **33.02 s**: round 12 (11/11), round 15 (3/3), round 16 (6/6), round 17 (4/4). The native CEX smoke passed all 40 trials (19 certified, 21 zero-evidence, no stops; all independently contained). Commands, timing receipts and complete logs are in `qualification/accepted/`. This does not resolve the historical missing-input limitation above.
