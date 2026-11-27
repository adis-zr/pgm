"""Specialist entrypoints stay explicit and reachable; the registry distinguishes selectable / specialist / reference /
historical / unfinished and every selectable owner is importable."""
import importlib
from pathlib import Path

import pytest

import pgm
from pgm import registry
from pgm.specialists import cbi, sf, h4a, cqr

FIX = Path(__file__).resolve().parents[1] / "tests" / "parity" / "fixtures"


def test_registry_statuses_and_owners():
    caps = pgm.capabilities()
    statuses = {v["status"] for v in caps.values()}
    assert statuses == {"selectable", "specialist", "reference", "historical", "unfinished"}
    selectable = {k: v for k, v in caps.items() if v["status"] == "selectable"}
    assert set(selectable) == {"structural", "block", "quotient", "response"}
    for name, cap in selectable.items():
        importlib.import_module(cap["owner"]); importlib.import_module(cap["adapter"])
        assert cap["entrypoint"] and cap["admission"] and cap["guarantees"]
    assert "accepted (default)" in caps["block"]["policies"] and caps["structural"]["policies"] == ["experimental"]
    caps["block"]["status"] = "x"; assert registry.CAPABILITIES["block"]["status"] == "selectable"     # a copy


def test_cbi_and_sf_entrypoints_import_their_implementations():
    api, model = cbi.modules(); assert callable(api.solve) and callable(api.verify) and hasattr(model, "Model")
    core, routes, check = sf.modules(); assert hasattr(core, "Law") and callable(core.select) and check is sf.checker()


def test_h4a_is_reference_only_with_an_availability_report():
    rep = h4a.available(); assert set(rep) >= {"available"} and isinstance(rep["available"], bool)
    assert hasattr(h4a.model(), "Model")


def test_cqr_explicit_task_language():
    task = cqr.load_task(FIX / "asym2.uai")
    assert task["all_singletons"] is True and len(task["queries"]) == 4 and task["mode"] == "PAC_EPS" and task["binding"]["query_sha256"] is None
    assert "A" in cqr.arms() or len(cqr.arms()) >= 1


def test_production_never_imports_the_specialist_bridge_or_campaign_code():
    import os, subprocess, sys
    code = ("import sys, pgm.api, pgm.switchboard, pgm.runtime.attempts, pgm.backends.worker, pgm.backends.structural, pgm.backends.block, pgm.backends.quotient, pgm.backends.response;"
            "import pgm.algorithms.structural.core, pgm.algorithms.block.integrated, pgm.algorithms.quotient.unified_pac_planner, pgm.algorithms.response.spectral_heatbath_run, pgm.runtime.supervise;"
            "bad=[m for m in sys.modules if m.startswith('pgm.specialists') or '/code/' in ((getattr(sys.modules[m],'__file__','') or '').replace(chr(92),'/')) and m.startswith('pgm')];"
            "legacy=[m for m in ('core','integrated','coarse_envelope','spectral_heatbath_run','gbidi.supervise') if m in sys.modules];"
            "print(bad, legacy); assert not bad and not legacy")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stdout + p.stderr
