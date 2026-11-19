"""amend_verification.py -- the SUCCESSOR VERIFICATION CHAIN (gate -> report -> closeout) for a completed shard, with the ORIGINAL PRODUCER identity, the ORIGINAL observation
history (receipts / outputs / dependency closure / ledger / original gate) and a SEPARATELY identified VERIFIER build. Every subcommand must run under gbidi.supervise (GBIDI_PARENT_JID
present; refused otherwise) so that it is a charged receipt in AMEND_DIR/CQR_LEDGER.jsonl. Nothing in the original run directory RD is ever written.

  prepare  --original RD --verifier-build V --out AMEND_DIR [--allowed-verifier-files cqr/checker.py,cqr/registry.py,cqr/gate.py,cqr/report.py] [--producer-commit SHA] [--fresh]
           [--closure-exception cqr/registry.py --closure-justification TEXT]   (a verifier-only file INSIDE the producer's static import closure must be declared and justified)
      (1) the frozen gate's GLOBAL PREFLIGHT (gate.global_preflight of the verifier build, with the verifier build's inventory / kernels on disk): unique planned ids, unique receipts,
          exact planned / observed set equality, CAMPAIGN_START + ledger CAMPAIGN_START bound to the manifest and the frozen inventory, no amendment files, complete inventory,
          registry identity, kernel identity for every tag a planned arm loads;  (2) every source that differs between the frozen PRODUCER inventory and the verifier build must be
          in the declared verifier-only set (a producer-side difference is an execution-affecting change -> REFUSED);  (3) the HISTORICAL AUTHORITY: every receipt is bound to its
          supervisor RECEIPT row in the shard ledger (job / outcome / rc / wall) and -- unless --fresh (a shard that has no gate yet) -- to the ORIGINAL GATE_RESULT.json gated set
          (receipt sha256, output sha256, status / outcome / guarantee, the complete dependency closure incl. absences); the original gate itself is authenticated (manifest / inventory
          hashes, planned / receipt counts, gated set digest, gated set == planned set); worker outputs equal their receipt hash; tasks equal the frozen hashes;  (4) the TOOL identity
          (every .py of cex/cqr_amend + gbidi/supervise.py of the verifier build) and the VERIFIER identity (full inventory, checker / gate / report / closeout versions, kernels) are
          pinned.  Writes ORIGINAL_INVENTORY.json + VERIFICATION_AMENDMENT_MANIFEST.json (status PREPARED_NOT_EXECUTED or REFUSED: ...). Refuses an existing AMEND_DIR manifest.
  execute  --amend AMEND_DIR --attempt NAME [--cells ID,ID,...] [--budget-s S] [--label TEXT]
      refuses unless: tool identity, verifier identity, original manifest / START / ledger / gate hashes, ORIGINAL_INVENTORY all equal the prepared ones; the global preflight passes
      again; every receipt / output / evidence file equals the historical authority NOW. Then every planned receipt (or the --cells subset = a MECHANICS CHECK, never a gate) is
      re-verified exactly as the frozen gate does (gate._check_cqr_cell with the PRODUCER cqr scope; baseline arms through the frozen pac gate; loaded-kernel provenance against the
      ORIGINAL kernel identity) under the aggregate budget (--budget-s, default the manifest's verification allowance): exhaustion -> every unchecked cell UNVERIFIABLE and the typed
      status INCOMPLETE_BUDGET_EXHAUSTED. Progress is durable (attempts/NAME/PROGRESS.jsonl after every cell; the result is written in `finally`). attempts/NAME/GATE_RESULT.json is
      schema-compatible with the frozen gate result (gated_set with evidence closure + verified attribution) and carries `successor` (identities, authority, attempt, status).
      An existing attempts/NAME is REFUSED (immutable; a failed attempt and the original FAILED gate are preserved).
  report   --amend AMEND_DIR --attempt NAME     the verifier build's report.py with --gate attempts/NAME/GATE_RESULT.json --out-dir attempts/NAME (RD read-only).
  closeout --amend AMEND_DIR --attempt NAME --qualification PATH
      fail-closed: identities as above; attempt result COMPLETE, gate_passed, no failures, counts, gated set digest, every gated hash == the historical authority == disk now; the
      ledger's LATEST cqr_successor_gate / cqr_successor_report receipts for this attempt COMPLETED rc 0; the report binds this attempt's gate file (sha256) and gated set, has no
      mismatch, and RE-DERIVES equal (summary + semantic run rows, published JSON domain); qualification record: cqr-qualification suite, groups == the registry schema, all pass,
      candidate_sources == the VERIFIER cqr scope, suite_sha256 == the verifier's suite file; no CONFIRMED_INACCURATE. Writes attempts/NAME/CLOSEOUT_SUCCESSOR.md; exit 0 only on
      SUCCESSOR VERIFICATION QUALIFIED."""
import os, sys, json, time, hashlib, glob, argparse, difflib, subprocess, collections, shutil, tempfile, traceback
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from __init__ import AMEND_VERSION
WALL_TOL_S = 0.011            # receipt.supervisor.wall_s is the ledger wall rounded to 2 decimals
LAUNCH_OVERHEAD_BOUND_S = 2.0 # launch_relative_wall_s - supervisor wall: spawn / cleanup overhead observed <= 0.28 s on A1; a declared bound, recorded in the manifest
SCOPES = dict(prepare='cqr_successor_prepare', execute='cqr_successor_gate', report='cqr_successor_report', closeout='cqr_successor_closeout')
SEMANTIC_RUN_FIELDS = ('cell_id', 'case', 'arm', 'cohort', 'budget', 'rep', 'status', 'outcome', 'guarantee', 'route', 'output_sha256', 'exact', 'bias', 'bias_applied_to_original_answers', 'bias_interpretation',
                       'committed_operators', 'guarantee_source', 'claimed_route', 'attribution_mismatch', 'mode', 'outcome_class', 'kind', 'work_reference', 'work_optional', 'reference_progress', 'ratio_draws', 'epochs', 'frontier', 'routes')


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def hjson(d): return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()
def pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
def tool_identity(V):
    """the load-bearing identity of THIS tool: every .py of cex/cqr_amend as invoked + the supervisor module of the verifier build"""
    files = {('cqr_amend/' + f): sha(os.path.join(HERE, f)) for f in sorted(os.listdir(HERE)) if f.endswith('.py')}
    sp = os.path.join(V, 'gbidi', 'supervise.py'); files['gbidi/supervise.py'] = sha(sp) if os.path.exists(sp) else None
    return dict(files=files, sha256=hjson(files), invoked_from=HERE)
def require_supervised(step):
    if not os.environ.get('GBIDI_PARENT_JID'): raise SystemExit('refuse: %s must run as a charged supervised job (python -m gbidi.supervise --ledger AMEND_DIR/CQR_LEDGER.jsonl --scope %s --job ... -- ...); GBIDI_PARENT_JID absent' % (step, SCOPES[step]))
    return os.environ['GBIDI_PARENT_JID']
def load_build(build):
    """import the VERIFIER build's gate exactly as the campaign does (gate.py arranges the pac / cqr module paths itself)"""
    sys.path.insert(0, os.path.join(build, 'cex', 'cqr')); import gate as G
    if not hasattr(G, 'global_preflight'): raise SystemExit('refuse: the verifier build\'s gate has no global_preflight (needs cqr-gate-v1.2+)')
    return G
def producer_import_closure(V):
    """the STATIC import closure of the producer entry points (cex/cqr/worker.py and cex/pac/worker.py) over the cqr / newarm / pac scopes: module names imported anywhere in a reached
    module (import X / from X import / import X as Y, incl. nested imports) that resolve to a file of those scopes. A verifier-only file INSIDE this closure is producer-side unless declared
    as an explicit, recorded exception (--closure-exception); the declared exception is reviewable in the manifest with its diff."""
    import ast
    dirs = {'cqr': os.path.join(V, 'cex', 'cqr'), 'newarm': os.path.join(V, 'cex', 'newarm'), 'pac': os.path.join(V, 'cex', 'pac')}
    mods = {}
    for tag, d in dirs.items():
        if not os.path.isdir(d): continue
        for f in os.listdir(d):
            if f.endswith('.py'): mods.setdefault(f[:-3], []).append('%s/%s' % (tag, f))
    def imports_of(key):
        tag, f = key.split('/', 1); p = os.path.join(dirs[tag], f); out = set()
        try: tree = ast.parse(open(p).read())
        except Exception: return out
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names: out.add(al.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module: out.add(node.module.split('.')[0])
        return out
    seen = set(); stack = ['cqr/worker.py', 'pac/worker.py']
    while stack:
        k = stack.pop()
        if k in seen or k.split('/', 1)[0] not in dirs or not os.path.exists(os.path.join(dirs[k.split('/', 1)[0]], k.split('/', 1)[1])): continue
        seen.add(k); own = k.split('/', 1)[0]
        for m in imports_of(k):
            for cand in mods.get(m, []):
                # a bare `import registry` inside cqr/ resolves to cqr/registry.py when it exists there (sys.path order of the worker), else to pac/registry.py; both are added when ambiguous
                stack.append(cand)
    return sorted(seen)


def ledger_rows(RD):
    out = []
    lp = os.path.join(RD, 'CQR_LEDGER.jsonl')
    if os.path.exists(lp):
        for i, line in enumerate(open(lp)):
            if not line.strip(): continue
            try: row = json.loads(line); row['_i'] = i; out.append(row)
            except Exception: pass
    return out


def authority(G, RD, man, cells, receipts, g0, fail):
    """the HISTORICAL AUTHORITY per cell (never 'whatever is present'): (1) the ledger RECEIPT row of the cell's supervised job (outcome / rc / wall); (2) when an original gate exists,
    its gated-set entry (receipt / output sha256, labels, dependency closure). Returns inv (per cell), with failures appended through `fail`."""
    rows = ledger_rows(RD); by_job = collections.defaultdict(list)
    for x in rows:
        if x.get('kind') == 'RECEIPT' and str(x.get('job', '')).startswith('cell:'): by_job[x['job']].append(x)
    gs = {}
    if g0 is not None:
        ents = g0.get('gated_set') if isinstance(g0.get('gated_set'), list) else None
        if ents is None: fail('*', 'original gate result carries no gated set')
        else:
            ids = [e.get('cell_id') for e in ents]
            if len(ids) != len(set(ids)): fail('*', 'original gated set has duplicate cell ids')
            if set(ids) != set(cells): fail('*', 'original gated set (%d) is not the planned set (%d)' % (len(ids), len(cells)))
            if g0.get('gated_set_sha256') != hashlib.sha256(json.dumps(ents, sort_keys=True).encode()).hexdigest(): fail('*', 'original gated set digest does not match its gated set')
            gs = {e['cell_id']: e for e in ents}
    inv = {}
    for cid in sorted(receipts):
        r = receipts[cid]; c = cells.get(cid); rp = r['_path']; rsha = r['_sha']
        wo = r.get('worker_output'); wp = os.path.join(RD, wo) if wo else None; osha = (sha(wp) if (wp and os.path.exists(wp)) else None)
        if wo and osha is None: fail(cid, 'receipt names a worker output that is missing on disk')
        if osha != r.get('output_sha256'): fail(cid, 'worker output sha256 differs from the receipt')
        sup = r.get('supervisor') or {}; L = by_job.get(sup.get('job'))
        if not L: fail(cid, 'no ledger RECEIPT row for the cell\'s supervised job %s (the observation is not in the append-only ledger)' % sup.get('job'))
        else:
            if len(L) > 1: fail(cid, 'ledger holds %d RECEIPT rows for job %s' % (len(L), sup.get('job')))
            x = L[-1]
            if x.get('outcome') != sup.get('outcome') or x.get('returncode') != sup.get('rc'): fail(cid, 'receipt supervisor outcome / rc (%s / %s) differ from the ledger row (%s / %s)' % (sup.get('outcome'), sup.get('rc'), x.get('outcome'), x.get('returncode')))
            lw = x.get('wall_s'); sw = sup.get('wall_s'); rw = r.get('launch_relative_wall_s')
            if not (isinstance(lw, (int, float)) and isinstance(sw, (int, float)) and abs(lw - sw) <= WALL_TOL_S): fail(cid, 'receipt supervisor wall %s differs from the ledger wall %s' % (sw, lw))
            if not (isinstance(rw, (int, float)) and isinstance(lw, (int, float)) and (lw - WALL_TOL_S) <= rw <= (lw + LAUNCH_OVERHEAD_BOUND_S)): fail(cid, 'receipt launch-relative wall %s is not within [ledger wall %s - %.3f, + %.1f] (altered measurement history)' % (rw, lw, WALL_TOL_S, LAUNCH_OVERHEAD_BOUND_S))
        ev = {}
        if c is not None:
            for dep in G.task_dependencies(c): ev[dep] = sha(dep) if os.path.exists(dep) else None
            if wp: ev[os.path.relpath(wp, RD)] = osha
        e = gs.get(cid)
        if e is not None:
            if e.get('receipt_sha256') != rsha: fail(cid, 'receipt bytes differ from the ORIGINAL gate\'s gated set (changed after the original gate)')
            if e.get('output_sha256') != osha: fail(cid, 'worker output differs from the ORIGINAL gate\'s gated set')
            if (e.get('status'), e.get('outcome'), e.get('guarantee')) != (r.get('status'), r.get('outcome'), r.get('guarantee_type')): fail(cid, 'receipt status / outcome / guarantee differ from the ORIGINAL gate\'s gated set')
            oe = e.get('evidence') or {}
            for k, v in oe.items():
                fp = k if os.path.isabs(k) else os.path.join(RD, k)
                if (sha(fp) if os.path.exists(fp) else None) != v: fail(cid, 'dependency %s differs from the hash the ORIGINAL gate recorded (changed / replaced / missing)' % os.path.basename(k))
            if c is not None and (r.get('status') == 'COMPLETED' or r.get('outcome') == 'PROVED_ZERO_EVIDENCE'):
                for m_ in G.dependency_closure_failures(RD, c, oe): fail(cid, 'original gate: ' + m_)
            ev = {(k if os.path.isabs(k) else k): v for k, v in oe.items()} or ev
        inv[cid] = dict(path=os.path.relpath(rp, RD), sha256=rsha, output_path=wo, output_sha256=osha, status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=(c or {}).get('arm'), launch_relative_wall_s=r.get('launch_relative_wall_s'),
                        supervisor=dict(job=sup.get('job'), outcome=sup.get('outcome'), rc=sup.get('rc'), wall_s=sup.get('wall_s')), ledger_row=(L[-1]['_i'] if L else None), evidence=ev, in_original_gated_set=(e is not None))
    return inv


def preflight(G, RD, MN, man, V, fail):
    """the frozen gate's global preflight with the VERIFIER build on disk; returns (pf, differ) -- differing frozen sources are judged by the caller against the verifier-only set"""
    R = G.R; KI = G.KI; mh = sha(os.path.join(RD, MN))
    if man.get('schema') != 'cqr_campaign_manifest_v1': fail('*', 'manifest schema %s is not cqr_campaign_manifest_v1' % man.get('schema'))
    pf = G.global_preflight(RD, MN, man, mh, fail, R.full_inventory(V), KI.collect(V))
    return pf


def current_originals(RD, MN):
    d = dict(manifest_sha256=sha(os.path.join(RD, MN)), campaign_start_sha256=(sha(os.path.join(RD, 'CAMPAIGN_START.json')) if os.path.exists(os.path.join(RD, 'CAMPAIGN_START.json')) else None), gate_result_sha256=(sha(os.path.join(RD, 'GATE_RESULT.json')) if os.path.exists(os.path.join(RD, 'GATE_RESULT.json')) else None))
    rows = ledger_rows(RD); d['ledger_campaign_start_sha256'] = hjson(next((x for x in rows if x.get('kind') == 'CAMPAIGN_START'), None)); d['ledger_cell_receipt_rows_sha256'] = hjson([{k: v for k, v in x.items() if k != '_i'} for x in rows if x.get('kind') == 'RECEIPT' and str(x.get('job', '')).startswith('cell:')])
    return d


def prepare(a):
    jid = require_supervised('prepare'); RD = os.path.abspath(a.original); V = os.path.abspath(a.verifier_build); OUT = os.path.abspath(a.out); MN = a.manifest
    if os.path.exists(os.path.join(OUT, 'VERIFICATION_AMENDMENT_MANIFEST.json')): raise SystemExit('refuse: amendment manifest exists (immutable; use a new directory)')
    os.makedirs(OUT, exist_ok=True); G = load_build(V); R = G.R; CK = G.CK; KI = G.KI; t0 = time.monotonic(); failures = []
    def fail(cid, m): failures.append((cid, m))
    man = json.load(open(os.path.join(RD, MN))); g0p = os.path.join(RD, 'GATE_RESULT.json'); g0 = json.load(open(g0p)) if os.path.exists(g0p) else None
    if g0 is None and not a.fresh: fail('*', 'no original GATE_RESULT.json: a shard without a gate needs --fresh (its authority is then the ledger + the frozen manifest)')
    if g0 is not None and a.fresh: fail('*', '--fresh given but an original GATE_RESULT.json exists: the original gate IS the authority (drop --fresh)')
    pf = preflight(G, RD, MN, man, V, fail)
    producer_inv = man.get('candidate_artifact_hashes') or {}; verifier_inv = R.full_inventory(V); allowed = sorted(x for x in a.allowed_verifier_files.split(',') if x)
    differ = pf['differ']; bad = [k for k in differ if k not in allowed]
    if bad: fail('*', 'producer-side sources differ between the frozen inventory and the verifier build (%s): an execution-affecting change needs a NEW candidate identity, not a successor verification' % bad[:3])
    closure = producer_import_closure(V); exceptions = sorted(x for x in (a.closure_exception or '').split(',') if x); inside = [k for k in differ if k in closure]
    bad_cl = [k for k in inside if k not in exceptions]
    if bad_cl: fail('*', 'verifier-only files %s lie INSIDE the producer\'s static import closure (worker.py reaches them): producer-side unless declared with --closure-exception and justified' % bad_cl[:3])
    if a.closure_exception and not a.closure_justification: fail('*', '--closure-exception requires --closure-justification (recorded in the manifest for review)')
    diffs = {}
    for k in differ:
        try: full = subprocess.run(['git', '-C', V, 'show', '%s:code/cex/%s' % (a.producer_commit, k)], capture_output=True, text=True, timeout=20); old_txt = full.stdout if full.returncode == 0 else None
        except Exception: old_txt = None
        new_txt = open(os.path.join(V, 'cex', k)).read() if os.path.exists(os.path.join(V, 'cex', k)) else ''
        diffs[k] = dict(producer_sha256=producer_inv.get(k), verifier_sha256=verifier_inv.get(k), unified_diff=(''.join(difflib.unified_diff(old_txt.splitlines(True), new_txt.splitlines(True), 'producer/' + k, 'verifier/' + k)) if old_txt is not None else 'producer source not recoverable from git (%s)' % a.producer_commit))
    cells = pf['cells']; receipts = pf['receipts']
    # the original gate is authenticated against the manifest / inventory / counts (its verdict is retained, never edited)
    if g0 is not None:
        mh = sha(os.path.join(RD, MN))
        if not str(g0.get('gate_version', '')).startswith('cqr-gate-v1'): fail('*', 'original gate result produced by an unknown gate (%s)' % str(g0.get('gate_version'))[:40])
        if g0.get('manifest_sha256') != mh: fail('*', 'original gate result belongs to a different manifest')
        if g0.get('artifact_hashes_sha256') != pf['ah']: fail('*', 'original gate result binds a different frozen source inventory')
        if g0.get('planned') != len(cells) or g0.get('receipts') != len(receipts): fail('*', 'original gate counts (planned %s, receipts %s) differ from the manifest (%d) / disk (%d)' % (g0.get('planned'), g0.get('receipts'), len(cells), len(receipts)))
        gate_rows = [x for x in ledger_rows(RD) if x.get('scope') == 'cqr_finalize_gate' and x.get('kind') == 'RECEIPT']
        if not gate_rows: fail('*', 'the ledger has no cqr_finalize_gate receipt: the original gate was not run under the chain')
    inv_cells = authority(G, RD, man, cells, receipts, g0, fail)
    tasks = {}
    for c in man['cells']:
        mp = c.get('model_path')
        if not mp or mp in tasks: continue
        deps = G.task_dependencies(c); tasks[mp] = dict(dependency_sha256={d: (sha(d) if os.path.exists(d) else None) for d in deps}, frozen=dict(model=c.get('model_sha256'), evidence=c.get('evidence_sha256'), query=c.get('query_sha256')))
        nf = len(failures); G.bind_task_dependencies(c, fail); tasks[mp]['equals_frozen'] = (len(failures) == nf)
    inv = dict(schema='CQR_SUCCESSOR_ORIGINAL_INVENTORY_V2', authority=('ledger RECEIPT rows + the ORIGINAL gate\'s gated set (receipt / output / dependency hashes)' if g0 is not None else 'ledger RECEIPT rows + the frozen manifest hashes (fresh shard: no gate yet)'), wall_tolerance_s=WALL_TOL_S, launch_overhead_bound_s=LAUNCH_OVERHEAD_BOUND_S, receipts=inv_cells, tasks=tasks)
    json.dump(inv, open(os.path.join(OUT, 'ORIGINAL_INVENTORY.json'), 'w'), indent=1, default=str); inv_sha = sha(os.path.join(OUT, 'ORIGINAL_INVENTORY.json'))
    kv = KI.collect(V); orig = current_originals(RD, MN)
    status = 'PREPARED_NOT_EXECUTED' if not failures else ('REFUSED: %d preflight / authority failures (first: %s)' % (len(failures), str(failures[0])[:200]))
    producer_cqr = {k: v for k, v in producer_inv.items() if R.is_cqr_scope_key(k)}; cqr_v = R.cqr_source_inventory(V)
    am = dict(schema='CQR_VERIFICATION_AMENDMENT_MANIFEST_V2', version=AMEND_VERSION, status=status, prepared_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), prepare_jid=jid, mode=('fresh' if g0 is None else 'amend'),
              original=dict(run_dir=RD, manifest=MN, **orig, gate_passed=(g0 or {}).get('gate_passed'), gate_failures=len((g0 or {}).get('failures') or []), gate_failures_all_unverifiable=(bool(g0) and all('UNVERIFIABLE' in str(f_[1]) for f_ in (g0.get('failures') or []))), gate_version=(g0 or {}).get('gate_version'), gate_counters=(g0 or {}).get('counters'), planned=len(cells), receipts=len(receipts), note='the ORIGINAL gate verdict is RETAINED (never edited); this chain writes separate immutable attempts'),
              preflight_failures=failures,
              producer_identity=dict(commit=a.producer_commit, full_inventory_sha256=hjson(producer_inv), artifacts=len(producer_inv), cqr_scope=producer_cqr, cqr_scope_sha256=hjson(producer_cqr), kernel_identity_sha256=hjson(man.get('kernel_identity') or {}), artifact_hashes_sha256=pf['ah']),
              verifier_identity=dict(build=V, git_head=(subprocess.run(['git', '-C', V, 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=20).stdout.strip() or None), full_inventory_sha256=hjson(verifier_inv), artifacts=len(verifier_inv), cqr_scope_sha256=hjson(cqr_v), kernel_identity_sha256=hjson(kv), checker_version=CK.CHECKER_VERSION, gate_version=G.GATE_VERSION, baseline_gate_version=G.PG.GATE_VERSION, python=pybin(V)),
              tool_identity=tool_identity(V), differing_sources=differ, allowed_verifier_only_files=allowed, producer_side_differences=bad, source_diffs=diffs,
              producer_import_closure=dict(modules=closure, verifier_only_files_inside_closure=inside, declared_exceptions=exceptions, justification=a.closure_justification, rule='a differing file inside the static import closure of cqr/worker.py / pac/worker.py is producer-side unless declared here with its justification; its unified diff is in source_diffs'),
              original_inventory=dict(file='ORIGINAL_INVENTORY.json', sha256=inv_sha, receipts=len(inv_cells), outputs=sum(1 for v in inv_cells.values() if v['output_sha256']), tasks=len(tasks), in_original_gated_set=sum(1 for v in inv_cells.values() if v['in_original_gated_set'])),
              policy=dict(uniform='EVERY planned receipt is re-verified by the verifier build\'s checker (gate._check_cqr_cell with the PRODUCER cqr scope) under replay_factor x budget; baseline arms through the frozen pac gate cell check; loaded-kernel provenance against the ORIGINAL kernel identity; the aggregate budget is enforced (exhaustion = typed INCOMPLETE, every unchecked cell UNVERIFIABLE)',
                          preserved='original worker files, walls, censoring, seeds, tolerances, arm definitions, scoring and the ORIGINAL gate are untouched; current / prepared / executed hashes must all equal the historical authority',
                          identity='tool identity (cqr_amend/*.py + gbidi/supervise.py) and verifier identity (full inventory + kernels) enforced at every step; a changed tool refuses against an old prepared identity even for a comment',
                          charging='every step is a supervised job in AMEND_DIR/CQR_LEDGER.jsonl (scopes %s); never added to the original cells' % json.dumps(SCOPES), immutability='attempts/NAME is never overwritten; failed attempts are preserved'),
              commands=dict(execute='cd %s && %s -m gbidi.supervise --ledger %s/CQR_LEDGER.jsonl --scope cqr_successor_gate --job successor_gate:attempt_1 --timeout %d --mem-gib 8 -- %s cex/cqr_amend/amend_verification.py execute --amend %s --attempt attempt_1 --budget-s %d --label "successor verification"' % (V, pybin(V), OUT, int((man.get('ceiling') or {}).get('verification_stage_seconds') or 3600) + 60, pybin(V), OUT, int((man.get('ceiling') or {}).get('verification_stage_seconds') or 3600)),
                            report='cd %s && %s -m gbidi.supervise --ledger %s/CQR_LEDGER.jsonl --scope cqr_successor_report --job successor_report:attempt_1 --timeout 1200 --mem-gib 8 -- %s cex/cqr_amend/amend_verification.py report --amend %s --attempt attempt_1' % (V, pybin(V), OUT, pybin(V), OUT),
                            closeout='cd %s && %s -m gbidi.supervise --ledger %s/CQR_LEDGER.jsonl --scope cqr_successor_closeout --job successor_closeout:attempt_1 --timeout 1200 --mem-gib 8 -- %s cex/cqr_amend/amend_verification.py closeout --amend %s --attempt attempt_1 --qualification <QUALIFICATION RECORD of the verifier identity>' % (V, pybin(V), OUT, pybin(V), OUT)),
              prepare_wall_s=round(time.monotonic() - t0, 3))
    json.dump(am, open(os.path.join(OUT, 'VERIFICATION_AMENDMENT_MANIFEST.json'), 'w'), indent=1, default=str)
    print(json.dumps(dict(status=status[:120], mode=am['mode'], differing_sources=differ, producer_side_differences=bad, receipts=len(inv_cells), failures=len(failures), first_failures=failures[:4], wall_s=am['prepare_wall_s']), default=str))
    return 0 if status == 'PREPARED_NOT_EXECUTED' else 1


def _load_prepared(a, step):
    jid = require_supervised(step); AM = os.path.abspath(a.amend); am = json.load(open(os.path.join(AM, 'VERIFICATION_AMENDMENT_MANIFEST.json'))); am_sha = sha(os.path.join(AM, 'VERIFICATION_AMENDMENT_MANIFEST.json'))
    if am.get('schema') != 'CQR_VERIFICATION_AMENDMENT_MANIFEST_V2' or not str(am.get('status', '')).startswith('PREPARED'): raise SystemExit('refuse: amendment status %s (schema %s)' % (str(am.get('status'))[:80], am.get('schema')))
    RD = am['original']['run_dir']; MN = am['original']['manifest']; V = am['verifier_identity']['build']; G = load_build(V)
    ti = tool_identity(V)
    if ti['sha256'] != am['tool_identity']['sha256']: raise SystemExit('refuse: the invoked tool identity %s differs from the prepared identity %s (changed files: %s)' % (ti['sha256'][:12], am['tool_identity']['sha256'][:12], sorted(k for k in set(ti['files']) | set(am['tool_identity']['files']) if ti['files'].get(k) != am['tool_identity']['files'].get(k))[:4]))
    if hjson(G.R.full_inventory(V)) != am['verifier_identity']['full_inventory_sha256']: raise SystemExit('refuse: the verifier build on disk differs from the prepared verifier identity')
    if hjson(G.KI.collect(V)) != am['verifier_identity']['kernel_identity_sha256']: raise SystemExit('refuse: the verifier build\'s kernel identity differs from the prepared one')
    if sha(os.path.join(AM, 'ORIGINAL_INVENTORY.json')) != am['original_inventory']['sha256']: raise SystemExit('refuse: ORIGINAL_INVENTORY.json altered')
    cur = current_originals(RD, MN); diff = [k for k in cur if cur[k] != am['original'].get(k)]
    if diff: raise SystemExit('refuse: the original %s changed since preparation' % diff)
    return jid, AM, am, am_sha, RD, MN, V, G


def execute(a):
    jid, AM, am, am_sha, RD, MN, V, G = _load_prepared(a, 'execute'); R = G.R; CK = G.CK; KI = G.KI; PG = G.PG
    AD = os.path.join(AM, 'attempts', a.attempt)
    if os.path.exists(AD): raise SystemExit('refuse: attempt directory %s exists (attempts are immutable; choose a new name)' % AD)
    os.makedirs(AD); t0 = time.monotonic(); failures = []; exhausted_at = None; gated = []; counters = dict(checked=0, gated=0, pac_verified=0, cqr_checked=0, cqr_verified=0, zero_checked=0, zero_verified=0, unverifiable=0, baseline_checked=0, cqr_provenance_checked=0); status = 'RUNNING'
    def fail(cid, m): failures.append((cid, m))
    man = json.load(open(os.path.join(RD, MN))); mh = sha(os.path.join(RD, MN)); inv = json.load(open(os.path.join(AM, 'ORIGINAL_INVENTORY.json')))
    budget = float(a.budget_s) if a.budget_s is not None else float((man.get('ceiling') or {}).get('verification_stage_seconds') or 3600.0)
    subset = sorted(x for x in (a.cells or '').split(',') if x) or None
    prog = open(os.path.join(AD, 'PROGRESS.jsonl'), 'a')
    def write_result(final_status):
        gs = hashlib.sha256(json.dumps(gated, sort_keys=True).encode()).hexdigest()
        res = dict(gate_version=G.GATE_VERSION, manifest=MN, manifest_sha256=mh, artifact_hashes_sha256=am['producer_identity']['artifact_hashes_sha256'], planned=len(man['cells']), receipts=len(inv['receipts']), completed_checked=counters['checked'], completed_gated=counters['gated'], counters=counters, failures=failures,
                   gate_passed=(final_status == 'COMPLETE' and not failures and subset is None), gated_set=gated, gated_set_sha256=gs, gate_wall_s=round(time.monotonic() - t0, 3), replay_factor=G.REPLAY_FACTOR, gate_budget_s=budget, budget_exhausted_at_cell=exhausted_at, checker_version=CK.CHECKER_VERSION, baseline_gate_version=PG.GATE_VERSION,
                   verification_policy=am['policy']['uniform'],
                   successor=dict(schema='CQR_SUCCESSOR_GATE_RESULT_V2', version=AMEND_VERSION, attempt=a.attempt, label=a.label, status=final_status, jid=jid, amendment_manifest_sha256=am_sha, mechanics_check_cells=subset, original=am['original'], original_inventory_sha256=am['original_inventory']['sha256'],
                                  producer_identity={k: v for k, v in am['producer_identity'].items() if k != 'cqr_scope'}, verifier_identity=am['verifier_identity'], tool_identity_sha256=am['tool_identity']['sha256'], utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                                  note=('MECHANICS CHECK on %d cells: NOT a gate (gate_passed is always false)' % len(subset)) if subset else ('every planned receipt re-verified' if final_status == 'COMPLETE' else 'INCOMPLETE: typed; every unchecked cell is UNVERIFIABLE')))
        tmp = os.path.join(AD, 'GATE_RESULT.json.tmp'); json.dump(res, open(tmp, 'w'), indent=1, default=str); os.replace(tmp, os.path.join(AD, 'GATE_RESULT.json')); return res
    try:
        pf = preflight(G, RD, MN, man, V, fail)
        if [k for k in pf['differ'] if k not in am['allowed_verifier_only_files']]: fail('*', 'producer-side sources differ from the frozen inventory')
        cells = pf['cells']; receipts = pf['receipts']
        # the historical authority NOW: every receipt / output / dependency equals ORIGINAL_INVENTORY (which equals the ledger + the original gate)
        if set(receipts) != set(inv['receipts']): fail('*', 'the receipts on disk are not the prepared set (%d vs %d)' % (len(receipts), len(inv['receipts'])))
        for cid, h in inv['receipts'].items():
            r = receipts.get(cid)
            if r is None: continue
            if r['_sha'] != h['sha256']: fail(cid, 'receipt bytes differ from the historical authority')
            wp = os.path.join(RD, h['output_path']) if h.get('output_path') else None
            if (sha(wp) if (wp and os.path.exists(wp)) else None) != h['output_sha256']: fail(cid, 'worker output differs from the historical authority')
            for k, v in (h.get('evidence') or {}).items():
                fp = k if os.path.isabs(k) else os.path.join(RD, k)
                if (sha(fp) if os.path.exists(fp) else None) != v: fail(cid, 'dependency %s differs from the historical authority' % os.path.basename(k))
        if failures: status = 'REFUSED_PRECONDITIONS'; write_result(status); print(json.dumps(dict(status=status, failures=failures[:6]), default=str)); return 1
        producer_cqr = am['producer_identity']['cqr_scope']; frozen_cand = {k: v for k, v in pf['ch'].items() if R.PR.scope_of_key(k) == 'candidate'}; frozen_b0 = {k: v for k, v in pf['ch'].items() if R.PR.scope_of_key(k) == 'b0_frozen_v14'}
        import fractions; EPS = fractions.Fraction(str((man.get('task') or {}).get('epsilon', '1/200'))); models = {}
        G._agg['deadline'] = t0 + budget; PG._agg['deadline'] = G._agg['deadline']; G._evidence.clear(); PG._evidence.clear(); G._attrib.clear()
        order = [cid for cid in sorted(receipts) if (subset is None or cid in subset)]
        if subset is not None and len(order) != len(subset): fail('*', 'mechanics subset names %d unknown cells' % (len(subset) - len(order)))
        for cid in order:
            r = receipts[cid]; c = cells[cid]
            entry = dict(cell_id=cid, receipt_sha256=r['_sha'], output_sha256=r.get('output_sha256'), status=r.get('status'), outcome=r.get('outcome'), guarantee=r.get('guarantee_type'), arm=c['arm'], cohort=c['cohort'], budget_s=c['budget_s'], case_id=c['case_id'], replicate=c['replicate'], kind=c.get('kind'), evidence={}, verified=False, verified_attribution=None); gated.append(entry)
            if exhausted_at is not None: fail(cid, 'UNVERIFIABLE -- aggregate verification budget exhausted before this cell was checked'); prog.write(json.dumps(dict(cell_id=cid, verified=False, note='budget exhausted')) + '\n'); prog.flush(); continue
            G._cell_paths.clear(); PG._cell_paths.clear(); nf = len(failures)
            try:
                if R.validator_of(c['arm']) == 'cqr_candidate': G._check_cqr_cell(RD, cid, r, c, man, producer_cqr, failures, fail, G.REPLAY_FACTOR, counters)        # worker identity vs the PRODUCER scope; the checker is the VERIFIER build's
                else:
                    n0 = counters['checked']; G.bind_task_dependencies(c, fail); PG._check_cell(RD, cid, r, c, man, frozen_cand, frozen_b0, models, failures, fail, EPS, G.REPLAY_FACTOR, counters); counters['baseline_checked'] += counters['checked'] - n0
                if man.get('kernel_identity') and r.get('worker_output') and os.path.exists(os.path.join(RD, r['worker_output'])) and KI.tags_needed_by(c['arm']):
                    try: w_ = json.load(open(os.path.join(RD, r['worker_output'])))
                    except (ValueError, OSError): w_ = None
                    if w_ is not None:
                        for m_ in KI.receipt_failures(man['kernel_identity'], w_, c['arm']): fail(cid, 'loaded kernel provenance (ORIGINAL identity): ' + m_)
                        if R.validator_of(c['arm']) == 'cqr_candidate': counters['cqr_provenance_checked'] += 1
            except (G.GateBudgetExhausted, PG.GateBudgetExhausted): exhausted_at = cid; fail(cid, 'UNVERIFIABLE -- aggregate verification budget exhausted while checking this cell')
            except Exception as ex: fail(cid, 'SUCCESSOR CHECK FAULT: %s: %s' % (type(ex).__name__, str(ex)[:160]))
            entry['verified_attribution'] = G._attrib.get(cid); paths = set(G._cell_paths) | set(PG._cell_paths)
            for p_ in PG._cell_paths: G._evidence[p_] = PG._evidence.get(p_)
            entry['evidence'] = {(os.path.relpath(k, RD) if k.startswith(RD + os.sep) else k): G._evidence.get(k) for k in sorted(paths)}; entry['verified'] = (len(failures) == nf)
            h = inv['receipts'][cid]
            if h.get('in_original_gated_set') and entry['verified'] and entry['evidence'] != h.get('evidence'): fail(cid, 'dependency closure hashed by the successor differs from the ORIGINAL gate\'s closure'); entry['verified'] = False
            prog.write(json.dumps(dict(cell_id=cid, verified=entry['verified'], failures=len(failures) - nf, elapsed_s=round(time.monotonic() - t0, 3))) + '\n'); prog.flush()
        if G._agg['deadline'] is not None and time.monotonic() > G._agg['deadline'] and exhausted_at is None and gated: exhausted_at = gated[-1]['cell_id']; fail(exhausted_at, 'UNVERIFIABLE -- the gate finished after its aggregate budget (final acceptance clock check)'); gated[-1]['verified'] = False
        status = 'INCOMPLETE_BUDGET_EXHAUSTED' if exhausted_at is not None else ('MECHANICS_CHECK' if subset is not None else 'COMPLETE')
    except Exception as ex:
        status = 'FAULT'; fail('*', 'SUCCESSOR GATE FAULT: %s: %s' % (type(ex).__name__, str(ex)[:200])); open(os.path.join(AD, 'FAULT_TRACE.txt'), 'w').write(traceback.format_exc())
    finally:
        prog.close(); res = write_result(status)
    print(json.dumps(dict(status=status, attempt=a.attempt, checked=len([g for g in gated]), gate_passed=res['gate_passed'], counters=counters, failures=failures[:6], wall_s=res['gate_wall_s']), default=str)[:1500])
    return 0 if res['gate_passed'] else 1


def report(a):
    jid, AM, am, am_sha, RD, MN, V, G = _load_prepared(a, 'report'); AD = os.path.join(AM, 'attempts', a.attempt); gp = os.path.join(AD, 'GATE_RESULT.json')
    if not os.path.exists(gp): raise SystemExit('refuse: attempt %s has no GATE_RESULT.json' % a.attempt)
    if os.path.exists(os.path.join(AD, 'RESULTS_CQR.json')): raise SystemExit('refuse: attempt %s already holds a report (immutable)' % a.attempt)
    gr = json.load(open(gp))
    if (gr.get('successor') or {}).get('amendment_manifest_sha256') != am_sha: raise SystemExit('refuse: the attempt result was produced under a different amendment manifest')
    p = subprocess.run([pybin(V), os.path.join(V, 'cex', 'cqr', 'report.py'), RD, '--manifest', MN, '--gate', gp, '--out-dir', AD], capture_output=True, text=True, cwd=V, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    open(os.path.join(AD, 'report_stdout.txt'), 'w').write(p.stdout); open(os.path.join(AD, 'report_stderr.txt'), 'w').write(p.stderr)
    ok = p.returncode == 0 and os.path.exists(os.path.join(AD, 'RESULTS_CQR.json'))
    rb = (json.load(open(os.path.join(AD, 'RESULTS_CQR.json'))).get('gate_binding') or {}) if ok else {}
    bound = ok and rb.get('gated_set_sha256') == gr.get('gated_set_sha256') and rb.get('gate_file_sha256') == sha(gp) and not rb.get('mismatch')
    json.dump(dict(step='report', attempt=a.attempt, jid=jid, rc=p.returncode, bound_to_attempt_gate=bound, gate_binding=rb, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(AD, 'REPORT_STEP.json'), 'w'), indent=1)
    print(json.dumps(dict(rc=p.returncode, bound_to_attempt_gate=bound, mismatch=(rb.get('mismatch') or [])[:3], tail=p.stdout[-200:])))
    return 0 if bound else 1


def closeout(a):
    jid, AM, am, am_sha, RD, MN, V, G = _load_prepared(a, 'closeout'); R = G.R; KI = G.KI; AD = os.path.join(AM, 'attempts', a.attempt); prereq = []; P = prereq.append
    man = json.load(open(os.path.join(RD, MN))); mh = sha(os.path.join(RD, MN)); inv = json.load(open(os.path.join(AM, 'ORIGINAL_INVENTORY.json'))); cells = man['cells']; planned_arms = sorted({c['arm'] for c in cells})
    for m_ in KI.failures_vs_frozen(man['kernel_identity'], KI.collect(V), planned_arms): P('kernel identity at closeout: ' + m_)
    gp = os.path.join(AD, 'GATE_RESULT.json'); G_ = json.load(open(gp)) if os.path.exists(gp) else None
    if G_ is None: P('attempt has no GATE_RESULT.json')
    else:
        su = G_.get('successor') or {}
        if su.get('schema') != 'CQR_SUCCESSOR_GATE_RESULT_V2' or su.get('attempt') != a.attempt: P('attempt result schema / attempt name differ')
        if su.get('amendment_manifest_sha256') != am_sha: P('attempt result was produced under a different amendment manifest')
        if su.get('status') != 'COMPLETE': P('attempt status %s is not COMPLETE (typed: %s)' % (su.get('status'), su.get('note')))
        if su.get('mechanics_check_cells'): P('a MECHANICS CHECK is never a gate')
        if G_.get('failures'): P('successor gate lists %d failures (first: %s)' % (len(G_['failures']), str(G_['failures'][0])[:160]))
        if not G_.get('gate_passed'): P('successor gate FAILED')
        if G_.get('manifest_sha256') != mh or G_.get('artifact_hashes_sha256') != am['producer_identity']['artifact_hashes_sha256']: P('successor gate binds a different manifest / frozen inventory')
        gs = G_.get('gated_set')
        if not isinstance(gs, list): P('successor gate carries no gated set')
        else:
            if G_.get('gated_set_sha256') != hashlib.sha256(json.dumps(gs, sort_keys=True).encode()).hexdigest(): P('gated set digest does not match')
            ids = [e['cell_id'] for e in gs]
            if len(ids) != len(set(ids)) or set(ids) != {c['cell_id'] for c in cells} or G_.get('planned') != len(cells) or G_.get('receipts') != len(cells): P('gated set / counts are not exactly the planned set (%d gated, %d planned, planned field %s, receipts field %s)' % (len(ids), len(cells), G_.get('planned'), G_.get('receipts')))
            for e in gs:
                h = inv['receipts'].get(e['cell_id'])
                if h is None: P('gated cell %s is not in the historical authority' % e['cell_id']); break
                if e.get('receipt_sha256') != h['sha256'] or e.get('output_sha256') != h['output_sha256']: P('gated hashes of %s differ from the historical authority' % e['cell_id']); break
                rp = os.path.join(RD, h['path'])
                if (sha(rp) if os.path.exists(rp) else None) != h['sha256']: P('receipt %s on disk differs from the authority now' % e['cell_id']); break
                if (e.get('status') == 'COMPLETED' or e.get('outcome') == 'PROVED_ZERO_EVIDENCE') and e.get('verified') is not True: P('gated entry %s was not verified' % e['cell_id']); break
        for k in ('producer_identity', 'verifier_identity'):
            if (su.get(k) or {}).get('full_inventory_sha256') != am[k]['full_inventory_sha256']: P('%s of the attempt differs from the prepared one' % k)
        if su.get('tool_identity_sha256') != am['tool_identity']['sha256']: P('tool identity of the attempt differs from the prepared one')
    rows = ledger_rows(AM); by_scope = collections.defaultdict(float)
    for x in rows:
        if x.get('kind') == 'RECEIPT' and isinstance(x.get('wall_s'), (int, float)): by_scope[x.get('scope')] += x['wall_s']
    for scope, job in ((SCOPES['execute'], 'successor_gate:%s' % a.attempt), (SCOPES['report'], 'successor_report:%s' % a.attempt)):
        at = [x for x in rows if x.get('kind') == 'RECEIPT' and x.get('scope') == scope and x.get('job') == job]
        if not at: P('no supervised receipt (scope %s, job %s) in %s/CQR_LEDGER.jsonl' % (scope, job, os.path.basename(AM)))
        elif not (at[-1].get('outcome') == 'COMPLETED' and at[-1].get('returncode') == 0): P('the LATEST %s attempt ended %s rc %s' % (job, at[-1].get('outcome'), at[-1].get('returncode')))
    rp_ = os.path.join(AD, 'RESULTS_CQR.json'); RES = json.load(open(rp_)) if os.path.exists(rp_) else None
    if RES is None: P('attempt has no RESULTS_CQR.json')
    elif G_ is not None:
        rb = RES.get('gate_binding') or {}
        if rb.get('gated_set_sha256') != G_.get('gated_set_sha256') or rb.get('gate_file_sha256') != sha(gp): P('the report does not bind this attempt\'s gate file / gated set')
        if rb.get('mismatch'): P('report records %d gated-set mismatches' % len(rb['mismatch']))
        if RES.get('manifest_sha256') != mh: P('report manifest identity differs')
        if not str(RES.get('report_version', '')).startswith('cqr-report-v1'): P('results produced by an unknown reporter (%s)' % RES.get('report_version'))
        if os.path.getmtime(rp_) < os.path.getmtime(gp): P('RESULTS_CQR.json is older than the attempt gate')
        td = tempfile.mkdtemp(prefix='succ_rederive_')
        p = subprocess.run([pybin(V), os.path.join(V, 'cex', 'cqr', 'report.py'), RD, '--manifest', MN, '--gate', gp, '--out-dir', td], capture_output=True, text=True, cwd=V, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        RR = json.load(open(os.path.join(td, 'RESULTS_CQR.json'))) if os.path.exists(os.path.join(td, 'RESULTS_CQR.json')) else None
        if RR is None: P('report re-derivation failed (rc %s): %s' % (p.returncode, p.stderr[-160:]))
        else:
            core_run = lambda x: json.loads(json.dumps({k: x.get(k) for k in SEMANTIC_RUN_FIELDS}, sort_keys=True, default=str))
            if RR.get('summary_sha256') != RES.get('summary_sha256') or RR.get('summary') != RES.get('summary'): P('RESULTS_CQR.json summary differs from the summary RE-DERIVED from the raw records')
            if sorted((core_run(x) for x in RES.get('runs') or []), key=lambda x: str(x['cell_id'])) != sorted((core_run(x) for x in RR.get('runs') or []), key=lambda x: str(x['cell_id'])): P('report run rows differ from the re-derived rows')
            inacc = [x for x in (RR.get('reference_audit') or []) if x.get('accurate') == 'CONFIRMED_INACCURATE']
            if inacc: P('INVESTIGATE: %d DETERMINISTIC publications / zero claims are contradicted by an exact reference' % len(inacc))
        shutil.rmtree(td, ignore_errors=True)
    Q = json.load(open(a.qualification)) if os.path.exists(a.qualification) else None
    if Q is None: P('qualification record missing')
    else:
        names = [g.get('name') for g in (Q.get('groups') or [])]
        if not str(Q.get('suite_version', '')).startswith('cqr-qualification'): P('qualification record from a foreign suite')
        if names != list(R.QUALIFICATION_GROUPS) or len(names) != len(set(names)): P('qualification groups differ from the registry schema')
        if not Q.get('all_pass') or Q.get('passed') != Q.get('total') or Q.get('total') != len(names) or not names or not all(g.get('ok') is True for g in Q['groups']): P('qualification groups not all passed')
        qs = Q.get('candidate_sources') or {}; vc = R.cqr_source_inventory(V)
        if qs != vc: P('qualification record identity does not equal the VERIFIER cqr scope (%d differing / missing / extra; e.g. %s)' % (len([k for k in set(qs) | set(vc) if qs.get(k) != vc.get(k)]), [k for k in set(qs) | set(vc) if qs.get(k) != vc.get(k)][:1]))
        if Q.get('suite_sha256') != R.suite_sha256(V): P('qualification record was produced by a different suite file than the verifier build\'s')
        pc = am['producer_identity']['cqr_scope']; diffp = sorted(k for k in set(pc) | set(vc) if pc.get(k) != vc.get(k))
        if [k for k in diffp if k not in am['allowed_verifier_only_files']]: P('producer cqr scope differs from the qualified verifier scope outside the verifier-only files')
    verdict = 'SUCCESSOR VERIFICATION QUALIFIED' if not prereq else ('INVESTIGATE' if any(p.startswith('INVESTIGATE') for p in prereq) else 'UNQUALIFIED')
    L = ['# CQR SUCCESSOR VERIFICATION -- CLOSEOUT (%s UTC; %s) -- %s' % (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), AMEND_VERSION, verdict), '',
         'Original shard `%s` (manifest `%s` sha256 `%s`; original gate %s with %d failures, RETAINED). Producer identity %s (full inventory `%s`); verifier identity `%s` (build `%s`, git `%s`); tool identity `%s`; verifier-only files %s. Attempt `%s`: %s.' % (RD, MN, mh[:16], 'PASSED' if am['original'].get('gate_passed') else ('FAILED' if am['original'].get('gate_passed') is False else 'none (fresh shard)'), am['original'].get('gate_failures') or 0, am['producer_identity']['commit'][:12], am['producer_identity']['full_inventory_sha256'][:16], am['verifier_identity']['full_inventory_sha256'][:16], V, str(am['verifier_identity'].get('git_head'))[:12], am['tool_identity']['sha256'][:16], am['allowed_verifier_only_files'], a.attempt, ((G_ or {}).get('successor') or {}).get('status')),
         '', 'Charged seconds by scope (%s/CQR_LEDGER.jsonl): %s; total %.1f s.' % (os.path.basename(AM), json.dumps({k: round(v, 1) for k, v in sorted(by_scope.items())}), sum(by_scope.values())), '']
    if prereq: L += ['## Prerequisites failed -- NO qualified verdict', ''] + ['- %s' % x for x in prereq] + ['']
    counts = ((RES or {}).get('outcome_counts_by_arm') or {}); L += ['## Counts by arm (from the attempt report)', '', '| arm | planned | received | PUBLISHED-DETERMINISTIC | PUBLISHED-PAC | PROVED_ZERO_EVIDENCE | DEADLINE | MEMORY | FAULT | other |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for arm, d in counts.items(): L.append('| %s | %d | %d | %s |' % (arm, d.get('planned', 0), d.get('received', 0), ' | '.join(str(d.get(k, 0)) for k in ('PUBLISHED-DETERMINISTIC', 'PUBLISHED-PAC', 'PROVED_ZERO_EVIDENCE', 'DEADLINE', 'MEMORY', 'FAULT', 'other'))))
    L += ['', '## Verdict', '', '**%s.** %s' % (verdict, 'Every prerequisite holds: the complete planned set of the ORIGINAL shard, every receipt / output / dependency equal to the historical authority (ledger + original gate), re-verified by the separately identified verifier under the chain, report bound to this attempt\'s gate and re-derived equal, qualification record bound to the verifier identity, no deterministic contradiction. Counts only; no performance claim. The original FAILED gate is retained beside this record.' if not prereq else 'Prerequisites failed (listed above). Nothing is accepted.')]
    open(os.path.join(AD, 'CLOSEOUT_SUCCESSOR.md'), 'w').write('\n'.join(L) + '\n'); json.dump(dict(step='closeout', attempt=a.attempt, jid=jid, verdict=verdict, prerequisites_failed=prereq, qualification=a.qualification, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())), open(os.path.join(AD, 'CLOSEOUT_STEP.json'), 'w'), indent=1)
    print('closeout:', verdict, ('(%d reasons)' % len(prereq)) if prereq else '')
    for x in prereq: print('  -', x[:240])
    return 0 if not prereq else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest='cmd', required=True)
    p1 = sub.add_parser('prepare'); p1.add_argument('--original', required=True); p1.add_argument('--verifier-build', required=True); p1.add_argument('--out', required=True); p1.add_argument('--manifest', default='CAMPAIGN_MANIFEST.json'); p1.add_argument('--producer-commit', default='f672b69b74a65445576688fc7b8215cab50e8aa0'); p1.add_argument('--allowed-verifier-files', default='cqr/checker.py,cqr/registry.py,cqr/gate.py,cqr/report.py'); p1.add_argument('--fresh', action='store_true'); p1.add_argument('--closure-exception', default=''); p1.add_argument('--closure-justification', default='')
    p2 = sub.add_parser('execute'); p2.add_argument('--amend', required=True); p2.add_argument('--attempt', required=True); p2.add_argument('--cells', default=None); p2.add_argument('--budget-s', type=float, default=None); p2.add_argument('--label', default='')
    p3 = sub.add_parser('report'); p3.add_argument('--amend', required=True); p3.add_argument('--attempt', required=True)
    p4 = sub.add_parser('closeout'); p4.add_argument('--amend', required=True); p4.add_argument('--attempt', required=True); p4.add_argument('--qualification', required=True)
    a = ap.parse_args(); sys.exit(dict(prepare=prepare, execute=execute, report=report, closeout=closeout)[a.cmd](a))
