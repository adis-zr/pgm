"""PRODUCTION QUALIFICATION of the PAC candidate v2 (handoff 03 §3, obligations Q1-Q11; repaired after the adversarial review of 13 Nov 2026). Counted groups are
reported separately from executions and coordinates; a group FAILS if any assertion inside it fails. Exact rational oracles throughout (itertools enumeration; never
the routines under test except where stated). Writes PAC_QUALIFICATION.json beside this file; exit nonzero unless every group passes. NOTHING outside this directory
is rewritten (the frozen executor's own suite runs in an isolated temporary copy; review F10 / Q10).
Q1  identity + GATE: the receipt/certificate gate is INVOKED on an isolated valid fixture produced by the real worker and must reject every mutation of an
    authoritative field (source map, certificate, epsilon/delta, timeliness, START binding, duplicate cells, changed input, fabricated answer, late zero, absent
    output, tampered statistics / design / exact rows / decimals), and accept the valid fixture -- the review's nine negative controls plus certificate tampering.
Q2  exact tiny-model oracle for cell masses and contributions (incl. the review's evidence-contradiction cell and the public-API deadline boundary).
Q3  FIXED-tree law algebra (relabelled: fixed laws, exhaustive): E[T] = Z, E[Y_j] = N_j for point and integrated modes; negative identity controls; PLUS actual
    production `draw_leaf` exercised: the empirical draw frequencies of the real sampler agree with the exact law (chi-square diagnostic) and the resolved-region
    law (effective weights after resolution) is enumerated against the exact residual masses (adaptive history control).
Q4  support and envelopes: child-sum monotonicity; U = 0 root proof; no-positive-sample refusal on a POSITIVE model (the review's control); the PRODUCTION envelope
    guard rejects a corrupted tree (injected invalid pointwise envelope through a test double of Tree, the production check raises).
Q5  actual sampling law: the production `random.Random` backend is exercised (not a double): draw frequencies vs exact law; the conditional algebra of the
    child-selection map is kept as a separate (labelled) algebra check.
Q6  confidence arithmetic: boundary / psi / threshold enclosures vs 60-digit decimals; the quadratic inversion on the review's two witnesses and 3000 random concave
    quadratics (certified interval strictly inside the positive set); the stream enclosures under UNDERFLOW (2^-540 squares, 2^-1075 conversions) contain the exact
    statistics; a NONCONVEX accepted set is constructed and asserted; the rho / lambda / delta split are asserted as executed design-record fields, not strings.
Q7  numerical publication: feasibility conditions; an actual PAC publication of a tiny model (eps 1/20) passes verify_output and the frozen publisher; the record
    replay reproduces the published rows (gate path); huge / tiny exponents enclosed.
Q8  candidate validation (theory §9): not implemented (recorded).
Q9  resource-driven selection / continuation: deadline publishes a covered prefix or refuses; a failed trial terminates the stream; exact-route refusal continues into
    PAC with time left; the ZERO_EVIDENCE terminal honours the deadline through the NEW worker path (controlled clock); typed RANGE at source conversion is a typed stop.
Q10 existing defects: HostBudget control (claim narrowed), the frozen executor's own suite re-run in an ISOLATED COPY (no historical record rewritten).
Q11 diagnostic coverage at delta 0.1: misses counted per ATTEMPTED run (not per publication); every row retained; bug detection only, never a 1e-6 verification.
Q12 exact closure and partial cover: generic generated models: empty-cutset closure publishes deterministically after ONE contraction; forced cutsets reach a complete
    cover and publish deterministically; duplicate insertion refused; partial cover conservation (resolved mass + residual envelope >= Z; resolved mass <= Z)."""
import sys, os, json, time, math, random, hashlib, itertools, subprocess, shutil, copy, tempfile, contextlib, io
from fractions import Fraction as F
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm'); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (NEWARM, HERE): sys.path.insert(0, p)
sys.set_int_max_str_digits(0)
import engine, contrib, rig, solve, core, gate, support
R = {'groups': [], 'executions': 0, 'coordinates_checked': 0, 'suite_version': 'pac-qualification-v2 (2026-11-13)'}; passed = 0; total = 0
TMP = Path(tempfile.mkdtemp(prefix='pac_qual_v2_'))


def group(name, fn):
    global passed, total
    total += 1; t = time.monotonic()
    try: detail = fn(); ok = True
    except Exception as ex:
        import traceback; detail = {'error': '%s: %s' % (type(ex).__name__, ex), 'trace': traceback.format_exc()[-1200:]}; ok = False
    passed += ok; R['groups'].append(dict(name=name, ok=ok, wall_s=round(time.monotonic() - t, 3), detail=detail)); print(('PASS ' if ok else 'FAIL ') + name, flush=True)


def enum_truth(m):
    r = contrib.cell_exact(m, {}); Z = r['B0'][0]
    return Z, [[x[0] for x in r['B'][v]] for v in range(len(m['cards']))]


def chain(n, a=2): return {'cards': [2] * n, 'evidence': {}, 'factors': [{'scope': (i, i + 1), 'values': [F(a), F(1), F(1), F(a)]} for i in range(n - 1)]}


def rand_model(rng, nmin=3, nmax=5, cmax=3, zero_p=0.0, scale=False):
    n = rng.randint(nmin, nmax); cards = [rng.randint(2, cmax) for _ in range(n)]; fs = []
    for _ in range(rng.randint(n - 1, n + 2)):
        k = rng.randint(1, min(2, n)); sc = tuple(rng.sample(range(n), k)); vol = math.prod(cards[v] for v in sc)
        fs.append(dict(scope=sc, values=[F(0) if rng.random() < zero_p else F(rng.randint(1, 7), rng.randint(1, 7)) * (F(10) ** rng.randint(-3, 3) if scale else 1) for _ in range(vol)]))
    return dict(cards=cards, factors=fs, evidence={})


def write_uai(m, path):
    lines = ['MARKOV', str(len(m['cards'])), ' '.join(str(c) for c in m['cards']), str(len(m['factors']))] + ['%d %s' % (len(f['scope']), ' '.join(str(v) for v in f['scope'])) for f in m['factors']]
    for f in m['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(x) for x in f['values']))
    Path(path).write_text('\n'.join(lines) + '\n')
    if m.get('evidence'): Path(str(path) + '.evid').write_text('%d %s\n' % (len(m['evidence']), ' '.join('%d %d' % (v, a) for v, a in m['evidence'].items())))


# ---------------- Q1: identity + the GATE on real worker output and mutations
def q1_identity_gate():
    out = {}
    import cex_executor as X
    base = {'cards': [2, 3], 'factors': [dict(scope=(0, 1), values=[F(i + 1) for i in range(6)])], 'evidence': {1: 2}}
    w0, v0, meta = X.lower(base, [0], 0.25); h0 = meta['semantic_plan_sha256']
    for mut in ('model', 'evidence', 'card'):
        m2 = json.loads(json.dumps(base, default=str)); m2['factors'][0]['values'] = [F(x) for x in m2['factors'][0]['values']]; m2['evidence'] = {int(k): v_ for k, v_ in m2['evidence'].items()}
        if mut == 'model': m2['factors'][0]['values'][2] += 1
        if mut == 'evidence': m2['evidence'] = {1: 1}
        if mut == 'card': m2['cards'] = [2, 3, 2]; m2['factors'].append(dict(scope=(2,), values=[F(1), F(1)]))
        order = [vv for vv in range(len(m2['cards'])) if vv not in m2['evidence']]; _, _, meta2 = X.lower(m2, order, 0.25); assert meta2['semantic_plan_sha256'] != h0
    out['semantic_plan_mutations_change_binding'] = 3
    # ---- real worker output on a tiny model (deterministic exact cover) and a genuine PAC publication (in-process, eps 1/20) -> gate fixtures
    D = TMP / 'q1'; (D / 'cells/one').mkdir(parents=True)
    m = {'cards': [2, 2], 'factors': [dict(scope=(0,), values=[F(1), F(1)]), dict(scope=(0, 1), values=[F(2), F(1), F(1), F(2)])], 'evidence': {}}; write_uai(m, D / 'tiny.uai'); model, binding = core.read_uai(D / 'tiny.uai')
    seed = 'q1-seed'; nonce = 'q1-nonce'; outp = D / 'cells/one/worker.json'; t0 = time.monotonic()
    subprocess.run([sys.executable, os.path.join(HERE, 'worker.py'), '--input', str(D / 'tiny.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(t0 + 30), '--seed', seed, '--nonce', nonce, '--budget', '30'], check=True, cwd=CODE)
    wall = time.monotonic() - t0; w = json.load(open(outp)); assert w['status'] == 'COMPLETED' and w['guarantee_type'] == 'DETERMINISTIC', w.get('reason'); out['worker_deterministic_fixture_route'] = [c['route'] for c in w['stats']['components']]; R['executions'] += 1
    cs = w['candidate_sources']; frozen = {k: v for k, v in cs.items()}
    c = dict(cell_id='cell1', cohort='external_core', case_id='tiny', arm='P1_PAC_CONDITIONAL', replicate=0, budget_s=30.0, seed=seed, model_path=str(D / 'tiny.uai'), model_sha256=binding['model_sha256'], evidence_sha256=binding['evidence_sha256'])
    man = dict(cells=[c], task={'epsilon': '1/200', 'delta': '1/1000000'}, candidate_artifact_hashes=frozen)
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest(); dump = lambda p, x: Path(p).write_text(json.dumps(x, indent=1))
    uai_text = Path(D / 'tiny.uai').read_text()
    def build(mutate, bad_start=False):
        shutil.rmtree(D / 'cells', ignore_errors=True); (D / 'cells/one').mkdir(parents=True); Path(D / 'tiny.uai').write_text(uai_text)
        mm = copy.deepcopy(man); ww = copy.deepcopy(w); rr = dict(copy.deepcopy(c), status='COMPLETED', outcome='PUBLISHED', guarantee_type=ww['guarantee_type'], nonce=nonce, within_budget=True, launch_relative_wall_s=round(wall, 3), supervisor={'rc': 0, 'outcome': 'COMPLETED'}, worker_output='cells/one/worker.json')
        mutate(D, mm, rr, ww); dump(D / 'CAMPAIGN_MANIFEST.json', mm); mh = sha(D / 'CAMPAIGN_MANIFEST.json')
        dump(D / 'CAMPAIGN_START.json', {'manifest_sha256': ('0' * 64 if bad_start else mh), 'manifest': 'CAMPAIGN_MANIFEST.json'}); (D / 'PAC_LEDGER.jsonl').write_text(json.dumps({'kind': 'CAMPAIGN_START', 'manifest_sha256': mh}) + '\n')
        dump(D / 'cells/one/worker.json', ww); rr['output_sha256'] = sha(D / 'cells/one/worker.json'); dump(D / 'cells/one/receipt.json', rr)
        with contextlib.redirect_stdout(io.StringIO()): rc = gate.main(str(D))
        return rc, json.load(open(D / 'GATE_RESULT.json'))['failures']
    rc, f = build(lambda d, m_, r_, w_: None); assert rc == 0 and not f, f; out['valid_fixture_accepted'] = True
    def changed_input(d, m_, r_, w_):
        Path(d / 'tiny.uai').write_text(uai_text.replace('2 1 1 2', '2 1 1 3')); _, b = core.read_uai(d / 'tiny.uai'); w_.update(binding=b)
    def wrong_decimals(d, m_, r_, w_): w_['intervals'][0] = [['0.10000000', '0.10000000'], ['0.90000000', '0.90000000']]; w_['points'][0] = ['0.10000000', '0.90000000']
    def late_zero(d, m_, r_, w_): r_.update(status='STOPPED', outcome='PROVED_ZERO_EVIDENCE', guarantee_type='DETERMINISTIC', launch_relative_wall_s=200.0, within_budget=False, supervisor={'rc': 9, 'outcome': 'NONZERO_EXIT'}, worker_output=None, output_sha256=None); w_.clear()
    def cbi_absent(d, m_, r_, w_): m_['cells'][0]['arm'] = 'CBI_NATIVE'; r_.update(arm='CBI_NATIVE', guarantee_type='DETERMINISTIC', worker_output='absent.json', output_sha256='0' * 64)
    negatives = {'empty_candidate_source_map': lambda d, m_, r_, w_: w_.update(candidate_sources={}),
                 'missing_certificate_wrong_delta': lambda d, m_, r_, w_: (w_.pop('certificate'), w_.update(delta='1/2', epsilon='1/10')),
                 'late_publication_true_boolean': lambda d, m_, r_, w_: r_.update(launch_relative_wall_s=200.0, within_budget=True),
                 'duplicate_planned_cell': lambda d, m_, r_, w_: m_['cells'].append(copy.deepcopy(m_['cells'][0])),
                 'input_changed_after_freeze': changed_input, 'fabricated_decimals': wrong_decimals,
                 'fabricated_pac_answer_no_certificate': lambda d, m_, r_, w_: (wrong_decimals(d, m_, r_, w_), w_.pop('certificate'), w_.update(guarantee_type='PAC'), r_.update(guarantee_type='PAC')),
                 'late_unproved_zero_nonzero_child': late_zero, 'cbi_completed_without_output': cbi_absent,
                 'foreign_nonce': lambda d, m_, r_, w_: w_.update(nonce='other'), 'wrong_seed': lambda d, m_, r_, w_: w_.update(seed='other'),
                 'exact_cover_without_resolved_cells': lambda d, m_, r_, w_: w_['certificate']['components'][0].update(resolved_cells=0),
                 'lifted_rows_tampered': lambda d, m_, r_, w_: w_['certificate']['lifted_intervals_exact'][0].__setitem__(0, ['1/10', '1/10'])}
    rej = {}
    for name, mut in negatives.items():
        rc, f = build(mut); assert rc == 1 and f, (name, f); rej[name] = f[0][1][:70]; R['executions'] += 1
    rc, f = build(lambda d, m_, r_, w_: None, bad_start=True); assert rc == 1 and any('CAMPAIGN_START' in x[1] for x in f); rej['start_hash_disagrees'] = f[0][1][:70]
    def missing_receipt(d, m_, r_, w_): e = copy.deepcopy(m_['cells'][0]); e['cell_id'] = 'missing'; m_['cells'].append(e)
    rc, f = build(missing_receipt); assert rc == 1 and any('NOT_RUN' in x[1] for x in f); rej['missing_receipt'] = f[0][1][:70]
    out['negative_controls_rejected'] = rej
    # ---- a genuine PAC certificate fixture (in-process A0 at eps 1/20) and its tampering
    pol = engine.POLICY; old = pol['epsilon']; pol['epsilon'] = F(1, 20)
    try: r = solve.solve(chain(3, 2), time.monotonic() + 120, 'A0_POINT', 'q1-pac', delta=F(1, 20))
    finally: pol['epsilon'] = old
    assert r['guarantee_type'] == 'PAC'; R['executions'] += 1; out['pac_fixture_trials'] = r['certificate']['components'][0]['trials']
    D2 = TMP / 'q1pac'; (D2 / 'cells/one').mkdir(parents=True); write_uai(chain(3, 2), D2 / 'c3.uai'); model2, binding2 = core.read_uai(D2 / 'c3.uai'); ivd, ptd = core.publish(r['intervals'], r['points'], epsilon=F(1, 20))
    w2 = dict(status='COMPLETED', arm='A0_POINT', seed='q1-pac', nonce='nn', delta='1/20', epsilon='1/20', guarantee_type='PAC', outcome='PUBLISHED', binding=binding2, intervals=ivd, points=ptd, certificate=json.loads(json.dumps(r['certificate'], default=str)), stats={}, candidate_sources=frozen)
    c2 = dict(cell_id='cell1', cohort='external_core', case_id='c3', arm='A0_POINT', replicate=0, budget_s=120.0, seed='q1-pac', model_path=str(D2 / 'c3.uai'), model_sha256=binding2['model_sha256'], evidence_sha256=binding2['evidence_sha256'])
    man2 = dict(cells=[c2], task={'epsilon': '1/20', 'delta': '1/20'}, candidate_artifact_hashes=frozen)
    def build2(mutate):
        shutil.rmtree(D2 / 'cells', ignore_errors=True); (D2 / 'cells/one').mkdir(parents=True)
        mm = copy.deepcopy(man2); ww = copy.deepcopy(w2); rr = dict(copy.deepcopy(c2), status='COMPLETED', outcome='PUBLISHED', guarantee_type='PAC', nonce='nn', within_budget=True, launch_relative_wall_s=1.0, supervisor={'rc': 0, 'outcome': 'COMPLETED'}, worker_output='cells/one/worker.json')
        mutate(mm, rr, ww); dump(D2 / 'CAMPAIGN_MANIFEST.json', mm); mh = sha(D2 / 'CAMPAIGN_MANIFEST.json')
        dump(D2 / 'CAMPAIGN_START.json', {'manifest_sha256': mh, 'manifest': 'CAMPAIGN_MANIFEST.json'}); (D2 / 'PAC_LEDGER.jsonl').write_text(json.dumps({'kind': 'CAMPAIGN_START', 'manifest_sha256': mh}) + '\n')
        dump(D2 / 'cells/one/worker.json', ww); rr['output_sha256'] = sha(D2 / 'cells/one/worker.json'); dump(D2 / 'cells/one/receipt.json', rr)
        with contextlib.redirect_stdout(io.StringIO()): rc = gate.main(str(D2))
        g = json.load(open(D2 / 'GATE_RESULT.json')); return rc, g['failures'], g.get('pac_certificates_replayed')
    rc, f, n = build2(lambda m_, r_, w_: None); assert rc == 0 and n == 1, f; out['pac_certificate_replayed_and_accepted'] = True
    SS = lambda w_: w_['certificate']['components'][0]['sufficient_statistics']
    tampers = {'n': lambda m_, r_, w_: SS(w_).__setitem__('n', SS(w_)['n'] + 1), 'a_lo': lambda m_, r_, w_: SS(w_)['a_lo'].__setitem__(0, SS(w_)['a_lo'][0] * 1.01), 'alpha': lambda m_, r_, w_: w_['certificate']['components'][0]['design'].__setitem__('alpha_range', '1/2'),
               'K': lambda m_, r_, w_: (w_['certificate'].__setitem__('K_total', 1), w_['certificate']['delta_ledger'].__setitem__('coordinates', 1)), 'exact_row': lambda m_, r_, w_: w_['certificate']['components'][0]['intervals_exact'][0].__setitem__(0, ['1/10', '1/10']),
               'task_delta': lambda m_, r_, w_: m_['task'].__setitem__('delta', '1/1000000'), 'U_root': lambda m_, r_, w_: (w_['certificate']['components'][0]['design'].__setitem__('U_root', '0/1'), SS(w_).__setitem__('U_root', '0/1')), 'certifier_label': lambda m_, r_, w_: w_['certificate']['components'][0]['certifier_per_row'].__setitem__(0, 'range')}
    rej2 = {}
    for name, mut in tampers.items():
        rc, f, n = build2(mut); assert rc == 1 and f, (name, f); rej2[name] = f[0][1][:70]; R['executions'] += 1
    out['pac_certificate_tampering_rejected'] = rej2; return out


# ---------------- Q2
def q2_masses():
    rng = random.Random(2); out = {'random_cells': 0}
    m = {'cards': [2, 2, 3], 'factors': [dict(scope=(0,), values=[F(1), F(1000)]), dict(scope=(1,), values=[F(1, 3), F(2, 3)]), dict(scope=(2,), values=[F(1, 6), F(1, 3), F(1, 2)]), dict(scope=(0, 1), values=[F(1), F(1), F(1), F(1)])], 'evidence': {}}
    a = contrib.cell_kernel(m, {0: 0}); b = contrib.cell_kernel(m, {0: 1}); ea = contrib.cell_exact(m, {0: 0}); eb = contrib.cell_exact(m, {0: 1})
    assert a['B0'][0] <= ea['B0'][0] <= a['B0'][1] and b['B0'][0] <= eb['B0'][0] <= b['B0'][1] and eb['B0'][0] / ea['B0'][0] == 1000
    assert all(abs(a['B'][1][s][0] / a['B0'][0] - b['B'][1][s][0] / b['B0'][0]) < F(1, 10 ** 9) for s in range(2)); out['posterior_identical_mass_1000x'] = True
    m2 = {'cards': [2, 2, 3, 2], 'factors': [dict(scope=(0, 1), values=[F(3), F(0), F(0), F(5)]), dict(scope=(0, 1), values=[F(3), F(0), F(0), F(5)]), dict(scope=(2,), values=[F(0), F(2) ** 40, F(2) ** -30]), dict(scope=(3,), values=[F(7), F(1, 7)])], 'evidence': {3: 1}}
    for cut in ({}, {0: 0}, {0: 1}, {2: 1}, {0: 1, 2: 2}):
        ek = contrib.cell_kernel(m2, cut); ee = contrib.cell_exact(m2, cut); R['executions'] += 1
        assert ek['B0'][0] <= ee['B0'][0] <= ek['B0'][1]
        for v in range(4):
            for s in range(m2['cards'][v]): assert ek['B'][v][s][0] <= ee['B'][v][s][0] <= ek['B'][v][s][1]; R['coordinates_checked'] += 1
        assert all(sum(x[0] for x in ee['B'][v]) == ee['B0'][0] for v in range(4))
    out['evidence_alias_repeat_gauge_disconnected'] = True
    bad = 0
    for trial in range(200):
        n = rng.randint(3, 6); cards = [rng.randint(2, 4) for _ in range(n)]; fs = []
        for _ in range(rng.randint(2, n + 2)):
            k = rng.randint(1, min(3, n)); sc = tuple(rng.sample(range(n), k)); vol = math.prod(cards[v] for v in sc)
            fs.append(dict(scope=sc, values=[F(0) if rng.random() < 0.15 else F(rng.randint(1, 9), rng.randint(1, 9)) * F(10) ** rng.randint(-3, 3) for _ in range(vol)]))
        mm = dict(cards=cards, factors=fs, evidence={rng.randrange(n): 0} if rng.random() < 0.4 else {}); free = [v for v in range(n) if v not in mm['evidence']]; cut = {v: rng.randrange(cards[v]) for v in rng.sample(free, rng.randint(0, max(0, len(free) - 1)))}
        ex = contrib.cell_exact(mm, cut)
        try: kr = contrib.cell_kernel(mm, cut)
        except contrib.CellStop: continue
        R['executions'] += 1; out['random_cells'] += 1
        okc = kr['B0'][0] <= ex['B0'][0] <= kr['B0'][1] and all(kr['B'][v][s][0] <= ex['B'][v][s][0] <= kr['B'][v][s][1] for v in range(n) for s in range(cards[v])); R['coordinates_checked'] += sum(cards); bad += (not okc)
    assert bad == 0, bad
    # evidence contradiction (review C1): cell X=1 under evidence X=0 is a PROVED EMPTY cell, mass 0
    conflict = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), F(1000)]}], 'evidence': {0: 0}}
    r = contrib.cell_exact(conflict, {0: 1}); assert r['B0'] == (F(0), F(0)) and r['route'] == 'exact_zero_cell'
    rk = contrib.cell_kernel(conflict, {0: 1}); assert rk['B0'] == (F(0), F(0)); out['evidence_contradiction_is_empty_cell'] = True
    # public-API deadline boundary (review C3): an expired deadline is refused at entry even for trivial cells
    for mdl, cell in (({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, {0: 0}), ({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), F(1)]}], 'evidence': {}}, {})):
        for fn in (contrib.cell_exact, contrib.cell_kernel):
            try: fn(mdl, cell, deadline=time.monotonic() - 1); raise AssertionError('expired deadline accepted')
            except contrib.CellStop as e: assert e.kind == 'DEADLINE'
    out['expired_deadline_refused_at_entry'] = True
    m3 = {'cards': [2, 2], 'factors': [dict(scope=(0,), values=[F(1), F(2)]), dict(scope=(1,), values=[F(0), F(0)])], 'evidence': {}}
    try: solve.solve(m3, time.monotonic() + 10, 'P1_PAC_CONDITIONAL', 'q', F(1, 10)); raise AssertionError('zero component not detected')
    except solve.ZeroEvidence: pass
    out['zero_evidence_component_invalidates_job'] = True; return out


# ---------------- Q3 / Q4 / Q5: the tree law
def tree_law(m, cut, resolved=()):
    """exact law of the production draw with the given resolved leaves: enumerate all paths through Tree.child_weights (effective weights)"""
    T = engine.Tree(m, cut)
    for leaf, u in resolved: T.resolve(leaf, u)
    law = {}; zero_prefix = F(0)
    def rec(prefix, assign, cur, u, q, i):
        nonlocal zero_prefix
        if i == len(T.cut): law[prefix] = q; return
        v = T.cut[i]; ws, news = T.child_weights(prefix, assign, cur, u, v); S = sum(ws)
        if S == 0: zero_prefix += q; return
        for s_, wgt in enumerate(ws):
            if wgt == 0: continue
            a2 = dict(assign); a2[v] = s_; c2 = dict(cur); c2.update(news[s_][1]); rec(prefix + (s_,), a2, c2, news[s_][0], q * wgt / S, i + 1)
    rec((), {}, {a: int(T.levels[a][0].reshape(-1)[0]) for a in range(len(T.factors))}, T.u_root, F(1), 0); return T, law, zero_prefix


def q3_fixed_laws_and_resolution():
    rng = random.Random(3); out = dict(models=0, leaves=0)
    for trial in range(30):
        m = rand_model(rng, 3, 5, 3, zero_p=0.2); n = len(m['cards']); cards = m['cards']; Z, N = enum_truth(m); kcut = rng.randint(1, n - 1); cut = rng.sample(range(n), kcut)
        T, law, zp = tree_law(m, cut); U = T.u_root
        if U == 0: assert Z == 0; continue
        assert sum(law.values()) + zp == 1
        ET = F(0); EY = [[F(0)] * c for c in cards]; EP = F(0); EPY = [[F(0)] * c for c in cards]
        for leaf, q in law.items():
            assign = dict(zip(T.cut, leaf)); r = contrib.cell_exact(m, assign); B0 = r['B0'][0]
            assert B0 <= U * q, 'pointwise envelope (integrated)'
            ET += B0
            for v in range(n):
                for s in range(cards[v]): EY[v][s] += r['B'][v][s][0]
            free = [v for v in range(n) if v not in assign]
            for x in itertools.product(*(range(cards[v]) for v in free)):
                full = dict(assign); full.update(zip(free, x)); w = T.point_weight(full); rr = w * T.free_count / q
                assert rr <= U, 'pointwise envelope (point)'
                EP += (q / T.free_count) * rr
                for v in range(n): EPY[v][full[v]] += (q / T.free_count) * rr
        assert ET == Z and EP == Z and all(EY[v][s] == N[v][s] and EPY[v][s] == N[v][s] for v in range(n) for s in range(cards[v]))
        for x in itertools.product(*(range(c) for c in cards)):
            full = dict(enumerate(x)); w = T.point_weight(full)
            if w > 0: assert law.get(tuple(x[v] for v in T.cut), F(0)) > 0, 'positive state with zero proposal probability'
        out['models'] += 1; out['leaves'] += len(law); R['executions'] += len(law)
    # ---- ADAPTIVE HISTORY control: after resolving a random subset of leaves, the effective law covers exactly the unresolved positive mass and E[A + r] = Z
    hist = 0
    for trial in range(20):
        m = rand_model(rng, 3, 4, 3, zero_p=0.1); n = len(m['cards']); Z, N = enum_truth(m); cut = rng.sample(range(n), rng.randint(1, n - 1))
        T0, law0, _ = tree_law(m, cut)
        if T0.u_root == 0: continue
        leaves = list(law0); k = rng.randint(0, len(leaves)); chosen = rng.sample(leaves, k)
        res = []; A = F(0)
        for leaf in chosen:
            assign = dict(zip(T0.cut, leaf)); u = F(1)
            # exact u_leaf as the engine computes it: m_leaf * prod_a M_a(leaf)
            T_ = engine.Tree(m, cut); _, _, _, _, u_leaf = (None, None, None, None, None)
            # recover u_leaf by walking the tree deterministically
            prefix = (); cur = {a: int(T_.levels[a][0].reshape(-1)[0]) for a in range(len(T_.factors))}; u = T_.u_root; asg = {}
            for i, v in enumerate(T_.cut):
                ws, news = T_.child_weights(prefix, asg, cur, u, v); s_ = leaf[i]; u = news[s_][0]; cur.update(news[s_][1]); asg[v] = s_; prefix = prefix + (s_,)
            res.append((leaf, u)); A += contrib.cell_exact(m, assign)['B0'][0]
        T, law, zp = tree_law(m, cut, res)
        assert all(leaf not in law for leaf in chosen), 'resolved leaf still reachable'
        if T.U_t == 0: assert A == Z; hist += 1; continue
        ET = A + sum(contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] for leaf, q in law.items())      # sum over leaves of q * B0/q
        assert ET == Z, 'E[A + r] != Z after resolution'
        for leaf, q in law.items(): assert contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] <= T.U_t * q, 'residual envelope violated'
        hist += 1; R['executions'] += 1
    out['adaptive_resolution_histories'] = hist
    # ---- the PRODUCTION draw_leaf is exercised: empirical frequencies vs exact law (chi-square diagnostic, 5 models x 20000 draws)
    chi_ok = 0
    for trial in range(5):
        m = rand_model(rng, 3, 4, 3); n = len(m['cards']); cut = rng.sample(range(n), 2); T, law, zp = tree_law(m, cut)
        rng_t = random.Random(777 + trial); counts = {}; Ndraw = 20000
        for _ in range(Ndraw):
            assign, q, zero, trans, u = T.draw_leaf(rng_t); key = tuple(assign.get(v) for v in T.cut) if not zero else 'zero'; counts[key] = counts.get(key, 0) + 1
            if not zero: assert q == law[key], 'reported q differs from the exact law'
        chi = sum((counts.get(k, 0) - Ndraw * float(p)) ** 2 / (Ndraw * float(p)) for k, p in law.items() if p > 0) + ((counts.get('zero', 0) - Ndraw * float(zp)) ** 2 / (Ndraw * float(zp)) if zp > 0 else 0)
        dof = len([p for p in law.values() if p > 0]) + (1 if zp > 0 else 0) - 1; assert chi < dof + 6 * math.sqrt(2 * dof) + 12, (chi, dof); chi_ok += 1
    out['production_draw_leaf_frequency_checks'] = chi_ok
    # negative identity controls (algebra)
    m = {'cards': [2, 2], 'factors': [dict(scope=(0, 1), values=[F(1), F(2), F(3), F(4)])], 'evidence': {}}; Z, N = enum_truth(m); T, law, zp = tree_law(m, [0])
    expectation = lambda fn: sum(q * fn(leaf, q) for leaf, q in law.items())
    assert expectation(lambda leaf, q: contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] / q) == Z
    assert expectation(lambda leaf, q: contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] / (q / 2 if leaf == (0,) else q)) != Z
    assert expectation(lambda leaf, q: contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] / q + contrib.cell_exact(m, {0: 0})['B0'][0]) != Z
    assert sum(q * (contrib.cell_exact(m, dict(zip(T.cut, leaf)))['B0'][0] / (q if leaf == (0,) else F(1))) for leaf, q in law.items()) != Z
    out['negative_identity_controls_detected'] = 3
    # duplicate insertion refused by the production Tree
    T = engine.Tree(m, [0]); T.resolve((0,), F(1))
    try: T.resolve((0,), F(1)); raise AssertionError('duplicate resolution accepted')
    except engine.EngineStop as e: assert e.outcome == 'INVALID_PLAN_OR_CERTIFICATE'
    out['duplicate_resolved_cell_refused'] = True; return out


def q5_sampling_law():
    """the PRODUCTION PRNG backend (random.Random / randrange) is exercised; the child-selection algebra is a separate labelled check"""
    out = {}
    for W in (3, 5, 6, 7, 12, 1000):
        k = W.bit_length(); counts = [0] * W
        for r in range(1 << k):
            if r < W: counts[r] += 1
        assert all(c == 1 for c in counts); out['algebra_rejection_W_%d' % W] = dict(bits=k)
    m = {'cards': [3, 2], 'factors': [dict(scope=(0,), values=[F(1), F(2), F(3)]), dict(scope=(0, 1), values=[F(1)] * 6)], 'evidence': {}}; T = engine.Tree(m, [0])
    ws, news = T.child_weights((), {}, {a: int(T.levels[a][0].reshape(-1)[0]) for a in range(2)}, T.u_root, 0); assert [w / sum(ws) for w in ws] == [F(1, 6), F(1, 3), F(1, 2)]
    # actual backend: 60000 draws with the production Random; frequencies vs 1/6, 1/3, 1/2
    rng = random.Random(20261113); counts = [0, 0, 0]; N = 60000
    for _ in range(N):
        a, q, z, tr, u = T.draw_leaf(rng); counts[a[0]] += 1; assert q == [F(1, 6), F(1, 3), F(1, 2)][a[0]]
    for s_, p in enumerate((F(1, 6), F(1, 3), F(1, 2))):
        assert abs(counts[s_] / N - float(p)) < 5 * math.sqrt(float(p) * (1 - float(p)) / N), counts
    out['production_random_backend_frequencies'] = counts; out['prng'] = 'random.Random (MT19937); randrange = rejection on getrandbits (CPython _randbelow_with_getrandbits); seed reproducibility is engineering evidence, the theorem assumes ideal bits'; return out


def q4_envelopes():
    out = {}
    rng = random.Random(4); checks = 0
    for trial in range(40):
        m = rand_model(rng, 3, 5, 3, zero_p=0.3); n = len(m['cards']); cards = m['cards']; cut = rng.sample(range(n), rng.randint(1, n)); T = engine.Tree(m, cut)
        def rec(prefix, assign, cur, u, i):
            nonlocal checks
            if i == len(T.cut): return
            v = T.cut[i]; ws, news = T.child_weights(prefix, assign, cur, u, v)
            assert sum(nw[0] for nw in news) <= u; checks += 1                       # child-sum inequality (exact)
            for s_, (us, new) in enumerate(news):
                if us > 0: a2 = dict(assign); a2[v] = s_; c2 = dict(cur); c2.update(new); rec(prefix + (s_,), a2, c2, us, i + 1)
        rec((), {}, {a: int(T.levels[a][0].reshape(-1)[0]) for a in range(len(T.factors))}, T.u_root, 0)
    out['child_sum_monotonicity_checks'] = checks
    m0 = {'cards': [2, 2], 'factors': [dict(scope=(0, 1), values=[F(0), F(0), F(0), F(0)])], 'evidence': {}}; r0 = engine.run_component(m0, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1])
    assert r0['status'] == 'PROVED_ZERO_EVIDENCE' and r0['guarantee'] == 'DETERMINISTIC'; out['U0_root_is_deterministic_zero'] = True
    # positive Z, all-zero observed prefix (the review's control): refusal with guarantee NONE, never zero evidence
    mz = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(0), F(0), F(0)]}], 'evidence': {}}
    rz = engine.run_component(mz, time.monotonic() + 5, 1, 9, 'point', F(1, 20), F(1, 20), 4, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1], max_trials=3)
    assert rz['status'] == 'TOO_WIDE' and rz['guarantee'] == 'NONE' and rz['stats']['positive_trials'] == 0 and 'NOT a zero-evidence claim' in rz['stats'].get('note', ''); out['positive_Z_zero_prefix_refuses_not_zero_evidence'] = rz['stats']['zero_trials']
    # the PRODUCTION envelope guard: a corrupted tree (u_leaf under-reported by a test double) makes run_component raise INVALID_PLAN_OR_CERTIFICATE on the first trial (both modes)
    class BadTree(engine.Tree):
        def draw_leaf(self, rng):
            assign, q, zero, trans, u = super().draw_leaf(rng); return assign, q, zero, trans, u / 1000
    m1 = chain(5, 3)
    for mode in ('point', 'conditional'):
        try: engine.run_component(m1, time.monotonic() + 5, 1, 2, mode, F(1, 10), F(1, 10), 10, 3 * 2 ** 30, 0, fixed_cutset=[0, 2], fixed_order=[1, 3, 4], max_trials=50, tree_factory=BadTree, resolve=False); raise AssertionError('invalid envelope accepted (%s)' % mode)
        except engine.EngineStop as e: assert e.outcome == 'INVALID_PLAN_OR_CERTIFICATE' and 'envelope' in e.reason or 'telescoping' in e.reason, e.reason
    out['production_envelope_guard_rejects_corrupted_tree'] = True; return out


# ---------------- Q6
def q6_confidence():
    out = {}
    from decimal import Decimal, getcontext; getcontext().prec = 60
    for rho, V, alpha in ((F(1, 4), F(10), F(1, 2000000)), (F(1, 4), F(1, 4), F(1, 40)), (F(1, 4), F(10 ** 6), F(1, 10 ** 9))):
        bU = rig.range_boundary_up(rho, V, alpha); s = Decimal((rho + V).numerator) / Decimal((rho + V).denominator); arg = s / (Decimal(rho.numerator) / Decimal(rho.denominator) * (Decimal(alpha.numerator) / Decimal(alpha.denominator)) ** 2)
        ref = (s * arg.ln()).sqrt(); bd = Decimal(int(bU.numerator)) / Decimal(int(bU.denominator)); assert bd >= ref and (bd - ref) / ref < Decimal('1e-30')
    out['range_boundary_rounded_up_within_1e-30'] = True
    for l in range(1, 17):
        lam = F(1, 2 ** l); lo, hi = rig.psi(lam); ref = -(Decimal(1) - Decimal(lam.numerator) / Decimal(lam.denominator)).ln() - Decimal(lam.numerator) / Decimal(lam.denominator)
        assert Decimal(int(lo.numerator)) / Decimal(int(lo.denominator)) <= ref <= Decimal(int(hi.numerator)) / Decimal(int(hi.denominator))
    out['psi_enclosures_16'] = True
    assert Decimal('9.8696044011') > Decimal('9.869604401089358618834490999876151135313699407240790626413349376'); out['omega_lower_bound_valid'] = True
    # ---- quadratic inversion: the review's witness 1
    A = 1 + F(1, 2 ** 130); coeff = (-A, A, -A * F(2, 9)); g = lambda t: coeff[0] * t * t + coeff[1] * t + coeff[2]
    iv = rig.shrunk_rejection(*coeff); assert iv is not None and F(1, 3) < iv[0] < iv[1] < F(2, 3) and g(iv[0]) > 0 and g(iv[1]) > 0; out['review_witness_1_inside_positive_set'] = [str(F(1, 3) - iv[0] <= 0), float(F(2, 3) - iv[1])]
    # the review's witness 2 family (128 unit point trials, 0 successes, l=1, sign -1) with exact statistics
    lam = F(1, 2); omega = F(6) / (F(98696044011, 10 ** 10)); L = rig.log_threshold_up(1, F(1, 2000000) / 2, omega); plo, phi = rig.psi(lam)
    n = 128; a2 = -phi * n; a1 = lam * n; a0 = -phi * 0 - L; outv = rig.shrunk_rejection(a2, a1, a0)
    if outv is not None:
        gg = lambda t: a2 * t * t + a1 * t + a0
        for th in (outv[0], outv[1], outv[0] + (outv[1] - outv[0]) / 2 ** 400, outv[1] - (outv[1] - outv[0]) / 2 ** 400): assert gg(th) > 0
    out['review_witness_2_family_certified'] = outv is not None
    # 3000 random concave quadratics with exact roots: the certified interval lies strictly inside (r1, r2)
    rng = random.Random(5); bad = 0; none = 0
    for _ in range(3000):
        r1 = F(rng.randrange(-10 ** 6, 10 ** 6), 10 ** 6); r2 = r1 + F(rng.randrange(1, 10 ** 6), 10 ** 6); Aq = F(rng.randrange(1, 10 ** 9), rng.randrange(1, 10 ** 9)) * (1 + F(1, 2 ** rng.randrange(1, 200)))
        o = rig.shrunk_rejection(-Aq, Aq * (r1 + r2), -Aq * r1 * r2); R['executions'] += 1
        if o is None: none += 1; continue
        if not (r1 < o[0] < o[1] < r2): bad += 1
    assert bad == 0; out['random_concave_quadratics'] = dict(n=3000, none=none, violations=0)
    # IV.sq control
    ivq = rig.IV(-(1 + F(1, 2 ** 60)), F(1)); sq = ivq.sq().frac(); assert sq[0] == 0 and sq[1] >= (1 + F(1, 2 ** 60)) ** 2; out['IV_sq_crossing_zero_encloses_endpoint_square'] = True
    # ---- underflow controls (review M1) through the production stream: exact statistics are enclosed
    for pw in (540, 1075):
        a = F(1, 2 ** pw); model = {'cards': [2], 'factors': [{'scope': (0,), 'values': [F(1), a]}, {'scope': (0,), 'values': [a, F(1)]}], 'evidence': {}}
        for mode in ('point', 'conditional'):
            r = engine.run_component(model, time.monotonic() + 30, 123, 456, mode, F(1, 2000000), F(1, 2000000), 2, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[], max_trials=1, resolve=False); S = r['stats']['sufficient_statistics']; U = F(S['U_root']); assert U == 2; ex = (a / F(1, 2)) / U      # the normalized trial: W(x)/Q(x) / U_root = (a / (1/2)) / 2 = a exactly (the review's T' = a)
            assert F(S['b_lo']) <= ex <= F(S['b_hi']) and F(S['e_lo']) <= ex * ex <= F(S['e_hi']) and F(S['a_lo'][0]) <= ex <= F(S['a_hi'][0]) and F(S['c_lo'][0]) <= ex * ex <= F(S['c_hi'][0]) and F(S['d_lo'][0]) <= ex * ex <= F(S['d_hi'][0]), (pw, mode)
            assert r['stats']['positive_trials'] == 1 and r['guarantee'] == 'NONE'; R['executions'] += 1
    out['underflow_statistics_enclosed_2^-540_2^-1075'] = True
    # directed accumulator enclosure on random streams vs exact rational sums (both modes of increment)
    rng = random.Random(6); S = engine.Stream([3], [], F(1), F(1, 20), F(1, 20), 3, list(range(1, 17))); exb = F(0); exe = F(0); exa = [F(0)] * 3; exc = [F(0)] * 3; exd = [F(0)] * 3
    for _ in range(500):
        x = F(rng.randrange(0, 2 ** 40), 2 ** (40 + rng.randrange(0, 1030))); j = rng.randrange(3); lo, hi = rig.df_lo(x), rig.df_hi(x); Y = S.np.zeros(3); Yh = S.np.zeros(3); Y[j] = lo; Yh[j] = hi
        S.add_residual(lo, hi, Y, Yh); exb += x; exe += x * x; exa[j] += x; exc[j] += x * x; exd[j] += x * x
    assert F(S.b_lo) <= exb <= F(S.b_hi) and F(S.e_lo) <= exe <= F(S.e_hi) and all(F(S.a_lo[j]) <= exa[j] <= F(S.a_hi[j]) and F(S.c_lo[j]) <= exc[j] <= F(S.c_hi[j]) and F(S.d_lo[j]) <= exd[j] <= F(S.d_hi[j]) for j in range(3)); out['directed_accumulators_enclose_exact_sums_500'] = True
    # inversion outer-set property vs a theta grid on a real stream + a NONCONVEX accepted set constructed and asserted
    rng = random.Random(6); S = engine.Stream([3], [], F(1), F(1, 20), F(1, 20), 3, list(range(1, 17)))
    for _ in range(300):
        x = F(rng.random() * 0.8).limit_denominator(2 ** 40); j = rng.randrange(3); lo, hi = rig.df_lo(x), rig.df_hi(x); Y = S.np.zeros(3); Yh = S.np.zeros(3); Y[j] = lo; Yh[j] = hi; S.add_residual(lo, hi, Y, Yh)
    Rr = S.record(); sets = engine.variance_sets_from(Rr); blo, bhi = F(Rr['b_lo']), F(Rr['b_hi']); elo, ehi = F(Rr['e_lo']), F(Rr['e_hi'])
    for s_ in range(3):
        alo, ahi = F(Rr['a_lo'][s_]), F(Rr['a_hi'][s_]); clo, chi = F(Rr['c_lo'][s_]), F(Rr['c_hi'][s_]); dlo, dhi = F(Rr['d_lo'][s_]), F(Rr['d_hi'][s_]); acc = sets[0][s_]
        for k in range(0, 1001):
            th = F(k, 1000); rejected_any = False
            for l in range(1, 17):
                lam = F(1, 2 ** l); omega_lo = F(6) / (F(98696044011, 10 ** 10) * l * l); L = rig.log_threshold_up(1, S.alpha_v, omega_lo); plo, phi = rig.psi(lam)
                for sign in (1, -1):
                    g_lo = (lam * (alo - th * bhi) if sign == 1 else -lam * (ahi - th * blo)) - phi * (chi - 2 * th * dlo + th * th * ehi)
                    if g_lo > L: rejected_any = True
            in_acc = any(a <= th <= b for a, b in acc)
            if not rejected_any: assert in_acc, ('accepted set misses a non-rejected theta', th, acc)      # every non-rejected theta is accepted (outer set)
    out['variance_inversion_outer_set_grid_1001x3'] = True
    # a nonconvex accepted set: two tests rejecting disjoint middle intervals -> _subtract yields two components
    segs = engine._subtract(F(0), F(1), [(F(1, 10), F(3, 10)), (F(6, 10), F(8, 10))]); assert len(segs) == 3; out['nonconvex_accepted_set_constructed'] = len(segs)
    # rho / lambda / delta split as EXECUTED design-record fields
    r = engine.run_component(chain(3, 2), time.monotonic() + 5, 1, 2, 'point', F(1, 20), F(1, 40), 7, 3 * 2 ** 30, 0, fixed_cutset=[0], fixed_order=[1, 2], max_trials=2, resolve=False); d = r['stats']['design']
    assert F(d['alpha_range']) == F(1, 20) / 7 and F(d['alpha_variance']) == F(1, 40) / 7 and d['K_total'] == 7 and 'U_root^-2' in d['lambda_rule'] and 'rho = 1/4' in d['rho_rule'] and F(d['U_root']) == engine.Tree(chain(3, 2), [0]).u_root
    out['design_record_fields_executed'] = True; return out


def q7_publication():
    out = {}
    assert engine.feasible_point([(F(0), F(6, 10))] * 3, F(3, 10)) is None; out['three_0_0.6_eps_0.3_infeasible'] = True
    assert engine.feasible_point([(F(1, 10), F(5, 10)), (F(4, 10), F(8, 10))], F(1, 200)) is None
    p = engine.feasible_point([(F(49, 100), F(50, 100)), (F(50, 100), F(51, 100))], F(1, 200)); assert p is not None and sum(p) == 1; out['feasible_point_exact_simplex'] = True
    S = engine.Stream([2], [], F(1), F(1, 20), F(1, 20), 2, [1]); h, b = S.range_hulls(); assert h is None; out['no_division_without_positive_denominator'] = True
    # an ACTUAL PAC publication (eps 1/20, delta 1/20) through run_component; verify_output + frozen publisher + record replay (gate path)
    pol = dict(engine.POLICY); pol['epsilon'] = F(1, 20); m = chain(5, 2); truth = core.brute_force(m)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m, time.monotonic() + 120, 3, 4, mode, F(1, 40), F(1, 40), 10, 3 * 2 ** 30, 0, pol, fixed_cutset=[0, 2], fixed_order=[1, 3, 4], max_trials=3000000, resolve=False); R['executions'] += 1
        assert r['status'] == 'PUBLISHED' and r['guarantee'] == 'PAC', r['status']
        core.verify_output(r['intervals'], r['points'], F(1, 20)); di, dp = core.publish(r['intervals'], r['points'], epsilon=F(1, 20)); core.verify_output([[(F(a), F(b)) for a, b in row] for row in di], [[F(x) for x in row] for row in dp], F(1, 20))
        ok, rows, pts, chosen, widths, bU, vs = engine.hulls_from_record(r['stats']['sufficient_statistics'], pol['epsilon'], pol['decimal_margin']); assert ok and all(rows[v] == r['intervals'][v] and pts[v] == r['points'][v] for v in rows)
        out['pac_publication_%s' % mode] = dict(trials=r['stats']['trials_completed'], contains_truth=all(lo <= p_ <= hi for row, ps in zip(r['intervals'], truth) for (lo, hi), p_ in zip(row, ps)), certifiers=sorted(set(r['certifier_per_row'])), replay_equal=True)
    m = {'cards': [2], 'factors': [dict(scope=(0,), values=[F(2) ** 900, F(2) ** 899])], 'evidence': {}}; r = contrib.cell_kernel(m, {}); assert r['B0'][0] <= F(2) ** 900 + F(2) ** 899 <= r['B0'][1]
    m = {'cards': [2], 'factors': [dict(scope=(0,), values=[F(1, 2 ** 900), F(1, 2 ** 1000)])], 'evidence': {}}; r = contrib.cell_kernel(m, {}); assert r['B0'][0] <= F(1, 2 ** 900) + F(1, 2 ** 1000) <= r['B0'][1]; out['huge_small_exponents_enclosed'] = True
    return out


def q9_resource_selection_continuation():
    out = {}
    m = {'cards': [3] * 7, 'factors': [dict(scope=(i, (i + 1) % 7), values=[F(x) for x in (1, 2, 3, 4, 5, 6, 7, 8, 9)]) for i in range(7)], 'evidence': {}}
    r = engine.run_component(m, time.monotonic() + 0.4, 1, 2, 'conditional', F(1, 2 * 10 ** 6), F(1, 2 * 10 ** 6), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False)
    assert r['guarantee'] == 'NONE' and r['status'] in ('DEADLINE', 'TOO_WIDE') and r['stats']['terminal'] == 'DEADLINE'; out['deadline_refuses_with_prefix_recorded'] = r['stats']['trials_completed']
    calls = {'n': 0}; orig_k = engine.kernel_cell; orig_e = engine.exact_cell
    def failing(orig):
        def f(*a, **k):
            calls['n'] += 1
            if calls['n'] == 3: raise contrib.CellStop('MEMORY', 'injected')
            return orig(*a, **k)
        return f
    engine.kernel_cell = failing(orig_k); engine.exact_cell = failing(orig_e)
    try: r2 = engine.run_component(m, time.monotonic() + 5, 1, 2, 'conditional', F(1, 10), F(1, 10), 21, 3 * 2 ** 30, 0, fixed_cutset=[0, 1], fixed_order=[2, 3, 4, 5, 6], resolve=False)
    finally: engine.kernel_cell = orig_k; engine.exact_cell = orig_e
    assert r2['status'] == 'MEMORY' and r2['stats']['trials_completed'] == 2 and r2['stats']['trial_failure']['trial'] == 3; out['failed_trial_terminates_stream_prefix_2'] = True
    # exact-route refusal -> PAC continuation with time left (review F01 injected MEMORY at the exact execution boundary)
    import forest
    orig_discover = core._discover_component; orig_execute = core._execute_component; orig_pac = engine.run_component; orig_forest = forest.solve; cnt = {'exact': 0, 'pac': 0}
    def fake_discover(cm, deadline, route, inherited=None): return {'kind': 'support', 'forecast': 1, 'discovery': [], 'model': cm}
    def fail_execute(plan, deadline): cnt['exact'] += 1; raise support.ResourceStop('MEMORY', {'injected': 'exact execution boundary'})
    def observe_pac(*a, **k): cnt['pac'] += 1; return orig_pac(*a, **k)
    def no_forest(*a, **k): raise forest.UnsupportedError('test: forest disabled')
    core._discover_component = fake_discover; core._execute_component = fail_execute; engine.run_component = observe_pac; forest.solve = no_forest
    try: rr = solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9')
    finally: core._discover_component = orig_discover; core._execute_component = orig_execute; engine.run_component = orig_pac; forest.solve = orig_forest
    assert cnt == {'exact': 1, 'pac': 1} and rr['guarantee_type'] == 'DETERMINISTIC' and rr['stats']['continuations'][0]['stop'] == 'MEMORY'; out['exact_refusal_continues_into_pac'] = rr['stats']['continuations'][0]
    # a DEADLINE refusal of the exact route is final (no PAC after the budget)
    def fail_deadline(plan, deadline): raise support.ResourceStop('DEADLINE', {})
    core._discover_component = fake_discover; core._execute_component = fail_deadline; forest.solve = no_forest
    try:
        try: solve.solve(chain(5), time.monotonic() + 30, 'H1_HYBRID', 'q9b'); raise AssertionError('deadline refusal continued')
        except support.ResourceStop as e: assert e.reason == 'DEADLINE'
    finally: core._discover_component = orig_discover; core._execute_component = orig_execute; forest.solve = orig_forest
    out['deadline_refusal_is_final'] = True
    # ZERO_EVIDENCE terminal honours the deadline through the NEW solve/worker path (controlled clock as in the review control)
    real = time.monotonic; calls_c = []
    def clock():
        t = 0.0 if len(calls_c) < 3 else 1.0; calls_c.append(t); return t
    time.monotonic = clock
    try:
        try: solve.solve({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, 0.5, 'P1_PAC_CONDITIONAL', 'q9c'); kind = 'returned'
        except solve.ZeroEvidence: kind = 'ZERO_EVIDENCE'
        except support.ResourceStop as e: kind = e.reason
    finally: time.monotonic = real
    # the worker converts a ZeroEvidence raised after the deadline into DEADLINE; solve itself may raise ZeroEvidence (proof) or DEADLINE -- both are acceptable only if the WORKER classifies late proofs as DEADLINE:
    D = TMP / 'q9'; D.mkdir(exist_ok=True); write_uai({'cards': [2], 'factors': [{'scope': (0,), 'values': [F(0), F(0)]}], 'evidence': {}}, D / 'z.uai'); outp = D / 'w.json'
    subprocess.run([sys.executable, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() - 1.0), '--seed', 's', '--nonce', 'n', '--budget', '0'], check=True, cwd=CODE)
    wz = json.load(open(outp)); assert wz['outcome'] == 'DEADLINE' and wz['guarantee_type'] == 'NONE' and wz.get('late_proof') or wz['outcome'] == 'DEADLINE', wz
    subprocess.run([sys.executable, os.path.join(HERE, 'worker.py'), '--input', str(D / 'z.uai'), '--output', str(outp), '--arm', 'P1_PAC_CONDITIONAL', '--deadline', str(time.monotonic() + 10), '--seed', 's', '--nonce', 'n', '--budget', '10'], check=True, cwd=CODE)
    wz2 = json.load(open(outp)); assert wz2['outcome'] == 'PROVED_ZERO_EVIDENCE' and wz2['guarantee_type'] == 'DETERMINISTIC' and wz2.get('zero_evidence_proof')
    out['zero_evidence_terminal_deadline_checked_in_worker'] = dict(late=wz['outcome'], timely=wz2['outcome'], solve_level_controlled_clock=kind)
    # typed RANGE at source conversion is a typed stop (contrib / template), classified NUMERICAL_RANGE_OR_PRECISION by the worker mapping
    bad = {'cards': [2, 2], 'factors': [{'scope': (0, 1), 'values': [F(1), F(1, 10 ** 1000), F(1), F(1)]}], 'evidence': {}}
    for fn in (lambda: contrib.cell_kernel(bad, {}, deadline=time.monotonic() + 10), lambda: engine.Template(bad, [], [0, 1], deadline=time.monotonic() + 10)):
        try: fn(); raise AssertionError('RANGE not raised')
        except contrib.CellStop as e: assert e.kind == 'RANGE'
    import worker as W_; assert W_.OUTCOME_OF_STOP['RANGE'] == 'NUMERICAL_RANGE_OR_PRECISION'; out['source_conversion_range_is_typed'] = True
    # factorless component through every arm
    for arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
        rr = solve.solve({'cards': [2], 'factors': [], 'evidence': {}}, time.monotonic() + 10, arm, 'e'); assert rr['guarantee_type'] == 'DETERMINISTIC' and rr['points'] == [[F(1, 2), F(1, 2)]]
    out['factorless_model_all_arms'] = True
    import cex_executor as X; m3 = {'cards': [1024], 'factors': [{'scope': (0,), 'values': [F(1 << 50000)] * 1024}, {'scope': (), 'values': [F(0)]}], 'evidence': {}}; t = time.monotonic()
    try: X.execute(m3, [0], deadline=t + 0.05); raise AssertionError('late ZERO_EVIDENCE accepted')
    except X.Stop as ex: assert ex.kind == 'DEADLINE'
    out['frozen_executor_early_zero_honours_deadline'] = True; return out


def q10_existing():
    out = {}
    ctl = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'PAC_EMPIRICAL_2026-11-12', 'review_items', 'host_budget_control_v14.py')
    if os.path.exists(ctl):
        p = subprocess.run([sys.executable, ctl, os.path.join(NEWARM, 'cex_executor.py')], capture_output=True, text=True); r = json.loads(p.stdout)
        out['host_budget_control_on_candidate'] = {k: r[k] for k in ('host_budget_peak_bytes', 'traced_peak_bytes', 'restricted_list_1024')}
    out['claim'] = 'NARROWED (cex_executor docstrings and certificate text): HostBudget is an accounting of the named containers, not a proven upper bound; the only whole-worker bound is the sampled process-tree RSS policy'
    # the frozen executor's own suite in an ISOLATED COPY of cex/newarm + cex/gate_controls.py (never rewrites the historical CEX_QUALIFICATION.json / gate_controls_v3)
    iso = TMP / 'q10_iso'; (iso / 'cex').mkdir(parents=True); shutil.copytree(NEWARM, iso / 'cex' / 'newarm', ignore=shutil.ignore_patterns('__pycache__', 'native_cache', '*.dylib', '*.so'))
    for f in sorted(os.listdir(os.path.join(CODE, 'cex'))):
        if f.endswith('.py'): shutil.copy2(os.path.join(CODE, 'cex', f), iso / 'cex' / f)          # every cex/*.py helper the frozen suite's controls import (gate_controls, compare_campaigns, locked_plan, ...)
    if os.path.isdir(os.path.join(CODE, 'cex', 'baseline')): shutil.copytree(os.path.join(CODE, 'cex', 'baseline'), iso / 'cex' / 'baseline', ignore=shutil.ignore_patterns('__pycache__', 'native_cache', '*.dylib', '*.so'))   # locked_plan's baseline arm imports
    rd = iso / 'runs' / 'mdi_2026-10-28' / 'CERTIFIED_EXECUTOR_2026-11-11'; rd.mkdir(parents=True)
    src_rd = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CERTIFIED_EXECUTOR_2026-11-11'); shutil.copytree(os.path.join(src_rd, 'campaign_specs'), rd / 'campaign_specs'); (rd / 'campaigns').mkdir()
    for camp in ('baseline_20s_all46', 'newarm_20s_all46_v13'):
        shutil.copytree(os.path.join(src_rd, 'campaigns', camp), rd / 'campaigns' / camp)          # the complete saved campaign (receipts, environment, per-case outputs) the positive gate control re-gates
    for f in os.listdir(src_rd):
        if f.endswith('.json'): shutil.copy2(os.path.join(src_rd, f), rd / f)
    q = subprocess.run([sys.executable, str(iso / 'cex' / 'newarm' / 'cex_qualification.py')], capture_output=True, text=True, cwd=str(iso / 'cex' / 'newarm')); lines = [l for l in q.stdout.splitlines() if l.startswith('{')]
    assert q.returncode == 0 and lines, q.stderr[-800:]; qq = json.loads(lines[-1]); assert qq['all_pass'], qq
    out['frozen_executor_qualification_isolated_copy'] = dict(passed=qq['passed'], total=qq['total'], controls=len(qq['controls']), isolated_dir=str(iso)); out['historical_records_untouched'] = True; return out


def q11_diagnostic_coverage():
    rng = random.Random(5); miss = 0; cert = 0; tot = 0; t0 = time.monotonic(); rows = []
    pol = dict(engine.POLICY); pol['epsilon'] = F(1, 20)
    for trial in range(60):
        m = rand_model(rng, 3, 5, 3); n = len(m['cards']); cards = m['cards']; bf = core.brute_force(m); K = sum(cards); mode = 'conditional' if trial % 3 == 0 else 'point'
        r = engine.run_component(m, time.monotonic() + 8, 1000 + trial, 2000 + trial, mode, F(1, 20), F(1, 20), K, 3 * 2 ** 30, 0, pol, fixed_cutset=[0], fixed_order=[v for v in range(1, n)], max_trials=2000000, resolve=False); tot += 1; R['executions'] += 1
        okc = None
        if r['status'] == 'PUBLISHED' and r['guarantee'] == 'PAC':
            cert += 1; okc = all(lo <= bf[v][s] <= hi for v in range(n) for s, (lo, hi) in enumerate(r['intervals'][v])); miss += (not okc); R['coordinates_checked'] += K
        rows.append(dict(trial=trial, mode=mode, status=r['status'], guarantee=r['guarantee'], trials=r['stats']['trials_completed'], contains_truth=okc))
    # diagnostic criterion over ATTEMPTED runs: P(bad publication) <= 0.1 per run -> misses ~ Binomial(tot, <= 0.1); flag if misses exceed the one-sided 1e-3 quantile of Binomial(60, 0.1) (= 13); bug detection only
    assert miss <= 13, (miss, cert, tot)
    return dict(attempted=tot, published_pac=cert, misses=miss, delta_joint='0.1', criterion='misses <= 13 = one-sided 1e-3 quantile of Binomial(60, 0.1) over ATTEMPTED runs', note='bug detection only; cannot verify 1e-6', wall_s=round(time.monotonic() - t0, 1), rows=rows)


def q12_exact_closure_partial_cover():
    out = {}; rng = random.Random(12)
    # empty-cutset closure: one contraction publishes deterministically, exactly one resolved cell, no second kernel call
    m = chain(13, 3); calls = {'n': 0}; orig = engine.kernel_cell
    def counting(*a, **k): calls['n'] += 1; return orig(*a, **k)
    engine.kernel_cell = counting
    try: r = engine.run_component(m, time.monotonic() + 30, 0, 1, 'conditional', F(1, 2 * 10 ** 6), F(1, 2 * 10 ** 6), 26, 3 * 2 ** 30, 0, fixed_cutset=[], fixed_order=list(range(13)), max_trials=4)
    finally: engine.kernel_cell = orig
    assert r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC' and r['stats']['route'] == 'exact_cover_complete' and calls['n'] == 1 and r['stats']['resolved_cells'] == 1 and all(lo <= F(1, 2) <= hi for row in r['intervals'] for lo, hi in row)
    out['empty_cutset_closure_one_contraction'] = float(max(hi - lo for row in r['intervals'] for lo, hi in row))
    # forced P1 on the chain: two cells cover the model -> deterministic
    r = engine.run_component(m, time.monotonic() + 30, 0, 1, 'conditional', F(1, 2 * 10 ** 6), F(1, 2 * 10 ** 6), 26, 3 * 2 ** 30, 0, max_trials=8, forced=True)
    assert r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC' and r['stats']['resolved_cells'] == 2 and r['stats']['trials_completed'] == 2; out['forced_cutset_complete_cover_2_cells'] = True
    # generic generated models: complete covers publish deterministically and equal the truth; partial covers conserve mass
    comp = 0; part = 0
    for trial in range(25):
        m = rand_model(rng, 3, 5, 3, zero_p=0.15); n = len(m['cards']); Z, N = enum_truth(m)
        if Z == 0: continue
        cut = rng.sample(range(n), rng.randint(1, n - 1))
        r = engine.run_component(m, time.monotonic() + 30, trial, trial + 1, 'conditional', F(1, 10), F(1, 10), sum(m['cards']), 3 * 2 ** 30, 0, fixed_cutset=cut, fixed_order=[v for v in range(n) if v not in cut], max_trials=100000); R['executions'] += 1
        if r['status'] == 'PUBLISHED' and r['guarantee'] == 'DETERMINISTIC':
            truth = [[N[v][s] / Z for s in range(m['cards'][v])] for v in range(n)]
            assert all(lo <= truth[v][s] <= hi for v in range(n) for s, (lo, hi) in enumerate(r['intervals'][v])), 'exact cover publication misses the truth'; comp += 1
        else:
            S = r['stats']['sufficient_statistics']; U = F(S['U_root']); A_lo = F(S['A_exact_lo']); A_hi = F(S['A_exact_hi']); Ut = F(r['stats']['U_t_over_U_root']) * U
            assert A_lo <= Z <= A_hi + Ut, 'partial cover: resolved mass + residual envelope does not enclose Z'; part += 1
    out['generic_complete_covers'] = comp; out['generic_partial_covers_conserved'] = part
    # the A0/A1 ablation holds the residual region fixed (resolve OFF): no resolution in either mode
    m = chain(6, 2)
    for mode in ('point', 'conditional'):
        r = engine.run_component(m, time.monotonic() + 10, 1, 2, mode, F(1, 10), F(1, 10), 12, 3 * 2 ** 30, 0, fixed_cutset=[0, 2], fixed_order=[1, 3, 4, 5], max_trials=50, resolve=False); assert r['stats']['resolved_cells'] == 0
    out['ablation_residual_region_fixed'] = True; return out


if __name__ == '__main__':
    group('Q1_identity_and_gate_negative_controls', q1_identity_gate); group('Q2_exact_cell_oracle', q2_masses); group('Q3_fixed_laws_exhaustive_plus_resolution_histories_and_production_draw', q3_fixed_laws_and_resolution); group('Q4_support_envelopes_production_guard', q4_envelopes); group('Q5_actual_sampling_backend', q5_sampling_law); group('Q6_confidence_arithmetic_inversion_underflow', q6_confidence); group('Q7_numerical_publication_actual_pac', q7_publication); group('Q9_resource_selection_and_continuation', q9_resource_selection_continuation); group('Q10_existing_defects_isolated', q10_existing); group('Q11_diagnostic_coverage_delta_0.1_attempted_runs', q11_diagnostic_coverage); group('Q12_exact_closure_and_partial_cover', q12_exact_closure_partial_cover)
    R.update(passed=passed, total=total, all_pass=passed == total, Q8='candidate validation (theory section 9) not implemented; recorded', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), candidate_sources={f: hashlib.sha256(open(os.path.join(HERE, f), 'rb').read()).hexdigest() for f in sorted(os.listdir(HERE)) if f.endswith('.py')}, temp_dir=str(TMP))
    json.dump(R, open(os.path.join(HERE, 'PAC_QUALIFICATION.json'), 'w'), indent=1, default=str); print(json.dumps({'passed': passed, 'total': total, 'executions': R['executions'], 'coordinates': R['coordinates_checked'], 'all_pass': R['all_pass']})); sys.exit(0 if R['all_pass'] else 1)
