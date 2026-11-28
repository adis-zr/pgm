"""DGP5 oracle phase driver (derived from the DGP4 driver): runs dgp5_oracle.py on every ORACLE_MANIFEST model under supervision (scope dgp5_oracle), 100 s cap per model initially; --replay on the 11 replay anchors (7 exposed strong + 4 fresh ORACLE5); then ONE deterministic model-hash-order continuation pass over the models
whose outputs are censored, spending the oracle-phase remainder (allocation 2,000 s minus charged) on the phases not yet recorded (--continue reuses completed replays). usage: dgp5_oracle_driver.py --code-root ROOT [--records RD] [--phase initial|continuation] [--cap-s 100]"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
from research.source_execution import bound_source_command, supervisor_environment
import sys, os, json, time, subprocess, argparse, hashlib
RD = str(_runs_root() / 'mdi_2026-10-28/DGP5_JOINT_CONSTRUCTION'); SUP_CODE = os.environ.get('PGM_CODE', str(_repo_root())); PY = os.environ.get('PY', sys.executable); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate'); ALLOC = 2000.0
def charged(ledger, scope): return sum(json.loads(l)['wall_s'] for l in open(ledger) if json.loads(l).get('kind') == 'RECEIPT' and json.loads(l).get('scope') == scope)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code-root', required=True); ap.add_argument('--records', default=RD); ap.add_argument('--phase', default='initial', choices=['initial', 'continuation']); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--only', default=None); a = ap.parse_args()
    rd = a.records; root = os.path.abspath(a.code_root); mm = json.load(open(os.path.join(rd, 'MODEL_MANIFEST.json'))); man = json.load(open(os.path.join(rd, 'ORACLE_MANIFEST.json')))['tasks']; anchors = set(mm['panels']['replay_anchors']['exposed_7']) | set(mm['panels']['replay_anchors']['fresh_4'])
    ledger = os.path.join(rd, 'DGP5_LEDGER.jsonl'); out_dir = os.path.join(rd, 'oracle', 'results'); os.makedirs(out_dir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env = supervisor_environment(env)
    order = sorted(man, key=lambda t: t['model_sha256']) if a.phase == 'continuation' else man
    for t in order:
        if a.only and t['name'] not in a.only.split(','): continue
        out = os.path.join(out_dir, t['name'] + '.json'); extra = []
        if a.phase == 'continuation':
            d = json.load(open(out)) if os.path.exists(out) else None
            if d is not None and not d.get('censored'): continue
            rem = ALLOC - charged(ledger, 'dgp5_oracle')
            if rem < 20: print('oracle allowance exhausted; stopping the continuation pass at', t['name']); break
            cap = min(a.cap_s, rem); extra = ['--cap-s', str(cap), '--continue']; job = 'dgp5:oracle:%s:continuation' % t['name']
        else:
            if os.path.exists(out) and not (json.load(open(out)).get('censored')): print('initial: complete output exists for', t['name'], '-- not rerun'); continue
            cap = a.cap_s; extra = ['--cap-s', str(cap)]; job = 'dgp5:oracle:%s' % t['name']
        cmd = [PY, os.path.join(root, 'research/campaigns/hp/dgp5_oracle.py'), t['model'], out] + extra + (['--replay'] if t['name'] in anchors else [])
        cmd = bound_source_command(root, cmd)
        sup = [PY, '-m', 'pgm.runtime.supervise', '--ledger', ledger, '--scope', 'dgp5_oracle', '--job', job, '--timeout', str(cap + 15), '--mem-gib', '3', '--interval', '0.05', '--cwd', str(root), '--stdout', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stdout.txt'), '--stderr', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stderr.txt'), '--'] + ([CAFF, '-s'] if CAFF and os.path.exists(CAFF) else []) + cmd
        subprocess.run(sup, cwd=SUP_CODE, env=env); r = json.load(open(out)) if os.path.exists(out) else {}
        print(json.dumps(dict(model=t['name'], phase=a.phase, cap=cap, wall=r.get('wall_s'), censored=r.get('censored'), phases={k: round(v, 1) for k, v in (r.get('phases') or {}).items()}, replay=(t['name'] in anchors)), default=str), flush=True)
if __name__ == '__main__': main()
