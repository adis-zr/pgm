"""Source-checkout setup for research commands, never imported by production.

Commands may run with ``python -m research.campaigns...`` from the repository.
Direct script entry points bind the repository before calling this function.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys
from research.paths import repo_root, subprocess_env


def activate() -> None:
    source = (repo_root() / "src").resolve()
    loaded = sys.modules.get("pgm")
    if loaded is not None:
        actual = Path(loaded.__file__).resolve().parents[1]
        if actual != source:
            raise ImportError(f"research command requires this checkout's pgm: {source}, loaded {actual}")
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    os.environ["PYTHONPATH"] = subprocess_env()["PYTHONPATH"]
