"""DGP8 second freeze + manifests (derived from dgp7_manifests.py; PROTOCOL.md sections 2-6). `freeze` writes FREEZE.json (implementation, configuration, runner / analyzer / probe / validator identities, the native build identities of the accepted executor kernel AND the heat-bath
native kernel when its build record exists, dependency identities, the spectral-witness / certificate / transition-policy constants exposed by the new modules (recorded absent when not importable), the Stage A / Stage B panels, the release rule, the budget incl. recorded
reassignments, the frozen rate-model file hash when present). `holdout` (run at the frozen commit from the clean detached checkout) VERIFIES byte-identical the 16 original exposed dense inputs and the three exposed small oracle models (no fresh generation this round: nothing is
generated unless the regression is released and a committed recipe exists), reads the archived incumbents by task name from the DGP6 / DGP7 RESULTS tables, and writes MODEL_MANIFEST.json + the per-panel manifests consumed by run_dgp8.py: STAGE_A (16), GUARD (the eligible
failing anchors + one matched passing weak input + one strong refusal control), ORACLE_3, PRESERVATION_18 / PRESERVATION_13, HISTORICAL_24. usage: dgp8_manifests.py freeze|holdout [--code-root ROOT]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from research.source_execution import require_local_source, bound_source_command, checked_structural_build, checked_heatbath_build
import sys, os, json, hashlib, time, subprocess, platform, glob
HERE = os.path.dirname(os.path.abspath(__file__))
RD = os.environ.get('DGP8_RD', str(_runs_root() / 'mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH')); DGP7 = os.path.join(os.path.dirname(RD), 'DGP7_RESIDUAL_JOINT'); DGP6 = os.path.join(os.path.dirname(RD), 'DGP6_GLOBAL_CONSTRUCTION')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def git(root, *a): return subprocess.check_output(['git', '-C', root] + list(a)).decode().strip()
# ---- frozen panel definitions (PROTOCOL.md section 3)
STAGE_A_16 = ['dg_n%d_c%d_%s_%s' % (n, c, t, s) for n in (32, 64) for c in (2, 4) for t in ('er50', 'clique') for s in ('half', 'two')]
WEAK_8 = [t for t in STAGE_A_16 if t.endswith('_half')]; STRONG_8 = [t for t in STAGE_A_16 if t.endswith('_two')]
MATCHED_PASSING_WEAK = 'dg_n32_c4_er50_half'; STRONG_REFUSAL_CONTROL = 'dg_n64_c4_er50_two'
ORACLE_3 = ['dg_n6_c4_clique_two', 'dg_n8_c4_er50_two', 'dg_n8_c4_clique_two']
EPS = 0.005                                                       # epsilon = 1/200: a current FAILURE = archived best incumbent worst radius > EPS (or no completion)
def verify(tasks, rd=None):
    import research.campaigns.hp.dgp_paths as dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], rd or RD, t['model_sha256']); assert sha(t['model']) == t['model_sha256'], t['name']; assert sha(t['model'] + '.evid') == t['evid_sha256'], t['name']; t['verified_now'] = True
    return tasks

def archived_incumbents():
    """per task name: the hash-matched archived cells of the DGP6 main panel (BASE / REPAIRED / GLOBAL) and the DGP7 main matrix (REPAIRED / RESIDUAL_ONLY / RESIDUAL_JOINT): complete, worst_radius (full inventory), receipt_wall_s, dir; plus the best incumbent worst radius"""
    def grab(path, table):
        d = json.load(open(path)) if os.path.exists(path) else {}; out = {}
        for r in (d.get('tables') or {}).get(table, []):
            if r.get('confirm') or (r.get('seed_index') or 0) != 0: continue
            out[r['task']] = {arm: {k: a.get(k) for k in ('complete', 'worst_radius', 'median_radius', 'covered_at_eps', 'receipt_wall_s', 'outcome', 'published', 'K', 'dir')} for arm, a in (r.get('arms') or {}).items()}
        return out, (sha(path) if os.path.exists(path) else None)
    d6, s6 = grab(os.path.join(DGP6, 'RESULTS.json'), 'main'); d7, s7 = grab(os.path.join(DGP7, 'RESULTS.json'), 'main_matrix')
    def inc(name):
        cells = {}
        for arm, a in (d6.get(name) or {}).items(): cells['dgp6/' + arm] = a
        for arm, a in (d7.get(name) or {}).items(): cells['dgp7/' + arm] = a
        radii = [(a.get('worst_radius'), k) for k, a in cells.items() if isinstance(a.get('worst_radius'), (int, float))]
        best = min(radii) if radii else (None, None)
        return dict(dgp6_main=d6.get(name), dgp7_main_matrix=d7.get(name), best_worst_radius=best[0], best_cell=best[1], any_complete=any(a.get('complete') for a in cells.values()), current_failure=(best[0] is None or best[0] > EPS), sources=dict(dgp6_results_sha256=s6, dgp7_results_sha256=s7, rule='the hash-matched primary-seed cells (seed index 0, not confirmations); worst radius on the full frozen inventory with 0.5 for absent coordinates; a current failure = no archived cell reaches worst radius <= 0.005'))
    return inc

def freeze(root):
    require_local_source(root)
    import research.campaigns.hp.run_dgp8 as R, pgm.algorithms.quotient.unified_pac_planner as UPP
    head = git(root, 'rev-parse', 'HEAD'); tree = git(root, 'rev-parse', 'HEAD^{tree}'); dirty = git(root, 'status', '--porcelain', '--untracked-files=no', '--', 'src/pgm/algorithms', 'src/pgm/runtime', 'research'); assert not dirty, dirty
    harness = ['research/source_execution.py', 'research/paths.py', 'research/bootstrap.py', 'research/campaigns/hp/run_dgp8.py', 'research/campaigns/hp/run_dgp7.py', 'research/campaigns/hp/run_dgp6.py', 'research/campaigns/hp/dgp8_manifests.py', 'research/campaigns/hp/dgp8_analyze.py', 'research/campaigns/hp/dgp8_theory_return.py', 'research/campaigns/hp/dgp8_start_here.py', 'research/campaigns/hp/dgp8_package.py', 'research/campaigns/hp/dgp8_sidecar.py', 'research/campaigns/hp/dgp8_probes.py', 'research/campaigns/hp/dgp_paths.py', 'research/campaigns/hp/validate_round.py', 'research/campaigns/hp/check_dgp.py', 'src/pgm/algorithms/quotient/check_joint.py', 'src/pgm/algorithms/quotient/check_global.py', 'src/pgm/algorithms/quotient/check_residual.py', 'research/campaigns/hp/hp_gen.py', 'research/campaigns/hp/dense_gen.py', 'research/campaigns/hp/dgp2_oracle.py', 'research/campaigns/hp/dgp6_oracle.py', 'research/campaigns/hp/dgp7_oracle.py', 'src/pgm/runtime/supervise.py']
    present = [h for h in harness if os.path.exists(os.path.join(root, h))]; files = {f: sha(os.path.join(root, f)) for f in R.IDENTITY_FILES + present}
    kb = checked_structural_build(root); hb = checked_heatbath_build(root)
    py = subprocess.check_output([sys.executable, '-c', 'import sys,numpy,scipy; print(sys.version.split()[0], numpy.__version__, scipy.__version__)']).decode().split()
    bd = json.load(open(os.path.join(RD, 'BUDGET_DECLARATION.json'))); rates_p = os.path.join(RD, 'HEATBATH_RATES.json'); plain = lambda d: {k: v for k, v in d.items() if not isinstance(v, (list, tuple, dict))} if isinstance(d, dict) else d
    profiles = {}
    for mod in ('spectral_witness', 'markov_certificate', 'spectral_heatbath_run', 'heatbath_native', 'heatbath_exact'):
        try: M = __import__('pgm.algorithms.response.' + mod, fromlist=[mod]); profiles[mod] = dict(PROFILE=plain(getattr(M, 'PROFILE', None)), VERSION=getattr(M, 'VERSION', None), constants={k: getattr(M, k) for k in dir(M) if k.isupper() and isinstance(getattr(M, k), (int, float, str, bool)) and k not in ('PROFILE', 'VERSION')})
        except Exception as e: profiles[mod] = dict(absent=True, error=repr(e)[:160])
    inc = archived_incumbents()
    fr = dict(experiment='DGP8_SPECTRAL_HEATBATH', step='SECOND FREEZE: algorithm, verifier, transition precision policy, RNG, checkpoint / risk policy, constructor allowance, fixed cost model (HEATBATH_RATES.json when present), panel identities and release rule (brief section 6); the exposed inputs are verified byte-identical by `holdout` at this commit; no fresh input is generated this round', frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), protocol_freeze='PROTOCOL.md (first freeze)', brief_sha256=(bd.get('received') or {}).get('brief'), theory_sha256=(bd.get('received') or {}).get('theory'), missing_packet_items=bd.get('missing_packet_items'), harness_files=present, harness_files_absent_at_freeze=[h for h in harness if h not in present], arm_identity_files=R.IDENTITY_FILES,
              code=dict(commit=head, tree=tree, branch='dgp8-spectral-heatbath', parent='2ae105c (main = the DGP7 tip with the three archived harness amendments; every arm identity file byte-identical to the reviewed DGP7 engine commit 47d4024)', before_repair_reference='2ae105c (pgm-eval-2ae105c; the seven DGP7-review findings probed there: controls/before/seven_findings_on_2ae105c.json)', files=files, planner_version=UPP.VERSION, accepted_engine='v2.13.2 at pgm 1da6da3; blockres files byte-identical (checked by validate_round; confirmed from the repository at the first freeze)', kernel=dict(source_sha256=kb['source_sha256'], binary_sha256=kb['binary_sha256'], compiler=kb['compiler'], compiler_version=kb['compiler_version'], flags=kb['flags'], plan_format=kb.get('plan_format')), heatbath_kernel=(hb if hb else 'ABSENT at freeze (heatbath_build.json not present)'), dependencies=dict(python=py[0], numpy=py[1], scipy=py[2], platform=platform.platform(), machine=platform.machine())),
              arms=dict(BASE='cex/blockres/integrated.py with run_paired.FROZEN options (%s), --budget = hard' % json.dumps(R.FROZEN['base']), REPAIRED=' '.join(R.ARM_ARGS['REPAIRED']), SPECTRAL_HEATBATH='cex/hp/spectral_heatbath_run.py --input --output --budget hard --admission-stop work --seed S ' + ' '.join(R.ARM_ARGS['SPECTRAL_HEATBATH']) + ' [--rate-model HEATBATH_RATES.json]', HEATBATH_SCREEN='SPECTRAL_HEATBATH + ' + ' '.join(R.ARM_ARGS['HEATBATH_SCREEN'][-2:]) + ' (Stage A diagnostic; never a completion)', SELECT='RESERVED (refused without --allow-select and a frozen request-level risk allocation; NOT RUN this round)', production=list(R.PRODUCTION_ARMS), diagnostic=list(R.DIAGNOSTIC_ARMS), seeds=R.FROZEN['seed_rule'], arm_order=R.FROZEN['arm_rotation'], dev_stream_s=R.FROZEN['dev_stream_s']),
              heatbath=dict(modules=profiles, rate_model=(dict(path=os.path.relpath(rates_p, RD), sha256=sha(rates_p), content=json.load(open(rates_p))) if os.path.exists(rates_p) else 'ABSENT at freeze (written by the Stage A screen BEFORE the guard runs; its hash is recorded in RUN_MANIFEST / IDENTITY)'), mechanism='PROTOCOL.md section 2 (witness: outward logarithm enclosures + interval matrix + interval Cholesky with positive pivot lower bounds; kernel: exact random-scan heat-bath, native fast path with proved decisions and exact fallback; certificate: markov_heatbath, p0 from Z_U, burn-in coupling, Leon-Perron + union bound at frozen checkpoints)'),
              panels=dict(stage_a_16=STAGE_A_16, weak_8=WEAK_8, strong_8=STRONG_8, matched_passing_weak=MATCHED_PASSING_WEAK, strong_refusal_control=STRONG_REFUSAL_CONTROL, oracle_3=ORACLE_3, guard_rule='the eligible failing anchors = weak inputs whose archived best incumbent worst radius > 0.005 (hash-matched DGP6 / DGP7 cells) + %s + %s' % (MATCHED_PASSING_WEAK, STRONG_REFUSAL_CONTROL), archived_incumbents_stage_a={t: {k: v for k, v in inc(t).items() if k != 'sources'} for t in STAGE_A_16}, incumbent_rule=inc(STAGE_A_16[0])['sources']['rule']),
              release=dict(stage_b='Stage A forecasts (frozen rate model + checked gap) EITHER a credible new completion under the original contract (forecast radius <= 0.005 at 20 s) OR >= 2x improvement in worst certified radius on a current failure after all costs (witness + burn-in + sampling + publication)', regression='a guard gain (>= 2x worst-radius improvement on a current failure) survives BOTH seeds with no safety / resource defect', tuning='none on scored outcomes; no truth in admission or transition policy', forecast='r = sqrt((2 - g) ln(2 Q / delta_j) / (2 N g)); N = rate x (work budget - witness - burn-in / rate - 0.5 s); delta_j = delta / 8 (frozen 4-checkpoint sequence, half the request delta to the checkpoints, half to burn-in)'),
              contracts=R.CONTRACTS, memory='3 GiB sampled process-tree RSS; constructor account CE.Budget; witness / kernel / occupation / checkpoint arrays admitted before allocation; retained proof arrays stay charged', repairs=dict(findings='seven DGP7-review findings from the brief\'s abbreviated list (the review file is ABSENT)', before='controls/before/seven_findings_on_2ae105c.json', after='controls/qual/seven_findings_after_<frozen>.json', controls='D71+ (check_dgp.py) + the inherited suite D1-D70'),
              budget=dict(ceiling_s=bd['ceiling_s'], allocations=bd['allocations'], reassignments=bd.get('reassignments'), charged_before_freeze_s=round(sum(json.loads(l)['wall_s'] for l in open(os.path.join(RD, 'DGP8_LEDGER.jsonl')) if json.loads(l).get('kind') == 'RECEIPT'), 1) if os.path.exists(os.path.join(RD, 'DGP8_LEDGER.jsonl')) else 0.0))
    json.dump(fr, open(os.path.join(RD, 'FREEZE.json'), 'w'), indent=1, default=str); print('FROZEN', head[:9], tree[:9], 'charged before freeze', fr['budget']['charged_before_freeze_s'], 'harness files absent', fr['harness_files_absent_at_freeze'], 'heatbath modules', {k: ('absent' if v.get('absent') else 'ok') for k, v in profiles.items()})

def holdout(root):
    require_local_source(root)
    fr = json.load(open(os.path.join(RD, 'FREEZE.json'))); head = git(root, 'rev-parse', 'HEAD'); assert head == fr['code']['commit'], 'holdout must run at the frozen commit (%s != %s)' % (head[:9], fr['code']['commit'][:9])
    main76 = {t['name']: t for t in json.load(open(os.path.join(DGP7, 'MODEL_MANIFEST.json')))['panels']['main_76']}; inc = archived_incumbents()
    def mk(name, role):
        t = dict(main76[name]); t.pop('verified_now', None); t.pop('panel_dgp4', None); t.pop('panel_dgp5', None); t.pop('panel_dgp6', None); coup = 'half' if name.endswith('_half') else 'two'
        t.update(panel='stage_a_16', family=t.get('topology'), coupling=coup, weak=(coup == 'half'), role=role, exposure='exposed (original DENSE_GENERIC_PAC_INTEGRATION_1 dense input; bytes verified now; matched by sha256)', archived_incumbent=inc(name)); return t
    stage_a = verify([mk(n, ('weak_eligibility_candidate' if n.endswith('_half') else 'strong_refusal_control')) for n in STAGE_A_16]); assert len(stage_a) == 16 and len({(t['model_sha256'], t['evid_sha256']) for t in stage_a}) == 16
    by = {t['name']: t for t in stage_a}
    failing = [n for n in WEAK_8 if by[n]['archived_incumbent']['current_failure']]
    guard = [dict(by[n], role='eligible_failing_anchor') for n in failing] + [dict(by[MATCHED_PASSING_WEAK], role='matched_passing_weak')] + [dict(by[STRONG_REFUSAL_CONTROL], role='strong_refusal_control')]
    o7 = {t['name']: t for t in json.load(open(os.path.join(DGP7, 'ORACLE_MANIFEST.json')))['tasks']}; o6 = {t['name']: t for t in json.load(open(os.path.join(DGP6, 'ORACLE_MANIFEST.json')))['tasks']}
    oracle = verify([dict((o7.get(n) or o6[n]), panel='oracle_3', role='exact_conditional_and_geometry_check', exposure='exposed small oracle model (DGP2 / DGP4 / DGP5 / DGP6 oracle inputs; oracle only; never a production arm)') for n in ORACLE_3]); assert len(oracle) == 3
    pres18 = verify([dict(t, exposure='exposed (USR1 / DGP1 preservation)', panel='preservation_18') for t in json.load(open(os.path.join(DGP7, 'PRESERVATION_18_MANIFEST.json')))['tasks']]); pres13 = verify([dict(t, exposure='exposed (accepted preservation panel)', panel='preservation_13') for t in json.load(open(os.path.join(DGP7, 'PRESERVATION_13_MANIFEST.json')))['tasks']]); assert len(pres18) == 18 and len(pres13) == 13
    hist24_names = json.load(open(os.path.join(DGP7, 'MODEL_MANIFEST.json')))['panels']['historical_completions_24']; hist24 = verify([dict(main76[n], panel='historical_24', role='historical_completion', archived_incumbent=inc(n)) for n in hist24_names]); assert len(hist24) == 24
    for name, tasks in (('STAGE_A_MANIFEST', stage_a), ('GUARD_MANIFEST', guard), ('ORACLE_MANIFEST', oracle), ('PRESERVATION_18_MANIFEST', pres18), ('PRESERVATION_13_MANIFEST', pres13), ('HISTORICAL_24_MANIFEST', hist24)): json.dump(dict(tasks=tasks, code_commit=head, freeze_sha256=sha(os.path.join(RD, 'FREEZE.json'))), open(os.path.join(RD, name + '.json'), 'w'), indent=1, default=str)
    allm = dict(experiment='DGP8_SPECTRAL_HEATBATH', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), code_commit=head, freeze_sha256=sha(os.path.join(RD, 'FREEZE.json')), generated_manifests=[],
                panels=dict(stage_a_16=stage_a, weak_8=[dict(name=n, role=by[n]['role'], current_failure=by[n]['archived_incumbent']['current_failure'], best_worst_radius=by[n]['archived_incumbent']['best_worst_radius']) for n in WEAK_8], strong_8=[dict(name=n, role=by[n]['role']) for n in STRONG_8], guard=guard, eligible_failing_anchors=failing, matched_passing_weak=MATCHED_PASSING_WEAK, strong_refusal_control=STRONG_REFUSAL_CONTROL, oracle_3=oracle, preservation_18=pres18, preservation_13=pres13, historical_24=hist24, historical_completions_24=hist24_names),
                exposure_labels=dict(exposed='bytes identical to the DGP1-DGP7 / USR1 / accepted-panel inputs (sha256 verified now)', oracle='small models exposed to oracle calculations only (never production arms)', fresh='none generated this round (a committed recipe + a released regression would be required)'))
    json.dump(allm, open(os.path.join(RD, 'MODEL_MANIFEST.json'), 'w'), indent=1, default=str); print('stage_a', len(stage_a), 'failing anchors', failing, 'guard', [(t['name'], t['role']) for t in guard], 'oracle', [t['name'] for t in oracle], 'pres', len(pres18), len(pres13), 'historical', len(hist24))

if __name__ == '__main__':
    import argparse; ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['freeze', 'holdout']); ap.add_argument('--code-root', default=str(_repo_root())); a = ap.parse_args(); (freeze if a.cmd == 'freeze' else holdout)(os.path.abspath(a.code_root))
