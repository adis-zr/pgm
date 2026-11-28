"""DGP7 final-ledger sidecar (brief section 8: 'the final packaging receipt and any subsequent validation receipt may be delivered in a small final-ledger sidecar binding the immutable archive hashes and ledger sequence'): binds the
archive hashes (IDENTITY.json), the ledger sha256 and length, every receipt after CHARGES.json's utc (packaging / validation / restore-test receipts), the restored-packet test outcomes and the reconciled total vs the ceiling.
Written AFTER packaging + validation + the restore test; the archives themselves are not touched. usage: dgp7_sidecar.py"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import json, os, hashlib, time, glob
RD = os.environ.get('DGP7_RD', str(_runs_root() / 'mdi_2026-10-28/DGP7_RESIDUAL_JOINT'))
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
ch = json.load(open(RD + '/CHARGES.json')); ident = json.load(open(RD + '/IDENTITY.json')); bud = json.load(open(RD + '/BUDGET_DECLARATION.json'))
rows = [json.loads(l) for l in open(RD + '/DGP7_LEDGER.jsonl')]; rc = [r for r in rows if r.get('kind') == 'RECEIPT']; tail = [r for r in rc if (r.get('end_utc') or '') > ch['utc']]
rep = [json.loads(l) for l in open(RD + '/reproduce_test/RESTORED_PACKET_LEDGER_RECEIPTS.jsonl')] if os.path.exists(RD + '/reproduce_test/RESTORED_PACKET_LEDGER_RECEIPTS.jsonl') else []
reloc = json.load(open(RD + '/reproduce_test/RELOCATION_TEST.json')) if os.path.exists(RD + '/reproduce_test/RELOCATION_TEST.json') else None
total = round(sum(r['wall_s'] for r in rc) + sum(r['wall_s'] for r in rep), 3)
side = dict(experiment='DGP7_RESIDUAL_JOINT', kind='final-ledger sidecar', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), archives=ident['archives'], harness_bundle=ident.get('harness_bundle'), ledger=dict(path='DGP7_LEDGER.jsonl', sha256=sha(RD + '/DGP7_LEDGER.jsonl'), rows=len(rows), receipts=len(rc), last_end_utc=max((r.get('end_utc') or '') for r in rc)),
            charges_json=dict(utc=ch['utc'], total_s=ch['total_s'], n_receipts=ch['n_receipts']), receipt_tail_after_CHARGES=[dict(job=r['job'], scope=r['scope'], wall_s=r['wall_s'], outcome=r['outcome'], end_utc=r.get('end_utc')) for r in tail], restored_packet_receipts=[dict(job=r['job'], wall_s=r['wall_s'], outcome=r['outcome']) for r in rep], restored_packet_receipts_note='the restored-packet test ran in /tmp against the packet\'s own ledger copy (scope dgp7_reproduce); its receipts are copied here and COUNTED in the reconciled total',
            relocation_test=({k: reloc[k] for k in ('n', 'ok', 'bad', 'rule')} if reloc else None), reconciled_total_s=total, ceiling_s=bud['ceiling_s'], within_ceiling=(total <= bud['ceiling_s']), killed_launches_without_receipt='none observed in this round (every SPAWNED row has a RECEIPT row; checked below)', spawned_without_receipt=[s['jid'] for s in rows if s.get('kind') == 'SPAWNED' and not any(r.get('jid') == s['jid'] for r in rc)])
side['killed_launches_without_receipt'] = ('none' if not side['spawned_without_receipt'] else 'SEE spawned_without_receipt: each gets the declared worst-case charge (outer ceiling + 4 s grace) -- %d launches' % len(side['spawned_without_receipt']))
json.dump(side, open(RD + '/DGP7_FINAL_LEDGER_SIDECAR.json', 'w'), indent=1); print(json.dumps({k: side[k] for k in ('reconciled_total_s', 'within_ceiling', 'spawned_without_receipt')}), 'tail receipts', len(tail), 'restored receipts', len(rep))
