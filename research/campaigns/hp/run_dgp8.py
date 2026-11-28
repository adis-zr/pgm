"""DGP8 supervised runner (derived from run_dgp7.py / run_dgp6.py) (protocol rule 4): every arm executes from a CLEAN DETACHED CHECKOUT at the frozen commit (--code-root), with the worker's cwd set to that checkout, source identity checked at launch and at
completion (sha256 of the planner / engine / kernel / construction / residual / spectral heat-bath files vs FREEZE.json), outputs under the records tree. Arms (PROTOCOL.md section 2): BASE (the accepted engine v2.13.2 `cex/blockres/integrated.py` with run_paired.FROZEN options,
exactly run_dgp6's BASE command), REPAIRED (unified_pac_planner --lifted --envelope RMAX --global global: the DGP7-repaired engine's production arm), SPECTRAL_HEATBATH (the standalone runner `cex/hp/spectral_heatbath_run.py`: checked spectral witness + exact heat-bath + the
separate Markov certificate; same contract and sample-seed rule), SELECT (reserved: the integrated planner selection; REFUSED unless --allow-select with a frozen request-level risk allocation -- not expected this round); diagnostic pseudo-arm HEATBATH_SCREEN (= SPECTRAL_HEATBATH +
--dev-stream 2.0: the Stage A witness + predeclared 2.0 s development stream; never a completion). Sample seed per task: first eight SHA-256 bytes of 'DGP8-SAMPLE|<model_sha256>|<k>' (unsigned big-endian) reduced to 1..2^31-1 (k = 0 primary, 1 = the second guard seed), shared
across arms. Arm order rotated by the model hash (first eight hex digits mod the arm count); reversed for --confirm / --reverse. Contracts: main 20.0 / 19.5 / 19.0 (supervisor ceiling 24); p4 4.0 / 3.85 / 3.5 (ceiling 6); p20 = main. Input paths resolve through dgp_paths
(packet-relative / DGP_ROOTS; sha256-checked). Amendment schemas as run_dgp7 (validity DGP6 / DGP7 schemas; harness schema keeps the frozen engine identity).
usage: run_dgp8.py SUBDIR MANIFEST.json --code-root /path/to/detached --arms BASE,REPAIRED,SPECTRAL_HEATBATH --contract main|p4|p20 [--seed-index K] [--reverse] [--only a,b] [--scope S] [--records RD] [--freeze F] [--amendment F] [--skip-existing] [--allow-select] [--no-identity (dgp8_dev only)]"""

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
import research.campaigns.hp.run_dgp7 as R7
RD_DEFAULT = str(_runs_root() / 'mdi_2026-10-28/DGP8_SPECTRAL_HEATBATH'); SUP_CODE = os.environ.get('PGM_CODE', str(_repo_root())); PY = os.environ.get('PY', sys.executable); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
CONTRACTS = dict(main=dict(outer=20.0, hard=19.5, work=19.0, ceiling=24.0), p4=dict(outer=4.0, hard=3.85, work=3.5, ceiling=6.0), p20=dict(outer=20.0, hard=19.5, work=19.0, ceiling=24.0))
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024), contracts=CONTRACTS, seed_rule='DGP8-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1', arm_rotation='int(model_sha256[:8], 16) mod len(arms); reversed under --reverse / --confirm', dev_stream_s=2.0)
HEATBATH_FILES = ['src/pgm/algorithms/response/spectral_witness.py', 'src/pgm/algorithms/response/heatbath_exact.py', 'src/pgm/algorithms/response/heatbath_native.c', 'src/pgm/algorithms/response/heatbath_native.py', 'src/pgm/algorithms/response/markov_certificate.py', 'src/pgm/algorithms/response/spectral_heatbath_run.py']
IDENTITY_FILES = list(R7.IDENTITY_FILES) + HEATBATH_FILES          # DGP8: the six spectral heat-bath files join the arm identity (the first 28 entries are run_dgp7.IDENTITY_FILES verbatim)
assert IDENTITY_FILES[:len(R7.IDENTITY_FILES)] == list(R7.IDENTITY_FILES)
HB_ARGS = ['--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
ARM_ARGS = {'BASE': None, 'REPAIRED': ['--lifted', '--envelope', 'RMAX', '--global', 'global'], 'SPECTRAL_HEATBATH': list(HB_ARGS), 'HEATBATH_SCREEN': list(HB_ARGS) + ['--dev-stream', str(FROZEN['dev_stream_s'])], 'SELECT': ['--lifted', '--envelope', 'RMAX', '--global', 'global', '--heatbath', 'select']}
PRODUCTION_ARMS = ('BASE', 'REPAIRED', 'SPECTRAL_HEATBATH'); DIAGNOSTIC_ARMS = ('HEATBATH_SCREEN', 'SELECT'); HEATBATH_ARMS = ('SPECTRAL_HEATBATH', 'HEATBATH_SCREEN')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def identity(code_root, tolerate_missing=False):
    out = {}
    for f in IDENTITY_FILES:
        p = os.path.join(code_root, f)
        if os.path.exists(p): out[f] = sha(p)
        elif tolerate_missing: out[f] = None
        else: raise FileNotFoundError('identity file absent from the checkout: %s' % f)
    return out

def cmd_of(arm, model, out, c, seed, root, rates=None):
    b = FROZEN['base']; code = str(root)
    if arm == 'BASE': return [PY, os.path.join(code, 'src/pgm/algorithms/block/integrated.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(seed), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    if arm in HEATBATH_ARMS:
        cmd = [PY, os.path.join(code, 'src/pgm/algorithms/response/spectral_heatbath_run.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--seed', str(seed)] + ARM_ARGS[arm]
        if rates and os.path.exists(rates): cmd += ['--rate-model', rates]
        return cmd
    return [PY, os.path.join(code, 'src/pgm/algorithms/quotient/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)] + ARM_ARGS[arm]

def sample_seed(model_sha256, k):
    """the frozen sample-seed rule (PROTOCOL section 3): first eight SHA-256 bytes of 'DGP8-SAMPLE|<model_sha256>|<k>' as an unsigned big-endian integer, reduced to the CLI's domain 1..2^31-1"""
    x = int.from_bytes(hashlib.sha256(('DGP8-SAMPLE|%s|%d' % (model_sha256, k)).encode('utf-8')).digest()[:8], 'big'); return (x % ((1 << 31) - 1)) + 1

arm_rotation = R7.arm_rotation; last_receipt = R7.last_receipt; amendment_reference = R7.amendment_reference; direct_summary = R7.direct_summary

def heatbath_summary(d):
    """the spectral heat-bath digest of one standalone result (mechanism keys per PROTOCOL section 5; every access defensive)"""
    m = d.get('mechanism') or {}; w = m.get('witness') or {}; tr = m.get('transitions') or {}; cps = m.get('checkpoints') or []; bi = m.get('burn_in') or {}; p0 = m.get('p0') or {}; ds = m.get('dev_stream'); rf = m.get('refusal'); ph = m.get('phases_s') or {}; by = m.get('bytes') or {}
    done = [c for c in cps if isinstance(c, dict) and c.get('completed')]; last = done[-1] if done else None
    return dict(route=m.get('route'), refusal=rf, refusal_kind=(rf or {}).get('kind') if isinstance(rf, dict) else rf, eligible=w.get('eligible'), l=w.get('l'), u=w.get('u'), width=w.get('width'), margin_m=w.get('margin_m'), gap_g=w.get('gap_g'), dimension=w.get('dimension'), n=w.get('n'), witness_bytes=w.get('bytes'), witness_seconds_construct=w.get('seconds_construct'), witness_seconds_verify=w.get('seconds_verify'), log_enclosure_max_width=w.get('log_enclosure_max_width'), matrix_max_width=w.get('matrix_max_width'), min_pivot_lower_bound=w.get('min_pivot_lower_bound'), proposal_eigs=w.get('proposal_eigs'),
                x0=m.get('x0'), log2_p0_lower=p0.get('log2_p0_lower'), log2_Z_upper=p0.get('log2_Z_upper'), burn_in_steps=bi.get('steps'), burn_in_beta=bi.get('beta'), checkpoints=[{k: c.get(k) for k in ('index', 'N', 'delta_j', 'radius', 'completed', 'worst_radius', 'published_rows', 'seconds')} for c in cps if isinstance(c, dict)], checkpoints_completed=len(done), last_completed_checkpoint=last, certified_radius=(last or {}).get('radius'), worst_radius_achieved=(last or {}).get('worst_radius'),
                transitions_total=tr.get('total'), transitions_burn_in=tr.get('burn_in'), transitions_recorded=tr.get('recorded'), native_resolved=tr.get('native_resolved'), exact_fallbacks=tr.get('exact_fallbacks'), steps_per_second=tr.get('steps_per_second'), rate_model=m.get('rate_model'), phases_s=ph, bytes=by, dev_stream=ds, dev_steps_per_second=((ds or {}).get('steps_per_second') if isinstance(ds, dict) else None), fast_path_share=((ds or {}).get('fast_path_share') if isinstance(ds, dict) else None), Z_enclosure=d.get('Z_enclosure'), K=d.get('K'), published=d.get('published'), n_enclosures=len(d.get('enclosures') or []))

def summarize(arm, out, rc, c):
    from fractions import Fraction as F
    row = dict(receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc and rc.get('peak_tree_rss_bytes') else None))
    try:
        d = json.load(open(out)); m = d.get('mechanism') or {}
        row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), termination=m.get('termination'), route=m.get('route'), peak_rss_bytes=d.get('peak_rss_bytes'), positive_mass_witness=(d.get('positive_mass_witness') if (arm == 'BASE' or arm in HEATBATH_ARMS) and d.get('positive_mass_witness') is not None else m.get('positive_mass_witness')), hard_deadline_respected=d.get('hard_deadline_respected'), version=(d.get('version') or '')[:60])
        rows_ = d.get('answers') or []; ws = [float(F(r['hi']) - F(r['lo'])) / 2 for r in rows_ if r.get('guarantee') != 'NOT_PUBLISHED']; row['max_published_radius'] = (max(ws) if ws else None)
        if arm == 'BASE': row.update(base=dict(draws=m.get('draws'), Kq=m.get('Kq'), remaining=m.get('remaining'), max_remaining_width=m.get('max_remaining_width'), median_remaining_width=m.get('median_remaining_width'), X_mean=m.get('X_mean'), ESS=m.get('ESS'), zero_weight_fraction=m.get('zero_weight_fraction'), largest_share=m.get('largest_share'), eps_num=m.get('eps_num'), mb_cap=m.get('mb_cap'), mb_splits=m.get('mb_splits'), batch_used=m.get('batch_used'), deadline_phase=d.get('deadline_phase'), refusal=d.get('refusal'), trace=d.get('trace'), phases=d.get('phases_s'), structural={k: (m.get(k) or {}).get('status') for k in ('evidence_expansion', 'layered_contraction', 'ancestral_response', 'support_closure') if isinstance(m.get(k), dict)}))
        elif arm in HEATBATH_ARMS: row.update(heatbath=heatbath_summary(d))
        else: row.update(upac=dict(streams=[{k: s.get(k) for k in ('kind', 'label', 'stage', 'closed', 'delta_s', 'scale_to_original', 'Z_original', 'draws', 'zero_draws', 'batches', 'abandoned', 'checkpoints', 'witness', 'published', 'K', 't_prep', 't_sample', 't_cert', 'X_mean', 'zero_weight_fraction', 'ESS_DIAGNOSTIC', 'largest_share', 'max_log2_X_observed', 'max_remaining_width', 'retained_bytes', 'pooled_weight_statistics')} | dict(valid_endpoints=(s.get('trace') or [{}])[-1].get('valid_endpoints') if s.get('trace') else None, mechanism={k: v for k, v in (s.get('mechanism') or {}).items() if k in ('eps_num', 'rho_cap', 'rho_X', 'alpha_per_coordinate', 'cap_log2_total', 'cap_units', 'grouped_envelope', 'rmax', 'rmax_refusal', 'rmax_allowance', 'bound_kind', 'kappa_compact', 'kappa_log2_hi', 'mb_cap', 'mb_splits', 'Kq', 'batch_used', 'terminal', 'exact_route', 'memory_policy', 'proposal_immutable', 'coarse_cards', 'widening', 'widening_parts', 'certificate_defect', 'const_log2', 'close_release', 'allowance', 'graph_policy', 'residual_mode', 'kind')}, direct=(direct_summary(s) if s.get('kind') in ('joint', 'global', 'residual') else None), trace=s.get('trace')) for s in d.get('streams', [])],
                              risk_ledger=d.get('risk_ledger'), conflicts=d.get('conflicts'), checkpoints=d.get('checkpoints'), radius_report=d.get('radius_report'), cost_breakdown=d.get('cost_breakdown'), decisions=[{k: x.get(k) for k in ('chosen', 't_s', 'W_s', 'primary_protected', 'why', 'exploration_frac', 'exploration_account_set_s')} | dict(streams=[(s_.get('label'), s_.get('forecast_s'), s_.get('draws')) for s_ in (x.get('streams') or [])], joint_offer=x.get('joint_offer')) for x in d.get('decisions', [])], joint_offer=m.get('joint_offer'), scheduling_policy=m.get('scheduling_policy'), E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), refusal=m.get('refusal'), defect=m.get('defect'), structural=m.get('structural_info'), representations_solved=m.get('representations_solved'), native_attempts=m.get('native_attempts'), live_memory=m.get('live_memory_named_bytes'), lift_only=m.get('lift_only_candidates'),
                              forced=d.get('forced_stream'), joint_mode=d.get('joint_mode'), global_mode=d.get('global_mode'), residual_mode=d.get('residual_mode'), heatbath_mode=d.get('heatbath_mode'), policy8=d.get('policy8'), old_policy=d.get('old_policy'), actions=[{k: a.get(k) for k in ('action', 't_s', 'actual_s', 'status', 'result', 'stream', 'stage', 'closed', 'allowance_s', 'absolute_allowance_end_offset_s', 'promoted', 'witness_only', 'winner', 'reason', 'draws', 'batches', 'checks', 'forecast_s', 'label', 'kind', 'why', 'evaluations', 'graph', 'committed_epoch', 'epoch')} for a in d.get('actions', []) if a.get('action') in R7.DIRECT_ACTIONS]), radius_report=d.get('radius_report'))
    except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:200])
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False)) and arm not in DIAGNOSTIC_ARMS
    return row

def digest(arm, row):
    """one-line console digest"""
    if arm in HEATBATH_ARMS:
        h = row.get('heatbath') or {}; return dict(eligible=h.get('eligible'), width=h.get('width'), gap=h.get('gap_g'), refusal=h.get('refusal_kind'), burn_in=h.get('burn_in_steps'), recorded=h.get('transitions_recorded'), steps_per_s=h.get('steps_per_second') or h.get('dev_steps_per_second'), fallbacks=h.get('exact_fallbacks'), checkpoints=h.get('checkpoints_completed'), radius=h.get('certified_radius'), worst=h.get('worst_radius_achieved'))
    if arm == 'BASE': b = row.get('base') or {}; return dict(draws=b.get('draws'), max_remaining_width=b.get('max_remaining_width'))
    return dict(direct=R7.direct_digest(row))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--code-root', required=True); ap.add_argument('--arms', default='BASE,REPAIRED,SPECTRAL_HEATBATH'); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--reverse', action='store_true', help='reverse the rotated arm order (the second guard seed runs reversed)'); ap.add_argument('--seed-index', type=int, default=0); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp8_guard'); ap.add_argument('--records', default=RD_DEFAULT); ap.add_argument('--freeze', default=None); ap.add_argument('--amendment', default=None); ap.add_argument('--skip-existing', action='store_true'); ap.add_argument('--allow-select', action='store_true', help='SELECT is reserved for an integrated planner arm with a FROZEN request-level risk allocation; refused without this flag (and expected NOT RUN this round)')
    ap.add_argument('--rates', default=None, help='the frozen heat-bath rate model file passed to spectral_heatbath_run.py (--rate-model); default <RD>/HEATBATH_RATES.json when it exists'); ap.add_argument('--no-identity', action='store_true', help='DEVELOPMENT ONLY (refused unless --scope dgp8_dev): run without FREEZE.json; the cell records identity_ok = None and dev_unfrozen = True; never a scored cell'); a = ap.parse_args()
    RD = a.records; man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env = supervisor_environment(env); results = []; ledger = os.path.join(RD, 'DGP8_LEDGER.jsonl'); rates = a.rates or os.path.join(RD, 'HEATBATH_RATES.json')
    assert all(arm in ARM_ARGS for arm in arms), 'unknown arm in %s (known: %s)' % (arms, sorted(ARM_ARGS))
    if 'SELECT' in arms and not a.allow_select: raise SystemExit('SELECT refused: the integrated selection arm needs a frozen request-level risk allocation across the primary PAC route and the heat-bath route (brief section 4); pass --allow-select only with that allocation recorded in FREEZE.json')
    root = os.path.abspath(a.code_root); head = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD']).decode().strip(); tree = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD^{tree}']).decode().strip(); dirty = subprocess.check_output(['git', '-C', root, 'status', '--porcelain', '--untracked-files=no', '--', 'src/pgm/algorithms', 'src/pgm/runtime', 'research']).decode().strip()
    if a.no_identity:
        assert a.scope == 'dgp8_dev', '--no-identity is a development flag (scope dgp8_dev only)'; ref = None; schema = 'NONE (development, unfrozen)'; ident0 = identity(root, tolerate_missing=True); print('DEVELOPMENT RUN WITHOUT FREEZE.json: identity recorded, not checked; dirty tracked files: %r; absent identity files: %s' % (dirty[:120], [f for f, h in ident0.items() if h is None]))
    else:
        frozen = json.load(open(a.freeze or os.path.join(RD, 'FREEZE.json'))); amend = json.load(open(a.amendment)) if a.amendment else None; ref, schema = amendment_reference(amend, frozen); ident0 = identity(root)
        assert head == ref['commit'], 'code root %s is not at the %s commit %s' % (head, 'amendment' if amend else 'frozen', ref['commit']); assert not dirty, 'code root has tracked changes: %s' % dirty[:200]; assert all(ident0[f] == ref['files'].get(f) for f in ident0), 'identity mismatch vs %s at launch: %s' % (schema, [f for f in ident0 if ident0[f] != ref['files'].get(f)])
    kb = checked_structural_build(root)
    hb_build = None
    seen = set()
    for t in tasks:
        key = (t['model_sha256'], t['evid_sha256']); assert key not in seen, 'duplicate input identity in the manifest: %s' % t['name']; seen.add(key)
    import research.campaigns.hp.dgp_paths as dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], RD, t.get('model_sha256'))
    for i, t in enumerate(tasks):
        if a.only and t['name'] not in a.only.split(','): continue
        r = arm_rotation(t['model_sha256'], len(arms)); order = arms[r:] + arms[:r]
        if a.confirm or a.reverse: order = order[::-1]
        seed = sample_seed(t['model_sha256'], a.seed_index)
        for arm in order:
            tag = ('c%d' % a.seed_index) if a.confirm else ('p' if a.seed_index == 0 else 's%d' % a.seed_index); attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag))
            if a.skip_existing and os.path.exists(os.path.join(attempt, 'cell.json')): continue
            os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, seed, root, rates=rates); job = 'dgp8:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            ident_launch = identity(root, tolerate_missing=bool(a.no_identity))
            cmd = bound_source_command(root, cmd)
            sup = [PY, '-m', 'pgm.runtime.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['ceiling']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--cwd', str(root), '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--'] + ([CAFF, '-s'] if CAFF and os.path.exists(CAFF) else []) + cmd
            subprocess.run(sup, cwd=SUP_CODE, env=env); rc = last_receipt(ledger, job); ident_done = identity(root, tolerate_missing=bool(a.no_identity))
            ident_ok = (all(ident_launch[f] == ref['files'].get(f) == ident_done[f] for f in ident_launch) if ref is not None else None)
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), confirm=a.confirm, reverse=bool(a.reverse), seed=seed, seed_index=a.seed_index, seed_rule=FROZEN['seed_rule'], arm_rotation=FROZEN['arm_rotation'], contract=a.contract, supervisor_ceiling_s=c['ceiling'], panel=t.get('panel'), role=t.get('role'), coupling=t.get('coupling') or t.get('scale'), family=t.get('family') or t.get('topology'), n=t.get('n'), card=t.get('card'), exposure=t.get('exposure'), model=t['model'], model_sha256=t.get('model_sha256'), evid_sha256=t.get('evid_sha256'), model_sha256_at_run=sha(t['model']), code_commit=head, code_tree=tree, identity_ok=ident_ok, identity_reference=schema, dev_unfrozen=bool(a.no_identity), amendment=(os.path.basename(a.amendment) if a.amendment else None), diagnostic_arm=(arm in DIAGNOSTIC_ARMS), heatbath_build=result_native_build(out), rate_model_file=(rates if (arm in HEATBATH_ARMS and os.path.exists(rates)) else None), archived_incumbent=t.get('archived_incumbent'), command=' '.join(cmd), job=job); row.update(summarize(arm, out, rc, c)); results.append(row)
            json.dump(dict(cell=row, identity_at_launch=ident_launch, identity_at_completion=ident_done), open(os.path.join(attempt, 'cell.json'), 'w'), indent=1, default=str)
            print(json.dumps({k: row.get(k) for k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'complete', 'max_published_radius', 'identity_ok')} | dict(digest=digest(arm, row)), default=str), flush=True)
            json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, code_root=root, code_commit=head, code_tree=tree, confirm=a.confirm, reverse=bool(a.reverse), seed_index=a.seed_index, only=a.only, identity_reference=schema, dev_unfrozen=bool(a.no_identity), results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s_%s%s.json' % (a.contract, ('confirm_s%d' % a.seed_index) if a.confirm else ('s%d' % a.seed_index if a.seed_index != 0 else 'primary'), ('_' + a.only.replace(',', '_')[:60]) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
