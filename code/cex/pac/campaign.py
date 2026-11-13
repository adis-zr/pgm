"""PAC EMPIRICAL PASS campaign driver -- v2 (candidate v2; handoff 03 §4-6, 04): `manifest` resolves and FREEZES the complete matrix (inventory, arms, budgets, replicates, seeds, ordering rule,
artifact hashes, prospective ceiling) BEFORE any scored run; `run` executes the frozen cells sequentially, each in a fresh attempt directory with a nonce, under the
project supervisor (gbidi.supervise, unchanged) with the 3 GiB SAMPLED process-tree RSS policy (interval 0.05 s) and timeout = budget + 1 s cleanup grace; the receipt of
a cell is written once; a crashed campaign resumes by skipping cells whose receipt exists (the manifest is immutable). Every attempt (incl. failed launches) is logged.
    python cex/pac/campaign.py manifest <RD> <inputs_dir> [--dev]
    python cex/pac/campaign.py run <RD> [--only COHORT] [--max-cells N]"""
import sys, os, json, time, hashlib, secrets, subprocess, math, glob, platform
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); PY = sys.executable
sys.path.insert(0, CODE)
CORE_PANEL = None
PRIMARY = [('B0_FROZEN_V14', 1), ('P1_PAC_CONDITIONAL', 3), ('H1_HYBRID', 3)]
COMPARATORS = [('LIBDAI_EXACT', 1), ('LBP', 1), ('WMB', 1), ('IJGP', 1), ('PGMAX_SUMPRODUCT_BP', 1), ('MERLIN_CTE', 1)]       # all deterministic configurations (one repetition each)
ABLATION = [('A0_POINT', 1), ('A1_CONDITIONAL', 1)]
UNAVAILABLE = {'SAMPLESEARCH': 'UNAVAILABLE_BACKEND: x86-64 binary aborts under emulation, source does not build (six bounded historical attempts, EXTERNAL_SWEEP_2026-11-06/AVAILABILITY.json); no reimplementation', 'ACE': 'UNAVAILABLE_BACKEND: registration-gated download never obtained (comparator pass 2026-11-04)'}
BUDGETS = [20.0, 120.0]


def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def resolve_inventory(inputs, seed_inventory):
    S = json.load(open(seed_inventory)); rows = []
    for c in S['canonical_external_cases']:
        mp = os.path.join(inputs, c['model_filename']); ep = os.path.join(inputs, c['evidence_filename']); ok = os.path.exists(mp)
        mh = sha(mp) if ok else None; eh = hashlib.sha256(open(ep, 'rb').read() if os.path.exists(ep) else b'0').hexdigest()
        rows.append(dict(cohort='external_core', case_id=c['case_id'], family=c['family'], model_path=mp, evidence_path=ep, model_sha256=mh, evidence_sha256=eh, expected_model_sha256=c['model_sha256'], expected_evidence_sha256=c['evidence_sha256'], hash_verified=(mh == c['model_sha256'] and eh == c['evidence_sha256']), status='AVAILABLE_HASH_VERIFIED' if (mh == c['model_sha256'] and eh == c['evidence_sha256']) else ('AVAILABLE_HASH_MISMATCH' if ok else 'UNAVAILABLE_INPUT'), task='all original singleton marginals under original evidence', epsilon='1/200'))
    for m in S['missing_slots']: rows.append(dict(cohort='external_core', case_id=m['case_id'], family=m['family'], status='HISTORICALLY_INACCESSIBLE_SLOT', note=m['note'], model_sha256=None, task='all original singleton marginals'))
    # selector transfer additions (Promedus_11 / Promedus_16): raw inputs retained in the historical sweep's source archive
    E = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'EXTERNAL_SWEEP_2026-11-06', 'sources', 'uai2022_tuning', 'MAR')
    for c in ('Promedus_11', 'Promedus_16'):
        mp = os.path.join(E, c + '.uai'); ep = mp + '.evid'; ok = os.path.exists(mp)
        rows.append(dict(cohort='selector_transfer_additions', case_id=c, family='Promedus', model_path=mp, evidence_path=ep, model_sha256=sha(mp) if ok else None, evidence_sha256=hashlib.sha256(open(ep, 'rb').read() if os.path.exists(ep) else b'0').hexdigest(), status='AVAILABLE_RAW_UAI2022_TUNING_ARCHIVE' if ok else 'UNAVAILABLE_INPUT', provenance='runs/mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06/sources (UAI 2022 tuning MAR archive); historical selector bindings used canonical (not raw) hashes -- recorded, not asserted equal', task='all original singleton marginals under original evidence', epsilon='1/200'))
    return rows


def legacy_cohorts():
    """registered historical suites: inventoried with explicit statuses (candidate v2 reconciliation, review F07 of 13 Nov 2026)"""
    return [
        dict(cohort='H4', suite='H4 arithmetic / complete-query (runs/h4_arith_2026-10-27*, runs/h4q_pilot_2026-10-27; docs/h4-*-2026-10-27; docs/lab-reports/bench/runs/h4_external_v1)', tasks='8 primary workloads n in {64,128} x seed {0,1} x evidence {E0, Ehalf}: the two source-conditioned target probabilities P(x_target = +1 | x_source = +-1) (NOT all singleton marginals); irrational sqrt(beta/n) loadings (MPFR enclosures); 6 frozen arithmetic nodes (FROZEN_NODES.json)',
             primary_arms='UNSUPPORTED_TASK_ADAPTER (typed): the H4 positive-node law has IRRATIONAL factor tables (exp of a quadratic form with sqrt(beta/n) loadings; h4a/masses.py enclosures), outside the exact-nonnegative-rational table contract of B0 / PAC; the task is two conditional target probabilities, not the UAI singleton task. No conversion is performed.',
             native_specialists='RECOVERABLE: h4a/arm.py arms C / PI / PP on the six frozen nodes (packet docs/h4-arithmetic-contract-2026-10-27/inputs: FROZEN_NODES.json 572275de..., H4-n128-s1.canonical.json e4dcb7ff...), h4q/pilot.py complete-query pilot; retained references docs/lab-reports/bench/runs/h4_external_v1/references/*.json (REF_TIGHT Fourier intervals for all 8 primary workloads). SCHEDULED in the v2 supplementary plan (own contract: 120 s cap, 4 GiB historical cap -> to be run at the common 3 GiB policy, both budgets), NOT RUN in this pass (no scored execution authorized before review).',
             generators='h4a/model.py (strong-compact-v1 hash rules) + h4a/build.py; deterministic', status='INVENTORIED_RECOVERABLE_SCHEDULED_V2_PLAN'),
        dict(cohort='qgrid', suite='query-aware grid benchmark QG (docs/handoff/historical/v4/experiments/QGRID_*.md; proofs QG01-QG09)', tasks='POSITIVE rational grids: attractive (q,1,1,q) / repulsive (1,q,q,1) edges, fields (1,v) / (v,1), hash-selected signs; principal 16x16 q=3 v=11/10 seeds 0/1 centre (8,8); main screen L in {8,16,32} x q in {3/2,3,9} x seeds 0/1; strips; tiny grids; zero-field squares; queries: corner/centre singletons (UAI-compatible), adjacent/far-pair/block JOINT laws, influence, parities (not singleton tasks)',
             primary_arms='SUPPORTED for the singleton queries (all original singleton marginals cover corner + centre): 37 generated instances (cex/pac/legacy_qgrid.py; generator checkpoints verified). The previous manifest (2026-11-12) excluded this cohort as "signed factors (negative entries)": that was FALSE (every table entry is positive; verified per instance). Joint / parity queries: UNSUPPORTED_TASK_ADAPTER (typed).',
             native_specialists='UNAVAILABLE_BACKEND: the historical moment-LP / checkerboard-oracle / window-transfer methods exist only as prose (GRID_INFERENCE.md); no executable specialist and no historical model files are in the repository (QGRID_REPRODUCTION.md: "the historical complete explicit JSON schema and historical hashes are not supplied"). The dq/ package is the signed-EXPONENTIAL chain pilot (irrational loadings), a different suite.',
             generators='cex/pac/legacy_qgrid.py (qgrid-v1 SHA-256 rules; NEW labelled generation, not a bitwise historical replay)', status='INVENTORIED_GENERATED_SCHEDULED_V2_PLAN'),
        dict(cohort='SF_bridge', suite='sparse/Fourier bridge (branch sf-bridge-2026-11-06: code/sf/; runs/mdi_2026-10-28/SF_BRIDGE_2026-11-06 on that branch)', tasks='4 panels (small_control n=12 m=128; primary_A/B and ordinary_control n=24 m=4096) x 8 couplings r x 2 widths {1/100, 1/20}: per-coordinate probabilities of the coupled two-block law (weighted supports A, B joined by the full-coordinate product kernel)',
             primary_arms='the two-block law IS a CBI-type explicit-table model (two variables of cardinality m, one m x m pairwise factor): small_control (128 x 128 = 16,384 entries) is RENDERABLE by cex/pac/legacy_cbi_uai.py; the three n=24 m=4096 panels (16.8 M entries per table) are UNSUPPORTED_TASK_ADAPTER (explicit rendering exceeds the adapter cap; the kernel is implicit natively). Coupling r enters the kernel table exactly (kappa integers).',
             native_specialists='RECOVERABLE on branch sf-bridge-2026-11-06: sf/invoke.py (select / route modes, cooperative deadline) + sf/runner.py (manifest of 169 invocations; 203 s of 3,600 s historical). SCHEDULED in the v2 supplementary plan (checkout of code/sf and inputs/PANELS.json + panel JSONs from that branch; hashes recorded there), NOT RUN in this pass.',
             generators='sf/generate.py (sf-gen-1 SHA-256 counter stream) on branch sf-bridge-2026-11-06; PANELS.json sha256 per panel retained', status='INVENTORIED_RECOVERABLE_SCHEDULED_V2_PLAN'),
        dict(cohort='CBI', suite='CBI library pass 2 (cbi/experiment.py instances(); archive MDI_CBI_PASS2_REVIEW_2026-11-06.zip a07da14c...)', tasks='23 retained instances (10 correctness-layer d=6, 13 performance-layer d=24): per-coordinate probabilities of every block, width 1/100, delta 0 (native CBI contract)',
             primary_arms='SEMANTIC ADAPTER (cex/pac/legacy_cbi_uai.py): block law -> explicit-table UAI model (one variable per block, cardinality = support size; unary weights; m_u x m_v kernel tables from the exact kappa integers; dropped positive scalars v^-d per edge recorded); UAI all-singleton rows -> native per-coordinate enclosures by summation (linear image; verified equal to the native exact reference on the 7 brute-forceable instances). 14 instances RENDERED (all 10 correctness + p_chain8_s0/s1, p_tree15_s0, p_nearhard_cycle); 9 UNSUPPORTED_TASK_ADAPTER (explicit tables > 4 M entries).',
             native_specialists='cbi CLI solve (certified intervals width 1/100, delta 0): RERUN in the 2026-11-12 campaign at 20 s and 120 s (22/23 certified at both budgets; p_island_mesh_8x8 NOT_COMPLETED); the 14 rendered instances x primary arms are SCHEDULED in the v2 supplementary plan', generators='cbi/generators.py via cbi/experiment.py instances() (deterministic streams); retained inputs hash-verified', status='NATIVE_RERUN_DONE_2026-11-12; UAI_ADAPTER_SCHEDULED_V2_PLAN'),
        dict(cohort='other_registered_timed_tasks', suite='ND positive perturbations (branch nd-certificate-2026-11-05), n32 H4/type-count, long alternating chains, Walsh diagnostics, earlier CBI chain/spoke/cycle/ladder fixtures', tasks='correctness controls and certificate diagnostics with their own contracts (per 05_INVENTORY_AUDIT: "correctness fixtures rather than primary timed tasks"); individually: ND = Promedus_12 positive-perturbation family (two-channel certificate; stopped), chains / Walsh = diagnostics of the sf / h4 theory, earlier CBI fixtures = subsumed by the 10 retained correctness instances', primary_arms='not applicable (fixtures; signed or irrational models where timed)', native_specialists='historical; NOT RERUN (no primary timed contract to reconcile)', status='INVENTORIED_CORRECTNESS_FIXTURES')]


def manifest(RD, inputs, dev=False):
    RD = os.path.abspath(RD); inputs = os.path.abspath(inputs); os.makedirs(RD, exist_ok=True); SI = os.path.join(CODE, '..', 'docs', 'handoff-received-2026-11-12-pac-empirical', 'PAC_EMPIRICAL_HANDOFF_2026-11-12', '06_SEED_INVENTORY.json')
    inv = resolve_inventory(inputs, SI); legacy = legacy_cohorts()
    # CBI cohort: the 23 pass-2 inputs retained in runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/inputs, HASH-VERIFIED against that pass's MANIFEST.json (21 of them are
    # regenerated bit-identically by cbi/experiment.py instances(); the two m=2048 panel instances exist only as retained inputs). The native CBI contract is kept.
    cbi_rows = []; CB = os.path.join(CODE, 'runs', 'mdi_2026-10-28', 'CBI_LIBRARY_2026-11-06')
    try:
        cm = json.load(open(os.path.join(CB, 'MANIFEST.json')))
        for name, info in sorted(cm['instances'].items()):
            p = os.path.join(CB, 'inputs', name + '.json'); ok = os.path.exists(p) and sha(p) == info['sha256']
            cbi_rows.append(dict(cohort='CBI', case_id=name, model_path=p, model_sha256=info['sha256'], status='RETAINED_PASS2_INPUT_HASH_VERIFIED' if ok else 'UNAVAILABLE_INPUT', layer=info.get('layer'), meta=info.get('meta'), task='all block queries, width 1/100, delta 0 (native CBI contract; pass-2 primary mode "library")'))
        legacy[3]['status'] = 'NATIVE_RERUN_SCHEDULED (23 retained pass-2 inputs, hash-verified)'
    except Exception as ex:
        legacy[3]['status'] = 'INPUT_MANIFEST_UNAVAILABLE: %s' % str(ex)[:200]
    root_seed = secrets.token_hex(16); cells = []
    arms = PRIMARY + COMPARATORS + ABLATION
    def mk(row, arm, rep, budget, kind):
        cid = hashlib.sha256('|'.join([row['case_id'], arm, str(rep), str(budget), kind]).encode()).hexdigest()[:16]
        seed_arm = 'ABLATION_PAIR' if kind == 'ablation' else arm        # the matched pair A0/A1 shares ONE seed (common cutset-tree draw stream; the point completion uses a separate domain inside the engine)
        seed = hashlib.sha256('|'.join([root_seed, row.get('model_sha256') or '', row.get('evidence_sha256') or '', row.get('task', ''), seed_arm, str(budget), str(rep), 'ablation' if kind == 'ablation' else 'primary']).encode()).hexdigest() if arm not in ('B0_FROZEN_V14',) and kind != 'comparator' else None
        return dict(cell_id=cid, cohort=row['cohort'], case_id=row['case_id'], arm=arm, replicate=rep, budget_s=budget, kind=kind, model_path=row.get('model_path'), evidence_path=row.get('evidence_path'), model_sha256=row.get('model_sha256'), evidence_sha256=row.get('evidence_sha256'), seed=seed, seed_namespace=('paired_ablation' if kind == 'ablation' else ('scored_primary' if seed else None)))
    core_rows = [r for r in inv if r['status'] == 'AVAILABLE_HASH_VERIFIED']; sel_rows = [r for r in inv if r['cohort'] == 'selector_transfer_additions' and r.get('model_sha256')]
    for row in core_rows + sel_rows:
        for budget in BUDGETS:
            for arm, reps in PRIMARY:
                for rep in range(reps): cells.append(mk(row, arm, rep, budget, 'primary'))
            for arm, reps in COMPARATORS:
                for rep in range(reps): cells.append(mk(row, arm, rep, budget, 'comparator'))
        for arm, reps in ABLATION: cells.append(mk(row, arm, 0, 120.0, 'ablation'))
    for row in cbi_rows:
        if row['status'].startswith('RETAINED'):
            for budget in BUDGETS: cells.append(mk(row, 'CBI_NATIVE', 0, budget, 'legacy_native'))
    # ORDERING RULE: by (cohort, case, budget), within a case/budget: B0, then P1 r0, H1 r0, P1 r1, H1 r1, P1 r2, H1 r2, then comparators in registry order, then (after both budgets) A0, A1; CBI cohort last
    order_arm = {'B0_FROZEN_V14': 0, 'P1_PAC_CONDITIONAL': 1, 'H1_HYBRID': 2}; comp_order = {a: 10 + i for i, (a, _) in enumerate(COMPARATORS)}
    def key(c):
        coh = {'external_core': 0, 'selector_transfer_additions': 1, 'CBI': 2}[c['cohort']]
        if c['kind'] == 'ablation': return (coh, c['case_id'], 999.0, 50 + (0 if c['arm'] == 'A0_POINT' else 1), 0)
        a = c['arm']; o = order_arm.get(a, comp_order.get(a, 90)); rep = c['replicate']
        return (coh, c['case_id'], c['budget_s'], (rep * 2 + o) if a in ('P1_PAC_CONDITIONAL', 'H1_HYBRID') else (0 if a == 'B0_FROZEN_V14' else o), rep)
    cells.sort(key=key)
    for i, c in enumerate(cells): c['order_index'] = i
    nominal = sum(c['budget_s'] for c in cells); n_trials = len(cells); orch = 2 * n_trials + max(600, math.ceil(0.05 * nominal))
    ceiling = dict(availability_environment_build_total_seconds=3600, qualification_total_seconds=3600, offline_reference_total_seconds=7200, independent_audit_reporting_packaging_total_seconds=1800, scored_matrix_seconds=nominal, orchestration_seconds=orch, total_ceiling_seconds=16200 + 2 * (nominal + orch), formula='16200 + 2*(scored_matrix_seconds + orchestration_seconds) (04_BENCHMARK_DEFAULTS); the second matrix is reserved for one correctness contingency, unused otherwise')
    b0_build = json.load(open(os.path.join(CODE, 'cex', 'b0_frozen_v14', 'cex_build.json'))) if os.path.exists(os.path.join(CODE, 'cex', 'b0_frozen_v14', 'cex_build.json')) else None
    cand_build = json.load(open(os.path.join(CODE, 'cex', 'newarm', 'cex_build.json'))) if os.path.exists(os.path.join(CODE, 'cex', 'newarm', 'cex_build.json')) else None
    artifact = {'%s/%s' % (d, f): sha(os.path.join(CODE, 'cex', d, f)) for d in ('pac', 'newarm', 'b0_frozen_v14') for f in sorted(os.listdir(os.path.join(CODE, 'cex', d))) if f.endswith(('.py', '.cpp'))}      # PER-DIRECTORY keys (the 2026-11-12 flat dict collided; MANIFEST_AMENDMENT_1)
    comparators = dict(LIBDAI_EXACT=dict(binary=sha(os.path.join(CODE, 'bench', 'libdai', 'libdai_mar')), config='JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592] (historical sweep setting; maxmem is the driver internal admission, the worker policy is the 3 GiB sampled RSS)'), LBP=dict(binary=sha(os.path.join(CODE, 'bench', 'libdai', 'libdai_mar')), config='BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime=<remaining>]'), WMB=dict(binary=sha('/Users/adis/Workspace/comparators/merlin/build/merlin'), config='merlin 1.7.0 wmb, i-bound ladder [2,4,6,8,10,12,16,20], 100 iterations; execution capacity tagged exact/approximate per run'), IJGP=dict(binary=sha('/Users/adis/Workspace/comparators/merlin/build/merlin'), config='merlin 1.7.0 ijgp, same ladder'), PGMAX_SUMPRODUCT_BP=dict(interpreter='.venv-pgmax (pgmax 0.6.1, jax 0.4.31 cpu, float32)', config='200 iterations, damping 0.5, temperature 1.0'), MERLIN_CTE=dict(binary=sha('/Users/adis/Workspace/comparators/merlin/build/merlin'), config='merlin 1.7.0 cte (exact clique-tree elimination, binary64 point)'), **{k: dict(status=v) for k, v in UNAVAILABLE.items()})
    man = dict(schema='pac_empirical_campaign_manifest_v2', frozen_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), dev=dev, host=dict(platform=platform.platform(), machine=platform.machine(), python=sys.version, cpu_count=os.cpu_count()), inputs_dir=os.path.abspath(inputs), inventory=inv, legacy_cohorts=legacy, cbi_instances=cbi_rows, arms=dict(primary=PRIMARY, comparators=COMPARATORS, ablation=ABLATION, unavailable=UNAVAILABLE), budgets_s=BUDGETS, task=dict(epsilon='1/200', delta='1/1000000', delta_allocation='range 1/2, variance 1/2; per coordinate family_delta/K over all stochastic coordinates of the job', deterministic_delta='0'), resource_contract=dict(memory='3 GiB sampled process-tree RSS kill (interval 0.05 s), identical for every arm; RLIMIT_AS unavailable on macOS', clock='launch-relative absolute deadline on the host monotonic clock (mach_absolute_time); host sleep prohibited (caffeinate -s)', cleanup_grace_s=1.0, supervisor_internal_grace_s=4.0, actual_kill_threshold_s='budget + 5 (timeout budget+1 plus the supervisor GRACE_S = 4 before SIGKILL; review F11 / H4); walls are charged in full; late outputs never count', late_output_counts_as_success=False, threads='single worker at a time; OMP/BLAS threads 1; JAX cpu single-thread flags; Merlin single-threaded'), seeds=dict(root_seed=root_seed, generation='sha256(root | model_sha | evidence_sha | task | arm | budget | replicate | namespace); development namespace = the literal string devseed (never scored)', prng='python random.Random (MT19937) seeded from the 128-bit integer of the seed hash; unbiased integer draws; the theorem assumes ideal independent unbiased bits (separate assumption)'), ordering_rule='sorted by (cohort, case, budget); within a case/budget: B0, P1 r0, H1 r0, P1 r1, H1 r1, P1 r2, H1 r2, comparators in registry order; after both budgets A0 then A1; CBI cohort last; strictly sequential', cells=cells, counts=dict(cells=len(cells), by_arm={a: sum(1 for c in cells if c['arm'] == a) for a in sorted({c['arm'] for c in cells})}, by_cohort={k: sum(1 for c in cells if c['cohort'] == k) for k in sorted({c['cohort'] for c in cells})}), ceiling=ceiling, candidate_artifact_hashes=artifact, kernel_builds=dict(b0_frozen_v14=b0_build, candidate=cand_build, note='binaries rebuilt on this host with the recorded flags; the historical binary hash is not portable'), comparator_identities=comparators)
    man['manifest_sha256_without_self'] = hashlib.sha256(json.dumps(man, sort_keys=True, default=str).encode()).hexdigest()
    p = os.path.join(RD, 'CAMPAIGN_MANIFEST%s.json' % ('_dev' if dev else '')); json.dump(man, open(p, 'w'), indent=1, default=str)
    print(json.dumps(dict(cells=len(cells), nominal_s=nominal, ceiling_s=ceiling['total_ceiling_seconds'], by_arm=man['counts']['by_arm'], by_cohort=man['counts']['by_cohort'], root_seed=root_seed, manifest=p)))


def run(RD, only=None, max_cells=None, manifest_name='CAMPAIGN_MANIFEST.json'):
    RD = os.path.abspath(RD)                                              # the comparator adapters run their children with cwd = the cell directory: every path must be absolute
    man = json.load(open(os.path.join(RD, manifest_name))); L = os.path.join(RD, 'PAC_LEDGER.jsonl'); cells_dir = os.path.join(RD, 'cells'); os.makedirs(cells_dir, exist_ok=True); done = 0
    # CAMPAIGN START record (the manifest's identity bound to the ledger before the first scored cell; an existing record is kept and a resume is recorded as such)
    mh = sha(os.path.join(RD, manifest_name)); st_row = dict(kind='CAMPAIGN_START', manifest=manifest_name, manifest_sha256=mh, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), only=only, max_cells=max_cells, resume=os.path.exists(os.path.join(RD, 'CAMPAIGN_START.json')), candidate_artifact_hashes=man.get('candidate_artifact_hashes'))
    open(L, 'a').write(json.dumps(st_row) + '\n')
    if not os.path.exists(os.path.join(RD, 'CAMPAIGN_START.json')): json.dump(st_row, open(os.path.join(RD, 'CAMPAIGN_START.json'), 'w'), indent=1)
    for c in man['cells']:
        if only and c['cohort'] != only: continue
        if max_cells is not None and done >= max_cells: break
        cdir = os.path.join(cells_dir, '%05d__%s__%s__%s__r%d' % (c['order_index'], c['case_id'], c['arm'], int(c['budget_s']), c['replicate'])); rp = os.path.join(cdir, 'receipt.json')
        if os.path.exists(rp): continue
        os.makedirs(cdir, exist_ok=True); nonce = secrets.token_hex(8); attempt = os.path.join(cdir, 'attempt_' + nonce); os.makedirs(attempt); budget = c['budget_s']; out = os.path.join(attempt, 'worker.json')
        launch = time.monotonic(); deadline = launch + budget
        if c['arm'] == 'B0_FROZEN_V14': cmd = [PY, os.path.join(CODE, 'cex', 'b0_frozen_v14', 'evaluate.py'), '--worker', '--input', c['model_path'], '--output', out, '--route', 'auto', '--deadline', str(deadline)]
        elif c['arm'] in ('P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'): cmd = [PY, os.path.join(HERE, 'worker.py'), '--input', c['model_path'], '--output', out, '--arm', c['arm'], '--deadline', str(deadline), '--seed', c['seed'], '--nonce', nonce, '--budget', str(budget)]
        elif c['arm'] == 'CBI_NATIVE': cmd = [PY, '-m', 'cbi.cli', 'solve', c['model_path'], '--queries', 'all', '--width', '1/100', '--out', out]
        else: cmd = [PY, os.path.join(HERE, 'comparator_cell.py'), c['arm'], c['model_path'], c['evidence_path'], os.path.join(attempt, 'cmp'), str(budget), nonce, str(launch)]
        job = 'cell:%s:%s:%d:r%d' % (c['case_id'], c['arm'], int(budget), c['replicate'])
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'pac_scored_' + c['kind'], '--job', job, '--timeout', str(budget + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', 'caffeinate', '-s', *cmd]
        env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
        p = subprocess.run(sup, capture_output=True, text=True, cwd=CODE, env=env); wall = time.monotonic() - launch
        try: srec = json.loads(p.stderr.strip().splitlines()[-1])
        except Exception: srec = dict(parse_error=p.stderr[-300:])
        w = {}
        if c['arm'] not in ('CBI_NATIVE',) and not c['arm'].startswith(('LIBDAI', 'LBP', 'WMB', 'IJGP', 'PGMAX', 'MERLIN')):
            w = json.load(open(out)) if os.path.exists(out) else {}
            status = w.get('status', 'NO_OUTPUT'); outcome = w.get('outcome') or ({'COMPLETED': 'PUBLISHED'}.get(status)); gt = w.get('guarantee_type') or ('DETERMINISTIC' if c['arm'] == 'B0_FROZEN_V14' and status == 'COMPLETED' else 'NONE')
            if c['arm'] == 'B0_FROZEN_V14' and status == 'STOPPED': outcome = {'DEADLINE': 'DEADLINE', 'MEMORY': 'MEMORY', 'ZERO_EVIDENCE': 'PROVED_ZERO_EVIDENCE'}.get(str(w.get('reason', ''))[:13], 'DEADLINE' if 'deadline' in str(w.get('reason', '')).lower() else ('MEMORY' if ('SUPPORT_ROWS_CAP' in str(w.get('reason', '')) or 'MEMORY' in str(w.get('reason', ''))) else 'NOT_COMPLETED'))
            if status == 'COMPLETED' and wall > budget: status = 'LATE_OUTPUT'; outcome = 'DEADLINE'; gt = 'NONE'
            if srec.get('outcome') == 'MEMORY_KILL' or 'MEMORY' in str(srec.get('outcome')): status = 'MEMORY_KILL'; outcome = 'MEMORY'; gt = 'NONE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
            if status == 'COMPLETED' and srec.get('rc') not in (0, None): status = 'INVALID_PROCESS_EXIT'; outcome = 'INVALID_PLAN_OR_CERTIFICATE'; gt = 'NONE'
        elif c['arm'] == 'CBI_NATIVE':
            w = json.load(open(out)) if os.path.exists(out) else {}; st = w.get('status'); status = 'COMPLETED' if st == 'CERTIFIED' and wall <= budget else ('LATE_OUTPUT' if st == 'CERTIFIED' else (st or 'NO_OUTPUT')); outcome = 'PUBLISHED' if status == 'COMPLETED' else ('DEADLINE' if status in ('LATE_OUTPUT', 'TIMEOUT_KILL') or srec.get('outcome') == 'TIMEOUT_KILL' else 'NOT_COMPLETED'); gt = 'DETERMINISTIC' if status == 'COMPLETED' else 'NONE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'; gt = 'NONE'
        else:
            pr = os.path.join(attempt, 'cmp', 'pac_receipt.json'); w = json.load(open(pr)) if os.path.exists(pr) else {}
            outcome = w.get('outcome', 'NOT_COMPLETED'); status = 'COMPLETED' if outcome == 'PUBLISHED' and wall <= budget else ('LATE_OUTPUT' if outcome == 'PUBLISHED' else w.get('adapter_status', 'NO_OUTPUT'))
            if status == 'LATE_OUTPUT': outcome = 'DEADLINE'
            if srec.get('outcome') == 'TIMEOUT_KILL': status = 'TIMEOUT_KILL'; outcome = 'DEADLINE'
            if srec.get('outcome') == 'MEMORY_KILL': status = 'MEMORY_KILL'; outcome = 'MEMORY'
            gt = 'UNGUARANTEED' if outcome == 'PUBLISHED' else 'NONE'
        rec = dict(c, nonce=nonce, attempt_dir=attempt, launch_relative_wall_s=wall, status=status, outcome=outcome, guarantee_type=gt, supervisor=srec, output_sha256=(sha(out) if os.path.exists(out) else None), worker_output=os.path.relpath(out, RD) if os.path.exists(out) else None, cmd=cmd, within_budget=wall <= budget, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        if c['arm'].startswith(('LIBDAI', 'LBP', 'WMB', 'IJGP', 'PGMAX', 'MERLIN')): rec['comparator'] = {k: w.get(k) for k in ('adapter_status', 'execution_capacity', 'capacity_note', 'output_sha256', 'output_file')}
        json.dump(rec, open(rp, 'w'), indent=1, default=str); done += 1
        print(json.dumps(dict(i=c['order_index'], case=c['case_id'], arm=c['arm'], b=budget, r=c['replicate'], status=status, outcome=outcome, gt=gt, wall=round(wall, 2))), flush=True)


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'manifest': manifest(sys.argv[2], sys.argv[3], dev='--dev' in sys.argv)
    elif cmd == 'run':
        only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None; mx = int(sys.argv[sys.argv.index('--max-cells') + 1]) if '--max-cells' in sys.argv else None
        run(sys.argv[2], only, mx, 'CAMPAIGN_MANIFEST_dev.json' if '--dev' in sys.argv else 'CAMPAIGN_MANIFEST.json')
