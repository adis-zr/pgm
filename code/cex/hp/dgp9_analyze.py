"""DGP9 committed analyzer (PROTOCOL.md sections 5-6; protocol rule 8): every count / table is derived from the raw cells (runs/<sub>/<dir>/cell.json + result.json), the manifests, the control / probe receipts and the ledger. Writes
RESULTS.json (tables per sub: 'screen' (HB_SCREEN development streams), 'main' (the 7 exposed inputs x INCUMBENT / HB_FIXED / HB_REVISED x seeds 0 / 1), 'fresh' (5 matched fresh inputs), 'preservation_24' / '_18' / '_13' (INCUMBENT);
the FIVE GATES kept separate: validity, mechanism, inference, preservation_cost, generalization; the limiting-term classification per heat-bath cell), DIAGNOSTICS.json, RUN_MANIFEST.json, CHARGES.json, REPORT.md.
usage: dgp9_analyze.py [analyze | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
RD = os.environ.get('DGP9_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION'); DGP7 = os.path.join(os.path.dirname(RD), 'DGP7_RESIDUAL_JOINT')
ARMS = ['INCUMBENT', 'HB_FIXED', 'HB_REVISED']; HB_ARMS = ('HB_FIXED', 'HB_REVISED', 'HB_SCREEN'); DIAG_ARMS = ['HB_SCREEN']; EPS = 0.005; DELTA = 1e-6
SUBS = ('screen', 'main', 'fresh', 'preservation_24', 'preservation_18', 'preservation_13'); PRIMARY = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half', 'dg_n64_c4_er50_half', 'dg_n64_c4_clique_half', 'dg_n32_c4_er50_half']; NEAR_MISSES = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half']; ER_GAIN = 'dg_n64_c4_er50_half'; WEAK_CLIQUE = 'dg_n64_c4_clique_half'
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
    """per ORIGINAL coordinate final radius on the FULL fixed query inventory: published rows, plus (heat-bath arms) informative partial enclosures; 0.5 for every inventory coordinate without one"""
    d = c['_result']
    if d is None: return None, None
    K = d.get('K') or 0; rows = d.get('answers') or []; rad = {}
    for a in rows:
        key = (a['var'], a['state'])
        if a.get('guarantee') != 'NOT_PUBLISHED': rad[key] = float(F(a['hi']) - F(a['lo'])) / 2
    if c['arm'] in HB_ARMS:
        for e in d.get('enclosures') or []:
            key = (e['var'], e['state']); w = float(F(str(e['hi'])) - F(str(e['lo']))) / 2
            if key not in rad or w < rad[key]: rad[key] = w
    full = [rad.get((a['var'], a['state']), 0.5) for a in rows] if rows else ([0.5] * K if K else [])
    return full, dict(K=K, published=sum(1 for a in rows if a.get('guarantee') != 'NOT_PUBLISHED'), informative=sum(1 for w in full if w < 0.5), width_max=(2 * max(full) if full else None))


def cell_row(c):
    full, info = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}; hb = c.get('heatbath') if c['arm'] in HB_ARMS else None
    late = bool(d.get('published')) and d.get('hard_deadline_respected') is False
    return dict(complete=bool(c.get('complete')), outcome=c.get('outcome'), receipt_outcome=c.get('receipt_outcome'), receipt_wall_s=c.get('receipt_wall_s'), solver_wall_s=c.get('solver_wall_s'), published=c.get('published'), K=c.get('K'), identity_ok=c.get('identity_ok'), hard_deadline_respected=c.get('hard_deadline_respected'), late_rows=late, seed=c.get('seed'), seed_index=c.get('seed_index', 0), dir=os.path.relpath(c['_dir'], RD),
                worst_radius=(max(full) if full else None), median_radius=(med(full) if full else None), covered_at_eps=(sum(1 for w in full if w <= EPS) if full else None), inventory=info, ledger_identity=m.get('constructor_live_ledger_identity'), defect=(m.get('defect') or m.get('candidate_defect') or m.get('certificate_defect') or m.get('internal_error')), heatbath=hb, rate_model_file=c.get('rate_model_file'), peak_rss_bytes=c.get('peak_rss_bytes'), refusal=((hb or {}).get('refusal_kind') if hb else (m.get('refusal') or {}).get('kind') if isinstance(m.get('refusal'), dict) else None))


def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0)), {})[c['arm']] = cell_row(c)
    return by, cs


def limiting_term(hb, contract_work_s=19.0):
    """which term limits a heat-bath cell: admission (typed refusal), gap (the N needed for epsilon exceeds what the measured rate could record in the whole allowance), draw_rate (within 2x of it), checkpoint_loss (the recorded
    count at the last completed checkpoint is below what was reachable), burn_in (burn-in share > 25 %), publication_cost (phase share > 10 %), none (epsilon reached)"""
    if not hb: return dict(term='no_cell')
    if hb.get('refusal_kind'): return dict(term='admission', refusal=hb.get('refusal_kind'))
    r = hb.get('certified_radius'); N = hb.get('certified_N') or hb.get('transitions_recorded'); rate = hb.get('steps_per_second'); ph = hb.get('phases_s') or {}; tot = sum(v for v in ph.values() if isinstance(v, (int, float))) or 1.0
    if not (isinstance(r, (int, float)) and r > 0 and N): return dict(term='no_certificate')
    N_eps = N * (r / EPS) ** 2; reachable = (rate or 0) * max(0.0, contract_work_s - (ph.get('witness') or 0) - (ph.get('certificate_setup') or 0) - (ph.get('chain_construct') or 0) - (ph.get('burn_in') or 0) - 0.35); burn_share = (ph.get('burn_in') or 0) / tot; pub_share = ((ph.get('publication') or 0) + sum(c.get('checkpoint_overhead_s') or 0 for c in (hb.get('checkpoints') or []))) / tot
    if r <= EPS: term = 'none (epsilon reached)'
    elif burn_share > 0.25: term = 'burn_in'
    elif N_eps > reachable * 2: term = 'gap'
    elif N_eps > reachable: term = 'draw_rate'
    elif pub_share > 0.10: term = 'publication_cost'
    else: term = 'checkpoint_loss'
    return dict(term=term, N_recorded=N, N_needed_for_epsilon=N_eps, reachable_at_measured_rate=reachable, ratio_needed_over_reachable=(N_eps / reachable if reachable else None), burn_in_share=burn_share, publication_share=pub_share, sampling_stop=hb.get('sampling_stop'), checkpoints=(hb.get('checkpoints_completed'), hb.get('checkpoints_declared')))


def analyze():
    man, tp = panels(); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code'].get('commit'), freeze_sha256=(sha(os.path.join(RD, 'FREEZE.json')) if os.path.exists(os.path.join(RD, 'FREEZE.json')) else None), tables={}, completions_by_sub={}, verdict_inputs={}, gates={})
    meta = {}
    for p in tp.values():
        for t in p: meta.setdefault(t['name'], t)
    for sub in SUBS:
        by, cs = table(sub)
        if not cs: continue
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], role=meta.get(k[0], {}).get('role'), family=(meta.get(k[0], {}).get('family') or meta.get(k[0], {}).get('topology')), coupling=meta.get(k[0], {}).get('coupling'), n=meta.get(k[0], {}).get('n'), card=meta.get(k[0], {}).get('card'), archived_incumbent=meta.get(k[0], {}).get('archived_incumbent'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][1], PRIMARY.index(kv[0][0]) if kv[0][0] in PRIMARY else 99, kv[0][0]))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- validity gate (from the qualification receipts + every cell)
    q = os.path.join(RD, 'controls', 'qual'); ctl = load(os.path.join(q, 'CONTROLS_DGP_90.json')) or {}; pa = load(os.path.join(q, 'PROBES_AFTER.json')) or {}; pb = load(os.path.join(RD, 'controls', 'before', 'PROBES_BEFORE.json')) or load(os.path.join(RD, 'controls', 'dev', 'probes_parent', 'PROBES.json')) or {}
    suites = {n: ((load(os.path.join(q, f)) or {}).get('all_ok')) for n, f in (('hp', 'CONTROLS_HP.json'), ('unified', 'CONTROLS_UNIFIED.json'), ('revision', 'CONTROLS_REVISION.json'))}; refs = next((c for c in (ctl.get('controls') or []) if c.get('control', '').startswith('D90')), None)
    all_cells = [c for sub in SUBS for c in cells_of(sub)]; hb_cells = [c for c in all_cells if c['arm'] in HB_ARMS]
    late = [os.path.relpath(c['_dir'], RD) for c in all_cells if (c.get('published') or 0) > 0 and c.get('hard_deadline_respected') is False]; bad_ident = [os.path.relpath(c['_dir'], RD) for c in all_cells if c.get('identity_ok') is False]
    bad_ledger = [os.path.relpath(c['_dir'], RD) for c in hb_cells if ((c.get('_result') or {}).get('mechanism') or {}).get('constructor_live_ledger_identity') is not True]; wrong_refusals = [os.path.relpath(c['_dir'], RD) for c in hb_cells if ((c.get('heatbath') or {}).get('refusal_kind') in ('INTERNAL',))]
    validity = dict(controls=dict(all_ok=ctl.get('all_ok'), n=ctl.get('n'), n_ok=ctl.get('n_ok'), failed=[c['control'] for c in (ctl.get('controls') or []) if not c.get('ok')]), probes_after_absent=dict(present=pa.get('present'), n_present=pa.get('n_present'), errors=pa.get('errors')), probes_before_present=dict(present=pb.get('present'), n_present=pb.get('n_present')), suites=suites, references=(dict(ok=refs.get('ok')) if refs else None),
                    late_rows=late, identity_failures=bad_ident, heatbath_ledger_identity_failures=bad_ledger, internal_errors=wrong_refusals, cells=len(all_cells), heatbath_cells=len(hb_cells))
    v_ok = bool(ctl.get('all_ok')) and pa.get('n_present') == 0 and (pa.get('n_absent') or 0) == 7 and (pb.get('n_present') or 0) == 7 and all(suites.values()) and bool(refs and refs.get('ok')) and not late and not bad_ident and not bad_ledger and not wrong_refusals
    validity['status'] = 'PASS' if v_ok else ('INCOMPLETE' if not ctl else 'FAIL'); res['gates']['validity'] = validity
    # ---- per-input view of the main table
    main = {(r['task'], r['seed_index']): r for r in res['tables'].get('main', [])}; fresh = {(r['task'], r['seed_index']): r for r in res['tables'].get('fresh', [])}
    def arm_cell(rows, task, seed, arm): return ((rows.get((task, seed)) or {}).get('arms') or {}).get(arm)
    def hbw(cell): return (cell or {}).get('worst_radius')
    # ---- mechanism gate
    clique = {s: arm_cell(main, WEAK_CLIQUE, s, 'HB_REVISED') for s in (0, 1)}; clique_fixed = {s: arm_cell(main, WEAK_CLIQUE, s, 'HB_FIXED') for s in (0, 1)}
    adm = {s: dict(revised_eligible=((clique[s] or {}).get('heatbath') or {}).get('eligible'), revised_attempts=len(((clique[s] or {}).get('heatbath') or {}).get('attempts') or []), revised_gap=((clique[s] or {}).get('heatbath') or {}).get('gap_g'), revised_width=((clique[s] or {}).get('heatbath') or {}).get('width'), fixed_eligible=((clique_fixed[s] or {}).get('heatbath') or {}).get('eligible'), fixed_refusal=((clique_fixed[s] or {}).get('heatbath') or {}).get('refusal_kind')) for s in (0, 1)}
    past_cap = {}
    for t in NEAR_MISSES:
        for s in (0, 1):
            hf = (arm_cell(main, t, s, 'HB_FIXED') or {}).get('heatbath') or {}; hr = (arm_cell(main, t, s, 'HB_REVISED') or {}).get('heatbath') or {}
            past_cap['%s/seed%d' % (t, s)] = dict(fixed_N_max=(hf.get('checkpoint_plan') or {}).get('N_max'), fixed_last_N=hf.get('certified_N'), revised_last_N=hr.get('certified_N'), revised_completed=hr.get('checkpoints_completed'), revised_declared=hr.get('checkpoints_declared'), executes_past_cap=bool(hr.get('certified_N') and hf.get('checkpoint_plan', {}).get('N_max') and hr['certified_N'] > hf['checkpoint_plan']['N_max']), fixed_radius=hf.get('certified_radius'), revised_radius=hr.get('certified_radius'))
    mech_ok_adm = all(adm[s]['revised_eligible'] for s in (0, 1)) and all(isinstance(adm[s]['revised_gap'], (int, float)) and adm[s]['revised_gap'] > 0 for s in (0, 1)); mech_ok_cap = bool(past_cap) and all(v['executes_past_cap'] for v in past_cap.values())
    res['gates']['mechanism'] = dict(status=('PASS' if (mech_ok_adm and mech_ok_cap) else ('PARTIAL' if (mech_ok_adm or mech_ok_cap) else ('NOT RUN' if not main else 'FAIL'))), weak_clique_admission=adm, weak_clique_admitted_both_seeds=mech_ok_adm, revised_plan_executes_past_fixed_cap=past_cap, past_cap_all=mech_ok_cap, note='mechanism progress is not inference progress')
    # ---- inference gate (exposed, observed only)
    inf_rows = {}
    for t in PRIMARY:
        inc = (meta.get(t) or {}).get('archived_incumbent') or {}; cur_fail = inc.get('current_failure'); per = {}
        for s in (0, 1):
            cells = {a: arm_cell(main, t, s, a) for a in ARMS}; per[s] = dict(worst={a: hbw(cells[a]) for a in ARMS}, complete={a: bool((cells[a] or {}).get('complete')) for a in ARMS}, outcome={a: (cells[a] or {}).get('outcome') for a in ARMS}, published={a: (cells[a] or {}).get('published') for a in ARMS}, refusal={a: (cells[a] or {}).get('refusal') for a in ARMS}, receipt_s={a: (cells[a] or {}).get('receipt_wall_s') for a in ARMS})
            wi, wf, wr = per[s]['worst']['INCUMBENT'], per[s]['worst']['HB_FIXED'], per[s]['worst']['HB_REVISED']
            per[s]['ratio_revised_over_fixed'] = (wr / wf) if (isinstance(wr, (int, float)) and isinstance(wf, (int, float)) and wf > 0) else None; per[s]['ratio_revised_over_incumbent'] = (wr / wi) if (isinstance(wr, (int, float)) and isinstance(wi, (int, float)) and wi > 0) else None; per[s]['ratio_fixed_over_incumbent'] = (wf / wi) if (isinstance(wf, (int, float)) and isinstance(wi, (int, float)) and wi > 0) else None
            per[s]['dgp8_heatbath_radius'] = (inc.get('dgp8_heatbath_radii') or {}).get(str(s)); per[s]['er_gain_retained'] = (isinstance(wr, (int, float)) and isinstance(per[s]['dgp8_heatbath_radius'], (int, float)) and wr <= 1.1 * per[s]['dgp8_heatbath_radius']) if t == ER_GAIN else None
        both = all(s in per and any(per[s]['worst'].values()) for s in (0, 1))
        newc = {a: bool(both and all(per[s]['complete'][a] for s in (0, 1))) for a in ('HB_FIXED', 'HB_REVISED')}; newc_inc = bool(both and all(per[s]['complete']['INCUMBENT'] for s in (0, 1)))
        inf_rows[t] = dict(current_failure=cur_fail, incumbent_archived_best_worst_radius=inc.get('best_worst_radius'), seeds=per, both_seeds_run=both, new_completion=dict(HB_FIXED=(newc['HB_FIXED'] and bool(cur_fail)), HB_REVISED=(newc['HB_REVISED'] and bool(cur_fail)), INCUMBENT_now_completes=newc_inc), best_revised_worst=(max([per[s]['worst']['HB_REVISED'] for s in (0, 1) if isinstance(per[s]['worst']['HB_REVISED'], (int, float))] or [None])), er_gain_retained_both=(all(per[s].get('er_gain_retained') for s in (0, 1)) if t == ER_GAIN else None))
    new_comp = [t for t, r in inf_rows.items() if r['new_completion']['HB_REVISED'] or r['new_completion']['HB_FIXED']]
    inference = dict(status=('NEW COMPLETION' if new_comp else ('NO NEW COMPLETION' if main else 'NOT RUN')), new_completions=new_comp, per_input=inf_rows, er_gain_retained=(inf_rows.get(ER_GAIN) or {}).get('er_gain_retained_both'), rule='observed epsilon completion on a current failure in BOTH seeds = NEW COMPLETION; equal-cost worst radii per arm; ER gain retained iff HB_REVISED worst <= 1.1 x the DGP8 certified radius in both seeds; predictions do not count')
    res['gates']['inference'] = inference
    # ---- preservation + cost gate (INCUMBENT on the cohorts; overhead where both complete)
    d7 = load(os.path.join(DGP7, 'RESULTS.json')) or {}; hist7 = {sub: {r['task']: (r['arms'].get('REPAIRED') or {}).get('complete') for r in (d7.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}; hist24 = {t['name']: True for t in tp.get('preservation_24', [])}
    pres = {}
    for sub, hist in (('preservation_24', hist24), ('preservation_18', hist7['preservation_18']), ('preservation_13', hist7['preservation_13'])):
        rows = res['tables'].get(sub, []); ran = {r['task'] for r in rows if 'INCUMBENT' in r['arms']}; comp = {r['task'] for r in rows if (r['arms'].get('INCUMBENT') or {}).get('complete')}
        pres[sub] = dict(cohort_size=len(hist), ran=len(ran), complete=len(comp), lost=sorted(n for n in ran if hist.get(n) and n not in comp), gained=sorted(n for n in comp if not hist.get(n)), not_run=sorted(n for n in hist if n not in ran), status=('NOT RUN' if not rows else ('PRESERVED on the %d run of %d' % (len(ran), len(hist)) if not [n for n in ran if hist.get(n) and n not in comp] else 'LOST %s' % sorted(n for n in ran if hist.get(n) and n not in comp))))
    cost = []
    for sub in ('main', 'fresh'):
        for r in res['tables'].get(sub, []):
            A = r['arms']; inc_ = A.get('INCUMBENT')
            for arm in ('HB_FIXED', 'HB_REVISED'):
                h = A.get(arm)
                if inc_ and h and inc_['complete'] and h['complete']: cost.append(dict(sub=sub, task=r['task'], seed_index=r['seed_index'], arm=arm, INCUMBENT_s=inc_['receipt_wall_s'], HB_s=h['receipt_wall_s'], ratio=h['receipt_wall_s'] / inc_['receipt_wall_s'], flag=bool(h['receipt_wall_s'] - inc_['receipt_wall_s'] >= 0.1 and h['receipt_wall_s'] / inc_['receipt_wall_s'] >= 1.25)))
    passing_loss = [(r['task'], r['seed_index'], arm) for r in res['tables'].get('main', []) for arm in ('HB_FIXED', 'HB_REVISED') if (r['arms'].get('INCUMBENT') or {}).get('complete') and r['arms'].get(arm) and not r['arms'][arm]['complete']]
    res['gates']['preservation_cost'] = dict(status=('; '.join('%s: %s' % (k, v['status']) for k, v in pres.items())), cohorts=pres, overhead=dict(mutual_completions=len(cost), flags=[(x['sub'], x['task'], x['seed_index'], x['arm'], round(x['ratio'], 3)) for x in cost if x['flag']], median_ratio=med([x['ratio'] for x in cost]), rule='INCUMBENT vs HB where both complete: 1.25x and +0.1 s'), standalone_hb_loses_on_passing_cases=passing_loss, note='standalone HB may lose to the incumbent and is never presented as an unconditional replacement; SELECT not implemented')
    # ---- generalization (fresh, separately)
    gen = {}
    for (t, s), r in sorted(fresh.items()):
        A = r['arms']; gen.setdefault(t, {})[s] = dict(worst={a: hbw(A.get(a)) for a in ARMS}, complete={a: bool((A.get(a) or {}).get('complete')) for a in ARMS}, eligible={a: ((A.get(a) or {}).get('heatbath') or {}).get('eligible') for a in ('HB_FIXED', 'HB_REVISED')}, refusal={a: (A.get(a) or {}).get('refusal') for a in ARMS}, revised_attempts=len(((A.get('HB_REVISED') or {}).get('heatbath') or {}).get('attempts') or []))
    res['gates']['generalization'] = dict(status=('REPORTED SEPARATELY (fresh, %d inputs)' % len(gen) if gen else 'NOT RUN'), fresh=gen, note='no conclusion about strong frustration from weak-only admission; the strong twins are negative admission controls')
    # ---- limiting terms per heat-bath cell
    lim = {}
    for sub in ('main', 'fresh'):
        for r in res['tables'].get(sub, []):
            for arm in ('HB_FIXED', 'HB_REVISED'):
                h = (r['arms'].get(arm) or {}).get('heatbath')
                if h is not None: lim['%s/%s/seed%d/%s' % (sub, r['task'], r['seed_index'], arm)] = limiting_term(h)
    res['verdict_inputs']['limiting_terms'] = lim; res['verdict_inputs']['limiting_term_counts'] = {k: sum(1 for v in lim.values() if v.get('term') == k) for k in sorted({v.get('term') for v in lim.values()})}
    # ---- screen table summary (development streams; the frozen rate model)
    scr = [dict(task=r['task'], **{k: ((r['arms'].get('HB_SCREEN') or {}).get('heatbath') or {}).get(k) for k in ('eligible', 'width', 'gap_g', 'refusal_kind', 'chain', 'dev_steps_per_second', 'fast_path_share', 'exact_fallbacks', 'checkpoint_overhead_s', 'burn_in_steps')}, attempts=len(((r['arms'].get('HB_SCREEN') or {}).get('heatbath') or {}).get('attempts') or [])) for r in res['tables'].get('screen', [])]
    res['verdict_inputs']['screen'] = scr; res['verdict_inputs']['rate_model'] = load(os.path.join(RD, 'HEATBATH_RATES.json'))
    # ---- charges
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP9_LEDGER.jsonl'))] if os.path.exists(os.path.join(RD, 'DGP9_LEDGER.jsonl')) else []; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json')) or {}
    ch = dict(utc=res['utc'], ceiling_s=bud.get('ceiling_s'), allocation_s=bud.get('allocations'), reassignments=bud.get('reassignments'), by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), by_outcome={o: sum(1 for r in rc if r['outcome'] == o) for o in sorted({r['outcome'] for r in rc})}, within_ceiling=(sum(r['wall_s'] for r in rc) <= (bud.get('ceiling_s') or 0)), unique_jids=(len({r['jid'] for r in rc}) == len(rc)), spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r.get('jid') == s['jid'] for r in rc)], ledger='DGP9_LEDGER.jsonl', implementation_labor='reported separately in controls/UNSUPERVISED_DEV_LOG.md (not charged)')
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    # ---- run manifest
    planned = []
    def plan(sub, names, arms, seeds, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, contract=contract))
    plan('screen', [t['name'] for t in tp.get('main_exposed', [])], ['HB_SCREEN'], [0], 'main'); plan('main', [t['name'] for t in tp.get('main_exposed', [])], ARMS, [0, 1], 'main'); plan('fresh', [t['name'] for t in tp.get('fresh', [])], ARMS, [0, 1], 'main')
    plan('preservation_24', [t['name'] for t in tp.get('preservation_24', [])], ['INCUMBENT'], [0], 'main'); plan('preservation_18', [t['name'] for t in tp.get('preservation_18', [])], ['INCUMBENT'], [0], 'p4'); plan('preservation_13', [t['name'] for t in tp.get('preservation_13', [])], ['INCUMBENT'], [0], 'p20')
    actual = {}
    for sub in SUBS:
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0))] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md)'
    json.dump(dict(utc=res['utc'], code_commit=fr['code'].get('commit'), planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), unplanned_actual=[k for k in actual if not any((p['sub'], p['task'], p['arm'], p['seed_index']) == k for p in planned)], amendments=[os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json'))]), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(dict(utc=res['utc'], limiting_terms=lim, screen=scr, mechanism=res['gates']['mechanism'], inference=inference, units='radii = half-widths of the certified marginal intervals on the full inventory (0.5 for absent coordinates); gap g = lower bound of the random-scan heat-bath absolute spectral gap; N = recorded post-burn-in states at the last completed checkpoint'), open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(completions=res['completions_by_sub'], validity=validity['status'], mechanism=res['gates']['mechanism']['status'], inference=inference['status'], er_gain_retained=inference['er_gain_retained'], preservation=res['gates']['preservation_cost']['status'], generalization=res['gates']['generalization']['status'], limiting=res['verdict_inputs']['limiting_term_counts'], charged=ch['total_s']), default=str)[:1800])
    return res


def report():
    R = load(os.path.join(RD, 'RESULTS.json')); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
    G = R['gates']; ch = R['charges']
    P('# REPORT -- DGP9_SPECTRAL_HEATBATH_CONTINUATION (repair DGP8 + one frozen continuation; 27 Nov 2026)'); P()
    P('Frozen pgm `%s` (branch dgp9-heatbath-continuation from ebf994c; the DGP8 engine ad20e73 is the pinned parent of every before-probe). Analyzer `dgp9_analyze.py` at the same commit; every number below is derived from the raw cells under runs/, the manifests, the control / probe receipts and the ledger. Five gates, reported separately (PROTOCOL section 6). Nothing here is a claim about strong frustrated graphs; SELECT was not implemented.' % (fr['code'].get('commit') or '?')[:12]); P()
    P('## 0. What executed'); P()
    for sub, c in R['completions_by_sub'].items(): P('- %s: %d cells (%s)' % (sub, c['cells'], ', '.join('%s %d / %d complete, %d receipts COMPLETED, %d identity_ok' % (a, v['complete'], v['cells'], v['receipts_completed'], v['identity_ok']) for a, v in c['by_arm'].items())))
    P(); P('## 1. Validity gate: **%s**' % G['validity']['status']); P()
    v = G['validity']; P('- controls D1-D90 from the clean checkout: all_ok %s (%s / %s%s)' % (v['controls'].get('all_ok'), v['controls'].get('n_ok'), v['controls'].get('n'), ('; failed ' + ', '.join(v['controls']['failed'])) if v['controls'].get('failed') else ''))
    P('- review findings RV1-RV7 (dgp9_probes): PRESENT on the pinned parent %s; present at the frozen commit %s (errors %s)' % (v['probes_before_present'].get('present'), v['probes_after_absent'].get('present'), v['probes_after_absent'].get('errors')))
    P('- accepted suites: %s; recovered references (D90): %s' % (v['suites'], (v['references'] or {}).get('ok')))
    P('- late published rows: %s; identity failures: %s; heat-bath ledger-identity failures: %s; internal errors: %s (over %d cells, %d heat-bath cells)' % (v['late_rows'], v['identity_failures'], v['heatbath_ledger_identity_failures'], v['internal_errors'], v['cells'], v['heatbath_cells'])); P()
    P('## 2. Mechanism gate: **%s**' % G['mechanism']['status']); P()
    for s, a in G['mechanism']['weak_clique_admission'].items(): P('- weak n64 card-4 clique, seed %s: HB_REVISED eligible %s (attempts %s, checked width %s, gap %s); HB_FIXED eligible %s (%s)' % (s, a['revised_eligible'], a['revised_attempts'], f4(a['revised_width']) if isinstance(a['revised_width'], (int, float)) else a['revised_width'], a['revised_gap'], a['fixed_eligible'], a['fixed_refusal']))
    P(); P('| near-miss / seed | HB_FIXED N_max | HB_FIXED last N | HB_REVISED last N | revised checkpoints | past the cap | r fixed | r revised |'); P('|---|---:|---:|---:|---|---|---:|---:|')
    for k, v_ in G['mechanism']['revised_plan_executes_past_fixed_cap'].items(): P('| %s | %s | %s | %s | %s / %s | %s | %s | %s |' % (k, v_['fixed_N_max'], v_['fixed_last_N'], v_['revised_last_N'], v_['revised_completed'], v_['revised_declared'], v_['executes_past_cap'], f4(v_['fixed_radius']), f4(v_['revised_radius'])))
    P(); P('## 3. Inference gate (exposed, observed only): **%s**; ER gain retained: %s' % (G['inference']['status'], G['inference']['er_gain_retained'])); P()
    P('| input | failure | archived incumbent r | seed | INCUMBENT r (outcome) | HB_FIXED r (outcome) | HB_REVISED r (outcome) | revised / fixed | revised / incumbent | DGP8 HB r |'); P('|---|---|---:|---|---|---|---|---:|---:|---:|')
    for t, r in G['inference']['per_input'].items():
        for s, x in r['seeds'].items(): P('| %s | %s | %s | %s | %s (%s) | %s (%s) | %s (%s) | %s | %s | %s |' % (t, r['current_failure'], f4(r['incumbent_archived_best_worst_radius']), s, f4(x['worst']['INCUMBENT']), x['outcome']['INCUMBENT'], f4(x['worst']['HB_FIXED']), x['outcome']['HB_FIXED'] if not x['refusal']['HB_FIXED'] else x['refusal']['HB_FIXED'], f4(x['worst']['HB_REVISED']), x['outcome']['HB_REVISED'] if not x['refusal']['HB_REVISED'] else x['refusal']['HB_REVISED'], f2(x['ratio_revised_over_fixed']), f2(x['ratio_revised_over_incumbent']), f4(x['dgp8_heatbath_radius'])))
    P(); P('New completions (both seeds, current failures): %s.' % (G['inference']['new_completions'] or 'NONE')); P()
    P('## 4. Preservation and cost gate: **%s**' % G['preservation_cost']['status']); P()
    for k, v_ in G['preservation_cost']['cohorts'].items(): P('- %s: cohort %d, ran %d, complete %d, lost %s, gained %s, not run %d' % (k, v_['cohort_size'], v_['ran'], v_['complete'], v_['lost'], v_['gained'], len(v_['not_run'])))
    o = G['preservation_cost']['overhead']; P('- overhead where INCUMBENT and a heat-bath arm both complete: %d mutual completions, median ratio %s, flags %s' % (o['mutual_completions'], f2(o['median_ratio']), o['flags'])); P('- passing cases where a standalone heat-bath arm does NOT complete while INCUMBENT does: %s' % G['preservation_cost']['standalone_hb_loses_on_passing_cases']); P()
    P('## 5. Generalization gate (fresh inputs, separately): **%s**' % G['generalization']['status']); P()
    P('| fresh input | seed | INCUMBENT r | HB_FIXED r (eligible) | HB_REVISED r (eligible, attempts) | completions |'); P('|---|---|---:|---|---|---|')
    for t, per in G['generalization']['fresh'].items():
        for s, x in per.items(): P('| %s | %s | %s | %s (%s) | %s (%s, %s) | %s |' % (t, s, f4(x['worst']['INCUMBENT']), f4(x['worst']['HB_FIXED']), x['eligible']['HB_FIXED'], f4(x['worst']['HB_REVISED']), x['eligible']['HB_REVISED'], x['revised_attempts'], [a for a, c in x['complete'].items() if c]))
    P(); P('## 6. Which term limits the result (per heat-bath cell)'); P(); P('Counts: %s.' % R['verdict_inputs']['limiting_term_counts']); P()
    P('| cell | term | N recorded | N needed for epsilon | reachable at the measured rate | needed / reachable | burn-in share | publication share | stop |'); P('|---|---|---:|---:|---:|---:|---:|---:|---|')
    for k, v_ in R['verdict_inputs']['limiting_terms'].items(): P('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (k, v_.get('term'), v_.get('N_recorded'), ('%.3g' % v_['N_needed_for_epsilon']) if isinstance(v_.get('N_needed_for_epsilon'), (int, float)) else '-', ('%.3g' % v_['reachable_at_measured_rate']) if isinstance(v_.get('reachable_at_measured_rate'), (int, float)) else '-', f2(v_.get('ratio_needed_over_reachable')), f2(v_.get('burn_in_share')), f2(v_.get('publication_share')), v_.get('sampling_stop') or v_.get('refusal') or '-'))
    P(); P('## 7. Screen (development streams; the frozen rate model)'); P()
    P('| input | eligible | width | gap | refusal | chain | steps / s | fast-path share | fallbacks | checkpoint overhead s | burn-in | attempts |'); P('|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|')
    for r in R['verdict_inputs']['screen']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], r['eligible'], f4(r['width']), ('%.3g' % r['gap_g']) if isinstance(r['gap_g'], (int, float)) else '-', r['refusal_kind'], r['chain'], ('%.3g' % r['dev_steps_per_second']) if isinstance(r['dev_steps_per_second'], (int, float)) else '-', f2(r['fast_path_share']), r['exact_fallbacks'], ('%.4f' % r['checkpoint_overhead_s']) if isinstance(r['checkpoint_overhead_s'], (int, float)) else '-', r['burn_in_steps'], r['attempts']))
    rm = R['verdict_inputs'].get('rate_model') or {}; P(); P('Frozen rate model: %s' % json.dumps({k: round(v['steps_per_s_floor']) for k, v in (rm.get('classes') or {}).items()})); P()
    P('## 8. Charges'); P(); P('Total %.1f s of the %s s ceiling (%d receipts; %s; unique receipt ids %s). By scope: %s. Reassignments: %s. Launches without a receipt: %s.' % (ch['total_s'], ch['ceiling_s'], ch['n_receipts'], json.dumps(ch['by_outcome']), ch['unique_jids'], json.dumps(ch['by_scope_s']), json.dumps(ch.get('reassignments'), default=str)[:300], ch.get('spawned_without_receipt'))); P()
    P('## 9. Distinctions and limitations'); P()
    P('- An INVALID CERTIFICATE (a published or enclosed interval not containing the truth) was not observed on any fixture or cell after the repairs; the review\'s counterexamples (uniform 1e-200 triangle; cancellation; clipped points; scalar Z) are controls D82-D85 and probes RV1-RV7.'); P('- A PUBLIC WRONG ANSWER on the pinned parent (six rows excluding 1/2) is reproduced in controls/before; none exists at the frozen commit.'); P('- RESOURCE VIOLATIONS: see gate 1 (ledger identity on every heat-bath cell; admission before staging) and D86 / D89.'); P('- PACKAGING: the external identity manifest, the reconciled ledger and the restored-packet test are in IDENTITY_EXTERNAL.json / DGP9_FINAL_LEDGER_SIDECAR.json / reproduce_test/.'); P('- Standalone heat-bath arms may lose to the incumbent on passing cases (gate 4); no integrated selector exists, so no deployment claim is made.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md written (%d lines)' % len(L))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'analyze'
    analyze() if cmd == 'analyze' else report()
