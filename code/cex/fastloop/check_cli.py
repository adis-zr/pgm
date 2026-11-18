"""SOURCE-ISOLATED checker call: run in the BUILD that produced a worker output (cwd + sys.path = that build), so every build is verified by its OWN checker under its own identity;
an old certificate's version mismatch is a refusal, never patched. Writes {fails, info(attribution, structural, commits, declines, bias)} as JSON. Usage: check_cli.py BUILD MODEL WORKER_JSON ARM DEADLINE_S OUT"""
import os, sys, json, time
build, mp, wp, arm, dl, out = sys.argv[1:7]; sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); sys.path.insert(0, os.path.join(build, 'cex', 'newarm'))
import checker as CK, registry as R
t0 = time.monotonic(); w = json.load(open(wp))
try: fails, info = CK.check_worker_output(mp, w, arm=arm, deadline=time.monotonic() + float(dl))
except Exception as ex: fails, info = ['CHECKER FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200])], {}
src_ok = (w.get('candidate_sources') == R.cqr_source_inventory(build))
json.dump(dict(fails=fails, checker_s=round(time.monotonic() - t0, 4), checker_version=CK.CHECKER_VERSION, worker_sources_equal_build=src_ok,
               attribution=(info.get('attribution') if isinstance(info, dict) else None), structural=(info.get('structural') if isinstance(info, dict) else None), commits=(info.get('commits') if isinstance(info, dict) else None), declines=(info.get('declines') if isinstance(info, dict) else None), bias=(info.get('bias') if isinstance(info, dict) else None), compile_outcome=(info.get('compile_outcome') if isinstance(info, dict) else None)), open(out, 'w'), indent=1, default=str)
