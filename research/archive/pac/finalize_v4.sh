#!/bin/sh
# FINALIZATION v4 (fail-closed; reviews F06, R06, R08: content- and schema-bound closeout v4): every stage's exit status is required; nothing downstream runs after a failed stage.
# Usage: sh finalize_v4.sh <RUN_DIR> <OUT_ZIP> [CODE_DIR]
set -eu
RD=$1; OUT=$2; CODE=${3:-/Users/adis/Workspace/pgm-repair-2026-11-13/code}; PY=${PY:-/Users/adis/Workspace/pgm/code/.venv/bin/python}
cd "$CODE"
grep -q SCORED_CAMPAIGN_DONE "$RD/scored_campaign.log" || { echo "campaign not finished"; exit 2; }
test -f cex/pac/PAC_QUALIFICATION.json || { echo "qualification record missing"; exit 4; }
$PY -c "import json,sys; q=json.load(open('cex/pac/PAC_QUALIFICATION.json')); sys.exit(0 if (q.get('all_pass') and q.get('passed') == q.get('total') == len(q.get('groups') or []) and str(q.get('suite_version','')).startswith('pac-qualification-v4')) else 5)" || { echo "qualification not a v4 all-pass record: finalization refused"; exit 5; }
test -f "$RD/CAMPAIGN_START.json" || { echo "CAMPAIGN_START missing"; exit 8; }
ls "$RD"/MANIFEST_AMENDMENT_* >/dev/null 2>&1 && { echo "amendment files present: the frozen identity is immutable"; exit 9; }
$PY -c "import json,sys; sys.path.insert(0,'cex/pac'); import registry; q=json.load(open('cex/pac/PAC_QUALIFICATION.json')); sys.exit(0 if sorted(g['name'] for g in q['groups']) == sorted(registry.QUALIFICATION_GROUPS) else 10)" || { echo "qualification group schema differs from the registry"; exit 10; }
$PY cex/pac/gate.py "$RD" > "$RD/gate_stdout.txt" 2>&1; GATE=$?; head -3 "$RD/gate_stdout.txt"
test $GATE -eq 0 || { echo "GATE FAILED (exit $GATE): finalization refused; see $RD/GATE_RESULT.json"; $PY cex/pac/closeout.py "$RD" || true; exit 6; }
$PY cex/pac/report.py "$RD"
$PY cex/pac/closeout.py "$RD" || { echo "closeout refused a qualified verdict"; exit 7; }
git add -A "$RD" cex/pac/PAC_QUALIFICATION.json && git commit -q -m "PAC v4 pass: receipts, gate result, RESULTS_PAC, REFERENCE_AUDIT, CLOSEOUT_PAC

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git log --oneline -1
test -e "$OUT" && { echo "archive exists"; exit 3; }
$PY -m gbidi.supervise --ledger "$RD/PAC_LEDGER.jsonl" --scope pac_packaging --job packaging:pac_v4_pass_1 --timeout 1800 --mem-gib 8 --stdout "$RD/package_pac_1.txt" --stderr "$RD/package_pac_1.err" -- $PY cex/pac/package.py "$RD" "$OUT"
tail -1 "$RD/PAC_LEDGER.jsonl" > "$OUT.receipt.json"
git add -A "$RD" && git commit -q -m "PAC v4 pass: package record + charged packaging receipt

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git log --oneline -1
echo FINALIZE_DONE
