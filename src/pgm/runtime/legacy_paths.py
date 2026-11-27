"""The ISOLATED legacy import bridge (unfinished-integration item, listed in the migration manifest).

Retained implementation modules that still live under ``code/`` use bare imports (``import core``, ``import
integrated`` ...).  Until a closure is relocated under ``pgm.algorithms`` with fully qualified imports, its
adapter resolves the checkout / installed layout here and nowhere else.  Production modules under ``pgm`` must
not manipulate ``sys.path`` themselves.
"""
from __future__ import annotations

from pathlib import Path
import sys


class InstallationRefused(Exception):
    pass


def code_root() -> Path:
    """Resolve the ``code/`` tree of a source checkout or of the installed distribution without a workstation path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "code"
        if (candidate / "cex" / "newarm" / "core.py").is_file():
            return candidate
    import importlib.util
    spec = importlib.util.find_spec("cex.newarm")
    if spec and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).parent.parent
    raise InstallationRefused("retained inference packages are absent")


def install_paths(subdirs=("", "cex/newarm", "cex/blockres", "cex/hp")) -> Path:
    code = code_root()
    for suffix in subdirs:
        path = str(code / suffix) if suffix else str(code)
        if path not in sys.path:
            sys.path.insert(0, path)
    return code
