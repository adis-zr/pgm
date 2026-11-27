"""Certified discrete inference through one supported API."""
from .api import infer
from .contracts import InferenceRequest, InferenceResult
from .registry import capabilities
__all__ = ["infer", "InferenceRequest", "InferenceResult", "capabilities"]
__version__ = "0.1.0"
