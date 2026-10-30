"""The numerical guard (Gate A).

A planning-only observation must never produce or read a marginal. While the
guard is installed, every numerical entry point -- executor dispatch, checker
dispatch, the identity solver's marginal production, the program executor,
the collective evaluators -- refuses with `GuardViolation`. The planning
driver installs it for the whole run; the acceptance matrix's guard control
verifies that an executor entry fails under it.
"""
from __future__ import annotations


class GuardViolation(RuntimeError):
    """A numerical executor or checker was entered during a planning-only run."""


NUMERICAL_GUARD = False
ENTRIES = []          # every guarded entry point touched while the guard was ON


def install(on: bool):
    global NUMERICAL_GUARD
    NUMERICAL_GUARD = bool(on)
    if on:
        del ENTRIES[:]


def numerical_entry(where: str):
    """Call at every numerical entry point; raises under the guard."""
    if NUMERICAL_GUARD:
        ENTRIES.append(str(where))
        raise GuardViolation("numerical entry %r refused: planning-only run" % where)
