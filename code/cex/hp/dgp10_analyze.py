"""DGP10 committed analyzer (FROZEN_EXPERIMENT_SPEC sections 7, 9): every count / table is derived from the raw cells (runs/<sub>/<dir>/cell.json + result.json), the manifests, the control / probe / oracle receipts and the ledger. Writes
RESULTS.json (tables per sub: 'screen' (RESPONSE_SCREEN development streams), 'main' (12 exposed inputs x INCUMBENT_R / HB_R / RESPONSE x seeds 0 / 1), 'fresh' (7), 'preservation_24' / '_18' / '_13' (INCUMBENT_R); the SEVEN GATES kept
separate: validity_resources, response_execution, material_partial_accuracy, completion, preservation, cost, generalization; the limiting-term classification per heat-bath cell), DIAGNOSTICS.json, RUN_MANIFEST.json, CHARGES.json, REPORT.md.
The partial-accuracy metric (spec gate 3): per ORIGINAL coordinate the final timely checked confidence enclosure [L, H] (published rows AND wider-than-epsilon enclosures of the heat-bath arms), radius (H - L) / 2, [0, 1] -> 0.5 when none;
the maximum over the complete inventory; never improved by dropping rows; the same metric for every arm. usage: dgp10_analyze.py [analyze | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
RD = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE'); DGP9 = os.path.join(os.path.dirname(RD), 'DGP9_SPECTRAL_HEATBATH_CONTINUATION'); DGP7 = os.path.join(os.path.dirname(RD), 'DGP7_RESIDUAL_JOINT')
ARMS = ['INCUMBENT_R', 'HB_R', 'RESPONSE']; HB_ARMS = ('HB_R', 'RESPONSE', 'RESPONSE_SCREEN'); DIAG_ARMS = ['RESPONSE_SCREEN']; EPS = 0.005; DELTA = 1e-6
SUBS = ('screen', 'main', 'fresh', 'preservation_24', 'preservation_18', 'preservation_13'); PRIMARY = ['dg_n64_c2_er50_half', 'dg_n64_c2_clique_half', 'dg_n64_c4_er50_half', 'dg_n64_c4_clique_half', 'dg_n32_c4_er50_half']; ANCHORS = ['dg_n64_c4_er50_half', 'dg_n64_c4_clique_half']; PASSING_N32 = ['dg_n32_c4_er50_half', 'dg_n32_c4_er50_half__eval9']
HB_SUCCESS_CELLS = [('dg_n64_c2_er50_half', 0), ('dg_n64_c2_er50_half__eval9', 0), ('dg_n64_c2_er50_half__eval9', 1)]
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
    """spec gate 3: per ORIGINAL coordinate the final timely checked enclosure radius -- published rows (every arm) and the heat-bath arms' informative enclosures; 0.5 for a coordinate without any; only timely (hard_deadline_respected) cells"""
    d = c['_result']
    if d is None: return None, None
    K = d.get('K') or 0; rows = d.get('answers') or []; rad = {}; timely = d.get('hard_deadline_respected') is not False
    if timely:
        for a in rows:
            key = (a['var'], a['state'])
            if a.get('guarantee') != 'NOT_PUBLISHED': rad[key] = float(F(str(a['hi'])) - F(str(a['lo']))) / 2
        if c['arm'] in HB_ARMS:
            for e in d.get('enclosures') or []:
                key = (e['var'], e['state']); w = float(F(str(e['hi'])) - F(str(e['lo']))) / 2
                if key not in rad or w < rad[key]: rad[key] = w
    full = [rad.get((a['var'], a['state']), 0.5) for a in rows] if rows else ([0.5] * K if K else [])
    return full, dict(K=K, published=sum(1 for a in rows if a.get('guarantee') != 'NOT_PUBLISHED'), informative=sum(1 for w in full if w < 0.5), width_max=(2 * max(full) if full else None), timely=timely)


def cell_row(c):
    full, info = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}; hb = c.get('heatbath') if c['arm'] in HB_ARMS else None; rs = c.get('response') if c['arm'] in ('RESPONSE', 'RESPONSE_SCREEN') else None
    if rs is not None:
        # The compact cell record omits B. Recover the frozen physical scale
        # from the raw result rather than guessing it from cardinality.
        rs = dict(rs, moment_bounds=(m.get('response') or {}).get('B') or {})
    late = bool(d.get('published')) and d.get('hard_deadline_respected') is False
    return dict(complete=bool(c.get('complete')), outcome=c.get('outcome'), receipt_outcome=c.get('receipt_outcome'), receipt_wall_s=c.get('receipt_wall_s'), solver_wall_s=c.get('solver_wall_s'), published=c.get('published'), K=c.get('K'), identity_ok=c.get('identity_ok'), hard_deadline_respected=c.get('hard_deadline_respected'), late_rows=late, seed=c.get('seed'), seed_index=c.get('seed_index', 0), seed_tag=c.get('seed_tag'), dir=os.path.relpath(c['_dir'], RD),
                worst_radius=(max(full) if full else None), median_radius=(med(full) if full else None), covered_at_eps=(sum(1 for w in full if w <= EPS) if full else None), inventory=info, ledger_identity=m.get('constructor_live_ledger_identity'), defect=(m.get('defect') or m.get('candidate_defect') or m.get('certificate_defect') or m.get('internal_error')), heatbath=hb, response=rs, rate_model_file=c.get('rate_model_file'), peak_rss_bytes=c.get('peak_rss_bytes'),
                refusal=((hb or {}).get('refusal_kind') if hb else (m.get('refusal') or {}).get('kind') if isinstance(m.get('refusal'), dict) else None), phases_s=d.get('phases_s'))


def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0)), {})[c['arm']] = cell_row(c)
    return by, cs


def moment_inflation(group, bounds):
    """Compare physical U with B*y_max, where y_max estimates Y/B."""
    try:
        bound = F(str(bounds[str(group['k'])]))
        normalized = F(str(group['y_max']))
        upper = F(str(group['U']))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if bound <= 0 or normalized <= 0 or upper < 0:
        return None
    return float(upper / (bound * normalized))


def limiting_term(hb, rs, contract_work_s=19.0):
    """which term limits a heat-bath / response cell: admission (typed refusal), observation_overhead (RESPONSE recorded fewer transitions than HB_R by > 15 %: reported by the caller), gap (the N needed for epsilon exceeds what the measured
    rate could record in the whole allowance), draw_rate (within 2x), checkpoint_loss (local count at the last completed local checkpoint < 80 % of the visits), moment_conservatism (U / (B*y_max) > 2), mean_tail (R / arithmetic >= ... the
    statistical radius dominates), burn_in (> 25 %), publication_cost (> 10 %), none (epsilon reached)"""
    if not hb: return dict(term='no_cell')
    if hb.get('refusal_kind'): return dict(term='admission', refusal=hb.get('refusal_kind'))
    r = hb.get('worst_radius_on_inventory'); N = hb.get('certified_N') or hb.get('transitions_recorded'); rate = hb.get('steps_per_second'); ph = hb.get('phases_s') or {}; tot = sum(v for v in ph.values() if isinstance(v, (int, float))) or 1.0
    if not (isinstance(r, (int, float)) and r > 0 and N): return dict(term='no_certificate')
    N_eps = N * (r / EPS) ** 2; reachable = (rate or 0) * max(0.0, contract_work_s - (ph.get('witness') or 0) - (ph.get('certificate_setup') or 0) - (ph.get('chain_construct') or 0) - (ph.get('burn_in') or 0) - 0.35); burn_share = (ph.get('burn_in') or 0) / tot; pub_share = ((ph.get('publication') or 0) + (ph.get('response_certificate') or 0) + (ph.get('response_intersection') or 0) + sum(c.get('checkpoint_overhead_s') or 0 for c in (hb.get('checkpoints') or []))) / tot
    extra = {}
    if rs and rs.get('executed'):
        lc = rs.get('local_counts') or {}; gr = rs.get('groups') or []; tr = hb.get('transitions_recorded') or 0; n_act = (rs.get('risks') or {}) and None
        if gr:
            g0 = max(gr, key=lambda g: g.get('M') or 0)
            bounds = rs.get('moment_bounds') or {}
            extra = dict(moment_inflation=moment_inflation(g0, bounds),
                         moment_scale_B=bounds.get(str(g0.get('k'))),
                         moment_inflation_rule='physical U / (B * normalized y_max)',
                         U=g0.get('U'), U_mode=g0.get('U_mode'), R=g0.get('R'),
                         local_M=g0.get('M'),
                         checkpoint_utilization=((g0.get('M') * (g0.get('sites') or 1)) / tr if (g0.get('M') and tr) else None))
    if r <= EPS: term = 'none (epsilon reached)'
    elif burn_share > 0.25: term = 'burn_in'
    elif rs and rs.get('executed') and extra.get('moment_inflation') and extra['moment_inflation'] > 2.0: term = 'moment_conservatism'
    elif rs and rs.get('executed') and extra.get('checkpoint_utilization') is not None and extra['checkpoint_utilization'] < 0.8: term = 'local_checkpoint_loss'
    elif N_eps > reachable * 2: term = 'gap'
    elif N_eps > reachable: term = 'draw_rate'
    elif pub_share > 0.10: term = 'publication_cost'
    else: term = 'checkpoint_loss'
    return dict(term=term, N_recorded=N, N_needed_for_epsilon=N_eps, reachable_at_measured_rate=reachable, ratio_needed_over_reachable=(N_eps / reachable if reachable else None), burn_in_share=burn_share, publication_share=pub_share, sampling_stop=hb.get('sampling_stop'), checkpoints=(hb.get('checkpoints_completed'), hb.get('checkpoints_declared')), **extra)


def analyze():
    man, tp = panels(); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code'].get('commit'), freeze_sha256=(sha(os.path.join(RD, 'FREEZE.json')) if os.path.exists(os.path.join(RD, 'FREEZE.json')) else None), tables={}, completions_by_sub={}, verdict_inputs={}, gates={})
    meta = {}
    for p in tp.values():
        for t in p: meta.setdefault(t['name'], t)
    for sub in SUBS:
        by, cs = table(sub)
        if not cs: continue
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], role=meta.get(k[0], {}).get('role'), family=(meta.get(k[0], {}).get('family') or meta.get(k[0], {}).get('topology')), coupling=meta.get(k[0], {}).get('coupling'), n=meta.get(k[0], {}).get('n'), card=meta.get(k[0], {}).get('card'), archived_incumbent=meta.get(k[0], {}).get('archived_incumbent'), archived_dgp9=meta.get(k[0], {}).get('archived_dgp9'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][1], PRIMARY.index(kv[0][0]) if kv[0][0] in PRIMARY else 99, kv[0][0]))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- gate 1: validity / resources
    q = os.path.join(RD, 'controls', 'qual'); ctl = load(os.path.join(q, 'CONTROLS_DGP_90.json')) or {}; ctl10 = load(os.path.join(q, 'CONTROLS_DGP10.json')) or {}; orc = load(os.path.join(q, 'ORACLE.json')) or {}; pa = load(os.path.join(RD, 'controls', 'after', 'PROBES_SUMMARY.json')) or {}; pb = load(os.path.join(RD, 'controls', 'before', 'PROBES_SUMMARY.json')) or {}
    suites = {n: ((load(os.path.join(q, f)) or {}).get('all_ok')) for n, f in (('hp', 'CONTROLS_HP.json'), ('unified', 'CONTROLS_UNIFIED.json'), ('revision', 'CONTROLS_REVISION.json'))}; refs = load(os.path.join(RD, 'controls', 'bootstrap', 'references_receipt.json')) or {}
    all_cells = [c for sub in SUBS for c in cells_of(sub)]; hb_cells = [c for c in all_cells if c['arm'] in HB_ARMS]
    late = [os.path.relpath(c['_dir'], RD) for c in all_cells if (c.get('published') or 0) > 0 and c.get('hard_deadline_respected') is False]; bad_ident = [os.path.relpath(c['_dir'], RD) for c in all_cells if c.get('identity_ok') is False]
    bad_ledger = [os.path.relpath(c['_dir'], RD) for c in hb_cells if ((c.get('_result') or {}).get('mechanism') or {}).get('constructor_live_ledger_identity') is not True]; internal = [os.path.relpath(c['_dir'], RD) for c in hb_cells if ((c.get('heatbath') or {}).get('refusal_kind') in ('INTERNAL',))]
    resp_cells = [c for c in all_cells if c['arm'] == 'RESPONSE']; obs_invalid = [os.path.relpath(c['_dir'], RD) for c in resp_cells if ((c.get('response') or {}).get('observer_state') or {}).get('valid') is False]; conflicts = [os.path.relpath(c['_dir'], RD) for c in resp_cells if (c.get('response') or {}).get('conflicts')]
    validity = dict(controls_D1_D90=dict(all_ok=ctl.get('all_ok'), n=ctl.get('n'), n_ok=ctl.get('n_ok'), failed=[c['control'] for c in (ctl.get('controls') or []) if not c.get('ok')]), controls_D91_D102=dict(all_ok=ctl10.get('all_ok'), n=ctl10.get('n'), n_ok=ctl10.get('n_ok'), failed=[c['control'] for c in (ctl10.get('controls') or []) if not c.get('ok')]), oracle_gate=orc.get('gate'), oracle_nonvacuous=orc.get('nonvacuous_models'),
                    probes_after=pa, probes_before=pb, suites=suites, packet_references_all_ok=(refs.get('all_ok') if refs else None), late_rows=late, identity_failures=bad_ident, heatbath_ledger_identity_failures=bad_ledger, internal_errors=internal, observer_invalidations=obs_invalid, intersection_conflicts=conflicts, cells=len(all_cells), heatbath_cells=len(hb_cells))
    v_ok = bool(ctl.get('all_ok')) and bool(ctl10.get('all_ok')) and orc.get('gate') == 'PASS' and pa.get('all_absent') is True and pb.get('all_present') is True and all(suites.values()) and refs.get('all_ok') is True and not late and not bad_ident and not bad_ledger and not internal and not obs_invalid
    validity['status'] = 'PASS' if v_ok else ('INCOMPLETE' if not (ctl and ctl10 and orc) else 'FAIL'); res['gates']['validity_resources'] = validity
    main = {(r['task'], r['seed_index']): r for r in res['tables'].get('main', [])}; fresh = {(r['task'], r['seed_index']): r for r in res['tables'].get('fresh', [])}
    def arm_cell(rows, task, seed, arm): return ((rows.get((task, seed)) or {}).get('arms') or {}).get(arm)
    def wr(cell): return (cell or {}).get('worst_radius')
    # ---- gate 2: response execution on the card-4 anchors
    ex = {}
    for t in ANCHORS:
        for s in (0, 1):
            c = arm_cell(main, t, s, 'RESPONSE') or {}; rs = c.get('response') or {}; gr = rs.get('groups') or []
            ex['%s/seed%d' % (t, s)] = dict(executed=rs.get('executed'), unavailable=rs.get('unavailable'), observer_valid=((rs.get('observer_state') or {}).get('valid')), local_counts=rs.get('local_counts'), groups=rs.get('n_groups'), certified=rs.get('n_certified'), checked_U=[g.get('U') for g in gr if g.get('available')], U_modes=[g.get('U_mode') for g in gr if g.get('available')], R=[g.get('R') for g in gr if g.get('available')], response_worst=((rs.get('radius') or {}).get('response_worst')), raw_worst=((rs.get('radius') or {}).get('raw_worst')), intersected_worst=((rs.get('radius') or {}).get('intersected_worst')), nontrivial=(isinstance((rs.get('radius') or {}).get('response_worst'), (int, float)) and (rs.get('radius') or {}).get('response_worst') < 0.5))
    ex_ok = bool(ex) and all(v['executed'] is True and (v['certified'] or 0) >= 1 and v['nontrivial'] and any(mode == 'checked' for mode in v['U_modes']) for v in ex.values()); res['gates']['response_execution'] = dict(status=('PASS' if ex_ok else ('NOT RUN' if not main else 'FAIL')), anchors=ex, rule='actual conditional observations, local snapshots, a CHECKED moment U (not the deterministic support fallback alone) and checked mean certificates on both exposed card-4 anchors in both seeds')
    # ---- gate 3: material partial accuracy (2x) on both anchors in both seeds
    pa_rows = {}
    for t in ANCHORS:
        for s in (0, 1):
            hr = arm_cell(main, t, s, 'HB_R'); rp = arm_cell(main, t, s, 'RESPONSE'); inc = arm_cell(main, t, s, 'INCUMBENT_R'); w_h = wr(hr); w_r = wr(rp)
            pa_rows['%s/seed%d' % (t, s)] = dict(HB_R_worst=w_h, RESPONSE_worst=w_r, INCUMBENT_R_worst=wr(inc), ratio=((w_r / w_h) if (isinstance(w_r, (int, float)) and isinstance(w_h, (int, float)) and w_h > 0) else None), meets_half=(isinstance(w_r, (int, float)) and isinstance(w_h, (int, float)) and w_r <= 0.5 * w_h), HB_R_refused=(hr or {}).get('refusal'), RESPONSE_refused=(rp or {}).get('refusal'), both_timely=(((hr or {}).get('inventory') or {}).get('timely') and ((rp or {}).get('inventory') or {}).get('timely')), HB_R_median=(hr or {}).get('median_radius'), RESPONSE_median=(rp or {}).get('median_radius'))
    pa_ok = bool(pa_rows) and all(v['meets_half'] and not v['HB_R_refused'] and not v['RESPONSE_refused'] for v in pa_rows.values())
    fresh_an = {}
    for (t, s), r in sorted(fresh.items()):
        if 'c4' in t and 'half' in t:
            A = r['arms']; w_h = wr(A.get('HB_R')); w_r = wr(A.get('RESPONSE')); ref_h = (A.get('HB_R') or {}).get('refusal'); ref_r = (A.get('RESPONSE') or {}).get('refusal')
            if ref_h or ref_r: fresh_an['%s/seed%d' % (t, s)] = dict(HB_R_worst=w_h, RESPONSE_worst=w_r, ratio=None, meets_half=None, classified='comparator refused (%s / %s): not a mechanism ratio' % (ref_h, ref_r))        # (harness amendment 3: a refused comparator is classified separately, never a 0.5 / 0.5 ratio)
            else: fresh_an['%s/seed%d' % (t, s)] = dict(HB_R_worst=w_h, RESPONSE_worst=w_r, ratio=((w_r / w_h) if (isinstance(w_r, (int, float)) and isinstance(w_h, (int, float)) and w_h > 0) else None), meets_half=(isinstance(w_r, (int, float)) and isinstance(w_h, (int, float)) and w_r <= 0.5 * w_h))
    all_ratios = {}
    for sub, rows in (('main', main), ('fresh', fresh)):
        for (t, s), r in sorted(rows.items()):
            A = r['arms']; w_h = wr(A.get('HB_R')); w_r = wr(A.get('RESPONSE')); w_i = wr(A.get('INCUMBENT_R')); all_ratios['%s/%s/seed%d' % (sub, t, s)] = dict(INCUMBENT_R=w_i, HB_R=w_h, RESPONSE=w_r, response_over_hb=((w_r / w_h) if (isinstance(w_r, (int, float)) and isinstance(w_h, (int, float)) and w_h > 0) else None), response_over_incumbent=((w_r / w_i) if (isinstance(w_r, (int, float)) and isinstance(w_i, (int, float)) and w_i > 0) else None), refusals={a: (A.get(a) or {}).get('refusal') for a in ARMS})
    res['gates']['material_partial_accuracy'] = dict(status=('PASS' if pa_ok else ('NOT RUN' if not main else 'FAIL')), anchors=pa_rows, fresh_card4_analogues=fresh_an, all_cells=all_ratios, rule='RESPONSE worst original-inventory radius <= 1/2 x same-round HB_R worst radius on BOTH exposed card-4 anchors in BOTH seeds; [0,1] -> 0.5 for a coordinate without a timely checked enclosure; refused comparators classified separately (never 0.5 / 0.5 ratios)')
    # ---- gate 4: completion (both seeds; exposed / fresh separately; one-seed separately)
    def completion_table(rows):
        out = {}
        for (t, s), r in rows.items():
            e = out.setdefault(t, {a: {} for a in ARMS})
            for a in ARMS: e[a][s] = bool((r['arms'].get(a) or {}).get('complete'))
        summ = {}
        for t, e in out.items():
            inc = (meta.get(t) or {}).get('archived_incumbent') or {}; d9 = (meta.get(t) or {}).get('archived_dgp9') or {}
            # harness amendment 3 (classification only): 'current failure' = the archived incumbent record when one exists (DGP6-DGP8 REPAIRED / BASE never completed), else the SAME-ROUND INCUMBENT_R not completing in both seeds AND the
            # archived DGP9 INCUMBENT (when recorded) not completing; a 'new completion' = both seeds complete on a current failure (the spec's both-seeds rule; the incumbent's failure is what makes it NEW)
            inc_same_round_fails = not (e['INCUMBENT_R'].get(0, False) and e['INCUMBENT_R'].get(1, False)); d9_inc = [((d9.get(str(s_)) or {}).get('INCUMBENT') or {}).get('complete') for s_ in (0, 1)]
            cur_fail = inc.get('current_failure') if inc.get('current_failure') is not None else (inc_same_round_fails and not any(d9_inc))
            summ[t] = dict(current_failure=cur_fail, current_failure_basis=('archived incumbent (DGP6-DGP8)' if inc.get('current_failure') is not None else 'same-round INCUMBENT_R (both seeds) and the archived DGP9 INCUMBENT'), incumbent_r_same_round_both_seeds=(not inc_same_round_fails), both_seeds={a: (e[a].get(0, False) and e[a].get(1, False)) for a in ARMS}, one_seed={a: [s for s in (0, 1) if e[a].get(s)] for a in ARMS}, new_completion={a: (e[a].get(0, False) and e[a].get(1, False) and bool(cur_fail)) for a in ('HB_R', 'RESPONSE')}, dgp9_hb_revised_complete={s: ((d9.get(str(s)) or {}).get('HB_REVISED') or {}).get('complete') for s in (0, 1)}, dgp9_incumbent_complete={s: d9_inc[s] for s in (0, 1)})
        return summ
    comp_main = completion_table(main); comp_fresh = completion_table(fresh)
    newc = [t for t, v in comp_main.items() if v['new_completion']['RESPONSE'] or v['new_completion']['HB_R']]; newc_f = [t for t, v in comp_fresh.items() if v['new_completion']['RESPONSE'] or v['new_completion']['HB_R']]
    res['gates']['completion'] = dict(status=(('NEW COMPLETION (exposed %s; fresh %s)' % (newc, newc_f)) if (newc or newc_f) else ('NO NEW COMPLETION' if main else 'NOT RUN')), exposed=comp_main, fresh=comp_fresh, new_completions_exposed=newc, new_completions_fresh=newc_f, one_seed_only={t: {a: v['one_seed'][a] for a in ('HB_R', 'RESPONSE') if v['one_seed'][a] and not v['both_seeds'][a]} for t, v in list(comp_main.items()) + list(comp_fresh.items()) if any(v['one_seed'][a] and not v['both_seeds'][a] for a in ('HB_R', 'RESPONSE'))}, rule='every original coordinate epsilon-published with positive mass and a valid timely receipt in BOTH seeds of a model; wide valid enclosures count for partial accuracy only; one-seed completions reported separately')
    # ---- gate 5: preservation (INCUMBENT_R cohorts; RESPONSE keeps the DGP9 HB successes; passing n32 across arms)
    # harness amendment 5: the cohort membership comes from the SHIPPED manifests (every member of the 24 / 18 / 13 panels is a historical completion by the panels' definition); the sibling DGP7 records are an optional cross-check only (not shipped: a restored analysis must not depend on them)
    hist24 = {t['name']: True for t in tp.get('preservation_24', [])}; hist7 = {sub: {t['name']: True for t in tp.get(sub, [])} for sub in ('preservation_18', 'preservation_13')}; d7 = load(os.path.join(DGP7, 'RESULTS.json')) or {}; cross7 = {sub: {r['task']: (r['arms'].get('REPAIRED') or {}).get('complete') for r in (d7.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}
    pres = {}
    for sub, hist in (('preservation_24', hist24), ('preservation_18', hist7['preservation_18']), ('preservation_13', hist7['preservation_13'])):
        rows = res['tables'].get(sub, []); ran = {r['task'] for r in rows if 'INCUMBENT_R' in r['arms']}; comp = {r['task'] for r in rows if (r['arms'].get('INCUMBENT_R') or {}).get('complete')}; lost = sorted(n for n in ran if hist.get(n) and n not in comp)
        pres[sub] = dict(cohort_size=len(hist), ran=len(ran), complete=len(comp), lost=lost, gained=sorted(n for n in comp if not hist.get(n)), not_run=sorted(n for n in hist if n not in ran), status=('NOT RUN' if not rows else ('PRESERVED %d / %d' % (len(comp), len(ran)) if not lost else 'LOST %s' % lost)), dgp7_cross_check=(('all %d members complete in DGP7 REPAIRED' % len(hist)) if cross7.get(sub) and all(cross7[sub].get(n) for n in hist) else ('DGP7 records not available here' if not cross7.get(sub) else 'DIFFERS: %s' % sorted(n for n in hist if not cross7[sub].get(n)))) if sub != 'preservation_24' else 'the DGP6 historical 24 (manifest)')
    keep = {}
    for (t, s) in HB_SUCCESS_CELLS:
        c = arm_cell(main, t, s, 'RESPONSE'); keep['%s/seed%d' % (t, s)] = dict(RESPONSE_complete=bool((c or {}).get('complete')), RESPONSE_worst=wr(c), HB_R_complete=bool((arm_cell(main, t, s, 'HB_R') or {}).get('complete')), HB_R_worst=wr(arm_cell(main, t, s, 'HB_R')), dgp9_radius=(((meta.get(t) or {}).get('archived_dgp9') or {}).get(str(s)) or {}).get('HB_REVISED', {}).get('radius'), seed=(c or {}).get('seed'))
    n32 = {}
    for t in PASSING_N32:
        for s in (0, 1):
            if (t, s) in main: n32['%s/seed%d' % (t, s)] = {a: dict(complete=bool((arm_cell(main, t, s, a) or {}).get('complete')), worst=wr(arm_cell(main, t, s, a)), receipt_s=(arm_cell(main, t, s, a) or {}).get('receipt_wall_s')) for a in ARMS}
    pres_ok = all(v['status'].startswith('PRESERVED') and v['ran'] == v['cohort_size'] for v in pres.values()) and all(v['RESPONSE_complete'] for v in keep.values())
    res['gates']['preservation'] = dict(status=('PASS' if pres_ok else ('NOT RUN' if not any(res['tables'].get(s_) for s_ in ('preservation_24', 'preservation_18', 'preservation_13')) else 'FAIL')), cohorts=pres, response_keeps_dgp9_hb_successes=keep, passing_n32_across_arms=n32, rule='INCUMBENT_R 24/24, 18/18, 13/13 under the original contracts; RESPONSE keeps every successful DGP9 HB seed-cell (dg_n64_c2_er50_half seed 0; __eval9 seeds 0 and 1); any loss is a failure; no SELECT -> no deployability claim')
    # ---- gate 6: cost (mutual completions; 1.25x and 0.1 s) + full cost decomposition
    cost = []; decomp = []
    for sub in ('main', 'fresh'):
        for r in res['tables'].get(sub, []):
            A = r['arms']; inc_ = A.get('INCUMBENT_R')
            for arm in ('HB_R', 'RESPONSE'):
                h = A.get(arm)
                if inc_ and h and inc_['complete'] and h['complete']: cost.append(dict(sub=sub, task=r['task'], seed_index=r['seed_index'], arm=arm, INCUMBENT_R_s=inc_['receipt_wall_s'], arm_s=h['receipt_wall_s'], ratio=h['receipt_wall_s'] / inc_['receipt_wall_s'], flag=bool(h['receipt_wall_s'] - inc_['receipt_wall_s'] >= 0.1 and h['receipt_wall_s'] / inc_['receipt_wall_s'] >= 1.25)))
            hr = A.get('HB_R'); rp = A.get('RESPONSE')
            if hr and rp and hr['complete'] and rp['complete']: cost.append(dict(sub=sub, task=r['task'], seed_index=r['seed_index'], arm='RESPONSE_vs_HB_R', INCUMBENT_R_s=hr['receipt_wall_s'], arm_s=rp['receipt_wall_s'], ratio=rp['receipt_wall_s'] / hr['receipt_wall_s'], flag=bool(rp['receipt_wall_s'] - hr['receipt_wall_s'] >= 0.1 and rp['receipt_wall_s'] / hr['receipt_wall_s'] >= 1.25)))
            for arm in ('HB_R', 'RESPONSE'):
                h = A.get(arm)
                if h and h.get('phases_s'): decomp.append(dict(sub=sub, task=r['task'], seed_index=r['seed_index'], arm=arm, phases_s=h['phases_s'], receipt_s=h.get('receipt_wall_s'), transitions_recorded=(h.get('heatbath') or {}).get('transitions_recorded'), steps_per_s=(h.get('heatbath') or {}).get('steps_per_second'), checker_calls=((h.get('response') or {}).get('checker_calls') if arm == 'RESPONSE' else None)))
    res['gates']['cost'] = dict(status=('REPORTED (%d mutual completions, %d flags)' % (len(cost), sum(1 for x in cost if x['flag'])) if cost else ('NO MUTUAL COMPLETIONS' if main else 'NOT RUN')), mutual=cost, flags=[(x['sub'], x['task'], x['seed_index'], x['arm'], round(x['ratio'], 3)) for x in cost if x['flag']], median_ratio=med([x['ratio'] for x in cost]), decomposition=decomp, rule='mutual completions only: flag > 1.25x AND > 0.1 s (the established conjunction); absolute seconds reported; a smaller radius at greater total time is not an equal-cost win')
    # ---- gate 7: generalization (fresh, separately)
    gen = {}
    for (t, s), r in sorted(fresh.items()):
        A = r['arms']; gen.setdefault(t, {})[s] = dict(worst={a: wr(A.get(a)) for a in ARMS}, complete={a: bool((A.get(a) or {}).get('complete')) for a in ARMS}, eligible={a: ((A.get(a) or {}).get('heatbath') or {}).get('eligible') for a in ('HB_R', 'RESPONSE')}, refusal={a: (A.get(a) or {}).get('refusal') for a in ARMS}, response_executed=((A.get('RESPONSE') or {}).get('response') or {}).get('executed'))
    res['gates']['generalization'] = dict(status=('REPORTED SEPARATELY (fresh, %d inputs)' % len(gen) if gen else 'NOT RUN'), fresh=gen, card4_half_gate_analogue=fresh_an, note='fresh results stay separate; strong refusal is not a mixing claim; two seeds confirm a model, not two-model generalization')
    # ---- limiting terms + attribution per cell
    lim = {}; attrib = {}
    for sub in ('main', 'fresh'):
        for r in res['tables'].get(sub, []):
            for arm in ('HB_R', 'RESPONSE'):
                h = (r['arms'].get(arm) or {}).get('heatbath'); rs = (r['arms'].get(arm) or {}).get('response')
                if h is not None: lim['%s/%s/seed%d/%s' % (sub, r['task'], r['seed_index'], arm)] = limiting_term(h, rs)
            rp = r['arms'].get('RESPONSE') or {}; rs = rp.get('response') or {}; hr = r['arms'].get('HB_R') or {}
            if rs.get('executed'):
                hb_rec = ((hr.get('heatbath') or {}).get('transitions_recorded')); rp_rec = ((rp.get('heatbath') or {}).get('transitions_recorded'))
                attrib['%s/%s/seed%d' % (sub, r['task'], r['seed_index'])] = dict(raw_occupation_same_path_full_delta=((rs.get('raw_full_delta_same_path') or {}).get('radius')), raw_reduced_delta_quarter=((rs.get('radius') or {}).get('raw_worst')), response_checked=((rs.get('radius') or {}).get('response_worst')), intersected=((rs.get('radius') or {}).get('intersected_worst')), HB_R_actual=wr(hr), observation_overhead_transitions=((rp_rec / hb_rec) if (hb_rec and rp_rec) else None), groups=rs.get('groups'), note='same stored trajectory: raw (full delta/2 diagnostic; NOT published) vs raw (delta/4, the RESPONSE raw family) vs checked response vs intersection; HB_R actual is a different trajectory (its own recorded count)')
    res['verdict_inputs']['limiting_terms'] = lim; res['verdict_inputs']['limiting_term_counts'] = {k: sum(1 for v in lim.values() if v.get('term') == k) for k in sorted({v.get('term') for v in lim.values()})}; res['verdict_inputs']['attribution_same_trajectory'] = attrib
    scr = [dict(task=r['task'], **{k: ((r['arms'].get('RESPONSE_SCREEN') or {}).get('heatbath') or {}).get(k) for k in ('eligible', 'width', 'gap_g', 'refusal_kind', 'chain', 'dev_steps_per_second', 'fast_path_share', 'exact_fallbacks', 'checkpoint_overhead_s', 'burn_in_steps')}, observer=((((r['arms'].get('RESPONSE_SCREEN') or {}).get('heatbath') or {}).get('dev_stream') or {}).get('observer'))) for r in res['tables'].get('screen', [])]
    res['verdict_inputs']['screen'] = scr; res['verdict_inputs']['rate_models'] = dict(hb=load(os.path.join(RD, 'HEATBATH_RATES.json')), response=load(os.path.join(RD, 'RESPONSE_RATES.json')))
    # ---- charges
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP10_LEDGER.jsonl'))] if os.path.exists(os.path.join(RD, 'DGP10_LEDGER.jsonl')) else []; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json')) or {}
    ch = dict(utc=res['utc'], ceiling_s=bud.get('ceiling_s'), allocation_s=bud.get('allocations'), reassignments=bud.get('reassignments'), by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), by_outcome={o: sum(1 for r in rc if r['outcome'] == o) for o in sorted({r['outcome'] for r in rc})}, within_ceiling=(sum(r['wall_s'] for r in rc) <= (bud.get('ceiling_s') or 0)), unique_jids=(len({r['jid'] for r in rc}) == len(rc)), spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r['jid'] == s['jid'] for r in rc)])
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, contract=contract))
    plan('screen', [t['name'] for t in tp.get('main_exposed', []) if t.get('name') in PRIMARY], ['RESPONSE_SCREEN'], [0], 'main'); plan('main', [t['name'] for t in tp.get('main_exposed', [])], ARMS, [0, 1], 'main'); plan('fresh', [t['name'] for t in tp.get('fresh', [])], ARMS, [0, 1], 'main')
    plan('preservation_24', [t['name'] for t in tp.get('preservation_24', [])], ['INCUMBENT_R'], [0], 'main'); plan('preservation_18', [t['name'] for t in tp.get('preservation_18', [])], ['INCUMBENT_R'], [0], 'p4'); plan('preservation_13', [t['name'] for t in tp.get('preservation_13', [])], ['INCUMBENT_R'], [0], 'p20')
    actual = {}
    for sub in SUBS:
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0))] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned: p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'])); p['reason'] = None if p['actual'] else 'not run (see REPORT.md)'
    json.dump(dict(utc=res['utc'], code_commit=fr['code'].get('commit'), planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), unplanned_actual=[k for k in actual if not any((p['sub'], p['task'], p['arm'], p['seed_index']) == k for p in planned)], amendments=[os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json'))]), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(dict(utc=res['utc'], limiting_terms=lim, attribution_same_trajectory=attrib, screen=scr, response_execution=res['gates']['response_execution'], partial_accuracy=res['gates']['material_partial_accuracy'], units='radii = half-widths of the final timely checked enclosures on the full original inventory (0.5 for absent coordinates); g = checked lower bound of the random-scan gap; eta = n g / (1 + n g); N = recorded post-burn-in states at the last completed global checkpoint; M = local visits at the last completed local checkpoint; raw_full_delta_same_path = NON-PUBLISHING diagnostic'), open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(completions=res['completions_by_sub'], validity=validity['status'], response_execution=res['gates']['response_execution']['status'], partial_accuracy=res['gates']['material_partial_accuracy']['status'], anchors={k: (round(v['ratio'], 3) if isinstance(v['ratio'], float) else v['ratio']) for k, v in pa_rows.items()}, completion=res['gates']['completion']['status'], preservation=res['gates']['preservation']['status'], cost=res['gates']['cost']['status'], generalization=res['gates']['generalization']['status'], limiting=res['verdict_inputs']['limiting_term_counts'], charged=ch['total_s']), default=str)[:2000])
    return res


def report():
    R = load(os.path.join(RD, 'RESULTS.json')); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
    G = R['gates']; ch = R['charges']
    P('# REPORT -- DGP10_QUERY_RESPONSE (conditional response certification + carried DGP9 repairs; 27 Nov 2026)'); P()
    P('Frozen pgm `%s` (branch dgp10-query-response from the DGP9 frozen d1932cf). Analyzer `dgp10_analyze.py` at the same commit; every number below is derived from the raw cells under runs/, the manifests, the control / probe / oracle receipts and the ledger. Seven gates, reported separately (FROZEN_EXPERIMENT_SPEC section 7). No SELECT; no deployability claim; nothing here is a claim about strong frustrated graphs.' % (fr['code'].get('commit') or '?')[:12]); P()
    P('## 0. What executed'); P()
    for sub, c in R['completions_by_sub'].items(): P('- %s: %d cells (%s)' % (sub, c['cells'], ', '.join('%s %d / %d complete, %d receipts COMPLETED, %d identity_ok' % (a, v['complete'], v['cells'], v['receipts_completed'], v['identity_ok']) for a, v in c['by_arm'].items())))
    v = G['validity_resources']; P(); P('## 1. Validity / resources gate: **%s**' % v['status']); P()
    P('- controls D1-D90: all_ok %s (%s / %s%s); D91-D102: all_ok %s (%s / %s%s)' % (v['controls_D1_D90'].get('all_ok'), v['controls_D1_D90'].get('n_ok'), v['controls_D1_D90'].get('n'), ('; failed ' + ', '.join(v['controls_D1_D90']['failed'])) if v['controls_D1_D90'].get('failed') else '', v['controls_D91_D102'].get('all_ok'), v['controls_D91_D102'].get('n_ok'), v['controls_D91_D102'].get('n'), ('; failed ' + ', '.join(v['controls_D91_D102']['failed'])) if v['controls_D91_D102'].get('failed') else ''))
    P('- exact oracle / reference gate: %s (nonvacuous tiny models: %s); packet references all_ok: %s; accepted suites: %s' % (v['oracle_gate'], v['oracle_nonvacuous'], v['packet_references_all_ok'], v['suites']))
    P('- carried DGP9 review probes: PRESENT on the pinned parent %s; ABSENT at the frozen commit %s (details controls/before, controls/after)' % ((v['probes_before'] or {}).get('all_present'), (v['probes_after'] or {}).get('all_absent')))
    P('- late published rows: %s; identity failures: %s; heat-bath ledger-identity failures: %s; internal errors: %s; observer invalidations: %s; intersection conflicts: %s (over %d cells, %d heat-bath cells)' % (v['late_rows'], v['identity_failures'], v['heatbath_ledger_identity_failures'], v['internal_errors'], v['observer_invalidations'], v['intersection_conflicts'], v['cells'], v['heatbath_cells'])); P()
    P('## 2. Response execution gate: **%s**' % G['response_execution']['status']); P()
    for k, a in G['response_execution']['anchors'].items(): P('- %s: executed %s; observer valid %s; local counts %s; groups %s certified %s; checked U %s (%s); R %s; response worst %s; raw worst %s' % (k, a['executed'], a['observer_valid'], a['local_counts'], a['groups'], a['certified'], [('%.5f' % u) if isinstance(u, float) else u for u in (a['checked_U'] or [])], a['U_modes'], [('%.5f' % r) if isinstance(r, float) else r for r in (a['R'] or [])], f4(a['response_worst']), f4(a['raw_worst'])))
    P(); P('## 3. Material partial-accuracy gate (2x on both exposed card-4 anchors, both seeds): **%s**' % G['material_partial_accuracy']['status']); P()
    P('| anchor / seed | INCUMBENT_R worst r | HB_R worst r | RESPONSE worst r | RESPONSE / HB_R | <= 1/2 | HB_R median | RESPONSE median |'); P('|---|---:|---:|---:|---:|---|---:|---:|')
    for k, x in G['material_partial_accuracy']['anchors'].items(): P('| %s | %s | %s | %s | %s | %s | %s | %s |' % (k, f4(x['INCUMBENT_R_worst']), f4(x['HB_R_worst']) if not x['HB_R_refused'] else x['HB_R_refused'], f4(x['RESPONSE_worst']) if not x['RESPONSE_refused'] else x['RESPONSE_refused'], f2(x['ratio']), x['meets_half'], f4(x['HB_R_median']), f4(x['RESPONSE_median'])))
    P(); P('All cells (worst radius; RESPONSE / HB_R; RESPONSE / INCUMBENT_R):'); P(); P('| cell | INCUMBENT_R | HB_R | RESPONSE | R / HB | R / INC | refusals |'); P('|---|---:|---:|---:|---:|---:|---|')
    for k, x in G['material_partial_accuracy']['all_cells'].items(): P('| %s | %s | %s | %s | %s | %s | %s |' % (k, f4(x['INCUMBENT_R']), f4(x['HB_R']), f4(x['RESPONSE']), f2(x['response_over_hb']), f2(x['response_over_incumbent']), {a: r_ for a, r_ in x['refusals'].items() if r_} or '-'))
    P(); P('## 4. Completion gate: **%s**' % G['completion']['status']); P()
    for lab, tab in (('exposed', G['completion']['exposed']), ('fresh', G['completion']['fresh'])):
        P('%s:' % lab); P()
        for t, x in tab.items(): P('- %s (current failure %s by %s): both seeds %s; one-seed %s; DGP9 HB_REVISED complete %s; DGP9 INCUMBENT complete %s' % (t, x['current_failure'], x.get('current_failure_basis'), {a: b for a, b in x['both_seeds'].items() if b} or 'none', {a: s_ for a, s_ in x['one_seed'].items() if s_} or 'none', x['dgp9_hb_revised_complete'], x.get('dgp9_incumbent_complete')))
        P()
    P('New completions (both seeds, current failures): exposed %s; fresh %s. One-seed-only completions (reported separately, not completions): %s.' % (G['completion']['new_completions_exposed'] or 'NONE', G['completion']['new_completions_fresh'] or 'NONE', G['completion'].get('one_seed_only') or 'none')); P()
    P('## 5. Preservation gate: **%s**' % G['preservation']['status']); P()
    for k, x in G['preservation']['cohorts'].items(): P('- %s: cohort %d, ran %d, complete %d, lost %s, gained %s, not run %d' % (k, x['cohort_size'], x['ran'], x['complete'], x['lost'], x['gained'], len(x['not_run'])))
    for k, x in G['preservation']['response_keeps_dgp9_hb_successes'].items(): P('- DGP9 HB success cell %s (seed %s): RESPONSE complete %s (worst %s); HB_R complete %s (worst %s); DGP9 HB_REVISED radius %s' % (k, x['seed'], x['RESPONSE_complete'], f4(x['RESPONSE_worst']), x['HB_R_complete'], f4(x['HB_R_worst']), f4(x['dgp9_radius'])))
    for k, x in G['preservation']['passing_n32_across_arms'].items(): P('- passing n32 %s: %s' % (k, {a: ('complete' if y['complete'] else f4(y['worst'])) + ' @ %ss' % f2(y['receipt_s']) for a, y in x.items()}))
    P(); P('## 6. Cost gate: **%s**' % G['cost']['status']); P(); P('Median ratio on mutual completions: %s; flags (> 1.25x and > 0.1 s): %s.' % (f2(G['cost']['median_ratio']), G['cost']['flags'])); P()
    P('| cell / arm | receipt s | phases s | transitions recorded | steps / s | checker calls |'); P('|---|---:|---|---:|---:|---:|')
    for x in G['cost']['decomposition']: P('| %s/%s/seed%d/%s | %s | %s | %s | %s | %s |' % (x['sub'], x['task'], x['seed_index'], x['arm'], f2(x['receipt_s']), {k: round(v_, 3) for k, v_ in (x['phases_s'] or {}).items()}, x['transitions_recorded'], ('%.3g' % x['steps_per_s']) if isinstance(x['steps_per_s'], (int, float)) else '-', x['checker_calls']))
    P(); P('## 7. Generalization gate (fresh, separately): **%s**' % G['generalization']['status']); P()
    P('| fresh input | seed | INCUMBENT_R r | HB_R r (eligible) | RESPONSE r (eligible, executed) | completions |'); P('|---|---|---:|---|---|---|')
    for t, per in G['generalization']['fresh'].items():
        for s, x in per.items(): P('| %s | %s | %s | %s (%s) | %s (%s, %s) | %s |' % (t, s, f4(x['worst']['INCUMBENT_R']), f4(x['worst']['HB_R']), x['eligible']['HB_R'], f4(x['worst']['RESPONSE']), x['eligible']['RESPONSE'], x['response_executed'], [a for a, c in x['complete'].items() if c]))
    P(); P('Fresh card-4 half analogues of gate 3: %s' % json.dumps({k: dict(ratio=(round(v_['ratio'], 3) if isinstance(v_['ratio'], float) else None), meets_half=v_['meets_half'], classified=v_.get('classified')) for k, v_ in G['generalization']['card4_half_gate_analogue'].items()})); P()
    P('## 8. Which term limits the result (per heat-bath cell) and same-trajectory attribution'); P(); P('Counts: %s.' % R['verdict_inputs']['limiting_term_counts']); P()
    P('| cell | term | N recorded | N needed for eps | reachable | needed / reachable | moment inflation U / y | U mode | R | local M | utilization | stop |'); P('|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|')
    for k, x in R['verdict_inputs']['limiting_terms'].items(): P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (k, x.get('term'), x.get('N_recorded'), ('%.3g' % x['N_needed_for_epsilon']) if isinstance(x.get('N_needed_for_epsilon'), (int, float)) else '-', ('%.3g' % x['reachable_at_measured_rate']) if isinstance(x.get('reachable_at_measured_rate'), (int, float)) else '-', f2(x.get('ratio_needed_over_reachable')), f2(x.get('moment_inflation')), x.get('U_mode') or '-', ('%.5f' % x['R']) if isinstance(x.get('R'), float) else '-', x.get('local_M') or '-', f2(x.get('checkpoint_utilization')), x.get('sampling_stop') or x.get('refusal') or '-'))
    P(); P('| cell | raw full delta/2 (diagnostic, NOT published) | raw delta/4 (RESPONSE raw family) | checked response | intersected (published basis) | HB_R actual (own trajectory) | RESPONSE / HB_R transitions |'); P('|---|---:|---:|---:|---:|---:|---:|')
    for k, x in R['verdict_inputs']['attribution_same_trajectory'].items(): P('| %s | %s | %s | %s | %s | %s | %s |' % (k, f4(x['raw_occupation_same_path_full_delta']), f4(x['raw_reduced_delta_quarter']), f4(x['response_checked']), f4(x['intersected']), f4(x['HB_R_actual']), f2(x['observation_overhead_transitions'])))
    P(); P('## 9. Screen (RESPONSE development streams; the frozen RESPONSE rate model)'); P()
    P('| input | eligible | width | gap | chain | steps / s (observer on) | fallbacks | checkpoint overhead s | certificate s / group | groups | burn-in |'); P('|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|')
    for r in R['verdict_inputs']['screen']: ob = r.get('observer') or {}; P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (r['task'], r['eligible'], f4(r['width']), ('%.3g' % r['gap_g']) if isinstance(r['gap_g'], (int, float)) else '-', r['chain'], ('%.3g' % r['dev_steps_per_second']) if isinstance(r['dev_steps_per_second'], (int, float)) else '-', r['exact_fallbacks'], ('%.4f' % r['checkpoint_overhead_s']) if isinstance(r['checkpoint_overhead_s'], (int, float)) else '-', ('%.4f' % ob['seconds_per_group']) if isinstance(ob.get('seconds_per_group'), (int, float)) else '-', ob.get('groups'), r['burn_in_steps']))
    rm = R['verdict_inputs'].get('rate_models') or {}; P(); P('Frozen rate models: HB_R (the exact DGP9 bytes) %s; RESPONSE %s' % (json.dumps({k: round(v_['steps_per_s_floor']) for k, v_ in ((rm.get('hb') or {}).get('classes') or {}).items()}), json.dumps({k: round(v_['steps_per_s_floor']) for k, v_ in ((rm.get('response') or {}).get('classes') or {}).items()}))); P()
    P('## 10. Charges'); P(); P('Total %.1f s of the %s s ceiling (%d receipts; %s; unique receipt ids %s; within ceiling %s). By scope: %s. Reassignments: %s. Launches without a receipt: %s.' % (ch['total_s'], ch['ceiling_s'], ch['n_receipts'], json.dumps(ch['by_outcome']), ch['unique_jids'], ch['within_ceiling'], json.dumps(ch['by_scope_s']), json.dumps(ch.get('reassignments'), default=str)[:400], ch.get('spawned_without_receipt'))); P()
    P('## 11. Distinctions'); P()
    P('- PROVED: the response identity, the observation-chain gap bound eta = n g / (1 + n g), the two-state spectral domination, the moment inversion and the Hermite mean majorant (theory note sections 3-5; the exact oracle checks them on enumerable models).'); P('- INDEPENDENTLY CHECKED ARITHMETIC: every published U / R passed the exact Fraction checker (the packet reference, byte-identical); the native enclosures were checked against exact conditionals (D92, oracle); the risk totals are <= delta (D95).'); P('- EMPIRICAL: the radii, completions, costs and preservation outcomes above (frozen protocol; two seeds; exposed and fresh separate).'); P('- FORECASTS (not results): the packet\'s floating diagnostics; the same-path raw full-delta diagnostic is NOT published and enters no gate.'); P('- UNRESOLVED: strong twins remain refused by spectral admission (not a mixing statement); no SELECT; the n32 passing case is reported against INCUMBENT_R without a combined-library claim.')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md written (%d lines)' % len(L))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'analyze'
    analyze() if cmd == 'analyze' else report()
