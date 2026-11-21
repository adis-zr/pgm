# pgm — certified inference: implementation library

This repository holds the implementation only: the solvers, checkers, supervisor, comparator adapters, generators and tests of the certified-inference
research program (October–November 2026) that are still executed or hashed by the live campaign chain. The research record (handoffs, reviews, ledgers, run
directories with receipts and results) lives in a separate full-history repository, `pgm-records`, which is not published; this code is what those records
were produced with. Earlier passes (direct-query pilot, NF and H4 diagnostics, MDI integrated pass, aggregate DP, discarded-mass certificate, BIDI native pilot,
GENERAL_BIDI V2 / V3, their closeouts and test suites) were removed from the working tree on 18 Nov 2026; they remain in the git history (every commit before
the cleanup, e.g. `5ae02ff`) and their closeouts are in `pgm-records`.

## Layout (`code/`)

| package | role |
|---|---|
| `cex/cqr` | **Certified Query Refinement** candidate: finite task language, certificate-carrying reduction compiler, prefix frontier, ratio / signed streams, protected exact reference, independent checker, worker, dispatcher (`campaign.py`), gate / references / report / closeout, qualification suite, resolver, schedule, WMC converter |
| `cex/pac` | the repaired PAC empirical candidate (v4.3): supplies the frozen comparator R0 (`H1_HYBRID`) and the baseline arms (P1, A0, A1), the comparator cell runner and the baseline gate / registry / qualification the CQR chain reuses |
| `cex/newarm` | the exact executor and reduction core (`core.py` shared UAI reader, `reduction.py`, `support.py`, `dag.py`, `forest.py`, `stream*.py`, `planning.py`, `geometry.py`; C++ kernels `libcex_kernel` / `libstream_kernel`) |
| `cex/b0_frozen_v14`, `cex/newarm_dev`, `cex/baseline` | frozen snapshots of the executor kept for identity (the B0 anchor arm; the PAC qualification's isolated replay copies); read-only |
| `cex/blockres` | the block-contraction engine of the Nov 19-21 rounds: `integrated.py` (frozen research baseline v2.9.4, pgm 03f7d76), `blockres.py` (exact-integer contraction + bookkeeping it imports), `run_paired.py` (paired candidate / incumbent cells under the supervisor), `report.py`, the control suites `check_*.py`, `NOTE.md` (the mathematics, sections 1-19a) |
| `cex/gate_controls.py`, `cex/locked_plan.py` | negative controls and the locked-plan check run by the frozen executors' own qualification |
| `gbidi/supervise.py` | the charging supervisor every scored cell and finalize stage runs under (sampled process-tree RSS kill, deadlines, receipts, survivor diagnostics) |
| `bench/cells.py`, `bench/pgmax_mar.py`, `bench/cbi_adapter.py`, `bench/libdai/libdai_mar.cpp` | comparator cell runners and glue (libDAI exact / LBP, Merlin WMB / IJGP, PGMax); the host-built `libdai_mar` binary and the external executables are not included |
| `ext/uai.py`, `ext/supervise.py`, `ext/comparator/` | the UAI reader every adapter imports, the adapters' runner, the Merlin adapter and its pin |
| `cbi`, `sf`, `h4a`, `native` | native cohorts: coupled-block inference library (`CBI_NATIVE`), sparse/Fourier two-block laws (`SF_NATIVE_SELECT`), H4 arithmetic nodes (`H4_NATIVE_*`) and the C++ sources of their executables |
| `build/`, `PINNED_BINARIES.json` | the exact pinned H4 executables and kernel binaries whose sha256 the frozen build records carry (a rebuild from source yields a different hash) |
| `tests` | the conformance suites of the native cohorts and the adapter tests; the CQR suite is `cex/cqr/qualification.py` (+ `test_cqr_provenance_intake.py`, `test_acquire.py`), the PAC suite `cex/pac/qualification.py` |

## Running

Python 3.12 virtual environment at `code/.venv` (numpy, gmpy2, psutil); PGMax lives in a separate `code/.venv-pgmax`. Both are ignored by git. Workers are
invoked per cell by the campaign chain (`cex/cqr/campaign.py`, `cex/pac/campaign.py`) under `gbidi/supervise.py`; everything a worker writes goes to
`code/runs/…`, which is ignored here and tracked in `pgm-records`. A few scripts read overseer-supplied inputs under `docs/…` (also in `pgm-records`);
locally, `docs` and `code/runs` are symlinks into that repository.

## Status (18 Nov 2026)

Nothing here is a performance claim. `main` is the identity the scored CQR campaign was frozen on (`0d7cc6a`: qualification suite v10 PASS 28/28,
admission_v16 qualified) plus this cleanup, which changes none of the 159 hashed artifacts of that identity. That campaign is PAUSED (PARTIAL / PAUSED FOR
ARCHITECTURAL REVISION) and is never resumed on later code. The structured-execution revision (diagnostics sidecar, cumulative-credit reference service,
structural executors as typed adapters; suite v11 PASS 31/31, admission_v17 qualified) is on branch `cqr-structured-exec-2026-11-17`, STOPPED FOR REVIEW and
not merged. See the research ledger in `pgm-records/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md` (entry E-MDI-45 and its continuations).

## Cleanup (21 Nov 2026)

Dead code removed from the working tree after the block-contraction implementation pass closed (all of it remains in git history at `03f7d76` and earlier): `cex/fastloop` and
`cex/cqr_amend` (the Nov 17-18 A1 fast-loop repair runner and amendment verification; imported by nothing; their records and reproduction commands are in `pgm-records`), the
round 1-8 block-contraction solver arms inside `cex/blockres/blockres.py` (deterministic refinement, ratio / signed streams, the v1 mini-bucket arm, the CLI) together with their
superseded controls and runners (`check.py`, `check_integrated.py`, `check_integrated_containment.py`, `run_cells.py`, `run_panel.sh`). `blockres.py` keeps exactly the definition
closure `integrated.py` and the nine live control suites use, byte-identical in every kept definition. `integrated.py` is byte-identical to the frozen baseline. Not removed, by
design: the identity-hashed scopes of the HELD CQR campaign (`cex/pac`, `cex/newarm`, `cex/b0_frozen_v14`, `gbidi`, `cbi`, `sf`, `h4a`, the comparator glue, the pinned binaries),
`cex/cqr` (the incumbent arm of every paired run), the PAC qualification's replay snapshots (`cex/baseline`, `cex/newarm_dev`), and the git-ignored PGMax comparator environment
`code/.venv-pgmax` (2.5 GB; its 194-package freeze is recorded in `pgm-records` as `VENV_PGMAX_FREEZE_2026-11-21.txt`). Regression evidence: 62 pytest tests, all 83 block-contraction
controls, and the 9-cell nonregression panel (deterministic cells interval-identical to round 17; PAC cells identical in outcome and count, differing only in the wall-clock-driven
draw count as they do between any two runs).

