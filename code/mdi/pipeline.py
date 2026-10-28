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
                 collective as CO, modes as MD, coarse as CZ)


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
    stages = {}
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
        return Outcome(status="ZERO_EVIDENCE_PROVED",
                       reason="a restricted factor is identically zero or a "
                              "pinned factor is exactly zero",
                       stages=stages, budget=bg.report())

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
        return Outcome(status="ZERO_EVIDENCE_PROVED",
                       reason="factor %d is identically zero" % simp.impossible,
                       stages=stages, budget=bg.report())
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

    # identity, always retained
    sel = P.choose_plan(r.free, r.card, r.factors, 64, cap_bytes)
    if sel["chosen"] is None:
        best = sel["candidates"][0] if sel["candidates"] else None
        return Outcome(status="RESOURCE_STOP",
                       reason="no generic ordering fits the byte cap; best "
                              "forecast %s" % (best[1] if best else None),
                       stages=stages, budget=bg.report())
    ipl, iest = sel["chosen"]
    iprice = PR.price_identity_plan(ipl, iest, nq, 64,
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
        executor_id="mdi.registry:_identity_executor",
        checker_id="mdi.registry:_identity_checker",
        numerical={"precision": 64, "mode": "P"},
        cost_counters={k: c.as_dict() for k, c in iprice.counters.items()},
        storage_schedule={"peak_live_entries": iest["peak_live_entries"]},
        rejected_alternatives=[], properties=iprops)
    records.append((irec, iprice, {"plan": ipl, "est": iest}))
    prices.append(iprice)

    # regional, when research is enabled
    if research_enabled:
        try:
            cands = R.propose_partitions(r.free, r.card, r.factors)
        except Exception as e:
            cands = []
            rejected.append({"name": "regional:discovery",
                             "reason": "partition discovery failed: %s" % e})
        t_level = K.level_radius(1)
        for c in cands:
            if c["mode"] == "singleton":
                continue
            if bg.remaining() < wall_s * 0.25:
                rejected.append({"name": "regional:" + c["mode"],
                                 "reason": "discovery budget exhausted"})
                continue
            regs = c["regions"]
            rho_cap = K.region_distortion_budget(t_level, len(regs))
            region_of = {v: i for i, rr in enumerate(regs) for v in rr}
            rds, crs, skipped = [], [], 0
            dl = bg.deadline_fn("regional:" + c["mode"])
            try:
                for reg in regs:
                    try:
                        rd = R.region_data(reg, r.card, r.factors, queries,
                                           deadline=dl)
                        cr = R.merge_region(rd, r.factors, r.card, rho_cap,
                                            queries, deadline=dl,
                                            region_of=region_of, aggregate=True)
                    except (R.CapExceeded, R.Declined):
                        skipped += 1
                        continue
                    rds.append(rd); crs.append(cr)
            except B.BudgetExceeded as e:
                rejected.append({"name": "regional:" + c["mode"],
                                 "reason": str(e)})
                continue
            if skipped or not crs:
                rejected.append({
                    "name": "regional:" + c["mode"],
                    "reason": "%d of %d regions skipped: INCOMPLETE partition"
                              % (skipped, len(regs))})
                continue
            Rlevel = R.level_distortion(crs)
            certified = K.certify_R_against_t(Rlevel, t_level)
            if not certified:
                rejected.append({"name": "regional:" + c["mode"],
                                 "reason": "R_level %s not certified at t=%s"
                                           % (Rlevel, t_level)})
                continue
            try:
                proj, _ = CP.project_crossings(r, regs, crs, rds)
            except CP.CompactError as e:
                rejected.append({"name": "regional:" + c["mode"],
                                 "reason": "projection failed: %s" % e})
                continue
            # MEASURED local construction, plus the checker's own
            # reconstruction. The checker rebuilds every region's masses and
            # markers independently (that is the point of it), so the complete
            # cost carries that work too -- it is paid, not free.
            cons = sum(int(getattr(rd, "construction_ops", 0)) for rd in rds)
            checker_cons = 2 * cons     # recheck_region + its own region_data
            rprice = PR.price_regional_plan("regional:" + c["mode"], regs, crs,
                                            rds, proj, nq, t_level,
                                            construction_ops=cons
                                            + checker_cons)
            rsup = PT.supported("regional")
            rprops = PT.PlanProperties()
            rprops.set("mathematically_certified")
            if rsup["executor_supported"]:
                rprops.set("executor_supported")
            if rsup["checker_supported"]:
                rprops.set("checker_supported")
            rprops.set("complete_cost_priced")
            rrec = PT.PlanRecord(
                kind="regional", name="regional:" + c["mode"],
                model_sha256=mh, evidence_sha256=eh, query_sha256=qh,
                preprocess_identity=simp.identity(),
                factor_ownership=[(f.origin, "region") for f in r.factors],
                factor_scopes=[(f.origin, tuple(f.scope), tuple(f.card))
                               for f in r.factors],
                region_membership=[(i, tuple(reg))
                                   for i, reg in enumerate(regs)],
                cell_membership=[(i, ci, [tuple(mb) for mb, _ in cell.members])
                                 for i, cr in enumerate(crs)
                                 for ci, cell in enumerate(cr.cells)],
                allocations={"regional_level1": t_level},
                executor_id="mdi.registry:_regional_executor",
                checker_id="mdi.registry:_regional_checker",
                numerical={"precision": 64, "mode": "P"},
                cost_counters={k: cc.as_dict()
                               for k, cc in rprice.counters.items()},
                storage_schedule={"cells": sum(len(x.cells) for x in crs)},
                rejected_alternatives=[], properties=rprops)
            records.append((rrec, rprice,
                            {"regions": regs, "coarse": crs, "rds": rds,
                             "proj": proj, "t_level": t_level}))
            prices.append(rprice)

            # ---- the COMPOSED route on this partition's categorical cells ----
            try:
                from mdi import composed as CM
                cctx = A.Ctx(160)
                cm_out, cm_meta = CM.run(r, regs, crs, rds, queries, cctx, eps,
                                         t_level=t_level,
                                         deadline=bg.deadline_fn("composed"))
            except Exception as e:
                rejected.append({"name": "composed:" + c["mode"],
                                 "reason": "composed route declined: %s: %s"
                                           % (type(e).__name__, e)})
                cm_out = None
            if cm_out is not None:
                ccons = sum(int(getattr(rd, "construction_ops", 0))
                            for rd in rds)
                cprice = PR.price_regional_plan("composed:" + c["mode"], regs,
                                                crs, rds, proj, nq, t_level,
                                                construction_ops=3 * ccons)
                cprice.kind = "composed"
                cprice.put("collective_statistic_support",
                           cm_meta.get("statistic_support", 0), PR.EXACT)
                csup = PT.supported("composed")
                cprops = PT.PlanProperties()
                cprops.set("mathematically_certified")
                if csup["executor_supported"]:
                    cprops.set("executor_supported")
                if csup["checker_supported"]:
                    cprops.set("checker_supported")
                cprops.set("complete_cost_priced")
                crec2 = PT.PlanRecord(
                    kind="composed", name="composed:" + c["mode"],
                    model_sha256=mh, evidence_sha256=eh, query_sha256=qh,
                    preprocess_identity=simp.identity(),
                    factor_ownership=[(f.origin, "region") for f in r.factors],
                    factor_scopes=[(f.origin, tuple(f.scope), tuple(f.card))
                                   for f in r.factors],
                    region_membership=[(i, tuple(reg))
                                       for i, reg in enumerate(regs)],
                    cell_membership=[],
                    allocations={"regional_level1": t_level,
                                 "collective_total":
                                     Fr(cm_meta["total_radius"])},
                    executor_id="mdi.registry:_composed_executor",
                    checker_id="mdi.registry:_composed_checker",
                    numerical={"precision": 160, "mode": "P"},
                    cost_counters={k: cc.as_dict()
                                   for k, cc in cprice.counters.items()},
                    storage_schedule={"cells": sum(len(x.cells) for x in crs)},
                    rejected_alternatives=[], properties=cprops)
                records.append((crec2, cprice,
                                {"regions": regs, "coarse": crs, "rds": rds,
                                 "proj": proj, "t_level": t_level,
                                 "composed": cm_out, "composed_meta": cm_meta}))
                prices.append(cprice)
    stages["discover_s"] = time.monotonic() - t
    out.rejected = rejected

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
        path = os.path.join(plan_dir, "%s.plan.json"
                            % rec.name.replace(":", "_"))
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
            back.bind_check(mh, eh, qh)
        except (PT.PlanError, ValueError, OSError) as e:
            rejected.append({"name": rec.name,
                             "reason": "plan record failed persist/reload: %s"
                                       % e})
            continue
        back.source_path = path
        reloaded.append((back, price, payload))
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
        miss = rec.properties.may_execute_as_certified_route()
        miss = [x for x in miss if x != "selected"]
        if miss:
            price.eligible = False
            price.ineligible_reason = ("missing %s; an unregistered executor or "
                                       "checker makes the route ineligible"
                                       % miss)
    cmp = PR.compare([p for _, p, _ in reloaded], cap_bytes=cap_bytes)
    stages["select_s"] = time.monotonic() - t
    out.prices = [p.as_dict() for _, p, _ in reloaded]
    if cmp["chosen"] is None:
        return Outcome(status="RESOURCE_STOP",
                       reason="every route is ineligible or over the byte cap",
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    chosen_name = cmp["chosen"]["name"]
    chosen = next(x for x in reloaded if x[1].name == chosen_name)
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

    # ---------------- stage 6: execute through the dispatcher ----------------
    try:
        bg.enter("execute")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    t = time.monotonic()
    try:
        executor, checker = PT.dispatch(crec.kind)
    except PT.PlanError as e:
        return Outcome(status="RESOURCE_STOP",
                       reason="dispatch refused: %s" % e, prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report())
    radius = Fr(crec.allocations.get("regional_level1",
                                     crec.allocations.get("transformation", 0)))
    num_eps = eps - 2 * radius - K.PUBLICATION_RESERVE
    if num_eps <= 0:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="the charged radius consumes the whole contract",
                       prices=out.prices, stages=stages, budget=bg.report())
    try:
        # INVOKE the executor bound by the validated selected plan. The
        # previous code called PT.dispatch() and then branched on crec.kind,
        # so the dispatched executor was never used: swapping in a raising
        # sentinel still produced a certified result with zero executor calls.
        pexec = PT.dispatch_pipeline(crec.kind)
        if crec.executor_id and not crec.executor_id.endswith(crec.kind) \
                and crec.kind not in crec.executor_id:
            return Outcome(status="RESOURCE_STOP",
                           reason="the persisted executor id %r does not name "
                                  "the plan kind %r"
                                  % (crec.executor_id, crec.kind),
                           prices=out.prices, rejected=rejected,
                           stages=stages, budget=bg.report())
        raw = pexec({"model": model, "evidence": evidence, "eps": num_eps,
                     "cap_bytes": cap_bytes, "remaining": bg.remaining,
                     "restricted": r, "payload": cpayload,
                     "queries": queries, "budget": bg,
                     "regional_execute": _regional_execute})
    except PT.ExecutorRefusal as e:
        return Outcome(status=e.status, reason=e.reason, prices=out.prices,
                       rejected=rejected, stages=stages, budget=bg.report())
    except PT.PlanError as e:
        return Outcome(status="RESOURCE_STOP",
                       reason="pipeline dispatch refused: %s" % e,
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    stages["execute_s"] = time.monotonic() - t
    crec.properties.set("producer_complete")

    # outward expansion by the certified radius, once
    pub, worst = {}, Fr(0)
    already_widened = (crec.kind == "composed")
    for v in sorted(raw):
        rows = []
        for (lo, hi) in raw[v]:
            lo2, hi2 = Fr(lo), Fr(hi)
            if not already_widened and not (lo2 == hi2 and
                                            (lo2 == 0 or lo2 == 1)):
                lo2 = max(Fr(0), lo2 - radius)
                hi2 = min(Fr(1), hi2 + radius)
            if hi2 - lo2 > worst:
                worst = hi2 - lo2
            rows.append((lo2, hi2))
        pub[v] = rows
    for v, st in evidence.items():
        pub[v] = [(Fr(1), Fr(1)) if s == st else (Fr(0), Fr(0))
                  for s in range(model.card[v])]

    # ---------------- stage 7: independent check ----------------
    try:
        bg.enter("check")
    except B.BudgetExceeded as e:
        return Outcome(status="RESOURCE_STOP", reason=str(e),
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report())
    # the independent checker receives the SHARED deadline, so its own work is
    # bounded by the same budget as the producer's
    check_dl = bg.deadline_fn("check")
    t = time.monotonic()
    try:
        if crec.kind == "identity":
            ok, fails = checker(model, evidence, pub, eps,
                                deadline_s=bg.remaining(),
                                cap_bytes=cap_bytes)
            meta = {"kind": "identity"}
            bg.check("after-identity-check")
        elif crec.kind == "composed":
            ok, fails, meta = checker(
                r, cpayload["regions"], cpayload["coarse"], cpayload["rds"],
                queries, pub, eps,
                Fr(cpayload["composed_meta"]["total_radius"]),
                regional_radius=Fr(cpayload["composed_meta"]["regional_radius"]))
        else:
            ok, fails, meta = checker(r, cpayload["regions"],
                                      cpayload["coarse"], cpayload["rds"],
                                      queries, pub, cpayload["t_level"], eps,
                                      deadline=bg.deadline_fn("check"))
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
    if not ok:
        return Outcome(status="NUMERICAL_REFUSAL",
                       reason="independent checker REJECTED the publication",
                       checker={"status": "FAILED",
                                "failures": [str(x)[:200] for x in fails[:6]]},
                       prices=out.prices, rejected=rejected, stages=stages,
                       budget=bg.report(),
                       properties=crec.properties.as_dict())
    # the LAST enforcement point: a run that exceeded its budget may not
    # publish, even if every stage individually completed
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
    crec.properties.set("independently_verified")
    if worst <= eps:
        crec.properties.set("publication_contract_met")
    status = ("CERTIFIED_RESEARCH_ROUTE" if crec.kind != "identity"
              else "CERTIFIED_FALLBACK_ONLY")
    out.plan["executed_kind"] = crec.kind
    if worst > eps:
        status = "NUMERICAL_REFUSAL"
    return Outcome(status=status, intervals=pub, plan=out.plan,
                   prices=out.prices, rejected=rejected, stages=stages,
                   budget=bg.report(), preprocess=out.preprocess,
                   checker={"status": "VERIFIED", **(meta or {})},
                   properties=crec.properties.as_dict())


def _regional_execute(r, payload, queries, eps, bg):
    """Execute the regional route with compact crossings and direct readout."""
    regions = payload["regions"]
    coarse = payload["coarse"]
    rds = payload["rds"]
    proj = payload["proj"]
    dl = bg.deadline_fn("regional-execute")
    # cavity per region: the product of everything outside it, by enumerating
    # the other regions' cells
    import itertools
    ncell = [len(c.cells) for c in coarse]
    total = 1
    for k in ncell:
        total *= k
    if total > K.CAPS["checker_contraction_space"]:
        raise B.BudgetExceeded("regional_assignments", total,
                               K.CAPS["checker_contraction_space"],
                               "regional execute")
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
