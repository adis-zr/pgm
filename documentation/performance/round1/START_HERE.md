# Untuned runtime review packet

Read [REPORT.md](REPORT.md) first. This branch is a measured opt-in candidate; the accepted default is unchanged. The full-suite validity and automatic union-preservation gates remain FAIL. Broad speed dominance is not established.

- [IMPLEMENTATION.md](IMPLEMENTATION.md): exact scope and invariant boundaries.
- [ROUND_DECISION.json](ROUND_DECISION.json): identities, decisions and disclosures.
- [results/FROZEN_REPORT.md](results/FROZEN_REPORT.md), [results/ANALYSIS.json](results/ANALYSIS.json), [results/PAIRS.csv](results/PAIRS.csv): complete frozen results.
- [results/FREEZE.json](results/FREEZE.json): tasks, contracts, executed identities and toolchain.
- `development/`: pre-freeze tests, controls, parity, comparator qualification and audits.
- `portability/`: post-run amendment, analysis-equivalence tests and restored-source replay.
- `RAW_ARCHIVE.json`: full raw-log archive identity, shipped in the handoff alongside the git bundle.

No historical consolidation results or main branch were rewritten. All 61 performance tasks are exposed regression inputs.
