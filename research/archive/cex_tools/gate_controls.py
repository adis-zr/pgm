"""Negative controls of the experimental-integrity gates (follow-up review §4 / §5), run by the qualification job; every control must be REJECTED.
  gate v3: missing five cases / duplicate receipt / contradictory source manifest / extra case / wrong budget -> nonzero exit with the failure listed;
  locked_plan v3: existing attempt directory refused; a child that exits 7 before writing while stale COMPLETED files exist -> no arm accepted, no containment.
    python cex/gate_controls.py <RD> <code_dir> <out_json>   (exit 0 iff every control is rejected)"""
import sys, os, json, subprocess, shutil, pathlib, importlib.util, io, contextlib
RD, CODE, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]; sys.set_int_max_str_digits(0)
W = pathlib.Path(RD) / 'qualification' / 'gate_controls_v3'; shutil.rmtree(W, ignore_errors=True); W.mkdir(parents=True)
SPEC_B = os.path.join(RD, 'campaign_specs', 'baseline_20s_all46.json'); SPEC_N = os.path.join(RD, 'campaign_specs', 'newarm_20s_all46_v13.json'); res = []
drop = {'1aie', '1npl', '1qt9', 'BN_12', 'BN_13'}
for test in ('missing_five_cases', 'duplicate_receipt', 'contradictory_source_manifest', 'extra_case', 'wrong_budget', 'untouched_saved_campaigns'):
    d = W / test; d.mkdir()
    for arm, src in (('baseline', 'baseline_20s_all46'), ('new', 'newarm_20s_all46_v13')):
        p = d / arm; p.mkdir(); source = pathlib.Path(RD) / 'campaigns' / src; rr = json.loads((source / 'receipts.json').read_text()); env = json.loads((source / 'environment.json').read_text())
        if test == 'missing_five_cases': rr = [x for x in rr if x['case'] not in drop]
        elif test == 'duplicate_receipt': rr.append(dict(rr[0]))
        elif test == 'contradictory_source_manifest': env['source_hashes_before']['core.py'] = '0' * 64
        elif test == 'extra_case': rr.append(dict(rr[0], case='NOT_AN_INPUT'))
        elif test == 'wrong_budget': rr[0] = dict(rr[0], budget_s=25.0)
        (p / 'receipts.json').write_text(json.dumps(rr)); (p / 'environment.json').write_text(json.dumps(env))
        for x in rr:
            f = p / (x['case'] + '.json'); sf = source / (x['case'] + '.json')
            if sf.exists() and not f.exists(): f.symlink_to(sf)
    run = subprocess.run([sys.executable, os.path.join(CODE, 'cex', 'compare_campaigns.py'), str(d / 'baseline'), str(d / 'new'), str(d / 'result.json'), SPEC_B, SPEC_N], capture_output=True, text=True)
    j = json.loads((d / 'result.json').read_text()) if (d / 'result.json').exists() else {}; S = j.get('summary', {}); expect_reject = test != 'untouched_saved_campaigns'
    ok = (run.returncode != 0 and S.get('gate_passed') is False and bool(S.get('gate_failures'))) if expect_reject else (run.returncode == 0 and S.get('gate_passed') is True)
    res.append(dict(control='gate_v3:' + test, expect='REJECTED' if expect_reject else 'ACCEPTED', returncode=run.returncode, gate_passed=S.get('gate_passed'), failures=(S.get('gate_failures') or [])[:4], ok=ok))
# ---- locked_plan v3: stale output after child failure; existing directory refused
L = W / 'locked_stale'; L.mkdir(); I = L / 'inputs'; I.mkdir(); (I / 'Synthetic.uai').write_text('MARKOV\n3\n2 2 2\n1\n3 0 1 2\n8\n1 2 3 4 5 6 7 8\n')
spec = importlib.util.spec_from_file_location('locked_v3', os.path.join(CODE, 'cex', 'locked_plan.py')); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); mod.P = str(I)
attempt = L / 'attempt'; points = [['5/18', '13/18'], ['7/18', '11/18'], ['4/9', '5/9']]
# (a) an existing attempt directory with stale COMPLETED arm files is refused outright
attempt.mkdir()
for arm in ('new', 'baseline'): (attempt / ('Synthetic.%s.json' % arm)).write_text(json.dumps({'arm': arm, 'status': 'COMPLETED', 'components': [{'component': 0, 'variables': 3, 'status': 'CERTIFIED', 'points': points, 'intervals': [[[q, q] for q in row] for row in points]}]}))
argv0 = sys.argv; sys.argv = ['locked_plan.py', 'Synthetic', str(attempt), '1', '100000000', 'new,baseline']; refused = False
try:
    with contextlib.redirect_stdout(io.StringIO()): mod.main()
except SystemExit as e: refused = 'refuse' in str(e)
res.append(dict(control='locked_v3:existing_attempt_directory_refused', expect='REJECTED', ok=refused))
# (b) fresh directory, child exits 7 before writing: no arm accepted, no containment claim
mod.CHILD = 'import sys; sys.exit(7)\n'; fresh = L / 'attempt_fresh'; sys.argv = ['locked_plan.py', 'Synthetic', str(fresh), '1', '100000000', 'new,baseline']
with contextlib.redirect_stdout(io.StringIO()): mod.main()
sys.argv = argv0; j = json.loads((fresh / 'Synthetic.json').read_text()); arms = {a: (v.get('status'), v.get('returncode'), v.get('rejection_reasons')) for a, v in j['executors'].items()}
ok = all(st != 'COMPLETED' and rc == 7 for st, rc, _ in arms.values()) and j.get('new_encloses_exact_reference') is None
res.append(dict(control='locked_v3:child_exit_7_no_stale_acceptance', expect='REJECTED', arms=arms, containment=j.get('new_encloses_exact_reference'), ok=ok))
# (c) fresh directory, a child that writes a COMPLETED output with a FOREIGN nonce and exits 0 -> rejected (stale / foreign output)
mod.CHILD = "import sys, json; json.dump({'arm': sys.argv[1], 'nonce': 'deadbeef', 'plan_sha256': 'x', 'status': 'COMPLETED', 'wall_s': 0.01, 'peak_rss_bytes_this_process': 1, 'components': []}, open(sys.argv[3], 'w'))\n"
fresh2 = L / 'attempt_fresh2'; sys.argv = ['locked_plan.py', 'Synthetic', str(fresh2), '1', '100000000', 'new,baseline']
with contextlib.redirect_stdout(io.StringIO()): mod.main()
sys.argv = argv0; j = json.loads((fresh2 / 'Synthetic.json').read_text()); arms = {a: (v.get('status'), v.get('rejection_reasons')) for a, v in j['executors'].items()}
ok = all(st == 'REJECTED' for st, _ in arms.values()) and j.get('new_encloses_exact_reference') is None
res.append(dict(control='locked_v3:foreign_nonce_output_rejected', expect='REJECTED', arms=arms, ok=ok))
json.dump(res, open(OUT, 'w'), indent=1, default=str); allok = all(r['ok'] for r in res); print(json.dumps([(r['control'], r['ok']) for r in res])); sys.exit(0 if allok else 1)
