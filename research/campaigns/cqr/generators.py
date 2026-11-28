"""MECHANISM-FAMILY GENERATORS (benchmark_expansion.txt §4; M01-M12), implemented INDEPENDENTLY of the solver: only Fractions, the UAI writer and the query spec writer.
Every generator: generate(family, n, regime, seed) -> dict(model, queries_spec, meta) with regime in {'favorable', 'near_miss'}; the near-miss changes exactly the premise the
family tests (the general engine must still be correct on it). Development sizes n in {8, 16}; scored sizes {32, 64}; the FOUR reserved performance families (M03, M05, M09,
M12) must not be executed for tuning (policy enforced by the caller's size/seed discipline; this module exposes them for correctness examples only).
Parameters are chosen from the theorems' checked sufficient conditions (wide margin for development), never from floating thresholds. All tables are nonnegative rationals."""
from ._paths import HERE, ROOT, CODE, CEX, PAC, NEWARM, RUNTIME, PY, runs_root, source_path, subprocess_env
import random, json, os
from fractions import Fraction as F
from itertools import product
from math import prod

GENERATOR_VERSION = 'cqr-generators-v1 (2026-11-16)'
FAMILIES = ('M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11', 'M12')
RESERVED_PERFORMANCE_FAMILIES = ('M03', 'M05', 'M09', 'M12')


def write_uai(model, path):
    cards = model['cards']; lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(model['factors']))]
    for f in model['factors']: lines.append(' '.join([str(len(f['scope']))] + [str(v) for v in f['scope']]))
    for f in model['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(_fmt(v) for v in f['values']))
    open(path, 'w').write('\n'.join(lines) + '\n')
    ev = model.get('evidence', {}); open(path + '.evid', 'w').write(' '.join([str(len(ev))] + ['%d %d' % (v, a) for v, a in sorted(ev.items())]) + '\n')


def _fmt(v):
    v = F(v)
    return str(v.numerator) if v.denominator == 1 else '%d/%d' % (v.numerator, v.denominator)


def write_query_spec(spec, path): json.dump(spec, open(path + '.query.json', 'w'), indent=1)


def _pair(u, v, vals): return dict(scope=(u, v), values=[F(x) for x in vals])
def _unary(v, vals): return dict(scope=(v,), values=[F(x) for x in vals])
def _rp(rng, lo=1, hi=9): return F(rng.randint(lo, hi), rng.randint(lo, hi))


def _ring_edges(n): return [(i, (i + 1) % n) for i in range(n)]
def _grid_edges(n):
    w = max(2, int(n ** 0.5)); h = max(1, n // w); E = []
    for i in range(h):
        for j in range(w):
            v = i * w + j
            if v >= n: continue
            if j + 1 < w and v + 1 < n: E.append((v, v + 1))
            if i + 1 < h and v + w < n: E.append((v, v + w))
    return E


def generate(family, n, regime, seed):
    rng = random.Random('%s|%d|%s|%d' % (family, n, regime, seed)); fn = globals()['_' + family.lower()]
    model, qspec, meta = fn(rng, n, regime)
    meta.update(family=family, n=n, regime=regime, seed=seed, generator_version=GENERATOR_VERSION)
    return dict(model=model, query_spec=qspec, meta=meta)


# ---- M01 query relevance / local structure: a small query component + an irrelevant high-width component; near-miss: a weak bridge makes it relevant
def _m01(rng, n, regime):
    nq = max(3, n // 4); cards = [2] * n; factors = []
    for u, v in _ring_edges(nq): factors.append(_pair(u, v, [_rp(rng) for _ in range(4)]))
    others = list(range(nq, n))
    for i in range(len(others)):
        for j in range(i + 1, min(i + 4, len(others))): factors.append(_pair(others[i], others[j], [_rp(rng) for _ in range(4)]))
    if regime == 'near_miss': factors.append(_pair(nq - 1, nq, [F(1), F(1), F(1), F(3, 2)]))   # a weak bridge: the big component becomes relevant
    qs = dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=v, state=1) for v in range(nq)], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(query_component=nq, irrelevant_component=n - nq, mechanism='component_omission / leaf_sumout')


# ---- M02 weighted categorical clones: d = r*s states; pair factors alpha(c,a) beta(d,b) G(c,d); near-miss: one entry perturbed OR evidence on a clone state
def _m02(rng, n, regime):
    r = 3 if n <= 8 else rng.choice([3, 4, 5]); s = 2; d = r * s; cards = [d] * n; factors = []      # development n <= 8 keeps d = 6 so the independent enumerator can finish; scored sizes use d in {6, 8, 10}
    for u, v in _grid_edges(n):
        al = [F(rng.randint(1, 7)) for _ in range(d)]; be = [F(rng.randint(1, 7)) for _ in range(d)]; G = [[F(rng.randint(1, 5)) for _ in range(r)] for _ in range(r)]
        factors.append(_pair(u, v, [al[x] * be[y] * G[x // s][y // s] for x in range(d) for y in range(d)]))
    ev = {}
    if regime == 'near_miss':
        if rng.random() < 0.5: f = factors[0]; f['values'][rng.randrange(d * d)] += F(1, 3)      # breaks exact proportionality of one slice
        else: ev = {0: rng.randrange(d)}                                                             # evidence selects a state that would otherwise be merged
    qs = dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence=ev), qs, dict(r=r, s=s, mechanism='exact_quotient_pass')


# ---- M03 symmetry (RESERVED): binary pair tables [[a,b],[b,a]] on a non-grid graph; invariant vs non-invariant queries; near-miss: one asymmetric field
def _m03(rng, n, regime):
    cards = [2] * n; factors = []
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < 0.3: a = _rp(rng); b = _rp(rng); factors.append(_pair(i, j, [a, b, b, a]))
    if regime == 'near_miss': factors.append(_unary(0, [F(1), F(2)]))
    qs = dict(mode='PAC_EPS', queries=[dict(kind='all_singletons'), dict(kind='parity', variables=[0, 1], bit=0)], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='symmetry', reserved=True)


# ---- M04 partial affine support: GF(2) equations on a subset + nonuniform weights elsewhere; parity queries; near-miss: a forbidden entry becomes positive / nonlinear support
def _m04(rng, n, regime):
    cards = [2] * n; factors = []; k = max(3, n // 2)
    for t in range(k):
        a, b, c = rng.sample(range(n), 3); bit = rng.randrange(2)
        vals = [F(0)] * 8
        for xs in product((0, 1), repeat=3):
            if (xs[0] ^ xs[1] ^ xs[2]) == bit: vals[xs[0] * 4 + xs[1] * 2 + xs[2]] = F(rng.randint(1, 4))      # affine support with NONUNIFORM positive weights
        if regime == 'near_miss' and t == 0:
            if rng.random() < 0.5: vals[next(i for i, v in enumerate(vals) if v == 0)] = F(1, 7)              # forbidden entry small positive: not affine any more
            else: vals = [F(1) if i in (0, 1, 2, 4) else F(0) for i in range(8)]                              # {000,001,010,100}: power-of-two size, NOT affine
        factors.append(dict(scope=(a, b, c), values=vals))
    for v in range(n): factors.append(_unary(v, [F(rng.randint(1, 5)), F(rng.randint(1, 5))]))
    qs = dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=v, state=1) for v in range(min(n, 6))] + [dict(kind='parity', variables=[0, 1, 2], bit=1)], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(equations=k, mechanism='affine')


# ---- M05 general sparse support (RESERVED): non-affine sparse relations, mixed domains, one-hot constraints; near-miss densifies support
def _m05(rng, n, regime):
    cards = [rng.choice([2, 3]) for _ in range(n)]; factors = []; planted = [rng.randrange(c) for c in cards]      # a planted satisfying assignment keeps Z > 0
    for u, v in _grid_edges(n):
        size = cards[u] * cards[v]; vals = [F(0)] * size
        for i in rng.sample(range(size), max(2, size // 2 if regime == 'favorable' else size - 1)): vals[i] = F(rng.randint(1, 4))
        vals[planted[u] * cards[v] + planted[v]] = F(rng.randint(1, 4))
        factors.append(dict(scope=(u, v), values=vals))
    qs = dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='support propagation (GF(2)-only recognizer must decline)', reserved=True)


# ---- M06 generic influence / factor removal: strictly positive heterogeneous tables with small oscillation (alpha < 1 by the checked condition); near-miss crosses the threshold
def _m06(rng, n, regime):
    cards = [rng.choice([2, 3]) for _ in range(n)]; factors = []; eta = F(1, 40) if regime == 'favorable' else F(3, 2)
    for u, v in _grid_edges(n):
        base = [F(rng.randint(2, 5)) for _ in range(cards[u])]; base2 = [F(rng.randint(2, 5)) for _ in range(cards[v])]
        factors.append(dict(scope=(u, v), values=[base[x] * base2[y] * (1 + eta * F(rng.randint(0, 3), 3)) for x in range(cards[u]) for y in range(cards[v])]))
    for v in range(n): factors.append(_unary(v, [F(rng.randint(1, 9)) for _ in range(cards[v])]))
    qs = dict(mode='DETERMINISTIC_EPS', queries=[dict(kind='singleton', variable=v, state=0) for v in range(min(n, 8))], epsilon='1/200', delta='0')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(eta=str(eta), mechanism='influence_deletion')


# ---- M07 dense weak interaction: dense positive binary models with individually weak interactions; nonsymmetric fields
def _m07(rng, n, regime):
    cards = [2] * n; factors = []; eta = F(1, 8 * n) if regime == 'favorable' else F(1, 2)
    for i in range(n):
        for j in range(i + 1, n): e = eta * F(rng.randint(1, 4), 4); factors.append(_pair(i, j, [1 + e, F(1), F(1), 1 + e]))
    for v in range(n): factors.append(_unary(v, [F(rng.randint(1, 9)), F(rng.randint(1, 9))]))
    qs = dict(mode='DETERMINISTIC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='0')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(eta=str(eta), mechanism='influence_deletion (all non-unary)')


# ---- M08 concentrated law: strong heterogeneous fields + bounded interactions, planted core; near-miss shifts mass into a remote region
def _m08(rng, n, regime):
    cards = [rng.choice([2, 3]) for _ in range(n)]; factors = []; M = 2
    for u, v in _grid_edges(n): factors.append(dict(scope=(u, v), values=[F(rng.randint(1, M)) for _ in range(cards[u] * cards[v])]))
    deg = {v: 0 for v in range(n)}
    for f in factors:
        for v in f['scope']: deg[v] += 1
    for v in range(n):
        # CHECKED sufficient condition of the concentration certificate (reduction note §4.2): r_i(s) <= ratio * M^deg(i) per bad state, R_i <= (card-1) ratio M^deg,
        # t_i = R_i/(1+R_i); a singleton query's bias is t_i, which must fit the compiler reserve eps/4 = 1/800: ratio = 1/(4000 M^deg) gives t_i <= 1/2001 (wide margin)
        vals = [F(1)] + [F(1, 4000 * M ** deg[v]) for _ in range(cards[v] - 1)]
        if regime == 'near_miss' and v == n - 1: vals = [F(1)] * cards[v]        # the remote states regain mass: the tail certificate must fail
        factors.append(dict(scope=(v,), values=vals))
    qs = dict(mode='DETERMINISTIC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='0')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='concentration')


# ---- M09 multimodal (RESERVED): selector variable with two separated modes with different query values
def _m09(rng, n, regime):
    cards = [2] * n; factors = []; sel = n - 1
    for v in range(n - 1): factors.append(dict(scope=(v, sel), values=[F(9), F(1), F(1), F(9)]))       # mode 0: x_v = 0; mode 1: x_v = 1
    factors.append(_unary(sel, [F(1), F(1) if regime == 'favorable' else F(1, 10 ** 4)]))
    qs = dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='frontier + signed residual (all modes covered)', reserved=True)


# ---- M10 query-centered signed residual: a huge unresolved mass with exactly zero residual for the query, plus a small query-relevant region; near-miss: one weight changed
def _m10(rng, n, regime):
    """query-centered signed residual: a HEAVY region (x1 = 0; unary weight 10^4) where the query is CONSTANT 1/2 (zero signed residual for the candidate 1/2 regardless of its
    unknown mass), plus a light query-relevant region (x1 = 1) where the query is the indicator x0 = 1 coupled to a chain; near miss: the constant becomes 13/25 (the previously
    zero residual is nonzero); the query is an explicit TABLE over (x0, x1) -- a bounded query, not a singleton"""
    cards = [2] * n; factors = [_unary(1, [F(10 ** 4), F(1)]), _pair(0, 1, [F(1), F(3), F(1), F(1)])]
    big = list(range(2, n))
    for i in range(len(big) - 1): factors.append(_pair(big[i], big[i + 1], [_rp(rng, 1, 5) for _ in range(4)]))
    factors.append(_pair(1, big[0], [F(1), F(2), F(2), F(1)]))
    c0 = F(1, 2) if regime == 'favorable' else F(13, 25)
    qs = dict(mode='PAC_EPS', queries=[dict(kind='table', table=dict(name='Q_signed', kind='expectation', output=dict(kind='table'), f=dict(scope=[0, 1], values=[str(c0), '0', str(c0), '1'])))], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='signed stream omits zero-residual cells (heavy region x1 = 0, query constant %s there)' % c0, constant=str(c0))


# ---- M11 exact/PAC continuation: shared exact-resolved regions; a rare hidden contribution in the near-miss
def _m11(rng, n, regime):
    cards = [2] * n; factors = []
    for u, v in _grid_edges(n): factors.append(_pair(u, v, [_rp(rng, 1, 4) for _ in range(4)]))
    for v in range(n): factors.append(_unary(v, [F(1), F(1) if regime == 'favorable' else F(1, 50)]))
    if regime == 'near_miss': factors.append(dict(scope=tuple(range(min(4, n))), values=[F(1)] * (2 ** min(4, n) - 1) + [F(10 ** 6)]))   # a rare heavy point
    qs = dict(mode='PAC_EPS', queries=[dict(kind='all_singletons')], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence={}), qs, dict(mechanism='frontier carving / resolution / ratio stream')


# ---- M12 mixed composition (RESERVED): relevance + clones + partial support + influence composed; near-miss invalidates one premise via evidence
def _m12(rng, n, regime):
    a = generate('M01', max(8, n // 2), 'favorable', rng.randrange(10 ** 6)); b = generate('M02', max(4, n // 4), 'favorable', rng.randrange(10 ** 6)); c = generate('M04', max(6, n // 4), 'favorable', rng.randrange(10 ** 6))
    cards = []; factors = []; off = 0
    for part in (a, b, c):
        m = part['model']
        for f in m['factors']: factors.append(dict(scope=tuple(v + off for v in f['scope']), values=list(f['values'])))
        cards += m['cards']; off += len(m['cards'])
    ev = {}
    if regime == 'near_miss': ev = {len(a['model']['cards']): 0}     # evidence on a clone variable invalidates the quotient premise there
    qs = dict(mode='PAC_EPS', queries=[dict(kind='singleton', variable=v, state=0) for v in range(0, off, max(1, off // 8))][:8], epsilon='1/200', delta='1/1000000')
    return dict(cards=cards, factors=factors, evidence=ev), qs, dict(mechanism='composition (no family dispatch)', reserved=True, parts=['M01', 'M02', 'M04'])


def materialize(family, n, regime, seed, out_dir, case_id=None):
    g = generate(family, n, regime, seed); case_id = case_id or '%s_n%d_%s_s%d' % (family, n, regime, seed); p = os.path.join(out_dir, case_id + '.uai')
    os.makedirs(out_dir, exist_ok=True); write_uai(g['model'], p); write_query_spec(g['query_spec'], p); json.dump(g['meta'], open(p + '.meta.json', 'w'), indent=1)
    return p
