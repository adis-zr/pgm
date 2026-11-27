"""Explicit runtime resource locations for the native kernels (no checkout-relative assumptions).

Sources, strict-FP flags and build records live WITH the owning implementation (``pgm.algorithms.*``).  Compiled
binaries are content-addressed under a cache directory: ``$PGM_NATIVE_CACHE`` when set, else ``native_cache/``
next to the owning module when that directory is writable (the source-checkout behaviour, unchanged), else a
per-user cache (``$XDG_CACHE_HOME/pgm/native_cache`` or ``~/.cache/pgm/native_cache``).  Build records and host
build targets follow the same rule through ``writable_home``.
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
    owner = Path(owner_dir)
    if os.access(owner, os.W_OK):
        return str(owner / "native_cache")
    return str(_user_cache() / owner.name)


def writable_home(owner_dir) -> str:
    """where the owning implementation may write its build target / build record: the module directory when writable, else the cache"""
    owner = Path(owner_dir)
    if os.access(owner, os.W_OK) and not os.environ.get("PGM_NATIVE_CACHE"):
        return str(owner)
    home = Path(native_cache_dir(owner_dir)); home.mkdir(parents=True, exist_ok=True)
    return str(home)
