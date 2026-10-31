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
                                deadline_s=deadline_s, cap_bytes=cap_bytes,
                                checker_precision=(program["checker"]["precision"]
                                                   if program is not None else None))


# ---- pipeline executors ----
# The public pipeline must INVOKE the executor bound by the validated selected
# plan. It previously looked one up via dispatch() and then branched on
# crec.kind, calling a different path entirely: replacing the identity
# executor with a raising sentinel still produced a certified result with zero
# executor calls. These adapters give every route one uniform signature so the
# dispatched object is the thing that actually runs.

def pipeline_identity_executor(ctx):
    """Execute the IDENTITY program: the persisted order, precision and
    exponent range govern; planning is not rerun."""
    from mdi import solve as S
    prog = ctx.get("program")
    sub = None
    if prog is not None:
        sub = {"order": prog["order"], "precision": prog["precision"],
               "emin": prog["arithmetic"]["emin"], "emax": prog["arithmetic"]["emax"]}
    bg = ctx.get("budget")
    charge = (lambda n: bg.charge("local_mass_entries", n, "identity producer message entries")) if bg else None
    res = S.solve(ctx["model"], ctx["evidence"], eps=ctx["eps"], mode="P",
                  cap_bytes=ctx["cap_bytes"],
                  deadline_s=ctx["remaining"](),
                  run_checker=False, preprocess=True, program=sub, charge=charge)
    if res["outcome"] != "PRODUCER_COMPLETE_UNCHECKED":
        raise PT.ExecutorRefusal(res["outcome"], res.get("reason", ""))
    ctx["meta"] = {"evaluator": "identity", "ops": res.get("ops"),
                   "peak_live_message_entries": res.get("peak_live_message_entries"),
                   "settings": res.get("program_settings")}
    return res["intervals"]


def pipeline_identity_checker(model, evidence, iv, eps, deadline_s=None,
                              cap_bytes=None, program=None, **kw):
    """The identity checker the pipeline INVOKES: the standalone independent
    verifier, whose own schedule strategy (min-fill, interval mode) and
    precision are what the program declares."""
    from mdi import solve as S
    if program is not None and program["checker"]["strategy"] != "min_fill_interval":
        return False, [{"reason": "the program declares checker strategy %r, which "
                                  "this checker does not run"
                                  % program["checker"]["strategy"]}], None
    return S.verify_publication(model, evidence, iv, eps=eps,
                                deadline_s=deadline_s, cap_bytes=cap_bytes,
                                checker_precision=(program["checker"]["precision"]
                                                   if program is not None else None))


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
                                budget=bg, num_eps=ctx.get("eps"),
                                progress=ctx.get("progress"))
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
for _k in ("regional", "composed", "statistic", "gaussian", "fourier", "mixed"):
    PT.register_pipeline_executor(_k, pipeline_program_executor)

# the checkers the pipeline invokes, by kind
PIPELINE_CHECKERS = {"identity": pipeline_identity_checker}
for _k in ("regional", "composed", "statistic", "gaussian", "fourier", "mixed"):
    PIPELINE_CHECKERS[_k] = _program_checker

# ---- what exists ----
PT.register_executor("identity", _identity_executor)
PT.register_checker("identity", _identity_checker)

# Every research kind is executed from its PERSISTED PROGRAM and checked by
# the program checker against the original model (routes.py,
# program_check.py). The former per-kind adapters (coarse.py executor,
# collective.py point evaluators, composed.py) are no longer on any path.
for _k in ("regional", "composed", "statistic", "gaussian", "fourier", "mixed"):
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
