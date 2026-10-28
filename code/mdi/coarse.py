"""Execute a coarse regional model and restore the original query markers.

Spec 5.6: the final contraction computes ORIGINAL-variable outputs directly
from the markers, not by independently approximating every coarse-cell marginal.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import model as M, plan as P, contract as C, arith as A


def build_coarse_model(free, card, factors, regions, coarse, rds):
    """Turn the coarse regions into an ordinary factor graph over CELL variables.

    Cell variable r has cardinality len(cells[r]). Its unary factor is M_R(C).
    Each original crossing factor becomes a factor over the incident cell
    variables, evaluated at the cell REPRESENTATIVES (spec 5.3). Original tables
    plus projection maps are used; no gratuitous Cartesian expansion.
    """
    reg_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            reg_of[v] = i
    ncell = [len(c.cells) for c in coarse]
    nreg = len(regions)
    cfacs = []
    # unary cell masses
    for i in range(nreg):
        cfacs.append(M.Factor(scope=(i,), card=(ncell[i],),
                              table=[Fr(x) for x in coarse[i].M], origin=-(i + 1)))
    # crossing factors at representatives
    crossing = []
    for fi, f in enumerate(factors):
        rs = sorted({reg_of[v] for v in f.scope})
        if len(rs) <= 1:
            continue
        crossing.append(fi)
        scope = tuple(rs)
        cards = tuple(ncell[i] for i in rs)
        n = 1
        for c in cards:
            n *= c
        st = [1] * len(cards)
        acc = 1
        for k in range(len(cards) - 1, -1, -1):
            st[k] = acc; acc *= cards[k]
        fst = f.strides()
        tab = []
        for flat in range(n):
            rem = flat
            digits = []
            for k in range(len(cards)):
                digits.append(rem // st[k]); rem = rem % st[k]
            a = {}
            for k, i in enumerate(rs):
                rep = coarse[i].cells[digits[k]].rep
                a.update(dict(zip(rds[i].boundary, rep)))
            off = 0
            ok = True
            for k, v in enumerate(f.scope):
                if v not in a:
                    ok = False; break
                off += a[v] * fst[k]
            tab.append(f.table[off] if ok else Fr(1))
        cfacs.append(M.Factor(scope=scope, card=cards, table=tab, origin=fi))
    cmodel = M.Model(nvars=nreg, card=list(ncell), factors=cfacs).validate()
    return cmodel, crossing, reg_of


def solve_coarse_with_markers(free, card, factors, regions, coarse, rds,
                              queries, eps, mode="P", cap_bytes=1 << 30,
                              deadline_s=120.0, p_min=64):
    """Contract the coarse model once, reading ORIGINAL-variable markers.

    For query i owned by region R, the marked coarse weight replaces M_R(C) by
    N_{R,i,a}(C). Because the replacement touches only R's unary cell factor, a
    single calibrated pass over the coarse model yields every original marginal:
    the cell-marginal of R gives P(cell), and the payload g_{i,a}(C) =
    N/M is then applied cellwise. This avoids one contraction per query.
    """
    from mdi import solve as S
    cmodel, crossing, reg_of = build_coarse_model(free, card, factors, regions,
                                                  coarse, rds)
    # The coarse model's own singleton marginals over CELL variables.
    res = S.solve(cmodel, {}, eps=eps, mode=mode, cap_bytes=cap_bytes,
                  deadline_s=deadline_s, p_min=p_min, run_checker=False)
    # solve() with run_checker=False now reports PRODUCER_COMPLETE_UNCHECKED,
    # which is the honest status: the coarse contraction finished but nothing
    # independently verified it.
    if res["outcome"] not in ("VERIFIED_ALL_MARGINALS",
                              "PRODUCER_COMPLETE_UNCHECKED"):
        return {"outcome": res["outcome"], "reason": res.get("reason"),
                "coarse_model": {"nvars": cmodel.nvars,
                                 "card": cmodel.card,
                                 "factors": len(cmodel.factors)},
                "coarse_result": {k: v for k, v in res.items()
                                  if k not in ("intervals", "raw_intervals")}}
    cell_iv = res["intervals"]

    # restore original markers: P(x_i = a) = sum_C P(C) * g_{i,a}(C)
    out = {}
    for v in sorted(queries):
        i = reg_of[v]
        cr = coarse[i]
        lo = hi = Fr(0)
        rows = cell_iv[i]
        per = []
        for ci in range(len(cr.cells)):
            Mc = Fr(cr.M[ci])
            if Mc <= 0:
                per.append((Fr(0), Fr(0))); continue
            per.append(rows[ci])
        n_states = card[v]
        acc = []
        for a in range(n_states):
            l = h = Fr(0)
            for ci in range(len(cr.cells)):
                Mc = Fr(cr.M[ci])
                if Mc <= 0:
                    continue
                g = Fr(cr.N[(v, a)][ci]) / Mc      # payload in [0,1]
                plo, phi = per[ci]
                l += Fr(plo) * g
                h += Fr(phi) * g
            acc.append((min(l, Fr(1)), min(h, Fr(1))))
        out[v] = acc
    # The coarse contraction ran with run_checker=False, so NOTHING here has
    # been independently verified. Returning VERIFIED_ALL_MARGINALS let the arm
    # publish CERTIFIED_RESEARCH_ROUTE with no independent check at all. The
    # honest status is UNCHECKED; a caller must not treat it as certified.
    return {"outcome": "PRODUCER_COMPLETE_UNCHECKED", "intervals": out,
            "checker": {"status": "NOT_RUN",
                        "reason": "no independent checker exists for a coarse "
                                  "publication; spec 11 requires local "
                                  "certificates plus the smaller contraction"},
            "coarse_model": {"nvars": cmodel.nvars, "card": cmodel.card,
                             "factors": len(cmodel.factors),
                             "crossing_factors": len(crossing)},
            "coarse_result": {k: v for k, v in res.items()
                              if k not in ("intervals", "raw_intervals")}}
