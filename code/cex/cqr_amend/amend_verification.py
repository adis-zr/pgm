"""amend_verification.py -- a SUCCESSOR verification record for a completed shard whose original gate FAILED on verifier-completeness grounds.
  prepare  --original RD --verifier-build BUILD --out AMEND_DIR [--allowed-verifier-files cqr/checker.py,cqr/registry.py]
           hashes every original receipt / worker output / task file (ORIGINAL_INVENTORY.json), binds the PRODUCER identity (the original manifest's frozen inventory + kernel identity,
           f672b69) and the VERIFIER identity (the current build's inventory + checker version), REQUIRES that every differing source be in the declared verifier-only set (any producer-side
           difference is an execution-affecting change -> REFUSED), records the unified diff of every allowed file for review, and writes VERIFICATION_AMENDMENT_MANIFEST.json with
           status PREPARED_NOT_EXECUTED. Nothing in RD is modified.
  execute  --amend AMEND_DIR [--cells N --label TEXT]   (ONLY after the amendment is reviewed and approved; `--cells` limits a MECHANICS CHECK that is never the amended gate)
           re-verifies EVERY original receipt uniformly: receipt / worker / task bytes must equal the prepared inventory; the worker's candidate_sources must equal the PRODUCER cqr scope;
           loader provenance against the ORIGINAL kernel identity; the VERIFIER build's checker under replay_factor x budget; baseline arms through the frozen pac gate cell check.
           Writes GATE_RESULT_AMENDED.json (+ the gated set) in AMEND_DIR; the original GATE_RESULT.json (FAILED) is untouched and referenced by hash.
  The campaign's unrun shards are NOT touched by this tool (continuation is a separate approved decision; see the manifest's `continuation_policy`)."""
import os, sys, json, time, hashlib, glob, argparse, difflib, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from __init__ import AMEND_VERSION
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def hjson(d): return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
def load_build(build):
    """import the VERIFIER build's gate exactly as the campaign does (gate.py arranges the pac / cqr module paths itself: the pac registry is `registry`, the cqr registry is loaded as `cqr_registry`)"""
    sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); import gate as G
    return G.R, G.CK, G, G.KI, G.TK
def prepare(a):
    RD = os.path.abspath(a.original); V = os.path.abspath(a.verifier_build); OUT = os.path.abspath(a.out); os.makedirs(OUT, exist_ok=True)
    if os.path.exists(os.path.join(OUT, 'VERIFICATION_AMENDMENT_MANIFEST.json')): raise SystemExit('refuse: amendment manifest exists (immutable; use a new directory)')
    R, CK, G, KI, TK = load_build(V); t0 = time.monotonic()
    man = json.load(open(os.path.join(RD, 'CAMPAIGN_MANIFEST.json'))); st = json.load(open(os.path.join(RD, 'CAMPAIGN_START.json'))); g0 = json.load(open(os.path.join(RD, 'GATE_RESULT.json')))
    producer_inv = man['candidate_artifact_hashes']; verifier_inv = R.full_inventory(V)
    differ = sorted(k for k in set(producer_inv) | set(verifier_inv) if producer_inv.get(k) != verifier_inv.get(k)); allowed = sorted(a.allowed_verifier_files.split(','))
    bad = [k for k in differ if k not in allowed]
    diffs = {}
    for k in differ:
        old_p = None
        try:
            full = subprocess.run(['git', '-C', V, 'show', '%s:code/cex/%s' % (man.get('producer_commit') or a.producer_commit, k)], capture_output=True, text=True)
            old_txt = full.stdout if full.returncode == 0 else None
        except Exception: old_txt = None
        new_txt = open(os.path.join(V, 'cex', k)).read() if os.path.exists(os.path.join(V, 'cex', k)) else ''
        diffs[k] = dict(producer_sha256=producer_inv.get(k), verifier_sha256=verifier_inv.get(k), unified_diff=(''.join(difflib.unified_diff(old_txt.splitlines(True), new_txt.splitlines(True), 'producer/' + k, 'verifier/' + k)) if old_txt is not None else 'producer source not recoverable from git (%s)' % a.producer_commit))
    # original inventory: every receipt, worker output, sidecar, task file
    inv = dict(receipts={}, worker_outputs={}, tasks={}); n_missing = 0
    for rp in sorted(glob.glob(os.path.join(RD, 'cells', '*', 'receipt.json'))):
        r = json.load(open(rp)); inv['receipts'][r['cell_id']] = dict(path=os.path.relpath(rp, RD), sha256=sha(rp), output_sha256_recorded=r.get('output_sha256'), outcome=r['outcome'], status=r['status'], arm=r['arm'])
        if r.get('worker_output'):
            wp = os.path.join(RD, r['worker_output'])
            if os.path.exists(wp): inv['worker_outputs'][r['cell_id']] = dict(path=r['worker_output'], sha256=sha(wp), equals_receipt=(sha(wp) == r.get('output_sha256')))
            else: inv['worker_outputs'][r['cell_id']] = dict(path=r['worker_output'], MISSING=True); n_missing += 1
    for c in man['cells']:
        mp = c['model_path']
        if mp in inv['tasks']: continue
        inv['tasks'][mp] = dict(model_sha256=(sha(mp) if os.path.exists(mp) else None), evidence_sha256=(sha(mp + '.evid') if os.path.exists(mp + '.evid') else hashlib.sha256(b'0').hexdigest()), query_sha256=(sha(mp + '.query.json') if os.path.exists(mp + '.query.json') else None), frozen=dict(model=c['model_sha256'], evidence=c['evidence_sha256'], query=c['query_sha256']))
        inv['tasks'][mp]['equals_frozen'] = (inv['tasks'][mp]['model_sha256'] == c['model_sha256'] and inv['tasks'][mp]['evidence_sha256'] == c['evidence_sha256'] and (inv['tasks'][mp]['query_sha256'] or None) == (c['query_sha256'] or None))
    json.dump(inv, open(os.path.join(OUT, 'ORIGINAL_INVENTORY.json'), 'w'), indent=1); inv_sha = sha(os.path.join(OUT, 'ORIGINAL_INVENTORY.json'))
    task_bad = [p for p, v in inv['tasks'].items() if not v['equals_frozen']]; out_bad = [k for k, v in inv['worker_outputs'].items() if v.get('MISSING') or not v.get('equals_receipt')]
    am = dict(schema='CQR_VERIFICATION_AMENDMENT_MANIFEST_V1', version=AMEND_VERSION, status=('REFUSED: producer-side sources differ (%s): an execution-affecting change needs a NEW candidate identity, not an amendment' % bad if bad else ('REFUSED: original inputs / outputs do not match their frozen hashes' if (task_bad or out_bad) else 'PREPARED_NOT_EXECUTED')), prepared_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              original=dict(run_dir=RD, manifest_sha256=sha(os.path.join(RD, 'CAMPAIGN_MANIFEST.json')), campaign_start_sha256=sha(os.path.join(RD, 'CAMPAIGN_START.json')), gate_result_sha256=sha(os.path.join(RD, 'GATE_RESULT.json')), gate_passed=g0.get('gate_passed'), gate_failures=len(g0.get('failures') or []), gate_failures_all_unverifiable=all('UNVERIFIABLE' in f_[1] for f_ in (g0.get('failures') or [])), gate_counters=g0.get('counters'), note='the ORIGINAL gate verdict (FAILED) is RETAINED; this amendment writes a separate record'),
              producer_identity=dict(commit=a.producer_commit, full_inventory_sha256=hjson(producer_inv), artifacts=len(producer_inv), cqr_scope={k: v for k, v in producer_inv.items() if R.is_cqr_scope_key(k)}, cqr_scope_sha256=hjson({k: v for k, v in producer_inv.items() if R.is_cqr_scope_key(k)}), kernel_identity_sha256=hjson(man['kernel_identity']), campaign_start_artifact_hashes_sha256=st.get('artifact_hashes_sha256')),
              verifier_identity=dict(build=V, git_head=subprocess.run(['git', '-C', V, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(), full_inventory_sha256=hjson(verifier_inv), artifacts=len(verifier_inv), cqr_scope_sha256=hjson(R.cqr_source_inventory(V)), checker_version=CK.CHECKER_VERSION, gate_version=G.GATE_VERSION, amendment_tool_sha256=sha(os.path.abspath(__file__))),
              differing_sources=differ, allowed_verifier_only_files=allowed, producer_side_differences=bad, source_diffs=diffs,
              original_inventory=dict(file='ORIGINAL_INVENTORY.json', sha256=inv_sha, receipts=len(inv['receipts']), worker_outputs=len(inv['worker_outputs']), outputs_missing_or_mismatched=out_bad, tasks=len(inv['tasks']), tasks_not_equal_frozen=task_bad),
              policy=dict(uniform='EVERY original receipt is re-verified (not only the failed ones) by the verifier build\'s checker under replay_factor x budget; baseline arms through the frozen pac gate cell check', preserved='original worker files, times, censoring, seeds, tolerances, arm definitions, scoring and the FAILED original gate are untouched and referenced by hash', identity='worker candidate_sources == PRODUCER cqr scope (original frozen inventory); loader provenance against the ORIGINAL kernel identity; receipts / outputs / tasks must equal ORIGINAL_INVENTORY.json', charging='every execution of this amendment is a separate supervised job (scope cqr_verification_amendment) charged in AMEND_DIR/CQR_LEDGER.jsonl; never added to the original cells', output='GATE_RESULT_AMENDED.json + GATED_SET_AMENDED.json in AMEND_DIR; a report may be derived from them by the frozen report tool with --manifest pointing at the original manifest and the amended gate'),
              continuation_policy='the unrun shards (A2..A5, stage check, B1..B4) are NOT touched by this amendment; if the overseer approves continuation under the ORIGINAL producer identity f672b69 with the AMENDED verifier for their gates, each later shard runs its dispatcher from the f672b69 worktree unchanged and its finalize gate is executed through this tool (execute on that shard) instead of finalize.sh\'s gate step -- an explicit, recorded protocol deviation; alternatively a NEW candidate identity (producers unchanged, verifier repaired) is registered and the campaign restarted as a successor; either path is the overseer\'s decision',
              commands=dict(execute='python cex/cqr_amend/amend_verification.py execute --amend %s --label "amended A1 verification"' % OUT, mechanics_check='python cex/cqr_amend/amend_verification.py execute --amend %s --cells 3 --label "MECHANICS CHECK (3 cells; not the amended gate)"' % OUT), prepare_wall_s=round(time.monotonic() - t0, 3))
    json.dump(am, open(os.path.join(OUT, 'VERIFICATION_AMENDMENT_MANIFEST.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(status=am['status'], differing_sources=differ, producer_side_differences=bad, receipts=len(inv['receipts']), outputs_bad=len(out_bad), tasks_bad=len(task_bad), verifier=am['verifier_identity']['checker_version'][:40], wall_s=am['prepare_wall_s'])))
    return 0 if am['status'] == 'PREPARED_NOT_EXECUTED' else 1
def execute(a):
    AM = os.path.abspath(a.amend); am = json.load(open(os.path.join(AM, 'VERIFICATION_AMENDMENT_MANIFEST.json'))); RD = am['original']['run_dir']; V = am['verifier_identity']['build']
    if not am['status'].startswith('PREPARED'): raise SystemExit('refuse: amendment status %s' % am['status'])
    R, CK, G, KI, TK = load_build(V); PG = G.PG
    inv = json.load(open(os.path.join(AM, 'ORIGINAL_INVENTORY.json')))
    if sha(os.path.join(AM, 'ORIGINAL_INVENTORY.json')) != am['original_inventory']['sha256']: raise SystemExit('refuse: ORIGINAL_INVENTORY.json altered')
    if hjson(R.full_inventory(V)) != am['verifier_identity']['full_inventory_sha256']: raise SystemExit('refuse: the verifier build on disk differs from the prepared verifier identity')
    man = json.load(open(os.path.join(RD, 'CAMPAIGN_MANIFEST.json')))
    if sha(os.path.join(RD, 'CAMPAIGN_MANIFEST.json')) != am['original']['manifest_sha256'] or sha(os.path.join(RD, 'GATE_RESULT.json')) != am['original']['gate_result_sha256']: raise SystemExit('refuse: the original manifest / gate result changed since preparation')
    producer_cqr = am['producer_identity']['cqr_scope']; frozen_cand = {k: v for k, v in man['candidate_artifact_hashes'].items() if R.PR.scope_of_key(k) == 'candidate'}; frozen_b0 = {k: v for k, v in man['candidate_artifact_hashes'].items() if R.PR.scope_of_key(k) == 'b0_frozen_v14'}
    cells = {c['cell_id']: c for c in man['cells']}; failures = []; counters = dict(checked=0, gated=0, pac_verified=0, cqr_checked=0, cqr_verified=0, zero_checked=0, zero_verified=0, unverifiable=0, baseline_checked=0, cqr_provenance_checked=0)
    def fail(cid, m): failures.append((cid, m))
    t0 = time.monotonic(); gated = []; EPS = __import__('fractions').Fraction(str((man.get('task') or {}).get('epsilon', '1/200'))); models = {}; order = sorted(inv['receipts']); limit = a.cells
    if limit: order = [c for c in order if inv['receipts'][c]['outcome'] == 'PROVED_ZERO_EVIDENCE'][:max(1, limit - 2)] + [c for c in order if inv['receipts'][c]['outcome'] == 'PUBLISHED' and inv['receipts'][c]['arm'] == 'N1_CQR'][:1] + [c for c in order if inv['receipts'][c]['outcome'] == 'PUBLISHED' and inv['receipts'][c]['arm'] == 'H1_HYBRID'][:1]
    for cid in order:
        rec0 = inv['receipts'][cid]; rp = os.path.join(RD, rec0['path'])
        if sha(rp) != rec0['sha256']: fail(cid, 'receipt bytes differ from ORIGINAL_INVENTORY'); continue
        r = json.load(open(rp)); c = cells.get(cid)
        if not c: fail(cid, 'receipt for a cell not in the original manifest'); continue
        entry = dict(cell_id=cid, receipt_sha256=rec0['sha256'], output_sha256=r.get('output_sha256'), status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=c['arm'], cohort=c['cohort'], budget_s=c['budget_s'], verified_by=am['verifier_identity']['checker_version'][:60]); nf = len(failures)
        wo = inv['worker_outputs'].get(cid)
        if wo and not wo.get('MISSING') and sha(os.path.join(RD, wo['path'])) != wo['sha256']: fail(cid, 'worker output bytes differ from ORIGINAL_INVENTORY')
        tk = inv['tasks'].get(c['model_path']) or {}
        if not tk.get('equals_frozen') or (sha(c['model_path']) if os.path.exists(c['model_path']) else None) != tk.get('model_sha256'): fail(cid, 'task bytes differ from the frozen / prepared inventory')
        if len(failures) == nf:
            G._cell_paths.clear(); PG._cell_paths.clear()
            try:
                if R.validator_of(c['arm']) == 'cqr_candidate': G._check_cqr_cell(RD, cid, r, c, man, producer_cqr, failures, fail, G.REPLAY_FACTOR, counters)        # worker identity vs the PRODUCER scope; the checker is the VERIFIER build's
                else:
                    n0 = counters['checked']; G.bind_task_dependencies(c, fail); PG._check_cell(RD, cid, r, c, man, frozen_cand, frozen_b0, models, failures, fail, EPS, G.REPLAY_FACTOR, counters); counters['baseline_checked'] += counters['checked'] - n0
                if man.get('kernel_identity') and r.get('worker_output') and os.path.exists(os.path.join(RD, r['worker_output'])) and KI.tags_needed_by(c['arm']):
                    w_ = json.load(open(os.path.join(RD, r['worker_output'])))
                    for m_ in KI.receipt_failures(man['kernel_identity'], w_, c['arm']): fail(cid, 'loaded kernel provenance (ORIGINAL identity): ' + m_)
                    if R.validator_of(c['arm']) == 'cqr_candidate': counters['cqr_provenance_checked'] += 1
            except Exception as ex: fail(cid, 'AMENDED CHECK FAULT: %s: %s' % (type(ex).__name__, str(ex)[:160]))
        entry['verified'] = (len(failures) == nf); entry['verified_attribution'] = G._attrib.get(cid); gated.append(entry)
    gs = hjson(gated); res = dict(schema='CQR_GATE_RESULT_AMENDED_V1', amendment_version=AMEND_VERSION, label=a.label, mechanics_check_cells=limit, original_gate_result_sha256=am['original']['gate_result_sha256'], original_gate_passed=am['original']['gate_passed'], producer_identity=dict(commit=am['producer_identity']['commit'], full_inventory_sha256=am['producer_identity']['full_inventory_sha256']), verifier_identity=dict(git_head=am['verifier_identity']['git_head'], checker_version=am['verifier_identity']['checker_version'], full_inventory_sha256=am['verifier_identity']['full_inventory_sha256']),
               planned=len(cells), receipts_reverified=len(order), counters=counters, failures=failures, gate_passed_amended=(not failures and not limit), gated_set_sha256=gs, wall_s=round(time.monotonic() - t0, 3), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), note=('MECHANICS CHECK on %d cells: NOT the amended gate' % len(order)) if limit else 'uniform re-verification of every original receipt by the amended verifier; the original FAILED gate stands as its own record')
    tag = ('MECHANICS_CHECK_%dcells' % len(order)) if limit else 'AMENDED'; json.dump(res, open(os.path.join(AM, 'GATE_RESULT_%s.json' % tag), 'w'), indent=1, default=str); json.dump(gated, open(os.path.join(AM, 'GATED_SET_%s.json' % tag), 'w'), indent=1, default=str)
    print(json.dumps(dict(reverified=len(order), failures=failures[:5], counters=counters, gate_passed_amended=res['gate_passed_amended'], wall_s=res['wall_s'])))
    return 0 if not failures else 1
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd', required=True)
    p1 = sub.add_parser('prepare'); p1.add_argument('--original', required=True); p1.add_argument('--verifier-build', required=True); p1.add_argument('--out', required=True); p1.add_argument('--producer-commit', default='f672b69b74a65445576688fc7b8215cab50e8aa0'); p1.add_argument('--allowed-verifier-files', default='cqr/checker.py,cqr/registry.py')
    p2 = sub.add_parser('execute'); p2.add_argument('--amend', required=True); p2.add_argument('--cells', type=int, default=0); p2.add_argument('--label', default='')
    a = ap.parse_args(); sys.exit(prepare(a) if a.cmd == 'prepare' else execute(a))
