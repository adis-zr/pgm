"""DGP10 supervised runner (derived from run_dgp9.py; FROZEN_EXPERIMENT_SPEC sections 4, 6, 8): every arm executes from a CLEAN DETACHED CHECKOUT at the frozen commit (--code-root), with the worker's cwd set to that checkout, source
identity checked at launch and at completion against FREEZE.json (or a recorded amendment), the input bound by sha256 at launch, one supervisor receipt per cell in the round ledger, and cell.json next to result.json. Arms:
INCUMBENT_R = the repaired engine without the heat-bath route (unified_pac_planner --lifted --envelope RMAX --global global; the DGP9 INCUMBENT arguments); HB_R = the repaired standalone heat-bath runner with DGP9's HB_REVISED policy
(--policy revised) and the ORIGINAL frozen DGP9 rate file (HEATBATH_RATES.json, exact bytes bound); RESPONSE = the same runner with the conditional-response observer and checked certificate (--response) planning from its OWN frozen
rate file (RESPONSE_RATES.json); RESPONSE_SCREEN = RESPONSE's witness + a development stream with the observer on (--dev-stream; diagnostic, never scored: the cost calibration). Sample seeds: the twelve EXPOSED inputs reuse DGP9's exact
rule and bytes `DGP9-SAMPLE|<model_sha256>|<k>`; the seven FRESH inputs use the frozen tag `DGP10-SAMPLE`; k = 0, 1; seed 1 runs the arms in REVERSED rotation order. usage: run_dgp10.py SUBDIR MANIFEST.json --code-root ROOT
--arms INCUMBENT_R,HB_R,RESPONSE --contract main|p4|p20 [--seed-index K] [--reverse] [--only a,b] [--scope S] [--records RD] [--freeze F] [--amendment F] [--hb-rates F] [--response-rates F] [--skip-existing] [--no-identity (dev only)]"""
import sys, os, json, time, subprocess, argparse, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_dgp7 as R7, run_dgp8 as R8, run_dgp9 as R9
RD_DEFAULT = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE'); SUP_CODE = os.environ.get('PGM_CODE', '/Users/adis/Workspace/pgm/code'); PY = os.environ.get('PY', os.path.join(SUP_CODE, '.venv/bin/python')); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
CONTRACTS = dict(R8.CONTRACTS)
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', contracts=CONTRACTS, seed_rule_exposed='DGP9-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1 (the DGP9 rule and bytes, verified against the archived DGP9 cells)', seed_rule_fresh='DGP10-SAMPLE|<model_sha256>|<k> -> first 8 SHA-256 bytes big-endian -> (x mod (2^31 - 1)) + 1', arm_rotation='int(model_sha256[:8], 16) mod len(arms); reversed under --reverse', dev_stream_s=2.0)
HEATBATH_FILES = list(R8.HEATBATH_FILES) + ['cex/hp/response_certificate.py', 'cex/hp/checked_tilt.py', 'cex/hp/reservation.py']; IDENTITY_FILES = list(R7.IDENTITY_FILES) + HEATBATH_FILES
HB_ARGS = ['--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
ARM_ARGS = {'INCUMBENT_R': ['--lifted', '--envelope', 'RMAX', '--global', 'global'], 'HB_R': list(HB_ARGS) + ['--policy', 'revised'], 'RESPONSE': list(HB_ARGS) + ['--policy', 'revised', '--response'], 'RESPONSE_SCREEN': list(HB_ARGS) + ['--policy', 'revised', '--response', '--dev-stream', str(FROZEN['dev_stream_s'])]}
PRODUCTION_ARMS = ('INCUMBENT_R', 'HB_R', 'RESPONSE'); DIAGNOSTIC_ARMS = ('RESPONSE_SCREEN',); HEATBATH_ARMS = ('HB_R', 'RESPONSE', 'RESPONSE_SCREEN'); RESPONSE_ARMS = ('RESPONSE', 'RESPONSE_SCREEN')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def identity(code_root, tolerate_missing=False):
    out = {}
    for f in IDENTITY_FILES:
        p = os.path.join(code_root, 'code', f)
        if os.path.exists(p): out[f] = sha(p)
        elif tolerate_missing: out[f] = None
        else: raise FileNotFoundError('identity file absent from the checkout: %s' % f)
    return out


def sample_seed(model_sha256, k, tag):
    x = int.from_bytes(hashlib.sha256(('%s|%s|%d' % (tag, model_sha256, k)).encode('utf-8')).digest()[:8], 'big'); return (x % ((1 << 31) - 1)) + 1


def cmd_of(arm, model, out, c, seed, root, hb_rates=None, response_rates=None):
    code = os.path.join(root, 'code')
    if arm in HEATBATH_ARMS:
        rates = response_rates if arm in RESPONSE_ARMS else hb_rates
        if arm in PRODUCTION_ARMS and not rates: raise SystemExit('the production heat-bath arms require their frozen rate model (%s)' % ('--response-rates' if arm in RESPONSE_ARMS else '--hb-rates'))
        return [PY, os.path.join(code, 'cex/hp/spectral_heatbath_run.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--seed', str(seed)] + ARM_ARGS[arm] + (['--rate-model', rates] if rates else [])
    return [PY, os.path.join(code, 'cex/hp/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)] + ARM_ARGS[arm]


def response_summary(d):
    m = d.get('mechanism') or {}; r = m.get('response') or {}; dg = d.get('diagnostics') or {}
    if not r: return None
    return dict(eta=r.get('eta_float'), executed=r.get('executed'), unavailable=r.get('unavailable'), observer_state=r.get('observer_state'), local_counts=r.get('local_counts'), n_groups=r.get('n_groups'), n_certified=r.get('n_certified'), checker_calls=r.get('checker_calls'), conflicts=len(r.get('conflicts') or []), variables_with_response=r.get('variables_with_response'), variables_raw_only=r.get('variables_raw_only'), radius=r.get('radius'), publication=r.get('publication'), tail_s=r.get('tail_s'), risks=r.get('risks'),
                groups=[dict(j=g.get('j'), k=g.get('k'), M=g.get('M'), sites=g.get('n_sites'), y_max=g.get('y_max'), U=(g.get('moment') or {}).get('U_float'), U_mode=(g.get('moment') or {}).get('mode'), alpha_moment=(g.get('moment') or {}).get('alpha'), R=(g.get('mean') or {}).get('R_float'), alpha_mean=(g.get('mean') or {}).get('alpha'), available=g.get('available'), reason=g.get('reason')) for g in (r.get('groups') or [])], unavailable_sites=len(r.get('unavailable_sites') or []), raw_full_delta_same_path=dg.get('raw_full_delta_same_path'))


def summarize(arm, out, rc, c):
    row = R9.summarize(arm if arm in ('INCUMBENT',) else ('HB_REVISED' if arm in HEATBATH_ARMS and arm not in DIAGNOSTIC_ARMS else ('HB_SCREEN' if arm in DIAGNOSTIC_ARMS else 'INCUMBENT')), out, rc, c)
    try:
        d = json.load(open(out))
        if arm in RESPONSE_ARMS: row['response'] = response_summary(d)
    except Exception as e: row['response_error'] = repr(e)[:200]
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False)) and arm not in DIAGNOSTIC_ARMS
    return row


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--code-root', required=True); ap.add_argument('--arms', default='INCUMBENT_R,HB_R,RESPONSE'); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--reverse', action='store_true'); ap.add_argument('--seed-index', type=int, default=0); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp10_main'); ap.add_argument('--records', default=RD_DEFAULT); ap.add_argument('--freeze', default=None); ap.add_argument('--amendment', default=None); ap.add_argument('--skip-existing', action='store_true')
    ap.add_argument('--hb-rates', default=None, help='the ORIGINAL frozen DGP9 rate file for HB_R (default <RD>/HEATBATH_RATES.json)'); ap.add_argument('--response-rates', default=None, help='the frozen RESPONSE rate file (default <RD>/RESPONSE_RATES.json when it exists; RESPONSE_SCREEN needs none)'); ap.add_argument('--no-identity', action='store_true', help='DEVELOPMENT ONLY (refused unless --scope dgp10_dev / dgp10_cost)'); a = ap.parse_args()
    RD = a.records; man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None); results = []; ledger = os.path.join(RD, 'DGP10_LEDGER.jsonl')
    hb_rates = a.hb_rates or (os.path.join(RD, 'HEATBATH_RATES.json') if os.path.exists(os.path.join(RD, 'HEATBATH_RATES.json')) else None); rr = a.response_rates or (os.path.join(RD, 'RESPONSE_RATES.json') if os.path.exists(os.path.join(RD, 'RESPONSE_RATES.json')) else None)
    hb_sha = sha(hb_rates) if (hb_rates and os.path.exists(hb_rates)) else None; rr_sha = sha(rr) if (rr and os.path.exists(rr)) else None
    assert all(arm in ARM_ARGS for arm in arms), 'unknown arm in %s (known: %s)' % (arms, sorted(ARM_ARGS))
    root = os.path.abspath(a.code_root); head = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD']).decode().strip(); tree = subprocess.check_output(['git', '-C', root, 'rev-parse', 'HEAD^{tree}']).decode().strip(); dirty = subprocess.check_output(['git', '-C', root, 'status', '--porcelain', '--untracked-files=no', '--', 'code/cex', 'code/gbidi']).decode().strip()
    if a.no_identity:
        if a.scope not in ('dgp10_dev', 'dgp10_cost'): raise SystemExit('--no-identity is a development option (scope dgp10_dev / dgp10_cost only)')
        frozen = None; amend = None; ref = None; schema = 'development (unfrozen; identity_ok = None)'; ident0 = identity(root, tolerate_missing=True)
    else:
        if dirty: raise SystemExit('the checkout is dirty: %s' % dirty[:200])
        frozen = json.load(open(a.freeze or os.path.join(RD, 'FREEZE.json'))); amend = json.load(open(a.amendment)) if a.amendment else None; ref, schema = R7.amendment_reference(amend, frozen); ident0 = identity(root)
        if head != ref['commit']: raise SystemExit('checkout %s is not the %s commit %s' % (head, schema, ref['commit']))
        bad = [f for f in ref['files'] if ident0.get(f) != ref['files'][f]]
        if bad: raise SystemExit('arm identity mismatch at launch: %s' % bad[:5])
        rmh = frozen.get('heatbath', {}).get('rate_model_hb'); rmr = frozen.get('heatbath', {}).get('rate_model_response')                    # (harness amendment 1: FREEZE.json records 'NOT YET' as a STRING for a rate file written after the freeze; only dict records carry a hash)
        if 'HB_R' in arms and isinstance(rmh, dict) and rmh.get('sha256') and hb_sha != rmh['sha256']: raise SystemExit('HB_R rate file does not match the frozen hash')
        if 'RESPONSE' in arms:
            if isinstance(rmr, dict) and rmr.get('sha256') and rr_sha != rmr['sha256']: raise SystemExit('RESPONSE rate file does not match the frozen hash')
            frz = os.path.join(RD, 'FREEZE_RATES.json')
            if not os.path.exists(frz) or json.load(open(frz)).get('response_rates_sha256') != rr_sha: raise SystemExit('RESPONSE rate file is not the one frozen in FREEZE_RATES.json')
    build_rec = None; hb_build = os.path.join(root, 'code', 'cex', 'hp', 'heatbath_build.json')
    import dgp_paths
    for t in tasks: t['model'] = dgp_paths.resolve_input(t['model'], RD, t.get('model_sha256'))
    if a.only: tasks = [t for t in tasks if t['name'] in a.only.split(',')]
    os.makedirs(os.path.join(RD, a.sub), exist_ok=True)
    for i, t in enumerate(tasks):
        msha = sha(t['model']); assert (not t.get('model_sha256')) or msha == t['model_sha256'], 'input hash mismatch for %s' % t['name']; evid = t['model'] + '.evid'; esha = sha(evid) if os.path.exists(evid) else None
        rot = R7.arm_rotation(msha, len(arms)); order = arms[rot:] + arms[:rot]
        if a.reverse: order = list(reversed(order))
        tag = t.get('seed_tag') or ('DGP10-SAMPLE' if man.get('panel') == 'fresh' else 'DGP9-SAMPLE'); seed = sample_seed(msha, a.seed_index, tag)
        if t.get('seeds') and str(a.seed_index) in t['seeds']: assert int(t['seeds'][str(a.seed_index)]) == seed, 'manifest-bound seed differs for %s' % t['name']
        for arm in order:
            stag = 'p' if a.seed_index == 0 else 's%d' % a.seed_index; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, stag))
            if a.skip_existing and os.path.exists(os.path.join(attempt, 'cell.json')): continue
            os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, seed, root, hb_rates=hb_rates, response_rates=rr); job = 'dgp10:%s:%s:%s:%s' % (a.sub, t['name'], arm, stag)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['ceiling']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--'] + ([CAFF] if CAFF and os.path.exists(CAFF) else []) + cmd
            subprocess.run(sup, cwd=SUP_CODE, env=env); rc = R7.last_receipt(ledger, job); ident_done = identity(root, tolerate_missing=bool(a.no_identity))
            if os.path.exists(hb_build): build_rec = {k: json.load(open(hb_build)).get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'flags')}
            rates_used = (rr if arm in RESPONSE_ARMS else hb_rates) if arm in HEATBATH_ARMS else None
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), reverse=bool(a.reverse), seed=seed, seed_index=a.seed_index, seed_tag=tag, seed_rule=(FROZEN['seed_rule_fresh'] if tag == 'DGP10-SAMPLE' else FROZEN['seed_rule_exposed']), contract=a.contract, model=t['model'], model_sha256=t.get('model_sha256'), model_sha256_at_run=msha, evid_sha256=esha, panel=man.get('panel'), role=t.get('role'), family=t.get('family') or t.get('topology'), coupling=t.get('coupling'), n=t.get('n'), card=t.get('card'), archived_incumbent=t.get('archived_incumbent'), archived_dgp9=t.get('archived_dgp9'), job=job, command=' '.join(cmd), code_commit=head, code_tree=tree,
                       identity_ok=(None if a.no_identity else (ident_done == ident0 and all(ident_done[f] == ref['files'][f] for f in ref['files']))), identity_reference=schema, dev_unfrozen=bool(a.no_identity), amendment=(os.path.basename(a.amendment) if a.amendment else None), rate_model_file=(dict(path=rates_used, sha256=(sha(rates_used) if rates_used and os.path.exists(rates_used) else None)) if arm in HEATBATH_ARMS else None), heatbath_build=(build_rec if arm in HEATBATH_ARMS else None), supervisor_ceiling_s=c['ceiling'], diagnostic_arm=(arm in DIAGNOSTIC_ARMS), version='run_dgp10 v0.1')
            row.update(summarize(arm, out, rc, c)); row['digest'] = R9.digest('HB_REVISED' if arm in HEATBATH_ARMS else 'INCUMBENT', row); results.append(row)
            if arm in RESPONSE_ARMS and row.get('response'): row['digest']['response'] = {k: (row['response'] or {}).get(k) for k in ('executed', 'unavailable', 'n_groups', 'n_certified', 'conflicts')} | dict(worst=((row['response'] or {}).get('radius') or {}).get('intersected_worst'), raw_worst=((row['response'] or {}).get('radius') or {}).get('raw_worst'))
            json.dump(dict(cell=row, identity_at_launch=ident0, identity_at_completion=ident_done, frozen_reference=schema), open(os.path.join(attempt, 'cell.json'), 'w'), indent=1, default=str)
            print(json.dumps(dict(task=t['name'], arm=arm, outcome=row.get('outcome'), published=row.get('published'), K=row.get('K'), receipt_wall_s=row.get('receipt_wall_s'), receipt_outcome=row.get('receipt_outcome'), complete=row.get('complete'), max_published_radius=row.get('max_published_radius'), identity_ok=row.get('identity_ok'), digest=row['digest']), default=str), flush=True)
    json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, code_root=root, code_commit=head, code_tree=tree, reverse=bool(a.reverse), seed_index=a.seed_index, only=a.only, hb_rates=hb_rates, hb_rates_sha256=hb_sha, response_rates=rr, response_rates_sha256=rr_sha, identity_reference=schema, dev_unfrozen=bool(a.no_identity), results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'SUMMARY_%s_seed%d%s.json' % (a.contract, a.seed_index, '_rev' if a.reverse else '')), 'w'), indent=1, default=str)


if __name__ == '__main__': main()
