"""Exact-rational evaluation of the per-site perturbation bound of amendments/NUMERICAL_PROOF_REPAIR.md section 4 under the domain D*."""
import sys
from fractions import Fraction as Fr
sys.set_int_max_str_digits(0)
CR = 16
def bound(P, n=2 ** 16):
    e = Fr(1, 2 ** P)
    w_theta = 2 * e * Fr(1, 3) + 4 * e * Fr(1, 2) + 2 * e * Fr(5, 6)
    delta_u = (w_theta * (1 + w_theta) + 2 * e) / 2
    hw_ang = (2 * e * Fr(1, 32) + 2 * e * Fr(1, 32)) / 2
    dD = (delta_u + e * (1 + delta_u)) + (2 * (hw_ang + e * Fr(1, 32)) + 2 * e) + 2 * e * (1 + delta_u) * (1 + e)
    dM = e + e * (1 + e)
    inc = dM * (1 + dD) + dD + CR * e * (1 + dD) * (1 + dM)
    s_n = (1 + inc) ** n - 1
    return {"P": P, "dD_over_eps": float(dD / e), "dM_over_eps": float(dM / e), "inc_over_eps": float(inc / e), "s_n_upper": float(s_n), "S_max": float(48 * n * e), "ceiling_dominates": s_n <= 48 * n * e}
if __name__ == "__main__":
    for P in (96, 144):
        r = bound(P); print(r); assert r["ceiling_dominates"]
    print("OK: inc <= 26.3 eps and s_n <= 48 n eps for n <= 2^16, P >= 96")
