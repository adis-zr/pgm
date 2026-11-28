# Incumbent-first performance round

Read `REPORT.md` for the decision and limitations. The frozen analyzer returns **ELIGIBLE**: 732/732 cells, all seven release gates pass, 52 automatic both-repeat completions, no lost full completion against the same-round baseline union or previous 50-task automatic target. The accepted default stays unchanged. Broad latency dominance over libDAI is not established, and the 1qt9 partial-answer loss is reported.

- `IMPLEMENTATION.md`: algorithm and runtime changes.
- `ROUND_DECISION.json`: machine-readable release decision.
- `results/FROZEN_REPORT.md`, `ANALYSIS.json`, `PAIRS.csv`, `ALL_TASKS.csv`: unchanged frozen results and cell summaries.
- `results/FREEZE.json`: exact sources, inputs, protocol, dependencies and executable identities.
- `qualification/`: pre-freeze commands, controls, parity and logs.
- `INDEPENDENT_REVIEW.json` and `.md`: independent recomputation and caveats.
- `RAW_ARCHIVE.json`: full raw evidence archive identity.
- `portability/REPLAY_ANALYSIS.md`: relocated report replay without rerunning inference.

The delivered git bundle requires consolidation baseline `f664ee7aa06851c77e9876cea409d4a04a9e4b21` and contains both the prior performance history and this repair. The external handoff manifest names the final bundle tip, archive hashes and restore receipt. Original round-1 failed records remain in history and are not reclassified.
