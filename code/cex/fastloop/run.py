"""FAST LOOP RUNNER: executes the pinned development manifest (smoke subset or full) against a CANDIDATE build and ONE comparator per row, under one global wall cap. Every worker is a
supervised child (gbidi.supervise of the candidate build: hard-kill grace, process-group reaping, receipts in RUN/CQR_LEDGER.jsonl); every publication is verified by the producing build's
OWN checker (source-isolated subprocess) and against INDEPENDENT cached truth; activation evidence is read from the certificate and the sidecar. Budget exhaustion / missing results /
hard kills / refused honest publications are VISIBLE and make the run INCOMPLETE or STOP; nothing incomplete is ever PASS.
Usage: run.py --manifest DIR --candidate BUILD --baseline BUILD --out RUN_DIR --mode smoke|full [--hypothesis FILE.json] [--total-cap 300] [--rows ID,ID] [--inject-missing-output ID] [--inject-corrupt ID] [--label TEXT]"""
import os, sys, json, time, argparse, subprocess, hashlib, shutil, copy
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import truth as TR, report as RP
from __init__ import FASTLOOP_VERSION
GRACE_S = 5.0; VERIFY_S = 20.0; TRUTH_S = 30.0
def sha(p): return TR.sha_file(p)
def git(d, *a): return subprocess.run(['git', '-C', d, *a], capture_output=True, text=True).stdout.strip()
def identity(build):
    p = subprocess.run([os.path.join(build, '.venv', 'bin', 'python') if os.path.exists(os.path.join(build, '.venv', 'bin', 'python')) else sys.executable, '-c', "import sys, json, hashlib; sys.path.insert(0, %r); import registry as R; inv = R.full_inventory(%r); cqr = R.cqr_source_inventory(%r); print(json.dumps(dict(full_inventory_sha256=hashlib.sha256(json.dumps(inv, sort_keys=True).encode()).hexdigest(), artifacts=len(inv), cqr_scope_sha256=hashlib.sha256(json.dumps(cqr, sort_keys=True).encode()).hexdigest(), cqr_files=len(cqr))))" % (os.path.join(build, 'cex', 'cqr'), build, build)], capture_output=True, text=True)
    d = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else dict(error=p.stderr[-300:])
    d.update(build=build, git_head=git(build, 'rev-parse', 'HEAD'), git_branch=git(build, 'branch', '--show-current') or 'DETACHED', tracked_clean=(git(build, 'status', '--porcelain', '--untracked-files=no') == '')); return d
def _shift(wc):
    """a detectable corruption of a publication COPY: the first answer's lo / hi / point and the certificate's publication bounds / point are moved by +1/97 (clipped to 1)"""
    a0 = wc['answers'][0]; v = str(min(F(1), F(a0['point']) + F(1, 97))); a0['lo'] = a0['hi'] = a0['point'] = v
    pub = wc['certificate']['publication']; pub['bounds'][0] = [v, v]
    if isinstance(pub.get('point'), list): pub['point'][0] = v
    return wc
def pybin(build): return os.path.join(build, '.venv', 'bin', 'python') if os.path.exists(os.path.join(build, '.venv', 'bin', 'python')) else sys.executable

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--candidate', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); ap.add_argument('--mode', choices=['smoke', 'full'], default='full')
    ap.add_argument('--hypothesis', default=None); ap.add_argument('--total-cap', type=float, default=300.0); ap.add_argument('--rows', default=None); ap.add_argument('--inject-missing-output', default=None); ap.add_argument('--inject-corrupt', default=None); ap.add_argument('--label', default=''); ap.add_argument('--seed', default='fl')
    a = ap.parse_args(); T0 = time.monotonic(); t_wall0 = time.time(); RUN = os.path.abspath(a.out)
    if os.path.exists(os.path.join(RUN, 'ITERATION_REPORT.json')): raise SystemExit('refuse: %s already holds a report (runs are immutable)' % RUN)
    os.makedirs(RUN, exist_ok=True); M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); cand, base = os.path.abspath(a.candidate), os.path.abspath(a.baseline)
    pin_p = os.path.join(a.manifest, 'LADDER_PIN.json'); pin = json.load(open(pin_p)) if os.path.exists(pin_p) else None
    for r in M['rows']:
        if r['block'] == 'change_specific_ladder': r['pinned'] = bool(pin) and r['id'] in (pin.get('pinned_ids') or [])
    hyp = json.load(open(a.hypothesis)) if a.hypothesis else dict(change='(none declared: regression / calibration run)', premise=None, expected_favorable=None, expected_near_miss=None, preserved=['every exact / structured sentinel and contract row publishes and verifies as on the accepted baseline'], question=None)
    ids = dict(candidate=identity(cand), baseline=identity(base), harness=dict(version=FASTLOOP_VERSION, files={f: sha(os.path.join(HERE, f)) for f in sorted(os.listdir(HERE)) if f.endswith('.py')}), manifest_sha256=sha(os.path.join(a.manifest, 'DEV_MANIFEST.json')), ladder_pin=(pin or {'status': 'NOT PINNED (calibrate.py has not run): change-specific rows NOT RUN'}))
    stop = None; L = os.path.join(RUN, 'CQR_LEDGER.jsonl'); rows_sel = [r for r in M['rows'] if (r['id'] in M['smoke_rows'] if a.mode == 'smoke' else (r['block'] != 'change_specific_ladder' or r.get('pinned')))]
    if a.rows: want = set(a.rows.split(',')); rows_sel = [r for r in M['rows'] if r['id'] in want]
    nominal = sum(r['budget_s'] * (2 if r.get('comparator') else 0) for r in rows_sel) + sum(r['budget_s'] for r in rows_sel if not r.get('comparator'))
    plan = dict(mode=a.mode, rows=[r['id'] for r in rows_sel], worker_nominal_s=nominal, cap_s=a.total_cap, allocations=M['allocations'], within_worker_cap=(nominal <= M['allocations']['worker_nominal_s_cap'] + 10))
    def left(): return a.total_cap - (time.monotonic() - T0)
    def launch(build, arm, r, tag, order_i):
        """ONE supervised fresh worker of `build` on the pinned task; returns the cell record"""
        d = os.path.join(RUN, 'cells', '%02d_%s__%s__%s' % (order_i, r['id'], tag, arm)); os.makedirs(d, exist_ok=True); out = os.path.join(d, 'worker.json'); b = r['budget_s']
        if left() < b + GRACE_S + 2.0: return dict(id=r['id'], tag=tag, arm=arm, build=build, status='NOT_RUN', outcome='NOT_RUN', reason='global cap: %.1f s left < budget %.0f s + grace' % (left(), b), wall_s=0.0, dir=d)
        PY = pybin(build); dl = time.monotonic() + b                                              # the worker's deadline is launch-relative like the campaign's
        if a.inject_missing_output == r['id'] and tag == 'candidate': cmd = [PY, '-c', 'import time; time.sleep(0.2)']        # HARNESS CONTROL: a child that exits without writing (no solver change)
        else: cmd = [PY, os.path.join(build, 'cex', 'cqr', 'worker.py'), '--input', r['model'], '--output', out, '--arm', arm, '--deadline', str(dl), '--budget', str(b), '--seed', a.seed, '--nonce', '%s-%s-%s' % (r['id'], tag, arm)]
        job = 'cell:%s:%s:%s' % (r['id'], tag, arm); sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_' + a.mode, '--job', job, '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
        t = time.monotonic(); p = subprocess.run(sup, capture_output=True, text=True, cwd=build, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')); wall = time.monotonic() - t
        try: srec = json.loads(p.stderr.strip().splitlines()[-1])
        except Exception: srec = dict(parse_error=p.stderr[-300:])
        w = json.load(open(out)) if os.path.exists(out) else {}
        status = w.get('status', 'NO_OUTPUT'); outcome = w.get('outcome', 'NO_OUTPUT')
        if srec.get('outcome') == 'TIMEOUT_KILL': status, outcome = 'TIMEOUT_KILL', 'DEADLINE'
        if srec.get('outcome') == 'MEMORY_KILL': status, outcome = 'MEMORY_KILL', 'MEMORY'
        if status == 'COMPLETED' and wall > b + 0.05: status, outcome = 'LATE_OUTPUT', 'DEADLINE'
        if a.inject_corrupt == r['id'] and tag == 'candidate' and w.get('outcome') == 'PUBLISHED':                   # HARNESS CONTROL: the verified copy is corrupted (first answer shifted by 1/97, certificate publication shifted alike); the honest file is kept beside it
            wc = copy.deepcopy(w); wc = _shift(wc); out = os.path.join(d, 'worker_CORRUPTED_BY_HARNESS.json'); json.dump(wc, open(out, 'w'), default=str); w = wc
        dg = out[:-5] + '.diag.json' if os.path.exists(out[:-5] + '.diag.json') else (os.path.join(d, 'worker.diag.json') if os.path.exists(os.path.join(d, 'worker.diag.json')) else None)
        return dict(id=r['id'], tag=tag, arm=arm, build=build, status=status, outcome=outcome, route=w.get('route'), guarantee=w.get('guarantee_type'), reason=(w.get('reason') or '')[:160], wall_s=round(wall, 3), worker_elapsed_s=w.get('worker_elapsed_s'), peak_rss_mb=(round((w.get('peak_rss_bytes') or 0) / 1e6, 1) if w else None), supervisor=dict(outcome=srec.get('outcome'), survivors=srec.get('survivors'), wall_s=srec.get('wall_s'), peak_MB=srec.get('peak_MB')), worker_json=(os.path.relpath(out, RUN) if os.path.exists(out) else None), sidecar=(os.path.relpath(dg, RUN) if dg else None), dir=os.path.relpath(d, RUN), answers=w.get('answers'), bias=w.get('bias'), cert=(w.get('certificate') or {}), seed=a.seed)
    def verify(cell, r):
        """the producing build's OWN checker (subprocess) + independent truth; fills cell['check'], cell['truth']"""
        if cell['status'] in ('NOT_RUN',) or not cell.get('worker_json'): cell['check'] = dict(status='NOT_RUN' if cell['status'] == 'NOT_RUN' else 'NO_OUTPUT'); cell['truth'] = dict(status='NA'); return
        if cell['outcome'] != 'PUBLISHED': cell['check'] = dict(status='NA (not a publication)'); cell['truth'] = dict(status='NA'); return
        if left() < 3.0: cell['check'] = dict(status='NOT_RUN', reason='global cap exhausted before verification'); cell['truth'] = dict(status='NOT_RUN'); return
        outp = os.path.join(RUN, cell['dir'], 'check.json'); t = time.monotonic(); dl = max(2.0, min(VERIFY_S, left() - 2.0))
        p = subprocess.run([pybin(cell['build']), os.path.join(HERE, 'check_cli.py'), cell['build'], r['model'], os.path.join(RUN, cell['worker_json']), cell['arm'], str(dl), outp], capture_output=True, text=True, cwd=cell['build'], timeout=dl + 10)
        ck = json.load(open(outp)) if os.path.exists(outp) else dict(fails=['checker subprocess produced no result: ' + p.stderr[-200:]], checker_s=None)
        ck['status'] = 'ACCEPTED' if not ck.get('fails') else 'REFUSED'; ck['harness_wall_s'] = round(time.monotonic() - t, 3); cell['check'] = ck
        try: rec = TR.truth_for(r['model'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=min(TRUTH_S, max(2.0, left() - 2.0)))
        except Exception as ex: rec = dict(status='UNRESOLVED', reason='oracle error %s: %s' % (type(ex).__name__, str(ex)[:120]), prep_s=None, method=None)
        cont = TR.containment(dict(outcome=cell['outcome'], answers=cell.get('answers')), rec)
        cell['truth'] = dict(status=rec['status'], method=rec.get('method'), prep_s=rec.get('prep_s'), cache_hit=rec.get('cache_hit'), containment=cont, truth_answers=(rec.get('answers') or [rec.get('Z')])[:4] if rec['status'] == 'EXACT' else None, reason=rec.get('reason'))
        if cont == 'MISS' and cell.get('guarantee') in ('DETERMINISTIC',) : cell['hard_failure'] = 'deterministic / exact publication misses the independent truth'
        if cont == 'MISS' and cell.get('guarantee') == 'PAC': cell['pac_miss'] = 'PAC publication outside the truth: preserved for investigation under the statistical contract (not a soundness verdict by itself)'
        if ck['status'] == 'REFUSED': cell['hard_failure'] = (cell.get('hard_failure') or '') + '; publication REFUSED by its own checker: %s' % (ck['fails'] or [''])[0][:120]
    def activation(cell):
        """mechanism evidence read from the CERTIFICATE (authoritative) and the sidecar (diagnostic, labelled)"""
        c = cell.get('cert') or {}; st = c.get('structural') or {}; cl = ((c.get('compile') or {}).get('log') or {}); steps = cl.get('steps') or []
        ev = dict(structural_attempts=[(x.get('representation'), x.get('decision'), x.get('which')) for x in st.get('attempts', [])], compile_commits=[s.get('op') for s in steps if s.get('committed')], compile_declines=[(s.get('op'), (s.get('reason') or '')[:60]) for s in steps if s.get('committed') is False and s.get('reason')], compile_quota=cl.get('quota'),
                  bias=cell.get('bias'), ratio_draws=((c.get('ratio_stream') or {}).get('t')), signed_epochs=len(c.get('epochs') or []), frontier=({k: (c.get('frontier') or {}).get(k) for k in ('open_cells', 'resolved_cells', 'splits', 'closures')} if c.get('frontier') else None),
                  work=({k: (v.get('total') if isinstance(v, dict) else v) for k, v in (c.get('work') or {}).items()} if c.get('work') else None), reference=({k: (c.get('reference') or {}).get(k) for k in ('done', 'progress', 'assignments_done', 'assignments_total', 'steps')} if c.get('reference') else None), scheduling=(c.get('scheduling') or {}).get('expired_requests') if isinstance(c.get('scheduling'), dict) else None)
        sc_p = os.path.join(RUN, cell['sidecar']) if cell.get('sidecar') else None
        if sc_p and os.path.exists(sc_p):
            s = json.load(open(sc_p)); fr = s.get('frontier') or {}; le = fr.get('last_enclosure') if isinstance(fr, dict) else None
            ev['sidecar'] = dict(phase_at_end=s.get('phase'), phase_times_s=s.get('phase_times_s'), overhead_s=s.get('overhead_s'), freshness=s.get('freshness'), stream=(s.get('streams') or {}).get('ratio'), signed_epochs_ring=len((s.get('streams') or {}).get('signed_epochs') or []),
                                 last_enclosure_DIAGNOSTIC=({k: le.get(k) for k in ('elapsed_s', 'queries', 'max_width', 'median_width', 'undefined')} if isinstance(le, dict) else le), note='frontier.last_enclosure is the COMPILED-model enclosure BEFORE original-query bias widening (float summary / top 8): a diagnostic width, NOT a certified original-task error; only the verified publication is authoritative')
        cell['activation'] = ev; cell.pop('cert', None)
    cells = []; order_i = 0; hard = []
    for i, r in enumerate(rows_sel):
        comp = r.get('comparator'); arms = [('candidate', cand, r['candidate_arm'])] + ([('comparator', (base if comp['kind'] == 'baseline_N1' else cand), comp['arm'])] if comp else [])
        if i % 2 == 1 and len(arms) == 2: arms = arms[::-1]                                     # deterministic BALANCED arm order (alternates by row index)
        for tag, build, arm in arms:
            order_i += 1; cell = launch(build, arm, r, tag, order_i); cell['comparator_kind'] = (comp or {}).get('kind') if tag == 'comparator' else None; verify(cell, r); activation(cell); cells.append(cell)
            if (cell.get('supervisor') or {}).get('survivors'): cell['hard_failure'] = (cell.get('hard_failure') or '') + '; supervisor reported live survivors'
            if r.get('expected_outcome') and tag == 'candidate' and cell['status'] not in ('NOT_RUN',) and cell['outcome'] != r['expected_outcome']: cell['hard_failure'] = (cell.get('hard_failure') or '') + '; control expectation violated: expected %s, observed %s' % (r['expected_outcome'], cell['outcome'])
            if r['id'] == 'FL_CTL_zero_mass' and tag == 'candidate' and cell['outcome'] == 'PUBLISHED' and not all(a.get('lo') == a.get('hi') == '0' for a in (cell.get('answers') or [])): cell['hard_failure'] = (cell.get('hard_failure') or '') + '; zero-mass control published a nonzero answer'
            if cell.get('hard_failure'): hard.append((cell['id'], cell['tag'], cell['hard_failure'])); stop = 'STOP: %s / %s: %s' % (cell['id'], cell['tag'], cell['hard_failure'])
            if stop: break
        if stop: break
    if stop:
        done = {(c['id'], c['tag']) for c in cells}
        for r in rows_sel:
            for tag in (['candidate'] + (['comparator'] if r.get('comparator') else [])):
                if (r['id'], tag) not in done: cells.append(dict(id=r['id'], tag=tag, arm=(r['candidate_arm'] if tag == 'candidate' else r['comparator']['arm']), status='NOT_RUN', outcome='NOT_RUN', reason='stopped after a hard failure', wall_s=0.0, check=dict(status='NOT_RUN'), truth=dict(status='NA'), activation={}))
    # ---------------- mutation controls on the first honest candidate publication of the smoke set (checker must REFUSE each; copies only)
    muts = []
    hon = next((c for cid in ('FL_C35_mixed_alias', 'FL_SENT_ASIA') for c in cells if c['id'] == cid and c['tag'] == 'candidate' and c['outcome'] == 'PUBLISHED' and (c.get('check') or {}).get('status') == 'ACCEPTED'), None)
    if hon and left() > 12.0:
        r = next(x for x in rows_sel if x['id'] == hon['id']); w = json.load(open(os.path.join(RUN, hon['worker_json']))); md = os.path.join(RUN, 'mutations'); os.makedirs(md, exist_ok=True)
        def refuse(name, wm, model_path, needle):
            wp = os.path.join(md, name + '.json'); json.dump(wm, open(wp, 'w'), default=str); outp = os.path.join(md, name + '.check.json')
            subprocess.run([pybin(cand), os.path.join(HERE, 'check_cli.py'), cand, model_path, wp, hon['arm'], '8', outp], capture_output=True, text=True, cwd=cand, timeout=20)
            ck = json.load(open(outp)) if os.path.exists(outp) else dict(fails=['no result'])
            ok = bool(ck.get('fails')) and any(needle in f_ for f_ in ck['fails']); muts.append(dict(name=name, refused=bool(ck.get('fails')), intended_reason=ok, first=(ck.get('fails') or [''])[0][:120]))
        refuse('answer_shifted_by_1_97', _shift(copy.deepcopy(w)), r['model'], '')
        w2 = copy.deepcopy(w); w2['guarantee_type'] = 'PAC'; w2['certificate']['publication']['guarantee'] = 'PAC'; refuse('guarantee_relabelled', w2, r['model'], 'class')
        if hon['id'] == 'FL_C35_mixed_alias':                                                        # label swapped to a DIFFERENT denotation in a COPY of the task dir -> binding / semantics refuse
            td = os.path.join(md, 'label_swap_task'); shutil.copytree(os.path.dirname(r['model']), td); mp2 = os.path.join(td, os.path.basename(r['model'])); q = json.load(open(mp2 + '.query.json')); q['queries'][0] = dict(kind='joint', assign={'0': 0}); json.dump(q, open(mp2 + '.query.json', 'w')); refuse('label_swapped_to_other_denotation', copy.deepcopy(w), mp2, '')
    # ---------------- status
    elapsed = time.monotonic() - T0; not_run = [c for c in cells if c['status'] == 'NOT_RUN']; no_out = [c for c in cells if c['status'] == 'NO_OUTPUT']; unverified = [c for c in cells if c['outcome'] == 'PUBLISHED' and (c.get('check') or {}).get('status') not in ('ACCEPTED', 'REFUSED')]
    status = 'STOP' if stop else ('INCOMPLETE' if (not_run or no_out or unverified or elapsed > a.total_cap or (muts and not all(m['refused'] for m in muts)) or (hon is None and a.mode == 'smoke')) else 'COMPLETE')
    rec = dict(schema='CQR_FASTLOOP_ITERATION_V1', harness=FASTLOOP_VERSION, label=a.label, utc_start=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_wall0)), status=status, stop_reason=stop, hard_failures=hard, elapsed_s=round(elapsed, 3), cap_s=a.total_cap, within_cap=(elapsed <= a.total_cap), plan=plan, hypothesis=hyp, identities=ids,
               cells=cells, mutation_controls=muts, not_run=[(c['id'], c['tag'], c.get('reason')) for c in not_run], no_output=[(c['id'], c['tag']) for c in no_out], unverified_publications=[(c['id'], c['tag']) for c in unverified],
               harness_controls=dict(inject_missing_output=a.inject_missing_output, inject_corrupt=a.inject_corrupt), host=dict(node=os.uname().nodename, load_avg_1m=os.getloadavg()[0]),
               charges=dict(cell_receipts=sum(1 for l in open(L) if '"RECEIPT"' in l) if os.path.exists(L) else 0, cell_wall_s=round(sum(json.loads(l)['wall_s'] for l in open(L) if '"kind": "RECEIPT"' in l), 3) if os.path.exists(L) else 0.0, note='the whole run is itself ONE charged supervised job when launched through gbidi.supervise (see the caller ledger); cell receipts are nested inside it'),
               limitations=['a small fixed panel cannot show the absence of regressions elsewhere', 'PAC rows: a few fixed seeds test reachability / regression only, never delta calibration; relaxed-tolerance rows are qualification-only witnesses', 'sidecar frontier.last_enclosure = COMPILED widths before bias (diagnostic), never certified original-task error; per-operator wall times are unavailable (not inferred); signed epoch history is a bounded ring', 'structural_original publications are production successes, not mechanism coverage (activation is read from the certificate)'])
    json.dump(rec, open(os.path.join(RUN, 'ITERATION_REPORT.json'), 'w'), indent=1, default=str); RP.write_md(rec, rows_sel, os.path.join(RUN, 'ITERATION_REPORT.md'))
    print(json.dumps(dict(status=status, elapsed_s=round(elapsed, 2), cells=len(cells), not_run=len(not_run), stop=stop, mutations=[(m['name'], m['refused']) for m in muts]))); sys.exit(0 if status == 'COMPLETE' else 1)
if __name__ == '__main__': main()
