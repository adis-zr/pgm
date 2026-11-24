"""development smoke of the unified PAC planner vs BASE on dev inputs (charged as one job); usage: dgp_dev_smoke.py OUTDIR names... [--budget 4.0 --hard 3.85 --work 3.5]"""
import sys, os, json, subprocess, argparse, time
CODE = '/Users/adis/Workspace/pgm/code'; PY = os.path.join(CODE, '.venv/bin/python'); DEV = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DENSE_GENERIC_PAC_INTEGRATION_1/dev/inputs'
ap = argparse.ArgumentParser(); ap.add_argument('outdir'); ap.add_argument('names', nargs='+'); ap.add_argument('--hard', type=float, default=3.85); ap.add_argument('--work', type=float, default=3.5); ap.add_argument('--arms', default='BASE,UPAC,FULL'); ap.add_argument('--inputs', default=None); a = ap.parse_args()
if a.inputs: DEV = a.inputs
os.makedirs(a.outdir, exist_ok=True); env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'); rows = []
for name in a.names:
    m = os.path.join(DEV, name + '.uai')
    for arm in a.arms.split(','):
        out = os.path.join(a.outdir, '%s__%s.json' % (name, arm))
        if arm == 'BASE': cmd = [PY, CODE + '/cex/blockres/integrated.py', '--input', m, '--output', out, '--budget', str(a.hard), '--mb-cap', str(1 << 24), '--table-cap', str(1 << 18), '--enum-cap', str(1 << 16), '--schedule', 'targeted', '--route', 'auto', '--proposal', 'mb', '--batch', '1024', '--seed', '1', '--epsilon', '1/200', '--delta', '1/1000000']
        else: cmd = [PY, CODE + '/cex/hp/unified_pac_planner.py', '--input', m, '--output', out, '--budget', str(a.hard), '--admission-stop', str(a.work), '--epsilon', '1/200', '--delta', '1/1000000', '--seed', '1'] + (['--lifted'] if arm == 'FULL' else [])
        t0 = time.time(); r = subprocess.run(cmd, cwd=CODE, env=env, capture_output=True, text=True); wall = time.time() - t0
        try: d = json.load(open(out)); mech = d.get('mechanism') or {}; row = dict(name=name, arm=arm, wall_s=round(wall, 3), outcome=d.get('outcome'), guarantee=d.get('guarantee'), published=d.get('published'), K=d.get('K'), route=mech.get('route'), termination=mech.get('termination'), streams=[(s['label'], s['stage'], s['draws'], s['published'], s.get('closed'), round(s.get('X_mean') or 0, 5), round(s.get('max_remaining_width') or 0, 4), s.get('mechanism', {}).get('cap_log2_total')) for s in d.get('streams', [])], base_mech={k: mech.get(k) for k in ('route', 'draws', 'published', 'remaining', 'max_remaining_width', 'X_mean', 'ESS', 'Kq', 'mb_splits')} if arm == 'BASE' else None, timing=d.get('cost_breakdown'), radius=(d.get('radius_report') or {}).get('worst'), E=mech.get('exploration_account_s'), E_used=mech.get('exploration_used_s'), conflicts=len(d.get('conflicts') or []), decisions=[x.get('chosen') for x in d.get('decisions', [])][:12], err=(r.stderr[-300:] if r.returncode else None))
        except Exception as e: row = dict(name=name, arm=arm, wall_s=round(wall, 3), outcome='NO_RESULT', err=(r.stderr[-600:] or repr(e)))
        rows.append(row); print(json.dumps(row, default=str)[:700], flush=True)
json.dump(rows, open(os.path.join(a.outdir, 'SMOKE.json'), 'w'), indent=1, default=str)
