"""Block adapter: the accepted engine (exact support closure, signed evidence expansion, layered contraction,
ancestral responses, block contraction with the exact route and the certified PAC residual stream).

The configuration is passed EXPLICITLY by the policy (``pgm.policies.accepted.ACCEPTED_CONFIGURATION`` for the
default policy): ``integrated.solve``'s own defaults (schedule ``baseline``) do not reproduce the accepted arm.
"""
from __future__ import annotations

from .base import AdapterContext, memory_policy, remaining

DEFAULT_ROUTE_BY_MODE = {"auto": "auto", "deterministic": "exact", "exact": "exact"}


def module():
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import integrated
    return integrated


def run(bound, context: AdapterContext) -> dict:
    integrated = module()
    memory_policy(integrated, context.memory_bytes)
    cfg = dict(context.configuration or {})
    route_by_mode = cfg.get("route_by_mode") or DEFAULT_ROUTE_BY_MODE
    return integrated.solve(str(bound.path), remaining(context.deadline), seed=context.seed,
                            eps=context.epsilon, delta=context.delta, schedule=cfg.get("schedule", "targeted"),
                            route=route_by_mode.get(context.mode, "exact"), proposal=cfg.get("proposal", "mb"),
                            table_cap=int(cfg.get("table_cap", 1 << 18)), enum_cap=int(cfg.get("enum_cap", 1 << 16)),
                            mb_cap=int(cfg.get("mb_cap", 1 << 24)), batch=int(cfg.get("batch", 1024)),
                            crosscheck=bool(cfg.get("crosscheck", True)), model=bound.model, binding=bound.binding)
