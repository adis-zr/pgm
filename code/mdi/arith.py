"""The arithmetic contract: N1 specialization with downward-rounded MPFR points,
explicit error-depth labels, and directed intervals (spec section 3).

Invariant maintained for every computed nonnegative quantity:

    (1-u)^E * v <= vhat <= v,        u = 2^(1-p)

with E=0 for an exact input, E=1 for a downward conversion of a positive
rational, E=max(E1,E2)+1 for a rounded addition, E=E1+E2+1 for a rounded
multiplication (a REUSED operand counts again). Exact power-of-two scaling
leaves E unchanged. Then with lambda = 1 - E*u > 0:

    vhat <= v <= vhat / lambda.

lambda is computed with EXACT Fractions; (1-u)^E is never evaluated.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from gmpy2 import mpfr, mpq

RNDD = gmpy2.RoundDown
RNDU = gmpy2.RoundUp


class NumericalRefusal(Exception):
    """A checked numerical predicate failed. Cost is retained by the caller."""


class DepthOverflow(NumericalRefusal):
    pass


def u_of(p: int) -> Fr:
    """Unit quantity u = 2^(1-p), exact."""
    if p < 2:
        raise ValueError("precision %d too small" % p)
    return Fr(1, 1 << (p - 1))


def lam(E: int, p: int) -> Fr:
    """lambda = 1 - E*u, exact. Must be positive to be usable."""
    if E < 0:
        raise DepthOverflow("negative error depth %d" % E)
    L = Fr(1) - Fr(E) * u_of(p)
    if L <= 0:
        raise DepthOverflow("error depth %d exhausts precision p=%d (lambda<=0)" % (E, p))
    return L


def max_depth_for(p: int, eps: Fr | None = None) -> int:
    """Largest E with E*u <= min(1/2, eps/4) -- the spec's precision predicate."""
    u = u_of(p)
    bound = Fr(1, 2)
    if eps is not None:
        bound = min(bound, Fr(eps) / 4)
    return int(bound / u)


def choose_precision(E_max: int, eps: Fr, p_min: int = 64) -> int:
    """Smallest p >= p_min with E_max * 2^(1-p) <= min(1/2, eps/4). Exact compares."""
    bound = min(Fr(1, 2), Fr(eps) / 4)
    p = p_min
    while p < 4096:
        if Fr(E_max) * u_of(p) <= bound:
            return p
        p += 16
    raise NumericalRefusal("no precision <= 4096 bits satisfies E_max=%d, eps=%s"
                           % (E_max, eps))


class Ctx:
    """MPFR contexts for directed rounding at a fixed precision, with a validated
    exponent range and trap checking."""

    def __init__(self, p: int, emin: int | None = None, emax: int | None = None):
        self.p = p
        self.D = gmpy2.context(precision=p, round=RNDD,
                               trap_divzero=True, trap_invalid=True)
        self.U = gmpy2.context(precision=p, round=RNDU,
                               trap_divzero=True, trap_invalid=True)
        if emin is not None:
            self.D.emin = emin; self.U.emin = emin
        if emax is not None:
            self.D.emax = emax; self.U.emax = emax
        self.emin = self.D.emin
        self.emax = self.D.emax

    # ---- conversions ----
    def down(self, q) -> mpfr:
        """Downward conversion of an exact nonnegative rational. E contribution 1
        for a positive value; exact zero stays exactly zero (E contribution 0)."""
        q = Fr(q)
        if q < 0:
            raise ValueError("negative value in a nonnegative circuit")
        if q == 0:
            return mpfr(0)
        with self.D:
            x = mpfr(mpq(q.numerator, q.denominator))
        self._check(x, q)
        return x

    def up(self, q) -> mpfr:
        q = Fr(q)
        if q < 0:
            raise ValueError("negative value in a nonnegative circuit")
        if q == 0:
            return mpfr(0)
        with self.U:
            x = mpfr(mpq(q.numerator, q.denominator))
        self._check(x, q)
        return x

    def _check(self, x, src=None):
        if gmpy2.is_nan(x):
            raise NumericalRefusal("NaN produced (source %s)" % (src,))
        if gmpy2.is_infinite(x):
            raise NumericalRefusal("infinity produced: exponent range exhausted "
                                   "(source %s)" % (src,))
        if x == 0 and src is not None and Fr(src) != 0:
            raise NumericalRefusal("underflow to zero: exponent range exhausted "
                                   "(source %s)" % (src,))

    # ---- rounded nonnegative operations (point mode, RNDD) ----
    def add_d(self, a, b):
        with self.D:
            r = a + b
        self._check(r)
        return r

    def mul_d(self, a, b):
        with self.D:
            r = a * b
        if gmpy2.is_nan(r) or gmpy2.is_infinite(r):
            raise NumericalRefusal("non-finite product")
        if r == 0 and a != 0 and b != 0:
            raise NumericalRefusal("product underflowed to zero: exponent range exhausted")
        return r

    # ---- interval mode (outward) ----
    def iadd(self, A, B):
        with self.D:
            lo = A[0] + B[0]
        with self.U:
            hi = A[1] + B[1]
        self._check(lo); self._check(hi)
        return (lo, hi)

    def imul(self, A, B):
        """Nonnegative operands only: endpoints multiply directly."""
        with self.D:
            lo = A[0] * B[0]
        with self.U:
            hi = A[1] * B[1]
        self._check(lo); self._check(hi)
        if lo > hi:
            raise NumericalRefusal("inverted interval from multiplication")
        if lo == 0 and A[0] != 0 and B[0] != 0:
            raise NumericalRefusal("interval lower endpoint underflowed")
        return (lo, hi)

    def ienc(self, q):
        """Exact rational -> outward enclosure."""
        return (self.down(q), self.up(q))


def exact_fr(x) -> Fr:
    """Exact Fraction value of an mpfr (mpfr values are dyadic)."""
    return Fr(gmpy2.mpq(x))


# ------------------ final marginal intervals ------------------

def marginal_interval(A, C, L: Fr):
    """Spec's all-marginal formula, evaluated on exact rationals.

    A = stored point count for this state; C = sum of the OTHER stored counts;
    L = lambda_i dominating all their error labels. Returns exact Fractions

        [ L*A / (L*A + C),  A / (A + L*C) ].

    Never computes 1 - qhat (which can erase a positive complement near 1).
    Structural zero/one is exact.
    """
    A = Fr(A); C = Fr(C)
    if A < 0 or C < 0:
        raise ValueError("negative count")
    if A == 0 and C == 0:
        raise NumericalRefusal("all state counts are zero: no normalization")
    if A == 0:
        return (Fr(0), Fr(0))          # structural zero is exact
    if C == 0:
        return (Fr(1), Fr(1))          # structural one is exact
    lo = (L * A) / (L * A + C)
    hi = A / (A + L * C)
    if not (0 <= lo <= hi <= 1):
        raise NumericalRefusal("invalid marginal interval [%s, %s]" % (lo, hi))
    return (lo, hi)


def max_width(L: Fr) -> Fr:
    """Maximum mathematical width (1-L)/(1+L), attained at q=1/2."""
    return (Fr(1) - L) / (Fr(1) + L)


def publish(lo: Fr, hi: Fr, expand: Fr, eps: Fr):
    """Expand each side by `expand`, clip to [0,1], verify width <= eps."""
    p_lo = max(Fr(0), Fr(lo) - expand)
    p_hi = min(Fr(1), Fr(hi) + expand)
    if p_lo > p_hi:
        raise NumericalRefusal("publication inverted")
    if p_hi - p_lo > eps:
        raise NumericalRefusal("published width %s exceeds eps %s" % (p_hi - p_lo, eps))
    return (p_lo, p_hi)


def dyadic_str(q: Fr) -> str:
    """Serialize an exact rational endpoint losslessly as 'num/den'."""
    return "%d/%d" % (Fr(q).numerator, Fr(q).denominator)
