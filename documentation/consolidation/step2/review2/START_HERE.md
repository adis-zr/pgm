# Step-2 independent review packet

Read `PGM_STEP2_REVIEW.md`, then `CLAUDE_STEP2_BOUNDED_COMPLETION.md`.
Detailed reviews are in `runtime/REVIEW.md`, `gates/GATE_REVIEW.md` and `results/RESULTS_REVIEW.md`.

The reviewed implementation is Git commit `d45a1367101ff5d68597684aa29c1cecced76fd9` in https://github.com/adis-zr/pgm, branch `consolidate/production-layout`. Scored engine is `f74f7f3da84cade7ac2bc6776087790a0c698a73`. This packet does not replace or modify either source tree or the original scored records.

The two bounded probe scripts accept `PGM_REVIEW_ROOT` pointing to a checkout. Run with the project's Python environment:

```sh
PGM_REVIEW_ROOT=/absolute/path/to/pgm python runtime/probe_repairs.py
PGM_REVIEW_ROOT=/absolute/path/to/pgm python gates/probe_analysis_boundaries.py
```

The first script uses only its own disposable sleeper processes and cleans them on exit; the rest are injected synthetic boundaries. It demonstrates defects at the reviewed commit, not new inference measurements. `PROBE_RESULTS.json` / `ANALYSIS_BOUNDARIES.json` retain the initial outputs; `PORTABLE_PROBE_REPLAY.json` files retain replays after adding the path override. No solver code was changed.

`results/HISTORICAL_3283CFD_122_CELLS.json` is the missing historical extract, bound to model/evidence identities and the original records. Its comparison establishes retention of all 47 previous experimental completions. The original prior evidence zip is included unchanged under `historical/` so this evidence cannot disappear at handoff.

To regenerate historical extraction, unpack that nested zip to a temporary directory, set `PGM_PRIOR_RUN` to its `benchmark_runs/consolidation-v1-repaired` directory, `PGM_PRIOR_ARCHIVE` to the original nested zip, and `PGM_REVIEW_ROOT` to the reviewed checkout. Run `results/recover_historical_experimental.py`. The script writes only the two recovered result files beside itself. `results/recompute_results.py` accepts the same PGM_REVIEW_ROOT override and recomputes the current committed compact/receipt summaries.

The current 39MB step-2 raw archive was not available to this review. Original coordinate geometry was not independently replayed. Counts, receipt consistency, bounded source defects and historical preservation are independently checked. See the lead review for precise scope.

`MANIFEST.json` binds packet files by SHA-256; compiled artifacts and unrelated working directories are excluded.
