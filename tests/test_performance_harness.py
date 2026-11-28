"""Campaign guards are separate from the inference correctness tests."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

HERE = Path(__file__).resolve().parents[1] / "benchmarks/external"
sys.path.insert(0, str(HERE))
import run_performance as campaign


def test_reverses_paired_order_without_results():
    frozen = dict(tasks=[dict(name="alpha"), dict(name="beta")], arms=list(campaign.ARMS), replicates=[1, 2])
    jobs = list(campaign.schedule(frozen))
    assert len(jobs) == 24
    for name in ("alpha", "beta"):
        first = [arm for task, arm, rep in jobs if task["name"] == name and rep == 1]
        second = [arm for task, arm, rep in jobs if task["name"] == name and rep == 2]
        assert first == list(reversed(second))
        assert set(first) == set(campaign.ARMS)


def test_receipt_must_be_unique(tmp_path):
    ledger = tmp_path / "receipts.jsonl"
    with pytest.raises(RuntimeError, match="exactly one"):
        campaign.terminal_receipt(ledger, "cell")
    record = dict(kind="RECEIPT", job="cell", jid="one")
    ledger.write_text(json.dumps(record) + "\n")
    assert campaign.terminal_receipt(ledger, "cell")["jid"] == "one"
    with ledger.open("a") as stream:
        stream.write(json.dumps(dict(record, jid="two")) + "\n")
    with pytest.raises(RuntimeError, match="found 2"):
        campaign.terminal_receipt(ledger, "cell")


def test_resume_never_relaunches_an_unreceipted_attempt(tmp_path):
    task = dict(name="alpha", model="model", evidence="evidence", model_sha256="m", evidence_sha256="e")
    config = dict(runtime_python=str(Path(sys.executable).absolute()), tasks=[task], arms=["PGM_ACCEPTED"], replicates=[1])
    (tmp_path / "FREEZE.json").write_text(json.dumps(config))
    folder = tmp_path / "runs/alpha__PGM_ACCEPTED__r1"
    folder.mkdir(parents=True)
    (folder / "launch.json").write_text("{}")
    with patch.object(campaign, "verify_identity"), patch.object(campaign, "sha", side_effect=lambda p: "m" if p == "model" else "e"), patch.object(campaign, "supervised") as launch:
        with pytest.raises(RuntimeError, match="exactly one"):
            campaign.run(SimpleNamespace(run_dir=tmp_path, max_cells=None))
        launch.assert_not_called()


def test_completed_cell_cannot_hide_wrong_receipt_identity(tmp_path):
    task = dict(name="alpha")
    config = dict(runtime_python=str(Path(sys.executable).absolute()), tasks=[task], arms=["PGM_ACCEPTED"], replicates=[1])
    (tmp_path / "FREEZE.json").write_text(json.dumps(config))
    folder = tmp_path / "runs/alpha__PGM_ACCEPTED__r1"
    folder.mkdir(parents=True)
    (folder / "cell.json").write_text(json.dumps(dict(receipt_jid="different", identity_ok=True)))
    (tmp_path / "RECEIPTS.jsonl").write_text(json.dumps(dict(kind="RECEIPT", job="alpha__PGM_ACCEPTED__r1", jid="actual")) + "\n")
    with patch.object(campaign, "verify_identity"), patch.object(campaign, "supervised") as launch:
        with pytest.raises(RuntimeError, match="Invalid prior cell"):
            campaign.run(SimpleNamespace(run_dir=tmp_path, max_cells=None))
        launch.assert_not_called()


def test_unresolved_terminal_cleanup_cannot_complete(tmp_path):
    task = dict(name="alpha", model_sha256="m", evidence_sha256="e")
    receipt = dict(jid="r", wall_s=0.5, outcome="COMPLETED", returncode=0, peak_tree_rss_bytes=12,
                   cleanup_unresolved=True, group_empty_at_receipt=False, nested_groups_live_at_receipt=1)
    with patch.object(campaign.checks, "check_libdai", return_value=dict(all_queries_returned=True, output_valid=True, contract_valid=True)):
        row = campaign.read_cell(dict(contracts={}), task, "LIBDAI_JT", 1, tmp_path, receipt, True)
    assert not row["complete_within_contract"]


def test_automatic_contract_is_explicit_and_keeps_risk():
    c = campaign.contract("PGM_AUTOMATIC")
    assert c["policy"] == "automatic"
    assert c["policy_version"] == "structural-portfolio-3"
    assert c["risk_shares"] == campaign.contract("BASE_EXPERIMENTAL")["risk_shares"]
    config = dict(runtime_python="python", libdai_binary="libdai")
    cmd = campaign.command(config, dict(model="model"), "PGM_AUTOMATIC", 2, Path("out"))
    assert cmd[cmd.index("--policy") + 1] == "automatic"
    assert cmd[cmd.index("--budget") + 1] == "19.5"
    assert cmd[cmd.index("--seed") + 1] == "2"


def test_atomic_json_and_single_runner_lock(tmp_path):
    target = tmp_path / "cell.json"
    campaign.atomic_json(target, dict(value=3))
    assert json.loads(target.read_text()) == {"value": 3}
    assert not target.with_name("cell.json.tmp").exists()
    with campaign.exclusive_run(tmp_path):
        with pytest.raises(BlockingIOError):
            with campaign.exclusive_run(tmp_path):
                raise AssertionError("Concurrent runner acquired lock")


def test_unsafe_task_paths_refused():
    with pytest.raises(ValueError):
        campaign.job_name(dict(name="../outside"), "PGM_ACCEPTED", 1)
