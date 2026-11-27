"""DGP8 SPECTRAL_HEATBATH, part 2a: the EXACT reference heat-bath kernel (brief section 3; theory section 4 'Exact updates and arithmetic'). Pure Python / exact rationals: at every transition a site is selected exactly uniformly (random
bits with rejection), the conditional weights are the products of the original incident rational factors (unary included), their common denominator is cleared, a uniform integer below the integer sum is drawn by random-bit rejection
and the exact cumulative row is inverted. One fully completed random-site update = one step (a null move counts); nothing is counted before the draw and the state change are committed. Occupation counts by last-change timestamps:
a variable's dwell interval closes when its state changes and every variable is flushed at a checkpoint (tested against explicit per-step counts). This module is the REFERENCE for the controls and the EXACT FALLBACK of the native fast
path (heatbath_native.py): `decide_exact(weights, u53, bits)` refines the SAME progressively revealed uniform bit stream until the decision is resolved."""
import math, random
from fractions import Fraction as F
from pgm.algorithms.quotient import coarse_envelope as CE


class HeatBathModel:
    """the pairwise model in the form the kernels use: cards; unary rational weights psi[i][a]; pair factors (i, j, k_i, k_j, values row-major over (i, j)); incident[i] = [(f, role)] with role 0 when i is the FIRST variable of the scope"""
    def __init__(self, M):
        self.cards = list(M.cards); self.n = len(self.cards); self.psi = [[F(v) for v in row] for row in M.psi]; self.pairs = []; self.incident = [[] for _ in range(self.n)]
        for sc, vals in M.factors:
            if len(sc) == 1:
                i = sc[0]
                for a in range(self.cards[i]): self.psi[i][a] *= F(vals[a])
                continue
            if len(sc) != 2: raise ValueError('HeatBathModel: arity %d' % len(sc))
            i, j = sc; fi = len(self.pairs); self.pairs.append((i, j, self.cards[i], self.cards[j], [F(v) for v in vals])); self.incident[i].append((fi, 0)); self.incident[j].append((fi, 1))
        if any(v <= 0 for row in self.psi for v in row) or any(v <= 0 for p in self.pairs for v in p[4]): raise ValueError('HeatBathModel: a non-positive weight (hard zero)')
    def weights_exact(self, x, i):
        """exact rational conditional weights of variable i given the other coordinates of x"""
        w = list(self.psi[i])
        for fi, role in self.incident[i]:
            a_, b_, ki, kj, vals = self.pairs[fi]
            if role == 0:
                xb = x[b_]
                for a in range(ki): w[a] *= vals[a * kj + xb]
            else:
                xa = x[a_]
                for b in range(kj): w[b] *= vals[xa * kj + b]
        return w
    def log_weight(self, x):
        """ln W(x) as an exact Fraction product -> returned as the rational W(x) (callers take rigorous logs)"""
        W = F(1)
        for i in range(self.n): W *= self.psi[i][x[i]]
        for (i, j, ki, kj, vals) in self.pairs: W *= vals[x[i] * kj + x[j]]
        return W


def integerize(weights):
    """exact rational weights -> positive integer weights with the common denominator cleared, and their sum"""
    den = 1
    for w in weights: den = den * w.denominator // math.gcd(den, w.denominator)
    ints = [int(w.numerator * (den // w.denominator)) for w in weights]; return ints, sum(ints)


def uniform_below(S, bits_fn, clock=None, tag=''):
    """an exact uniform integer in [0, S) by random-bit rejection (bits_fn(k) -> k random bits as an int); polled"""
    k = S.bit_length(); tries = 0
    while True:
        r = bits_fn(k); tries += 1
        if r < S: return r, tries
        if clock is not None and (tries & 63) == 63: clock.poll('heat-bath rejection loop %s' % tag)


def invert_cumulative(ints, r):
    """the state a with C_{a-1} <= r < C_a for the integer cumulative row"""
    c = 0
    for a, w in enumerate(ints):
        c += w
        if r < c: return a
    raise AssertionError('cumulative inversion fell through')


def decide_exact(weights, u53, bits_fn, max_extra_bits=4096, clock=None, poll_every=64):
    """the exact decision for a PROGRESSIVELY REVEALED uniform bit stream whose first 53 bits are u53 (U in [u53 / 2^53, (u53 + 1) / 2^53)): refine with further bits until [U_lo S, U_hi S) lies inside one cumulative cell;
    -> (state, extra_bits_used). The law of the decision is EXACTLY the heat-bath conditional (U is uniform on [0, 1)). DGP9 (review RV6): POLLED every `poll_every` refinement bits when a clock is given (the DGP8 fallback
    could refine 4,096 bits without a deadline check). Integer comparisons only: u S vs cum 2^k (no Fraction allocation per refinement)."""
    ints, S = integerize(weights); cum = []; c = 0
    for w in ints: c += w; cum.append(c)
    k = 53; u = u53; extra = 0
    while True:
        lo_num = u * S; hi_num = (u + 1) * S; scale = 1 << k                                   # [U_lo S, U_hi S) = [lo_num, hi_num) / 2^k
        a = 0
        while cum[a] * scale <= lo_num: a += 1                                                 # the unique a with cum[a-1] <= U_lo S
        if hi_num <= cum[a] * scale: return a, extra
        if extra >= max_extra_bits: raise CE.Refused('RNG_REFINEMENT', 'the uniform bit stream did not resolve the heat-bath decision within %d extra bits' % max_extra_bits)
        if clock is not None and extra and (extra % poll_every) == 0: clock.poll('heat-bath exact fallback refinement (%d extra bits)' % extra)
        u = (u << 1) | bits_fn(1); k += 1; extra += 1


class ExactChain:
    """the reference chain: exact site selection, exact conditional draws, step / occupation bookkeeping with last-change timestamps"""
    def __init__(self, hbm, x0, seed, clock=None):
        self.m = hbm; self.x = list(x0); self.rng = random.Random(seed); self.t = 0; self.clock = clock; self.start = None; self.occ = None; self.site_tries = 0; self.draw_tries = 0
    def bits(self, k): return self.rng.getrandbits(k) if k > 0 else 0
    def select_site(self):
        n = self.m.n
        if n & (n - 1) == 0: return self.bits(n.bit_length() - 1)
        r, tries = uniform_below(n, self.bits, self.clock, 'site'); self.site_tries += tries - 1; return r
    def step(self):
        """ONE completed random-site update (null moves count); returns (i, old, new)"""
        i = self.select_site(); w = self.m.weights_exact(self.x, i); ints, S = integerize(w); r, tries = uniform_below(S, self.bits, self.clock, 'draw'); self.draw_tries += tries - 1; a = invert_cumulative(ints, r)
        old = self.x[i]
        # commit: the step counter advances only now, together with the state and the occupation bookkeeping
        self.t += 1
        if self.occ is not None and a != old: self.occ[i][old] += (self.t - 1) - self.start[i]; self.start[i] = self.t - 1
        self.x[i] = a; return i, old, a
    def start_recording(self):
        """the recording window begins AFTER the current step: states X_{t+1}, X_{t+2}, ... are counted"""
        self.occ = [[0] * k for k in self.m.cards]; self.start = [self.t] * self.m.n; self.t_record0 = self.t
    def flush(self):
        """close every open dwell interval at the current step (a checkpoint); the counts then equal sum_{s = t_record0 + 1}^{t} 1[X_s[i] = a]"""
        for i in range(self.m.n): self.occ[i][self.x[i]] += self.t - self.start[i]; self.start[i] = self.t
        return [list(row) for row in self.occ]
    # ---- DGP9: the runner-compatible interface (the exact chain is the CHECKED FALLBACK of the native route when the native range witness refuses; same calls as heatbath_native.NativeChain)
    def set_recording(self): self.start_recording()
    def steps(self): return self.t
    def state(self): return list(self.x)
    def counters(self): return dict(resolved=0, unresolved=0, null_moves=None, site_rejections=self.site_tries, exact_fallbacks=self.t, fallback_extra_bits=0, draw_rejections=self.draw_tries, exact_chain=True)
    def run(self, steps, batch=4096, tag=''):
        """exactly `steps` completed exact transitions, polled every `batch` steps"""
        done = 0
        while done < steps:
            if self.clock is not None: self.clock.poll('exact heat-bath batch %s (%d / %d)' % (tag, done, steps))
            want = min(batch, steps - done)
            for _ in range(want): self.step()
            done += want
        return done
    def close(self): pass
    def record(self): return dict(kind='exact rational chain (checked fallback)', site_rejections=self.site_tries, draw_rejections=self.draw_tries)


def exact_chain_bytes_estimate(hbm):
    """the host-side exact chain: the state, the occupation lists, the integer temporaries of one draw (common denominator x k)"""
    bits = sum(v.numerator.bit_length() + v.denominator.bit_length() for row in hbm.psi for v in row) + sum(v.numerator.bit_length() + v.denominator.bit_length() for p in hbm.pairs for v in p[4])
    return 64 * hbm.n + 64 * sum(hbm.cards) + (bits // 8 + 64) * (max(hbm.cards) + 3) + 4096


def conditional_exact(hbm, x, i):
    """the exact heat-bath conditional distribution of variable i (Fractions summing to one) -- the reference for the exact-conditional and detailed-balance controls"""
    w = hbm.weights_exact(x, i); S = sum(w); return [v / S for v in w]
