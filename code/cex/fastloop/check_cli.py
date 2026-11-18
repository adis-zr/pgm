"""SOURCE-ISOLATED, BUILD-BOUND verification of ONE worker output (CQR-FL-03 repaired): runs inside the BUILD that produced the output (cwd + sys.path = that build), so each build is
verified by its OWN checker under its own identity. ACCEPTANCE requires ALL of: the checker completes normally with no failure; the worker's recorded candidate_sources EQUAL the build's
cqr scope (a mismatch is a REFUSAL, never a note); every loader provenance record in the output names a frozen kernel of the arm's group with the frozen digest (kernel_identity.receipt_failures
against the build's own collected identity); the worker's arm equals the planned arm. A checker exception is a CHECKER_FAULT status (never a refusal for a reason, never an acceptance).
Writes JSON {status: ACCEPTED | REFUSED | CHECKER_FAULT | UNVERIFIABLE, fails, identity, provenance, attribution...}. Usage: check_cli.py BUILD MODEL WORKER_JSON ARM DEADLINE_S OUT"""
import os, sys, json, time, traceback
build, mp, wp, arm, dl, out = sys.argv[1:7]; sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); sys.path.insert(0, os.path.join(build, 'cex', 'newarm'))
import checker as CK, registry as R, kernel_identity as KI
t0 = time.monotonic(); w = json.load(open(wp)); rec = dict(checker_version=CK.CHECKER_VERSION, build=build)
try:
    fails, info = CK.check_worker_output(mp, w, arm=arm, deadline=time.monotonic() + float(dl)); rec['fails'] = fails; rec['checker_completed'] = True
    rec.update(attribution=info.get('attribution'), structural=info.get('structural'), commits=info.get('commits'), declines=info.get('declines'), bias=info.get('bias'), compile_outcome=info.get('compile_outcome'), zero_transfer=info.get('zero_transfer'), zero_proof=info.get('zero_proof'))
except Exception as ex:
    rec.update(fails=['CHECKER FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200])], checker_completed=False, traceback=traceback.format_exc()[-1200:])
src = R.cqr_source_inventory(build); ws = w.get('candidate_sources') or {}
id_f = []
if ws != src:
    miss = sorted(k for k in src if k not in ws); diff = sorted(k for k in src if k in ws and ws[k] != src[k]); extra = sorted(k for k in ws if k not in src)
    id_f.append('worker candidate_sources differ from the build cqr scope (%d missing, %d differing, %d extra; e.g. %s)' % (len(miss), len(diff), len(extra), (miss + diff + extra)[:1]))
if w.get('arm') != arm: id_f.append('worker arm %s differs from the planned arm %s' % (w.get('arm'), arm))
frozen = KI.collect(build); prov_f = KI.receipt_failures(frozen, w, arm)
rec.update(identity=dict(worker_sources_equal_build=(ws == src), failures=id_f), provenance=dict(failures=prov_f, frozen_tags={k: (v or {}).get('binary_sha256') for k, v in frozen.items() if k in KI.tags_needed_by(arm, None)}))
if not rec.get('checker_completed'): rec['status'] = 'CHECKER_FAULT'
elif any('UNVERIFIABLE' in f_ for f_ in rec['fails']) and not id_f and not prov_f: rec['status'] = 'UNVERIFIABLE'
elif rec['fails'] or id_f or prov_f: rec['status'] = 'REFUSED'
else: rec['status'] = 'ACCEPTED'
rec['all_failures'] = list(rec.get('fails') or []) + id_f + prov_f; rec['checker_s'] = round(time.monotonic() - t0, 4)
json.dump(rec, open(out, 'w'), indent=1, default=str)
