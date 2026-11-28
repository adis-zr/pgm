"""STEP2_AMENDMENT_1 harness preflight: native resources resolve from the owning implementation (no deleted code/cex/newarm
paths), PGM_NATIVE_CACHE is honoured by the probe, the arms / pairs / contracts are consistent, and the historical reference
cells bind to the current input manifests by hash."""
import importlib.util, json, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_suite", ROOT / "benchmarks/external/run_suite.py"); h = importlib.util.module_from_spec(spec); sys.modules["run_suite"] = h; spec.loader.exec_module(h)


def _have_compilers():
    return bool(os.environ.get("CC")) and bool(os.environ.get("CXX"))


def test_arms_pairs_contracts_consistent():
    assert len(h.ARMS) == 6 and set(h.RESULT_ARMS) <= set(h.ARMS) and set(h.PGM_ARMS) <= set(h.RESULT_ARMS)
    for name, (cand, comp) in h.PAIRS.items():
        assert cand in h.ARMS and comp in h.ARMS and cand != comp, name
    for arm in h.RESULT_ARMS:
        assert arm in h.CONTRACTS and h.CONTRACTS[arm]["reader"] in ("legacy", "public", "public_legacy")
    assert "code/cex/newarm" not in open(ROOT / "benchmarks/external/run_suite.py").read().replace("code/cex/newarm\", \"code/cex/blockres", "")  # only the pinned-root import roots name that directory


def test_native_probe_resolves_from_the_owning_implementation(monkeypatch, tmp_path):
    if not _have_compilers():
        pytest.skip("explicit qualified CC/CXX required for native setup")
    cache = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.delenv("PGM_NATIVE_CACHE", raising=False)
    monkeypatch.setattr(h, "NATIVE_CACHE", None)
    h._build_root("PGM_ACCEPTED")  # Build into a fresh default cache before probing.
    probe = h.native_probe("PGM_ACCEPTED")
    assert probe["native_cache"] is None
    for artifact in probe["active"]:
        owner = ROOT / "src/pgm/algorithms" if artifact["role"].endswith("_source") else cache / "pgm/native_cache"
        assert Path(artifact["path"]).resolve().is_relative_to(owner.resolve()), artifact
    paths = [a["path"] for a in probe["active"]]
    assert all("code/cex/newarm" not in p and "code/cex/hp" not in p for p in paths)
    assert {a["role"] for a in probe["active"]} == {"cex_source", "cex_record", "cex_build_target", "cex_loaded_binary", "stream_source", "stream_record", "stream_build_target", "stream_loaded_binary", "heat_source", "heat_record", "heat_loaded_binary"}
    assert all(a["sha256"] for a in probe["active"])
    files = h.host_files(); assert files and all(not f.startswith("code/cex/newarm") for f in files)


def test_native_probe_honours_pgm_native_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CC", os.environ.get("CC", "/usr/bin/clang")); monkeypatch.setenv("CXX", os.environ.get("CXX", "/usr/bin/clang++"))
    cache = tmp_path / "cache"; monkeypatch.setenv("PGM_NATIVE_CACHE", str(cache)); h.NATIVE_CACHE = str(cache)
    try:
        h._build_root("PGM_ACCEPTED")                                                # build + warm INTO the override (setup-time, not timed)
        probe = h.native_probe("PGM_ACCEPTED")
    finally:
        h.NATIVE_CACHE = None
    loaded = [a["path"] for a in probe["active"] if a["role"].endswith("loaded_binary")]
    assert loaded and all(p.startswith(str(cache)) for p in loaded), loaded
    assert probe["native_cache"] == str(cache)


def test_historical_reference_cells_bind_to_the_current_manifests():
    ref = json.loads(h.REFERENCE.read_text()); tasks = h.tasks_from_manifest(ROOT / "benchmarks/external/INPUT_MANIFEST.json") + h.tasks_from_manifest(ROOT / "benchmarks/external/HOLDOUT_FREEZE.json")
    by_name = {t["name"]: t for t in tasks}
    assert len(tasks) == 61
    for c in ref["cells"]:
        t = by_name[c["task"]]; assert c["model_sha256"] == t["model_sha256"] and c["evidence_sha256"] == t["evidence_sha256"], c["task"]
    prior29 = {r["task"] for r in ref["cells"] if r["arm"] == "PGM" and r["budget_s"] == 20 and all(any(s["task"] == r["task"] and s["arm"] == "PGM" and s["budget_s"] == 20 and s["replicate"] == rep and s["complete_within_contract"] for s in ref["cells"]) for rep in (1, 2))}
    assert len(prior29) == 29


def test_plan_declares_the_full_matrix_and_ceiling_before_scoring():
    plan = json.loads((ROOT / "benchmarks/external/STEP2_PLAN.json").read_text())
    assert plan["cells"]["total"] == 732 == 61 * 6 * 2 and plan["contract"]["scored_ceiling_s"] >= 732 * 20
    assert plan["cost_criterion"]["adopted"] is True and plan["prior_experimental_extract"]["status"].startswith("RECOVERED") and (ROOT / plan["prior_experimental_extract"]["file"]).is_file()
    sup = json.loads((ROOT / "benchmarks/external/STEP2_SUPPLEMENT_1.json").read_text())
    assert sup["cells"]["total"] == 245 == 61 * 2 * 2 + 1 and sup["contract"]["scored_ceiling_s"] == 4900 == 245 * 20 and sup["arms"] == h.SUPPLEMENT_ARMS and len(h.SUPPLEMENT_REPLAY) == 1
    assert set(plan["arms"]) == set(h.ARMS)
