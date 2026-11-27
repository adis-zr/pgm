"""DGP2 / DGP3 one-shot packet consistency validator (protocol rule 9 / brief section 9): derives summary counts from the raw cells, enforces unique cell identities and parent / superseding links, reconciles charges to the ledger
and the ceiling, verifies input / code bindings (manifests vs result files vs FREEZE.json), checks the accepted engine's byte identity, and lists missing required packet files. BOOKKEEPING ONLY: it does not prove
statistical coverage. usage: validate_round.py [--records RD] -> RD/VALIDATION.json (exit 1 on any failure)"""
import sys, os, json, glob, hashlib, subprocess
RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/DGP2_REPAIR_AND_DIAGNOSIS'
def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()
def main():
    rd = sys.argv[sys.argv.index('--records') + 1] if '--records' in sys.argv else RD; checks = []; 
    def chk(name, ok, **kw): checks.append(dict(check=name, ok=bool(ok), **kw))
    ledgers = sorted(glob.glob(os.path.join(rd, '*_LEDGER.jsonl'))); chk('one_round_ledger', len(ledgers) == 1, ledgers=[os.path.basename(x) for x in ledgers]); ledger = ledgers[0] if ledgers else os.path.join(rd, 'DGP2_LEDGER.jsonl')
    req = ['START_HERE.md', 'PROTOCOL.md', 'FREEZE.json', 'REPORT.md', 'THEORY_RETURN.md', 'PROOF_TO_CODE.md', 'MODEL_MANIFEST.json', 'RUN_MANIFEST.json', 'RESULTS.json', 'DIAGNOSTICS.json', 'CHARGES.json', 'IDENTITY.json', os.path.basename(ledger), 'BUDGET_DECLARATION.json']
    for f in req: chk('required_file:' + f, os.path.exists(os.path.join(rd, f)))
    for d in ('runs', 'controls', 'oracle'): chk('required_dir:' + d, os.path.isdir(os.path.join(rd, d)))
    fr = json.load(open(os.path.join(rd, 'FREEZE.json'))); root = '/Users/adis/Workspace/pgm-eval-' + fr['code']['commit'][:7]; arm_files = fr.get('arm_identity_files') or list(fr['code']['files'])
    if os.path.isdir(root):
        ident = {f: sha(os.path.join(root, 'code', f)) for f in fr['code']['files']}; chk('frozen_identity_at_eval_checkout', ident == fr['code']['files'], mismatches=[f for f in ident if ident[f] != fr['code']['files'][f]])
        try:
            same = subprocess.run(['git', '-C', root, 'diff', '--quiet', '1da6da3', 'HEAD', '--', 'code/cex/blockres/integrated.py', 'code/cex/blockres/blockres.py', 'code/cex/blockres/layered_contraction.py', 'code/cex/blockres/signed_evidence.py', 'code/cex/blockres/ancestral_response.py', 'code/cex/blockres/support_closure.py', 'code/cex/newarm/cex_executor.py', 'code/cex/newarm/cex_kernel.cpp']).returncode == 0; chk('accepted_engine_byte_identical_to_1da6da3', same)
        except Exception as e: chk('accepted_engine_byte_identical_to_1da6da3', False, error=repr(e)[:100])
    else: chk('eval_checkout_present', False, root=root)
    # every cell's recorded code commit is the frozen commit and its launch / completion identities equal the frozen ARM identity files (the harness files may carry a HARNESS amendment)
    bad_commit = []; bad_arm_ident = []; amends = {}
    for a_ in sorted(glob.glob(os.path.join(rd, 'FREEZE_AMENDMENT*.json'))):
        aj = json.load(open(a_))
        if aj.get('kind', '').startswith('validity') and aj.get('code'): amends[aj['code']['commit']] = aj          # DGP5: a VALIDITY amendment carries its own commit + identity files; cells launched after it record the amendment
    n_amended = 0
    for p in sorted(glob.glob(os.path.join(rd, 'runs', '*', '*', 'cell.json'))):
        cj = json.load(open(p)); c = cj['cell']; ref = fr['code']
        if c.get('code_commit') != fr['code']['commit']:
            if c.get('code_commit') in amends and c.get('amendment'): ref = amends[c['code_commit']]['code']; n_amended += 1
            else: bad_commit.append(os.path.relpath(p, rd))
        for k in ('identity_at_launch', 'identity_at_completion'):
            if any(cj.get(k, {}).get(f) != ref['files'].get(f) for f in (ref.get('arm_identity_files') or arm_files)): bad_arm_ident.append((os.path.relpath(p, rd), k))
    chk('cells_at_frozen_commit', not bad_commit, bad=bad_commit[:10], cells_at_validity_amendment_commit=n_amended, amendments=sorted(amends)); chk('cells_arm_identity_equals_freeze', not bad_arm_ident, bad=bad_arm_ident[:10])
    # oracle results: produced by the frozen oracle harness or a recorded HARNESS amendment (arm files unchanged)
    am = sorted(glob.glob(os.path.join(rd, 'FREEZE_AMENDMENT*.json')))
    for a in am:
        aj = json.load(open(a))
        if aj.get('kind', '').startswith('validity'): chk('validity_amendment_complete:' + os.path.basename(a), bool(aj.get('code', {}).get('commit')) and bool(aj.get('affected_cells')) and bool(aj.get('requalification')) and bool(aj.get('superseded_dir')), kind=aj.get('kind', '')[:80], affected=len(aj.get('affected_cells') or []))
        else: chk('amendment_arm_files_unchanged:' + os.path.basename(a), aj.get('arm_identity_files_unchanged') is True, kind=aj.get('kind', '')[:80])
    # cells: unique identities, manifest / result binding, identity_ok, receipt present
    cells = sorted(glob.glob(os.path.join(rd, 'runs', '*', '*', 'cell.json'))); ids = set(); bad_bind = []; bad_ident = []; no_receipt = []; per_sub = {}
    rows = [json.loads(l) for l in open(ledger)]; receipts = {}
    for r in rows:
        if r.get('kind') == 'RECEIPT': receipts.setdefault(r['job'], []).append(r)
    for p in cells:
        c = json.load(open(p))['cell']; key = (c['task'], c['arm'], c['seed'], c['confirm'], os.path.basename(os.path.dirname(os.path.dirname(p))))
        if key in ids: chk('duplicate_cell:' + str(key), False)
        ids.add(key); sub = key[4]; per_sub.setdefault(sub, dict(cells=0, complete=0, arms={}))
        per_sub[sub]['cells'] += 1; per_sub[sub]['complete'] += int(bool(c.get('complete'))); per_sub[sub]['arms'][c['arm']] = per_sub[sub]['arms'].get(c['arm'], 0) + 1
        if c.get('model_sha256') and c.get('model_sha256_at_run') != c['model_sha256']: bad_bind.append(key)
        if not c.get('identity_ok'): bad_ident.append(key)
        if c['job'] not in receipts: no_receipt.append(key)
        res = os.path.join(os.path.dirname(p), 'result.json')
        if os.path.exists(res):
            d = json.load(open(res)); inp = d.get('input')
            if inp and os.path.abspath(inp) != os.path.abspath(c['model']): bad_bind.append(key + ('result input differs',))
    chk('cells_input_binding', not bad_bind, bad=bad_bind[:10]); chk('cells_identity_ok', not bad_ident, bad=bad_ident[:10]); chk('cells_have_receipts', not no_receipt, missing=no_receipt[:10]); chk('cells_counted', True, per_sub=per_sub, n_cells=len(cells))
    # DGP4 R2: the constructor live-ledger identity must hold in EVERY planner result (incl. refusals / partials / deadline cells); BASE cells (accepted engine) carry no planner ledger
    bad_ledger = []; n_planner = 0
    for p in cells:
        c = json.load(open(p))['cell']; res = os.path.join(os.path.dirname(p), 'result.json')
        if c['arm'] == 'BASE' or not os.path.exists(res): continue
        d = json.load(open(res)); m = d.get('mechanism') or {}; n_planner += 1
        if m.get('constructor_live_ledger_identity') is not True: bad_ledger.append((os.path.relpath(p, rd), d.get('outcome'), m.get('constructor_live_at_end_bytes')))
    chk('planner_results_ledger_identity_true_everywhere', not bad_ledger, planner_results=n_planner, bad=bad_ledger[:10])
    # charges reconcile
    tot = round(sum(r['wall_s'] for rs in receipts.values() for r in rs), 3); ch = json.load(open(os.path.join(rd, 'CHARGES.json'))) if os.path.exists(os.path.join(rd, 'CHARGES.json')) else {}
    # CHARGES.json is written by the analyzer; the analysis / packaging / validation receipts that necessarily follow it (scope *_analysis) are reconciled separately against the ledger's end_utc
    # DGP8 HARNESS AMENDMENT 1: reconcile by receipt COUNT when CHARGES.json records n_receipts (the analyzer summed exactly the first n_receipts RECEIPT rows in ledger order); the utc cut alone counted the analyzer's
    # own receipt when it ended in the same UTC second as the CHARGES.json write (a 0.4 s analysis run) -- a boundary artifact, not a charge discrepancy. The utc cut remains the fallback for records without n_receipts.
    cut = ch.get('utc'); rc_ordered = [r for r in rows if r.get('kind') == 'RECEIPT']
    if isinstance(ch.get('n_receipts'), int) and 0 <= ch['n_receipts'] <= len(rc_ordered): at_analysis = round(sum(r['wall_s'] for r in rc_ordered[:ch['n_receipts']]), 3)
    else: at_analysis = round(sum(r['wall_s'] for rs in receipts.values() for r in rs if (cut is None or (r.get('end_utc') or '') <= cut)), 3)
    after = round(tot - at_analysis, 3)
    chk('charges_reconcile_ledger', abs((ch.get('total_s') or -1) - at_analysis) < 0.01, ledger_total_at_analysis_s=at_analysis, charges_total_s=ch.get('total_s'), post_analysis_receipts_s=after, ledger_total_s=tot, note='post-analysis receipts are the analyzer / report / packaging / validation runs themselves (scope *_analysis), charged after CHARGES.json was written'); ceiling = (json.load(open(os.path.join(rd, 'BUDGET_DECLARATION.json'))).get('ceiling_s') if os.path.exists(os.path.join(rd, 'BUDGET_DECLARATION.json')) else None) or 7200; chk('charges_within_ceiling', tot <= ceiling, total_s=tot, ceiling_s=ceiling)
    # RUN_MANIFEST: every planned cell has an actual cell or an explicit reason
    rm = json.load(open(os.path.join(rd, 'RUN_MANIFEST.json'))) if os.path.exists(os.path.join(rd, 'RUN_MANIFEST.json')) else None
    if rm: missing = [c for c in rm.get('planned', []) if not c.get('actual') and not c.get('reason')]; chk('run_manifest_complete', not missing, missing=missing[:10], planned=len(rm.get('planned', [])))
    # RESULTS.json counts derive from cells (recomputed here)
    rs = json.load(open(os.path.join(rd, 'RESULTS.json'))) if os.path.exists(os.path.join(rd, 'RESULTS.json')) else None
    if rs:
        for sub, cnt in (rs.get('completions_by_sub') or {}).items():
            if sub in per_sub: chk('results_counts_match_cells:' + sub, cnt.get('cells') == per_sub[sub]['cells'] and cnt.get('complete') == per_sub[sub]['complete'], results=cnt, cells=per_sub[sub])
    # DGP3+: the EXECUTED harness / analyzer snapshot (git bundle of the branch + hashes of the executed files) and a replay command must be in the packet (DGP2 review, packaging finding)
    if fr.get('experiment', '').startswith(('DGP3', 'DGP4', 'DGP5', 'DGP6', 'DGP7', 'DGP8')):
        hs = os.path.join(rd, 'harness'); bundle = glob.glob(os.path.join(hs, '*.bundle')); ex = os.path.join(hs, 'EXECUTED_HARNESS_SHA256.json')
        chk('executed_harness_snapshot_present', bool(bundle) and os.path.exists(ex), bundle=[os.path.basename(b) for b in bundle])
        if os.path.exists(ex):
            exh = json.load(open(ex)); bad = [f for f, h in exh.get('files', {}).items() if not os.path.exists(os.path.join(hs, 'files', os.path.basename(f))) or sha(os.path.join(hs, 'files', os.path.basename(f))) != h]
            chk('executed_harness_files_match_hashes', not bad, bad=bad)
        rp = os.path.join(rd, 'reproduce.sh'); chk('reproduce_sh_has_replay_command', os.path.exists(rp) and any(('run_dgp%d.py' % k) in open(rp).read() for k in (3, 4, 5, 6, 7, 8)) and 'harness/files' in open(rp).read())
    # DGP6 (finding 9): relocation test -- every manifest input path rewritten onto a NON-EXISTENT workstation prefix must resolve back through the packet / DGP_ROOTS with its sha256 (never a silent substitute); run with the original paths ABSENT from the candidates
    if fr.get('experiment', '').startswith(('DGP6', 'DGP7', 'DGP8')):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import dgp_paths
            mm = json.load(open(os.path.join(rd, 'MODEL_MANIFEST.json'))); pnames = [p_ for p_ in mm['panels'] if isinstance(mm['panels'][p_], list) and mm['panels'][p_] and isinstance(mm['panels'][p_][0], dict) and 'model' in mm['panels'][p_][0]]; tasks = [t for p_ in pnames for t in mm['panels'][p_]]       # DGP7: every task-list panel of the manifest (main / oracle / preservation / guard / gate / policy8), deduplicated by model path below
            roots_env = os.environ.get('DGP_ROOTS'); os.environ['DGP_ROOTS'] = os.environ.get('DGP6_RELOCATION_ROOTS', dgp_paths._repo_root_of(rd) or os.path.dirname(rd))          # default: the records repository holding this packet (inputs under code/runs/... AND docs/...); a restored packet sets DGP6_RELOCATION_ROOTS / DGP_ROOTS to the relocated copy
            seen = set(); tasks = [t for t in tasks if not (t.get('model') in seen or seen.add(t.get('model')))]
            try: rel = dgp_paths.relocation_test(tasks, rd)
            finally:
                if roots_env is None: os.environ.pop('DGP_ROOTS', None)
                else: os.environ['DGP_ROOTS'] = roots_env
            bad = [r for r in rel if not r['ok']]; chk('relocation_resolves_every_manifest_input', not bad, n=len(rel), bad=bad[:5], roots='DGP6_RELOCATION_ROOTS (also honoured for DGP7) or the records repository root; every fake prefix /nonexistent/workstation/... never exists')
        except Exception as e: chk('relocation_resolves_every_manifest_input', False, error=repr(e)[:200])
    # unsupported claims: forbidden phrases in REPORT / THEORY_RETURN
    for f in ('REPORT.md', 'THEORY_RETURN.md', 'START_HERE.md'):
        p = os.path.join(rd, f)
        if os.path.exists(p):
            t = open(p).read().lower(); bad = [w for w in ('proven empirically', 'instance optimal', 'certified by ess', 'ess proves', 'guarantees convergence') if w in t]; chk('no_unsupported_phrases:' + f, not bad, found=bad)
    ok = all(c['ok'] for c in checks); json.dump(dict(all_ok=ok, n_checks=len(checks), n_failed=sum(1 for c in checks if not c['ok']), checks=checks, note='bookkeeping consistency only; statistical coverage comes from the theorem and its implementation conditions, not from this validator'), open(os.path.join(rd, 'VALIDATION.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(all_ok=ok, failed=[c['check'] for c in checks if not c['ok']]))); sys.exit(0 if ok else 1)
if __name__ == '__main__': main()
