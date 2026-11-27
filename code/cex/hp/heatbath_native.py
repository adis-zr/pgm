"""DGP8 SPECTRAL_HEATBATH, part 2c (DGP9 REPAIRED): the ctypes host of the native exact-decision heat-bath kernel (heatbath_native.c). `build()` compiles once per (source, flags, compiler) with a pinned record (heatbath_build.json:
source / binary sha256, flags, compiler version) UNDER THE CALLER'S CLOCK (compiler timeout = the remaining allowance; review RV6). `NativeChain` owns one kernel context: the model's unary / pair tables as binary64, the state, the
step counter and the occupation bookkeeping live in the kernel; `run(steps)` executes a batch and, when the kernel reports an UNRESOLVED decision, resolves it EXACTLY (heatbath_exact.decide_exact on the same 53-bit prefix plus
refinement bits from a separate seeded Python bit source -- conditional on the prefix the remaining bits are independent uniform bits, so any independent source keeps U exactly uniform; the fallback is POLLED and its integer
temporaries are ADMITTED before construction) and applies it through hb_apply, then continues.

DGP9 repair of the review's RV1 (native arithmetic range): (1) every unary / pair table is divided by an EXACT power of two 2^s_f chosen so that its maximum entry lies in [1/2, 1) -- a positive constant per factor cancels in EVERY
conditional of EVERY site (and in the target up to the normalizer), so the sampled law is unchanged; the stored doubles are the nearest binary64 of the SCALED exact rationals (relative conversion error <= u as before; every
stored value <= 1, so no multiplication can overflow and prefix products are nonincreasing); (2) an ALL-ASSIGNMENT RANGE WITNESS is computed exactly in rationals from the per-table maxima / minima ONLY (no scaled table is
materialized before admission): for every variable i the smallest conditional weight over every assignment of the other variables is bounded below by psi'_i,min x prod_{f incident} min_f'; the kernel is admitted only when that
bound is >= 2^RANGE_FLOOR_LOG2 = 2^-900 for every variable -- then every exact weight, every multiplication prefix, every cumulative sum (>= the first weight, <= k) and every threshold product (>= 2^-53 x 2^-900 unless the uniform
prefix is exactly 0, which is exact) lies in the NORMAL binary64 range with margin, so the kernel's relative error model (2 m + 4) u holds for every operation and no information is lost to the subnormal range; otherwise the native
route is REFUSED typed (NATIVE_RANGE) before any state is committed and the runner uses the exact-rational chain (heatbath_exact.ExactChain) as the checked fallback. (3) Construction is CHARGED before staging: the witness's own
small temporaries, then the kernel heap (incl. the (n + 1)-int incidence-start array the DGP8 counter omitted) and the ctypes staging copies are admitted before any array is built; the staging charge is released after hb_create.
(4) The native site-rejection loop is BOUNDED: after REJECT_CAP rejections inside one batch the kernel returns to the host, which polls the clock. Counters: resolved / unresolved (exact fallbacks) / null moves / site rejections /
poll returns."""
import os, sys, json, time, hashlib, subprocess, ctypes, random, math
from fractions import Fraction as F
import coarse_envelope as CE
import heatbath_exact as HX
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, 'heatbath_native.c'); RECORD = os.path.join(HERE, 'heatbath_build.json')
FLAGS = ['-std=c11', '-O2', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', '-fPIC', '-shared']
RANGE_FLOOR_LOG2 = -900; REJECT_CAP = 1 << 16; FALLBACK_POLL_BITS = 64; STAGING_OVERHEAD = 4096
PROFILE = dict(normalization='every table divided by the exact power of two 2^s with max entry / 2^s in [1/2, 1): law-preserving, stored doubles <= 1 (converted on the fly after admission)', range_floor_log2=RANGE_FLOOR_LOG2, range_witness='exact rational all-assignment lower bound psi_min x prod min_f per variable >= 2^-900 from per-table maxima / minima only, else typed NATIVE_RANGE refusal before any commit',
               error_model='(2 m + 4) u relative per weight on normal binary64 values; thresholds (1 +- 2 u); CDF (1 +- (a + 2) u)', reject_cap=REJECT_CAP, fallback='heatbath_exact.decide_exact on the same 53-bit prefix, polled every %d refinement bits, integer temporaries admitted first' % FALLBACK_POLL_BITS, build='compiled under the caller clock (compiler timeout = remaining allowance)')
_LIB = None


class RefusedNative(CE.Refused):
    pass


def _sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def build(clock=None):
    """compile the kernel into a content-addressed dylib under native_cache/; the record pins compiler, flags, source and binary hashes (a stale record triggers a rebuild). The compiler runs with a timeout equal to the caller's
    remaining allowance (a timeout is a typed DEADLINE refusal); the clock is polled before compiling."""
    global _LIB
    cc = os.environ.get('CC', 'clang'); sh = _sha(SRC); cache = os.path.join(HERE, 'native_cache'); os.makedirs(cache, exist_ok=True); digest = hashlib.sha256((sh + json.dumps(FLAGS) + cc).encode()).hexdigest()[:16]; lib = os.path.join(cache, 'heatbath_%s.dylib' % digest)
    prev = json.load(open(RECORD)) if os.path.exists(RECORD) else {}
    if not os.path.exists(lib) or prev.get('source_sha256') != sh or prev.get('flags') != FLAGS or prev.get('compiler') != cc or (os.path.exists(lib) and prev.get('binary_sha256') != _sha(lib)):
        if clock is not None: clock.poll('native build entry')
        timeout = max(1.0, clock.remaining()) if clock is not None else 600.0; t = time.monotonic()
        try: subprocess.check_call([cc] + FLAGS + ['-o', lib, SRC], timeout=timeout)
        except subprocess.TimeoutExpired: raise CE.Refused('DEADLINE', 'native build exceeded the remaining allowance (%.1f s)' % timeout)
        ver = subprocess.check_output([cc, '--version'], timeout=30).decode().split('\n')[0]
        prev = dict(source_sha256=sh, binary_sha256=_sha(lib), flags=FLAGS, compiler=cc, compiler_version=ver, build_wall_s=time.monotonic() - t, platform=sys.platform, built_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), library=os.path.basename(lib), rng='xoshiro256** seeded by splitmix64 from the 64-bit sample seed', decision='outward binary64 weight / CDF intervals on power-of-two normalized tables inside a proved normal range, 53-bit uniform prefix, exact fallback on the same bit stream', range_floor_log2=RANGE_FLOOR_LOG2)
        json.dump(prev, open(RECORD, 'w'), indent=1)
    if _LIB is None or getattr(_LIB, '_path', None) != lib:
        L = ctypes.CDLL(lib); L._path = lib
        L.hb_create.restype = ctypes.c_void_p; L.hb_create.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_longlong), ctypes.c_uint64]
        L.hb_free.argtypes = [ctypes.c_void_p]; L.hb_set_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]; L.hb_get_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        L.hb_steps.restype = ctypes.c_longlong; L.hb_steps.argtypes = [ctypes.c_void_p]; L.hb_counters.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]; L.hb_set_recording.argtypes = [ctypes.c_void_p]; L.hb_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
        L.hb_unresolved.restype = ctypes.c_int; L.hb_unresolved.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]; L.hb_bytes.restype = ctypes.c_size_t; L.hb_bytes.argtypes = [ctypes.c_void_p]; L.hb_apply.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.hb_run.restype = ctypes.c_longlong; L.hb_run.argtypes = [ctypes.c_void_p, ctypes.c_longlong]; L.hb_inspect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        L.hb_take_poll_request.restype = ctypes.c_int; L.hb_take_poll_request.argtypes = [ctypes.c_void_p]
        _LIB = L
    return _LIB, dict(prev)


def kernel_bytes_estimate(hbm):
    """the kernel's heap (hb_bytes) before creation: tables + incidence (incl. the (n + 1) incidence-start ints) + state / occupation / timestamps + workspace + the context struct"""
    D = sum(hbm.cards); nf = len(hbm.pairs); nv = sum(ki * kj for (_, _, ki, kj, _) in hbm.pairs); inc = 2 * nf
    return 256 + 4 * (hbm.n * 3 + 1 + nf * 4 + inc * 2 + (hbm.n + 1)) + 8 * (nf + 1 + D + hbm.n) + 8 * (D + nv + 3 * max(hbm.cards)) + 4096


def staging_bytes_estimate(hbm):
    """the ctypes staging copies built by the host before hb_create (released after creation)"""
    D = sum(hbm.cards); nf = len(hbm.pairs); nv = sum(ki * kj for (_, _, ki, kj, _) in hbm.pairs)
    return 8 * (D + nv + nf + 1) + 4 * (hbm.n * 2 + 2 * max(1, nf)) + 32 * (D + nv) + STAGING_OVERHEAD                  # the Python float objects of the conversion lists (~32 B each) dominate


def witness_bytes_estimate(hbm): return 160 * 2 * (hbm.n + len(hbm.pairs)) + 64 * hbm.n + 4096                           # the per-table max / min Fractions and the scale lists of the range witness (admitted BEFORE they are computed)


def _pow2(s): return (F(2) ** s) if s >= 0 else F(1) / (F(2) ** (-s))


def _pow2_scale(xmax):
    """the exact power of two 2^s with xmax / 2^s in [1/2, 1) for a positive rational xmax -> s"""
    s = xmax.numerator.bit_length() - xmax.denominator.bit_length()
    if xmax / _pow2(s) >= 1: s += 1
    return s


def range_witness(hbm):
    """-> dict(scales=dict(unary=[s_i], pair=[s_f]), range=dict(...)) WITHOUT materializing any scaled table: per table only its exact max (-> the power-of-two scale with max / 2^s in [1/2, 1)) and its exact min; the
    all-assignment range witness per variable: lower bound on every conditional weight = (psi_min / 2^s_i) x prod_f (min_f / 2^s_f); upper bound < 1 by construction; admitted iff min_i lower_i >= 2^RANGE_FLOOR_LOG2"""
    su = []; umin = []
    for row in hbm.psi: m = max(row); s = _pow2_scale(m); su.append(s); umin.append(min(row) / _pow2(s))
    sp = []; pmin = []
    for (i, j, ki, kj, vals) in hbm.pairs: m = max(vals); s = _pow2_scale(m); sp.append(s); pmin.append(min(vals) / _pow2(s))
    floor = _pow2(RANGE_FLOOR_LOG2); worst = None; per_var = []
    for i in range(hbm.n):
        lo = umin[i]
        for fi, role in hbm.incident[i]: lo *= pmin[fi]
        per_var.append(lo)
        if worst is None or lo < worst: worst = lo
    def l2(x):
        if x <= 0: return -math.inf
        e = x.numerator.bit_length() - x.denominator.bit_length(); return e + math.log2(float(x / _pow2(e)))          # exact exponent + a float mantissa log (reporting only)
    rng = dict(floor_log2=RANGE_FLOOR_LOG2, min_weight_log2_lower=(l2(worst) if worst is not None else None), max_weight_log2_upper=0.0, admitted=bool(worst is not None and worst >= floor), per_variable_min_log2=[round(l2(x), 3) for x in per_var[:64]], n_variables=hbm.n,
               rule='every scaled entry < 1 (no overflow; prefix products nonincreasing); min over variables of psi_min x prod min_f >= 2^%d (exact rational comparison) -> every weight, prefix, cumulative sum and nonzero threshold product normal' % RANGE_FLOOR_LOG2)
    return dict(scales=dict(unary=su, pair=sp), range=rng)


def normalize_tables(hbm):
    """materialized scaled tables (CONTROLS / references only -- the chain converts on the fly after admission): every table divided by its exact power-of-two scale"""
    w = range_witness(hbm); psi = [[v / _pow2(s) for v in row] for row, s in zip(hbm.psi, w['scales']['unary'])]; pairs = [[v / _pow2(s) for v in p[4]] for p, s in zip(hbm.pairs, w['scales']['pair'])]
    return dict(psi=psi, pairs=pairs, scales=w['scales'], range=w['range'])


class NativeChain:
    def __init__(self, hbm, x0, seed, clock, budget=None, refine_seed=None):
        self.m = hbm; self.clock = clock; self.budget = budget; self.owned = 0; self.staging_owned = 0; n = hbm.n
        clock.poll('native chain construction entry')
        # 1. the range witness's own small temporaries are admitted FIRST, then the witness is computed from per-table extrema (no scaled table materialized)
        wb = witness_bytes_estimate(hbm); wit_owned = budget.charge(wb, 'heat-bath native range witness temporaries') if budget is not None else 0
        try: norm = range_witness(hbm); self.range_record = norm['range']; self.scales = norm['scales']
        finally:
            if wit_owned: budget.release(wit_owned)
        if not norm['range']['admitted']: raise RefusedNative('NATIVE_RANGE', 'the native arithmetic range witness fails: the smallest normalized conditional weight over all assignments has log2 %.1f < %d (exact fallback chain required)' % (norm['range']['min_weight_log2_lower'] if norm['range']['min_weight_log2_lower'] is not None else -math.inf, RANGE_FLOOR_LOG2))
        # 2. admission BEFORE staging: the kernel heap + the ctypes staging copies
        self.bytes = kernel_bytes_estimate(hbm); staging = staging_bytes_estimate(hbm)
        if budget is not None: self.owned = budget.charge(self.bytes, 'heat-bath native kernel (%d variables, %d pair factors)' % (n, len(hbm.pairs))); self.staging_owned = budget.charge(staging, 'heat-bath native staging copies')
        try:
            self.lib, self.build_record = build(clock); clock.poll('native chain staging'); su = self.scales['unary']; sp = self.scales['pair']
            cards = (ctypes.c_int * n)(*hbm.cards); D = sum(hbm.cards); psi = (ctypes.c_double * D)(*[float(v / _pow2(su[i])) for i, row in enumerate(hbm.psi) for v in row])
            nf = len(hbm.pairs); fi = (ctypes.c_int * max(1, nf))(*[p[0] for p in hbm.pairs]); fj = (ctypes.c_int * max(1, nf))(*[p[1] for p in hbm.pairs]); offs = [0]
            for p in hbm.pairs: offs.append(offs[-1] + len(p[4]))
            foff = (ctypes.c_longlong * (nf + 1))(*offs); fvals = (ctypes.c_double * max(1, offs[-1]))(*[float(v / _pow2(sp[f])) for f, p in enumerate(hbm.pairs) for v in p[4]])
            self.ctx = self.lib.hb_create(n, cards, psi, nf, fi, fj, fvals, foff, ctypes.c_uint64(int(seed) & ((1 << 64) - 1)))
            if not self.ctx: raise CE.Refused('NATIVE', 'heat-bath kernel creation failed')
            self.lib.hb_set_state(self.ctx, (ctypes.c_int * n)(*[int(v) for v in x0]))
            del cards, psi, fi, fj, foff, fvals
            if self.staging_owned: budget.release(self.staging_owned); self.staging_owned = 0
            actual = int(self.lib.hb_bytes(self.ctx))
            if actual > self.bytes: raise CE.Refused('MEMORY', 'native kernel heap %d B exceeds its admitted estimate %d B' % (actual, self.bytes))
            self.bytes_actual = actual
        except BaseException:
            if getattr(self, 'ctx', None): self.lib.hb_free(self.ctx); self.ctx = None
            if self.staging_owned: budget.release(self.staging_owned); self.staging_owned = 0
            if self.owned: budget.release(self.owned); self.owned = 0
            raise
        self.refine = random.Random(int(refine_seed if refine_seed is not None else (int(seed) ^ 0x5DEECE66D))); self.fallbacks = 0; self.fallback_extra_bits = 0; self.poll_returns = 0; self.seed = int(seed)
    def close(self):
        if getattr(self, 'ctx', None): self.lib.hb_free(self.ctx); self.ctx = None
        if self.staging_owned and self.budget is not None: self.budget.release(self.staging_owned); self.staging_owned = 0
        if self.owned and self.budget is not None: self.budget.release(self.owned); self.owned = 0
    def state(self):
        out = (ctypes.c_int * self.m.n)(); self.lib.hb_get_state(self.ctx, out); return list(out)
    def steps(self): return int(self.lib.hb_steps(self.ctx))
    def counters(self):
        out = (ctypes.c_longlong * 4)(); self.lib.hb_counters(self.ctx, out); return dict(resolved=int(out[0]), unresolved=int(out[1]), null_moves=int(out[2]), site_rejections=int(out[3]), exact_fallbacks=self.fallbacks, fallback_extra_bits=self.fallback_extra_bits, poll_returns=self.poll_returns)
    def set_recording(self): self.lib.hb_set_recording(self.ctx)
    def flush(self):
        D = sum(self.m.cards); out = (ctypes.c_longlong * D)(); self.lib.hb_flush(self.ctx, out); occ = []; k = 0
        for c in self.m.cards: occ.append([int(out[k + a]) for a in range(c)]); k += c
        return occ
    def _resolve(self):
        """the exact fallback of ONE unresolved decision: polled, its integer temporaries admitted first (the common denominator and the integer weights), the SAME 53-bit prefix refined by independent uniform bits"""
        u = ctypes.c_uint64(); i = self.lib.hb_unresolved(self.ctx, ctypes.byref(u))
        if i < 0: return False
        self.clock.poll('heat-bath exact fallback (site %d)' % i); x = self.state(); w = self.m.weights_exact(x, i)
        bits = sum(v.numerator.bit_length() + v.denominator.bit_length() for v in w); est = (bits // 8 + 64) * (len(w) + 3) + 1024; owned = self.budget.charge(est, 'exact fallback integers') if self.budget is not None else 0
        try: a, extra = HX.decide_exact(w, int(u.value), lambda k: self.refine.getrandbits(k) if k else 0, clock=self.clock, poll_every=FALLBACK_POLL_BITS)
        finally:
            if owned: self.budget.release(owned)
        self.fallbacks += 1; self.fallback_extra_bits += extra; self.lib.hb_apply(self.ctx, i, a); return True
    def run(self, steps, batch=200000, tag=''):
        """exactly `steps` completed transitions (batches polled; unresolved decisions resolved exactly in between; a bounded site-rejection return polls the clock); returns the steps done"""
        done = 0
        while done < steps:
            self.clock.poll('heat-bath batch %s (%d / %d)' % (tag, done, steps)); want = min(batch, steps - done); got = int(self.lib.hb_run(self.ctx, want)); done += got
            if got < want:
                if self._resolve(): done += 1
                elif int(self.lib.hb_take_poll_request(self.ctx)): self.poll_returns += 1
        return done
    def inspect(self, i):
        k = self.m.cards[i]; w = (ctypes.c_double * k)(); lo = (ctypes.c_double * k)(); hi = (ctypes.c_double * k)(); self.lib.hb_inspect(self.ctx, i, w, lo, hi); return list(w), list(lo), list(hi)
    def record(self):
        return dict(bytes_admitted=self.bytes, bytes_actual=getattr(self, 'bytes_actual', None), range=self.range_record, scales=dict(unary_distinct=len(set(self.scales['unary'])), pair_distinct=len(set(self.scales['pair'])), unary_min=min(self.scales['unary']), unary_max=max(self.scales['unary']), pair_min=(min(self.scales['pair']) if self.scales['pair'] else None), pair_max=(max(self.scales['pair']) if self.scales['pair'] else None)))
