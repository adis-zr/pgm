"""Specialist relocation preserves checked answers and uses package-local imports."""
from fractions import Fraction as F
from itertools import product
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pgm.specialists import cbi, sf


ROWS_A = [(0, 2), (3, 1), (5, 4)]
ROWS_B = [(0, 3), (2, 5), (5, 1)]


def exact_pair_marginals(r):
    """Independent enumeration of the stated product kernel, with rational weights."""
    z = F(0)
    nums = [[F(0) for _ in range(3)] for _ in range(2)]
    for (x, a), (y, b) in product(ROWS_A, ROWS_B):
        w = F(a * b)
        for j in range(3):
            w *= 1 + r * (1 if (x >> j) & 1 else -1) * (1 if (y >> j) & 1 else -1)
        z += w
        for block, state in enumerate((x, y)):
            for j in range(3):
                if (state >> j) & 1:
                    nums[block][j] += w
    return [[n / z for n in block] for block in nums]


def block_model(r):
    return {"d": 3,
            "blocks": [{"id": i, "rows": [x for x, _ in rows],
                        "weights": [w for _, w in rows]}
                       for i, rows in enumerate((ROWS_A, ROWS_B))],
            "edges": [{"u": 0, "v": 1, "r": str(r)}]}


@pytest.mark.parametrize("r", [F(0), F(1, 3), F(1)])
def test_cbi_package_and_specialist_api_agree_with_independent_truth(r):
    api, model = cbi.modules()
    assert api.__package__ == model.__package__ == "pgm.algorithms.cbi"
    source = block_model(r)
    result = cbi.solve(source, requested_width="1/100")
    assert result["status"] == "CERTIFIED"
    assert cbi.verify(source, result)["accepted"]
    truth = exact_pair_marginals(r)
    for block, rows in result["intervals"].items():
        for j, bounds in enumerate(rows["coordinates"]):
            assert F(int(bounds["lo"]), 1 << 80) <= truth[int(block)][j] <= F(int(bounds["hi"]), 1 << 80)


@pytest.mark.parametrize("r", [F(0), F(1, 3), F(1)])
def test_sf_exact_routes_and_checker_agree_with_independent_truth(r):
    core, routes, checker = sf.modules()
    assert all(module.__package__ == "pgm.algorithms.sf" for module in (core, routes, checker))
    law = sf.law(3, ROWS_A, ROWS_B)
    truth = exact_pair_marginals(r)[0]
    symmetric, _ = law.antipodal()
    for result in (routes.route_E(law, r, symmetric), routes.route_W(law, r),
                   routes.route_F(law, r, law.n, symmetric)):
        assert result["status"] == "OK"
        assert result["intervals"] == [(value, value) for value in truth]
        result["published"] = [core.publish(lo, hi) for lo, hi in result["intervals"]]
        assert sf.checker().check(law, r, result, symmetric)["ok"]


def test_specialist_imports_do_not_activate_top_level_packages_or_change_search_path(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    script = """
import sys
before = list(sys.path)
from pgm.specialists import cbi, sf
assert cbi.modules()[0].__package__ == 'pgm.algorithms.cbi'
assert sf.modules()[0].__package__ == 'pgm.algorithms.sf'
assert sys.path == before
assert not any(k in ('cbi', 'sf') or k.startswith(('cbi.', 'sf.')) for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], env=env, cwd=tmp_path,
                   check=True, capture_output=True, text=True, timeout=20)


def test_cbi_module_cli_solves_and_independently_checks(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    source, result = tmp_path / "model.json", tmp_path / "result.json"
    source.write_text(json.dumps(block_model(F(1, 3))))
    prefix = [sys.executable, "-m", "pgm.algorithms.cbi.cli"]
    subprocess.run(prefix + ["solve", str(source), "--out", str(result)],
                   cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=20)
    checked = subprocess.run(prefix + ["verify", str(source), str(result)],
                             cwd=tmp_path, env=env, check=True, capture_output=True, text=True, timeout=20)
    assert json.loads(checked.stdout)["accepted"]


@pytest.mark.parametrize("family", ["cbi", "sf"])
def test_relocated_campaign_worker_is_executable_as_a_module(tmp_path, family):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root), str(root / "src"))),
               OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    source, result = tmp_path / "model.json", tmp_path / "result.json"
    if family == "cbi":
        source.write_text(json.dumps(block_model(F(1, 3))))
        argv = ["research.campaigns.cbi.run_case", str(source), "all", "1/100", "library", "{}", str(result)]
    else:
        source.write_text(json.dumps({"n": 3, "A": ROWS_A, "B": ROWS_B}))
        argv = ["research.campaigns.sf.invoke", "route", str(source), "1", "3", "E", str(result), "5"]
    subprocess.run([sys.executable, "-m", *argv], cwd=tmp_path, env=env,
                   check=True, capture_output=True, text=True, timeout=20)
    record = json.loads(result.read_text())
    if family == "cbi":
        assert record["status"] == "CERTIFIED" and record["verify_accepted"] is True
    else:
        assert record["status"] == "OK" and record["checker"]["status"] == "VERIFIED"
