"""The installed library owns every method; research is not a runtime dependency."""
from pathlib import Path
import ast
import os
import subprocess
import sys

import pytest

import pgm
from pgm import registry
from pgm.switchboard import resolve_method
from pgm.runtime.resources import native_cache_dir, writable_home

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_tree_has_been_removed():
    assert not (ROOT / "code").exists()


def test_registered_methods_are_canonical_and_metadata_cannot_change_dispatch():
    for name in ("structural", "block", "quotient", "response", "cbi", "sf", "cqr", "h4"):
        handle = pgm.method(name)
        assert handle.name == name
        assert handle.api is resolve_method(name).api
        assert handle.api.__name__.startswith("pgm.")
        with pytest.raises(TypeError):
            handle.metadata["status"] = "selectable"
        with pytest.raises(AttributeError):
            handle._name = "block"
    with pytest.raises(TypeError):
        pgm.method("block").metadata["policies"][0] = "fake"
    assert registry.selectable_backends() == ("structural", "block", "quotient", "response")
    for name in ("cbi", "sf", "cqr", "h4"):
        with pytest.raises(ValueError, match="not a generic UAI backend"):
            registry.backend(name)
    for name in ("frozen_snapshots", "missing", "__import__", None, []):
        with pytest.raises(ValueError, match="unknown method"):
            pgm.method(name)


def test_provider_lookup_is_lazy_and_does_not_import_research():
    script = """
import sys
import pgm
for name in ('cbi', 'sf', 'cqr', 'h4'):
    assert pgm.method(name).name == name
assert not any(n.startswith(('pgm.algorithms.', 'pgm.specialists.', 'research.')) for n in sys.modules)
"""
    run = subprocess.run([sys.executable, "-c", script], env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                         cwd=ROOT.parent, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr


def test_production_has_no_research_or_legacy_imports():
    forbidden = {"research", "cex", "cbi", "sf", "h4a", "gbidi", "ext", "bench"}
    faults = []
    for path in (ROOT / "src/pgm").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in forbidden for name in names):
                faults.append((str(path.relative_to(ROOT)), node.lineno, names))
    assert not faults


def test_writable_source_is_never_a_native_output_directory(tmp_path, monkeypatch):
    owner = tmp_path / "source" / "structural"
    owner.mkdir(parents=True)
    monkeypatch.delenv("PGM_NATIVE_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "user-cache"))
    expected = tmp_path / "user-cache/pgm/native_cache/structural"
    assert Path(native_cache_dir(owner)) == expected
    assert Path(writable_home(owner)) == expected
    assert not list(owner.iterdir())
    monkeypatch.setenv("PGM_NATIVE_CACHE", str(tmp_path / "explicit-cache"))
    assert Path(writable_home(owner)) == tmp_path / "explicit-cache/structural"
