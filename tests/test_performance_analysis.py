"""Independent analysis mutations: incomplete work cannot become a speed win."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks/external"))
import analyze_performance as a
import run_suite as h


def simple_row(task, arm, rep, wall, complete=True):
    return dict(task=task, arm=arm, replicate=rep, wall_s=wall, peak_rss_bytes=100,
                complete_within_contract=complete)


def test_timeout_is_not_a_latency_denominator():
    rows = [simple_row("pass", arm, rep, 1 if arm == "PGM_ACCEPTED" else 2)
            for arm in ("PGM_ACCEPTED", "BASE_ACCEPTED") for rep in (1, 2)]
    rows += [simple_row("censored", arm, rep, 1 if arm == "PGM_ACCEPTED" else 20, arm == "PGM_ACCEPTED")
             for arm in ("PGM_ACCEPTED", "BASE_ACCEPTED") for rep in (1, 2)]
    result = a.compare_pair(rows, ["pass", "censored"], [1, 2], "PGM_ACCEPTED", "BASE_ACCEPTED")
    assert result["candidate_only"] == ["censored"]
    assert result["mutual_both"] == ["pass"]
    assert result["median_wall_ratio"] == 0.5
    assert len(result["per_task"]) == 1


def test_cost_flag_requires_both_thresholds_in_both_repeats():
    rows = [simple_row("tiny", arm, rep, 0.02 if arm == "PGM_ACCEPTED" else 0.01)
            for arm in ("PGM_ACCEPTED", "BASE_ACCEPTED") for rep in (1, 2)]
    rows += [simple_row("noisy", arm, rep, (2 if rep == 1 else 1) if arm == "PGM_ACCEPTED" else 1)
             for arm in ("PGM_ACCEPTED", "BASE_ACCEPTED") for rep in (1, 2)]
    rows += [simple_row("slow", arm, rep, 2 if arm == "PGM_ACCEPTED" else 1)
             for arm in ("PGM_ACCEPTED", "BASE_ACCEPTED") for rep in (1, 2)]
    result = a.compare_pair(rows, ["tiny", "noisy", "slow"], [1, 2], "PGM_ACCEPTED", "BASE_ACCEPTED")
    assert result["cost_flags"] == ["slow"]


def test_deterministic_and_pac_conflicts_are_separate():
    pub = {("x", "BASE_ACCEPTED", 1): {"0:0": dict(lo="1/2", hi="1/2", label="EXACT")},
           ("x", "PGM_ACCEPTED", 1): {"0:0": dict(lo="3/4", hi="3/4", label="PAC")}}
    det, pac = a.interval_conflicts(pub)
    assert not det and len(pac) == 1
    pub["x", "PGM_ACCEPTED", 1]["0:0"]["label"] = "EXACT"
    det, pac = a.interval_conflicts(pub)
    assert len(det) == 1 and not pac


def test_automatic_preservation_uses_union_of_both_baselines():
    sets = dict(BASE_ACCEPTED=["a", "shared"], BASE_EXPERIMENTAL=["b", "shared"],
                PGM_ACCEPTED=["a", "shared"], PGM_AUTOMATIC=["b", "shared"])
    result = a.preservation_decisions(sets)
    assert result["accepted"]["decision"] == "PASS"
    assert result["automatic"]["decision"] == "FAIL"
    assert result["automatic"]["losses"] == ["a"]
    assert result["automatic"]["baseline_count"] == 3
    sets["PGM_AUTOMATIC"].append("a")
    assert a.preservation_decisions(sets)["automatic"]["decision"] == "PASS"


@pytest.fixture
def campaign(tmp_path):
    model = ROOT / "tests/parity/fixtures/asym2.uai"
    evidence = tmp_path / "empty.evid"; evidence.write_text("0\n")
    task = dict(name="asym2", model=str(model), evidence=str(evidence), model_sha256=h.sha(model), evidence_sha256=h.sha(evidence))
    arms = ["BASE_ACCEPTED", "PGM_ACCEPTED"]
    freeze = dict(tasks=[task], arms=arms, replicates=[1, 2], expected_cells=4, budget_s=20, scored_ceiling_s=80,
                  contracts={arm: h.CONTRACTS["PGM_ACCEPTED"] for arm in arms})
    (tmp_path / "FREEZE.json").write_text(json.dumps(freeze))
    receipts = []
    for arm in arms:
        for rep in [1, 2]:
            job = f"asym2__{arm}__r{rep}"; folder = tmp_path / "runs" / job; folder.mkdir(parents=True)
            result = dict(outcome="COMPLETE", guarantee="EXACT", K=4, published=4,
                answers=[dict(variable=v, state=s, lo="1/2", hi="1/2", point="1/2", guarantee="EXACT") for v in range(2) for s in range(2)],
                positive_mass_witness=True, binding={k: task[k] for k in ("model_sha256", "evidence_sha256")},
                policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", epsilon="1/200", delta="1/1000000",
                hard_deadline_respected=True, mode="auto", wall_s=0.1, risk_allocations={"block": "1/1000000"},
                attempts=[dict(backend="block", outcome="COMPLETE", wall_s=0.08, worker_wall_s=0.05,
                               configuration=h.CONTRACTS["PGM_ACCEPTED"]["configuration"])])
            (folder / "result.json").write_text(json.dumps(result))
            check = h.check_pgm(folder / "result.json", task, freeze["contracts"][arm])
            row = dict(job=job, task=task["name"], arm=arm, replicate=rep, wall_s=0.2, receipt_outcome="COMPLETED", returncode=0,
                       peak_rss_bytes=100, identity_ok=True, cleanup_unresolved=False, complete_within_contract=True,
                       model_sha256=task["model_sha256"], evidence_sha256=task["evidence_sha256"], **check)
            (folder / "cell.json").write_text(json.dumps(row))
            receipts.append(dict(kind="RECEIPT", job=job, outcome="COMPLETED", returncode=0, wall_s=0.2,
                                 peak_tree_rss_bytes=100, cleanup_unresolved=False, group_empty_at_receipt=True, nested_groups_live_at_receipt=0))
    (tmp_path / "RECEIPTS.jsonl").write_text("".join(json.dumps(r) + "\n" for r in receipts))
    return tmp_path


def test_raw_campaign_passes_and_report_is_reproducible(campaign):
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "PASS" and result["completeness"] == "PASS", result["validation_issues"]
    assert result["geometry"]["published_coordinate_instances"] == 16
    assert result["same_host_preservation"]["accepted"]["decision"] == "PASS"
    a.write_report(campaign, result)
    first = (campaign / "ANALYSIS.json").read_bytes()
    a.write_report(campaign, a.analyze(campaign)[2])
    assert (campaign / "ANALYSIS.json").read_bytes() == first


def test_identity_failure_invalidates_success(campaign):
    path = campaign / "runs/asym2__PGM_ACCEPTED__r1/cell.json"
    row = json.loads(path.read_text()); row["identity_ok"] = False; path.write_text(json.dumps(row))
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "FAIL"
    assert result["complete_both"]["PGM_ACCEPTED"] == []
    assert result["same_host_preservation"]["accepted"]["losses"] == ["asym2"]


def test_cell_receipt_incarnation_and_artifact_hash_are_bound(campaign):
    folder = campaign / "runs/asym2__PGM_ACCEPTED__r1"
    path = folder / "cell.json"; row = json.loads(path.read_text())
    row["receipt_jid"] = "foreign-jid"
    row["artifact_sha256"] = {"result.json": "0" * 64}
    path.write_text(json.dumps(row))
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "FAIL"
    assert any("incarnation disagreement" in issue for issue in result["validation_issues"])
    assert any("artifact changed" in issue for issue in result["validation_issues"])


def test_actual_phase_and_dispatch_fields_are_reported(campaign):
    path = campaign / "runs/asym2__PGM_ACCEPTED__r1/result.json"
    raw = json.loads(path.read_text())
    raw["phase_timings"] = dict(inspection_s=0.01, planning_s=0.02, attempts_s=0.08, publication_s=0.01)
    raw["dispatch"] = [dict(backend="block", reason="existing accepted method", structural_route="auto", attempted=True)]
    raw["attempts"][0]["worker_timings"] = dict(source_parse_s=0.001, adapter_s=0.04, normalization_s=0.002)
    path.write_text(json.dumps(raw))
    _, _, result = a.analyze(campaign)
    assert result["phase_timing"]["PGM_ACCEPTED"]["workers_source_parse_s"]["total_s"] == 0.001
    assert result["phase_timing"]["PGM_ACCEPTED"]["planning_s"]["total_s"] == 0.02
    assert result["dispatch_counts"]["PGM_ACCEPTED"][0]["attempted"] is True


def test_duplicate_cells_and_receipts_fail(campaign):
    copy = campaign / "runs/duplicate"; copy.mkdir()
    copy.joinpath("cell.json").write_bytes((campaign / "runs/asym2__PGM_ACCEPTED__r1/cell.json").read_bytes())
    receipt_path = campaign / "RECEIPTS.jsonl"
    with receipt_path.open("a") as out: out.write(receipt_path.read_text().splitlines()[0] + "\n")
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "FAIL" and result["completeness"] == "INCOMPLETE"
    assert "Duplicate scored cell keys" in result["validation_issues"]
    assert any("exactly one terminal receipt" in x for x in result["validation_issues"])


def test_raw_geometry_is_rechecked(campaign):
    path = campaign / "runs/asym2__PGM_ACCEPTED__r1/result.json"
    raw = json.loads(path.read_text()); raw["answers"][0]["hi"] = "3/4"; path.write_text(json.dumps(raw))
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "FAIL"
    assert result["artifact_faults"]
    assert result["complete_both"]["PGM_ACCEPTED"] == []


def test_missing_cell_and_receipt_are_incomplete(campaign):
    path = campaign / "runs/asym2__PGM_ACCEPTED__r1/cell.json"; path.unlink()
    receipt_path = campaign / "RECEIPTS.jsonl"
    receipts = [json.loads(s) for s in receipt_path.read_text().splitlines()]
    receipt_path.write_text("".join(json.dumps(r) + "\n" for r in receipts if r["job"] != "asym2__PGM_ACCEPTED__r1"))
    _, _, result = a.analyze(campaign)
    assert result["validity"] == "INCOMPLETE" and result["completeness"] == "INCOMPLETE"
    assert result["missing_cells"] == [("asym2", "PGM_ACCEPTED", 1)]


def test_historical_reference_relocates_without_rewriting_freeze(tmp_path, monkeypatch):
    restored = tmp_path / "restored"
    restored.mkdir()
    monkeypatch.setattr(a.h, "REPO", restored)
    original = Path("/creator-workstation-unavailable/pgm")
    relative = Path("documentation/consolidation/step2/supplement/ANALYSIS.json")
    target = restored / relative
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"complete_both": {"PGM_ACCEPTED": ["a"], "PGM_EXPERIMENTAL": ["a", "b"]}}))
    frozen = {"roots": {"candidate": {"path": str(original)}},
              "historical_reference": {"path": str(original / relative), "sha256": a.h.sha(target)}}
    before = json.dumps(frozen, sort_keys=True)
    sets = {"BASE_ACCEPTED": ["a"], "PGM_ACCEPTED": ["a"],
            "BASE_EXPERIMENTAL": ["a", "b"], "PGM_AUTOMATIC": ["a", "b"]}
    issues = []
    result = a._historical(frozen, sets, issues)
    assert not issues and result["policies"]["experimental"]["retained"] == ["a", "b"]
    assert json.dumps(frozen, sort_keys=True) == before
    target.write_text("{}")
    assert a._historical(frozen, sets, issues)["status"] == "INVALID_REFERENCE"
    assert issues == ["Historical reference missing or changed"]


def test_restored_input_preferred_over_old_workstation_path(tmp_path, monkeypatch):
    restored = tmp_path / "restored"
    restored.mkdir()
    monkeypatch.setattr(a.h, "REPO", restored)
    original = tmp_path / "original"
    original.write_text("stale original")
    local = restored / "model.uai"
    local.write_text("restored source")
    assert a._source_path({}, original, "model.uai") == local


@pytest.mark.parametrize("relative", ["../outside", "/tmp/outside"])
def test_restored_input_cannot_escape_checkout(tmp_path, monkeypatch, relative):
    monkeypatch.setattr(a.h, "REPO", tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        a._source_path({}, "/old/model.uai", relative)


def test_restored_input_symlink_escape_refused(tmp_path, monkeypatch):
    restored = tmp_path / "restored"
    restored.mkdir()
    monkeypatch.setattr(a.h, "REPO", restored)
    (restored / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        a._source_path({}, "/old/model.uai", "escape/outside")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_runner_analysis_dispatch_propagates_analyzer_status(tmp_path, monkeypatch, exit_code):
    import run_performance as runner
    calls = []
    def analyze_main(argv):
        calls.append(argv)
        return exit_code
    monkeypatch.setattr(a, "main", analyze_main)
    with pytest.raises(SystemExit) as stopped:
        runner.main(["analyze", "--run-dir", str(tmp_path)])
    assert stopped.value.code == exit_code
    assert calls == [[str(tmp_path.resolve())]]
