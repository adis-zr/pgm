"""HARNESS LIFECYCLE / INTEGRITY CONTROLS (CQR-FL-01..05): the UNCHANGED runner is exercised against (i) a purpose-built, explicitly labelled STUB build (a worker / checker / oracle whose
behaviour is switched by environment variables: serialized FAULT, correct output then nonzero exit, hanging worker, checker crash on mutations, hanging checker, hanging oracle) and
(ii) controlled mutations of fixture inputs / cache records (task drift, forged cache identity, wrong cached answer). These are INJECTED harness controls, never natural solver behaviour,
and never a change to any candidate source. Each scenario states the EXPECTED typed outcome; the battery passes only when every observed outcome matches. Also runs the three built-in
harness controls (missing output, corrupted copy, cap exhaustion) against the REAL accepted baseline on the pinned manifest. Writes CONTROLS.json. Usage: controls.py --out DIR --baseline BUILD --manifest DIR"""
import os, sys, json, time, argparse, subprocess, shutil, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
STUB_WORKER = r'''import sys, os, json, argparse, time
p = argparse.ArgumentParser()
for k in ['input', 'output', 'arm', 'deadline', 'budget', 'seed', 'nonce']: p.add_argument('--' + k)
a = p.parse_args(); mode = os.environ.get('LIFECYCLE_WORKER', 'normal')
if mode == 'hang': time.sleep(120)
if mode == 'missing': raise SystemExit(0)
import hashlib
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
b = dict(model_sha256=sha(a.input), evidence_sha256=(sha(a.input + '.evid') if os.path.exists(a.input + '.evid') else hashlib.sha256(b'0').hexdigest()), query_sha256=(sha(a.input + '.query.json') if os.path.exists(a.input + '.query.json') else None))
w = {'status': 'COMPLETED', 'outcome': 'PUBLISHED', 'route': 'exact_reference', 'guarantee_type': 'DETERMINISTIC', 'worker_elapsed_s': 0.01, 'arm': a.arm, 'candidate_sources': {'cqr/stub.py': 'stub-identity-v1'}, 'binding': b,
     'answers': [{'query': 'P(X0=1)', 'lo': '3/4', 'hi': '3/4', 'point': '3/4', 'status': 'OK'}], 'certificate': {'publication': {'route': 'exact_reference', 'bounds': [['3/4', '3/4']], 'point': ['3/4'], 'guarantee': 'DETERMINISTIC'}}}
if mode == 'fault': w = {'status': 'STOPPED', 'outcome': 'FAULT', 'reason': 'INJECTED worker crash serialized as FAULT', 'worker_elapsed_s': 0.01, 'arm': a.arm, 'candidate_sources': {'cqr/stub.py': 'stub-identity-v1'}}
json.dump(w, open(a.output, 'w'))
if mode == 'nonzero': raise SystemExit(7)
'''
STUB_CHECKER = r'''import os, time, json
from fractions import Fraction as F
CHECKER_VERSION = 'lifecycle-stub-checker-v1'
def check_worker_output(mp, w, arm=None, deadline=None, manifest_task=None):
    mode = os.environ.get('LIFECYCLE_CHECKER', 'normal')
    if mode == 'hang': time.sleep(120)
    fails = []
    pt = F(w['answers'][0]['point'])
    if pt != F(3, 4): fails.append('published bounds do not contain the re-derived enclosure [3/4, 3/4]')
    if w.get('guarantee_type') != 'DETERMINISTIC': fails.append('publication guarantee %s differs from the class DETERMINISTIC of route exact_reference' % w.get('guarantee_type'))
    q = json.load(open(mp + '.query.json'))['queries'][0]
    if q.get('assign') == {'0': 0}: fails.append('worker binding differs from the files on disk')
    if fails and mode == 'fault_on_mutation': raise RuntimeError('INJECTED checker crash on a mutated copy')
    return fails, dict(attribution=dict(route='exact_reference'), commits=[], declines=[], bias=['0'])
'''
STUB_REGISTRY = "def cqr_source_inventory(build): return {'cqr/stub.py': 'stub-identity-v1'}\ndef full_inventory(build): return {'cqr/stub.py': 'stub-identity-v1'}\n"
STUB_KI = "def collect(build): return {}\ndef receipt_failures(frozen, w, arm, pac_arms=None): return []\ndef tags_needed_by(arm, pac_arms=None): return ()\n"
def stub_oracle(real_base): return "import os, sys, time, importlib.util\nspec = importlib.util.spec_from_file_location('real_oracle', %r); real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)\ndef enumerate_truth(*a, **k):\n    if os.environ.get('LIFECYCLE_ORACLE') == 'hang': time.sleep(120)\n    return real.enumerate_truth(*a, **k)\ndef eliminate_truth(*a, **k): return real.eliminate_truth(*a, **k)\n" % os.path.join(real_base, 'cex', 'cqr', 'oracle.py')
def build_stub(root, real_base):
    q = os.path.join(root, 'cex', 'cqr'); os.makedirs(q, exist_ok=True)
    for name, body in (('worker.py', STUB_WORKER), ('checker.py', STUB_CHECKER), ('registry.py', STUB_REGISTRY), ('kernel_identity.py', STUB_KI), ('oracle.py', stub_oracle(real_base))): open(os.path.join(q, name), 'w').write(body)
    for link, target in (('gbidi', os.path.join(real_base, 'gbidi')), ('cex/newarm', os.path.join(real_base, 'cex', 'newarm')), ('.venv', os.path.join(real_base, '.venv'))):
        lp = os.path.join(root, link)
        if not os.path.exists(lp): os.symlink(target, lp)
    shutil.copyfile(os.path.join(real_base, 'cex', 'cqr', 'task.py'), os.path.join(q, 'task.py')); open(os.path.join(q, '__init__.py'), 'w').write('')
    open(os.path.join(root, 'STUB_BUILD_README.txt'), 'w').write('LIFECYCLE STUB BUILD: a purpose-built fixture for harness controls; NOT a candidate; its worker / checker / oracle are switched by LIFECYCLE_* environment variables\n')
def stub_manifest(md, model_dir, required, budget=0.5):
    os.makedirs(model_dir, exist_ok=True); mp = os.path.join(model_dir, 'model.uai'); open(mp, 'w').write('MARKOV\n1\n2\n1\n1 0\n2\n1 3\n'); json.dump(dict(mode='DETERMINISTIC_EPS', epsilon='1/200', delta='0', queries=[dict(kind='joint', assign={'0': 1})]), open(mp + '.query.json', 'w'))
    sha = TR.sha_file; row = dict(id='FL_C35_mixed_alias', block='lifecycle_stub', budget_s=budget, candidate_arm='N1_CQR', comparator=None, expected_mechanism='lifecycle stub', spec='stub fixture', model=mp, model_sha256=sha(mp), evidence_sha256=None, query_sha256=sha(mp + '.query.json'), coverage_required=[])
    os.makedirs(md, exist_ok=True); json.dump(dict(schema='CQR_FASTLOOP_DEV_MANIFEST_V2', rows=[row], smoke_rows=[row['id']], allocations=dict(worker_nominal_s_cap=180), mutation_controls_required=required), open(os.path.join(md, 'DEV_MANIFEST.json'), 'w')); return mp
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--manifest', required=True); a = ap.parse_args()
    OUT = os.path.abspath(a.out); base = os.path.abspath(a.baseline); os.makedirs(OUT, exist_ok=True); stub = os.path.join(OUT, 'stub_build'); build_stub(stub, base); PY = os.path.join(base, '.venv', 'bin', 'python'); T0 = time.monotonic(); res = []
    REQ = ['answer_shifted_by_1_97', 'guarantee_relabelled', 'source_identity_emptied', 'label_swapped_to_other_denotation']
    def run(name, md, cap, env, expect, build=None, extra=()):
        rd = os.path.join(OUT, name); cmd = [PY, os.path.join(HERE, 'run.py'), '--manifest', md, '--candidate', build or stub, '--baseline', build or stub, '--out', rd, '--mode', 'full', '--total-cap', str(cap), '--label', 'CONTROL ' + name] + list(extra)
        t = time.monotonic()
        try: p = subprocess.run(cmd, capture_output=True, text=True, timeout=cap + 60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', **env)); rc = p.returncode; err = p.stderr[-400:]
        except subprocess.TimeoutExpired: rc = 'DRIVER_TIMEOUT'; err = 'the driver itself exceeded cap + 60 s'
        wall = time.monotonic() - t; rp = os.path.join(rd, 'ITERATION_REPORT.json'); rep = json.load(open(rp)) if os.path.exists(rp) else {}
        obs = dict(status=rep.get('status'), execution=rep.get('execution'), correctness=rep.get('correctness'), stop=(rep.get('stop_reason') or '')[:120], report_written=os.path.exists(rp), rc=rc, launch_wall_s=round(wall, 3), elapsed_reported_s=rep.get('elapsed_s'), within_cap=rep.get('within_cap'), controls=rep.get('required_controls'), cells=[(c.get('status'), c.get('outcome'), (c.get('check') or {}).get('status'), (c.get('truth') or {}).get('verdict'), (c.get('failure') or {}).get('kind')) for c in rep.get('cells', [])])
        ok = all((obs.get(k) == v) if not callable(v) else v(obs) for k, v in expect.items()); res.append(dict(name=name, expect={k: (v if not callable(v) else 'predicate') for k, v in expect.items()}, observed=obs, PASS=ok, stderr_tail=err)); print(json.dumps(dict(name=name, PASS=ok, status=obs['status'], execution=obs['execution'], stop=obs['stop'][:80], wall=obs['launch_wall_s'], within_cap=obs['within_cap'])), flush=True)
    md = os.path.join(OUT, 'stub_manifest'); mp = stub_manifest(md, os.path.join(OUT, 'stub_task'), REQ)
    TR.truth_for(mp, stub, os.path.join(md, 'truth_cache'), deadline_s=10)          # honest authenticated cache record (the stub oracle delegates to the real one)
    N = dict(LIFECYCLE_WORKER='normal', LIFECYCLE_CHECKER='normal', LIFECYCLE_ORACLE='normal')
    run('honest_stub', md, 60, N, dict(status='COMPLETE', execution='COMPLETE', correctness='OK', report_written=True))
    run('worker_fault_serialized', md, 60, dict(N, LIFECYCLE_WORKER='fault'), dict(status='STOP', correctness='FAILED', report_written=True, stop=lambda o: 'WORKER_FAULT' in o['stop']))
    run('nonzero_exit_after_correct_output', md, 60, dict(N, LIFECYCLE_WORKER='nonzero'), dict(status='STOP', correctness='FAILED', report_written=True, stop=lambda o: 'ABNORMAL_EXIT' in o['stop']))
    run('worker_missing_output', md, 60, dict(N, LIFECYCLE_WORKER='missing'), dict(status='INCOMPLETE', report_written=True, cells=lambda o: any(c[0] == 'NO_OUTPUT' for c in o['cells'])))
    run('worker_hang_hard_killed', md, 60, dict(N, LIFECYCLE_WORKER='hang'), dict(status='INCOMPLETE', report_written=True, cells=lambda o: any(c[0] == 'TIMEOUT_KILL' and c[1] == 'DEADLINE' for c in o['cells'])))
    run('checker_crash_on_mutations', md, 60, dict(N, LIFECYCLE_CHECKER='fault_on_mutation'), dict(status='INCOMPLETE', report_written=True, controls=lambda o: (o['controls'] or {}).get('failed') and set((o['controls'] or {}).get('failed')) >= {'answer_shifted_by_1_97', 'guarantee_relabelled'}))
    run('checker_hang_bounded', md, 30, dict(N, LIFECYCLE_CHECKER='hang'), dict(status='STOP', report_written=True, within_cap=True, stop=lambda o: 'VERIFIER_FAULT' in o['stop']))
    run('oracle_hang_cache_hit_never_runs', md, 40, dict(N, LIFECYCLE_ORACLE='hang'), dict(status='COMPLETE', report_written=True, within_cap=True, cells=lambda o: all(c[3] == 'CONTAINED' for c in o['cells'])))      # an authenticated cache HIT: the oracle is never invoked
    # oracle hang needs a cache MISS: a second manifest copy with a different query bytes (whitespace) so the digest differs
    md2 = os.path.join(OUT, 'stub_manifest_nocache'); mp2 = stub_manifest(md2, os.path.join(OUT, 'stub_task_nocache'), REQ); open(mp2 + '.query.json', 'a').write('\n'); m2 = json.load(open(os.path.join(md2, 'DEV_MANIFEST.json'))); m2['rows'][0]['query_sha256'] = TR.sha_file(mp2 + '.query.json'); json.dump(m2, open(os.path.join(md2, 'DEV_MANIFEST.json'), 'w'))
    run('oracle_hang_bounded_cache_miss', md2, 40, dict(N, LIFECYCLE_ORACLE='hang'), dict(report_written=True, within_cap=True, cells=lambda o: any(c[3] == 'UNRESOLVED' for c in o['cells'])))
    run('skipped_controls_tight_cap', md, 14, N, dict(status='INCOMPLETE', report_written=True, controls=lambda o: bool((o['controls'] or {}).get('missing'))))
    # task drift: pinned manifest, model edited afterwards
    md3 = os.path.join(OUT, 'stub_manifest_drift'); mp3 = stub_manifest(md3, os.path.join(OUT, 'stub_task_drift'), REQ); open(mp3, 'w').write('MARKOV\n1\n2\n1\n1 0\n2\n1 1\n')
    run('task_drift_model_changed', md3, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'TASK_INTEGRITY' in o['stop'], cells=lambda o: len(o['cells']) == 1 and o['cells'][0][0] == 'NOT_RUN'))
    # forged cache identity and wrong cached answer
    md4 = os.path.join(OUT, 'stub_manifest_cache'); mp4 = stub_manifest(md4, os.path.join(OUT, 'stub_task_cache'), REQ); rec = TR.truth_for(mp4, stub, os.path.join(md4, 'truth_cache'), deadline_s=10); cp = os.path.join(md4, 'truth_cache', rec['digest'] + '.json')
    hon = json.load(open(cp)); shutil.copyfile(cp, cp + '.honest'); forged = dict(hon); forged['oracle'] = dict(hon['oracle'], sha256='0' * 64); json.dump(forged, open(cp, 'w'))
    run('forged_cache_oracle_identity', md4, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'HARNESS_INTEGRITY' in o['stop']))
    wrong = dict(hon); wrong['answers'] = ['1/2']; json.dump(wrong, open(cp, 'w'))
    run('wrong_cached_answer_unsealed', md4, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'HARNESS_INTEGRITY' in o['stop']))
    shutil.copyfile(cp + '.honest', cp)
    # built-in harness controls on the REAL accepted baseline and the real pinned manifest (smoke subset)
    for name, extra, exp in (('real_missing_output', ['--inject-missing-output', 'FL_SENT_ASIA', '--mode', 'smoke'], dict(status='INCOMPLETE', report_written=True)), ('real_corrupted_copy', ['--inject-corrupt', 'FL_C35_mixed_alias', '--mode', 'smoke'], dict(status='STOP', report_written=True, stop=lambda o: 'CANDIDATE_CORRECTNESS' in o['stop'] or 'IDENTITY' in o['stop'])), ('real_cap_exhaustion_40s', ['--mode', 'full'], dict(status='INCOMPLETE', report_written=True, within_cap=True))):
        cap = 40 if 'cap' in name else 120
        rd = os.path.join(OUT, name); cmd = [PY, os.path.join(HERE, 'run.py'), '--manifest', a.manifest, '--candidate', base, '--baseline', base, '--out', rd, '--total-cap', str(cap), '--label', 'CONTROL ' + name] + extra
        t = time.monotonic(); p = subprocess.run(cmd, capture_output=True, text=True, timeout=cap + 60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1')); wall = time.monotonic() - t; rp = os.path.join(rd, 'ITERATION_REPORT.json'); rep = json.load(open(rp)) if os.path.exists(rp) else {}
        obs = dict(status=rep.get('status'), execution=rep.get('execution'), stop=(rep.get('stop_reason') or '')[:120], report_written=os.path.exists(rp), rc=p.returncode, launch_wall_s=round(wall, 3), elapsed_reported_s=rep.get('elapsed_s'), within_cap=rep.get('within_cap'), not_run=len(rep.get('not_run') or []), no_output=rep.get('no_output'))
        ok = all((obs.get(k) == v) if not callable(v) else v(obs) for k, v in exp.items()); res.append(dict(name=name, expect={k: (v if not callable(v) else 'predicate') for k, v in exp.items()}, observed=obs, PASS=ok, note='REAL accepted baseline; injected at the harness boundary')); print(json.dumps(dict(name=name, PASS=ok, status=obs['status'], stop=obs['stop'][:80], wall=obs['launch_wall_s'], within_cap=obs['within_cap'])), flush=True)
    out = dict(schema='CQR_FASTLOOP_CONTROLS_V1', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), elapsed_s=round(time.monotonic() - T0, 3), all_pass=all(r['PASS'] for r in res), scenarios=res, note='every scenario is an INJECTED harness control (stub build or boundary injection), never a natural candidate failure; the stub build is labelled and lives under this directory only')
    json.dump(out, open(os.path.join(OUT, 'CONTROLS.json'), 'w'), indent=1); print(json.dumps(dict(all_pass=out['all_pass'], elapsed_s=out['elapsed_s'], failed=[r['name'] for r in res if not r['PASS']])))
    # cleanup check: no stub / harness process alive
    alive = subprocess.run(['pgrep', '-fl', 'stub_build|cex/fastloop/run.py'], capture_output=True, text=True).stdout.strip(); print('processes alive after the battery:', alive or 'none')
if __name__ == '__main__': main()
