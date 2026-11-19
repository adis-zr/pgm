"""INDEPENDENT truth for development tasks (CQR-FL-02 repaired; repair-2 review CQR-AF2-05 / truth-index): exact rational enumeration or bucket elimination by the PINNED ORACLE of the
accepted baseline (cex/cqr/oracle.py; nothing of the solver / compiler / decoder), computed in a FRESH SUBPROCESS under a hard timeout. The child must EXIT NORMALLY (rc 0) and print a
valid record: a result followed by an abnormal exit is ORACLE_FAULT (typed; never cached, never EXACT); the child's rc / timeout are recorded with every result. Cached IMMUTABLY by the
full task digest; EVERY cache hit is validated against (a) the task digest and its parts re-derived from the bytes on disk, (b) the oracle DEPENDENCY identity (oracle.py + task.py +
newarm/core.py sha256 of the accepted build), (c) the record's own CONTENT digest, and (d) when the cache directory carries a TRUSTED PREPARATION INDEX (TRUTH_INDEX.json, written once by
truth_prep under a supervised receipt: {task digest: record file sha256}), the record FILE's sha256 must equal the index entry and a record file the index does not list is refused.
TRUSTED-WRITER BOUNDARY (stated, not assumed away): the index and the records live in the same directory; the index's sha256 is recorded in TRUTH_PREP.json and in every iteration
report, so a coherent replacement of records AND index is detectable only by comparing those recorded index digests (or the supervised preparation receipt) -- the self-contained record
seal alone is NOT independent authentication, and this module never claims it is. A record that fails any check is a CACHE_INTEGRITY failure (typed; never a solver truth miss, never
silently recomputed as truth)."""
import os, sys, json, time, hashlib, subprocess
ZERO_HASH = hashlib.sha256(b'0').hexdigest()
INDEX_NAME = 'TRUTH_INDEX.json'

def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def task_parts(model_path):
    ev = model_path + '.evid'; qp = model_path + '.query.json'
    return [sha_file(model_path), sha_file(ev) if os.path.exists(ev) else ZERO_HASH, sha_file(qp) if os.path.exists(qp) else 'all_singletons']
def pinned_parts(model_sha256, evidence_sha256, query_sha256):
    """the manifest's pinned triple in the READER's representation (absent evidence = sha256(b'0'); absent query spec = 'all_singletons') -- ONE normalization used by every consumer"""
    return [model_sha256, evidence_sha256 if evidence_sha256 is not None else ZERO_HASH, query_sha256 if query_sha256 is not None else 'all_singletons']
def task_digest(model_path):
    parts = task_parts(model_path); return hashlib.sha256('|'.join(parts).encode()).hexdigest(), parts
def oracle_identity(oracle_dir):
    """the oracle DEPENDENCY identity: the inference-independent oracle AND the shared task / UAI parsers it relies on"""
    deps = {k: sha_file(os.path.join(oracle_dir, *k.split('/'))) for k in ('cex/cqr/oracle.py', 'cex/cqr/task.py', 'cex/newarm/core.py')}
    return dict(files=deps, sha256=hashlib.sha256(json.dumps(deps, sort_keys=True).encode()).hexdigest())
def _seal(rec):
    body = {k: v for k, v in rec.items() if k not in ('content_sha256', 'cache_hit', 'indexed')}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
def _pybin(b): return os.path.join(b, '.venv', 'bin', 'python') if os.path.exists(os.path.join(b, '.venv', 'bin', 'python')) else sys.executable
_CHILD = r'''
import sys, json, time, os
mp, oracle_dir, max_a, max_t, dl = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
sys.path.insert(0, os.path.join(oracle_dir, 'cex', 'cqr')); sys.path.insert(0, os.path.join(oracle_dir, 'cex', 'newarm'))
import task as TK, oracle as OR
t0 = time.monotonic(); task = TK.load_task(mp); norm = bool((task.get('query_spec') or {}).get('normalizer_task'))
qs = task['queries'] if not norm else [TK.singleton_query(0, 0, task['model']['cards'])]
r = OR.enumerate_truth(task['model'], qs, deadline=t0 + dl, max_assignments=max_a); method = 'enumeration'
if r is None: r = OR.eliminate_truth(task['model'], qs, deadline=t0 + dl, max_table=max_t); method = 'elimination'
out = dict(prep_s=round(time.monotonic() - t0, 4), normalizer=norm)
if r is None: out.update(status='UNRESOLVED', method=None)
else: out.update(status='EXACT', method=method, Z=str(r['Z']), answers=(None if norm else [str(a) for a in r['answers']]))
print(json.dumps(out))
'''
def _record_shape_problem(rec):
    """the TYPED schema of a truth record (never consumed before validation)"""
    from fractions import Fraction as F
    if not isinstance(rec, dict): return 'record is not an object'
    if rec.get('status') not in ('EXACT', 'UNRESOLVED'): return 'record status %s unknown' % rec.get('status')
    if rec.get('status') == 'EXACT':
        if rec.get('method') not in ('enumeration', 'elimination'): return 'record method %s unknown' % rec.get('method')
        try: F(str(rec.get('Z')))
        except (ValueError, ZeroDivisionError, TypeError): return 'record Z is not a rational'
        if rec.get('normalizer'):
            if rec.get('answers') is not None: return 'normalizer record carries answers'
        else:
            ans = rec.get('answers')
            if not isinstance(ans, list) or not ans: return 'record answers missing'
            for a in ans:
                if a in ('UNDEFINED', 'ZERO_EVIDENCE'): continue
                try: F(str(a))
                except (ValueError, ZeroDivisionError, TypeError): return 'record answer %r is not a rational' % (str(a)[:20],)
    return None
def load_index(cache_dir):
    p = os.path.join(cache_dir, INDEX_NAME)
    if not os.path.exists(p): return None
    try: idx = json.load(open(p))
    except Exception: return dict(error='unreadable', sha256=sha_file(p))
    idx['_sha256'] = sha_file(p); return idx
def write_index(cache_dir, oracle_dir, note=''):
    """the TRUSTED PREPARATION INDEX: every record file of the cache by task digest -> file sha256 (written ONCE by the preparation step; refuses to overwrite)"""
    p = os.path.join(cache_dir, INDEX_NAME)
    if os.path.exists(p): raise SystemExit('refuse: %s exists (the preparation index is written once; prepare a new cache directory for a new index)' % p)
    recs = {}
    for fn in sorted(os.listdir(cache_dir)):
        if fn.endswith('.json') and fn != INDEX_NAME and len(fn) == 69: recs[fn[:-5]] = sha_file(os.path.join(cache_dir, fn))
    idx = dict(schema='CQR_FASTLOOP_TRUTH_INDEX_V1', utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), oracle=oracle_identity(oracle_dir), records=recs, note=note, trusted_writer_boundary='written by truth_prep under a supervised receipt; its sha256 is recorded in TRUTH_PREP.json and in every iteration report; a coherent replacement of records and index is detectable only against those recorded digests')
    json.dump(idx, open(p, 'w'), indent=1, sort_keys=True); return sha_file(p)
def validate_record(rec, model_path, oracle_dir, record_file=None, index=None):
    """returns [] when the cached record binds this task, this oracle identity, its own content and (when an index is given) the trusted preparation index; else the list of integrity failures"""
    fails = []; dg, parts = task_digest(model_path); oid = oracle_identity(oracle_dir)
    if not isinstance(rec, dict): return ['record is not an object']
    if rec.get('schema') != 'CQR_FASTLOOP_TRUTH_V2': fails.append('record schema %s is not CQR_FASTLOOP_TRUTH_V2' % rec.get('schema'))
    if rec.get('digest') != dg: fails.append('record task digest differs from the bytes on disk')
    if rec.get('parts') != parts: fails.append('record task parts (model / evidence / query sha256) differ from the bytes on disk')
    if (rec.get('oracle') or {}).get('sha256') != oid['sha256']: fails.append('record oracle dependency identity differs from the accepted oracle (oracle.py / task.py / core.py)')
    sp = _record_shape_problem(rec)
    if sp: fails.append(sp)
    if rec.get('child_rc', 0) != 0: fails.append('record was produced by an oracle child that exited abnormally (rc %s)' % rec.get('child_rc'))
    if rec.get('content_sha256') != _seal(rec): fails.append('record content seal does not match (altered record)')
    if index is not None and record_file is not None:
        if index.get('error'): fails.append('trusted preparation index unreadable')
        else:
            want = (index.get('records') or {}).get(dg)
            if want is None: fails.append('record file is not listed in the trusted preparation index (unprepared record present in the cache)')
            elif sha_file(record_file) != want: fails.append('record file sha256 differs from the trusted preparation index entry')
            if (index.get('oracle') or {}).get('sha256') != oid['sha256']: fails.append('trusted preparation index was written for a different oracle identity')
    return fails
def truth_for(model_path, oracle_dir, cache_dir, max_assignments=1 << 20, max_table=1 << 22, deadline_s=60.0, allow_compute=True, hard_timeout_s=None, index='auto', persist=True):
    """{status: EXACT | UNRESOLVED | ORACLE_FAULT | CACHE_INTEGRITY | NOT_RUN, method, Z, answers, prep_s, cache_hit, indexed, oracle, child_rc, integrity_failures}.
    `hard_timeout_s`: the subprocess wait (the caller's remaining allowance; default deadline_s + 5). `index`: 'auto' loads TRUTH_INDEX.json from cache_dir when present; None disables.
    `persist`: write a freshly computed record into cache_dir (the runner passes False when the cache carries a trusted index: an in-run computation never pollutes the indexed cache)."""
    os.makedirs(cache_dir, exist_ok=True); dg, parts = task_digest(model_path); cp = os.path.join(cache_dir, dg + '.json'); oid = oracle_identity(oracle_dir)
    idx = load_index(cache_dir) if index == 'auto' else index
    if os.path.exists(cp):
        try: rec = json.load(open(cp))
        except Exception as ex: rec = dict(parse_error=str(ex)[:80])
        bad = validate_record(rec, model_path, oracle_dir, record_file=cp, index=idx)
        if not bad: rec = dict(rec); rec['cache_hit'] = True; rec['indexed'] = idx is not None; return rec
        return dict(status='CACHE_INTEGRITY', digest=dg, parts=parts, oracle=oid, integrity_failures=bad, cache_file=cp, cache_hit=False, indexed=False, note='a corrupted / foreign / stale / unindexed cache record is an INTEGRITY failure of the harness inputs, not a solver truth miss; nothing was recomputed silently')
    if not allow_compute: return dict(status='NOT_RUN', digest=dg, parts=parts, oracle=oid, reason='no cache record and computation not allowed in this phase', cache_hit=False, indexed=False)
    cmd = [_pybin(oracle_dir), '-c', _CHILD, model_path, oracle_dir, str(max_assignments), str(max_table), str(deadline_s)]; hard = float(hard_timeout_s) if hard_timeout_s is not None else deadline_s + 5.0
    t = time.monotonic()
    try: p = subprocess.run(cmd, capture_output=True, text=True, timeout=max(0.1, hard), cwd=oracle_dir, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    except subprocess.TimeoutExpired: return dict(status='UNRESOLVED', digest=dg, parts=parts, oracle=oid, method=None, reason='oracle subprocess exceeded its hard wait (%.1f s; cooperative deadline %.1f s)' % (hard, deadline_s), prep_s=round(time.monotonic() - t, 3), cache_hit=False, indexed=False, child_rc=None, child_timed_out=True)
    try: out = json.loads(p.stdout.strip().splitlines()[-1]); assert isinstance(out, dict)
    except Exception: out = None
    if p.returncode != 0 or out is None:                                       # a result followed by an abnormal exit is NOT a result (repair-2 review CQR-AF2-05): typed, uncached, never EXACT
        return dict(status='ORACLE_FAULT', digest=dg, parts=parts, oracle=oid, method=None, reason='oracle subprocess %s (rc %s); %s: %s' % ('exited abnormally' if out is not None else 'produced no valid result', p.returncode, 'output discarded' if out is not None else 'stderr', p.stderr[-160:]), prep_s=round(time.monotonic() - t, 3), cache_hit=False, indexed=False, child_rc=p.returncode, child_timed_out=False, discarded_output=(out if out is not None else None))
    rec = dict(schema='CQR_FASTLOOP_TRUTH_V2', digest=dg, parts=parts, oracle=dict(dir=oracle_dir, **oid), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), caps=dict(max_assignments=max_assignments, max_table=max_table, deadline_s=deadline_s), child_rc=p.returncode, child_timed_out=False, **out)
    sp = _record_shape_problem(rec)
    if sp: return dict(status='ORACLE_FAULT', digest=dg, parts=parts, oracle=oid, method=None, reason='oracle result malformed: %s' % sp, prep_s=round(time.monotonic() - t, 3), cache_hit=False, indexed=False, child_rc=p.returncode, child_timed_out=False)
    if rec['status'] == 'UNRESOLVED': rec['reason'] = 'beyond enumeration (2^%d) and elimination (table 2^%d) within %.0f s' % (max_assignments.bit_length() - 1, max_table.bit_length() - 1, deadline_s)
    rec['content_sha256'] = _seal(rec)
    if persist: json.dump(rec, open(cp, 'w'), indent=1)
    rec = dict(rec); rec['cache_hit'] = False; rec['indexed'] = False; rec['persisted'] = bool(persist); return rec
def containment(w, rec):
    """CONTAINED / MISS / UNRESOLVED / ORACLE_FAULT / CACHE_INTEGRITY / NA for a PUBLISHED worker output against the truth record (deterministic misses are hard failures for the caller; PAC misses are preserved)"""
    from fractions import Fraction as F
    if w.get('outcome') != 'PUBLISHED': return 'NA'
    if rec.get('status') in ('CACHE_INTEGRITY', 'ORACLE_FAULT'): return rec['status']
    if rec.get('status') != 'EXACT': return 'UNRESOLVED'
    ans = w.get('answers') or []
    try:
        if rec.get('normalizer'):
            if not ans: return 'MISS'
            Z = F(rec['Z']); return 'CONTAINED' if (F(ans[0]['lo']) <= Z <= F(ans[0]['hi'])) else 'MISS'
        tr = rec['answers']
        if len(ans) != len(tr): return 'MISS'
        for a, t in zip(ans, tr):
            if t in ('UNDEFINED', 'ZERO_EVIDENCE'):
                if t == 'UNDEFINED' and a.get('status') != 'UNDEFINED': return 'MISS'
                continue
            if a.get('status') != 'OK' or not (F(a['lo']) <= F(t) <= F(a['hi'])): return 'MISS'
    except (ValueError, ZeroDivisionError, TypeError, KeyError, AttributeError): return 'MISS'          # malformed published answers never contain the truth
    return 'CONTAINED'
def zero_claim_check(rec):
    """for a PROVED_ZERO_EVIDENCE outcome: AGREES (Z = 0) / CONTRADICTED (Z > 0) / UNRESOLVED / ORACLE_FAULT / CACHE_INTEGRITY"""
    from fractions import Fraction as F
    if rec.get('status') in ('CACHE_INTEGRITY', 'ORACLE_FAULT'): return rec['status']
    if rec.get('status') != 'EXACT': return 'UNRESOLVED'
    return 'AGREES' if F(rec['Z']) == 0 else 'CONTRADICTED'
