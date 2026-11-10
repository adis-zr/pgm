"""Metadata-only elimination orders (brief §12). Scope graph: every pair of variables co-occurring in a current factor / message scope is joined
(a hyperedge induces a clique). Eliminating v makes its current remaining neighbours a clique and removes v. min-fill scores v by the number of currently
missing neighbour-pair edges elimination would add; min-volume scores the exact product of the CURRENT reduced cardinalities of {v} union neighbours.
Ties: smallest original variable id (the reduction map keeps the smallest id of an alias class as representative). One update = one adjacency insertion /
removal or one score evaluation, charged to the SHARED metadata cap (3,000,000) on the CELL clock. An incomplete candidate is discarded. No nominal table
is allocated: only adjacency sets and exact Python integers."""
from __future__ import annotations
from gbidi3.clock import PlanStop

CONSTRUCTION_PRIORITY = ("original_id", "min_volume", "min_fill")
MANDATORY_ORDERS = ("original_id", "min_volume", "min_fill")        # all three use the cell clock + shared metadata cap (brief §12 policy clarification)


def order_original(dom, scopes, clock):
    return sorted(dom), {"name": "original_id", "updates": 0}


def _adjacency(dom, scopes, clock):
    adj = {v: set() for v in dom}
    for sc in scopes:
        sc = [v for v in sc if v in adj]
        for i in range(len(sc)):
            for j in range(i + 1, len(sc)):
                if sc[i] != sc[j]:
                    adj[sc[i]].add(sc[j]); adj[sc[j]].add(sc[i]); clock.spend_meta(2)
    return adj


def _greedy(dom, scopes, clock, score_fn, name):
    adj = _adjacency(dom, scopes, clock); remaining = set(dom); order = []; updates0 = clock.meta
    while remaining:
        best = None
        for v in sorted(remaining):
            s = score_fn(v, adj, dom, clock) if score_fn is _fill_score else score_fn(v, adj, dom); clock.spend_meta(1)
            if best is None or s < best[0] or (s == best[0] and v < best[1]):
                best = (s, v)
        v = best[1]; nb = sorted(adj[v])
        for i in range(len(nb)):
            for j in range(i + 1, len(nb)):
                if nb[j] not in adj[nb[i]]:
                    adj[nb[i]].add(nb[j]); adj[nb[j]].add(nb[i]); clock.spend_meta(2)
        for u in nb:
            adj[u].discard(v); clock.spend_meta(1)
        del adj[v]; remaining.discard(v); order.append(v)
    return order, {"name": name, "updates": clock.meta - updates0}


def _fill_score(v, adj, dom, clock=None):
    nb = sorted(adj[v]); missing = 0
    for i in range(len(nb)):
        for j in range(i + 1, len(nb)):
            if nb[j] not in adj[nb[i]]:
                missing += 1
        if clock is not None:
            clock.spend_meta(max(1, len(nb) - i - 1))                      # every neighbour-pair inspection is a metadata update (polled)
    return missing


def _volume_score(v, adj, dom):
    p = len(dom[v])
    for u in adj[v]:
        p *= len(dom[u])
    return p


def order_min_fill(dom, scopes, clock):
    return _greedy(dom, scopes, clock, _fill_score, "min_fill")


def order_min_volume(dom, scopes, clock):
    return _greedy(dom, scopes, clock, _volume_score, "min_prospective_bag_volume")


ORDER_FN = {"original_id": order_original, "min_volume": order_min_volume, "min_fill": order_min_fill}


def candidate_orders(dom, scopes, clock, names=CONSTRUCTION_PRIORITY):
    """returns [(name, order or None, info)] in construction priority; an incomplete heuristic (metadata cap / deadline) is recorded and discarded"""
    out = []
    for name in names:
        try:
            o, info = ORDER_FN[name](dom, scopes, clock); out.append((name, o, dict(info, state="COMPLETE")))
        except PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                raise
            out.append((name, None, {"name": name, "state": "ORDER_INCOMPLETE_" + ex.kind, "reason": ex.reason}))
    return out
