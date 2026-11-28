"""Structural Cartesian square recognition and checked frontier orders.

This is a schedule constructor, not an inference engine.  No values, filenames,
or assumed coordinate labels determine recognition.  Local square relations are
only candidate generation: a full graph/product bijection validates the result.
It intentionally declines product graphs with other prime factorizations.
"""
from collections import deque
from itertools import combinations
from math import isqrt, prod
import time


class Deadline(TimeoutError):
    pass


def _poll(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise Deadline('geometry deadline')


class _Union:
    def __init__(self, size):
        self.p = list(range(size))
        self.rank = [0] * size
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x
    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = b, a
        self.p[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def _components(graph):
    left = set(graph)
    components = []
    membership = {}
    for seed in sorted(graph):
        if seed not in left:
            continue
        seen = {seed}
        left.remove(seed)
        queue = deque([seed])
        while queue:
            u = queue.popleft()
            for v in graph[u]:
                if v in left:
                    left.remove(v)
                    seen.add(v)
                    queue.append(v)
        i = len(components)
        components.append(seen)
        for v in seen:
            membership[v] = i
    return components, membership


def _axis_order(graph):
    """Return path/cycle sequence, or None; graph already small and simple."""
    degrees = [len(v) for v in graph.values()]
    endpoints = [v for v in graph if len(graph[v]) == 1]
    if len(endpoints) == 2 and all(d in (1, 2) for d in degrees):
        kind, first = 'path', min(endpoints)
    elif len(graph) >= 5 and all(d == 2 for d in degrees):
        kind, first = 'cycle', min(graph)
    else:
        return None
    order, seen, previous, current = [], set(), None, first
    while current not in seen:
        order.append(current)
        seen.add(current)
        nxt = sorted(graph[current] - ({previous} if previous is not None else set()))
        if not nxt:
            break
        previous, current = current, nxt[0]
    if len(order) != len(graph):
        return None
    if kind == 'cycle' and current != first:
        return None
    return kind, order


def replay_order(graph, order, cards=None, deadline=None):
    """Explicit certificate replay. Width and volumes, not a full cost bound."""
    if len(order) != len(graph) or set(order) != set(graph):
        raise ValueError('order is not a vertex permutation')
    cards = {v: 2 for v in graph} if cards is None else cards
    g = {v: set(ns) for v, ns in graph.items()}
    width = rows = peak = pair_checks = cardinality_multiplies = 0
    neighbors = []
    for v in order:
        _poll(deadline)
        ns = g[v]
        size = prod(cards[x] for x in ns) * cards[v]
        cardinality_multiplies += len(ns) + 1
        rows += size
        peak = max(peak, size)
        width = max(width, len(ns))
        neighbors.append(len(ns))
        for a, b in combinations(ns, 2):
            g[a].add(b)
            g[b].add(a)
            pair_checks += 1
        for u in ns:
            g[u].remove(v)
        del g[v]
    return {'induced_width': width, 'sum_dense_bag_rows': rows,
            'peak_bag_entries': peak, 'neighbor_counts': neighbors,
            'fill_pair_checks': pair_checks,
            'bag_cardinality_multiplies': cardinality_multiplies}


def discover_graph(graph, cards=None, deadline=None):
    """Discover P_k square P_k or C_k square C_k from an arbitrary graph.

    Returns None when this recognizer fails. Failure never proves absence of a
    useful product representation. Work is O(n log n) for candidate discovery
    on the degree-four accepted classes, including label sorting, plus explicit
    fill replay. The
    latter has exactly the reported sum choose(current_degree, 2) pair checks.
    """
    start = time.monotonic()
    g = {v: set(ns) for v, ns in graph.items()}
    n = len(g)
    side = isqrt(n)
    if side < 2 or side * side != n:
        return None
    if any(v in ns or not 1 <= len(ns) <= 4 for v, ns in g.items()):
        return None
    if any(v not in g or u not in g[v] for u, ns in g.items() for v in ns):
        raise ValueError('graph must be undirected and closed')
    if len(_components(g)[0]) != 1:
        return None
    edges = sorted((u, v) for u in g for v in g[u] if u < v)
    eid = {e: i for i, e in enumerate(edges)}
    def key(a, b):
        return (a, b) if a < b else (b, a)
    union = _Union(len(edges))
    wedge_checks = square_candidates = 0
    for u in sorted(g):
        _poll(deadline)
        for v, w in combinations(sorted(g[u]), 2):
            wedge_checks += 1
            # Chordless squares u-v-x-w-u. Opposite directions on a single
            # factor do not bound exactly one square; merge their edges.
            xs = [] if w in g[v] else sorted((g[v] & g[w]) - g[u] - {u})
            square_candidates += len(xs)
            if len(xs) != 1:
                union.join(eid[key(u, v)], eid[key(u, w)])
            else:
                x = xs[0]
                union.join(eid[key(u, v)], eid[key(w, x)])
                union.join(eid[key(u, w)], eid[key(v, x)])
    groups = {}
    for edge, i in eid.items():
        groups.setdefault(union.find(i), []).append(edge)
    if len(groups) != 2:
        return None
    dimensions = []
    axis_labels = []
    for es in groups.values():
        h = {v: set() for v in g}
        for a, b in es:
            h[a].add(b)
            h[b].add(a)
        comps, labels = _components(h)
        if len(comps) != side or any(len(c) != side for c in comps):
            return None
        quotient = {i: set() for i in range(side)}
        for a, b in edges:
            x, y = labels[a], labels[b]
            if x != y:
                quotient[x].add(y)
                quotient[y].add(x)
        axial = _axis_order(quotient)
        if axial is None:
            return None
        kind, sequence = axial
        position = {v: j for j, v in enumerate(sequence)}
        dimensions.append(kind)
        axis_labels.append({v: position[labels[v]] for v in g})
    if dimensions[0] != dimensions[1]:
        return None
    kind = 'open_square' if dimensions[0] == 'path' else 'torus_square'
    coordinates = {v: (axis_labels[0][v], axis_labels[1][v]) for v in g}
    inverse = {xy: v for v, xy in coordinates.items()}
    if len(inverse) != n:
        return None
    expected = set()
    for v, (x, y) in coordinates.items():
        for xx, yy in ((x + 1, y), (x, y + 1)):
            if kind == 'torus_square':
                xx %= side
                yy %= side
            if xx < side and yy < side:
                expected.add(key(v, inverse[xx, yy]))
    if expected != set(edges):
        return None
    if kind == 'open_square':
        introduction = sorted(g, key=lambda v: (sum(coordinates[v]), -coordinates[v][0]))
    else:
        introduction = sorted(g, key=lambda v: (
            sum(min(c, side - c) for c in coordinates[v]),
            -coordinates[v][0], -coordinates[v][1]))
    pos = {v: i for i, v in enumerate(introduction)}
    order = sorted(g, key=lambda v: (max(pos[w] for w in g[v] | {v}), pos[v]))
    recognition_s = time.monotonic() - start
    before_replay = time.monotonic()
    costs = replay_order(g, order, cards, deadline)
    seen, frontier, max_frontier, frontier_rows = set(), set(), 0, 0
    volume = 1
    volume_updates = 0
    for v in introduction:
        _poll(deadline)
        seen.add(v)
        if g[v] - seen:
            frontier.add(v)
            volume *= cards[v] if cards else 2
            volume_updates += 1
        for u in g[v] & seen:
            if u in frontier and not (g[u] - seen):
                frontier.remove(u)
                volume //= cards[u] if cards else 2
                volume_updates += 1
        max_frontier = max(max_frontier, len(frontier))
        frontier_rows += volume
    return {'order': order, 'introduction_order': introduction,
            'coordinates': coordinates, 'family': kind, 'side': side,
            'stats': {'vertices': n, 'edges': len(edges),
                      'wedge_checks': wedge_checks,
                      'chordless_square_candidates': square_candidates,
                      'recognition_s': recognition_s,
                      'replay_s': time.monotonic() - before_replay,
                      'total_s': time.monotonic() - start,
                      'frontier_peak': max_frontier,
                      'frontier_volume_sum': frontier_rows,
                      'frontier_volume_updates': volume_updates,
                      **costs},
            'certificate': {'coordinate_bijection_checked': True,
                            'exact_edge_set_checked': True,
                            'order_permutation_checked': True,
                            'width_scope': 'this graph and dense elimination only',
                            'inference_optimality': 'OPEN',
                            'numerical_execution': False}}


def discover(model, deadline=None):
    """Extract residual pairwise graph, respecting evidence, then recognize."""
    start = time.monotonic()
    evidence = model.get('evidence', {})
    cards = model['cards']
    graph = {v: set() for v in range(len(cards)) if v not in evidence}
    scans = 0
    for factor in model['factors']:
        _poll(deadline)
        scope = [v for v in factor['scope'] if v not in evidence]
        scans += len(factor['scope'])
        if len(scope) > 2:
            return None
        if len(scope) == 2:
            a, b = scope
            graph[a].add(b)
            graph[b].add(a)
    out = discover_graph(graph, {v: cards[v] for v in graph}, deadline)
    if out is not None:
        out['stats']['source_scope_positions_scanned'] = scans
        out['stats']['total_s_with_graph_extraction'] = time.monotonic() - start
    return out
