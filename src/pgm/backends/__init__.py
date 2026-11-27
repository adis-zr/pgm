"""Explicit backend adapters, one per implementation family, run in an isolated worker process.

Each adapter has explicit inputs (the request-local ``BoundModel``, the attempt context) and returns the
implementation's candidate result / certificate or raises a typed ``AdapterRefused``.  Cheap support screening
is the policy's job from the planner's facts; the adapters perform the expensive construction only.  Adapters
import their implementations by fully qualified name from ``pgm.algorithms``.
"""
from .base import AdapterContext, memory_policy, remaining

__all__ = ["AdapterContext", "memory_policy", "remaining"]
