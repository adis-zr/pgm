"""CBI: native coupled binary blocks on a SUPPLIED product-kernel block representation (``code/cbi``).

``load_model(path)`` reads the explicit block model (JSON); ``solve(model, queries='all', requested_width='1/100',
limits=None)`` returns CERTIFIED / VALID_BUT_TOO_WIDE / INFEASIBLE / UNSUPPORTED_INPUT / RESOURCE_LIMIT with proofs;
``verify(model, result)`` is the independent checker.  Automatic construction from arbitrary UAI tables is not assumed
(the historical UAI adapter is benchmark tooling: ``code/bench/cbi_adapter.py``)."""
from __future__ import annotations

from ._bridge import ensure_package, SpecialistUnavailable  # noqa: F401


def modules():
    ensure_package("cbi")
    from cbi import api, model
    return api, model


def load_model(path):
    _, model = modules()
    return model.Model.load(str(path))


def solve(model, queries="all", requested_width="1/100", limits=None):
    api, _ = modules()
    return api.solve(model, queries, requested_width, limits)


def verify(model, result):
    api, _ = modules()
    return api.verify(model, result)
