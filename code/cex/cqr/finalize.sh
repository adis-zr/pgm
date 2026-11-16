#!/bin/sh
# CQR FINALIZATION (fail-closed): references -> gate -> report, EACH a CHARGED, SUPERVISED job with its own receipt in $RD/CQR_LEDGER.jsonl (scopes cqr_finalize_references,
# cqr_finalize_gate, cqr_finalize_report; --mem-gib 8). The gate runs with --gate-budget-s = the manifest's verification allowance (ceiling.verification_stage_seconds) under a
# supervisor timeout of that allowance + 60 s; a gate that fails or exhausts its budget writes a structured result and the script stops (nothing downstream runs).
# The CLOSEOUT is NOT run here: it is run separately (python cex/cqr/closeout.py RD --manifest NAME --qualification PATH) AFTER the qualification record
# (cex/cqr/CQR_QUALIFICATION.json, or the path given) exists; the closeout requires the LATEST cqr_finalize_gate receipt to be COMPLETED rc 0 and the report to bind that gate.
# Usage: sh cex/cqr/finalize.sh <RUN_DIR> <MANIFEST_NAME> [CODE_DIR]      (PY may be overridden in the environment)
set -eu
RD=$1; MN=$2; CODE=${3:-$(cd "$(dirname "$0")/../.." && pwd)}; PY=${PY:-/Users/adis/Workspace/pgm/code/.venv/bin/python}
cd "$CODE"
RD=$(cd "$RD" && pwd)
test -f "$RD/$MN" || { echo "manifest missing: $RD/$MN"; exit 2; }
test -f "$RD/CAMPAIGN_START.json" || { echo "CAMPAIGN_START missing (no dispatcher run)"; exit 8; }
ls "$RD"/MANIFEST_AMENDMENT_* >/dev/null 2>&1 && { echo "amendment files present: the frozen identity is immutable"; exit 9; }
SUP="$PY -m gbidi.supervise --ledger $RD/CQR_LEDGER.jsonl --mem-gib 8"
GB=$($PY -c "import json; m=json.load(open('$RD/$MN')); print(int(m['ceiling']['verification_stage_seconds']))")
RB=$($PY -c "import json; m=json.load(open('$RD/$MN')); print(int(m['ceiling']['offline_reference_total_seconds']))")
echo "finalize: RD=$RD manifest=$MN gate budget ${GB}s reference cap ${RB}s"
$SUP --scope cqr_finalize_references --job dev_finalize:references --timeout $RB --stdout "$RD/references_stdout.txt" --stderr "$RD/references_stderr.txt" -- $PY cex/cqr/references.py "$RD" --manifest "$MN" || { echo "reference stage failed (see $RD/references_stderr.txt)"; exit 11; }
test -f "$RD/REFERENCES_R0.json" || { echo "reference artifact missing"; exit 11; }
$SUP --scope cqr_finalize_gate --job dev_finalize:gate --timeout $((GB + 60)) --stdout "$RD/gate_stdout.txt" --stderr "$RD/gate_stderr.txt" -- $PY cex/cqr/gate.py "$RD" --manifest "$MN" --gate-budget-s $GB || { echo "GATE FAILED or UNVERIFIABLE: finalization stopped; see $RD/GATE_RESULT.json"; head -c 1500 "$RD/gate_stdout.txt"; exit 6; }
head -c 600 "$RD/gate_stdout.txt"; echo
$SUP --scope cqr_finalize_report --job dev_finalize:report --timeout 1200 --stdout "$RD/report_stdout.txt" --stderr "$RD/report_stderr.txt" -- $PY cex/cqr/report.py "$RD" --manifest "$MN" || { echo "report stage failed (see $RD/report_stderr.txt)"; exit 12; }
tail -c 400 "$RD/report_stdout.txt"; echo
echo "FINALIZE_DONE (closeout is run separately once the qualification record exists)"
