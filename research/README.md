# Research workspace

This directory contains the actual experiment code and historical material. The
installed library lives entirely under `src/pgm` and never imports `research`.

| Directory | Contents | Execution |
|---|---|---|
| `campaigns/hp` | HP and DGP experiments, controls, oracles and reporting | Current package imports; `python -m research.campaigns.hp.check_dgp10 OUT.json` |
| `campaigns/blockres` | Block-contraction experiments and controls | Current package imports |
| `campaigns/structural` | Structural experiments and qualification tools | Current imports; some studies require recorded private inputs |
| `campaigns/cqr`, `cbi`, `sf`, `h4` | Specialist experiments and generators | Runtime algorithms imported from `pgm.algorithms` |
| `archive` | Frozen snapshots, historical native artifacts, retired layout tools and tests | Restore the original commit for historical execution |
| `comparators` | Historical comparison integrations | Research-only dependencies |

Run current campaign modules from the repository root with the installed package
or `PYTHONPATH=src:.`. Runtime methods also work without this checkout via
`pgm.method("cqr")`, `pgm.method("cbi")`, `pgm.method("sf")` and `pgm.method("h4")`.

`research.paths` resolves `PGM_RECORDS_ROOT` first, otherwise a sibling
`pgm-records` checkout. That external repository retains its historical
`code/runs` schema. Without a records repository, new outputs use ignored
`research/runs`. An explicitly configured missing input is not silently
replaced. No `code/runs` symlink is needed in this repository.

The historical step-1 classification is preserved under
`archive/layout_tools/CLASSIFICATION_STEP1.json`; it is not a current inventory.
The complete old-file disposition map is
`documentation/migration/complete-layout/MIGRATION.json`. It accounts for every
former tracked `code/` file, including wrappers whose canonical implementation
already existed. Old scored records and frozen archive bytes are not rewritten.

For recorded benchmark replay, use `benchmarks/external/replay_frozen.py`: it
restores the recorded source commit before running the original hash-checked
analyzer. A refactored harness does not have a historical harness's identity.
