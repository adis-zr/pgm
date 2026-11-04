"""Controls of the SELECTOR (generalization experiment, implementation pass of 3-4 November 2026;
GENERALIZATION_DESIGN.md SS1/SS3/SS8/SS9 as corrected by the overseer's review): the one selection
policy over dense identity / compiled support / constraint quotient, its explicit probe window, the
charged fallbacks, the preserved dense candidate, the late-refusal transitions, the natural rejection
control, the contradiction transition, the fresh-replay accounting, the selector arm through the
public launcher on a toy packet, and the panel-driven scorer. Tiny synthetic instances only; no
external input is read."""
import os, sys, json, tempfile, glob, zipfile, hashlib, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
import pytest
from mdi import (model as M, plan as P, pipeline as PLN, oracle as O, budget as B, quotient as QT, support as SP,
                 quotient_check as QC, replay as RP, launch as L, arm as ARM)
import mdi.registry  # noqa: F401
from test_mdi_quotient_pilot import _chain_model, _eq, _ne, _restricted
from test_mdi_support_pilot import _perm_chain, _band_chain
from mdi.matrix import _write_uai


def _run(m, ev, **kw):
    kw.setdefault("wall_s", 120)
    kw.setdefault("plan_dir", tempfile.mkdtemp())
    return PLN.solve(m, ev, cap_bytes=1 << 30, research_enabled=False, route_policy="selector", **kw)


def _contained(res, m, ev):
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    # every ORIGINAL variable is published (observed ones as point masses); every unobserved coordinate contains the exact value
    return (set(res.intervals) == set(range(m.nvars)) and set(pt) <= set(res.intervals) and
            all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(len(pt[v]))))


def _att(res, mech):
    return [a for a in res.plan["selector"]["attempts"] if a["mechanism"] == mech]


def _src(res, key):
    return sum(v for k, v in res.budget["used_by_source"].items() if key in k)


_POS = M.Model(nvars=5, card=[2] * 5, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(4)]).validate()
_NAT = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(1), Fr(1), Fr(0)], origin=0)]).validate()


# ---------------------------------------------------------------- 1 / 7: support selected, evidence, truth on every coordinate
def test_successful_support_selection_runs_the_sparse_layout_with_the_dense_candidate_preserved():
    m = _band_chain(7, k=8, band=2, seed=31)
    ev = {3: 1}
    res = _run(m, ev)
    assert res.status == "CERTIFIED_FALLBACK_ONLY", (res.status, res.reason)
    blk = res.plan["selector"]
    assert blk["gate"]["verdict"] == "probe" and blk["gate"]["zero_entries"] > 0
    assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "NOT_ADMITTED"), ("support", "ADMITTED")]
    assert blk["recommended"] == "support" == blk["executed_route"] and blk["agreement"] is True and blk["late_refusal"] is None
    assert res.plan["executed"]["layout"] == "sparse-support" and res.plan["chosen"] == "identity"
    assert sorted(p["name"] for p in res.prices) == ["identity", "identity:dense"]        # the dense candidate PRESERVED and bound
    assert blk["transformed_record"] and blk["dense_record"] and blk["transformed_record"] != blk["dense_record"]
    assert all(a["charged_entries"] > 0 and a["wall_s"] >= 0 for a in blk["attempts"])      # every probe charged and timed
    assert _src(res, "quotient recognition") > 0 and _src(res, "support compilation") > 0 and _src(res, "selector gate") > 0
    assert _contained(res, m, ev)
    assert res.checker["support_reconstructed"]["declared_matches"] is True


# ---------------------------------------------------------------- 2 / 7: quotient selected; every original row restored (mixed cardinalities, evidence)
def test_successful_quotient_selection_restores_every_original_row_under_evidence_and_mixed_cardinalities():
    m = _chain_model(11)
    for ev in ({}, {3: 1}, {6: 2}):
        res = _run(m, ev)
        assert res.status == "CERTIFIED_FALLBACK_ONLY", (ev, res.status, res.reason)
        blk = res.plan["selector"]
        assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "ADMITTED")]     # support never probed
        assert blk["executed_route"] == "quotient" and blk["agreement"] is True
        assert res.plan["executed"]["quotient"]["fixed"] + res.plan["executed"]["quotient"]["merged"] == blk["attempts"][0]["eliminated"]["fixed"] + blk["attempts"][0]["eliminated"]["merged"]
        assert res.checker["quotient_rederived"]["declared_matches"] is True and res.checker["quotient_rederived"]["restoration_checked_rows"] > 0
        assert set(res.intervals) == set(range(m.nvars)) and all(len(res.intervals[v]) == m.card[v] for v in range(m.nvars))
        assert res.checker["coordinates_checked"] == sum(m.card[v] for v in range(m.nvars))
        assert _contained(res, m, ev)
        assert sorted(p["name"] for p in res.prices) == ["identity", "identity:dense"]


# ---------------------------------------------------------------- 3: strictly positive -> gate bypass, dense, nothing compiled
def test_strictly_positive_law_bypasses_both_mechanisms_after_one_charged_scan():
    res = _run(_POS, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, _POS, {})
    blk = res.plan["selector"]
    assert blk["gate"] == {"zero_entries": 0, "table_entries": sum(f.size() for f in _restricted(_POS, {}).factors), "verdict": "bypass"}
    assert blk["attempts"] == [] and blk["skipped"].startswith("gate:") and blk["executed_route"] == "dense"
    assert [p["name"] for p in res.prices] == ["identity"]
    assert _src(res, "selector gate") == blk["gate"]["table_entries"] and _src(res, "quotient recognition") == 0 and _src(res, "support compilation") == 0
    assert any(x.get("typed") == "SELECTOR_SKIPPED" for x in res.rejected)


# ---------------------------------------------------------------- 4: caps, the probe window, and the terminal kinds that stay terminal
def test_cap_refusal_and_window_exhaustion_are_charged_fallbacks_while_wall_stops_stay_terminal(monkeypatch):
    m = _chain_model(11)
    # (a) the recognizer's wall cap -> typed REFUSAL, charged (its first factor scan precedes the cap test), support probed next, dense certified
    monkeypatch.setattr(QT, "QUOTIENT_WALL_CAP_S", 0.0)
    res = _run(m, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    q = _att(res, "quotient")[0]
    assert q["verdict"] == "REFUSAL" and q["charged_entries"] > 0 and "cap" in q["detail"]
    assert _att(res, "support")[0]["verdict"] == "NOT_ADMITTED" and res.plan["selector"]["executed_route"] == "dense"
    assert any(x.get("typed") == "QUOTIENT_REFUSAL" for x in res.rejected)
    monkeypatch.undo()
    # (b) the probe window spent inside the first probe: both probes PROBE_EXHAUSTED, every charge kept, dense certified
    monkeypatch.setattr(PLN, "SELECTOR_PROBE_WINDOW_S", 1e-4)
    res = _run(m, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    assert [a["verdict"] for a in res.plan["selector"]["attempts"]] == ["PROBE_EXHAUSTED", "PROBE_EXHAUSTED"]
    assert _att(res, "quotient")[0]["charged_entries"] > 0
    assert sum(1 for x in res.rejected if x.get("typed") == "SELECTOR_PROBE_EXHAUSTED") == 2
    assert [p["name"] for p in res.prices] == ["identity"]
    monkeypatch.undo()
    # (c) a wall / counter stop raised inside a probe is the invocation's TERMINAL, with the attempt block carried
    def wall_stop(*a, **k):
        raise B.BudgetExceeded("wall", 1.0, 0.5, "injected inside the recognizer")
    monkeypatch.setattr(QT, "recognize_cached", wall_stop)
    res = _run(m, {})
    assert res.status == "RESOURCE_STOP" and "selector's probes" in res.reason and not res.intervals
    assert res.plan["selector"]["gate"]["verdict"] == "probe"
    monkeypatch.undo()
    # (d) the probe view: a construction-allowance stop becomes ProbeExhausted, a wall stop propagates, charges land on the real budget
    bg = B.Budget(wall_s=100.0, phase_limits={"construction": 0.05, "check_local": 30.0})
    bg.enter("discover")
    pb = PLN._ProbeBudget(bg, time.monotonic() + 10, 10.0)
    time.sleep(0.06)
    with pytest.raises(PLN.ProbeExhausted):
        pb.deadline_fn("x")()
    pb.charge("pricing_entries", 7, "probe")
    assert bg.used["pricing_entries"] == 7
    bg2 = B.Budget(wall_s=1e-9)
    with pytest.raises(B.BudgetExceeded):
        PLN._ProbeBudget(bg2, time.monotonic() + 10, 10.0).deadline_fn("x")()
    # (e) the planner and both quotient constructions poll their deadline and never swallow it
    r = _restricted(m, {})
    def dl():
        raise B.BudgetExceeded("wall", 2, 1, "planner")
    with pytest.raises(B.BudgetExceeded):
        P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30, deadline=dl)
    decl = QT.recognize(r.factors, r.free, r.card)
    with pytest.raises(B.BudgetExceeded):
        QT.build_quotient(r, decl, deadline=dl)
    with pytest.raises(B.BudgetExceeded):
        QC.build_quotient(r, decl, deadline=dl)
    charged = []
    QT.build_quotient(r, decl, charge=charged.append)
    assert sum(charged) == sum(f.size() for f in QT.build_quotient(r, decl).factors)


# ---------------------------------------------------------------- 5: both applicable -> quotient, deterministically; support not probed
def test_both_applicable_selects_the_quotient_deterministically_and_never_probes_the_support():
    m = _perm_chain(10, k=3, seed=21)
    ev = {5: 1}
    r = _restricted(m, ev)
    pl = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)["chosen"][0]
    assert SP.support_price(pl, SP.compile_support(pl, r.factors, r.card))["admitted"], "the control's support must be admissible on its own"
    keys = []
    for _ in range(2):
        res = _run(m, ev)
        assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, ev)
        blk = res.plan["selector"]
        assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "ADMITTED")]
        assert blk["attempts"][0]["reduction_ratio"] >= QT.MIN_REDUCTION_RATIO and blk["executed_route"] == "quotient"
        assert _src(res, "support compilation") == 0
        keys.append((res.plan["identity"], blk["transformed_record"]))
    assert keys[0] == keys[1]


# ---------------------------------------------------------------- 6: corrupt transformations refused by the independent checker
def test_corrupt_transformations_through_the_selector_are_refused_and_nothing_is_published(monkeypatch):
    m = _chain_model(11)
    orig = QT.recognize

    def unimplied(factors, free, card, **kw):
        d = orig(factors, free, card, **kw)
        d["merged"]["7"] = [0, 0]                      # 7 is independent of 0: a relation the factors do not imply
        d["n_free"] -= 1
        d["digest"] = QT._digest({int(k): v for k, v in d["fixed"].items()}, {int(k): tuple(v) for k, v in d["merged"].items()})
        return d
    monkeypatch.setattr(QT, "recognize", unimplied)
    bad = _run(m, {})
    assert bad.status == "NUMERICAL_REFUSAL" and not bad.intervals, (bad.status, bad.reason)
    assert bad.plan["selector"]["executed_route"] == "quotient"            # admitted by the producer, refused by the checker
    monkeypatch.undo()
    m2 = _band_chain(7, k=8, band=2, seed=31)
    orig_c = SP.compile_support

    def dropping(plan, factors, card, **kw):
        sup = orig_c(plan, factors, card, **kw)
        b = max(sup.rows, key=lambda i: sup.rows[i].size)
        sup.rows[b] = sup.rows[b][1:]                  # one positive row omitted from the declaration
        return sup
    monkeypatch.setattr(SP, "compile_support", dropping)
    bad2 = _run(m2, {3: 1})
    assert bad2.status == "NUMERICAL_REFUSAL" and not bad2.intervals, (bad2.status, bad2.reason)
    monkeypatch.undo()
    assert _run(m2, {3: 1}).status == "CERTIFIED_FALLBACK_ONLY"


# ---------------------------------------------------------------- 8: fresh replay charges its own recognition; saved bounds cover it; attempts persisted by the arm
def test_fresh_replay_is_charged_its_own_recognition_within_the_saved_bounds_and_the_arm_persists_the_attempts():
    m = _chain_model(11)
    mp = _write_uai(m)
    ep = mp + ".evid"
    open(ep, "w").write("1 3 1\n")
    d = tempfile.mkdtemp()
    res = _run(M.read_uai(mp), {3: 1}, plan_dir=d)
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and res.plan["selector"]["executed_route"] == "quotient"
    plans = {json.load(open(p))["name"]: p for p in glob.glob(d + "/*.plan.json")}
    assert set(plans) == {"identity", "identity:dense"}
    assert json.load(open(plans["identity"]))["program"].get("quotient") and not json.load(open(plans["identity:dense"]))["program"].get("quotient")
    pr = next(p for p in res.prices if p["name"] == "identity")
    recog_pipeline = _src(res, "quotient recognition")
    assert recog_pipeline == res.plan["executed"]["quotient"]["recognition"]["entries_scanned"] > 0     # ONE recognition in the pipeline's invocation
    rr = RP.replay(mp, ep, plans["identity"])
    assert rr["status"] == "REPLAY_VERIFIED", rr.get("reason")
    recog_replay = sum(v for k, v in rr["budget"]["used_by_source"].items() if "quotient recognition" in k)
    # the replay is its own invocation: its binding re-derives the declared quotient afresh and is CHARGED for the full scan
    # (the executor then reuses that in-invocation result), and the saved scan bound covers it
    assert recog_replay == recog_pipeline > 0, (recog_replay, recog_pipeline)
    assert int(pr["counters"]["quotient_recognition_scan_bound"]["value"]) >= recog_replay
    assert int(pr["counters"]["producer_metered_entries"]["value"]) >= sum(v for k, v in rr["budget"]["used_by_source"].items() if "producer" in k)
    assert int(pr["counters"]["checker_metered_entries"]["value"]) >= sum(v for k, v in rr["budget"]["used_by_source"].items() if "checker" in k)
    assert RP.replay(mp, ep, plans["identity:dense"])["status"] == "REPLAY_VERIFIED"
    # the public arm persists the selector block (every attempt, wall, charge, verdict) in its durable record
    rd = tempfile.mkdtemp()
    rec = ARM.run_arm("tiny", False, rd, wall=60, model_path=mp, evid_path=ep, selector=True)
    assert rec["arm"] == "selector" and rec["outcome"] == "CERTIFIED_FALLBACK_ONLY"
    saved = json.load(open(os.path.join(rd, "arm_tiny_selector.json")))
    blk = saved["pipeline"]["plan"]["selector"]
    assert blk["attempts"] and all(set(a) >= {"mechanism", "verdict", "wall_s", "charged_entries", "detail"} for a in blk["attempts"])
    assert blk["executed_route"] == "quotient" and saved["pipeline"]["plan"]["route_policy"] == "selector"
    json.dumps(saved)


# ---------------------------------------------------------------- 9: insufficient remaining budget -> probes skipped and recorded
def test_insufficient_remaining_wall_or_construction_allowance_skips_the_probes_with_the_reason_recorded():
    m = _chain_model(11)
    res = _run(m, {}, wall_s=25)                     # < window 20 s + dense forecast + 30 s margin
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    blk = res.plan["selector"]
    assert blk["attempts"] == [] and blk["skipped"].startswith("insufficient remaining wall") and blk["executed_route"] == "dense"
    assert blk["precondition"]["remaining_wall_s"] < blk["precondition"]["needed_s"]
    assert _src(res, "quotient recognition") == 0 and _src(res, "support compilation") == 0
    assert any(x.get("typed") == "SELECTOR_SKIPPED" for x in res.rejected)
    res2 = _run(m, {}, phase_limits={"construction": 4.0, "check_local": 30.0})     # < the 5 s dense reserve
    assert res2.status == "CERTIFIED_FALLBACK_ONLY" and res2.plan["selector"]["skipped"].startswith("insufficient construction allowance")
    assert res2.plan["selector"]["window_s"] <= 0


# ---------------------------------------------------------------- 10: the natural rejection control [1, 1, 1, 0]
def test_natural_rejection_control_neither_transformation_qualifies_and_every_attempt_is_charged():
    res = _run(_NAT, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, _NAT, {})
    blk = res.plan["selector"]
    assert blk["gate"] == {"zero_entries": 1, "table_entries": sum(f.size() for f in _restricted(_NAT, {}).factors), "verdict": "probe"}
    assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "NOT_ADMITTED"), ("support", "NOT_ADMITTED")]
    assert all(a["charged_entries"] > 0 for a in blk["attempts"])
    assert blk["attempts"][1]["reduction_ratio"] < SP.MIN_REDUCTION_RATIO
    assert blk["executed_route"] == "dense" and blk["recommended"] == "dense" and res.plan["chosen"] == "identity"
    assert [p["name"] for p in res.prices] == ["identity"]
    assert blk["probes_charged_entries"] == sum(a["charged_entries"] for a in blk["attempts"]) > 0
    typed = [x.get("typed") for x in res.rejected]
    assert "QUOTIENT_NOT_ADMITTED" in typed and "SUPPORT_NOT_ADMITTED" in typed


# ---------------------------------------------------------------- 11: the contradiction transition (no new proof mechanism)
def test_quotient_contradiction_stops_probing_and_the_dense_zero_evidence_proof_decides():
    cases = [M.Model(nvars=3, card=[2, 2, 2], factors=[_eq(0, 1), _ne(0, 1), M.Factor(scope=(2,), card=(2,), table=[Fr(1), Fr(2)], origin=9)]).validate(),
             M.Model(nvars=3, card=[2, 2, 2], factors=[_ne(0, 1), _ne(1, 2), _ne(0, 2)]).validate()]
    for m in cases:
        res = _run(m, {})
        assert res.status in ("ZERO_EVIDENCE_PROVED", "ZERO_SUPPORT_UNCHECKED") and not res.intervals, (res.status, res.reason)
        blk = res.plan["selector"]
        assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "CONTRADICTION")]     # the support is never probed
        assert "NOT a certificate" in blk["attempts"][0]["detail"] and blk["attempts"][0]["charged_entries"] > 0
        assert blk["recommended"] == "dense" and blk["executed_route"] == "dense"
        assert any(x.get("typed") == "QUOTIENT_CONTRADICTION" for x in res.rejected)
        assert _src(res, "support compilation") == 0
        if res.status == "ZERO_EVIDENCE_PROVED":
            assert "INDEPENDENTLY verified" in res.reason


# ---------------------------------------------------------------- 12: the complete support attempt (both compilations) and the explicit late refusals
def test_support_attempt_compiles_both_orders_inside_the_window_and_late_refusals_are_explicit_transitions(monkeypatch):
    m = _perm_chain(8, k=4, seed=1)
    r = _restricted(m, {})
    pl = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)["chosen"][0]
    from mdi import capacity as CAP
    chk = CAP.checker_plan(r)
    assert list(chk.order) != list(pl.order), "the control needs differing producer / checker orders"
    n1 = SP.compile_support(pl, r.factors, r.card).counts()["scan_positions"]
    n2 = SP.compile_support(chk, r.factors, r.card).counts()["scan_positions"]
    res = _run(m, {})
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    s = _att(res, "support")[0]
    assert s["verdict"] == "ADMITTED" and s["checker_compiled_separately"] is True
    assert _src(res, "support compilation") >= n1 + n2                      # BOTH compilations charged
    pr = next(p for p in res.prices if p["name"] == "identity")
    assert pr["counters"]["support_rows_total"]["value"] > 0
    # (a) the second compilation refuses after the first was admitted -> LATE_REFUSAL, typed, dense certified
    orig = SP.compile_support
    calls = []

    def second_refuses(plan, factors, card, **kw):
        calls.append(plan.name)
        if len(calls) == 2:
            raise SP.SupportError("injected refusal of the checker-order compilation")
        return orig(plan, factors, card, **kw)
    monkeypatch.setattr(SP, "compile_support", second_refuses)
    res2 = _run(m, {})
    assert res2.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res2, m, {})
    s2 = _att(res2, "support")[0]
    assert s2["verdict"] == "LATE_REFUSAL" and "after the producer-order compilation was admitted" in s2["detail"] and s2["charged_entries"] >= n1
    assert res2.plan["selector"]["executed_route"] == "dense" and [p["name"] for p in res2.prices] == ["identity"]
    assert any(x.get("typed") == "SUPPORT_REFUSAL" for x in res2.rejected)
    monkeypatch.undo()
    # (b) the transformed record's BINDING runs out of the probe window -> SELECTOR_LATE_REFUSAL, the preserved dense record runs
    orig_b = PLN.bind_loaded

    def window_spent(back, *a, **k):
        if (back.program or {}).get("support") or (back.program or {}).get("quotient"):
            raise PLN.ProbeExhausted("injected: the probe window is spent during the binding re-derivation")
        return orig_b(back, *a, **k)
    monkeypatch.setattr(PLN, "bind_loaded", window_spent)
    res3 = _run(m, {})
    assert res3.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res3, m, {})
    blk3 = res3.plan["selector"]
    assert _att(res3, "support")[0]["verdict"] == "ADMITTED" and blk3["recommended"] == "support"
    assert blk3["executed_route"] == "dense" and blk3["agreement"] is False and blk3["late_refusal"].startswith("binding:")
    assert res3.plan["chosen"] == "identity:dense" and res3.plan["executed"]["layout"] != "sparse-support"
    assert any(x.get("typed") == "SELECTOR_LATE_REFUSAL" for x in res3.rejected)
    monkeypatch.undo()
    # (c) the transformed record is ineligible at binding (its declaration cannot be re-derived) -> the same transition
    def ineligible(back, *a, **k):
        price = orig_b(back, *a, **k)
        if (back.program or {}).get("support"):
            price.eligible = False
            price.ineligible_reason = "injected: the declared support could not be re-derived as declared at binding"
        return price
    monkeypatch.setattr(PLN, "bind_loaded", ineligible)
    res4 = _run(m, {})
    assert res4.status == "CERTIFIED_FALLBACK_ONLY" and res4.plan["chosen"] == "identity:dense"
    assert res4.plan["selector"]["late_refusal"].startswith("binding: injected") and res4.plan["selector"]["agreement"] is False
    assert any(x.get("typed") == "SELECTOR_LATE_REFUSAL" for x in res4.rejected)


# ---------------------------------------------------------------- 13: the route-policy interface keeps the pilots' calls meaning what they meant
def test_route_policy_values_and_route_call_compatibility():
    m = _chain_model(11)
    bad = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, route_policy="sparse")
    assert bad.status == "INVALID_INPUT" and "route_policy" in bad.reason
    a = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, quotient_enabled=True)
    b = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, route_policy="quotient")
    assert a.status == b.status == "CERTIFIED_FALLBACK_ONLY" and a.plan["identity"] == b.plan["identity"] and b.plan["route_policy"] == "quotient"
    assert a.plan.get("selector") is None and b.plan.get("selector") is None and [p["name"] for p in b.prices] == ["identity"]
    c = PLN.solve(m, {}, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, support_enabled=True, quotient_enabled=True, route_policy="dense")
    assert c.status == "CERTIFIED_FALLBACK_ONLY" and c.plan["route_policy"] == "dense" and c.plan["executed"].get("quotient") is None \
        and c.plan["executed"].get("layout") != "sparse-support" and not any(x.get("name", "").startswith("identity+") for x in c.rejected)
    # the pilots' legacy admission now polls the deadline in construction and planning (recorded as sources only when charged)
    assert _src(b, "quotient construction") > 0


# ---------------------------------------------------------------- 14: the selector arm through the public launcher on a toy packet, separate input directory, panel-driven scoring
def test_toy_packet_preparation_runs_the_selector_arm_on_a_separate_input_dir_and_scores_panel_driven():
    from ext import uai, score_cells as SCO
    tmp = tempfile.mkdtemp()
    m = _chain_model(11)
    ev = {3: 1}
    mp = _write_uai(m)
    model_bytes = open(mp, "rb").read()
    evid_bytes = b"1 3 1\n"
    # the reference: the exact marginals rounded to six decimals (observed variables as point masses)
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    rows = [[float(pt[v][s]) for s in range(m.card[v])] if v in pt else [1.0 if s == ev[v] else 0.0 for s in range(m.card[v])] for v in range(m.nvars)]
    ref_path = os.path.join(tmp, "Tiny_1.uai.MAR")
    uai.write_mar(ref_path, rows)
    pk = os.path.join(tmp, "packet.zip")
    with zipfile.ZipFile(pk, "w") as z:
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai", model_bytes)
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.evid", evid_bytes)
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.MAR", open(ref_path, "rb").read())
    pinned = ["code/mdi/launch.py", "code/ext/supervise.py", "code/mdi/arm.py", "code/mdi/pipeline.py"]
    pin = {"commit": "synthetic", "code_tree_sha256": {rel: L.sha256_file(os.path.join(HERE, rel[5:])) for rel in pinned}}
    pp = os.path.join(tmp, "BUILD_PIN.json")
    json.dump(pin, open(pp, "w"))
    from mdi import config as K
    input_dir = os.path.join(tmp, "panel_inputs")                       # SEPARATE from the pinned default directory
    order = [["Tiny_1", "baseline"], ["Tiny_1", "selector"]]
    b = {"engine_commit": "synthetic", "build_pin": {"path": pp, "sha256": L.sha256_file(pp)}, "input_dir": input_dir,
         "inputs": {"Tiny_1.uai": hashlib.sha256(model_bytes).hexdigest(), "Tiny_1.uai.evid": hashlib.sha256(evid_bytes).hexdigest()},
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]),
                           "threads": int(K.RESOURCES["threads"]), "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": 90.0, "allowance_s": 200.0, "session_cap_s": 1000.0, "previous_expenditure_s": {"earlier": 12.5},
         "durable_grace_s": 10.0, "order": order, "synthetic_control": True, "launch_authorized": True}
    bp = os.path.join(tmp, "bindings.json")
    json.dump(b, open(bp, "w"))
    rd = os.path.join(tmp, "run")
    man, idir = L.prepare(rd, b, pin, bp, pp, packet=pk, argv=["launch", "toy"])
    assert idir == input_dir and man["input_dir"] == input_dir
    assert sorted(os.listdir(input_dir)) == ["Tiny_1.uai", "Tiny_1.uai.evid"]      # the reference is NEVER restored into the solver inputs
    assert man["order"] == order
    # the REAL child command carries the input directory as its fifth argument
    cmd = L.default_cmd_factory(sys.executable, input_dir)("Tiny_1", "selector", "/x", 90.0)
    assert cmd[-1] == input_dir and cmd[3:6] == ["--cell", "Tiny_1", "selector"]
    led = L.run_cells(rd, b)                                              # real children, real supervisor
    assert [c["status"] for c in led["cells"]] == ["CONSUMED", "CONSUMED"], json.dumps(led, indent=1)[:2000]
    for c in led["cells"]:
        att = c["attempts"][0]
        assert att["arm_outcome"] == "CERTIFIED_FALLBACK_ONLY" and att["class"] == "certified_fallback", att
    sel = json.load(open(os.path.join(rd, "cells", "Tiny_1_selector", "attempt_1", "arm_Tiny_1_selector.json")))
    assert sel["arm"] == "selector" and sel["input_sha256"]["model"] == b["inputs"]["Tiny_1.uai"]
    blk = sel["pipeline"]["plan"]["selector"]
    assert blk["executed_route"] == "quotient" and [a["verdict"] for a in blk["attempts"]] == ["ADMITTED"]
    base = json.load(open(os.path.join(rd, "cells", "Tiny_1_baseline", "attempt_1", "arm_Tiny_1_baseline.json")))
    assert base["arm"] == "baseline" and base["pipeline"]["plan"].get("selector") is None
    # panel-driven scoring: the problems come from the ledger, the inputs from the manifest, the reference from the packet
    out = SCO.score_run(rd, pk)
    assert out["problems"] == ["Tiny_1"] and out["references_missing"] == [] and out["input_dir"] == input_dir
    assert sorted(os.listdir(input_dir)) == ["Tiny_1.uai", "Tiny_1.uai.evid"]
    assert os.path.exists(os.path.join(rd, "references_read_after_all_cells", "Tiny_1.uai.MAR"))
    for lab in ("Tiny_1_baseline", "Tiny_1_selector"):
        a = out["cells"][lab]["attempts"][0]
        assert a["containment"]["coordinates"] == sum(m.card[v] for v in pt) and a["containment"]["inside_with_half_ulp_slack"] == a["containment"]["coordinates"], a
        assert a["point_vector"]["max_hellinger"] < 0.01            # the published point is the midpoint of a width <= 1/100 enclosure
    # an unknown arm name in non-synthetic bindings is refused BEFORE any child
    b2 = dict(b, synthetic_control=False, order=[["Tiny_1", "sparse"]], cell_wall_s=float(K.RESOURCES["arm_wall_s"]))
    with pytest.raises(L.Refused) as ei:
        L.validate_bindings(b2, pin, HERE, input_dir)
    assert "unknown arm" in str(ei.value)


def test_scorer_takes_its_problems_from_the_ledger_and_reports_a_missing_reference():
    from ext import score_cells as SCO
    tmp = tempfile.mkdtemp()
    rd = os.path.join(tmp, "run"); os.makedirs(rd)
    led = {"cells": [{"label": "Alpha_1_baseline", "problem": "Alpha_1", "arm": "baseline", "status": "NOT_RUN_ALLOWANCE_STOP", "attempts": []},
                     {"label": "Beta_2_selector", "problem": "Beta_2", "arm": "selector", "status": "NOT_RUN_ALLOWANCE_STOP", "attempts": []},
                     {"label": "Alpha_1_selector", "problem": "Alpha_1", "arm": "selector", "status": "NOT_RUN_ALLOWANCE_STOP", "attempts": []}]}
    json.dump(led, open(os.path.join(rd, "LEDGER.json"), "w"))
    pk = os.path.join(tmp, "packet.zip")
    with zipfile.ZipFile(pk, "w") as z:
        z.writestr(L.PACKET_MEMBER_PREFIX + "Alpha_1.uai.MAR", b"MAR\n1 2 0.5 0.5\n")
    assert SCO.ledger_problems(led) == ("Alpha_1", "Beta_2")
    refs = SCO.extract_refs(pk, os.path.join(tmp, "refs"), ("Alpha_1", "Beta_2"))
    assert refs["Beta_2"] is None and refs["Alpha_1"].endswith("Alpha_1.uai.MAR")
    out = SCO.score_run(rd, pk, refdir=os.path.join(tmp, "refs2"), input_dir=os.path.join(tmp, "inputs"))
    assert out["problems"] == ["Alpha_1", "Beta_2"] and out["references_missing"] == ["Beta_2"]
    assert all("never ran" in c["diagnostics"] for c in out["cells"].values())
