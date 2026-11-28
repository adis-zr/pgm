"""DGP7 START_HERE writer: question, pinned identities, the missing-packet disclosure, verdicts, gate tables, reading / reproduction entrypoints. Reads RESULTS / DIAGNOSTICS / CHARGES / FREEZE / IDENTITY / VALIDATION / BUDGET_DECLARATION. usage: dgp7_start_here.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import json, os, statistics
RD = os.environ.get('DGP7_RD', str(_runs_root() / 'mdi_2026-10-28/DGP7_RESIDUAL_JOINT'))
R = json.load(open(RD + '/RESULTS.json')); D = json.load(open(RD + '/DIAGNOSTICS.json')); C = json.load(open(RD + '/CHARGES.json')); FR = json.load(open(RD + '/FREEZE.json')); ID = json.load(open(RD + '/IDENTITY.json')) if os.path.exists(RD + '/IDENTITY.json') else {}; VAL = json.load(open(RD + '/VALIDATION.json')) if os.path.exists(RD + '/VALIDATION.json') else {}; BUD = json.load(open(RD + '/BUDGET_DECLARATION.json')); REL = json.load(open(RD + '/RELEASE_DECISION.json')) if os.path.exists(RD + '/RELEASE_DECISION.json') else {}
vi = R['verdict_inputs']; V = R['verdicts']; G = R['gates']; mi = vi['main']; mc = vi.get('mechanism_counts', {}); O = {r['task']: r for r in D['oracle']}; XG = vi.get('execution_gate', {})
def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
def f3(x): return ('%.3f' % x) if isinstance(x, (int, float)) else '-'
def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
L = []
def P(s=''): L.append(s)
P('# START_HERE -- DGP7_RESIDUAL_JOINT (26 Nov 2026)'); P()
P('**Question.** Retain the checked MAX-group slacks of the seed pass as a residual envelope bank (W_0 <= envelope_B q prod rho) and jointly re-optimize 2 / 4 consecutive conditionals per local window under a kernel-checked residual update (G1 fixed; regions <= 65,536 states; exact gates 10 B_new <= 11 B_ref and 10 B_new <= 11 initial_seed_cap): does it (M) lower the TRUE second moment by >= 0.5 bits at a checked cap <= 1.10 x the best same-law seed cap on 2 of the 3 exposed n8 reference cliques, (X) execute a genuinely changed law with >= 1,024 future draws on an n32 AND an n64 anchor at 20 s / 4 s, and (E / O) transfer to completions / radii at equal cost without preservation loss? One substantive round (brief section 9); the eight DGP6-review repairs R1-R8 are bundled (PROTOCOL.md section 8).'); P()
P('## Disclosure first (brief section 0 / BUDGET_DECLARATION.json)'); P()
P('Only the two markdown files of the packet (the brief and the theory note) reached this machine. The packet bootstrap / manifest, `dgp7_theory/repairs/REPAIR_SPEC.md` and the supplied before-probes, `dgp7_theory/benchmark/DGP7_FROZEN_EXPERIMENT.md` and its appendix, the DGP6 review evidence archive, the exact tiny references and the floating oracle references with their observed outputs were ABSENT. They are recorded as INCOMPLETE QUALIFICATION INPUTS and never claimed: R1-R8 were implemented from the brief\'s text with this round\'s own probes (8 / 8 present before, 0 / 8 after); exact tests were written here and labelled independent; **the supplied floating reference comparison was NOT RUN**. Items: ');
for it in BUD['missing_packet_items']['items']: P('- ' + it)
P()
P('## Pinned identities'); P()
P('- pgm frozen commit **%s** (tree %s), branch `%s` from 2b4012e (arm identity files identical to the DGP6 frozen commit df02d18); pushed, NOT merged; the accepted default engine v2.13.2 (pgm 1da6da3) byte-identical (VALIDATION).' % (FR['code']['commit'][:9], FR['code']['tree'][:9], FR['code'].get('branch')))
P('- Before-repair reference: `pgm-eval-df02d18` (controls/before/eight_findings_on_df02d18.json). Planner %s.' % (FR['code'].get('planner_version') or '')[:60])
P('- Records: PROTOCOL.md first freeze (records 86fae7d7f); FREEZE.json (second freeze) sha256 %s; this packet\'s archives: %s.' % (R.get('freeze_sha256', '')[:12], json.dumps((ID.get('archives') or {}), default=str)[:400] if ID else 'see IDENTITY.json'))
P('- Validation: %s (%s checks, %s failed). Charges: %.1f s of the %s s ceiling (%d receipts; by scope %s); the final packaging / validation / restore receipts are in DGP7_FINAL_LEDGER_SIDECAR.json.' % ('all_ok' if VAL.get('all_ok') else 'see VALIDATION.json', VAL.get('n_checks'), VAL.get('n_failed'), C['total_s'], C['ceiling_s'], C['n_receipts'], json.dumps({k: round(v) for k, v in C['by_scope_s'].items()})))
P()
P('## Verdicts (separate; REPORT.md section 1 for the full basis)'); P()
P('| verdict | status |'); P('|---|---|')
for k in ('validity', 'preservation', 'mechanism', 'execution', 'deployable_progress', 'cost_overhead'):
    v = V.get(k); P('| %s | **%s** |' % (k, (v[:160] if isinstance(v, str) else (v.get('status') if isinstance(v, dict) else v))))
P('| release of the broad phase | **%s** |' % (('RELEASED' if REL.get('released') else 'NOT RELEASED') if REL else 'see RELEASE_DECISION.json'))
P()
mg = V['mechanism']; P('## Mechanism gate (oracle; production RESIDUAL_JOINT vs seed; numerator / denominator)'); P()
P('Exposed reference cliques passing: **%s of %s run** (of 3; gate needs 2). Fresh ORACLE7 cliques: **%s of %s run** (fresh claim: %s). Rule: %s' % (mg['exposed_pass'], mg['exposed_run'], mg['fresh_pass'], mg['fresh_run'], mg['fresh_claim'], mg['rule'])); P()
P('| model | seed log2 M2 | RJ true M2 gain (bits) | RJ checked cap ratio | inside allowance | changed-law transactions | RO gain | teacher gain (q = p) | injected true-context gain | gate |'); P('|---|---:|---:|---:|---|---|---:|---:|---:|---|')
for t in (G['mechanism']['exposed_hard_cliques'] + (G['mechanism'].get('fresh_cliques') or []) + (G['mechanism'].get('fresh_er50') or [])):
    c = (O.get(t) or {}).get('contrasts') or {}; rj = c.get('RJ_final') or {}
    P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (t, f3(c.get('seed_M2')), f3(rj.get('M2_gain_bits')), f4(rj.get('cap_ratio_vs_seed')), rj.get('inside_allowance'), c.get('RJ_transactions'), f3((c.get('RO_final') or {}).get('M2_gain_bits')), f3((c.get('teacher') or {}).get('M2_gain_bits_vs_seed')), f3((c.get('oracle_injected_true_context') or {}).get('M2_gain_bits')), c.get('mechanism_gate_RJ') if t in O else 'NOT_RUN'))
P()
xg = V['execution']; P('## Execution gate (RESIDUAL_JOINT, four anchors x paired seeds, 20 s / 4 s)'); P()
P('Status **%s**: n32 anchors passing both seeds %s; n64 %s (numerator %s / denominator %s). Rule: %s' % (xg['status'], xg['n32'], xg['n64'], xg['numerator'], xg['denominator'], xg['rule'])); P()
P('| task | seed | passes | changed-law commits | future draws under the new law | allowance s | seed s | closed |'); P('|---|---|---|---|---:|---:|---:|---|')
for x in (XG.get('cells') or []): P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], x['seed_index'], x['passes'], x['changed_law_commits'], x['future_draws'], f2(x['allowance_s']), f2(x['seed_s']), (x.get('closed') or '-')[:50]))
P()
P('## Main matrix and preservation'); P()
P('Tasks in the matrix %d (released broad phase: %s). Ran: %s. Completions: %s; identical sets across the three arms: %s; historical 24 lost: %s; hard-8 completed: %s; new dense completion candidates: %s; mutual-failure 2x gains vs REPAIRED: %s; overhead flags: %s.' % (mi['n_tasks'], bool(REL.get('released')), {a: mi['n_ran'][a] for a in mi['n_ran']}, {a: mi['n_complete'][a] for a in mi['n_complete']}, mi['identical_sets_all_three'], {a: len(v) for a, v in mi['historical_lost'].items()}, {a: len(v) for a, v in mi['hard8_completed'].items()}, mi['new_dense_completion_candidates'], V['deployable_progress']['material_2x'], V['cost_overhead']['flags']))
pv = V['preservation']; P('Preservation: 18-cohort %s; 13-cohort %s; status %s.' % ({a: ('%s/%s' % ((pv['preservation_18'].get(a) or {}).get('complete'), (pv['preservation_18'].get(a) or {}).get('n'))) for a in pv['preservation_18']}, {a: ('%s/%s' % ((pv['preservation_13'].get(a) or {}).get('complete'), (pv['preservation_13'].get(a) or {}).get('n'))) for a in pv['preservation_13']}, pv['status']))
rj = mc.get('main/RESIDUAL_JOINT', {}); P('Mechanism counts (main / RESIDUAL_JOINT): cells %s, offered %s, created %s, READY %s, attempted %s, cells with a changed law %s, cells with >= 1,024 future draws %s, changed-law commits %s, same-law commits %s, median live atoms %s, median seed %s s. RESIDUAL_ONLY same-law commits: %s.' % (rj.get('cells'), rj.get('offered'), rj.get('created'), rj.get('ready'), rj.get('attempted'), rj.get('cells_with_changed_law'), rj.get('cells_with_1024_future_draws'), rj.get('changed_law_commits'), rj.get('same_law_commits'), rj.get('atoms_median'), f3(rj.get('seed_s_median')), mc.get('main/RESIDUAL_ONLY', {}).get('same_law_commits')))
P()
P('## Reading order'); P()
P('1. This file; 2. REPORT.md (every table from the raw cells); 3. THEORY_RETURN.md (the separated loss budget; what executed); 4. PROTOCOL.md (frozen question / arms / recipe / contracts / analysis / selection / decision / repairs / budget) and FREEZE.json; 5. PROOF_TO_CODE.md; 6. controls/ (before probes on df02d18, dev smoke / e2e / calibration, qualification at the frozen commit incl. D1-D70 and the inherited suites, after probes, UNSUPERVISED_DEV_LOG.md); 7. oracle/results/*.json (12 models; per law TRUE M2 / R* / checked cap; replays); 8. runs/<sub>/<dir>/ (cell.json with identities, result.json, stdout, stderr); 9. RESULTS.json / DIAGNOSTICS.json / RUN_MANIFEST.json / CHARGES.json / VALIDATION.json / IDENTITY.json / DGP7_FINAL_LEDGER_SIDECAR.json; 10. harness/ (executed files + the self-contained bundle); 11. reproduce.sh (restore / controls / oracle / cell / analyze / campaign).'); P()
P('## Reproduction'); P()
P('`./reproduce.sh restore` (from the unzipped results archive; the bundle is inside harness/), then `./reproduce.sh controls --only D63`, `./reproduce.sh oracle --model dg_n8_c4_clique_two`, `./reproduce.sh cell --id runs/gate/<dir>`. The code archive is the git archive of the frozen commit with its identity sidecar; the results archive carries the self-contained bundle. Inputs resolve through dgp_paths (packet-relative, then DGP_ROOTS, sha256-checked).')
open(RD + '/START_HERE.md', 'w').write('\n'.join(L) + '\n'); print('START_HERE.md written', len(L), 'lines')
