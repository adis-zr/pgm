"""Bind migrated review probes to their claimed source checkout.

Current probes import canonical modules only from this repository. Historical
before/after runs execute byte-preserved probe source in a fresh isolated Python
process, with local module imports restricted to the explicitly requested tree.
A missing target module is an error, never a fallback to the current checkout.
"""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from research.paths import repo_root

THIRD_PARTY = {"numpy", "scipy", "psutil", "gmpy2", "mpmath"}

# Kept in an isolated child: no module from this research package is imported there.
ISOLATED_RUNNER = r'''
import importlib.abc, importlib.machinery, json, pathlib, runpy, sys
cfg = json.loads(sys.argv[1])
root = pathlib.Path(cfg["source"]).resolve()
paths = cfg["paths"]
trusted = set(cfg["trusted"])
class TargetOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in trusted:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path if path is not None else paths)
        if spec is None:
            raise ImportError("requested source lacks required local module: " + fullname)
        locations = list(spec.submodule_search_locations or [])
        if spec.origin and spec.origin not in ("built-in", "frozen"):
            locations.append(spec.origin)
        if not locations or any(not pathlib.Path(p).resolve().is_relative_to(root) for p in locations):
            raise ImportError("refusing local module outside requested source: " + fullname)
        return spec
sys.meta_path.insert(0, TargetOnly())
sys.path[:0] = paths
sys.argv = [cfg["probe"]] + cfg["argv"]
runpy.run_path(cfg["probe"], run_name="__main__")
'''


def _local_imports(probe: Path) -> set[str]:
    names = set()
    for node in ast.parse(probe.read_text()).body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".", 1)[0])
    return names - sys.stdlib_module_names - THIRD_PARTY


def historical_command(source, probe, argv):
    """Prepare an isolated launch, rejecting missing target dependencies up front."""
    source, probe = Path(source).resolve(), Path(probe).resolve()
    if not source.is_dir() or not probe.is_file():
        raise ValueError("requested source checkout or preserved probe is missing")
    folders = [source / "code/cex/hp", source / "code/cex/blockres", source / "code/cex/newarm",
               source / "code/cex/cqr", source / "code", source / "src"]
    required = _local_imports(probe)
    missing = sorted(name for name in required if not any((p / (name + ".py")).is_file() or (p / name / "__init__.py").is_file() for p in folders))
    if missing:
        raise ValueError("requested source lacks required probe/runtime modules: " + ", ".join(missing))
    guarded = required | {"pgm", "research"}
    for folder in folders[:4]:
        if folder.is_dir():
            guarded.update(p.stem for p in folder.glob("*.py") if p.stem not in sys.stdlib_module_names)
    cfg = dict(source=str(source), probe=str(probe), argv=list(argv), paths=[str(p) for p in folders if p.is_dir()], guarded=sorted(guarded), trusted=sorted(sys.stdlib_module_names | THIRD_PARTY))
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    return [sys.executable, "-I", "-c", ISOLATED_RUNNER, json.dumps(cfg)], env


def bind_source(source, probe_name, argv=None):
    """Return only for this checkout; historical requests finish in an isolated child."""
    source = Path(source).resolve()
    if source == repo_root().resolve():
        return str(source)
    archive = repo_root() / "research/archive/dgp_review_probes" / probe_name
    try:
        command, env = historical_command(source, archive, sys.argv[1:] if argv is None else argv)
    except ValueError as exc:
        raise SystemExit("SOURCE_BINDING_REFUSED: " + str(exc)) from exc
    result = subprocess.run(command, cwd=source, env=env)
    raise SystemExit(result.returncode)
