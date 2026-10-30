"""Fresh-process execution of a PERSISTED plan through the pipeline's ONE
loaded-object boundary (spec §8/§11 binding).

    python -m mdi.replay MODEL.uai [EVIDENCE.evid|-] PLAN.plan.json [OUT.json]

Reads the original model and evidence, rebuilds the restricted and
preprocessed law, loads the record, BINDS it exactly as the pipeline does
(`pipeline.bind_loaded`: hashes, scopes, preprocessing proof, roles, no
completion flags, program/kind agreement, re-derived price on the saved
order), then runs `pipeline.run_loaded` -- the same executor dispatch,
publication rule, independent checker, research agreement, status
derivation and shared budget limits as the public pipeline. Nothing from the
discovering process is available here.
"""
from __future__ import annotations
import sys, json, time
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr


def replay(model_path, evidence_path, plan_path, eps=None, wall_s=600.0, wrap=None):
    """Bind, admit, execute and check ONE persisted plan in this process under
    a fresh shared budget with the pipeline's limits; a record the pipeline's
    admission rule refuses is refused here too. `wrap(stage, fn)` optionally
    wraps the executor and checker calls (the acceptance matrix counts
    operations through it)."""
    from mdi import (model as M, plantype as PT, preprocess as PRE, config as K,
                     pipeline as PLN, budget as B, solve as S)
    import mdi.registry            # noqa: F401
    t0 = time.monotonic()
    eps = Fr(eps) if eps is not None else K.MAX_WIDTH
    m = M.read_uai(model_path)
    ev = M.read_evidence(evidence_path, m) if evidence_path and evidence_path != "-" else {}
    with open(plan_path) as fh:
        txt = fh.read()
    rec = PT.PlanRecord.from_json(txt)
    prog = rec.parsed_program
    queries = set(prog["queries"])
    r0 = M.restrict(m, ev)
    mh, eh, qh = PLN.model_hashes(m, ev, queries)
    simp = PRE.simplify(r0)
    PRE.verify_identities(r0, simp)
    r = M.Restricted(model=m, evidence=dict(ev), factors=simp.factors,
                     free=list(simp.free), card=dict(simp.card),
                     constant=r0.constant, impossible_factor=None)
    nq = sum(r.card[v] for v in sorted(queries))
    bg = B.Budget(wall_s=wall_s,
                  limits={"profile_comparisons": K.CAPS["profile_entry_comparisons"],
                          "local_mass_entries": K.CAPS["local_mass_entries"]},
                  rss_fn=S._rss_bytes, rss_limit=K.RESOURCES["arm_rss_bytes"])
    try:
        bg.enter("bind")
        price = PLN.bind_loaded(rec, mh, eh, qh, r, simp, queries, nq,
                                K.RESOURCES["arm_rss_bytes"], bg=bg)
    except PT.PlanError as e:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "reason": "binding refused: %s" % e, "elapsed_s": time.monotonic() - t0}
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": rec.kind, "name": rec.name,
                "reason": "binding: %s" % e, "budget": bg.report(),
                "elapsed_s": time.monotonic() - t0}
    bad = PLN.loaded_admission(rec, price)
    if bad:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "identity": getattr(rec, "identity_key", None),
                "reason": "the loaded program is not admissible under the pipeline's "
                          "rule: %s" % bad,
                "price": price.as_dict(), "budget": bg.report(),
                "elapsed_s": time.monotonic() - t0}
    rec.properties.set("selected")
    out = PLN.Outcome(status="INIT")
    out.prices = [price.as_dict()]
    res = PLN.run_loaded(rec, m, ev, queries, r, bg, eps, K.RESOURCES["arm_rss_bytes"],
                         out=out, wrap=wrap)
    status = {"CERTIFIED_RESEARCH_ROUTE": "REPLAY_VERIFIED",
              "CERTIFIED_FALLBACK_ONLY": "REPLAY_VERIFIED",
              "NUMERICAL_REFUSAL": "REPLAY_REJECTED",
              "RESOURCE_STOP": "REPLAY_RESOURCE_STOP",
              "VERIFIED_SHARED_AGGREGATION_ONLY": "REPLAY_SHARED_AGGREGATION_ONLY"}.get(
        res.status, "REPLAY_" + res.status)
    pub = res.intervals or {}
    worst = max((Fr(hi) - Fr(lo) for v in pub for lo, hi in pub[v]), default=Fr(0))
    return {"status": status, "pipeline_status": res.status, "kind": rec.kind,
            "name": rec.name, "identity": getattr(rec, "identity_key", None),
            "plan_sha_bound": {"model": mh[:16], "evidence": eh[:16], "query": qh[:16]},
            "intervals": {str(v): [[str(lo), str(hi)] for lo, hi in pub[v]]
                          for v in sorted(pub) if v in queries},
            "radius": str(sum((Fr(v) for v in rec.allocations.values()), Fr(0))),
            "max_width": str(worst), "research": (res.plan or {}).get("research"),
            "executor": {k: str(v) for k, v in ((res.plan or {}).get("executed") or {}).items()
                         if k not in ("lattice",)},
            "checker": {k: (str(v) if not isinstance(v, (dict, list, bool)) else v)
                        for k, v in (res.checker or {}).items() if k != "executor"},
            "failures": [str(x)[:200] for x in ((res.checker or {}).get("failures") or [])[:8]],
            "reason": res.reason, "budget": res.budget or bg.report(),
            "price": price.as_dict(), "elapsed_s": time.monotonic() - t0}


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
