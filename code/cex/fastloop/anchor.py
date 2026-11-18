"""R0 ANCHOR ONLY (labelled history for the panel initialization; a charged job): H1_HYBRID through the pac worker on the structural sentinels at the fast budgets. Usage: anchor.py --manifest DIR --baseline BUILD --out RUN_DIR"""
import os, sys, json, time, argparse, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); a = ap.parse_args()
M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); base = os.path.abspath(a.baseline); RUN = os.path.abspath(a.out); os.makedirs(RUN, exist_ok=True); L = os.path.join(RUN, 'CQR_LEDGER.jsonl'); PY = os.path.join(base, '.venv', 'bin', 'python'); out_rows = []; t0 = time.monotonic()
for r in [x for x in M['rows'] if x['block'] == 'structural_sentinel']:
    d = os.path.join(RUN, 'cells', r['id'] + '__anchor_R0__H1_HYBRID'); os.makedirs(d, exist_ok=True); out = os.path.join(d, 'worker.json'); b = r['budget_s']
    cmd = [PY, os.path.join(base, 'cex', 'pac', 'worker.py'), '--input', r['model'], '--output', out, '--arm', 'H1_HYBRID', '--deadline', str(time.monotonic() + b), '--budget', str(b), '--seed', 'cal', '--nonce', 'anchor-' + r['id']]
    sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_calibration', '--job', 'anchor:%s:H1_HYBRID' % r['id'], '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
    t = time.monotonic(); p = subprocess.run(sup, capture_output=True, text=True, cwd=base, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')); wall = time.monotonic() - t
    try: srec = json.loads(p.stderr.strip().splitlines()[-1])
    except Exception: srec = {}
    w = json.load(open(out)) if os.path.exists(out) else {}; rec = dict(id=r['id'], arm='H1_HYBRID', status=w.get('status', 'NO_OUTPUT'), outcome=w.get('outcome', 'NO_OUTPUT'), route=w.get('route'), wall_s=round(wall, 3), survivors=srec.get('survivors'), reason=(w.get('reason') or '')[:100])
    if w.get('outcome') == 'PUBLISHED' or w.get('status') == 'COMPLETED':
        tr = TR.truth_for(r['model'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=20.0); rec['truth'] = dict(status=tr['status'], method=tr.get('method'))
    out_rows.append(rec); print(json.dumps(rec), flush=True)
json.dump(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), baseline=base, elapsed_s=round(time.monotonic() - t0, 3), anchor=out_rows, note='R0 anchor via the pac worker (the first calibration run dispatched H1_HYBRID to the cqr worker: a HARNESS defect, recorded in calibration_1 as FAULT KeyError; corrected here)'), open(os.path.join(RUN, 'ANCHOR.json'), 'w'), indent=1)
