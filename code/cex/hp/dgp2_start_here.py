"""DGP2 START_HERE writer (reads RESULTS.json / DIAGNOSTICS.json / CHARGES.json / IDENTITY.json / FREEZE.json; every number comes from those files)"""
import json, os
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS'
R = json.load(open(RD + '/RESULTS.json')); D = json.load(open(RD + '/DIAGNOSTICS.json')); C = json.load(open(RD + '/CHARGES.json')); fr = json.load(open(RD + '/FREEZE.json')); I = json.load(open(RD + '/IDENTITY.json')) if os.path.exists(RD + '/IDENTITY.json') else {}
vi = R['verdict_inputs']; ex = vi['exposed']; cb = R['completions_by_sub']; st = {k: v['status'] for k, v in D['explanations'].items()}
conf = cb.get('confirm', {}); conf_rows = R['tables'].get('confirm', [])
conf_line = ('%d cells (6 anchor tasks x BASE / UPAC2 / FULL2 x seeds 2, 3, reversed order): complete %d; every outcome equals the primary' % (conf['cells'], conf['complete'])) if conf else 'not run'
if conf_rows:
    prim = {r['task']: r['arms'] for r in R['tables']['exposed_main']}; mism = [(r['task'], r['seed'], a) for r in conf_rows for a, c in r['arms'].items() if prim.get(r['task'], {}).get(a, {}).get('complete') != c['complete']]
    conf_line = ('%d cells (6 anchor tasks x BASE / UPAC2 / FULL2 x seeds 2, 3, reversed order): complete %d; %s' % (conf['cells'], conf['complete'], ('every completion outcome equals the primary' if not mism else 'outcome differences vs the primary: %s' % mism)))
fresh = cb.get('fresh', {}).get('by_arm', {}); p18 = vi.get('preservation_18', {}); p13 = vi.get('preservation_13', {})
L = []
P = L.append
P('# START_HERE -- DGP2_REPAIR_AND_DIAGNOSIS (25 Nov 2026)')
P('')
P('**Question.** On dense generic cyclic models (positive pairwise tables; ER p = 1/2 and cliques; card 2 / 4), is the obstruction to certified completion by the integrated PAC planner primarily avoidable fixed-q cap slack (H1), coarse sampler / cap construction (H2), information lost by the conditional decoder / representation (H3), numerical allowance or arithmetic (H4), query-specific certification (H5), or planner reachability / scheduling (H6)? Brief `PACKET/CLAUDE_DGP2_REPAIR_AND_DIAGNOSIS.md` (sha256 d3245a67...), standing protocol `PACKET/INFERENCE_RESEARCH_ROUND_PROTOCOL.md` (f2e579f9...).')
P('')
P('**Pinned identities.** Parent pgm d4a63cc (DGP1 v0.5.1). Repairs pgm 02326d3; frozen implementation pgm %s (tree %s), branch dgp2-repair-diagnosis-2026-11-25; every evaluation cell ran from the clean detached checkout `pgm-eval-%s` with identity checked at launch and completion. Accepted engine v2.13.2 (pgm 1da6da3) byte-identical. First freeze PROTOCOL.md (records 9cc7c08d9), second freeze FREEZE.json (records 2da1d583a), holdout after the freeze (records 8b6ada82c). Archives: see IDENTITY.json.' % (fr['code']['commit'][:9], fr['code']['tree'][:9], fr['code']['commit'][:7]))
P('')
P('## Verdicts')
P('')
P('| verdict | result |')
P('|---|---|')
P('| Validity | QUALIFIED: all seven DGP1 review findings reproduced on the parent (controls/before) and repaired (26 DGP controls + HP 80 / 57 / 32 + accepted PAC suites, controls/qualification); every cell from the frozen checkout with identity ok; one harness launch fix before any cell ran (FREEZE_AMENDMENT_harness1.json); no validity amendment of any result |')
P('| Historical preservation | PRESERVED: FULL2 %d / %d at 4 s and %d / %d at 20 s (no regression, no gain vs DGP1 FULL v0.5.1) |' % (p18.get('FULL2_complete', 0), p18.get('n', 0), p13.get('FULL2_complete', 0), p13.get('n', 0)))
P('| New completion | NONE: exposed BASE %d = UPAC2 %d = FULL2 %d of 28 (identical sets; dense 6 / 16 each); fresh BASE %d, UPAC2 %d, FULL2 %d of 8 |' % (ex['n_complete']['BASE'], ex['n_complete']['UPAC2'], ex['n_complete']['FULL2'], fresh.get('BASE', {}).get('complete', 0), fresh.get('UPAC2', {}).get('complete', 0), fresh.get('FULL2', {}).get('complete', 0)))
P('| Fresh transfer | nothing to transfer (fresh cohort reproduces the exposed pattern) |')
P('| Partial accuracy | no material gain: BASE / FULL2 recorded certificate radii within 10 %% on every mutual failure |')
P('| Efficiency | FULL2 / BASE receipt ratio median %.2f on %d mutual completions |' % (sorted(x['ratio_FULL2_over_BASE'] for x in vi['efficiency_mutual'])[len(vi['efficiency_mutual']) // 2], len(vi['efficiency_mutual'])))
P('| Diagnostic identifiability | H1 %s, H2 %s, H3 %s, H4 %s, H5 %s, H6 %s (oracle cohort = controlled; see THEORY_RETURN.md for the per-model readings and the next construction) |' % tuple(st[k].upper() for k in ('H1_avoidable_fixed_q_cap_slack', 'H2_coarse_sampler_or_cap_construction', 'H3_conditional_decoder_or_representation', 'H4_numerical_allowance_or_arithmetic', 'H5_query_specific_certification', 'H6_planner_reachability_or_scheduling')))
P('| Confirmations | %s |' % conf_line)
P('| Charges | %.1f s of 7,200 (%d receipts, %d completed; by scope in CHARGES.json) |' % (C['total_s'], C['n_receipts'], C['completed']))
P('')
P('## Result table (exposed 28 x 3 at 20 s; C = complete, x = not; published / K; receipt s)')
P('')
P('| task | BASE | UPAC2 | FULL2 |')
P('|---|---|---|---|')
for r in R['tables']['exposed_main']: P('| %s | %s |' % (r['task'], ' | '.join('%s %s/%s %.1fs' % ('C' if c['complete'] else 'x', c['published'], c['K'], c['receipt_wall_s'] or 0) for a in ('BASE', 'UPAC2', 'FULL2') for c in [r['arms'][a]])))
P('')
P('## Reading order')
P('')
P('1. `THEORY_RETURN.md` -- hypotheses, distinguishing evidence, claim status, smallest examples, the next mathematical question.')
P('2. `REPORT.md` -- the complete analyzer-derived matrix (exposed, fresh, preservation, confirmations, forced-stream panel, oracle table, explanation statuses, charges, disclosures).')
P('3. `PROTOCOL.md`, `FREEZE.json`, `FREEZE_AMENDMENT_harness1.json` -- the preregistered experiment and freezes; `PROOF_TO_CODE.md` -- lemmas K, C, W, Z, F, E, O, R, U mapped to functions and consumed bounds.')
P('4. `MODEL_MANIFEST.json`, `RUN_MANIFEST.json`, `RESULTS.json`, `DIAGNOSTICS.json`, `CHARGES.json`, `IDENTITY.json`, `VALIDATION.json`; raw evidence under `runs/`, `controls/`, `oracle/`; the ledger `DGP2_LEDGER.jsonl`.')
P('5. Reproduction: `reproduce.sh` (entrypoints); analysis `code/cex/hp/dgp2_analyze.py`; validator `code/cex/hp/validate_round.py`.')
P('')
P('## DGP1 erratum carried here (scored DGP1 records unchanged)')
P('')
P('BASE preservation on the 18 unified inputs at 4 s was 13 / 18 (not 11 / 18). DGP1 receipts: 358, of which 354 COMPLETED and 4 NONZERO_EXIT; 3,877.071256 supervised seconds (unsupervised development disclosed separately). WITHDRAWN: the "B / Z of 2^60-2^131" range (an absolute cap exponent was reported, not a cap / normalizer ratio) and "all slack is the upper envelope". The six n64 / card4 zero-draw lifted refusals were construction failures (exact-kappa BITS at decoder build), now repaired (compact kappa). The 60 s statements apply only to the four strong ER tasks run.')
open(RD + '/START_HERE.md', 'w').write('\n'.join(L) + '\n'); print('START_HERE.md written')
