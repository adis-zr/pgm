"""DGP3 committed analyzer (PROTOCOL.md sections 5-7; protocol rule 8): derives every count / table from the raw cells, oracle outputs and the ledger. Writes RESULTS.json (complete attempted matrix, completion sets vs BASE /
UPAC3 and vs the historical DGP2 FULL2, original-coordinate accuracy, costs, per-sub counts, confirmation selection by the frozen rule), DIAGNOSTICS.json (per-oracle-model quantities per envelope level G1 / G2 / G3,
counterfactual laws, block decoder, paired arithmetic, replay effects; per-large-input grouped-envelope stream diagnostics; hypothesis statuses G1-G5 by the frozen rules), RUN_MANIFEST.json, CHARGES.json, REPORT.md.
usage: dgp3_analyze.py [select-confirm | report]"""
import sys, os, json, glob, math, time, hashlib
from fractions import Fraction as F
import numpy as np
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP3_GROUPED_ENVELOPE'; DGP1 = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'; DGP2 = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS'
ARMS = ['BASE', 'UPAC3', 'FULL3']; FORCED_ARMS = ['FORCED_ORIG', 'FORCED_LIFT_G1', 'FORCED_LIFT_G2']; EPS = 0.005; LEVELS = ('G1', 'G2', 'G3'); NEAR_THRESHOLD = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half']
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
        m = s.get('mechanism') or {}; stages = [(x['stage'], x.get('completed'), x.get('censored'), round(x.get('seconds') or 0, 3)) for x in (s.get('measurements') or []) if x.get('kind') in ('pac_stage', 'lifted_stage')]
        out.append(dict(kind=s['kind'], label=s['label'], stage=s['stage'], closed=s.get('closed'), construction=('BUILT' if s['stage'] in ('READY', 'COMPLETE') or s['draws'] else ('REFUSED: ' + str(s.get('closed'))[:80] if s.get('closed') else s['stage'])), stages=stages, draws=s['draws'], batches=s.get('batches'), published_parent_mask=s.get('published'), valid_endpoints=((s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None), witness=s.get('witness'), X_mean=s.get('X_mean'), log2_X_mean=(math.log2(s['X_mean']) if s.get('X_mean') else None), zero_frac=s.get('zero_weight_fraction'), ESS=s.get('ESS_DIAGNOSTIC'), largest_share=s.get('largest_share'), max_log2_X=s.get('max_log2_X_observed'), max_remaining_width=s.get('max_remaining_width'), t_prep=s.get('t_prep'), t_sample=s.get('t_sample'), t_cert=s.get('t_cert'), eps_num=m.get('eps_num'), rho_X=m.get('rho_X'), kappa=m.get('kappa_compact'), cap_units=m.get('cap_units'), grouped_envelope=m.get('grouped_envelope'), terminal=m.get('terminal'), delta_s=s.get('delta_s'), scale_to_original=s.get('scale_to_original'), Z_original=s.get('Z_original'), retained_bytes=s.get('retained_bytes')))
    return out

def cell_row(c):
    rad = radii(c) or []; cw = cert_widths(c); d = c['_result'] or {}; m = d.get('mechanism') or {}
    return dict(task=c['task'], arm=c['arm'], seed=c['seed'], confirm=c['confirm'], contract=c['contract'], complete=bool(c.get('complete')), outcome=c.get('outcome'), published=c.get('published'), K=c.get('K'), receipt_wall_s=c.get('receipt_wall_s'), receipt_outcome=c.get('receipt_outcome'), peak_MiB=c.get('peak_MiB'), termination=c.get('termination'), route=c.get('route'), identity_ok=c.get('identity_ok'), code_commit=c.get('code_commit'), hard_deadline_respected=c.get('hard_deadline_respected'),
                worst_radius=(max(rad) if rad else None), median_radius=(float(np.median(rad)) if rad else None), p90_radius=(float(np.percentile(rad, 90)) if rad else None), covered_at_eps=sum(1 for x in rad if x <= EPS), certificate=cw, streams=stream_rows(c), cost=d.get('cost_breakdown') if c['arm'] != 'BASE' else {k: v for k, v in (d.get('phases_s') or {}).items()}, time_to_first_batch=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s') if c['arm'] != 'BASE' else None), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), conflicts=len(d.get('conflicts') or []), refusal=m.get('refusal') or d.get('refusal'), defect=m.get('defect'), envelope=d.get('envelope'), lift_only=m.get('lift_only_candidates'), decisions=[x.get('chosen') for x in d.get('decisions', [])][:16], dir=os.path.relpath(c['_dir'], RD))

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c['seed'], c['confirm']), {})[c['arm']] = cell_row(c)
    return by, cs

def worst_of(cw): return (min(0.5, cw['max'] / 2) if cw and cw.get('max') is not None else None)

def final_by_seed(rep, treatment=None):
    """replay finals per seed: DGP2 format (checkpoints per treatment) or the simple format (one law)"""
    fin = []
    for sd in (rep or {}).get('seeds', {}).values():
        ch = sd.get('checkpoints')
        if not ch: continue
        ch = ch.get(treatment) if (treatment and isinstance(ch, dict)) else ch
        if ch: fin.append(ch[-1])
    return dict(n_seeds=len(fin), worst=[x['worst_radius'] for x in fin], median=[x['median_radius'] for x in fin], covered=[x['covered'] for x in fin], K=(fin[0]['K'] if fin else None), contains_truth=[x.get('contains_truth') for x in fin], draws=[x['draws'] for x in fin])

def material(a, b):
    """a -> b improvement: >= 2x worst radius in >= 2 seeds (index-paired seeds; different laws do not share draws) or newly all covered"""
    if not a or not b or not a['worst'] or not b['worst']: return None
    wa, wb = a['worst'], b['worst']; n2 = sum(1 for x, y in zip(wa, wb) if y > 0 and x / y >= 2); cov = any(cb == b['K'] and ca < a['K'] for ca, cb in zip(a['covered'], b['covered']))
    return dict(improved_2x_seeds=n2, newly_all_covered=cov, material=(n2 >= 2 or cov), ratios=[(x / y if y > 0 else None) for x, y in zip(wa, wb)], median_a=float(np.median(wa)), median_b=float(np.median(wb)))

def analyze():
    man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); fr = load(os.path.join(RD, 'FREEZE.json')); res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code']['commit'], freeze_sha256=sha(os.path.join(RD, 'FREEZE.json')), tables={}, completions_by_sub={}, verdict_inputs={})
    PANEL_OF = {'exposed_main': 'exposed_36', 'fresh': 'fresh_8', 'preservation_18': 'preservation_18', 'preservation_13': 'preservation_13', 'forced': 'exposed_28', 'confirm': 'exposed_36'}
    meta_panel = {p: {t['name']: t for t in man['panels'][p]} for p in ('exposed_36', 'exposed_28', 'fresh_8', 'preservation_18', 'preservation_13', 'oracle_16')}
    meta = {}
    for p in ('fresh_8', 'oracle_16', 'preservation_13', 'preservation_18', 'exposed_36'): meta.update(meta_panel[p])          # exposed last = wins on a shared name (the fresh EVAL-3 panel reuses DGP1 names with different bytes)
    for sub in ('exposed_main', 'fresh', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        by, cs = table(sub)
        if not cs: continue
        mp = meta_panel[PANEL_OF[sub]]; order_names = [t['name'] for t in man['panels'][PANEL_OF[sub]]]
        if sub == 'confirm': mp = dict(meta_panel['preservation_18'], **meta_panel['exposed_36']); order_names = [t['name'] for t in man['panels']['exposed_36']] + [t['name'] for t in man['panels']['preservation_18']]
        res['tables'][sub] = [dict(task=k[0], seed=k[1], confirm=k[2], topology=mp.get(k[0], meta.get(k[0], {})).get('topology') or mp.get(k[0], meta.get(k[0], {})).get('family'), panel=mp.get(k[0], meta.get(k[0], {})).get('panel'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], order_names.index(kv[0][0]) if kv[0][0] in order_names else 999))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- historical comparators: DGP2 FULL2 on the 28 exposed + the 8 DGP2 fresh (now exposed as <name>__eval2); DGP1 FULL v0.5.1 per task
    d2 = load(os.path.join(DGP2, 'RESULTS.json')) or {}; hist2 = {}
    for r in (d2.get('tables') or {}).get('exposed_main', []): hist2[r['task']] = r['arms'].get('FULL2', {})
    for r in (d2.get('tables') or {}).get('fresh', []): hist2[r['task'] + '__eval2'] = r['arms'].get('FULL2', {})
    dgp1 = load(os.path.join(DGP1, 'ANALYSIS.json')); hist1 = {r['task']: (r.get('FULL') or {}) for r in (dgp1 or {}).get('table', [])}
    em = res['tables'].get('exposed_main', []); comp = {a: sorted(r['task'] for r in em if r['arms'].get(a, {}).get('complete')) for a in ARMS}
    dense = lambda names: [t for t in names if meta.get(t, {}).get('topology') in ('er50', 'clique') or meta.get(t, {}).get('panel') == 'external']
    full2_complete = sorted(t for t, h in hist2.items() if h.get('complete') and t in {r['task'] for r in em})
    res['verdict_inputs']['exposed'] = dict(n_tasks=len(em), complete=comp, n_complete={a: len(comp[a]) for a in ARMS}, dense_complete={a: len(dense(comp[a])) for a in ARMS}, FULL3_not_BASE=sorted(set(comp['FULL3']) - set(comp['BASE'])), BASE_not_FULL3=sorted(set(comp['BASE']) - set(comp['FULL3'])), UPAC3_not_BASE=sorted(set(comp['UPAC3']) - set(comp['BASE'])), FULL3_not_UPAC3=sorted(set(comp['FULL3']) - set(comp['UPAC3'])), UPAC3_not_FULL3=sorted(set(comp['UPAC3']) - set(comp['FULL3'])),
                                           DGP2_FULL2_historical_complete=full2_complete, FULL3_vs_DGP2_FULL2=dict(gained=sorted(set(comp['FULL3']) - set(full2_complete)), lost=sorted(set(full2_complete) - set(comp['FULL3']))), new_completion_candidates=sorted(set(comp['FULL3']) - set(comp['BASE']) - set(comp['UPAC3']) - set(full2_complete)))
    # accuracy on mutual failures (BASE vs UPAC3 vs FULL3 vs historical FULL2 recorded widths) and efficiency on mutual completions
    acc = []; eff = []
    for r in em:
        b = r['arms'].get('BASE'); f = r['arms'].get('FULL3'); u = r['arms'].get('UPAC3'); h = hist2.get(r['task'], {})
        if not b or not f: continue
        if not b['complete'] and not f['complete']:
            rb, rf, ru, rh = worst_of(b.get('certificate')), worst_of(f.get('certificate')), worst_of((u or {}).get('certificate')), worst_of(h.get('certificate'))
            acc.append(dict(task=r['task'], topology=r['topology'], BASE_worst=rb, UPAC3_worst=ru, FULL3_worst=rf, FULL2_hist_worst=rh, ratio_BASE_over_FULL3=(rb / rf if rb is not None and rf not in (None, 0) else None), ratio_FULL2_over_FULL3=(rh / rf if rh is not None and rf not in (None, 0) else None), material_2x_vs_BASE=bool(rb is not None and rf not in (None, 0) and rb / rf >= 2), material_2x_vs_FULL2=bool(rh is not None and rf not in (None, 0) and rh / rf >= 2), published_fraction_FULL3=((f['published'] or 0) / f['K']) if f.get('K') else None, published_fraction_BASE=((b['published'] or 0) / b['K']) if b.get('K') else None, covered_BASE=b['covered_at_eps'], covered_FULL3=f['covered_at_eps'], FULL3_lifted=next(({k: s.get(k) for k in ('construction', 'draws', 'log2_X_mean', 'ESS', 'max_remaining_width', 'grouped_envelope', 'closed')} for s in f['streams'] if s['kind'] == 'lifted'), None)))
        if b['complete'] and f['complete']: eff.append(dict(task=r['task'], BASE_s=b['receipt_wall_s'], UPAC3_s=(u or {}).get('receipt_wall_s'), FULL3_s=f['receipt_wall_s'], FULL2_hist_s=h.get('receipt_wall_s'), ratio_FULL3_over_BASE=f['receipt_wall_s'] / b['receipt_wall_s']))
    res['verdict_inputs']['accuracy_mutual_failures'] = acc; res['verdict_inputs']['efficiency_mutual'] = eff
    # fresh (EVAL-3)
    fe = res['tables'].get('fresh', []); fcomp = {a: sorted(r['task'] for r in fe if r['arms'].get(a, {}).get('complete')) for a in ARMS}
    res['verdict_inputs']['fresh'] = dict(n_tasks=len(fe), complete=fcomp, n_complete={a: len(fcomp[a]) for a in ARMS}, FULL3_not_BASE=sorted(set(fcomp['FULL3']) - set(fcomp['BASE'])), BASE_not_FULL3=sorted(set(fcomp['BASE']) - set(fcomp['FULL3'])), FULL3_not_UPAC3=sorted(set(fcomp['FULL3']) - set(fcomp['UPAC3'])))
    # preservation vs DGP1 FULL v0.5.1 and DGP2 FULL2
    for sub, ref in (('preservation_18', 'preservation_18_v051'), ('preservation_13', 'preservation_13_v051')):
        rows = res['tables'].get(sub, []); ref1 = load(glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json'))[0]) if glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json')) else None; refc = {r['task']: r['complete'] for r in (ref1 or {}).get('results', [])}
        ref2 = {r['task']: r['arms'].get('FULL2', {}).get('complete') for r in (d2.get('tables') or {}).get(sub, [])}
        res['verdict_inputs'][sub] = dict(FULL3_complete=sum(1 for r in rows if r['arms'].get('FULL3', {}).get('complete')), n=len(rows), DGP1_FULL_v051_complete=sum(bool(v) for v in refc.values()), DGP2_FULL2_complete=sum(bool(v) for v in ref2.values()), regressions=sorted(r['task'] for r in rows if (refc.get(r['task']) or ref2.get(r['task'])) and not r['arms'].get('FULL3', {}).get('complete')), gains=sorted(r['task'] for r in rows if not refc.get(r['task']) and not ref2.get(r['task']) and r['arms'].get('FULL3', {}).get('complete')))
    # forced / standalone panel vs FULL3's own streams (reachability; equal 20 s contract)
    fo = res['tables'].get('forced', []); reach = []
    for r in fo:
        full = next((x for x in em if x['task'] == r['task']), {}).get('arms', {}).get('FULL3', {})
        for arm, kind in (('FORCED_ORIG', 'original'), ('FORCED_LIFT_G1', 'lifted'), ('FORCED_LIFT_G2', 'lifted')):
            a = r['arms'].get(arm)
            if not a: continue
            s = next((x for x in a['streams'] if x['kind'] == kind or (kind == 'original' and x['kind'] == 'exact_parent')), None); fs = next((x for x in full.get('streams', []) if x['kind'] == kind or (kind == 'original' and x['kind'] == 'exact_parent')), None)
            # a forced LIFTED request on a model whose FAST class map is the identity (every binary model) has no coarse representation to lift: the planner records REFUSED with no stream (lift_only candidate exact identity) -- NOT APPLICABLE, not a reachability failure
            not_applicable = (kind == 'lifted' and s is None and a.get('outcome') == 'REFUSED' and any((c.get('name') or '').startswith('approx_lift_only(identity)') and c.get('exact') for c in (a.get('lift_only') or [])))
            pick = lambda x: dict(construction=(x or {}).get('construction'), stages=(x or {}).get('stages'), draws=(x or {}).get('draws'), valid_endpoints=(x or {}).get('valid_endpoints'), max_remaining_width=(x or {}).get('max_remaining_width'), log2_X_mean=(x or {}).get('log2_X_mean'), ESS=(x or {}).get('ESS'), largest_share=(x or {}).get('largest_share'), t_prep=(x or {}).get('t_prep'), t_sample=(x or {}).get('t_sample'), grouped_envelope=(x or {}).get('grouped_envelope'), cap_units=(x or {}).get('cap_units'), closed=(x or {}).get('closed'))
            reach.append(dict(task=r['task'], arm=arm, stream=kind, near_threshold=(r['task'] in NEAR_THRESHOLD), not_applicable=('identity class map on a binary model: no coarse representation to lift (REFUSED in %.1f s)' % (a['receipt_wall_s'] or 0)) if not_applicable else None, forced=dict(pick(s), covered=a['covered_at_eps'], worst_radius=a['worst_radius'], outcome=a['outcome'], receipt_wall_s=a['receipt_wall_s']), in_FULL3=dict(pick(fs), offered=fs is not None, time_to_first_batch=full.get('time_to_first_batch'), decisions=full.get('decisions'), envelope=full.get('envelope'))))
    res['verdict_inputs']['forced_vs_FULL3'] = reach
    # grouped-envelope production diagnostics: FULL3's lifted stream on every exposed / fresh task (construction cost, cap, weights, information)
    ge = []
    for sub in ('exposed_main', 'fresh'):
        for r in res['tables'].get(sub, []):
            f = r['arms'].get('FULL3', {}); L = next((s for s in f.get('streams', []) if s['kind'] == 'lifted'), None)
            ge.append(dict(sub=sub, task=r['task'], topology=r['topology'], envelope=f.get('envelope'), stream=(L and dict(construction=L['construction'], stages=L['stages'], grouped_envelope=L.get('grouped_envelope'), cap_units=L.get('cap_units'), kappa=L.get('kappa'), draws=L['draws'], valid_endpoints=L.get('valid_endpoints'), max_remaining_width=L.get('max_remaining_width'), log2_X_mean=L.get('log2_X_mean'), ESS=L.get('ESS'), closed=L.get('closed'), t_prep=L.get('t_prep'))), decisions=f.get('decisions'), complete=f.get('complete'), E=f.get('E'), E_used=f.get('E_used')))
    res['verdict_inputs']['grouped_envelope_production'] = ge
    # ---- oracle diagnostics
    diag = dict(utc=res['utc'], oracle=[], explanations={}, units='original target W on the original (evidence-restricted) model; log2 everywhere; C = implemented cap in W_int units (2^(logU_capf + E_U)) converted to the same unit as Z; recorded bit values are log2 M2 = log2(1 + chi-square) and log2 R*; PROTOCOL.md section 5')
    for t in man['panels']['oracle_16']:
        d = load(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')); row = dict(task=t['name'], topology=t['topology'], n=t['n'], card=t['card'], scale=t['scale'], fine_states=t['fine_states'])
        if d is None: row['status'] = 'NOT_RUN'; diag['oracle'].append(row); continue
        row.update(status=('CENSORED: ' + '; '.join(d['censored'])) if d.get('censored') else 'COMPLETE', wall_s=d.get('wall_s'), phases=d.get('phases'), reused=d.get('reused'), continued_from=d.get('continued_from'), Z_log2=(d.get('original') or {}).get('log2_Z'), K=(d.get('original') or {}).get('K'))
        q = d.get('original_stream') or {}; row['original_stream'] = {k: q.get(k) for k in ('kind', 'stage', 'closed', 'note', 'n_sep_states', 'mb_splits', 'support_failure', 'log2_R_star', 'log2_M2', 'log2_C_over_Z', 'log2_C_tight_over_Z', 'max_X_analyzed', 'ordering_ok', 'K', 'eps_num')}
        row['paired_arithmetic'] = d.get('paired_arithmetic'); rp = d.get('original_replay')
        if rp: A = final_by_seed(rp, 'A'); B_ = final_by_seed(rp, 'B'); row['original_replay'] = dict(A=A, B=B_, cap_effect_B_vs_A=material(A, B_))
        lf = d.get('lifted') or {}; row['identity_class_map'] = lf.get('identity_class_map'); row['coarse_cards'] = lf.get('coarse_cards'); row['levels'] = {}; row['levels_production_cap'] = {}
        for slot in ('levels', 'levels_production_cap'):
            for lv, q in (lf.get(slot) or {}).items():
                e = {k: q.get(k) for k in ('prep_s', 'grouped', 'envelope_valid', 'dominance', 'zero_weight_states', 'log2_ZU_over_Z', 'log2_B_over_ZU', 'log2_K_hi', 'log2_C_over_Z', 'log2_C_tight_over_Z', 'cap_ratio_impl_over_tight', 'log2_M2', 'log2_R_star', 'max_X_analyzed', 'ordering_ok', 'support_failure', 'B_cap_violations', 'numerical_cap_inflation_log2', 'M2_coarse', 'log2_M2_min_fixed_r', 'log2_R_star_min_fixed_r', 'exact_upper_law', 'eps_num', 'mb_splits', 'mb_cap', 'cap_units', 'V_j_max', 'V_j_median', 'stage', 'closed')}
                if q.get('replay'): A = final_by_seed(q['replay'], 'A'); B_ = final_by_seed(q['replay'], 'B'); e['replay'] = dict(A=A, B=B_, cap_effect_B_vs_A=material(A, B_), censored=[sd.get('censored') for sd in q['replay']['seeds'].values()])
                row[slot][lv] = e
        cf = lf.get('counterfactual_laws_same_decoder') or {}; row['counterfactual_laws_same_decoder'] = {k: dict(log2_R_star=v.get('log2_R_star'), log2_M2=v.get('log2_M2'), replay=final_by_seed(v.get('replay'))) for k, v in cf.items()}
        bd = d.get('block_decoder') or {}; row['block_decoder'] = {k: bd.get(k) for k in ('blocks', 'factors_inside_blocks', 'n_factors', 'normalization_violations', 'log2_M2_min_fixed_rB', 'log2_R_star_min_fixed_rB')}
        if bd.get('cap_optimal_law'): row['block_decoder']['cap_optimal'] = dict(log2_R_star=bd['cap_optimal_law'].get('log2_R_star'), replay=final_by_seed(bd['cap_optimal_law'].get('replay')))
        row['production_cap_secondary'] = lf.get('production_cap_secondary')
        # derived contrasts
        g1 = row['levels'].get('G1') or {}; g2 = row['levels'].get('G2') or {}; g3 = row['levels'].get('G3') or {}
        row['contrasts'] = dict(C_G1_minus_G2_bits=((g1.get('log2_C_over_Z') - g2.get('log2_C_over_Z')) if g1.get('log2_C_over_Z') is not None and g2.get('log2_C_over_Z') is not None else None), C_G1_minus_G3_bits=((g1.get('log2_C_over_Z') - g3.get('log2_C_over_Z')) if g1.get('log2_C_over_Z') is not None and g3.get('log2_C_over_Z') is not None else None), ZU_G1_minus_G2_bits=((g1.get('log2_ZU_over_Z') - g2.get('log2_ZU_over_Z')) if g1.get('log2_ZU_over_Z') is not None and g2.get('log2_ZU_over_Z') is not None else None), M2_G1_minus_G2_bits=((g1.get('log2_M2') - g2.get('log2_M2')) if g1.get('log2_M2') is not None and g2.get('log2_M2') is not None else None), Rstar_G1_minus_G2_bits=((g1.get('log2_R_star') - g2.get('log2_R_star')) if g1.get('log2_R_star') is not None and g2.get('log2_R_star') is not None else None),
                                realized_G2_vs_G1_replay_A=material((g1.get('replay') or {}).get('A'), (g2.get('replay') or {}).get('A')), realized_G2_vs_G1_replay_B=material((g1.get('replay') or {}).get('B'), (g2.get('replay') or {}).get('B')),
                                G2_to_cap_optimal_gap_bits=((g2.get('log2_R_star') - g2.get('log2_R_star_min_fixed_r')) if g2.get('log2_R_star') is not None and g2.get('log2_R_star_min_fixed_r') is not None else None), G3_to_cap_optimal_gap_bits=((g3.get('log2_R_star') - g3.get('log2_R_star_min_fixed_r')) if g3.get('log2_R_star') is not None and g3.get('log2_R_star_min_fixed_r') is not None else None),
                                block_vs_product_cap_optimal_Rstar_bits=((row['counterfactual_laws_same_decoder'].get('cap_optimal_same_decoder', {}).get('log2_R_star') - row['block_decoder'].get('log2_R_star_min_fixed_rB')) if row['counterfactual_laws_same_decoder'].get('cap_optimal_same_decoder', {}).get('log2_R_star') is not None and row['block_decoder'].get('log2_R_star_min_fixed_rB') is not None else None),
                                block_vs_product_M2_min_bits=((g1.get('log2_M2_min_fixed_r') - row['block_decoder'].get('log2_M2_min_fixed_rB')) if g1.get('log2_M2_min_fixed_r') is not None and row['block_decoder'].get('log2_M2_min_fixed_rB') is not None else None),
                                block_cap_optimal_vs_product_cap_optimal_replay=material(row['counterfactual_laws_same_decoder'].get('cap_optimal_same_decoder', {}).get('replay'), (row['block_decoder'].get('cap_optimal') or {}).get('replay')))
        diag['oracle'].append(row)
    # ---- hypothesis statuses by the frozen rules (PROTOCOL.md section 7)
    O = [r for r in diag['oracle'] if r.get('status', '').startswith(('COMPLETE', 'CENSORED'))]
    # the frozen G1 / G2 / G4 panel (PROTOCOL section 7: 'the 6 strong card-4 oracle models' = the DGP2 definition: card-4 models whose ORIGINAL stream reaches READY under the forced profile; the two n6 ER models contract exactly there); the other card-4 models are reported as supplementary
    strong = [r for r in O if r['card'] == 4 and (r['levels'].get('G1') or {}).get('log2_C_over_Z') is not None and (r.get('original_stream') or {}).get('log2_C_over_Z') is not None]; diag['card4_ready_panel'] = [r['task'] for r in strong]
    diag['card4_supplementary'] = [r['task'] for r in O if r['card'] == 4 and (r['levels'].get('G1') or {}).get('log2_C_over_Z') is not None and r['task'] not in diag['card4_ready_panel']]
    def st(name, cases, rule, threshold=None, n_needed=None):
        sup = [c for c in cases if c[1] is True]; con = [c for c in cases if c[1] is False]; unk = [c for c in cases if c[1] is None]
        if n_needed is not None: status = 'unidentified' if not cases or len(unk) == len(cases) else ('supported' if len(sup) >= n_needed else 'contradicted')
        else: status = 'unidentified' if not cases or len(unk) == len(cases) else ('supported' if sup and not con else ('contradicted' if con and not sup else 'mixed'))
        diag['explanations'][name] = dict(status=status, rule=rule, n_needed=n_needed, supported=[c[0] for c in sup], contradicted=[c[0] for c in con], unidentified=[c[0] for c in unk], detail={c[0]: c[2] for c in cases})
    cases = [(r['task'], (r['contrasts']['C_G1_minus_G2_bits'] >= 1.0) if r['contrasts']['C_G1_minus_G2_bits'] is not None else None, dict(C_G1_minus_G2_bits=r['contrasts']['C_G1_minus_G2_bits'], C_G1_minus_G3_bits=r['contrasts']['C_G1_minus_G3_bits'], ZU_G1_minus_G2_bits=r['contrasts']['ZU_G1_minus_G2_bits'], G1=(r['levels'].get('G1') or {}).get('log2_C_over_Z'), G2=(r['levels'].get('G2') or {}).get('log2_C_over_Z'), G3=(r['levels'].get('G3') or {}).get('log2_C_over_Z'))) for r in strong]
    st('G1_grouped_envelope_tightens_checked_cap', cases, 'supported when log2 C^G2 / Z is >= 1 bit below log2 C^G1 / Z on >= 4 of the card-4 oracle models with a READY lifted stream (6 in DGP2)', n_needed=4)
    cases = [(r['task'], (r['contrasts']['realized_G2_vs_G1_replay_A'] or {}).get('material') if r['contrasts']['realized_G2_vs_G1_replay_A'] else None, dict(replay_A=r['contrasts']['realized_G2_vs_G1_replay_A'], replay_B=r['contrasts']['realized_G2_vs_G1_replay_B'], M2_G1_minus_G2_bits=r['contrasts']['M2_G1_minus_G2_bits'], Rstar_G1_minus_G2_bits=r['contrasts']['Rstar_G1_minus_G2_bits'])) for r in strong]
    st('G2_realized_G2_law_materially_better_certificate', cases, 'supported when the realized G2 lifted law\'s replay (treatment A: its own implemented cap) is MATERIAL vs the realized G1 law (>= 2x worst radius in >= 2 of 3 index-paired seeds, or newly all covered) on >= 2 of those models', n_needed=2)
    ex = res['verdict_inputs']['exposed']; acc_m = [x['task'] for x in acc if x['material_2x_vs_BASE'] or x['material_2x_vs_FULL2']]
    g3_cases = [(t, True, 'new FULL3 completion (not BASE, not UPAC3, not DGP2 FULL2)') for t in ex['new_completion_candidates']] + [(t, True, 'material production radius gain (>= 2x vs BASE or vs historical FULL2 on a mutual failure)') for t in acc_m]
    if not g3_cases and em: g3_cases = [('exposed_panel', False, dict(n_tasks=len(em), n_complete=ex['n_complete'], FULL3_not_BASE=ex['FULL3_not_BASE'], material_gains=acc_m, note='no new completion and no material radius gain'))]
    st('G3_research_outcome_new_completion_or_material_radius_gain', g3_cases, 'the research outcome: a FULL3 completion that BASE, UPAC3 and the historical FULL2 lack, or a >= 2x worst-radius gain on a mutual failure at equal total cost, CONFIRMED by the frozen rule (seeds 2, 3); oracle evidence alone is mechanism evidence')
    cases = [(r['task'], (r['contrasts']['block_cap_optimal_vs_product_cap_optimal_replay'] or {}).get('material') if r['contrasts']['block_cap_optimal_vs_product_cap_optimal_replay'] else None, dict(replay=r['contrasts']['block_cap_optimal_vs_product_cap_optimal_replay'], block_vs_product_cap_optimal_Rstar_bits=r['contrasts']['block_vs_product_cap_optimal_Rstar_bits'], block_vs_product_M2_min_bits=r['contrasts']['block_vs_product_M2_min_bits'], block=r['block_decoder'])) for r in strong]
    st('G4_block_decoder_adds_affordable_improvement', cases, 'supported when the block-decoder oracle\'s cap-optimal replay is MATERIAL vs the same-partition product-decoder cap-optimal replay (the best any coarse law / envelope can do with the decoder fixed) on >= 2 of those models', n_needed=2)
    cases = []
    for x in reach:
        if not x['near_threshold']: continue
        if x.get('not_applicable'): cases.append((x['task'] + '/' + x['arm'], None, dict(not_applicable=x['not_applicable']))); continue
        f = x['forced']; g = x['in_FULL3']; useful_forced = (f.get('covered') or 0) > 0 or (f.get('max_remaining_width') is not None and f['max_remaining_width'] < 1.0); useful_full = (g.get('max_remaining_width') is not None and g['max_remaining_width'] < 1.0) if g.get('offered') else False
        cases.append((x['task'] + '/' + x['arm'], True if (useful_forced and not useful_full) else (False if (useful_full or not useful_forced) else None), dict(forced_useful=useful_forced, FULL3_offered=g.get('offered'), FULL3_useful=useful_full, forced_draws=f.get('draws'), FULL3_draws=g.get('draws'), forced_max_width=f.get('max_remaining_width'), FULL3_max_width=g.get('max_remaining_width'), forced_t_prep=f.get('t_prep'), FULL3_time_to_first_batch=g.get('time_to_first_batch'))))
    st('G5_standalone_stream_informative_where_planner_was_not_near_threshold', cases, 'supported when a standalone (forced) stream reaches informative original-coordinate evidence (max remaining certificate width < 1 or a covered coordinate) on a near-threshold weak binary n64 task where FULL3\'s own stream did not')
    res['explanations'] = diag['explanations']; json.dump(diag, open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    # charges
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP3_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json'))
    ch = dict(ceiling_s=7200, allocation_s=bud['allocation_s'], by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), non_completed=[dict(job=r['job'], outcome=r['outcome'], wall_s=round(r['wall_s'], 3)) for r in rc if r['outcome'] != 'COMPLETED'], note='supervisor receipt wall seconds (process wall after cleanup); request elapsed time is in each result file (wall_s); implementation / setup labor is not charged and is disclosed in REPORT.md', unsupervised_disclosed='controls/UNSUPERVISED_DEV_LOG.md')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, confirm, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed=s, confirm=confirm, contract=contract))
    plan('exposed_main', [t['name'] for t in man['panels']['exposed_36']], ARMS, [1], False, 'main'); plan('fresh', [t['name'] for t in man['panels']['fresh_8']], ARMS, [1], False, 'main'); plan('preservation_18', [t['name'] for t in man['panels']['preservation_18']], ['FULL3'], [1], False, 'p4'); plan('preservation_13', [t['name'] for t in man['panels']['preservation_13']], ['FULL3'], [1], False, 'p20'); plan('forced', man['panels']['forced_10'], FORCED_ARMS, [1], False, 'main')
    cm = load(os.path.join(RD, 'CONFIRM_MANIFEST.json'))
    if cm: plan('confirm', cm['selected'], ARMS, [2, 3], True, 'per task')
    actual = {}
    for sub in ('exposed_main', 'fresh', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c['seed'], c['confirm'])] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed'], p['confirm'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md: budget / blocked)'
    oracle_actual = {t['name']: (os.path.exists(os.path.join(RD, 'oracle', 'results', t['name'] + '.json'))) for t in man['panels']['oracle_16']}
    json.dump(dict(utc=res['utc'], code_commit=fr['code']['commit'], planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), oracle=oracle_actual, superseding_links=('see ' + ', '.join(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')))) if glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')) else 'none (no amendment in this round)', historical_comparators=dict(DGP2_FULL2='DGP2_REPAIR_AND_DIAGNOSIS/runs/exposed_main, fresh, preservation_* (labelled historical; not rerun)', DGP1_FULL_v051='DENSE_GENERIC_PAC_INTEGRATION_1 (labelled historical)')), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], exposed=ex.get('n_complete'), dense=ex.get('dense_complete'), new=ex.get('new_completion_candidates'), fresh=res['verdict_inputs']['fresh'].get('n_complete'), explanations={k: v['status'] for k, v in diag['explanations'].items()}, charges=ch['total_s'])))
    return res, diag

def select_confirm():
    res = load(os.path.join(RD, 'RESULTS.json')); man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); vi = res['verdict_inputs']; meta = {}
    for p in ('fresh_8', 'preservation_13', 'preservation_18', 'exposed_36'): meta.update({t['name']: t for t in man['panels'][p]})
    ex = vi['exposed']; tiers = []
    tiers.append(('a_regression', sorted(set(vi.get('preservation_18', {}).get('regressions', []) + vi.get('preservation_13', {}).get('regressions', []) + ex['BASE_not_FULL3'] + ex['FULL3_vs_DGP2_FULL2']['lost']), key=lambda t: sha(meta[t]['model']) if t in meta else t)))
    tiers.append(('b_new_completion', sorted(set(ex['FULL3_not_BASE']) | set(ex['FULL3_not_UPAC3']) | set(vi['fresh']['FULL3_not_BASE']), key=lambda t: sha(meta[t]['model']) if t in meta else t)))
    tiers.append(('c_material_accuracy', sorted([x['task'] for x in vi['accuracy_mutual_failures'] if x['material_2x_vs_BASE'] or x['material_2x_vs_FULL2'] or (x['published_fraction_FULL3'] or 0) >= 0.25], key=lambda t: sha(meta[t]['model']) if t in meta else t)))
    fr = load(os.path.join(RD, 'FREEZE.json')); tiers.append(('d_anchors', fr['confirmation']['anchors']))
    chosen = []; affected = []
    for name, ts in tiers:
        for t in ts:
            if name != 'd_anchors': affected.append((name, t))
            if t not in chosen and len(chosen) < 6: chosen.append(t)
    cm = dict(rule='PROTOCOL.md section 6 / FREEZE.json confirmation', tiers={n: ts for n, ts in tiers}, affected_all=affected, selected=chosen, unconfirmed_affected=[t for n, t in affected if t not in chosen], tasks=[dict(meta[t], contract=('p4' if meta[t].get('panel') == 'unified_18' else 'main')) for t in chosen], arms=ARMS, seeds=[2, 3], order='reversed', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(cm, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in cm.items() if k != 'tasks'}))

def report():
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')); L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    def med(fin): return f4(float(np.median(fin['worst']))) if fin and fin.get('worst') else '-'
    P('# DGP3_GROUPED_ENVELOPE -- REPORT (analyzer-derived; code pgm %s, tree %s; freeze sha256 %s)' % (fr['code']['commit'][:9], fr['code']['tree'][:9], R['freeze_sha256'][:12])); P()
    P('Question (PROTOCOL.md section 1): with the two-class product decoder FIXED, does a tighter CHECKED upper envelope -- grouped products of adjacent factors maximized within coarse cells (lemma G) -- realize the oracle cap advantage at equal total cost, and does a block decoder add affordable improvement beyond it? Every count below is derived from the raw cells and oracle outputs by `dgp3_analyze.py`; oracle and forced-stream results never enter completion counts.'); P()
    P('## 1. Completion matrix (production arms; completion = receipt COMPLETED, wall <= outer, published == K, outcome COMPLETE / EXACT, positive witness, hard deadline respected)'); P()
    for sub, title in (('exposed_main', 'Exposed main panel (28 DGP1 inputs + 8 DGP2 fresh inputs `__eval2`, original bytes; 20 s)'), ('fresh', 'Fresh dense panel (8 new DENSE-GENERIC-PAC-EVAL-3 inputs; 20 s)'), ('preservation_18', 'Preservation: 18 unified inputs at 4 s (FULL3)'), ('preservation_13', 'Preservation: 12 exposed + G4 at 20 s (FULL3)'), ('confirm', 'Confirmations (seeds 2, 3; reversed order)')):
        rows = R['tables'].get(sub)
        if not rows: P('### %s: NOT RUN' % title); P(); continue
        cb = R['completions_by_sub'][sub]; P('### %s -- cells %d, complete %d; by arm: %s' % (title, cb['cells'], cb['complete'], ', '.join('%s %d / %d' % (a, v['complete'], v['cells']) for a, v in cb['by_arm'].items()))); P()
        arms = sorted({a for r in rows for a in r['arms']}); P('| task | topology | seed | ' + ' | '.join(arms) + ' |'); P('|---|---|---:|' + '---|' * len(arms))
        for r in rows: P('| %s | %s | %s | %s |' % (r['task'], r['topology'], r['seed'], ' | '.join(('%s %s/%s %.2fs r%s%s' % ('C' if c['complete'] else 'x', c['published'], c['K'], c['receipt_wall_s'] or 0, f4(c['worst_radius']), ('' if c.get('identity_ok') else ' ID!'))) if (c := r['arms'].get(a)) else '-' for a in arms)))
        P()
    vi = R['verdict_inputs']; ex = vi.get('exposed', {})
    if ex: P('## 2. Exposed-panel sets (36 tasks)'); P(); P('- Complete: %s; dense (er50 + clique + external): %s' % (ex['n_complete'], ex['dense_complete'])); P('- FULL3 not BASE: %s; BASE not FULL3: %s; UPAC3 not BASE: %s; FULL3 not UPAC3: %s; UPAC3 not FULL3: %s' % (ex['FULL3_not_BASE'] or 'none', ex['BASE_not_FULL3'] or 'none', ex['UPAC3_not_BASE'] or 'none', ex['FULL3_not_UPAC3'] or 'none', ex['UPAC3_not_FULL3'] or 'none')); P('- Historical DGP2 FULL2 (labelled comparator, not rerun) complete: %d; FULL3 gained %s, lost %s relative to it. New-completion candidates (FULL3 only): %s' % (len(ex['DGP2_FULL2_historical_complete']), ex['FULL3_vs_DGP2_FULL2']['gained'] or 'none', ex['FULL3_vs_DGP2_FULL2']['lost'] or 'none', ex['new_completion_candidates'] or 'none')); P()
    fv = vi.get('fresh', {})
    if fv: P('- Fresh EVAL-3: complete %s; FULL3 not BASE %s; BASE not FULL3 %s' % (fv['n_complete'], fv['FULL3_not_BASE'] or 'none', fv['BASE_not_FULL3'] or 'none'))
    for sub in ('preservation_18', 'preservation_13'):
        p = vi.get(sub)
        if p: P('- %s: FULL3 %d / %d (DGP1 FULL v0.5.1 %d; DGP2 FULL2 %d); regressions %s; gains %s' % (sub, p['FULL3_complete'], p['n'], p['DGP1_FULL_v051_complete'], p['DGP2_FULL2_complete'], p['regressions'] or 'none', p['gains'] or 'none'))
    P(); P('## 3. Original-coordinate accuracy on mutual failures (recorded final certificate widths; radius = half the max remaining width; 0.5 = unresolved)'); P(); P('| task | topology | BASE | UPAC3 | FULL3 | FULL2 hist | BASE / FULL3 | FULL2 / FULL3 | material | FULL3 lifted: construction / draws / log2 mean X / max width |'); P('|---|---|---:|---:|---:|---:|---:|---:|---|---|')
    for x in vi.get('accuracy_mutual_failures', []): l = x.get('FULL3_lifted') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s / %s |' % (x['task'], x['topology'], f4(x['BASE_worst']), f4(x['UPAC3_worst']), f4(x['FULL3_worst']), f4(x['FULL2_hist_worst']), f2(x['ratio_BASE_over_FULL3']), f2(x['ratio_FULL2_over_FULL3']), ('vs BASE' if x['material_2x_vs_BASE'] else '') + (' vs FULL2' if x['material_2x_vs_FULL2'] else '') or 'no', (l.get('construction') or '-')[:28], l.get('draws', '-'), f2(l.get('log2_X_mean')), f4(l.get('max_remaining_width'))))
    P(); P('## 4. Efficiency on mutual completions (receipt seconds)'); P(); P('| task | BASE | UPAC3 | FULL3 | FULL2 hist | FULL3 / BASE |'); P('|---|---:|---:|---:|---:|---:|')
    for x in vi.get('efficiency_mutual', []): P('| %s | %.2f | %s | %.2f | %s | %.2f |' % (x['task'], x['BASE_s'], f2(x['UPAC3_s']), x['FULL3_s'], f2(x['FULL2_hist_s']), x['ratio_FULL3_over_BASE']))
    if vi.get('efficiency_mutual'): rs = sorted(x['ratio_FULL3_over_BASE'] for x in vi['efficiency_mutual']); P(); P('FULL3 / BASE median %.2f (min %.2f, max %.2f) over %d mutual completions.' % (rs[len(rs) // 2], rs[0], rs[-1], len(rs)))
    P(); P('## 5. Grouped envelope in production (FULL3 lifted stream per task: construction, charged bytes, cap, weights, information)'); P(); P('| sub | task | lifted construction | groups / pairs / cells / s / bytes | cap W_int log2 | draws | log2 mean X | ESS | max width | closed |'); P('|---|---|---|---|---:|---:|---:|---:|---:|---|')
    for k in vi.get('grouped_envelope_production', []): s = k.get('stream') or {}; g = s.get('grouped_envelope') or {}; P('| %s | %s | %s | %s / %s / %s / %s / %s | %s | %s | %s | %s | %s | %s |' % (k['sub'], k['task'], (s.get('construction') or 'no stream')[:30], g.get('groups', '-'), g.get('grouped_pairs', '-'), g.get('cells', '-'), f2(g.get('seconds')), g.get('charged_bytes', '-'), f2((s.get('cap_units') or {}).get('cap_Wint_log2')), s.get('draws', '-'), f2(s.get('log2_X_mean')), f2(s.get('ESS')), f4(s.get('max_remaining_width')), (s.get('closed') or '')[:50]))
    P(); P('## 6. Forced / standalone panel vs FULL3 (reachability at equal 20 s contract; NOT completions; near-threshold tasks marked *)'); P(); P('| task | arm | forced: construction / draws / valid endpoints / max width / log2 mean X / t_prep / grouped s | FULL3: offered / construction / draws / max width / first batch s |'); P('|---|---|---|---|')
    for x in vi.get('forced_vs_FULL3', []): f = x['forced']; g = x['in_FULL3']; P('| %s%s | %s | %s / %s / %s / %s / %s / %s / %s | %s / %s / %s / %s / %s |' % (x['task'], '*' if x['near_threshold'] else '', x['arm'], (x['not_applicable'][:60] if x.get('not_applicable') else (f.get('construction') or ''))[:60], f.get('draws'), f.get('valid_endpoints'), f4(f.get('max_remaining_width')), f2(f.get('log2_X_mean')), f2(f.get('t_prep')), f2((f.get('grouped_envelope') or {}).get('seconds')), g.get('offered'), (g.get('construction') or '')[:28], g.get('draws'), f4(g.get('max_remaining_width')), f2(g.get('time_to_first_batch'))))
    P(); P('## 7. Oracle panel: envelope levels (16 DGP2 oracle models, forced-PAC profile; exact enumeration; log2 units; C in W_int units)'); P(); P('| model | states | level | groups/pairs | Z_U/Z | B/Z_U | C/Z | C_tight/Z | M2 | R* | M2_min^(r) | R*_min^(r) | B viol | replay A worst (3 seeds) | B vs A material |'); P('|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|')
    for r in D['oracle']:
        if not r.get('levels'): P('| %s | %d | %s | | | | | | | | | | | | |' % (r['task'], r['fine_states'], r.get('status', 'not run')[:60])); continue
        for lv in LEVELS:
            q = r['levels'].get(lv) or {}
            if q.get('log2_C_over_Z') is None: P('| %s | %d | %s | %s | - | - | - | - | - | - | - | - | - | - | - |' % (r['task'], r['fine_states'], lv, (str(q.get('closed') or q.get('stage') or 'not run'))[:40])); continue
            g = q.get('grouped') or {}; rp = q.get('replay') or {}; P('| %s | %d | %s%s | %s/%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], r['fine_states'], lv, (' (identity control)' if r.get('identity_class_map') else ''), g.get('groups', '-'), g.get('grouped_pairs', '-'), f2(q['log2_ZU_over_Z']), f2(q['log2_B_over_ZU']), f2(q['log2_C_over_Z']), f2(q['log2_C_tight_over_Z']), f2(q['log2_M2']), f2(q['log2_R_star']), f2(q['log2_M2_min_fixed_r']), f2(q['log2_R_star_min_fixed_r']), q.get('B_cap_violations'), ' / '.join('%.4f' % w for w in (rp.get('A') or {}).get('worst', [])) or '-', ((rp.get('cap_effect_B_vs_A') or {}).get('material', '-'))))
    P(); P('## 8. Oracle panel: original stream, counterfactual laws (same decoder) and the block decoder'); P(); P('| model | orig C/Z | orig tight | orig M2 | orig R* | paired arithmetic max / bound | cap-opt law R* / M2 / replay worst | M2-opt law R* / M2 / replay | block: M2_min / R*_min / cap-opt replay | realized G2 vs G1 (A) | block vs product cap-opt |'); P('|---|---:|---:|---:|---:|---|---|---|---|---|---|')
    for r in D['oracle']:
        o = r.get('original_stream') or {}; pa = r.get('paired_arithmetic') or {}; cf = r.get('counterfactual_laws_same_decoder') or {}; bd = r.get('block_decoder') or {}; co = cf.get('cap_optimal_same_decoder') or {}; mo = cf.get('M2_optimal_same_decoder') or {}; ct = r.get('contrasts') or {}
        P('| %s | %s | %s | %s | %s | %s / %s | %s / %s / %s | %s / %s / %s | %s / %s / %s | %s | %s |' % (r['task'], f2(o.get('log2_C_over_Z')), f2(o.get('log2_C_tight_over_Z')), f2(o.get('log2_M2')), f2(o.get('log2_R_star')), ('%.1e' % pa['max_abs_log2_dev']) if pa.get('max_abs_log2_dev') is not None else '-', ('%.1e' % pa['bound_log2_from_rho_X']) if pa.get('bound_log2_from_rho_X') else '-', f2(co.get('log2_R_star')), f2(co.get('log2_M2')), med(co.get('replay')), f2(mo.get('log2_R_star')), f2(mo.get('log2_M2')), med(mo.get('replay')), f2(bd.get('log2_M2_min_fixed_rB')), f2(bd.get('log2_R_star_min_fixed_rB')), med((bd.get('cap_optimal') or {}).get('replay')), (ct.get('realized_G2_vs_G1_replay_A') or {}).get('material', '-'), (ct.get('block_cap_optimal_vs_product_cap_optimal_replay') or {}).get('material', '-')))
    P(); P('## 9. Hypothesis statuses (frozen rules, PROTOCOL.md section 7; the six card-4 models with a READY original stream: %s; supplementary card-4 models (original contracts exactly): %s)' % (D.get('card4_ready_panel'), D.get('card4_supplementary'))); P()
    for k, v in D['explanations'].items(): P('- **%s**: %s (supported %d, contradicted %d, unidentified %d of %d%s). Rule: %s' % (k, v['status'].upper(), len(v['supported']), len(v['contradicted']), len(v['unidentified']), len(v['supported']) + len(v['contradicted']) + len(v['unidentified']), ('; needed %d' % v['n_needed']) if v.get('n_needed') else '', v['rule']))
    P(); P('## 10. Charges (supervisor receipts; ceiling 7,200 s)'); P(); P('```'); P(json.dumps({k: v for k, v in R['charges'].items() if k != 'non_completed'}, indent=1)); P('non-completed receipts: %s' % R['charges']['non_completed']); P('```'); P()
    P('## 11. Disclosures'); P(); P('- The 7,200 s ceiling was adopted from DGP2 (not stated by the review or the overseer message; BUDGET_DECLARATION.json).'); P('- Unsupervised work: controls/UNSUPERVISED_DEV_LOG.md (syntax / import checks; everything else charged).'); P('- The oracle panel is the DGP2 oracle panel (now exposed to the oracle calculations, labelled); the 8 DGP2 fresh inputs are now exposed production inputs (`__eval2`); the fresh EVAL-3 inputs were generated after the second freeze.'); P('- Historical FULL2 numbers are the DGP2 cells (not rerun).'); P('- DGP2 erratum: DGP2_REPAIR_AND_DIAGNOSIS/ERRATUM.md (reporting only; scored records unchanged).'); P('- Budget deviation: BUDGET_DECLARATION allocated the forced panel as 10 x 2 arms (400 s) before PROTOCOL.md fixed three forced arms (FORCED_ORIG / FORCED_LIFT_G1 / FORCED_LIFT_G2: up to 600 s); the difference is drawn from contingency. Two oracle receipts were TIMEOUT_KILLed at the 100 s cap before FREEZE_AMENDMENT_harness1 (oracle harness only) and are charged; the oracle allocation (800 s) was exhausted before the continuation pass reached the two n12 binary cliques (their G3 replay is absent; G1 / G2 complete).'); P('- The two dev-tree TIMEOUT_KILL receipts (a control hang during development, a dev oracle continuation) and the dev-tree planner smokes are development charges (scope dgp3_dev), disclosed in CHARGES.json.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md', len(L), 'lines')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'select-confirm': select_confirm()
    elif len(sys.argv) > 1 and sys.argv[1] == 'report': report()
    else: analyze()
