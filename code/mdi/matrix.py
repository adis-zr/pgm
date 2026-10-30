"""The integrated acceptance matrix (spec §12, revision r17).

Every control enters through the public entry point (`pipeline.solve`) and,
where a persisted program is exercised, through the ONE loaded-object
boundary (`mdi.replay`, in a fresh interpreter or in-process with the same
validator, dispatcher and limits). Nothing here calls an executor or checker
with `budget=None`: every execution runs under the shared budget with the
production caps, so a resource stop is reported as a resource stop.

Every PASS row carries the advertised predicates: containment of the exact
truth, published width within the contract, the replay status, and the
resource obligations (the budget report with no stops and every meter within
its limit). Measurements are measured (expansion counters, operation counts,
budget usage); nothing is asserted by hand. A branch that the shared budget
refuses is a BLOCKED row naming the precise resource blocker, never a PASS.

    python -m mdi.matrix OUT.json [per_control_wall_s] [only ...]
"""
from __future__ import annotations
import sys, os, json, time, math, tempfile, subprocess, traceback, copy
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPS = Fr(1, 100)


# ------------------------------------------------------------------ helpers

def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def _dec(x):
    x = Fr(x)
    k = 0
    while (x * 10 ** k).denominator != 1:
        k += 1
    n = (x * 10 ** k).numerator
    return str(n) if k == 0 else "%d.%0*d" % (n // 10 ** k, k, n % 10 ** k)


def _write_uai(m):
    lines = ["MARKOV", str(m.nvars), " ".join(str(c) for c in m.card), str(len(m.factors))]
    for f in m.factors:
        lines.append("%d %s" % (len(f.scope), " ".join(str(v) for v in f.scope)))
    for f in m.factors:
        lines.append(str(len(f.table)))
        lines.append(" ".join(_dec(x) for x in f.table))
    fh = tempfile.NamedTemporaryFile("w", suffix=".uai", delete=False)
    fh.write("\n".join(lines) + "\n")
    fh.close()
    return fh.name


def _contains(pub, pt):
    return all(Fr(pub[v][s][0]) <= pt[v][s] <= Fr(pub[v][s][1])
               for v in pub for s in range(len(pub[v])))


def _contains_rep(rep, pt):
    iv = rep.get("intervals") or {}
    return bool(iv) and all(Fr(lo) <= pt[int(v)][s] <= Fr(hi)
                            for v, rows in iv.items() for s, (lo, hi) in enumerate(rows))


def _width(pub):
    return max((Fr(hi) - Fr(lo) for v in pub for lo, hi in pub[v]), default=Fr(0))


def _resource(bud):
    """The resource obligations of one guarded run: a budget report exists,
    no meter stopped, and every meter is within its declared limit."""
    bud = bud or {}
    used = bud.get("used") or {}
    lim = bud.get("limits") or {}
    within = all(used.get(k, 0) <= lim[k] for k in lim)
    return {"present": bool(bud), "stops": list(bud.get("stops") or []), "used": used,
            "limits": lim, "ok": bool(bud) and not bud.get("stops") and within}


def _solve(m, wall, evidence=None, queries=None):
    from mdi import pipeline as PLN, factors as FX
    d = tempfile.mkdtemp()
    FX.reset_expansion_counter()
    t = time.time()
    res = PLN.solve(m, evidence or {}, queries=queries, wall_s=wall, cap_bytes=1 << 30,
                    plan_dir=d)
    el = time.time() - t
    exp = dict(FX.EXPANSIONS)
    return res, d, el, exp


def _plan(res, d, name):
    """Plan files are named by the candidate's STABLE identity."""
    p = next(x for x in res.prices if x["name"] == name)
    return os.path.join(d, p["identity"] + ".plan.json")


def _price(res, name):
    return next(x for x in res.prices if x["name"] == name)


def _replay_fresh(mp, plan, timeout):
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE
    out = subprocess.run([sys.executable, "-m", "mdi.replay", mp, "-", plan], cwd=HERE,
                         capture_output=True, text=True, timeout=timeout, env=env)
    if not out.stdout.strip():
        raise RuntimeError("replay produced no output: %s" % out.stderr[-600:])
    return json.loads(out.stdout)


def _replay_here(mp, plan, wrap=None):
    """The same boundary in-process (bind -> admission -> run_loaded under a
    fresh shared budget with the pipeline's limits); used where a fault is
    injected into the producer or operations are counted."""
    from mdi import replay as RP
    return RP.replay(mp, "-", plan, wrap=wrap)


def _unique(res):
    ids = [p["identity"] for p in res.prices]
    dups = [x for x in res.rejected if "duplicate" in x["reason"]]
    return {"records": len(ids), "distinct_identities": len(set(ids)),
            "duplicates_rejected_with_reason": len(dups),
            "duplicate_reasons": [x["reason"][:80] for x in dups[:3]],
            "ok": len(ids) == len(set(ids)) and all("identity" in x["reason"] for x in dups)}


def _measure_ops():
    """A wrap(stage, fn) that counts Fraction operations per stage."""
    import fractions
    counts = {}
    saved = {nm: getattr(fractions.Fraction, nm) for nm in
             ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__", "__rtruediv__",
              "__sub__", "__rsub__")}
    box = {"n": 0}

    def mk(fn):
        def w_(self, other, *a):
            box["n"] += 1
            return fn(self, other, *a)
        return w_

    def wrap(stage, fn):
        for nm, f in saved.items():
            setattr(fractions.Fraction, nm, mk(f))
        box["n"] = 0
        try:
            return fn()
        finally:
            for nm, f in saved.items():
                setattr(fractions.Fraction, nm, f)
            counts[stage] = box["n"]
    return wrap, counts


# ----------------------------------------------------------------- fixtures

def _two_block_signed():
    from mdi import model as M
    n = 6
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(v, 20)], origin=v) for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            J = 0.25 if (i < 3 and j < 3) else (-0.20 if (i >= 3 and j >= 3) else 0.05)
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _two_equal_blocks(J=0.25, nb=2, bs=3):
    from mdi import model as M
    n = nb * bs
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(5 + 5 * (v % 2), 100)], origin=v)
            for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if i // bs == j // bs:
                facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _triangle(a=0.15, b=0.05, c=-0.05):
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(10 * (v + 1), 100)], origin=v)
            for v in range(3)]
    for (i, j), J in (((0, 1), a), ((0, 2), b), ((1, 2), c)):
        if J:
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=10 + i * 3 + j))
    return M.Model(nvars=3, card=[2] * 3, factors=facs).validate()


def _categorical_pairwise():
    """Four 3-state variables with pairwise contrasts: the categorical menu's
    natural input (rank-1 categorical features, combined, masked)."""
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(3,), table=[Fr(1), Fr(1) + Fr(v + 1, 10), Fr(1) - Fr(v + 1, 20)],
                     origin=v) for v in range(4)]
    for i in range(4):
        for j in range(i + 1, 4):
            tab = [Fr(1) + Fr(((a + b) % 3) - 1, 10) * Fr(1, 1 + ((i + j) % 2))
                   for a in range(3) for b in range(3)]
            facs.append(M.Factor(scope=(i, j), card=(3, 3), table=tab, origin=10 + 4 * i + j))
    return M.Model(nvars=4, card=[3] * 4, factors=facs).validate()


def _categorical():
    from mdi import model as M
    facs = [M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(1), Fr(2), Fr(0), Fr(3), Fr(1), Fr(5)], origin=0),
            M.Factor(scope=(1, 2, 3), card=(3, 2, 2),
                     table=[Fr(x) for x in (1, 2, 1, 0, 2, 1, 1, 3, 1, 1, 2, Fr(1, 10 ** 9))], origin=1),
            M.Factor(scope=(4, 5), card=(2, 3), table=[Fr(2), Fr(1), Fr(1), Fr(1), Fr(0), Fr(4)], origin=2)]
    return M.Model(nvars=6, card=[2, 3, 2, 2, 2, 3], factors=facs).validate()


def _mean_field_path(n, J):
    from tests.test_mdi_research import mean_field, w
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
    return w(mean_field(n, J, fields))


# ---------------------------------------------------------------- controls

def control_identity_replay(wall):
    """F1: the identity program governs the public run and a fresh process;
    the identity checker runs at the program's checker precision."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import TINY, w
    mp = w(TINY)
    m = M.read_uai(mp)
    res, d, el, exp = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    plan = _plan(res, d, "identity")
    rep = _replay_fresh(mp, plan, wall)
    prog = json.load(open(plan))["program"]
    prec_ok = (int(res.checker.get("checker_precision_bits", -1)) == int(prog["checker"]["precision"])
               and str(rep.get("checker", {}).get("checker_precision_bits")) == str(prog["checker"]["precision"]))
    rs = _resource(res.budget)
    rr = _resource(rep.get("budget"))
    return {"pipeline": res.status, "chosen": res.plan.get("chosen"), "identity": res.plan.get("identity"),
            "truth": _contains(res.intervals, pt), "width": str(_width(res.intervals)),
            "replay": rep["status"], "replay_truth": _contains_rep(rep, pt),
            "checker_precision_program": prog["checker"]["precision"],
            "checker_precision_run": res.checker.get("checker_precision_bits"),
            "resources_pipeline": rs, "resources_replay": rr, "seconds": round(el, 2),
            "ok": (res.status == "CERTIFIED_FALLBACK_ONLY" and res.plan.get("chosen") == "identity"
                   and rep["status"] == "REPLAY_VERIFIED" and _contains(res.intervals, pt)
                   and _contains_rep(rep, pt) and _width(res.intervals) <= EPS and prec_ok
                   and rs["ok"] and rr["ok"])}


def control_regional_two_scales_replay(wall):
    """F2: compact one- and two-scale programs selected and replayed fresh;
    unique identities; the altered witness rejects on the named obligation;
    dense expansions are MEASURED."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import ring_of_blocks, w
    mp = w(ring_of_blocks()[0])
    m = M.read_uai(mp)
    res, d, el, exp = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    names = [p["name"] for p in res.prices]
    l1 = next(n for n in names if n.startswith("regional:") and "@64" in n and not n.endswith(":L2"))
    l2 = next(n for n in names if n.startswith("regional:") and n.endswith(":L2"))
    r1 = _replay_fresh(mp, _plan(res, d, l1), wall)
    r2 = _replay_fresh(mp, _plan(res, d, l2), wall)
    base = json.load(open(_plan(res, d, l1)))
    bad = copy.deepcopy(base)
    for c in bad["program"]["scales"][0]["regions"][0]["cells"]:
        tot = Fr(c["M"])
        vs = sorted({int(k.split(",")[0]) for k in c["N"]})
        c["N"] = {}
        for v in vs:
            c["N"]["%d,0" % v] = str(tot * Fr(9, 10))
            c["N"]["%d,1" % v] = str(tot * Fr(1, 10))
    p2 = os.path.join(d, "altered.plan.json")
    json.dump(bad, open(p2, "w"))
    alt = _replay_fresh(mp, p2, wall)
    uq = _unique(res)
    rs = _resource(res.budget)
    ok = (res.status == "CERTIFIED_RESEARCH_ROUTE" and _contains(res.intervals, pt)
          and _width(res.intervals) <= EPS
          and r1["status"] == "REPLAY_VERIFIED" and r2["status"] == "REPLAY_VERIFIED"
          and _contains_rep(r1, pt) and _contains_rep(r2, pt)
          and _resource(r1.get("budget"))["ok"] and _resource(r2.get("budget"))["ok"]
          and alt["status"] == "REPLAY_REJECTED"
          and "alpha_b A_{R,i,a}" in (alt.get("failures") or [""])[0]
          and uq["ok"] and rs["ok"] and exp["entries"] <= 4096 * max(1, exp["materializations"]))
    return {"pipeline": res.status, "chosen": res.plan.get("chosen"), "research": res.plan.get("research"),
            "truth": _contains(res.intervals, pt), "width": str(_width(res.intervals)),
            "replay_L1": r1["status"], "replay_L2": r2["status"],
            "replay_L1_truth": _contains_rep(r1, pt), "replay_L2_truth": _contains_rep(r2, pt),
            "altered": alt["status"], "altered_obligation": (alt.get("failures") or [""])[0][:100],
            "measured_expansions_during_solve": exp, "unique_candidates": uq,
            "resources_pipeline": rs, "complete_cost": res.plan.get("complete_cost"),
            "seconds": round(el, 2), "ok": ok}


def control_compact_structural_refusal(wall):
    """F3: a grouping whose lifted compact view exceeds the declared cap is
    refused for its SCHEDULE price without any dense expansion (measured),
    on a local fixture and -- when present -- on the external Pedigree input
    through the pipeline's VERIFIED simplification. Construction probes:
    nothing is executed."""
    from mdi import model as M, regions as R, marked as MK, routes as RT, pricing as PR, factors as FX
    from mdi import preprocess as PRE
    out = {"label": "construction probes through the verified simplification; no execution"}
    # local: two regions of seven binary variables joined by a complete
    # bipartite set of weak couplings, so every variable is boundary and each
    # region keeps 128 cells: every crossing view is a 128 x 128 = 16,384-entry
    # compact map, above the 4,096-entry message cap
    k = 7
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 7, 20)], origin=v)
            for v in range(2 * k)]
    for i in range(k):
        for j in range(k):
            facs.append(M.Factor(scope=(i, k + j), card=(2, 2),
                                 table=_pair(0.05 * (1 + ((i + j) % 3)) / 2), origin=100 + 10 * i + j))
    regs = [tuple(range(k)), tuple(range(k, 2 * k))]
    m = M.Model(nvars=2 * k, card=[2] * (2 * k), factors=facs).validate()
    r0 = M.restrict(m, {})
    simp = PRE.simplify(r0)
    PRE.verify_identities(r0, simp)
    r = M.Restricted(model=m, evidence={}, factors=simp.factors, free=list(simp.free),
                     card=dict(simp.card), constant=r0.constant, impossible_factor=None)
    FX.reset_expansion_counter()
    t = time.time()
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, set(r.free)), regs, 1)
    big = max(f.size() for f in final.factors)
    views = sum(1 for f in final.factors if FX.is_view(f))
    price, order = PR.price_program("local", "regional", final, scales, None,
                                    sum(r.card[v] for v in r.free),
                                    sum(rd.construction_ops for sc in scales for rd in sc.rds))
    exp_local = dict(FX.EXPANSIONS)
    out["local"] = {"built_s": round(time.time() - t, 2), "cells": [len(c.cells) for c in scales[0].coarse],
                    "views": views, "largest_view_entries": big,
                    "measured_expansions": exp_local, "eligible": price.eligible,
                    "refusal": price.ineligible_reason[:140]}
    local_ok = views > 0 and big > 4096 and not price.eligible and exp_local["entries"] == 0 \
        and "cap" in price.ineligible_reason
    # external (construction only, verified simplification, nothing executed)
    p = "/tmp/tep/three_external_problems/inputs/Pedigree_11"
    ext_ok = True
    if os.path.exists(p + ".uai"):
        me = M.read_uai(p + ".uai")
        ev = M.read_evidence(p + ".uai.evid", me)
        re0 = M.restrict(me, ev)
        simp = PRE.simplify(re0)
        PRE.verify_identities(re0, simp)
        re = M.Restricted(model=me, evidence=dict(ev), factors=simp.factors, free=list(simp.free),
                          card=dict(simp.card), constant=re0.constant, impossible_factor=None)
        q = set(re.free)
        c = [c for c in R.propose_partitions(re.free, re.card, re.factors) if c["mode"] != "singleton"][0]
        FX.reset_expansion_counter()
        t = time.time()
        scales, final = RT.build_scales(MK.Marked.from_restricted(re, q), [tuple(x) for x in c["regions"]], 1)
        tb = time.time() - t
        views = sum(1 for f in final.factors if FX.is_view(f))
        big = max(f.size() for f in final.factors)
        price, order = PR.price_program("ext", "regional", final, scales, None, sum(re.card[v] for v in q),
                                        sum(rd.construction_ops for sc in scales for rd in sc.rds))
        exp_ext = dict(FX.EXPANSIONS)
        out["external_Pedigree_11"] = {
            "label": "simplified restricted model (PRE.simplify + verify_identities); construction only",
            "free_after_simplification": len(re.free), "built_s": round(tb, 2),
            "regions": len(c["regions"]), "views": views, "largest_view_entries": big,
            "measured_expansions": exp_ext, "eligible": price.eligible,
            "refusal": price.ineligible_reason[:140]}
        ext_ok = views > 0 and big > 4096 and not price.eligible and exp_ext["entries"] == 0
    else:
        out["external_Pedigree_11"] = {"present": False,
                                       "note": "external inputs absent; the local witness is the mandatory one"}
    out["ok"] = local_ok and ext_ok
    return out


def control_independent_representation_and_readout(wall):
    """F4: the checker's proof of the original query is independent: the
    compact-compose fault, the shared-readout fault, the statistic
    state-count fault and the Fourier payload fault each REJECT on the
    containment obligation through the same loaded-object boundary, with
    their clean counterparts VERIFIED under identical publication rules;
    categorical / hard-zero / subset restoration verifies."""
    from mdi import model as M, oracle as O, factors as FX, marked as MK, collective_jt as CJ
    from tests.test_mdi_research import ring_of_blocks, w
    out = {}
    oks = []

    def pair_(label, mp, plan, pt, patch_target, attr, faulty, obligation="does NOT contain"):
        clean = _replay_here(mp, plan)
        orig = getattr(patch_target, attr)
        setattr(patch_target, attr, faulty(orig))
        try:
            bad = _replay_here(mp, plan)
        finally:
            setattr(patch_target, attr, orig)
        fail0 = (bad.get("failures") or [""])[0]
        rs = _resource(clean.get("budget"))
        ok = (clean["status"] == "REPLAY_VERIFIED" and _contains_rep(clean, pt)
              and Fr(clean["max_width"]) <= EPS and rs["ok"]
              and bad["status"] == "REPLAY_REJECTED" and obligation in fail0)
        out[label] = {"clean": clean["status"], "clean_truth": _contains_rep(clean, pt),
                      "clean_width": clean["max_width"], "clean_resources": rs,
                      "fault": bad["status"], "fault_obligation": fail0[:110],
                      "fault_intervals_x0": (bad.get("intervals") or {}).get("0"), "ok": ok}
        oks.append(ok)

    # ring: compose fault (producer-side offset maps corrupted) and shared readout fault
    mp = w(ring_of_blocks()[0])
    m = M.read_uai(mp)
    res, d, el, exp = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    l1 = next(p["name"] for p in res.prices if p["name"].startswith("regional:") and "@64" in p["name"]
              and not p["name"].endswith(":L2"))
    plan = _plan(res, d, l1)

    def compose_fault(orig):
        def faulty(self, region_of, reps, bpos, ncell):
            v = orig(self, region_of, reps, bpos, ncell)
            i = min(v.offsets)
            if len(v.offsets[i]) >= 2:
                v.offsets[i] = list(reversed(v.offsets[i]))
            return FX.ProjectedFactor(scope=v.scope, card=v.card, offsets=v.offsets, base=v.base,
                                      origin=v.origin, scale=v.scale)
        return faulty
    pair_("compact_compose_fault", mp, plan, pt, FX.ProjectedFactor, "compose", compose_fault)

    def readout_fault(orig):
        def faulty(marked, Z, counts):
            o = orig(marked, Z, counts)
            return {v: [(lo * Fr(9, 5), hi * Fr(9, 5)) if s == 0 else (lo / 5, hi / 5)
                        for s, (lo, hi) in enumerate(rws)] for v, rws in o.items()}
        return faulty
    pair_("shared_readout_fault", mp, plan, pt, MK, "read_original", readout_fault)

    # mean field 4: statistic state-count fault and Fourier payload fault
    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, el4, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])

    def stat_fault(orig):
        def faulty(marked, cand, Q, ctx, *a, **k):
            Zr, counts, meta = orig(marked, cand, Q, ctx, *a, **k)
            counts = {v: [(lo * 3, hi * 3) if s == 0 else (lo, hi) for s, (lo, hi) in enumerate(rows)]
                      for v, rows in counts.items()}
            return Zr, counts, meta
        return faulty
    pair_("statistic_state_count_fault", mp4, _plan(res4, d4, stat), pt4, CJ, "statistic_evaluate", stat_fault)

    mpf = _mean_field_path(4, -0.22)
    mf = M.read_uai(mpf)
    resf, df, elf, _ = _solve(mf, wall)
    Z, ptf = O.exact_all_marginals(M.restrict(mf, {}))
    four = next(p["name"] for p in resf.prices if p["name"].startswith("fourier:") and p["eligible"])

    def payload_fault(orig):
        def faulty(marked, marg, others, alg):
            o = orig(marked, marg, others, alg)
            for v in o:
                o[v][0] = alg.mul(o[v][0], (Fr(3), Fr(3), Fr(0), Fr(0)) if alg.name == "complex"
                                  else (Fr(3), Fr(3)))
            return o
        return faulty
    pair_("fourier_payload_fault", mpf, _plan(resf, df, four), ptf, CJ, "_own_mass_contribution",
          payload_fault)

    # categorical / hard zero / subset restoration through the public entry
    mc = _categorical()
    resc, dc, elc, _ = _solve(mc, wall, evidence={3: 1}, queries={0, 1, 5})
    Z, ptc = O.exact_all_marginals(M.restrict(mc, {3: 1}))
    reg = [p["name"] for p in resc.prices if p["name"].startswith("regional:") and p["eligible"]]
    cat = {"pipeline": resc.status, "chosen": resc.plan.get("chosen"),
           "truth": _contains({v: resc.intervals[v] for v in (0, 1, 5)}, ptc),
           "width": str(_width({v: resc.intervals[v] for v in (0, 1, 5)})),
           "resources": _resource(resc.budget), "regional_records": reg}
    cat_ok = resc.status.startswith("CERTIFIED") and cat["truth"] and Fr(cat["width"]) <= EPS \
        and cat["resources"]["ok"]
    if reg:
        mpc = _write_uai(mc)
        # replay needs the evidence file
        evp = mpc + ".evid"
        open(evp, "w").write("1 3 1\n")
        from mdi import replay as RP
        rc = RP.replay(mpc, evp, _plan(resc, dc, reg[0]))
        cat["regional_replay"] = rc["status"]
        cat["regional_replay_truth"] = _contains_rep(rc, ptc)
        cat["regional_replay_reason"] = str(rc.get("reason"))[:100]
        cat_ok = cat_ok and rc["status"] == "REPLAY_VERIFIED" and _contains_rep(rc, ptc)
    cat["ok"] = cat_ok
    out["categorical_zero_subset"] = cat
    oks.append(cat_ok)
    out["ok"] = all(oks)
    return out


def control_portfolio_menu_and_identity(wall):
    """F5: the specified bounded algorithm is the candidate portfolio: block
    recognition keeps within-block data and the incidence of equal blocks,
    the mask menu and categorical menu are offered, every certified
    representation is offered to every applicable evaluator (pure-sign
    multiple modes included), candidates are unique by IDENTITY, coarse Q is
    bound-selected, and a vector statistic program runs and verifies."""
    from mdi import model as M, oracle as O, modes as MO
    from tests.test_mdi_research import ring_of_blocks, w
    out = {}
    # two-block signed model
    m = _two_block_signed()
    mp = _write_uai(m)
    res, d, el, exp = _solve(M.read_uai(mp), wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    names = {p["name"]: p for p in res.prices}
    progs = {n: json.load(open(_plan(res, d, n)))["program"] for n in names if names[n]["identity"]}
    kinds = sorted({(n.split(":")[0], progs[n]["collective"]["candidate"]["kind"],
                     tuple(progs[n]["collective"]["candidate"]["signs"]))
                    for n in progs if progs[n].get("collective")})
    cands, info = MO.propose_modes(list(M.restrict(m, {}).free), M.restrict(m, {}).factors,
                                   M.restrict(m, {}).card)
    bm = info.get("block_matrix")
    vec = next((n for n in names if n.startswith("statistic:block_combined")), None)
    out["two_block_signed"] = {
        "pipeline": res.status, "chosen": res.plan.get("chosen"), "truth": _contains(res.intervals, pt),
        "evaluator_kind_signs": [list(k) for k in kinds],
        "block_matrix_from_recognizer": bm,
        "mixed_offered_and_priced": [n for n in names if n.startswith("mixed:")],
        "mixed_eligibility": {n: (names[n]["eligible"], names[n]["ineligible_reason"][:90])
                              for n in names if n.startswith("mixed:")},
        "masks_offered": sorted({n.split(":")[1] for n in names if "_forest" in n or "_augmented" in n
                                 or "_outlier" in n}),
        "unique_candidates": _unique(res), "resources": _resource(res.budget)}
    ok = (res.status.startswith("CERTIFIED") and _contains(res.intervals, pt) and vec is not None
          and bm is not None and all(abs(bm[i][i]) > 0 for i in range(len(bm)))
          and any(e == "mixed" for e, k, s in kinds)
          and any("_forest" in n for n in names) and out["two_block_signed"]["unique_candidates"]["ok"]
          and out["two_block_signed"]["resources"]["ok"])
    if vec:
        rv = _replay_here(mp, _plan(res, d, vec))
        out["two_block_signed"]["vector_statistic_replay"] = {
            "name": vec, "status": rv["status"], "truth": _contains_rep(rv, pt), "width": rv.get("max_width"),
            "rank": len(progs[vec]["collective"]["candidate"]["signs"]),
            "Q": progs[vec]["collective"]["Q"], "support": (rv.get("executor") or {}).get("statistic_support"),
            "resources": _resource(rv.get("budget"))}
        ok = ok and rv["status"] == "REPLAY_VERIFIED" and _contains_rep(rv, pt) \
            and Fr(rv["max_width"]) <= EPS and _resource(rv.get("budget"))["ok"]
    # two EQUAL disconnected blocks: two block modes (incidence preserved), a
    # pure-sign rank-2 candidate offered to statistic AND Gaussian
    m2 = _two_equal_blocks()
    mp2 = _write_uai(m2)
    res2, d2, el2, _ = _solve(M.read_uai(mp2), wall)
    Z, pt2 = O.exact_all_marginals(M.restrict(m2, {}))
    n2 = {p["name"]: p for p in res2.prices}
    pure = {}
    for n in n2:
        if n2[n]["identity"] and n.split(":")[0] in ("statistic", "gaussian", "fourier"):
            pg = json.load(open(_plan(res2, d2, n)))["program"]["collective"]
            if len(pg["candidate"]["signs"]) >= 2:
                pure[n] = {"signs": pg["candidate"]["signs"], "eligible": n2[n]["eligible"],
                           "reason": n2[n]["ineligible_reason"][:110],
                           "metered_entries_forecast": (n2[n]["counters"].get("metered_entries_forecast") or {}).get("value")}
    eq = {"pipeline": res2.status, "truth": _contains(res2.intervals, pt2),
          "pure_sign_multi_mode_candidates": pure, "unique_candidates": _unique(res2),
          "resources": _resource(res2.budget)}
    gauss2 = [n for n in pure if n.startswith("gaussian:block_combined")]
    stat2 = [n for n in pure if n.startswith("statistic:block_combined")]
    ok2 = (res2.status.startswith("CERTIFIED") and eq["truth"] and gauss2 and stat2
           and all(s == 1 for s in pure[gauss2[0]]["signs"]) and eq["unique_candidates"]["ok"]
           and eq["resources"]["ok"])
    if stat2:
        rs2 = _replay_here(mp2, _plan(res2, d2, stat2[0]))
        eq["statistic_block_combined_replay"] = {"status": rs2["status"], "truth": _contains_rep(rs2, pt2),
                                                 "width": rs2.get("max_width"),
                                                 "resources": _resource(rs2.get("budget"))}
        ok2 = ok2 and rs2["status"] == "REPLAY_VERIFIED" and _contains_rep(rs2, pt2)
    out["two_equal_disconnected_blocks"] = eq
    # categorical menu on a pairwise 3-state model, through the pipeline
    mc = _categorical_pairwise()
    mpc = _write_uai(mc)
    resc, dc, elc, _ = _solve(M.read_uai(mpc), wall)
    Z, ptc = O.exact_all_marginals(M.restrict(mc, {}))
    catn = sorted({p["name"] for p in resc.prices if "categorical" in p["name"]})
    out["categorical_menu"] = {"records": catn, "pipeline": resc.status, "truth": _contains(resc.intervals, ptc),
                               "unique_candidates": _unique(resc), "resources": _resource(resc.budget)}
    okc = (any("categorical_rank1" in k for k in catn) and any("categorical_combined" in k for k in catn)
           and any("_forest" in k for k in catn) and resc.status.startswith("CERTIFIED")
           and _contains(resc.intervals, ptc) and out["categorical_menu"]["unique_candidates"]["ok"])
    cstat = next((k for k in catn if k.startswith("statistic:categorical_rank1")), None)
    if cstat:
        rcs = _replay_here(mpc, _plan(resc, dc, cstat))
        out["categorical_menu"]["statistic_categorical_replay"] = {
            "status": rcs["status"], "truth": _contains_rep(rcs, ptc), "width": rcs.get("max_width"),
            "resources": _resource(rcs.get("budget"))}
        okc = okc and rcs["status"] == "REPLAY_VERIFIED" and _contains_rep(rcs, ptc) \
            and Fr(rcs["max_width"]) <= EPS
    # coarse Q on the composed ring, read from the PERSISTED record
    mr = _write_uai(M.read_uai(w(ring_of_blocks()[0])))
    resr, dr, elr, _ = _solve(M.read_uai(mr), wall)
    comp = [p for p in resr.prices if p["name"].startswith("composed:") and ":statistic:" in p["name"]]
    qs = {p["name"]: json.load(open(_plan(resr, dr, p["name"])))["program"]["collective"]["Q"] for p in comp}
    out["composed_ring_coarse_Q"] = {"Q_by_record": qs, "all_below_2^16": bool(qs) and all(q < (1 << 16) for q in qs.values())}
    okq = bool(qs) and all(q < (1 << 16) for q in qs.values())
    out["ok"] = bool(ok and ok2 and okc and okq)
    return out


def control_mixed_under_shared_budget(wall):
    """F6: the mixed Gaussian/Fourier branch under the NORMAL shared budget.
    The smallest genuinely mixed candidates are admitted, priced on their
    saved order, persisted and deduplicated; their forecast metered entry
    visits are compared with the shared cap; the pipeline and a fresh replay
    refuse what the price refuses; the guarded component run confirms the
    stop. If no fixture is admissible, the row is BLOCKED with the precise
    resource blocker (never a PASS, never an unguarded run)."""
    from mdi import model as M, oracle as O, routes as RT, plantype as PT, budget as B, config as K
    from mdi import solve as S
    fixtures = [("triangle 0.15/0.05/-0.05", _triangle(0.15, 0.05, -0.05)),
                ("triangle 0.05/0/-0.05", _triangle(0.05, 0.0, -0.05)),
                ("chain -0.05/-0.05", _triangle(-0.05, 0.0, -0.05)),
                ("chain -0.01/-0.01", _triangle(-0.01, 0.0, -0.01))]
    rows = []
    best = None
    for label, m in fixtures:
        mp = _write_uai(m)
        res, d, el, _ = _solve(M.read_uai(mp), wall)
        for p in res.prices:
            if not p["name"].startswith("mixed:"):
                continue
            prog = json.load(open(_plan(res, d, p["name"])))["program"]["collective"]
            c = p["counters"]
            row = {"fixture": label, "name": p["name"], "signs": prog["candidate"]["signs"],
                   "nodes_per_mode": [l["nodes"] for l in prog["lattices"]],
                   "eligible": p["eligible"], "refusal": p["ineligible_reason"][:160],
                   "metered_entries_forecast": (c.get("metered_entries_forecast") or {}).get("value"),
                   "producer_entries": (c.get("producer_metered_entries") or {}).get("value"),
                   "checker_entries": (c.get("checker_metered_entries") or {}).get("value"),
                   "remaining_cost": p["total_arithmetic"]["value"], "identity": p["identity"],
                   "plan": _plan(res, d, p["name"]), "model_path": mp, "pipeline": res.status,
                   "unique_candidates": _unique(res)["ok"]}
            rows.append(row)
            f = int(row["metered_entries_forecast"] or 0)
            if best is None or f < best[0]:
                best = (f, row)
    cap = K.CAPS["local_mass_entries"]
    out = {"candidates": [{k: v for k, v in r.items() if k not in ("plan", "model_path")} for r in rows],
           "shared_cap_local_mass_entries": cap}
    if not rows:
        out["ok"] = False
        out["reason"] = "no mixed candidate was admitted on any fixture"
        return out
    admissible = [r for r in rows if r["eligible"]]
    if admissible:
        r = admissible[0]
        rep = _replay_fresh(r["model_path"], r["plan"], wall)
        m = M.read_uai(r["model_path"])
        Z, pt = O.exact_all_marginals(M.restrict(m, {}))
        out["admissible_run"] = {"name": r["name"], "fixture": r["fixture"], "replay": rep["status"],
                                 "truth": _contains_rep(rep, pt), "width": rep.get("max_width"),
                                 "executor": rep.get("executor"), "resources": _resource(rep.get("budget"))}
        out["ok"] = (rep["status"] == "REPLAY_VERIFIED" and _contains_rep(rep, pt)
                     and Fr(rep["max_width"]) <= EPS and _resource(rep.get("budget"))["ok"]
                     and (rep.get("executor") or {}).get("omitted_positive_nodes", "0") not in ("0", 0))
        return out
    # BLOCKED: the smallest forecast against the cap; the pipeline's and the
    # fresh replay's refusals; the guarded component run's measured stop
    f, r = best
    rep = _replay_fresh(r["model_path"], r["plan"], wall)
    rec = PT.PlanRecord.from_json(open(r["plan"]).read())
    m = M.read_uai(r["model_path"])
    bg = B.Budget(wall_s=wall, limits={"profile_comparisons": K.CAPS["profile_entry_comparisons"],
                                        "local_mass_entries": cap},
                  rss_fn=S._rss_bytes, rss_limit=1 << 30)
    t = time.time()
    stop = None
    try:
        RT.execute(rec.parsed_program, M.restrict(m, {}), set(rec.parsed_program["queries"]),
                   deadline=bg.deadline_fn("component"), budget=bg)
        comp = "COMPLETED"
    except B.BudgetExceeded as e:
        comp = "RESOURCE_STOP"
        stop = {"kind": e.kind, "used": e.used, "limit": e.limit, "where": e.where}
    out["blocked"] = True
    out["smallest_mixed_candidate"] = {k: v for k, v in r.items() if k not in ("plan", "model_path")}
    out["pipeline_refusal"] = r["refusal"]
    out["fresh_replay"] = {"status": rep["status"], "reason": str(rep.get("reason"))[:200]}
    out["guarded_component_run"] = {"outcome": comp, "stop": stop, "seconds": round(time.time() - t, 1),
                                    "used": dict(bg.used),
                                    "label": "the persisted program executed under a fresh shared budget "
                                             "with the production caps, outside selection, to confirm the "
                                             "forecast stop; not a certified result"}
    out["precise_blocker"] = (
        "every genuinely mixed candidate on the smallest fixtures needs a %d x %d-node tensor lattice "
        "(positive quadrature allowance %s, negative delta from L = exp(-Y_max)); the smallest forecast "
        "metered entry visits (producer + checker) is %d against the shared cumulative cap of %d; the "
        "pipeline refuses it by price, a fresh replay refuses it by the same rule, and the guarded "
        "component run stops at %s. No cap was enlarged."
        % (r["nodes_per_mode"][0], r["nodes_per_mode"][1], K.RADII["gaussian_quadrature"], f, cap,
           (stop or {}).get("used")))
    out["ok"] = (not r["eligible"] and "cap" in r["refusal"] and rep["status"] == "REPLAY_REFUSED"
                 and comp == "RESOURCE_STOP" and stop["kind"] == "local_mass_entries"
                 and f > cap and r["unique_candidates"])
    return out


def control_price_covers_counted_work(wall):
    """F7: priced bounds cover the COUNTED producer and checker operations
    and the MEASURED metered entries and liveness of guarded replays on
    statistic (scalar and vector), Fourier, regional and composed programs;
    the price is on the saved order and a legal different order does not
    bind."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import ring_of_blocks, w
    rows = []
    all_ok = True

    def check(label, mp, res, d, name, pt):
        wrap, counts = _measure_ops()
        rep = _replay_here(mp, _plan(res, d, name), wrap=wrap)
        p = _price(res, name)
        c = p["counters"]
        pp = sum(int(c[k]["value"]) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops"))
        pc = int(c["checker_ops"]["value"])
        used = (rep.get("budget") or {}).get("used", {}).get("local_mass_entries", 0)
        fc = (c.get("metered_entries_forecast") or {}).get("value")
        ex = rep.get("executor") or {}
        live_m = ex.get("peak_live_entries")
        live_p = int(c["peak_live_message_entries"]["value"]) + int(c["final_largest_bag"]["value"])
        row = {"control": label, "program": name, "replay": rep["status"], "truth": _contains_rep(rep, pt),
               "width": rep.get("max_width"),
               "producer_priced": pp, "producer_counted": counts.get("execute"),
               "checker_priced": pc, "checker_counted": counts.get("check"),
               "metered_entries_forecast": fc, "metered_entries_measured": used,
               "peak_live_priced": live_p, "peak_live_measured": live_m,
               "resources": _resource(rep.get("budget"))}
        row["covers"] = (pp >= (counts.get("execute") or 0) and pc >= (counts.get("check") or 0)
                         and fc is not None and int(fc) >= int(used)
                         and (live_m is None or int(live_m) <= live_p))
        row["ok"] = (rep["status"] == "REPLAY_VERIFIED" and row["truth"] and Fr(rep["max_width"]) <= EPS
                     and row["covers"] and row["resources"]["ok"])
        rows.append(row)
        return row["ok"]

    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, _, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])
    all_ok &= check("mean-field-4 statistic", mp4, res4, d4, stat, pt4)
    mpf = _mean_field_path(4, -0.22)
    mf = M.read_uai(mpf)
    resf, df, _, _ = _solve(mf, wall)
    Z, ptf = O.exact_all_marginals(M.restrict(mf, {}))
    four = next(p["name"] for p in resf.prices if p["name"].startswith("fourier:") and p["eligible"])
    all_ok &= check("mean-field-4 fourier", mpf, resf, df, four, ptf)
    mpr = w(ring_of_blocks()[0])
    mr = M.read_uai(mpr)
    resr, dr, _, _ = _solve(mr, wall)
    Z, ptr = O.exact_all_marginals(M.restrict(mr, {}))
    l1 = next(p["name"] for p in resr.prices if p["name"].startswith("regional:") and "@64" in p["name"]
              and not p["name"].endswith(":L2"))
    all_ok &= check("ring regional L1", mpr, resr, dr, l1, ptr)
    comp = next((p["name"] for p in resr.prices if p["name"].startswith("composed:") and ":statistic:" in p["name"]
                 and p["eligible"]), None)
    if comp:
        all_ok &= check("ring composed statistic", mpr, resr, dr, comp, ptr)
    mb = _two_block_signed()
    mpb = _write_uai(mb)
    resb, db, _, _ = _solve(M.read_uai(mpb), wall)
    Z, ptb = O.exact_all_marginals(M.restrict(mb, {}))
    vec = next((p["name"] for p in resb.prices if p["name"].startswith("statistic:block_combined")), None)
    if vec:
        all_ok &= check("two-block vector statistic", mpb, resb, db, vec, ptb)
    # saved-order pricing: a legal but different order does not bind
    base = json.load(open(_plan(resr, dr, l1)))
    bad = copy.deepcopy(base)
    order = list(bad["program"]["order"])
    bad["program"]["order"] = order[1:] + order[:1] if len(order) > 1 else order
    p2 = os.path.join(dr, "reordered.plan.json")
    json.dump(bad, open(p2, "w"))
    rep = _replay_here(mpr, p2)
    saved = {"status": rep["status"], "reason": str(rep.get("reason"))[:160],
             "ok": rep["status"] == "REPLAY_REFUSED" and "SAVED order" in str(rep.get("reason"))}
    all_ok &= saved["ok"]
    return {"rows": rows, "saved_order_witness": saved, "ok": bool(all_ok)}


def control_public_selection(wall):
    """F8: the public pipeline selects the REMAINING-cost argmin among
    admissible loaded programs under one stated convention; the complete
    invocation cost and the budget report are returned; identity may win."""
    from mdi import model as M, oracle as O
    out = []
    ok = True
    for n in (6, 9):
        mp = _mean_field_path(n, 0.30)
        m = M.read_uai(mp)
        Z, pt = O.exact_all_marginals(M.restrict(m, {}))
        res, d, el, _ = _solve(m, wall)
        elig = {p["name"]: int(p["total_arithmetic"]["value"]) for p in res.prices
                if p["eligible"] and p["total_arithmetic"]["value"] is not None}
        argmin = min(elig, key=elig.get)
        conv = {p["total_arithmetic"].get("convention") for p in res.prices}
        rs = _resource(res.budget)
        row = {"n": n, "status": res.status, "chosen": res.plan["chosen"], "argmin": argmin,
               "eligible_remaining_costs": elig,
               "ineligible": {p["name"]: p["ineligible_reason"][:80] for p in res.prices if not p["eligible"]},
               "convention": sorted(c for c in conv if c), "complete_cost": res.plan.get("complete_cost"),
               "truth": _contains(res.intervals, pt), "width": str(_width(res.intervals)),
               "resources": rs, "seconds": round(el, 2)}
        ok = ok and res.status.startswith("CERTIFIED") and res.plan["chosen"] == argmin \
            and row["truth"] and Fr(row["width"]) <= EPS and rs["ok"] and len(row["convention"]) == 1 \
            and res.plan.get("complete_cost") is not None
        out.append(row)
    return {"runs": out, "ok": ok}


CONTROLS = [
    ("F1 identity program replay", control_identity_replay),
    ("F2 compact two-scale replay, unique identities, altered witness", control_regional_two_scales_replay),
    ("F3 compact structural refusal without expansion", control_compact_structural_refusal),
    ("F4 independent representation and readout (four faults)", control_independent_representation_and_readout),
    ("F5 portfolio menu, pure-sign modes, coarse Q, identity", control_portfolio_menu_and_identity),
    ("F6 mixed Gaussian/Fourier under the shared budget", control_mixed_under_shared_budget),
    ("F7 prices cover counted work, entries, liveness; saved order", control_price_covers_counted_work),
    ("F8 public selection argmin and complete cost", control_public_selection),
]


def run_matrix(out_path, wall=600.0, only=None):
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "tests"))
    import signal
    rows = []
    for name, fn in CONTROLS:
        if only and not any(k in name for k in only):
            continue
        t = time.time()
        print("[matrix] %s ..." % name, flush=True)

        def _alarm(signum, frame):
            raise TimeoutError("control exceeded its %ds wall" % int(wall))
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(int(wall))
        try:
            res = fn(wall)
            if res.get("ok") is None:
                status = "SKIP"
            elif res.get("ok") and res.get("blocked"):
                status = "BLOCKED"
            elif res.get("ok"):
                status = "PASS"
            else:
                status = "FAIL"
        except TimeoutError as e:
            res = {"ok": False, "timeout": str(e)}
            status = "TIMEOUT"
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                   "traceback": traceback.format_exc()[-1500:]}
            status = "ERROR"
        finally:
            signal.alarm(0)
        el = time.time() - t
        print("[matrix] %-66s %-7s %.1fs" % (name, status, el), flush=True)
        rows.append({"control": name, "status": status, "seconds": round(el, 1),
                     "result": json.loads(json.dumps(res, default=str))})
    summary = {"controls": rows,
               "passed": sum(1 for r in rows if r["status"] == "PASS"),
               "blocked": sum(1 for r in rows if r["status"] == "BLOCKED"),
               "failed": sum(1 for r in rows if r["status"] in ("FAIL", "ERROR", "TIMEOUT")),
               "skipped": sum(1 for r in rows if r["status"] == "SKIP"),
               "per_control_wall_s": wall, "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "note": "BLOCKED rows hold on every predicate they state but name a branch the shared "
                       "budget refuses; they are not passes and the preflight is not returned while any exists"}
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "route_matrix.json"
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    only = sys.argv[3:] or None
    s = run_matrix(out, wall, only)
    print(json.dumps({k: v for k, v in s.items() if k != "controls"}))
    sys.exit(0 if s["failed"] == 0 else 1)
