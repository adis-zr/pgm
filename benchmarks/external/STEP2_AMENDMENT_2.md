# STEP2_AMENDMENT_2 -- post-run ANALYSIS amendment (27 Nov 2026, after the 732-cell run completed)

No cell, receipt, input, policy, rate or inference code changed. The frozen analyzer's outputs are preserved beside the
amended ones (`ANALYSIS.frozen_analyzer_v1.json`, `GATES.frozen_analyzer_v1.json`, `REPORT.frozen_analyzer_v1.md`,
`PAIRS.frozen_analyzer_v1.csv`). Two items:

1. **Legacy internal-wall rule reclassified as a diagnostic.** Amendment 1 made the PGM_REFERENCE reader flag
   `internal wall exceeds the allowance` whenever the pinned engine's own `wall_s` exceeded 19.5 s. The engine's contract
   is the outer 20 s receipt plus its 19.5 s budget; at DEADLINE it keeps the partial rows computed before the deadline and
   its `wall_s` includes the deadline handling and serialization, so 16 non-completing reference cells (outer receipt
   19.6-19.7 s, `DEADLINE_PARTIAL`, never counted as completions) were marked contract-faulty, failing `validity` for a
   reason that is not a defect of any arm. The rule is now recorded as `legacy_internal_wall_past_allowance` (diagnostic);
   completion still requires the outer receipt <= 20 s and every requested coordinate; the new public arms are held to
   `hard_deadline_respected`. The analyzer records the 16 cell-time reclassifications under
   `gates.validity.amendment_2_reclassified_non_publishing_legacy_cells`. Regression: `tests/test_benchmark_validator.py`.
2. **Operator identity incident recorded, not removed.** During the frozen run the operator edited a tracked documentation
   file (`documentation/consolidation/step1/START_HERE.md`); the harness identity guard aborted before cell 115 and the
   cell that was in flight at the edit, `exposed_regression__DBN_11__LIBDAI_BP__r1`, has `identity_ok = false` in its
   post-cell check. The edit was reverted byte-for-byte and the run resumed under the same freeze (`CAMPAIGN_OPERATOR.log`).
   The differing file is documentation outside every arm's execution closure, and the cell's artifacts are valid, but the
   frozen `validity` gate keeps the failure. The analyzer adds `validity_excluding_operator_identity_incident` (the same
   predicate with that one recorded incident set aside) so the reviewer can decide; `promotion_decision` is derived from the
   frozen `validity` and therefore stays HOLD.

Also added for the report: the paired-overhead decomposition of every same-round mutual completion (controller wall, worker
wall, common-contract overhead = controller minus worker, reference internal wall) so the cost flags can be read against the
fixed per-request cost of the common contract.
