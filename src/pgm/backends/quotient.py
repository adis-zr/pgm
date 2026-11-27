"""Quotient / proposal adapter: the unified PAC planner (checked identity / exact / approximate quotients,
residual MAX envelope, the lifted and global proposals) on the validated model.  The DGP9 INCUMBENT flags are
passed explicitly (``lifted``, ``envelope RMAX``, ``glob global``); the planner's constructor defaults are not
the benchmarked arm."""
from __future__ import annotations

import time

from .base import AdapterContext, memory_policy, remaining


def modules():
    from ..algorithms.quotient import unified_pac_planner
    from ..algorithms.structural import core
    return unified_pac_planner, core


def run(bound, context: AdapterContext) -> dict:
    planner_module, core = modules()
    memory_policy(planner_module.CE, context.memory_bytes)
    memory_policy(planner_module.PA.IG, context.memory_bytes)
    memory_policy(core, context.memory_bytes)
    begin = time.monotonic()
    left = remaining(context.deadline)
    planner = planner_module.UPlanner(bound.model, bound.binding, left, eps=context.epsilon, delta=context.delta,
                                      admission_stop_s=max(0.0, left - 0.35), t_start=begin,
                                      seed=context.seed, pac=context.mode == "auto", lifted=True, envelope="RMAX", glob="global")
    result = planner.run()
    result["binding"] = bound.binding
    return result
