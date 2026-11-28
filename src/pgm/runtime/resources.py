"""Explicit runtime resource locations for the native kernels (no checkout-relative assumptions).

Sources, strict-FP flags and build records live WITH the owning implementation (``pgm.algorithms.*``).  Compiled
binaries are content-addressed under ``$PGM_NATIVE_CACHE`` when set, else a per-user
cache (``$XDG_CACHE_HOME/pgm/native_cache`` or ``~/.cache/pgm/native_cache``).
Build records and host build targets follow the same rule through ``writable_home``.
Neither a source checkout nor an installed package is a build-output directory.
"""
from __future__ import annotations

import os
from pathlib import Path


def _user_cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "pgm" / "native_cache"


def native_cache_dir(owner_dir) -> str:
    """the content-addressed binary cache for the implementation living in ``owner_dir``"""
    env = os.environ.get("PGM_NATIVE_CACHE")
    if env:
        return str(Path(env) / Path(owner_dir).name)
    return str(_user_cache() / Path(owner_dir).name)


def writable_home(owner_dir) -> str:
    """Writable build output outside the owning implementation's source directory."""
    home = Path(native_cache_dir(owner_dir)); home.mkdir(parents=True, exist_ok=True)
    return str(home)
