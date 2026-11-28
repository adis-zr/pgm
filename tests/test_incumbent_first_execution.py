"""Incumbent-first scheduling must still execute and certify original coordinates."""
from fractions import Fraction as F
from itertools import product

from pgm import infer, switchboard


def model_and_truth(tmp_path, monkeypatch):
    states = list(product(range(3), repeat=3))
    weights = {x: 0 if x == (0, 0, 0) else 1 + x[0] + 3*x[1] + 9*x[2]
               for x in states}
    path = tmp_path / "categorical.uai"
    path.write_text("MARKOV\n3\n3 3 3\n1\n3 0 1 2\n27\n" +
                    " ".join(str(weights[x]) for x in states) + "\n")
    mass = sum(weights.values())
    truth = {(v, a): F(sum(w for x, w in weights.items() if x[v] == a), mass)
             for v in range(3) for a in range(3)}
    inspect = switchboard.inspect_model

    def refused_optional_forecast(*args, **kwargs):
        meta = inspect(*args, **kwargs)
        meta.update(native_forecast=None, native_forecast_memory_bytes=None,
                    forecast_refusal={"kind": "FORECAST", "reason": "injected optional forecast refusal"})
        return meta

    monkeypatch.setattr(switchboard, "inspect_model", refused_optional_forecast)
    return path, truth


def check_truth(result, truth):
    assert result["outcome"] == "COMPLETE", result
    assert result["published"] == result["K"] == len(truth)
    assert result["positive_mass_witness"] and result["hard_deadline_respected"]
    for row in result["answers"]:
        lo, hi, point = (F(row[key]) for key in ("lo", "hi", "point"))
        target = truth[row["variable"], row["state"]]
        assert lo <= target <= hi
        assert abs(point-target) <= F(1, 200)
    assert all(not record["cleanup_final"]["unresolved"]
               for record in result["attempts"] if record.get("accepted"))


def test_incumbent_completes_without_speculative_quotient(tmp_path, monkeypatch):
    path, truth = model_and_truth(tmp_path, monkeypatch)
    result = infer(path, policy="automatic", budget=6, memory_mib=256).to_dict()
    check_truth(result, truth)
    assert [r["backend"] for r in result["attempts"]] == ["block"]
    assert result["dispatch"][1]["backend"] == "quotient"
    assert result["dispatch"][1]["attempted"] is False
    assert F(result["attempts"][0]["delta"]) == F(1, 2_000_000)


def test_incumbent_refusal_keeps_real_quotient_fallback(tmp_path, monkeypatch):
    path, truth = model_and_truth(tmp_path, monkeypatch)
    original = switchboard.run_attempt

    def refuse_block(choice, request, deadline, directory, number):
        if choice["backend"] == "block":
            return None, dict(backend="block", outcome="MEMORY", accepted=False,
                              delta=str(request.delta / 2), reason="injected incumbent admission refusal")
        return original(choice, request, deadline, directory, number)

    monkeypatch.setattr(switchboard, "run_attempt", refuse_block)
    result = infer(path, policy="automatic", budget=6, memory_mib=256).to_dict()
    check_truth(result, truth)
    assert [r["backend"] for r in result["attempts"]] == ["block", "quotient"]
    assert result["attempts"][1]["accepted"]
    assert F(result["attempts"][1]["delta"]) == F(1, 4_000_000)
    assert sum(F(value) for value in result["risk_allocations"].values()) == F(1, 1_000_000)
