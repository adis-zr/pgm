"""Paired sweep runner (round 9): for each task, the FROZEN candidate (integrated.py, max proposal) and the FROZEN incumbent bank arm (cex/cqr/worker.py N1_CQR, the bank's fixed
selection policy route_policy auto) under IDENTICAL supervision: outer timeout 20 s, worker budget 19.5 s, 3 GiB, caffeinate -s, single-thread env. Arm order alternates per task.
usage: run_paired.py SUBDIR MANIFEST.json [--seed S] [--arms both|cand|inc] ; the manifest lists tasks [{name, model, evidence}] in frozen order."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, subprocess, secrets, hashlib, argparse, shutil
from research.source_execution import bound_source_command, supervisor_environment
RD = str(_runs_root() / 'mdi_2026-10-28/BLOCKRES_2026-11-19'); CODE = str(_repo_root()); PY = sys.executable
FROZEN = dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, check_s=0.5, construct_share=0.5, crosscheck=True, budget_s=19.5, outer_timeout_s=20.0, mem_gib=3, epsilon='1/200', delta='1/1000000')
ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--seed', default='1'); ap.add_argument('--arms', default='both'); ap.add_argument('--cand-extra', default='', help='extra arguments appended to the candidate command (e.g. --no-support-closure for the frozen comparator path)'); ap.add_argument('--only', default=None)
a = ap.parse_args(); man = json.load(open(a.manifest)); env = supervisor_environment(dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'))
def sup(job, cmd, attempt):
    return [PY, '-m', 'pgm.runtime.supervise', '--ledger', os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'), '--scope', 'blockres_sweep', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05',
            '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--'] + ([shutil.which('caffeinate'), '-s'] if shutil.which('caffeinate') else []) + bound_source_command(CODE, cmd)
def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None
results = []
for i, t in enumerate(man['tasks']):
    if a.only and t['name'] not in a.only.split(','): continue
    order = ['cand', 'inc'] if i % 2 == 0 else ['inc', 'cand']
    for arm in order:
        if a.arms != 'both' and arm != a.arms: continue
        attempt = os.path.join(RD, a.sub, '%02d__%s__%s__s%s' % (i, t['name'], arm, a.seed)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); nonce = secrets.token_hex(8)
        if arm == 'cand':
            cmd = [PY, os.path.join(CODE, 'src/pgm/algorithms/block/integrated.py'), '--input', t['model'], '--output', out, '--budget', str(FROZEN['budget_s']), '--mb-cap', str(FROZEN['mb_cap']), '--table-cap', str(FROZEN['table_cap']), '--enum-cap', str(FROZEN['enum_cap']),
                   '--schedule', FROZEN['schedule'], '--route', FROZEN['route'], '--proposal', FROZEN['proposal'], '--batch', str(FROZEN['batch']), '--seed', a.seed, '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']] + a.cand_extra.split()
        else:
            seed_hex = hashlib.sha256(('blockres_sweep|%s|%s|N1_CQR|%s' % (t['name'], t['model'], a.seed)).encode()).hexdigest()
            launch = time.monotonic(); cmd = [PY, os.path.join(CODE, 'research/campaigns/cqr/worker.py'), '--input', t['model'], '--output', out, '--arm', 'N1_CQR', '--deadline', str(launch + FROZEN['budget_s']), '--seed', seed_hex, '--nonce', nonce, '--budget', str(FROZEN['budget_s'])]
        job = 'sweep:%s:%s:%s:s%s' % (a.sub, t['name'], arm, a.seed); t0 = time.monotonic(); subprocess.run(sup(job, cmd, attempt), cwd=CODE, env=env); wall_outer = time.monotonic() - t0
        rc = last_receipt(job); row = dict(task=t['name'], arm=arm, seed=a.seed, order=order.index(arm), receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_gib=((rc['peak_tree_rss_bytes'] / 2 ** 30) if rc else None))
        try:
            d = json.load(open(out))
            if arm == 'cand':
                row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d['K'], route=d['mechanism'].get('route'), splits=d['mechanism'].get('mb_splits'), refusal=d.get('refusal'), max_remaining_width=d['mechanism'].get('max_remaining_width'),
                           X_mean=d['mechanism'].get('X_mean'), ESS=d['mechanism'].get('ESS'), largest_share=d['mechanism'].get('largest_share'), zero_frac=d['mechanism'].get('zero_weight_fraction'), draws=d['mechanism'].get('draws'), interior_failed=d['mechanism'].get('interior_queries_failed'), construct_s=sum(v for k, v in d['phases_s'].items() if k in ('read', 'integerize', 'contract', 'float_convert', 'query_tables', 'mb_construct')))
            else:
                ans = d.get('answers') or []; pubn = sum(1 for x in ans if x.get('status') == 'OK') if ans and isinstance(ans[0], dict) else None
                row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee_type'), published=pubn, K=(len(ans) if ans else None), route=d.get('route'), status=d.get('status'), reason=str(d.get('reason', ''))[:120])
        except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:120])
        row['complete_within_contract'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= 20.0 and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'PUBLISHED', 'EXACT'))
        results.append(row); print(json.dumps(row, default=str)[:400], flush=True)
json.dump(dict(frozen=FROZEN, manifest=a.manifest, seed=a.seed, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'SWEEP_RESULTS_s%s%s.json' % (a.seed, ('_' + a.only.replace(',', '_')) if a.only else '')), 'w'), indent=1, default=str)
