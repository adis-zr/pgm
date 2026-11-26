"""DGP6 oracle phase driver (brief section 6): runs dgp6_oracle.py on every ORACLE_MANIFEST model under supervision (scope dgp6_oracle) in the FROZEN priority order: (1) the full-law construction diagnostics on all 32 models (cap per model;
replays of seed / G0_joint / G1_joint / ideal q = p on the priority anchors: the three exposed hard n8 cliques (original, __oracle4, __oracle5) then the two fresh ORACLE6 cliques (n6, n8), in that order); (2) the cap-only / moment-only G1
endpoints on those anchors; (3) the remaining eleven strong anchors + the fresh ER anchors in stable model-hash order (deduplicated) under the same laws. The oracle phase stops at its 1,200 s allocation: remaining planned entries stay
explicitly censored (recorded by the analyzer; never claimed). --continue reuses completed replays. usage: dgp6_oracle_driver.py --code-root ROOT [--records RD] [--phase construct|anchors1|anchors2|anchors3|all] [--cap-s 100] [--alloc 1200]"""
import sys, os, json, time, subprocess, argparse, hashlib
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP6_GLOBAL_CONSTRUCTION'; SUP_CODE = os.environ.get('PGM_CODE', '/Users/adis/Workspace/pgm/code'); PY = os.environ.get('PY', os.path.join(SUP_CODE, '.venv/bin/python')); CAFF = os.environ.get('CAFF', '/usr/bin/caffeinate')
PRIORITY_LAWS_1 = 'seed,G0_joint,G1_joint,ideal_q_eq_p'; PRIORITY_LAWS_2 = 'G1_cap_only,G1_moment_only'
def charged(ledger, scope): return sum(json.loads(l)['wall_s'] for l in open(ledger) if json.loads(l).get('kind') == 'RECEIPT' and json.loads(l).get('scope') == scope)
def run_one(rd, root, t, out_dir, ledger, cap, laws, phase, env, cont):
    out = os.path.join(out_dir, t['name'] + '.json'); job = 'dgp6:oracle:%s:%s' % (t['name'], phase)
    cmd = [PY, os.path.join(root, 'code/cex/hp/dgp6_oracle.py'), t['model'], out, '--cap-s', str(cap)] + (['--replay', '--replay-laws', laws] if laws else []) + (['--continue'] if cont else [])
    sup = [PY, '-m', 'gbidi.supervise', '--ledger', ledger, '--scope', 'dgp6_oracle', '--job', job, '--timeout', str(cap + 15), '--mem-gib', '3', '--interval', '0.05', '--cwd', os.path.join(root, 'code'), '--stdout', os.path.join(out_dir, '%s.%s.stdout.txt' % (t['name'], phase)), '--stderr', os.path.join(out_dir, '%s.%s.stderr.txt' % (t['name'], phase)), '--', CAFF, '-s'] + cmd
    subprocess.run(sup, cwd=SUP_CODE, env=env); r = json.load(open(out)) if os.path.exists(out) else {}
    print(json.dumps(dict(model=t['name'], phase=phase, cap=cap, wall=r.get('wall_s'), censored=r.get('censored'), constructions={k: v.get('status') for k, v in (r.get('constructions') or {}).items()}, replays={k: ('ok' if isinstance(v, dict) and v.get('caps') else (v.get('censored') or v.get('reason') or 'n/a')) for k, v in (r.get('replays') or {}).items()}), default=str), flush=True)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--code-root', required=True); ap.add_argument('--records', default=RD); ap.add_argument('--phase', default='all', choices=['construct', 'anchors1', 'anchors2', 'anchors3', 'all']); ap.add_argument('--cap-s', type=float, default=100.0); ap.add_argument('--alloc', type=float, default=1200.0); ap.add_argument('--only', default=None); a = ap.parse_args()
    rd = a.records; root = os.path.abspath(a.code_root); mm = json.load(open(os.path.join(rd, 'MODEL_MANIFEST.json'))); man = json.load(open(os.path.join(rd, 'ORACLE_MANIFEST.json')))['tasks']; by = {t['name']: t for t in man}; anchors = mm['panels']['replay_anchors']
    ledger = os.path.join(rd, 'DGP6_LEDGER.jsonl'); out_dir = os.path.join(rd, 'oracle', 'results'); os.makedirs(out_dir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); env.pop('PYTHONPATH', None)
    import dgp_paths
    for t in man: t['model'] = dgp_paths.resolve_input(t['model'], rd, t.get('model_sha256'))
    def left(): return a.alloc - charged(ledger, 'dgp6_oracle')
    def done(name, laws):
        p = os.path.join(out_dir, name + '.json')
        if not os.path.exists(p): return False
        d = json.load(open(p));
        if d.get('censored') or not d.get('constructions'): return False
        return all((k in (d.get('replays') or {}) and (d['replays'][k].get('caps') or d['replays'][k].get('not_available'))) for k in (laws.split(',') if laws else []))
    phases = []
    if a.phase in ('construct', 'all'): phases.append(('construct', [t['name'] for t in man if (not a.only or t['name'] in a.only.split(','))], None))
    if a.phase in ('anchors1', 'all'): phases.append(('anchors1', anchors['priority_5'], PRIORITY_LAWS_1))
    if a.phase in ('anchors2', 'all'): phases.append(('anchors2', anchors['priority_5'], PRIORITY_LAWS_2))
    if a.phase in ('anchors3', 'all'): phases.append(('anchors3', anchors['remaining_hash_order'], PRIORITY_LAWS_1 + ',' + PRIORITY_LAWS_2))
    for phase, names, laws in phases:
        for name in names:
            if name not in by: print('skip (not in the oracle manifest):', name); continue
            if phase == 'construct' and os.path.exists(os.path.join(out_dir, name + '.json')) and not json.load(open(os.path.join(out_dir, name + '.json'))).get('censored'): print('construct: complete output exists for', name); continue
            if phase != 'construct' and done(name, laws): print(phase, 'complete for', name); continue
            rem = left()
            if rem < 20: print('ORACLE ALLOWANCE EXHAUSTED (%.1f s left) before %s %s: the remaining planned entries stay censored' % (rem, phase, name)); return
            run_one(rd, root, by[name], out_dir, ledger, min(a.cap_s, rem), laws, phase, env, cont=(phase != 'construct'))
if __name__ == '__main__': main()
