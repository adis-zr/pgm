"""HARNESS LIFECYCLE / INTEGRITY CONTROLS v3 (CQR-FL-01..05; repair-2 review CQR-AF2-03..06): the UNCHANGED runner is exercised against (i) a purpose-built, explicitly labelled STUB build
(worker / checker / oracle switched by environment variables) and (ii) controlled mutations of fixture inputs / cache records / output directories. These are INJECTED harness controls,
never natural solver behaviour, never a change to any candidate source. EVERY acceptance-boundary scenario is PAIRED with an honest control on the same fixture. Each scenario states the
EXPECTED typed outcome; the battery passes only when every observed outcome matches. Also runs the three built-in harness controls (missing output, corrupted copy, cap exhaustion) against
the REAL accepted baseline on the pinned manifest. Writes CONTROLS.json. Usage: controls.py --out DIR --baseline BUILD --manifest DIR"""
import os, sys, json, time, argparse, subprocess, shutil, hashlib
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
STUB_WORKER = r'''import sys, os, json, argparse, time, hashlib
p = argparse.ArgumentParser()
for k in ['input', 'output', 'arm', 'deadline', 'budget', 'seed', 'nonce']: p.add_argument('--' + k)
a = p.parse_args(); mode = os.environ.get('LIFECYCLE_WORKER', 'normal'); only = os.environ.get('LIFECYCLE_WORKER_ONLY_FOR')
if only and not a.nonce.startswith(only + '-'): mode = 'normal'
if mode == 'hang': time.sleep(120)
if mode == 'missing': raise SystemExit(0)
if mode == 'empty': json.dump({}, open(a.output, 'w')); raise SystemExit(0)
if mode == 'unknown_outcome': json.dump({'status': 'COMPLETED', 'outcome': 'MYSTERY', 'arm': a.arm}, open(a.output, 'w')); raise SystemExit(0)
HERE = os.path.dirname(os.path.abspath(__file__)); BUILD = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, HERE); import registry
if mode == 'inject_evidence': open(a.input + '.evid', 'w').write('1 0 0\n')                       # INJECTED: evidence appears in the snapshot AFTER the runner verified it (runtime boundary)
if mode == 'edit_original' and os.environ.get('LIFECYCLE_ORIGINAL'): open(os.environ['LIFECYCLE_ORIGINAL'], 'a').write('\n')      # POSITIVE CONTROL: the ORIGINAL changes after the snapshot; the snapshot is unaffected
if mode == 'drift': open(os.path.join(HERE, 'checker.py'), 'a').write('\n# INJECTED comment: build changed after the pinned identity\n')     # INJECTED mid-run source drift (answer unchanged)
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
b = dict(model_sha256=sha(a.input), evidence_sha256=(sha(a.input + '.evid') if os.path.exists(a.input + '.evid') else hashlib.sha256(b'0').hexdigest()), query_sha256=(sha(a.input + '.query.json') if os.path.exists(a.input + '.query.json') else None))
ans = '3/4' if not os.path.exists(a.input + '.evid') else '0'
w = {'status': 'COMPLETED', 'outcome': 'PUBLISHED', 'route': 'exact_reference', 'guarantee_type': 'DETERMINISTIC', 'worker_elapsed_s': 0.01, 'arm': a.arm, 'candidate_sources': registry.cqr_source_inventory(BUILD), 'binding': b,
     'answers': [{'query': 'P(X0=1)', 'lo': ans, 'hi': ans, 'point': ans, 'status': 'OK'}], 'certificate': {'publication': {'route': 'exact_reference', 'bounds': [[ans, ans]], 'point': [ans], 'guarantee': 'DETERMINISTIC'}}}
if mode == 'fault': w = {'status': 'STOPPED', 'outcome': 'FAULT', 'reason': 'INJECTED worker crash serialized as FAULT', 'worker_elapsed_s': 0.01, 'arm': a.arm, 'candidate_sources': registry.cqr_source_inventory(BUILD)}
json.dump(w, open(a.output, 'w'))
if mode == 'nonzero': raise SystemExit(7)
'''
STUB_CHECKER = r'''import os, time, json
from fractions import Fraction as F
CHECKER_VERSION = 'lifecycle-stub-checker-v1'
if os.environ.get('LIFECYCLE_CHECKER') == 'exit7':
    import atexit; atexit.register(lambda: os._exit(7))                      # INJECTED: a complete record is written, then the verifier PROCESS exits abnormally
def check_worker_output(mp, w, arm=None, deadline=None, manifest_task=None):
    mode = os.environ.get('LIFECYCLE_CHECKER', 'normal')
    if mode == 'hang': time.sleep(120)
    fails = []
    pt = F(w['answers'][0]['point'])
    want = F(3, 4) if not os.path.exists(mp + '.evid') else F(0)
    if pt != want: fails.append('published bounds do not contain the re-derived enclosure [%s, %s]' % (want, want))
    if w.get('guarantee_type') != 'DETERMINISTIC': fails.append('publication guarantee %s differs from the class DETERMINISTIC of route exact_reference' % w.get('guarantee_type'))
    q = json.load(open(mp + '.query.json'))['queries'][0]
    if q.get('assign') == {'0': 0}: fails.append('worker binding differs from the files on disk')
    if fails and mode == 'fault_on_mutation': raise RuntimeError('INJECTED checker crash on a mutated copy')
    return fails, dict(attribution=dict(route='exact_reference'), commits=[], declines=[], bias=['0'])
'''
STUB_REGISTRY = r'''import os, hashlib
SOURCE_SCOPES = {'cqr_candidate': ('cex/cqr',)}
def cqr_source_inventory(build): return {'cqr/' + f: hashlib.sha256(open(os.path.join(build, 'cex', 'cqr', f), 'rb').read()).hexdigest() for f in sorted(os.listdir(os.path.join(build, 'cex', 'cqr'))) if f.endswith('.py')}
def full_inventory(build): return cqr_source_inventory(build)
'''
STUB_KI = "def collect(build): return {}\ndef receipt_failures(frozen, w, arm, pac_arms=None): return []\ndef tags_needed_by(arm, pac_arms=None): return ()\n"
def stub_oracle(real_base): return "import os, sys, time, importlib.util\nspec = importlib.util.spec_from_file_location('real_oracle', %r); real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)\nif os.environ.get('LIFECYCLE_ORACLE') == 'exit7':\n    import atexit; atexit.register(lambda: os._exit(7))       # INJECTED: the oracle child prints its result, then exits abnormally\ndef enumerate_truth(*a, **k):\n    if os.environ.get('LIFECYCLE_ORACLE') == 'hang': time.sleep(120)\n    return real.enumerate_truth(*a, **k)\ndef eliminate_truth(*a, **k): return real.eliminate_truth(*a, **k)\n" % os.path.join(real_base, 'cex', 'cqr', 'oracle.py')
def build_stub(root, real_base):
    q = os.path.join(root, 'cex', 'cqr'); os.makedirs(q, exist_ok=True)
    for name, body in (('worker.py', STUB_WORKER), ('checker.py', STUB_CHECKER), ('registry.py', STUB_REGISTRY), ('kernel_identity.py', STUB_KI), ('oracle.py', stub_oracle(real_base))): open(os.path.join(q, name), 'w').write(body)
    for link, target in (('gbidi', os.path.join(real_base, 'gbidi')), ('cex/newarm', os.path.join(real_base, 'cex', 'newarm')), ('.venv', os.path.join(real_base, '.venv'))):
        lp = os.path.join(root, link)
        if not os.path.exists(lp): os.symlink(target, lp)
    shutil.copyfile(os.path.join(real_base, 'cex', 'cqr', 'task.py'), os.path.join(q, 'task.py')); open(os.path.join(q, '__init__.py'), 'w').write('')
    open(os.path.join(root, 'STUB_BUILD_README.txt'), 'w').write('LIFECYCLE STUB BUILD: a purpose-built fixture for harness controls; NOT a candidate; its worker / checker / oracle are switched by LIFECYCLE_* environment variables\n')
def stub_manifest(md, model_dir, required, budget=0.5, rows=1):
    os.makedirs(model_dir, exist_ok=True); sha = TR.sha_file; R = []
    for i in range(rows):
        mp = os.path.join(model_dir, 'model%d.uai' % i if i else 'model.uai'); open(mp, 'w').write('MARKOV\n1\n2\n1\n1 0\n2\n1 3\n'); json.dump(dict(mode='DETERMINISTIC_EPS', epsilon='1/200', delta='0', queries=[dict(kind='joint', assign={'0': 1})]), open(mp + '.query.json', 'w'))
        R.append(dict(id=('FL_C35_mixed_alias' if i == 0 else 'FL_SECOND_%d' % i), block='lifecycle_stub', budget_s=budget, candidate_arm='N1_CQR', comparator=None, expected_mechanism='lifecycle stub', spec='stub fixture', model=mp, model_sha256=sha(mp), evidence_sha256=None, query_sha256=sha(mp + '.query.json'), coverage_required=[]))
    os.makedirs(md, exist_ok=True); json.dump(dict(schema='CQR_FASTLOOP_DEV_MANIFEST_V2', rows=R, smoke_rows=[r['id'] for r in R], allocations=dict(worker_nominal_s_cap=180), mutation_controls_required=required), open(os.path.join(md, 'DEV_MANIFEST.json'), 'w')); return R[0]['model']
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--manifest', required=True); a = ap.parse_args()
    OUT = os.path.abspath(a.out); base = os.path.abspath(a.baseline); os.makedirs(OUT, exist_ok=True); stub = os.path.join(OUT, 'stub_build'); build_stub(stub, base); PY = os.path.join(base, '.venv', 'bin', 'python'); T0 = time.monotonic(); res = []
    REQ = ['answer_shifted_by_1_97', 'guarantee_relabelled', 'source_identity_emptied', 'label_swapped_to_other_denotation']
    def run(name, md, cap, env, expect, build=None, extra=(), pair=None, cls='INJECTED STUB LIFECYCLE', pre=None):
        rd = os.path.join(OUT, name); cmd = [PY, os.path.join(HERE, 'run.py'), '--manifest', md, '--candidate', build or stub, '--baseline', build or stub, '--out', rd, '--mode', 'full', '--total-cap', str(cap), '--label', 'CONTROL ' + name] + list(extra)
        if pre: pre(rd)
        t = time.monotonic()
        try: p = subprocess.run(cmd, capture_output=True, text=True, timeout=cap + 60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', **env)); rc = p.returncode; err = p.stderr[-400:]
        except subprocess.TimeoutExpired: rc = 'DRIVER_TIMEOUT'; err = 'the driver itself exceeded cap + 60 s'
        wall = time.monotonic() - t; rp = os.path.join(rd, 'ITERATION_REPORT.json'); rep = json.load(open(rp)) if os.path.exists(rp) else {}
        obs = dict(status=rep.get('status'), execution=rep.get('execution'), correctness=rep.get('correctness'), stop=(rep.get('stop_reason') or '')[:160], report_written=os.path.exists(rp), rc=rc, launch_wall_s=round(wall, 3), elapsed_reported_s=rep.get('elapsed_s'), within_cap=rep.get('within_cap'), controls=rep.get('required_controls'), drift=rep.get('drift_checks'), oracle_faults=rep.get('oracle_faults'),
                   cells=[(c.get('status'), c.get('outcome'), (c.get('check') or {}).get('status'), (c.get('truth') or {}).get('verdict'), (c.get('failure') or {}).get('kind'), ((c.get('answers') or [{}])[0] or {}).get('point')) for c in rep.get('cells', [])], stderr_tail=err)
        ok = all((obs.get(k) == v) if not callable(v) else v(obs) for k, v in expect.items()); res.append(dict(name=name, classification=cls, paired_honest_control=pair, expect={k: (v if not callable(v) else 'predicate') for k, v in expect.items()}, observed=obs, PASS=ok)); print(json.dumps(dict(name=name, PASS=ok, status=obs['status'], execution=obs['execution'], correctness=obs['correctness'], stop=obs['stop'][:90], wall=obs['launch_wall_s'], within_cap=obs['within_cap'])), flush=True)
        return obs
    md = os.path.join(OUT, 'stub_manifest'); mp = stub_manifest(md, os.path.join(OUT, 'stub_task'), REQ)
    TR.truth_for(mp, stub, os.path.join(md, 'truth_cache'), deadline_s=10)          # honest authenticated cache record (the stub oracle delegates to the real one)
    N = dict(LIFECYCLE_WORKER='normal', LIFECYCLE_CHECKER='normal', LIFECYCLE_ORACLE='normal')
    COMPLETE_3_4 = dict(status='COMPLETE', execution='COMPLETE', correctness='OK', report_written=True, cells=lambda o: all(c[5] == '3/4' for c in o['cells']))
    run('honest_stub', md, 60, N, COMPLETE_3_4, cls='HONEST CONTROL')
    run('worker_fault_serialized', md, 60, dict(N, LIFECYCLE_WORKER='fault'), dict(status='STOP', correctness='FAILED', report_written=True, stop=lambda o: 'WORKER_FAULT' in o['stop']), pair='honest_stub')
    run('nonzero_exit_after_correct_output', md, 60, dict(N, LIFECYCLE_WORKER='nonzero'), dict(status='STOP', correctness='FAILED', report_written=True, stop=lambda o: 'ABNORMAL_EXIT' in o['stop']), pair='honest_stub')
    run('worker_missing_output', md, 60, dict(N, LIFECYCLE_WORKER='missing'), dict(status='INCOMPLETE', report_written=True, cells=lambda o: any(c[0] == 'NO_OUTPUT' for c in o['cells'])), pair='honest_stub')
    run('worker_hang_hard_killed', md, 60, dict(N, LIFECYCLE_WORKER='hang'), dict(status='INCOMPLETE', report_written=True, cells=lambda o: any(c[0] == 'TIMEOUT_KILL' and c[1] == 'DEADLINE' for c in o['cells'])), pair='honest_stub')
    run('checker_crash_on_mutations', md, 60, dict(N, LIFECYCLE_CHECKER='fault_on_mutation'), dict(status='INCOMPLETE', report_written=True, controls=lambda o: (o['controls'] or {}).get('failed') and set((o['controls'] or {}).get('failed')) >= {'answer_shifted_by_1_97', 'guarantee_relabelled'}), pair='honest_stub')
    run('checker_hang_bounded', md, 30, dict(N, LIFECYCLE_CHECKER='hang'), dict(status='STOP', report_written=True, within_cap=True, stop=lambda o: 'VERIFIER_FAULT' in o['stop']), pair='honest_stub')
    run('oracle_hang_cache_hit_never_runs', md, 40, dict(N, LIFECYCLE_ORACLE='hang'), dict(status='COMPLETE', report_written=True, within_cap=True, cells=lambda o: all(c[3] == 'CONTAINED' for c in o['cells'])), pair='honest_stub')      # an authenticated cache HIT: the oracle is never invoked
    # ---- AF2-05: a VALID JSON {} / an unknown outcome from the SECOND worker of a two-row honest panel (the first row keeps the required controls alive)
    md2r = os.path.join(OUT, 'stub_manifest_two_rows'); stub_manifest(md2r, os.path.join(OUT, 'stub_task_two_rows'), REQ, rows=2)
    for r_ in json.load(open(os.path.join(md2r, 'DEV_MANIFEST.json')))['rows']: TR.truth_for(r_['model'], stub, os.path.join(md2r, 'truth_cache'), deadline_s=10)
    run('two_rows_honest', md2r, 60, N, dict(COMPLETE_3_4, cells=lambda o: len(o['cells']) == 2 and all(c[5] == '3/4' and c[2] == 'ACCEPTED' for c in o['cells'])), cls='HONEST CONTROL')
    run('second_worker_writes_empty_json', md2r, 60, dict(N, LIFECYCLE_WORKER='empty', LIFECYCLE_WORKER_ONLY_FOR='FL_SECOND_1'), dict(status='STOP', report_written=True, stop=lambda o: 'WORKER_PROTOCOL' in o['stop'], cells=lambda o: any(c[1] == 'WORKER_PROTOCOL' for c in o['cells'])), pair='two_rows_honest')
    run('second_worker_unknown_outcome', md2r, 60, dict(N, LIFECYCLE_WORKER='unknown_outcome', LIFECYCLE_WORKER_ONLY_FOR='FL_SECOND_1'), dict(status='STOP', report_written=True, stop=lambda o: 'WORKER_PROTOCOL' in o['stop']), pair='two_rows_honest')
    # ---- AF2-05: a complete checker record followed by exit 7 -> VERIFIER_FAULT (the record is discarded; no positive accepted; no negative control passes)
    run('checker_record_then_exit7', md2r, 60, dict(N, LIFECYCLE_CHECKER='exit7'), dict(status='STOP', report_written=True, stop=lambda o: 'VERIFIER_FAULT' in o['stop'], cells=lambda o: not any(c[2] == 'ACCEPTED' for c in o['cells']), controls=lambda o: not (o['controls'] or {}).get('passed')), pair='two_rows_honest')
    # ---- AF2-05: oracle result then exit 7 on a cache MISS -> ORACLE_FAULT, nothing cached, INCOMPLETE
    md2 = os.path.join(OUT, 'stub_manifest_nocache'); mp2 = stub_manifest(md2, os.path.join(OUT, 'stub_task_nocache'), REQ); open(mp2 + '.query.json', 'a').write('\n'); m2 = json.load(open(os.path.join(md2, 'DEV_MANIFEST.json'))); m2['rows'][0]['query_sha256'] = TR.sha_file(mp2 + '.query.json'); json.dump(m2, open(os.path.join(md2, 'DEV_MANIFEST.json'), 'w'))
    run('oracle_hang_bounded_cache_miss', md2, 40, dict(N, LIFECYCLE_ORACLE='hang'), dict(report_written=True, within_cap=True, cells=lambda o: any(c[3] == 'UNRESOLVED' for c in o['cells'])), pair='honest_stub')
    o = run('oracle_result_then_exit7_cache_miss', md2, 40, dict(N, LIFECYCLE_ORACLE='exit7'), dict(status='INCOMPLETE', report_written=True, within_cap=True, cells=lambda o: any(c[3] == 'ORACLE_FAULT' for c in o['cells']), oracle_faults=lambda o: bool(o['oracle_faults'])), pair='honest_stub')
    res[-1]['cache_records_after'] = sorted(f for f in os.listdir(os.path.join(md2, 'truth_cache')) if f.endswith('.json')) if os.path.isdir(os.path.join(md2, 'truth_cache')) else []; res[-1]['PASS'] = res[-1]['PASS'] and not res[-1]['cache_records_after']; print('  cache records after the faulting oracle:', res[-1]['cache_records_after'] or 'none')
    run('skipped_controls_tight_cap', md, 14, N, dict(status='INCOMPLETE', report_written=True, within_cap=True, controls=lambda o: bool((o['controls'] or {}).get('missing'))), pair='honest_stub')
    # ---- AF2-06: slow identity calls (a `git` on PATH that sleeps 3 s) under a 14 s cap: the ONE absolute deadline bounds every call; the report is durable and within the cap
    fake = os.path.join(OUT, 'slow_git'); os.makedirs(fake, exist_ok=True); open(os.path.join(fake, 'git'), 'w').write('#!%s\nimport time\ntime.sleep(3)\n' % PY); os.chmod(os.path.join(fake, 'git'), 0o755)
    run('identity_git_slow_within_cap', md, 14, dict(N, PATH=fake + os.pathsep + os.environ['PATH']), dict(report_written=True, within_cap=True, status='INCOMPLETE'), pair='honest_stub', cls='INJECTED PATH (slow git)')
    # ---- AF2-03: task drift (pinned manifest, model edited afterwards) refused before launch; a PRE-EXISTING snapshot evidence file in the output directory refused before anything runs; evidence injected into the snapshot at the runtime boundary refused at the worker binding; the positive control (ORIGINAL edited after the snapshot) still COMPLETE 3/4
    md3 = os.path.join(OUT, 'stub_manifest_drift'); mp3 = stub_manifest(md3, os.path.join(OUT, 'stub_task_drift'), REQ); open(mp3, 'w').write('MARKOV\n1\n2\n1\n1 0\n2\n1 1\n')
    run('task_drift_model_changed', md3, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'TASK_INTEGRITY' in o['stop'], cells=lambda o: len(o['cells']) == 1 and o['cells'][0][0] == 'NOT_RUN'), pair='honest_stub', cls='COPIED FIXTURE MUTATION')
    def preexisting(rd): os.makedirs(os.path.join(rd, 'inputs', 'FL_C35_mixed_alias')); open(os.path.join(rd, 'inputs', 'FL_C35_mixed_alias', 'model.uai.evid'), 'w').write('1 0 0\n')
    run('preexisting_snapshot_evidence_refused', md, 60, N, dict(report_written=False, rc=lambda o: o['rc'] not in (0, 'DRIVER_TIMEOUT'), stderr_tail=lambda o: 'refuse' in (o['stderr_tail'] or '') and 'not empty' in (o['stderr_tail'] or '')), pair='honest_stub', cls='OUTPUT-DIRECTORY MUTATION (unchanged runner)', pre=preexisting)
    run('evidence_injected_into_snapshot_at_runtime', md, 60, dict(N, LIFECYCLE_WORKER='inject_evidence'), dict(status='STOP', report_written=True, stop=lambda o: 'TASK_INTEGRITY' in o['stop'], cells=lambda o: not any(c[2] == 'ACCEPTED' for c in o['cells'])), pair='honest_stub')
    md5 = os.path.join(OUT, 'stub_manifest_edit_original'); mp5 = stub_manifest(md5, os.path.join(OUT, 'stub_task_edit_original'), REQ); TR.truth_for(mp5, stub, os.path.join(md5, 'truth_cache'), deadline_s=10)
    o5 = run('original_edited_after_snapshot_positive', md5, 60, dict(N, LIFECYCLE_WORKER='edit_original', LIFECYCLE_ORIGINAL=mp5), COMPLETE_3_4, cls='HONEST CONTROL (the original changes after the snapshot; the pinned snapshot is unaffected)')
    res[-1]['original_changed'] = TR.sha_file(mp5) != json.load(open(os.path.join(md5, 'DEV_MANIFEST.json')))['rows'][0]['model_sha256']; res[-1]['PASS'] = res[-1]['PASS'] and res[-1]['original_changed']
    # ---- AF2-04: BUILD DRIFT after the pinned identity (a comment appended to the stub build's checker.py by the first worker; the answer is unchanged) -> BUILD_DRIFT stop; the drifted stub is a COPY so later scenarios keep the clean stub
    stub2 = os.path.join(OUT, 'stub_build_drift'); shutil.copytree(stub, stub2, symlinks=True); md6 = os.path.join(OUT, 'stub_manifest_build_drift'); mp6 = stub_manifest(md6, os.path.join(OUT, 'stub_task_build_drift'), REQ); TR.truth_for(mp6, stub2, os.path.join(md6, 'truth_cache'), deadline_s=10)
    run('build_drift_comment_after_pinned_identity', md6, 60, dict(N, LIFECYCLE_WORKER='drift'), dict(status='STOP', report_written=True, stop=lambda o: 'BUILD_DRIFT' in o['stop'], drift=lambda o: bool((o['drift'] or {}).get('drift_found'))), build=stub2, pair='honest_stub', cls='INJECTED BUILD MUTATION (copied stub build)')
    # ---- forged cache identity, wrong cached answer, and the TRUSTED INDEX: an unindexed record / a record whose file differs from the index
    md4 = os.path.join(OUT, 'stub_manifest_cache'); mp4 = stub_manifest(md4, os.path.join(OUT, 'stub_task_cache'), REQ); rec = TR.truth_for(mp4, stub, os.path.join(md4, 'truth_cache'), deadline_s=10); cp = os.path.join(md4, 'truth_cache', rec['digest'] + '.json')
    hon = json.load(open(cp)); shutil.copyfile(cp, cp + '.honest'); forged = dict(hon); forged['oracle'] = dict(hon['oracle'], sha256='0' * 64); json.dump(forged, open(cp, 'w'))
    run('forged_cache_oracle_identity', md4, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'HARNESS_INTEGRITY' in o['stop']), pair='honest_stub', cls='CACHE RECORD MUTATION')
    wrong = dict(hon); wrong['answers'] = ['1/2']; json.dump(wrong, open(cp, 'w'))
    run('wrong_cached_answer_unsealed', md4, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'HARNESS_INTEGRITY' in o['stop']), pair='honest_stub', cls='CACHE RECORD MUTATION')
    shutil.copyfile(cp + '.honest', cp); os.remove(cp + '.honest'); idx_sha = TR.write_index(os.path.join(md4, 'truth_cache'), stub, note='controls battery')
    run('indexed_cache_honest', md4, 60, N, dict(COMPLETE_3_4, cells=lambda o: all(c[3] == 'CONTAINED' for c in o['cells'])), cls='HONEST CONTROL (trusted preparation index present)')
    coherent = dict(hon); coherent['answers'] = ['1/2']; coherent['content_sha256'] = TR._seal(coherent); json.dump(coherent, open(cp, 'w'))          # a COHERENTLY resealed wrong record (passes the self-seal) -> refused by the INDEX
    run('coherently_resealed_record_refused_by_index', md4, 60, N, dict(status='STOP', report_written=True, stop=lambda o: 'HARNESS_INTEGRITY' in o['stop'] and 'index' in o['stop']), pair='indexed_cache_honest', cls='CACHE RECORD MUTATION (coherent reseal)')
    json.dump(hon, open(cp, 'w'), indent=1)
    # built-in harness controls on the REAL accepted baseline and the real pinned manifest (smoke subset)
    for name, extra, exp in (('real_missing_output', ['--inject-missing-output', 'FL_SENT_ASIA', '--mode', 'smoke'], dict(status='INCOMPLETE', report_written=True)), ('real_corrupted_copy', ['--inject-corrupt', 'FL_C35_mixed_alias', '--mode', 'smoke'], dict(status='STOP', report_written=True, stop=lambda o: 'CANDIDATE_CORRECTNESS' in o['stop'])), ('real_cap_exhaustion', ['--mode', 'smoke', '--total-cap', '16'], dict(status='INCOMPLETE', report_written=True, within_cap=True))):
        cap = 16 if 'cap' in name else 120
        rd = os.path.join(OUT, name); cmd = [PY, os.path.join(HERE, 'run.py'), '--manifest', a.manifest, '--candidate', base, '--baseline', base, '--out', rd, '--label', 'CONTROL ' + name] + (['--total-cap', str(cap)] if 'cap' not in name else []) + extra
        t = time.monotonic(); p = subprocess.run(cmd, capture_output=True, text=True, timeout=cap + 60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1')); wall = time.monotonic() - t; rp = os.path.join(rd, 'ITERATION_REPORT.json'); rep = json.load(open(rp)) if os.path.exists(rp) else {}
        obs = dict(status=rep.get('status'), execution=rep.get('execution'), stop=(rep.get('stop_reason') or '')[:120], report_written=os.path.exists(rp), rc=p.returncode, launch_wall_s=round(wall, 3), elapsed_reported_s=rep.get('elapsed_s'), within_cap=rep.get('within_cap'), not_run=len(rep.get('not_run') or []), no_output=len(rep.get('no_output') or []))
        ok = all((obs.get(k) == v) if not callable(v) else v(obs) for k, v in exp.items()); res.append(dict(name=name, classification='REAL accepted baseline; injected at the harness boundary', paired_honest_control='the smoke panel of the development run', expect={k: (v if not callable(v) else 'predicate') for k, v in exp.items()}, observed=obs, PASS=ok)); print(json.dumps(dict(name=name, PASS=ok, status=obs['status'], execution=obs['execution'], stop=obs['stop'][:80], wall=obs['launch_wall_s'], within_cap=obs['within_cap'])), flush=True)
    out = dict(schema='CQR_FASTLOOP_CONTROLS_V3', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), elapsed_s=round(time.monotonic() - T0, 3), all_pass=all(r['PASS'] for r in res), scenarios=res, note='every scenario is an INJECTED harness control (stub build, copied-fixture / cache / output-directory mutation, PATH injection, or boundary injection on the real baseline), never a natural candidate failure; each acceptance-boundary scenario names its paired honest control')
    json.dump(out, open(os.path.join(OUT, 'CONTROLS.json'), 'w'), indent=1); print(json.dumps(dict(all_pass=out['all_pass'], scenarios=len(res), elapsed_s=out['elapsed_s'], failed=[r['name'] for r in res if not r['PASS']])))
    alive = subprocess.run(['pgrep', '-fl', 'stub_build/|cex/fastloop/run.py'], capture_output=True, text=True).stdout.strip(); print('processes alive after the battery:', alive or 'none')
if __name__ == '__main__': main()
