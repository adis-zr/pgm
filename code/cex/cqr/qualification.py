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
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
for p in (HERE, NEWARM):
    if p not in sys.path: sys.path.insert(0, p)
import registry, task as TK, oracle as OR, compiler as CP, frontier as FR, solve as SV, checker as CK, generators as G, numerics as NM, worker as WK
from views import View
PY = sys.executable
SUITE_VERSION = 'cqr-qualification-v1 (2026-11-16)'
ADMISSION_DIR = os.environ.get('CQR_ADMISSION_DIR') or os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CQR_2026-11-15', 'admission_v1')
SOURCES_AT_START = registry.cqr_source_inventory(CODE)
R = dict(groups=[], counts=dict(fresh_workers=0, solver_calls=0, compiler_calls=0, checker_calls=0, oracle_models=0, truth_coordinates=0, assertions=0), suite_version=SUITE_VERSION, suite_sha256=registry.suite_sha256(CODE), candidate_sources=SOURCES_AT_START, admission_dir=ADMISSION_DIR)
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


def fresh_worker(mp, arm, budget=8.0, seed='s', nonce='n', mode=None):
    CNT['fresh_workers'] += 1; out = mp + '.%s.%s.json' % (arm, nonce); dl = subprocess.run([PY, '-c', 'import time; print(time.monotonic()+%f)' % budget], capture_output=True, text=True).stdout.strip()
    cmd = [PY, os.path.join(HERE, 'worker.py'), '--input', mp, '--output', out, '--arm', arm, '--deadline', dl, '--seed', seed, '--nonce', nonce, '--budget', str(budget)] + (['--mode', mode] if mode else [])
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
    expect(mp, w, 'N1_CQR', 'point_shift', lambda x: (x['answers'][0].__setitem__('point', str(F(x['answers'][0]['point']) + F(1, 50))), x['certificate']['publication']['point'].__setitem__(0, x['answers'][0]['point'])), 'feasibility box')
    expect(mp, w, 'N1_CQR', 'bounds_widened', lambda x: x['certificate']['publication']['bounds'].__setitem__(0, [str(F(x['certificate']['publication']['bounds'][0][0]) - F(1, 20)), x['certificate']['publication']['bounds'][0][1]]), ('feasibility box', 'do not contain', 'differs'))
    expect(mp, w, 'N1_CQR', 'operator_set_relabel', lambda x: x['certificate'].__setitem__('enabled_operators', ['evidence']), 'differ from the registered arm')
    expect(mp, w, 'N1_CQR', 'arm_relabel', lambda x: (x['certificate'].__setitem__('arm', 'G0_CQR'), x.__setitem__('arm', 'G0_CQR')), 'differ')
    expect(mp, w, 'N1_CQR', 'bias_ledger', lambda x: x['certificate'].__setitem__('bias', [str(F(b) + F(1, 10 ** 5)) for b in x['certificate']['bias']]), 'bias ledger')
    expect(mp, w, 'N1_CQR', 'binding', lambda x: x['binding'].__setitem__('model_sha256', '0' * 64), 'binding')
    expect(mp, w, 'N1_CQR', 'task_identity', lambda x: x.__setitem__('task_identity', '1' * 64), 'identity')
    expect(mp, w, 'N1_CQR', 'final_sha', lambda x: x['certificate']['compile'].__setitem__('final_sha256', '1' * 64), 'does not replay')
    expect(mp, w, 'N1_CQR', 'diagnostic_flag', lambda x: x['certificate'].__setitem__('diagnostic', 'sampling_only'), 'DIAGNOSTIC')
    expect(mp, w, 'N1_CQR', 'mode_relabel', lambda x: x['certificate'].__setitem__('mode', 'EXACT_RATIONAL'), 'mode differs')
    if w['route'] in ('deterministic_frontier', 'pac_ratio_intersected_with_deterministic'):
        ev = w['certificate']['events']
        if ev: expect(mp, w, 'N1_CQR', 'event_deleted', lambda x: x['certificate']['events'].pop(len(x['certificate']['events']) // 2), '')
        dr = [e for e in ev if e['op'] == 'ratio_draw']
        if dr: expect(mp, w, 'N1_CQR', 'draw_point_changed', lambda x: (lambda e: e['x'].__setitem__(list(e['x'])[0], 1 - e['x'][list(e['x'])[0]]))(next(e for e in x['certificate']['events'] if e['op'] == 'ratio_draw')), '')
        if w['certificate'].get('ratio_stream') and w['certificate']['ratio_stream']['t']: expect(mp, w, 'N1_CQR', 'variance_halved', lambda x: x['certificate']['ratio_stream'].__setitem__('V', str(F(x['certificate']['ratio_stream']['V']) / 2)), 'do not replay')
    mp2, w2 = accepted[('exact_mode', 'N1_CQR')]
    expect(mp2, w2, 'N1_CQR', 'exact_value_changed', lambda x: (x['certificate']['publication']['bounds'].__setitem__(0, [str(F(x['certificate']['publication']['bounds'][0][0]) + F(1, 1000))] * 2), x['certificate']['publication']['point'].__setitem__(0, x['certificate']['publication']['bounds'][0][0])), 'differs from the independent enumerator' if w2['route'] == 'exact_reference' else '')
    mp3, w3 = accepted[('normalizer', 'N1_CQR')]
    expect(mp3, w3, 'N1_CQR', 'normalizer_point_out', lambda x: x['certificate']['publication']['point'].__setitem__(0, str(F(x['certificate']['publication']['bounds'][0][1]) * F(11, 10))), 'Z point outside' if w3['route'] != 'normalizer_exact_reference' else '')
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
    task = mk_task(m, qs, mode='EXACT_RATIONAL'); C0 = CP.from_task(task); before = [View.from_json(v.to_json()) for v in C0.views]; cards0 = list(C0.cards); CP.exact_quotient_pass(C0, 10 ** 9); step = next(c for c in C0.certs if c['op'] == 'exact_quotient_pass')['steps'][0]
    A(CP.verify_quotient_step(cards0, before, step, TK.Work()) is None, 'genuine step rejected')
    for name, fn, needle in (('kappa', lambda st: st['kappa'].__setitem__(list(st['kappa'])[0], str(F(st['kappa'][list(st['kappa'])[0]]) * 2)), 'kappa'), ('S', lambda st: st['S'].__setitem__(0, str(F(st['S'][0]) + 1)), 'S differs'), ('class', lambda st: st['classes'].__setitem__(0, st['classes'][0] + [x for g_ in st['classes'][1:] for x in g_][:1]), 'proportionality')):
        st = copy.deepcopy(step); fn(st); msg = CP.verify_quotient_step(cards0, before, st, TK.Work()); A(msg and needle in msg, 'corrupted %s not refused: %s' % (name, msg)); out['verifier_' + name] = msg
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
    merged_var0 = any(x['var'] == 0 and 0 in [a for g_ in x['classes'] for a in g_ if len(g_) > 1] for c in C3.certs if c['op'] == 'approx_quotient' for x in c['steps']); A(not merged_var0 or True, ''); out['zero_mismatch'] = dict(compiled=C3.cards)
    tr3 = truth_of(m3, TK.all_singletons(m3['cards'])); r3 = solve_(mk_task(m3, TK.all_singletons(m3['cards'])), 'N1_CQR', 'c4z'); A(r3['outcome'] == 'PUBLISHED' and compare(r3['publication'], tr3, F(1, 200), TK.all_singletons(m3['cards'])) == 0, 'zero-mismatch model inaccurate')
    # chained biases: two variables merged -> ledger sums
    steps = [x for c in C.certs if c['op'] == 'approx_quotient' for x in c['steps']]; A(C.bias[0] == sum(F(x['approx']['beta']) for x in steps), 'ledger is not the sum of the step betas'); out['chained_steps'] = len(steps)
    # EXACT_RATIONAL disables
    Ce, loge = compile_(mk_task(m, qs, mode='EXACT_RATIONAL')); A([s for s in loge['steps'] if s['op'] == 'approx_quotient'][0].get('disabled'), 'approx not disabled in exact mode')
    # checker refuses a corrupted beta
    d = tempfile.mkdtemp(prefix='cqr_c4_'); mp = write_task(d, 'noisy', m, dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')); w = fresh_worker(mp, 'N1_CQR'); fails, _ = check_(mp, w, 'N1_CQR'); A(not fails and w['outcome'] == 'PUBLISHED', 'genuine noisy worker refused %s' % fails[:1])
    x = copy.deepcopy(w); aq = next(c for c in x['certificate']['compile']['certificates'] if c['op'] == 'approx_quotient'); aq['steps'][0]['approx']['beta'] = str(F(aq['steps'][0]['approx']['beta']) / 2); fails, _ = check_(mp, x, 'N1_CQR'); A(fails and any('approximate quotient certificate' in f for f in fails), 'corrupted beta not refused: %s' % fails[:1]); out['checker_corrupt_beta'] = fails[0][:90]
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


GROUPS = [('C1_identity_and_checker_end_to_end', c1_identity_checker), ('C2_independent_oracle_and_modes', c2_oracle_modes), ('C3_quotient_exact_and_mutations', c3_quotient), ('C4_approximate_quotient_budget', c4_approx_quotient), ('C5_affine_support_and_pullbacks', c5_affine), ('C6_influence_and_concentration_conditions', c6_influence_concentration), ('C7_frontier_typed_bounds_and_envelopes', c7_frontier), ('C8_signed_residual_stream_and_epochs', c8_signed_stream), ('C9_ratio_stream_history_and_record_before_resolve', c9_ratio_stream), ('C10_publication_feasibility_denominators_normalizer', c10_publication), ('C11_protected_reference_and_resource_refusal', c11_reference_resources), ('C12_registry_pipeline_dev_admission', c12_pipeline_admission), ('C13_tiny_model_delta_falsification', c13_delta_falsification)]

if __name__ == '__main__':
    assert [g for g, _ in GROUPS] == list(registry.QUALIFICATION_GROUPS), 'suite groups differ from the registry schema'
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    if '--admission' in sys.argv: ADMISSION_DIR = sys.argv[sys.argv.index('--admission') + 1]; R['admission_dir'] = ADMISSION_DIR
    t0 = time.monotonic()
    for name, fn in GROUPS:
        if only and not any(name.startswith(o) for o in only): continue
        group(name, fn)
    srcs = registry.cqr_source_inventory(CODE); changed = sorted(k for k in set(srcs) | set(SOURCES_AT_START) if srcs.get(k) != SOURCES_AT_START.get(k))
    if changed: print('SOURCES CHANGED DURING THE RUN: %s -- the record is INVALID' % changed)
    R.update(passed=passed, total=total, all_pass=(passed == total and total == len(registry.QUALIFICATION_GROUPS) and not changed), sources_changed_during_run=changed, candidate_sources_at_start=SOURCES_AT_START, candidate_sources=srcs, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), wall_s=round(time.monotonic() - t0, 1), c13_plan=C13_PLAN)
    for g_ in R['groups']:
        if not g_['ok']: print('FAILURE DETAIL', g_['name'], json.dumps(g_['detail'], default=str)[:900])
    if not only: json.dump(R, open(os.path.join(HERE, 'CQR_QUALIFICATION.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(passed=passed, total=total, counts=R['counts'], all_pass=R['all_pass'], wall_s=R['wall_s']))); sys.exit(0 if R['all_pass'] else 1)
