"""Paired comparison of two campaigns (baseline vs new arm) on the same host / inputs / budget -- v3 (follow-up review of 11 Nov 2026 §4): an AUDIT GATE driven by
AUTHORITATIVE CAMPAIGN SPECIFICATIONS (cex/campaign_spec.py: expected cases, budget, route from the supervisor START row recorded before execution; source and binary
identities from the frozen artifact file). The gate FAILS (nonzero exit, every failure listed) unless:
  completeness: exactly ONE receipt per expected case in each arm; no missing, extra or duplicate receipt; the receipts' budget equals the specification's;
  identity: environment.source_hashes_before == source_hashes_after == the frozen artifact's hashes for every .py / .cpp of the arm, and the recorded shared-library
            hash equals the frozen build record's binary (new arm); `source_unchanged` is derived, never trusted; equal platform / Python / route / budget between arms;
  per COMPLETED record: returncode 0, EXIT, wall <= budget, output file present with the receipted sha256, worker status COMPLETED, model/evidence sha256 equal to
            the actual input files, one interval row and one point row per ORIGINAL variable of the right cardinality, observed variables one-hot, publication contract;
  cross-arm (both completed): STRICT MUTUAL CONTAINMENT of published points and the separate 1/100 tolerance (consistency only; not an oracle).
Then: delivered completions / failures, paired complete-task walls (both completed only), peak RSS, phases, residual reasons.
    python cex/compare_campaigns.py <baseline_dir> <newarm_dir> <out.json> <baseline_spec.json> <newarm_spec.json>        exit 0 iff the gate passes"""
import sys, os, json, hashlib, collections, glob
sys.set_int_max_str_digits(0); HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, 'baseline'))
from fractions import Fraction as F
import core
def load(d, spec, arm, failures):
    raw = json.load(open(os.path.join(d, 'receipts.json'))); env = json.load(open(os.path.join(d, 'environment.json'))); out = {}
    counts = collections.Counter(r['case'] for r in raw)
    for c, k in sorted(counts.items()):
        if k > 1: failures.append((c, arm, 'duplicate receipt (%d records)' % k))
    exp = set(spec['expected_cases'])
    for c in sorted(exp - set(counts)): failures.append((c, arm, 'case missing from the campaign (declared in the specification)'))
    for c in sorted(set(counts) - exp): failures.append((c, arm, 'case not in the specification (extra receipt)'))
    for r in raw:
        if r.get('budget_s') != spec['seconds']: failures.append((r['case'], arm, 'receipt budget %s differs from the specification %s' % (r.get('budget_s'), spec['seconds'])))
    if env.get('seconds') != spec['seconds']: failures.append(('*', arm, 'environment budget differs from the specification'))
    if env.get('route') != spec['route']: failures.append(('*', arm, 'environment route differs from the specification'))
    hb = env.get('source_hashes_before') or {}; ha = env.get('source_hashes_after') or {}
    if hb != ha: failures.append(('*', arm, 'source_hashes_before != source_hashes_after'))
    for f, h in spec['frozen_source_hashes'].items():
        if hb.get(f) != h: failures.append(('*', arm, 'source %s differs from the frozen artifact (%s vs %s)' % (f, (hb.get(f) or 'absent')[:12], h[:12])))
    for f in hb:
        if f.endswith(('.py', '.cpp')) and f not in spec['frozen_source_hashes']: failures.append(('*', arm, 'source %s present in the campaign but not in the frozen artifact' % f))
    if spec.get('frozen_binary_sha256') and hb.get('libcex_kernel.dylib') != spec['frozen_binary_sha256']: failures.append(('*', arm, 'kernel binary differs from the frozen build record'))
    for r in raw:
        case = r['case']; p = os.path.join(d, case + '.json'); w = json.load(open(p)) if os.path.exists(p) else {}
        out[case] = dict(receipt=r, worker=w, output_sha256_actual=(hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else None))
    return out, env
def phases(w):
    st = w.get('stats') or {}; comps = st.get('components') or []; ph = {'parse_s': w.get('parse_s'), 'publication_s': w.get('publication_s'), 'split_s': st.get('split_s'), 'total_s': st.get('total_s'), 'routes': [(c['route'], len(c['variables'])) for c in comps]}
    ex = [d for c in comps for d in c.get('discovery', []) if d.get('kind') in ('compiled_executor', 'exact_reference_fallback')]
    if ex: ph['executor_attempts'] = [(d.get('kind'), d.get('status'), round(d.get('wall_s', 0), 3), (d.get('stats') or {}).get('kernel_s'), (d.get('stats') or {}).get('max_label_K'), (d.get('stats') or {}).get('max_width_float'), ((d.get('stats') or {}).get('counters') or {}).get('peak_logical_bytes'), d.get('stop'), (d.get('reason') or '')[:80]) for d in ex]
    rd = st.get('root_discovery') or []; ph['root_discovery_s'] = sum(x.get('wall_s', 0) or 0 for x in rd); ph['component_planning_s'] = sum((dd.get('planning_wall_s') or 0) for c in comps for dd in c.get('discovery', []) if 'planning_wall_s' in dd)
    ph['execution_wall_s'] = sum(c.get('execution_wall_s') or 0 for c in comps); ph['stop_phase'] = ((w.get('stop_stats') or {}).get('core_trace') or {}).get('phase') if w.get('status') == 'STOPPED' else None; return ph
def gate_record(case, r, w, actual_sha, env, model, binding, failures, arm):
    """every condition a COMPLETED record must satisfy; appends (case, arm, condition) for each violation"""
    def need(cond, what):
        if not cond: failures.append((case, arm, what))
    need(r.get('returncode') == 0, 'returncode != 0'); need(r.get('process_outcome') == 'EXIT', 'process outcome %s (not EXIT)' % r.get('process_outcome'))
    need(isinstance(r.get('wall_s'), (int, float)) and isinstance(r.get('budget_s'), (int, float)) and r['wall_s'] <= r['budget_s'], 'receipt wall exceeds budget')
    need(r.get('budget_s') == env.get('seconds'), 'receipt budget differs from the campaign environment budget')
    need(actual_sha is not None and actual_sha == r.get('output_sha256'), 'output file missing or sha256 differs from the receipt')
    need(w.get('status') == 'COMPLETED', 'worker status %s' % w.get('status'))
    need(model is not None, 'input .uai missing for this case')
    if model is None: return
    need(w.get('binding') == binding, 'model/evidence binding differs from the actual input files')
    iv = w.get('intervals'); pts = w.get('points'); cards = model['cards']; ev = model.get('evidence', {})
    okshape = isinstance(iv, list) and isinstance(pts, list) and len(iv) == len(cards) and len(pts) == len(cards) and all(len(row) == c and len(pr) == c for row, pr, c in zip(iv, pts, cards))
    need(okshape, 'output shape differs from the original model (rows / cardinalities)')
    if not okshape: return
    try:
        IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]
        core.verify_output(IV, PT)
        for v, a in ev.items(): need(all((PT[v][s] == 1 and IV[v][s] == (F(1), F(1))) if s == a else (PT[v][s] == 0 and IV[v][s] == (F(0), F(0))) for s in range(cards[v])), 'observed variable %d is not one-hot' % v)
    except Exception as ex: need(False, 'publication contract: %s' % str(ex)[:80])
def main(bd, nd, outp, bspec, nspec):
    SB = json.load(open(bspec)); SN = json.load(open(nspec)); failures = []
    if SB['expected_cases'] != SN['expected_cases']: failures.append(('*', 'both', 'the two specifications declare different case sets'))
    if SB['seconds'] != SN['seconds'] or SB['route'] != SN['route']: failures.append(('*', 'both', 'the two specifications declare different budgets / routes'))
    inputs = SB['inputs_dir']
    B, envB = load(bd, SB, 'baseline', failures); N, envN = load(nd, SN, 'new', failures)
    for k in ('seconds', 'platform', 'python', 'route'):
        if envB.get(k) != envN.get(k): failures.append(('*', 'both', 'environment %s differs between arms' % k))
    cases = sorted(set(SB['expected_cases']) | set(B) | set(N)); budget = SB['seconds']
    models = {}
    for case in cases:
        p = os.path.join(inputs, case + '.uai'); models[case] = core.read_uai(p) if os.path.exists(p) else (None, None)
    rows = []
    for case in cases:
        b = B.get(case, {}); n = N.get(case, {}); rb = b.get('receipt', {}); rn = n.get('receipt', {}); wb = b.get('worker', {}); wn = n.get('worker', {}); model, binding = models[case]
        row = dict(case=case, baseline=dict(status=rb.get('status'), wall_s=rb.get('wall_s'), peak_tree_rss_MB=round((rb.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1), worker_peak_rss_MB=round((wb.get('peak_rss_bytes') or 0) / 2 ** 20, 1), reason=(wb.get('reason') or '')[:120], exception=wb.get('exception_type'), phases=phases(wb)),
                   new=dict(status=rn.get('status'), wall_s=rn.get('wall_s'), peak_tree_rss_MB=round((rn.get('peak_tree_rss_bytes_sampled') or 0) / 2 ** 20, 1), worker_peak_rss_MB=round((wn.get('peak_rss_bytes') or 0) / 2 ** 20, 1), reason=(wn.get('reason') or '')[:120], exception=wn.get('exception_type'), phases=phases(wn)))
        for arm, r, w, sha in (('baseline', rb, wb, b.get('output_sha256_actual')), ('new', rn, wn, n.get('output_sha256_actual'))):
            if r.get('status') == 'COMPLETED' or w.get('status') == 'COMPLETED':
                before = len(failures); gate_record(case, r, w, sha, envB if arm == 'baseline' else envN, model, binding, failures, arm); row[arm]['gate_ok'] = len(failures) == before
                if w.get('intervals'):
                    try: row[arm]['max_width'] = float(max(F(c_) - F(a_) for r_ in w['intervals'] for a_, c_ in r_))
                    except Exception: pass
        if wb.get('status') == 'COMPLETED' and wn.get('status') == 'COMPLETED' and row['baseline'].get('gate_ok') and row['new'].get('gate_ok'):
            PB = [[F(x) for x in r_] for r_ in wb['points']]; PN = [[F(x) for x in r_] for r_ in wn['points']]; IB = [[(F(a), F(c)) for a, c in r_] for r_ in wb['intervals']]; IN = [[(F(a), F(c)) for a, c in r_] for r_ in wn['intervals']]
            mutual = all(IB[v][a][0] <= PN[v][a] <= IB[v][a][1] and IN[v][a][0] <= PB[v][a] <= IN[v][a][1] for v in range(len(PB)) for a in range(len(PB[v])))
            tol = all(abs(PN[v][a] - PB[v][a]) <= F(1, 100) for v in range(len(PB)) for a in range(len(PB[v])))
            row['cross_arm_strict_mutual_containment'] = mutual; row['cross_arm_points_within_0.01'] = tol; row['coordinates_compared'] = sum(len(r_) for r_ in PB)
            if not mutual: failures.append((case, 'both', 'published points are not mutually contained in the other arm\'s intervals'))
            if not tol: failures.append((case, 'both', 'published points differ by more than 1/100'))
            row['paired_wall_ratio_new_over_baseline'] = (rn['wall_s'] / rb['wall_s']) if rb.get('wall_s') else None; row['paired_peak_rss_ratio'] = ((rn.get('peak_tree_rss_bytes_sampled') or 0) / (rb.get('peak_tree_rss_bytes_sampled') or 1))
        rows.append(row)
    def cnt(arm, st): return sum(1 for r in rows if r[arm]['status'] == st and r[arm].get('gate_ok'))
    summary = dict(budget_s=budget, cases=len(rows), expected_cases=len(SB['expected_cases']), specification={'baseline': {k: SB[k] for k in ('job', 'kind', 'seconds', 'route', 'start_utc')}, 'new': {k: SN[k] for k in ('job', 'kind', 'seconds', 'route', 'start_utc')}}, gate_failures=failures, gate_passed=not failures, completed_and_gated={'baseline': cnt('baseline', 'COMPLETED'), 'new': cnt('new', 'COMPLETED')}, status_counts={arm: dict(collections.Counter(r[arm]['status'] for r in rows)) for arm in ('baseline', 'new')},
                   new_only=[r['case'] for r in rows if r['new']['status'] == 'COMPLETED' and r['baseline']['status'] != 'COMPLETED'], baseline_only=[r['case'] for r in rows if r['baseline']['status'] == 'COMPLETED' and r['new']['status'] != 'COMPLETED'],
                   both=[r['case'] for r in rows if r['new']['status'] == 'COMPLETED' and r['baseline']['status'] == 'COMPLETED'], neither=[r['case'] for r in rows if r['new']['status'] != 'COMPLETED' and r['baseline']['status'] != 'COMPLETED'],
                   cross_arm_not_mutually_contained=[r['case'] for r in rows if r.get('cross_arm_strict_mutual_containment') is False], cross_arm_inconsistent=[r['case'] for r in rows if r.get('cross_arm_points_within_0.01') is False], coordinates_mutually_contained=sum(r.get('coordinates_compared', 0) for r in rows if r.get('cross_arm_strict_mutual_containment')),
                   gate_scope='specification-driven: exactly one receipt per declared case (no missing / extra / duplicate), budget / route from the START row, source + binary identity derived from the frozen artifact hashes (source_unchanged never trusted); per record: process success, EXIT, wall <= budget, output identity, input binding, original-model shape, one-hot evidence rows, publication contract; cross-arm strict mutual containment + 1/100 tolerance (consistency, not an oracle)')
    pr = sorted([(r['case'], round(r['paired_wall_ratio_new_over_baseline'], 3), round(r['baseline']['wall_s'], 2), round(r['new']['wall_s'], 2)) for r in rows if r.get('paired_wall_ratio_new_over_baseline')], key=lambda t: t[1])
    rs = [t[1] for t in pr]; summary['paired_complete_tasks'] = dict(n=len(pr), median_wall_ratio_new_over_baseline=(sorted(rs)[len(rs) // 2] if rs else None), new_faster=sum(1 for x in rs if x < 1), baseline_faster=sum(1 for x in rs if x > 1), per_case=pr, note='matched completed tasks only; no censored cell enters a ratio; one observation per cell')
    sup = [(c, x, b_, n_) for c, x, b_, n_ in pr if any(rt == 'support' for rt, _ in next(r for r in rows if r['case'] == c)['new']['phases'].get('routes', []))]
    summary['paired_support_route_tasks'] = dict(n=len(sup), per_case=sup, note='pairs whose new-arm trace contains a support-route component (the executor under test); the all-pairs median mostly measures untouched routes')
    mr = sorted([(r['case'], round(r['paired_peak_rss_ratio'], 3), r['baseline']['peak_tree_rss_MB'], r['new']['peak_tree_rss_MB']) for r in rows if r.get('paired_peak_rss_ratio')], key=lambda t: t[1]); summary['paired_peak_rss'] = dict(n=len(mr), median_ratio=(sorted(t[1] for t in mr)[len(mr) // 2] if mr else None), per_case=mr, note='fresh-process sampled tree RSS per arm')
    summary['new_executor_attempts'] = {r['case']: r['new']['phases'].get('executor_attempts') for r in rows if r['new']['phases'].get('executor_attempts')}
    summary['failures_new'] = {r['case']: (r['new']['status'], r['new']['exception'], r['new']['reason'], r['new']['phases'].get('stop_phase')) for r in rows if r['new']['status'] != 'COMPLETED'}; summary['failures_baseline'] = {r['case']: (r['baseline']['status'], r['baseline']['exception'], r['baseline']['reason'], r['baseline']['phases'].get('stop_phase')) for r in rows if r['baseline']['status'] != 'COMPLETED'}
    summary['environments'] = {'baseline': {k: envB.get(k) for k in ('platform', 'python', 'route', 'seconds', 'source_unchanged')}, 'new': {k: envN.get(k) for k in ('platform', 'python', 'route', 'seconds', 'source_unchanged')}}
    json.dump(dict(summary=summary, rows=rows), open(outp, 'w'), indent=1, default=str)
    print(json.dumps({k: summary[k] for k in ('budget_s', 'cases', 'gate_passed', 'completed_and_gated', 'new_only', 'baseline_only', 'cross_arm_not_mutually_contained', 'cross_arm_inconsistent', 'coordinates_mutually_contained')}, default=str)); print('paired:', json.dumps({k: summary['paired_complete_tasks'][k] for k in ('n', 'median_wall_ratio_new_over_baseline', 'new_faster', 'baseline_faster')}), 'support-route pairs:', json.dumps(summary['paired_support_route_tasks']['per_case']))
    if failures: print('GATE FAILURES (%d):' % len(failures)); [print('  ', f) for f in failures[:60]]
    return 0 if not failures else 1
if __name__ == '__main__':
    if len(sys.argv) != 6: raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:6]))
