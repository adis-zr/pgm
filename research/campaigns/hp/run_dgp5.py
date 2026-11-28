"""DGP5 supervised runner (derived from run_dgp4.py) (protocol rule 4): every arm executes from a CLEAN DETACHED CHECKOUT at the frozen commit (--code-root), with the worker's cwd set to that checkout, source identity checked at launch and at completion
(sha256 of the planner / engine / kernel / joint files vs FREEZE.json), outputs under the records tree (outside tracked source). Arms (brief section 12): BASE (accepted integrated.py with run_paired.FROZEN options), REPAIRED (unified_pac_planner v0.9 --lifted --envelope RMAX: DGP4 NEW + the six repairs,
new construction disabled), SEED (--lifted --envelope RMAX --joint seed), JOINT (--lifted --envelope RMAX --joint joint); the diagnostic pseudo-arms CAP_ONLY / MOMENT_ONLY (--lifted --envelope RMAX --joint cap_only|moment_only: strategy ablations) and FORCED_SEED / FORCED_JOINT (--force-stream joint --joint seed|joint; the optional-role risk
delta / 4; never completions). Sample seed per task: first eight SHA-256 bytes of 'DGP5-SAMPLE|<model_sha256>|<k>' (unsigned big-endian) reduced to 1..2^31-1 (k = 0 primary, 1 / 2 confirmations), shared across arms. Primary arm order rotated by the model hash (first eight hex digits mod the arm count); reversed for confirmations.
Contracts: main 20.0 / 19.5 / 19.0; p4 4.0 / 3.85 / 3.5; p20 = main. usage: run_dgp5.py SUBDIR MANIFEST.json --code-root /path/to/detached --arms BASE,REPAIRED,SEED,JOINT --contract main|p4|p20 [--confirm --seed-index K] [--only a,b] [--scope S] [--records RD]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from research.source_execution import bound_source_command, supervisor_environment, checked_structural_build, result_native_build
import sys, os, json, time, subprocess, argparse, hashlib
RD_DEFAULT = str(_runs_root() / 'mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION'); SUP_CODE = os.environ.get('PGM_CODE', str(_repo_root())); PY = os.environ.get('PY', sys.executable); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
CONTRACTS = dict(main=dict(outer=20.0, hard=19.5, work=19.0), p4=dict(outer=4.0, hard=3.85, work=3.5), p20=dict(outer=20.0, hard=19.5, work=19.0))
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024), contracts=CONTRACTS)
IDENTITY_FILES = ['src/pgm/algorithms/quotient/unified_pac_planner.py', 'src/pgm/algorithms/quotient/pac_actions.py', 'src/pgm/algorithms/quotient/joint_stream.py', 'src/pgm/algorithms/quotient/joint_proposal.py', 'src/pgm/algorithms/quotient/joint_witness.py', 'src/pgm/algorithms/quotient/joint_optimize.py', 'src/pgm/algorithms/quotient/check_joint.py', 'src/pgm/algorithms/quotient/lifted_decoder.py', 'src/pgm/algorithms/quotient/grouped_envelope.py', 'src/pgm/algorithms/quotient/residual_max_envelope.py', 'src/pgm/algorithms/quotient/unified_planner.py', 'src/pgm/algorithms/quotient/coarse_envelope.py', 'src/pgm/algorithms/quotient/cost_model.py', 'src/pgm/algorithms/quotient/PHASE_RATES_R1.json', 'src/pgm/algorithms/block/integrated.py', 'src/pgm/algorithms/block/blockres.py', 'src/pgm/algorithms/structural/cex_executor.py', 'src/pgm/algorithms/structural/cex_kernel.cpp']
ARM_ARGS = {'REPAIRED': ['--lifted', '--envelope', 'RMAX'], 'SEED': ['--lifted', '--envelope', 'RMAX', '--joint', 'seed'], 'JOINT': ['--lifted', '--envelope', 'RMAX', '--joint', 'joint'], 'CAP_ONLY': ['--lifted', '--envelope', 'RMAX', '--joint', 'cap_only'], 'MOMENT_ONLY': ['--lifted', '--envelope', 'RMAX', '--joint', 'moment_only'], 'FORCED_SEED': ['--force-stream', 'joint', '--joint', 'seed'], 'FORCED_JOINT': ['--force-stream', 'joint', '--joint', 'joint']}
DIAGNOSTIC_ARMS = ('CAP_ONLY', 'MOMENT_ONLY', 'FORCED_SEED', 'FORCED_JOINT')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def identity(code_root): return {f: sha(os.path.join(code_root, f)) for f in IDENTITY_FILES}

def cmd_of(arm, model, out, c, seed, root):
    b = FROZEN['base']; code = str(root)
    if arm == 'BASE': return [PY, os.path.join(code, 'src/pgm/algorithms/block/integrated.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(seed), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    base = [PY, os.path.join(code, 'src/pgm/algorithms/quotient/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)]
    return base + ARM_ARGS[arm]

def sample_seed(model_sha256, k):
    """the frozen sample-seed rule (PROTOCOL section 3): first eight SHA-256 bytes of 'DGP5-SAMPLE|<model_sha256>|<k>' as an unsigned big-endian integer, reduced to the CLI's domain 1..2^31-1"""
    x = int.from_bytes(hashlib.sha256(('DGP5-SAMPLE|%s|%d' % (model_sha256, k)).encode('utf-8')).digest()[:8], 'big'); return (x % ((1 << 31) - 1)) + 1

def arm_rotation(model_sha256, n): return int(model_sha256[:8], 16) % n

def last_receipt(ledger, job):
    rows = [json.loads(l) for l in open(ledger)]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def joint_summary(s):
    j = s.get('joint') or {}; m = s.get('mechanism') or {}; sd = m.get('seed') if isinstance(m.get('seed'), dict) else {}        # HARNESS amendment 2: a joint stream closed BEFORE its seed stage leaves the base Stream's integer RNG seed under mech['seed']
    return dict(mode=j.get('mode'), stage=s.get('stage'), closed=s.get('closed'), draws=s.get('draws'), published=s.get('published'), epochs=[{k: e.get(k) for k in ('index', 'reason', 'draws_from', 'draws_to', 'eps_num_epoch', 'eps_num_certificate_after', 'cert_t_at_commit', 'committed_offset_s', 'fingerprint', 'predecessor', 'live_joint_bytes', 'storage_released_bytes')} | dict(proposal={k: e['proposal'].get(k) for k in ('sha256', 'log2_B_W0', 'log2_S_W0sq', 'conditionals', 'provenance', 'bytes')}, constants={k: (e.get('constants') or {}).get(k) for k in ('B_eff_log2', 'eps_num', 'rho_X', 'rho_cap', 'cap_tol', 'cap_units')}, Z_epoch=e.get('Z_over_cap_EB_DIAGNOSTIC_epoch')) for e in j.get('epochs', [])],
                current_epoch=j.get('current_epoch'), epoch_switches=j.get('epoch_switches'), attempts=j.get('attempts'), pilot=j.get('pilot'), refinement_ended=j.get('refinement_ended'), joint_bytes=j.get('joint_bytes'), allowance=j.get('allowance'), seed={k: sd.get(k) for k in ('seconds', 'stages_done', 'stages_total', 'max_splits', 'work_cells', 'consumed_messages', 'peak_owned_bytes', 'owned_bytes', 'zero_rows', 'checker', 'absent_sum_scalars', 'plan_groups')}, elimination=m.get('elimination'), eps_num=m.get('eps_num'), cap_units=m.get('cap_units'), widening_parts=m.get('widening_parts'), construction_defect=m.get('construction_defect'), candidate_defect=m.get('candidate_defect'), close_release=m.get('close_release'))

def summarize(arm, out, rc, c):
    from fractions import Fraction as F
    row = dict(receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc and rc.get('peak_tree_rss_bytes') else None))
    try:
        d = json.load(open(out)); m = d.get('mechanism') or {}
        row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), termination=m.get('termination'), route=m.get('route'), peak_rss_bytes=d.get('peak_rss_bytes'), positive_mass_witness=(d.get('positive_mass_witness') if arm == 'BASE' else m.get('positive_mass_witness')), hard_deadline_respected=d.get('hard_deadline_respected'), version=(d.get('version') or '')[:60])
        rows_ = d.get('answers') or []; ws = [float(F(r['hi']) - F(r['lo'])) / 2 for r in rows_ if r['guarantee'] != 'NOT_PUBLISHED']
        if arm == 'BASE': row.update(base=dict(draws=m.get('draws'), Kq=m.get('Kq'), remaining=m.get('remaining'), max_remaining_width=m.get('max_remaining_width'), median_remaining_width=m.get('median_remaining_width'), X_mean=m.get('X_mean'), ESS=m.get('ESS'), zero_weight_fraction=m.get('zero_weight_fraction'), largest_share=m.get('largest_share'), eps_num=m.get('eps_num'), mb_cap=m.get('mb_cap'), mb_splits=m.get('mb_splits'), batch_used=m.get('batch_used'), deadline_phase=d.get('deadline_phase'), refusal=d.get('refusal'), trace=d.get('trace'), phases=d.get('phases_s'), structural={k: (m.get(k) or {}).get('status') for k in ('evidence_expansion', 'layered_contraction', 'ancestral_response', 'support_closure')}), radius_report=dict(worst=(max(ws) if ws else None), covered_at_eps=sum(1 for w in ws if w <= 0.005), published=len(ws), K=d.get('K')))
        else: row.update(upac=dict(streams=[{k: s.get(k) for k in ('kind', 'label', 'stage', 'closed', 'delta_s', 'scale_to_original', 'Z_original', 'draws', 'zero_draws', 'batches', 'abandoned', 'checkpoints', 'witness', 'published', 'K', 't_prep', 't_sample', 't_cert', 'X_mean', 'zero_weight_fraction', 'ESS_DIAGNOSTIC', 'largest_share', 'max_log2_X_observed', 'max_remaining_width', 'retained_bytes')} | dict(valid_endpoints=(s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None, mechanism={k: v for k, v in (s.get('mechanism') or {}).items() if k in ('eps_num', 'rho_cap', 'rho_X', 'alpha_per_coordinate', 'cap_log2_total', 'cap_units', 'grouped_envelope', 'rmax', 'rmax_refusal', 'rmax_allowance', 'bound_kind', 'kappa_compact', 'kappa_log2_hi', 'mb_cap', 'mb_splits', 'Kq', 'batch_used', 'terminal', 'exact_route', 'memory_policy', 'proposal_immutable', 'coarse_cards', 'widening', 'widening_parts', 'certificate_defect', 'const_log2', 'close_release')}, joint=(joint_summary(s) if s.get('kind') == 'joint' else None), trace=s.get('trace'), measurements=[x for x in (s.get('measurements') or []) if x.get('kind') in ('pac_stage', 'lifted_stage', 'joint_stage', 'joint_action')]) for s in d.get('streams', [])], risk_ledger=d.get('risk_ledger'), conflicts=d.get('conflicts'), checkpoints=d.get('checkpoints'), radius_report=d.get('radius_report'), cost_breakdown=d.get('cost_breakdown'), decisions=[x.get('chosen') for x in d.get('decisions', [])], joint_offer=m.get('joint_offer'), joint_offer_records=[x.get('joint_offer') for x in d.get('decisions', []) if x.get('joint_offer')], E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), refusal=m.get('refusal'), defect=m.get('defect'), structural=m.get('structural_info'), representations_solved=m.get('representations_solved'), native_attempts=m.get('native_attempts'), live_memory=m.get('live_memory_named_bytes'), lift_only=m.get('lift_only_candidates'), forced=d.get('forced_stream'), joint_mode=d.get('joint_mode'), actions=[{k: a.get(k) for k in ('action', 't_s', 'actual_s', 'status', 'result', 'stream', 'stage', 'closed', 'allowance_s', 'promoted', 'winner', 'reason', 'draws')} for a in d.get('actions', []) if a.get('action') in ('create_joint', 'joint_offer', 'joint_pilot', 'joint_refine', 'prepare_stream', 'probe_stream', 'create_lifted', 'alias_stream')]), radius_report=d.get('radius_report'))
    except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:200])
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False)) and arm not in DIAGNOSTIC_ARMS
    return row

def resummarize(RD, amendment_name):
    """HARNESS amendment 2: for every cell whose recorded summary failed (outcome NO_RESULT_FILE) while its result.json exists, recompute the summary row from the immutable result.json + the ledger receipt; identity fields,
    the receipt and the original error are preserved; the cell records `resummarized`. Never re-runs anything."""
    ledger = os.path.join(RD, 'DGP5_LEDGER.jsonl'); n = 0
    for p in sorted(__import__('glob').glob(os.path.join(RD, 'runs', '*', '*', 'cell.json'))):
        cj = json.load(open(p)); c = cj['cell']; res = os.path.join(os.path.dirname(p), 'result.json')
        if c.get('outcome') != 'NO_RESULT_FILE' or not os.path.exists(res) or 'superseded' in p: continue
        rc = last_receipt(ledger, c['job']); row = summarize(c['arm'], res, rc, CONTRACTS[c['contract']]); orig_err = c.get('error')
        keep = {k: c[k] for k in c if k not in row}; keep.update(row); keep['resummarized'] = dict(amendment=amendment_name, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), original_summary_error=orig_err, note='summary recomputed from the unchanged result.json and the ledger receipt; nothing re-run'); cj['cell'] = keep
        json.dump(cj, open(p, 'w'), indent=1, default=str); n += 1; print('resummarized', os.path.relpath(p, RD), '->', keep.get('outcome'), keep.get('published'), '/', keep.get('K'), 'complete', keep.get('complete'))
    print('resummarized cells:', n)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'resummarize': resummarize(sys.argv[2] if len(sys.argv) > 2 else RD_DEFAULT, sys.argv[3] if len(sys.argv) > 3 else 'FREEZE_AMENDMENT_harness2.json'); return
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--code-root', required=True); ap.add_argument('--arms', default='BASE,REPAIRED,SEED,JOINT'); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--seed-index', type=int, default=0, help='k in DGP5-SAMPLE|<model_sha256>|<k>: 0 primary, 1 / 2 confirmations'); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp5_main'); ap.add_argument('--records', default=RD_DEFAULT); ap.add_argument('--freeze', default=None); ap.add_argument('--amendment', default=None, help='a FREEZE_AMENDMENT_*.json of kind validity whose code.commit / code.files the checkout must match (cells record the amendment)'); ap.add_argument('--skip-existing', action='store_true', help='skip a cell whose cell.json already exists (resuming an interrupted panel after an amendment; superseded cells live in runs/<sub>/superseded_*/)'); a = ap.parse_args()
    RD = a.records; man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env = supervisor_environment(env); results = []; ledger = os.path.join(RD, 'DGP5_LEDGER.jsonl')
    root = os.path.abspath(a.code_root); head = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD']).decode().strip(); tree = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD^{tree}']).decode().strip(); dirty = subprocess.check_output(['git', '-C', root, 'status', '--porcelain', '--untracked-files=no', '--', 'src/pgm/algorithms', 'src/pgm/runtime', 'research']).decode().strip()
    frozen = json.load(open(a.freeze or os.path.join(RD, 'FREEZE.json'))); amend = json.load(open(a.amendment)) if a.amendment else None; ref = (amend['code'] if amend else frozen['code']); ident0 = identity(root); assert head == ref['commit'], 'code root %s is not at the %s commit %s' % (head, 'amendment' if amend else 'frozen', ref['commit']); assert not dirty, 'code root has tracked changes: %s' % dirty[:200]; assert all(ident0[f] == ref['files'].get(f) for f in ident0), 'identity mismatch vs %s at launch: %s' % ('the amendment' if amend else 'FREEZE.json', [f for f in ident0 if ident0[f] != ref['files'].get(f)])
    kb = checked_structural_build(root)
    seen = set()
    for t in tasks:
        key = (t['model_sha256'], t['evid_sha256']); assert key not in seen, 'duplicate input identity in the manifest: %s' % t['name']; seen.add(key)        # preflight: cells are joined by hashes, never names
    import research.campaigns.hp.dgp_paths as dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], RD, t.get('model_sha256'))                  # DGP6 repair (finding 9): packet-relative / DGP_ROOTS resolution; a non-existent recorded path is never used silently
    for i, t in enumerate(tasks):
        if a.only and t['name'] not in a.only.split(','): continue
        r = arm_rotation(t['model_sha256'], len(arms)); order = arms[r:] + arms[:r]
        if a.confirm: order = order[::-1]
        seed = sample_seed(t['model_sha256'], a.seed_index)
        for arm in order:
            tag = ('c%d' % a.seed_index) if a.confirm else ('p' if a.seed_index == 0 else 's%d' % a.seed_index); attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag))
            if a.skip_existing and os.path.exists(os.path.join(attempt, 'cell.json')): continue
            os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, seed, root); job = 'dgp5:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            ident_launch = identity(root)
            cmd = bound_source_command(root, cmd)
            sup = [PY, '-m', 'pgm.runtime.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['outer']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--cwd', str(root), '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--'] + ([CAFF, '-s'] if CAFF and os.path.exists(CAFF) else []) + cmd
            subprocess.run(sup, cwd=SUP_CODE, env=env); rc = last_receipt(ledger, job); ident_done = identity(root)
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), confirm=a.confirm, seed=seed, seed_index=a.seed_index, seed_rule='DGP5-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1', arm_rotation='int(model_sha256[:8], 16) mod len(arms); reversed for confirmations', contract=a.contract, panel=t.get('panel'), family=t.get('family') or t.get('topology'), exposure=t.get('exposure'), model=t['model'], model_sha256=t.get('model_sha256'), evid_sha256=t.get('evid_sha256'), model_sha256_at_run=sha(t['model']), code_commit=head, code_tree=tree, identity_ok=all(ident_launch[f] == ref['files'].get(f) == ident_done[f] for f in ident_launch), amendment=(os.path.basename(a.amendment) if a.amendment else None), command=' '.join(cmd), job=job); row.update(summarize(arm, out, rc, c)); results.append(row)
            json.dump(dict(cell=row, identity_at_launch=ident_launch, identity_at_completion=ident_done), open(os.path.join(attempt, 'cell.json'), 'w'), indent=1, default=str)
            print(json.dumps({k: row.get(k) for k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'complete', 'termination', 'identity_ok')} | dict(joint=[(j['joint']['stage'], j['joint']['draws'], j['joint']['epoch_switches']) for j in (row.get('upac') or {}).get('streams', []) if j.get('joint')]), default=str), flush=True)
            json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, code_root=root, code_commit=head, code_tree=tree, confirm=a.confirm, seed_index=a.seed_index, only=a.only, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s_%s%s.json' % (a.contract, ('confirm_s%d' % a.seed_index) if a.confirm else ('s%d' % a.seed_index if a.seed_index != 0 else 'primary'), ('_' + a.only.replace(',', '_')[:60]) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
