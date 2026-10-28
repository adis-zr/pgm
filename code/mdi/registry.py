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


def _identity_checker(model, evidence, iv, eps, deadline_s=None,
                      cap_bytes=None, **kw):
    from mdi import solve as S
    return S.verify_publication(model, evidence, iv, eps=eps,
                                deadline_s=deadline_s, cap_bytes=cap_bytes)


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


def _general_statistic_executor(plan, factors, card, cand, Q, queries, ctx,
                                **kw):
    from mdi import gendp as G
    return G.run(plan, factors, card, cand, Q, queries, ctx, **kw)


def _gaussian_executor(free, card, residual_unary, cand, queries, ctx, delta,
                       **kw):
    from mdi import collective as CO
    return CO.gaussian_evaluate(free, card, residual_unary, cand, queries, ctx,
                                delta, **kw)


# ---- pipeline executors ----
# The public pipeline must INVOKE the executor bound by the validated selected
# plan. It previously looked one up via dispatch() and then branched on
# crec.kind, calling a different path entirely: replacing the identity
# executor with a raising sentinel still produced a certified result with zero
# executor calls. These adapters give every route one uniform signature so the
# dispatched object is the thing that actually runs.

def pipeline_identity_executor(ctx):
    """ctx carries model, evidence, eps, cap_bytes, remaining()."""
    from mdi import solve as S
    res = S.solve(ctx["model"], ctx["evidence"], eps=ctx["eps"], mode="P",
                  cap_bytes=ctx["cap_bytes"],
                  deadline_s=max(0.001, ctx["remaining"]()),
                  run_checker=False, preprocess=True)
    if res["outcome"] != "PRODUCER_COMPLETE_UNCHECKED":
        raise PT.ExecutorRefusal(res["outcome"], res.get("reason", ""))
    return res["intervals"]


def pipeline_regional_executor(ctx):
    return ctx["regional_execute"](ctx["restricted"], ctx["payload"],
                                   ctx["queries"], ctx["eps"], ctx["budget"])


def pipeline_composed_executor(ctx):
    pay = ctx["payload"].get("composed")
    if pay is None:
        raise PT.ExecutorRefusal("NUMERICAL_REFUSAL",
                                 "the composed payload is absent")
    return pay


PT.register_pipeline_executor("identity", pipeline_identity_executor)
PT.register_pipeline_executor("regional", pipeline_regional_executor)
PT.register_pipeline_executor("composed", pipeline_composed_executor)

# ---- what exists ----
PT.register_executor("identity", _identity_executor)
PT.register_checker("identity", _identity_checker)

def _regional_checker(restricted, regions, coarse, rds, queries, published,
                      t_level, eps, **kw):
    from mdi import regional_check as RC
    return RC.verify_regional_publication(restricted, regions, coarse, rds,
                                          queries, published, t_level, eps, **kw)


PT.register_executor("regional", _regional_executor)
PT.register_checker("regional", _regional_checker)

PT.register_executor("statistic", _statistic_executor)
# The GENERAL-residual variant runs on a validated elimination schedule, so a
# residual with retained pair or higher-arity factors is admissible.
GENERAL_STATISTIC = _general_statistic_executor
# NO statistic checker yet.

PT.register_executor("gaussian", _gaussian_executor)
# NO gaussian checker yet.

def _fourier_executor(free, card, residual_unary, cand, queries, ctx, delta,
                      **kw):
    from mdi import collective as CO
    return CO.fourier_evaluate(free, card, residual_unary, cand, queries, ctx,
                               delta, **kw)


def _composed_executor(restricted, regions, coarse, rds, queries, ctx, eps,
                       **kw):
    """Coarsen, then run a verified collective evaluator on the CATEGORICAL
    cells (contract E.7)."""
    from mdi import composed as CM
    return CM.run(restricted, regions, coarse, rds, queries, ctx, eps, **kw)


PT.register_executor("fourier", _fourier_executor)
PT.register_executor("composed", _composed_executor)

UNIMPLEMENTED = {}

def _statistic_checker(free, card, unary, cand, Q, queries, published, eps,
                       ctx, **kw):
    from mdi import collective_check as CC
    return CC.check_statistic_publication(free, card, unary, cand, Q, queries,
                                          published, eps, ctx, **kw)


def _quadrature_checker(free, card, unary, cand, queries, published, eps, ctx,
                        delta, **kw):
    from mdi import collective_check as CC
    return CC.check_quadrature_publication(free, card, unary, cand, queries,
                                           published, eps, ctx, delta, **kw)


def _composed_checker(restricted, regions, coarse, rds, queries, published,
                      eps, total_radius, regional_radius=None, **kw):
    from mdi import collective_check as CC
    return CC.check_composed_publication(restricted, regions, coarse, rds,
                                         queries, published, eps, total_radius,
                                         regional_radius=regional_radius)


PT.register_checker("statistic", _statistic_checker)
PT.register_checker("gaussian", _quadrature_checker)
PT.register_checker("fourier", _quadrature_checker)
PT.register_checker("composed", _composed_checker)

MISSING_CHECKERS = {}


def status_table():
    rows = []
    for k in PT.KINDS:
        s = PT.supported(k)
        rows.append({"kind": k, **s,
                     "executor_note": UNIMPLEMENTED.get(k, ""),
                     "checker_note": MISSING_CHECKERS.get(k, "")})
    return rows
