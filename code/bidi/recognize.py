"""UNTRUSTED compiler / recognizer for the BIDI pilot: proposes a STRUCTURAL plan only (which variables form the two sides of a binary
bipartite pairwise model, which side is enumerated, how evidence is handled). It parses with ext.uai (the producer-side mdi.model parser
rejects arity-0 factors, which the kernel admits); the certifying executor re-parses the caller's files ITSELF and validates every claim
from its own parse -- nothing (structural or numeric) from this module is trusted downstream."""
from __future__ import annotations
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from ext import uai as U

PLAN_KIND = "BINARY_BIPARTITE_PAIRWISE_CONDITIONED_STREAM"


def recognize(model_path, evidence_path):
    """Returns a plan dict or a typed refusal dict {"kind": "ROUTE_LIMITATION", "reason": ...}. Proposal only."""
    m = U.read_model(model_path); m.check(); ev = U.read_evidence(evidence_path)
    if any(c != 2 for c in m.card):
        return {"kind": "ROUTE_LIMITATION", "reason": "non-binary variable (card %s)" % sorted(set(m.card))}
    pairs = []; unary = 0; scalar = 0
    for f in m.factors:
        if len(f.scope) == 2:
            pairs.append(tuple(f.scope))
        elif len(f.scope) == 1:
            unary += 1
        elif len(f.scope) == 0:
            scalar += 1
        else:
            return {"kind": "ROUTE_LIMITATION", "reason": "factor of arity %d (pairwise model required)" % len(f.scope)}
    # 2-colouring of the pair graph (any proper colouring of a bipartite graph works; isolated variables go to the X side)
    adj = {v: set() for v in range(m.nvars)}
    for a, b in pairs:
        if a == b:
            return {"kind": "ROUTE_LIMITATION", "reason": "self-pair factor on variable %d" % a}
        adj[a].add(b); adj[b].add(a)
    col = {}
    for s0 in range(m.nvars):
        if s0 in col:
            continue
        col[s0] = 0; st = [s0]
        while st:
            v = st.pop()
            for w in adj[v]:
                if w not in col:
                    col[w] = 1 - col[v]; st.append(w)
                elif col[w] == col[v]:
                    return {"kind": "ROUTE_LIMITATION", "reason": "pair graph is not bipartite (odd cycle through variable %d)" % w}
    X = [v for v in range(m.nvars) if col[v] == 0]; Y = [v for v in range(m.nvars) if col[v] == 1]
    if len(Y) > len(X):
        X, Y = Y, X                                          # enumerate the smaller side
    return {"kind": PLAN_KIND, "x_side": X, "y_side": Y, "enumerated_side": "y", "n_pair_factors": len(pairs), "n_unary_factors": unary, "n_scalar_factors": scalar,
            "evidence": "absorbed into the observed variable's unary factor as an exact indicator (zero at forbidden states)", "n_evidence": len(ev),
            "proposal_note": "UNTRUSTED structural proposal; the executor validates every claim from its own parse"}


if __name__ == "__main__":
    import json
    print(json.dumps(recognize(sys.argv[1], sys.argv[2])))
