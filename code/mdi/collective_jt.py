"""Collective evaluators on a MARKED model, through calibrated contraction
(spec §7.1 owned-statistic DP, §7.2 Gaussian / Fourier, §7.3 composition).

The law being evaluated is

    W'(z) = b(z) * exp{ (1/2) sum_k s_k gamma_k S_k(z)^2 },   S_k = sum_i f_ki(z_i)

where b is the residual (the marked model's own factors: masses, retained
pair/higher-arity factors, hard zeros) and the fitted modes are the exact
rational (gamma_k, f_ki). The query observable stays g = N/M on the owner.

Three evaluators, one schedule:
  * statistic: every variable's integer statistic k_ki(a) (one per mode) is
    inserted exactly once when it is forgotten; joins convolve; the signed
    exponential is applied ONCE at the root to the total distribution. One
    calibrated pass yields every marker's statistic distribution.
  * gaussian (positive rank-1): exp(+g S^2/2) = E_Z exp(sqrt(g) Z S); each
    node adds a unary tilt enclosed in exact intervals and the residual is
    contracted in the interval algebra. Nodes and tail bound from gf_lattice.
  * fourier (negative rank-1): exp(-g S^2/2) = E_Z exp(i sqrt(g) Z S); each
    node adds a unary complex phase (directed cos/sin enclosures) and the
    residual is contracted in the complex-rectangle algebra; the node's real
    part is accumulated with sign-correct scaling. Nodes from fourier_lattice.

`engine` selects the aggregation implementation: "sparse" (the producer's
sparse_jt) or "dense" (the checker's dense_be). Producer and checker run the
SAME mathematics through DIFFERENT code and different schedules.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import gmpy2
from mdi import arith as A, config as K, collective as CO
from mdi import sparse_jt as SJ, dense_be as DB


class Declined(Exception):
    pass


def _exp_pair(x: Fr, ctx):
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _law_tables(marked, lift):
    """The marked model's law as (scope, dense table) pairs with entries
    lifted into the algebra by `lift(Fr) -> value`."""
    out = []
    for f in marked.law_factors():
        out.append((tuple(f.scope), [lift(Fr(x)) for x in f.table]))
    touched = {v for f in marked.factors for v in f.scope}
    for v in marked.free():
        if v not in touched and not any(x != 1 for x in marked.mass[v]):
            # an isolated variable with unit mass still needs a table
            out.append(((v,), [lift(Fr(1))] * marked.card[v]))
    return out


def _others_products(alg, roots, root_total):
    """For every root, the algebra product of the OTHER roots' totals, by
    prefix/suffix products: 3(n-1) multiplies instead of n(n-1), no division
    (spec §4: exclusion products, never dividing by a message)."""
    n = len(roots)
    one = alg.one()
    pre = [one] * (n + 1)
    for i in range(n):
        pre[i + 1] = alg.mul(pre[i], root_total[roots[i]])
    suf = [one] * (n + 1)
    for i in range(n - 1, -1, -1):
        suf[i] = alg.mul(root_total[roots[i]], suf[i + 1])
    return {roots[i]: alg.mul(pre[i], suf[i + 1]) for i in range(n)}


def _run(tables, card, alg, engine, deadline, stat_insert=None, order=None,
         entry_cap=None, charge=None):
    """One calibrated contraction. Returns (total, marg, ops, peak, others)
    where others[v] is the product of the totals of every component OTHER
    than v's (the algebra one when the model is connected)."""
    if engine == "dense":
        jt = DB.DenseJT(tables, card, alg, deadline=deadline,
                        stat_insert=stat_insert, order=order,
                        entry_cap=entry_cap, charge=charge).run()
        total = jt.total()
        marg = {v: jt.marginal(v) for v in card}
        roots = sorted(jt.root_total)
        oth = _others_products(alg, roots, jt.root_total) if len(roots) > 1 else None
        others = {v: (oth[jt.component_root(v)] if oth else None) for v in card}
        return total, marg, jt.ops, jt.peak_live_entries, others
    # sparse: tables as sparse entries
    stabs = []
    for sc, tab in tables:
        cd = [card[v] for v in sc]
        strides = [1] * len(cd)
        acc = 1
        for k in range(len(cd) - 1, -1, -1):
            strides[k] = acc
            acc *= cd[k]
        ent = {}
        for flat, val in enumerate(tab):
            if alg.is_zero(val):
                continue
            rem = flat
            key = []
            for k in range(len(cd)):
                key.append(rem // strides[k])
                rem %= strides[k]
            ent[tuple(key)] = val
        stabs.append(SJ.Table(sc, ent))
    semi = {"rational": SJ.Rational, "interval": SJ.Interval,
            "complex": SJ.Complex}.get(alg.name)
    if alg.name == "statistic":
        semi = SJ.Statistic(alg.support_cap, rank=alg.rank)
    jt = SJ.SparseJT(stabs, card, semi, deadline=deadline, order=order,
                     entry_cap=entry_cap, charge=charge).run(stat_insert=stat_insert)
    total = jt.total()
    marg = {}
    for v in card:
        m = jt.marginal(v)
        row = [alg.zero] * card[v]
        for a, w in m.entries.items():
            row[a[0]] = w
        marg[v] = row
    roots = sorted(jt.root_total)
    oth = _others_products(alg, roots, jt.root_total) if len(roots) > 1 else None
    others = {v: (oth[jt.component_of(v)] if oth else None) for v in card}
    return total, marg, jt.ops, jt.peak_live_entries, others


# ----------------------------------------------------------- statistic DP

def statistic_evaluate(marked, cand, Q, ctx, engine="sparse", deadline=None,
                       support_cap=None, order=None, charge=None):
    """Owned-statistic DP on the residual (§7.1), all modes, all queries.

    Returns ((Zlo, Zhi), {orig var: [(lo, hi) counts per state]}, meta).
    The counts are relative to Z (not normalized), exact up to the directed
    exponential enclosure applied once at the root.
    """
    rank = cand.rank
    free = marked.free()
    cap = support_cap or K.CAPS["local_mass_entries"]
    kq = CO.round_features(cand, free, Q)
    if rank == 1:
        stat_insert = {v: [kq[0][v][a] for a in range(marked.card[v])]
                       for v in free}
        zero_key = 0
    else:
        stat_insert = {v: [tuple(kq[k][v][a] for k in range(rank))
                           for a in range(marked.card[v])] for v in free}
        zero_key = (0,) * rank
    alg = DB.StatAlg(cap, rank=rank)
    tables = _law_tables(marked, lambda x: ({zero_key: x} if x != 0 else {}))
    total, marg, ops, peak, others = _run(tables, marked.card, alg, engine,
                                          deadline, stat_insert=stat_insert,
                                          order=order, entry_cap=cap,
                                          charge=charge)
    if total is None or not total:
        raise Declined("the residual has zero total weight")

    cache = {}

    def wfac(key):
        if key not in cache:
            ks = key if isinstance(key, tuple) else (key,)
            x = Fr(0)
            for k in range(rank):
                S = Fr(ks[k], Q)
                x += Fr(cand.signs[k]) * cand.gammas[k] * S * S / 2
            cache[key] = _exp_pair(x, ctx)
        return cache[key]

    bitcap = K.CAPS["rational_bit_length"]

    _n = [0]

    def integrate(dist):
        lo = hi = Fr(0)
        for key, w in dist.items():
            _n[0] += 1
            if deadline is not None and (_n[0] & 0x3F) == 0:
                deadline()
            l, h = wfac(key)
            lo += w * l
            hi += w * h
            if (hi.numerator.bit_length() > bitcap
                    or hi.denominator.bit_length() > bitcap):
                raise Declined("the integrated statistic total reached %d bits, "
                               "above the declared %d-bit cap"
                               % (max(hi.numerator.bit_length(),
                                      hi.denominator.bit_length()), bitcap))
        return lo, hi

    Zlo, Zhi = integrate(total)
    if Zlo <= 0:
        raise Declined("nonpositive integrated total")
    # markers: for each owner state c, the statistic distribution of the
    # component containing the owner, times the OTHER components' totals
    counts = {}
    for v in marked.queries():
        o = marked.owner[v]
        rows = []
        for a in range(marked.orig_card[v]):
            lo = hi = Fr(0)
            for c in range(marked.card[o]):
                g = marked.payload(v, a, c)
                if g == 0:
                    continue
                dist = marg[o][c]
                if not dist:
                    continue
                # convolve with the other components' totals so the root
                # exponential sees the TOTAL statistic (cross terms retained)
                full = alg.mul(dist, others[o]) if others[o] is not None else dist
                l, h = integrate(full)
                lo += l * g
                hi += h * g
            rows.append((lo, hi))
        counts[v] = rows
    meta = {"evaluator": "statistic", "engine": engine, "Q": Q,
            "statistic_support": len(total), "ops": ops,
            "peak_live_entries": peak, "rank": rank}
    return (Zlo, Zhi), counts, meta


# ----------------------------------------------------- Gaussian / Fourier

def _features_R(cand, k):
    Rk = Fr(0)
    for f in cand.features[k].values():
        Rk += max(abs(Fr(x)) for x in f)
    return Rk


def gaussian_evaluate(marked, cand, ctx, delta, engine="sparse", deadline=None,
                      cap_nodes=None, order=None, charge=None):
    """Positive rank-1 mode by Gaussian quadrature over tilts (§7.2), the
    residual contracted per node in the exact interval algebra."""
    if cand.rank != 1 or cand.signs[0] <= 0:
        raise Declined("gaussian_evaluate needs a single POSITIVE mode")
    g = cand.gammas[0]
    Rk = _features_R(cand, 0)
    lat = CO.gf_lattice(g, Rk, delta)
    nodes = lat["nodes"]
    if cap_nodes and nodes > cap_nodes:
        raise Declined("gaussian lattice needs %d nodes, cap %d" % (nodes, cap_nodes))
    h, T = lat["h"], lat["T"]
    sg_lo, sg_hi = CO._sqrt_enclose(g, ctx)
    free = marked.free()
    base = _law_tables(marked, lambda x: (x, x))
    alg = DB.IntervalAlg
    Zlo = Zhi = Fr(0)
    counts = {v: [[Fr(0), Fr(0)] for _ in range(marked.orig_card[v])]
              for v in marked.queries()}
    j = -int(Fr(T) / h)
    jmax = int(Fr(T) / h)
    processed = 0
    while j <= jmax:
        if deadline is not None:
            deadline()
        z = Fr(j) * h
        wl, wu = CO._normal_weight(z, h, ctx)
        tilts = []
        for v in free:
            fv = cand.features[0].get(v, [Fr(0)] * marked.card[v])
            row = []
            for a in range(marked.card[v]):
                row.append(CO._exp_enclose(z * Fr(fv[a]), sg_lo, sg_hi, ctx))
            tilts.append(((v,), row))
        total, marg, ops, peak, others = _run(base + tilts, marked.card, alg,
                                              engine, deadline, order=order,
                                              charge=charge)
        if total is None:
            raise Declined("the residual has zero total weight")
        Zlo += wl * total[0]
        Zhi += wu * total[1]
        _accumulate(marked, marg, others, wl, wu, counts, alg)
        processed += 1
        j += 1
    if processed != nodes:
        raise Declined("gaussian lattice processed %d of %d nodes"
                       % (processed, nodes))
    meta = {"evaluator": "gaussian", "engine": engine, "nodes": nodes,
            "T": str(T), "h": str(h), "quadrature_tv": str(lat["total_bound"]),
            "lattice": {k: str(v) for k, v in lat.items() if k != "derivation"}}
    return (Zlo, Zhi), {v: [tuple(r) for r in rows] for v, rows in counts.items()}, meta


def _accumulate(marked, marg, others, wl, wu, counts, alg):
    """Add one node's marker contributions. For a disconnected residual the
    owner's marginal is per component, so it is multiplied by the product of
    the OTHER components' totals (precomputed once per node by prefix/suffix
    products in `_run`)."""
    for v in marked.queries():
        o = marked.owner[v]
        oth = others.get(o)
        for a in range(marked.orig_card[v]):
            acc = alg.zero
            for c in range(marked.card[o]):
                g = marked.payload(v, a, c)
                if g == 0:
                    continue
                val = marg[o][c]
                if alg.is_zero(val):
                    continue
                if oth is not None:
                    val = alg.mul(val, oth)
                if g != 1:
                    val = alg.mul(val, _scalar(alg, g))
                acc = alg.add(acc, val)
            if alg.name == "interval":
                counts[v][a][0] += wl * acc[0]
                counts[v][a][1] += wu * acc[1]
            else:
                lo, hi = CO._scale_interval(acc[0], acc[1], wl, wu)
                counts[v][a][0] += lo
                counts[v][a][1] += hi


def _scalar(alg, g):
    if alg.name == "interval":
        return (g, g)
    return (g, g, Fr(0), Fr(0))


def fourier_evaluate(marked, cand, ctx, delta, engine="sparse", deadline=None,
                     cap_nodes=None, order=None, charge=None):
    """Negative rank-1 mode by the complex-phase identity (§7.2), the residual
    contracted per node in the complex-rectangle algebra; the real part is
    accumulated with sign-correct scaling, the imaginary part is a witness."""
    if cand.rank != 1 or cand.signs[0] >= 0:
        raise Declined("fourier_evaluate needs a single NEGATIVE mode")
    g = cand.gammas[0]
    Rk = _features_R(cand, 0)
    lat = CO.fourier_lattice(g, Rk, delta)
    nodes = lat["nodes"]
    if cap_nodes and nodes > cap_nodes:
        raise Declined("fourier lattice needs %d nodes, cap %d" % (nodes, cap_nodes))
    h, T = lat["h"], lat["T"]
    sg_lo, sg_hi = CO._sqrt_enclose(g, ctx)
    free = marked.free()
    base = _law_tables(marked, lambda x: (x, x, Fr(0), Fr(0)))
    alg = DB.ComplexAlg
    Zlo = Zhi = Fr(0)
    Imlo = Imhi = Fr(0)
    counts = {v: [[Fr(0), Fr(0)] for _ in range(marked.orig_card[v])]
              for v in marked.queries()}
    j = -int(Fr(T) / h)
    jmax = int(Fr(T) / h)
    processed = 0
    while j <= jmax:
        if deadline is not None:
            deadline()
        z = Fr(j) * h
        wl, wu = CO._normal_weight(z, h, ctx)
        phases = []
        for v in free:
            fv = cand.features[0].get(v, [Fr(0)] * marked.card[v])
            row = []
            for a in range(marked.card[v]):
                t = z * Fr(fv[a])
                alo = (sg_lo if t >= 0 else sg_hi) * t
                ahi = (sg_hi if t >= 0 else sg_lo) * t
                clo, chi = CO._cos_enclose(alo, ahi, ctx)
                slo, shi = CO._sin_enclose(alo, ahi, ctx)
                row.append((clo, chi, slo, shi))
            phases.append(((v,), row))
        total, marg, ops, peak, others = _run(base + phases, marked.card, alg,
                                              engine, deadline, order=order,
                                              charge=charge)
        if total is None:
            raise Declined("the residual has zero total weight")
        lo, hi = CO._scale_interval(total[0], total[1], wl, wu)
        Zlo += lo
        Zhi += hi
        ilo, ihi = CO._scale_interval(total[2], total[3], wl, wu)
        Imlo += ilo
        Imhi += ihi
        _accumulate(marked, marg, others, wl, wu, counts, alg)
        processed += 1
        j += 1
    if processed != nodes:
        raise Declined("fourier lattice processed %d of %d nodes"
                       % (processed, nodes))
    # certified truncation + discretization error, on the NORMALIZED average,
    # scaled by the total residual mass (bounds the modulus of the integrand)
    qerr = Fr(lat["total_bound"])
    mass = _residual_mass_upper(marked, engine, deadline, order)
    wid = qerr * mass
    Zlo -= wid
    Zhi += wid
    for v in counts:
        for row in counts[v]:
            row[0] -= wid
            row[1] += wid
    if Imlo > wid or Imhi < -wid:
        raise Declined("the accumulated imaginary part [%s, %s] excludes zero "
                       "beyond the lattice allowance" % (Imlo, Imhi))
    meta = {"evaluator": "fourier", "engine": engine, "nodes": nodes,
            "T": str(T), "h": str(h), "quadrature_tv": str(lat["total_bound"]),
            "imaginary_enclosure": (str(Imlo), str(Imhi)),
            "negative_exponent_Ymax": str(CO.negative_response_bound(cand)),
            "lattice": {k: str(v) for k, v in lat.items() if k != "derivation"}}
    return (Zlo, Zhi), {v: [tuple(r) for r in rows] for v, rows in counts.items()}, meta


def _residual_mass_upper(marked, engine, deadline, order):
    """The residual's total mass sum_z b(z), an upper bound on the modulus of
    every node's complex contraction (unit-modulus phases)."""
    tables = _law_tables(marked, lambda x: x)
    tot, _m, _o, _p, _oth = _run(tables, marked.card, DB.RationalAlg, engine,
                                 deadline, order=order)
    if tot is None:
        raise Declined("the residual has zero total mass")
    return Fr(tot)


# --------------------------------------------------------------- dispatch

def evaluate(marked, coll, ctx, engine="sparse", deadline=None, order=None,
             charge=None):
    """Run the evaluator named by a parsed collective record on the marked
    residual. Returns ((Zlo, Zhi), counts, meta)."""
    cand = coll["candidate"]
    ev = coll["evaluator"]
    if ev == "statistic":
        return statistic_evaluate(marked, cand, coll["Q"], ctx, engine=engine,
                                  deadline=deadline, order=order, charge=charge)
    if ev == "gaussian":
        return gaussian_evaluate(marked, cand, ctx, coll["delta"], engine=engine,
                                 deadline=deadline, order=order, charge=charge)
    if ev == "fourier":
        return fourier_evaluate(marked, cand, ctx, coll["delta"], engine=engine,
                                deadline=deadline, order=order, charge=charge)
    raise Declined("unknown evaluator %r" % ev)
