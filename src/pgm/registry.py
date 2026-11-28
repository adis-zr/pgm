"""Capability registry: algorithms are selected from input facts and the explicit policy, never from names.

status: ``selectable`` (a policy may schedule it for a UAI request), ``specialist`` (explicit API on its own
representation), ``reference`` (retained mathematics / provenance; not a generic backend), ``historical`` (pinned
frozen snapshots for differential tests and receipt identity), ``unfinished`` (integration items listed in the
migration manifest).  Every selectable entry names its canonical owner module and entrypoint.
"""
CAPABILITIES = {
    "structural": {"status": "selectable", "owner": "pgm.algorithms.structural", "entrypoint": "core.solve(model, deadline, route)", "adapter": "pgm.backends.structural",
                   "representation": "exact rational UAI model (evidence sliced)", "guarantees": ["EXACT", "DETERMINISTIC"],
                   "methods": ["forest", "source DAG", "support contraction", "bipartite stream"],
                   "admission": "pairwise forest; empty-evidence source DAG; affordable sparse-support contraction; binary bipartite stream (checked by the route itself)",
                   "policies": ["experimental", "automatic"], "evidence": ["research/campaigns/structural/*.json qualification records", "tests/parity/reference_f8197e6.json"]},
    "block": {"status": "selectable", "owner": "pgm.algorithms.block", "entrypoint": "integrated.solve(path, budget, ..., model=, binding=)", "adapter": "pgm.backends.block",
              "representation": "UAI file + adjacent .evid (exact rational)", "guarantees": ["EXACT", "DETERMINISTIC", "PAC"],
              "methods": ["support closure", "signed evidence", "layered contraction", "ancestral response", "block contraction", "importance sampling"],
              "admission": "any nonnegative rational model; exact route when affordable, certified PAC residual stream otherwise (typed refusals)",
              "policies": ["accepted (default)", "experimental", "automatic"], "evidence": ["benchmarks/external/reference/previous_accepted_cells.json", "documentation/reviews/QUALIFICATION.json"]},
    "quotient": {"status": "selectable", "owner": "pgm.algorithms.quotient", "entrypoint": "unified_pac_planner.UPlanner(model, binding, budget, ...).run()", "adapter": "pgm.backends.quotient",
                 "representation": "exact rational UAI model (canonicalized)", "guarantees": ["EXACT", "DETERMINISTIC", "PAC"],
                 "methods": ["identity", "exact quotient", "checked approximate quotient", "residual MAX", "global proposal"],
                 "admission": "general nonnegative rational categorical model; each quotient / proposal is admitted by its own proof-boundary checker",
                 "policies": ["experimental", "automatic"], "evidence": ["pgm-records DENSE_GENERIC_PAC_INTEGRATION_1 .. DGP7 rounds (E-MDI-50..56)"]},
    "response": {"status": "selectable", "owner": "pgm.algorithms.response", "entrypoint": "spectral_heatbath_run.solve_response(model, binding, ...)", "adapter": "pgm.backends.response",
                 "representation": "strictly positive pairwise categorical model after canonicalization", "guarantees": ["PAC"],
                 "methods": ["spectral admission", "exact heat bath", "Markov confidence certificate", "conditional-response certificate"],
                 "admission": "checked spectral witness (typed refusal on arity / hard zero / width / proof); PAC-permitted request only",
                 "policies": ["experimental", "automatic"], "evidence": ["pgm-records DGP8 / DGP9 / DGP10 rounds (E-MDI-57..59)", "documentation/reviews/DGP10_*.md"]},
    "cqr": {"status": "specialist", "owner": "pgm.algorithms.cqr", "entrypoint": "pgm.specialists.cqr.load_task / solve",
            "representation": "explicit bounded rational expectation / ratio query tables; singleton / joint / parity / conditional constructors; normalizer tasks",
            "guarantees": ["EXACT_RATIONAL", "DETERMINISTIC", "PAC"], "reason": "general finite query / normalizer language is not silently reduced to singleton queries",
            "evidence": ["research/campaigns/cqr/CQR_QUALIFICATION.json"]},
    "cbi": {"status": "specialist", "owner": "pgm.algorithms.cbi", "entrypoint": "pgm.specialists.cbi.solve / verify", "representation": "supplied product-kernel binary block model (JSON)",
            "guarantees": ["CERTIFIED width"], "reason": "requires a supplied product-kernel block representation", "evidence": ["tests/specialists/test_cbi_conformance.py"]},
    "sf": {"status": "specialist", "owner": "pgm.algorithms.sf", "entrypoint": "pgm.specialists.sf.law / select / checker", "representation": "supplied sparse two-block law (n <= 63) with bridge r",
           "guarantees": ["published grid enclosure (2^-80 outward)"], "reason": "requires a supplied sparse two-block law", "evidence": ["tests/specialists/test_sf_conformance.py"]},
    "h4": {"status": "reference", "owner": "pgm.algorithms.h4 (native sources included; host-built kernels in user cache)", "entrypoint": "pgm.specialists.h4a.available / arm_main",
           "representation": "fixed H4 arithmetic cohort", "guarantees": ["checked point / rectangle witnesses"], "reason": "shipped worker is a fixed arithmetic cohort, not a generic UAI recognizer",
           "evidence": ["tests/specialists/test_h4a_review2.py"]},
    "frozen_snapshots": {"status": "historical", "owner": "research/archive/{pac,baseline,b0_frozen_v14,newarm_dev}, research/comparators/legacy_ext", "entrypoint": None,
                         "reason": "pinned references for differential tests and receipt identity; production never imports them"},
    "unfinished": {"status": "unfinished", "items": [
        "inherited D1-D90 controls: 51 depend on private record inputs (see documentation/consolidation/step1/BLOCKED_CONTROLS.json)",
    ]},
}


def capabilities():
    import copy
    return copy.deepcopy(CAPABILITIES)


# One registry owns both automatic backend resolution and explicit specialist access.
# Importing this module does not load algorithms or optional native resources.
_PROVIDERS = {
    "structural": "pgm.backends.structural",
    "block": "pgm.backends.block",
    "quotient": "pgm.backends.quotient",
    "response": "pgm.backends.response",
    "cqr": "pgm.specialists.cqr",
    "cbi": "pgm.specialists.cbi",
    "sf": "pgm.specialists.sf",
    "h4": "pgm.specialists.h4a",
}


def _immutable(value):
    from types import MappingProxyType
    if isinstance(value, dict):
        return MappingProxyType({key: _immutable(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_immutable(item) for item in value)
    return value


class Method:
    """Read-only capability description and lazy access to a method's existing API.

    Methods retain their own representations, arguments, result types and checkers.
    This handle never reinterprets specialist certificates as singleton guarantees.
    """

    __slots__ = ("_name", "_metadata")

    def __init__(self, name):
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_metadata", _immutable(CAPABILITIES[name]))

    def __setattr__(self, name, value):
        raise AttributeError("method handles are immutable")

    @property
    def name(self):
        return self._name

    @property
    def metadata(self):
        return self._metadata

    @property
    def api(self):
        from importlib import import_module
        return import_module(_PROVIDERS[self._name])

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.api, name)


def method(name):
    """Resolve a named supported method without guessing its input representation.

    Example: ``pgm.method("cbi").solve(block_model)`` and
    ``pgm.method("cbi").verify(block_model, result)``.
    General UAI requests continue to use ``pgm.infer`` and its admission policy.
    """
    if not isinstance(name, str) or name not in _PROVIDERS:
        raise ValueError(f"unknown method {name!r}; choose from {', '.join(_PROVIDERS)}")
    return Method(name)


def selectable_backends():
    """Names eligible for the generic UAI worker, excluding explicit specialists."""
    return tuple(name for name in _PROVIDERS if CAPABILITIES[name]["status"] == "selectable")


def backend(name):
    """Load a generic UAI adapter; a specialist needs its declared representation."""
    handle = method(name)
    if handle.metadata["status"] != "selectable":
        raise ValueError(f"{name} is not a generic UAI backend: {handle.metadata['representation']}")
    return handle.api
