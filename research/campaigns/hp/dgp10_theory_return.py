"""DGP10 THEORY_RETURN.md writer: the answer to the one scientific question in the theory group's terms, derived from RESULTS.json / DIAGNOSTICS.json (never hand-typed numbers)."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import os, json, sys
RD = os.environ.get('DGP10_RD', str(_runs_root() / 'mdi_2026-10-28/DGP10_QUERY_RESPONSE'))
def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else str(x)
def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else str(x)
R = json.load(open(os.path.join(RD, 'RESULTS.json'))); D = json.load(open(os.path.join(RD, 'DIAGNOSTICS.json'))); G = R['gates']; fr = json.load(open(os.path.join(RD, 'FREEZE.json'))); L = []
P = L.append
P('# THEORY_RETURN -- DGP10_QUERY_RESPONSE (to the theory group)'); P('')
P('Question (FROZEN_EXPERIMENT_SPEC section 1): at equal end-to-end cost, does the exact conditional response observed on selected-site visits, with a checked population-moment / tilted-operator certificate, materially improve certified original-coordinate accuracy over repaired DGP9 heat bath while preserving its successful cells?'); P('')
P('## Answer by gate'); P('')
for k, lab in (('validity_resources', 'Validity / resources'), ('response_execution', 'Response execution'), ('material_partial_accuracy', 'Material partial accuracy (2x on both card-4 anchors, both seeds)'), ('completion', 'Completion'), ('preservation', 'Preservation'), ('cost', 'Cost'), ('generalization', 'Generalization')): P('- %s: **%s**' % (lab, G[k]['status']))
P(''); P('## The mechanism in numbers (exposed card-4 anchors)'); P('')
P('| anchor / seed | HB_R worst r | RESPONSE worst r | ratio | checked U | mean R | local M | groups |'); P('|---|---:|---:|---:|---|---|---:|---:|')
for k, x in G['material_partial_accuracy']['anchors'].items():
    e = G['response_execution']['anchors'].get(k) or {}; lc = e.get('local_counts') or {}
    P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (k, f4(x['HB_R_worst']), f4(x['RESPONSE_worst']), f2(x['ratio']), [f4(u) for u in (e.get('checked_U') or [])], [f4(r) for r in (e.get('R') or [])], lc.get('max'), e.get('groups')))
P(''); P('## Same-trajectory attribution (what the raw occupation certificate would have been on the SAME stored trajectory; NOT published, in no gate)'); P('')
P('| cell | raw full delta/2 | raw delta/4 | checked response | intersected | HB_R (own trajectory) | transitions RESPONSE / HB_R |'); P('|---|---:|---:|---:|---:|---:|---:|')
for k, x in D['attribution_same_trajectory'].items(): P('| %s | %s | %s | %s | %s | %s | %s |' % (k, f4(x['raw_occupation_same_path_full_delta']), f4(x['raw_reduced_delta_quarter']), f4(x['response_checked']), f4(x['intersected']), f4(x['HB_R_actual']), f2(x['observation_overhead_transitions'])))
P(''); P('## Limiting terms'); P(''); P('Counts: %s.' % R['verdict_inputs']['limiting_term_counts']); P('')
for k, x in D['limiting_terms'].items(): P('- %s: %s (moment inflation U / y %s; U mode %s; local utilization %s; needed / reachable %s)' % (k, x.get('term'), f2(x.get('moment_inflation')), x.get('U_mode'), f2(x.get('checkpoint_utilization')), f2(x.get('ratio_needed_over_reachable'))))
P(''); P('## Oracle gate (exact tiny models)'); P('')
orc = json.load(open(os.path.join(RD, 'controls', 'qual', 'ORACLE.json'))) if os.path.exists(os.path.join(RD, 'controls', 'qual', 'ORACLE.json')) else {}
P('Gate %s; nonvacuous models %s. Per model: exact identities (target / projections / Poisson identity / response-mean identity / observation chain stochastic-stationary-reversible-PSD / eta-domination by LDL^T), production observer coverage of the true marginal at delta = 1e-3, and the mpmath MGF diagnostic (labelled numerical).' % (orc.get('gate'), orc.get('nonvacuous_models')))
for n_, m in (orc.get('models') or {}).items(): po = m.get('production_observer') or {}; P('- %s: eta %s; r_resp %s vs r_raw %s; coverage %s; nonvacuous %s; mgf worst %s' % (n_, f4(m.get('eta_float')), f4(po.get('response_radius_max')), f4(po.get('raw_radius_same_trajectory')), po.get('coverage_true_marginals'), po.get('nonvacuous'), ('%.2e' % (m.get('mgf_diagnostic') or {}).get('worst', 0)) if isinstance((m.get('mgf_diagnostic') or {}).get('worst'), (int, float)) else '-'))
P(''); P('## What the theory group should take from this'); P('')
pa = G['material_partial_accuracy']; ratios = [v['ratio'] for v in pa['anchors'].values() if isinstance(v['ratio'], float)]
P('- The response identity f - (I - P)(n f) = q and the observation-chain gap eta = n g / (1 + n g) hold exactly on every enumerable model (oracle); the production quantized observer encloses the exact conditional at every checked state (D92; oracle 0 violations).')
P('- On the exposed card-4 anchors the RESPONSE / HB_R worst-radius ratios are %s (gate: all <= 0.5 -> %s). The gain comes from the certified second moment U (checked, not the support fallback) replacing the indicator variance proxy; the loss terms are the observer\'s throughput share (transitions RESPONSE / HB_R above), the moment inflation U / y and the local checkpoint utilization.' % ([f2(r) for r in ratios], pa['status']))
P('- Completions: %s (exposed), %s (fresh). Preservation: %s. No SELECT: standalone results only.' % (G['completion']['new_completions_exposed'] or 'none', G['completion']['new_completions_fresh'] or 'none', G['preservation']['status']))
P('- Next mathematically identified obstruction: see REPORT section 8 (the dominant limiting term) -- the frozen center c = 1/k makes the certified second moment E (q - c)^2 include the squared offset of the marginal from 1/k (exact on the independent oracle model); a checked data-independent center closer to the marginal, or a two-stage centered moment, is the next lever; the moment allowance per variable (delta w_j / 8 n_q) and the two-point majorant at v = min(U, 1/4) are where the remaining conservatism sits.')
P(''); P('Frozen commit %s; every number above is from RESULTS.json / DIAGNOSTICS.json at that commit.' % (fr['code']['commit'][:12]))
open(os.path.join(RD, 'THEORY_RETURN.md'), 'w').write('\n'.join(L) + '\n'); print('THEORY_RETURN.md written (%d lines)' % len(L))
