"""CQR: the installed general finite query / normalizer language, explicit API.

``load_task(model_path, mode=None)`` reads the model through the shared exact reader plus an optional
``<model>.query.json`` (singleton / all_singletons / joint / parity / conditional / table queries, mode, epsilon,
delta, normalizer_task); ``solve(task, deadline, arm, seed, ...)`` runs one arm with its checked certificates.
Nothing here reinterprets a general query as singleton inference."""
from __future__ import annotations

from .errors import SpecialistUnavailable  # compatibility export

def modules():
    from pgm.algorithms.cqr import task as TK, solve as SV, checker as CK
    return TK, SV, CK


def load_task(model_path, mode=None):
    TK, _, _ = modules()
    return TK.load_task(str(model_path), mode)


def solve(task, deadline, arm, seed, **kw):
    _, SV, _ = modules()
    return SV.solve(task, deadline, arm, seed, **kw)


def arms():
    _, SV, _ = modules()
    return sorted(SV.ARMS)
