"""CQR CAMPAIGN CHAIN -- manifest producer + dispatcher (candidate CQR; composition over the FROZEN baseline chain cex/pac/campaign.py, which is imported, never edited).
`manifest` FREEZES the complete matrix (explicit input rows incl. UNAVAILABLE rows, arms per cohort from a `plan`, budgets, replicates, seeds, ordering rule, the complete
frozen source inventory registry.full_inventory(), prospective ceiling) BEFORE any scored run; `run` executes the frozen cells sequentially, each in a fresh attempt directory
with a nonce, under the project supervisor (gbidi.supervise; since 16 Nov 2026 it also RETAINS a description of every process found alive in the owned group after the leader's exit, before killing it -- policy unchanged; 3 GiB sampled process-tree RSS, interval 0.05 s, timeout = budget + 1 s cleanup grace, caffeinate -s).
The baseline arms run EXACTLY the command lines of cex/pac/campaign.py (B0 evaluate.py --worker, pac worker.py, cbi.cli, h4a/arm.py, sf/invoke.py, comparator_cell.py);
the CQR arms run cex/cqr/worker.py. A receipt is written once; a crashed campaign resumes by skipping cells whose receipt exists (the manifest is immutable).
    python cex/cqr/campaign.py run <RD> [--dev] [--only COHORT] [--max-cells N]
(the manifest is produced programmatically: manifest(RD, rows, dev, dev_restrictions, budgets, plan); rows from make_row(...))"""
import sys, os, json, time, hashlib, secrets, subprocess, math, glob, platform, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__)); CEX = os.path.dirname(HERE); CODE = os.path.dirname(CEX); PAC = os.path.join(CEX, 'pac'); NEWARM = os.path.join(CEX, 'newarm'); PY = sys.executable
# ---- module binding order (bare module names collide between cex/pac and cex/cqr: registry / solve / gate / report / campaign): the BASELINE registry and the shared reader
# bind the bare names `registry` / `core` first (PAC, NEWARM, CODE ahead of this directory); then this directory shadows the baseline for the CQR modules (solve, task, ...)
for _p in (CODE, NEWARM, PAC):
    if _p in sys.path: sys.path.remove(_p)
    sys.path.insert(0, _p)
import registry as PR, core
if HERE in sys.path: sys.path.remove(HERE)
sys.path.insert(0, HERE)
import solve as SV, task as TK


def load_module(name, path):
    """load a file as a module under a NON-colliding name (cqr_registry, pac_campaign, pac_gate): both registries / gates coexist in one process"""
    if name in sys.modules: return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m


R = load_module('cqr_registry', os.path.join(HERE, 'registry.py'))
PC = load_module('pac_campaign', os.path.join(PAC, 'campaign.py'))          # the baseline producer / dispatcher: command-line constants, ensure_h4_native_build
if HERE in sys.path: sys.path.remove(HERE)
sys.path.insert(0, HERE)                                                   # pac campaign re-inserted PAC at the front; the CQR directory stays first for later bare imports
import kernel_identity as KI                                               # frozen identity of EVERY natively loaded artifact (binaries + build records; CQR-09)
CAMPAIGN_VERSION = 'cqr-campaign-v2 (2026-11-16; kernel identity frozen, balanced arm blocks, no second-matrix contingency)'
MANIFEST_SCHEMA = 'cqr_campaign_manifest_v1'
KINDS = ('cqr_primary', 'cqr_ablation', 'legacy_primary', 'comparator', 'legacy_native', 'cqr_normalizer')
BUDGETS = [20.0, 120.0]
REPLAY_FACTOR = 3.0
TASK = dict(epsilon='1/200', delta='1/1000000', delta_allocation='delta/2 ratio stream; delta/(2 e (e+1)) validation epoch e (CQR); per coordinate family_delta/K (baseline PAC arms)', deterministic_delta='0', note='campaign default; a row whose frozen query spec declares its own mode / epsilon / delta carries them in task_params (the gate verifies the certificate against the row declaration)')
LEDGER = 'CQR_LEDGER.jsonl'
PAC_CANDIDATE_ARMS = tuple(PR.CANDIDATE_ARMS)
KERNEL_RECORDS = {'newarm': (os.path.join(NEWARM, 'cex_build.json'), os.path.join(NEWARM, 'libcex_kernel.dylib'), PAC_CANDIDATE_ARMS), 'b0_frozen_v14': (os.path.join(CEX, 'b0_frozen_v14', 'cex_build.json'), os.path.join(CEX, 'b0_frozen_v14', 'libcex_kernel.dylib'), ('B0_FROZEN_V14',))}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def effective_paths(model_path):
    """the reader's effective files: <model>.evid (present or absent; absent = empty evidence, hash of b'0') and the optional <model>.query.json"""
    mp = os.path.abspath(model_path); return mp, mp + '.evid', mp + '.query.json'


def evidence_hash(ep): return hashlib.sha256(open(ep, 'rb').read() if os.path.exists(ep) else b'0').hexdigest()


def task_params_of(qp):
    """the frozen task declaration of a row: mode / epsilon / delta / normalizer / all_singletons / query count from the query spec (defaults = the legacy all-singleton PAC contract)"""
    if not qp or not os.path.exists(qp): return dict(mode='PAC_EPS', epsilon='1/200', delta='1/1000000', normalizer_task=False, all_singletons=True, declared_queries=None, source='absent query spec: all original singleton marginals (legacy contract)')
    spec = json.load(open(qp)); qs = spec.get('queries') or []
    return dict(mode=spec.get('mode', 'PAC_EPS'), epsilon=str(spec.get('epsilon', '1/200')), delta=str(spec.get('delta', '1/1000000')), normalizer_task=bool(spec.get('normalizer_task')), all_singletons=all(q.get('kind') == 'all_singletons' for q in qs) if qs else False, declared_queries=len(qs), query_kinds=sorted({q.get('kind') for q in qs}), source='query spec')


def make_row(cohort, case_id, model_path, task=None, status=None, **meta):
    """one explicit INPUT ROW: effective evidence / query files, content hashes (an absent .evid is the empty-evidence task, hash of b'0'), the frozen task declaration, origin metadata"""
    mp, ep, qp = effective_paths(model_path); ok = os.path.exists(mp); has_q = os.path.exists(qp)
    row = dict(cohort=cohort, case_id=case_id, model_path=mp, evidence_path=ep, query_path=(qp if has_q else None), model_sha256=(sha(mp) if ok else None), evidence_sha256=evidence_hash(ep), query_sha256=(sha(qp) if has_q else None),
               evidence_present=os.path.exists(ep), task=task or ('declared query schedule (%s)' % os.path.basename(qp) if has_q else 'all original singleton marginals under original evidence'), status=status or ('AVAILABLE_HASH_RECORDED' if ok else 'UNAVAILABLE_INPUT'), task_params=(task_params_of(qp) if ok else None))
    row.update(meta); return row


def validate_row(row):
    """refuse rows whose declared files are not the reader's effective files or whose hashes differ from disk (one effective-input resolver)"""
    for k in ('cohort', 'case_id', 'status'):
        if k not in row: raise SystemExit('refuse: row without %s: %r' % (k, row))
    if row['cohort'] not in R.COHORTS: raise SystemExit('refuse: row %s names a cohort not in the registry (%s)' % (row['case_id'], row['cohort']))
    mp = row.get('model_path')
    if not mp or not row.get('model_sha256'): return False                                   # UNAVAILABLE row: inventoried, never scheduled
    mp_, ep, qp = effective_paths(mp)
    if os.path.abspath(row.get('evidence_path') or '') != ep: raise SystemExit('refuse: row %s declares evidence_path %s, not the reader\'s effective evidence file %s' % (row['case_id'], row.get('evidence_path'), ep))
    if not os.path.exists(mp_): raise SystemExit('refuse: row %s model file missing on disk' % row['case_id'])
    if sha(mp_) != row['model_sha256']: raise SystemExit('refuse: row %s model_sha256 differs from the file on disk' % row['case_id'])
    if evidence_hash(ep) != row.get('evidence_sha256'): raise SystemExit('refuse: row %s evidence_sha256 differs from the effective evidence file (present / absent / changed)' % row['case_id'])
    if os.path.exists(qp):
        if os.path.abspath(row.get('query_path') or '') != qp or row.get('query_sha256') != sha(qp): raise SystemExit('refuse: row %s has a query spec on disk that the row does not declare / hash correctly' % row['case_id'])
    elif row.get('query_path') is not None or row.get('query_sha256') is not None: raise SystemExit('refuse: row %s declares a query spec that is not on disk' % row['case_id'])
    return True


def kind_of(arm, row):
    if arm in R.CQR_ARMS:
        if (row.get('task_params') or {}).get('normalizer_task'): return 'cqr_normalizer'
        return 'cqr_primary' if R.CQR_ARMS[arm]['kind'] == 'primary' else 'cqr_ablation'
    if arm not in PR.ARMS: raise SystemExit('refuse: arm %s is in no registry' % arm)
    return {'primary': 'legacy_primary', 'ablation': 'legacy_primary', 'comparator': 'comparator', 'legacy_native': 'legacy_native'}[PR.ARMS[arm]['kind']]


def arm_order(arm):
    if arm == 'N1_CQR': return 0
    if arm == 'G0_CQR': return 1
    if arm in R.CQR_ARMS: return 2 + sorted(R.CQR_ARMS).index(arm)
    base = {'B0_FROZEN_V14': 20, 'P1_PAC_CONDITIONAL': 21, 'H1_HYBRID': 22, 'A0_POINT': 23, 'A1_CONDITIONAL': 24}
    if arm in base: return base[arm]
    if arm in PR.COMPARATOR_ARMS: return 30 + list(PR.COMPARATOR_ARMS).index(arm)
    return 40 + (list(PR.NATIVE_ARMS).index(arm) if arm in PR.NATIVE_ARMS else 9)


# ---- balanced arm blocks (review of 16 Nov 2026). The draft (docs/handoff-received-2026-11-15-cqr/packet/benchmark_expansion.txt, resource contract) states verbatim:
#      "Run arm order in predeclared balanced blocks to reduce host-temperature/order bias."
# The producer previously sorted (arm, replicate), i.e. every N1 replicate before the first G0 replicate. Now, within one (cohort, case, budget):
# block k holds replicate k of EVERY planned arm of that case/budget (a complete block); blocks ascend; inside a block the predeclared arm order (arm_order:
# N1_CQR, G0_CQR, ablations, B0, P1, H1, A0, A1, comparators, natives) is used for even k and REVERSED for odd k (ABBA counterbalancing), so that over
# an even replicate count every arm occupies the first and the last position of a block equally often. Nothing depends on timing or on results.
ORDERING_RULE = ('sorted by (cohort order, case, budget); within a case/budget BALANCED ARM BLOCKS: block k = replicate k of every planned arm (complete block), blocks '
                 'ascending; arm order inside a block = N1_CQR, G0_CQR, CQR ablations, B0, P1, H1, A0, A1, comparators in registry order, natives for even k and the '
                 'reverse for odd k (ABBA counterbalancing), with the initial orientation of each CASE predeclared by the parity of sha256(case_id): this is predeclared and results-independent but does NOT guarantee exact global first-position balance (the parities of the planned case ids decide the actual split); strictly sequential. Draft: "Run arm order in predeclared balanced blocks to reduce host-temperature/order bias."')
ARM_ORDER_SPAN = 100                                                         # arm_order() values lie in [0, 50); the reversal maps o -> SPAN - o


def case_parity(case_id):
    """predeclared initial orientation of a case's first block: the parity of sha256(case_id) (fixed before any run; independent of results and timing), so that with an odd
    replicate count (AB/BA/AB) the first arm of a case's first block alternates ACROSS cases campaign-wide (second review, preparation item)"""
    return int(hashlib.sha256(str(case_id).encode()).hexdigest(), 16) % 2


def block_key(c):
    """(replicate block, position inside the block) for one cell; the block alternates the predeclared arm order (ABBA), starting from the case's predeclared orientation"""
    o = arm_order(c['arm']); k = int(c['replicate']); flip = (k + case_parity(c['case_id'])) % 2
    return (k, o if flip == 0 else ARM_ORDER_SPAN - o)


def kernel_identity_failures(planned_arms):
    """the frozen kernel BINARIES the baseline workers load (cex/newarm, cex/b0_frozen_v14): an absent / foreign binary makes the frozen worker REBUILD and rewrite the frozen
    build record inside a scored attempt; a manifest planning such an arm is refused until the pinned binary (sha256 of cex_build.json) is present"""
    fails = []; rec = {}
    for tag, (record, lib, arms) in KERNEL_RECORDS.items():
        if not any(a in arms for a in planned_arms): continue
        if not os.path.exists(record): fails.append('%s: kernel build record %s missing' % (tag, record)); continue
        want = json.load(open(record)).get('binary_sha256'); got = sha(lib) if os.path.exists(lib) else None
        rec[tag] = dict(record=record, binary=lib, record_binary_sha256=want, binary_sha256_on_disk=got)
        if got != want: fails.append('%s: the pinned kernel binary %s is %s (record %s): the frozen worker would rebuild and rewrite %s inside a scored attempt' % (tag, lib, ('absent' if got is None else 'foreign (%s)' % got[:12]), str(want)[:12], os.path.basename(record)))
    return fails, rec


def manifest(RD, rows, dev=False, dev_restrictions=None, budgets=None, plan=None, arms_by_cohort=None, root_seed=None, budgets_by_cohort=None):
    """rows: explicit input rows (make_row); plan: {cohort: [(arm, repetitions), ...]} (alias arms_by_cohort); budgets: list of seconds. Writes RD/CAMPAIGN_MANIFEST[_dev].json (refuses if it exists)."""
    plan = dict(plan or arms_by_cohort or {}); DR = dict(dev_restrictions or {}); budgets = [float(b) for b in (budgets or BUDGETS)]
    if DR and not dev: raise SystemExit('refuse: dev_restrictions are only allowed on a DEV manifest')
    if not plan: raise SystemExit('refuse: empty plan (cohort -> [(arm, repetitions)])')
    RD = os.path.abspath(RD); os.makedirs(RD, exist_ok=True); p = os.path.join(RD, 'CAMPAIGN_MANIFEST%s.json' % ('_dev' if dev else ''))
    if os.path.exists(p): raise SystemExit('refuse: %s exists (a frozen manifest is immutable; use a new run directory)' % p)
    for coh, arms in plan.items():
        if coh not in R.COHORTS: raise SystemExit('refuse: plan names cohort %s not in the registry' % coh)
        for arm, reps in arms:
            if arm not in R.ARMS: raise SystemExit('refuse: plan names arm %s not in the registry' % arm)
            if arm in R.UNAVAILABLE_ARMS: raise SystemExit('refuse: plan names an UNAVAILABLE arm %s' % arm)
    rows = [dict(r) for r in rows]; avail = [r for r in rows if validate_row(r)]
    ids = [r['case_id'] for r in rows]
    if len(ids) != len(set(ids)): raise SystemExit('refuse: duplicate case ids in the rows')
    root_seed = root_seed or secrets.token_hex(16); cells = []
    def mk(row, arm, rep, budget, kind):
        cid = hashlib.sha256('|'.join([row['case_id'], arm, str(rep), str(budget), kind]).encode()).hexdigest()[:16]
        seeded = (arm in R.CQR_ARMS) or (arm in PAC_CANDIDATE_ARMS)       # B0 / comparators / natives are deterministic configurations (no seed), as in the baseline producer
        seed = hashlib.sha256('|'.join([root_seed, row.get('model_sha256') or '', row.get('evidence_sha256') or '', row.get('query_sha256') or '', arm, str(budget), str(rep)]).encode()).hexdigest() if seeded else None
        return dict(cell_id=cid, cohort=row['cohort'], case_id=row['case_id'], arm=arm, replicate=rep, budget_s=budget, kind=kind, model_path=row.get('model_path'), evidence_path=row.get('evidence_path'), query_path=row.get('query_path'), model_sha256=row.get('model_sha256'), evidence_sha256=row.get('evidence_sha256'), query_sha256=row.get('query_sha256'), seed=seed, task=row.get('task'), task_params=row.get('task_params'),
                    blocks_path=row.get('blocks_path'), blocks_sha256=row.get('blocks_sha256'), native_arm=row.get('native_arm'), packet=row.get('packet'), sf_r=row.get('sf_r'), sf_eps=row.get('sf_eps'), panel=row.get('panel'))
    for row in avail:
        for arm, reps in plan.get(row['cohort'], []):
            kind = kind_of(arm, row)
            if kind == 'legacy_native' and arm != row.get('native_arm_name', arm): continue
            for budget in [float(b) for b in (budgets_by_cohort or {}).get(row['cohort'], budgets)]:        # a cohort may carry its own budgets (natives at their contract budgets)
                for rep in range(int(reps)): cells.append(mk(row, arm, rep, budget, kind))
    order_coh = {k: R.COHORTS[k]['order'] for k in R.COHORTS}
    cells.sort(key=lambda c: (order_coh[c['cohort']], c['case_id'], c['budget_s']) + block_key(c))
    for i, c in enumerate(cells): c['order_index'] = i
    ids_ = [c['cell_id'] for c in cells]
    if len(ids_) != len(set(ids_)): raise SystemExit('refuse: duplicate cell ids')
    planned_arms = sorted({c['arm'] for c in cells})
    artifact = R.full_inventory(CODE)
    id_fail, unavailable_artifacts = PR.identity_failures(artifact, planned_arms)
    if id_fail: raise SystemExit('refuse: ' + '; '.join(id_fail))
    k_fail, kernel_rec = kernel_identity_failures(planned_arms)
    if k_fail: raise SystemExit('refuse: ' + '; '.join(k_fail))
    kernel_identity = KI.collect(CODE)                                     # EVERY natively loaded artifact: binary sha256 + build-record FILE sha256 + the record's inner claim
    ki_fail = KI.failures_vs_frozen(kernel_identity, kernel_identity, planned_arms)
    if ki_fail: raise SystemExit('refuse: kernel identity not freezable: ' + '; '.join(ki_fail))
    nominal = sum(c['budget_s'] for c in cells); n = len(cells); orch = 2 * n + max(600, math.ceil(0.05 * nominal))
    ver_cells = [c for c in cells if c['kind'] in ('cqr_primary', 'cqr_ablation', 'cqr_normalizer', 'legacy_primary', 'legacy_native')]
    verification = REPLAY_FACTOR * sum(c['budget_s'] for c in ver_cells)
    # ceiling = ALLOWANCE (hard upper allocation), the same accounting as resolve_design.py: fixed stages + solver nominal + per-child cleanup/kill (5 s x cells) + verification
    # (REPLAY_FACTOR x the guaranteed cells' budgets). Review of 16 Nov 2026: the previous formula reserved a second full matrix (2 x (nominal + orchestration)) for a
    # 'correctness contingency' that the draft explicitly excludes; resolve_design.py: 'no implicit second-matrix contingency is reserved'. Both formulas are recorded below.
    FIXED = 3600 + 3600 + 7200 + 3600; cleanup = 5 * n
    old_formula = '(3600 availability + 3600 qualification + 7200 references + 3600 report/closeout/package) + verification + 2 x (scored matrix nominal + orchestration); the second matrix is reserved for one correctness contingency'
    new_formula = '(3600 availability + 3600 qualification + 7200 references + 3600 report/closeout/package) + scored matrix nominal + 5 s x cells (per-child cleanup/kill) + verification; no implicit second-matrix contingency is reserved (a correctness contingency needs a new manifest and a new decision)'
    ceiling = dict(availability_environment_build_total_seconds=3600, qualification_total_seconds=3600, offline_reference_total_seconds=7200.0, verification_stage_seconds=verification,
                   verification_stage_rule='aggregate cap for gate.py (--gate-budget-s) = REPLAY_FACTOR (%.1f) x sum of the budgets of every cqr / legacy_primary / legacy_native cell (%d cells); per cell the checker stops at REPLAY_FACTOR x the cell budget; exhaustion is a structured UNVERIFIABLE result' % (REPLAY_FACTOR, len(ver_cells)),
                   reporting_closeout_packaging_total_seconds=3600, scored_matrix_seconds=nominal, per_child_cleanup_kill_seconds=cleanup, orchestration_seconds=orch,
                   orchestration_note='orchestration_seconds (2 s x cells + max(600, 5 %% of nominal)) is an informational forecast of dispatcher overhead, NOT a term of the allowance; the allowance term is per_child_cleanup_kill_seconds as in resolve_design.py',
                   total_ceiling_seconds=FIXED + nominal + cleanup + verification, formula=new_formula, statement='ALLOWANCES (hard upper allocations), not runtime forecasts or predictions; no implicit second-matrix contingency is reserved',
                   formula_change_2026_11_16=dict(old_formula=old_formula, old_total_seconds=18000 + verification + 2 * (nominal + orch), new_formula=new_formula, new_total_seconds=FIXED + nominal + cleanup + verification,
                                                  reason='adversarial review of 16 Nov 2026: the executable ceiling reserved a second full matrix contrary to the draft; aligned with resolve_design.py allowance (solver_nominal + 5 x cells + 3 x guaranteed nominal + fixed 18000)'))
    ceiling['formula_change_2026-11-16'] = ceiling['formula_change_2026_11_16']
    arms_rec = {a: dict(kind=d['kind'], representation=d['representation'], guarantee=d['guarantee'], validator=d['validator'], identity_scope=d['identity_scope'], task=d.get('task'), feature_flags=d.get('feature_flags'), role=d.get('role')) for a, d in R.ARMS.items()}
    man = dict(schema=MANIFEST_SCHEMA, campaign_version=CAMPAIGN_VERSION, registry_version=R.REGISTRY_VERSION, frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), dev=dev, dev_restrictions=(DR or None), host=dict(platform=platform.platform(), machine=platform.machine(), python=sys.version, cpu_count=os.cpu_count()),
               inventory=rows, task=dict(TASK), arms=dict(registry=arms_rec, cqr_arms=sorted(R.CQR_ARMS), plan={k: [[a, int(r)] for a, r in v] for k, v in plan.items()}, unavailable=dict(R.UNAVAILABLE_ARMS), kinds=list(KINDS), legacy_ablation_note='baseline ablation arms (A0 / A1), if planned, are scheduled under kind legacy_primary'),
               cohorts={k: dict(order=v['order'], representation=v['representation'], original_task=v['original_task'], arms=list(v['arms']), comparison=v.get('comparison')) for k, v in R.COHORTS.items()}, budgets_s=sorted(set(budgets)), budgets_by_cohort={k: [float(b) for b in v] for k, v in (budgets_by_cohort or {}).items()},
               resource_contract=dict(memory='3 GiB sampled process-tree RSS kill (interval 0.05 s), identical for every arm; RLIMIT_AS requested by the CQR worker', clock='launch-relative absolute deadline on the host monotonic clock; host sleep prohibited (caffeinate -s)', cleanup_grace_s=1.0, supervisor_internal_grace_s=4.0, actual_kill_threshold_s='budget + 5', late_output_counts_as_success=False, threads='single worker at a time; OMP/BLAS threads 1'),
               seeds=dict(root_seed=root_seed, generation='sha256(root | model_sha | evidence_sha | query_sha | arm | budget | replicate) for the CQR arms and the baseline PAC arms; B0 / comparators / natives unseeded'),
               ordering_rule=ORDERING_RULE,
               cells=cells, counts=dict(cells=n, by_arm={a: sum(1 for c in cells if c['arm'] == a) for a in planned_arms}, by_cohort={k: sum(1 for c in cells if c['cohort'] == k) for k in sorted({c['cohort'] for c in cells})}, by_kind={k: sum(1 for c in cells if c['kind'] == k) for k in sorted({c['kind'] for c in cells})}, rows=len(rows), rows_available=len(avail), rows_unavailable=len(rows) - len(avail)),
               ceiling=ceiling, candidate_artifact_hashes=artifact, cqr_scope_keys=sorted(k for k in artifact if k.startswith('cqr/') or k == 'newarm/core.py'), kernel_binaries=kernel_rec, kernel_identity=kernel_identity, kernel_identity_version=KI.VERSION,
               kernel_identity_rule='every tag needed by a planned arm must match binary_sha256 AND record_sha256 (build-record file bytes) AND the record inner binary_sha256 at launch, resume, before and after every native cell; rebuilds under this identity are prohibited', replay_factor=REPLAY_FACTOR)
    man['manifest_sha256_without_self'] = hashlib.sha256(json.dumps(man, sort_keys=True, default=str).encode()).hexdigest()
    man['unavailable_artifacts_not_needed_by_planned_arms'] = unavailable_artifacts
    if os.path.exists(p): raise SystemExit('refuse: %s exists' % p)
    json.dump(man, open(p, 'w'), indent=1, default=str)
    print(json.dumps(dict(cells=n, nominal_s=nominal, verification_s=verification, ceiling_s=ceiling['total_ceiling_seconds'], by_arm=man['counts']['by_arm'], by_cohort=man['counts']['by_cohort'], root_seed=root_seed, manifest=p)))
    return p


def cqr_scope(artifact): return {k: v for k, v in (artifact or {}).items() if k.startswith('cqr/') or k == 'newarm/core.py'}


def classify_cqr(w, srec, wall, budget):
    """receipt classification for the cqr_candidate validator: status / outcome / guarantee from the worker JSON; LATE_OUTPUT, MEMORY_KILL, TIMEOUT_KILL, INVALID_PROCESS_EXIT from the clock and the supervisor record"""
    status = w.get('status', 'NO_OUTPUT'); outcome = w.get('outcome') or ({'COMPLETED': 'PUBLISHED'}.get(status, 'NOT_COMPLETED')); gt = w.get('guarantee_type') or 'NONE'
    if status == 'COMPLETED' and wall > budget: status = 'LATE_OUTPUT'; outcome = 'DEADLINE'; gt = 'NONE'
    if outcome == 'PROVED_ZERO_EVIDENCE' and wall > budget: status = 'LATE_OUTPUT'; outcome = 'DEADLINE'; gt = 'NONE'
    if srec.get('outcome') == 'MEMORY_KILL' or 'MEMORY' in str(srec.get('outcome')): status = 'MEMORY_KILL'; outcome = 'MEMORY'; gt = 'NONE'
    if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
    if status == 'COMPLETED' and srec.get('rc') not in (0, None): status = 'INVALID_PROCESS_EXIT'; outcome = 'INVALID_PLAN_OR_CERTIFICATE'; gt = 'NONE'
    return status, outcome, gt


def run(RD, manifest_name='CAMPAIGN_MANIFEST.json', only=None, max_cells=None):
    RD = os.path.abspath(RD)
    man = json.load(open(os.path.join(RD, manifest_name))); L = os.path.join(RD, LEDGER); cells_dir = os.path.join(RD, 'cells'); os.makedirs(cells_dir, exist_ok=True); done = 0
    if man.get('schema') != MANIFEST_SCHEMA: raise SystemExit('START REFUSED: manifest schema %s is not %s' % (man.get('schema'), MANIFEST_SCHEMA))
    mh = sha(os.path.join(RD, manifest_name)); sp = os.path.join(RD, 'CAMPAIGN_START.json'); ah = hashlib.sha256(json.dumps(man.get('candidate_artifact_hashes') or {}, sort_keys=True).encode()).hexdigest()
    cur = R.full_inventory(CODE)
    if os.path.exists(sp):
        st0 = json.load(open(sp))
        if st0.get('manifest_sha256') != mh or st0.get('manifest') != manifest_name: raise SystemExit('RESUME REFUSED: manifest on disk (%s) differs from the CAMPAIGN_START binding (%s)' % (mh[:16], str(st0.get('manifest_sha256'))[:16]))
        if glob.glob(os.path.join(RD, 'MANIFEST_AMENDMENT_*')): raise SystemExit('RESUME REFUSED: artifact amendment files present (the frozen identity is immutable; no amendment mechanism)')
        if st0.get('artifact_hashes_sha256') != ah: raise SystemExit('RESUME REFUSED: the frozen source inventory content hash differs from the CAMPAIGN_START binding')
        if cur != (man.get('candidate_artifact_hashes') or {}): raise SystemExit('RESUME REFUSED: the source files on disk differ from the frozen inventory')
        st_row = dict(kind='CAMPAIGN_START', manifest=manifest_name, manifest_sha256=mh, artifact_hashes_sha256=ah, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), only=only, max_cells=max_cells, resume=True)
    else:
        if cur != (man.get('candidate_artifact_hashes') or {}):
            d = sorted(k for k in set(cur) | set(man.get('candidate_artifact_hashes') or {}) if cur.get(k) != (man.get('candidate_artifact_hashes') or {}).get(k))
            raise SystemExit('START REFUSED: the source files on disk differ from the frozen inventory of the manifest (%d differ, e.g. %s)' % (len(d), d[:3]))
        st_row = dict(kind='CAMPAIGN_START', manifest=manifest_name, manifest_sha256=mh, artifact_hashes_sha256=ah, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), only=only, max_cells=max_cells, resume=False, candidate_artifact_hashes=man.get('candidate_artifact_hashes'), campaign_version=CAMPAIGN_VERSION, note='the frozen source inventory (content hash artifact_hashes_sha256) and the manifest are bound here; no amendment mechanism exists')
        json.dump(st_row, open(sp, 'w'), indent=1)
    planned_arms = sorted({c['arm'] for c in man['cells']}); resume = os.path.exists(sp) and st_row.get('resume')
    def refuse(msg):                                                       # a refused START leaves no CAMPAIGN_START binding behind (the next attempt is a START again, not a RESUME)
        if not resume and os.path.exists(sp): os.remove(sp)
        raise SystemExit(('RESUME REFUSED: ' if resume else 'START REFUSED: ') + msg)
    k_fail, _krec = kernel_identity_failures(planned_arms)
    if k_fail: refuse('; '.join(k_fail))
    # ---- CQR-09: the FROZEN kernel identity of the manifest (binary + build-record file + inner claim, every natively loaded artifact) must be the identity on disk
    # at launch and at every resume; a manifest without the frozen field cannot be run (no fallback to the mutable on-disk pair)
    if not man.get('kernel_identity'): refuse('the manifest carries no frozen kernel_identity (pre-2026-11-16 manifest schema content; freeze a new manifest)')
    cur_ki = KI.collect(CODE); ki_fail = KI.failures_vs_frozen(man['kernel_identity'], cur_ki, planned_arms)
    if ki_fail: refuse('frozen kernel identity violated: ' + '; '.join(ki_fail))
    st_row['kernel_identity_sha256'] = hashlib.sha256(json.dumps(man['kernel_identity'], sort_keys=True).encode()).hexdigest(); st_row['kernel_identity_verified_tags'] = sorted(KI.needed_tags(planned_arms))
    if not resume: json.dump(st_row, open(sp, 'w'), indent=1)
    open(L, 'a').write(json.dumps(st_row) + '\n')
    if any(c['arm'].startswith('H4_NATIVE_') for c in man['cells']): json.dump(PC.ensure_h4_native_build(L), open(os.path.join(RD, 'H4_NATIVE_BUILD.json'), 'w'), indent=1)
    for c in man['cells']:
        if only and c['cohort'] != only: continue
        if max_cells is not None and done >= max_cells: break
        cdir = os.path.join(cells_dir, '%05d__%s__%s__%s__r%d' % (c['order_index'], c['case_id'], c['arm'], int(c['budget_s']), c['replicate'])); rp = os.path.join(cdir, 'receipt.json')
        if os.path.exists(rp): continue
        os.makedirs(cdir, exist_ok=True); nonce = secrets.token_hex(8); attempt = os.path.join(cdir, 'attempt_' + nonce); os.makedirs(attempt); budget = c['budget_s']; out = os.path.join(attempt, 'worker.json')
        arm = c['arm']; ki_tags = KI.tags_needed_by(arm)
        if ki_tags:                                                           # BEFORE a native cell: the frozen identity must still hold (a rebuild between cells is a halt, not a silent relaunch)
            pre = KI.collect(CODE); pre_fail = KI.failures_vs_frozen(man['kernel_identity'], pre, [arm])
            if pre_fail:
                json.dump(dict(c, nonce=nonce, attempt_dir=attempt, status='REBUILT_UNDER_FROZEN_IDENTITY', outcome='NOT_COMPLETED', guarantee_type='NONE', kernel_identity_failures=pre_fail, phase='before_launch', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(rp, 'w'), indent=1, default=str)
                raise SystemExit('CAMPAIGN HALTED: kernel identity changed before cell %s (%s)' % (c['cell_id'], '; '.join(pre_fail)))
        launch = time.monotonic(); deadline = launch + budget
        # ---- command lines: the CQR arms -> cex/cqr/worker.py; every baseline arm EXACTLY as cex/pac/campaign.py run()
        if arm in R.CQR_ARMS: cmd = [PY, os.path.join(HERE, 'worker.py'), '--input', c['model_path'], '--output', out, '--arm', arm, '--deadline', str(deadline), '--seed', c['seed'], '--nonce', nonce, '--budget', str(budget)]
        elif arm == 'B0_FROZEN_V14': cmd = [PY, os.path.join(CODE, 'cex', 'b0_frozen_v14', 'evaluate.py'), '--worker', '--input', c['model_path'], '--output', out, '--route', 'auto', '--deadline', str(deadline)]
        elif arm in ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'): cmd = [PY, os.path.join(PC.HERE, 'worker.py'), '--input', c['model_path'], '--output', out, '--arm', arm, '--deadline', str(deadline), '--seed', c['seed'], '--nonce', nonce, '--budget', str(budget)]
        elif arm == 'CBI_NATIVE': cmd = [PY, '-m', 'cbi.cli', 'solve', c['model_path'], '--queries', 'all', '--width', '1/100', '--out', out]
        elif arm.startswith('H4_NATIVE_'): cmd = [PY, os.path.join(CODE, 'h4a', 'arm.py'), '--arm', c['native_arm'], '--rep', str(c['replicate']), '--out-dir', os.path.join(attempt, 'h4'), '--packet', c['packet']]
        elif arm == 'SF_NATIVE_SELECT': r_ = __import__('fractions').Fraction(c['sf_r']); e_ = __import__('fractions').Fraction(c['sf_eps']); cmd = [PY, os.path.join(CODE, 'sf', 'invoke.py'), 'select', c['model_path'], str(r_.numerator), str(r_.denominator), str(e_.numerator), str(e_.denominator), out, str(budget)]
        else: cmd = [PY, os.path.join(PC.HERE, 'comparator_cell.py'), arm, c['model_path'], c['evidence_path'], os.path.join(attempt, 'cmp'), str(budget), nonce, str(launch)]
        job = 'cell:%s:%s:%d:r%d' % (c['case_id'], arm, int(budget), c['replicate'])
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_scored_' + c['kind'], '--job', job, '--timeout', str(budget + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', 'caffeinate', '-s', *cmd]
        env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
        p = subprocess.run(sup, capture_output=True, text=True, cwd=CODE, env=env); wall = time.monotonic() - launch
        try: srec = json.loads(p.stderr.strip().splitlines()[-1])
        except Exception: srec = dict(parse_error=p.stderr[-300:])
        w = {}; validator = R.validator_of(arm)
        if validator == 'cqr_candidate':
            w = json.load(open(out)) if os.path.exists(out) else {}
            status, outcome, gt = classify_cqr(w, srec, wall, budget)
        elif validator == 'uai_candidate':                                   # ---- baseline classification copied from cex/pac/campaign.py run()
            w = json.load(open(out)) if os.path.exists(out) else {}
            status = w.get('status', 'NO_OUTPUT'); outcome = w.get('outcome') or ({'COMPLETED': 'PUBLISHED'}.get(status)); gt = w.get('guarantee_type') or ('DETERMINISTIC' if arm == 'B0_FROZEN_V14' and status == 'COMPLETED' else 'NONE')
            if arm == 'B0_FROZEN_V14' and status == 'STOPPED': outcome = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'ZERO_EVIDENCE': 'PROVED_ZERO_EVIDENCE'}.get(str(w.get('reason', ''))[:13], 'DEADLINE' if 'deadline' in str(w.get('reason', '')).lower() else ('MEMORY' if ('SUPPORT_ROWS_CAP' in str(w.get('reason', '')) or 'MEMORY' in str(w.get('reason', ''))) else 'NOT_COMPLETED'))
            if status == 'COMPLETED' and wall > budget: status = 'LATE_OUTPUT'; outcome = 'DEADLINE'; gt = 'NONE'
            if srec.get('outcome') == 'MEMORY_KILL' or 'MEMORY' in str(srec.get('outcome')): status = 'MEMORY_KILL'; outcome = 'MEMORY'; gt = 'NONE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
            if status == 'COMPLETED' and srec.get('rc') not in (0, None): status = 'INVALID_PROCESS_EXIT'; outcome = 'INVALID_PLAN_OR_CERTIFICATE'; gt = 'NONE'
        elif arm.startswith('H4_NATIVE_'):
            rp_ = os.path.join(attempt, 'h4', 'bundle.json'); w = json.load(open(rp_)) if os.path.exists(rp_) else {}; ok_ = bool(w.get('all_verified'))
            status = 'COMPLETED' if ok_ and wall <= budget else ('LATE_OUTPUT' if ok_ else ('NO_OUTPUT' if not w else 'NOT_VERIFIED')); outcome = 'PUBLISHED' if status == 'COMPLETED' else ('DEADLINE' if status in ('LATE_OUTPUT', 'TIMEOUT_KILL') or srec.get('outcome') == 'TIMEOUT_KILL' else 'NOT_COMPLETED'); gt = 'DETERMINISTIC' if status == 'COMPLETED' else 'NONE'; out = rp_
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
        elif arm == 'SF_NATIVE_SELECT':
            w = json.load(open(out)) if os.path.exists(out) else {}; st = w.get('status', 'NO_OUTPUT'); met = bool((w.get('width_met') or {}).get(c['sf_eps']))
            status = 'COMPLETED' if st == 'OK' and met and wall <= budget else ('LATE_OUTPUT' if st == 'OK' and met else st); outcome = 'PUBLISHED' if status == 'COMPLETED' else ('DEADLINE' if status in ('LATE_OUTPUT', 'TIMEOUT_KILL', 'TIMEOUT_COOPERATIVE') or srec.get('outcome') == 'TIMEOUT_KILL' else ('TOO_WIDE' if st == 'OK' else 'NOT_COMPLETED')); gt = 'DETERMINISTIC' if status == 'COMPLETED' else 'NONE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
        elif arm == 'CBI_NATIVE':
            w = json.load(open(out)) if os.path.exists(out) else {}; st = w.get('status'); status = 'COMPLETED' if st == 'CERTIFIED' and wall <= budget else ('LATE_OUTPUT' if st == 'CERTIFIED' else (st or 'NO_OUTPUT')); outcome = 'PUBLISHED' if status == 'COMPLETED' else ('DEADLINE' if status in ('LATE_OUTPUT', 'TIMEOUT_KILL') or srec.get('outcome') == 'TIMEOUT_KILL' else 'NOT_COMPLETED'); gt = 'DETERMINISTIC' if status == 'COMPLETED' else 'NONE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
        else:
            pr = os.path.join(attempt, 'cmp', 'pac_receipt.json'); w = json.load(open(pr)) if os.path.exists(pr) else {}
            outcome = w.get('outcome', 'NOT_COMPLETED'); status = 'COMPLETED' if outcome == 'PUBLISHED' and wall <= budget else ('LATE_OUTPUT' if outcome == 'PUBLISHED' else w.get('adapter_status', 'NO_OUTPUT'))
            if status == 'LATE_OUTPUT': outcome = 'DEADLINE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'
            if srec.get('outcome') == 'MEMORY_KILL': status = 'MEMORY_KILL'; outcome = 'MEMORY'
            gt = 'UNGUARANTEED' if outcome == 'PUBLISHED' else 'NONE'
        if arm.startswith('H4_NATIVE_'): out = os.path.join(attempt, 'h4', 'bundle.json')
        if ki_tags:                                                           # AFTER a native cell: a frozen worker that rebuilt (binary or build record rewritten inside the attempt) halts the campaign
            post = KI.collect(CODE); post_fail = KI.failures_vs_frozen(man['kernel_identity'], post, [arm])
            w_ = json.load(open(out)) if (os.path.exists(out) and out.endswith('.json')) else {}
            post_fail += KI.receipt_failures(man['kernel_identity'], w_ if isinstance(w_, dict) else {}, arm)
            if post_fail:
                json.dump(dict(c, nonce=nonce, attempt_dir=attempt, launch_relative_wall_s=wall, status='REBUILT_UNDER_FROZEN_IDENTITY', outcome='NOT_COMPLETED', guarantee_type='NONE', supervisor=srec, kernel_identity_failures=post_fail, phase='after_cell', worker_status_discarded=status, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(rp, 'w'), indent=1, default=str)
                raise SystemExit('CAMPAIGN HALTED: kernel identity changed during cell %s (%s)' % (c['cell_id'], '; '.join(post_fail)))
        rec = dict(c, nonce=nonce, attempt_dir=attempt, launch_relative_wall_s=wall, status=status, outcome=outcome, guarantee_type=gt, supervisor=srec, output_sha256=(sha(out) if os.path.exists(out) else None), worker_output=os.path.relpath(out, RD) if os.path.exists(out) else None, cmd=cmd, within_budget=wall <= budget, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        if validator == 'cqr_candidate': rec['route'] = w.get('route'); rec['bias'] = w.get('bias'); rec['worker_reason'] = (w.get('reason') or None)
        if validator == 'comparator_mar': rec['comparator'] = {k: w.get(k) for k in ('adapter_status', 'execution_capacity', 'capacity_note', 'output_sha256', 'output_file')}
        json.dump(rec, open(rp, 'w'), indent=1, default=str); done += 1
        print(json.dumps(dict(i=c['order_index'], case=c['case_id'], arm=arm, b=budget, r=c['replicate'], status=status, outcome=outcome, gt=gt, route=rec.get('route'), wall=round(wall, 2))), flush=True)
    return done


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != 'run': raise SystemExit(__doc__)
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None; mx = int(sys.argv[sys.argv.index('--max-cells') + 1]) if '--max-cells' in sys.argv else None
    run(sys.argv[2], 'CAMPAIGN_MANIFEST_dev.json' if '--dev' in sys.argv else 'CAMPAIGN_MANIFEST.json', only, mx)
