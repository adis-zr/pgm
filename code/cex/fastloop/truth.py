"""INDEPENDENT truth for development tasks (CQR-FL-02 repaired): exact rational enumeration or bucket elimination by the PINNED ORACLE of the accepted baseline (cex/cqr/oracle.py; nothing of
the solver / compiler / decoder), computed in a FRESH SUBPROCESS under a hard timeout (never in the harness process: genuine isolation and a hard bound). Cached IMMUTABLY by the full task
digest; EVERY cache hit is validated against (a) the task digest and its parts re-derived from the bytes on disk, (b) the oracle DEPENDENCY identity (oracle.py + task.py + newarm/core.py
sha256 of the accepted build: parser / reader included), (c) the record's own CONTENT digest (sha256 of the canonical record without the seal). A record that fails any of these is a
CACHE_INTEGRITY failure (typed; never a solver truth miss, never silently recomputed as truth). On a valid hit the method and the ORIGINAL preparation cost are preserved; a recomputation is
charged once by its caller."""
import os, sys, json, time, hashlib, subprocess

def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def task_parts(model_path):
    ev = model_path + '.evid'; qp = model_path + '.query.json'
    return [sha_file(model_path), sha_file(ev) if os.path.exists(ev) else hashlib.sha256(b'0').hexdigest(), sha_file(qp) if os.path.exists(qp) else 'all_singletons']
def task_digest(model_path):
    parts = task_parts(model_path); return hashlib.sha256('|'.join(parts).encode()).hexdigest(), parts
def oracle_identity(oracle_dir):
    """the oracle DEPENDENCY identity: the inference-independent oracle AND the shared task / UAI parsers it relies on"""
    deps = {k: sha_file(os.path.join(oracle_dir, *k.split('/'))) for k in ('cex/cqr/oracle.py', 'cex/cqr/task.py', 'cex/newarm/core.py')}
    return dict(files=deps, sha256=hashlib.sha256(json.dumps(deps, sort_keys=True).encode()).hexdigest())
def _seal(rec):
    body = {k: v for k, v in rec.items() if k not in ('content_sha256', 'cache_hit')}
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
def validate_record(rec, model_path, oracle_dir):
    """returns [] when the cached record binds this task, this oracle identity and its own content; else the list of integrity failures"""
    fails = []; dg, parts = task_digest(model_path); oid = oracle_identity(oracle_dir)
    if not isinstance(rec, dict): return ['record is not an object']
    if rec.get('schema') != 'CQR_FASTLOOP_TRUTH_V2': fails.append('record schema %s is not CQR_FASTLOOP_TRUTH_V2' % rec.get('schema'))
    if rec.get('digest') != dg: fails.append('record task digest differs from the bytes on disk')
    if rec.get('parts') != parts: fails.append('record task parts (model / evidence / query sha256) differ from the bytes on disk')
    if (rec.get('oracle') or {}).get('sha256') != oid['sha256']: fails.append('record oracle dependency identity differs from the accepted oracle (oracle.py / task.py / core.py)')
    if rec.get('status') not in ('EXACT', 'UNRESOLVED'): fails.append('record status %s unknown' % rec.get('status'))
    if rec.get('status') == 'EXACT' and rec.get('method') not in ('enumeration', 'elimination'): fails.append('record method %s unknown' % rec.get('method'))
    if rec.get('content_sha256') != _seal(rec): fails.append('record content seal does not match (altered record)')
    return fails
def truth_for(model_path, oracle_dir, cache_dir, max_assignments=1 << 20, max_table=1 << 22, deadline_s=60.0, allow_compute=True):
    """{status: EXACT | UNRESOLVED | CACHE_INTEGRITY | NOT_RUN, method, Z, answers, prep_s, cache_hit, oracle, integrity_failures}"""
    os.makedirs(cache_dir, exist_ok=True); dg, parts = task_digest(model_path); cp = os.path.join(cache_dir, dg + '.json'); oid = oracle_identity(oracle_dir)
    if os.path.exists(cp):
        try: rec = json.load(open(cp))
        except Exception as ex: rec = dict(parse_error=str(ex)[:80])
        bad = validate_record(rec, model_path, oracle_dir)
        if not bad: rec = dict(rec); rec['cache_hit'] = True; return rec
        return dict(status='CACHE_INTEGRITY', digest=dg, parts=parts, oracle=oid, integrity_failures=bad, cache_file=cp, cache_hit=False, note='a corrupted / foreign / stale cache record is an INTEGRITY failure of the harness inputs, not a solver truth miss; nothing was recomputed silently')
    if not allow_compute: return dict(status='NOT_RUN', digest=dg, parts=parts, oracle=oid, reason='no cache record and computation not allowed in this phase', cache_hit=False)
    cmd = [_pybin(oracle_dir), '-c', _CHILD, model_path, oracle_dir, str(max_assignments), str(max_table), str(deadline_s)]
    try: p = subprocess.run(cmd, capture_output=True, text=True, timeout=deadline_s + 5.0, cwd=oracle_dir, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    except subprocess.TimeoutExpired: return dict(status='UNRESOLVED', digest=dg, parts=parts, oracle=oid, method=None, reason='oracle subprocess exceeded its hard timeout (%.0f s)' % deadline_s, prep_s=deadline_s, cache_hit=False)
    try: out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception: return dict(status='UNRESOLVED', digest=dg, parts=parts, oracle=oid, method=None, reason='oracle subprocess produced no result (rc %s): %s' % (p.returncode, p.stderr[-160:]), prep_s=None, cache_hit=False)
    rec = dict(schema='CQR_FASTLOOP_TRUTH_V2', digest=dg, parts=parts, oracle=dict(dir=oracle_dir, **oid), utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), caps=dict(max_assignments=max_assignments, max_table=max_table, deadline_s=deadline_s), **out)
    if rec['status'] == 'UNRESOLVED': rec['reason'] = 'beyond enumeration (2^%d) and elimination (table 2^%d) within %.0f s' % (max_assignments.bit_length() - 1, max_table.bit_length() - 1, deadline_s)
    rec['content_sha256'] = _seal(rec); json.dump(rec, open(cp, 'w'), indent=1); rec = dict(rec); rec['cache_hit'] = False; return rec
def containment(w, rec):
    """CONTAINED / MISS / UNRESOLVED / CACHE_INTEGRITY / NA for a PUBLISHED worker output against the truth record (deterministic misses are hard failures for the caller; PAC misses are preserved)"""
    from fractions import Fraction as F
    if w.get('outcome') != 'PUBLISHED': return 'NA'
    if rec.get('status') == 'CACHE_INTEGRITY': return 'CACHE_INTEGRITY'
    if rec.get('status') != 'EXACT': return 'UNRESOLVED'
    ans = w.get('answers') or []
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
    return 'CONTAINED'
def zero_claim_check(rec):
    """for a PROVED_ZERO_EVIDENCE outcome: AGREES (Z = 0) / CONTRADICTED (Z > 0) / UNRESOLVED / CACHE_INTEGRITY"""
    from fractions import Fraction as F
    if rec.get('status') == 'CACHE_INTEGRITY': return 'CACHE_INTEGRITY'
    if rec.get('status') != 'EXACT': return 'UNRESOLVED'
    return 'AGREES' if F(rec['Z']) == 0 else 'CONTRADICTED'
