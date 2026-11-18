# CQR fast theory–implementation–measurement loop (harness)

Infrastructure only (outside every candidate inventory scope). Protocol: `pgm-records/docs/handoff-received-2026-11-18-cqr-fast-iteration/`.

| step | command (from the CANDIDATE worktree's `code/`) | cap |
|---|---|---|
| pin the development manifest (once per manifest version) | `python cex/fastloop/manifest.py materialize --baseline <ACCEPTED_BUILD> --out <RECORDS>/fastloop/manifest_vN` | — |
| prepare the independent truth cache (once) | `python cex/fastloop/truth_prep.py --manifest <MANIFEST> --baseline <ACCEPTED_BUILD>` | recorded |
| calibrate on the accepted baseline (once; R0 anchor + size ladder; pins the change-specific pair) | `python cex/fastloop/calibrate.py --manifest <MANIFEST> --baseline <ACCEPTED_BUILD> --out <RECORDS>/fastloop/calibration_N` | 600 s |
| smoke subset (while editing) | `python cex/fastloop/run.py --manifest <MANIFEST> --candidate . --baseline <ACCEPTED_BUILD> --out <RUN_DIR> --mode smoke` | 60 s target |
| full development run (every meaningful change) | `python cex/fastloop/run.py --manifest <MANIFEST> --candidate . --baseline <ACCEPTED_BUILD> --out <RUN_DIR> --mode full --hypothesis HYPOTHESIS.json --label "<change>"` | 300 s hard |

Every run should itself be launched as ONE charged job: `python -m gbidi.supervise --ledger <RECORDS>/fastloop/CQR_LEDGER.jsonl --scope cqr_fastloop --job fastloop:<label> --timeout 330 --mem-gib 8 -- <command>`.

`HYPOTHESIS.json`: `{"change", "premise", "expected_favorable", "expected_near_miss", "preserved": [...], "question"}` — written BEFORE the run.

Outputs in `<RUN_DIR>`: `ITERATION_REPORT.md` (first screen: hypothesis, identities, status, one row per case, regressions, failures, controls, limitations, next question), `ITERATION_REPORT.json`, `cells/<n>_<id>__<tag>__<arm>/` (worker.json, worker.diag.json, check.json, stdout / stderr), `mutations/`, `CQR_LEDGER.jsonl` (one supervised receipt per cell).

Rules the harness enforces: one primary comparator per row (baseline N1 / same-build G0 / same-build matched ablation), deterministic balanced arm order, identical pinned bytes / seeds / budgets, each build verified by its OWN checker in its OWN process, independent truth from the baseline's oracle (cached by task digest; never a worker's output), structural publications counted as production success and NOT as mechanism coverage (activation read from the certificate), relaxed-tolerance rows labelled qualification-only, sidecar enclosures labelled diagnostic (compiled widths before bias), budget exhaustion / missing output / unverified publication → INCOMPLETE, a refused publication / deterministic truth miss / survivor → STOP with remaining rows NOT_RUN. Nothing is PASS.

Harness controls: `--inject-missing-output <ID>` (child exits without writing → NO_OUTPUT → INCOMPLETE), `--inject-corrupt <ID>` (a shifted COPY of the publication is verified → REFUSED → STOP), `--total-cap <s>` (exhaustion → NOT_RUN rows → INCOMPLETE).

Do not run timed development jobs on a host executing a frozen scored campaign.
