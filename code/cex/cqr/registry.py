"""CQR campaign REGISTRY (composition over the repaired baseline's registry cex/pac/registry.py, which is NOT modified: the baseline R0 keeps its frozen identity).
Arms: the baseline arms (B0 anchor, R0 = H1_HYBRID of the repaired source on its native all-singleton contract; comparators; native) are imported from the pac registry;
the NEW arms are the CQR candidate N1_CQR, the general-query reference core G0_CQR (same parser / semantics / kernel / stopping / limits, every new reduction disabled,
no signed stream, no query-directed refinement) and the named feature ablations. Cohorts: the 105 legacy explicit tasks (imported), the 90 native slots (imported), and the
NEW cohorts constructed (M01-M12), new_uai2022, new_wmc2024, query_transfer, plus the separately contracted closest-method panels (normalizer_dis, bounded_query_osstar).
Validator for the CQR arms: cqr_candidate (cex/cqr/checker.py). Identity scope 'cqr_candidate' = cex/cqr/*.py + cex/newarm/core.py (the shared reader)."""
import os, sys, hashlib, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); PAC = os.path.join(os.path.dirname(HERE), 'pac'); CODE = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    """load a module by FILE PATH under a distinct name (the baseline's cex/pac and this cex/cqr share module names: registry / solve / gate / report / closeout / campaign)"""
    if name in sys.modules: return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path); mod = importlib.util.module_from_spec(spec); sys.modules[name] = mod; spec.loader.exec_module(mod); return mod


PR = _load('pac_registry', os.path.join(PAC, 'registry.py'))          # the baseline registry (read-only; never shadowed)
if HERE not in sys.path: sys.path.insert(0, HERE)
_m = sys.modules.get('solve')
_solve = _m if (_m is not None and os.path.dirname(os.path.abspath(getattr(_m, '__file__', ''))) == HERE) else _load('cqr_solve', os.path.join(HERE, 'solve.py'))

REGISTRY_VERSION = 'cqr-registry-v1 (2026-11-16)'
CQR_ARMS = {a: dict(kind=('primary' if a in ('N1_CQR', 'G0_CQR') else 'ablation'), representation='uai_table+query_spec', guarantee='EXACT|DETERMINISTIC|PAC', validator='cqr_candidate', identity_scope='cqr_candidate',
                    feature_flags=dict(enabled_operators=sorted(s['enabled']), signed_stream=s['signed_stream'], query_directed_refinement=s['query_directed_refinement']), role=('candidate' if a == 'N1_CQR' else ('general_reference_core' if a == 'G0_CQR' else 'feature_ablation')))
            for a, s in _solve.ARMS.items()}
ARMS = dict(PR.ARMS); ARMS.update(CQR_ARMS)
R0_ARM = 'H1_HYBRID'          # the repaired pre-new-mechanism baseline on its native (all-singleton) contract
B0_ARM = 'B0_FROZEN_V14'
ABLATION_OF_FAMILY = {'M01': 'N1_NO_SYMMETRY_RELEVANCE', 'M02': 'N1_NO_QUOTIENT', 'M03': 'N1_NO_SYMMETRY_RELEVANCE', 'M04': 'N1_NO_AFFINE', 'M05': 'N1_NO_AFFINE', 'M06': 'N1_NO_INFLUENCE', 'M07': 'N1_NO_INFLUENCE', 'M08': 'N1_NO_CONCENTRATION', 'M09': 'N1_NO_QUERY_DIRECTED_REFINEMENT', 'M10': 'N1_NO_SIGNED_STREAM', 'M11': 'N1_NO_QUERY_DIRECTED_REFINEMENT', 'M12': 'N1_NO_QUOTIENT'}
COHORTS = dict(PR.COHORTS)
COHORTS.update({
    'constructed': dict(order=10, representation='uai_table+query_spec', original_task='mechanism families M01-M12 with their declared query schedules (singleton / all singletons / parity / conditional); favorable and near-miss regimes', arms=('cqr_primary', 'comparator_if_all_singletons'), native_query=None, pooled_with_uai_numerator=False, comparison='G0_vs_N1'),
    'new_uai2022': dict(order=11, representation='uai_table', original_task='all original singleton marginals with the official evidence (UAI 2022 FINAL MAR; metadata-only salted selection)', arms=('legacy_primary', 'cqr_primary', 'comparator'), native_query=None, pooled_with_uai_numerator=False, comparison='G0_vs_N1 (R0 reported alongside)'),
    'new_wmc2024': dict(order=12, representation='uai_table (converted weighted CNF; conversion certificate)', original_task='all original-literal singleton marginals of the converted nonnegative weighted CNF (auxiliary OR-gate variables excluded from the task)', arms=('legacy_primary', 'cqr_primary', 'comparator'), native_query=None, pooled_with_uai_numerator=False, comparison='G0_vs_N1 (R0 reported alongside)'),
    'query_transfer': dict(order=13, representation='uai_table+query_spec', original_task='one selected conditional event and one selected pair-joint / parity query per preselected source model (public salted rule); original evidence preserved', arms=('cqr_primary',), native_query=None, pooled_with_uai_numerator=False, comparison='G0_vs_N1'),
    'normalizer_dis': dict(order=14, representation='uai_table+query_spec(normalizer)', original_task='Z with relative error 1/200, delta 1e-6 (N1 normalizer contract) vs DIS at the same contract', arms=('cqr_normalizer', 'dis'), native_query=None, pooled_with_uai_numerator=False, comparison='separate table'),
    'bounded_query_osstar': dict(order=15, representation='uai_table+query_spec', original_task='bounded-expectation queries vs OS* exact sampling + fixed-sample confidence wrapper', arms=('cqr_primary', 'osstar'), native_query=None, pooled_with_uai_numerator=False, comparison='separate table'),
})
COHORT_ORDER = tuple(sorted(COHORTS, key=lambda k: COHORTS[k]['order']))
UNAVAILABLE_ARMS = dict(PR.UNAVAILABLE_ARMS)
UNAVAILABLE_ARMS.update({'DIS': 'see runs/.../baselines/BASELINE_AVAILABILITY.json (author archive linked; build / adapter qualification status recorded there)', 'OSSTAR': 'see runs/.../baselines/BASELINE_AVAILABILITY.json (no author implementation located => UNAVAILABLE_NO_IMPLEMENTATION; no independent reimplementation)'})
QUALIFICATION_GROUPS = ('C1_identity_and_checker_end_to_end', 'C2_independent_oracle_and_modes', 'C3_quotient_exact_and_mutations', 'C4_approximate_quotient_budget', 'C5_affine_support_and_pullbacks', 'C6_influence_and_concentration_conditions', 'C7_frontier_typed_bounds_and_envelopes', 'C8_signed_residual_stream_and_epochs', 'C9_ratio_stream_history_and_record_before_resolve', 'C10_publication_feasibility_denominators_normalizer', 'C11_protected_reference_and_resource_refusal', 'C12_registry_pipeline_dev_admission', 'C13_tiny_model_delta_falsification', 'C14_publication_contract_every_route', 'C15_semantics_and_guarantee_binding', 'C16_fresh_process_pac_routes', 'C17_protected_reference_scheduling', 'C18_task_local_state_and_policy', 'C19_provenance_and_intake', 'C20_atomic_compilation_replay_service_history_attribution', 'C21_checker_soundness_lifecycle_dependencies_closeout', 'C22_precision_zero_mass_witness_service', 'C23_exactly_once_accounting_quota_inheritance_tolerance_domain', 'C24_zero_risk_controller_cadence_completed_charges')
SOURCE_SCOPES = dict(PR.SOURCE_SCOPES); SOURCE_SCOPES['cqr_candidate'] = ('cex/cqr',)


TEST_SIDE_FILES = ('qualification.py', 'test_acquire.py', 'test_cqr_provenance_intake.py')          # the qualification suite and test drivers: NOT part of the candidate identity (the suite's own sha256 is recorded in
                                                                    # the qualification record and the closeout requires it to equal the CURRENT suite file; the candidate scope is the production code)


def cqr_source_inventory(code_dir=CODE):
    """{key: sha256} for the CQR candidate identity: every .py in cex/cqr EXCEPT TEST_SIDE_FILES, + cex/newarm/core.py (keys 'cqr/x.py', 'newarm/core.py') == worker.candidate_sources()"""
    out = {}
    for f in sorted(os.listdir(os.path.join(code_dir, 'cex', 'cqr'))):
        if f.endswith('.py') and f not in TEST_SIDE_FILES: out['cqr/' + f] = hashlib.sha256(open(os.path.join(code_dir, 'cex', 'cqr', f), 'rb').read()).hexdigest()
    out['newarm/core.py'] = hashlib.sha256(open(os.path.join(code_dir, 'cex', 'newarm', 'core.py'), 'rb').read()).hexdigest()
    return out


def full_inventory(code_dir=CODE):
    """the complete frozen source inventory of a CQR campaign: the baseline inventory (every scope of the pac registry) + the cqr scope"""
    inv = PR.source_inventory(code_dir); inv.update(cqr_source_inventory(code_dir)); return inv


def validator_of(arm): return ARMS[arm]['validator'] if arm in ARMS else None
def is_cqr_arm(arm): return arm in CQR_ARMS
def scope_of_key(key):
    if key.startswith('cqr/') or key == 'newarm/core.py' and False: return 'cqr_candidate'
    return PR.scope_of_key(key)


def suite_sha256(code_dir=CODE): return hashlib.sha256(open(os.path.join(code_dir, 'cex', 'cqr', 'qualification.py'), 'rb').read()).hexdigest()
