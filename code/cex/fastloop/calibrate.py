"""ONE-TIME BASELINE CALIBRATION (charged separately; cap 600 s; NOT a steady-state iteration): on the ACCEPTED baseline build, (1) the R0 anchor (H1_HYBRID) on the four structural
sentinels at the fast budgets, labelled ANCHOR; (2) the change-specific SIZE LADDER (M10 favorable / near_miss x rungs) on N1 and its matched ablation at 15 s: every attempt retained,
the pin rule applied (smallest rung beyond trivial exact completion with EXACT independent truth); (3) writes LADDER_CALIBRATION.json + LADDER_PIN.json into the manifest dir (the
manifest file is never edited). Usage: calibrate.py --manifest DIR --baseline BUILD --out RUN_DIR [--cap 600]"""
import os, sys, json, time, argparse, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
EXACT = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional')
def pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); ap.add_argument('--cap', type=float, default=600.0); a = ap.parse_args()
    T0 = time.monotonic(); M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); base = os.path.abspath(a.baseline); RUN = os.path.abspath(a.out); os.makedirs(RUN, exist_ok=True); L = os.path.join(RUN, 'CQR_LEDGER.jsonl'); PY = pybin(base)
    def left(): return a.cap - (time.monotonic() - T0)
    def cell(r, arm, tag):
        d = os.path.join(RUN, 'cells', '%s__%s__%s' % (r['id'], tag, arm)); os.makedirs(d, exist_ok=True); out = os.path.join(d, 'worker.json'); b = r['budget_s']
        if left() < b + 8: return dict(id=r['id'], arm=arm, tag=tag, status='NOT_RUN', reason='calibration cap', wall_s=0.0)
        wk = os.path.join(base, 'cex', 'pac', 'worker.py') if arm in ('H1_HYBRID', 'P1_PAC_CONDITIONAL', 'A0_POINT', 'A1_CONDITIONAL') else os.path.join(base, 'cex', 'cqr', 'worker.py')      # the R0 anchor is a pac arm: dispatched EXACTLY as the campaign dispatcher does
        cmd = [PY, wk, '--input', r['model'], '--output', out, '--arm', arm, '--deadline', str(time.monotonic() + b), '--budget', str(b), '--seed', 'cal', '--nonce', 'cal-%s-%s' % (r['id'], arm)]
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_calibration', '--job', 'cal:%s:%s:%s' % (r['id'], tag, arm), '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
        t = time.monotonic(); p = subprocess.run(sup, capture_output=True, text=True, cwd=base, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')); wall = time.monotonic() - t
        try: srec = json.loads(p.stderr.strip().splitlines()[-1])
        except Exception: srec = {}
        w = json.load(open(out)) if os.path.exists(out) else {}; c = w.get('certificate') or {}
        rec = dict(id=r['id'], arm=arm, tag=tag, status=('TIMEOUT_KILL' if srec.get('outcome') == 'TIMEOUT_KILL' else w.get('status', 'NO_OUTPUT')), outcome=('DEADLINE' if srec.get('outcome') == 'TIMEOUT_KILL' else w.get('outcome', 'NO_OUTPUT')), route=w.get('route'), guarantee=w.get('guarantee_type'), wall_s=round(wall, 3), worker_json=os.path.relpath(out, RUN) if os.path.exists(out) else None,
                   ratio_draws=(c.get('ratio_stream') or {}).get('t'), signed_epochs=len(c.get('epochs') or []), commits=[s_.get('op') for s_ in ((c.get('compile') or {}).get('log') or {}).get('steps', []) if s_.get('committed')], structural=[(x.get('representation'), x.get('decision')) for x in (c.get('structural') or {}).get('attempts', [])], frontier_open=(c.get('frontier') or {}).get('open_cells') if c.get('frontier') else None, survivors=srec.get('survivors'))
        if w.get('outcome') == 'PUBLISHED':
            tr = TR.truth_for(r['model'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=min(30.0, max(2.0, left() - 2))); rec['truth'] = dict(status=tr['status'], method=tr.get('method'), containment=TR.containment(w, tr), prep_s=tr.get('prep_s'))
        return rec
    out = dict(schema='CQR_FASTLOOP_CALIBRATION_V1', baseline=base, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), anchor=[], ladder=[], note='R0 anchor cells are labelled history for the panel initialization, never a fresh matched comparison inside an iteration; the ladder attempts are retained in full')
    for r in [x for x in M['rows'] if x['block'] == 'structural_sentinel']: out['anchor'].append(cell(r, 'H1_HYBRID', 'anchor_R0'))
    ladder = sorted([x for x in M['rows'] if x['block'] == 'change_specific_ladder'], key=lambda x: (x['regime'], x['ladder_rung'])); pinned = {}
    for r in ladder:
        if r['regime'] in pinned: out['ladder'].append(dict(id=r['id'], status='NOT_RUN', reason='rung above the pinned one for %s' % r['regime'])); continue
        c1 = cell(r, r['candidate_arm'], 'baseline_N1'); c2 = cell(r, r['comparator']['arm'], 'baseline_ablation'); out['ladder'] += [c1, c2]
        beyond = c1['outcome'] == 'PUBLISHED' and c1['route'] not in EXACT and not str(c1['route'] or '').startswith('structural') or (c1['outcome'] == 'DEADLINE' and (c1.get('ratio_draws') or c1.get('signed_epochs') or c1.get('frontier_open')))
        exact_truth = (c1.get('truth') or {}).get('status') == 'EXACT' if c1['outcome'] == 'PUBLISHED' else True
        c1['beyond_trivial_exact'] = bool(beyond); c1['truth_exact'] = exact_truth
        if beyond and exact_truth and c1['status'] not in ('NOT_RUN', 'NO_OUTPUT'): pinned[r['regime']] = r['id']
    out['pinned_ids'] = sorted(pinned.values()); out['pinned'] = pinned; out['elapsed_s'] = round(time.monotonic() - T0, 3); out['within_cap'] = out['elapsed_s'] <= a.cap
    out['coverage_gap'] = [reg for reg in ('favorable', 'near_miss') if reg not in pinned]
    json.dump(out, open(os.path.join(a.manifest, 'LADDER_CALIBRATION.json'), 'w'), indent=1, default=str)
    json.dump(dict(pinned_ids=out['pinned_ids'], pinned=pinned, rule=M.get('ladder_pin_rule'), from_calibration=os.path.join(a.manifest, 'LADDER_CALIBRATION.json'), coverage_gap=out['coverage_gap'], utc=out['utc']), open(os.path.join(a.manifest, 'LADDER_PIN.json'), 'w'), indent=1)
    json.dump(out, open(os.path.join(RUN, 'CALIBRATION.json'), 'w'), indent=1, default=str); print(json.dumps(dict(elapsed_s=out['elapsed_s'], pinned=pinned, coverage_gap=out['coverage_gap'], anchor=[(x['id'], x['outcome'], x.get('route'), x['wall_s']) for x in out['anchor']], ladder=[(x['id'], x['arm'], x['outcome'], x.get('route'), x['wall_s'], x.get('signed_epochs'), x.get('ratio_draws')) for x in out['ladder'] if x.get('arm')])))
if __name__ == '__main__': main()
