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
                   "policies": ["experimental", "automatic"], "evidence": ["code/cex/newarm/*.json qualification records", "tests/parity/reference_f8197e6.json"]},
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
    "cqr": {"status": "specialist", "owner": "code/cex/cqr (checkout-only; bare sibling imports)", "entrypoint": "pgm.specialists.cqr.load_task / solve",
            "representation": "explicit bounded rational expectation / ratio query tables; singleton / joint / parity / conditional constructors; normalizer tasks",
            "guarantees": ["EXACT_RATIONAL", "DETERMINISTIC", "PAC"], "reason": "general finite query / normalizer language is not silently reduced to singleton queries",
            "evidence": ["code/cex/cqr/CQR_QUALIFICATION.json"]},
    "cbi": {"status": "specialist", "owner": "code/cbi", "entrypoint": "pgm.specialists.cbi.solve / verify", "representation": "supplied product-kernel binary block model (JSON)",
            "guarantees": ["CERTIFIED width"], "reason": "requires a supplied product-kernel block representation", "evidence": ["code/tests/test_cbi_conformance.py"]},
    "sf": {"status": "specialist", "owner": "code/sf", "entrypoint": "pgm.specialists.sf.law / select / checker", "representation": "supplied sparse two-block law (n <= 63) with bridge r",
           "guarantees": ["published grid enclosure (2^-80 outward)"], "reason": "requires a supplied sparse two-block law", "evidence": ["code/tests/test_sf_conformance.py"]},
    "h4": {"status": "reference", "owner": "code/h4a + code/native (host-built kernels in code/build)", "entrypoint": "pgm.specialists.h4a.available / arm_main",
           "representation": "fixed H4 arithmetic cohort", "guarantees": ["checked point / rectangle witnesses"], "reason": "shipped worker is a fixed arithmetic cohort, not a generic UAI recognizer",
           "evidence": ["code/tests/test_h4a_review2.py"]},
    "frozen_snapshots": {"status": "historical", "owner": "code/cex/{pac,baseline,b0_frozen_v14,newarm_dev}, code/ext", "entrypoint": None,
                         "reason": "pinned references for differential tests and receipt identity; production never imports them"},
    "unfinished": {"status": "unfinished", "items": [
        "specialist bridge: pgm.specialists._bridge appends the code/ tree for cbi / sf / h4a / cqr (the only residual path manipulation; production inference does not use it)",
        "CQR packaging: checkout-only (bare sibling imports inside code/cex/cqr)",
        "H4 kernels: host-built executables under code/build (not wheel contents)",
        "inherited D1-D90 controls: 51 depend on private record inputs (see documentation/consolidation/step1/BLOCKED_CONTROLS.json)",
    ]},
}


def capabilities():
    import copy
    return copy.deepcopy(CAPABILITIES)
