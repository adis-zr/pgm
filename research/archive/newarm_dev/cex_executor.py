"""Certified compiled executor for the nonnegative bucket-contraction / all-singleton-reverse plan (certified executor pass, 11 Nov 2026).

Boundary (prompt section 5A): the executor receives an IMMUTABLE VALIDATED PLAN -- the evidence-restricted component model (exact nonnegative rational factor
occurrences, scope/axis order preserved, no deduplication), the selected elimination order over its unobserved variables, and the requested output = every
singleton row of the component's variables. It binds the plan (sha256 of the lowered semantic plan: cards, order, factor scopes and exact values) and
separately records the PHYSICAL schedule (dense / sparse representation per source, the kernel's fill threshold). Supports are not trusted metadata: the kernel
derives them from the exact zeros of the converted values.

Arithmetic contract (prompt section 6; proof-to-code map in PROOF_TO_CODE.md): binary64 round-to-nearest, u = 2^-53, with the reciprocal envelope label
a^E x <= xhat <= a^-E x (a = 1-u) maintained by the kernel per message / context / numerator (max over entries): source conversion E = 0 if exact else 1;
mul E1+E2+1; add max+1; sequential accumulation of m terms +(m-1); exact power-of-two rescaling +0. The final probability p = N_x / Z is formed EXACTLY in
Python from the kernel's doubles and binary exponents, then widened by K = E_N + E_Z: with delta = K u < 1, [p(1-delta), p/(1-delta)] contains the true value
(Bernoulli: a^K >= 1-Ku, a^-K <= 1/(1-Ku)), intersected with [0,1]. A range failure (non-normal intermediate from nonzero operands), a deadline, a memory cap
or a label overflow is a TYPED stop; the caller may then run the exact Fraction reference on the same plan (controlled fallback, charged) -- never an
approximate answer. Exact zeros: the kernel stores 0.0 only for an exact zero operand, so an all-zero root message is a typed ZERO_EVIDENCE for the component.

Memory: every kernel allocation is reserved against `cap_bytes` BEFORE it happens (capacity-based); messages and contexts are released after their final
reverse use; the peak logical reservation is reported beside the process RSS (sampled by the harness)."""
import ctypes as C, hashlib, json, math, os, subprocess, sys, time
from fractions import Fraction as F
from itertools import product
from pathlib import Path

BASE = Path(__file__).resolve().parent; SRC = BASE / 'cex_kernel.cpp'; LIB = BASE / 'libcex_kernel.dylib'; RECORD = BASE / 'cex_build.json'
FLAGS = ['-std=c++17', '-O2', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', '-fPIC', '-shared']
U = F(1, 2 ** 53); A = 1 - U
STOPS = {0: 'OK', 1: 'DEADLINE', 2: 'MEMORY', 3: 'RANGE', 4: 'BADPLAN', 5: 'FPENV', 6: 'FAULT', 7: 'ZERO_EVIDENCE'}
COUNTERS = ('forward_rows', 'reverse_rows', 'multiplications', 'additions', 'join_index_rows', 'join_probes', 'join_rows_generated', 'dense_rows', 'sparse_rows', 'rescale_entries', 'polls', 'messages_entries', 'contexts_entries', 'max_label', 'buckets_dense', 'buckets_sparse', 'source_values_converted', 'peak_logical_bytes', 'logical_bytes_at_exit', 'peak_join_rows', 'max_live_message_entries')


class Stop(Exception):
    def __init__(self, kind, reason, stats):
        super().__init__('%s: %s' % (kind, reason)); self.kind = kind; self.reason = reason; self.stats = dict(stats)


def build(deadline=None):
    """compile once per (source, flags); the record pins compiler, flags, source and binary hashes; a stale record triggers a rebuild (charged inside the attempt)"""
    sh = hashlib.sha256(SRC.read_bytes()).hexdigest(); prev = {}
    if RECORD.exists():
        try: prev = json.loads(RECORD.read_text())
        except (ValueError, OSError): prev = {}
    bsha = hashlib.sha256(LIB.read_bytes()).hexdigest() if LIB.exists() else None
    cxx = os.environ.get('CXX', 'clang++')
    if prev.get('source_sha256') != sh or prev.get('flags') != FLAGS or prev.get('binary_sha256') != bsha or bsha is None or prev.get('compiler') != cxx:
        t = time.monotonic(); tmp = LIB.with_name(LIB.name + '.tmp_%d' % os.getpid())
        try:
            remaining = None if deadline is None else max(0.001, deadline - time.monotonic())
            p = subprocess.run([cxx, *FLAGS, '-o', str(tmp), str(SRC)], capture_output=True, text=True, timeout=remaining)
            if p.returncode: raise RuntimeError(p.stderr[-2000:])
            tmp.replace(LIB)
        finally: tmp.unlink(missing_ok=True)
        ver = subprocess.run([cxx, '--version'], capture_output=True, text=True).stdout.splitlines()[0]
        prev = {'source_sha256': sh, 'binary_sha256': hashlib.sha256(LIB.read_bytes()).hexdigest(), 'flags': FLAGS, 'compiler': cxx, 'compiler_version': ver, 'build_wall_s': time.monotonic() - t, 'platform': sys.platform, 'built_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        RECORD.write_text(json.dumps(prev, indent=1) + '\n')
    return prev


_LIBS = {}
def load(prov):
    """hash-addressed immutable load (a dlopen handle is bound to the reported bytes even after a rebuild in the same process)"""
    digest = prov['binary_sha256']
    if digest in _LIBS: return _LIBS[digest]
    cache = BASE / 'native_cache'; cache.mkdir(exist_ok=True); path = cache / ('cex_%s.dylib' % digest)
    if not path.exists():
        b = LIB.read_bytes()
        if hashlib.sha256(b).hexdigest() != digest: raise RuntimeError('native binary changed between build and load')
        tmp = path.with_name(path.name + '.tmp_%d' % os.getpid()); tmp.write_bytes(b); tmp.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest: raise RuntimeError('hash-addressed binary failed identity check')
    lib = C.CDLL(str(path)); lib.cex_run.restype = C.c_int; lib.cex_schedule_id.restype = C.c_char_p
    lib.cex_run.argtypes = [C.POINTER(C.c_int64), C.c_int64, C.POINTER(C.c_double), C.c_int64, C.c_int64, C.c_double, C.c_double, C.POINTER(C.c_double), C.POINTER(C.c_int64), C.POINTER(C.c_int64), C.POINTER(C.c_double), C.POINTER(C.c_int64), C.POINTER(C.c_uint64), C.c_int64, C.c_char_p, C.c_int64]
    _LIBS[digest] = lib; prov['loaded_binary_path'] = str(path); prov['schedule_id'] = lib.cex_schedule_id().decode(); return lib


def convert(q):
    """nearest binary64 of an exact nonnegative rational with its label (0 exact, 1 one rounding); the relative bound is CHECKED exactly"""
    if q == 0: return 0.0, 0
    x = float(q)
    if not math.isfinite(x) or x < 2 * sys.float_info.min or x > sys.float_info.max / 2: raise Stop('RANGE', 'source conversion out of the supported binary64 range', {})
    if F(x) == q: return x, 0
    if not (A * q <= F(x) <= q / A): raise AssertionError('source conversion violates the one-rounding envelope')
    return x, 1


def lower(model, order, dense_fill_threshold=0.25, deadline=None):
    """validate + lower the semantic plan: evidence restriction, scalar cancellation, exact values -> doubles with labels, dense / sparse per source.
    Returns (plan_words, values, meta). meta carries the semantic plan hash (independent of representation) and the physical schedule hash."""
    cards = list(model['cards']); n = len(cards); ev = dict(model.get('evidence', {}))
    if any(type(c) is not int or c < 1 for c in cards): raise ValueError('invalid cardinality')
    if any(type(v) is not int or not 0 <= v < n or type(a) is not int or not 0 <= a < cards[v] for v, a in ev.items()): raise ValueError('invalid evidence')
    active = [v for v in range(n) if v not in ev]
    if sorted(order) != active: raise ValueError('order must cover the unobserved variables exactly')
    sem = hashlib.sha256(); sem.update(json.dumps({'cards': cards, 'evidence': sorted(ev.items()), 'order': list(order)}).encode())
    words = [n] + cards + [n] + [0] * 0; vals = []; srcs = []; stats = {'source_entries_read': 0, 'source_positive_rows': 0, 'scalar_factors_cancelled': 0, 'sources_dense': 0, 'sources_sparse': 0, 'conversion_exact': 0, 'conversion_rounded': 0}
    # the kernel order covers ALL n variable slots: observed variables get a trivial position at the end (their rows are restored exactly afterwards)
    korder = list(order) + [v for v in range(n) if v in ev]; words = [n] + cards + [n] + korder
    for f in model['factors']:
        sc = tuple(f['scope']); v_ = f['values']
        if len(sc) != len(set(sc)) or any(type(v) is not int or not 0 <= v < n for v in sc): raise ValueError('invalid factor scope')
        if len(v_) != math.prod(cards[v] for v in sc): raise ValueError('factor shape mismatch')
        keep = [i for i, v in enumerate(sc) if v not in ev]; newsc = tuple(sc[i] for i in keep); data = []; vol = math.prod(cards[v] for v in newsc)
        for a, w in zip(product(*(range(cards[v]) for v in sc)), v_):
            stats['source_entries_read'] += 1
            if not isinstance(w, F): w = F(w)
            if w < 0: raise ValueError('negative factor entry')
            if all(a[i] == ev[v] for i, v in enumerate(sc) if v in ev): data.append(w)
            if deadline is not None and stats['source_entries_read'] % 4096 == 0 and time.monotonic() >= deadline: raise Stop('DEADLINE', 'lowering deadline', stats)
        sem.update(json.dumps([list(newsc), [str(x) for x in data]]).encode())
        nz = sum(1 for w in data if w != 0); stats['source_positive_rows'] += nz
        if not newsc:
            if data[0] == 0: return None, None, dict(stats, zero_evidence=True)
            stats['scalar_factors_cancelled'] += 1; continue
        if nz == 0: return None, None, dict(stats, zero_evidence=True)
        dense = nz >= dense_fill_threshold * vol; lab = 0
        if dense:
            stats['sources_dense'] += 1; dv = []
            for w in data:
                x, l = convert(w); dv.append(x); lab = max(lab, l); stats['conversion_exact' if l == 0 else 'conversion_rounded'] += 1
            srcs.append((newsc, 0, None, dv, lab))
        else:
            stats['sources_sparse'] += 1; keys = []; dv = []
            for k, w in enumerate(data):
                if w != 0:
                    x, l = convert(w); keys.append(k); dv.append(x); lab = max(lab, l); stats['conversion_exact' if l == 0 else 'conversion_rounded'] += 1
            srcs.append((newsc, 1, keys, dv, lab))
    words.append(len(srcs))
    for sc, mode, keys, dv, lab in srcs:
        words += [len(sc)] + list(sc) + [mode, len(dv)]
        if mode == 1: words += keys
        words.append(lab); vals += dv
    phys = hashlib.sha256(json.dumps({'dense_fill_threshold': dense_fill_threshold, 'modes': [s[1] for s in srcs], 'kernel': hashlib.sha256(SRC.read_bytes()).hexdigest()}).encode()).hexdigest()
    return words, vals, dict(stats, semantic_plan_sha256=sem.hexdigest(), physical_schedule_sha256=phys, n=n, active=active, evidence=ev, cards=cards)


def execute(model, order, deadline=None, cap_bytes=3 * 1024 ** 3, dense_fill_threshold=0.25, host_reserved_bytes=0):
    """run the validated plan; returns dict(status, intervals, points, stats, certificate) or raises Stop (typed) / ValueError (invalid plan)"""
    t0 = time.monotonic(); stats = {'phase': 'build'}
    prov = build(deadline); lib = load(prov); stats['build_s'] = time.monotonic() - t0; stats['phase'] = 'lowering'; t = time.monotonic()
    words, vals, meta = lower(model, order, dense_fill_threshold, deadline); stats.update({k: v for k, v in meta.items() if k not in ('active', 'evidence', 'cards')}); stats['lowering_s'] = time.monotonic() - t
    if meta.get('zero_evidence'): return {'status': 'ZERO_EVIDENCE', 'intervals': None, 'stats': stats}
    n = meta['n']; cards = meta['cards']; ev = meta['evidence']
    kcap = cap_bytes - host_reserved_bytes - (len(words) * 8 + len(vals) * 8) * 2 - 64 * 1024 ** 2
    if kcap <= 0: raise Stop('MEMORY', 'host-side reservations leave no kernel capacity', stats)
    stats['kernel_cap_bytes'] = kcap; stats['phase'] = 'kernel'; t = time.monotonic()
    W = (C.c_int64 * len(words))(*words); V = (C.c_double * max(1, len(vals)))(*vals); tot = sum(cards)
    N = (C.c_double * tot)(); NE = (C.c_int64 * n)(); NL = (C.c_int64 * n)(); Z = (C.c_double * 1)(); ZM = (C.c_int64 * 2)(); CT = (C.c_uint64 * len(COUNTERS))(); RS = C.create_string_buffer(256)
    rc = lib.cex_run(W, len(words), V, len(vals), kcap, float('inf') if deadline is None else deadline, dense_fill_threshold, N, NE, NL, Z, ZM, CT, len(COUNTERS), RS, 256)
    stats['kernel_s'] = time.monotonic() - t; stats['counters'] = {k: int(CT[i]) for i, k in enumerate(COUNTERS)}; stats['kernel_status'] = STOPS.get(rc, 'UNKNOWN_%d' % rc); stats['kernel_reason'] = RS.value.decode(errors='replace')
    if rc == 7: return {'status': 'ZERO_EVIDENCE', 'intervals': None, 'stats': stats}
    if rc != 0: raise Stop(STOPS.get(rc, 'FAULT'), stats['kernel_reason'], stats)
    # ---- exact enclosure from the kernel's doubles + labels
    stats['phase'] = 'enclosure'; t = time.monotonic(); zv = F(Z[0]) * F(2) ** int(ZM[0]); zlab = int(ZM[1])
    if zv <= 0: raise Stop('RANGE', 'nonpositive Z', stats)
    intervals = []; points = []; off = 0; maxK = 0; maxw = F(0)
    for v in range(n):
        c = cards[v]
        if v in ev:
            row = [(F(int(a == ev[v])), F(int(a == ev[v]))) for a in range(c)]; pts = [F(int(a == ev[v])) for a in range(c)]
        else:
            K = int(NL[v]) + zlab; maxK = max(maxK, K); delta = K * U
            if delta >= F(1, 2): raise Stop('RANGE', 'error label too large for a certified enclosure (K=%d)' % K, stats)
            lo_f = 1 - delta; hi_f = 1 / (1 - delta); row = []
            for a in range(c):
                r = F(N[off + a]) * F(2) ** int(NE[v]) / zv
                if r == 0: row.append((F(0), F(0)))          # an exact zero numerator: exactly zero mass (exact zeros only arise from exact zero operands)
                else: row.append((max(F(0), r * lo_f), min(F(1), r * hi_f)))
            s_lo = sum(x for x, _ in row); s_hi = sum(y for _, y in row)
            if s_lo > 1 or s_hi < 1: raise AssertionError('enclosure box excludes the simplex (row %d)' % v)
            pts = [lo for lo, _ in row]; left = 1 - sum(pts)
            for a in range(c):
                take = min(left, row[a][1] - pts[a]); pts[a] += take; left -= take
            if left != 0: raise AssertionError('simplex point allocation failed')
            for (lo, hi), p in zip(row, pts): maxw = max(maxw, hi - lo)
        intervals.append(row); points.append(pts); off += c
    for row, pts in zip(intervals, points):
        if sum(pts) != 1 or any(not (0 <= lo <= p <= hi <= 1) for (lo, hi), p in zip(row, pts)): raise AssertionError('publication invariant')
    stats['enclosure_s'] = time.monotonic() - t; stats['max_label_K'] = maxK; stats['max_width'] = str(maxw); stats['max_width_float'] = float(maxw); stats['total_s'] = time.monotonic() - t0; stats['phase'] = 'complete'
    if maxw > F(1, 100): raise Stop('WIDTH', 'delivered width %s exceeds 1/100 (precision insufficient; retry or exact fallback required)' % float(maxw), stats)
    return {'status': 'CERTIFIED', 'intervals': intervals, 'points': points, 'stats': stats,
            'certificate': {'method': 'compiled_nonnegative_bucket_contraction_all_singleton_reverse', 'arithmetic': 'binary64 nearest with reciprocal-envelope labels (u=2^-53); exact N/Z in Python; Bernoulli widening by K=E_N+E_Z', 'order': list(order), 'semantic_plan_sha256': meta['semantic_plan_sha256'], 'physical_schedule_sha256': meta['physical_schedule_sha256'], 'kernel': {k: prov.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'flags', 'schedule_id')}, 'max_label_K': maxK, 'convention': 'unnormalized adjoints (zero-safe prefix/suffix exclusion products, no division); final exact N/Z'}}
