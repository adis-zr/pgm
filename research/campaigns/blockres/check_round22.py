"""Round-22 controls (integrated v2.13, ancestral response ON): the normalized ancestral-response constructor against brute-force enumeration of the ORIGINAL model, on REAL work.
C1 the packet's 24 independent-oracle models (its generator: permuted roles / ids / axes, nonbinary alleles, hard zeros, unnormalised founders, negative rho, repeated selectors and repeated
chain positions, correlated retained allele / selector, child likelihoods) through the PRODUCTION route end to end (every coordinate and Z contained, points in the epsilon-safe J, retained
set as the oracle asserts); C2 implicit root multiplicity (no unary -> mass = cardinality) and duplicated founder unaries (exact product) vs brute force, with the opaque-factor variant retaining
the root; C3 child likelihood / evidence retention (a unary on a multiplexer child is residual; evidence on an erased candidate retains it); C4 source accounting: a duplicated multiplexer
factor refuses by type, a duplicated channel keeps its path retained, the existing route completes both; C5 negative rho (theta 1/5) and a response with two positions on one chain; C6 zero
global mass (zero founder weight -> typed refusal, existing route ZERO_EVIDENCE; a residual zeroing the mass -> executor ZERO_EVIDENCE, 0 rows); C7 source-independent relabeling (ids, axes,
factor order): same structure counts, every row contains the truth, every pair overlaps; C8 admission before allocation (query-entry cap, live-term cap, construction byte cap: typed
ResourceRefused with no executor call, the existing route completes); C9 interruption on real work (a 1 ms construction allowance on G4 refuses inside the construction; a clock expiring after
the executor -> DEADLINE with nothing published and no fallback phases; an expired deadline at decode); C10 all-original expansion on G4 (2,448 once, K preserved) and on an evidence model;
C11 operator-off dispatch (ancestral_response=False and --no-ancestral-response: DISABLED, the v2.12.1 path runs; no other flag toggles it)."""

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
from types import SimpleNamespace
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = str(_repo_root())
import pgm.algorithms.block.integrated as IG, pgm.algorithms.block.ancestral_response as AR, pgm.algorithms.block.layered_contraction as LC, pgm.algorithms.structural.core as core, research.campaigns.blockres.transfer_gen as TG
assert IG.ANCESTRAL_RESPONSE_DEFAULT is True and IG.LAYERED_CONTRACTION_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []
RD = str(_runs_root() / 'mdi_2026-10-28/BLOCKRES_2026-11-19'); G4 = RD + '/round21/inputs/G4_near_c3_theta17-20_span3.uai'
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:460], flush=True)
def write_uai(name, m):
    p = os.path.join(TMP, name + '.uai'); cards = m['cards']; lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(m['factors']))]
    for f in m['factors']: lines.append('%d %s' % (len(f['scope']), ' '.join(map(str, f['scope']))))
    for f in m['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(v) for v in f['values']))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = m.get('evidence', {}); open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
MAX_ENUM = 1 << 16
def brute(m):
    """exact enumeration of the ORIGINAL model; the loop visits every assignment (observed states included) so the bound is on ALL variables (round 22b harness guard)"""
    cards = m['cards']; ev = m.get('evidence', {}); z = F(0); num = {}
    total = math.prod(cards)
    if total > MAX_ENUM: raise AssertionError('brute-force fixture has %d assignments > %d (harness guard)' % (total, MAX_ENUM))
    for xs in itertools.product(*(range(c) for c in cards)):
        if any(xs[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in m['factors']:
            ix = 0
            for v in f['scope']: ix = ix * cards[v] + xs[v]
            w *= f['values'][ix]
            if not w: break
        if not w: continue
        z += w
        for v in range(len(cards)):
            if v not in ev: num[(v, xs[v])] = num.get((v, xs[v]), F(0)) + w
    return z, ({k: v / z for k, v in num.items()} if z else None)
def solve(p, budget=10.0, **kw):
    """AR-targeted controls disable the layered route explicitly (round 22b: the established layered route has precedence, so tiny recognisable models would otherwise take it); the dispatch controls (C11, check_round22b) use the default"""
    kw.setdefault('layered_contraction', False); return IG.solve(p, budget, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted', **kw)
def ar(r): return r['mechanism'].get('ancestral_response') or {}
def check(res, m, need_route='ancestral_response', eps=F(1, 200)):
    z, tv = brute(m); miss = 0; K = res['K']; sums = {}
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': miss += 1; continue
        lo, hi, pt = F(a['lo']), F(a['hi']), F(a['point']); t = tv.get((a['var'], a['state']), F(0)) if tv else None
        if t is None or not (lo <= t <= hi and lo <= pt <= hi and max(pt - lo, hi - pt) <= eps): miss += 1
        sums.setdefault(a['var'], []).append((lo, hi))
    ze = res.get('Z_enclosure'); zc = bool(ze) and F(ze['lo']) <= z <= F(ze['hi'])
    ok = miss == 0 and res['published'] == K and res['outcome'] in (('COMPLETE',) if need_route == 'ancestral_response' else ('COMPLETE', 'EXACT')) and all(sum(l for l, _ in v) <= 1 <= sum(h for _, h in v) for v in sums.values()) and (need_route is None or res['mechanism'].get('route') == need_route) and (need_route != 'ancestral_response' or zc)
    return ok, dict(miss=miss, published=res['published'], K=K, outcome=res['outcome'], route=res['mechanism'].get('route'), Z_contained=zc, status=str(ar(res).get('status'))[:80])
# ---- the packet's oracle generator (verbatim semantics: roles then permutations)
def factor(cards, sc, fn): return {'scope': tuple(sc), 'values': [F(fn(dict(zip(sc, x)))) for x in itertools.product(*(range(cards[v]) for v in sc))]}
Rr = random.Random(22026)
def oracle_model(case):
    names = ['A', 'B', 'C', 'D', 'E', 's0', 's1', 's2']; Rr.shuffle(names); id_ = {x: i for i, x in enumerate(names)}; card0 = 3 if case % 2 else 2; cards = [card0 if x[0] != 's' else 2 for x in names]; fs = []
    weights = {x: [F(Rr.randrange(0, 6), Rr.randrange(1, 6)) for _ in range(card0)] for x in ['A', 'B']}
    for x in weights:
        if not sum(weights[x]): weights[x][0] = F(1)
        fs.append({'scope': (id_[x],), 'values': weights[x]})
    for ch, pa, pb, se in [('C', 'A', 'B', 's0'), ('D', 'C', 'B', 's0'), ('E', 'D', 'A', 's1')]:
        sc = [id_[x] for x in (ch, pa, pb, se)]; Rr.shuffle(sc); fs.append(factor(cards, sc, lambda a, ch=id_[ch], pa=id_[pa], pb=id_[pb], se=id_[se]: int(a[ch] == a[pa if a[se] == 0 else pb])))
    fs.append({'scope': (id_['s0'],), 'values': [F(1, 2)] * 2}); theta = [F(1, 5) if case % 3 == 0 else F(4, 5), F(1, 3) if case % 3 == 1 else F(3, 4)]
    for k in range(2):
        sc = [id_['s%d' % k], id_['s%d' % (k + 1)]]; Rr.shuffle(sc); fs.append(factor(cards, sc, lambda a, k=k, sc=tuple(sc): int(a[sc[0]] == a[sc[1]]) * theta[k] + int(a[sc[0]] != a[sc[1]]) * (1 - theta[k])))
    sc = [id_['A'], id_['s2']]; Rr.shuffle(sc); lik = [F(Rr.randrange(0, 7), 7) for _ in range(card0 * 2)]
    if not any(lik): lik[0] = F(1)
    fs.append({'scope': tuple(sc), 'values': lik})
    if case % 4 == 0: fs.append({'scope': (id_['C'],), 'values': [F(1 + v, card0 + 1) for v in range(card0)]})
    Rr.shuffle(fs); return {'cards': cards, 'factors': fs, 'evidence': {}}, id_
# ---- C1
c1 = []; okall = True; nz = 0
for case in range(24):
    m, id_ = oracle_model(case); z, tv = brute(m)
    if not z: continue
    nz += 1; p = write_uai('r22_oracle_%d' % case, m); r = solve(p); ok, d = check(r, m); st = ar(r).get('structure') or {}
    retained_ok = (st.get('retained_alleles') == (3 if case % 4 == 0 else 1)); okall &= ok and retained_ok; c1.append(dict(case=case, card=m['cards'][id_['A']], ok=ok and retained_ok, retained_alleles=st.get('retained_alleles'), aux=st.get('query_auxiliaries'), **{k: d[k] for k in ('miss', 'published', 'K', 'Z_contained')}))
say(dict(control='C1_packet_oracle_models_through_production_route', models=nz, all_ok=okall, cases=c1[:6], ok=okall and nz == 24))
# ---- C2 implicit roots + duplicated founder unaries
def c2_model(opaque, dup):
    cards = [3, 3, 2, 3]; vals = [F(int(ch == (b if s else a))) for ch, a, b, s in itertools.product(range(3), range(3), range(3), range(2))]
    fs = [dict(scope=(1,), values=[F(2), F(1), F(3)]), dict(scope=(2,), values=[F(1, 2), F(1, 2)]), dict(scope=(3, 0, 1, 2), values=vals)]
    if dup: fs.append(dict(scope=(1,), values=[F(1, 2), F(2), F(1)]))                                   # a second founder unary: exact product
    if opaque: fs.append(dict(scope=(0, 2), values=[F(1, 3), F(2), F(3, 2), F(1, 4), F(2, 5), F(7, 4)]))
    return dict(cards=cards, factors=fs, evidence={})
c2 = {}
for opaque in (False, True):
    for dup in (False, True):
        m = c2_model(opaque, dup); p = write_uai('r22_root_%d%d' % (opaque, dup), m); r = solve(p); ok, d = check(r, m); st = ar(r).get('structure') or {}; z, _ = brute(m)
        pl = AR.recognize(m, time.monotonic() + 2); c2['opaque%d_dup%d' % (opaque, dup)] = dict(ok=ok and ((0 in pl.mapping) == opaque), implicit_root_retained=(0 in pl.mapping), scalar=str(pl.scalar), Z=str(z), **{k: d[k] for k in ('miss', 'published', 'K', 'Z_contained', 'route')})
say(dict(control='C2_implicit_root_multiplicity_and_duplicated_founder_unaries', cases=c2, ok=all(v['ok'] for v in c2.values())))
# ---- C3 child likelihood / evidence retention (pedigree miniature T=2)
def mini(seed, **kw):
    P = dict(T=2, N=1, Fo=2, cards=[2], theta=F(3, 4), zeros=False, span=1); P.update(kw); cs = []; fac = []; TG.pedigree(random.Random(seed), P, 0, cs, fac); return dict(cards=cs, factors=[dict(scope=sc, values=v) for sc, v in fac], evidence={})
m = mini(3); child = next(v for v, d in [(ch, 0) for ch in range(len(m['cards'])) for f in m['factors'] if len(f['scope']) == 4 and f['scope'][0] == ch] )  # first multiplexer child in scope position 0
m3a = dict(m, factors=m['factors'] + [dict(scope=(child,), values=[F(1, 3), F(2, 3)])]); pa_ = write_uai('r22_childlik', m3a); ra = solve(pa_); oka, da = check(ra, m3a); pla = AR.recognize(m3a, time.monotonic() + 2)
m3b = dict(m, evidence={child: 1}); pb_ = write_uai('r22_evid', m3b); rb = solve(pb_); okb, db = check(rb, m3b, need_route=None); plb_status = None
try: plb = AR.recognize(m3b, time.monotonic() + 2); plb_status = 'RECOGNIZED retained %d' % len(plb.retained); ev_ret = child in plb.mapping
except AR.NotApplicable as e: plb_status = 'NOT_APPLICABLE: ' + str(e)[:60]; ev_ret = None
say(dict(control='C3_child_likelihood_and_evidence_retention', child_likelihood=dict(ok=oka and child in pla.mapping, retained=child in pla.mapping, residuals=pla.structure['residual_factors'], **{k: da[k] for k in ('miss', 'published', 'K')}), evidence=dict(ok=okb and (ev_ret in (True, None)), status=plb_status, **{k: db[k] for k in ('miss', 'published', 'K', 'route')}), ok=oka and child in pla.mapping and okb and (ev_ret in (True, None))))
# ---- C4 source accounting
m = mini(5); mux = next(f for f in m['factors'] if len(f['scope']) == 4); m4a = dict(m, factors=m['factors'] + [dict(mux)]); p4a = write_uai('r22_dupmux', m4a); r4a = solve(p4a); ok4a, d4a = check(r4a, m4a, need_route=None)
chn = next(f for f in m['factors'] if len(f['scope']) == 2 and f['values'][0] == f['values'][3] and f['values'][0] + f['values'][1] == 1 and f['values'][0] != f['values'][1]); m4b = dict(m, factors=m['factors'] + [dict(chn)]); p4b = write_uai('r22_dupchan', m4b); r4b = solve(p4b); ok4b, d4b = check(r4b, m4b, need_route=None)
say(dict(control='C4_duplicate_source_accounting', dup_multiplexer=dict(ok=ok4a and str(ar(r4a).get('status')).startswith('NOT_APPLICABLE'), **d4a), dup_channel=dict(ok=ok4b, **d4b), ok=ok4a and str(ar(r4a).get('status')).startswith('NOT_APPLICABLE') and ok4b))
# ---- C5 negative rho + repeated chain positions (the oracle's D reuses s0; theta 1/5 cases) -- a dedicated pedigree with theta 1/5 and a two-locus anchor
m5 = mini(11, T=2, theta=F(1, 5)); p5 = write_uai('r22_negrho', m5); r5 = solve(p5); ok5, d5 = check(r5, m5); pl5 = AR.recognize(m5, time.monotonic() + 2)
neg = sum(1 for s, (b, rho) in pl5.selector_transport.items() if rho < 0)
m5b = mini(12, T=3, theta=F(1, 5), span=2); p5b = write_uai('r22_negrho3', m5b); r5on = solve(p5b); r5off = solve(p5b, ancestral_response=False)             # no brute force (24 variables): the accepted v2.12.1 arm is the reference
k_on = {(a['var'], a['state']): a for a in r5on['answers']}; k_off = {(a['var'], a['state']): a for a in r5off['answers'] if a['guarantee'] != 'NOT_PUBLISHED'}
ov5 = r5on['published'] == r5on['K'] and r5off['published'] == r5off['K'] and all(not (F(k_on[k]['hi']) < F(v['lo']) or F(v['hi']) < F(k_on[k]['lo'])) for k, v in k_off.items())
pl5b = AR.recognize(m5b, time.monotonic() + 2); multi = sum(1 for pp in pl5b.decoder.values() for poly in pp for key in poly if len(key[2]) >= 2)
say(dict(control='C5_negative_rho_and_repeated_chain_positions', T2=dict(negative_rho_transports=neg, removed_selectors=len(pl5.removed_selectors), **d5), T3_vs_accepted_arm=dict(overlap_every_coordinate=ov5, on=(r5on['outcome'], r5on['mechanism'].get('route'), r5on['published']), off=(r5off['outcome'], r5off['mechanism'].get('route'), r5off['published']), removed_selectors=len(pl5b.removed_selectors), negative_rho=sum(1 for s, (b, rho) in pl5b.selector_transport.items() if rho < 0), multi_selector_terms=multi), ok=ok5 and neg > 0 and ov5))
# ---- C6 zero mass: under default dispatch the closure establishes exact zero evidence BEFORE the ancestral route is reached (0 rows); the constructor's own typed ZeroMass refusal is tested directly
m6a = c2_model(False, False); m6a['factors'][0] = dict(scope=(1,), values=[F(0), F(0), F(0)]); p6a = write_uai('r22_zero_founder', m6a); r6a = solve(p6a)
try: AR.recognize(m6a, time.monotonic() + 2); zm = 'RETURNED'
except AR.ZeroMass as e: zm = 'ZeroMass: ' + str(e)[:50]
m6b = mini(7); m6b['factors'].append(dict(scope=(0, 1), values=[F(0)] * (m6b['cards'][0] * m6b['cards'][1]))); p6b = write_uai('r22_zero_resid', m6b); r6b = solve(p6b)
r6c = solve(p6b, support_closure=False)                                                                       # closure off: the executor's own ZERO_EVIDENCE (or the fallback's) must still publish nothing
say(dict(control='C6_zero_global_mass', zero_founder=dict(dispatch_outcome=r6a['outcome'], published=r6a['published'], constructor_direct=zm), zero_residual=dict(dispatch_outcome=r6b['outcome'], published=r6b['published'], closure_off=dict(outcome=r6c['outcome'], published=r6c['published'], ar_status=str(ar(r6c).get('status'))[:40])), ok=(r6a['outcome'] == 'ZERO_EVIDENCE' and r6a['published'] == 0 and zm.startswith('ZeroMass') and r6b['outcome'] == 'ZERO_EVIDENCE' and r6b['published'] == 0 and r6c['outcome'] == 'ZERO_EVIDENCE' and r6c['published'] == 0)))
# ---- C7 relabeling
m7 = mini(13, T=2, cards=[2]); rng = random.Random(77); n = len(m7['cards']); pi = list(range(n)); rng.shuffle(pi); cards2 = [0] * n
for v in range(n): cards2[pi[v]] = m7['cards'][v]
nf = []
for f in reversed(m7['factors']):
    sc = list(f['scope']); ps = list(range(len(sc))); rng.shuffle(ps); ns = [sc[j] for j in ps]; vs = []
    for xx in itertools.product(*(range(m7['cards'][v]) for v in ns)):
        env = dict(zip(ns, xx)); ix = 0
        for v in sc: ix = ix * m7['cards'][v] + env[v]
        vs.append(f['values'][ix])
    nf.append(dict(scope=tuple(pi[v] for v in ns), values=vs))
m7p = dict(cards=cards2, factors=nf, evidence={}); p7 = write_uai('r22_relabel_a', m7); p7p = write_uai('r22_relabel_b', m7p); r7 = solve(p7); r7p = solve(p7p); ok7, d7 = check(r7, m7); ok7p, d7p = check(r7p, m7p)
a1 = {(a['var'], a['state']): a for a in r7['answers']}; a2 = {(pi.index(a['var']), a['state']): a for a in r7p['answers']}
overlap = set(a1) == set(a2) and all(not (F(a1[k]['hi']) < F(a2[k]['lo']) or F(a2[k]['hi']) < F(a1[k]['lo'])) for k in a1); s1 = ar(r7)['structure']; s2 = ar(r7p)['structure']
same = all(s1[k] == s2[k] for k in ('retained_original_variables', 'removed_alleles', 'removed_selectors', 'query_auxiliaries', 'removed_founders'))
say(dict(control='C7_source_independent_relabeling', same_structure_counts=same, overlap_every_coordinate=overlap, a=d7, b=d7p, ok=ok7 and ok7p and same and overlap))
# ---- C8 admission before allocation (G4 as the real workload; caps injected)
mG, bG = core.read_uai(G4); c8 = {}
for name, kw in (('query_entry_cap', dict(max_query_entries=100)), ('live_term_cap', dict(max_live_terms=50)), ('byte_cap', dict(byte_limit=1000))):
    t0 = time.monotonic()
    try: AR.recognize(mG, time.monotonic() + 5, bG, **kw); oc = 'RETURNED'
    except AR.ResourceRefused as e: oc = 'ResourceRefused: ' + str(e)[:70]
    c8[name] = dict(outcome=oc, elapsed_s=round(time.monotonic() - t0, 3), ok=oc.startswith('ResourceRefused'))
m8 = mini(17); p8 = write_uai('r22_small_cap', m8); cap0 = IG.ANCESTRAL_BYTE_CAP; IG.ANCESTRAL_BYTE_CAP = 1
try: r8 = solve(p8)
finally: IG.ANCESTRAL_BYTE_CAP = cap0
ok8, d8 = check(r8, m8, need_route=None); c8['integrated_byte_cap'] = dict(ok=ok8 and str(ar(r8).get('status')).startswith('RESOURCE_REFUSED') and 'executor' not in ar(r8), **d8)
say(dict(control='C8_admission_before_allocation', cases=c8, ok=all(v['ok'] for v in c8.values())))
# ---- C9 interruption on real work
t0 = time.monotonic()
try: AR.recognize(mG, math.inf, bG, construction_s=0.001); oc9 = 'RETURNED'
except AR.RecognitionRefused as e: oc9 = 'RecognitionRefused: ' + str(e)[:70]
el9 = time.monotonic() - t0
orig_x = LC.execute; orig_t = AR.tnow; state = dict(done=False)
def exec_then_expire(*a, **k):
    out = orig_x(*a, **k); state['done'] = True; return out
def clock(): return orig_t() + (1000.0 if state['done'] else 0.0)
LC.execute = exec_then_expire; AR.tnow = clock; IG_t = IG.tnow; IG.tnow = clock
try: r9 = solve(G4, 19.5)
finally: LC.execute = orig_x; AR.tnow = orig_t; IG.tnow = IG_t
plan9 = AR.recognize(mG, time.monotonic() + 5, bG); R9 = LC.execute(plan9, plan9.aug, time.monotonic() + 10, 1 << 30, 0); dec_exp = None
try: AR.decode(plan9, R9, F(1, 200), deadline=-math.inf)
except AR.DeadlineRefused as e: dec_exp = str(e)[:60]
say(dict(control='C9_interruption_on_real_work', construction_1ms=dict(outcome=oc9, elapsed_s=round(el9, 4), ok=oc9.startswith('RecognitionRefused') and el9 < 0.1), expire_after_executor=dict(outcome=r9['outcome'], published=r9['published'], status=str(ar(r9).get('status'))[:70], no_fallback=not any(k in r9['phases_s'] for k in ('integerize', 'contract', 'mb_construct')), ok=r9['outcome'] == 'DEADLINE' and r9['published'] == 0), decode_expired=dict(outcome=dec_exp, ok=dec_exp is not None), ok=oc9.startswith('RecognitionRefused') and el9 < 0.1 and r9['outcome'] == 'DEADLINE' and r9['published'] == 0 and not any(k in r9['phases_s'] for k in ('integerize', 'contract')) and dec_exp is not None))
# ---- C10 all-original expansion
r10 = solve(G4, 19.5); keys = [(a['var'], a['state']) for a in r10['answers']]; exp = [(v, s) for v in range(len(mG['cards'])) for s in range(mG['cards'][v])]
m10 = mini(19, T=2); ev_var = [v for v in range(len(m10['cards'])) if m10['cards'][v] == 2 and all(v not in f['scope'] or len(f['scope']) != 4 or f['scope'][0] != v for f in m10['factors'])][-1]; m10['evidence'] = {ev_var: 1}; p10 = write_uai('r22_allorig_ev', m10); r10b = solve(p10); ok10b, d10b = check(r10b, m10, need_route=None)
say(dict(control='C10_all_original_expansion', G4=dict(published=r10['published'], K=r10['K'], keys_once_in_order=(keys == exp), outcome=r10['outcome'], exact_rows=ar(r10).get('exact_rows'), policies=ar(r10).get('point_policies')), evidence_model=dict(evidence=m10['evidence'], **d10b, excluded_observed=all(a['var'] != ev_var for a in r10b['answers'])), ok=(keys == exp and r10['published'] == 2448 and ok10b and all(a['var'] != ev_var for a in r10b['answers']))))
# ---- C11 operator-off dispatch
m11 = mini(23, T=2); p11 = write_uai('r22_switch', m11); r_on = solve(p11); r_off = solve(p11, ancestral_response=False); ok_off, d_off = check(r_off, m11, need_route=None); r_def = solve(p11, layered_contraction=True); ok_def, d_def = check(r_def, m11, need_route=None)
outp = os.path.join(TMP, 'r22_cli_off.json'); cp = subprocess.run([sys.executable, _source_path('pgm.algorithms.block.integrated'), '--input', p11, '--output', outp, '--budget', '10', '--no-ancestral-response', '--no-layered-contraction', '--schedule', 'targeted'], capture_output=True, text=True); r_cli = json.load(open(outp)); ok_cli, d_cli = check(r_cli, m11, need_route=None)
r_nl = solve(p11, layered_contraction=False)
say(dict(control='C11_operator_off_dispatch', on_lc_off=dict(route=r_on['mechanism'].get('route'), status=str(ar(r_on).get('status'))[:20]), default_dispatch=dict(dispatch_route=r_def['mechanism'].get('route'), ar_status=str(ar(r_def).get('status'))[:40], **d_def), off_inprocess=dict(ar_status=ar(r_off).get('status'), layered=str(r_off['mechanism']['layered_contraction'].get('status'))[:30], **d_off), off_cli=dict(rc=cp.returncode, ar_status=ar(r_cli).get('status'), **d_cli), ok=r_on['mechanism'].get('route') == 'ancestral_response' and ar(r_off).get('status') == 'DISABLED' and ar(r_cli).get('status') == 'DISABLED' and ok_off and ok_cli and ok_def and cp.returncode == 0 and r_def['mechanism'].get('route') == 'layered_contraction' and str(ar(r_def).get('status')).startswith('DEFERRED')))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
