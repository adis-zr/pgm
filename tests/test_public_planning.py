"""Tiny correctness and refusal tests, not performance benchmark inputs."""
import hashlib
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pgm.planning import PlanningRefused, inspect_model


def model(tmp_path, text, evidence=None):
    path = tmp_path / "tiny.uai"
    path.write_text(text)
    if evidence is not None:
        Path(str(path)+".evid").write_text(evidence)
    return path


def test_pairwise_forest_inventory_binding(tmp_path):
    p = model(tmp_path, "MARKOV\n3\n2 2 2\n2\n2 0 1\n2 1 2\n4\n1 2 3 4\n4\n1 1 1 1\n", "1 0 1\n")
    r = inspect_model(p)
    assert r["pairwise_forest"] and r["forest_factor_graph"]
    assert r["binary_pairwise_bipartite"] and r["bipartition_sizes"] == [[1, 1]]
    assert len(r["inventory"]) == 6 and len(r["unobserved_inventory"]) == 4
    assert r["binding"]["model_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert r["binding"]["evidence_sha256"] == hashlib.sha256(b"1 0 1\n").hexdigest()


def test_cycle_and_duplicate_pair_factors(tmp_path):
    p = model(tmp_path, "MARKOV 3 2 2 2 3 2 0 1 2 1 2 2 2 0 4 1 1 1 1 4 1 1 1 1 4 1 1 1 1")
    r = inspect_model(p)
    assert not r["pairwise_forest"] and not r["binary_pairwise_bipartite"]
    p = model(tmp_path, "MARKOV 2 2 2 2 2 0 1 2 1 0 4 1 1 1 1 4 1 1 1 1")
    r = inspect_model(p)
    assert r["pairwise_forest"] and not r["forest_factor_graph"]
    assert r["binary_pairwise_bipartite"]


def test_tiny_positive_is_not_zero(tmp_path):
    p = model(tmp_path, "MARKOV 1 2 1 1 0 2 1e-100000 -0.000e-30")
    r = inspect_model(p)
    assert r["hard_zero_entries"] == 1 and r["zero_fraction"] == 0.5
    assert r["binding"]["evidence_sha256"] == hashlib.sha256(b"0").hexdigest()


@pytest.mark.parametrize("values", ["-1 1", "1/0 1", "NaN 1", "1e999999999999999 1"])
def test_invalid_numeric_tokens(tmp_path, values):
    p = model(tmp_path, "MARKOV 1 2 1 1 0 2 " + values)
    with pytest.raises(PlanningRefused) as error:
        inspect_model(p)
    assert error.value.kind in ("INVALID_TASK", "BITS")
    assert error.value.inventory == [(0, 0), (0, 1)]


def test_deadline_and_memory_refuse_before_inventory(tmp_path):
    p = model(tmp_path, "MARKOV 1 2 0")
    with pytest.raises(PlanningRefused) as error:
        inspect_model(p, deadline=time.monotonic()-1)
    assert error.value.kind == "DEADLINE"
    with pytest.raises(PlanningRefused) as error:
        inspect_model(p, memory_bytes=1000)
    assert error.value.kind == "MEMORY"


def test_higher_arity_forest_is_not_legacy_forest(tmp_path):
    p = model(tmp_path, "MARKOV 3 2 2 2 1 3 0 1 2 8 " + "1 "*8)
    r = inspect_model(p)
    assert r["forest_factor_graph"] and not r["pairwise_forest"]
    assert not r["binary_pairwise_bipartite"]


def test_optional_forecast_refusal_keeps_valid_metadata(tmp_path, monkeypatch):
    import pgm.planning as planning
    p = model(tmp_path, "MARKOV 1 2 0")
    def refuse(*args):
        raise PlanningRefused("MEMORY", "injected optional graph refusal")
    monkeypatch.setattr(planning.features, "_forecast", refuse)   # the inspector lives in pgm.planning.features (consolidation step 1)
    r = planning.inspect_model(p)
    assert r["cards"] == [2] and r["physical_volume"] is None
    assert r["forecast_refusal"]["kind"] == "MEMORY"


def test_table_shape_and_trailing_tokens(tmp_path):
    for source in ["MARKOV 1 2 1 1 0 1 1", "MARKOV 1 2 0 garbage"]:
        with pytest.raises(PlanningRefused) as error:
            inspect_model(model(tmp_path, source))
        assert error.value.kind == "INVALID_TASK"
