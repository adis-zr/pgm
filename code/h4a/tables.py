"""Directed-MPFR construction and exact certification of the stochastic FFBS tables, complex phases and Fourier weights.

All enclosures use gmpy2/MPFR with explicit precision and RNDD/RNDU per endpoint; every acceptance predicate is an EXACT
rational/dyadic inequality (NUMERICAL_THEOREM.md §2, TABLES_AND_DOMAIN.md).

Probability rows (eq. 3): dyadic mesh 2^-53, floor the certified LOWER endpoints of the first m-1 allowed entries, exact
integer remainder to the last allowed entry; forbidden states exact zero; row sum exactly 1 as integers; L1 error <= 2^-48.
Phases  (eq. 4): certified midpoint, shrink by (1 - 2^-50), quantize both components to the 2^-53 mesh with ties-to-even;
exact squared norm <= 1; sum of the two componentwise endpoint distances <= 2^-48.  Zero frequency exactly (1,0).
Weights (eq. 5): nearest binary64; nonnegative; true and stored sums <= 2; total L1 error <= 2^-48.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from gmpy2 import mpfr, mpq

EPS_P = Fr(1, 1 << 48); EPS_PHI = Fr(1, 1 << 48); EPS_LAM = Fr(1, 1 << 48)
MESH = 1 << 53; SHRINK = Fr((1 << 50) - 1, 1 << 50)

def ctx(prec, rnd):
    c = gmpy2.get_context().copy(); c.precision = prec; c.round = rnd
    c.emin, c.emax = -16384, 16384
    c.trap_overflow = c.trap_underflow = c.trap_invalid = c.trap_divzero = True
    return c

class MP:
    """directed interval arithmetic at one precision; every endpoint rounded in its own direction"""
    def __init__(self, prec):
        self.prec = prec; self.D = ctx(prec, gmpy2.RoundDown); self.U = ctx(prec, gmpy2.RoundUp)
    def q(self, x: Fr):
        m = mpq(x.numerator, x.denominator)
        with self.D: lo = mpfr(m)
        with self.U: hi = mpfr(m)
        return (lo, hi)
    def add(self, a, b):
        with self.D: lo = a[0] + b[0]
        with self.U: hi = a[1] + b[1]
        return (lo, hi)
    def mul_pos(self, a, b):
        with self.D: lo = a[0] * b[0]
        with self.U: hi = a[1] * b[1]
        return (lo, hi)
    def mul(self, a, b):
        with self.D: lo = min(a[0]*b[0], a[0]*b[1], a[1]*b[0], a[1]*b[1])
        with self.U: hi = max(a[0]*b[0], a[0]*b[1], a[1]*b[0], a[1]*b[1])
        return (lo, hi)
    def div_pos(self, a, b):
        """a / b with a of ANY sign and b strictly positive. The numerator sign case-split is mandatory: with a
        negative numerator the extreme quotients come from the OPPOSITE divisor endpoints. Omitting it returns an
        inverted interval that can exclude the true value (review finding 3)."""
        if not b[0] > 0: raise ValueError("div_pos requires a strictly positive divisor")
        with self.D: lo = (a[0] / b[1]) if a[0] >= 0 else (a[0] / b[0])
        with self.U: hi = (a[1] / b[0]) if a[1] >= 0 else (a[1] / b[1])
        if not lo <= hi: raise ValueError("div_pos produced an inverted interval")
        return (lo, hi)
    def exp(self, a):
        with self.D: lo = gmpy2.exp(a[0])
        with self.U: hi = gmpy2.exp(a[1])
        return (lo, hi)
    def sqrt(self, a):
        assert a[0] >= 0
        with self.D: lo = gmpy2.sqrt(a[0])
        with self.U: hi = gmpy2.sqrt(a[1])
        return (lo, hi)
    def scale2(self, a, e):
        """Exact power-of-two scaling of both endpoints, done on the EXACT rational values and converted back in the
        endpoint's own direction. gmpy2.mul_2exp/div_2exp operate at the ambient context precision, which collapsed the
        interval to a point and silently destroyed the enclosure; this routine cannot do that. A power-of-two shift of a
        binary float is exact in-range, so the reconversion is exact and the width scales by exactly 2^e."""
        lo_q = fr(a[0]) * (Fr(2) ** e); hi_q = fr(a[1]) * (Fr(2) ** e)
        with self.D: lo = mpfr(mpq(lo_q.numerator, lo_q.denominator))
        with self.U: hi = mpfr(mpq(hi_q.numerator, hi_q.denominator))
        if fr(lo) != lo_q or fr(hi) != hi_q: raise ValueError("power-of-two scaling was not exact (exponent range)")
        if not lo <= hi: raise ValueError("scaling produced an inverted interval")
        return (lo, hi)
    def cos_sin(self, a):
        """outward rectangle for (cos, sin) over the interval a, including interior extrema (cos at k*pi, sin at pi/2+k*pi)"""
        from h4a.grid import PI_LO, PI_HI
        lo_f, hi_f = fr(a[0]), fr(a[1])
        def ends(f):
            with self.D: v0 = f(a[0]); v1 = f(a[1])
            with self.U: w0 = f(a[0]); w1 = f(a[1])
            return min(v0, v1), max(w0, w1)
        c = list(ends(gmpy2.cos)); s = list(ends(gmpy2.sin))
        # cos extrema at k*pi -> value (-1)^k ; sin extrema at (k+1/2)*pi -> value (-1)^k
        kmin = (lo_f / PI_HI); kmax = (hi_f / PI_LO)
        k0 = int(kmin) - 2; k1 = int(kmax) + 2
        for k in range(k0, k1 + 1):
            lo_k, hi_k = k * PI_LO, k * PI_HI
            if k < 0: lo_k, hi_k = k * PI_HI, k * PI_LO
            if lo_f <= hi_k and lo_k <= hi_f:                      # k*pi may lie inside -> cos hits (-1)^k
                v = 1 if k % 2 == 0 else -1
                if v > 0: c[1] = max(c[1], mpfr(1))
                else: c[0] = min(c[0], mpfr(-1))
            lo_h, hi_h = (k + Fr(1, 2)) * PI_LO, (k + Fr(1, 2)) * PI_HI
            if k + Fr(1,2) < 0: lo_h, hi_h = (k + Fr(1,2)) * PI_HI, (k + Fr(1,2)) * PI_LO
            if lo_f <= hi_h and lo_h <= hi_f:
                v = 1 if k % 2 == 0 else -1
                if v > 0: s[1] = max(s[1], mpfr(1))
                else: s[0] = min(s[0], mpfr(-1))
        c[0] = max(c[0], mpfr(-1)); c[1] = min(c[1], mpfr(1)); s[0] = max(s[0], mpfr(-1)); s[1] = min(s[1], mpfr(1))
        return (c[0], c[1]), (s[0], s[1])

def fr(x) -> Fr:
    """exact rational value of an mpfr"""
    if x == 0: return Fr(0)
    m, e = x.as_mantissa_exp(); return Fr(int(m)) * (Fr(2) ** int(e))

def floor_mesh(x: Fr) -> int: return (x * MESH).numerator // (x * MESH).denominator
def round_mesh_ties_even(x: Fr) -> int:
    y = x * MESH; n, d = y.numerator, y.denominator
    q, r = divmod(n, d)
    if 2 * r > d: return q + 1
    if 2 * r < d: return q
    return q if q % 2 == 0 else q + 1       # ties to even

# ---------------- probability rows ----------------
def store_row(enclosures, allowed_idx, m_total):
    """enclosures: list of (lo,hi) Fr for each ALLOWED state in declared order; returns (ints over 2^53, exact L1 bound).
    Floors the lower endpoints of all but the last allowed entry; the last gets the exact remainder."""
    ints = [0] * m_total
    acc = 0
    for j, idx in enumerate(allowed_idx[:-1]):
        v = max(0, floor_mesh(enclosures[j][0])); ints[idx] = v; acc += v
    last = allowed_idx[-1]; ints[last] = MESH - acc
    assert sum(ints) == MESH, "row must sum to exactly one"
    assert ints[last] >= 0, "remainder negative: construction precision insufficient"
    # exact L1 bound: sum over allowed of max(|stored - lo|, |stored - hi|)
    l1 = Fr(0)
    for j, idx in enumerate(allowed_idx):
        lo, hi = enclosures[j]; st = Fr(ints[idx], MESH)
        l1 += max(abs(st - lo), abs(st - hi))
    return ints, l1

# ---------------- phases ----------------
def store_phase(c_iv, s_iv):
    """c_iv, s_iv: exact (lo,hi) Fr enclosures of cos/sin. Returns ((cr,ci) ints over 2^53, exact L1 error bound)."""
    cm = (c_iv[0] + c_iv[1]) / 2; sm = (s_iv[0] + s_iv[1]) / 2
    cr = round_mesh_ties_even(cm * SHRINK); ci = round_mesh_ties_even(sm * SHRINK)
    sc, ss = Fr(cr, MESH), Fr(ci, MESH)
    assert sc * sc + ss * ss <= 1, "stored phase must lie in the closed unit disk"
    err = max(abs(sc - c_iv[0]), abs(sc - c_iv[1])) + max(abs(ss - s_iv[0]), abs(ss - s_iv[1]))
    return (cr, ci), err

def exact_phase_one(): return (MESH, 0), Fr(0)      # zero frequency: exactly (1,0)
