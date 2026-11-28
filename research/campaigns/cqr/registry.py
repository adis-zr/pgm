"""CQR campaign REGISTRY (composition over the repaired baseline's registry cex/pac/registry.py, which is NOT modified: the baseline R0 keeps its frozen identity).
Arms: the baseline arms (B0 anchor, R0 = H1_HYBRID of the repaired source on its native all-singleton contract; comparators; native) are imported from the pac registry;
the NEW arms are the CQR candidate N1_CQR, the general-query reference core G0_CQR (same parser / semantics / kernel / stopping / limits, every new reduction disabled,
no signed stream, no query-directed refinement) and the named feature ablations. Cohorts: the 105 legacy explicit tasks (imported), the 90 native slots (imported), and the
NEW cohorts constructed (M01-M12), new_uai2022, new_wmc2024, query_transfer, plus the separately contracted closest-method panels (normalizer_dis, bounded_query_osstar).
Validator for the CQR arms: cqr_candidate (cex/cqr/checker.py). Identity scope 'cqr_candidate' = cex/cqr/*.py + cex/newarm/core.py (the shared reader)."""
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import os, sys, hashlib, importlib.util
from pathlib import Path




from ._legacy import load_pac
PR = load_pac('registry')          # the baseline registry (read-only; never shadowed)
from pgm.algorithms.cqr import solve as _solve

REGISTRY_VERSION = 'cqr-registry-v2.5 (2026-11-19, repair-2 review CQR-AF2-01..07: verifier-side versions only (checker v1.10, gate v1.2, report v1.1, suite v15); no group change; v2.4 2026-11-18, A1 review CQR-A1-01: group C36; v2.3 2026-11-18, structured-repair review CQR-S2-01: group C35; v2.2 2026-11-17, structured review repairs; groups C32-C34; v2.1: the candidate identity scope includes the cex/newarm structural executor modules the CQR worker may run; arms N1_NO_STRUCTURAL / G0_NO_STRUCTURAL; qualification groups C29-C31)'
CQR_SCOPE_NEWARM = ('core.py', 'forest.py', 'dag.py', 'support.py', 'stream.py', 'stream_float.py', 'cex_executor.py', 'planning.py', 'geometry.py')      # the shared reader + the structural executors (cqr/structural.py adapters)
def is_cqr_scope_key(key):
    return key.startswith(('pgm/algorithms/cqr/', 'pgm/algorithms/structural/', 'cqr_campaign/'))
CQR_ARMS = {a: dict(kind=('primary' if a in ('N1_CQR', 'G0_CQR') else 'ablation'), representation='uai_table+query_spec', guarantee='EXACT|DETERMINISTIC|PAC', validator='cqr_candidate', identity_scope='cqr_candidate',
                    feature_flags=dict(enabled_operators=sorted(s['enabled']), signed_stream=s['signed_stream'], query_directed_refinement=s['query_directed_refinement'], structural=bool(s.get('structural', False))), role=('candidate' if a == 'N1_CQR' else ('general_reference_core' if a == 'G0_CQR' else ('qualification_mechanism_control' if a.endswith('_NO_STRUCTURAL') and a not in ('N1_NO_STRUCTURAL',) else 'feature_ablation'))), structural_backend=bool(s.get('structural', False)))
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
QUALIFICATION_GROUPS = ('C1_identity_and_checker_end_to_end', 'C2_independent_oracle_and_modes', 'C3_quotient_exact_and_mutations', 'C4_approximate_quotient_budget', 'C5_affine_support_and_pullbacks', 'C6_influence_and_concentration_conditions', 'C7_frontier_typed_bounds_and_envelopes', 'C8_signed_residual_stream_and_epochs', 'C9_ratio_stream_history_and_record_before_resolve', 'C10_publication_feasibility_denominators_normalizer', 'C11_protected_reference_and_resource_refusal', 'C12_registry_pipeline_dev_admission', 'C13_tiny_model_delta_falsification', 'C14_publication_contract_every_route', 'C15_semantics_and_guarantee_binding', 'C16_fresh_process_pac_routes', 'C17_protected_reference_scheduling', 'C18_task_local_state_and_policy', 'C19_provenance_and_intake', 'C20_atomic_compilation_replay_service_history_attribution', 'C21_checker_soundness_lifecycle_dependencies_closeout', 'C22_precision_zero_mass_witness_service', 'C23_exactly_once_accounting_quota_inheritance_tolerance_domain', 'C24_zero_risk_controller_cadence_completed_charges', 'C25_ratio_prior_binding_influence_scan_tolerance_semantics', 'C26_partition_premise_order_validation_structural_negative', 'C27_final_query_accounting_evaluation_site_audit', 'C28_view_storage_ownership_renumbering_declarations_event_schema', 'C29_failure_telemetry_survives_graceful_and_hard_kills', 'C30_cumulative_credit_reference_scheduling', 'C31_structural_adapters_composition_checker_reachability', 'C32_query_semantics_arm_eligibility_provenance_attribution', 'C33_compositional_discovery_deadline_propagation_reduction_lift', 'C34_terminal_diagnostics_freshness_and_operation_observability', 'C35_query_presentation_equivalence_structural_routes', 'C36_zero_evidence_proofs_beyond_the_enumeration_cap')
SOURCE_SCOPES = dict(PR.SOURCE_SCOPES)
SOURCE_SCOPES['cqr_candidate'] = ('src/pgm/algorithms/cqr', 'src/pgm/algorithms/structural', 'research/campaigns/cqr')


TEST_SIDE_FILES = ('qualification.py', 'test_acquire.py', 'test_cqr_provenance_intake.py')          # the qualification suite and test drivers: NOT part of the candidate identity (the suite's own sha256 is recorded in
                                                                    # the qualification record and the closeout requires it to equal the CURRENT suite file; the candidate scope is the production code)


def cqr_source_inventory(code_dir=CODE):
    """Hash the executed CQR closure and its research wrapper at canonical locations.

    Logical keys identify the current layout; old manifests are historical and
    are not relabelled or silently accepted against this source inventory.
    ``code_dir`` still accepts a repository's ``code`` path for caller compatibility.
    """
    root = Path(code_dir).resolve()
    if root.name == 'code': root = root.parent
    out = {}
    scopes = (
        ('pgm/algorithms/cqr', root / 'src/pgm/algorithms/cqr', ('.py',)),
        ('pgm/algorithms/structural', root / 'src/pgm/algorithms/structural', ('.py', '.cpp', '.json')),
        ('cqr_campaign', root / 'research/campaigns/cqr', ('.py', '.sh')),
    )
    for key, folder, suffixes in scopes:
        if not folder.is_dir(): raise FileNotFoundError('CQR identity source directory missing: ' + str(folder))
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix in suffixes and path.name not in TEST_SIDE_FILES:
                out[key + '/' + path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def full_inventory(code_dir=CODE):
    """Inventory the inherited comparison scopes at their current physical paths.

    The archived registry's logical keys remain available to its verifier. Their
    values are hashes of the relocated files, never hashes copied from old logs.
    A new campaign therefore needs a new freeze; old scored identities are not
    rewritten by this mapping.
    """
    root = Path(code_dir).resolve()
    if root.name == 'code': root = root.parent
    locations = {
        'cex/pac': 'research/archive/pac',
        'cex/newarm': 'src/pgm/algorithms/structural',
        'cex/b0_frozen_v14': 'research/archive/b0_frozen_v14',
        'gbidi/supervise.py': 'src/pgm/runtime/supervise.py',
        'cbi': 'src/pgm/algorithms/cbi',
        'sf': 'src/pgm/algorithms/sf',
        'h4a': 'src/pgm/algorithms/h4',
        'build/h4rect': 'research/archive/native/h4_binaries/h4rect',
        'build/h4point': 'research/archive/native/h4_binaries/h4point',
        'build/h4pcheck': 'research/archive/native/h4_binaries/h4pcheck',
        'cex/pac/comparator_cell.py': 'research/archive/pac/comparator_cell.py',
        'ext/comparator/merlin_adapter.py': 'research/comparators/legacy_ext/merlin_adapter.py',
        'bench/cells.py': 'research/comparators/legacy_cells.py',
        'bench/pgmax_mar.py': 'benchmarks/external/comparators/pgmax_mar.py',
        'ext/uai.py': 'benchmarks/external/tools/uai.py',
    }
    inv = {}
    for paths in PR.SOURCE_SCOPES.values():
        for logical in paths:
            path = root / locations.get(logical, logical)
            if path.is_file(): inv[logical] = hashlib.sha256(path.read_bytes()).hexdigest()
            elif path.is_dir():
                for child in sorted(path.iterdir()):
                    if child.is_file() and child.suffix in PR.SOURCE_EXTS:
                        inv[Path(logical).name + '/' + child.name] = hashlib.sha256(child.read_bytes()).hexdigest()
            else: inv[logical] = None
    inv.update(cqr_source_inventory(code_dir))
    return inv


def validator_of(arm): return ARMS[arm]['validator'] if arm in ARMS else None
def is_cqr_arm(arm): return arm in CQR_ARMS
def scope_of_key(key):
    if is_cqr_scope_key(key): return 'cqr_candidate'
    return PR.scope_of_key(key)


def suite_sha256(code_dir=CODE):
    root = Path(code_dir).resolve()
    if root.name == 'code': root = root.parent
    return hashlib.sha256((root / 'research/campaigns/cqr/qualification.py').read_bytes()).hexdigest()
