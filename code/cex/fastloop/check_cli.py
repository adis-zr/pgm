"""SOURCE-ISOLATED, PINNED-IDENTITY verification of ONE worker output (CQR-FL-03 repaired; repair-2 review CQR-AF2-03 / 04 / 05): runs inside the BUILD that produced the output (cwd +
sys.path = that build), so each build is verified by its OWN checker. ACCEPTANCE requires ALL of: the checker completes normally with no failure; the worker's recorded candidate_sources
EQUAL the PINNED cqr scope of this build (pinned by the runner at iteration start -- never the current build compared with itself); the build's CURRENT full inventory and kernel identity
EQUAL the pinned ones (mid-run source / kernel drift is a refusal even when the answer is unchanged); the snapshot task the checker reads has the PINNED binding (model / evidence incl.
absence / query spec); every loader provenance record names a frozen kernel of the arm's group with the PINNED digest; the worker's arm equals the planned arm. A checker exception is
CHECKER_FAULT (never an acceptance). Exits 0 only when the record was written completely; the caller requires rc 0 AND the record.
Usage: check_cli.py BUILD MODEL WORKER_JSON ARM DEADLINE_S OUT PINNED_JSON   (PINNED_JSON: {cqr_scope, full_inventory_sha256, kernel_identity, task: {model_sha256, evidence_sha256, query_sha256}})"""
import os, sys, json, time, traceback, hashlib
build, mp, wp, arm, dl, out, pinp = sys.argv[1:8]; sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); sys.path.insert(0, os.path.join(build, 'cex', 'newarm'))
import checker as CK, registry as R, kernel_identity as KI, task as TK
def hj(d): return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
ZERO_HASH = hashlib.sha256(b'0').hexdigest()
t0 = time.monotonic(); w = json.load(open(wp)); pin = json.load(open(pinp)); rec = dict(checker_version=CK.CHECKER_VERSION, build=build, pinned_identity_sha256=pin.get('sha256'))
try:
    fails, info = CK.check_worker_output(mp, w, arm=arm, deadline=time.monotonic() + float(dl)); rec['fails'] = fails; rec['checker_completed'] = True
    rec.update(attribution=info.get('attribution'), structural=info.get('structural'), commits=info.get('commits'), declines=info.get('declines'), bias=info.get('bias'), compile_outcome=info.get('compile_outcome'), zero_transfer=info.get('zero_transfer'), zero_proof=info.get('zero_proof'))
except Exception as ex:
    rec.update(fails=['CHECKER FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200])], checker_completed=False, traceback=traceback.format_exc()[-1200:])
# ---- identity: worker sources vs the PINNED scope; the build NOW vs the PINNED identity (drift); kernels NOW vs PINNED
pinned_cqr = pin.get('cqr_scope') or {}; ws = w.get('candidate_sources') or {}; id_f = []
if ws != pinned_cqr:
    miss = sorted(k for k in pinned_cqr if k not in ws); diff = sorted(k for k in pinned_cqr if k in ws and ws[k] != pinned_cqr[k]); extra = sorted(k for k in ws if k not in pinned_cqr)
    id_f.append('worker candidate_sources differ from the PINNED cqr scope (%d missing, %d differing, %d extra; e.g. %s)' % (len(miss), len(diff), len(extra), (miss + diff + extra)[:1]))
cur_inv = R.full_inventory(build); cur_cqr = R.cqr_source_inventory(build); cur_k = KI.collect(build)
if hj(cur_inv) != pin.get('full_inventory_sha256'): id_f.append('BUILD DRIFT: the build\'s current full inventory differs from the identity pinned at iteration start (%s)' % sorted(k for k in set(cur_cqr) | set(pinned_cqr) if cur_cqr.get(k) != pinned_cqr.get(k))[:2])
if hj(cur_k) != hj(pin.get('kernel_identity') or {}): id_f.append('BUILD DRIFT: the build\'s current kernel identity differs from the one pinned at iteration start')
if w.get('arm') != arm: id_f.append('worker arm %s differs from the planned arm %s' % (w.get('arm'), arm))
# ---- the task the checker read is the PINNED task (binding incl. absence)
pt = pin.get('task') or {}; task_f = []
try:
    b = TK.load_task(mp)['binding']; want = dict(model_sha256=pt.get('model_sha256'), evidence_sha256=(pt.get('evidence_sha256') if pt.get('evidence_sha256') is not None else ZERO_HASH), query_sha256=pt.get('query_sha256'))
    got = dict(model_sha256=b.get('model_sha256'), evidence_sha256=b.get('evidence_sha256'), query_sha256=b.get('query_sha256'))
    if got != want: task_f.append('the snapshot task the checker read is not the pinned row (%s)' % sorted(k for k in want if want[k] != got[k]))
except Exception as ex: task_f.append('snapshot task unreadable for the binding check: %s' % str(ex)[:80])
prov_f = KI.receipt_failures(pin.get('kernel_identity') or {}, w, arm)                      # provenance against the PINNED identity
rec.update(identity=dict(worker_sources_equal_pinned=(ws == pinned_cqr), build_equals_pinned=(hj(cur_inv) == pin.get('full_inventory_sha256')), failures=id_f), task_binding=dict(failures=task_f), provenance=dict(failures=prov_f, pinned_tags={k: (v or {}).get('binary_sha256') for k, v in (pin.get('kernel_identity') or {}).items() if k in KI.tags_needed_by(arm, None)}))
if not rec.get('checker_completed'): rec['status'] = 'CHECKER_FAULT'
elif any('UNVERIFIABLE' in f_ for f_ in rec['fails']) and not id_f and not prov_f and not task_f: rec['status'] = 'UNVERIFIABLE'
elif rec['fails'] or id_f or prov_f or task_f: rec['status'] = 'REFUSED'
else: rec['status'] = 'ACCEPTED'
rec['all_failures'] = list(rec.get('fails') or []) + id_f + task_f + prov_f; rec['checker_s'] = round(time.monotonic() - t0, 4)
tmp = out + '.tmp'; json.dump(rec, open(tmp, 'w'), indent=1, default=str); os.replace(tmp, out)
