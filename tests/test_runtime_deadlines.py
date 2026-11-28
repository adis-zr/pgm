"""Deadline coordination without extending the work allowance or hiding cleanup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from pgm import switchboard
from pgm.contracts import InferenceRequest, InferenceResult
from pgm.runtime import attempts


ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def test_expired_absolute_supervisor_deadline_never_launches(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    marker = tmp_path / "must-not-exist"
    deadline = time.monotonic() - 1
    result = subprocess.run(
        [sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger),
         "--scope", "test", "--job", "expired", "--timeout", "60",
         "--deadline-monotonic", repr(deadline), "--", sys.executable,
         "-c", "from pathlib import Path; Path(%r).write_text('launched')" % str(marker)],
        env=ENV, capture_output=True, text=True, timeout=5,
    )
    records = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert result.returncode != 0 and not marker.exists()
    assert not any(r["kind"] == "SPAWNED" for r in records)
    receipt = records[-1]
    assert receipt["kind"] == "RECEIPT" and receipt["outcome"] == "TIMEOUT_KILL"
    assert receipt["deadline_monotonic"] == deadline
    assert receipt["group_empty_at_receipt"] and not receipt["cleanup_unresolved"]


def test_attempt_forwards_one_absolute_deadline_to_supervisor_and_worker(tmp_path, monkeypatch):
    seen = []

    class FinishedProcess:
        returncode = 1
        pid = 123456789

        def __init__(self, command, **kwargs):
            seen.append(command)

        def poll(self):
            return self.returncode

    monkeypatch.setattr(attempts.subprocess, "Popen", FinishedProcess)
    monkeypatch.setattr(attempts, "kill_owned", lambda *a, **k: dict(unresolved=[]))
    deadline = time.monotonic() + 5
    choice = dict(backend="block", structural_route="auto", allowance_fraction=1)
    result, record = attempts.run_attempt(choice, InferenceRequest(tmp_path / "unused"),
                                           deadline, tmp_path, 0)
    command = seen[0]
    supervisor, worker = command[:command.index("--")], command[command.index("--")+1:]
    assert float(supervisor[supervisor.index("--deadline-monotonic")+1]) == deadline
    assert float(worker[worker.index("--deadline")+1]) == deadline
    assert result is None and record["accepted"] is False


def test_ownership_identity_does_not_parse_obsolete_wall_clock_fields(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("\n".join(map(json.dumps, [
        dict(kind="START", jid="owned"),
        dict(kind="SPAWNED", jid="owned", pid=123, pgid=123,
             leader_create_time=17.0, spawn_utc="irrelevant diagnostic"),
        dict(kind="RECEIPT", jid="owned", cleanup_unresolved=False,
             group_empty_at_receipt=True, nested_groups_live_at_receipt=0),
    ])) + "\n")

    def obsolete_parse(*args):
        raise AssertionError("wall-clock parsing is not an ownership proof")

    monkeypatch.setattr(attempts.time, "strptime", obsolete_parse)
    groups, established, _ = attempts.owned_groups(ledger)
    assert established and groups[123]["create_time"] == 17.0


def test_late_api_fallback_inventory_is_prepared_before_final_sample(tmp_path, monkeypatch):
    binding = dict(model_sha256="model", evidence_sha256="evidence")
    meta = dict(binding=binding, cards=[2], evidence={})
    choice = dict(backend="block", structural_route="auto", allowance_fraction=1)
    candidate = dict(outcome="COMPLETE", binding=binding, positive_mass_witness=True,
                     answers=[dict(variable=0, var=0, state=a, lo="1/2", hi="1/2",
                                   point="1/2", guarantee="EXACT") for a in range(2)])
    monkeypatch.setattr(switchboard, "inspect_model", lambda *a, **k: meta)
    monkeypatch.setattr(switchboard, "candidate_plan", lambda *a, **k: [choice])
    monkeypatch.setattr(switchboard, "run_attempt", lambda *a, **k:
                        (candidate, dict(backend="block", outcome="COMPLETE", wall_s=0)))
    samples = []
    allocations = []
    empty = switchboard._empty

    def clock():
        samples.append(1)
        return 102.0 if len(samples) == 4 else 100.0

    def prepare_empty(inventory):
        allocations.append(len(samples))
        return empty(inventory)

    monkeypatch.setattr(switchboard, "_empty", prepare_empty)
    monkeypatch.setattr(switchboard.time, "monotonic", clock)
    result = switchboard.solve(InferenceRequest(tmp_path / "unused", budget=1)).to_dict()
    assert allocations == [3] and len(samples) == 4
    assert result["outcome"] == "DEADLINE" and result["published"] == 0
    assert result["wall_s"] == 2 and result["hard_deadline_respected"] is False
    assert len(result["answers"]) == 2


def test_cli_keeps_api_timestamp_when_its_own_publication_is_late(tmp_path, monkeypatch):
    from pgm import __main__ as cli

    result = dict(outcome="COMPLETE", guarantee="EXACT", published=2,
                  max_published_radius=0, hard_deadline_respected=True, wall_s=0.8,
                  answers=[dict(var=0, variable=0, state=a, lo="1/2", hi="1/2",
                                point="1/2", guarantee="EXACT") for a in range(2)])
    monkeypatch.setattr(cli, "infer", lambda *a, **k: InferenceResult(result))
    ticks = iter((100.0, 100.0, 100.99, 101.1, 101.1))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    output = tmp_path / "result.json"
    cli.main(["--input", str(tmp_path / "unused"), "--output", str(output), "--budget", "1"])
    actual = json.loads(output.read_text())
    assert actual["api_wall_s"] == 0.8 and actual["api_hard_deadline_respected"] is True
    assert actual["outcome"] == "DEADLINE" and actual["published"] == 0
    assert actual["wall_s"] > 1 and actual["hard_deadline_respected"] is False
