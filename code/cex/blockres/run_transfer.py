"""Round-21 paired transfer driver: for each task of the FROZEN manifest, BOTH arms of the SAME build under IDENTICAL supervision (the run_paired.py conventions: outer 20 s, worker 19.5 s,
3 GiB, caffeinate -s, single-thread env, seed 1): 'new' = integrated.py default (layered constructor ON), 'base' = integrated.py --no-layered-contraction (= accepted v2.11.2 behaviour, proven
in round 20 / 21 setup). Arm order alternates per task index. usage: run_transfer.py SUBDIR MANIFEST.json"""
import sys, os, json, time, subprocess
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'; CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(CODE, '.venv/bin/python')
FROZEN = dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, check_s=0.5, construct_share=0.5, crosscheck=True, budget_s=19.5, outer_timeout_s=20.0, mem_gib=3, epsilon='1/200', delta='1/1000000')
ARMS = dict(new=[], base=['--no-layered-contraction'])
sub, manifest = sys.argv[1], sys.argv[2]; man = json.load(open(manifest)); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
assert open(os.path.join(CODE, 'cex/blockres/run_paired.py')).read().count("FROZEN = dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, check_s=0.5, construct_share=0.5, crosscheck=True, budget_s=19.5, outer_timeout_s=20.0, mem_gib=3, epsilon='1/200', delta='1/1000000')") == 1, 'FROZEN drifted from run_paired.py'
def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None
results = []
for i, t in enumerate(man['tasks']):
    for arm in (['new', 'base'] if i % 2 == 0 else ['base', 'new']):
        attempt = os.path.join(RD, sub, '%02d__%s__%s__s1' % (i, t['name'], arm)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json')
        cmd = [PY, os.path.join(CODE, 'cex/blockres/integrated.py'), '--input', t['model'], '--output', out, '--budget', str(FROZEN['budget_s']), '--mb-cap', str(FROZEN['mb_cap']), '--table-cap', str(FROZEN['table_cap']), '--enum-cap', str(FROZEN['enum_cap']), '--schedule', FROZEN['schedule'], '--route', FROZEN['route'], '--proposal', FROZEN['proposal'], '--batch', str(FROZEN['batch']), '--seed', '1', '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']] + ARMS[arm]
        job = 'transfer:%s:%s:%s:s1' % (sub, t['name'], arm)
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'), '--scope', 'blockres_transfer', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', 'caffeinate', '-s'] + cmd
        subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(job)
        row = dict(task=t['name'], group=t.get('group'), arm=arm, receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc else None))
        try:
            d = json.load(open(out)); lc = d['mechanism'].get('layered_contraction') or {}
            row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d['K'], route=d['mechanism'].get('route'), Z=('enclosure' if 'Z_enclosure' in d else ('exact' if 'Z' in d else 'none')), recognition_s=d['phases_s'].get('layered_recognition'), layered_status=str(lc.get('status'))[:140], width_bits=((lc.get('structure') or {}).get('selected') or {}).get('max_interface_bits'), solver_wall_s=d['wall_s'])
        except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:120])
        row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= 20.0 and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'EXACT'))
        results.append(row); print(json.dumps(row, default=str)[:300], flush=True)
json.dump(dict(frozen=FROZEN, arms=ARMS, manifest=manifest, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, sub, 'TRANSFER_RESULTS.json'), 'w'), indent=1, default=str)
