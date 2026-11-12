"""Finalize the repair pass (candidate tag given as argv[2]: v12 or v13) from SAVED artifacts only (no execution): the repaired comparator gate on baseline (unchanged campaigns) vs new-arm v1.2 campaigns;
the isolated baseline DIABETES rerun beside its original (both preserved); the fresh-process locked plans (exact coordinates recomputed from the retained strings);
the residual-failure classification of the v1.2 20 s campaign by MEASURED PHASE (core_trace.phase + executor attempts), with conditional estimates labelled as such.
    python cex/finalize_v12.py <RD>"""
import sys, os, json, subprocess, collections, statistics
from fractions import Fraction as F
sys.set_int_max_str_digits(0); RD = sys.argv[1]; TAG = sys.argv[2] if len(sys.argv) > 2 else 'v12'; LOCKED = {'v12': 'v12_fresh_2', 'v13': 'v13_fresh', 'v14': 'v14_fresh'}[TAG]; HERE = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable
SPECS = os.path.join(RD, 'campaign_specs')
out = {}
# ---- 1. gate: baseline (unchanged) vs v1.2
for tag, b, n in (('20s_all46_' + TAG, 'baseline_20s_all46', 'newarm_20s_all46_' + TAG), ('120s_panel13_' + TAG, 'baseline_120s_panel13', 'newarm_120s_panel13_' + TAG)):
    p = subprocess.run([PY, os.path.join(HERE, 'compare_campaigns.py'), os.path.join(RD, 'campaigns', b), os.path.join(RD, 'campaigns', n), os.path.join(RD, 'COMPARISON_%s.json' % tag), os.path.join(SPECS, b + '.json'), os.path.join(SPECS, n + '.json')], capture_output=True, text=True)
    out['gate_' + tag] = dict(exit=p.returncode, stdout=p.stdout[-3000:], stderr=p.stderr[-800:], specs=[b + '.json', n + '.json'])
    print(tag, 'gate exit', p.returncode); print(p.stdout[:1500])
# ---- 2. DIABETES isolated rerun vs original (baseline, 120 s)
def rec(camp, case):
    r = [x for x in json.load(open(os.path.join(RD, 'campaigns', camp, 'receipts.json'))) if x['case'] == case]; w = json.load(open(os.path.join(RD, 'campaigns', camp, case + '.json')))
    return dict(status=r[0]['status'] if r else None, wall_s=r[0]['wall_s'] if r else None, peak_tree_rss_MB=round((r[0].get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1) if r else None, reason=(w.get('reason') or '')[:120], phase=((w.get('stop_stats') or {}).get('core_trace') or {}).get('phase'), route=[c.get('route') for c in (((w.get('stop_stats') or {}).get('core_trace') or {}).get('component_plans') or [])])
d0 = rec('baseline_120s_panel13', 'DIABETES'); d1 = rec('baseline_120s_diabetes_isolated_rerun', 'DIABETES') if os.path.exists(os.path.join(RD, 'campaigns', 'baseline_120s_diabetes_isolated_rerun', 'receipts.json')) else None
out['diabetes_baseline_120s'] = dict(original_overlapped_attempt=d0, isolated_rerun=d1, note='the original attempt (21:15:19-21:17:19Z) overlapped a 5.2 s development qualification job; both attempts preserved; the isolated rerun is the clean observation')
print('DIABETES', json.dumps(out['diabetes_baseline_120s'], default=str)[:600])
# ---- 3. locked plans v1.2 fresh process (attempt 2; attempt 1 preserved as a failed attempt)
L = {}
import glob as _g
for src_path in sorted(_g.glob(os.path.join(RD, 'locked_plan', LOCKED, '**', '*.json'), recursive=True)):      # per-case attempt directories (locked_plan v3 refuses a reused directory) and the flat layout alike
    f = os.path.basename(src_path)
    if f.endswith('.plan.json') or '.new.' in f or '.baseline.' in f: continue
    d = json.load(open(src_path)); ex = d.get('executors') or {}      # (follow-up review §6: the path is the SELECTED directory; its name is recorded in every summary)
    if 'case' not in d: continue
    # recompute containment from the retained coordinates
    rc = d.get('retained_coordinates') or {}; cont = None; coords = 0
    if 'new' in rc and 'baseline' in rc and ex.get('new', {}).get('status') == 'COMPLETED' and ex.get('baseline', {}).get('status') == 'COMPLETED':
        cont = True
        for cn, cb in zip(rc['new'], rc['baseline']):
            for row, ps in zip(cn['intervals'], cb['points']):
                for (lo, hi), p in zip(row, ps): coords += 1; cont = cont and F(lo) <= F(p) <= F(hi)
    L[d['case']] = dict(source_file=os.path.relpath(src_path, RD), plan_sha256=d.get('plan_sha256'), kernel_source=((ex.get('new') or {}).get('components') or [{}])[0].get('kernel', {}).get('source_sha256') if (ex.get('new') or {}).get('components') else None, plan_construction_s=round(d['plan_construction_s'], 3), arms={a: dict(status=(r.get('status') if r.get('status') not in ('NO_OUTPUT', None) else r.get('process_outcome')), process_outcome=r.get('process_outcome'), returncode=r.get('returncode'), rejection_reasons=r.get('rejection_reasons'), wall_s=round(r.get('wall_s') or r.get('parent_measured_wall_s') or 0, 2), own_peak_rss_MB=round((r.get('peak_rss_bytes_this_process') or 0) / 2 ** 20, 1), tree_rss_MB=round((r.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1), stop=(str(r.get('stop'))[:100] if r.get('stop') else None), kernel_s=(r['components'][0].get('kernel_s') if r.get('components') else None), K=(r['components'][0].get('max_label_K') if r.get('components') else None), peak_logical_MB=round(((r['components'][0].get('counters') or {}).get('peak_logical_bytes') or 0) / 2 ** 20, 1) if r.get('components') else None) for a, r in ex.items()}, recomputed_containment=cont, coordinates=coords, recorded_containment=d.get('new_encloses_exact_reference'), worst_excursion=d.get('worst_excursion'))
out['locked_plans_fresh_process_' + TAG] = L; print('LOCKED', json.dumps(L, default=str)[:1500])
# ---- 4. residual failures of the v1.2 20 s campaign by measured phase
D = os.path.join(RD, 'campaigns', 'newarm_20s_all46_' + TAG)
if os.path.exists(os.path.join(D, 'receipts.json')):
    R = {r['case']: r for r in json.load(open(os.path.join(D, 'receipts.json')))}; rows = []
    for case, r in sorted(R.items()):
        if r['status'] == 'COMPLETED': continue
        w = json.load(open(os.path.join(D, case + '.json'))); ct = ((w.get('stop_stats') or {}).get('core_trace') or {}); plans = ct.get('component_plans') or []
        att = [(dd.get('status'), dd.get('stop'), (dd.get('reason') or '')[:90], round(dd.get('wall_s', 0), 2), ((dd.get('stats') or {}).get('counters') or {}).get('forward_rows'), ((dd.get('stats') or {}).get('counters') or {}).get('peak_logical_bytes'), cp.get('forecast')) for cp in plans for dd in cp.get('discovery', []) if dd.get('kind') in ('compiled_executor', 'exact_reference_fallback')]
        routes = [cp.get('route') for cp in plans]; prep = (w.get('parse_s') or 0) + sum((x.get('wall_s') or 0) for x in (ct.get('root_discovery') or [])) + sum((dd.get('planning_wall_s') or 0) for cp in plans for dd in cp.get('discovery', []) if 'planning_wall_s' in dd) + ((ct.get('reduction') or {}).get('elapsed_s') or 0)
        kinds = {a[1] for a in att if a[0] == 'STOP'}
        if ct.get('phase') == 'execution' and routes and all(x == 'dag' for x in routes): cls = 'EXECUTION of the selected exact source-DAG route (Python Fraction executor, untouched by this pass) exceeds the budget after ~%.2f s of recognition/reduction/planning; a faster DAG executor, a cheaper plan, or both may help' % prep
        elif 'MEMORY' in kinds: cls = 'EXECUTION: typed MEMORY refusal at the kernel allocation boundary (live storage of this plan under this schedule exceeds the cap); plan size behind it'
        elif 'DEADLINE' in kinds: cls = 'EXECUTION: the compiled kernel ran the whole budget (DEADLINE); CONDITIONAL estimate at the observed rate puts the plan far beyond 20 s -- plan size under this schedule, not a task lower bound'
        elif 'RANGE' in kinds: cls = 'EXECUTION (arithmetic range): a nonzero product left the binary64 normal range inside a bucket (typed RANGE; the traces report the product, not a stored-relation dynamic range); the exact fallback then exceeded its row cap / budget'
        elif 'REPRESENTATION' in kinds: cls = 'EXECUTION: typed REPRESENTATION refusal (volume not addressable)'
        else: cls = 'phase=%s: %s' % (ct.get('phase'), (w.get('reason') or '')[:80])
        rows.append(dict(case=case, status=r['status'], wall_s=round(r['wall_s'], 1), measured_phase=ct.get('phase'), routes=routes, preparation_s_measured=round(prep, 2), executor_attempts=att[:4], peak_tree_rss_MB=round((r.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20), classification=cls))
    json.dump(rows, open(os.path.join(RD, 'RESIDUAL_FAILURES_20s_%s.json' % TAG), 'w'), indent=1, default=str)
    out['residual_20s_classes_' + TAG] = dict(collections.Counter(r['classification'].split(':')[0].split(' (')[0] for r in rows)); print('RESIDUAL', out['residual_20s_classes_' + TAG])
    for r in rows: print('  %-19s %-8s %5.1f phase=%-10s %s | %s' % (r['case'], r['status'], r['wall_s'], r['measured_phase'], r['routes'][:2], str(r['executor_attempts'][:1])[:110]))
json.dump(out, open(os.path.join(RD, 'FINALIZE_%s.json' % TAG.upper()), 'w'), indent=1, default=str)
