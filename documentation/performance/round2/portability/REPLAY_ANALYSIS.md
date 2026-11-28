# Replay the full benchmark analysis after relocation

Use Python 3.12 and the supplied review commit. The replay needs only the
standard library; it runs no inference and does not execute Linux binaries.
Restore the code bundle in a fresh checkout and extract the raw run archive into
a separate directory. Keep all frozen files and raw outputs unchanged.

```bash
python3 /path/to/restored-pgm/documentation/performance/round2/portability/replay_analysis.py \
  --code-checkout /path/to/restored-pgm \
  --run-dir /path/to/extracted-raw-run \
  --output-dir /path/to/new-empty-replay-directory
```

The output directory must be outside both the checkout and raw run. The wrapper
verifies the frozen hashes of `run_suite.py`, `analyze_performance.py`, and
`benchmark_validity.py`. It resolves all 122 model/evidence files, the historical
preservation reference, and the previous candidate's analysis/freeze under the
restored checkout, checking every original hash. File reads from either original
creator-source root are forbidden during replay.

It then recomputes all 732 cells from raw artifacts and receipts. `ANALYSIS.json`,
`PAIRS.csv`, and `REPORT.md` must match the copies in `frozen_analysis/` byte for
byte. The new `REPLAY_RECEIPT.json` records the resolved bindings, protected-file
hashes, report comparisons, original verdict and every release gate.

For this round the expected receipt is `replay_ok: true`, validity `PASS`, release
`ELIGIBLE`, and exit code **0**. Exit 1 means the replay matches a negative
validity/release verdict. Exit 2 means provenance, relocation or reproduction
failed. A successful replay never overwrites the original evidence.

New inference timing on another machine requires a new qualified native setup
and a new freeze. Archived Linux timings are not paired Mac measurements.
