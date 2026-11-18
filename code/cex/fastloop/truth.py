"""INDEPENDENT truth for development tasks: exact rational enumeration (tiny free space) or bucket elimination, computed by the PINNED ORACLE MODULE of the accepted baseline build
(cex/cqr/oracle.py: nothing of the solver / compiler / decoder under test), never from any worker output. Cached IMMUTABLY by the full task digest (model | evidence | query bytes |
epsilon | delta | mode) with the oracle's sha256, method and one-time preparation cost. A task beyond both methods within the allowance is recorded UNRESOLVED (never guessed)."""
import os, sys, json, time, hashlib, importlib.util
from fractions import Fraction as F

def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def task_digest(model_path):
    ev = model_path + '.evid'; qp = model_path + '.query.json'
    parts = [sha_file(model_path), sha_file(ev) if os.path.exists(ev) else hashlib.sha256(b'0').hexdigest(), sha_file(qp) if os.path.exists(qp) else 'all_singletons']
    return hashlib.sha256('|'.join(parts).encode()).hexdigest(), parts

def _load(oracle_dir):
    """import task.py + oracle.py + core.py from the PINNED oracle build under private module names (no collision with any other build imported in this process)"""
    cqr = os.path.join(oracle_dir, 'cex', 'cqr'); newarm = os.path.join(oracle_dir, 'cex', 'newarm')
    for p in (cqr, newarm):
        if p not in sys.path: sys.path.insert(0, p)
    import task as TK, oracle as OR
    return TK, OR

def truth_for(model_path, oracle_dir, cache_dir, max_assignments=1 << 20, max_table=1 << 22, deadline_s=60.0):
    """returns the cache record: {digest, status: EXACT|UNRESOLVED, method, Z, answers (str), prep_s, oracle_sha256, normalizer}"""
    os.makedirs(cache_dir, exist_ok=True); dg, parts = task_digest(model_path); cp = os.path.join(cache_dir, dg + '.json')
    if os.path.exists(cp): rec = json.load(open(cp)); rec['cache_hit'] = True; return rec
    TK, OR = _load(oracle_dir); osha = sha_file(os.path.join(oracle_dir, 'cex', 'cqr', 'oracle.py')); t0 = time.monotonic()
    task = TK.load_task(model_path); norm = bool((task.get('query_spec') or {}).get('normalizer_task'))
    qs = task['queries'] if not norm else [TK.singleton_query(0, 0, task['model']['cards'])]        # a normalizer task has no queries: Z is the truth; one dummy singleton drives the oracle
    r = OR.enumerate_truth(task['model'], qs, deadline=time.monotonic() + deadline_s, max_assignments=max_assignments); method = 'enumeration'
    if r is None: r = OR.eliminate_truth(task['model'], qs, deadline=time.monotonic() + deadline_s, max_table=max_table); method = 'elimination'
    prep = time.monotonic() - t0
    if r is None: rec = dict(digest=dg, parts=parts, status='UNRESOLVED', method=None, reason='beyond enumeration (2^%d cap) and elimination (table cap 2^%d) within %.0f s' % (max_assignments.bit_length() - 1, max_table.bit_length() - 1, deadline_s), prep_s=round(prep, 4), oracle_sha256=osha, normalizer=norm)
    else: rec = dict(digest=dg, parts=parts, status='EXACT', method=method, Z=str(r['Z']), answers=(None if norm else [str(a) for a in r['answers']]), prep_s=round(prep, 4), oracle_sha256=osha, oracle_dir=oracle_dir, normalizer=norm, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    json.dump(rec, open(cp, 'w'), indent=1); rec['cache_hit'] = False; return rec

def containment(w, rec, eps_normalizer=None):
    """CONTAINED / MISS / UNRESOLVED / NA for a worker output against the truth record (deterministic / exact publications must contain; PAC misses are preserved, not errors)"""
    if w.get('outcome') not in ('PUBLISHED',): return 'NA'
    if rec['status'] != 'EXACT': return 'UNRESOLVED'
    ans = w.get('answers') or []
    if rec.get('normalizer'):
        if not ans: return 'MISS'
        a = ans[0]; Z = F(rec['Z'])
        return 'CONTAINED' if (F(a['lo']) <= Z <= F(a['hi'])) else 'MISS'
    tr = rec['answers']
    if len(ans) != len(tr): return 'MISS'
    for a, t in zip(ans, tr):
        if t in ('UNDEFINED', 'ZERO_EVIDENCE'):
            if a.get('status') != 'UNDEFINED' and t == 'UNDEFINED': return 'MISS'
            continue
        if a.get('status') != 'OK' or not (F(a['lo']) <= F(t) <= F(a['hi'])): return 'MISS'
    return 'CONTAINED'
