"""DGP9 final-ledger sidecar (review RV8 / RPA2 repaired): binds the EXTERNAL identity manifest (IDENTITY_EXTERNAL.json, written outside the results zip) by hash, reconciles EVERY receipt of the main ledger plus the restored-packet
test's receipts with UNIQUE ids (a duplicate jid is reported), lists every receipt after CHARGES.json (analysis / packaging / validation / restore-test runs), and states the reconciled total against the declared ceiling. Written
AFTER packaging + validation + the restore test; the archives are not touched; the sidecar itself is attested by its own sha256 in the records commit. usage: dgp9_sidecar.py (env DGP9_RD)"""
import json, os, hashlib, time, glob
RD = os.environ.get('DGP9_RD', '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP9_SPECTRAL_HEATBATH_CONTINUATION')
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
ch = json.load(open(RD + '/CHARGES.json')); ext = json.load(open(RD + '/IDENTITY_EXTERNAL.json')); bud = json.load(open(RD + '/BUDGET_DECLARATION.json'))
rows = [json.loads(l) for l in open(RD + '/DGP9_LEDGER.jsonl')]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; tail = [r for r in rc if (r.get('end_utc') or '') > ch['utc']]
rep = []
for p in sorted(glob.glob(RD + '/reproduce_test*/RESTORED_PACKET_LEDGER_RECEIPTS.jsonl')): rep += [dict(json.loads(l), _source=os.path.relpath(p, RD)) for l in open(p)]
ids = [r['jid'] for r in rc] + [r['jid'] for r in rep]; dup = sorted({j for j in ids if ids.count(j) > 1})
arch = ext['archives']; actual = {}
for k, v in arch.items():
    p = os.path.expanduser(v['path']); actual[k] = dict(exists=os.path.exists(p), sha256_matches=(os.path.exists(p) and sha(p) == v['sha256']), bytes_match=(os.path.exists(p) and os.path.getsize(p) == v['bytes']))
total = round(sum(r['wall_s'] for r in rc) + sum(r['wall_s'] for r in rep), 3)
side = dict(experiment='DGP9_SPECTRAL_HEATBATH_CONTINUATION', kind='final-ledger sidecar', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), external_identity=dict(path='IDENTITY_EXTERNAL.json (copy; the original sits next to the results zip)', sha256=sha(RD + '/IDENTITY_EXTERNAL.json'), archives=arch, archives_verified_now=actual), harness_bundle=ext.get('harness_bundle'),
            ledger=dict(path='DGP9_LEDGER.jsonl', sha256=sha(RD + '/DGP9_LEDGER.jsonl'), rows=len(rows), receipts=len(rc), last_end_utc=max((r.get('end_utc') or '') for r in rc), unique_receipt_ids=(not dup), duplicate_ids=dup), charges_json=dict(utc=ch['utc'], total_s=ch['total_s'], n_receipts=ch['n_receipts']),
            receipt_tail_after_CHARGES=[dict(jid=r['jid'], job=r['job'], scope=r['scope'], wall_s=r['wall_s'], outcome=r['outcome'], end_utc=r.get('end_utc')) for r in tail], restored_packet_receipts=[dict(jid=r['jid'], job=r['job'], wall_s=r['wall_s'], outcome=r['outcome'], source=r['_source']) for r in rep], restored_packet_receipts_note='the restored-packet test writes its receipts into the restored copy\'s ledger; they are collected under reproduce_test*/ and counted here (every run, not only the last)',
            reconciled_total_s=total, ceiling_s=bud['ceiling_s'], within_ceiling=(total <= bud['ceiling_s']), spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r.get('jid') == s['jid'] for r in rc)], by_scope_s={s: round(sum(r['wall_s'] for r in rc if r['scope'] == s), 3) for s in sorted({r['scope'] for r in rc})}, allocations=bud['allocations'], reassignments=bud.get('reassignments'))
json.dump(side, open(RD + '/DGP9_FINAL_LEDGER_SIDECAR.json', 'w'), indent=1); print(json.dumps({k: side[k] for k in ('reconciled_total_s', 'within_ceiling', 'spawned_without_receipt')}), 'tail', len(tail), 'restored', len(rep), 'dup ids', dup, 'archives', actual)
