"""DGP8 SPECTRAL_HEATBATH, part 2c: the ctypes host of the native exact-decision heat-bath kernel (heatbath_native.c). `build()` compiles once per (source, flags, compiler) with a pinned record (heatbath_build.json: source / binary
sha256, flags, compiler version), mirroring cex_executor.build. `NativeChain` owns one kernel context: the model's unary / pair tables as binary64 (nearest conversion of the exact rationals; the kernel's error bound covers it), the
state, the step counter and the occupation bookkeeping live in the kernel; `run(steps)` executes a batch and, when the kernel reports an UNRESOLVED decision, resolves it EXACTLY (heatbath_exact.decide_exact on the same 53-bit prefix
plus refinement bits from a separate seeded Python bit source -- conditional on the prefix the remaining bits are independent uniform bits, so any independent source keeps U exactly uniform) and applies it through hb_apply, then
continues. Batches are the host's polling granularity (the clock is polled between batches; an interrupted batch leaves the last completed state / counters usable). Counters: resolved / unresolved (exact fallbacks) / null moves /
site rejections; bytes = the kernel's own accounting (admitted by the caller before creation)."""
import os, sys, json, time, hashlib, subprocess, ctypes, random
from fractions import Fraction as F
import numpy as np
import coarse_envelope as CE
import heatbath_exact as HX
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, 'heatbath_native.c'); RECORD = os.path.join(HERE, 'heatbath_build.json')
FLAGS = ['-std=c11', '-O2', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', '-fPIC', '-shared']
_LIB = None


def _sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def build(deadline=None):
    """compile the kernel into a content-addressed dylib under native_cache/; the record pins compiler, flags, source and binary hashes (a stale record triggers a rebuild)"""
    global _LIB
    cc = os.environ.get('CC', 'clang'); sh = _sha(SRC); cache = os.path.join(HERE, 'native_cache'); os.makedirs(cache, exist_ok=True); digest = hashlib.sha256((sh + json.dumps(FLAGS) + cc).encode()).hexdigest()[:16]; lib = os.path.join(cache, 'heatbath_%s.dylib' % digest)
    prev = json.load(open(RECORD)) if os.path.exists(RECORD) else {}
    if not os.path.exists(lib) or prev.get('source_sha256') != sh or prev.get('flags') != FLAGS or prev.get('compiler') != cc or (os.path.exists(lib) and prev.get('binary_sha256') != _sha(lib)):
        t = time.monotonic(); subprocess.check_call([cc] + FLAGS + ['-o', lib, SRC]); ver = subprocess.check_output([cc, '--version']).decode().split('\n')[0]
        prev = dict(source_sha256=sh, binary_sha256=_sha(lib), flags=FLAGS, compiler=cc, compiler_version=ver, build_wall_s=time.monotonic() - t, platform=sys.platform, built_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), library=os.path.basename(lib), rng='xoshiro256** seeded by splitmix64 from the 64-bit sample seed', decision='outward binary64 weight / CDF intervals, 53-bit uniform prefix, exact fallback on the same bit stream')
        json.dump(prev, open(RECORD, 'w'), indent=1)
    if _LIB is None or getattr(_LIB, '_path', None) != lib:
        L = ctypes.CDLL(lib); L._path = lib
        L.hb_create.restype = ctypes.c_void_p; L.hb_create.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_longlong), ctypes.c_uint64]
        L.hb_free.argtypes = [ctypes.c_void_p]; L.hb_set_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]; L.hb_get_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        L.hb_steps.restype = ctypes.c_longlong; L.hb_steps.argtypes = [ctypes.c_void_p]; L.hb_counters.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]; L.hb_set_recording.argtypes = [ctypes.c_void_p]; L.hb_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
        L.hb_unresolved.restype = ctypes.c_int; L.hb_unresolved.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]; L.hb_bytes.restype = ctypes.c_size_t; L.hb_bytes.argtypes = [ctypes.c_void_p]; L.hb_apply.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.hb_run.restype = ctypes.c_longlong; L.hb_run.argtypes = [ctypes.c_void_p, ctypes.c_longlong]; L.hb_inspect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        _LIB = L
    return _LIB, dict(prev)


def kernel_bytes_estimate(hbm):
    """the kernel's heap (hb_bytes) before creation: tables + incidence + state / occupation / timestamps + workspace"""
    D = sum(hbm.cards); nf = len(hbm.pairs); nv = sum(ki * kj for (_, _, ki, kj, _) in hbm.pairs); inc = 2 * nf
    return 4 * (hbm.n * 3 + 1 + nf * 4 + inc * 2) + 8 * (nf + 1 + D + hbm.n) + 8 * (D + nv + 3 * max(hbm.cards)) + 4096


class NativeChain:
    def __init__(self, hbm, x0, seed, clock, budget=None, refine_seed=None):
        self.m = hbm; self.clock = clock; self.budget = budget; self.lib, self.build_record = build(); n = hbm.n
        cards = (ctypes.c_int * n)(*hbm.cards); D = sum(hbm.cards); psi = (ctypes.c_double * D)(*[float(v) for row in hbm.psi for v in row])
        nf = len(hbm.pairs); fi = (ctypes.c_int * max(1, nf))(*[p[0] for p in hbm.pairs]); fj = (ctypes.c_int * max(1, nf))(*[p[1] for p in hbm.pairs]); offs = [0]
        for p in hbm.pairs: offs.append(offs[-1] + len(p[4]))
        foff = (ctypes.c_longlong * (nf + 1))(*offs); fvals = (ctypes.c_double * max(1, offs[-1]))(*[float(v) for p in hbm.pairs for v in p[4]])
        self.bytes = kernel_bytes_estimate(hbm); self.owned = 0
        if budget is not None: self.owned = budget.charge(self.bytes, 'heat-bath native kernel (%d variables, %d pair factors)' % (n, nf))
        try:
            self.ctx = self.lib.hb_create(n, cards, psi, nf, fi, fj, fvals, foff, ctypes.c_uint64(int(seed) & ((1 << 64) - 1)))
            if not self.ctx: raise CE.Refused('NATIVE', 'heat-bath kernel creation failed')
            self.lib.hb_set_state(self.ctx, (ctypes.c_int * n)(*[int(v) for v in x0]))
        except BaseException:
            if self.owned: budget.release(self.owned); self.owned = 0
            raise
        self.refine = random.Random(int(refine_seed if refine_seed is not None else (int(seed) ^ 0x5DEECE66D))); self.fallbacks = 0; self.fallback_extra_bits = 0; self.seed = int(seed)
    def close(self):
        if getattr(self, 'ctx', None): self.lib.hb_free(self.ctx); self.ctx = None
        if self.owned and self.budget is not None: self.budget.release(self.owned); self.owned = 0
    def state(self):
        out = (ctypes.c_int * self.m.n)(); self.lib.hb_get_state(self.ctx, out); return list(out)
    def steps(self): return int(self.lib.hb_steps(self.ctx))
    def counters(self):
        out = (ctypes.c_longlong * 4)(); self.lib.hb_counters(self.ctx, out); return dict(resolved=int(out[0]), unresolved=int(out[1]), null_moves=int(out[2]), site_rejections=int(out[3]), exact_fallbacks=self.fallbacks, fallback_extra_bits=self.fallback_extra_bits)
    def set_recording(self): self.lib.hb_set_recording(self.ctx)
    def flush(self):
        D = sum(self.m.cards); out = (ctypes.c_longlong * D)(); self.lib.hb_flush(self.ctx, out); occ = []; k = 0
        for c in self.m.cards: occ.append([int(out[k + a]) for a in range(c)]); k += c
        return occ
    def _resolve(self):
        u = ctypes.c_uint64(); i = self.lib.hb_unresolved(self.ctx, ctypes.byref(u))
        if i < 0: return
        x = self.state(); w = self.m.weights_exact(x, i); a, extra = HX.decide_exact(w, int(u.value), lambda k: self.refine.getrandbits(k) if k else 0); self.fallbacks += 1; self.fallback_extra_bits += extra; self.lib.hb_apply(self.ctx, i, a)
    def run(self, steps, batch=200000, tag=''):
        """exactly `steps` completed transitions (batches polled; unresolved decisions resolved exactly in between); returns the steps done"""
        done = 0
        while done < steps:
            self.clock.poll('heat-bath batch %s (%d / %d)' % (tag, done, steps)); want = min(batch, steps - done); got = int(self.lib.hb_run(self.ctx, want)); done += got
            if got < want: self._resolve(); done += 1
        return done
    def inspect(self, i):
        k = self.m.cards[i]; w = (ctypes.c_double * k)(); lo = (ctypes.c_double * k)(); hi = (ctypes.c_double * k)(); self.lib.hb_inspect(self.ctx, i, w, lo, hi); return list(w), list(lo), list(hi)
