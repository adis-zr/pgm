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
for tag in ('both_1', 'new_1', 'baseline_1', 'v12_fresh_2', 'v13_fresh', 'v14_fresh'):
    for f in sorted(glob.glob(os.path.join(RD, 'locked_plan', tag, '**', '*.json'), recursive=True)):
        if f.endswith('.plan.json') or '.new.json' in f or '.baseline.json' in f: continue      # fresh-process per-arm files and serialized plans are not case records
        d = json.load(open(f)); ex = d.get('executors') or d.get('executors_partial') or {}
        if 'case' not in d: continue
        def arm(a):
            r = ex.get(a); 
            if not r: return 'not run in this file'
            c0 = r['components'][0] if r['components'] else {}
            if r.get('status') in ('NO_OUTPUT', None) and r.get('process_outcome'): r = dict(r, status=r['process_outcome'])
            wall = r.get('wall_s') if r.get('wall_s') is not None else r.get('parent_measured_wall_s', 0); rssb = r.get('peak_rss_bytes_process') if r.get('peak_rss_bytes_process') is not None else (r.get('peak_rss_bytes_this_process') or r.get('peak_tree_rss_bytes_sampled') or 0)
            return '%s %.2f s, RSS %d MB%s%s' % (r['status'], wall, rssb // 2 ** 20, (' (' + str(r['stop'])[:60] + ')') if r.get('stop') else '', ' [fresh process; tree RSS %d MB]' % ((r.get('peak_tree_rss_bytes_sampled') or 0) // 2 ** 20) if 'peak_rss_bytes_this_process' in r or r.get('process_outcome') else '')
        c0n = (ex.get('new') or {}).get('components', [{}])[0] if ex.get('new') else {}
        P('| %s (%s) | %.3f | %s | %s | %s (%s coords) | %s | %s |' % (d['case'], tag, d['plan_construction_s'], arm('baseline'), arm('new'), d.get('new_encloses_exact_reference'), d.get('coordinates_compared'), c0n.get('max_width'), c0n.get('max_label_K')))
P(''); P('Grids_11 / Grids_15 baseline (exact) runs were MEMORY_KILLed by the 3 GiB harness cap before writing a record (CEX ledger: locked_plan:Grids_1x_baseline_1, 70 s / 92 s, peak 3.2 GB) — the same failure class as the packet (3 GiB address-space MemoryError at 107 s).'); P('')
for tag, label in (('20s_all46', 'all 46 cases at 20 s'), ('120s_panel13', 'the explicitly scoped 13-case panel at 120 s (denominator 13)')):
    for cand in ('', '_v11', '_v11_gated', '_v12', '_v13', '_v14'):
        p = os.path.join(RD, 'COMPARISON_%s%s.json' % (tag, cand))
        C = jl(p)
        if not C: continue
        S = C['summary']; P('## %s — %s%s' % ('2' if tag.startswith('20s') else '3', label, {'': ' — candidate v1.0', '_v11': ' — candidate v1.1 (rescaled sources / contexts)', '_v11_gated': ' — candidate v1.1 re-read through the REPAIRED audit gate (comparator v2)', '_v12': ' — candidate v1.2 (repaired kernel / executor with tracemalloc host accounting; new arm rerun, baseline campaigns unchanged)', '_v13': ' — candidate v1.3 (= v1.2 kernel; host accounting by counted bytes + RSS growth)', '_v14': ' — candidate v1.4 (checked metadata + ABI bounds; HostBudget charged before construction; streamed hash; terminal deadlines; gate v3 with campaign specifications; FINAL)'}[cand])); P('')
        comp = S.get('completed') or S.get('completed_and_gated')
        P('- completed%s: baseline %d, new %d of %d; new-only %s; baseline-only (lost successes) %s; neither %d' % (' (and passing the v2 audit gate)' if 'completed_and_gated' in S else '', comp['baseline'], comp['new'], S['cases'], S['new_only'], S['baseline_only'] or 'none', len(S['neither'])))
        P('- status counts: %s' % S['status_counts'])
        if 'gate_failures' in S: P('- AUDIT GATE (comparator v2): %s; failures: %s; cross-arm STRICT mutual containment failures: %s; points differing by > 1/100: %s; coordinates mutually contained: %d' % ('PASSED' if S['gate_passed'] else 'FAILED', S['gate_failures'] or 'none', S['cross_arm_not_mutually_contained'] or 'none', S['cross_arm_inconsistent'] or 'none', S['coordinates_mutually_contained']))
        else: P('- published contract failures: %s; cross-arm inconsistencies (new point outside the baseline interval widened by 0.01 -- the v1 comparator\'s one-directional predicate, superseded by the v2 gate): %s' % (S['published_contract_failures'] or 'none', S['cross_arm_inconsistent'] or 'none'))
        if 'paired_support_route_tasks' in S: P('- support-route pairs (the executor under test; case, ratio, baseline s, new s): %s' % S['paired_support_route_tasks']['per_case'])
        pc = S['paired_complete_tasks']; P('- paired complete tasks n = %d: median wall ratio new/baseline %s; new faster %d, baseline faster %d; per case (case, ratio, baseline s, new s): %s' % (pc['n'], pc['median_wall_ratio_new_over_baseline'], pc['new_faster'], pc['baseline_faster'], pc['per_case']))
        P('- paired peak tree RSS median ratio: %s' % S['paired_peak_rss']['median_ratio'])
        P(''); P('| case | baseline | new | new executor attempts (kind, status, wall, kernel_s, K, width, peak logical bytes, stop, reason) |'); P('|---|---|---|---|')
        for r in C['rows']:
            b = r['baseline']; n = r['new']; P('| %s | %s %.2f s %s | %s %.2f s %s | %s |' % (r['case'], b['status'], b['wall_s'] or 0, ('(' + (b['reason'] or '')[:40] + ')') if b['status'] != 'COMPLETED' else 'RSS %s MB' % b['peak_tree_rss_MB'], n['status'], n['wall_s'] or 0, ('(' + (n['reason'] or '')[:40] + ')') if n['status'] != 'COMPLETED' else 'RSS %s MB' % n['peak_tree_rss_MB'], str(n['phases'].get('executor_attempts', ''))[:220]))
        P('')
P('## 4. Qualification'); P('')
for ver in ('v1.0', 'v1.1', 'v1.2', 'v1.3', 'v1.4'):
    Q = jl(os.path.join(RD, 'kernel_versions', 'CEX_QUALIFICATION_%s.json' % ver))
    if Q: P('- %s: %s / %s counted tests and control groups (%s random executions %s + %d grouped controls; NOT a count of enclosures); controls: %s' % (ver, Q['passed'], Q['total'], len(Q.get('records', [])), dict(collections.Counter(r['status'] for r in Q.get('records', []))), len(Q.get('controls', [])), [c['name'] for c in Q.get('controls', []) if not c.get('ok')] or 'all OK'))
P('- reviewer\'s independent fuzz suites (unchanged scripts, own exact oracle) on v1.2 / v1.3 on this host: 1,050/1,050 and 1,500/1,500 (qualification/cex_qualification_v12_2.txt, cex_qualification_v13_1.txt)')
P('- baseline release suites on this host: qualification.py, native_qualification.py (arm64 FE_UPWARD adapter), reduction_qualification.py, review_additive.py (36), review_regression.py (9), test_forest / test_dag / test_reduction / test_identity_alternative: all pass, every suite exit status 0 (qualification/baseline_qualification_v2.txt, exit propagation)'); P('')
P('## 5. Experimental ledger (CEX_LEDGER.jsonl, Python-monotonic receipted wall, every job supervised)'); P(''); P('- receipts %d; total %.1f s of the 10,800 s budget; by scope: %s' % (len(R), tot, {k: round(v, 1) for k, v in by_scope.items()}))
P('- cold kernel builds: baseline native stream (inside baseline qualification job 2) and the new kernel (cex_build.json build_wall_s %s); rebuilds inside attempts are charged to that attempt.' % (json.load(open('cex/newarm/cex_build.json')).get('build_wall_s')))
open(os.path.join(RD, 'RESULTS_CEX.md'), 'w').write('\n'.join(out) + '\n'); print('written', len(out), 'lines')
