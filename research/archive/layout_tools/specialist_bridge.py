"""The ISOLATED specialist bridge (listed as unfinished in the migration manifest).

The specialists keep their historical package layout under ``code/`` (``cbi``, ``sf``, ``h4a`` are importable packages;
``cex/cqr`` uses bare sibling imports).  This module is the ONLY place that resolves that tree: a source checkout
(``<repo>/code``) or an installed copy of the specialist packages.  Production inference (``pgm.infer``) never imports it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


class SpecialistUnavailable(Exception):
    """typed: the specialist's package is not present in this installation (kind UNAVAILABLE)"""
    kind = "UNAVAILABLE"


def code_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "code"
        if (candidate / "cbi" / "api.py").is_file() or (candidate / "cex" / "cqr" / "solve.py").is_file():
            return candidate
    return None


def package_root(name: str) -> Path | None:
    """where the top-level specialist package `name` (cbi / sf / h4a) lives, if anywhere"""
    spec = importlib.util.find_spec(name)
    if spec and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).parent
    root = code_root()
    return root if root is not None and (root / name / "__init__.py").is_file() else None


def ensure_package(name: str):
    root = package_root(name)
    if root is None:
        raise SpecialistUnavailable("specialist package %r is not installed and no source checkout is present" % name)
    if str(root) not in sys.path:
        sys.path.append(str(root))        # appended, never prepended: the specialist tree cannot shadow pgm or the stdlib
    return root


def ensure_cqr():
    root = code_root()
    if root is None or not (root / "cex" / "cqr" / "solve.py").is_file():
        raise SpecialistUnavailable("the CQR specialist is available only from a source checkout (code/cex/cqr; bare sibling imports)")
    for sub in ("cex/cqr", "cex/newarm"):
        p = str(root / sub)
        if p not in sys.path:
            sys.path.append(p)
    return root / "cex" / "cqr"
