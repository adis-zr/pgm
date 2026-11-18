"""ONE-TIME truth cache preparation for every pinned task of a manifest (independent oracle of the baseline build; recorded cost). Usage: truth_prep.py --manifest DIR --baseline BUILD"""
import os, sys, json, time, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--deadline-s', type=float, default=60.0); a = ap.parse_args()
M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); out = []; t0 = time.monotonic()
for r in M['rows']:
    if r['block'] == 'control' and 'INVALID' in str(r.get('expected_outcome', '')): out.append(dict(id=r['id'], status='SKIPPED (INVALID_TASK fixture)')); continue
    try: rec = TR.truth_for(r['model'], os.path.abspath(a.baseline), os.path.join(a.manifest, 'truth_cache'), deadline_s=a.deadline_s)
    except Exception as ex: rec = dict(status='ERROR', reason='%s: %s' % (type(ex).__name__, str(ex)[:120]))
    out.append(dict(id=r['id'], status=rec['status'], method=rec.get('method'), prep_s=rec.get('prep_s'), reason=rec.get('reason'), n_answers=len(rec.get('answers') or []) if rec.get('answers') else (1 if rec.get('Z') else 0)))
    print(json.dumps(out[-1]), flush=True)
json.dump(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), total_s=round(time.monotonic() - t0, 3), tasks=out), open(os.path.join(a.manifest, 'TRUTH_PREP.json'), 'w'), indent=1); print(json.dumps(dict(total_s=round(time.monotonic() - t0, 3), exact=sum(1 for x in out if x['status'] == 'EXACT'), unresolved=[x['id'] for x in out if x['status'] not in ('EXACT',) and 'SKIPPED' not in x['status']])))
