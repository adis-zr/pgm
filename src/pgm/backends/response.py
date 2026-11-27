"""Response adapter: the spectrally admitted exact heat-bath chain with the conditional-response certificate
(policy ``revised`` + ``--response``), through the callable solver extracted from the former CLI.  The adapter
requires a PAC-permitted request; the solver never mutates ``sys.argv`` and never writes the public output."""
from __future__ import annotations

from .base import AdapterContext, memory_policy, remaining
from ..validation.publication import AdapterRefused


def module():
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import spectral_heatbath_run
    return spectral_heatbath_run


def native_module():
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import heatbath_native
    return heatbath_native


def run(bound, context: AdapterContext) -> dict:
    if context.mode != "auto":
        raise AdapterRefused("INELIGIBLE", "response backend requires a PAC-permitted request")
    runner = module()
    memory_policy(runner.CE, context.memory_bytes)
    from ..runtime.legacy_paths import install_paths
    install_paths()
    import integrated
    memory_policy(integrated, context.memory_bytes)
    left = remaining(context.deadline)
    return runner.solve_response(bound.model, bound.binding, budget=left, admission_stop=max(0.0, left - 0.35),
                                 seed=context.seed, epsilon=context.epsilon, delta=context.delta,
                                 policy="revised", response=True, input_path=str(bound.path))
