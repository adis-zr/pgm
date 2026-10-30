"""The one real public route (contract §3 of the repair priorities).

parse/restrict -> independently verified COMMON exact preprocessing -> candidate
discovery -> complete exact plan records -> reload and validate -> price real
supported executors and checkers -> select -> execute -> independently check ->
publish original-variable results.

Every stage uses ONE shared monotonic budget. Fallback is explicit and charged.
A route whose executor or checker is unregistered is ineligible, and nothing is
silently routed into the original-model solver.
"""
from __future__ import annotations
import sys, time, json, hashlib, os, tempfile
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field

from mdi import (model as M, plan as P, arith as A, solve as S, config as K,
                 preprocess as PRE, plantype as PT, registry as RG,
                 pricing as PR, regions as R, compact as CP, budget as B,
                 regional_check as RC, level2 as L2, residual as RS,
                 collective as CO, modes as MD, coarse as CZ,
                 program as PG, routes as RT, collective_route as CR)


class PipelineError(ValueError):
    pass


def _sha(obj) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()


def model_hashes(model, evidence, queries):
    mh = hashlib.sha256()
    mh.update(("%s;%d;" % (model.net_type, model.nvars)).encode())
    mh.update((",".join(str(c) for c in model.card) + ";").encode())
    for f in model.factors:
        mh.update(("%s|%s|" % (f.scope, [str(x) for x in f.table])).encode())
    eh = hashlib.sha256(
        (",".join("%d:%d" % (v, s) for v, s in sorted(evidence.items()))).encode())
    qh = PT.query_hash(model.nvars, model.card, evidence, queries)
    return mh.hexdigest(), eh.hexdigest(), qh


@dataclass
class Outcome:
    status: str
    reason: str = ""
    intervals: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    prices: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    preprocess: dict = field(default_factory=dict)
    checker: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)
    properties: dict = field(default_factory=dict)


def solve(model, evidence=None, queries=None, max_width=None, wall_s=600.0,
          cap_bytes=None, research_enabled=True, plan_dir=None,
          progress=None):
    """The single public entry point."""
    evidence = dict(evidence or {})
    eps = Fr(max_width if max_width is not None else K.MAX_WIDTH)
    cap_bytes = cap_bytes or K.RESOURCES["arm_rss_bytes"]
    prog = progress or (lambda *a, **k: None)
    bg = B.Budget(wall_s=wall_s,
                  limits={"profile_comparisons": K.CAPS["profile_entry_comparisons"],
                          "local_mass_entries": K.CAPS["local_mass_entries"]},
                  rss_fn=S._rss_bytes, rss_limit=cap_bytes)
    bg.progress = prog
    stages = {}
    # `rejected` is referenced by every stage's RESOURCE_STOP path, so it must
    # exist before the first stage can fail. An expired preprocessing deadline
    # raised UnboundLocalError instead of a typed refusal.
    rejected = []
    out = Outcome(status="INIT")

    # ---------------- stage 1: parse and restrict ----------------
    try:
        bg.enter("parse")
    except B.BudgetExceeded as e:
        # the process is ALREADY over budget before any work: refuse cleanly
        # rather than starting and rather than raising at the caller
        return Outcome(status="RESOURCE_STOP",
                       reason="the shared budget was already exhausted before "
                              "the first stage: %s" % e,
                       budget=bg.report())
    t = time.monotonic()
    try:
        model.validate()
    except M.InvalidModel as e:
        return Outcome(status="INVALID_INPUT", reason=str(e))
    for v, s in evidence.items():
        if not (0 <= v < model.nvars) or not (0 <= s < model.card[v]):
            return Outcome(status="INVALID_INPUT",
                           reason="evidence (%d,%d) out of range" % (v, s))
    r0 = M.restrict(model, evidence)
    if queries is None:
        queries = set(r0.free)
    else:
        # A requested variable outside the model, or pinned by evidence, is an
        # INVALID request. Silently filtering it priced zero requested markers
        # and still returned certified outputs for other variables: asking for
        # {999} on a two-variable model certified variables 0 and 1 instead.
        queries = set(queries)
        unknown = sorted(v for v in queries
                         if not (isinstance(v, int) and 0 <= v < model.nvars))
        if unknown:
            return Outcome(status="INVALID_INPUT",
                           reason="requested variables %s are not variables of "
                                  "this model" % unknown[:8])
        pinned = sorted(v for v in queries if v in evidence)
        if pinned:
            return Outcome(status="INVALID_INPUT",
                           reason="requested variables %s are pinned by the "
                                  "evidence, so they have no free marginal"
                                  % pinned[:8])
        notfree = sorted(v for v in queries if v not in set(r0.free))
        if notfree:
            return Outcome(status="INVALID_INPUT",
                           reason="requested variables %s are not free in the "
                                  "restricted model" % notfree[:8])
    stages["parse_s"] = time.monotonic() - t
    if r0.impossible_factor is not None or r0.constant == 0:
        # the terminal outcome carries the SAME original-model proof
        # requirement as a publication: the named witness is re-derived from
        # the ORIGINAL factor bytes at the evidence, not taken from restrict()
        proof = zero_evidence_proof(model, evidence, r0)
        if proof.get("proved"):
            return Outcome(status="ZERO_EVIDENCE_PROVED", reason=proof["reason"],
                           stages=stages, budget=bg.report(), checker=proof)
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="the restriction claims zero evidence weight but the claim "
                              "does not re-derive from the original model: %s" % proof["reason"],
                       stages=stages, budget=bg.report(), checker=proof)

    if not r0.free:
        # EVERY variable is observed: there is no free marginal to compute.
        # The evidence weight is the exact product of the pinned factor
        # values, already proved positive above, and the publication is the
        # exact restoration of the evidence. Nothing numerical ran, so the
        # certificate is the exact constant itself.
        pub = {v: [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                   for s in range(model.card[v])] for v, st in evidence.items()}
        return Outcome(status="CERTIFIED_FALLBACK_ONLY",
                       reason="every variable is observed; the evidence weight "
                              "is the exact pinned constant %s > 0 and the "
                              "publication restores the evidence exactly"
                              % r0.constant,
                       intervals=pub, plan={"chosen": "identity",
                                            "kind": "identity",
                                            "why": "no free variable"},
                       stages=stages, budget=bg.report(),
                       checker={"status": "VERIFIED",
                                "method": "exact pinned constant; no free "
                                          "variable, no contraction",
                                "independent_aggregation_checked": True})
    mh, eh, qh = model_hashes(model, evidence, queries)

    # ---------------- stage 2: common exact preprocessing ----------------
    try:
        bg.enter("preprocess")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e), stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    try:
        simp = PRE.simplify(r0)
        PRE.verify_identities(r0, simp)        # independent verification
    except PRE.PreprocessError as e:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="exact preprocessing failed its own independent "
                              "verification: %s" % e,
                       stages=stages, budget=bg.report())
    if simp.impossible is not None:
        proof = zero_evidence_proof(model, evidence, r0, named=simp.impossible)
        if proof.get("proved"):
            return Outcome(status="ZERO_EVIDENCE_PROVED", reason=proof["reason"],
                           stages=stages, budget=bg.report(), checker=proof)
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="preprocessing claims factor %d is identically zero but the "
                              "claim does not re-derive from the original model: %s"
                              % (simp.impossible, proof["reason"]),
                       stages=stages, budget=bg.report(), checker=proof)
    r = M.Restricted(model=model, evidence=evidence, factors=simp.factors,
                     free=list(simp.free), card=dict(simp.card),
                     constant=r0.constant, impossible_factor=None)
    stages["preprocess_s"] = time.monotonic() - t
    out.preprocess = simp.identity()
    prog("preprocess", "%d constants, %d splits"
         % (len(simp.removed_constants), len(simp.split_pairs)))

    nq = sum(r.card[v] for v in sorted(queries))

    # ---------------- stage 3: discovery and plan records ----------------
    try:
        bg.enter("discover")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    records, prices = [], []
    rejected = []
    _shared_exhausted = None

    # identity, always retained -- as a CANDIDATE. When no generic ordering
    # fits the byte cap the identity route is recorded as an admission
    # refusal with its concrete forecast and discovery CONTINUES: a research
    # route whose reduced model fits may still certify. Identity's
    # infeasibility used to end the invocation before any research candidate
    # was examined.
    sel = P.choose_plan(r.free, r.card, r.factors, 64, cap_bytes)
    if sel["chosen"] is None:
        best = sel["candidates"][0] if sel["candidates"] else None
        rejected.append({"name": "identity",
                         "reason": "no generic ordering fits the byte cap; "
                                   "best forecast %s" % (best[1] if best else None)})
        ipl = iest = None
    else:
        ipl, iest = sel["chosen"]
    if ipl is not None:
        # the identity PROGRAM: the chosen order, the precision its depth bound
        # requires and the input-derived exponent range -- recorded, not rechosen
        _E = S._compiled_depth_bound(ipl, r)
        try:
            _p = A.choose_precision(_E, eps, 64)
        except A.NumericalRefusal as e:
            _p = None
            rejected.append({"name": "identity", "reason": "no usable precision: %s" % e})
        if _p is not None:
            _B, _Q, _T = S._exponent_bounds(r)
            _emin, _emax = -(_B + _Q + 256), (_T + _Q + 256)
            from mdi import routes as _RT
            iprog = _RT.identity_program(ipl.order, _p, _emin, _emax, queries,
                                         max(80, _p + 16))
    if ipl is not None and _p is not None:
        iprice = PR.price_identity_plan(ipl, iest, nq, _p,
                                        {"constants": len(simp.removed_constants),
                                         "splits": len(simp.split_pairs)})
        isup = PT.supported("identity")
        iprops = PT.PlanProperties()
        iprops.set("mathematically_certified")          # exact elimination
        if isup["executor_supported"]:
            iprops.set("executor_supported")
        if isup["checker_supported"]:
            iprops.set("checker_supported")
        iprops.set("complete_cost_priced")
        irec = PT.PlanRecord(
            kind="identity", name="identity", model_sha256=mh, evidence_sha256=eh,
            query_sha256=qh, preprocess_identity=simp.identity(),
            factor_ownership=[(f.origin, "bag") for f in r.factors],
            factor_scopes=[(f.origin, tuple(f.scope), tuple(f.card))
                           for f in r.factors],
            region_membership=[], cell_membership=[],
            allocations={"transformation": Fr(0)},
            executor_id="mdi.registry:pipeline_identity_executor",
            checker_id="mdi.registry:pipeline_identity_checker",
            numerical={"precision": _p, "mode": "P", "emin": _emin, "emax": _emax},
            cost_counters={k: c.as_dict() for k, c in iprice.counters.items()},
            storage_schedule={"peak_live_entries": iest["peak_live_entries"],
                              "identity": executable_identity("identity", iprog)},
            rejected_alternatives=[], properties=iprops, program=iprog)
        irec.identity_key = irec.storage_schedule["identity"]
        records.append((irec, iprice, {"plan": ipl, "est": iest}))
        prices.append(iprice)

    # ---- every research route, as a PERSISTED PROGRAM ----
    # Each candidate is BUILT here (discovery is paid work) and recorded as a
    # program: coarsening witnesses, deletion certificates, the collective
    # record, the final elimination order. Execution and checking later read
    # the program back from disk and reconstruct everything from the original
    # model; the live objects built here are not passed to them.
    if research_enabled:
        _discover_programs(r, queries, nq, mh, eh, qh, simp, bg, wall_s,
                           records, prices, rejected, cap_bytes)
        _shared_exhausted = getattr(_discover_programs, "_shared", None)
        if _shared_exhausted is not None:
            _discover_programs._shared = None
    stages["discover_s"] = time.monotonic() - t
    if _shared_exhausted is not None:
        # a consumed SHARED work counter stops the invocation; it is not a
        # per-candidate refusal that a fallback may proceed past
        return Outcome(status="RESOURCE_STOP",
                       reason="the shared work budget was exhausted during "
                              "discovery: %s" % _shared_exhausted,
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    out.rejected = rejected
    if not records:
        return Outcome(status="RESOURCE_STOP",
                       reason="no route was admitted: identity does not fit the "
                              "byte cap and every research candidate declined",
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())

    # ---------------- stage 4: persist, reload, validate ----------------
    try:
        bg.enter("persist")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    # The record must be WRITTEN first and then read back FROM DISK, so the
    # on-disk bytes are the authority for everything downstream. Reloading
    # from an in-memory string before writing meant a corrupted written plan
    # still produced a certified result: the file was never read again.
    if not plan_dir:
        plan_dir = tempfile.mkdtemp(prefix="mdi_plans_")
    os.makedirs(plan_dir, exist_ok=True)
    reloaded = []
    for rec, price, payload in records:
        # the file is named by the candidate's STABLE IDENTITY (the law/program
        # it represents), so two candidates on one partition never overwrite
        ident = (rec.storage_schedule or {}).get("identity") or rec.name.replace(":", "_")
        path = os.path.join(plan_dir, "%s.plan.json" % ident)
        try:
            txt = rec.to_json()
            with open(path, "w") as fh:
                fh.write(txt)
            # read the bytes BACK from the filesystem
            with open(path, "r") as fh:
                ondisk = fh.read()
            if ondisk != txt:
                raise PT.PlanError("the persisted plan does not match what "
                                   "was written")
            back = PT.PlanRecord.from_json(ondisk)
            if back.to_json() != ondisk:
                raise PT.PlanError("plan record is not byte-identical after a "
                                   "round trip through disk")
            # bind the SEMANTIC fields too, against the original restricted
            # model and the preprocessing proof the current inputs produce
            # DISCARD discovery's live payload and price: from here on the
            # loaded record is the only input, bound at the ONE boundary
            rprice = bind_loaded(back, mh, eh, qh, r, simp, queries, nq, cap_bytes,
                                 bg=bg)
        except (PT.PlanError, ValueError, OSError) as e:
            rejected.append({"name": rec.name,
                             "reason": "plan record failed persist/reload/binding: %s"
                                       % e})
            continue
        except B.BudgetExceeded as e:
            return Outcome(status="RESOURCE_STOP",
                           reason="the shared budget was exhausted while re-pricing "
                                  "loaded programs: %s" % e,
                           rejected=rejected, stages=stages, budget=bg.report())
        back.source_path = path
        reloaded.append((back, rprice, None))
    del records
    stages["persist_s"] = time.monotonic() - t
    if not reloaded:
        return Outcome(status="RESOURCE_STOP",
                       reason="no plan record survived reload",
                       rejected=rejected, stages=stages, budget=bg.report())

    # ---------------- stage 5: price and select ----------------
    try:
        bg.enter("select")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    for rec, price, payload in reloaded:
        bad = loaded_admission(rec, price, cap_bytes=cap_bytes, bg=bg)
        if bad and price.eligible:
            price.eligible = False
            price.ineligible_reason = bad
    # explicit DEDUPLICATION by represented-law identity, never by generator
    # label: two loaded records with the same identity key are the same
    # program; the second is recorded as a duplicate, not lost
    by_id = {}
    uniq = []
    for rec, price, pl in reloaded:
        key = getattr(rec, "identity_key", None) or rec.name
        if key in by_id:
            rejected.append({"name": rec.name,
                             "reason": "duplicate of %s under the explicit identity "
                                       "rule (same evaluator, canonical modes, Q/deltas, "
                                       "retained and dropped sets, witness)" % by_id[key]})
            continue
        by_id[key] = rec.name
        uniq.append((rec, price, pl))
    reloaded = uniq
    cmp = PR.compare([p for _, p, _ in reloaded], cap_bytes=cap_bytes)
    stages["select_s"] = time.monotonic() - t
    out.prices = [dict(p.as_dict(), identity=getattr(rec, "identity_key", None))
                  for rec, p, _ in reloaded]
    if cmp["chosen"] is None:
        return Outcome(status="RESOURCE_STOP",
                       reason="every route is ineligible or over the byte cap",
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    chosen_name = cmp["chosen"]["name"]
    chosen_rec = cmp["chosen"]["record"]
    chosen = next(x for x in reloaded if x[1] is chosen_rec)
    crec, cprice, cpayload = chosen
    crec.properties.set("selected")
    for x in cmp["all"]:
        if x["name"] != chosen_name and (x["ineligible_reason"] or
                                         x["admission_refusal"]):
            rejected.append({"name": x["name"],
                             "reason": x["ineligible_reason"]
                                       or x["admission_refusal"]})
    out.plan = {"chosen": chosen_name, "kind": crec.kind,
                "why": cmp["rule"],
                "properties": crec.properties.as_dict()}
    prog("select", "%s (%s)" % (chosen_name, crec.kind))

    # ---------------- stages 6-7: the ONE loaded-object boundary ----------------
    out.plan["executed_kind"] = crec.kind
    res = run_loaded(crec, model, evidence, queries, r, bg, eps, cap_bytes, prog,
                     out=out, rejected=rejected, stages=stages)
    return res


def run_loaded(crec, model, evidence, queries, r, bg, eps, cap_bytes, prog=None,
               out=None, rejected=None, stages=None, wrap=None):
    """Execute and independently check ONE loaded, bound plan record. This is
    the single validation/dispatch boundary: the public pipeline and
    `mdi.replay` both call it, so a fresh process enforces exactly the limits,
    role binding, publication rule, research agreement and status derivation
    the pipeline does.

    `crec` must already have passed `bind_check`; its roles are resolved from
    the record and must be the registered ones; the executor runs under the
    shared budget; the checker named by the record verifies; the research
    label follows the checker's verified transformations. `wrap(stage, fn)`
    optionally wraps the executor and checker calls (the acceptance matrix
    counts operations through it; it changes nothing else)."""
    _w = wrap or (lambda stage, f: f())
    out = out if out is not None else Outcome(status="INIT")
    rejected = rejected if rejected is not None else []
    stages = stages if stages is not None else {}
    try:
        bg.enter("execute")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    radius = sum((Fr(v) for v in crec.allocations.values()), Fr(0))
    num_eps = eps - 2 * radius - K.PUBLICATION_RESERVE
    if num_eps <= 0:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="the charged radius consumes the whole contract",
                       prices=out.prices, stages=stages, budget=bg.report())
    exec_meta = {}
    try:
        pexec = _resolve_role(crec.executor_id)
        if pexec is not PT.dispatch_pipeline(crec.kind):
            return Outcome(status="RESOURCE_STOP",
                           reason="the persisted executor %r is not the pipeline "
                                  "executor registered for kind %r"
                                  % (crec.executor_id, crec.kind),
                           prices=out.prices, rejected=rejected,
                           stages=stages, budget=bg.report())
        checker = _resolve_role(crec.checker_id)
        if checker is not RG.PIPELINE_CHECKERS.get(crec.kind):
            return Outcome(status="RESOURCE_STOP",
                           reason="the persisted checker %r is not the pipeline "
                                  "checker registered for kind %r"
                                  % (crec.checker_id, crec.kind),
                           prices=out.prices, rejected=rejected,
                           stages=stages, budget=bg.report())
        ectx = {"model": model, "evidence": evidence, "eps": num_eps,
                "cap_bytes": cap_bytes, "remaining": bg.remaining,
                "restricted": r, "queries": queries, "budget": bg,
                "program": getattr(crec, "parsed_program", None),
                "progress": prog or (lambda *a, **k: None)}
        raw = _w("execute", lambda: pexec(ectx))
        exec_meta = ectx.get("meta") or {}
    except PT.ExecutorRefusal as e:
        return Outcome(status=e.status, reason=e.reason, prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report())
    except PT.PlanError as e:
        return Outcome(status="RESOURCE_STOP",
                       reason="pipeline dispatch refused: %s" % e, prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report())
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e), prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report())
    stages["execute_s"] = time.monotonic() - t
    crec.properties.set("producer_complete")

    # outward expansion by the certified radius, once, plus the publication
    # reserve the checker's own rounding may consume
    pub, worst = {}, Fr(0)
    pad = radius + K.PUBLICATION_RESERVE
    for v in sorted(raw):
        rows = []
        for (lo, hi) in raw[v]:
            lo2, hi2 = Fr(lo), Fr(hi)
            if not (lo2 == hi2 and (lo2 == 0 or lo2 == 1) and radius == 0):
                lo2 = max(Fr(0), lo2 - pad)
                hi2 = min(Fr(1), hi2 + pad)
            if hi2 - lo2 > worst:
                worst = hi2 - lo2
            rows.append((lo2, hi2))
        pub[v] = rows
    if crec.kind != "identity":
        pub = {v: pub[v] for v in sorted(queries) if v in pub}
        missing_q = [v for v in sorted(queries) if v not in pub]
        if missing_q:
            return Outcome(status="NUMERICAL_REFUSAL",
                           reason="the executor published no row for requested "
                                  "variables %s" % missing_q[:8],
                           prices=out.prices, rejected=rejected, stages=stages,
                           budget=bg.report())
    for v, st in evidence.items():
        pub[v] = [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                  for s in range(model.card[v])]
    resp = {v: pub[v] for v in sorted(pub) if v in queries or v in evidence}
    bad = response_schema_violation(resp, model, evidence, queries)
    if bad:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="the response does not bind to the original request: %s" % bad,
                       prices=out.prices, rejected=rejected, stages=stages, budget=bg.report())

    # ---------------- independent check ----------------
    try:
        bg.enter("check")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    check_dl = bg.deadline_fn("check")
    t = time.monotonic()
    try:
        if crec.kind == "identity":
            ok, fails, meta = _w("check", lambda: checker(
                model, evidence, pub, eps, deadline_s=bg.remaining(),
                cap_bytes=cap_bytes, program=crec.parsed_program))
            meta = dict(meta or {})
            meta["kind"] = "identity"
            bg.check("after-identity-check")
        else:
            qpub = {v: pub[v] for v in sorted(queries)}
            ok, fails, meta = _w("check", lambda: checker(
                r, queries, crec.parsed_program, qpub, eps, deadline=check_dl,
                budget=bg, exec_record=exec_meta))
            meta = dict(meta or {})
            meta["kind"] = crec.kind
            meta["executor"] = exec_meta
    except B.BudgetExceeded as e:
        stages["check_s"] = time.monotonic() - t
        return Outcome(status="RESOURCE_STOP",
                       reason="producer completed but independent verification "
                              "did not finish: %s" % e,
                       intervals=pub, prices=out.prices, rejected=rejected,
                       stages=stages, budget=bg.report(),
                       checker={"status": "VERIFICATION_INCOMPLETE",
                                "verified_coordinates": 0,
                                "verified_subset": None},
                       properties=crec.properties.as_dict())
    except Exception as e:
        stages["check_s"] = time.monotonic() - t
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="checker raised: %s: %s" % (type(e).__name__, e),
                       prices=out.prices, stages=stages, budget=bg.report())
    stages["check_s"] = time.monotonic() - t
    if ok and crec.kind != "identity":
        # the ROUTE-SPECIFIC ERROR LEDGER: the checker's own verified components
        # against the saved allocations (finite, nonnegative, within the frozen
        # caps, applicable to this route, unused components exactly zero, the
        # saved total at least the verified expansion)
        led = (meta or {}).get("ledger") or {}
        bad = ledger_violation(led, crec.allocations, crec.parsed_program)
        if bad:
            return Outcome(status="NUMERICAL_REFUSAL",
                           reason="invalid proof budget: %s" % bad,
                           checker={"status": "FAILED", "failures": [bad], "ledger": led},
                           prices=out.prices, rejected=rejected, stages=stages,
                           budget=bg.report(), properties=crec.properties.as_dict())
        out.plan["ledger"] = {"verified": led, "saved": {k: str(Fr(v)) for k, v in crec.allocations.items()},
                              "saved_total": str(radius),
                              "necessary_expansion": str(sum((Fr(v) for v in led.values()), Fr(0)))}
    if not ok:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="independent checker REJECTED the publication",
                       checker={"status": "FAILED",
                                "failures": [str(x)[:200] for x in fails[:6]]},
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report(),
                       properties=crec.properties.as_dict())
    try:
        bg.check("publish")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP",
                       reason="verification completed but the shared budget "
                              "was exhausted before publication: %s" % e,
                       intervals=pub, prices=out.prices, rejected=rejected,
                       stages=stages, budget=bg.report(),
                       checker={"status": "VERIFIED_BUT_UNPUBLISHED"},
                       properties=crec.properties.as_dict())
    _agg = (meta or {}).get("independent_aggregation_checked")
    _agg_required = (crec.kind == "identity")
    _agg_ok = (not _agg_required) or bool(_agg)
    out.plan["executed_kind"] = crec.kind
    if worst > eps:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="the published width exceeds the contract",
                       intervals=pub, plan=out.plan, prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report(),
                       preprocess=out.preprocess,
                       checker={"status": "VERIFIED", **(meta or {})},
                       properties=crec.properties.as_dict())
    if not _agg_ok:
        return Outcome(
            status="VERIFIED_SHARED_AGGREGATION_ONLY",
            reason="every coordinate passed independent containment, but the "
                   "independent AGGREGATION check could not run on this "
                   "input: the free joint space exceeds the declared "
                   "enumeration cap, so producer and checker share one "
                   "aggregate implementation. The contract's complete "
                   "independently verified status is NOT claimed.",
            intervals=pub, plan=out.plan, prices=out.prices,
            rejected=rejected, stages=stages, budget=bg.report(),
            preprocess=out.preprocess,
            checker={"status": "VERIFIED_WITHOUT_INDEPENDENT_AGGREGATION",
                     **(meta or {})},
            properties=crec.properties.as_dict())
    crec.properties.set("independently_verified")
    crec.properties.set("publication_contract_met")
    pub = {v: pub[v] for v in sorted(pub) if v in queries or v in evidence}
    _claimed = (getattr(crec, "parsed_program", None) or {}).get("research") or {}
    _research = (meta or {}).get("verified_research") or {}
    if crec.kind != "identity":
        for _k in ("cells_merged_regions", "deleted_states", "collective"):
            if _claimed.get(_k) != _research.get(_k):
                return Outcome(
                    status="NUMERICAL_REFUSAL",
                    reason="the program claims research %s=%r but the checker "
                           "verified %r" % (_k, _claimed.get(_k), _research.get(_k)),
                    intervals=pub, plan=out.plan, prices=out.prices,
                    rejected=rejected, stages=stages, budget=bg.report(),
                    checker={"status": "VERIFIED", **(meta or {})},
                    properties=crec.properties.as_dict())
    if crec.kind == "identity":
        status = "CERTIFIED_FALLBACK_ONLY"
    elif _research.get("qualifies"):
        status = "CERTIFIED_RESEARCH_ROUTE"
    else:
        status = "CERTIFIED_FALLBACK_ONLY"
        out.plan["note"] = ("the selected program grouped regions but merged no "
                            "cells, deleted no state and ran no collective "
                            "evaluator, so it does not qualify as a research "
                            "route")
    out.plan["research"] = _research
    out.plan["identity"] = getattr(crec, "identity_key", None)
    if exec_meta:
        out.plan["executed"] = {k: v for k, v in exec_meta.items()
                                if k not in ("lattice",)}
    out.plan["complete_cost"] = _complete_cost(out.prices, rejected, exec_meta,
                                               meta, stages)
    return Outcome(status=status, intervals=pub, plan=out.plan,
                   prices=out.prices, rejected=rejected, stages=stages,
                   budget=bg.report(), preprocess=out.preprocess,
                   checker={"status": "VERIFIED", **(meta or {})},
                   properties=crec.properties.as_dict())


LEDGER_CAPS = {"regional": K.RADII["regional_coarsening_total"],
               "deletion": K.RADII["state_deletion_total"],
               "collective_fit": K.RADII["collective_fit_and_rounding"],
               "collective_rounding": K.RADII["collective_fit_and_rounding"],
               "gaussian_quadrature": K.RADII["gaussian_quadrature"]}


def ledger_violation(verified, saved, prog):
    """Compare the checker's verified component radii with the SAVED
    allocations of the loaded record. Every saved allowance must be an exact
    nonnegative rational, within its frozen cap, applicable to the route the
    program actually runs (a component the program does not use must be
    exactly zero on both sides), and at least the verified value (a
    conservative saved allowance is valid); the saved total must contain the
    necessary expansion. Returns a reason or None."""
    saved = {k: Fr(v) for k, v in saved.items()}
    verified = {k: Fr(v) for k, v in verified.items()}
    levels = len(prog["scales"])
    coll = prog["collective"]
    applicable = set()
    for k in range(levels):
        applicable.add("regional_level%d" % (k + 1))
        applicable.add("deletion_level%d" % (k + 1))
    if coll is not None:
        applicable |= {"collective_fit", "collective_rounding"}
        if coll["evaluator"] != "statistic":
            applicable.add("gaussian_quadrature")
    for k, v in saved.items():
        if v < 0:
            return "saved allowance %s is negative (%s)" % (k, v)
        base = k.split("_level")[0] if k.startswith(("regional", "deletion")) else k
        cap = LEDGER_CAPS.get(base)
        if cap is None:
            return "saved allowance %s is not a component of any route" % k
        if v > cap:
            return "saved allowance %s = %s exceeds its frozen cap %s" % (k, v, cap)
        if k not in applicable and v != 0:
            return "saved allowance %s = %s is not applicable to this route and is not zero" % (k, v)
    for k, v in verified.items():
        if v < 0:
            return "verified component %s is negative (%s)" % (k, v)
        if k not in applicable and v != 0:
            return "verified component %s = %s is not applicable to this route" % (k, v)
        if k in applicable and saved.get(k) is None:
            return "the record saves no allowance for the verified component %s" % k
        if k in applicable and saved[k] < v:
            return ("saved allowance %s = %s is below the checker's verified %s" % (k, saved[k], v))
    for k in applicable:
        if k not in saved:
            return "the record saves no allowance for component %s" % k
    sum_saved = sum(saved.values(), Fr(0))
    sum_verified = sum(verified.values(), Fr(0))
    reg = sum((saved[k] for k in saved if k.startswith("regional_level")), Fr(0))
    dele = sum((saved[k] for k in saved if k.startswith("deletion_level")), Fr(0))
    if reg > LEDGER_CAPS["regional"]:
        return "the regional allowances total %s above the frozen cap %s" % (reg, LEDGER_CAPS["regional"])
    if dele > LEDGER_CAPS["deletion"]:
        return "the deletion allowances total %s above the frozen cap %s" % (dele, LEDGER_CAPS["deletion"])
    if sum_saved < sum_verified:
        return "the saved total %s is below the necessary expansion %s" % (sum_saved, sum_verified)
    return None


def response_schema_violation(pub, model, evidence, queries):
    """The regular response schema, bound to the ORIGINAL request: exactly the
    requested variables plus the observed coordinates the public API returns,
    one row per model state, exact rationals, lower <= upper inside [0, 1],
    and every observed coordinate an exact point mass at its observed state.
    Returns a reason or None."""
    want = set(queries) | set(evidence)
    got = set(pub)
    if got != want:
        return "response keys %s differ from the request %s" % (sorted(got)[:8], sorted(want)[:8])
    for v in sorted(pub):
        rows = pub[v]
        if len(rows) != model.card[v]:
            return "variable %d publishes %d states, the model declares %d" % (v, len(rows), model.card[v])
        for a, (lo, hi) in enumerate(rows):
            lo, hi = Fr(lo), Fr(hi)
            if lo > hi:
                return "variable %d state %d: lower %s exceeds upper %s" % (v, a, lo, hi)
            if lo < 0 or hi > 1:
                return "variable %d state %d: endpoints outside [0, 1]" % (v, a)
        if v in evidence:
            st = evidence[v]
            if any((Fr(lo), Fr(hi)) != ((Fr(1), Fr(1)) if a == st else (Fr(0), Fr(0)))
                   for a, (lo, hi) in enumerate(rows)):
                return "observed variable %d is not published as the point mass at state %d" % (v, st)
    return None


def zero_evidence_proof(model, evidence, r0, named=None):
    """Re-derive a zero-evidence claim from the ORIGINAL factor tables at the
    evidence assignment (the checker's own witness): either a named factor is
    identically zero on every free assignment consistent with the evidence,
    or a fully pinned factor evaluates to exactly zero. Returns a dict with
    `proved` and the named witness."""
    import itertools
    ev = dict(evidence)
    cands = [named] if named is not None else []
    if r0.impossible_factor is not None and r0.impossible_factor not in cands:
        cands.append(r0.impossible_factor)
    for f in model.factors:
        if f.origin in cands or named is None:
            free = [v for v in f.scope if v not in ev]
            if any(len(free) > 12 for _ in [0]):
                continue
            allzero = True
            for ass in itertools.product(*[range(model.card[v]) for v in free]):
                a = dict(ev)
                a.update(dict(zip(free, ass)))
                if Fr(f.at(a)) != 0:
                    allzero = False
                    break
            if allzero:
                return {"proved": True, "witness_factor": f.origin,
                        "reason": "original factor %d is identically zero on every assignment "
                                  "consistent with the evidence (re-derived from the original "
                                  "table, %d free variable(s))" % (f.origin, len(free)),
                        "method": "checker-owned enumeration of the original factor"}
    return {"proved": False, "witness_factor": None,
            "reason": "no original factor is identically zero at the evidence (candidates %s)"
                      % cands[:4]}


def executable_identity(kind, prog_json):
    """The ONE executable identity of a program, derived from the RAW program
    JSON alone (discovery and binding call this same function): kind, the
    coarsening witness key, the collective record's canonical modes, Q or GF
    tolerances, actual integer statistics after rounding, grid parameters,
    retained/dropped/masked sets, and the executable settings (saved order,
    precision, arithmetic, checker). Two records are duplicates only when
    every one of these agrees; a shared generator name never decides."""
    raw = json.loads(json.dumps(prog_json, default=str))
    prog = PG.validate_program(raw)
    scales_key = tuple(hashlib.sha256(json.dumps(sc, sort_keys=True).encode()).hexdigest()[:12]
                       for sc in (raw.get("scales") or []))
    executable = {"order": [int(x) for x in (raw.get("order") or [])],
                  "precision": int(raw.get("precision") or 0),
                  "arithmetic": {k: str(v) for k, v in (raw.get("arithmetic") or {}).items()},
                  "checker": {k: str(v) for k, v in (raw.get("checker") or {}).items()},
                  "queries": sorted(int(v) for v in (raw.get("queries") or []))}
    if prog.get("collective") is not None:
        ident, _ikey = CR.canonical_identity(prog["collective"], scales_key, executable=executable)
    elif kind == "identity":
        ident = hashlib.sha256(json.dumps(executable, sort_keys=True).encode()).hexdigest()[:16]
    else:
        ident = hashlib.sha256(("regional|" + "|".join(scales_key) + "|"
                                + json.dumps(executable, sort_keys=True)).encode()).hexdigest()[:16]
    return "%s-%s" % (kind, ident)


def loaded_admission(rec, price, cap_bytes=None, bg=None):
    """The ONE admission rule a bound loaded record must pass before it may be
    selected or replayed: registered roles for its kind and an eligible
    re-derived price (bounded counters all known, within every declared cap,
    forecast metered entries within the shared cap). Returns the named reason
    or None. The pipeline applies it at selection; mdi.replay applies it after
    binding, so a fresh process cannot run what the pipeline would refuse."""
    if not price.eligible:
        return price.ineligible_reason or "the re-derived price is ineligible"
    miss = rec.properties.may_execute_as_certified_route()
    miss = [x for x in miss if x not in ("selected", "complete_cost_priced")]
    if miss:
        return ("missing %s; an unregistered executor or checker makes the route "
                "ineligible" % miss)
    if not rec.properties.complete_cost_priced:
        return "the record was never completely priced"
    # byte forecasts against the declared cap (the SAME rule compare() applies)
    if cap_bytes:
        for who, c in (("producer", price.bytes_producer), ("checker", price.bytes_checker)):
            if c is not None and c.value is not None and int(c.value) > cap_bytes:
                return ("the %s byte forecast %d exceeds the %d cap" % (who, int(c.value), cap_bytes))
    # the forecast metered entries must fit what REMAINS of the shared meter
    if bg is not None:
        fc = price.counters.get("metered_entries_forecast")
        lim = bg.limits.get("local_mass_entries")
        if fc is not None and fc.value is not None and lim is not None:
            remaining = lim - bg.used.get("local_mass_entries", 0)
            if int(fc.value) > remaining:
                return ("the forecast metered entry visits %d exceed the REMAINING shared "
                        "meter %d of %d" % (int(fc.value), remaining, lim))
    return None


def bind_loaded(back, mh, eh, qh, r, simp, queries, nq, cap_bytes, bg=None):
    """The single BINDING of a loaded record: hashes, scopes, preprocessing
    proof, roles, no completion flags, program/kind agreement, requested set,
    and a RE-DERIVED price on the saved order that must equal the recorded
    counters. Used by the pipeline after read-back and by mdi.replay."""
    back.bind_check(mh, eh, qh, restricted=r, preprocess_identity=simp.identity(),
                    max_precision=4096)
    if getattr(back, "parsed_program", None) is None:
        raise PT.PlanError("a %s plan reloaded without a program" % back.kind)
    if sorted(back.parsed_program["queries"]) != sorted(queries):
        raise PT.PlanError("the reloaded program's requested set differs from "
                           "the current request")
    rprice = _reprice_loaded(back, r, queries, nq, simp, cap_bytes, bg=bg)
    bad = _price_disagrees(back.cost_counters, rprice)
    if bad:
        raise PT.PlanError("the recorded cost counters do not match the price "
                           "re-derived from the loaded program on its SAVED "
                           "order: %s" % bad)
    # the executable identity is RE-DERIVED from the loaded program; the stored
    # name is checked against it, never trusted
    own = executable_identity(back.kind, back.program)
    stored = (back.storage_schedule or {}).get("identity")
    if stored is not None and stored != own:
        raise PT.PlanError("the stored identity %s is not the identity re-derived from the "
                           "loaded program %s" % (stored, own))
    back.identity_key = own
    # the saved allocations must be exactly the program's radii per component
    want = RT.allocations_for_program(back.parsed_program) if back.kind != "identity" else {}
    saved = {k: Fr(v) for k, v in back.allocations.items()}
    if back.kind != "identity" and saved != want:
        raise PT.PlanError("the saved allocations %s are not the program's radii %s"
                           % ({k: str(v) for k, v in saved.items()}, {k: str(v) for k, v in want.items()}))
    return rprice


def _producer_reduced_contract(r, regions, coarse, rds, queries,
                               deadline=None, budget=None):
    """The PRODUCER's own contraction of the reduced cell model, BY ELIMINATION.

    Independent of regional_check._reduced_message_passing: it owns its
    factors, eliminates cell variables in a min-degree order, and reads each
    requested marker from its own cell marginals. Sharing is limited to the
    validated structural data (regions, cells, compact projections) and exact
    rational arithmetic.

    r8 formed a GLOBAL JOINT instead -- it multiplied every table into one
    table and never called its own `marginalize` helper -- which destroyed the
    factorization r7 had. A 20-variable width-one chain that completed under
    r7 allocated 8,192 joint entries and refused; even a 13-variable equality
    chain with only two feasible configurations failed. Independence and
    factorized execution are SIMULTANEOUS requirements: separating the two
    whole-model contractions must not cost the structure that makes the
    computation affordable.
    """
    from mdi import compact as CP, config as KK
    ncell = [len(c.cells) for c in coarse]
    projected, _ = CP.project_crossings(r, regions, coarse, rds)
    nreg = len(regions)
    cap = KK.CAPS["checker_contraction_space"]

    def _charge(n_entries, where):
        if budget is not None:
            budget.charge("local_mass_entries", max(1, n_entries), where)

    # ---- factors over CELL variables, as (scope tuple, {assignment: value})
    # Each is admitted BEFORE it is materialized, so an oversized projection
    # refuses rather than being built first.
    tables = []
    for i in range(nreg):
        ent = {}
        for ci in range(ncell[i]):
            mv = Fr(coarse[i].M[ci])
            if mv != 0:
                ent[(ci,)] = mv
        tables.append(((i,), ent))
    for pc in projected:
        rs = tuple(pc.regions)
        want = 1
        for i in rs:
            want *= ncell[i]
        if want > cap:
            raise RuntimeError(
                "a projected crossing over regions %s would need %d entries, "
                "above the %d cap; admitted BEFORE materializing it"
                % (rs, want, cap))
        import itertools as _it
        ent = {}
        for tup in _it.product(*[range(ncell[i]) for i in rs]):
            if deadline is not None:
                deadline()
            v = pc.value({rs[k]: tup[k] for k in range(len(rs))})
            if v != 0:
                ent[tup] = v
        _charge(len(ent), "producer projected crossing")
        tables.append((rs, ent))

    def multiply(t1, t2):
        sc1, e1 = t1
        sc2, e2 = t2
        out_sc = tuple(sorted(set(sc1) | set(sc2)))
        pos = {v: k for k, v in enumerate(out_sc)}
        shared = sorted(set(sc1) & set(sc2))
        # index the smaller table by its shared-variable key
        idx = {}
        for a2, v2 in e2.items():
            m2 = {sc2[k]: a2[k] for k in range(len(sc2))}
            key = tuple(m2[v] for v in shared)
            idx.setdefault(key, []).append((a2, v2))
        out = {}
        for a1, v1 in e1.items():
            m1 = {sc1[k]: a1[k] for k in range(len(sc1))}
            key = tuple(m1[v] for v in shared)
            for a2, v2 in idx.get(key, ()):
                if deadline is not None:
                    deadline()
                m2 = {sc2[k]: a2[k] for k in range(len(sc2))}
                kk = [0] * len(out_sc)
                for v, av in list(m1.items()) + list(m2.items()):
                    kk[pos[v]] = av
                k = tuple(kk)
                if k not in out and len(out) >= cap:
                    raise RuntimeError(
                        "the producer's elimination reached the %d-entry cap "
                        "while combining scopes %s and %s" % (cap, sc1, sc2))
                nv = out.get(k, Fr(0)) + v1 * v2
                # EXACT rational growth is bounded. Two legal inputs with
                # 40001-bit entries produced an 80003-bit mass despite the
                # declared 65536-bit cap, because exact multiplication was
                # never checked. A resource contract that only bounds entry
                # COUNTS does not bound exact arithmetic.
                if (nv.numerator.bit_length() > KK.CAPS["rational_bit_length"]
                        or nv.denominator.bit_length()
                        > KK.CAPS["rational_bit_length"]):
                    raise RuntimeError(
                        "the producer's elimination produced a %d-bit "
                        "rational while combining scopes %s and %s, above the "
                        "declared %d-bit cap"
                        % (max(nv.numerator.bit_length(),
                               nv.denominator.bit_length()), sc1, sc2,
                           KK.CAPS["rational_bit_length"]))
                out[k] = nv
        return (out_sc, out)

    def marginalize(t, var):
        sc, e = t
        if var not in sc:
            return t
        k = sc.index(var)
        out_sc = tuple(v for v in sc if v != var)
        out = {}
        for a, v in e.items():
            key = tuple(a[j] for j in range(len(sc)) if j != k)
            out[key] = out.get(key, Fr(0)) + v
        return (out_sc, out)

    def eliminate(tabs, keep):
        """Sum out every cell variable except `keep`, min-degree order."""
        tabs = list(tabs)
        remaining = sorted({v for sc, _e in tabs for v in sc} - {keep})
        while remaining:
            # choose the variable whose combined scope is smallest
            best, best_cost = None, None
            for v in remaining:
                touch = [t for t in tabs if v in t[0]]
                sc = set()
                for t in touch:
                    sc |= set(t[0])
                cost = 1
                for u in sc:
                    cost *= ncell[u]
                if best_cost is None or cost < best_cost:
                    best, best_cost = v, cost
            v = best
            touch = [t for t in tabs if v in t[0]]
            rest = [t for t in tabs if v not in t[0]]
            acc = touch[0]
            for t in touch[1:]:
                acc = multiply(acc, t)
            acc = marginalize(acc, v)
            _charge(len(acc[1]), "producer elimination")
            tabs = rest + [acc]
            remaining.remove(v)
        acc = ((), {(): Fr(1)})
        for t in tabs:
            acc = multiply(acc, t)
        return acc

    # eliminate down to each queried region in turn, reusing the factor list
    Ztot = None
    counts = {}
    for i in range(nreg):
        has_q = any(k[0] in queries for k in coarse[i].N)
        if not has_q:
            continue
        sc, ent = eliminate(tables, i)
        tot = sum(ent.values())
        if tot <= 0:
            raise RuntimeError("cell variable %d has nonpositive total" % i)
        if Ztot is None:
            Ztot = tot
        elif tot != Ztot:
            # every calibrated cell marginal must share one total
            if abs(tot - Ztot) * 10 ** 12 > Ztot:
                raise RuntimeError(
                    "cell marginals disagree on the total (%s vs %s)"
                    % (tot, Ztot))
            Ztot = min(Ztot, tot)
        k = sc.index(i) if i in sc else None
        for a, w in ent.items():
            ci = a[k] if k is not None else 0
            Mc = Fr(coarse[i].M[ci])
            if Mc <= 0:
                continue
            for key, col in coarse[i].N.items():
                if key[0] not in queries:
                    continue
                Nc = Fr(col[ci])
                if Nc == 0:
                    continue
                counts[key] = counts.get(key, Fr(0)) + w * Nc / Mc
    if Ztot is None or Ztot <= 0:
        raise RuntimeError("the reduced model has no positive total")
    return (Ztot, Ztot), (counts, dict(counts))


def _regional_execute(r, payload, queries, eps, bg):
    """Execute the regional route with compact crossings and direct readout."""
    regions = payload["regions"]
    coarse = payload["coarse"]
    rds = payload["rds"]
    proj = payload["proj"]
    dl = bg.deadline_fn("regional-execute")
    import itertools
    ncell = [len(c.cells) for c in coarse]
    # FACTORIZED contraction first, by elimination over the reduced graph.
    # Enumerating the product of all cell cardinalities is what the price does
    # NOT describe: a 20-variable width-one chain was priced for elimination
    # at 2,937 operations and then refused 1,048,576 joint assignments against
    # the 4,096 cap. Pricing and execution must describe the same program, so
    # the producer now runs the same reduced-graph elimination the price
    # assumes, and falls back to enumeration only when elimination is
    # unavailable AND the joint space is within the declared cap.
    # The PRODUCER must not call the checker's contractor. Both calling
    # regional_check._reduced_message_passing made them common-mode: a fault
    # in that one function returning total 4 with state masses 18/5 and 2/5
    # yielded CERTIFIED_RESEARCH_ROUTE with independently_verified=True and
    # intervals [.898, .902] excluding the true 1/2 on every coordinate.
    #
    # This is the producer's OWN reduced contraction over the compact
    # projected crossings: it eliminates cell variables in a fixed order,
    # sharing only the validated structural data and the exact rational
    # primitives the contract permits.
    try:
        # pass budget=bg: the hook existed but the EXECUTED call omitted it,
        # so a direct helper test charged and refused while the production
        # path bypassed the counter entirely
        (Zlo, Zhi), (clo, chi) = _producer_reduced_contract(
            r, regions, coarse, rds, queries, deadline=dl, budget=bg)
        # The INDEPENDENT checker runs its own 128-bit point contraction and
        # charges that arithmetic's N1 error, so its enclosure is wider than
        # an exact-rational producer point by about 5e-39 on each side. The
        # publication must leave room for the checker's own error or it can
        # never contain the checker's enclosure. This allowance is charged
        # from the declared publication reserve, not invented.
        _chk_slack = K.PUBLICATION_RESERVE
        # the producer publishes a point-valued count set; take the enclosure's
        # lower end for Z and upper for counts so the readout stays outward
        rows = {}
        for v in sorted(queries):
            nst = None
            for i, reg in enumerate(regions):
                if v in reg:
                    nst = len({k[1] for k in coarse[i].N if k[0] == v})
                    break
            if not nst:
                continue
            rr = []
            for sx in range(nst):
                lo = clo.get((v, sx), Fr(0)) / Zhi if Zhi > 0 else Fr(0)
                hi = chi.get((v, sx), Fr(0)) / Zlo if Zlo > 0 else Fr(1)
                rr.append((max(Fr(0), lo - _chk_slack),
                           min(Fr(1), hi + _chk_slack)))
            rows[v] = rr
        if rows:
            return rows
    except RC.RegionalCheckError:
        # elimination is UNAVAILABLE for structural reasons; a bounded
        # enumeration fallback is admitted below and charged there
        pass
    except B.BudgetExceeded:
        # A SHARED EXHAUSTED WORK CAP must stop. Catching it here and
        # continuing through enumeration meant the executor charged four
        # entries against a declared limit of 1, recorded exhaustion, and
        # still returned all four coordinates. A candidate-specific refusal
        # may permit a charged fallback; an exhausted shared budget may not.
        raise
    total = 1
    for k in ncell:
        total *= k
    if total > K.CAPS["checker_contraction_space"]:
        raise B.BudgetExceeded("regional_assignments", total,
                               K.CAPS["checker_contraction_space"],
                               "regional execute (elimination unavailable, "
                               "and the joint cell space exceeds the cap)")
    Z = Fr(0)
    counts = {}
    for tup in itertools.product(*[range(k) for k in ncell]):
        dl()
        cell_of = {i: tup[i] for i in range(len(regions))}
        w = Fr(1)
        for i, ci in enumerate(tup):
            w *= Fr(coarse[i].M[ci])
            if w == 0:
                break
        if w == 0:
            continue
        for pc in proj:
            w *= pc.value(cell_of)
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for i, ci in enumerate(tup):
            Mc = Fr(coarse[i].M[ci])
            if Mc <= 0:
                continue
            for key, col in coarse[i].N.items():
                if key[0] not in queries:
                    continue
                Nc = Fr(col[ci])
                if Nc == 0:
                    continue
                counts[key] = counts.get(key, Fr(0)) + w / Mc * Nc
    if Z <= 0:
        raise PipelineError("regional execution gave a nonpositive total")
    # DIRECT original-query readout: counts, then ONE normalization and pad
    out = {}
    pad = eps / 4
    for v in sorted(queries):
        nst = len({k[1] for k in
                   next(c for i, c in enumerate(coarse) if v in regions[i]).N
                   if k[0] == v})
        rows = []
        for s in range(nst):
            Aq = counts.get((v, s), Fr(0))
            Cq = Z - Aq
            lo, hi = CP.normalize_once(Aq, Cq, pad, eps)
            rows.append((lo, hi))
        out[v] = rows
    return out


# ======================= loaded-program binding =======================

def _resolve_role(ref):
    import importlib
    mod, _, fn = ref.partition(":")
    return getattr(importlib.import_module(mod), fn)


def _reprice_loaded(rec, r, queries, nq, simp, cap_bytes, bg=None):
    """Re-derive a loaded record's price FROM ITS PROGRAM: rebuild the lifted
    models from the witness and the residual from the collective record, then
    price the schedule that will run. Discovery's live price is not consulted."""
    from mdi import routes as RT, marked as MK, collective_route as CR
    prog = rec.parsed_program
    if rec.kind == "identity":
        pl = P.build_plan("program", prog["order"], r.free, r.card, r.factors)
        est = P.byte_estimate(pl, 64)
        return PR.price_identity_plan(pl, est, nq, prog["precision"],
                                      {"constants": len(simp.removed_constants),
                                       "splits": len(simp.split_pairs)})
    marked = MK.Marked.from_restricted(r, set(queries))
    scales = []
    for sc in prog["scales"]:
        scales.append(RT.scale_view_from_record(marked, sc))
        marked = RT.lift_from_record(marked, sc)
    coll = prog["collective"]
    final = marked
    if coll is not None:
        final, _res, _can = CR.rebuild_residual(marked, coll, A.Ctx(coll["precision"]))
        coll = dict(coll)
    cons = int((rec.cost_counters.get("construction_ops") or {}).get("value") or 0)
    # price EXACTLY the saved order, under the shared budget
    price, _order = PR.price_program(rec.name, rec.kind, final, scales, coll, nq, cons,
                                     order=prog["order"] or None,
                                     deadline=(bg.deadline_fn("reprice") if bg else None),
                                     budget=bg)
    if _order is not None and prog["order"] and list(_order) != list(prog["order"]):
        raise PT.PlanError("the re-priced schedule's order %s is not the saved order %s"
                           % (_order[:6], prog["order"][:6]))
    return price


def _price_disagrees(recorded, price):
    """The recorded counters must equal the re-derived ones on every bounded
    arithmetic counter; a measured construction count is carried, not
    recomputed."""
    for k, c in price.counters.items():
        if c.label not in (PR.UPPER, PR.EXACT):
            continue
        rv = (recorded.get(k) or {}).get("value")
        if rv is None:
            return "counter %s absent from the record" % k
        if str(rv) != str(c.as_dict()["value"]):
            return "counter %s recorded %s, re-derived %s" % (k, rv, c.as_dict()["value"])
    return None


def _complete_cost(prices, rejected, exec_meta, check_meta, stages):
    tot = 0
    labels = set()
    for p in prices:
        for k in ("construction_ops", "mode_fit_ops"):
            c = p["counters"].get(k)
            if c and c["value"] is not None:
                tot += int(c["value"])
                labels.add(c["label"])
    ex = (exec_meta or {}).get("ops")
    ex_ops = (sum(int(v) for k, v in ex.items() if k in ("mul", "add"))
              if isinstance(ex, dict) and ex else None)          # MISSING stays missing
    ck = (check_meta or {}).get("collective") or {}
    ck_raw = (ck.get("ops") if isinstance(ck, dict) else None) or (check_meta or {}).get("ops")
    ck_ops = (sum(int(v) for k, v in ck_raw.items() if k in ("mul", "add"))
              if isinstance(ck_raw, dict) and ck_raw else None)
    ex_tr = (exec_meta or {}).get("transcendental_calls")
    ck_tr = (ck.get("transcendental_calls") if isinstance(ck, dict) else None)
    bounds, forecasts = {}, {}
    for p in prices:
        for k, c in p["counters"].items():
            if c.get("value") is None:
                continue
            if c.get("label") == "upper_bound":
                bounds.setdefault(k, 0)
                bounds[k] += int(c["value"])
            elif c.get("label") == "forecast":
                forecasts.setdefault(k, 0)
                forecasts[k] += int(c["value"])
    return {"discovery_all_candidates_ops": tot,
            "discovery_labels": sorted(labels),
            "rejected_candidates": len(rejected),
            "proven_bounds_all_candidates": bounds,
            "forecasts_all_candidates": forecasts,
            "measured": {"executed_engine_ops": ex_ops, "checker_engine_ops": ck_ops,
                         "executor_transcendental_calls": ex_tr,
                         "checker_transcendental_calls": ck_tr,
                         "executor_peak_live_entries": (exec_meta or {}).get("peak_live_entries"),
                         "retained_positive_node_entries": (exec_meta or {}).get("retained_positive_node_entries"),
                         "precomputed_phase_entries": (exec_meta or {}).get("precomputed_phase_entries")},
            "executed_engine_ops": ex_ops,
            "checker_engine_ops": ck_ops,
            "stage_seconds": {k: round(v, 4) for k, v in stages.items()
                              if isinstance(v, (int, float))},
            "label": "forecast" if ("forecast" in labels or "measured_calibration" in labels) else "exact",
            "note": "selection compared the REMAINING cost of each loaded "
                    "program; this is the complete invocation cost including "
                    "discovery of every candidate and failed candidates"}


# ======================= discovery of PROGRAM routes =======================

def _candidate_record(kind, name, mh, eh, qh, simp, r, prog, allocations,
                      price, order, precision, storage, extra_props=None):
    """A plan record for one built program. Every allocation is exact."""
    sup = PT.supported(kind)
    props = PT.PlanProperties()
    props.set("mathematically_certified")
    if sup["executor_supported"]:
        props.set("executor_supported")
    if sup["checker_supported"]:
        props.set("checker_supported")
    if price.counters and price.eligible:
        props.set("complete_cost_priced")
    regions = []
    cells = []
    for k, sc in enumerate(prog["scales"]):
        for i, rg in enumerate(sc["regions"]):
            regions.append((k * 10000 + i, tuple(rg["region"])))
            for ci, c in enumerate(rg["cells"]):
                cells.append((k * 10000 + i, ci, [tuple(mb) for mb, _a in c["members"]]))
    owner_tag = "region" if prog["scales"] else "bag"
    rec = PT.PlanRecord(
        kind=kind, name=name, model_sha256=mh, evidence_sha256=eh,
        query_sha256=qh, preprocess_identity=simp.identity(),
        factor_ownership=[(f.origin, owner_tag) for f in r.factors],
        factor_scopes=[(f.origin, tuple(f.scope), tuple(f.card)) for f in r.factors],
        region_membership=regions, cell_membership=cells,
        allocations={k: Fr(v) for k, v in allocations.items()},
        executor_id="mdi.registry:pipeline_program_executor",
        checker_id="mdi.registry:_program_checker",
        numerical={"precision": int(precision), "mode": "E"},
        cost_counters={k: c.as_dict() for k, c in price.counters.items()},
        storage_schedule=storage, rejected_alternatives=[], properties=props,
        program=prog)
    return rec


def _discover_programs(r, queries, nq, mh, eh, qh, simp, bg, wall_s, records,
                       prices, rejected, cap_bytes):
    """Build and price every research program (§5-§8) on the restricted model.

    Routes offered, each a real candidate with its own program, price,
    executor and checker:
      * collective on the INPUT: statistic / gaussian / fourier (§6-7.2);
      * regional, one scale, with deletion (§5);
      * regional, two scales (§5.6);
      * composed: a collective evaluator on the level-1 coarse cells (§7.3).
    Discovery is bounded by the shared budget. A consumed SHARED counter
    stops discovery (recorded on the function for the caller); a candidate's
    own refusal is recorded and the next candidate proceeds.
    """
    from mdi import (marked as MK, routes as RT, collective_route as CR,
                     program as PG)
    _discover_programs._shared = None
    deadline = bg.deadline_fn("discover")
    mk0 = MK.Marked.from_restricted(r, set(queries))
    prec = 128
    ctx = A.Ctx(prec)

    def _record(kind, name, scales, coll, final, cons, fit_ops=None):
        try:
            # the schedule is chosen ONCE here (the dry run's order) and saved;
            # every later price is derived on that saved order
            price, order = PR.price_program(name, kind, final, scales, coll, nq,
                                            cons, fit_ops=fit_ops,
                                            deadline=deadline, budget=bg)
        except B.BudgetExceeded as e:
            if _shared(e):
                _discover_programs._shared = e
            rejected.append({"name": name, "reason": "pricing: %s" % e})
            return
        except Exception as e:
            rejected.append({"name": name, "reason": "pricing failed: %s: %s"
                             % (type(e).__name__, e)})
            return
        prog = RT.program_for(kind, scales, coll, order or [], prec, queries)
        ident = executable_identity(kind, json.loads(json.dumps(prog)))
        # the program must PARSE strictly before it is offered
        try:
            PG.validate_program(json.loads(json.dumps(prog)))
        except PG.ProgramError as e:
            rejected.append({"name": name, "reason": "program block invalid: %s" % e})
            return
        alloc = RT.allocations_for(scales, coll)
        flb = price.counters.get("final_largest_bag")
        storage = {"final_variables": len(final.card),
                   "final_largest_bag": (int(flb.value) if flb is not None and flb.value is not None else None),
                   "levels": len(scales), "identity": ident}
        if not price.eligible:
            # a TYPED price refusal: the candidate is recorded with its reason
            # and discovery continues to every other candidate and fallback
            rejected.append({"name": name, "reason": "price refusal: %s" % price.ineligible_reason,
                             "typed": "PRICE_REFUSAL"})
        rec = _candidate_record(kind, name, mh, eh, qh, simp, r, prog, alloc,
                                price, order, prec, storage)
        rec.identity_key = ident
        records.append((rec, price, {"program": prog}))
        prices.append(price)

    def _shared(e):
        if getattr(e, "kind", None) in ("wall", "rss"):
            return True
        lim = bg.limits.get(getattr(e, "kind", ""), None)
        used = bg.used.get(getattr(e, "kind", ""), 0)
        return lim is not None and used >= lim

    # ---- collective routes on the INPUT law: every certified candidate is
    # offered to every evaluator that applies to it (statistic DP at any rank;
    # Gaussian / Fourier / mixed integration when the §7.2 forecast is
    # affordable); each is its own priced program
    num_eps = K.MAX_WIDTH - 2 * (K.RADII["collective_fit_and_rounding"]
                                 + K.RADII["gaussian_quadrature"]) - K.PUBLICATION_RESERVE
    try:
        admitted = CR.admit(mk0, ctx, deadline=deadline, num_eps=num_eps)
    except CR.Declined as e:
        admitted = []
        rejected.append({"name": "collective", "reason": "collective routes declined: %s" % e})
    except B.BudgetExceeded as e:
        if _shared(e):
            _discover_programs._shared = e
            return
        admitted = []
        rejected.append({"name": "collective", "reason": str(e)})
    except Exception as e:
        admitted = []
        rejected.append({"name": "collective", "reason": "collective admission failed: "
                         "%s: %s" % (type(e).__name__, e)})
    n_pairs = sum(1 for f in r.factors if len(f.scope) == 2)
    seen_names = {}
    for coll, rmk in admitted:
        if bg.remaining() < wall_s * 0.25:
            rejected.append({"name": coll["evaluator"],
                             "reason": "discovery budget exhausted: candidate NOT priced"})
            continue
        base_name = "%s:%s" % (coll["evaluator"], coll["candidate"].kind)
        n_prev = seen_names.get(base_name, 0)
        seen_names[base_name] = n_prev + 1
        name = base_name if n_prev == 0 else "%s#%d" % (base_name, n_prev + 1)
        if coll["evaluator"] == "statistic" and n_prev == 0 and \
                not any(k.startswith("statistic:") for k in seen_names if k != base_name):
            name = base_name
        for dcl in coll.get("declines", []):
            if dcl not in [x["reason"] for x in rejected]:
                rejected.append({"name": "collective", "reason": dcl})
        _record(coll["evaluator"], name, [], coll, rmk, 0,
                fit_ops=8 * (n_pairs + len(r.free)) * 4)

    # ---- regional routes
    try:
        cands = R.propose_partitions(r.free, r.card, r.factors)
    except Exception as e:
        cands = []
        rejected.append({"name": "regional:discovery",
                         "reason": "partition discovery failed: %s" % e})
    for c in cands:
        if c["mode"] == "singleton":
            continue
        base = "regional:" + c["mode"]
        if bg.remaining() < wall_s * 0.25:
            rejected.append({"name": base, "reason": "discovery budget exhausted"})
            continue
        regs = [tuple(x) for x in c["regions"]]
        # ADMISSION-TIME cover validation, BEFORE any local construction
        cover = {}
        for i, rr_ in enumerate(regs):
            for v in rr_:
                cover.setdefault(v, []).append(i)
        miss = [v for v in sorted(r.card) if v not in cover]
        dup = [v for v, owners in sorted(cover.items()) if len(owners) > 1]
        alien = [v for v in sorted(cover) if v not in r.card]
        if miss or dup or alien:
            rejected.append({"name": base,
                             "reason": "the proposed partition is not a disjoint "
                                       "exact cover of the free variables: "
                                       "uncovered %s, duplicated %s, unknown %s"
                                       % (miss[:4], dup[:4], alien[:4])})
            continue
        badf = [getattr(f, "origin", fi) for fi, f in enumerate(r.factors)
                if any(v not in cover for v in f.scope)]
        if badf:
            rejected.append({"name": base,
                             "reason": "factors %s have variables outside the "
                                       "proposed partition" % badf[:4]})
            continue
        for levels in (1, 2):
            name = base if levels == 1 else base + ":L2"
            try:
                scales, final = RT.build_scales(mk0, regs, levels,
                                                deadline=deadline, budget=bg)
            except B.BudgetExceeded as e:
                if _shared(e):
                    _discover_programs._shared = e
                    return
                rejected.append({"name": name, "reason": str(e)})
                continue
            except (R.CapExceeded, R.Declined, MK.MarkedError, CP.CompactError) as e:
                rejected.append({"name": name, "reason": "%s: %s"
                                 % (type(e).__name__, e)})
                continue
            cons = sum(int(getattr(rd, "construction_ops", 0))
                       for sc in scales for rd in sc.rds)
            _record("regional", name, scales, None, final, cons)
            if True:
                # ---- the COMPOSED route: a collective evaluator on the cells
                # of this scale (§7.3: coarsen the fixed law first, then fit)
                cname = "composed:" + c["mode"] + ("" if levels == 1 else ":L2")
                try:
                    admitted = CR.admit(final, A.Ctx(160), deadline=deadline,
                                        num_eps=num_eps)
                except CR.Declined as e:
                    rejected.append({"name": cname,
                                     "reason": "composed route declined: %s" % e})
                    continue
                except B.BudgetExceeded as e:
                    if _shared(e):
                        _discover_programs._shared = e
                        return
                    rejected.append({"name": cname, "reason": str(e)})
                    continue
                except Exception as e:
                    rejected.append({"name": cname,
                                     "reason": "composed route declined: %s: %s"
                                               % (type(e).__name__, e)})
                    continue
                cseen = {}
                for coll, rmk in admitted:
                    cb = cname + ":" + coll["evaluator"] + ":" + coll["candidate"].kind
                    k_prev = cseen.get(cb, 0)
                    cseen[cb] = k_prev + 1
                    cn = cb if k_prev == 0 else "%s#%d" % (cb, k_prev + 1)
                    n_pairs = len(final.factors)
                    _record("composed", cn, scales, coll, rmk, cons,
                            fit_ops=8 * (n_pairs + len(final.card)) * 4)
                continue
