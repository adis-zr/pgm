"""CERTIFIED QUERY REFINEMENT (CQR) -- the common finite task language (manuscript §2; prompt 'THE COMMON TASK CONTRACT').

A TASK = finite categorical model (cards, nonnegative rational factor tables, evidence) + a finite list of bounded QUERIES + a result MODE.
Queries are explicit rational TABLES over a declared scope (any finite bounded query is a table; singleton / joint / parity / constant are constructors):
  * 'expectation'  f with 0 <= f <= 1 (table over scope)                      -> mu_j = sum w f / Z
  * 'ratio'        (h, g) with 0 <= h <= g <= 1 (tables; h's scope ⊇ g's)     -> N_j / D_j = sum w h / sum w g; D_j = 0 is UNDEFINED (typed), not an answer
Modes: EXACT_RATIONAL (only exact ratios or proved zero / undefined; no positive-width publication; biased rewrites disabled), DETERMINISTIC_EPS (certified bounded
error, no statistical risk), PAC_EPS (epsilon / delta). Every number is a Fraction; the reader is the SHARED UAI reader (model_path + '.evid' is the ONE effective
evidence file); the optional query file is model_path + '.query.json' (absent => all original singleton marginals, the legacy contract).
All work is counted in `Work` units (table entries read, rational operations, point evaluations, cell operations) -- the quota currency of the controller."""
import json, hashlib, os, sys
from fractions import Fraction as F
from itertools import product
from math import prod
HERE = os.path.dirname(os.path.abspath(__file__)); NEWARM = os.path.join(os.path.dirname(HERE), 'newarm')
if NEWARM not in sys.path: sys.path.insert(0, NEWARM)

MODES = ('EXACT_RATIONAL', 'DETERMINISTIC_EPS', 'PAC_EPS')


class Work:
    """charged work counter; one unit = one table entry read / one rational op / one point evaluation / one cell op (the unit is recorded with the policy)"""
    __slots__ = ('entries', 'ratops', 'evals', 'cells', 'bits')
    def __init__(self): self.entries = self.ratops = self.evals = self.cells = self.bits = 0
    def total(self): return self.entries + self.ratops + self.evals + self.cells
    def add(self, other):
        for k in self.__slots__: setattr(self, k, getattr(self, k) + getattr(other, k))
    def snapshot(self): return dict(entries=self.entries, ratops=self.ratops, evals=self.evals, cells=self.cells, max_bits=self.bits, total=self.total())
    def note_bits(self, x):
        if isinstance(x, F): b = x.numerator.bit_length() + x.denominator.bit_length()
        else: b = int(x).bit_length()
        if b > self.bits: self.bits = b


def frac(x):
    return x if isinstance(x, F) else F(str(x)) if isinstance(x, (str, float)) else F(x)


def table_index(scope, cards, x):
    i = 0
    for v in scope: i = i * cards[v] + x[v]
    return i


class Table:
    """an explicit rational table over a scope (distinct variables); values in row-major order of the scope"""
    __slots__ = ('scope', 'values')
    def __init__(self, scope, values): self.scope = tuple(scope); self.values = list(values)
    def at(self, cards, x): return self.values[table_index(self.scope, cards, x)]
    def size(self): return len(self.values)
    def to_json(self): return dict(scope=list(self.scope), values=[str(v) for v in self.values])
    @staticmethod
    def from_json(d): return Table(d['scope'], [frac(v) for v in d['values']])
    def sha(self): return hashlib.sha256(json.dumps(self.to_json(), sort_keys=True).encode()).hexdigest()


class Query:
    """kind 'expectation' (f) or 'ratio' (h, g); `name` is the original-task label; `output` says where the answer goes in the publication"""
    __slots__ = ('name', 'kind', 'f', 'h', 'g', 'output')
    def __init__(self, name, kind, f=None, h=None, g=None, output=None):
        self.name, self.kind, self.f, self.h, self.g, self.output = name, kind, f, h, g, output or {}
    def scope(self):
        return set(self.f.scope) if self.kind == 'expectation' else set(self.h.scope) | set(self.g.scope)
    def to_json(self):
        d = dict(name=self.name, kind=self.kind, output=self.output)
        if self.kind == 'expectation': d['f'] = self.f.to_json()
        else: d['h'] = self.h.to_json(); d['g'] = self.g.to_json()
        return d
    @staticmethod
    def from_json(d):
        if d['kind'] == 'expectation': return Query(d['name'], 'expectation', f=Table.from_json(d['f']), output=d.get('output'))
        return Query(d['name'], 'ratio', h=Table.from_json(d['h']), g=Table.from_json(d['g']), output=d.get('output'))
    def check_range(self, cards, work):
        """syntactic range certificate: every table entry in [0,1]; ratio: 0 <= h <= g pointwise on the joint scope"""
        if self.kind == 'expectation':
            for v in self.f.values:
                work.entries += 1
                if not (0 <= v <= 1): raise ValueError('query %s out of [0,1]' % self.name)
            return True
        sc = sorted(set(self.h.scope) | set(self.g.scope))
        for xs in product(*(range(cards[v]) for v in sc)):
            x = dict(zip(sc, xs)); hv = self.h.at(cards, x); gv = self.g.at(cards, x); work.entries += 2
            if not (0 <= hv <= gv <= 1): raise ValueError('ratio query %s violates 0 <= h <= g <= 1' % self.name)
        return True


def _index(v, n, what):
    if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v < n): raise ValueError('%s index %r outside [0, %d) (negative or out-of-range indices are refused, never wrapped)' % (what, v, n))
    return v


def singleton_query(v, a, cards):
    v = _index(v, len(cards), 'variable'); a = _index(a, cards[v], 'state')
    vals = [F(int(s == a)) for s in range(cards[v])]
    return Query('P(X%d=%d)' % (v, a), 'expectation', f=Table((v,), vals), output=dict(kind='singleton', variable=v, state=a))


def singleton_indicator_of(q, cards):
    """AUTHORITATIVE singleton semantics (structured review CQR-S1-01): (variable, state) iff the query is an expectation whose table has ONE in-range variable in scope and whose
    values are EXACTLY the indicator of one state (a single 1, every other entry 0). Derived from the table alone; the output metadata is never consulted. None otherwise."""
    if q.kind != 'expectation' or q.f is None or len(q.f.scope) != 1: return None
    v = q.f.scope[0]
    if isinstance(v, bool) or not isinstance(v, int) or not (0 <= v < len(cards)) or len(q.f.values) != cards[v]: return None
    ones = [s for s, x in enumerate(q.f.values) if x == 1]
    if len(ones) != 1 or any(x != 0 for s, x in enumerate(q.f.values) if s != ones[0]): return None
    return (v, ones[0])


def derived_output(q, cards):
    """the placement metadata the constructors would have produced for this table, derived from the table alone: singleton / joint / parity indicators, conditional ratio pairs; None = a general table query (no placement)"""
    if q.kind == 'expectation':
        sv = singleton_indicator_of(q, cards)
        if sv is not None: return dict(kind='singleton', variable=sv[0], state=sv[1])
        sc = tuple(q.f.scope)
        if len(sc) != len(set(sc)) or any(isinstance(v, bool) or not isinstance(v, int) or not (0 <= v < len(cards)) for v in sc) or len(q.f.values) != prod(cards[v] for v in sc): return None
        ones = [i for i, x in enumerate(q.f.values) if x == 1]
        if ones and all(x in (0, 1) for x in q.f.values):
            if len(ones) == 1 and sc == tuple(sorted(sc)):
                xs = list(product(*(range(cards[v]) for v in sc)))[ones[0]]; return dict(kind='joint', assign={str(v): xs[i] for i, v in enumerate(sc)})
            if sc == tuple(sorted(sc)):
                for bit in (0, 1):
                    if [F(int(sum(xs) % 2 == bit)) for xs in product(*(range(cards[v]) for v in sc))] == list(q.f.values): return dict(kind='parity', variables=list(sc), bit=bit)
        return None
    sg = tuple(q.g.scope); sh = tuple(q.h.scope)
    if sg != tuple(sorted(sg)) or sh != tuple(sorted(sh)) or not set(sg) <= set(sh): return None
    gi = [i for i, x in enumerate(q.g.values) if x == 1]
    if len(gi) != 1 or any(x not in (0, 1) for x in q.g.values) or any(x not in (0, 1) for x in q.h.values): return None
    given = dict(zip(sg, list(product(*(range(cards[v]) for v in sg)))[gi[0]])); hi = [i for i, x in enumerate(q.h.values) if x == 1]
    if len(hi) != 1: return None
    xs = dict(zip(sh, list(product(*(range(cards[v]) for v in sh)))[hi[0]]))
    if any(xs[v] != given[v] for v in given): return None
    event = {v: xs[v] for v in sh if v not in given}
    if not event: return None
    return dict(kind='conditional', event={str(k): v for k, v in event.items()}, given={str(k): v for k, v in given.items()})


def validate_output_metadata(q, cards):
    """a table query's output metadata must be ABSENT or exactly the metadata derivable from its table (CQR-S1-01: metadata never redefines a query); raises ValueError (INVALID_TASK)"""
    o = q.output or {}
    if not o or o == {'kind': 'table'}: return          # absent or the explicit general-table marker: no placement claimed
    d = derived_output(q, cards)
    norm = lambda m: json.loads(json.dumps(m, sort_keys=True))
    if d is None or norm(d) != norm(o): raise ValueError('query %s: output metadata %s is not derivable from its table (derived: %s): a placement label never redefines the query; drop the metadata or supply the matching table' % (q.name, json.dumps(o, sort_keys=True)[:120], json.dumps(d, sort_keys=True)[:120] if d else 'general table'))


def joint_query(assign, cards):
    """indicator of a joint event {X_v = a for (v,a) in assign}"""
    for v, a in assign.items(): _index(v, len(cards), 'variable'); _index(a, cards[v], 'state')
    if not assign: raise ValueError('joint query with an empty assignment')
    sc = tuple(sorted(assign)); vals = []
    for xs in product(*(range(cards[v]) for v in sc)): vals.append(F(int(all(xs[i] == assign[v] for i, v in enumerate(sc)))))
    return Query('P(%s)' % ','.join('X%d=%d' % (v, assign[v]) for v in sc), 'expectation', f=Table(sc, vals), output=dict(kind='joint', assign={str(k): v for k, v in assign.items()}))


def parity_query(vars_, bit, cards):
    """indicator of (sum of binary-valued coordinates mod 2) == bit; for nonbinary variables the parity of the state index is used (bounded modular-sum query)"""
    for v in vars_: _index(v, len(cards), 'variable')
    if bit not in (0, 1) or isinstance(bit, bool): raise ValueError('parity bit must be 0 or 1')
    if not vars_ or len(set(vars_)) != len(vars_): raise ValueError('parity query needs distinct variables')
    sc = tuple(sorted(vars_)); vals = []
    for xs in product(*(range(cards[v]) for v in sc)): vals.append(F(int(sum(xs) % 2 == bit)))
    return Query('P(parity(%s)=%d)' % (','.join('X%d' % v for v in sc), bit), 'expectation', f=Table(sc, vals), output=dict(kind='parity', variables=list(sc), bit=bit))


def conditional_query(event, given, cards):
    """P(event | given) as a ratio pair: h = 1[event & given], g = 1[given]"""
    for v, a in list(event.items()) + list(given.items()): _index(v, len(cards), 'variable'); _index(a, cards[v], 'state')
    if not event or not given: raise ValueError('conditional query needs a nonempty event and a nonempty condition')
    if any(v in given and given[v] != a for v, a in event.items()): raise ValueError('conditional query: the event contradicts the condition')
    sg = tuple(sorted(given)); sh = tuple(sorted(set(event) | set(given)))
    gv = [F(int(all(xs[i] == given[v] for i, v in enumerate(sg)))) for xs in product(*(range(cards[v]) for v in sg))]
    hv = []
    for xs in product(*(range(cards[v]) for v in sh)):
        x = dict(zip(sh, xs)); hv.append(F(int(all(x[v] == given[v] for v in given) and all(x[v] == event[v] for v in event))))
    return Query('P(%s | %s)' % (','.join('X%d=%d' % (v, event[v]) for v in sorted(event)), ','.join('X%d=%d' % (v, given[v]) for v in sg)), 'ratio', h=Table(sh, hv), g=Table(sg, gv),
                 output=dict(kind='conditional', event={str(k): v for k, v in event.items()}, given={str(k): v for k, v in given.items()}))


LEGACY_BASE_DIGITS = 8          # the legacy comparator contract: outward decimal rows with at least 8 digits


EPSILON_DOMAIN = 'a rational with 0 < epsilon <= 1 in every mode (DETERMINISTIC_EPS / PAC_EPS: the published tolerance; EXACT_RATIONAL: publications are exact regardless, epsilon only sizes the optional legacy decimal rows); 0 and negative values are REJECTED at parsing (an exact tolerance is requested through EXACT_RATIONAL, not through epsilon = 0: arbitrary rational probabilities have no finite exact decimal expansion)'
DELTA_DOMAIN = 'a rational with 0 <= delta < 1 (0 = no statistical risk; PAC publications need delta > 0)'


def check_tolerances(eps, delta):
    """the input domain of the tolerances (fifth review, CQR-R4-03): rejected clearly at parsing, never discovered by an unbounded precision search"""
    eps = F(eps); delta = F(delta)
    if not (0 < eps <= 1): raise ValueError('epsilon %s is outside the supported domain: %s' % (eps, EPSILON_DOMAIN))
    if not (0 <= delta < 1): raise ValueError('delta %s is outside the supported domain: %s' % (delta, DELTA_DOMAIN))
    return eps, delta


def legacy_digits(eps):
    """digits of the legacy decimal rows for a task of tolerance eps: the smallest d >= 8 with 2 / 10^d <= eps / 4, so the rounding reservation never consumes more than a
    quarter of the tolerance (eps = 1/200 -> 8 digits, as before; eps = 1e-12 -> 13 digits). The rows are an OUTPUT REPRESENTATION; their precision follows the request.
    Guarded: eps must be positive (a non-positive tolerance has no finite decimal reservation; the task parser rejects it before any worker runs)."""
    eps = F(eps)
    if eps <= 0: raise ValueError('legacy_digits needs a positive tolerance (epsilon %s): %s' % (eps, EPSILON_DOMAIN))
    d = LEGACY_BASE_DIGITS
    while F(2, 10 ** d) > eps / 4: d += 1
    return d


def output_reservation(task):
    """the accuracy reservation of the task's OUTPUT REPRESENTATION (fourth review, CQR-R3-01 / 02): exact rational `answers` need none (0); the legacy all-singleton decimal
    rows (emitted only for the all-singleton contract) move the point and both endpoints by at most 1 / 10^d each, so 2 / 10^d of the tolerance is reserved for them.
    Producer (solve) and checker derive the same number from the same task; nothing else subtracts a fixed margin."""
    if task.get('all_singletons'): return F(2, 10 ** legacy_digits(task['epsilon']))
    return F(0)


def _validate_table_query(q, cards):
    """shape of an explicit table query: distinct in-range scope variables; table length = product of cardinalities (for both tables of a ratio)"""
    for t in ((q.f,) if q.kind == 'expectation' else (q.h, q.g)):
        if t is None: raise ValueError('query %s: missing table' % q.name)
        sc = tuple(t.scope)
        if len(sc) != len(set(sc)): raise ValueError('query %s: repeated variable in a table scope' % q.name)
        for v in sc: _index(v, len(cards), 'variable')
        if len(t.values) != prod(cards[v] for v in sc): raise ValueError('query %s: table length %d differs from the scope volume %d' % (q.name, len(t.values), prod(cards[v] for v in sc)))


def all_singletons(cards):
    return [singleton_query(v, a, cards) for v in range(len(cards)) for a in range(cards[v])]


def load_task(model_path, mode=None):
    """SHARED reader (core.read_uai: model + '<model>.evid'); optional '<model>.query.json' with {"mode":..., "queries":[{"kind":"singleton","variable":v,"state":a} | {"kind":"joint","assign":{v:a}} |
    {"kind":"parity","variables":[...],"bit":b} | {"kind":"conditional","event":{...},"given":{...}} | {"kind":"table", ...explicit...}], "epsilon": "1/200", "delta": "1/1000000"}"""
    import core
    model, binding = core.read_uai(model_path); cards = model['cards']; qp = model_path + '.query.json'; spec = None
    if os.path.exists(qp):
        spec = json.load(open(qp)); binding = dict(binding, query_sha256=hashlib.sha256(open(qp, 'rb').read()).hexdigest())
        qs = []
        for q in spec['queries']:
            k = q['kind']
            if k == 'singleton': qs.append(singleton_query(int(q['variable']), int(q['state']), cards))
            elif k == 'all_singletons': qs += all_singletons(cards)
            elif k == 'joint': qs.append(joint_query({int(a): int(b) for a, b in q['assign'].items()}, cards))
            elif k == 'parity': qs.append(parity_query([int(v) for v in q['variables']], int(q['bit']), cards))
            elif k == 'conditional': qs.append(conditional_query({int(a): int(b) for a, b in q['event'].items()}, {int(a): int(b) for a, b in q['given'].items()}, cards))
            elif k == 'table':
                tq = Query.from_json(q['table']); _validate_table_query(tq, cards); validate_output_metadata(tq, cards); qs.append(tq)
            else: raise ValueError('unsupported query kind %s' % k)
    else:
        qs = all_singletons(cards); binding = dict(binding, query_sha256=None)
    m = (spec or {}).get('mode') if mode is None else mode
    eps_, delta_ = check_tolerances(F(str((spec or {}).get('epsilon', '1/200'))), F(str((spec or {}).get('delta', '1/1000000'))))
    task = dict(model=model, queries=qs, mode=m or 'PAC_EPS', epsilon=eps_, delta=delta_, binding=binding,
                all_singletons=(spec is None or (bool(spec['queries']) and all(q['kind'] == 'all_singletons' for q in spec['queries']) and not spec.get('normalizer_task'))), query_spec=spec)
    if task['mode'] not in MODES: raise ValueError('unknown mode %s' % task['mode'])
    if not task['queries'] and not (spec or {}).get('normalizer_task'): raise ValueError('a task needs at least one query (or normalizer_task)')
    if (spec or {}).get('normalizer_task') and task['queries']: raise ValueError('a normalizer task (Z with relative error) carries NO queries: the combined normalizer + query contract is not supported (review CQR-08)')
    if mode is not None and spec is not None and spec.get('mode') and spec['mode'] != mode: raise ValueError('mode override %s disagrees with the task file mode %s' % (mode, spec['mode']))
    return task


def task_identity(task):
    """semantic task id: model semantics (cards, factors as exact rationals), evidence, queries, error, risk, mode"""
    m = task['model']
    d = dict(cards=m['cards'], factors=[dict(scope=list(f['scope']), values=[str(v) for v in f['values']]) for f in m['factors']], evidence={str(k): v for k, v in sorted(m.get('evidence', {}).items())},
             queries=[q.to_json() for q in task['queries']], epsilon=str(task['epsilon']), delta=str(task['delta']), mode=task['mode'])
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def evaluate_query(q, cards, x):
    """exact evaluation at a full assignment: ('expectation', f) or ('ratio', h, g)"""
    if q.kind == 'expectation': return q.f.at(cards, x)
    return q.h.at(cards, x), q.g.at(cards, x)
