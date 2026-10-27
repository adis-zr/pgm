"""Publication rules (exact rationals; outward to the 2^-64 grid).  Shared scalar module (declared): the checker re-derives its own
interval with the same rule from its own enclosures and tests containment in the producer's published interval."""
from __future__ import annotations

import sys
sys.set_int_max_str_digits(0)

from fractions import Fraction as Fr

G64 = 1 << 64


def floor64(x: Fr) -> Fr: return Fr((x * G64).numerator // (x * G64).denominator, G64)
def ceil64(x: Fr) -> Fr: return -floor64(-x)
def clip01(lo: Fr, hi: Fr): return max(Fr(0), lo), min(Fr(1), hi)


def fx(s: str) -> Fr:
    """parse 'm*2^e' exact dyadic strings written by the native code"""
    m, e = s.split("*2^"); return Fr(int(m)) * (Fr(2) ** int(e))


def publish_direct(q0_lo: Fr, q0_hi: Fr, intrinsic_radius: Fr, pad_numerical: Fr) -> dict:
    """Arm D: [q0_lo - E0 - pad, q0_hi + E0 + pad] rounded outward to 2^-64 (publication rounding <= 2^-64), clipped."""
    lo = floor64(q0_lo - intrinsic_radius - pad_numerical); hi = ceil64(q0_hi + intrinsic_radius + pad_numerical)
    lo, hi = clip01(lo, hi)
    return {"lo": str(lo), "hi": str(hi), "width": str(hi - lo), "width_float": float(hi - lo), "rule": "q0 enclosure +- (intrinsic radius + stored numerical padding), outward to 2^-64, clipped to [0,1]"}


def marker_ratio(Nhat_lo: Fr, Nhat_hi: Fr, Mhat_lo: Fr, Mhat_hi: Fr, eta: Fr) -> dict:
    """Arm F: count intervals N = Nhat +- eta, M = Mhat +- eta intersected with [0, inf); p in [N_L/(N_L+M_U), N_U/(N_U+M_L)] with
    zero handling (denominator 0 -> trivial bound), outward to 2^-64 (<= 1/100000), clipped."""
    NL, NU = max(Fr(0), Nhat_lo - eta), max(Fr(0), Nhat_hi + eta)
    ML, MU = max(Fr(0), Mhat_lo - eta), max(Fr(0), Mhat_hi + eta)
    lo = NL / (NL + MU) if NL + MU > 0 else Fr(0)
    hi = NU / (NU + ML) if NU + ML > 0 else Fr(1)
    lo, hi = clip01(floor64(lo), ceil64(hi))
    return {"lo": str(lo), "hi": str(hi), "width": str(hi - lo), "width_float": float(hi - lo), "N": [str(NL), str(NU)], "M": [str(ML), str(MU)], "eta": str(eta),
            "rule": "p_lower = N_L/(N_L+M_U), p_upper = N_U/(N_U+M_L); counts = finite Fourier estimates +- eta clipped at 0; outward to 2^-64"}
