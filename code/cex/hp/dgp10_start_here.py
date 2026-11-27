"""DGP10 START_HERE.md writer (derived from RESULTS / FREEZE / IDENTITY_EXTERNAL / VALIDATION; no hand-typed numbers)."""
import os, json
RD = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE')
def ld(p):
    try: return json.load(open(os.path.join(RD, p)))
    except Exception: return None
R = ld('RESULTS.json') or {'gates': {}}; fr = ld('FREEZE.json') or {'code': {}}; ext = ld('IDENTITY_EXTERNAL.json'); val = ld('VALIDATION.json'); ch = (R.get('charges') or {}); G = R['gates']; L = []; P = L.append
P('# START_HERE -- DGP10_QUERY_RESPONSE (27 Nov 2026)'); P('')
P('Conditional-response certification on the exact random-scan heat-bath chain (theory note) + the carried DGP9 repairs (review F9-1..F9-5), one frozen campaign. Frozen pgm `%s` (branch dgp10-query-response from the DGP9 frozen d1932cf). The accepted default engine v2.13.2 is unchanged; the branch is pushed, NOT merged.' % (fr['code'].get('commit') or '?')[:12]); P('')
P('## Decision (the eight items of the brief section 10)'); P('')
for k, lab in (('validity_resources', 'validity'), ('response_execution', 'repair / response execution status'), ('material_partial_accuracy', 'mechanism (2x partial accuracy)'), ('preservation', 'preservation'), ('completion', 'new completion'), ('cost', 'cost'), ('generalization', 'scope / generalization')): P('- %s: **%s**' % (lab, (G.get(k) or {}).get('status', 'NOT RUN')))
P('- next mathematically identified obstruction: THEORY_RETURN.md (last section)'); P('')
P('## Read in this order'); P('')
P('1. REPORT.md (the seven gates, every table from the raw cells); 2. THEORY_RETURN.md; 3. PROTOCOL.md + FREEZE.json (+ FREEZE_RATES.json, FREEZE_AMENDMENT*.json if any); 4. PROOF_TO_CODE.md and REPAIR_TABLE.md; 5. RESULTS.json / DIAGNOSTICS.json / RUN_MANIFEST.json / CHARGES.json; 6. controls/ (bootstrap, before = the pinned parent, dev, qual = the frozen checkout incl. ORACLE.json and CONTROLS_DGP10.json, after = the carried probes at the frozen commit); 7. runs/ (every cell: cell.json + result.json + receipt in DGP10_LEDGER.jsonl); 8. reproduce.sh / RESTORE_TEST.sh / reproduce_test/.'); P('')
P('## Identities'); P('')
if ext: P('- archives (EXTERNAL manifest, written after both archives closed): %s' % json.dumps(ext.get('archives'), indent=0)[:900])
else: P('- archives: not yet packaged')
P('- validation: %s' % (json.dumps(dict(all_ok=val.get('all_ok'), n=val.get('n_checks'), failed=[c['check'] for c in val.get('checks', []) if not c['ok']])) if val else 'not yet run'))
P('- charges: %s s of the %s s ceiling (%s receipts; unique ids %s; within ceiling %s); the final sidecar DGP10_FINAL_LEDGER_SIDECAR.json reconciles the receipts written after analysis' % (ch.get('total_s'), ch.get('ceiling_s'), ch.get('n_receipts'), ch.get('unique_jids'), ch.get('within_ceiling')))
P('- normative inputs: PACKET/NORMATIVE_INVENTORY.json (every supplied normative file used, hashed); the packet zip sha256 984043e3...; the brief, theory and external identity delivered first (PACKET/MISSING_PACKET.md records that the zip arrived second)'); P('')
P('## Limits'); P('')
P('- No SELECT: INCUMBENT_R preservation plus standalone RESPONSE results prove nothing about a combined selector. Strong twins remain refused by spectral admission (not a mixing statement). Fresh results are separate. The same-path raw full-delta figure is a NON-PUBLISHING diagnostic. The DGP9 scored records are unchanged (read only).')
open(os.path.join(RD, 'START_HERE.md'), 'w').write('\n'.join(L) + '\n'); print('START_HERE.md written')
