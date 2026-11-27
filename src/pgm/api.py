"""Supported inference API. Campaign modules and backend flags are private."""
from .contracts import InferenceRequest, InferenceResult


def infer(model=None, *, request=None, budget=20.0, memory_mib=3072,
          epsilon="1/200", delta="1/1000000", seed=1, mode="auto", queries=None, policy="accepted") -> InferenceResult:
    """Certified singleton marginals of a UAI model.

    ``mode`` is the permitted GUARANTEE (auto / deterministic / exact); ``policy`` is the public SCHEDULING
    policy: ``accepted`` (default; the accepted engine through the common contract) or ``experimental``
    (the frozen ``structural-portfolio-1`` switchboard).  Callers never select an internal algorithm.
    """
    if request is not None:
        if model is not None or not isinstance(request, InferenceRequest):
            raise TypeError("pass an InferenceRequest or a model path")
    else:
        if model is None:
            raise TypeError("a model path is required")
        request = InferenceRequest(model, budget, memory_mib, epsilon, delta, seed, mode, queries, policy)
    from .switchboard import solve
    return solve(request)
