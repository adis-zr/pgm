"""Publication-boundary checks independent of the numerical engines."""
from fractions import Fraction as F
import json
from pathlib import Path
import time

import pytest
from pgm.backends.worker import AdapterRefused, normalize_result, read_inventory, write_result

BINDING = {"model_sha256": "model", "evidence_sha256": "evidence"}
INVENTORY = [(0, 0), (0, 1)]


def result(rows, **extra):
    return dict(answers=rows, positive_mass_witness=True, binding=BINDING,
                outcome="COMPLETE", **extra)


def row(state, lo="1/2", hi="1/2", point="1/2", guarantee="EXACT"):
    return dict(var=0, state=state, lo=lo, hi=hi, point=point, guarantee=guarantee)


def test_legacy_tolerance_does_not_become_a_stricter_answer():
    raw = result([row(0, "49/100", "51/100", guarantee="DETERMINISTIC"), row(1)])
    actual = normalize_result(raw, INVENTORY, BINDING, F(1, 200))
    assert actual["published"] == 1
    assert actual["outcome"] == "PARTIAL"
    assert actual["answers"][0] == dict(var=0, variable=0, state=0, guarantee="NOT_PUBLISHED")


def test_duplicate_coordinates_do_not_masquerade_as_complete():
    with pytest.raises(AdapterRefused, match="duplicate coordinate"):
        normalize_result(result([row(0), row(0)]), INVENTORY, BINDING, F(1, 200))


def test_exact_label_requires_exact_geometry():
    with pytest.raises(AdapterRefused, match="EXACT label"):
        normalize_result(result([row(0, "49/100", "51/100"), row(1)]), INVENTORY, BINDING, F(1, 200))


def test_positive_mass_is_required_for_any_published_answer():
    raw = result([row(0), row(1)])
    raw["positive_mass_witness"] = None
    with pytest.raises(AdapterRefused, match="positive-mass witness"):
        normalize_result(raw, INVENTORY, BINDING, F(1, 200))


def test_late_commit_retains_inventory_and_suppresses_every_row(tmp_path):
    actual = normalize_result(result([row(0), row(1)]), INVENTORY, BINDING, F(1, 200))
    actual["enclosures"] = [dict(var=0, lo="0", hi="1")]
    path = tmp_path / "result.json"
    write_result(path, actual, INVENTORY, time.monotonic() - 1, time.monotonic() - 2)
    delivered = json.loads(path.read_text())
    assert delivered["K"] == 2 and delivered["published"] == 0
    assert delivered["outcome"] == "DEADLINE"
    assert delivered["enclosures"] == []
    assert all(r["guarantee"] == "NOT_PUBLISHED" for r in delivered["answers"])


def test_inventory_uses_original_nonobserved_coordinates(tmp_path):
    path = tmp_path / "model.uai"
    path.write_text("MARKOV\n2\n2 3\n0\n")
    Path(str(path) + ".evid").write_text("1 0 1\n")
    inventory, binding = read_inventory(path, 1 << 20)
    assert inventory == [(1, 0), (1, 1), (1, 2)]
    assert len(binding["model_sha256"]) == len(binding["evidence_sha256"]) == 64


def test_coordinate_boxes_must_admit_the_simplex():
    with pytest.raises(AdapterRefused, match="simplex"):
        normalize_result(result([row(0, "1/3", "1/3", "1/3"), row(1, "1/3", "1/3", "1/3")]), INVENTORY, BINDING, F(1, 200))
