"""Deterministic structural, relabeling, and negative controls; no inference."""
from pathlib import Path
import json
import random
import time
from geometry import discover_graph, discover, Deadline


def grid(side, periodic):
    g = {v: set() for v in range(side * side)}
    for v in g:
        row, col = divmod(v, side)
        for r, c in ((row + 1, col), (row, col + 1)):
            if periodic:
                r %= side
                c %= side
            if r < side and c < side:
                w = r * side + c
                g[v].add(w)
                g[w].add(v)
    return g


def run():
    results = []
    for side, periodic, expected_width in ((2, False, 2), (3, False, 3),
                                          (6, True, 11), (10, True, 19),
                                          (20, False, 20)):
        graph = grid(side, periodic)
        for seed in range(5):
            labels = list(graph)
            random.Random(7000 + seed).shuffle(labels)
            rename = dict(zip(graph, labels))
            relabeled = {rename[v]: {rename[w] for w in ns}
                         for v, ns in graph.items()}
            result = discover_graph(relabeled, deadline=time.monotonic() + 10)
            assert result is not None
            st = result['stats']
            assert st['induced_width'] == expected_width
            if side == 10:
                assert st['sum_dense_bag_rows'] == 27600958
                assert st['peak_bag_entries'] == 1048576
            if side == 20:
                assert st['sum_dense_bag_rows'] == 153092110
                assert st['peak_bag_entries'] == 2097152
            results.append({'side': side, 'periodic': periodic, 'seed': seed,
                            'status': 'PASS', 'stats': st})
    # Structurally nearby perturbations must fail the checked product witness.
    graph = grid(10, True)
    graph[0].remove(1)
    graph[1].remove(0)
    assert discover_graph(graph) is None
    graph = grid(10, True)
    graph[0].add(55)
    graph[55].add(0)
    assert discover_graph(graph) is None
    assert discover_graph(grid(4, True)) is None  # four prime axes, not two
    try:
        discover_graph(grid(10, True), deadline=time.monotonic() - 1)
    except Deadline:
        pass
    else:
        raise AssertionError('expired deadline was ignored')
    # An exact product certificate is scoped to the graph. The odd shell is a
    # legal upper construction, not always a minimum-width construction.
    odd = discover_graph(grid(5, True))
    assert odd['stats']['induced_width'] == 10
    return {'controls': results, 'negative_and_deadline_controls': 4,
            'odd_torus_nonoptimal_width_witness': 10,
            'all_pass': True, 'numerical_inference_run': False}


if __name__ == '__main__':
    result = run()
    target = Path(__file__).with_name('geometry_controls.json')
    target.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'controls': len(result['controls']),
                      'negative_and_deadline_controls': 4,
                      'all_pass': result['all_pass']}))
