# pgm — certified inference: implementation library

This repository holds the implementation only: every solver, checker, supervisor, adapter, generator and test written for the certified-inference
research program (October–November 2026). The research record (handoffs, reviews, ledgers, run directories with receipts and results) lives in a
separate full-history repository, `pgm-records`, which is not published; this code is what those records were produced with.

## Layout (`code/`)

| package | role |
|---|---|
| `cex/cqr` | **Certified Query Refinement** candidate (16 Nov 2026): finite task language, certificate-carrying reduction compiler (evidence / support / leaf sum-out / component omission / symmetry; exact proportional-slice quotient; checked approximate quotient; affine support with linear-map views; influence deletion; concentration), prefix-cell frontier with typed bounds, deterministic root bounds, full-support ratio stream and fixed-candidate signed-residual stream, protected exact reference, end-to-end checker, worker, independent oracle, mechanism-family generators, external-input acquisition, campaign chain, 13-group qualification suite |
| `cex/pac` | the repaired PAC empirical candidate (v4.3): hybrid controller, PAC engine, gate, references, report, closeout, registry, qualification |
| `cex/newarm` | the exact executor and reduction core (`core.py` shared reader, `reduction.py`, `support.py`, `dag.py`, `forest.py`, kernels in C++) |
| `cex/b0_frozen_v14`, `cex/newarm_dev`, `cex/baseline` | frozen snapshots of the executor kept for identity (the B0 anchor arm; the qualification's isolated replay copy) |
| `gbidi`, `gbidi3`, `bidi` | bidirectional kernels and the charging supervisor (`gbidi/supervise.py`: sampled process-tree RSS, deadlines, receipts) |
| `sf`, `cbi`, `h4a`, `native` | native cohorts: sparse/Fourier two-block laws, coupled-block inference library, H4 arithmetic nodes |
| `mdi`, `adp`, `nd`, `nf`, `dq`, `h4q`, `portfolio`, `validation` | earlier passes (direct-query pilot, aggregate DP, census, certificates); retained as implemented |
| `ext`, `bench` | repository readers and the comparator adapters (libDAI, Merlin, PGMax glue); the external binaries themselves are not included |
| `tests` | the test suites of every pass |
| `build/`, `PINNED_BINARIES.json` | the exact pinned H4 executables and kernel binaries whose sha256 the frozen build records carry (a rebuild from source yields a different hash) |

## Running

Python 3.12 virtual environment at `code/.venv` (numpy, gmpy2); PGMax lives in a separate `code/.venv-pgmax`. Both are ignored by git. Workers are
invoked per cell by the campaign chain (`cex/cqr/campaign.py`, `cex/pac/campaign.py`) under `gbidi/supervise.py`; everything a worker writes goes to
`code/runs/…`, which is ignored here and tracked in `pgm-records`. A few scripts read overseer-supplied inputs under `docs/…` (also in `pgm-records`);
locally, `docs` and `code/runs` are symlinks into that repository.

## Status

Nothing here is a performance claim. The most recent candidate (`cex/cqr`) is qualified (13/13) and admitted on development seeds only; the proposed
scored campaign is resolved but not frozen and not launched. See the research ledger in `pgm-records/docs/LEDGER_ADDITIONS_mdi_capacity_2026-11-02.md`.
