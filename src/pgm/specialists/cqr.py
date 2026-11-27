"""CQR: the general finite query / normalizer language (``code/cex/cqr``), explicit API, checkout-only.

``load_task(model_path, mode=None)`` reads the model through the shared exact reader plus an optional
``<model>.query.json`` (singleton / all_singletons / joint / parity / conditional / table queries, mode, epsilon,
delta, normalizer_task); ``solve(task, deadline, arm, seed, ...)`` runs one arm with its checked certificates.
Nothing here reinterprets a general query as singleton inference."""
from __future__ import annotations

from ._bridge import ensure_cqr, SpecialistUnavailable  # noqa: F401


def modules():
    ensure_cqr()
    import task as TK, solve as SV, checker as CK      # the cqr package's own module names (bare sibling imports)
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
