"""Seven-arm supervised runner of UNIFIED_SCHEDULING_REVISION_1 (brief section 7). Arms: A = repaired legacy (frozen v0.3.1 at the detached checkout REF, P0 / R0); B = calibration only (P0 / R1);
C = scheduling only (P1 / R0); D = the proposed revision (P1 / R1); IDENTITY = the frozen identity-only adapter (REF, --policy identity); FAST = frozen HP v0.2 FAST; BASE = accepted v2.13.2.
Primary order for task index i = left rotation of [A, B, C, D, IDENTITY, FAST, BASE] by i mod 7; --confirm reverses that task's primary order. Same external contract as the pilot (4.0 s / 3 GiB).
usage: run_revision.py SUBDIR MANIFEST.json [--only NAME[,..]] [--confirm] [--arms a,b,..]"""
import sys, os, json, time, subprocess, argparse
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/UNIFIED_SCHEDULING_REVISION_1'; CODE = '/Users/adis/Workspace/pgm/code'; REF = '/Users/adis/Workspace/pgm-ref-6c5690a/code'; PY = os.path.join(CODE, '.venv/bin/python')
FROZEN = dict(outer_timeout_s=4.0, mem_gib=3, worker_budget_s=3.85, admission_stop_s=3.5, epsilon='1/200', delta='1/1000000', fast_fit_allowance_s=1.0, base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024, seed=1), ref_checkout='6c5690a (frozen v0.3.1) at ' + REF)
ARMS = ['A', 'B', 'C', 'D', 'IDENTITY', 'FAST', 'BASE']
def order_for(i): r = i % 7; return ARMS[r:] + ARMS[:r]

def cmd_of(arm, model, out):
    b = FROZEN['base']
    if arm == 'BASE': return [PY, os.path.join(CODE, 'cex/blockres/integrated.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(b['seed']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    if arm == 'FAST': return [PY, os.path.join(CODE, 'cex/hp/coarse_envelope.py'), '--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--admission-stop', str(FROZEN['admission_stop_s']), '--policy', 'FAST', '--epsilon', FROZEN['epsilon'], '--fit-allowance', str(FROZEN['fast_fit_allowance_s'])]
    common = ['--input', model, '--output', out, '--budget', str(FROZEN['worker_budget_s']), '--admission-stop', str(FROZEN['admission_stop_s']), '--epsilon', FROZEN['epsilon']]
    if arm == 'A': return [PY, os.path.join(REF, 'cex/hp/unified_planner.py')] + common + ['--policy', 'unified']
    if arm == 'IDENTITY': return [PY, os.path.join(REF, 'cex/hp/unified_planner.py')] + common + ['--policy', 'identity']
    sched, rates = {'B': ('P0', 'R1'), 'C': ('P1', 'R0'), 'D': ('P1', 'R1')}[arm]
    return [PY, os.path.join(CODE, 'cex/hp/unified_planner.py')] + common + ['--policy', 'unified', '--sched', sched, '--rates', rates]

def last_receipt(job):
    rows = [json.loads(l) for l in open(os.path.join(RD, 'USR_LEDGER.jsonl'))]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--only', default=None); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--arms', default=','.join(ARMS)); a = ap.parse_args()
    man = json.load(open(a.manifest)); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); results = []; wanted = a.arms.split(',')
    for i, t in enumerate(man['tasks']):
        if a.only and t['name'] not in a.only.split(','): continue
        order = order_for(i)
        if a.confirm: order = order[::-1]
        for arm in order:
            if arm not in wanted: continue
            tag = 'c' if a.confirm else 'p'; attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out); job = 'usr:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            sup = [PY, '-m', 'gbidi.supervise', '--ledger', os.path.join(RD, 'USR_LEDGER.jsonl'), '--scope', 'usr_pilot', '--job', job, '--timeout', str(FROZEN['outer_timeout_s']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', '/usr/bin/caffeinate', '-s'] + cmd
            subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(job)
            row = dict(task=t['name'], panel=t.get('panel'), topology=t.get('topology'), card=t.get('card'), family=t.get('family'), arm=arm, confirm=a.confirm, order_index=order.index(arm), receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc else None), command=' '.join(cmd))
            try:
                d = json.load(open(out)); m = d.get('mechanism') or {}
                row.update(outcome=d['outcome'], guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), max_width=d.get('max_width'), Z=d.get('Z_enclosure'), phases={k: round(v, 4) for k, v in (d.get('phases_s') or {}).items()}, peak_rss_bytes=d.get('peak_rss_bytes'))
                if arm == 'BASE': row.update(route=m.get('route'), deadline_phase=d.get('deadline_phase'))
                elif arm == 'FAST': row.update(executor_calls=m.get('executor_calls'), witnesses=[(w.get('kind'), w.get('status'), w.get('coarse_states'), w.get('local_R'), w.get('max_width')) for w in m.get('witnesses', [])], refusal=m.get('refusal'), defect=m.get('defect'))
                else: row.update(native_attempts=m.get('native_attempts'), actions=d.get('actions'), decisions=d.get('decisions'), candidates=d.get('candidates'), measurements=d.get('measurements'), refusal=m.get('refusal'), defect=m.get('defect'), note=m.get('note'), representations_solved=m.get('representations_solved'), rational_bit_peak=m.get('rational_bit_peak'), constructor_peak_bytes=m.get('constructor_budget_peak_bytes'), constructor_cumulative_bytes=m.get('constructor_budget_cumulative_bytes'), constructor_live_end=m.get('constructor_live_at_end_bytes'), ledger_identity=m.get('constructor_live_ledger_identity'), max_point_radius=d.get('max_point_radius'), hard_deadline_respected=d.get('hard_deadline_respected'), unassigned_residual_s=d.get('unassigned_residual_s'), version=d.get('version'), sched=d.get('sched'), rates_model=d.get('rates_model'), rates=d.get('rates'), estimation_refusals=m.get('estimation_refusals'))
            except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:160])
            row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= FROZEN['outer_timeout_s'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and str(row.get('outcome')) in ('COMPLETE', 'EXACT') and (row.get('Z') or {}).get('positive', True) is not False)
            results.append(row); print(json.dumps({k: v for k, v in row.items() if k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'complete', 'native_attempts', 'representations_solved')}, default=str)[:260], flush=True)
    json.dump(dict(frozen=FROZEN, arms=ARMS, manifest=a.manifest, confirm=a.confirm, only=a.only, arms_run=a.arms, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s%s.json' % ('confirm' if a.confirm else 'primary', ('_' + a.only.replace(',', '_')) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
