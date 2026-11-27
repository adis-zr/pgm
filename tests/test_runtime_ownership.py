"""Repair R1: durable ownership is reconciled even when the supervisor died first; identity-checked; unresolved refuses success."""
import json, os, subprocess, sys, tempfile, time
from pathlib import Path

import pytest

from pgm.runtime.attempts import kill_owned, owned_groups
from pgm.runtime.supervise import group_members, kill_group_and_wait

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT / "code"))


def _spawn_supervised_sleeper(tmp, seconds=30):
    ledger = Path(tmp) / "l.jsonl"
    p = subprocess.Popen([sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger), "--scope", "test", "--job", "orphan", "--timeout", str(seconds), "--",
                          sys.executable, "-c", "import time; time.sleep(%d)" % seconds], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)
    until = time.monotonic() + 5; pgid = None
    while time.monotonic() < until and pgid is None:
        if ledger.exists():
            sp = [json.loads(x) for x in ledger.read_text().splitlines() if '"SPAWNED"' in x]
            if sp: pgid = sp[0]["pgid"]
        time.sleep(0.01)
    assert pgid is not None, "supervisor never spawned"
    return p, ledger, pgid


def test_supervisor_killed_first_still_cleans_its_registered_worker():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        p, ledger, pgid = _spawn_supervised_sleeper(tmp)
        try:
            p.kill(); p.wait(timeout=2)
            assert group_members(pgid), "the worker should still be alive after the supervisor's death"
            record = kill_owned(p, ledger)
            assert record["supervisor_alive_at_entry"] is False and record["receipt_established"] is False
            assert not group_members(pgid) and record["killed"] and not record["unresolved"]
        finally:
            kill_group_and_wait(pgid, wait_s=0.3)
            if p.poll() is None: p.kill()


def test_reused_group_id_older_than_the_recorded_spawn_is_refused_not_signalled():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], start_new_session=True)
        try:
            time.sleep(0.2)
            ledger = Path(tmp) / "l.jsonl"
            future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))      # a record claiming a spawn AFTER the victim existed = a reused pgid
            ledger.write_text(json.dumps(dict(kind="START", jid="j", owner_dir=tmp)) + "\n" + json.dumps(dict(kind="SPAWNED", jid="j", pid=victim.pid, pgid=victim.pid, spawn_utc=future)) + "\n")
            dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
            record = kill_owned(dead, ledger)
            assert victim.poll() is None, "an unrelated older process group must never be signalled"
            assert record["identity_refused"] and record["identity_refused"][0]["pgid"] == victim.pid and not record["killed"]
        finally:
            victim.kill(); victim.wait()


def test_callers_own_group_is_never_signalled():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        ledger = Path(tmp) / "l.jsonl"
        ledger.write_text(json.dumps(dict(kind="START", jid="j", owner_dir=tmp)) + "\n" + json.dumps(dict(kind="SPAWNED", jid="j", pid=os.getpid(), pgid=os.getpgrp(), spawn_utc="2000-01-01T00:00:00Z")) + "\n")
        dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
        record = kill_owned(dead, ledger)
        assert record["identity_refused"] and "own process group" in record["identity_refused"][0]["reason"] and not record["killed"]


def test_valid_receipt_is_recognised():
    with tempfile.TemporaryDirectory(prefix="pgm-own-") as tmp:
        ledger = Path(tmp) / "l.jsonl"
        p = subprocess.run([sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger), "--scope", "test", "--job", "ok", "--timeout", "10", "--", sys.executable, "-c", "pass"], env=ENV, capture_output=True)
        assert p.returncode == 0
        groups, established, receipt = owned_groups(ledger)
        assert established and receipt["outcome"] == "COMPLETED" and groups
        dead = subprocess.Popen([sys.executable, "-c", "pass"]); dead.wait()
        record = kill_owned(dead, ledger)
        assert record["receipt_established"] and not record["killed"] and not record["unresolved"]
