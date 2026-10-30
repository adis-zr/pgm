"""Fresh-process execution of a PERSISTED plan (spec §8/§11 binding).

    python -m mdi.replay MODEL.uai [EVIDENCE.evid|-] PLAN.plan.json [OUT.json]

Reads the original model and evidence from disk, rebuilds the restricted and
preprocessed law, binds the plan record (hashes, scopes, preprocessing proof,
executor/checker references), parses its PROGRAM strictly, executes the
program with the producer's engine, publishes with the recorded radii, and
runs the independent program checker against the ORIGINAL model. Nothing from
the discovering process is available here: this is the demonstration that
the saved plan governs execution.
"""
from __future__ import annotations
import sys, json, time
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr


def replay(model_path, evidence_path, plan_path, eps=None, wall_s=600.0):
    from mdi import (model as M, plantype as PT, preprocess as PRE, config as K,
                     routes as RT, program_check as PC, budget as B, pipeline as PLN,
                     solve as S)
    import mdi.registry            # noqa: F401
    t0 = time.monotonic()
    eps = Fr(eps) if eps is not None else K.MAX_WIDTH
    m = M.read_uai(model_path)
    ev = M.read_evidence(evidence_path, m) if evidence_path and evidence_path != "-" else {}
    with open(plan_path) as fh:
        txt = fh.read()
    rec = PT.PlanRecord.from_json(txt)
    if rec.kind == "identity":
        return {"status": "NOT_A_PROGRAM_PLAN",
                "reason": "the identity plan's program is the validated generic "
                          "schedule run by mdi.solve; replay covers program routes"}
    prog = rec.parsed_program
    queries = set(prog["queries"])
    r0 = M.restrict(m, ev)
    mh, eh, qh = PLN.model_hashes(m, ev, queries)
    simp = PRE.simplify(r0)
    PRE.verify_identities(r0, simp)
    r = M.Restricted(model=m, evidence=dict(ev), factors=simp.factors,
                     free=list(simp.free), card=dict(simp.card),
                     constant=r0.constant, impossible_factor=None)
    rec.bind_check(mh, eh, qh, restricted=r, preprocess_identity=simp.identity(),
                   max_precision=4096)
    bg = B.Budget(wall_s=wall_s,
                  limits={"local_mass_entries": K.CAPS["local_mass_entries"]},
                  rss_fn=S._rss_bytes, rss_limit=K.RESOURCES["arm_rss_bytes"])
    bg.enter("replay-execute")
    try:
        rows, meta = RT.execute(prog, r, queries, deadline=bg.deadline_fn("replay"),
                                budget=bg)
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": rec.kind, "name": rec.name,
                "reason": "execution: %s" % e, "budget": bg.report(),
                "elapsed_s": time.monotonic() - t0}
    except Exception as e:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "reason": "%s: %s" % (type(e).__name__, e),
                "elapsed_s": time.monotonic() - t0}
    radius = sum((Fr(v) for v in rec.allocations.values()), Fr(0))
    pad = radius + K.PUBLICATION_RESERVE
    pub = {}
    for v in sorted(queries):
        pub[v] = [(max(Fr(0), Fr(lo) - pad), min(Fr(1), Fr(hi) + pad))
                  for lo, hi in rows[v]]
    bg.enter("replay-check")
    try:
        ok, fails, cmeta = PC.verify_program(r, queries, prog, pub, eps,
                                             deadline=bg.deadline_fn("replay-check"),
                                             budget=bg)
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": rec.kind, "name": rec.name,
                "reason": "producer completed but independent verification did "
                          "not finish: %s" % e,
                "intervals": {str(v): [[str(lo), str(hi)] for lo, hi in pub[v]]
                              for v in sorted(pub)},
                "budget": bg.report(), "elapsed_s": time.monotonic() - t0}
    worst = max((hi - lo for v in pub for lo, hi in pub[v]), default=Fr(0))
    status = ("REPLAY_VERIFIED" if ok and worst <= eps else
              "REPLAY_REJECTED" if not ok else "REPLAY_WIDTH_EXCEEDED")
    return {"status": status, "kind": rec.kind, "name": rec.name,
            "plan_sha_bound": {"model": mh[:16], "evidence": eh[:16], "query": qh[:16]},
            "intervals": {str(v): [[str(lo), str(hi)] for lo, hi in pub[v]]
                          for v in sorted(pub)},
            "radius": str(radius), "max_width": str(worst),
            "research": prog["research"], "executor": {k: str(v) for k, v in meta.items()
                                                       if k not in ("lattice",)},
            "checker": {k: (str(v) if not isinstance(v, (dict, list, bool)) else v)
                        for k, v in (cmeta or {}).items()},
            "failures": [str(x)[:200] for x in (fails or [])[:8]],
            "budget": bg.report(), "elapsed_s": time.monotonic() - t0}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    out = replay(argv[0], argv[1], argv[2])
    txt = json.dumps(out, indent=1, default=str)
    if len(argv) > 3:
        with open(argv[3], "w") as fh:
            fh.write(txt)
    print(txt)
    return 0 if out["status"] == "REPLAY_VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
