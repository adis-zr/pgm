"""Independent checkers for the collective routes (contract §H).

Each checker rebuilds the quantity from the ORIGINAL inputs with its own code
and requires the publication to CONTAIN its enclosure. It shares the validated
structural data and the arithmetic primitives the specification permits, but
never the producer's aggregation or readout.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import itertools
from mdi import arith as A, config as K, collective as CO, modes as MD


class CollectiveCheckError(ValueError):
    pass


def _enclose_weight(unary, card, free, combo, cand, Q, ctx):
    """One configuration's weight under the represented law, as an enclosure.

    Deliberately independent of the DP: it evaluates the product and the signed
    exponential directly for a single configuration.
    """
    import gmpy2
    w = Fr(1)
    stat = 0
    for k, v in enumerate(sorted(free)):
        a = combo[k]
        uw = Fr(unary[v][a])
        if uw == 0:
            return Fr(0), Fr(0)
        w *= uw
        fv = Fr(cand.features[0].get(v, [Fr(0)] * card[v])[a])
        stat += int(round(float(fv) * Q))
    S = Fr(stat, Q)
    x = Fr(cand.signs[0]) * cand.gammas[0] * S * S / 2
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    return w * A.exact_fr(lo), w * A.exact_fr(hi)


def check_statistic_publication(free, card, unary, cand, Q, queries, published,
                                eps, ctx, radius=Fr(0), cap_configs=None):
    """Independent check of a statistic-DP publication.

    Enumerates configurations directly, which is a DIFFERENT implementation from
    the DP's statistic convolution. Bounded: it refuses rather than running away.
    """
    cap = cap_configs or K.CAPS["region_tuple_assignments"]
    total = 1
    for v in sorted(free):
        total *= card[v]
    if total > cap:
        raise CollectiveCheckError(
            "independent enumeration needs %d configurations, above the %d cap; "
            "this is a RESOURCE refusal, not a verification" % (total, cap))
    Zlo = Zhi = Fr(0)
    mk = {(v, a): [Fr(0), Fr(0)] for v in sorted(free) if v in queries
          for a in range(card[v])}
    order = sorted(free)
    for combo in itertools.product(*[range(card[v]) for v in order]):
        lo, hi = _enclose_weight(unary, card, free, combo, cand, Q, ctx)
        if hi == 0:
            continue
        Zlo += lo
        Zhi += hi
        for k, v in enumerate(order):
            if v not in queries:
                continue
            mk[(v, combo[k])][0] += lo
            mk[(v, combo[k])][1] += hi
    if Zhi <= 0:
        raise CollectiveCheckError("independent total is nonpositive")
    fails = []
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        if len(rows) != card[v]:
            fails.append("variable %d publishes %d states, model has %d"
                         % (v, len(rows), card[v]))
            continue
        for a in range(card[v]):
            lo, hi = Fr(rows[a][0]), Fr(rows[a][1])
            if lo > hi or lo < 0 or hi > 1:
                fails.append("variable %d state %d: invalid endpoints" % (v, a))
                continue
            mlo, mhi = mk[(v, a)]
            clo = max(Fr(0), mlo / Zhi - radius)
            chi = min(Fr(1), mhi / Zlo + radius)
            if not (lo <= clo and chi <= hi):
                fails.append("variable %d state %d: publication [%s, %s] does "
                             "NOT contain the independent enclosure [%s, %s]"
                             % (v, a, lo, hi, clo, chi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: width exceeds eps" % (v, a))
    return (not fails), fails, {"configurations": total,
                                "independent_enclosure": True,
                                "method": "direct configuration enumeration, "
                                          "independent of the statistic "
                                          "convolution"}


def check_quadrature_publication(free, card, unary, cand, queries, published,
                                 eps, ctx, delta, radius=Fr(0),
                                 cap_configs=None):
    """Independent check of a Gaussian or Fourier publication.

    Does NOT redo the quadrature. It evaluates the represented law directly,
    which is what the quadrature identity is supposed to compute, and requires
    containment after the quadrature radius is charged.
    """
    ok, fails, meta = check_statistic_publication(
        free, card, unary, cand, 1, queries, published, eps, ctx,
        radius=radius + CO.gf_lattice(cand.gammas[0],
                                      sum(max(abs(Fr(x)) for x in f)
                                          for f in cand.features[0].values()),
                                      delta)["total_bound"],
        cap_configs=cap_configs)
    meta["method"] = ("direct evaluation of the represented law; the quadrature "
                      "identity is not re-run, and its certified radius is "
                      "charged into the enclosure")
    return ok, fails, meta


def check_composed_publication(restricted, regions, coarse, rds, queries,
                               published, eps, total_radius,
                               regional_radius=None):
    """Independent check of a composed publication.

    Reuses the regional checker's independent reduced contraction, then requires
    the publication to contain the checker's own enclosure. It never solves the
    uncoarsened original model.

    The checker's enclosure is the exact coarse value widened by the radii the
    checker can itself justify: the REGIONAL radius, which bounds coarse against
    original. It must NOT additionally widen by the producer's collective-fit
    radius, because the checker did not run the collective evaluator and that
    radius bounds the producer's value against the exact coarse value the
    checker computed directly. Widening by the full producer total demanded
    containment of a strictly wider interval than the publication charges, which
    rejected correct publications.
    """
    from mdi import regional_check as RC
    Z, counts = RC.independent_contract(restricted, regions, coarse, rds,
                                        queries)
    if Z <= 0:
        raise CollectiveCheckError("independent reduced total is nonpositive")
    fails = []
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        for s in range(len(rows)):
            lo, hi = Fr(rows[s][0]), Fr(rows[s][1])
            q = counts.get((v, s), Fr(0)) / Z
            # the radius the CHECKER can justify from its own computation
            own = Fr(regional_radius) if regional_radius is not None \
                else Fr(total_radius)
            clo = max(Fr(0), q - own)
            chi = min(Fr(1), q + own)
            if not (lo <= clo and chi <= hi):
                fails.append("variable %d state %d: publication [%s, %s] does "
                             "NOT contain [%s, %s]" % (v, s, lo, hi, clo, chi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: width exceeds eps" % (v, s))
    return (not fails), fails, {
        "independent_enclosure": True,
        "checker_radius": str(Fr(regional_radius)
                              if regional_radius is not None
                              else Fr(total_radius)),
        "producer_total_radius": str(Fr(total_radius)),
        "method": "independent reduced-model contraction widened by the radius "
                  "the checker can itself justify; the producer's collective-fit "
                  "radius is NOT re-applied, since the checker computed the "
                  "exact coarse value directly"}
