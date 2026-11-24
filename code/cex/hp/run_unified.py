"""Four-arm supervised runner of the unified-planner pilot (brief section 9): BASE = accepted v2.13.2 integrated.py default (frozen run_hp options, its own recovery cutoff preserved);
IDENTITY = unified_planner.py --policy identity (the common task / executor / publisher path restricted to identity; its sole solve gets the remaining work deadline); FAST = the frozen HP v0.2
coarse_envelope.py --policy FAST (unchanged); UNIFIED = unified_planner.py --policy unified. Identical external limits per cell (4.0 s supervisor, 3 GiB, caffeinate -s, single thread, fresh process).
Arm order cycles BASE,IDENTITY,FAST,UNIFIED and its left rotations by task index; --confirm reverses. usage: run_unified.py SUBDIR MANIFEST.json [--only NAME[,..]] [--confirm] [--arms a,b,..]"""
import sys, os, json, time, subprocess, argparse
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/UNIFIED_PLANNER_2026-11-24'; CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(CODE, '.venv/bin/python')
FROZEN = dict(outer_timeout_s=4.0, mem_gib=3, worker_budget_s=3.85, admission_stop_s=3.5, epsilon='1/200', delta='1/1000000', base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, seed=1), fast_fit_allowance_s=1.0)
ARMS = ['base', 'identity', 'fast', 'unified']
def order_for(i): r = i % 4; return ARMS[r:] + ARMS[:r]

def cmd_of(arm, model, out):
    if arm == 'base':
        b = FROZEN['base']; return [PY, os.path.join(CODE, 'cex/blockres/integrated.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(b['seed']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    if arm == 'fast': return [PY, os.path.join(CODE, 'cex/hp/coarse_envelope.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--admission-stop', str(FROZEN['admission_stop_s']), '--policy', 'FAST', '--epsilon', FROZEN['epsilon'], '--fit-allowance', str(FROZEN['fast_fit_allowance_s'])]
    return [PY, os.path.join(CODE, 'cex/hp/unified_planner.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--admission-stop', str(FROZEN['admission_stop_s']), '--policy', arm, '--epsilon', FROZEN['epsilon']]

def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'UP_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--only', default=None); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--arms', default=','.join(ARMS)); a = ap.parse_args()
    man = json.load(open(a.manifest)); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); results = []; wanted = a.arms.split(',')
    for i, t in enumerate(man['tasks']):
        if a.only and t['name'] not in a.only.split(','): continue
        order = order_for(i)
        if a.confirm: order = order[::-1]
        for arm in order:
            if arm not in wanted: continue
            tag = 'c' if a.confirm else 'p'; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out); job = 'up:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', os.path.join(RD, 'UP_LEDGER.jsonl'), '--scope', 'up_pilot', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', '/usr/bin/caffeinate', '-s'] + cmd
            subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(job)
            row = dict(task=t['name'], panel=t.get('panel'), topology=t.get('topology'), card=t.get('card'), family=t.get('family'), arm=arm, confirm=a.confirm, order_index=order.index(arm), receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc else None), command=' '.join(cmd))
            try:
                d = json.load(open(out)); m = d.get('mechanism') or {}
                row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), max_width=d.get('max_width'), Z=d.get('Z_enclosure'), phases={k: round(v, 4) for k, v in (d.get('phases_s') or {}).items()}, peak_rss_bytes=d.get('peak_rss_bytes'))
                if arm == 'base': row.update(route=m.get('route'), deadline_phase=d.get('deadline_phase'), base_mech={k: m.get(k) for k in ('route', 'exact_route', 'mb_splits', 'draws', 'ESS', 'published', 'max_remaining_width')})
                elif arm == 'fast': row.update(executor_calls=m.get('executor_calls'), witnesses=[(w.get('kind'), w.get('status'), w.get('coarse_states'), w.get('local_R'), w.get('actual_rho'), w.get('max_width')) for w in m.get('witnesses', [])], refusal=m.get('refusal'), defect=m.get('defect'), note=m.get('note'), rational_bit_peak=max([w.get('proposal_record', {}).get('max_bits', 0) for w in m.get('witnesses', [])] + [0]))
                else: row.update(native_attempts=m.get('native_attempts'), actions=d.get('actions'), decisions=d.get('decisions'), candidates=d.get('candidates'), refusal=m.get('refusal'), defect=m.get('defect'), note=m.get('note'), representations_solved=m.get('representations_solved'), rational_bit_peak=m.get('rational_bit_peak'), constructor_peak_bytes=m.get('constructor_budget_peak_bytes'), constructor_cumulative_bytes=m.get('constructor_budget_cumulative_bytes'), max_point_radius=d.get('max_point_radius'), rates=d.get('rates'))
            except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:160])
            row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= FROZEN['outer_timeout_s'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'EXACT') and (row.get('Z') or {}).get('positive', True) is not False)
            results.append(row); print(json.dumps({k: v for k, v in row.items() if k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'peak_MiB', 'complete', 'native_attempts', 'representations_solved', 'refusal')}, default=str)[:300], flush=True)
    json.dump(dict(frozen=FROZEN, arms=ARMS, manifest=a.manifest, confirm=a.confirm, only=a.only, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s%s.json' % ('confirm' if a.confirm else 'primary', ('_' + a.only.replace(',', '_')) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
