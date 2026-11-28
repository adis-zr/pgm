"""Analysis of DENSE_GENERIC_PAC_INTEGRATION_1 results (brief section 10): per-task table, separate verdicts, dense subsets, failure causes, checkpoint coverage, cost breakdown, stream risk ledger.
usage: dgp_analyze.py  -- reads RD/main/RESULTS_main_primary.json (+ confirmations, long, preservation when present), writes RD/ANALYSIS.json and RD/RESULTS.md"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, glob, math, hashlib, time
from fractions import Fraction as F
RD = str(_runs_root() / 'mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1')
ARMS = ['BASE', 'DET', 'UPAC', 'FULL']; EPS = 0.005
CHECK_T = [1, 2, 5, 10, 19]

def load(path):
    try: return json.load(open(path))
    except Exception: return None

def rows_by(results):
    out = {}
    for r in results: out.setdefault(r['task'], {})[r['arm']] = r
    return out

def enclosure_radii(r, arm):
    """per-coordinate final radius from the result file: published rows and (UPAC / FULL) the planner's valid enclosures; an unpublished, unresolved coordinate counts 0.5 ([0, 1])"""
    p = os.path.join(RD, r['_dir'], 'result.json'); d = load(p)
    if d is None: return None
    if arm in ('UPAC', 'FULL') and d.get('enclosures'): return [float(F(e['hi']) - F(e['lo'])) / 2 for e in d['enclosures']]
    K = d.get('K') or 0; rad = []
    for a in d.get('answers') or []:
        if a.get('guarantee') == 'NOT_PUBLISHED': rad.append(0.5)
        else: rad.append(float(F(a['hi']) - F(a['lo'])) / 2)
    return rad if rad else [0.5] * K

def certificate_widths(r, arm):
    """the RECORDED final certificate read-out of the unpublished coordinates (anytime-valid confidence sets at the last check: max and median remaining width), for the paired accuracy comparison;
    BASE: mechanism.max/median_remaining_width; UPAC / FULL: the primary stream's last trace row. None when no certificate exists (no draws); 2.0 = an empty / unresolved set"""
    p = os.path.join(RD, r['_dir'], 'result.json'); d = load(p)
    if d is None: return None
    if arm == 'BASE':
        m = d.get('mechanism') or {}
        if m.get('route') != 'pac' or not m.get('draws'): return None
        return dict(max=m.get('max_remaining_width'), median=m.get('median_remaining_width'), remaining=m.get('remaining'), draws=m.get('draws'), stream='BASE pac')
    st = [x for x in (d.get('streams') or []) if x.get('trace')]
    if not st: return None
    best = None
    for x in st:
        t = x['trace'][-1]; cand = dict(max=t['max_remaining_width'], median=t['median_remaining_width'], remaining=t['remaining'], draws=x['draws'], stream=x['label'], empty_sets=t.get('empty_sets'))
        if best is None or (cand['max'] or 2) < (best['max'] or 2): best = cand
    return best

def checkpoint_coverage(r, arm):
    """coverage (count of coordinates with radius <= eps) at the recorded checkpoints nearest 1, 2, 5, 10, 19 s; from the planner trace (UPAC / FULL) or the BASE certificate trace"""
    p = os.path.join(RD, r['_dir'], 'result.json'); d = load(p)
    if d is None: return None
    pts = []
    if arm in ('UPAC', 'FULL'): pts = [(c['t_s'], c['covered']) for c in d.get('checkpoints') or []]
    elif arm == 'BASE':
        K = d.get('K') or 0
        for t in d.get('trace') or []: pts.append((t['t'], t['published'] + (K - (d['mechanism'].get('Kq') or K))))
    if not pts: return {str(t): None for t in CHECK_T}
    out = {}
    for t in CHECK_T:
        prior = [c for tt, c in pts if tt <= t]; out[str(t)] = (prior[-1] if prior else 0)
    fin = d.get('published') if d.get('outcome') in ('COMPLETE', 'EXACT') else None
    if fin is not None and d.get('wall_s', 99) <= 19.5:
        for t in CHECK_T:
            if d['wall_s'] <= t: out[str(t)] = fin
    return out

def cause(r, arm):
    """evidence-based failure cause of a non-complete cell"""
    p = os.path.join(RD, r['_dir'], 'result.json'); d = load(p)
    if d is None: return 'no result file (%s)' % r.get('receipt_outcome')
    if r.get('complete'): return None
    m = d.get('mechanism') or {}
    if arm == 'BASE':
        if d.get('outcome') in ('MEMORY_POLICY_REFUSED',): return 'construction/admission (memory policy)'
        if d.get('outcome') == 'NUMERIC_RANGE_REFUSED': return 'numerical floor/range'
        if m.get('route') == 'pac' and m.get('draws'):
            zf = m.get('zero_weight_fraction') or 0; xm = m.get('X_mean') or 0; ls = m.get('largest_share') or 0
            if (m.get('ESS') or 0) < 0.01 * m['draws'] and ls > 0.05: return 'proposal concentration/rare events (largest share %.2f, ESS %.0f of %d)' % (ls, m['ESS'], m['draws'])
            if xm < 1e-3: return 'loose cap (mean X %.2e)' % xm
            return 'sampling budget: certificate widths %.4f max at the deadline (mean X %.3f, ESS %.0f)' % (m.get('max_remaining_width') or 0, xm, m.get('ESS') or 0)
        if d.get('outcome') == 'DEADLINE': return 'exact work / construction before any PAC batch (phase %s)' % (d.get('deadline_phase') or 'unknown')
        return 'not distinguished by this run (%s)' % d.get('outcome')
    if arm == 'DET':
        ref = m.get('refusal') or {}
        if ref.get('kind') == 'DEADLINE': return 'exact work: identity / quotient native solve exceeds the contract (forecast %s)' % (([a for a in d.get('actions', []) if a.get('action') == 'price'] or [{}])[0].get('estimate_s'))
        return 'scheduling/deterministic exhaustion (%s %s)' % (d.get('outcome'), ref.get('kind'))
    st = d.get('streams') or []
    if not st: return 'no stream created (%s; refusal %s)' % (d.get('outcome'), (m.get('refusal') or {}).get('kind'))
    prim = st[0]
    if prim['stage'] == 'CLOSED' and 'MEMORY_POLICY' in str(prim.get('closed')): return 'construction/admission (memory policy): %s' % prim['closed'][:80]
    if prim['stage'] == 'CLOSED' and 'RANGE' in str(prim.get('closed')): return 'numerical floor/range: %s' % prim['closed'][:80]
    if prim['stage'] == 'CLOSED' and 'DEADLINE' in str(prim.get('closed')): return 'exact work / preparation (%s)' % prim['closed'][:80]
    if prim.get('draws'):
        xm = prim.get('X_mean') or 0; ess = prim.get('ESS_DIAGNOSTIC') or 0; ls = prim.get('largest_share') or 0
        if ess < 0.01 * prim['draws'] and ls > 0.05: return 'proposal concentration/rare events (largest share %.2f, ESS %.0f of %d)' % (ls, ess, prim['draws'])
        if xm < 1e-3: return 'loose cap (mean X %.2e; cap log2 %s)' % (xm, (prim.get('mechanism') or {}).get('cap_log2_total'))
        return 'sampling budget: max width %.4f at the deadline (mean X %.3f, ESS %.0f, %d draws, first batch at %s s)' % (prim.get('max_remaining_width') or 0, xm, ess, prim['draws'], (d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s'))
    return 'not distinguished by this run (%s)' % d.get('outcome')

def main(sub='main', merge_from=None, out_name='ANALYSIS.json'):
    """sub = the directory with the UPAC / FULL (and BASE / DET) cells; merge_from = a directory whose BASE / DET cells are used when `sub` lacks them (the frozen primary: BASE / DET code unchanged)"""
    res = load(os.path.join(RD, sub, 'RESULTS_main_primary.json')); assert res, 'no main results'
    for r in res['results']: r['_dir'] = '%s/%02d__%s__%s__p' % (sub, r['task_index'], r['task'], r['arm'])
    if merge_from:
        have = {(r['task'], r['arm']) for r in res['results']}; base = load(os.path.join(RD, merge_from, 'RESULTS_main_primary.json'))
        for r in base['results']:
            if (r['task'], r['arm']) not in have: r['_dir'] = '%s/%02d__%s__%s__p' % (merge_from, r['task_index'], r['task'], r['arm']); r['_merged_from'] = merge_from; res['results'].append(r)
    by = rows_by(res['results']); man = load(os.path.join(RD, 'MAIN_MANIFEST.json')); tasks = [t['name'] for t in man['tasks']]; meta = {t['name']: t for t in man['tasks']}
    table = []; comp = {a: 0 for a in ARMS}; dense = {a: 0 for a in ARMS}; sparse = {a: 0 for a in ARMS}; ext = {a: 0 for a in ARMS}
    for t in tasks:
        row = dict(task=t, panel=meta[t].get('panel'), topology=meta[t].get('topology') or meta[t].get('family'), K=meta[t].get('K'))
        for a in ARMS:
            r = by.get(t, {}).get(a)
            if r is None: row[a] = None; continue
            rad = enclosure_radii(r, a) or []; worst = max(rad) if rad else None; med = (sorted(rad)[len(rad) // 2] if rad else None); p90 = (sorted(rad)[min(len(rad) - 1, int(0.9 * len(rad)))] if rad else None); cov = sum(1 for x in rad if x <= EPS)
            row[a] = dict(complete=r['complete'], outcome=r.get('outcome'), published=r.get('published'), receipt_wall_s=r.get('receipt_wall_s'), receipt_outcome=r.get('receipt_outcome'), worst_radius=worst, median_radius=med, p90_radius=p90, covered=cov, checkpoints=checkpoint_coverage(r, a), cause=cause(r, a), peak_MiB=r.get('peak_MiB'), termination=r.get('termination'), route=r.get('route'))
            if a in ('UPAC', 'FULL'):
                u = r.get('upac') or {}; row[a].update(streams=[dict(label=s['label'], stage=s['stage'], draws=s['draws'], published=s['published'], K=s.get('K'), X_mean=s.get('X_mean'), zero_frac=s.get('zero_weight_fraction'), ESS=s.get('ESS_DIAGNOSTIC'), largest_share=s.get('largest_share'), max_remaining_width=s.get('max_remaining_width'), cap_log2=(s.get('mechanism') or {}).get('cap_log2_total'), kappa_log2=(s.get('mechanism') or {}).get('kappa_log2'), eps_num=(s.get('mechanism') or {}).get('eps_num'), delta_s=s.get('delta_s'), closed=s.get('closed'), t_prep=s.get('t_prep'), t_sample=s.get('t_sample'), t_cert=s.get('t_cert')) for s in u.get('streams') or []], cost=u.get('cost_breakdown'), E=u.get('E'), E_used=u.get('E_used'), conflicts=len(u.get('conflicts') or []), risk_ledger=u.get('risk_ledger'), decisions=(u.get('decisions') or [])[:14])
            if a == 'BASE': b = r.get('base') or {}; row[a].update(base=dict(draws=b.get('draws'), X_mean=b.get('X_mean'), ESS=b.get('ESS'), zero_frac=b.get('zero_weight_fraction'), largest_share=b.get('largest_share'), max_remaining_width=b.get('max_remaining_width'), mb_splits=b.get('mb_splits'), mb_cap=b.get('mb_cap'), phases=b.get('phases'), structural=b.get('structural')))
            if r['complete']:
                comp[a] += 1
                if row['panel'] == 'external': ext[a] += 1
                elif row['topology'] in ('er50', 'clique'): dense[a] += 1
                else: sparse[a] += 1
        table.append(row)
    # verdicts
    new_completion = [r['task'] for r in table if r.get('FULL') and r['FULL']['complete'] and r.get('BASE') and not r['BASE']['complete']]
    lost = [r['task'] for r in table if r.get('BASE') and r['BASE']['complete'] and r.get('FULL') and not r['FULL']['complete']]
    integ = [r['task'] for r in table if r.get('UPAC') and r['UPAC']['complete'] and r.get('BASE') and not r['BASE']['complete']]
    prop = [r['task'] for r in table if r.get('FULL') and r['FULL']['complete'] and r.get('UPAC') and not r['UPAC']['complete']]
    acc = []
    for r in table:
        b = r.get('BASE'); f = r.get('FULL'); u = r.get('UPAC')
        if b and f and not b['complete'] and not f['complete']:
            cw = {a: certificate_widths(by[r['task']][a], a) for a in ('BASE', 'UPAC', 'FULL') if by.get(r['task'], {}).get(a)}
            def rad(a): w = cw.get(a); return (None if not w or w.get('max') is None else min(0.5, w['max'] / 2))
            rb, ru, rf = rad('BASE'), rad('UPAC'), rad('FULL'); ratio = (rb / rf if (rb is not None and rf is not None and rf > 0) else None)
            acc.append(dict(task=r['task'], topology=r['topology'], BASE_worst=rb, UPAC_worst=ru, FULL_worst=rf, ratio_BASE_over_FULL=ratio, material_2x=bool(ratio is not None and ratio >= 2), BASE_median=(cw.get('BASE') or {}).get('median'), FULL_median=(cw.get('FULL') or {}).get('median'), UPAC_median=(cw.get('UPAC') or {}).get('median'), BASE_covered=b['covered'], FULL_covered=f['covered'], UPAC_covered=(u or {}).get('covered'), certificate_source={a: (w or {}).get('stream') for a, w in cw.items()}, note='radius = half the recorded max remaining certificate width at the last check (anytime-valid confidence sets of the unpublished coordinates); 0.5 = unresolved'))
    eff = []
    for r in table:
        b = r.get('BASE'); f = r.get('FULL'); u = r.get('UPAC'); d = r.get('DET')
        if b and f and b['complete'] and f['complete']: eff.append(dict(task=r['task'], BASE_s=b['receipt_wall_s'], UPAC_s=(u or {}).get('receipt_wall_s'), FULL_s=f['receipt_wall_s'], DET_s=(d or {}).get('receipt_wall_s'), ratio_FULL_over_BASE=f['receipt_wall_s'] / b['receipt_wall_s']))
    causes = {a: {} for a in ARMS}
    for r in table:
        for a in ARMS:
            if r.get(a) and r[a]['cause']: k = r[a]['cause'].split(' (')[0].split(':')[0]; causes[a][k] = causes[a].get(k, 0) + 1
    rs = [json.loads(l) for l in open(os.path.join(RD, 'DGP_LEDGER.jsonl'))]; rc = [x for x in rs if x.get('kind') == 'RECEIPT']
    charges = {s: round(sum(x['wall_s'] for x in rc if x['scope'] == s), 2) for s in sorted(set(x['scope'] for x in rc))}; charges['total'] = round(sum(x['wall_s'] for x in rc), 2); charges['n_receipts'] = len(rc); charges['non_completed_receipts'] = [dict(job=x['job'], outcome=x['outcome'], wall_s=round(x['wall_s'], 2)) for x in rc if x['outcome'] != 'COMPLETED']
    out = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), completions=comp, dense_completions=dense, sparse_completions=sparse, external_completions=ext, new_completion_FULL_not_BASE=new_completion, lost_BASE_not_FULL=lost, integration_UPAC_not_BASE=integ, proposal_FULL_not_UPAC=prop, accuracy_pairs=acc, efficiency_mutual=eff, failure_causes=causes, charges=charges, table=table)
    out['sources'] = dict(sub=sub, merge_from=merge_from); json.dump(out, open(os.path.join(RD, out_name), 'w'), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ('table', 'accuracy_pairs', 'efficiency_mutual')}, default=str))
    for r in table: print('%-24s %-8s' % (r['task'], str(r['topology'])), ' '.join('%s:%s/%s %5.2fs w%.4f' % (a, ('C' if r[a]['complete'] else 'x'), r[a]['published'], r[a]['receipt_wall_s'] or 0, r[a]['worst_radius'] or 0) if r.get(a) else a + ':-' for a in ARMS))

if __name__ == '__main__' and len(sys.argv) == 1: main()
if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'repaired': main(sub='main_v051', merge_from='main', out_name='ANALYSIS.json')


def report():
    """RESULTS.md from ANALYSIS.json + confirmations / long / preservation results when present"""
    A = load(os.path.join(RD, 'ANALYSIS.json')); man = load(os.path.join(RD, 'MAIN_MANIFEST.json')); fr = load(os.path.join(RD, 'EVALUATION_FREEZE.json')); L = []
    def P(s=''): L.append(s)
    P('# DENSE_GENERIC_PAC_INTEGRATION_1 -- results (brief sha256 f4637665...; freeze %s; code pgm %s)' % (fr['frozen_utc'], fr['code']['commit'][:9])); P()
    P('Main panel: %d tasks (24 fresh dense synthetic + %d external) x 4 arms (BASE accepted v2.13.2 / DET USR1-D / UPAC persistent PAC / FULL = UPAC + lifted proposal), 20 s contract (19.5 hard / 19.0 work), 3 GiB, eps 1/200, delta 1e-6, seed 1. Completion = all original coordinates delivered within eps and the contract with a positive-mass witness, derived from the final validated file and the supervisor receipt.' % (man['n_tasks'], man['n_tasks'] - 24)); P()
    P('## Completions'); P(); P('| arm | all | dense (er50 + clique) | sparse (reg6) | external |'); P('|---|---:|---:|---:|---:|')
    for a in ARMS: P('| %s | %d | %d | %d | %d |' % (a, A['completions'][a], A['dense_completions'][a], A['sparse_completions'][a], A['external_completions'][a]))
    P(); P('FULL completes and BASE does not: %s. BASE completes and FULL does not: %s. UPAC completes and BASE does not (integration): %s. FULL completes and UPAC does not (proposal): %s.' % (A['new_completion_FULL_not_BASE'] or 'none', A['lost_BASE_not_FULL'] or 'none', A['integration_UPAC_not_BASE'] or 'none', A['proposal_FULL_not_UPAC'] or 'none')); P()
    P('## Per-task table (C = complete; published / K; receipt seconds; worst final radius, 0.5 = unresolved)'); P(); P('| task | topology | K | BASE | DET | UPAC | FULL |'); P('|---|---|---:|---|---|---|---|')
    for r in A['table']:
        cells = []
        for a in ARMS:
            c = r.get(a)
            cells.append('-' if not c else '%s %s/%s %.2fs r%.4f' % ('C' if c['complete'] else 'x', c['published'], r['K'], c['receipt_wall_s'] or 0, c['worst_radius'] if c['worst_radius'] is not None else 0.5))
        P('| %s | %s | %s | %s |' % (r['task'], r['topology'], r['K'], ' | '.join(cells)))
    P(); P('## Accuracy progress on tasks neither BASE nor FULL completes (paired worst-coordinate radius; material = >= 2x, and it must repeat in both confirmation seeds)'); P()
    if A['accuracy_pairs']:
        P('Radius = half the recorded maximum remaining certificate width at the final check (anytime-valid confidence sets of the unpublished coordinates; 0.5 = unresolved / no certificate). Medians likewise.'); P()
        P('| task | topology | BASE worst | UPAC worst | FULL worst | BASE / FULL | material | BASE median | FULL median | covered BASE / UPAC / FULL |'); P('|---|---|---:|---:|---:|---:|---|---:|---:|---|')
        fm = lambda v: ('%.4f' % v) if isinstance(v, (int, float)) else '-'
        for x in A['accuracy_pairs']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s |' % (x['task'], x['topology'], fm(x['BASE_worst']), fm(x['UPAC_worst']), fm(x['FULL_worst']), ('%.2f' % x['ratio_BASE_over_FULL']) if x['ratio_BASE_over_FULL'] else '-', x['material_2x'], fm((x['BASE_median'] or 0) / 2 if x['BASE_median'] is not None else None), fm((x['FULL_median'] or 0) / 2 if x['FULL_median'] is not None else None), x['BASE_covered'], x['UPAC_covered'], x['FULL_covered']))
    else: P('none')
    P(); P('## Efficiency on mutual completions (receipt seconds)'); P()
    if A['efficiency_mutual']:
        P('| task | BASE | UPAC | FULL | DET | FULL / BASE |'); P('|---|---:|---:|---:|---:|---:|')
        for x in A['efficiency_mutual']: P('| %s | %.2f | %s | %.2f | %s | %.2f |' % (x['task'], x['BASE_s'], ('%.2f' % x['UPAC_s']) if x['UPAC_s'] else '-', x['FULL_s'], ('%.2f' % x['DET_s']) if x['DET_s'] else '-', x['ratio_FULL_over_BASE']))
        rs = [x['ratio_FULL_over_BASE'] for x in A['efficiency_mutual']]; P(); P('FULL / BASE ratio: median %.2f, min %.2f, max %.2f over %d mutual completions.' % (sorted(rs)[len(rs) // 2], min(rs), max(rs), len(rs)))
    P(); P('## Failure causes (evidence-based, per arm)'); P()
    for a in ARMS: P('- **%s**: %s' % (a, ', '.join('%s x%d' % (k, v) for k, v in sorted(A['failure_causes'][a].items(), key=lambda kv: -kv[1])) or 'no failures'))
    P(); P('## Checkpoint coverage (coordinates within eps at ~1 / 2 / 5 / 10 / 19 s; BASE from its 0.5 s certificate trace, UPAC / FULL from the planner checkpoints; a completed cell is full from its completion time)'); P()
    P('| task | arm | 1 s | 2 s | 5 s | 10 s | 19 s | K |'); P('|---|---|---:|---:|---:|---:|---:|---:|')
    for r in A['table']:
        for a in ('BASE', 'UPAC', 'FULL'):
            c = r.get(a)
            if c and c.get('checkpoints'): P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], a, *(c['checkpoints'].get(str(t), '-') for t in CHECK_T), r['K']))
    Af = load(os.path.join(RD, 'ANALYSIS_frozen_v05.json'))
    if Af:
        P(); P('## Frozen v0.5 primary vs the repaired v0.5.1 rerun (UPAC / FULL cells; BASE / DET are the unchanged frozen cells)'); P(); P('Frozen v0.5 completions: %s. Repaired v0.5.1: %s. Cells whose completion or outcome changed:' % (Af['completions'], A['completions'])); P()
        tf = {r['task']: r for r in Af['table']}
        for r in A['table']:
            for a in ('UPAC', 'FULL'):
                c = r.get(a); cf = (tf.get(r['task']) or {}).get(a)
                if c and cf and (c['complete'] != cf['complete'] or c['outcome'] != cf['outcome'] or (c['published'] != cf['published'])): P('- %s %s: v0.5 %s %s/%s -> v0.5.1 %s %s/%s' % (r['task'], a, cf['outcome'], cf['published'], r['K'], c['outcome'], c['published'], r['K']))
    for name, title in (('confirm', 'Confirmations (seeds 2 and 3, reversed order; selected by the frozen rule on the repaired primary)'), ('long', 'Long-budget panel (60 s; predetermined dense-random strong-coupling tasks)'), ('preservation_18', 'Preservation: 18 unified inputs at 4 s, FROZEN v0.5 (BASE, FULL)'), ('preservation_18_v051', 'Preservation: 18 unified inputs at 4 s, repaired v0.5.1 (FULL)'), ('preservation_13', 'Preservation: 12 exposed cases + G4 at 20 s, FROZEN v0.5 (BASE, FULL)'), ('preservation_13_v051', 'Preservation: 12 exposed cases + G4 at 20 s, repaired v0.5.1 (FULL)')):
        files = sorted(glob.glob(os.path.join(RD, name, 'RESULTS_*.json')))
        if not files: continue
        P(); P('## ' + title); P(); P('| task | arm | seed | complete | published / K | receipt s | outcome | worst radius |'); P('|---|---|---:|---|---|---:|---|---:|')
        for f in files:
            d = load(f)
            for r in d['results']:
                r['_dir'] = '%s/%02d__%s__%s__%s' % (name, r['task_index'], r['task'], r['arm'], ('c%d' % r['seed']) if r['confirm'] else ('p' if r['seed'] == 1 else 's%d' % r['seed'])); rad = enclosure_radii(r, r['arm']) or []
                P('| %s | %s | %s | %s | %s / %s | %.2f | %s | %s |' % (r['task'], r['arm'], r['seed'], 'C' if r['complete'] else 'x', r['published'], r['K'], r['receipt_wall_s'] or 0, r['outcome'], ('%.4f' % max(rad)) if rad else '-'))
    P(); P('## Charges (supervisor receipts, DGP_LEDGER.jsonl)'); P(); P('```'); P(json.dumps(A['charges'], indent=1)); P('```')
    open(os.path.join(RD, 'RESULTS.md'), 'w').write('\n'.join(L) + '\n'); print('RESULTS.md written', len(L), 'lines')


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'report': report()
