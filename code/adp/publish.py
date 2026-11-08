"""Publication contract of AGGREGATE_DP_V1 (exact rationals only).

For every original variable, certified intervals [L_s, U_s] per state and a simplex-feasible point p with
    p_s in [L_s, U_s] ∩ [U_s - eps, L_s + eps] ∩ [0, 1],   sum_s p_s = 1,
on an exact dyadic grid 2^-G with G = 40 + ceil(log2(max_domain)). Endpoints are first widened outward to the grid, then an
integer allocation problem is solved on the grid (lower bounds first, remaining mass allocated deterministically in state
order within the upper bounds). The serialized decimal strings are exact finite decimals of the dyadic grid points and are
re-parsed and re-verified exactly before anything is written. Width-only certification and point feasibility are distinct.
"""
from __future__ import annotations
import sys, math
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

EPS = Fr(1, 200)
MAX_WIDTH = Fr(1, 100)


def grid_bits(max_domain):
    return 40 + max(0, math.ceil(math.log2(max(2, max_domain))))


def floor_grid(q, G):
    return Fr(math.floor(q * (1 << G)), 1 << G)


def ceil_grid(q, G):
    return Fr(math.ceil(q * (1 << G)), 1 << G)


def widen(row, G):
    """Outward-rounded endpoints on the grid, clipped to [0,1]."""
    return [(max(Fr(0), floor_grid(lo, G)), min(Fr(1), ceil_grid(hi, G))) for lo, hi in row]


def robust_center(row_grid, G, eps=EPS):
    """Exact grid point p with p_s in [max(L,U-eps), min(U,L+eps)] ∩ [0,1] and sum = 1, or None if infeasible on the grid.
    Bounds are themselves taken on the grid (lower up, upper down) so every coordinate is a grid multiple."""
    lo = []; hi = []
    for L, U in row_grid:
        a = max(Fr(0), L, U - eps); b = min(Fr(1), U, L + eps)
        a = ceil_grid(a, G); b = floor_grid(b, G)
        if a > b:
            return None
        lo.append(a); hi.append(b)
    if sum(lo) > 1 or sum(hi) < 1:
        return None
    p = list(lo); left = Fr(1) - sum(p)
    for i in range(len(p)):
        add = min(left, hi[i] - p[i]); p[i] += add; left -= add
    assert left == 0 and sum(p) == 1
    return p


def verify_point(p, row, eps=EPS):
    """Exact check of the publication predicate for ONE row against the (unwidened or widened) certified intervals."""
    if sum(p) != 1:
        return False, "row sum %s != 1" % sum(p)
    for s, (q, (L, U)) in enumerate(zip(p, row)):
        if not (0 <= q <= 1):
            return False, "state %d outside [0,1]" % s
        if not (L <= q <= U):
            return False, "state %d: point %s outside its interval [%s, %s]" % (s, q, L, U)
        if not (U - eps <= q <= L + eps):
            return False, "state %d: point %s not within eps of every value of [%s, %s]" % (s, q, L, U)
    return True, "ok"


def dyadic_decimal(q, G):
    """Exact finite decimal string of a dyadic rational with denominator dividing 2^G."""
    q = Fr(q); assert (1 << G) % q.denominator == 0, "not on the grid"
    n = q.numerator * (10 ** G // (2 ** G)) if False else None
    # 1/2^G = 5^G / 10^G: exact decimal with G fractional digits
    num = q.numerator * (5 ** G) * ((1 << G) // q.denominator)
    s = str(num).rjust(G + 1, "0")
    out = s[:-G] + "." + s[-G:]
    return out.rstrip("0").rstrip(".") if "." in out else out


def parse_decimal(s):
    return Fr(s)


def publish_rows(intervals, card, eps=EPS, max_width=MAX_WIDTH):
    """intervals: {v: [(L, U) per original state]} exact Fractions for EVERY original variable (observed rows [1,1]/[0,0]).
    Returns (rows_points | None, report). A row is TOO_WIDE if any width > max_width; INFEASIBLE if the robust center does
    not exist on the grid (then the point target is not met even though widths may be <= max_width)."""
    G = grid_bits(max(card)); points = {}; widened = {}; report = {"grid_bits": G, "eps": str(eps), "max_width": str(max_width), "rows": {}, "max_width_observed": "0", "status": "CERTIFIED"}
    wmax = Fr(0); ok_all = True
    for v in range(len(card)):
        row = intervals[v]; rg = widen(row, G); widened[v] = rg; w = max(U - L for L, U in row); wmax = max(wmax, w)      # certified width (pre-grid)
        p = robust_center(rg, G, eps)
        if p is None:
            report["rows"][str(v)] = {"width": str(w), "point": None, "reason": "robust-center box infeasible on the grid"}; ok_all = False; continue
        strs = [dyadic_decimal(x, G) for x in p]; back = [parse_decimal(s) for s in strs]
        okp, why = (verify_point(back, rg, eps) if back == p else (False, "serialization round trip failed"))   # the DELIVERED decimals against the PUBLISHED (grid-widened) intervals
        if not okp:
            report["rows"][str(v)] = {"width": str(w), "point": None, "reason": why}; ok_all = False; continue
        points[v] = strs; report["rows"][str(v)] = {"width": str(w), "point": strs}
    report["widened_intervals"] = widened; report["max_width_published_grid"] = str(max((U - L) for rg in widened.values() for L, U in rg))
    report["max_width_observed"] = str(wmax); report["width_met"] = bool(wmax <= max_width); report["point_feasible_all_rows"] = ok_all
    if not ok_all:
        report["status"] = "CERTIFIED_TOO_WIDE" if wmax > max_width else "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE"
    elif wmax > max_width:
        report["status"] = "CERTIFIED_TOO_WIDE"
    return (points if ok_all else None), report


def verify_mar_against_intervals(mar_path, intervals, card, eps=EPS):
    """Independent exact re-verification of a delivered MAR file (parsed by ext.uai) against grid-widened certified intervals."""
    from ext import uai as U
    rows, _ = U.read_mar(mar_path); G = grid_bits(max(card))
    if len(rows) != len(card):
        return False, "row count"
    for v in range(len(card)):
        if len(rows[v]) != card[v]:
            return False, "row %d length" % v
        ok, why = verify_point([Fr(x) for x in rows[v]], widen(intervals[v], G), eps)
        if not ok:
            return False, "row %d: %s" % (v, why)
    return True, "ok"


def write_mar(path, points, card):
    rows = ["%d %s" % (card[v], " ".join(points[v])) for v in range(len(card))]
    with open(path, "w") as fh:
        fh.write("MAR\n%d %s\n" % (len(card), " ".join(rows)))
