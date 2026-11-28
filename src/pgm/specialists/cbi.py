"""CBI: coupled binary blocks on a SUPPLIED product-kernel block representation.

``load_model(path)`` reads the explicit block model (JSON); ``solve(model, queries='all', requested_width='1/100',
limits=None)`` returns CERTIFIED / VALID_BUT_TOO_WIDE / INFEASIBLE / UNSUPPORTED_INPUT / RESOURCE_LIMIT with proofs;
``verify(model, result)`` is the independent checker.  Automatic construction from arbitrary UAI tables is not assumed
(the historical UAI adapter is benchmark tooling: ``benchmarks/external/tools/cbi_adapter.py``)."""
from __future__ import annotations

from .errors import SpecialistUnavailable  # retained public exception import


def modules():
    from ..algorithms.cbi import api, model
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
