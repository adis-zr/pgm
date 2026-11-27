"""Bounded, read-only structural facts for the public policies (``pgm.planning.features``).

The inspector streams the source once lexically (validating numbers without a floating conversion, hashing the
bytes, fixing the original inventory and the factor scopes) and derives structural facts: pairwise forest, binary
bipartite components, effective arity, hard zeros, and the OPTIONAL min-product physical forecast.  It constructs
no inference model; backends check their own applicability.  This pass is the one remaining parse besides the
worker's exact parse (``pgm.model.uai``); both are charged to the request.
"""
from .features import PlanningRefused, inspect_model

__all__ = ["PlanningRefused", "inspect_model"]
