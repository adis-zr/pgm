"""Two actual collective evaluators (spec section 7).

7.1 Owned-statistic DP: insert each variable's integer statistic exactly once
    when it is forgotten; convolve disjoint forgotten statistics exactly at
    joins; multiply by the signed quadratic exponential at the root and sum.
    Signed energy does NOT mean signed DP masses.

7.2 Gaussian positive modes and Fourier negative modes via
    exp(+g S^2/2) = E exp(sqrt(g) Z S)  and  exp(-g S^2/2) = E exp(i sqrt(g) Z S).
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass
import itertools, math
from mdi import config as K, arith as A


class Declined(Exception):
    pass


# ======================= 7.1 owned-statistic DP =======================

def exact_round_half_up(x: Fr) -> int:
    """Exact round-half-UP on a rational. `round()` on a Fraction is BANKER'S
    rounding, so round(Fr(1,2)) == 0 and round(Fr(3,2)) == 2; the declared
    quantization semantics are half-up and must not depend on float conversion
    or on tie-to-even. The independent checker implements the same rule, so a
    mismatch here is a producer/checker law disagreement."""
    fl = x.numerator // x.denominator
    return fl + 1 if (x - fl) >= Fr(1, 2) else fl


def round_features(cand, free, Q: int):
    """Round each local feature ONCE to k_ki/Q, exactly (round-half-up)."""
    out = []
    for k in range(cand.rank):
        row = {}
        for v in sorted(free):
            f = cand.features[k].get(v)
            if f is None:
                row[v] = [0] * 2
                continue
            row[v] = [exact_round_half_up(Fr(x) * Q) for x in f]
        out.append(row)
    return out


def rounding_energy_bound(cand, free, kq, Q: int) -> Fr:
    """Spec 7.1: Delta <= (1/2) sum_k gamma_k tau_k (2 R_k + tau_k) with
       R_k   = sum_i max_a |f_ki(a)|
       tau_k = sum_i max_a |f_ki(a) - k_ki(a)/Q|
    """
    D = Fr(0)
    for k in range(cand.rank):
        Rk = Fr(0); tau = Fr(0)
        for v in sorted(free):
            f = cand.features[k].get(v)
            if f is None:
                continue
            Rk += max(abs(Fr(x)) for x in f)
            tau += max(abs(Fr(x) - Fr(kq[k][v][a], Q)) for a, x in enumerate(f))
        D += cand.gammas[k] * tau * (2 * Rk + tau)
    return D / 2


def statistic_dp(free, card, residual_unary, residual_pairs, kept_factors,
                 cand, Q: int, queries, cap_support=None):
    """Exact integer-statistic DP over a residual that is a PRODUCT law plus the
    retained factors. This implementation handles the product-residual case
    (no retained higher-arity factors), which is what the controls exercise.

    Masses stay NONNEGATIVE; the signed quadratic exponential is applied only at
    the root. Statistics are inserted once per variable, at the moment it is
    forgotten, and convolved exactly.
    """
    if kept_factors:
        raise Declined("statistic DP here requires a pure product residual; "
                       "%d retained factors present" % len(kept_factors))
    if residual_pairs:
        # This DP multiplies ONLY unary tables; it has no mechanism for a pair
        # factor. Accepting them silently produced wrong answers (a single
        # [1,1,1,9] pair gave 1/2 where the truth is 5/6). Refuse instead.
        raise Declined("statistic DP cannot consume %d residual PAIR factors; "
                       "it multiplies unary tables only. A general-residual DP "
                       "is not implemented." % len(residual_pairs))
    if cand.rank != 1:
        raise Declined("statistic DP implemented for rank 1 in this build")
    cap = cap_support or K.CAPS["local_mass_entries"]
    kq = round_features(cand, free, Q)
    # the DP state is the integer statistic s = sum_i k_i(a_i)
    # masses: dict s -> exact rational weight ; plus per-query marked masses
    acc = {0: Fr(1)}
    marks = {(v, a): {} for v in sorted(free) if v in queries for a in range(card[v])}
    for v in sorted(free):
        nxt = {}
        nmk = {key: {} for key in marks}
        for s, w in acc.items():
            for a in range(card[v]):
                uw = Fr(residual_unary[v][a])
                if uw == 0:
                    continue
                s2 = s + kq[0][v][a]
                nw = w * uw
                nxt[s2] = nxt.get(s2, Fr(0)) + nw
                # carry existing marks forward
                for key in marks:
                    mv = marks[key].get(s)
                    if mv is not None and mv != 0:
                        nmk[key][s2] = nmk[key].get(s2, Fr(0)) + mv * uw
                # insert this variable's own marker
                if (v, a) in nmk:
                    nmk[(v, a)][s2] = nmk[(v, a)].get(s2, Fr(0)) + nw
        acc = nxt
        marks = nmk
        if len(acc) > cap:
            raise Declined("statistic support %d exceeded the cap" % len(acc))
    return acc, marks, kq


def dp_root_combine(acc, marks, cand, Q: int, ctx: A.Ctx):
    """Multiply by exp(s_k gamma_k (S)^2 / 2) with S = s/Q and sum, with
    DIRECTED enclosures so the result is a rigorous interval."""
    import gmpy2
    s_k, g_k = cand.signs[0], cand.gammas[0]

    def wfac(s):
        S = Fr(s, Q)
        x = Fr(s_k) * g_k * S * S / 2
        with ctx.D:
            lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        with ctx.U:
            hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        return A.exact_fr(lo), A.exact_fr(hi)

    Zlo = Zhi = Fr(0)
    cache = {}
    for s, w in acc.items():
        if s not in cache:
            cache[s] = wfac(s)
        lo, hi = cache[s]
        Zlo += w * lo
        Zhi += w * hi
    out = {}
    for key, tab in marks.items():
        nlo = nhi = Fr(0)
        for s, w in tab.items():
            lo, hi = cache.get(s) or wfac(s)
            nlo += w * lo
            nhi += w * hi
        out[key] = (nlo, nhi)
    return (Zlo, Zhi), out


# ======================= 7.2 Gaussian / Fourier =======================

def gf_lattice(gamma: Fr, R: Fr, delta: Fr, second_derivative_bound=None):
    """Rational lattice and certified error for a scalar standard-normal average.

    exp(+g S^2/2) = E_Z exp(sqrt(g) Z S) with |S| <= R. The quantity actually
    integrated is the WEIGHTED integrand

        F(z) = phi(z) * (per-variable product),   |product| <= exp(sqrt(g)|z|R),

    so |F(z)| <= phi(z) exp(a|z|) with a = sqrt(g) R. The key identity is

        phi(z) e^{a z} = e^{a^2/2} phi(z - a),

    a SHIFTED GAUSSIAN. Hence, with M = e^{a^2/2}/sqrt(2 pi),
      * |F| <= M  and  |F''| <= M   (the second derivative of a unit Gaussian
        is ((z-a)^2 - 1) e^{-(z-a)^2/2}, bounded by 1 in absolute value), and
      * the two tails beyond |z| > T are at most 2 M exp(-(T-a)^2/2).

    Trapezoid error on [-T, T] with step h is at most (2T) h^2 M / 12. We split
    delta equally between tail and discretization and solve for T and h with
    exact integer/rational search. Deriving the constants this way (rather than
    copying binary cost constants) is what the spec requires.

    Bounding the integrand WITHOUT its Gaussian weight, as exp(sqrt(g) T R),
    inflates the node count by orders of magnitude and is wrong to use here.
    """
    g = Fr(gamma); Rr = Fr(R); d = Fr(delta)
    if g <= 0 or Rr < 0:
        raise Declined("gf_lattice needs gamma>0 and R>=0")
    if d <= 0:
        raise Declined("gf_lattice needs a positive delta")

    # All certificate constants are EXACT RATIONAL UPPER bounds. The previous
    # version computed M and the tail with binary64 math.* and then compared a
    # float-derived total against the target, which admitted a 1e-18 request
    # whose returned bound was 2e-15.
    a2 = g * Rr * Rr                      # a^2 = gamma * R^2, exact
    # M = e^{a^2/2} / sqrt(2 pi) <= e^{a^2/2} * (2/5), since 1/sqrt(2pi) < 0.4
    M_up = _exp_upper(a2 / 2) * Fr(2, 5)

    half = d / 2

    # tail: 2 M e^{-(T-a)^2/2} <= delta/2, with an EXACT comparison.
    # a <= ceil(sqrt(a2)) is an integer upper bound on a.
    a_up = _isqrt_ceil(a2)
    T = a_up + 1
    tail_up = None
    while T < 4096:
        dd = T - a_up                     # <= T - a, so the bound is conservative
        tail_up = 2 * M_up * _exp_upper(-Fr(dd * dd, 2))
        if tail_up <= half:
            break
        T += 1
    else:
        raise Declined("no truncation radius below 4096 meets delta=%s "
                       "(M upper bound %s)" % (d, M_up))

    # discretization: (2T) h^2 M2 / 12 <= delta/2, solved EXACTLY over dyadic h.
    # M2 is a bound on the SECOND DERIVATIVE of the integrand. For a positive
    # mode the shifted-Gaussian argument gives M2 <= M_up. For an OSCILLATORY
    # (Fourier) integrand the caller supplies its own larger bound: the phase
    # contributes g*S^2 and a cross term, so the positive-mode constant is not
    # valid and using it understated the truncation error.
    M2 = Fr(second_derivative_bound) if second_derivative_bound is not None \
        else M_up
    if M2 < M_up and second_derivative_bound is not None:
        # never silently accept a WEAKER bound than the Gaussian magnitude one
        M2 = M_up
    MAX_BITS = 40
    bits = 1
    hq = Fr(1, 2)
    disc_up = None
    while bits <= MAX_BITS:
        hq = Fr(1, 1 << bits)
        disc_up = Fr(2 * T) * hq * hq * M2 / 12
        if disc_up <= half:
            break
        bits += 1
    if disc_up is None or disc_up > half:
        raise Declined(
            "lattice cannot meet delta=%s: even a 2^-%d step leaves a "
            "discretization bound %s above %s with M upper bound %s and T=%d"
            % (d, MAX_BITS, disc_up, half, M_up, T))

    nodes = int(2 * T / hq) + 1
    total = tail_up + disc_up
    # the FINAL admission comparison is on the RETURNED bound, exactly
    if total > d:
        raise Declined(
            "lattice total bound %s exceeds the requested delta %s "
            "(tail %s + discretization %s); nodes would be %d"
            % (total, d, tail_up, disc_up, nodes))
    return {"T": T, "h": hq, "nodes": nodes,
            "a_squared": a2,
            "a_upper": a_up,
            "M_upper": M_up,
            "tail_bound": tail_up,
            "discretization_bound": disc_up,
            "total_bound": total,
            "exact_admission": True,
            "derivation": "shifted-Gaussian: phi(z)e^{az}=e^{a^2/2}phi(z-a); "
                          "|F|,|F''| <= M=e^{a^2/2}/sqrt(2pi) <= e^{a^2/2}*2/5; "
                          "trapezoid (2T)h^2 M/12; tails 2M exp(-(T-a)^2/2). "
                          "All constants are exact rational UPPER bounds and the "
                          "final comparison is exact on the returned total."}


def _exp_upper(x: Fr, terms=64) -> Fr:
    """An exact rational UPPER bound on exp(x) for any rational x.

    For x >= 0 a truncated series underestimates, so we use
    exp(x) <= sum_{k<n} x^k/k! + x^n/n! * 1/(1 - x/n) when x < n, which bounds
    the tail by a geometric series. For x < 0, exp(x) = 1/exp(-x) and a LOWER
    bound on exp(-x) gives an upper bound on exp(x).
    """
    x = Fr(x)
    if x == 0:
        return Fr(1)
    if x < 0:
        lo = _exp_lower(-x, terms)
        if lo <= 0:
            raise Declined("exp lower bound nonpositive")
        return Fr(1) / lo
    n = terms
    while Fr(n) <= x:
        n *= 2
        if n > 1 << 20:
            raise Declined("exp argument %s too large to bound" % x)
    s = Fr(0)
    term = Fr(1)
    for k in range(n):
        if k:
            term = term * x / k
        s += term
    tail = term * x / n / (Fr(1) - x / n)
    return s + tail


def _exp_lower(x: Fr, terms=64) -> Fr:
    """An exact rational LOWER bound on exp(x) for x >= 0: a truncated series."""
    x = Fr(x)
    if x < 0:
        up = _exp_upper(-x, terms)
        return Fr(1) / up
    s = Fr(0)
    term = Fr(1)
    for k in range(terms):
        if k:
            term = term * x / k
        s += term
    return s


def _isqrt_ceil(q: Fr) -> int:
    """Smallest integer n with n >= sqrt(q), exactly."""
    import math
    q = Fr(q)
    if q <= 0:
        return 0
    n = math.isqrt(q.numerator // max(1, q.denominator)) + 1
    while Fr(n * n) < q:
        n += 1
    while n > 0 and Fr((n - 1) * (n - 1)) >= q:
        n -= 1
    return n


def negative_response_bound(cand) -> Fr:
    """Conservative L = exp(-Y_max) with Y_max = (1/2) sum_{negative} g_k R_k^2.

    Returned as the exact rational EXPONENT Y_max; the caller encloses exp.
    """
    Y = Fr(0)
    for k in range(cand.rank):
        if cand.signs[k] >= 0:
            continue
        Rk = Fr(0)
        for v, f in cand.features[k].items():
            Rk += max(abs(Fr(x)) for x in f)
        Y += cand.gammas[k] * Rk * Rk
    return Y / 2


def marker_ratio(xl: Fr, xu: Fr, cl: Fr, cu: Fr):
    """Spec 7.2 sharp aggregation: [x_l/(x_l+c_u), x_u/(x_u+c_l)] with proved
    positivity and outward evaluation."""
    xl, xu, cl, cu = Fr(xl), Fr(xu), Fr(cl), Fr(cu)
    if min(xl, xu, cl, cu) < 0:
        raise Declined("negative marker mass")
    if xu + cl <= 0 or xl + cu <= 0:
        if xu + cl <= 0 and xl + cu <= 0:
            raise Declined("no positive denominator for the marker ratio")
    lo = xl / (xl + cu) if (xl + cu) > 0 else Fr(0)
    hi = xu / (xu + cl) if (xu + cl) > 0 else Fr(1)
    if lo > hi:
        raise Declined("inverted marker ratio")
    return (max(Fr(0), lo), min(Fr(1), hi))


def fourier_enclose(a_lo: Fr, a_hi: Fr, m_hi: Fr, delta: Fr):
    """Spec 7.2: enclose the negative-reweighted count by
       [max(0, a^- - delta m^+), min(m^+, a^+ + delta m^+)].
    An UNPROCESSED node contributes [0, m^+]."""
    d = Fr(delta) * Fr(m_hi)
    lo = max(Fr(0), Fr(a_lo) - d)
    hi = min(Fr(m_hi), Fr(a_hi) + d)
    if lo > hi:
        raise Declined("inverted Fourier enclosure")
    return (lo, hi)


def gaussian_evaluate(free, card, residual_unary, cand, queries, ctx: A.Ctx,
                      delta: Fr, cap_nodes=None):
    """Evaluate a POSITIVE rank-1 mode by Gaussian quadrature over the tilt.

    Each node adds a unary real tilt exp(sqrt(g) z f_i(a)), so the inner sum
    factorizes over variables: a product of per-variable sums. All markers are
    accumulated at every node. Returns interval masses.
    """
    import gmpy2
    if cand.rank != 1 or cand.signs[0] <= 0:
        raise Declined("gaussian_evaluate needs a single POSITIVE mode")
    g = cand.gammas[0]
    Rk = Fr(0)
    for v, f in cand.features[0].items():
        Rk += max(abs(Fr(x)) for x in f)
    lat = gf_lattice(g, Rk, delta)
    nodes = lat["nodes"]
    if cap_nodes and nodes > cap_nodes:
        raise Declined("gaussian lattice needs %d nodes, cap %d" % (nodes, cap_nodes))
    h, T = lat["h"], lat["T"]
    sg_lo, sg_hi = _sqrt_enclose(g, ctx)

    Zlo = Zhi = Fr(0)
    mk = {(v, a): [Fr(0), Fr(0)] for v in sorted(free) if v in queries
          for a in range(card[v])}
    j = -int(Fr(T) / h)
    jmax = int(Fr(T) / h)
    while j <= jmax:
        z = Fr(j) * h
        # standard normal weight, enclosed
        wl, wu = _normal_weight(z, h, ctx)
        # per-variable sums with the tilt
        plo = phi = Fr(1)
        per = {}
        for v in sorted(free):
            slo = shi = Fr(0)
            row = []
            for a in range(card[v]):
                uw = Fr(residual_unary[v][a])
                if uw == 0:
                    row.append((Fr(0), Fr(0))); continue
                fv = Fr(cand.features[0].get(v, [Fr(0)] * card[v])[a])
                x = (sg_lo if (z * fv) >= 0 else sg_hi) * z * fv
                lo, hi = _exp_enclose(z * fv, sg_lo, sg_hi, ctx)
                row.append((uw * lo, uw * hi))
                slo += uw * lo; shi += uw * hi
            per[v] = (row, slo, shi)
            plo *= slo; phi *= shi
        Zlo += wl * plo; Zhi += wu * phi
        for v in sorted(free):
            if v not in queries:
                continue
            row, slo, shi = per[v]
            for a in range(card[v]):
                rl, rh = row[a]
                # product with v's own term replaced by state a
                olo = plo / slo * rl if slo > 0 else Fr(0)
                ohi = phi / shi * rh if shi > 0 else Fr(0)
                mk[(v, a)][0] += wl * olo
                mk[(v, a)][1] += wu * ohi
        j += 1
    return (Zlo, Zhi), {k: tuple(v) for k, v in mk.items()}, lat


def _sqrt_enclose(q: Fr, ctx: A.Ctx):
    import gmpy2
    with ctx.D:
        lo = gmpy2.sqrt(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    with ctx.U:
        hi = gmpy2.sqrt(gmpy2.mpfr(gmpy2.mpq(q.numerator, q.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _exp_enclose(t: Fr, sg_lo: Fr, sg_hi: Fr, ctx: A.Ctx):
    """Enclose exp(sqrt(g) * t) given an enclosure of sqrt(g)."""
    import gmpy2
    a = sg_lo * t if t >= 0 else sg_hi * t
    b = sg_hi * t if t >= 0 else sg_lo * t
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(a.numerator, a.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(b.numerator, b.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _normal_weight(z: Fr, h: Fr, ctx: A.Ctx):
    """Enclose the quadrature weight h * phi(z), phi the standard normal pdf.

    The constant 1/sqrt(2 pi) is a QUOTIENT, so its endpoints need opposite
    rounding on numerator and denominator: a lower bound divides by an UPWARD
    -rounded sqrt(2 pi), an upper bound by a DOWNWARD-rounded one. Rounding the
    denominator in the same direction as the result (the previous code) makes
    the "lower" endpoint too large, and at p=24 that inverted 35 of 81 nodes.
    """
    import gmpy2
    x = -(z * z) / 2
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        den_hi = gmpy2.sqrt(2 * gmpy2.const_pi())      # over-estimate
    with ctx.D:
        den_lo = gmpy2.sqrt(2 * gmpy2.const_pi())      # under-estimate
    c_lo = Fr(1) / A.exact_fr(den_hi)                  # smallest 1/sqrt(2pi)
    c_hi = Fr(1) / A.exact_fr(den_lo)                  # largest
    if not (0 < c_lo <= c_hi):
        raise Declined("normal-weight constant enclosure is invalid")
    out = (h * A.exact_fr(lo) * c_lo, h * A.exact_fr(hi) * c_hi)
    if out[0] > out[1]:
        raise Declined("inverted quadrature weight")
    return out


# ================= complex negative Fourier evaluation (§7.2) =================

def _cmul(a, b):
    """Interval complex multiplication on rectangles.

    a = (re_lo, re_hi, im_lo, im_hi), likewise b. Returns the rectangular hull
    of the product. Each real part of the product is a sum/difference of two
    real interval products, so every endpoint combination is taken.

    The previous code multiplied only MODULUS upper bounds, which discards the
    phase entirely and so cannot represent an oscillatory cancellation: the
    accumulated node contribution was the symmetric [-|z|, +|z|] regardless of
    the actual complex value, which is never informative. It also multiplied a
    negative lower contribution by the LOWER positive weight, the wrong endpoint
    direction for a signed product.
    """
    arl, arh, ail, aih = a
    brl, brh, bil, bih = b
    def prod(xl, xh, yl, yh):
        c = (xl * yl, xl * yh, xh * yl, xh * yh)
        return min(c), max(c)
    rr_lo, rr_hi = prod(arl, arh, brl, brh)      # Re*Re
    ii_lo, ii_hi = prod(ail, aih, bil, bih)      # Im*Im
    ri_lo, ri_hi = prod(arl, arh, bil, bih)      # Re*Im
    ir_lo, ir_hi = prod(ail, aih, brl, brh)      # Im*Re
    # Re(ab) = Re*Re - Im*Im ; Im(ab) = Re*Im + Im*Re
    return (rr_lo - ii_hi, rr_hi - ii_lo, ri_lo + ir_lo, ri_hi + ir_hi)


def _scale_interval(lo: Fr, hi: Fr, wl: Fr, wu: Fr):
    """Multiply the interval [lo,hi] by a NONNEGATIVE weight interval [wl,wu],
    taking the correct endpoint direction for each sign. Scaling a negative
    lower bound by the lower weight understates the magnitude."""
    c = (lo * wl, lo * wu, hi * wl, hi * wu)
    return min(c), max(c)


def fourier_lattice(gamma: Fr, R: Fr, delta: Fr):
    """Lattice and certified error for the OSCILLATORY (negative-mode) average

        exp(-g S^2 / 2) = E_Z exp(i sqrt(g) Z S),   |S| <= R.

    The integrand is phi(z) times a product of UNIT-MODULUS phases, so

        |F(z)| <= phi(z) <= 1/sqrt(2 pi) < 2/5

    with NO exp(a^2/2) growth factor and NO shifted mean. The positive-mode
    construction bounds |F| by e^{a^2/2}/sqrt(2 pi) with a = sqrt(g) R and
    truncates around a shifted centre, because there the per-variable sums
    grow like e^{sqrt(g) z R}. Forcing those constants onto the oscillatory
    integrand made the lattice unaffordable: at g = 1, R = 10, delta = 1e-3 it
    refused even at a 2^-40 step, since e^{50} multiplies every bound.

    Tails: the two tails beyond |z| > T are at most 2 * phi-tail, and for
    T >= 1, int_{|z|>T} phi <= 2 phi(T)/T <= (4/5) e^{-T^2/2} / T.

    Discretization: the evaluator sums FULL endpoint weights, so it is a
    composite MIDPOINT rule on [-T - h/2, T + h/2], not the trapezoid rule.
    The reviewer supplied the proof that the recorded bound is nevertheless
    valid, and it is documented here rather than left as a wording mismatch:

        midpoint error on [-T-h/2, T+h/2]  <=  (2T + h) h^2 M2 / 24
                                           <=  (2T) h^2 M2 / 12   when h <= 2T

    since (2T + h)/24 <= (2T + 2T)/24 = (2T)/12. The global second-derivative
    bound M2 applies on the slightly expanded interval, and the recorded tail
    beyond T dominates the tail beyond T + h/2 (the expanded interval is
    LARGER, so its tail is smaller). Hence the recorded
    (2T) h^2 M2 / 12 is a valid upper bound for the program that actually
    runs, and NO extra padding is required for the endpoint-weight
    convention.

    delta is split equally between tail and discretization, solved exactly.
    """
    g, Rr, d = Fr(gamma), Fr(R), Fr(delta)
    if g <= 0 or Rr < 0:
        raise Declined("fourier_lattice needs gamma>0 and R>=0")
    if d <= 0:
        raise Declined("fourier_lattice needs a positive delta")
    half = d / 2
    M2 = fourier_second_derivative_bound(g, Rr)

    # tail: (4/5) e^{-T^2/2} / T <= delta/2, exact comparison
    T = 1
    tail_up = None
    while T < 4096:
        tail_up = Fr(4, 5) * _exp_upper(-Fr(T * T, 2)) / Fr(T)
        if tail_up <= half:
            break
        T += 1
    else:
        raise Declined("no oscillatory truncation radius below 4096 meets "
                       "delta=%s" % d)

    # discretization: (2T) h^2 M2 / 12 <= delta/2 over dyadic h
    MAX_BITS = 40
    bits, hq, disc_up = 1, Fr(1, 2), None
    while bits <= MAX_BITS:
        hq = Fr(1, 1 << bits)
        disc_up = Fr(2 * T) * hq * hq * M2 / 12
        if disc_up <= half:
            break
        bits += 1
    if disc_up is None or disc_up > half:
        raise Declined(
            "oscillatory lattice cannot meet delta=%s: even a 2^-%d step "
            "leaves %s against %s" % (d, MAX_BITS, disc_up, half))

    total = tail_up + disc_up
    if total > d:
        raise Declined("oscillatory lattice total bound %s exceeds delta %s"
                       % (total, d))
    nodes = 2 * int(Fr(T) / hq) + 1
    return {"T": T, "h": hq, "nodes": nodes,
            "tail_bound": tail_up, "discretization_bound": disc_up,
            "total_bound": total, "second_derivative_bound": M2,
            "derivation": "unit-modulus oscillatory integrand: |F| <= phi, no "
                          "exp(gamma R^2/2) factor and no shifted centre"}


def fourier_second_derivative_bound(g: Fr, Rk: Fr) -> Fr:
    """A rigorous bound on |d^2/dz^2 [ phi(z) * exp(i sqrt(g) z S) ]| for
    |S| <= Rk, used for the lattice discretization error.

    The integrand is the Gaussian density times an OSCILLATORY phase, so the
    positive-Gaussian constant is NOT valid here: differentiating the phase
    twice contributes g*S^2 and the cross term contributes 2*sqrt(g)*|S*z|.
    With phi(z) <= 1/sqrt(2 pi) < 2/5 and |z phi(z)| <= 1/sqrt(2 pi e) < 1/4
    and |(z^2-1) phi(z)| <= 2/5:

        |f''| <= 2/5 + 2*sqrt(g)*Rk*(1/4) + g*Rk^2*(2/5)

    The code previously reused the positive-mode constant 0.4205084385504096,
    which is smaller than a rigorous lower bound 0.43883650844157596 on the
    relevant second-derivative magnitude, so the truncation bound it produced
    was not valid for the oscillatory integrand.
    """
    sg_hi = _isqrt_ceil_fr(g)
    return Fr(2, 5) + 2 * sg_hi * Rk * Fr(1, 4) + g * Rk * Rk * Fr(2, 5)


def _isqrt_ceil_fr(x: Fr) -> Fr:
    """A rational UPPER bound on sqrt(x) for x >= 0."""
    if x <= 0:
        return Fr(0)
    num = _isqrt_ceil(x.numerator * 10 ** 12)
    den = _isqrt_floor(x.denominator * 10 ** 12)
    if den == 0:
        den = 1
    return Fr(num, den)


def _isqrt_floor(n: int) -> int:
    import math as _m
    if n <= 0:
        return 0
    return _m.isqrt(n)


def fourier_evaluate(free, card, residual_unary, cand, queries, ctx: A.Ctx,
                     delta: Fr, cap_nodes=None, deadline=None):
    """Evaluate a NEGATIVE rank-1 mode by the complex-phase identity

        exp(-g S^2 / 2) = E_Z exp(i sqrt(g) Z S),   S = sum_i f_i(z_i).

    Each quadrature node contributes a unary COMPLEX phase, so the inner sum
    factorizes over variables exactly as in the Gaussian case. The per-variable
    complex sums are multiplied as interval RECTANGLES, preserving the phase,
    and the node's real part is accumulated with its correct sign. The
    imaginary part of the exact integral is zero by symmetry and is tracked only
    as a consistency witness.

    Directed enclosures are used for the angle construction and for cos and sin,
    including interior extrema at both signs.
    """
    import gmpy2
    if cand.rank != 1 or cand.signs[0] >= 0:
        raise Declined("fourier_evaluate needs a single NEGATIVE mode")
    g = cand.gammas[0]
    Rk = Fr(0)
    for v, f in cand.features[0].items():
        Rk += max(abs(Fr(x)) for x in f)
    # the OSCILLATORY discretization bound, not the positive-Gaussian constant
    m2 = fourier_second_derivative_bound(g, Rk)
    # the OSCILLATORY lattice: a unit-modulus phase needs neither the
    # positive-mode exp(gamma R^2 / 2) magnitude factor nor a shifted tail
    lat = fourier_lattice(g, Rk, delta)
    nodes = lat["nodes"]
    if cap_nodes and nodes > cap_nodes:
        raise Declined("fourier lattice needs %d nodes, cap %d"
                       % (nodes, cap_nodes))
    h, T = lat["h"], lat["T"]
    sg_lo, sg_hi = _sqrt_enclose(g, ctx)

    Ymax = negative_response_bound(cand)

    Zlo = Zhi = Fr(0)
    Imlo = Imhi = Fr(0)
    mk = {(v, a): [Fr(0), Fr(0)] for v in sorted(free) if v in queries
          for a in range(card[v])}
    jmin = -int(Fr(T) / h)
    jmax = int(Fr(T) / h)
    j = jmin
    processed = 0
    expected = jmax - jmin + 1
    while j <= jmax:
        if deadline is not None and (processed & 0xFF) == 0:
            deadline()
        processed += 1
        z = Fr(j) * h
        wl, wu = _normal_weight(z, h, ctx)
        # per-variable complex sums: sum_a u(a) * exp(i theta_a),
        # theta_a = sqrt(g) * z * f_i(a)
        per = {}
        # the running complex product over variables, as a rectangle
        prod = (Fr(1), Fr(1), Fr(0), Fr(0))
        for v in sorted(free):
            re_lo = re_hi = Fr(0)
            im_lo = im_hi = Fr(0)
            rows = []
            for a in range(card[v]):
                uw = Fr(residual_unary[v][a])
                if uw == 0:
                    rows.append((Fr(0), Fr(0), Fr(0), Fr(0)))
                    continue
                fv = Fr(cand.features[0].get(v, [Fr(0)] * card[v])[a])
                t = z * fv
                alo = (sg_lo if t >= 0 else sg_hi) * t
                ahi = (sg_hi if t >= 0 else sg_lo) * t
                clo, chi = _cos_enclose(alo, ahi, ctx)
                slo, shi = _sin_enclose(alo, ahi, ctx)
                rows.append((uw * clo, uw * chi, uw * slo, uw * shi))
                re_lo += uw * clo; re_hi += uw * chi
                im_lo += uw * slo; im_hi += uw * shi
            per[v] = (rows, re_lo, re_hi, im_lo, im_hi)
            prod = _cmul(prod, (re_lo, re_hi, im_lo, im_hi))
            if max(abs(prod[0]), abs(prod[1])) > Fr(10) ** 60:
                raise Declined("complex product exceeded a safe range")
        # the node contributes its REAL part, scaled by the nonnegative weight
        nlo, nhi = _scale_interval(prod[0], prod[1], wl, wu)
        Zlo += nlo
        Zhi += nhi
        ilo, ihi = _scale_interval(prod[2], prod[3], wl, wu)
        Imlo += ilo
        Imhi += ihi
        # marked response: divide out one variable's factor by recomputing the
        # product over the OTHERS, so no division of intervals is needed
        for v in sorted(free):
            if v not in queries:
                continue
            rows = per[v][0]
            others = (Fr(1), Fr(1), Fr(0), Fr(0))
            for u in sorted(free):
                if u == v:
                    continue
                _r, rl, rh, il, ih = per[u]
                others = _cmul(others, (rl, rh, il, ih))
            for a in range(card[v]):
                arl, arh, ail, aih = rows[a]
                if arl == arh == ail == aih == 0:
                    continue
                cp = _cmul((arl, arh, ail, aih), others)
                clo_, chi_ = _scale_interval(cp[0], cp[1], wl, wu)
                mk[(v, a)][0] += clo_
                mk[(v, a)][1] += chi_
        j += 1          # <-- the lattice index. Its absence made this loop
                        #     never terminate: a declared 33-node lattice
                        #     re-evaluated node z = -4 indefinitely.
    if processed != expected:
        raise Declined("fourier lattice processed %d of %d declared nodes"
                       % (processed, expected))
    # The lattice sum approximates the integral; its CERTIFIED truncation and
    # discretization error must widen the returned enclosure, or the result is
    # a point that excludes the true value. The accumulated interval tracked
    # only the per-node arithmetic rounding.
    qerr = Fr(lat["total_bound"])
    # the error is on the normalized average; scale by the total unary mass,
    # which bounds the modulus of the per-variable product sum
    mass = Fr(1)
    for v in sorted(free):
        mass *= sum(abs(Fr(x)) for x in residual_unary[v])
    wid = qerr * mass
    Zlo -= wid
    Zhi += wid
    for key in mk:
        mk[key][0] -= wid
        mk[key][1] += wid
    # the exact integral is real; a nonzero-excluding imaginary enclosure is a
    # defect witness, not something to discard
    if Imlo > 0 or Imhi < 0:
        raise Declined(
            "the accumulated imaginary part [%s, %s] excludes zero, so the "
            "complex contraction is inconsistent with a real integral"
            % (Imlo, Imhi))
    meta = {"nodes": nodes, "T": T, "h": h, "processed": processed,
            "expected_nodes": expected,
            "negative_exponent_Ymax": Ymax,
            "second_derivative_bound": str(m2),
            "imaginary_enclosure": (str(Imlo), str(Imhi)),
            "lattice": {k: str(v) for k, v in lat.items() if k != "derivation"},
            "note": "complex-phase identity exp(-gS^2/2) = E exp(i sqrt(g) Z S); "
                    "per-variable complex sums multiplied as interval "
                    "rectangles preserving phase, real part accumulated with "
                    "signed endpoint direction, oscillatory discretization "
                    "bound"}
    return (Zlo, Zhi), {k: tuple(v) for k, v in mk.items()}, meta


def _modulus_upper(re_lo: Fr, re_hi: Fr, im_lo: Fr, im_hi: Fr) -> Fr:
    """An exact rational UPPER bound on |x + iy| over the rectangle."""
    rm = max(abs(re_lo), abs(re_hi))
    im = max(abs(im_lo), abs(im_hi))
    # |x+iy| <= |x| + |y|, exact and sufficient
    return rm + im


def _pi_bounds(ctx: A.Ctx = None):
    """Rigorous rational bounds on pi, at high precision.

    The coarse constants 314159/100000 and 3927/1250 have a relative slack of
    about 3.18e-6. Multiplied by a critical index k, that slack grows like
    |k|, so a FIXED one-or-two-index pad around a coarse quotient cannot
    locate k*pi at large |k|: around -1,000,000*pi the search range came out
    [-999999, -999999] and never reached k = -1000000, so the cosine
    enclosure missed its true maximum 1 by about 5e-7.
    """
    import gmpy2
    p = 512 if ctx is None else max(512, 4 * ctx.p)
    with gmpy2.context(precision=p, round=gmpy2.RoundDown):
        lo = A.exact_fr(gmpy2.const_pi())
    with gmpy2.context(precision=p, round=gmpy2.RoundUp):
        hi = A.exact_fr(gmpy2.const_pi())
    return lo, hi


def _critical_index_range(lo: Fr, hi: Fr, pi_lo: Fr, pi_hi: Fr, shift: Fr):
    """Every integer k with (shift + k*pi) possibly inside [lo, hi].

    Solved with SIGN-CORRECT rational quotient bounds: for k*pi to land in
    [lo - shift, hi - shift], k must lie between the two quotients taken with
    the pi bound that makes each extreme largest. Both signs of k are handled
    explicitly, and the result is padded by one index on each side only to
    absorb the division's own flooring.
    """
    a, b = lo - shift, hi - shift
    cands = []
    for piv in (pi_lo, pi_hi):
        for end in (a, b):
            cands.append(Fr(end) / piv)
    k_lo = min(cands)
    k_hi = max(cands)
    import math as _m
    return _m.floor(k_lo) - 1, _m.ceil(k_hi) + 1


def _trig_point_enclose(q: Fr, ctx: A.Ctx, which: str):
    """Rigorous enclosure of sin(q) or cos(q) at an EXACT RATIONAL q.

    `gmpy2.mpfr(mpq(...))` rounds the ARGUMENT, and the previous code rounded
    the argument and the function in the SAME direction. On a decreasing
    branch that composition does not bound the value at the exact rational
    argument: for sin(197658/49435) at precision 160 the returned upper bound
    fell 9.42e-50 BELOW a rigorously enclosed reference, and at 24 bits the
    discrepancy exceeded 2.38e-9.

    Both |sin'| <= 1 and |cos'| <= 1, so an argument perturbation of at most
    `da` moves the value by at most `da`. We therefore:
      * evaluate at EXTRA precision in both directions, bounding the
        function's own rounding, and
      * add the exact argument-conversion error as a Lipschitz allowance.
    The result is a valid enclosure of the exact-argument value.
    """
    import gmpy2
    p = ctx.p
    extra = 2 * p + 64
    fn = gmpy2.sin if which == "sin" else gmpy2.cos
    # the exact rational argument, converted at EXTRA precision both ways, so
    # the conversion error itself is bounded exactly
    cd = gmpy2.context(precision=extra, round=gmpy2.RoundDown)
    cu = gmpy2.context(precision=extra, round=gmpy2.RoundUp)
    mq = gmpy2.mpq(q.numerator, q.denominator)
    with cd:
        a_d = gmpy2.mpfr(mq)
    with cu:
        a_u = gmpy2.mpfr(mq)
    # exact argument-conversion error in each direction
    da = max(abs(q - A.exact_fr(a_d)), abs(A.exact_fr(a_u) - q))
    with cd:
        v_lo = min(fn(a_d), fn(a_u))
    with cu:
        v_hi = max(fn(a_d), fn(a_u))
    lo = A.exact_fr(v_lo) - da
    hi = A.exact_fr(v_hi) + da
    # the function's own value is in [-1, 1] regardless
    return max(Fr(-1), lo), min(Fr(1), hi)


def _cos_enclose(lo: Fr, hi: Fr, ctx: A.Ctx):
    """Directed enclosure of cos over [lo, hi], INCLUDING interior extrema."""
    import gmpy2
    if lo > hi:
        lo, hi = hi, lo
    width = hi - lo
    # pi upper bound: 3.1416 > pi
    pi_up = Fr(31416, 10000)
    if width >= 2 * pi_up:
        return Fr(-1), Fr(1)
    l1, h1 = _trig_point_enclose(lo, ctx, "cos")
    l2, h2 = _trig_point_enclose(hi, ctx, "cos")
    out_lo, out_hi = min(l1, l2), max(h1, h2)
    # an interior extremum of cos sits at a multiple of pi. If the interval can
    # contain one, widen conservatively.
    # RIGOROUS pi bounds, and a sign-correct critical-index range. Negative-k
    # brackets must also be ordered: for k < 0 the product with the LARGER pi
    # bound is the SMALLER number.
    pl, ph = _pi_bounds(ctx)
    k_lo, k_hi = _critical_index_range(lo, hi, pl, ph, Fr(0))
    if k_hi - k_lo > 4096:
        # the interval spans thousands of critical points, so both extrema are
        # certainly attained
        return Fr(-1), Fr(1)
    for k in range(k_lo, k_hi + 1):
        a, b = Fr(k) * pl, Fr(k) * ph
        centre_lo, centre_hi = (a, b) if a <= b else (b, a)
        if (lo <= centre_hi and centre_lo <= hi):
            if k % 2 == 0:
                out_hi = Fr(1)
            else:
                out_lo = Fr(-1)
    return max(Fr(-1), out_lo), min(Fr(1), out_hi)


def _sin_enclose(lo: Fr, hi: Fr, ctx: A.Ctx):
    """Directed enclosure of sin over [lo, hi], INCLUDING interior extrema."""
    import gmpy2
    if lo > hi:
        lo, hi = hi, lo
    pi_up = Fr(31416, 10000)
    if hi - lo >= 2 * pi_up:
        return Fr(-1), Fr(1)
    l1, h1 = _trig_point_enclose(lo, ctx, "sin")
    l2, h2 = _trig_point_enclose(hi, ctx, "sin")
    out_lo, out_hi = min(l1, l2), max(h1, h2)
    pl, ph = _pi_bounds(ctx)
    # sin's extrema sit at pi/2 + k*pi; the shift is bracketed too, so take
    # the widest span over both pi bounds
    k_lo1, k_hi1 = _critical_index_range(lo, hi, pl, ph, pl / 2)
    k_lo2, k_hi2 = _critical_index_range(lo, hi, pl, ph, ph / 2)
    k_lo, k_hi = min(k_lo1, k_lo2), max(k_hi1, k_hi2)
    if k_hi - k_lo > 4096:
        return Fr(-1), Fr(1)
    for k in range(k_lo, k_hi + 1):
        ends = [pl / 2 + Fr(k) * pl, ph / 2 + Fr(k) * ph,
                pl / 2 + Fr(k) * ph, ph / 2 + Fr(k) * pl]
        centre_lo, centre_hi = min(ends), max(ends)
        if (lo <= centre_hi and centre_lo <= hi):
            if k % 2 == 0:
                out_hi = Fr(1)
            else:
                out_lo = Fr(-1)
    return max(Fr(-1), out_lo), min(Fr(1), out_hi)
