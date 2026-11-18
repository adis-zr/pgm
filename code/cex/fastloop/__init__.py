"""CQR FAST ITERATION LOOP (overseer protocol of 18 Nov 2026): a 30-60 s smoke subset and a <= 300 s all-in development run that executes a PINNED development manifest against a
candidate build and ONE relevant comparator per row, verifies every publication with the build's OWN checker (source-isolated) and against INDEPENDENT truth (cached by task digest),
and writes ITERATION_REPORT.md / .json. Harness infrastructure OUTSIDE the candidate identity (cex/fastloop is in no registry scope). It never changes a solver, never relaxes a check,
and never runs on the host of a frozen scored campaign without an explicitly recorded window."""
FASTLOOP_VERSION = 'cqr-fastloop-v1 (2026-11-18)'
