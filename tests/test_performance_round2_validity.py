"""Prospective refusal/censoring rules never manufacture a successful answer."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks/external"))
import benchmark_validity as rules
import run_performance as runner
import run_suite as original


ROUND2 = {"budget_s": 20, "protocol": {"schema": "PGM_UNTUNED_PERFORMANCE_PLAN_2", "output_validation": {
    "resource_killed_comparator": "censored_nonanswer",
    "claimed_publication_timestamps": "finite_within_cli_and_recorded_api_budgets",
    "late_empty_deadline_refusal": "typed_nonanswer_with_clean_outer_completion"}}}


@pytest.fixture
def refusal(tmp_path):
    model = ROOT / "tests/parity/fixtures/asym2.uai"
    evidence = tmp_path / "empty.evid"
    evidence.write_text("0\n")
    task = dict(name="tiny", model=str(model), evidence=str(evidence), model_sha256=original.sha(model), evidence_sha256=original.sha(evidence))
    result = dict(outcome="DEADLINE", guarantee="NONE", K=4, published=0,
        answers=[dict(variable=v, state=s, guarantee="NOT_PUBLISHED") for v in range(2) for s in range(2)],
        positive_mass_witness=False, binding={key: task[key] for key in ("model_sha256", "evidence_sha256")},
        policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", epsilon="1/200", delta="1/1000000",
        hard_deadline_respected=False, mode="auto", wall_s=19.502556, api_wall_s=19.49,
        risk_allocations={"block": "1/1000000"}, max_published_radius=None,
        attempts=[dict(backend="block", outcome="DEADLINE", configuration=original.CONTRACTS["PGM_ACCEPTED"]["configuration"])])
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result))
    receipt = dict(jid="r", outcome="COMPLETED", returncode=0, wall_s=19.8, peak_tree_rss_bytes=1,
                   cleanup_unresolved=False, group_empty_at_receipt=True, nested_groups_live_at_receipt=0)
    return path, task, result, receipt


def checked(fixture, config=ROUND2):
    path, task, result, receipt = fixture
    path.write_text(json.dumps(result))
    return rules.check_public_output(config, path, task, original.CONTRACTS["PGM_ACCEPTED"], receipt)


def test_typed_late_refusal_is_valid_but_never_complete_and_old_rule_stays_strict(refusal):
    new = checked(refusal)
    assert new["output_valid"] and new["contract_valid"]
    assert not new["all_queries_returned"] and new["published"] == 0
    assert new["late_refusal_wall_s"] == 19.502556 and new["late_refusal_api_wall_s"] == 19.49
    old = checked(refusal, {"budget_s": 20})
    assert not old["contract_valid"]
    assert old["contract_faults"] == ["hard deadline not respected"]
    assert "late_empty_deadline_refusal" not in old


@pytest.mark.parametrize("mutation", ["published", "payload", "binding", "inventory", "outcome", "guarantee", "radius", "bad_time", "after_outer", "attempt_cleanup"])
def test_refusal_exception_does_not_hide_claims_or_other_defects(refusal, mutation):
    path, task, raw, receipt = refusal
    if mutation == "published":
        raw["published"] = 1
        raw["answers"][0].update(guarantee="EXACT", lo="1/2", hi="1/2", point="1/2")
    elif mutation == "payload": raw["answers"][0]["point"] = "1/2"
    elif mutation == "binding": raw["binding"]["model_sha256"] = "wrong"
    elif mutation == "inventory": raw["answers"].pop()
    elif mutation == "outcome": raw["outcome"] = "COMPLETE"
    elif mutation == "guarantee": raw["guarantee"] = "PAC"
    elif mutation == "radius": raw["max_published_radius"] = 0.005
    elif mutation == "bad_time": raw["wall_s"] = float("nan")
    elif mutation == "after_outer": raw["wall_s"] = 20.1
    elif mutation == "attempt_cleanup": raw["attempts"][0]["cleanup_final"] = {"unresolved": ["live worker"]}
    result = checked(refusal)
    assert not result["contract_valid"] or not result["output_valid"]
    assert not result["all_queries_returned"]


@pytest.mark.parametrize("field,value", [("outcome", "TIMEOUT_KILL"), ("returncode", 1), ("wall_s", 20.1),
    ("cleanup_unresolved", True), ("group_empty_at_receipt", False), ("nested_groups_live_at_receipt", 1)])
def test_late_refusal_needs_clean_on_time_outer_completion(refusal, field, value):
    refusal[3][field] = value
    result = checked(refusal)
    assert not result["contract_valid"]
    assert "hard deadline not respected" in result["contract_faults"]


@pytest.mark.parametrize("kill", ["TIMEOUT_KILL", "MEMORY_KILL"])
def test_killed_comparator_header_is_censored_without_parsing(refusal, kill):
    path, task, raw, receipt = refusal
    folder = path.parent
    (folder / "output.MAR").write_text("MAR\n")
    receipt.update(outcome=kill, returncode=-9)
    with patch.object(original, "check_libdai", side_effect=AssertionError("Censored output must not be interpreted")):
        row = runner.read_cell(ROUND2, task, "LIBDAI_JT", 1, folder, receipt, True)
    assert row["censored_output"] and row["output_validation"] == "CENSORED_NONANSWER"
    assert not row["complete_within_contract"] and not row["all_queries_returned"]
    assert not rules.censored_comparator({}, "LIBDAI_JT", receipt)
    assert not rules.censored_comparator(ROUND2, "PGM_ACCEPTED", receipt)


def test_completed_malformed_comparator_remains_invalid(refusal):
    path, task, raw, receipt = refusal
    (path.parent / "output.MAR").write_text("MAR\n")
    row = runner.read_cell(ROUND2, task, "LIBDAI_JT", 1, path.parent, receipt, True)
    assert not row["output_valid"] and not row["complete_within_contract"]
    assert "validation_error" in row and not row.get("censored_output")


@pytest.mark.parametrize("mutation", ["cli_late_true_flag", "cli_nan", "cli_bool", "api_late_true_flag", "api_nan", "api_bool", "api_false_flag", "api_bool_budget", "api_missing_budget", "api_oversized_budget"])
def test_claimed_answer_cannot_hide_contradictory_timestamps(refusal, mutation):
    path, task, raw, receipt = refusal
    raw.update(outcome="COMPLETE", guarantee="EXACT", published=4, positive_mass_witness=True,
               hard_deadline_respected=True, wall_s=19.4, api_wall_s=19.3,
               api_hard_deadline_respected=True, requested_budget_s=19.35, max_published_radius=0.0)
    for row in raw["answers"]:
        row.update(guarantee="EXACT", lo="1/2", hi="1/2", point="1/2")
    assert checked(refusal)["contract_valid"]
    if mutation == "cli_late_true_flag": raw["wall_s"] = 19.75
    elif mutation == "cli_nan": raw["wall_s"] = float("nan")
    elif mutation == "cli_bool": raw["wall_s"] = True
    elif mutation == "api_late_true_flag": raw["api_wall_s"] = 19.36
    elif mutation == "api_nan": raw["api_wall_s"] = float("nan")
    elif mutation == "api_bool": raw["api_wall_s"] = True
    elif mutation == "api_false_flag": raw["api_hard_deadline_respected"] = False
    elif mutation == "api_bool_budget": raw["requested_budget_s"] = True
    elif mutation == "api_missing_budget": raw.pop("requested_budget_s")
    elif mutation == "api_oversized_budget": raw["requested_budget_s"] = 20
    result = checked(refusal)
    assert not result["contract_valid"], mutation
    # The first round did not prospectively declare these timestamp crosschecks.
    assert checked(refusal, {"budget_s": 20})["contract_valid"]
