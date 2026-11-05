"""Adversarial controls of the OPT-IN selector pilot (repaired 4 Nov 2026). EVERY control -- the tiny invocation AND its exact-oracle
check -- runs in a FRESH child process (tests/_pilot_control_child.py) under the UNCHANGED `ext.supervise.run` with a 10 s deadline, a
1 GiB process-tree RSS limit and NO grace. Fixtures have <= 4,096 restricted states, asserted by the child BEFORE every oracle call.
A receipt (supervisor outcome, charged wall, peak tree RSS, child result) is persisted for EVERY control -- failures and timeouts
included -- before any assertion. Injected values are labelled by the child and are not elapsed time. The default path is asserted
restored after each control; the accepted pin is asserted intact."""
import os, sys, json, tempfile, time, hashlib, math
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
import pytest
from mdi import pipeline as PLN, selector_pilot as SPL
from ext import supervise as SV

CHILD = os.path.join(HERE, "tests", "_pilot_control_child.py")
RECEIPTS_DIR = os.environ.get("MDI_PILOT_RECEIPTS_DIR", os.path.join(HERE, "runs/mdi_2026-10-28/GENERALIZATION_2026-11-03/COMPARISON_2026-11-04/pilot/receipts"))
LIMITS = {"deadline_s": 10.0, "mem_limit_kib": 1 << 20, "grace_s": 0.0, "max_oracle_states": 4096}


def _control(name):
    os.makedirs(RECEIPTS_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(); out_path = os.path.join(tmp, "result.json")
    cmd = [sys.executable, CHILD, name, out_path]
    sup = SV.run(cmd, cwd=HERE, log_path=os.path.join(tmp, "supervisor.log"), deadline_s=LIMITS["deadline_s"], mem_limit_kib=LIMITS["mem_limit_kib"],
                 env={"PYTHONPATH": HERE}, label="pilot:" + name)
    receipt_path = os.path.join(RECEIPTS_DIR, "%s.json" % name)
    receipt = {"control": name, "command": cmd, "limits": LIMITS, "supervisor": {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "mem_samples")},
               "charged_s": sup.get("elapsed_s"), "child": None, "child_read_status": "pending", "supervisor_log": None, "recorded": time.strftime("%Y-%m-%d %H:%M:%S")}
    def persist():
        with open(receipt_path + ".tmp", "w") as f:
            json.dump(receipt, f, indent=1, default=str)
            f.flush(); os.fsync(f.fileno())
        os.replace(receipt_path + ".tmp", receipt_path)
    persist()       # retain the supervisor's known charge BEFORE parsing any child artifact
    res = None
    try:
        if os.path.exists(out_path):
            with open(out_path) as f:
                parsed = json.load(f)
            if not isinstance(parsed, dict):
                raise ValueError("child result is not a JSON object")
            res = parsed
            receipt["child"] = res
            receipt["child_read_status"] = "parsed"
        else:
            receipt["child_read_status"] = "missing"
    except (OSError, ValueError) as e:
        receipt["child_read_status"] = "invalid"
        receipt["child_read_error"] = {"type": type(e).__name__, "message": str(e)}
    try:
        with open(os.path.join(tmp, "supervisor.log")) as f:
            receipt["supervisor_log"] = f.read()[-1500:]
    except OSError as e:
        receipt["supervisor_log_error"] = {"type": type(e).__name__, "message": str(e)}
    finally:
        persist()
    assert isinstance(receipt["charged_s"], (int, float)) and math.isfinite(receipt["charged_s"]) and receipt["charged_s"] >= 0, (name, "unknown or invalid supervisor charge")
    assert sup["outcome"] == "COMPLETED", (name, sup["outcome"], (res or {}).get("error"))
    assert res is not None and res["ok"], (name, (res or {}).get("error"))
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN._PILOT_HOOKS == {}
    return res["result"], receipt


def test_pilot_disabled_by_default_and_the_accepted_pin_intact():
    assert PLN._select_route.__module__ == "mdi.pipeline" and PLN._PILOT_HOOKS == {}
    with SPL.enabled():
        assert PLN._select_route is SPL.select_route and set(PLN._PILOT_HOOKS) == {"admission", "record_begin", "record_end", "select_begin", "select_end", "selected", "terminal"}
    assert PLN._PILOT_HOOKS == {} and PLN.run_loaded.__module__ == "mdi.pipeline"
    pin = json.load(open(os.path.join(HERE, "runs/mdi_2026-10-28/BUILD_PIN_6ce6977.json")))
    changed = [f for f, h in pin["code_tree_sha256"].items() if hashlib.sha256(open(os.path.join(os.path.dirname(HERE), f), "rb").read()).hexdigest() != h]
    assert changed == ["code/mdi/pipeline.py"], changed          # the ONLY accepted file the pilot build changes: the opt-in hook sites (pinned separately)


def test_positive_bypass():
    r, _ = _control("positive_bypass")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["oracle"]["contained"] and r["oracle"]["restricted_states"] <= 4096
    assert [s[0] for s in r["scopes"]] == ["gate", "dense.candidate", "dense.record"] and r["attempts"] == []
    assert r["cleanup"]["dropped_cache_entries"] == {"support": 0, "recognition": 0, "occupancy": 0} and r["cleanup"]["reason"] == "selected"
    assert r["record_scopes"][0]["kind"] == "mandatory" and r["selection_scope"]["kind"] == "mandatory"


def test_natural_rejection_accounts_every_scope_and_releases_probe_state():
    r, _ = _control("natural_rejection")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["oracle"]["contained"]
    assert [s[0] for s in r["scopes"]] == ["gate", "dense.candidate", "quotient.recognition", "support.compile_producer_order", "support.pricing", "dense.record"]
    assert [tuple(a[:2]) for a in r["attempts"]] == [("quotient", "NOT_ADMITTED"), ("support", "NOT_ADMITTED")]
    assert r["manifest"]["new_cache_entries_discovery"] == {"support": 1, "recognition": 1, "occupancy": 0}
    assert r["cleanup"]["dropped_cache_entries"] == {"support": 1, "recognition": 1, "occupancy": 0} and r["caches_after"]["support"] == 0 and r["caches_after"]["recognition"] == 0
    assert r["total_optional_wall_s"] >= r["optional_cost"]["optional_wall_s"] > 0


def test_residual_zero_quotient_success_never_probes_the_quotient_in_discovery_or_binding():
    r, _ = _control("residual_zero_quotient_success")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["route"] == "quotient" and r["oracle"]["contained"] and r["oracle"]["restricted_states"] == 16
    assert tuple(r["attempts"][0][:3]) == ("quotient", "ADMITTED", "admitted_without_probe")
    assert set(r["occupancy_call_free_counts"]) == {4}, r["occupancy_call_free_counts"]      # every occupancy call is on the 4 dense free variables; NONE on the 2-variable quotient (discovery AND binding)
    assert r["binding_scopes"] and r["binding_scopes"][0]["status"] == "admitted_without_probe" and r["binding_scopes"][0]["charged_entries"] == 0
    assert [s[0] for s in r["scopes"]].index("quotient.pricing") < [s[0] for s in r["scopes"]].index("quotient.preflight")      # cheap ratio check BEFORE the preflight
    assert r["cleanup"]["kept_for_execution"]["recognition"] == 1 and r["executed_quotient"] is True and r["caches_after"]["occupancy"] == 1
    assert len(r["record_scopes"]) == 2 and all(x["kind"] == "optional" for x in r["record_scopes"])          # both records' stage-4 walls are optional when a transformed record exists
    assert r["checker"]["coordinates_checked"] == 8


def test_late_binding_refusal_releases_binding_created_state_and_keeps_the_record_scope():
    r, _ = _control("late_binding_refusal_after_genuine_binding")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["route"] == "dense" and r["chosen"] == "identity:dense" and r["oracle"]["contained"]
    assert r["late_refusal"].startswith("binding:") and "SELECTOR_LATE_REFUSAL" in r["rejected_typed"]
    rs = {x["record"]: x for x in r["record_scopes"]}
    assert rs["identity"]["status"] == "bound_ineligible" and rs["identity"]["wall_s"] > 0
    assert r["cleanup"]["kept_for_execution"] == {"support": 0, "recognition": 0, "occupancy": 0} and r["cleanup"]["dropped_cache_entries"]["recognition"] == 1
    assert r["caches_after"] == {"support": 0, "recognition": 0, "occupancy": 1}          # only the dense candidate's occupancy entry survives


def test_binding_exhaustion_retains_the_failed_records_complete_scope():
    r, _ = _control("binding_exhausted_after_injected_work")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["route"] == "dense" and r["oracle"]["contained"]
    rs = {x["record"]: x for x in r["record_scopes"]}
    assert rs["identity"]["status"] == "late_refusal" and rs["identity"]["wall_s"] >= r["injected"]["sleep_s"]      # the failed binding's wall is retained though bind_loaded never returned
    assert r["total_optional_wall_s"] >= rs["identity"]["wall_s"] and "SELECTOR_LATE_REFUSAL" in r["rejected_typed"]


def test_global_stop_at_the_gate_finalizes_the_scope_and_starts_no_probe():
    r, _ = _control("global_stop_at_gate")
    assert r["status"] == "RESOURCE_STOP" and r["attempts"] == []
    assert [tuple(s[:3]) for s in r["scopes"]] == [("gate", "optional", "global_stop")] and r["scopes"][0][4] == 20    # the gate's full charge (20 restricted table entries) is kept
    assert "optional_cost" in r and r["optional_cost"]["optional_wall_s"] >= 0 and r["cleanup"]["reason"].startswith("terminal:")


def test_global_stop_in_the_recognizer_stays_terminal():
    r, _ = _control("global_stop_in_recognizer")
    assert r["status"] == "RESOURCE_STOP" and [tuple(a[:2]) for a in r["attempts"]] == [("quotient", "GLOBAL_STOP")] and r["attempts"][0][4] == 8
    assert any(s[0] == "quotient.recognition" and s[2] == "global_stop" for s in r["scopes"]) and not any(s[0].startswith("support") for s in r["scopes"])
    assert r["cleanup"]["reason"].startswith("terminal:") and r["caches_after"]["recognition"] == 0


def test_prospective_refusal_declines_before_allocation():
    r, _ = _control("prospective_refusal_declines_before_allocation")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["route"] == "dense" and r["oracle"]["contained"]
    assert set(r["occupancy_call_free_counts"]) == {4}            # no quotient-sized occupancy call
    assert r["declined"] and r["declined"][0]["preflight"]["decision"] == "declined_before_allocation" and "MISSED opportunity" in r["declined"][0]["reason"]
    pre = next(s for s in r["scopes"] if s[0] == "quotient.preflight"); assert pre[2] == "declined_before_allocation"
    assert r["attempts"][0][1] == "NOT_ADMITTED" and r["attempts"][0][4] > 0


def test_ratio_below_two_is_rejected_before_any_admission_work():
    r, _ = _control("ratio_below_two_rejected_before_admission_work")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["oracle"]["contained"] and r["oracle"]["restricted_states"] <= 4096
    assert r["attempts"][0][1] == "NOT_ADMITTED" and r["attempts"][0][3] < 2.0
    names = [s[0] for s in r["scopes"]]
    assert "quotient.pricing" in names and "quotient.preflight" not in names and "quotient.admission_with_probe" not in names
    assert set(r["occupancy_call_free_counts"]) == {10}           # only the dense candidate's occupancy; nothing on the quotient


def test_support_with_two_orders_and_with_one_order():
    r, _ = _control("support_two_orders")
    assert r["status"] == "CERTIFIED_FALLBACK_ONLY" and r["route"] == "support" and r["oracle"]["contained"] and r["oracle"]["restricted_states"] == 4096
    names = [s[0] for s in r["scopes"]]; assert "support.compile_producer_order" in names and "support.compile_checker_order" in names
    assert r["cleanup"]["kept_for_execution"]["support"] == 1 and r["cleanup"]["dropped_cache_entries"]["support"] == 1 and r["executed_support"] is True
    r2, _ = _control("support_same_order")
    assert r2["status"] == "CERTIFIED_FALLBACK_ONLY" and r2["route"] == "support" and r2["oracle"]["contained"] and "support.compile_checker_order" not in [s[0] for s in r2["scopes"]]


def test_static_prospective_figures_distinguish_operand_multiplicity():
    r, _ = _control("static_prospective_figures_repeated_factors")
    one, two = r["single"], r["doubled_factor_occurrences"]
    assert r["no_allocation"] and two["sum_bag_domains_entries"] == one["sum_bag_domains_entries"] and two["operand_weighted_entries"] > one["operand_weighted_entries"]
    assert "NOT included" in one["units"]


def test_receipts_total():
    recs = [json.load(open(os.path.join(RECEIPTS_DIR, f))) for f in sorted(os.listdir(RECEIPTS_DIR)) if f.endswith(".json") and f != "SUMMARY.json"]
    charges = [r.get("charged_s") for r in recs]
    assert all(isinstance(c, (int, float)) and math.isfinite(c) and c >= 0 for c in charges), "unknown or invalid supervisor charge; no total available"
    tot = sum(charges)
    json.dump({"controls": len(recs), "supervised_wall_total_s": round(tot, 4), "limits": LIMITS, "scope": "each control = one fresh child incl. its tiny invocation AND its oracle check, supervised by ext.supervise.run (unchanged); the supervisor's spawn-to-exit wall is the charge",
               "outcomes": {r["control"]: r["supervisor"]["outcome"] for r in recs}, "built": time.strftime("%Y-%m-%d %H:%M:%S")}, open(os.path.join(RECEIPTS_DIR, "SUMMARY.json"), "w"), indent=1)
    assert tot < 60 and all(r["supervisor"]["outcome"] == "COMPLETED" for r in recs)
