#!/bin/sh
# FINALIZATION v6 (fail-closed; reviews F06, R06, R08, fourth review F05/F06, FIFTH review R05 stage-cap reconciliation + supervisor-kill policy): every stage is a CHARGED, SUPERVISED, AGGREGATE-CAPPED job with its own receipt;
# the sequence is qualification record -> references (fresh, manifest-bound) -> gate (aggregate budget from the manifest ceiling) -> report -> closeout -> packaging;
# a stage KILLED by its supervisor (timeout / memory) leaves NO qualified artifact: the supervisor RECEIPT in PAC_LEDGER.jsonl is the authoritative failure record and the
# chain stops (set -e); no stage promises to write a result after SIGKILL -- the closeout then finds the stage artifact missing / stale / unbound and refuses;
# the reporting / closeout / packaging allowance of the manifest ceiling (3600 s) is the SUM of the three per-stage hard caps below (1200 + 600 + 1800; reconciled).
# RETRY POLICY (sixth review S2): the closeout binds to the LATEST verification-stage attempt recorded in the ledger (scope pac_finalize_gate): a failed or killed retry
# leaves the chain UNQUALIFIED until the gate is re-run successfully, even when an earlier GATE_RESULT is unchanged (the earlier proof may still be mathematically valid;
# the completion criterion is the latest attempt).
# nothing downstream runs after a failed stage; a gate that exhausts its budget writes a structured UNVERIFIABLE result and the closeout refuses it.
# Usage: sh finalize_v6.sh <RUN_DIR> <OUT_ZIP> [CODE_DIR] [MANIFEST_NAME]
set -eu
RD=$1; OUT=$2; CODE=${3:-/Users/adis/Workspace/pgm-repair-2026-11-13/code}; MN=${4:-CAMPAIGN_MANIFEST.json}; PY=${PY:-/Users/adis/Workspace/pgm/code/.venv/bin/python}
cd "$CODE"
SUP="$PY -m gbidi.supervise --ledger $RD/PAC_LEDGER.jsonl --mem-gib 8"
test -f "$RD/$MN" || { echo "manifest missing"; exit 2; }
test -f "$RD/CAMPAIGN_START.json" || { echo "CAMPAIGN_START missing"; exit 8; }
ls "$RD"/MANIFEST_AMENDMENT_* >/dev/null 2>&1 && { echo "amendment files present: the frozen identity is immutable"; exit 9; }
grep -q SCORED_CAMPAIGN_DONE "$RD/scored_campaign.log" 2>/dev/null || { echo "campaign not finished (SCORED_CAMPAIGN_DONE sentinel absent)"; exit 2; }
test -f cex/pac/PAC_QUALIFICATION.json || { echo "qualification record missing"; exit 4; }
$PY -c "import json,sys; sys.path.insert(0,'cex/pac'); import registry; q=json.load(open('cex/pac/PAC_QUALIFICATION.json')); sys.exit(0 if (q.get('all_pass') and q.get('passed') == q.get('total') == len(q.get('groups') or []) and str(q.get('suite_version','')).startswith('pac-qualification-v4.2') and sorted(g['name'] for g in q['groups']) == sorted(registry.QUALIFICATION_GROUPS) and not q.get('sources_changed_during_run')) else 5)" || { echo "qualification record not a v4 all-pass record with the registry schema: finalization refused"; exit 5; }
GB=$($PY -c "import json; m=json.load(open('$RD/$MN')); print(int(m['ceiling'].get('verification_stage_seconds', 1800)))"); RB=$($PY -c "import json; m=json.load(open('$RD/$MN')); print(int(m['ceiling'].get('offline_reference_total_seconds', 7200)))")
$SUP --scope pac_finalize_references --job finalize:references --timeout $RB -- $PY cex/pac/references.py "$RD" --manifest "$MN" || { echo "reference stage failed"; exit 11; }
test -f "$RD/REFERENCES_R0.json" || { echo "reference artifact missing"; exit 11; }
$SUP --scope pac_finalize_gate --job finalize:gate --timeout $((GB + 60)) -- $PY cex/pac/gate.py "$RD" --manifest "$MN" --gate-budget-s $GB > "$RD/gate_stdout.txt" 2>&1 || { echo "GATE FAILED or UNVERIFIABLE: finalization refused; see $RD/GATE_RESULT.json"; $SUP --scope pac_finalize_closeout --job finalize:closeout_unqualified --timeout 600 -- $PY cex/pac/closeout.py "$RD" --manifest "$MN" || true; exit 6; }
head -3 "$RD/gate_stdout.txt"
RC=$($PY -c "import json; m=json.load(open('$RD/$MN')); print(int(m['ceiling'].get('reporting_closeout_packaging_total_seconds', 0)))"); test "$RC" -ge 3600 || { echo "manifest reporting/closeout/packaging allowance $RC s is below the finalizer stage caps (1200 + 600 + 1800 = 3600)"; exit 13; }
$SUP --scope pac_finalize_report --job finalize:report --timeout 1200 -- $PY cex/pac/report.py "$RD" --manifest "$MN" || { echo "report stage failed"; exit 12; }
$SUP --scope pac_finalize_closeout --job finalize:closeout --timeout 600 -- $PY cex/pac/closeout.py "$RD" --manifest "$MN" || { echo "closeout refused a qualified verdict"; exit 7; }
git add -A "$RD" cex/pac/PAC_QUALIFICATION.json && git commit -q -m "PAC pass: receipts, references, gate result, RESULTS_PAC, REFERENCE_AUDIT, CLOSEOUT_PAC

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git log --oneline -1
test -e "$OUT" && { echo "archive exists"; exit 3; }
$SUP --scope pac_packaging --job packaging:pac_pass_1 --timeout 1800 --stdout "$RD/package_pac_1.txt" --stderr "$RD/package_pac_1.err" -- $PY cex/pac/package.py "$RD" "$OUT"
tail -1 "$RD/PAC_LEDGER.jsonl" > "$OUT.receipt.json"
git add -A "$RD" && git commit -q -m "PAC pass: package record + charged packaging receipt

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" && git log --oneline -1
echo FINALIZE_DONE
