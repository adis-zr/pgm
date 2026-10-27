"""Exact rational scalar constants and inequalities (declared shared between producer wrapper and checker; pure Fraction arithmetic,
no inference).  Reproduces docs/direct-query-theory-pass-2026-10-26/{witness_response_constants.py, check_additional_constants.py}
from the INPUT rather than from literal family values, so a mislabelled input cannot pass."""
from __future__ import annotations

import sys
from fractions import Fraction as Fr

sys.set_int_max_str_digits(0)


def ceil_dyadic(x: Fr, bits: int = 128) -> Fr:
    """Smallest multiple of 2^-bits that is >= x (compact OUTWARD representative of a huge-denominator rational upper bound)."""
    g = 1 << bits; return Fr(-((-x * g).numerator // (x * g).denominator), g)


def exp_lower(x: Fr, order: int = 80) -> Fr:
    """Rational lower bound for exp(x), x >= 0 (finite Taylor sum)."""
    term = total = Fr(1)
    for k in range(1, order + 1):
        term *= x / k
        total += term
    return total


def exp_upper(x: Fr, order: int = 80) -> Fr:
    """Rational upper bound for exp(x), 0 <= x < order+2 (Taylor sum + geometric remainder)."""
    assert 0 <= x < order + 2
    term = Fr(1)
    for k in range(1, order + 2):
        term *= x / k
    return exp_lower(x, order) + term / (1 - x / (order + 2))


def exp_neg_lower(x: Fr) -> Fr:
    """Rational lower bound for exp(-x), x >= 0: 1/exp_upper(x)."""
    return 1 / exp_upper(x)


def exp_neg_upper(x: Fr) -> Fr:
    return 1 / exp_lower(x)


def sqrt_lower(x: Fr, bits: int = 128) -> Fr:
    """Rational lower bound for sqrt(x), x >= 0, on the 2^-bits grid."""
    from math import isqrt
    num = x.numerator << (2 * bits); den = x.denominator
    r = isqrt(num // den)               # floor(sqrt(num/den)) <= sqrt
    return Fr(r, 1 << bits)


def sqrt_upper(x: Fr, bits: int = 128) -> Fr:
    return sqrt_lower(x, bits) + Fr(1, 1 << bits)


PI_LOWER = Fr(3141592653589793238462643383279, 10 ** 30)          # 3.14159265358979323846264338327 < pi
PI_UPPER = Fr(3141592653589793238462643383280, 10 ** 30)


def contraction_two_state(f: Fr) -> Fr:
    """tau for the two-state kernel [[f,1],[1,f]], f > 0: cross ratio R = f^2 (or 1/f^2), tau = (sqrt R - 1)/(sqrt R + 1) = |f-1|/(f+1).
    Exact (no square root needed because sqrt(f^2) = f).  Matches further/08_residual_certificates.md eq. (1)."""
    return abs(f - 1) / (f + 1)


def alias_upper(h: Fr, r: Fr, V: Fr) -> Fr:
    """Upper bound on the Poisson-alias error  2 sum_{l>=1} exp[-(2 pi l/h - r)^2 / (2(1+V))]  (scalar_fourier_baseline.md eq. 2),
    using pi > PI_LOWER, the first term exactly bounded and a geometric tail with the minimal exponent gap."""
    P = 2 * PI_LOWER / h                                # lower bound on the alias period 2 pi/h
    assert P > r
    x1 = (P - r) ** 2 / (2 * (1 + V))                   # first exponent (l = 1), lower bound
    x2 = (2 * P - r) ** 2 / (2 * (1 + V))
    d = x2 - x1                                         # exponent increments are increasing in l, so gap >= d
    assert d > 0
    return ceil_dyadic(2 * exp_neg_upper(x1) / (1 - exp_neg_upper(d)))


def truncation_upper(h: Fr, J: int) -> Fr:
    """Upper bound on  (2h/sqrt(2 pi)) sum_{k>=J+1} exp(-(kh)^2/2)  (eq. 3), with 2/sqrt(2 pi) <= 2/sqrt(2*PI_LOWER) bounded above."""
    pref = 2 * h / sqrt_lower(2 * PI_LOWER)
    x1 = ((J + 1) * h) ** 2 / 2
    x2 = ((J + 2) * h) ** 2 / 2
    return ceil_dyadic(pref * exp_neg_upper(x1) / (1 - exp_neg_upper(x2 - x1)))


def fourier_count_width_bounds(eta: Fr, L: Fr):
    """Conservative width 4 eta/(L - 2 eta) (eq. 6) and the sharp marker-ratio width 2 eta/(L - 2 eta) (section 5), both requiring L > 2 eta."""
    assert L > 2 * eta
    return 4 * eta / (L - 2 * eta), 2 * eta / (L - 2 * eta)
