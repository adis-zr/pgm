"""DGP7 committed analyzer (PROTOCOL.md sections 5-7; protocol rule 8): every count / table is derived from the raw cells (runs/<sub>/<dir>/cell.json + result.json), the oracle outputs (oracle/results/*.json) and the ledger. Writes RESULTS.json
(the attempted matrix for REPAIRED / RESIDUAL_ONLY / RESIDUAL_JOINT on the gate / main / preservation panels, the eight-second diagnostic cells, confirmations; completion sets vs each other, vs the 24 historical DGP6 completions and the 18 / 13
preservation cohorts; full-inventory radii; cost / overhead; per-cell residual mechanism: bank coverage, windows planned / fitted / excluded, context modes, candidate checked, transaction committed (changed law / same-law cap / none),
envelope / consumed / new caps, future draws under the new law, phase times, peak bytes, typed refusals), DIAGNOSTICS.json (per oracle model: seed, the production RESIDUAL_JOINT / RESIDUAL_ONLY trajectories with TRUE M2 / R* per epoch law, the
teacher (ideal q = p), the oracle-injected and uniform-context laws, replays per law with its own checked cap; the mechanism gate; the execution gate from the gate cells), RUN_MANIFEST.json, CHARGES.json, REPORT.md.
usage: dgp7_analyze.py [analyze | select-confirm | report]"""
import sys, os, json, glob, math, time, hashlib, statistics
from fractions import Fraction as F
import numpy as np
RD = os.environ.get('DGP7_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'); DGP6 = os.path.join(os.path.dirname(RD), 'DGP6_GLOBAL_CONSTRUCTION')
ARMS = ['REPAIRED', 'RESIDUAL_ONLY', 'RESIDUAL_JOINT']; DIAG_ARMS = ['REPAIRED_8', 'RESIDUAL_JOINT_8']; FORCED_ARMS = ['FORCED_RESIDUAL']; EPS = 0.005
SUBS = ('gate', 'main', 'preservation_18', 'preservation_13', 'policy8', 'forced', 'confirm')
FAILURE_LABEL = 'no checked candidate promoted under the tested windows / atoms / profile / budget'
ANCHORS = ['dg_n32_c4_er50_two', 'dg_n32_c4_clique_two', 'dg_n64_c4_er50_two', 'dg_n64_c4_clique_two']
EXPOSED_CLIQUES = ['dg_n8_c4_clique_two', 'dg_n8_c4_clique_two__oracle4', 'dg_n8_c4_clique_two__oracle5']
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
    """per ORIGINAL coordinate final radius on the FULL fixed query inventory: enclosures (informative partial enclosures preserved) with 0.5 for every inventory coordinate without one"""
    d = c['_result']
    if d is None: return None, None
    K = d.get('K') or 0; rows = d.get('answers') or []; rad = {}
    for a in rows:
        key = (a['var'], a['state'])
        if a.get('guarantee') != 'NOT_PUBLISHED': rad[key] = float(F(a['hi']) - F(a['lo'])) / 2
    for e in d.get('enclosures') or []:
        key = (e['var'], e['state']); w = float(F(e['hi']) - F(e['lo'])) / 2
        if key not in rad or w < rad[key]: rad[key] = w
    full = [rad.get((a['var'], a['state']), 0.5) for a in rows] if rows else ([0.5] * K if K else [])
    return full, dict(K=K, published=sum(1 for a in rows if a.get('guarantee') != 'NOT_PUBLISHED'), informative=sum(1 for w in full if w < 0.5), width_max=(2 * max(full) if full else None))

def residual_status(c):
    """the residual-stream mechanism of one planner cell, read from result.json directly (never from a harness summary): offered / created / READY / piloted / attempts / windows / transactions / future draws / bank / phases / refusals"""
    d = c['_result']
    if d is None: return None
    m = d.get('mechanism') or {}; jo = m.get('joint_offer') or {}; sp = m.get('scheduling_policy') or {}; streams = d.get('streams') or []; D = [s for s in streams if s.get('kind') == 'residual']; G = [s for s in streams if s.get('kind') == 'global']
    acts = d.get('actions') or []
    st = dict(mode=d.get('residual_mode') or d.get('global_mode'), policy8=bool(d.get('policy8')), offered=bool(jo.get('created')) or any(a.get('action') == 'create_joint' for a in acts), refused=jo.get('refused'), deferred=sp.get('optional_deferrals'), created=bool(D or G), ready=False, sampled=False, draws=0, pub=0, epochs=0, attempts=[], pilot=None, closed=None, stage=None, refinement_ended=None, allowance_s=None, seed_s=None, construction_s=None,
              E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), exploration_frac=sp.get('exploration_frac'), allowance_rule=sp.get('allowance_rule'), primary_probe=sp.get('primary_probe'), first_batch_t_s=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s')), lifted=[(s['label'][:30], s['stage'], s['draws']) for s in streams if s.get('kind') == 'lifted'],
              transactions=[], changed_law_commits=0, same_law_commits=0, future_draws_under_new_law=0, bank=None, windows_planned=0, windows_fitted=0, windows_excluded=0, window_status={}, context_modes={}, typed_refusals=[], phase_s={}, peak_bytes=None, kind=('residual' if D else ('global' if G else None)))
    if G and not D:
        s = G[0]; j = s.get('joint') or {}; st.update(stage=s['stage'], closed=s.get('closed'), ready=(s['stage'] in ('READY', 'COMPLETE') or s['draws'] > 0), sampled=(s['draws'] > 0), draws=s['draws'], pub=s['published'], epochs=len(j.get('epochs') or []), refinement_ended=j.get('refinement_ended'), allowance_s=((j.get('allowance') or {}).get('total_s')), seed_s=(((s.get('mechanism') or {}).get('seed') or {}).get('seconds')), attempts=[dict(status=a.get('status'), kind=a.get('kind'), why=(a.get('why') or '')[:120], promoted=a.get('promoted'), seconds=a.get('seconds')) for a in j.get('attempts') or []], promotion=j.get('promotion'), activation=j.get('activation'))
        return st
    if D:
        s = D[0]; j = s.get('joint') or {}; sm = s.get('mechanism') or {}; bank = j.get('bank') or sm.get('residual_bank') or {}; seed = sm.get('seed') or {}
        atts = []
        for a in j.get('attempts') or []:
            ws = a.get('windows') or []
            for w in ws:
                st['window_status'][w.get('status')] = st['window_status'].get(w.get('status'), 0) + 1; cm = ((w.get('fit') or {}).get('context') or {}).get('mode')
                if cm: cm = cm.split(' ')[0]; st['context_modes'][cm] = st['context_modes'].get(cm, 0) + 1
                if w.get('status') == 'REFUSED': st['typed_refusals'].append(dict(where='window', kind=w.get('kind'), why=(w.get('why') or '')[:100]))
            if a.get('status') == 'REFUSED': st['typed_refusals'].append(dict(where='attempt', kind=a.get('kind'), why=(a.get('why') or '')[:100]))
            st['windows_planned'] += len(a.get('windows_planned') or []); st['windows_fitted'] += (a.get('windows_fitted') or 0); st['windows_excluded'] += (a.get('windows_excluded') or 0)
            tx = a.get('transaction') or {}
            atts.append(dict(status=a.get('status'), kind=(tx.get('kind') or a.get('kind')), why=(a.get('why') or '')[:140], label=a.get('label'), promoted=a.get('promoted'), seconds=a.get('seconds'), windows_fitted=a.get('windows_fitted'), windows_planned=len(a.get('windows_planned') or []), log2_B_before=tx.get('log2_B_before'), log2_B_after=tx.get('log2_B_after'), rows_changed=tx.get('rows_changed'), rank=tx.get('rank'), d_ratio=tx.get('d_ratio'), window=tx.get('window'), fit_s=sum(((w.get('fit') or {}).get('seconds') or 0) for w in ws), kernel_s=sum(((w.get('kernel') or {}).get('seconds') or 0) for w in ws), best_rank=min([w.get('rank') for w in ws if isinstance(w.get('rank'), (int, float))] or [None]) if any(isinstance(w.get('rank'), (int, float)) for w in ws) else None, whole_model_windows=sum(1 for w in ws if w.get('whole_model_region'))))
        eps_ = j.get('epochs') or []; total_draws = s.get('draws') or 0
        for e in eps_:
            if str(e.get('reason', '')).startswith('promoted:changed_law'): to = e.get('draws_to') if e.get('draws_to') is not None else total_draws; st['future_draws_under_new_law'] += max(0, to - (e.get('draws_from') or 0))
        txs = j.get('transactions') or []; st['transactions'] = [{k: t.get(k) for k in ('id', 'kind', 'log2_B_before', 'log2_B_after', 'log2_B_ref_same_law', 'rank', 'd_ratio', 'rows_changed', 'committed_offset_s', 'epoch_after', 'version_after', 'window')} for t in txs]
        st['changed_law_commits'] = sum(1 for t in txs if t.get('kind') == 'changed_law'); st['same_law_commits'] = sum(1 for t in txs if t.get('kind') == 'same_law')
        st.update(stage=s['stage'], closed=s.get('closed'), ready=(s['stage'] in ('READY', 'COMPLETE') or s['draws'] > 0), sampled=(s['draws'] > 0), draws=total_draws, pub=s['published'], epochs=len(eps_), refinement_ended=j.get('refinement_ended'), allowance_s=((j.get('allowance') or {}).get('total_s')), seed_s=seed.get('seconds'), attempts=atts, pilot=({k: j['pilot'].get(k) for k in ('status', 'draws', 'seconds', 'd_seed_s_per_draw')} if j.get('pilot') else None), activation=j.get('activation'), graph=((j.get('graph') or {}).get('label')), graph_extended=((j.get('graph') or {}).get('n_extended')),
                  bank=dict(atoms=bank.get('atoms'), live_atoms=bank.get('live_atoms'), entries=bank.get('entries'), bytes=bank.get('bytes'), version=bank.get('version'), dropped=len(bank.get('dropped') or []), evicted=len(bank.get('evicted') or []), log2_envelope_B=bank.get('log2_envelope_B'), log2_consumed_B=bank.get('log2_consumed_B'), log2_initial_seed_cap=bank.get('log2_initial_seed_cap'), sink=bank.get('sink'), check_seconds=bank.get('check_seconds'), check_cells=bank.get('check_cells')),
                  epoch_records=[dict(index=e.get('index'), reason=e.get('reason'), draws_from=e.get('draws_from'), draws_to=e.get('draws_to'), log2_B=((e.get('proposal') or {}).get('log2_B_W0')), log2_S=((e.get('proposal') or {}).get('log2_S_W0sq')), committed_offset_s=e.get('committed_offset_s'), law_sha=((e.get('proposal') or {}).get('sha256') or '')[:12]) for e in eps_], epoch_weight_statistics=j.get('epoch_weight_statistics'), peak_bytes=j.get('joint_bytes'), bank_bytes=j.get('bank_bytes'), seed_work_cells=seed.get('work_cells'), seed_owned_bytes=seed.get('owned_bytes'))
        st['phase_s'] = dict(seed=seed.get('seconds'), bank_retention=((bank.get('sink') or {}).get('retention_seconds')), pilot=((st['pilot'] or {}).get('seconds')), attempts=sum((a.get('seconds') or 0) for a in atts), fit=sum((a.get('fit_s') or 0) for a in atts), kernel=sum((a.get('kernel_s') or 0) for a in atts), activation=((j.get('activation') or {}).get('seconds')))
        st['construction_s'] = (seed.get('seconds') or 0) + sum((a.get('seconds') or 0) for a in atts) + ((st['pilot'] or {}).get('seconds') or 0)
    return st

def cell_row(c):
    full, info = radii_full_inventory(c); d = c['_result'] or {}; m = d.get('mechanism') or {}
    return dict(complete=bool(c.get('complete')), outcome=c.get('outcome'), receipt_outcome=c.get('receipt_outcome'), receipt_wall_s=c.get('receipt_wall_s'), solver_wall_s=c.get('solver_wall_s'), published=c.get('published'), K=c.get('K'), identity_ok=c.get('identity_ok'), hard_deadline_respected=c.get('hard_deadline_respected'), termination=c.get('termination'), seed=c.get('seed'), seed_index=c.get('seed_index', 0), dir=os.path.relpath(c['_dir'], RD), worst_radius=(max(full) if full else None), median_radius=med(full), p90_radius=(float(np.percentile(full, 90)) if full else None), covered_at_eps=(sum(1 for w in full if w <= EPS) if full else None), inventory=info, ledger_identity=m.get('constructor_live_ledger_identity'), defect=m.get('defect'), refusal=(m.get('refusal') or {}).get('kind') if isinstance(m.get('refusal'), dict) else m.get('refusal'), time_to_first_batch=((d.get('cost_breakdown') or {}).get('time_to_first_committed_batch_s')), peak_rss_bytes=d.get('peak_rss_bytes'), direct=residual_status(c), primary_probe_s=sum((a.get('actual_s') or 0) for a in (d.get('actions') or []) if a.get('action') == 'primary_probe'))

def table(sub):
    cs = cells_of(sub); by = {}
    for c in cs: by.setdefault((c['task'], c.get('seed_index', 0), c['confirm']), {})[c['arm']] = cell_row(c)
    return by, cs

def final_worst(rep):
    out = []
    for s_, v in sorted(((rep or {}).get('seeds') or {}).items(), key=lambda kv: int(kv[0])):
        ch = (v.get('checkpoints') or [])
        if ch: out.append(dict(seed=int(s_), worst=ch[-1]['worst_radius'], median=ch[-1]['median_radius'], covered=ch[-1]['covered'], K=ch[-1]['K'], contains_truth=ch[-1].get('contains_truth'), draws=ch[-1]['draws']))
        else: out.append(dict(seed=int(s_), censored=v.get('censored')))
    return out

def failure_subreason(dm):
    """the sub-reason of a RESIDUAL cell that did not complete (PROTOCOL section 5); every label is a sub-reason of FAILURE_LABEL"""
    if not dm or not dm.get('offered'): return 'never offered (%s)' % ((dm or {}).get('refused') or ('deferred by the primary protection' if (dm or {}).get('deferred') else 'n/a'))
    if not dm.get('created'): return 'admission refusal (offered, not created)'
    if not dm.get('ready'): return ('policy / memory refusal' if any(k in str(dm.get('closed')) for k in ('MEMORY', 'VOLUME', 'ALLOWANCE')) else ('numerical floor' if any(k in str(dm.get('closed')) for k in ('NUMERIC', 'RANGE', 'BITS')) else 'constructor cost (seed not READY inside the allowance: %s)' % str(dm.get('closed'))[:40]))
    atts = dm.get('attempts') or []
    if not atts: return 'scheduler never attempted a transaction inside the allowance'
    kinds = [a.get('status') for a in atts]
    if any(a.get('status') == 'NO_RESIDUAL_INFORMATION' for a in atts): return 'no residual information (no live atom)'
    if any(a.get('status') == 'NO_WINDOW' for a in atts): return 'no admissible window'
    if any(a.get('promoted') for a in atts):
        if (dm.get('future_draws_under_new_law') or 0) <= 1024: return 'promoted; <= 1,024 future draws under the new law (scheduler / allowance)'
        return 'promoted; sampled beyond activation (the certificate did not close inside the contract)'
    last = atts[-1]; st = last.get('status'); k = str(last.get('kind') or '')
    if st == 'REFUSED': return {'DEADLINE': 'window expiry (deadline inside fitting / checking)', 'ALLOWANCE': 'allowance exhausted before an attempt', 'MEMORY_POLICY': 'admission refusal', 'MEMORY': 'admission refusal'}.get(k, 'candidate refused (%s)' % k)
    if st in ('DEFECT', 'NUMERIC', 'INTERNAL'): return 'candidate refused (%s)' % st
    if st == 'KEPT_INCUMBENT': return 'no promotable candidate (rank >= 0.99 or exact gate / same-law < 1 %%)'
    return 'unresolved (%s)' % st

def analyze():
    man, tp = panels(); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {'commit': None}}; res = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=fr['code'].get('commit'), freeze_sha256=(sha(os.path.join(RD, 'FREEZE.json')) if os.path.exists(os.path.join(RD, 'FREEZE.json')) else None), tables={}, completions_by_sub={}, verdict_inputs={})
    meta = {}
    for p in tp.values():
        for t in p: meta.setdefault(t['name'], t)
    main_names = [t['name'] for t in tp.get('main_76', tp.get('main', []))]; guard_names = [t['name'] for t in tp.get('guard_32', tp.get('guard', []))]; hist24 = [t['name'] for t in (tp.get('guard_32') or tp.get('guard') or []) if (t.get('role') or '').startswith('historical')]; hard8 = [t['name'] for t in (tp.get('guard_32') or tp.get('guard') or []) if (t.get('role') or '').startswith('hard')]
    if not hist24 and (man.get('historical_completions_24')): hist24 = list(man['historical_completions_24'])
    for sub in SUBS:
        by, cs = table(sub)
        if not cs: continue
        order_names = main_names + [t['name'] for p in ('preservation_18', 'preservation_13') for t in tp.get(p, [])]
        res['tables'][sub] = [dict(task=k[0], seed_index=k[1], confirm=k[2], topology=(meta.get(k[0], {}).get('topology') or meta.get(k[0], {}).get('family')), panel=meta.get(k[0], {}).get('panel'), exposure=meta.get(k[0], {}).get('exposure'), n=meta.get(k[0], {}).get('n'), arms=v) for k, v in sorted(by.items(), key=lambda kv: (kv[0][2], kv[0][1], order_names.index(kv[0][0]) if kv[0][0] in order_names else 999))]
        arms_here = sorted({c['arm'] for c in cs}); res['completions_by_sub'][sub] = dict(cells=len(cs), complete=sum(1 for c in cs if c.get('complete')), by_arm={a: dict(cells=sum(1 for c in cs if c['arm'] == a), complete=sum(1 for c in cs if c['arm'] == a and c.get('complete')), receipts_completed=sum(1 for c in cs if c['arm'] == a and c.get('receipt_outcome') == 'COMPLETED'), identity_ok=sum(1 for c in cs if c['arm'] == a and c.get('identity_ok'))) for a in arms_here})
    # ---- historical comparators: the 24 DGP6 completions (GLOBAL / REPAIRED arms, identical sets) and the DGP6 preservation cohorts
    d6 = load(os.path.join(DGP6, 'RESULTS.json')) or {}; hist6 = {r['task']: r['arms'] for r in (d6.get('tables') or {}).get('main', [])}; hist6_complete = sorted(t for t, a in hist6.items() if (a.get('GLOBAL') or {}).get('complete'))
    if not hist24: hist24 = hist6_complete
    hist6_pres = {sub: {r['task']: (r['arms'].get('GLOBAL') or {}).get('complete') for r in (d6.get('tables') or {}).get(sub, [])} for sub in ('preservation_18', 'preservation_13')}
    # the main matrix = main cells + gate cells (seed 0 of the gate anchors live in the gate sub when the broad phase did not run them again); merge by task
    em = res['tables'].get('main', []); gate_rows = [r for r in res['tables'].get('gate', []) if r['seed_index'] == 0]; seen = {r['task'] for r in em}
    for r in gate_rows:
        if r['task'] not in seen:
            r2 = dict(r, from_gate=True); em.append(r2); seen.add(r['task'])
        else:
            tgt = next(x for x in em if x['task'] == r['task'])
            for a, v in r['arms'].items(): tgt['arms'].setdefault(a, v)
    res['tables']['main_matrix'] = em
    comp = {a: sorted(r['task'] for r in em if r['arms'].get(a, {}).get('complete')) for a in ARMS}; ran = {a: sorted(r['task'] for r in em if a in r['arms']) for a in ARMS}; is_fresh = lambda t: (meta.get(t, {}).get('panel') or '').startswith('fresh'); is_dense = lambda t: (meta.get(t, {}).get('topology') or meta.get(t, {}).get('family')) in ('er50', 'clique', 'ER')
    mi = dict(n_tasks=len(em), ran=ran, n_ran={a: len(ran[a]) for a in ARMS}, complete=comp, n_complete={a: len(comp[a]) for a in ARMS}, dense_complete={a: len([t for t in comp[a] if is_dense(t)]) for a in ARMS}, fresh_complete={a: sorted(t for t in comp[a] if is_fresh(t)) for a in ARMS}, historical_DGP6_complete_24=hist24, hard_8=hard8,
              historical_lost={a: sorted(t for t in hist24 if t in set(ran[a]) and t not in set(comp[a])) for a in ARMS}, historical_not_run={a: sorted(t for t in hist24 if t not in set(ran[a])) for a in ARMS}, hard8_completed={a: sorted(t for t in hard8 if t in set(comp[a])) for a in ARMS},
              RJ_not_REPAIRED=sorted(set(comp['RESIDUAL_JOINT']) - set(comp['REPAIRED'])), REPAIRED_not_RJ=sorted(set(comp['REPAIRED']) - set(comp['RESIDUAL_JOINT'])), RO_not_REPAIRED=sorted(set(comp['RESIDUAL_ONLY']) - set(comp['REPAIRED'])), REPAIRED_not_RO=sorted(set(comp['REPAIRED']) - set(comp['RESIDUAL_ONLY'])), RJ_not_RO=sorted(set(comp['RESIDUAL_JOINT']) - set(comp['RESIDUAL_ONLY'])), RO_not_RJ=sorted(set(comp['RESIDUAL_ONLY']) - set(comp['RESIDUAL_JOINT'])),
              identical_sets_all_three=(len({tuple(comp[a]) for a in ARMS}) == 1), new_dense_completion_candidates=sorted(t for t in set(comp['RESIDUAL_JOINT']) | set(comp['RESIDUAL_ONLY']) if is_dense(t) and t not in set(comp['REPAIRED'])))
    res['verdict_inputs']['main'] = mi
    acc = []; cost = []
    for r in em:
        A = r['arms']; p = A.get('REPAIRED'); o = A.get('RESIDUAL_ONLY'); g = A.get('RESIDUAL_JOINT')
        if not (p and g): continue
        if not g['complete'] and not p['complete']:
            rg, rp, ro = g['worst_radius'], p['worst_radius'], (o or {}).get('worst_radius')
            acc.append(dict(task=r['task'], topology=r['topology'], n=r.get('n'), fresh=is_fresh(r['task']), hard8=(r['task'] in hard8), REPAIRED_worst=rp, RESIDUAL_ONLY_worst=ro, RESIDUAL_JOINT_worst=rg, ratio_REPAIRED_over_RJ=(rp / rg if rp is not None and rg not in (None, 0) else None), ratio_REPAIRED_over_RO=(rp / ro if rp is not None and ro not in (None, 0) else None), ratio_RO_over_RJ=(ro / rg if ro is not None and rg not in (None, 0) else None), material_2x_RJ_vs_REPAIRED=bool(rp is not None and rg not in (None, 0) and rp / rg >= 2), material_4_3_RJ_vs_REPAIRED=bool(rp is not None and rg not in (None, 0) and rp / rg >= 4 / 3), RJ_covered=g['covered_at_eps'], REPAIRED_covered=p['covered_at_eps'], K=g['K'], rj_mech={k: (g.get('direct') or {}).get(k) for k in ('changed_law_commits', 'same_law_commits', 'future_draws_under_new_law', 'draws', 'ready', 'closed', 'refinement_ended')}, ro_mech={k: ((o or {}).get('direct') or {}).get(k) for k in ('changed_law_commits', 'same_law_commits', 'draws', 'ready')}))
        if p['complete'] and g['complete']:
            slower = (g['receipt_wall_s'] - p['receipt_wall_s']); cost.append(dict(task=r['task'], REPAIRED_s=p['receipt_wall_s'], RESIDUAL_ONLY_s=(o['receipt_wall_s'] if o and o['complete'] else None), RESIDUAL_JOINT_s=g['receipt_wall_s'], ratio_RJ_over_REPAIRED=g['receipt_wall_s'] / p['receipt_wall_s'], ratio_RO_over_REPAIRED=((o['receipt_wall_s'] / p['receipt_wall_s']) if o and o['complete'] else None), flag_slower=bool(slower >= 0.1 and g['receipt_wall_s'] / p['receipt_wall_s'] >= 1.25), flag_slower_RO=bool(o and o['complete'] and o['receipt_wall_s'] - p['receipt_wall_s'] >= 0.1 and o['receipt_wall_s'] / p['receipt_wall_s'] >= 1.25), RJ_first_batch=g.get('time_to_first_batch'), REPAIRED_first_batch=p.get('time_to_first_batch'), RJ_construction_s=((g.get('direct') or {}).get('construction_s')), RJ_created=((g.get('direct') or {}).get('created')), REPAIRED_probe_s=p.get('primary_probe_s')))
    res['verdict_inputs']['accuracy_mutual_failures'] = acc; res['verdict_inputs']['cost_mutual_completions'] = cost
    for sub in ('preservation_18', 'preservation_13'):
        rows = res['tables'].get(sub, []); h6 = hist6_pres.get(sub, {})
        res['verdict_inputs'][sub] = {a: dict(complete=sum(1 for r in rows if r['arms'].get(a, {}).get('complete')), n=len(rows), ran=sum(1 for r in rows if a in r['arms']), regressions_vs_DGP6=sorted(r['task'] for r in rows if h6.get(r['task']) and a in r['arms'] and not r['arms'].get(a, {}).get('complete')), offered=sum(1 for r in rows if (r['arms'].get(a, {}).get('direct') or {}).get('offered')), created=sum(1 for r in rows if (r['arms'].get(a, {}).get('direct') or {}).get('created')), sampled=sum(1 for r in rows if (r['arms'].get(a, {}).get('direct') or {}).get('sampled')), probed=sum(1 for r in rows if ((r['arms'].get(a, {}).get('direct') or {}).get('primary_probe') or {}).get('batches'))) for a in ARMS}
        res['verdict_inputs'][sub]['historical_complete'] = sum(1 for v in h6.values() if v)
        for a in ARMS[1:]: res['verdict_inputs'][sub]['%s_not_REPAIRED' % a] = sorted(r['task'] for r in rows if r['arms'].get(a, {}).get('complete') and not r['arms'].get('REPAIRED', {}).get('complete')); res['verdict_inputs'][sub]['REPAIRED_not_%s' % a] = sorted(r['task'] for r in rows if r['arms'].get('REPAIRED', {}).get('complete') and a in r['arms'] and not r['arms'].get(a, {}).get('complete'))
    # ---- execution gate (RESIDUAL_JOINT on the four anchors x seeds 0 / 1): changed quantized law + checked transaction + >= 1,024 future draws under that law, inside the 20 s / 4 s contract
    gate = []
    for r in res['tables'].get('gate', []) + [x for x in em if x['task'] in ANCHORS and x.get('from_gate') is not True]:
        g = r['arms'].get('RESIDUAL_JOINT')
        if not g or r['task'] not in ANCHORS: continue
        dm = g.get('direct') or {}; ok = bool(dm.get('changed_law_commits')) and (dm.get('future_draws_under_new_law') or 0) >= 1024 and not dm.get('policy8') and (dm.get('allowance_s') or 99) <= 4.0 + 1e-6
        gate.append(dict(task=r['task'], n=int(r['task'].split('_n')[1].split('_')[0]), seed_index=r['seed_index'], confirm=r['confirm'], passes=ok, changed_law_commits=dm.get('changed_law_commits'), same_law_commits=dm.get('same_law_commits'), future_draws=dm.get('future_draws_under_new_law'), allowance_s=dm.get('allowance_s'), seed_s=dm.get('seed_s'), ready=dm.get('ready'), closed=dm.get('closed'), transactions=dm.get('transactions'), outcome=g['outcome'], dir=g['dir']))
    seen_k = set(); gate = [x for x in gate if not ((x['task'], x['seed_index'], x['confirm']) in seen_k or seen_k.add((x['task'], x['seed_index'], x['confirm'])))]
    per_model = {}
    for x in gate: per_model.setdefault(x['task'], {})[x['seed_index']] = x['passes']
    paired = {t: (v.get(0) is True and v.get(1) is True) for t, v in per_model.items()}; n32 = [t for t, ok in paired.items() if ok and '_n32_' in t]; n64 = [t for t, ok in paired.items() if ok and '_n64_' in t]
    XG = dict(cells=gate, per_model_seed_pass=per_model, paired_pass=paired, n32_pass=n32, n64_pass=n64, status=('PASS' if (n32 and n64) else ('FAIL' if all(len(v) >= 2 for v in per_model.values()) and len(per_model) >= 4 else 'INCOMPLETE')), numerator=dict(n32=len(n32), n64=len(n64)), denominator=dict(models=len(per_model), seeds_per_model=2), rule='per anchor BOTH paired seeds (indices 0, 1) show a changed quantized law + a checked transaction + >= 1,024 future draws under that law at 20 s / 4 s; the gate needs >= 1 n32 AND >= 1 n64 anchor')
    res['verdict_inputs']['execution_gate'] = XG
    # ---- eight-second diagnostic (REPAIRED_8 / RESIDUAL_JOINT_8 on the eight pinned models) vs the 4 s main cells
    diag_rows = []
    for sub in ('policy8', 'forced'):
        for r in res['tables'].get(sub, []):
            for arm, a in r['arms'].items():
                dm = a.get('direct') or {}; mainrow = next((x['arms'] for x in em if x['task'] == r['task']), {})
                diag_rows.append(dict(sub=sub, task=r['task'], arm=arm, outcome=a['outcome'], receipt_wall_s=a['receipt_wall_s'], worst_radius=a['worst_radius'], covered=a['covered_at_eps'], K=a['K'], created=dm.get('created'), ready=dm.get('ready'), draws=dm.get('draws'), epochs=dm.get('epochs'), changed_law_commits=dm.get('changed_law_commits'), same_law_commits=dm.get('same_law_commits'), future_draws=dm.get('future_draws_under_new_law'), allowance_s=dm.get('allowance_s'), E=dm.get('E'), attempts=dm.get('attempts'), closed=dm.get('closed'), seed_s=dm.get('seed_s'), main_REPAIRED_worst=(mainrow.get('REPAIRED') or {}).get('worst_radius'), main_RJ_worst=(mainrow.get('RESIDUAL_JOINT') or {}).get('worst_radius'), main_REPAIRED_s=(mainrow.get('REPAIRED') or {}).get('receipt_wall_s'), main_RJ_s=(mainrow.get('RESIDUAL_JOINT') or {}).get('receipt_wall_s'), main_RJ_changed=((mainrow.get('RESIDUAL_JOINT') or {}).get('direct') or {}).get('changed_law_commits')))
    res['verdict_inputs']['diagnostics'] = diag_rows
    # ---- mechanism counts over every planner cell
    mech = {}
    for sub in SUBS:
        for r in res['tables'].get(sub, []):
            for arm, a in r['arms'].items():
                dm = a.get('direct')
                if dm is None: continue
                k = (sub, arm); m_ = mech.setdefault(k, dict(cells=0, probed=0, deferred=0, offered=0, created=0, ready=0, piloted=0, attempted=0, windows_planned=0, windows_fitted=0, promoted_cells=0, changed_law_commits=0, same_law_commits=0, cells_with_changed_law=0, cells_with_1024_future_draws=0, future_draws=0, published=0, closed_before_ready=0, no_residual_information=0, refused_threshold=0, refused_admission=0, by_status={}, context_modes={}, window_status={}, atoms=[], seed_s=[], attempt_s=[]))
                m_['cells'] += 1; m_['probed'] += int(bool((dm.get('primary_probe') or {}).get('batches'))); m_['deferred'] += int(bool(dm.get('deferred'))); m_['offered'] += int(bool(dm.get('offered'))); m_['created'] += int(bool(dm.get('created'))); m_['ready'] += int(bool(dm.get('ready'))); m_['piloted'] += int(((dm.get('pilot') or {}).get('status')) == 'COMPLETE'); m_['published'] += int((dm.get('pub') or 0) > 0)
                m_['refused_threshold'] += int(str(dm.get('refused') or '').startswith('OFFER_THRESHOLD')); m_['refused_admission'] += int(str(dm.get('refused') or '').startswith('ADMISSION')); m_['closed_before_ready'] += int(bool(dm.get('created')) and not dm.get('ready')); m_['attempted'] += int(bool(dm.get('attempts'))); m_['windows_planned'] += (dm.get('windows_planned') or 0); m_['windows_fitted'] += (dm.get('windows_fitted') or 0)
                m_['changed_law_commits'] += (dm.get('changed_law_commits') or 0); m_['same_law_commits'] += (dm.get('same_law_commits') or 0); m_['cells_with_changed_law'] += int((dm.get('changed_law_commits') or 0) > 0); m_['cells_with_1024_future_draws'] += int((dm.get('future_draws_under_new_law') or 0) >= 1024); m_['future_draws'] += (dm.get('future_draws_under_new_law') or 0); m_['promoted_cells'] += int(bool(dm.get('transactions')))
                for a_ in dm.get('attempts') or []: m_['by_status'][a_.get('status')] = m_['by_status'].get(a_.get('status'), 0) + 1; m_['attempt_s'].append(a_.get('seconds') or 0); m_['no_residual_information'] += int(a_.get('status') == 'NO_RESIDUAL_INFORMATION')
                for cm, n_ in (dm.get('context_modes') or {}).items(): m_['context_modes'][cm] = m_['context_modes'].get(cm, 0) + n_
                for ws_, n_ in (dm.get('window_status') or {}).items(): m_['window_status'][ws_] = m_['window_status'].get(ws_, 0) + n_
                if (dm.get('bank') or {}).get('live_atoms') is not None: m_['atoms'].append(dm['bank']['live_atoms'])
                if dm.get('seed_s') is not None: m_['seed_s'].append(dm['seed_s'])
    for m_ in mech.values(): m_['atoms_median'] = med(m_['atoms']); m_['atoms'] = len(m_['atoms']); m_['seed_s_median'] = med(m_['seed_s']); m_['seed_s'] = len(m_['seed_s']); m_['attempt_s_median'] = med(m_['attempt_s']); m_['attempt_s'] = len(m_['attempt_s'])
    res['verdict_inputs']['mechanism_counts'] = {'%s/%s' % k: v for k, v in mech.items()}
    # ---- oracle diagnostics
    diag = dict(utc=res['utc'], oracle=[], units='W_0 = canonical target WITHOUT the scalar; Z_0 = Z / scalar; R* = max_x W_0 / q (true max weight = tight cap of a law); B = the law\'s checked cap (W_0 units); S* = exact sum W_0^2 / q; M2 = S* / Z_0^2 (floating enumeration <= 65,536 states; exact-rational checks <= 4,096); M2 gain bits = log2 M2(seed) - log2 M2(law); cap ratio = 2^(log2 B(law) - log2 B(seed)); radii = worst requested certificate radius at 2^18 draws (final checkpoint) per seed, each law under its OWN checked cap (tight cap paired on the same draws)')
    LAWS = ['seed', 'RJ_final', 'RO_final', 'ideal_q_eq_p', 'oracle_injected_true_context', 'uniform_context_DIAGNOSTIC']
    oracle_tasks = tp.get('oracle_12', tp.get('oracle', []))
    for t in oracle_tasks:
        d = load(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')); row = dict(task=t['name'], panel=t.get('panel'), exposure=t.get('exposure'), topology=t.get('topology') or t.get('family'), n=int(t.get('n') or 0), card=int(t.get('card') or 0), scale=str(t.get('scale')), fine_states=t.get('fine_states'))
        if d is None: row['status'] = 'NOT_RUN'; diag['oracle'].append(row); continue
        mg0 = d.get('mechanism_gate') or {}; row.update(status=('CENSORED: ' + '; '.join(d['censored'])) if d.get('censored') else 'COMPLETE', wall_s=d.get('wall_s'), phases=d.get('phases'), allowance_s=d.get('allowance_s'), log2_Z0=(d.get('original') or {}).get('log2_Z0'), seed=((d.get('seed') or {}).get('law')), seed_exact_check=((d.get('seed') or {}).get('exact_check')), seed_identity=((d.get('seed') or {}).get('identity_seed')), laws={}, replays={}, trajectories={}, mechanism_gate=mg0, whole_model_region=any(t.get('whole_model_region') for t in (mg0.get('per_transaction') or [])), offline=({k: (d.get('offline') or {}).get(k) for k in ('window_selection', 'windows_planned', 'windows_excluded', 'seconds')} if d.get('offline') else None), classification=d.get('classification'))
        for k, l in (d.get('laws') or {}).items():
            if not isinstance(l, dict): continue
            row['laws'][k] = {kk: l.get(kk) for kk in ('log2_Z0', 'log2_B_star', 'log2_S_star', 'log2_M2', 'log2_B_over_Rstar', 'log2_B_over_Z0', 'max_log2_X_implemented', 'cap_dominates_true_Rstar', 'same_as_seed', 'identity', 'exact_check', 'label', 'mode', 'log2_cap_change_vs_seed', 'M2_gain_bits_vs_seed', 'log2_B_checked')} | dict(conditionals=[(c_['z'], c_['parents'], c_['volume']) for c_ in ((l.get('proposal') or {}).get('conditionals') or [])][:12], sha=(l.get('proposal') or {}).get('sha256', '')[:12], log2_B=(l.get('log2_B_checked') if l.get('log2_B_checked') is not None else (l.get('proposal') or {}).get('log2_B_W0')), log2_S=((l.get('proposal') or {}).get('log2_S_W0sq')), bytes=((l.get('proposal') or {}).get('bytes')), identical_to_seed=l.get('same_as_seed'))
        for k in ('stream_rj', 'stream_ro'):
            tr = d.get(k)
            if isinstance(tr, dict): row['trajectories'][k] = {kk: (tr.get(kk) if kk not in ('bank',) else ({b_: (tr.get('bank') or {}).get(b_) for b_ in ('atoms', 'live_atoms', 'entries', 'bytes', 'version', 'sink')} if isinstance(tr.get('bank'), dict) else tr.get('bank'))) for kk in ('mode', 'prepare', 'closed', 'inside_allowance', 'allowance_s', 'seconds', 'transactions', 'attempts', 'epochs', 'bank', 'final_law', 'activation', 'draws', 'pilot', 'graph')}
        for k, r in (d.get('replays') or {}).items():
            if not isinstance(r, dict) or r.get('not_available') or (r.get('censored') and not r.get('caps')): row['replays'][k] = dict(not_available=bool(r.get('not_available')), censored=r.get('censored'), reason=r.get('reason')); continue
            row['replays'][k] = dict(implemented=final_worst(r.get('caps', {}).get('implemented')), tight=final_worst(r.get('caps', {}).get('tight')), log2_cap_implemented_over_Z0=r.get('log2_cap_implemented_over_Z0'), log2_cap_tight_over_Z0=r.get('log2_cap_tight_over_Z0'), same_as_seed=r.get('same_as_seed'), seconds=r.get('seconds'))
        L_ = row['laws']; sd = L_.get('seed') or {}
        def worsts(k): return [x.get('worst') for x in (row['replays'].get(k) or {}).get('implemented', []) if isinstance(x, dict) and 'worst' in x]
        con = dict(seed_M2=sd.get('log2_M2'), seed_log2_B=sd.get('log2_B'), seed_Rstar_over_Z0=((sd.get('log2_B_star') - row['log2_Z0']) if (sd.get('log2_B_star') is not None and row.get('log2_Z0') is not None) else None), seed_B_over_Rstar=sd.get('log2_B_over_Rstar'), seed_worst=worsts('seed'), ideal_worst=worsts('ideal_q_eq_p'))
        for k in ('RJ_final', 'RO_final', 'oracle_injected_true_context', 'uniform_context_DIAGNOSTIC'):
            l = L_.get(k) or {}
            con[k] = dict(log2_M2=l.get('log2_M2'), M2_gain_bits=((sd.get('log2_M2') - l.get('log2_M2')) if (sd.get('log2_M2') is not None and l.get('log2_M2') is not None) else None), log2_B=l.get('log2_B'), cap_ratio_vs_seed=((2.0 ** (l.get('log2_B') - sd.get('log2_B'))) if (l.get('log2_B') is not None and sd.get('log2_B') is not None) else None), B_over_Rstar=l.get('log2_B_over_Rstar'), cap_dominates_true_Rstar=l.get('cap_dominates_true_Rstar'), identical_to_seed=l.get('identical_to_seed'), inside_allowance=(mg0.get('inside_allowance') if k == 'RJ_final' else ((mg0.get('RO') or {}).get('inside_allowance') if k == 'RO_final' else None)), worst=worsts(k), certificate_ratios_seed_over=[(s_ / j_ if j_ and j_ > 0 else None) for s_, j_ in zip(worsts('seed'), worsts(k))])
        mg_ = mg0; rj = con['RJ_final']; con['RJ_transactions'] = mg_.get('changed_law_transactions'); con['RJ_per_transaction'] = mg_.get('per_transaction'); con['best_same_law_cap'] = mg_.get('best_same_law_cap'); con['cap_ratio_vs_best_same_law'] = mg_.get('cap_ratio_vs_best_same_law'); con['teacher'] = mg_.get('teacher')
        con['mechanism_gate_RJ'] = bool(mg_.get('passed')) if 'passed' in mg_ else bool(rj.get('M2_gain_bits') is not None and rj['M2_gain_bits'] >= 0.5 and rj.get('cap_ratio_vs_seed') is not None and rj['cap_ratio_vs_seed'] <= 1.10 + 1e-9 and (rj.get('inside_allowance') is not False))
        con['mechanism_gate_detail'] = mg_; row['contrasts'] = con; diag['oracle'].append(row)
    O = {r['task']: r for r in diag['oracle']}
    fresh_cliques = [t['name'] for t in oracle_tasks if 'clique' in t['name'] and t['name'].endswith('__oracle7')]; fresh_er = [t['name'] for t in oracle_tasks if 'er50' in t['name'] and t['name'].endswith('__oracle7')]
    exposed_pass = [t for t in EXPOSED_CLIQUES if (O.get(t) or {}).get('contrasts', {}).get('mechanism_gate_RJ')]; exposed_run = [t for t in EXPOSED_CLIQUES if t in O and O[t].get('status') != 'NOT_RUN']; fresh_pass = [t for t in fresh_cliques if (O.get(t) or {}).get('contrasts', {}).get('mechanism_gate_RJ')]; fresh_run = [t for t in fresh_cliques if t in O and O[t].get('status') != 'NOT_RUN']
    MG = dict(status=('SUPPORTED' if len(exposed_pass) >= 2 else ('NOT SUPPORTED' if len(exposed_run) == 3 else 'INCOMPLETE')), exposed_pass=len(exposed_pass), exposed_run=len(exposed_run), exposed_pass_names=exposed_pass, exposed_hard_cliques=EXPOSED_CLIQUES, fresh_pass=len(fresh_pass), fresh_run=len(fresh_run), fresh_pass_names=fresh_pass, fresh_cliques=fresh_cliques, fresh_claim=('SUPPORTED' if fresh_pass else ('NOT SUPPORTED' if len(fresh_run) == len(fresh_cliques) and fresh_cliques else 'INCOMPLETE')), fresh_er50=fresh_er, rule='the ACTUAL production RESIDUAL_JOINT construction: >= 0.5 bits of TRUE oracle M2 gain AND checked cap <= 1.10 x the best same-law seed cap, inside its declared construction allowance, on 2 of the 3 exposed n8 reference cliques; the fresh-mechanism claim needs >= 1 of the 2 fresh ORACLE7 cliques (reported separately)')
    diag['gates'] = dict(mechanism=MG, execution=XG, replay_coverage=dict(planned=[(t['name'], k) for t in oracle_tasks for k in LAWS[:4]], done=sum(1 for t in oracle_tasks if t['name'] in O for k in LAWS[:4] if (O[t['name']].get('replays') or {}).get(k, {}).get('implemented')), not_available=sum(1 for t in oracle_tasks if t['name'] in O for k in LAWS[:4] if (O[t['name']].get('replays') or {}).get(k, {}).get('not_available')), censored=sum(1 for t in oracle_tasks if t['name'] in O for k in LAWS[:4] if not (O[t['name']].get('replays') or {}).get(k, {}).get('implemented') and not (O[t['name']].get('replays') or {}).get(k, {}).get('not_available'))))
    # ---- verdicts
    vi = res['verdict_inputs']; mat2 = [x for x in acc if x['material_2x_RJ_vs_REPAIRED']]; mat43 = [x for x in acc if x['material_4_3_RJ_vs_REPAIRED'] and not x['material_2x_RJ_vs_REPAIRED']]
    pres_ok = all(not vi.get(sub, {}).get(a, {}).get('regressions_vs_DGP6') for sub in ('preservation_18', 'preservation_13') for a in ARMS) and not any(mi['historical_lost'][a] for a in ARMS) and not mi['REPAIRED_not_RJ'] and not mi['REPAIRED_not_RO']
    pres_complete = all(vi.get(sub, {}).get(a, {}).get('ran') == vi.get(sub, {}).get(a, {}).get('n') for sub in ('preservation_18', 'preservation_13') for a in ARMS if vi.get(sub)) and all(not mi['historical_not_run'][a] for a in ARMS)
    flags = [x['task'] for x in cost if x['flag_slower']]; flags_ro = [x['task'] for x in cost if x['flag_slower_RO']]; fr_over = (fr.get('confirmation') or {}).get('overhead_cases') or ['dg_n32_c2_clique_half', 'dg_n32_c2_clique_two', 'dg_n64_c2_reg6_half', 'dg_n64_c2_reg6_two']
    mc = vi['mechanism_counts']; main_rj = mc.get('main/RESIDUAL_JOINT', {}); main_ro = mc.get('main/RESIDUAL_ONLY', {}); main_r = mc.get('main/REPAIRED', {})
    fcs = {}
    for r in em:
        gcell = r['arms'].get('RESIDUAL_JOINT')
        if not gcell or gcell['complete']: continue
        dm = gcell.get('direct') or {}; sub = failure_subreason(dm); fcs[r['task']] = dict(label=FAILURE_LABEL, sub_reason=sub, worst=gcell['worst_radius'], draws=dm.get('draws'), changed_law_commits=dm.get('changed_law_commits'), future_draws=dm.get('future_draws_under_new_law'), attempts=[(a.get('status'), a.get('kind'), a.get('promoted')) for a in (dm.get('attempts') or [])], closed=dm.get('closed'))
    by_cls = {}
    for t, v in fcs.items(): by_cls.setdefault(v['sub_reason'].split(' (')[0], []).append(t)
    hard3 = [x for x in mat2 if x['task'] in set(hard8) | set(ANCHORS)]; dep = ('candidate' if (mi['new_dense_completion_candidates'] or (len(hard3) >= 3 and any('_n64_' in x['task'] for x in hard3))) else ('secondary_4_3_candidate' if mat43 else 'NONE'))
    diag['verdicts'] = dict(validity='see VALIDATION.json + controls (identity_ok on every cell; ledger identity on every planner result; before / after probes of the eight findings; D1-D70; HP80 / unified57 / scheduling32 / accepted PAC suites); the supplied floating reference comparison NOT RUN (absent); missing packet items stay INCOMPLETE',
                            preservation=dict(status=('PRESERVED' if (pres_ok and pres_complete) else ('REGRESSION' if not pres_ok else 'INCOMPLETE')), historical_24_lost={a: mi['historical_lost'][a] for a in ARMS}, historical_24_not_run={a: mi['historical_not_run'][a] for a in ARMS}, REPAIRED_not_RJ=mi['REPAIRED_not_RJ'], REPAIRED_not_RO=mi['REPAIRED_not_RO'], preservation_18={a: vi.get('preservation_18', {}).get(a) for a in ARMS}, preservation_13={a: vi.get('preservation_13', {}).get(a) for a in ARMS}, rule='no loss of any historical (24 DGP6) or same-round comparator completion; 18 / 18 and 13 / 13 retained in all three arms'),
                            mechanism=dict(status=MG['status'], exposed_pass=MG['exposed_pass'], exposed_run=MG['exposed_run'], fresh_pass=MG['fresh_pass'], fresh_run=MG['fresh_run'], fresh_claim=MG['fresh_claim'], rule=MG['rule']), execution=dict(status=XG['status'], n32=XG['n32_pass'], n64=XG['n64_pass'], numerator=XG['numerator'], denominator=XG['denominator'], rule=XG['rule']),
                            deployable_progress=dict(status=dep, candidates=mi['new_dense_completion_candidates'], material_2x=[x['task'] for x in mat2], material_2x_hard_anchors=[x['task'] for x in hard3], secondary_4_3=[x['task'] for x in mat43], fresh_transfer=sorted(t for t in (mi['new_dense_completion_candidates'] + [x['task'] for x in mat2]) if is_fresh(t)), rule='a confirmed new dense completion, or a confirmed >= 2x worst-radius improvement on three hard anchors incl. n64, at equal total cost and without preservation loss; a confirmed 4/3 improvement is secondary accuracy progress (never deployment); confirmations decide the final status'),
                            cost_overhead=dict(flags=flags, flags_RESIDUAL_ONLY=flags_ro, n_mutual_completions=len(cost), median_ratio_RJ_over_REPAIRED=med([x['ratio_RJ_over_REPAIRED'] for x in cost]), median_RJ_construction_s=med([x['RJ_construction_s'] for x in cost]), dgp5_overhead_cases=fr_over, dgp5_overhead_cases_flagged_now=[t for t in fr_over if t in flags], status=('FLAGGED' if flags else 'none'), rule='both > 0.1 s and > 1.25 x REPAIRED on a mutual completion; confirmed in both confirmation seeds; a good median cannot erase a flag'),
                            arms_attribution=dict(RJ_not_RO=mi['RJ_not_RO'], RO_not_RJ=mi['RO_not_RJ'], RO_not_REPAIRED=mi['RO_not_REPAIRED'], median_ratio_RO_over_RJ_worst=med([x['ratio_RO_over_RJ'] for x in acc]), median_ratio_REPAIRED_over_RJ_worst=med([x['ratio_REPAIRED_over_RJ'] for x in acc]), RO_same_law_commits=main_ro.get('same_law_commits'), RJ_changed_law_commits=main_rj.get('changed_law_commits'), note='RESIDUAL_ONLY isolates the bank / window machinery with the law frozen (checked same-law tightening only); RESIDUAL_JOINT adds the local joint fit'),
                            eight_second_diagnostic=dict(n_cells=len(diag_rows), changed_law_cells={a: sum(1 for x in diag_rows if x['arm'] == a and (x.get('changed_law_commits') or 0) > 0) for a in DIAG_ARMS}, completions={a: sum(1 for x in diag_rows if x['arm'] == a and x['outcome'] in ('COMPLETE', 'EXACT')) for a in DIAG_ARMS}, note='REPAIRED_8 / RESIDUAL_JOINT_8 (W / 2 account; min(E_rem, 0.50 initial work, 8 s)) on the eight pinned models only; never the 4 s cohort; an eight-second-only execution cannot pass the four-second gate'),
                            mechanism_counts=dict(main_RESIDUAL_JOINT=main_rj, main_RESIDUAL_ONLY=main_ro, main_REPAIRED=main_r, all=mc), failure_classes=dict(label=FAILURE_LABEL, by_sub_reason={k: sorted(v) for k, v in by_cls.items()}, per_task=fcs))
    res['verdicts'] = diag['verdicts']; res['gates'] = diag['gates']; json.dump(diag, open(os.path.join(RD, 'DIAGNOSTICS.json'), 'w'), indent=1, default=str)
    rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP7_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; bud = load(os.path.join(RD, 'BUDGET_DECLARATION.json')) or {}
    ch = dict(utc=res['utc'], ceiling_s=bud.get('ceiling_s'), allocation_s=bud.get('allocations') or bud.get('allocation_s'), reassignments=bud.get('reassignments'), by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), completed=sum(1 for r in rc if r['outcome'] == 'COMPLETED'), by_outcome={o: sum(1 for r in rc if r['outcome'] == o) for o in sorted({r['outcome'] for r in rc})}, within_ceiling=(sum(r['wall_s'] for r in rc) <= (bud.get('ceiling_s') or 1e18)), ledger='DGP7_LEDGER.jsonl', implementation_labor='reported separately in controls/UNSUPERVISED_DEV_LOG.md (not charged); every computational probe is charged under dgp7_dev', spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r.get('jid') == s['jid'] for r in rc)])
    json.dump(ch, open(os.path.join(RD, 'CHARGES.json'), 'w'), indent=1); res['charges'] = ch
    planned = []
    def plan(sub, names, arms, seeds, confirm, contract):
        for nm in names:
            for a in arms:
                for s in seeds: planned.append(dict(sub=sub, task=nm, arm=a, seed_index=s, confirm=confirm, contract=contract))
    released = bool(load(os.path.join(RD, 'RELEASE_DECISION.json')) and (load(os.path.join(RD, 'RELEASE_DECISION.json')) or {}).get('released'))
    plan('gate', ANCHORS, ['RESIDUAL_JOINT'], [0, 1], False, 'main'); plan('main', (main_names if released else guard_names), ARMS, [0], False, 'main'); plan('preservation_18', [t['name'] for t in tp.get('preservation_18', [])], ARMS, [0], False, 'p4'); plan('preservation_13', [t['name'] for t in tp.get('preservation_13', [])], ARMS, [0], False, 'p20'); plan('policy8', [t['name'] for t in tp.get('policy8_8', tp.get('policy8', []))], DIAG_ARMS, [0], False, 'main')
    cm = load(os.path.join(RD, 'CONFIRM_MANIFEST.json'))
    if cm: plan('confirm', cm['selected'], ARMS, [1, 2], True, 'per task')
    actual = {}
    for sub in SUBS:
        for c in cells_of(sub): actual[(sub, c['task'], c['arm'], c.get('seed_index', 0), c['confirm'])] = dict(dir=os.path.relpath(c['_dir'], RD), outcome=c.get('outcome'), receipt=c.get('receipt_outcome'), complete=c.get('complete'))
    for p in planned:
        p['actual'] = actual.get((p['sub'], p['task'], p['arm'], p['seed_index'], p['confirm']))
        if not p['actual'] and p['sub'] == 'main' and (p['task'] in ANCHORS) and p['arm'] == 'RESIDUAL_JOINT': p['actual'] = actual.get(('gate', p['task'], p['arm'], 0, False)); p['reason'] = None if p['actual'] else None
        p['reason'] = None if p['actual'] else ('not run: broad phase not released (mandatory guard subset only)' if (p['sub'] == 'main' and not released) else 'not run (see REPORT.md: budget / blocked)')
    oracle_actual = {t['name']: os.path.exists(os.path.join(RD, 'oracle', 'results', t['name'] + '.json')) for t in oracle_tasks}
    json.dump(dict(utc=res['utc'], code_commit=fr['code'].get('commit'), released=released, planned=planned, n_planned=len(planned), n_actual=sum(1 for p in planned if p['actual']), oracle=oracle_actual, replay_coverage=diag['gates']['replay_coverage'], superseding_links=('see ' + ', '.join(os.path.basename(x) for x in glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json'))) if glob.glob(os.path.join(RD, 'FREEZE_AMENDMENT*.json')) else 'none'), cells_joined_by='model_sha256 + evid_sha256 + contract (names resolved from MODEL_MANIFEST by model_sha256)'), open(os.path.join(RD, 'RUN_MANIFEST.json'), 'w'), indent=1, default=str)
    json.dump(res, open(os.path.join(RD, 'RESULTS.json'), 'w'), indent=1, default=str); print(json.dumps(dict(completions=res['completions_by_sub'], main=mi.get('n_complete'), new=mi.get('new_dense_completion_candidates'), verdicts={k: (v if isinstance(v, str) else (v.get('status') if isinstance(v, dict) else None)) for k, v in diag['verdicts'].items()}, mechanism=main_rj, gate=XG['status']), default=str)[:1800])
    return res, diag

def select_confirm():
    res = load(os.path.join(RD, 'RESULTS.json')); man, tp = panels(); vi = res['verdict_inputs']; meta = {}
    for p in tp.values():
        for t in p: meta.setdefault(t['name'], t)
    mi = vi['main']; key = lambda t: meta[t]['model_sha256'] if t in meta else t; fr = load(os.path.join(RD, 'FREEZE.json')) or {}; conf = fr.get('confirmation') or {}
    overhead_cases = conf.get('overhead_cases') or ['dg_n32_c2_clique_half', 'dg_n32_c2_clique_two', 'dg_n64_c2_reg6_half', 'dg_n64_c2_reg6_two']; anchors = conf.get('anchors') or ANCHORS; max_tasks = conf.get('max_tasks', 7)
    tiers = [('a_completion_loss', sorted(set(mi['REPAIRED_not_RJ'] + mi['REPAIRED_not_RO'] + [t for a in ARMS for t in mi['historical_lost'][a]]), key=key)), ('b_new_completion', sorted(set(mi['RJ_not_REPAIRED']) | set(mi['RO_not_REPAIRED']), key=key)), ('c_radius_gain_2x', sorted({x['task'] for x in vi['accuracy_mutual_failures'] if x['material_2x_RJ_vs_REPAIRED']}, key=key)), ('c2_radius_gain_4_3', sorted({x['task'] for x in vi['accuracy_mutual_failures'] if x['material_4_3_RJ_vs_REPAIRED']}, key=key)), ('d_overhead_flags', sorted({x['task'] for x in vi['cost_mutual_completions'] if x['flag_slower']} | set(overhead_cases), key=key)), ('e_n64_coverage', sorted([t for t in anchors if '_n64_' in t], key=key)), ('f_anchors', anchors)]
    chosen = []; affected = []
    for name, ts in tiers:
        for t in ts:
            if name not in ('e_n64_coverage', 'f_anchors'): affected.append((name, t))
            if t not in chosen and len(chosen) < max_tasks: chosen.append(t)
    if not any('_n64_' in t for t in chosen) and len(chosen) >= max_tasks: chosen[-1] = next(t for t in anchors if '_n64_' in t)                         # n64 coverage is mandatory (PROTOCOL section 6)
    cm = dict(rule='PROTOCOL.md section 6 (priority losses, new completions, >= 2x then >= 4/3 radius gains, overhead flags incl. the four DGP5 overhead cases, n64 coverage, strong anchors; stable model-hash order; deduplicated; <= 7 tasks x 3 arms x seeds 1 / 2; reverse arm order)', tiers={n: ts for n, ts in tiers}, affected_all=affected, selected=chosen, unconfirmed_affected=[t for n, t in affected if t not in chosen], tasks=[dict(meta[t], contract=('p4' if (meta[t].get('panel') or '').startswith('unified_18') or meta[t].get('contract') == 'p4' else 'main')) for t in chosen if t in meta], utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(cm, open(os.path.join(RD, 'CONFIRM_MANIFEST.json'), 'w'), indent=1); print(json.dumps({k: v for k, v in cm.items() if k != 'tasks'}))

def report():
    R = load(os.path.join(RD, 'RESULTS.json')); D = load(os.path.join(RD, 'DIAGNOSTICS.json')); fr = load(os.path.join(RD, 'FREEZE.json')) or {'code': {}}; L = []
    def P(s=''): L.append(s)
    def f4(x): return ('%.4f' % x) if isinstance(x, (int, float)) else '-'
    def f2(x): return ('%.2f' % x) if isinstance(x, (int, float)) else '-'
    vi = R['verdict_inputs']; mi = vi['main']; V = R['verdicts']; G = R['gates']; mc = vi['mechanism_counts']; XG = vi['execution_gate']
    P('# DGP7 -- REPORT (derived by dgp7_analyze.py from the raw cells, oracle outputs and the ledger)'); P(); P('Frozen code: pgm %s (tree %s). Analyzer utc %s. Every count below is recomputed from `runs/*/*/cell.json`, `oracle/results/*.json` and `DGP7_LEDGER.jsonl`. No unrun cell is a failure or a confirmation; numerators / denominators are given per gate.' % ((fr['code'].get('commit') or '')[:9], (fr['code'].get('tree') or '')[:9], R['utc'])); P()
    P('## 1. Verdicts (kept separate)'); P(); P('| verdict | status | basis |'); P('|---|---|---|')
    P('| validity / resources | see VALIDATION.json | %d / %d cells identity_ok; ledger identity on every planner result (validate_round); before / after probes of the eight findings; D1-D70 + HP80 + unified57 + scheduling32 + accepted PAC suites; the supplied floating reference comparison NOT RUN (absent) |' % (sum(v['by_arm'][a]['identity_ok'] for v in R['completions_by_sub'].values() for a in v['by_arm']), sum(v['cells'] for v in R['completions_by_sub'].values())))
    pv = V['preservation']; P('| preservation | **%s** | historical 24 lost: %s; not run: %s; REPAIRED-not-RJ %s; REPAIRED-not-RO %s; preservation_18 %s; preservation_13 %s |' % (pv['status'], {a: len(v) for a, v in pv['historical_24_lost'].items()}, {a: len(v) for a, v in pv['historical_24_not_run'].items()}, pv['REPAIRED_not_RJ'], pv['REPAIRED_not_RO'], {a: ('%s/%s' % ((pv['preservation_18'].get(a) or {}).get('complete'), (pv['preservation_18'].get(a) or {}).get('n'))) for a in ARMS}, {a: ('%s/%s' % ((pv['preservation_13'].get(a) or {}).get('complete'), (pv['preservation_13'].get(a) or {}).get('n'))) for a in ARMS}))
    mg = V['mechanism']; P('| mechanism (oracle; production RESIDUAL_JOINT vs seed) | **%s** | exposed reference cliques passing %s of %s run (of 3); fresh ORACLE7 cliques passing %s of %s run (fresh claim: %s) (%s) |' % (mg['status'], mg['exposed_pass'], mg['exposed_run'], mg['fresh_pass'], mg['fresh_run'], mg['fresh_claim'], mg['rule']))
    xg = V['execution']; P('| execution gate (n32 / n64 anchors x paired seeds) | **%s** | n32 passing %s; n64 passing %s; numerator %s / denominator %s (%s) |' % (xg['status'], xg['n32'], xg['n64'], xg['numerator'], xg['denominator'], xg['rule']))
    ep = V['deployable_progress']; P('| deployment | **%s** | new dense completion candidates %s; >= 2x mutual-failure gains vs REPAIRED %s (hard anchors %s); secondary 4/3 %s; fresh transfer %s (%s) |' % (ep['status'], ep['candidates'], ep['material_2x'], ep['material_2x_hard_anchors'], ep['secondary_4_3'], ep['fresh_transfer'], ep['rule']))
    co = V['cost_overhead']; P('| overhead | %s | flags %s on %d mutual completions (RESIDUAL_ONLY flags %s); the four DGP5 overhead cases flagged now: %s; median RJ / REPAIRED wall %s; median RJ construction %s s |' % (co['status'], co['flags'], co['n_mutual_completions'], co['flags_RESIDUAL_ONLY'], co['dgp5_overhead_cases_flagged_now'], f2(co['median_ratio_RJ_over_REPAIRED']), f2(co['median_RJ_construction_s'])))
    aa = V['arms_attribution']; P('| arms attribution (RESIDUAL_ONLY vs RESIDUAL_JOINT) | descriptive | RJ-not-RO %s; RO-not-RJ %s; RO-not-REPAIRED %s; RO same-law commits %s; RJ changed-law commits %s; median RO / RJ worst radius %s |' % (aa['RJ_not_RO'], aa['RO_not_RJ'], aa['RO_not_REPAIRED'], aa['RO_same_law_commits'], aa['RJ_changed_law_commits'], f2(aa['median_ratio_RO_over_RJ_worst'])))
    e8 = V['eight_second_diagnostic']; P('| eight-second diagnostic | descriptive | %d cells; changed-law cells %s; completions %s (%s) |' % (e8['n_cells'], e8['changed_law_cells'], e8['completions'], e8['note'][:120])); P()
    P('## 2. Execution gate cells (RESIDUAL_JOINT, four anchors x seeds 0 / 1, 20 s / 4 s)'); P(); P('| task | seed | passes | changed-law commits | same-law | future draws under the new law | allowance s | seed s | READY | closed | outcome |'); P('|---|---|---|---|---|---:|---:|---:|---|---|---|')
    for x in XG['cells']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], x['seed_index'], x['passes'], x['changed_law_commits'], x['same_law_commits'], x['future_draws'], f2(x['allowance_s']), f2(x['seed_s']), x['ready'], (x['closed'] or '-')[:40], x['outcome']))
    P(); P('## 3. Main matrix (%d tasks x 3 arms, 20 s; released: %s)' % (mi['n_tasks'], (load(os.path.join(RD, 'RELEASE_DECISION.json')) or {}).get('released'))); P(); P('Ran: ' + ', '.join('%s %d' % (a, mi['n_ran'][a]) for a in ARMS) + '. Completions: ' + ', '.join('%s %d' % (a, mi['n_complete'][a]) for a in ARMS) + '; identical sets across the three arms: %s. Historical 24 lost: %s. Hard 8 completed: %s. Fresh EVAL7 completions: %s.' % (mi['identical_sets_all_three'], {a: len(mi['historical_lost'][a]) for a in ARMS}, {a: mi['hard8_completed'][a] for a in ARMS}, {a: len(mi['fresh_complete'][a]) for a in ARMS})); P()
    P('| task | panel | REPAIRED | RESIDUAL_ONLY | RESIDUAL_JOINT | RJ worst r | RO worst r | REPAIRED worst r | RJ mechanism (probe / offered / created / READY / atoms / windows fitted / changed-law / same-law / future draws) | RJ attempts |'); P('|---|---|---|---|---|---:|---:|---:|---|---|')
    for r in R['tables'].get('main_matrix', []):
        A = r['arms']; g = (A.get('RESIDUAL_JOINT') or {}).get('direct') or {}; b_ = g.get('bank') or {}
        P('| %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s / %s / %s / %s / %s / %s / %s | %s |' % (r['task'], (r.get('panel') or '')[:10], *['C' if (A.get(a) or {}).get('complete') else ((A.get(a) or {}).get('outcome') or '-')[:8] for a in ARMS], f4((A.get('RESIDUAL_JOINT') or {}).get('worst_radius')), f4((A.get('RESIDUAL_ONLY') or {}).get('worst_radius')), f4((A.get('REPAIRED') or {}).get('worst_radius')), (g.get('primary_probe') or {}).get('batches', '-') if isinstance(g.get('primary_probe'), dict) else '-', 'Y' if g.get('offered') else 'n', 'Y' if g.get('created') else 'n', 'Y' if g.get('ready') else 'n', b_.get('live_atoms', '-'), g.get('windows_fitted', '-'), g.get('changed_law_commits', '-'), g.get('same_law_commits', '-'), g.get('future_draws_under_new_law', '-'), '; '.join('%s%s' % (a_.get('status'), (':' + str(a_.get('kind'))) if a_.get('kind') and a_.get('status') in ('REFUSED', 'PROMOTED') else '') for a_ in (g.get('attempts') or [])) or '-'))
    P(); P('Mechanism counts (main / RESIDUAL_JOINT): %s. Main / RESIDUAL_ONLY: %s. Main / REPAIRED: %s.' % (json.dumps(mc.get('main/RESIDUAL_JOINT'), default=str)[:900], json.dumps(mc.get('main/RESIDUAL_ONLY'), default=str)[:600], json.dumps(mc.get('main/REPAIRED'), default=str)[:400])); P()
    P('## 4. Mutual failures: worst radius on the full inventory (0.5 = vacuous)'); P(); P('| task | n | fresh | hard8 | REPAIRED | RESIDUAL_ONLY | RESIDUAL_JOINT | REPAIRED / RJ | RO / RJ | 2x | 4/3 | RJ changed-law / future draws | RJ covered / K |'); P('|---|---|---|---|---:|---:|---:|---:|---:|---|---|---|---|')
    for x in vi['accuracy_mutual_failures']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s | %s / %s |' % (x['task'], x.get('n'), x['fresh'], x['hard8'], f4(x['REPAIRED_worst']), f4(x['RESIDUAL_ONLY_worst']), f4(x['RESIDUAL_JOINT_worst']), f2(x['ratio_REPAIRED_over_RJ']), f2(x['ratio_RO_over_RJ']), 'Y' if x['material_2x_RJ_vs_REPAIRED'] else '', 'Y' if x['material_4_3_RJ_vs_REPAIRED'] else '', (x['rj_mech'] or {}).get('changed_law_commits'), (x['rj_mech'] or {}).get('future_draws_under_new_law'), x['RJ_covered'], x['K']))
    P(); P('## 5. Mutual completions: cost'); P(); P('| task | REPAIRED s | RESIDUAL_ONLY s | RESIDUAL_JOINT s | RJ / REPAIRED | flag | RJ created | RJ construction s | REPAIRED probe s |'); P('|---|---:|---:|---:|---:|---|---|---:|---:|')
    for x in vi['cost_mutual_completions']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (x['task'], f2(x['REPAIRED_s']), f2(x['RESIDUAL_ONLY_s']), f2(x['RESIDUAL_JOINT_s']), f2(x['ratio_RJ_over_REPAIRED']), 'FLAG' if x['flag_slower'] else '', x['RJ_created'], f2(x['RJ_construction_s']), f2(x['REPAIRED_probe_s'])))
    P(); P('## 6. Preservation'); P()
    for sub in ('preservation_18', 'preservation_13'):
        v = vi.get(sub)
        if v: P('- %s: ' % sub + '; '.join('%s %s / %s (ran %s; regressions vs DGP6 %s; offered / created / sampled %s / %s / %s)' % (a, v[a]['complete'], v[a]['n'], v[a]['ran'], v[a]['regressions_vs_DGP6'], v[a]['offered'], v[a]['created'], v[a]['sampled']) for a in ARMS if v.get(a)) + '; historical complete %s.' % v['historical_complete'])
    P(); P('## 7. Eight-second diagnostic cells (REPAIRED_8 / RESIDUAL_JOINT_8 on the eight pinned models) and forced cells'); P(); P('| sub | task | arm | outcome | wall s | worst r | main REPAIRED r | main RJ r | main RJ changed-law | created / READY / draws / epochs | changed-law / same-law / future draws | allowance s | attempts |'); P('|---|---|---|---|---:|---:|---:|---:|---|---|---|---:|---|')
    for x in vi['diagnostics']: P('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s / %s / %s | %s / %s / %s | %s | %s |' % (x['sub'], x['task'], x['arm'], x['outcome'], f2(x['receipt_wall_s']), f4(x['worst_radius']), f4(x['main_REPAIRED_worst']), f4(x['main_RJ_worst']), x['main_RJ_changed'], x['created'], x['ready'], x['draws'], x['epochs'], x['changed_law_commits'], x['same_law_commits'], x['future_draws'], f2(x['allowance_s']), '; '.join('%s%s' % (a_.get('status'), (':' + str(a_.get('kind'))) if a_.get('status') in ('REFUSED', 'PROMOTED') else '') for a_ in (x.get('attempts') or [])) or '-'))
    P(); P('## 8. Oracle mechanism panel (12 models)'); P(); P('Units: ' + D['units']); P()
    P('| model | status | seed log2 M2 | seed B / R* bits | RJ_final: M2 gain bits / cap ratio / inside allowance / B over R* | RO_final: gain / cap ratio | injected (true context): gain / cap | uniform DIAG: gain / cap | whole-model | replay worst (impl.): seed / RJ / RO / ideal | cert ratios seed / RJ | M gate |'); P('|---|---|---:|---:|---|---|---|---|---|---|---|---|')
    for o in D['oracle']:
        c = o.get('contrasts') or {}; rj = c.get('RJ_final') or {}; ro = c.get('RO_final') or {}; inj = c.get('oracle_injected_true_context') or {}; un = c.get('uniform_context_DIAGNOSTIC') or {}
        P('| %s | %s | %s | %s | %s / %s / %s / %s | %s / %s | %s / %s | %s / %s | %s | %s / %s / %s / %s | %s | %s |' % (o['task'], (o.get('status') or '')[:14], f2(c.get('seed_M2')), f2(c.get('seed_B_over_Rstar')), f2(rj.get('M2_gain_bits')), f2(rj.get('cap_ratio_vs_seed')), rj.get('inside_allowance'), f2(rj.get('B_over_Rstar')), f2(ro.get('M2_gain_bits')), f2(ro.get('cap_ratio_vs_seed')), f2(inj.get('M2_gain_bits')), f2(inj.get('cap_ratio_vs_seed')), f2(un.get('M2_gain_bits')), f2(un.get('cap_ratio_vs_seed')), o.get('whole_model_region'), ' '.join(f4(w) for w in (c.get('seed_worst') or [])), ' '.join(f4(w) for w in (rj.get('worst') or [])), ' '.join(f4(w) for w in (ro.get('worst') or [])), ' '.join(f4(w) for w in (c.get('ideal_worst') or [])), ' '.join(f2(w) for w in (rj.get('certificate_ratios_seed_over') or []) if w is not None), c.get('mechanism_gate_RJ')))
    P(); P('Replay coverage: %s.' % json.dumps(G.get('replay_coverage', {}), default=str)[:400]); P()
    P('## 9. Failure classes (RESIDUAL_JOINT, main matrix) -- label: %s' % FAILURE_LABEL); P()
    for k, v in (V['failure_classes']['by_sub_reason'] or {}).items(): P('- **%s**: %s' % (k, ', '.join(v)))
    P(); P('## 10. Charges'); P(); ch = R['charges']; P('Total %.1f s of the %s s ceiling (%d receipts; %s). By scope: %s. Reassignments: %s. Launches without a receipt: %s.' % (ch['total_s'], ch['ceiling_s'], ch['n_receipts'], json.dumps(ch['by_outcome']), json.dumps(ch['by_scope_s']), json.dumps(ch.get('reassignments'), default=str)[:600], ch.get('spawned_without_receipt'))); P()
    P('## 11. Limitations'); P(); P('- Geometry alone does not establish PAC containment on a model without an oracle; the oracle panel (<= 2^16 states) is the only containment check; exact-rational checks only <= 4,096 states, floating enumeration above is a diagnostic.'); P('- The local proxy G is floating and advisory; only the kernel\'s compact B / rho enter an epoch; a proxy win is not a performance win (section 5 decides cost).'); P('- Context weights are the proposal\'s (exact when parent-closed, else 1,024 advisory draws); the oracle-injected law shows what TRUE context weights would give and never reaches production.'); P('- A finite candidate or a policy refusal never establishes a family ceiling; the supplied floating reference was not available on this machine (its comparison is NOT RUN).')
    open(os.path.join(RD, 'REPORT.md'), 'w').write('\n'.join(L) + '\n'); print('REPORT.md written', len(L), 'lines')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'analyze'
    if cmd == 'analyze': analyze()
    elif cmd == 'select-confirm': select_confirm()
    elif cmd == 'report': report()
