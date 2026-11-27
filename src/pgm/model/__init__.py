"""ONE input boundary: source / evidence bytes and hashes, original cardinalities, the original query inventory, exact
numeric parsing and validated factor scopes (``pgm.model.uai``).  Backends consume the validated model through
explicit arguments; their own canonicalizations / reductions / decoders keep their existing proof obligations."""
from .uai import BoundModel, load_bound, read_uai, original_inventory, SourceRefused

__all__ = ["BoundModel", "load_bound", "read_uai", "original_inventory", "SourceRefused"]
