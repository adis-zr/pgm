#!/bin/bash
# Diagnostic-pass closeout (spec of 7 Nov 2026): extraction -> ledger -> report, charged as ONE packaging job; then the package is built by a
# second charged job. Idempotent; reads only the frozen manifest, the immutable primary artifacts and the diagnostic ledgers.
set -u
S=/Users/adis/Workspace/pgm/code/runs/mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06
D=$S/diag_2026-11-07
PY=/Users/adis/Workspace/pgm/code/.venv/bin/python
CH=/Users/adis/Workspace/pgm/code/bench/charge.py
cd /Users/adis/Workspace/pgm/code || exit 1
date -u > $D/closeout_started.txt
$PY $CH --ledger $D/DIAG_LEDGER.jsonl --scope diag_closeout --job diag_extraction_ledger_report --timeout 900 --cwd /Users/adis/Workspace/pgm/code -- bash -c "$PY bench/diag_extract.py $S && $PY bench/ledger.py $S && $PY bench/diag_report.py $S" > $D/closeout.log 2>&1
echo "rc=$?" >> $D/closeout.log
date -u > $D/closeout_finished.txt
tail -4 $D/closeout.log
