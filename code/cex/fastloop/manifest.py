"""PINNED DEVELOPMENT MANIFEST of the fast loop: materializes every task's model / evidence / query BYTES under a DEVELOPMENT id (never a held-out campaign input; archived admission
query files are NOT trusted for a family's intended query: the CURRENT generator's query spec is materialized and its bytes pinned), records sha256 of each file, the arms, budgets,
tolerances, seeds, the comparator policy per row, the expected mechanism and the block. `calibrate` runs the declared SIZE LADDER of the change-specific pair on the accepted baseline
(all attempts retained) and pins the first rung whose candidate run is beyond trivial exact completion. Usage:
  manifest.py materialize --baseline BUILD_DIR --out MANIFEST_DIR          (writes MANIFEST_DIR/tasks/* + MANIFEST_DIR/DEV_MANIFEST.json; refuses to overwrite)"""
import os, sys, json, hashlib, time, argparse
from fractions import Fraction as F
LEGACY = '/Users/adis/Workspace/pgm-records/docs/handoff-received-2026-11-11-certified-executor/packet/inputs'
DEV_NORMALIZER = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/CQR_2026-11-15/dev_inputs/normalizer/M06_n8_Z_s11.uai'
DET = dict(mode='DETERMINISTIC_EPS', epsilon='1/200', delta='0'); PAC = dict(mode='PAC_EPS', epsilon='1/200', delta='1/1000000'); PAC_QUAL = dict(mode='PAC_EPS', epsilon='1/10', delta='1/10')
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def _uai(path, cards, fs):
    toks = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(fs))]
    for sc, vals in fs: toks.append(' '.join(map(str, [len(sc)] + list(sc))))
    for sc, vals in fs: toks.extend([str(len(vals)), ' '.join(str(v) for v in vals)])
    open(path, 'w').write('\n'.join(toks) + '\n'); return path
def _sprinkled(seed, n, nf, ar, big=10, small=1, holes=1):
    """the suite's C16 ratio-PAC fixture generator (copied verbatim from qualification._sprinkled; pinned here so the harness does not import the suite)"""
    import random; rng = random.Random(seed); fs = []; cover = list(range(n)); rng.shuffle(cover); k = 0
    for i in range(nf):
        if k + ar <= n: sc = tuple(sorted(cover[k:k + ar])); k += ar
        else: sc = tuple(sorted(rng.sample(range(n), ar)))
        vals = [big] * (2 ** ar)
        for h in rng.sample(range(2 ** ar), holes): vals[h] = small
        fs.append((sc, vals))
    return [2] * n, fs
def bind(mp):
    ev = mp + '.evid'; qp = mp + '.query.json'
    return dict(model=mp, model_sha256=sha(mp), evidence_sha256=(sha(ev) if os.path.exists(ev) else None), query_sha256=(sha(qp) if os.path.exists(qp) else None), query_contract=('explicit query spec' if os.path.exists(qp) else 'all original singletons (legacy implicit contract; PAC_EPS 1/200 1e-6)'))

def materialize(baseline, out):
    sys.path.insert(0, os.path.join(baseline, 'cex', 'cqr')); sys.path.insert(0, os.path.join(baseline, 'cex', 'newarm')); import generators as G, task as TK
    T = os.path.join(out, 'tasks'); os.makedirs(T); rows = []; gen_sha = sha(os.path.join(baseline, 'cex', 'cqr', 'generators.py'))
    def row(rid, block, mp, arm_c, comparator, expected, budget, spec_note=None, **meta):
        TK.load_task(mp)                                                                   # every pinned task parses under the baseline (INVALID_TASK fixtures are flagged, not loaded)
        rows.append(dict(id=rid, block=block, budget_s=budget, candidate_arm=arm_c, comparator=comparator, expected_mechanism=expected, spec=spec_note, **bind(mp), **meta))
    def copy_legacy(name):
        d = os.path.join(T, 'legacy_' + name); os.makedirs(d); mp = os.path.join(d, 'model.uai')
        for ext in ('', '.evid'): open(mp + ext, 'wb').write(open(os.path.join(LEGACY, name + '.uai' + ext), 'rb').read())
        return mp
    # ---------------- block 1: existing structural capability (accepted-N1 comparator; legacy implicit contract preserved)
    for name, bud in (('ASIA', 3.0), ('ALARM', 3.0), ('BN_31', 10.0), ('DBN_11', 5.0)):
        row('FL_SENT_' + name, 'structural_sentinel', copy_legacy(name), 'N1_CQR', dict(kind='baseline_N1', arm='N1_CQR'), 'structural (original or reduced); production success', bud, coverage_required=['structural_publication'], spec_note='legacy packet %s.uai + .evid; all original singletons; PAC_EPS 1/200 1e-6 (the campaign contract)' % name, source='certified-executor packet (public legacy input; EXPOSED in every campaign)')
    # ---------------- block 2: contract correctness
    d = os.path.join(T, 'FL_C35_mixed_alias'); os.makedirs(d); mp = _uai(os.path.join(d, 'model.uai'), [2], [([0], ['1', '3'])])
    json.dump(dict(queries=[dict(kind='joint', assign={'0': 1}), dict(kind='parity', variables=[0], bit=1), dict(kind='singleton', variable=0, state=1), dict(kind='singleton', variable=0, state=0), dict(kind='table', table=dict(name='ind', kind='expectation', f=dict(scope=[0], values=['0', '1']), output=dict(kind='table')))], **DET), open(mp + '.query.json', 'w'))
    row('FL_C35_mixed_alias', 'contract', mp, 'N1_CQR', dict(kind='baseline_N1', arm='N1_CQR'), 'structural_original on a table-derived simplex family of mixed presentations', 5.0, coverage_required=['structural_publication'], spec_note='[1,3] model; joint / parity / singleton x2 / general-table-marker presentations of P(X0=1) and P(X0=0); DETERMINISTIC_EPS 1/200 (CQR-S2-01 witness)', source='suite C35 (c) repeated_mixed_family + marker')
    d = os.path.join(T, 'FL_normalizer_M06_n8'); os.makedirs(d); mp = os.path.join(d, 'model.uai')
    for ext in ('', '.evid', '.query.json'): open(mp + ext, 'wb').write(open(DEV_NORMALIZER + ext, 'rb').read())
    row('FL_normalizer_M06_n8', 'contract', mp, 'N1_CQR', dict(kind='baseline_N1', arm='N1_CQR'), 'normalizer route (exact reference or deterministic frontier); Z independently enumerable (2^10.3)', 5.0, coverage_required=['normalizer_publication'], spec_note='normalizer task (Z, relative error 1/200, delta 1e-6); dev input M06_n8_Z_s11 (development seed 11)', source='CQR_2026-11-15/dev_inputs/normalizer (development admission input; not held out)')
    # ---------------- block 3: fixed approximate canaries
    g = G.generate('M02', 8, 'near_miss', 1); m = g['model']; cb = m['cards']; d = os.path.join(T, 'FL_C31_nonzero_bias'); os.makedirs(d); mp = os.path.join(d, 'model.uai'); G.write_uai(m, mp)
    json.dump(dict(queries=[dict(kind='singleton', variable=0, state=1), dict(kind='table', table=dict(name='g1', kind='expectation', f=dict(scope=[1], values=[str(F(k + 1, cb[1] + 1)) for k in range(cb[1])])))], **DET), open(mp + '.query.json', 'w'))
    row('FL_C31_nonzero_bias', 'approximate_canary', mp, 'N1_CQR', dict(kind='same_build_G0', arm='G0_CQR'), 'approx_quotient commit with NONZERO bias -> structural_compiled (the compiled bias widens the original answers)', 10.0, coverage_required=['approx_quotient_nonzero_bias'], spec_note='M02 n=8 near_miss seed 1 (6-state clones; CURRENT generator %s); singleton + general scope-1 table; DETERMINISTIC_EPS 1/200' % gen_sha[:12], source='suite C31 (c) nonzero-bias fixture (re-generated; bytes pinned here)', generator_sha256=gen_sha)
    cards, fs = _sprinkled(1, 28, 14, 4); d = os.path.join(T, 'FL_C16_ratio_pac'); os.makedirs(d); mp = _uai(os.path.join(d, 'model.uai'), cards, fs)
    json.dump(dict(queries=[dict(kind='singleton', variable=0, state=1), dict(kind='parity', variables=[2, 3, 4, 5, 6, 7], bit=1)], **PAC_QUAL), open(mp + '.query.json', 'w'))
    row('FL_C16_ratio_pac', 'bank_optional', mp, 'N1_CQR', dict(kind='baseline_N1', arm='N1_CQR'), 'ratio stream draws -> pac_ratio_intersected_with_deterministic (route reachability only)', 15.0, 'sprinkled(1, 28, 14, 4); singleton + 6-variable parity; QUALIFICATION-TOLERANCE eps 1/10 delta 1/10 (RELAXED: a route-reachability witness, NOT evidence at the benchmark contract; a few fixed seeds never establish delta calibration)', source='suite C16 ratio fixture (re-generated; bytes pinned here)', relaxed_tolerance=True)
    # ---------------- block 4: change-specific pair (DEFAULT pair = signed residual, family M10, the CURRENT generator's Q_signed table; the size rung is pinned by `calibrate`)
    for regime in ('favorable', 'near_miss'):
        g = G.generate('M10', 20, regime, 1); d = os.path.join(T, 'FL_PAC_M10_n20_%s_s1' % regime); os.makedirs(d); mp = os.path.join(d, 'model.uai'); G.write_uai(g['model'], mp); json.dump(g['query_spec'], open(mp + '.query.json', 'w'))
        row('FL_PAC_M10_n20_%s_s1' % regime, 'approximate_canary', mp, 'N1_CQR', dict(kind='same_build_ablation', arm='N1_NO_SIGNED_STREAM'), 'GENUINE signed-PAC publication (pac_signed_residual_validation) at the PRODUCTION contract eps 1/200 delta 1e-6', 10.0, coverage_required=['signed_pac_publication'], spec_note='M10 n=20 %s seed 1 (Q_signed table; 2^20 states: the production reference needs ~3.3 s, the signed route publishes in 1-2.5 s on the accepted baseline, 18 Nov probe); PAC_EPS 1/200 1e-6 (production tolerance; a fixed seed tests reachability, never delta calibration)' % regime, generator_sha256=gen_sha, regime=regime, source='generator M10 (non-reserved family); DEVELOPMENT id')
    for regime in ('favorable', 'near_miss'):
        for n in (8, 12, 16, 20, 24):
            g = G.generate('M10', n, regime, 1); d = os.path.join(T, 'FL_M10_n%d_%s_s1' % (n, regime)); os.makedirs(d); mp = os.path.join(d, 'model.uai'); G.write_uai(g['model'], mp); json.dump(g['query_spec'], open(mp + '.query.json', 'w'))
            row('FL_M10_n%d_%s_s1' % (n, regime), 'change_specific_ladder', mp, 'N1_CQR', dict(kind='same_build_ablation', arm='N1_NO_SIGNED_STREAM'), 'signed residual stream (epochs > 0; pac_signed_residual_validation) on the heavy zero-residual region', 10.0, coverage_required=['signed_epochs_with_draws'], spec_note='M10 n=%d %s seed 1 (CURRENT generator Q_signed TABLE query, constant %s on the heavy region); PAC_EPS 1/200 1e-6 (production tolerance)' % (n, regime, g['meta']['constant']), source='generator M10 (non-reserved family); DEVELOPMENT id; NOT an archived admission query', generator_sha256=gen_sha, ladder_rung=n, regime=regime, pinned=False)
    # ---------------- block 5: cheap changed-surface controls (candidate only; checker-level; INVALID_TASK fixtures are refusals by design)
    def one(rid, q, note, expect):
        d = os.path.join(T, rid); os.makedirs(d); mp = _uai(os.path.join(d, 'model.uai'), [2], [([0], ['1', '3'])]); json.dump(dict(queries=[q], **DET), open(mp + '.query.json', 'w'))
        rows.append(dict(id=rid, block='control', budget_s=1.0, candidate_arm='N1_CQR', comparator=None, expected_mechanism=expect, spec=note, **bind(mp), expected_outcome=expect.split(':')[0]))
    d = os.path.join(T, 'FL_CTL_zero_evidence_beyond_cap'); os.makedirs(d); mpz = _uai(os.path.join(d, 'model.uai'), [2] * 24, [((0, 1), ['1', '1', '0', '0'])]); open(mpz + '.evid', 'w').write('1 0 1\n'); json.dump(dict(queries=[dict(kind='singleton', variable=1, state=1)], **DET), open(mpz + '.query.json', 'w'))
    rows.append(dict(id='FL_CTL_zero_evidence_beyond_cap', block='control', budget_s=3.0, candidate_arm='G0_CQR', comparator=None, expected_mechanism='PROVED_ZERO_EVIDENCE: a frontier zero proof beyond the enumeration cap (2^23 free states), VERIFIED by replay + transfer (CQR-A1-01)', spec='24 binary variables, one pair factor [1,1,0,0] on (X0,X1), evidence X0 = 1 (the A1 reviewer\'s just-beyond-cap fixture); DETERMINISTIC_EPS 1/200', **bind(mpz), expected_outcome='PROVED_ZERO_EVIDENCE', coverage_required=['zero_evidence_proof_verified']))
    one('FL_CTL_zero_mass', dict(kind='table', table=dict(name='cz', kind='expectation', f=dict(scope=[0], values=['0', '0']))), 'metadata-free constant-zero table -> exact 0 (never 3/4)', 'PUBLISHED: exact 0 through the general path')
    one('FL_CTL_undefined_ratio', dict(kind='table', table=dict(name='rat0', kind='ratio', h=dict(scope=[0], values=['0', '0']), g=dict(scope=[0], values=['0', '0']))), 'zero-denominator ratio -> typed UNDEFINED coordinate', 'PUBLISHED: UNDEFINED status')
    one('FL_CTL_false_metadata', dict(kind='table', table=dict(name='cz', kind='expectation', f=dict(scope=[0], values=['0', '0']), output=dict(kind='singleton', variable=0, state=1))), 'S1-01 witness: constant-zero table with a singleton label', 'INVALID_TASK: refused before inference (both arms)')
    man = dict(schema='CQR_FASTLOOP_DEV_MANIFEST_V2', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), baseline_build=baseline, generator_sha256=gen_sha, rows=rows,
               nominal_full_s='sentinels 2x(3+3+10+5) + contract 2x2x5 + C31 2x10 + PAC M10 n20 2x2x10 + pinned ladder pair 2x2x10 + controls 3+3x1 = 168 s (<= 180); the C16 ratio-PAC row is bank_optional (not reachable in 15 s on this host, 18 Nov probe)', ladder_pin_rule='calibrate.py pins, per regime, the SMALLEST rung at which the PRODUCTION REFERENCE (reference.Reference, run to completion in the calibration) needs MORE than the row budget / 2 to enumerate (so exact completion is NOT easy within the allowance) AND the baseline N1 run at 15 s publishes with the signed mechanism active (epochs with draws) or ends DEADLINE with stream activity, while its independent truth stays EXACT (elimination); every rung attempted is retained; no rung qualifying -> coverage gap disclosed; every attempt retained in LADDER_CALIBRATION.json; the pin is LADDER_PIN.json (the manifest file itself is never edited)',
               allocations=dict(worker_nominal_s_cap=180.0, verifier_oracle_s=80.0, overhead_cleanup_report_s=40.0, total_cap_s=300.0, smoke_target_s='30-60'),
               smoke_rows=['FL_SENT_ASIA', 'FL_C35_mixed_alias', 'FL_normalizer_M06_n8', 'FL_CTL_zero_evidence_beyond_cap', 'FL_CTL_zero_mass', 'FL_CTL_undefined_ratio', 'FL_CTL_false_metadata'],
               mutation_controls_required=['answer_shifted_by_1_97', 'guarantee_relabelled', 'source_identity_emptied', 'label_swapped_to_other_denotation'],
               comparator_policy='one primary comparator per row: baseline_N1 (last ACCEPTED build; pointer advanced only by explicit decision) for regressions; same_build_G0 for incremental CQR value; same_build_ablation for a causal operator / stream question; R0 anchor only at initialization / structural checkpoints',
               mutation_controls_note=['label_swap_binding (query file label swapped to a DIFFERENT denotation after publication -> checker refuses)', 'answer_shifted_by_1_97 (first answer and certificate publication moved by +1/97 -> checker refuses; truth MISS)', 'route_relabel (guarantee relabelled -> checker refuses)'],
               notes=['structural_original is production success, NOT mechanism coverage: activation is read from the certificate (compile journal commits, ratio_stream.t, epochs, structural attempts)',
                      'the ladder rows are candidates; `calibrate` pins ONE rung per regime (pinned=True) on the accepted baseline and retains every attempt', 'M03 / M05 / M09 / M12 reserved; no held-out campaign input is used'])
    json.dump(man, open(os.path.join(out, 'DEV_MANIFEST.json'), 'w'), indent=1); print(json.dumps(dict(rows=len(rows), blocks={b: sum(1 for r in rows if r['block'] == b) for b in sorted({r['block'] for r in rows})})))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['materialize']); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); a = ap.parse_args()
    if os.path.exists(os.path.join(a.out, 'DEV_MANIFEST.json')): raise SystemExit('refuse: DEV_MANIFEST.json exists (pinned manifests are immutable; use a new directory)')
    os.makedirs(a.out, exist_ok=True); materialize(os.path.abspath(a.baseline), os.path.abspath(a.out))
