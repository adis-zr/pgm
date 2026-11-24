"""Lifted coarse proposal, decoder half (brief CLAUDE_DENSE_GENERIC_PAC_INTEGRATION.md section 3). Given the parent canonical model M_par (identity or an EXACT quotient parent: the fine
state z lives on M_par's variables), one APPROXIMATE stage (classes, Cz = coarse_envelope.check_candidate(M_par, classes, scales)) with product decoder d_v(a|c) = Cz.d[v][a] for
class c = classes[v][a], and the grid Q = 2^52, this module builds the implementable support-preserving conditional proposal r(z|c) = prod_v r_v(z_v | c_v) as exact dyadic categorical rows:
every positive decoder entry receives one count, the remaining Q - m counts are distributed proportionally by exact rational floors of (Q - m) d_v(a|c) with the deterministic
largest-remainder rule (ties: the lower state index first); zero decoder entries receive zero counts; a row is refused when it cannot be represented (m > Q) or admitted (budget).
kappa = prod_v max_{c, a: d > 0} d_v(a|c) / r_v(a|c) with checked rational growth (coarse_envelope.checked_mul); kappa_float = kappa rounded OUTWARD (up) to a double.
The exact pointwise argument (checked independently by `enumerate_check` on small models): with the parent's unnormalized target W(z) = s prod_v psi_v(z_v) prod_f f(z_f) and the upper coarse
weight G_U(c) = s prod_v A_v(c_v) prod_f U_f(c_f) (the scalar s owned ONCE, on both sides), 0 <= W(z) <= G_U(c(z)) d(z|c(z)) is coarse_envelope's checked upper-envelope relation, and
W(z) / (q_C(c) r(z|c)) <= (G_U(c) / q_C(c)) (d(z|c) / r(z|c)) <= B kappa whenever G_U(c) <= B q_C(c). Sampling z | c uses one integer uniform draw per variable: u in [0, Q) and the integer
cumulative counts (the draw function is supplied by the stream so the RNG state stays owned by the stream). Nothing here touches the certificate; that is the sampler's job."""
import math
from fractions import Fraction as F
import coarse_envelope as CE

Q_BITS = 52; Q = 1 << Q_BITS


class LiftedRows:
    __slots__ = ('n', 'cards', 'ccards', 'classes', 'members', 'counts', 'cum', 'kappa', 'kappa_v', 'kappa_float', 'bytes', 'Q')
    def __init__(self): self.counts = {}; self.cum = {}; self.members = {}


def _row_counts(ds, Q):
    """ds = decoder entries of one class (fine states in order); -> integer counts summing to Q, support preserved, largest remainder"""
    pos = [i for i, d in enumerate(ds) if d > 0]; m = len(pos)
    if m == 0: raise CE.Defect('lifted decoder: a class without positive decoder mass')
    if m > Q: raise CE.Refused('RANGE', 'lifted decoder: %d positive entries exceed the grid %d' % (m, Q))
    rem = Q - m; tot = sum(ds[i] for i in pos)
    if tot != 1: raise CE.Defect('lifted decoder: decoder row does not sum to one (%s)' % tot)
    shares = [(rem * ds[i]) for i in pos]; floors = [math.floor(x) for x in shares]; left = rem - sum(floors)
    order = sorted(range(m), key=lambda k: (-(shares[k] - floors[k]), pos[k]))                      # largest remainder first; ties -> lower state index
    counts = [0] * len(ds)
    for k in range(m): counts[pos[k]] = 1 + floors[k] + (1 if k in set(order[:left]) else 0)
    assert sum(counts) == Q and all((c > 0) == (d > 0) for c, d in zip(counts, ds))
    return counts


def build_rows(M_par, classes, Cz, clock, budget, Qgrid=Q):
    """-> LiftedRows for the approximate stage (classes, Cz) over the parent M_par; charges 16 bytes per (class, fine state) entry before building"""
    clock.poll('at the lifted decoder entry'); n = len(M_par.cards); R = LiftedRows(); R.n = n; R.cards = list(M_par.cards); R.ccards = list(Cz.ccards); R.classes = [list(cl) for cl in classes]; R.Q = Qgrid
    total = sum(M_par.cards); R.bytes = budget.charge(16 * total + 64 * n, 'lifted decoder rows (%d entries)' % total)
    try:
        kap = F(1); R.kappa_v = []
        for v in range(n):
            mem = {}
            for a in range(M_par.cards[v]): mem.setdefault(classes[v][a], []).append(a)
            R.members[v] = mem; kv = F(0)
            for c, states in mem.items():
                ds = [Cz.d[v][a] for a in states]
                if sum(ds) == 0: raise CE.Defect('lifted decoder: zero-mass class %d of variable %d has no decoder mass' % (c, v))
                cnt = _row_counts(ds, Qgrid); R.counts[(v, c)] = cnt; cum = []; s = 0
                for x in cnt: s += x; cum.append(s)
                R.cum[(v, c)] = cum
                for d, k in zip(ds, cnt):
                    if d > 0:
                        r = F(k, Qgrid); ratio = d / r
                        if ratio > kv: kv = ratio
            if (v & 15) == 15: clock.poll('in the lifted decoder rows')
            R.kappa_v.append(kv); kap = CE.checked_mul(kap, kv)
        R.kappa = kap; R.kappa_float = float_up(kap); clock.poll('at the lifted decoder exit'); return R
    except BaseException:
        budget.release(R.bytes); R.bytes = 0; raise


def float_up(q):
    """the smallest double >= the positive rational q (outward)"""
    x = float(q)
    if F(x) < q: x = math.nextafter(x, math.inf)
    assert F(x) >= q
    return x


def float_down(q):
    x = float(q)
    if F(x) > q: x = math.nextafter(x, -math.inf)
    assert F(x) <= q
    return x


def r_prob(R, v, c, a):
    """exact dyadic r_v(a | c)"""
    states = R.members[v][c]; i = states.index(a); return F(R.counts[(v, c)][i], R.Q)


def draw_state(R, v, c, u):
    """fine state of variable v given class c from the integer uniform u in [0, Q): the first state whose cumulative count exceeds u"""
    cum = R.cum[(v, c)]; lo, hi = 0, len(cum) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cum[mid] > u: hi = mid
        else: lo = mid + 1
    return R.members[v][c][lo]


def parent_weight(M_par, z):
    """exact unnormalized target W(z) = scalar prod psi prod factors on the parent canonical model"""
    w = M_par.scalar
    for v, a in enumerate(z): w *= M_par.psi[v][a]
    for sc, vals in M_par.factors:
        idx = 0
        for x in sc: idx = idx * M_par.cards[x] + z[x]
        w *= vals[idx]
    return w


def upper_weight(M_par, Cz, c):
    """exact upper coarse weight G_U(c) = scalar prod A prod U at the coarse state c (the scalar owned once, here, as in parent_weight)"""
    w = M_par.scalar
    for v, cc in enumerate(c): w *= Cz.A[v][cc]
    for fi, (sc, _) in enumerate(M_par.factors):
        idx = 0
        for x in sc: idx = idx * Cz.ccards[x] + c[x]
        w *= Cz.U[fi][idx]
    return w


def enumerate_check(M_par, classes, Cz, R, cap=1 << 16):
    """independent enumeration (controls only): support, normalization, pointwise W <= G_U d, d / r <= kappa; returns a dict of maxima"""
    import itertools
    n = len(M_par.cards)
    if math.prod(M_par.cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    for v in range(n):
        for c, states in R.members[v].items():
            assert sum(R.counts[(v, c)]) == R.Q
            for a in states: assert (r_prob(R, v, c, a) > 0) == (Cz.d[v][a] > 0)
    worst_ratio = F(0); worst_env = F(0); zero_W = 0
    for z in itertools.product(*[range(k) for k in M_par.cards]):
        c = tuple(classes[v][z[v]] for v in range(n)); W = parent_weight(M_par, z); G = upper_weight(M_par, Cz, c)
        d = F(1); r = F(1)
        for v in range(n): d *= Cz.d[v][z[v]]; r *= r_prob(R, v, c[v], z[v])
        if W > G * d: raise CE.Defect('upper envelope violated at %s: W %s > G_U d %s' % (z, W, G * d))
        if W == 0: zero_W += 1
        if r > 0 and d / r > worst_ratio: worst_ratio = d / r
        if G * d > 0 and W / (G * d) > worst_env: worst_env = W / (G * d)
    if worst_ratio > R.kappa: raise CE.Defect('kappa understated: %s > %s' % (worst_ratio, R.kappa))
    return dict(states=math.prod(M_par.cards), max_d_over_r=str(worst_ratio), kappa=str(R.kappa), kappa_float=R.kappa_float, max_W_over_envelope=str(worst_env), zero_weight_states=zero_W)
