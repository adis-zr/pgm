"""Rigorous arithmetic helpers for the PAC engine: outward-rounded intervals on gmpy2 mpfr (128-bit) for the accumulated statistics, exact rational sqrt bounds,
and the two confidence boundaries. Every function documents its rounding direction. No interval is ever narrowed by an unchecked float operation."""
import gmpy2
from gmpy2 import mpfr, mpq
from fractions import Fraction as F
import math
PREC = 128
_UP = gmpy2.context(precision=PREC, round=gmpy2.RoundUp); _DN = gmpy2.context(precision=PREC, round=gmpy2.RoundDown)


def to_q(x):
    if isinstance(x, F): return mpq(x.numerator, x.denominator)
    if isinstance(x, int): return mpq(x)
    return x


class IV:
    """closed interval [lo, hi] of mpfr with outward rounding; constructed from exact rationals or other IVs"""
    __slots__ = ('lo', 'hi')
    def __init__(self, lo, hi=None):
        if hi is None: hi = lo
        if isinstance(lo, (F, int)):
            q = to_q(lo)
            with _DN: self.lo = mpfr(q)
            with _UP: self.hi = mpfr(to_q(hi)) if not isinstance(hi, IV) else hi.hi
            if not isinstance(hi, (F, int)) and not isinstance(hi, IV): self.hi = hi
            elif isinstance(hi, (F, int)):
                with _UP: self.hi = mpfr(to_q(hi))
        else: self.lo = lo; self.hi = hi
        assert self.lo <= self.hi, (self.lo, self.hi)
    @staticmethod
    def exact(q): return IV(q, q)
    def __add__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        with _DN: lo = self.lo + o.lo
        with _UP: hi = self.hi + o.hi
        return IV._raw(lo, hi)
    def __sub__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        with _DN: lo = self.lo - o.hi
        with _UP: hi = self.hi - o.lo
        return IV._raw(lo, hi)
    def __mul__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        with _DN: cl = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
        with _UP: ch = [self.lo * o.lo, self.lo * o.hi, self.hi * o.lo, self.hi * o.hi]
        return IV._raw(min(cl), max(ch))
    def __truediv__(self, o):
        o = o if isinstance(o, IV) else IV(o)
        if not (o.lo > 0 or o.hi < 0): raise ZeroDivisionError('interval divisor contains zero')
        with _DN: cl = [self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi]
        with _UP: ch = [self.lo / o.lo, self.lo / o.hi, self.hi / o.lo, self.hi / o.hi]
        return IV._raw(min(cl), max(ch))
    def sq(self):
        if self.lo >= 0: return self * self
        if self.hi <= 0: return IV._raw(min((self * self).lo, 0 * self.lo), (self * self).hi)
        m = max(-self.lo, self.hi)
        with _UP: hi = m * m
        return IV._raw(mpfr(0), hi)
    @staticmethod
    def _raw(lo, hi):
        iv = IV.__new__(IV); iv.lo = lo; iv.hi = hi; return iv
    def frac(self):
        """exact rational enclosure (the mpfr endpoints are dyadic rationals: exact conversion)"""
        return (F(gmpy2.mpq(self.lo)) if gmpy2.is_finite(self.lo) else None, F(gmpy2.mpq(self.hi)) if gmpy2.is_finite(self.hi) else None)
    def __repr__(self): return 'IV[%s, %s]' % (float(self.lo), float(self.hi))


def isqrt_lo(n):
    """floor(sqrt(n)) for a nonnegative int"""
    return math.isqrt(n)


def sqrt_bounds(q, bits=128):
    """exact rational bounds lo <= sqrt(q) <= hi for a nonnegative rational q, with relative gap <= 2^-bits"""
    q = F(q)
    if q < 0: raise ValueError('sqrt of negative')
    if q == 0: return F(0), F(0)
    s = 1 << (2 * bits); n = q.numerator * s; d = q.denominator
    # sqrt(q) = sqrt(n/d) = sqrt(n*d)/d
    r = math.isqrt(n * d); lo = F(r, d << bits); hi = F(r + 1, d << bits)
    return lo, hi


def log_up(x_hi):
    """upper bound on log(x) for a rational/mpfr x >= x_hi's value (round-up mpfr)"""
    with _UP: return gmpy2.log(mpfr(to_q(x_hi)) if isinstance(x_hi, (F, int)) else x_hi)


def range_boundary_up(rho, V_hi, alpha):
    """b(V, alpha) = sqrt((rho+V) log((rho+V)/(rho alpha^2))) rounded UP (exact rational inputs; mpfr round-up for log and sqrt). V_hi is an upper bound on V
    (b increases in V); alpha the per-coordinate failure allowance. Returns an exact rational upper bound."""
    rho = F(rho); V = F(V_hi); alpha = F(alpha); s = rho + V; arg = s / (rho * alpha * alpha)
    if arg <= 1: return F(0)
    with _UP:
        L = gmpy2.log(mpfr(to_q(arg)))
        prod = mpfr(to_q(s)) * L
        root = gmpy2.sqrt(prod)
    return F(gmpy2.mpq(root))


def psi(lam):
    """psi(lambda) = -log(1-lambda) - lambda as an exact rational (LOWER, UPPER) bound pair for dyadic lambda in (0,1). Directed rounding with the NEGATION handled
    explicitly: an upper bound of -log(x) is the negation of a LOWER bound of log(x) (negation is exact), then the subtraction of lambda is rounded in the wanted direction."""
    lam = F(lam); x = to_q(1 - lam)
    with _DN: log_lo = gmpy2.log(mpfr(x))
    with _UP: log_hi = gmpy2.log(mpfr(x))
    with _UP: hi = (-log_lo) - mpfr(to_q(lam))          # -log_lo >= -log(x); the subtraction rounds up
    with _DN: lo = (-log_hi) - mpfr(to_q(lam))          # -log_hi <= -log(x); the subtraction rounds down
    return F(gmpy2.mpq(lo)), F(gmpy2.mpq(hi))


def log_threshold_up(K, delta_c, omega_l):
    """log(2K/(delta omega_l)) rounded up, exact rational"""
    with _UP: v = gmpy2.log(mpfr(to_q(F(2 * K) / (F(delta_c) * F(omega_l)))))
    return F(gmpy2.mpq(v))


def quad_roots_outer(A, Bc, Cc):
    """for the quadratic A t^2 + B t + C with exact rational coefficients, return the OUTER rational enclosures of its real roots (lo1, hi1), (lo2, hi2) or None if
    no real root; used to bound rejection intervals from the inside (a rejection interval is shrunk to be safe)"""
    disc = Bc * Bc - 4 * A * Cc
    if disc < 0: return None
    slo, shi = sqrt_bounds(disc)
    if A > 0:
        r1 = ((-Bc - shi) / (2 * A), (-Bc - slo) / (2 * A)); r2 = ((-Bc + slo) / (2 * A), (-Bc + shi) / (2 * A))
    else:
        r1 = ((-Bc + slo) / (2 * A), (-Bc + shi) / (2 * A)); r2 = ((-Bc - shi) / (2 * A), (-Bc - slo) / (2 * A))
        r1, r2 = (min(r1[0], r2[0]), min(r1[1], r2[1])), (max(r1[0], r2[0]), max(r1[1], r2[1]))
    return r1, r2


# ---------------- fast directed-rounding quadratic inversion (mpfr 128-bit, correctly rounded; the rejected interval is SHRUNK by rounding its endpoints inward)
def shrunk_rejection(A2, A1, A0L):
    """for the concave quadratic g(t) = A2 t^2 + A1 t + A0L (A2 < 0, exact rationals or mpfr), return the OPEN interval strictly between its roots, SHRUNK (lower root
    rounded UP, upper root rounded DOWN) so that every t in the returned interval certainly has g(t) > 0; None if no real root. Directed rounding via gmpy2 contexts:
    each operation is correctly rounded in the stated direction, so the enclosures are rigorous."""
    a2 = to_q(A2); a1 = to_q(A1); a0 = to_q(A0L)
    with _DN: disc_lo = mpfr(a1) * mpfr(a1) - mpfr(4) * mpfr(a2) * mpfr(a0)      # a1^2 rounded down, 4 a2 a0 is NEGATIVE*? (a2<0, a0 sign free): compute both bounds explicitly below
    with _UP: t1 = mpfr(a1) * mpfr(a1)
    with _DN: t1d = mpfr(a1) * mpfr(a1)
    # 4 a2 a0: outer bounds
    with _UP: p_hi = mpfr(4) * mpfr(a2) * mpfr(a0)
    with _DN: p_lo = mpfr(4) * mpfr(a2) * mpfr(a0)
    with _DN: disc_lo = t1d - p_hi
    with _UP: disc_hi = t1 - p_lo
    if disc_hi < 0: return None
    if disc_lo < 0: disc_lo = mpfr(0)
    with _DN: s_lo = gmpy2.sqrt(disc_lo)
    with _UP: s_hi = gmpy2.sqrt(disc_hi)
    # roots: (-a1 -/+ s)/(2 a2) with a2 < 0: lower root = (-a1 + s)/(2 a2) ... careful: 2a2 < 0 flips order. r_minus = (-a1 - s)/(2a2) = (a1 + s)/(-2a2) [larger]; r_plus = (a1 - s)/(-2 a2) [smaller]
    with _UP: den_hi = mpfr(-2) * mpfr(a2)
    with _DN: den_lo = mpfr(-2) * mpfr(a2)
    a1u = None
    with _UP: lo_root_up = (mpfr(a1) - s_lo) / den_lo if (mpfr(a1) - s_lo) >= 0 else (mpfr(a1) - s_lo) / den_hi          # smaller root rounded UP
    with _DN: hi_root_dn = (mpfr(a1) + s_lo) / den_hi if (mpfr(a1) + s_lo) >= 0 else (mpfr(a1) + s_lo) / den_lo          # larger root rounded DOWN
    if not (lo_root_up < hi_root_dn): return None
    return F(gmpy2.mpq(lo_root_up)), F(gmpy2.mpq(hi_root_dn))
