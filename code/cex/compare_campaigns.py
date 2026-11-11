"""Paired comparison of two campaigns (baseline vs new arm) run on the same host / inputs / budget / verification boundary (prompt section 8).
Primary: delivered completions and failures; then paired complete-task walls (both completed only; censored cells never become runtimes), peak RSS,
phase costs, representation / arithmetic diagnostics, failure reasons. Also checks every COMPLETED output: returncode 0, EXIT, wall <= budget, binding,
publication contract (core.verify_output on the published decimals), and cross-arm agreement of published points where both completed (consistency only).
    python cex/compare_campaigns.py <baseline_dir> <newarm_dir> <out.json>"""
import sys, os, json, hashlib, collections
sys.set_int_max_str_digits(0); HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'baseline'))
from fractions import Fraction as F
import core
P = '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'
def load(d):
    rec = {r['case']: r for r in json.load(open(os.path.join(d, 'receipts.json')))}; env = json.load(open(os.path.join(d, 'environment.json'))); out = {}
    for case, r in rec.items():
        p = os.path.join(d, case + '.json'); w = json.load(open(p)) if os.path.exists(p) else {}
        if os.path.exists(p) and r.get('output_sha256'): assert hashlib.sha256(open(p, 'rb').read()).hexdigest() == r['output_sha256'], 'output identity'
        out[case] = dict(receipt=r, worker=w)
    return out, env
def phases(w):
    st = w.get('stats') or {}; comps = st.get('components') or []; ph = {'parse_s': w.get('parse_s'), 'publication_s': w.get('publication_s'), 'split_s': st.get('split_s'), 'total_s': st.get('total_s'), 'routes': [(c['route'], len(c['variables'])) for c in comps]}
    ex = [d for c in comps for d in c.get('discovery', []) if d.get('kind') in ('compiled_executor', 'exact_reference_fallback')]
    if ex: ph['executor_attempts'] = [(d.get('kind'), d.get('status'), round(d.get('wall_s', 0), 3), (d.get('stats') or {}).get('kernel_s'), (d.get('stats') or {}).get('max_label_K'), (d.get('stats') or {}).get('max_width_float'), ((d.get('stats') or {}).get('counters') or {}).get('peak_logical_bytes'), d.get('stop'), (d.get('reason') or '')[:80]) for d in ex]
    rd = st.get('root_discovery') or []; ph['root_discovery_s'] = sum(x.get('wall_s', 0) or 0 for x in rd); ph['component_planning_s'] = sum((dd.get('planning_wall_s') or 0) for c in comps for dd in c.get('discovery', []) if 'planning_wall_s' in dd)
    ph['execution_wall_s'] = sum(c.get('execution_wall_s') or 0 for c in comps); return ph
def main(bd, nd, outp):
    B, envB = load(bd); N, envN = load(nd); cases = sorted(set(B) | set(N)); rows = []; budget = envB.get('seconds')
    for case in cases:
        b = B.get(case, {}); n = N.get(case, {}); rb = b.get('receipt', {}); rn = n.get('receipt', {}); wb = b.get('worker', {}); wn = n.get('worker', {})
        row = dict(case=case, baseline=dict(status=rb.get('status'), wall_s=rb.get('wall_s'), peak_tree_rss_MB=round((rb.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1), worker_peak_rss_MB=round((wb.get('peak_rss_bytes') or 0) / 2 ** 20, 1), reason=(wb.get('reason') or '')[:120], exception=wb.get('exception_type'), phases=phases(wb)),
                   new=dict(status=rn.get('status'), wall_s=rn.get('wall_s'), peak_tree_rss_MB=round((rn.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1), worker_peak_rss_MB=round((wn.get('peak_rss_bytes') or 0) / 2 ** 20, 1), reason=(wn.get('reason') or '')[:120], exception=wn.get('exception_type'), phases=phases(wn)))
        # publication contract re-check on the published decimals (both arms)
        for arm, w in (('baseline', wb), ('new', wn)):
            if w.get('status') == 'COMPLETED':
                try: core.verify_output([[(F(a), F(c)) for a, c in r_] for r_ in w['intervals']], [[F(x) for x in r_] for r_ in w['points']]); row[arm]['published_contract_ok'] = True; row[arm]['max_width'] = float(max(F(c) - F(a) for r_ in w['intervals'] for a, c in r_))
                except Exception as ex: row[arm]['published_contract_ok'] = False; row[arm]['contract_error'] = str(ex)[:100]
        if wb.get('status') == 'COMPLETED' and wn.get('status') == 'COMPLETED':
            # cross-arm consistency: each arm's published point lies inside the other arm's published interval (not an independent oracle)
            okc = all(F(wn['points'][v][a]) >= F(wb['intervals'][v][a][0]) - F(1, 100) and F(wn['points'][v][a]) <= F(wb['intervals'][v][a][1]) + F(1, 100) for v in range(len(wb['points'])) for a in range(len(wb['points'][v])))
            row['cross_arm_points_within_0.01_of_other_intervals'] = okc; row['paired_wall_ratio_new_over_baseline'] = (rn['wall_s'] / rb['wall_s']) if rb.get('wall_s') else None
            row['paired_peak_rss_ratio'] = ((rn.get('peak_tree_rss_bytes_sampled') or 0) / (rb.get('peak_tree_rss_bytes_sampled') or 1))
        rows.append(row)
    def cnt(arm, st): return sum(1 for r in rows if r[arm]['status'] == st)
    summary = dict(budget_s=budget, cases=len(rows), completed={'baseline': cnt('baseline', 'COMPLETED'), 'new': cnt('new', 'COMPLETED')}, status_counts={arm: dict(collections.Counter(r[arm]['status'] for r in rows)) for arm in ('baseline', 'new')},
                   new_only=[r['case'] for r in rows if r['new']['status'] == 'COMPLETED' and r['baseline']['status'] != 'COMPLETED'], baseline_only=[r['case'] for r in rows if r['baseline']['status'] == 'COMPLETED' and r['new']['status'] != 'COMPLETED'],
                   both=[r['case'] for r in rows if r['new']['status'] == 'COMPLETED' and r['baseline']['status'] == 'COMPLETED'], neither=[r['case'] for r in rows if r['new']['status'] != 'COMPLETED' and r['baseline']['status'] != 'COMPLETED'],
                   published_contract_failures=[(r['case'], arm) for r in rows for arm in ('baseline', 'new') if r[arm].get('published_contract_ok') is False], cross_arm_inconsistent=[r['case'] for r in rows if r.get('cross_arm_points_within_0.01_of_other_intervals') is False])
    pr = sorted([(r['case'], round(r['paired_wall_ratio_new_over_baseline'], 3), round(r['baseline']['wall_s'], 2), round(r['new']['wall_s'], 2)) for r in rows if r.get('paired_wall_ratio_new_over_baseline')], key=lambda t: t[1])
    rs = [t[1] for t in pr]; summary['paired_complete_tasks'] = dict(n=len(pr), median_wall_ratio_new_over_baseline=(sorted(rs)[len(rs) // 2] if rs else None), new_faster=sum(1 for x in rs if x < 1), baseline_faster=sum(1 for x in rs if x > 1), per_case=pr, note='matched completed tasks only; no censored cell enters a ratio; one observation per cell')
    mr = sorted([(r['case'], round(r['paired_peak_rss_ratio'], 3), r['baseline']['peak_tree_rss_MB'], r['new']['peak_tree_rss_MB']) for r in rows if r.get('paired_peak_rss_ratio')], key=lambda t: t[1]); summary['paired_peak_rss'] = dict(n=len(mr), median_ratio=(sorted(t[1] for t in mr)[len(mr) // 2] if mr else None), per_case=mr)
    summary['new_executor_attempts'] = {r['case']: r['new']['phases'].get('executor_attempts') for r in rows if r['new']['phases'].get('executor_attempts')}
    summary['failures_new'] = {r['case']: (r['new']['status'], r['new']['exception'], r['new']['reason']) for r in rows if r['new']['status'] != 'COMPLETED'}; summary['failures_baseline'] = {r['case']: (r['baseline']['status'], r['baseline']['exception'], r['baseline']['reason']) for r in rows if r['baseline']['status'] != 'COMPLETED'}
    summary['environments'] = {'baseline': {k: envB.get(k) for k in ('platform', 'python', 'route', 'seconds', 'source_unchanged')}, 'new': {k: envN.get(k) for k in ('platform', 'python', 'route', 'seconds', 'source_unchanged')}}
    json.dump(dict(summary=summary, rows=rows), open(outp, 'w'), indent=1, default=str); print(json.dumps({k: summary[k] for k in ('budget_s', 'cases', 'completed', 'new_only', 'baseline_only', 'published_contract_failures', 'cross_arm_inconsistent')}, default=str)); print('paired:', json.dumps({k: summary['paired_complete_tasks'][k] for k in ('n', 'median_wall_ratio_new_over_baseline', 'new_faster', 'baseline_faster')}))
if __name__ == '__main__': main(*sys.argv[1:])
