"""DGP8 committed analyzer (PROTOCOL.md sections 5-7; protocol rule 8): every count / table is derived from the raw cells (runs/<sub>/<dir>/cell.json + result.json), the manifests and the ledger. Writes RESULTS.json (tables per sub: 'screen' = the Stage A
witness + development-stream cells (HEATBATH_SCREEN), 'guard' = Stage B cells (SPECTRAL_HEATBATH seeds 0 / 1, REPAIRED / BASE comparators), 'regression_18' / 'regression_13' / 'regression_24' = the repaired-engine preservation cohorts; the Stage A feasibility table per
exposed input (witness, eligibility, gap, dimension, seconds, development-stream rate, FORECAST radii at the 20 s / 4 s contracts from the frozen rate model, the hash-matched archived incumbent worst radius and the forecast improvement factor); the guard table (achieved
certified worst radius per seed vs the archived incumbent, improvement factor, transitions actual vs forecast, burn-in, bytes, elapsed); preservation tables with the intersections actually run; verdicts kept separate: validity, spectral_admission, finite_time_confidence,
throughput, partial_accuracy, new_completion, preservation, overhead, deployability), DIAGNOSTICS.json, RUN_MANIFEST.json, CHARGES.json, REPORT.md; `release-decision` writes RELEASE_DECISION.json from the frozen rule (PROTOCOL section 6).
usage: dgp8_analyze.py [analyze | release-decision | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
import numpy as np
RD = os.environ.get('DGP8_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH'); DGP7 = os.path.join(os.path.dirname(RD), 'DGP7_RESIDUAL_JOINT'); DGP6 = os.path.join(os.path.dirname(RD), 'DGP6_GLOBAL_CONSTRUCTION')
ARMS = ['BASE', 'REPAIRED', 'SPECTRAL_HEATBATH']; HB_ARMS = ('SPECTRAL_HEATBATH', 'HEATBATH_SCREEN'); DIAG_ARMS = ['HEATBATH_SCREEN', 'SELECT']; EPS = 0.005; DELTA = 1e-6; N_CHECKPOINTS = 4; RESERVE_S = 0.5
SUBS = ('screen', 'guard', 'regression_18', 'regression_13', 'regression_24'); WORK_S = dict(main=19.0, p4=3.5, p20=19.0)
def load(p):
    try: return json.load(open(p))
    except Exception: return None
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def med(xs): xs = [x for x in (xs or []) if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))]; return float(statistics.median(xs)) if xs else None
def panels():
    man = load(os.path.join(RD, 'MODEL_MANIFEST.json')) or {}; P = man.get('panels') or {}
    return man, {k: v for k, v in P.items() if isinstance(v, list) and v and isinstance(v[0], dict) and 'model' in v[0]}
_SHA_NAME = None
def sha_name_map():
    global _SHA_NAME
    if _SHA_NAME is None:
        _, tp = panels(); _SHA_NAME = {}
        for p in tp.values():
            for t in p: _SHA_NAME.setdefault(t.get('model_sha256'), t['name'])
    return _SHA_NAME
def cells_of(sub):
    out = []
    for p in sorted(glob.glob(os.path.join(RD, 'runs', sub, '*', 'cell.json'))):
        c = load(p)['cell']; c['_dir'] = os.path.dirname(p); c['_result'] = load(os.path.join(c['_dir'], 'result.json')); c['task_recorded'] = c['task']; c['task'] = sha_name_map().get(c.get('model_sha256'), c['task']); out.append(c)
    return out

def radii_full_inventory(c):
    """per ORIGINAL coordinate final radius on the FULL fixed query inventory: published rows, plus (every arm but BASE) informative partial enclosures; 0.5 for every inventory coordinate without one"""
    d = c['_result']
    if d is None: return None, None
    K = d.get('K') or 0; rows = d.get('answers') or []; rad = {}
    for a in rows:
        key = (a['var'], a['state'])
        if a.get('guarantee') != 'NOT_PUBLISHED': rad[key] = float(F(a['hi']) - F(a['lo'])) / 2
    if c['arm'] != 'BASE':
        for e in d.get('enclosures') or []:
            key = (e['var'], e['state']); w = float(F(str(e['hi'])) - F(str(e['lo']))) / 2
            if key not in rad or w < rad[key]: rad[key] = w
    full = [rad.get((a['var'], a['state']), 0.5) for a in rows] if rows else ([0.5] * K if K else [])
    return full, dict(K=K, published=sum(1 for a in rows if a.get('guarantee') != 'NOT_PUBLISHED'), informative=sum(1 for w in full if w < 0.5), width_max=(2 * max(full) if full else None))

def heatbath_status(c):
    """the spectral heat-bath mechanism of one standalone cell, read from result.json directly"""
    d = c['_result']
    if d is None or c['arm'] not in HB_ARMS: return None
    m = d.get('mechanism') or {}; w = m.get('witness') or {}; tr = m.get('transitions') or {}; cps = [x for x in (m.get('checkpoints') or []) if isinstance(x, dict)]; bi = m.get('burn_in') or {}; p0 = m.get('p0') or {}; ds = m.get('dev_stream') if isinstance(m.get('dev_stream'), dict) else None; rf = m.get('refusal'); ph = m.get('phases_s') or {}; by = m.get('bytes') or {}
    done = [x for x in cps if x.get('completed')]; last = done[-1] if done else None; ws = (w.get('seconds_construct') or 0) + (w.get('seconds_verify') or 0)
    rate = tr.get('steps_per_second') or (ds or {}).get('steps_per_second')
    return dict(route=m.get('route'), refusal=rf, refusal_kind=((rf or {}).get('kind') if isinstance(rf, dict) else rf), eligible=w.get('eligible'), l=w.get('l'), u=w.get('u'), width=w.get('width'), margin_m=w.get('margin_m'), gap_g=w.get('gap_g'), dimension=w.get('dimension'), n=w.get('n'), witness_bytes=w.get('bytes'), witness_seconds=ws, witness_seconds_construct=w.get('seconds_construct'), witness_seconds_verify=w.get('seconds_verify'), log_enclosure_max_width=w.get('log_enclosure_max_width'), matrix_max_width=w.get('matrix_max_width'), min_pivot_lower_bound=w.get('min_pivot_lower_bound'), proposal_eigs=w.get('proposal_eigs'),
                x0=m.get('x0'), log2_p0_lower=p0.get('log2_p0_lower'), log2_Z_upper=p0.get('log2_Z_upper'), burn_in_steps=bi.get('steps'), burn_in_beta=bi.get('beta'), checkpoints=cps, checkpoints_completed=len(done), certified_radius=(last or {}).get('radius'), worst_radius_certified=(last or {}).get('worst_radius'), recorded_at_last=(last or {}).get('N'), transitions_total=tr.get('total'), transitions_burn_in=tr.get('burn_in'), transitions_recorded=tr.get('recorded'), native_resolved=tr.get('native_resolved'), exact_fallbacks=tr.get('exact_fallbacks'), steps_per_second=rate, fast_path_share=((ds or {}).get('fast_path_share') if ds else (tr.get('native_resolved') / tr['total'] if tr.get('total') and tr.get('native_resolved') is not None else None)),
                rate_model=m.get('rate_model'), phases_s=ph, bytes=by, dev_stream=ds, Z_enclosure=d.get('Z_enclosure'), published=d.get('published'), K=d.get('K'), n_enclosures=len(d.get('enclosures') or []), defect=m.get('defect'), internal_error=m.get('internal_error'))

def cell_row(c):
    full, info = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}
    return dict(complete=bool(c.get('complete')), outcome=c.get('outcome'), receipt_outcome=c.get('receipt_outcome'), receipt_wall_s=c.get('receipt_wall_s'), solver_wall_s=c.get('solver_wall_s'), published=c.get('published'), K=c.get('K'), identity_ok=c.get('identity_ok'), hard_deadline_respected=c.get('hard_deadline_respected'), termination=c.get('termination'), seed=c.get('seed'), seed_index=c.get('seed_index', 0), reverse=c.get('reverse'), dir=os.path.relpath(c['_dir'], RD), worst_radius=(max(full) if full else None), median_radius=med(full), p90_radius=(float(np.percentile(full, 90)) if full else None), covered_at_eps=(sum(1 for w in full if w <= EPS) if full else None), inventory=info, ledger_identity=m.get('constructor_live_ledger_identity'), defect=(m.get('defect') or m.get('internal_error')), refusal=((m.get('refusal') or {}).get('kind') if isinstance(m.get('refusal'), dict) else m.get('refusal')), peak_rss_bytes=d.get('peak_rss_bytes'), heatbath=heatbath_status(c), archived_incumbent=c.get('archived_incumbent'))

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0), bool(c.get('confirm'))), {})[c['arm']] = cell_row(c)
    return by, cs

def forecast_radius(g, rate, Q, work_s, witness_s, burn_in_steps, delta=DELTA, n_checkpoints=N_CHECKPOINTS):
    """the frozen forecast (PROTOCOL section 6 / FREEZE release.forecast): N = rate x (work - witness - burn-in / rate - reserve); r = sqrt((2 - g) ln(2 Q / delta_j) / (2 N g)), delta_j = (delta / 2) / n_checkpoints (floats; a FORECAST, never a certificate)"""
    if not (isinstance(g, (int, float)) and g > 0 and isinstance(rate, (int, float)) and rate > 0 and Q): return None
    N = rate * (work_s - (witness_s or 0) - (burn_in_steps or 0) / rate - RESERVE_S)
    if N <= 0: return dict(N=0, radius=None, note='no sampling time left after witness + burn-in')
    dj = (delta / 2) / n_checkpoints; r = math.sqrt((2 - g) * math.log(2 * Q / dj) / (2 * N * g)); return dict(N=N, radius=r, completes=(r <= EPS), delta_j=dj)

def analyze():
    man, tp = panels(); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code'].get('commit'), freeze_sha256=(sha(os.path.join(RD, 'FREEZE.json')) if os.path.exists(os.path.join(RD, 'FREEZE.json')) else None), tables={}, completions_by_sub={}, verdict_inputs={})
    meta = {}
    for p in tp.values():
        for t in p: meta.setdefault(t['name'], t)
    stage_a = tp.get('stage_a_16', []); guard_tasks = tp.get('guard', []); names_a = [t['name'] for t in stage_a]
    for sub in SUBS:
        by, cs = table(sub)
        if not cs: continue
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], confirm=k[2], family=(meta.get(k[0], {}).get('family') or meta.get(k[0], {}).get('topology')), coupling=meta.get(k[0], {}).get('coupling'), n=meta.get(k[0], {}).get('n'), card=meta.get(k[0], {}).get('card'), role=meta.get(k[0], {}).get('role'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], names_a.index(kv[0][0]) if kv[0][0] in names_a else 999, kv[0][0]))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- Stage A feasibility table (one row per exposed input; the HEATBATH_SCREEN cell carries the witness + the development stream)
    screen = {r['task']: r['arms'] for r in res['tables'].get('screen', [])}; feas = []
    for t in stage_a:
        name = t['name']; inc = t.get('archived_incumbent') or {}; cell = (screen.get(name) or {}).get('HEATBATH_SCREEN') or (screen.get(name) or {}).get('SPECTRAL_HEATBATH'); hb = (cell or {}).get('heatbath') or {}
        Q = hb.get('K') or (cell or {}).get('K') or t.get('K'); g = hb.get('gap_g'); rate = hb.get('steps_per_second'); ws = hb.get('witness_seconds'); bi = hb.get('burn_in_steps')
        f20 = forecast_radius(g, rate, Q, WORK_S['main'], ws, bi) if hb.get('eligible') else None; f4 = forecast_radius(g, rate, Q, WORK_S['p4'], ws, bi) if hb.get('eligible') else None
        inc_r = inc.get('best_worst_radius'); cur_fail = inc.get('current_failure'); imp20 = ((inc_r / f20['radius']) if (f20 and f20.get('radius') and isinstance(inc_r, (int, float)) and f20['radius'] > 0) else None)
        feas.append(dict(task=name, n=t.get('n'), card=t.get('card'), family=t.get('family') or t.get('topology'), coupling=t.get('coupling'), role=t.get('role'), screened=bool(cell), outcome=(cell or {}).get('outcome'), eligible=hb.get('eligible'), refusal=hb.get('refusal_kind'), l=hb.get('l'), u=hb.get('u'), width=hb.get('width'), margin_m=hb.get('margin_m'), gap_g=g, dimension=hb.get('dimension'), witness_seconds=ws, witness_bytes=hb.get('witness_bytes'), min_pivot_lower_bound=hb.get('min_pivot_lower_bound'), proposal_eigs=hb.get('proposal_eigs'), log2_p0_lower=hb.get('log2_p0_lower'), burn_in_steps=bi, dev_steps_per_second=rate, fast_path_share=hb.get('fast_path_share'), exact_fallbacks=hb.get('exact_fallbacks'), dev_stream=hb.get('dev_stream'), Q=Q,
                         forecast_20s=f20, forecast_4s=f4, incumbent_best_worst_radius=inc_r, incumbent_best_cell=inc.get('best_cell'), incumbent_any_complete=inc.get('any_complete'), current_failure=cur_fail, forecast_improvement_20s=imp20, forecast_new_completion_20s=bool(f20 and f20.get('completes')), stage_b_candidate=bool(hb.get('eligible') and cur_fail and ((f20 and f20.get('completes')) or (imp20 is not None and imp20 >= 2.0))), cell_dir=(cell or {}).get('dir')))
    res['verdict_inputs']['stage_a'] = feas
    weak = [x for x in feas if x['coupling'] == 'half']; strong = [x for x in feas if x['coupling'] == 'two']
    adm = dict(screened=sum(1 for x in feas if x['screened']), of=len(feas), weak_eligible=[x['task'] for x in weak if x['eligible']], weak_refused=[x['task'] for x in weak if x['screened'] and not x['eligible']], strong_eligible=[x['task'] for x in strong if x['eligible']], strong_refused=[x['task'] for x in strong if x['screened'] and not x['eligible']], margins={x['task']: x['margin_m'] for x in feas if x['eligible']}, widths={x['task']: x['width'] for x in feas if x['screened']},
               status=('INCOMPLETE' if sum(1 for x in feas if x['screened']) < len(feas) else ('AS PREDICTED (weak eligible, strong refused)' if all(x['eligible'] for x in weak) and not any(x['eligible'] for x in strong) else 'DEVIATES FROM THE FLOATING PREDICTION')), rule='eligible iff the checked witness proves w = u - l < 2 (interval Cholesky with positive pivot lower bounds); refusal is typed and local; failure of width admission never proves slow mixing')
    res['verdict_inputs']['spectral_admission'] = adm
    # ---- guard table (Stage B)
    gt = {r['task']: r for r in res['tables'].get('guard', [])}; guard_rows = []
    for t in guard_tasks:
        name = t['name']; inc = t.get('archived_incumbent') or {}; inc_r = inc.get('best_worst_radius'); cur_fail = inc.get('current_failure'); fa = next((x for x in feas if x['task'] == name), {})
        per_seed = {}
        for r in res['tables'].get('guard', []):
            if r['task'] != name: continue
            A = r['arms']; hbc = A.get('SPECTRAL_HEATBATH'); hb = (hbc or {}).get('heatbath') or {}
            if hbc:
                ach = hbc.get('worst_radius'); imp = ((inc_r / ach) if (isinstance(inc_r, (int, float)) and isinstance(ach, (int, float)) and ach > 0) else None); f20 = fa.get('forecast_20s') or {}
                per_seed[r['seed_index']] = dict(dir=hbc['dir'], outcome=hbc['outcome'], complete=hbc['complete'], eligible=hb.get('eligible'), refusal=hb.get('refusal_kind'), worst_radius_achieved=ach, certified_radius=hb.get('certified_radius'), checkpoints_completed=hb.get('checkpoints_completed'), recorded=hb.get('transitions_recorded'), forecast_recorded=f20.get('N'), forecast_radius=f20.get('radius'), burn_in_steps=hb.get('burn_in_steps'), transitions_total=hb.get('transitions_total'), steps_per_second=hb.get('steps_per_second'), exact_fallbacks=hb.get('exact_fallbacks'), bytes=hb.get('bytes'), peak_rss_bytes=hbc.get('peak_rss_bytes'), elapsed_s=hbc.get('receipt_wall_s'), improvement=imp, gain_2x=bool(cur_fail and imp is not None and imp >= 2.0), new_completion=bool(cur_fail and hbc.get('complete')), defect=hbc.get('defect'), identity_ok=hbc.get('identity_ok'), receipt=hbc.get('receipt_outcome'), hard_deadline_respected=hbc.get('hard_deadline_respected'), phases_s=hb.get('phases_s'),
                                               REPAIRED=({k: (A['REPAIRED'] or {}).get(k) for k in ('complete', 'worst_radius', 'receipt_wall_s', 'outcome', 'dir')} if A.get('REPAIRED') else None), BASE=({k: (A['BASE'] or {}).get(k) for k in ('complete', 'worst_radius', 'receipt_wall_s', 'outcome', 'dir')} if A.get('BASE') else None))
        seeds = sorted(per_seed); both = (0 in per_seed and 1 in per_seed); safe = all((per_seed[s].get('receipt') == 'COMPLETED') and (per_seed[s].get('identity_ok') is not False) and (per_seed[s].get('hard_deadline_respected') is not False) and not per_seed[s].get('defect') for s in seeds)
        guard_rows.append(dict(task=name, role=t.get('role'), current_failure=cur_fail, incumbent_best_worst_radius=inc_r, incumbent_best_cell=inc.get('best_cell'), seeds=per_seed, both_seeds_run=both, gain_2x_both_seeds=bool(both and all(per_seed[s]['gain_2x'] for s in (0, 1))), new_completion_both_seeds=bool(both and all(per_seed[s]['new_completion'] for s in (0, 1))), no_safety_defect=safe, worst_radius_achieved_max=max([per_seed[s]['worst_radius_achieved'] for s in seeds if isinstance(per_seed[s].get('worst_radius_achieved'), (int, float))] or [None]) if seeds else None))
    res['verdict_inputs']['guard'] = guard_rows
    # ---- preservation (REPAIRED on the cohorts actually run) with intersections against the historical sets
    d7 = load(os.path.join(DGP7, 'RESULTS.json')) or {}; d6 = load(os.path.join(DGP6, 'RESULTS.json')) or {}
    hist7 = {sub: {r['task']: (r['arms'].get('REPAIRED') or {}).get('complete') for r in (d7.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}; hist24 = list((man.get('panels') or {}).get('historical_completions_24') or [])
    pres = {}
    for sub, hist in (('regression_18', hist7['preservation_18']), ('regression_13', hist7['preservation_13']), ('regression_24', {n: True for n in hist24})):
        rows = res['tables'].get(sub, []); ran = {r['task'] for r in rows if 'REPAIRED' in r['arms']}; comp = {r['task'] for r in rows if (r['arms'].get('REPAIRED') or {}).get('complete')}
        pres[sub] = dict(cohort_size=len(hist), ran=len(ran), complete=len(comp), intersection_with_historical_completions=sorted(ran & {n for n, v in hist.items() if v}), lost=sorted(n for n in ran if hist.get(n) and n not in comp), gained=sorted(n for n in comp if not hist.get(n)), not_run=sorted(n for n in hist if n not in ran), arms_run=sorted({a for r in rows for a in r['arms']}), status=('NOT RUN' if not rows else ('PRESERVED on the %d run of %d' % (len(ran), len(hist)) if not [n for n in ran if hist.get(n) and n not in comp] else 'REGRESSION')))
    res['verdict_inputs']['preservation'] = pres
    # ---- overhead: mutual completions REPAIRED vs SPECTRAL_HEATBATH (and BASE) across guard + regression subs
    cost = []
    for sub in ('guard', 'regression_18', 'regression_13', 'regression_24'):
        for r in res['tables'].get(sub, []):
            A = r['arms']; p = A.get('REPAIRED'); h = A.get('SPECTRAL_HEATBATH'); b = A.get('BASE')
            if p and h and p['complete'] and h['complete']: cost.append(dict(sub=sub, task=r['task'], seed_index=r['seed_index'], REPAIRED_s=p['receipt_wall_s'], HEATBATH_s=h['receipt_wall_s'], BASE_s=(b or {}).get('receipt_wall_s'), ratio=h['receipt_wall_s'] / p['receipt_wall_s'], flag=bool(h['receipt_wall_s'] - p['receipt_wall_s'] >= 0.1 and h['receipt_wall_s'] / p['receipt_wall_s'] >= 1.25)))
    res['verdict_inputs']['cost_mutual_completions'] = cost
    # ---- mechanism counts
    mc = {}
    for sub in SUBS:
        for r in res['tables'].get(sub, []):
            for arm, a in r['arms'].items():
                hb = a.get('heatbath')
                if hb is None: continue
                k = '%s/%s' % (sub, arm); m_ = mc.setdefault(k, dict(cells=0, eligible=0, refused=0, refusal_kinds={}, checkpoints_completed=0, cells_with_certificate=0, published_cells=0, recorded=[], rates=[], fallbacks=0, defects=0))
                m_['cells'] += 1; m_['eligible'] += int(bool(hb.get('eligible'))); m_['refused'] += int(bool(hb.get('refusal_kind'))); m_['refusal_kinds'][str(hb.get('refusal_kind'))] = m_['refusal_kinds'].get(str(hb.get('refusal_kind')), 0) + 1; m_['checkpoints_completed'] += (hb.get('checkpoints_completed') or 0); m_['cells_with_certificate'] += int((hb.get('checkpoints_completed') or 0) > 0); m_['published_cells'] += int((a.get('published') or 0) > 0); m_['fallbacks'] += (hb.get('exact_fallbacks') or 0); m_['defects'] += int(bool(hb.get('defect') or hb.get('internal_error')))
                if hb.get('transitions_recorded') is not None: m_['recorded'].append(hb['transitions_recorded'])
                if hb.get('steps_per_second'): m_['rates'].append(hb['steps_per_second'])
    for m_ in mc.values(): m_['recorded_median'] = med(m_['recorded']); m_['rate_median'] = med(m_['rates']); m_['recorded'] = len(m_['recorded']); m_['rates'] = len(m_['rates'])
    res['verdict_inputs']['mechanism_counts'] = mc
    # ---- verdicts
    rel = load(os.path.join(RD, 'RELEASE_DECISION.json')) or {}
    elig = [x for x in feas if x['eligible']]; ftc = dict(per_input={x['task']: dict(log2_p0_lower=x['log2_p0_lower'], burn_in_steps=x['burn_in_steps'], gap_g=x['gap_g'], forecast_radius_20s=((x['forecast_20s'] or {}).get('radius')), forecast_radius_4s=((x['forecast_4s'] or {}).get('radius'))) for x in elig}, guard_certified={g['task']: {s: dict(certified_radius=v.get('certified_radius'), checkpoints=v.get('checkpoints_completed'), recorded=v.get('recorded')) for s, v in g['seeds'].items()} for g in guard_rows}, status=('CERTIFIED at %d guard cells' % sum(1 for g in guard_rows for v in g['seeds'].values() if (v.get('checkpoints_completed') or 0) > 0)) if guard_rows else ('FORECAST ONLY (Stage B not run)' if elig else 'NO ELIGIBLE INPUT'))
    thr = dict(dev_rates={x['task']: x['dev_steps_per_second'] for x in feas if x['dev_steps_per_second']}, median_dev_rate=med([x['dev_steps_per_second'] for x in feas]), guard_rates={g['task']: {s: v.get('steps_per_second') for s, v in g['seeds'].items()} for g in guard_rows}, fast_path_share={x['task']: x['fast_path_share'] for x in feas if x['fast_path_share'] is not None}, exact_fallbacks_total=sum((x['exact_fallbacks'] or 0) for x in feas) + sum((v.get('exact_fallbacks') or 0) for g in guard_rows for v in g['seeds'].values()), status=('MEASURED (%d development streams)' % sum(1 for x in feas if x['dev_steps_per_second'])) if any(x['dev_steps_per_second'] for x in feas) else 'NOT MEASURED')
    pa_pass = [g['task'] for g in guard_rows if g['gain_2x_both_seeds'] and g['no_safety_defect']]; pa_any = [g['task'] for g in guard_rows if any(v['gain_2x'] for v in g['seeds'].values())]
    pa = dict(status=('PASS' if pa_pass else ('FAIL' if [g for g in guard_rows if g['current_failure'] and g['both_seeds_run']] else ('NOT RUN (Stage B not released)' if not guard_rows else 'INCOMPLETE'))), passing_both_seeds=pa_pass, passing_any_seed=pa_any, forecast_candidates=[x['task'] for x in feas if x['stage_b_candidate']], rule='>= 2x improvement of the worst certified radius on a current failure (archived best incumbent > 0.005) after all costs, in BOTH guard seeds, with no safety / resource defect')
    nc_pass = [g['task'] for g in guard_rows if g['new_completion_both_seeds']]; nc = dict(status=('PASS' if nc_pass else ('NONE' if guard_rows else 'NOT RUN')), tasks=nc_pass, any_seed=[g['task'] for g in guard_rows if any(v['new_completion'] for v in g['seeds'].values())], forecast=[x['task'] for x in feas if x['forecast_new_completion_20s']], rule='a published COMPLETE answer set at epsilon = 1/200 on a current failure under the original contract, both seeds')
    flags = [x for x in cost if x['flag']]; ov = dict(status=('FLAGGED' if flags else ('none' if cost else 'NO MUTUAL COMPLETION')), flags=[(x['sub'], x['task'], round(x['ratio'], 3)) for x in flags], n_mutual_completions=len(cost), median_ratio=med([x['ratio'] for x in cost]), rule='a mutual completion (REPAIRED and SPECTRAL_HEATBATH) exceeding both 1.25x and +0.1 s; new discovery, arithmetic, risk allocation and memory retention all count')
    res['verdicts'] = dict(validity='see VALIDATION.json + controls/qual (identity_ok on every cell; the witness is a proof; kernel exactness qualified; before / after probes of the seven findings; D1-D71+ and the accepted suites); the supplied references / review / packet are ABSENT (INCOMPLETE qualification inputs, never claimed)', spectral_admission=adm, finite_time_confidence=ftc, throughput=thr, partial_accuracy=pa, new_completion=nc, preservation=dict(status=('; '.join('%s: %s' % (k, v['status']) for k, v in pres.items()) if pres else 'NOT RUN'), cohorts=pres, rule='the repaired engine (REPAIRED) keeps every historical completion on the cohorts actually run; intersections reported explicitly; unrun cells are never implied preserved'), overhead=ov,
                           deployability=dict(status='standalone prototype only (SELECT NOT RUN: no frozen request-level risk allocation across the primary PAC route and the heat-bath route this round); no default integration', release=rel), mechanism_counts=mc)
    res['release_decision'] = rel
    json.dump(dict(utc=res['utc'], stage_a=feas, guard=guard_rows, spectral_admission=adm, units='l, u = checked spectral bounds of the centered one-hot log-interaction matrix A (natural logs); width w = u - l; margin m = 1 - w / 2; gap g = m / n (absolute spectral gap lower bound of random-scan heat-bath); radii = half-widths of the certified marginal intervals on the full inventory (0.5 for absent coordinates); forecast radii are floats from the frozen rate model, never certificates'), open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP8_LEDGER.jsonl'))] if os.path.exists(os.path.join(RD, 'DGP8_LEDGER.jsonl')) else []; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json')) or {}
    ch = dict(utc=res['utc'], ceiling_s=bud.get('ceiling_s'), allocation_s=bud.get('allocations'), reassignments=bud.get('reassignments'), by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), by_outcome={o: sum(1 for r in rc if r['outcome'] == o) for o in sorted({r['outcome'] for r in rc})}, within_ceiling=(sum(r['wall_s'] for r in rc) <= (bud.get('ceiling_s') or 1e18)), ledger='DGP8_LEDGER.jsonl', spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r.get('jid') == s['jid'] for r in rc)], implementation_labor='reported separately in controls/UNSUPERVISED_DEV_LOG.md (not charged)')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, contract, gate_ok, gate_reason):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, contract=contract, gated=(not gate_ok), gate_reason=(None if gate_ok else gate_reason)))
    sb = bool(rel.get('stage_b_released')); rg = bool(rel.get('regression_released')); failing = [t['name'] for t in guard_tasks if t.get('role') == 'eligible_failing_anchor']
    plan('screen', names_a, ['HEATBATH_SCREEN'], [0], 'main', True, None); plan('guard', [t['name'] for t in guard_tasks], ['SPECTRAL_HEATBATH'], [0, 1], 'main', sb, 'Stage B not released'); plan('guard', failing, ['REPAIRED'], [0], 'main', sb, 'Stage B not released')
    plan('regression_18', [t['name'] for t in tp.get('preservation_18', [])], ['REPAIRED'], [0], 'p4', rg or bool(res['tables'].get('regression_18')), 'regression not released'); plan('regression_13', [t['name'] for t in tp.get('preservation_13', [])], ['REPAIRED'], [0], 'p20', rg, 'regression not released'); plan('regression_24', hist24, ['REPAIRED'], [0], 'main', rg, 'regression not released')
    actual = {}
    for sub in SUBS:
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0))] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'])); p['reason'] = None if p['actual'] else (p['gate_reason'] or 'not run (see REPORT.md: budget / blocked)')
    json.dump(dict(utc=res['utc'], code_commit=fr['code'].get('commit'), release=rel, planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), n_gated=sum(1 for p in planned if p['gated'] and not p['actual']), unplanned_actual=[k for k in actual if not any((p['sub'], p['task'], p['arm'], p['seed_index']) == k for p in planned)], superseding_links=('see ' + ', '.join(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json'))) if glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')) else 'none'), cells_joined_by='model_sha256 + evid_sha256 + contract (names resolved from MODEL_MANIFEST by model_sha256)'), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], admission=adm['status'], eligible=adm['weak_eligible'], strong_eligible=adm['strong_eligible'], stage_b_candidates=pa['forecast_candidates'], partial_accuracy=pa['status'], new_completion=nc['status'], preservation=res['verdicts']['preservation']['status'], overhead=ov['status']), default=str)[:1600])
    return res

def release_decision():
    """RELEASE_DECISION.json from the frozen rule (PROTOCOL section 6; FREEZE release): stage_b iff Stage A forecasts a new completion or >= 2x on a current failure; regression iff a guard gain survives both seeds without a safety / resource defect"""
    R = load(os.path.join(RD, 'RESULTS.json')); vi = R['verdict_inputs']; feas = vi['stage_a']; guard = vi.get('guard') or []
    cands = [x['task'] for x in feas if x['stage_b_candidate']]; cur = [x['task'] for x in feas if x['current_failure']]; screened = [x['task'] for x in feas if x['screened']]
    stage_b = bool(cands) and len(screened) == len(feas); gain = [g['task'] for g in guard if g['gain_2x_both_seeds'] and g['no_safety_defect']]; newc = [g['task'] for g in guard if g['new_completion_both_seeds'] and g['no_safety_defect']]; regression = bool(gain or newc)
    prev = load(os.path.join(RD, 'RELEASE_DECISION.json')) or {}
    out = dict(stage_b_released=stage_b, stage_b_decision=('RELEASED: Stage A forecasts %s on %s' % ('a new completion or >= 2x worst-radius improvement', cands) if stage_b else ('NOT RELEASED: no eligible current failure forecasts a new completion or a >= 2x improvement (screened %d of %d; candidates %s)' % (len(screened), len(feas), cands))), stage_b_numerator=len(cands), stage_b_denominator=dict(current_failures=len(cur), eligible=sum(1 for x in feas if x['eligible']), screened=len(screened), of=len(feas)), forecast_candidates=cands, current_failures=cur,
               regression_released=regression if guard else prev.get('regression_released', False), regression_decision=(('RELEASED: a guard gain survives both seeds with no safety / resource defect on %s' % sorted(set(gain + newc))) if (guard and regression) else ('NOT RELEASED: no guard gain survives both seeds (gain_2x both seeds: %s; new completion both seeds: %s; safety defects: %s)' % (gain, newc, [g['task'] for g in guard if not g['no_safety_defect']]) if guard else 'NOT DECIDED (guard not run)')), regression_numerator=len(set(gain + newc)), regression_denominator=dict(guard_tasks=len(guard), current_failures_in_guard=sum(1 for g in guard if g['current_failure'])),
               rule='PROTOCOL.md section 6: Stage B iff a credible new completion under the original contract or >= 2x improvement in worst certified radius on a current failure after all costs is FORECAST from the frozen rate model and the checked gap; the regression iff the guard gain survives BOTH seeds with no safety / resource defect; no policy tuning on scored outcomes; a lack of release is a valid result', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(out, open(os.path.join(RD, 'RELEASE_DECISION.json'), 'w'), indent=1); print(json.dumps({k: out[k] for k in ('stage_b_released', 'stage_b_numerator', 'stage_b_denominator', 'regression_released', 'regression_numerator')}))

def report():
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
    def f3(x): return ('%.3f' % x) if isinstance(x, (int, float)) else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
    def fe(x): return ('%.3g' % x) if isinstance(x, (int, float)) else '-'
    vi = R['verdict_inputs']; V = R['verdicts']; rel = R.get('release_decision') or {}
    P('# DGP8 -- REPORT (derived by dgp8_analyze.py from the raw cells, manifests and the ledger)'); P(); P('Frozen code: pgm %s (tree %s). Analyzer utc %s. Every count below is recomputed from `runs/*/*/cell.json`, `MODEL_MANIFEST.json` and `DGP8_LEDGER.jsonl`. Forecast radii are floats from the frozen rate model and the checked gap, never certificates; no unrun cell is a failure or a confirmation.' % ((fr['code'].get('commit') or '')[:9], (fr['code'].get('tree') or '')[:9], R['utc'])); P()
    P('## 1. Verdicts (kept separate)'); P(); P('| verdict | status | basis |'); P('|---|---|---|')
    P('| validity | see VALIDATION.json | %d / %d cells identity_ok; %s |' % (sum(v['by_arm'][a]['identity_ok'] for v in R['completions_by_sub'].values() for a in v['by_arm']), sum(v['cells'] for v in R['completions_by_sub'].values()), V['validity'][:200]))
    a_ = V['spectral_admission']; P('| spectral admission | **%s** | screened %s of %s; weak eligible %s; weak refused %s; strong eligible %s; strong refused %s |' % (a_['status'], a_['screened'], a_['of'], a_['weak_eligible'], a_['weak_refused'], a_['strong_eligible'], a_['strong_refused']))
    P('| finite-time confidence | %s | %s |' % (V['finite_time_confidence']['status'], json.dumps(V['finite_time_confidence'].get('guard_certified'), default=str)[:300]))
    t_ = V['throughput']; P('| throughput | %s | median development rate %s steps / s; fast-path share %s; exact fallbacks %s |' % (t_['status'], fe(t_['median_dev_rate']), json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in (t_['fast_path_share'] or {}).items()})[:200], t_['exact_fallbacks_total']))
    pa = V['partial_accuracy']; P('| partial accuracy (>= 2x worst radius on a current failure, both seeds) | **%s** | passing both seeds %s; any seed %s; Stage A forecast candidates %s |' % (pa['status'], pa['passing_both_seeds'], pa['passing_any_seed'], pa['forecast_candidates']))
    nc = V['new_completion']; P('| new completion | **%s** | both seeds %s; any seed %s; forecast %s |' % (nc['status'], nc['tasks'], nc['any_seed'], nc['forecast']))
    P('| preservation (repaired engine) | **%s** | %s |' % (V['preservation']['status'], json.dumps({k: dict(ran=v['ran'], complete=v['complete'], lost=v['lost'], not_run=len(v['not_run'])) for k, v in (V['preservation']['cohorts'] or {}).items()}, default=str)[:400]))
    ov = V['overhead']; P('| overhead | %s | flags %s on %d mutual completions; median HEATBATH / REPAIRED wall %s |' % (ov['status'], ov['flags'], ov['n_mutual_completions'], f2(ov['median_ratio'])))
    P('| deployability | %s | release: stage B %s; regression %s |' % (V['deployability']['status'][:80], rel.get('stage_b_released'), rel.get('regression_released'))); P()
    P('## 2. Stage A feasibility matrix (16 exposed dense inputs; HEATBATH_SCREEN = checked witness + a predeclared 2.0 s development stream)'); P()
    P('| input | role | screened | eligible | l | u | width | margin m | gap g | dim | witness s | burn-in steps | dev steps/s | fast share | forecast r (20 s) | forecast r (4 s) | incumbent worst r | incumbent cell | current failure | forecast improvement | Stage B candidate |'); P('|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|')
    for x in vi['stage_a']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], (x['role'] or '')[:22], x['screened'], x['eligible'] if x['screened'] else (x['refusal'] or '-'), f4(x['l']), f4(x['u']), f4(x['width']), f4(x['margin_m']), fe(x['gap_g']), x['dimension'], f3(x['witness_seconds']), x['burn_in_steps'], fe(x['dev_steps_per_second']), f3(x['fast_path_share']), f4((x['forecast_20s'] or {}).get('radius')), f4((x['forecast_4s'] or {}).get('radius')), f4(x['incumbent_best_worst_radius']), x['incumbent_best_cell'], x['current_failure'], f2(x['forecast_improvement_20s']), x['stage_b_candidate']))
    P(); P('Release decision: %s / %s' % (rel.get('stage_b_decision', 'not decided'), rel.get('regression_decision', 'not decided'))); P()
    P('## 3. Stage B guard cells (SPECTRAL_HEATBATH x seeds 0 / 1; REPAIRED / BASE comparators)'); P(); P('| input | role | seed | outcome | eligible | worst r achieved | certified r | checkpoints | recorded N | forecast N | burn-in | steps/s | fallbacks | elapsed s | REPAIRED worst r / s | BASE worst r / s | incumbent worst r | improvement | 2x gain | new completion | safety |'); P('|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---|---|---|')
    for g in vi['guard']:
        for s, v in sorted(g['seeds'].items()): P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s | %s / %s | %s | %s | %s | %s | %s |' % (g['task'], (g['role'] or '')[:22], s, v['outcome'], v['eligible'] if v['eligible'] is not None else (v['refusal'] or '-'), f4(v['worst_radius_achieved']), f4(v['certified_radius']), v['checkpoints_completed'], v['recorded'], fe(v['forecast_recorded']), v['burn_in_steps'], fe(v['steps_per_second']), v['exact_fallbacks'], f2(v['elapsed_s']), f4((v.get('REPAIRED') or {}).get('worst_radius')), f2((v.get('REPAIRED') or {}).get('receipt_wall_s')), f4((v.get('BASE') or {}).get('worst_radius')), f2((v.get('BASE') or {}).get('receipt_wall_s')), f4(g['incumbent_best_worst_radius']), f2(v['improvement']), v['gain_2x'], v['new_completion'], 'ok' if not v.get('defect') else str(v.get('defect'))[:40]))
    if not vi['guard']: P('- not run (Stage B not released)')
    P(); P('## 4. Preservation (REPAIRED on the cohorts actually run; intersections explicit)'); P()
    for k, v in (vi.get('preservation') or {}).items(): P('- %s: cohort %d, ran %d, complete %d, lost %s, gained %s, not run %d -> %s' % (k, v['cohort_size'], v['ran'], v['complete'], v['lost'], v['gained'], len(v['not_run']), v['status']))
    P(); P('## 5. Mutual completions: cost'); P(); P('| sub | input | seed | REPAIRED s | HEATBATH s | BASE s | ratio | flag |'); P('|---|---|---|---:|---:|---:|---:|---|')
    for x in vi['cost_mutual_completions']: P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (x['sub'], x['task'], x['seed_index'], f2(x['REPAIRED_s']), f2(x['HEATBATH_s']), f2(x['BASE_s']), f2(x['ratio']), 'FLAG' if x['flag'] else ''))
    if not vi['cost_mutual_completions']: P('- none')
    P(); P('## 6. Mechanism counts'); P(); P(json.dumps(vi['mechanism_counts'], default=str)[:1500]); P()
    P('## 7. Charges'); P(); ch = R['charges']; P('Total %.1f s of the %s s ceiling (%d receipts; %s). By scope: %s. Reassignments: %s. Launches without a receipt: %s.' % (ch['total_s'], ch['ceiling_s'], ch['n_receipts'], json.dumps(ch['by_outcome']), json.dumps(ch['by_scope_s']), json.dumps(ch.get('reassignments'), default=str)[:400], ch.get('spawned_without_receipt'))); P()
    P('## 8. Limitations'); P(); P('- The spectral condition w < 2 is sufficient, never necessary: a refusal by width admission does not prove slow mixing; the strong dense wall is not addressed by this route.'); P('- The finite-sample radius uses the conservative Leon-Perron / union-bound / burn-in-coupling chain at frozen checkpoints; empirical autocorrelation or effective sample size never replaces it.'); P('- Forecast radii combine the checked gap with a MEASURED development rate (2.0 s streams); they are scheduling heuristics, not certificates and not impossibility statements.'); P('- The route certifies marginals and conditional queries only; it never claims Z accuracy (Z_enclosure stays the available bound or unknown).'); P('- Archived incumbents are hash-matched primary-seed cells of earlier rounds (different sample seeds); the contemporaneous REPAIRED / BASE comparators in the guard table are the same-session controls.'); P('- The supplied packet (references, review, probes) was absent: every reference here is independent and labelled so.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md written', len(L), 'lines')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'analyze'
    if cmd == 'analyze': analyze()
    elif cmd == 'release-decision': release_decision()
    elif cmd == 'report': report()
