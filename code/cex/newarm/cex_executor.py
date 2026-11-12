"""Certified compiled executor for the nonnegative bucket-contraction / all-singleton-reverse plan (certified executor pass, 11 Nov 2026) -- v1.4 (v1.2 repaired
after the adversarial review of 11 Nov 2026 (checked arithmetic by operand provenance, checked integer dimensions, one native allocation boundary, typed
conversion stops with exact power-of-two source scaling, deadline at entry / phase boundaries / return, measured host-side memory).

Boundary (prompt section 5A): the executor receives an IMMUTABLE VALIDATED PLAN -- the evidence-restricted component model (exact nonnegative rational factor
occurrences, scope/axis order preserved, no deduplication), the selected elimination order over its unobserved variables, and the requested output = every
singleton row of the component's variables. It binds the plan (sha256 of the lowered SEMANTIC plan: cards, evidence, order, factor scopes and EXACT values --
independent of any representation choice) and separately records the PHYSICAL schedule (dense / sparse representation and power-of-two scale per source, fill
threshold, kernel source). Supports are not trusted metadata: the kernel derives them from the exact zeros of the converted values.

Arithmetic contract (prompt section 6; proof-to-code map in PROOF_TO_CODE.md): binary64 round-to-nearest, u = 2^-53, with the reciprocal envelope label
a^E x <= xhat <= a^-E x (a = 1-u) maintained by the kernel per message / context / numerator (max over entries): source conversion E = 0 if exact else 1;
mul E1+E2+1; add max+1; sequential accumulation of m terms +(m-1); exact power-of-two rescaling +0 (round trip checked). The kernel's only arithmetic
primitives decide from the OPERANDS: a product of two nonzero operands must be a normal finite double (else typed RANGE); an exact zero arises only from an
exact zero operand. The final probability p = N_x / Z is formed EXACTLY in Python from the kernel's doubles and binary exponents, then widened by
K = E_N + E_Z: with delta = K u < 1/2, [p(1-delta), p/(1-delta)] contains the true value (Bernoulli), intersected with [0,1]. A zero numerator is accepted as
exact zero mass ONLY because the kernel's primitives make every stored zero an exact zero (enforced, not assumed).
Source scaling: each source factor is scaled EXACTLY in rational arithmetic by a power of two so that its maximum entry lies in [1, 2) before conversion
(the scale travels with the plan as the source's binary exponent); a positive entry whose scaled value is below 2*DBL_MIN is a typed RANGE stop (never a
zero); conversion therefore never overflows, and OverflowError in float() is nevertheless mapped to the typed RANGE stop (precisely that exception only).
Typed stops: DEADLINE, MEMORY, RANGE, BADPLAN (invalid plan), FPENV, FAULT, ZERO_EVIDENCE, REPRESENTATION (a mixed-radix volume this kernel cannot address
with 64-bit keys: a resource / representation refusal, NEVER a zero-evidence claim), WIDTH (enclosure wider than 1/100).

Memory (v1.4 contract, stated precisely): the kernel charges EVERY native heap allocation (exact requested bytes, transient growth overlap included)
against its cap BEFORE allocating and refuses with a typed MEMORY stop; `peak_logical_bytes` is the peak of all live kernel heap bytes. The HOST side runs a
`HostBudget` that charges a documented upper bound of every host construction BEFORE it is built -- the serialized value strings of the semantic hash (streamed
in fixed-size blocks, never a whole-model text copy), each converted value, the plan-word / value lists, the ctypes arrays, each enclosure row -- and raises
a typed MEMORY stop when the running total would exceed cap - host_reserved_bytes. Not covered (and not claimed): CPython interpreter internals outside the
counted objects, the C allocator's bookkeeping, and the process RSS high-water mark; these are REPORTED (rss growth per phase) and remain the business of the
worker policy (the harness's sampled process-tree RSS kill), which is the ONLY whole-worker bound. Deadline: checked at entry, after lowering, before the
kernel, during the enclosure, and before EVERY terminal return (CERTIFIED and ZERO_EVIDENCE alike); lowering polls the deadline every 256 entries and once per hash block."""
import ctypes as C, hashlib, json, math, os, resource, subprocess, sys, threading, time
from fractions import Fraction as F
from itertools import product
from pathlib import Path

BASE = Path(__file__).resolve().parent; SRC = BASE / 'cex_kernel.cpp'; LIB = BASE / 'libcex_kernel.dylib'; RECORD = BASE / 'cex_build.json'
FLAGS = ['-std=c++17', '-O2', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', '-fPIC', '-shared']
U = F(1, 2 ** 53); A = 1 - U; PLAN_FORMAT = 2
STOPS = {0: 'OK', 1: 'DEADLINE', 2: 'MEMORY', 3: 'RANGE', 4: 'BADPLAN', 5: 'FPENV', 6: 'FAULT', 7: 'ZERO_EVIDENCE', 8: 'REPRESENTATION'}
COUNTERS = ('forward_rows', 'reverse_rows', 'multiplications', 'additions', 'join_index_rows', 'join_probes', 'join_rows_generated', 'dense_rows', 'sparse_rows', 'rescale_entries', 'polls', 'messages_entries', 'contexts_entries', 'max_label', 'buckets_dense', 'buckets_sparse', 'source_values_converted', 'peak_logical_bytes', 'logical_bytes_at_exit', 'peak_join_rows', 'max_live_message_entries', 'allocations')
NUMERICAL_STOPS = ('RANGE', 'WIDTH', 'FPENV')            # the caller may run the exact reference on the same plan after these
RESOURCE_STOPS = ('DEADLINE', 'MEMORY', 'REPRESENTATION')  # final for this attempt


class Stop(Exception):
    def __init__(self, kind, reason, stats):
        super().__init__('%s: %s' % (kind, reason)); self.kind = kind; self.reason = reason; self.stats = dict(stats)


def build(deadline=None):
    """compile once per (source, flags, compiler); the record pins compiler, flags, source and binary hashes; a stale record triggers a rebuild (charged inside the attempt)"""
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
        prev = {'source_sha256': sh, 'binary_sha256': hashlib.sha256(LIB.read_bytes()).hexdigest(), 'flags': FLAGS, 'compiler': cxx, 'compiler_version': ver, 'build_wall_s': time.monotonic() - t, 'platform': sys.platform, 'built_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'plan_format': PLAN_FORMAT}
        RECORD.write_text(json.dumps(prev, indent=1) + '\n')
    return prev


_LIBS = {}; _KERNEL_LOCK = threading.Lock()      # one kernel invocation at a time in this process (ctypes releases the GIL; the kernel's own busy flag is defense in depth)
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


def rss_bytes():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; return r if sys.platform == 'darwin' else r * 1024


def counted_bytes(*lists):
    """exact CPython size of the given lists and of every element object (sys.getsizeof; shared small ints are counted conservatively)"""
    return sum(sys.getsizeof(l) + sum(sys.getsizeof(x) for x in l) for l in lists)


class HostBudget:
    """charge-before-build accounting of host-side construction bytes: every charge is a documented UPPER BOUND on the CPython object about to be created
    (sys.getsizeof of the finished object, or a closed-form bound before it exists); exceeding the budget is a typed MEMORY stop BEFORE the object is built."""
    def __init__(self, budget, stats):
        self.budget = int(budget); self.live = 0; self.peak = 0; self.stats = stats
    def charge(self, nbytes, what):
        nbytes = int(nbytes)
        if self.live + nbytes > self.budget:
            self.stats['host_budget_live_bytes'] = self.live; self.stats['host_budget_refused_bytes'] = nbytes; self.stats['host_budget_peak_bytes'] = self.peak
            raise Stop('MEMORY', 'host budget: %d live + %d requested for %s exceeds %d' % (self.live, nbytes, what, self.budget), self.stats)
        self.live += nbytes; self.peak = max(self.peak, self.live); return nbytes
    def release(self, nbytes): self.live = max(0, self.live - int(nbytes))
    def report(self): self.stats['host_budget_peak_bytes'] = self.peak; self.stats['host_budget_live_bytes'] = self.live; self.stats['host_budget_bytes'] = self.budget


def int_str_bytes_bound(x):
    """upper bound on sys.getsizeof(str(x)) for a Python int without building the string: digits <= bit_length * log10(2) + 1, plus the str header (49) and NUL"""
    return 49 + 2 + (x.bit_length() * 30103) // 100000 + 1


def frac_str_bytes_bound(q):
    return int_str_bytes_bound(q.numerator) + (0 if q.denominator == 1 else 1 + int_str_bytes_bound(q.denominator))


HASH_BLOCK = 1 << 16
def floor_log2(q):
    """exact floor(log2 q) for a positive rational"""
    e = q.numerator.bit_length() - q.denominator.bit_length()
    if F(2) ** e > q: e -= 1
    assert F(2) ** e <= q < F(2) ** (e + 1)
    return e


def convert(q, shift):
    """nearest binary64 of the EXACTLY scaled positive rational q * 2^shift with its label (0 exact, 1 one rounding); the relative bound is CHECKED exactly.
    Raises the typed RANGE stop for a positive value whose scaled double would not be a normal double (never a zero witness) and for a float() OverflowError."""
    if q == 0: return 0.0, 0
    qs = q * F(2) ** shift
    try: x = float(qs)
    except OverflowError: raise Stop('RANGE', 'source conversion overflow after exact scaling (value %s * 2^%d)' % (float(q) if q.denominator.bit_length() < 1000 and q.numerator.bit_length() < 1000 else 'huge', shift), {})
    if not math.isfinite(x) or x < 2 * sys.float_info.min or x > sys.float_info.max / 2: raise Stop('RANGE', 'source conversion out of the supported binary64 range after exact scaling (the dynamic range inside one factor exceeds binary64)', {})
    if F(x) == qs: return x, 0
    if not (A * qs <= F(x) <= qs / A): raise AssertionError('source conversion violates the one-rounding envelope')
    return x, 1


def lower(model, order, dense_fill_threshold=0.25, deadline=None, budget=None):
    """validate + lower the semantic plan: evidence restriction, scalar cancellation, exact power-of-two scaling per source, exact values -> doubles with labels,
    dense / sparse per source. Returns (plan_words, values, meta). meta carries the semantic plan hash (independent of representation and scaling) and the
    physical schedule hash (representation modes, scales, fill threshold, kernel source). The semantic hash is fed in FIXED-SIZE BLOCKS (the byte stream is
    exactly json.dumps([scope, [str(v) for v in data]]) per factor, verified by control), so no whole-model text copy is ever built; every host object the
    lowering retains or holds transiently (restricted-value lists, value strings per block, converted doubles, plan words) is charged to `budget` BEFORE it is
    built (typed MEMORY stop); the deadline is polled every 256 entries and once per hash block."""
    cards = list(model['cards']); n = len(cards); ev = dict(model.get('evidence', {}))
    if any(type(c) is not int or c < 1 for c in cards): raise ValueError('invalid cardinality')
    if any(type(v) is not int or not 0 <= v < n or type(a) is not int or not 0 <= a < cards[v] for v, a in ev.items()): raise ValueError('invalid evidence')
    active = [v for v in range(n) if v not in ev]
    if sorted(order) != active: raise ValueError('order must cover the unobserved variables exactly')
    B = budget or HostBudget(1 << 62, {})
    sem = hashlib.sha256(); sem.update(json.dumps({'cards': cards, 'evidence': sorted(ev.items()), 'order': list(order)}).encode())
    srcs = []; stats = {'source_entries_read': 0, 'source_positive_rows': 0, 'scalar_factors_cancelled': 0, 'sources_dense': 0, 'sources_sparse': 0, 'conversion_exact': 0, 'conversion_rounded': 0, 'source_scale_shifts': [], 'hash_blocks': 0}
    korder = list(order) + [v for v in range(n) if v in ev]; words = [PLAN_FORMAT, n] + cards + [n] + korder; B.charge(counted_bytes(words), 'plan header words'); charged_srcs = 0
    def tick(force=False):
        if deadline is not None and (force or stats['source_entries_read'] % 256 == 0) and time.monotonic() >= deadline: raise Stop('DEADLINE', 'lowering deadline', stats)
    for f in model['factors']:
        sc = tuple(f['scope']); v_ = f['values']
        if len(sc) != len(set(sc)) or any(type(v) is not int or not 0 <= v < n for v in sc): raise ValueError('invalid factor scope')
        if len(v_) != math.prod(cards[v] for v in sc): raise ValueError('factor shape mismatch')
        keep = [i for i, v in enumerate(sc) if v not in ev]; newsc = tuple(sc[i] for i in keep); vol = math.prod(cards[v] for v in newsc)
        if vol > 2 ** 62: raise Stop('REPRESENTATION', 'a source factor volume above 2^62 is not addressable by this kernel (64-bit keys): typed representation refusal, not a zero-evidence claim', stats)
        data_charge = B.charge(56 + 8 * vol, 'restricted value list (%d slots)' % vol); data = []       # the list of references to the caller's (shared) Fraction objects
        for a, w in zip(product(*(range(cards[v]) for v in sc)), v_):
            stats['source_entries_read'] += 1
            if not isinstance(w, F): w = F(w)
            if w < 0: raise ValueError('negative factor entry')
            if all(a[i] == ev[v] for i, v in enumerate(sc) if v in ev): data.append(w)
            tick()
        # ---- streamed semantic hash: byte stream == json.dumps([list(newsc), [str(x) for x in data]]) without materializing it; value strings are built per BLOCK (charged, then released)
        sem.update(b'[' + json.dumps(list(newsc)).encode() + b', ['); block = []; block_bytes = 0; block_charge = 0; first = True
        for x in data:
            bnd = frac_str_bytes_bound(x) + 3
            if block_bytes + bnd > HASH_BLOCK and block:
                sem.update(b''.join(block)); stats['hash_blocks'] += 1; B.release(block_charge); block = []; block_bytes = 0; block_charge = 0; tick(True)
            block_charge += B.charge(bnd, 'hash block value string'); block_bytes += bnd; block.append((b'' if first else b', ') + b'"' + str(x).encode() + b'"'); first = False
        sem.update(b''.join(block) + b']]'); stats['hash_blocks'] += 1; B.release(block_charge)
        nz = sum(1 for w in data if w != 0); stats['source_positive_rows'] += nz
        if not newsc:
            if data[0] == 0: B.release(data_charge); return None, None, dict(stats, zero_evidence=True)
            stats['scalar_factors_cancelled'] += 1; B.release(data_charge); continue
        if nz == 0: B.release(data_charge); return None, None, dict(stats, zero_evidence=True)
        shift = -floor_log2(max(data)); stats['source_scale_shifts'].append(shift)        # exact: max(data) * 2^shift in [1, 2)
        dense = nz >= dense_fill_threshold * vol; lab = 0
        if dense:
            stats['sources_dense'] += 1; B.charge(56 + 32 * vol, 'converted dense values (%d doubles)' % vol); dv = []
            for w in data:
                x, l = convert(w, shift); dv.append(x); lab = max(lab, l); stats['conversion_exact' if l == 0 else 'conversion_rounded'] += 1
            srcs.append((newsc, 0, None, dv, lab, -shift))
        else:
            stats['sources_sparse'] += 1; B.charge(2 * (56 + 36 * nz), 'converted sparse keys + values (%d)' % nz); keys = []; dv = []
            for k, w in enumerate(data):
                if w != 0:
                    x, l = convert(w, shift); keys.append(k); dv.append(x); lab = max(lab, l); stats['conversion_exact' if l == 0 else 'conversion_rounded'] += 1
            srcs.append((newsc, 1, keys, dv, lab, -shift))
        B.release(data_charge)                                                                   # the restricted-value list dies with the factor
    nw = sum(4 + len(sc) + (len(keys) if mode == 1 else 0) for sc, mode, keys, dv, lab, e in srcs) + 1; nv = sum(len(dv) for s_ in srcs for dv in [s_[3]])
    plan_lists_charge = B.charge(56 + 36 * nw + 56 + 32 * nv, 'plan words (%d) + value list (%d)' % (nw, nv))
    words.append(len(srcs)); vals = []
    for sc, mode, keys, dv, lab, exp2 in srcs:
        words += [len(sc)] + list(sc) + [mode, len(dv)]
        if mode == 1: words += keys
        words += [lab, exp2]; vals += dv
    phys = hashlib.sha256(json.dumps({'plan_format': PLAN_FORMAT, 'dense_fill_threshold': dense_fill_threshold, 'modes': [s_[1] for s_ in srcs], 'scales': [s_[5] for s_ in srcs], 'kernel': hashlib.sha256(SRC.read_bytes()).hexdigest()}).encode()).hexdigest()
    stats['source_scale_shifts'] = (min(stats['source_scale_shifts']), max(stats['source_scale_shifts'])) if stats['source_scale_shifts'] else None
    return words, vals, dict(stats, semantic_plan_sha256=sem.hexdigest(), physical_schedule_sha256=phys, n=n, active=active, evidence=ev, cards=cards, plan_lists_charge=plan_lists_charge)


def enclose(Nvals, Nexp, Nlab, Zval, Zexp, Zlab, cards, ev, stats, deadline=None, budget=None):
    """exact enclosure from the kernel's doubles, binary exponents and labels: p = N_x 2^e / (Z 2^e') as a Fraction; K = E_N + E_Z; delta = K u (< 1/2 required,
    else typed RANGE); [p(1-delta), p/(1-delta)] intersected with [0,1] (Bernoulli); an exactly zero numerator is exact zero mass because the kernel's primitives make
    every stored zero an exact zero (operand provenance). Returns (intervals, points, maxK, maxw). Unit-testable (label overflow control)."""
    n = len(cards); B = budget or HostBudget(1 << 62, {}); zv = F(Zval) * F(2) ** int(Zexp); zlab = int(Zlab); B.charge(2 * (128 + 32 * ((zv.numerator.bit_length() + 63) // 64 + (zv.denominator.bit_length() + 63) // 64)), 'Z as a Fraction')
    if zv <= 0: raise Stop('RANGE', 'nonpositive Z', stats)
    intervals = []; points = []; off = 0; maxK = 0; maxw = F(0); zbits = zv.numerator.bit_length() + zv.denominator.bit_length()
    for v in range(n):
        c = cards[v]; bits = zbits + abs(int(Nexp[v])) + 53 + 2 * 54 + 64     # bound BEFORE reduction: p = N 2^e / Z has <= zbits + |e| + 53 bits over numerator + denominator; times (1-delta) or 1/(1-delta) (K/2^53, 54 bits each) adds <= 108; slack 64
        fb = 128 + 32 * ((bits + 63) // 64 + 1)                             # Fraction proxy (memory.py): 128 B + 32 B per 64-bit limb of numerator and denominator
        B.charge(c * 3 * fb + 4 * fb + 2 * (56 + 8 * c), 'enclosure row %d (%d states: three Fractions per state + four row temporaries of <= %d bits)' % (v, c, bits))
        if v in ev:
            row = [(F(int(a == ev[v])), F(int(a == ev[v]))) for a in range(c)]; pts = [F(int(a == ev[v])) for a in range(c)]
        else:
            K = int(Nlab[v]) + zlab; maxK = max(maxK, K); delta = K * U
            if delta >= F(1, 2): raise Stop('RANGE', 'error label too large for a certified enclosure (K=%d)' % K, stats)
            lo_f = 1 - delta; hi_f = 1 / (1 - delta); row = []
            for a in range(c):
                r = F(Nvals[off + a]) * F(2) ** int(Nexp[v]) / zv
                if r == 0: row.append((F(0), F(0)))          # exact zero mass (enforced by the kernel's operand-provenance primitives, not assumed)
                else: row.append((max(F(0), r * lo_f), min(F(1), r * hi_f)))
            s_lo = sum(x for x, _ in row); s_hi = sum(y for _, y in row)
            if s_lo > 1 or s_hi < 1: raise AssertionError('enclosure box excludes the simplex (row %d)' % v)
            pts = [lo for lo, _ in row]; left = 1 - sum(pts)
            for a in range(c):
                take = min(left, row[a][1] - pts[a]); pts[a] += take; left -= take
            if left != 0: raise AssertionError('simplex point allocation failed')
            for (lo, hi), p in zip(row, pts): maxw = max(maxw, hi - lo)
        intervals.append(row); points.append(pts); off += c
        if deadline is not None and v % 256 == 255 and time.monotonic() >= deadline: raise Stop('DEADLINE', 'deadline expired during enclosure construction', stats)
    for row, pts in zip(intervals, points):
        if sum(pts) != 1 or any(not (0 <= lo <= p <= hi <= 1) for (lo, hi), p in zip(row, pts)): raise AssertionError('publication invariant')
    return intervals, points, maxK, maxw


def execute(model, order, deadline=None, cap_bytes=3 * 1024 ** 3, dense_fill_threshold=0.25, host_reserved_bytes=0):
    """run the validated plan; returns dict(status, intervals, points, stats, certificate) or raises Stop (typed) / ValueError (invalid plan)"""
    t0 = time.monotonic(); stats = {'phase': 'build'}
    def terminal_deadline(where):
        if deadline is not None and time.monotonic() >= deadline: raise Stop('DEADLINE', 'deadline expired %s' % where, stats)
    terminal_deadline('at executor entry')
    prov = build(deadline); lib = load(prov); stats['build_s'] = time.monotonic() - t0; stats['phase'] = 'lowering'; t = time.monotonic(); rss0 = rss_bytes()
    host_budget_bytes = cap_bytes - host_reserved_bytes
    if host_budget_bytes <= 0: raise Stop('MEMORY', 'host RSS at entry (%d) leaves no capacity under cap %d' % (host_reserved_bytes, cap_bytes), stats)
    B = HostBudget(host_budget_bytes, stats)
    words, vals, meta = lower(model, order, dense_fill_threshold, deadline, budget=B)
    stats['host_lowering_rss_growth_bytes_measured'] = max(0, rss_bytes() - rss0); stats['host_lowering_retained_bytes_counted'] = counted_bytes(words or [], vals or [])
    stats.update({k: v for k, v in meta.items() if k not in ('active', 'evidence', 'cards', 'plan_lists_charge')}); stats['lowering_s'] = time.monotonic() - t; B.report()
    if meta.get('zero_evidence'):
        terminal_deadline('before the ZERO_EVIDENCE return'); return {'status': 'ZERO_EVIDENCE', 'intervals': None, 'stats': stats}
    n = meta['n']; cards = meta['cards']; ev = meta['evidence']; tot = sum(cards)
    arrays_bytes = len(words) * 8 + max(1, len(vals)) * 8 + tot * 8 + n * 16 + 8 + 16 + len(COUNTERS) * 8 + 256
    stats['host_plan_output_arrays_bytes'] = arrays_bytes; B.charge(arrays_bytes, 'ctypes plan / output arrays')
    stats['host_budget_live_at_kernel_call_bytes'] = B.live; kcap = host_budget_bytes - B.live
    if kcap <= 0: raise Stop('MEMORY', 'host-side charges (%d live under budget %d) leave no kernel capacity' % (B.live, host_budget_bytes), stats)
    stats['kernel_cap_bytes'] = kcap; stats['phase'] = 'kernel'; t = time.monotonic(); terminal_deadline('after lowering')
    W = (C.c_int64 * len(words))(*words); V = (C.c_double * max(1, len(vals)))(*vals)
    N = (C.c_double * tot)(); NE = (C.c_int64 * n)(); NL = (C.c_int64 * n)(); Z = (C.c_double * 1)(); ZM = (C.c_int64 * 2)(); CT = (C.c_uint64 * len(COUNTERS))(); RS = C.create_string_buffer(256)
    with _KERNEL_LOCK:
        rc = lib.cex_run(W, len(words), V, len(vals), kcap, float('inf') if deadline is None else deadline, dense_fill_threshold, N, NE, NL, Z, ZM, CT, len(COUNTERS), RS, 256)
    stats['kernel_s'] = time.monotonic() - t; stats['counters'] = {k: int(CT[i]) for i, k in enumerate(COUNTERS)}; stats['kernel_status'] = STOPS.get(rc, 'UNKNOWN_%d' % rc); stats['kernel_reason'] = RS.value.decode(errors='replace')
    if rc == 7: terminal_deadline('before the ZERO_EVIDENCE return'); B.report(); return {'status': 'ZERO_EVIDENCE', 'intervals': None, 'stats': stats}
    if rc != 0: B.report(); raise Stop(STOPS.get(rc, 'FAULT'), stats['kernel_reason'], stats)
    B.release(len(words) * 8 + max(1, len(vals)) * 8); B.release(meta['plan_lists_charge']); del W, V, words, vals      # the plan is consumed: its word / value lists and input arrays are released before the enclosure
    # ---- exact enclosure from the kernel's doubles + labels, every row charged to the host budget BEFORE it is built; RSS growth reported
    stats['phase'] = 'enclosure'; t = time.monotonic(); rss1 = rss_bytes()
    try:
        intervals, points, maxK, maxw = enclose([N[i] for i in range(tot)], [int(x) for x in NE], [int(x) for x in NL], Z[0], int(ZM[0]), int(ZM[1]), cards, ev, stats, deadline, budget=B)
    finally:
        stats['host_enclosure_rss_growth_bytes_measured'] = max(0, rss_bytes() - rss1); B.report()
    stats['enclosure_s'] = time.monotonic() - t; stats['max_label_K'] = maxK; stats['max_width'] = str(maxw); stats['max_width_float'] = float(maxw); stats['total_s'] = time.monotonic() - t0; stats['phase'] = 'complete'
    if maxw > F(1, 100): raise Stop('WIDTH', 'delivered width %s exceeds 1/100 (precision insufficient; retry or exact fallback required)' % float(maxw), stats)
    terminal_deadline('before the CERTIFIED return')
    return {'status': 'CERTIFIED', 'intervals': intervals, 'points': points, 'stats': stats,
            'certificate': {'method': 'compiled_nonnegative_bucket_contraction_all_singleton_reverse', 'arithmetic': 'binary64 nearest with reciprocal-envelope labels (u=2^-53); every product checked by operand provenance; exact N/Z in Python; Bernoulli widening by K=E_N+E_Z', 'memory_contract': 'kernel heap charged before allocation (hard); host constructions charged before build against cap - entry RSS (documented upper bounds; interpreter internals and RSS excluded); whole-worker bound = the harness sampled-RSS policy', 'order': list(order), 'semantic_plan_sha256': meta['semantic_plan_sha256'], 'physical_schedule_sha256': meta['physical_schedule_sha256'], 'kernel': {k: prov.get(k) for k in ('source_sha256', 'binary_sha256', 'compiler', 'compiler_version', 'flags', 'schedule_id', 'plan_format')}, 'max_label_K': maxK, 'convention': 'unnormalized adjoints (zero-safe prefix/suffix exclusion products, no division); final exact N/Z'}}
