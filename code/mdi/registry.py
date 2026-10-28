"""Register the executors and checkers that ACTUALLY exist (contract §A).

Registration is a factual statement about implemented code, not an aspiration.
An unregistered kind makes `dispatch` refuse, so a recognized-but-unimplemented
route can never be routed silently into the original-model solver.
"""
from __future__ import annotations
from mdi import plantype as PT


def _identity_executor(model, evidence, **kw):
    from mdi import solve as S
    return S.solve(model, evidence, **kw)


def _identity_checker(model, evidence, iv, eps, **kw):
    from mdi import solve as S
    return S.verify_publication(model, evidence, iv, eps=eps)


def _regional_executor(restricted, regions, coarse, rds, queries, **kw):
    from mdi import coarse as CZ
    return CZ.solve_coarse_with_markers(
        restricted.free, restricted.card, restricted.factors, regions, coarse,
        rds, queries, **kw)


def _statistic_executor(free, card, residual_unary, residual_pairs,
                        kept_factors, cand, Q, queries, **kw):
    from mdi import collective as CO
    acc, marks, kq = CO.statistic_dp(free, card, residual_unary, residual_pairs,
                                     kept_factors, cand, Q, queries, **kw)
    return acc, marks, kq


def _gaussian_executor(free, card, residual_unary, cand, queries, ctx, delta,
                       **kw):
    from mdi import collective as CO
    return CO.gaussian_evaluate(free, card, residual_unary, cand, queries, ctx,
                                delta, **kw)


# ---- what exists ----
PT.register_executor("identity", _identity_executor)
PT.register_checker("identity", _identity_checker)

PT.register_executor("regional", _regional_executor)
# NO regional checker: spec 11 requires local certificates plus the reduced
# contraction, which is not implemented. Leaving it unregistered is what makes
# a regional route ineligible for a certified label.

PT.register_executor("statistic", _statistic_executor)
# NO statistic checker yet.

PT.register_executor("gaussian", _gaussian_executor)
# NO gaussian checker yet.

# 'fourier' and 'composed' have NO executor: both refuse at dispatch.

UNIMPLEMENTED = {
    "fourier": "no complex-phase tensor evaluator exists; negative modes run "
               "through the exact statistic DP instead",
    "composed": "coarsening followed by a collective evaluator is not "
                "connected; categorical mode fitting is missing",
}

MISSING_CHECKERS = {
    "regional": "spec 11 requires local certificates plus an independent "
                "reduced-model contraction; not implemented",
    "statistic": "no independent statistic-DP checker",
    "gaussian": "no independent quadrature checker",
}


def status_table():
    rows = []
    for k in PT.KINDS:
        s = PT.supported(k)
        rows.append({"kind": k, **s,
                     "executor_note": UNIMPLEMENTED.get(k, ""),
                     "checker_note": MISSING_CHECKERS.get(k, "")})
    return rows
