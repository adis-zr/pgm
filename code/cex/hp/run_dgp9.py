"""DGP9 supervised runner (derived from run_dgp8.py) (protocol rule 4): every arm executes from a CLEAN DETACHED CHECKOUT at the frozen commit (--code-root), with the worker's cwd set to that checkout, source identity checked at launch
and at completion against FREEZE.json (or a recorded amendment), the input bound by sha256 at launch, one supervisor receipt per cell in the round ledger, and cell.json next to result.json. Arms (PROTOCOL section 4): INCUMBENT = the
repaired engine without the heat-bath route (unified_pac_planner --lifted --envelope RMAX --global global); HB_FIXED = the repaired standalone heat-bath runner with the DGP8 proposal / checkpoint policy (--policy fixed); HB_REVISED = the
same runner with mechanism changes A + B (--policy revised); HB_SCREEN = HB_REVISED's witness + a development stream (--dev-stream; diagnostic, never scored). Both heat-bath arms REQUIRE the frozen rate model (--rates; the runner fails
typed when the file is absent -- never a default rate) and record its sha256 and the native build identity in cell.json (review RV7). Arm order per task rotates by the input hash (reversed under --reverse). Sample seed rule
`DGP9-SAMPLE|<model_sha256>|<k>`. usage: run_dgp9.py SUBDIR MANIFEST.json --code-root ROOT --arms INCUMBENT,HB_FIXED,HB_REVISED --contract main|p4|p20 [--seed-index K] [--reverse] [--only a,b] [--scope S] [--records RD] [--freeze F]
[--amendment F] [--rates F] [--skip-existing] [--no-identity (dev only)]"""
import sys, os, json, time, subprocess, argparse, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_dgp7 as R7, run_dgp8 as R8
RD_DEFAULT = os.environ.get('DGP9_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION'); SUP_CODE = os.environ.get('PGM_CODE', '/Users/adis/Workspace/pgm/code'); PY = os.environ.get('PY', os.path.join(SUP_CODE, '.venv/bin/python')); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
CONTRACTS = dict(R8.CONTRACTS)
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', contracts=CONTRACTS, seed_rule='DGP9-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1', arm_rotation='int(model_sha256[:8], 16) mod len(arms); reversed under --reverse', dev_stream_s=2.0)
HEATBATH_FILES = list(R8.HEATBATH_FILES); IDENTITY_FILES = list(R8.IDENTITY_FILES)
HB_ARGS = ['--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
ARM_ARGS = {'INCUMBENT': ['--lifted', '--envelope', 'RMAX', '--global', 'global'], 'HB_FIXED': list(HB_ARGS) + ['--policy', 'fixed'], 'HB_REVISED': list(HB_ARGS) + ['--policy', 'revised'], 'HB_SCREEN': list(HB_ARGS) + ['--policy', 'revised', '--dev-stream', str(FROZEN['dev_stream_s'])]}
PRODUCTION_ARMS = ('INCUMBENT', 'HB_FIXED', 'HB_REVISED'); DIAGNOSTIC_ARMS = ('HB_SCREEN',); HEATBATH_ARMS = ('HB_FIXED', 'HB_REVISED', 'HB_SCREEN')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
identity = R8.identity; sample_seed_8 = R8.sample_seed


def sample_seed(model_sha256, k):
    x = int.from_bytes(hashlib.sha256(('DGP9-SAMPLE|%s|%d' % (model_sha256, k)).encode('utf-8')).digest()[:8], 'big'); return (x % ((1 << 31) - 1)) + 1


def cmd_of(arm, model, out, c, seed, root, rates=None):
    code = os.path.join(root, 'code')
    if arm in HEATBATH_ARMS:
        if arm in PRODUCTION_ARMS and not rates: raise SystemExit('the production heat-bath arms require the frozen rate model (--rates)')
        return [PY, os.path.join(code, 'cex/hp/spectral_heatbath_run.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--seed', str(seed)] + ARM_ARGS[arm] + (['--rate-model', rates] if rates else [])          # HB_SCREEN (development stream) measures the rate: no model yet
    return [PY, os.path.join(code, 'cex/hp/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)] + ARM_ARGS[arm]


def heatbath_summary(d):
    m = d.get('mechanism') or {}; w = m.get('witness') or {}; tr = m.get('transitions') or {}; cps = [x for x in (m.get('checkpoints') or []) if isinstance(x, dict)]; bi = m.get('burn_in') or {}; p0 = m.get('p0') or {}; ds = m.get('dev_stream') if isinstance(m.get('dev_stream'), dict) else None; rf = m.get('refusal'); ph = d.get('phases_s') or {}; by = m.get('bytes') or {}; cr = m.get('chain_record') or {}; cert = m.get('certificate') or {}; plan = m.get('checkpoint_plan') or {}
    done = [x for x in cps if x.get('completed')]; last = done[-1] if done else None
    return dict(route=m.get('route'), policy=m.get('policy'), refusal=rf, refusal_kind=((rf or {}).get('kind') if isinstance(rf, dict) else rf), eligible=w.get('eligible'), l=w.get('l'), u=w.get('u'), width=w.get('width'), width_proposal_float=w.get('width_proposal_float'), margin_m=w.get('margin_m'), gap_g=w.get('gap_g'), attempts=[{k: x.get(k) for k in ('attempt', 'extra_margin', 'lower_ok', 'upper_ok', 'min_pivot_lower', 'seconds', 'width_float')} for x in (w.get('attempts') or [])], dimension=w.get('dimension'), n=w.get('n'),
                witness_seconds_construct=w.get('seconds_construct'), witness_seconds_verify=w.get('seconds_verify'), witness_bytes=w.get('bytes'), witness_retained_bytes=w.get('retained_bytes'), log_enclosure_max_width=w.get('log_width_max'), matrix_max_width=w.get('matrix_width_max'), x0=m.get('x0'), log2_p0_lower=p0.get('log2_p0_lower'), burn_in_steps=bi.get('steps'), chain=m.get('chain'), native_refusal=m.get('native_refusal'), native_range=cr.get('range'), native_bytes=dict(admitted=cr.get('bytes_admitted'), actual=cr.get('bytes_actual')), native_build=m.get('native_build'),
                checkpoint_plan=dict(policy=plan.get('policy'), N_max=plan.get('N_max'), N_floor=plan.get('N_floor'), N_1=plan.get('N_1'), rho_N=plan.get('rho_N'), J_max=plan.get('J_max'), declared=len(plan.get('plan') or []), plan_head=(plan.get('plan') or [])[:4], plan_last=((plan.get('plan') or [None])[-1]), risk_sum=plan.get('risk_sum'), rate_steps_per_s=plan.get('rate_steps_per_s')), checkpoints=[{k: c.get(k) for k in ('index', 'N', 'delta_j', 'radius', 'published_rows', 'variables_published', 'enclosures', 'seconds', 'checkpoint_overhead_s')} for c in cps],
                checkpoints_declared=m.get('checkpoints_declared'), checkpoints_completed=len(done), sampling_stop=m.get('sampling_stop'), certified_radius=cert.get('radius'), certified_N=cert.get('N'), worst_radius_on_inventory=cert.get('worst_radius_on_inventory'), total_failure_probability=cert.get('total_failure_probability'), publication=cert.get('publication'), transitions_total=tr.get('total'), transitions_burn_in=tr.get('burn_in'), transitions_recorded=tr.get('recorded'), exact_fallbacks=tr.get('exact_fallbacks'), poll_returns=tr.get('poll_returns'), steps_per_second=tr.get('steps_per_second'),
                rate_model=m.get('rate_model'), rate_model_file=m.get('rate_model_file'), phases_s=ph, bytes=by, dev_stream=ds, dev_steps_per_second=((ds or {}).get('steps_per_second') if ds else None), fast_path_share=((ds or {}).get('fast_path_share') if ds else None), checkpoint_overhead_s=((ds or {}).get('checkpoint_overhead_s') if ds else None), Z_enclosure=d.get('Z_enclosure'), K=d.get('K'), published=d.get('published'), n_enclosures=len(d.get('enclosures') or []), ledger_identity=m.get('constructor_live_ledger_identity'), live_at_end=m.get('constructor_live_at_end_bytes'), defect=m.get('defect'), internal_error=m.get('internal_error'), traceback=m.get('traceback'))


def summarize(arm, out, rc, c):
    from fractions import Fraction as F
    row = dict(receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc and rc.get('peak_tree_rss_bytes') else None))
    try:
        d = json.load(open(out)); m = d.get('mechanism') or {}
        row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), termination=m.get('termination'), route=m.get('route'), peak_rss_bytes=d.get('peak_rss_bytes'), positive_mass_witness=(d.get('positive_mass_witness') if arm in HEATBATH_ARMS and d.get('positive_mass_witness') is not None else m.get('positive_mass_witness')), hard_deadline_respected=d.get('hard_deadline_respected'), version=(d.get('version') or '')[:80])
        rows_ = d.get('answers') or []; ws = [float(F(r['hi']) - F(r['lo'])) / 2 for r in rows_ if r.get('guarantee') != 'NOT_PUBLISHED']; row['max_published_radius'] = (max(ws) if ws else None)
        if arm in HEATBATH_ARMS: row.update(heatbath=heatbath_summary(d))
        else: row['upac'] = R8.summarize('REPAIRED', out, rc, c).get('upac'); row['radius_report'] = d.get('radius_report')
    except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:200])
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False)) and arm not in DIAGNOSTIC_ARMS
    return row


def digest(arm, row):
    if arm in HEATBATH_ARMS:
        h = row.get('heatbath') or {}; return dict(eligible=h.get('eligible'), width=h.get('width'), attempts=len(h.get('attempts') or []), gap=h.get('gap_g'), refusal=h.get('refusal_kind'), chain=h.get('chain'), declared=h.get('checkpoints_declared'), completed=h.get('checkpoints_completed'), recorded=h.get('transitions_recorded'), steps_per_s=h.get('steps_per_second') or h.get('dev_steps_per_second'), fallbacks=h.get('exact_fallbacks'), radius=h.get('certified_radius'), worst=h.get('worst_radius_on_inventory'), stop=h.get('sampling_stop'))
    return dict(direct=R7.direct_digest(row))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--code-root', required=True); ap.add_argument('--arms', default='INCUMBENT,HB_FIXED,HB_REVISED'); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--reverse', action='store_true'); ap.add_argument('--seed-index', type=int, default=0); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp9_main'); ap.add_argument('--records', default=RD_DEFAULT); ap.add_argument('--freeze', default=None); ap.add_argument('--amendment', default=None); ap.add_argument('--skip-existing', action='store_true')
    ap.add_argument('--rates', default=None, help='the frozen heat-bath rate model file (REQUIRED for the heat-bath arms; default <RD>/HEATBATH_RATES.json when it exists; an absent requested file is a typed cell failure)'); ap.add_argument('--no-identity', action='store_true', help='DEVELOPMENT ONLY (refused unless --scope dgp9_dev or dgp9_screen)'); a = ap.parse_args()
    RD = a.records; man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None); results = []; ledger = os.path.join(RD, 'DGP9_LEDGER.jsonl')
    rates = a.rates or (os.path.join(RD, 'HEATBATH_RATES.json') if os.path.exists(os.path.join(RD, 'HEATBATH_RATES.json')) else None); rates_sha = sha(rates) if (rates and os.path.exists(rates)) else None
    assert all(arm in ARM_ARGS for arm in arms), 'unknown arm in %s (known: %s)' % (arms, sorted(ARM_ARGS))
    root = os.path.abspath(a.code_root); head = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD']).decode().strip(); tree = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD^{tree}']).decode().strip(); dirty = subprocess.check_output(['git', '-C', root, 'status', '--porcelain', '--untracked-files=no', '--', 'code/cex', 'code/gbidi']).decode().strip()
    if a.no_identity:
        if a.scope not in ('dgp9_dev', 'dgp9_screen'): raise SystemExit('--no-identity is a development option (scope dgp9_dev / dgp9_screen only)')
        frozen = None; amend = None; ref = None; schema = 'development (unfrozen; identity_ok = None)'; ident0 = identity(root, tolerate_missing=True)
    else:
        if dirty: raise SystemExit('the checkout is dirty: %s' % dirty[:200])
        frozen = json.load(open(a.freeze or os.path.join(RD, 'FREEZE.json'))); amend = json.load(open(a.amendment)) if a.amendment else None; ref, schema = R7.amendment_reference(amend, frozen); ident0 = identity(root)
        if head != ref['commit']: raise SystemExit('checkout %s is not the %s commit %s' % (head, schema, ref['commit']))
        bad = [f for f in ref['files'] if ident0.get(f) != ref['files'][f]]
        if bad: raise SystemExit('arm identity mismatch at launch: %s' % bad[:5])
    build_rec = None; hb_build = os.path.join(root, 'code', 'cex', 'hp', 'heatbath_build.json')
    import dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], RD, t.get('model_sha256'))
    if a.only: tasks = [t for t in tasks if t['name'] in a.only.split(',')]
    os.makedirs(os.path.join(RD, a.sub), exist_ok=True)
    for i, t in enumerate(tasks):
        msha = sha(t['model']); assert (not t.get('model_sha256')) or msha == t['model_sha256'], 'input hash mismatch for %s' % t['name']; evid = t['model'] + '.evid'; esha = sha(evid) if os.path.exists(evid) else None
        rot = R7.arm_rotation(msha, len(arms)); order = arms[rot:] + arms[:rot]
        if a.reverse: order = list(reversed(order))
        seed = sample_seed(msha, a.seed_index)
        for arm in order:
            tag = 'p' if a.seed_index == 0 else 's%d' % a.seed_index; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag))
            if a.skip_existing and os.path.exists(os.path.join(attempt, 'cell.json')): continue
            os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, seed, root, rates=rates); job = 'dgp9:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['ceiling']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--'] + ([CAFF] if CAFF and os.path.exists(CAFF) else []) + cmd
            subprocess.run(sup, cwd=SUP_CODE, env=env); rc = R7.last_receipt(ledger, job); ident_done = identity(root, tolerate_missing=bool(a.no_identity))
            if os.path.exists(hb_build): build_rec = {k: json.load(open(hb_build)).get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'flags')}
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), reverse=bool(a.reverse), seed=seed, seed_index=a.seed_index, seed_rule=FROZEN['seed_rule'], contract=a.contract, model=t['model'], model_sha256=t.get('model_sha256'), model_sha256_at_run=msha, evid_sha256=esha, panel=man.get('panel'), role=t.get('role'), family=t.get('family') or t.get('topology'), coupling=t.get('coupling'), n=t.get('n'), card=t.get('card'), archived_incumbent=t.get('archived_incumbent'), job=job, command=' '.join(cmd), code_commit=head, code_tree=tree,
                       identity_ok=(None if a.no_identity else (ident_done == ident0 and all(ident_done[f] == ref['files'][f] for f in ref['files']))), identity_reference=schema, dev_unfrozen=bool(a.no_identity), amendment=(os.path.basename(a.amendment) if a.amendment else None), rate_model_file=(dict(path=rates, sha256=rates_sha) if arm in HEATBATH_ARMS else None), heatbath_build=(build_rec if arm in HEATBATH_ARMS else None), supervisor_ceiling_s=c['ceiling'], diagnostic_arm=(arm in DIAGNOSTIC_ARMS), version='run_dgp9 v0.1')
            row.update(summarize(arm, out, rc, c)); row['digest'] = digest(arm, row); results.append(row)
            json.dump(dict(cell=row, identity_at_launch=ident0, identity_at_completion=ident_done, frozen_reference=schema), open(os.path.join(attempt, 'cell.json'), 'w'), indent=1, default=str)
            print(json.dumps(dict(task=t['name'], arm=arm, outcome=row.get('outcome'), published=row.get('published'), K=row.get('K'), receipt_wall_s=row.get('receipt_wall_s'), receipt_outcome=row.get('receipt_outcome'), complete=row.get('complete'), max_published_radius=row.get('max_published_radius'), identity_ok=row.get('identity_ok'), digest=row['digest']), default=str), flush=True)
    json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, code_root=root, code_commit=head, code_tree=tree, reverse=bool(a.reverse), seed_index=a.seed_index, only=a.only, rates=rates, rates_sha256=rates_sha, identity_reference=schema, dev_unfrozen=bool(a.no_identity), results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'SUMMARY_%s_seed%d%s.json' % (a.contract, a.seed_index, '_rev' if a.reverse else '')), 'w'), indent=1, default=str)


if __name__ == '__main__': main()
