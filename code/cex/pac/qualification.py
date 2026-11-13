"""PRODUCTION QUALIFICATION of the PAC candidate v3 (handoff 03 §3; repaired after the two adversarial reviews of 13 Nov 2026). Counted GROUPS are reported separately
from END-TO-END INFERENCE EXECUTIONS (`executions`: real run_component / solve / worker runs) and HELPER EVALUATIONS (`helper_evaluations`: quadratic / arithmetic
helper calls), and from COORDINATES checked. A group FAILS if any assertion inside it fails. Truth comes from an INDEPENDENT original-model enumerator (`truth`,
itertools over the original factor tables; never contrib / core routines) wherever a publication is judged. Every published answer (deterministic or PAC) is checked
for shape, interval containment of the truth, point-in-interval and certificate replay; a DETERMINISTIC miss fails the group; PAC misses are counted per ATTEMPTED run
against the declared finite-sample allowance. Writes PAC_QUALIFICATION.json beside this file (candidate identity = every pac/*.py and newarm/*.py, *.cpp).
Groups:
Q1  identity + GATE end to end: real worker fixtures (exact cover, partial cover, forest route with evidence, support route, zero proof) and a genuine PAC fixture are
    accepted; the first review's nine negative controls, the second review's COHERENT mutations (wrong lift with matching decimals, foreign design, false U_root,
    fabricated exact cover, false zero proof string / structured, coherent K underallocation, empty freeze, negative wall, unbound / empty amendments) and tampered
    deterministic rows are REJECTED; a valid candidate is accepted when the manifest also freezes B0 sources (per-arm identity).
Q2  exact cell oracle (contributions vs the independent enumerator, evidence intersection, deadline boundary).
Q3  fixed-law algebra (exhaustive, independent cell truth) + ACTUAL adaptive accumulation: real resolving runs are observed at Stream.add_residual: the A_t enclosure
    contains the exact resolved mass (nonzero resolved mass exercised); production draw_leaf frequencies vs the exact law; duplicate refused.
Q4  frontier invariants on random models (zeros, heterogeneous cardinalities, extreme gauges): closure after resolving every positive-bound leaf (strict child-sum slack
    included), U_t bounds the residual mass at every step, telescoping, deterministic bounds contain the truth, rebuild reproduces U_t; U = 0 root; positive-Z zero
    prefix refusal; production envelope guard.
Q5  actual sampling backend (random.Random) frequencies.
Q6  confidence arithmetic: boundary / psi / threshold enclosures; both review witnesses; 3000 random concave quadratics (helper evaluations); repaired quad_roots_outer;
    directed accumulators under underflow; nonconvex set; design-record fields.
Q7  numerical publication: feasibility; actual PAC publications (both modes, resolve OFF) and an ADAPTIVE PAC publication (resolve ON, A > 0) ASSERTED to contain the truth
    and to replay; exact answers with a = 2^-1075 / 2^-2000 (R03) published deterministically; huge exponents.
Q9  resource selection / continuation: deadline prefix; failed trial terminates; exact refusal continues into PAC for EVERY real backend refusal class (stream.UnsupportedError,
    dag.Unsupported, support.Unsupported after a numerical stop, ResourceStop MEMORY); DEADLINE final; late zero -> DEADLINE through the real worker; typed RANGE; factorless.
Q10 existing defects: HostBudget control (claim narrowed), the frozen executor's own suite in an ISOLATED copy (dependencies listed).
Q11 diagnostic coverage at delta 0.1 over ATTEMPTED runs (resolve OFF and ON): misses <= 14 of 60 (exact one-sided tail P[X > 14] = 6.66e-4 at p = 0.1); all rows retained;
    bug detection only, never a 1e-6 verification.
Q12 exact closure and partial cover (review controls + generic): slack cover a in {1/2, 1/10, 0}; full-solver chain13 + unary; 257-star partial bounds; generic models with
    every publication checked against the independent truth (deterministic miss = FAIL); complete covers close with U_t = 0; partial covers conserve mass; the review's
    output-corruption wrapper applied to real publications is DETECTED by this group's checker (sensitivity self-test).
Q13 adapters and the executable pipeline: CBI/SF native transform refuses truncated / mis-shaped / wrongly bound rows and scores the native width separately; the exact
    integer UAI export is parsed by the repository readers and by the libDAI / Merlin binaries when present; the REAL manifest producer -> dispatcher -> gate v3 ->
    report v3 -> closeout v3 pipeline runs on a tiny manifest under the supervisor (dev seeds); closeout refuses a foreign qualification identity; resume preflight refuses
    an edited manifest."""
import sys, os, json, time, math, random, hashlib, itertools, subprocess, shutil, copy, tempfile, contextlib, io, glob
from fractions import Fraction as F
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm'); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (NEWARM, HERE, CODE): sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
import engine, contrib, rig, solve, core, gate, support
SUITE_VERSION = 'pac-qualification-v3 (2026-11-13 completion)'
R = {'groups': [], 'executions': 0, 'helper_evaluations': 0, 'coordinates_checked': 0, 'suite_version': SUITE_VERSION}; passed = 0; total = 0
TMP = Path(tempfile.mkdtemp(prefix='pac_qual_v3_')); PY = sys.executable


def group(name, fn):
    global passed, total
    total += 1; t = time.monotonic()
    try: detail = fn(); ok = True
    except Exception as ex:
        import traceback; detail = {'error': '%s: %s' % (type(ex).__name__, ex), 'trace': traceback.format_exc()[-1500:]}; ok = False
    passed += ok; R['groups'].append(dict(name=name, ok=ok, wall_s=round(time.monotonic() - t, 3), detail=detail)); print(('PASS ' if ok else 'FAIL ') + name, flush=True)


# ---------------- INDEPENDENT original-model enumerator (never contrib / core)
def truth(m):
    """exact Z, singleton numerators N[v][s] and marginals of the ORIGINAL model under its evidence (itertools over the factor tables)"""
    cards = m['cards']; ev = m.get('evidence') or {}; n = len(cards); Z = F(0); N = [[F(0)] * c for c in cards]
    for x in itertools.product(*(range(c) for c in cards)):
        if any(x[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in m['factors']:
            i = 0
            for v in f['scope']: i = i * cards[v] + x[v]
            w *= f['values'][i]
            if w == 0: break
        if w == 0: continue
        Z += w
        for v in range(n): N[v][x[v]] += w
    return Z, N, ([[a / Z for a in row] for row in N] if Z else None)


def chain(n, a=2, extra=()): m = {'cards': [2] * n, 'evidence': {}, 'factors': [{'scope': (i, i + 1), 'values': [F(a), F(1), F(1), F(a)]} for i in range(n - 1)]}; m['factors'] += list(extra); return m


def rand_model(rng, nmin=3, nmax=5, cmax=3, zero_p=0.0, gauge=False):
    n = rng.randint(nmin, nmax); cards = [rng.randint(2, cmax) for _ in range(n)]; fs = []
    for _ in range(rng.randint(n - 1, n + 2)):
        k = rng.randint(1, min(2, n)); sc = tuple(rng.sample(range(n), k)); vol = math.prod(cards[v] for v in sc)
        fs.append(dict(scope=sc, values=[F(0) if rng.random() < zero_p else F(rng.randint(1, 7), rng.randint(1, 7)) * (F(2) ** rng.randint(-60, 60) if gauge else 1) for _ in range(vol)]))
    return dict(cards=cards, factors=fs, evidence={})


def write_uai(m, path):
    import uai_export
    return uai_export.write_uai(m, path)


def contained(rows, pts, marg, eps):
    core.verify_output(rows, pts, eps)
    return all(lo <= p <= hi for row, ps in zip(rows, marg) for (lo, hi), p in zip(row, ps))


def check_publication(r, m, eps, label):
    """every published component result: shape, truth containment, certifier replay; returns (guarantee, contains)"""
    Z, N, marg = truth(m); cards = m['cards']
    assert r['status'] == 'PUBLISHED', label
    assert len(r['intervals']) == len(cards) and all(len(row) == c for row, c in zip(r['intervals'], cards)), label + ': shape'
    ok = contained(r['intervals'], r['points'], marg, eps); R['coordinates_checked'] += sum(cards)
    if r['guarantee'] == 'DETERMINISTIC': assert ok, label + ': DETERMINISTIC publication misses the truth'
    else:
        ok2, rows, pts, chosen, *_ = engine.hulls_from_record(r['stats']['sufficient_statistics'], eps, engine.POLICY['decimal_margin'])
        assert ok2 and all(rows[v] == r['intervals'][v] and pts[v] == r['points'][v] for v in rows), label + ': PAC replay differs'
    return r['guarantee'], ok


# ---------------- Q1
def q1_identity_gate():
    out = {}; sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest(); dump = lambda p, x: Path(p).write_text(json.dumps(x, indent=1, default=str))
    import worker as W; frozen = W.candidate_sources(); D = TMP / 'q1'; D.mkdir()
    def fixture(name, model, arm, eps='1/200', delta='1/1000000', inproc=None, budget=60):
        d = D / name; (d / 'cells/one').mkdir(parents=True); mp = d / 'model.uai'; write_uai(model, mp); _, binding = core.read_uai(mp)
        if inproc is None:
            t0 = time.monotonic(); subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(mp), '--output', str(d / 'cells/one/worker.json'), '--arm', arm, '--deadline', str(t0 + budget), '--seed', 's-' + name, '--nonce', 'n-' + name, '--budget', str(budget), '--delta', delta], check=True, cwd=CODE); wall = time.monotonic() - t0; w = json.load(open(d / 'cells/one/worker.json')); R['executions'] += 1
        else: w = inproc; wall = 1.0
        c = dict(cell_id='cell1', cohort='external_core', case_id=name, arm=arm, replicate=0, budget_s=float(budget), seed='s-' + name, model_path=str(mp), **binding)
        return dict(d=d, c=c, man=dict(cells=[c], task={'epsilon': eps, 'delta': delta}, candidate_artifact_hashes=dict(frozen)), w=w, wall=wall, binding=binding, mp=mp)
    def gate_run(fx, mutate=None, start_mut=None, amend=None):
        d = fx['d']; shutil.rmtree(d / 'cells', ignore_errors=True); (d / 'cells/one').mkdir(parents=True)
        m = copy.deepcopy(fx['man']); ww = copy.deepcopy(fx['w']); status = 'COMPLETED' if ww.get('status') == 'COMPLETED' else 'STOPPED'
        r = dict(copy.deepcopy(fx['c']), status=status, outcome=ww.get('outcome'), guarantee_type=ww.get('guarantee_type'), nonce=ww.get('nonce'), within_budget=True, launch_relative_wall_s=round(fx['wall'], 3), supervisor={'rc': 0, 'outcome': 'COMPLETED'}, worker_output='cells/one/worker.json')
        if mutate: mutate(d, m, r, ww)
        dump(d / 'CAMPAIGN_MANIFEST.json', m); mh = sha(d / 'CAMPAIGN_MANIFEST.json'); st = {'manifest_sha256': mh, 'manifest': 'CAMPAIGN_MANIFEST.json', 'bound_amendments': []}
        if start_mut: start_mut(st)
        dump(d / 'CAMPAIGN_START.json', st); (d / 'PAC_LEDGER.jsonl').write_text(json.dumps({'kind': 'CAMPAIGN_START', 'manifest_sha256': mh}) + '\n')
        for f in d.glob('MANIFEST_AMENDMENT_*'): f.unlink()
        if amend: dump(d / 'MANIFEST_AMENDMENT_999_artifact_hashes.json', dict(amend, manifest_sha256=mh))
        dump(d / 'cells/one/worker.json', ww); r['output_sha256'] = sha(d / 'cells/one/worker.json'); dump(d / 'cells/one/receipt.json', r)
        with contextlib.redirect_stdout(io.StringIO()): rc = gate.main(str(d))
        g = json.load(open(d / 'GATE_RESULT.json')); return rc, g['failures'], g.get('pac_certificates_replayed')
    fixes = {'det_cover': fixture('det_cover', chain(13, 3, [{'scope': (1,), 'values': [F(1), F(1, 2)]}]), 'P1_PAC_CONDITIONAL'),
             'det_partial': fixture('det_partial', {'cards': [257] + [2] * 6, 'factors': [{'scope': (0, i), 'values': [F(1)] * 514} for i in range(1, 7)], 'evidence': {}}, 'P1_PAC_CONDITIONAL')}
    mev = chain(5, 3); mev['evidence'] = {4: 1}; fixes['h1_forest_ev'] = fixture('h1_forest_ev', mev, 'H1_HYBRID')
    g9 = {'cards': [3] * 9, 'evidence': {4: 1}, 'factors': []}; rng = random.Random(3)
    for r_ in range(3):
        for c_ in range(3):
            v = r_ * 3 + c_
            if c_ < 2: g9['factors'].append({'scope': (v, v + 1), 'values': [F(rng.randrange(1, 6)) for _ in range(9)]})
            if r_ < 2: g9['factors'].append({'scope': (v, v + 3), 'values': [F(rng.randrange(1, 6)) for _ in range(9)]})
    fixes['h1_support_grid'] = fixture('h1_support_grid', g9, 'H1_HYBRID')
    fixes['zero'] = fixture('zero', {'cards': [2, 2], 'factors': [{'scope': (0,), 'values': [F(1), F(2)]}, {'scope': (1,), 'values': [F(0), F(0)]}], 'evidence': {}}, 'P1_PAC_CONDITIONAL')
    acc = {}
    for k, fx in fixes.items():
        rc, f, n = gate_run(fx); assert rc == 0 and not f, (k, f); acc[k] = dict(routes=[c['route'] for c in fx['w']['certificate']['components']] if fx['w'].get('certificate') else fx['w'].get('outcome'), guarantee=fx['w'].get('guarantee_type'))
        if fx['w'].get('status') == 'COMPLETED': R['coordinates_checked'] += sum(len(r_) for r_ in fx['w']['intervals'])
    out['real_worker_fixtures_accepted'] = acc
    pol = engine.POLICY; old = pol['epsilon']; pol['epsilon'] = F(1, 20)
    try: r = solve.solve(chain(3, 2), time.monotonic() + 120, 'A0_POINT', 's-pac', delta=F(1, 20))
    finally: pol['epsilon'] = old
    R['executions'] += 1; assert r['guarantee_type'] == 'PAC'
    mp = D / 'pac_model.uai'; write_uai(chain(3, 2), mp); _, b = core.read_uai(mp); ivd, ptd = core.publish(r['intervals'], r['points'], epsilon=F(1, 20))
    wpac = dict(status='COMPLETED', arm='A0_POINT', seed='s-pac', nonce='n-pac', delta='1/20', epsilon='1/20', guarantee_type='PAC', outcome='PUBLISHED', binding=b, intervals=ivd, points=ptd, certificate=json.loads(json.dumps(r['certificate'], default=str)), stats={}, candidate_sources=frozen)
    fe = fixture('pac', chain(3, 2), 'A0_POINT', eps='1/20', delta='1/20', inproc=wpac); fe['mp'] = mp; fe['c']['model_path'] = str(mp); fe['c'].update(b); fe['binding'] = b
    rc, f, n = gate_run(fe); assert rc == 0 and n == 1, f; out['pac_fixture_trials'] = r['certificate']['components'][0]['trials']
    def wrong_lift(d, m, rr, w):
        cert = w['certificate']; cert['lifted_intervals_exact'] = [[['1/10', '1/10'], ['9/10', '9/10']] for _ in range(3)]; cert['lifted_points_exact'] = [['1/10', '9/10'] for _ in range(3)]
        li = [[(F(a), F(b_)) for a, b_ in row] for row in cert['lifted_intervals_exact']]; lp = [[F(x) for x in row] for row in cert['lifted_points_exact']]; w['intervals'], w['points'] = core.publish(li, lp, epsilon=F(1, 20))
    def foreign_design(d, m, rr, w):
        for comp in w['certificate']['components']: de = comp['design']; de['cutset'] = [999, 999]; de['order_free'] = [-99]; de['mode'] = 'invented'
    def false_U(d, m, rr, w):
        for comp in w['certificate']['components']: comp['design']['U_root'] = '1/1' + '0' * 60; comp['sufficient_statistics']['U_root'] = comp['design']['U_root']
    def det_lie(d, m, rr, w):
        wrong_lift(d, m, rr, w); rr['guarantee_type'] = w['guarantee_type'] = 'DETERMINISTIC'; cert = w['certificate']; cert['delta'] = '0'
        cert['components'] = [{'component': 0, 'variables': [0, 1, 2], 'route': 'pac_conditional_exact_cover_complete', 'guarantee': 'DETERMINISTIC', 'resolved_cells': 1, 'intervals_exact': cert['lifted_intervals_exact'], 'points_exact': cert['lifted_points_exact'], 'design': {'cutset': [0], 'order_free': [1, 2]}, 'frontier': {'resolved_leaves': [[0]], 'extra_expanded': [], 'U_t': '0/1'}, 'resolved_totals': {'E': 0, 'A_lo': 1.0, 'A_hi': 1.0, 'a_lo': [0.1, 0.9] * 3, 'a_hi': [0.1, 0.9] * 3, 'A_exact_lo': '1/1', 'A_exact_hi': '1/1', 'cells': [{'leaf': [0], 'B0_lo': '1/1', 'B0_hi': '1/1'}]}}]
    def zero_lie(d, m, rr, w):
        rr.update(status='STOPPED', outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC'); w.clear(); w.update(status='STOPPED', outcome='PROVED_ZERO_EVIDENCE', zero_evidence_proof='Trust me, zero.', binding=fe['binding'], nonce='n-pac', seed='s-pac', arm='A0_POINT', guarantee_type='DETERMINISTIC', candidate_sources=frozen)
    def zero_lie_structured(d, m, rr, w): zero_lie(d, m, rr, w); w['zero_evidence_proof'] = {'kind': 'reduction', 'reason': 'fabricated'}
    def coherent_K(d, m, rr, w):
        cert = w['certificate']; cert['K_total'] = cert['delta_ledger']['coordinates'] = 1
        for comp in cert['components']:
            de = comp['design']; RR = comp['sufficient_statistics']; de['K_total'] = RR['K'] = 1; de['alpha_range'] = de['alpha_variance'] = RR['alpha_range'] = RR['alpha_variance'] = str(F(1, 40))
            ok, rows, pts, chosen, *_ = engine.hulls_from_record(RR, F(de['epsilon']), F(de['decimal_margin'])); assert ok
            comp['intervals_exact'] = [[[str(a), str(b_)] for a, b_ in rows[v]] for v in range(3)]; comp['points_exact'] = [[str(x) for x in pts[v]] for v in range(3)]; comp['certifier_per_row'] = [chosen[v] for v in range(3)]
            cert['lifted_intervals_exact'] = comp['intervals_exact']; cert['lifted_points_exact'] = comp['points_exact']; w['intervals'], w['points'] = core.publish([rows[v] for v in range(3)], [pts[v] for v in range(3)], epsilon=F(1, 20))
    uai_text = Path(fe['mp']).read_text()
    def changed_input(d, m, rr, w):
        Path(fe['mp']).write_text(uai_text.replace('2 1 1 2', '2 1 1 3')); _, bb = core.read_uai(fe['mp']); w.update(binding=bb)
    negatives = {'wrong_lift_consistent_decimals': wrong_lift, 'foreign_design': foreign_design, 'false_U_root': false_U, 'false_exact_cover': det_lie, 'false_zero_string': zero_lie, 'false_zero_structured': zero_lie_structured, 'coherent_K_one': coherent_K,
                 'empty_freeze': lambda d, m, r_, w: (m.__setitem__('candidate_artifact_hashes', {}), w.__setitem__('candidate_sources', {})), 'negative_wall': lambda d, m, r_, w: r_.update(launch_relative_wall_s=-1000),
                 'empty_candidate_source_map': lambda d, m, r_, w: w.update(candidate_sources={}), 'missing_certificate_wrong_delta': lambda d, m, r_, w: (w.pop('certificate'), w.update(delta='1/2', epsilon='1/10')),
                 'late_publication_true_boolean': lambda d, m, r_, w: r_.update(launch_relative_wall_s=200.0, within_budget=True), 'duplicate_planned_cell': lambda d, m, r_, w: m['cells'].append(copy.deepcopy(m['cells'][0])),
                 'input_changed_after_freeze': changed_input, 'foreign_nonce': lambda d, m, r_, w: w.update(nonce='other'), 'wrong_seed': lambda d, m, r_, w: w.update(seed='other'),
                 'cbi_completed_without_output': lambda d, m, r_, w: (m['cells'][0].__setitem__('arm', 'CBI_NATIVE'), r_.update(arm='CBI_NATIVE', guarantee_type='DETERMINISTIC', worker_output='absent.json', output_sha256='0' * 64)),
                 'tampered_statistic_n': lambda d, m, r_, w: w['certificate']['components'][0]['sufficient_statistics'].__setitem__('n', w['certificate']['components'][0]['sufficient_statistics']['n'] + 1),
                 'tampered_exact_row': lambda d, m, r_, w: w['certificate']['components'][0]['intervals_exact'][0].__setitem__(0, ['1/10', '1/10'])}
    rej = {}
    for name, mut in negatives.items():
        rc, f, n = gate_run(fe, mutate=mut); Path(fe['mp']).write_text(uai_text); assert rc == 1 and f, (name, f); rej[name] = f[0][1][:80]
    rc, f, n = gate_run(fe, start_mut=lambda st: st.__setitem__('manifest_sha256', '0' * 64)); assert rc == 1; rej['start_hash_disagrees'] = f[0][1][:80]
    rc, f, n = gate_run(fe, mutate=lambda d, m, r_, w: w.update(candidate_sources={}), amend={'per_directory_hashes': {'pac': {}, 'newarm': {}}}); assert rc == 1 and any('not bound' in x[1] for x in f); rej['unbound_amendment_erasure'] = f[0][1][:80]
    rc, f, n = gate_run(fe, mutate=lambda d, m, r_, w: w.update(candidate_sources={}), start_mut=lambda st: st.__setitem__('bound_amendments', ['MANIFEST_AMENDMENT_999_artifact_hashes.json']), amend={'per_directory_hashes': {'pac': {}, 'newarm': {}}}); assert rc == 1 and any('empty candidate map' in x[1] for x in f); rej['bound_amendment_empty_maps'] = f[0][1][:80]
    def missing_receipt(d, m, r_, w): e = copy.deepcopy(m['cells'][0]); e['cell_id'] = 'missing'; m['cells'].append(e)
    rc, f, n = gate_run(fe, mutate=missing_receipt); assert rc == 1 and any('NOT_RUN' in x[1] for x in f); rej['missing_receipt'] = f[0][1][:80]
    def tamper_det(d, m, r_, w): w['certificate']['components'][0]['intervals_exact'][0][0] = ['1/10', '1/10']
    rc, f, n = gate_run(fixes['det_partial'], mutate=tamper_det); assert rc == 1 and any('re-derived' in x[1] for x in f); rej['tampered_deterministic_row'] = f[0][1][:80]
    out['negative_controls_rejected'] = rej
    rc, f, n = gate_run(fe, mutate=lambda d, m, r_, w: m.__setitem__('candidate_artifact_hashes', dict(m['candidate_artifact_hashes'], **{'b0_frozen_v14/core.py': 'ab' * 32}))); assert rc == 0, f; out['b0_scope_in_manifest_valid_candidate_accepted'] = True
    return out


# ---------------- Q2
def q2_masses():
    rng = random.Random(2); out = {'random_cells': 0}
    m = {'cards': [2, 2, 3], 'factors': [dict(scope=(0,), values=[F(1), F(1000)]), dict(scope=(1,), values=[F(1, 3), F(2, 3)]), dict(scope=(2,), values=[F(1, 6), F(1, 3), F(1, 2)]), dict(scope=(0, 1), values=[F(1), F(1), F(1), F(1)])], 'evidence': {}}
    a = contrib.cell_kernel(m, {0: 0}); b = contrib.cell_kernel(m, {0: 1}); R['executions'] += 2
    Za, _, _ = truth(dict(m, evidence={0: 0})); Zb, _, _ = truth(dict(m, evidence={0: 1}))
    assert a['B0'][0] <= Za <= a['B0'][1] and b['B0'][0] <= Zb <= b['B0'][1] and Zb / Za == 1000; out['posterior_identical_mass_1000x'] = True
    bad = 0
    for trial in range(200):
        n = rng.randint(3, 6); cards = [rng.randint(2, 4) for _ in range(n)]; fs = []
        for _ in range(rng.randint(2, n + 2)):
            k = rng.randint(1, min(3, n)); sc = tuple(rng.sample(range(n), k)); vol = math.prod(cards[v] for v in sc)
            fs.append(dict(scope=sc, values=[F(0) if rng.random() < 0.15 else F(rng.randint(1, 9), rng.randint(1, 9)) * F(10) ** rng.randint(-3, 3) for _ in range(vol)]))
        mm = dict(cards=cards, factors=fs, evidence={rng.randrange(n): 0} if rng.random() < 0.4 else {}); free = [v for v in range(n) if v not in mm['evidence']]; cut = {v: rng.randrange(cards[v]) for v in rng.sample(free, rng.randint(0, max(0, len(free) - 1)))}
        cm = dict(mm); cm['evidence'] = {**mm['evidence'], **cut}; Z, N, _ = truth(cm)
        try: kr = contrib.cell_kernel(mm, cut)
        except contrib.CellStop: continue
        R['executions'] += 1; out['random_cells'] += 1
        okc = kr['B0'][0] <= Z <= kr['B0'][1] and all(kr['B'][v][s][0] <= N[v][s] <= kr['B'][v][s][1] for v in range(n) for s in range(cards[v])); R['coordinates_checked'] += sum(cards); bad += (not okc)
    assert bad == 0, bad
    conflict = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), F(1000)]}], 'evidence': {0: 0}}
    assert contrib.cell_exact(conflict, {0: 1})['B0'] == (F(0), F(0)) and contrib.cell_kernel(conflict, {0: 1})['B0'] == (F(0), F(0)); out['evidence_contradiction_is_empty_cell'] = True
    for mdl, cell in (({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, {0: 0}), ({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), F(1)]}], 'evidence': {}}, {})):
        for fn in (contrib.cell_exact, contrib.cell_kernel):
            try: fn(mdl, cell, deadline=time.monotonic() - 1); raise AssertionError('expired deadline accepted')
            except contrib.CellStop as e: assert e.kind == 'DEADLINE'
    out['expired_deadline_refused_at_entry'] = True
    m3 = {'cards': [2, 2], 'factors': [dict(scope=(0,), values=[F(1), F(2)]), dict(scope=(1,), values=[F(0), F(0)])], 'evidence': {}}
    try: solve.solve(m3, time.monotonic() + 10, 'P1_PAC_CONDITIONAL', 'q', F(1, 10)); raise AssertionError('zero component not detected')
    except solve.ZeroEvidence as e: assert e.proof['kind'] == 'reduction'
    out['zero_evidence_component_invalidates_job'] = True; return out


# ---------------- Q3
def tree_law(T):
    law = {}; zero_prefix = F(0)
    def rec(prefix, assign, cur, u, q, i):
        nonlocal zero_prefix
        if i == len(T.cut): law[prefix] = q; return
        v = T.cut[i]; ws, news = T.child_weights(prefix, assign, cur, u, v); S = sum(ws)
        if S == 0: zero_prefix += q; return
        for s_, wgt in enumerate(ws):
            if wgt == 0: continue
            a2 = dict(assign); a2[v] = s_; c2 = dict(cur); c2.update(news[s_][1]); rec(prefix + (s_,), a2, c2, news[s_][0], q * wgt / S, i + 1)
    root = {a: int(T.levels[a][0].reshape(-1)[0]) for a in range(len(T.factors))}
    rec((), {}, dict(root), T.u_root, F(1), 0)          # first pass: expands every node (child-sum propagation refreshes the ancestors' effective weights)
    law.clear(); zero_prefix = F(0); rec((), {}, dict(root), T.u_root, F(1), 0)   # second pass over the now-stable fully expanded frontier = the law draw_leaf samples
    return law, zero_prefix


def cell_truth(m, cut, leaf):
    cm = dict(m); cm['evidence'] = dict(zip(cut, leaf)); return truth(cm)


def q3_laws_and_actual_accumulation():
    rng = random.Random(3); out = dict(models=0, leaves=0)
    for trial in range(30):
        m = rand_model(rng, 3, 5, 3, zero_p=0.2); n = len(m['cards']); cards = m['cards']; Z, N, _ = truth(m); cut = rng.sample(range(n), rng.randint(1, n - 1)); T = engine.Tree(m, cut); law, zp = tree_law(T); U = T.u_root
        if U == 0: assert Z == 0; continue
        assert sum(law.values()) + zp == 1
        ET = F(0); EY = [[F(0)] * c for c in cards]
        for leaf, q in law.items():
            Zc, Nc, _ = cell_truth(m, cut, leaf); u, _, _ = T.node_bounds(leaf); assert Zc <= u and Zc <= T.U_t * q <= U * q; ET += Zc
            for v in range(n):
                for s in range(cards[v]): EY[v][s] += Nc[v][s]
        assert ET == Z and all(EY[v][s] == N[v][s] for v in range(n) for s in range(cards[v]))
        out['models'] += 1; out['leaves'] += len(law); R['helper_evaluations'] += len(law)
    orig = engine.Stream.add_residual; seen = {'calls': 0, 'positive_A': 0, 'checked': 0}; state = {}
    def observing(self, rlo, rhi, Ylo, Yhi):
        seen['calls'] += 1
        if self.A_hi > 0:
            seen['positive_A'] += 1; A = state['resolved_mass'] / state['U']; assert F(self.A_lo) <= A <= F(self.A_hi), 'A_t enclosure does not contain the exact resolved mass'; seen['checked'] += 1
        return orig(self, rlo, rhi, Ylo, Yhi)
    orig_resolve = engine.Tree.resolve
    def tracking_resolve(self, leaf, u):
        Zc, _, _ = cell_truth(self.m, self.cut, tuple(leaf)); state['resolved_mass'] = state.get('resolved_mass', F(0)) + Zc; return orig_resolve(self, leaf, u)
    engine.Stream.add_residual = observing; engine.Tree.resolve = tracking_resolve
    try:
        for trial in range(12):
            m = rand_model(rng, 4, 6, 3, zero_p=0.1); n = len(m['cards'])
            cut = rng.sample(range(n), rng.randint(2, n - 1)); T0 = engine.Tree(m, cut)
            if T0.u_root == 0: continue
            state.clear(); state['resolved_mass'] = F(0); state['U'] = T0.u_root
            r = engine.run_component(m, time.monotonic() + 30, trial, trial + 1, 'conditional', F(1, 20), F(1, 20), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=12); R['executions'] += 1
            if r['status'] == 'PUBLISHED': check_publication(r, m, engine.POLICY['epsilon'], 'q3 adaptive run')
    finally: engine.Stream.add_residual = orig; engine.Tree.resolve = orig_resolve
    assert seen['positive_A'] > 0 and seen['checked'] == seen['positive_A'], seen; out['actual_add_residual_observed'] = seen
    chi_ok = 0
    for trial in range(5):
        m = rand_model(rng, 3, 4, 3); n = len(m['cards']); cut = rng.sample(range(n), 2); T = engine.Tree(m, cut); law, zp = tree_law(T); rng_t = random.Random(777 + trial); counts = {}; Nd = 20000
        for _ in range(Nd):
            assign, q, zero, trans, u = T.draw_leaf(rng_t); key = tuple(assign.get(v) for v in T.cut) if not zero else 'zero'; counts[key] = counts.get(key, 0) + 1
            if not zero: assert q == law[key]
        chi = sum((counts.get(k, 0) - Nd * float(p)) ** 2 / (Nd * float(p)) for k, p in law.items() if p > 0) + ((counts.get('zero', 0) - Nd * float(zp)) ** 2 / (Nd * float(zp)) if zp > 0 else 0)
        dof = len([p for p in law.values() if p > 0]) + (1 if zp > 0 else 0) - 1; assert chi < dof + 6 * math.sqrt(2 * dof) + 12; chi_ok += 1
    out['production_draw_frequency_checks'] = chi_ok
    T = engine.Tree({'cards': [2, 2], 'factors': [dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)])], 'evidence': {}}, [0]); T.resolve((0,), T.node_bounds((0,))[0])
    try: T.resolve((0,), T.node_bounds((0,))[0]); raise AssertionError('duplicate accepted')
    except engine.EngineStop as e: assert e.outcome == 'INVALID_PLAN_OR_CERTIFICATE'
    out['duplicate_resolved_cell_refused'] = True; return out


# ---------------- Q4
def q4_frontier_invariants():
    rng = random.Random(4); st = dict(models=0, steps=0, closures=0, telescoping=0, rebuild=0, zero_prefix_models=0, strict_slack_models=0, zero_mass_positive_bound_leaves=0, closing_draws=0)
    def atom(m, x):
        w = F(1)
        for f in m['factors']:
            i = 0
            for v in f['scope']: i = i * m['cards'][v] + x[v]
            w *= f['values'][i]
        return w
    for case in range(120):
        m = rand_model(rng, 2, 5, 3, zero_p=rng.choice([0.0, 0.0, 0.15, 0.35]), gauge=True); n = len(m['cards']); cards = m['cards']; cut = rng.sample(range(n), rng.randrange(1, n + 1)); T = engine.Tree(m, cut)
        states = list(itertools.product(*(range(c) for c in cards))); W = {x: atom(m, x) for x in states}; Z = sum(W.values())
        if T.u_root == 0: assert Z == 0; continue
        st['models'] += 1; leaves = {}
        for x in states:
            k = tuple(x[v] for v in cut); leaves.setdefault(k, F(0)); leaves[k] += W[x]
        todo = [k for k in leaves if T.node_bounds(k)[0] > 0]; rng.shuffle(todo); st['zero_mass_positive_bound_leaves'] += sum(1 for k in todo if leaves[k] == 0)
        if sum(T.node_bounds(k)[0] for k in todo) < T.u_root: st['strict_slack_models'] += 1
        tot = engine.Totals(sum(cards)); off = [0]
        for c in cards: off.append(off[-1] + c)
        resolved = F(0); r2 = random.Random(case)
        for leaf in todo:
            for _ in range(3):
                a, q, z, tr, u = T.draw_leaf(r2)
                if not z: assert q * T.U_t >= u; st['telescoping'] += 1
            u, _, _ = T.node_bounds(leaf); T.resolve(leaf, u); resolved += leaves[leaf]
            idx = []; lo = []
            for v in range(n):
                for s_ in range(cards[v]): idx.append(off[v] + s_); lo.append(sum(W[x] for x in states if tuple(x[vv] for vv in cut) == leaf and x[v] == s_))
            tot.add_cell(leaf, leaves[leaf], leaves[leaf], lo, lo, idx)
            assert Z - resolved <= T.U_t, 'U_t does not bound the residual mass'
            rows = tot.bounds(T.U_t, cards, off)
            if rows is not None:
                marg = [[sum(W[x] for x in states if x[v] == s_) / Z for s_ in range(cards[v])] for v in range(n)]
                assert all(lo_ <= p <= hi for row, ps in zip(rows, marg) for (lo_, hi), p in zip(row, ps)), 'deterministic bounds miss the truth'; R['coordinates_checked'] += sum(cards)
            st['steps'] += 1
        k = 0
        while T.U_t > 0 and k < 2000:
            a, q, z, tr, u = T.draw_leaf(r2); k += 1; assert z, 'a positive leaf remained after every positive-bound leaf was resolved'
        st['closing_draws'] += k; assert T.U_t == 0, ('frontier not closed', T.frontier_record()); st['closures'] += 1
        fr = T.frontier_record(); st['zero_prefix_models'] += bool(fr['zero_prefixes'])
        assert engine.Tree.rebuild(m, cut, fr['resolved_leaves'], fr['extra_expanded']).U_t == 0; st['rebuild'] += 1
        T3 = engine.Tree(m, cut); r3 = random.Random(case + 7)
        for _ in range(4): T3.draw_leaf(r3)
        for leaf in todo[:len(todo) // 2]: T3.resolve(leaf, T3.node_bounds(leaf)[0])
        fr3 = T3.frontier_record(); assert engine.Tree.rebuild(m, cut, fr3['resolved_leaves'], fr3['extra_expanded']).U_t == T3.U_t; st['rebuild'] += 1
    assert st['strict_slack_models'] > 0 and st['zero_prefix_models'] > 0
    out = dict(st)
    m0 = {'cards': [2, 2], 'factors': [dict(scope=(0, 1), values=[F(0)] * 4)], 'evidence': {}}; r0 = engine.run_component(m0, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1]); R['executions'] += 1
    assert r0['status'] == 'PROVED_ZERO_EVIDENCE'; out['U0_root_deterministic_zero'] = True
    mz = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(0), F(0), F(0)]}], 'evidence': {}}
    rz = engine.run_component(mz, time.monotonic() + 5, 1, 9, 'point', F(1, 20), F(1, 20), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1], max_trials=3); R['executions'] += 1
    assert rz['status'] == 'TOO_WIDE' and rz['guarantee'] == 'NONE' and rz['stats']['positive_trials'] == 0; out['positive_Z_zero_prefix_refuses'] = True
    class BadTree(engine.Tree):
        def draw_leaf(self, rng):
            a, q, z, tr, u = super().draw_leaf(rng); return a, q, z, tr, u / 1000
    for mode in ('point', 'conditional'):
        try: engine.run_component(chain(5, 3), time.monotonic() + 5, 1, 2, mode, F(1, 10), F(1, 10), 10, 3 * 2 ** 30, 0, fixed_cutset=[0, 2], fixed_order=[1, 3, 4], max_trials=50, tree_factory=BadTree, resolve=False); raise AssertionError('invalid envelope accepted')
        except engine.EngineStop as e: assert e.outcome == 'INVALID_PLAN_OR_CERTIFICATE'
    out['production_envelope_guard'] = True; return out


def q5_sampling_backend():
    out = {}
    m = {'cards': [3, 2], 'factors': [dict(scope=(0,), values=[F(1), F(2), F(3)]), dict(scope=(0, 1), values=[F(1)] * 6)], 'evidence': {}}; T = engine.Tree(m, [0])
    rng = random.Random(20261113); counts = [0, 0, 0]; N = 60000
    for _ in range(N):
        a, q, z, tr, u = T.draw_leaf(rng); counts[a[0]] += 1; assert q == [F(1, 6), F(1, 3), F(1, 2)][a[0]]
    for s_, p in enumerate((F(1, 6), F(1, 3), F(1, 2))): assert abs(counts[s_] / N - float(p)) < 5 * math.sqrt(float(p) * (1 - float(p)) / N)
    out['production_random_backend_frequencies'] = counts; out['prng'] = engine.POLICY['prng']; return out


def q6_confidence():
    out = {}
    from decimal import Decimal, getcontext; getcontext().prec = 60
    for rho, V, alpha in ((F(1, 4), F(10), F(1, 2000000)), (F(1, 4), F(1, 4), F(1, 40)), (F(1, 4), F(10 ** 6), F(1, 10 ** 9))):
        bU = rig.range_boundary_up(rho, V, alpha); s = Decimal((rho + V).numerator) / Decimal((rho + V).denominator); arg = s / (Decimal(rho.numerator) / Decimal(rho.denominator) * (Decimal(alpha.numerator) / Decimal(alpha.denominator)) ** 2)
        ref = (s * arg.ln()).sqrt(); bd = Decimal(int(bU.numerator)) / Decimal(int(bU.denominator)); assert bd >= ref and (bd - ref) / ref < Decimal('1e-30'); R['helper_evaluations'] += 1
    for l in range(1, 17):
        lam = F(1, 2 ** l); lo, hi = rig.psi(lam); ref = -(Decimal(1) - Decimal(lam.numerator) / Decimal(lam.denominator)).ln() - Decimal(lam.numerator) / Decimal(lam.denominator)
        assert Decimal(int(lo.numerator)) / Decimal(int(lo.denominator)) <= ref <= Decimal(int(hi.numerator)) / Decimal(int(hi.denominator)); R['helper_evaluations'] += 1
    out['boundary_psi_enclosures'] = True
    A = 1 + F(1, 2 ** 130); coeff = (-A, A, -A * F(2, 9)); g = lambda t: coeff[0] * t * t + coeff[1] * t + coeff[2]
    iv = rig.shrunk_rejection(*coeff); assert iv and F(1, 3) < iv[0] < iv[1] < F(2, 3) and g(iv[0]) > 0 and g(iv[1]) > 0; out['review_witness_1'] = True
    lam = F(1, 2); omega = F(6) / F(98696044011, 10 ** 10); L = rig.log_threshold_up(1, F(1, 4000000), omega); plo, phi = rig.psi(lam); n = 128; a2 = -phi * n; a1 = lam * n; a0 = -L
    o = rig.shrunk_rejection(a2, a1, a0)
    if o: assert all(a2 * t * t + a1 * t + a0 > 0 for t in (o[0], o[1]))
    out['review_witness_2_family'] = o is not None
    rng = random.Random(5); bad = 0
    for _ in range(3000):
        r1 = F(rng.randrange(-10 ** 6, 10 ** 6), 10 ** 6); r2 = r1 + F(rng.randrange(1, 10 ** 6), 10 ** 6); Aq = F(rng.randrange(1, 10 ** 9), rng.randrange(1, 10 ** 9)) * (1 + F(1, 2 ** rng.randrange(1, 200)))
        o = rig.shrunk_rejection(-Aq, Aq * (r1 + r2), -Aq * r1 * r2); R['helper_evaluations'] += 1
        if o is not None and not (r1 < o[0] < o[1] < r2): bad += 1
    assert bad == 0; out['random_concave_quadratics_3000'] = True
    rr = rig.quad_roots_outer(F(-1), F(1), F(-2, 9)); assert rr[0][0] <= F(1, 3) <= rr[0][1] and rr[1][0] <= F(2, 3) <= rr[1][1] and rr[0][1] <= rr[1][0]; bad = 0
    for _ in range(1000):
        r1 = F(rng.randrange(-10 ** 6, 10 ** 6), 10 ** 6); r2 = r1 + F(rng.randrange(0, 10 ** 6), 10 ** 6); Aq = F(rng.randrange(-10 ** 6, 10 ** 6) or 1, rng.randrange(1, 10 ** 6)); (a, b), (c, d) = rig.quad_roots_outer(Aq, -Aq * (r1 + r2), Aq * r1 * r2); R['helper_evaluations'] += 1
        if not (a <= r1 <= b and c <= r2 <= d and b <= c): bad += 1
    assert bad == 0; out['quad_roots_outer_repaired_1000'] = True
    ivq = rig.IV(-(1 + F(1, 2 ** 60)), F(1)); sq = ivq.sq().frac(); assert sq[0] == 0 and sq[1] >= (1 + F(1, 2 ** 60)) ** 2; out['IV_sq'] = True
    for pw in (540, 1075):
        a = F(1, 2 ** pw); model = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(1)]}], 'evidence': {}}
        for mode in ('point', 'conditional'):
            r = engine.run_component(model, time.monotonic() + 30, 123, 456, mode, F(1, 2000000), F(1, 2000000), 2, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[], max_trials=1, resolve=False); S = r['stats']['sufficient_statistics']; ex = (a / F(1, 2)) / F(S['U_root']); R['executions'] += 1
            assert F(S['b_lo']) <= ex <= F(S['b_hi']) and F(S['e_lo']) <= ex * ex <= F(S['e_hi']) and F(S['a_lo'][0]) <= ex <= F(S['a_hi'][0]) and F(S['c_lo'][0]) <= ex * ex <= F(S['c_hi'][0])
    out['underflow_statistics_enclosed'] = True
    rng = random.Random(6); S = engine.Stream([3], [], F(1), F(1, 20), F(1, 20), 3, list(range(1, 17))); exb = F(0); exe = F(0); exa = [F(0)] * 3; exc = [F(0)] * 3; exd = [F(0)] * 3
    for _ in range(500):
        x = F(rng.randrange(0, 2 ** 40), 2 ** (40 + rng.randrange(0, 1030))); j = rng.randrange(3); lo, hi = rig.df_lo(x), rig.df_hi(x); Y = S.np.zeros(3); Yh = S.np.zeros(3); Y[j] = lo; Yh[j] = hi
        S.add_residual(lo, hi, Y, Yh); exb += x; exe += x * x; exa[j] += x; exc[j] += x * x; exd[j] += x * x; R['helper_evaluations'] += 1
    assert F(S.b_lo) <= exb <= F(S.b_hi) and F(S.e_lo) <= exe <= F(S.e_hi) and all(F(S.a_lo[j]) <= exa[j] <= F(S.a_hi[j]) and F(S.c_lo[j]) <= exc[j] <= F(S.c_hi[j]) and F(S.d_lo[j]) <= exd[j] <= F(S.d_hi[j]) for j in range(3)); out['directed_accumulators_500'] = True
    segs = engine._subtract(F(0), F(1), [(F(1, 10), F(3, 10)), (F(6, 10), F(8, 10))]); assert len(segs) == 3; out['nonconvex_accepted_set'] = 3
    r = engine.run_component(chain(3, 2), time.monotonic() + 5, 1, 2, 'point', F(1, 20), F(1, 40), 7, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1, 2], max_trials=2, resolve=False); d = r['stats']['design']; R['executions'] += 1
    assert F(d['alpha_range']) == F(1, 20) / 7 and F(d['alpha_variance']) == F(1, 40) / 7 and d['K_total'] == 7 and F(d['U_root']) == engine.Tree(chain(3, 2), [0]).u_root; out['design_record_fields'] = True
    return out


def q7_publication():
    out = {}
    assert engine.feasible_point([(F(0), F(6, 10))] * 3, F(3, 10)) is None
    pol = dict(engine.POLICY); pol['epsilon'] = F(1, 20); m = chain(5, 2)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m, time.monotonic() + 120, 3, 4, mode, F(1, 40), F(1, 40), 10, 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 2], fixed_order=[1, 3, 4], max_trials=3000000, resolve=False); R['executions'] += 1
        g, ok = check_publication(r, m, F(1, 20), 'q7 ' + mode); assert g == 'PAC' and ok, (mode, ok)
        out['pac_publication_%s' % mode] = dict(trials=r['stats']['trials_completed'], contains_truth=ok, certifiers=sorted(set(r['certifier_per_row'])))
    m15 = chain(15, 2); cut = list(range(11)); order = [v for v in range(15) if v not in cut]
    r = engine.run_component(m15, time.monotonic() + 300, 8, 9, 'conditional', F(1, 40), F(1, 40), 30, 3 * 2 ** 30, 0, pol, fixed_cutset=cut, fixed_order=order, max_trials=20000, resolve=True); R['executions'] += 1
    g, ok = check_publication(r, m15, F(1, 20), 'q7 adaptive'); assert r['stats']['resolved_cells'] > 0 and r['stats']['sufficient_statistics']['A_hi'] > 0 and ok
    out['adaptive_publication'] = dict(guarantee=g, route=r['stats'].get('route'), resolved=r['stats']['resolved_cells'], trials=r['stats']['trials_completed'], U_t_over_U=r['stats']['U_t_over_U_root'], contains_truth=ok)
    for power, odds in [(1075, 1), (2000, 3)]:
        a = F(1, 2 ** power); mm = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(odds)]}], 'evidence': {}}
        rr = solve.solve(mm, time.monotonic() + 20, 'P1_PAC_CONDITIONAL', 'q7'); R['executions'] += 1; Z, N, marg = truth(mm)
        assert rr['guarantee_type'] == 'DETERMINISTIC' and all(lo <= p <= hi for (lo, hi), p in zip(rr['intervals'][0], marg[0])); R['coordinates_checked'] += 2
    out['tiny_a_exact_answers_published'] = True
    m = {'cards': [2], 'factors': [dict(scope=(0,), values=[F(2) ** 900, F(2) ** 899])], 'evidence': {}}; r = contrib.cell_kernel(m, {}); assert r['B0'][0] <= F(2) ** 900 + F(2) ** 899 <= r['B0'][1]; out['huge_exponents'] = True
    return out


def q9_continuation():
    out = {}
    m = {'cards': [3] * 7, 'factors': [dict(scope=(i, (i + 1) % 7), values=[F(x) for x in (1, 2, 3, 4, 5, 6, 7, 8, 9)]) for i in range(7)], 'evidence': {}}
    r = engine.run_component(m, time.monotonic() + 0.4, 1, 2, 'conditional', F(1, 2 * 10 ** 6), F(1, 2 * 10 ** 6), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False); R['executions'] += 1
    assert r['guarantee'] == 'NONE' and r['stats']['terminal'] == 'DEADLINE'; out['deadline_refuses'] = True
    calls = {'n': 0}; ok_ = engine.kernel_cell; oe = engine.exact_cell
    def failing(orig):
        def f(*a, **k):
            calls['n'] += 1
            if calls['n'] == 3: raise contrib.CellStop('MEMORY', 'injected')
            return orig(*a, **k)
        return f
    engine.kernel_cell = failing(ok_); engine.exact_cell = failing(oe)
    try: r2 = engine.run_component(m, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False); R['executions'] += 1
    finally: engine.kernel_cell = ok_; engine.exact_cell = oe
    assert r2['status'] == 'MEMORY' and r2['stats']['trials_completed'] == 2; out['failed_trial_terminates'] = True
    import forest, stream, stream_float, dag, cex_executor as X
    cyc = {'cards': [2] * 4, 'factors': [{'scope': (i, (i + 1) % 4), 'values': list(map(F, [3, 1, 1, 3]))} for i in range(4)], 'evidence': {}}
    def raiser(exc):
        def f(*a, **k): raise exc
        return f
    of = forest.solve; forest.solve = raiser(forest.UnsupportedError('test: forest off')); conts = {}
    try:
        osf = stream_float.solve; stream_float.solve = raiser(stream.UnsupportedError('injected representation limit'))
        try: rr = solve.solve(cyc, time.monotonic() + 30, 'H1_HYBRID', 'q9a'); conts['stream.UnsupportedError'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['executions'] += 1
        finally: stream_float.solve = osf
        odisc = core._discover_component; oexec = core._execute_component
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'dag', 'forecast': 1, 'discovery': [], 'model': cm, 'dag': None}
        oplan = dag.execute_plan; dag.execute_plan = raiser(dag.Unsupported('injected dag refusal'))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9b'); conts['dag.Unsupported'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['executions'] += 1
        finally: core._discover_component = odisc; dag.execute_plan = oplan
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm, 'order': list(range(len(cm['cards'])))}
        oex = X.execute; X.execute = raiser(X.Stop('RANGE', 'injected', {})); osup = support.solve; support.solve = raiser(support.Unsupported('injected exact fallback refusal'))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9c'); conts['support.Unsupported_after_RANGE'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['executions'] += 1
        finally: X.execute = oex; support.solve = osup; core._discover_component = odisc
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm}; core._execute_component = raiser(support.ResourceStop('MEMORY', {}))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9d'); conts['ResourceStop.MEMORY'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['executions'] += 1
        finally: core._discover_component = odisc; core._execute_component = oexec
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm}; core._execute_component = raiser(support.ResourceStop('DEADLINE', {}))
        try:
            try: solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9e'); raise AssertionError('deadline refusal continued')
            except support.ResourceStop as e: assert e.reason == 'DEADLINE'
        finally: core._discover_component = odisc; core._execute_component = oexec
    finally: forest.solve = of
    assert all(v[0] == 'DETERMINISTIC' for v in conts.values()) and len(conts) == 4, conts; out['continuation_per_backend_class'] = conts; out['deadline_refusal_final'] = True
    D = TMP / 'q9'; D.mkdir(exist_ok=True); write_uai({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, D / 'z.uai'); outp = D / 'w.json'
    subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() - 1.0), '--seed', 's', '--nonce', 'n', '--budget', '0'], check=True, cwd=CODE); wz = json.load(open(outp)); R['executions'] += 1
    assert wz['outcome'] == 'DEADLINE' and wz['guarantee_type'] == 'NONE'
    subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() + 10), '--seed', 's', '--nonce', 'n', '--budget', '10'], check=True, cwd=CODE); wz2 = json.load(open(outp)); R['executions'] += 1
    assert wz2['outcome'] == 'PROVED_ZERO_EVIDENCE' and isinstance(wz2.get('zero_evidence_proof'), dict) and gate.verify_zero_proof(core.read_uai(D / 'z.uai')[0], wz2['zero_evidence_proof']) is None
    out['late_zero_is_DEADLINE_timely_zero_verified'] = True
    bad = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(1, 10 ** 1000), F(1), F(1)]}], 'evidence': {}}
    for fn in (lambda: contrib.cell_kernel(bad, {}, deadline=time.monotonic() + 10), lambda: engine.Template(bad, [], [0, 1], deadline=time.monotonic() + 10)):
        try: fn(); raise AssertionError('RANGE not raised')
        except contrib.CellStop as e: assert e.kind == 'RANGE'
    out['typed_range'] = True
    for arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
        rr = solve.solve({'cards': [2], 'factors': [], 'evidence': {}}, time.monotonic() + 10, arm, 'e'); assert rr['points'] == [[F(1, 2), F(1, 2)]]; R['executions'] += 1
    out['factorless_all_arms'] = True; return out


def q10_existing():
    out = {}
    for ctl in (os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'PAC_EMPIRICAL_2026-11-12', 'review_items', 'host_budget_control_v14.py'), '/Users/adis/Workspace/pgm/code/runs/mdi_2026-10-28/PAC_EMPIRICAL_2026-11-12/review_items/host_budget_control_v14.py'):
        if os.path.exists(ctl):
            p = subprocess.run([PY, ctl, os.path.join(NEWARM, 'cex_executor.py')], capture_output=True, text=True); r = json.loads(p.stdout); out['host_budget_control'] = {k: r[k] for k in ('host_budget_peak_bytes', 'traced_peak_bytes')}; break
    out['claim'] = 'NARROWED: HostBudget is an accounting of the named containers, not a proven bound; the only whole-worker bound is the sampled RSS policy'
    iso = TMP / 'q10_iso'; (iso / 'cex').mkdir(parents=True); shutil.copytree(NEWARM, iso / 'cex' / 'newarm', ignore=shutil.ignore_patterns('__pycache__', 'native_cache', '*.dylib', '*.so'))
    for f in sorted(os.listdir(os.path.join(CODE, 'cex'))):
        if f.endswith('.py'): shutil.copy2(os.path.join(CODE, 'cex', f), iso / 'cex' / f)
    if os.path.isdir(os.path.join(CODE, 'cex', 'baseline')): shutil.copytree(os.path.join(CODE, 'cex', 'baseline'), iso / 'cex' / 'baseline', ignore=shutil.ignore_patterns('__pycache__', 'native_cache', '*.dylib', '*.so'))
    rd = iso / 'runs' / 'mdi_2026-10-28' / 'CERTIFIED_EXECUTOR_2026-11-11'; rd.mkdir(parents=True); src_rd = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CERTIFIED_EXECUTOR_2026-11-11')
    shutil.copytree(os.path.join(src_rd, 'campaign_specs'), rd / 'campaign_specs'); (rd / 'campaigns').mkdir()
    for camp in ('baseline_20s_all46', 'newarm_20s_all46_v13'): shutil.copytree(os.path.join(src_rd, 'campaigns', camp), rd / 'campaigns' / camp)
    for f in os.listdir(src_rd):
        if f.endswith('.json'): shutil.copy2(os.path.join(src_rd, f), rd / f)
    q = subprocess.run([PY, str(iso / 'cex' / 'newarm' / 'cex_qualification.py')], capture_output=True, text=True, cwd=str(iso / 'cex' / 'newarm')); lines = [l for l in q.stdout.splitlines() if l.startswith('{')]
    assert q.returncode == 0 and lines, q.stderr[-800:]; qq = json.loads(lines[-1]); assert qq['all_pass'], qq
    out['frozen_executor_isolated'] = dict(passed=qq['passed'], total=qq['total'], controls=len(qq['controls'])); out['dependencies_for_standalone_replay'] = 'cex/*.py, cex/baseline/, cex/newarm/, runs/mdi_2026-10-28/CERTIFIED_EXECUTOR_2026-11-11/{campaign_specs, campaigns/baseline_20s_all46, campaigns/newarm_20s_all46_v13, *.json}'; return out


def q11_diagnostic():
    rng = random.Random(5); t0 = time.monotonic(); pol = dict(engine.POLICY); pol['epsilon'] = F(1, 20); rows = []; miss = 0; tot = 0; pub = 0
    for trial in range(60):
        m = rand_model(rng, 3, 5, 3); n = len(m['cards']); Z, N, marg = truth(m); K = sum(m['cards']); mode = 'conditional' if trial % 3 == 0 else 'point'; resolve = (trial % 6 == 0)
        try: r = engine.run_component(m, time.monotonic() + 12, 1000 + trial, 2000 + trial, mode, F(1, 20), F(1, 20), K, 3 * 2 ** 30, 0, pol, fixed_cutset=[0], fixed_order=list(range(1, n)), max_trials=2000000, resolve=resolve)
        except engine.EngineStop as e: assert e.outcome == 'DEADLINE', e; r = dict(status='DEADLINE', guarantee='NONE', stats=dict(e.stats, trials_completed=e.stats.get('trials_completed')))
        tot += 1; R['executions'] += 1
        okc = None
        if r['status'] == 'PUBLISHED':
            pub += 1; okc = contained(r['intervals'], r['points'], marg, F(1, 20)); R['coordinates_checked'] += K
            if r['guarantee'] == 'DETERMINISTIC': assert okc, 'deterministic publication misses the truth'
            elif not okc: miss += 1
        rows.append(dict(trial=trial, mode=mode, resolve=resolve, status=r['status'], guarantee=r['guarantee'], trials=r['stats'].get('trials_completed'), resolved=r['stats'].get('resolved_cells'), contains_truth=okc))
    assert miss <= 14, (miss, tot)
    return dict(attempted=tot, published=pub, pac_misses=miss, delta='1/10 per run (two families 1/20)', criterion='misses <= 14 (P[X > 14] = 6.66e-4 at p = 0.1, n = 60)', note='bug detection only; cannot verify 1e-6', wall_s=round(time.monotonic() - t0, 1), rows=rows)


def q12_closure_partial_cover():
    out = {}; eps = engine.POLICY['epsilon']
    for a in (F(1, 2), F(1, 10), F(0)):
        model = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(1)]}], 'evidence': {}}
        r = engine.run_component(model, time.monotonic() + 30, 0, 0, 'conditional', F(1, 2000000), F(1, 2000000), 2, 64 * 1024 ** 2, 0, fixed_cutset=[0], fixed_order=[], max_trials=8); R['executions'] += 1
        if a == 0: assert r['status'] == 'PROVED_ZERO_EVIDENCE'
        else: assert r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC' and r['stats']['terminal'] == 'COVER_COMPLETE' and r['stats']['trials_completed'] == 2 and r['stats']['frontier']['U_t'] == '0/1'; check_publication(r, model, eps, 'slack cover')
    out['review_slack_cover_a_1/2_1/10_0'] = True
    m = chain(13, 3, [{'scope': (1,), 'values': [F(1), F(1, 2)]}]); rr = solve.solve(m, time.monotonic() + 30, 'P1_PAC_CONDITIONAL', 'q12a'); R['executions'] += 1; c = rr['certificate']['components'][0]
    Z, N, marg = truth(m); assert rr['guarantee_type'] == 'DETERMINISTIC' and 'exact_cover' in c['route'] and c['resolved_cells'] == 2 and contained(rr['intervals'], rr['points'], marg, eps); R['coordinates_checked'] += 26; out['review_full_solver_cover'] = True
    star = {'cards': [257] + [2] * 6, 'factors': [{'scope': (0, i), 'values': [F(1)] * 514} for i in range(1, 7)], 'evidence': {}}; rr = solve.solve(star, time.monotonic() + 60, 'P1_PAC_CONDITIONAL', 'q12b'); R['executions'] += 1; c = rr['certificate']['components'][0]
    Z, N, marg = truth(star); assert rr['guarantee_type'] == 'DETERMINISTIC' and 'partial_cover' in c['route'] and c['resolved_cells'] < 257 and contained(rr['intervals'], rr['points'], marg, eps); R['coordinates_checked'] += 269; out['review_partial_cover_star'] = dict(resolved=c['resolved_cells'], trials=c['trials'])
    rng = random.Random(12); comp = part = det = pac = 0; pac_miss = 0
    for trial in range(25):
        m = rand_model(rng, 3, 5, 3, zero_p=0.15); n = len(m['cards']); Z, N, marg = truth(m)
        if Z == 0: continue
        cut = rng.sample(range(n), rng.randint(1, n - 1))
        r = engine.run_component(m, time.monotonic() + 30, trial, trial + 1, 'conditional', F(1, 10), F(1, 10), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=100000); R['executions'] += 1
        if r['status'] == 'PUBLISHED':
            g, ok = check_publication(r, m, eps, 'q12 generic')
            if g == 'DETERMINISTIC': det += 1
            else:
                pac += 1
                if not ok: pac_miss += 1
        if r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC' and 'exact_cover' in r['stats'].get('route', ''): comp += 1; assert r['stats']['frontier']['U_t'] == '0/1'
        else:
            S = r['stats']['sufficient_statistics']; A_lo = F(S['A_exact_lo']); A_hi = F(S['A_exact_hi']); Ut = F(r['stats']['frontier']['U_t'])
            assert A_lo <= Z <= A_hi + Ut, 'partial cover: resolved mass + residual envelope does not enclose Z'; part += 1
    assert pac_miss <= 3, pac_miss
    out['generic'] = dict(complete_covers=comp, partial_or_pac=part, deterministic_publications=det, pac_publications=pac, pac_misses=pac_miss)
    orig = engine.run_component; detected = {'n': 0}
    def wrong_pac(*a, **k):
        rr = orig(*a, **k)
        if rr.get('status') == 'PUBLISHED':
            Z, N, marg = truth(a[0]); iv = []; pts = []
            for row in marg:
                idx = min(range(len(row)), key=lambda j: row[j]); pr = [F(int(j == idx)) for j in range(len(row))]; iv.append([(p, p) for p in pr]); pts.append(pr)
            rr['intervals'] = iv; rr['points'] = pts
        return rr
    engine.run_component = wrong_pac
    try:
        for trial in range(6):
            m = rand_model(rng, 3, 4, 3); n = len(m['cards']); Z, N, marg = truth(m)
            if Z == 0: continue
            cut = rng.sample(range(n), rng.randint(1, n - 1)); r = engine.run_component(m, time.monotonic() + 30, 100 + trial, 101 + trial, 'conditional', F(1, 10), F(1, 10), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=100000); R['executions'] += 1
            if r['status'] != 'PUBLISHED': continue
            try: check_publication(r, m, eps, 'corrupted')
            except AssertionError: detected['n'] += 1; continue
            raise AssertionError('corrupted publication NOT detected')
    finally: engine.run_component = orig
    assert detected['n'] > 0; out['output_corruption_detected'] = detected['n']
    m6 = chain(6, 2)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m6, time.monotonic() + 10, 1, 2, mode, F(1, 10), F(1, 10), 12, 3 * 2 ** 30, 0, fixed_cutset=[0, 2], fixed_order=[1, 3, 4, 5], max_trials=50, resolve=False); assert r['stats']['resolved_cells'] == 0; R['executions'] += 1
    out['ablation_residual_region_fixed'] = True; return out


def q13_adapters_and_pipeline():
    out = {}; import legacy_cbi_uai as LC, uai_export
    from ext import uai as U
    meta = {'d': 1, 'blocks': [{'id': 0, 'rows': [0, 1]}], 'cards': [2]}
    for bad in ([[(F(1, 2), F(1, 2))]], [[(F(1, 2), F(1, 2)), (F(1, 2), F(1, 2)), (F(0), F(0))]], [], [[(F(2), F(3)), (F(0), F(0))]]):
        try: LC.native_enclosures(meta, bad); raise AssertionError('malformed accepted')
        except LC.AdapterError: pass
    try: LC.native_enclosures(meta, [[(F(1, 2), F(1, 2)), (F(1, 2), F(1, 2))]], meta_sha256='0' * 64); raise AssertionError('wrong metadata accepted')
    except LC.AdapterError: pass
    out['truncated_misshaped_wrongly_bound_refused'] = True
    meta4 = {'d': 2, 'blocks': [{'id': 0, 'rows': [0, 1, 2, 3]}], 'cards': [4]}; sc = LC.native_score(meta4, [[(F(49, 200), F(51, 200))] * 4]); assert sc['native_completion'] == 'STATE_ROWS_ONLY_WIDTH_EXCEEDED'; out['native_width_scored_separately'] = sc['max_coordinate_width']
    D = TMP / 'q13'; D.mkdir(); m = {'cards': [2, 3], 'factors': [{'scope': (0, 1), 'values': [F(3, 2), F(1), F(11, 10), F(7, 3), F(1, 5), F(2)]}, {'scope': (0,), 'values': [F(1), F(11, 10)]}], 'evidence': {}}
    ex = uai_export.write_uai(m, D / 'x.uai'); mm, b = core.read_uai(D / 'x.uai'); um = U.read_model(str(D / 'x.uai')); ue = U.read_evidence(str(D / 'x.uai.evid'))
    Z1, N1, marg1 = truth(m); Z2, N2, marg2 = truth(mm); assert marg1 == marg2 and um.nvars == 2 and ue == {} and all('/' not in tok for tok in Path(D / 'x.uai').read_text().split()); out['integer_export_exact_and_parsed_by_repository_readers'] = True
    libdai = os.path.join(CODE, 'bench', 'libdai', 'libdai_mar'); merlin = '/Users/adis/Workspace/comparators/merlin/build/merlin'; ext_ = {}
    if os.path.exists(libdai):
        p = subprocess.run([libdai, str(D / 'x.uai'), str(D / 'x.uai.evid'), str(D / 'x.MAR'), str(D / 'x.side.json'), 'JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]'], capture_output=True, text=True, timeout=60); rows = None
        if p.returncode == 0 and (D / 'x.MAR').exists():
            toks = (D / 'x.MAR').read_text().split(); i = toks.index('MAR') + 1; n = int(toks[i]); i += 1; rows = []
            for _ in range(n): k = int(toks[i]); i += 1; rows.append([F(toks[i + j]) for j in range(k)]); i += k
        ext_['libdai'] = dict(rc=p.returncode, max_abs_error=float(max(abs(a - t) for r_, tr in zip(rows, marg1) for a, t in zip(r_, tr))) if rows else None); assert rows and ext_['libdai']['max_abs_error'] < 1e-6
    if os.path.exists(merlin):
        p = subprocess.run([merlin, '--input-file', str(D / 'x.uai'), '--evidence-file', str(D / 'x.uai.evid'), '--task', 'MAR', '--algorithm', 'cte', '--output-format', 'uai', '--output-file', str(D / 'x_m')], capture_output=True, text=True, timeout=60)
        txt = (D / 'x_m.MAR').read_text() if (D / 'x_m.MAR').exists() else ''; ext_['merlin'] = dict(rc=p.returncode, status_true='true' in txt); assert 'true' in txt
    out['external_readers_parse_export'] = ext_
    RD = D / 'pipeline'; RD.mkdir(); qg = D / 'qgrid'; qg.mkdir(); import legacy_qgrid as LQ
    mq, _ = LQ.grid_model(2, F(3, 2), F(11, 10), 0); exq = LQ.write_uai(mq, str(qg / 'qgrid_tiny.uai'))
    json.dump(dict(instances=[dict(case_id='qgrid_tiny_L2', model_path=str(qg / 'qgrid_tiny.uai'), evidence_path=exq['evidence_path'], model_sha256=exq['model_sha256'], evidence_sha256=exq['evidence_sha256'], export_factor_scalars=exq['factor_scalars'])]), open(D / 'QG.json', 'w'))
    import campaign as CP
    oP, oC, oA, oB = CP.PRIMARY, CP.COMPARATORS, CP.ABLATION, CP.BUDGETS
    CP.PRIMARY = [('P1_PAC_CONDITIONAL', 1), ('H1_HYBRID', 1)]; CP.COMPARATORS = []; CP.ABLATION = []; CP.BUDGETS = [20.0]
    try:
        with contextlib.redirect_stdout(io.StringIO()): CP.manifest(str(RD), '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs', dev=False, qgrid_inventory=str(D / 'QG.json'), include=('qgrid',))
        man = json.load(open(RD / 'CAMPAIGN_MANIFEST.json')); assert len(man['cells']) == 2 and all('/' in k for k in man['candidate_artifact_hashes']) and man['candidate_artifact_hashes']
        with contextlib.redirect_stdout(io.StringIO()): CP.run(str(RD))
        R['executions'] += 2
    finally: CP.PRIMARY, CP.COMPARATORS, CP.ABLATION, CP.BUDGETS = oP, oC, oA, oB
    with contextlib.redirect_stdout(io.StringIO()): rc = gate.main(str(RD))
    g = json.load(open(RD / 'GATE_RESULT.json')); assert rc == 0, g['failures'][:3]
    import report as RP
    with contextlib.redirect_stdout(io.StringIO()): RP.main(str(RD))
    res = json.load(open(RD / 'RESULTS_PAC.json')); assert len(res['runs']) == 2 and not res['unrun'] and all(x['outcome'] == 'PUBLISHED' for x in res['runs'])
    import worker as W; stub = dict(suite_version=SUITE_VERSION + ' (pipeline-test stub)', all_pass=True, passed=1, total=1, groups=[dict(name='stub', ok=True)], candidate_sources=W.candidate_sources(), executions=0, helper_evaluations=0, coordinates_checked=0); json.dump(stub, open(RD / 'Q_stub.json', 'w'))
    p = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), str(RD), '--qualification', str(RD / 'Q_stub.json')], capture_output=True, text=True); assert p.returncode == 0, p.stdout + p.stderr[-300:]
    stub['candidate_sources'] = {k: '0' * 64 for k in stub['candidate_sources']}; json.dump(stub, open(RD / 'Q_bad.json', 'w'))
    p2 = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), str(RD), '--qualification', str(RD / 'Q_bad.json')], capture_output=True, text=True); assert p2.returncode == 1 and 'UNQUALIFIED' in p2.stdout
    man['cells'].append(dict(man['cells'][0], cell_id='extra')); json.dump(man, open(RD / 'CAMPAIGN_MANIFEST.json', 'w'))
    p3 = subprocess.run([PY, os.path.join(HERE, 'campaign.py'), 'run', str(RD)], capture_output=True, text=True); assert p3.returncode != 0 and 'RESUME REFUSED' in (p3.stdout + p3.stderr)
    out['real_pipeline_manifest_run_gate_report_closeout'] = dict(cells=2, gate_passed=g['gate_passed'], closeout_qualified_with_matching_identity=True, closeout_refuses_foreign_identity=True, resume_preflight_refuses_edited_manifest=True); return out


if __name__ == '__main__':
    group('Q1_identity_and_gate_end_to_end', q1_identity_gate); group('Q2_exact_cell_oracle', q2_masses); group('Q3_laws_and_actual_adaptive_accumulation', q3_laws_and_actual_accumulation); group('Q4_frontier_invariants_random_models', q4_frontier_invariants); group('Q5_actual_sampling_backend', q5_sampling_backend); group('Q6_confidence_arithmetic', q6_confidence); group('Q7_numerical_publication_truth_asserted', q7_publication); group('Q9_continuation_every_backend_class', q9_continuation); group('Q10_existing_defects_isolated', q10_existing); group('Q11_diagnostic_coverage_attempted_runs', q11_diagnostic); group('Q12_exact_closure_partial_cover_sensitivity', q12_closure_partial_cover); group('Q13_adapters_and_executable_pipeline', q13_adapters_and_pipeline)
    srcs = {}
    for d, tag in ((HERE, 'pac'), (NEWARM, 'newarm')):
        for f in sorted(os.listdir(d)):
            if f.endswith(('.py', '.cpp')): srcs['%s/%s' % (tag, f)] = hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest()
    R.update(passed=passed, total=total, all_pass=passed == total, Q8='candidate validation (theory section 9) OPTIONAL in the handoff; not implemented; recorded', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), candidate_sources=srcs, temp_dir=str(TMP), counts_note='executions = end-to-end inference executions (run_component / solve / worker); helper_evaluations = arithmetic helper calls; coordinates_checked = published coordinates compared with the independent truth')
    json.dump(R, open(os.path.join(HERE, 'PAC_QUALIFICATION.json'), 'w'), indent=1, default=str); print(json.dumps({'passed': passed, 'total': total, 'executions': R['executions'], 'helper_evaluations': R['helper_evaluations'], 'coordinates': R['coordinates_checked'], 'all_pass': R['all_pass']})); sys.exit(0 if R['all_pass'] else 1)
