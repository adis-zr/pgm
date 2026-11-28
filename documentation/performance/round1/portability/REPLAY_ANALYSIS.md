# Reproduce the recorded analysis on another machine

This replay reads the frozen benchmark outputs and checks their analysis. It
runs no inference, does not execute the archived Linux binaries, and changes no
freeze, raw result, receipt or original report. Use Python 3.12. Analysis itself
needs only the standard library.

1. Restore or check out the supplied final review commit in a **new directory**.
   It contains the frozen implementation plus the disclosed path-resolution
   fix. The existing baseline checkout can provide the prerequisite for the
   incremental Git bundle; use the accompanying handoff to import its branch.
2. Extract the raw run archive into a separate directory. Keep `FREEZE.json`,
   `RECEIPTS.jsonl`, `runs/`, `artifacts/`, `setup/`, and `frozen_analysis/` intact.
3. Run the supplied wrapper, using an empty output directory outside both the
   source checkout and the archived run:

```bash
python3 replay_analysis.py \
  --code-checkout /absolute/path/to/restored-pgm \
  --run-dir /absolute/path/to/raw-run \
  --output-dir /absolute/path/to/new-analysis-replay
```

The wrapper resolves all 122 model/evidence files and the historical preservation
reference inside the restored checkout and checks their original SHA256 hashes.
It refuses attempts to open files under either creator-workstation source root.
The result reader itself must match the frozen reader hash. It recomputes all
732 cells from raw outputs and receipts, then requires `ANALYSIS.json`,
`PAIRS.csv`, and `REPORT.md` to match the original files under `frozen_analysis/`
byte for byte.

Read `REPLAY_RECEIPT.json` in the new output directory. For this campaign, the
expected result is **`replay_ok: true` with process exit code 1**: the original
campaign has a validity FAIL, and the replay preserves that verdict. Exit code 1
here is not a failure to reproduce. Exit code 2 means the replay, path binding,
provenance or report comparison failed. A campaign with validity PASS would
return 0 instead.

The supplied Linux restore receipt records the source closure restored from
`d33d40a`, the analyzer-only portability overlay, 122 relocated input files,
one relocated historical reference, and all three identical reports. The
creator's source directories remained present but were unavailable for file
reads during this test; no original model or reference file was reused.

To measure inference on a Mac, build and qualify native kernels and libDAI on
that machine and declare a **new** benchmark run with a new setup and freeze.
Do not resume Linux receipts or compare cross-host wall times as paired timings.
