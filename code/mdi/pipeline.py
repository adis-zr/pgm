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
    _shared_exhausted = None

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
            # ADMISSION-TIME cover validation, BEFORE any local construction.
            # A faulty proposal that omitted a hidden variable previously ran
            # the whole route and reached CERTIFIED_RESEARCH_ROUTE with both
            # probabilities near .5 against a truth of (.3, .7); the
            # independent checker catches it, but a candidate that cannot be
            # sound should never be priced or executed at all.
            cover = {}
            for i, rr_ in enumerate(regs):
                for v in rr_:
                    cover.setdefault(v, []).append(i)
            miss = [v for v in sorted(r.card) if v not in cover]
            dup = [v for v, owners in sorted(cover.items()) if len(owners) > 1]
            alien = [v for v in sorted(cover) if v not in r.card]
            if miss or dup or alien:
                rejected.append({
                    "name": "regional:" + c["mode"],
                    "reason": "the proposed partition is not a disjoint exact "
                              "cover of the free variables: uncovered %s, "
                              "duplicated %s, unknown %s"
                              % (miss[:4], dup[:4], alien[:4])})
                continue
            badf = [getattr(f, "origin", fi) for fi, f in enumerate(r.factors)
                    if any(v not in cover for v in f.scope)]
            if badf:
                rejected.append({
                    "name": "regional:" + c["mode"],
                    "reason": "factors %s have variables outside the proposed "
                              "partition, so they could be classified neither "
                              "local nor crossing" % badf[:4]})
                continue
            rho_cap = K.region_distortion_budget(t_level, len(regs))
            region_of = {v: i for i, rr in enumerate(regs) for v in rr}
            rds, crs, skipped = [], [], 0
            dl = bg.deadline_fn("regional:" + c["mode"])
            try:
                for reg in regs:
                    try:
                        # pass budget=bg so the DECLARED allocation counters
                        # are actually charged on the production path. The
                        # helper enforced its limit, but the pipeline omitted
                        # the argument, so a public route reported used={}
                        # while building masses and markers.
                        rd = R.region_data(reg, r.card, r.factors, queries,
                                           deadline=dl, budget=bg)
                        cr = R.merge_region(rd, r.factors, r.card, rho_cap,
                                            queries, deadline=dl,
                                            region_of=region_of,
                                            aggregate=True)
                    except (R.CapExceeded, R.Declined):
                        skipped += 1
                        continue
                    rds.append(rd); crs.append(cr)
            except B.BudgetExceeded as e:
                # SHARED WORK EXHAUSTION must stop; it is not a per-candidate
                # refusal. Discovery recorded a rejection and continued, so a
                # unit local_mass_entries limit was charged twice and the
                # pipeline still certified the identity fallback. A candidate
                # whose own construction is too large may legitimately be
                # rejected -- but a consumed SHARED counter cannot be
                # swallowed by moving to the next candidate.
                if getattr(e, "kind", None) in ("wall", "rss"):
                    _shared_exhausted = e
                    break
                _lim = bg.limits.get(getattr(e, "kind", ""), None)
                _used = bg.used.get(getattr(e, "kind", ""), 0)
                if _lim is not None and _used >= _lim:
                    # the shared counter is spent: no later candidate, and no
                    # fallback, may proceed on a budget that is gone
                    _shared_exhausted = e
                    break
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
            # `construction_ops` is the PRODUCER's local construction only.
            # Passing cons + 2*cons here while price_regional_plan ALSO added
            # 2*cons into the checker field charged the checker's
            # reconstruction twice: on the ring, cons = 151,552 produced
            # 454,656 construction plus another 303,104 inside checker_ops.
            # Each phase is counted exactly once.
            cons = sum(int(getattr(rd, "construction_ops", 0)) for rd in rds)
            rprice = PR.price_regional_plan("regional:" + c["mode"], regs, crs,
                                            rds, proj, nq, t_level,
                                            construction_ops=cons)
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
            # ADMISSION ONLY. The full composed inference ran here just to
            # find out whether the candidate was usable, so an UNSELECTED
            # candidate incurred its entire inference cost. Admission
            # recognizes the mode, fits the residual and chooses Q with its
            # rounding energy charged -- all bounded by the coarse model's
            # local structure -- and the expensive evaluation happens after
            # selection, inside the registered executor.
            try:
                from mdi import composed as CM
                cctx = A.Ctx(160)
                cm_adm = CM.admit(r, regs, crs, rds, queries, cctx, eps,
                                  t_level=t_level,
                                  deadline=bg.deadline_fn("composed"))
                cm_out = True              # admitted, not yet evaluated
                cm_meta = {"Q": cm_adm["Q"],
                           "rounding_tv_charged": str(cm_adm["rounding_tv"]),
                           "fit_tv": str(cm_adm["fit_tv"]),
                           "residual_tv": str(cm_adm["total_fit_tv"]),
                           "regional_radius": str(cm_adm["t_level"]),
                           "total_radius": str(cm_adm["t_level"]
                                               + cm_adm["total_fit_tv"]),
                           "mode_kind": cm_adm["cand"].kind,
                           "mode_sign": cm_adm["cand"].signs[0],
                           "statistic_support": 0,
                           "admission_only": True}
            except Exception as e:
                rejected.append({"name": "composed:" + c["mode"],
                                 "reason": "composed route declined: %s: %s"
                                           % (type(e).__name__, e)})
                cm_out = None
                cm_adm = None
            if cm_out is not None:
                ccons = sum(int(getattr(rd, "construction_ops", 0))
                            for rd in rds)      # producer side only
                cprice = PR.price_regional_plan("composed:" + c["mode"], regs,
                                                crs, rds, proj, nq, t_level,
                                                construction_ops=ccons)
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
                                 "composed_admission": cm_adm,
                                 "composed_meta": cm_meta}))
                prices.append(cprice)
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
            # bind the SEMANTIC fields too, against the original restricted
            # model and the preprocessing proof the current inputs produce
            back.bind_check(mh, eh, qh, restricted=r,
                            preprocess_identity=simp.identity(),
                            max_precision=4096)
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
            # consume the checker's OWN metadata. Replacing it with
            # {"kind": "identity"} discarded independent_aggregation_checked,
            # so a result whose exact independent check HAD run and passed was
            # downgraded anyway.
            ok, fails, meta = checker(model, evidence, pub, eps,
                                      deadline_s=bg.remaining(),
                                      cap_bytes=cap_bytes)
            meta = dict(meta or {})
            meta["kind"] = "identity"
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
                                      deadline=bg.deadline_fn("check"),
                                      budget=bg)
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
    # The CERTIFIED statuses and the independently_verified property require
    # that the checking method the route depends on actually RAN. For identity
    # that includes the independent AGGREGATION cross-check; above its
    # enumeration cap producer and checker share one aggregate
    # implementation, so a common-mode fault is undetectable and the complete
    # status must not be claimed.
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
    status = ("CERTIFIED_RESEARCH_ROUTE" if crec.kind != "identity"
              else "CERTIFIED_FALLBACK_ONLY")
    return Outcome(status=status, intervals=pub, plan=out.plan,
                   prices=out.prices, rejected=rejected, stages=stages,
                   budget=bg.report(), preprocess=out.preprocess,
                   checker={"status": "VERIFIED", **(meta or {})},
                   properties=crec.properties.as_dict())


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
