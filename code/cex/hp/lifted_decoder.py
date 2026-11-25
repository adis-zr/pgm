"""Lifted coarse proposal, decoder half (brief CLAUDE_DENSE_GENERIC_PAC_INTEGRATION.md section 3). Given the parent canonical model M_par (identity or an EXACT quotient parent: the fine
state z lives on M_par's variables), one APPROXIMATE stage (classes, Cz = coarse_envelope.check_candidate(M_par, classes, scales)) with product decoder d_v(a|c) = Cz.d[v][a] for
class c = classes[v][a], and the grid Q = 2^52, this module builds the implementable support-preserving conditional proposal r(z|c) = prod_v r_v(z_v | c_v) as exact dyadic categorical rows:
every positive decoder entry receives one count, the remaining Q - m counts are distributed proportionally by exact rational floors of (Q - m) d_v(a|c) with the deterministic
largest-remainder rule (ties: the lower state index first); zero decoder entries receive zero counts; a row is refused when it cannot be represented (m > Q) or admitted (budget).
kappa = prod_v max_{c, a: d > 0} d_v(a|c) / r_v(a|c): production keeps a COMPACT outward enclosure K = [K_lo, K_hi] with 128-bit significands (class Compact; DGP2 lemma K) and consumes K_hi in the cap; the
exact product exists only in oracle controls (exact_kappa). kappa_float = K_hi rounded outward to a double.
The exact pointwise argument (checked independently by `enumerate_check` on small models): with the parent's unnormalized target W(z) = s prod_v psi_v(z_v) prod_f f(z_f) and the upper coarse
weight G_U(c) = s prod_v A_v(c_v) prod_f U_f(c_f) (the scalar s owned ONCE, on both sides), 0 <= W(z) <= G_U(c(z)) d(z|c(z)) is coarse_envelope's checked upper-envelope relation, and
W(z) / (q_C(c) r(z|c)) <= (G_U(c) / q_C(c)) (d(z|c) / r(z|c)) <= B kappa whenever G_U(c) <= B q_C(c). Sampling z | c uses one integer uniform draw per variable: u in [0, Q) and the integer
cumulative counts (the draw function is supplied by the stream so the RNG state stays owned by the stream). Nothing here touches the certificate; that is the sampler's job."""
import math
from fractions import Fraction as F
import coarse_envelope as CE

Q_BITS = 52; Q = 1 << Q_BITS; K_BITS = 128                                                       # compact kappa: 128-bit significand + separate binary exponent, outward rounding after every multiplication


class Compact:
    """a positive dyadic interval [lo_m 2^lo_e, hi_m 2^hi_e] with K_BITS-bit significands (lo_m, hi_m in [2^(K-1), 2^K)); the product of two such intervals is rounded OUTWARD to K bits after each
    multiplication (lo down, hi up), so the invariant lo <= exact product <= hi is preserved by induction (DGP2 PROOF_TO_CODE lemma K). Storage: two K-bit ints + two small ints."""
    __slots__ = ('lo_m', 'lo_e', 'hi_m', 'hi_e')
    def __init__(self, lo_m, lo_e, hi_m, hi_e): self.lo_m = lo_m; self.lo_e = lo_e; self.hi_m = hi_m; self.hi_e = hi_e
    @staticmethod
    def _norm_down(m, e):
        b = m.bit_length()
        if b > K_BITS: sh = b - K_BITS; return m >> sh, e + sh                                        # floor
        if b < K_BITS: sh = K_BITS - b; return m << sh, e - sh
        return m, e
    @staticmethod
    def _norm_up(m, e):
        b = m.bit_length()
        if b > K_BITS: sh = b - K_BITS; q = m >> sh; q += 1 if (m & ((1 << sh) - 1)) else 0; return Compact._norm_up(q, e + sh) if q.bit_length() > K_BITS else (q, e + sh)      # ceil
        if b < K_BITS: sh = K_BITS - b; return m << sh, e - sh
        return m, e
    @classmethod
    def from_fraction(cls, q):
        """outward K-bit enclosure of a positive Fraction: floor / ceil of num 2^s / den with s chosen so the quotient has K + 1 bits (one integer division each; no growth beyond bits(num) + K)"""
        if q <= 0: raise CE.Defect('compact enclosure of a nonpositive value')
        num, den = q.numerator, q.denominator; s = K_BITS + 1 - (num.bit_length() - den.bit_length()); sn = num << s if s >= 0 else num; sd = den << (-s) if s < 0 else den
        lo = sn // sd; hi = lo + (1 if sn % sd else 0); lo_m, lo_e = cls._norm_down(lo, -s); hi_m, hi_e = cls._norm_up(hi, -s); return cls(lo_m, lo_e, hi_m, hi_e)
    @classmethod
    def one(cls): return cls(1 << (K_BITS - 1), 1 - K_BITS, 1 << (K_BITS - 1), 1 - K_BITS)
    def mul(self, other):
        lo_m, lo_e = self._norm_down(self.lo_m * other.lo_m, self.lo_e + other.lo_e); hi_m, hi_e = self._norm_up(self.hi_m * other.hi_m, self.hi_e + other.hi_e); return Compact(lo_m, lo_e, hi_m, hi_e)
    def lo(self): return F(self.lo_m) * F(2) ** self.lo_e
    def hi(self): return F(self.hi_m) * F(2) ** self.hi_e
    def contains(self, q): return self.lo() <= q <= self.hi()
    def inflation(self): return float(self.hi() / self.lo() - 1)
    def log2_hi(self): return math.log2(self.hi_m) + self.hi_e
    def record(self): return dict(lo_m=str(self.lo_m), lo_e=self.lo_e, hi_m=str(self.hi_m), hi_e=self.hi_e, K_bits=K_BITS, relative_inflation=self.inflation(), log2_hi=self.log2_hi(), storage_bytes=2 * (K_BITS // 8) + 16)


class LiftedRows:
    __slots__ = ('n', 'cards', 'ccards', 'classes', 'members', 'counts', 'cum', 'kappa', 'kappa_v', 'kappa_float', 'bytes', 'Q', 'K')
    def __init__(self): self.counts = {}; self.cum = {}; self.members = {}; self.kappa = None; self.K = None


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
        K = Compact.one(); R.kappa_v = []
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
                        if CE.bits(d) + Q_BITS + k.bit_length() > CE.BIT_CAP + 2 * Q_BITS: raise CE.Refused('BITS', 'lifted decoder: a per-variable ratio would need %d bits' % (CE.bits(d) + Q_BITS + k.bit_length()))   # guarded PER-VARIABLE ratio (no product across variables)
                        ratio = d / F(k, Qgrid)
                        if ratio > kv: kv = ratio
            if (v & 15) == 15: clock.poll('in the lifted decoder rows')
            R.kappa_v.append(kv); K = K.mul(Compact.from_fraction(kv))                            # compact outward product: K.lo <= prod kappa_v <= K.hi (lemma K); never the exact product in production
        R.K = K; R.kappa = None; R.kappa_float = float_up(K.hi()); clock.poll('at the lifted decoder exit'); return R
    except BaseException:
        budget.release(R.bytes); R.bytes = 0; raise


def exact_kappa(R):
    """ORACLE / CONTROLS ONLY: the exact rational product of the per-variable maxima (unbounded growth); production uses R.K"""
    kap = F(1)
    for kv in R.kappa_v: kap *= kv
    return kap


def float_up(q):
    """the smallest double >= the positive rational q (outward); for huge rationals via the exponent (no float() of the raw rational)"""
    if q.numerator.bit_length() > 1000 or q.denominator.bit_length() > 1000:
        s = q.numerator.bit_length() - q.denominator.bit_length(); m = q / F(2) ** s; x = math.ldexp(float(m), s)
        if F(x) < q: x = math.nextafter(x, math.inf)
        return x
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


def enumerate_check(M_par, classes, Cz, R, cap=1 << 16, upper_fn=None):
    """independent enumeration (controls only): support, normalization, pointwise W <= G_U d (G_U = the per-factor upper weight, or `upper_fn(c)` for a grouped envelope), d / r <= kappa; returns a dict of maxima"""
    import itertools
    n = len(M_par.cards); upper_fn = upper_fn or (lambda c: upper_weight(M_par, Cz, c))
    if math.prod(M_par.cards) > cap: raise CE.Refused('ENUM', 'enumeration cap')
    for v in range(n):
        for c, states in R.members[v].items():
            assert sum(R.counts[(v, c)]) == R.Q
            for a in states: assert (r_prob(R, v, c, a) > 0) == (Cz.d[v][a] > 0)
    worst_ratio = F(0); worst_env = F(0); zero_W = 0
    for z in itertools.product(*[range(k) for k in M_par.cards]):
        c = tuple(classes[v][z[v]] for v in range(n)); W = parent_weight(M_par, z); G = upper_fn(c)
        d = F(1); r = F(1)
        for v in range(n): d *= Cz.d[v][z[v]]; r *= r_prob(R, v, c[v], z[v])
        if W > G * d: raise CE.Defect('upper envelope violated at %s: W %s > G_U d %s' % (z, W, G * d))
        if W == 0: zero_W += 1
        if r > 0 and d / r > worst_ratio: worst_ratio = d / r
        if G * d > 0 and W / (G * d) > worst_env: worst_env = W / (G * d)
    kap = exact_kappa(R)
    if worst_ratio > kap: raise CE.Defect('kappa understated: %s > %s' % (worst_ratio, kap))
    if not R.K.contains(kap): raise CE.Defect('compact kappa enclosure does not contain the exact product')
    return dict(states=math.prod(M_par.cards), max_d_over_r=str(worst_ratio), kappa=str(kap), kappa_float=R.kappa_float, K_lo=str(R.K.lo()), K_hi=str(R.K.hi()), K_inflation=R.K.inflation(), max_W_over_envelope=str(worst_env), zero_weight_states=zero_W)
