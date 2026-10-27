"""Directed interval arithmetic on gmpy2 mpfr for the 256-bit enumeration reference and for exact-rational/dyadic conversions.
Every endpoint is rounded in its own direction; exp uses MPFR's correctly rounded directed exp. Not used for the large run (native kernels)."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from gmpy2 import mpfr, mpq

def _ctx(prec, rnd):
    c = gmpy2.get_context().copy(); c.precision = prec; c.round = rnd; c.trap_overflow = c.trap_underflow = c.trap_invalid = c.trap_divzero = True; c.emax = 1 << 20; c.emin = -(1 << 20); return c

class IvCtx:
    def __init__(self, prec):
        self.prec = prec; self.D = _ctx(prec, gmpy2.RoundDown); self.U = _ctx(prec, gmpy2.RoundUp)
    def q(self, x: Fr):
        m = mpq(x.numerator, x.denominator)
        with self.D: lo = mpfr(m)
        with self.U: hi = mpfr(m)
        return Iv(self, lo, hi)
    def ui(self, k): return self.q(Fr(k))

class Iv:
    __slots__ = ("c", "lo", "hi")
    def __init__(self, c, lo, hi):
        self.c = c; self.lo = lo; self.hi = hi
        if not (gmpy2.is_finite(lo) and gmpy2.is_finite(hi) and lo <= hi): raise ValueError(f"invalid interval [{lo},{hi}]")
    def __add__(s, o):
        with s.c.D: lo = s.lo + o.lo
        with s.c.U: hi = s.hi + o.hi
        return Iv(s.c, lo, hi)
    def __sub__(s, o):
        with s.c.D: lo = s.lo - o.hi
        with s.c.U: hi = s.hi - o.lo
        return Iv(s.c, lo, hi)
    def __neg__(s): return Iv(s.c, -s.hi, -s.lo)
    def __mul__(s, o):
        with s.c.D: lo = min(s.lo * o.lo, s.lo * o.hi, s.hi * o.lo, s.hi * o.hi)
        with s.c.U: hi = max(s.lo * o.lo, s.lo * o.hi, s.hi * o.lo, s.hi * o.hi)
        return Iv(s.c, lo, hi)
    def div_pos(s, o):
        if not o.lo > 0: raise ValueError("division by a non-positive interval")
        with s.c.D: lo = (s.lo / o.hi) if s.lo >= 0 else (s.lo / o.lo)
        with s.c.U: hi = (s.hi / o.lo) if s.hi >= 0 else (s.hi / o.hi)
        return Iv(s.c, lo, hi)
    def exp(s):
        with s.c.D: lo = gmpy2.exp(s.lo)
        with s.c.U: hi = gmpy2.exp(s.hi)
        return Iv(s.c, lo, hi)
    def sqrt_pos(s):
        if s.lo < 0: raise ValueError("sqrt of negative")
        with s.c.D: lo = gmpy2.sqrt(s.lo)
        with s.c.U: hi = gmpy2.sqrt(s.hi)
        return Iv(s.c, lo, hi)
    def frac(s): return (fr_of(s.lo), fr_of(s.hi))
    def width(s): return fr_of(s.hi) - fr_of(s.lo)
    def __repr__(s): return f"[{s.lo},{s.hi}]"

def fr_of(x) -> Fr:
    """exact rational value of an mpfr"""
    if x == 0: return Fr(0)
    m, e = x.as_mantissa_exp(); return Fr(int(m)) * (Fr(2) ** int(e))

def fx(s: str) -> Fr:
    """parse the native kernels' exact 'm*2^e' strings"""
    m, e = s.split("*2^"); return Fr(int(m)) * (Fr(2) ** int(e))
