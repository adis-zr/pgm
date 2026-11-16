"""Sharp mixture transfer (theory §5): with L <= R, D <= U, rho = U/(L+U), a retained-law enclosure [l,u] of an event becomes
[(1-rho) l, (1-rho) u + rho] under the original law; width (1-rho) w + rho. Exact rationals; the published 6-decimal
endpoints are rounded OUTWARD and the width tests use the outward-rounded endpoints. Observed coordinates stay exact point
masses (both laws obey the evidence)."""
from fractions import Fraction as Fr

DEC = 6


def rho_of(L, U):
    L, U = Fr(L), Fr(U)
    assert L > 0 and U >= 0
    return U / (L + U)


def transfer_interval(l, u, rho):
    l, u, rho = Fr(l), Fr(u), Fr(rho)
    assert 0 <= l <= u <= 1 and 0 <= rho < 1
    return (1 - rho) * l, (1 - rho) * u + rho


def round_outward(lo, hi, dec=DEC):
    q = Fr(10) ** dec
    lo_r = Fr((lo * q).numerator // (lo * q).denominator, 1) / q          # floor
    hi_r = Fr(-((-hi * q).numerator // (-hi * q).denominator), 1) / q      # ceil
    return max(Fr(0), lo_r), min(Fr(1), hi_r)


def transfer_publication(intervals, evidence, card, rho, targets=(Fr(1, 100), Fr(1, 50), Fr(1, 20))):
    """intervals: {var: [[lo, hi], ...]} as strings or Fractions (the retained law's certified enclosures, every original
    variable). Returns the transferred exact and outward-rounded rows, the per-coordinate widths and the target-width outcomes."""
    rho = Fr(rho)
    out_exact, out_round = {}, {}
    worst_num_w = Fr(0); worst_exact_w = Fr(0); worst_round_w = Fr(0)
    n_unobs = 0
    for v, rows in intervals.items():
        v = int(v)
        if v in evidence:
            out_exact[v] = [[Fr(lo), Fr(hi)] for lo, hi in rows]           # exact point masses: unchanged
            out_round[v] = [[Fr(lo), Fr(hi)] for lo, hi in rows]
            continue
        ex, rd = [], []
        for lo, hi in rows:
            lo, hi = Fr(lo), Fr(hi); n_unobs += 1
            worst_num_w = max(worst_num_w, hi - lo)
            tlo, thi = transfer_interval(lo, hi, rho)
            worst_exact_w = max(worst_exact_w, thi - tlo)
            rlo, rhi = round_outward(tlo, thi)
            worst_round_w = max(worst_round_w, rhi - rlo)
            ex.append([tlo, thi]); rd.append([rlo, rhi])
        out_exact[v] = ex; out_round[v] = rd
    res = {"rho": str(rho), "worst_numerical_width": str(worst_num_w), "worst_transferred_width_exact": str(worst_exact_w),
           "worst_published_width_outward_rounded": str(worst_round_w), "unobserved_coordinates": n_unobs,
           "targets": {str(t): {"met_on_outward_rounded_endpoints": bool(worst_round_w <= t), "met_exact": bool(worst_exact_w <= t),
                                "rho_allowance_rule_(eps-w)/(1-w)": (str((t - worst_num_w) / (1 - worst_num_w)) if worst_num_w < 1 else None),
                                "rule_satisfied": bool(worst_num_w < 1 and rho <= (t - worst_num_w) / (1 - worst_num_w))} for t in targets}}
    return out_exact, out_round, res
