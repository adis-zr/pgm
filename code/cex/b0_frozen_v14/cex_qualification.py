"""Qualification of the compiled executor (prompt section 8 step 2; v1.2 after the adversarial review of 11 Nov 2026) against raw-model exact enumeration and the
exact Fraction reference on the SAME plan. Random section A: 120 mixed-domain models (hard zeros, repeated occurrences, evidence, skewed magnitudes) x 3 physical
schedules (fill thresholds 0 / 0.25 / 1.01). Grouped controls (one count each): B permuted axes/ids; C disconnected components; D extreme exponents 10^+-60 and
10^+-300 (valid enclosure or typed RANGE), a positive value below the normal range refused (never zero); E typed ZERO_EVIDENCE; F deadline inside the kernel,
memory cap refused BEFORE allocation (kernel side and host side), sufficient cap completes and reports the peak; G semantic vs physical plan hash; H non-covering
order refused; I checker rejects a tampered interval; J three physical schedules of one semantic plan; K all 24 elimination orders of a 4-variable model.
REVIEW REGRESSIONS (permanent, 11 Nov 2026): L the reviewer's three reverse-underflow constructions + a randomized high-degree family (valid enclosure containing
exact truth or typed RANGE; never a false certificate) under several multiplication orders; M integer-volume overflow (22x8 / 32x4 / 21x8 stars direct and the
22x8 complete graph through the automatic solver) -> typed REPRESENTATION refusal, never ZERO_EVIDENCE; an affordable 10x4 star certifies the uniform truth;
N source conversion: huge entries (10^400, 2^2000) certify after exact power-of-two scaling, direct and through the automatic solver (the baseline success is kept);
O an already-expired deadline is a typed DEADLINE at entry (no row visited); P label overflow: the enclosure refuses K u >= 1/2 (typed RANGE) and the kernel refuses
an int64 label-sum overflow (typed REPRESENTATION); Q the allocation boundary (instrumented global operator new, strict build AND UBSan build): the kernel's
peak_logical_bytes EQUALS the tracked native peak and nothing is live at return on every control; small caps are refused before any row; growth overlap is charged;
rescale exactness is round-trip checked; R host-side HostBudget charged before every construction + RSS growth measured. FOLLOW-UP REVIEW REGRESSIONS (v1.4): S the reviewer's
host-memory counterexample is refused before construction and certifies within budget under a sufficient cap; streamed semantic hash == closed form; T early ZERO_EVIDENCE honours the
deadline; U integer metadata ABI bounds (driver `meta` mode, strict + UBSan); V gate v3 / locked_plan v3 negative controls all rejected (cex/gate_controls.py). Writes CEX_QUALIFICATION.json beside this file. Count = passed/total
TESTS AND CONTROL GROUPS (random executions + grouped controls), NOT a count of enclosures."""
import sys, time, random, json, math, hashlib, os, collections
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
BD = X.HostBudget(1 << 62, {}); X.lower(mDense, list(range(11)), 0.25, budget=BD); arraysD = len(wD) * 8 + max(1, len(vD)) * 8 + sum(mDense['cards']) * 8 + 11 * 16 + 8 + 16 + len(X.COUNTERS) * 8 + 256     # exactly execute()'s arrays_bytes
capK = BD.live + arraysD + 1024 ** 2    # the host budget admits every host construction (live after lowering + arrays) and leaves the kernel exactly 1 MiB: the 1.4 MB source is refused by the KERNEL's allocation boundary BEFORE allocation
rM, eM = run(mDense, list(range(11)), cap_bytes=capK); ok = eM is not None and eM.kind == 'MEMORY' and 'allocation boundary' in eM.reason and (eM.stats.get('counters') or {}).get('forward_rows', 0) == 0
total += 1; passed += ok; R['controls'].append(dict(name='memory_cap_typed_stop_before_allocation', ok=ok, outcome=(eM.kind + ': ' + eM.reason[:100] if eM else rM['status']), kernel_cap_bytes=(eM.stats.get('kernel_cap_bytes') if eM else None)))
rM2, eM2 = run(mDense, list(range(11)), cap_bytes=1024 ** 2); ok = eM2 is not None and eM2.kind == 'MEMORY' and 'host budget' in eM2.reason and 'counters' not in eM2.stats; total += 1; passed += ok; R['controls'].append(dict(name='memory_cap_below_host_headroom_refused_before_kernel', ok=ok, outcome=(eM2.kind + ': ' + eM2.reason[:80] if eM2 else rM2['status'])))
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
# ======================= REVIEW REGRESSIONS (adversarial review of 11 Nov 2026) =======================
import subprocess, itertools, ctypes as CT_
def exact_marginals(model):
    nums = [[F(0)] * c for c in model['cards']]; z = F(0)
    for a in itertools.product(*(range(c) for c in model['cards'])):
        w = F(1)
        for f in model['factors']:
            idx = 0
            for v in f['scope']: idx = idx * model['cards'][v] + a[v]
            w *= f['values'][idx]
        z += w
        for v, st in enumerate(a): nums[v][st] += w
    return None if z == 0 else [[x / z for x in row] for row in nums]
def sound(m, order, **kw):
    """a result is SOUND iff it is CERTIFIED and encloses the exact truth (or truth is zero mass and it says so) or a typed RANGE/REPRESENTATION/MEMORY/DEADLINE stop; a false certificate is UNSOUND"""
    truth = exact_marginals(m); r, e = run(m, order, **kw)
    if e is not None: return e.kind in ('RANGE', 'REPRESENTATION', 'MEMORY', 'DEADLINE'), 'STOP:%s %s' % (e.kind, e.reason[:90])
    if truth is None: return r['status'] == 'ZERO_EVIDENCE', r['status']
    if r['status'] != 'CERTIFIED': return False, r['status']
    return contained(r['intervals'], truth) and core.verify_output(r['intervals'], r['points']), 'CERTIFIED' + ('' if contained(r['intervals'], truth) else ' FALSE_CERTIFICATE')
# ---- L. reverse-underflow constructions (reviewer's F1): 110 unary [3/2,1] occurrences on y, equality (x,y), two tiny leaves (z,y),(w,y) with 2^-541 entries
def review_model(binary=True, strictly_positive=False):
    factors = [{'scope': (3,), 'values': [F(3, 2), F(1)]} for _ in range(110)]
    eps = F(1, 2 ** 1020) if strictly_positive else F(0)
    factors.append({'scope': (0, 3), 'values': [F(1), eps, eps, F(1)]})
    for leaf in (1, 2):
        vals = [F(1, 2 ** 541), F(1, 2)] * 2 if binary else [F(1, 2 ** 540), F(1)]
        factors.append({'scope': (leaf, 3), 'values': vals})
    return {'cards': [2, 2, 2, 2] if binary else [2, 1, 1, 2], 'evidence': {}, 'factors': factors}
outsL = []
for binary, positive in ((False, False), (True, False), (True, True)):
    ok, what = sound(review_model(binary, positive), [0, 1, 2, 3]); outsL.append((binary, positive, ok, what)); total += 1; passed += ok
    R['controls'].append(dict(name='review_F1_reverse_underflow_%s%s' % ('binary' if binary else 'mixed_card', '_strictly_positive' if positive else '_hard_zero'), ok=ok, outcome=what))
# randomized high-degree family: k tiny leaves (2^-a, a in 300..700), u unary occurrences (1..160) of [3/2,1] or [1,3/2], all 24 orders of the 4 variables, three fill thresholds
rngL = random.Random(1111); allok = True; fam = []
for trial in range(40):
    k = rngL.randint(1, 3); u = rngL.randint(1, 160); a = rngL.randint(300, 700); m = {'cards': [2] * (2 + k), 'evidence': {}, 'factors': []}
    for _ in range(u): m['factors'].append({'scope': (1,), 'values': rngL.choice([[F(3, 2), F(1)], [F(1), F(3, 2)], [F(7, 5), F(1, 3)]])})
    m['factors'].append({'scope': (0, 1), 'values': rngL.choice([[F(1), F(0), F(0), F(1)], [F(1), F(1, 2 ** 1020), F(1, 2 ** 1020), F(1)], [F(2), F(1), F(1), F(3)]])})
    for leaf in range(2, 2 + k): m['factors'].append({'scope': (leaf, 1), 'values': [F(1, 2 ** a), F(1, 2), F(1, 2 ** rngL.randint(1, a)), F(1, 2)]})
    orders = [list(o) for o in permutations(range(2 + k))]; rngL.shuffle(orders)
    for o in orders[:4]:
        for thr in (0.0, 0.25, 1.01):
            ok, what = sound(m, o, dense_fill_threshold=thr); allok = allok and ok; fam.append((trial, o, thr, what[:40]))
            if not ok: print('FAIL L', trial, o, thr, what, flush=True)
total += 1; passed += allok; R['controls'].append(dict(name='review_F1_randomized_high_degree_family_480_executions_4_of_24_orders_per_model', ok=allok, outcomes=dict(collections.Counter(w.split(' ')[0] for _, _, _, w in fam))))
# ---- M. integer-volume overflow (reviewer's F2): typed REPRESENTATION, never ZERO_EVIDENCE; the automatic solver surfaces a ResourceStop
for n_, c_ in ((22, 8), (32, 4), (21, 8)):
    mS = {'cards': [c_] * n_, 'evidence': {}, 'factors': [{'scope': (0, i), 'values': [F(1)] * (c_ * c_)} for i in range(1, n_)]}
    rS, eS = run(mS, list(range(n_)), cap_bytes=100_000_000); ok = eS is not None and eS.kind == 'REPRESENTATION' and (eS.stats.get('counters') or {}).get('forward_rows', 0) == 0; total += 1; passed += ok
    R['controls'].append(dict(name='review_F2_star_%dx%d_volume_overflow_typed_representation' % (n_, c_), ok=ok, outcome=('STOP:%s %s' % (eS.kind, eS.reason[:80]) if eS else rS['status'])))
mQ = {'cards': [8] * 22, 'evidence': {}, 'factors': [{'scope': (i, j), 'values': [F(1)] * 64} for i in range(22) for j in range(i + 1, 22)]}
try: core.solve(mQ, deadline=time.monotonic() + 20); okQ = False; whatQ = 'completed?'
except support.ResourceStop as ex: okQ = ex.reason == 'REPRESENTATION'; whatQ = 'ResourceStop:%s' % ex.reason
except Exception as ex: okQ = False; whatQ = '%s: %s' % (type(ex).__name__, str(ex)[:60])
total += 1; passed += okQ; R['controls'].append(dict(name='review_F2_automatic_solver_22x8_complete_graph_typed_refusal_not_zero_evidence', ok=okQ, outcome=whatQ))
mS10 = {'cards': [4] * 10, 'evidence': {}, 'factors': [{'scope': (0, i), 'values': [F(1)] * 16} for i in range(1, 10)]}; rS10, eS10 = run(mS10, list(range(10)), cap_bytes=200_000_000)
ok = rS10 is not None and rS10['status'] == 'CERTIFIED' and contained(rS10['intervals'], [[F(1, 4)] * 4 for _ in range(10)]); total += 1; passed += ok; R['controls'].append(dict(name='review_F2_affordable_10x4_star_certifies_uniform_truth', ok=ok))
# ---- N. source conversion range (reviewer's F4): huge entries are scaled exactly by a power of two; the baseline success is preserved through the automatic solver
mN = {'cards': [2, 2, 2], 'evidence': {}, 'factors': [{'scope': (0, 1, 2), 'values': [F(10 ** 400) * (i + 1) for i in range(8)]}]}; tN = [[F(5, 18), F(13, 18)], [F(7, 18), F(11, 18)], [F(4, 9), F(5, 9)]]
rN, eN = run(mN, [0, 1, 2]); ok = rN is not None and rN['status'] == 'CERTIFIED' and contained(rN['intervals'], tN); total += 1; passed += ok; R['controls'].append(dict(name='review_F4_source_10^400_direct_certified_after_exact_scaling', ok=ok, outcome=(rN['status'] if rN else 'STOP:%s' % eN.kind)))
try: gN = core.solve(mN, deadline=time.monotonic() + 10); ok = contained(gN['intervals'], tN) and gN['stats']['components'][0]['route'] == 'support'; whatN = gN['status']
except Exception as ex: ok = False; whatN = '%s: %s' % (type(ex).__name__, str(ex)[:60])
total += 1; passed += ok; R['controls'].append(dict(name='review_F4_source_10^400_automatic_solver_keeps_the_baseline_success', ok=ok, outcome=whatN))
m2k = {'cards': [2], 'evidence': {}, 'factors': [{'scope': (0,), 'values': [F(2) ** 2000, F(2) ** 2000]}]}; r2k, e2k = run(m2k, [0]); ok = r2k is not None and r2k['status'] == 'CERTIFIED' and contained(r2k['intervals'], [[F(1, 2), F(1, 2)]]); total += 1; passed += ok; R['controls'].append(dict(name='review_F4_source_2^2000_certified_after_exact_scaling', ok=ok))
mW = {'cards': [2], 'evidence': {}, 'factors': [{'scope': (0,), 'values': [F(10) ** 400, F(10) ** -400]}]}; rW, eW = run(mW, [0]); ok = eW is not None and eW.kind == 'RANGE'; total += 1; passed += ok; R['controls'].append(dict(name='review_F4_dynamic_range_inside_one_factor_beyond_binary64_typed_RANGE_not_zero', ok=ok, outcome=('STOP:%s' % eW.kind if eW else rW['status'])))
# ---- O. expired deadline at entry (reviewer's R2): typed DEADLINE, zero rows
mO = {'cards': [2] * 1000, 'evidence': {}, 'factors': [{'scope': (i,), 'values': [F(1, 2), F(1, 2)]} for i in range(1000)]}
try: X.execute(mO, list(range(1000)), deadline=0.0, cap_bytes=200_000_000); okO = False; whatO = 'returned'
except X.Stop as ex: okO = ex.kind == 'DEADLINE' and (ex.stats.get('counters') or {}).get('forward_rows') in (0, None); whatO = 'STOP:%s %s (kernel entered: %s)' % (ex.kind, ex.reason[:60], 'counters' in ex.stats)   # refused at the Python entry check (no kernel call) or at the kernel's entry check (zero rows)
total += 1; passed += okO; R['controls'].append(dict(name='review_R2_expired_deadline_is_typed_DEADLINE_at_entry', ok=okO, outcome=whatO))
try: X.execute(mO, list(range(1000)), deadline=time.monotonic() + 0.0005, cap_bytes=200_000_000); okO2 = False; whatO2 = 'returned'
except X.Stop as ex: okO2 = ex.kind == 'DEADLINE'; whatO2 = 'STOP:%s %s' % (ex.kind, ex.reason[:60])
total += 1; passed += okO2; R['controls'].append(dict(name='review_R2_deadline_during_parsing_or_phases_typed_DEADLINE', ok=okO2, outcome=whatO2))
# ---- P. label overflow: the enclosure refuses K u >= 1/2; the kernel refuses an int64 label-sum overflow (direct call with patched plan words)
try: X.enclose([1.0, 1.0], [0], [2 ** 52], 2.0, 0, 0, [2], {}, {}); okP = False; whatP = 'returned'
except X.Stop as ex: okP = ex.kind == 'RANGE' and 'label' in ex.reason; whatP = 'STOP:%s %s' % (ex.kind, ex.reason[:60])
total += 1; passed += okP; R['controls'].append(dict(name='review_P_enclosure_refuses_label_K_u_>=_1/2_typed_RANGE', ok=okP, outcome=whatP))
mP = {'cards': [2, 2], 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [F(1), F(2), F(3), F(4)]}, {'scope': (0, 1), 'values': [F(2), F(1), F(1), F(2)]}]}
wP, vP, metaP = X.lower(mP, [0, 1], 0.25); provP = X.build(); libP = X.load(provP)
# plan words: 2, n, cards[2], n, order[2], nsrc, then per source: slen, scope..., mode, count, label, exp2 -> patch both labels to 2^62
idx = 2 + 2 + 1 + 2 + 1; pos = []
for s_ in range(2):
    sl = wP[idx]; idx += 1 + sl; mode = wP[idx]; cnt = wP[idx + 1]; idx += 2 + (cnt if mode == 1 else 0); pos.append(idx); idx += 2
wP2 = list(wP)
for q_ in pos: wP2[q_] = 2 ** 62
Wp = (CT_.c_int64 * len(wP2))(*wP2); Vp = (CT_.c_double * len(vP))(*vP); Np = (CT_.c_double * 4)(); NEp = (CT_.c_int64 * 2)(); NLp = (CT_.c_int64 * 2)(); Zp = (CT_.c_double * 1)(); ZMp = (CT_.c_int64 * 2)(); CTp = (CT_.c_uint64 * len(X.COUNTERS))(); RSp = CT_.create_string_buffer(256)
rcP = libP.cex_run(Wp, len(wP2), Vp, len(vP), 10 ** 8, float('inf'), 0.25, Np, NEp, NLp, Zp, ZMp, CTp, len(X.COUNTERS), RSp, 256)
okP1 = rcP == 4 and b'ABI precondition' in RSp.value
wP3 = list(wP)
for q_ in pos: wP3[q_] = 2 ** 40          # in-bounds extreme labels: carried and summed without overflow (K = 2^41 + ... -> the enclosure then refuses K u >= 1/2 as RANGE, not a wrapped negative label)
Wp3 = (CT_.c_int64 * len(wP3))(*wP3); rcP3 = libP.cex_run(Wp3, len(wP3), Vp, len(vP), 10 ** 8, float('inf'), 0.25, Np, NEp, NLp, Zp, ZMp, CTp, len(X.COUNTERS), RSp, 256); okP2 = rcP3 == 0 and int(NLp[0]) > 2 ** 41 and int(ZMp[1]) > 2 ** 41
ok = okP1 and okP2; total += 1; passed += ok; R['controls'].append(dict(name='review_P_kernel_label_metadata_ABI_bound_refused_and_in_bounds_labels_carried', ok=ok, outcome='2^62 labels: %s %s; 2^40 labels: rc %d Nlab %d Zlab %d' % (X.STOPS.get(rcP, rcP), RSp.value.decode(errors='replace')[:60], rcP3, int(NLp[0]), int(ZMp[1]))))
# ---- Q. the allocation boundary: the instrumented control driver (global operator new counts every requested byte while cex_run executes), strict build and UBSan build
def build_driver(extra, out):
    cmd = ['clang++', '-std=c++17', '-O1', '-g', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', *extra, '-DKERNEL_PATH="cex_kernel.cpp"', '-I' + BASE, os.path.join(BASE, 'cex_control_driver.cpp'), '-o', out]
    p = subprocess.run(cmd, capture_output=True, text=True); return p.returncode == 0, p.stderr[-400:]
drv = {}
for tag, extra in (('strict', []), ('ubsan', ['-fsanitize=undefined', '-fno-sanitize-recover=undefined'])):
    out = os.path.join(BASE, 'native_cache', 'cex_control_driver_' + tag); os.makedirs(os.path.dirname(out), exist_ok=True); okb, err = build_driver(extra, out); drv[tag] = dict(built=okb, err=err, cases=[])
    if not okb: continue
    for args, expect in ((['unaries', '32000'], 'MEMORY'), (['unaries', '4000000'], 'OK'), (['isolated', '160000', '0'], 'DEADLINE'), (['isolated', '4000000', '1e18'], 'MEMORY'), (['star', '22', '8'], 'REPRESENTATION'), (['star', '32', '4'], 'REPRESENTATION'), (['star', '21', '8'], 'REPRESENTATION'), (['star', '10', '4'], 'OK'), (['sparse', '2000000'], 'OK'), (['sparse', '2000'], 'MEMORY')):
        p = subprocess.run([out, *args], capture_output=True, text=True, timeout=120)
        try: j = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception: j = {'parse_error': p.stdout[-200:] + p.stderr[-400:]}
        okc = p.returncode == 0 and j.get('stop') == expect and j.get('peak_matches') is True and j.get('nothing_live') is True and (expect != 'MEMORY' or j.get('forward_rows') == 0) and (expect != 'REPRESENTATION' or j.get('forward_rows') == 0) and (expect != 'DEADLINE' or j.get('tracked_allocations') == 0)
        drv[tag]['cases'].append(dict(args=args, expect=expect, ok=okc, stop=j.get('stop'), reported_peak=j.get('reported_peak_logical_bytes'), tracked_peak=j.get('tracked_native_peak_requested_bytes'), live_at_return=j.get('tracked_native_live_at_return'), sanitizer_stderr=p.stderr[-200:] if p.stderr else ''))
    p = subprocess.run([out, 'growth'], capture_output=True, text=True, timeout=60); j = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
    drv[tag]['growth'] = dict(ok=(j.get('first_allowed') is True and j.get('second_allowed') is False and j.get('reported_peak_logical_bytes') == j.get('tracked_native_peak_requested_bytes')), record=j)
    p = subprocess.run([out, 'rescale_boundary'], capture_output=True, text=True, timeout=60); j = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
    drv[tag]['rescale_boundary'] = dict(ok=(j.get('inexact_case_refused') is True and j.get('exact_case_ok') is True and j.get('exact_case_values_and_exponent_correct') is True), record=j)
    p = subprocess.run([out, 'meta'], capture_output=True, text=True, timeout=60); jm = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else []
    drv[tag]['meta'] = dict(ok=(p.returncode == 0 and len(jm) == 5 and all(x.get('ok') for x in jm) and not p.stderr.strip()), records=jm, stderr=p.stderr[-200:])
for tag in ('strict', 'ubsan'):
    d = drv[tag]; okd = d['built'] and len(d['cases']) == 10 and all(c['ok'] for c in d['cases']) and d.get('growth', {}).get('ok') and d.get('rescale_boundary', {}).get('ok') and d.get('meta', {}).get('ok')
    total += 1; passed += bool(okd); R['controls'].append(dict(name='review_F3_allocation_boundary_instrumented_driver_%s_build' % tag, ok=bool(okd), detail=d))
# ======================= FOLLOW-UP REVIEW REGRESSIONS (repair review of 11 Nov 2026) =======================
# ---- S. §3 the reviewer's host-memory counterexample: 1,024 states x 2^50000 under cap = entry RSS + 4 MiB must be a typed MEMORY stop BEFORE the construction (never CERTIFIED past the cap)
mS = {'cards': [1024], 'factors': [{'scope': (0,), 'values': [F(1 << 50000)] * 1024}], 'evidence': {}}; entryS = X.rss_bytes(); capS = entryS + 4 * 1024 ** 2
try: rS_ = X.execute(mS, [0], deadline=time.monotonic() + 60, cap_bytes=capS, host_reserved_bytes=entryS); okS = False; whatS = 'CERTIFIED past the cap (budget peak %s)' % rS_['stats'].get('host_budget_peak_bytes')
except X.Stop as ex: okS = ex.kind == 'MEMORY' and 'host budget' in ex.reason and (ex.stats.get('host_budget_live_bytes', 0) + ex.stats.get('host_budget_refused_bytes', 0)) > capS - entryS; whatS = 'STOP:%s %s' % (ex.kind, ex.reason[:110])
total += 1; passed += okS; R['controls'].append(dict(name='review2_S3_host_memory_cap_refused_before_construction', ok=okS, outcome=whatS, cap_minus_entry=capS - entryS))
entryS = X.rss_bytes()
try: rS2 = X.execute(mS, [0], deadline=time.monotonic() + 60, cap_bytes=entryS + 256 * 1024 ** 2, host_reserved_bytes=entryS); okS2 = rS2['status'] == 'CERTIFIED' and contained(rS2['intervals'], [[F(1, 1024)] * 1024]) and rS2['stats']['host_budget_peak_bytes'] <= 256 * 1024 ** 2 and rS2['stats']['hash_blocks'] >= 2; whatS2 = 'CERTIFIED; budget peak %d; rss growth %d; hash blocks %d' % (rS2['stats']['host_budget_peak_bytes'], rS2['stats']['host_lowering_rss_growth_bytes_measured'], rS2['stats']['hash_blocks'])
except X.Stop as ex: okS2 = False; whatS2 = 'STOP:%s %s' % (ex.kind, ex.reason[:100])
total += 1; passed += okS2; R['controls'].append(dict(name='review2_S3_same_model_under_sufficient_cap_certifies_within_budget', ok=okS2, outcome=whatS2))
# the streamed semantic hash must equal the v1.3 closed form json.dumps([scope, [str(v) ...]]) per factor (binding unchanged across versions)
mH = {'cards': [2, 3], 'factors': [{'scope': (0,), 'values': [F(1, 3), F(2, 3)]}, {'scope': (0, 1), 'values': [F(1), F(2), F(3), F(4), F(0), F(2 ** 100, 7)]}], 'evidence': {1: 2}}
wH, vH, metaH = X.lower(mH, [0], 0.25); semH = hashlib.sha256(); semH.update(json.dumps({'cards': [2, 3], 'evidence': [(1, 2)], 'order': [0]}).encode())
for f in mH['factors']:
    sc = f['scope']; data = [wv for a, wv in zip(product(*(range(mH['cards'][x]) for x in sc)), f['values']) if all(a[i] == mH['evidence'][x] for i, x in enumerate(sc) if x in mH['evidence'])]; newsc = tuple(x for x in sc if x not in mH['evidence']); semH.update(json.dumps([list(newsc), [str(x) for x in data]]).encode())
okH = semH.hexdigest() == metaH['semantic_plan_sha256']; total += 1; passed += okH; R['controls'].append(dict(name='review2_streamed_semantic_hash_equals_closed_form', ok=okH))
# ---- T. §7B an early ZERO_EVIDENCE must still honour the deadline (typed DEADLINE, not a late ZERO_EVIDENCE)
mT2 = {'cards': [1024], 'factors': [{'scope': (0,), 'values': [F(1 << 50000)] * 1024}, {'scope': (), 'values': [F(0)]}], 'evidence': {}}; tT = time.monotonic()
try: rT2 = X.execute(mT2, [0], deadline=tT + 0.05); okT = False; whatT = '%s after %.2f s' % (rT2['status'], time.monotonic() - tT)
except X.Stop as ex: okT = ex.kind == 'DEADLINE'; whatT = 'STOP:%s after %.2f s (%s)' % (ex.kind, time.monotonic() - tT, ex.reason[:60])
total += 1; passed += okT; R['controls'].append(dict(name='review2_S7B_early_zero_evidence_honours_deadline', ok=okT, outcome=whatT))
rT3, eT3 = run(mT2, [0], budget=60); okT3 = rT3 is not None and rT3['status'] == 'ZERO_EVIDENCE'; total += 1; passed += okT3; R['controls'].append(dict(name='review2_S7B_same_model_with_budget_is_zero_evidence', ok=okT3))
# ---- U. §7A integer metadata: the ABI precondition (label in [0, 2^40], exponent in [-2^40, 2^40]) is enforced at the parser (BADPLAN), in-bounds metadata is carried; checked under UBSan by the driver's `meta` mode (control Q below)
# ---- V. §4 / §5 experimental-integrity gates: every negative control of cex/gate_controls.py must be rejected (and the untouched saved campaigns accepted)
pG = subprocess.run([sys.executable, os.path.join(BASE, '..', 'gate_controls.py'), os.path.join(BASE, '..', '..', 'runs', 'mdi_2026-10-28', 'CERTIFIED_EXECUTOR_2026-11-11'), os.path.join(BASE, '..', '..'), os.path.join(BASE, 'GATE_CONTROLS.json')], capture_output=True, text=True)
try: gc = json.load(open(os.path.join(BASE, 'GATE_CONTROLS.json')))
except Exception: gc = []
okG = pG.returncode == 0 and len(gc) == 9 and all(g['ok'] for g in gc); total += 1; passed += okG; R['controls'].append(dict(name='review2_S4_S5_gate_and_locked_plan_negative_controls_rejected', ok=okG, controls=[(g['control'], g['ok']) for g in gc], stderr=pG.stderr[-300:] if not okG else ''))
# ---- R. host-side memory is measured per phase and enters the kernel cap
rR, eR = run(mJ, oJ); wJ, vJ, _ = X.lower(mJ, oJ, 0.25)
ok = rR is not None and rR['stats']['host_lowering_retained_bytes_counted'] == X.counted_bytes(wJ, vJ) > 0 and rR['stats']['host_budget_peak_bytes'] >= rR['stats']['host_lowering_retained_bytes_counted'] and rR['stats']['kernel_cap_bytes'] == 3 * 1024 ** 3 - rR['stats']['host_budget_live_at_kernel_call_bytes'] and 'host_lowering_rss_growth_bytes_measured' in rR['stats'] and 'host_enclosure_rss_growth_bytes_measured' in rR['stats']
total += 1; passed += ok; R['controls'].append(dict(name='review_F3_host_side_budget_charged_before_build_and_rss_growth_measured', ok=ok, measured={k: rR['stats'].get(k) for k in ('host_budget_peak_bytes', 'host_budget_live_bytes', 'host_budget_live_at_kernel_call_bytes', 'host_lowering_rss_growth_bytes_measured', 'host_lowering_retained_bytes_counted', 'host_plan_output_arrays_bytes', 'host_enclosure_rss_growth_bytes_measured', 'kernel_cap_bytes')} if rR else None))
import collections
R.update(dict(passed=passed, total=total, all_pass=passed == total, random_executions=len(R['records']), random_status_counts=dict(collections.Counter(r['status'] for r in R['records'])), control_groups=len(R['controls']), count_semantics='passed/total counts random EXECUTIONS (each one test) plus grouped CONTROLS (one count each, several executing many plans); it is NOT a count of enclosures', kernel=json.load(open(os.path.join(BASE, 'cex_build.json'))), executor_sha256=hashlib.sha256(open(os.path.join(BASE, 'cex_executor.py'), 'rb').read()).hexdigest(), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
json.dump(R, open(os.path.join(BASE, 'CEX_QUALIFICATION.json'), 'w'), indent=1, default=str); print(json.dumps({'passed': passed, 'total': total, 'all_pass': R['all_pass'], 'random_executions': len(R['records']), 'controls': [(c['name'], c['ok']) for c in R['controls']]}))
sys.exit(0 if R['all_pass'] else 1)
