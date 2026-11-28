"""Checkout and optional private-record locations for research tooling only.

Private historical records retain their own ``code/runs`` schema. The library
checkout never needs a ``code/runs`` symlink. Explicit roots are authoritative.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def records_root() -> Path | None:
    explicit = os.environ.get("PGM_RECORDS_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    sibling = repo_root().parent / "pgm-records"
    return sibling.resolve() if sibling.is_dir() else None


def runs_root() -> Path:
    records = records_root()
    return records / "code" / "runs" if records is not None else repo_root() / "research" / "runs"


def subprocess_env(overrides=None) -> dict[str, str]:
    env = os.environ.copy()
    prefix = [str(repo_root()), str(repo_root() / "src")]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(prefix + ([p for p in env["PYTHONPATH"].split(os.pathsep) if p] if env.get("PYTHONPATH") else [])))
    if overrides:
        env.update(overrides)
    return env


def source_path(module: str) -> str:
    spec = importlib.util.find_spec(module)
    if spec is None or spec.origin is None:
        raise ImportError("module has no source path: " + module)
    return spec.origin
