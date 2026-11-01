"""Launcher controls (post-r26): the six-cell launcher's MECHANICS with dummy
children and a tiny synthetic packet -- clean binding and supervision pass;
changed / missing input, changed pinned source and a reference file in the
input directory refuse BEFORE any child; a resumed STARTED cell is never
silently rerun; the repair balance rule and the session-cap stop charge and
stop as declared. No external model is planned or solved here."""
import os, sys, json, time, zipfile, tempfile, hashlib, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pytest
from mdi import launch as L

PY = sys.executable
DUMMY = r'''
import sys, os, json, time
problem, arm, adir, wall = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
label = "%s_%s" % (problem, arm)
mode = os.environ.get("DUMMY_MODE", "ok")
t0 = time.time()
if mode == "sleep":
    time.sleep(float(os.environ.get("DUMMY_SLEEP", "5")))
outcome = {"ok": "CERTIFIED_FALLBACK_ONLY", "stop": "RESOURCE_STOP", "crash": None, "sleep": "CERTIFIED_FALLBACK_ONLY"}[mode]
if mode == "crash":
    sys.exit(7)
el = time.time() - t0
json.dump({"problem": problem, "arm": arm, "label": label, "outcome": outcome, "reason": "dummy", "elapsed_s": el,
           "final_max_width": "1/200" if outcome.startswith("CERTIFIED") else None}, open(os.path.join(adir, "arm_%s.json" % label), "w"))
json.dump({"label": label, "outcome": outcome, "elapsed_s_including_durable_write": el, "wall_s": wall, "within_wall": el <= wall},
          open(os.path.join(adir, "arm_%s.receipt.json" % label), "w"))
'''


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _synthetic(tmp, cell_wall=2.0, allowance=None, session_cap=1000.0, previous=None):
    """A tiny synthetic packet (two fake inputs + a .MAR that must never be
    extracted), a BUILD_PIN over two real small files, and bindings."""
    inputs = {"Tiny_1.uai": b"MARKOV\n1\n2\n1\n1 0\n\n2\n 1 3\n", "Tiny_1.uai.evid": b"0\n"}
    pk = os.path.join(tmp, "packet.zip")
    with zipfile.ZipFile(pk, "w") as z:
        for n, data in inputs.items():
            z.writestr(L.PACKET_MEMBER_PREFIX + n, data)
        z.writestr(L.PACKET_MEMBER_PREFIX + "Tiny_1.uai.MAR", b"REFERENCE MUST NEVER BE EXTRACTED\n")
    pinned = ["code/mdi/launch.py", "code/ext/supervise.py"]
    pin = {"commit": "synthetic", "code_tree_sha256": {rel: L.sha256_file(os.path.join(HERE, rel[5:])) for rel in pinned}}
    pp = os.path.join(tmp, "BUILD_PIN.json"); json.dump(pin, open(pp, "w"))
    from mdi import config as K, budget as B
    order = [["Tiny_1", "baseline"], ["Tiny_1", "research"], ["Tiny_1", "baseline2"]]
    b = {"engine_commit": "synthetic", "build_pin": {"path": pp, "sha256": L.sha256_file(pp)},
         "input_dir": os.path.join(tmp, "inputs"),
         "inputs": {n: _sha(d) for n, d in inputs.items()},
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]),
                           "threads": int(K.RESOURCES["threads"]), "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": cell_wall, "allowance_s": (allowance if allowance is not None else cell_wall * len(order)),
         "session_cap_s": session_cap, "previous_expenditure_s": previous or {}, "order": order, "synthetic_control": True}
    bp = os.path.join(tmp, "bindings.json"); json.dump(b, open(bp, "w"))
    dummy = os.path.join(tmp, "dummy_child.py"); open(dummy, "w").write(DUMMY)
    return pk, pp, pin, bp, b, dummy


def _factory(dummy, mode="ok", sleep=None):
    def f(problem, arm, adir, wall):
        return [PY, dummy, problem, arm, adir, "%.3f" % wall]
    return f


def _sup(mode, sleep=None):
    """The REAL supervisor with the dummy's mode passed through the environment."""
    from ext import supervise as SV

    def run(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=None, label=""):
        e = dict(env or {}); e["DUMMY_MODE"] = mode
        if sleep is not None:
            e["DUMMY_SLEEP"] = str(sleep)
        return SV.run(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=e, label=label)
    return run


def test_clean_binding_and_supervision_pass():
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp)
    rd = os.path.join(tmp, "run")
    man, idir = L.prepare(rd, b, pin, bp, pp, packet=pk, argv=["launch", "control"])
    # only the two inputs were restored; the reference member was never extracted
    assert sorted(os.listdir(idir)) == ["Tiny_1.uai", "Tiny_1.uai.evid"]
    assert man["engine"]["pinned_files_verified"] == 2 and man["launcher"]["sha256"] == L.sha256_file(L.__file__)
    assert man["runtime"]["version_info"][:2] >= [3, 12] and man["supervisor"]["sha256"] and man["reference_files_opened"] is False
    led = L.run_cells(rd, b, cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    assert [c["status"] for c in led["cells"]] == ["CONSUMED"] * 3
    assert all(a["class"] == "certified_fallback" and a["supervisor"]["outcome"] == "COMPLETED" for c in led["cells"] for a in c["attempts"])
    assert L.charged_cells_s(led) > 0 and led["preparation_s"] > 0
    # every attempt has its own directory with the durable record and receipt
    for c in led["cells"]:
        a = c["attempts"][0]
        assert os.path.exists(os.path.join(rd, a["dir"], "arm_%s.json" % c["label"])) and os.path.exists(os.path.join(rd, a["dir"], "supervisor.log"))
    s = L.closeout(rd, b)
    assert len(s["cells"]) == 3 and s["closeout_s"] >= 0 and s["charged_cells_s"] == L.charged_cells_s(led)


def test_changed_or_missing_input_and_changed_source_refuse_before_any_child():
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp)
    rd = os.path.join(tmp, "run")
    # a changed input in the packet: hash mismatch refuses, nothing is written
    bad = dict(b); bad["inputs"] = dict(b["inputs"]); bad["inputs"]["Tiny_1.uai"] = "0" * 64
    with pytest.raises(L.Refused) as e:
        L.prepare(rd, bad, pin, bp, pp, packet=pk)
    assert "hashes" in str(e.value) and not os.path.exists(os.path.join(rd, "EXECUTION_MANIFEST.json"))
    assert any(f.startswith("REFUSED_") for f in os.listdir(rd))
    # a missing input (no packet restoration, empty directory)
    rd2 = os.path.join(tmp, "run2")
    with pytest.raises(L.Refused) as e:
        L.prepare(rd2, b, pin, bp, pp, packet=None)
    assert "missing" in str(e.value)
    # a reference file inside the solver input directory refuses
    L.restore_inputs(pk, b["input_dir"], b["inputs"])
    open(os.path.join(b["input_dir"], "Tiny_1.uai.MAR"), "w").write("ref\n")
    with pytest.raises(L.Refused) as e:
        L.prepare(os.path.join(tmp, "run3"), b, pin, bp, pp, packet=None)
    assert "reference" in str(e.value).lower()
    os.remove(os.path.join(b["input_dir"], "Tiny_1.uai.MAR"))
    # a changed pinned source hash refuses
    pin_bad = json.loads(json.dumps(pin)); pin_bad["code_tree_sha256"]["code/ext/supervise.py"] = "f" * 64
    with pytest.raises(L.Refused) as e:
        L.prepare(os.path.join(tmp, "run4"), b, pin_bad, bp, pp, packet=None)
    assert "pinned source" in str(e.value)
    # a changed frozen configuration refuses
    bc = json.loads(json.dumps(b)); bc["engine_limits"]["threads"] = 7
    with pytest.raises(L.Refused) as e:
        L.prepare(os.path.join(tmp, "run5"), bc, pin, bp, pp, packet=None)
    assert "configuration" in str(e.value)
    # running without a manifest refuses too
    with pytest.raises(L.Refused):
        L.run_cells(os.path.join(tmp, "run6"), b, cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    # no cell directory was ever created by any refusal
    assert not any(os.path.exists(os.path.join(tmp, r, "cells")) for r in ("run", "run2", "run3", "run4", "run5", "run6"))


def test_a_resumed_started_cell_is_never_silently_rerun_and_consumed_cells_are_skipped():
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp)
    rd = os.path.join(tmp, "run")
    L.prepare(rd, b, pin, bp, pp, packet=pk)
    led = L.load_ledger(rd, b)
    # simulate an interrupted first cell: STARTED persisted, no terminal
    led["cells"][0]["attempts"].append({"n": 1, "kind": "initial", "dir": "cells/x/attempt_1", "wall_granted_s": 2.0, "status": "STARTED", "started": "earlier"})
    led["cells"][0]["status"] = "STARTED"
    L._jdump(led, os.path.join(rd, "LEDGER.json"))
    led2 = L.run_cells(rd, b, cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    c0 = led2["cells"][0]
    assert c0["status"] == "INTERRUPTED" and len(c0["attempts"]) == 1 and c0["attempts"][0]["status"] == "INTERRUPTED"
    assert [c["status"] for c in led2["cells"][1:]] == ["CONSUMED", "CONSUMED"]
    # a second invocation reruns nothing: consumed cells are skipped, the interrupted one stays
    before = json.dumps(led2, sort_keys=True, default=str)
    led3 = L.run_cells(rd, b, cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    assert sum(len(c["attempts"]) for c in led3["cells"]) == 3 and led3["cells"][0]["status"] == "INTERRUPTED"
    assert json.dumps(led3, sort_keys=True, default=str) == before
    # only an explicit --repair runs the interrupted cell again, as THE one repair, inside the balance
    led4 = L.run_cells(rd, b, repair="Tiny_1_baseline", cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    assert led4["repair"]["used"] and led4["repair"]["label"] == "Tiny_1_baseline"
    assert len(led4["cells"][0]["attempts"]) == 2 and led4["cells"][0]["attempts"][1]["kind"] == "repair"
    assert led4["cells"][0]["attempts"][0]["status"] == "INTERRUPTED"          # the earlier attempt is retained, not overwritten
    # a second repair is refused
    led5 = L.run_cells(rd, b, repair="Tiny_1_research", cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    assert len(led5["cells"][1]["attempts"]) == 1 and led5["cells"][1]["repair_refused"][0]["reason"].startswith("the one repair was already used")


def test_repair_balance_rule_and_cumulative_stop_charge_and_stop_as_declared():
    # (a) a child past its wall: the REAL supervisor kills it; resource refusal; charged >= the wall
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp, cell_wall=2.0, allowance=6.0)
    b1 = json.loads(json.dumps(b)); b1["order"] = b["order"][:1]
    bp1 = os.path.join(tmp, "b1.json"); json.dump(b1, open(bp1, "w"))
    rd1 = os.path.join(tmp, "run1")
    L.prepare(rd1, b1, pin, bp1, pp, packet=pk)
    led1 = L.run_cells(rd1, b1, cmd_factory=_factory(dummy), supervisor=_sup("sleep", sleep=30))
    a = led1["cells"][0]["attempts"][0]
    assert a["supervisor"]["outcome"] == "TIMEOUT" and a["class"] == "resource_refusal" and a["charged_s"] >= 2.0
    # a ledger prepared under one order refuses another order
    with pytest.raises(L.Refused):
        L.run_cells(rd1, b, cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    # (b) the repair balance: cell 0 failed and charged a full wall; two initial cells unstarted reserve 2 x 2 s;
    #     balance = 6 - 2 - 4 = 0 -> the repair is refused and the failed outcome stands; the initial cells still get their FULL wall
    rd = os.path.join(tmp, "run")
    L.prepare(rd, b, pin, bp, pp, packet=pk)
    led = L.load_ledger(rd, b)
    led["cells"][0]["attempts"].append({"n": 1, "kind": "initial", "dir": "cells/Tiny_1_baseline/attempt_1", "wall_granted_s": 2.0, "status": "TERMINAL",
                                        "charged_s": 2.0, "class": "resource_refusal", "arm_outcome": None, "supervisor": {"outcome": "TIMEOUT"}})
    led["cells"][0]["status"] = "CONSUMED"
    os.makedirs(os.path.join(rd, "cells", "Tiny_1_baseline", "attempt_1"))
    L._jdump(led, os.path.join(rd, "LEDGER.json"))
    assert L.repair_balance_s(led, "Tiny_1_baseline") <= 0
    led_r = L.run_cells(rd, b, repair="Tiny_1_baseline", cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    c0 = led_r["cells"][0]
    assert len(c0["attempts"]) == 1 and not led_r["repair"]["used"] and "balance" in c0["repair_refused"][0]["reason"]
    assert c0["attempts"][0]["class"] == "resource_refusal"
    assert [c["status"] for c in led_r["cells"][1:]] == ["CONSUMED", "CONSUMED"]
    assert all(c["attempts"][0]["wall_granted_s"] == 2.0 for c in led_r["cells"][1:])
    # (c) a positive balance funds the repair with at most the balance, never more than a cell wall
    led_r["cells"][1]["attempts"][0]["charged_s"] = 0.1; led_r["cells"][2]["attempts"][0]["charged_s"] = 0.1
    L._jdump(led_r, os.path.join(rd, "LEDGER.json"))
    bal2 = L.repair_balance_s(led_r, "Tiny_1_baseline")
    assert abs(bal2 - (6.0 - 2.2)) < 1e-9
    led_r2 = L.run_cells(rd, b, repair="Tiny_1_baseline", cmd_factory=_factory(dummy), supervisor=_sup("ok"))
    rep = led_r2["cells"][0]["attempts"][1]
    assert rep["kind"] == "repair" and abs(rep["wall_granted_s"] - min(2.0, bal2)) < 1e-9 and led_r2["repair"]["used"]
    assert led_r2["cells"][0]["attempts"][0]["class"] == "resource_refusal"      # the earlier attempt is preserved
    # (d) session cap: with the cap nearly spent, an unstarted cell is marked NOT_RUN_CUMULATIVE_STOP and never run
    tmp2 = tempfile.mkdtemp()
    pk2, pp2, pin2, bp2, b2, dummy2 = _synthetic(tmp2, cell_wall=2.0, session_cap=100.0)
    rd2 = os.path.join(tmp2, "run")
    L.prepare(rd2, b2, pin2, bp2, pp2, packet=pk2)
    led2 = L.load_ledger(rd2, b2)
    # previous ledgers leave exactly one wall plus a sliver: the first cell starts, its charge drops the remainder below a wall
    led2["previous_expenditure_s"] = {"earlier": 100.0 - led2["preparation_s"] - 2.05}
    L._jdump(led2, os.path.join(rd2, "LEDGER.json"))
    assert 2.0 <= L.session_remaining_s(led2) < 2.1
    led2 = L.run_cells(rd2, b2, cmd_factory=_factory(dummy2), supervisor=_sup("ok"))
    statuses = [c["status"] for c in led2["cells"]]
    assert statuses[0] == "CONSUMED" and "NOT_RUN_CUMULATIVE_STOP" in statuses, statuses
    stopped = next(c for c in led2["cells"] if c["status"] == "NOT_RUN_CUMULATIVE_STOP")
    assert not stopped["attempts"] and stopped["cumulative_stop"]["needed_s"] == 2.0
    # (e) a crashing child is an implementation failure, charged, with the record retained
    tmp3 = tempfile.mkdtemp()
    pk3, pp3, pin3, bp3, b3, dummy3 = _synthetic(tmp3)
    b3one = json.loads(json.dumps(b3)); b3one["order"] = b3["order"][:1]
    bp3one = os.path.join(tmp3, "b3one.json"); json.dump(b3one, open(bp3one, "w"))
    rd3 = os.path.join(tmp3, "run")
    L.prepare(rd3, b3one, pin3, bp3one, pp3, packet=pk3)
    led3 = L.run_cells(rd3, b3one, cmd_factory=_factory(dummy3), supervisor=_sup("crash"))
    a3 = led3["cells"][0]["attempts"][0]
    assert a3["class"] == "implementation_failure" and a3["supervisor"]["outcome"] == "NONZERO_EXIT" and a3["charged_s"] > 0
    # (f) re-preparing the same run directory re-validates and keeps the ONE manifest; different bindings refuse
    man = L.prepare(rd3, b3one, pin3, bp3one, pp3, packet=None)[0]
    assert len(man.get("revalidations") or []) == 1
    with pytest.raises(L.Refused):
        L.prepare(rd3, b3, pin3, bp3, pp3, packet=None)


def test_cli_prepare_only_refuses_a_wrong_pin_hash_and_passes_clean():
    tmp = tempfile.mkdtemp()
    pk, pp, pin, bp, b, dummy = _synthetic(tmp)
    rd = os.path.join(tmp, "run")
    env = dict(os.environ, PYTHONPATH=HERE)
    out = subprocess.run([PY, "-m", "mdi.launch", rd, "--bindings", bp, "--packet", pk, "--prepare-only"], capture_output=True, text=True, env=env, cwd=HERE, timeout=300)
    assert out.returncode == 0 and "manifest written" in out.stdout, out.stdout + out.stderr
    man = json.load(open(os.path.join(rd, "EXECUTION_MANIFEST.json")))
    assert man["launcher"]["exact_command"][1:3] == ["-m", "mdi.launch"] and man["launcher"]["exact_command"][3] == rd and man["launcher_commit"]
    # a bindings file whose BUILD_PIN hash does not match refuses at the CLI
    bb = json.load(open(bp)); bb["build_pin"]["sha256"] = "0" * 64
    bp2 = os.path.join(tmp, "bindings_bad.json"); json.dump(bb, open(bp2, "w"))
    out2 = subprocess.run([PY, "-m", "mdi.launch", os.path.join(tmp, "run2"), "--bindings", bp2, "--packet", pk, "--prepare-only"], capture_output=True, text=True, env=env, cwd=HERE, timeout=300)
    assert out2.returncode != 0 and "does not hash" in (out2.stdout + out2.stderr)
