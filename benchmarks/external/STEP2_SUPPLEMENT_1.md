# STEP2_SUPPLEMENT_1 -- prospective confirmation of the changed public runtime (declared before execution, 27 Nov 2026)

The bounded-completion pass changed the public runtime (`pgm.runtime.attempts`: staged candidate with ONE terminal acceptance
decision after final cleanup; process-incarnation ownership checks; the controller's consistency check) and tightened the
gates. The original 732-cell run (engine `f74f7f3`) is immutable and its cells, receipts and identity flags are not changed.

## Declared matrix

| what | cells |
|---|---:|
| `PGM_ACCEPTED` on all 61 exposed inputs, repeats 1 and 2 (seed = repeat) | 122 |
| `PGM_EXPERIMENTAL` on all 61 exposed inputs, repeats 1 and 2 | 122 |
| clean supplemental replay of `DBN_11 / LIBDAI_BP / r1` (original comparator build, original contract) | 1 |
| **total** | **245** |

Contract unchanged: 20 s end to end, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6, pgm allowance 19.5 s,
strict zero-grace supervisor, serial execution. **Ceiling 4,900 s = 245 x 20 s**, declared here; exhaustion returns
INCOMPLETE; never raised after a scored outcome. Setup (kernel builds / warm caches / six-arm smoke on the committed tiny
fixture) and the combined qualification are separate and reported.

## Acceptance (decided before execution)

1. validity: every recorded cell has one terminal receipt, `identity_ok` (checkout + comparator + the arm's own native closure
   before and after the cell), a valid output and a valid contract including the terminal-cleanup contract.
2. completeness: all 245 cells recorded within the ceiling.
3. preservation vs the original run: no loss from the recorded both-repeat completion sets, 45 (`PGM_ACCEPTED`) and 54
   (`PGM_EXPERIMENTAL`); gains are reported, never forbidden; one-repeat cases listed.
4. replay cell: the `DBN_11 / LIBDAI_BP / r1` replay is recorded with `identity_ok` and a valid output. The original cell keeps
   `identity_ok = false`; the original campaign's `validity` stays FAIL; the aggregate is labelled adjudicated / supplemented.
5. timing: wall times from different run periods are descriptive only; the 18 original cost flags remain reported; no causal
   cost claim is made from this supplement. A matched rerun of an old arm would be a separately declared bounded diagnostic.

## Commands

```bash
export PGM_BENCH_PY=... PGM_LIBDAI=<the original comparator build> CC=/usr/bin/clang CXX=/usr/bin/clang++
export PGM_BENCH_REFERENCE_ROOT=... PGM_BENCH_EXPERIMENTAL_REF_ROOT=...      # setup smokes all six arms; only the two public arms are scored
export PGM_BENCH_SUPPLEMENT_OF=<original run dir> PGM_BENCH_RUN_DIR=<supplement run dir>
$PGM_BENCH_PY benchmarks/external/run_suite.py setup
$PGM_BENCH_PY benchmarks/external/run_suite.py freeze-supplement
$PGM_BENCH_PY benchmarks/external/run_suite.py supplement
$PGM_BENCH_PY benchmarks/external/analyze_suite.py <supplement run dir>
```
