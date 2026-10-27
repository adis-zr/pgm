"""Frozen certificate formulas (CLAUDE_CODE_SPEC.md §5) in exact rational arithmetic with rigorous rational bounds for exp and sqrt.
R_old(M) = 2 q(1-q) s exp((M-1)/2)    (max of q(1-q) over the certified q interval, interior maximum 1/4 included when it contains 1/2)
R_new(M) = (5/4) (alpha sqrt(M) + 2 alpha^2)
Decisions: PASS  — outward published UNCLIPPED width <= 1/100 and independent checking succeeds
           DECLINE — lower enclosure of the ideal padded width > 1/100
           UNRESOLVED — otherwise (straddle / contract failure / inconclusive checking)."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from math import isqrt

WIDTH_TARGET = Fr(1, 100); DELTA_NUM = Fr(1, 16000); DELTA_PUB = Fr(1, 16000); PADS = 2 * (DELTA_NUM + DELTA_PUB)
Q_WIDTH_MAX = Fr(1, 8000)

def exp_lower(x: Fr, order=60) -> Fr:
    """rational lower bound of exp(x) for any rational x (|x| <= 8 in use): Taylor for x>=0; 1/exp_upper(-x) for x<0"""
    if x < 0: return 1 / exp_upper(-x, order)
    s = t = Fr(1)
    for k in range(1, order + 1): t = t * x / k; s += t
    return s

def exp_upper(x: Fr, order=60) -> Fr:
    if x < 0: return 1 / exp_lower(-x, order)
    assert x < order + 2
    s = t = Fr(1)
    for k in range(1, order + 1): t = t * x / k; s += t
    tail = t * x / (order + 1) / (1 - x / (order + 2))      # geometric tail bound
    return s + tail

def sqrt_lower(x: Fr, bits=128) -> Fr:
    assert x >= 0; num = x.numerator << (2 * bits); return Fr(isqrt(num // x.denominator), 1 << bits)
def sqrt_upper(x: Fr, bits=128) -> Fr:
    return sqrt_lower(x, bits) + Fr(1, 1 << bits)

def q1q_range(q_lo: Fr, q_hi: Fr):
    """[min, max] of q(1-q) over [q_lo, q_hi] ⊂ [0,1] (interior maximum 1/4 included when the interval contains 1/2)"""
    ends = [q_lo * (1 - q_lo), q_hi * (1 - q_hi)]
    mx = Fr(1, 4) if q_lo <= Fr(1, 2) <= q_hi else max(ends)
    return min(ends), mx

def R_old_range(q_lo, q_hi, s_lo, s_hi, M_lo, M_hi):
    """enclosure of 2 q(1-q) s exp((M-1)/2) over the ranges (all factors nonnegative, exp monotone)"""
    a, b = q1q_range(q_lo, q_hi)
    return 2 * a * max(s_lo, 0) * exp_lower((M_lo - 1) / 2), 2 * b * s_hi * exp_upper((M_hi - 1) / 2)

def R_new_range(alpha_lo, alpha_hi, M_lo, M_hi):
    al = max(alpha_lo, 0)
    return Fr(5, 4) * (al * sqrt_lower(M_lo) + 2 * al * al), Fr(5, 4) * (alpha_hi * sqrt_upper(M_hi) + 2 * alpha_hi * alpha_hi)

def publication(qhat: Fr, R_upper: Fr):
    lo, hi = qhat - R_upper - DELTA_NUM - DELTA_PUB, qhat + R_upper + DELTA_NUM + DELTA_PUB
    return {"unclipped": (lo, hi), "clipped": (max(Fr(0), lo), min(Fr(1), hi)), "unclipped_width": hi - lo}

def classify(R_lo: Fr, R_hi: Fr, checker_ok: bool, contract_ok: bool):
    """ideal padded width enclosure W = 2R + PADS over [R_lo, R_hi]; published unclipped width = 2 R_hi + PADS"""
    W_lo, W_hi = 2 * R_lo + PADS, 2 * R_hi + PADS
    if not contract_ok: status = "UNRESOLVED"; reason = "width_contract_or_domain_failure"
    elif W_hi <= WIDTH_TARGET and checker_ok: status = "PASS"; reason = "published_unclipped_width_le_1/100_and_checked"
    elif W_hi <= WIDTH_TARGET and not checker_ok: status = "UNRESOLVED"; reason = "width_ok_but_independent_check_failed"
    elif W_lo > WIDTH_TARGET: status = "DECLINE"; reason = "ideal_padded_width_lower_bound_gt_1/100"
    else: status = "UNRESOLVED"; reason = "width_enclosure_straddles_1/100"
    return {"status": status, "reason": reason, "ideal_padded_width_enclosure": (W_lo, W_hi), "published_unclipped_width": W_hi,
            "R_enclosure": (R_lo, R_hi), "width_target": WIDTH_TARGET}

def residual_sq_upper(gradient_pairs):
    """Σ_j max(|g_lo|,|g_hi|)^2 — exact on dyadic endpoints; the frozen admission test compares it with 1/256"""
    return sum(max(abs(lo), abs(hi)) ** 2 for lo, hi in gradient_pairs)

def fr_str(x: Fr) -> str: return f"{x.numerator}/{x.denominator}"
def dec(x: Fr, d=12) -> str:
    sgn = "-" if x < 0 else ""; x = abs(x); ip = x.numerator // x.denominator; fp = x - ip
    digits = (fp.numerator * 10 ** d) // fp.denominator; return f"{sgn}{ip}.{digits:0{d}d}"
