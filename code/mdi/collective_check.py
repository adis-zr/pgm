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


def _exact_quantize(fv: Fr, Q: int) -> Fr:
    """Exact rational quantization, round-half-UP, matching the producer.

    `round(float(fv) * Q)` was used here. Binary64 is not a permissible
    replacement for the declared exact semantics: for fv = 1/2 + 2^-54 and Q = 1
    the float path rounds the input to 0.5 and then banker's-rounds to 0, while
    the exact declared quantization is 1. The checker then verified a different
    law from the producer's, and accepted a publication near 1/2 for a quantized
    law whose true state-1 probability is about 0.6224593312018546.
    """
    if Q is None:
        raise CollectiveCheckError("quantization requires an explicit Q")
    scaled = fv * Q
    fl = scaled.numerator // scaled.denominator
    frac = scaled - fl
    return Fr(fl + 1 if frac >= Fr(1, 2) else fl, Q)


def _enclose_weight(unary, card, free, combo, cand, Q, ctx):
    """One configuration's weight under the law the checker CLAIMS to verify.

    `Q=None` means evaluate the ORIGINAL unrounded rational features, which is
    what the Gaussian/Fourier collective identity represents. An integer `Q`
    means reproduce the declared exact quantized law. Passing Q=1 to check an
    unrounded law silently replaced the law: features [0, 1/4] quantize to
    [0, 0], so the checker enclosed a law with both weights equal to 1 and a
    state probability of exactly 1/2, against a true 0.5078118642792046.

    EVERY signed mode is included. Only mode 0 was read before, so a rank > 1
    candidate had its remaining modes silently dropped.
    """
    import gmpy2
    w = Fr(1)
    if cand.rank != len(cand.signs) or cand.rank != len(cand.gammas) \
            or cand.rank != len(cand.features):
        raise CollectiveCheckError(
            "candidate rank %s disagrees with %d signs / %d gammas / %d feature "
            "maps; the checker will not guess which modes the law contains"
            % (cand.rank, len(cand.signs), len(cand.gammas),
               len(cand.features)))
    for k, v in enumerate(sorted(free)):
        a = combo[k]
        uw = Fr(unary[v][a])
        if uw == 0:
            return Fr(0), Fr(0)
        w *= uw
    # the signed exponent, summed over all modes
    x = Fr(0)
    for mi in range(cand.rank):
        S = Fr(0)
        for k, v in enumerate(sorted(free)):
            a = combo[k]
            fv = Fr(cand.features[mi].get(v, [Fr(0)] * card[v])[a])
            S += fv if Q is None else _exact_quantize(fv, Q)
        x += Fr(cand.signs[mi]) * cand.gammas[mi] * S * S / 2
    with ctx.D:
        lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    with ctx.U:
        hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
    return w * A.exact_fr(lo), w * A.exact_fr(hi)


def validate_published_rows(published, card, queries):
    """Schema validation applied at EVERY verifier entry point.

    Rejects missing, empty, truncated, over-long, inverted, non-rational and
    out-of-range rows, and any output key that is not a requested query
    variable. `check_composed_publication` accepted an empty row for every
    requested variable and reported no failures, because it validated nothing
    before consuming the producer's masses.
    """
    fails = []
    for v in sorted(queries):
        if v not in card:
            fails.append("requested variable %d is not in the model" % v)
            continue
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        try:
            n = len(rows)
        except TypeError:
            fails.append("variable %d publishes a non-sequence row" % v)
            continue
        if n == 0:
            fails.append("variable %d publishes an EMPTY state row" % v)
            continue
        if n != card[v]:
            fails.append("variable %d publishes %d states, the model declares "
                         "%d" % (v, n, card[v]))
            continue
        for a in range(n):
            try:
                lo, hi = Fr(rows[a][0]), Fr(rows[a][1])
            except (TypeError, ValueError, IndexError, ZeroDivisionError):
                fails.append("variable %d state %d: endpoints are not exact "
                             "rationals" % (v, a))
                continue
            if lo > hi:
                fails.append("variable %d state %d: INVERTED endpoints "
                             "[%s, %s]" % (v, a, lo, hi))
            elif lo < 0 or hi > 1:
                fails.append("variable %d state %d: endpoints [%s, %s] outside "
                             "[0, 1]" % (v, a, lo, hi))
    extra = sorted(k for k in published if k not in queries)
    if extra:
        fails.append("publication carries unrequested output keys %s"
                     % extra[:8])
    return fails


def check_statistic_publication(free, card, unary, cand, Q, queries, published,
                                eps, ctx, radius=Fr(0), cap_configs=None):
    """Independent check of a statistic-DP publication.

    Enumerates configurations directly, which is a DIFFERENT implementation from
    the DP's statistic convolution. Bounded: it refuses rather than running away.
    """
    if Q is not None and (not isinstance(Q, int) or Q < 1):
        raise CollectiveCheckError("a quantized statistic law needs a positive "
                                   "integer Q, got %r" % (Q,))
    # the RESOURCE refusal is decided before anything else: an oversized
    # verification must refuse rather than report a verdict, including a
    # schema verdict it could not have backed with a check
    cap = cap_configs or K.CAPS["region_tuple_assignments"]
    total = 1
    for v in sorted(free):
        total *= card[v]
    if total > cap:
        raise CollectiveCheckError(
            "independent enumeration needs %d configurations, above the %d cap; "
            "this is a RESOURCE refusal, not a verification" % (total, cap))
    schema = validate_published_rows(published, card, queries)
    if schema:
        return False, schema, {"schema_rejected": True}
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

    Evaluates the ORIGINAL UNROUNDED rational features, which is the law the
    Gaussian/Fourier identity represents, and charges the certified quadrature
    radius for every mode.

    This previously delegated with Q=1, which quantized the features away: for
    features [0, 1/4] it checked a law with both weights equal to 1, i.e. a
    state probability of exactly 1/2, against a true
    exp(1/32)/(1+exp(1/32)) = 0.5078118642792046. A publication centred on 1/2
    was then accepted for a law whose probability is 0.5078. Rounding is a
    property of the statistic DP, not of the quadrature identity, so the
    quadrature checker must never apply it.
    """
    # the quadrature radius is charged PER MODE, from each mode's own feature
    # radius, rather than from mode 0 alone
    qrad = Fr(0)
    for mi in range(cand.rank):
        Rk = Fr(0)
        for f in cand.features[mi].values():
            Rk += max(abs(Fr(x)) for x in f)
        qrad += Fr(CO.gf_lattice(cand.gammas[mi], Rk, delta)["total_bound"])
    ok, fails, meta = check_statistic_publication(
        free, card, unary, cand, None, queries, published, eps, ctx,
        radius=radius + qrad, cap_configs=cap_configs)
    meta["method"] = ("direct evaluation of the represented UNROUNDED law; the "
                      "quadrature identity is not re-run, and each mode's "
                      "certified radius is charged into the enclosure")
    meta["quadrature_radius_charged"] = str(qrad)
    meta["law"] = "original unrounded rational features"
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
    from mdi import regions as R, config as K
    # --- SCHEMA first. `for s in range(len(rows))` silently passes an EMPTY
    # row: zero iterations, zero failures, accepted. Every requested variable
    # must publish a complete, well-formed, in-range row.
    # `restricted.card` is a DICT keyed by ORIGINAL variable id, and those ids
    # are not dense after conditioning: pinning X0 leaves free = [1, 2], so
    # `v < len(restricted.card)` rejected a valid query for X2 against a
    # length of 2. Test MEMBERSHIP, never an index range.
    card = {v: restricted.card[v] for v in sorted(queries)
            if v in restricted.card}
    schema = validate_published_rows(published, card, queries)
    if schema:
        return False, schema, {"schema_rejected": True}

    # --- the REGIONAL CERTIFICATE, independently. The composed publication
    # inherits the coarsening error, so the checker must re-derive each
    # region's cells, masses, markers and rho from the ORIGINAL factors and
    # confirm the level distortion is certified at the claimed radius. This
    # previously consumed the producer's `coarse` and `rds` unchecked, so a
    # corrupted certificate passed.
    if restricted.impossible_factor is not None:
        return False, ["a restricted factor is identically zero"], None
    if restricted.constant == 0:
        return False, ["a fully pinned factor is exactly zero"], None
    own_radius = Fr(regional_radius) if regional_radius is not None \
        else Fr(total_radius)
    region_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            region_of[v] = i
    rho_cap = K.region_distortion_budget(own_radius, len(regions))
    problems, rebuilt, own_rds = [], [], []
    for i, reg in enumerate(regions):
        rd_own = R.region_data(reg, restricted.card, restricted.factors,
                               queries)
        own_rds.append(rd_own)
        if tuple(rd_own.boundary) != tuple(rds[i].boundary):
            problems.append("region %d: producer boundary order %s differs "
                            "from the rebuilt %s"
                            % (i, rds[i].boundary, rd_own.boundary))
        cr, probs = RC.recheck_region(reg, restricted, restricted.card,
                                      queries, rho_cap, region_of, coarse[i])
        rebuilt.append(cr)
        problems.extend("region %d: %s" % (i, p) for p in probs)
    # A DISJOINT EXACT COVER OF EVERY FREE VARIABLE, not only the requested
    # ones: a hidden unowned variable drops its factors from the coarse law.
    for v in sorted(restricted.card):
        owners = [i for i, reg in enumerate(regions) if v in reg]
        if len(owners) != 1:
            problems.append(
                "free variable %d is owned by %d regions; the partition is "
                "incomplete or overlapping%s"
                % (v, len(owners), "" if v in queries
                   else " (hidden variable, not requested)"))
    for fi, f in enumerate(restricted.factors):
        unowned = [v for v in f.scope
                   if not any(v in reg for reg in regions)]
        if unowned:
            problems.append(
                "factor %d on scope %s has variables %s in no region and "
                "would be DROPPED from the coarse law"
                % (getattr(f, "origin", fi), tuple(f.scope), unowned[:4]))
    if problems:
        return False, problems, {"certificate_rejected": True}
    Rlevel = R.level_distortion(rebuilt)
    if not K.certify_R_against_t(Rlevel, own_radius):
        return False, ["R_level %s is not certified at the claimed radius %s"
                       % (Rlevel, own_radius)], None
    coarse, rds = rebuilt, own_rds
    (Zlo, Zhi), (counts_lo, counts_hi) = RC.independent_contract(
        restricted, regions, coarse, rds, queries)
    Z = Zlo
    if Z <= 0:
        raise CollectiveCheckError("independent reduced total is nonpositive")
    fails = []
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        for s in range(card[v]):
            lo, hi = Fr(rows[s][0]), Fr(rows[s][1])
            # the quotient enclosure, charging the reduced contraction's own
            # numerical error, then the radius the checker can justify
            qlo = counts_lo.get((v, s), Fr(0)) / Zhi
            qhi = counts_hi.get((v, s), Fr(0)) / Zlo
            own = own_radius
            clo = max(Fr(0), qlo - own)
            chi = min(Fr(1), qhi + own)
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
