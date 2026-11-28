"""Certified discrete inference through one supported API.

Public objects are loaded on first access.  In particular, starting the owned
process supervisor must not import the inference request, planner or engines.
"""
__all__ = ["infer", "InferenceRequest", "InferenceResult", "capabilities", "method"]
__version__ = "0.2.0"


def __getattr__(name):
    if name == "infer":
        from .api import infer
        value = infer
    elif name in {"InferenceRequest", "InferenceResult"}:
        from . import contracts
        value = getattr(contracts, name)
    elif name == "capabilities":
        from .registry import capabilities
        value = capabilities
    elif name == "method":
        from .registry import method
        value = method
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
