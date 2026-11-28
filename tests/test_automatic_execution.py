"""Execute automatic higher-arity dispatch and its fallback against exact truth."""
from fractions import Fraction as F
from itertools import product

from pgm import infer, switchboard


def higher_order_model(tmp_path):
    path = tmp_path / "higher_order.uai"
    path.write_text("MARKOV\n3\n2 2 2\n2\n3 0 1 2\n1 1\n"
                    "8\n1 2 3 5 7 11 13 17\n2\n2 3\n")
    weights = {x: F((1, 2, 3, 5, 7, 11, 13, 17)[4*x[0] + 2*x[1] + x[2]]
                    * (2, 3)[x[1]]) for x in product(range(2), repeat=3)}
    mass = sum(weights.values())
    truth = {(v, a): sum(w for x, w in weights.items() if x[v] == a) / mass
             for v in range(3) for a in range(2)}
    return path, truth


def check_answer(result, truth):
    assert result["outcome"] == "COMPLETE", result
    assert result["published"] == result["K"] == 6
    assert result["positive_mass_witness"]
    assert {(r["variable"], r["state"]) for r in result["answers"]} == set(truth)
    for row in result["answers"]:
        lo, hi, point = (F(row[k]) for k in ("lo", "hi", "point"))
        target = truth[row["variable"], row["state"]]
        assert lo <= target <= hi
        assert lo <= point <= hi
        assert max(point-lo, hi-point) <= F(1, 200)
        assert abs(point-target) <= F(1, 200)
        assert row["guarantee"] in {"EXACT", "DETERMINISTIC", "DETERMINISTIC_RESIDUAL"}
    assert all(value >= 0 for value in result["phase_timings"].values())
    assert result["hard_deadline_respected"]


def test_automatic_higher_order_execution_contains_independent_truth(tmp_path):
    path, truth = higher_order_model(tmp_path)
    result = infer(path, policy="automatic", budget=6, memory_mib=256).to_dict()
    check_answer(result, truth)
    assert [a["backend"] for a in result["attempts"]] == ["structural"]
    assert result["dispatch"][0]["attempted"]
    assert all(not c["attempted"] for c in result["dispatch"][1:])
    assert result["attempts"][0]["accepted"]
    assert not result["attempts"][0]["cleanup_final"]["unresolved"]
    assert {"source_parse_s", "adapter_s", "normalization_s"} <= set(
        result["attempts"][0]["worker_timings"])


def test_automatic_refusal_preserves_real_block_fallback_and_risk(tmp_path, monkeypatch):
    path, truth = higher_order_model(tmp_path)
    original = switchboard.run_attempt
    calls = []

    def refuse_structural(choice, request, deadline, directory, number):
        calls.append((choice["backend"], deadline))
        if choice["backend"] == "structural":
            return None, dict(backend="structural", outcome="MEMORY", delta="0",
                              accepted=False, reason="injected construction admission refusal")
        return original(choice, request, deadline, directory, number)

    monkeypatch.setattr(switchboard, "run_attempt", refuse_structural)
    delta = F(1, 1234567)
    result = infer(path, policy="automatic", budget=6, memory_mib=256,
                   delta=delta).to_dict()
    check_answer(result, truth)
    assert [a["backend"] for a in result["attempts"]] == ["structural", "block"]
    assert calls[0][1] < calls[1][1]
    assert result["attempts"][1]["accepted"]
    assert F(result["attempts"][1]["delta"]) == delta / 2
    assert sum(F(x) for x in result["risk_allocations"].values()) == delta
    assert [c["attempted"] for c in result["dispatch"]] == [True, True, False]
