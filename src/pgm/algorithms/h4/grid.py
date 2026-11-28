"""Frozen frequency grid binding + exact alias/tail recertification (H4_DEFINITION.md §4 'For replay'; FROZEN_NODES.json).

Representatives, frozen order: k2 = 0..J2, k3 = -J3..J3, retaining k2>0 or (k2==0 and k3>=0); multiplicity 2 except (0,0) -> 1.
lambda_k = m_k * h2*h3/(2*pi) * exp(-((h2 k2)^2 + (h3 k3)^2)/2).
delta_comp = d2 + d3 + d2*d3 with d_l = A(h_l) + T(h_l,J_l); recertified against FROZEN_NODES:analytic_delta_comp_exact."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

def exp_lower(x: Fr, order: int = 120) -> Fr:
    if x < 0: return 1 / exp_upper(-x, order)
    s = t = Fr(1)
    for k in range(1, order + 1): t = t * x / k; s += t
    return s

def exp_upper(x: Fr, order: int = 120) -> Fr:
    if x < 0: return 1 / exp_lower(-x, order)
    assert x < order + 2
    s = t = Fr(1)
    for k in range(1, order + 1): t = t * x / k; s += t
    return s + t * x / (order + 1) / (1 - x / (order + 2))

def sqrt_lower(x: Fr, bits: int = 160) -> Fr:
    from math import isqrt
    assert x >= 0
    return Fr(isqrt((x.numerator << (2 * bits)) // x.denominator), 1 << bits)
def sqrt_upper(x: Fr, bits: int = 160) -> Fr: return sqrt_lower(x, bits) + Fr(1, 1 << bits)

PI_LO = Fr(31415926535897932384626433832795028841971693993751, 10 ** 49)
PI_HI = Fr(31415926535897932384626433832795028841971693993752, 10 ** 49)
# guard against a digit-count slip in the constants above (this exact bug occurred once during implementation)
assert Fr(314, 100) < PI_LO < PI_HI < Fr(315, 100) and PI_LO < PI_HI
assert PI_LO ** 2 < 10 and (PI_HI * 2) ** 2 > 39, "pi bounds sanity"

class Grid:
    def __init__(self, cols, representatives_expected=265):
        """cols: the two per-mode dicts from FROZEN_NODES.json:frequency_grids[sign] (column, a, R_tot, c_max, s, t, h, J)."""
        assert len(cols) == 2
        self.cols = cols
        self.h = [Fr(c["h"]) for c in cols]; self.J = [int(c["J"]) for c in cols]
        self.a = [Fr(c["a"]) for c in cols]; self.R_tot = [Fr(c["R_tot"]) for c in cols]
        self.c_max = [Fr(c["c_max"]) for c in cols]; self.s = [int(c["s"]) for c in cols]; self.t = [int(c["t"]) for c in cols]
        self.reps = self._reps()
        assert len(self.reps) == representatives_expected, (len(self.reps), representatives_expected)
    def _reps(self):
        J2, J3 = self.J[0], self.J[1]; out = []
        for k2 in range(0, J2 + 1):
            for k3 in range(-J3, J3 + 1):
                if k2 > 0 or (k2 == 0 and k3 >= 0): out.append((k2, k3, 1 if (k2 == 0 and k3 == 0) else 2))
        return out
    # ---- exact alias/tail recertification of the DECLARED h, J (not a new search)
    def alias_upper(self, l: int) -> Fr:
        """A(h) <= 2 exp(-(P-B)^2/2) / (1 - exp(-P(P-B))), P = 2 pi / h, B = c_max"""
        h, B = self.h[l], self.c_max[l]
        P_lo, P_hi = 2 * PI_LO / h, 2 * PI_HI / h
        assert P_lo > B, "P > B required"
        d_lo = P_lo - B                                     # lower bound on P - B
        num = 2 * exp_upper(-(d_lo * d_lo) / 2)
        den = 1 - exp_upper(-(P_lo * d_lo))                 # lower bound of the denominator
        assert den > 0
        return num / den
    def trunc_upper(self, l: int) -> Fr:
        """T(h,J) <= sqrt(2/pi) exp(-(Jh)^2/2) / (Jh)"""
        Jh = self.J[l] * self.h[l]
        return sqrt_upper(Fr(2) / PI_LO) * exp_upper(-(Jh * Jh) / 2) / Jh
    def delta_comp_upper(self) -> Fr:
        d = [self.alias_upper(l) + self.trunc_upper(l) for l in (0, 1)]
        return d[0] + d[1] + d[0] * d[1]
    def recertify(self, archived_delta: Fr):
        mine = self.delta_comp_upper()
        return {"recomputed_delta_comp_upper": mine, "archived_delta_comp": archived_delta,
                "no_larger_than_archived": mine <= archived_delta,
                "per_mode": [{"alias_upper": self.alias_upper(l), "trunc_upper": self.trunc_upper(l),
                              "declared_alias_hi": Fr(self.cols[l]["alias_hi"]) if "alias_hi" in self.cols[l] else None,
                              "declared_trunc_hi": Fr(self.cols[l]["trunc_hi"]) if "trunc_hi" in self.cols[l] else None,
                              "P_gt_B": 2 * PI_LO / self.h[l] > self.c_max[l], "J": self.J[l], "s": self.s[l], "t": self.t[l]} for l in (0, 1)],
                "h_bounds_7_24_to_7_10": all(Fr(7, 24) < self.h[l] < Fr(7, 10) for l in (0, 1)),
                "J_le_14": all(self.J[l] <= 14 for l in (0, 1)), "Jh_lt_47_10": all(self.J[l] * self.h[l] < Fr(47, 10) for l in (0, 1))}
