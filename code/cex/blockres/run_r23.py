"""Round-23 paired runner: both arms of the SAME frozen build under IDENTICAL supervision (run_paired conventions): NEW = integrated.py default; BASE = the same command + --no-ancestral-response.
Arm order alternates by task index (even: NEW first); a confirmation (--confirm) reverses it. One fresh supervised process per cell. usage: run_r23.py SUBDIR MANIFEST.json [--only NAME[,..]] [--confirm]"""
import sys, os, json, time, subprocess, argparse
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'; CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(CODE, '.venv/bin/python')
FROZEN = dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, check_s=0.5, construct_share=0.5, crosscheck=True, budget_s=19.5, outer_timeout_s=20.0, mem_gib=3, epsilon='1/200', delta='1/1000000')
ARMS = dict(new=[], base=['--no-ancestral-response'])
assert open(os.path.join(CODE, 'cex/blockres/run_paired.py')).read().count("FROZEN = dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, check_s=0.5, construct_share=0.5, crosscheck=True, budget_s=19.5, outer_timeout_s=20.0, mem_gib=3, epsilon='1/200', delta='1/1000000')") == 1
ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--only', default=None); ap.add_argument('--confirm', action='store_true'); a = ap.parse_args()
man = json.load(open(a.manifest)); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None
results = []
for i, t in enumerate(man['tasks']):
    if a.only and t['name'] not in a.only.split(','): continue
    order = ['new', 'base'] if i % 2 == 0 else ['base', 'new']
    if a.confirm: order = order[::-1]
    for arm in order:
        tag = 'c' if a.confirm else 's1'; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json')
        cmd = [PY, os.path.join(CODE, 'cex/blockres/integrated.py'), '--input', t['model'], '--output', out, '--budget', str(FROZEN['budget_s']), '--mb-cap', str(FROZEN['mb_cap']), '--table-cap', str(FROZEN['table_cap']), '--enum-cap', str(FROZEN['enum_cap']), '--schedule', FROZEN['schedule'], '--route', FROZEN['route'], '--proposal', FROZEN['proposal'], '--batch', str(FROZEN['batch']), '--seed', '1', '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']] + ARMS[arm]
        job = 'r23:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', os.path.join(RD, 'BLOCKRES_LEDGER.jsonl'), '--scope', 'blockres_r23', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', 'caffeinate', '-s'] + cmd
        subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(job)
        row = dict(task=t['name'], group=t.get('group'), arm=arm, confirm=a.confirm, receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc else None), command=' '.join(cmd))
        try:
            d = json.load(open(out)); ar = d['mechanism'].get('ancestral_response') or {}; lc = d['mechanism'].get('layered_contraction') or {}; se = d['mechanism'].get('evidence_expansion') or {}
            row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d['K'], route=d['mechanism'].get('route'), ar_status=str(ar.get('status'))[:160], lc_status=str(lc.get('status'))[:100], se_status=str(se.get('status'))[:60], solver_wall_s=d['wall_s'], phases={k: round(v, 3) for k, v in d['phases_s'].items()})
        except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:120])
        row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= 20.0 and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'EXACT'))
        results.append(row); print(json.dumps({k: v for k, v in row.items() if k not in ('command', 'phases')}, default=str)[:330], flush=True)
json.dump(dict(frozen=FROZEN, arms=ARMS, manifest=a.manifest, confirm=a.confirm, only=a.only, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s%s.json' % ('confirm' if a.confirm else 'primary', ('_' + a.only.replace(',', '_')) if a.only else '')), 'w'), indent=1, default=str)
