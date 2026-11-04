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
        "non-decimal or non-finite nan": GOOD.replace("0.500000 0.500000", "nan nan"),
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
    completed_rec = {"outcome": "COMPARATOR_COMPLETED", "child": {"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 0.5}, "merlin_process_elapsed_s": 0.5, "validation": {"ok": True, "consistent_evidence": True, "zero_evidence_or_underflow": False}}
    assert CL._classify_comparator({"outcome": "NONZERO_EXIT", "returncode": 3, "elapsed_s": 1.0}, completed_rec, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "LAUNCH_FAILURE", "returncode": 127, "elapsed_s": 0.1}, completed_rec, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "TIMEOUT", "elapsed_s": 70.0}, completed_rec, 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "MEMORY_STOP", "elapsed_s": 5.0}, completed_rec, 60.0)[0] == "comparator_memory_stop"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, None, 60.0)[0] == "comparator_failure"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, dict(completed_rec, child={"outcome": "TIMEOUT"}), 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 61.0}, completed_rec, 60.0)[0] == "comparator_timeout"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, completed_rec, 60.0)[0] == "comparator_completed_native"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, dict(completed_rec, outcome="COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW", reason="STATUS false", validation={"ok": True, "consistent_evidence": False, "zero_evidence_or_underflow": True}), 60.0)[0] == "comparator_zero_evidence_or_underflow"
    assert CL._classify_comparator({"outcome": "COMPLETED", "returncode": 0, "elapsed_s": 1.0}, {"outcome": "COMPARATOR_OUTPUT_INVALID", "reason": "nan"}, 60.0)[0] == "comparator_failure"


@pytest.mark.parametrize("outer_stop", ["TIMEOUT", "MEMORY_STOP", "INNER_MEMORY_STOP"])
def test_same_process_group_child_is_terminated_by_outer_timeout_and_rss(outer_stop, monkeypatch):
    """Real synthetic child/grandchild; outer RSS stop uses an injected sampler.
    No external inference. The frozen supervisor waits for its direct adapter,
    while group SIGKILL reaches its child and grandchild. Subsequent PID polling
    verifies disappearance; it is not claimed to be included in charged wall.
    """
    tmp = tempfile.mkdtemp()
    fake = os.path.join(tmp, "fake_merlin.py")
    gpfile = os.path.join(tmp, "grandchild.pid")
    cpfile = os.path.join(tmp, "child.pid")
    grand = "import os,time; open(%r, 'w').write(str(os.getpid())); time.sleep(8)" % gpfile
    open(fake, "w").write("import os,sys,subprocess,time\nopen(%r,'w').write(str(os.getpid()))\n"
                           "subprocess.Popen([sys.executable,'-c',%r])\ntime.sleep(8)\n" % (cpfile, grand))
    drv = os.path.join(tmp, "drive.py")
    driver = "import sys,json; sys.path.insert(0,%r)\nfrom ext.comparator import merlin_adapter as MA\n" % HERE
    inner_mem = 1 << 20
    if outer_stop == "INNER_MEMORY_STOP":
        driver += "from ext import supervise as SV\nimport os\n"
        driver += "SV._tree_rss_kib=lambda pid: (2,2) if os.path.exists(%r) else (0,1)\n" % gpfile
        driver += "MA._descendants=lambda pid: [int(open(%r).read())] if os.path.exists(%r) else []\n" % (gpfile, gpfile)
        inner_mem = 1
    driver += "r=MA.run_child_same_group([sys.executable,%r],cwd=%r,log_path=%r,deadline_s=8,mem_limit_kib=%d)\n" % (fake, tmp, tmp + "/inner.log", inner_mem)
    driver += "json.dump(r,open(%r,'w'))\n" % (tmp + "/inner.json")
    open(drv, "w").write(driver)
    if outer_stop == "MEMORY_STOP":
        # Trigger the outer path only after both descendant PIDs are durable.
        monkeypatch.setattr(SV, "_tree_rss_kib", lambda pid: ((1 << 20) + 1, 3) if os.path.exists(gpfile) else (0, 1))
    pids = []
    try:
        sup = SV.run([sys.executable, drv], cwd=tmp, log_path=tmp + "/outer.log",
                     deadline_s=1.0 if outer_stop == "TIMEOUT" else 3.0,
                     mem_limit_kib=1 << 20, label="outer")
        assert sup["outcome"] == ("COMPLETED" if outer_stop == "INNER_MEMORY_STOP" else outer_stop) and sup["elapsed_s"] < 10.0
        if outer_stop == "INNER_MEMORY_STOP":
            assert json.load(open(tmp + "/inner.json"))["outcome"] == "MEMORY_STOP"
        pids = [int(open(p).read()) for p in (cpfile, gpfile)]
        def remains(pid):
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
        # SIGKILL delivery/OS reaping may finish just after the adapter exits.
        end = time.monotonic() + 1.0
        while any(remains(p) for p in pids) and time.monotonic() < end:
            time.sleep(0.01)
        assert not any(remains(p) for p in pids), "descendants survived the outer stop"
    finally:
        for pf in (cpfile, gpfile):
            if os.path.exists(pf):
                try:
                    os.kill(int(open(pf).read()), signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _toy_bindings(tmp, model_bytes, evid_bytes, pk, pp, order, extra=None):
    mpin = MA.load_pin()
    b = {"engine_commit": "synthetic", "build_pin": {"path": os.path.relpath(pp, HERE), "sha256": L.sha256_file(pp)}, "input_dir": os.path.join(tmp, "inputs"),
         "inputs": {"Tiny_1.uai": hashlib.sha256(model_bytes).hexdigest(), "Tiny_1.uai.evid": hashlib.sha256(evid_bytes).hexdigest()},
         "packet": {"sha256": L.sha256_file(pk)},
         "comparator": {"binary_sha256": mpin["binary"]["sha256"], "source_commit": mpin["source"]["commit"], "pin_file_sha256": L.sha256_file(MA.PIN_PATH)},
         "glue": CL.glue_hashes(),
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]), "threads": int(K.RESOURCES["threads"]),
                           "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": 10.0, "durable_grace_s": 0.0, "allowance_s": 40.0, "session_cap_s": 1000.0, "previous_expenditure_s": {"earlier": 1.0},
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


@pytest.fixture
def synthetic_comparator_pin(monkeypatch, tmp_path):
    """Preparation-only controls need no installed or executed Merlin binary."""
    binary = tmp_path / "not_executed_binary"
    binary.write_bytes(b"synthetic identity fixture; never executed\n")
    pin = {"binary": {"path": str(binary), "sha256": L.sha256_file(binary)},
           "source": {"commit": "synthetic"}, "command": "not executed",
           "guarantee": "synthetic fixture", "structural_mechanism": "synthetic fixture"}
    pp = tmp_path / "SYNTHETIC_COMPARATOR_PIN.json"
    pp.write_text(json.dumps(pin))
    monkeypatch.setattr(MA, "PIN_PATH", str(pp))
    return pin


def test_glue_hashes_are_enforced_on_preparation_and_revalidation_and_the_packet_hash_first(synthetic_comparator_pin):
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


def test_charges_persist_before_child_artifacts_are_parsed_and_unknown_expenditure_is_never_zero(monkeypatch, synthetic_comparator_pin):
    """A child that exits 0 but leaves a TRUNCATED record: the attempt's measured charge and outcome are durable, the
    cell is classified as a failure with the read fault named. An unknown interrupted charge
    stops resumption and leaves the total and carry-forward unavailable; a deadline is not a measurement."""
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
    # unresolved: a kill deadline is not a measurement or a safe elapsed-time bound
    led["cells"][1]["attempts"] = [{"n": 1, "kind": "initial", "dir": "cells/Tiny_2_merlin/attempt_1", "wall_granted_s": 10.0, "supervisor_kill_deadline_s": 10.0,
                                    "command": ["x"], "status": "STARTED", "started": "now"}]
    led["cells"][1]["status"] = "STARTED"
    os.makedirs(os.path.join(rd, "cells", "Tiny_2_merlin", "attempt_1"), exist_ok=True)
    json.dump(led, open(os.path.join(rd, "LEDGER.json"), "w"), indent=1)
    with pytest.raises(L.Refused, match="unresolved expenditure"):
        CL.conservative_charged_s(led)
    # The unresolved attempt must refuse before any new child can be spawned.
    def forbidden_run(*args, **kwargs):
        pytest.fail("a child was spawned despite unresolved expenditure")
    monkeypatch.setattr(SV, "run", forbidden_run)
    with pytest.raises(L.Refused, match="unresolved expenditure"):
        CL.run_cells(rd, b)
    led2 = json.load(open(os.path.join(rd, "LEDGER.json")))
    assert led2["cells"][1]["status"] == "INTERRUPTED" and len(led2["cells"][1]["attempts"]) == 1
    assert led2["cells"][0]["attempts"][0]["charged_s"] == a["charged_s"]
    assert led2["accounting_status"] == "UNRESOLVED" and not led2["carry_forward_available"]
    assert "unknown_expenditure_bound_s" not in led2
    summary = CL.closeout(rd, b)
    assert summary["charged_cells_s"] is None and summary["session_remaining_s"] is None
    assert summary["allowance_remaining_s"] is None and not summary["carry_forward_available"]
    assert summary["known_charged_cells_s"] == a["charged_s"]


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
    assert a_sel["wall_granted_s"] == 10.0 and a_sel["supervisor_kill_deadline_s"] == 10.0 and a_mer["supervisor"]["mem_limitation"]
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
