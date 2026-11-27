"""DGP8 START_HERE writer: the missing-packet disclosure first, pinned identities, verdicts, the Stage A table, the guard table, reading / reproduction entrypoints. Reads RESULTS / DIAGNOSTICS / CHARGES / FREEZE / IDENTITY / VALIDATION / BUDGET_DECLARATION / RELEASE_DECISION. usage: dgp8_start_here.py"""
import json, os
RD = os.environ.get('DGP8_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH')
R = json.load(open(RD + '/RESULTS.json')); D = json.load(open(RD + '/DIAGNOSTICS.json')); C = json.load(open(RD + '/CHARGES.json')); FR = json.load(open(RD + '/FREEZE.json')); ID = json.load(open(RD + '/IDENTITY.json')) if os.path.exists(RD + '/IDENTITY.json') else {}; VAL = json.load(open(RD + '/VALIDATION.json')) if os.path.exists(RD + '/VALIDATION.json') else {}; BUD = json.load(open(RD + '/BUDGET_DECLARATION.json')); REL = json.load(open(RD + '/RELEASE_DECISION.json')) if os.path.exists(RD + '/RELEASE_DECISION.json') else {}
vi = R['verdict_inputs']; V = R['verdicts']; feas = vi['stage_a']; guard = vi.get('guard') or []
def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
def f3(x): return ('%.3f' % x) if isinstance(x, (int, float)) else '-'
def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
def fe(x): return ('%.3g' % x) if isinstance(x, (int, float)) else '-'
L = []
def P(s=''): L.append(s)
P('# START_HERE -- DGP8_SPECTRAL_HEATBATH (26 Nov 2026)'); P()
P('**Question.** Certify spectral eligibility of the original pairwise model from its rational factors (l I <= A <= u I on the centered one-hot log interaction, width w = u - l < 2, gap g = (1 - w / 2) / n), run EXACT random-scan heat-bath on the original target, and publish original-coordinate marginal intervals from a separate finite-time Markov certificate: does this improve certified accuracy at equal total cost on the exposed dense inputs (Stage A feasibility on 16 inputs; Stage B guard only if the frozen forecast promises a new completion or a 2x worst-radius gain on a current failure)? Not an importance-proposal campaign. The seven DGP7-review findings are repaired in the same round (PROTOCOL.md section 8).'); P()
P('## Disclosure first (brief section 0 / BUDGET_DECLARATION.json)'); P()
P('Only the brief and the theory note reached this machine. The theory packet zip, its bootstrap and manifest, the DGP7 independent review and its probes, the heat-bath / categorical-gap references, the tiny aggregate references and rational cases, and the floating diagnostics were ABSENT. They are recorded as INCOMPLETE QUALIFICATION INPUTS and never claimed; every reference used here is this round\'s own and labelled independent; the DGP7 review findings were repaired from the brief\'s abbreviated list with this round\'s probes. Items:')
for it in (BUD.get('missing_packet_items') or {}).get('items', []): P('- ' + it)
P()
P('## Pinned identities'); P()
P('- pgm frozen commit **%s** (tree %s), branch `%s` from main = 2ae105c (every arm identity file byte-identical to the reviewed DGP7 engine commit 47d4024); the accepted default engine v2.13.2 (pgm 1da6da3) byte-identical, confirmed from the repository (VALIDATION).' % ((FR['code'].get('commit') or '')[:9], (FR['code'].get('tree') or '')[:9], FR['code'].get('branch')))
P('- Before-repair reference: `pgm-eval-2ae105c` (controls/before/seven_findings_on_2ae105c.json). Planner %s. Heat-bath native kernel: %s.' % ((FR['code'].get('planner_version') or '')[:60], (json.dumps({k: FR['code']['heatbath_kernel'].get(k) for k in ('source_sha256', 'binary_sha256', 'compiler')}, default=str)[:160] if isinstance(FR['code'].get('heatbath_kernel'), dict) else FR['code'].get('heatbath_kernel'))))
P('- Records: PROTOCOL.md (first freeze); FREEZE.json (second freeze) sha256 %s; archives: %s.' % ((R.get('freeze_sha256') or '')[:12], json.dumps((ID.get('archives') or {}), default=str)[:400] if ID else 'see IDENTITY.json'))
P('- Validation: %s (%s checks, %s failed). Charges: %.1f s of the %s s ceiling (%d receipts; by scope %s); the final packaging / validation / restore receipts are in DGP8_FINAL_LEDGER_SIDECAR.json.' % ('all_ok' if VAL.get('all_ok') else 'see VALIDATION.json', VAL.get('n_checks'), VAL.get('n_failed'), C['total_s'], C['ceiling_s'], C['n_receipts'], json.dumps({k: round(v) for k, v in C['by_scope_s'].items()})))
P()
P('## Verdicts (separate; REPORT.md section 1 for the basis)'); P()
P('| verdict | status |'); P('|---|---|')
for k in ('validity', 'spectral_admission', 'finite_time_confidence', 'throughput', 'partial_accuracy', 'new_completion', 'preservation', 'overhead', 'deployability'):
    v = V.get(k); P('| %s | **%s** |' % (k, (v[:140] if isinstance(v, str) else (str(v.get('status'))[:140] if isinstance(v, dict) else v))))
P('| release of Stage B | **%s** |' % ('RELEASED' if REL.get('stage_b_released') else 'NOT RELEASED')); P('| release of the regression | **%s** |' % ('RELEASED' if REL.get('regression_released') else 'NOT RELEASED'))
P()
P('## Stage A feasibility (16 exposed dense inputs)'); P()
P('| input | role | eligible | width w | margin m | gap g | witness s | dev steps/s | forecast r (20 s) | incumbent worst r | current failure | forecast improvement | Stage B candidate |'); P('|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---|')
for x in feas: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], (x['role'] or '')[:22], (x['eligible'] if x['screened'] else 'not screened'), f4(x['width']), f4(x['margin_m']), fe(x['gap_g']), f3(x['witness_seconds']), fe(x['dev_steps_per_second']), f4((x['forecast_20s'] or {}).get('radius')), f4(x['incumbent_best_worst_radius']), x['current_failure'], f2(x['forecast_improvement_20s']), x['stage_b_candidate']))
P(); P('Release decision: %s' % (REL.get('stage_b_decision') or 'not decided')); P()
P('## Stage B guard (if released)'); P()
if guard:
    P('| input | role | seed | eligible | worst r achieved | certified r | checkpoints | recorded N | burn-in | elapsed s | incumbent worst r | improvement | 2x gain | new completion |'); P('|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|')
    for g in guard:
        for s, v in sorted(g['seeds'].items()): P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (g['task'], (g['role'] or '')[:22], s, v['eligible'] if v['eligible'] is not None else (v['refusal'] or '-'), f4(v['worst_radius_achieved']), f4(v['certified_radius']), v['checkpoints_completed'], v['recorded'], v['burn_in_steps'], f2(v['elapsed_s']), f4(g['incumbent_best_worst_radius']), f2(v['improvement']), v['gain_2x'], v['new_completion']))
    P(); P('Regression decision: %s' % (REL.get('regression_decision') or 'not decided'))
else: P('- not run (Stage B not released); the Stage A forecasts stand as the feasibility result')
P(); P('## Reading order'); P()
P('1. This file; 2. REPORT.md (every table from the raw cells); 3. THEORY_RETURN.md (the brief\'s five questions answered from the data); 4. PROTOCOL.md and FREEZE.json (frozen question / arms / panels / contracts / release rule / repairs / budget); 5. PROOF_TO_CODE.md; 6. controls/ (before probes on 2ae105c, dev smoke, qualification at the frozen commit incl. D1-D71+ and the inherited suites, after probes, UNSUPERVISED_DEV_LOG.md); 7. runs/<sub>/<dir>/ (cell.json with identities, result.json with the exact spectral witness / checkpoints / transition counts, stdout, stderr); 8. RESULTS.json / DIAGNOSTICS.json / RUN_MANIFEST.json / CHARGES.json / RELEASE_DECISION.json / VALIDATION.json / IDENTITY.json / DGP8_FINAL_LEDGER_SIDECAR.json; 9. harness/ (executed files + the self-contained bundle); 10. reproduce.sh (restore / controls / cell).'); P()
P('## Reproduction'); P()
P('`./reproduce.sh restore` (from the unzipped results archive; the bundle is inside harness/), then `./reproduce.sh controls --only D71`, `./reproduce.sh cell --id runs/screen/<dir>` (an eligible input) and `./reproduce.sh cell --id runs/screen/<strong dir>` (a refusing input). The code archive is the git archive of the frozen commit with its identity sidecar; inputs resolve through dgp_paths (packet-relative, then DGP_ROOTS, sha256-checked).')
open(RD + '/START_HERE.md', 'w').write('\n'.join(L) + '\n'); print('START_HERE.md written', len(L), 'lines')
