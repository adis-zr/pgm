"""ONE-TIME truth cache preparation for every pinned task of a manifest (independent oracle of the ACCEPTED build in a bounded subprocess; recorded one-time cost; authenticated records). Usage: truth_prep.py --manifest DIR --baseline BUILD [--deadline-s 60]"""
import os, sys, json, time, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--deadline-s', type=float, default=60.0); a = ap.parse_args()
M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); out = []; t0 = time.monotonic(); base = os.path.abspath(a.baseline)
for r in M['rows']:
    if r['block'] == 'control' and 'INVALID' in str(r.get('expected_outcome', '')): out.append(dict(id=r['id'], status='SKIPPED (INVALID_TASK fixture)')); continue
    rec = TR.truth_for(r['model'], base, os.path.join(a.manifest, 'truth_cache'), deadline_s=a.deadline_s)
    out.append(dict(id=r['id'], status=rec['status'], method=rec.get('method'), prep_s=rec.get('prep_s'), cache_hit=rec.get('cache_hit'), reason=rec.get('reason'), integrity=rec.get('integrity_failures'))); print(json.dumps(out[-1]), flush=True)
json.dump(dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), total_s=round(time.monotonic() - t0, 3), oracle=TR.oracle_identity(base), tasks=out), open(os.path.join(a.manifest, 'TRUTH_PREP.json'), 'w'), indent=1)
print(json.dumps(dict(total_s=round(time.monotonic() - t0, 3), exact=sum(1 for x in out if x['status'] == 'EXACT'), unresolved=[x['id'] for x in out if x['status'] not in ('EXACT',) and 'SKIPPED' not in x['status']])))
