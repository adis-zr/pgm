"""Step-1 consolidation: the single input boundary, the binding check across the worker boundary, the explicit backend
configuration, the callable response solver (no argv, no file), the parse / infer seam of the accepted engine and the
compatibility entrypoints."""
import json, os, subprocess, sys, time
from fractions import Fraction as F
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "parity" / "fixtures"
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"))


def worker(tmp_path, model, *extra, budget=8.0):
    out = tmp_path / "w.json"
    cmd = [PY, "-m", "pgm.backends.worker", "--backend", "block", "--input", str(model), "--output", str(out), "--deadline", repr(time.monotonic() + budget),
           "--memory-mib", "512", "--delta", "1/1000000", *extra]
    p = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=budget + 30)
    assert out.exists(), p.stderr[-1500:]
    return json.loads(out.read_text())


def test_one_input_boundary_binding_and_inventory():
    from pgm.model import load_bound, read_uai, original_inventory
    from pgm.backends.worker import read_inventory
    b = load_bound(FIX / "asym2_evidence.uai")
    model, binding = read_uai(FIX / "asym2_evidence.uai")
    assert b.binding == binding and b.model == model
    assert b.inventory == original_inventory(model) and all(v not in model["evidence"] for v, _ in b.inventory)
    assert len(b.all_inventory) == sum(model["cards"]) and b.binding["evidence_sha256"] != read_uai(FIX / "asym2.uai")[1]["evidence_sha256"]
    assert read_inventory(FIX / "asym2_evidence.uai", 1 << 28) == (b.inventory, b.binding)
    assert all(isinstance(v, F) for f in model["factors"] for v in f["values"])


def test_source_refusals_are_typed(tmp_path):
    from pgm.model import load_bound, SourceRefused
    bad = tmp_path / "bad.uai"; bad.write_text("MARKOV\n1\n2\n1\n1 0\n3\n0.5 0.5 0.5\n")
    with pytest.raises(SourceRefused) as e: load_bound(bad)
    assert e.value.kind == "INVALID_TASK"
    with pytest.raises(SourceRefused) as e: load_bound(FIX / "asym2.uai", expected_binding=dict(model_sha256="0" * 64, evidence_sha256="0" * 64))
    assert e.value.kind == "BINDING"


def test_worker_refuses_a_binding_mismatch_typed(tmp_path):
    wrong = json.dumps(dict(model_sha256="0" * 64, evidence_sha256="0" * 64))
    r = worker(tmp_path, FIX / "asym2.uai", "--expected-binding", wrong)
    assert r["outcome"] == "BINDING" and r["published"] == 0 and r["mechanism"]["adapter_refusal"]["kind"] == "BINDING"
    assert all(row["guarantee"] == "NOT_PUBLISHED" for row in r["answers"]) and r["K"] == 4


def test_worker_records_policy_and_explicit_configuration(tmp_path):
    from pgm.policies import accepted
    cfg = json.dumps(accepted.candidates(None, None, 10.0)[0]["configuration"], sort_keys=True)
    from pgm.model import read_uai
    binding = json.dumps(read_uai(FIX / "asym2.uai")[1], sort_keys=True)
    r = worker(tmp_path, FIX / "asym2.uai", "--policy", "accepted", "--configuration", cfg, "--expected-binding", binding)
    assert r["outcome"] == "COMPLETE" and r["policy"] == "accepted" and r["configuration"]["schedule"] == "targeted" and r["configuration"]["table_cap"] == 1 << 18
    assert r["binding"] == json.loads(binding) and r["published"] == r["K"] == 4


def test_accepted_engine_parse_infer_seam_reuses_the_bound_model():
    from pgm.backends import block
    from pgm.model import load_bound
    integrated = block.module()
    b = load_bound(FIX / "asym2.uai")
    r1 = integrated.solve(str(b.path), 5.0, seed=1, route="exact", schedule="targeted", model=b.model, binding=b.binding)
    r2 = integrated.solve(str(b.path), 5.0, seed=1, route="exact", schedule="targeted")
    assert r1["binding"] == b.binding == r2["binding"]
    rows = lambda r: [(a["var"], a["state"], a.get("lo"), a.get("hi"), a.get("point"), a["guarantee"]) for a in r["answers"]]
    assert rows(r1) == rows(r2) and r1["outcome"] in {"COMPLETE", "EXACT"}


def test_response_solver_is_callable_without_argv_or_files(tmp_path, monkeypatch):
    from pgm.backends import response
    from pgm.model import load_bound
    runner = response.module()
    b = load_bound(FIX / "pos4.uai")
    argv_before = list(sys.argv); monkeypatch.chdir(tmp_path)
    r = runner.solve_response(b.model, b.binding, budget=2.5, admission_stop=2.0, seed=1, epsilon=F(1, 200), delta=F(1, 10**6), policy="revised", response=True, input_path=str(b.path))
    assert sys.argv == argv_before and list(tmp_path.iterdir()) == []
    assert r["binding"] == b.binding and r["K"] == 8 and r["mechanism"]["route"] == "spectral_heatbath_response"
    assert r["outcome"] in {"COMPLETE", "PARTIAL", "DEADLINE", "REFUSED"} and r["positive_mass_witness"] is True
    assert all(("--%s" % k) in {opt for opt, _ in r["argv"]} for k in ("budget", "seed", "response"))


def test_compatibility_entrypoints_import():
    import pgm.supervision, pgm.build, pgm.runtime.supervision, pgm.runtime.build, pgm.runtime.attempts, pgm.validation.publication, pgm.planning.features
    assert pgm.supervision.main is pgm.runtime.supervision.main and pgm.build.main is pgm.runtime.build.main
    from pgm.backends.worker import normalize_result, read_inventory, write_result, AdapterRefused
    from pgm.switchboard import run_attempt, POLICY_VERSION, NATIVE_ROWS_PER_SECOND
    assert POLICY_VERSION == "structural-portfolio-1" and NATIVE_ROWS_PER_SECOND == 20_000_000
