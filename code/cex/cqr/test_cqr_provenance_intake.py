#!/usr/bin/env python3
"""Controls for the provenance / intake repairs of 16 Nov 2026 (CQR-09 kernel freeze, CQR-10 projected counting, constructed schedule, balanced
arm blocks, allowance ceiling). Plain python: one line per test, exit 1 on any failure. Never modifies a real kernel / record file: the freeze
witness works on a temporary COPY. Run: cd code && .venv/bin/python cex/cqr/test_cqr_provenance_intake.py"""
import os, sys, json, shutil, tempfile, hashlib, traceback
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import campaign as C                       # binds the baseline registry / shared reader first, then the CQR modules
import kernel_identity as KI, schedule as SCHED, wcnf
R = C.R
RESULTS = []


def test(name):
    def deco(fn):
        try:
            detail = fn(); RESULTS.append((name, True, detail)); print('PASS %-44s %s' % (name, detail or ''))
        except Exception as ex:
            RESULTS.append((name, False, str(ex))); print('FAIL %-44s %s' % (name, ''.join(traceback.format_exception_only(type(ex), ex)).strip()[:300]))
        return fn
    return deco


def sha(b): return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------------------------------------------------------------- (1) kernel freeze
NEWARM_COPY = {'newarm_cex': ('libcex_kernel.dylib', 'cex_build.json', 'cex_executor.py'), 'newarm_stream': ('libstream_kernel.so', 'stream_build.json', 'stream_float.py')}


def _temp_newarm_copy():
    """a temporary COPY of the newarm kernel pair (binary + record) for cex and stream; the real files are never touched"""
    td = tempfile.mkdtemp(prefix='ki_')
    for tag, (b, r, _l) in NEWARM_COPY.items():
        shutil.copy2(os.path.join(CODE, 'cex', 'newarm', b), os.path.join(td, b)); shutil.copy2(os.path.join(CODE, 'cex', 'newarm', r), os.path.join(td, r))
    return td


def _replace_pair(td, binary, record, new_bytes):
    """the reviewer's witness: replace BOTH the binary and the record, consistent with each other, source_sha256 unchanged (bytes are never executed)"""
    rec = json.load(open(os.path.join(td, record))); open(os.path.join(td, binary), 'wb').write(new_bytes)
    rec['binary_sha256'] = sha(new_bytes); json.dump(rec, open(os.path.join(td, record), 'w'))


@test('kernel_freeze_witness_refused')
def _():
    td = _temp_newarm_copy(); frozen = KI.collect(td, NEWARM_COPY)
    assert KI.failures_vs_frozen(frozen, KI.collect(td, NEWARM_COPY), ['H1_HYBRID']) == [], 'unchanged copy must pass'
    src_before = json.load(open(os.path.join(td, 'cex_build.json')))['source_sha256']
    _replace_pair(td, 'libcex_kernel.dylib', 'cex_build.json', b'review-only preflight B, never loaded')
    assert json.load(open(os.path.join(td, 'cex_build.json')))['source_sha256'] == src_before
    cur = KI.collect(td, NEWARM_COPY); assert cur['newarm_cex']['record_binary_sha256'] == cur['newarm_cex']['binary_sha256'], 'replacement is internally consistent (the old check passed it)'
    fails = KI.failures_vs_frozen(frozen, cur, ['H1_HYBRID'])
    assert any('BINARY_CHANGED' in f for f in fails) and any('RECORD_CHANGED' in f for f in fails), fails
    assert KI.failures_vs_frozen(frozen, cur, ['N1_CQR', 'G0_CQR']) == [], 'CQR arms load nothing native'
    shutil.rmtree(td); return '%d failures for H1_HYBRID (BINARY_CHANGED + RECORD_CHANGED), 0 for N1/G0' % len(fails)


@test('kernel_freeze_distinct_messages')
def _():
    td = _temp_newarm_copy(); frozen = KI.collect(td, NEWARM_COPY)
    os.remove(os.path.join(td, 'libcex_kernel.dylib')); f1 = KI.failures_vs_frozen(frozen, KI.collect(td, NEWARM_COPY), ['P1_PAC_CONDITIONAL']); assert any('BINARY_ABSENT' in f for f in f1), f1
    shutil.copy2(os.path.join(CODE, 'cex', 'newarm', 'libcex_kernel.dylib'), os.path.join(td, 'libcex_kernel.dylib')); os.remove(os.path.join(td, 'cex_build.json'))
    f2 = KI.failures_vs_frozen(frozen, KI.collect(td, NEWARM_COPY), ['P1_PAC_CONDITIONAL']); assert any('RECORD_ABSENT' in f for f in f2), f2
    shutil.copy2(os.path.join(CODE, 'cex', 'newarm', 'cex_build.json'), os.path.join(td, 'cex_build.json')); open(os.path.join(td, 'libstream_kernel.so'), 'ab').write(b'\0')
    f3 = KI.failures_vs_frozen(frozen, KI.collect(td, NEWARM_COPY), ['P1_PAC_CONDITIONAL']); assert any('newarm_stream: BINARY_CHANGED' in f for f in f3) and any('RECORD_INCONSISTENT' in f for f in f3), f3
    shutil.rmtree(td); return 'BINARY_ABSENT / RECORD_ABSENT / stream BINARY_CHANGED+RECORD_INCONSISTENT'


@test('kernel_valid_binary_identity_control')
def _():
    # LIMITED CLAIM: the real on-disk newarm / b0 / h4 / libdai artifacts match their own freshly collected identity and every build record's inner claim equals
    # the binary on disk. Nothing is executed here; this says the frozen identity is well-formed, not that the binaries compute anything correctly.
    real = KI.collect(CODE); arms = ['H1_HYBRID', 'B0_FROZEN_V14', 'LIBDAI_EXACT', 'H4_NATIVE_control', 'N1_CQR']
    fails = KI.failures_vs_frozen(real, KI.collect(CODE), arms); assert fails == [], fails
    for tag in ('newarm_cex', 'newarm_stream', 'b0_frozen_v14_cex', 'b0_frozen_v14_stream'):
        assert real[tag]['binary_sha256'] and real[tag]['record_sha256'] and real[tag]['record_binary_sha256'] == real[tag]['binary_sha256'], tag
    return 'on-disk identity consistent for %s' % ','.join(sorted(KI.needed_tags(arms)))


@test('kernel_receipt_failures')
def _():
    real = KI.collect(CODE); good = dict(certificate=dict(build=dict(binary_sha256=real['newarm_cex']['binary_sha256'], loaded_binary_path='/x/libcex_kernel.dylib', schedule_id='s')))
    assert KI.receipt_failures(real, good, 'H1_HYBRID') == []
    bad = dict(stats=dict(components=[dict(build=dict(binary_sha256='00' * 32, loaded_binary_path='/x/libstream_kernel.so'))]))
    f = KI.receipt_failures(real, bad, 'H1_HYBRID'); assert len(f) == 1 and 'newarm_stream' in f[0], f
    assert KI.receipt_failures(real, bad, 'N1_CQR') == []
    return 'loaded-binary provenance compared to the frozen identity'


def _tiny_uai(td):
    p = os.path.join(td, 'tiny.uai'); open(p, 'w').write('MARKOV\n2\n2 2\n1\n2 0 1\n\n4\n1 2 3 4\n'); return p


def _manifest_dict(RD, cells, ki):
    inv = R.full_inventory(CODE)
    return dict(schema=C.MANIFEST_SCHEMA, candidate_artifact_hashes=inv, cells=cells, kernel_identity=ki)


@test('campaign_run_refuses_replaced_pair')
def _():
    # the reviewer's witness against the ACTUAL campaign.run startup: the manifest froze identity A for newarm (binary + record), the disk now holds a different
    # consistent pair; source inventory unchanged -> START REFUSED (previously: startup succeeded and wrote CAMPAIGN_START). Simulated by freezing a manifest whose
    # newarm identity differs from the real disk (equivalent to replacing the disk pair after freeze) -- the real files are never modified.
    td = tempfile.mkdtemp(prefix='run_'); ki = KI.collect(CODE); fakeb = sha(b'review-only preflight A, never loaded')
    ki['newarm_cex'] = dict(ki['newarm_cex'], binary_sha256=fakeb, record_binary_sha256=fakeb, record_sha256=sha(b'record A'))
    man = _manifest_dict(td, [dict(arm='H1_HYBRID', cohort='x', case_id='c', budget_s=1.0, replicate=0, kind='legacy_primary', cell_id='0' * 16, order_index=0)], ki)
    json.dump(man, open(os.path.join(td, 'CAMPAIGN_MANIFEST.json'), 'w'))
    try:
        C.run(td, max_cells=0); raise AssertionError('startup must be refused')
    except SystemExit as ex:
        msg = str(ex); assert msg.startswith('START REFUSED:') and 'BINARY_CHANGED' in msg and 'RECORD_CHANGED' in msg, msg
    assert not os.path.exists(os.path.join(td, 'CAMPAIGN_START.json')), 'a refused START must leave no CAMPAIGN_START binding'
    # control: the true identity starts (max_cells=0 -> nothing launched) and a manifest without the field is refused
    td2 = tempfile.mkdtemp(prefix='run_'); json.dump(_manifest_dict(td2, man['cells'], KI.collect(CODE)), open(os.path.join(td2, 'CAMPAIGN_MANIFEST.json'), 'w'))
    assert C.run(td2, max_cells=0) == 0 and os.path.exists(os.path.join(td2, 'CAMPAIGN_START.json'))
    td3 = tempfile.mkdtemp(prefix='run_'); m3 = _manifest_dict(td3, man['cells'], None); json.dump(m3, open(os.path.join(td3, 'CAMPAIGN_MANIFEST.json'), 'w'))
    try:
        C.run(td3, max_cells=0); raise AssertionError('manifest without kernel_identity must be refused')
    except SystemExit as ex: assert 'no frozen kernel_identity' in str(ex), str(ex)
    for t in (td, td2, td3): shutil.rmtree(t)
    return 'START REFUSED on replaced pair; true identity starts; missing field refused'


# ------------------------------------------------------------------------------------------------------------------------- (2) wcnf intake
PMC_CONTROL = 'c t pmc\nc p show 1 0\np cnf 2 1\n1 0\n'


def _z_of(cnf_text):
    td = tempfile.mkdtemp(prefix='wcnf_'); cp = os.path.join(td, 'a.cnf'); open(cp, 'w').write(cnf_text); up = os.path.join(td, 'a.uai')
    meta, clauses, weights = wcnf.scan_wcnf(cp, keep_clauses=True); side = wcnf.convert(cp, up, name='a')
    model, info = C.core.read_uai(up); z = wcnf.uai_partition_bruteforce(model); zd = wcnf.wmc_direct(meta['n_vars'], clauses, weights)
    shutil.rmtree(td); return Fraction(str(z)), Fraction(str(zd)), meta


@test('wcnf_pmc_control_refused')
def _():
    td = tempfile.mkdtemp(prefix='wcnf_'); cp = os.path.join(td, 'pmc.cnf'); open(cp, 'w').write(PMC_CONTROL)
    meta = wcnf.scan_wcnf(cp); assert meta['declared_type'] == 'pmc' and meta['show_lines'] == 1 and meta['count_semantics_status'] == 'REFUSED_PROJECTED_COUNT_SEMANTICS', meta['count_semantics_status']
    try:
        wcnf.convert(cp, os.path.join(td, 'pmc.uai'), name='pmc'); raise AssertionError('must refuse')
    except ValueError as ex: assert str(ex).startswith('REFUSED_PROJECTED_COUNT_SEMANTICS'), str(ex)
    shutil.rmtree(td); return 'declared_type=pmc show_lines=1 -> REFUSED_PROJECTED_COUNT_SEMANTICS'


@test('wcnf_wmc_same_clauses_accepted_Z2')
def _():
    z, zd, meta = _z_of('c t wmc\np cnf 2 1\n1 0\n'); assert meta['declared_type'] == 'wmc' and meta['show_lines'] == 0 and meta['count_semantics_status'] == 'OK'
    assert z == 2 and zd == 2, (z, zd)
    z2, zd2, meta2 = _z_of('c t mc\np cnf 2 1\n1 0\n'); assert meta2['declared_type'] == 'mc' and z2 == 2
    z3, zd3, meta3 = _z_of('p cnf 2 1\n1 0\n'); assert meta3['declared_type'] is None and z3 == 2
    return 'wmc / mc / absent type accepted; Z = 2 (projected count would be 1)'


@test('wcnf_show_line_alone_refused')
def _():
    td = tempfile.mkdtemp(prefix='wcnf_'); cp = os.path.join(td, 'show.cnf'); open(cp, 'w').write('c t wmc\nc p show 1 0\np cnf 2 1\n1 0\n')
    meta = wcnf.scan_wcnf(cp); assert meta['declared_type'] == 'wmc' and meta['show_lines'] == 1 and meta['count_semantics_status'] == 'REFUSED_PROJECTED_COUNT_SEMANTICS'
    try:
        wcnf.convert(cp, os.path.join(td, 'show.uai'), name='show'); raise AssertionError('must refuse')
    except ValueError as ex: assert 'REFUSED_PROJECTED_COUNT_SEMANTICS' in str(ex)
    cp2 = os.path.join(td, 'pwmc.cnf'); open(cp2, 'w').write('c t pwmc\np cnf 2 1\n1 0\n'); assert wcnf.scan_wcnf(cp2)['count_semantics_status'] == 'REFUSED_PROJECTED_COUNT_SEMANTICS'
    shutil.rmtree(td); return "'c p show' alone and 'c t pwmc' alone both refused"


# ------------------------------------------------------------------------------------------------------------------------- (3) schedule
@test('schedule_deterministic_and_covering')
def _():
    cards = [2, 3, 2, 2, 3, 2, 2, 2, 3, 2, 2, 2]; salt = 'salt-A'
    for i in range(96):
        a = SCHED.constructed_schedule(i, cards, salt, 'slot%d' % i); b = SCHED.constructed_schedule(i, list(cards), salt, 'slot%d' % i)
        assert a == b and a['status'] == 'RESOLVED' and a['query_sha256'] == SCHED.qsha(a['query_spec'])
        assert a['query_kind'] == SCHED.KINDS[(i % 8) % 4] and a['evidence_regime'] == SCHED.EVIDENCE[(i % 8) // 4]
        assert (a['evidence'] == {}) == (a['evidence_regime'] == 'no_evidence'); assert all(int(v) not in {int(e) for e in a['evidence']} for q in a['query_spec']['queries'] for v in (q.get('variables') or list(q.get('assign') or {}) or ([q['variable']] if 'variable' in q else [])))
    assert SCHED.constructed_schedule(3, cards, 'salt-B', 'slot3') != SCHED.constructed_schedule(3, cards, salt, 'slot3')
    assert SCHED.coverage(range(96)) and not SCHED.coverage(list(range(95)) + [0])
    d = SCHED.constructed_schedule(0, None, salt, 'x'); assert d['status'] == SCHED.DEFERRED and d['query_spec'] is None, d       # slot 0 = selected_singleton x no_evidence: needs cards
    e = SCHED.constructed_schedule(4, None, salt, 'x'); assert e['status'] == SCHED.DEFERRED and e['evidence_regime'] == 'nontrivial_evidence'
    g = SCHED.constructed_schedule(1, None, salt, 'x'); assert g['query_kind'] == 'all_singletons' and g['evidence_regime'] == 'no_evidence' and g['status'] == 'RESOLVED', g
    return 'deterministic over 96 slots; salt-sensitive; coverage 8x per family; cards-free all_singletons x no_evidence resolves'


@test('schedule_check_flags_tamper')
def _():
    cards = [2] * 16; salt = 's'
    cells = [dict(cohort='constructed', slot_index=i, slot_id='c%d' % i, cards=cards, salt=salt, schedule=SCHED.constructed_schedule(i, cards, salt, 'c%d' % i)) for i in range(16)]
    ok = SCHED.check_schedule(cells); assert ok['ok'] and ok['checked'] == 16 and ok['resolved'] == 16, ok
    assert cells[6]['schedule']['query_kind'] == 'selected_pair_joint' and cells[12]['schedule']['evidence_regime'] == 'nontrivial_evidence'
    cells[6]['schedule']['query_spec']['queries'][0] = dict(kind='all_singletons'); cells[12]['schedule']['evidence_regime'] = 'no_evidence'
    bad = SCHED.check_schedule(cells); assert not bad['ok'] and {m['slot'] for m in bad['mismatches']} == {'c6', 'c12'}, bad['mismatches']
    return 'tampered query_spec (c6) and evidence_regime (c12) flagged; 14 others clean'


# ------------------------------------------------------------------------------------------------------------------------- (4) ordering / (5) ceiling
def _dev_manifest(plan, budgets):
    td = tempfile.mkdtemp(prefix='man_'); mp = _tiny_uai(td); coh = sorted(R.COHORTS, key=lambda k: R.COHORTS[k]['order'])[0]
    rows = [C.make_row(coh, 'tiny', mp)]; p = C.manifest(td, rows, dev=True, budgets=budgets, plan={coh: plan}, root_seed='00' * 16)
    return json.load(open(p)), td


@test('ordering_balanced_arm_blocks')
def _():
    abl = sorted(a for a in R.CQR_ARMS if a not in ('N1_CQR', 'G0_CQR'))[:1]
    man, td = _dev_manifest([('N1_CQR', 2), ('G0_CQR', 2)] + [(a, 2) for a in abl], [1.0])
    got = [(c['arm'], c['replicate']) for c in man['cells']]
    exp = [('N1_CQR', 0), ('G0_CQR', 0)] + [(a, 0) for a in abl] + [(a, 1) for a in abl] + [('G0_CQR', 1), ('N1_CQR', 1)]
    assert got == exp, got
    assert 'BALANCED ARM BLOCKS' in man['ordering_rule'] and 'predeclared balanced blocks' in man['ordering_rule']
    man3, td3 = _dev_manifest([('N1_CQR', 3), ('G0_CQR', 3)], [1.0]); got3 = [(c['arm'], c['replicate']) for c in man3['cells']]
    assert got3 == [('N1_CQR', 0), ('G0_CQR', 0), ('G0_CQR', 1), ('N1_CQR', 1), ('N1_CQR', 2), ('G0_CQR', 2)], got3
    shutil.rmtree(td); shutil.rmtree(td3); return 'order %s' % got


@test('ceiling_no_second_matrix')
def _():
    man, td = _dev_manifest([('N1_CQR', 2), ('G0_CQR', 1)], [1.0, 2.0]); ce = man['ceiling']; n = man['counts']['cells']; nominal = ce['scored_matrix_seconds']
    assert ce['total_ceiling_seconds'] == 18000 + nominal + 5 * n + ce['verification_stage_seconds'], ce
    assert 'second matrix is reserved' not in ce['formula'] and 'no implicit second-matrix contingency is reserved' in ce['formula']
    fc = ce['formula_change_2026-11-16']; assert fc['old_total_seconds'] > fc['new_total_seconds'] and 'second matrix is reserved' in fc['old_formula']
    assert man['kernel_identity'] and set(man['kernel_identity']) == set(KI.ARTIFACTS) and man['kernel_identity_version'] == KI.VERSION
    shutil.rmtree(td); return 'total = 18000 + %d + 5 x %d + %d; manifest carries kernel_identity (%d tags)' % (nominal, n, ce['verification_stage_seconds'], len(man['kernel_identity']))


if __name__ == '__main__':
    bad = [r for r in RESULTS if not r[1]]
    print('%d/%d passed' % (len(RESULTS) - len(bad), len(RESULTS)))
    sys.exit(1 if bad else 0)
