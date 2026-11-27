"""Structural adapter: the retained structural dispatcher (pairwise forest, source DAG, support contraction, binary
bipartite stream) on the validated model.  Deterministic enclosures with simplex-feasible points; observed
variables are not reported by this marginal-only adapter; no normalizer is supplied."""
from __future__ import annotations

from .base import AdapterContext, memory_policy, remaining


def modules():
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import core
    return core


def native_modules():
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import cex_executor, stream_float
    return cex_executor, stream_float


def run(bound, context: AdapterContext) -> dict:
    core = modules()
    memory_policy(core, context.memory_bytes)
    remaining(context.deadline)
    model = bound.model
    result = core.solve(model, deadline=context.deadline, route=context.structural_route)
    rows = []
    for v, (bounds, points) in enumerate(zip(result["intervals"], result["points"])):
        if v in model.get("evidence", {}):
            continue
        for a, ((lo, hi), point) in enumerate(zip(bounds, points)):
            rows.append({"var": v, "state": a, "lo": str(lo), "hi": str(hi),
                         "point": str(point), "guarantee": "EXACT" if lo == hi else "DETERMINISTIC"})
    return {"outcome": "COMPLETE", "answers": rows, "binding": bound.binding,
            "positive_mass_witness": True, "Z": None,
            "mechanism": {"route": "structural", "structural_route": context.structural_route,
                          "stats": result.get("stats"), "certificate": result.get("certificate"),
                          "reduction_certificate": result.get("reduction_certificate"),
                          "decoder": result.get("decoder"),
                          "normalizer": "not supplied by this marginal-only adapter"}}
