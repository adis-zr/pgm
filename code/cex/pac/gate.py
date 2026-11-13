"""Specification-driven RECEIPT GATE for the PAC pass (handoff 03 Q1; 07 "Outputs and receipts"). Authoritative specification = the frozen CAMPAIGN_MANIFEST.json
(written before any scored run; its sha256 recorded in the ledger START row of the campaign). For every planned cell: exactly ONE receipt (missing / extra / duplicate
cells fail); the receipt's case / arm / replicate / budget / seed / model+evidence hashes equal the manifest's; the worker output (when present) is bound to the same
nonce (PAC arms), the same input hashes (binding) and the candidate artifact hashes; a COMPLETED cell has returncode 0, EXIT, wall <= budget, output file present with the
receipted sha256, worker status COMPLETED, original-model shape, one-hot evidence rows, publication contract (frozen core.verify_output); guarantee_type and outcome are
consistent (PUBLISHED <-> COMPLETED; PAC/DETERMINISTIC only when PUBLISHED). Exit nonzero with every failure listed.
    python cex/pac/gate.py <RD> [--manifest CAMPAIGN_MANIFEST.json]  -> GATE_RESULT.json"""
import sys, os, json, hashlib, glob
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE)); sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import core


def main(RD, manifest_name='CAMPAIGN_MANIFEST.json'):
    RD = os.path.abspath(RD); man = json.load(open(os.path.join(RD, manifest_name))); failures = []; cells = {c['cell_id']: c for c in man['cells']}
    # frozen candidate source hashes: MANIFEST_AMENDMENT_1 (per-directory, from the manifest commit) supersedes the manifest's flat dict whose keys collided across directories
    ap = os.path.join(RD, 'MANIFEST_AMENDMENT_1_artifact_hashes.json')
    if os.path.exists(ap):
        am = json.load(open(ap)); frozen_candidate = dict(am['per_directory_hashes']['newarm']); frozen_candidate.update(am['per_directory_hashes']['pac'])
    else: frozen_candidate = {f.split('/')[-1]: h for f, h in (man.get('candidate_artifact_hashes') or {}).items()}
    receipts = {}
    for rp in glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json')):
        r = json.load(open(rp)); cid = r.get('cell_id')
        if cid in receipts: failures.append((cid, 'duplicate receipt: %s and %s' % (receipts[cid]['_path'], rp))); continue
        r['_path'] = rp; receipts[cid] = r
    for cid in cells:
        if cid not in receipts: failures.append((cid, 'planned cell without receipt (NOT_RUN)'))
    for cid in receipts:
        if cid not in cells: failures.append((cid, 'receipt for a cell not in the frozen manifest'))
    models = {}; gated = 0; checked = 0
    for cid, r in receipts.items():
        c = cells.get(cid)
        if not c: continue
        for k in ('case_id', 'arm', 'replicate', 'budget_s', 'seed', 'model_sha256', 'evidence_sha256'):
            if r.get(k) != c.get(k): failures.append((cid, 'receipt %s differs from the manifest' % k))
        if r.get('status') == 'COMPLETED':
            checked += 1; sup = r.get('supervisor') or {}
            if sup.get('rc') not in (0,): failures.append((cid, 'COMPLETED with supervisor rc %s' % sup.get('rc')))
            if sup.get('outcome') not in ('COMPLETED',): failures.append((cid, 'COMPLETED with supervisor outcome %s' % sup.get('outcome')))
            if not r.get('within_budget'): failures.append((cid, 'COMPLETED but launch-relative wall %.3f > budget %s' % (r.get('launch_relative_wall_s', -1), c['budget_s'])))
            if r.get('outcome') != 'PUBLISHED': failures.append((cid, 'COMPLETED but outcome %s' % r.get('outcome')))
            if r['arm'] in ('B0_FROZEN_V14', 'P1_PAC_CONDITIONAL', 'H1_HYBRID', 'A0_POINT', 'A1_CONDITIONAL'):
                wp = os.path.join(RD, r.get('worker_output') or 'MISSING')
                if not os.path.exists(wp): failures.append((cid, 'COMPLETED without a worker output file')); continue
                if hashlib.sha256(open(wp, 'rb').read()).hexdigest() != r.get('output_sha256'): failures.append((cid, 'worker output sha256 differs from the receipt'))
                w = json.load(open(wp))
                if w.get('status') != 'COMPLETED': failures.append((cid, 'worker status %s' % w.get('status')))
                if r['arm'] != 'B0_FROZEN_V14':
                    if w.get('nonce') != r.get('nonce'): failures.append((cid, 'worker nonce differs from the receipt (stale or foreign output)'))
                    if w.get('seed') != c.get('seed'): failures.append((cid, 'worker seed differs from the manifest'))
                    if w.get('arm') != c['arm']: failures.append((cid, 'worker arm differs'))
                    if w.get('guarantee_type') not in ('PAC', 'DETERMINISTIC'): failures.append((cid, 'completed PAC-arm output without a guarantee type'))
                    cs = w.get('candidate_sources') or {}
                    for base, h in frozen_candidate.items():
                        if base in cs and cs[base] != h: failures.append((cid, 'worker candidate source %s differs from the frozen artifact' % base))
                if r.get('guarantee_type') != (w.get('guarantee_type') or 'DETERMINISTIC'): failures.append((cid, 'receipt guarantee_type differs from the worker'))
                mp = c['model_path']
                if mp not in models: models[mp] = core.read_uai(mp)
                model, binding = models[mp]
                if w.get('binding') != binding: failures.append((cid, 'worker binding differs from the actual input files'))
                iv = w.get('intervals'); pts = w.get('points'); cards = model['cards']; ev = model.get('evidence', {})
                okshape = isinstance(iv, list) and isinstance(pts, list) and len(iv) == len(cards) and len(pts) == len(cards) and all(len(row) == k and len(pr) == k for row, pr, k in zip(iv, pts, cards))
                if not okshape: failures.append((cid, 'output shape differs from the original model')); continue
                try:
                    IV = [[(F(a), F(b)) for a, b in row] for row in iv]; PT = [[F(x) for x in row] for row in pts]; core.verify_output(IV, PT)
                    for v, a in ev.items():
                        if not all((PT[v][s] == 1 and IV[v][s] == (F(1), F(1))) if s == a else (PT[v][s] == 0 and IV[v][s] == (F(0), F(0))) for s in range(cards[v])): failures.append((cid, 'observed variable %d not one-hot' % v))
                except Exception as ex: failures.append((cid, 'publication contract: %s' % str(ex)[:80]))
                gated += 1
        else:
            if r.get('outcome') == 'PUBLISHED': failures.append((cid, 'non-COMPLETED receipt with outcome PUBLISHED'))
            if r.get('guarantee_type') in ('PAC', 'DETERMINISTIC') and r.get('outcome') != 'PROVED_ZERO_EVIDENCE': failures.append((cid, 'guarantee claimed without publication'))
    res = dict(manifest=manifest_name, planned=len(cells), receipts=len(receipts), completed_checked=checked, completed_gated=gated, failures=failures, gate_passed=not failures)
    json.dump(res, open(os.path.join(RD, 'GATE_RESULT.json'), 'w'), indent=1); print(json.dumps({k: res[k] for k in ('planned', 'receipts', 'completed_checked', 'completed_gated', 'gate_passed')})); 
    for f in failures[:40]: print('  ', f)
    return 0 if not failures else 1


if __name__ == '__main__':
    mn = sys.argv[sys.argv.index('--manifest') + 1] if '--manifest' in sys.argv else 'CAMPAIGN_MANIFEST.json'; sys.exit(main(sys.argv[1], mn))
