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
poll returns.
DGP10 (DGP9 independent review F9-2 / F9-3 / F9-4; carried repair contract sections 1-3; brief sections 3-4): (5) the constructor is ONE `reservation.Txn`: the range-witness temporaries, the kernel heap, the ctypes staging copies and
the observer arrays are transaction-owned until the chain is returned (then the kernel + observer charges are TRANSFERRED to the chain's `reservation.Owner`); any failure (MEMORY at the staging reservation, DEADLINE anywhere, a kernel
creation failure) rolls every token back -- live charge returns to the caller's entry value (the review's 4,800 B orphan). (6) the range witness decides by BIT LENGTHS first: floor(log2) of every per-table extremum is exact from the
numerator / denominator bit lengths (no power-of-two division, no big product), the per-variable sum of floors is a rigorous LOWER bound of log2 of the exact product and the sum of ceilings an upper bound; the exact product is formed
ONLY for a variable whose bounds straddle the floor (admitted first by its bit-length estimate, polled) -- the admission decision is EXACTLY the parent's (same predicate) at a cost independent of the entry sizes (the review's 4,091-bit
fixture: 7.2 MB traced on the parent). (7) the exact fallback admits its integer temporaries from a per-variable BIT-LENGTH estimate computed at construction BEFORE `weights_exact` runs. (8) the compiler and the compiler-version
probe run with a timeout equal to the POSITIVE remaining allowance (an exhausted allowance refuses DEADLINE before spawning; no 1 s / 30 s floors), polled before and after. (9) the OPTIONAL conditional-response observer
(heatbath_native.c): `observer=dict(sites, centers, plan)` configures it inside the same transaction; `observer_start()` is called with `set_recording()` after burn-in; `observer_snapshots()` returns the latest COMPLETED local
checkpoint per queried site as exact Python integers (uint128 limbs recombined); `observer_state()` the typed validity; the observation never changes the random draws, the update law, the source weights or the occupation counters
(the matched-run control D91 checks RNG state / transitions / final state / occupation identity with the observer on and off)."""
import os, sys, json, time, hashlib, subprocess, ctypes, random, math
from fractions import Fraction as F
from pgm.algorithms.quotient import coarse_envelope as CE
from pgm.algorithms.response import heatbath_exact as HX
from pgm.algorithms.quotient import reservation as RV
from pgm.runtime.resources import native_cache_dir, writable_home
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(HERE, 'heatbath_native.c'); RECORD = os.path.join(writable_home(HERE), 'heatbath_build.json')
FLAGS = ['-std=c11', '-O2', '-ffp-model=strict', '-ffp-contract=off', '-fno-fast-math', '-fno-unsafe-math-optimizations', '-fno-reciprocal-math', '-fno-associative-math', '-fPIC', '-shared']
RANGE_FLOOR_LOG2 = -900; REJECT_CAP = 1 << 16; FALLBACK_POLL_BITS = 64; FALLBACK_MAX_EXTRA_BITS = 4096; STAGING_OVERHEAD = 4096; OBS_S = 1 << 32
PROFILE = dict(normalization='every table divided by the exact power of two 2^s with max entry / 2^s in [1/2, 1): law-preserving, stored doubles <= 1 (converted on the fly after admission)', range_floor_log2=RANGE_FLOOR_LOG2, range_witness='exact rational all-assignment lower bound psi_min x prod min_f per variable >= 2^-900 from per-table maxima / minima only, else typed NATIVE_RANGE refusal before any commit; DGP10: decided by exact bit-length floor / ceiling sums, the exact product formed only when they straddle the floor (admitted first)',
               error_model='(2 m + 4) u relative per weight on normal binary64 values; thresholds (1 +- 2 u); CDF (1 +- (a + 2) u)', reject_cap=REJECT_CAP, fallback='heatbath_exact.decide_exact on the same 53-bit prefix, polled every %d refinement bits, integer temporaries admitted first (DGP10: from a per-variable bit-length estimate BEFORE weights_exact)' % FALLBACK_POLL_BITS, build='compiled under the caller clock (compiler and version-probe timeouts = the positive remaining allowance; DGP10: no floors)',
               observer=dict(grid='Q32 (S = 2^32): L = max(0, floor(qlo 2^32) - 1), U = min(2^32, ceil(qhi 2^32) + 1)', enclosure='qlo = RN(RN(wl rlo)(1 - 2u)) <= q_a, qhi = RN(RN(wh rhi)(1 + 4u)) >= q_a with rlo = RN(1 / Shi)(1 - 2u), rhi = RN(1 / Slo)(1 + 4u) on the step\'s own outward weight / sum bounds (normal by the range witness)', center='C = round(2^32 / k), ties to the smaller integer, frozen before sampling', sums='uint128 first_lo / first_hi / second_hi = sum max((L - C)^2, (U - C)^2); local count < 2^63 -> first sums < 2^95, squared sums < 2^127', commit='one committed visit observes exactly once (resolved: inside hb_run after the commit; exact fallback: inside hb_apply from the unchanged workspace; null moves observe; rejected site indices / abandoned batches never)', snapshots='per queried site the latest COMPLETED local checkpoint M_j (immutable buffer written only by the kernel at the checkpoint event; read by the host between synchronous kernel calls)'))
_LIB = None


class RefusedNative(CE.Refused):
    pass


def _sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest()


def build(clock=None):
    """compile the kernel into a content-addressed dylib under native_cache/; the record pins compiler, flags, source and binary hashes (a stale record triggers a rebuild). DGP10 (review F9-4): the compiler AND the compiler-version
    probe run with a timeout equal to the POSITIVE remaining allowance (an exhausted allowance is a typed DEADLINE refusal BEFORE any subprocess; no 1 s / 30 s floors); the clock is polled before and after each subprocess."""
    global _LIB
    cc = os.environ.get('CC', 'clang'); sh = _sha(SRC); cache = native_cache_dir(HERE); os.makedirs(cache, exist_ok=True); digest = hashlib.sha256((sh + json.dumps(FLAGS) + cc).encode()).hexdigest()[:16]; lib = os.path.join(cache, 'heatbath_%s.dylib' % digest)
    prev = json.load(open(RECORD)) if os.path.exists(RECORD) else {}
    if not os.path.exists(lib) or prev.get('source_sha256') != sh or prev.get('flags') != FLAGS or prev.get('compiler') != cc or (os.path.exists(lib) and prev.get('binary_sha256') != _sha(lib)):
        def allowance(where):
            if clock is None: return 600.0
            clock.poll(where); rem = clock.remaining()
            if rem <= 0: raise CE.Refused('DEADLINE', 'no allowance remains for the %s' % where)
            return rem
        timeout = allowance('native build entry'); t = time.monotonic()
        try: subprocess.check_call([cc] + FLAGS + ['-o', lib, SRC], timeout=timeout)
        except subprocess.TimeoutExpired: raise CE.Refused('DEADLINE', 'native build exceeded the remaining allowance (%.3f s)' % timeout)
        timeout2 = allowance('native build: compiler version probe')
        try: ver = subprocess.check_output([cc, '--version'], timeout=timeout2).decode().split('\n')[0]
        except subprocess.TimeoutExpired: raise CE.Refused('DEADLINE', 'compiler version probe exceeded the remaining allowance (%.3f s)' % timeout2)
        if clock is not None: clock.poll('native build: done')
        prev = dict(source_sha256=sh, binary_sha256=_sha(lib), flags=FLAGS, compiler=cc, compiler_version=ver, build_wall_s=time.monotonic() - t, platform=sys.platform, built_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), library=os.path.basename(lib), rng='xoshiro256** seeded by splitmix64 from the 64-bit sample seed', decision='outward binary64 weight / CDF intervals on power-of-two normalized tables inside a proved normal range, 53-bit uniform prefix, exact fallback on the same bit stream', range_floor_log2=RANGE_FLOOR_LOG2, observer='DGP10 conditional-response observer (optional; off unless configured)')
        json.dump(prev, open(RECORD, 'w'), indent=1)
    if _LIB is None or getattr(_LIB, '_path', None) != lib:
        L = ctypes.CDLL(lib); L._path = lib
        L.hb_create.restype = ctypes.c_void_p; L.hb_create.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_longlong), ctypes.c_uint64]
        L.hb_free.argtypes = [ctypes.c_void_p]; L.hb_set_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]; L.hb_get_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        L.hb_steps.restype = ctypes.c_longlong; L.hb_steps.argtypes = [ctypes.c_void_p]; L.hb_counters.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]; L.hb_set_recording.argtypes = [ctypes.c_void_p]; L.hb_flush.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
        L.hb_unresolved.restype = ctypes.c_int; L.hb_unresolved.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]; L.hb_bytes.restype = ctypes.c_size_t; L.hb_bytes.argtypes = [ctypes.c_void_p]; L.hb_apply.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.hb_run.restype = ctypes.c_longlong; L.hb_run.argtypes = [ctypes.c_void_p, ctypes.c_longlong]; L.hb_inspect.restype = ctypes.c_int; L.hb_inspect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)]
        L.hb_take_poll_request.restype = ctypes.c_int; L.hb_take_poll_request.argtypes = [ctypes.c_void_p]
        U64P = ctypes.POINTER(ctypes.c_uint64); L.hb_observer_bytes_for.restype = ctypes.c_size_t; L.hb_observer_bytes_for.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.hb_observer_setup.restype = ctypes.c_int; L.hb_observer_setup.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint32), ctypes.c_int, ctypes.POINTER(ctypes.c_longlong)]
        L.hb_observer_start.argtypes = [ctypes.c_void_p]; L.hb_observer_stop.argtypes = [ctypes.c_void_p]; L.hb_observer_state.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
        L.hb_observer_snapshot.restype = ctypes.c_int; L.hb_observer_snapshot.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_longlong), ctypes.POINTER(ctypes.c_int), U64P, U64P, U64P]
        L.hb_observer_current.restype = ctypes.c_int; L.hb_observer_current.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_longlong), U64P, U64P, U64P]
        L.hb_observe_inspect.restype = ctypes.c_int; L.hb_observe_inspect.argtypes = [ctypes.c_void_p, ctypes.c_int, U64P, U64P]
        L.hb_inject_bits.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_int]
        _LIB = L
    return _LIB, dict(prev)


def kernel_bytes_estimate(hbm):
    """the kernel's heap (hb_bytes) before creation: tables + incidence (incl. the (n + 1) incidence-start ints) + state / occupation / timestamps + workspace + the context struct"""
    D = sum(hbm.cards); nf = len(hbm.pairs); nv = sum(ki * kj for (_, _, ki, kj, _) in hbm.pairs); inc = 2 * nf
    return 256 + 4 * (hbm.n * 3 + 1 + nf * 4 + inc * 2 + (hbm.n + 1)) + 8 * (nf + 1 + D + hbm.n) + 8 * (D + nv + 3 * max(hbm.cards)) + 4096 + 8 * hbm.n + 64          # DGP10: + the host's per-variable fallback estimates (owned with the chain)


def table_bits(hbm):
    """the total numerator + denominator bit length of every table entry (the staging conversions form one exact scaled Fraction per entry)"""
    return sum(v.numerator.bit_length() + v.denominator.bit_length() for row in hbm.psi for v in row) + sum(v.numerator.bit_length() + v.denominator.bit_length() for p in hbm.pairs for v in p[4])


def staging_bytes_estimate(hbm):
    """the ctypes staging copies built by the host before hb_create (released after creation); DGP10: + the transient exact scaled Fractions of the conversions (bit-length dependent)"""
    D = sum(hbm.cards); nf = len(hbm.pairs); nv = sum(ki * kj for (_, _, ki, kj, _) in hbm.pairs)
    return 8 * (D + nv + nf + 1) + 4 * (hbm.n * 2 + 2 * max(1, nf)) + 32 * (D + nv) + table_bits(hbm) // 8 + 64 * (D + nv) + STAGING_OVERHEAD          # the Python float objects of the conversion lists (~32 B each) + one scaled Fraction per entry


def witness_bytes_estimate(hbm): return 64 * 2 * (hbm.n + len(hbm.pairs)) + 64 * hbm.n + 4096                            # DGP10: small integers only (floor / ceiling log2 per table, the per-variable sums); the exact product of a straddling variable is admitted separately


def _pow2(s): return (F(2) ** s) if s >= 0 else F(1) / (F(2) ** (-s))


def floor_log2(x):
    """EXACT floor(log2 x) of a positive rational from the bit lengths (2^(e-1) < x < 2^(e+1) with e = bits(num) - bits(den); one exact integer comparison decides)"""
    e = x.numerator.bit_length() - x.denominator.bit_length()
    ge = (x.numerator >= (x.denominator << e)) if e >= 0 else ((x.numerator << (-e)) >= x.denominator)
    return e if ge else e - 1


def ceil_log2(x):
    """EXACT ceil(log2 x) of a positive rational"""
    f = floor_log2(x); return f if (x.numerator << (-f) if f < 0 else x.numerator) == (x.denominator << f if f >= 0 else x.denominator) else f + 1


def _pow2_scale(xmax):
    """the exact power of two 2^s with xmax / 2^s in [1/2, 1) for a positive rational xmax -> s = floor(log2 xmax) + 1 (exact from bit lengths; no division)"""
    return floor_log2(xmax) + 1


def exact_product_bytes_estimate(bits_sum, m):
    """the bit-length estimate of forming one exact product of m + 1 rationals whose numerator + denominator bits sum to bits_sum (every partial product + the gcd temporaries: <= 3 copies of the final size)"""
    return 3 * (bits_sum // 8 + 64) + 64 * (m + 2) + 1024


def range_witness(hbm, clock=None, budget=None, txn=None):
    """-> dict(scales=dict(unary=[s_i], pair=[s_f]), range=dict(...)) WITHOUT materializing any scaled table: per table only its exact max (-> the power-of-two scale with max / 2^s in [1/2, 1)) and its exact min; the all-assignment
    range witness per variable: lower bound on every conditional weight = (psi_min / 2^s_i) x prod_f (min_f / 2^s_f); upper bound < 1 by construction; admitted iff min_i lower_i >= 2^RANGE_FLOOR_LOG2. DGP10 (review F9-3 / F9-4):
    the comparison is decided by EXACT integer log2 floors / ceilings (dividing by 2^s shifts them exactly) -- sum of floors <= log2(product) <= sum of ceilings -- and the exact rational product is formed ONLY for a variable whose
    two bounds straddle the floor (admitted first by its bit-length estimate, polled): the decision is the parent's exact predicate at an entry-size-independent cost; polled per table and per variable"""
    su = []; lf_u = []; cf_u = []
    for t, row in enumerate(hbm.psi):
        if clock is not None and (t & 63) == 0: clock.poll('native range witness: unary table %d' % t)
        m = max(row); s = _pow2_scale(m); mn = min(row); su.append(s); lf_u.append(floor_log2(mn) - s); cf_u.append(ceil_log2(mn) - s)
    sp = []; lf_p = []; cf_p = []
    for t, (i, j, ki, kj, vals) in enumerate(hbm.pairs):
        if clock is not None and (t & 63) == 0: clock.poll('native range witness: pair table %d' % t)
        m = max(vals); s = _pow2_scale(m); mn = min(vals); sp.append(s); lf_p.append(floor_log2(mn) - s); cf_p.append(ceil_log2(mn) - s)
    worst_lo = None; per_var = []; exact_formed = 0; admitted = True; worst_exact_log2 = None
    for i in range(hbm.n):
        if clock is not None and (i & 15) == 0: clock.poll('native range witness: variable %d' % i)
        lo = lf_u[i]; hi = cf_u[i]
        for fi, role in hbm.incident[i]: lo += lf_p[fi]; hi += cf_p[fi]
        if lo >= RANGE_FLOOR_LOG2: dec = True; val = lo
        elif hi < RANGE_FLOOR_LOG2: dec = False; val = lo
        else:
            # straddling: the exact product decides (admitted first from the bit lengths of its factors; polled)
            mn_u = min(hbm.psi[i]); bits = mn_u.numerator.bit_length() + mn_u.denominator.bit_length() + abs(su[i]) + sum(min(hbm.pairs[fi][4]).numerator.bit_length() + min(hbm.pairs[fi][4]).denominator.bit_length() + abs(sp[fi]) for fi, _ in hbm.incident[i])
            est = exact_product_bytes_estimate(bits, len(hbm.incident[i])); tok = None
            if txn is not None: tok = txn.reserve(est, 'native range witness: exact product of variable %d (%d bits)' % (i, bits))
            elif budget is not None: budget.charge(est, 'native range witness: exact product of variable %d (%d bits)' % (i, bits))
            try:
                prod = mn_u / _pow2(su[i])
                for c_, (fi, _) in enumerate(hbm.incident[i]):
                    prod *= min(hbm.pairs[fi][4]) / _pow2(sp[fi])
                    if clock is not None and (c_ & 7) == 7: clock.poll('native range witness: exact product of variable %d (factor %d)' % (i, c_))
                dec = prod >= _pow2(RANGE_FLOOR_LOG2); val = floor_log2(prod); exact_formed += 1
                if worst_exact_log2 is None or val < worst_exact_log2: worst_exact_log2 = val
                prod = None
            finally:
                if tok is not None: txn.release(tok)
                elif budget is not None: budget.release(est)
        per_var.append(val); admitted = admitted and dec
        if worst_lo is None or val < worst_lo: worst_lo = val
    rng = dict(floor_log2=RANGE_FLOOR_LOG2, min_weight_log2_lower=(float(worst_lo) if worst_lo is not None else None), max_weight_log2_upper=0.0, admitted=bool(admitted and hbm.n > 0), per_variable_min_log2=[int(x) for x in per_var[:64]], n_variables=hbm.n, exact_products_formed=exact_formed,
               bound='exact integer floor(log2) sums (a rigorous lower bound of the exact per-variable product; the exact product itself only where the floor / ceiling sums straddle 2^%d)' % RANGE_FLOOR_LOG2,
               rule='every scaled entry < 1 (no overflow; prefix products nonincreasing); min over variables of psi_min x prod min_f >= 2^%d (exact comparison) -> every weight, prefix, cumulative sum and nonzero threshold product normal' % RANGE_FLOOR_LOG2)
    return dict(scales=dict(unary=su, pair=sp), range=rng)


def fallback_bytes_estimate_one(hbm, i):
    """Admit the rational weights, common-denominator row and decision workspace.

    Let b bound numerator-plus-denominator bits of each conditional weight.
    The LCM of k unrelated denominators can have k*b bits; consequently EACH
    cleared integer weight can have (k+1)*b bits.  Both the integer row and
    its cumulative row are retained by decide_exact, so storage may grow as
    k**2*b, even for nearly uniform probabilities.  Include the bounded bit
    refinement, arithmetic temporaries, list slots and copied native state.
    Integer sizes use the supported CPython 30-bit limb representation with
    64 bytes of object/slack overhead; rational scratch is charged generously.
    """
    bits = max(v.numerator.bit_length() + v.denominator.bit_length() for v in hbm.psi[i]) + sum(max(v.numerator.bit_length() + v.denominator.bit_length() for v in hbm.pairs[fi][4]) for fi, _ in hbm.incident[i]); k = hbm.cards[i]
    def integer_bytes(nbits): return 64 + 4 * ((nbits + 29) // 30)
    integer_bits = (k + 1) * bits
    sum_bits = integer_bits + max(1, k.bit_length())
    decision_bits = sum_bits + 53 + FALLBACK_MAX_EXTRA_BITS + 1
    rational_workspace = 4 * k * (128 + 2 * integer_bytes(bits))
    integer_workspace = (k + 8) * integer_bytes(integer_bits)
    decision_workspace = (k + 6) * integer_bytes(decision_bits)
    return rational_workspace + integer_workspace + decision_workspace + 64 * (hbm.n + 6 * k + 16) + 4096


def fallback_bytes_estimates(hbm):
    """per variable (computed at construction so `_resolve` admits BEFORE `weights_exact`; review F9-3)"""
    return [fallback_bytes_estimate_one(hbm, i) for i in range(hbm.n)]


def observer_bytes_estimate(n, nq, Q, J): return 4 * (n + 4 * nq + 1) + 4 * nq + 8 * (2 * nq + J) + 16 * 6 * Q + 4096         # mirrors hb_observer_bytes_for + staging slack


def local_checkpoint_plan(J=64, M1=1 << 14, ratio=F(5, 4)):
    """the FROZEN local visit-count plan M_j = ceil(2^14 (5/4)^(j-1)), j = 1..J, exact integers, strictly increasing (asserted)"""
    plan = []; cur = F(M1)
    for j in range(J):
        Mj = math.ceil(cur); assert not plan or Mj > plan[-1], (j, Mj, plan[-1] if plan else None); plan.append(int(Mj)); cur *= ratio
    return plan


def center_for(k, S=OBS_S):
    """C = round(S / k) with ties to the SMALLER integer (frozen before sampling)"""
    q, r = divmod(S, k); return q + (1 if 2 * r > k else 0)


def normalize_tables(hbm):
    """materialized scaled tables (CONTROLS / references only -- the chain converts on the fly after admission): every table divided by its exact power-of-two scale"""
    w = range_witness(hbm); psi = [[v / _pow2(s) for v in row] for row, s in zip(hbm.psi, w['scales']['unary'])]; pairs = [[v / _pow2(s) for v in p[4]] for p, s in zip(hbm.pairs, w['scales']['pair'])]
    return dict(psi=psi, pairs=pairs, scales=w['scales'], range=w['range'])


class NativeChain:
    def __init__(self, hbm, x0, seed, clock, budget=None, refine_seed=None, observer=None):
        self.m = hbm; self.clock = clock; self.budget = budget; self.owned = 0; self.staging_owned = 0; n = hbm.n; self.ctx = None; self.owner = RV.Owner(budget, 'heat-bath native chain'); self.observer = None
        clock.poll('native chain construction entry')
        with RV.Txn(budget, clock, 'native chain') as txn:
            try:
                # 1. the range witness's own small temporaries are admitted FIRST, then the witness is computed from per-table extrema (bit-length decision; exact products only where they straddle the floor, admitted inside)
                tok_w = txn.reserve(witness_bytes_estimate(hbm), 'heat-bath native range witness temporaries'); norm = range_witness(hbm, clock, txn=txn); self.range_record = norm['range']; self.scales = norm['scales']; txn.release(tok_w)
                if not norm['range']['admitted']: raise RefusedNative('NATIVE_RANGE', 'the native arithmetic range witness fails: the smallest normalized conditional weight over all assignments has log2 %.1f < %d (exact fallback chain required)' % (norm['range']['min_weight_log2_lower'] if norm['range']['min_weight_log2_lower'] is not None else -math.inf, RANGE_FLOOR_LOG2))
                # 2. admission BEFORE staging: the kernel heap (transferred to the chain on success) + the ctypes staging copies (a temporary) + the per-variable fallback estimates
                self.bytes = kernel_bytes_estimate(hbm); staging = staging_bytes_estimate(hbm); tok_k = txn.reserve(self.bytes, 'heat-bath native kernel (%d variables, %d pair factors)' % (n, len(hbm.pairs))); tok_s = txn.reserve(staging, 'heat-bath native staging copies')
                self.lib, self.build_record = build(clock); clock.poll('native chain staging'); su = self.scales['unary']; sp = self.scales['pair']
                cards = (ctypes.c_int * n)(*hbm.cards); D = sum(hbm.cards); psi_l = []
                for i, row in enumerate(hbm.psi):
                    if (i & 63) == 63: clock.poll('native chain staging: unary %d' % i)
                    psi_l.extend(float(v / _pow2(su[i])) for v in row)
                psi = (ctypes.c_double * D)(*psi_l); psi_l = None
                nf = len(hbm.pairs); fi = (ctypes.c_int * max(1, nf))(*[p[0] for p in hbm.pairs]); fj = (ctypes.c_int * max(1, nf))(*[p[1] for p in hbm.pairs]); offs = [0]
                for p in hbm.pairs: offs.append(offs[-1] + len(p[4]))
                fv = []
                for f, p in enumerate(hbm.pairs):
                    if (f & 31) == 31: clock.poll('native chain staging: pair table %d' % f)
                    fv.extend(float(v / _pow2(sp[f])) for v in p[4])
                foff = (ctypes.c_longlong * (nf + 1))(*offs); fvals = (ctypes.c_double * max(1, offs[-1]))(*fv); fv = None
                self.ctx = self.lib.hb_create(n, cards, psi, nf, fi, fj, fvals, foff, ctypes.c_uint64(int(seed) & ((1 << 64) - 1)))
                if not self.ctx: raise CE.Refused('NATIVE', 'heat-bath kernel creation failed')
                self.lib.hb_set_state(self.ctx, (ctypes.c_int * n)(*[int(v) for v in x0]))
                del cards, psi, fi, fj, foff, fvals; txn.release(tok_s)
                actual = int(self.lib.hb_bytes(self.ctx))
                if actual > self.bytes: raise CE.Refused('MEMORY', 'native kernel heap %d B exceeds its admitted estimate %d B' % (actual, self.bytes))
                self.bytes_actual = actual; self.fb_est = fallback_bytes_estimates(hbm)                                     # (the estimates' own bytes are inside kernel_bytes_estimate)
                # 3. the optional conditional-response observer (admitted before hb_observer_setup allocates)
                if observer is not None:
                    sites = list(observer['sites']); centers = list(observer['centers']); plan = list(observer['plan']); nq = len(sites); Q = sum(hbm.cards[i] for i in sites)
                    assert len(centers) == nq and plan and all(plan[j] > plan[j - 1] for j in range(1, len(plan))) and plan[0] >= 1
                    self.obs_bytes = observer_bytes_estimate(n, nq, Q, len(plan)); tok_o = txn.reserve(self.obs_bytes, 'heat-bath response observer (%d sites, %d coordinates, %d local checkpoints)' % (nq, Q, len(plan)))
                    r = int(self.lib.hb_observer_setup(self.ctx, nq, (ctypes.c_int * nq)(*sites), (ctypes.c_uint32 * nq)(*centers), len(plan), (ctypes.c_longlong * len(plan))(*plan)))
                    if r < 0: raise CE.Refused('NATIVE', 'observer setup refused (%d)' % r)
                    actual2 = int(self.lib.hb_bytes(self.ctx))
                    if actual2 > self.bytes + self.obs_bytes: raise CE.Refused('MEMORY', 'native kernel + observer heap %d B exceeds the admitted %d B' % (actual2, self.bytes + self.obs_bytes))
                    self.observer = dict(sites=sites, centers=centers, plan=plan, nq=nq, Q=Q, J=len(plan), bytes_admitted=self.obs_bytes, bytes_actual=actual2 - actual); txn.transfer(tok_o, self.owner)
                txn.transfer(tok_k, self.owner); self.owned = self.owner.bytes
            except BaseException:
                if self.ctx: self.lib.hb_free(self.ctx); self.ctx = None
                raise                                                                                                    # the transaction rolls every token back: live charge == the caller's entry charge
        self.refine = random.Random(int(refine_seed if refine_seed is not None else (int(seed) ^ 0x5DEECE66D))); self.fallbacks = 0; self.fallback_extra_bits = 0; self.poll_returns = 0; self.seed = int(seed)
    def close(self):
        if getattr(self, 'ctx', None): self.lib.hb_free(self.ctx); self.ctx = None
        self.owner.close(); self.owned = 0
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
        """the exact fallback of ONE unresolved decision: polled, its integer temporaries admitted FIRST from the per-variable bit-length estimate (DGP10: BEFORE weights_exact runs), the SAME 53-bit prefix refined by independent
        uniform bits; hb_apply commits the transition AND the pending observation together"""
        u = ctypes.c_uint64(); i = self.lib.hb_unresolved(self.ctx, ctypes.byref(u))
        if i < 0: return False
        self.clock.poll('heat-bath exact fallback (site %d)' % i)
        est = self.fb_est[i] if getattr(self, 'fb_est', None) is not None else fallback_bytes_estimate_one(self.m, i)             # (an injected / partially constructed chain: the estimate is formed for this variable, still BEFORE weights_exact)
        with RV.Txn(self.budget, None, 'exact fallback') as txn:
            txn.reserve(est, 'exact fallback integers (variable %d)' % i); x = self.state(); w = self.m.weights_exact(x, i)
            a, extra = HX.decide_exact(w, int(u.value), lambda k: self.refine.getrandbits(k) if k else 0, max_extra_bits=FALLBACK_MAX_EXTRA_BITS, clock=self.clock, poll_every=FALLBACK_POLL_BITS)
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
        k = self.m.cards[i]; w = (ctypes.c_double * k)(); lo = (ctypes.c_double * k)(); hi = (ctypes.c_double * k)(); r = int(self.lib.hb_inspect(self.ctx, i, w, lo, hi))
        if r < 0: raise CE.Defect('hb_inspect refused: a decision is pending (the workspace holds the unresolved step)')
        return list(w), list(lo), list(hi)
    # ---- DGP10 observer
    def observer_start(self):
        if self.observer is None: raise CE.Defect('observer not configured')
        self.lib.hb_observer_start(self.ctx)
    def observer_stop(self): self.lib.hb_observer_stop(self.ctx)
    def observer_state(self):
        out = (ctypes.c_longlong * 8)(); self.lib.hb_observer_state(self.ctx, out); o = list(out)
        return dict(configured=bool(o[0]), observing=bool(o[1]), valid=bool(o[2]), invalid_code=int(o[3]), invalid_reason={0: None, 1: 'enclosure outside the proved range', 2: 'local counter bound'}.get(int(o[3]), 'unknown'), committed=int(o[4]), snapshots=int(o[5]), nq=int(o[6]), Q=int(o[7]))
    @staticmethod
    def _ints(limbs, k): return [int(limbs[2 * a]) | (int(limbs[2 * a + 1]) << 64) for a in range(k)]
    def observer_snapshots(self):
        """-> per queried site the latest COMPLETED local checkpoint: dict(site, q, k, center, count (= M_j), j (1-based; None when no checkpoint completed), first_lo[], first_hi[], second_hi[] as exact Python integers)"""
        out = []
        for q, i in enumerate(self.observer['sites']):
            k = self.m.cards[i]; cnt = ctypes.c_longlong(); j = ctypes.c_int(); fl = (ctypes.c_uint64 * (2 * k))(); fh = (ctypes.c_uint64 * (2 * k))(); sh = (ctypes.c_uint64 * (2 * k))()
            r = int(self.lib.hb_observer_snapshot(self.ctx, q, ctypes.byref(cnt), ctypes.byref(j), fl, fh, sh)); assert r == k
            jj = int(j.value); out.append(dict(site=i, q=q, k=k, center=self.observer['centers'][q], count=int(cnt.value), j=(jj + 1 if jj >= 0 else None), M=(self.observer['plan'][jj] if jj >= 0 else None), first_lo=self._ints(fl, k), first_hi=self._ints(fh, k), second_hi=self._ints(sh, k)))
        return out
    def observer_current(self, q):
        """the CURRENT partial sums of queried site q (diagnostic only)"""
        i = self.observer['sites'][q]; k = self.m.cards[i]; cnt = ctypes.c_longlong(); fl = (ctypes.c_uint64 * (2 * k))(); fh = (ctypes.c_uint64 * (2 * k))(); sh = (ctypes.c_uint64 * (2 * k))()
        self.lib.hb_observer_current(self.ctx, q, ctypes.byref(cnt), fl, fh, sh); return dict(site=i, count=int(cnt.value), first_lo=self._ints(fl, k), first_hi=self._ints(fh, k), second_hi=self._ints(sh, k))
    def inject_bits(self, bits, nbits):
        """QUALIFICATION hook: the next draws read these bits (forces an ambiguous 53-bit prefix -> the exact fallback with a pending observation)"""
        self.lib.hb_inject_bits(self.ctx, ctypes.c_uint64(int(bits)), int(nbits))
    def observe_inspect(self, i):
        """the observation enclosure [L / 2^32, U / 2^32] of every state of site i at the current state, as the kernel would record it (qualification; no accumulation)"""
        k = self.m.cards[i]; L = (ctypes.c_uint64 * k)(); U = (ctypes.c_uint64 * k)(); r = int(self.lib.hb_observe_inspect(self.ctx, i, L, U))
        if r < 0: raise CE.Defect('hb_observe_inspect refused: a decision is pending')
        return [int(x) for x in L], [int(x) for x in U]
    def record(self):
        return dict(bytes_admitted=self.bytes, bytes_actual=getattr(self, 'bytes_actual', None), owner_bytes=self.owner.bytes, range=self.range_record, scales=dict(unary_distinct=len(set(self.scales['unary'])), pair_distinct=len(set(self.scales['pair'])), unary_min=min(self.scales['unary']), unary_max=max(self.scales['unary']), pair_min=(min(self.scales['pair']) if self.scales['pair'] else None), pair_max=(max(self.scales['pair']) if self.scales['pair'] else None)), observer=(dict(self.observer, state=self.observer_state()) if (self.observer is not None and self.ctx) else self.observer))
