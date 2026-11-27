"""Structural dispatcher (``core.solve``): exact pairwise forest / source DAG / support contraction (native strict-FP
contraction kernel ``cex_kernel.cpp`` with exact fallback) / binary bipartite stream (``stream_kernel.cpp``).
Guarantee: DETERMINISTIC enclosures (EXACT when zero width) with simplex-feasible epsilon-safe points.  Native sources,
flags and build records (``cex_build.json`` / ``stream_build.json``) live here; binaries are content-addressed under the
cache (``pgm.runtime.resources``)."""
