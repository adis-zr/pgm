# code/ — direct chain-query certificate pilot

Implements `docs/direct-query-theory-pass-2026-10-26/CLAUDE_CODE_SPEC.md` (frozen pilot, 26 Oct 2026). Everything here was written fresh
for this pilot; the previous strongcompact lab no longer exists (see `docs/`).

Layout: `dq/` Python (model, gate, arms, checker, supervisor, campaign, report), `native/` C++ (`dqchain.cpp` producer, `dqcheck.cpp`
independent checker kernel, `mpiv.hpp` + `dqinput.hpp` declared shared primitives), `tests/test_dq_small.py` (tiny validation + tamper
tests), `runs/<run>/` durable campaign records.

## Build and run

    /opt/homebrew/bin/python3.12 -m venv .venv && .venv/bin/pip install gmpy2 psutil pytest
    mkdir -p build
    c++ -O2 -std=c++17 -fno-fast-math -I/opt/homebrew/opt/gmp/include -I/opt/homebrew/opt/mpfr/include native/dqchain.cpp -o build/dqchain -L/opt/homebrew/opt/gmp/lib -L/opt/homebrew/opt/mpfr/lib -lmpfr -lgmp
    c++ -O2 -std=c++17 -fno-fast-math -I/opt/homebrew/opt/gmp/include -I/opt/homebrew/opt/mpfr/include native/dqcheck.cpp -o build/dqcheck -L/opt/homebrew/opt/gmp/lib -L/opt/homebrew/opt/mpfr/lib -lmpfr -lgmp
    .venv/bin/python -m pytest -q tests/                          # 24 tests (< 60 s); 7 need build/dqchain and build/dqcheck
    .venv/bin/python -m dq.campaign --run-dir runs/dq_pilot_<tag>  # stages 1-4, 1,200 s cap

`build/` and `.venv/` are untracked and are not shipped in the handoff archives: the build step must precede the tests and the campaign
(without it the 7 kernel-dependent tests fail with FileNotFoundError). The compiler flags are written out in full because zsh, the
default shell on the recorded machine, does not word-split an unquoted `$I`, so the earlier `export I=...; ... $I ...` form fails with
`mpfr.h file not found`.

Inspect: `runs/<run>/REPORT.md`, `tables.json`, `campaign_state.json`, `events.jsonl`, `resources.jsonl` (heartbeats + contention samples),
`attempts.jsonl`, `lock.json` (environment, source and binary hashes, frozen constants), `cells/<cell>/{result.json,witness.json,input.txt,
producer_fb*/producer.json,checker_fb*/{verdict.json,checker_kernel.json}}`.

## Numerical design (what the checker and producer actually do)

Two-state chain; unary weights exp(±(h_i − a_i c)) as directed MPFR intervals; forward/backward messages scaled by exact powers of two
(interval normalisation by dependent sums overflows after ~100 sites). Real passes are full interval arithmetic. Complex passes propagate
point messages with one rigorously propagated relative-error scalar against the exact real chain (rectangle arithmetic wraps and overflows on
signed quantities): the producer sweeps forward from the marker, the checker sweeps backward and applies the marker at site 0. The per-site
error coefficient and the closed-form ceiling S_max = 48·n·2^-P under the enforced proof domain are derived in
`runs/dq_pilot_2026-10-26/amendments/NUMERICAL_PROOF_REPAIR.md` (amendment 1, 27 Oct 2026); the checker treats the ceiling as the binding
allowance and rejects any input/witness outside the domain. Centre: 17
gradient updates with step 2/5 from c = 0, rounded to the 2^-64 grid; a separate final real pass certifies the residual |c − E_Q AX| and q_0.
The checker binds the residual requirement to the frozen 1/8 and requires complete frequency arrays k = 1..J on both sides (amendment 2).
Gate and checker verify the frozen declared constants (K = 99/46, V̄ = 2079/1472, L = 15/32, E_0 = 3/800; CONTROL K = 63/17, L = 1/4) against
input-derived exact quantities (alternating closed form for K, exact M, (1 − x/8)^8 floor, RoundUp influence sum) before use.

## Normalization-free certificate clearance diagnostic (26/27 Oct 2026) — `nf/`, `native/nfchain.cpp`, `native/nfcheck.cpp`

Fresh positive-real implementation of `docs/normalization-free-diagnostic-v1/CLAUDE_CODE_SPEC.md` (bounded diagnostic; not a campaign). `nf/model.py`
(exact generator, fixtures, geometry verification), `nf/certs.py` (frozen formulas, exact rational bounds), `nf/check.py` (independent binding
checks), `nf/validate.py` + `tests/test_nf_small.py` (fixtures vs 256-bit enumeration, rejection suite), `nf/run.py` (driver: stages A/B/C, external
deadlines, durable records), `nf/report.py`, `nf/replay.py`, `nf/closeout.py`. Outcome in `runs/nf_diag_2026-10-26/REPORT.md`:
**OLD_CHEAP_ALREADY_SUFFICIENT** (both cheap certificates pass at width 1/100; Stage C not run). Reproduce: `runs/nf_diag_2026-10-26/REPRODUCE.md`.
