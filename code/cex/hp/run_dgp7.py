"""DGP7 supervised runner (derived from run_dgp6.py) (protocol rule 4): every arm executes from a CLEAN DETACHED CHECKOUT at the frozen commit (--code-root), with the worker's cwd set to that checkout, source identity checked at launch and at completion
(sha256 of the planner / engine / kernel / construction / residual files vs FREEZE.json), outputs under the records tree. Arms (PROTOCOL.md section 2): REPAIRED (unified_pac_planner v0.11 --lifted --envelope RMAX --global global: the repaired DGP6 GLOBAL arm, no residual
constructor), RESIDUAL_ONLY (--lifted --envelope RMAX --residual residual_only: the same bank / window machinery with the law frozen; checked same-law cap tightening), RESIDUAL_JOINT (--lifted --envelope RMAX --residual residual_joint: the full algorithm); diagnostic
pseudo-arms REPAIRED_8 / RESIDUAL_JOINT_8 (+ --policy8: the separate eight-second policy; never completions; never on the four-second preservation cohort) and FORCED_RESIDUAL (--force-stream residual --residual residual_joint; the optional-role risk delta / 4; never
completions). BASE is NOT an arm this round. Sample seed per task: first eight SHA-256 bytes of 'DGP7-SAMPLE|<model_sha256>|<k>' (unsigned big-endian) reduced to 1..2^31-1 (k = 0 primary, 1 / 2 confirmations), shared across arms. Primary arm order rotated by the model hash
(first eight hex digits mod the arm count); reversed for confirmations. Contracts: main 20.0 / 19.5 / 19.0 (supervisor ceiling 24); p4 4.0 / 3.85 / 3.5 (ceiling 6); p20 = main. Input paths resolve through dgp_paths (packet-relative / DGP_ROOTS; sha256-checked).
Amendment schemas (DGP7 repair R8): --amendment F accepts (a) the DGP6 validity schema {code: {commit, files}} (the arm identity is checked against the amendment's files), (b) the DGP7 schema {amendment: {commit, files, reason}} (same semantics), (c) a harness amendment
{amendment_commit, harness_files_changed | files_changed} (the ENGINE identity stays FREEZE.json's; only the named harness files may differ: the frozen engine executes with the amended harness). The schema used is recorded per cell.
usage: run_dgp7.py SUBDIR MANIFEST.json --code-root /path/to/detached --arms REPAIRED,RESIDUAL_ONLY,RESIDUAL_JOINT --contract main|p4|p20 [--confirm --seed-index K] [--only a,b] [--scope S] [--records RD] [--freeze F] [--amendment F] [--skip-existing] [--no-identity (dgp7_dev only)]"""
import sys, os, json, time, subprocess, argparse, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
RD_DEFAULT = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP7_RESIDUAL_JOINT'; SUP_CODE = os.environ.get('PGM_CODE', '/Users/adis/Workspace/pgm/code'); PY = os.environ.get('PY', os.path.join(SUP_CODE, '.venv/bin/python')); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
CONTRACTS = dict(main=dict(outer=20.0, hard=19.5, work=19.0, ceiling=24.0), p4=dict(outer=4.0, hard=3.85, work=3.5, ceiling=6.0), p20=dict(outer=20.0, hard=19.5, work=19.0, ceiling=24.0))
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', contracts=CONTRACTS, seed_rule='DGP7-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1', arm_rotation='int(model_sha256[:8], 16) mod len(arms); reversed for confirmations')
IDENTITY_FILES = ['cex/hp/unified_pac_planner.py', 'cex/hp/pac_actions.py', 'cex/hp/joint_stream.py', 'cex/hp/joint_proposal.py', 'cex/hp/joint_witness.py', 'cex/hp/joint_optimize.py', 'cex/hp/check_joint.py', 'cex/hp/global_stream.py', 'cex/hp/global_circuit.py', 'cex/hp/global_optimize.py', 'cex/hp/check_global.py', 'cex/hp/lifted_decoder.py', 'cex/hp/grouped_envelope.py', 'cex/hp/residual_max_envelope.py', 'cex/hp/unified_planner.py', 'cex/hp/coarse_envelope.py', 'cex/hp/cost_model.py', 'cex/hp/PHASE_RATES_R1.json', 'cex/blockres/integrated.py', 'cex/blockres/blockres.py', 'cex/newarm/cex_executor.py', 'cex/newarm/cex_kernel.cpp', 'cex/newarm/libcex_kernel.dylib', 'cex/newarm/cex_build.json',
                  'cex/hp/residual_bank.py', 'cex/hp/residual_local.py', 'cex/hp/check_residual.py', 'cex/hp/residual_stream.py']          # DGP7: the four residual modules join the arm identity (the first 24 entries are run_dgp6.IDENTITY_FILES verbatim)
ARM_ARGS = {'REPAIRED': ['--lifted', '--envelope', 'RMAX', '--global', 'global'], 'RESIDUAL_ONLY': ['--lifted', '--envelope', 'RMAX', '--residual', 'residual_only'], 'RESIDUAL_JOINT': ['--lifted', '--envelope', 'RMAX', '--residual', 'residual_joint'],
            'REPAIRED_8': ['--lifted', '--envelope', 'RMAX', '--global', 'global', '--policy8'], 'RESIDUAL_JOINT_8': ['--lifted', '--envelope', 'RMAX', '--residual', 'residual_joint', '--policy8'], 'FORCED_RESIDUAL': ['--force-stream', 'residual', '--residual', 'residual_joint']}
PRODUCTION_ARMS = ('REPAIRED', 'RESIDUAL_ONLY', 'RESIDUAL_JOINT'); DIAGNOSTIC_ARMS = ('REPAIRED_8', 'RESIDUAL_JOINT_8', 'FORCED_RESIDUAL')
DIRECT_ACTIONS = ('create_joint', 'joint_offer', 'joint_pilot', 'joint_refine', 'global_optimize', 'global_activate', 'residual_optimize', 'residual_activate', 'primary_probe', 'prepare_stream', 'probe_stream', 'create_lifted', 'alias_stream')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def identity(code_root): return {f: sha(os.path.join(code_root, 'code', f)) for f in IDENTITY_FILES}

def cmd_of(arm, model, out, c, seed, root):
    code = os.path.join(root, 'code')
    base = [PY, os.path.join(code, 'cex/hp/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)]
    return base + ARM_ARGS[arm]

def sample_seed(model_sha256, k):
    """the frozen sample-seed rule (PROTOCOL section 3): first eight SHA-256 bytes of 'DGP7-SAMPLE|<model_sha256>|<k>' as an unsigned big-endian integer, reduced to the CLI's domain 1..2^31-1"""
    x = int.from_bytes(hashlib.sha256(('DGP7-SAMPLE|%s|%d' % (model_sha256, k)).encode('utf-8')).digest()[:8], 'big'); return (x % ((1 << 31) - 1)) + 1

def arm_rotation(model_sha256, n): return int(model_sha256[:8], 16) % n

def last_receipt(ledger, job):
    rows = [json.loads(l) for l in open(ledger)]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def amendment_reference(amend, frozen):
    """-> (reference dict {commit, files}, schema label) for the identity check (R8: three accepted schemas; the harness schema keeps the FROZEN engine identity and lets only the named harness files differ)"""
    if amend is None: return frozen['code'], 'FREEZE.json'
    if 'code' in amend and 'files' in amend['code']: return dict(commit=amend['code']['commit'], files=amend['code']['files']), 'validity (DGP6 schema: code.commit / code.files)'
    if 'amendment' in amend and 'files' in amend['amendment']: return dict(commit=amend['amendment']['commit'], files=amend['amendment']['files']), 'validity (DGP7 schema: amendment.commit / amendment.files)'
    if 'amendment_commit' in amend:
        files = dict(frozen['code']['files']); changed = amend.get('files_changed') or {}
        if isinstance(changed, dict): files.update({k: v for k, v in changed.items() if isinstance(v, str)})
        return dict(commit=amend['amendment_commit'], files=files), 'harness (amendment_commit; engine identity = FREEZE.json; harness files overlaid)'
    raise ValueError('unknown amendment schema: keys %s' % sorted(amend))

def global_summary(s):
    """the DGP6 global-stream summary of one planner stream record (the REPAIRED arm's direct proposal)"""
    j = s.get('joint') or {}; m = s.get('mechanism') or {}; sd = m.get('seed') if isinstance(m.get('seed'), dict) else {}
    atts = []
    for a in j.get('attempts', []):
        atts.append({k: a.get(k) for k in ('index', 'kind', 'status', 'why', 'label', 'promoted', 'witness_only', 'winner', 'comparator', 'committed_epoch', 'seconds', 'started_offset_s', 'ended_offset_s', 'optimizer_failure', 'eta', 'baselines', 'forecast', 'pre_forecast', 'admission', 'quantization', 'payback', 'graph', 'float_seed', 'reference')} | dict(plans={k: {kk: (a.get('plans') or {}).get(k, {}).get(kk) for kk in ('n_nodes', 'n_reductions', 'max_splits', 'work_cells', 'peak_entries', 'n_params', 'float_tape_bytes', 'compact_peak_bytes', 'sha256')} for k in ('cap', 'moment')} if a.get('plans') else None, optimizer=({k: (a.get('optimizer') or {}).get(k) for k in ('seconds', 'evaluations', 'cache_hits', 'phases', 'endpoint')} if a.get('optimizer') else None), segment_best=((a.get('segment') or {}).get('best')), certification=a.get('certification'), candidates=a.get('candidates')))
    return dict(kind=s.get('kind'), mode=j.get('global_mode') or j.get('mode'), objective=j.get('objective'), stage=s.get('stage'), closed=s.get('closed'), draws=s.get('draws'), published=s.get('published'), epochs=[{k: e.get(k) for k in ('index', 'reason', 'draws_from', 'draws_to', 'eps_num_epoch', 'eps_num_certificate_after', 'cert_t_at_commit', 'committed_offset_s', 'fingerprint', 'predecessor', 'live_joint_bytes', 'storage_released_bytes')} | dict(proposal={k: e['proposal'].get(k) for k in ('sha256', 'log2_B_W0', 'log2_S_W0sq', 'provenance', 'bytes')}, constants={k: (e.get('constants') or {}).get(k) for k in ('B_eff_log2', 'eps_num', 'rho_X', 'rho_cap', 'cap_tol')}, Z_epoch=e.get('Z_over_cap_EB_DIAGNOSTIC_epoch')) for e in j.get('epochs', [])],
                current_epoch=j.get('current_epoch'), epoch_switches=j.get('epoch_switches'), attempts=atts, pilot=j.get('pilot'), promotion=j.get('promotion'), activation=j.get('activation'), graph=j.get('graph'), refinement_ended=j.get('refinement_ended'), joint_bytes=j.get('joint_bytes'), allowance=j.get('allowance'), epoch_weight_statistics=j.get('epoch_weight_statistics'), seed={k: sd.get(k) for k in ('seconds', 'stages_done', 'stages_total', 'max_splits', 'work_cells', 'consumed_messages', 'peak_owned_bytes', 'owned_bytes', 'zero_rows', 'checker', 'absent_sum_scalars', 'plan_groups')}, elimination=m.get('elimination'), eps_num=m.get('eps_num'), cap_units=m.get('cap_units'), construction_defect=m.get('construction_defect'), candidate_defect=m.get('candidate_defect'), internal_error=m.get('internal_error'), close_release=m.get('close_release'))

def _window_summary(w):
    f = w.get('fit') or {}; k = w.get('kernel') or {}
    return dict(A=w.get('A'), R=w.get('R'), atoms=w.get('atoms'), vol=w.get('vol'), whole_model_region=w.get('whole_model_region'), status=w.get('status'), kind=w.get('kind'), why=w.get('why'), seconds=w.get('seconds'), predicted_work_s=w.get('predicted_work_s'), rank=w.get('rank'), d_ratio=w.get('d_ratio'), gates=w.get('gates'), tighter_than_consumed_1pct=w.get('tighter_than_consumed_1pct'), log2_cap_change_vs_consumed=w.get('log2_cap_change_vs_consumed'), admission=w.get('admission'),
                fit=({kk: f.get(kk) for kk in ('status', 'seconds', 'sweeps', 'best_sweep', 'rows_changed', 'G_ref', 'G_new_float', 'G_new_actual', 'K_float_ref', 'K_float_new', 'K_float_new_actual', 'kappa_publish', 'kappa_fit', 'feasible_actual', 'infeasible_rows', 'zero_rows', 'proxy_ratio_G', 'headroom', 'note')} | dict(context_mode=((f.get('context') or {}).get('mode')), context=f.get('context'))) if f else None,
                kernel=({kk: k.get(kk) for kk in ('ok', 'why', 'zero_target', 'seconds', 'cells', 'region_volume', 'whole_model_region', 'log2_K_ref', 'log2_K_new', 'log2_B_ref', 'log2_B_new', 'gate_ref_ok', 'gate_seed_ok', 'log2_T2_max', 'log2_moment_bound', 'weighted_moment', 'rho_new_clipped', 'same_law', 'identity', 'units')} if k else None))

def residual_summary(s):
    """the residual-stream summary of one planner stream record (RESIDUAL_ONLY / RESIDUAL_JOINT / FORCED_RESIDUAL arms): bank, attempts with their windows, transactions, activation, epochs"""
    j = s.get('joint') or {}; m = s.get('mechanism') or {}; sd = m.get('seed') if isinstance(m.get('seed'), dict) else {}; bank = j.get('bank') or m.get('residual_bank') or {}
    atts = []
    for a in j.get('attempts', []):
        atts.append({k: a.get(k) for k in ('index', 'kind', 'mode', 'status', 'why', 'label', 'promoted', 'committed_epoch', 'seconds', 'started_offset_s', 'ended_offset_s', 'transactions_before', 'T_before_s', 'windows_fitted', 'windows_excluded', 'windows_excluded_sample', 'zero_target', 'payback', 'bank', 'bank_after', 'traceback')} | dict(transaction=a.get('transaction'), graph=({k: (a.get('graph') or {}).get(k) for k in ('label', 'policy', 'alias_G0', 'n_extended', 'total_entries')} if a.get('graph') else None), windows_planned=a.get('windows_planned'), windows=[_window_summary(w) for w in (a.get('windows') or [])]))
    bank_s = {k: bank.get(k) for k in ('version', 'law_identity', 'log2_envelope_B', 'log2_consumed_B', 'log2_initial_seed_cap', 'atoms', 'live_atoms', 'entries', 'bytes', 'owned_bytes', 'scopes', 'scores', 'mean_log2', 'dropped', 'evicted', 'transactions', 'check_seconds', 'check_cells', 'sink', 'retention_time_cap_s', 'model_identity', 'seed_proof_identity')} if bank else None
    return dict(kind=s.get('kind'), mode=j.get('residual_mode') or j.get('mode'), stage=s.get('stage'), closed=s.get('closed'), draws=s.get('draws'), published=s.get('published'), epochs=[{k: e.get(k) for k in ('index', 'reason', 'draws_from', 'draws_to', 'eps_num_epoch', 'eps_num_certificate_after', 'cert_t_at_commit', 'committed_offset_s', 'fingerprint', 'predecessor', 'live_joint_bytes', 'storage_released_bytes')} | dict(proposal={k: e['proposal'].get(k) for k in ('sha256', 'log2_B_W0', 'log2_S_W0sq', 'provenance', 'bytes')}, constants={k: (e.get('constants') or {}).get(k) for k in ('B_eff_log2', 'eps_num', 'rho_X', 'rho_cap', 'cap_tol')}, Z_epoch=e.get('Z_over_cap_EB_DIAGNOSTIC_epoch')) for e in j.get('epochs', [])],
                current_epoch=j.get('current_epoch'), epoch_switches=j.get('epoch_switches'), attempts=atts, pilot=j.get('pilot'), transactions=j.get('transactions'), transactions_done=j.get('transactions_done'), promotion=j.get('promotion'), activation=j.get('activation'), graph=j.get('graph'), refinement_ended=j.get('refinement_ended'), joint_bytes=j.get('joint_bytes'), bank_bytes=j.get('bank_bytes'), allowance=j.get('allowance'), bank=bank_s, epoch_weight_statistics=j.get('epoch_weight_statistics'),
                seed={k: sd.get(k) for k in ('seconds', 'stages_done', 'stages_total', 'max_splits', 'work_cells', 'consumed_messages', 'peak_owned_bytes', 'owned_bytes', 'zero_rows', 'checker', 'absent_sum_scalars', 'plan_groups')}, phases=s.get('ph') or m.get('phases'), elimination=m.get('elimination'), eps_num=m.get('eps_num'), cap_units=m.get('cap_units'), construction_defect=m.get('construction_defect'), candidate_defect=m.get('candidate_defect'), internal_error=m.get('internal_error'), close_release=m.get('close_release'))

def direct_summary(s):
    """dispatch on the stream kind (residual / global / joint)"""
    return residual_summary(s) if s.get('kind') == 'residual' else global_summary(s)

def summarize(arm, out, rc, c):
    from fractions import Fraction as F
    row = dict(receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc and rc.get('peak_tree_rss_bytes') else None))
    try:
        d = json.load(open(out)); m = d.get('mechanism') or {}
        row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), termination=m.get('termination'), route=m.get('route'), peak_rss_bytes=d.get('peak_rss_bytes'), positive_mass_witness=m.get('positive_mass_witness'), hard_deadline_respected=d.get('hard_deadline_respected'), version=(d.get('version') or '')[:60])
        row.update(upac=dict(streams=[{k: s.get(k) for k in ('kind', 'label', 'stage', 'closed', 'delta_s', 'scale_to_original', 'Z_original', 'draws', 'zero_draws', 'batches', 'abandoned', 'checkpoints', 'witness', 'published', 'K', 't_prep', 't_sample', 't_cert', 'X_mean', 'zero_weight_fraction', 'ESS_DIAGNOSTIC', 'largest_share', 'max_log2_X_observed', 'max_remaining_width', 'retained_bytes', 'pooled_weight_statistics')} | dict(valid_endpoints=(s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None, mechanism={k: v for k, v in (s.get('mechanism') or {}).items() if k in ('eps_num', 'rho_cap', 'rho_X', 'alpha_per_coordinate', 'cap_log2_total', 'cap_units', 'grouped_envelope', 'rmax', 'rmax_refusal', 'rmax_allowance', 'bound_kind', 'kappa_compact', 'kappa_log2_hi', 'mb_cap', 'mb_splits', 'Kq', 'batch_used', 'terminal', 'exact_route', 'memory_policy', 'proposal_immutable', 'coarse_cards', 'widening', 'widening_parts', 'certificate_defect', 'const_log2', 'close_release', 'allowance', 'graph_policy', 'residual_mode', 'kind')}, direct=(direct_summary(s) if s.get('kind') in ('joint', 'global', 'residual') else None), trace=s.get('trace'), measurements=[x for x in (s.get('measurements') or []) if x.get('kind') in ('pac_stage', 'lifted_stage', 'joint_stage', 'joint_action')]) for s in d.get('streams', [])],
                              risk_ledger=d.get('risk_ledger'), conflicts=d.get('conflicts'), checkpoints=d.get('checkpoints'), radius_report=d.get('radius_report'), cost_breakdown=d.get('cost_breakdown'), decisions=[{k: x.get(k) for k in ('chosen', 't_s', 'W_s', 'primary_protected', 'why', 'exploration_frac', 'exploration_account_set_s')} | dict(streams=[(s_.get('label'), s_.get('forecast_s'), s_.get('draws')) for s_ in (x.get('streams') or [])], joint_offer=x.get('joint_offer')) for x in d.get('decisions', [])], joint_offer=m.get('joint_offer'), scheduling_policy=m.get('scheduling_policy'), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), refusal=m.get('refusal'), defect=m.get('defect'), structural=m.get('structural_info'), representations_solved=m.get('representations_solved'), native_attempts=m.get('native_attempts'), live_memory=m.get('live_memory_named_bytes'), lift_only=m.get('lift_only_candidates'),
                              forced=d.get('forced_stream'), joint_mode=d.get('joint_mode'), global_mode=d.get('global_mode'), residual_mode=d.get('residual_mode'), policy8=d.get('policy8'), old_policy=d.get('old_policy'), actions=[{k: a.get(k) for k in ('action', 't_s', 'actual_s', 'status', 'result', 'stream', 'stage', 'closed', 'allowance_s', 'absolute_allowance_end_offset_s', 'promoted', 'witness_only', 'winner', 'reason', 'draws', 'batches', 'checks', 'forecast_s', 'label', 'kind', 'why', 'evaluations', 'graph', 'committed_epoch', 'windows_fitted', 'windows_planned', 'log2_B_before', 'log2_B_after', 'rows_changed', 'rank', 'window', 'epoch')} for a in d.get('actions', []) if a.get('action') in DIRECT_ACTIONS]), radius_report=d.get('radius_report'))
    except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:200])
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False)) and arm not in DIAGNOSTIC_ARMS
    return row

def direct_digest(row):
    """one-line digest of the direct stream(s) of a cell for the console"""
    out = []
    for j in (row.get('upac') or {}).get('streams', []):
        d = j.get('direct')
        if not d: continue
        if d.get('kind') == 'residual':
            tx = d.get('transactions') or []; b = d.get('bank') or {}
            out.append(dict(kind='residual', stage=d.get('stage'), draws=d.get('draws'), atoms=b.get('live_atoms'), epochs=len(d.get('epochs') or []), transactions=[(t.get('kind'), t.get('rows_changed'), round(t.get('log2_B_after', 0) - t.get('log2_B_before', 0), 3) if t.get('log2_B_after') is not None and t.get('log2_B_before') is not None else None) for t in tx], attempts=[(x.get('status'), (x.get('transaction') or {}).get('kind') or x.get('kind')) for x in d.get('attempts', [])], activation=((d.get('activation') or {}).get('draws'))))
        else: out.append(dict(kind=d.get('kind'), stage=d.get('stage'), draws=d.get('draws'), epoch_switches=d.get('epoch_switches'), attempts=[(x.get('status'), x.get('kind')) for x in d.get('attempts', [])]))
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--code-root', required=True); ap.add_argument('--arms', default='REPAIRED,RESIDUAL_ONLY,RESIDUAL_JOINT'); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--seed-index', type=int, default=0); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp7_main'); ap.add_argument('--records', default=RD_DEFAULT); ap.add_argument('--freeze', default=None); ap.add_argument('--amendment', default=None); ap.add_argument('--skip-existing', action='store_true')
    ap.add_argument('--no-identity', action='store_true', help='DEVELOPMENT ONLY (refused unless --scope dgp7_dev): run without FREEZE.json; the cell records identity_ok = None and dev_unfrozen = True; never a scored cell'); a = ap.parse_args()
    RD = a.records; man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None); results = []; ledger = os.path.join(RD, 'DGP7_LEDGER.jsonl')
    assert all(arm in ARM_ARGS for arm in arms), 'unknown arm in %s (known: %s)' % (arms, sorted(ARM_ARGS))
    if a.contract == 'p4': assert not any(arm in ('REPAIRED_8', 'RESIDUAL_JOINT_8') for arm in arms), 'the eight-second diagnostic policy never runs on the four-second preservation cohort (brief section 7)'
    root = os.path.abspath(a.code_root); head = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD']).decode().strip(); tree = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD^{tree}']).decode().strip(); dirty = subprocess.check_output(['git', '-C', root, 'status', '--porcelain', '--untracked-files=no', '--', 'code/cex', 'code/gbidi']).decode().strip()
    if a.no_identity:
        assert a.scope == 'dgp7_dev', '--no-identity is a development flag (scope dgp7_dev only)'; ref = None; schema = 'NONE (development, unfrozen)'; ident0 = identity(root); print('DEVELOPMENT RUN WITHOUT FREEZE.json: identity recorded, not checked; dirty tracked files: %r' % dirty[:120])
    else:
        frozen = json.load(open(a.freeze or os.path.join(RD, 'FREEZE.json'))); amend = json.load(open(a.amendment)) if a.amendment else None; ref, schema = amendment_reference(amend, frozen); ident0 = identity(root)
        assert head == ref['commit'], 'code root %s is not at the %s commit %s' % (head, 'amendment' if amend else 'frozen', ref['commit']); assert not dirty, 'code root has tracked changes: %s' % dirty[:200]; assert all(ident0[f] == ref['files'].get(f) for f in ident0), 'identity mismatch vs %s at launch: %s' % (schema, [f for f in ident0 if ident0[f] != ref['files'].get(f)])
    kb = json.load(open(os.path.join(root, 'code/cex/newarm/cex_build.json'))); assert kb['binary_sha256'] == sha(os.path.join(root, 'code/cex/newarm/libcex_kernel.dylib')), 'kernel binary does not match its build record'
    seen = set()
    for t in tasks:
        key = (t['model_sha256'], t['evid_sha256']); assert key not in seen, 'duplicate input identity in the manifest: %s' % t['name']; seen.add(key)
    import dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], RD, t.get('model_sha256'))
    for i, t in enumerate(tasks):
        if a.only and t['name'] not in a.only.split(','): continue
        r = arm_rotation(t['model_sha256'], len(arms)); order = arms[r:] + arms[:r]
        if a.confirm: order = order[::-1]
        seed = sample_seed(t['model_sha256'], a.seed_index)
        for arm in order:
            tag = ('c%d' % a.seed_index) if a.confirm else ('p' if a.seed_index == 0 else 's%d' % a.seed_index); attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag))
            if a.skip_existing and os.path.exists(os.path.join(attempt, 'cell.json')): continue
            os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, seed, root); job = 'dgp7:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            ident_launch = identity(root)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['ceiling']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', CAFF, '-s'] + cmd
            subprocess.run(sup, cwd=SUP_CODE, env=env); rc = last_receipt(ledger, job); ident_done = identity(root)
            ident_ok = (all(ident_launch[f] == ref['files'].get(f) == ident_done[f] for f in ident_launch) if ref is not None else None)
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), confirm=a.confirm, seed=seed, seed_index=a.seed_index, seed_rule=FROZEN['seed_rule'], arm_rotation=FROZEN['arm_rotation'], contract=a.contract, supervisor_ceiling_s=c['ceiling'], panel=t.get('panel'), role=t.get('role'), family=t.get('family') or t.get('topology'), exposure=t.get('exposure'), model=t['model'], model_sha256=t.get('model_sha256'), evid_sha256=t.get('evid_sha256'), model_sha256_at_run=sha(t['model']), code_commit=head, code_tree=tree, identity_ok=ident_ok, identity_reference=schema, dev_unfrozen=bool(a.no_identity), amendment=(os.path.basename(a.amendment) if a.amendment else None), diagnostic_arm=(arm in DIAGNOSTIC_ARMS), command=' '.join(cmd), job=job); row.update(summarize(arm, out, rc, c)); results.append(row)
            json.dump(dict(cell=row, identity_at_launch=ident_launch, identity_at_completion=ident_done), open(os.path.join(attempt, 'cell.json'), 'w'), indent=1, default=str)
            print(json.dumps({k: row.get(k) for k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'complete', 'termination', 'identity_ok')} | dict(direct=direct_digest(row)), default=str), flush=True)
            json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, code_root=root, code_commit=head, code_tree=tree, confirm=a.confirm, seed_index=a.seed_index, only=a.only, identity_reference=schema, dev_unfrozen=bool(a.no_identity), results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s_%s%s.json' % (a.contract, ('confirm_s%d' % a.seed_index) if a.confirm else ('s%d' % a.seed_index if a.seed_index != 0 else 'primary'), ('_' + a.only.replace(',', '_')[:60]) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
