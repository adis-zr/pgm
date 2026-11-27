"""Capability registry: algorithms are selected from input facts, never names."""
CAPABILITIES = {
    "structural": {"status": "automatic", "guarantees": ["EXACT", "DETERMINISTIC"],
                   "methods": ["forest", "source DAG", "support contraction", "bipartite stream"]},
    "block": {"status": "automatic", "guarantees": ["EXACT", "DETERMINISTIC", "PAC"],
              "methods": ["support closure", "signed evidence", "layered contraction", "ancestral response", "block contraction", "importance sampling"]},
    "quotient": {"status": "automatic", "guarantees": ["EXACT", "DETERMINISTIC", "PAC"],
                 "methods": ["identity", "exact quotient", "checked approximate quotient", "residual MAX", "global proposal"]},
    "response": {"status": "automatic", "guarantees": ["EXACT", "DETERMINISTIC", "PAC"],
                 "methods": ["spectral admission", "exact heat bath", "conditional-response certificate"]},
    "cqr": {"status": "retained specialized API", "reason": "general finite query/normalizer language is not silently reduced to singleton queries"},
    "cbi": {"status": "retained specialized API", "reason": "requires a supplied product-kernel block representation"},
    "sf": {"status": "retained specialized API", "reason": "requires a supplied sparse two-block law"},
    "h4": {"status": "retained specialist/reference", "reason": "shipped worker is a fixed arithmetic cohort, not a generic UAI recognizer"},
}

def capabilities():
    import copy
    return copy.deepcopy(CAPABILITIES)
