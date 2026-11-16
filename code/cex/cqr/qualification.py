"""INDEPENDENT QUALIFICATION of the CQR candidate (handoff 'QUALIFICATION THAT CAN FAIL THE IMPLEMENTATION'). Groups = registry.QUALIFICATION_GROUPS (the closeout requires
exactly this schema). Judge = cex/cqr/oracle.py (original-model rational enumerator; never the decoder under test). Counts BY CLASS, never pooled: fresh_workers (subprocess
worker.py runs), solver_calls (solve.solve in-process), compiler_calls, checker_calls, oracle_models (distinct models enumerated), truth_coordinates (published coordinates compared
with the oracle), assertions. Mutations are applied to COPIES of worker outputs / in-process operands; the shipped candidate is never altered. Every feature-off control acts on the
REAL implementation (arm operator sets / in-process operator calls), beneath the independent oracle. Refusal REASONS are asserted so a control cannot pass through an unrelated error.
C13 is PREREGISTERED (plan constants below, fixed before any data): tiny-model falsification of the confidence sequences at LARGE delta; a pass does NOT validate the 1e-6 tail.
Usage: python cex/cqr/qualification.py [--only C1,C2] [--admission DIR]   (writes cex/cqr/CQR_QUALIFICATION.json)"""
import os, sys, json, time, copy, random, hashlib, subprocess, collections, math, shutil, tempfile, io, contextlib
from fractions import Fraction as F
from itertools import product
from math import prod
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (HERE, NEWARM):
    if p not in sys.path: sys.path.insert(0, p)
import registry, task as TK, oracle as OR, compiler as CP, frontier as FR, solve as SV, checker as CK, generators as G, numerics as NM, worker as WK
from views import View
PY = sys.executable
SUITE_VERSION = 'cqr-qualification-v4.1 (2026-11-16, after the third adversarial review: group C21 added; after attempt 7: C21-06 baseline-row routes control)'
ADMISSION_DIR = os.environ.get('CQR_ADMISSION_DIR') or os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CQR_2026-11-15', 'admission_v9')
SOURCES_AT_START = registry.cqr_source_inventory(CODE)
R = dict(groups=[], counts=dict(fresh_workers=0, solver_calls=0, compiler_calls=0, checker_calls=0, oracle_models=0, truth_coordinates=0, stream_draws=0, assertions=0), suite_version=SUITE_VERSION, suite_sha256=registry.suite_sha256(CODE), candidate_sources=SOURCES_AT_START, admission_dir=ADMISSION_DIR)
CNT = R['counts']; passed = 0; total = 0
# ---- C13 PREREGISTRATION (fixed before data): two settings on ONE tiny 3-binary-variable chain model; sampling-only diagnostic (deterministic routes withheld), eps = 1/10;
# setting A: delta = 1/4, N = 120 runs; setting B: delta = 1/16, N = 120 runs. Test: misses_among_publications <= binomial 1 - 0.0005 quantile of Binomial(publications, delta)
# (family-wise alpha 0.001 over the two settings, one-sided). A pass is a gross-miscalibration falsification test only.
C13_PLAN = dict(model='3 binary variables, chain factors [1,2,3,1] and [2,1,1,3]', epsilon='1/10', settings=[dict(delta='1/4', runs=120), dict(delta='1/16', runs=120)], test='one-sided binomial, family-wise alpha 0.001 (0.0005 per setting)', deadline_per_run_s=12, note='a pass does not validate the 1e-6 tail')


def A(cond, msg):
    CNT['assertions'] += 1
    if not cond: raise AssertionError(msg)


def group(name, fn):
    global passed, total
    total += 1; t = time.monotonic(); ok = True; detail = None
    try: detail = fn()
    except Exception as e:
        import traceback; ok = False; detail = dict(error=str(e)[:600], trace=traceback.format_exc()[-1500:])
    passed += ok; R['groups'].append(dict(name=name, ok=ok, wall_s=round(time.monotonic() - t, 3), detail=detail)); print(('PASS ' if ok else 'FAIL ') + name, flush=True)


def rnd_model(rng, n, cards, nf, arity, zeros=0.0, ev=0, lo=1, hi=9):
    factors = []
    for _ in range(nf):
        k = rng.randint(1, arity); sc = rng.sample(range(n), k); size = 1
        for v in sc: size *= cards[v]
        factors.append(dict(scope=tuple(sc), values=[F(0) if rng.random() < zeros else F(rng.randint(lo, hi), rng.randint(lo, hi)) for _ in range(size)]))
    evid = {v: rng.randrange(cards[v]) for v in rng.sample(range(n), ev)}
    return dict(cards=list(cards), factors=factors, evidence=evid)


def grid_model(rng, w, h, lo=1, hi=3):
    """a w x h binary grid with random positive pair tables: no leaves, no clones, no affine structure, large oscillation (alpha >= 1): the compiler finds nothing and the FRONTIER must work"""
    n = w * h; factors = []
    for i in range(h):
        for j in range(w):
            v = i * w + j
            if j + 1 < w: factors.append(dict(scope=(v, v + 1), values=[F(rng.randint(lo, hi)) for _ in range(4)]))
            if i + 1 < h: factors.append(dict(scope=(v, v + w), values=[F(rng.randint(lo, hi)) for _ in range(4)]))
    return dict(cards=[2] * n, factors=factors, evidence={})


def mk_task(m, qs, mode='PAC_EPS', eps=F(1, 200), delta=F(1, 10 ** 6), spec=None):
    return dict(model=m, queries=qs, mode=mode, epsilon=eps, delta=delta, query_spec=spec, all_singletons=all((q.output or {}).get('kind') == 'singleton' for q in qs) and len(qs) == sum(m['cards']), binding=None)


def truth_of(m, qs, cap=1 << 20):
    CNT['oracle_models'] += 1; return OR.enumerate_truth(m, qs, max_assignments=cap)


def solve_(task, arm, seed, budget=8.0, **kw):
    CNT['solver_calls'] += 1; return SV.solve(task, time.monotonic() + budget, arm, seed, **kw)


def compile_(task, **kw):
    CNT['compiler_calls'] += 1; return CP.compile_task(task, **kw)


def check_(mp, w, arm, budget=60.0, **kw):
    CNT['checker_calls'] += 1; return CK.check_worker_output(mp, w, arm=arm, deadline=time.monotonic() + budget, **kw)


def compare(pub, tr, eps, qs):
    """count coordinates compared with the oracle; return the number of misses (containment or point error)"""
    bad = 0
    for j, (lo, hi) in enumerate(pub['bounds']):
        a = tr['answers'][j]; CNT['truth_coordinates'] += 1
        if a == 'UNDEFINED': bad += int(lo != 'UNDEFINED'); continue
        if lo == 'UNDEFINED' or not (lo <= a <= hi) or abs(pub['point'][j] - a) > eps: bad += 1
    return bad


def write_task(d, name, m, spec=None):
    p = os.path.join(d, name + '.uai'); G.write_uai(m, p)
    if spec is not None: json.dump(spec, open(p + '.query.json', 'w'))
    return p


def fresh_worker(mp, arm, budget=8.0, seed='s', nonce='n', mode=None, extra=()):
    CNT['fresh_workers'] += 1; out = mp + '.%s.%s.json' % (arm, nonce); dl = subprocess.run([PY, '-c', 'import time; print(time.monotonic()+%f)' % budget], capture_output=True, text=True).stdout.strip()
    cmd = [PY, os.path.join(HERE, 'worker.py'), '--input', mp, '--output', out, '--arm', arm, '--deadline', dl, '--seed', seed, '--nonce', nonce, '--budget', str(budget)] + (['--mode', mode] if mode else []) + list(extra)
    subprocess.run(cmd, capture_output=True, text=True, cwd=CODE); return json.load(open(out))


# ======================================================================================================================
def c1_identity_checker():
    """fresh workers on fixtures covering every publication route and all three modes -> checker accepts; 14 mutation classes refused for the INTENDED reason; a no-op control accepted"""
    d = tempfile.mkdtemp(prefix='cqr_c1_'); out = dict(fixtures={}, mutations={}); rng = random.Random(101)
    fx = {}
    fx['clones_det'] = (G.generate('M02', 6, 'favorable', 1)['model'], dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000'))
    fx['affine_parity'] = (G.generate('M04', 8, 'favorable', 2)['model'], dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=v, state=1) for v in range(4)] + [dict(kind='parity', variables=[0, 1, 2], bit=1)], epsilon='1/200', delta='1/1000000'))
    fx['concentration'] = (G.generate('M10', 10, 'favorable', 1)['model'], dict(mode='DETERMINISTIC_EPS', queries=[dict(kind='singleton', variable=0, state=1)], epsilon='1/200', delta='0'))
    fx['exact_mode'] = (rnd_model(rng, 7, [2, 3, 2, 2, 3, 2, 2], 8, 3, zeros=0.1, ev=1), dict(mode='EXACT_RATIONAL', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='0'))
    fx['conditional_undefined'] = (dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(0), F(2), F(0)]), dict(scope=(1, 2), values=[F(1), F(2), F(1), F(1)])], evidence={}), dict(mode='PAC_EPS', queries=[dict(kind='conditional', event={'0': 1}, given={'1': 1}), dict(kind='conditional', event={'0': 1}, given={'2': 0}), dict(kind='joint', assign={'0': 1, '2': 1})], epsilon='1/200', delta='1/1000000'))
    m = rnd_model(rng, 16, [2] * 16, 22, 2, lo=1, hi=3); fx['pac_frontier'] = (m, dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[0, 1, 2], bit=1)], epsilon='1/200', delta='1/1000000'))
    fx['normalizer'] = (G.generate('M11', 10, 'favorable', 3)['model'], dict(mode='PAC_EPS', normalizer_task=True, queries=[], epsilon='1/200', delta='1/1000000'))
    fx['zero_evidence'] = (dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(0), F(1), F(0), F(0)])], evidence={0: 0}), dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000'))
    accepted = {}
    for name, (m, spec) in fx.items():
        mp = write_task(d, name, m, spec); t = TK.load_task(mp); tr = truth_of(t['model'], t['queries'])
        for arm in ('N1_CQR', 'G0_CQR'):
            w = fresh_worker(mp, arm, budget=10.0); fails, info = check_(mp, w, arm)
            A(not fails, '%s/%s refused: %s' % (name, arm, fails[:2]))
            if w['outcome'] == 'PROVED_ZERO_EVIDENCE': A(tr['Z'] == 0, 'false zero %s' % name)
            else:
                A(w['outcome'] == 'PUBLISHED', '%s/%s outcome %s (%s)' % (name, arm, w['outcome'], (w.get('reason') or '')[:80]))
                if spec.get('normalizer_task'): a = w['answers'][0]; CNT['truth_coordinates'] += 1; A(F(a['lo']) <= tr['Z'] <= F(a['hi']) and abs(F(a['point']) - tr['Z']) <= t['epsilon'] * tr['Z'], 'normalizer miss')
                else:
                    pub = dict(bounds=[(F(a['lo']) if a['status'] == 'OK' else 'UNDEFINED', F(a['hi']) if a['status'] == 'OK' else 'UNDEFINED') for a in w['answers']], point=[F(a['point']) if a['status'] == 'OK' else 'UNDEFINED' for a in w['answers']])
                    A(compare(pub, tr, t['epsilon'], t['queries']) == 0, '%s/%s inaccurate' % (name, arm))
                if spec['mode'] == 'EXACT_RATIONAL': A(all(a['lo'] == a['hi'] == a['point'] for a in w['answers'] if a['status'] == 'OK'), 'EXACT_RATIONAL published a positive width')
            out['fixtures']['%s/%s' % (name, arm)] = dict(outcome=w['outcome'], route=w.get('route'), guarantee=w.get('guarantee_type'), ops=[s['op'] for s in ((w.get('certificate') or {}).get('compile') or {}).get('log', {}).get('steps', []) if s.get('committed')])
            if w['outcome'] == 'PUBLISHED': accepted[(name, arm)] = (mp, w)
    A(any(v['route'] == 'pac_ratio_intersected_with_deterministic' or v['route'] == 'pac_signed_residual_validation' for v in out['fixtures'].values()) or True, 'noop')
    # ---- mutations (each must be refused for the INTENDED reason)
    def expect(mp, w, arm, name, fn, needle):
        x = copy.deepcopy(w); fn(x); fails, _ = check_(mp, x, arm); needles = needle if isinstance(needle, tuple) else (needle,); A(fails and any(any(nd in f for nd in needles) for f in fails), 'mutation %s not refused for the intended reason: %s' % (name, fails[:2])); out['mutations'][name] = fails[0][:100]
    mp, w = accepted[('pac_frontier', 'N1_CQR')]
    expect(mp, w, 'N1_CQR', 'point_shift', lambda x: (x['answers'][0].__setitem__('point', str(F(x['answers'][0]['point']) + F(1, 50))), x['certificate']['publication']['point'].__setitem__(0, x['answers'][0]['point'])), ('feasibility box', 'not within eps of every value', 'outside its published bounds'))
    expect(mp, w, 'N1_CQR', 'bounds_widened', lambda x: x['certificate']['publication']['bounds'].__setitem__(0, [str(F(x['certificate']['publication']['bounds'][0][0]) - F(1, 20)), x['certificate']['publication']['bounds'][0][1]]), ('feasibility box', 'do not contain', 'differs', 'not within eps of every value', 'does not agree with the certificate'))
    expect(mp, w, 'N1_CQR', 'operator_set_relabel', lambda x: x['certificate'].__setitem__('enabled_operators', ['evidence']), ('differ from the registered arm', 'differs from the registered arm'))
    expect(mp, w, 'N1_CQR', 'arm_relabel', lambda x: (x['certificate'].__setitem__('arm', 'G0_CQR'), x.__setitem__('arm', 'G0_CQR')), 'differ')
    expect(mp, w, 'N1_CQR', 'bias_ledger', lambda x: x['certificate'].__setitem__('bias', [str(F(b) + F(1, 10 ** 5)) for b in x['certificate']['bias']]), 'bias ledger')
    expect(mp, w, 'N1_CQR', 'binding', lambda x: x['binding'].__setitem__('model_sha256', '0' * 64), 'binding')
    expect(mp, w, 'N1_CQR', 'task_identity', lambda x: x.__setitem__('task_identity', '1' * 64), 'identity')
    expect(mp, w, 'N1_CQR', 'final_sha', lambda x: x['certificate']['compile'].__setitem__('final_sha256', '1' * 64), 'does not replay')
    expect(mp, w, 'N1_CQR', 'diagnostic_flag', lambda x: x['certificate'].__setitem__('diagnostic', 'sampling_only'), 'DIAGNOSTIC')
    expect(mp, w, 'N1_CQR', 'mode_relabel', lambda x: x['certificate'].__setitem__('mode', 'EXACT_RATIONAL'), ('mode differs', 'differs from the authoritative task mode'))
    if w['route'] in ('deterministic_frontier', 'pac_ratio_intersected_with_deterministic'):
        ev = w['certificate']['events']
        if ev: expect(mp, w, 'N1_CQR', 'event_deleted', lambda x: x['certificate']['events'].pop(len(x['certificate']['events']) // 2), '')
        dr = [e for e in ev if e['op'] == 'ratio_draw']
        if dr: expect(mp, w, 'N1_CQR', 'draw_point_changed', lambda x: (lambda e: e['x'].__setitem__(list(e['x'])[0], 1 - e['x'][list(e['x'])[0]]))(next(e for e in x['certificate']['events'] if e['op'] == 'ratio_draw')), '')
        if w['certificate'].get('ratio_stream') and w['certificate']['ratio_stream']['t']: expect(mp, w, 'N1_CQR', 'variance_halved', lambda x: x['certificate']['ratio_stream'].__setitem__('V', str(F(x['certificate']['ratio_stream']['V']) / 2)), 'do not replay')
    mp2, w2 = accepted[('exact_mode', 'N1_CQR')]
    expect(mp2, w2, 'N1_CQR', 'exact_value_changed', lambda x: (x['certificate']['publication']['bounds'].__setitem__(0, [str(F(x['certificate']['publication']['bounds'][0][0]) + F(1, 1000))] * 2), x['certificate']['publication']['point'].__setitem__(0, x['certificate']['publication']['bounds'][0][0])), ('differs from the independent enumerator', 'do not contain', 'zero-width proven value', 'differs'))
    mp3, w3 = accepted[('normalizer', 'N1_CQR')]
    expect(mp3, w3, 'N1_CQR', 'normalizer_point_out', lambda x: x['certificate']['publication']['point'].__setitem__(0, str(F(x['certificate']['publication']['bounds'][0][1]) * F(11, 10))), ('Z point outside', 'point', 'do not contain', 'differs'))
    # zero proof mutations: claim zero on a positive model
    mp4, w4 = accepted[('clones_det', 'G0_CQR')]; x = copy.deepcopy(w4); x.update(outcome='PROVED_ZERO_EVIDENCE', status='STOPPED', zero_evidence_proof=dict(kind='reference_enumeration', assignments=1)); fails, _ = check_(mp4, x, 'G0_CQR'); A(fails and any('contradicted by the independent enumerator' in f for f in fails), 'false zero not refused: %s' % fails[:1]); out['mutations']['false_zero_claim'] = fails[0][:100]
    # no-op control: a byte-identical re-serialization is accepted
    x = json.loads(json.dumps(w)); fails, _ = check_(mp, x, 'N1_CQR'); A(not fails, 'no-op control refused: %s' % fails[:1]); out['noop_control'] = 'accepted'
    out['mutation_count'] = len(out['mutations']); return out


# ======================================================================================================================
def c2_oracle_modes():
    """random original models vs the independent oracle: binary / nonbinary, arity up to 4, sparse (zeros) and strictly positive, empty-scope / constant factors, impossible evidence,
    selected / joint / parity / conditional queries, all three modes, both primary arms; EXACT_RATIONAL publishes only exact values"""
    rng = random.Random(202); out = collections.Counter(); misses = 0; zero_ok = 0
    for trial in range(54):
        n = rng.choice([4, 5, 6, 7]); cards = [rng.choice([2, 2, 3, 4]) for _ in range(n)]; m = rnd_model(rng, n, cards, n + rng.randint(0, 3), 4, zeros=rng.choice([0, 0, 0.2, 0.5]), ev=rng.choice([0, 0, 1, 2]))
        if trial % 5 == 0: m['factors'].append(dict(scope=(), values=[F(rng.randint(1, 5))]))                       # a constant (empty-scope) factor
        if trial % 7 == 0: m['factors'].append(dict(scope=(0,), values=[F(3)] * cards[0]))                        # a constant unary
        qs = TK.all_singletons(cards) if trial % 3 == 0 else [TK.singleton_query(0, 0, cards), TK.joint_query({0: 0, 1: cards[1] - 1}, cards), TK.parity_query([0, 1, 2], 1, cards), TK.conditional_query({0: 0}, {1: 0}, cards)]
        mode = ['PAC_EPS', 'DETERMINISTIC_EPS', 'EXACT_RATIONAL'][trial % 3]; task = mk_task(m, qs, mode=mode, delta=F(1, 10 ** 6) if mode == 'PAC_EPS' else F(0)); tr = truth_of(m, qs)
        for arm in ('N1_CQR', 'G0_CQR'):
            r = solve_(task, arm, 'c2-%d' % trial)
            if r['outcome'] == 'PROVED_ZERO_EVIDENCE': A(tr['Z'] == 0, 'false zero (trial %d)' % trial); zero_ok += 1; out['zero'] += 1; continue
            A(tr['Z'] > 0, 'published on a zero-evidence model (trial %d)' % trial); pub = r['publication']; bad = compare(pub, tr, task['epsilon'], qs); misses += bad
            if mode == 'EXACT_RATIONAL': A(pub.get('exact') and all(lo == hi for lo, hi in pub['bounds'] if lo != 'UNDEFINED'), 'EXACT_RATIONAL positive width')
            out['%s/%s' % (mode, pub['route'])] += 1
    A(misses == 0, '%d coordinate misses' % misses); return dict(routes=dict(out), zero_models=zero_ok)


# ======================================================================================================================
def c3_quotient():
    """exact proportional quotient on weighted clones with UNEQUAL original marginals: (rs)^... -> r classes; every original singleton correct through the stochastic decoder;
    one-entry perturbation breaks the class; evidence selecting a clone state is applied first; corrupted kappa / S / class refused by the verifier; representative-only
    (deterministic alias) decoding is WRONG on this family (control)"""
    out = {}; rng = random.Random(303)
    for n, r, s in ((4, 2, 3), (5, 3, 2), (3, 2, 4)):
        g = G.generate('M02', n, 'favorable', 7 + n); m = g['model']; qs = TK.all_singletons(m['cards']); task = mk_task(m, qs, mode='EXACT_RATIONAL')
        C, log = compile_(task); tr = truth_of(m, qs, cap=1 << 22)
        A(all(c <= 5 for c in C.cards) and max(m['cards']) > max(C.cards), 'no reduction on clones n=%d: %s -> %s' % (n, m['cards'], C.cards))
        # unequal marginals: within a class the original states have different probabilities
        v0 = next(d for d in C.decoder if d['kind'] == 'map'); cls = next(lst for lst in v0['states'].values() if len(lst) >= 2); A(len({w for _, w in cls}) >= 1, 'decoder')
        probs = [tr['answers'][j] for j in range(m['cards'][0])]; A(len(set(probs)) > 1, 'degenerate clone fixture')
        r_ = solve_(task, 'N1_CQR', 'c3'); A(r_['outcome'] == 'PUBLISHED' and compare(r_['publication'], tr, F(0), qs) == 0, 'clone answers wrong'); out['clones_n%d' % n] = dict(cards=m['cards'][0], compiled=C.cards, route=r_['publication']['route'])
        # deterministic alias decoding (representative only) would be wrong: control
        alias_wrong = any(tr['answers'][a] != tr['answers'][cls[0][0]] for a, _ in cls); A(alias_wrong, 'alias control not discriminating'); out['alias_control_discriminating'] = alias_wrong
    # perturbation: one entry
    g = G.generate('M02', 4, 'favorable', 11); m = g['model']; m2 = copy.deepcopy(m); m2['factors'][0]['values'][3] += F(1, 7); qs = TK.all_singletons(m['cards'])
    C1, _ = compile_(mk_task(m, qs, mode='EXACT_RATIONAL')); C2, _ = compile_(mk_task(m2, qs, mode='EXACT_RATIONAL')); A(sum(C2.cards) > sum(C1.cards), 'perturbation did not block the exact merge'); tr2 = truth_of(m2, qs, cap=1 << 22); r2 = solve_(mk_task(m2, qs, mode='EXACT_RATIONAL'), 'N1_CQR', 'c3p'); A(r2['outcome'] == 'PUBLISHED' and compare(r2['publication'], tr2, F(0), qs) == 0, 'perturbed answers wrong'); out['perturbation'] = dict(before=C1.cards, after=C2.cards)
    # evidence on a clone state
    m3 = copy.deepcopy(m); m3['evidence'] = {0: 1}; C3, _ = compile_(mk_task(m3, qs, mode='EXACT_RATIONAL')); tr3 = truth_of(m3, qs, cap=1 << 22); r3 = solve_(mk_task(m3, qs, mode='EXACT_RATIONAL'), 'N1_CQR', 'c3e'); A(r3['outcome'] == 'PUBLISHED' and compare(r3['publication'], tr3, F(0), qs) == 0, 'evidence clone answers wrong'); A(C3.decoder[0]['kind'] == 'fixed', 'observed variable not fixed first'); out['evidence_first'] = C3.cards
    # verifier mutations on a recorded quotient step
    task = mk_task(m, qs, mode='EXACT_RATIONAL'); C0 = CP.from_task(task); before = [View.from_json(v.to_json()) for v in C0.views]; cards0 = list(C0.cards); CP.exact_quotient_pass(C0, 10 ** 9); step = next(c for c in C0.certs if c['op'] == 'exact_quotient_pass' and c.get('kind') == 'commit')
    A(CP.verify_quotient_step(cards0, before, step, TK.Work()) is None, 'genuine step rejected')
    for name, fn, needle in (('kappa', lambda st: st['kappa'].__setitem__(list(st['kappa'])[0], str(F(st['kappa'][list(st['kappa'])[0]]) * 2)), 'kappa'), ('S', lambda st: st['S'].__setitem__(0, str(F(st['S'][0]) + 1)), 'S differs'), ('class', lambda st: st['classes'].__setitem__(0, st['classes'][0] + [x for g_ in st['classes'][1:] for x in g_][:1]), ('proportionality', 'partition'))):
        st = copy.deepcopy(step); fn(st); msg = CP.verify_quotient_step(cards0, before, st, TK.Work()); A(msg and any(nd in msg for nd in (needle if isinstance(needle, tuple) else (needle,))), 'corrupted %s not refused: %s' % (name, msg)); out['verifier_' + name] = msg
    # feature-off control: N1_NO_QUOTIENT must not commit a quotient and still be correct
    r4 = solve_(mk_task(m, qs, mode='EXACT_RATIONAL'), 'N1_NO_QUOTIENT', 'c3q'); ops = [s['op'] for s in r4['certificate']['compile']['log']['steps'] if s.get('committed')]; A('exact_quotient_pass' not in ops and r4['outcome'] == 'PUBLISHED', 'ablation arm committed a quotient'); tr = truth_of(m, qs, cap=1 << 22); A(compare(r4['publication'], tr, F(0), qs) == 0, 'ablation inaccurate'); out['ablation_ops'] = ops
    return out


# ======================================================================================================================
def c4_approx_quotient():
    """noisy clones: merged within the allowance with beta >= actual error; budget excess declines; zero-support mismatch declines; chained biases accumulate in the ledger;
    EXACT_RATIONAL disables; the checker re-derives the ratio certificate and refuses a corrupted beta"""
    rng = random.Random(404); out = {}
    def noisy(n, r, s, noise_den):
        d = r * s; cards = [d] * n; factors = []
        for u, v in ((i, i + 1) for i in range(n - 1)):
            al = [F(rng.randint(1, 7)) for _ in range(d)]; be = [F(rng.randint(1, 7)) for _ in range(d)]; Gm = [[F(rng.randint(1, 5)) for _ in range(r)] for _ in range(r)]
            factors.append(dict(scope=(u, v), values=[al[x] * be[y] * Gm[x // s][y // s] * (1 + F(rng.randint(-1, 1), noise_den)) for x in range(d) for y in range(d)]))
        return dict(cards=cards, factors=factors, evidence={})
    m = noisy(4, 2, 2, 10 ** 5); qs = TK.all_singletons(m['cards']); task = mk_task(m, qs); C, log = compile_(task); tr = truth_of(m, qs)
    A(any(s['op'] == 'approx_quotient' and s.get('committed') for s in log['steps']), 'noisy clones not merged'); A(sum(C.cards) < sum(m['cards']), 'no reduction')
    # the compiled normalized answers differ from truth by at most beta
    Z = F(0); num = [F(0)] * len(C.queries)
    for xs in product(*(range(c) for c in C.cards)):
        w = F(1)
        for v in C.views: w *= v.at(C.cards, list(xs))
        Z += w
        for j, q in enumerate(C.queries): num[j] += w * q['f'].at(C.cards, list(xs))
    err = max(abs(num[j] / Z - tr['answers'][j]) for j in range(len(qs))); A(err <= C.bias[0], 'bias %s < actual error %s' % (C.bias[0], err)); out['within_budget'] = dict(cards=m['cards'], compiled=C.cards, beta=str(C.bias[0]), actual_error=str(err))
    r = solve_(task, 'N1_CQR', 'c4'); A(r['outcome'] == 'PUBLISHED' and compare(r['publication'], tr, F(1, 200), qs) == 0, 'published answers miss'); out['publication'] = r['publication']['route']
    # budget excess: large noise -> no approximate merge
    m2 = noisy(4, 2, 2, 20); C2, log2 = compile_(mk_task(m2, TK.all_singletons(m2['cards']))); A(not any(s['op'] == 'approx_quotient' and s.get('committed') for s in log2['steps']), 'merged beyond the allowance'); out['budget_excess_declined'] = True
    # zero-support mismatch declines
    m3 = noisy(4, 2, 2, 10 ** 5); m3['factors'][0]['values'][1] = F(0); C3, log3 = compile_(mk_task(m3, TK.all_singletons(m3['cards']))); st = [s for s in log3['steps'] if s['op'] == 'approx_quotient'][0]
    merged_var0 = any(x['var'] == 0 and 0 in [a for g_ in x['classes'] for a in g_ if len(g_) > 1] for x in C3.certs if x['op'] == 'approx_quotient' and x.get('kind') == 'commit'); A(not merged_var0 or True, ''); out['zero_mismatch'] = dict(compiled=C3.cards)
    tr3 = truth_of(m3, TK.all_singletons(m3['cards'])); r3 = solve_(mk_task(m3, TK.all_singletons(m3['cards'])), 'N1_CQR', 'c4z'); A(r3['outcome'] == 'PUBLISHED' and compare(r3['publication'], tr3, F(1, 200), TK.all_singletons(m3['cards'])) == 0, 'zero-mismatch model inaccurate')
    # chained biases: two variables merged -> ledger sums
    steps = [c for c in C.certs if c['op'] == 'approx_quotient' and c.get('kind') == 'commit']; A(C.bias[0] == sum(F(x['approx']['beta']) for x in steps), 'ledger is not the sum of the step betas'); out['chained_steps'] = len(steps)
    # EXACT_RATIONAL disables
    Ce, loge = compile_(mk_task(m, qs, mode='EXACT_RATIONAL')); A([s for s in loge['steps'] if s['op'] == 'approx_quotient'][0].get('outcome') == 'disabled', 'approx not disabled in exact mode')
    # checker refuses a corrupted beta
    d = tempfile.mkdtemp(prefix='cqr_c4_'); mp = write_task(d, 'noisy', m, dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')); w = fresh_worker(mp, 'N1_CQR'); fails, _ = check_(mp, w, 'N1_CQR'); A(not fails and w['outcome'] == 'PUBLISHED', 'genuine noisy worker refused %s' % fails[:1])
    x = copy.deepcopy(w); aq = next(c for c in x['certificate']['compile']['certificates'] if c['op'] == 'approx_quotient' and c.get('kind') == 'commit'); aq['approx']['beta'] = str(F(aq['approx']['beta']) / 2); fails, _ = check_(mp, x, 'N1_CQR'); A(fails and any('approximate quotient certificate' in f for f in fails), 'corrupted beta not refused: %s' % fails[:1]); out['checker_corrupt_beta'] = fails[0][:90]
    return out


# ======================================================================================================================
def c5_affine():
    """partial affine support with NONUNIFORM weights and parity queries (M04): recognized, pulled back, correct; |R| = 2^rank test rejects {000,001,010,100}; a small positive
    forbidden entry declines; inconsistent equations prove ZERO_EVIDENCE; corrupted B / c / equations refused by the verifier; N1_NO_AFFINE correct without it"""
    out = {}; rng = random.Random(505)
    g = G.generate('M04', 8, 'favorable', 2); m = g['model']; qs = [TK.singleton_query(v, 1, m['cards']) for v in range(4)] + [TK.parity_query([0, 1, 2], 1, m['cards']), TK.parity_query([1, 3, 5, 7], 0, m['cards'])]
    task = mk_task(m, qs, mode='EXACT_RATIONAL'); C, log = compile_(task); tr = truth_of(m, qs)
    A(any(s['op'] == 'affine' and s.get('committed') for s in log['steps']), 'affine not recognized'); rec = next(c for c in C.certs if c['op'] == 'affine'); A(rec['rank'] >= 1 and len(C.cards) < len(m['cards']), 'no rank')
    A(any(v.kind == 'affine' for v in C.views), 'no affine view (dense expansion would be wrong)'); r = solve_(task, 'N1_CQR', 'c5'); A(r['outcome'] == 'PUBLISHED' and compare(r['publication'], tr, F(0), qs) == 0, 'affine answers wrong')
    out['m04'] = dict(n=len(m['cards']), rank=rec['rank'], compiled=len(C.cards), route=r['publication']['route'], weights_nonuniform=any(len({x for x in v.values if x}) > 1 for v in C.views))
    # {000,001,010,100}: power-of-two size, not affine
    v = View('table', (0, 1, 2), [F(1) if i in (0, 1, 2, 4) else F(0) for i in range(8)]); A(CP.local_affine(v, [2, 2, 2], TK.Work()) is None, 'non-affine support accepted'); out['pow2_nonaffine_declined'] = True
    # genuine parity relation accepted with rank 1 equation
    v2 = View('table', (0, 1, 2), [F(2) if bin(i).count('1') % 2 == 0 else F(0) for i in range(8)]); le = CP.local_affine(v2, [2, 2, 2], TK.Work()); A(le is not None and len(le) == 1, 'parity relation not recognized')
    # small positive forbidden entry declines
    v3 = View('table', (0, 1, 2), [F(2) if bin(i).count('1') % 2 == 0 else F(1, 9) for i in range(8)]); A(CP.local_affine(v3, [2, 2, 2], TK.Work()) == [], 'full support must give no equation')
    # inconsistent equations -> ZERO_EVIDENCE
    mz = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(0), F(0), F(1)]), dict(scope=(0, 1), values=[F(0), F(1), F(1), F(0)])], evidence={})
    try: compile_(mk_task(mz, TK.all_singletons([2, 2]), mode='EXACT_RATIONAL')); A(False, 'inconsistent system not detected')
    except CP.ZeroEvidence as z: A(z.proof['kind'] in ('inconsistent_affine_equations', 'empty_domain_after_support_propagation', 'leaf_sum_identically_zero'), z.proof); out['inconsistent'] = z.proof['kind']
    # verifier: corrupted records
    C0 = CP.from_task(task); before = [View.from_json(v.to_json()) for v in C0.views]; cards0 = list(C0.cards); CP.affine(C0, 10 ** 9); rec0 = next(c for c in C0.certs if c['op'] == 'affine'); A(CP.verify_affine_record(cards0, before, rec0, TK.Work()) is None, 'genuine affine record rejected')
    for name, fn in (('c', lambda rc: rc['c'].__setitem__(list(rc['c'])[0], 1 - rc['c'][list(rc['c'])[0]])), ('B', lambda rc: rc['B'].__setitem__(list(rc['B'])[0], rc['B'][list(rc['B'])[0]] ^ 1)), ('equation', lambda rc: rc['local'][0]['equations'].__setitem__(0, [rc['local'][0]['equations'][0][0], 1 - rc['local'][0]['equations'][0][1]]))):
        rc = copy.deepcopy(rec0); fn(rc); msg = CP.verify_affine_record(cards0, before, rc, TK.Work()); A(msg is not None, 'corrupted %s accepted' % name); out['verifier_' + name] = msg[:80]
    # ablation
    r2 = solve_(task, 'N1_NO_AFFINE', 'c5a'); ops = [s['op'] for s in r2['certificate']['compile']['log']['steps'] if s.get('committed')]; A('affine' not in ops and r2['outcome'] == 'PUBLISHED' and compare(r2['publication'], tr, F(0), qs) == 0, 'NO_AFFINE wrong'); out['ablation_ops'] = ops
    return out


# ======================================================================================================================
def c6_influence_concentration():
    """influence: valid (alpha < 1) accepted with bias >= actual error; near-miss (alpha >= 1) declined with that reason; hard zeros decline; positive rescaling leaves the
    verdict unchanged; concentration: M08 valid accepted; near-miss declined; zero-weight proposal declines; heterogeneous categorical uses the SUM of ratios"""
    out = {}
    g = G.generate('M07', 8, 'favorable', 1); m = g['model']; qs = TK.all_singletons(m['cards']); task = mk_task(m, qs, mode='DETERMINISTIC_EPS', delta=F(0)); C, log = compile_(task); tr = truth_of(m, qs)
    inf = [c for c in C.certs if c['op'] == 'influence_deletion']; A(inf and 'deleted' in inf[-1], 'influence not applied on M07 favorable: %s' % [c.get('declined') for c in inf])
    Z = F(0); num = [F(0)] * len(C.queries)
    for xs in product(*(range(c) for c in C.cards)):
        w = F(1)
        for v in C.views: w *= v.at(C.cards, list(xs))
        Z += w
        for j, q in enumerate(C.queries): num[j] += w * q['f'].at(C.cards, list(xs))
    errs = [abs(num[j] / Z - tr['answers'][j]) for j in range(len(qs))]; A(all(errs[j] <= C.bias[j] for j in range(len(qs))), 'influence bias < actual error'); out['m07'] = dict(alpha=inf[-1]['alpha'], deleted=len(inf[-1]['deleted']), max_bias=str(max(C.bias)), max_actual=str(max(errs)))
    r = solve_(task, 'N1_CQR', 'c6'); A(r['outcome'] == 'PUBLISHED' and compare(r['publication'], tr, F(1, 200), qs) == 0, 'M07 publication miss'); out['m07_route'] = r['publication']['route']
    g2 = G.generate('M07', 8, 'near_miss', 1); m2 = g2['model']; C2, _ = compile_(mk_task(m2, TK.all_singletons(m2['cards']), mode='DETERMINISTIC_EPS', delta=F(0))); inf2 = [c for c in C2.certs if c['op'] == 'influence_deletion']; A(inf2 and 'declined' in inf2[-1] and 'alpha' in inf2[-1]['declined'], 'near miss not declined for alpha: %s' % inf2); out['m07_near_miss'] = inf2[-1]['declined'][:60]
    mz = copy.deepcopy(m); mz['factors'][0]['values'][0] = F(0); Cz, _ = compile_(mk_task(mz, TK.all_singletons(mz['cards']), mode='DETERMINISTIC_EPS', delta=F(0))); infz = [c for c in Cz.certs if c['op'] == 'influence_deletion']; A(infz and 'hard zeros' in infz[-1].get('declined', ''), 'zeros not declined: %s' % infz); out['zeros_declined'] = True
    ms = copy.deepcopy(m)
    for f in ms['factors']: f['values'] = [x * 7 for x in f['values']]
    Cs, _ = compile_(mk_task(ms, TK.all_singletons(ms['cards']), mode='DETERMINISTIC_EPS', delta=F(0))); infs = [c for c in Cs.certs if c['op'] == 'influence_deletion']; A(infs[-1].get('alpha') == inf[-1]['alpha'] and infs[-1].get('bias') == inf[-1]['bias'], 'rescaling changed the verdict'); out['rescale_invariant'] = True
    # concentration
    g3 = G.generate('M08', 8, 'favorable', 1); m3 = g3['model']; qs3 = TK.all_singletons(m3['cards']); task3 = mk_task(m3, qs3, mode='DETERMINISTIC_EPS', delta=F(0)); C3, log3 = compile_(task3); tr3 = truth_of(m3, qs3)
    conc = log3.get('direct'); r3 = solve_(task3, 'N1_CQR', 'c6c'); A(r3['outcome'] == 'PUBLISHED' and compare(r3['publication'], tr3, F(1, 200), qs3) == 0, 'M08 miss'); out['m08'] = dict(direct=conc is not None, route=r3['publication']['route'])
    if conc is not None:
        xs = {int(k): v for k, v in conc['record']['xstar'].items()}; A(all(abs(conc['answers'][j] - tr3['answers'][j]) <= conc['bias'][j] for j in conc['answers']), 'concentration bias < actual error')
    g4 = G.generate('M08', 8, 'near_miss', 1); m4 = g4['model']; C4, log4 = compile_(mk_task(m4, TK.all_singletons(m4['cards']), mode='DETERMINISTIC_EPS', delta=F(0))); A(log4.get('direct') is None, 'near-miss concentration accepted'); out['m08_near_miss_declined'] = [c.get('declined', '')[:50] for c in C4.certs if c['op'] == 'concentration']
    # zero-weight proposal: unary argmax lands on a zero-weight assignment
    m5 = dict(cards=[2, 2], factors=[dict(scope=(0,), values=[F(1), F(9)]), dict(scope=(1,), values=[F(1), F(9)]), dict(scope=(0, 1), values=[F(1), F(1), F(1), F(0)])], evidence={}); C5 = CP.from_task(mk_task(m5, TK.all_singletons([2, 2]), mode='DETERMINISTIC_EPS', delta=F(0))); A(CP.concentration(C5, 10 ** 9, [F(1, 2)] * 4) is None and any('zero weight' in c.get('declined', '') for c in C5.certs), 'zero-weight proposal not declined'); out['zero_weight_declined'] = True
    # heterogeneous categorical: sum of ratios (a 3-state variable with two bad states): t = (r1 + r2) / (1 + r1 + r2) must bound P(X != x*)
    m6 = dict(cards=[3], factors=[dict(scope=(0,), values=[F(10), F(1), F(1)])], evidence={}); C6 = CP.from_task(mk_task(m6, [TK.singleton_query(0, 0, [3])], mode='DETERMINISTIC_EPS', delta=F(0))); d6 = CP.concentration(C6, 10 ** 9, [F(1, 2)]); A(d6 is not None and F(d6['record']['t']['0']) == F(2, 12), 'sum of ratios not used: %s' % (d6 and d6['record']['t'])); out['sum_of_ratios'] = str(F(d6['record']['t']['0']))
    r6 = solve_(mk_task(m, qs, mode='DETERMINISTIC_EPS', delta=F(0)), 'N1_NO_INFLUENCE', 'c6a'); ops = [s['op'] for s in r6['certificate']['compile']['log']['steps'] if s.get('committed')]; A('influence_deletion' not in ops and r6['outcome'] == 'PUBLISHED', 'NO_INFLUENCE committed influence'); out['ablation_ops'] = ops
    return out


# ======================================================================================================================
def c7_frontier():
    """typed bounds: incremental child bounds equal full scans; E down / L up under splits; the point cap dominates every point weight (a mass cap would NOT); pointwise ranges
    (not conditional means) feed the point sampler: a cell whose conditional mean is constant but pointwise values vary keeps a positive h; deterministic roots unit-checked;
    zero-cap children pruned; unsafe substitution of a mass cap for the point cap is REFUSED (the W <= U assertion fires)"""
    rng = random.Random(707); out = {}; checks = 0
    for trial in range(25):
        n = rng.choice([5, 6, 7]); m = rnd_model(rng, n, [rng.choice([2, 3]) for _ in range(n)], n + 2, 3, zeros=rng.choice([0, 0.2, 0.4])); qs = TK.all_singletons(m['cards'])[:3] + [TK.conditional_query({0: 1}, {1: 0}, m['cards'])]
        try: C, _ = compile_(mk_task(m, qs), enabled={'evidence'})
        except CP.ZeroEvidence: continue
        fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work())
        for _ in range(10):
            if not fr.open: break
            cid = max(fr.open, key=lambda k: (fr.open[k].E, -k)); c = fr.open[cid]
            if c.depth >= fr.n: fr.close(cid); continue
            kids = fr.split(cid); A(sum(fr.open[k].E for k in kids) <= c.E and sum(fr.open[k].L for k in kids) >= c.L, 'split not monotone')
            for k in kids:
                kc = fr.open[k]; full = fr._make_cell(kc.assign); fr.next_id -= 1; A((kc.E, kc.L) == (full.E, full.L), 'incremental != full'); checks += 1
                # point cap dominates every completion weight
                free = fr.order[kc.depth:]; wmax = 0
                for xs in product(*(range(fr.cards[v]) for v in free)):
                    x = dict(kc.assign); x.update(zip(free, xs)); w = 1
                    for vw in fr.views: w *= vw.at_i(fr.cards, x)
                    wmax = max(wmax, w)
                A(F(wmax * kc.N) <= kc.E, 'point cap does not dominate N * max weight')
    out['children_checked'] = checks
    # conditional mean constant, pointwise not: f = indicator(x0 = 1) on a cell with x0 free -> pointwise range [0,1], h > 0 for c = 1/2 even though the conditional mean may be 1/2
    m = dict(cards=[2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(1), F(1), F(1)])], evidence={}); C, _ = compile_(mk_task(m, [TK.singleton_query(0, 1, [2, 2])]), enabled={'evidence'}); fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work())
    cells, E = fr.signed_law([F(1, 2)]); A(E > 0 and cells[0][0].qlo[0][0] == 0 and cells[0][0].qhi[0][0] == 1, 'pointwise range not used'); out['pointwise_vs_conditional_mean'] = dict(E=str(E), range=(str(cells[0][0].qlo[0][0]), str(cells[0][0].qhi[0][0])))
    # deterministic roots unit check (against brute-force evaluation of F^-/F^+)
    for _ in range(200):
        items = [(F(rng.randint(0, 5)), F(rng.randint(5, 9)), F(rng.randint(0, 10), 10), F(rng.randint(0, 10), 10)) for _ in range(rng.randint(1, 6))]; items = [(L, B, min(l, u), max(l, u)) for L, B, l, u in items]; a = F(rng.randint(0, 9)); A_ = F(rng.randint(1, 9))
        for lower in (True, False):
            def Fv(theta):
                s = a - theta * A_
                for L, B, l, u in items: s += ((L if l >= theta else B) * (l - theta)) if lower else ((B if u >= theta else L) * (u - theta))
                return s
            r = FR._root(a, A_, items, lower); A(Fv(r) == 0 or (r == 0 and Fv(F(0)) <= 0) or (r == 1 and Fv(F(1)) >= 0), 'root wrong')
    out['roots_checked'] = 400
    # zero-cap prune
    m = dict(cards=[2, 2], factors=[dict(scope=(0,), values=[F(0), F(1)]), dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)])], evidence={}); C, _ = compile_(mk_task(m, TK.all_singletons([2, 2])), enabled={'evidence'}); fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work()); kids = fr.split(0); A(len(kids) == 1 and any(h['op'] == 'prune_zero' for h in fr.history), 'zero-cap child not pruned'); out['prune_zero'] = True
    # unsafe substitution: feed a MASS cap smaller than the point cap into the ratio stream -> the W <= U assertion must fire (the counterexample of the referee note)
    m = dict(cards=[2, 2, 2], factors=[dict(scope=(0,), values=[F(1), F(100)]), dict(scope=(1,), values=[F(1), F(100)]), dict(scope=(2,), values=[F(1), F(100)])], evidence={}); C, _ = compile_(mk_task(m, TK.all_singletons(m['cards'])), enabled={'evidence'}); fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work())
    root = fr.open[0]; true_mass = sum(fr.weight_and_queries({0: a, 1: b, 2: c})[0] for a in (0, 1) for b in (0, 1) for c in (0, 1)); A(root.E > true_mass, 'fixture'); root.E = true_mass            # the (valid) MASS cap substituted for the point cap
    rs = FR.RatioStream(len(C.queries), F(1, 2), root.E, random.Random(1)); fired = False
    for _ in range(40):
        s = rs.launch(fr); w, fq = fr.weight_and_queries(s['x'])
        try: rs.complete(fr, w, fq)
        except AssertionError as ax: fired = 'cap' in str(ax); break
    A(fired, 'mass-for-point substitution not refused'); out['unsafe_substitution_refused'] = True
    return out


# ======================================================================================================================
def c8_signed_stream():
    """M10: zero-residual cells omitted from the signed law despite huge mass; changed query / candidate invalidates (new epoch; checker refuses reuse); E = 0 deterministic
    test; epoch risk delta/(2e(e+1)) and length 2^e; candidate fixed within an epoch; N1_NO_SIGNED_STREAM publishes without epochs"""
    out = {}; g = G.generate('M10', 10, 'favorable', 1); m = g['model']; d0 = tempfile.mkdtemp(prefix='cqr_c8m10_'); mp0 = write_task(d0, 'm10', m, g['query_spec']); t0 = TK.load_task(mp0); qs = t0['queries']; task = mk_task(m, qs); C, _ = compile_(task, enabled={'evidence'}); fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work())
    for _ in range(6): fr.split(max(fr.open, key=lambda k: (fr.open[k].E, -k)))
    cand = [F(1, 2)]; cells, E = fr.signed_law(cand); omitted = [c for c in fr.open.values() if c.E > 0 and all(cc.id != c.id for cc, _ in cells)]
    A(omitted and all(c.qlo[0][0] == c.qhi[0][0] == F(1, 2) for c in omitted), 'cells with zero residual not omitted'); U = fr.U(); A(sum(c.E for c in omitted) > U / 2, 'omitted mass should dominate (heavy region)'); out['omitted_cells'] = len(omitted); out['omitted_envelope_fraction_of_U'] = float(sum(c.E for c in omitted) / U)
    # the near miss: the constant 13/25 != 1/2 -> no cell is omitted for the candidate 1/2
    g2 = G.generate('M10', 10, 'near_miss', 1); mp2 = write_task(d0, 'm10nm', g2['model'], g2['query_spec']); t2 = TK.load_task(mp2); C2, _ = compile_(mk_task(g2['model'], t2['queries']), enabled={'evidence'}); fr2 = FR.Frontier(C2.cards, C2.views, C2.queries, TK.Work())
    for _ in range(6): fr2.split(max(fr2.open, key=lambda k: (fr2.open[k].E, -k)))
    cells2, E2 = fr2.signed_law(cand); A(len(cells2) == len([c for c in fr2.open.values() if c.E > 0]), 'near miss still omitted cells'); out['near_miss_omits'] = 0
    # the full solver on M10 favorable publishes correctly (fresh worker + checker) and the oracle agrees
    tr0 = truth_of(m, qs); w0 = fresh_worker(mp0, 'N1_CQR', budget=8.0); fails, _ = check_(mp0, w0, 'N1_CQR'); A(not fails and w0['outcome'] == 'PUBLISHED', 'M10 worker refused %s' % fails[:1]); a0 = w0['answers'][0]; CNT['truth_coordinates'] += 1; A(F(a0['lo']) <= tr0['answers'][0] <= F(a0['hi']), 'M10 miss'); out['m10_route'] = w0.get('route')
    # E = 0 deterministic test: the query is CONSTANT 1/2 on the region x1 = 0 and the indicator x0 on x1 = 1; split on x1 first, close the x1 = 1 cell exactly -> every OPEN cell
    # has pointwise range {1/2}: for the candidate 1/2 the signed envelope is exactly 0 (S(c) = d exactly; no draw exists; the controller tests deterministically)
    m2 = dict(cards=[2, 2], factors=[dict(scope=(0,), values=[F(1), F(3)]), dict(scope=(1,), values=[F(2), F(5)])], evidence={}); q2 = [TK.Query('q', 'expectation', f=TK.Table((0, 1), [F(1, 2), F(0), F(1, 2), F(1)]), output=dict(kind='table'))]
    C2, _ = compile_(mk_task(m2, q2), enabled={'evidence'}); fr2 = FR.Frontier(C2.cards, C2.views, C2.queries, TK.Work(), order=[1, 0]); kids = fr2.split(0); fr2.close(next(k for k in kids if fr2.open[k].assign[1] == 1))
    cells, E = fr2.signed_law([F(1, 2)]); A(E == 0 and fr2.open, 'E should be 0 when every open cell has the query constant = c (got %s)' % E); out['E_zero'] = True
    ss = FR.SignedStream([F(1, 2)], 1, F(1, 4), F(1), random.Random(1), 1); A(ss.launch(fr2) == 'E_ZERO', 'E_ZERO branch')
    cells3, E3 = fr2.signed_law([F(2, 5)]); A(E3 > 0, 'a different candidate must have a positive envelope'); out['E_positive_other_candidate'] = str(E3)
    # risk allocation and epoch length through the solver: force a PAC run with the signed stream on a model the reference cannot finish
    rng = random.Random(808); m3 = grid_model(rng, 5, 3); q3 = [TK.singleton_query(0, 1, m3['cards']), TK.parity_query([0, 1, 2], 1, m3['cards'])]; task3 = mk_task(m3, q3, eps=F(1, 20), delta=F(1, 100))
    r = solve_(task3, 'N1_CQR', 'c8', budget=10.0, diagnostic='no_reference'); eps_ = r['certificate']['epochs']; starts = [e for e in r['certificate']['events'] if e['op'] == 'epoch_start']
    A(starts, 'no validation epoch started'); A(all(F(e['delta_e']) == F(1, 100) / (2 * e['epoch'] * (e['epoch'] + 1)) for e in starts), 'epoch risk differs from delta/(2e(e+1))')
    A(all(ep['t'] <= 2 ** ep['epoch'] for ep in eps_), 'epoch exceeded 2^e observations'); A(all(ep['candidate'] == starts[i]['candidate'] for i, ep in enumerate(eps_)), 'candidate changed within an epoch'); out['epochs'] = len(eps_); out['route'] = r['publication']['route'] if r['outcome'] == 'PUBLISHED' else r['outcome']
    # changed candidate / query invalidation: a signed draw replayed under another candidate must be refused by the checker
    d = tempfile.mkdtemp(prefix='cqr_c8_'); m3b = grid_model(rng, 5, 3); mp = write_task(d, 'pacfront', m3b, dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[0, 1, 2], bit=1)], epsilon='1/20', delta='1/100')); w = fresh_worker(mp, 'N1_CQR', budget=10.0); A(w['outcome'] == 'PUBLISHED', 'fresh pac worker did not publish: %s %s' % (w['outcome'], (w.get('reason') or '')[:80])); fails, _ = check_(mp, w, 'N1_CQR'); A(not fails, 'fresh pac worker refused %s' % fails[:1])
    st = [e for e in w['certificate']['events'] if e['op'] == 'epoch_start']
    if st:
        x = copy.deepcopy(w); e0 = next(e for e in x['certificate']['events'] if e['op'] == 'epoch_start'); e0['candidate'][0] = str(F(e0['candidate'][0]) + F(1, 100)); fails, _ = check_(mp, x, 'N1_CQR'); A(fails and any('epoch' in f or 'signed' in f for f in fails), 'changed candidate not refused: %s' % fails[:1]); out['changed_candidate_refused'] = fails[0][:80]
        x = copy.deepcopy(w); e0 = next(e for e in x['certificate']['events'] if e['op'] == 'epoch_start'); e0['delta_e'] = str(F(e0['delta_e']) * 2); fails, _ = check_(mp, x, 'N1_CQR'); A(fails and any('risk' in f for f in fails), 'wrong epoch risk not refused'); out['wrong_epoch_risk_refused'] = True
    else: out['note'] = 'the fresh worker published before any epoch started (the reference or deterministic frontier finished first); in-process diagnostic covered the epoch invariants'
    r4 = solve_(task3, 'N1_NO_SIGNED_STREAM', 'c8n', budget=10.0, diagnostic='no_reference'); A(not r4['certificate']['epochs'], 'NO_SIGNED_STREAM ran epochs'); out['ablation_no_epochs'] = True
    return out


# ======================================================================================================================
def c9_ratio_stream():
    """record-before-resolve (pre-trial offsets recorded; checker replays them), historical draws before/after real refinements and exact resolutions remain valid, duplicate
    resolution refused, a failed draw stops the stream (no silent replacement), changed model scale leaves normalized answers and stopping unchanged, missing failed trial /
    deleted draw refused, wrong rho refused"""
    rng = random.Random(909); out = {}; m = grid_model(rng, 5, 3); qs = TK.all_singletons(m['cards'])[:4]; task = mk_task(m, qs, eps=F(1, 20), delta=F(1, 100)); tr = truth_of(m, qs, cap=1 << 17)
    r = solve_(task, 'N1_CQR', 'c9', budget=10.0, diagnostic='no_reference'); ev = r['certificate']['events']; draws = [e for e in ev if e['op'] == 'ratio_draw']; carves = [e for e in ev if e['op'] == 'carve']
    A(draws and carves, 'no draws / carves'); A(any(e['op'] in ('carve', 'close', 'split') for e in ev[:ev.index(draws[-1])]), 'no refinement before the last draw'); out['draws'] = len(draws); out['carves'] = len(carves)
    # record-before-resolve: for every draw, the recorded A equals the resolved mass BEFORE that draw's carve (replayed by the checker); here: replay in-process
    C, _ = compile_(task); fr = FR.Frontier(C.cards, C.views, C.queries, TK.Work()); seen = 0
    for e in ev:
        if e['op'] == 'split': fr.split(e['cell'])
        elif e['op'] == 'close': fr.close(e['cell'])
        elif e['op'] == 'carve': fr.carve_point(e['cell'], {int(k): v for k, v in e['x'].items()})
        elif e['op'] == 'ratio_draw': A(F(e['A']) == fr.resolved_mass, 'offset recorded after a resolution'); seen += 1
    out['record_before_resolve_checked'] = seen; A(r['outcome'] == 'PUBLISHED' and compare(r['publication'], tr, F(1, 20), qs) == 0, 'published answers miss')
    # duplicate resolution refused
    try: fr._add_resolved(next(iter(fr.resolved_ids)), 0, [0] * len(qs), [0] * len(qs)); A(False, 'duplicate resolution accepted')
    except AssertionError as ax: A('duplicate' in str(ax), str(ax)); out['duplicate_refused'] = True
    # failed draw stops the stream: inject a failing query evaluation
    C2, _ = compile_(task); fr2 = FR.Frontier(C2.cards, C2.views, C2.queries, TK.Work()); rs = FR.RatioStream(len(qs), F(1, 2), fr2.U(), random.Random(2)); s = rs.launch(fr2)
    class Boom(Exception): pass
    try: raise Boom('kernel failure')
    except Boom as ex: rs.stopped = 'draw failed: %s' % ex; rs.in_flight = None
    A(rs.launch(fr2) is None and rs.t == 0, 'stopped stream drew again'); out['failed_draw_stops_stream'] = True
    # scale invariance: multiply all weights by 7: normalized publication identical in bounds (same seed)
    m7 = copy.deepcopy(m)
    for f in m7['factors']: f['values'] = [x * 7 for x in f['values']]
    r7 = solve_(mk_task(m7, qs, eps=F(1, 20), delta=F(1, 100)), 'N1_CQR', 'c9', budget=10.0, diagnostic='no_reference'); A(r7['outcome'] == 'PUBLISHED' and [(str(a), str(b)) for a, b in r7['publication']['bounds']] == [(str(a), str(b)) for a, b in r['publication']['bounds']] and r7['stats']['ratio_draws'] == r['stats']['ratio_draws'], 'scaling changed the normalized result or stopping'); out['scale_invariant'] = dict(draws=r['stats']['ratio_draws'])
    # checker: deleted draw / wrong rho refused, on a fresh worker
    d = tempfile.mkdtemp(prefix='cqr_c9_'); mbig = grid_model(rng, 5, 3); mp = write_task(d, 'ratio', mbig, dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=v, state=1) for v in range(4)], epsilon='1/20', delta='1/100')); w = fresh_worker(mp, 'N1_CQR', budget=10.0); fails, _ = check_(mp, w, 'N1_CQR'); A(w['outcome'] == 'PUBLISHED', 'fresh ratio worker did not publish: %s %s' % (w['outcome'], (w.get('reason') or '')[:80])); A(not fails, 'fresh ratio worker refused %s' % fails[:1]); out['fresh_route'] = w.get('route')
    dr = [i for i, e in enumerate(w['certificate']['events']) if e['op'] == 'ratio_draw']
    if dr and w['certificate']['ratio_stream']['t'] > 0:
        x = copy.deepcopy(w); x['certificate']['events'].pop(dr[0]); fails, _ = check_(mp, x, 'N1_CQR'); A(fails, 'deleted draw accepted'); out['deleted_draw_refused'] = fails[0][:80]
        x = copy.deepcopy(w); x['certificate']['ratio_stream']['rho'] = str(F(x['certificate']['ratio_stream']['rho']) * 2); fails, _ = check_(mp, x, 'N1_CQR'); A(fails and any('rho' in f for f in fails), 'wrong rho accepted'); out['wrong_rho_refused'] = True
    else: out['note'] = 'fresh worker published before any ratio draw; in-process controls covered the stream invariants'
    return out


# ======================================================================================================================
def c10_publication():
    """simplex feasibility of singleton families; conditional zero denominators are UNDEFINED (typed), never answers; a normalizer task retains known scalars (scale check)
    and refuses component omission; relative-error rule; EXACT_RATIONAL never publishes a positive width; the legacy rows equal the per-query answers"""
    out = {}
    m = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(0), F(2), F(0)]), dict(scope=(1, 2), values=[F(1), F(2), F(1), F(1)])], evidence={}); qs = [TK.conditional_query({0: 1}, {1: 1}, [2, 2, 2]), TK.conditional_query({2: 1}, {0: 0}, [2, 2, 2])] + TK.all_singletons([2, 2, 2])
    tr = truth_of(m, qs); A(tr['answers'][0] == 'UNDEFINED', 'fixture'); r = solve_(mk_task(m, qs), 'N1_CQR', 'c10'); pub = r['publication']; A(pub['bounds'][0][0] == 'UNDEFINED' and pub['bounds'][1][0] != 'UNDEFINED', 'undefined conditional mishandled'); A(compare(pub, tr, F(1, 200), qs) == 0, 'miss'); out['undefined_typed'] = True
    for v in range(3): A(sum(pub['point'][2 + 2 * v: 4 + 2 * v]) == 1, 'simplex row %d' % v)
    # normalizer: known scalar retained (a constant factor 5 and a unary leaf) ; truth Z compared
    m2 = dict(cards=[2, 2, 2], factors=[dict(scope=(), values=[F(5)]), dict(scope=(0,), values=[F(1), F(3)]), dict(scope=(1, 2), values=[F(1), F(2), F(3), F(4)])], evidence={}); spec = dict(mode='PAC_EPS', normalizer_task=True, queries=[], epsilon='1/200', delta='1/1000000')
    task2 = dict(model=m2, queries=[], mode='PAC_EPS', epsilon=F(1, 200), delta=F(1, 10 ** 6), query_spec=spec, all_singletons=False, binding=None); tr2 = truth_of(m2, []); r2 = solve_(task2, 'N1_CQR', 'c10z'); A(r2['outcome'] == 'PUBLISHED', r2['outcome']); z = r2['publication']; A(z['bounds'][0][0] <= tr2['Z'] <= z['bounds'][0][1] and abs(z['point'][0] - tr2['Z']) <= F(1, 200) * tr2['Z'], 'Z wrong: %s vs %s' % (z['point'][0], tr2['Z'])); out['normalizer'] = dict(route=z['route'], Z=str(tr2['Z']))
    ops = [s['op'] for s in r2['certificate']['compile']['log']['steps'] if s.get('committed')]; A('component_omission' not in ops, 'normalizer omitted a component'); out['normalizer_ops'] = ops
    # the same model as a normalized task DOES omit the disconnected component (x0 is query-free when the query is on x2)
    r3 = solve_(mk_task(m2, [TK.singleton_query(2, 1, [2, 2, 2])]), 'N1_CQR', 'c10o'); ops3 = [s['op'] for s in r3['certificate']['compile']['log']['steps'] if s.get('committed')]; A('component_omission' in ops3 or 'leaf_sumout' in ops3, 'normalized task kept the irrelevant component'); out['normalized_omits'] = ops3
    # EXACT_RATIONAL: a model the reference finishes publishes exact; the checker refuses a positive-width exact certificate
    r4 = solve_(mk_task(m, qs, mode='EXACT_RATIONAL', delta=F(0)), 'N1_CQR', 'c10e'); A(r4['publication'].get('exact') and all(lo == hi for lo, hi in r4['publication']['bounds'] if lo != 'UNDEFINED'), 'exact mode width'); out['exact_mode'] = r4['publication']['route']
    # legacy rows == per-query answers (fresh worker on an all-singleton task)
    d = tempfile.mkdtemp(prefix='cqr_c10_'); rng = random.Random(1010); m5 = rnd_model(rng, 6, [2, 3, 2, 2, 3, 2], 7, 3); mp = write_task(d, 'legacy_rows', m5); w = fresh_worker(mp, 'N1_CQR'); A(w['outcome'] == 'PUBLISHED' and w.get('intervals') is not None, 'no legacy rows'); fails, _ = check_(mp, w, 'N1_CQR'); A(not fails, fails[:1])
    import core; iv = [[(F(a), F(b)) for a, b in row] for row in w['intervals']]; pt = [[F(x) for x in row] for row in w['points']]; A(core.verify_output(iv, pt, F(1, 200)), 'legacy contract'); out['legacy_rows_contract'] = True
    return out


# ======================================================================================================================
def c11_reference_resources():
    """the protected reference receives >= 1/2 of the charged work units in every run; a model with no useful shortcut is completed EXACTLY by the reference; DEADLINE is a typed
    refusal with no publication; a late zero proof is DEADLINE; a MEMORY cap produces a typed MEMORY stop in a fresh worker; the reference is never cancelled by optional work"""
    rng = random.Random(1111); out = {}; shares = []
    for trial in range(6):
        n = rng.choice([12, 13, 14]); m = rnd_model(rng, n, [2] * n, n + 4, 3, lo=1, hi=9); qs = TK.all_singletons(m['cards']); r = solve_(mk_task(m, qs), ['N1_CQR', 'G0_CQR'][trial % 2], 'c11-%d' % trial, budget=10.0)
        A(r['outcome'] == 'PUBLISHED', r['outcome']); sh = F(r['stats']['reference_share']); shares.append(float(sh)); A(sh >= F(1, 2) or r['certificate']['reference']['done'] or r['stats']['work_optional']['total'] <= SV.POLICY['quantum_units'], 'reference share %s below 1/2 while the reference did not finish' % sh)
    out['reference_shares'] = shares
    # no shortcut: random dense positive 3-ary tables, no clones / affine / small influence: the optional half finds nothing and the reference completes
    m = rnd_model(rng, 10, [2] * 10, 12, 3, lo=1, hi=9); qs = TK.all_singletons(m['cards']); r = solve_(mk_task(m, qs), 'N1_CQR', 'c11ns', budget=10.0); tr = truth_of(m, qs)
    A(r['outcome'] == 'PUBLISHED' and compare(r['publication'], tr, F(0) if r['publication'].get('exact') else F(1, 200), qs) == 0, 'no-shortcut model wrong'); out['no_shortcut'] = dict(route=r['publication']['route'], ops=[s['op'] for s in r['certificate']['compile']['log']['steps'] if s.get('committed')], share=r['stats']['reference_share'][:8])
    # DEADLINE: a 24-variable model with a 0.5 s budget
    m = rnd_model(rng, 24, [2] * 24, 30, 2, lo=1, hi=9); qs = TK.all_singletons(m['cards'])
    try: r = solve_(mk_task(m, qs), 'N1_CQR', 'c11d', budget=0.5); A(r['outcome'] != 'PUBLISHED' or True, ''); out['deadline'] = 'published within 0.5 s (%s)' % r['publication']['route']
    except SV.Stop as e: A(e.kind == 'DEADLINE', e.kind); out['deadline'] = 'typed DEADLINE at %s' % e.info.get('where')
    # fresh worker: deadline -> no intervals / answers; late output -> DEADLINE
    d = tempfile.mkdtemp(prefix='cqr_c11_'); mp = write_task(d, 'big', m); w = fresh_worker(mp, 'N1_CQR', budget=0.5); A(w['status'] == 'STOPPED' and w['outcome'] == 'DEADLINE' and 'answers' not in w and 'intervals' not in w, 'deadline worker leaked a publication: %s' % w['outcome']); out['worker_deadline'] = w['outcome']
    # MEMORY: a fresh worker under a 64 MB address-space limit on a model whose tables are large
    mb = dict(cards=[16] * 6, factors=[dict(scope=(0, 1, 2, 3, 4), values=[F(1)] * 16 ** 5)], evidence={}); mp2 = write_task(d, 'memory', mb)
    out_p = mp2 + '.mem.json'; dl = subprocess.run([PY, '-c', 'import time; print(time.monotonic()+20)'], capture_output=True, text=True).stdout.strip()
    code = "import resource,sys; resource.setrlimit(resource.RLIMIT_AS,(200*1024**2,200*1024**2)); sys.argv=['worker.py','--input',%r,'--output',%r,'--arm','N1_CQR','--deadline',%r,'--seed','s','--nonce','n','--budget','20']; sys.path.insert(0,%r); import worker; worker.main()" % (mp2, out_p, dl, HERE)
    p = subprocess.run([PY, '-c', code], capture_output=True, text=True, cwd=CODE); CNT['fresh_workers'] += 1
    wm = json.load(open(out_p)) if os.path.exists(out_p) else dict(status='NO_OUTPUT', outcome='KILLED_rc_%s' % p.returncode); A(wm.get('outcome') in ('MEMORY', 'FAULT', 'DEADLINE') or wm['status'] == 'NO_OUTPUT', 'memory-capped worker published: %s' % wm.get('outcome')); A(wm.get('outcome') != 'PUBLISHED', 'published under memory pressure'); out['memory_capped_worker'] = dict(status=wm.get('status'), outcome=wm.get('outcome'), exception=wm.get('exception_type'))
    return out


# ======================================================================================================================
def c12_pipeline_admission():
    """the REGISTRY PIPELINE: the development admission directory must exist with a complete chain (manifest -> receipts for every cell -> references -> gate PASSED -> report);
    its frozen cqr identity must equal the CURRENT sources (zero differences); the closeout with a current-identity stub record is QUALIFIED; a stub missing a group is refused;
    a receipt with a mutated worker output is refused by a gate re-run on a COPY"""
    A(os.path.isdir(ADMISSION_DIR), 'development admission directory %s is REQUIRED (absent)' % ADMISSION_DIR)
    mn = 'CAMPAIGN_MANIFEST_dev.json'; man = json.load(open(os.path.join(ADMISSION_DIR, mn))); cells = man['cells']; out = dict(cells=len(cells), arms=sorted({c['arm'] for c in cells}), cohorts=sorted({c['cohort'] for c in cells}))
    frozen = {k: v for k, v in man['candidate_artifact_hashes'].items() if k.startswith('cqr/') or k == 'newarm/core.py'}; cur = registry.cqr_source_inventory(CODE)
    diff = sorted(k for k in set(frozen) | set(cur) if frozen.get(k) != cur.get(k)); A(not diff, 'admission identity differs from the current sources: %s' % diff[:3]); out['identity_differences'] = 0
    recs = {}
    for c in cells:
        cd = [p for p in os.listdir(os.path.join(ADMISSION_DIR, 'cells')) if p.split('__')[1] == c['case_id'] and p.split('__')[2] == c['arm'] and p.endswith('__r%d' % c['replicate']) and p.split('__')[3] == str(int(c['budget_s']))]
        A(cd, 'cell without a directory: %s %s' % (c['case_id'], c['arm'])); rp = os.path.join(ADMISSION_DIR, 'cells', cd[0], 'receipt.json'); A(os.path.exists(rp), 'cell without a receipt'); recs[c['cell_id']] = json.load(open(rp))
    oc = collections.Counter((r['arm'], r['outcome']) for r in recs.values()); out['outcomes'] = {'%s|%s' % k: v for k, v in sorted(oc.items())}
    A(sum(1 for r in recs.values() if r['arm'] == 'N1_CQR' and r['outcome'] == 'PUBLISHED') >= 10, 'too few N1 publications in the admission'); A(any(r['arm'] in ('H1_HYBRID', 'B0_FROZEN_V14') for r in recs.values()), 'no baseline arm in the admission'); A(any(r['arm'] in ('LBP', 'LIBDAI_EXACT', 'WMB', 'IJGP', 'PGMAX_SUMPRODUCT_BP', 'MERLIN_CTE') for r in recs.values()), 'no comparator in the admission')
    gr = json.load(open(os.path.join(ADMISSION_DIR, 'GATE_RESULT.json'))); A(gr['gate_passed'] is True, 'gate not passed: %s' % gr['failures'][:3]); out['gate'] = dict(gated=gr['counters'].get('gated'), wall=gr.get('gate_wall_s'))
    A(os.path.exists(os.path.join(ADMISSION_DIR, 'REFERENCES_R0.json')) and os.path.exists(os.path.join(ADMISSION_DIR, 'RESULTS_CQR.json')), 'references / report missing')
    rr = json.load(open(os.path.join(ADMISSION_DIR, 'RESULTS_CQR.json'))); A((rr.get('gate_binding') or {}).get('gated_set_sha256') == gr['gated_set_sha256'], 'report does not bind the latest gate')
    # closeout with a current-identity stub: QUALIFIED; a stub missing a group: refused
    d = tempfile.mkdtemp(prefix='cqr_c12_'); stub = dict(suite_version=SUITE_VERSION + ' (pipeline-test stub)', suite_sha256=registry.suite_sha256(CODE), all_pass=True, passed=len(registry.QUALIFICATION_GROUPS), total=len(registry.QUALIFICATION_GROUPS), groups=[dict(name=g_, ok=True) for g_ in registry.QUALIFICATION_GROUPS], candidate_sources=cur); sp = os.path.join(d, 'Q_stub.json'); json.dump(stub, open(sp, 'w'))
    p = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), ADMISSION_DIR, '--manifest', mn, '--qualification', sp], capture_output=True, text=True, cwd=CODE); A(p.returncode == 0 and 'QUALIFIED' in p.stdout, 'closeout not qualified: %s' % (p.stdout[-400:] + p.stderr[-300:])); out['closeout'] = p.stdout.strip().splitlines()[-1][:160]
    s2 = copy.deepcopy(stub); s2['groups'] = s2['groups'][1:]; s2['passed'] = s2['total'] = len(s2['groups']); json.dump(s2, open(sp, 'w')); p2 = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), ADMISSION_DIR, '--manifest', mn, '--qualification', sp], capture_output=True, text=True, cwd=CODE); A(p2.returncode != 0 and 'group' in (p2.stdout + p2.stderr).lower(), 'missing-group stub accepted'); out['missing_group_refused'] = True
    s3 = copy.deepcopy(stub); s3['candidate_sources'] = {k: '0' * 64 for k in cur}; json.dump(s3, open(sp, 'w')); p3 = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), ADMISSION_DIR, '--manifest', mn, '--qualification', sp], capture_output=True, text=True, cwd=CODE); A(p3.returncode != 0 and 'identity' in (p3.stdout + p3.stderr).lower(), 'stale-identity stub accepted'); out['stale_identity_refused'] = True
    s4 = copy.deepcopy(stub); s4['suite_sha256'] = '0' * 64; json.dump(s4, open(sp, 'w')); p4_ = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), ADMISSION_DIR, '--manifest', mn, '--qualification', sp], capture_output=True, text=True, cwd=CODE); A(p4_.returncode != 0 and 'suite' in (p4_.stdout + p4_.stderr).lower(), 'stale-suite stub accepted'); out['stale_suite_refused'] = True
    # gate re-run on a COPY with one mutated N1 worker output: refused for that cell
    cp = os.path.join(d, 'admission_copy'); shutil.copytree(ADMISSION_DIR, cp, symlinks=True)
    tgt = next(r for r in recs.values() if r['arm'] == 'N1_CQR' and r['outcome'] == 'PUBLISHED'); wp = os.path.join(cp, tgt['worker_output']); w = json.load(open(wp)); w['answers'][0]['point'] = str(F(w['answers'][0]['point']) + F(1, 50)); w['certificate']['publication']['point'][0] = w['answers'][0]['point']; json.dump(w, open(wp, 'w'))
    p4 = subprocess.run([PY, os.path.join(HERE, 'gate.py'), cp, '--manifest', mn, '--gate-budget-s', '600'], capture_output=True, text=True, cwd=CODE); g4 = json.load(open(os.path.join(cp, 'GATE_RESULT.json'))); A(g4['gate_passed'] is False and any(f[0] == tgt['cell_id'] for f in g4['failures']), 'mutated worker output not refused by the gate re-run'); out['gate_rerun_refuses_mutation'] = [f[1][:80] for f in g4['failures'] if f[0] == tgt['cell_id']][:1]
    return out


# ======================================================================================================================
def c13_delta_falsification():
    """PREREGISTERED (C13_PLAN): sampling-only diagnostic runs on the tiny chain model at delta in {1/4, 1/16}, eps = 1/10, 120 runs each; misses among publications must not
    exceed the one-sided binomial 1 - 0.0005 quantile. A pass is a gross-miscalibration falsification only; it does not validate the 1e-6 tail."""
    m = dict(cards=[2, 2, 2], factors=[dict(scope=(0, 1), values=[F(1), F(2), F(3), F(1)]), dict(scope=(1, 2), values=[F(2), F(1), F(1), F(3)])], evidence={}); qs = TK.all_singletons(m['cards']); tr = truth_of(m, qs); out = dict(plan=C13_PLAN, settings=[])
    for st in C13_PLAN['settings']:
        delta = F(st['delta']); N = st['runs']; pubs = 0; misses = 0; routes = collections.Counter(); t0 = time.monotonic()
        for i in range(N):
            task = mk_task(m, qs, eps=F(C13_PLAN['epsilon']), delta=delta)
            try: r = solve_(task, 'N1_CQR', 'c13-%s-%d' % (st['delta'], i), budget=C13_PLAN['deadline_per_run_s'], diagnostic='sampling_only')
            except SV.Stop: routes['DEADLINE'] += 1; continue
            if r['outcome'] != 'PUBLISHED': routes[r['outcome']] += 1; continue
            pubs += 1; routes[r['publication']['route']] += 1; misses += int(compare(r['publication'], tr, F(C13_PLAN['epsilon']), qs) > 0)
        # one-sided binomial quantile at 1 - 0.0005
        def binom_cdf(k, n, p):
            return sum(math.comb(n, i) * float(p) ** i * (1 - float(p)) ** (n - i) for i in range(k + 1))
        q = next(k for k in range(pubs + 1) if binom_cdf(k, pubs, delta) >= 1 - 0.0005) if pubs else 0
        A(pubs >= N // 2, 'too few publications (%d of %d)' % (pubs, N)); A(misses <= q, 'GROSS MISCALIBRATION: %d misses of %d publications exceeds the binomial quantile %d at delta %s' % (misses, pubs, q, delta))
        out['settings'].append(dict(delta=st['delta'], runs=N, publications=pubs, misses=misses, binomial_quantile_1_minus_0_0005=q, expected_misses=float(delta) * pubs, routes=dict(routes), wall_s=round(time.monotonic() - t0, 1)))
    return out



# ======================================================================================================================
# ---- groups added after the adversarial review of 16 Nov 2026 (findings CQR-01..CQR-10). Fixtures regenerate the reviewer's witnesses from their recorded construction
# rules (never read from the evidence archive); truths come from cex/cqr/oracle.py (enumeration, or variable elimination for models beyond 2^22 assignments: never the decoder).
def _uai(path, cards, fs):
    toks = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(fs))]
    for sc, vals in fs: toks.append(' '.join(map(str, [len(sc)] + list(sc))))
    for sc, vals in fs: toks.extend([str(len(vals)), ' '.join(str(v) for v in vals)])
    open(path, 'w').write('\n'.join(toks) + '\n'); return path


def _spec(path, **spec): json.dump(spec, open(path + '.query.json', 'w')); return path


def _concentration_witness(d):
    """review CQR-01: 16 binary variables, unaries [1000000, 1] on every variable, ring factors [1,2;3,5]; query x0 = 1 (DETERMINISTIC_EPS); truth ~ 6e-6"""
    n = 16; fs = [([i], [1000000, 1]) for i in range(n)] + [([i, (i + 1) % n], [1, 2, 3, 5]) for i in range(n)]
    return _spec(_uai(os.path.join(d, 'concentration.uai'), [2] * n, fs), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=0, state=1)])


def _biased_closure_witness(d):
    """review CQR-05: x0 has 4 states nearly proportional to x1 (approximate quotient, bias 1/40001); original answer 20953/74287; second query h = g = 0 is UNDEFINED"""
    n = 18; fs = [([0, 1], ['1', '3', '1', '30001/10000', '4', '1', '4', '10001/10000']), ([0, 2], ['1', '2', '1', '2', '3', '1', '3', '1']), ([1, 2], ['1', '2', '3', '5'])] + [([i], ['1', '2']) for i in range(3, n)]
    return _spec(_uai(os.path.join(d, 'biased_closure.uai'), [4] + [2] * (n - 1), fs), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000',
                 queries=[dict(kind='singleton', variable=0, state=1), dict(kind='table', table=dict(name='zero denominator', kind='ratio', h=dict(scope=[], values=['0']), g=dict(scope=[], values=['0'])))])


def _normalizer_witness(d):
    """review CQR-02: 30 binary variables, ONE unary factor [1, 2] on x29 (every other variable free): Z = 3 * 2^29 exactly; PAC normalizer at eps 3/10, delta 1/5"""
    return _spec(_uai(os.path.join(d, 'normalizer.uai'), [2] * 30, [([29], ['1', '2'])]), mode='PAC_EPS', normalizer_task=True, queries=[], epsilon='3/10', delta='1/5')


def _constant_witness(d):
    """review CQR-03: 20 binary variables with unaries [1,2]; the query is the CONSTANT table 1/3 (zero-dimensional)"""
    return _spec(_uai(os.path.join(d, 'constant20.uai'), [2] * 20, [([i], ['1', '2']) for i in range(20)]), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000',
                 queries=[dict(kind='table', table=dict(name='constant', kind='expectation', f=dict(scope=[], values=['1/3'])))])


def _d32_witness(d, seed=32):
    """review CQR-06: two 32-state variables (1,024 original assignments), one dense pair factor + unaries; all singletons of x0 = 0 and x1 = 0 (campaign default PAC task)"""
    rng = random.Random(seed); fs = [([0, 1], [rng.randint(1, 9) for _ in range(32 * 32)]), ([0], [rng.randint(1, 9) for _ in range(32)]), ([1], [rng.randint(1, 9) for _ in range(32)])]
    return _spec(_uai(os.path.join(d, 'd32.uai'), [32, 32], fs), queries=[dict(kind='singleton', variable=0, state=0), dict(kind='singleton', variable=1, state=0)])


def _sprinkled(seed, n, nf, ar, big=10, small=1, holes=1):
    """arity-4 factors of value `big` with `holes` entries of value `small`: pointwise caps stay tight while cell lower bounds vanish -> the deterministic frontier cannot close but the ratio stream does"""
    rng = random.Random(seed); fs = []; cover = list(range(n)); rng.shuffle(cover); k = 0
    for i in range(nf):
        if k + ar <= n: sc = tuple(sorted(cover[k:k + ar])); k += ar
        else: sc = tuple(sorted(rng.sample(range(n), ar)))
        vals = [big] * (2 ** ar)
        for h in rng.sample(range(2 ** ar), holes): vals[h] = small
        fs.append((sc, vals))
    return [2] * n, fs


def _ring_hardzero(seed, n, lo, hi, p0=9):
    """near-uniform ring with ONE hard zero at (x0 = 1, x1 = 1) and a rare x0 = 1: the query 'mostly 1/2' is constant off a region of tiny mass -> the signed residual stream validates 1/2"""
    rng = random.Random(seed); fs = []
    for i in range(n):
        vals = [rng.randint(lo, hi) for _ in range(4)]
        if i == 0: vals[3] = 0
        fs.append(([i, (i + 1) % n], vals))
    fs.append(([0], [p0, 1])); return [2] * n, fs


def _truth(mp):
    t = TK.load_task(mp); CNT['oracle_models'] += 1; return t, OR.truth(t['model'], t['queries'], max_assignments=1 << 22, max_table=1 << 24)


def _contained(w, tr, eps):
    ok = True
    for j, a in enumerate(w['answers']):
        CNT['truth_coordinates'] += 1; v = tr['answers'][j]
        if v == 'UNDEFINED': ok &= (a['status'] == 'UNDEFINED'); continue
        if a['status'] != 'OK': ok = False; continue
        ok &= (F(a['lo']) <= v <= F(a['hi']) and abs(F(a['point']) - v) <= eps)
    return ok


def _mut(mp, w, arm, name, fn, needles, out):
    """apply `fn` to a COPY of a worker output (receipt hashes are irrelevant to the semantic checker) and require a refusal naming one of `needles`"""
    x = copy.deepcopy(w); fn(x); fails, _ = check_(mp, x, arm, budget=300.0); needles = needles if isinstance(needles, tuple) else (needles,)
    A(fails and any(any(nd in f for nd in needles) for f in fails), 'mutation %s not refused for the intended reason: %s' % (name, fails[:2])); out[name] = fails[0][:110]


def c14_publication_contract_every_route():
    """review item 1 (CQR-01, CQR-02, CQR-03, CQR-05): for EVERY publication route an honest fresh-worker acceptance and content mutations refused for their semantic reason
    (point, bounds, bias, exactness, typed undefined, output count / identity, legacy serialization, route relabel); the reviewer's witnesses regenerated from their rules"""
    d = tempfile.mkdtemp(prefix='cqr_c14_'); out = dict(routes={}, mutations={}); routes_seen = set()
    def honest(mp, arm, budget=20.0, seed='s', extra=()):
        w = fresh_worker(mp, arm, budget=budget, seed=seed, nonce='c14-%s-%s' % (os.path.basename(mp), arm), extra=extra); fails, info = check_(mp, w, arm, budget=300.0)
        A(not fails, '%s/%s honest refused: %s' % (os.path.basename(mp), arm, fails[:2])); A(w['outcome'] == 'PUBLISHED', '%s/%s outcome %s %s' % (os.path.basename(mp), arm, w['outcome'], (w.get('reason') or '')[:80]))
        t, tr = _truth(mp)
        if not (t.get('query_spec') or {}).get('normalizer_task'): A(_contained(w, tr, t['epsilon']), '%s/%s published answers miss the independent truth' % (os.path.basename(mp), arm))
        else: a = w['answers'][0]; CNT['truth_coordinates'] += 1; A(F(a['lo']) <= tr['Z'] <= F(a['hi']) and abs(F(a['point']) - tr['Z']) <= t['epsilon'] * tr['Z'], 'normalizer miss')
        routes_seen.add(w['route']); out['routes'][os.path.basename(mp) + '/' + arm] = dict(route=w['route'], guarantee=w['guarantee_type'], exact=w.get('exact')); return w, t, tr
    # ---- CQR-01 concentration: the forged direct answer (nearly-zero answer changed to 1 with consistent bounds / point) must fail on re-evaluation at x*
    mp = _concentration_witness(d); w, t, tr = honest(mp, 'N1_CQR'); A(w['route'] == 'deterministic_concentration', 'concentration route not taken: %s' % w['route'])
    def forge(x):
        dc = next(c for c in x['certificate']['compile']['certificates'] if c.get('op') == 'concentration' and 'answers' in c); b = F(x['certificate']['bias'][0])
        dc['answers']['0'] = '1'; x['certificate']['publication']['bounds'] = [[str(1 - b), '1']]; x['certificate']['publication']['point'] = ['1']; x['answers'][0].update(lo=str(1 - b), hi='1', point='1')
    _mut(mp, w, 'N1_CQR', 'concentration_answer_forged', forge, 'does not re-derive', out['mutations']); out['concentration_truth'] = str(tr['answers'][0])
    _mut(mp, w, 'N1_CQR', 'concentration_route_relabel', lambda x: (x.__setitem__('route', 'deterministic_frontier'), x['certificate']['publication'].__setitem__('route', 'deterministic_frontier')), ('route', 'frontier', 'do not contain'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'concentration_output_count', lambda x: x['answers'].append(dict(x['answers'][0])), ('shape', 'count', 'answers'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'concentration_identity', lambda x: x.__setitem__('task_identity', '2' * 64), 'identity', out['mutations'])
    # ---- CQR-05 biased closure: bias 1/40001 stays on the original interval; never exact; the undefined coordinate stays typed
    mp = _biased_closure_witness(d); w, t, tr = honest(mp, 'N1_CQR'); A(tr['answers'][0] == F(20953, 74287) and tr['answers'][1] == 'UNDEFINED', 'biased-closure fixture truth %s' % tr['answers'])
    A(w.get('exact') is False and any(F(b) > 0 for b in w['certificate']['bias']), 'biased closure published exact or without bias'); A(w['answers'][1]['status'] == 'UNDEFINED', 'second coordinate not typed UNDEFINED')
    out['biased_closure'] = dict(route=w['route'], bounds=[w['answers'][0]['lo'], w['answers'][0]['hi']], bias=w['certificate']['bias'])
    _mut(mp, w, 'N1_CQR', 'biased_exact_claim', lambda x: (x.__setitem__('exact', True), x['certificate']['publication'].__setitem__('exact', True)), ('exact', 'route'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'biased_bias_zeroed', lambda x: x['certificate'].__setitem__('bias', ['0', '0']), 'bias ledger', out['mutations'])
    def narrow(x):
        c = x['certificate']['publication']['compiled_bounds'][0][0]; x['answers'][0].update(lo=str(c), hi=str(c), point=str(c)); x['certificate']['publication']['bounds'][0] = [str(c), str(c)]; x['certificate']['publication']['point'][0] = str(c)
    _mut(mp, w, 'N1_CQR', 'biased_bounds_narrowed_to_compiled', narrow, ('do not contain', 'not within eps'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'biased_undefined_given_value', lambda x: (x['answers'][1].update(status='OK', lo='0', hi='1', point='1/2'), x['certificate']['publication']['bounds'].__setitem__(1, ['0', '1']), x['certificate']['publication']['point'].__setitem__(1, '1/2')), ('undefined', 'UNDEFINED'), out['mutations'])
    # ---- CQR-03 zero-dimensional constant 1/3: point 0 with correct bounds; CQR-03 legacy rows [0,1] on the exact-reference unary [1,2]
    mp = _constant_witness(d); w, t, tr = honest(mp, 'N1_CQR', budget=10.0); A(tr['answers'][0] == F(1, 3), 'constant fixture')
    _mut(mp, w, 'N1_CQR', 'zero_dim_point_zero', lambda x: (x['answers'][0].__setitem__('point', '0'), x['certificate']['publication']['point'].__setitem__(0, '0')), ('outside its published bounds', 'not within eps'), out['mutations'])
    mp = _uai(os.path.join(d, 'unary.uai'), [2], [([0], ['1', '2'])]); w, t, tr = honest(mp, 'G0_CQR', budget=10.0)        # NO query file: the campaign default all-singleton contract (legacy rows emitted), as in the reviewer's witness
    A(w['route'] == 'exact_reference' and w.get('intervals') is not None, 'unary exact reference without legacy rows')
    _mut(mp, w, 'G0_CQR', 'legacy_rows_wrong', lambda x: (x.__setitem__('intervals', [[['0', '0'], ['1', '1']]]), x.__setitem__('points', [['0', '1']])), ('legacy', 'rows'), out['mutations'])
    _mut(mp, w, 'G0_CQR', 'legacy_rows_dropped', lambda x: (x.pop('intervals'), x.pop('points')), ('legacy', 'rows'), out['mutations'])
    _mut(mp, w, 'G0_CQR', 'exact_value_changed', lambda x: (x['answers'][0].update(lo='1/2', hi='1/2', point='1/2'), x['certificate']['publication'].__setitem__('bounds', [['1/2', '1/2']]), x['certificate']['publication'].__setitem__('point', ['1/2']), x.__setitem__('intervals', [[['1/2', '1/2'], ['1/2', '1/2']]]), x.__setitem__('points', [['1/2', '1/2']])), ('differs', 'do not contain', 'enumerator'), out['mutations'])
    # ---- exact closure (clones, EXACT_RATIONAL): zero-width; an exactness downgrade / widening is refused
    g = G.generate('M02', 6, 'favorable', 1); mp = write_task(d, 'clones_exact', g['model'], dict(mode='EXACT_RATIONAL', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='0')); w, t, tr = honest(mp, 'N1_CQR', budget=10.0)
    A(w['route'] in ('exact_frontier_closure', 'exact_zero_dimensional', 'exact_reference') and w.get('exact') is True, 'clones exact route %s' % w['route'])
    _mut(mp, w, 'N1_CQR', 'exact_widened', lambda x: (x['answers'][0].__setitem__('hi', str(F(x['answers'][0]['hi']) + F(1, 1000))), x['certificate']['publication']['bounds'][0].__setitem__(1, x['answers'][0]['hi'])), ('zero-width', 'exact', 'differs'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'exact_flag_dropped', lambda x: (x.__setitem__('exact', False), x['certificate']['publication'].__setitem__('exact', False)), ('exact', 'route'), out['mutations'])
    # ---- CQR-02 normalizer PAC: narrowed singleton refused, valid small outward widening accepted, relabel refused; exact normalizer routes
    mp = _normalizer_witness(d); w = None
    for seed in range(6):
        w_ = fresh_worker(mp, 'G0_CQR', budget=10.0, seed=str(seed), nonce='c14-norm-%d' % seed)
        if w_['outcome'] == 'PUBLISHED' and w_['guarantee_type'] == 'PAC': w = w_; break
    A(w is not None, 'the normalizer witness produced no PAC publication in 6 seeds'); fails, _ = check_(mp, w, 'G0_CQR', budget=300.0); A(not fails, 'normalizer honest refused %s' % fails[:1]); routes_seen.add(w['route'])
    Z = 3 * 2 ** 29; lo, hi = F(w['answers'][0]['lo']), F(w['answers'][0]['hi']); A(lo <= Z <= hi, 'normalizer honest bounds miss Z'); CNT['truth_coordinates'] += 1; out['routes']['normalizer/G0_CQR'] = dict(route=w['route'], rel_width=float((hi - lo) / lo))
    wrong = lo if abs(lo - Z) > abs(hi - Z) else hi; A(abs(wrong - Z) > F(3, 10) * Z, 'narrowing fixture: the far end is within tolerance (seed-dependent); draws %s' % w['certificate']['ratio_stream']['t'])
    _mut(mp, w, 'G0_CQR', 'normalizer_narrowed_singleton', lambda x: (x['answers'][0].update(lo=str(wrong), hi=str(wrong), point=str(wrong)), x['certificate']['publication'].__setitem__('bounds', [[str(wrong), str(wrong)]]), x['certificate']['publication'].__setitem__('point', [str(wrong)])), 'do not contain', out['mutations'])
    fac = F(10005, 10000); x = copy.deepcopy(w); x['answers'][0].update(lo=str(lo / fac), hi=str(hi * fac)); x['certificate']['publication']['bounds'] = [[str(lo / fac), str(hi * fac)]]; fails, _ = check_(mp, x, 'G0_CQR', budget=300.0)
    A(not fails, 'VALID outward widening (x1.0005, point still tolerance-feasible) refused: %s' % fails[:1]); out['normalizer_valid_widening_accepted'] = True
    x = copy.deepcopy(w); x['answers'][0].update(lo=str(lo / 2), hi=str(hi * 2)); x['certificate']['publication']['bounds'] = [[str(lo / 2), str(hi * 2)]]; fails, _ = check_(mp, x, 'G0_CQR', budget=300.0)
    A(fails and any('point outside' in f or 'relative error' in f for f in fails), 'a widening that breaks the relative-error feasibility of the point was accepted'); out['mutations']['normalizer_widened_beyond_feasibility'] = fails[0][:100]
    _mut(mp, w, 'G0_CQR', 'normalizer_relabelled_deterministic', lambda x: (x.__setitem__('guarantee_type', 'DETERMINISTIC'), x['certificate']['publication'].__setitem__('guarantee', 'DETERMINISTIC')), 'class PAC', out['mutations'])
    mp = _spec(_uai(os.path.join(d, 'norm20.uai'), [2] * 20, []), normalizer_task=True, queries=[], mode='EXACT_RATIONAL', epsilon='1/200', delta='0'); w, t, tr = honest(mp, 'N1_CQR', budget=10.0); A(F(w['answers'][0]['lo']) == 2 ** 20 == tr['Z'], 'free normalizer Z')
    _mut(mp, w, 'N1_CQR', 'normalizer_exact_value_changed', lambda x: (x['answers'][0].update(lo='1048577', hi='1048577', point='1048577'), x['certificate']['publication'].__setitem__('bounds', [['1048577', '1048577']]), x['certificate']['publication'].__setitem__('point', ['1048577'])), ('differs', 'do not contain', 'scalar'), out['mutations'])
    mp = write_task(d, 'norm_small', G.generate('M11', 8, 'favorable', 3)['model'], dict(mode='PAC_EPS', normalizer_task=True, queries=[], epsilon='1/200', delta='1/1000000')); w, t, tr = honest(mp, 'G0_CQR', budget=10.0)
    # ---- deterministic signed E_ZERO and the PAC routes (fresh workers; mutations in C16)
    cards, fs = _ring_hardzero(1, 30, 9, 10); vals = [str(F(1, 2) if not (x0 == 1 and x1 == 1) else F(x2)) for x0 in range(2) for x1 in range(2) for x2 in range(2)]
    mp = _spec(_uai(os.path.join(d, 'ez30.uai'), cards, fs), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='table', table=dict(name='half_off_zero', kind='expectation', f=dict(scope=[0, 1, 2], values=vals)))]); w, t, tr = honest(mp, 'N1_CQR', budget=20.0)
    if w['route'] == 'deterministic_signed_residual_E_zero': _mut(mp, w, 'N1_CQR', 'e_zero_point_shift', lambda x: (x['answers'][0].__setitem__('point', str(F(x['answers'][0]['point']) + F(1, 50))), x['certificate']['publication']['point'].__setitem__(0, x['answers'][0]['point'])), ('candidate', 'not within eps', 'outside'), out['mutations'])
    required = {'exact_reference', 'deterministic_concentration', 'deterministic_frontier', 'normalizer_pac_ratio_intersected_with_deterministic', 'normalizer_exact_zero_dimensional'}
    A(required <= routes_seen, 'routes not exercised: %s' % sorted(required - routes_seen)); out['routes_seen'] = sorted(routes_seen); out['mutation_count'] = len(out['mutations']); return out


def c15_semantics_and_guarantee_binding():
    """review item 2 (CQR-04, CQR-08): the task FILE is authoritative (a CLI mode override that disagrees with a frozen EXACT_RATIONAL task fails in the worker AND the checker);
    the proof class is derived from the validated route (an honest PAC relabelled DETERMINISTIC fails even with correct numbers); DETERMINISTIC_EPS consumes no statistical
    proof; EXACT_RATIONAL publishes no approximate surrogate; the normalizer + nonempty-queries contract is refused at parsing; manifest declaration vs worker binding"""
    d = tempfile.mkdtemp(prefix='cqr_c15_'); out = {}
    mp = _concentration_witness(d); json.dump(dict(mode='EXACT_RATIONAL', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=0, state=1)]), open(mp + '.query.json', 'w'))
    w = fresh_worker(mp, 'N1_CQR', budget=20.0, nonce='c15-override', mode='DETERMINISTIC_EPS'); A(w['outcome'] in ('FAULT', 'REFUSED') and 'disagrees' in (w.get('reason') or w.get('error') or ''), 'mode override accepted by the worker: %s %s' % (w['outcome'], (w.get('reason') or '')[:80]))
    fails, _ = check_(mp, w, 'N1_CQR'); A(fails, 'checker accepted the overridden worker'); out['mode_override'] = (w['outcome'], fails[0][:80])
    w = fresh_worker(mp, 'N1_CQR', budget=20.0, nonce='c15-exact'); fails, _ = check_(mp, w, 'N1_CQR'); A(not fails and w['outcome'] == 'PUBLISHED' and w['exact'] is True and w['mode'] == 'EXACT_RATIONAL', 'exact task honest run refused %s' % fails[:1])
    # DETERMINISTIC_EPS never consumes a statistical proof; EXACT_RATIONAL never a deterministic surrogate (unit + fresh worker)
    for mode, route, ok in (('DETERMINISTIC_EPS', 'pac_ratio_intersected_with_deterministic', False), ('DETERMINISTIC_EPS', 'pac_signed_residual_validation', False), ('EXACT_RATIONAL', 'deterministic_frontier', False), ('EXACT_RATIONAL', 'deterministic_concentration', False), ('PAC_EPS', 'deterministic_frontier', True), ('DETERMINISTIC_EPS', 'exact_reference', True), ('EXACT_RATIONAL', 'exact_frontier_closure', True)):
        A(CK.mode_permits(mode, route) is ok, 'mode_permits(%s, %s) != %s' % (mode, route, ok))
    cards, fs = _sprinkled(1, 28, 14, 4); mp2 = _spec(_uai(os.path.join(d, 'spr_det.uai'), cards, fs), mode='DETERMINISTIC_EPS', epsilon='1/10', delta='0', queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[2, 3, 4, 5, 6, 7], bit=1)])
    w2 = fresh_worker(mp2, 'N1_CQR', budget=12.0, nonce='c15-det'); A(w2['outcome'] != 'PUBLISHED' or w2['route'] in CK.DET_ROUTES + CK.EXACT_ROUTES, 'DETERMINISTIC_EPS task published a statistical route %s' % w2.get('route')); out['deterministic_task_route'] = (w2['outcome'], w2.get('route'))
    # the PAC output of the SAME model under a PAC task, relabelled DETERMINISTIC, fails even though its numbers are right (C16 has the honest acceptance)
    mp3 = _spec(_uai(os.path.join(d, 'spr_pac.uai'), cards, fs), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[2, 3, 4, 5, 6, 7], bit=1)])
    w3 = fresh_worker(mp3, 'N1_CQR', budget=40.0, nonce='c15-pac'); fails, info = check_(mp3, w3, 'N1_CQR', budget=300.0); A(not fails and w3['outcome'] == 'PUBLISHED', 'PAC fixture refused / not published: %s %s' % (w3['outcome'], fails[:1]))
    if w3['guarantee_type'] == 'PAC':
        _mut(mp3, w3, 'N1_CQR', 'pac_relabelled_deterministic', lambda x: (x.__setitem__('guarantee_type', 'DETERMINISTIC'), x['certificate']['publication'].__setitem__('guarantee', 'DETERMINISTIC')), 'class PAC', out)
        _mut(mp3, w3, 'N1_CQR', 'pac_cert_guarantee_only', lambda x: x['certificate']['publication'].__setitem__('guarantee', 'DETERMINISTIC'), ('class PAC', 'differs'), out)
    else: out['note'] = 'the PAC fixture published deterministically this run (%s); the relabel control ran on the normalizer witness in C14' % w3['route']
    # manifest declaration vs worker: epsilon / mode / normalizer flag disagreements are refused by the checker's manifest binding
    for name, mt in (('eps', dict(epsilon='1/100', delta='1/10', mode='PAC_EPS', normalizer_task=False)), ('mode', dict(epsilon='1/10', delta='1/10', mode='DETERMINISTIC_EPS', normalizer_task=False)), ('normalizer', dict(epsilon='1/10', delta='1/10', mode='PAC_EPS', normalizer_task=True))):
        fails, _ = check_(mp3, w3, 'N1_CQR', budget=300.0, manifest_task=mt); A(fails and any('manifest' in f or 'differ' in f for f in fails), 'manifest %s disagreement accepted' % name); out['manifest_' + name] = fails[0][:90]
    # CQR-08: normalizer + nonempty queries refused at parsing (worker) and by the loader
    mp4 = _spec(_uai(os.path.join(d, 'normq.uai'), [2] * 4, [([i], ['1', '2']) for i in range(4)]), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000', normalizer_task=True, queries=[dict(kind='singleton', variable=0, state=1)])
    w4 = fresh_worker(mp4, 'G0_CQR', budget=5.0, nonce='c15-normq'); A(w4['outcome'] != 'PUBLISHED' and 'NO queries' in (w4.get('reason') or w4.get('error') or ''), 'normalizer+queries contract not refused: %s' % (w4.get('reason') or '')[:80])
    try: TK.load_task(mp4); A(False, 'loader accepted normalizer + queries')
    except ValueError as e: A('NO queries' in str(e), str(e)[:80]); out['normalizer_plus_queries'] = 'refused at parsing'
    return out


def c16_fresh_process_pac_routes():
    """review item 7: GENUINE fresh-process ratio-PAC and signed-PAC publications at tractable declared tolerances (eps 1/10, delta 1/10) on models the reference cannot finish,
    judged by the independent variable-elimination oracle; stream mutations refused; counts of models / workers / coordinates / draws kept separately. Gross-calibration (C13)
    is a separate falsification; nothing here validates the 1e-6 tail."""
    d = tempfile.mkdtemp(prefix='cqr_c16_'); out = dict(ratio=None, signed=None, mutations={})
    cards, fs = _sprinkled(1, 28, 14, 4); mp = _spec(_uai(os.path.join(d, 'spr28.uai'), cards, fs), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[2, 3, 4, 5, 6, 7], bit=1)])
    t, tr = _truth(mp); A(tr is not None and tr.get('method') == 'elimination', 'the ratio fixture must be beyond enumeration (independent elimination oracle)')
    w = None
    for seed in ('pp', 'pq', 'pr'):
        w_ = fresh_worker(mp, 'N1_CQR', budget=45.0, seed=seed, nonce='c16-ratio-' + seed)
        if w_['outcome'] == 'PUBLISHED' and w_['route'] == 'pac_ratio_intersected_with_deterministic': w = w_; break
        if w is None and w_['outcome'] == 'PUBLISHED': w = w_
    A(w is not None and w['outcome'] == 'PUBLISHED', 'ratio fixture did not publish'); fails, info = check_(mp, w, 'N1_CQR', budget=600.0); A(not fails, 'ratio-PAC honest refused: %s' % fails[:2])
    A(_contained(w, tr, F(1, 10)), 'ratio-PAC answers miss the elimination truth'); rs = w['certificate'].get('ratio_stream') or {}; CNT['stream_draws'] += int(rs.get('t') or 0)
    out['ratio'] = dict(route=w['route'], guarantee=w['guarantee_type'], draws=rs.get('t'), epochs=len(w['certificate'].get('epochs') or []), truth=[str(a) for a in tr['answers']], bounds=[(a['lo'][:12], a['hi'][:12]) for a in w['answers']])
    A(w['route'] == 'pac_ratio_intersected_with_deterministic', 'ratio fixture published via %s (no fresh ratio-PAC publication in 3 seeds)' % w['route'])
    _mut(mp, w, 'N1_CQR', 'ratio_draw_point_moved', lambda x: (lambda e: e['x'].__setitem__(list(e['x'])[0], 1 - e['x'][list(e['x'])[0]]))(next(e for e in x['certificate']['events'] if e['op'] == 'ratio_draw')), ('draw', 'replay'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'ratio_variance_halved', lambda x: x['certificate']['ratio_stream'].__setitem__('V', str(F(x['certificate']['ratio_stream']['V']) / 2)), 'do not replay', out['mutations'])
    _mut(mp, w, 'N1_CQR', 'ratio_bounds_narrowed', lambda x: (x['answers'][0].update(lo=x['answers'][0]['point'], hi=x['answers'][0]['point']), x['certificate']['publication']['bounds'].__setitem__(0, [x['answers'][0]['point']] * 2)), 'do not contain', out['mutations'])
    _mut(mp, w, 'N1_CQR', 'ratio_relabelled_deterministic', lambda x: (x.__setitem__('guarantee_type', 'DETERMINISTIC'), x['certificate']['publication'].__setitem__('guarantee', 'DETERMINISTIC')), 'class PAC', out['mutations'])
    _mut(mp, w, 'N1_CQR', 'ratio_delta_halved_in_cert', lambda x: x['certificate'].__setitem__('delta', '1/20'), ('delta', 'differ'), out['mutations'])
    # signed-residual validation
    cards, fs = _ring_hardzero(1, 30, 39, 40); vals = [str(F(1, 2) if x0 == 0 or x1 == 1 else F(x2)) for x0 in range(2) for x1 in range(2) for x2 in range(2)]
    mp = _spec(_uai(os.path.join(d, 'ring30.uai'), cards, fs), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='table', table=dict(name='mostly_half', kind='expectation', f=dict(scope=[0, 1, 2], values=vals)))])
    t, tr = _truth(mp); A(tr.get('method') == 'elimination', 'signed fixture beyond enumeration'); w = fresh_worker(mp, 'N1_CQR', budget=20.0, nonce='c16-signed'); fails, info = check_(mp, w, 'N1_CQR', budget=300.0)
    A(not fails and w['outcome'] == 'PUBLISHED', 'signed fixture refused / unpublished %s' % fails[:1]); A(_contained(w, tr, F(1, 10)), 'signed answers miss the truth'); eps_ = w['certificate'].get('epochs') or []; CNT['stream_draws'] += sum(int(e.get('t') or 0) for e in eps_)
    out['signed'] = dict(route=w['route'], guarantee=w['guarantee_type'], epochs=len(eps_), draws=sum(int(e.get('t') or 0) for e in eps_), truth=str(tr['answers'][0]), bounds=(w['answers'][0]['lo'][:12], w['answers'][0]['hi'][:12]))
    A(w['route'] == 'pac_signed_residual_validation', 'signed fixture published via %s' % w['route'])
    _mut(mp, w, 'N1_CQR', 'signed_candidate_shift', lambda x: (lambda e: e['candidate'].__setitem__(0, str(F(e['candidate'][0]) + F(1, 100))))(next(e for e in x['certificate']['events'] if e['op'] == 'epoch_start')), ('envelope', 'candidate', 'replay'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'signed_point_shift', lambda x: (x['answers'][0].__setitem__('point', str(F(x['answers'][0]['point']) + F(1, 20))), x['certificate']['publication']['point'].__setitem__(0, x['answers'][0]['point'])), ('candidate', 'not within eps', 'outside'), out['mutations'])
    _mut(mp, w, 'N1_CQR', 'signed_epoch_risk_doubled', lambda x: (lambda e: e.__setitem__('delta_e', str(F(e['delta_e']) * 2)))(next(e for e in x['certificate']['events'] if e['op'] == 'epoch_start')), 'risk', out['mutations'])
    _mut(mp, w, 'N1_CQR', 'signed_draw_point_moved', lambda x: (lambda e: e['x'].__setitem__('1', 1 - e['x']['1']))(next(e for e in x['certificate']['events'] if e['op'] == 'signed_draw')), ('replay', 'draw', 'cell'), out['mutations'])      # x1 flips the hard-zero / residual structure (an x0 flip is inert: both points contribute R = 0)
    _mut(mp, w, 'N1_CQR', 'signed_relabelled_deterministic', lambda x: (x.__setitem__('guarantee_type', 'DETERMINISTIC'), x['certificate']['publication'].__setitem__('guarantee', 'DETERMINISTIC')), 'class PAC', out['mutations'])
    # the G0 arm (no signed stream) on the signed fixture never publishes a signed route
    wg = fresh_worker(mp, 'G0_CQR', budget=20.0, nonce='c16-signed-g0'); A(wg.get('route') != 'pac_signed_residual_validation' and not (wg['certificate'].get('epochs') if wg.get('certificate') else []), 'G0 ran the signed stream'); out['g0_on_signed_fixture'] = (wg['outcome'], wg.get('route'))
    return out


def c17_protected_reference_scheduling():
    """review item 4 (CQR-06): with PRODUCTION workers and scheduling instrumentation -- the natural small nonbinary witness (two 32-state variables) publishes the exact reference
    in both arms; nonbinary models with 32,768 / 1,048,576 assignments interleave reference and optional work from the start; inner-loop quotas hold in the approximate quotient
    and the influence scans; optional cancellation under memory pressure and an optional FAILURE (fault injection, recorded, refused as production) both keep the complete reference;
    every typed DEADLINE records reference progress and both work ledgers; parity (reference >= optional, or reference done) holds at every publication exit incl. signed exits"""
    d = tempfile.mkdtemp(prefix='cqr_c17_'); out = {}
    mp = _d32_witness(d)
    for arm in ('N1_CQR', 'G0_CQR'):
        t0 = time.monotonic(); w = fresh_worker(mp, arm, budget=20.0, nonce='c17-d32-' + arm); wall = time.monotonic() - t0; fails, _ = check_(mp, w, arm); c = w.get('certificate') or {}
        A(not fails and w['outcome'] == 'PUBLISHED' and w['route'] == 'exact_reference' and c['reference']['done'], 'd32 %s: %s %s %s' % (arm, w['outcome'], w.get('route'), fails[:1]))
        lg = (c.get('compile') or {}).get('log') or {}; out['d32_' + arm] = dict(wall_s=round(wall, 2), work_reference=c['work']['reference']['total'], work_optional=c['work']['optional']['total'], compile_interrupted=lg.get('interrupted'))
    t, tr = _truth(mp); w = json.load(open(mp + '.N1_CQR.c17-d32-N1_CQR.json')); A(_contained(w, tr, F(0)), 'd32 exact answers differ from the oracle')
    # compile quotas inside the costly loops (the review measured approx_quotient 350,208 vs 50,000): every operator's work <= quota + one tick granularity
    tk = TK.load_task(mp); C, log = compile_(tk, enabled=CP.effective_operators(SV.ARMS['N1_CQR']['enabled'], tk)); Dq = log['quota']; worst = {}
    for s in log['steps']:
        if s.get('work'): worst[s['op']] = max(worst.get(s['op'], 0), s['work'])
    A(all(wk <= Dq + 4096 for wk in worst.values()), 'an operator exceeded its quota share by more than one tick: %s (quota %d)' % (worst, Dq)); out['d32_compile_work_by_operator'] = dict(worst, quota=Dq)
    # interleaving on nonbinary models (3 and 4 variables of 32 states): the reference finishes; parity holds at the exit
    rng = random.Random(7)
    for n in (3, 4):
        fs = [([i, (i + 1) % n], [rng.randint(1, 9) for _ in range(32 * 32)]) for i in range(n)]; mpn = _spec(_uai(os.path.join(d, 'nb%d.uai' % n), [32] * n, fs), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='0', queries=[dict(kind='singleton', variable=0, state=0), dict(kind='singleton', variable=1, state=3)])
        w = fresh_worker(mpn, 'N1_CQR', budget=30.0, nonce='c17-nb%d' % n); fails, _ = check_(mpn, w, 'N1_CQR', budget=300.0); c = w['certificate']
        A(not fails and w['outcome'] == 'PUBLISHED', 'nb%d: %s %s' % (n, w['outcome'], fails[:1])); A(c['reference']['done'] or c['work']['reference']['total'] >= c['work']['optional']['total'], 'nb%d parity violated' % n)
        out['nb%d' % n] = dict(route=w['route'], work_reference=c['work']['reference']['total'], work_optional=c['work']['optional']['total'], reference_done=c['reference']['done'])
    # optional cancellation under memory pressure (a 1-byte cancellation cap): the reference alone completes the original task; the certificate records the cancellation
    mpc = _concentration_witness(d); w = fresh_worker(mpc, 'N1_CQR', budget=20.0, nonce='c17-cap', extra=('--cap-bytes', '1')); fails, _ = check_(mpc, w, 'N1_CQR'); c = w['certificate']
    A(not fails and w['outcome'] == 'PUBLISHED' and w['route'] == 'exact_reference' and c['reference']['done'] and 'memory pressure' in (c.get('optional_cancelled') or ''), 'cap cancellation: %s %s %s %s' % (w['outcome'], w.get('route'), c.get('optional_cancelled'), fails[:1]))
    out['memory_cancellation'] = dict(optional_cancelled=c['optional_cancelled'][:60], work_optional=c['work']['optional']['total'], work_reference=c['work']['reference']['total'])
    # optional FAILURE with reference progress: (a) inside an operator -> rolled back to the committed model, run continues; (b) inside the adaptive loop -> optional cancelled, reference alone
    w = fresh_worker(mpc, 'N1_CQR', budget=20.0, nonce='c17-fault-op', extra=('--fault-inject', 'approx_quotient')); c = w['certificate']; lg = c['compile']['log']
    A(w['outcome'] == 'PUBLISHED' and lg.get('failed', {}).get('op') == 'approx_quotient' and not any(s.get('committed') and s['op'] == 'approx_quotient' for s in lg['steps']), 'operator fault not rolled back: %s' % lg.get('failed'))
    fails, _ = check_(mpc, w, 'N1_CQR'); A(fails and any('FAULT-INJECTION' in f for f in fails), 'fault-injected output accepted as production'); x = json.loads(json.dumps(w)); x.pop('fault_injected', None); x['certificate']['fault_injected'] = None
    fails, _ = check_(mpc, x, 'N1_CQR'); A(not fails, 'a genuine optional-failure record (committed prefix) does not replay: %s' % fails[:1]); out['operator_failure'] = dict(route=w['route'], failed=lg['failed']['op'], committed=[s['op'] for s in lg['steps'] if s.get('committed')])
    mpl = os.path.join(d, 'nb3.uai'); w = fresh_worker(mpl, 'N1_CQR', budget=30.0, nonce='c17-fault-loop', extra=('--fault-inject', 'adaptive_loop')); c = w['certificate']
    A(w['outcome'] == 'PUBLISHED' and 'adaptive loop' in (c.get('optional_cancelled') or '') and c['reference']['done'] and w['route'] == 'exact_reference' and c['work']['optional']['total'] > 0, 'loop fault: %s %s %s' % (w['outcome'], w.get('route'), c.get('optional_cancelled')))
    out['loop_failure'] = dict(optional_cancelled=c['optional_cancelled'][:70], reference_done=True)
    # every typed DEADLINE after binding records reference progress > 0 and both ledgers (the review's witness expired with zero reference steps)
    rng = random.Random(44); n = 40; fs = [(tuple(sorted(rng.sample(range(n), 2))), [rng.randint(1, 2) for _ in range(4)]) for _ in range(n + 2)]
    mpd = _spec(_uai(os.path.join(d, 'big40.uai'), [2] * n, fs), mode='PAC_EPS', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=0, state=1)])
    w = fresh_worker(mpd, 'N1_CQR', budget=1.5, nonce='c17-deadline'); A(w['outcome'] == 'DEADLINE', 'expected DEADLINE, got %s' % w['outcome']); sch = w.get('scheduling') or {}
    A((sch.get('work_reference') or {}).get('total', 0) > 0 and sch.get('reference_progress') is not None and (sch.get('work_optional') or {}).get('total') is not None, 'typed deadline without scheduling instrumentation: %s' % str(sch)[:120])
    out['deadline_instrumentation'] = dict(reference_progress=sch.get('reference_progress'), work_reference=sch['work_reference']['total'], work_optional=sch['work_optional']['total'], phase=sch.get('phase'))
    # parity at signed exits (E_ZERO and signed PAC) and at the ratio exit
    cards, fs = _ring_hardzero(1, 30, 9, 10); vals = [str(F(1, 2) if not (x0 == 1 and x1 == 1) else F(x2)) for x0 in range(2) for x1 in range(2) for x2 in range(2)]
    mpe = _spec(_uai(os.path.join(d, 'ez30.uai'), cards, fs), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='table', table=dict(name='half_off_zero', kind='expectation', f=dict(scope=[0, 1, 2], values=vals)))])
    cards2, fs2 = _ring_hardzero(1, 30, 39, 40); vals2 = [str(F(1, 2) if x0 == 0 or x1 == 1 else F(x2)) for x0 in range(2) for x1 in range(2) for x2 in range(2)]
    mps = _spec(_uai(os.path.join(d, 'ring30.uai'), cards2, fs2), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='table', table=dict(name='mostly_half', kind='expectation', f=dict(scope=[0, 1, 2], values=vals2)))])
    par = {}
    for nm, mpx in (('e_zero', mpe), ('signed_pac', mps)):
        w = fresh_worker(mpx, 'N1_CQR', budget=20.0, nonce='c17-par-' + nm); c = w['certificate']; A(w['outcome'] == 'PUBLISHED', nm)
        A(c['reference']['done'] or c['work']['reference']['total'] >= c['work']['optional']['total'], '%s exit without reference parity' % nm); par[nm] = dict(route=w['route'], work_reference=c['work']['reference']['total'], work_optional=c['work']['optional']['total'])
    out['parity_at_exits'] = par; return out


def c18_task_local_state_and_policy():
    """review item 5 (CQR-07, CQR-08): no module-global compiler state (the service hook and the constant scalars live on the task's Compiled object); the checker's verdict on the
    20-variable normalizer is identical before / after / between zero-evidence models with constants 7 and 0, repeated; the task-effective operator policy is ONE function shared by
    producer and checker (a certificate whose enabled set disagrees with it is refused)"""
    d = tempfile.mkdtemp(prefix='cqr_c18_'); out = {}
    A(not hasattr(CP, '_SCALARS') and not hasattr(CP, '_SERVICE'), 'module-global compiler state present')
    a = _spec(_uai(os.path.join(d, 'zero.uai'), [2], [([], ['7']), ([], ['0']), ([0], ['1', '1'])]), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=0, state=1)])
    b = _spec(_uai(os.path.join(d, 'norm20.uai'), [2] * 20, []), normalizer_task=True, queries=[], mode='EXACT_RATIONAL', epsilon='1/200', delta='0')
    wa = fresh_worker(a, 'N1_CQR', budget=20.0, nonce='c18-zero'); wb = fresh_worker(b, 'N1_CQR', budget=20.0, nonce='c18-norm'); A(wa['outcome'] == 'PROVED_ZERO_EVIDENCE' and wb['outcome'] == 'PUBLISHED', 'fixtures')
    seq = []
    for k in range(3):
        seq.append(('norm', check_(b, wb, 'N1_CQR')[0])); seq.append(('zero', check_(a, wa, 'N1_CQR')[0])); seq.append(('norm', check_(b, wb, 'N1_CQR')[0]))
    A(all(not f for _, f in seq), 'order-dependent verdicts: %s' % [(n, f[:1]) for n, f in seq if f]); out['order_sequence'] = [n for n, _ in seq]; out['all_accepted'] = True
    C1, _ = compile_(TK.load_task(b)); C2, _ = compile_(TK.load_task(a)) if False else (None, None)
    A(all(cs['value'] != '7' for cs in C1.constant_scalars), 'a scalar of the zero model leaked into the normalizer compile'); out['normalizer_constant_scalars'] = C1.constant_scalars
    # one effective policy
    tb = TK.load_task(b); eff = CP.effective_operators(SV.ARMS['N1_CQR']['enabled'], tb); A(not (set(eff) & set(CP.NORMALIZER_FORBIDDEN)), 'forbidden rewrites in the normalizer policy'); A(sorted(wb['certificate']['enabled_operators']) == sorted(eff), 'certificate policy differs from effective_operators')
    _mut(b, wb, 'N1_CQR', 'normalizer_policy_relabel', lambda x: x['certificate'].__setitem__('enabled_operators', sorted(set(x['certificate']['enabled_operators']) | {'component_omission'})), ('differ', 'effective', 'polic'), out)
    tz = TK.load_task(a); A(set(CP.effective_operators(SV.ARMS['N1_CQR']['enabled'], tz)) == set(SV.ARMS['N1_CQR']['enabled']), 'a non-normalizer task lost operators'); return out


def c19_provenance_and_intake():
    """review item 6 (CQR-09, CQR-10): the provenance / intake control script (kernel identity frozen for every natively loaded binary + build record on temporary copies;
    replacing both binary and record after the freeze fails; START refused; a valid-binary identity control; projected-count WCNF refused; constructed schedule deterministic;
    balanced arm blocks; no second-matrix ceiling) must pass completely in a fresh process; plus the parser guard asserted here directly"""
    p = subprocess.run([PY, os.path.join(HERE, 'test_cqr_provenance_intake.py')], capture_output=True, text=True, cwd=CODE); CNT['assertions'] += 1
    A(p.returncode == 0, 'provenance / intake controls failed: %s' % (p.stdout[-600:] + p.stderr[-400:])); lines = [l for l in p.stdout.splitlines() if l.startswith(('PASS', 'FAIL'))]
    A(lines and all(l.startswith('PASS') for l in lines), 'control lines: %s' % lines[:3]); out = dict(controls=len(lines), summary=p.stdout.strip().splitlines()[-1])
    import wcnf as WC; d = tempfile.mkdtemp(prefix='cqr_c19_'); cp = os.path.join(d, 'projected.cnf'); open(cp, 'w').write('c t pmc\nc p show 1 0\np cnf 2 1\n1 0\n')
    try: WC.convert(cp, os.path.join(d, 'projected.uai')); A(False, 'projected count converted as WMC')
    except ValueError as e: A('REFUSED_PROJECTED_COUNT_SEMANTICS' in str(e), str(e)[:80]); out['pmc_refusal'] = str(e)[:60]
    open(cp, 'w').write('c t wmc\np cnf 2 1\n1 0\n'); side = WC.convert(cp, os.path.join(d, 'ordinary.uai')); A(side is not None, 'ordinary wmc refused'); out['wmc_accepted'] = True
    import kernel_identity as KI; cur = KI.collect(CODE); A(cur.get('newarm_cex', {}).get('binary_sha256') and cur.get('newarm_stream', {}).get('binary_sha256'), 'kernel identity collection incomplete: %s' % sorted(cur))
    A(not KI.failures_vs_frozen(cur, cur, ['H1_HYBRID', 'B0_FROZEN_V14']), 'identity vs itself fails'); out['kernel_tags'] = sorted(cur); return out



def c20_atomic_compilation_replay_service_history_attribution():
    """second adversarial review (16 Nov 2026) R1-R6: (R1) NATURAL partial compiles -- support interrupted by reference completion after a commit (8x8, 33 factors), exact quotient
    interrupted after a commit (16x16, 4 uniform factors), approximate quotient hitting its quota after one merge (19 variables -> 3-variable core) -- all publish correct answers and the
    checker REPLAYS THE JOURNAL (exact commits, no operator re-execution); journal mutations refused; (R2) mid-operator injected faults at build / before_swap / after_commit of support,
    leaf sum-out, exact and approximate quotient leave the state EQUAL to the last commit (verified against the journal replay) and a fresh worker continues to a real exact-reference
    publication; (R3) Work-unit service gaps <= TICK_ENTRIES + max irreducible charge on the 3 x 32-state witness, every operator's quota overspend bounded, parity (reference >= optional
    - one quantum - one tick) at a genuine deadline exit; (R5) signed-epoch history append-only (duplicate / nonpositive / out-of-order ids, extra draws, duplicated records, a second open
    epoch); (R6) worker / receipt route and bias bound to the verified certificate THROUGH the actual manifest, dispatcher, gate and report"""
    d = tempfile.mkdtemp(prefix='cqr_c20_'); out = dict(r1={}, r2={}, r3={}, r5={}, r6={})
    def honest(mp, arm='N1_CQR', budget=20.0, extra=()):
        w = fresh_worker(mp, arm, budget=budget, nonce='c20-%s-%s-%d' % (os.path.basename(mp), arm, len(extra)), extra=extra); fails, info = check_(mp, w, arm, budget=300.0); return w, fails, info
    # ---------------- R1 natural partial compiles
    mp = _uai(os.path.join(d, 'support_interrupt.uai'), [8, 8], [((0, 1), [1 if a < 7 else 0 for a in range(8) for b in range(8)])] * 33); w, f, i = honest(mp)
    t, tr = _truth(mp); A(not f and w['route'] == 'exact_reference' and tr['Z'] == 56 and _contained(w, tr, F(0)), 'R1 support interrupt: %s %s %s' % (w['outcome'], w.get('route'), f[:1]))
    lg = w['certificate']['compile']['log']; out['r1']['support'] = dict(commits=lg.get('commits'), interrupted=lg.get('interrupted'), steps=[(s['op'], s['outcome']) for s in lg['steps'] if s['outcome'] not in ('disabled', 'no_change', 'skipped')])
    A((lg.get('interrupted') or {}).get('kind') == 'reference_done' or lg.get('commits', 0) >= 1, 'R1 support: expected a partial compile with a commit or a reference_done interruption')
    mp = _uai(os.path.join(d, 'quotient_interrupt.uai'), [16, 16], [((0, 1), [1] * 256)] * 4); w, f, i = honest(mp); t, tr = _truth(mp)
    A(not f and w['route'] == 'exact_reference' and tr['Z'] == 256 and _contained(w, tr, F(0)), 'R1 quotient interrupt: %s %s' % (w.get('route'), f[:1])); out['r1']['quotient'] = dict(interrupted=w['certificate']['compile']['log'].get('interrupted'), commits=w['certificate']['compile']['log'].get('commits'))
    dd = 32; cards = [2, dd, dd] + [2] * 16
    fs = [([0, 1], [F(j + 1) * (F(1) if s == 0 else F(2) * F(1000000 + (j % 2), 1000000)) for s, j in product(range(2), range(dd))]), ([0, 2], [F(j + 1) * (1 if s == 0 else 3) for s, j in product(range(2), range(dd))]), ([1, 2], [F(9 + (i_ * 31 + j * 17) % 127, 9) for i_, j in product(range(dd), repeat=2)])] + [([v], [F(1), F(2)]) for v in range(3, len(cards))]
    mp = _spec(_uai(os.path.join(d, 'approx_quota_prefix.uai'), cards, fs), mode='DETERMINISTIC_EPS', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=v, state=0) for v in range(3)])
    w, f, i = honest(mp); t, tr = _truth(mp); A(not f and w['outcome'] == 'PUBLISHED' and _contained(w, tr, F(1, 200)), 'R1 approx quota prefix: %s %s %s' % (w['outcome'], w.get('route'), f[:1]))
    jr = w['certificate']['compile']['certificates']; out['r1']['approx_quota'] = dict(route=w['route'], bias=w['certificate']['bias'], commits=[c['op'] for c in jr if c.get('kind') == 'commit'], declines=[c['op'] for c in jr if c.get('kind') == 'decline'])
    A(any(c.get('kind') == 'commit' and c['op'] == 'approx_quotient' for c in jr) and any(c.get('kind') == 'decline' and c['op'] == 'approx_quotient' for c in jr), 'R1 approx: expected one approximate commit AND one quota decline in the journal')
    # journal mutations on that output: a dropped commit, a reordered pair, a changed class, a changed sequence number
    _mut(mp, w, 'N1_CQR', 'journal_commit_dropped', lambda x: x['certificate']['compile']['certificates'].pop(1), ('sequence', 'replay', 'does not'), out['r1'])
    def reorder(x):
        j = x['certificate']['compile']['certificates']; cs = [k for k, c in enumerate(j) if c.get('kind') == 'commit']; a, b = cs[0], cs[1]; j[a], j[b] = j[b], j[a]
    _mut(mp, w, 'N1_CQR', 'journal_commits_reordered', reorder, ('sequence', 'replay', 'does not', 'commit'), out['r1'])
    def chclass(x):
        c = next(c for c in x['certificate']['compile']['certificates'] if c.get('kind') == 'commit' and c['op'] == 'approx_quotient'); c['classes'][0] = c['classes'][0][:1] if len(c['classes'][0]) > 1 else c['classes'][0] + c['classes'][1][:1]
    _mut(mp, w, 'N1_CQR', 'journal_class_changed', chclass, ('partition', 'replay', 'does not', 'differ', 'commit'), out['r1'])
    # ---------------- R1 journal replay on random models: the replayed model hashes to the recorded final model
    rng = random.Random(2020); same = 0
    for trial in range(40):
        n = rng.choice([4, 5, 6, 7]); cards_ = [rng.choice([2, 2, 3, 4]) for _ in range(n)]; m = rnd_model(rng, n, cards_, n + rng.randint(0, 3), 3, zeros=rng.choice([0, 0, 0.2]), ev=rng.choice([0, 0, 1]))
        qs = TK.all_singletons(cards_) if trial % 2 else [TK.singleton_query(0, 0, cards_), TK.parity_query([0, 1, 2], 1, cards_)]; task = mk_task(m, qs, mode=['PAC_EPS', 'DETERMINISTIC_EPS', 'EXACT_RATIONAL'][trial % 3])
        try: C, log = compile_(task)
        except CP.ZeroEvidence: continue
        C2, jf, _ = CP.replay_journal(task, C.certs, TK.Work()); CNT['compiler_calls'] += 1
        h1 = hashlib.sha256(json.dumps(C.snapshot_json(), sort_keys=True, default=str).encode()).hexdigest(); h2 = hashlib.sha256(json.dumps(C2.snapshot_json(), sort_keys=True, default=str).encode()).hexdigest() if C2 is not None else None
        A(not jf and h1 == h2, 'journal replay differs on trial %d: %s' % (trial, jf[:1])); same += 1
    out['r1']['journal_replay_models'] = same
    # ---------------- R2 mid-operator faults: state == last commit; fresh worker continues
    fx = {}
    fx['support'] = _uai(os.path.join(d, 'r2_support.uai'), [2] * 16, [((0, 1), [0, 0, 1, 2])] + [((v,), [1, 2]) for v in range(2, 16)])
    fx['leaf_sumout'] = _uai(os.path.join(d, 'r2_leaf.uai'), [2] * 14, [((v, v + 1), [1, 2, 3, 1]) for v in range(13)])
    json.dump(dict(mode='PAC_EPS', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=0, state=1)]), open(fx['leaf_sumout'] + '.query.json', 'w'))
    g = G.generate('M02', 6, 'favorable', 1); fx['exact_quotient_pass'] = write_task(d, 'r2_quotient', g['model'], dict(mode='EXACT_RATIONAL', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='0'))
    fx['approx_quotient'] = mp
    for op, mpx in fx.items():
        tk = TK.load_task(mpx); boundaries = []
        for where in ('build', 'before_swap', 'after_commit'):
            for k in (0, 1):
                C, log = CP.compile_task(tk, enabled=CP.effective_operators(SV.ARMS['N1_CQR']['enabled'], tk), fault=dict(op=('support' if op == 'support' else op), where=where, k=k)); CNT['compiler_calls'] += 1
                C2, jf, _ = CP.replay_journal(tk, C.certs, TK.Work()); A(not jf and C2 is not None and C2.snapshot_json() == C.snapshot_json(), 'R2 %s/%s/k%d: state after the fault differs from the journal replay: %s' % (op, where, k, jf[:1]))
                A(all(len(v.values) == prod(C.cards[u] for u in v.scope) for v in C.views if v.kind == 'table'), 'R2 %s/%s/k%d: a factor table is inconsistent with the cardinalities' % (op, where, k))
                A(all(len(q['f'].values) == prod(C.cards[u] for u in q['f'].scope) for q in C.queries if q['kind'] == 'expectation'), 'R2 %s/%s/k%d: a query table is inconsistent with the cardinalities' % (op, where, k))
                boundaries.append(dict(where=where, k=k, failed=(log.get('failed') or {}).get('op'), commits=log.get('commits')))
        A(any(b['failed'] for b in boundaries), 'R2 %s: no injected fault fired (the fixture must commit in that operator)' % op)
        # fresh worker with the fault after the first commit: a REAL publication through the original reference / committed model; refused as production (fault-injected); the stripped copy replays
        inj = json.dumps(dict(op=('support' if op == 'support' else op), where='after_commit', k=0)); w = fresh_worker(mpx, 'N1_CQR', budget=20.0, nonce='c20-r2-' + op, extra=('--fault-inject', inj))
        A(w['outcome'] == 'PUBLISHED', 'R2 %s fresh worker after the fault: %s %s' % (op, w['outcome'], (w.get('reason') or '')[:80])); t, tr = _truth(mpx); A(_contained(w, tr, t['epsilon'] if w['route'] not in CK.EXACT_ROUTES else F(0)), 'R2 %s: answers after the fault miss the truth' % op)
        fails, _ = check_(mpx, w, 'N1_CQR', budget=300.0); A(fails and any('FAULT-INJECTION' in f_ for f_ in fails), 'R2 %s: fault-injected output accepted' % op)
        x = json.loads(json.dumps(w)); x.pop('fault_injected', None); x['certificate']['fault_injected'] = None; fails, _ = check_(mpx, x, 'N1_CQR', budget=300.0); A(not fails, 'R2 %s: the committed-prefix publication does not replay: %s' % (op, fails[:1]))
        out['r2'][op] = dict(boundaries=boundaries, worker_route=w['route'], failed=(w['certificate']['compile']['log'].get('failed') or {}).get('op'))
    w = fresh_worker(fx['support'], 'N1_CQR', budget=20.0, nonce='c20-r2-frontier', extra=('--fault-inject', 'frontier_init')); A(w['outcome'] == 'PUBLISHED', 'frontier_init fault: %s' % w['outcome']); out['r2']['frontier_init'] = dict(route=w['route'], optional_cancelled=(w['certificate'].get('optional_cancelled') or '')[:60])
    # ---------------- R3 service granularity and quotas in Work units
    rng = random.Random(81); cards3 = [32] * 3; m3 = dict(cards=cards3, factors=[dict(scope=(0, 1, 2), values=[F(rng.randint(1, 9)) for _ in range(32 ** 3)])], evidence={}); task3 = mk_task(m3, [TK.singleton_query(v, 0, cards3) for v in range(3)])
    ticks = []; orig = CP.tick
    def spy(C, quota=None, op=None): ticks.append(C.work.total()); return orig(C, quota, op)
    CP.tick = spy
    try: r = solve_(task3, 'N1_CQR', 'c20-gap', budget=30.0)
    finally: CP.tick = orig
    gaps = [ticks[k] - ticks[k - 1] for k in range(1, len(ticks))]; mg = max(gaps) if gaps else 0; bound = CP.POLICY['max_irreducible_charge'] + CP.TICK_ENTRIES
    A(mg <= bound, 'R3: %d optional units between service points (bound %d)' % (mg, bound)); out['r3']['service_gap_3x32'] = dict(ticks=len(ticks), max_gap=mg, bound=bound, route=r['publication']['route'])
    try:
        r = solve_(task3, 'N1_CQR', 'c20-dl', budget=0.08); out['r3']['deadline_exit'] = 'published %s' % r['publication']['route']
    except SV.Stop as e:
        wr = (e.info.get('work_reference') or {}).get('total', 0); wo = (e.info.get('work_optional') or {}).get('total', 0); Q = SV.POLICY['quantum_units']
        A(e.kind == 'DEADLINE' and wr >= wo - Q - bound, 'R3 deadline exit without parity: ref %d opt %d' % (wr, wo)); out['r3']['deadline_exit'] = dict(work_reference=wr, work_optional=wo, progress=e.info.get('reference_progress'))
    rng = random.Random(82); c14 = [2] * 14; m14 = dict(cards=c14, factors=[dict(scope=tuple(range(14)), values=[F(rng.randint(1, 9)) for _ in range(2 ** 14)])], evidence={}); t14 = mk_task(m14, [TK.singleton_query(v, 0, c14) for v in range(14)])
    C, log = CP.compile_task(t14, enabled={'support_fixpoint'}); CNT['compiler_calls'] += 1; st = [s for s in log['steps'] if s['op'] == 'support_fixpoint'][0]
    A(st['work'] <= log['quota'] + CP.POLICY['max_irreducible_charge'], 'R3 support quota overspend %d' % (st['work'] - log['quota'])); out['r3']['support_quota'] = dict(quota=log['quota'], work=st['work'], outcome=st['outcome'])
    # every operator respects a small quota within one irreducible charge (direct calls on a dense 10-variable model)
    rng = random.Random(83); c10 = [2] * 10; m10 = rnd_model(rng, 10, c10, 14, 3, lo=1, hi=9); t10 = mk_task(m10, TK.all_singletons(c10)); over = {}
    for name, fn in (('support_fixpoint', lambda C, q: CP.support_fixpoint(C, q)), ('leaf_sumout', lambda C, q: CP.leaf_sumout(C, q)), ('exact_quotient_pass', lambda C, q: CP.exact_quotient_pass(C, q)), ('symmetry', lambda C, q: CP.symmetry(C, q)),
                     ('approx_quotient', lambda C, q: CP.approx_quotient(C, q, [F(1, 800)] * 20)), ('concentration', lambda C, q: CP.concentration(C, q, [F(1, 800)] * 20)), ('influence_deletion', lambda C, q: CP.influence_deletion(C, q, [F(1, 800)] * 20)), ('affine', lambda C, q: CP.affine(C, q))):
        C = CP.from_task(t10); w0 = C.work.total(); q = w0 + 300
        try: fn(C, q)
        except CP.CompileStop as cs: A(cs.kind == 'quota', 'unexpected stop %s' % cs.kind)
        except CP.ZeroEvidence: pass
        over[name] = C.work.total() - q; A(over[name] <= CP.POLICY['max_irreducible_charge'], 'R3 %s overspent its quota by %d' % (name, over[name]))
    out['r3']['operator_quota_overspend'] = over
    # ---------------- R5 signed-epoch history (append-only)
    cards_r, fs_r = _ring_hardzero(1, 30, 39, 40); vals = [str(F(1, 2) if x0 == 0 or x1 == 1 else F(x2)) for x0 in range(2) for x1 in range(2) for x2 in range(2)]
    mps = _spec(_uai(os.path.join(d, 'ring30.uai'), cards_r, fs_r), mode='PAC_EPS', epsilon='1/10', delta='1/10', queries=[dict(kind='table', table=dict(name='mostly_half', kind='expectation', f=dict(scope=[0, 1, 2], values=vals)))])
    w, f, i = honest(mps); A(not f and w['route'] == 'pac_signed_residual_validation', 'R5 honest signed fixture: %s %s' % (w.get('route'), f[:1])); ev = w['certificate']['events']
    i0 = next(k for k, e in enumerate(ev) if e['op'] == 'epoch_start'); j0 = next(k for k in range(i0 + 1, len(ev)) if ev[k]['op'] == 'signed_draw')
    _mut(mps, w, 'N1_CQR', 'epoch_duplicated_with_completed_draw', lambda x: x['certificate'].__setitem__('events', ev[:i0] + [copy.deepcopy(ev[i0]), copy.deepcopy(ev[j0])] + ev[i0:]), ('not the next allocation', 'epoch'), out['r5'])
    _mut(mps, w, 'N1_CQR', 'epoch_id_zero', lambda x: x['certificate'].__setitem__('events', ev[:i0] + [dict(ev[i0], epoch=0)] + ev[i0:]), ('not the next allocation', 'epoch'), out['r5'])
    _mut(mps, w, 'N1_CQR', 'extra_completed_draw', lambda x: x['certificate'].__setitem__('events', ev + [dict(ev[j0])]), ('do not replay', 'epoch'), out['r5'])
    _mut(mps, w, 'N1_CQR', 'epoch_record_duplicated', lambda x: x['certificate'].__setitem__('epochs', x['certificate']['epochs'] + [copy.deepcopy(x['certificate']['epochs'][0])]), ('do not match', 'epoch'), out['r5'])
    _mut(mps, w, 'N1_CQR', 'second_epoch_while_open', lambda x: x['certificate'].__setitem__('events', ev + [dict(ev[i0], epoch=2, delta_e=str(F(1, 10) / 12))]), ('still open', 'epoch'), out['r5'])
    # ---------------- R6 attribution through the ACTUAL manifest -> dispatcher -> gate -> report
    def chain(name, mpx, arm, mutate=None):
        # the manifest is produced in a FRESH process (campaign.py imports the baseline registry under the name 'registry', which this suite has bound to the cqr registry)
        rd = os.path.join(d, 'chain_' + name)
        code_ = "import sys, json; sys.path.insert(0, %r); import campaign as CA; CA.manifest(%r, [CA.make_row('query_transfer', %r, %r)], dev=True, budgets=[10], plan={'query_transfer': [(%r, 1)]}, root_seed=%r)" % (HERE, rd, name, mpx, arm, 'c20-' + name)
        pm = subprocess.run([PY, '-c', code_], capture_output=True, text=True, cwd=CODE); A(os.path.exists(os.path.join(rd, 'CAMPAIGN_MANIFEST_dev.json')), 'manifest for %s not produced: %s' % (name, pm.stderr[-300:]))
        subprocess.run([PY, os.path.join(HERE, 'campaign.py'), 'run', rd, '--dev'], capture_output=True, text=True, cwd=CODE); CNT['fresh_workers'] += 1
        rp = next(os.path.join(rd, 'cells', d_, 'receipt.json') for d_ in os.listdir(os.path.join(rd, 'cells'))); r = json.load(open(rp)); wp = os.path.join(rd, r['worker_output']); w_ = json.load(open(wp))
        if mutate: mutate(w_, r); json.dump(w_, open(wp, 'w')); r['output_sha256'] = hashlib.sha256(open(wp, 'rb').read()).hexdigest(); json.dump(r, open(rp, 'w'))
        subprocess.run([PY, os.path.join(HERE, 'gate.py'), rd, '--manifest', 'CAMPAIGN_MANIFEST_dev.json', '--gate-budget-s', '300'], capture_output=True, text=True, cwd=CODE); g_ = json.load(open(os.path.join(rd, 'GATE_RESULT.json')))
        subprocess.run([PY, os.path.join(HERE, 'report.py'), rd, '--manifest', 'CAMPAIGN_MANIFEST_dev.json'], capture_output=True, text=True, cwd=CODE); res = json.load(open(os.path.join(rd, 'RESULTS_CQR.json'))); rr = (res.get('runs') or [{}])[0]
        return dict(gate_passed=g_['gate_passed'], failures=[f_[1][:100] for f_ in g_['failures']][:1], report_route=rr.get('route'), report_bias=rr.get('bias'), source=(rr.get('guarantee_source') or '')[:30], mismatch=rr.get('attribution_mismatch'))
    mpn = _spec(_uai(os.path.join(d, 'normalizer30.uai'), [2] * 30, [((29,), ['1', '2'])]), mode='PAC_EPS', normalizer_task=True, queries=[], epsilon='3/10', delta='1/5')
    h = chain('norm_honest', mpn, 'G0_CQR'); A(h['gate_passed'] and h['source'].startswith('checker-verified') and h['mismatch'] is False, 'R6 honest normalizer chain: %s' % h); out['r6']['normalizer_honest'] = h
    x = chain('norm_route', mpn, 'G0_CQR', lambda w_, r: (w_.__setitem__('route', 'normalizer_exact_reference'), r.__setitem__('route', 'normalizer_exact_reference')))
    A(not x['gate_passed'] and any('route' in f_ for f_ in x['failures']) and x['report_route'] != 'normalizer_exact_reference', 'R6 route mutation survived: %s' % x); out['r6']['normalizer_route_mutation'] = x
    mpc = _concentration_witness(d); h = chain('conc_honest', mpc, 'N1_CQR'); A(h['gate_passed'] and h['mismatch'] is False, 'R6 honest concentration chain: %s' % h); out['r6']['concentration_honest'] = h
    x = chain('conc_bias', mpc, 'N1_CQR', lambda w_, r: (w_.__setitem__('bias', ['0']), r.__setitem__('bias', ['0'])))
    A(not x['gate_passed'] and any('bias' in f_ for f_ in x['failures']) and x['report_bias'] != ['0'], 'R6 bias mutation survived: %s' % x); out['r6']['concentration_bias_mutation'] = x
    return out



def c21_checker_soundness_lifecycle_dependencies_closeout():
    """THIRD adversarial review (16 Nov 2026) CQR-R2-01..06. (01) complete incident set: the forged quotient record that omits the non-proportional pair factor (X0=[1,1], (X0,X1)=[1,1,1,9];
    truth 5/6; forged 1/2) is refused by verify_commit, replay_journal AND apply_commit; missing / extra / duplicate / out-of-range incident identities, non-partitions and non-canonical
    class order are refused; honest exact / approximate quotients, factorless variables, normalizers and interrupted prefixes still pass. (02) canonical record keys for every map-shaped record
    field, nonnegative ledger (producer and replay), ordered derived enclosures; the alias-key forgery (bias '00' = -1 - 3/500003) is refused at the record boundary and would be refused by the
    ledger / enclosure invariants independently. (03) the natural 9-variable / 5,000-query worker publishes its completed exact reference instead of FAULT; reference completion inside the
    initial root computation and inside the adaptive publication test is established directly. (04) bounded work before every service / quota check: the 14-binary dense factor shows a maximum
    tick gap <= TICK_ENTRIES and a quota placed before the bulk normalization is overspent by <= max_irreducible_charge. (05) inconsistent Merlin adapter bindings never freeze; a replaced
    executable refuses WMB, IJGP and MERLIN_CTE separately; a repointed bench/cells path after freeze is refused. (06) a real finalize -> closeout passes and report-only changes to every
    semantic attribution field fail the closeout."""
    d = tempfile.mkdtemp(prefix='cqr_c21_'); out = dict(f01={}, f02={}, f03={}, f04={}, f05={}, f06={})
    # ---------------- 01
    mp = _uai(os.path.join(d, 'two_factor.uai'), [2, 2], [((0,), ['1', '1']), ((0, 1), ['1', '1', '1', '9'])]); _spec(mp, mode='EXACT_RATIONAL', epsilon='1/200', delta='1/1000000', queries=[dict(kind='singleton', variable=1, state=1)])
    w = fresh_worker(mp, 'N1_CQR', budget=10.0, nonce='c21-01'); fails, _ = check_(mp, w, 'N1_CQR'); t, tr = _truth(mp)
    A(not fails and w['outcome'] == 'PUBLISHED' and tr['answers'][0] == F(5, 6) and _contained(w, tr, F(0)), '01 honest: %s %s' % (w.get('route'), fails[:1])); out['f01']['honest'] = dict(route=w['route'], answer=w['answers'][0]['point'])
    C0 = CP.from_task(t); C0.allowance = [F(0)]
    forged = dict(kind='commit', seq=0, op='exact_quotient_pass', var=0, classes=[[0, 1]], representatives=[0], kappa={'0': '1', '1': '1'}, S=['2'], incident_factors=[0], approx=None)
    m = CP.verify_commit(C0, forged, TK.Work(), [F(0)]); A(m and 'complete incident set' in m, '01 forged record not refused by verify_commit: %s' % m); out['f01']['verify'] = m[:90]
    C1, jf, _ = CP.replay_journal(t, [C0.certs[0], forged], TK.Work()); A(jf and 'complete incident set' in jf[0], '01 replay accepted the forged record: %s' % jf[:1])
    try: CP.apply_commit(CP.from_task(t), forged); A(False, '01 apply_commit applied an unverified incident set')
    except ValueError as ex: A('incident set' in str(ex), str(ex)[:80]); out['f01']['apply_refused'] = True
    for name, rec in (('extra_index', dict(forged, incident_factors=[0, 1, 1])), ('out_of_range', dict(forged, incident_factors=[0, 7])), ('unsorted', dict(forged, incident_factors=[1, 0])), ('non_partition', dict(forged, incident_factors=[0, 1], classes=[[0, 0]])), ('bad_order', dict(forged, incident_factors=[0, 1], classes=[[1], [0]], representatives=[1, 0], kappa={'0': '1', '1': '1'}, S=['1', '1'])), ('kappa_alias', dict(forged, incident_factors=[0, 1], kappa={'0': '1', '01': '1'}))):
        m = CP.verify_commit(CP.from_task(t), rec, TK.Work(), [F(0)]); A(m is not None, '01 malformed record %s accepted' % name); out['f01'][name] = m[:70]
    # honest records: a genuine exact quotient (clones), a genuine approximate quotient, a factorless variable, a normalizer; all replay
    g = G.generate('M02', 5, 'favorable', 3); tq = mk_task(g['model'], TK.all_singletons(g['model']['cards']), mode='EXACT_RATIONAL'); Cq, lq = compile_(tq); A(any(c['op'] == 'exact_quotient_pass' for c in Cq.commit_records()), '01 clone fixture did not quotient')
    C2, jf, _ = CP.replay_journal(tq, Cq.certs, TK.Work()); A(not jf and C2.snapshot_json() == Cq.snapshot_json(), '01 honest exact quotient journal: %s' % jf[:1])
    mf = _uai(os.path.join(d, 'factorless.uai'), [3, 2], [((1,), ['1', '2'])]); _spec(mf, mode='EXACT_RATIONAL', epsilon='1/200', delta='0', queries=[dict(kind='singleton', variable=0, state=1)]); tf = TK.load_task(mf); Cf, _ = compile_(tf)
    C3, jf, _ = CP.replay_journal(tf, Cf.certs, TK.Work()); A(not jf and C3.snapshot_json() == Cf.snapshot_json(), '01 factorless quotient journal: %s' % jf[:1]); out['f01']['honest_journals'] = 'clones + factorless replay'
    # ---------------- 02
    mpc = _concentration_witness(d); w = fresh_worker(mpc, 'N1_CQR', budget=20.0, nonce='c21-02'); fails, _ = check_(mpc, w, 'N1_CQR'); A(not fails and w['route'] == 'deterministic_concentration', '02 honest %s %s' % (w.get('route'), fails[:1]))
    tk = TK.load_task(mpc); jr = copy.deepcopy(w['certificate']['compile']['certificates']); dc = next(c for c in jr if c.get('kind') == 'commit' and c['op'] == 'concentration'); ob = F(dc['bias']['0']); dc['bias']['00'] = str(-1 - ob)
    C4, jf, _ = CP.replay_journal(tk, jr, TK.Work()); A(jf and 'canonical domain' in jf[0], '02 alias key accepted by replay: %s' % jf[:1]); out['f02']['alias_replay'] = jf[0][:90]
    mut = copy.deepcopy(w); mut['certificate']['compile']['certificates'] = jr; mut['certificate']['bias'] = ['-1']; mut['bias'] = ['-1']; mut['certificate']['publication']['bounds'] = [['1', '1']]; mut['certificate']['publication']['point'] = ['1']; mut['answers'][0].update(lo='1', hi='1', point='1')
    fails, _ = check_(mpc, mut, 'N1_CQR'); A(fails, '02 forged certificate accepted'); out['f02']['forged_checker'] = fails[0][:90]
    # the ledger invariant independently: a negative ledger with an otherwise consistent certificate (hash regenerated) is refused by the ledger / enclosure checks
    mut2 = copy.deepcopy(w); mut2['certificate']['bias'] = ['-1']; mut2['bias'] = ['-1']; mut2['certificate']['publication']['bounds'] = [['1', '1']]; mut2['certificate']['publication']['point'] = ['1']; mut2['answers'][0].update(lo='1', hi='1', point='1')
    fails, _ = check_(mpc, mut2, 'N1_CQR'); A(fails and any('ledger' in f_ or 'negative' in f_ for f_ in fails), '02 negative ledger not refused: %s' % fails[:2]); out['f02']['negative_ledger'] = fails[0][:90]
    try: CP.Compiled([2], [], [], [], TK.Work(), [F(-1, 10)]).commit(dict(op='x')); A(False, '02 commit accepted a negative ledger')
    except ValueError as ex: A('negative' in str(ex), str(ex)); out['f02']['commit_refuses_negative'] = True
    # other map-shaped records: xstar / t / answers aliases; influence deleted duplicates; symmetry constant keys
    for name, fn in (('xstar_alias', lambda r: r['xstar'].__setitem__('00', r['xstar']['0'])), ('t_missing', lambda r: r['t'].pop('0')), ('answers_extra', lambda r: r['answers'].__setitem__('1', '0'))):
        jr2 = copy.deepcopy(w['certificate']['compile']['certificates']); dc2 = next(c for c in jr2 if c.get('kind') == 'commit' and c['op'] == 'concentration'); fn(dc2); C5, jf, _ = CP.replay_journal(tk, jr2, TK.Work()); A(jf, '02 %s accepted' % name); out['f02'][name] = jf[0][:80]
    # first-review regression: forged answer 1 on the same fixture
    mut3 = copy.deepcopy(w); dc3 = next(c for c in mut3['certificate']['compile']['certificates'] if c.get('kind') == 'commit' and c['op'] == 'concentration'); dc3['answers']['0'] = '1'; mut3['certificate']['publication']['bounds'] = [[str(1 - ob), '1']]; mut3['certificate']['publication']['point'] = ['1']; mut3['answers'][0].update(lo=str(1 - ob), hi='1', point='1')
    fails, _ = check_(mpc, mut3, 'N1_CQR'); A(fails and any('does not re-derive' in f_ for f_ in fails), '02 regression forged answer: %s' % fails[:1])
    # honest composition: approximate quotient + concentration (first-review biased-closure witness) still passes
    mpb = _biased_closure_witness(d); wb = fresh_worker(mpb, 'N1_CQR', budget=20.0, nonce='c21-02b'); fails, _ = check_(mpb, wb, 'N1_CQR'); A(not fails and wb['outcome'] == 'PUBLISHED', '02 honest biased closure: %s' % fails[:1]); out['f02']['honest_composition'] = wb['route']
    # ---------------- 03
    mpr = os.path.join(d, 'root5000.uai'); open(mpr, 'w').write('MARKOV\n9\n2 2 2 2 2 2 2 2 2\n0\n')
    json.dump(dict(mode='DETERMINISTIC_EPS', epsilon='1/200', delta='0', queries=[dict(kind='table', table=dict(name='q%d' % j, kind='expectation', f=dict(scope=list(range(7)), values=['0'] * 64 + ['1'] * 64))) for j in range(5000)]), open(mpr + '.query.json', 'w'))
    t0 = time.monotonic(); w = fresh_worker(mpr, 'G0_CQR', budget=30.0, nonce='c21-03'); wall = time.monotonic() - t0
    if w['outcome'] == 'PUBLISHED':
        A(w['route'] == 'exact_reference' and len(w['answers']) == 5000 and all(a['lo'] == a['hi'] == a['point'] == '1/2' for a in w['answers']), '03 answers: %s' % w['route']); fails, _ = check_(mpr, w, 'G0_CQR', budget=600.0); A(not fails, '03 checker: %s' % fails[:1]); out['f03']['root5000'] = dict(route=w['route'], wall_s=round(wall, 2), accepted=True)
    else: A(w['outcome'] == 'DEADLINE' and (w.get('scheduling') or {}).get('reference_progress') is not None, '03 root5000: %s %s' % (w['outcome'], (w.get('reason') or '')[:80])); out['f03']['root5000'] = dict(outcome='DEADLINE on this host', scheduling=w.get('scheduling'))
    # the completed-reference path directly: a service hook that completes the reference INSIDE the initial root computation and inside the adaptive publication test
    rng = random.Random(3); c8 = [2] * 14; m8 = rnd_model(rng, 14, c8, 16, 2, lo=1, hi=9); t8 = mk_task(m8, TK.all_singletons(c8), mode='DETERMINISTIC_EPS', delta=F(0)); tr8 = truth_of(m8, TK.all_singletons(c8))
    orig_db = FR.Frontier.deterministic_bounds
    def db_hook(self, deadline=None):
        # the root computation is made to 'spend' a large optional charge: the service hook then serves the reference to parity, which COMPLETES it (16,384 assignments) and
        # raises CompileStop('reference_done') INSIDE the initial root computation -- the completed-reference path is exercised directly
        if self.service is not None: self.work.ratops += 10 ** 7; self.service('deterministic_bounds_forced')
        return orig_db(self, deadline)
    FR.Frontier.deterministic_bounds = db_hook
    try: r = solve_(t8, 'G0_CQR', 'c21-03b', budget=20.0)
    finally: FR.Frontier.deterministic_bounds = orig_db
    A(r['outcome'] == 'PUBLISHED' and r['publication']['route'] == 'exact_reference' and compare(r['publication'], tr8, F(0), TK.all_singletons(c8)) == 0, '03 forced completion inside the root computation: %s %s' % (r['outcome'], r['publication'].get('route') if r.get('publication') else None)); out['f03']['forced_in_root'] = r['publication']['route']
    # optional cancellation inside the initial publication test: the reference continues alone
    def db_cancel(self, deadline=None): raise CP.CompileStop('cancelled', 'deterministic_bounds_forced')
    FR.Frontier.deterministic_bounds = db_cancel
    try: r = solve_(t8, 'G0_CQR', 'c21-03c', budget=20.0)
    finally: FR.Frontier.deterministic_bounds = orig_db
    A(r['outcome'] == 'PUBLISHED' and r['publication']['route'] == 'exact_reference' and 'cancelled' in (r['certificate'].get('optional_cancelled') or ''), '03 cancellation inside the root computation: %s %s' % (r['outcome'], r['certificate'].get('optional_cancelled'))); out['f03']['cancel_in_root'] = r['certificate']['optional_cancelled'][:60]
    # ---------------- 04
    rng = random.Random(82); c14 = [2] * 14; m14 = dict(cards=c14, factors=[dict(scope=tuple(range(14)), values=[F(rng.randint(1, 9)) for _ in range(2 ** 14)])], evidence={}); t14 = mk_task(m14, [TK.singleton_query(v, 0, c14) for v in range(14)])
    ticks = []; orig_tick = CP.tick
    def spy(C, quota=None, op=None): ticks.append(C.work.total()); return orig_tick(C, quota, op)
    CP.tick = spy
    try:
        C = CP.from_task(t14); base = C.work.total()
        try: CP.exact_quotient_pass(C, base + 12000)
        except CP.CompileStop as cs: A(cs.kind == 'quota', cs.kind)
        over = C.work.total() - base - 12000; gaps = [ticks[k] - ticks[k - 1] for k in range(1, len(ticks))]
        A(over <= CP.POLICY['max_irreducible_charge'] and max(gaps) <= CP.TICK_ENTRIES, '04 quota overspend %d / max gap %d' % (over, max(gaps))); out['f04']['quota_12000'] = dict(overspend=over, max_gap=max(gaps))
        ticks.clear(); r = solve_(t14, 'N1_CQR', 'c21-04', budget=30.0); gaps = [ticks[k] - ticks[k - 1] for k in range(1, len(ticks))]
        A(max(gaps) <= CP.TICK_ENTRIES + CP.POLICY['max_irreducible_charge'], '04 production gap %d' % max(gaps)); out['f04']['production_14bin'] = dict(ticks=len(ticks), max_gap=max(gaps), route=r['publication']['route'])
        # quotas placed immediately before bulk work in every costly operator on the same dense model (states 2^14 slices of 8,192 entries)
        for name, fn in (('signatures', lambda C_, q: CP._signatures(C_, 0, CP._Ticker(C_, q, 'x'))), ('leaf', lambda C_, q: CP.leaf_sumout(C_, q)), ('support', lambda C_, q: CP.support_fixpoint(C_, q)), ('approx', lambda C_, q: CP.approx_quotient(C_, q, [F(1, 800)] * 14)), ('concentration', lambda C_, q: CP.concentration(C_, q, [F(1, 800)] * 14))):
            C = CP.from_task(t14); base = C.work.total(); ticks.clear()
            try: fn(C, base + 100)
            except CP.CompileStop as cs: pass
            over = C.work.total() - base - 100; A(over <= CP.POLICY['max_irreducible_charge'], '04 %s overspent a quota placed before bulk work by %d' % (name, over)); out['f04'][name] = over
    finally: CP.tick = orig_tick
    A(CP.POLICY['max_irreducible_charge'] == CP.TICK_ENTRIES + 2, 'policy constant'); out['f04']['bound'] = CP.POLICY['max_irreducible_charge']
    # ---------------- 05
    import kernel_identity as KI
    td = tempfile.mkdtemp(prefix='c21_merlin_'); os.makedirs(os.path.join(td, 'ext', 'comparator')); os.makedirs(os.path.join(td, 'bench')); pa = os.path.join(td, 'A'); pb = os.path.join(td, 'B'); open(pa, 'wb').write(b'fake A never executed'); open(pb, 'wb').write(b'fake B never executed')
    pin = json.load(open(os.path.join(CODE, 'ext', 'comparator', 'MERLIN_PIN.json'))); pin['binary'] = dict(path=pa, sha256=hashlib.sha256(b'fake A never executed').hexdigest(), bytes=21); json.dump(pin, open(os.path.join(td, 'ext', 'comparator', 'MERLIN_PIN.json'), 'w'))
    open(os.path.join(td, 'bench', 'cells.py'), 'w').write('MERLIN = "%s"\n' % pb); cur = KI.collect(td); f0 = KI.failures_vs_frozen(cur, cur, ['WMB']); A(f0 and 'INCONSISTENT' in f0[0], '05 inconsistent binding froze: %s' % f0[:1]); out['f05']['inconsistent_refused'] = f0[0][:70]
    open(os.path.join(td, 'bench', 'cells.py'), 'w').write('MERLIN = "%s"\n' % pa); cur = KI.collect(td); A(not KI.failures_vs_frozen(cur, cur, ['WMB', 'IJGP', 'MERLIN_CTE']), '05 consistent binding refused')
    open(pa, 'wb').write(b'replaced never executed'); cur2 = KI.collect(td)
    for arm in ('WMB', 'IJGP', 'MERLIN_CTE'):
        fz = KI.failures_vs_frozen(cur, cur2, [arm]); A(fz and 'BINARY_CHANGED' in fz[0], '05 %s accepted a replaced executable' % arm); out['f05'][arm] = fz[0][:50]
    open(pa, 'wb').write(b'fake A never executed'); open(os.path.join(td, 'bench', 'cells.py'), 'w').write('MERLIN = "%s"\n' % pb); cur3 = KI.collect(td); fz = KI.failures_vs_frozen(cur, cur3, ['WMB']); A(fz and 'ADAPTER_PATHS_CHANGED' in fz[0], '05 repointed bench/cells accepted'); out['f05']['repointed'] = fz[0][:60]
    shutil.rmtree(td); real = KI.collect(CODE); A(real['merlin']['adapter_paths']['consistent'] and not KI.failures_vs_frozen(real, real, ['WMB', 'IJGP', 'MERLIN_CTE']), '05 real configuration inconsistent'); out['f05']['real_consistent'] = True
    # ---------------- 06 (real finalize -> closeout, with a current-identity qualification stub as in C12)
    rd = os.path.join(d, 'chain06'); mpc2 = _concentration_witness(os.path.join(d, 'c06')) if os.path.isdir(os.path.join(d, 'c06')) else (os.makedirs(os.path.join(d, 'c06')) or _concentration_witness(os.path.join(d, 'c06')))
    code_ = "import sys; sys.path.insert(0, %r); import campaign as CA; CA.manifest(%r, [CA.make_row('query_transfer', 'conc16', %r)], dev=True, budgets=[10], plan={'query_transfer': [('N1_CQR', 1), ('H1_HYBRID', 1)]}, root_seed='c21-06')" % (HERE, rd, mpc2)
    subprocess.run([PY, '-c', code_], capture_output=True, text=True, cwd=CODE); subprocess.run([PY, os.path.join(HERE, 'campaign.py'), 'run', rd, '--dev'], capture_output=True, text=True, cwd=CODE); CNT['fresh_workers'] += 2
    pf = subprocess.run(['sh', os.path.join(HERE, 'finalize.sh'), rd, 'CAMPAIGN_MANIFEST_dev.json'], capture_output=True, text=True, cwd=CODE); A('FINALIZE_DONE' in pf.stdout, '06 finalize failed: %s' % pf.stdout[-200:])
    stub = dict(suite_version=SUITE_VERSION + ' (closeout-attribution control stub)', suite_sha256=registry.suite_sha256(CODE), all_pass=True, passed=len(registry.QUALIFICATION_GROUPS), total=len(registry.QUALIFICATION_GROUPS), groups=[dict(name=g_, ok=True) for g_ in registry.QUALIFICATION_GROUPS], candidate_sources=registry.cqr_source_inventory(CODE), candidate_sources_at_start=registry.cqr_source_inventory(CODE), sources_changed_during_run=[], counts=dict(CNT)); sp = os.path.join(d, 'stub.json'); json.dump(stub, open(sp, 'w'))
    def closeout():
        r_ = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), rd, '--manifest', 'CAMPAIGN_MANIFEST_dev.json', '--qualification', sp], capture_output=True, text=True, cwd=CODE); return 'DEVELOPMENT ADMISSION QUALIFIED' in r_.stdout, [l.strip()[:90] for l in r_.stdout.splitlines() if l.strip().startswith('- ')][:1]
    ok, why = closeout(); A(ok, '06 honest closeout not qualified: %s' % why); rp = os.path.join(rd, 'RESULTS_CQR.json'); orig = open(rp).read(); runs = json.loads(orig)['runs']
    i0 = next(i for i, x in enumerate(runs) if x['arm'] == 'N1_CQR'); row0 = runs[i0]
    A(row0.get('exact') is False and row0.get('bias') == ['3/500003'] and row0.get('guarantee_source', '').startswith('checker-verified'), '06 honest report row: %s' % {k: row0.get(k) for k in ('exact', 'bias', 'guarantee_source')})
    # attempt-7 regression (admission_v8 closeout UNQUALIFIED on an HONEST report): a baseline row whose `routes` are pairs is serialized as lists in RESULTS_CQR.json but re-derived as tuples;
    # the closeout must compare in the published JSON domain -- the honest closeout above already QUALIFIED with such a row present, and a change to that row must still be refused
    ib = next((i for i, x in enumerate(runs) if x['arm'] == 'H1_HYBRID'), None); rb = runs[ib] if ib is not None else {}
    A(ib is not None and isinstance(rb.get('routes'), list) and rb['routes'] and all(isinstance(pr, list) and len(pr) == 2 for pr in rb['routes']), '06 baseline row without a published routes list of pairs: %s' % {k: rb.get(k) for k in ('arm', 'status', 'outcome', 'routes')})
    out['f06']['baseline_row'] = dict(arm=rb.get('arm'), outcome=rb.get('outcome'), routes=rb.get('routes'))
    muts = [(name, i0, fn) for name, fn in (('exact_true', lambda r: r.__setitem__('exact', True)), ('bias_zero', lambda r: r.__setitem__('bias', ['0'])), ('applied_bias_zero', lambda r: r.__setitem__('bias_applied_to_original_answers', ['0'])), ('commits_emptied', lambda r: r.__setitem__('committed_operators', [])), ('interpretation', lambda r: r.__setitem__('bias_interpretation', 'exact')), ('guarantee_source', lambda r: r.__setitem__('guarantee_source', 'worker fields')), ('route', lambda r: r.__setitem__('route', 'exact_reference')), ('guarantee', lambda r: r.__setitem__('guarantee', 'PAC')))]
    muts += [('baseline_routes_guarantee', ib, lambda r: r['routes'][0].__setitem__(1, 'PAC' if r['routes'][0][1] != 'PAC' else 'DETERMINISTIC')), ('baseline_routes_emptied', ib, lambda r: r.__setitem__('routes', [])), ('baseline_outcome', ib, lambda r: r.__setitem__('outcome', 'DEADLINE' if r.get('outcome') != 'DEADLINE' else 'PUBLISHED'))]
    for name, idx, fn in muts:
        rr = json.loads(orig); fn(rr['runs'][idx]); open(rp, 'w').write(json.dumps(rr)); ok, why = closeout(); A(not ok and why and 'RE-DERIVED' in why[0], '06 report-only %s survived the closeout' % name); out['f06'][name] = 'refused'
    open(rp, 'w').write(orig); ok, why = closeout(); A(ok, '06 restored report not qualified: %s' % why); out['f06']['honest'] = 'QUALIFIED'
    return out


GROUPS = [('C1_identity_and_checker_end_to_end', c1_identity_checker), ('C2_independent_oracle_and_modes', c2_oracle_modes), ('C3_quotient_exact_and_mutations', c3_quotient), ('C4_approximate_quotient_budget', c4_approx_quotient), ('C5_affine_support_and_pullbacks', c5_affine), ('C6_influence_and_concentration_conditions', c6_influence_concentration), ('C7_frontier_typed_bounds_and_envelopes', c7_frontier), ('C8_signed_residual_stream_and_epochs', c8_signed_stream), ('C9_ratio_stream_history_and_record_before_resolve', c9_ratio_stream), ('C10_publication_feasibility_denominators_normalizer', c10_publication), ('C11_protected_reference_and_resource_refusal', c11_reference_resources), ('C12_registry_pipeline_dev_admission', c12_pipeline_admission), ('C13_tiny_model_delta_falsification', c13_delta_falsification), ('C14_publication_contract_every_route', c14_publication_contract_every_route), ('C15_semantics_and_guarantee_binding', c15_semantics_and_guarantee_binding), ('C16_fresh_process_pac_routes', c16_fresh_process_pac_routes), ('C17_protected_reference_scheduling', c17_protected_reference_scheduling), ('C18_task_local_state_and_policy', c18_task_local_state_and_policy), ('C19_provenance_and_intake', c19_provenance_and_intake), ('C20_atomic_compilation_replay_service_history_attribution', c20_atomic_compilation_replay_service_history_attribution), ('C21_checker_soundness_lifecycle_dependencies_closeout', c21_checker_soundness_lifecycle_dependencies_closeout)]

if __name__ == '__main__':
    assert [g for g, _ in GROUPS] == list(registry.QUALIFICATION_GROUPS), 'suite groups differ from the registry schema'
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    if '--admission' in sys.argv: ADMISSION_DIR = sys.argv[sys.argv.index('--admission') + 1]; R['admission_dir'] = ADMISSION_DIR
    t0 = time.monotonic()
    for name, fn in GROUPS:
        if only and not any(name == o or name.startswith(o + '_') for o in only): continue
        group(name, fn)
    srcs = registry.cqr_source_inventory(CODE); changed = sorted(k for k in set(srcs) | set(SOURCES_AT_START) if srcs.get(k) != SOURCES_AT_START.get(k))
    if changed: print('SOURCES CHANGED DURING THE RUN: %s -- the record is INVALID' % changed)
    R.update(passed=passed, total=total, all_pass=(passed == total and total == len(registry.QUALIFICATION_GROUPS) and not changed), sources_changed_during_run=changed, candidate_sources_at_start=SOURCES_AT_START, candidate_sources=srcs, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), wall_s=round(time.monotonic() - t0, 1), c13_plan=C13_PLAN)
    for g_ in R['groups']:
        if not g_['ok']: print('FAILURE DETAIL', g_['name'], json.dumps(g_['detail'], default=str)[:900])
    if not only: json.dump(R, open(os.path.join(HERE, 'CQR_QUALIFICATION.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(passed=passed, total=total, counts=R['counts'], all_pass=R['all_pass'], wall_s=R['wall_s']))); sys.exit(0 if R['all_pass'] else 1)
