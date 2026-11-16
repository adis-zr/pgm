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


def singleton_query(v, a, cards):
    vals = [F(int(s == a)) for s in range(cards[v])]
    return Query('P(X%d=%d)' % (v, a), 'expectation', f=Table((v,), vals), output=dict(kind='singleton', variable=v, state=a))


def joint_query(assign, cards):
    """indicator of a joint event {X_v = a for (v,a) in assign}"""
    sc = tuple(sorted(assign)); vals = []
    for xs in product(*(range(cards[v]) for v in sc)): vals.append(F(int(all(xs[i] == assign[v] for i, v in enumerate(sc)))))
    return Query('P(%s)' % ','.join('X%d=%d' % (v, assign[v]) for v in sc), 'expectation', f=Table(sc, vals), output=dict(kind='joint', assign={str(k): v for k, v in assign.items()}))


def parity_query(vars_, bit, cards):
    """indicator of (sum of binary-valued coordinates mod 2) == bit; for nonbinary variables the parity of the state index is used (bounded modular-sum query)"""
    sc = tuple(sorted(vars_)); vals = []
    for xs in product(*(range(cards[v]) for v in sc)): vals.append(F(int(sum(xs) % 2 == bit)))
    return Query('P(parity(%s)=%d)' % (','.join('X%d' % v for v in sc), bit), 'expectation', f=Table(sc, vals), output=dict(kind='parity', variables=list(sc), bit=bit))


def conditional_query(event, given, cards):
    """P(event | given) as a ratio pair: h = 1[event & given], g = 1[given]"""
    sg = tuple(sorted(given)); sh = tuple(sorted(set(event) | set(given)))
    gv = [F(int(all(xs[i] == given[v] for i, v in enumerate(sg)))) for xs in product(*(range(cards[v]) for v in sg))]
    hv = []
    for xs in product(*(range(cards[v]) for v in sh)):
        x = dict(zip(sh, xs)); hv.append(F(int(all(x[v] == given[v] for v in given) and all(x[v] == event[v] for v in event))))
    return Query('P(%s | %s)' % (','.join('X%d=%d' % (v, event[v]) for v in sorted(event)), ','.join('X%d=%d' % (v, given[v]) for v in sg)), 'ratio', h=Table(sh, hv), g=Table(sg, gv),
                 output=dict(kind='conditional', event={str(k): v for k, v in event.items()}, given={str(k): v for k, v in given.items()}))


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
            elif k == 'table': qs.append(Query.from_json(q['table']))
            else: raise ValueError('unsupported query kind %s' % k)
    else:
        qs = all_singletons(cards); binding = dict(binding, query_sha256=None)
    m = (spec or {}).get('mode') if mode is None else mode
    task = dict(model=model, queries=qs, mode=m or 'PAC_EPS', epsilon=F(str((spec or {}).get('epsilon', '1/200'))), delta=F(str((spec or {}).get('delta', '1/1000000'))), binding=binding,
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
