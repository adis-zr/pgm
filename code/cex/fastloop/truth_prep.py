"""ONE-TIME truth cache preparation for every pinned task of a manifest (independent oracle of the ACCEPTED build in a bounded subprocess; recorded one-time cost; authenticated records)
and the TRUSTED PREPARATION INDEX (TRUTH_INDEX.json: task digest -> record file sha256; its sha256 recorded in TRUTH_PREP.json). Run as a supervised job. Refuses a cache that already
carries an index (prepare a fresh cache directory instead). Usage: truth_prep.py --manifest DIR --baseline BUILD [--deadline-s 60] [--cache DIR]"""
import os, sys, json, time, argparse
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); import truth as TR
ap = argparse.ArgumentParser(); ap.add_argument('--manifest', required=True); ap.add_argument('--baseline', required=True); ap.add_argument('--deadline-s', type=float, default=60.0); ap.add_argument('--cache', default=None); a = ap.parse_args()
M = json.load(open(os.path.join(a.manifest, 'DEV_MANIFEST.json'))); out = []; t0 = time.monotonic(); base = os.path.abspath(a.baseline); cache = os.path.abspath(a.cache) if a.cache else os.path.join(a.manifest, 'truth_cache')
if os.path.exists(os.path.join(cache, TR.INDEX_NAME)): raise SystemExit('refuse: %s already carries a preparation index (immutable); prepare a fresh cache directory' % cache)
for r in M['rows']:
    if r['block'] == 'control' and 'INVALID' in str(r.get('expected_outcome', '')): out.append(dict(id=r['id'], status='SKIPPED (INVALID_TASK fixture)')); continue
    rec = TR.truth_for(r['model'], base, cache, deadline_s=a.deadline_s, index=None)
    if rec.get('parts') != TR.pinned_parts(r['model_sha256'], r['evidence_sha256'], r['query_sha256']): rec = dict(rec, status='TASK_INTEGRITY', reason='the task bytes on disk are not the pinned row')
    out.append(dict(id=r['id'], status=rec['status'], method=rec.get('method'), prep_s=rec.get('prep_s'), cache_hit=rec.get('cache_hit'), reason=rec.get('reason'), integrity=rec.get('integrity_failures'), child_rc=rec.get('child_rc'))); print(json.dumps(out[-1]), flush=True)
faults = [x['id'] for x in out if x['status'] in ('ORACLE_FAULT', 'CACHE_INTEGRITY', 'TASK_INTEGRITY')]
idx_sha = TR.write_index(cache, base, note='prepared by truth_prep.py for %s' % a.manifest) if not faults else None
prep_out = os.path.join(a.manifest, 'TRUTH_PREP.json'); prep_out = prep_out if not os.path.exists(prep_out) else os.path.join(a.manifest, 'TRUTH_PREP_%s.json' % time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))        # earlier preparation records are never overwritten
json.dump(dict(schema='CQR_FASTLOOP_TRUTH_PREP_V2', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), total_s=round(time.monotonic() - t0, 3), oracle=TR.oracle_identity(base), cache_dir=cache, index_sha256=idx_sha, index_written=(idx_sha is not None), faults=faults, tasks=out, supervised_jid=os.environ.get('GBIDI_PARENT_JID')), open(prep_out, 'w'), indent=1)
print(json.dumps(dict(total_s=round(time.monotonic() - t0, 3), exact=sum(1 for x in out if x['status'] == 'EXACT'), unresolved=[x['id'] for x in out if x['status'] not in ('EXACT',) and 'SKIPPED' not in x['status']], faults=faults, index_sha256=idx_sha)))
sys.exit(0 if not faults else 1)
