"""Query-directed exact singleton computation in a recognized source DAG.

No family names, precomputed answers, or saved benchmark orders are consulted.
Recognition peels degree-one variables from the factor-occurrence incidence graph.
If exactly n factors on n variables admit a one-child-per-factor DAG orientation,
every sink has incidence degree one. Removing any degree-one variable and its
factor preserves this property. Conversely a complete peeling orients every
parent before its child in reverse peel order. Thus recognition is complete for
this source representation, in linear incidence work (not for transformed DAGs).

The raw factors are normalized by child rows. A likelihood-ratio range proves
that all event probabilities change by at most (U-L)/(U+L). Exact Fraction
evaluation of the normalized DAG then supplies deterministic raw-model bounds.
This is a prototype exact executor, NOT a formal proof of its Python runtime.
"""
from collections import deque
from fractions import Fraction
from itertools import product
from math import prod
import time
import heapq


class Unsupported(ValueError):
    pass


class Deadline(TimeoutError):
    pass


def _check(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise Deadline("DAG recognition/planning/execution deadline")


def _strides(scope, cards):
    out = [1] * len(scope)
    for i in range(len(scope)-2, -1, -1):
        out[i] = out[i+1] * cards[scope[i+1]]
    return tuple(out)


def _orientation(model, deadline):
    cards = tuple(model['cards']); n = len(cards)
    if any(not isinstance(d, int) or d < 1 for d in cards):
        raise Unsupported("positive integer cardinalities required")
    if model.get('evidence'):
        raise Unsupported("DAG marginal propagation requires empty evidence")
    fs = model['factors']
    if len(fs) != n:
        raise Unsupported("source DAG requires one nonempty factor per variable")
    incidence = [set() for _ in cards]
    reads = 0
    for fi, f in enumerate(fs):
        _check(deadline)
        scope = tuple(f['scope'])
        if not scope or len(set(scope)) != len(scope) or any(v < 0 or v >= n for v in scope):
            raise Unsupported("invalid or empty factor scope")
        if len(f['values']) != prod(cards[v] for v in scope):
            raise Unsupported("incorrect factor size")
        for v in scope:
            incidence[v].add(fi); reads += 1
    queue = deque(v for v in range(n) if len(incidence[v]) == 1)
    bychild = {}; parents = {}; peeled = []; active = set(range(n))
    while queue:
        v = queue.popleft()
        if v in bychild or len(incidence[v]) != 1:
            continue
        fi = next(iter(incidence[v]))
        if fi not in active:
            continue
        bychild[v] = fi
        parents[v] = tuple(u for u in fs[fi]['scope'] if u != v)
        peeled.append(v); active.remove(fi)
        for u in fs[fi]['scope']:
            incidence[u].remove(fi); reads += 1
            if len(incidence[u]) == 1:
                queue.append(u)
        if len(peeled) % 128 == 0:
            _check(deadline)
    if len(bychild) != n:
        raise Unsupported("source factor scopes have no one-child-per-factor DAG orientation")
    topo = tuple(reversed(peeled)); earlier = set()
    for v in topo:
        if not set(parents[v]) <= earlier:
            raise AssertionError("invalid incidence peeling")
        earlier.add(v)
    return cards, parents, bychild, topo, reads


def _normalize(model, cards, parents, bychild, topo, deadline):
    cpt = {}; ranges = []; L = Fraction(1); U = Fraction(1)
    stats = {'source_values_checked': 0, 'normalization_adds': 0,
             'normalization_divisions': 0, 'normalization_range_products': 0}
    for v in topo:
        _check(deadline)
        raw = model['factors'][bychild[v]]; oldscope = tuple(raw['scope'])
        scope = parents[v] + (v,); vals = raw['values']
        if any(not isinstance(x, (int, Fraction)) or x < 0 for x in vals):
            raise Unsupported("nonnegative exact rational source values required")
        stats['source_values_checked'] += len(vals)
        if scope == oldscope:
            reordered = vals
        else:
            strides = _strides(oldscope, cards)
            positions = tuple(scope.index(u) for u in oldscope)
            reordered = []
            for j, assignment in enumerate(product(*(range(cards[u]) for u in scope))):
                reordered.append(vals[sum(assignment[p] * s for p, s in zip(positions, strides))])
                if not j % 4096: _check(deadline)
        d = cards[v]; normalized = []; row_sums = []
        for start in range(0, len(reordered), d):
            row = reordered[start:start+d]
            s = Fraction(row[0])
            for x in row[1:]: s += x
            if s <= 0:
                raise Unsupported("zero child row: normalization shortcut unavailable")
            row_sums.append(s)
            normalized.extend(Fraction(x) / s for x in row)
            stats['normalization_adds'] += d-1
            stats['normalization_divisions'] += d
            if not start % 4096: _check(deadline)
        lo = min(row_sums); hi = max(row_sums)
        L *= lo; U *= hi; stats['normalization_range_products'] += 2
        ranges.append({'child': v, 'source_factor': bychild[v], 'minimum': lo, 'maximum': hi})
        cpt[v] = {'scope': scope, 'values': normalized}
    delta = (U-L)/(U+L)
    return cpt, ranges, L, U, delta, stats


def _ve_order(cards, scopes, query, deadline):
    """The same min-volume order, incrementally maintained from incidence.

    Only neighbors of an eliminated vertex change their bag volumes, so stale
    heap entries can be discarded without rescoring every remaining vertex.
    Factor occurrence incidence separately supplies exact multiplication counts.
    """
    factors = {i:set(s) for i,s in enumerate(scopes)}
    allvars = set().union(*factors.values())
    remaining = allvars-set(query)
    incidence = {v:set() for v in allvars}
    graph = {v:set() for v in allvars}
    for fi,sc in factors.items():
        for v in sc:
            incidence[v].add(fi); graph[v].update(sc-{v})
    candidates = 0
    def score(v):
        nonlocal candidates
        candidates += 1
        if not candidates % 128: _check(deadline)
        return (cards[v]*prod(cards[u] for u in graph[v]),len(graph[v])+1,v)
    keys = {v:score(v) for v in remaining}
    heap = list(keys.values()); heapq.heapify(heap)
    order=[];ops=0;peak=1;nextfid=len(factors)
    while remaining:
        _check(deadline)
        key=heapq.heappop(heap);v=key[2]
        if v not in remaining or key!=keys[v]:continue
        volume=key[0]; bag=graph[v]|{v}; hit=tuple(incidence[v])
        ops+=(len(hit)-1)*volume+volume-volume//cards[v]
        peak=max(peak,volume);order.append(v);remaining.remove(v)
        for fi in hit:
            for u in factors[fi]:incidence[u].remove(fi)
            del factors[fi]
        message=bag-{v};factors[nextfid]=message
        for u in message:incidence[u].add(nextfid)
        nextfid+=1
        for u in message:
            graph[u].update(message-{u});graph[u].discard(v)
        del graph[v]
        for u in message & remaining:
            keys[u]=score(u);heapq.heappush(heap,keys[u])
    volume=prod(cards[u] for u in query)
    ops+=max(0,len(factors)-1)*volume
    return {'order':tuple(order),'scalar_ops':ops,
            'peak_bag_entries':max(peak,volume),'candidate_scores':candidates}


def _additive_identity(cpt, ps, cards, deadline):
    """Check q(a|p)=base[a]+sum_i g_i(p_i)[a] at EVERY table entry.

    This exact identity needs only parent singleton expectations even when the
    parents are correlated. Failed recognition is charged, never assumed free.
    """
    start=time.monotonic();d=cards[cpt['scope'][-1]];vals=cpt['values']
    base=tuple(vals[:d]);strides=_strides(cpt['scope'],cards)[:-1]
    coeff={};subtractions=0;reads=d
    for p,stride in zip(ps,strides):
        rows=[tuple(Fraction(0) for _ in range(d))]
        for s in range(1,cards[p]):
            rows.append(tuple(vals[s*stride+a]-base[a] for a in range(d)))
            subtractions+=d;reads+=d
        coeff[p]=tuple(rows)
    additions=0;comparisons=0;witness=None
    for ri,pa in enumerate(product(*(range(cards[p]) for p in ps))):
        if not ri % 256:_check(deadline)
        for a in range(d):
            predicted=base[a]
            for p,s in zip(ps,pa):
                if coeff[p][s][a]:predicted+=coeff[p][s][a];additions+=1
            comparisons+=1;reads+=1
            if predicted!=vals[ri*d+a]:
                witness={'parent_states':pa,'child_state':a,'additive_value':predicted,'source_value':vals[ri*d+a]}
                break
        if witness is not None:break
    stats={'subtractions':subtractions,'additions':additions,'comparisons':comparisons,
           'source_reads':reads,'seconds':time.monotonic()-start,'accepted':witness is None}
    if witness is not None:return None,stats,witness
    terms=tuple(tuple((p,s,coeff[p][s][a]) for p in ps for s in range(1,cards[p]) if coeff[p][s][a]) for a in range(d))
    return {'base':base,'terms':terms,'execution_scalar_ops':2*sum(map(len,terms)),
            'proof':'complete exact anchored additive identity on the normalized child table',
            'checked_coordinates':comparisons},stats,None


def plan(model, deadline=None, epsilon=Fraction(1, 200), additive=True):
    """Recognize, normalize, and price a complete source-DAG construction.

    deadline is an absolute time.monotonic deadline. Partial work before refusal
    or deadline is real work and must be charged by the caller. The caller owns
    parsing, input authentication, final serialization, and independent review.
    """
    t0 = time.monotonic()
    cards, parents, bychild, topo, incidence_work = _orientation(model, deadline)
    t1 = time.monotonic()
    cpt, ranges, L, U, delta, normstats = _normalize(model, cards, parents, bychild, topo, deadline)
    if delta > epsilon / 2:
        raise Unsupported("normalization bound exceeds reserved half-error budget")
    t2 = time.monotonic()
    ancestors = {}; independent = {}; joints = {}; local_ops = 0
    additive_identities={};additive_checks=[]
    peak = max((len(f['values']) for f in cpt.values()), default=0)
    for v in topo:
        _check(deadline)
        ps = parents[v]
        ancestors[v] = {v}.union(*(ancestors[p] for p in ps))
        independent[v] = all(not ancestors[a] & ancestors[b]
                             for i, a in enumerate(ps) for b in ps[i+1:])
        if not ps: continue
        parentrows = prod(cards[p] for p in ps)
        if additive and len(ps)>=2:
            identity,istats,witness=_additive_identity(cpt[v],ps,cards,deadline)
            additive_checks.append({'child':v,**istats,'rejection_witness':witness})
            ordinary_local=parentrows*cards[v]+(parentrows-1)*cards[v]
            # A lower cost for THIS ordinary joint-table recipe, not intrinsic
            # query necessity. Discovery has already been charged separately.
            if identity is not None and identity['execution_scalar_ops']<ordinary_local:
                additive_identities[v]=identity
                local_ops+=identity['execution_scalar_ops']
                continue
        if independent[v]:
            local_ops += max(0, len(ps)-1) * parentrows
        else:
            A = set().union(*(ancestors[p] for p in ps))
            j = _ve_order(cards, [cpt[u]['scope'] for u in sorted(A)], ps, deadline)
            j['ancestors'] = tuple(sorted(A)); joints[v] = j
            peak = max(peak, j['peak_bag_entries'])
        local_ops += parentrows * cards[v] + (parentrows-1) * cards[v]
    t3 = time.monotonic()
    stats = {**normstats, 'incidence_entries_visited': incidence_work,
             'orientation_s': t1-t0, 'normalization_s': t2-t1,
             'ancestry_and_schedule_s': t3-t2, 'planning_s': t3-t0,
             'local_scalar_ops_predicted': local_ops,
             'joint_scalar_ops_predicted': sum(j['scalar_ops'] for j in joints.values()),
             'scalar_ops_predicted': local_ops + sum(j['scalar_ops'] for j in joints.values()),
             'peak_bag_entries': peak, 'joint_queries': len(joints),
             'direct_nodes': len(cards)-len(joints),
             'ancestral_independent_nodes':sum(independent.values()),
             'additive_nodes':len(additive_identities),
             'additive_execution_scalar_ops':sum(x['execution_scalar_ops'] for x in additive_identities.values()),
             'additive_recognition_subtractions':sum(x['subtractions'] for x in additive_checks),
             'additive_recognition_additions':sum(x['additions'] for x in additive_checks),
             'additive_recognition_comparisons':sum(x['comparisons'] for x in additive_checks),
             'additive_recognition_source_reads':sum(x['source_reads'] for x in additive_checks),
             'additive_recognition_s':sum(x['seconds'] for x in additive_checks),
             'order_candidate_scores': sum(j['candidate_scores'] for j in joints.values())}
    # A deliberately coarse integer bound, without constructing the product D:
    # each contraction denominator divides the product of all normalized source
    # denominators. Every partial sum has <= prod(cards) terms, each <= 1.
    stats['normalized_contraction_rational_bit_bound'] = (
        1 + sum(x.denominator.bit_length() for f in cpt.values() for x in f['values'])
        + sum(d.bit_length() for d in cards)+(1+sum(cards)).bit_length())
    stats['bit_bound_scope'] = (
        'Reduced numerator/denominator of normalized-Q contractions; excludes '
        'raw normalization and final delta widening. An extra magnitude term '
        'covers signed additive partial sums. Fraction temporaries can '
        'have up to twice this many bits plus a constant.')
    return {'cards': cards, 'parents': parents, 'factor_by_child': bychild,
            'topological_order': topo, 'cpt': cpt, 'independent': independent,
            'additive_identities':additive_identities,'additive_checks':additive_checks,
            'joint_plans': joints, 'normalization_ranges': ranges,
            'L': L, 'U': U, 'delta': delta, 'stats': stats}


def _contract(factors, eliminated, outscope, cards, stats, deadline):
    """Fused dense multiplication/reduction; no materialized product bag."""
    bag = tuple(outscope) + (() if eliminated is None else (eliminated,))
    pos = {v: i for i, v in enumerate(bag)}
    indexed = [(f['values'], tuple((pos[v], s) for v, s in zip(f['scope'], _strides(f['scope'], cards))))
               for f in factors]
    out = []; accum = None
    d = 1 if eliminated is None else cards[eliminated]
    for ri, a in enumerate(product(*(range(cards[v]) for v in bag))):
        values, mapping = indexed[0]
        w = values[sum(a[i]*s for i, s in mapping)]
        for values, mapping in indexed[1:]:
            w *= values[sum(a[i]*s for i, s in mapping)]
            stats['multiplications'] += 1
        if accum is None: accum = w
        else:
            accum += w; stats['additions'] += 1
        if ri % d == d-1:
            out.append(accum); accum = None
        if not ri % 1024: _check(deadline)
    stats['contraction_rows'] += prod(cards[v] for v in bag)
    stats['peak_query_live_scalar_slots'] = max(stats['peak_query_live_scalar_slots'],
                                               sum(len(f['values']) for f in factors)+len(out))
    return {'scope': tuple(outscope), 'values': out}


def _joint(p, child, stats, deadline):
    j = p['joint_plans'][child]; cards = p['cards']
    factors = [p['cpt'][v] for v in j['ancestors']]
    for v in j['order']:
        _check(deadline)
        hit = [f for f in factors if v in f['scope']]
        keep = [f for f in factors if v not in f['scope']]
        bag = set().union(*(set(f['scope']) for f in hit))
        outscope = tuple(sorted(bag-{v}))
        stats['peak_query_live_scalar_slots'] = max(stats['peak_query_live_scalar_slots'],
            sum(len(f['values']) for f in factors)+prod(cards[u] for u in outscope))
        keep.append(_contract(hit, v, outscope, cards, stats, deadline))
        factors = keep
    return _contract(factors, None, p['parents'][child], cards, stats, deadline)['values']


def execute_plan(p, deadline=None):
    t0 = time.monotonic(); cards = p['cards']; answers = [None] * len(cards)
    stats = dict(p['stats']); stats.update({'additions': 0, 'multiplications': 0,
        'contraction_rows': 0, 'peak_query_live_scalar_slots': 0})
    for v in p['topological_order']:
        _check(deadline)
        ps = p['parents'][v]; vals = p['cpt'][v]['values']; d = cards[v]
        if not ps:
            answers[v] = list(vals); continue
        if v in p.get('additive_identities',{}):
            identity=p['additive_identities'][v];q=list(identity['base'])
            for a,terms in enumerate(identity['terms']):
                for i,(parent,s,coefficient) in enumerate(terms):
                    q[a]+=coefficient*answers[parent][s]
                    stats['multiplications']+=1;stats['additions']+=1
                    if not i % 1024:_check(deadline)
            answers[v]=q
            continue
        if p['independent'][v]:
            joint = []
            for a in product(*(range(cards[u]) for u in ps)):
                w = answers[ps[0]][a[0]]
                for u, s in zip(ps[1:], a[1:]):
                    w *= answers[u][s]; stats['multiplications'] += 1
                joint.append(w)
        else:
            joint = _joint(p, v, stats, deadline)
        q = [None] * d
        for ri, w in enumerate(joint):
            for a in range(d):
                term = w * vals[ri*d+a]; stats['multiplications'] += 1
                if q[a] is None: q[a] = term
                else: q[a] += term; stats['additions'] += 1
            if not ri % 1024: _check(deadline)
        answers[v] = q
    t1 = time.monotonic()
    assert stats['additions'] + stats['multiplications'] == stats['scalar_ops_predicted']
    for row in answers:
        if sum(row, Fraction(0)) != 1 or any(x < 0 or x > 1 for x in row):
            raise AssertionError("exact normalized-DAG marginal invariant")
    stats['max_output_rational_bits'] = max(
        (max(x.numerator.bit_length(), x.denominator.bit_length()) for row in answers for x in row),
        default=0)
    delta = p['delta']
    intervals = [[(max(Fraction(0), x-delta), min(Fraction(1), x+delta)) for x in row]
                 for row in answers]
    stats['numeric_execution_s'] = t1-t0
    stats['enclosure_and_simplex_check_s'] = time.monotonic()-t1
    stats['total_s_excluding_caller_io'] = stats['planning_s'] + time.monotonic()-t0
    certificate = {k:p[k] for k in ('parents','factor_by_child','topological_order',
        'independent','joint_plans','additive_identities','additive_checks','normalization_ranges','L','U','delta')}
    return {'status': 'CERTIFIED', 'intervals': intervals, 'points': answers,
            'stats': stats, 'certificate': certificate,
            'guarantee': 'Exact normalized-DAG rational computation; raw event error <= delta; caller must bind and serialize outputs.'}


def solve(model, deadline=None, epsilon=Fraction(1, 200), additive=True):
    return execute_plan(plan(model, deadline, epsilon, additive), deadline)
