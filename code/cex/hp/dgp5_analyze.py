"""DGP5 committed analyzer (PROTOCOL.md sections 5-7; protocol rule 8): derives every count / table from the raw cells, oracle outputs and the ledger. Writes RESULTS.json (complete attempted matrix for BASE / REPAIRED / SEED / JOINT on the 60-task
main panel, the preservation panels (REPAIRED / JOINT), the eight-model CAP_ONLY / MOMENT_ONLY and FORCED_SEED / FORCED_JOINT diagnostics, confirmations; completion sets vs each other and vs the historical DGP4 set; original-coordinate accuracy on the FULL
query inventory; cost / overhead; mechanism counts offered / admitted / READY / sampled / published; per-epoch records), DIAGNOSTICS.json (per oracle model: seed law, first family, packets at V 1,024 / 4,096 / 16,384 with witness slack vs the exact
coefficients, the seed / cap-only / moment-only / joint-selected / retune / exact-coefficient / oracle-Z laws, replays, coincidence; the gates C / J / S / E / O; failure classes), RUN_MANIFEST.json, CHARGES.json, REPORT.md. usage: dgp5_analyze.py [select-confirm | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
import numpy as np
RD = os.environ.get('DGP5_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION'); DGP4 = os.path.join(os.path.dirname(RD), 'DGP4_RESIDUAL_MAX'); DGP1 = os.path.join(os.path.dirname(RD), 'DENSE_GENERIC_PAC_INTEGRATION_1')
ARMS = ['BASE', 'REPAIRED', 'SEED', 'JOINT']; DIAG_ARMS = ['CAP_ONLY', 'MOMENT_ONLY']; FORCED_ARMS = ['FORCED_SEED', 'FORCED_JOINT']; EPS = 0.005
FAILURE_CLASSES = ['no family headroom', 'loose MAX', 'loose SUM', 'poor scalar objective / Z proxy', 'quantization / floor cost', 'constructor cost', 'slow per-draw work', 'numerical floor', 'no useful normalizer information', 'policy / memory refusal', 'mechanism never executed', 'unresolved']
def load(p):
    try: return json.load(open(p))
    except Exception: return None
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def med(xs): xs = [x for x in (xs or []) if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))]; return float(statistics.median(xs)) if xs else None

_SHA_NAME = None
def sha_name_map():
    global _SHA_NAME
    if _SHA_NAME is None:
        man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); _SHA_NAME = {}
        for p in ('preservation_13', 'preservation_18', 'oracle_28', 'main_60'):
            for t in man['panels'][p]: _SHA_NAME[t['model_sha256']] = t['name']
    return _SHA_NAME

def cells_of(sub):
    out = []
    for p in sorted(glob.glob(os.path.join(RD, 'runs', sub, '*', 'cell.json'))):
        c = load(p)['cell']; c['_dir'] = os.path.dirname(p); c['_result'] = load(os.path.join(c['_dir'], 'result.json')); c['task_recorded'] = c['task']; c['task'] = sha_name_map().get(c.get('model_sha256'), c['task']); out.append(c)
    return out

def radii_full_inventory(c):
    """per ORIGINAL coordinate final radius on the FULL fixed query inventory: planner arms = enclosures (informative partial enclosures preserved) with 0.5 for every inventory coordinate without one; BASE = published rows, 0.5 otherwise (aggregate certificate widths assigned conservatively)"""
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
    keys = [(a['var'], a['state']) for a in rows] if rows else list(rad); base_cert = None
    if c['arm'] == 'BASE':
        m = d.get('mechanism') or {}
        if m.get('route') == 'pac' and m.get('max_remaining_width') is not None and m.get('max_remaining_width') < 1.0:
            base_cert = dict(max_remaining_width=m['max_remaining_width'], median_remaining_width=m.get('median_remaining_width'), note='BASE enclosures are not per coordinate: every unpublished coordinate is assigned the recorded MAX remaining half-width (conservative for BASE)')
            for k in keys:
                if k not in rad: rad[k] = m['max_remaining_width'] / 2
    full = [min(0.5, rad.get(k, 0.5)) for k in keys]; return full, dict(K=K, informative=sum(1 for k in keys if k in rad), deterministic_rows=sum(1 for a in rows if a.get('guarantee') in ('EXACT', 'DETERMINISTIC')), pac_rows=sum(1 for a in rows if a.get('guarantee') == 'PAC_EB'), base_certificate=base_cert)

def joint_status(c):
    """offered / admitted / READY / sampled / published + epochs / attempts of the joint stream of one planner cell (None for BASE)"""
    d = c['_result']
    if d is None or c['arm'] == 'BASE': return None
    m = d.get('mechanism') or {}; jo = m.get('joint_offer') or {}; J = [s for s in d.get('streams') or [] if s.get('kind') == 'joint']; mode = d.get('joint_mode')
    st = dict(mode=mode, offered=bool(jo.get('created')) or any(x.get('joint_offer', {}).get('offered') for x in d.get('decisions', []) if x.get('joint_offer')), refused=jo.get('refused'), created=bool(J), ready=False, sampled=False, published=False, draws=0, pub=0, epochs=0, switches=0, attempts=[], pilot=None, closed=None, stage=None, refinement_ended=None, allowance_s=None, seed_s=None, construction_s=None, first_batch_t_s=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s')), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), lifted=[(s['label'][:30], s['stage'], s['draws']) for s in d.get('streams') or [] if s.get('kind') == 'lifted'])
    if J:
        s = J[0]; j = s.get('joint') or {}; sm = dict(s.get('mechanism') or {}); sm['seed'] = sm.get('seed') if isinstance(sm.get('seed'), dict) else {}      # HARNESS amendment 2: the integer RNG seed under mech['seed'] when the stream closed before its seed stage
        st.update(stage=s['stage'], closed=s.get('closed'), ready=(s['stage'] in ('READY', 'COMPLETE') or s['draws'] > 0), sampled=(s['draws'] > 0), draws=s['draws'], pub=s['published'], published=(s['published'] > 0 or any((x.get('var') is not None) for x in [])), epochs=len(j.get('epochs') or []), switches=j.get('epoch_switches') or 0, pilot=({k: j['pilot'].get(k) for k in ('status', 'draws', 'seconds', 'd_seed_s_per_draw', 'log2_Z_proxy_fit', 'log2_Z_proxy_heldout_DIAGNOSTIC')} if j.get('pilot') else None), refinement_ended=j.get('refinement_ended'), allowance_s=((j.get('allowance') or {}).get('total_s')), seed_s=((sm.get('seed') or {}).get('seconds')), seed=({k: (sm.get('seed') or {}).get(k) for k in ('stages_done', 'max_splits', 'owned_bytes', 'zero_rows', 'work_cells')} | dict(log2_B=((sm.get('seed') or {}).get('proposal') or {}).get('log2_B_W0'))), eps_num=sm.get('eps_num'), log2_X_mean=(math.log2(s['X_mean']) if s.get('X_mean') else None), max_log2_X=s.get('max_log2_X_observed'), ESS=s.get('ESS_DIAGNOSTIC'), t_prep=s.get('t_prep'), t_sample=s.get('t_sample'), t_cert=s.get('t_cert'), retained_bytes=s.get('retained_bytes'), joint_bytes=j.get('joint_bytes'), defect=sm.get('certificate_defect') or sm.get('construction_defect') or sm.get('candidate_defect'),
                  attempts=[dict(status=a.get('status'), kind=a.get('kind'), why=(a.get('why') or '')[:100], winner=a.get('winner'), promoted=a.get('promoted'), payback=(a.get('payback') or {}).get('passed'), ratio_J=(a.get('payback') or {}).get('ratio_J'), ratio_T=(a.get('payback') or {}).get('ratio_T'), seconds=a.get('seconds'), family=a.get('family'), log2_Cmin=a.get('log2_Cmin'), incumbent={k: (a.get('incumbent') or {}).get(k) for k in ('log2_B', 'log2_S', 'log2_J')}, winner_B=next((c_.get('log2_B') for c_ in (a.get('candidates') or []) if c_.get('label') == a.get('winner')), None), winner_S=next((c_.get('log2_S') for c_ in (a.get('candidates') or []) if c_.get('label') == a.get('winner')), None), n_candidates=len(a.get('candidates') or []), rejected=len(a.get('rejected_rows') or []), heldout=a.get('heldout_offpolicy'), packet_seconds=((a.get('packet') or {}).get('seconds')), packet_bytes=((a.get('packet') or {}).get('owned_bytes'))) for a in j.get('attempts') or []],
                  epoch_records=[dict(index=e.get('index'), reason=e.get('reason'), draws_from=e.get('draws_from'), draws_to=e.get('draws_to'), log2_B=((e.get('proposal') or {}).get('log2_B_W0')), log2_S=((e.get('proposal') or {}).get('log2_S_W0sq')), eps_num=e.get('eps_num_epoch'), conditionals=[(c_['z'], c_['parents'], c_['volume']) for c_ in ((e.get('proposal') or {}).get('conditionals') or [])][:8], committed_offset_s=e.get('committed_offset_s'), Z_epoch=e.get('Z_epoch')) for e in j.get('epochs') or []])
        st['construction_s'] = (st['seed_s'] or 0) + sum((a.get('seconds') or 0) for a in st['attempts']) + ((st['pilot'] or {}).get('seconds') or 0)
    return st

def cell_row(c):
    full, info = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}
    row = dict(complete=bool(c.get('complete')), outcome=c.get('outcome'), receipt_outcome=c.get('receipt_outcome'), receipt_wall_s=c.get('receipt_wall_s'), solver_wall_s=c.get('solver_wall_s'), published=c.get('published'), K=c.get('K'), identity_ok=c.get('identity_ok'), hard_deadline_respected=c.get('hard_deadline_respected'), termination=c.get('termination'), seed=c.get('seed'), dir=os.path.relpath(c['_dir'], RD),
               worst_radius=(max(full) if full else None), median_radius=med(full), p90_radius=(float(np.percentile(full, 90)) if full else None), covered_at_eps=(sum(1 for w in full if w <= EPS) if full else None), inventory=info, ledger_identity=m.get('constructor_live_ledger_identity'), defect=m.get('defect'), refusal=(m.get('refusal') or {}).get('kind') if isinstance(m.get('refusal'), dict) else m.get('refusal'), time_to_first_batch=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s')), joint=joint_status(c))
    return row

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0), c['confirm']), {})[c['arm']] = cell_row(c)
    return by, cs

def final_worst(rep):
    """[(seed, worst, covered, K, contains)] from the LAST checkpoint of each seed of a replay_fine_law record"""
    out = []
    for s_, v in sorted(((rep or {}).get('seeds') or {}).items(), key=lambda kv: int(kv[0])):
        ch = (v.get('checkpoints') or [])
        if ch: out.append(dict(seed=int(s_), worst=ch[-1]['worst_radius'], median=ch[-1]['median_radius'], covered=ch[-1]['covered'], K=ch[-1]['K'], contains_truth=ch[-1].get('contains_truth'), draws=ch[-1]['draws']))
        else: out.append(dict(seed=int(s_), censored=v.get('censored')))
    return out

def analyze():
    man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); fr = load(os.path.join(RD, 'FREEZE.json')); res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code']['commit'], freeze_sha256=sha(os.path.join(RD, 'FREEZE.json')), tables={}, completions_by_sub={}, verdict_inputs={})
    PANEL_OF = {'main': 'main_60', 'preservation_18': 'preservation_18', 'preservation_13': 'preservation_13', 'diag': 'main_60', 'forced': 'main_60', 'confirm': 'main_60'}
    meta_panel = {p: {t['name']: t for t in man['panels'][p]} for p in ('main_60', 'preservation_18', 'preservation_13', 'oracle_28')}; meta = {}
    for p in ('oracle_28', 'preservation_13', 'preservation_18', 'main_60'): meta.update(meta_panel[p])
    for sub in ('main', 'preservation_18', 'preservation_13', 'diag', 'forced', 'confirm'):
        by, cs = table(sub)
        if not cs: continue
        mp = meta_panel[PANEL_OF[sub]]; order_names = [t['name'] for t in man['panels'][PANEL_OF[sub]]]
        if sub == 'confirm': mp = dict(meta_panel['preservation_18'], **meta_panel['main_60']); order_names = order_names + [t['name'] for t in man['panels']['preservation_18']]
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], confirm=k[2], topology=(mp.get(k[0]) or meta.get(k[0], {})).get('topology') or (mp.get(k[0]) or meta.get(k[0], {})).get('family'), panel=(mp.get(k[0]) or meta.get(k[0], {})).get('panel'), exposure=(mp.get(k[0]) or meta.get(k[0], {})).get('exposure'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], order_names.index(kv[0][0]) if kv[0][0] in order_names else 999))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- historical comparator: the DGP4 main set (BASE = REPAIRED = NEW: the 20 historical completions) by name (the 52 inputs are byte-identical; names identical in DGP4's MODEL_MANIFEST)
    d4 = load(os.path.join(DGP4, 'RESULTS.json')) or {}; hist4 = {r['task']: r['arms'] for r in (d4.get('tables') or {}).get('main', [])}; hist4_complete = sorted(t for t, a in hist4.items() if (a.get('NEW') or {}).get('complete'))
    hist4_pres = {sub: {r['task']: (r['arms'].get('NEW') or {}).get('complete') for r in (d4.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}
    em = res['tables'].get('main', []); comp = {a: sorted(r['task'] for r in em if r['arms'].get(a, {}).get('complete')) for a in ARMS}; is_fresh = lambda t: meta.get(t, {}).get('panel') == 'fresh_8'; is_dense = lambda t: meta.get(t, {}).get('topology') in ('er50', 'clique')
    mi = dict(n_tasks=len(em), complete=comp, n_complete={a: len(comp[a]) for a in ARMS}, dense_complete={a: len([t for t in comp[a] if is_dense(t)]) for a in ARMS}, fresh_complete={a: sorted(t for t in comp[a] if is_fresh(t)) for a in ARMS}, historical_DGP4_complete=sorted(t for t in hist4_complete if t in {r['task'] for r in em}),
              JOINT_not_SEED=sorted(set(comp['JOINT']) - set(comp['SEED'])), SEED_not_JOINT=sorted(set(comp['SEED']) - set(comp['JOINT'])), SEED_not_REPAIRED=sorted(set(comp['SEED']) - set(comp['REPAIRED'])), REPAIRED_not_SEED=sorted(set(comp['REPAIRED']) - set(comp['SEED'])), JOINT_not_REPAIRED=sorted(set(comp['JOINT']) - set(comp['REPAIRED'])), REPAIRED_not_JOINT=sorted(set(comp['REPAIRED']) - set(comp['JOINT'])), JOINT_not_BASE=sorted(set(comp['JOINT']) - set(comp['BASE'])), BASE_not_JOINT=sorted(set(comp['BASE']) - set(comp['JOINT'])),
              JOINT_vs_DGP4=dict(lost=sorted(set(hist4_complete) & {r['task'] for r in em} - set(comp['JOINT'])), gained=sorted(set(comp['JOINT']) - set(hist4_complete) - {t for t in comp['JOINT'] if is_fresh(t)})), identical_sets_all_four=(len({tuple(comp[a]) for a in ARMS}) == 1), new_dense_completion_candidates=sorted(t for t in set(comp['JOINT']) | set(comp['SEED']) if is_dense(t) and t not in set(comp['REPAIRED']) and t not in set(comp['BASE'])))
    res['verdict_inputs']['main'] = mi
    acc = []; cost = []
    for r in em:
        A = r['arms']; b = A.get('BASE'); p = A.get('REPAIRED'); s = A.get('SEED'); j = A.get('JOINT')
        if not (p and s and j): continue
        if not j['complete'] and not s['complete']:
            rj, rs, rp, rb = j['worst_radius'], s['worst_radius'], p['worst_radius'], (b or {}).get('worst_radius')
            acc.append(dict(task=r['task'], topology=r['topology'], fresh=is_fresh(r['task']), BASE_worst=rb, REPAIRED_worst=rp, SEED_worst=rs, JOINT_worst=rj, ratio_SEED_over_JOINT=(rs / rj if rs is not None and rj not in (None, 0) else None), ratio_REPAIRED_over_SEED=(rp / rs if rp is not None and rs not in (None, 0) else None), ratio_REPAIRED_over_JOINT=(rp / rj if rp is not None and rj not in (None, 0) else None), material_2x_JOINT_vs_REPAIRED=bool(rp is not None and rj not in (None, 0) and rp / rj >= 2 and rp >= 0.5 * 0 and not (rp == 0.5 and rj == 0.5)), material_2x_JOINT_vs_BASE=bool(rb is not None and rj not in (None, 0) and rb / rj >= 2), material_2x_SEED_vs_REPAIRED=bool(rp is not None and rs not in (None, 0) and rp / rs >= 2), JOINT_covered=j['covered_at_eps'], SEED_covered=s['covered_at_eps'], REPAIRED_covered=p['covered_at_eps'], K=j['K'], joint_mech=(j.get('joint') or {}), seed_mech=(s.get('joint') or {})))
        if p['complete'] and j['complete']:
            slower = (j['receipt_wall_s'] - p['receipt_wall_s']); cost.append(dict(task=r['task'], BASE_s=(b or {}).get('receipt_wall_s'), REPAIRED_s=p['receipt_wall_s'], SEED_s=s['receipt_wall_s'], JOINT_s=j['receipt_wall_s'], ratio_JOINT_over_REPAIRED=j['receipt_wall_s'] / p['receipt_wall_s'], flag_slower=bool(slower >= 0.1 and j['receipt_wall_s'] / p['receipt_wall_s'] >= 1.25), JOINT_first_batch=j.get('time_to_first_batch'), REPAIRED_first_batch=p.get('time_to_first_batch'), JOINT_construction_s=((j.get('joint') or {}).get('construction_s')), SEED_construction_s=((s.get('joint') or {}).get('construction_s'))))
    res['verdict_inputs']['accuracy_mutual_failures'] = acc; res['verdict_inputs']['cost_mutual_completions'] = cost
    for sub in ('preservation_18', 'preservation_13'):
        rows = res['tables'].get(sub, []); h4 = hist4_pres.get(sub, {})
        res['verdict_inputs'][sub] = {a: dict(complete=sum(1 for r in rows if r['arms'].get(a, {}).get('complete')), n=len(rows), regressions_vs_DGP4=sorted(r['task'] for r in rows if h4.get(r['task']) and not r['arms'].get(a, {}).get('complete')), offered=sum(1 for r in rows if (r['arms'].get(a, {}).get('joint') or {}).get('offered')), created=sum(1 for r in rows if (r['arms'].get(a, {}).get('joint') or {}).get('created')), sampled=sum(1 for r in rows if (r['arms'].get(a, {}).get('joint') or {}).get('sampled'))) for a in ('REPAIRED', 'JOINT')}
        res['verdict_inputs'][sub]['historical_complete'] = sum(1 for v in h4.values() if v); res['verdict_inputs'][sub]['JOINT_not_REPAIRED'] = sorted(r['task'] for r in rows if r['arms'].get('JOINT', {}).get('complete') and not r['arms'].get('REPAIRED', {}).get('complete')); res['verdict_inputs'][sub]['REPAIRED_not_JOINT'] = sorted(r['task'] for r in rows if r['arms'].get('REPAIRED', {}).get('complete') and not r['arms'].get('JOINT', {}).get('complete'))
    # diagnostics panels (CAP_ONLY / MOMENT_ONLY; FORCED_SEED / FORCED_JOINT)
    diag_rows = []
    for sub in ('diag', 'forced'):
        for r in res['tables'].get(sub, []):
            for arm, a in r['arms'].items():
                jm = a.get('joint') or {}; mainrow = next((x['arms'] for x in em if x['task'] == r['task']), {})
                diag_rows.append(dict(sub=sub, task=r['task'], arm=arm, outcome=a['outcome'], receipt_wall_s=a['receipt_wall_s'], worst_radius=a['worst_radius'], covered=a['covered_at_eps'], K=a['K'], created=jm.get('created'), ready=jm.get('ready'), sampled=jm.get('sampled'), draws=jm.get('draws'), epochs=jm.get('epochs'), switches=jm.get('switches'), attempts=jm.get('attempts'), pilot=jm.get('pilot'), refinement_ended=jm.get('refinement_ended'), log2_X_mean=jm.get('log2_X_mean'), seed=jm.get('seed'), closed=jm.get('closed'), defect=jm.get('defect'), main_SEED_worst=(mainrow.get('SEED') or {}).get('worst_radius'), main_JOINT_worst=(mainrow.get('JOINT') or {}).get('worst_radius'), main_REPAIRED_worst=(mainrow.get('REPAIRED') or {}).get('worst_radius')))
    res['verdict_inputs']['diagnostics'] = diag_rows
    # mechanism counts over every planner cell of every panel
    mech = {}
    for sub in ('main', 'preservation_18', 'preservation_13', 'diag', 'forced', 'confirm'):
        for r in res['tables'].get(sub, []):
            for arm, a in r['arms'].items():
                jm = a.get('joint')
                if jm is None: continue
                k = (sub, arm); m_ = mech.setdefault(k, dict(cells=0, offered=0, created=0, ready=0, sampled=0, published=0, switched=0, refused_threshold=0, refused_admission=0, closed_before_ready=0, pilot_complete=0, attempts=0, promoted=0, payback_passed=0))
                m_['cells'] += 1; m_['offered'] += int(bool(jm.get('offered'))); m_['created'] += int(bool(jm.get('created'))); m_['ready'] += int(bool(jm.get('ready'))); m_['sampled'] += int(bool(jm.get('sampled'))); m_['published'] += int((jm.get('pub') or 0) > 0); m_['switched'] += int((jm.get('switches') or 0) > 0)
                m_['refused_threshold'] += int(str(jm.get('refused') or '').startswith('OFFER_THRESHOLD')); m_['refused_admission'] += int(str(jm.get('refused') or '').startswith('ADMISSION')); m_['closed_before_ready'] += int(bool(jm.get('created')) and not jm.get('ready')); m_['pilot_complete'] += int(((jm.get('pilot') or {}).get('status')) == 'COMPLETE'); m_['attempts'] += len(jm.get('attempts') or []); m_['promoted'] += sum(1 for x in (jm.get('attempts') or []) if x.get('promoted')); m_['payback_passed'] += sum(1 for x in (jm.get('attempts') or []) if x.get('payback'))
    res['verdict_inputs']['mechanism_counts'] = {'%s/%s' % k: v for k, v in mech.items()}
    # ---- oracle diagnostics
    diag = dict(utc=res['utc'], oracle=[], units='W_0 = canonical target WITHOUT the scalar; Z_0 = Z / scalar; R* = max_x W_0 / q (tight cap of a law); B = the law\'s checked cap (W_0 units); S = checked second-moment witness (W_0^2 units); S_0 = exact sum W_0^2 / q; M2 = S_0 / Z_0^2; radii = worst requested certificate radius at 2^18 draws (final checkpoint) per seed')
    for t in man['panels']['oracle_28']:
        d = load(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')); row = dict(task=t['name'], panel=t.get('panel'), exposure=t.get('exposure'), topology=t['topology'], n=int(t['n']), card=int(t['card']), scale=str(t['scale']), fine_states=t.get('fine_states'))
        if d is None: row['status'] = 'NOT_RUN'; diag['oracle'].append(row); continue
        row.update(status=('CENSORED: ' + '; '.join(d['censored'])) if d.get('censored') else 'COMPLETE', wall_s=d.get('wall_s'), phases=d.get('phases'), log2_Z0=(d.get('original') or {}).get('log2_Z0'), seed=((d.get('seed') or {}).get('law')), seed_record=((d.get('seed') or {}).get('record')), seed_exact_check=((d.get('seed') or {}).get('exact_check')), family=d.get('family'), selector=d.get('selector'), stream=({k: (d.get('stream') or {}).get(k) for k in ('prepare', 'closed', 'seed_matches_offline', 'cap_consumed_log2_W0', 'eps_num')} | dict(pilot={k: ((d.get('stream') or {}).get('pilot') or {}).get(k) for k in ('status', 'draws', 'd_seed_s_per_draw', 'log2_Z_proxy_fit', 'log2_Z_proxy_heldout_DIAGNOSTIC')})), packets={}, laws={}, replays={}, coincidence=d.get('coincidence'), production_trajectory=({k: (d.get('production_trajectory') or {}).get(k) for k in ('final_law', 'seconds')} | dict(attempts=[{k: a.get(k) for k in ('status', 'kind', 'why', 'winner', 'promoted', 'payback', 'family', 'committed_epoch')} for a in ((d.get('production_trajectory') or {}).get('attempts') or [])], epochs=len((d.get('production_trajectory') or {}).get('epochs') or []))) if d.get('production_trajectory') else None)
        for k, pk in (d.get('packets') or {}).items(): row['packets'][k] = {kk: pk.get(kk) for kk in ('V', 'seconds', 'refused', 'reason', 'slack_vs_float_exact', 'exact_rational_check', 'log2_Cmin', 'incumbent')} | dict(record={kk: (pk.get('record') or {}).get(kk) for kk in ('family_volume', 'inherited_entries_used')} | dict(b_pass={kk: ((pk.get('record') or {}).get('b_pass') or {}).get(kk) for kk in ('stages_done', 'max_splits', 'work_cells', 'seconds', 'peak_owned_bytes', 'checker')}, a_pass={kk: ((pk.get('record') or {}).get('a_pass') or {}).get(kk) for kk in ('stages_done', 'max_splits', 'work_cells', 'seconds', 'peak_owned_bytes', 'checker')}), selection=({kk: ((pk.get('selection') or {}).get(kk)) for kk in ('retune', 'exact_coefficients', 'oracle_Z_selector')} | dict(production={kk: ((pk.get('selection') or {}).get('production') or {}).get(kk) for kk in ('winner', 'promoted', 'incumbent_log2_J', 'winner_log2_J')}, production_candidates=[{kk: c_.get(kk) for kk in ('label', 'log2_B', 'log2_S', 'S_witness', 'log2_J', 'nominal_log2_C', 'rejected')} for c_ in ((pk.get('selection') or {}).get('production') or {}).get('candidates', [])], cap_only=[{kk: c_.get(kk) for kk in ('label', 'log2_B', 'log2_S', 'log2_J', 'rejected')} for c_ in (pk.get('selection') or {}).get('cap_only', [])], moment_only=[{kk: c_.get(kk) for kk in ('label', 'log2_B', 'log2_S', 'log2_J', 'rejected')} for c_ in (pk.get('selection') or {}).get('moment_only', [])]) if pk.get('selection') else None))
        for k, l in (d.get('laws') or {}).items(): row['laws'][k] = {kk: l.get(kk) for kk in ('log2_Z0', 'log2_Rstar', 'log2_S0', 'log2_M2', 'log2_Rstar_over_Z0', 'log2_B', 'log2_B_over_Z0', 'log2_B_over_Rstar', 'log2_S_over_S0', 'log2_witness_S_over_exact_S0', 'max_log2_X', 'same_as_seed', 'exact_check', 'total_q_log2')} | dict(conditionals=[(c_['z'], c_['parents'], c_['volume']) for c_ in ((l.get('proposal') or {}).get('conditionals') or [])], sha=(l.get('proposal') or {}).get('sha256', '')[:12])
        for k, r in (d.get('replays') or {}).items():
            if not isinstance(r, dict) or r.get('not_available'): row['replays'][k] = dict(not_available=True); continue
            row['replays'][k] = dict(implemented=final_worst(r.get('caps', {}).get('implemented')), tight=final_worst(r.get('caps', {}).get('tight')), log2_cap_implemented_over_Z0=r.get('log2_cap_implemented_over_Z0'), log2_cap_tight_over_Z0=r.get('log2_cap_tight_over_Z0'), same_as_seed=r.get('same_as_seed'), seconds=r.get('seconds'))
        # contrasts: construction (joint-selected vs seed) and joint objective (joint vs the better of cap-only / moment-only) at the IMPLEMENTED cap, per seed
        def worsts(k): return [x.get('worst') for x in (row['replays'].get(k) or {}).get('implemented', []) if isinstance(x, dict) and 'worst' in x]
        def covs(k): return [(x.get('covered'), x.get('K')) for x in (row['replays'].get(k) or {}).get('implemented', []) if isinstance(x, dict) and 'worst' in x]
        ws, wj, wc, wm = worsts('seed'), worsts('joint_selected'), worsts('cap_only'), worsts('moment_only'); cj = covs('joint_selected'); cs_ = covs('seed')
        constr = [(s_ / j_ if j_ > 0 else None) for s_, j_ in zip(ws, wj)]; new_full = [(c_[0] == c_[1] and s_[0] < s_[1]) for c_, s_ in zip(cj, cs_)]
        constr_seeds = sum(1 for r_, nf in zip(constr, new_full) if (r_ is not None and r_ >= 2.0) or nf)
        better_ep = [min(c_, m_) for c_, m_ in zip(wc, wm)] if wc and wm else []; jo = [(j_ <= 0.8 * e_) for j_, e_ in zip(wj, better_ep)]; jo_seeds = sum(jo)
        co = row.get('coincidence') or {}; coincident = bool(co.get('cap_eq_moment') and co.get('cap_eq_joint')); same_law = (row['laws'].get('joint_selected') or {}).get('same_as_seed')
        row['contrasts'] = dict(seed_worst=ws, joint_worst=wj, cap_only_worst=wc, moment_only_worst=wm, construction_ratios_seed_over_joint=constr, construction_new_full_completion=new_full, construction_seeds_2x=constr_seeds, construction_gate=(constr_seeds >= 2), joint_vs_better_endpoint_ratios=[(j_ / e_ if e_ > 0 else None) for j_, e_ in zip(wj, better_ep)], joint_objective_seeds_20pct=jo_seeds, joint_objective_gate=(jo_seeds >= 2 and not coincident), coincident_endpoints=coincident, joint_selected_is_seed=same_law, whole_model_family=(row.get('family') or {}).get('whole_model'),
                                tight_vs_implemented_seed=[(a_.get('worst'), b_.get('worst')) for a_, b_ in zip((row['replays'].get('seed') or {}).get('tight', []), (row['replays'].get('seed') or {}).get('implemented', [])) if isinstance(a_, dict) and isinstance(b_, dict)], packet_slack_V4096=((row['packets'].get('V4096') or {}).get('slack_vs_float_exact')), seed_B_over_Rstar=((row.get('seed') or {}).get('log2_B_over_Rstar')), seed_M2=((row.get('seed') or {}).get('log2_M2')), joint_M2=((row['laws'].get('joint_selected') or {}).get('log2_M2')), exact_coef_M2=((row['laws'].get('exact_coef_selected') or {}).get('log2_M2')), oracleZ_M2=((row['laws'].get('oracleZ_selected') or {}).get('log2_M2')), retune_M2=((row['laws'].get('retune_selected') or {}).get('log2_M2')), joint_Rstar_over_Z0=((row['laws'].get('joint_selected') or {}).get('log2_Rstar_over_Z0')), seed_Rstar_over_Z0=((row.get('seed') or {}).get('log2_Rstar_over_Z0')), proxy_error_bits=((row.get('selector') or {}).get('proxy_error_bits')))
        diag['oracle'].append(row)
    O = {r['task']: r for r in diag['oracle']}; anchors = man['panels'].get('replay_anchors') or {}; exposed_anchor = [t for t in anchors.get('exposed_7', []) if t in O]; fresh_anchor = [t for t in anchors.get('fresh_4', []) if t in O]
    g = lambda ts, key: [t for t in ts if (O[t].get('contrasts') or {}).get(key)]
    C = dict(exposed_anchors=exposed_anchor, exposed_pass=g(exposed_anchor, 'construction_gate'), fresh_anchors=fresh_anchor, fresh_pass=g(fresh_anchor, 'construction_gate'), per_model={t: dict(ratios=(O[t].get('contrasts') or {}).get('construction_ratios_seed_over_joint'), new_full=(O[t].get('contrasts') or {}).get('construction_new_full_completion'), seeds_2x=(O[t].get('contrasts') or {}).get('construction_seeds_2x'), gate=(O[t].get('contrasts') or {}).get('construction_gate'), joint_is_seed=(O[t].get('contrasts') or {}).get('joint_selected_is_seed'), status=O[t].get('status')) for t in exposed_anchor + fresh_anchor})
    complete_all = all(O[t].get('status', '').startswith('COMPLETE') for t in exposed_anchor + fresh_anchor) and exposed_anchor and fresh_anchor
    C['status'] = 'supported' if (len(C['exposed_pass']) >= 2 and len(C['fresh_pass']) >= 2) else ('descriptive' if (C['exposed_pass'] or C['fresh_pass']) else ('not supported' if complete_all else 'unidentified'))
    J = dict(exposed_pass=g(exposed_anchor, 'joint_objective_gate'), fresh_pass=g(fresh_anchor, 'joint_objective_gate'), coincident=[t for t in exposed_anchor + fresh_anchor if (O[t].get('contrasts') or {}).get('coincident_endpoints')], per_model={t: dict(ratios=(O[t].get('contrasts') or {}).get('joint_vs_better_endpoint_ratios'), seeds_20pct=(O[t].get('contrasts') or {}).get('joint_objective_seeds_20pct'), gate=(O[t].get('contrasts') or {}).get('joint_objective_gate'), coincident=(O[t].get('contrasts') or {}).get('coincident_endpoints'), whole_model=(O[t].get('contrasts') or {}).get('whole_model_family')) for t in exposed_anchor + fresh_anchor})
    J['status'] = 'supported' if (J['exposed_pass'] and J['fresh_pass']) else ('coincident' if complete_all and len(J['coincident']) == len(exposed_anchor + fresh_anchor) else ('not supported' if complete_all else 'unidentified'))
    diag['gates'] = dict(construction_mechanism=C, joint_objective=J)
    # ---- verdicts
    vi = res['verdict_inputs']; mat = [x for x in acc if x['material_2x_JOINT_vs_REPAIRED'] or x['material_2x_JOINT_vs_BASE']]
    pres_ok = all(not vi.get(sub, {}).get('JOINT', {}).get('regressions_vs_DGP4') for sub in ('preservation_18', 'preservation_13')) and not mi['JOINT_vs_DGP4']['lost'] and not mi['REPAIRED_not_JOINT'] and not mi['BASE_not_JOINT'] and not mi['SEED_not_JOINT']
    flags = [x['task'] for x in cost if x['flag_slower']]; seed_contrib = dict(SEED_not_REPAIRED=mi['SEED_not_REPAIRED'], REPAIRED_not_SEED=mi['REPAIRED_not_SEED'], material_2x_SEED_vs_REPAIRED=[x['task'] for x in acc if x['material_2x_SEED_vs_REPAIRED']], median_ratio_REPAIRED_over_SEED=med([x['ratio_REPAIRED_over_SEED'] for x in acc]), median_ratio_SEED_over_JOINT=med([x['ratio_SEED_over_JOINT'] for x in acc]), JOINT_adds_beyond_SEED=bool(mi['JOINT_not_SEED'] or any((x['ratio_SEED_over_JOINT'] or 0) >= 2 for x in acc)))
    mc = vi['mechanism_counts']; main_j = mc.get('main/JOINT', {}); main_s = mc.get('main/SEED', {})
    # failure classes per failing JOINT task on the main panel
    fcs = {}
    for r in em:
        j = r['arms'].get('JOINT')
        if not j or j['complete']: continue
        jm = j.get('joint') or {}; cls = None
        if not jm.get('offered'): cls = 'mechanism never executed (not offered: %s)' % (jm.get('refused') or 'n/a')
        elif not jm.get('created'): cls = 'policy / memory refusal (offered, not created)'
        elif not jm.get('ready'): cls = ('policy / memory refusal' if any(k in str(jm.get('closed')) for k in ('MEMORY', 'VOLUME', 'ALLOWANCE')) else ('numerical floor' if any(k in str(jm.get('closed')) for k in ('NUMERIC', 'RANGE', 'BITS')) else 'constructor cost (closed before READY: %s)' % str(jm.get('closed'))[:50]))
        elif not jm.get('sampled'): cls = 'constructor cost (READY, never sampled)'
        else:
            att = jm.get('attempts') or []; pil = jm.get('pilot') or {}
            if pil.get('status') != 'COMPLETE' and r['arms'].get('JOINT', {}).get('joint', {}).get('mode') == 'joint': cls = 'constructor cost (pilot short)'
            elif pil.get('log2_Z_proxy_fit') is None: cls = 'no useful normalizer information (no positive Z proxy)'
            elif not att: cls = 'constructor cost (no attempt inside the allowance)'
            elif all(a.get('status') == 'REFUSED' for a in att): cls = 'constructor cost (every attempt refused: %s)' % ', '.join(sorted({str(a.get('kind')) for a in att}))
            elif not any(a.get('promoted') for a in att): cls = 'no family headroom (no candidate beat the incumbent by 1 %)'
            else:
                lx = jm.get('log2_X_mean'); cls = ('slow per-draw work' if (jm.get('draws') or 0) < 20000 else ('poor scalar objective / Z proxy' if (lx is not None and lx < -20) else 'unresolved (promoted, sampled; the certificate did not close)'))
        fcs[r['task']] = dict(cls=cls, worst=j['worst_radius'], draws=jm.get('draws'), log2_X_mean=jm.get('log2_X_mean'), attempts=[(a.get('status'), a.get('winner'), a.get('promoted')) for a in (jm.get('attempts') or [])], closed=jm.get('closed'))
    by_cls = {}
    for t, v in fcs.items(): by_cls.setdefault(v['cls'].split(' (')[0], []).append(t)
    E_status = ('candidate' if (mi['new_dense_completion_candidates'] or mat) else 'none')
    diag['verdicts'] = dict(validity='see VALIDATION.json + controls (identity_ok on every cell; ledger identity on every planner result; before / after probes; D1-D53)', preservation=dict(status=('PRESERVED' if pres_ok else 'REGRESSION'), JOINT_lost_vs_DGP4=mi['JOINT_vs_DGP4']['lost'], REPAIRED_not_JOINT=mi['REPAIRED_not_JOINT'], BASE_not_JOINT=mi['BASE_not_JOINT'], SEED_not_JOINT=mi['SEED_not_JOINT'], preservation_18=vi.get('preservation_18', {}).get('JOINT'), preservation_13=vi.get('preservation_13', {}).get('JOINT'), note='four-second preservation exercises the repaired OLD behaviour (the 8 s offer threshold); 20 s panels exercise the new integration'),
                            seed_contribution=seed_contrib, construction_mechanism=dict(status=C['status'], exposed_pass=C['exposed_pass'], fresh_pass=C['fresh_pass'], rule='>= 2x worst-radius reduction (implemented caps, same draws per law) or a new full-eps completion of joint-selected vs seed, in >= 2 of 3 seeds; broad support needs >= 2 exposed AND >= 2 fresh anchors'), joint_objective=dict(status=J['status'], exposed_pass=J['exposed_pass'], fresh_pass=J['fresh_pass'], coincident=J['coincident'], rule='joint worst radius <= 0.8 x the better of cap-only / moment-only in the SAME family + packet, >= 1 exposed AND >= 1 fresh anchor in >= 2 of 3 seeds; coincident endpoints classified structurally'),
                            deployable_progress=dict(status=E_status, candidates=mi['new_dense_completion_candidates'], material_mutual_failures=[x['task'] for x in mat], seed_alone_explains=(bool(mi['SEED_not_REPAIRED']) and not mi['JOINT_not_SEED']), fresh_transfer=sorted(t for t in (mi['new_dense_completion_candidates'] + [x['task'] for x in mat]) if is_fresh(t)), rule='>= 1 new dense completion or >= 2x smaller worst radius on a mutual failure vs REPAIRED and BASE at the equal full contract, reproduced in BOTH confirmation seeds (confirmations decide the final status)'),
                            cost_overhead=dict(flags=flags, n_mutual_completions=len(cost), median_ratio_JOINT_over_REPAIRED=med([x['ratio_JOINT_over_REPAIRED'] for x in cost]), median_JOINT_construction_s=med([x['JOINT_construction_s'] for x in cost]), status=('FLAGGED' if flags else 'none')), mechanism_counts=dict(main_JOINT=main_j, main_SEED=main_s, all=mc), failure_classes=dict(by_class={k: sorted(v) for k, v in by_cls.items()}, per_task=fcs, legend=FAILURE_CLASSES))
    res['verdicts'] = diag['verdicts']; res['gates'] = diag['gates']; json.dump(diag, open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP5_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json'))
    ch = dict(utc=res['utc'], ceiling_s=bud['ceiling_s'], allocation_s=bud['allocation_s'], reassignments=bud.get('reassignments'), by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), by_outcome={o: sum(1 for r in rc if r['outcome'] == o) for o in sorted({r['outcome'] for r in rc})}, within_ceiling=(sum(r['wall_s'] for r in rc) <= bud['ceiling_s']), ledger='DGP5_LEDGER.jsonl', implementation_labor='reported separately in controls/UNSUPERVISED_DEV_LOG.md (not charged)')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, confirm, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, confirm=confirm, contract=contract))
    plan('main', [t['name'] for t in man['panels']['main_60']], ARMS, [0], False, 'main'); plan('preservation_18', [t['name'] for t in man['panels']['preservation_18']], ['REPAIRED', 'JOINT'], [0], False, 'p4'); plan('preservation_13', [t['name'] for t in man['panels']['preservation_13']], ['REPAIRED', 'JOINT'], [0], False, 'p20'); plan('diag', man['panels']['diag_8'], DIAG_ARMS, [0], False, 'main'); plan('forced', man['panels']['diag_8'], FORCED_ARMS, [0], False, 'main')
    cm = load(os.path.join(RD, 'CONFIRM_MANIFEST.json'))
    if cm: plan('confirm', cm['selected'], ARMS, [1, 2], True, 'per task')
    actual = {}
    for sub in ('main', 'preservation_18', 'preservation_13', 'diag', 'forced', 'confirm'):
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0), c['confirm'])] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'], p['confirm'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md: budget / blocked)'
    oracle_actual = {t['name']: os.path.exists(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')) for t in man['panels']['oracle_28']}
    json.dump(dict(utc=res['utc'], code_commit=fr['code']['commit'], planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), oracle=oracle_actual, superseding_links=('see ' + ', '.join(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json'))) if glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')) else 'none'), cells_joined_by='model_sha256 + evid_sha256 + contract (names resolved from MODEL_MANIFEST by model_sha256)'), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], main=mi.get('n_complete'), new=mi.get('new_dense_completion_candidates'), verdicts={k: (v if isinstance(v, str) else (v.get('status') if isinstance(v, dict) else None)) for k, v in diag['verdicts'].items()}, mechanism=main_j), default=str)[:1500])
    return res, diag

def select_confirm():
    res = load(os.path.join(RD, 'RESULTS.json')); man = load(os.path.join(RD, 'MODEL_MANIFEST.json')); vi = res['verdict_inputs']; meta = {t['name']: t for p in ('preservation_13', 'preservation_18', 'main_60') for t in man['panels'][p]}; mi = vi['main']; key = lambda t: meta[t]['model_sha256'] if t in meta else t
    tiers = [('a_completion_loss', sorted(set(mi['REPAIRED_not_JOINT'] + mi['BASE_not_JOINT'] + mi['SEED_not_JOINT'] + mi['JOINT_vs_DGP4']['lost']), key=key)), ('b_new_completion', sorted(set(mi['JOINT_not_REPAIRED']) | set(mi['JOINT_not_BASE']) | set(mi['SEED_not_REPAIRED']), key=key)), ('c_radius_gain_2x', sorted({x['task'] for x in vi['accuracy_mutual_failures'] if x['material_2x_JOINT_vs_REPAIRED'] or x['material_2x_JOINT_vs_BASE'] or x['material_2x_SEED_vs_REPAIRED']}, key=key)), ('d_overhead_flags', sorted({x['task'] for x in vi['cost_mutual_completions'] if x['flag_slower']}, key=key))]
    fr = load(os.path.join(RD, 'FREEZE.json')); tiers.append(('e_anchors', fr['confirmation']['anchors'])); chosen = []; affected = []
    for name, ts in tiers:
        for t in ts:
            if name != 'e_anchors': affected.append((name, t))
            if t not in chosen and len(chosen) < fr['confirmation'].get('max_tasks', 6): chosen.append(t)
    cm = dict(rule='PROTOCOL.md section 6 / FREEZE.json confirmation', tiers={n: ts for n, ts in tiers}, affected_all=affected, selected=chosen, unconfirmed_affected=[t for n, t in affected if t not in chosen], tasks=[dict(meta[t], contract=('p4' if meta[t].get('panel') == 'unified_18' else 'main')) for t in chosen if t in meta], utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(cm, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in cm.items() if k != 'tasks'}))

def report():
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')); L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
    vi = R['verdict_inputs']; mi = vi['main']; V = R['verdicts']; G = R['gates']; mc = vi['mechanism_counts']
    P('# DGP5 -- REPORT (derived by dgp5_analyze.py from the raw cells, oracle outputs and the ledger)'); P(); P('Frozen code: pgm %s (tree %s). Analyzer utc %s. Every count below is recomputed from `runs/*/*/cell.json`, `oracle/results/*.json` and `DGP5_LEDGER.jsonl`.' % (fr['code']['commit'][:9], fr['code']['tree'][:9], R['utc'])); P()
    P('## 1. Verdicts'); P()
    P('| verdict | status | basis |'); P('|---|---|---|')
    P('| validity / resources | see VALIDATION.json | %d / %d cells identity_ok; ledger identity on every planner result (validate_round); before / after probes of the six findings; D1-D53 + HP80 + unified57 + scheduling32 + accepted PAC suites |' % (sum(v['by_arm'][a]['identity_ok'] for v in R['completions_by_sub'].values() for a in v['by_arm']), sum(v['cells'] for v in R['completions_by_sub'].values())))
    pv = V['preservation']; P('| preservation | **%s** | JOINT lost vs DGP4 %s; REPAIRED-not-JOINT %s; BASE-not-JOINT %s; SEED-not-JOINT %s; preservation_18 JOINT %s / %s (regressions %s); preservation_13 JOINT %s / %s (regressions %s) |' % (pv['status'], pv['JOINT_lost_vs_DGP4'], pv['REPAIRED_not_JOINT'], pv['BASE_not_JOINT'], pv['SEED_not_JOINT'], (pv.get('preservation_18') or {}).get('complete'), (pv.get('preservation_18') or {}).get('n'), (pv.get('preservation_18') or {}).get('regressions_vs_DGP4'), (pv.get('preservation_13') or {}).get('complete'), (pv.get('preservation_13') or {}).get('n'), (pv.get('preservation_13') or {}).get('regressions_vs_DGP4')))
    sc = V['seed_contribution']; P('| seed contribution | descriptive | SEED-not-REPAIRED %s; REPAIRED-not-SEED %s; >= 2x radius gains SEED vs REPAIRED %s; median worst-radius ratio REPAIRED / SEED on mutual failures %s; JOINT adds beyond SEED: %s |' % (sc['SEED_not_REPAIRED'], sc['REPAIRED_not_SEED'], sc['material_2x_SEED_vs_REPAIRED'], f2(sc['median_ratio_REPAIRED_over_SEED']), sc['JOINT_adds_beyond_SEED']))
    cm_ = V['construction_mechanism']; P('| construction mechanism (oracle replays) | **%s** | exposed anchors passing %s of %s; fresh %s of %s (%s) |' % (cm_['status'], cm_['exposed_pass'], G['construction_mechanism']['exposed_anchors'], cm_['fresh_pass'], G['construction_mechanism']['fresh_anchors'], cm_['rule']))
    jo = V['joint_objective']; P('| joint-objective attribution | **%s** | exposed passing %s; fresh passing %s; coincident endpoints %s (%s) |' % (jo['status'], jo['exposed_pass'], jo['fresh_pass'], jo['coincident'], jo['rule']))
    ep = V['deployable_progress']; P('| deployable progress | **%s** | new dense completion candidates %s; >= 2x mutual-failure gains %s; SEED alone explains: %s; fresh transfer %s (%s) |' % (ep['status'], ep['candidates'], ep['material_mutual_failures'], ep['seed_alone_explains'], ep['fresh_transfer'], ep['rule']))
    co = V['cost_overhead']; P('| overhead | %s | flags %s on %d mutual completions; median JOINT / REPAIRED wall %s; median JOINT construction %s s |' % (co['status'], co['flags'], co['n_mutual_completions'], f2(co['median_ratio_JOINT_over_REPAIRED']), f2(co['median_JOINT_construction_s']))); P()
    P('## 2. Main panel (60 tasks x 4 arms, 20 s)'); P(); P('Completions: ' + ', '.join('%s %d' % (a, mi['n_complete'][a]) for a in ARMS) + '; identical completion sets across the four arms: %s; historical DGP4 set retained by JOINT: %s (lost %s). Fresh EVAL5 completions: %s.' % (mi['identical_sets_all_four'], not mi['JOINT_vs_DGP4']['lost'], mi['JOINT_vs_DGP4']['lost'], {a: len(mi['fresh_complete'][a]) for a in ARMS})); P()
    P('| task | panel | BASE | REPAIRED | SEED | JOINT | JOINT worst r | SEED worst r | REPAIRED worst r | JOINT mechanism (offered / created / READY / draws / epochs / switches) | attempts |'); P('|---|---|---|---|---|---|---:|---:|---:|---|---|')
    for r in R['tables'].get('main', []):
        A = r['arms']; j = (A.get('JOINT') or {}).get('joint') or {}
        P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s / %s / %s / %s | %s |' % (r['task'], (r.get('panel') or '')[:10], *['C' if (A.get(a) or {}).get('complete') else ((A.get(a) or {}).get('outcome') or '-')[:8] for a in ARMS], f4((A.get('JOINT') or {}).get('worst_radius')), f4((A.get('SEED') or {}).get('worst_radius')), f4((A.get('REPAIRED') or {}).get('worst_radius')), 'Y' if j.get('offered') else 'n', 'Y' if j.get('created') else 'n', 'Y' if j.get('ready') else 'n', j.get('draws'), j.get('epochs'), j.get('switches'), '; '.join('%s%s' % (a_.get('status'), ('->' + str(a_.get('winner'))) if a_.get('promoted') else '') for a_ in (j.get('attempts') or [])) or '-'))
    P(); P('Mechanism counts (main / JOINT): %s. Main / SEED: %s.' % (json.dumps(mc.get('main/JOINT')), json.dumps(mc.get('main/SEED')))); P()
    P('## 3. Mutual failures: worst radius on the full inventory (0.5 = vacuous)'); P(); P('| task | fresh | BASE | REPAIRED | SEED | JOINT | REPAIRED / SEED | SEED / JOINT | JOINT covered / K |'); P('|---|---|---:|---:|---:|---:|---:|---:|---|')
    for x in vi['accuracy_mutual_failures']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |' % (x['task'], x['fresh'], f4(x['BASE_worst']), f4(x['REPAIRED_worst']), f4(x['SEED_worst']), f4(x['JOINT_worst']), f2(x['ratio_REPAIRED_over_SEED']), f2(x['ratio_SEED_over_JOINT']), x['JOINT_covered'], x['K']))
    P(); P('## 4. Mutual completions: cost'); P(); P('| task | BASE s | REPAIRED s | SEED s | JOINT s | JOINT / REPAIRED | flag | JOINT construction s |'); P('|---|---:|---:|---:|---:|---:|---|---:|')
    for x in vi['cost_mutual_completions']: P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], f2(x['BASE_s']), f2(x['REPAIRED_s']), f2(x['SEED_s']), f2(x['JOINT_s']), f2(x['ratio_JOINT_over_REPAIRED']), 'FLAG' if x['flag_slower'] else '', f2(x['JOINT_construction_s'])))
    P(); P('## 5. Preservation'); P()
    for sub in ('preservation_18', 'preservation_13'):
        v = vi.get(sub)
        if v: P('- %s: REPAIRED %s / %s, JOINT %s / %s (historical %s); JOINT regressions vs DGP4 %s; REPAIRED-not-JOINT %s; JOINT route offered / created / sampled: %s / %s / %s.' % (sub, v['REPAIRED']['complete'], v['REPAIRED']['n'], v['JOINT']['complete'], v['JOINT']['n'], v['historical_complete'], v['JOINT']['regressions_vs_DGP4'], v['REPAIRED_not_JOINT'], v['JOINT']['offered'], v['JOINT']['created'], v['JOINT']['sampled']))
    P(); P('## 6. Eight predetermined diagnostic models'); P(); P('| task | arm | outcome | worst r | main SEED r | main JOINT r | created / READY / draws / epochs | attempts | refinement ended |'); P('|---|---|---|---:|---:|---:|---|---|---|')
    for x in vi['diagnostics']: P('| %s | %s | %s | %s | %s | %s | %s / %s / %s / %s | %s | %s |' % (x['task'], x['arm'], x['outcome'], f4(x['worst_radius']), f4(x['main_SEED_worst']), f4(x['main_JOINT_worst']), x['created'], x['ready'], x['draws'], x['epochs'], '; '.join('%s%s' % (a_.get('status'), ('->' + str(a_.get('winner'))) if a_.get('promoted') else '') for a_ in (x.get('attempts') or [])) or '-', (x.get('refinement_ended') or '-')[:50]))
    P(); P('## 7. Oracle mechanism panel'); P(); P('Units: ' + D['units']); P()
    P('| model | status | seed B / R* bits | seed R* / Z0 | joint R* / Z0 | M2 seed -> joint (exact-coef / oracle-Z / retune) | family (z <- parents; whole model?) | packet slack V4096 b / a-mass bits | replay worst (impl.): seed / cap / moment / joint | C gate | J gate | coincident |'); P('|---|---|---:|---:|---:|---|---|---|---|---|---|---|')
    for o in D['oracle']:
        c = o.get('contrasts') or {}; fam = o.get('family') or {}; sl = c.get('packet_slack_V4096') or {}
        P('| %s | %s | %s | %s | %s | %s -> %s (%s / %s / %s) | %s <- %s; %s | %s / %s | %s / %s / %s / %s | %s | %s | %s |' % (o['task'], (o.get('status') or '')[:14], f2(c.get('seed_B_over_Rstar')), f2(c.get('seed_Rstar_over_Z0')), f2(c.get('joint_Rstar_over_Z0')), f2(c.get('seed_M2')), f2(c.get('joint_M2')), f2(c.get('exact_coef_M2')), f2(c.get('oracleZ_M2')), f2(c.get('retune_M2')), fam.get('z'), fam.get('parents'), fam.get('whole_model'), f2(sl.get('b_max_bits')), f2(sl.get('a_mass_bits')), ' '.join(f4(w) for w in (c.get('seed_worst') or [])), ' '.join(f4(w) for w in (c.get('cap_only_worst') or [])), ' '.join(f4(w) for w in (c.get('moment_only_worst') or [])), ' '.join(f4(w) for w in (c.get('joint_worst') or [])), c.get('construction_gate'), c.get('joint_objective_gate'), c.get('coincident_endpoints')))
    P(); P('## 8. Failure classes (JOINT, main panel)'); P()
    for k, v in (V['failure_classes']['by_class'] or {}).items(): P('- **%s**: %s' % (k, ', '.join(v)))
    P(); P('## 9. Charges'); P(); ch = R['charges']; P('Total %.1f s of the %d s ceiling (%d receipts; %s). By scope: %s. Reassignments: %s.' % (ch['total_s'], ch['ceiling_s'], ch['n_receipts'], json.dumps(ch['by_outcome']), json.dumps(ch['by_scope_s']), json.dumps(ch.get('reassignments'), default=str)[:600])); P()
    P('## 10. Limitations'); P(); P('- Geometry alone does not establish PAC containment on a model without an oracle; the oracle panel (<= 2^16 states) is the only containment check.'); P('- Z_proxy is a heuristic; the production selector\'s error against the true Z_0 is reported on the oracle panel only.'); P('- The oracle counterfactuals (exact coefficients, oracle-Z selector) are labelled oracle-assisted and never reach production.'); P('- BASE per-coordinate radii use the recorded aggregate certificate widths (conservative for BASE).'); P('- The replay comparison is pinned to the FIRST attempted family and a common packet; the production trajectory (<= 2 attempts) is reported separately.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md written', len(L), 'lines')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'analyze'
    if cmd == 'analyze': analyze()
    elif cmd == 'select-confirm': select_confirm()
    elif cmd == 'report': report()
