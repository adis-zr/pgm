"""Frozen Fourier grids and the declared analytic radii (CLAUDE_CODE_SPEC.md "Arm F"), plus the exact-rational verification that the
declared radius dominates the input-derived alias+truncation bound (scalar_fourier_baseline.md).  Shared scalar module (declared)."""
from __future__ import annotations

from fractions import Fraction as Fr

from dq.constants import alias_upper, truncation_upper

GRIDS = {"MAIN": {"h": Fr(1), "J": 3, "delta_declared": Fr(113, 100000)}, "CONTROL": {"h": Fr(3, 4), "J": 4, "delta_declared": Fr(1, 1400)}}
E_NUM = Fr(1, 400000)            # required arithmetic error per finite marker estimate
PAD_NUM_F = Fr(1, 100000)        # stored four-error padding
PAD_PUB_F = Fr(1, 100000)        # max outward endpoint rounding
RESIDUAL_REQ = Fr(1, 8)


def verify_declared_delta(case: str, V_bar: Fr, r: Fr = RESIDUAL_REQ) -> dict:
    g = GRIDS[case]
    A = alias_upper(g["h"], r, V_bar); T = truncation_upper(g["h"], g["J"])
    return {"h": str(g["h"]), "J": g["J"], "alias_upper": str(A), "truncation_upper": str(T), "alias_plus_truncation": str(A + T), "alias_plus_truncation_float": float(A + T),
            "delta_declared": str(g["delta_declared"]), "declared_dominates": A + T <= g["delta_declared"], "V_bar_used": str(V_bar)}
