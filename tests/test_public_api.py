"""Independent API contract tests; these are not performance benchmarks."""
from fractions import Fraction as F
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from pgm import infer, InferenceRequest
from pgm import switchboard
from pgm.backends.worker import normalize_result
from pgm.planning import PlanningRefused, inspect_model


def tiny(tmp_path, evidence=None, zero=False):
    path = tmp_path / "asymmetric.uai"
    path.write_text("MARKOV\n2\n2 2\n3\n1 0\n1 1\n2 0 1\n2\n2 1\n2\n1 3\n4\n"
                    + ("0 0 0 0\n" if zero else "5 2 1 8\n"))
    if evidence is not None:
        Path(str(path) + ".evid").write_text(evidence)
    return path


def enumerated_truth(evidence=None):
    """Independent exact sum of four asymmetric, non-dyadic state weights."""
    evidence = evidence or {}
    weights = {}
    for x in product(range(2), repeat=2):
        if any(x[v] != a for v, a in evidence.items()):
            continue
        weights[x] = F((2, 1)[x[0]] * (1, 3)[x[1]] * ((5, 2), (1, 8))[x[0]][x[1]])
    z = sum(weights.values(), F(0))
    return {(v, a): sum((w for x, w in weights.items() if x[v] == a), F(0)) / z
            for v in range(2) for a in range(2)}


def assert_geometry(result, truth, epsilon=F(1, 200)):
    for row in result.answers:
        if row["guarantee"] == "NOT_PUBLISHED":
            continue
        lo, hi, point = (F(row[k]) for k in ("lo", "hi", "point"))
        target = truth[row["variable"], row["state"]]
        assert 0 <= lo <= target <= hi <= 1
        assert lo <= point <= hi
        assert max(point-lo, hi-point) <= epsilon
        assert abs(point-target) <= epsilon
        if row["guarantee"] == "EXACT":
            assert lo == point == hi == target


def test_actual_asymmetric_forest_against_independent_exact_reference(tmp_path):
    actual = infer(tiny(tmp_path), budget=3, memory_mib=256)
    assert actual.complete, actual.to_dict()
    assert actual.data["published"] == actual.data["K"] == 4
    assert_geometry(actual, enumerated_truth())
    receipt = actual.data["attempts"][0]["supervisor_receipt"]
    assert receipt["outcome"] == "COMPLETED"
    assert receipt["group_empty_at_receipt"] and not receipt["cleanup_unresolved"]


def test_actual_explicit_observed_and_nonobserved_queries(tmp_path):
    queries = [(0, 0), (0, 1), (1, 0)]
    actual = infer(tiny(tmp_path, "1 0 1\n"), queries=queries, budget=3, memory_mib=256)
    assert actual.complete, actual.to_dict()
    assert [(r["variable"], r["state"]) for r in actual.answers] == queries
    assert_geometry(actual, enumerated_truth({0: 1}))
    assert actual.probability(0, 0) == 0 and actual.probability(0, 1) == 1


def test_zero_mass_does_not_publish_observed_coordinates(tmp_path):
    actual = infer(tiny(tmp_path, "1 0 1\n", zero=True), queries=[(0, 1)],
                   budget=3, memory_mib=256)
    assert not actual.complete and actual.data["published"] == 0
    assert actual.data["positive_mass_witness"] is False
    assert actual.answers[0]["guarantee"] == "NOT_PUBLISHED"


def test_planning_refusal_preserves_explicit_inventory(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    def refuse(*args, **kwargs):
        raise PlanningRefused("MEMORY", "injected", [(0, 0), (0, 1), (1, 0), (1, 1)])
    monkeypatch.setattr(switchboard, "inspect_model", refuse)
    actual = infer(path, queries=[(1, 0)], budget=1)
    assert actual.outcome == "MEMORY" and actual.data["K"] == 1
    assert [(r["variable"], r["state"]) for r in actual.answers] == [(1, 0)]


@pytest.mark.parametrize("work,memory", [(None, None), (None, 100), (100, None)])
def test_optional_null_forecast_keeps_fallback_available(tmp_path, work, memory):
    path = tiny(tmp_path)
    meta = inspect_model(path)
    meta.update(pairwise_forest=False, binary_pairwise_bipartite=False,
                hard_zero_entries=1,
                native_forecast={"sum_product": work, "native_bytes_estimate": memory})
    choices = switchboard.candidate_plan(meta, InferenceRequest(path), 1.0)
    assert choices[0]["backend"] == "block"
    assert any(choice["backend"] == "structural" for choice in choices)


def test_optional_estimator_refusal_does_not_end_request(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    meta = inspect_model(path)
    meta["native_forecast"] = {"sum_product": None, "native_bytes_estimate": None}
    monkeypatch.setattr(switchboard, "inspect_model", lambda *args, **kwargs: meta)
    actual = infer(path, budget=3, memory_mib=256)
    assert actual.complete, actual.to_dict()
    assert_geometry(actual, enumerated_truth())


def test_expired_parse_retains_known_explicit_queries(tmp_path):
    actual = infer(tiny(tmp_path), queries=[(1, 1)], budget=1e-12)
    assert actual.outcome == "DEADLINE" and actual.data["published"] == 0
    assert actual.data["K"] == 1 and actual.answers[0]["state"] == 1


def test_invalid_query_is_a_request_error_not_certificate_defect(tmp_path):
    actual = infer(tiny(tmp_path), queries=[(2, 0)], budget=1)
    assert actual.outcome == "INVALID_TASK" and actual.data["published"] == 0
    assert not actual.data["attempts"]


def test_insufficient_total_memory_returns_typed_inventory(tmp_path):
    actual = infer(tiny(tmp_path), memory_mib=1, budget=1)
    assert actual.outcome == "MEMORY" and actual.data["published"] == 0
    assert actual.data["K"] == 4
    assert not actual.complete


def mocked_choices(monkeypatch, meta, results):
    choices = [dict(backend=name, reason="fixture", allowance_fraction=1, structural_route="auto")
               for name in ("block", "quotient")[:len(results)]]
    monkeypatch.setattr(switchboard, "inspect_model", lambda *a, **k: meta)
    monkeypatch.setattr(switchboard, "candidate_plan", lambda *a: choices)
    def attempt(choice, request, deadline, directory, number):
        return results[number], dict(choice, outcome=results[number]["outcome"], wall_s=0)
    monkeypatch.setattr(switchboard, "run_attempt", attempt)


def test_separate_valid_partial_boxes_cannot_combine_outside_simplex(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    meta = inspect_model(path)
    inventory = [(0, 0), (0, 1), (1, 0), (1, 1)]
    results = []
    for state in (0, 1):
        raw = dict(outcome="PARTIAL", positive_mass_witness=True, binding=meta["binding"],
                   answers=[dict(var=0, state=state, lo="4/5", hi="4/5", point="4/5", guarantee="PAC")])
        # Each input is independently accepted by the real backend boundary.
        results.append(normalize_result(raw, inventory, meta["binding"], F(1, 200)))
    mocked_choices(monkeypatch, meta, results)
    actual = infer(path, queries=[(0, 0), (0, 1)], budget=1)
    assert actual.outcome == "CERTIFICATE_DEFECT" and actual.data["published"] == 0
    assert "simplex" in actual.data["error"]


@pytest.mark.parametrize("mode,label", [("exact", "DETERMINISTIC"), ("exact", "PAC"), ("deterministic", "PAC")])
def test_requested_guarantee_is_not_weakened(tmp_path, monkeypatch, mode, label):
    path = tiny(tmp_path)
    meta = inspect_model(path)
    raw = dict(outcome="COMPLETE", positive_mass_witness=True, binding=meta["binding"],
               answers=[dict(variable=0, state=a, lo="49/100", hi="51/100", point="1/2", guarantee=label)
                        for a in (0, 1)])
    mocked_choices(monkeypatch, meta, [raw])
    actual = infer(path, queries=[(0, 0), (0, 1)], mode=mode, epsilon="1/50", budget=1)
    assert not actual.complete and actual.data["published"] == 0


def test_risk_allocations_total_no_more_than_request(tmp_path):
    actual = infer(tiny(tmp_path), budget=3, memory_mib=256, delta="1/1234567")
    assert sum(map(F, actual.data["risk_allocations"].values())) == F(1, 1234567)
    for attempt in actual.data["attempts"]:
        assert F(attempt["delta"]) == F(actual.data["risk_allocations"][attempt["backend"]])


def test_final_timestamp_suppresses_assembled_answers(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    meta = inspect_model(path)
    raw = dict(outcome="COMPLETE", positive_mass_witness=True, binding=meta["binding"],
               answers=[dict(variable=0, state=a, lo="1/2", hi="1/2", point="1/2", guarantee="EXACT")
                        for a in (0, 1)])
    mocked_choices(monkeypatch, meta, [raw])
    ticks = iter((100.0, 100.0, 100.0, 102.0))
    monkeypatch.setattr(switchboard.time, "monotonic", lambda: next(ticks))
    actual = infer(path, queries=[(0, 0), (0, 1)], budget=1)
    assert actual.outcome == "DEADLINE" and actual.data["published"] == 0
    assert actual.data["max_published_radius"] is None
    assert actual.data["K"] == 2 and all(r["guarantee"] == "NOT_PUBLISHED" for r in actual.answers)


@pytest.mark.parametrize("kwargs", [dict(delta="1"), dict(epsilon="0"), dict(budget=float("inf")),
                                     dict(queries=[(0, 0), (0, 0)]), dict(memory_mib=True)])
def test_invalid_request_contract_rejected_before_work(tmp_path, kwargs):
    with pytest.raises(ValueError):
        InferenceRequest(tiny(tmp_path), **kwargs)


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def test_fast_worker_exit_cannot_leave_an_unobserved_orphan(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    child_file = tmp_path / "child.pid"
    probe = tmp_path / "worker.py"
    probe.write_text("import subprocess,sys,json\n"
                     "from pathlib import Path\n"
                     "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'])\n"
                     f"Path({str(child_file)!r}).write_text(str(child.pid))\n"
                     "output=Path(sys.argv[sys.argv.index('--output')+1])\n"
                     "output.write_text(json.dumps({'outcome':'COMPLETE','published':1}))\n")
    popen = subprocess.Popen
    def replace_worker(cmd, **kwargs):
        marker = cmd.index("--")
        worker_args = cmd[marker+4:]
        return popen(cmd[:marker+1] + [sys.executable, str(probe)] + worker_args, **kwargs)
    monkeypatch.setattr(switchboard.subprocess, "Popen", replace_worker)
    choice = dict(backend="structural", structural_route="auto", reason="fixture", allowance_fraction=1)
    pid = None
    try:
        result, record = switchboard.run_attempt(choice, InferenceRequest(path, memory_mib=256),
                                                 time.monotonic()+2, tmp_path, 0)
        pid = int(child_file.read_text())
        assert result is None and record["outcome"] == "BACKEND_EXIT"
        receipt = record["supervisor_receipt"]
        assert receipt["outcome"] == "COMPLETED_LEADER_EXIT_SURVIVORS_KILLED"
        assert receipt["group_empty_at_receipt"] and not alive(pid)
    finally:
        if pid is None and child_file.exists():
            pid = int(child_file.read_text())
        if pid and alive(pid):
            psutil.Process(pid).kill()


def test_timed_out_worker_is_reaped_and_never_published(tmp_path, monkeypatch):
    path = tiny(tmp_path)
    popen = subprocess.Popen
    def replace_worker(cmd, **kwargs):
        marker = cmd.index("--")
        return popen(cmd[:marker+1] + [sys.executable, "-c", "import time;time.sleep(5)"], **kwargs)
    monkeypatch.setattr(switchboard.subprocess, "Popen", replace_worker)
    choice = dict(backend="structural", structural_route="auto", reason="fixture", allowance_fraction=1)
    started = time.monotonic()
    result, record = switchboard.run_attempt(choice, InferenceRequest(path, memory_mib=256),
                                             started+0.3, tmp_path, 0)
    assert result is None and record["outcome"] == "DEADLINE"
    assert time.monotonic()-started < 1.5
    assert record["supervisor_receipt"]["group_empty_at_receipt"]
    assert record["supervisor_receipt"]["nested_groups_live_at_receipt"] == 0


def test_nested_supervisor_receipt_survives_request_directory_cleanup(tmp_path):
    path = tiny(tmp_path)
    ledger = tmp_path / "outer.jsonl"
    source = str(Path(switchboard.__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = source + os.pathsep + env.get("PYTHONPATH", "")
    script = ("from pgm import infer; "
              f"r=infer({str(path)!r}, budget=3, memory_mib=256); "
              "assert r.complete, r.to_dict()")
    result = subprocess.run([sys.executable, "-m", "pgm.supervision", "--ledger", str(ledger),
                             "--scope", "api-test", "--job", "outer", "--timeout", "5", "--interval", "0.01",
                             "--", sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=6)
    assert result.returncode == 0, result.stderr
    receipt = [json.loads(line) for line in ledger.read_text().splitlines()
               if json.loads(line)["kind"] == "RECEIPT"][-1]
    assert receipt["outcome"] == "COMPLETED" and receipt["nested_groups_registered"] == 1
    assert receipt["nested_receipts_written_by_parent"] == 0
    registrations = switchboard._ledger_records(Path(receipt["owner_dir"]) / "groups.jsonl")
    nested = [r for r in registrations if r["jid"] != receipt["jid"]]
    assert len(nested) == 1 and Path(nested[0]["ledger"]).is_file()
    assert switchboard._ledger_records(Path(nested[0]["ledger"]))[-1]["outcome"] == "COMPLETED"
