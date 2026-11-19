"""FAST LOOP RUNNER v3 (A1 review repairs CQR-FL-01..07; repair-2 review CQR-AF2-03..06). ONE ABSOLUTE DEADLINE for everything: identity (incl. every git call), inputs, workers,
truth, verification, controls, cleanup and report -- the remaining allowance is recomputed before EVERY subprocess and bounds its hard wait; a FINALIZATION RESERVE is kept from the
start; partial results are written DURABLY after every cell and in a `finally`. TASK BINDING: the output directory must be EMPTY (fresh private snapshot set; a pre-existing snapshot
is refused, never reused); every snapshot directory is created fresh, holds EXACTLY the declared files, and is verified after copying (hashes AND absences, the manifest's absent-evidence
marker normalized to the reader's sha256(b'0')); the consumed binding is compared with the pinned row at the WORKER boundary (every field incl. absences), the CHECKER boundary
(check_cli re-reads the snapshot against the pinned triple) and the ORACLE boundary (the truth record's task parts). BUILD: the candidate and baseline identities (full inventory, cqr
scope, kernel identity, per-file paths) are PINNED at iteration start; every worker / checker / kernel identity is compared with the PINNED identity (never the current build with
itself); the build is re-hashed before every launch and after every verification, and re-identified by subprocess before final success -- any drift is a typed BUILD_DRIFT stop even
when the answer is unchanged. OUTCOMES: the worker record must have the required fields and a recognized (status, outcome) terminal pair with its required claim fields (a parsed `{}`
or an unknown outcome is a WORKER_PROTOCOL failure, never an ordinary non-publication); worker, checker AND oracle must complete NORMALLY (rc 0) -- a record followed by an abnormal exit
is discarded (VERIFIER_FAULT / ORACLE_FAULT); the actual rc / timeout / hard wait are recorded beside every result; a failed checker cannot accept a positive or pass a negative control;
a failed oracle cannot populate an EXACT cache. TRUTH: authenticated cache records, with the trusted preparation index when the cache carries one (its sha256 recorded). REPORT: three
separate verdicts -- execution completeness, correctness, required capability COVERAGE -- plus two labelled evidence channels. Nothing is PASS.
Usage: run.py --manifest DIR --candidate BUILD --baseline BUILD --out RUN_DIR --mode smoke|full [--hypothesis FILE] [--total-cap 300] [--rows ID,..] [--label TEXT]
       harness controls (fixtures only; never a solver change): --inject-missing-output ID --inject-corrupt ID"""
import os, sys, json, time, argparse, subprocess, hashlib, shutil, copy, traceback
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import truth as TR, report as RP
from __init__ import FASTLOOP_VERSION
FINAL_RESERVE_S = 12.0; GRACE_S = 5.0; VERIFY_MAX_S = 20.0; TRUTH_MAX_S = 30.0; MUT_MAX_S = 8.0; HARD_WAIT_MARGIN_S = 4.0; IDENTITY_MAX_S = 20.0
PAC_ARMS = ('H1_HYBRID', 'P1_PAC_CONDITIONAL', 'A0_POINT', 'A1_CONDITIONAL')
EXACT_ROUTES = ('exact_reference', 'exact_frontier_closure', 'exact_zero_dimensional', 'normalizer_exact_reference', 'normalizer_exact_frontier_closure', 'normalizer_exact_zero_dimensional')
TERMINAL_PAIRS = {('COMPLETED', 'PUBLISHED'), ('STOPPED', 'PROVED_ZERO_EVIDENCE'), ('STOPPED', 'DEADLINE'), ('STOPPED', 'MEMORY'), ('STOPPED', 'FAULT'), ('STOPPED', 'INVALID_TASK'), ('STOPPED', 'NUMERICAL_RANGE_OR_PRECISION'),
                  ('STOPPED', 'INTERSECTION_EMPTY'), ('STOPPED', 'INTERSECTION_EMPTY_Z'), ('STOPPED', 'ZERO_RISK'), ('STOPPED', 'INVALID_PLAN_OR_CERTIFICATE')}
ZERO_HASH = TR.ZERO_HASH
def sha(p): return TR.sha_file(p)
def hj(d): return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
def pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
_ID_CODE = r'''
import sys, json, hashlib, os
build = sys.argv[1]; sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); sys.path.insert(0, os.path.join(build, 'cex', 'newarm'))
import registry as R, kernel_identity as KI
inv = R.full_inventory(build); cqr = R.cqr_source_inventory(build); k = KI.collect(build); paths = {}
for scope, dirs in R.SOURCE_SCOPES.items():
    for d in dirs:
        p = os.path.join(build, d)
        if os.path.isfile(p): paths[d] = p; continue
        if os.path.isdir(p):
            tag = os.path.basename(d)
            for f in sorted(os.listdir(p)):
                key = '%s/%s' % (tag, f)
                if key in inv: paths[key] = os.path.join(p, f)
for key in cqr:
    if key.startswith('cqr/'): paths[key] = os.path.join(build, 'cex', 'cqr', key[4:])
    elif key.startswith('newarm/'): paths[key] = os.path.join(build, 'cex', 'newarm', key[7:])
kpaths = {}
for tag, rec in k.items():
    bp = rec.get('binary_path'); rp = rec.get('record_path')
    kpaths[tag] = dict(binary=(bp if (bp and os.path.isabs(bp)) else (os.path.join(build, bp) if bp else None)), record=(os.path.join(build, rp) if rp else None))
hj = lambda d: hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
print(json.dumps(dict(full_inventory_sha256=hj(inv), artifacts=len(inv), cqr_scope_sha256=hj(cqr), cqr_files=len(cqr), kernel_identity_sha256=hj(k), full_inventory=inv, cqr_scope=cqr, kernel_identity=k, paths=paths, kernel_paths=kpaths, unlocated_inventory_keys=sorted(x for x in inv if x not in paths and inv[x] is not None))))
'''
def git(d, *a, timeout):
    if timeout <= 0.2: return None
    try: return subprocess.run(['git', '-C', d, *a], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception: return None
def identity(build, remaining, with_git=True):
    """the build's identity by subprocess (its own registry / kernel_identity), every call bounded by the REMAINING allowance (recomputed before each call; CQR-AF2-06)"""
    t0 = time.monotonic(); left = lambda: remaining() if callable(remaining) else remaining - (time.monotonic() - t0)
    try:
        to = max(0.5, min(IDENTITY_MAX_S, left())); p = subprocess.run([pybin(build), '-c', _ID_CODE, build], capture_output=True, text=True, timeout=to, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        d = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else dict(error='identity subprocess rc %s: %s' % (p.returncode, p.stderr[-300:]))
    except Exception as ex: d = dict(error='%s: %s' % (type(ex).__name__, str(ex)[:120]))
    if with_git: d.update(git_head=git(build, 'rev-parse', 'HEAD', timeout=min(10.0, left())), git_branch=(git(build, 'branch', '--show-current', timeout=min(10.0, left())) or 'DETACHED'), tracked_clean=(git(build, 'status', '--porcelain', '--untracked-files=no', timeout=min(10.0, left())) == ''))
    d.update(build=build, identity_wall_s=round(time.monotonic() - t0, 3))
    d['pinned_sha256'] = hj(dict(full_inventory_sha256=d.get('full_inventory_sha256'), cqr_scope_sha256=d.get('cqr_scope_sha256'), kernel_identity_sha256=d.get('kernel_identity_sha256'))) if not d.get('error') else None
    return d
def drift_now(pin):
    """re-hash every pinned source / kernel file of a build IN PROCESS (no subprocess): the keys whose bytes no longer equal the PINNED hashes"""
    bad = []
    for key, p in (pin.get('paths') or {}).items():
        if (sha(p) if os.path.exists(p) else None) != (pin.get('full_inventory') or {}).get(key): bad.append(key)
    for tag, kp in (pin.get('kernel_paths') or {}).items():
        rec = (pin.get('kernel_identity') or {}).get(tag) or {}
        for which, field in (('binary', 'binary_sha256'), ('record', 'record_sha256')):
            p = kp.get(which)
            if p and (sha(p) if os.path.exists(p) else None) != rec.get(field): bad.append('%s:%s' % (tag, which))
    return bad
def worker_schema_problem(w, arm):
    """the TYPED worker record boundary (CQR-AF2-05): required fields, a recognized terminal (status, outcome) pair, the claim fields its outcome requires, the consumed binding for every claim"""
    if not isinstance(w, dict): return 'worker record is not an object'
    for k in ('status', 'outcome', 'arm'):
        if k not in w: return 'worker record lacks the required field %s' % k
    if (w.get('status'), w.get('outcome')) not in TERMINAL_PAIRS: return 'worker status / outcome (%s / %s) is not a recognized terminal pair' % (w.get('status'), w.get('outcome'))
    if w.get('arm') != arm: return 'worker arm %s differs from the planned arm %s' % (w.get('arm'), arm)
    if w['outcome'] == 'PUBLISHED':
        if w.get('guarantee_type') not in ('PAC', 'DETERMINISTIC'): return 'published without a guarantee class (%s)' % w.get('guarantee_type')
        if not isinstance(w.get('answers'), list) and w.get('intervals') is None: return 'published without answers'
    if w['outcome'] == 'PROVED_ZERO_EVIDENCE' and arm not in PAC_ARMS and (w.get('guarantee_type') != 'DETERMINISTIC' or not isinstance(w.get('zero_evidence_proof'), dict)): return 'zero-evidence claim without a DETERMINISTIC proof record'
    if w['outcome'] in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE', 'DEADLINE') and not isinstance(w.get('binding'), dict): return 'worker record with outcome %s carries no consumed binding' % w['outcome']
    return None
def binding_problem(bnd, r, arm):
    """the consumed binding vs the pinned row: EVERY field incl. absences (pinned None = reader sha256(b'0') for evidence; None for the query spec); pac workers record no query field (legacy all-singleton contract) -- allowed only when the row pins no query spec"""
    if not isinstance(bnd, dict): return None
    if bnd.get('model_sha256') != r['model_sha256']: return 'model'
    if bnd.get('evidence_sha256') != (r['evidence_sha256'] if r['evidence_sha256'] is not None else ZERO_HASH): return 'evidence (present / absent / changed)'
    if 'query_sha256' in bnd:
        if (bnd.get('query_sha256') or None) != (r['query_sha256'] or None): return 'query spec (present / absent / changed)'
    elif r['query_sha256'] is not None or arm not in PAC_ARMS: return 'query spec binding missing from the worker record'
    return None

# ---------------------------------------------------------------- coverage predicates (CQR-FL-07): precise, from CHECKER-VERIFIED facts only
def predicates(cell):
    """VERIFIED predicates are decided from the checker-replayed certificate (channel A) only. The observed predicates (`*_OBSERVED`) are decided from the sidecar (channel B) and labelled as such"""
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
    if os.path.isdir(RUN) and os.listdir(RUN): raise SystemExit('refuse: %s is not empty (runs are immutable and every snapshot set is fresh and private: use a new, empty directory)' % RUN)
    os.makedirs(RUN, exist_ok=True); cand, base = os.path.abspath(a.candidate), os.path.abspath(a.baseline); L = os.path.join(RUN, 'CQR_LEDGER.jsonl')
    def left(): return T_END - time.monotonic()
    def work_left(): return left() - FINAL_RESERVE_S                                  # what may still be SPENT on work (the reserve is for cleanup + report)
    def deadline_s(want): return max(0.0, min(want, work_left()))
    def hard_wait(coop): return max(1.0, min(coop + 5.0, left() - HARD_WAIT_MARGIN_S))  # the subprocess hard wait never exceeds the remaining allowance minus a bounded margin
    rec = dict(schema='CQR_FASTLOOP_ITERATION_V3', harness=FASTLOOP_VERSION, label=a.label, utc_start=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_wall0)), cap_s=a.total_cap, finalization_reserve_s=FINAL_RESERVE_S, status='RUNNING', execution='RUNNING', correctness='RUNNING', coverage='RUNNING',
               stop_reason=None, hard_failures=[], integrity_failures=[], cells=[], mutation_controls=[], required_controls=dict(expected=[], executed=[], passed=[], failed=[]), not_run=[], not_run_steps=[], no_output=[], unverified=[], oracle_faults=[], coverage_required=[], coverage_missing=[], drift_checks=dict(in_process=0, subprocess=0, drift_found=[]), host=dict(node=os.uname().nodename, load_avg_1m=os.getloadavg()[0]),
               harness_controls=dict(inject_missing_output=a.inject_missing_output, inject_corrupt=a.inject_corrupt), elapsed_s=None, within_cap=None,
               limitations=['a small fixed panel cannot show the absence of regressions elsewhere', 'PAC rows: fixed seeds test reachability / regression only, never delta calibration; relaxed-tolerance rows are qualification-only witnesses', 'sidecar observations (channel B) are DIAGNOSTIC: frontier.last_enclosure = compiled widths before bias; stream counts are the last checkpoint; per-operator wall times are unavailable; signed epoch history is a bounded ring', 'structural publications are production successes, not mechanism coverage (predicates read the verified certificate)',
                            'in-process drift checks re-hash the PINNED file set (a file ADDED to a scope after the start is caught by the subprocess re-identification before final success, not by the per-boundary re-hash)', 'the ladder rungs are difficult for the protected enumerator (reference.Reference), not for exact inference in general: the independent elimination oracle solves them in milliseconds (mechanism qualification, never a general approximate-inference advantage claim)'])
    rows_sel = []; hyp = {}; pins = {}
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
    def incomplete(kind, where, msg):
        """an EXECUTION stop that is not a correctness verdict (the allowance did not permit the step): nothing downstream runs; the report is INCOMPLETE"""
        rec['not_run_steps'].append([where, kind, msg[:200]])
        if rec['stop_reason'] is None: rec['stop_reason'] = 'INCOMPLETE [%s] %s: %s' % (kind, where, msg[:200])
    def pin_for(tag, task):
        """the PINNED identity file a checker is bound to: the build's pinned scope / inventory / kernels + the task triple the snapshot must carry"""
        p = pins[tag]; return dict(sha256=p.get('pinned_sha256'), cqr_scope=p.get('cqr_scope'), full_inventory_sha256=p.get('full_inventory_sha256'), kernel_identity=p.get('kernel_identity'), task=task)
    def drift_check(tag, where):
        rec['drift_checks']['in_process'] += 1; bad = drift_now(pins[tag])
        if bad: rec['drift_checks']['drift_found'].append(dict(build=tag, where=where, keys=bad[:6])); hard('BUILD_DRIFT', where, '%s build changed after the pinned identity (%s)' % (tag, bad[:3])); return True
        return False
    try:
        # ---------------- 0. manifest, hypothesis, PINNED identities, TASK INTEGRITY + fresh snapshots (before any launch)
        M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); rec['manifest_sha256'] = sha(os.path.join(a.manifest, 'DEV_MANIFEST.json'))
        pin_p = os.path.join(a.manifest, 'LADDER_PIN.json'); pin = json.load(open(pin_p)) if os.path.exists(pin_p) else None
        for r in M['rows']:
            if r['block'] == 'change_specific_ladder': r['pinned'] = bool(pin) and r['id'] in (pin.get('pinned_ids') or [])
        hyp = json.load(open(a.hypothesis)) if a.hypothesis else dict(change='(none declared: regression / calibration run)', premise=None, expected_favorable=None, expected_near_miss=None, preserved=['every exact / structured sentinel and contract row publishes and verifies as on the accepted baseline'], question=None)
        rec['hypothesis'] = hyp
        rows_sel = [r for r in M['rows'] if (r['id'] in M['smoke_rows'] if a.mode == 'smoke' else (r['block'] not in ('change_specific_ladder', 'bank_optional') or r.get('pinned')))]
        if a.rows: want = set(a.rows.split(',')); rows_sel = [r for r in M['rows'] if r['id'] in want]
        cache_dir = os.path.join(a.manifest, 'truth_cache'); idx = TR.load_index(cache_dir) if os.path.isdir(cache_dir) else None
        pins['candidate'] = identity(cand, work_left); pins['baseline'] = identity(base, work_left)
        for tag in ('candidate', 'baseline'):
            if pins[tag].get('error'): incomplete('IDENTITY_UNAVAILABLE', tag, 'build identity could not be established within the allowance: %s' % pins[tag]['error'][:160])
            elif pins[tag].get('unlocated_inventory_keys'): hard('IDENTITY', tag, 'inventory keys without a located file (drift checks would be incomplete): %s' % pins[tag]['unlocated_inventory_keys'][:3])
            json.dump(pins[tag], open(os.path.join(RUN, 'PINNED_IDENTITY_%s.json' % tag), 'w'), indent=1)
        rec['identities'] = dict(candidate={k: v for k, v in pins['candidate'].items() if k not in ('full_inventory', 'cqr_scope', 'kernel_identity', 'paths', 'kernel_paths')}, baseline={k: v for k, v in pins['baseline'].items() if k not in ('full_inventory', 'cqr_scope', 'kernel_identity', 'paths', 'kernel_paths')},
                                 harness=dict(version=FASTLOOP_VERSION, files={f: sha(os.path.join(HERE, f)) for f in sorted(os.listdir(HERE)) if f.endswith('.py')}), ladder_pin=(pin or {'status': 'NOT PINNED (calibrate.py has not run): change-specific rows NOT RUN'}), oracle=TR.oracle_identity(base),
                                 truth_index=(dict(sha256=idx.get('_sha256'), records=len(idx.get('records') or {}), utc=idx.get('utc')) if idx and not idx.get('error') else None), truth_cache_policy=('trusted preparation index present: every cache hit must be listed in it with its file sha256; in-run computations are NOT persisted into the indexed cache' if idx else 'NO preparation index: cache records authenticated by task digest + oracle identity + self-seal only (NOT independent authentication of a coherently replaced record set)'))
        nominal = sum(r['budget_s'] * (2 if r.get('comparator') else 1) for r in rows_sel)
        rec['plan'] = dict(mode=a.mode, rows=[r['id'] for r in rows_sel], worker_nominal_s=nominal, allocations=M.get('allocations'), within_worker_cap=(nominal <= (M.get('allocations') or {}).get('worker_nominal_s_cap', 180.0)))
        rec['coverage_required'] = [dict(id=r['id'], predicates=r.get('coverage_required') or []) for r in rows_sel if r.get('coverage_required')]
        rec['required_controls']['expected'] = list(M.get('mutation_controls_required') or [])
        snap_dir = os.path.join(RUN, 'inputs')
        if os.path.exists(snap_dir): hard('SNAPSHOT_POLICY', 'inputs', 'a snapshot directory already exists in the output directory: snapshots are fresh and private, never reused')
        if not rec['hard_failures']:
            os.makedirs(snap_dir)
            for r in rows_sel:                                                           # CQR-FL-01 / AF2-03: validate pinned bytes + absence markers, SNAPSHOT into a fresh directory, verify the snapshot (hashes AND absences, exact file set)
                cur = dict(model_sha256=sha(r['model']), evidence_sha256=(sha(r['model'] + '.evid') if os.path.exists(r['model'] + '.evid') else None), query_sha256=(sha(r['model'] + '.query.json') if os.path.exists(r['model'] + '.query.json') else None))
                bad = [k for k in cur if cur[k] != r.get(k)]
                if bad: rec['integrity_failures'].append(dict(kind='TASK_INTEGRITY', id=r['id'], fields=bad, pinned={k: r.get(k) for k in bad}, on_disk={k: cur[k] for k in bad})); continue
                sd = os.path.join(snap_dir, r['id']); os.makedirs(sd); mp = os.path.join(sd, 'model.uai'); shutil.copyfile(r['model'], mp)
                for ext, key in (('.evid', 'evidence_sha256'), ('.query.json', 'query_sha256')):
                    if r.get(key) is not None: shutil.copyfile(r['model'] + ext, mp + ext)
                want_files = sorted(['model.uai'] + (['model.uai.evid'] if r.get('evidence_sha256') is not None else []) + (['model.uai.query.json'] if r.get('query_sha256') is not None else []))
                have = sorted(os.listdir(sd)); parts = TR.task_parts(mp); want_parts = TR.pinned_parts(r['model_sha256'], r['evidence_sha256'], r['query_sha256'])
                if have != want_files or parts != want_parts: rec['integrity_failures'].append(dict(kind='SNAPSHOT_INTEGRITY', id=r['id'], files=have, expected_files=want_files, parts=parts, pinned_parts=want_parts)); continue
                r['_snapshot'] = mp
            if rec['integrity_failures']: hard('TASK_INTEGRITY', 'manifest', 'pinned task bytes differ on disk / snapshot not equal to the pinned row for %s: no worker launched' % [x['id'] for x in rec['integrity_failures']])
        flush()
        # ---------------- 1. cells
        def launch(tag_b, build, arm, r, tag, order_i):
            d = os.path.join(RUN, 'cells', '%02d_%s__%s__%s' % (order_i, r['id'], tag, arm)); os.makedirs(d); out = os.path.join(d, 'worker.json'); b = r['budget_s']; mp = r['_snapshot']
            cell = dict(id=r['id'], tag=tag, arm=arm, build=build, build_tag=tag_b, dir=os.path.relpath(d, RUN), budget_s=b, seed=a.seed)
            if work_left() < b + GRACE_S + 2.0: cell.update(status='NOT_RUN', outcome='NOT_RUN', reason='global deadline: %.1f s of work left < budget %.0f s + grace' % (work_left(), b), wall_s=0.0); return cell
            if drift_check(tag_b, '%s/%s before launch' % (r['id'], tag)): cell.update(status='NOT_RUN', outcome='NOT_RUN', reason='build drift before launch', wall_s=0.0); return cell
            PY = pybin(build); dl = time.monotonic() + b
            if a.inject_missing_output == r['id'] and tag == 'candidate': cmd = [PY, '-c', 'import time; time.sleep(0.2)']           # HARNESS CONTROL: a child that writes nothing
            else: cmd = [PY, os.path.join(build, 'cex', 'pac' if arm in PAC_ARMS else 'cqr', 'worker.py'), '--input', mp, '--output', out, '--arm', arm, '--deadline', str(dl), '--budget', str(b), '--seed', a.seed, '--nonce', '%s-%s-%s' % (r['id'], tag, arm)]
            job = 'cell:%s:%s:%s' % (r['id'], tag, arm); sup = [PY, '-m', 'gbidi.supervise', '--ledger', L, '--scope', 'cqr_fastloop_' + a.mode, '--job', job, '--timeout', str(b + 1.0), '--mem-gib', '3', '--interval', '0.05', '--stdout', os.path.join(d, 'stdout.txt'), '--stderr', os.path.join(d, 'stderr.txt'), '--'] + cmd
            t = time.monotonic(); hw = hard_wait(b + 1.0 + GRACE_S + 10.0)
            try: p = subprocess.run(sup, capture_output=True, text=True, cwd=build, env=dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1'), timeout=hw); serr = p.stderr; prc = p.returncode; hw_expired = False
            except subprocess.TimeoutExpired as tx: serr = (tx.stderr or b'').decode() if isinstance(tx.stderr, bytes) else (tx.stderr or ''); prc = None; hw_expired = True
            wall = time.monotonic() - t
            try: srec = json.loads(serr.strip().splitlines()[-1])
            except Exception: srec = dict(parse_error=(serr or '')[-300:], outcome='SUPERVISOR_UNREADABLE')
            w = None; malformed = None
            if os.path.exists(out):
                try: w = json.load(open(out))
                except Exception as ex: malformed = 'worker output unreadable: %s' % str(ex)[:80]
            cell.update(wall_s=round(wall, 3), supervisor=dict(outcome=srec.get('outcome'), rc=srec.get('rc'), survivors=srec.get('survivors'), wall_s=srec.get('wall_s'), peak_MB=srec.get('peak_MB'), parse_error=srec.get('parse_error'), supervisor_process_rc=prc, hard_wait_s=round(hw, 2), hard_wait_expired=hw_expired), worker_json=(os.path.relpath(out, RUN) if os.path.exists(out) else None))
            # ---- OUTCOME RECONCILIATION (CQR-FL-04 / AF2-05): supervisor x worker record schema x cleanup
            if hw_expired: cell['failure'] = dict(kind='PROCESS_CONTAINMENT', msg='the supervisor did not return within the hard wait (%.1f s)' % hw)
            elif srec.get('survivors'): cell['failure'] = dict(kind='PROCESS_CONTAINMENT', msg='supervisor reported %s live survivors' % srec.get('survivors'))
            if srec.get('outcome') == 'TIMEOUT_KILL': cell.update(status='TIMEOUT_KILL', outcome='DEADLINE', reason='hard kill by the supervisor at the budget + grace (no graceful stop)')
            elif srec.get('outcome') == 'MEMORY_KILL': cell.update(status='MEMORY_KILL', outcome='MEMORY')
            elif w is None: cell.update(status=('MALFORMED_OUTPUT' if malformed else 'NO_OUTPUT'), outcome='NO_OUTPUT', reason=(malformed or 'the worker exited (rc %s) without writing its output' % srec.get('rc'))); cell.setdefault('failure', dict(kind='NO_OUTPUT', msg=cell['reason']))
            else:
                sp = worker_schema_problem(w, arm)
                if sp: cell.update(status='MALFORMED_OUTPUT', outcome='WORKER_PROTOCOL', reason=sp, worker_record_keys=sorted(w.keys())[:12] if isinstance(w, dict) else None); cell['failure'] = dict(kind='WORKER_PROTOCOL', msg='worker record is not a recognized terminal record: %s' % sp); return cell
                cell.update(status=w['status'], outcome=w['outcome'], route=w.get('route'), guarantee=w.get('guarantee_type'), reason=(w.get('reason') or '')[:160], worker_elapsed_s=w.get('worker_elapsed_s'), peak_rss_mb=(round((w.get('peak_rss_bytes') or 0) / 1e6, 1)), answers=w.get('answers'), bias=w.get('bias'), binding=w.get('binding'))
                if w.get('outcome') == 'FAULT' or w.get('exception_type'): cell['failure'] = dict(kind='WORKER_FAULT', msg='worker reported %s: %s' % (w.get('outcome'), (w.get('reason') or w.get('exception_type') or '')[:120]))
                elif srec.get('outcome') != 'COMPLETED' or srec.get('rc') != 0: cell['failure'] = dict(kind='ABNORMAL_EXIT', msg='supervisor outcome %s rc %s with a worker file present (status %s): numerical correctness does not excuse an abnormal process completion' % (srec.get('outcome'), srec.get('rc'), w.get('status')))
                elif w.get('status') == 'COMPLETED' and wall > b + 0.05: cell.update(status='LATE_OUTPUT', outcome='DEADLINE')
                bp = binding_problem(w.get('binding'), r, arm)                        # consumed bytes == the pinned row, EVERY field incl. absences (CQR-FL-01 / AF2-03)
                if bp: cell['failure'] = dict(kind='TASK_INTEGRITY', msg='the worker consumed bytes other than the pinned row: %s binding differs' % bp)
                if a.inject_corrupt == r['id'] and tag == 'candidate' and w.get('outcome') == 'PUBLISHED':                   # HARNESS CONTROL: a shifted COPY is verified; the honest file is kept
                    wc = _shift(copy.deepcopy(w)); out = os.path.join(d, 'worker_CORRUPTED_BY_HARNESS.json'); json.dump(wc, open(out, 'w'), default=str); cell['worker_json'] = os.path.relpath(out, RUN); cell['answers'] = wc['answers']; cell['harness_corrupted_copy'] = True
            dg = out[:-5] + '.diag.json'
            if not os.path.exists(dg): dg = os.path.join(d, 'worker.diag.json')
            cell['sidecar'] = os.path.relpath(dg, RUN) if os.path.exists(dg) else None
            return cell
        def run_checker(build, tag_b, model_path, worker_path, arm, outp, pinp, coop):
            """check_cli in the build's own process: the record is consumed ONLY when the process exits normally (rc 0); the rc / timeout / hard wait are recorded beside it"""
            hw = hard_wait(coop); t = time.monotonic()
            try: p = subprocess.run([pybin(build), os.path.join(HERE, 'check_cli.py'), build, model_path, worker_path, arm, str(coop), outp, pinp], capture_output=True, text=True, cwd=build, timeout=hw, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1')); rc = p.returncode; to = False; err = p.stderr[-300:]
            except subprocess.TimeoutExpired: rc = None; to = True; err = None
            written = json.load(open(outp)) if os.path.exists(outp) else None
            proc = dict(rc=rc, timed_out=to, hard_wait_s=round(hw, 2), cooperative_s=round(coop, 2), wall_s=round(time.monotonic() - t, 3), stderr_tail=err)
            if to: ck = dict(status='VERIFIER_TIMEOUT', fails=['the verifier process exceeded its hard wait (%.1f s)' % hw], checker_completed=False)
            elif rc != 0: ck = dict(status='VERIFIER_FAULT', fails=['the verifier process exited abnormally (rc %s)%s' % (rc, '; its record (status %s) is DISCARDED' % written.get('status') if written else ' and wrote no record')], checker_completed=False, discarded_record_status=(written or {}).get('status'))
            elif written is None or 'status' not in written: ck = dict(status='VERIFIER_NO_RESULT', fails=['the verifier process exited normally but wrote no complete record'], checker_completed=False)
            else: ck = written
            ck['process'] = proc; return ck
        def verify(cell, r):
            """the producing build's OWN checker (bounded subprocess, PINNED identity + pinned task) + authenticated independent truth; PROVED_ZERO_EVIDENCE is verified too"""
            if cell['outcome'] not in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') or not cell.get('worker_json'): cell['check'] = dict(status='NA'); cell['truth'] = dict(status='NA'); return
            dl = deadline_s(VERIFY_MAX_S)
            if dl < 2.0: cell['check'] = dict(status='NOT_RUN', reason='global deadline before verification'); cell['truth'] = dict(status='NOT_RUN'); return
            pinp = os.path.join(RUN, cell['dir'], 'pinned.json'); json.dump(pin_for(cell['build_tag'], dict(model_sha256=r['model_sha256'], evidence_sha256=r['evidence_sha256'], query_sha256=r['query_sha256'])), open(pinp, 'w'), indent=1)
            ck = run_checker(cell['build'], cell['build_tag'], r['_snapshot'], os.path.join(RUN, cell['worker_json']), cell['arm'], os.path.join(RUN, cell['dir'], 'check.json'), pinp, dl); cell['check'] = ck
            if ck['status'] == 'REFUSED':
                idf = (ck.get('identity') or {}).get('failures') or []; tbf = (ck.get('task_binding') or {}).get('failures') or []; prf = (ck.get('provenance') or {}).get('failures') or []
                kind = 'BUILD_DRIFT' if any('BUILD DRIFT' in m for m in idf) else ('TASK_INTEGRITY' if tbf else ('IDENTITY' if (idf or prf) else 'CANDIDATE_CORRECTNESS'))
                cell['failure'] = dict(kind=kind, msg='publication REFUSED by its own build: %s' % (ck.get('all_failures') or [''])[0][:160])
            elif ck['status'] in ('CHECKER_FAULT', 'VERIFIER_TIMEOUT', 'VERIFIER_NO_RESULT', 'VERIFIER_FAULT'): cell['failure'] = dict(kind='VERIFIER_FAULT', msg='%s: %s' % (ck['status'], (ck.get('fails') or [''])[0][:140]))
            elif ck['status'] == 'UNVERIFIABLE': cell['unverifiable'] = (ck.get('fails') or [''])[0][:160]
            if drift_check(cell['build_tag'], '%s/%s after verification' % (cell['id'], cell['tag'])): cell['failure'] = dict(kind='BUILD_DRIFT', msg='build changed during the cell'); return
            tdl = deadline_s(TRUTH_MAX_S)
            tr = TR.truth_for(r['_snapshot'], base, cache_dir, deadline_s=tdl, hard_timeout_s=hard_wait(tdl), persist=(idx is None)) if work_left() > 3.0 else dict(status='NOT_RUN', reason='global deadline before truth')
            cont = TR.containment(dict(outcome=cell['outcome'], answers=cell.get('answers')), tr) if cell['outcome'] == 'PUBLISHED' else TR.zero_claim_check(tr)
            cell['truth'] = dict(status=tr.get('status'), method=tr.get('method'), prep_s=tr.get('prep_s'), cache_hit=tr.get('cache_hit'), indexed=tr.get('indexed'), verdict=cont, truth_answers=((tr.get('answers') or [tr.get('Z')])[:4] if tr.get('status') == 'EXACT' else None), reason=tr.get('reason'), integrity_failures=tr.get('integrity_failures'), child_rc=tr.get('child_rc'), parts_equal_pinned=(tr.get('parts') == TR.pinned_parts(r['model_sha256'], r['evidence_sha256'], r['query_sha256']) if tr.get('parts') else None))
            if tr.get('parts') and cell['truth']['parts_equal_pinned'] is False: cell['failure'] = dict(kind='TASK_INTEGRITY', msg='the task the oracle read is not the pinned row'); return
            if cont == 'CACHE_INTEGRITY': cell['failure'] = dict(kind='HARNESS_INTEGRITY', msg='truth cache record failed authentication: %s' % (tr.get('integrity_failures') or [''])[0][:140])
            elif cont == 'ORACLE_FAULT': cell['oracle_fault'] = (tr.get('reason') or '')[:160]; rec['oracle_faults'].append([cell['id'], cell['tag'], cell['oracle_fault']])
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
        if any(p.get('error') for p in pins.values()): stop = True
        for i, r in enumerate(rows_sel):
            if stop: break
            comp = r.get('comparator'); arms = [('candidate', 'candidate', cand, r['candidate_arm'])] + ([('comparator', ('baseline' if comp['kind'] == 'baseline_N1' else 'candidate'), (base if comp['kind'] == 'baseline_N1' else cand), comp['arm'])] if comp else [])
            if i % 2 == 1 and len(arms) == 2: arms = arms[::-1]
            for tag, tag_b, build, arm in arms:
                order_i += 1; cell = launch(tag_b, build, arm, r, tag, order_i); cell['comparator_kind'] = (comp or {}).get('kind') if tag == 'comparator' else None
                if cell['status'] != 'NOT_RUN' and cell.get('outcome') != 'WORKER_PROTOCOL': verify(cell, r); activation(cell)
                else: cell['check'] = dict(status='NOT_RUN' if cell['status'] == 'NOT_RUN' else 'NA'); cell['truth'] = dict(status='NOT_RUN' if cell['status'] == 'NOT_RUN' else 'NA'); cell['predicates'] = {}
                if r.get('expected_outcome') and tag == 'candidate' and cell['status'] != 'NOT_RUN' and cell['outcome'] != r['expected_outcome'] and not cell.get('failure'): cell['failure'] = dict(kind='CONTROL_EXPECTATION', msg='expected %s, observed %s' % (r['expected_outcome'], cell['outcome']))
                if r['id'] == 'FL_CTL_zero_mass' and tag == 'candidate' and cell['outcome'] == 'PUBLISHED' and not all(x.get('lo') == x.get('hi') == '0' for x in (cell.get('answers') or [])) and not cell.get('failure'): cell['failure'] = dict(kind='CANDIDATE_CORRECTNESS', msg='zero-mass control published a nonzero answer')
                cells.append(cell)
                if cell.get('failure') and cell['failure']['kind'] not in ('NO_OUTPUT',): hard(cell['failure']['kind'], '%s/%s' % (cell['id'], cell['tag']), cell['failure']['msg'])
                elif cell.get('failure'): rec['no_output'].append([cell['id'], cell['tag'], cell['failure']['msg']])
                if rec['hard_failures']: stop = True
                flush()
                if stop: break
        done = {(c['id'], c['tag']) for c in cells}
        for r in rows_sel:
            for tag in (['candidate'] + (['comparator'] if r.get('comparator') else [])):
                if (r['id'], tag) not in done: cells.append(dict(id=r['id'], tag=tag, arm=(r['candidate_arm'] if tag == 'candidate' else r['comparator']['arm']), status='NOT_RUN', outcome='NOT_RUN', reason=(('stopped: ' + rec['stop_reason'][:100]) if rec['stop_reason'] else 'global deadline'), wall_s=0.0, check=dict(status='NOT_RUN'), truth=dict(status='NOT_RUN'), predicates={}))
        rec['not_run'] = [[c['id'], c['tag'], c.get('reason')] for c in cells if c['status'] == 'NOT_RUN']
        # ---------------- 2. REQUIRED negative controls (copies of the first honest smoke publication): pass = the checker process COMPLETES NORMALLY and REFUSES for the intended class
        hon = next((c for cid in ('FL_C35_mixed_alias', 'FL_SENT_ASIA') for c in cells if c['id'] == cid and c['tag'] == 'candidate' and c['outcome'] == 'PUBLISHED' and (c.get('check') or {}).get('status') == 'ACCEPTED' and not c.get('harness_corrupted_copy')), None)
        req = rec['required_controls']['expected']
        if hon and not stop:
            r = next(x for x in rows_sel if x['id'] == hon['id']); w = json.load(open(os.path.join(RUN, hon['worker_json']))); md = os.path.join(RUN, 'mutations'); os.makedirs(md)
            def control(name, wm, model_path, needles):
                if name not in req: return
                dl = deadline_s(MUT_MAX_S)
                if dl < 1.5: rec['mutation_controls'].append(dict(name=name, status='NOT_RUN', reason='global deadline')); return
                wp = os.path.join(md, name + '.json'); json.dump(wm, open(wp, 'w'), default=str); outp = os.path.join(md, name + '.check.json')
                pinp = os.path.join(md, name + '.pinned.json'); json.dump(pin_for('candidate', dict(model_sha256=sha(model_path), evidence_sha256=(sha(model_path + '.evid') if os.path.exists(model_path + '.evid') else None), query_sha256=(sha(model_path + '.query.json') if os.path.exists(model_path + '.query.json') else None))), open(pinp, 'w'))   # the control tests the CHECKER's refusal: the pinned task is the control's own task
                ck = run_checker(cand, 'candidate', model_path, wp, hon['arm'], outp, pinp, dl)
                intended = ck.get('checker_completed') and ck.get('status') == 'REFUSED' and (ck.get('process') or {}).get('rc') == 0 and any(any(nd in f_ for nd in needles) for f_ in (ck.get('all_failures') or []))
                rec['mutation_controls'].append(dict(name=name, status=('PASSED' if intended else 'FAILED'), checker_status=ck.get('status'), checker_completed=ck.get('checker_completed'), process=ck.get('process'), first=(ck.get('all_failures') or ck.get('fails') or [''])[0][:140], intended_needles=list(needles)))
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
        # ---------------- 4. final identity (subprocess re-identification of both builds against the PINNED identities) and verdicts
        if not stop and left() > HARD_WAIT_MARGIN_S + 2.0:
            for tag_b, build in (('candidate', cand), ('baseline', base)):
                rec['drift_checks']['subprocess'] += 1; now = identity(build, lambda: left() - HARD_WAIT_MARGIN_S, with_git=False)
                if now.get('error') or now.get('pinned_sha256') != pins[tag_b].get('pinned_sha256'): rec['drift_checks']['drift_found'].append(dict(build=tag_b, where='final re-identification', pinned=pins[tag_b].get('pinned_sha256'), now=now.get('pinned_sha256'), error=now.get('error'))); hard('BUILD_DRIFT', 'final', '%s build identity at the end (%s) differs from the pinned identity (%s)' % (tag_b, str(now.get('pinned_sha256'))[:12], str(pins[tag_b].get('pinned_sha256'))[:12])); stop = True
        elif not stop: rec['drift_checks']['final_skipped'] = 'no allowance left for the final re-identification'; rec['not_run_steps'].append(['final_identity', 'GLOBAL_DEADLINE', 'no allowance left for the final re-identification'])
        unver = [c for c in cells if c['outcome'] in ('PUBLISHED', 'PROVED_ZERO_EVIDENCE') and (c.get('check') or {}).get('status') not in ('ACCEPTED', 'REFUSED', 'UNVERIFIABLE', 'NA')]
        rec['unverified'] = [[c['id'], c['tag'], (c.get('check') or {}).get('status')] for c in unver]; rec['unverifiable'] = [[c['id'], c['tag'], c.get('unverifiable')] for c in cells if c.get('unverifiable')]
        rec['required_controls']['missing'] = missing_ctl
        CAND_KINDS = ('CANDIDATE_CORRECTNESS', 'WORKER_FAULT', 'ABNORMAL_EXIT', 'CONTROL_EXPECTATION', 'IDENTITY', 'WORKER_PROTOCOL')          # failures attributable to the candidate's execution / record; the rest are harness / verifier / build-boundary stops
        rec['correctness'] = ('FAILED' if any(x['kind'] in CAND_KINDS for x in rec['hard_failures']) else 'NOT ESTABLISHED (harness / verifier / build stop)') if rec['hard_failures'] else 'OK'
        halted = bool(rec['hard_failures'])
        rec['execution'] = 'STOP' if halted else ('INCOMPLETE' if (rec['not_run'] or rec['not_run_steps'] or rec['no_output'] or unver or missing_ctl or rec['required_controls']['failed'] or (hon is None) or rec['unverifiable'] or rec['oracle_faults']) else 'COMPLETE')
        rec['coverage'] = 'INCOMPLETE' if rec['coverage_missing'] else ('COMPLETE' if rec['coverage_required'] else 'NONE REQUIRED')
        rec['status'] = 'STOP' if halted else ('INCOMPLETE' if rec['execution'] != 'COMPLETE' or rec['coverage'] == 'INCOMPLETE' else 'COMPLETE')
    except Exception as ex:
        rec['harness_exception'] = dict(type=type(ex).__name__, msg=str(ex)[:300], traceback=traceback.format_exc()[-1500:]); rec['execution'] = 'HARNESS_EXCEPTION'; rec['status'] = 'INCOMPLETE'
        if rec['correctness'] == 'RUNNING': rec['correctness'] = 'UNKNOWN'
        if rec['coverage'] == 'RUNNING': rec['coverage'] = 'UNKNOWN'
    finally:
        try: rec['charges'] = dict(cell_receipts=sum(1 for l in open(L) if '"RECEIPT"' in l) if os.path.exists(L) else 0, cell_wall_s=round(sum(json.loads(l)['wall_s'] for l in open(L) if '"kind": "RECEIPT"' in l), 3) if os.path.exists(L) else 0.0, note='nested receipts lie INSIDE the outer supervised receipt of this run when launched through gbidi.supervise; never add them to it')
        except Exception: rec['charges'] = dict(error='ledger unreadable')
        if rec['status'] == 'RUNNING': rec['status'] = 'INCOMPLETE'
        if time.monotonic() - T0 > a.total_cap and rec['status'] == 'COMPLETE': rec['status'] = 'INCOMPLETE'; rec['execution'] = 'INCOMPLETE (cap exceeded)'
        flush(final=True)
    print(json.dumps(dict(status=rec['status'], execution=rec['execution'], correctness=rec['correctness'], coverage=rec['coverage'], elapsed_s=rec['elapsed_s'], within_cap=rec['within_cap'], cells=len(rec['cells']), not_run=len(rec['not_run']), stop=rec['stop_reason'], controls=rec['required_controls'], coverage_missing=[(x['id'], x['predicate']) for x in rec['coverage_missing']], drift_checks=rec['drift_checks'])))
    sys.exit(0 if rec['status'] == 'COMPLETE' else 1)

def _shift(wc):
    """a detectable corruption of a publication COPY: the first answer and the certificate publication moved by +1/97 (clipped to 1)"""
    a0 = wc['answers'][0]; v = str(min(F(1), F(a0['point']) + F(1, 97))); a0['lo'] = a0['hi'] = a0['point'] = v
    pub = wc['certificate']['publication']; pub['bounds'][0] = [v, v]
    if isinstance(pub.get('point'), list): pub['point'][0] = v
    return wc
if __name__ == '__main__': main()
