"""Exact integer all-singleton inference on effective binary bipartite graphs.

No model names, stored answers, or benchmark orders are used. A source factor is
first restricted by evidence. Its remaining scope must have arity <= 2 and every
free variable must be binary. Parallel factors are multiplied, and connected
components cancel from one another's normalized singleton answers.

For a bipartition A,B, condition the smaller A. Maintain each B-state product by
exact-divisibility Gray updates, with zero multiplicities, and sum all singleton
numerators using prefix/suffix products or provably exact integer quotients. Integer factor denominator multipliers
cancel from normalized answers. No operation tape grows with 2**len(A).

The exact arithmetic is trusted execution, qualified against independent tiny
whole-joint oracles. The returned metadata is not a succinct independently
checkable numerical proof: a verifier requiring independent arithmetic replay
must charge such a replay separately (root-level evaluation does so when used).
"""
from fractions import Fraction
from math import prod, gcd
from collections import deque
import time


class UnsupportedError(ValueError):
    pass


class DeadlineExceeded(TimeoutError):
    def __init__(self, stats):
        self.stats = dict(stats)
        super().__init__('exact bipartite stream deadline exceeded')


def _check(deadline, stats):
    if deadline is not None and time.monotonic() >= deadline:
        raise DeadlineExceeded(stats)


def _prepare(model, deadline, stats):
    cards = list(model['cards'])
    n = len(cards)
    ev = {int(v): int(a) for v, a in model.get('evidence', {}).items()}
    if any(c < 1 for c in cards):
        raise ValueError('empty variable domain')
    if any(v < 0 or v >= n or not 0 <= a < cards[v] for v, a in ev.items()):
        raise ValueError('invalid evidence')
    free = [v for v in range(n) if v not in ev]
    if any(cards[v] != 2 for v in free):
        raise UnsupportedError('free variables must be binary')
    unary = {v: [1, 1] for v in free}
    edges = {}
    stats['source_entries_validated'] = 0
    stats['sliced_entries'] = 0
    stats['denominator_lcm_steps'] = 0
    stats['denominator_clear_divisions'] = 0
    stats['denominator_clear_multiplications'] = 0
    stats['parallel_factor_multiplications'] = 0
    for fi, factor in enumerate(model['factors']):
        _check(deadline, stats)
        scope = tuple(factor['scope'])
        vals = factor['values']
        if len(set(scope)) != len(scope) or any(v < 0 or v >= n for v in scope):
            raise ValueError('invalid factor scope')
        if len(vals) != prod(cards[v] for v in scope):
            raise ValueError('factor length does not match scope')
        for j, x in enumerate(vals):
            if not isinstance(x, (int, Fraction)) or x < 0:
                raise ValueError('source entries must be nonnegative exact rationals')
            stats['source_entries_validated'] += 1
            if j % 4096 == 0:
                _check(deadline, stats)
        remaining = tuple(v for v in scope if v not in ev)
        if len(remaining) > 2:
            raise UnsupportedError('effective factor arity exceeds two')
        sliced = []
        for code in range(1 << len(remaining)):
            assn = dict(ev)
            for j, v in enumerate(remaining):
                assn[v] = (code >> (len(remaining)-j-1)) & 1
            ix = 0
            for v in scope:
                ix = ix*cards[v] + assn[v]
            sliced.append(Fraction(vals[ix]))
        stats['sliced_entries'] += len(sliced)
        den = 1
        for x in sliced:
            den = den//gcd(den, x.denominator)*x.denominator
            stats['denominator_lcm_steps'] += 1
        ints = []
        for x in sliced:
            ints.append(x.numerator*(den//x.denominator))
            stats['denominator_clear_divisions'] += 1
            stats['denominator_clear_multiplications'] += 1
        if not any(ints):
            raise ValueError('zero total mass: an evidence-sliced factor is zero')
        if not remaining:
            continue  # Positive scalar cancels in every normalized query.
        if len(remaining) == 1:
            v = remaining[0]
            unary[v][0] *= ints[0]
            unary[v][1] *= ints[1]
            stats['parallel_factor_multiplications'] += 2
        else:
            a, b = remaining
            if a > b:
                a, b = b, a
                ints = [ints[0], ints[2], ints[1], ints[3]]
            key = (a, b)
            if key in edges:
                edges[key] = [x*y for x, y in zip(edges[key], ints)]
                stats['parallel_factor_multiplications'] += 4
            else:
                edges[key] = ints
    graph = {v: [] for v in free}
    for a, b in edges:
        graph[a].append(b)
        graph[b].append(a)
    color = {}
    components = []
    for start in free:
        if start in color:
            continue
        color[start] = 0
        q = deque([start])
        sides = [[], []]
        while q:
            v = q.popleft()
            sides[color[v]].append(v)
            for w in graph[v]:
                if w not in color:
                    color[w] = 1-color[v]
                    q.append(w)
                elif color[w] == color[v]:
                    raise UnsupportedError('effective pairwise graph is not bipartite')
        a, b = map(sorted, sides)
        if len(a) > len(b):
            a, b = b, a
        components.append((a, b))
        _check(deadline, stats)
    stats['graph_vertices'] = len(free)
    stats['graph_edges'] = len(edges)
    stats['components'] = len(components)
    stats['conditioning_configurations_planned'] = sum(1 << len(a) for a, _ in components)
    return cards, ev, unary, edges, graph, components


def recognize(model, deadline=None):
    """Fully checked eligibility and priced plan facts; this work is not free."""
    t = time.monotonic()
    stats = {}
    try:
        _, _, _, _, _, comps = _prepare(model, deadline, stats)
        return {'supported': True, 'components': comps, 'stats': stats,
                'seconds': time.monotonic()-t}
    except UnsupportedError as ex:
        return {'supported': False, 'reason': str(ex), 'stats': stats,
                'seconds': time.monotonic()-t}


def solve(model, deadline=None, product_mode="exact_quotient"):
    """Return exact singleton intervals, or raise a typed unsupported/deadline error.

    deadline is an absolute time.monotonic deadline, shared with the caller.
    Integer operation counts do not pretend bit lengths are constant: maximum
    exact integer size is reported separately, with a conservative bound.
    """
    if product_mode not in ('exact_quotient', 'prefix_suffix'):
        raise ValueError('unknown product schedule')
    start = time.monotonic()
    stats = {'product_mode': product_mode, 'solver': 'exact_integer_bipartite_stream', 'configurations': 0,
             'zero_configurations': 0, 'integer_additions': 0,
             'integer_multiplications': 0, 'integer_exact_divisions': 0,
             'max_component_integer_bound_bits': 0,
             'max_accumulator_bits': 0, 'normalization_fraction_constructions': 0,
             'publication_fraction_operations': 0, 'recognition_s': 0.0,
             'execution_s': 0.0, 'publication_s': 0.0, 'completed_components': 0}
    cards, ev, unary, edges, graph, comps = _prepare(model, deadline, stats)
    stats['recognition_s'] = time.monotonic()-start
    answers = [None]*len(cards)
    certificate = {'method': 'conditional distributivity with exact integer arithmetic',
                   'components': [], 'independent_numeric_replay_performed': False,
                   'source_denominators_canceled': True,
                   'cost_model': 'Recognition scans every source entry, clears sliced denominators, multiplies parallel factors, and BFS-colors scopes. Each component costs O(E+(|A|+|B|)2^|A|) bounded-bit integer operations plus O(V) rational normalizations. Loop counters do not include Python control/instrumentation operations; elapsed_s includes them. Input parsing, external decimal publication, and independent numeric replay are caller costs.',
                   'integer_memory_scope': 'O(V+E) working integers per component, plus caller input tables and retained original-output rows/certificate integers; no enumeration-sized tape.'}
    for v, a in ev.items():
        answers[v] = [Fraction(int(j == a)) for j in range(cards[v])]
    exec_start = time.monotonic()
    for ca, cb in comps:
        _check(deadline, stats)
        na, nb = len(ca), len(cb)
        bi = {v: j for j, v in enumerate(cb)}
        adjacency = []
        component_edges = []
        for a in ca:
            aa = []
            for b in graph[a]:
                tab = edges[min(a, b), max(a, b)]
                if a > b:
                    tab = [tab[0], tab[2], tab[1], tab[3]]
                aa.append((bi[b], tab))
                component_edges.append(tab)
            adjacency.append(aa)
        bit_bound = len(ca)+len(cb)+1
        bit_bound += sum(max(unary[v]).bit_length() for v in ca+cb)
        bit_bound += sum(max(t).bit_length() for t in component_edges)
        stats['max_component_integer_bound_bits'] = max(
            stats['max_component_integer_bound_bits'], bit_bound)
        # Store the product of nonzero entries and zero multiplicity separately.
        up, uz = 1, 0
        for a in ca:
            val = unary[a][0]
            if val:
                up *= val
                stats['integer_multiplications'] += 1
            else:
                uz += 1
        qp = [[1, 1] for _ in cb]
        qz = [[0, 0] for _ in cb]
        for j, b in enumerate(cb):
            for state in (0, 1):
                val = unary[b][state]
                if val:
                    qp[j][state] *= val
                    stats['integer_multiplications'] += 1
                else:
                    qz[j][state] += 1
        for neighbors in adjacency:
            for j, table in neighbors:
                for state in (0, 1):
                    val = table[state]
                    if val:
                        qp[j][state] *= val
                        stats['integer_multiplications'] += 1
                    else:
                        qz[j][state] += 1
        z = 0
        ns = [0]*(na+nb)
        configs = 1 << na
        for step in range(configs):
            if step % 64 == 0:
                stats['execution_s'] = time.monotonic()-exec_start
                stats['max_accumulator_bits'] = max(stats['max_accumulator_bits'], z.bit_length())
                stats['elapsed_s'] = time.monotonic()-start
                _check(deadline, stats)
            if step:
                # The changed bit in the reflected Gray sequence is ctz(step).
                i = (step & -step).bit_length()-1
                prev_gray = (step-1)^((step-1)>>1)
                old_state = (prev_gray >> i) & 1
                new_state = 1-old_state
                old, new = unary[ca[i]][old_state], unary[ca[i]][new_state]
                if old:
                    up //= old
                    stats['integer_exact_divisions'] += 1
                else:
                    uz -= 1
                if new:
                    up *= new
                    stats['integer_multiplications'] += 1
                else:
                    uz += 1
                for j, table in adjacency[i]:
                    for state in (0, 1):
                        old, new = table[2*old_state+state], table[2*new_state+state]
                        if old:
                            qp[j][state] //= old
                            stats['integer_exact_divisions'] += 1
                        else:
                            qz[j][state] -= 1
                        if new:
                            qp[j][state] *= new
                            stats['integer_multiplications'] += 1
                        else:
                            qz[j][state] += 1
            stats['configurations'] += 1
            if uz:
                stats['zero_configurations'] += 1
                continue
            q1, sums = [], []
            for j in range(nb):
                t0 = 0 if qz[j][0] else qp[j][0]
                t1 = 0 if qz[j][1] else qp[j][1]
                q1.append(t1)
                sums.append(t0+t1)
                stats['integer_additions'] += 1
            if any(s == 0 for s in sums):
                stats['zero_configurations'] += 1
                continue
            if product_mode == 'prefix_suffix':
                prefix = [up]
                for s in sums:
                    prefix.append(prefix[-1]*s)
                weight = prefix[-1]
            else:
                weight = up
                for s in sums:
                    weight *= s
            stats['integer_multiplications'] += nb
            z += weight
            stats['integer_additions'] += 1
            gray = step^(step>>1)
            for i in range(na):
                if (gray >> i) & 1:
                    ns[i] += weight
                    stats['integer_additions'] += 1
            if product_mode == 'prefix_suffix':
                suffix = 1
                for j in range(nb-1, -1, -1):
                    ns[na+j] += prefix[j]*q1[j]*suffix
                    suffix *= sums[j]
                stats['integer_multiplications'] += 3*nb
            else:
                # All sums are positive here, and each is a literal integer
                # factor of weight. This division is exact even if individual
                # source entries are zero; zero-sum configurations were skipped.
                for j in range(nb):
                    ns[na+j] += (weight//sums[j])*q1[j]
                stats['integer_exact_divisions'] += nb
                stats['integer_multiplications'] += nb
            stats['integer_additions'] += nb
        if z == 0:
            raise ValueError('zero evidence mass in a connected component')
        stats['max_accumulator_bits'] = max(stats['max_accumulator_bits'], z.bit_length())
        assert z.bit_length() <= bit_bound
        for v, numerator in zip(ca+cb, ns):
            if not 0 <= numerator <= z:
                raise AssertionError('invalid exact singleton numerator')
            p = Fraction(numerator, z)
            stats['normalization_fraction_constructions'] += 1
            stats['publication_fraction_operations'] += 1
            answers[v] = [1-p, p]
        stats['completed_components'] += 1
        certificate['components'].append({
            'conditioned': ca, 'independent': cb,
            'configurations': configs, 'normalizer': z,
            'state_one_numerators': ns, 'integer_bound_bits': bit_bound,
            'maximum_multiply_before_divide_bits_bound': 2*bit_bound,
            'working_scalar_count_bound': 10*(len(ca)+len(cb)+len(component_edges))+20})
    stats['execution_s'] = time.monotonic()-exec_start
    pub_start = time.monotonic()
    intervals = [[(p, p) for p in row] for row in answers]
    for row in answers:
        stats['publication_fraction_operations'] += len(row)
        if sum(row) != 1 or any(p < 0 or p > 1 for p in row):
            raise AssertionError('exact publication row invalid')
    stats['output_coordinates'] = sum(cards)
    stats['publication_s'] = time.monotonic()-pub_start
    stats['elapsed_s'] = time.monotonic()-start
    _check(deadline, stats)
    return {'status': 'CERTIFIED_EXACT', 'intervals': intervals,
            'points': answers, 'stats': stats, 'certificate': certificate}
