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

def round_features(cand, free, Q: int):
    """Round each local feature ONCE to k_ki/Q, exactly."""
    out = []
    for k in range(cand.rank):
        row = {}
        for v in sorted(free):
            f = cand.features[k].get(v)
            if f is None:
                row[v] = [0] * 2
                continue
            row[v] = [int(round(Fr(x) * Q)) for x in f]
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

def gf_lattice(gamma: Fr, R: Fr, delta: Fr):
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
    af = math.sqrt(float(g)) * float(Rr)
    M = math.exp(0.5 * af * af) / math.sqrt(2 * math.pi)
    half = float(d) / 2

    # tail: 2 M exp(-(T-a)^2/2) <= delta/2, integer search on T
    T = max(1, int(math.ceil(af)) + 1)
    while T < 4096:
        tail = 2.0 * M * math.exp(-0.5 * (T - af) ** 2)
        if tail <= half:
            break
        T += 1
    else:
        raise Declined("no truncation radius below 4096 meets delta")

    # discretization: (2T) h^2 M / 12 <= delta/2  =>  h <= sqrt(6 delta / (2 T M))
    hmax = math.sqrt(max(6.0 * float(d) / (2.0 * T * M), 1e-300))
    bits = max(1, int(math.ceil(-math.log2(min(hmax, 0.5)))))
    bits = min(bits, 40)
    hq = Fr(1, 1 << bits)
    nodes = int(2 * T / float(hq)) + 1
    disc = (2.0 * T) * float(hq) ** 2 * M / 12.0
    return {"T": T, "h": hq, "nodes": nodes,
            "a_shift": Fr(round(af * 10 ** 9), 10 ** 9),
            "M_bound": Fr(round(M * 10 ** 9), 10 ** 9),
            "tail_bound": Fr(round(tail * 10 ** 15) + 1, 10 ** 15),
            "discretization_bound": Fr(round(disc * 10 ** 15) + 1, 10 ** 15),
            "total_bound": Fr(round((tail + disc) * 10 ** 15) + 2, 10 ** 15),
            "derivation": "shifted-Gaussian: phi(z)e^{az}=e^{a^2/2}phi(z-a); "
                          "|F|,|F''| <= M=e^{a^2/2}/sqrt(2pi); trapezoid "
                          "(2T)h^2 M/12; tails 2M exp(-(T-a)^2/2)"}


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
    """Enclose the quadrature weight h * phi(z) with phi the standard normal pdf."""
    import gmpy2
    x = -(z * z) / 2
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        c_lo = gmpy2.mpfr(1) / gmpy2.sqrt(2 * gmpy2.const_pi())
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        c_hi = gmpy2.mpfr(1) / gmpy2.sqrt(2 * gmpy2.const_pi())
    return (h * A.exact_fr(lo) * A.exact_fr(c_lo),
            h * A.exact_fr(hi) * A.exact_fr(c_hi))
