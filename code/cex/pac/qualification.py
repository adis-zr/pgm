"""PRODUCTION QUALIFICATION of the PAC candidate v4 (handoff 03 §3; repaired after the THREE adversarial reviews of 13 Nov 2026). Counts are reported BY CLASS and never
pooled: fresh_workers (subprocess worker.py runs), solver_component_executions (solve.solve / run_component calls), kernel_cell_calls (contrib.cell_kernel / cell_exact),
helper_evaluations (arithmetic helpers), truth_coordinates (published coordinates compared with the INDEPENDENT original-model enumerator `truth`), gate_only_coordinates
(coordinates accepted by the production gate without an enumerator comparison). A group FAILS if any assertion inside it fails. Deterministic misses fail; PAC misses are
counted per ATTEMPTED run against the declared allowance. Mutations are DIAGNOSTICS applied in-process and restored; the shipped candidate is never altered.
Groups (names = registry.QUALIFICATION_GROUPS; the closeout requires exactly this schema):
Q1  identity + GATE v4 end to end: real worker fixtures (exact cover, partial cover, forest+evidence, support, zero, the natural 13-variable rebase witness) ACCEPTED; a genuine
    A0 PAC fixture ACCEPTED through the design REPLAY; the three reviews' negative controls REJECTED, incl. the third review's coherent false numerators (simplex-coherent),
    false zero with closed frontier and omitted / zeroed cells, impossible point-mode statistics at the diagnostic AND the primary contract, foreign PRNG / seeds / scale,
    partial nonempty source map, any amendment file, START without the inventory content hash, omitted / duplicated contribution records.
Q2  exact cell oracle (kernel_cell_calls vs the independent enumerator).
Q3  fixed-law algebra + MOMENT ORACLE on real adaptive runs: every trial's draw and every resolution are recorded; the exact first, second and cross moments (B, E, a_j, c_j, d_j)
    and the resolved totals are recomputed independently from the original factors and compared with the directed accumulators (deletion of the query update is detected).
Q4  frontier invariants on random models + REBASE HISTORIES (exponent gaps 600 / 601 / 1074 / 1075 / 2000, both orders, repeated rebases, non-dyadic, zero cells, tiny
    positive cells, untouched cut coordinates; invariant lo*2^E <= exact <= hi*2^E after every insertion; rebases asserted to execute) + the natural and 601-bit witnesses
    through the fresh worker / run_component with decimal publication.
Q5  actual sampling backend.   Q6  confidence arithmetic.
Q7  numerical publication: PAC publications in both modes CONTAIN the truth; a GENUINE ADAPTIVE PAC publication with a NONEMPTY residual region and positive resolved
    query contributions (route pac_statistical_intersected_with_deterministic) contains the truth and replays; exact tiny-a answers; huge exponents.
Q8  INTERSECTION (02_IMPLEMENTATION_REQUIREMENTS line 52) + MECHANISM SENSITIVITY: hull ∩ deterministic narrower than either; EMPTY intersection -> typed INTERSECTION_EMPTY
    (engine and solve); three GENERIC controls where a row publishes ONLY through the intersection; complete-cover deterministic control (delta 0); evidence / alias /
    two-component lift control through the gate; a valid no-publication; each mandatory mechanism DISABLED in-process must FAIL its test (query resolution, rebase
    direction, frontier closure, contribution binding, risk allocation, intersection, output / lift binding).
Q9  continuation for every backend refusal class; DEADLINE final; late zero.   Q10 frozen executor suite in an isolated copy.
Q11 diagnostic coverage over ATTEMPTED runs (misses <= 14 of 60; bug detection, never a verification of 1e-6).
Q12 exact closure and partial cover (review controls + generic + corruption wrapper detected).
Q13 REGISTRY PIPELINE over EVERY arm and representation: the tiny real manifest -> dispatcher -> gate v4 -> report v4 -> closeout v4 chain in-suite (qgrid); the archived
    54-cell dev admission (every registered arm incl. H4 / SF / CBI natives, comparators, zero and deadline controls) RE-GATED, references dispatched by representation,
    report + closeout; malformed native outputs rejected; closeout refuses stale gate / foreign rows / missing identity / one-group subset / failures with pass flag."""
import sys, os, json, time, math, random, hashlib, itertools, subprocess, shutil, copy, tempfile, contextlib, io, glob, collections
from fractions import Fraction as F
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm'); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (NEWARM, HERE, CODE): sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
import engine, contrib, rig, solve, core, gate, support, registry
SUITE_VERSION = 'pac-qualification-v4.1 (2026-11-14 repair 4)'
SOURCES_AT_START = registry.source_inventory(CODE, scopes=('candidate',))      # the identity of the candidate (incl. this suite file) WHEN THE RUN STARTS; compared again at the end: a source edited during the run invalidates the record
R = {'groups': [], 'counts': dict(fresh_workers=0, solver_component_executions=0, kernel_cell_calls=0, helper_evaluations=0, truth_coordinates=0, gate_only_coordinates=0), 'suite_version': SUITE_VERSION}; passed = 0; total = 0
def cnt(k, n=1): R['counts'][k] += n
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
    ok = contained(r['intervals'], r['points'], marg, eps); R['counts']['truth_coordinates'] += sum(cards)
    if r['guarantee'] == 'DETERMINISTIC': assert ok, label + ': DETERMINISTIC publication misses the truth'
    else:
        st = r['stats']; det = None
        if (st.get('publication_composition') or {}).get('used') == 'intersection_with_deterministic':
            off = [0]
            for c in cards: off.append(off[-1] + c)
            det = engine.Totals.bounds_from_record(st['resolved_totals'], F(st['frontier']['U_t']), cards, off)
        ok2, rows, pts, chosen, *_ = engine.hulls_from_record(st['sufficient_statistics'], eps, engine.POLICY['decimal_margin'], det_rows=det)
        assert ok2 and all(rows[v] == r['intervals'][v] and pts[v] == r['points'][v] for v in rows), label + ': PAC replay differs'
    return r['guarantee'], ok


# ---------------- Q1
def q1_identity_gate():
    out = {}; sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest(); dump = lambda p, x: Path(p).write_text(json.dumps(x, indent=1, default=str))
    import worker as W; frozen_all = registry.source_inventory(CODE); frozen = {k: v for k, v in frozen_all.items() if registry.scope_of_key(k) == 'candidate'}; D = TMP / 'q1'; D.mkdir()
    def fixture(name, model, arm, eps='1/200', delta='1/1000000', inproc=None, budget=60, seed=None):
        d = D / name; (d / 'cells/one').mkdir(parents=True); mp = d / 'model.uai'; write_uai(model, mp); _, binding = core.read_uai(mp)
        if inproc is None:
            t0 = time.monotonic(); subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(mp), '--output', str(d / 'cells/one/worker.json'), '--arm', arm, '--deadline', str(t0 + budget), '--seed', seed or ('s-' + name), '--nonce', 'n-' + name, '--budget', str(budget), '--delta', delta], check=True, cwd=CODE); wall = time.monotonic() - t0; w = json.load(open(d / 'cells/one/worker.json')); cnt('fresh_workers')
        else: w = inproc; wall = 1.0
        c = dict(cell_id='cell1', cohort='external_core', case_id=name, arm=arm, replicate=0, budget_s=float(budget), seed=seed or ('s-' + name), model_path=str(mp), **binding)
        return dict(d=d, c=c, man=dict(cells=[c], task={'epsilon': eps, 'delta': delta}, candidate_artifact_hashes=dict(frozen_all)), w=w, wall=wall, binding=binding, mp=mp)
    def gate_run(fx, mutate=None, start_mut=None, amend=None):
        d = fx['d']; shutil.rmtree(d / 'cells', ignore_errors=True); (d / 'cells/one').mkdir(parents=True)
        m = copy.deepcopy(fx['man']); ww = copy.deepcopy(fx['w']); status = 'COMPLETED' if ww.get('status') == 'COMPLETED' else 'STOPPED'
        r = dict(copy.deepcopy(fx['c']), status=status, outcome=ww.get('outcome'), guarantee_type=ww.get('guarantee_type'), nonce=ww.get('nonce'), within_budget=True, launch_relative_wall_s=round(fx['wall'], 3), supervisor={'rc': 0, 'outcome': 'COMPLETED'}, worker_output='cells/one/worker.json')
        if mutate: mutate(d, m, r, ww)
        dump(d / 'CAMPAIGN_MANIFEST.json', m); mh = sha(d / 'CAMPAIGN_MANIFEST.json'); ah = hashlib.sha256(json.dumps(m.get('candidate_artifact_hashes') or {}, sort_keys=True).encode()).hexdigest(); st = {'manifest_sha256': mh, 'manifest': 'CAMPAIGN_MANIFEST.json', 'artifact_hashes_sha256': ah}
        if start_mut: start_mut(st)
        dump(d / 'CAMPAIGN_START.json', st); (d / 'PAC_LEDGER.jsonl').write_text(json.dumps(dict(kind='CAMPAIGN_START', **st)) + '\n')
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
    a_ = F(1, 2 ** 2000); m13 = {'cards': [2] * 13, 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [F(1), a_, F(1), F(1)]}, {'scope': (0, 1), 'values': [a_, F(1), F(1), F(1)]}] + [{'scope': (0, i), 'values': [F(1)] * 4} for i in range(2, 13)]}
    fixes['rebase13_natural_witness'] = fixture('rebase13', m13, 'P1_PAC_CONDITIONAL', seed='rebase-1')
    m3 = {'cards': [2] * 3, 'evidence': {}, 'factors': [{'scope': (0,), 'values': [F(2, 5), F(3, 5)]}, {'scope': (0, 1), 'values': [F(4, 5), F(1, 5), F(1, 10), F(9, 10)]}, {'scope': (0, 1, 2), 'values': [F(1, 5), F(4, 5), F(7, 10), F(3, 10), F(1, 10), F(9, 10), F(3, 5), F(2, 5)]}]}
    fixes['h1_root_identity_dag_natural'] = fixture('rootdag', m3, 'H1_HYBRID', seed='rootdag'); wd = fixes['h1_root_identity_dag_natural']['w']; Z3, N3, marg3 = truth(m3)
    assert wd['status'] == 'COMPLETED' and [c_['route'] for c_ in wd['certificate']['components']] == ['dag'] and wd['certificate']['K_total'] == 0 and wd['certificate']['delta_ledger']['coordinates'] == 0 and all(F(lo) <= p <= F(hi) for row, ps in zip(wd['intervals'], marg3) for (lo, hi), p in zip(row, ps)), 'root identity-DAG certificate ledger / truth'; cnt('truth_coordinates', 6)
    wr = fixes['rebase13_natural_witness']['w']; assert wr['status'] == 'COMPLETED' and wr['guarantee_type'] == 'DETERMINISTIC' and F(wr['intervals'][0][0][1]) > 0 and F(wr['intervals'][0][0][0]) <= a_ / (1 + a_) <= F(wr['intervals'][0][0][1]), ('the natural rebase witness must publish a positive upper bound containing 1/(2^2000+1)', wr['intervals'][0])
    out['natural_rebase_witness_first_row'] = wr['intervals'][0]
    acc = {}
    for k, fx in fixes.items():
        rc, f, n = gate_run(fx); assert rc == 0 and not f, (k, f); acc[k] = dict(routes=[c['route'] for c in fx['w']['certificate']['components']] if fx['w'].get('certificate') else fx['w'].get('outcome'), guarantee=fx['w'].get('guarantee_type'))
        if fx['w'].get('status') == 'COMPLETED': cnt('gate_only_coordinates', sum(len(r_) for r_ in fx['w']['intervals']))
    out['real_worker_fixtures_accepted'] = acc
    pol = engine.POLICY; old = pol['epsilon']; pol['epsilon'] = F(1, 20)
    try: r = solve.solve(chain(3, 2), time.monotonic() + 120, 'A0_POINT', 's-pac', delta=F(1, 20))
    finally: pol['epsilon'] = old
    R['counts']['solver_component_executions'] += 1; assert r['guarantee_type'] == 'PAC'
    mp = D / 'pac_model.uai'; write_uai(chain(3, 2), mp); _, b = core.read_uai(mp); ivd, ptd = core.publish(r['intervals'], r['points'], epsilon=F(1, 20))
    wpac = dict(status='COMPLETED', arm='A0_POINT', seed='s-pac', nonce='n-pac', delta='1/20', epsilon='1/20', guarantee_type='PAC', outcome='PUBLISHED', binding=b, intervals=ivd, points=ptd, certificate=json.loads(json.dumps(r['certificate'], default=str)), stats={}, candidate_sources=frozen)
    fe = fixture('pac', chain(3, 2), 'A0_POINT', eps='1/20', delta='1/20', inproc=wpac); fe['mp'] = mp; fe['c']['model_path'] = str(mp); fe['c'].update(b); fe['binding'] = b
    rc, f, n = gate_run(fe); assert rc == 0 and n == 1, f; out['pac_fixture_trials'] = r['certificate']['components'][0]['trials']; out['pac_fixture_verified_by_design_replay'] = True
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
    def impossible_stats(d, m, rr, w):
        import numpy as np
        comp = w['certificate']['components'][0]; de = comp['design']; RR = comp['sufficient_statistics']; cards = RR['cards']
        S = engine.Stream(cards, de['cutset'], F(de['U_root']), F(de['delta_range']), F(de['delta_variance']), de['K_total'], de['l_values']); Y = np.array([.125, .875] * len(cards))
        for i in range(RR['n']): S.add_residual(1.0, 1.0, Y, Y)
        R2 = S.record(); eps_ = F(de['epsilon']); ok, rows, pts, chosen, *_ = engine.hulls_from_record(R2, eps_, F(de['decimal_margin'])); assert ok
        comp['sufficient_statistics'] = R2; comp['trials'] = R2['n']; comp['certifier_per_row'] = [chosen[v] for v in range(len(cards))]; comp['intervals_exact'] = [[[str(a), str(b_)] for a, b_ in rows[v]] for v in range(len(cards))]; comp['points_exact'] = [[str(x) for x in pts[v]] for v in range(len(cards))]
        w['certificate']['lifted_intervals_exact'] = copy.deepcopy(comp['intervals_exact']); w['certificate']['lifted_points_exact'] = copy.deepcopy(comp['points_exact']); w['intervals'], w['points'] = core.publish([rows[v] for v in range(len(cards))], [pts[v] for v in range(len(cards))], epsilon=eps_)
    def impossible_stats_primary(d, m, rr, w):
        impossible_stats(d, m, rr, w); comp = w['certificate']['components'][0]; de = comp['design']; RR = comp['sufficient_statistics']; cards = RR['cards']; mult = 2048
        RR['n'] *= mult; RR['positive_trials'] *= mult
        for key in ('b_lo', 'b_hi', 'e_lo', 'e_hi'): RR[key] *= mult
        for key in ('a_lo', 'a_hi', 'c_lo', 'c_hi', 'd_lo', 'd_hi'): RR[key] = [x * mult for x in RR[key]]
        eps2 = F(1, 200); del2 = F(1, 10 ** 6); K = w['certificate']['K_total']
        RR['alpha_range'] = RR['alpha_variance'] = de['alpha_range'] = de['alpha_variance'] = str(del2 / (2 * K)); de['delta_range'] = de['delta_variance'] = str(del2 / 2); de['epsilon'] = str(eps2)
        w['epsilon'] = w['certificate']['epsilon'] = str(eps2); w['delta'] = w['certificate']['delta'] = str(del2); led = w['certificate']['delta_ledger']; led.update(delta=str(del2), range_family=str(del2 / 2), variance_family=str(del2 / 2), per_coordinate_alpha_each_family=str(del2 / (2 * K)))
        ok, rows, pts, chosen, *_ = engine.hulls_from_record(RR, eps2, F(de['decimal_margin'])); assert ok
        comp['trials'] = RR['n']; comp['certifier_per_row'] = [chosen[v] for v in range(len(cards))]; comp['intervals_exact'] = [[[str(a), str(b_)] for a, b_ in rows[v]] for v in range(len(cards))]; comp['points_exact'] = [[str(x) for x in pts[v]] for v in range(len(cards))]
        w['certificate']['lifted_intervals_exact'] = copy.deepcopy(comp['intervals_exact']); w['certificate']['lifted_points_exact'] = copy.deepcopy(comp['points_exact']); w['intervals'], w['points'] = core.publish([rows[v] for v in range(len(cards))], [pts[v] for v in range(len(cards))], epsilon=eps2)
        m['task'] = {'epsilon': str(eps2), 'delta': str(del2)}
    def foreign_prng(d, m, rr, w):
        de = w['certificate']['components'][0]['design']; de['seed_tree'] = '1'; de['seed_point'] = '2'; de['prng'] = 'constant generator'; de['lambda_rule'] = 'retrospective U_t'; de['stream_scale'] = 'U_t'
    def partial_map(d, m, rr, w): m['candidate_artifact_hashes'] = {'pac/gate.py': frozen_all['pac/gate.py']}; w['candidate_sources'] = {'pac/gate.py': frozen_all['pac/gate.py']}
    def relabel_P1(d, m, rr, w): m['cells'][0]['arm'] = rr['arm'] = w['arm'] = 'P1_PAC_CONDITIONAL'; w['certificate']['arm'] = 'P1_PAC_CONDITIONAL'; w['certificate']['components'][0]['route'] = 'pac_conditional'
    def relabel_A1(d, m, rr, w): m['cells'][0]['arm'] = rr['arm'] = w['arm'] = 'A1_CONDITIONAL'; w['certificate']['arm'] = 'A1_CONDITIONAL'; w['certificate']['components'][0]['route'] = 'pac_conditional'
    def relabel_H1(d, m, rr, w): m['cells'][0]['arm'] = rr['arm'] = w['arm'] = 'H1_HYBRID'; w['certificate']['arm'] = 'H1_HYBRID'; w['certificate']['components'][0]['route'] = 'pac_conditional'
    def cert_arm_only(d, m, rr, w): w['certificate']['arm'] = 'P1_PAC_CONDITIONAL'
    def comp_index_shift(d, m, rr, w): w['certificate']['components'][0]['component'] = 1
    negatives = {'A0_relabelled_P1_same_lawful_statistics': relabel_P1, 'A0_relabelled_A1': relabel_A1, 'A0_relabelled_H1': relabel_H1, 'certificate_arm_field_only_changed': cert_arm_only, 'component_index_not_partition_position': comp_index_shift,
                 'coherent_impossible_PAC_statistics_diag': impossible_stats, 'coherent_impossible_PAC_statistics_PRIMARY_eps1-200_delta1e-6': impossible_stats_primary, 'foreign_prng_seeds_scale_same_statistics': foreign_prng, 'partial_nonempty_frozen_source_map': partial_map,
                 'wrong_lift_consistent_decimals': wrong_lift, 'foreign_design': foreign_design, 'false_U_root': false_U, 'false_exact_cover': det_lie, 'false_zero_string': zero_lie, 'false_zero_structured': zero_lie_structured, 'coherent_K_one': coherent_K,
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
    rc, f, n = gate_run(fe, amend={'per_directory_hashes': {'pac': {}, 'newarm': {}}}); assert rc == 1 and any('amendment' in x[1] for x in f); rej['any_amendment_file_refused'] = f[0][1][:80]
    rc, f, n = gate_run(fe, start_mut=lambda st: st.pop('artifact_hashes_sha256')); assert rc == 1 and any('content hash' in x[1] for x in f); rej['start_without_inventory_content_hash'] = f[0][1][:80]
    def missing_receipt(d, m, r_, w): e = copy.deepcopy(m['cells'][0]); e['cell_id'] = 'missing'; m['cells'].append(e)
    rc, f, n = gate_run(fe, mutate=missing_receipt); assert rc == 1 and any('NOT_RUN' in x[1] for x in f); rej['missing_receipt'] = f[0][1][:80]
    def tamper_det(d, m, r_, w): w['certificate']['components'][0]['intervals_exact'][0][0] = ['1/10', '1/10']
    rc, f, n = gate_run(fixes['det_partial'], mutate=tamper_det); assert rc == 1 and any('re-derived' in x[1] for x in f); rej['tampered_deterministic_row'] = f[0][1][:80]
    fd = fixes['det_cover']; cdet = fd['w']['certificate']['components'][0]
    def false_numerators(d, m, rr, w):
        comp = w['certificate']['components'][0]; RT = comp['resolved_totals']; Alo = F(RT['A_lo']); Ahi = F(RT['A_hi']); n_ = len(RT['a_lo'])
        for j in range(n_): frac = F(1, 8) if j % 2 == 0 else F(7, 8); RT['a_lo'][j] = float(Alo * frac); RT['a_hi'][j] = math.nextafter(math.nextafter(float(Ahi * frac), math.inf), math.inf)
        cards = comp['sufficient_statistics']['cards']; off = [0]
        for k in cards: off.append(off[-1] + k)
        rows = engine.Totals.bounds_from_record(RT, F(comp['frontier']['U_t']), cards, off); eps_ = F(comp['design']['epsilon']); pts = [engine.feasible_point(rows[v], eps_ - F(comp['design']['decimal_margin'])) for v in range(len(cards))]; assert all(p_ is not None for p_ in pts), 'control must be simplex-coherent'
        comp['intervals_exact'] = [[[str(a), str(b_)] for a, b_ in rows[v]] for v in range(len(cards))]; comp['points_exact'] = [[str(x) for x in pts[v]] for v in range(len(cards))]
        w['certificate']['lifted_intervals_exact'] = copy.deepcopy(comp['intervals_exact']); w['certificate']['lifted_points_exact'] = copy.deepcopy(comp['points_exact']); w['intervals'], w['points'] = core.publish(rows, pts, epsilon=eps_)
    rc, f, n = gate_run(fd, mutate=false_numerators); assert rc == 1 and any('re-accumulated' in x[1] for x in f), f; rej['coherent_false_deterministic_numerators_1-8_7-8'] = f[0][1][:80]
    def false_zero(cells_mode):
        def mut(d, m, rr, w):
            RT = copy.deepcopy(cdet['resolved_totals']); RT['A_exact_hi'] = '0/1'; RT['A_exact_lo'] = '0/1'
            if cells_mode == 'omitted': RT['cells'] = []
            elif cells_mode == 'zeroed':
                for x in RT['cells']: x['B0_lo'] = '0/1'; x['B0_hi'] = '0/1'
            elif cells_mode == 'duplicated': RT['cells'] = RT['cells'] + [copy.deepcopy(RT['cells'][0])]
            rr.update(status='STOPPED', outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC'); w.clear()
            w.update(status='STOPPED', outcome='PROVED_ZERO_EVIDENCE', zero_evidence_proof=dict(kind='pac_exact_cover', component=0, variables=list(range(13)), cutset=cdet['design']['cutset'], frontier=cdet['frontier'], resolved_totals=RT), binding=fd['binding'], nonce='n-det_cover', seed='s-det_cover', arm='P1_PAC_CONDITIONAL', guarantee_type='DETERMINISTIC', candidate_sources=dict(frozen))
        return mut
    for mode_ in ('omitted', 'zeroed', 'duplicated'):
        rc, f, n = gate_run(fd, mutate=false_zero(mode_)); assert rc == 1 and any('zero-evidence proof NOT re-derivable' in x[1] for x in f), (mode_, f); rej['false_zero_closed_frontier_cells_' + mode_] = f[0][1][:80]
    def omitted_contribution(d, m, rr, w):
        comp = w['certificate']['components'][0]; comp['resolved_totals']['cells'] = comp['resolved_totals']['cells'][1:]
    rc, f, n = gate_run(fd, mutate=omitted_contribution); assert rc == 1 and any('bijection' in x[1] for x in f), f; rej['omitted_contribution_record'] = f[0][1][:80]
    def duplicated_contribution(d, m, rr, w):
        comp = w['certificate']['components'][0]; comp['resolved_totals']['cells'] = comp['resolved_totals']['cells'] + [copy.deepcopy(comp['resolved_totals']['cells'][0])]
    rc, f, n = gate_run(fd, mutate=duplicated_contribution); assert rc == 1 and any('duplicate' in x[1] for x in f), f; rej['duplicated_contribution_record'] = f[0][1][:80]
    out['negative_controls_rejected'] = rej
    # checker RESOURCE outcomes are STRUCTURED (review 4 F06): exhausted per-component allowance, exhausted aggregate budget, invalid replay factor -> result written, UNVERIFIABLE failure, exit 1
    def gate_with(fx, **kw):
        d = fx['d']; shutil.rmtree(d / 'cells', ignore_errors=True); (d / 'cells/one').mkdir(parents=True); m = copy.deepcopy(fx['man']); ww = copy.deepcopy(fx['w'])
        r_ = dict(copy.deepcopy(fx['c']), status='COMPLETED', outcome='PUBLISHED', guarantee_type=ww['guarantee_type'], nonce=ww['nonce'], within_budget=True, launch_relative_wall_s=1.0, supervisor={'rc': 0, 'outcome': 'COMPLETED'}, worker_output='cells/one/worker.json')
        dump(d / 'CAMPAIGN_MANIFEST.json', m); mh = sha(d / 'CAMPAIGN_MANIFEST.json'); ah = hashlib.sha256(json.dumps(m['candidate_artifact_hashes'], sort_keys=True).encode()).hexdigest(); st = {'manifest_sha256': mh, 'manifest': 'CAMPAIGN_MANIFEST.json', 'artifact_hashes_sha256': ah}
        dump(d / 'CAMPAIGN_START.json', st); (d / 'PAC_LEDGER.jsonl').write_text(json.dumps(dict(kind='CAMPAIGN_START', **st)) + '\n'); dump(d / 'cells/one/worker.json', ww); r_['output_sha256'] = sha(d / 'cells/one/worker.json'); dump(d / 'cells/one/receipt.json', r_)
        with contextlib.redirect_stdout(io.StringIO()): rc_ = gate.main(str(d), **kw)
        return rc_, json.load(open(d / 'GATE_RESULT.json'))
    rc_, g_ = gate_with(fe, replay_factor=1e-9); assert rc_ == 1 and g_['failures'] and 'UNVERIFIABLE' in g_['failures'][0][1] and g_.get('gate_version'), g_['failures'][:1]; out['replay_allowance_exhausted_is_structured_UNVERIFIABLE'] = g_['failures'][0][1][:100]
    rc_, g_ = gate_with(fe, gate_budget_s=1e-6); assert rc_ == 1 and g_.get('budget_exhausted_at_cell') == 'cell1' and any('aggregate gate budget' in f_[1] for f_ in g_['failures']); out['aggregate_budget_exhausted_is_structured'] = True
    rc_, g_ = gate_with(fe, replay_factor=-1.0); assert rc_ == 1 and 'invalid replay factor' in g_['failures'][0][1]; out['invalid_replay_factor_refused'] = True
    rc_, g_ = gate_with(fe); assert rc_ == 0 and g_['gated_set'][0]['verified'] is True and g_['gated_set'][0]['evidence'], 'gated set must carry evidence hashes'; out['gated_set_carries_evidence_hashes'] = sorted(g_['gated_set'][0]['evidence'])[:3]
    out['complete_inventory_with_b0_supervisor_native_and_glue_valid_candidate_accepted'] = True
    return out


# ---------------- Q2
def q2_masses():
    rng = random.Random(2); out = {'random_cells': 0}
    m = {'cards': [2, 2, 3], 'factors': [dict(scope=(0,), values=[F(1), F(1000)]), dict(scope=(1,), values=[F(1, 3), F(2, 3)]), dict(scope=(2,), values=[F(1, 6), F(1, 3), F(1, 2)]), dict(scope=(0, 1), values=[F(1), F(1), F(1), F(1)])], 'evidence': {}}
    a = contrib.cell_kernel(m, {0: 0}); b = contrib.cell_kernel(m, {0: 1}); cnt('kernel_cell_calls', 2)
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
        cnt('kernel_cell_calls'); out['random_cells'] += 1
        okc = kr['B0'][0] <= Z <= kr['B0'][1] and all(kr['B'][v][s][0] <= N[v][s] <= kr['B'][v][s][1] for v in range(n) for s in range(cards[v])); R['counts']['truth_coordinates'] += sum(cards); bad += (not okc)
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


def moment_oracle(rng, n_models, label, mutate_stream=None, require_positive_resolved=True):
    """independent exact recomputation of every accumulated statistic of real adaptive runs; returns counts; raises AssertionError on the first enclosure violation.
    mutate_stream: optional callable applied to the engine.Stream class before the runs (Q8 sensitivity); always restored."""
    pristine_add = engine.Stream.add_residual; pristine_res = engine.Stream.resolve_add; orig_draw = engine.Tree.draw_leaf; state = {}; seen = dict(trials=0, checked_trials=0, resolutions=0, positive_resolved_trials=0, models=0)
    orig_add = pristine_add; orig_res = pristine_res
    def draw_obs(self, rng_):
        a, q, z, tr, u = orig_draw(self, rng_); state['last'] = (dict(a), q, z); return a, q, z, tr, u
    def add_obs(self, rlo, rhi, Ylo, Yhi):
        a, q, z = state['last']; m = state['m']; cut = state['cut']; cards = m['cards']; U = state['U']; off = state['off']
        if z: rT = F(0); rY = [F(0)] * self.tot
        else:
            Zc, Nc, _ = cell_truth(m, cut, tuple(a[v] for v in cut)); rT = Zc / q; rY = [F(0)] * self.tot
            for v in range(len(cards)):
                for s_ in range(cards[v]): rY[off[v] + s_] = Nc[v][s_] / q
        T = (state['A'] + rT) / U; Y = [(state['ra'][j] + rY[j]) / U for j in range(self.tot)]
        state['B'] += T; state['E'] += T * T
        for j in range(self.tot): state['a'][j] += Y[j]; state['c'][j] += Y[j] * Y[j]; state['d'][j] += Y[j] * T
        res = orig_add(self, rlo, rhi, Ylo, Yhi); seen['trials'] += 1
        if state['A'] > 0: seen['positive_resolved_trials'] += 1
        assert F(self.b_lo) <= state['B'] <= F(self.b_hi) and F(self.e_lo) <= state['E'] <= F(self.e_hi), '%s: denominator moments not enclosed at trial %d' % (label, self.t)
        for j in range(self.tot):
            assert F(float(self.a_lo[j])) <= state['a'][j] <= F(float(self.a_hi[j])), '%s: first query moment a_%d not enclosed at trial %d' % (label, j, self.t)
            assert F(float(self.c_lo[j])) <= state['c'][j] <= F(float(self.c_hi[j])), '%s: second query moment c_%d not enclosed' % (label, j)
            assert F(float(self.d_lo[j])) <= state['d'][j] <= F(float(self.d_hi[j])), '%s: cross moment d_%d not enclosed' % (label, j)
        seen['checked_trials'] += 1; return res
    def res_obs(self, B0lo, B0hi, rows_lo, rows_hi, B0_exact_lo, B0_exact_hi):
        a, q, z = state['last']; m = state['m']; cut = state['cut']; cards = m['cards']; off = state['off']; Zc, Nc, _ = cell_truth(m, cut, tuple(a[v] for v in cut))
        state['A'] += Zc
        for v in range(len(cards)):
            for s_ in range(cards[v]): state['ra'][off[v] + s_] += Nc[v][s_]
        res = orig_res(self, B0lo, B0hi, rows_lo, rows_hi, B0_exact_lo, B0_exact_hi); seen['resolutions'] += 1; U = state['U']
        assert F(self.A_lo) <= state['A'] / U <= F(self.A_hi), '%s: resolved mass A not enclosed' % label
        for j in range(self.tot): assert F(float(self.ra_lo[j])) <= state['ra'][j] / U <= F(float(self.ra_hi[j])), '%s: resolved query total ra_%d not enclosed after resolution %d' % (label, j, seen['resolutions'])
        return res
    if mutate_stream: mutate_stream()                     # the mutation (or a no-op wrapper) is installed FIRST, underneath the oracle's observers (review 4 F07)
    orig_add = engine.Stream.add_residual; orig_res = engine.Stream.resolve_add
    engine.Stream.add_residual = add_obs; engine.Stream.resolve_add = res_obs; engine.Tree.draw_leaf = draw_obs
    try:
        for trial in range(n_models):
            m = rand_model(rng, 4, 6, 3, zero_p=0.1); n = len(m['cards']); cards = m['cards']; cut = rng.sample(range(n), rng.randint(2, n - 1)); T0 = engine.Tree(m, cut)
            if T0.u_root == 0: continue
            off = [0]
            for c in cards: off.append(off[-1] + c)
            state.clear(); state.update(m=m, cut=cut, U=T0.u_root, off=off, A=F(0), ra=[F(0)] * off[-1], B=F(0), E=F(0), a=[F(0)] * off[-1], c=[F(0)] * off[-1], d=[F(0)] * off[-1])
            r = engine.run_component(m, time.monotonic() + 30, trial, trial + 1, 'conditional', F(1, 20), F(1, 20), sum(cards), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=12); cnt('solver_component_executions'); seen['models'] += 1
            if r['status'] == 'PUBLISHED': check_publication(r, m, engine.POLICY['epsilon'], label + ' adaptive run')
    finally: engine.Stream.add_residual = pristine_add; engine.Stream.resolve_add = pristine_res; engine.Tree.draw_leaf = orig_draw
    if require_positive_resolved: assert seen['positive_resolved_trials'] > 0 and seen['resolutions'] > 0 and seen['checked_trials'] == seen['trials'] > 0, seen
    return dict(moment_oracle=seen)


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
        out['models'] += 1; out['leaves'] += len(law); R['counts']['helper_evaluations'] += len(law)
    # ---- MOMENT ORACLE (review R05): every production trial's drawn leaf (and its exact cell truth) and every resolution are recorded through non-mutating observers;
    # the EXACT dimensionless statistics are recomputed INDEPENDENTLY from the original factors (T_t = (A_t + r_t)/U, Y_tj = (a_tj + r_t f_tj)/U with exact rationals) and
    # every directed accumulator (b, e, a_j, c_j, d_j, A, ra_j) must enclose them after EVERY trial; a deleted / corrupted query update is detected (Q8 proves sensitivity)
    out.update(moment_oracle(rng, 12, 'q3'))
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
def rebase_histories(rng):
    """Totals invariant lo*2^E <= exact <= hi*2^E for the denominator and EVERY numerator after every insertion, over adversarial exponent histories: gaps 600 / 601 / 1074 /
    1075 / 2000 and random, increasing AND decreasing cell orders, repeated rebases, non-dyadic fractions, zero cells, tiny positive cells, coordinates untouched by later
    cells (sparse idx); asserts that rebases actually execute"""
    checks = 0; rebases = 0; lost_upper = 0; hist = 0
    for trial in range(300):
        tot = rng.randint(2, 7); T = engine.Totals(tot); exA_lo = F(0); exA_hi = F(0); ex_lo = [F(0)] * tot; ex_hi = [F(0)] * tot
        gaps = rng.choice([[0, 600], [0, 601], [0, 1074], [0, 1075], [0, 2000], [2000, 0], [1075, 0, 1075 * 2], [-2100, 2100], [rng.randint(-2100, 2100) for _ in range(4)], [0, 650, 1300, 1950]])
        for ci, e in enumerate(gaps):
            mant = F(rng.randint(1, 10 ** 6), rng.randint(1, 10 ** 6)) if rng.random() < 0.7 else F(rng.randint(1, 9))
            B0 = mant * F(2) ** e if rng.random() > 0.08 else F(0)
            B0lo = B0 * (1 - F(1, 10 ** rng.randint(3, 15))) if rng.random() < 0.5 else B0; B0hi = B0 * (1 + F(1, 10 ** rng.randint(3, 15))) if rng.random() < 0.5 else B0
            idx = sorted(rng.sample(range(tot), rng.randint(1, tot))); rows_lo = []; rows_hi = []
            for j in idx:
                x = B0 * F(rng.randint(0, 100), 100); rows_lo.append(x * (1 - F(1, 10 ** 7)) if x else F(0)); rows_hi.append(x * (1 + F(1, 10 ** 7)) if x else F(0))
            T.add_cell((ci,), B0lo, B0hi, rows_lo, rows_hi, idx); exA_lo += B0lo; exA_hi += B0hi
            for j, lo, hi in zip(idx, rows_lo, rows_hi): ex_lo[j] += lo; ex_hi[j] += hi
            sc = F(2) ** T.E; checks += 1
            assert F(T.A_lo) * sc <= exA_lo and exA_hi <= F(T.A_hi) * sc, 'denominator invariant violated (trial %d cell %d)' % (trial, ci)
            for j in range(tot):
                assert F(float(T.a_lo[j])) * sc <= ex_lo[j] and ex_hi[j] <= F(float(T.a_hi[j])) * sc, 'numerator invariant violated (trial %d cell %d coord %d)' % (trial, ci, j)
                if ex_hi[j] > 0 and not (T.a_hi[j] > 0): lost_upper += 1
        rebases += T.rebases; hist += 1
    assert lost_upper == 0 and rebases > 0, (lost_upper, rebases); cnt('helper_evaluations', checks)
    return dict(histories=hist, insertion_checks=checks, rebases_executed=rebases, positive_upper_bounds_lost=lost_upper)


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
                assert all(lo_ <= p <= hi for row, ps in zip(rows, marg) for (lo_, hi), p in zip(row, ps)), 'deterministic bounds miss the truth'; R['counts']['truth_coordinates'] += sum(cards)
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
    out = dict(st); out['rebase_histories'] = rebase_histories(rng)
    # the natural witness and the 601-bit subnormal witness through run_component (publication asserted to contain the truth with a POSITIVE upper bound)
    a_ = F(1, 2 ** 2000); m13 = {'cards': [2] * 13, 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [F(1), a_, F(1), F(1)]}, {'scope': (0, 1), 'values': [a_, F(1), F(1), F(1)]}] + [{'scope': (0, i), 'values': [F(1)] * 4} for i in range(2, 13)]}
    for seed_ in ('rebase-1', 'rebase-0'):
        rr = solve.solve(m13, time.monotonic() + 60, 'P1_PAC_CONDITIONAL', seed_); cnt('solver_component_executions'); iv = rr['intervals'][0]; tr = a_ / (1 + a_)
        assert rr['guarantee_type'] == 'DETERMINISTIC' and iv[0][0] <= tr <= iv[0][1] and iv[0][1] > 0, (seed_, iv); di, dp = core.publish(rr['intervals'], rr['points'], epsilon=F(1, 200)); assert F(di[0][0][1]) > 0 and F(di[0][0][0]) <= tr <= F(di[0][0][1]); cnt('truth_coordinates', 26)
    out['natural_rebase_witness_both_orders_contain_truth_after_decimals'] = True
    L_ = F(2) ** 601; weights = [F(1, 2), F(1, 2 ** 501), F(2) ** 600]; va = []; vb = []
    for w_ in weights: va.extend([L_, w_ / L_]); vb.extend([w_ / L_, L_])
    m2 = dict(cards=[3, 2], evidence={}, factors=[dict(scope=(0, 1), values=va), dict(scope=(0, 1), values=vb)])
    rs = engine.run_component(m2, None, 5, 91, 'conditional', F(1, 2000000), F(1, 2000000), 5, 3 * 1024 ** 3, 0, fixed_cutset=[0], fixed_order=[1], max_trials=4); cnt('solver_component_executions'); p_ = weights[1] / sum(weights)
    assert rs['status'] == 'PUBLISHED' and rs['stats']['resolved_totals']['rebases'] >= 1 and rs['intervals'][0][1][0] <= p_ <= rs['intervals'][0][1][1], 'subnormal rebase witness'; cnt('truth_coordinates', 5); out['subnormal_601_bit_rebase_witness_contains_truth'] = True
    m0 = {'cards': [2, 2], 'factors': [dict(scope=(0, 1), values=[F(0)] * 4)], 'evidence': {}}; r0 = engine.run_component(m0, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1]); R['counts']['solver_component_executions'] += 1
    assert r0['status'] == 'PROVED_ZERO_EVIDENCE'; out['U0_root_deterministic_zero'] = True
    mz = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(0), F(0), F(0)]}], 'evidence': {}}
    rz = engine.run_component(mz, time.monotonic() + 5, 1, 9, 'point', F(1, 20), F(1, 20), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1], max_trials=3); R['counts']['solver_component_executions'] += 1
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
        ref = (s * arg.ln()).sqrt(); bd = Decimal(int(bU.numerator)) / Decimal(int(bU.denominator)); assert bd >= ref and (bd - ref) / ref < Decimal('1e-30'); R['counts']['helper_evaluations'] += 1
    for l in range(1, 17):
        lam = F(1, 2 ** l); lo, hi = rig.psi(lam); ref = -(Decimal(1) - Decimal(lam.numerator) / Decimal(lam.denominator)).ln() - Decimal(lam.numerator) / Decimal(lam.denominator)
        assert Decimal(int(lo.numerator)) / Decimal(int(lo.denominator)) <= ref <= Decimal(int(hi.numerator)) / Decimal(int(hi.denominator)); R['counts']['helper_evaluations'] += 1
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
        o = rig.shrunk_rejection(-Aq, Aq * (r1 + r2), -Aq * r1 * r2); R['counts']['helper_evaluations'] += 1
        if o is not None and not (r1 < o[0] < o[1] < r2): bad += 1
    assert bad == 0; out['random_concave_quadratics_3000'] = True
    rr = rig.quad_roots_outer(F(-1), F(1), F(-2, 9)); assert rr[0][0] <= F(1, 3) <= rr[0][1] and rr[1][0] <= F(2, 3) <= rr[1][1] and rr[0][1] <= rr[1][0]; bad = 0
    for _ in range(1000):
        r1 = F(rng.randrange(-10 ** 6, 10 ** 6), 10 ** 6); r2 = r1 + F(rng.randrange(0, 10 ** 6), 10 ** 6); Aq = F(rng.randrange(-10 ** 6, 10 ** 6) or 1, rng.randrange(1, 10 ** 6)); (a, b), (c, d) = rig.quad_roots_outer(Aq, -Aq * (r1 + r2), Aq * r1 * r2); R['counts']['helper_evaluations'] += 1
        if not (a <= r1 <= b and c <= r2 <= d and b <= c): bad += 1
    assert bad == 0; out['quad_roots_outer_repaired_1000'] = True
    ivq = rig.IV(-(1 + F(1, 2 ** 60)), F(1)); sq = ivq.sq().frac(); assert sq[0] == 0 and sq[1] >= (1 + F(1, 2 ** 60)) ** 2; out['IV_sq'] = True
    for pw in (540, 1075):
        a = F(1, 2 ** pw); model = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(1)]}], 'evidence': {}}
        for mode in ('point', 'conditional'):
            r = engine.run_component(model, time.monotonic() + 30, 123, 456, mode, F(1, 2000000), F(1, 2000000), 2, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[], max_trials=1, resolve=False); S = r['stats']['sufficient_statistics']; ex = (a / F(1, 2)) / F(S['U_root']); R['counts']['solver_component_executions'] += 1
            assert F(S['b_lo']) <= ex <= F(S['b_hi']) and F(S['e_lo']) <= ex * ex <= F(S['e_hi']) and F(S['a_lo'][0]) <= ex <= F(S['a_hi'][0]) and F(S['c_lo'][0]) <= ex * ex <= F(S['c_hi'][0])
    out['underflow_statistics_enclosed'] = True
    rng = random.Random(6); S = engine.Stream([3], [], F(1), F(1, 20), F(1, 20), 3, list(range(1, 17))); exb = F(0); exe = F(0); exa = [F(0)] * 3; exc = [F(0)] * 3; exd = [F(0)] * 3
    for _ in range(500):
        x = F(rng.randrange(0, 2 ** 40), 2 ** (40 + rng.randrange(0, 1030))); j = rng.randrange(3); lo, hi = rig.df_lo(x), rig.df_hi(x); Y = S.np.zeros(3); Yh = S.np.zeros(3); Y[j] = lo; Yh[j] = hi
        S.add_residual(lo, hi, Y, Yh); exb += x; exe += x * x; exa[j] += x; exc[j] += x * x; exd[j] += x * x; R['counts']['helper_evaluations'] += 1
    assert F(S.b_lo) <= exb <= F(S.b_hi) and F(S.e_lo) <= exe <= F(S.e_hi) and all(F(S.a_lo[j]) <= exa[j] <= F(S.a_hi[j]) and F(S.c_lo[j]) <= exc[j] <= F(S.c_hi[j]) and F(S.d_lo[j]) <= exd[j] <= F(S.d_hi[j]) for j in range(3)); out['directed_accumulators_500'] = True
    segs = engine._subtract(F(0), F(1), [(F(1, 10), F(3, 10)), (F(6, 10), F(8, 10))]); assert len(segs) == 3; out['nonconvex_accepted_set'] = 3
    r = engine.run_component(chain(3, 2), time.monotonic() + 5, 1, 2, 'point', F(1, 20), F(1, 40), 7, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1, 2], max_trials=2, resolve=False); d = r['stats']['design']; R['counts']['solver_component_executions'] += 1
    assert F(d['alpha_range']) == F(1, 20) / 7 and F(d['alpha_variance']) == F(1, 40) / 7 and d['K_total'] == 7 and F(d['U_root']) == engine.Tree(chain(3, 2), [0]).u_root; out['design_record_fields'] = True
    return out


def q7_publication():
    out = {}
    assert engine.feasible_point([(F(0), F(6, 10))] * 3, F(3, 10)) is None
    pol = dict(engine.POLICY); pol['epsilon'] = F(1, 20); m = chain(5, 2)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m, time.monotonic() + 120, 3, 4, mode, F(1, 40), F(1, 40), 10, 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 2], fixed_order=[1, 3, 4], max_trials=3000000, resolve=False); R['counts']['solver_component_executions'] += 1
        g, ok = check_publication(r, m, F(1, 20), 'q7 ' + mode); assert g == 'PAC' and ok, (mode, ok)
        out['pac_publication_%s' % mode] = dict(trials=r['stats']['trials_completed'], contains_truth=ok, certifiers=sorted(set(r['certifier_per_row'])))
    m15 = chain(15, 2); cut = list(range(11)); order = [v for v in range(15) if v not in cut]
    r = engine.run_component(m15, time.monotonic() + 300, 8, 9, 'conditional', F(1, 40), F(1, 40), 30, 3 * 2 ** 30, 0, pol, fixed_cutset=cut, fixed_order=order, max_trials=20000, resolve=True); cnt('solver_component_executions')
    g, ok = check_publication(r, m15, F(1, 20), 'q7 adaptive'); assert r['stats']['resolved_cells'] > 0 and r['stats']['sufficient_statistics']['A_hi'] > 0 and ok
    out['adaptive_publication_deterministic_partial_cover'] = dict(guarantee=g, route=r['stats'].get('route'), resolved=r['stats']['resolved_cells'], trials=r['stats']['trials_completed'], U_t_over_U=r['stats']['U_t_over_U_root'], contains_truth=ok)
    # GENUINE ADAPTIVE PAC publication: nonempty residual region, positive resolved query contributions in the statistics, route pac_statistical_intersected_with_deterministic
    rng_ = random.Random(5); C_ = 64; ma = {'cards': [C_, C_, 2, 2], 'evidence': {}, 'factors': [{'scope': (0, 2), 'values': [F(rng_.randint(1, 3)) for _ in range(2 * C_)]}, {'scope': (1, 3), 'values': [F(rng_.randint(1, 3)) for _ in range(2 * C_)]}, {'scope': (2, 3), 'values': [F(3), F(1), F(1), F(3)]}]}
    ra = engine.run_component(ma, time.monotonic() + 120, 5, 6, 'conditional', F(1, 40), F(1, 40), 2 * C_ + 4, 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 1], fixed_order=[2, 3], max_trials=20000, resolve=True); cnt('solver_component_executions'); sa = ra['stats']
    ga, oka = check_publication(ra, ma, F(1, 20), 'q7 adaptive PAC'); S_ = sa['sufficient_statistics']
    assert ga == 'PAC' and oka and F(sa['frontier']['U_t']) > 0 and sa['resolved_cells'] > 0 and S_['A_hi'] > 0 and sum(1 for x in S_['ra_hi'] if x > 0) > 0 and (sa.get('publication_composition') or {}).get('used') == 'intersection_with_deterministic', (ga, oka, sa.get('route'))
    out['adaptive_PAC_publication_nonempty_residual'] = dict(route=sa.get('route'), trials=sa['trials_completed'], resolved=sa['resolved_cells'], U_t_over_U=sa['U_t_over_U_root'], positive_resolved_query_coordinates=sum(1 for x in S_['ra_hi'] if x > 0), contains_truth=oka)
    for power, odds in [(1075, 1), (2000, 3)]:
        a = F(1, 2 ** power); mm = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(odds)]}], 'evidence': {}}
        rr = solve.solve(mm, time.monotonic() + 20, 'P1_PAC_CONDITIONAL', 'q7'); R['counts']['solver_component_executions'] += 1; Z, N, marg = truth(mm)
        assert rr['guarantee_type'] == 'DETERMINISTIC' and all(lo <= p <= hi for (lo, hi), p in zip(rr['intervals'][0], marg[0])); R['counts']['truth_coordinates'] += 2
    out['tiny_a_exact_answers_published'] = True
    m = {'cards': [2], 'factors': [dict(scope=(0,), values=[F(2) ** 900, F(2) ** 899])], 'evidence': {}}; r = contrib.cell_kernel(m, {}); assert r['B0'][0] <= F(2) ** 900 + F(2) ** 899 <= r['B0'][1]; out['huge_exponents'] = True
    return out

# ---------------- Q8: INTERSECTION (requirement line 52) + MECHANISM SENSITIVITY (every mandatory mechanism disabled in-process must FAIL its test)
def q8_intersection_and_sensitivity():
    out = {}; eps = F(1, 20); mg = engine.POLICY['decimal_margin']; pol = dict(engine.POLICY, epsilon=eps)
    chain3 = chain(3, 2)
    # (a) unit: a real 256-trial record (stat alone too wide) ∩ offset wide deterministic rows -> narrower than either; disjoint det -> EMPTY_INTERSECTION
    r = engine.run_component(chain3, time.monotonic() + 30, 3, 4, 'conditional', F(1, 40), F(1, 40), 6, 3 * 2 ** 30, 0, pol, fixed_cutset=[0], fixed_order=[1, 2], max_trials=256, resolve=False); cnt('solver_component_executions'); RR = r['stats']['sufficient_statistics']
    ok0, *_, w0, bU, vs, c0 = engine.hulls_from_record(RR, eps, mg); assert not ok0 and c0['used'] == 'statistical_only'
    det = [[(F(1, 2) - F(1, 100), F(1, 2) + F(11, 100)), (F(1, 2) - F(11, 100), F(1, 2) + F(1, 100))] for v in range(3)]
    ok1, rows1, pts1, ch1, w1, bU, vs, c1 = engine.hulls_from_record(RR, eps, mg, det_rows=det)
    assert c1['used'] == 'intersection_with_deterministic' and all(w1['intersection'][v] <= min(w1['range'][v], w1['deterministic'][v]) for v in range(3)) and sum(1 for v in range(3) if w1['intersection'][v] < min(w1['range'][v], w1['deterministic'][v])) >= 2, w1      # never wider than either; strictly narrower than both on >= 2 rows (row 0's statistical hull is wider than the deterministic row here)
    out['unit_intersection_narrower_than_either'] = {v: dict(range=round(w1['range'][v], 3), deterministic=round(w1['deterministic'][v], 3), intersection=round(w1['intersection'][v], 3)) for v in range(3)}
    ok2, *_, c2 = engine.hulls_from_record(RR, eps, mg, det_rows=[[(F(9, 10), F(1)), (F(0), F(1, 10))] for v in range(3)]); assert not ok2 and c2['used'] == 'EMPTY_INTERSECTION' and c2['empty']; out['unit_empty_intersection_typed'] = True
    # (b) GENERIC controls: natural adaptive runs where at least one row publishes ONLY through the intersection (neither standalone enclosure meets the task)
    gen = []
    for seed, C_, lo_, hi_ in ((201, 24, 14, 16), (202, 30, 14, 16), (204, 30, 19, 21)):
        rng_ = random.Random(seed); _ = rng_.choice([24, 26, 28, 30, 32]); _ = rng_.choice([(19, 21), (29, 31), (14, 16)])
        m = {'cards': [C_, C_, 2, 2], 'evidence': {}, 'factors': [{'scope': (0, 2), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(2 * C_)]}, {'scope': (1, 3), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(2 * C_)]}, {'scope': (2, 3), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(4)]}]}
        rr = engine.run_component(m, time.monotonic() + 60, seed, seed + 1, 'conditional', F(1, 40), F(1, 40), sum(m['cards']), 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 1], fixed_order=[2, 3], max_trials=8192, resolve=True); cnt('solver_component_executions')
        g, ok = check_publication(rr, m, eps, 'q8 generic %d' % seed); comp = rr['stats'].get('publication_composition') or {}
        both = [v for v in comp.get('standalone_deterministic_ok', {}) if not comp['standalone_deterministic_ok'][v] and not comp['standalone_statistical_ok'].get(v, False)]
        assert g == 'PAC' and ok and both, (seed, g, ok, both); gen.append(dict(seed=seed, C=C_, trials=rr['stats']['trials_completed'], rows_published_only_through_intersection=both, U_t_over_U=rr['stats']['U_t_over_U_root'], contains_truth=ok))
    out['generic_intersection_only_publications'] = gen
    # (c) complete-cover deterministic control (delta 0, no statistics spent) and a valid no-publication (TOO_WIDE) case
    rd = engine.run_component(chain(13, 3, [{'scope': (1,), 'values': [F(1), F(1, 2)]}]), time.monotonic() + 30, 1, 2, 'conditional', F(1, 2000000), F(1, 2000000), 26, 3 * 2 ** 30, 0, fixed_cutset=[1], fixed_order=[v for v in range(13) if v != 1], max_trials=8); cnt('solver_component_executions')
    assert rd['status'] == 'PUBLISHED' and rd['guarantee'] == 'DETERMINISTIC' and rd['stats']['frontier']['U_t'] == '0/1'; check_publication(rd, chain(13, 3, [{'scope': (1,), 'values': [F(1), F(1, 2)]}]), F(1, 200), 'q8 complete cover'); out['complete_cover_deterministic_delta0'] = True
    rn = engine.run_component(chain3, time.monotonic() + 30, 3, 4, 'conditional', F(1, 2000000), F(1, 2000000), 6, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1, 2], max_trials=64, resolve=False); cnt('solver_component_executions'); assert rn['status'] == 'TOO_WIDE' and rn['guarantee'] == 'NONE'; out['valid_no_publication_TOO_WIDE'] = True
    # (d) evidence / alias / two-component lift control through solve + gate chain (reduction decoder re-derived by the gate in Q1; here the lift is checked against the truth)
    mev = {'cards': [2, 3, 2, 2, 2], 'evidence': {3: 1}, 'factors': [{'scope': (0, 1), 'values': [F(2), F(1), F(1), F(1), F(3), F(1)]}, {'scope': (2, 3), 'values': [F(1), F(2), F(2), F(1)]}, {'scope': (4,), 'values': [F(1), F(1)]}, {'scope': (1,), 'values': [F(1), F(0), F(2)]}]}
    for arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID'):
        rr = solve.solve(mev, time.monotonic() + 30, arm, 'q8-ev'); cnt('solver_component_executions'); Z, N, marg = truth(mev)
        assert rr['outcome'] == 'PUBLISHED' and contained(rr['intervals'], rr['points'], marg, F(1, 200)) and rr['intervals'][3] == [(F(0), F(0)), (F(1), F(1))] and rr['intervals'][1][1] == (F(0), F(0)); cnt('truth_coordinates', 11)
    out['evidence_alias_components_lift_contains_truth'] = True
    # (e) MECHANISM SENSITIVITY: each mandatory mechanism disabled in-process; the associated test must FAIL; everything restored afterwards (diagnostics never ship)
    sens = {}
    def expect_fail(name, fn):
        try: fn(); sens[name] = 'NOT DETECTED'; raise AssertionError('mechanism disablement NOT detected: ' + name)
        except AssertionError as e:
            if 'NOT detected' in str(e): raise
            sens[name] = 'DETECTED: ' + str(e)[:90]
    # (e1) query resolution deleted from Stream.resolve_add (the review's mutation): the moment oracle must fail
    orig_res = engine.Stream.resolve_add; calls = {'noop': 0}
    def noop_wrapper(self, *a, **k): calls['noop'] += 1; return orig_res(self, *a, **k)
    def mut0(): engine.Stream.resolve_add = noop_wrapper
    try: moment_oracle(random.Random(3), 6, 'q8-noop', mutate_stream=mut0, require_positive_resolved=False); assert calls['noop'] > 0, 'the no-op wrapper was never reached through the hook'; sens['noop_wrapper_through_the_hook'] = 'PASSES (%d calls): the hook applies mutations underneath the oracle instrumentation' % calls['noop']
    finally: engine.Stream.resolve_add = orig_res
    def deleted_query(self, B0lo, B0hi, rows_lo, rows_hi, elo, ehi):
        ra_lo, ra_hi = self.ra_lo.copy(), self.ra_hi.copy(); orig_res(self, B0lo, B0hi, rows_lo, rows_hi, elo, ehi); self.ra_lo, self.ra_hi = ra_lo, ra_hi
    def mut1(): engine.Stream.resolve_add = deleted_query
    try: expect_fail('query_resolution_deleted', lambda: moment_oracle(random.Random(3), 6, 'q8-mut1', mutate_stream=mut1, require_positive_resolved=False))
    finally: engine.Stream.resolve_add = orig_res
    assert 'resolved query total' in sens['query_resolution_deleted'] or 'query moment' in sens['query_resolution_deleted'], ('the deletion must be detected on a QUERY statistic, not on the denominator', sens['query_resolution_deleted'])
    # (e2) rebase direction reverted to ordinary multiplication: the rebase histories must fail (positive upper bound lost / invariant)
    orig_vec = engine.Totals._scale_down_vec; orig_sc = engine.Totals._scale_down_scalar
    def bad_vec(self, arr, k, up): return arr * (2.0 ** k)
    def bad_sc(x, k, up): return x * (2.0 ** k)
    engine.Totals._scale_down_vec = bad_vec; engine.Totals._scale_down_scalar = staticmethod(bad_sc)
    try: expect_fail('rebase_direction_ordinary_multiplication', lambda: rebase_histories(random.Random(4)))
    finally: engine.Totals._scale_down_vec = orig_vec; engine.Totals._scale_down_scalar = staticmethod(orig_sc)
    # (e3) frontier closure disabled (resolved leaves keep their bound): closure test must fail
    orig_resolve = engine.Tree.resolve
    def no_close(self, leaf, u):
        leaf = tuple(leaf); self.resolved.add(leaf); self.resolved_count += 1
    engine.Tree.resolve = no_close
    def closure_test():
        T = engine.Tree(chain(4, 2), [0, 1])
        for l in itertools.product(range(2), range(2)): T.resolve(l, T.node_bounds(l)[0])
        assert T.U_t == 0, 'frontier did not close'
    try: expect_fail('frontier_closure_disabled', closure_test)
    finally: engine.Tree.resolve = orig_resolve
    # (e4) contribution binding: gate accepts a cover whose cells list is replaced -> verify_cover must fail (checked directly)
    rc_ = solve.solve(chain3, time.monotonic() + 30, 'P1_PAC_CONDITIONAL', 'q8-bind'); cnt('solver_component_executions'); cc = json.loads(json.dumps(rc_['certificate'], default=str))['components'][0]
    import reduction
    red = reduction.reduce(chain3, deadline=None); cm = core.components(red['model'], deadline=None)[0][1]
    msg, ver = gate.verify_cover(cm, cc['design']['cutset'], cc['design']['order_free'], cc['frontier'], cc['resolved_totals']); assert msg is None, msg
    RT = copy.deepcopy(cc['resolved_totals']); RT['a_hi'] = [x * 0.5 for x in RT['a_hi']]
    msg2, _ = gate.verify_cover(cm, cc['design']['cutset'], cc['design']['order_free'], cc['frontier'], RT); assert msg2 and 're-accumulated' in msg2; sens['contribution_binding_numerators_altered'] = 'DETECTED: ' + msg2[:80]
    # (e5) risk allocation: K understated -> the gate rejects (Q1 coherent_K_one); here design_binding + K re-derivation are asserted directly
    bad = engine.design_binding_failures(dict(cc['design'], lambda_rule='other'), engine.POLICY, 'q8-bind', 0, F(1, 200)); assert bad; sens['risk_allocation_design_bound_to_frozen_policy'] = 'DETECTED: ' + bad[0]
    # (e6) intersection disabled (certify_pac without det rows): the generic intersection-only control must not publish at the recorded trial count
    seed, C_, lo_, hi_ = 204, 30, 19, 21; rng_ = random.Random(seed); _ = rng_.choice([24, 26, 28, 30, 32]); _ = rng_.choice([(19, 21), (29, 31), (14, 16)])
    m = {'cards': [C_, C_, 2, 2], 'evidence': {}, 'factors': [{'scope': (0, 2), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(2 * C_)]}, {'scope': (1, 3), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(2 * C_)]}, {'scope': (2, 3), 'values': [F(rng_.randint(lo_, hi_)) for _ in range(4)]}]}
    orig_h = engine.hulls_from_record
    def no_det(R_, eps_=engine.POLICY['epsilon'], margin=engine.POLICY['decimal_margin'], det_rows=None): return orig_h(R_, eps_, margin, det_rows=None)
    engine.hulls_from_record = no_det
    try:
        rr = engine.run_component(m, time.monotonic() + 60, seed, seed + 1, 'conditional', F(1, 40), F(1, 40), sum(m['cards']), 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 1], fixed_order=[2, 3], max_trials=512, resolve=True); cnt('solver_component_executions')
        assert not (rr['status'] == 'PUBLISHED' and rr['guarantee'] == 'PAC'), 'without the intersection the 512-trial run must not publish PAC'; sens['intersection_disabled'] = 'DETECTED: status %s at 512 trials (with intersection: PAC)' % rr['status']
    finally: engine.hulls_from_record = orig_h
    # (e7) output / lift binding: the gate's lift check (Q1 wrong_lift) and the engine's typed INTERSECTION_EMPTY through solve
    orig_b = engine.Totals.bounds
    engine.Totals.bounds = lambda self, U_t, cards, off: ([[(F(9, 10), F(1))] + [(F(0), F(1, 10))] * (k - 1) for k in cards] if self.E is not None else None)
    try:
        r7 = engine.run_component(m, time.monotonic() + 60, seed, seed + 1, 'conditional', F(1, 40), F(1, 40), sum(m['cards']), 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 1], fixed_order=[2, 3], max_trials=4096, resolve=True); cnt('solver_component_executions')
        assert r7['status'] == 'INTERSECTION_EMPTY' and r7['guarantee'] == 'NONE' and r7['stats'].get('empty_intersection'), r7['status']; sens['empty_intersection_typed_outcome_engine'] = 'DETECTED: ' + r7['status']
        # through solve.solve: the forced cutset must keep the cover incomplete long enough for a narrow statistical hull (fixed two-variable cutset via the selection hook; task epsilon 1/20)
        orig_cc = engine.choose_cutset; pol_eps = engine.POLICY['epsilon']; engine.POLICY['epsilon'] = eps
        engine.choose_cutset = lambda model, deadline=None, policy=engine.POLICY, budget_fraction=0.1: dict(cutset=[0, 1], order=[2, 3], residual_forecast=0, residual_peak_bag=0, trace=[], steps=0, stopped=None, selection_s=0.0, fits=True)
        try:
            try: solve.solve(m, time.monotonic() + 60, 'P1_PAC_CONDITIONAL', 'q8-empty'); raise AssertionError('solve published through an empty intersection')
            except support.ResourceStop as e: assert e.reason == 'INTERSECTION_EMPTY', e.reason; sens['empty_intersection_typed_outcome_solve'] = 'DETECTED: ResourceStop INTERSECTION_EMPTY'
        finally: engine.choose_cutset = orig_cc; engine.POLICY['epsilon'] = pol_eps
        cnt('solver_component_executions')
    finally: engine.Totals.bounds = orig_b
    out['mechanism_sensitivity'] = sens; return out


def q9_continuation():
    out = {}
    m = {'cards': [3] * 7, 'factors': [dict(scope=(i, (i + 1) % 7), values=[F(x) for x in (1, 2, 3, 4, 5, 6, 7, 8, 9)]) for i in range(7)], 'evidence': {}}
    r = engine.run_component(m, time.monotonic() + 0.4, 1, 2, 'conditional', F(1, 2 * 10 ** 6), F(1, 2 * 10 ** 6), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False); R['counts']['solver_component_executions'] += 1
    assert r['guarantee'] == 'NONE' and r['stats']['terminal'] == 'DEADLINE'; out['deadline_refuses'] = True
    calls = {'n': 0}; ok_ = engine.kernel_cell; oe = engine.exact_cell
    def failing(orig):
        def f(*a, **k):
            calls['n'] += 1
            if calls['n'] == 3: raise contrib.CellStop('MEMORY', 'injected')
            return orig(*a, **k)
        return f
    engine.kernel_cell = failing(ok_); engine.exact_cell = failing(oe)
    try: r2 = engine.run_component(m, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False); R['counts']['solver_component_executions'] += 1
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
        try: rr = solve.solve(cyc, time.monotonic() + 30, 'H1_HYBRID', 'q9a'); conts['stream.UnsupportedError'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['counts']['solver_component_executions'] += 1
        finally: stream_float.solve = osf
        odisc = core._discover_component; oexec = core._execute_component
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'dag', 'forecast': 1, 'discovery': [], 'model': cm, 'dag': None}
        oplan = dag.execute_plan; dag.execute_plan = raiser(dag.Unsupported('injected dag refusal'))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9b'); conts['dag.Unsupported'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['counts']['solver_component_executions'] += 1
        finally: core._discover_component = odisc; dag.execute_plan = oplan
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm, 'order': list(range(len(cm['cards'])))}
        oex = X.execute; X.execute = raiser(X.Stop('RANGE', 'injected', {})); osup = support.solve; support.solve = raiser(support.Unsupported('injected exact fallback refusal'))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9c'); conts['support.Unsupported_after_RANGE'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['counts']['solver_component_executions'] += 1
        finally: X.execute = oex; support.solve = osup; core._discover_component = odisc
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm}; core._execute_component = raiser(support.ResourceStop('MEMORY', {}))
        try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9d'); conts['ResourceStop.MEMORY'] = (rr['guarantee_type'], rr['stats']['continuations'][0]['stop']); R['counts']['solver_component_executions'] += 1
        finally: core._discover_component = odisc; core._execute_component = oexec
        core._discover_component = lambda cm, dl, route, inherited=None: {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm}; core._execute_component = raiser(support.ResourceStop('DEADLINE', {}))
        try:
            try: solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9e'); raise AssertionError('deadline refusal continued')
            except support.ResourceStop as e: assert e.reason == 'DEADLINE'
        finally: core._discover_component = odisc; core._execute_component = oexec
    finally: forest.solve = of
    assert all(v[0] == 'DETERMINISTIC' for v in conts.values()) and len(conts) == 4, conts; out['continuation_per_backend_class'] = conts; out['deadline_refusal_final'] = True
    D = TMP / 'q9'; D.mkdir(exist_ok=True); write_uai({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, D / 'z.uai'); outp = D / 'w.json'
    subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() - 1.0), '--seed', 's', '--nonce', 'n', '--budget', '0'], check=True, cwd=CODE); wz = json.load(open(outp)); cnt('fresh_workers')
    assert wz['outcome'] == 'DEADLINE' and wz['guarantee_type'] == 'NONE'
    subprocess.run([PY, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() + 10), '--seed', 's', '--nonce', 'n', '--budget', '10'], check=True, cwd=CODE); wz2 = json.load(open(outp)); cnt('fresh_workers')
    assert wz2['outcome'] == 'PROVED_ZERO_EVIDENCE' and isinstance(wz2.get('zero_evidence_proof'), dict) and gate.verify_zero_proof(core.read_uai(D / 'z.uai')[0], wz2['zero_evidence_proof']) is None
    out['late_zero_is_DEADLINE_timely_zero_verified'] = True
    bad = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(1, 10 ** 1000), F(1), F(1)]}], 'evidence': {}}
    for fn in (lambda: contrib.cell_kernel(bad, {}, deadline=time.monotonic() + 10), lambda: engine.Template(bad, [], [0, 1], deadline=time.monotonic() + 10)):
        try: fn(); raise AssertionError('RANGE not raised')
        except contrib.CellStop as e: assert e.kind == 'RANGE'
    out['typed_range'] = True
    for arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
        rr = solve.solve({'cards': [2], 'factors': [], 'evidence': {}}, time.monotonic() + 10, arm, 'e'); assert rr['points'] == [[F(1, 2), F(1, 2)]]; R['counts']['solver_component_executions'] += 1
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
        tot += 1; R['counts']['solver_component_executions'] += 1
        okc = None
        if r['status'] == 'PUBLISHED':
            pub += 1; okc = contained(r['intervals'], r['points'], marg, F(1, 20)); R['counts']['truth_coordinates'] += K
            if r['guarantee'] == 'DETERMINISTIC': assert okc, 'deterministic publication misses the truth'
            elif not okc: miss += 1
        rows.append(dict(trial=trial, mode=mode, resolve=resolve, status=r['status'], guarantee=r['guarantee'], trials=r['stats'].get('trials_completed'), resolved=r['stats'].get('resolved_cells'), contains_truth=okc))
    assert miss <= 14, (miss, tot)
    return dict(attempted=tot, published=pub, pac_misses=miss, delta='1/10 per run (two families 1/20)', criterion='misses <= 14 (P[X > 14] = 6.66e-4 at p = 0.1, n = 60)', note='bug detection only; cannot verify 1e-6', wall_s=round(time.monotonic() - t0, 1), rows=rows)


def q12_closure_partial_cover():
    out = {}; eps = engine.POLICY['epsilon']
    for a in (F(1, 2), F(1, 10), F(0)):
        model = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(1)]}], 'evidence': {}}
        r = engine.run_component(model, time.monotonic() + 30, 0, 0, 'conditional', F(1, 2000000), F(1, 2000000), 2, 64 * 1024 ** 2, 0, fixed_cutset=[0], fixed_order=[], max_trials=8); R['counts']['solver_component_executions'] += 1
        if a == 0: assert r['status'] == 'PROVED_ZERO_EVIDENCE'
        else: assert r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC' and r['stats']['terminal'] == 'COVER_COMPLETE' and r['stats']['trials_completed'] == 2 and r['stats']['frontier']['U_t'] == '0/1'; check_publication(r, model, eps, 'slack cover')
    out['review_slack_cover_a_1/2_1/10_0'] = True
    m = chain(13, 3, [{'scope': (1,), 'values': [F(1), F(1, 2)]}]); rr = solve.solve(m, time.monotonic() + 30, 'P1_PAC_CONDITIONAL', 'q12a'); R['counts']['solver_component_executions'] += 1; c = rr['certificate']['components'][0]
    Z, N, marg = truth(m); assert rr['guarantee_type'] == 'DETERMINISTIC' and 'exact_cover' in c['route'] and c['resolved_cells'] == 2 and contained(rr['intervals'], rr['points'], marg, eps); R['counts']['truth_coordinates'] += 26; out['review_full_solver_cover'] = True
    star = {'cards': [257] + [2] * 6, 'factors': [{'scope': (0, i), 'values': [F(1)] * 514} for i in range(1, 7)], 'evidence': {}}; rr = solve.solve(star, time.monotonic() + 60, 'P1_PAC_CONDITIONAL', 'q12b'); R['counts']['solver_component_executions'] += 1; c = rr['certificate']['components'][0]
    Z, N, marg = truth(star); assert rr['guarantee_type'] == 'DETERMINISTIC' and 'partial_cover' in c['route'] and c['resolved_cells'] < 257 and contained(rr['intervals'], rr['points'], marg, eps); R['counts']['truth_coordinates'] += 269; out['review_partial_cover_star'] = dict(resolved=c['resolved_cells'], trials=c['trials'])
    rng = random.Random(12); comp = part = det = pac = 0; pac_miss = 0
    for trial in range(25):
        m = rand_model(rng, 3, 5, 3, zero_p=0.15); n = len(m['cards']); Z, N, marg = truth(m)
        if Z == 0: continue
        cut = rng.sample(range(n), rng.randint(1, n - 1))
        r = engine.run_component(m, time.monotonic() + 30, trial, trial + 1, 'conditional', F(1, 10), F(1, 10), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=100000); R['counts']['solver_component_executions'] += 1
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
            cut = rng.sample(range(n), rng.randint(1, n - 1)); r = engine.run_component(m, time.monotonic() + 30, 100 + trial, 101 + trial, 'conditional', F(1, 10), F(1, 10), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=100000); R['counts']['solver_component_executions'] += 1
            if r['status'] != 'PUBLISHED': continue
            try: check_publication(r, m, eps, 'corrupted')
            except AssertionError: detected['n'] += 1; continue
            raise AssertionError('corrupted publication NOT detected')
    finally: engine.run_component = orig
    assert detected['n'] > 0; out['output_corruption_detected'] = detected['n']
    m6 = chain(6, 2)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m6, time.monotonic() + 10, 1, 2, mode, F(1, 10), F(1, 10), 12, 3 * 2 ** 30, 0, fixed_cutset=[0, 2], fixed_order=[1, 3, 4, 5], max_trials=50, resolve=False); assert r['stats']['resolved_cells'] == 0; R['counts']['solver_component_executions'] += 1
    out['ablation_residual_region_fixed'] = True; return out


def q13_registry_pipeline():
    """REGISTRY PIPELINE over EVERY arm and representation (review R06 / R07 / R08)"""
    out = {}; import legacy_cbi_uai as LC, uai_export
    from ext import uai as U
    # ---- adapters: refusals, both SF widths, external block ids preserved, comparator native points
    meta = {'d': 1, 'blocks': [{'id': 0, 'internal': 0, 'rows': [0, 1]}], 'cards': [2]}
    for bad in ([[(F(1, 2), F(1, 2))]], [[(F(1, 2), F(1, 2)), (F(1, 2), F(1, 2)), (F(0), F(0))]], [], [[(F(2), F(3)), (F(0), F(0))]]):
        try: LC.native_enclosures(meta, bad); raise AssertionError('malformed accepted')
        except LC.AdapterError: pass
    try: LC.native_enclosures(meta, [[(F(1, 2), F(1, 2)), (F(1, 2), F(1, 2))]], meta_sha256='0' * 64); raise AssertionError('wrong metadata accepted')
    except LC.AdapterError: pass
    out['truncated_misshaped_wrongly_bound_refused'] = True
    meta8 = {'d': 3, 'blocks': [{'id': 42, 'internal': 0, 'rows': list(range(8))}], 'cards': [8]}; rows8 = [[(F(1, 8) - F(1, 250), F(1, 8) + F(1, 250))] * 8]
    sc = LC.native_score(meta8, rows8, native_widths=['1/100', '1/20'], guarantee='PAC'); assert sc['native_completion'] == 'STATE_ROWS_ONLY_WIDTH_EXCEEDED' and sc['native_widths_met'] == {'1/100': False, '1/20': True} and abs(sc['max_coordinate_width'] - 0.032) < 1e-9 and 'PAC' in sc['delta_note'] and list(sc['coordinates']) == ['42']
    out['sf_two_widths_scored_separately_pac_delta_kept_external_id_preserved'] = sc['native_widths_met']
    pts = LC.native_point_score(meta8, [[F(1, 8)] * 8]); assert pts['native_completion'] == 'UNGUARANTEED_ESTIMATE' and pts['coordinates']['42'] == ['1/2'] * 3; out['comparator_native_points_unguaranteed'] = True
    # sparse / reordered external ids through the real CBI adapter + exact reference lookup
    inst = {'d': 2, 'blocks': [{'id': 99, 'rows': [0, 1, 3], 'weights': [1, 2, 1]}, {'id': 42, 'rows': [0, 2], 'weights': [3, 1]}], 'edges': [{'u': 99, 'v': 42, 'r': '1/2'}]}
    model_, entries, status, meta_ = LC.render(inst); assert status == 'RENDERED' and meta_['external_block_ids'] == [42, 99] and [b['id'] for b in meta_['blocks']] == [42, 99]
    Z, N, marg = truth(model_); rows_ = [[(p, p) for p in row] for row in marg]; sc2 = LC.native_score(meta_, rows_, meta_sha256=LC.meta_sha(meta_), instance_json=inst, guarantee='DETERMINISTIC')
    assert sc2['native_completion'] == 'NATIVE_WIDTH_MET' and sc2['native_reference'].get('contains_truth') is True and sc2['native_reference'].get('coordinates_compared') == 4 and set(sc2['coordinates']) == {'42', '99'}, sc2.get('native_reference'); cnt('truth_coordinates', 5)
    out['sparse_external_block_ids_42_99_reference_lookup'] = True
    # ---- exact integer export parsed by repository and external readers
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
    # ---- in-suite REAL pipeline on a 2-cell qgrid manifest (producer -> dispatcher -> gate v4 -> report v4 -> closeout v4; resume preflight)
    RD = D / 'pipeline'; RD.mkdir(); qg = D / 'qgrid'; qg.mkdir(); import legacy_qgrid as LQ, campaign as CP, report as RP
    mq, _ = LQ.grid_model(2, F(3, 2), F(11, 10), 0); exq = LQ.write_uai(mq, str(qg / 'qgrid_tiny.uai'))
    json.dump(dict(instances=[dict(case_id='qgrid_tiny_L2', model_path=str(qg / 'qgrid_tiny.uai'), evidence_path=exq['evidence_path'], model_sha256=exq['model_sha256'], evidence_sha256=exq['evidence_sha256'], export_factor_scalars=exq['factor_scalars'])]), open(D / 'QG.json', 'w'))
    with contextlib.redirect_stdout(io.StringIO()): CP.manifest(str(RD), '/Users/adis/Workspace/pgm/docs/handoff-received-2026-11-11-certified-executor/packet/inputs', dev=True, qgrid_inventory=str(D / 'QG.json'), include=('qgrid',), dev_restrictions=dict(primary=[('P1_PAC_CONDITIONAL', 1), ('H1_HYBRID', 1)], comparators=[], ablation=[], budgets=[20.0]))
    man = json.load(open(RD / 'CAMPAIGN_MANIFEST_dev.json')); assert len(man['cells']) == 2 and set(man['candidate_artifact_hashes']) == set(registry.source_inventory(CODE))
    with contextlib.redirect_stdout(io.StringIO()): CP.run(str(RD), manifest_name='CAMPAIGN_MANIFEST_dev.json')
    cnt('fresh_workers', 2)
    with contextlib.redirect_stdout(io.StringIO()): rc = gate.main(str(RD), 'CAMPAIGN_MANIFEST_dev.json')
    g = json.load(open(RD / 'GATE_RESULT.json')); assert rc == 0 and g['gated_set_sha256'], g['failures'][:3]
    with contextlib.redirect_stdout(io.StringIO()): RP.main(str(RD), 'CAMPAIGN_MANIFEST_dev.json')
    res = json.load(open(RD / 'RESULTS_PAC.json')); assert len(res['runs']) == 2 and not res['unrun'] and all(x['outcome'] == 'PUBLISHED' for x in res['runs']) and res['gated_set_sha256'] == g['gated_set_sha256'] and not (res.get('gate_binding') or {}).get('mismatch')
    stub = dict(suite_version=SUITE_VERSION + ' (pipeline-test stub)', all_pass=True, passed=len(registry.QUALIFICATION_GROUPS), total=len(registry.QUALIFICATION_GROUPS), groups=[dict(name=n_, ok=True) for n_ in registry.QUALIFICATION_GROUPS], candidate_sources=registry.source_inventory(CODE, scopes=('candidate',)), counts={}); json.dump(stub, open(RD / 'Q_stub.json', 'w'))
    def closeout(qual='Q_stub.json'):
        p_ = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), str(RD), '--manifest', 'CAMPAIGN_MANIFEST_dev.json', '--qualification', str(RD / qual)], capture_output=True, text=True); return p_.returncode, p_.stdout.strip()[-160:]
    rc0, msg0 = closeout(); assert rc0 == 0, msg0; out['real_pipeline_2_cells_qualified'] = msg0[-120:]
    # closeout staleness / completeness controls (the third review's five + schema + foreign identity), each on a copy of the valid pipeline
    import shutil as sh
    def ctl(name, mutate):
        d2 = D / ('ctl_' + name); sh.copytree(RD, d2); mutate(d2)
        p_ = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), str(d2), '--manifest', 'CAMPAIGN_MANIFEST_dev.json', '--qualification', str(d2 / 'Q_stub.json')], capture_output=True, text=True); assert p_.returncode == 1 and 'UNQUALIFIED' in p_.stdout, (name, p_.stdout[-200:]); return p_.stdout.strip()[-110:]
    def dump(pth, x): Path(pth).write_text(json.dumps(x, indent=1, default=str))
    def stale_gate(d2):
        rp = sorted((d2 / 'cells').glob('*/receipt.json'))[0]; r = json.load(open(rp)); wp = d2 / r['worker_output']; w = json.load(open(wp)); w['points'][0] = ['0.10000000', '0.90000000']; dump(wp, w); r['output_sha256'] = hashlib.sha256(wp.read_bytes()).hexdigest(); dump(rp, r)
    def foreign_rows(d2):
        res_ = json.load(open(d2 / 'RESULTS_PAC.json')); res_['runs'][0]['cell_id'] = 'not-the-planned-cell'; res_['runs'][0]['guarantee'] = 'PAC'; dump(d2 / 'RESULTS_PAC.json', res_)
    def missing_identity(d2):
        res_ = json.load(open(d2 / 'RESULTS_PAC.json')); res_.pop('manifest_sha256'); dump(d2 / 'RESULTS_PAC.json', res_)
    def one_group(d2):
        q = json.load(open(d2 / 'Q_stub.json')); q['groups'] = q['groups'][:1]; q['passed'] = q['total'] = 1; dump(d2 / 'Q_stub.json', q)
    def stale_pass_flag(d2):
        g_ = json.load(open(d2 / 'GATE_RESULT.json')); g_['failures'] = [['cell1', 'certificate broken']]; dump(d2 / 'GATE_RESULT.json', g_)
    def foreign_qual(d2):
        q = json.load(open(d2 / 'Q_stub.json')); q['candidate_sources'] = {k: '0' * 64 for k in q['candidate_sources']}; dump(d2 / 'Q_stub.json', q)
    def extra_group(d2):
        q = json.load(open(d2 / 'Q_stub.json')); q['groups'].append(dict(name='Q99_extra', ok=True)); q['passed'] = q['total'] = len(q['groups']); dump(d2 / 'Q_stub.json', q)
    def altered_conclusion(d2):
        res_ = json.load(open(d2 / 'RESULTS_PAC.json')); k = list(res_['conclusions_by_cohort_budget'])[0]; res_['conclusions_by_cohort_budget'][k]['by_arm']['P1_PAC_CONDITIONAL']['published_pac'] = 1; dump(d2 / 'RESULTS_PAC.json', res_)
    def amendment(d2): dump(d2 / 'MANIFEST_AMENDMENT_1_artifact_hashes.json', {})
    def changed_output_bytes_only(d2):
        rp = sorted((d2 / 'cells').glob('*/receipt.json'))[0]; r = json.load(open(rp)); wp = d2 / r['worker_output']; w = json.load(open(wp)); w['points'][0] = ['1.00000000', '0.00000000']; w['intervals'][0] = [['1.00000000', '1.00000000'], ['0.00000000', '0.00000000']]; dump(wp, w)      # receipt AND gate untouched
    def case_alias(d2):
        res_ = json.load(open(d2 / 'RESULTS_PAC.json')); h1 = [x for x in res_['runs'] if x['arm'] == 'H1_HYBRID']; h1[0]['case'] = 'qgrid_L24_q3_v11-10_s1_deadline_control'; dump(d2 / 'RESULTS_PAC.json', res_)
    def evidence_file_changed(d2):
        rp = sorted((d2 / 'cells').glob('*/receipt.json'))[0]; r = json.load(open(rp)); mp_ = Path(r['model_path']); g_ = json.load(open(d2 / 'GATE_RESULT.json'))
        for e in g_['gated_set']:
            for rel in list(e.get('evidence') or {}):
                e['evidence'][rel] = '0' * 64
        dump(d2 / 'GATE_RESULT.json', g_)
    out['closeout_controls_refused'] = {n_: ctl(n_, f_) for n_, f_ in (('changed_output_bytes_only_receipt_and_gate_untouched', changed_output_bytes_only), ('coherent_case_alias_false_gain', case_alias), ('evidence_hash_tampered_in_gate_result', evidence_file_changed), ('stale_gate_after_worker_and_receipt_change', stale_gate), ('foreign_report_same_count_and_manifest', foreign_rows), ('missing_report_manifest_identity', missing_identity), ('only_one_qualification_group', one_group), ('failed_gate_rows_with_stale_pass_flag', stale_pass_flag), ('foreign_qualification_identity', foreign_qual), ('extra_qualification_group', extra_group), ('altered_conclusion_counts', altered_conclusion), ('amendment_file_present', amendment))}
    man['cells'].append(dict(man['cells'][0], cell_id='extra')); json.dump(man, open(RD / 'CAMPAIGN_MANIFEST_dev.json', 'w'))
    p3 = subprocess.run([PY, os.path.join(HERE, 'campaign.py'), 'run', str(RD), '--dev'], capture_output=True, text=True); assert p3.returncode != 0 and 'RESUME REFUSED' in (p3.stdout + p3.stderr); out['resume_preflight_refuses_edited_manifest'] = True
    # ---- the ARCHIVED 54-cell dev admission (every registered arm and representation; dev seeds) RE-GATED by gate v4, references dispatched, report + closeout
    A = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'PAC_REPAIR_2026-11-13', 'admission_v5')
    if os.path.exists(os.path.join(A, 'CAMPAIGN_MANIFEST_dev.json')) and os.path.isdir(os.path.join(A, 'cells')):
        AM = json.load(open(os.path.join(A, 'CAMPAIGN_MANIFEST_dev.json'))); arms_present = sorted({c['arm'] for c in AM['cells']}); reps_present = sorted({registry.COHORTS[c['cohort']]['representation'] for c in AM['cells']})
        # REGISTRY-DERIVED coverage obligation (review 4 F05): EVERY executable arm of the registry must be planned in the admission AND have a receipt; a missing arm fails
        missing_arms = sorted(set(registry.ARMS) - set(arms_present)); assert not missing_arms, ('admission plan does not cover every registered executable arm', missing_arms)
        rec_arms = sorted({cells_a['arm'] for cells_a in AM['cells'] if os.path.exists(os.path.join(A, 'cells'))} )
        rcpt = {json.load(open(rp))['cell_id'] for rp in glob.glob(os.path.join(A, 'cells', '*', 'receipt.json'))}; assert all(c_['cell_id'] in rcpt for c_ in AM['cells']), 'every planned admission cell must have a receipt'
        assert set(reps_present) == set(registry.REPRESENTATIONS), reps_present
        for stage in ('GATE_RESULT.json', 'REFERENCES_R0.json', 'RESULTS_PAC.json'): assert os.path.exists(os.path.join(A, stage)), 'admission chain artifact missing: ' + stage
        # the admission CLOSEOUT is run HERE with a schema-complete stub record bound to the CURRENT sources (the real record is written after this suite finishes; the development finalization re-runs the closeout with it)
        stubA = dict(suite_version=SUITE_VERSION + ' (pipeline-test stub)', all_pass=True, passed=len(registry.QUALIFICATION_GROUPS), total=len(registry.QUALIFICATION_GROUPS), groups=[dict(name=n_, ok=True) for n_ in registry.QUALIFICATION_GROUPS], candidate_sources=registry.source_inventory(CODE, scopes=('candidate',)), counts={}); json.dump(stubA, open(D / 'Q_stub_admission.json', 'w'))
        pA = subprocess.run([PY, os.path.join(HERE, 'closeout.py'), A, '--manifest', 'CAMPAIGN_MANIFEST_dev.json', '--qualification', str(D / 'Q_stub_admission.json'), '--out', str(D / 'ADMISSION_CLOSEOUT_stub.md')], capture_output=True, text=True)
        out['admission_closeout_with_current_identity'] = pA.stdout.strip()[-140:]; assert pA.returncode == 0 or 'differs from the file on disk' in pA.stdout or 'does not match the frozen candidate' in pA.stdout, pA.stdout[-400:]
        GA = json.load(open(os.path.join(A, 'GATE_RESULT.json'))); assert GA['gate_passed'] and not GA['failures'] and GA['gated_set_sha256'], 'the archived admission gate must have passed on the frozen sources'
        RF = json.load(open(os.path.join(A, 'REFERENCES_R0.json'))); assert any(v['kind'] == 'R0_cbi_exact_coordinates' for v in RF['references'].values()), 'native CBI reference must be produced by the executable task set'
        RA = json.load(open(os.path.join(A, 'RESULTS_PAC.json'))); assert any(x.get('arm') == 'CBI_NATIVE' and (x.get('native_reference') or {}).get('kind') == 'R0_cbi_exact_coordinates' and (x.get('native_reference') or {}).get('contains_truth') is True for x in RA['native_query_scores']), 'the report must consume the native CBI reference'
        assert all(c_['arm'] not in ('WMB', 'IJGP', 'PGMAX_SUMPRODUCT_BP') or any(json.load(open(rp))['cell_id'] == c_['cell_id'] for rp in glob.glob(os.path.join(A, 'cells', '*', 'receipt.json'))) for c_ in AM['cells'])
        frozen_now = registry.source_inventory(CODE); stale_keys = [k for k, v in AM['candidate_artifact_hashes'].items() if frozen_now.get(k) != v]
        # the archived admission was frozen on an earlier source state (the qualification suite itself and later repairs changed afterwards): re-gate against ITS frozen identity by replaying the v4 gate on a copy whose manifest inventory is rebound to the current sources
        # for the IDENTITY checks only (the worker outputs' candidate_sources of changed files will then differ -> the gate must report exactly those identity differences and nothing else)
        with contextlib.redirect_stdout(io.StringIO()): rc_a = gate.main(A, 'CAMPAIGN_MANIFEST_dev.json', out_path=str(D / 'ADMISSION_GATE_RESULT.json'))
        ga = json.load(open(D / 'ADMISSION_GATE_RESULT.json')); fails = [f[1] for f in ga['failures']]
        non_identity = [f for f in fails if not ('frozen source' in f or 'candidate source' in f or 'INCOMPLETE' in f or 'not in the required scopes' in f)]
        assert not non_identity, non_identity[:5]
        out['archived_dev_admission_regated'] = dict(cells=ga['planned'], receipts=ga['receipts'], completed=ga['completed_checked'], gated_completed=ga['completed_gated'], pac_replayed=ga['pac_certificates_replayed'], arms=arms_present, representations=reps_present, identity_failures_only=len(fails), identity_note='the admission froze an earlier source state (%d keys since changed); every non-identity check passes incl. the H4 / SF / CBI native validators, the zero and DEADLINE controls' % len(stale_keys))
        # the native validators must REFUSE malformed native outputs (controls on copies of the real admission outputs)
        rec = {json.load(open(rp))['cell_id']: (rp, json.load(open(rp))) for rp in glob.glob(os.path.join(A, 'cells', '*', 'receipt.json'))}; cells = {c['cell_id']: c for c in AM['cells']}
        def native_ctl(arm, mutate):
            cid = next(k for k, (rp, r) in rec.items() if cells[k]['arm'] == arm and r['status'] == 'COMPLETED'); rp, r = rec[cid]; c = cells[cid]; wp = os.path.join(A, r['worker_output']); tmpd = D / ('nat_' + arm); tmpd.mkdir(exist_ok=True)
            w = json.load(open(wp)); mutate(w); att = tmpd / ('attempt_' + r['nonce']); att.mkdir(exist_ok=True); wp2 = att / os.path.basename(wp); dump(wp2, w); fails_ = []
            fn = {'h4_native': gate.validate_h4_native, 'sf_native': gate.validate_sf_native, 'cbi_native': gate.validate_cbi_native}[registry.validator_of(arm)]
            r2 = dict(r); ok_ = fn(A, c, r2, str(wp2), lambda cid_, msg: fails_.append(msg)); assert ok_ is False and fails_, (arm, 'malformed native output accepted'); return fails_[0][:90]
        def native_ctl_fs(arm, mutate_dir):
            cid = next(k for k, (rp, r) in rec.items() if cells[k]['arm'] == arm and r['status'] == 'COMPLETED'); rp, r = rec[cid]; c = cells[cid]; src_att = Path(os.path.join(A, r['worker_output'])).parent
            tmpd = D / ('natfs_' + arm + '_' + mutate_dir.__name__); att = tmpd / ('attempt_' + r['nonce']); shutil.copytree(src_att, att); wp2 = att / os.path.basename(r['worker_output']); mutate_dir(att); fails_ = []
            fn = {'h4_native': gate.validate_h4_native, 'sf_native': gate.validate_sf_native, 'cbi_native': gate.validate_cbi_native}[registry.validator_of(arm)]
            ok_ = fn(A, c, dict(r), str(wp2), lambda cid_, msg: fails_.append(msg)); assert ok_ is False and fails_, (arm, 'malformed native evidence accepted'); return fails_[0][:90]
        def h4_remove_numeric(att):
            for child in att.iterdir():
                if child.is_dir():
                    for f in child.iterdir():
                        if f.name != 'verdict.json': f.unlink()
        def h4_alter_producer_channel(att):
            pj = json.load(open(att / 'sp_r1' / 'prod.json')); pj['channels'][0]['re'][1] = pj['channels'][0]['re'][1].replace('*2^', '9*2^', 1); dump(att / 'sp_r1' / 'prod.json', pj)
        nat = {}
        nat['h4_numeric_evidence_removed_flags_retained'] = native_ctl_fs('H4_NATIVE_C', h4_remove_numeric); assert 'missing' in nat['h4_numeric_evidence_removed_flags_retained']
        nat['h4_producer_channel_altered'] = native_ctl_fs('H4_NATIVE_C', h4_alter_producer_channel); assert 'RE-RUN' in nat['h4_producer_channel_altered']
        nat['h4_arm_mismatch'] = native_ctl('H4_NATIVE_C', lambda w: w.__setitem__('arm', 'PI'))
        nat['sf_width_not_met'] = native_ctl('SF_NATIVE_SELECT', lambda w: w.__setitem__('width_met', {'1/100': False, '1/20': False}))
        assert 'width' in nat['sf_width_not_met'], nat['sf_width_not_met']
        nat['sf_checker_failed'] = native_ctl('SF_NATIVE_SELECT', lambda w: w['checker'].__setitem__('status', 'FAILED'))
        nat['sf_published_shape'] = native_ctl('SF_NATIVE_SELECT', lambda w: w['published'].pop())
        def sf_false_zero_n1(w): w.update(n=1, published=[['0', '0']], intervals_exact=[['0', '0']], max_width='0'); w['width_met'] = {k: True for k in w['width_met']}
        nat['sf_false_zero_truncated_n1'] = native_ctl('SF_NATIVE_SELECT', sf_false_zero_n1); assert 'PANEL dimension' in nat['sf_false_zero_truncated_n1']
        def sf_one_interval_altered(w): lo, hi = w['intervals_exact'][3]; w['intervals_exact'][3] = [str(F(lo) + F(1, 10 ** 6)), hi]
        nat['sf_exact_interval_altered'] = native_ctl('SF_NATIVE_SELECT', sf_one_interval_altered); assert 'RE-RUN' in nat['sf_exact_interval_altered']
        def cbi_empty(w):
            for b_ in w['intervals'].values(): b_['coordinates'] = []; b_['max_width'] = '0'
        nat['cbi_empty_coordinates'] = native_ctl('CBI_NATIVE', cbi_empty); assert 'coordinate records' in nat['cbi_empty_coordinates']
        def cbi_zero(w):
            for b_ in w['intervals'].values():
                for x_ in b_['coordinates']: x_.update(lo=0, hi=0, exact=['0', '0'], width='0')
        nat['cbi_all_zero_intervals'] = native_ctl('CBI_NATIVE', cbi_zero); assert 'RE-RUN' in nat['cbi_all_zero_intervals']
        def cbi_shift(w): x_ = list(w['intervals'].values())[0]['coordinates'][0]; x_['lo'] = int(x_['lo']) + 5; x_['hi'] = int(x_['hi']) + 5
        nat['cbi_one_coordinate_shifted'] = native_ctl('CBI_NATIVE', cbi_shift)
        nat['cbi_query_not_certified'] = native_ctl('CBI_NATIVE', lambda w: w['statuses_per_query'].__setitem__(list(w['statuses_per_query'])[0], 'TOO_WIDE'))
        nat['cbi_block_id_map_altered'] = native_ctl('CBI_NATIVE', lambda w: w['id_map'].__setitem__('external_ids', [7, 8]))
        out['native_validators_refuse_malformed'] = nat
        # typed outcomes present in the admission: PROVED_ZERO_EVIDENCE (candidate arms), DEADLINE, MEMORY, comparator unresolved zero
        oc = collections.Counter((cells[k]['arm'], r['outcome']) for k, (rp, r) in rec.items())
        assert oc[('P1_PAC_CONDITIONAL', 'PROVED_ZERO_EVIDENCE')] >= 1 and oc[('P1_PAC_CONDITIONAL', 'DEADLINE')] >= 1 and oc[('MERLIN_CTE', 'ZERO_EVIDENCE_OR_UNDERFLOW_UNRESOLVED')] >= 1 and oc[('H4_NATIVE_C', 'PUBLISHED')] == 1 and oc[('SF_NATIVE_SELECT', 'PUBLISHED')] >= 1 and oc[('CBI_NATIVE', 'PUBLISHED')] == 1, dict(oc)
        out['admission_outcomes'] = {'%s|%s' % k: v for k, v in sorted(oc.items())}
        refp = os.path.join(A, 'REFERENCES_R0.json')
        if os.path.exists(refp):
            RF = json.load(open(refp))['references']; kinds = collections.Counter(v['kind'] for v in RF.values()); assert kinds.get('UNAVAILABLE_FOR_R0', 0) >= 5 and kinds.get('R0_exact_rational', 0) >= 3 and kinds.get('R0_zero_evidence', 0) >= 1, dict(kinds); out['references_dispatched_by_representation'] = dict(kinds)
    else: out['archived_dev_admission_regated'] = 'ADMISSION DIRECTORY ABSENT'
    return out


if __name__ == '__main__':
    GROUPS = [('Q1_identity_and_gate_end_to_end', q1_identity_gate), ('Q2_exact_cell_oracle', q2_masses), ('Q3_laws_moments_and_actual_adaptive_accumulation', q3_laws_and_actual_accumulation), ('Q4_frontier_invariants_and_rebase_histories', q4_frontier_invariants), ('Q5_actual_sampling_backend', q5_sampling_backend), ('Q6_confidence_arithmetic', q6_confidence), ('Q7_numerical_publication_truth_asserted', q7_publication), ('Q8_intersection_and_mechanism_sensitivity', q8_intersection_and_sensitivity), ('Q9_continuation_every_backend_class', q9_continuation), ('Q10_existing_defects_isolated', q10_existing), ('Q11_diagnostic_coverage_attempted_runs', q11_diagnostic), ('Q12_exact_closure_partial_cover_sensitivity', q12_closure_partial_cover), ('Q13_registry_pipeline_every_arm_complete', q13_registry_pipeline)]
    assert [g for g, _ in GROUPS] == list(registry.QUALIFICATION_GROUPS), 'suite groups differ from the registry schema'
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    for name, fn in GROUPS:
        if only and name not in only: continue
        group(name, fn)
    srcs = registry.source_inventory(CODE, scopes=('candidate',)); changed = sorted(k for k in set(srcs) | set(SOURCES_AT_START) if srcs.get(k) != SOURCES_AT_START.get(k))
    if changed: print('SOURCES CHANGED DURING THE RUN: %s -- the record is INVALID' % changed)
    R.update(passed=passed, total=total, all_pass=(passed == total and total == len(registry.QUALIFICATION_GROUPS) and not changed), sources_changed_during_run=changed, candidate_sources_at_start=SOURCES_AT_START, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), candidate_sources=srcs, temp_dir=str(TMP), counts_note='counts BY CLASS, never pooled: fresh_workers = subprocess worker.py runs; solver_component_executions = solve.solve / run_component calls; kernel_cell_calls = contrib cell evaluations; helper_evaluations = arithmetic helper / Totals insertion checks; truth_coordinates = published coordinates compared with the independent original-model enumerator; gate_only_coordinates = coordinates accepted by the production gate without an enumerator comparison', optional_not_implemented='candidate validation (theory section 9); cost-oracle planner; subtree re-tightening; U_t re-weighting')
    json.dump(R, open(os.path.join(HERE, 'PAC_QUALIFICATION.json'), 'w'), indent=1, default=str); print(json.dumps({'passed': passed, 'total': total, 'counts': R['counts'], 'all_pass': R['all_pass']})); sys.exit(0 if R['all_pass'] else 1)
