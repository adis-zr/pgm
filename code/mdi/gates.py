"""Gate A / Gate B acceptance (overseer handoff, 30 October 2026).

One short acceptance table. Every row runs through `pipeline.solve` and
`mdi.replay`; a successful row requires exact query/state coverage, exact
original truth on the bounded fixture, the width recomputed from the
endpoints, no resource violation; every injected refusal must carry its named
reason; a BLOCKED or SKIP row does not satisfy acceptance. One aggregate
control under the usual resources.

    python -m mdi.gates OUT.json [per_control_wall_s]
"""
from __future__ import annotations
import sys, os, json, time, copy, tempfile, subprocess, math
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from mdi.matrix import (_pair, _write_uai, _contains, _contains_rep, _keys_rep, _width, _resource,   # noqa: E402
                        _row_ok, _solve, _plan, _price, _replay_fresh, _replay_here, _offering,
                        _measure_ops, _chain3, _f3_bipartite, _two_equal_blocks, _mean_field_path, EPS)


def _reprice_coherent(bad, m, kind):
    """Give an altered record COHERENT outer counters and a re-derived identity,
    so only the independent proof can refuse it."""
    from mdi import pipeline as PLN, plantype as PT, preprocess as PRE, model as M, config as K
    rec = PT.PlanRecord.from_json(json.dumps(bad))
    r0 = M.restrict(m, {})
    simp = PRE.simplify(r0)
    r = M.Restricted(model=m, evidence={}, factors=simp.factors, free=list(simp.free), card=dict(simp.card),
                     constant=r0.constant, impossible_factor=None)
    price = PLN._reprice_loaded(rec, r, set(rec.parsed_program["queries"]), sum(r.card[v] for v in r.free), simp, 1 << 30)
    bad["cost_counters"] = {k: c.as_dict() for k, c in price.counters.items()}
    mh, eh, qh = PLN.model_hashes(m, {}, set(rec.parsed_program["queries"]))
    bad["storage_schedule"]["identity"] = PLN.executable_identity(kind, bad["program"], request=(mh, eh, qh, K.MAX_WIDTH))
    return bad


# ------------------------------------------------------------ GATE B rows

def gate_b_grids(wall):
    """B1: GF1/GF2 admissibility and GF3 transfer verified independently from the
    loaded grid and the original observable range; node and frequency counts
    derived and charged before price; clean 15/25/13 with 5 retained and six
    exact probabilities within 0.01; a producer TAIL fault with coherent outer
    counters is refused by the independent proof on the same saved file; the
    negative error, false signed count and inconsistent terminal index are
    rejected at load."""
    from mdi import model as M, oracle as O, pipeline as PLN
    m = _chain3()
    mp = _write_uai(m)
    res, d, _, _ = _solve(M.read_uai(mp), wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    plan = _plan(res, d, "mixed:lowrank_combined")
    rep = _replay_fresh(mp, plan, wall)
    row = _row_ok(rep, pt, q)
    ex = rep.get("executor") or {}
    ck = (rep.get("checker") or {}).get("collective") or {}
    prog = json.load(open(plan))["program"]["collective"]
    cnt = _price(res, "mixed:lowrank_combined")["counters"]
    row.update({"positive_nodes": ex.get("positive_nodes"), "processed": ex.get("processed_positive_nodes"),
                "omitted": ex.get("omitted_positive_nodes"), "pairs": ex.get("conjugate_pairs"),
                "checker_processed": ck.get("processed"), "six_rows": sum(len(v) for v in rep["intervals"].values()),
                "grid_construction_charged_before_price": (cnt.get("grid_construction_ops") or {}).get("value"),
                "nodes_from_loaded_grids": [g["nodes"] for g in prog["grids"]],
                "representatives": [g["representatives"] for g in prog["grids"]]})
    ok = (row["ok"] and str(row["positive_nodes"]) == "15" and str(row["pairs"]) == "13" and str(row["processed"]) == "5"
          and ck.get("processed") == 5 and row["six_rows"] == 6 and sorted(row["nodes_from_loaded_grids"]) == [15, 25])
    base = json.load(open(plan))
    out = {"clean": row}
    # producer tail fault with coherent outer counters
    bad = copy.deepcopy(base)
    gneg = next(g for g in bad["program"]["collective"]["grids"] if g["sign"] < 0)
    J2 = gneg["J"] - 1
    gneg.update(J=J2, nodes=2 * J2 + 1, signed_frequencies=2 * J2 + 1, representatives=J2 + 1)
    bad = _reprice_coherent(bad, M.read_uai(mp), "mixed")
    p2 = os.path.join(d, "tailfault.plan.json")
    json.dump(bad, open(p2, "w"))
    r2 = _replay_fresh(mp, p2, wall)
    txt = str(r2.get("reason")) + " ".join(r2.get("failures") or [])
    out["tail_fault_coherent_counters"] = {"status": r2["status"], "reason": txt[:200],
                                          "ok": r2["status"] == "REPLAY_REJECTED" and "reach" in txt}
    ok = ok and out["tail_fault_coherent_counters"]["ok"]
    # load-time rejections
    loads = {}
    for label, mut in (("negative_error", lambda g: g.update(error="-1/1000", tol="-1/1000")),
                       ("false_signed_count", lambda g: g.update(signed_frequencies=g["signed_frequencies"] + 2)),
                       ("inconsistent_terminal_index", lambda g: g.update(J=g["J"] + 1))):
        b = copy.deepcopy(base)
        mut(next(g for g in b["program"]["collective"]["grids"] if g["sign"] < 0))
        p3 = os.path.join(d, label + ".plan.json")
        json.dump(b, open(p3, "w"))
        r3 = _replay_fresh(mp, p3, wall)
        loads[label] = {"status": r3["status"], "reason": str(r3.get("reason"))[:160],
                        "ok": r3["status"] == "REPLAY_REFUSED" and "invalid proof record" in str(r3.get("reason"))}
        ok = ok and loads[label]["ok"]
    out["load_rejections"] = loads
    # the verifier/ records
    vdir = os.path.join(HERE, "verifier")
    vrows = {}
    if os.path.isdir(vdir):
        man = json.load(open(os.path.join(vdir, "MANIFEST.json")))
        for fn, info in man["records"].items():
            mpv = os.path.join(vdir, info["model"])
            tr = json.load(open(os.path.join(vdir, info["model"].replace(".uai", "_truth.json"))))
            ptv = {int(v): [Fr(x) for x in row] for v, row in tr.items()}
            rv = _replay_fresh(mpv, os.path.join(vdir, fn), wall)
            if "fault" in info:
                txt = str(rv.get("reason")) + " ".join(rv.get("failures") or [])
                vrows[fn] = {"status": rv["status"], "reason": txt[:160],
                             "ok": rv["status"] == "REPLAY_REJECTED" and "reach" in txt}
            else:
                rr = _row_ok(rv, ptv, sorted(ptv))
                rr["ok"] = rr["ok"] if info.get("eligible", True) else (rv["status"] == "REPLAY_REFUSED")
                vrows[fn] = rr
            ok = ok and vrows[fn]["ok"]
    out["verifier_records"] = vrows
    out["ok"] = bool(ok)
    return out


def gate_b_observable_and_ledger(wall):
    """B2: the checker's immutable original observable is snapshotted before
    residual construction; the in-place and output-only marker-label faults
    are caught; exact applicable component keys, unused zero, identity's zero
    transformation allowance and the combined fit+rounding cap are enforced;
    a real undercharge is a named typed refusal without a traceback; an honest
    conservative allowance verifies."""
    from mdi import model as M, oracle as O, collective_route as CR, pipeline as PLN
    out = {}
    oks = []
    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, _, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    q4 = sorted(M.restrict(m4, {}).free)
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])
    plan4 = _plan(res4, d4, stat)
    clean = _replay_here(mp4, plan4)
    out["clean"] = _row_ok(clean, pt4, q4)
    oks.append(out["clean"]["ok"])
    orig = CR._residual_marked

    def output_only(marked, res, can, kept):
        rmk = orig(marked, res, can, kept)
        vs = sorted(rmk.queries())
        rmk.owner[vs[0]], rmk.owner[vs[1]] = rmk.owner[vs[1]], rmk.owner[vs[0]]
        return rmk

    def in_place(marked, res, can, kept):
        vs = sorted(marked.queries())
        a, b = vs[0], vs[1]
        # mutate the CHECKER's verified model in place, then build from it
        marked.marks[(a, 0)], marked.marks[(a, 1)] = marked.marks[(a, 1)], marked.marks[(a, 0)]
        return orig(marked, res, can, kept)
    for label, fn in (("output_only_label_fault", output_only), ("in_place_label_fault", in_place)):
        CR._residual_marked = fn
        try:
            bad = _replay_here(mp4, plan4)
        finally:
            CR._residual_marked = orig
        txt = str(bad.get("reason")) + " ".join(bad.get("failures") or [])
        out[label] = {"status": bad["status"], "reason": txt[:160],
                      "ok": bad["status"] == "REPLAY_REJECTED" and "residual binding" in txt}
        oks.append(out[label]["ok"])
    base = json.load(open(plan4))
    muts = {}
    b = copy.deepcopy(base); b["allocations"]["gaussian_quadrature"] = "1/100000"; muts["non_applicable_component_nonzero"] = (b, "proof budget")
    b = copy.deepcopy(base); b["allocations"]["extra_component"] = "0"; muts["foreign_component_key"] = (b, "proof budget")
    b = copy.deepcopy(base); b["allocations"]["collective_rounding"] = str(Fr(5, 10000)); b["program"]["collective"]["rounding_tv"] = str(Fr(5, 10000)); muts["combined_fit_rounding_above_cap"] = (b, "proof budget")
    b = copy.deepcopy(base); b["allocations"]["collective_fit"] = str(Fr(b["allocations"]["collective_fit"]) / 10 ** 6); b["program"]["collective"]["fit_tv"] = b["allocations"]["collective_fit"]; muts["real_undercharge"] = (b, "")
    b = copy.deepcopy(base); b["allocations"]["collective_fit"] = str(Fr(b["allocations"]["collective_fit"]) * 2); b["program"]["collective"]["fit_tv"] = b["allocations"]["collective_fit"]; muts["honest_conservative_allowance"] = (b, "VERIFIED")
    for label, (bad, want) in muts.items():
        if label in ("combined_fit_rounding_above_cap", "honest_conservative_allowance"):
            # these change the program's radii: make the outer counters and the
            # identity coherent so the record BINDS and the ledger rule decides
            bad = _reprice_coherent(bad, m4, "statistic")
        p2 = os.path.join(d4, label + ".plan.json")
        json.dump(bad, open(p2, "w"))
        r2 = _replay_fresh(mp4, p2, wall)
        txt = str(r2.get("reason")) + " ".join(r2.get("failures") or [])
        if want == "VERIFIED":
            rr = _row_ok(r2, pt4, q4)
            rr["note"] = "a conservative saved allowance above the verified component is valid"
            out[label] = rr
        else:
            typed = r2["status"] in ("REPLAY_REJECTED", "REPLAY_REFUSED") and "Traceback" not in txt
            named = ((want in txt) or ("saved allocations" in txt and "radii" in txt)) if want else (
                "below the checker's verified" in txt or "does not re-derive" in txt or "exceeds the recorded" in txt)
            out[label] = {"status": r2["status"], "reason": txt[:160], "typed_without_traceback": typed, "named": named,
                          "ok": typed and named}
        oks.append(out[label]["ok"])
    # identity's zero transformation allowance
    from tests.test_mdi_research import TINY, w
    mpt = w(TINY)
    rt, dt, _, _ = _solve(M.read_uai(mpt), wall)
    bi = json.load(open(_plan(rt, dt, "identity")))
    bi["allocations"]["transformation"] = "1/1000000"
    p3 = os.path.join(dt, "identity_alloc.plan.json")
    json.dump(bi, open(p3, "w"))
    ri = _replay_fresh(mpt, p3, wall)
    txt = str(ri.get("reason"))
    out["identity_nonzero_transformation"] = {"status": ri["status"], "reason": txt[:160],
                                              "ok": ri["status"] in ("REPLAY_REFUSED", "REPLAY_REJECTED")
                                                    and ("proof budget" in txt or "identity" in txt or "allocation" in txt)}
    oks.append(out["identity_nonzero_transformation"]["ok"])
    out["ok"] = all(oks)
    return out


def gate_b_terminals(wall):
    """B3: positive / zero-evidence terminals (pipeline, fully pinned, nested
    identity executor, arm driver) pass through the original-model proof;
    request width, queries and observations are bound; serialized keys and
    intervals validated and the width recomputed; observed point masses
    preserved on replay; the stock 0.005 / 0.01 mixed request; caps and
    precision validated; charging from parsing to the durable write."""
    from mdi import model as M, oracle as O, pipeline as PLN, solve as S, arm as ARM, replay as RP
    out = {}
    oks = []
    z = M.Model(nvars=2, card=[2, 2], factors=[
        M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=0),
        M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=1)]).validate()
    rz = PLN.solve(z, {0: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    sz = S.solve(z, {0: 1}, eps=EPS, mode="P", cap_bytes=1 << 30, deadline_s=30, run_checker=False)
    fake = PLN.zero_evidence_proof(z, {}, M.restrict(z, {}), named=1)
    out["zero_evidence"] = {"pipeline": rz.status, "pipeline_witness": (rz.checker or {}).get("witness_factor"),
                           "nested_identity_executor": sz["outcome"], "nested_witness": (sz.get("checker") or {}).get("witness_factor"),
                           "false_claim_proved": fake.get("proved"),
                           "ok": rz.status == "ZERO_EVIDENCE_PROVED" and sz["outcome"] == "ZERO_EVIDENCE_PROVED"
                                 and (rz.checker or {}).get("witness_factor") == 0 and fake.get("proved") is False}
    oks.append(out["zero_evidence"]["ok"])
    # the real arm driver's terminal on a zero-evidence input (local model, no external input)
    mpz = _write_uai(z)
    evz = mpz + ".evid"
    open(evz, "w").write("1 0 1\n")
    rd = tempfile.mkdtemp()
    arm_rec = ARM.run_arm("zero", False, rd, wall=30, model_path=mpz, evid_path=evz) if "model_path" in ARM.run_arm.__code__.co_varnames else None
    out["arm_driver_terminal"] = ({"outcome": arm_rec["outcome"], "witness": (arm_rec.get("checker") or {}).get("witness_factor"),
                                   "ok": arm_rec["outcome"] == "ZERO_EVIDENCE_PROVED" and (arm_rec.get("checker") or {}).get("witness_factor") == 0}
                                  if arm_rec else {"ok": False, "reason": "arm driver has no local-model entry"})
    oks.append(out["arm_driver_terminal"]["ok"])
    mc = M.read_uai(_mean_field_path(4, 0.30))
    rp = PLN.solve(mc, {0: 0, 1: 1, 2: 0, 3: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    out["fully_pinned"] = {"status": rp.status, "method": (rp.checker or {}).get("method", "")[:80],
                           "keys": sorted(rp.intervals), "ok": rp.status == "CERTIFIED_FALLBACK_ONLY"
                           and "original factors" in (rp.checker or {}).get("method", "") and sorted(rp.intervals) == [0, 1, 2, 3]}
    oks.append(out["fully_pinned"]["ok"])
    # observed point masses preserved on replay; request bound
    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {1: 1}))
    d4 = tempfile.mkdtemp()
    r4 = PLN.solve(m4, {1: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=d4)
    evp = mp4 + ".e1"
    open(evp, "w").write("1 1 1\n")
    ident = next(p["identity"] for p in r4.prices if p["name"] == r4.plan["chosen"])
    rep = RP.replay(mp4, evp, os.path.join(d4, ident + ".plan.json"))
    rowr = _row_ok(rep, {**pt4, 1: [Fr(0), Fr(1)]}, [0, 1, 2, 3], need_ledger=(r4.plan["chosen"] != "identity"))
    rowr["observed_row"] = rep["intervals"].get("1")
    rowr["request_width"] = rep.get("request_width")
    rowr["ok"] = (rep["status"] == "REPLAY_VERIFIED" and rep["intervals"].get("1") == [["0", "0"], ["1", "1"]]
                  and sorted(int(k) for k in rep["intervals"]) == [0, 1, 2, 3] and rowr["width_ok"] and rowr["resources"]["ok"])
    other = RP.replay(mp4, evp, os.path.join(d4, ident + ".plan.json"), eps="1/200")
    rowr["other_width_refused"] = other["status"] == "REPLAY_REFUSED"
    rowr["ok"] = rowr["ok"] and rowr["other_width_refused"]
    out["observed_point_masses_and_request_binding"] = rowr
    oks.append(rowr["ok"])
    # stock 0.005 / 0.01 mixed request on the chain
    mch = _chain3()
    mpc = _write_uai(mch)
    Z, ptc = O.exact_all_marginals(M.restrict(mch, {}))
    qc = sorted(M.restrict(mch, {}).free)
    stock = {}
    for eps in (Fr(1, 100), Fr(1, 200)):
        dd = tempfile.mkdtemp()
        rr = PLN.solve(M.read_uai(mpc), {}, max_width=eps, wall_s=wall, cap_bytes=1 << 30, plan_dir=dd)
        mixed = next((p for p in rr.prices if p["name"] == "mixed:lowrank_combined"), None)
        row = {"status": rr.status, "chosen": rr.plan.get("chosen"), "truth": _contains(rr.intervals, ptc),
               "width": str(_width(rr.intervals)), "width_ok": _width(rr.intervals) <= eps, "resources": _resource(rr.budget)}
        if mixed:
            repm = _replay_fresh(mpc, os.path.join(dd, mixed["identity"] + ".plan.json"), wall, eps=eps)
            rm = _row_ok(repm, ptc, qc)
            rm["width_ok"] = bool(repm.get("max_width")) and Fr(repm["max_width"]) <= eps
            rm["ok"] = rm["ok"] and rm["width_ok"]
            row["mixed_replay"] = rm
            row["ok"] = rr.status.startswith("CERTIFIED") and row["truth"] and row["width_ok"] and row["resources"]["ok"] and rm["ok"]
        else:
            row["ok"] = False
        stock[str(eps)] = row
        oks.append(row["ok"])
    out["stock_mixed_request"] = stock
    out["ok"] = all(oks)
    return out


def gate_b_costs(wall):
    """B4: every MPFR call counted in both engines (forecast >= measured, per
    engine); partial entry batches flushed (metered entries measured >= 1 on a
    tiny statistic program); support probes, construction and repricing
    charged; the 12-variable statistic price regression, the small Gaussian
    storage control and clean F6 coverage rows; missing measurements stay
    unknown; whole-tree figure from the supervisor; F3 keeps a feasible
    fallback after the 30 s construction allowance."""
    from mdi import model as M, oracle as O
    from mdi.matrix import control_work_and_memory
    out = {"coverage": control_work_and_memory(wall)}
    oks = [out["coverage"]["ok"]]
    # partial batch flush: a tiny program's metered entries are no longer zero
    rows = out["coverage"]["rows"]
    tiny = next((r for r in rows if "statistic (default order)" in r.get("control", "")), None)
    out["partial_batches_flushed"] = {"metered_entries_measured": (tiny or {}).get("measured", {}).get("metered_entries"),
                                      "ok": bool(tiny) and int((tiny["measured"].get("metered_entries") or 0)) > 0}
    oks.append(out["partial_batches_flushed"]["ok"])
    # the 12-variable statistic price regression (ring composed statistic) is in the coverage rows
    out["twelve_variable_statistic_regression"] = {"present": any("composed statistic" in r.get("control", "") for r in rows),
                                                   "ok": any("composed statistic" in r.get("control", "") and r.get("ok") for r in rows)}
    oks.append(out["twelve_variable_statistic_regression"]["ok"])
    # F3 under the 30 s construction allowance keeps the identity fallback
    m3 = _f3_bipartite()
    Z, pt3 = O.exact_all_marginals(M.restrict(m3, {}))
    res3, d3, el3, _ = _solve(m3, wall)
    import collections
    typed = dict(collections.Counter(x.get("typed") for x in res3.rejected))
    out["f3_fallback_after_discovery_timeout"] = {
        "status": res3.status, "chosen": res3.plan.get("chosen"), "seconds": round(el3, 1),
        "discovery_complete": res3.plan.get("discovery_complete"), "typed_refusals": {str(k): v for k, v in typed.items()},
        "phase_used_s": res3.budget.get("phase_used_s"), "coordinates": sum(len(r) for r in res3.intervals.values()),
        "truth": _contains(res3.intervals, pt3), "width": str(_width(res3.intervals)),
        "ok": res3.status.startswith("CERTIFIED") and res3.plan.get("discovery_complete") is False
              and typed.get("PHASE_TIMEOUT", 0) >= 1 and _contains(res3.intervals, pt3) and _width(res3.intervals) <= EPS
              and (res3.budget.get("phase_used_s") or {}).get("construction", 0) <= 31.0}
    oks.append(out["f3_fallback_after_discovery_timeout"]["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------ GATE A rows

def gate_a_controls(wall):
    """A1: the planning stop and guard (no executor or checker entry, no
    interval published, explicit terminal); the 13-variable identity checker;
    the synthetic 30 s phase controls; the strict-mask forest controls with
    actual residual scopes and largest bag; feasibility quoted at the checking
    standard; a different executable never overwrites a completed program; the
    request identity is in the plan key; the GF grid regression."""
    from mdi import model as M, oracle as O, pipeline as PLN, guard as GD, planning as PLAN
    out = {}
    oks = []
    # planning stop on the 14-variable F3 model through the SUPERVISED driver (fresh child)
    m3 = _f3_bipartite()
    mp3 = _write_uai(m3)
    rd = tempfile.mkdtemp()
    term = PLAN.run_pass("f3_synthetic", True, rd, model_path=mp3, evid_path=None, wall=wall)
    out["planning_stop_supervised"] = {
        "status": term.get("status"), "chosen": (term.get("plan") or {}).get("chosen"),
        "guard_entries_touched": term.get("guard_entries_touched"), "intervals_published": "intervals" in term,
        "phases": (term.get("budget") or {}).get("phases"), "phase_used_s": (term.get("budget") or {}).get("phase_used_s"),
        "supervisor": term.get("supervisor"), "elapsed_s": term.get("elapsed_s"), "durable_write_s": term.get("durable_write_s"),
        "plan_files": len(term.get("plan_files") or []), "prestart_recorded": os.path.exists(os.path.join(rd, "prestart_f3_synthetic_research.json")),
        "progress_lines": sum(1 for _ in open(os.path.join(rd, "progress_f3_synthetic_research.jsonl"))) if os.path.exists(os.path.join(rd, "progress_f3_synthetic_research.jsonl")) else 0,
        "ok": term.get("status") in ("PLANNING_COMPLETE", "PLANNING_INCOMPLETE") and not term.get("guard_entries_touched")
              and "intervals" not in term
              and (((term.get("supervisor") or {}).get("peak_tree_rss_bytes") or 0) > 0
                   or (term.get("supervisor") or {}).get("peak_tree_rss") == "unavailable")
              and term.get("durable_write_s") is not None and (term.get("plan_files") or [])}
    oks.append(out["planning_stop_supervised"]["ok"])
    # guard control: a full run under the guard fails at the executor entry
    mp4 = _mean_field_path(4, 0.30)
    GD.install(True)
    try:
        rg = PLN.solve(M.read_uai(mp4), {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        GD.install(False)
    out["guard_control"] = {"status": rg.status, "reason": rg.reason[:120], "entries": list(GD.ENTRIES)[:3],
                            "ok": rg.status == "GUARD_VIOLATION" and "executor" in rg.reason}
    oks.append(out["guard_control"]["ok"])
    # 13-variable identity checker
    n = 13
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 5, 10)], origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + i % 3)], origin=100 + i) for i in range(n - 1)]
    m13 = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    Z, pt13 = O.exact_all_marginals(M.restrict(m13, {}))
    r13 = PLN.solve(m13, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    out["identity_checker_13"] = {"status": r13.status, "coordinates_checked": r13.checker.get("coordinates_checked"),
                                  "truth": _contains(r13.intervals, pt13), "width": str(_width(r13.intervals)),
                                  "resources": _resource(r13.budget),
                                  "ok": r13.status.startswith("CERTIFIED") and r13.checker.get("coordinates_checked") == 26
                                        and _contains(r13.intervals, pt13) and _width(r13.intervals) <= EPS and _resource(r13.budget)["ok"]}
    oks.append(out["identity_checker_13"]["ok"])
    # synthetic 30 s phase control: F3 full run (discovery times out, fallback certifies)
    Z, pt3 = O.exact_all_marginals(M.restrict(m3, {}))
    r3, d3, el3, _ = _solve(m3, wall)
    out["synthetic_30s_phase_control"] = {"status": r3.status, "seconds": round(el3, 1), "discovery_complete": r3.plan.get("discovery_complete"),
                                         "phase_used_s": r3.budget.get("phase_used_s"), "stops": r3.budget.get("stops")[:1],
                                         "truth": _contains(r3.intervals, pt3),
                                         "ok": r3.status.startswith("CERTIFIED") and r3.plan.get("discovery_complete") is False
                                               and (r3.budget.get("phase_used_s") or {}).get("construction", 99) <= 31.0 and _contains(r3.intervals, pt3)}
    oks.append(out["synthetic_30s_phase_control"]["ok"])
    # strict mask forest controls
    from portfolio import strict_mask as SM
    sm = SM.run()
    strict_rows = [c for row in sm["rows"] for c in row.get("masked_candidates", []) if c["strict"]]
    out["strict_mask_controls"] = {"fixtures": len(sm["rows"]), "strict_candidates": len(strict_rows),
                                   "all_strict_residuals_equal_mask": all(c["residual_pairs_equal_mask"] for c in strict_rows),
                                   "largest_bags": sorted({c["largest_residual_bag_entries"] for c in strict_rows}),
                                   "declines": [d for row in sm["rows"] for d in row.get("strict_declines", []) if "fit budget" in d][:3],
                                   "ok": bool(strict_rows) and all(c["residual_pairs_equal_mask"] for c in strict_rows)}
    oks.append(out["strict_mask_controls"]["ok"])
    # feasibility quoted per engine on F3's refused candidates
    feas = {p["name"]: p.get("feasibility") for p in r3.prices}
    out["feasibility_quoted"] = {"sample": dict(list(feas.items())[:4]),
                                 "has_cap_proved_or_unknown": any(v and (v.get("checker", "").endswith("PROVED") or v.get("checker", "").endswith("UNKNOWN")
                                                                         or v.get("producer", "").endswith("PROVED") or v.get("producer", "").endswith("UNKNOWN")) for v in feas.values()),
                                 "ok": all(v is not None for v in feas.values())}
    oks.append(out["feasibility_quoted"]["ok"])
    # no overwrite of a completed program by a different executable
    res4, d4, _, _ = _solve(M.read_uai(mp4), wall)
    ident = next(p["identity"] for p in res4.prices if p["name"] == res4.plan["chosen"])
    path = os.path.join(d4, ident + ".plan.json")
    with open(path, "a") as fh:
        fh.write("\n")
    res4b = PLN.solve(M.read_uai(mp4), {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=d4)
    hit = [x for x in res4b.rejected if "never overwrites" in x["reason"]]
    out["no_overwrite"] = {"rejected": [x["name"] for x in hit][:3], "ok": bool(hit) and res4b.status.startswith("CERTIFIED")}
    oks.append(out["no_overwrite"]["ok"])
    out["request_identity_in_key"] = {"example": ident, "ok": "-req" in ident}
    oks.append(out["request_identity_in_key"]["ok"])
    from benchmark import gf_grid_regression as GR
    gr = GR.run()
    out["gf_grid_regression"] = {k: v.get("ok") if isinstance(v, dict) else v for k, v in gr.items()}
    oks.append(bool(gr["ok"]))
    out["ok"] = all(oks)
    return out


CONTROLS = [
    ("A1 planning stop, guard, 13-var identity checker, 30 s phases, strict masks, feasibility", gate_a_controls),
    ("B1 GF1/GF2/GF3 independent admissibility, tail fault, load rejections, verifier records", gate_b_grids),
    ("B2 immutable observable, label faults, ledger exactness, typed undercharge", gate_b_observable_and_ledger),
    ("B3 terminals through the original-model proof, request binding, stock 0.005/0.01", gate_b_terminals),
    ("B4 costs reconciled, batches flushed, missing stays unknown, F3 fallback", gate_b_costs),
]


def run_gates(out_path, wall=600.0, only=None):
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "tests"))
    import signal, traceback
    rows = []
    for name, fn in CONTROLS:
        if only and not any(k in name for k in only):
            continue
        t = time.time()
        print("[gates] %s ..." % name, flush=True)

        def _alarm(signum, frame):
            raise TimeoutError("control exceeded its %ds wall" % int(wall))
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(int(wall))
        try:
            res = fn(wall)
            status = "PASS" if res.get("ok") else "FAIL"
        except TimeoutError as e:
            res = {"ok": False, "timeout": str(e)}
            status = "TIMEOUT"
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "traceback": traceback.format_exc()[-1500:]}
            status = "ERROR"
        finally:
            signal.alarm(0)
        el = time.time() - t
        print("[gates] %-84s %-7s %.1fs" % (name, status, el), flush=True)
        rows.append({"control": name, "status": status, "seconds": round(el, 1), "result": json.loads(json.dumps(res, default=str))})
    summary = {"controls": rows, "passed": sum(1 for r in rows if r["status"] == "PASS"),
               "failed": sum(1 for r in rows if r["status"] != "PASS"), "per_control_wall_s": wall,
               "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "acceptance": "exact query/state coverage, exact original truth, width recomputed from endpoints, no "
                             "resource violation for successes, named reason for each injected refusal; BLOCKED/SKIP never satisfy"}
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "gate_matrix.json"
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    s = run_gates(out, wall, only=(sys.argv[3:] or None))
    print(json.dumps({k: v for k, v in s.items() if k != "controls"}))
    sys.exit(0 if s["failed"] == 0 else 1)
