"""DGP4 committed analyzer (PROTOCOL.md sections 5-7; protocol rule 8): derives every count / table from the raw cells, oracle outputs and the ledger. Writes RESULTS.json (complete attempted matrix for BASE / REPAIRED / NEW
on the 52-task main panel and the preservation panels, completion sets vs each other and vs the historical DGP3 FULL3, original-coordinate accuracy on the FULL query inventory, cost / overhead, confirmation selection by the
frozen rule), DIAGNOSTICS.json (per-oracle-model constructions G2 / RMAX V64..4096: both decompositions, prefix-zero vs completed closure, packing inflation, splits, consumed messages, costs; replay radii; the gates C / R;
per-production-cell optional-route status), RUN_MANIFEST.json, CHARGES.json, REPORT.md. usage: dgp4_analyze.py [select-confirm | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
import numpy as np
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP4_RESIDUAL_MAX'; DGP3 = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP3_GROUPED_ENVELOPE'; DGP1 = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'
ARMS = ['BASE', 'REPAIRED', 'NEW']; FORCED_ARMS = ['FORCED_G2', 'FORCED_RMAX']; EPS = 0.005; WIDTHS = (64, 256, 1024, 4096); EXPOSED_STRONG = ['dg_n6_c4_clique_two', 'dg_n8_c4_er50_two', 'dg_n8_c4_clique_two']
FAILURE_CLASSES = ['no constructor admission', 'insufficient checked prefix', 'envelope still loose', 'packing erases gain', 'coarse bounding overhead erases gain', 'poor fixed-decoder overlap', 'construction cost consumes benefit', 'retained-memory / scheduling limitation', 'unresolved / censored']
def load(p):
    try: return json.load(open(p))
    except Exception: return None
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()

def cells_of(sub):
    out = []
    for p in sorted(glob.glob(os.path.join(RD, 'runs', sub, '*', 'cell.json'))):
        c = load(p)['cell']; c['_dir'] = os.path.dirname(p); c['_result'] = load(os.path.join(c['_dir'], 'result.json')); out.append(c)
    return out

def radii_full_inventory(c):
    """per ORIGINAL coordinate final radius on the FULL fixed query inventory: planner arms = enclosures (informative partial enclosures preserved) with 0.5 for every inventory coordinate without one; BASE = published rows, 0.5 otherwise"""
    d = c['_result']
    if d is None: return None, None
    K = d.get('K') or 0; rows = d.get('answers') or []; rad = {}
    for a in rows:
        key = (a['var'], a['state'])
        if a.get('guarantee') != 'NOT_PUBLISHED': rad[key] = float(F(a['hi']) - F(a['lo'])) / 2
    if c['arm'] != 'BASE':
        for e in d.get('enclosures') or []:
            key = (e['var'], e['state']); w = float(F(e['hi']) - F(e['lo'])) / 2
            if key not in rad or w < rad[key]: rad[key] = w
    keys = [(a['var'], a['state']) for a in rows] if rows else list(rad)
    full = [min(0.5, rad.get(k, 0.5)) for k in keys]; return full, dict(K=K, informative=sum(1 for k in keys if k in rad), deterministic_rows=sum(1 for a in rows if a.get('guarantee') in ('EXACT', 'DETERMINISTIC')), pac_rows=sum(1 for a in rows if a.get('guarantee') == 'PAC_EB'))

def stream_rows(c):
    d = c['_result']; out = []
    for s in (d or {}).get('streams') or []:
        m = s.get('mechanism') or {}; stages = [(x['stage'], x.get('completed'), x.get('censored'), round(x.get('seconds') or 0, 3)) for x in (s.get('measurements') or []) if x.get('kind') in ('pac_stage', 'lifted_stage')]
        rm = m.get('rmax') or {}
        out.append(dict(kind=s['kind'], label=s['label'], stage=s['stage'], closed=s.get('closed'), construction=('BUILT' if s['stage'] in ('READY', 'COMPLETE') or s['draws'] else ('REFUSED: ' + str(s.get('closed'))[:80] if s.get('closed') else s['stage'])), stages=stages, draws=s['draws'], batches=s.get('batches'), valid_endpoints=((s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None), witness=s.get('witness'), X_mean=s.get('X_mean'), log2_X_mean=(math.log2(s['X_mean']) if s.get('X_mean') else None), ESS=s.get('ESS_DIAGNOSTIC'), largest_share=s.get('largest_share'), max_remaining_width=s.get('max_remaining_width'), t_prep=s.get('t_prep'), t_sample=s.get('t_sample'), eps_num=m.get('eps_num'), cap_units=m.get('cap_units'), bound_kind=m.get('bound_kind'), grouped_envelope=m.get('grouped_envelope'), rmax=({k: rm.get(k) for k in ('stages_done', 'stages_total', 'prefix_complete', 'consumed_messages', 'max_splits', 'work_cells', 'seconds_total', 'peak_owned_bytes', 'packing', 'checker', 'refusals', 'profile')} if rm else None), rmax_refusal=m.get('rmax_refusal'), rmax_allowance=m.get('rmax_allowance'), construction_defect=m.get('construction_defect'), terminal=m.get('terminal'), delta_s=s.get('delta_s'), scale_to_original=s.get('scale_to_original'), Z_original=s.get('Z_original'), retained_bytes=s.get('retained_bytes'), proposal_immutable=m.get('proposal_immutable')))
    return out

def optional_status(streams):
    """offered / admitted / prefix-checked / READY / sampled / published status of the optional lifted route + reason code"""
    L = [s for s in streams if s['kind'] == 'lifted']
    if not L: return dict(status='NOT_OFFERED', reason=None)
    s = L[0]; rm = s.get('rmax') or {}
    if s['stage'] in ('READY', 'COMPLETE') or s['draws']: st = 'SAMPLED' if s['draws'] else 'READY'
    elif rm.get('stages_done'): st = 'PREFIX_CHECKED_THEN_CLOSED'
    elif s.get('rmax_refusal') or (s.get('closed') or '').startswith(('REFUSED', 'MEMORY', 'SUPPORT', 'DEFECT')): st = 'REFUSED'
    else: st = 'CLOSED'
    return dict(status=st, reason=(s.get('closed') or (s.get('rmax_refusal') or {}).get('kind')), published_from_route=s.get('valid_endpoints'), stages_done=rm.get('stages_done'), stages_total=rm.get('stages_total'), draws=s['draws'])

def cell_row(c):
    rad, inv = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}; streams = stream_rows(c); cost = d.get('cost_breakdown') if c['arm'] != 'BASE' else None
    L = next((s for s in streams if s['kind'] == 'lifted'), None); P = next((s for s in streams if s['kind'] in ('original', 'exact_parent')), None)
    row = dict(task=c['task'], arm=c['arm'], seed=c.get('seed'), seed_index=c.get('seed_index', 0), confirm=c['confirm'], contract=c['contract'], complete=bool(c.get('complete')), outcome=c.get('outcome'), published=c.get('published'), K=c.get('K'), receipt_wall_s=c.get('receipt_wall_s'), receipt_outcome=c.get('receipt_outcome'), peak_MiB=c.get('peak_MiB'), termination=c.get('termination'), route=c.get('route'), identity_ok=c.get('identity_ok'), code_commit=c.get('code_commit'), hard_deadline_respected=c.get('hard_deadline_respected'),
               worst_radius=(max(rad) if rad else None), median_radius=(float(np.median(rad)) if rad else None), covered_at_eps=(sum(1 for x in rad if x <= EPS) if rad else None), inventory=inv, streams=streams, optional_route=optional_status(streams), ledger_identity=m.get('constructor_live_ledger_identity'), live_bytes=m.get('live_memory_named_bytes'), cost=cost, time_to_first_batch=((cost or {}).get('time_to_first_committed_batch_s')), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), refusal=m.get('refusal') or d.get('refusal'), defect=m.get('defect'), envelope=d.get('envelope'), decisions=[x.get('chosen') for x in d.get('decisions', [])][:16], dir=os.path.relpath(c['_dir'], RD),
               constructor_fraction=((sum((cost or {}).get(k, 0) or 0 for k in ('canonicalize', 'features', 'pricing', 'structural_routes', 'quotient_construction', 'pac_preparation', 'lifted_preparation') if isinstance((cost or {}).get(k), (int, float))) / d['wall_s']) if cost and d.get('wall_s') else None), primary_draws=(P or {}).get('draws'), lifted_draws=(L or {}).get('draws'), draws_per_remaining_s=((((P or {}).get('draws') or 0) + ((L or {}).get('draws') or 0)) / max(1e-9, (d.get('wall_s') or 0) - ((cost or {}).get('time_to_first_committed_batch_s') or 0))) if d.get('wall_s') and cost and cost.get('time_to_first_committed_batch_s') is not None else None)
    return row

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0), c['confirm']), {})[c['arm']] = cell_row(c)
    return by, cs

def final_worst(rep, treatment=None):
    vals = []
    for sd in (rep or {}).get('seeds', {}).values():
        ch = sd.get('checkpoints'); ch = ch.get(treatment) if (treatment and isinstance(ch, dict)) else ch
        if ch: vals.append(dict(worst=ch[-1]['worst_radius'], covered=ch[-1]['covered'], K=ch[-1]['K'], draws=ch[-1]['draws']))
    return vals

def analyze():
    man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); fr = load(os.path.join(RD, 'FREEZE.json')); res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code']['commit'], freeze_sha256=sha(os.path.join(RD, 'FREEZE.json')), tables={}, completions_by_sub={}, verdict_inputs={})
    PANEL_OF = {'main': 'main_52', 'preservation_18': 'preservation_18', 'preservation_13': 'preservation_13', 'forced': 'exposed_36', 'confirm': 'main_52'}
    meta_panel = {p: {t['name']: t for t in man['panels'][p]} for p in ('main_52', 'exposed_36', 'preservation_18', 'preservation_13', 'oracle_24')}; meta = {}
    for p in ('oracle_24', 'preservation_13', 'preservation_18', 'main_52'): meta.update(meta_panel[p])
    for sub in ('main', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        by, cs = table(sub)
        if not cs: continue
        mp = meta_panel[PANEL_OF[sub]]; order_names = [t['name'] for t in man['panels'][PANEL_OF[sub]]]
        if sub == 'confirm': mp = dict(meta_panel['preservation_18'], **meta_panel['main_52']); order_names = order_names + [t['name'] for t in man['panels']['preservation_18']]
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], confirm=k[2], topology=mp.get(k[0], meta.get(k[0], {})).get('topology') or mp.get(k[0], meta.get(k[0], {})).get('family'), panel=mp.get(k[0], meta.get(k[0], {})).get('panel'), exposure=mp.get(k[0], meta.get(k[0], {})).get('exposure'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], order_names.index(kv[0][0]) if kv[0][0] in order_names else 999))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- historical comparator: DGP3 FULL3 (exposed 36 by name; EVAL-3 fresh by name + '__eval3'; preservation panels)
    d3 = load(os.path.join(DGP3, 'RESULTS.json')) or {}; hist3 = {}
    for r in (d3.get('tables') or {}).get('exposed_main', []): hist3[r['task']] = r['arms'].get('FULL3', {})
    for r in (d3.get('tables') or {}).get('fresh', []): hist3[r['task'] + '__eval3'] = r['arms'].get('FULL3', {})
    hist3_pres = {sub: {r['task']: r['arms'].get('FULL3', {}) for r in (d3.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}
    em = res['tables'].get('main', []); comp = {a: sorted(r['task'] for r in em if r['arms'].get(a, {}).get('complete')) for a in ARMS}; is_fresh = lambda t: meta.get(t, {}).get('panel') == 'fresh_8'; is_dense = lambda t: meta.get(t, {}).get('topology') in ('er50', 'clique') or meta.get(t, {}).get('panel') == 'external' or 'wcsp' in t or 'CSP' in t
    full3_complete = sorted(t for t, h in hist3.items() if h.get('complete') and t in {r['task'] for r in em})
    res['verdict_inputs']['main'] = dict(n_tasks=len(em), complete=comp, n_complete={a: len(comp[a]) for a in ARMS}, dense_complete={a: len([t for t in comp[a] if is_dense(t)]) for a in ARMS}, fresh_complete={a: sorted(t for t in comp[a] if is_fresh(t)) for a in ARMS}, NEW_not_REPAIRED=sorted(set(comp['NEW']) - set(comp['REPAIRED'])), REPAIRED_not_NEW=sorted(set(comp['REPAIRED']) - set(comp['NEW'])), NEW_not_BASE=sorted(set(comp['NEW']) - set(comp['BASE'])), BASE_not_NEW=sorted(set(comp['BASE']) - set(comp['NEW'])), REPAIRED_not_BASE=sorted(set(comp['REPAIRED']) - set(comp['BASE'])), BASE_not_REPAIRED=sorted(set(comp['BASE']) - set(comp['REPAIRED'])), DGP3_FULL3_historical_complete=full3_complete, NEW_vs_FULL3=dict(gained=sorted(set(comp['NEW']) - set(full3_complete)), lost=sorted(set(full3_complete) - set(comp['NEW']))), REPAIRED_vs_FULL3=dict(gained=sorted(set(comp['REPAIRED']) - set(full3_complete)), lost=sorted(set(full3_complete) - set(comp['REPAIRED']))), new_dense_completion_candidates=sorted(t for t in set(comp['NEW']) - set(comp['BASE']) - set(comp['REPAIRED']) - set(full3_complete) if is_dense(t)))
    # accuracy on mutual failures (full inventory radii) and cost / overhead on mutual completions
    acc = []; cost = []
    for r in em:
        b = r['arms'].get('BASE'); p = r['arms'].get('REPAIRED'); nw = r['arms'].get('NEW')
        if not p or not nw: continue
        if not p['complete'] and not nw['complete']:
            rp, rn, rb = p['worst_radius'], nw['worst_radius'], (b or {}).get('worst_radius')
            acc.append(dict(task=r['task'], topology=r['topology'], fresh=is_fresh(r['task']), BASE_worst=rb, REPAIRED_worst=rp, NEW_worst=rn, ratio_REPAIRED_over_NEW=(rp / rn if rp is not None and rn not in (None, 0) else None), material_2x_vs_REPAIRED=bool(rp is not None and rn not in (None, 0) and rp / rn >= 2), material_2x_vs_BASE=bool(rb is not None and rn not in (None, 0) and rb / rn >= 2), NEW_informative=(nw.get('inventory') or {}).get('informative'), REPAIRED_informative=(p.get('inventory') or {}).get('informative'), NEW_covered=nw['covered_at_eps'], REPAIRED_covered=p['covered_at_eps'], NEW_route=nw['optional_route'], REPAIRED_route=p['optional_route'], NEW_lifted=next(({k: s.get(k) for k in ('construction', 'draws', 'log2_X_mean', 'max_remaining_width', 'rmax', 'rmax_refusal', 'closed', 't_prep')} for s in nw['streams'] if s['kind'] == 'lifted'), None), REPAIRED_lifted=next(({k: s.get(k) for k in ('construction', 'draws', 'log2_X_mean', 'max_remaining_width', 'grouped_envelope', 'closed', 't_prep')} for s in p['streams'] if s['kind'] == 'lifted'), None)))
        if p['complete'] and nw['complete']:
            slower = (nw['receipt_wall_s'] - p['receipt_wall_s']); cost.append(dict(task=r['task'], BASE_s=(b or {}).get('receipt_wall_s'), REPAIRED_s=p['receipt_wall_s'], NEW_s=nw['receipt_wall_s'], ratio_NEW_over_REPAIRED=nw['receipt_wall_s'] / p['receipt_wall_s'], flag_slower=bool(slower >= 0.1 and nw['receipt_wall_s'] / p['receipt_wall_s'] >= 1.25), NEW_first_batch=nw.get('time_to_first_batch'), REPAIRED_first_batch=p.get('time_to_first_batch'), NEW_constructor_fraction=nw.get('constructor_fraction'), NEW_draws_per_s=nw.get('draws_per_remaining_s'), REPAIRED_draws_per_s=p.get('draws_per_remaining_s')))
    res['verdict_inputs']['accuracy_mutual_failures'] = acc; res['verdict_inputs']['cost_mutual_completions'] = cost
    # preservation
    for sub, ref in (('preservation_18', 'preservation_18_v051'), ('preservation_13', 'preservation_13_v051')):
        rows = res['tables'].get(sub, []); h3 = hist3_pres.get(sub, {}); ref1 = load(glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json'))[0]) if glob.glob(os.path.join(DGP1, ref, 'RESULTS_*.json')) else None; refc = {r['task']: r['complete'] for r in (ref1 or {}).get('results', [])}
        res['verdict_inputs'][sub] = {a: dict(complete=sum(1 for r in rows if r['arms'].get(a, {}).get('complete')), n=len(rows), regressions_vs_FULL3=sorted(r['task'] for r in rows if h3.get(r['task'], {}).get('complete') and not r['arms'].get(a, {}).get('complete')), regressions_vs_DGP1=sorted(r['task'] for r in rows if refc.get(r['task']) and not r['arms'].get(a, {}).get('complete'))) for a in ('REPAIRED', 'NEW')}
        res['verdict_inputs'][sub]['DGP3_FULL3_complete'] = sum(1 for v in h3.values() if v.get('complete')); res['verdict_inputs'][sub]['NEW_not_REPAIRED'] = sorted(r['task'] for r in rows if r['arms'].get('NEW', {}).get('complete') and not r['arms'].get('REPAIRED', {}).get('complete')); res['verdict_inputs'][sub]['REPAIRED_not_NEW'] = sorted(r['task'] for r in rows if r['arms'].get('REPAIRED', {}).get('complete') and not r['arms'].get('NEW', {}).get('complete'))
    # forced panel
    fo = res['tables'].get('forced', []); forced = []
    for r in fo:
        for arm in FORCED_ARMS:
            a = r['arms'].get(arm)
            if not a: continue
            s = next((x for x in a['streams'] if x['kind'] == 'lifted'), None) or {}
            forced.append(dict(task=r['task'], arm=arm, outcome=a['outcome'], receipt_wall_s=a['receipt_wall_s'], construction=s.get('construction'), closed=s.get('closed'), draws=s.get('draws'), valid_endpoints=s.get('valid_endpoints'), max_remaining_width=s.get('max_remaining_width'), log2_X_mean=s.get('log2_X_mean'), ESS=s.get('ESS'), largest_share=s.get('largest_share'), t_prep=s.get('t_prep'), cap_Wint_log2=(s.get('cap_units') or {}).get('cap_Wint_log2'), rmax=s.get('rmax'), rmax_refusal=s.get('rmax_refusal'), grouped=s.get('grouped_envelope'), retained_bytes=s.get('retained_bytes'), worst_radius=a['worst_radius'], covered=a['covered_at_eps'], ledger_identity=a.get('ledger_identity')))
    res['verdict_inputs']['forced'] = forced
    # optional-route status over every NEW / REPAIRED production cell
    opt = []
    for sub in ('main', 'preservation_18', 'preservation_13'):
        for r in res['tables'].get(sub, []):
            for arm in ('REPAIRED', 'NEW'):
                a = r['arms'].get(arm)
                if a: opt.append(dict(sub=sub, task=r['task'], arm=arm, **a['optional_route'], complete=a['complete'], ledger_identity=a.get('ledger_identity'), lifted=next(({k: s.get(k) for k in ('t_prep', 'draws', 'log2_X_mean', 'max_remaining_width', 'rmax', 'rmax_refusal', 'grouped_envelope', 'cap_units', 'closed')} for s in a['streams'] if s['kind'] == 'lifted'), None)))
    res['verdict_inputs']['optional_route_status'] = opt
    # ---- oracle diagnostics
    diag = dict(utc=res['utc'], oracle=[], units='W_0 = canonical target WITHOUT the scalar; Z_0 = Z / scalar; t(c) = max_{x in c} W_0 / r (actual dyadic decoder); B = implemented certified cap in W_0 units (C_int / scale_F); two decompositions of log2 B / T: mass (B / sum U) + (sum U / T) and law ((B / Z_0) / R*) + (R* / (T / Z_0)); never mixed')
    for t in man['panels']['oracle_24']:
        d = load(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')); row = dict(task=t['name'], panel=t.get('panel'), exposure=t.get('exposure'), topology=t['topology'], n=int(t['n']), card=int(t['card']), scale=str(t['scale']), fine_states=t.get('fine_states'))
        if d is None: row['status'] = 'NOT_RUN'; diag['oracle'].append(row); continue
        row.update(status=('CENSORED: ' + '; '.join(d['censored'])) if d.get('censored') else 'COMPLETE', wall_s=d.get('wall_s'), phases=d.get('phases'), continued_from=d.get('continued_from'), reference=d.get('reference'), log2_Z0=(d.get('original') or {}).get('log2_Z0'), constructions={}, replays={})
        for k, c in (d.get('constructions') or {}).items():
            row['constructions'][k] = {kk: c.get(kk) for kk in ('envelope', 'prepare', 'prep_s', 'closed', 'rmax_refusal', 'mb_splits', 'mb_cap_used', 'log2_B_W0', 'log2_B_over_Z0', 'log2_B_over_T', 'log2_B_over_sumU', 'log2_sumU_over_T', 'log2_sumU_compact_over_T', 'log2_packing_inflation_sum', 'log2_prefix0_sumU_over_T', 'log2_prefix0_over_completed', 'log2_R_star', 'log2_M2', 'max_X_analyzed', 'support_failures', 'U_ge_t_everywhere', 'G2_U_ge_t_everywhere', 'envelope_valid', 'decomposition_mass', 'decomposition_law', 'V_j_max', 'V_j_median', 'log2_K_hi', 'retained_bytes')}
            rm = c.get('rmax') or {}; row['constructions'][k]['rmax'] = {kk: rm.get(kk) for kk in ('stages_done', 'stages_total', 'prefix_complete', 'consumed_messages', 'max_splits', 'work_cells', 'seconds_total', 'peak_owned_bytes', 'packing', 'checker')} if rm else None
        for k, r in (d.get('replays') or {}).items():
            if k == 'ideal_t_over_T': row['replays'][k] = {cap: final_worst(v) for cap, v in (r.get('caps') or {}).items()}
            else: row['replays'][k] = dict(A_implemented_cap=final_worst(r.get('realized'), 'A'), B_tight_cap=final_worst(r.get('realized'), 'B'), seconds=r.get('seconds'))
        g2 = row['constructions'].get('G2') or {}; rx = row['constructions'].get('RMAX_V4096') or {}
        cap_gain = (g2['log2_B_W0'] - rx['log2_B_W0']) if g2.get('log2_B_W0') is not None and rx.get('log2_B_W0') is not None else None
        ra = row['replays'].get('RMAX_V4096', {}).get('A_implemented_cap') or []; ga = row['replays'].get('G2', {}).get('A_implemented_cap') or []
        rad_ratios = [g['worst'] / r_['worst'] if r_['worst'] > 0 else None for g, r_ in zip(ga, ra)]; newly_all = any(r_['covered'] == r_['K'] and g['covered'] < g['K'] for g, r_ in zip(ga, ra))
        row['contrasts'] = dict(log2_cap_gain_G2_over_RMAX4096=cap_gain, cap_gate_2x=(cap_gain is not None and cap_gain >= 1.0 and (rx.get('rmax') or {}).get('stages_done', 0) > 0), prefix_executed=(rx.get('rmax') or {}).get('stages_done'), mass_term_G2=(g2.get('log2_sumU_over_T')), mass_term_RMAX=rx.get('log2_sumU_over_T'), bounding_term_G2=g2.get('log2_B_over_sumU'), bounding_term_RMAX=rx.get('log2_B_over_sumU'), law_term_G2=(g2.get('decomposition_law') or {}).get('log2_Rstar_over_T_over_Z0'), law_term_RMAX=(rx.get('decomposition_law') or {}).get('log2_Rstar_over_T_over_Z0'), packing_RMAX=rx.get('log2_packing_inflation_sum'), prefix0_vs_completed_RMAX=rx.get('log2_prefix0_over_completed'), width_dose={('V%d' % V): (row['constructions'].get('RMAX_V%d' % V) or {}).get('log2_B_over_T') for V in WIDTHS}, replay_radius_ratios_G2_over_RMAX=rad_ratios, replay_seeds_2x=sum(1 for x in rad_ratios if x is not None and x >= 2), newly_all_covered=newly_all, certificate_gate=(sum(1 for x in rad_ratios if x is not None and x >= 2) >= 2 or newly_all) if ra and ga else None, ideal_tight=[x['worst'] for x in (row['replays'].get('ideal_t_over_T') or {}).get('tight_T_over_Z0', [])], ideal_under_RMAX_U=[x['worst'] for x in (row['replays'].get('ideal_t_over_T') or {}).get('required_by_RMAX_V4096_sumU_over_Z0', [])], ideal_under_G2_U=[x['worst'] for x in (row['replays'].get('ideal_t_over_T') or {}).get('required_by_G2_sumU_over_Z0', [])])
        diag['oracle'].append(row)
    O = {r['task']: r for r in diag['oracle']}
    exposed_anchor = [t for t in EXPOSED_STRONG if t in O]; fresh_strong = sorted(t for t, r in O.items() if r.get('panel') == 'oracle_fresh_8' and r['scale'] == '2' and r['card'] == 4)
    gate = lambda ts: [t for t in ts if (O[t].get('contrasts') or {}).get('cap_gate_2x')]
    cap = dict(exposed_anchors=exposed_anchor, exposed_pass=gate(exposed_anchor), exposed_gate=(len(gate(exposed_anchor)) >= 2), fresh_strong=fresh_strong, fresh_pass=gate(fresh_strong), fresh_gate=(len(gate(fresh_strong)) >= 2), per_model={t: dict(gain_bits=(O[t].get('contrasts') or {}).get('log2_cap_gain_G2_over_RMAX4096'), prefix=(O[t].get('contrasts') or {}).get('prefix_executed')) for t in exposed_anchor + fresh_strong})
    cap['status'] = 'supported' if (cap['exposed_gate'] and cap['fresh_gate']) else ('contradicted' if all(t in O and O[t].get('status', '').startswith('COMPLETE') for t in exposed_anchor + fresh_strong) and (exposed_anchor and fresh_strong) else 'unidentified')
    qual = cap['exposed_pass'] + cap['fresh_pass']; cert = dict(qualifying=qual, per_model={t: dict(ratios=(O[t].get('contrasts') or {}).get('replay_radius_ratios_G2_over_RMAX'), seeds_2x=(O[t].get('contrasts') or {}).get('replay_seeds_2x'), newly_all=(O[t].get('contrasts') or {}).get('newly_all_covered'), gate=(O[t].get('contrasts') or {}).get('certificate_gate')) for t in qual})
    cert['passing'] = [t for t in qual if cert['per_model'][t]['gate']]; cert['status'] = ('unidentified' if not qual else ('supported' if cert['passing'] and len(cert['passing']) == len(qual) else ('mixed' if cert['passing'] else 'contradicted')))
    diag['gates'] = dict(cap_mechanism=cap, certificate_mechanism=cert)
    # ---- end-to-end + preservation + cost verdicts
    vi = res['verdict_inputs']; mi = vi.get('main', {}); mat = [x for x in acc if x['material_2x_vs_REPAIRED'] or x['material_2x_vs_BASE']]
    e_candidates = mi.get('new_dense_completion_candidates', []) + [x['task'] for x in mat]
    pres_ok = all(not vi.get(sub, {}).get('NEW', {}).get('regressions_vs_FULL3') for sub in ('preservation_18', 'preservation_13')) and not mi.get('REPAIRED_not_NEW') and not mi.get('BASE_not_NEW')
    flags = [x['task'] for x in cost if x['flag_slower']]
    # failure class (one): derived from the oracle contrasts on the anchors and the production route statuses
    fc = None
    if cap['status'] != 'supported':
        anch = [O[t]['contrasts'] for t in exposed_anchor + fresh_strong if O.get(t, {}).get('contrasts')]
        if not anch: fc = 'unresolved / censored'
        elif any(((O[t]['constructions'].get('RMAX_V4096') or {}).get('prepare') != 'READY') for t in exposed_anchor + fresh_strong if t in O): fc = 'no constructor admission'
        elif any((c.get('prefix_executed') or 0) == 0 for c in anch): fc = 'insufficient checked prefix'
        elif any((c.get('packing_RMAX') or 0) >= 1.0 for c in anch): fc = 'packing erases gain'
        elif any((c.get('bounding_term_RMAX') or 0) >= 1.0 for c in anch): fc = 'coarse bounding overhead erases gain'
        else: fc = 'envelope still loose'
    elif cert['status'] != 'supported': fc = 'poor fixed-decoder overlap'
    elif not e_candidates:
        prod_new = [x for x in opt if x['arm'] == 'NEW' and x['sub'] == 'main']; refused = [x for x in prod_new if x['status'] in ('REFUSED', 'CLOSED', 'PREFIX_CHECKED_THEN_CLOSED')]
        fc = 'retained-memory / scheduling limitation' if refused and len(refused) >= len(prod_new) / 4 else 'construction cost consumes benefit'
    diag['verdicts'] = dict(validity='see VALIDATION.json + controls (the analyzer records: identity_ok on every cell, ledger identity on every planner result, no late publication)', preservation=dict(status=('PRESERVED' if pres_ok else 'REGRESSION'), NEW_losses_vs_FULL3={sub: vi.get(sub, {}).get('NEW', {}).get('regressions_vs_FULL3') for sub in ('preservation_18', 'preservation_13')}, main_losses_vs_REPAIRED=mi.get('REPAIRED_not_NEW'), main_losses_vs_BASE=mi.get('BASE_not_NEW')), cap_mechanism=cap['status'], certificate_mechanism=cert['status'], deployable_progress=dict(status=('CANDIDATE (confirmation pending)' if e_candidates else 'NONE'), new_dense_completions=mi.get('new_dense_completion_candidates'), material_radius_gains=[x['task'] for x in mat], fresh_transfer=[t for t in e_candidates if is_fresh(t)]), cost_overhead=dict(flags=flags, n_mutual=len(cost), median_ratio=(statistics.median(x['ratio_NEW_over_REPAIRED'] for x in cost) if cost else None)), failure_class=fc)
    res['verdicts'] = diag['verdicts']; res['gates'] = diag['gates']; json.dump(diag, open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    # charges
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP4_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json'))
    ch = dict(utc=res['utc'], ceiling_s=9000, allocation_s=bud['allocation_s'], by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), non_completed=[dict(job=r['job'], outcome=r['outcome'], wall_s=round(r['wall_s'], 3)) for r in rc if r['outcome'] != 'COMPLETED'], note='supervisor receipt wall seconds; implementation labor is not charged and is disclosed in REPORT.md', unsupervised_disclosed='controls/UNSUPERVISED_DEV_LOG.md')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, confirm, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, confirm=confirm, contract=contract))
    plan('main', [t['name'] for t in man['panels']['main_52']], ARMS, [0], False, 'main'); plan('preservation_18', [t['name'] for t in man['panels']['preservation_18']], ['REPAIRED', 'NEW'], [0], False, 'p4'); plan('preservation_13', [t['name'] for t in man['panels']['preservation_13']], ['REPAIRED', 'NEW'], [0], False, 'p20'); plan('forced', man['panels']['forced_6'], FORCED_ARMS, [0], False, 'main')
    cm = load(os.path.join(RD, 'CONFIRM_MANIFEST.json'))
    if cm: plan('confirm', cm['selected'], ARMS, [1, 2], True, 'per task')
    actual = {}
    for sub in ('main', 'preservation_18', 'preservation_13', 'forced', 'confirm'):
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0), c['confirm'])] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'], p['confirm'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md: budget / blocked)'
    oracle_actual = {t['name']: os.path.exists(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')) for t in man['panels']['oracle_24']}
    json.dump(dict(utc=res['utc'], code_commit=fr['code']['commit'], planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), oracle=oracle_actual, superseding_links=('see ' + ', '.join(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')))) if glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')) else 'none (no amendment in this round)', historical_comparators=dict(DGP3_FULL3='DGP3_GROUPED_ENVELOPE/runs/exposed_main, fresh, preservation_* (labelled historical; not rerun)')), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], main=mi.get('n_complete'), new=mi.get('new_dense_completion_candidates'), verdicts={k: (v if isinstance(v, str) else (v.get('status') if isinstance(v, dict) else v)) for k, v in diag['verdicts'].items()}, cap_pass=dict(exposed=cap['exposed_pass'], fresh=cap['fresh_pass']), cert=cert['passing'], charges=ch['total_s']), default=str))
    return res, diag

def select_confirm():
    res = load(os.path.join(RD, 'RESULTS.json')); man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); vi = res['verdict_inputs']; meta = {t['name']: t for p in ('preservation_13', 'preservation_18', 'main_52') for t in man['panels'][p]}; mi = vi['main']
    tiers = [('a_regression', sorted(set(mi['REPAIRED_not_NEW'] + mi['BASE_not_NEW'] + mi['NEW_vs_FULL3']['lost']), key=lambda t: meta[t]['model_sha256'] if t in meta else t)), ('b_new_completion', sorted(set(mi['NEW_not_REPAIRED']) | set(mi['NEW_not_BASE']), key=lambda t: meta[t]['model_sha256'] if t in meta else t)), ('c_material_radius', sorted([x['task'] for x in vi['accuracy_mutual_failures'] if x['material_2x_vs_REPAIRED'] or x['material_2x_vs_BASE']], key=lambda t: meta[t]['model_sha256'] if t in meta else t))]
    fr = load(os.path.join(RD, 'FREEZE.json')); tiers.append(('d_anchors', fr['confirmation']['anchors'])); chosen = []; affected = []
    for name, ts in tiers:
        for t in ts:
            if name != 'd_anchors': affected.append((name, t))
            if t not in chosen and len(chosen) < 6: chosen.append(t)
    cm = dict(rule='PROTOCOL.md section 6 / FREEZE.json confirmation', tiers={n: ts for n, ts in tiers}, affected_all=affected, selected=chosen, unconfirmed_affected=[t for n, t in affected if t not in chosen], tasks=[dict(meta[t], contract=('p4' if meta[t].get('panel') == 'unified_18' else 'main')) for t in chosen], arms=ARMS, seed_indices=[1, 2], order='reversed', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(cm, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in cm.items() if k != 'tasks'}))

def report():
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')); L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) and x is not None else '-'
    def med(fin): return f4(statistics.median(x['worst'] for x in fin)) if fin else '-'
    P('# DGP4_RESIDUAL_MAX -- REPORT (analyzer-derived; code pgm %s, tree %s; freeze sha256 %s)' % (fr['code']['commit'][:9], fr['code']['tree'][:9], R['freeze_sha256'][:12])); P()
    P('Question (PROTOCOL.md section 1): does preserving compatibility between fine-state choices through bounded residual MAX elimination (RMAX, decoder fixed) produce a materially tighter IMPLEMENTED certified cap than the repaired grouped envelope (G2), and better original-coordinate accuracy at equal total cost, on dense generic cyclic models? Every count below is derived from the raw cells and oracle outputs by `dgp4_analyze.py`; oracle and forced results never enter completion counts.'); P()
    P('## 1. Completion matrix (completion = receipt COMPLETED, wall <= outer, published == K, outcome COMPLETE / EXACT, positive witness, hard deadline respected)'); P()
    for sub, title in (('main', 'Main panel: 44 exposed (36 DGP3 exposed + 8 EVAL-3 `__eval3`) + 8 fresh EVAL-4; 20 s'), ('preservation_18', 'Preservation: 18 unified inputs at 4 s (REPAIRED, NEW)'), ('preservation_13', 'Preservation: 12 exposed + G4 at 20 s (REPAIRED, NEW)'), ('confirm', 'Confirmations (seed indices 1, 2; reversed order)')):
        rows = R['tables'].get(sub)
        if not rows: P('### %s: NOT RUN' % title); P(); continue
        cb = R['completions_by_sub'][sub]; P('### %s -- cells %d, complete %d; by arm: %s' % (title, cb['cells'], cb['complete'], ', '.join('%s %d / %d' % (a, v['complete'], v['cells']) for a, v in cb['by_arm'].items()))); P()
        arms = sorted({a for r in rows for a in r['arms']}); P('| task | topology | seed idx | ' + ' | '.join(arms) + ' |'); P('|---|---|---:|' + '---|' * len(arms))
        for r in rows: P('| %s | %s | %s | %s |' % (r['task'], r['topology'], r['seed_index'], ' | '.join(('%s %s/%s %.2fs r%s%s%s' % ('C' if c['complete'] else 'x', c['published'], c['K'], c['receipt_wall_s'] or 0, f4(c['worst_radius']), ('' if c.get('identity_ok') else ' ID!'), ('' if c.get('ledger_identity') in (True, None) else ' LEDGER!'))) if (c := r['arms'].get(a)) else '-' for a in arms)))
        P()
    vi = R['verdict_inputs']; mi = vi.get('main', {})
    if mi: P('## 2. Main-panel sets (52 tasks)'); P(); P('- Complete: %s; dense: %s; fresh EVAL-4 complete: %s' % (mi['n_complete'], mi['dense_complete'], {a: len(v) for a, v in mi['fresh_complete'].items()})); P('- NEW not REPAIRED: %s; REPAIRED not NEW: %s; NEW not BASE: %s; BASE not NEW: %s; REPAIRED not BASE: %s; BASE not REPAIRED: %s' % (mi['NEW_not_REPAIRED'] or 'none', mi['REPAIRED_not_NEW'] or 'none', mi['NEW_not_BASE'] or 'none', mi['BASE_not_NEW'] or 'none', mi['REPAIRED_not_BASE'] or 'none', mi['BASE_not_REPAIRED'] or 'none')); P('- Historical DGP3 FULL3 complete on these tasks: %d; NEW gained %s / lost %s; REPAIRED gained %s / lost %s. New dense completion candidates (NEW only): %s' % (len(mi['DGP3_FULL3_historical_complete']), mi['NEW_vs_FULL3']['gained'] or 'none', mi['NEW_vs_FULL3']['lost'] or 'none', mi['REPAIRED_vs_FULL3']['gained'] or 'none', mi['REPAIRED_vs_FULL3']['lost'] or 'none', mi['new_dense_completion_candidates'] or 'none')); P()
    for sub in ('preservation_18', 'preservation_13'):
        p = vi.get(sub)
        if p: P('- %s: REPAIRED %d / %d, NEW %d / %d (DGP3 FULL3 %d); NEW regressions vs FULL3 %s, vs DGP1 %s; NEW not REPAIRED %s; REPAIRED not NEW %s' % (sub, p['REPAIRED']['complete'], p['REPAIRED']['n'], p['NEW']['complete'], p['NEW']['n'], p['DGP3_FULL3_complete'], p['NEW']['regressions_vs_FULL3'] or 'none', p['NEW']['regressions_vs_DGP1'] or 'none', p['NEW_not_REPAIRED'] or 'none', p['REPAIRED_not_NEW'] or 'none'))
    P(); P('## 3. Original-coordinate accuracy on mutual failures (FULL inventory; radius 0.5 for a coordinate without an informative enclosure)'); P(); P('| task | fresh | BASE | REPAIRED | NEW | REPAIRED / NEW | material | NEW route: status / stages / draws / log2 mean X / max width | REPAIRED route: status / draws / log2 mean X |'); P('|---|---|---:|---:|---:|---:|---|---|---|')
    for x in vi.get('accuracy_mutual_failures', []): nl = x.get('NEW_lifted') or {}; rl = x.get('REPAIRED_lifted') or {}; nr = x['NEW_route']; P('| %s | %s | %s | %s | %s | %s | %s | %s / %s/%s / %s / %s / %s | %s / %s / %s |' % (x['task'], x['fresh'], f4(x['BASE_worst']), f4(x['REPAIRED_worst']), f4(x['NEW_worst']), f2(x['ratio_REPAIRED_over_NEW']), ('vs REPAIRED' if x['material_2x_vs_REPAIRED'] else '') + (' vs BASE' if x['material_2x_vs_BASE'] else '') or 'no', nr['status'], nr.get('stages_done'), nr.get('stages_total'), nl.get('draws'), f2(nl.get('log2_X_mean')), f4(nl.get('max_remaining_width')), x['REPAIRED_route']['status'], rl.get('draws'), f2(rl.get('log2_X_mean'))))
    P(); P('## 4. Cost / overhead on mutual completions (receipt seconds; flag = NEW slower than REPAIRED by >= 0.1 s AND >= 1.25x)'); P(); P('| task | BASE | REPAIRED | NEW | NEW / REPAIRED | flag | first batch REPAIRED / NEW | draws per s REPAIRED / NEW |'); P('|---|---:|---:|---:|---:|---|---|---|')
    for x in vi.get('cost_mutual_completions', []): P('| %s | %s | %.2f | %.2f | %.2f | %s | %s / %s | %s / %s |' % (x['task'], f2(x['BASE_s']), x['REPAIRED_s'], x['NEW_s'], x['ratio_NEW_over_REPAIRED'], x['flag_slower'], f2(x['REPAIRED_first_batch']), f2(x['NEW_first_batch']), f2(x['REPAIRED_draws_per_s']), f2(x['NEW_draws_per_s'])))
    P(); P('## 5. Optional route status in every NEW / REPAIRED production cell'); P(); P('| sub | task | arm | status | reason | stages | draws | t_prep | log2 mean X | max width | cap W_int log2 | ledger |'); P('|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|')
    for x in vi.get('optional_route_status', []): l = x.get('lifted') or {}; rm = l.get('rmax') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['sub'], x['task'], x['arm'], x['status'], (str(x.get('reason') or '')[:60]), ('%s/%s' % (rm.get('stages_done'), rm.get('stages_total'))) if rm else '-', l.get('draws', '-'), f2(l.get('t_prep')), f2(l.get('log2_X_mean')), f4(l.get('max_remaining_width')), f2((l.get('cap_units') or {}).get('cap_Wint_log2')), x.get('ledger_identity')))
    P(); P('## 6. Forced diagnostic (six card-4 anchors; FORCED_G2 vs FORCED_RMAX at 20 s, delta / 4; NOT completions)'); P(); P('| task | arm | outcome | construction | stages | splits | consumed msgs | t_prep | draws | valid endpoints | max width | log2 mean X | cap W_int log2 | peak owned B | refusal |'); P('|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for x in vi.get('forced', []): rm = x.get('rmax') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], x['arm'], x['outcome'], (x.get('construction') or '')[:30], ('%s/%s' % (rm.get('stages_done'), rm.get('stages_total'))) if rm else '-', rm.get('max_splits', '-'), rm.get('consumed_messages', '-'), f2(x.get('t_prep')), x.get('draws'), x.get('valid_endpoints'), f4(x.get('max_remaining_width')), f2(x.get('log2_X_mean')), f2(x.get('cap_Wint_log2')), rm.get('peak_owned_bytes', '-'), (str((x.get('rmax_refusal') or {}).get('kind') or x.get('closed') or ''))[:40]))
    P(); P('## 7. Oracle panel: constructions (16 exposed + 8 fresh small models; same classes / decoder / coarse-sampler settings; log2 units; W_0 units)'); P(); P('| model | panel | T/Z0 | construction | ready | prep s | B/T | = B/sumU + sumU/T | prefix0 sumU/T | packing | R* | M2 | max X | stages | splits | consumed | V_j max |'); P('|---|---|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|')
    for r in D['oracle']:
        if not r.get('constructions'): P('| %s | %s | - | %s | | | | | | | | | | | | | |' % (r['task'], r.get('panel'), r.get('status', 'not run')[:50])); continue
        for k, c in r['constructions'].items():
            rm = c.get('rmax') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s + %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], (r.get('panel') or '')[:12], f2((r.get('reference') or {}).get('log2_T_over_Z0')), k, c.get('prepare'), f2(c.get('prep_s')), f2(c.get('log2_B_over_T')), f2(c.get('log2_B_over_sumU')), f2(c.get('log2_sumU_over_T')), f2(c.get('log2_prefix0_sumU_over_T')), f2(c.get('log2_packing_inflation_sum')), f2(c.get('log2_R_star')), f2(c.get('log2_M2')), f2(c.get('max_X_analyzed')), ('%s/%s' % (rm.get('stages_done'), rm.get('stages_total'))) if rm else '-', rm.get('max_splits', '-') if rm else (c.get('mb_splits', '-')), rm.get('consumed_messages', '-') if rm else '-', f2(c.get('V_j_max'))))
    P(); P('## 8. Oracle replays (2^18 draws x seeds 1-3; worst requested radius per seed; A = implemented cap, B = tight cap on the SAME draws; ideal q_C = t / T under its tight cap and under each arm\'s retained U)'); P(); P('| model | G2 A | G2 B | RMAX4096 A | RMAX4096 B | ratio G2/RMAX (A) per seed | seeds >= 2x | ideal tight | ideal under RMAX U | ideal under G2 U | cap gain bits | cap gate | cert gate |'); P('|---|---|---|---|---|---|---:|---|---|---|---:|---|---|')
    for r in D['oracle']:
        rp = r.get('replays') or {}
        if not rp: continue
        ct = r.get('contrasts') or {}; g2 = rp.get('G2') or {}; rx = rp.get('RMAX_V4096') or {}; idl = rp.get('ideal_t_over_T') or {}
        P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], ' / '.join(f4(x['worst']) for x in g2.get('A_implemented_cap', [])), ' / '.join(f4(x['worst']) for x in g2.get('B_tight_cap', [])), ' / '.join(f4(x['worst']) for x in rx.get('A_implemented_cap', [])), ' / '.join(f4(x['worst']) for x in rx.get('B_tight_cap', [])), ' / '.join(f2(x) for x in (ct.get('replay_radius_ratios_G2_over_RMAX') or [])), ct.get('replay_seeds_2x'), ' / '.join(f4(x['worst']) for x in idl.get('tight_T_over_Z0', [])), ' / '.join(f4(x['worst']) for x in idl.get('required_by_RMAX_V4096_sumU_over_Z0', [])), ' / '.join(f4(x['worst']) for x in idl.get('required_by_G2_sumU_over_Z0', [])), f2(ct.get('log2_cap_gain_G2_over_RMAX4096')), ct.get('cap_gate_2x'), ct.get('certificate_gate')))
    P(); P('## 9. Verdicts (frozen criteria, PROTOCOL.md section 7)'); P(); g = D['gates']
    P('- **Cap mechanism**: %s -- exposed anchors %s pass %s (gate %s); fresh strong %s pass %s (gate %s); per model %s' % (g['cap_mechanism']['status'].upper(), g['cap_mechanism']['exposed_anchors'], g['cap_mechanism']['exposed_pass'], g['cap_mechanism']['exposed_gate'], g['cap_mechanism']['fresh_strong'], g['cap_mechanism']['fresh_pass'], g['cap_mechanism']['fresh_gate'], {k: (f2(v['gain_bits']), v['prefix']) for k, v in g['cap_mechanism']['per_model'].items()}))
    P('- **Certificate mechanism**: %s -- qualifying %s; passing %s; per model %s' % (g['certificate_mechanism']['status'].upper(), g['certificate_mechanism']['qualifying'], g['certificate_mechanism']['passing'], {k: (v['seeds_2x'], v['newly_all']) for k, v in g['certificate_mechanism']['per_model'].items()}))
    for k, v in D['verdicts'].items():
        if k not in ('cap_mechanism', 'certificate_mechanism'): P('- **%s**: %s' % (k, json.dumps(v, default=str)[:600]))
    P(); P('## 10. Charges (supervisor receipts; ceiling 9,000 s)'); P(); P('```'); P(json.dumps({k: v for k, v in R['charges'].items() if k != 'non_completed'}, indent=1)); P('non-completed receipts: %s' % R['charges']['non_completed']); P('```'); P()
    P('## 11. Disclosures'); P(); P('- The DGP3 independent review and its evidence packet named by the brief were not present on this machine; the three repairs were implemented from the brief\'s concrete fixtures (section 2) and reproduced before / after (controls/before, controls/after).'); P('- Unsupervised work: controls/UNSUPERVISED_DEV_LOG.md (syntax / import checks and text rewrites; every computation charged).'); P('- Historical FULL3 numbers are the DGP3 cells (not rerun). The 8 DGP3 EVAL-3 inputs are exposed in this round (`__eval3`). The 16 DGP2 oracle models are exposed to the oracle (labelled); the 8 ORACLE4 models and the 8 EVAL-4 inputs were generated after the second freeze.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md', len(L), 'lines')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'select-confirm': select_confirm()
    elif len(sys.argv) > 1 and sys.argv[1] == 'report': report()
    else: analyze()
