"""FAST LOOP RUNNER v2 (A1 review repairs CQR-FL-01..07). ONE ABSOLUTE DEADLINE for everything (identity, inputs, workers, truth, verification, controls, cleanup, report); a FINALIZATION
RESERVE is kept from the start; every child is a bounded subprocess; partial results are written DURABLY after every cell and in a `finally`, so a timeout / exception / forced stop leaves a
typed report. TASK BINDING: the pinned model / evidence / query hashes (and absences) are validated BEFORE any launch, the inputs are SNAPSHOTTED into the run directory and every worker /
verifier / oracle reads the snapshot; the worker's consumed binding is compared with the row; drift is a typed TASK_INTEGRITY stop. TRUTH: authenticated cache records (truth.py). BUILD:
each worker is verified by ITS build's checker in its build's process; source mismatch / loader provenance mismatch / arm mismatch are refusals. OUTCOMES: supervisor outcome + rc, worker
status / outcome, terminal cleanup and expected control outcomes are reconciled; FAULT / abnormal exit / NO_OUTPUT / malformed output are typed failures; PROVED_ZERO_EVIDENCE is a
mathematical claim verified by the checker AND checked against independent truth. CONTROLS: the REQUIRED negative controls are declared; a negative passes only when the checker COMPLETES
and REFUSES for the intended class; a checker fault / missing result never passes; missing required controls -> INCOMPLETE. REPORT: three separate verdicts -- execution completeness,
correctness, required capability COVERAGE (precise predicates) -- plus two labelled evidence channels (checker-verified facts; timestamped sidecar diagnostics). Nothing is PASS.
Usage: run.py --manifest DIR --candidate BUILD --baseline BUILD --out RUN_DIR --mode smoke|full [--hypothesis FILE] [--total-cap 300] [--rows ID,..] [--label TEXT]
       harness controls (fixtures only; never a solver change): --inject-missing-output ID --inject-corrupt ID"""
import os, sys, json, time, argparse, subprocess, hashlib, shutil, copy, traceback
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import truth as TR, report as RP
from __init__ import FASTLOOP_VERSION
FINAL_RESERVE_S = 12.0; GRACE_S = 5.0; VERIFY_MAX_S = 20.0; TRUTH_MAX_S = 30.0; MUT_MAX_S = 8.0
EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
def sha(p): return TR.sha_file(p)
def pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
def git(d, *a, timeout=10):
    try: return subprocess.run(['git', '-C', d, *a], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception: return None
def identity(build, timeout):
    code = "import sys, json, hashlib; sys.path.insert(0, %r); import registry as R; inv = R.full_inventory(%r); cqr = R.cqr_source_inventory(%r); print(json.dumps(dict(full_inventory_sha256=hashlib.sha256(json.dumps(inv, sort_keys=True).encode()).hexdigest(), artifacts=len(inv), cqr_scope_sha256=hashlib.sha256(json.dumps(cqr, sort_keys=True).encode()).hexdigest(), cqr_files=len(cqr))))" % (os.path.join(build, 'cex', 'cqr'), build, build)
    try: p = subprocess.run([pybin(build), '-c', code], capture_output=True, text=True, timeout=timeout); d = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else dict(error=p.stderr[-300:])
    except Exception as ex: d = dict(error='%s: %s' % (type(ex).__name__, str(ex)[:120]))
    d.update(build=build, git_head=git(build, 'rev-parse', 'HEAD'), git_branch=(git(build, 'branch', '--show-current') or 'DETACHED'), tracked_clean=(git(build, 'status', '--porcelain', '--untracked-files=no') == '')); return d

# ---------------------------------------------------------------- coverage predicates (CQR-FL-07): precise, from CHECKER-VERIFIED facts only
def predicates(cell):
    """VERIFIED predicates are decided from the checker-replayed certificate (channel A) only. The ONE observed predicate, `signed_stream_executed_OBSERVED`, is decided from the sidecar
    (channel B) and is labelled as such: it states that signed epochs with draws were OBSERVED at the last checkpoint (never that anything was published or verified)"""
    obs = cell.get('activation_observed') or {}; observed = dict(signed_stream_executed_OBSERVED=(sum(int(e.get('draws') or 0) for e in (obs.get('signed_epochs_observed') or [])) > 0), ratio_stream_executed_OBSERVED=(int(obs.get('ratio_draws_observed') or 0) > 0))
    if cell.get('outcome') not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') or (cell.get('check') or {}).get('status') != 'ACCEPTED': return observed
    a = cell.get('activation_verified') or {}; r = cell.get('route') or ''; bias = [str(b) for b in (a.get('bias') or [])]
    ep = a.get('signed_epochs') or []
    return dict(structural_publication=r.startswith('structural'), exact_publication=(r in EXACT_ROUTES), deterministic_approx_publication=(cell['outcome'] == 'PUBLISHED' and not r.startswith('structural') and r not in EXACT_ROUTES and 'pac' not in r),
                approx_quotient_nonzero_bias=('approx_quotient' in (a.get('compile_commits') or []) and any(b not in ('0', 'None') for b in bias)), exact_quotient_commit=('exact_quotient_pass' in (a.get('compile_commits') or [])),
                concentration_nonzero_bias=('concentration' in (a.get('compile_commits') or []) and any(b not in ('0', 'None') for b in bias)), signed_epochs_with_draws=(sum(int(e.get('t') or 0) for e in ep) > 0), signed_pac_publication=(r == 'pac_signed_residual_validation'),
                ratio_draws=(int(a.get('ratio_draws') or 0) > 0), ratio_pac_publication=('pac_ratio' in r), zero_evidence_proof_verified=(cell['outcome'] == 'PROVED_ZERO_EVIDENCE'), normalizer_publication=r.startswith('normalizer'), **observed)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--candidate', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--out', required=True); ap.add_argument('--mode', choices=['smoke', 'full'], default='full')
    ap.add_argument('--hypothesis', default=None); ap.add_argument('--total-cap', type=float, default=300.0); ap.add_argument('--rows', default=None); ap.add_argument('--inject-missing-output', default=None); ap.add_argument('--inject-corrupt', default=None); ap.add_argument('--label', default=''); ap.add_argument('--seed', default='fl')
    a = ap.parse_args(); T0 = time.monotonic(); T_END = T0 + a.total_cap; t_wall0 = time.time(); RUN = os.path.abspath(a.out)
    if os.path.exists(os.path.join(RUN, 'ITERATION_REPORT.json')): raise SystemExit('refuse: %s already holds a report (runs are immutable)' % RUN)
    os.makedirs(RUN, exist_ok=True); cand, base = os.path.abspath(a.candidate), os.path.abspath(a.baseline); L = os.path.join(RUN, 'CQR_LEDGER.jsonl')
    def left(): return T_END - time.monotonic()
    def work_left(): return left() - FINAL_RESERVE_S                                  # what may still be SPENT on work (the reserve is for cleanup + report)
    def deadline_s(want): return max(0.0, min(want, work_left()))
    rec = dict(schema='CQR_FASTLOOP_ITERATION_V2', harness=FASTLOOP_VERSION, label=a.label, utc_start=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_wall0)), cap_s=a.total_cap, finalization_reserve_s=FINAL_RESERVE_S, status='RUNNING', execution='RUNNING', correctness='RUNNING', coverage='RUNNING',
               stop_reason=None, hard_failures=[], integrity_failures=[], cells=[], mutation_controls=[], required_controls=dict(expected=[], executed=[], passed=[], failed=[]), not_run=[], no_output=[], unverified=[], coverage_required=[], coverage_missing=[], host=dict(node=os.uname().nodename, load_avg_1m=os.getloadavg()[0]),
               harness_controls=dict(inject_missing_output=a.inject_missing_output, inject_corrupt=a.inject_corrupt), elapsed_s=None, within_cap=None,
               limitations=['a small fixed panel cannot show the absence of regressions elsewhere', 'PAC rows: fixed seeds test reachability / regression only, never delta calibration; relaxed-tolerance rows are qualification-only witnesses', 'sidecar observations (channel B) are DIAGNOSTIC: frontier.last_enclosure = compiled widths before bias; stream counts are the last checkpoint; per-operator wall times are unavailable; signed epoch history is a bounded ring', 'structural publications are production successes, not mechanism coverage (predicates read the verified certificate)'])
    rows_sel = []; hyp = {}
    def flush(final=False):
        """DURABLE partial report after every step; the final write measures the whole run INCLUDING report generation"""
        rec['elapsed_s'] = round(time.monotonic() - T0, 3); rec['within_cap'] = rec['elapsed_s'] <= a.total_cap
        tmp = os.path.join(RUN, 'ITERATION_REPORT.json.tmp'); json.dump(rec, open(tmp, 'w'), indent=1, default=str); os.replace(tmp, os.path.join(RUN, 'ITERATION_REPORT.json'))
        try: RP.write_md(rec, rows_sel, os.path.join(RUN, 'ITERATION_REPORT.md'))
        except Exception as ex: open(os.path.join(RUN, 'ITERATION_REPORT.md'), 'w').write('# report rendering failed: %s\n(see ITERATION_REPORT.json)\n' % ex)
        if final:
            rec['elapsed_s'] = round(time.monotonic() - T0, 3); rec['within_cap'] = rec['elapsed_s'] <= a.total_cap
            json.dump(rec, open(tmp, 'w'), indent=1, default=str); os.replace(tmp, os.path.join(RUN, 'ITERATION_REPORT.json'))        # the final number includes the report writes
    def hard(kind, where, msg):
        rec['hard_failures'].append(dict(kind=kind, where=where, msg=msg[:300]))
        if rec['stop_reason'] is None: rec['stop_reason'] = 'STOP [%s] %s: %s' % (kind, where, msg[:200])
    try:
        # ---------------- 0. manifest, hypothesis, identities, TASK INTEGRITY (before any launch)
        M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); rec['manifest_sha256'] = sha(os.path.join(a.manifest, 'DEV_MANIFEST.json'))
        pin_p = os.path.join(a.manifest, 'LADDER_PIN.json'); pin = json.load(open(pin_p)) if os.path.exists(pin_p) else None
        for r in M['rows']:
            if r['block'] == 'change_specific_ladder': r['pinned'] = bool(pin) and r['id'] in (pin.get('pinned_ids') or [])
        hyp = json.load(open(a.hypothesis)) if a.hypothesis else dict(change='(none declared: regression / calibration run)', premise=None, expected_favorable=None, expected_near_miss=None, preserved=['every exact / structured sentinel and contract row publishes and verifies as on the accepted baseline'], question=None)
        rec['hypothesis'] = hyp
        rows_sel = [r for r in M['rows'] if (r['id'] in M['smoke_rows'] if a.mode == 'smoke' else (r['block'] not in ('change_specific_ladder', 'bank_optional') or r.get('pinned')))]
        if a.rows: want = set(a.rows.split(',')); rows_sel = [r for r in M['rows'] if r['id'] in want]
        rec['identities'] = dict(candidate=identity(cand, deadline_s(20)), baseline=identity(base, deadline_s(20)), harness=dict(version=FASTLOOP_VERSION, files={f: sha(os.path.join(HERE, f)) for f in sorted(os.listdir(HERE)) if f.endswith('.py')}), ladder_pin=(pin or {'status': 'NOT PINNED (calibrate.py has not run): change-specific rows NOT RUN'}), oracle=TR.oracle_identity(base))
        nominal = sum(r['budget_s'] * (2 if r.get('comparator') else 1) for r in rows_sel)
        rec['plan'] = dict(mode=a.mode, rows=[r['id'] for r in rows_sel], worker_nominal_s=nominal, allocations=M.get('allocations'), within_worker_cap=(nominal <= (M.get('allocations') or {}).get('worker_nominal_s_cap', 180.0)))
        rec['coverage_required'] = [dict(id=r['id'], predicates=r.get('coverage_required') or []) for r in rows_sel if r.get('coverage_required')]
        rec['required_controls']['expected'] = list(M.get('mutation_controls_required') or [])
        snap_dir = os.path.join(RUN, 'inputs'); os.makedirs(snap_dir, exist_ok=True)
        for r in rows_sel:                                                           # CQR-FL-01: validate pinned bytes + absence markers, then SNAPSHOT
            cur = dict(model_sha256=sha(r['model']), evidence_sha256=(sha(r['model'] + '.evid') if os.path.exists(r['model'] + '.evid') else None), query_sha256=(sha(r['model'] + '.query.json') if os.path.exists(r['model'] + '.query.json') else None))
            bad = [k for k in cur if cur[k] != r.get(k)]
            if bad: rec['integrity_failures'].append(dict(kind='TASK_INTEGRITY', id=r['id'], fields=bad, pinned={k: r.get(k) for k in bad}, on_disk={k: cur[k] for k in bad})); continue
            sd = os.path.join(snap_dir, r['id']); os.makedirs(sd, exist_ok=True); mp = os.path.join(sd, 'model.uai'); shutil.copyfile(r['model'], mp)
            for ext in ('.evid', '.query.json'):
                if os.path.exists(r['model'] + ext): shutil.copyfile(r['model'] + ext, mp + ext)
            r['_snapshot'] = mp
        if rec['integrity_failures']: hard('TASK_INTEGRITY', 'manifest', 'pinned task bytes differ on disk for %s: no worker launched' % [x['id'] for x in rec['integrity_failures']])
        flush()
        # ---------------- 1. cells
        def launch(build, arm, r, tag, order_i):
            d = os.path.join(RUN, 'cells', '%02d_%s__%s__%s' % (order_i, r['id'], tag, arm)); os.makedirs(d, exist_ok=True); out = os.path.join(d, 'worker.json'); b = r['budget_s']; mp = r['_snapshot']
            cell = dict(id=r['id'], tag=tag, arm=arm, build=build, dir=os.path.relpath(d, RUN), budget_s=b, seed=a.seed)
            if work_left() < b + GRACE_S + 2.0: cell.update(status='NOT_RUN', outcome='NOT_RUN', reason='global deadline: %.1f s of work left < budget %.0f s + grace' % (work_left(), b), wall_s=0.0); return cell
            PY = pybin(build); dl = time.monotonic() + b
            if a.inject_missing_output == r['id'] and tag == 'candidate': cmd = [PY, '-c', 'import time; time.sleep(0.2)']           # HARNESS CONTROL: a child that writes nothing
            else: cmd = [PY, os.path.join(build, 'cex', 'pac' if arm in ('H1_HYBRID', 'P1_PAC_CONDITIONAL', 'A0_POINT', 'A1_CONDITIONAL') else 'cqr', 'worker.py'), '--input', mp, '--output', out, '--arm', arm, '--deadline', str(dl), '--budget', str(b), '--seed', a.seed, '--nonce', '%s-%s-%s' % (r['id'], tag, arm)]
            job = 'cell:%s:%s:%s' % (r['id'], tag, arm); sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_' + a.mode, '--job', job, '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
            t = time.monotonic()
            try: p = subprocess.run(sup, capture_output=True, text=True, cwd=build, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'), timeout=b + 1.0 + GRACE_S + 15.0); serr = p.stderr; prc = p.returncode
            except subprocess.TimeoutExpired as tx: serr = (tx.stderr or b'').decode() if isinstance(tx.stderr, bytes) else (tx.stderr or ''); prc = None
            wall = time.monotonic() - t
            try: srec = json.loads(serr.strip().splitlines()[-1])
            except Exception: srec = dict(parse_error=(serr or '')[-300:], outcome='SUPERVISOR_UNREADABLE')
            w = None; malformed = None
            if os.path.exists(out):
                try: w = json.load(open(out))
                except Exception as ex: malformed = 'worker output unreadable: %s' % str(ex)[:80]
            cell.update(wall_s=round(wall, 3), supervisor=dict(outcome=srec.get('outcome'), rc=srec.get('rc'), survivors=srec.get('survivors'), wall_s=srec.get('wall_s'), peak_MB=srec.get('peak_MB'), parse_error=srec.get('parse_error')), worker_json=(os.path.relpath(out, RUN) if os.path.exists(out) else None))
            # ---- OUTCOME RECONCILIATION (CQR-FL-04): supervisor x worker x cleanup
            if srec.get('survivors'): cell['failure'] = dict(kind='PROCESS_CONTAINMENT', msg='supervisor reported %s live survivors' % srec.get('survivors'))
            if srec.get('outcome') == 'TIMEOUT_KILL': cell.update(status='TIMEOUT_KILL', outcome='DEADLINE', reason='hard kill by the supervisor at the budget + grace (no graceful stop)')
            elif srec.get('outcome') == 'MEMORY_KILL': cell.update(status='MEMORY_KILL', outcome='MEMORY')
            elif w is None: cell.update(status=('MALFORMED_OUTPUT' if malformed else 'NO_OUTPUT'), outcome='NO_OUTPUT', reason=(malformed or 'the worker exited (rc %s) without writing its output' % srec.get('rc'))); cell['failure'] = dict(kind='NO_OUTPUT', msg=cell['reason'])
            else:
                cell.update(status=w.get('status', 'UNKNOWN'), outcome=w.get('outcome', 'UNKNOWN'), route=w.get('route'), guarantee=w.get('guarantee_type'), reason=(w.get('reason') or '')[:160], worker_elapsed_s=w.get('worker_elapsed_s'), peak_rss_mb=(round((w.get('peak_rss_bytes') or 0) / 1e6, 1)), answers=w.get('answers'), bias=w.get('bias'), binding=w.get('binding'))
                if w.get('outcome') == 'FAULT' or w.get('exception_type'): cell['failure'] = dict(kind='WORKER_FAULT', msg='worker reported %s: %s' % (w.get('outcome'), (w.get('reason') or w.get('exception_type') or '')[:120]))
                elif srec.get('outcome') != 'COMPLETED' or srec.get('rc') not in (0, None): cell['failure'] = dict(kind='ABNORMAL_EXIT', msg='supervisor outcome %s rc %s with a worker file present (status %s): numerical correctness does not excuse an abnormal process completion' % (srec.get('outcome'), srec.get('rc'), w.get('status')))
                elif w.get('status') == 'COMPLETED' and wall > b + 0.05: cell.update(status='LATE_OUTPUT', outcome='DEADLINE')
                # consumed bytes == the row (CQR-FL-01)
                bnd = w.get('binding') or {}
                if bnd and (bnd.get('model_sha256') != r['model_sha256'] or (bnd.get('evidence_sha256') != r['evidence_sha256'] and r['evidence_sha256'] is not None) or (bnd.get('query_sha256') or None) != (r['query_sha256'] or None)): cell['failure'] = dict(kind='TASK_INTEGRITY', msg='the worker consumed bytes other than the pinned row (binding differs)')
                if a.inject_corrupt == r['id'] and tag == 'candidate' and w.get('outcome') == 'PUBLISHED':                   # HARNESS CONTROL: a shifted COPY is verified; the honest file is kept
                    wc = _shift(copy.deepcopy(w)); out = os.path.join(d, 'worker_CORRUPTED_BY_HARNESS.json'); json.dump(wc, open(out, 'w'), default=str); cell['worker_json'] = os.path.relpath(out, RUN); cell['answers'] = wc['answers']; cell['harness_corrupted_copy'] = True
            dg = out[:-5] + '.diag.json'
            if not os.path.exists(dg): dg = os.path.join(d, 'worker.diag.json')
            cell['sidecar'] = os.path.relpath(dg, RUN) if os.path.exists(dg) else None
            return cell
        def verify(cell, r):
            """the producing build's OWN checker (bounded subprocess) + authenticated independent truth; PROVED_ZERO_EVIDENCE is verified too"""
            if cell['outcome'] not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') or not cell.get('worker_json'): cell['check'] = dict(status='NA'); cell['truth'] = dict(status='NA'); return
            dl = deadline_s(VERIFY_MAX_S)
            if dl < 2.0: cell['check'] = dict(status='NOT_RUN', reason='global deadline before verification'); cell['truth'] = dict(status='NOT_RUN'); return
            outp = os.path.join(RUN, cell['dir'], 'check.json'); t = time.monotonic()
            try: p = subprocess.run([pybin(cell['build']), os.path.join(HERE, 'check_cli.py'), cell['build'], r['_snapshot'], os.path.join(RUN, cell['worker_json']), cell['arm'], str(dl), outp], capture_output=True, text=True, cwd=cell['build'], timeout=dl + 5.0); to = False
            except subprocess.TimeoutExpired: to = True
            ck = json.load(open(outp)) if os.path.exists(outp) else dict(status=('VERIFIER_TIMEOUT' if to else 'VERIFIER_NO_RESULT'), fails=['the verifier subprocess %s' % ('exceeded its bounded allowance (%.1f s)' % dl if to else 'produced no result')], checker_completed=False)
            ck['harness_wall_s'] = round(time.monotonic() - t, 3); cell['check'] = ck
            if ck['status'] == 'REFUSED': cell['failure'] = dict(kind=('IDENTITY' if (ck.get('identity') or {}).get('failures') or (ck.get('provenance') or {}).get('failures') else 'CANDIDATE_CORRECTNESS'), msg='publication REFUSED by its own build: %s' % (ck.get('all_failures') or [''])[0][:160])
            elif ck['status'] in ('CHECKER_FAULT', 'VERIFIER_TIMEOUT', 'VERIFIER_NO_RESULT'): cell['failure'] = dict(kind='VERIFIER_FAULT', msg='%s: %s' % (ck['status'], (ck.get('fails') or [''])[0][:140]))
            elif ck['status'] == 'UNVERIFIABLE': cell['unverifiable'] = (ck.get('fails') or [''])[0][:160]
            tr = TR.truth_for(r['_snapshot'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=deadline_s(TRUTH_MAX_S)) if work_left() > 3.0 else dict(status='NOT_RUN', reason='global deadline before truth')
            cont = TR.containment(dict(outcome=cell['outcome'], answers=cell.get('answers')), tr) if cell['outcome'] == 'PUBLISHED' else TR.zero_claim_check(tr)
            cell['truth'] = dict(status=tr.get('status'), method=tr.get('method'), prep_s=tr.get('prep_s'), cache_hit=tr.get('cache_hit'), verdict=cont, truth_answers=((tr.get('answers') or [tr.get('Z')])[:4] if tr.get('status') == 'EXACT' else None), reason=tr.get('reason'), integrity_failures=tr.get('integrity_failures'))
            if cont == 'CACHE_INTEGRITY': cell['failure'] = dict(kind='HARNESS_INTEGRITY', msg='truth cache record failed authentication: %s' % (tr.get('integrity_failures') or [''])[0][:140])
            elif cont in ('MISS', 'CONTRADICTED') and cell.get('guarantee') == 'DETERMINISTIC': cell['failure'] = dict(kind='CANDIDATE_CORRECTNESS', msg='deterministic %s outside the independent truth' % ('publication' if cont == 'MISS' else 'zero claim'))
            elif cont == 'MISS' and cell.get('guarantee') == 'PAC': cell['pac_miss'] = 'PAC publication outside the truth: preserved for investigation under the statistical contract (not a soundness verdict by itself)'
        def activation(cell):
            """two LABELLED channels: A = facts verified by the checker (certificate replayed); B = sidecar observations with timestamps / ages (diagnostic)"""
            A_ = {}
            if cell.get('worker_json') and (cell.get('check') or {}).get('status') == 'ACCEPTED':
                w = json.load(open(os.path.join(RUN, cell['worker_json']))); c = w.get('certificate') or {}; ck = cell['check']
                A_ = dict(compile_commits=ck.get('commits') or [], compile_declines=ck.get('declines') or [], bias=ck.get('bias'), ratio_draws=((c.get('ratio_stream') or {}).get('t')), signed_epochs=[dict(epoch=e.get('epoch'), t=e.get('t'), retired=e.get('retired')) for e in (c.get('epochs') or [])],
                          frontier=({k: (c.get('frontier') or {}).get(k) for k in ('open_cells', 'resolved_cells', 'splits', 'closures')} if c.get('frontier') else None), structural=ck.get('structural'), attribution_route=(ck.get('attribution') or {}).get('route'), zero_transfer=ck.get('zero_transfer'),
                          work=({k: (v.get('total') if isinstance(v, dict) else v) for k, v in (c.get('work') or {}).items()} if c.get('work') else None), reference=({k: (c.get('reference') or {}).get(k) for k in ('done', 'progress')} if c.get('reference') else None), source='checker-verified certificate')
            cell['activation_verified'] = A_
            B_ = None; sc_p = os.path.join(RUN, cell['sidecar']) if cell.get('sidecar') else None
            if sc_p and os.path.exists(sc_p):
                try:
                    s_ = json.load(open(sc_p)); st = s_.get('streams') or {}; fr = s_.get('frontier') or {}; le = fr.get('last_enclosure') if isinstance(fr, dict) else None; ages = (s_.get('freshness') or {}).get('section_ages_s') or {}
                    B_ = dict(source='diagnostic sidecar (last checkpoint; NOT verified)', elapsed_s_at_write=(s_.get('freshness') or {}).get('elapsed_s_at_write'), phase_at_end=s_.get('phase'), phase_times_s=s_.get('phase_times_s'), phase_table_covers_s=round(sum((s_.get('phase_times_s') or {}).values()), 3) if s_.get('phase_times_s') else None,
                              ratio_draws_observed=(st.get('ratio') or {}).get('draws'), ratio_age_s=ages.get('streams'), signed_epochs_observed=[dict(epoch=e.get('epoch'), draws=e.get('draws'), retired=e.get('retired')) for e in (st.get('signed_epochs') or [])], planner_decisions=[(x.get('representation'), x.get('decision'), (x.get('reason') or '')[:80]) for x in ((s_.get('planner') or {}).get('decisions') or [])][-4:],
                              frontier_counts={k: fr.get(k) for k in ('open_cells', 'resolved_cells', 'splits', 'closures')} if isinstance(fr, dict) else None, frontier_age_s=ages.get('frontier'), reference_progress=(s_.get('reference') or {}).get('progress'), overhead_s=s_.get('overhead_s'),
                              last_enclosure_DIAGNOSTIC=({k: le.get(k) for k in ('elapsed_s', 'queries', 'max_width', 'median_width', 'undefined')} if isinstance(le, dict) else le), note='frontier.last_enclosure = COMPILED-model widths BEFORE original-query bias widening (float summary / top 8): never a certified original-task error')
                except Exception as ex: B_ = dict(source='diagnostic sidecar', error='unreadable: %s' % str(ex)[:80])
            cell['activation_observed'] = B_
            cell['predicates'] = predicates(cell)
        cells = rec['cells']; order_i = 0; stop = bool(rec['stop_reason'])
        for i, r in enumerate(rows_sel):
            if stop: break
            comp = r.get('comparator'); arms = [('candidate', cand, r['candidate_arm'])] + ([('comparator', (base if comp['kind'] == 'baseline_N1' else cand), comp['arm'])] if comp else [])
            if i % 2 == 1 and len(arms) == 2: arms = arms[::-1]
            for tag, build, arm in arms:
                order_i += 1; cell = launch(build, arm, r, tag, order_i); cell['comparator_kind'] = (comp or {}).get('kind') if tag == 'comparator' else None
                if cell['status'] != 'NOT_RUN': verify(cell, r); activation(cell)
                else: cell['check'] = dict(status='NOT_RUN'); cell['truth'] = dict(status='NOT_RUN'); cell['predicates'] = {}
                if r.get('expected_outcome') and tag == 'candidate' and cell['status'] != 'NOT_RUN' and cell['outcome'] != r['expected_outcome'] and not cell.get('failure'): cell['failure'] = dict(kind='CONTROL_EXPECTATION', msg='expected %s, observed %s' % (r['expected_outcome'], cell['outcome']))
                if r['id'] == 'FL_CTL_zero_mass' and tag == 'candidate' and cell['outcome'] == 'PUBLISHED' and not all(x.get('lo') == x.get('hi') == '0' for x in (cell.get('answers') or [])) and not cell.get('failure'): cell['failure'] = dict(kind='CANDIDATE_CORRECTNESS', msg='zero-mass control published a nonzero answer')
                cells.append(cell)
                if cell.get('failure') and cell['failure']['kind'] not in ('NO_OUTPUT',): hard(cell['failure']['kind'], '%s/%s' % (cell['id'], cell['tag']), cell['failure']['msg']); stop = True
                elif cell.get('failure'): rec['no_output'].append([cell['id'], cell['tag'], cell['failure']['msg']])
                flush()
                if stop: break
        done = {(c['id'], c['tag']) for c in cells}
        for r in rows_sel:
            for tag in (['candidate'] + (['comparator'] if r.get('comparator') else [])):
                if (r['id'], tag) not in done: cells.append(dict(id=r['id'], tag=tag, arm=(r['candidate_arm'] if tag == 'candidate' else r['comparator']['arm']), status='NOT_RUN', outcome='NOT_RUN', reason=('stopped after a hard failure' if stop else 'global deadline'), wall_s=0.0, check=dict(status='NOT_RUN'), truth=dict(status='NOT_RUN'), predicates={}))
        rec['not_run'] = [[c['id'], c['tag'], c.get('reason')] for c in cells if c['status'] == 'NOT_RUN']
        # ---------------- 2. REQUIRED negative controls (copies of the first honest smoke publication): pass = checker COMPLETES and REFUSES for the intended class
        hon = next((c for cid in ('FL_C35_mixed_alias', 'FL_SENT_ASIA') for c in cells if c['id'] == cid and c['tag'] == 'candidate' and c['outcome'] == 'PUBLISHED' and (c.get('check') or {}).get('status') == 'ACCEPTED' and not c.get('harness_corrupted_copy')), None)
        req = rec['required_controls']['expected']
        if hon and not stop:
            r = next(x for x in rows_sel if x['id'] == hon['id']); w = json.load(open(os.path.join(RUN, hon['worker_json']))); md = os.path.join(RUN, 'mutations'); os.makedirs(md, exist_ok=True)
            def control(name, wm, model_path, needles):
                if name not in req: return
                dl = deadline_s(MUT_MAX_S)
                if dl < 1.5: rec['mutation_controls'].append(dict(name=name, status='NOT_RUN', reason='global deadline')); return
                wp = os.path.join(md, name + '.json'); json.dump(wm, open(wp, 'w'), default=str); outp = os.path.join(md, name + '.check.json')
                try: subprocess.run([pybin(cand), os.path.join(HERE, 'check_cli.py'), cand, model_path, wp, hon['arm'], str(dl), outp], capture_output=True, text=True, cwd=cand, timeout=dl + 5.0); to = False
                except subprocess.TimeoutExpired: to = True
                ck = json.load(open(outp)) if os.path.exists(outp) else dict(status=('VERIFIER_TIMEOUT' if to else 'VERIFIER_NO_RESULT'), fails=[], checker_completed=False)
                intended = ck.get('checker_completed') and ck.get('status') == 'REFUSED' and any(any(nd in f_ for nd in needles) for f_ in (ck.get('all_failures') or []))
                rec['mutation_controls'].append(dict(name=name, status=('PASSED' if intended else 'FAILED'), checker_status=ck.get('status'), checker_completed=ck.get('checker_completed'), first=(ck.get('all_failures') or ck.get('fails') or [''])[0][:140], intended_needles=list(needles)))
                rec['required_controls']['executed'].append(name); (rec['required_controls']['passed'] if intended else rec['required_controls']['failed']).append(name)
            control('answer_shifted_by_1_97', _shift(copy.deepcopy(w)), r['_snapshot'], ('contain', 'legacy row'))
            w2 = copy.deepcopy(w); w2['guarantee_type'] = 'PAC'; w2['certificate']['publication']['guarantee'] = 'PAC'; control('guarantee_relabelled', w2, r['_snapshot'], ('class',))
            w3 = copy.deepcopy(w); w3['candidate_sources'] = {}; control('source_identity_emptied', w3, r['_snapshot'], ('candidate_sources differ',))
            if hon['id'] == 'FL_C35_mixed_alias':
                td = os.path.join(md, 'label_swap_task'); shutil.copytree(os.path.dirname(r['_snapshot']), td); mp2 = os.path.join(td, os.path.basename(r['_snapshot'])); q = json.load(open(mp2 + '.query.json')); q['queries'][0] = dict(kind='joint', assign={'0': 0}); json.dump(q, open(mp2 + '.query.json', 'w')); control('label_swapped_to_other_denotation', copy.deepcopy(w), mp2, ('binding', 'identity', 'denotes'))
        missing_ctl = [n for n in req if n not in rec['required_controls']['executed']]
        # ---------------- 3. COVERAGE (required predicates per row, decided from verified facts)
        for item in rec['coverage_required']:
            cs = [c for c in cells if c['id'] == item['id'] and c['tag'] == 'candidate']; got = (cs[0].get('predicates') or {}) if cs else {}
            for pname in item['predicates']:
                if not got.get(pname): rec['coverage_missing'].append(dict(id=item['id'], predicate=pname, observed=(cs[0]['outcome'] if cs else 'NOT_RUN'), route=(cs[0].get('route') if cs else None)))
        # ---------------- 4. verdicts
        unver = [c for c in cells if c['outcome'] in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and (c.get('check') or {}).get('status') not in ('ACCEPTED', 'REFUSED', 'UNVERIFIABLE', 'NA')]
        rec['unverified'] = [[c['id'], c['tag'], (c.get('check') or {}).get('status')] for c in unver]; rec['unverifiable'] = [[c['id'], c['tag'], c.get('unverifiable')] for c in cells if c.get('unverifiable')]
        rec['required_controls']['missing'] = missing_ctl
        rec['correctness'] = 'FAILED' if rec['hard_failures'] else 'OK'
        rec['execution'] = 'STOP' if stop else ('INCOMPLETE' if (rec['not_run'] or rec['no_output'] or unver or missing_ctl or rec['required_controls']['failed'] or (hon is None) or rec['unverifiable']) else 'COMPLETE')
        rec['coverage'] = 'INCOMPLETE' if rec['coverage_missing'] else ('COMPLETE' if rec['coverage_required'] else 'NONE REQUIRED')
        rec['status'] = 'STOP' if stop else ('INCOMPLETE' if rec['execution'] != 'COMPLETE' or rec['coverage'] == 'INCOMPLETE' else 'COMPLETE')
    except Exception as ex:
        rec['harness_exception'] = dict(type=type(ex).__name__, msg=str(ex)[:300], traceback=traceback.format_exc()[-1500:]); rec['execution'] = 'HARNESS_EXCEPTION'; rec['status'] = 'INCOMPLETE'
        if rec['correctness'] == 'RUNNING': rec['correctness'] = 'UNKNOWN'
        if rec['coverage'] == 'RUNNING': rec['coverage'] = 'UNKNOWN'
    finally:
        try: rec['charges'] = dict(cell_receipts=sum(1 for l in open(L) if '"RECEIPT"' in l) if os.path.exists(L) else 0, cell_wall_s=round(sum(json.loads(l)['wall_s'] for l in open(L) if '"kind": "RECEIPT"' in l), 3) if os.path.exists(L) else 0.0, note='nested receipts lie INSIDE the outer supervised receipt of this run when launched through gbidi.supervise; never add them to it')
        except Exception: rec['charges'] = dict(error='ledger unreadable')
        if rec['status'] == 'RUNNING': rec['status'] = 'INCOMPLETE'
        if rec['elapsed_s'] is not None or True:
            if time.monotonic() - T0 > a.total_cap and rec['status'] == 'COMPLETE': rec['status'] = 'INCOMPLETE'; rec['execution'] = 'INCOMPLETE (cap exceeded)'
        flush(final=True)
    print(json.dumps(dict(status=rec['status'], execution=rec['execution'], correctness=rec['correctness'], coverage=rec['coverage'], elapsed_s=rec['elapsed_s'], cells=len(rec['cells']), not_run=len(rec['not_run']), stop=rec['stop_reason'], controls=rec['required_controls'], coverage_missing=[(x['id'], x['predicate']) for x in rec['coverage_missing']])))
    sys.exit(0 if rec['status'] == 'COMPLETE' else 1)

def _shift(wc):
    """a detectable corruption of a publication COPY: the first answer and the certificate publication moved by +1/97 (clipped to 1)"""
    a0 = wc['answers'][0]; v = str(min(F(1), F(a0['point']) + F(1, 97))); a0['lo'] = a0['hi'] = a0['point'] = v
    pub = wc['certificate']['publication']; pub['bounds'][0] = [v, v]
    if isinstance(pub.get('point'), list): pub['point'][0] = v
    return wc
if __name__ == '__main__': main()
