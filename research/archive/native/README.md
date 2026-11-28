# Historical native artifacts

The early `dq*` and `nf*` sources and their shared headers are retained unchanged
for research provenance. The three `h4_binaries` executables are the historical
pinned build bytes; the original `PINNED_BINARIES.json` is retained with its
original path keys and hashes. Those keys describe the old layout, not runtime
lookup locations.

Active H4 kernel sources now ship under `pgm.algorithms.h4/native`. Explicit host
builds use an external cache and never select the executables in this archive.
