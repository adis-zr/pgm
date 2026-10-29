"""Independent regional checker (contract §D.7).

Rebuilds masses, marks, aggregation, extrema, alpha/rho, support and ownership
from the ORIGINAL local factors, then independently contracts the REDUCED model.

It must NOT globally solve the uncoarsened original model as hidden checking
work, and it must not call the producer's aggregation or readout. It therefore
has its own contraction over cell assignments, deliberately simple, with its
cost charged to the plan.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import itertools
from mdi import regions as R, config as K, compact as CP


class RegionalCheckError(ValueError):
    pass


def _independent_region_local(region, card, factors, queries, deadline=None,
                              budget=None):
    """The CHECKER's own local masses and marked masses for one region.

    Independent of regions.region_data: it enumerates the region's boundary
    and interior directly and accumulates A_R(b) and A_{R,i,a}(b) with its own
    loop and its own ownership bookkeeping.

    Calling the producer's region_data left local reconstruction common-mode:
    skewing its markers to 9/10 and 1/10 of the true mass -- while preserving
    the mark/mass identity, so no invariant fired -- made four uniform binary
    variables publish [.897998, .902002] and [.097998, .102002] under
    CERTIFIED_RESEARCH_ROUTE with both verification flags true, every one of
    the eight intervals excluding 1/2.
    """
    import itertools as _it
    from mdi import config as _K
    rset = set(region)
    internal, crossing = [], []
    for fi, f in enumerate(factors):
        sc = set(f.scope)
        if sc <= rset:
            internal.append(fi)
        elif sc & rset:
            crossing.append(fi)
    boundary = tuple(sorted({v for fi in crossing for v in factors[fi].scope
                             if v in rset}))
    interior = tuple(v for v in region if v not in boundary)
    nb = 1
    for v in boundary:
        nb *= card[v]
    ni = 1
    for v in interior:
        ni *= card[v]
    if nb * ni > _K.CAPS["region_local_enumeration"]:
        raise RegionalCheckError(
            "the checker's own local enumeration for region %s needs %d "
            "assignments, above the declared cap" % (tuple(region), nb * ni))
    want = [(v, st) for v in region if v in queries
            for st in range(card[v])]
    A, marks = {}, {k: {} for k in want}
    if deadline is not None:
        deadline()
    seen = 0
    for bc in _it.product(*[range(card[v]) for v in boundary]):
        b = tuple(bc)
        tot = Fr(0)
        mk = {k: Fr(0) for k in want}
        for ic in _it.product(*[range(card[v]) for v in interior]):
            seen += 1
            if deadline is not None and (seen & 0xFF) == 0:
                deadline()
            a = dict(zip(boundary, bc))
            a.update(dict(zip(interior, ic)))
            w = Fr(1)
            for fi in internal:
                f = factors[fi]
                st = f.strides()
                off = sum(a[v] * st[k] for k, v in enumerate(f.scope))
                e = f.table[off]
                if e == 0:
                    w = Fr(0)
                    break
                w *= e
            if w == 0:
                continue
            tot += w
            for (v, stt) in want:
                if a[v] == stt:
                    mk[(v, stt)] += w
        if tot == 0:
            continue
        A[b] = tot
        if budget is not None:
            budget.charge("local_mass_entries", 1, "checker local mass")
        for k in want:
            if mk[k] != 0:
                marks[k][b] = mk[k]
                if budget is not None:
                    budget.charge("local_mass_entries", 1,
                                  "checker local marker")
    # the checker's OWN mark/mass identity
    for v in region:
        if v not in queries:
            continue
        for b in A:
            tot = sum(marks[(v, st)].get(b, Fr(0))
                      for st in range(card[v]))
            if tot != A[b]:
                raise RegionalCheckError(
                    "the checker's own marks do not sum to its own mass at "
                    "region %s assignment %s" % (tuple(region), b))
    return boundary, interior, internal, crossing, A, marks


def _own_profile_product(fis, factors, card, region, in_vars, nout, layout,
                         deadline=None, budget=None):
    """The CHECKER's own product kernel for one verified group, in the layout
    the emitted profile is REQUIRED to have.

    `layout` is "factor" for a bare single-factor profile (crossing_profile
    keeps the factor's own scope order for both inside and outside axes) or
    "sorted" for a tagged aggregate kernel (aggregate_crossings sorts the
    union). r12 sorted the union unconditionally, so a legal factor whose
    scope lists an outside variable before an inside one -- ordinary UAI
    input -- was compared against a differently ordered table and REJECTED.
    UAI scope order is part of the table indexing contract, not bad input.

    Returns None when the kernel exceeds the declared entry cap. Temporary
    products are bit-bounded (a legal two-variable control built an
    80,001-bit intermediate under the 65,536-bit cap before cancelling it),
    strides are hoisted, and the deadline is checked inside the outside loop.
    """
    import itertools as _it
    from mdi import config as _K
    rset = set(region)
    if layout == "factor":
        if len(fis) != 1:
            return {"__layout__": "factor layout needs exactly one factor"}
        f = factors[fis[0]]
        inside = [v for v in f.scope if v in rset]
        outside = [v for v in f.scope if v not in rset]
    else:
        scope = sorted({v for fi in fis for v in factors[fi].scope})
        inside = [v for v in scope if v in rset]
        outside = [v for v in scope if v not in rset]
    nin = non = 1
    for v in inside:
        nin *= card[v]
    for v in outside:
        non *= card[v]
    if nin * non > _K.CAPS["aggregated_kernel_entries"]:
        return None
    if list(inside) != list(in_vars) or non != nout:
        return {"__layout__": (tuple(inside), non, tuple(in_vars), nout)}
    if budget is not None:
        budget.charge("local_mass_entries", max(1, nin * non),
                      "checker profile product")
    # hoist strides and scope positions once per group
    pre = []
    for fi in fis:
        f = factors[fi]
        pre.append((f, f.strides(), list(enumerate(f.scope))))
    bitcap = _K.CAPS["rational_bit_length"]
    # ENTRY check, then bounded checks on actual inner work. A four-entry
    # product of 128 factors performed 512 reads after simulated expiry before
    # the completion check caught it: counting kernel entries alone misses
    # long constituent-factor loops. Work is counted per factor read.
    if deadline is not None:
        deadline()
    out = {}
    work = 0
    for ic in _it.product(*[range(card[v]) for v in inside]):
        row = []
        a_in = dict(zip(inside, ic))
        for oc in _it.product(*[range(card[v]) for v in outside]):
            a = dict(a_in)
            a.update(zip(outside, oc))
            w = Fr(1)
            for f, st, sc in pre:
                work += 1
                if deadline is not None and (work & 0x3F) == 0:
                    deadline()
                off = 0
                for k, v in sc:
                    off += a[v] * st[k]
                e = Fr(f.table[off])
                if e == 0:
                    w = Fr(0)
                    break
                w *= e
                # bound the TEMPORARY, not only the returned value
                if (w.numerator.bit_length() > bitcap
                        or w.denominator.bit_length() > bitcap):
                    raise RegionalCheckError(
                        "the checker's profile product reached %d bits, "
                        "above the declared %d-bit cap"
                        % (max(w.numerator.bit_length(),
                               w.denominator.bit_length()), bitcap))
            row.append(w)
        out[tuple(ic)] = row
    if deadline is not None:
        deadline()
    return out


def _profiles_agree(submitted, own):
    """Exact comparison of a submitted profile table with the checker's own."""
    if not isinstance(own, dict) or "__layout__" in own:
        return False
    if not isinstance(submitted, dict) or set(submitted) != set(own):
        return False
    for k in own:
        srow, orow = submitted[k], own[k]
        if len(srow) != len(orow):
            return False
        if any(Fr(a) != Fr(b) for a, b in zip(srow, orow)):
            return False
    return True


def _own_profile_rows(b, profiles, bpos, card):
    """Select each verified profile's row for boundary assignment `b` with the
    CHECKER's own position maps.

    r13 verified every profile table's contents and then called the PRODUCER's
    R._profile_signature -- its coarsening merge-key computation -- to pick
    which rows to compare. Table equality does not prove the later
    assignment-to-row mapping: a shared projector that returned the zero row
    for every assignment collapsed pair [1,2,3,8] to one cell per region and
    certified four intervals near 1/2 against truths (3/14, 11/14) and
    (2/7, 5/7), with every table value, id and layout correct.

    Here the key is derived from the checker's checked boundary order and the
    validated profile's own inside axes, and every selected row is confirmed
    to exist with the declared outside width. Hoisted position maps are
    reused across members.
    """
    rows = []
    for (fid, in_vars, nout, tbl) in profiles:
        key = []
        for v in in_vars:
            if v not in bpos:
                raise RegionalCheckError(
                    "profile %r indexes inside variable %d, which is not in "
                    "the checker's boundary order" % (fid, v))
            st = b[bpos[v]]
            if not (0 <= st < card[v]):
                raise RegionalCheckError(
                    "boundary assignment %s puts variable %d at state %d, "
                    "outside its cardinality %d" % (b, v, st, card[v]))
            key.append(st)
        key = tuple(key)
        if key not in tbl:
            raise RegionalCheckError(
                "profile %r has no row for inside key %s" % (fid, key))
        row = tbl[key]
        if len(row) != nout:
            raise RegionalCheckError(
                "profile %r row %s has %d entries, declared outside width %d"
                % (fid, key, len(row), nout))
        rows.append(row)
    return tuple(rows)


def _own_ratio_extrema(row_b, row_r):
    """The CHECKER's OWN exact ratio extrema over common positive entries.

    r10 called the producer's R.ratio_extrema here, so the DECISIVE bound
    calculation was shared: corrupting that one routine to return (1, 1)
    admitted a false R = 1 and four wrong intervals near 1/2 for the pair
    [1,2,3,8], whose truths are X0 = (3/14, 11/14) and X1 = (2/7, 5/7). My
    r10 regression rejected that submission only because it omitted the valid
    publication reserve -- with the reserve restored the false certificate
    passed. A test that asserts `not ok` has not demonstrated rejection of the
    named defect.

    This is a separate implementation of the same mathematics: identical zero
    masks are required, 0/0 is never formed, and L and U are the exact minimum
    and maximum of y_b / y_r over the commonly positive coordinates.
    """
    if len(row_b) != len(row_r):
        raise RegionalCheckError("profile length mismatch (%d vs %d)"
                                 % (len(row_b), len(row_r)))
    lo = hi = None
    for yb, yr in zip(row_b, row_r):
        b0 = (Fr(yb) == 0)
        r0 = (Fr(yr) == 0)
        if b0 != r0:
            raise RegionalCheckError(
                "zero masks differ: one profile entry is zero and the other "
                "is not, so these states cannot merge")
        if b0:
            continue
        q = Fr(yb) / Fr(yr)
        if lo is None or q < lo:
            lo = q
        if hi is None or q > hi:
            hi = q
    if lo is None:
        # every coordinate is zero on both sides: the ratio is unconstrained
        # but the merge is exact, so L = U = 1
        return Fr(1), Fr(1)
    return lo, hi


def _verify_coarsening_witness(region, card, factors, queries, producer_coarse,
                               iA, imarks, rho_cap, deadline=None,
                               region_of_for_profiles=None,
                               prebuilt_rd=None, budget=None):
    """Verify the SUBMITTED coarsening witness from checker-owned quantities.

    r9 verified the raw local weights A_R(b) and A_{R,i,a}(b) independently,
    but then built its reference cell representation by calling the
    PRODUCER's merge_region. Correct input to a shared faulty transformation
    is not independent verification of its output: changing only the shared
    merger's cell markers to 0.9 and 0.1 times the unchanged cell mass -- and
    leaving cells, raw sums, alpha, rho and the mark-sum identity intact --
    certified all eight intervals near .9/.1 on four uniform binary variables
    whose every true probability is 1/2. A second control corrupting only the
    shared profile-ratio routine admitted a false R = 1 and probabilities near
    1/2 against X0 = (3/14, 11/14).

    So the witness is CHECKED, not recomputed by the same code:
      * cell membership partitions the supported boundary states exactly once;
      * every member weight alpha is re-derived from the ORIGINAL factors via
        this checker's own profile extrema;
      * the per-cell distortion rho and the claimed cap are re-derived;
      * M_c      = sum_{b in c} alpha_b A_R(b)
        N_{c,i,a}= sum_{b in c} alpha_b A_{R,i,a}(b)
        are recomputed from the checker's OWN raw arrays and compared exactly.
    The mark-sum-equals-mass identity is necessary but verifies no individual
    marker, so it is not used as evidence here.
    """
    pc = producer_coarse
    problems = []

    # ---- membership is an exact partition of the checker's own support
    seen = {}
    for ci, cell in enumerate(pc.cells):
        for mb, al in cell.members:
            b = tuple(mb)
            if b in seen:
                problems.append(
                    "boundary state %s appears in cells %d and %d; the cell "
                    "map is not a partition" % (b, seen[b], ci))
            seen[b] = ci
            if b not in iA:
                problems.append(
                    "cell %d claims boundary state %s, which has NO support "
                    "in the checker's own local enumeration" % (ci, b))
    missing = [b for b in iA if b not in seen]
    if missing:
        problems.append(
            "boundary states %s carry checker-computed support but belong to "
            "no cell, so their mass is dropped" % (sorted(missing)[:4],))
    if problems:
        return problems

    # ---- re-derive each member's alpha and the cell distortion from the
    # ORIGINAL factors, using this checker's own profile construction
    # Build the response profiles the certificate depends on, from the
    # ORIGINAL factors, with the checker's own call into the validated
    # structural primitives (crossing_profile / aggregate_crossings are
    # permitted shared structure; the decisive extrema and the alpha/rho
    # derivation below are the checker's own).
    rd_sig = prebuilt_rd if prebuilt_rd is not None else R.region_data(
        region, card, factors, queries, deadline=deadline)
    bpos = {v: k for k, v in enumerate(rd_sig.boundary)}
    try:
        agg_detail = None
        if region_of_for_profiles is not None:
            profiles, agg_detail = R.aggregate_crossings(
                rd_sig, factors, card, region_of_for_profiles,
                deadline=deadline)
        else:
            profiles = []
            for fi in rd_sig.crossing_factors:
                f = factors[fi]
                in_vars, nout, tbl = R.crossing_profile(f, rd_sig.vars, card)
                profiles.append((fi, in_vars, nout, tbl))
    except Exception as _e:
        # A proof-construction refusal must stay a REFUSAL. Setting
        # profiles=None skipped the alpha/rho obligations entirely and
        # returned an empty problem list for an invalid witness.
        return ["the checker could not construct the profiles its distortion "
                "proof requires (%s), so the witness is UNVERIFIED rather "
                "than accepted" % _e]

    # ---- INDEPENDENT coverage AND numerical product verification.
    #
    # r11 derived own_crossing but could only reject when the profile list was
    # EMPTY: the second `len(profiles) < 1` branch was unreachable once the
    # list was nonempty, so keeping one profile while omitting another
    # accepted four wrong coordinates. It also trusted the profile TABLE
    # VALUES: replacing them with ones -- preserving every factor id, scope,
    # length and support mask -- left the independent extrema computing (1,1)
    # on wrong inputs and accepted four intervals near 1/2 for [1,2,3,8].
    # Labels do not prove products, and a nonempty list does not prove
    # coverage.
    #
    # The identifier schema is a bare factor index OR a tagged group such as
    # ('agg', r1, r2); `int('agg')` crashed a CLEAN valid case, which is why
    # the constituent factors are read from the aggregation DETAIL record.
    own_crossing = []
    rset = set(region)
    for fi, f in enumerate(factors):
        sc = set(f.scope)
        if (sc & rset) and not (sc <= rset):
            own_crossing.append(fi)

    # ---- ONE explicit relation:
    #   original crossing OCCURRENCES -> represented GROUPS -> expected
    #   EMITTED profiles (with identity and layout) -> verified tables.
    #
    # r12 checked the detail record's factor multiset and some products, but
    # never bound every CONSUMED profile to a verified group. by_id silently
    # overwrote duplicate ids, a singleton group verified only the profile
    # selected by its id, and the extrema loop then consumed the whole list
    # including profiles nobody checked. On a uniform pair an appended
    # unowned profile (id 37, rows [1,1]/[9,9]) or a duplicate id 0 with a bad
    # table first certified four intervals near .1/.9 for truths of 1/2.
    #
    # The expected emitted set is derived from the detail record and the
    # aggregator's actual schema:
    #   aggregated group  -> exactly one profile tagged ("agg", *fis), sorted
    #                        axis layout;
    #   singleton group or DECLINED aggregate (product over the entry cap)
    #                     -> one bare-id profile per factor, factor-scope
    #                        axis layout.
    # r12 assumed any multi-factor group needed a tagged profile, so the
    # ordinary over-cap fallback to individual profiles -- a legal
    # representation under unchanged caps -- was rejected.
    expected = []      # (profile_id, fis, layout)
    claimed = []
    if agg_detail:
        for gi, entry in enumerate(agg_detail):
            if not isinstance(entry, dict) or "factors" not in entry:
                problems.append(
                    "aggregation record %d does not name its constituent "
                    "original factors, so coverage cannot be established"
                    % gi)
                continue
            fl = [int(x) for x in entry["factors"]]
            bad = [fi for fi in fl if not (0 <= fi < len(factors))]
            if bad:
                problems.append("aggregation record %d names factor index(es) "
                                "%s outside the model" % (gi, bad[:4]))
                continue
            claimed.extend(fl)
            if entry.get("aggregated") and len(fl) > 1:
                expected.append((("agg",) + tuple(fl), fl, "sorted"))
            else:
                for fi in fl:
                    expected.append((fi, [fi], "factor"))
    else:
        for entry in profiles:
            fid = entry[0]
            if isinstance(fid, int) and 0 <= fid < len(factors):
                claimed.append(fid)
                expected.append((fid, [fid], "factor"))
            else:
                problems.append(
                    "profile identifier %r is not a plain original factor "
                    "index and no aggregation record explains it" % (fid,))

    from collections import Counter as _Ctr
    # (a) the groups partition the checker's own crossing occurrences once
    want_c, got_c = _Ctr(own_crossing), _Ctr(claimed)
    if want_c != got_c:
        miss = sorted((want_c - got_c).elements())
        extra = sorted((got_c - want_c).elements())
        problems.append(
            "the represented groups do not account for the checker's own "
            "crossing-factor occurrences exactly once: missing %s, extra %s"
            % (miss[:4], extra[:4]))
    # (b) the EMITTED profile ids equal the expected ids as a multiset --
    #     checked BEFORE any dictionary could collapse a duplicate
    emitted_ids = [e[0] for e in profiles]
    exp_c, emi_c = _Ctr(x[0] for x in expected), _Ctr(emitted_ids)
    if exp_c != emi_c:
        miss = sorted((exp_c - emi_c).elements(), key=repr)
        extra = sorted((emi_c - exp_c).elements(), key=repr)
        problems.append(
            "the emitted profiles do not correspond one-to-one with the "
            "represented groups: expected but missing %s, emitted but "
            "unjustified %s (duplicates count)" % (miss[:4], extra[:4]))
    if problems:
        return problems

    # (c) every emitted profile is verified against ITS OWN group, in its own
    #     layout -- never cross-compared against another group's product
    exp_by_id = {x[0]: x for x in expected}
    for (fid, in_vars, nout, tbl) in profiles:
        _pid, fl, layout = exp_by_id[fid]
        try:
            own = _own_profile_product(fl, factors, card, region, in_vars,
                                       nout, layout, deadline=deadline,
                                       budget=budget)
        except RegionalCheckError as e:
            problems.append("profile %r: %s" % (fid, e))
            continue
        if own is None:
            problems.append(
                "the profile for original factor(s) %s is too large for the "
                "checker to verify locally, so the witness is UNVERIFIED"
                % (fl[:4],))
            continue
        if not _profiles_agree(tbl, own):
            problems.append(
                "the response profile %r for original factor(s) %s does NOT "
                "match the product the checker computes from those factors "
                "in the %s layout; labels and support masks do not prove "
                "profile VALUES" % (fid, fl[:4], layout))
    if problems:
        return problems

    if profiles is not None:
        for ci, cell in enumerate(pc.cells):
            rep = tuple(cell.rep)
            rho_cell = Fr(1)
            for mb, al in cell.members:
                b = tuple(mb)
                if b == rep:
                    if Fr(al) != Fr(1):
                        problems.append(
                            "cell %d representative %s has alpha %s, not 1"
                            % (ci, b, al))
                    continue
                try:
                    sb = _own_profile_rows(b, profiles, bpos, card)
                    sr = _own_profile_rows(rep, profiles, bpos, card)
                except Exception as e:
                    problems.append("cell %d: profile rebuild failed: %s"
                                    % (ci, e))
                    continue
                alpha = Fr(1)
                rho = Fr(1)
                bad = False
                for rb, rr in zip(sb, sr):
                    try:
                        L, U = _own_ratio_extrema(rb, rr)
                    except Exception as e:
                        problems.append(
                            "cell %d member %s: the checker's own profile "
                            "extrema refuse (%s), so this merge is not "
                            "justified" % (ci, b, e))
                        bad = True
                        break
                    if L <= 0:
                        problems.append(
                            "cell %d member %s: nonpositive profile lower "
                            "bound" % (ci, b))
                        bad = True
                        break
                    alpha *= L
                    rho *= U / L
                if bad:
                    continue
                if Fr(al) != alpha:
                    problems.append(
                        "cell %d member %s has alpha %s, but the checker's own "
                        "profile extrema give %s" % (ci, b, al, alpha))
                if rho > rho_cell:
                    rho_cell = rho
                if rho > Fr(rho_cap):
                    problems.append(
                        "cell %d member %s has distortion %s, above the "
                        "allocated cap %s" % (ci, b, rho, rho_cap))
            if Fr(pc.rho_region) < rho_cell:
                problems.append(
                    "the region's claimed rho %s is BELOW the checker's own "
                    "worst cell distortion %s" % (pc.rho_region, rho_cell))

    # ---- recompute M and every N from the CHECKER's own raw arrays
    for ci, cell in enumerate(pc.cells):
        mexp = Fr(0)
        for mb, al in cell.members:
            mexp += Fr(al) * Fr(iA[tuple(mb)])
        if Fr(pc.M[ci]) != mexp:
            problems.append(
                "cell %d mass is %s, but sum_b alpha_b A_R(b) over the "
                "checker's own raw weights is %s"
                % (ci, pc.M[ci], mexp))
    # EXACT marker coverage, derived from the ORIGINAL requested variables and
    # their cardinalities. Iterating only the SUBMITTED keys let a merger that
    # dropped X0's whole key set pass this check, so a missing numerator
    # silently became zero.
    required = {(v, st) for v in region if v in queries
                for st in range(card[v])}
    present = {k for k in pc.N if k[0] in queries}
    miss_k = sorted(required - present)
    if miss_k:
        problems.append(
            "the witness omits required marker key(s) %s; a missing marked "
            "mass is NOT zero" % (miss_k[:6],))
    extra_k = sorted(present - required)
    if extra_k:
        problems.append("the witness carries marker key(s) %s that no "
                        "requested variable implies" % (extra_k[:6],))
    for key, col in sorted(pc.N.items()):
        if key[0] not in queries:
            continue
        if len(col) != len(pc.cells):
            problems.append(
                "marker %s has %d cell entries but the witness declares %d "
                "cells" % (key, len(col), len(pc.cells)))
            continue
        own = imarks.get(key)
        if own is None:
            problems.append("marker %s is published but the checker computed "
                            "no raw marked mass for it" % (key,))
            continue
        for ci, cell in enumerate(pc.cells):
            nexp = Fr(0)
            for mb, al in cell.members:
                nexp += Fr(al) * Fr(own.get(tuple(mb), Fr(0)))
            if Fr(col[ci]) != nexp:
                problems.append(
                    "marker %s cell %d is %s, but sum_b alpha_b "
                    "A_{R,i,a}(b) over the checker's own raw weights is %s"
                    % (key, ci, col[ci], nexp))
                break
    return problems


def recheck_region(region, restricted, card, queries, rho_cap, region_of,
                   producer_coarse, deadline=None, budget=None,
                   prebuilt_rd=None):
    """Independently rebuild one region's cells and compare STRUCTURE only.

    The producer's numbers are never consumed: masses and marks are recomputed
    from the original factors, and only the resulting membership and mass values
    are compared.
    """
    # Reuse the caller's already-reconstructed local data. The checker made
    # THREE local enumerations per region (the outer loop's, this one, and the
    # witness verifier's profile rebuild); reuse is a work reduction that does
    # not weaken independence, because the independent raw accumulation below
    # is a separate implementation either way.
    rd = prebuilt_rd if prebuilt_rd is not None else R.region_data(
        region, card, restricted.factors, queries,
        deadline=deadline, budget=budget)
    cr = R.merge_region(rd, restricted.factors, card, rho_cap, queries,
                        deadline=deadline, region_of=region_of, aggregate=True)
    pc = producer_coarse
    problems = []
    # ---- the CHECKER's OWN local masses and markers, from a distinct
    # implementation, compared against the ones the merge was built from.
    # Structural utilities may be shared; the local aggregate may not.
    try:
        ib, ii, iint, icr, iA, imarks = _independent_region_local(
            region, card, restricted.factors, queries, deadline=deadline,
            budget=budget)
    except RegionalCheckError as e:
        problems.append("independent local reconstruction refused: %s" % e)
        return cr, problems
    if tuple(ib) != tuple(rd.boundary):
        problems.append("independent boundary %s != producer %s"
                        % (tuple(ib), tuple(rd.boundary)))
    if sorted(iint) != sorted(rd.internal_factors):
        problems.append("independent internal factor set differs")
    if sorted(icr) != sorted(rd.crossing_factors):
        problems.append("independent crossing factor set differs")
    if set(iA) != set(rd.A):
        problems.append("independent boundary support differs (%d vs %d "
                        "assignments)" % (len(iA), len(rd.A)))
    else:
        for b in iA:
            if Fr(iA[b]) != Fr(rd.A[b]):
                problems.append("independent local mass at %s is %s, the "
                                "producer's is %s" % (b, iA[b], rd.A[b]))
                break
    if set(imarks) != set(rd.marks):
        problems.append("independent marker key set differs")
    else:
        for k in sorted(imarks):
            for b in imarks[k]:
                if Fr(imarks[k][b]) != Fr(rd.marks[k].get(b, Fr(0))):
                    problems.append(
                        "independent marked mass %s at %s is %s, the "
                        "producer's is %s"
                        % (k, b, imarks[k][b], rd.marks[k].get(b, Fr(0))))
                    break
            if problems:
                break
    if problems:
        return cr, problems
    # ---- verify the SUBMITTED coarsening witness from checker-owned
    # quantities. Comparing against another call to the same merger is not
    # independent verification of the transformation.
    wp = _verify_coarsening_witness(
        region, card, restricted.factors, queries, pc, iA, imarks, rho_cap,
        deadline=deadline, region_of_for_profiles=region_of,
        prebuilt_rd=rd, budget=budget)
    if wp:
        problems.extend(wp)
        return cr, problems
    if len(cr.cells) != len(pc.cells):
        problems.append("cell count %d != producer %d" % (len(cr.cells),
                                                          len(pc.cells)))
        return cr, problems
    for ci, (a, b) in enumerate(zip(cr.cells, pc.cells)):
        if a.rep != b.rep:
            problems.append("cell %d representative %s != %s" % (ci, a.rep, b.rep))
        if sorted(x for x, _ in a.members) != sorted(x for x, _ in b.members):
            problems.append("cell %d membership differs" % ci)
        for (mb, al_a), (mb2, al_b) in zip(sorted(a.members), sorted(b.members)):
            if al_a != al_b:
                problems.append("cell %d alpha for %s: %s != %s"
                                % (ci, mb, al_a, al_b))
    for ci in range(len(cr.cells)):
        if Fr(cr.M[ci]) != Fr(pc.M[ci]):
            problems.append("cell %d mass %s != %s" % (ci, cr.M[ci], pc.M[ci]))
    if set(cr.N) != set(pc.N):
        problems.append("marker key sets differ")
    else:
        for key in cr.N:
            for ci in range(len(cr.cells)):
                if Fr(cr.N[key][ci]) != Fr(pc.N[key][ci]):
                    problems.append("marker %s cell %d: %s != %s"
                                    % (key, ci, cr.N[key][ci], pc.N[key][ci]))
    if Fr(cr.rho_region) != Fr(pc.rho_region):
        problems.append("rho %s != %s" % (cr.rho_region, pc.rho_region))
    # the mark/mass identity, independently
    for v in region:
        keys = [k for k in cr.N if k[0] == v]
        if not keys:
            continue
        for ci in range(len(cr.cells)):
            tot = sum(Fr(cr.N[k][ci]) for k in keys)
            if tot != Fr(cr.M[ci]):
                problems.append("mark/mass identity fails at %d cell %d" % (v, ci))
    return cr, problems


def independent_contract(restricted, regions, coarse, rds, queries,
                         deadline=None, cap_assignments=None,
                         allow_enumeration=True):
    """Contract the REDUCED model with the checker's own code.

    Prefers an independent MESSAGE-PASSING contraction over the reduced graph,
    which preserves the factorization. Enumerating every joint cell assignment
    costs the product of all cell cardinalities and so priced the regional route
    at ~1e78 purely because of the checker: a 50-variable binary chain has 2^50
    joint assignments but elimination width one and a largest bag of four.

    Exhaustive enumeration is retained only for bounded controls, and only when
    the reduced graph's own elimination is unavailable.
    """
    try:
        return _reduced_message_passing(restricted, regions, coarse, rds,
                                        queries, deadline=deadline)
    except RegionalCheckError:
        if not allow_enumeration:
            raise
    cap = cap_assignments or K.CAPS["checker_contraction_space"]
    projected, _ = CP.project_crossings(restricted, regions, coarse, rds)
    ncell = [len(c.cells) for c in coarse]
    total = 1
    for k in ncell:
        total *= k
    if total > cap:
        raise RegionalCheckError(
            "independent contraction needs %d cell assignments, above the %d "
            "cap; this is a RESOURCE refusal, not a verification" % (total, cap))
    Z = Fr(0)
    counts = {}
    for tup in itertools.product(*[range(k) for k in ncell]):
        if deadline is not None:
            deadline()
        cell_of = {i: tup[i] for i in range(len(regions))}
        w = Fr(1)
        for i, ci in enumerate(tup):
            w *= Fr(coarse[i].M[ci])
        if w == 0:
            continue
        for pc in projected:
            w *= pc.value(cell_of)
            if w == 0:
                break
        if w == 0:
            continue
        Z += w
        for i, ci in enumerate(tup):
            Mc = Fr(coarse[i].M[ci])
            if Mc <= 0:
                continue
            for key, col in coarse[i].N.items():
                if key[0] not in queries:
                    continue
                Nc = Fr(col[ci])
                if Nc == 0:
                    continue
                counts[key] = counts.get(key, Fr(0)) + w / Mc * Nc
    if Z <= 0:
        raise RegionalCheckError("reduced model has nonpositive total weight")
    # This path is EXACT rational arithmetic throughout, so its enclosure is a
    # point. The same (lo, hi) shape is returned so callers cannot accidentally
    # treat a rounded result as exact.
    return (Z, Z), (counts, dict(counts))


def _reduced_message_passing(restricted, regions, coarse, rds, queries,
                             deadline=None):
    """Independent contraction of the REDUCED graph by elimination.

    Builds a factor graph over CELL variables using the compact projected
    crossings, then runs the generic engine on it. This is the checker's own
    code path: it shares the validated primitives the spec permits but not the
    producer's aggregation or readout.
    """
    from mdi import model as MM, plan as PP, arith as AA, contract as CC
    ncell = [len(c.cells) for c in coarse]
    projected, _ = CP.project_crossings(restricted, regions, coarse, rds)
    facs = []
    for i in range(len(regions)):
        facs.append(MM.Factor(scope=(i,), card=(ncell[i],),
                              table=[Fr(x) for x in coarse[i].M],
                              origin=-(i + 1)))
    for pc in projected:
        rs = tuple(pc.regions)
        cards = tuple(ncell[i] for i in rs)
        n = 1
        for c in cards:
            n *= c
        if n > K.CAPS["aggregated_kernel_entries"]:
            raise RegionalCheckError(
                "a reduced crossing factor over regions %s needs %d entries, "
                "above the declared cap" % (rs, n))
        st = [1] * len(cards)
        acc = 1
        for k in range(len(cards) - 1, -1, -1):
            st[k] = acc
            acc *= cards[k]
        tab = []
        for flat in range(n):
            rem, dig = flat, []
            for k in range(len(cards)):
                dig.append(rem // st[k])
                rem %= st[k]
            tab.append(pc.value({rs[k]: dig[k] for k in range(len(rs))}))
        facs.append(MM.Factor(scope=rs, card=cards, table=tab, origin=-1000))
    cm = MM.Model(nvars=len(regions), card=list(ncell), factors=facs)
    cm.validate()
    rc = MM.restrict(cm, {})
    sel = PP.choose_plan(rc.free, rc.card, rc.factors, 128,
                         K.RESOURCES["arm_rss_bytes"])
    if sel["chosen"] is None:
        raise RegionalCheckError("no ordering fits for the reduced graph")
    pl, est = sel["chosen"]
    ctx = AA.Ctx(128)
    eng = CC.Engine(pl, rc.factors, ctx, mode="P", deadline=deadline)
    roots = [b.idx for b in pl.bags if b.parent == -1]
    if len(roots) != 1:
        raise RegionalCheckError("reduced graph is disconnected")
    eng.upward(roots[0])
    rootv = eng.root_value(roots[0])
    if not rootv.support[0]:
        raise RegionalCheckError("reduced model has zero weight")
    Z = AA.exact_fr(rootv.vals[0])
    if Z <= 0:
        raise RegionalCheckError("reduced model total is nonpositive")
    # cell marginals, then original markers via the payloads
    # Read each cell variable at its HOME bag, as the main solve path does, and
    # only once that bag is calibrated. Reading every variable of every bag as
    # it was visited collected UNCALIBRATED beliefs for non-home bags, which
    # produced per-variable totals of 1.2e4 and 6.1e6 against a partition
    # function of 1.02e11.
    collected = {}
    home_vars = {}
    for vv in rc.free:
        home_vars.setdefault(pl.var_home[vv], []).append(vv)

    def on_cal(bag):
        for vv in home_vars.get(bag, ()):
            if vv not in collected:
                collected[vv] = eng.read_marginal(vv)

    eng.downward(roots[0], on_calibrated=on_cal)
    # Each cell variable's marginal has its own total, and for a calibrated
    # junction tree every one of those totals equals the partition function. Any
    # discrepancy is a defect, not something to paper over by rescaling: an
    # earlier version returned region 0's total for every count, which made other
    # regions' marginals wrong by orders of magnitude (3.8e-08 against an exact
    # 0.1367), and a rescaling "fix" merely moved the error.
    totals = {}
    for i in range(len(regions)):
        if i not in collected:
            raise RegionalCheckError("cell variable %d was never read" % i)
        vals, seen, depth = collected[i]
        t = Fr(0)
        for ci in range(ncell[i]):
            if seen[ci]:
                t += AA.exact_fr(vals[ci])
        if t <= 0:
            raise RegionalCheckError("cell variable %d has a nonpositive total"
                                     % i)
        totals[i] = t
    # Calibration consistency: every CALIBRATED cell marginal must share one
    # total, which is the partition function. `root_value` is NOT that number:
    # it contracts the root bag after the upward pass only, so it omits the
    # downward contributions. The shared total is taken from the calibrated
    # marginals themselves, and disagreement among them is the real defect
    # signal.
    # Directed rounding means two calibrated totals agree only up to the
    # arithmetic's own error, so exact equality is the wrong test: the observed
    # spread here is 1.7e-39 relative, which is rounding noise, not a
    # calibration defect. A LOOSE relative tolerance still catches the real
    # failure mode, which was totals differing by factors of 1e7.
    ref_total = None
    tol = Fr(1, 10 ** 12)
    for i in sorted(totals):
        t = totals[i]
        if ref_total is None:
            ref_total = t
            continue
        if ref_total <= 0:
            raise RegionalCheckError("nonpositive calibrated total")
        rel = abs(t - ref_total) / ref_total
        if rel > tol:
            raise RegionalCheckError(
                "cell variables disagree on the total by a relative %s: "
                "variable %d gives %s while another gives %s, so the reduced "
                "contraction is NOT calibrated and its marginals cannot be "
                "trusted" % (float(rel), i, t, ref_total))
        if t < ref_total:
            ref_total = t          # the smallest total, conservatively
    if ref_total is None or ref_total <= 0:
        raise RegionalCheckError("no positive calibrated total")
    Z = ref_total
    # The point DAG's outputs are ROUNDED, so converting them with exact_fr
    # yields an exact representation of a rounded number, NOT the true value.
    # The N1 contract gives (1-E*u)^1 v <= v_hat <= v per table, so each
    # calibrated mass lies in [v_hat, v_hat/lambda] with lambda = 1 - E*u.
    # Treating v_hat as exact let the checker accept a zero-width wrong point
    # at t = 0: on a small rational-table example the error was about 1.4e-39.
    counts_lo, counts_hi = {}, {}
    max_depth = 0
    for i in range(len(regions)):
        vals, seen, depth = collected[i]
        max_depth = max(max_depth, int(depth))
        lamb = AA.lam(int(depth), 128)
        for ci in range(ncell[i]):
            if not seen[ci]:
                continue
            pc_hat = AA.exact_fr(vals[ci])
            pc_lo = pc_hat
            pc_hi = pc_hat / lamb
            Mc = Fr(coarse[i].M[ci])
            if Mc <= 0:
                continue
            for key, col in coarse[i].N.items():
                if key[0] not in queries:
                    continue
                Nc = Fr(col[ci])
                if Nc == 0:
                    continue
                counts_lo[key] = counts_lo.get(key, Fr(0)) + pc_lo * Nc / Mc
                counts_hi[key] = counts_hi.get(key, Fr(0)) + pc_hi * Nc / Mc
    # Z was taken from the same rounded marginals, so it carries the same
    # error; widen it in the OPPOSITE direction for each quotient bound.
    lam_z = AA.lam(max_depth, 128)
    return (Z, Z / lam_z), (counts_lo, counts_hi)


def verify_regional_publication(restricted, regions, coarse, rds, queries,
                                published, t_level, eps, deadline=None,
                                budget=None):
    """Full §D.7 check: rebuild every region, independently contract the reduced
    model, and require the publication to CONTAIN the checker's enclosure."""
    # original model and evidence validation BEFORE any numerical work
    if restricted.impossible_factor is not None:
        return False, ["a restricted factor is identically zero: the "
                       "conditioning event has probability zero, so no "
                       "conditional distribution exists"], None
    if restricted.constant == 0:
        return False, ["a fully pinned factor is exactly zero: zero evidence "
                       "weight"], None
    if not queries:
        return False, ["no queries requested"], None
    # Reject an UNKNOWN requested variable explicitly, as the public pipeline
    # does. It was rejected only incidentally, via "marker key sets differ",
    # which names the wrong cause.
    unknown = sorted(v for v in queries if v not in restricted.card)
    if unknown:
        return False, ["requested variables %s are not free variables of the "
                       "restricted model" % unknown[:8]], None
    missing = [v for v in sorted(queries) if v not in published]
    if missing:
        return False, ["variables %s have no published row" % missing[:8]], None
    # ---- COMPLETE PARTITION / QUERY / OUTPUT validation, before any
    # numerical work. An incomplete partition covering only X0 of two
    # independent variables let both X1 state intervals [0, .002] be accepted
    # although the truth is (.25, .75): the checker simply had no region
    # carrying X1 and so never built an enclosure for it, and the rejection it
    # did emit was about a DIFFERENT variable's padding.
    schema = []
    # A DISJOINT EXACT COVER OF EVERY FREE VARIABLE, not only the requested
    # ones. Query selection changes which markers are needed; it does NOT
    # remove hidden variables or their factors from the law. Covering only the
    # requested variables let an unowned X1 drop its crossing factor
    # silently: with pair table [1,2,3,4] and query {0} the checker accepted
    # [.499, .501] for both X0 states where the truth is (.3, .7).
    free_all = sorted(restricted.card)
    for v in free_all:
        owners = [i for i, reg in enumerate(regions) if v in reg]
        if len(owners) == 0:
            schema.append(
                "free variable %d is in NO region: the partition does not "
                "cover the model, so the reduced law omits it and every "
                "factor on its scope%s" % (v, " (REQUESTED)" if v in queries
                                           else " (hidden, not requested)"))
        elif len(owners) > 1:
            schema.append(
                "free variable %d is in %d regions %s: the partition "
                "overlaps, so its mass would be counted more than once"
                % (v, len(owners), owners[:4]))
    # EVERY original factor must be classified, with its whole scope owned.
    # A factor only partly inside the partition was silently skipped.
    for fi, f in enumerate(restricted.factors):
        unowned = [v for v in f.scope
                   if not any(v in reg for reg in regions)]
        if unowned:
            schema.append(
                "factor %d on scope %s has variables %s in no region, so it "
                "can be classified neither local nor crossing and would be "
                "DROPPED from the reduced law"
                % (getattr(f, "origin", fi), tuple(f.scope), unowned[:4]))
    # every region variable must be a real model variable, and regions must not
    # overlap at all
    seen_vars = {}
    for i, reg in enumerate(regions):
        for v in reg:
            if v in seen_vars:
                schema.append("variable %d appears in regions %d and %d"
                              % (v, seen_vars[v], i))
            seen_vars[v] = i
            if v not in restricted.card:
                schema.append("region %d names variable %d, which is not a "
                              "free variable of the restricted model" % (i, v))
    # unknown output keys must reject rather than be silently ignored
    extra = sorted(k for k in published if k not in queries)
    if extra:
        schema.append("publication carries output keys %s that were not "
                      "requested" % extra[:8])
    if schema:
        return False, schema, {"schema_rejected": True}
    region_of = {}
    for i, reg in enumerate(regions):
        for v in reg:
            region_of[v] = i
    rho_cap = K.region_distortion_budget(t_level, len(regions))
    problems = []
    rebuilt = []
    own_rds = []
    for i, reg in enumerate(regions):
        # Rebuild the region's own RegionData, including its BOUNDARY ORDER, and
        # use that rather than the producer's rds. Trusting producer boundary
        # metadata after discarding our own let a corrupted boundary ordering
        # pass an exact-coarsening example with error about 0.131.
        # the checker's own reconstruction is charged too: it is real work
        rd_own = R.region_data(reg, restricted.card, restricted.factors,
                               queries, deadline=deadline, budget=budget)
        own_rds.append(rd_own)
        if tuple(rd_own.boundary) != tuple(rds[i].boundary):
            problems.append("region %d: producer boundary order %s differs from "
                            "the independently rebuilt %s"
                            % (i, rds[i].boundary, rd_own.boundary))
        cr, probs = recheck_region(reg, restricted, restricted.card, queries,
                                   rho_cap, region_of, coarse[i],
                                   deadline=deadline, budget=budget,
                                   prebuilt_rd=rd_own)
        rebuilt.append(cr)
        for p in probs:
            problems.append("region %d: %s" % (i, p))
    if problems:
        return False, problems, None
    rds = own_rds
    Rlevel = R.level_distortion(rebuilt)
    if not K.certify_R_against_t(Rlevel, t_level):
        return False, ["R_level %s is not certified at t=%s" % (Rlevel, t_level)], None
    (Zlo, Zhi), (counts_lo, counts_hi) = independent_contract(
        restricted, regions, rebuilt, rds, queries, deadline=deadline)
    fails = []
    # STRUCTURAL support from the checker's own counts: how many states of
    # each variable carry positive mass. With an EXACT coarsening (t_level 0)
    # a single supported state has probability exactly 1 and a zero count
    # exactly 0, so a correct exact publication must be accepted rather than
    # refused for failing to contain a needlessly padded reference.
    _exact_support = (Fr(t_level) == 0)
    _n_supported = {}
    for _k, _vv in counts_hi.items():
        if _vv > 0:
            _n_supported[_k[0]] = _n_supported.get(_k[0], 0) + 1
    # Build the checker's OWN original-model enclosure, then require the
    # publication to CONTAIN it.
    #
    # The previous direction was backwards: it widened the SUBMITTED interval by
    # t_level and asked whether the coarse point fitted inside. That accepts any
    # publication within t of the coarse answer, including one that is wrong
    # about the original model, and it lets a corrupted producer pass by
    # submitting its own (wrong) number.
    for v in sorted(queries):
        rows = published.get(v)
        if rows is None:
            fails.append("variable %d has no published row" % v)
            continue
        if not rows:
            fails.append("variable %d has an EMPTY state row" % v)
            continue
        nst = None
        for i, reg in enumerate(regions):
            if v in reg:
                nst = len({k[1] for k in coarse[i].N if k[0] == v})
                break
        if nst and len(rows) != nst:
            fails.append("variable %d publishes %d states, the region holds %d"
                         % (v, len(rows), nst))
            continue
        for s in range(len(rows)):
            try:
                lo, hi = Fr(rows[s][0]), Fr(rows[s][1])
            except (TypeError, ValueError, IndexError):
                fails.append("variable %d state %d: endpoints are not exact "
                             "rationals" % (v, s))
                continue
            if lo > hi:
                fails.append("variable %d state %d: INVERTED endpoints "
                             "[%s, %s]" % (v, s, lo, hi))
                continue
            if lo < 0 or hi > 1:
                fails.append("variable %d state %d: endpoints outside [0,1]"
                             % (v, s))
                continue
            # the checker's independent coarse answer, widened OUTWARD by every
            # charged error, is a rigorous enclosure of the ORIGINAL probability
            # the quotient enclosure: smallest numerator over largest
            # denominator, and conversely
            qlo = counts_lo.get((v, s), Fr(0)) / Zhi
            qhi = counts_hi.get((v, s), Fr(0)) / Zlo
            # STRUCTURAL support is exact: when the checker's own count is
            # exactly zero and the coarsening is exact (t_level == 0), the
            # probability IS zero and a correct publication of [0, 0] must be
            # accepted. Padding a zero reference out to [0, t] refused a
            # correct exact-zero result.
            if qlo == 0 and qhi == 0:
                clo = chi = Fr(0)
            elif _exact_support and _n_supported.get(v) == 1 and qlo > 0:
                # the only supported state: its probability IS exactly 1
                clo = chi = Fr(1)
            else:
                clo = max(Fr(0), qlo - t_level)
                chi = min(Fr(1), qhi + t_level)
            # the publication must CONTAIN that enclosure
            if not (lo <= clo and chi <= hi):
                fails.append(
                    "variable %d state %d: publication [%s, %s] does NOT "
                    "contain the independent enclosure [%s, %s]"
                    % (v, s, lo, hi, clo, chi))
            if hi - lo > Fr(eps):
                fails.append("variable %d state %d: published width exceeds eps"
                             % (v, s))
    return (not fails), fails, {"Z": Zlo, "Z_enclosure": (str(Zlo), str(Zhi)),
                                "numerical_error_charged": True,
                                "R_level": Rlevel,
                                "regions_rebuilt": len(rebuilt),
                                "independent_enclosure": True,
                                "direction": "publication must CONTAIN the "
                                             "checker's enclosure, not the "
                                             "reverse"}
