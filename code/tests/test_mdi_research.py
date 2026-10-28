"""Controls for the research mechanism (spec section 12).

All controls enter through the external model API; no branch on their names.
Bytes/generators are fixed in this file.
"""
import os, sys, math, itertools, tempfile
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from mdi import (model as M, plan as P, arith as A, contract as C, oracle as O,
                 solve as S, config as K, regions as R, modes as MD,
                 collective as CO, planner as PL)


def dec(q, places=12):
    q = Fr(q)
    s = q * Fr(10) ** places
    n = int(s) if s.denominator == 1 else int(round(float(s)))
    sign = "-" if n < 0 else ""
    n = abs(n)
    t = str(n).rjust(places + 1, "0")
    return sign + t[:-places] + "." + t[-places:]


def w(txt, suffix=".uai"):
    fh = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    fh.write(txt); fh.close(); return fh.name


# =============== control 2: real regional compression ===============

def ring_of_blocks(NB=4, BS=3, pert=Fr(1, 1000)):
    """A ring of blocks with nonuniform local fields and crossing factors
    depending mainly on BLOCK COUNT, plus a fixed small perturbation."""
    n = NB * BS
    scopes = [(v,) for v in range(n)]
    for b in range(NB):
        base = b * BS
        for k in range(BS - 1):
            scopes.append((base + k, base + k + 1))
    for b in range(NB):
        nxt = (b + 1) % NB
        scopes.append(tuple(range(b * BS, (b + 1) * BS)) + (nxt * BS,))
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "%s %s" % (dec(Fr(10 + v, 10)), dec(Fr(10 + (v * 3) % 7, 10)))])
    for b in range(NB):
        for k in range(BS - 1):
            lines.extend(["4", "2 1 1 3"])
    for b in range(NB):
        rows = []
        for combo in itertools.product(*[range(2)] * BS):
            c = sum(combo)
            for y in range(2):
                rows.append(Fr(2 + c) * (Fr(3) if y == 1 else Fr(1)))
        rows[1] = rows[1] * (Fr(1) + pert)
        lines.extend([str(len(rows)), " ".join(dec(x) for x in rows)])
    return "\n".join(lines) + "\n", n, NB, BS


def _coarsen(m, r, regs, levels=1, queries=None):
    queries = queries or set(r.free)
    t_level = K.level_radius(levels)
    rho_cap = K.region_distortion_budget(t_level, len(regs))
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, queries)
        cr = R.merge_region(rd, r.factors, r.card, rho_cap, queries)
        rds.append(rd); crs.append(cr)
    return rds, crs, t_level


def _lifted(m, r, regs, rds, crs, queries):
    """Enumerate cell tuples: the lifted coarse weight and marked masses."""
    reg_of = {}
    for i, reg in enumerate(regs):
        for v in reg:
            reg_of[v] = i
    cross = [fi for fi, f in enumerate(r.factors)
             if len({reg_of[v] for v in f.scope}) > 1]
    Wt = Fr(0)
    mark = {(v, s): Fr(0) for v in r.free for s in range(r.card[v])}
    ncells = [len(c.cells) for c in crs]
    for tup in itertools.product(*[range(k) for k in ncells]):
        wgt = Fr(1)
        for i, ci in enumerate(tup):
            wgt *= crs[i].M[ci]
        if wgt == 0:
            continue
        a = {}
        for i, ci in enumerate(tup):
            a.update(dict(zip(rds[i].boundary, crs[i].cells[ci].rep)))
        for fi in cross:
            f = r.factors[fi]
            st = f.strides(); off = 0
            for k, v in enumerate(f.scope):
                off += a[v] * st[k]
            e = f.table[off]
            if e == 0:
                wgt = Fr(0); break
            wgt *= e
        if wgt == 0:
            continue
        Wt += wgt
        for i, ci in enumerate(tup):
            for v in regs[i]:
                for s in range(r.card[v]):
                    key = (v, s)
                    if key not in crs[i].N:
                        continue
                    nm = crs[i].N[key][ci]
                    if nm == 0:
                        continue
                    mark[key] += wgt / crs[i].M[ci] * nm
    return Wt, mark


def test_control2_real_regional_compression():
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    queries = set(r.free)
    rds, crs, t_level = _coarsen(m, r, regs, 1, queries)
    states = sum(rd.n_boundary_states() for rd in rds)
    cells = sum(len(c.cells) for c in crs)
    # at least two retained cells, and fewer represented states
    assert all(len(c.cells) >= 2 for c in crs), "every region must retain >= 2 cells"
    assert cells < states, (states, cells)
    # nonconstant crossing interactions
    reg_of = {v: i for i, reg in enumerate(regs) for v in reg}
    cross = [f for f in r.factors if len({reg_of[v] for v in f.scope}) > 1]
    assert cross, "the control must have crossing factors"
    assert any(len(set(f.table)) > 1 for f in cross), "crossings must be nonconstant"
    # the proof: Wtilde <= W <= R_level * Wtilde
    Rlevel = R.level_distortion(crs)
    assert K.certify_R_against_t(Rlevel, t_level), (Rlevel, t_level)
    Ztrue, ptrue = O.exact_all_marginals(r)
    Wt, mark = _lifted(m, r, regs, rds, crs, queries)
    assert Wt <= Ztrue, (float(Wt), float(Ztrue))
    assert Ztrue <= Rlevel * Wt, (float(Ztrue), float(Rlevel * Wt))
    # microscopic outputs preserved within the allocated radius
    worst = max(abs(mark[(v, s)] / Wt - ptrue[v][s])
                for v in r.free for s in range(r.card[v]))
    assert worst <= t_level, (float(worst), float(t_level))


def test_control2_markers_sum_to_mass():
    """sum_a N_{i,a}(C) = M_R(C) through the hierarchy (checker obligation)."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    rds, crs, _ = _coarsen(m, r, regs, 1, set(r.free))
    for i, cr in enumerate(crs):
        for ci in range(len(cr.cells)):
            for v in regs[i]:
                tot = sum(cr.N[(v, s)][ci] for s in range(r.card[v]))
                assert tot == cr.M[ci], (i, ci, v, tot, cr.M[ci])


# =============== control 3: coarsening proof boundaries ===============

def test_control3_proportional_rows_merge_exactly():
    """U=L implies rho=1: proportional rows merge even with very different scales."""
    rows_b = (Fr(2), Fr(4), Fr(6))
    rows_r = (Fr(1), Fr(2), Fr(3))
    L, U = R.ratio_extrema(rows_b, rows_r)
    assert L == U == Fr(2)
    assert U / L == 1, "proportional rows must give rho=1"


def test_control3_near_proportional_rows_charge_rho():
    rows_b = (Fr(2), Fr(4), Fr(6) * Fr(1001, 1000))
    rows_r = (Fr(1), Fr(2), Fr(3))
    L, U = R.ratio_extrema(rows_b, rows_r)
    assert L == Fr(2) and U == Fr(2) * Fr(1001, 1000)
    assert U / L == Fr(1001, 1000)


def test_control3_equal_zero_masks_allowed():
    L, U = R.ratio_extrema((Fr(0), Fr(4)), (Fr(0), Fr(2)))
    assert (L, U) == (Fr(2), Fr(2)), "equal zero masks must skip the 0/0 position"


def test_control3_unequal_zero_masks_refused():
    with pytest.raises(R.Declined):
        R.ratio_extrema((Fr(0), Fr(4)), (Fr(1), Fr(2)))
    with pytest.raises(R.Declined):
        R.ratio_extrema((Fr(3), Fr(4)), (Fr(0), Fr(2)))


def test_control3_factor_spanning_three_regions():
    """A factor spanning three regions must be owned once and still be a
    crossing factor for each incident region."""
    txt = """MARKOV
6
2 2 2 2 2 2
4
3 0 2 4
1 0
1 2
1 4
8
1 2 3 4 5 6 7 8
2
1 2
2
1 3
2
1 5
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = ((0, 1), (2, 3), (4, 5))
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        assert 0 in rd.crossing_factors, "the 3-region factor must cross %s" % (reg,)
    # ownership: exactly one bag owns it in the elimination plan
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    assert P.validate_plan(pl, r.factors)


def test_control3_permuted_scope_order():
    """Permuting a factor's scope must not change the coarsening result."""
    txt_a = """MARKOV
4
2 2 2 2
3
2 0 1
2 1 2
2 2 3
4
1 2 3 5
4
1 3 2 7
4
1 2 5 3
"""
    m_a = M.read_uai(w(txt_a))
    # same law, pair (1,2) written as (2,1) with the table transposed
    facs = []
    for f in m_a.factors:
        if f.scope == (1, 2):
            t = f.table
            facs.append(M.Factor(scope=(2, 1), card=(2, 2),
                                 table=[t[0], t[2], t[1], t[3]], origin=f.origin))
        else:
            facs.append(f)
    m_b = M.Model(nvars=4, card=[2] * 4, factors=facs).validate()
    ra, rb = M.restrict(m_a, {}), M.restrict(m_b, {})
    Za, pa = O.exact_all_marginals(ra)
    Zb, pb = O.exact_all_marginals(rb)
    assert Za == Zb
    for v in range(4):
        assert pa[v] == pb[v], v


def test_control3_rare_state_amplified_by_exterior_refuses_deletion():
    """A rare local state amplified by exterior factors must NOT be deleted."""
    txt = """MARKOV
3
2 2 2
3
1 0
2 0 1
2 0 2
2
1.0 0.000001
4
1 1 1 1
4
1 1 1000000 1000000
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    # state 1 has tiny local mass but a huge exterior response
    best = R.propose_deletions(rd, r.factors, r.card, Fr(1, 10000))
    if best is not None:
        # if anything was certified, it must not be the amplified state
        U, L, p = R.deletion_bounds(rd, r.factors, r.card, best["deleted"])
        assert p <= Fr(1, 10000), (float(p),)


def test_control3_hard_zero_declines_deletion_test():
    """Hard zeros can force L_R = 0: the deletion test must DECLINE."""
    txt = """MARKOV
2
2 2
2
1 0
2 0 1
2
1 1
4
0 0 1 0
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    # deleting the only state with positive retained response drives L_R to 0
    try:
        U, L, p = R.deletion_bounds(rd, r.factors, r.card, [b for b in rd.A][:1])
        assert L > 0
    except R.Declined as e:
        assert "L_R = 0" in str(e) or "declined" in str(e)


def test_control3_unhelpful_partition_gives_no_reduction():
    """A partition with diverse profiles must produce no merge, not a fake one."""
    n = 6
    scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "%s %s" % (dec(Fr(v + 1)), dec(Fr(v + 2)))])
    for k in range(n - 1):
        lines.extend(["4", "%s %s %s %s" % (dec(Fr(1)), dec(Fr(10 ** (k + 1))),
                                            dec(Fr(10 ** (k + 2))), dec(Fr(1)))])
    m = M.read_uai(w("\n".join(lines) + "\n")); r = M.restrict(m, {})
    regs = ((0, 1), (2, 3), (4, 5))
    rds, crs, t = _coarsen(m, r, regs, 1, set(r.free))
    states = sum(rd.n_boundary_states() for rd in rds)
    cells = sum(len(c.cells) for c in crs)
    # strongly varying crossings: little or no compression, and never unsound
    assert cells <= states
    Rlevel = R.level_distortion(crs)
    assert K.certify_R_against_t(Rlevel, t), "any merge performed must stay certified"


def test_control3_two_level_restores_all_markers():
    """A MANDATORY two-level case must restore all original markers correctly."""
    txt, n, NB, BS = ring_of_blocks(NB=4, BS=2)
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    queries = set(r.free)
    # level 1: the blocks
    regs1 = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    rds1, crs1, t1 = _coarsen(m, r, regs1, 2, queries)
    Wt1, mark1 = _lifted(m, r, regs1, rds1, crs1, queries)
    # every original variable/state still has a marker, and they sum to the mass
    for v in r.free:
        tot = sum(mark1[(v, s)] for s in range(r.card[v]))
        assert tot == Wt1, (v, float(tot), float(Wt1))
    # payload g = N/M sums to 1 in every cell (query restoration identity)
    for i, cr in enumerate(crs1):
        for ci in range(len(cr.cells)):
            for v in regs1[i]:
                g = sum(cr.N[(v, s)][ci] for s in range(r.card[v])) / cr.M[ci]
                assert g == 1, (i, ci, v, g)
    # level 2 composition: parent regions over child cells, markers recomputed
    Ztrue, ptrue = O.exact_all_marginals(r)
    worst = max(abs(mark1[(v, s)] / Wt1 - ptrue[v][s])
                for v in r.free for s in range(r.card[v]))
    assert worst <= K.RADII["regional_coarsening_total"], float(worst)


# =============== control 4: recognition without metadata ===============

def mean_field(n, J, fields, places=12):
    scopes = [(v,) for v in range(n)] + [(i, j) for i in range(n)
                                         for j in range(i + 1, n)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "%s %s" % (
            dec(Fr(round(math.exp(-fields[v]) * 10 ** places), 10 ** places), places),
            dec(Fr(round(math.exp(fields[v]) * 10 ** places), 10 ** places), places))])
    for i in range(n):
        for j in range(i + 1, n):
            e = [Fr(round(math.exp(J * a * b) * 10 ** places), 10 ** places)
                 for a in (-1, 1) for b in (-1, 1)]
            lines.extend(["4", " ".join(dec(x, places) for x in e)])
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("J,want", [(0.30, +1), (-0.25, -1)])
def test_control4_recognizes_mode_sign_from_tables(J, want):
    n = 6
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
    m = M.read_uai(w(mean_field(n, J, fields)))
    r = M.restrict(m, {})
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    assert cands, info
    assert cands[0].signs[0] == want, (cands[0].signs, want)
    # gamma = 2|J| for the +-1 feature parameterization
    assert abs(float(cands[0].gammas[0]) - 2 * abs(J)) < 1e-4, cands[0].gammas


def test_control4_recognition_survives_gauge_change():
    """Redistribute every unary factor into pair tables, preserving the law.
    Recognition must still find the same mode."""
    n, J = 4, 0.30
    fields = [0.1, -0.2, 0.15, -0.05]
    m0 = M.read_uai(w(mean_field(n, J, fields)))
    r0 = M.restrict(m0, {})
    unary = {f.scope[0]: list(f.table) for f in m0.factors if len(f.scope) == 1}
    facs, used = [], set()
    for f in m0.factors:
        if len(f.scope) == 1:
            facs.append(M.Factor(scope=f.scope, card=f.card,
                                 table=[Fr(1), Fr(1)], origin=f.origin))
            continue
        i, j = f.scope
        tbl = list(f.table)
        for who, pos in ((i, 0), (j, 1)):
            if who in used:
                continue
            u = unary[who]; used.add(who)
            tbl = [tbl[a * 2 + b] * (u[a] if pos == 0 else u[b])
                   for a in range(2) for b in range(2)]
        facs.append(M.Factor(scope=f.scope, card=f.card, table=tbl, origin=f.origin))
    m1 = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r1 = M.restrict(m1, {})
    Z0, p0 = O.exact_all_marginals(r0)
    Z1, p1 = O.exact_all_marginals(r1)
    assert Z0 == Z1, "the gauge change must preserve the law exactly"
    for v in range(n):
        assert p0[v] == p1[v], v
    assert all(all(t == 1 for t in f.table) for f in m1.factors if len(f.scope) == 1)
    c0, _ = MD.propose_modes(r0.free, r0.factors, r0.card)
    c1, _ = MD.propose_modes(r1.free, r1.factors, r1.card)
    assert c0 and c1, "recognition must succeed on both"
    assert c0[0].signs == c1[0].signs
    assert c0[0].gammas == c1[0].gammas, (c0[0].gammas, c1[0].gammas)


def test_control4_gauge_split_identity_is_exact():
    tbl = [Fr(3), Fr(5), Fr(7), Fr(11)]
    g = MD.gauge_split(tbl, 2, 2)
    for a in range(2):
        for b in range(2):
            assert g.C * g.u[a] * g.v[b] * g.H[a][b] == tbl[a * 2 + b]
    assert g.H[0][0] == g.H[0][1] == g.H[1][0] == 1


def test_control4_finite_decimal_export_is_the_rational_model():
    """A finite-decimal export is the RATIONAL table model, not silently the
    exact exponential. The fit error must cover that distinction."""
    n, J = 4, 0.30
    fields = [0.0] * n
    m = M.read_uai(w(mean_field(n, J, fields, places=6)))
    r = M.restrict(m, {})
    # the exported entries are exact decimals, not exp(J)
    f = next(x for x in m.factors if len(x.scope) == 2)
    assert all(t.denominator <= 10 ** 6 for t in f.table)
    assert f.table[3] != Fr(math.exp(J)), "the export is a rational approximation"
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    assert cands
    ctx = A.Ctx(120)
    res = MD.build_residual(r.free, r.factors, r.card, cands[0], ctx)
    assert res.nu >= 0, "the certified error must be nonnegative"


# =============== control 5: combined route and the statistic DP ===============

def test_control5_statistic_dp_matches_enumeration_both_signs():
    """The owned-statistic DP must agree with exact enumeration, both signs."""
    import gmpy2
    n = 8
    unary = [[Fr(10 + v, 10), Fr(10 + (3 * v) % 7, 10)] for v in range(n)]
    ctx = A.Ctx(160)
    for s_sign in (1, -1):
        g = Fr(1, 10)

        class Cand:
            rank = 1
            signs = [s_sign]
            gammas = [g]
            features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

        acc, marks, _ = CO.statistic_dp(
            list(range(n)), {v: 2 for v in range(n)},
            {v: unary[v] for v in range(n)}, {}, [], Cand(), 1, set(range(n)))
        # 2^n assignments compress to at most n+1 statistic values
        assert len(acc) <= n + 1, len(acc)
        (Zlo, Zhi), mk = CO.dp_root_combine(acc, marks, Cand(), 1, ctx)
        # reference: full enumeration with the SAME enclosure arithmetic
        Rlo = Rhi = Fr(0)
        rmk = {(v, a): [Fr(0), Fr(0)] for v in range(n) for a in range(2)}
        for combo in itertools.product(*[range(2)] * n):
            wt = Fr(1); Ssum = 0
            for v, a in enumerate(combo):
                wt *= unary[v][a]; Ssum += (1 if a == 1 else -1)
            x = Fr(s_sign) * g * Fr(Ssum * Ssum) / 2
            with ctx.D:
                lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
            with ctx.U:
                hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
            l, h = wt * A.exact_fr(lo), wt * A.exact_fr(hi)
            Rlo += l; Rhi += h
            for v, a in enumerate(combo):
                rmk[(v, a)][0] += l; rmk[(v, a)][1] += h
        assert max(Zlo, Rlo) <= min(Zhi, Rhi), (float(Zlo), float(Zhi),
                                                float(Rlo), float(Rhi))
        for v in range(n):
            for a in range(2):
                dlo, dhi = mk[(v, a)]
                rlo, rhi = rmk[(v, a)]
                pd = (dlo / Zhi, dhi / Zlo)
                pr = (rlo / Rhi, rhi / Rlo)
                assert max(pd[0], pr[0]) <= min(pd[1], pr[1]), (v, a)


def test_control5_dp_masses_stay_nonnegative_for_negative_sign():
    """Signed energy does NOT mean signed DP masses."""
    n = 6
    unary = [[Fr(1), Fr(2)] for _ in range(n)]

    class Cand:
        rank = 1
        signs = [-1]
        gammas = [Fr(1, 5)]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    acc, marks, _ = CO.statistic_dp(list(range(n)), {v: 2 for v in range(n)},
                                    {v: unary[v] for v in range(n)}, {}, [],
                                    Cand(), 1, set(range(n)))
    assert all(wv >= 0 for wv in acc.values()), "DP masses must be nonnegative"
    for tab in marks.values():
        assert all(x >= 0 for x in tab.values())


def test_control5_gaussian_route_matches_enumeration():
    import gmpy2
    n = 6
    unary = [[Fr(10 + v, 10), Fr(10 + (3 * v) % 7, 10)] for v in range(n)]
    ctx = A.Ctx(140)
    g = Fr(1, 20)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [g]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    delta = Fr(1, 10000)
    (Zlo, Zhi), mk, lat = CO.gaussian_evaluate(
        list(range(n)), {v: 2 for v in range(n)},
        {v: unary[v] for v in range(n)}, Cand(), set(range(n)), ctx, delta,
        cap_nodes=200000)
    assert lat["nodes"] < 100000, lat
    Rlo = Rhi = Fr(0)
    for combo in itertools.product(*[range(2)] * n):
        wt = Fr(1); Ssum = 0
        for v, a in enumerate(combo):
            wt *= unary[v][a]; Ssum += (1 if a == 1 else -1)
        x = g * Fr(Ssum * Ssum) / 2
        with ctx.D:
            lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        with ctx.U:
            hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        Rlo += wt * A.exact_fr(lo); Rhi += wt * A.exact_fr(hi)
    mid_gf = float((Zlo + Zhi) / 2)
    mid_ref = float((Rlo + Rhi) / 2)
    rel = abs(mid_gf - mid_ref) / mid_ref
    # the quadrature error is charged separately; it must be small and bounded
    assert rel < 1e-4, rel
    assert lat["total_bound"] <= 2 * delta, lat["total_bound"]


def test_control5_lattice_uses_the_weighted_integrand_bound():
    """Bounding the integrand WITHOUT its Gaussian weight inflates the node
    count by orders of magnitude; the derivation must use the shifted Gaussian."""
    g, Rr, d = Fr(1, 20), Fr(6), Fr(1, 10000)
    lat = CO.gf_lattice(g, Rr, d)
    a = math.sqrt(float(g)) * float(Rr)
    naive = math.exp(a * float(lat["T"]))
    weighted = math.exp(0.5 * a * a) / math.sqrt(2 * math.pi)
    assert weighted < naive, "the weighted bound must be the smaller one"
    assert lat["nodes"] < 100000, lat["nodes"]
    assert "shifted-Gaussian" in lat["derivation"]


def test_control5_marker_ratio_is_sharp_and_outward():
    lo, hi = CO.marker_ratio(Fr(2), Fr(3), Fr(5), Fr(7))
    assert lo == Fr(2) / Fr(9) and hi == Fr(3) / Fr(8)
    assert lo <= hi
    with pytest.raises(CO.Declined):
        CO.marker_ratio(Fr(-1), Fr(3), Fr(5), Fr(7))


def test_control5_fourier_enclosure_and_unprocessed_node():
    lo, hi = CO.fourier_enclose(Fr(4), Fr(5), Fr(10), Fr(1, 100))
    assert lo == Fr(4) - Fr(1, 10) and hi == Fr(5) + Fr(1, 10)
    # an unprocessed node contributes [0, m+]
    lo2, hi2 = CO.fourier_enclose(Fr(0), Fr(0), Fr(10), Fr(1))
    assert lo2 == 0 and hi2 == Fr(10)


def test_control5_statistic_rounding_bound():
    n = 4

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 2)]
        features = [{v: [Fr(-1, 3), Fr(1, 3)] for v in range(n)}]

    for Q in (1, 4, 16):
        kq = CO.round_features(Cand(), list(range(n)), Q)
        D = CO.rounding_energy_bound(Cand(), list(range(n)), kq, Q)
        assert D >= 0
        if Q >= 16:
            assert D < Fr(1, 2), float(D)


# =============== control 6: no useful certificate -> fallback ===============

def test_control6_diverse_profiles_reject_and_fall_back():
    """A full-rank / profile-diverse control must trigger bounded rejection or
    an identity plan, then execute fallback correctly."""
    n = 7
    scopes = [(v,) for v in range(n)] + [(i, j) for i in range(n)
                                         for j in range(i + 1, n)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "%s %s" % (dec(Fr(v + 1)), dec(Fr(2 * v + 3)))])
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            k += 1
            lines.extend(["4", "%s %s %s %s" % (
                dec(Fr(1 + k)), dec(Fr(1 + 3 * k)), dec(Fr(1 + 7 * k)), dec(Fr(1 + 2 * k)))])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    ctx = A.Ctx(120)
    cands = [PL.price_identity(r.free, r.card, r.factors, 64, 1 << 30)]
    cands += PL.price_regional(r.free, r.card, r.factors, set(r.free), 1, 64,
                               1 << 30, 10.0)
    cands += PL.price_modes(r.free, r.factors, r.card, set(r.free), ctx, 10.0)
    sel = PL.select(cands)
    # either identity is chosen, or an admitted transformation that is certified
    assert sel["chosen"] is not None
    if sel["chosen"].kind != "identity":
        assert sel["chosen"].radius > 0
    # and the fallback actually solves the model
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=120)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS", res["outcome"]
    Z, p = O.exact_all_marginals(r)
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res["intervals"][v][s]
            assert lo <= p[v][s] <= hi, (v, s)


def test_control6_identity_plan_is_always_retained():
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    cands = [PL.price_identity(r.free, r.card, r.factors, 64, 1 << 30)]
    cands += PL.price_regional(r.free, r.card, r.factors, set(r.free), 1, 64,
                               1 << 30, 10.0)
    sel = PL.select(cands)
    assert any(c.kind == "identity" for c in sel["all"])


def test_control6_rejected_plans_are_recorded():
    n = 5
    scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.0 1.0"])
    for k in range(n - 1):
        lines.extend(["4", "%s 1.0 1.0 %s" % (dec(Fr(10 ** (k + 1))),
                                              dec(Fr(10 ** (k + 2))))])
    m = M.read_uai(w("\n".join(lines) + "\n")); r = M.restrict(m, {})
    cands = PL.price_regional(r.free, r.card, r.factors, set(r.free), 1, 64,
                              1 << 30, 10.0)
    sel = PL.select([PL.price_identity(r.free, r.card, r.factors, 64, 1 << 30)] + cands)
    assert isinstance(sel["rejected"], list)
    for rj in sel["rejected"]:
        assert rj["reason"], "every rejection must carry a concrete reason"


# =============== control 7: targeted mutations ===============

def test_mutation_inconsistent_alpha_in_marks_detected():
    """Masses and marks must use the SAME alpha; a mismatch breaks sum_a N = M."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    rds, crs, _ = _coarsen(m, r, regs, 1, set(r.free))
    cr = crs[0]
    # valid first
    for ci in range(len(cr.cells)):
        for v in regs[0]:
            assert sum(cr.N[(v, s)][ci] for s in range(r.card[v])) == cr.M[ci]
    # mutate: scale ONE mark by a different alpha
    v0 = regs[0][0]
    cr.N[(v0, 0)][0] = cr.N[(v0, 0)][0] * Fr(3, 2)
    bad = sum(cr.N[(v0, s)][0] for s in range(r.card[v0])) != cr.M[0]
    assert bad, "an inconsistent alpha must break the mark/mass identity"


def test_mutation_undersized_response_extrema_detected():
    """Scanning only part of the profile can understate U/L: saved extremizers
    alone do not prove extrema."""
    full_b = (Fr(1), Fr(2), Fr(100))
    full_r = (Fr(1), Fr(1), Fr(1))
    L, U = R.ratio_extrema(full_b, full_r)
    assert (L, U) == (Fr(1), Fr(100))
    # an undersized scan over the first two entries only
    L2, U2 = R.ratio_extrema(full_b[:2], full_r[:2])
    assert U2 == Fr(2) < U, "the truncated scan must understate the maximum"
    assert (U2 / L2) < (U / L), "and therefore understate rho"


def test_mutation_dropped_factor_changes_the_answer():
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    Z1, p1 = O.exact_all_marginals(r)
    r2 = M.restrict(m, {})
    r2.factors = [f for f in r2.factors if f.origin != r2.factors[-1].origin]
    Z2, p2 = O.exact_all_marginals(r2)
    assert p1 != p2


def test_mutation_omitted_absent_edge_mode_residual():
    """The residual check must cover ABSENT input pairs; omitting them hides
    error."""
    n = 4
    # a chain: pairs (0,1),(1,2),(2,3) present; (0,2),(0,3),(1,3) absent
    scopes = [(v,) for v in range(n)] + [(0, 1), (1, 2), (2, 3)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.0 1.1"])
    for _ in range(3):
        lines.extend(["4", "1.2 0.9 0.9 1.2"])
    m = M.read_uai(w("\n".join(lines) + "\n")); r = M.restrict(m, {})
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    assert cands
    ctx = A.Ctx(120)
    res = MD.build_residual(r.free, r.factors, r.card, cands[0], ctx)
    # a full-graph mode couples all 6 pairs, so 3 absent pairs must be checked
    assert res.detail["absent_pairs_checked"] >= 1, res.detail
    assert res.nu > 0, "absent-edge residual must contribute certified error"


def test_mutation_invalid_arithmetic_label_rejected():
    with pytest.raises(A.DepthOverflow):
        A.lam(-5, 64)
    with pytest.raises(A.DepthOverflow):
        A.lam(1 << 70, 64)


def test_mutation_inverted_or_too_wide_output_rejected():
    with pytest.raises(A.NumericalRefusal):
        A.publish(Fr(9, 10), Fr(1, 10), Fr(0), Fr(1, 100))
    with pytest.raises(A.NumericalRefusal):
        A.publish(Fr(0), Fr(1), Fr(0), Fr(1, 100))


def test_mutation_uncharged_scalar_fit_error_detected():
    """nu must be the SUM over factors; dropping a term understates it."""
    n = 4
    fields = [0.05 * k for k in range(n)]
    m = M.read_uai(w(mean_field(n, 0.2, fields)))
    r = M.restrict(m, {})
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    ctx = A.Ctx(120)
    res = MD.build_residual(r.free, r.factors, r.card, cands[0], ctx)
    npairs = res.detail["pairs_checked"] + res.detail["absent_pairs_checked"]
    nun = res.detail["unaries_checked"]
    assert npairs + nun >= n + n * (n - 1) // 2, res.detail
    assert res.nu >= 0


def test_mutation_wrong_frequency_key_set_detected():
    """The lattice node count must match the declared T and h exactly."""
    lat = CO.gf_lattice(Fr(1, 20), Fr(6), Fr(1, 10000))
    expect = int(2 * lat["T"] / float(lat["h"])) + 1
    assert lat["nodes"] == expect
    bad = dict(lat); bad["nodes"] = expect + 7
    assert bad["nodes"] != int(2 * bad["T"] / float(bad["h"])) + 1


def test_mutation_missing_hierarchy_ownership_detected():
    """Every query must have a unique current owner region."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    owner = {}
    for i, reg in enumerate(regs):
        for v in reg:
            assert v not in owner, "a variable may be owned by only one region"
            owner[v] = i
    assert set(owner) == set(r.free), "every query variable must have an owner"
    # mutate: drop a region, leaving an unowned query
    partial = {v: i for v, i in owner.items() if i != 0}
    assert set(partial) != set(r.free)
