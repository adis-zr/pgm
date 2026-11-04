"""Controls of the comparator glue (qualification pass 4 Nov 2026, REPAIRED the same day after the overseer's findings):
adapter output validation (fixtures), outcome precedence, the same-process-group child (no orphan under an outer stop),
charges persisted before child artifacts are parsed, no silent zero for unknown expenditure on restart, glue hash
enforcement, and the orchestrator toy run with ONE real MDI selector child and ONE real Merlin child under the CONFIGURED
tiny-invocation caps (10 s wall, 1 GiB RSS; <= 4,096 joint states). Disclosure: the toy run of commit cf50af4 used a 60 s
wall and the 8 GiB engine cap -- a deviation from the configured 10 s / 1 GiB caps, kept in history, corrected here."""
import os, sys, json, zipfile, hashlib, tempfile, time, subprocess, signal
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "tests"))
from fractions import Fraction as Fr
import pytest
from mdi import model as M, oracle as O, launch as L, budget as B, config as K
from ext import supervise as SV
from ext.comparator import merlin_adapter as MA, comparison_launch as CL
from test_mdi_quotient_pilot import _chain_model
from mdi.matrix import _write_uai

MERLIN_PRESENT = os.path.exists(os.path.expanduser(MA.load_pin()["binary"]["path"]))
GOOD = "PR\n0.69 (2.0e+00)\nSTATUS\ntrue: Consistent evidence\nMAR\n3 2 0.500000 0.500000 2 1.000000 0.000000 3 0.387200 0.235900 0.376900\n"


def _val(txt, n=3, card=(2, 2, 3), ev={1: 0}):
    d = tempfile.mkdtemp(); p = os.path.join(d, "x.MAR"); open(p, "w").write(txt)
    return MA.validate_output(MA.parse_mar(p), n, list(card), dict(ev))


def test_adapter_output_validation_rejects_every_named_fault_and_keeps_the_status_ambiguity():
    assert _val(GOOD) == {"ok": True, "issues": [], "consistent_evidence": True, "zero_evidence_or_underflow": False}
    bad = {
        "row sums": GOOD.replace("0.387200 0.235900 0.376900", "0.400000 0.235900 0.376900"),
        "point mass": GOOD.replace("1.000000 0.000000", "0.999999 0.000001"),
        "row count": "PR\n0.69\nSTATUS\ntrue: Consistent evidence\nMAR\n2 2 0.500000 0.500000 2 1.000000 0.000000\n",
        "cardinality": GOOD.replace("3 0.387200 0.235900 0.376900", "2 0.500000 0.500000"),
        "missing STATUS": "PR\n0.69\nMAR\n3 2 0.500000 0.500000 2 1.000000 0.000000 3 0.387200 0.235900 0.376900\n",
        "unrecognized STATUS": GOOD.replace("true: Consistent evidence", "maybe: who knows"),
        "non-decimal or non-finite": GOOD.replace("0.500000 0.500000", "nan nan"),
        "non-decimal or non-finite": GOOD.replace("0.500000 0.500000", "inf -inf"),
        "outside [0, 1]": GOOD.replace("0.500000 0.500000", "1.500000 -0.500000"),
        "truncated or malformed": "PR\n0.69\nSTATUS\ntrue: Consistent evidence\nMAR\n3 2 0.500000\n",
        "malformed MAR": "PR\n0.69\nSTATUS\ntrue: Consistent evidence\nMAR\nx\n",
        "missing MAR": "PR\n0.69\nSTATUS\ntrue: Consistent evidence\n",
        "trailing tokens": GOOD + "0.1 0.2\n",
    }
    for key, txt in bad.items():
        r = _val(txt)
        assert r["ok"] is False and any(key.split()[0].lower() in i.lower() for i in r["issues"]), (key, r["issues"])
    # STATUS false: zero evidence OR underflow (ambiguous, kept so); rows not judged for normalization but still range-checked
    z = _val("PR\n-inf (0.0e+00)\nSTATUS\nfalse: Inconsistent evidence or underflow\nMAR\n3 2 0.000000 0.000000 2 1.000000 0.000000 3 0.000000 0.000000 0.000000\n")
    assert z["ok"] is True and z["consistent_evidence"] is False and z["zero_evidence_or_underflow"] is True
    z2 = _val("PR\n-inf (0.0e+00)\nSTATUS\nfalse: Inconsistent evidence or underflow\nMAR\n3 2 1.500000 0.000000 2 1.000000 0.000000 3 0.000000 0.000000 0.000000\n")
    assert z2["ok"] is False and "outside" in " ".join(z2["issues"])


def test_outcome_precedence_outer_stops_and_nonzero_exits_never_become_completion():
    completed_rec = {"outcome": "COMPARATOR_COMPLETED", "child": {"outcome": "COMPLETED", "elapsed_s": 0.5}, "merlin_process_elapsed_s": 0.5}
    assert CL._classify_comparator({"outcome": "NONZERO_EXIT", "returncode": 3, "elapsed_s": 1.0}, completed_rec, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "LAUNCH_FAILURE", "returncode": 127, "elapsed_s": 0.1}, completed_rec, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "TIMEOUT", "elapsed_s": 70.0}, completed_rec, 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "MEMORY_STOP", "elapsed_s": 5.0}, completed_rec, 60.0)[0] == "comparator_memory_stop"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, None, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, dict(completed_rec, child={"outcome": "TIMEOUT"}), 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 61.0}, completed_rec, 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, completed_rec, 60.0)[0] == "comparator_completed_native"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, {"outcome": "COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW", "reason": "STATUS false"}, 60.0)[0] == "comparator_zero_evidence_or_underflow"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, {"outcome": "COMPARATOR_OUTPUT_INVALID", "reason": "nan"}, 60.0)[0] == "comparator_failure"


def test_same_process_group_child_is_reaped_by_an_outer_timeout_and_the_complete_termination_is_charged():
    """Synthetic processes only: a fake comparator that forks a grandchild and sleeps; the OUTER supervisor's 1.5 s
    deadline must terminate the adapter's child runner AND every descendant (the pre-repair adapter put the child in a
    new session, so the outer killpg could not reach it: reproduced in glue_repair/before_cf50af4.out)."""
    tmp = tempfile.mkdtemp()
    fake = os.path.join(tmp, "fake_merlin.sh"); open(fake, "w").write("#!/bin/sh\nsleep 300 &\necho $! > %s/grandchild.pid\nsleep 300\n" % tmp); os.chmod(fake, 0o755)
    drv = os.path.join(tmp, "drive.py")
    open(drv, "w").write("import sys; sys.path.insert(0, %r)\nfrom ext.comparator import merlin_adapter as MA\n"
                         "MA.run_child_same_group([%r], cwd=%r, log_path=%r, deadline_s=60, mem_limit_kib=1 << 20)\n" % (HERE, fake, tmp, tmp + "/inner.log"))
    sup = SV.run([sys.executable, drv], cwd=tmp, log_path=tmp + "/outer.log", deadline_s=1.5, mem_limit_kib=1 << 20, label="outer")
    time.sleep(0.5)
    assert sup["outcome"] == "TIMEOUT" and sup["elapsed_s"] >= 1.5          # the complete termination is charged to the outer wall
    gp = int(open(tmp + "/grandchild.pid").read().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(gp, 0)
    left = subprocess.run(["pgrep", "-f", "sleep 300"], capture_output=True, text=True).stdout.split()
    for p in left:
        try: os.kill(int(p), signal.SIGKILL)
        except Exception: pass
    assert left == [], "descendants survived the outer stop: %s" % left
    # the inner runner's own limits also kill the child's descendants (synthetic RSS stop: 1 KiB limit)
    rec = MA.run_child_same_group([fake], cwd=tmp, log_path=tmp + "/inner2.log", deadline_s=60, mem_limit_kib=1)
    time.sleep(0.3)
    assert rec["outcome"] == "MEMORY_STOP" and rec["same_process_group_as_adapter"] is True
    left2 = subprocess.run(["pgrep", "-f", "sleep 300"], capture_output=True, text=True).stdout.split()
    for p in left2:
        try: os.kill(int(p), signal.SIGKILL)
        except Exception: pass
    assert left2 == []


def _toy_bindings(tmp, model_bytes, evid_bytes, pk, pp, order, extra=None):
    mpin = MA.load_pin()
    b = {"engine_commit": "synthetic", "build_pin": {"path": os.path.relpath(pp, HERE), "sha256": L.sha256_file(pp)}, "input_dir": os.path.join(tmp, "inputs"),
         "inputs": {"Tiny_1.uai": hashlib.sha256(model_bytes).hexdigest(), "Tiny_1.uai.evid": hashlib.sha256(evid_bytes).hexdigest()},
         "packet": {"sha256": L.sha256_file(pk)},
         "comparator": {"binary_sha256": mpin["binary"]["sha256"], "source_commit": mpin["source"]["commit"], "pin_file_sha256": L.sha256_file(MA.PIN_PATH)},
         "glue": CL.glue_hashes(),
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]), "threads": int(K.RESOURCES["threads"]),
                           "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": 10.0, "durable_grace_s": 2.0, "allowance_s": 40.0, "session_cap_s": 1000.0, "previous_expenditure_s": {"earlier": 1.0},
         "order": order, "synthetic_control": True, "synthetic_control_mem_cap_bytes": 1 << 30}
    b.update(extra or {})
    return b


def _toy_packet(tmp):
    m = _chain_model(1); ev = {3: 1}
    mp = _write_uai(m); model_bytes = open(mp, "rb").read(); evid_bytes = b"1 3 1\n"
    pk = os.path.join(tmp, "packet.zip")
    with zipfile.ZipFile(pk, "w") as z:
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai", model_bytes); z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.evid", evid_bytes)
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.MAR", b"REFERENCE MUST NEVER BE EXTRACTED\n")
    pinned = ["code/mdi/launch.py", "code/ext/supervise.py"]
    pin = {"commit": "synthetic", "code_tree_sha256": {rel: L.sha256_file(os.path.join(HERE, rel[5:])) for rel in pinned}}
    pp = os.path.join(tmp, "BUILD_PIN.json"); json.dump(pin, open(pp, "w"))
    return m, ev, model_bytes, evid_bytes, pk, pin, pp


def test_glue_hashes_are_enforced_on_preparation_and_revalidation_and_the_packet_hash_first():
    tmp = tempfile.mkdtemp(); m, ev, mb, eb, pk, pin, pp = _toy_packet(tmp)
    b = _toy_bindings(tmp, mb, eb, pk, pp, [["Tiny_1", "merlin"]]); bp = os.path.join(tmp, "b.json"); json.dump(b, open(bp, "w"))
    # the packet's whole-file hash is tested FIRST: nothing is restored before it
    b_pk = dict(b, packet={"sha256": "0" * 64})
    with pytest.raises(L.Refused) as ei2:
        CL.prepare(os.path.join(tmp, "run_pk"), b_pk, pin, bp, pp, pk, argv=["x"])
    assert "the packet" in str(ei2.value) and not os.path.exists(b["input_dir"])
    b_bad = dict(b, glue=dict(b["glue"], adapter_sha256="0" * 64))
    with pytest.raises(L.Refused) as ei:
        CL.prepare(os.path.join(tmp, "run_bad"), b_bad, pin, bp, pp, pk, argv=["x"])
    assert "glue hash mismatch" in str(ei.value) and "adapter_sha256" in str(ei.value)
    assert not os.path.exists(os.path.join(tmp, "run_bad", "EXECUTION_MANIFEST.json"))      # refused before the manifest
    man, idir = CL.prepare(os.path.join(tmp, "run_ok"), b, pin, bp, pp, pk, argv=["x"])
    assert man["orchestrator"]["verified_against_bindings"] and man["adapter"]["verified_against_bindings"] and man["merlin_pin_file_sha256"] == b["glue"]["merlin_pin_sha256"]
    # revalidation before a run: a changed glue hash refuses the run itself
    with pytest.raises(L.Refused):
        CL.run_cells(os.path.join(tmp, "run_ok"), b_bad)


def test_charges_persist_before_child_artifacts_are_parsed_and_unknown_expenditure_is_never_zero(monkeypatch):
    """A child that exits 0 but leaves a TRUNCATED record: the attempt's measured charge and outcome are durable, the
    cell is classified as a failure with the read fault named, and a restart neither retries nor treats an interrupted
    attempt's unknown expenditure as zero (it is bounded by the kill deadline in the allowance / session tests)."""
    tmp = tempfile.mkdtemp(); m, ev, mb, eb, pk, pin, pp = _toy_packet(tmp)
    b = _toy_bindings(tmp, mb, eb, pk, pp, [["Tiny_1", "merlin"], ["Tiny_1", "merlin"]], {"allowance_s": 30.0})
    b["order"] = [["Tiny_1", "merlin"], ["Tiny_2", "merlin"]]; b["inputs"]["Tiny_2.uai"] = b["inputs"]["Tiny_1.uai"]; b["inputs"]["Tiny_2.uai.evid"] = b["inputs"]["Tiny_1.uai.evid"]
    with zipfile.ZipFile(pk, "a") as z:
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_2.uai", mb); z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_2.uai.evid", eb)
    b["packet"]["sha256"] = L.sha256_file(pk); bp = os.path.join(tmp, "b.json"); json.dump(b, open(bp, "w"))
    rd = os.path.join(tmp, "run"); CL.prepare(rd, b, pin, bp, pp, pk, argv=["x"])
    # a fake adapter child: sleeps 0.3 s, writes a truncated record, exits 0
    fake = os.path.join(tmp, "fake_adapter.py")
    open(fake, "w").write("import sys, time, os\ntime.sleep(0.3)\nopen(os.path.join(sys.argv[3], 'comparator_%s.json' % sys.argv[4]), 'w').write('{\"outcome\": \"COMPARATOR_COMPLETED\", \"child\"')\n")
    real_run = SV.run

    def fake_run(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=None, label=""):
        cmd2 = [sys.executable, fake] + cmd[3:] if "merlin_adapter" in " ".join(cmd) else cmd
        return real_run(cmd2, cwd, log_path, deadline_s, mem_limit_kib, env=env, label=label)
    monkeypatch.setattr(SV, "run", fake_run)
    led = CL.run_cells(rd, b)
    a = led["cells"][0]["attempts"][0]
    assert a["status"] == "TERMINAL" and a["charged_s"] >= 0.3 and a["supervisor"]["outcome"] == "COMPLETED"
    assert a["class"] == "comparator_failure" and a["record_read_faults"] and "JSONDecodeError" in a["record_read_faults"][0]
    assert a["arm_outcome"] is None and a["component_elapsed_s"] is None
    # restart semantics: an attempt left without a terminal classification is INTERRUPTED, never rerun, and its unknown charge is
    # bounded by the kill deadline (not zero) in the conservative allowance test
    led["cells"][1]["attempts"] = [{"n": 1, "kind": "initial", "dir": "cells/Tiny_2_merlin/attempt_1", "wall_granted_s": 10.0, "supervisor_kill_deadline_s": 12.0,
                                    "command": ["x"], "status": "STARTED", "started": "now"}]
    led["cells"][1]["status"] = "STARTED"
    os.makedirs(os.path.join(rd, "cells", "Tiny_2_merlin", "attempt_1"), exist_ok=True)
    json.dump(led, open(os.path.join(rd, "LEDGER.json"), "w"), indent=1)
    assert CL.conservative_charged_s(led) == pytest.approx(a["charged_s"] + 12.0)
    led2 = CL.run_cells(rd, b)
    assert led2["cells"][1]["status"] == "INTERRUPTED" and len(led2["cells"][1]["attempts"]) == 1 and led2["unknown_expenditure_bound_s"] == pytest.approx(12.0)
    assert L.charged_cells_s(led2) < CL.conservative_charged_s(led2)         # the pinned sum would read the unknown as zero; the orchestrator does not


@pytest.mark.skipif(not MERLIN_PRESENT, reason="the pinned Merlin binary is not installed on this host")
def test_mixed_arm_orchestrator_toy_run_under_the_configured_caps_one_mdi_child_and_one_merlin_child():
    tmp = tempfile.mkdtemp(); m, ev, mb, eb, pk, pin, pp = _toy_packet(tmp)
    b = _toy_bindings(tmp, mb, eb, pk, pp, [["Tiny_1", "selector"], ["Tiny_1", "merlin"]]); bp = os.path.join(tmp, "b.json"); json.dump(b, open(bp, "w"))
    rd = os.path.join(tmp, "run")
    man, idir = CL.prepare(rd, b, pin, bp, pp, pk, argv=["x"])
    assert sorted(os.listdir(b["input_dir"])) == ["Tiny_1.uai", "Tiny_1.uai.evid"]
    led = CL.run_cells(rd, b)
    assert [c["status"] for c in led["cells"]] == ["CONSUMED", "CONSUMED"], json.dumps(led, indent=1)[:1500]
    a_sel, a_mer = led["cells"][0]["attempts"][0], led["cells"][1]["attempts"][0]
    assert a_sel["wall_granted_s"] == 10.0 and a_sel["supervisor_kill_deadline_s"] == 12.0 and a_mer["supervisor"]["mem_limitation"]
    assert a_sel["class"] == "certified_fallback" and a_sel["kind_of_result"] == "certified_mdi" and a_sel["charged_s"] <= 10.0
    assert a_mer["class"] == "comparator_completed_native" and a_mer["arm_outcome"] == "COMPARATOR_COMPLETED" and a_mer["kind_of_result"] == "native_uncertified"
    assert a_mer["component_elapsed_s"] is not None and a_mer["component_elapsed_s"] <= a_mer["charged_s"]        # a component, never added
    rec = json.load(open(os.path.join(rd, a_mer["dir"], "comparator_Tiny_1_merlin.json")))
    assert rec["child"]["same_process_group_as_adapter"] is True and rec["child"]["descendants_after_exit"] == [] and "elapsed_s_including_durable_write" not in rec
    Z, pt = O.exact_all_marginals(M.restrict(m, ev))
    for v in pt:
        for s in range(m.card[v]):
            assert abs(Fr(rec["rows"][v][s]) - pt[v][s]) <= Fr(1, 10 ** 6)
    sel = json.load(open(os.path.join(rd, a_sel["dir"], "arm_Tiny_1_selector.json")))
    blk = sel["pipeline"]["plan"]["selector"]
    # under the CONFIGURED 10 s tiny-invocation cap the frozen selector policy (window 20 s + dense forecast + 30 s margin) must
    # skip its probes: the cell certifies on the dense route with the skip recorded -- the orchestration path is what this
    # toy exercises; the selector's transformed routes are exercised by tests/test_mdi_selector.py under longer walls
    assert blk["executed_route"] == "dense" and blk["skipped"].startswith("insufficient remaining wall") and sel["independently_verified"] is True
