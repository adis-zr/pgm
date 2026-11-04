"""Adversarial controls of the OPT-IN selector pilot (mdi/selector_pilot.py; disabled by default). Tiny synthetic models
only (<= 4,096 joint states where an exact oracle is used); every actual invocation runs under a 10 s SIGALRM supervision limit
and the budget's 1 GiB RSS cap with no grace. The engine's DECLARED in-process wall is 120 s so that the FROZEN precondition
(window + dense forecast + 30 s) does not skip the probes; the actual elapsed wall of every invocation is recorded in
`pilot_receipts` (it is ~0.1 s). Nothing of the accepted snapshot is edited: the pilot patches two pipeline attributes while
enabled and restores them afterwards (asserted)."""
import os, sys, json, tempfile, time, signal
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
import pytest
from mdi import model as M, pipeline as PLN, oracle as O, budget as B, quotient as QT, support as SP, capacity as CAPX, selector_pilot as SPL
import mdi.registry  # noqa: F401
from test_mdi_quotient_pilot import _chain_model, _eq, _ne, _restricted
from test_mdi_support_pilot import _perm_chain, _band_chain

RECEIPTS = []
SUPERVISION_S = 10


def _run(m, ev, **kw):
    """ONE actual tiny invocation: 10 s supervision (SIGALRM), 1 GiB budget RSS cap, no grace; the declared engine wall is 120 s."""
    def _alarm(signum, frame):
        raise TimeoutError("tiny invocation exceeded the %d s supervision limit" % SUPERVISION_S)
    case = kw.pop("_case", "?")
    old = signal.signal(signal.SIGALRM, _alarm); signal.alarm(SUPERVISION_S)
    t0 = time.monotonic()
    try:
        with SPL.enabled():
            res = PLN.solve(m, ev, wall_s=kw.pop("wall_s", 120), cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False, route_policy="selector", **kw)
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, old)
    RECEIPTS.append({"case": case, "status": res.status, "actual_elapsed_s": round(time.monotonic() - t0, 4), "supervision_limit_s": SUPERVISION_S, "rss_cap_bytes": 1 << 30,
                     "joint_states": None, "optional_wall_s": (res.plan.get("selector") or {}).get("optional_cost", {}).get("optional_wall_s")})
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN.run_loaded.__module__ == "mdi.pipeline"      # the default path is restored
    return res


def _contained(res, m, ev):
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    return set(res.intervals) == set(range(m.nvars)) and all(Fr(res.intervals[v][a][0]) <= pt[v][a] <= Fr(res.intervals[v][a][1]) for v in pt for a in range(len(pt[v])))


def _scopes(res):
    return [(s["scope"], s["kind"], s["status"]) for s in res.plan["selector"]["scopes"]]


def _no_overlap(res):
    rows = res.plan["selector"]["scopes"]
    return all(r["wall_s"] >= 0 for r in rows) and abs(sum(r["wall_s"] for r in rows) - res.plan["selector"]["optional_cost"]["optional_wall_s"] - res.plan["selector"]["optional_cost"]["mandatory_prefix_wall_s"]) < 1e-9


_POS = M.Model(nvars=5, card=[2] * 5, factors=[M.Factor(scope=(v, v + 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=v) for v in range(4)]).validate()
_NAT = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(1), Fr(1), Fr(0)], origin=0)]).validate()


def test_pilot_is_disabled_by_default_and_restores_the_frozen_attributes():
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN.run_loaded.__module__ == "mdi.pipeline"
    with SPL.enabled():
        assert PLN._select_route is SPL.select_route and PLN.run_loaded is SPL.run_loaded
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN.run_loaded.__module__ == "mdi.pipeline"
    # the accepted pin keeps verifying: the pilot is a NEW file, no pinned file changed
    import hashlib
    pin = json.load(open(os.path.join(HERE, "runs/mdi_2026-10-28/BUILD_PIN_6ce6977.json")))
    bad = [f for f, h in pin["code_tree_sha256"].items() if hashlib.sha256(open(os.path.join(os.path.dirname(HERE), f), "rb").read()).hexdigest() != h]
    assert bad == [] and len(pin["code_tree_sha256"]) == 83


def test_positive_bypass_records_only_the_gate_as_optional_and_releases_nothing_the_dense_route_needs():
    res = _run(_POS, {}, _case="positive bypass")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, _POS, {})
    blk = res.plan["selector"]
    assert _scopes(res) == [("gate", "optional", "done"), ("dense.candidate", "mandatory", "done"), ("dense.record", "mandatory", "done")]
    assert blk["optional_cost"]["optional_wall_s"] == blk["scopes"][0]["wall_s"] and blk["gate"]["verdict"] == "bypass" and _no_overlap(res)
    assert blk["optional_state_manifest"]["new_cache_entries"] == {"support": 0, "recognition": 0, "occupancy": 0}
    assert blk["cleanup"]["dropped_cache_entries"] == {"support": 0, "recognition": 0, "occupancy": 0}


def test_hard_zero_no_benefit_rejection_accounts_every_optional_scope_and_cleans_up_before_dense_fallback():
    occ_before = len(CAPX._OCCUPANCY_CACHE)
    res = _run(_NAT, {}, _case="natural rejection [1,1,1,0]")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, _NAT, {})
    blk = res.plan["selector"]
    names = [s["scope"] for s in blk["scopes"]]
    assert names == ["gate", "dense.candidate", "quotient.recognition", "support.compile_producer_order", "support.pricing", "dense.record"], names
    assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "NOT_ADMITTED"), ("support", "NOT_ADMITTED")]
    assert all(s["charged_entries"] > 0 for s in blk["scopes"] if s["scope"] in ("gate", "quotient.recognition", "support.compile_producer_order"))
    assert blk["optional_cost"]["optional_wall_s"] > 0 and _no_overlap(res)
    # optional state: one recognition and one support were created by the probes and are DROPPED before the dense executor;
    # the dense candidate's occupancy entry (mandatory fallback state) is NOT dropped
    assert blk["optional_state_manifest"]["new_cache_entries"] == {"support": 1, "recognition": 1, "occupancy": 0}
    assert blk["cleanup"]["dropped_cache_entries"] == {"support": 1, "recognition": 1, "occupancy": 0} and blk["cleanup"]["kept_for_execution"] == {"support": 0, "recognition": 0, "occupancy": 0}
    assert blk["cleanup"]["retained_bytes_estimate_after"] <= blk["cleanup"]["retained_bytes_estimate_before"] and blk["cleanup"]["wall_s"] >= 0
    assert "does not guarantee" in blk["cleanup"]["note"]
    # the dense executor did not recompute its occupancy (no extra 'occupancy probe' charge beyond the single admission probe)
    assert sum(1 for k in res.budget["used_by_source"] if "occupancy probe" in k) == 1


def test_admitted_quotient_restores_every_query_keeps_only_its_own_state_and_skips_the_probe_when_the_conservative_forecast_admits():
    m = _chain_model(11); ev = {6: 2}
    calls = []
    orig = CAPX.occupancy_probe

    def spy(plan, factors, card, deadline=None, charge=None):
        calls.append(len(factors)); return orig(plan, factors, card, deadline=deadline, charge=charge)
    CAPX.occupancy_probe = spy
    try:
        res = _run(m, ev, _case="admitted quotient, restoration")
    finally:
        CAPX.occupancy_probe = orig
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, ev)
    blk = res.plan["selector"]
    assert blk["executed_route"] == "quotient" and [a["verdict"] for a in blk["attempts"]] == ["ADMITTED"] and blk["attempts"][0]["preflight"] == "admitted_without_probe"
    names = [s["scope"] for s in blk["scopes"]]
    assert names == ["gate", "dense.candidate", "quotient.recognition", "quotient.construction", "quotient.planning", "quotient.preflight", "quotient.pricing", "quotient.program_record", "dense.record"], names
    n_dense = len(_restricted(m, ev).factors)
    assert set(calls) == {n_dense}, calls             # every occupancy call (admission, binding cache hit, aggregation cache hit) is on the DENSE factors: the quotient's probe never ran
    assert blk["scopes"][-1]["kind"] == "optional"    # the dense record is EXTRA when a transformed record exists
    assert blk["optional_state_manifest"]["new_cache_entries"]["recognition"] == 1 and blk["optional_state_manifest"]["new_cache_entries"]["occupancy"] == 0
    assert blk["cleanup"]["kept_for_execution"]["recognition"] == 1 and blk["cleanup"]["dropped_cache_entries"]["recognition"] == 0      # the selected quotient's recognition is kept for the executor
    assert res.plan["executed"]["quotient"]["reused_from_discovery"] is True                                                            # no uncharged recompilation
    assert res.checker["quotient_rederived"]["restoration_checked_rows"] > 0 and set(res.intervals) == set(range(m.nvars))


def test_admitted_support_keeps_its_compilation_and_both_orders_are_separate_scopes():
    m = _perm_chain(8, k=4, seed=1)
    res = _run(m, {}, _case="admitted support, two compilations")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    blk = res.plan["selector"]
    assert blk["executed_route"] == "support" and res.plan["executed"]["layout"] == "sparse-support"
    names = [s["scope"] for s in blk["scopes"]]
    assert "support.compile_producer_order" in names and "support.compile_checker_order" in names and "support.program_record" in names
    cp = next(s for s in blk["scopes"] if s["scope"] == "support.compile_producer_order")
    assert cp["bytes"]["retained_rows_bytes"] > 0 and cp["charged_entries"] > 0
    assert blk["optional_state_manifest"]["new_cache_entries"]["support"] == 2
    assert blk["cleanup"]["kept_for_execution"]["support"] == 1 and blk["cleanup"]["dropped_cache_entries"]["support"] == 1          # the checker-order compilation is not needed by the executor (the checker reconstructs its own)
    assert res.plan["executed"]["support"]["reused_from_discovery"] is True


def test_transformed_binding_rejection_is_a_charged_late_refusal_with_the_optional_state_released(monkeypatch):
    m = _chain_model(11)
    orig = PLN.bind_loaded

    def ineligible(back, *a, **k):
        price = orig(back, *a, **k)
        if (back.program or {}).get("quotient"):
            price.eligible = False; price.ineligible_reason = "injected: declared quotient not re-derivable at binding"
        return price
    monkeypatch.setattr(PLN, "bind_loaded", ineligible)
    res = _run(m, {}, _case="transformed binding rejection")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {}) and res.plan["chosen"] == "identity:dense"
    blk = res.plan["selector"]
    assert blk["late_refusal"].startswith("binding:") and blk["executed_route"] == "dense" and blk["attempts"][0]["verdict"] == "ADMITTED"
    assert blk["optional_cost"]["optional_wall_s"] > 0 and blk.get("transformed_binding_s") is not None
    assert blk["cleanup"]["dropped_cache_entries"]["recognition"] == 1 and blk["cleanup"]["kept_for_execution"] == {"support": 0, "recognition": 0, "occupancy": 0}
    assert any(x.get("typed") == "SELECTOR_LATE_REFUSAL" for x in res.rejected)


def test_long_no_poll_span_is_measured_and_caught_at_the_next_poll_as_a_charged_fallback(monkeypatch):
    """The record creation (`_identity_record` incl. `executable_identity`) is an UNPOLLED span. The injected clock crosses the
    window inside it; the pilot's post-record poll catches the crossing: the span's wall is recorded in its scope, the attempt
    is PROBE_EXHAUSTED, every charge stands, the dense fallback runs. This measures an overshoot; it does not bound it."""
    m = _chain_model(11)
    clock = [0.0]
    monkeypatch.setattr(PLN, "_PROBE_CLOCK", [lambda: time.monotonic() + clock[0]])
    orig = PLN.executable_identity

    def cross_inside(kind, prog, request=None):
        if prog.get("quotient"):
            clock[0] = 1000.0                                      # the window is crossed INSIDE the unpolled record creation
        return orig(kind, prog, request=request)
    monkeypatch.setattr(PLN, "executable_identity", cross_inside)
    res = _run(m, {}, _case="no-poll span crossing (record creation)")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    blk = res.plan["selector"]
    assert blk["attempts"][0]["verdict"] == "PROBE_EXHAUSTED" and "after quotient record" in blk["attempts"][0]["detail"]
    rec_scope = next(s for s in blk["scopes"] if s["scope"] == "quotient.program_record")
    assert rec_scope["status"] == "done" and rec_scope["wall_s"] >= 0                # the span completed unpolled; its wall is measured
    assert blk["attempts"][0]["charged_entries"] > 0 and blk["executed_route"] == "dense" and [p["name"] for p in res.prices] == ["identity"]
    assert blk["transformed_record_discarded_after_creation"] is True            # the record built inside the overrun span was discarded, not bound
    assert blk["cleanup"]["dropped_cache_entries"]["recognition"] == 1


def test_prospective_large_allocation_is_refused_before_any_allocation_and_the_dense_candidate_stands(monkeypatch):
    """Spies, not allocations: the conservative forecast is forced to refuse and the allowance set to one entry, so the quotient
    candidate must be DECLINED before `occupancy_probe` runs on it; the dense candidate and its charges stand."""
    m = _chain_model(11)
    calls = []
    orig_probe = CAPX.occupancy_probe

    def spy(plan, factors, card, deadline=None, charge=None):
        calls.append(len(factors)); return orig_probe(plan, factors, card, deadline=deadline, charge=charge)
    monkeypatch.setattr(CAPX, "occupancy_probe", spy)
    orig_admit = CAPX.admit

    def refuse_quotient(fc, wall, cap, now, **kw):
        ad = orig_admit(fc, wall, cap, now, **kw)
        if fc.get("occupancy_used") is False and len(calls) >= 1:            # the pilot's conservative (occupancy=None) forecast for the quotient
            ad = dict(ad, certificate="INJECTED_NOT_FEASIBLE", certificate_reason="injected for the control")
        return ad
    monkeypatch.setattr(CAPX, "admit", refuse_quotient)
    monkeypatch.setattr(SPL, "PILOT_OPTIONAL_PROBE_ENTRIES", 1)
    res = _run(m, {}, _case="prospective allocation refusal")
    assert res.status == "CERTIFIED_FALLBACK_ONLY" and _contained(res, m, {})
    blk = res.plan["selector"]
    assert set(calls) == {len(_restricted(m, {}).factors)}, calls           # no quotient-sized occupancy call: declined before allocation
    pre = next(s for s in blk["scopes"] if s["scope"] == "quotient.preflight")
    assert pre["status"] == "declined_before_allocation" and pre["bytes"] == 0
    rj = next(x for x in res.rejected if x.get("typed") == "QUOTIENT_DECLINED_PREFLIGHT")
    assert rj["preflight"]["decision"] == "declined_before_allocation" and rj["preflight"]["prospective_probe"]["sum_bag_domains_entries"] > 1
    assert "MISSED opportunity" in rj["reason"] and blk["attempts"][0]["verdict"] == "NOT_ADMITTED"
    assert blk["executed_route"] == "dense" and blk["attempts"][0]["charged_entries"] > 0
    assert "quotient.admission_with_probe" not in [s["scope"] for s in blk["scopes"]]


def test_global_stop_inside_a_probe_stays_terminal_with_no_second_probe_and_no_lost_charges_or_scopes(monkeypatch):
    m = _chain_model(11)
    orig = B.Budget.charge

    def seven(self, name, amount=1, where=""):
        cur = orig(self, name, amount, where)
        if where == "quotient recognition" and self.used_by_source.get("%s@%s" % (name, where), 0) > 7:
            raise B.BudgetExceeded(name, self.used_by_source["%s@%s" % (name, where)], 7, where)
        return cur
    monkeypatch.setattr(B.Budget, "charge", seven)
    res = _run(m, {}, _case="global counter stop inside the recognizer")
    assert res.status == "RESOURCE_STOP" and not res.intervals
    blk = res.plan["selector"]
    assert [(a["mechanism"], a["verdict"]) for a in blk["attempts"]] == [("quotient", "GLOBAL_STOP")] and blk["attempts"][0]["charged_entries"] == 8
    sc = next(s for s in blk["scopes"] if s["scope"] == "quotient.recognition")
    assert sc["status"] == "global_stop" and sc["charged_entries"] == 8
    assert "optional_state_manifest" in blk and "optional_cost" in blk            # the block was finished on the stop
    assert not any(s["scope"].startswith("support") for s in blk["scopes"])


def test_write_receipts():
    R = os.path.join(HERE, "runs/mdi_2026-10-28/GENERALIZATION_2026-11-03/COMPARISON_2026-11-04/pilot")
    os.makedirs(R, exist_ok=True)
    tot = sum(r["actual_elapsed_s"] for r in RECEIPTS)
    json.dump({"receipts": RECEIPTS, "actual_invocations": len(RECEIPTS), "actual_elapsed_total_s": round(tot, 4),
               "limits": {"supervision_s": SUPERVISION_S, "rss_cap_bytes": 1 << 30, "grace_s": 0, "declared_engine_wall_s": 120,
                          "note": "the declared in-process wall of 120 s lets the FROZEN precondition admit the probes; the actual supervision limit is the 10 s SIGALRM and the budget's 1 GiB RSS cap; injected clocks / allocators are used for the crossing and refusal controls and are not elapsed time"},
               "built": time.strftime("%Y-%m-%d %H:%M:%S")}, open(os.path.join(R, "pilot_receipts.json"), "w"), indent=1)
    assert tot < 60
