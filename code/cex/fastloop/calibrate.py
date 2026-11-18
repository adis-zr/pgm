"""ONE-TIME BASELINE CALIBRATION v2 (charged separately; cap 600 s): (1) R0 anchor (H1_HYBRID via the pac worker) on the structural sentinels at the fast budgets, labelled history;
(2) the change-specific SIZE LADDER on the accepted baseline: for every rung (every attempt RETAINED) measure (a) the PRODUCTION REFERENCE's completion time (reference.Reference run to the
end or to the row budget, in a bounded subprocess), (b) the N1 worker and its matched ablation at the row budget, (c) the independent elimination truth; the PIN RULE: the smallest rung
whose reference needs MORE than budget / 2 (exact completion not easy) AND whose N1 run shows the signed mechanism (epochs with draws) with EXACT truth available; none -> coverage gap
disclosed (never a hand-picked rung, never a loosened tolerance). Writes LADDER_CALIBRATION.json + LADDER_PIN.json beside the manifest (the manifest file is never edited).
Usage: calibrate.py --manifest DIR --baseline BUILD --out RUN_DIR [--cap 600]"""
import os, sys, json, time, argparse, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
def pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
_REF = r'''
import sys, time, json, os; mp, build, cap = sys.argv[1], sys.argv[2], float(sys.argv[3]); sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); sys.path.insert(0, os.path.join(build, 'cex', 'newarm'))
import task as TK, reference as RF; t = TK.load_task(mp); ref = RF.Reference(t['model'], t['queries'], TK.Work()); t0 = time.monotonic()
while not ref.done and time.monotonic() - t0 < cap: ref.step(4096)
print(json.dumps(dict(total=ref.total, done=ref.done, elapsed_s=round(time.monotonic() - t0, 3), progress=ref.progress())))
'''
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); ap.add_argument('--cap', type=float, default=600.0); a = ap.parse_args()
    T0 = time.monotonic(); M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); base = os.path.abspath(a.baseline); RUN = os.path.abspath(a.out); os.makedirs(RUN, exist_ok=True); L = os.path.join(RUN, 'CQR_LEDGER.jsonl'); PY = pybin(base)
    def left(): return a.cap - (time.monotonic() - T0)
    def cell(r, arm, tag):
        d = os.path.join(RUN, 'cells', '%s__%s__%s' % (r['id'], tag, arm)); os.makedirs(d, exist_ok=True); out = os.path.join(d, 'worker.json'); b = r['budget_s']
        if left() < b + 10: return dict(id=r['id'], arm=arm, tag=tag, status='NOT_RUN', outcome='NOT_RUN', reason='calibration cap', wall_s=0.0)
        wk = os.path.join(base, 'cex', 'pac' if arm in ('H1_HYBRID', 'P1_PAC_CONDITIONAL', 'A0_POINT', 'A1_CONDITIONAL') else 'cqr', 'worker.py')
        cmd = [PY, wk, '--input', r['model'], '--output', out, '--arm', arm, '--deadline', str(time.monotonic() + b), '--budget', str(b), '--seed', 'cal', '--nonce', 'cal-%s-%s' % (r['id'], arm)]
        sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_calibration', '--job', 'cal:%s:%s:%s' % (r['id'], tag, arm), '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
        t = time.monotonic()
        try: p = subprocess.run(sup, capture_output=True, text=True, cwd=base, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'), timeout=b + 25); serr = p.stderr
        except subprocess.TimeoutExpired: serr = ''
        wall = time.monotonic() - t
        try: srec = json.loads(serr.strip().splitlines()[-1])
        except Exception: srec = {}
        w = json.load(open(out)) if os.path.exists(out) else {}; c = w.get('certificate') or {}
        rec = dict(id=r['id'], arm=arm, tag=tag, status=('TIMEOUT_KILL' if srec.get('outcome') == 'TIMEOUT_KILL' else w.get('status', 'NO_OUTPUT')), outcome=('DEADLINE' if srec.get('outcome') == 'TIMEOUT_KILL' else w.get('outcome', 'NO_OUTPUT')), route=w.get('route'), guarantee=w.get('guarantee_type'), wall_s=round(wall, 3), worker_json=(os.path.relpath(out, RUN) if os.path.exists(out) else None),
                   ratio_draws=(c.get('ratio_stream') or {}).get('t'), signed_epochs=[e.get('t') for e in (c.get('epochs') or [])], commits=[s_.get('op') for s_ in ((c.get('compile') or {}).get('log') or {}).get('steps', []) if s_.get('committed')], structural=[(x.get('representation'), x.get('decision')) for x in (c.get('structural') or {}).get('attempts', [])], survivors=srec.get('survivors'), supervisor_outcome=srec.get('outcome'))
        tr = TR.truth_for(r['model'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=min(30.0, max(2.0, left() - 5)))              # the independent truth of the TASK (exists whether or not the worker published)
        rec['truth'] = dict(status=tr['status'], method=tr.get('method'), verdict=((TR.containment(w, tr) if w.get('outcome') == 'PUBLISHED' else TR.zero_claim_check(tr) if w.get('outcome') == 'PROVED_ZERO_EVIDENCE' else 'NA')), prep_s=tr.get('prep_s'), cache_hit=tr.get('cache_hit'))
        return rec
    def reference_time(r):
        cap = min(r['budget_s'], max(1.0, left() - 5))
        try: p = subprocess.run([PY, '-c', _REF, r['model'], base, str(cap)], capture_output=True, text=True, timeout=cap + 10, cwd=base); return json.loads(p.stdout.strip().splitlines()[-1])
        except Exception as ex: return dict(error='%s: %s' % (type(ex).__name__, str(ex)[:80]))
    out = dict(schema='CQR_FASTLOOP_CALIBRATION_V2', baseline=base, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), anchor=[], ladder=[], note='R0 anchor cells are labelled history for the panel initialization, never a fresh matched comparison inside an iteration; every ladder attempt and its production-reference timing is retained')
    for r in [x for x in M['rows'] if x['block'] == 'structural_sentinel']: out['anchor'].append(cell(r, 'H1_HYBRID', 'anchor_R0'))
    ladder = sorted([x for x in M['rows'] if x['block'] == 'change_specific_ladder'], key=lambda x: (x['regime'], x['ladder_rung'])); pinned = {}
    for r in ladder:
        if r['regime'] in pinned: out['ladder'].append(dict(id=r['id'], status='NOT_RUN', reason='rung above the pinned one for %s' % r['regime'])); continue
        rt = reference_time(r); c1 = cell(r, r['candidate_arm'], 'baseline_N1'); c2 = cell(r, r['comparator']['arm'], 'baseline_ablation')
        easy_exact = bool(rt.get('done')) and rt.get('elapsed_s', 0) <= r['budget_s'] / 2
        signed_active = sum(int(t_ or 0) for t_ in (c1.get('signed_epochs') or [])) > 0; c1['signed_source'] = 'certificate' if signed_active else None
        if not signed_active and c1.get('worker_json'):                                   # a DEADLINE has no certificate: the SIDECAR's observed epochs decide fixture selection (diagnostic, labelled)
            sp = os.path.join(RUN, c1['worker_json'])[:-5] + '.diag.json'
            if os.path.exists(sp):
                try: ep_obs = (json.load(open(sp)).get('streams') or {}).get('signed_epochs') or []; signed_active = sum(int(e.get('draws') or 0) for e in ep_obs) > 0; c1['signed_source'] = 'sidecar (observed, diagnostic)' if signed_active else None; c1['signed_epochs_observed'] = [e.get('draws') for e in ep_obs]
                except Exception: pass
        truth_exact = (c1.get('truth') or {}).get('status') == 'EXACT'
        c1.update(reference=rt, exact_completion_easy=easy_exact, signed_mechanism_active=signed_active, truth_exact=truth_exact, qualifies=(not easy_exact and signed_active and truth_exact and c1['status'] not in ('NOT_RUN', 'NO_OUTPUT')))
        out['ladder'] += [c1, c2]
        if c1['qualifies']: pinned[r['regime']] = r['id']
    out['pinned_ids'] = sorted(pinned.values()); out['pinned'] = pinned; out['coverage_gap'] = [reg for reg in ('favorable', 'near_miss') if reg not in pinned]; out['elapsed_s'] = round(time.monotonic() - T0, 3); out['within_cap'] = out['elapsed_s'] <= a.cap
    json.dump(out, open(os.path.join(a.manifest, 'LADDER_CALIBRATION.json'), 'w'), indent=1, default=str)
    json.dump(dict(pinned_ids=out['pinned_ids'], pinned=pinned, rule=M.get('ladder_pin_rule'), from_calibration=os.path.join(a.manifest, 'LADDER_CALIBRATION.json'), coverage_gap=out['coverage_gap'], utc=out['utc']), open(os.path.join(a.manifest, 'LADDER_PIN.json'), 'w'), indent=1)
    json.dump(out, open(os.path.join(RUN, 'CALIBRATION.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(elapsed_s=out['elapsed_s'], pinned=pinned, coverage_gap=out['coverage_gap'], anchor=[(x['id'], x['outcome'], x['wall_s']) for x in out['anchor']], ladder=[(x['id'], x.get('arm'), x.get('outcome'), x.get('route'), x.get('wall_s'), (x.get('reference') or {}).get('elapsed_s'), (x.get('reference') or {}).get('done'), x.get('signed_mechanism_active'), x.get('qualifies')) for x in out['ladder'] if x.get('arm') == 'N1_CQR'])))
if __name__ == '__main__': main()
