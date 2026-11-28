"""Supervised four-arm runner of DENSE_GENERIC_PAC_INTEGRATION_1 (brief sections 8-9). Arms: BASE = accepted v2.13.2 integrated.py with run_paired.FROZEN options; DET = unified_planner v0.4.1 (USR1 D: P1 / R1,
no PAC); UPAC = unified_pac_planner (persistent PAC, lifted disabled); FULL = UPAC + --lifted. Contracts: main 20.0 s outer / 19.5 hard / 19.0 work; preservation-4 4.0 / 3.85 / 3.5; preservation-20 and
long-60 59.5 / 59.0 under 60.0. 3 GiB sampled process-tree RSS. Arm order for task index i = left rotation of the arm list by i mod |arms|; --confirm reverses it. Seeds: --seed (BASE / UPAC / FULL share it).
usage: run_dgp.py SUBDIR MANIFEST.json --arms BASE,DET,UPAC,FULL --contract main|p4|p20|long [--confirm] [--seed N] [--only a,b] [--scope S]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, subprocess, argparse
RD = str(_runs_root() / 'mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1'); CODE = str(_repo_root()); PY = sys.executable
CONTRACTS = dict(main=dict(outer=20.0, hard=19.5, work=19.0), p4=dict(outer=4.0, hard=3.85, work=3.5), p20=dict(outer=20.0, hard=19.5, work=19.0), long=dict(outer=60.0, hard=59.5, work=59.0))
FROZEN = dict(mem_gib=3, epsilon='1/200', delta='1/1000000', base=dict(route='auto', proposal='mb', schedule='targeted', table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, batch=1024), det=dict(sched='P1', rates='R1'), contracts=CONTRACTS)
ARMS = ['BASE', 'DET', 'UPAC', 'FULL']

def cmd_of(arm, model, out, c, seed):
    b = FROZEN['base']
    if arm == 'BASE': return [PY, os.path.join(CODE, 'src/pgm/algorithms/block/integrated.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--mb-cap', str(b['mb_cap']), '--table-cap', str(b['table_cap']), '--enum-cap', str(b['enum_cap']), '--schedule', b['schedule'], '--route', b['route'], '--proposal', b['proposal'], '--batch', str(b['batch']), '--seed', str(seed), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta']]
    if arm == 'DET': return [PY, os.path.join(CODE, 'src/pgm/algorithms/quotient/unified_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--policy', 'unified', '--sched', FROZEN['det']['sched'], '--rates', FROZEN['det']['rates']]
    base = [PY, os.path.join(CODE, 'src/pgm/algorithms/quotient/unified_pac_planner.py'), '--input', model, '--output', out, '--budget', str(c['hard']), '--admission-stop', str(c['work']), '--epsilon', FROZEN['epsilon'], '--delta', FROZEN['delta'], '--seed', str(seed)]
    return base + (['--lifted'] if arm == 'FULL' else [])

def last_receipt(ledger, job):
    rows = [json.loads(l) for l in open(ledger)]; r = [x for x in rows if x.get('kind') == 'RECEIPT' and x['job'] == job]; return r[-1] if r else None

def summarize(arm, out, rc, c):
    row = dict(receipt_wall_s=(rc['wall_s'] if rc else None), receipt_outcome=(rc['outcome'] if rc else None), peak_MiB=((rc['peak_tree_rss_bytes'] / 2 ** 20) if rc and rc.get('peak_tree_rss_bytes') else None))
    try:
        d = json.load(open(out)); m = d.get('mechanism') or {}
        row.update(outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), solver_wall_s=d.get('wall_s'), max_width=d.get('max_width'), termination=m.get('termination'), route=m.get('route'), peak_rss_bytes=d.get('peak_rss_bytes'), positive_mass_witness=(d.get('positive_mass_witness') if arm == 'BASE' else m.get('positive_mass_witness')), hard_deadline_respected=d.get('hard_deadline_respected'))
        if arm == 'BASE':
            row.update(base=dict(draws=m.get('draws'), Kq=m.get('Kq'), remaining=m.get('remaining'), max_remaining_width=m.get('max_remaining_width'), median_remaining_width=m.get('median_remaining_width'), X_mean=m.get('X_mean'), ESS=m.get('ESS'), zero_weight_fraction=m.get('zero_weight_fraction'), largest_share=m.get('largest_share'), eps_num=m.get('eps_num'), mb_cap=m.get('mb_cap'), mb_splits=m.get('mb_splits'), batch_used=m.get('batch_used'), deadline_phase=d.get('deadline_phase'), refusal=d.get('refusal'), trace=d.get('trace'), phases=d.get('phases_s'), structural={k: (m.get(k) or {}).get('status') for k in ('evidence_expansion', 'layered_contraction', 'ancestral_response', 'support_closure')}))
            rows_ = d.get('answers') or []; ws = [float(__import__('fractions').Fraction(r['hi']) - __import__('fractions').Fraction(r['lo'])) / 2 for r in rows_ if r['guarantee'] != 'NOT_PUBLISHED']; row['radius_report'] = dict(worst=(max(ws) if ws else None), covered_at_eps=sum(1 for w in ws if w <= 0.005), published=len(ws), K=d.get('K'))
        elif arm == 'DET': row.update(det=dict(native_attempts=m.get('native_attempts'), refusal=m.get('refusal'), representations_solved=m.get('representations_solved'), decisions=[x.get('chosen') for x in d.get('decisions', [])], phases=d.get('phases_s'), max_point_radius=d.get('max_point_radius')))
        else: row.update(upac=dict(streams=[{k: s.get(k) for k in ('kind', 'label', 'stage', 'closed', 'delta_s', 'draws', 'zero_draws', 'batches', 'abandoned', 'checkpoints', 'witness', 'published', 'K', 't_prep', 't_sample', 't_cert', 'X_mean', 'zero_weight_fraction', 'ESS_DIAGNOSTIC', 'largest_share', 'max_log2_X_observed', 'max_remaining_width', 'retained_bytes')} | dict(mechanism={k: v for k, v in (s.get('mechanism') or {}).items() if k in ('eps_num', 'rho_cap', 'alpha_per_coordinate', 'cap_log2_total', 'kappa_log2', 'mb_cap', 'mb_splits', 'Kq', 'batch_used', 'terminal', 'exact_route', 'memory_policy', 'proposal_immutable', 'coarse_cards', 'widening')}, trace=s.get('trace')) for s in d.get('streams', [])], risk_ledger=d.get('risk_ledger'), conflicts=d.get('conflicts'), checkpoints=d.get('checkpoints'), radius_report=d.get('radius_report'), cost_breakdown=d.get('cost_breakdown'), decisions=[x.get('chosen') for x in d.get('decisions', [])], E=m.get('exploration_account_s'), E_used=m.get('exploration_used_s'), refusal=m.get('refusal'), defect=m.get('defect'), structural=m.get('structural_info'), representations_solved=m.get('representations_solved'), native_attempts=m.get('native_attempts'), live_memory=m.get('live_memory_named_bytes')), radius_report=d.get('radius_report'))
    except Exception as e: row.update(outcome='NO_RESULT_FILE', error=repr(e)[:200])
    row['complete'] = bool(rc and rc['outcome'] == 'COMPLETED' and rc['wall_s'] <= c['outer'] and row.get('published') is not None and row.get('K') and row['published'] == row['K'] and row.get('outcome') in ('COMPLETE', 'EXACT') and bool(row.get('positive_mass_witness')) and (row.get('hard_deadline_respected') is not False))
    return row

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sub'); ap.add_argument('manifest'); ap.add_argument('--arms', default=','.join(ARMS)); ap.add_argument('--contract', default='main', choices=list(CONTRACTS)); ap.add_argument('--confirm', action='store_true'); ap.add_argument('--seed', type=int, default=1); ap.add_argument('--only', default=None); ap.add_argument('--scope', default='dgp_main'); ap.add_argument('--tag', default=None); a = ap.parse_args()
    man = json.load(open(a.manifest)); tasks = man['tasks']; arms = a.arms.split(','); c = CONTRACTS[a.contract]; env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); results = []; ledger = os.path.join(RD, 'DGP_LEDGER.jsonl')
    for i, t in enumerate(tasks):
        if a.only and t['name'] not in a.only.split(','): continue
        r = i % len(arms); order = arms[r:] + arms[:r]
        if a.confirm: order = order[::-1]
        for arm in order:
            tag = a.tag or (('c%d' % a.seed) if a.confirm else 'p'); attempt = os.path.join(RD, a.sub, '%02d__%s__%s__%s' % (i, t['name'], arm, tag)); os.makedirs(attempt, exist_ok=True); out = os.path.join(attempt, 'result.json'); cmd = cmd_of(arm, t['model'], out, c, a.seed); job = 'dgp:%s:%s:%s:%s' % (a.sub, t['name'], arm, tag)
            sup = [PY, '-m', 'pgm.runtime.supervise', '--ledger', ledger, '--scope', a.scope, '--job', job, '--timeout', str(c['outer']), '--mem-gib', str(FROZEN['mem_gib']), '--interval', '0.05', '--stdout', os.path.join(attempt, 'stdout.txt'), '--stderr', os.path.join(attempt, 'stderr.txt'), '--', '/usr/bin/caffeinate', '-s'] + cmd
            subprocess.run(sup, cwd=CODE, env=env); rc = last_receipt(ledger, job)
            row = dict(task=t['name'], arm=arm, task_index=i, order_index=order.index(arm), confirm=a.confirm, seed=a.seed, contract=a.contract, panel=t.get('panel'), family=t.get('family') or t.get('topology'), model_sha256=t.get('model_sha256'), command=' '.join(cmd)); row.update(summarize(arm, out, rc, c)); results.append(row)
            print(json.dumps({k: row.get(k) for k in ('task', 'arm', 'outcome', 'published', 'K', 'receipt_wall_s', 'receipt_outcome', 'complete', 'termination', 'route')}, default=str), flush=True)
            json.dump(dict(frozen=FROZEN, arms=arms, contract=a.contract, manifest=a.manifest, confirm=a.confirm, seed=a.seed, only=a.only, results=results, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(RD, a.sub, 'RESULTS_%s_%s%s.json' % (a.contract, ('confirm_s%d' % a.seed) if a.confirm else ('s%d' % a.seed if a.seed != 1 else 'primary'), ('_' + a.only.replace(',', '_')[:60]) if a.only else '')), 'w'), indent=1, default=str)

if __name__ == '__main__': main()
