"""Controls for the census-pass harness (adp/census/): supervisor receipts survive a kill; diagnostic counters mean what they say on toy
inputs with known counts; instrumentation does not change the inference result."""
from __future__ import annotations
import sys, os, json, subprocess, tempfile, time, signal
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import numpy as np
from mdi import model as M, arith as A
from adp import source as SRC, engine as EN, oracle as O
from adp.census import diag_cell as DC

PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)


def test_supervisor_start_record_and_finally_receipt_survive_kill(tmp_path):
    L = str(tmp_path / "L.jsonl")
    # (a) a normal job: START then RECEIPT, same jid, COMPLETED
    subprocess.run([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "ok", "--", PY, "-c", "print(1)"], cwd=HERE, env=ENV, capture_output=True)
    rows = [json.loads(l) for l in open(L)]; assert [r["kind"] for r in rows] == ["START", "SPAWNED", "RECEIPT"] and len({r["jid"] for r in rows}) == 1 and rows[-1]["outcome"] == "COMPLETED"   # (repaired supervisor: SPAWNED after a successful launch)
    # (b) a timeout: the child is killed by its RECORDED pgid; receipt TIMEOUT_KILL with wall ~ timeout + grace
    subprocess.run([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "slow", "--timeout", "0.5", "--", PY, "-c", "import time; time.sleep(30)"], cwd=HERE, env=ENV, capture_output=True)
    rows = [json.loads(l) for l in open(L)]; r = rows[-1]; assert r["kind"] == "RECEIPT" and r["job"] == "slow" and r["outcome"] == "TIMEOUT_KILL" and r["wall_s"] < 8
    # (c) the SUPERVISOR itself is SIGTERMed: the START record is already on disk and the finally path still writes a receipt
    p = subprocess.Popen([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "killed_sup", "--timeout", "60", "--", PY, "-c", "import time; time.sleep(60)"], cwd=HERE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5); os.kill(p.pid, signal.SIGTERM); p.wait(timeout=20)
    rows = [json.loads(l) for l in open(L)]; starts = [r for r in rows if r["kind"] == "START" and r["job"] == "killed_sup"]; sp = [r for r in rows if r["kind"] == "SPAWNED" and r["job"] == "killed_sup"]; rcpt = [r for r in rows if r["kind"] == "RECEIPT" and r["job"] == "killed_sup"]
    assert len(starts) == 1 and len(sp) == 1 and len(rcpt) == 1 and rcpt[0]["outcome"].startswith("SUPERVISOR_SIGNAL") and rcpt[0]["wall_s"] < 10
    # the child's process group is gone
    import psutil
    time.sleep(0.3); assert not any(q.pid == sp[0]["pid"] and q.is_running() for q in psutil.process_iter())


def _toy():
    # chain A-B-C (binary) with a 3-state D attached to B: known program sizes under the default order
    facs = [M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1, 4), Fr(3, 4), Fr(1, 2), Fr(1, 2)], origin=0), M.Factor(scope=(1, 2), card=(2, 2), table=[Fr(3, 5), Fr(2, 5), Fr(1, 5), Fr(4, 5)], origin=1), M.Factor(scope=(1, 3), card=(2, 3), table=[Fr(1, 10), Fr(3, 10), Fr(3, 5), Fr(1, 2), Fr(1, 4), Fr(1, 4)], origin=2)]
    m = M.Model(nvars=4, card=[2, 2, 2, 3], factors=facs); m.validate(); return m


def test_node_metrics_have_known_values_on_a_toy():
    m = _toy(); cfg = dict(EN.DEFAULTS, rules=[]); R = SRC.Reduced(m, {}); R.reduce([]); P = EN.Program(R, cfg); met = DC.node_metrics(P)
    by_v = {x["v"]: x for x in met}
    # every node's planned core = response-class product <= raw boundary product; bag rows = core x |D_v|
    for x in met:
        assert x["response_class_product"] == x["planned_core_entries"] <= x["raw_boundary_domain_product"] and x["planned_bag_rows"] == x["planned_core_entries"] * x["dom_v"]
    # the root has empty scope: raw boundary product 1, core 1
    root = [x for x in met if x["parent"] is None]; assert len(root) == 1 and root[0]["raw_boundary_domain_product"] == 1 and root[0]["planned_core_entries"] == 1
    # the leaf eliminations of A, C and D each have a single input factor over (v, B): single-input elimination, boundary {B}, raw product 2
    for v in (0, 2, 3):
        if v in by_v and by_v[v]["parent"] is not None:
            assert by_v[v]["single_input_elimination"] and by_v[v]["raw_boundary_domain_product"] == 2 and by_v[v]["scope"] == [1]
    # the node eliminating B consumes three messages with pairwise-disjoint (empty) boundary scopes: rank-1 volume = |D_B| x sum of input sizes
    b = by_v[1]; assert b["inputs_have_disjoint_boundary_scopes"] and b["rank1_terms_volume_if_disjoint"] == 2 * sum(P.nodes[r[1]].size if r[0] == "M" else len(P.fac[r[1]].table) for r in b["inputs"])
    # per-axis class accounting: classes_out <= min raw; finest input named
    for x in met:
        for ax in x["axes"]:
            assert ax["classes_out"] <= ax["raw"] and all(k <= ax["raw"] for _, k in ax["classes_per_input"]) and ax["finest_inputs"]


def test_observed_executor_matches_plain_executor_and_counts_referenced_entries():
    for seed in range(60):
        m, ev = O.gen(seed); Z, N = O.brute(m, ev)
        for cfg in (dict(EN.DEFAULTS), dict(EN.DEFAULTS, rules=[]), dict(EN.DEFAULTS, rules=[], batched=False)):
            R = SRC.Reduced(m, ev); R.reduce(cfg["rules"])
            if R.zero_proof:
                continue
            P = EN.Program(R, cfg)
            class _Obs:
                def __init__(self):
                    self.ev = []
                def node_event(self, e):
                    self.ev.append(e)
                def snapshot(self, *a, **k):
                    pass
            obs = _Obs(); X1 = DC.ObservedExecutor(P, 64, cfg, obs=obs); X1.forward(); X1.backward(); e1, r1, _ = X1.enclosures()
            P2 = EN.Program(R, cfg); X2 = EN.Executor(P2, 64, cfg); X2.forward(); X2.backward(); e2, r2, _ = X2.enclosures()
            assert e1 == e2                                                       # exact Fractions: identical enclosures with and without observation
            assert {k: A.exact_fr(z) for k, (z, _) in r1.items()} == {k: A.exact_fr(z) for k, (z, _) in r2.items()}
            fw = [e for e in obs.ev if e["phase"] == "forward"]; bw = [e for e in obs.ev if e["phase"] == "backward"]
            assert len(fw) == len(P.nodes) == len(bw)
            # referenced child entries: a dense parent references every entry of a dense child it looks up (all classes) -> referenced <= child_entries; never more
            for e in fw:
                for cid, rr in e["referenced_child_entries"].items():
                    assert 0 <= rr["referenced"] <= rr["child_entries"]
            # a dense parent of a dense child with identity views references ALL of the child's entries (every class tuple appears in the bag)
            for e in fw:
                nd = P.nodes[e["nid"]]
                if e["executed_format"] == "dense" and all(len(nd.views[w].reps) == len(P.dom[w]) for w in nd.scope):
                    for cid, rr in e["referenced_child_entries"].items():
                        ch = P.nodes[int(cid)]
                        if X1.cores.get(ch.nid) is not None and all(len(ch.views[w].reps) == len(P.dom[w]) for w in ch.scope) and rr["child_entries"] == ch.size:
                            assert rr["referenced"] == rr["child_entries"]


def test_diag_cell_persists_plan_before_numerics_and_certifies_like_the_plain_cell(tmp_path):
    m = _toy(); d = str(tmp_path); mp = os.path.join(d, "m.uai"); O.write_uai(mp, m, {}); o1 = os.path.join(d, "plain"); o2 = os.path.join(d, "diag")
    subprocess.run([PY, "-m", "adp.cell", mp, mp + ".evid", o1, "60", "{}"], cwd=HERE, env=ENV, capture_output=True); subprocess.run([PY, "-m", "adp.census.diag_cell", mp, mp + ".evid", o2, "60", "{}"], cwd=HERE, env=ENV, capture_output=True)
    r1 = json.load(open(os.path.join(o1, "cell.json"))); r2 = json.load(open(os.path.join(o2, "cell.json"))); assert r1["status"] == r2["status"] == "CERTIFIED"
    assert open(os.path.join(o1, "output.MAR")).read() == open(os.path.join(o2, "output.MAR")).read()
    assert os.path.exists(os.path.join(o2, "plan_record.json")) and os.path.exists(os.path.join(o2, "reduced_record.json")) and os.path.exists(os.path.join(o2, "nodes.jsonl")) and os.path.exists(os.path.join(o2, "progress.json"))
    plan = json.load(open(os.path.join(o2, "plan_record.json"))); assert len(plan["node_metrics"]) == len(plan["nodes"]) == 4
    ev = [json.loads(l) for l in open(os.path.join(o2, "nodes.jsonl"))]; assert sum(1 for e in ev if e["phase"] == "forward") == 4 and sum(1 for e in ev if e["phase"] == "backward") == 4
    assert r2["reduced_hash"] == json.load(open(os.path.join(o1, "certificate.json")))["reduced"]["reduced_hash"]


# ---------------------------------------------------------------------------- review of 8 Nov 2026: prospective supervisor repair controls
def _rows(L):
    return [json.loads(l) for l in open(L)] if os.path.exists(L) else []


def test_review_supervisor_absent_executable_writes_start_and_launch_failed_receipt(tmp_path):
    L = str(tmp_path / "L.jsonl")
    r = subprocess.run([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "absent", "--timeout", "2", "--", str(tmp_path / "nonexistent_executable")], cwd=HERE, env=ENV, capture_output=True, text=True)
    rows = _rows(L); kinds = [x["kind"] for x in rows]
    assert kinds == ["START", "RECEIPT"], kinds
    assert rows[1]["outcome"] == "LAUNCH_FAILED" and rows[1]["jid"] == rows[0]["jid"] and rows[1]["pid"] is None and "FileNotFoundError" in (rows[1]["launch_error"] or "") and r.returncode == 1


def test_review_supervisor_successful_launch_has_start_spawned_receipt_in_order(tmp_path):
    L = str(tmp_path / "L.jsonl")
    subprocess.run([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "ok", "--timeout", "10", "--", PY, "-c", "print(7)"], cwd=HERE, env=ENV, capture_output=True)
    rows = _rows(L); assert [x["kind"] for x in rows] == ["START", "SPAWNED", "RECEIPT"] and len({x["jid"] for x in rows}) == 1
    assert rows[1]["pid"] == rows[2]["pid"] and rows[1]["pgid"] == rows[2]["pgid"] and rows[2]["outcome"] == "COMPLETED" and rows[2]["returncode"] == 0
    assert "pid" not in rows[0]                                                  # the START is written before any child exists


def test_review_supervisor_timeout_and_interruption_around_launch(tmp_path):
    import psutil
    L = str(tmp_path / "L.jsonl")
    subprocess.run([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "slow", "--timeout", "0.5", "--", PY, "-c", "import time; time.sleep(30)"], cwd=HERE, env=ENV, capture_output=True)
    rows = _rows(L); r = rows[-1]; assert r["kind"] == "RECEIPT" and r["outcome"] == "TIMEOUT_KILL" and r["wall_s"] < 8 and not psutil.pid_exists(rows[-2]["pid"]) or not any(q.pid == rows[-2]["pid"] and q.is_running() for q in psutil.process_iter())
    # SIGTERM to the supervisor immediately after launch: START + SPAWNED + RECEIPT, child gone
    p = subprocess.Popen([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "interrupted", "--timeout", "60", "--", PY, "-c", "import time; time.sleep(60)"], cwd=HERE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.8); os.kill(p.pid, signal.SIGTERM); p.wait(timeout=20)
    rows = [x for x in _rows(L) if x["job"] == "interrupted"]; kinds = [x["kind"] for x in rows]
    assert kinds == ["START", "SPAWNED", "RECEIPT"], kinds
    assert rows[2]["outcome"].startswith("SUPERVISOR_SIGNAL") and rows[2]["wall_s"] < 10
    time.sleep(0.3); assert not any(q.pid == rows[1]["pid"] and q.is_running() for q in psutil.process_iter())
    # SIGTERM BEFORE the launch can complete (race): START exists; if the child was never spawned the receipt says so; never a live orphan
    p = subprocess.Popen([PY, "-m", "adp.census.supervise", "--ledger", L, "--scope", "t", "--job", "early", "--timeout", "60", "--", PY, "-c", "import time; time.sleep(60)"], cwd=HERE, env=ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.05); os.kill(p.pid, signal.SIGTERM); p.wait(timeout=20)
    rows = [x for x in _rows(L) if x["job"] == "early"]; assert rows[0]["kind"] == "START" and rows[-1]["kind"] == "RECEIPT"
    spawned = [x for x in rows if x["kind"] == "SPAWNED"]
    if spawned:
        time.sleep(0.3); assert not any(q.pid == spawned[0]["pid"] and q.is_running() for q in psutil.process_iter())
    if rows[-1]["pid"] is not None:                                             # second review: the receipt pid must be checked even without a SPAWNED record
        assert rows[-1]["pgid"] == rows[-1]["pid"] and rows[-1]["cleanup_unresolved"] is False
        time.sleep(0.3); assert not any(q.pid == rows[-1]["pid"] and q.is_running() for q in psutil.process_iter())


def test_review_frozen_supervisor_reproduces_the_launch_gap(tmp_path):
    """The BEFORE copy (commit 580e0fbe) on an absent executable: no START, no RECEIPT (the gap the review found)."""
    before = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "review_2026-11-08", "supervisor_controls", "supervise_BEFORE_580e0fbe.py")
    if not os.path.exists(before):
        import pytest; pytest.skip("before-copy not present")
    L = str(tmp_path / "Lb.jsonl")
    r = subprocess.run([PY, before, "--ledger", L, "--scope", "t", "--job", "absent", "--timeout", "2", "--", str(tmp_path / "nonexistent_executable")], cwd=HERE, env=ENV, capture_output=True, text=True)
    assert r.returncode != 0 and "FileNotFoundError" in r.stderr and not os.path.exists(L)


# ---------------------------------------------------------------------------- second review of 8 Nov 2026: deterministic launch-boundary controls (real psutil, real signals)
TRACE_RUNNER = r"""
import sys, os, signal, time, runpy
target, marker, ledger, mode, job = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
src = open(target).read().splitlines(); line = next(i for i, t in enumerate(src, 1) if marker in t)
cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
sys.argv = [target, "--ledger", ledger, "--scope", "t", "--job", job, "--timeout", "60", "--stdout", os.devnull, "--stderr", os.devnull, "--"] + cmd
fired = False
def tracer(frame, event, arg):
    global fired
    if not fired and event == "line" and os.path.realpath(frame.f_code.co_filename) == os.path.realpath(target) and frame.f_lineno == line:
        fired = True
        if mode == "signal":
            os.kill(os.getpid(), signal.SIGTERM)                       # a REAL SIGTERM delivered exactly at the marked line (before it executes)
        elif mode == "spawned_write_failure":
            orig = frame.f_globals["append"]
            def failing(path, rec):
                if rec["kind"] == "SPAWNED":
                    raise OSError("injected SPAWNED append failure")
                return orig(path, rec)
            frame.f_globals["append"] = failing
            proc = frame.f_locals["proc"]; w = proc.wait
            def slow_wait(*a, **k):
                time.sleep(0.2); return w(*a, **k)
            proc.wait = slow_wait
    return tracer
sys.settrace(tracer)
runpy.run_path(target, run_name="__main__")
"""


def _trace_run(tmp_path, target, marker, mode, job, timeout):
    runner = tmp_path / "trace_runner.py"; runner.write_text(TRACE_RUNNER); L = str(tmp_path / ("L_%s.jsonl" % job))
    t = time.monotonic(); r = subprocess.run([PY, str(runner), target, marker, L, mode, job], cwd=HERE, env=ENV, capture_output=True, text=True, timeout=timeout); outer = time.monotonic() - t
    return _rows(L), r, outer


def _alive(pid):
    import psutil
    try:
        q = psutil.Process(pid); return q.is_running() and q.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _killpg_quiet(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


SUP = os.path.join(HERE, "adp", "census", "supervise.py")


def test_review2_sigterm_between_popen_and_identity_is_deferred_child_killed_wall_after_cleanup(tmp_path):
    """SIGTERM delivered after Popen returned and BEFORE the group identity is assigned (the reviewer's reproduced window): the repaired supervisor
    defers it, records SPAWNED, then kills and reaps the owned child and charges the wall AFTER cleanup; no live child survives the exit."""
    rows, r, outer = _trace_run(tmp_path, SUP, "group identity without a syscall", "signal", "boundary_sigterm", timeout=30)
    kinds = [x["kind"] for x in rows]; assert kinds == ["START", "SPAWNED", "RECEIPT"], kinds
    rc = rows[-1]; pid = rc["pid"]
    try:
        assert rc["outcome"] == "SUPERVISOR_SIGNAL_15" and rc["pending_signal"] == 15 and rc["returncode"] == -9 and rc["cleanup_unresolved"] is False
        assert rc["pgid"] == pid == rows[1]["pid"] and pid is not None
        assert not _alive(pid), "child survived the supervisor exit"
        assert rc["wall_s"] < 5 and outer < 15, (rc["wall_s"], outer)        # the before-version waited 2 x 10 s and charged only 10 of them
    finally:
        _killpg_quiet(pid)


def test_review2_sigterm_before_launch_is_deferred_across_the_start_record_no_child(tmp_path):
    """SIGTERM at the START write: deferred until the attempt record is durable, then acted upon before any launch; START + RECEIPT, pid None."""
    rows, r, outer = _trace_run(tmp_path, SUP, '{"kind": "START"', "signal", "prelaunch_sigterm", timeout=30)
    kinds = [x["kind"] for x in rows]; assert kinds == ["START", "RECEIPT"], kinds
    rc = rows[-1]; assert rc["outcome"] == "SUPERVISOR_SIGNAL_15" and rc["pid"] is None and rc["pgid"] is None and rc["cleanup_unresolved"] is False and rc["wall_s"] < 5


def test_review2_spawned_write_failure_after_launch_kills_child_and_charges_cleanup(tmp_path):
    """The SPAWNED append fails (injected) after a successful launch: the owned child is killed and reaped BEFORE the receipt; the charged wall
    includes the (slowed, 0.2 s) reap; the outcome names the error; the receipt pid/pgid identify the child even though no SPAWNED record exists."""
    rows, r, outer = _trace_run(tmp_path, SUP, "group identity without a syscall", "spawned_write_failure", "spawned_write_failure", timeout=30)
    kinds = [x["kind"] for x in rows]; assert kinds == ["START", "RECEIPT"], kinds
    rc = rows[-1]; pid = rc["pid"]
    try:
        assert rc["outcome"] == "SUPERVISOR_ERROR_AFTER_LAUNCH" and "injected SPAWNED append failure" in (rc["error"] or "") and rc["returncode"] == -9
        assert rc["pgid"] == pid and pid is not None and rc["cleanup_unresolved"] is False and rc["wall_s"] >= 0.2
        assert not _alive(pid)
    finally:
        _killpg_quiet(pid)


def test_review2_before_copy_3414b222_reproduces_the_launch_boundary_gap(tmp_path):
    """The BEFORE copy (commit 3414b222): the same SIGTERM between Popen and `pgid = os.getpgid(...)` leaves the child ALIVE at supervisor exit
    and charges ~10 s of a ~20 s exit (the reviewer's finding, reproduced here with real signals / real psutil). Costs ~20 s."""
    before = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08", "review_2026-11-08", "supervisor_controls", "supervise_BEFORE_3414b222.py")
    if not os.path.exists(before):
        import pytest; pytest.skip("before-copy not present")
    rows, r, outer = _trace_run(tmp_path, before, "pgid = os.getpgid(proc.pid)", "signal", "before_boundary_sigterm", timeout=60)
    rc = rows[-1]; pid = rc["pid"]
    try:
        assert [x["kind"] for x in rows] == ["START", "RECEIPT"] and rc["outcome"] == "SUPERVISOR_SIGNAL_15" and rc["pgid"] is None and rc["returncode"] is None
        assert _alive(pid), "expected the BEFORE copy to leave the child alive (the gap)"
        assert 9 < rc["wall_s"] < 12 and outer > 18, (rc["wall_s"], outer)   # charged 10 s, exited after ~20 s
    finally:
        _killpg_quiet(pid)


def test_review2_ledger_tool_charges_unresolved_cleanup_at_max_permitted(tmp_path):
    """A RECEIPT with cleanup_unresolved (the child could not be reaped) is open-ended: charged at max(wall, max permitted) and listed unresolved."""
    from adp.census import run as R
    D = str(tmp_path); L = os.path.join(D, "CENSUS_LEDGER.jsonl")
    rows = [{"kind": "START", "jid": "a|1", "scope": "s", "job": "a", "max_permitted_charge_s": 24.0}, {"kind": "RECEIPT", "jid": "a|1", "scope": "s", "job": "a", "wall_s": 1.0, "outcome": "COMPLETED", "cleanup_unresolved": False},
            {"kind": "START", "jid": "b|1", "scope": "s", "job": "b", "max_permitted_charge_s": 24.0}, {"kind": "RECEIPT", "jid": "b|1", "scope": "s", "job": "b", "wall_s": 10.5, "outcome": "CLEANUP_UNRESOLVED", "cleanup_unresolved": True},
            {"kind": "START", "jid": "c|1", "scope": "s", "job": "c", "max_permitted_charge_s": 64.0}]
    with open(L, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    total, by_scope, unresolved = R.charged(D)
    assert total == 1.0 + 24.0 + 64.0 and sorted(u["job"] for u in unresolved) == ["b", "c"] and [u for u in unresolved if u["job"] == "b"][0]["cleanup_unresolved"] is True
