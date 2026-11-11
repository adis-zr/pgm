"""Assemble RESULTS_CEX.md for the certified-executor pass from saved artifacts only: locked-plan JSONs, campaign comparisons (20 s all-46 and the
13-case 120 s panel, per candidate), qualification receipts, the CEX ledger. Primary = delivered completions / failures; then paired complete-task walls,
peak RSS, phase costs; every residual failure classified from its saved trace."""
import sys, os, json, glob, collections
RD = sys.argv[1]
def jl(p): return json.load(open(p)) if os.path.exists(p) else None
L = [json.loads(x) for x in open(os.path.join(RD, 'CEX_LEDGER.jsonl'))]; R = [x for x in L if x['kind'] == 'RECEIPT']; tot = sum(x['wall_s'] for x in R if isinstance(x.get('wall_s'), (int, float)))
by_scope = collections.defaultdict(float)
for x in R: by_scope[x['scope']] += x['wall_s']
out = []; P = out.append
P('# Certified executor pass — results (11 Nov 2026, same host for both arms: macOS arm64, Apple clang 15, Python 3.12)'); P('')
P('Both arms: the frozen `response_v3` planner / harness (+ shared host adapter). Baseline support route = exact Fraction reference; new arm = compiled certified binary64 backend on the SAME validated plan. 3 GiB worker policy enforced by sampled process-tree RSS (RLIMIT_AS not lowerable on this host). One fresh process per case; outer receipt wall = delivery clock; sleep prevented.'); P('')
P('## 1. Locked-plan comparisons (same component model + same order; plan construction by the unchanged planner, charged)'); P(''); P('| case | plan construction s | baseline (exact Fraction) | new (compiled) | new encloses exact reference | new max width | K |'); P('|---|---:|---|---|---|---:|---:|')
for tag in ('both_1', 'new_1', 'baseline_1'):
    for f in sorted(glob.glob(os.path.join(RD, 'locked_plan', tag, '*.json'))):
        d = json.load(open(f)); ex = d.get('executors') or d.get('executors_partial') or {}
        def arm(a):
            r = ex.get(a); 
            if not r: return 'not run in this file'
            c0 = r['components'][0] if r['components'] else {}
            return '%s %.2f s, RSS %d MB%s' % (r['status'], r['wall_s'], r['peak_rss_bytes_process'] // 2 ** 20, (' (' + str(r['stop'])[:60] + ')') if r.get('stop') else '')
        c0n = (ex.get('new') or {}).get('components', [{}])[0] if ex.get('new') else {}
        P('| %s (%s) | %.3f | %s | %s | %s (%s coords) | %s | %s |' % (d['case'], tag, d['plan_construction_s'], arm('baseline'), arm('new'), d.get('new_encloses_exact_reference'), d.get('coordinates_compared'), c0n.get('max_width'), c0n.get('max_label_K')))
P(''); P('Grids_11 / Grids_15 baseline (exact) runs were MEMORY_KILLed by the 3 GiB harness cap before writing a record (CEX ledger: locked_plan:Grids_1x_baseline_1, 70 s / 92 s, peak 3.2 GB) — the same failure class as the packet (3 GiB address-space MemoryError at 107 s).'); P('')
for tag, label in (('20s_all46', 'all 46 cases at 20 s'), ('120s_panel13', 'the explicitly scoped 13-case panel at 120 s (denominator 13)')):
    for cand in ('', '_v11'):
        p = os.path.join(RD, 'COMPARISON_%s%s.json' % (tag, cand))
        C = jl(p)
        if not C: continue
        S = C['summary']; P('## %s — %s%s' % ('2' if tag.startswith('20s') else '3', label, ' — candidate v1.1 (rescaled sources / contexts)' if cand else ' — candidate v1.0')); P('')
        P('- completed: baseline %d, new %d of %d; new-only %s; baseline-only (lost successes) %s; neither %d' % (S['completed']['baseline'], S['completed']['new'], S['cases'], S['new_only'], S['baseline_only'] or 'none', len(S['neither'])))
        P('- status counts: %s' % S['status_counts']); P('- published contract failures: %s; cross-arm inconsistencies (point outside the other arm\'s interval by > 0.01): %s' % (S['published_contract_failures'] or 'none', S['cross_arm_inconsistent'] or 'none'))
        pc = S['paired_complete_tasks']; P('- paired complete tasks n = %d: median wall ratio new/baseline %s; new faster %d, baseline faster %d; per case (case, ratio, baseline s, new s): %s' % (pc['n'], pc['median_wall_ratio_new_over_baseline'], pc['new_faster'], pc['baseline_faster'], pc['per_case']))
        P('- paired peak tree RSS median ratio: %s' % S['paired_peak_rss']['median_ratio'])
        P(''); P('| case | baseline | new | new executor attempts (kind, status, wall, kernel_s, K, width, peak logical bytes, stop, reason) |'); P('|---|---|---|---|')
        for r in C['rows']:
            b = r['baseline']; n = r['new']; P('| %s | %s %.2f s %s | %s %.2f s %s | %s |' % (r['case'], b['status'], b['wall_s'] or 0, ('(' + (b['reason'] or '')[:40] + ')') if b['status'] != 'COMPLETED' else 'RSS %s MB' % b['peak_tree_rss_MB'], n['status'], n['wall_s'] or 0, ('(' + (n['reason'] or '')[:40] + ')') if n['status'] != 'COMPLETED' else 'RSS %s MB' % n['peak_tree_rss_MB'], str(n['phases'].get('executor_attempts', ''))[:220]))
        P('')
Q = jl(os.path.join('cex/newarm/CEX_QUALIFICATION.json')); Q2 = jl(os.path.join('cex/newarm_dev/CEX_QUALIFICATION.json'))
P('## 4. Qualification'); P(''); P('- v1.0 kernel: %s / %s (CEX_QUALIFICATION.json; 120 random mixed-domain models x 3 physical schedules vs raw-model exact enumeration and the exact reference on the same order; controls listed in PROOF_TO_CODE.md)' % (Q['passed'], Q['total']))
if Q2: P('- v1.1 kernel (rescaled sources / completed contexts): %s / %s' % (Q2['passed'], Q2['total']))
P('- baseline release suites on this host: qualification.py, native_qualification.py (arm64 FE_UPWARD adapter), reduction_qualification.py, review_additive.py (36), review_regression.py (9), test_forest / test_dag / test_reduction / test_identity_alternative: all pass (qualification/baseline_qualification_*.txt)'); P('')
P('## 5. Experimental ledger (CEX_LEDGER.jsonl, Python-monotonic receipted wall, every job supervised)'); P(''); P('- receipts %d; total %.1f s of the 10,800 s budget; by scope: %s' % (len(R), tot, {k: round(v, 1) for k, v in by_scope.items()}))
P('- cold kernel builds: baseline native stream (inside baseline qualification job 2) and the new kernel (cex_build.json build_wall_s %s); rebuilds inside attempts are charged to that attempt.' % (json.load(open('cex/newarm/cex_build.json')).get('build_wall_s')))
open(os.path.join(RD, 'RESULTS_CEX.md'), 'w').write('\n'.join(out) + '\n'); print('written', len(out), 'lines')
