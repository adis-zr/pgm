#!/bin/bash
# Post-depth closeout in the spec's order: references (2,400 s allowance, 300 s per job) -> diagnostics (1,200 s, predeclared rules) ->
# blockers -> score -> budget ledger -> report. Each supervised numerical step charges itself; scoring / reporting are charged as one
# packaging/closeout job. Idempotent: completed reference files and labelled diagnostic rows are not repeated.
set -u
S=/Users/adis/Workspace/pgm/code/runs/mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06
PY=/Users/adis/Workspace/pgm/code/.venv/bin/python
CH=/Users/adis/Workspace/pgm/code/bench/charge.py
cd /Users/adis/Workspace/pgm/code || exit 1
date -u > $S/closeout_started.txt
$PY bench/references.py $S 2400 2>&1 | tee $S/references.log
$PY $CH --ledger $S/SETUP_LEDGER.jsonl --scope diagnostics_supervisor --job diagnostics_stage --timeout 1500 --cwd /Users/adis/Workspace/pgm/code -- $PY bench/diagnostics.py $S > $S/diagnostics.log 2>&1
$PY $CH --ledger $S/SETUP_LEDGER.jsonl --scope packaging --job scoring_and_report --timeout 600 --cwd /Users/adis/Workspace/pgm/code -- bash -c "$PY bench/blockers.py $S && $PY bench/score.py $S && $PY bench/ledger.py $S && $PY bench/report.py $S" > $S/closeout.log 2>&1
date -u > $S/closeout_finished.txt
tail -3 $S/closeout.log
