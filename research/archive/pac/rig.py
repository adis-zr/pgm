"""Rigorous arithmetic helpers for the PAC engine -- candidate v2 (repair of review findings F02 / F03 of 13 Nov 2026).

Two representations, each with a stated rounding contract:
  * DIRECTED binary64 ("DF"): a lower bound is obtained by rounding to nearest and then stepping ONE float towards -inf (math.nextafter / numpy.nextafter);
    an upper bound by stepping towards +inf. For round-to-nearest the true value lies within half an ulp of the rounded result, so the neighbour in the
    needed direction is a valid bound in EVERY case, including subnormal results, results that underflow to zero (the neighbours of 0 are +-2^-1074,
    and a nonnegative true value is then enclosed by [0, 2^-1074]) and exact results. Sums of nonnegative increments in [0, 1] cannot overflow for
    fewer than 2^1000 trials. The accumulators therefore carry NO multiplicative error label any more: a lower accumulator is a directed-down sum of
    directed-down terms (<= the exact sum), an upper accumulator the mirror image. The hardware rounding mode is CHECKED at stream start (`fp_selfcheck`).
    Binary64 values are dyadic rationals, so `Fraction(x)` recovers them exactly.
  * gmpy2 mpfr with PREC = 128 and directed rounding contexts that TRAP underflow / overflow / invalid / erange (`RangeStop`), used for the confidence
    boundaries (log, sqrt) and for the sign-aware interval arithmetic of the quadratic inversion.

Quadratic inversion (`shrunk_rejection`): for a concave quadratic g with EXACT rational coefficients the candidate open rejection interval is computed by
sign-aware interval arithmetic, and then each endpoint is CERTIFIED by EXACT rational evaluation g(endpoint) > 0. Concavity makes g > 0 on the whole closed
segment between two points where it is positive, so the open interval is strictly inside {g > 0}. If the exact check fails the interval is shrunk towards its
midpoint (a bounded number of times); if it still fails, NO rejection is returned (conservative). The gate re-verifies recorded intervals with
`exact_quadratic_positive_on`."""
import gmpy2
from gmpy2 import mpfr, mpq
from fractions import Fraction as F
import math, sys
PREC = 128
_TRAPS = dict(trap_underflow=True, trap_overflow=True, trap_invalid=True, trap_divzero=True, trap_erange=True)
_UP = gmpy2.context(precision=PREC, round=gmpy2.RoundUp, **_TRAPS); _DN = gmpy2.context(precision=PREC, round=gmpy2.RoundDown, **_TRAPS)
_MPFR = type(mpfr(0)); INF = float('inf')


class RangeStop(Exception):
    """typed numerical refusal: an mpfr operation left the representable range (underflow / overflow / invalid), or a binary64 directed bound is not finite"""


def to_q(x):
    if isinstance(x, F): return mpq(x.numerator, x.denominator)
    if isinstance(x, (int, float)): return mpq(x)
    return x


def _guard(fn):
    try: return fn()
    except (gmpy2.UnderflowResultError, gmpy2.OverflowResultError, gmpy2.InvalidOperationError, gmpy2.RangeError, gmpy2.DivisionByZeroError, ValueError) as e: raise RangeStop(str(e))


def neg(x):
    """EXACT negation of an mpfr: performed inside the 128-bit context (a negation at the interpreter's default 53-bit context would ROUND a 128-bit operand;
    this was the review's IV.sq defect)"""
    with _DN: return -x


def frac(x):
    """exact rational value of a finite mpfr or binary64 (both dyadic)"""
    if isinstance(x, float):
        if not math.isfinite(x): raise RangeStop('non-finite binary64 in an exact conversion')
        return F(x)
    q = mpq(x); return F(int(q.numerator), int(q.denominator))


# ---------------- directed binary64
def _to_float(q):
    try: return float(q)                                   # Fraction.__float__ / int.__float__ are correctly rounded (int/int true division)
    except OverflowError: raise RangeStop('rational too large for binary64')
def df_lo(q):
    """binary64 lower bound of the exact NONNEGATIVE rational / int q: nearest conversion; exact when representable, else one step down (clamped at 0)"""
    x = _to_float(q)
    if F(x) == q: return x
    y = math.nextafter(x, -INF); return 0.0 if y < 0 else y
def df_hi(q):
    x = _to_float(q)
    if F(x) == q: return x
    y = math.nextafter(x, INF)
    if not math.isfinite(y): raise RangeStop('rational too large for binary64')
    return y
def add_lo(a, b):
    """lower bound of a + b for NONNEGATIVE lower bounds a, b (nearest sum, one step down, clamped at 0)"""
    y = math.nextafter(a + b, -INF); return 0.0 if y < 0 else y
def add_hi(a, b):
    y = math.nextafter(a + b, INF)
    if not math.isfinite(y): raise RangeStop('binary64 upper accumulator overflow')
    return y
def mul_lo(a, b):
    """a, b >= 0"""
    y = math.nextafter(a * b, -INF); return 0.0 if y < 0 else y
def mul_hi(a, b):
    y = math.nextafter(a * b, INF)
    if not math.isfinite(y): raise RangeStop('binary64 upper product overflow')
    return y


def fp_selfcheck():
    """verify that the interpreter's binary64 arithmetic rounds to nearest-even and that the directed-neighbour rule encloses exact results on a fixed battery
    (run at every stream start, charged). Raises RangeStop if the arithmetic environment is not the assumed one."""
    import numpy as np, random
    assert 1.0 + 2.0 ** -53 == 1.0 and 1.0 + 2.0 ** -52 + 2.0 ** -53 == 1.0 + 2.0 ** -51 and 1.0 + 3 * 2.0 ** -53 == 1.0 + 2.0 ** -51, 'not round-to-nearest-even'
    assert float(F(1, 3)) == 0.3333333333333333 and float(F(2, 3)) == 0.6666666666666666
    assert np.nextafter(np.float64(0.0), np.float64(INF)) == 2.0 ** -1074 and math.nextafter(0.0, -INF) == -(2.0 ** -1074)
    rng = random.Random(20261113)
    for _ in range(2000):
        a = F(rng.randrange(0, 1 << 60), 1 << rng.randrange(0, 1100)); b = F(rng.randrange(0, 1 << 60), 1 << rng.randrange(0, 1100))
        s = a + b; p = a * b
        fa, fb = float(a), float(b)
        if not (F(df_lo(a)) <= a <= F(df_hi(a))): raise RangeStop('directed conversion failed')
        if not (F(df_lo(a / 3)) <= a / 3 <= F(df_hi(a / 3))): raise RangeStop('directed conversion failed (inexact)')
        if not (F(add_lo(fa, fb)) <= F(fa) + F(fb) <= F(add_hi(fa, fb))): raise RangeStop('directed add failed')
        if not (F(mul_lo(fa, fb)) <= F(fa) * F(fb) <= F(mul_hi(fa, fb))): raise RangeStop('directed mul failed')
        x = np.array([fa, fb]); y = np.array([fb, fa])
        lo = np.nextafter(x * y, -INF); hi = np.nextafter(x * y, INF)
        if not (F(float(max(lo[0], 0.0))) <= F(fa) * F(fb) <= F(float(hi[0]))): raise RangeStop('numpy directed mul failed')
    return True


# ---------------- mpfr helpers
def dn(x):
    """mpfr lower bound of an exact rational / int / float"""
    def f():
        with _DN: return mpfr(to_q(x)) if not isinstance(x, _MPFR) else mpfr(x)
    return _guard(f)
def up(x):
    def f():
        with _UP: return mpfr(to_q(x)) if not isinstance(x, _MPFR) else mpfr(x)
    return _guard(f)


class IV:
    """closed interval [lo, hi] of mpfr with outward rounding; sign-aware products, quotients and squares (every case of the sign table)"""
    __slots__ = ('lo', 'hi')
    def __init__(self, lo, hi=None):
        if hi is None: hi = lo
        self.lo = lo if isinstance(lo, _MPFR) else dn(lo); self.hi = hi if isinstance(hi, _MPFR) else up(hi)
        assert self.lo <= self.hi, (self.lo, self.hi)
    @staticmethod
    def exact(q): return IV(q, q)
    @staticmethod
    def _raw(lo, hi):
        iv = IV.__new__(IV); iv.lo = lo; iv.hi = hi; return iv
    def __add__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        def f():
            with _DN: lo = self.lo + o.lo
            with _UP: hi = self.hi + o.hi
            return IV._raw(lo, hi)
        return _guard(f)
    def __neg__(self): return IV._raw(neg(self.hi), neg(self.lo))             # exact negation inside the 128-bit context
    def __sub__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        return self + (-o)
    def __mul__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        def f():
            with _DN: cl = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
            with _UP: ch = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
            return IV._raw(min(cl), max(ch))
        return _guard(f)
    def __truediv__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        if not (o.lo > 0 or o.hi < 0): raise ZeroDivisionError('interval divisor contains zero')
        def f():
            with _DN: cl = [self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi]
            with _UP: ch = [self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi]
            return IV._raw(min(cl), max(ch))
        return _guard(f)
    def sq(self):
        """[lo, hi]^2: the magnitudes of the endpoints are formed by EXACT negation, so the square of a negative endpoint loses nothing (repair of the review's IV.sq control)"""
        a = neg(self.lo) if self.lo < 0 else self.lo; b = neg(self.hi) if self.hi < 0 else self.hi
        m = max(a, b)
        def f():
            with _UP: hi = m * m
            if self.lo >= 0 or self.hi <= 0:
                mn = min(a, b)
                with _DN: lo = mn * mn
                return IV._raw(lo, hi)
            return IV._raw(mpfr(0), hi)
        return _guard(f)
    def frac(self): return (frac(self.lo), frac(self.hi))
    def __repr__(self): return 'IV[%s, %s]' % (float(self.lo), float(self.hi))


def sqrt_bounds(q, bits=128):
    """exact rational bounds lo <= sqrt(q) <= hi for a nonnegative rational q, with relative gap <= 2^-bits"""
    q = F(q)
    if q < 0: raise ValueError('sqrt of negative')
    if q == 0: return F(0), F(0)
    s = 1 << (2 * bits); n = q.numerator * s; d = q.denominator
    r = math.isqrt(n * d); lo = F(r, d << bits); hi = F(r + 1, d << bits)
    return lo, hi


def range_boundary_up(rho, V_hi, alpha):
    """b(V, alpha) = sqrt((rho+V) log((rho+V)/(rho alpha^2))) rounded UP (exact rational inputs; mpfr round-up log and sqrt). V_hi is an upper bound on V
    (b increases in V); alpha the per-coordinate failure allowance. Returns an exact rational upper bound."""
    rho = F(rho); V = F(V_hi); alpha = F(alpha); s = rho + V; arg = s / (rho * alpha * alpha)
    if arg <= 1: return F(0)
    def f():
        with _UP:
            L = gmpy2.log(mpfr(to_q(arg))); prod = mpfr(to_q(s)) * L; root = gmpy2.sqrt(prod)
        return frac(root)
    return _guard(f)


def psi(lam):
    """psi(lambda) = -log(1-lambda) - lambda as an exact rational (LOWER, UPPER) bound pair for dyadic lambda in (0,1). Directed rounding with the NEGATION handled
    explicitly: an upper bound of -log(x) is the negation of a LOWER bound of log(x) (negation is exact), then the subtraction of lambda is rounded in the wanted direction."""
    lam = F(lam); x = to_q(1 - lam)
    def f():
        with _DN: log_lo = gmpy2.log(mpfr(x))
        with _UP: log_hi = gmpy2.log(mpfr(x))
        with _UP: hi = (-log_lo) - mpfr(to_q(lam))          # the negation inside the 128-bit context is exact
        with _DN: lo = (-log_hi) - mpfr(to_q(lam))
        return frac(lo), frac(hi)
    return _guard(f)


def log_threshold_up(K, delta_c, omega_l):
    """log(2K/(delta omega_l)) rounded up, exact rational"""
    def f():
        with _UP: v = gmpy2.log(mpfr(to_q(F(2 * K) / (F(delta_c) * F(omega_l)))))
        return frac(v)
    return _guard(f)


def quad_roots_outer(A, Bc, Cc):
    """for the quadratic A t^2 + B t + C with exact rational coefficients (A != 0), return the OUTER rational enclosures ((lo1, hi1), (lo2, hi2)) of its two real
    roots, ordered lo1 <= hi1 <= lo2 <= hi2 (each pair encloses one root; equal roots give two coincident pairs), or None if no real root. Exact rational discriminant;
    exact-rational sqrt bounds; the division by 2A is sign-aware (a negative 2A reverses the order of the bounds). Repaired after review R11 (the previous version
    returned reversed pairs for A < 0); verified against exact roots in qualification."""
    A = F(A); Bc = F(Bc); Cc = F(Cc)
    if A == 0: raise ValueError('not a quadratic')
    disc = Bc * Bc - 4 * A * Cc
    if disc < 0: return None
    slo, shi = sqrt_bounds(disc)                                   # 0 <= slo <= sqrt(disc) <= shi
    den = 2 * A
    def div_outer(lo, hi):                                         # outer enclosure of [lo, hi] / den
        a, b = lo / den, hi / den
        return (a, b) if den > 0 else (b, a)
    r_minus = div_outer(-Bc - shi, -Bc - slo)                      # encloses (-B - sqrt)/2A
    r_plus = div_outer(-Bc + slo, -Bc + shi)                       # encloses (-B + sqrt)/2A
    return (r_minus, r_plus) if r_minus[0] <= r_plus[0] else (r_plus, r_minus)


def shrunk_rejection(A2, A1, A0L, max_shrink=8):
    """for the CONCAVE quadratic g(t) = A2 t^2 + A1 t + A0L (A2 < 0; exact rationals), return an OPEN interval (lo, hi) such that g(t) > 0 for every t in [lo, hi],
    or None when no such interval is certified. Construction: sign-aware interval arithmetic (IV) for the discriminant and the two roots; the candidate interval is
    (upper bound of the smaller root, lower bound of the larger root); then both endpoints are CERTIFIED by EXACT rational evaluation g(lo) > 0 and g(hi) > 0
    (concavity: positive at both endpoints => positive on the segment). On failure the interval is shrunk towards its midpoint by a factor 2 per step (at most
    `max_shrink` steps) and re-certified; if no certified interval remains, None (no rejection; conservative)."""
    a2 = F(A2); a1 = F(A1); a0 = F(A0L)
    if a2 >= 0: raise ValueError('shrunk_rejection needs a concave quadratic (A2 < 0)')
    g = lambda t: a2 * t * t + a1 * t + a0
    try:
        A2i = IV.exact(a2); A1i = IV.exact(a1); A0i = IV.exact(a0)
        disc = A1i.sq() - IV.exact(4) * A2i * A0i
        if disc.hi < 0: return None
        def sq():
            with _DN: slo = gmpy2.sqrt(disc.lo) if disc.lo > 0 else mpfr(0)
            with _UP: shi = gmpy2.sqrt(disc.hi)
            return IV._raw(slo, shi)
        s = _guard(sq); den = IV.exact(2) * A2i                                  # den < 0 exactly
        r_small = (-A1i + s) / den; r_large = (-A1i - s) / den                     # den < 0: (-a1 + s)/den is the SMALLER root, (-a1 - s)/den the LARGER
        lo = frac(r_small.hi); hi = frac(r_large.lo)                               # inner candidate
    except (RangeStop, ZeroDivisionError): return None
    for _ in range(max_shrink + 1):
        if not (lo < hi): return None
        if g(lo) > 0 and g(hi) > 0: return lo, hi                                 # EXACT certification (concave => g > 0 on [lo, hi])
        mid = (lo + hi) / 2; lo = (lo + mid) / 2; hi = (hi + mid) / 2
    return None


def exact_quadratic_positive_on(A2, A1, A0L, lo, hi):
    """independent checker predicate: A2 < 0, lo < hi, exact g(lo) > 0 and g(hi) > 0 (hence g > 0 on [lo, hi] by concavity)"""
    a2 = F(A2); a1 = F(A1); a0 = F(A0L); g = lambda t: a2 * t * t + a1 * t + a0
    return a2 < 0 and F(lo) < F(hi) and g(F(lo)) > 0 and g(F(hi)) > 0
