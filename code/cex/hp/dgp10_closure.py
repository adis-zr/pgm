"""DGP10 EXTERNAL CLOSURE manifest (FROZEN_EXPERIMENT_SPEC section 9: 'Final receipts produced after archive closure must be separately shipped and hashed in the external closure manifest'): hashes IDENTITY_EXTERNAL.json, VALIDATION.json,
the restore-test directory's receipts (reproduce_test/**), DGP10_FINAL_LEDGER_SIDECAR.json, the ledger itself and the post-archive receipt tail, written OUTSIDE the archives (next to them AND into the records; excluded from any zip).
usage: dgp10_closure.py"""
import os, json, hashlib, time, glob
RD = os.environ.get('DGP10_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP10_QUERY_RESPONSE'); W = os.environ.get('DGP10_ARCHIVE_DIR', '/Users/adis/Workspace')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
ext = json.load(open(os.path.join(RD, 'IDENTITY_EXTERNAL.json'))); files = {}
for rel in ['IDENTITY_EXTERNAL.json', 'VALIDATION.json', 'DGP10_FINAL_LEDGER_SIDECAR.json', 'DGP10_LEDGER.jsonl', 'RESTORE_TEST_log.txt'] + sorted(os.path.relpath(p, RD) for p in glob.glob(os.path.join(RD, 'reproduce_test*', '**', '*'), recursive=True) if os.path.isfile(p) and '/restored/' not in p and not p.endswith('.pyc')):
    p = os.path.join(RD, rel)
    if os.path.exists(p): files[rel] = dict(sha256=sha(p), bytes=os.path.getsize(p))
rows = [json.loads(l) for l in open(os.path.join(RD, 'DGP10_LEDGER.jsonl'))]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; after = [r for r in rc if (r.get('start_utc') or '') >= ext['utc']]
out = dict(experiment='DGP10_QUERY_RESPONSE', kind='EXTERNAL closure manifest (written after the archives and every post-archive receipt; never a member of any zip)', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), archives=ext['archives'], post_archive_files=files, post_archive_receipts=[dict(job=r['job'], wall_s=round(r['wall_s'], 3), outcome=r['outcome'], start_utc=r['start_utc']) for r in after], post_archive_total_s=round(sum(r['wall_s'] for r in after), 3), ledger_total_s=round(sum(r['wall_s'] for r in rc), 3), n_receipts=len(rc), unique_jids=(len({r['jid'] for r in rc}) == len(rc)),
           restore_test_dirs=sorted(os.path.basename(p) for p in glob.glob(os.path.join(RD, 'reproduce_test*')) if os.path.isdir(p)), note='the files named here are DELIVERED next to the archives (records tree) and hashed; nothing undelivered is named')
json.dump(out, open(os.path.join(W, 'DGP10_CLOSURE_EXTERNAL.json'), 'w'), indent=1); json.dump(out, open(os.path.join(RD, 'CLOSURE_EXTERNAL.json'), 'w'), indent=1); print(json.dumps(dict(files=len(files), post_archive_receipts=len(after), post_archive_total_s=out['post_archive_total_s'], ledger_total_s=out['ledger_total_s'], restore_dirs=out['restore_test_dirs'])))
