"""ONE authoritative TASK / ARM / REPRESENTATION registry for the PAC pass (candidate v4; review R06 / R07 of 13 Nov 2026). Every component (manifest producer,
dispatcher, offline references, gate, reporter, closeout, qualification) derives its cohort names, arm applicability, representation, guarantee contract and
output validator from THIS module; no second string list exists. Unsupported / unavailable entries are first-class rows (visible in every inventory table)."""
from fractions import Fraction as F

# ---- representations of the frozen inputs
REPRESENTATIONS = {
    'uai_table': dict(reader='core.read_uai', description='UAI MARKOV: finite nonnegative rational factor tables + .evid evidence; the accepted contract of the UAI task (all original singleton marginals)', reference='R0 brute force (exact rationals) when the free state space is small enough'),
    'cbi_block_json': dict(reader='cbi.model.Model.from_json', description='CBI coupled-block law (explicit supports, integer weights, product kernel by coupling r); native task: per-coordinate probabilities, width 1/100, delta 0', reference='cbi.exact (variable elimination, exact rationals) when affordable'),
    'sf_panel_json': dict(reader='sf.core.Law.load', description='sparse/Fourier two-block panel; native task: per-coordinate probabilities at coupling r, width in {1/100, 1/20}', reference='the SF route checker (transposed exact pair reconstruction) inside the invocation'),
    'h4_frozen_packet': dict(reader='h4a.arm (FROZEN_NODES.json + canonical model)', description='six frozen H4 arithmetic nodes (irrational tables, conditional target responses); native task: marker masses / node weights / responses per node', reference='the independent checker phase inside h4a/arm.py (producer vs checker kernels)'),
}

# ---- arms: representation they consume, kind, guarantee contract on success, and the output validator the gate applies
ARMS = {
    'B0_FROZEN_V14': dict(kind='primary', representation='uai_table', guarantee='DETERMINISTIC', validator='uai_candidate', identity_scope='b0_frozen_v14', task='all original singleton marginals (UAI)'),
    'P1_PAC_CONDITIONAL': dict(kind='primary', representation='uai_table', guarantee='DETERMINISTIC|PAC', validator='uai_candidate', identity_scope='candidate', task='all original singleton marginals (UAI)'),
    'H1_HYBRID': dict(kind='primary', representation='uai_table', guarantee='DETERMINISTIC|PAC', validator='uai_candidate', identity_scope='candidate', task='all original singleton marginals (UAI)'),
    'A0_POINT': dict(kind='ablation', representation='uai_table', guarantee='DETERMINISTIC|PAC', validator='uai_candidate', identity_scope='candidate', task='all original singleton marginals (UAI)'),
    'A1_CONDITIONAL': dict(kind='ablation', representation='uai_table', guarantee='DETERMINISTIC|PAC', validator='uai_candidate', identity_scope='candidate', task='all original singleton marginals (UAI)'),
    'LIBDAI_EXACT': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'LBP': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'WMB': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'IJGP': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'PGMAX_SUMPRODUCT_BP': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'MERLIN_CTE': dict(kind='comparator', representation='uai_table', guarantee='UNGUARANTEED', validator='comparator_mar', identity_scope='comparator', task='all original singleton marginals (UAI; binary64 point)'),
    'CBI_NATIVE': dict(kind='legacy_native', representation='cbi_block_json', guarantee='DETERMINISTIC', validator='cbi_native', identity_scope='cbi', task='per-coordinate probabilities of every block, width 1/100, delta 0 (cbi CLI solve)'),
    'H4_NATIVE_C': dict(kind='legacy_native', representation='h4_frozen_packet', guarantee='DETERMINISTIC', validator='h4_native', identity_scope='h4a', task='six frozen H4 nodes, arm C (h4a/arm.py); own contract 120 s per invocation'),
    'H4_NATIVE_PI': dict(kind='legacy_native', representation='h4_frozen_packet', guarantee='DETERMINISTIC', validator='h4_native', identity_scope='h4a', task='six frozen H4 nodes, arm PI (h4a/arm.py); own contract 120 s per invocation'),
    'H4_NATIVE_PP': dict(kind='legacy_native', representation='h4_frozen_packet', guarantee='DETERMINISTIC', validator='h4_native', identity_scope='h4a', task='six frozen H4 nodes, arm PP (h4a/arm.py); own contract 120 s per invocation'),
    'SF_NATIVE_SELECT': dict(kind='legacy_native', representation='sf_panel_json', guarantee='DETERMINISTIC', validator='sf_native', identity_scope='sf', task='coupled two-block per-coordinate probabilities at coupling r, requested width (sf/invoke.py select; cooperative deadline = budget)'),
}
CANDIDATE_ARMS = tuple(a for a, d in ARMS.items() if d['identity_scope'] == 'candidate')
COMPARATOR_ARMS = tuple(a for a, d in ARMS.items() if d['kind'] == 'comparator')
NATIVE_ARMS = tuple(a for a, d in ARMS.items() if d['kind'] == 'legacy_native')
UNAVAILABLE_ARMS = {'SAMPLESEARCH': 'UNAVAILABLE_BACKEND: x86-64 binary aborts under emulation, source does not build (six bounded historical attempts, EXTERNAL_SWEEP_2026-11-06/AVAILABILITY.json); no reimplementation', 'ACE': 'UNAVAILABLE_BACKEND: registration-gated download never obtained (comparator pass 2026-11-04)'}

# ---- cohorts: representation, the original task, which arms apply, the native query (if any) and how adapted results are scored
COHORTS = {
    'external_core': dict(order=0, representation='uai_table', original_task='all singleton marginals of the 46 UAI/bnlearn cases (+2 historically inaccessible slots, visible)', arms=('primary', 'comparator', 'ablation'), native_query=None, pooled_with_uai_numerator=True),
    'selector_transfer_additions': dict(order=1, representation='uai_table', original_task='all singleton marginals of Promedus_11 / Promedus_16', arms=('primary', 'comparator', 'ablation'), native_query=None, pooled_with_uai_numerator=True),
    'qgrid': dict(order=2, representation='uai_table', original_task='corner / centre singleton probabilities of the positive rational grids (covered by all singletons); joint / parity / influence queries UNSUPPORTED_TASK_ADAPTER', arms=('primary', 'comparator', 'ablation'), native_query=None, pooled_with_uai_numerator=False),
    'CBI_UAI': dict(order=3, representation='uai_table', original_task='CBI native per-coordinate probabilities, width 1/100, delta 0 (adapted: explicit-table UAI of the block law; linear image of the singleton rows scored on the native query; PAC results keep their delta)', arms=('primary', 'comparator', 'ablation'), native_query=dict(widths=('1/100',), mapping='legacy_cbi_uai.native_score', metadata='blocks_path / blocks_sha256 (external block ids preserved)'), pooled_with_uai_numerator=False),
    'SF_small': dict(order=4, representation='uai_table', original_task='SF small_control per-coordinate probabilities at 8 couplings, widths 1/100 and 1/20 (adapted: explicit 128 x 128 table; scored at BOTH native widths)', arms=('primary', 'comparator', 'ablation'), native_query=dict(widths=('1/100', '1/20'), mapping='legacy_cbi_uai.native_score', metadata='blocks_path / blocks_sha256'), pooled_with_uai_numerator=False),
    'CBI': dict(order=5, representation='cbi_block_json', original_task='CBI native contract (23 retained pass-2 instances): per-coordinate probabilities, width 1/100, delta 0', arms=('legacy_native',), native_arms=('CBI_NATIVE',), native_query=dict(widths=('1/100',)), pooled_with_uai_numerator=False),
    'H4_native': dict(order=6, representation='h4_frozen_packet', original_task='H4 six frozen arithmetic nodes, arms C / PI / PP (NARROWER than the historical eight complete-query workloads; disclosed)', arms=('legacy_native',), native_arms=('H4_NATIVE_C', 'H4_NATIVE_PI', 'H4_NATIVE_PP'), native_query=dict(widths=('own contract',)), pooled_with_uai_numerator=False),
    'SF_native': dict(order=7, representation='sf_panel_json', original_task='SF selector on 4 panels x 8 couplings x 2 widths', arms=('legacy_native',), native_arms=('SF_NATIVE_SELECT',), native_query=dict(widths=('1/100', '1/20')), pooled_with_uai_numerator=False),
}
COHORT_ORDER = tuple(sorted(COHORTS, key=lambda k: COHORTS[k]['order']))
UAI_COHORTS = tuple(k for k, v in COHORTS.items() if v['representation'] == 'uai_table')
ADAPTED_COHORTS = tuple(k for k, v in COHORTS.items() if v['native_query'] and v['representation'] == 'uai_table')

# ---- the qualification suite's exact group schema (closeout requires EXACTLY these names, all ok)
QUALIFICATION_GROUPS = ('Q1_identity_and_gate_end_to_end', 'Q2_exact_cell_oracle', 'Q3_laws_moments_and_actual_adaptive_accumulation', 'Q4_frontier_invariants_and_rebase_histories', 'Q5_actual_sampling_backend', 'Q6_confidence_arithmetic', 'Q7_numerical_publication_truth_asserted', 'Q8_intersection_and_mechanism_sensitivity', 'Q9_continuation_every_backend_class', 'Q10_existing_defects_isolated', 'Q11_diagnostic_coverage_attempted_runs', 'Q12_exact_closure_partial_cover_sensitivity', 'Q13_registry_pipeline_every_arm_complete')

# ---- the REQUIRED frozen source inventory (identity scopes -> directories under code/cex or code/)
SOURCE_SCOPES = {'candidate': ('cex/pac', 'cex/newarm'), 'b0_frozen_v14': ('cex/b0_frozen_v14',), 'supervisor': ('gbidi/supervise.py',), 'native_cbi': ('cbi',), 'native_sf': ('sf',), 'native_h4': ('h4a', 'build/h4rect', 'build/h4point', 'build/h4pcheck'), 'comparator_glue': ('cex/pac/comparator_cell.py', 'ext/comparator/merlin_adapter.py', 'bench/cells.py', 'bench/pgmax_mar.py', 'ext/uai.py')}      # v4.2: the EXECUTED PGMax glue (factor slicing / merging / log-potentials / BP configuration) and the UAI reader every adapter imports are part of the experiment identity (fifth review R03)
SOURCE_EXTS = ('.py', '.cpp', '.sh', '.h', '.hpp', '.c')
SOURCE_BINARIES = ('build/h4rect', 'build/h4point', 'build/h4pcheck')      # native executables actually invoked by h4a/arm.py: identity frozen by content hash; rebuilt binaries change the identity (documented runtime assumption: the recorded hash is the one that ran)
# ---- v4.2 (fifth review, identity gap): a REQUIRED artifact whose identity is None (absent on the host) can never qualify a manifest that plans an arm needing it;
# artifacts needed by no planned arm are reported as UNAVAILABLE (scoped), never silently accepted as equal None entries
ARTIFACT_REQUIRED_BY = {'build/h4rect': ('H4_NATIVE_C', 'H4_NATIVE_PI', 'H4_NATIVE_PP'), 'build/h4point': ('H4_NATIVE_C', 'H4_NATIVE_PI', 'H4_NATIVE_PP'), 'build/h4pcheck': ('H4_NATIVE_C', 'H4_NATIVE_PI', 'H4_NATIVE_PP')}


def artifact_required(key, planned_arms):
    """True when the artifact `key` must carry a valid identity for the given planned arms: every source file is always required; a native executable is required
    exactly when an arm that invokes it is planned"""
    need = ARTIFACT_REQUIRED_BY.get(key)
    if need is None: return True
    return any(a in need for a in planned_arms)


def identity_failures(inventory, planned_arms):
    """(failures, unavailable): inventory entries that are None / not a sha256 hex digest for a REQUIRED artifact are failures; None entries of artifacts no planned arm
    needs are returned as scoped unavailable artifacts"""
    import re
    fails = []; unavailable = []
    for k, v in sorted(inventory.items()):
        ok = isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v) is not None
        if ok: continue
        if artifact_required(k, planned_arms): fails.append('required artifact %s has no valid identity (%r): a null identity never qualifies a manifest that plans an arm needing it' % (k, v))
        else: unavailable.append(k)
    return fails, unavailable


def arms_for_cohort(cohort, primary, comparators, ablation):
    """the (arm, repetitions, kind) triples a cohort schedules, from the registry (no cohort-specific lists elsewhere)"""
    spec = COHORTS[cohort]; out = []
    if 'primary' in spec['arms']: out += [(a, r, 'primary') for a, r in primary]
    if 'comparator' in spec['arms']: out += [(a, r, 'comparator') for a, r in comparators]
    if 'ablation' in spec['arms']: out += [(a, r, 'ablation') for a, r in ablation]
    return out


def validator_of(arm): return ARMS[arm]['validator'] if arm in ARMS else None


def source_inventory(code_dir, scopes=None):
    """{key: sha256} of every required frozen source under the given identity scopes (default: all); keys are 'pac/x.py', 'newarm/y.cpp', 'b0_frozen_v14/z.py', 'gbidi/supervise.py'"""
    import os, hashlib
    out = {}
    for scope, dirs in SOURCE_SCOPES.items():
        if scopes is not None and scope not in scopes: continue
        for d in dirs:
            p = os.path.join(code_dir, d)
            if os.path.isfile(p): out[d] = hashlib.sha256(open(p, 'rb').read()).hexdigest(); continue
            if not os.path.isdir(p): out[d] = None; continue                        # a REQUIRED artifact that is absent is recorded as None (the gate refuses a None identity)
            tag = os.path.basename(d)
            for f in sorted(os.listdir(p)):
                if f.endswith(SOURCE_EXTS) and os.path.isfile(os.path.join(p, f)): out['%s/%s' % (tag, f)] = hashlib.sha256(open(os.path.join(p, f), 'rb').read()).hexdigest()
    return out


def scope_of_key(key):
    if key in ('cex/pac/comparator_cell.py', 'ext/comparator/merlin_adapter.py', 'bench/cells.py', 'bench/pgmax_mar.py', 'ext/uai.py'): return 'comparator_glue'
    head = key.split('/', 1)[0]
    return {'pac': 'candidate', 'newarm': 'candidate', 'b0_frozen_v14': 'b0_frozen_v14', 'gbidi': 'supervisor', 'cbi': 'native_cbi', 'sf': 'native_sf', 'h4a': 'native_h4', 'build': 'native_h4'}.get(head)


# ---- arm EXECUTION SEMANTICS (review 4 F04): what a PAC component of each candidate arm may look like; the gate binds the recorded design to the planned arm
ARM_SEMANTICS = {
    'P1_PAC_CONDITIONAL': dict(mode='conditional', resolve=True, forced=True, deterministic_routes=('pac_conditional_exact_cover_complete', 'pac_conditional_deterministic_partial_cover_bounds', 'pac_conditional_uniform_factorless_component'), pac_routes=('pac_conditional',), root_routes=(), zero_proof_kinds=('reduction', 'component_restriction', 'pac_root_bound', 'pac_exact_cover')),
    'H1_HYBRID': dict(mode='conditional', resolve=True, forced=False, deterministic_routes=('pac_conditional_exact_cover_complete', 'pac_conditional_deterministic_partial_cover_bounds', 'pac_conditional_uniform_factorless_component', 'support', 'stream', 'dag', 'forest'), pac_routes=('pac_conditional',), root_routes=('forest', 'dag'), zero_proof_kinds=('forest', 'reduction', 'component_restriction', 'exact_component', 'pac_root_bound', 'pac_exact_cover')),
    'A0_POINT': dict(mode='point', resolve=False, forced=False, deterministic_routes=('pac_point_uniform_factorless_component',), pac_routes=('pac_point',), root_routes=(), zero_proof_kinds=('reduction', 'component_restriction', 'pac_root_bound')),
    'A1_CONDITIONAL': dict(mode='conditional', resolve=False, forced=False, deterministic_routes=('pac_conditional_exact_cover_complete', 'pac_conditional_deterministic_partial_cover_bounds', 'pac_conditional_uniform_factorless_component'), pac_routes=('pac_conditional',), root_routes=(), zero_proof_kinds=('reduction', 'component_restriction', 'pac_root_bound', 'pac_exact_cover'), empty_cutset_exception='an empty cutset in conditional mode resolves its single cell (one contraction closes the cover): resolve=True is legitimate for A1 exactly then'),
}


def permitted_resolution(arm, mode, cutset):
    """the ONE rule deciding whether an execution of `arm` may insert evaluated cells into the resolved region: the arm's resolve flag, or the empty-cutset closure
    of conditional mode (the engine resolves the single root cell for every conditional arm: engine.run_component `if mode == 'conditional' and not cut: resolve = True`)"""
    sem = ARM_SEMANTICS[arm]
    return bool(sem['resolve']) or (mode == 'conditional' and sem['mode'] == 'conditional' and not list(cutset or []))


def execution_semantics_failure(arm, family, route=None, design=None, resolved_leaves=None, contribution_cells=None, resolved_cells=None, zero_kind=None, cutset=None):
    """COMMON execution-semantics invariant for EVERY terminal family of a candidate arm (fifth review R04). Returns a failure message or None.
    family in {'pac', 'cover', 'factorless', 'frozen', 'root', 'zero'}:
      pac        -- a statistical publication: route in pac_routes; design mode = arm mode; design.resolve = permitted_resolution; resolved leaves / contribution records /
                    resolved_cells agree (all zero when resolution is not permitted);
      cover      -- a deterministic exact / partial cover: route in deterministic_routes; design mode = arm mode; resolution MUST be permitted (a cover resolves cells);
                    design.resolve True; resolved leaves = contribution records = resolved_cells >= 1;
      factorless -- the uniform factorless route of the arm's mode: empty cutset, no resolution claimed;
      frozen     -- a frozen executor route (support / stream / dag / forest) on a component: must be in deterministic_routes (H1 only);
      root       -- a whole-model root route: must be in root_routes (H1 only);
      zero       -- a zero-evidence proof: kind in zero_proof_kinds; a pac_exact_cover zero proof resolves cells and so needs permitted resolution for its cutset."""
    sem = ARM_SEMANTICS.get(arm)
    if sem is None: return 'arm %s has no execution semantics' % arm
    d = design or {}; nl = resolved_leaves; nc = contribution_cells; rc = resolved_cells
    if family == 'pac':
        if route not in sem['pac_routes']: return 'statistical route %s is not a PAC route of arm %s' % (route, arm)
        if d.get('mode') != sem['mode']: return 'design mode %s differs from the arm mode %s' % (d.get('mode'), sem['mode'])
        perm = permitted_resolution(arm, d.get('mode'), d.get('cutset'))
        if bool(d.get('resolve')) != perm: return 'design.resolve %s but the planned arm %s permits resolution = %s for cutset %s' % (d.get('resolve'), arm, perm, d.get('cutset'))
        if not perm and (nl or nc or rc): return 'arm %s must not resolve cells (cutset %s) yet %s leaves / %s contribution records / %s resolved cells are recorded' % (arm, d.get('cutset'), nl, nc, rc)
        if perm and rc is not None and rc != nl: return 'design and frontier disagree (%s resolved leaves recorded in the frontier, resolved_cells %s)' % (nl, rc)
        return None                                  # the frontier <-> contribution BIJECTION is verified by gate.verify_cover (precise per-record messages)
    if family == 'cover':
        if route not in sem['deterministic_routes'] or not str(route).startswith('pac_'): return 'cover route %s is not available to the planned arm %s' % (route, arm)
        if d.get('mode') != sem['mode']: return 'design mode %s differs from the arm mode %s' % (d.get('mode'), sem['mode'])
        perm = permitted_resolution(arm, d.get('mode'), d.get('cutset'))
        if not perm: return 'the planned arm %s does not resolve cells for cutset %s, yet a deterministic cover (%s) is claimed' % (arm, d.get('cutset'), route)
        if not d.get('resolve'): return 'deterministic cover with design.resolve = %s' % d.get('resolve')
        if not nl or (rc is not None and rc != nl): return 'cover: design and frontier disagree (%s resolved leaves recorded in the frontier, resolved_cells %s)' % (nl, rc)
        return None                                  # the frontier <-> contribution BIJECTION is verified by gate.verify_cover
    if family == 'factorless':
        if route != 'pac_%s_uniform_factorless_component' % sem['mode'] or route not in sem['deterministic_routes']: return 'factorless route %s is not the uniform route of arm %s' % (route, arm)
        if list(d.get('cutset') or []) or nl or nc or rc: return 'factorless component claims a cutset or resolved cells'
        return None
    if family == 'frozen':
        return None if (route in sem['deterministic_routes'] and not str(route).startswith('pac_')) else 'frozen executor route %s is not available to the planned arm %s' % (route, arm)
    if family == 'root':
        return None if route in sem['root_routes'] else 'whole-model root route %s is not available to the planned arm %s' % (route, arm)
    if family == 'zero':
        if zero_kind not in sem['zero_proof_kinds']: return 'zero-proof kind %s is not available to the planned arm %s' % (zero_kind, arm)
        if zero_kind == 'pac_exact_cover' and not permitted_resolution(arm, 'conditional' if sem['mode'] == 'conditional' else 'point', cutset): return 'a pac_exact_cover zero proof resolves cells, which arm %s does not permit for cutset %s' % (arm, cutset)
        return None
    return 'unknown terminal family %s' % family
