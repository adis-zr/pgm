"""Round-20 controls (integrated v2.12, layered contraction ON): the certified layered-contraction constructor against brute-force enumeration of the ORIGINAL model (containment of every
original coordinate AND of Z in the enclosure, points summing to one), on REAL work. L1 the packet's sixteen tiny transfer fixtures end to end through solve (closure APPLIED on each:
the route binds to the original model, no double decoder / scalar); L2 generated chain models: channel parameters away from 9/10 (7/10, 2/3), hard zeros, weighted nonbinary local
variables, births / deaths of chains, a terminal coupling residual (proposal residual_terminal), a low-end anchor (reflection), external evidence on a local and on a selector variable,
a one-state and a factorless nonbinary variable (EXACT rows with point inside), variable renaming + factor-order reversal + scope-axis permutation (same structural bounds, every row
contains the truth, every pair overlaps); L3 typed refusals with the existing route completing: no channel, branching channel graph, cyclic channel graph, a residual spanning a
nonadjacent interval; L4 bounds on real work: a 17-bit / 8-layer model whose kernel work is ~1 s -- (a) a real deadline inside the native kernel returns DEADLINE with nothing published
and no fallback phases, (b) the forecast covers the kernel's hard-charged peak, (c) an injected byte cap refuses BEFORE the executor and the existing route completes, (d) an injected
rows-per-second rate refuses on time BEFORE the executor, (e) a clock that expires right after the executor returns gives DEADLINE with nothing published; L5 the switch
(--no-layered-contraction in a subprocess and layered_contraction=False in process) reproduces the v2.11.2 path; L6 the exposed target's STRUCTURE only (no numerical solve here):
recognition in well under the allowance with the packet's bounds (20 interface bits, 2^21 max product, 2^20 max output, 885 active, 16 admissible of 32), and the same bounds after
reversing variable ids, a seeded random relabel, and changing every channel to 4/5 / 1/5."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, random, time, math, itertools, subprocess
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = str(_repo_root())
import pgm.algorithms.block.integrated as IG, pgm.algorithms.block.layered_contraction as LC, pgm.algorithms.structural.core as core
IG.ANCESTRAL_RESPONSE_DEFAULT = False       # (round 22) this suite exercises the layered route; the ancestral-response constructor (which runs first) has its own suite, check_round22.py
assert IG.LAYERED_CONTRACTION_DEFAULT is True and IG.SUPPORT_CLOSURE_DEFAULT is True and IG.EVIDENCE_EXPANSION_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []; rng = random.Random(2001)
RD = str(_runs_root() / 'mdi_2026-10-28/BLOCKRES_2026-11-19'); PACKET = os.path.join(RD, 'round20/R20_PACKET')
LINK = str(_runs_root() / 'mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06/sources/uai14/prob/linkage_13.uai')
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:460], flush=True)
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def brute(p):
    model, _ = core.read_uai(p); cards = model['cards']; n = len(cards); ev = model['evidence']; z = F(0); num = {}
    for xs in itertools.product(*(range(c) for c in cards)):
        if any(xs[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in model['factors']:
            ix = 0
            for v in f['scope']: ix = ix * cards[v] + xs[v]
            w *= f['values'][ix]
        if w == 0: continue
        z += w
        for v in range(n):
            if v not in ev: num[(v, xs[v])] = num.get((v, xs[v]), F(0)) + w
    return z, ({k: v / z for k, v in num.items()} if z else None)
def check(res, p, need_route='layered_contraction'):
    """every published row contains the truth with the point inside; Z enclosure contains Z; per-variable points sum to one; complete; route as required"""
    z, tv = brute(p); miss = 0; K = res['K']; sums = {}
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': miss += 1; continue
        lo, hi, pt = F(a['lo']), F(a['hi']), F(a['point']); t = tv.get((a['var'], a['state']), F(0)) if tv else None
        if t is None or not (lo <= t <= hi and lo <= pt <= hi): miss += 1
        sums.setdefault(a['var'], []).append(pt)
    ze = res.get('Z_enclosure'); zc = bool(ze) and F(ze['lo']) <= z <= F(ze['hi'])
    ok = miss == 0 and res['published'] == K and res['outcome'] in (('COMPLETE',) if need_route == 'layered_contraction' else ('COMPLETE', 'EXACT')) and all(sum(v) == 1 for v in sums.values()) and (need_route is None or res['mechanism'].get('route') == need_route) and (need_route != 'layered_contraction' or zc)
    return ok, dict(miss=miss, published=res['published'], K=K, outcome=res['outcome'], route=res['mechanism'].get('route'), Z_contained=zc, max_width=res.get('max_width'))
def solve(p, budget=10.0, **kw): return IG.solve(p, budget, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted', **kw)
def lc(res): return res['mechanism'].get('layered_contraction') or {}
# ---- generator: T layers, b selector chains, one local variable per layer joined to the selectors by a Boolean constraint + unary weights; options
def gen(name, T=3, b=2, local_cards=(2, 3, 2, 3), channel=(F(9, 10), F(1, 10)), zero=False, residual=None, chain_life=None, evidence=None, weighted_local=False, extra=()):
    a, bb = channel; cards = []; s = [[None] * b for _ in range(T)]; x = [None] * T
    for t in range(T):
        for i in range(b): s[t][i] = len(cards); cards.append(2)
        x[t] = len(cards); cards.append(local_cards[t % len(local_cards)])
    facs = []
    for i in range(b):
        lo_t, hi_t = (chain_life[i] if chain_life else (0, T - 1))
        for t in range(lo_t, hi_t): facs.append(((s[t][i], s[t + 1][i]), [a, bb, bb, a]))
    for t in range(T):
        c = cards[x[t]]
        if weighted_local: vals = [F(rng.randrange(1, 10), 10) for _ in range(c * 2 ** b)]
        else: vals = [F(1) if (xs % c) == (sum(((idx >> (b - 1 - k)) & 1) for k in range(b)) % c) else F(0) for xs in range(c) for idx in range(2 ** b)]      # x == (sum of selectors) mod c : Boolean local core
        facs.append(((x[t],) + tuple(s[t]), vals))
        w = [F(rng.randrange(1, 10), 10) for _ in range(c)]
        if zero and t == 1: w[0] = F(0)
        facs.append(((x[t],), w)); facs.append(((s[t][0],), [F(1, 2), F(1, 2)]))
    if residual is not None:
        t1, t2 = residual; facs.append(((x[t1], x[t2]), [F(rng.randrange(1, 10), 10) for _ in range(cards[x[t1]] * cards[x[t2]])]))
    for sc, vals in extra: facs.append((sc, vals))
    return write_uai(name, cards, facs, evidence), dict(s=s, x=x, cards=cards)
# ---- L1: the packet's sixteen tiny fixtures end to end
det = []; info1 = []
for k in range(16):
    p = os.path.join(PACKET, 'theory_r20_prototype/tiny/case%d.uai' % k); r = solve(p); ok, d = check(r, p); det.append(ok); info1.append(dict(case=k, closure=(r['mechanism'].get('support_closure') or {}).get('status'), **d))
say(dict(control='L1_packet_tiny_fixtures_end_to_end_contained_Z_enclosed_closure_bound_once', cases=16, ok=all(det), sample=info1[:3], widths_max=max(x['max_width'] for x in info1)))
# ---- L2: generated adversarial chain models
cases = {}
cases['channel_7_3'] = gen('r20_ch73', channel=(F(7, 10), F(3, 10)))[0]
cases['channel_2_3'] = gen('r20_ch23', channel=(F(2, 3), F(1, 3)))[0]
cases['hard_zero'] = gen('r20_zero', zero=True)[0]
cases['weighted_nonbinary_locals'] = gen('r20_wl', local_cards=(3, 4, 3), weighted_local=True)[0]
cases['births_deaths'] = gen('r20_bd', T=4, b=3, chain_life=[(0, 3), (1, 3), (0, 2)])[0]
cases['terminal_coupling'] = gen('r20_term', T=4, b=2, residual=(2, 3))[0]
cases['low_end_anchor_reflect'] = gen('r20_low', T=4, b=2, residual=(0, 1))[0]
pe, meta = gen('r20_ev_local', T=3, b=2); mo, _ = core.read_uai(pe); cases['evidence_on_local'] = write_uai('r20_ev_local', mo['cards'], [(f['scope'], f['values']) for f in mo['factors']], {meta['x'][1]: 1})
pe, meta = gen('r20_ev_sel', T=3, b=2); mo, _ = core.read_uai(pe); cases['evidence_on_selector'] = write_uai('r20_ev_sel', mo['cards'], [(f['scope'], f['values']) for f in mo['factors']], {meta['s'][1][0]: 1})
pe, meta = gen('r20_ev_both0', T=3, b=2); mo, _ = core.read_uai(pe); cases['evidence_on_local_and_selector'] = write_uai('r20_ev_both', mo['cards'], [(f['scope'], f['values']) for f in mo['factors']], {meta['x'][1]: 2, meta['s'][2][1]: 0})
pe, meta = gen('r20_triv0', T=3, b=2); mo, _ = core.read_uai(pe); n0 = len(mo['cards']); cases['one_state_and_factorless'] = write_uai('r20_triv', mo['cards'] + [1, 3], [(f['scope'], f['values']) for f in mo['factors']] + [((n0,), [F(2, 3)])])
l2 = {}
for name, p in cases.items():
    r = solve(p); ok, d = check(r, p); l2[name] = dict(ok=ok, proposal=(lc(r).get('structure') or {}).get('selected', {}).get('proposal'), folded=(lc(r).get('structure') or {}).get('selected', {}).get('folded_components'), exact_rows=lc(r).get('exact_rows'), **d)
    if name == 'one_state_and_factorless':
        tr = [a for a in r['answers'] if a['var'] in (n0, n0 + 1)]; l2[name]['trivial_rows_exact_point_inside'] = all(a['guarantee'] == 'EXACT' and a['lo'] == a['hi'] == a['point'] for a in tr) and len(tr) == 4; l2[name]['ok'] &= l2[name]['trivial_rows_exact_point_inside']
l2['terminal_coupling']['ok'] &= l2['terminal_coupling']['proposal'] == 'residual_terminal'; l2['low_end_anchor_reflect']['ok'] &= l2['low_end_anchor_reflect']['proposal'] == 'residual_terminal'
# renaming / reversal / axis permutation of the births-deaths model
m0, _ = core.read_uai(cases['births_deaths']); n = len(m0['cards']); perm = list(range(n)); rng.shuffle(perm); inv = {perm[v]: v for v in range(n)}; cards2 = [0] * n
for v in range(n): cards2[perm[v]] = m0['cards'][v]
nf = []
for f in reversed(m0['factors']):
    sc = list(f['scope']); ps = list(range(len(sc))); rng.shuffle(ps); ns = [sc[j] for j in ps]; vs = []
    for xx in itertools.product(*(range(m0['cards'][v]) for v in ns)):
        env = dict(zip(ns, xx)); ix = 0
        for v in sc: ix = ix * m0['cards'][v] + env[v]
        vs.append(f['values'][ix])
    nf.append((tuple(perm[v] for v in ns), vs))
p2 = write_uai('r20_bd_renamed', cards2, nf); r1 = solve(cases['births_deaths']); r2 = solve(p2); ok2, d2 = check(r2, p2)
a1 = {(a['var'], a['state']): a for a in r1['answers']}; a2 = {(inv[a['var']], a['state']): a for a in r2['answers']}
overlap = all(not (F(a1[k]['hi']) < F(a2[k]['lo']) or F(a2[k]['hi']) < F(a1[k]['lo'])) for k in a1) and set(a1) == set(a2)
sb1 = lc(r1)['structure']['selected']; sb2 = lc(r2)['structure']['selected']
l2['renamed_reversed_axis_permuted'] = dict(ok=ok2 and overlap and sb1['max_interface_bits'] == sb2['max_interface_bits'] and sb1['max_local_product_entries'] == sb2['max_local_product_entries'], overlap_every_coordinate=overlap, same_bounds=(sb1['max_interface_bits'], sb2['max_interface_bits'], sb1['max_local_product_entries'], sb2['max_local_product_entries']), **d2)
say(dict(control='L2_generated_chain_models_contained_Z_enclosed', cases={k: {kk: vv for kk, vv in v.items() if kk in ('ok', 'proposal', 'folded', 'outcome', 'route', 'miss', 'published', 'K', 'trivial_rows_exact_point_inside', 'overlap_every_coordinate', 'same_bounds')} for k, v in l2.items()}, ok=all(v['ok'] for v in l2.values())))
# ---- L3: typed refusals, the existing route completes
l3 = {}
pr = os.path.join(PACKET, 'theory_r20_prototype/tiny/refusal.uai'); r = solve(pr); ok, d = check(r, pr, need_route=None); l3['no_channel'] = dict(ok=ok and str(lc(r).get('status')).startswith('NOT_APPLICABLE'), status=str(lc(r).get('status'))[:70], **d)
pb, meta = gen('r20_branch', T=3, b=2); mo, _ = core.read_uai(pb); fs = [(f['scope'], f['values']) for f in mo['factors']] + [((meta['s'][0][0], meta['s'][1][1]), [F(9, 10), F(1, 10), F(1, 10), F(9, 10)])]; pb = write_uai('r20_branch', mo['cards'], fs)
r = solve(pb); ok, d = check(r, pb, need_route=None); l3['branching_channel_graph'] = dict(ok=ok and str(lc(r).get('status')).startswith('NOT_APPLICABLE'), status=str(lc(r).get('status'))[:70], **d)
pc, meta = gen('r20_cycle', T=3, b=2); mo, _ = core.read_uai(pc); fs = [(f['scope'], f['values']) for f in mo['factors']] + [((meta['s'][0][0], meta['s'][2][0]), [F(9, 10), F(1, 10), F(1, 10), F(9, 10)])]; pc = write_uai('r20_cycle', mo['cards'], fs)
r = solve(pc); ok, d = check(r, pc, need_route=None); l3['cyclic_channel_graph'] = dict(ok=ok and str(lc(r).get('status')).startswith('NOT_APPLICABLE'), status=str(lc(r).get('status'))[:70], **d)
pi_ = gen('r20_interior', T=4, b=2, residual=(0, 2))[0]; r = solve(pi_); ok, d = check(r, pi_, need_route=None); l3['residual_spanning_nonadjacent_layers'] = dict(ok=ok and str(lc(r).get('status')).startswith('NOT_APPLICABLE'), status=str(lc(r).get('status'))[:70], **d)
say(dict(control='L3_typed_refusals_existing_route_completes', cases=l3, ok=all(v['ok'] for v in l3.values())))
# ---- L4: bounds on REAL work (17-bit interfaces, 8 layers, weighted locals: ~35 M kernel rows)
def big(name, T=8, b=17):
    cards = []; s = [[None] * b for _ in range(T)]; x = [[None] * (b - 1) for _ in range(T)]
    for t in range(T):
        for i in range(b): s[t][i] = len(cards); cards.append(2)
        for k in range(b - 1): x[t][k] = len(cards); cards.append(2)
    facs = []
    for i in range(b):
        for t in range(T - 1): facs.append(((s[t][i], s[t + 1][i]), [F(9, 10), F(1, 10), F(1, 10), F(9, 10)]))
    for t in range(T):
        for k in range(b - 1): facs.append(((x[t][k], s[t][k], s[t][k + 1]), [F(rng.randrange(1, 10), 10) for _ in range(8)]))
        facs.append(((s[t][0],), [F(1, 2), F(1, 2)]))
    return write_uai(name, cards, facs)
pbig = big('r20_big17'); mbig, bbig = core.read_uai(pbig); plan = LC.recognize(mbig, time.monotonic() + 5, bbig); fc = LC.forecast(plan, 19.0)
t0 = time.monotonic(); r_full = solve(pbig, 19.5); full_s = time.monotonic() - t0; ex = lc(r_full).get('executor') or {}
l4 = dict(model=dict(vars=len(mbig['cards']), interface_bits=plan.structure['selected']['max_interface_bits'], max_product=plan.volume['max_product_entries'], forecast=fc), full=dict(outcome=r_full['outcome'], published=r_full['published'], K=r_full['K'], route=r_full['mechanism'].get('route'), wall_s=round(full_s, 3), kernel_s=ex.get('kernel_s'), kernel_peak_logical_bytes=ex.get('kernel_peak_logical_bytes'), forward_rows=ex.get('forward_rows')))
l4['forecast_covers_kernel_peak'] = bool(ex) and fc['forecast_bytes'] >= ex['kernel_peak_logical_bytes']; l4['forecast_rows_cover'] = bool(ex) and fc['forecast_rows'] >= ex['forward_rows'] + ex['reverse_rows']
# (a) a real deadline inside the kernel: budget = 40 % of the measured kernel time, with an OPTIMISTIC injected rate so the forecast admits and the kernel's own poll must stop it
bud = max(0.15, 0.4 * (ex.get('kernel_s') or 1.0)); rate0 = LC.ROWS_PER_S_CONSERVATIVE; LC.ROWS_PER_S_CONSERVATIVE = 1e12
try: t0 = time.monotonic(); r_dl = solve(pbig, bud)
finally: LC.ROWS_PER_S_CONSERVATIVE = rate0
l4['real_deadline_inside_kernel'] = dict(budget_s=round(bud, 3), outcome=r_dl['outcome'], published=r_dl['published'], status=str(lc(r_dl).get('status'))[:90], wall_s=round(time.monotonic() - t0, 3), phases=sorted(r_dl['phases_s']), no_fallback=not any(k in r_dl['phases_s'] for k in ('integerize', 'contract', 'mb_construct')))
l4['real_deadline_inside_kernel']['ok'] = r_dl['outcome'] == 'DEADLINE' and r_dl['published'] == 0 and 'EXECUTOR_REFUSED DEADLINE' in str(lc(r_dl).get('status')) and l4['real_deadline_inside_kernel']['no_fallback']
# (c) injected byte cap: refused BEFORE the executor; the existing route gets the remaining budget (small model so it completes)
psm = gen('r20_small_cap', T=3, b=2)[0]; cap0 = IG.LAYERED_BYTE_CAP; IG.LAYERED_BYTE_CAP = 1
try: r_cap = solve(psm)
finally: IG.LAYERED_BYTE_CAP = cap0
okc, dc = check(r_cap, psm, need_route=None); l4['byte_cap_refuses_before_executor'] = dict(ok=okc and str(lc(r_cap).get('status')).startswith('RESOURCE_REFUSED') and 'executor' not in lc(r_cap) and r_cap['mechanism'].get('route') != 'layered_contraction', status=str(lc(r_cap).get('status'))[:80], **dc)
# (d) injected rate: time forecast refuses before the executor
rate0 = LC.ROWS_PER_S_CONSERVATIVE; LC.ROWS_PER_S_CONSERVATIVE = 1.0
try: r_rate = solve(psm)
finally: LC.ROWS_PER_S_CONSERVATIVE = rate0
okr, dr = check(r_rate, psm, need_route=None); l4['rate_forecast_refuses_before_executor'] = dict(ok=okr and 'forecast kernel time' in str(lc(r_rate).get('status')) and 'executor' not in lc(r_rate), status=str(lc(r_rate).get('status'))[:80], **dr)
# (e) a clock that expires right after the executor returns: DEADLINE, nothing published
orig_x = LC.execute; orig_t = LC.tnow; state = dict(done=False)
def exec_then_expire(*a, **k):
    out = orig_x(*a, **k); state['done'] = True; return out
def clock(): return orig_t() + (1000.0 if state['done'] else 0.0)
LC.execute = exec_then_expire; LC.tnow = clock; IG_t = IG.tnow; IG.tnow = clock
try: r_e = solve(psm)
finally: LC.execute = orig_x; LC.tnow = orig_t; IG.tnow = IG_t
l4['expire_after_executor'] = dict(ok=r_e['outcome'] == 'DEADLINE' and r_e['published'] == 0 and not any(k in r_e['phases_s'] for k in ('integerize', 'contract')), outcome=r_e['outcome'], published=r_e['published'], status=str(lc(r_e).get('status'))[:80])
say(dict(control='L4_bounds_on_real_work', **l4, ok=l4['forecast_covers_kernel_peak'] and l4['forecast_rows_cover'] and r_full['outcome'] == 'COMPLETE' and r_full['published'] == r_full['K'] and l4['real_deadline_inside_kernel']['ok'] and l4['byte_cap_refuses_before_executor']['ok'] and l4['rate_forecast_refuses_before_executor']['ok'] and l4['expire_after_executor']['ok']))
# ---- L5: the switch reproduces the v2.11.2 path
p0 = os.path.join(PACKET, 'theory_r20_prototype/tiny/case3.uai'); r_on = solve(p0); r_off = solve(p0, layered_contraction=False); ok_off, d_off = check(r_off, p0, need_route=None)
outp = os.path.join(TMP, 'r20_cli_off.json'); cp = subprocess.run([sys.executable, _source_path('pgm.algorithms.block.integrated'), '--input', p0, '--output', outp, '--budget', '10', '--no-layered-contraction', '--schedule', 'targeted'], capture_output=True, text=True); r_cli = json.load(open(outp))
ok_cli, d_cli = check(r_cli, p0, need_route=None)
say(dict(control='L5_switch_reproduces_v2112_path', on=dict(route=r_on['mechanism'].get('route'), status=str(lc(r_on).get('status'))[:30]), off_inprocess=dict(status=lc(r_off).get('status'), **d_off), off_cli=dict(rc=cp.returncode, status=lc(r_cli).get('status'), **d_cli), ok=r_on['mechanism'].get('route') == 'layered_contraction' and lc(r_off).get('status') == 'DISABLED' and lc(r_cli).get('status') == 'DISABLED' and ok_off and ok_cli and r_off['mechanism'].get('route') != 'layered_contraction' and cp.returncode == 0))
# ---- L6: the exposed target's structure only (no numerical solve)
m, b = core.read_uai(LINK); t0 = time.monotonic(); plan = LC.recognize(m, time.monotonic() + IG.LAYERED_RECOGNITION_S, b); rec_s = time.monotonic() - t0; st = plan.structure; vol = plan.volume
base = dict(rec_s=round(rec_s, 3), channels=st['channels'], residuals=st['residuals'], chains=st['chains'], components=st['components'], main_vars=st['main_component_variables'], free_bits=st['proposals'][0]['free_main_sign_bits'], examined=st['proposals'][0]['sign_assignments_examined'], admissible=st['proposals'][0]['admissible_candidates'], selected=st['selected'], volume=vol, order_len=len(plan.order), refusals=st['proposal_refusals'])
okb = vol['max_product_entries'] == 1 << 21 and vol['max_output_entries'] == 1 << 20 and st['selected']['max_interface_bits'] == 20 and vol['active_variables'] == 885 and len(plan.order) == 1062 and rec_s < IG.LAYERED_RECOGNITION_S and st['proposals'][0]['admissible_candidates'] == 16 and st['proposals'][0]['free_main_sign_bits'] == 5
def permute(mm, p):
    cs = [0] * len(p)
    for old, new in enumerate(p): cs[new] = mm['cards'][old]
    return dict(mm, cards=cs, factors=[{'scope': tuple(p[v] for v in f['scope']), 'values': f['values']} for f in mm['factors']])
variants = {}
n = len(m['cards']); pr_ = list(reversed(range(n))); variants['reversed_ids'] = permute(m, pr_)
pr_ = list(range(n)); random.Random(200078).shuffle(pr_); variants['random_ids'] = permute(m, pr_)
variants['channels_4_5'] = dict(m, factors=[dict(f, values=[F(1, 5) if v == F(1, 10) else F(4, 5) for v in f['values']]) if (len(f['scope']) == 2 and set(f['values']) == {F(1, 10), F(9, 10)}) else f for f in m['factors']])
vres = {}
for k, mm in variants.items():
    t0 = time.monotonic()
    try: pl = LC.recognize(mm, time.monotonic() + IG.LAYERED_RECOGNITION_S, None); vres[k] = dict(ok=pl.volume['max_product_entries'] == 1 << 21 and pl.structure['selected']['max_interface_bits'] == 20 and pl.volume['max_output_entries'] == 1 << 20, bits=pl.structure['selected']['max_interface_bits'], maxprod=pl.volume['max_product_entries'], rec_s=round(time.monotonic() - t0, 3))
    except Exception as e: vres[k] = dict(ok=False, error=repr(e)[:120])
say(dict(control='L6_exposed_target_structure_and_representation_invariance', base=base, variants=vres, ok=okb and all(v['ok'] for v in vres.values())))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
