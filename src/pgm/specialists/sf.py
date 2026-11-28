"""SF: the sparse / Fourier bridge on a SUPPLIED sparse two-block law: two weighted binary-mask supports
A / B (n <= 63) coupled by the product bridge r; route selection (sparse / Fourier / exact / Walsh) with the independent
checker.  ``law(...)`` validates the input law (``sf.core.Law``); ``select(...)`` is the online selector; ``check`` is the
checker module."""
from __future__ import annotations

from .errors import SpecialistUnavailable  # retained public exception import


def modules():
    from ..algorithms.sf import core, routes, check
    return core, routes, check


def law(*args, **kw):
    core, _, _ = modules()
    return core.Law(*args, **kw)


def select(law_, r, eps, symmetric, Pint0, log=None):
    core, _, _ = modules()
    return core.select(law_, r, eps, symmetric, Pint0, log=log)


def checker():
    return modules()[2]
