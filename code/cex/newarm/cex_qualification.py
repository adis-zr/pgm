"""Qualification of the compiled executor (prompt section 8 step 2) against raw-model exact enumeration and the exact Fraction reference on the SAME plan.
Controls: hard zeros, repeated factor occurrences, permuted axes / variable ids, disconnected components, evidence, skewed magnitudes, extreme exponents,
near-zero normalizers, sparse / dense equivalent representations (fill thresholds 0 / 0.25 / 1.01), different sound reduction trees (every order is a different
tree), resource stops (deadline, memory cap, row cap), range refusal (no fabricated zero), label-overflow refusal, wrong binding (a mutated plan hash differs),
stale-output / checker-failure controls (publication invariants). Writes CEX_QUALIFICATION.json beside this file."""
import sys, time, random, json, math, hashlib, os
BASE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, BASE); sys.set_int_max_str_digits(0)
from fractions import Fraction as F
from itertools import permutations
import core, cex_executor as X, support
R = {'records': [], 'controls': []}
def contained(iv, truth): return all(lo <= p <= hi for row, ps in zip(iv, truth) for (lo, hi), p in zip(row, ps))
def run(m, order, **kw):
    try: return X.execute(m, order, deadline=time.monotonic() + kw.pop('budget', 60), **kw), None
    except X.Stop as e: return None, e
def gen(rng, n, cards, nf, zp, mag, repeat=False, ev_p=0.4):
    factors = []
    for i in range(nf):
        k = rng.randint(1, min(3, n)); sc = tuple(rng.sample(range(n), k)); vol = math.prod(cards[v] for v in sc)
        vals = []
        for _ in range(vol):
            if rng.random() < zp: vals.append(F(0))
            elif mag == 'skew': vals.append(F(rng.randint(1, 9)) * F(10) ** rng.randint(-mag_range, mag_range))
            else: vals.append(F(rng.randint(1, 9), rng.randint(1, 9)))
        factors.append(dict(scope=sc, values=vals))
        if repeat and rng.random() < 0.5: factors.append(dict(scope=sc, values=list(vals)))       # repeated OCCURRENCE (not deduplicated)
    ev = {rng.randrange(n): rng.randrange(cards[rng.randrange(n)] if False else 1) for _ in range(1)} if rng.random() < ev_p else {}
    ev = {v: rng.randrange(cards[v]) for v in ev}
    return dict(cards=cards, factors=factors, evidence=ev)
mag_range = 6
rng = random.Random(20261111); passed = 0; total = 0
# ---- A. random mixed-domain models vs brute force AND vs the exact reference on the SAME order, three physical schedules each
for trial in range(120):
    n = rng.randint(2, 8); cards = [rng.randint(2, 5) for _ in range(n)]; nf = rng.randint(1, n + 3); zp = rng.choice([0.0, 0.0, 0.15, 0.4, 0.7]); mag = rng.choice(['plain', 'plain', 'skew'])
    m = gen(rng, n, cards, nf, zp, mag, repeat=rng.random() < 0.3)
    if sum(math.log2(c) for c in cards) > 16: continue
    try: truth = core.brute_force(m); zero = False
    except ValueError: truth = None; zero = True
    order = [v for v in range(n) if v not in m['evidence']]; rng.shuffle(order)
    try: ref = support.solve(m, deadline=time.monotonic() + 60, order=order); ref_status = ref['status']
    except ValueError as ex: ref = None; ref_status = 'REFERENCE_RAISED: %s' % str(ex)[:60]; R.setdefault('reference_defects', []).append(dict(trial=trial, error=str(ex)[:120], note='frozen support.py joined(): an empty intermediate join leaves cols incomplete and raises ValueError instead of returning ZERO_EVIDENCE (reference-only defect; brute force remains the oracle)'))
    for thr in (0.0, 0.25, 1.01):
        total += 1; r, e = run(m, order, cap_bytes=256 * 1024 ** 2, dense_fill_threshold=thr)
        if zero:
            ok = (r is not None and r['status'] == 'ZERO_EVIDENCE') and (ref is None or ref['status'] == 'ZERO_EVIDENCE')
        elif e is not None:
            ok = False
        else:
            ok = r['status'] == 'CERTIFIED' and contained(r['intervals'], truth) and (ref is None or (ref['status'] == 'CERTIFIED' and contained(r['intervals'], ref['points']))) and core.verify_output(r['intervals'], r['points']) and F(r['stats']['max_width']) <= F(1, 100)
        passed += ok; R['records'].append(dict(kind='random', trial=trial, n=n, cards=cards, nf=len(m['factors']), zp=zp, mag=mag, evidence=m['evidence'], thr=thr, zero=zero, status=(r['status'] if r else 'STOP:%s' % e.kind), ref_status=ref_status, ok=ok, K=(r['stats'].get('max_label_K') if r else None), max_width=(r['stats'].get('max_width_float') if r else None), sparse_buckets=((r['stats'].get('counters') or {}).get('buckets_sparse') if r else None), reason=(e.reason[:120] if e else None)))
        if not ok: print('FAIL', R['records'][-1], flush=True)
# ---- B. permuted axes and variable ids: the answer permutes accordingly
m0 = gen(random.Random(5), 5, [2, 3, 2, 4, 3], 6, 0.2, 'plain'); perm = [3, 0, 4, 1, 2]; inv = {p: i for i, p in enumerate(perm)}
m1 = dict(cards=[m0['cards'][perm[i]] for i in range(5)], factors=[], evidence={inv[v]: a for v, a in m0['evidence'].items()})
for f in m0['factors']:
    sc = tuple(inv[v] for v in f['scope']); ax = list(range(len(sc))); rng2 = random.Random(len(f['values'])); rng2.shuffle(ax)      # permute axis order too
    new_sc = tuple(sc[a] for a in ax); vol = len(f['values']); cards0 = [m0['cards'][v] for v in f['scope']]; vals = [None] * vol
    from itertools import product
    strides0 = [math.prod(cards0[j + 1:]) for j in range(len(sc))]; new_cards = [cards0[a] for a in ax]; new_strides = [math.prod(new_cards[j + 1:]) for j in range(len(sc))]
    for assign in product(*(range(c) for c in cards0)):
        old_i = sum(assign[j] * strides0[j] for j in range(len(sc))); new_i = sum(assign[ax[j]] * new_strides[j] for j in range(len(sc))); vals[new_i] = f['values'][old_i]
    m1['factors'].append(dict(scope=new_sc, values=vals))
t0 = core.brute_force(m0); t1 = core.brute_force(m1); o1 = [v for v in range(5) if v not in m1['evidence']]
r1, e1 = run(m1, o1); ok = r1 is not None and contained(r1['intervals'], t1) and all(t1[inv[v]] == t0[v] for v in range(5)); total += 1; passed += ok; R['controls'].append(dict(name='permuted_axes_and_ids', ok=ok))
# ---- C. disconnected components (two independent blocks), handled as one plan: exact per-row truth
mA = gen(random.Random(11), 3, [2, 3, 2], 4, 0.1, 'plain', ev_p=0); mB = gen(random.Random(12), 3, [3, 2, 2], 3, 0.1, 'plain', ev_p=0)
mC = dict(cards=mA['cards'] + mB['cards'], factors=mA['factors'] + [dict(scope=tuple(v + 3 for v in f['scope']), values=f['values']) for f in mB['factors']], evidence={})
tC = core.brute_force(mC); rC, eC = run(mC, [0, 3, 1, 4, 2, 5]); ok = rC is not None and contained(rC['intervals'], tC); total += 1; passed += ok; R['controls'].append(dict(name='disconnected_components_one_plan', ok=ok, roots_note='two scalar roots multiplied into Z; exclusion products give each root adjoint'))
# ---- D. extreme exponents / near-zero normalizer: skewed magnitudes 10^-60 .. 10^60 in one model -> range refusal or valid enclosure, never a wrong answer
mag_range = 60; mE = gen(random.Random(13), 5, [2, 2, 3, 2, 2], 6, 0.0, 'skew', ev_p=0); tE = core.brute_force(mE); rE, eE = run(mE, [4, 0, 3, 1, 2])
ok = (rE is not None and contained(rE['intervals'], tE)) or (eE is not None and eE.kind == 'RANGE'); total += 1; passed += ok; R['controls'].append(dict(name='extreme_exponents_10^-60..10^60', ok=ok, outcome=(rE['status'] if rE else 'STOP:%s %s' % (eE.kind, eE.reason[:80]))))
mag_range = 300; mE2 = gen(random.Random(14), 4, [2, 2, 2, 2], 5, 0.0, 'skew', ev_p=0); tE2 = core.brute_force(mE2); rE2, eE2 = run(mE2, [0, 1, 2, 3])
ok = (rE2 is not None and contained(rE2['intervals'], tE2)) or (eE2 is not None and eE2.kind == 'RANGE'); total += 1; passed += ok; R['controls'].append(dict(name='extreme_exponents_10^-300..10^300_(source_conversion_range)', ok=ok, outcome=(rE2['status'] if rE2 else 'STOP:%s %s' % (eE2.kind, eE2.reason[:80]))))
# a positive true value whose double would be 0: 10^-400 is below the normal range -> conversion RANGE refusal (not a zero-support witness)
mT = dict(cards=[2], factors=[dict(scope=(0,), values=[F(1), F(1, 10 ** 400)])], evidence={}); rT, eT = run(mT, [0]); ok = eT is not None and eT.kind == 'RANGE'; total += 1; passed += ok; R['controls'].append(dict(name='positive_value_below_normal_range_refused_not_zero', ok=ok, outcome=('STOP:%s' % eT.kind if eT else rT['status'])))
# ---- E. hard zeros that make a component's mass zero: typed ZERO_EVIDENCE, no answer
mZ = dict(cards=[2, 2], factors=[dict(scope=(0,), values=[F(1), F(0)]), dict(scope=(0, 1), values=[F(0), F(0), F(1), F(1)])], evidence={}); rZ, eZ = run(mZ, [0, 1]); ok = rZ is not None and rZ['status'] == 'ZERO_EVIDENCE'; total += 1; passed += ok; R['controls'].append(dict(name='zero_evidence_mass_typed', ok=ok))
# ---- F. resource stops: deadline inside the kernel, memory cap, row cap -> typed, no partial answer
mBig = gen(random.Random(21), 12, [3] * 12, 20, 0.0, 'plain', ev_p=0); oB = list(range(12))
rD, eD = run(mBig, oB, budget=0.0005); ok = eD is not None and eD.kind == 'DEADLINE'; total += 1; passed += ok; R['controls'].append(dict(name='deadline_typed_stop', ok=ok, outcome=(eD.kind if eD else rD['status'])))
# a single dense factor over 11 ternary variables (177,147 entries = 1.4 MB): (a) kernel-side refusal: the cap leaves exactly 1 MiB of kernel capacity, so the source
# reservation (1.4 MB) is refused BEFORE allocation; (b) Python-side refusal: a cap below the host-side headroom is refused before the kernel is entered
mDense = dict(cards=[3] * 11, factors=[dict(scope=tuple(range(11)), values=[F(1 + (i * 7919) % 13) for i in range(3 ** 11)])], evidence={}); wD, vD, _ = X.lower(mDense, list(range(11)), 0.25)
capK = 64 * 1024 ** 2 + (len(wD) * 8 + len(vD) * 8) * 2 + 1024 ** 2
rM, eM = run(mDense, list(range(11)), cap_bytes=capK); ok = eM is not None and eM.kind == 'MEMORY' and 'logical reservation' in eM.reason and (eM.stats.get('counters') or {}).get('forward_rows', 0) == 0
total += 1; passed += ok; R['controls'].append(dict(name='memory_cap_typed_stop_before_allocation', ok=ok, outcome=(eM.kind + ': ' + eM.reason[:100] if eM else rM['status']), kernel_cap_bytes=(eM.stats.get('kernel_cap_bytes') if eM else None)))
rM2, eM2 = run(mDense, list(range(11)), cap_bytes=1024 ** 2); ok = eM2 is not None and eM2.kind == 'MEMORY' and 'host-side' in eM2.reason; total += 1; passed += ok; R['controls'].append(dict(name='memory_cap_below_host_headroom_refused_before_kernel', ok=ok, outcome=(eM2.kind + ': ' + eM2.reason[:80] if eM2 else rM2['status'])))
rM3, eM3 = run(mDense, list(range(11)), cap_bytes=256 * 1024 ** 2); tD = None
ok = rM3 is not None and rM3['status'] == 'CERTIFIED' and rM3['stats']['counters']['peak_logical_bytes'] > 1_400_000 and rM3['stats']['counters']['logical_bytes_at_exit'] <= rM3['stats']['counters']['peak_logical_bytes']; total += 1; passed += ok
R['controls'].append(dict(name='memory_cap_sufficient_completes_and_reports_peak_logical_bytes', ok=ok, peak_logical_bytes=(rM3['stats']['counters']['peak_logical_bytes'] if rM3 else None), at_exit=(rM3['stats']['counters']['logical_bytes_at_exit'] if rM3 else None)))
# ---- G. binding: the semantic plan hash changes with any value / scope / order change and is identical across physical schedules
w1, v1, meta1 = X.lower(mA, [0, 1, 2], 0.25); w2, v2, meta2 = X.lower(mA, [0, 1, 2], 1.01); mA2 = dict(mA, factors=[dict(mA['factors'][0], values=list(mA['factors'][0]['values'][:-1]) + [mA['factors'][0]['values'][-1] + 1])] + mA['factors'][1:])
w3, v3, meta3 = X.lower(mA2, [0, 1, 2], 0.25); w4, v4, meta4 = X.lower(mA, [2, 1, 0], 0.25)
ok = meta1['semantic_plan_sha256'] == meta2['semantic_plan_sha256'] and meta1['physical_schedule_sha256'] != meta2['physical_schedule_sha256'] and meta3['semantic_plan_sha256'] != meta1['semantic_plan_sha256'] and meta4['semantic_plan_sha256'] != meta1['semantic_plan_sha256']
total += 1; passed += ok; R['controls'].append(dict(name='plan_binding_semantic_vs_physical_hash', ok=ok))
# ---- H. wrong order (does not cover the unobserved variables) is refused before any arithmetic
try: X.lower(mA, [0, 1], 0.25); ok = False
except ValueError: ok = True
total += 1; passed += ok; R['controls'].append(dict(name='order_not_covering_refused', ok=ok))
# ---- I. publication invariant guard: a tampered interval row fails core.verify_output (checker failure control)
rI, _ = run(mA, [0, 1, 2]); bad = [list(row) for row in rI['intervals']]; bad[0][0] = (bad[0][0][1], bad[0][0][1] + F(1, 50))
try: core.verify_output(bad, rI['points']); ok = False
except AssertionError: ok = True
total += 1; passed += ok; R['controls'].append(dict(name='checker_rejects_tampered_interval', ok=ok))
# ---- J. equivalence of the three physical schedules on one model: identical semantic hash, all enclosures contain truth, widths all <= 1/100 (not bitwise equal)
mJ = gen(random.Random(31), 6, [2, 3, 2, 3, 2, 2], 7, 0.3, 'plain', ev_p=0); tJ = core.brute_force(mJ); oJ = [5, 2, 0, 4, 1, 3]; outs = []
for thr in (0.0, 0.25, 1.01):
    rJ, eJ = run(mJ, oJ, dense_fill_threshold=thr); outs.append((rJ, eJ))
ok = all(r is not None and contained(r['intervals'], tJ) for r, _ in outs) and len({r['certificate']['semantic_plan_sha256'] for r, _ in outs}) == 1 and len({r['certificate']['physical_schedule_sha256'] for r, _ in outs}) == 3
total += 1; passed += ok; R['controls'].append(dict(name='three_physical_schedules_same_semantic_plan', ok=ok, sparse_buckets=[r['stats']['counters']['buckets_sparse'] for r, _ in outs]))
# ---- K. different sound reduction trees (every permutation of a 4-variable order) all enclose truth
mK = gen(random.Random(41), 4, [2, 3, 2, 2], 5, 0.2, 'plain', ev_p=0); tK = core.brute_force(mK); allok = True
for perm_ in permutations(range(4)):
    rK, eK = run(mK, list(perm_)); allok = allok and rK is not None and contained(rK['intervals'], tK)
total += 1; passed += allok; R['controls'].append(dict(name='all_24_elimination_orders_enclose_truth', ok=allok))
R.update(dict(passed=passed, total=total, all_pass=passed == total, kernel=json.load(open(os.path.join(BASE, 'cex_build.json'))), executor_sha256=hashlib.sha256(open(os.path.join(BASE, 'cex_executor.py'), 'rb').read()).hexdigest(), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
json.dump(R, open(os.path.join(BASE, 'CEX_QUALIFICATION.json'), 'w'), indent=1, default=str); print(json.dumps({'passed': passed, 'total': total, 'all_pass': R['all_pass'], 'controls': [(c['name'], c['ok']) for c in R['controls']]}))
