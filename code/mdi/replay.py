"""Fresh-process execution of a PERSISTED plan through the pipeline's ONE
loaded-object boundary (spec §8/§11 binding).

    python -m mdi.replay MODEL.uai [EVIDENCE.evid|-] PLAN.plan.json [OUT.json] [--eps W] [--cap BYTES]

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


REPLAY_SUCCESS = ("REPLAY_VERIFIED", "REPLAY_ZERO_EVIDENCE_PROVED", "REPLAY_SHARED_AGGREGATION_ONLY")


def replay(model_path, evidence_path, plan_path, eps=None, wall_s=600.0, wrap=None, cap_bytes=None):
    """Bind, admit, execute and check ONE persisted plan in this process under
    a fresh shared budget with the pipeline's limits; a record the pipeline's
    admission rule refuses is refused here too. `wrap(stage, fn)` optionally
    wraps the executor and checker calls (the acceptance matrix counts
    operations through it). EVERY terminal -- ordinary success, zero
    evidence, refusal, rejection, exception, resource exhaustion -- leaves
    through `_finalize`: the effective limits are tested after any proof and
    before publication, and the final budget report travels with the result."""
    from mdi import config as K, budget as B, solve as S
    t0 = B.DEFAULT_CLOCK[0]()
    # the INVOCATION budget exists before any model / evidence / plan parsing:
    # parsing is inside the observed, metered time
    asked = {"wall_s": float(wall_s), "rss_bytes": int(cap_bytes or K.RESOURCES["arm_rss_bytes"])}
    wall_s = min(float(wall_s), float(K.RESOURCES["arm_wall_s"]))
    cap_eff = min(int(cap_bytes or K.RESOURCES["arm_rss_bytes"]), int(K.RESOURCES["arm_rss_bytes"]))
    bg = B.Budget(wall_s=wall_s,
                  limits={"profile_comparisons": K.CAPS["profile_entry_comparisons"],
                          "local_mass_entries": K.CAPS["local_mass_entries"]},
                  rss_fn=S._rss_bytes, rss_limit=cap_eff)
    bg.requested_by_caller = asked
    cap_bytes = cap_eff
    try:
        out = _replay(model_path, evidence_path, plan_path, eps, wrap, cap_bytes, bg, t0)
    except Exception as e:                       # an implementation fault is a typed terminal, not a crash
        import traceback
        out = {"status": "REPLAY_IMPLEMENTATION_INCOMPLETE", "kind": None, "name": None,
               "reason": "%s: %s" % (type(e).__name__, e), "traceback": traceback.format_exc()[-1500:]}
    return _finalize(out, bg, t0)


def _finalize(out, bg, t0):
    """The ONE terminal path of a replay."""
    from mdi import budget as B
    try:
        bg.check("terminal")
    except B.BudgetExceeded as e:
        if out.get("status") in REPLAY_SUCCESS:
            out = {"status": "REPLAY_RESOURCE_STOP", "kind": out.get("kind"), "name": out.get("name"),
                   "identity": out.get("identity"),
                   "reason": "completed after the effective limit: %s" % e,
                   "partial_evidence": {"status_before_limit_check": out.get("status"), "reason": out.get("reason"),
                                        "checker": out.get("checker"), "intervals_withheld": bool(out.get("intervals")),
                                        "note": "the proof completed after the effective limit; it is partial evidence, "
                                                "not a publication"},
                   "request": out.get("request"), "requested": out.get("requested"), "observed": out.get("observed")}
    out["budget"] = bg.report()
    out["elapsed_s"] = B.DEFAULT_CLOCK[0]() - t0
    return out


def _replay(model_path, evidence_path, plan_path, eps, wrap, cap_bytes, bg, t0):
    from mdi import (arith as A, model as M, plantype as PT, preprocess as PRE, config as K, law as LAW,
                     pipeline as PLN, budget as B, solve as S)
    import mdi.registry            # noqa: F401
    try:
        bg.enter("parse")
        m = M.read_uai(model_path)
        ev = M.read_evidence(evidence_path, m) if evidence_path and evidence_path != "-" else {}
        with open(plan_path) as fh:
            txt = fh.read()
        bg.check("parsed")
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": None, "name": None,
                "reason": "parsing: %s" % e, "budget": bg.report()}
    try:
        rec = PT.PlanRecord.from_json(txt)
    except (PT.PlanError, ValueError) as e:
        # an invalid proof record (negative or non-rational allowance, unknown
        # field, inconsistent program, missing request) is REFUSED at load
        return {"status": "REPLAY_REFUSED", "kind": None, "name": None,
                "reason": "invalid proof record: %s" % e}
    # the request width GOVERNS: a caller's width must equal the record's;
    # with none given the record's own request is replayed (never a default)
    req_w = Fr(rec.request["width"])
    if eps is not None and Fr(eps) != req_w:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "reason": "the record was built for width %s; this request asks %s" % (req_w, Fr(eps))}
    eps = req_w
    prog = rec.parsed_program
    queries = set(prog["queries"])
    # the IMMUTABLE original law (frozen copy with occurrence identities); every
    # owner below derives its own working restriction from it
    law = LAW.OriginalLaw.freeze(m, ev, queries)
    m = law.model
    try:
        bg.enter("restrict")
        r0 = law.restrict_only()
        if r0.impossible_factor is not None or r0.constant == 0:
            proof = PLN.zero_evidence_proof(m, ev, r0)
            return {"status": ("REPLAY_ZERO_EVIDENCE_PROVED" if proof.get("proved")
                               else "REPLAY_REJECTED"),
                    "kind": rec.kind, "name": rec.name, "reason": proof["reason"],
                    "supplied_program_verified": False,
                    "note": "the INPUT was independently proved to have zero evidence weight; the supplied "
                            "plan was neither executed nor verified",
                    "checker": proof, "budget": bg.report()}
        mh, eh, qh = law.hashes
        bg.enter("preprocess")
        # the BINDER's own working restriction
        own = law.restriction()
        simp = own.simp
        if simp.impossible is not None:
            proof = PLN.zero_evidence_proof(m, ev, r0, named=simp.impossible)
            return {"status": ("REPLAY_ZERO_EVIDENCE_PROVED" if proof.get("proved")
                               else "REPLAY_REJECTED"),
                    "kind": rec.kind, "name": rec.name, "reason": proof["reason"],
                    "supplied_program_verified": False,
                    "note": "the INPUT was independently proved to have zero evidence weight; the supplied "
                            "plan was neither executed nor verified",
                    "checker": proof, "budget": bg.report()}
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": rec.kind, "name": rec.name,
                "reason": "preprocessing: %s" % e, "budget": bg.report()}
    except PRE.PreprocessError as e:
        return {"status": "REPLAY_REJECTED", "kind": rec.kind, "name": rec.name,
                "reason": "exact preprocessing failed its independent verification: %s" % e,
                "budget": bg.report()}
    r = own.r
    nq = sum(r.card[v] for v in sorted(queries))
    _tr_bind = A.transcendental_snapshot()
    try:
        bg.enter("persist" if rec.kind != "identity" else "bind")
        price = PLN.bind_loaded(rec, mh, eh, qh, r, simp, queries, nq,
                                K.RESOURCES["arm_rss_bytes"], bg=bg, eps=eps)
    except PT.PlanError as e:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "reason": "binding refused: %s" % e}
    except B.BudgetExceeded as e:
        return {"status": "REPLAY_RESOURCE_STOP", "kind": rec.kind, "name": rec.name,
                "reason": "binding: %s" % e, "budget": bg.report()}
    cap = cap_bytes or K.RESOURCES["arm_rss_bytes"]
    bad = PLN.loaded_admission(rec, price, cap_bytes=cap, bg=bg)
    if bad:
        return {"status": "REPLAY_REFUSED", "kind": rec.kind, "name": rec.name,
                "identity": getattr(rec, "identity_key", None),
                "reason": "the loaded program is not admissible under the pipeline's "
                          "rule: %s" % bad,
                "price": price.as_dict(), "budget": bg.report()}
    bind_calls = A.transcendental_since(_tr_bind)
    rec.properties.set("selected")
    out = PLN.Outcome(status="INIT")
    out.prices = [price.as_dict()]
    del r, own                       # the binder's working tables are not handed on
    res = PLN.run_loaded(rec, law, queries, bg, eps, cap, out=out, wrap=wrap)
    if res.plan is not None:
        # the BIND stage (reconstruction, fit proof, grids, repricing) is a
        # metered stage of the replay like execute and check
        res.plan.setdefault("stage_transcendental_calls", {})["bind"] = bind_calls
        cc = res.plan.get("complete_cost") or {}
        if isinstance(cc.get("measured"), dict):
            cc["measured"].setdefault("stage_transcendental_calls", {})["bind"] = bind_calls
    status = {"CERTIFIED_RESEARCH_ROUTE": "REPLAY_VERIFIED",
              "CERTIFIED_FALLBACK_ONLY": "REPLAY_VERIFIED",
              "NUMERICAL_REFUSAL": "REPLAY_REJECTED",
              "RESOURCE_STOP": "REPLAY_RESOURCE_STOP",
              "VERIFIED_SHARED_AGGREGATION_ONLY": "REPLAY_SHARED_AGGREGATION_ONLY"}.get(
        res.status, "REPLAY_" + res.status)
    pub = res.intervals or {}
    # every serialized (variable, state) key and interval is validated against
    # the ORIGINAL model and the request; the width is recomputed from the
    # endpoints; observed coordinates are preserved as exact point masses
    schema_bad = None
    if pub:
        want = set(queries) | set(ev)
        if set(pub) != want:
            schema_bad = "published keys %s differ from the request %s" % (sorted(pub)[:6], sorted(want)[:6])
        for v in sorted(pub):
            if len(pub[v]) != m.card[v]:
                schema_bad = schema_bad or "variable %d publishes %d states of %d" % (v, len(pub[v]), m.card[v])
            for a, (lo, hi) in enumerate(pub[v]):
                lo, hi = Fr(lo), Fr(hi)
                if not (0 <= lo <= hi <= 1):
                    schema_bad = schema_bad or "variable %d state %d: [%s, %s] is not a valid interval" % (v, a, lo, hi)
            if v in ev and pub[v] != [(Fr(1), Fr(1)) if a == ev[v] else (Fr(0), Fr(0)) for a in range(m.card[v])]:
                schema_bad = schema_bad or "observed variable %d is not an exact point mass" % v
    worst = max((Fr(hi) - Fr(lo) for v in pub for lo, hi in pub[v]), default=Fr(0))
    if schema_bad and status == "REPLAY_VERIFIED":
        status = "REPLAY_REJECTED"
        res.reason = "response schema: %s" % schema_bad
    if status == "REPLAY_VERIFIED" and worst > eps:
        status = "REPLAY_REJECTED"
        res.reason = "the width recomputed from the endpoints %s exceeds the request %s" % (worst, eps)
    return {"status": status, "pipeline_status": res.status, "kind": rec.kind,
            "name": rec.name, "identity": getattr(rec, "identity_key", None),
            "plan_sha_bound": {"model": mh[:16], "evidence": eh[:16], "query": qh[:16]},
            "intervals": {str(v): [[str(lo), str(hi)] for lo, hi in pub[v]]
                          for v in sorted(pub)},
            "requested": sorted(int(v) for v in queries), "observed": {str(v): int(st) for v, st in sorted(ev.items())},
            "request_width": str(eps), "request": dict(rec.request or {}),
            "model_card": [int(c) for c in m.card],
            "radius": str(sum((Fr(v) for v in rec.allocations.values()), Fr(0))),
            "max_width": str(worst), "research": (res.plan or {}).get("research"),
            "executor": {k: str(v) for k, v in ((res.plan or {}).get("executed") or {}).items()
                         if k not in ("lattice",)},
            "checker": {k: (str(v) if not isinstance(v, (dict, list, bool)) else v)
                        for k, v in (res.checker or {}).items() if k != "executor"},
            "failures": [str(x)[:200] for x in ((res.checker or {}).get("failures") or [])[:8]],
            "reason": res.reason, "budget": res.budget or bg.report(),
            "stages": {k: round(v, 4) for k, v in (res.stages or {}).items() if isinstance(v, (int, float))},
            "ledger": (res.plan or {}).get("ledger"),
            "complete_cost": (res.plan or {}).get("complete_cost"),
            "price": price.as_dict()}


def main(argv):
    eps = None
    cap = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--eps":
            eps = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--cap":
            cap = int(argv[i + 1])
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    if len(rest) < 3:
        print(__doc__)
        return 2
    out = replay(rest[0], rest[1], rest[2], eps=eps, cap_bytes=cap)
    txt = json.dumps(out, indent=1, default=str)
    if len(rest) > 3:
        with open(rest[3], "w") as fh:
            fh.write(txt)
    print(txt)
    return 0 if out["status"] == "REPLAY_VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
