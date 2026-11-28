"""Bounded-completion repairs: ownership is reconciled by process INCARNATION, a valid terminal receipt closes ownership, unverified
identities are never signalled, and acceptance follows the FINAL cleanup.  Every probe cleans its own disposable processes."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path
from unittest.mock import patch

import psutil
import pytest

from pgm.runtime.attempts import kill_owned, owned_groups
from pgm.runtime import attempts
from pgm.runtime.supervise import group_members, kill_group_and_wait
from pgm import switchboard
from pgm.contracts import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT / "code"))


def _spawn_supervised_sleeper(tmp, seconds=30):
    ledger = Path(tmp) / "l.jsonl"
    p = subprocess.Popen([sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger), "--scope", "test", "--job", "orphan", "--timeout", str(seconds), "--",
                          sys.executable, "-c", "import time; time.sleep(%d)" % seconds], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)
    until = time.monotonic() + 5; sp = None
    while time.monotonic() < until and sp is None:
        if ledger.exists():
            rows = [json.loads(x) for x in ledger.read_text().splitlines() if '"SPAWNED"' in x]
            if rows: sp = rows[0]
        time.sleep(0.01)
    assert sp is not None, "supervisor never spawned"
    return p, ledger, sp


def _dead():
    d = subprocess.Popen([sys.executable, "-c", "pass"]); d.wait(); return d


def _ledger(tmp, spawned, receipt=None):
    ledger = Path(tmp) / "l.jsonl"
    rows = [dict(kind="START", jid="j", owner_dir=tmp), dict(kind="SPAWNED", jid="j", **spawned)]
    if receipt: rows.append(dict(kind="RECEIPT", jid="j", **receipt))
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows)); return ledger


def test_supervisor_killed_first_still_cleans_its_positively_identified_worker():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        p, ledger, sp = _spawn_supervised_sleeper(tmp); pgid = sp["pgid"]
        try:
            assert isinstance(sp.get("leader_create_time"), float), "the supervisor must record the leader incarnation"
            p.kill(); p.wait(timeout=2)
            assert group_members(pgid), "the worker should still be alive after the supervisor's death"
            record = kill_owned(p, ledger)
            assert record["supervisor_alive_at_entry"] is False and record["receipt_established"] is False
            assert not group_members(pgid) and record["killed"] == [sp["pid"]] and not record["unresolved"] and not record["identity_refused"]
        finally:
            kill_group_and_wait(pgid, wait_s=0.3)
            if p.poll() is None: p.kill()


def test_stale_registration_pointing_at_a_newer_process_is_not_signalled():
    """the normal direction of identifier reuse: a recorded OLDER incarnation, the group id now held by a newer unrelated process"""
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
        try:
            time.sleep(0.2); ct = psutil.Process(victim.pid).create_time()
            ledger = _ledger(tmp, dict(pid=victim.pid, pgid=victim.pid, leader_create_time=ct - 1000.0, spawn_utc="2000-01-01T00:00:00Z"))
            record = kill_owned(_dead(), ledger)
            assert victim.poll() is None, "a newer process reusing the recorded group id must never be signalled"
            assert not record["killed"] and record["identity_refused"] and record["identity_refused"][0]["pids"] == [victim.pid]
            assert record["unresolved"], "unverifiable ownership must leave the attempt unresolved (fail closed)"
        finally:
            victim.kill(); victim.wait()


def test_valid_terminal_receipt_closes_ownership_even_with_a_stale_live_registration():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
        try:
            time.sleep(0.2)
            ledger = _ledger(tmp, dict(pid=victim.pid, pgid=victim.pid, leader_create_time=psutil.Process(victim.pid).create_time(), spawn_utc="2000-01-01T00:00:00Z"),
                             receipt=dict(outcome="COMPLETED", cleanup_unresolved=False, group_empty_at_receipt=True, nested_groups_live_at_receipt=0))
            record = kill_owned(_dead(), ledger)
            assert victim.poll() is None and record["receipt_established"] and not record["killed"] and not record["groups"] and not record["unresolved"]
        finally:
            victim.kill(); victim.wait()


def test_missing_or_malformed_identity_fails_closed():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
        try:
            time.sleep(0.2)
            for spawned in (dict(pid=victim.pid, pgid=victim.pid, spawn_utc="2000-01-01T00:00:00Z"), dict(pid=victim.pid, pgid=victim.pid, leader_create_time="not-a-number", spawn_utc="2000-01-01T00:00:00Z")):
                record = kill_owned(_dead(), _ledger(tmp, spawned))
                assert victim.poll() is None and not record["killed"] and record["identity_refused"] and "incarnation" in record["identity_refused"][0]["reason"] and record["unresolved"]
        finally:
            victim.kill(); victim.wait()


def test_cleanup_poll_tolerates_a_process_disappearing_between_reads():
    """Exit can race either Process construction or status(), without turning cleanup into an exception."""
    pid = 123456789
    with patch.object(attempts.psutil, "Process", side_effect=psutil.NoSuchProcess(pid)):
        assert attempts._kill_pids_and_wait([pid], 0) == []

    class ExitingProcess:
        def __init__(self, process_pid): self.pid = process_pid
        def kill(self): pass
        def is_running(self): return True
        def status(self): raise psutil.NoSuchProcess(self.pid)

    with patch.object(attempts.psutil, "Process", ExitingProcess):
        assert attempts._kill_pids_and_wait([pid], 0) == []


def test_cleanup_poll_keeps_denied_inspection_unresolved():
    pid = 123456789
    with patch.object(attempts.psutil, "Process", side_effect=psutil.AccessDenied(pid)):
        assert attempts._kill_pids_and_wait([pid], 0) == [pid]

    class DeniedProcess:
        def __init__(self, process_pid): self.pid = process_pid
        def kill(self): pass
        def is_running(self): return True
        def status(self): raise psutil.AccessDenied(self.pid)

    with patch.object(attempts.psutil, "Process", DeniedProcess):
        assert attempts._kill_pids_and_wait([pid], 0) == [pid]


def test_callers_own_group_is_never_signalled():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        ledger = _ledger(tmp, dict(pid=os.getpid(), pgid=os.getpgrp(), leader_create_time=psutil.Process().create_time(), spawn_utc="2000-01-01T00:00:00Z"))
        record = kill_owned(_dead(), ledger)
        assert record["identity_refused"] and "own process group" in record["identity_refused"][0]["reason"] and not record["killed"]


def test_mixed_group_signals_only_verified_members():
    """a recorded group whose live members include an unverifiable one: the identified members are killed individually, the group is never signalled wholesale"""
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        leader = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']); time.sleep(20)"], start_new_session=True)
        try:
            time.sleep(0.6); members = group_members(leader.pid); assert len(members) >= 2
            # record an identity for the leader that does NOT match (older incarnation): the leader and its child are unverifiable -> nothing killed, unresolved reported
            record = kill_owned(_dead(), _ledger(tmp, dict(pid=leader.pid, pgid=leader.pid, leader_create_time=psutil.Process(leader.pid).create_time() - 500.0, spawn_utc="2000-01-01T00:00:00Z")))
            assert leader.poll() is None and not record["killed"] and set(record["identity_refused"][0]["pids"]) == set(members)
            # the correct incarnation: leader and child verified through the parent chain and killed individually
            record = kill_owned(_dead(), _ledger(tmp, dict(pid=leader.pid, pgid=leader.pid, leader_create_time=psutil.Process(leader.pid).create_time(), spawn_utc="2000-01-01T00:00:00Z")))
            assert set(record["killed"]) == set(members) and not record["unresolved"] and not group_members(leader.pid)
        finally:
            kill_group_and_wait(leader.pid, wait_s=0.3)
            if leader.poll() is None: leader.kill()


def test_valid_receipt_is_recognised_after_a_real_supervised_run():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        ledger = Path(tmp) / "l.jsonl"
        p = subprocess.run([sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger), "--scope", "test", "--job", "ok", "--timeout", "10", "--", sys.executable, "-c", "pass"], env=ENV, capture_output=True)
        assert p.returncode == 0
        groups, established, receipt = owned_groups(ledger)
        assert established and receipt["outcome"] == "COMPLETED" and groups and all(isinstance(g["create_time"], float) for g in groups.values())
        record = kill_owned(_dead(), ledger)
        assert record["receipt_established"] and not record["killed"] and not record["unresolved"]


# ---------------------------------------------------------------- acceptance follows the FINAL cleanup (the reviewer's injection, inverted)
def _fake_switchboard_run(cleanup_sequence):
    binding = {"model_sha256": "model", "evidence_sha256": "evidence"}
    class FakeProcess:
        returncode = 0; pid = 123456789
        def __init__(self, cmd, **kwargs):
            Path(cmd[cmd.index("--ledger") + 1]).write_text(json.dumps(dict(kind="RECEIPT", outcome="COMPLETED", cleanup_unresolved=False, group_empty_at_receipt=True, nested_groups_live_at_receipt=0)) + "\n")
            Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(dict(outcome="COMPLETE", binding=binding, positive_mass_witness=True, answers=[dict(variable=0, var=0, state=a, lo="1/2", hi="1/2", point="1/2", guarantee="EXACT") for a in range(2)], published=2, guarantee="EXACT", wall_s=.01)))
        def poll(self): return self.returncode
    calls = []
    def cleanup(*args, **kwargs):
        calls.append(1); return dict(unresolved=list(cleanup_sequence[min(len(calls), len(cleanup_sequence)) - 1]))
    choice = dict(backend="block", structural_route="auto", allowance_fraction=1); meta = dict(binding=binding, cards=[2], evidence={})
    with patch.object(attempts.subprocess, "Popen", FakeProcess), patch.object(attempts, "kill_owned", cleanup), patch.object(switchboard, "inspect_model", return_value=meta), patch.object(switchboard, "candidate_plan", return_value=[choice]):
        return switchboard.solve(InferenceRequest("/unused/model.uai")).to_dict(), len(calls)


def test_final_cleanup_failure_revokes_the_staged_candidate():
    result, calls = _fake_switchboard_run([[], [dict(pgid=123456789, pids=[123456789])]])        # first cleanup clean, FINAL cleanup unresolved
    assert calls == 2
    assert result["outcome"] != "COMPLETE" and result["published"] == 0 and all(r["guarantee"] == "NOT_PUBLISHED" for r in result["answers"]) and result["K"] == 2
    a = result["attempts"][0]; assert a["outcome"] == "CLEANUP_UNRESOLVED" and a["accepted"] is False and a["cleanup_final"]["unresolved"] and a["staged_candidate_rejected"]["published"] == 2


def test_successful_cleanup_path_publishes():
    result, calls = _fake_switchboard_run([[], []])
    assert calls == 2 and result["outcome"] == "COMPLETE" and result["published"] == 2 and result["attempts"][0]["accepted"] is True


def test_first_cleanup_failure_also_refuses_and_keeps_the_inventory():
    result, calls = _fake_switchboard_run([[dict(pgid=1, pids=[1])], []])
    assert result["outcome"] != "COMPLETE" and result["published"] == 0 and result["K"] == 2 and result["attempts"][0]["outcome"] == "CLEANUP_UNRESOLVED"
