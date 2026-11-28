"""Fixed-cohort H4 arithmetic specialist, with package-owned source and host kernels.

This is not a generic UAI recognizer. ``available()`` checks the external host
cache; ``model()`` and ``masses()`` expose the retained arithmetic modules;
``arm_main()`` returns the callable cold-bundle runner. Builds are explicit via
``python -m pgm.algorithms.h4.kernels`` and never use historical pinned binaries.
"""
from __future__ import annotations

from ..algorithms.h4.kernels import KERNELS
from .errors import SpecialistUnavailable  # retained shared public exception identity


def available():
    from ..algorithms.h4.kernels import available as check
    return check()


def model():
    from ..algorithms.h4 import model as M
    return M


def masses():
    from ..algorithms.h4 import masses as MS
    return MS


def arm_main():
    from ..algorithms.h4 import arm
    return arm.main
