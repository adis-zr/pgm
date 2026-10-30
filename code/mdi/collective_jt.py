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
from mdi import sparse_jt as SJ, dense_be as DB, factors as FX


class Declined(Exception):
    pass


def _exp_pair(x: Fr, ctx):
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    return A.exact_fr(lo), A.exact_fr(hi)


def _law_tables(marked, lift):
    """The marked model's law as (scope, table) pairs with entries lifted into
    the algebra by `lift(Fr) -> value`. A projected view stays a view: its
    table is a LazyTable with the lift applied on read."""
    out = []
    for f in marked.law_factors():
        if FX.is_view(f):
            out.append((tuple(f.scope),
                        FX.LazyTable(f.card, [f.offsets[v] for v in f.scope],
                                     f.base.table, lift=lambda x, _l=lift: _l(Fr(x)))))
        else:
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
    cap = K.CAPS["rational_bit_length"]
    chk = getattr(alg, "check", None) or getattr(alg, "check_bits", None)
    pre = [one] * (n + 1)
    for i in range(n):
        pre[i + 1] = alg.mul(pre[i], root_total[roots[i]])
        if chk is not None:
            chk(pre[i + 1], cap)          # operand bit bound at every boundary
    suf = [one] * (n + 1)
    for i in range(n - 1, -1, -1):
        suf[i] = alg.mul(root_total[roots[i]], suf[i + 1])
        if chk is not None:
            chk(suf[i], cap)
    out = {}
    for i in range(n):
        out[roots[i]] = alg.mul(pre[i], suf[i + 1])
        if chk is not None:
            chk(out[roots[i]], cap)
    return out


def _run(tables, card, alg, engine, deadline, stat_insert=None, order=None,
         entry_cap=None, charge=None, only=None, cache=None):
    """One calibrated contraction. Returns (total, marg, ops, peak, others)
    where others[v] is the product of the totals of every component OTHER
    than v's (the algebra one when the model is connected). `cache` (a dict)
    lets successive calls with identical scopes REUSE the built engine."""
    owners = set(only) if only is not None else set(card)
    if engine == "dense":
        key = ("dense", alg.name, tuple(tuple(sc) for sc, _t in tables))
        jt = cache.get(key) if cache is not None else None
        if jt is not None:
            jt.rebind(tables).run()
        else:
            jt = DB.DenseJT(tables, card, alg, deadline=deadline,
                            stat_insert=stat_insert, order=order,
                            entry_cap=entry_cap, charge=charge).run()
            if cache is not None:
                cache[key] = jt
        total = jt.total()
        marg = {v: jt.marginal(v) for v in card if v in owners}
        roots = sorted(jt.root_total)
        oth = _others_products(alg, roots, jt.root_total) if len(roots) > 1 else None
        others = {v: (oth[jt.component_root(v)] if oth else None) for v in card}
        return total, marg, jt.ops, jt.peak_live_entries, others
    # sparse: dense lists become sparse entries; lazy tables stay compact
    stabs = []
    for sc, tab in tables:
        cd = [card[v] for v in sc]
        if isinstance(tab, FX.LazyTable):
            stabs.append(SJ.Lazy(sc, cd, tab.at_digits))
            continue
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
    key = ("sparse", alg.name, tuple(tuple(sc) for sc, _t in tables))
    jt = cache.get(key) if cache is not None else None
    if jt is not None:
        jt.rebind(stabs).run(stat_insert=stat_insert)
    else:
        jt = SJ.SparseJT(stabs, card, semi, deadline=deadline, order=order,
                         entry_cap=entry_cap, charge=charge).run(stat_insert=stat_insert)
        if cache is not None:
            cache[key] = jt
    total = jt.total()
    marg = {}
    for v in card:
        if v not in owners:
            continue
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
                                          charge=charge,
                                          only=set(marked.owner.values()))
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


def _scalar(alg, g):
    if alg.name == "interval":
        return (g, g)
    return (g, g, Fr(0), Fr(0))


def _own_mass_contribution(marked, marg, others, alg):
    """Per requested (variable, state): the algebra sum over the owner's cells
    of count(c) x payload g(c), with the other components' totals multiplied
    in (prefix/suffix products, no division)."""
    out = {}
    for v in marked.queries():
        o = marked.owner[v]
        oth = others.get(o)
        rows = []
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
            rows.append(acc)
        out[v] = rows
    return out


def _tensor_error(deltas):
    """sum_k delta_k prod_{j != k} (1 + delta_j): the product-rule error of a
    tensor of 1-D lattices whose integrand is bounded by 1 (phases) or whose
    relative errors compound (positive tilts, each >= 1)."""
    out = Fr(0)
    for i, d in enumerate(deltas):
        prod = Fr(1)
        for j, d2 in enumerate(deltas):
            if j != i:
                prod *= (1 + d2)
        out += d * prod
    return out


def _lattice_points(lat):
    h, T = lat["h"], lat["T"]
    jmax = int(Fr(T) / h)
    return [Fr(j) * h for j in range(-jmax, jmax + 1)]


def gf_evaluate(marked, cand, ctx, deltas, engine="sparse", deadline=None,
                order=None, charge=None, num_eps=None, stop_early=True,
                progress=None, only_nodes=None):
    """§7.2 complete: positive Gaussian coordinates and negative Fourier
    coordinates together, on the residual of a Marked model.

        exp(sum_k s_k g_k S_k^2 / 2)
          = E_{Z+} exp(sum_{k+} sqrt(g_k) Z_k S_k) . E_{Z-} exp(i sum_{k-} sqrt(g_k) Z_k S_k)

    Positive grid: the tensor of the positive modes' GF lattices; at each
    positive node the per-variable REAL tilt is enclosed, and the FULL
    POSITIVE MARKER-MASS PASS contracts the residual (interval algebra) to the
    positive mass m+ of every requested event -- charged work, not pruning.
    These masses rank the positive nodes.

    Negative grid: for a positive node being processed, the tensor of the
    negative modes' oscillatory lattices; each negative node adds a unary
    complex PHASE, the residual (with the positive tilt) is contracted in the
    complex-rectangle algebra, and the node's real part is accumulated with
    sign-correct scaling. Conjugate pairing: node -z is the conjugate of node
    +z, so each pair is evaluated once and its real part doubled.

    Sharp marker-ratio stopping: with tensor Fourier error delta on the
    normalized average, a processed positive node's count for an event lies in
    [max(0, a- - delta m+), min(m+, a+ + delta m+)]; an UNPROCESSED positive
    node contributes [0, w m+]. Event X and complement C are accumulated and
    P in [x_l/(x_l + c_u), x_u/(x_u + c_l)]. Positive nodes are processed in
    decreasing mass order and processing stops when every requested output
    meets `num_eps`. Omitted nodes are recorded.

    Pure Gaussian (no negative mode) and pure Fourier (no positive mode) are
    the two special cases: no Fourier pass, respectively a single positive
    node with the identity tilt.

    Returns ((Zlo, Zhi), counts, meta) where counts[v][a] = (X_l, X_u) and the
    caller forms the ratio; for a pure Gaussian the counts are the positive
    masses and Z their total, and the positive-mode GF3 TV radius is charged
    by the caller as a probability radius.
    """
    rank = cand.rank
    pos = [k for k in range(rank) if cand.signs[k] > 0]
    neg = [k for k in range(rank) if cand.signs[k] < 0]
    free = marked.free()
    lats = {}
    for k in range(rank):
        Rk = _features_R(cand, k)
        lats[k] = (CO.gf_lattice(cand.gammas[k], Rk, Fr(deltas[k])) if cand.signs[k] > 0
                   else CO.fourier_lattice(cand.gammas[k], Rk, Fr(deltas[k])))
    sg = {k: CO._sqrt_enclose(cand.gammas[k], ctx) for k in range(rank)}
    base_int = _law_tables(marked, lambda x: (x, x))
    base_cx = _law_tables(marked, lambda x: (x, x, Fr(0), Fr(0)))
    queries = marked.queries()
    nst = {v: marked.orig_card[v] for v in queries}

    # ---- the positive grid and the FULL positive marker-mass pass
    import itertools
    _cache = {}
    pos_pts = [_lattice_points(lats[k]) for k in pos]
    pos_nodes = list(itertools.product(*pos_pts)) if pos else [()]
    mass = []        # per positive node: (weight (wl, wu), tilt rows, m+ per event, m+ total)
    processed_pos = 0
    for node in pos_nodes:
        if deadline is not None:
            deadline()
        wl = wu = Fr(1)
        for k, z in zip(pos, node):
            a, b = CO._normal_weight(z, lats[k]["h"], ctx)
            wl *= a
            wu *= b
        tilts = []
        for v in free:
            row = []
            for a in range(marked.card[v]):
                lo = hi = Fr(1)
                for k, z in zip(pos, node):
                    fv = Fr(cand.features[k].get(v, [Fr(0)] * marked.card[v])[a])
                    l, h = CO._exp_enclose(z * fv, sg[k][0], sg[k][1], ctx)
                    lo *= l
                    hi *= h
                row.append((lo, hi))
            tilts.append(((v,), row))
        total, marg, ops, peak, others = _run(base_int + tilts, marked.card,
                                              DB.IntervalAlg, engine, deadline,
                                              order=order, charge=charge,
                                              only=set(marked.owner.values()),
                                              cache=_cache)
        if total is None:
            raise Declined("the residual has zero total weight at a positive node")
        mplus = _own_mass_contribution(marked, marg, others, DB.IntervalAlg)
        mass.append(((wl, wu), tilts, mplus, total))
        processed_pos += 1
        if progress is not None and (processed_pos & 0x3F) == 0:
            progress("positive-mass", "%d/%d nodes" % (processed_pos, len(pos_nodes)))
    meta = {"evaluator": ("gaussian" if not neg else "fourier" if not pos else "mixed"),
            "engine": engine, "positive_nodes": len(pos_nodes),
            "negative_nodes_per_positive": 1,
            "lattices": {k: {kk: str(vv) for kk, vv in lats[k].items() if kk != "derivation"}
                         for k in range(rank)}}
    if only_nodes is None:
        omitted = 0
    if not neg:
        # pure Gaussian: the counts ARE the positive masses, weighted
        Zlo = Zhi = Fr(0)
        counts = {v: [[Fr(0), Fr(0)] for _ in range(nst[v])] for v in queries}
        for (wl, wu), _t, mplus, total in mass:
            Zlo += wl * total[0]
            Zhi += wu * total[1]
            for v in queries:
                for a in range(nst[v]):
                    counts[v][a][0] += wl * mplus[v][a][0]
                    counts[v][a][1] += wu * mplus[v][a][1]
        meta["quadrature_tv"] = str(_tensor_error([Fr(lats[k]["total_bound"]) for k in pos]))
        return (Zlo, Zhi), {v: [tuple(r) for r in rows] for v, rows in counts.items()}, meta

    # ---- the negative grid: tensor Fourier error on the normalized average
    neg_pts = [_lattice_points(lats[k]) for k in neg]
    neg_nodes = list(itertools.product(*neg_pts))
    meta["negative_nodes_per_positive"] = len(neg_nodes)
    # TENSOR ERROR LEMMA (finite Gaussian-grid product rule). Each negative
    # coordinate's lattice replaces its own expectation by a weighted sum whose
    # error on a unit-modulus integrand is at most delta_k, and whose weights
    # sum to at most 1 + delta_k. Applying the coordinates in turn,
    #   |E[prod] - sum prod| <= sum_k delta_k * prod_{j != k} (1 + delta_j).
    # The checker (program_check.own_gf_reference) evaluates the same lemma.
    dl = [Fr(lats[k]["total_bound"]) for k in neg]
    delta = Fr(0)
    for i, d in enumerate(dl):
        prod = Fr(1)
        for j, d2 in enumerate(dl):
            if j != i:
                prod *= (1 + d2)
        delta += d * prod
    # conjugate pairs: node z and -z (componentwise) have conjugate
    # contributions. The key set is built ONCE and checked symmetric with
    # linear work (charged below), then paired.
    keyset = set(neg_nodes)
    if charge is not None:
        charge(len(neg_nodes))
    symmetric = True
    for nd in neg_nodes:
        if tuple(-z for z in nd) not in keyset:
            symmetric = False
            break
    if not symmetric:
        raise Declined("the negative frequency key set is not symmetric; conjugate "
                       "pairing is impossible")
    pairs = []
    seen = set()
    for nd in neg_nodes:
        key = tuple(nd)
        if key in seen:
            continue
        conj = tuple(-z for z in nd)
        seen.add(key)
        seen.add(conj)
        pairs.append((nd, conj != key))
    meta["conjugate_pairs"] = len(pairs)
    meta["negative_key_set_symmetric"] = True
    # rank the positive nodes by their total positive mass (upper), largest first
    order_idx = sorted(range(len(mass)), key=lambda i: -(mass[i][0][1] * mass[i][3][1]))
    # accumulators per event: processed X interval, unprocessed allowance [0, w m+]
    X_done = {v: [[Fr(0), Fr(0)] for _ in range(nst[v])] for v in queries}
    X_todo = {v: [Fr(0)] * nst[v] for v in queries}
    for (wl, wu), _t, mplus, _tot in mass:
        for v in queries:
            for a in range(nst[v]):
                X_todo[v][a] += wu * mplus[v][a][1]
    Zlo = Zhi = Fr(0)
    Imlo = Imhi = Fr(0)
    processed = 0
    omitted = 0

    def current_rows():
        rows = {}
        worst = Fr(0)
        for v in queries:
            xs = []
            for a in range(nst[v]):
                xl = X_done[v][a][0]
                xu = X_done[v][a][1] + X_todo[v][a]
                xs.append((xl, xu))
            tl = sum(x[0] for x in xs)
            th = sum(x[1] for x in xs)
            rr = []
            for a, (xl, xu) in enumerate(xs):
                cl, cu = tl - xl, th - xu
                dl, du = xl + cu, xu + cl
                lo = xl / dl if dl > 0 else Fr(0)
                hi = xu / du if du > 0 else Fr(1)
                lo, hi = max(Fr(0), lo), min(Fr(1), hi)
                rr.append((lo, hi))
                worst = max(worst, hi - lo)
            rows[v] = rr
        return rows, worst

    # per NEGATIVE node: the per-variable phase rectangles depend on the
    # negative coordinates only, so they are enclosed ONCE here and reused at
    # every positive node (the tilt is multiplied in per pair)
    phase_rows = []
    for nd, has_conj in pairs:
        if deadline is not None:
            deadline()
        nwl = nwu = Fr(1)
        for k, z in zip(neg, nd):
            a, b = CO._normal_weight(z, lats[k]["h"], ctx)
            nwl *= a
            nwu *= b
        per_v = {}
        for v in free:
            row = []
            for a in range(marked.card[v]):
                alo = ahi = Fr(0)
                for k, z in zip(neg, nd):
                    fv = Fr(cand.features[k].get(v, [Fr(0)] * marked.card[v])[a])
                    t = z * fv
                    alo += (sg[k][0] if t >= 0 else sg[k][1]) * t
                    ahi += (sg[k][1] if t >= 0 else sg[k][0]) * t
                clo, chi = CO._cos_enclose(alo, ahi, ctx)
                slo, shi = CO._sin_enclose(alo, ahi, ctx)
                row.append((clo, chi, slo, shi))
            per_v[v] = row
        phase_rows.append((nwl, nwu, per_v, has_conj))
    owners = set(marked.owner.values())
    if only_nodes is not None:
        # RECHECK exactly the producer's retained positive nodes (§11): the
        # omitted ones keep their [0, w m+] allowance; nothing is integrated
        # to rescue the record
        want = set(int(i) for i in only_nodes)
        bad = [i for i in want if not (0 <= i < len(mass))]
        if bad:
            raise Declined("retained positive node indices %s are outside the "
                           "grid of %d nodes" % (bad[:4], len(mass)))
        order_idx = [i for i in order_idx if i in want]
        stop_early = False
    for i in order_idx:
        (wl, wu), tilts, mplus, total = mass[i]
        if stop_early and num_eps is not None and processed > 0:
            _rows, worst = current_rows()
            if worst <= Fr(num_eps):
                omitted = len(mass) - processed
                break
        # the Fourier integral at this positive node: complex phases on top of
        # the positive tilt, summed over conjugate pairs
        acc_tot = (Fr(0), Fr(0), Fr(0), Fr(0))
        acc_ev = {v: [(Fr(0), Fr(0), Fr(0), Fr(0)) for _ in range(nst[v])] for v in queries}
        for nwl, nwu, per_v, has_conj in phase_rows:
            if deadline is not None:
                deadline()
            phases = []
            for (v,), trow in tilts:
                prow = per_v[v]
                row = []
                for a in range(marked.card[v]):
                    tl, th = trow[a]
                    clo, chi, slo, shi = prow[a]
                    # nonnegative tilt interval times the phase rectangle
                    re = (min(tl * clo, th * clo, tl * chi, th * chi),
                          max(tl * clo, th * clo, tl * chi, th * chi))
                    im = (min(tl * slo, th * slo, tl * shi, th * shi),
                          max(tl * slo, th * slo, tl * shi, th * shi))
                    row.append((re[0], re[1], im[0], im[1]))
                phases.append(((v,), row))
            ctot, cmarg, ops, peak, cothers = _run(base_cx + phases, marked.card,
                                                   DB.ComplexAlg, engine, deadline,
                                                   order=order, charge=charge,
                                                   only=owners, cache=_cache)
            if ctot is None:
                raise Declined("the residual has zero total weight at a node")
            cev = _own_mass_contribution(marked, cmarg, cothers, DB.ComplexAlg)
            mult = 2 if has_conj else 1

            def wscale(rect):
                lo, hi = CO._scale_interval(rect[0], rect[1], nwl * mult, nwu * mult)
                if has_conj:
                    ilo, ihi = Fr(0), Fr(0)       # the pair's imaginary parts cancel
                else:
                    ilo, ihi = CO._scale_interval(rect[2], rect[3], nwl, nwu)
                return (lo, hi, ilo, ihi)
            acc_tot = DB.ComplexAlg.add(acc_tot, wscale(ctot))
            for v in queries:
                for a in range(nst[v]):
                    acc_ev[v][a] = DB.ComplexAlg.add(acc_ev[v][a], wscale(cev[v][a]))
        # the Fourier error is delta times the positive mass; clip to [0, m+]
        for v in queries:
            for a in range(nst[v]):
                mlo, mhi = mplus[v][a]
                alo, ahi = acc_ev[v][a][0], acc_ev[v][a][1]
                xl = max(Fr(0), alo - delta * mhi)
                xu = min(mhi, ahi + delta * mhi)
                if xl > xu:
                    xl, xu = Fr(0), mhi
                X_done[v][a][0] += wl * xl
                X_done[v][a][1] += wu * xu
                X_todo[v][a] -= wu * mhi
        tlo = max(Fr(0), acc_tot[0] - delta * total[1])
        thi = min(total[1], acc_tot[1] + delta * total[1])
        Zlo += wl * tlo
        Zhi += wu * thi
        Imlo += acc_tot[2]
        Imhi += acc_tot[3]
        processed += 1
        if progress is not None and (processed & 0x7) == 0:
            progress("fourier", "%d/%d positive nodes" % (processed, len(mass)))
    else:
        omitted = 0
    rows, worst = current_rows()
    # a conjugate pair's imaginary parts cancel exactly; any unpaired (self-
    # conjugate, i.e. zero) node is real by construction up to its enclosure
    if Imlo > delta * sum(m[3][1] for m in mass) or Imhi < -delta * sum(m[3][1] for m in mass):
        raise Declined("the accumulated imaginary part [%s, %s] excludes zero beyond "
                       "the lattice allowance" % (Imlo, Imhi))
    counts = {}
    for v in queries:
        counts[v] = [(X_done[v][a][0], X_done[v][a][1] + X_todo[v][a]) for a in range(nst[v])]
    for i in range(processed, len(mass)):
        pass
    # unprocessed positive nodes contribute [0, w m+] to Z as well
    for i in order_idx[processed:]:
        (wl, wu), _t, _m, total = mass[i]
        Zhi += wu * total[1]
    meta.update({"processed_positive_nodes": processed, "omitted_positive_nodes": omitted,
                 "retained_positive_node_indices": order_idx[:processed],
                 "fourier_delta": str(delta), "worst_width_after_ratio": str(worst),
                 "imaginary_enclosure": (str(Imlo), str(Imhi)),
                 "negative_exponent_Ymax": str(sum((cand.gammas[k] * _features_R(cand, k) ** 2 / 2
                                                    for k in neg), Fr(0))),
                 "quadrature_tv": str(_tensor_error([Fr(lats[k]["total_bound"]) for k in pos])),
                 "ratio_rows": {str(v): [[str(a), str(b)] for a, b in rows[v]] for v in rows}})
    return (Zlo, Zhi), counts, meta


def gaussian_evaluate(marked, cand, ctx, delta, engine="sparse", deadline=None,
                      cap_nodes=None, order=None, charge=None):
    if cand.rank != 1 or cand.signs[0] <= 0:
        raise Declined("gaussian_evaluate needs a single POSITIVE mode")
    return gf_evaluate(marked, cand, ctx, [delta], engine=engine, deadline=deadline,
                       order=order, charge=charge)


def fourier_evaluate(marked, cand, ctx, delta, engine="sparse", deadline=None,
                     cap_nodes=None, order=None, charge=None, num_eps=None):
    if cand.rank != 1 or cand.signs[0] >= 0:
        raise Declined("fourier_evaluate needs a single NEGATIVE mode")
    return gf_evaluate(marked, cand, ctx, [delta], engine=engine, deadline=deadline,
                       order=order, charge=charge, num_eps=num_eps)


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
             charge=None, num_eps=None, stop_early=True, only_nodes=None):
    """Run the evaluator named by a parsed collective record on the marked
    residual. Returns ((Zlo, Zhi), counts, meta)."""
    cand = coll["candidate"]
    ev = coll["evaluator"]
    if ev == "statistic":
        return statistic_evaluate(marked, cand, coll["Q"], ctx, engine=engine,
                                  deadline=deadline, order=order, charge=charge)
    if ev in ("gaussian", "fourier", "mixed"):
        deltas = coll.get("deltas") or [coll["delta"]]
        return gf_evaluate(marked, cand, ctx, [Fr(d) for d in deltas], engine=engine,
                           deadline=deadline, order=order, charge=charge,
                           num_eps=num_eps, stop_early=stop_early,
                           only_nodes=only_nodes)
    raise Declined("unknown evaluator %r" % ev)
