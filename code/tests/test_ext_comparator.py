"""Controls of the comparator glue (qualification pass, 4 Nov 2026): the Merlin adapter's output validation on
hand-written MAR texts (no solver run), and the mixed-arm orchestrator on a toy packet with ONE real MDI selector child
and ONE real Merlin child (tiny synthetic model; counts toward the pass's numerical diagnostic budget)."""
import os, sys, json, zipfile, hashlib, tempfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
import pytest
from mdi import model as M, oracle as O, launch as L, budget as B, config as K
from ext.comparator import merlin_adapter as MA, comparison_launch as CL
from test_mdi_quotient_pilot import _chain_model
from mdi.matrix import _write_uai

MERLIN_PRESENT = os.path.exists(os.path.expanduser(MA.load_pin()["binary"]["path"]))


def test_adapter_output_validation_catches_shape_normalization_point_mass_and_status_faults():
    n, card, ev = 3, [2, 2, 3], {1: 0}
    good = "PR\n0.69 (2.0e+00)\nSTATUS\ntrue: Consistent evidence\nMAR\n3 2 0.500000 0.500000 2 1.000000 0.000000 3 0.387200 0.235900 0.376900\n"
    d = tempfile.mkdtemp()
    def val(txt):
        p = os.path.join(d, "x.MAR"); open(p, "w").write(txt)
        return MA.validate_output(MA.parse_mar(p), n, card, ev)
    assert val(good)["ok"] is True
    assert "row sums" in " ".join(val(good.replace("0.387200 0.235900 0.376900", "0.400000 0.235900 0.376900"))["issues"])
    assert "point mass" in " ".join(val(good.replace("1.000000 0.000000", "0.999999 0.000001"))["issues"])
    assert "row count" in " ".join(val(good.replace("MAR\n3 ", "MAR\n2 ").rsplit(" 3 0.387200 0.235900 0.376900", 1)[0] + "\n")["issues"])
    assert "cardinality" in " ".join(val(good.replace("3 0.387200 0.235900 0.376900", "2 0.500000 0.500000"))["issues"])
    z = val("PR\n-inf (0.0e+00)\nSTATUS\nfalse: Inconsistent evidence or underflow\nMAR\n3 2 0.000000 0.000000 2 1.000000 0.000000 3 0.000000 0.000000 0.000000\n")
    assert z["consistent_evidence"] is False and z["ok"] is True          # rows are not judged for normalization when evidence is inconsistent
    assert val("PR\n0.1\n")["ok"] is False and "no MAR block" in val("PR\n0.1\n")["issues"]


@pytest.mark.skipif(not MERLIN_PRESENT, reason="the pinned Merlin binary is not installed on this host")
def test_mixed_arm_orchestrator_runs_one_mdi_selector_child_and_one_merlin_child_on_a_toy_packet():
    tmp = tempfile.mkdtemp()
    m = _chain_model(1)                                      # 9 + 1 variables, <= 4,096 assignments (2^9 * 3 = 1,536)
    ev = {3: 1}
    mp = _write_uai(m); model_bytes = open(mp, "rb").read(); evid_bytes = b"1 3 1\n"
    pk = os.path.join(tmp, "packet.zip")
    with zipfile.ZipFile(pk, "w") as z:
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai", model_bytes); z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.evid", evid_bytes)
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.MAR", b"REFERENCE MUST NEVER BE EXTRACTED BY THE ORCHESTRATOR\n")
    pinned = ["code/mdi/launch.py", "code/ext/supervise.py"]
    pin = {"commit": "synthetic", "code_tree_sha256": {rel: L.sha256_file(os.path.join(HERE, rel[5:])) for rel in pinned}}
    pp = os.path.join(tmp, "BUILD_PIN.json"); json.dump(pin, open(pp, "w"))
    mpin = MA.load_pin()
    input_dir = os.path.join(tmp, "inputs")
    b = {"engine_commit": "synthetic", "build_pin": {"path": os.path.relpath(pp, HERE), "sha256": L.sha256_file(pp)}, "input_dir": input_dir,
         "inputs": {"Tiny_1.uai": hashlib.sha256(model_bytes).hexdigest(), "Tiny_1.uai.evid": hashlib.sha256(evid_bytes).hexdigest()},
         "packet": {"sha256": L.sha256_file(pk)},
         "comparator": {"binary_sha256": mpin["binary"]["sha256"], "source_commit": mpin["source"]["commit"], "pin_file_sha256": L.sha256_file(MA.PIN_PATH)},
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]), "threads": int(K.RESOURCES["threads"]),
                           "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": 60.0, "durable_grace_s": 10.0, "allowance_s": 200.0, "session_cap_s": 1000.0, "previous_expenditure_s": {"earlier": 1.0},
         "order": [["Tiny_1", "selector"], ["Tiny_1", "merlin"]], "synthetic_control": True}
    bp = os.path.join(tmp, "bindings.json"); json.dump(b, open(bp, "w"))
    rd = os.path.join(tmp, "run")
    # a wrong packet hash refuses before anything is restored
    b_bad = dict(b, packet={"sha256": "0" * 64}); json.dump(b_bad, open(os.path.join(tmp, "bad.json"), "w"))
    with pytest.raises(L.Refused):
        CL.prepare(os.path.join(tmp, "run_bad"), b_bad, pin, os.path.join(tmp, "bad.json"), pp, pk, argv=["x"])
    assert not os.path.exists(input_dir)
    man, idir = CL.prepare(rd, b, pin, bp, pp, pk, argv=["x"])
    assert sorted(os.listdir(input_dir)) == ["Tiny_1.uai", "Tiny_1.uai.evid"]              # the reference is never restored
    assert man["full_order"] == b["order"] and man["comparator"]["binary_sha256"] == mpin["binary"]["sha256"] and man["packet"]["whole_file_verified"]
    led = json.load(open(os.path.join(rd, "LEDGER.json")))
    assert [c["label"] for c in led["cells"]] == ["Tiny_1_selector", "Tiny_1_merlin"] and all(c["status"] == "PENDING" for c in led["cells"])
    led = CL.run_cells(rd, b)
    assert [c["status"] for c in led["cells"]] == ["CONSUMED", "CONSUMED"], json.dumps(led, indent=1)[:1500]
    a_sel, a_mer = led["cells"][0]["attempts"][0], led["cells"][1]["attempts"][0]
    assert a_sel["class"] == "certified_fallback" and a_sel["arm_outcome"] == "CERTIFIED_FALLBACK_ONLY" and a_sel["kind_of_result"] == "certified_mdi"
    assert a_mer["class"] == "comparator_completed_native" and a_mer["arm_outcome"] == "COMPARATOR_COMPLETED" and a_mer["kind_of_result"] == "native_uncertified"
    rec = json.load(open(os.path.join(rd, a_mer["dir"], "comparator_Tiny_1_merlin.json")))
    assert rec["binary_sha256_at_run"] == mpin["binary"]["sha256"] and rec["validation"]["ok"] and rec["guarantee"].startswith("exact variable-elimination ALGORITHM")
    # the comparator's rows agree with the exact oracle within the frozen tolerance; MDI's publication is certified by its own checker
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    for v in pt:
        for s in range(m.card[v]):
            assert abs(Fr(rec["rows"][v][s]) - pt[v][s]) <= Fr(1, 10 ** 6)
    sel = json.load(open(os.path.join(rd, a_sel["dir"], "arm_Tiny_1_selector.json")))
    assert sel["pipeline"]["plan"]["selector"]["executed_route"] == "quotient" and sel["independently_verified"] is True
    assert L.charged_cells_s(led) == a_sel["charged_s"] + a_mer["charged_s"] > 0
