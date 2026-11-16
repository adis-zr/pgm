"""Outward rational enclosures for the transcendental parts of the confidence boundaries (manuscript §6: 'Logs and square roots require outward numerical bounds').
Everything is exact Fraction arithmetic; no floating point enters a certificate. ln_upper(x) >= ln x, sqrt_upper(x) >= sqrt x, boundary_upper(...) >= the ideal radius."""
from fractions import Fraction as F
from math import isqrt

_LN2_LO = F(0); _LN2_HI = F(1)


def _ln2_enclosure(terms=40):
    """ln 2 = 2 atanh(1/3) = 2 sum_{k>=0} (1/3)^(2k+1)/(2k+1); tail <= 2 * (1/3)^(2K+1)/(2K+1) * 1/(1-1/9)"""
    s = F(0); t = F(1, 3); k = 0
    while k < terms: s += t / (2 * k + 1); t /= 9; k += 1
    lo = 2 * s; tail = 2 * (t / (2 * k + 1)) * F(9, 8)
    return lo, lo + tail


_LN2_LO, _LN2_HI = _ln2_enclosure()


PREC = 128


def dyadic_up(x, prec=PREC):
    """smallest dyadic k / 2^prec' >= x with a bounded mantissa (prec bits): outward rounding of a (possibly huge) rational"""
    x = F(x)
    if x == 0: return x
    e = x.numerator.bit_length() - x.denominator.bit_length() - prec
    if e > 0: q = (x.numerator + (x.denominator << e) - 1) // (x.denominator << e); return F(q << e)
    q = -(-(x.numerator << -e) // x.denominator); return F(q, 1 << -e)


def dyadic_down(x, prec=PREC):
    x = F(x)
    if x == 0: return x
    e = x.numerator.bit_length() - x.denominator.bit_length() - prec
    if e > 0: return F((x.numerator // (x.denominator << e)) << e)
    return F((x.numerator << -e) // x.denominator, 1 << -e)


def ln_bounds(x, terms=24):
    """(lower, upper) rational enclosure of ln x for a Fraction x > 0: x = y 2^k with y in (1, 2]; y is enclosed by PREC-bit dyadics (ln is monotone), ln y by the
    atanh series with its tail bound, ln 2 by its own enclosure; every step outward."""
    x = F(x)
    if x <= 0: raise ValueError('ln of a nonpositive number')
    if x == 1: return F(0), F(0)
    if x < 1: lo, hi = ln_bounds(1 / x, terms); return -hi, -lo
    k = x.numerator.bit_length() - x.denominator.bit_length()          # 2^(k-1) < x < 2^(k+1)
    y = x / F(1 << k) if k >= 0 else x * F(1 << -k)
    while y > 2: y /= 2; k += 1
    while y <= 1: y *= 2; k -= 1
    def series_bounds(u):                                               # ln y = 2 atanh(u), u = (y-1)/(y+1) in (0, 1/3]
        s_ = F(0); t = u; i = 0
        while i < terms: s_ += t / (2 * i + 1); t *= u * u; i += 1
        return 2 * s_, 2 * s_ + 2 * (t / (2 * i + 1)) / (1 - u * u)
    y_lo = dyadic_down(y); y_hi = dyadic_up(y)
    lo = series_bounds((y_lo - 1) / (y_lo + 1))[0] if y_lo > 1 else F(0); hi = series_bounds((y_hi - 1) / (y_hi + 1))[1]
    return (lo + k * _LN2_LO, hi + k * _LN2_HI) if k >= 0 else (lo + k * _LN2_HI, hi + k * _LN2_LO)


def ln_bounds_series(x, terms=24): return ln_bounds(x, terms)      # the series enclosure (kept as the independent cross-check of the Decimal route)


from decimal import Decimal, getcontext, ROUND_FLOOR, ROUND_CEILING
DEC_PREC = 60


def _dec_frac(d):
    """exact Fraction of a Decimal"""
    sign, digits, exp = d.as_tuple(); n = int(''.join(map(str, digits)) or '0')
    f = F(n) * (F(10) ** exp) if exp >= 0 else F(n, 10 ** (-exp))
    return -f if sign else f


def ln_bounds_decimal(x):
    """(lower, upper) enclosure of ln x via Decimal.ln (correctly rounded to DEC_PREC digits, documented ROUND_HALF_EVEN): ln x = ln p - ln q for x = p/q; each term is within
    half an ulp of its own magnitude; the difference is widened by one ulp of each term plus one ulp of the result (outward); converted exactly to Fractions"""
    x = F(x)
    if x <= 0: raise ValueError('ln of a nonpositive number')
    if x == 1: return F(0), F(0)
    ctx = getcontext(); old = ctx.prec; ctx.prec = DEC_PREC
    try:
        lp = Decimal(x.numerator).ln() if x.numerator != 1 else Decimal(0); lq = Decimal(x.denominator).ln() if x.denominator != 1 else Decimal(0); d = lp - lq
        def ulp(v): return Decimal(1).scaleb(v.adjusted() - DEC_PREC + 1) if v != 0 else Decimal(0)
        m = ulp(lp) + ulp(lq) + ulp(d) + Decimal(1).scaleb(-DEC_PREC + 5)
        lo = _dec_frac(d - m); hi = _dec_frac(d + m)
    finally: ctx.prec = old
    return lo, hi


def ln_upper(x): return ln_bounds_decimal(x)[1]


def sqrt_upper_decimal(x):
    """upper bound of sqrt(x) via Decimal.sqrt (correctly rounded): result + one ulp"""
    x = F(x)
    if x < 0: raise ValueError('sqrt of a negative number')
    if x == 0: return F(0)
    ctx = getcontext(); old = ctx.prec; ctx.prec = DEC_PREC
    try:
        d = (Decimal(x.numerator) / Decimal(x.denominator)); dx = _dec_frac(d)
        # division rounding: widen x upward by 2 ulps before the root
        d_up = d + Decimal(1).scaleb(d.adjusted() - DEC_PREC + 2); r = d_up.sqrt(); r_up = r + Decimal(1).scaleb(r.adjusted() - DEC_PREC + 2)
        out = _dec_frac(r_up)
    finally: ctx.prec = old
    return out


def sqrt_upper(x, digits=40):
    """rational upper bound of sqrt(x) for x >= 0: ceil of the integer square root on a 10^(2 digits) grid (huge inputs are first rounded up to a PREC-bit dyadic)"""
    x = dyadic_up(F(x))
    if x < 0: raise ValueError('sqrt of a negative number')
    if x == 0: return F(0)
    S = 10 ** digits; N = (x * S * S).numerator; D = (x * S * S).denominator
    r = isqrt(N // D) + 1          # (r)^2 > N/D >= x S^2  ->  r/S > sqrt(x)
    return F(r, S)


def sqrt_lower(x, digits=40):
    x = dyadic_down(F(x))
    if x <= 0: return F(0)
    S = 10 ** digits; N = (x * S * S).numerator; D = (x * S * S).denominator
    return F(isqrt(N // D), S)


def boundary_upper(rho, V, alpha):
    """upper enclosure of sqrt((rho + V) log((rho + V) / (rho alpha^2))) -- the normal-mixture all-time boundary (manuscript (5), Theorem 6.2)"""
    rho = F(rho); V = F(V); alpha = F(alpha); a = rho + V; arg = a / (rho * alpha * alpha)
    if arg <= 1: return F(0)
    return sqrt_upper_decimal(a * ln_upper(arg))
