"""DGP4 oracle phase driver (derived from the DGP3 driver): runs dgp4_oracle.py on every ORACLE_MANIFEST model under supervision (scope dgp4_oracle), 100 s cap per model initially; --replay on the 7 replay-panel models (3 exposed strong card-4 anchors + 4 fresh strong card-4 oracles); then ONE deterministic model-hash-order continuation pass over the models
whose outputs are censored, spending the oracle-phase remainder (allocation 2,000 s minus charged) on the phases not yet recorded (--continue: every completed phase is reused from the JSON, the streams are rebuilt deterministically). usage: dgp4_oracle_driver.py --code-root ROOT [--records RD] [--phase initial|continuation]"""

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
RD = str(_runs_root() / 'mdi_2026-10-28/DGP4_RESIDUAL_MAX'); SUP_CODE = str(_repo_root()); PY = sys.executable; ALLOC = 2000.0; REPLAY_PANEL = {'dg_n6_c4_clique_two', 'dg_n8_c4_er50_two', 'dg_n8_c4_clique_two'}      # + every fresh ORACLE4 model with scale 2 (strong), resolved from the manifest
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def charged(ledger, scope): return sum(json.loads(l)['wall_s'] for l in open(ledger) if json.loads(l).get('kind') == 'RECEIPT' and json.loads(l).get('scope') == scope)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code-root', required=True); ap.add_argument('--records', default=RD); ap.add_argument('--phase', default='initial', choices=['initial', 'continuation']); ap.add_argument('--cap-s', type=float, default=100.0); a = ap.parse_args()
    rd = a.records; root = os.path.abspath(a.code_root); man = json.load(open(os.path.join(rd, 'ORACLE_MANIFEST.json')))['tasks']; ledger = os.path.join(rd, 'DGP4_LEDGER.jsonl'); out_dir = os.path.join(rd, 'oracle', 'results'); os.makedirs(out_dir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env = supervisor_environment(env)
    order = sorted(man, key=lambda t: t['model_sha256']) if a.phase == 'continuation' else man
    for t in order:
        out = os.path.join(out_dir, t['name'] + '.json'); extra = []
        if a.phase == 'continuation':
            d = json.load(open(out)) if os.path.exists(out) else None
            if d is not None and not d.get('censored'): continue
            rem = ALLOC - charged(ledger, 'dgp4_oracle')
            if rem < 20: print('oracle allowance exhausted; stopping the continuation pass at', t['name']); break
            cap = min(a.cap_s, rem); extra = ['--cap-s', str(cap), '--continue']; job = 'dgp4:oracle:%s:continuation' % t['name']; out2 = out
        else:
            if os.path.exists(out) and not (json.load(open(out)).get('censored')): print('initial: complete output exists for', t['name'], '-- not rerun'); continue        # idempotent restart of the initial pass (FREEZE_AMENDMENT_harness1)
            cap = a.cap_s; extra = ['--cap-s', str(cap)]; job = 'dgp4:oracle:%s' % t['name']; out2 = out
        cmd = [PY, os.path.join(root, 'research/campaigns/hp/dgp4_oracle.py'), t['model'], out2] + extra + (['--replay'] if (t['name'] in REPLAY_PANEL or (t.get('panel') == 'oracle_fresh_8' and str(t.get('scale')) == '2')) else [])
        cmd = bound_source_command(root, cmd)
        sup = [PY, '-m', 'pgm.runtime.supervise', '--ledger', ledger, '--scope', 'dgp4_oracle', '--job', job, '--timeout', str(cap + 15), '--mem-gib', '3', '--interval', '0.05', '--cwd', str(root), '--stdout', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stdout.txt'), '--stderr', os.path.join(out_dir, t['name'] + ('.continuation' if a.phase == 'continuation' else '') + '.stderr.txt'), '--'] + (['/usr/bin/caffeinate', '-s'] if os.path.exists('/usr/bin/caffeinate') else []) + cmd
        subprocess.run(sup, cwd=SUP_CODE, env=env); r = json.load(open(out2)) if os.path.exists(out2) else {}
        print(json.dumps(dict(model=t['name'], phase=a.phase, cap=cap, wall=r.get('wall_s'), censored=r.get('censored'), phases={k: round(v, 1) for k, v in (r.get('phases') or {}).items()}), default=str), flush=True)
if __name__ == '__main__': main()
