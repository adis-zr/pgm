"""Exact / rigorously bounded arithmetic shared by producer and verifier (PROOF-CRITICAL SHARED HELPERS, listed here explicitly):
rational kernel integers, theta / tanh identities in rationals, tails, the dyadic interval vector IVec (block-exponent integer
enclosures with outward rounding to P bits), limb-split exact distance histograms, publication rounding on the 2^-80 grid, and the
event / complement normalization (B)."""
from __future__ import annotations
from fractions import Fraction as Fr
from math import comb
import numpy as np

GRID_BITS = 80
P_BITS = 96                                       # mantissa bits of the dyadic enclosures


def uv(r):
    r = Fr(r)
    assert 0 <= r <= 1
    return r.numerator, r.denominator


def kappa_int(dprime, u, v, dist):
    """K_r on d' coordinates at Hamming distance `dist`, times v^d': (v+u)^(d'-dist) (v-u)^dist."""
    return (v + u) ** (dprime - dist) * (v - u) ** dist


def exp2L(r, s):
    """exp(2 s atanh r) = ((1+r)/(1-r))^s exactly (rational); None at r = 1."""
    r = Fr(r)
    return None if r == 1 else ((1 + r) / (1 - r)) ** s


def tanh_from_exp2L(E):
    """tanh(L) = (e^{2L} - 1)/(e^{2L} + 1)."""
    return Fr(1) if E is None else (E - 1) / (E + 1)


def theta_edge(r, s):
    """theta_e = tanh(s_e atanh r_e): the TV contraction of one kernel on s varying coordinates (exact rational)."""
    return tanh_from_exp2L(exp2L(r, s))


def tanh_half_sum_atanh(etas):
    """tanh( (1/2) sum atanh(eta_e) ): exp(2L) = prod sqrt((1+eta)/(1-eta)) is irrational in general; use the sound upper bound
    tanh(x/2) <= x/2 with x = sum atanh(eta) <= sum eta/(1-eta) ... both bounds kept rational: return min(1, (1/2) sum eta/(1-eta))."""
    s = sum((Fr(e) / (1 - Fr(e)) for e in etas), Fr(0))
    return min(Fr(1), s / 2)


def tail(dprime, k, r, parity=None):
    """sum_{j>k} C(d', j) r^j, optionally restricted to even / odd j."""
    r = Fr(r)
    return sum((comb(dprime, j) * r ** j for j in range(k + 1, dprime + 1) if parity is None or j % 2 == parity), Fr(0))


PUBLISH_SLACK_STEPS = 1        # one extra grid step per side so an independent re-derivation (different exact accumulation order,
                               # hence different dyadic rounding) is contained; total added width <= 4 * 2^-80 = 2^-78


def publish(lo, hi, slack=PUBLISH_SLACK_STEPS):
    """Exact rational [lo, hi] -> grid integers on 2^-GRID_BITS: floor / ceil (outward) plus `slack` steps per side, clipped to [0, 1]."""
    lo, hi = Fr(lo), Fr(hi)
    assert lo <= hi
    q = 1 << GRID_BITS
    lg = (lo * q).numerator // (lo * q).denominator - slack
    hg = -((-hi * q).numerator // (-hi * q).denominator) + slack
    return max(0, lg), min(q, hg)


EPS_PUBLISH_SLACK = Fr(2 + 2 * PUBLISH_SLACK_STEPS, 1 << GRID_BITS)      # the most the publication can add to a width


def normalize_event(LA, UA, LC, UC):
    """(B): event mass in [LA, UA], complement in [LC, UC] (nonnegative, UA + UC > 0): probability enclosure, conservative at zero denominators."""
    lo = Fr(LA, LA + UC) if LA + UC > 0 else Fr(0)
    hi = Fr(UA, UA + LC) if UA + LC > 0 else Fr(1)
    return lo, min(hi, Fr(1))


class IVec:
    """Nonnegative dyadic interval vector: entry i lies in [lo[i], hi[i]] * 2^exp (lo, hi Python ints in a numpy object array)."""
    __slots__ = ("lo", "hi", "exp")

    def __init__(self, lo, hi, exp=0):
        self.lo = np.array(lo, dtype=object); self.hi = np.array(hi, dtype=object); self.exp = int(exp)

    @staticmethod
    def exact(ints, exp=0):
        a = np.array([int(x) for x in ints], dtype=object)
        return IVec(a, a.copy(), exp)

    def __len__(self):
        return len(self.lo)

    def bits(self):
        return max((int(x).bit_length() for x in self.hi.tolist()), default=0)

    def normalize(self, P=P_BITS):
        """Round OUTWARD so that every hi fits in P bits (lo floored, hi ceiled); the exponent absorbs the shift."""
        s = self.bits() - P
        if s <= 0:
            return self
        lo = np.array([int(x) >> s for x in self.lo.tolist()], dtype=object)
        hi = np.array([-((-int(x)) >> s) for x in self.hi.tolist()], dtype=object)
        return IVec(lo, hi, self.exp + s)

    def mul(self, other):
        assert len(self) == len(other)
        return IVec(self.lo * other.lo, self.hi * other.hi, self.exp + other.exp).normalize()

    def scale_int(self, c):
        c = int(c); assert c > 0
        return IVec(self.lo * c, self.hi * c, self.exp).normalize()

    def mass(self):
        return int(sum(self.lo.tolist())), int(sum(self.hi.tolist()))

    def masked_mass(self, sel):
        """(lo, hi) of the sum over the boolean selection."""
        return int(sum(self.lo[sel].tolist())), int(sum(self.hi[sel].tolist()))

    def contains(self, other):
        """Every entry interval of `other` (same exp alignment handled) lies inside this one's."""
        if len(self) != len(other):
            return False
        e = min(self.exp, other.exp)
        a_lo = [int(x) << (self.exp - e) for x in self.lo.tolist()]; a_hi = [int(x) << (self.exp - e) for x in self.hi.tolist()]
        b_lo = [int(x) << (other.exp - e) for x in other.lo.tolist()]; b_hi = [int(x) << (other.exp - e) for x in other.hi.tolist()]
        return all(al <= bl and bh <= ah for al, ah, bl, bh in zip(a_lo, a_hi, b_lo, b_hi))


def ones(n):
    return IVec.exact([1] * n)


LIMB = 30


def hist_by_distance(src_rows, src_ints, tgt_rows, mask, dprime, chunk=256):
    """Exact per-target histograms H[y][dist] = sum_{x: popcount((x ^ y) & mask) = dist} src_ints[x], for Python-int weights of any size:
    the weights are split into base-2^30 limbs, each limb histogrammed with float64 bincount (exact: count * 2^30 < 2^53 needs
    len(src) < 2^23), then recombined. Returns a list (per target) of lists (per distance) of ints."""
    src = np.asarray(src_rows, dtype=np.uint64); tgt = np.asarray(tgt_rows, dtype=np.uint64); m = np.uint64(mask)
    assert len(src) < (1 << 23)
    wmax = max((int(w) for w in src_ints), default=0); nl = max(1, (wmax.bit_length() + LIMB - 1) // LIMB)
    limbs = []
    rem = [int(w) for w in src_ints]
    for _ in range(nl):
        limbs.append(np.array([w & ((1 << LIMB) - 1) for w in rem], dtype=np.float64)); rem = [w >> LIMB for w in rem]
    out = []
    for s in range(0, len(tgt), chunk):
        ys = tgt[s:s + chunk]
        D = np.bitwise_count((ys[:, None] ^ src[None, :]) & m).astype(np.int64)
        ids = (np.arange(len(ys), dtype=np.int64)[:, None] * (dprime + 1) + D).ravel()
        acc = [[0] * (dprime + 1) for _ in range(len(ys))]
        for li, lw in enumerate(limbs):
            c = np.bincount(ids, weights=np.broadcast_to(lw, D.shape).ravel(), minlength=len(ys) * (dprime + 1)).reshape(len(ys), dprime + 1)
            sh = LIMB * li
            for j in range(len(ys)):
                row = acc[j]; cj = c[j]
                for dd in range(dprime + 1):
                    cv = cj[dd]
                    if cv:
                        row[dd] += int(cv) << sh
        out.extend(acc)
    return out
