"""Round-19 controls (integrated v2.11, evidence expansion ON): the SPEC section-9 boundaries, every one against brute-force enumeration of the ORIGINAL model and over the original
denominator. T1 the three supplied tiny networks end to end (all original answers contained, Z exact, closure-enabled dispatch); T2 a recognised model whose closure is nonidentity
with a NONUNIT scalar: the expansion still returns the original Z and each original answer once (no double decoder / scalar); T3 recognised exact zero evidence: no normalised rows
(closure disabled -> the signed executor's own Znum = 0 branch; closure enabled -> dispatch) and a valid UNSUPPORTED model falls back instead of being reported zero; T4 near-match
table violating the product identity, internal branching (shared accumulator), negative / internal evidence: typed refusal + correct fallback; T5 interrupted recognition, projected
resource refusal, deadline inside evaluation: no signed-prefix answers, fallback honours the contract; T6 factor-list permutation and variable renumbering give equivalent answers;
an unsupported axis layout refuses safely; T7 both switches and explicit PAC / force-approx / construct-only reach their intended mechanisms."""
import sys, os, json, random, time, math, itertools
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import integrated as IG, signed_evidence as SE, core
assert IG.EVIDENCE_EXPANSION_DEFAULT is True and IG.SUPPORT_CLOSURE_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []; rng = random.Random(1901)
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def brute(p):
    """exact Z and per-coordinate truth by enumeration of the ORIGINAL model (None if Z = 0)"""
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
    return (z, {k: v / z for k, v in num.items()}) if z else (F(0), None)
def contained(res, p):
    z, tv = brute(p); n = 0; miss = []; K = res['K']
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = (tv or {}).get((a['var'], a['state']), F(0)); lo, hi = F(a['lo']), F(a['hi'])
        if not (F(0) <= lo <= hi <= 1) or not (lo <= tr <= hi): miss.append((a['var'], a['state'], str(lo), str(hi), str(tr)))
    return n, miss, z
def ee(res): return (res['mechanism'] or {}).get('evidence_expansion') or {}
def noisy(cards_n, roots, specs, name):
    """build a family model from (roots priors, chain specs [(root list, thetas, leak)]) with the packet's layout; returns (path, observed)"""
    factors = []; nextvar = len(roots); obs = []
    for r, pr in enumerate(roots): factors.append(((r,), [1 - pr, pr]))
    for rs, theta, leak in specs:
        a, b = rs[:2]; v = nextvar; nextvar += 1; neg = [theta[0] ** x * theta[1] ** y for x, y in itertools.product([0, 1], repeat=2)]
        factors.append(((v, a, b), neg + [1 - q for q in neg]))
        for r, t in zip(rs[2:], theta[2:]):
            prev = v; v = nextvar; nextvar += 1; neg = [t ** x * F(0) ** y for x, y in itertools.product([0, 1], repeat=2)]; factors.append(((v, r, prev), neg + [1 - q for q in neg]))
        y = nextvar; nextvar += 1; factors.append(((y, v), [leak, 0, 1 - leak, 1])); obs.append(y)
    return write_uai(name, [2] * nextvar, factors, {y: 1 for y in obs}), obs, factors
KW = dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False)
# ---- T1: the three supplied fixtures end to end
for k in range(3):
    p = os.path.join(TMP, 'tiny_noisy_or_%d.uai' % k); r = IG.solve(p, 6.0, **KW); n, miss, z = contained(r, p); e = ee(r)
    say(dict(control='T1_supplied_fixture_%d_end_to_end' % k, outcome=r['outcome'], guarantee=r.get('guarantee'), route=r['mechanism'].get('route'), expansion=e.get('status'), subsets=e.get('subsets'), published=n, K=r['K'], misses=len(miss), Z_equal=(F(r.get('Z', 0)) == z), ok=(e.get('status') == 'APPLIED' and r['mechanism'].get('route') == 'signed_evidence_expansion' and not miss and n == r['K'] and F(r['Z']) == z)))
# ---- T2: nonidentity closure with a NONUNIT scalar on a recognised model: root 0 has prior (0, 1) (fixed to 1) and a terminal directly on it with b < a, so closure turns that
#      terminal into a constant (1 - b) scalar; chain 2 carries the queries. The expansion must return the ORIGINAL Z (brute force), each coordinate once.
roots2 = [F(1), F(1, 3), F(2, 5)]; factors2 = [((r,), [1 - pr, pr]) for r, pr in enumerate(roots2)]
factors2.append(((3, 0), [F(9, 10), F(9, 10) * F(2, 5), F(1, 10), 1 - F(9, 10) * F(2, 5)]))                       # terminal y=3 on root 0: a = 9/10, b = a * 2/5
neg = [F(1, 2) ** x * F(3, 7) ** y for x, y in itertools.product([0, 1], repeat=2)]; factors2.append(((4, 1, 2), neg + [1 - q for q in neg]))
neg = [F(2, 9) ** x * F(0) ** y for x, y in itertools.product([0, 1], repeat=2)]; factors2.append(((5, 1, 4), neg + [1 - q for q in neg]))
factors2.append(((6, 5), [F(4, 5), 0, F(1, 5), 1])); p2 = write_uai('r19_t2_scalar', [2] * 7, factors2, {3: 1, 6: 1})
cl = IG.SC.compile_closure(core.read_uai(p2)[0], math.inf, 1 << 30); r = IG.solve(p2, 6.0, **KW); n, miss, z = contained(r, p2); e = ee(r)
seen = [(a['var'], a['state']) for a in r['answers']]
say(dict(control='T2_nonidentity_closure_nonunit_scalar_original_Z_once', closure_scalar=str(cl['scalar']), closure_identity=cl['identity'], closure_reps=cl['stats']['representatives'], outcome=r['outcome'], expansion=e.get('status'), Z_candidate=str(r.get('Z'))[:30], Z_brute=str(z)[:30], published=n, K=r['K'], each_once=(len(seen) == len(set(seen)) == r['K']), misses=len(miss), ok=(cl['scalar'] != 1 and not cl['identity'] and e.get('status') == 'APPLIED' and F(r['Z']) == z and not miss and n == r['K'] and len(seen) == len(set(seen)) == r['K'])))
# ---- T3: recognised exact zero evidence (root prior 0, terminal a = 1 and b = 1 -> y = 1 impossible); closure OFF exercises the executor's Znum = 0 branch; closure ON the dispatch
factors3 = [((0,), [1, 0]), ((1,), [F(1, 2), F(1, 2)]), ((2, 0), [1, 1, 0, 0]), ((3, 1), [F(1, 2), 0, F(1, 2), 1])]; p3 = write_uai('r19_t3_zero', [2] * 4, factors3, {2: 1, 3: 1})
z3, _ = brute(p3); r_off = IG.solve(p3, 6.0, support_closure=False, **KW); r_on = IG.solve(p3, 6.0, **KW)
say(dict(control='T3a_recognised_exact_zero_evidence_no_rows', brute_Z=str(z3), off=dict(outcome=r_off['outcome'], expansion=str(ee(r_off).get('status'))[:40], published=r_off['published']), on=dict(outcome=r_on['outcome'], published=r_on['published'], closure=str((r_on['mechanism'].get('support_closure') or {}).get('status'))[:30]), ok=(z3 == 0 and r_off['outcome'] == 'ZERO_EVIDENCE' and r_off['published'] == 0 and str(ee(r_off).get('status', '')).startswith('ZERO_EVIDENCE') and r_on['outcome'] == 'ZERO_EVIDENCE' and r_on['published'] == 0)))
p3b = write_uai('r19_t3_unsupported_positive', [3, 2], [((0, 1), [1, 2, 3, 4, 5, 6])]); r = IG.solve(p3b, 6.0, **KW); n, miss, z = contained(r, p3b)
say(dict(control='T3b_valid_unsupported_model_falls_back_not_zero', outcome=r['outcome'], expansion=str(ee(r).get('status'))[:50], published=n, K=r['K'], misses=len(miss), brute_Z=str(z), ok=(str(ee(r).get('status', '')).startswith('NOT_APPLICABLE') and r['outcome'] != 'ZERO_EVIDENCE' and not miss and n == r['K'])))
# ---- T4: typed refusals with correct fallback: (a) near-match gate violating the product identity (normalised), (b) shared accumulator, (c) internal evidence value 0
base_roots = [F(1, 5), F(1, 4)]; base_specs = [([0, 1], [F(1, 3), F(2, 5)], F(9, 10))]
p4a, obs, facs = noisy(None, base_roots, base_specs, 'r19_t4a'); facs = list(facs); sc, vals = facs[2]; vals = list(vals); vals[3] = vals[3] + F(1, 50); vals[7] = 1 - vals[3]; facs[2] = (sc, vals)
p4a = write_uai('r19_t4a_nearmatch', [2] * 4, facs, {3: 1}); r = IG.solve(p4a, 6.0, **KW); n, miss, z = contained(r, p4a)
say(dict(control='T4a_near_match_violating_product_identity_refused_fallback', expansion=str(ee(r).get('status'))[:70], outcome=r['outcome'], published=n, K=r['K'], misses=len(miss), ok=(str(ee(r).get('status', '')).startswith('NOT_APPLICABLE') and not miss and n == r['K'])))
facs4b = [((0,), [F(4, 5), F(1, 5)]), ((1,), [F(3, 4), F(1, 4)])]; neg = [F(1, 3) ** x * F(2, 5) ** y for x, y in itertools.product([0, 1], repeat=2)]; facs4b.append(((2, 0, 1), neg + [1 - q for q in neg]))
facs4b += [((3, 2), [F(9, 10), 0, F(1, 10), 1]), ((4, 2), [F(4, 5), 0, F(1, 5), 1])]                      # accumulator 2 consumed by two terminals
p4b = write_uai('r19_t4b_shared_acc', [2] * 5, facs4b, {3: 1, 4: 1}); r = IG.solve(p4b, 6.0, **KW); n, miss, z = contained(r, p4b)
say(dict(control='T4b_shared_accumulator_refused_fallback', expansion=str(ee(r).get('status'))[:70], outcome=r['outcome'], published=n, K=r['K'], misses=len(miss), ok=(str(ee(r).get('status', '')).startswith('NOT_APPLICABLE') and not miss and n == r['K'])))
p4c, obs, facs = noisy(None, base_roots, base_specs, 'r19_t4c'); p4c = write_uai('r19_t4c_negative_evidence', [2] * 4, facs, {3: 0}); r = IG.solve(p4c, 6.0, **KW); n, miss, z = contained(r, p4c)
say(dict(control='T4c_negative_evidence_refused_fallback', expansion=str(ee(r).get('status'))[:70], outcome=r['outcome'], published=n, K=r['K'], misses=len(miss), ok=(str(ee(r).get('status', '')).startswith('NOT_APPLICABLE') and not miss and n == r['K'])))
# ---- T5: interrupted recognition (1 ns allowance), projected resource refusal (budget 0), deadline inside evaluation (clock jumps after recognition): fallback, contained, no signed rows
p5 = os.path.join(TMP, 'tiny_noisy_or_0.uai'); saved = IG.EVIDENCE_RECOGNITION_S; IG.EVIDENCE_RECOGNITION_S = 1e-9
try: r = IG.solve(p5, 6.0, **KW)
finally: IG.EVIDENCE_RECOGNITION_S = saved
n, miss, z = contained(r, p5); s5a = str(ee(r).get('status', ''))
saved = IG.EVIDENCE_WORKSPACE_BUDGET; IG.EVIDENCE_WORKSPACE_BUDGET = 0
try: r2 = IG.solve(p5, 6.0, **KW)
finally: IG.EVIDENCE_WORKSPACE_BUDGET = saved
n2, miss2, _ = contained(r2, p5); s5b = str(ee(r2).get('status', ''))
# (c1) the executor's own poll: an expired deadline at entry to execute() raises DeadlineRefused before any subset work
model5, b5 = core.read_uai(p5); plan5 = SE.recognize(model5, [(x, v) for x in range(len(model5['cards'])) if x not in model5['evidence'] for v in range(2)], b5, math.inf); raised = None
try: SE.execute(plan5, -math.inf, 1 << 30)
except SE.DeadlineRefused as e: raised = str(e)[:40]
# (c2) the solve-level contract: a DeadlineRefused from the executor falls back to the existing route with the remaining budget, contained, no signed rows
orig_x = SE.execute
def refusing(*a, **k): raise SE.DeadlineRefused('injected deadline inside evaluation')
SE.execute = refusing
try: r3 = IG.solve(p5, 6.0, **KW)
finally: SE.execute = orig_x
n3, miss3, _ = contained(r3, p5); s5c = str(ee(r3).get('status', '')); s5c_direct = raised
say(dict(control='T5_interrupted_recognition_resource_refusal_deadline_fallback', recognition=dict(status=s5a[:40], outcome=r['outcome'], published=n, K=r['K'], misses=len(miss)), resource=dict(status=s5b[:40], outcome=r2['outcome'], published=n2, misses=len(miss2)), deadline=dict(executor_poll=s5c_direct, status=s5c[:40], outcome=r3['outcome'], published=n3, misses=len(miss3), route=r3['mechanism'].get('route')), ok=(s5a.startswith('RECOGNITION_REFUSED') and s5b.startswith('RESOURCE_REFUSED') and ((s5c_direct or '').startswith('deadline inside the subset sum') or (s5c_direct or '').startswith('deadline already passed at entry')) and s5c.startswith('DEADLINE_REFUSED') and not miss and not miss2 and not miss3 and n == r['K'] and n2 == r2['K'] and n3 == r3['K'] and r3['mechanism'].get('route') != 'signed_evidence_expansion')))
# ---- T6: factor-list permutation and variable renumbering of fixture 1 -> equivalent answers; an unsupported axis layout (gate scope (root, child, prev)) refuses safely
model6, _ = core.read_uai(os.path.join(TMP, 'tiny_noisy_or_1.uai')); n6 = len(model6['cards']); perm = list(range(n6)); rng.shuffle(perm)       # perm[old] = new
facs6 = [(tuple(perm[v] for v in f['scope']), list(f['values'])) for f in model6['factors']]; rng.shuffle(facs6); ev6 = {perm[v]: a for v, a in model6['evidence'].items()}
p6 = write_uai('r19_t6_renumbered', [2] * n6, facs6, ev6); r6 = IG.solve(p6, 6.0, **KW); r6o = IG.solve(os.path.join(TMP, 'tiny_noisy_or_1.uai'), 6.0, **KW)
m6 = {(perm[a['var']], a['state']): (a['lo'], a['hi']) for a in r6o['answers']}; same = all(m6[(a['var'], a['state'])] == (a['lo'], a['hi']) for a in r6['answers'])
f7 = [(tuple(f['scope']), list(f['values'])) for f in model6['factors']]; i7 = next(i for i, (sc, _) in enumerate(f7) if len(sc) == 3); sc, vals = f7[i7]
import numpy as np
arr = np.array(vals, dtype=object).reshape(2, 2, 2); f7[i7] = ((sc[1], sc[0], sc[2]), list(np.transpose(arr, (1, 0, 2)).reshape(-1)))      # same function, axes permuted: outside the declared layout
p7 = write_uai('r19_t6_axis_layout', [2] * n6, f7, model6['evidence']); r7 = IG.solve(p7, 6.0, **KW); n7, miss7, _ = contained(r7, p7)
say(dict(control='T6_permutation_renumbering_equivalent_and_axis_layout_refuses', renumbered=dict(expansion=ee(r6).get('status'), Z_equal=(F(r6['Z']) == F(r6o['Z'])), answers_equivalent=same), axis_layout=dict(expansion=str(ee(r7).get('status'))[:60], outcome=r7['outcome'], published=n7, K=r7['K'], misses=len(miss7)), ok=(ee(r6).get('status') == 'APPLIED' and F(r6['Z']) == F(r6o['Z']) and same and str(ee(r7).get('status', '')).startswith('NOT_APPLICABLE') and not miss7 and n7 == r7['K'])))
# ---- T7: switches and explicit controls reach their intended mechanisms
p = os.path.join(TMP, 'tiny_noisy_or_0.uai'); ra = IG.solve(p, 6.0, evidence_expansion=False, **KW); rb = IG.solve(p, 6.0, evidence_expansion=False, support_closure=False, **KW)
rc = IG.solve(p, 8.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='pac', schedule='targeted', crosscheck=False); pcq = write_uai('r19_t7_clique', [2] * 6, [((i, j), [rng.randint(1, 9) for _ in range(4)]) for i in range(6) for j in range(i + 1, 6)])          # a positive clique: nothing to close, uncontractible at table_cap 2 -> reaches construct-only
rd = IG.solve(pcq, 6.0, construct_only=True, force_approx=True, table_cap=1 << 1, enum_cap=1 << 4, mb_cap=1 << 12)
na, missa, _ = contained(ra, p); nb, missb, _ = contained(rb, p); nc, missc, _ = contained(rc, p)
say(dict(control='T7_switches_and_explicit_controls_reach_intended_mechanisms', no_expansion=dict(expansion=ee(ra).get('status'), closure=(ra['mechanism'].get('support_closure') or {}).get('status'), route=ra['mechanism'].get('route'), misses=len(missa), complete=(na == ra['K'])), both_off=dict(expansion=ee(rb).get('status'), closure=(rb['mechanism'].get('support_closure') or {}).get('status'), misses=len(missb), complete=(nb == rb['K'])), force_approx=dict(expansion=str(ee(rc).get('status'))[:30], route=rc['mechanism'].get('route'), misses=len(missc), complete=(nc == rc['K'])), construct_only=dict(expansion=str(ee(rd).get('status'))[:30], outcome=rd['outcome']), ok=(ee(ra).get('status') == 'DISABLED' and ra['mechanism'].get('route') != 'signed_evidence_expansion' and not missa and na == ra['K'] and ee(rb).get('status') == 'DISABLED' and (rb['mechanism'].get('support_closure') or {}).get('status') == 'DISABLED' and not missb and nb == rb['K'] and str(ee(rc).get('status', '')).startswith('SKIPPED') and rc['mechanism'].get('route') != 'signed_evidence_expansion' and not missc and str(ee(rd).get('status', '')).startswith('SKIPPED') and rd['outcome'] == 'CONSTRUCT_ONLY')))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
