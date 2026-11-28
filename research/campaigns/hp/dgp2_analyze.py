"""DGP2 committed analyzer (PROTOCOL.md section 5 definitions; protocol rule 8): derives every count / table from the raw cells, oracle outputs and the ledger. Writes RESULTS.json (complete attempted matrix, completion sets,
original-coordinate accuracy, time / resource costs, per-sub counts, confirmation selection by the frozen rule), DIAGNOSTICS.json (per-oracle-input quantities, replay effects, per-large-input stream diagnostics,
explanation status per cohort with the distinguishing evidence), RUN_MANIFEST.json (planned vs actual cells with reasons), CHARGES.json, and REPORT.md (tables). usage: dgp2_analyze.py [select-confirm | report]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, glob, math, time, hashlib
from fractions import Fraction as F
import numpy as np
RD = str(_runs_root() / 'mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS'); DGP1 = str(_runs_root() / 'mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1')
ARMS = ['BASE', 'UPAC2', 'FULL2']; EPS = 0.005
def load(p):
    try: return json.load(open(p))
    except Exception: return None
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()

def cells_of(sub):
    out = []
    for p in sorted(glob.glob(os.path.join(RD, 'runs', sub, '*', 'cell.json'))):
        c = load(p)['cell']; c['_dir'] = os.path.dirname(p); c['_result'] = load(os.path.join(c['_dir'], 'result.json')); out.append(c)
    return out

def radii(c):
    """per original coordinate final radius from the result (UPAC2 / FULL2: planner enclosures; BASE: published rows; unresolved = 0.5)"""
    d = c['_result']
    if d is None: return None
    if c['arm'] != 'BASE' and d.get('enclosures'): return [float(F(e['hi']) - F(e['lo'])) / 2 for e in d['enclosures']]
    rad = [0.5 if a.get('guarantee') == 'NOT_PUBLISHED' else float(F(a['hi']) - F(a['lo'])) / 2 for a in d.get('answers') or []]; return rad or [0.5] * (d.get('K') or 0)

def cert_widths(c):
    d = c['_result']
    if d is None: return None
    if c['arm'] == 'BASE':
        m = d.get('mechanism') or {}
        return dict(max=m.get('max_remaining_width'), median=m.get('median_remaining_width'), draws=m.get('draws'), stream='BASE pac') if m.get('route') == 'pac' and m.get('draws') else None
    best = None
    for s in d.get('streams') or []:
        if not s.get('trace'): continue
        t = s['trace'][-1]; cand = dict(max=t['max_remaining_width'], median=t['median_remaining_width'], draws=s['draws'], stream=s['label'], valid_endpoints=t.get('valid_endpoints'))
        if best is None or (cand['max'] or 2) < (best['max'] or 2): best = cand
    return best

def stream_rows(c):
    d = c['_result']; out = []
    for s in (d or {}).get('streams') or []:
        m = s.get('mechanism') or {}; stages = [(x['stage'], x.get('completed'), x.get('censored')) for x in (s.get('measurements') or []) if x.get('kind') in ('pac_stage', 'lifted_stage')]
        out.append(dict(kind=s['kind'], label=s['label'], stage=s['stage'], closed=s.get('closed'), construction=('BUILT' if s['stage'] in ('READY', 'COMPLETE') or s['draws'] else ('REFUSED: ' + str(s.get('closed'))[:80] if s.get('closed') else s['stage'])), stages=stages, draws=s['draws'], batches=s.get('batches'), published_parent_mask=s.get('published'), valid_endpoints=((s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None), witness=s.get('witness'), X_mean=s.get('X_mean'), log2_X_mean=(math.log2(s['X_mean']) if s.get('X_mean') else None), zero_frac=s.get('zero_weight_fraction'), ESS=s.get('ESS_DIAGNOSTIC'), largest_share=s.get('largest_share'), max_log2_X=s.get('max_log2_X_observed'), max_remaining_width=s.get('max_remaining_width'), t_prep=s.get('t_prep'), t_sample=s.get('t_sample'), t_cert=s.get('t_cert'), eps_num=m.get('eps_num'), rho_X=m.get('rho_X'), kappa=m.get('kappa_compact'), cap_units=m.get('cap_units'), cap_log2_total=m.get('cap_log2_total'), terminal=m.get('terminal'), delta_s=s.get('delta_s'), scale_to_original=s.get('scale_to_original'), Z_original=s.get('Z_original'), retained_bytes=s.get('retained_bytes')))
    return out

def cell_row(c):
    rad = radii(c) or []; cw = cert_widths(c); d = c['_result'] or {}; m = d.get('mechanism') or {}
    return dict(task=c['task'], arm=c['arm'], seed=c['seed'], confirm=c['confirm'], contract=c['contract'], complete=bool(c.get('complete')), outcome=c.get('outcome'), published=c.get('published'), K=c.get('K'), receipt_wall_s=c.get('receipt_wall_s'), receipt_outcome=c.get('receipt_outcome'), peak_MiB=c.get('peak_MiB'), termination=c.get('termination'), route=c.get('route'), identity_ok=c.get('identity_ok'), code_commit=c.get('code_commit'),
                worst_radius=(max(rad) if rad else None), median_radius=(float(np.median(rad)) if rad else None), p90_radius=(float(np.percentile(rad, 90)) if rad else None), covered_at_eps=sum(1 for x in rad if x <= EPS), certificate=cw, streams=stream_rows(c), cost=d.get('cost_breakdown') if c['arm'] != 'BASE' else {k: v for k, v in (d.get('phases_s') or {}).items()}, time_to_first_batch=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s') if c['arm'] != 'BASE' else None), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), conflicts=len(d.get('conflicts') or []), refusal=m.get('refusal') or d.get('refusal'), defect=m.get('defect'), lift_only=m.get('lift_only_candidates'), decisions=[x.get('chosen') for x in d.get('decisions', [])][:16], checkpoints=d.get('checkpoints') or (d.get('trace') if c['arm'] == 'BASE' else None), dir=os.path.relpath(c['_dir'], RD))

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c['seed'], c['confirm']), {})[c['arm']] = cell_row(c)
    return by, cs

def sel_hash(name): return hashlib.sha256(name.encode()).hexdigest()

def analyze():
    man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); fr = load(os.path.join(RD, 'FREEZE.json')); res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code']['commit'], freeze_sha256=sha(os.path.join(RD, 'FREEZE.json')), tables={}, completions_by_sub={}, verdict_inputs={})
    PANEL_OF = {'exposed_main': 'exposed_28', 'fresh': 'fresh_8', 'preservation_18': 'preservation_18', 'preservation_13': 'preservation_13', 'forced': 'exposed_28', 'confirm': 'exposed_28'}
    # the fresh panel REUSES the exposed task names (different bytes / tags): metadata is resolved per panel, exposed first for the shared maps
    meta_panel = {p: {t['name']: t for t in man['panels'][p]} for p in ('exposed_28', 'fresh_8', 'preservation_18', 'preservation_13', 'oracle_16')}
    meta = {}
    for p in ('fresh_8', 'oracle_16', 'preservation_13', 'preservation_18', 'exposed_28'): meta.update(meta_panel[p])          # exposed_28 last = wins on a shared name
    for sub in ('exposed_main', 'fresh', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        by, cs = table(sub)
        if not cs: continue
        mp = meta_panel[PANEL_OF[sub]]; order_names = [t['name'] for t in man['panels'][PANEL_OF[sub]]]
        res['tables'][sub] = [dict(task=k[0], seed=k[1], confirm=k[2], topology=mp.get(k[0], meta.get(k[0], {})).get('topology') or mp.get(k[0], meta.get(k[0], {})).get('family'), panel=mp.get(k[0], meta.get(k[0], {})).get('panel'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], order_names.index(kv[0][0]) if kv[0][0] in order_names else 999))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED')) for a in arms_here})
    # exposed main: sets, dense subset, gains / losses vs BASE, UPAC2 vs FULL2, DGP1 historical FULL comparator
    em = res['tables'].get('exposed_main', []); dgp1 = load(os.path.join(DGP1, 'ANALYSIS.json')); hist = {r['task']: r for r in (dgp1 or {}).get('table', [])}
    comp = {a: sorted(r['task'] for r in em if r['arms'].get(a, {}).get('complete')) for a in ARMS}; dense = lambda names: [t for t in names if meta.get(t, {}).get('topology') in ('er50', 'clique') or meta.get(t, {}).get('panel') == 'external']
    res['verdict_inputs']['exposed'] = dict(complete=comp, n_complete={a: len(comp[a]) for a in ARMS}, dense_complete={a: len(dense(comp[a])) for a in ARMS}, FULL2_not_BASE=sorted(set(comp['FULL2']) - set(comp['BASE'])), BASE_not_FULL2=sorted(set(comp['BASE']) - set(comp['FULL2'])), UPAC2_not_BASE=sorted(set(comp['UPAC2']) - set(comp['BASE'])), FULL2_not_UPAC2=sorted(set(comp['FULL2']) - set(comp['UPAC2'])), DGP1_FULL_historical_complete=sorted(t for t, r in hist.items() if (r.get('FULL') or {}).get('complete')), FULL2_vs_DGP1_FULL=dict(gained=sorted(set(comp['FULL2']) - {t for t, r in hist.items() if (r.get('FULL') or {}).get('complete')}), lost=sorted({t for t, r in hist.items() if (r.get('FULL') or {}).get('complete')} - set(comp['FULL2']))))
    # accuracy on mutual failures (BASE vs FULL2, recorded certificate widths), efficiency on mutual completions
    acc = []; eff = []
    for r in em:
        b = r['arms'].get('BASE'); f = r['arms'].get('FULL2'); u = r['arms'].get('UPAC2')
        if not b or not f: continue
        if not b['complete'] and not f['complete']:
            rb = (min(0.5, b['certificate']['max'] / 2) if b.get('certificate') and b['certificate'].get('max') is not None else None); rf = (min(0.5, f['certificate']['max'] / 2) if f.get('certificate') and f['certificate'].get('max') is not None else None); ru = (min(0.5, u['certificate']['max'] / 2) if u and u.get('certificate') and u['certificate'].get('max') is not None else None)
            acc.append(dict(task=r['task'], topology=r['topology'], BASE_worst=rb, UPAC2_worst=ru, FULL2_worst=rf, ratio_BASE_over_FULL2=(rb / rf if rb is not None and rf not in (None, 0) else None), material_2x=bool(rb is not None and rf not in (None, 0) and rb / rf >= 2), published_fraction_FULL2=((f['published'] or 0) / f['K']) if f.get('K') else None, published_fraction_BASE=((b['published'] or 0) / b['K']) if b.get('K') else None, enclosure_worst_FULL2=f['worst_radius'], covered_FULL2=f['covered_at_eps'], covered_BASE=b['covered_at_eps']))
        if b['complete'] and f['complete']: eff.append(dict(task=r['task'], BASE_s=b['receipt_wall_s'], UPAC2_s=(u or {}).get('receipt_wall_s'), FULL2_s=f['receipt_wall_s'], ratio_FULL2_over_BASE=f['receipt_wall_s'] / b['receipt_wall_s']))
    res['verdict_inputs']['accuracy_mutual_failures'] = acc; res['verdict_inputs']['efficiency_mutual'] = eff
    # preservation vs DGP1 (functional completion)
    for sub, ref in (('preservation_18', 'preservation_18_v051'), ('preservation_13', 'preservation_13_v051')):
        rows = res['tables'].get(sub, []); ref1 = load(glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json'))[0]) if glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json')) else None; refc = {r['task']: r['complete'] for r in (ref1 or {}).get('results', [])}
        base1 = load(glob.glob(os.path.join(DGP1, sub, 'RESULTS_*.json'))[0]) if glob.glob(os.path.join(DGP1, sub, 'RESULTS_*.json')) else None; basec = {r['task']: r['complete'] for r in (base1 or {}).get('results', []) if r['arm'] == 'BASE'}
        res['verdict_inputs'][sub] = dict(FULL2_complete=sum(1 for r in rows if r['arms'].get('FULL2', {}).get('complete')), n=len(rows), DGP1_FULL_v051_complete=sum(refc.values()), DGP1_BASE_complete=sum(basec.values()), regressions=sorted(r['task'] for r in rows if refc.get(r['task']) and not r['arms'].get('FULL2', {}).get('complete')), gains_over_DGP1_FULL=sorted(r['task'] for r in rows if not refc.get(r['task']) and r['arms'].get('FULL2', {}).get('complete')))
    # forced-stream vs FULL2: reachability
    fo = res['tables'].get('forced', []); reach = []
    for r in fo:
        full = next((x for x in em if x['task'] == r['task']), {}).get('arms', {}).get('FULL2', {})
        for arm, kind in (('FORCED_ORIG', 'original'), ('FORCED_LIFT', 'lifted')):
            a = r['arms'].get(arm)
            if not a: continue
            s = next((x for x in a['streams'] if x['kind'] == kind or (kind == 'original' and x['kind'] == 'exact_parent')), None); fs = next((x for x in full.get('streams', []) if x['kind'] == kind or (kind == 'original' and x['kind'] == 'exact_parent')), None)
            reach.append(dict(task=r['task'], stream=kind, forced=dict(construction=(s or {}).get('construction'), draws=(s or {}).get('draws'), valid_endpoints=(s or {}).get('valid_endpoints'), max_remaining_width=(s or {}).get('max_remaining_width'), log2_X_mean=(s or {}).get('log2_X_mean'), ESS=(s or {}).get('ESS'), t_prep=(s or {}).get('t_prep'), t_sample=(s or {}).get('t_sample'), covered=a['covered_at_eps'], worst_radius=a['worst_radius'], outcome=a['outcome']), in_FULL2=dict(offered=fs is not None, construction=(fs or {}).get('construction'), draws=(fs or {}).get('draws'), valid_endpoints=(fs or {}).get('valid_endpoints'), max_remaining_width=(fs or {}).get('max_remaining_width'), t_prep=(fs or {}).get('t_prep'), t_sample=(fs or {}).get('t_sample'), time_to_first_batch=full.get('time_to_first_batch'), decisions=full.get('decisions'))))
    res['verdict_inputs']['forced_vs_FULL2'] = reach
    # kappa constructor on the six n64/card4 (FULL2 cells): build / preparation / first batch / useful information
    k6 = []
    for r in em:
        if r['task'].startswith('dg_n64_c4'):
            f = r['arms'].get('FULL2', {}); L = next((s for s in f.get('streams', []) if s['kind'] == 'lifted'), None)
            k6.append(dict(task=r['task'], lift_only_candidates=f.get('lift_only'), stream=(L and dict(construction=L['construction'], stages=L['stages'], kappa=L.get('kappa'), draws=L['draws'], valid_endpoints=L.get('valid_endpoints'), max_remaining_width=L.get('max_remaining_width'), log2_X_mean=L.get('log2_X_mean'), closed=L.get('closed'))), decisions=f.get('decisions')))
    res['verdict_inputs']['kappa_n64c4'] = k6
    # ---- oracle diagnostics
    diag = dict(utc=res['utc'], oracle=[], explanations={}, units='original target W on the original (evidence-restricted) model; log2 everywhere; C = implemented cap in the stream unit converted to the same W_int unit as Z_int; caps and moments per PROTOCOL.md section 5')
    for t in man['panels']['oracle_16']:
        d = load(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')); row = dict(task=t['name'], topology=t['topology'], n=t['n'], card=t['card'], scale=t['scale'], fine_states=t['fine_states'])
        if d is None: row['status'] = 'NOT_RUN'; diag['oracle'].append(row); continue
        row.update(status=('CENSORED: ' + '; '.join(d['censored'])) if d.get('censored') else 'COMPLETE', wall_s=d.get('wall_s'), phases=d.get('phases'), Z_log2=(d.get('original') or {}).get('log2_Z'))
        for law in ('original_stream', 'lifted_stream'):
            q = d.get(law) or {}; row[law] = {k: q.get(k) for k in ('kind', 'stage', 'closed', 'note', 'identity_class_map', 'label', 'coarse_cards', 'n_sep_states', 'n_coarse_states', 'mb_splits', 'support_failure', 'omitted_target_mass_fraction', 'log2_R_star', 'log2_M2', 'log2_C_over_Z', 'log2_C_tight_over_Z', 'cap_ratio_impl_over_tight', 'max_X_analyzed', 'ordering_ok', 'constant_responses', 'K', 'eps_num', 'log2_ZU_over_Z', 'log2_B_over_ZU', 'log2_K_hi', 'K_inflation', 'log2_kappa_exact_oracle', 'numerical_cap_inflation_log2', 'B_cap_violations', 'M2_coarse', 'M2_min_fixed_r', 'M2_min_fixed_r_lower', 'R_star_min_fixed_r', 'log2_M2_min_fixed_r', 'log2_R_star_min_fixed_r', 'exact_upper_law', 'kappa_compact')}
            if q.get('V_j'): vj = np.array(q['V_j']); vp = np.array(q['var_p_g_j']); row[law].update(V_j_max=float(vj.max()), V_j_median=float(np.median(vj)), var_p_max=float(vp.max()), V_over_var_median=float(np.median(vj[vp > 0] / vp[vp > 0])) if (vp > 0).any() else None)
        for law in ('original_replay', 'lifted_replay'):
            r = d.get(law)
            if not r: continue
            eff = {}
            for k in 'ABCD':
                fin = [sd['checkpoints'][k][-1] for sd in r['seeds'].values() if sd.get('checkpoints') and sd['checkpoints'][k]]
                eff[k] = dict(n_seeds=len(fin), worst=[x['worst_radius'] for x in fin], median=[x['median_radius'] for x in fin], p90=[x['p90_radius'] for x in fin], covered=[x['covered'] for x in fin], K=(fin[0]['K'] if fin else None), contains_truth=[x['contains_truth'] for x in fin], max_abs_err=[x['max_abs_err'] for x in fin], ESS=[x['ESS_stable'] for x in fin], share=[x['largest_share'] for x in fin], draws=[x['draws'] for x in fin])
            def material(a, b):
                wa, wb = eff[a]['worst'], eff[b]['worst']; n2 = sum(1 for x, y in zip(wa, wb) if y > 0 and x / y >= 2); cov = any(cb == eff[b]['K'] and ca < eff[a]['K'] for ca, cb in zip(eff[a]['covered'], eff[b]['covered'])); return dict(improved_2x_seeds=n2, newly_all_covered=cov, material=(n2 >= 2 or cov), ratios=[(x / y if y > 0 else None) for x, y in zip(wa, wb)])
            row[law] = dict(final=eff, cap_effect_B_vs_A=material('A', 'B') if eff.get('A') and eff.get('B') else None, allowance_effect_C_vs_A=material('A', 'C') if eff.get('A') and eff.get('C') else None, both_D_vs_A=material('A', 'D') if eff.get('A') and eff.get('D') else None, cap_effect_zero_allowance_D_vs_C=material('C', 'D') if eff.get('C') and eff.get('D') else None, concentration_invariance=[sd.get('invariance_check') for sd in r['seeds'].values()], direct_stream=r.get('direct_stream_trace'), censored=[sd.get('censored') for sd in r['seeds'].values()])
        diag['oracle'].append(row)
    # explanation statuses (oracle cohort, controlled) -- computed by the frozen rules of PROTOCOL.md section 5 / brief section 7
    O = [r for r in diag['oracle'] if r.get('status', '').startswith('COMPLETE') or r.get('status', '').startswith('CENSORED')]
    def st(name, cases, rule):
        sup = [c for c in cases if c[1] is True]; con = [c for c in cases if c[1] is False]; unk = [c for c in cases if c[1] is None]
        status = 'unidentified' if not cases or len(unk) == len(cases) else ('supported' if sup and not con else ('contradicted' if con and not sup else 'mixed')); diag['explanations'][name] = dict(status=status, rule=rule, supported=[c[0] for c in sup], contradicted=[c[0] for c in con], unidentified=[c[0] for c in unk], detail={c[0]: c[2] for c in cases})
    cases = []
    for r in O:
        for law in ('original', 'lifted'):
            q = r.get(law + '_stream') or {}; rp = r.get(law + '_replay') or {}
            if q.get('log2_C_over_Z') is None or q.get('log2_C_tight_over_Z') is None: cases.append((r['task'] + '/' + law, None, 'cap or tight cap unknown')); continue
            slack = q['log2_C_over_Z'] - q['log2_C_tight_over_Z']; eff_ = (rp.get('cap_effect_B_vs_A') or {}); inv = rp.get('concentration_invariance')
            verdict = (True if (slack >= 1.0 and eff_.get('material')) else (False if slack < 1.0 or (eff_ and eff_.get('material') is False) else None)); cases.append((r['task'] + '/' + law, verdict, dict(log2_slack_impl_over_tight=slack, replay_B_vs_A=eff_, concentration_unchanged=inv)))
    st('H1_avoidable_fixed_q_cap_slack', cases, 'supported when log2(C / C_tight) >= 1 AND the paired B-vs-A replay effect is material (>= 2x worst radius in >= 2 of 3 seeds or newly all covered) with unchanged concentration; contradicted when the slack < 1 bit or the paired effect is not material')
    cases = []
    for r in O:
        q = r.get('lifted_stream') or {}
        if q.get('log2_M2') is None or (q.get('exact_upper_law') or {}).get('log2_M2') is None: cases.append((r['task'], None, 'lifted moments unknown')); continue
        dM2_upper = q['log2_M2'] - q['exact_upper_law']['log2_M2']; dR_upper = q['log2_R_star'] - q['exact_upper_law']['log2_R_star']; dM2_opt = q['log2_M2'] - q['log2_M2_min_fixed_r']; dR_opt = q['log2_R_star'] - q['log2_R_star_min_fixed_r']
        verdict = True if (dM2_opt >= 1.0 or dR_opt >= 1.0) else False; cases.append((r['task'], verdict, dict(log2_M2_minus_exact_upper=dM2_upper, log2_Rstar_minus_exact_upper=dR_upper, log2_M2_minus_optimum_coarse=dM2_opt, log2_Rstar_minus_optimum_coarse=dR_opt, note='cap construction vs normalized overlap: exact-upper removes the mini-bucket approximation; the optimum-coarse law removes the coarse overlap deficit with r fixed')))
    st('H2_coarse_sampler_or_cap_construction', cases, 'supported when the optimum-coarse (fixed r) or exact-upper law improves log2 M2 or log2 R* by >= 1 bit relative to the actual coarse law')
    cases = []
    for r in O:
        q = r.get('lifted_stream') or {}; o = r.get('original_stream') or {}
        if q.get('log2_M2_min_fixed_r') is None: cases.append((r['task'], None, 'fixed-r limits unknown')); continue
        poor = q['log2_M2_min_fixed_r'] >= max(1.0, (o.get('log2_M2') or 0)); cases.append((r['task'], True if poor else False, dict(log2_M2_min_fixed_r=q['log2_M2_min_fixed_r'], log2_R_star_min_fixed_r=q['log2_R_star_min_fixed_r'], original_log2_M2=o.get('log2_M2'), original_log2_R_star=o.get('log2_R_star'), note='the best coarse law with this decoder still exceeds the original stream\'s M2 (or 1 bit): the partition / conditional decoder, not the coarse sampler, bounds the lifted route')))
    st('H3_conditional_decoder_or_representation', cases, 'supported when even the fixed-r optimum M2_min stays >= max(2, the original stream\'s M2): the limit is the partition / decoder r, not the coarse law')
    cases = []
    for r in O:
        for law in ('original', 'lifted'):
            rp = r.get(law + '_replay') or {}; q = r.get(law + '_stream') or {}
            if not rp.get('allowance_effect_C_vs_A'): cases.append((r['task'] + '/' + law, None, 'no replay')); continue
            e = rp['allowance_effect_C_vs_A']; direct = (rp.get('direct_stream') or {}).get('log2_X_mean'); cases.append((r['task'] + '/' + law, bool(e.get('material')), dict(C_vs_A=e, D_vs_C=rp.get('cap_effect_zero_allowance_D_vs_C'), eps_num=q.get('eps_num'), direct_stream_log2_X_mean=direct, reference_ESS_A=(rp['final']['A']['ESS'] if rp.get('final') else None))))
    st('H4_numerical_allowance_or_arithmetic', cases, 'supported when zero allowance (C vs A, same cap, same draws) materially tightens the worst radius; the declared eps_num vs the oracle mean X and the direct-vs-reference weights are reported')
    cases = []
    for r in O:
        for law in ('original', 'lifted'):
            q = r.get(law + '_stream') or {}
            if q.get('V_j_max') is None: cases.append((r['task'] + '/' + law, None, 'no response moments')); continue
            glob_poor = (q.get('log2_M2') or 0) >= 2.0; resp_small = q['V_j_max'] <= 4 * max(q.get('var_p_max') or 0, 1e-300) * 1.0 and q['V_j_max'] < 1.0
            cases.append((r['task'] + '/' + law, True if (glob_poor and resp_small) else (False if q.get('log2_M2') is not None else None), dict(log2_M2=q.get('log2_M2'), V_j_max=q['V_j_max'], V_j_median=q.get('V_j_median'), var_p_max=q.get('var_p_max'), V_over_var_median=q.get('V_over_var_median'), constant_responses=q.get('constant_responses'))))
    st('H5_query_specific_certification', cases, 'supported when the global M2 is poor (>= 2 bits) but every requested response second moment V_j stays small (< 1 and <= 4 x the target-law response variance)')
    cases = []
    for x in reach:
        f = x['forced']; g = x['in_FULL2']; useful_forced = (f.get('covered') or 0) > 0 or (f.get('max_remaining_width') is not None and f['max_remaining_width'] < 1.0); useful_full = ((g.get('max_remaining_width') is not None and g['max_remaining_width'] < 1.0) or g.get('construction') == 'BUILT' and (g.get('draws') or 0) > 0 and False) if g.get('offered') else False
        useful_full = (g.get('max_remaining_width') is not None and g['max_remaining_width'] < 1.0) if g.get('offered') else False
        cases.append((x['task'] + '/' + x['stream'], True if (useful_forced and not useful_full) else (False if (useful_full or not useful_forced) else None), dict(forced_useful=useful_forced, FULL2_offered=g.get('offered'), FULL2_useful=useful_full, forced_draws=f.get('draws'), FULL2_draws=g.get('draws'), forced_t_prep=f.get('t_prep'), FULL2_time_to_first_batch=g.get('time_to_first_batch'), forced_construction=f.get('construction'), FULL2_construction=g.get('construction'))))
    st('H6_planner_reachability_or_scheduling', cases, 'supported when a forced stream reaches INFORMATIVE original-coordinate evidence (max remaining certificate width < 1, or a covered coordinate) that FULL2 did not reach on the same input; contradicted when FULL2 reached the same or the forced stream reached nothing informative either (then the obstruction is the mechanism, not the scheduling)')
    res['explanations'] = diag['explanations']; json.dump(diag, open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    # charges
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP2_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json'))
    ch = dict(ceiling_s=7200, allocation_s=bud['allocation_s'], by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), non_completed=[dict(job=r['job'], outcome=r['outcome'], wall_s=round(r['wall_s'], 3)) for r in rc if r['outcome'] != 'COMPLETED'], note='supervisor receipt wall seconds (process wall after cleanup); request elapsed time is in each result file (wall_s); implementation / setup labor is not charged and is disclosed in REPORT.md', unsupervised_disclosed='controls/UNSUPERVISED_DEV_LOG.md')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    # run manifest: planned vs actual
    planned = []
    def plan(sub, names, arms, seeds, confirm, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed=s, confirm=confirm, contract=contract))
    plan('exposed_main', [t['name'] for t in man['panels']['exposed_28']], ARMS, [1], False, 'main'); plan('fresh', [t['name'] for t in man['panels']['fresh_8']], ARMS, [1], False, 'main'); plan('preservation_18', [t['name'] for t in man['panels']['preservation_18']], ['FULL2'], [1], False, 'p4'); plan('preservation_13', [t['name'] for t in man['panels']['preservation_13']], ['FULL2'], [1], False, 'p20'); plan('forced', man['panels']['forced_8'], ['FORCED_ORIG', 'FORCED_LIFT'], [1], False, 'main')
    cm = load(os.path.join(RD, 'CONFIRM_MANIFEST.json'))
    if cm: plan('confirm', cm['selected'], ARMS, [2, 3], True, 'per task')
    actual = {}
    for sub in ('exposed_main', 'fresh', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c['seed'], c['confirm'])] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed'], p['confirm'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md: budget / blocked)'
    oracle_actual = {t['name']: (os.path.exists(os.path.join(RD, 'oracle', 'results', t['name'] + '.json'))) for t in man['panels']['oracle_16']}
    json.dump(dict(utc=res['utc'], code_commit=fr['code']['commit'], planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), oracle=oracle_actual, superseding_links='none (no validity amendment in this round)' if not os.path.exists(os.path.join(RD, 'FREEZE_AMENDMENT_1.json')) else 'see FREEZE_AMENDMENT_1.json', historical_comparators=dict(DGP1_FULL='DENSE_GENERIC_PAC_INTEGRATION_1/main_v051 (labelled historical; not rerun)', DGP1_BASE_preservation='DENSE_GENERIC_PAC_INTEGRATION_1/preservation_18, preservation_13')), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], exposed=res['verdict_inputs'].get('exposed', {}).get('n_complete'), dense=res['verdict_inputs'].get('exposed', {}).get('dense_complete'), explanations={k: v['status'] for k, v in diag['explanations'].items()}, charges=ch['total_s'])))
    return res, diag

def select_confirm():
    res = load(os.path.join(RD, 'RESULTS.json')); man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); vi = res['verdict_inputs']; meta = {}
    for p in ('fresh_8', 'preservation_13', 'preservation_18', 'exposed_28'): meta.update({t['name']: t for t in man['panels'][p]})       # exposed_28 wins on a shared name: the anchors and the exposed-panel tiers bind the EXPOSED bytes
    tiers = []; tiers.append(('a_regression', sorted(set(vi.get('preservation_18', {}).get('regressions', []) + vi.get('preservation_13', {}).get('regressions', []) + vi['exposed']['BASE_not_FULL2'] + [t for t in vi['exposed']['DGP1_FULL_historical_complete'] if t not in vi['exposed']['complete']['FULL2']]), key=lambda t: sha(meta[t]['model']) if t in meta else t)))
    tiers.append(('b_new_completion', sorted(set(vi['exposed']['FULL2_not_BASE']) | set(vi['exposed']['FULL2_not_UPAC2']), key=lambda t: sha(meta[t]['model']))))
    tiers.append(('c_material_accuracy', sorted([x['task'] for x in vi['accuracy_mutual_failures'] if x['material_2x'] or (x['published_fraction_FULL2'] or 0) >= 0.25], key=lambda t: sha(meta[t]['model']))))
    fr = load(os.path.join(RD, 'FREEZE.json')); tiers.append(('d_anchors', fr['confirmation']['anchors']))
    chosen = []; affected = []
    for name, ts in tiers:
        for t in ts:
            if name != 'd_anchors': affected.append((name, t))
            if t not in chosen and len(chosen) < 6: chosen.append(t)
    cm = dict(rule='PROTOCOL.md section 6 / FREEZE.json confirmation', tiers={n: ts for n, ts in tiers}, affected_all=affected, selected=chosen, unconfirmed_affected=[t for n, t in affected if t not in chosen], tasks=[dict(meta[t], contract=('p4' if meta[t].get('panel') == 'unified_18' else 'main')) for t in chosen], arms=ARMS, seeds=[2, 3], order='reversed', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(cm, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in cm.items() if k != 'tasks'}))

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'select-confirm': select_confirm()
    elif len(sys.argv) > 1 and sys.argv[1] == 'report': pass
    else: analyze()


def report():
    """REPORT.md and the DIAGNOSTICS-derived tables; THEORY_RETURN.md is written by hand from DIAGNOSTICS.json / RESULTS.json (the analyzer supplies every number it cites)"""
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')); man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    P('# DGP2_REPAIR_AND_DIAGNOSIS -- REPORT (analyzer-derived; code pgm %s, tree %s; freeze sha256 %s)' % (fr['code']['commit'][:9], fr['code']['tree'][:9], R['freeze_sha256'][:12])); P()
    P('Question (PROTOCOL.md section 1): on dense generic cyclic models, is the obstruction primarily avoidable fixed-q cap slack (H1), coarse sampler / cap construction (H2), information lost by the conditional decoder / representation (H3), numerical allowance or arithmetic (H4), query-specific certification (H5), or planner reachability / scheduling (H6)? Every count below is derived from the raw cells and oracle outputs by `dgp2_analyze.py`; oracle and forced-stream results never enter completion counts.'); P()
    P('## 1. Completion matrix (production arms; completion = receipt COMPLETED, wall <= outer, published == K, outcome COMPLETE / EXACT, positive witness, hard deadline respected)'); P()
    for sub, title in (('exposed_main', 'Exposed main panel (28 DGP1 inputs, original bytes; 20 s)'), ('fresh', 'Fresh dense panel (8 new DENSE-GENERIC-PAC-EVAL-2 inputs; 20 s)'), ('preservation_18', 'Preservation: 18 unified inputs at 4 s (FULL2)'), ('preservation_13', 'Preservation: 12 exposed + G4 at 20 s (FULL2)'), ('confirm', 'Confirmations (seeds 2, 3; reversed order)')):
        rows = R['tables'].get(sub)
        if not rows: P('### %s: NOT RUN' % title); P(); continue
        cb = R['completions_by_sub'][sub]; P('### %s -- cells %d, complete %d; by arm: %s' % (title, cb['cells'], cb['complete'], ', '.join('%s %d / %d' % (a, v['complete'], v['cells']) for a, v in cb['by_arm'].items()))); P()
        arms = sorted({a for r in rows for a in r['arms']}); P('| task | topology | seed | ' + ' | '.join(arms) + ' |'); P('|---|---|---:|' + '---|' * len(arms))
        for r in rows: P('| %s | %s | %s | %s |' % (r['task'], r['topology'], r['seed'], ' | '.join(('%s %s/%s %.2fs r%s%s' % ('C' if c['complete'] else 'x', c['published'], c['K'], c['receipt_wall_s'] or 0, f4(c['worst_radius']), ('' if c.get('identity_ok') else ' ID!'))) if (c := r['arms'].get(a)) else '-' for a in arms)))
        P()
    vi = R['verdict_inputs']; ex = vi.get('exposed', {})
    P('## 2. Exposed-panel sets'); P(); P('- Complete: %s' % {a: ex['n_complete'][a] for a in ARMS}); P('- Dense (er50 + clique + external) complete: %s' % ex['dense_complete']); P('- FULL2 not BASE: %s; BASE not FULL2: %s; UPAC2 not BASE: %s; FULL2 not UPAC2: %s' % (ex['FULL2_not_BASE'] or 'none', ex['BASE_not_FULL2'] or 'none', ex['UPAC2_not_BASE'] or 'none', ex['FULL2_not_UPAC2'] or 'none')); P('- Historical DGP1 FULL (v0.5.1, labelled comparator, not rerun) complete: %d; FULL2 gained %s, lost %s relative to it.' % (len(ex['DGP1_FULL_historical_complete']), ex['FULL2_vs_DGP1_FULL']['gained'] or 'none', ex['FULL2_vs_DGP1_FULL']['lost'] or 'none')); P()
    for sub in ('preservation_18', 'preservation_13'):
        p = vi.get(sub)
        if p: P('- %s: FULL2 %d / %d (DGP1 FULL v0.5.1 %d; DGP1 BASE %d); regressions %s; gains over DGP1 FULL %s' % (sub, p['FULL2_complete'], p['n'], p['DGP1_FULL_v051_complete'], p['DGP1_BASE_complete'], p['regressions'] or 'none', p['gains_over_DGP1_FULL'] or 'none'))
    P(); P('## 3. Original-coordinate accuracy on mutual failures (recorded final certificate widths; radius = half the max remaining width; 0.5 = unresolved)'); P(); P('| task | topology | BASE worst | UPAC2 worst | FULL2 worst | BASE / FULL2 | material (>= 2x) | FULL2 published fraction | covered BASE / FULL2 |'); P('|---|---|---:|---:|---:|---:|---|---:|---|')
    for x in vi.get('accuracy_mutual_failures', []): P('| %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |' % (x['task'], x['topology'], f4(x['BASE_worst']), f4(x['UPAC2_worst']), f4(x['FULL2_worst']), f2(x['ratio_BASE_over_FULL2']), x['material_2x'], f2(x['published_fraction_FULL2']), x['covered_BASE'], x['covered_FULL2']))
    P(); P('## 4. Efficiency on mutual completions (receipt seconds)'); P(); P('| task | BASE | UPAC2 | FULL2 | FULL2 / BASE |'); P('|---|---:|---:|---:|---:|')
    for x in vi.get('efficiency_mutual', []): P('| %s | %.2f | %s | %.2f | %.2f |' % (x['task'], x['BASE_s'], f2(x['UPAC2_s']), x['FULL2_s'], x['ratio_FULL2_over_BASE']))
    if vi.get('efficiency_mutual'): rs = sorted(x['ratio_FULL2_over_BASE'] for x in vi['efficiency_mutual']); P(); P('FULL2 / BASE median %.2f (min %.2f, max %.2f) over %d mutual completions.' % (rs[len(rs) // 2], rs[0], rs[-1], len(rs)))
    P(); P('## 5. Compact-kappa constructor on the six exposed n64 / card4 inputs (FULL2): build / preparation / first batch / useful information (counted separately)'); P(); P('| task | lift-only candidate | lifted stream construction | stages | draws | valid endpoints | max remaining width | log2 mean X | closed |'); P('|---|---|---|---|---:|---:|---:|---:|---|')
    for k in vi.get('kappa_n64c4', []): s = k.get('stream') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (k['task'], ('built' if k.get('lift_only_candidates') else 'none'), s.get('construction', 'no stream'), s.get('stages'), s.get('draws'), s.get('valid_endpoints'), f4(s.get('max_remaining_width')), f2(s.get('log2_X_mean')), (s.get('closed') or '')[:60]))
    P(); P('## 6. Forced-stream diagnostic panel vs FULL2 (reachability; NOT completions)'); P(); P('| task | stream | forced: construction / draws / valid endpoints / max width / log2 mean X / t_prep | FULL2: offered / construction / draws / valid endpoints / max width / first batch s |'); P('|---|---|---|---|')
    for x in vi.get('forced_vs_FULL2', []): f = x['forced']; g = x['in_FULL2']; P('| %s | %s | %s / %s / %s / %s / %s / %s | %s / %s / %s / %s / %s / %s |' % (x['task'], x['stream'], (f.get('construction') or '')[:30], f.get('draws'), f.get('valid_endpoints'), f4(f.get('max_remaining_width')), f2(f.get('log2_X_mean')), f2(f.get('t_prep')), g.get('offered'), (g.get('construction') or '')[:30], g.get('draws'), g.get('valid_endpoints'), f4(g.get('max_remaining_width')), f2(g.get('time_to_first_batch'))))
    P(); P('## 7. Oracle panel (16 fresh small dense models, forced-PAC diagnostic profile; exact enumeration; log2 units; original target W, Z on the original model)'); P()
    P('| model | states | law | sep / coarse states | log2 C/Z | log2 C_tight/Z | log2 M2 | log2 R* | M2_min^(r) | R*_min^(r) | exact-upper M2 / R* | B/Z_U | Z_U/Z | K_hi | support fail | replay B vs A worst (A -> B, 3 seeds) | C vs A material |'); P('|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|---|')
    for r in D['oracle']:
        for law in ('original_stream', 'lifted_stream'):
            q = r.get(law) or {}; rp = r.get(law.replace('_stream', '_replay')) or {}; fin = rp.get('final') or {}; wa = fin.get('A', {}).get('worst', []); wb = fin.get('B', {}).get('worst', []); ca = rp.get('allowance_effect_C_vs_A') or {}
            if q.get('log2_C_over_Z') is None: P('| %s | %d | %s | - | - | - | - | - | - | - | - | - | - | - | - | - | - |' % (r['task'], r['fine_states'], law.split('_')[0] + (': ' + str(q.get('terminal') or q.get('closed') or q.get('note') or q.get('stage') or r.get('status') or 'not run'))[:60])); continue
            P('| %s | %d | %s%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], r['fine_states'], law.split('_')[0], (' (identity control)' if q.get('identity_class_map') else ''), (q.get('n_sep_states') or q.get('n_coarse_states')), f2(q['log2_C_over_Z']), f2(q.get('log2_C_tight_over_Z')), f2(q.get('log2_M2')), f2(q.get('log2_R_star')), f2(q.get('log2_M2_min_fixed_r')), f2(q.get('log2_R_star_min_fixed_r')), ('%s / %s' % (f2((q.get('exact_upper_law') or {}).get('log2_M2')), f2((q.get('exact_upper_law') or {}).get('log2_R_star')))) if q.get('exact_upper_law') else '-', f2(q.get('log2_B_over_ZU')), f2(q.get('log2_ZU_over_Z')), f2(q.get('log2_K_hi')), q.get('support_failure'), ' / '.join('%.3f->%.3f' % (a, b) for a, b in zip(wa, wb)) if wa else '-', ca.get('material', '-')))
    P(); P('## 8. Explanation statuses (oracle cohort = controlled evidence; large cohort = exposed benchmark evidence)'); P()
    for k, v in D['explanations'].items(): P('- **%s**: %s (supported %d, contradicted %d, unidentified %d of %d). Rule: %s' % (k, v['status'].upper(), len(v['supported']), len(v['contradicted']), len(v['unidentified']), len(v['supported']) + len(v['contradicted']) + len(v['unidentified']), v['rule']))
    P(); P('## 9. Charges (supervisor receipts; ceiling 7,200 s)'); P(); P('```'); P(json.dumps({k: v for k, v in R['charges'].items() if k != 'non_completed'}, indent=1)); P('non-completed receipts: %s' % R['charges']['non_completed']); P('```'); P()
    P('## 10. Disclosures'); P(); P('- The DGP1 independent review file and evidence zip named by the brief were not present on this machine; the brief\'s five-finding table was the repair specification (PROTOCOL.md section 8).'); P('- Unsupervised work: controls/UNSUPERVISED_DEV_LOG.md (import / syntax checks and one 0.3 s arithmetic smoke; everything else charged).'); P('- The DGP1 erratum (PROTOCOL.md section 9): BASE preservation 13 / 18; 358 receipts (354 completed, 4 nonzero exits); 3,877.071256 s; the "B / Z 2^60-2^131" range and "all slack is the upper envelope" are WITHDRAWN (the quantity was an absolute cap exponent); the six n64 / card4 zero-draw lifted refusals were construction failures; the 60 s statements apply to the four strong ER tasks run.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md', len(L), 'lines')


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'report': report()
