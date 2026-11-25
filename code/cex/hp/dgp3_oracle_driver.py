"""DGP3 oracle phase driver (derived from the DGP2 driver): runs dgp3_oracle.py on every ORACLE_MANIFEST model under supervision (scope dgp3_oracle), 100 s cap per model initially; then ONE deterministic model-hash-order continuation pass over the models
whose outputs are censored, spending the oracle-phase remainder (allocation 800 s minus charged) on the phases not yet recorded (--continue: every completed phase is reused from the JSON, the streams are rebuilt deterministically). usage: dgp3_oracle_driver.py --code-root ROOT [--records RD] [--phase initial|continuation]"""
import sys, os, json, time, subprocess, argparse, hashlib
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP3_GROUPED_ENVELOPE'; SUP_CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(SUP_CODE, '.venv/bin/python'); ALLOC = 800.0
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def charged(ledger, scope): return sum(json.loads(l)['wall_s'] for l in open(ledger) if json.loads(l).get('kind') == 'RECEIPT' and json.loads(l).get('scope') == scope)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code-root', required=True); ap.add_argument('--records', default=RD); ap.add_argument('--phase', default='initial', choices=['initial', 'continuation']); ap.add_argument('--cap-s', type=float, default=100.0); a = ap.parse_args()
    rd = a.records; root = os.path.abspath(a.code_root); man = json.load(open(os.path.join(rd, 'ORACLE_MANIFEST.json')))['tasks']; ledger = os.path.join(rd, 'DGP3_LEDGER.jsonl'); out_dir = os.path.join(rd, 'oracle', 'results'); os.makedirs(out_dir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None)
    order = sorted(man, key=lambda t: t['model_sha256']) if a.phase == 'continuation' else man
    for t in order:
        out = os.path.join(out_dir, t['name'] + '.json'); extra = []
        if a.phase == 'continuation':
            d = json.load(open(out)) if os.path.exists(out) else None
            if d is not None and not d.get('censored'): continue
            rem = ALLOC - charged(ledger, 'dgp3_oracle')
            if rem < 20: print('oracle allowance exhausted; stopping the continuation pass at', t['name']); break
            cap = min(a.cap_s, rem); extra = ['--cap-s', str(cap), '--continue']; job = 'dgp3:oracle:%s:continuation' % t['name']; out2 = out
        else:
            if os.path.exists(out) and not (json.load(open(out)).get('censored')): print('initial: complete output exists for', t['name'], '-- not rerun'); continue        # idempotent restart of the initial pass (FREEZE_AMENDMENT_harness1)
            cap = a.cap_s; extra = ['--cap-s', str(cap)]; job = 'dgp3:oracle:%s' % t['name']; out2 = out
        cmd = [PY, os.path.join(root, 'code/cex/hp/dgp3_oracle.py'), t['model'], out2] + extra
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', 'dgp3_oracle', '--job', job, '--timeout', str(cap + 15), '--mem-gib', '3', '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stdout.txt'), '--stderr', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stderr.txt'), '--', '/usr/bin/caffeinate', '-s'] + cmd
        subprocess.run(sup, cwd=SUP_CODE, env=env); r = json.load(open(out2)) if os.path.exists(out2) else {}
        print(json.dumps(dict(model=t['name'], phase=a.phase, cap=cap, wall=r.get('wall_s'), censored=r.get('censored'), phases={k: round(v, 1) for k, v in (r.get('phases') or {}).items()}), default=str), flush=True)
if __name__ == '__main__': main()
