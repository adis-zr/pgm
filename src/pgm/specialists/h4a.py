"""H4 arithmetic / signed modes (``code/h4a``): a FIXED arithmetic cohort with native producer / checker kernels
(``code/native/*.cpp`` built on the host into ``code/build``).  Reference-only: its mathematics and provenance are
retained; it is not a generic UAI recognizer.  ``available()`` reports whether the host kernels are built;
``model()`` / ``masses()`` expose the arithmetic modules; ``arm_main(argv)`` runs one cold bundle (subprocess driver)."""
from __future__ import annotations

from pathlib import Path

from ._bridge import ensure_package, package_root, SpecialistUnavailable  # noqa: F401

KERNELS = ("h4point", "h4rect", "h4pcheck")


def available():
    root = package_root("h4a")
    if root is None:
        return dict(available=False, reason="h4a package absent")
    build = Path(root) / "build"
    missing = [k for k in KERNELS if not (build / k).is_file()]
    return dict(available=not missing, build_dir=str(build), missing_kernels=missing)


def model():
    ensure_package("h4a")
    from h4a import model as M
    return M


def masses():
    ensure_package("h4a")
    from h4a import masses as MS
    return MS


def arm_main():
    ensure_package("h4a")
    from h4a import arm
    return arm.main
