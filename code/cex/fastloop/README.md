# CQR fast theory–implementation–measurement loop (harness v2)

Infrastructure only (`cex/fastloop` and `cex/cqr_amend` are in no candidate inventory scope). Protocol: `pgm-records/docs/handoff-received-2026-11-18-cqr-fast-iteration/`; repairs after the A1 review: `docs/review-received-2026-11-18-cqr-a1-fastloop/`.

| step | command (from the CANDIDATE worktree's `code/`) | cap |
|---|---|---|
| pin the development manifest (once per version) | `python cex/fastloop/manifest.py materialize --baseline <ACCEPTED_BUILD> --out <RECORDS>/fastloop/manifest_vN` | — |
| prepare the authenticated truth cache (once) | `python cex/fastloop/truth_prep.py --manifest <MANIFEST> --baseline <ACCEPTED_BUILD>` | recorded |
| calibrate (once; R0 anchor + measured size ladder; pins the change-specific pair) | `python cex/fastloop/calibrate.py --manifest <MANIFEST> --baseline <ACCEPTED_BUILD> --out <RECORDS>/fastloop/calibration_N` | 600 s |
| harness controls battery (after any harness change) | `python cex/fastloop/controls.py --out <RECORDS>/fastloop/controls_N --baseline <ACCEPTED_BUILD> --manifest <MANIFEST>` | — |
| smoke subset (while editing) | `python cex/fastloop/run.py --manifest <MANIFEST> --candidate . --baseline <ACCEPTED_BUILD> --out <RUN_DIR> --mode smoke` | 60 s target |
| full development run (every meaningful change) | `python cex/fastloop/run.py --manifest <MANIFEST> --candidate . --baseline <ACCEPTED_BUILD> --out <RUN_DIR> --mode full --hypothesis HYPOTHESIS.json --label "<change>"` | 300 s hard, 12 s finalization reserve |

Launch every run as ONE charged job: `python -m gbidi.supervise --ledger <RECORDS>/fastloop/CQR_LEDGER.jsonl --scope cqr_fastloop --job fastloop:<label> --timeout 330 --mem-gib 8 -- <command>`.

Invariants (v2): one absolute deadline for identity, inputs, workers, truth, verification, controls, cleanup and report; bounded subprocesses everywhere; the report is written after every cell and in `finally`; pinned task bytes validated and SNAPSHOTTED before any launch, the worker's consumed binding compared (drift = TASK_INTEGRITY stop); truth records authenticated (task digest, oracle dependency identity, content seal; CACHE_INTEGRITY is a harness failure, never a solver miss); each build verified by its OWN checker in its own process, source / loader-provenance / arm mismatch = refusal, a checker exception = CHECKER_FAULT; supervisor × worker × cleanup × expected-control reconciliation (FAULT, abnormal exit, NO_OUTPUT, hard kill are typed); PROVED_ZERO_EVIDENCE verified and compared with independent truth; REQUIRED negative controls pass only on normal checker completion for the intended class, missing ones make the run INCOMPLETE; three separate verdicts (execution / correctness / required coverage) with precise predicates from checker-verified facts (channel A) and labelled sidecar observations with ages (channel B). Nothing is PASS.

`cex/cqr_amend/amend_verification.py`: prepare / execute a SEPARATELY identified re-verification of a completed shard (producer identity from the frozen manifest, verifier identity from the build; producer-side source differences are refused; the original gate is retained). `execute` only after review.
