"""Three-arm supervised runner of the Hinton-to-Pearl pilot (brief section 7-8): BASE = accepted v2.13.2 integrated.py default through its normal interface; COARSE_FAST / COARSE_FIT =
cex/hp/coarse_envelope.py --policy FAST | FIT. Identical external limits per cell: supervisor timeout 4.0 s, 3 GiB process-tree RSS, caffeinate -s, single-thread env, one fresh process
per cell; worker budget 3.85 s (admission stop 3.5 s for the candidates). Primary arm order cycles BASE,FAST,FIT / FAST,FIT,BASE / FIT,BASE,FAST by task index; --confirm reverses the
task's order. usage: run_hp.py SUBDIR MANIFEST.json [--only NAME[,..]] [--confirm] [--arms base,fast,fit]"""
import sys, os, json, time, subprocess, argparse
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/HP_COMPILER_2026-11-23'; CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(CODE, '.venv/bin/python')
FROZEN = dict(outer_timeout_s=4.0, mem_gib=3, worker_budget_s=3.85, admission_stop_s=3.5, epsilon='1/200', delta='1/1000000', fit_allowance_s=1.0,
              base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, seed=1))
ORDERS = [['base', 'fast', 'fit'], ['fast', 'fit', 'base'], ['fit', 'base', 'fast']]

def cmd_of(arm, model, out):
    if arm == 'base':
        b = FROZEN['base']
        return [PY, os.path.join(CODE, 'cex/blockres/integrated.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(b['seed']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    return [PY, os.path.join(CODE, 'cex/hp/coarse_envelope.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--admission-stop', str(FROZEN['admission_stop_s']), '--policy', arm.upper(), '--epsilon', FROZEN['epsilon'], '--fit-allowance', str(FROZEN['fit_allowance_s'])]

def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'HP_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--only', default=None); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--arms', default='base,fast,fit'); a = ap.parse_args()
    man = json.load(open(a.manifest)); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); results = []; arms_wanted = a.arms.split(',')
    for i, t in enumerate(man['tasks']):
        if a.only and t['name'] not in a.only.split(','): continue
        order = list(ORDERS[i % 3])
        if a.confirm: order = order[::-1]
        for arm in order:
            if arm not in arms_wanted: continue
            tag = 'c' if a.confirm else 'p'; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out)
            job = 'hp:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', os.path.join(RD, 'HP_LEDGER.jsonl'), '--scope', 'hp_pilot', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', 'caffeinate', '-s'] + cmd
            subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(job)
            row = dict(task=t['name'], topology=t.get('topology'), card=t.get('card'), family=t.get('family'), arm=arm, confirm=a.confirm, order_index=order.index(arm), receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc else None), command=' '.join(cmd))
            try:
                d = json.load(open(out)); m = d.get('mechanism') or {}
                row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), max_width=d.get('max_width'), Z=d.get('Z_enclosure'), phases={k: round(v, 4) for k, v in (d.get('phases_s') or {}).items()})
                if arm == 'base': row.update(route=m.get('route'), base_mech={k: m.get(k) for k in ('route', 'exact_route', 'mb_splits', 'draws', 'ESS', 'published', 'max_remaining_width')})
                else: row.update(executor_calls=m.get('executor_calls'), witnesses=[{k: w.get(k) for k in ('kind', 'status', 'coarse_cards', 'coarse_states', 'local_R', 'actual_rho', 'order_volume_sum', 'order_volume_max', 'executor_calls', 'lower_kernel_s', 'upper_kernel_s', 'one_solve_published', 'two_solve_published', 'max_width', 'one_solve_max_width')} for w in m.get('witnesses', [])],
                                proposals=m.get('proposals'), refinements=m.get('refinements'), refusal=m.get('refusal'), defect=m.get('defect'), note=m.get('note'), exact_quotient=m.get('exact_quotient'), canonical=m.get('canonical'), constructor_peak_bytes=m.get('constructor_budget_peak_bytes'), constructor_cumulative_bytes=m.get('constructor_budget_cumulative_bytes'), rational_bit_peak=max([w.get('proposal_record', {}).get('max_bits', 0) for w in m.get('witnesses', [])] + [0]), peak_rss_bytes=d.get('peak_rss_bytes'))
            except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:160])
            row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= FROZEN['outer_timeout_s'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'EXACT') and (row.get('Z') or {}).get('positive', True) is not False)
            results.append(row); print(json.dumps({k: v for k, v in row.items() if k in ('task', 'arm', 'outcome', 'guarantee', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'peak_MiB', 'complete', 'executor_calls', 'refusal', 'defect', 'route')}, default=str), flush=True)
    json.dump(dict(frozen=FROZEN, orders=ORDERS, manifest=a.manifest, confirm=a.confirm, only=a.only, arms=a.arms, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s%s.json' % ('confirm' if a.confirm else 'primary', ('_' + a.only.replace(',', '_')) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
