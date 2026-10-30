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
    # forward the TYPED result, including whether the independent aggregation
    # check actually ran; the pipeline gates its status on it
    return S.verify_publication(model, evidence, iv, eps=eps,
                                deadline_s=deadline_s, cap_bytes=cap_bytes)


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


def pipeline_program_executor(ctx):
    """Execute the PERSISTED program of the selected plan. The context carries
    the original restricted model, the requested variables, the parsed
    program read back from disk, and the shared budget -- and nothing from
    discovery."""
    from mdi import routes as RT
    prog = ctx["program"]
    if prog is None:
        raise PT.ExecutorRefusal("RESOURCE_STOP", "the selected plan carries "
                                 "no program block")
    bg = ctx["budget"]
    from mdi import budget as B
    try:
        rows, meta = RT.execute(prog, ctx["restricted"], ctx["queries"],
                                deadline=bg.deadline_fn("execute:" + prog["kind"]),
                                budget=bg)
    except B.BudgetExceeded:
        raise
    except Exception as e:
        # any refusal of the program's own construction (a witness that
        # violates the marker identity, a cap, a declined residual) is a
        # typed NUMERICAL refusal of this plan, never a crash
        raise PT.ExecutorRefusal("NUMERICAL_REFUSAL",
                                 "program execution refused: %s: %s"
                                 % (type(e).__name__, e))
    ctx["meta"] = meta
    return rows


def _program_executor(restricted, queries, program, **kw):
    from mdi import routes as RT
    return RT.execute(program, restricted, queries, **kw)


def _program_checker(restricted, queries, program, published, eps, **kw):
    from mdi import program_check as PC
    return PC.verify_program(restricted, queries, program, published, eps, **kw)


PT.register_pipeline_executor("identity", pipeline_identity_executor)
for _k in ("regional", "composed", "statistic", "gaussian", "fourier"):
    PT.register_pipeline_executor(_k, pipeline_program_executor)

# ---- what exists ----
PT.register_executor("identity", _identity_executor)
PT.register_checker("identity", _identity_checker)

# Every research kind is executed from its PERSISTED PROGRAM and checked by
# the program checker against the original model (routes.py,
# program_check.py). The former per-kind adapters (coarse.py executor,
# collective.py point evaluators, composed.py) are no longer on any path.
for _k in ("regional", "composed", "statistic", "gaussian", "fourier"):
    PT.register_executor(_k, _program_executor)
    PT.register_checker(_k, _program_checker)

UNIMPLEMENTED = {}
MISSING_CHECKERS = {}


def status_table():
    rows = []
    for k in PT.KINDS:
        s = PT.supported(k)
        rows.append({"kind": k, **s,
                     "executor_note": UNIMPLEMENTED.get(k, ""),
                     "checker_note": MISSING_CHECKERS.get(k, "")})
    return rows
