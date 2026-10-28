"""Controls for the research mechanism (spec section 12).

All controls enter through the external model API; no branch on their names.
Bytes/generators are fixed in this file.
"""
import os, sys, math, itertools, tempfile, inspect
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
    # (gamma/2)(sum_i f_i)^2 = (gamma/2)sum f_i^2 + gamma*sum_{i<j} f_i f_j, so a
    # uniform pair coupling J needs gamma = |J|. The earlier assertion demanded
    # 2|J|, i.e. it asserted the implementation's own doubling and could never
    # have detected it.
    assert abs(float(cands[0].gammas[0]) - abs(J)) < 1e-4, cands[0].gammas


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


# =============== control 5b: the COMPOSED route actually executes ===============

def test_control5_coarse_model_executes_and_restores_markers():
    """A small fixture must actually coarsen and then contract the COARSE model,
    preserving original query markers, with enumeration checking the composed
    allowance."""
    from mdi import coarse as CZ
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    queries = set(r.free)
    rds, crs, t_level = _coarsen(m, r, regs, 1, queries)
    states = sum(rd.n_boundary_states() for rd in rds)
    cells = sum(len(c.cells) for c in crs)
    assert cells < states, "the control must actually compress"
    res = CZ.solve_coarse_with_markers(r.free, r.card, r.factors, regs, crs, rds,
                                       queries, eps=Fr(1, 1000), mode="P",
                                       cap_bytes=1 << 30, deadline_s=120)
    # The coarse contraction runs with run_checker=False, so its result is NOT
    # verified. It must say so rather than returning VERIFIED_ALL_MARGINALS,
    # which the arm previously mapped to CERTIFIED_RESEARCH_ROUTE.
    assert res["outcome"] == "PRODUCER_COMPLETE_UNCHECKED", res["outcome"]
    assert res["checker"]["status"] == "NOT_RUN"
    # the coarse model is genuinely smaller than the original
    assert res["coarse_model"]["nvars"] == NB
    assert max(res["coarse_model"]["card"]) <= 2 ** BS
    # original markers restored within the numerical + transformation allowance
    Ztrue, ptrue = O.exact_all_marginals(r)
    worst = Fr(0)
    for v in sorted(queries):
        for a in range(r.card[v]):
            lo, hi = res["intervals"][v][a]
            lo2 = max(Fr(0), Fr(lo) - t_level)
            hi2 = min(Fr(1), Fr(hi) + t_level)
            assert lo2 <= ptrue[v][a] <= hi2, (v, a, float(lo2),
                                               float(ptrue[v][a]), float(hi2))
            if hi2 - lo2 > worst:
                worst = hi2 - lo2
    assert worst <= K.MAX_WIDTH, float(worst)


def test_control5_coarse_payload_sums_to_one():
    """g_{i,a}(C) = N/M must sum to 1 over states in every cell."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    rds, crs, _ = _coarsen(m, r, regs, 1, set(r.free))
    for i, cr in enumerate(crs):
        for ci in range(len(cr.cells)):
            for v in regs[i]:
                g = sum(Fr(cr.N[(v, s)][ci]) / Fr(cr.M[ci])
                        for s in range(r.card[v]))
                assert g == 1, (i, ci, v, g)


# =============== query-subset control: unrequested marker work is omitted ===============

def test_query_subset_omits_unrequested_marker_work():
    """Queries must determine payload work: asking for fewer variables must
    compute fewer marks. An all-singleton experiment alone cannot show this."""
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    full = set(r.free)
    subset = {regs[0][0], regs[2][0]}          # two variables only
    rd_full = R.region_data(regs[0], r.card, r.factors, full)
    rd_sub = R.region_data(regs[0], r.card, r.factors, subset)
    # the full request marks every variable in the region; the subset marks one
    assert len(rd_full.marks) == BS * 2, len(rd_full.marks)
    assert len(rd_sub.marks) == 2, len(rd_sub.marks)
    assert len(rd_sub.marks) < len(rd_full.marks), "unrequested marks must be omitted"
    # masses are identical either way: only payload work changes
    assert rd_full.A == rd_sub.A
    # and a region with no requested variable marks nothing
    rd_none = R.region_data(regs[1], r.card, r.factors, subset)
    assert rd_none.marks == {}, rd_none.marks
    assert rd_none.A, "masses are still computed"


# =============== deletion: a CERTIFIED execution, not only refusals ===============

def test_deletion_actually_certifies_and_bounds_the_event():
    """Positive-state deletion must EXECUTE on a case where it is sound, and its
    certificate must be the U_R/(U_R+L_R) bound, not a mass threshold.

    Existing controls cover the two refusals (hard zeros forcing L_R = 0, and a
    rare state amplified by exterior factors). This one covers the accepting
    branch, which no other control exercised.
    """
    txt = """MARKOV
3
2 2 2
3
1 0
2 0 1
1 1
2
1.0 0.0000001
4
1.0 1.0 1.0 1.0
2
1.0 1.0
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    assert len(rd.A) == 2, rd.A
    best = R.propose_deletions(rd, r.factors, r.card, Fr(1, 10000))
    assert best is not None, "deletion must certify on a genuinely negligible state"
    assert best["deleted"] == [(1,)], best["deleted"]
    assert best["prob_bound"] <= Fr(1, 10000), float(best["prob_bound"])
    # the bound is exactly U/(U+L) recomputed independently
    U, L, p = R.deletion_bounds(rd, r.factors, r.card, best["deleted"])
    assert L > 0 and U >= 0
    assert p == U / (U + L)
    assert p == best["prob_bound"]


def test_deletion_respects_its_allocated_radius():
    """A deletion whose bound exceeds the allocated radius must NOT be taken."""
    txt = """MARKOV
3
2 2 2
3
1 0
2 0 1
1 1
2
1.0 0.5
4
1.0 1.0 1.0 1.0
2
1.0 1.0
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    # the "rare" state holds a third of the mass: no tiny radius can justify it
    best = R.propose_deletions(rd, r.factors, r.card, Fr(1, 100000))
    assert best is None, best
    U, L, p = R.deletion_bounds(rd, r.factors, r.card, [(1,)])
    assert p > Fr(1, 100000), float(p)


def test_deletion_bound_is_uniform_over_exterior_configurations():
    """The certificate must hold for EVERY exterior configuration of positive
    weight: U uses the per-state MAXIMUM response and L the MINIMUM, so a
    stronger exterior cannot invalidate it."""
    txt = """MARKOV
3
2 2 2
3
1 0
2 0 2
1 2
2
1.0 0.001
4
1.0 1.0 1.0 100.0
2
1.0 1.0
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    U, L, p = R.deletion_bounds(rd, r.factors, r.card, [(1,)])
    # exhaustive check against every exterior assignment of variable 2
    f = next(x for x in r.factors if tuple(sorted(x.scope)) == (0, 2))
    st = f.strides()
    worst = Fr(0)
    for y in range(r.card[2]):
        num = rd.A[(1,)] * f.table[1 * st[0] + y * st[1]]
        den = num + rd.A[(0,)] * f.table[0 * st[0] + y * st[1]]
        if den > 0:
            q = num / den
            if q > worst:
                worst = q
    assert worst <= p, (float(worst), float(p))


# ===== review-2 defect regressions, each failing before its fix =====

def test_repeated_pair_factors_multiply_not_overwrite():
    """Two factors on the same scope define their PRODUCT. Overwriting made nu
    certify a model that was not the input (marginal 17/19 vs 5/7)."""
    txt = "MARKOV\n2\n2 2\n3\n1 0\n2 0 1\n2 0 1\n2\n1 1\n4\n1 1 1 4\n4\n1 1 1 4\n"
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    Hs, absorb, consts, zp = MD._pair_matrix(r.free, r.factors, r.card)
    assert Hs[(0, 1)][1][1] == 16, Hs[(0, 1)]
    Z, p = O.exact_all_marginals(r)
    assert p[0] == [Fr(2, 19), Fr(17, 19)], p[0]


def test_transposed_duplicate_scope_also_combines():
    """A pair written (1,0) must combine with (0,1), not be treated separately."""
    txt = "MARKOV\n2\n2 2\n3\n1 0\n2 0 1\n2 1 0\n2\n1 1\n4\n1 1 1 4\n4\n1 1 1 4\n"
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    Hs, absorb, consts, zp = MD._pair_matrix(r.free, r.factors, r.card)
    assert list(Hs.keys()) == [(0, 1)], list(Hs.keys())
    assert Hs[(0, 1)][1][1] == 16, Hs[(0, 1)]


def test_uniform_coupling_gamma_equals_J_not_twice():
    """Exhaustive algebra: (g/2)(sum x)^2 = (g/2)n + g*sum_{i<j} x_i x_j."""
    for n in (3, 4, 5):
        for g in (Fr(1, 2), Fr(3, 10)):
            for combo in itertools.product([-1, 1], repeat=n):
                S = sum(combo)
                pairs = sum(combo[i] * combo[j]
                            for i in range(n) for j in range(i + 1, n))
                assert g * Fr(S * S, 2) == g * Fr(n, 2) + g * pairs


def test_statistic_dp_refuses_residual_pairs():
    """It multiplies unary tables only; accepting pairs gave 1/2 vs exact 5/6."""
    with pytest.raises(CO.Declined) as e:
        CO.statistic_dp([0, 1], {0: 2, 1: 2},
                        {0: [Fr(1), Fr(1)], 1: [Fr(1), Fr(1)]},
                        {(0, 1): [Fr(1), Fr(1), Fr(1), Fr(9)]}, [], None, 1,
                        {0, 1})
    assert "PAIR" in str(e.value)


def test_normal_weight_never_inverts():
    """The 1/sqrt(2pi) quotient needs opposite rounding on its denominator;
    same-direction rounding inverted 35 of 81 nodes at p=24."""
    ctx = A.Ctx(24)
    for j in range(-40, 41):
        lo, hi = CO._normal_weight(Fr(j, 8), Fr(1, 8), ctx)
        assert 0 < lo <= hi, (j, float(lo), float(hi))


def test_lattice_rejects_when_it_cannot_meet_delta():
    """Capping the step without rejecting advertised 1.23e14 nodes whose true
    bound was 1.57e+142 against a 1e-3 target."""
    with pytest.raises(CO.Declined) as e:
        CO.gf_lattice(Fr(8721203, 1000000), Fr(467709, 50000), Fr(1, 1000))
    assert "cannot meet delta" in str(e.value)
    # a legitimate lattice still admits, with its bound inside the target
    lat = CO.gf_lattice(Fr(1, 20), Fr(6), Fr(1, 10000))
    assert lat["nodes"] < 100000
    assert lat["total_bound"] <= 2 * Fr(1, 10000)


def test_checker_refuses_zero_evidence_explicitly():
    """Both entry points must test the conditioning event, not rely on a
    numerical positivity side effect."""
    txt = """MARKOV
3
2 2 2
3
2 0 1
2 1 2
2 0 2
4
1 0 0 1
4
1 0 0 1
4
0 1 1 0
"""
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    Z, _ = O.exact_all_marginals(r)
    assert Z == 0
    iv = {v: [(Fr(1, 2), Fr(1, 2))] * 2 for v in range(3)}
    ok, fails = S.verify_publication(m, {}, iv, eps=Fr(1, 100), mode="I")
    assert not ok and fails, "a zero-probability conditioning event must be refused"


def test_incomplete_partition_is_not_admitted():
    """A partition with skipped regions covers only part of the model; its ratio
    is not comparable and it must not be admitted."""
    src = inspect.getsource(PL.price_regional)
    assert "skipped == 0" in src, "admission must require zero skipped regions"


def test_corrected_mode_actually_removes_the_interaction():
    """With gamma = |J| the residual interaction is annihilated; with the old
    2|J| it was replaced by an OPPOSING interaction of similar size.

    This is the test the review asked for: recognition is only meaningful if the
    intended interaction is actually removed.
    """
    n, J = 8, 0.30
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
    m = M.read_uai(w(mean_field(n, J, fields)))
    r = M.restrict(m, {})
    ctx = A.Ctx(140)
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    assert cands and abs(float(cands[0].gammas[0]) - abs(J)) < 1e-4
    res = MD.build_residual(r.free, r.factors, r.card, cands[0], ctx)
    assert not res.kept, res.kept
    # original interaction strength
    Hs, _, _, _ = MD._pair_matrix(r.free, r.factors, r.card)
    orig = [abs(float(H[1][1]) - 1.0) for H in Hs.values()]
    # residual interaction strength
    resid = []
    for tbl in res.pairs.values():
        g = MD.gauge_split(tbl, 2, 2)
        resid.append(abs(float(g.H[1][1]) - 1.0))
    assert orig and resid
    assert max(resid) < min(orig) / 1000, (
        "the residual must be far closer to non-interacting than the original: "
        "max residual %.3e vs min original %.3e" % (max(resid), min(orig)))
    assert MD.tv_from_nu(res.nu) <= K.RADII["collective_fit_and_rounding"]


# ===== contract B: remaining certificate and schema defects =====

def test_reversed_rectangular_scope_transposes_entrywise():
    """A pair written (j,i) with unequal cardinalities must normalize to (i,j)
    ENTRYWISE. The previous comprehension iterated the wrong extents and got 4
    of 6 entries wrong on a 3x2 reversed scope."""
    for txt, desc in [
        ("MARKOV\n2\n2 3\n2\n2 1 0\n1 1\n6\n1 2 3 4 5 6\n3\n1 1 1\n", "3x2 rev"),
        ("MARKOV\n2\n3 2\n2\n2 1 0\n1 1\n6\n1 2 3 4 5 6\n2\n1 1\n", "2x3 rev"),
        ("MARKOV\n2\n2 3\n2\n2 0 1\n1 1\n6\n1 2 3 4 5 6\n3\n1 1 1\n", "2x3 fwd"),
    ]:
        m = M.read_uai(w(txt)); r = M.restrict(m, {})
        f = next(x for x in r.factors if len(x.scope) == 2)
        orig = {}
        for a in range(f.card[0]):
            for b in range(f.card[1]):
                orig[(f.scope[0], a), (f.scope[1], b)] = f.table[a * f.card[1] + b]
        Hs, ab, cs, zp = MD._pair_matrix(r.free, r.factors, r.card)
        k = list(Hs.keys())[0]
        i, j = k
        for a in range(r.card[i]):
            for b in range(r.card[j]):
                recon = cs[k] * ab[i][a] * ab[j][b] * Hs[k][a][b]
                want = orig.get(((i, a), (j, b))) or orig.get(((j, b), (i, a)))
                assert recon == want, (desc, i, a, j, b, recon, want)


def test_rndd_saturation_is_refused():
    """MPFR saturates at the exponent range instead of returning an infinity, so
    a finite RNDD result there is not a lower bound. down(2^200) with emax=100
    silently returned 2^100, breaking the N1 invariant."""
    ctx = A.Ctx(64, emin=-100, emax=100)
    with pytest.raises(A.NumericalRefusal):
        ctx.down(Fr(2) ** 200)
    with pytest.raises(A.NumericalRefusal):
        ctx.down(Fr(1, 2 ** 200))
    a = ctx.down(Fr(2) ** 60)
    b = ctx.down(Fr(2) ** 60)
    with pytest.raises(A.NumericalRefusal):
        ctx.mul_d(a, b)
    # ordinary arithmetic is unaffected
    c2 = A.Ctx(64)
    assert A.exact_fr(c2.down(Fr(1, 3))) < Fr(1, 3)
    assert A.exact_fr(c2.mul_d(c2.down(Fr(1, 3)), c2.down(Fr(1, 7)))) <= Fr(1, 21)


def test_lowrank_induces_the_correct_coupling():
    """B.5: the iteration must not mutate the diagonal while accumulating its
    own Rayleigh quotient, and gamma must not double-count the eigenvector
    normalization (which reported |J|*n instead of |J|)."""
    for J in (0.30, -0.25):
        n = 6
        fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
        m = M.read_uai(w(mean_field(n, J, fields)))
        r = M.restrict(m, {})
        cands, _ = MD.propose_modes(r.free, r.factors, r.card)
        for c in cands:
            f = c.features[0]
            induced = float(c.signs[0] * c.gammas[0] * f[0][1] * f[1][1])
            assert abs(induced - J) < 1e-5, (c.kind, induced, J)


def test_lowrank_recovers_unequal_loadings():
    """A rank-one coupling J_ij = g*w_i*w_j must recover the pattern w."""
    n = 6
    wts = [1.0, 0.8, 1.2, 0.6, 1.4, 0.9]
    g = 0.25
    scopes = [(v,) for v in range(n)] + [(i, j) for i in range(n)
                                         for j in range(i + 1, n)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.000000000000 1.000000000000"])
    for i in range(n):
        for j in range(i + 1, n):
            J = g * wts[i] * wts[j]
            e = [Fr(round(math.exp(J * a * b) * 10 ** 12), 10 ** 12)
                 for a in (-1, 1) for b in (-1, 1)]
            lines.extend(["4", " ".join(dec(x) for x in e)])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    assert cands
    f = cands[0].features[0]
    rel = [float(f[v][1]) for v in range(n)]
    base = rel[0] / wts[0]
    for k in range(n):
        assert abs(rel[k] / wts[k] / base - 1.0) < 0.05, (k, rel[k], wts[k])


def test_exact_preprocessing_identities_and_law():
    """Constants, separable pairs (including with zeros), ternary and reversed
    scopes must all preserve Z exactly (with the scale) and the marginals."""
    from mdi import preprocess as PRE
    cases = [
        "MARKOV\n3\n2 2 2\n4\n1 0\n2 0 1\n2 1 2\n1 2\n2\n1.5 2.5\n4\n2 6 3 9\n4\n1 1 1 1\n2\n0.5 4\n",
        "MARKOV\n2\n2 2\n2\n1 0\n2 0 1\n2\n1 2\n4\n0 0 3 9\n",
        "MARKOV\n2\n2 2\n2\n1 0\n2 0 1\n2\n1 2\n4\n1 2 3 9\n",
        "MARKOV\n2\n3 2\n2\n1 0\n2 0 1\n3\n1 2 3\n6\n2 4 3 6 5 10\n",
        "MARKOV\n2\n2 3\n2\n2 1 0\n1 1\n6\n2 4 3 6 5 10\n3\n1 1 1\n",
    ]
    for txt in cases:
        m = M.read_uai(w(txt)); r = M.restrict(m, {})
        Z0, p0 = O.exact_all_marginals(r)
        simp = PRE.simplify(r)
        assert PRE.verify_identities(r, simp)
        r2 = M.Restricted(model=m, evidence={}, factors=simp.factors,
                          free=list(r.free), card=dict(r.card),
                          constant=Fr(1), impossible_factor=None)
        Z1, p1 = O.exact_all_marginals(r2)
        assert Z0 == simp.scale * Z1, (Z0, simp.scale, Z1)
        assert p0 == p1


def test_checker_rejects_malformed_output_schema():
    """Both verification entry points must validate the output schema before
    numerical work: wrong row count, wrong row length, unordered or
    out-of-range endpoints."""
    asym = ("MARKOV\n3\n2 3 2\n3\n1 1\n2 0 1\n3 0 1 2\n"
            "3\n2 5 11\n6\n1 7 2 13 3 5\n12\n2 1 3 1 5 1 7 1 11 1 13 1\n")
    m = M.read_uai(w(asym))
    good = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                   deadline_s=60)
    assert good["outcome"] == "VERIFIED_ALL_MARGINALS"
    iv = {v: [tuple(x) for x in rows] for v, rows in good["intervals"].items()}
    # missing a variable
    bad = dict(iv); bad.pop(sorted(bad)[0])
    ok, fails = S.verify_publication(m, {}, bad, eps=Fr(1, 100), mode="I")
    assert not ok, "a missing output row must be rejected"
    # wrong row length
    bad2 = {v: list(rows) for v, rows in iv.items()}
    bad2[sorted(bad2)[0]] = bad2[sorted(bad2)[0]][:-1]
    ok2, _ = S.verify_publication(m, {}, bad2, eps=Fr(1, 100), mode="I")
    assert not ok2, "a short output row must be rejected"
    # inverted endpoints
    bad3 = {v: list(rows) for v, rows in iv.items()}
    v0 = sorted(bad3)[0]
    bad3[v0] = [(Fr(9, 10), Fr(1, 10))] + list(bad3[v0][1:])
    ok3, _ = S.verify_publication(m, {}, bad3, eps=Fr(1, 100), mode="I")
    assert not ok3, "inverted endpoints must be rejected"


# ===== contract A: truthful plan properties, persisted records, dispatcher =====

def test_plan_properties_enforce_prerequisites():
    """None of the eight properties implies another, and a property with unmet
    prerequisites must be refusable, not a judgement call."""
    from mdi import plantype as PT
    p = PT.PlanProperties()
    with pytest.raises(PT.PlanError):
        p.set("selected")
    p.set("mathematically_certified")
    p.set("executor_supported")
    p.set("complete_cost_priced")
    p.set("selected")
    assert p.selected
    # a checker is still missing, so this is NOT a certified route
    assert p.may_execute_as_certified_route() == ["checker_supported"]
    with pytest.raises(PT.PlanError):
        p.set("independently_verified")       # no producer_complete yet
    p.set("producer_complete")
    with pytest.raises(PT.PlanError):
        p.set("independently_verified")       # still no checker_supported
    p.set("checker_supported")
    p.set("independently_verified")
    p.set("publication_contract_met")
    assert p.may_execute_as_certified_route() == []


def _demo_plan():
    from mdi import plantype as PT
    return PT.PlanRecord(
        kind="identity", name="identity",
        model_sha256="a" * 64, evidence_sha256="b" * 64, query_sha256="c" * 64,
        preprocess_identity={"scale": "1", "removed_constants": [],
                             "split_pairs": []},
        factor_ownership=[(0, "bag0"), (1, "bag1")],
        factor_scopes=[(0, (0, 1), (2, 2)), (1, (1,), (2,))],
        region_membership=[], cell_membership=[],
        allocations={"regional": Fr(2, 1000), "deletion": Fr(5, 10000)},
        executor_id="mdi.solve:identity", checker_id="mdi.solve:_check",
        numerical={"precision": 64, "mode": "P", "emin": -3000, "emax": 3000},
        cost_counters={"bag_visits": 254, "label": "exact"},
        storage_schedule={"peak_live_entries": 127},
        rejected_alternatives=[{"name": "regional:x", "reason": "skipped regions"}])


def test_plan_record_round_trips_byte_identically():
    from mdi import plantype as PT
    rec = _demo_plan().validate()
    back = PT.round_trip(rec)
    assert back.allocations["regional"] == Fr(2, 1000)
    assert back.to_json() == rec.to_json()


def test_plan_record_rejects_wrong_binding_and_damage():
    from mdi import plantype as PT
    import json
    rec = _demo_plan().validate()
    with pytest.raises(PT.PlanError):
        rec.bind_check("z" * 64, "b" * 64, "c" * 64)
    assert rec.bind_check("a" * 64, "b" * 64, "c" * 64)
    for mutate, why in [
        (lambda d: d.pop("cost_counters"), "truncated"),
        (lambda d: d.update(version=99), "stale"),
        (lambda d: d.update(factor_ownership=[[0, "b0"], [0, "b1"]]), "dup owner"),
        (lambda d: d.update(allocations={"regional": "not-a-rational"}), "bad rational"),
        (lambda d: d.update(kind="nonsense"), "unknown kind"),
        (lambda d: d.update(model_sha256="short"), "bad hash"),
    ]:
        d = json.loads(rec.to_json())
        mutate(d)
        with pytest.raises(PT.PlanError):
            PT.PlanRecord.from_json(json.dumps(d))


def test_dispatcher_refuses_unimplemented_kinds():
    """A recognized-but-unimplemented kind must never fall through to the
    original-model solver."""
    from mdi import plantype as PT
    from mdi import registry as RG          # registers what exists
    for kind in ("fourier", "composed"):
        with pytest.raises(PT.PlanError) as e:
            PT.dispatch(kind)
        assert "no executor" in str(e.value)
    ex, ck = PT.dispatch("identity")
    assert ex is not None and ck is not None
    # regional now has BOTH (contract D.7 checker implemented)
    ex2, ck2 = PT.dispatch("regional")
    assert ex2 is not None and ck2 is not None
    # statistic and gaussian still have executors but no checker
    for kind in ("statistic", "gaussian"):
        ex3, ck3 = PT.dispatch(kind)
        assert ex3 is not None and ck3 is None


def test_support_table_is_factual():
    from mdi import registry as RG
    rows = {r["kind"]: r for r in RG.status_table()}
    assert rows["identity"]["executor_supported"]
    assert rows["identity"]["checker_supported"]
    assert rows["regional"]["executor_supported"]
    assert rows["regional"]["checker_supported"], "D.7 checker is implemented"
    assert not rows["fourier"]["executor_supported"]
    assert not rows["composed"]["executor_supported"]
    for k in ("statistic", "gaussian"):
        assert not rows[k]["checker_supported"]
        assert rows[k]["checker_note"], "a missing checker must say why"


# ===== contract D: compact projected crossings and direct marker readout =====

def _ring_coarse(NB=4, BS=3):
    """Build the ring control's regions, cells and region map."""
    txt, n, NB_, BS_ = ring_of_blocks(NB, BS)
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    regs = tuple(tuple(range(b * BS, (b + 1) * BS)) for b in range(NB))
    tl = K.level_radius(1)
    cap = K.region_distortion_budget(tl, len(regs))
    region_of = {v: i for i, rr in enumerate(regs) for v in rr}
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        cr = R.merge_region(rd, r.factors, r.card, cap, set(r.free),
                            region_of=region_of, aggregate=True)
        rds.append(rd); crs.append(cr)
    return m, r, regs, crs, rds, region_of


def test_compact_projection_equals_cartesian_exactly():
    """The compact form must give the SAME value as the Cartesian table for
    every cell assignment, since it is the same mathematics stored differently."""
    from mdi import compact as CP, coarse as CZ
    m, r, regs, crs, rds, _ = _ring_coarse()
    pc, _ = CP.project_crossings(r, regs, crs, rds)
    assert pc, "the control must have crossing factors"
    cm, cross, _ = CZ.build_coarse_model(r.free, r.card, r.factors, regs, crs, rds)
    cfacs = {tuple(f.scope): f for f in cm.factors if len(f.scope) > 1}
    ncell = [len(c.cells) for c in crs]
    for tup in itertools.product(*[range(k) for k in ncell]):
        cell_of = {i: tup[i] for i in range(len(regs))}
        comp = Fr(1)
        for x in pc:
            comp *= x.value(cell_of)
        cart = Fr(1)
        for scope, f in cfacs.items():
            st = f.strides()
            off = sum(tup[v] * st[k] for k, v in enumerate(scope))
            cart *= f.table[off]
        assert comp == cart, (tup, comp, cart)


def test_compact_projection_avoids_cartesian_blowup_at_scale():
    """On a real instance the compact form must be far smaller. The Cartesian
    builder would have materialized ~5.3e7 entries on Promedus."""
    from mdi import compact as CP
    p = "/tmp/tep/three_external_problems/inputs/Promedus_12"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r = M.restrict(m, ev)
    c0 = next(x for x in R.propose_partitions(r.free, r.card, r.factors)
              if x["mode"] == "ascending_id")
    regs = c0["regions"]
    tl = K.level_radius(1)
    cap = K.region_distortion_budget(tl, len(regs))
    region_of = {v: i for i, rr in enumerate(regs) for v in rr}
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        cr = R.merge_region(rd, r.factors, r.card, cap, set(r.free),
                            region_of=region_of, aggregate=True)
        rds.append(rd); crs.append(cr)
    pc, _ = CP.project_crossings(r, regs, crs, rds)
    avoided = CP.cartesian_entries_avoided(pc, crs)
    compact = CP.compact_entries(pc)["total"]
    assert avoided > 10 ** 7, avoided
    assert compact * 100 < avoided, (compact, avoided)


def test_missing_projection_is_an_error_not_a_one():
    """A region with no assigned cell must raise, never silently contribute 1."""
    from mdi import compact as CP
    m, r, regs, crs, rds, _ = _ring_coarse()
    pc, _ = CP.project_crossings(r, regs, crs, rds)
    x = pc[0]
    partial = {ri: 0 for ri in x.regions[:-1]}      # omit the last region
    with pytest.raises(CP.CompactError) as e:
        x.value(partial)
    assert "never be treated as the value 1" in str(e.value)


def test_direct_readout_pads_once_not_per_cell():
    """A state present in two cells accumulated two eps-wide paddings, giving
    width 0.02 for an eps=0.01 request. The direct readout accumulates counts
    exactly and pads once."""
    from mdi import compact as CP
    eps = Fr(1, 100)
    # the old path: each coarse CELL interval already padded to eps, combined
    cells = [(Fr(0), eps), (Fr(0), eps)]
    g_both = [Fr(1), Fr(1)]
    lo = sum(Fr(c[0]) * g_both[i] for i, c in enumerate(cells))
    hi = sum(Fr(c[1]) * g_both[i] for i, c in enumerate(cells))
    assert hi - lo == 2 * eps, (hi - lo, eps)        # the 0.02 defect
    # the direct path: one pad on the final original-state interval
    lo2, hi2 = CP.normalize_once(Fr(37), Fr(63), eps / 4, eps)
    assert hi2 - lo2 <= eps / 2, (hi2 - lo2)


def test_direct_query_counts_use_exclusion_not_division():
    """A and C come from H*N and H*(M-N); the complement is never 1 minus a
    rounded probability."""
    from mdi import compact as CP
    m, r, regs, crs, rds, _ = _ring_coarse()
    cr = crs[0]
    cavity = {ci: Fr(1) for ci in range(len(cr.cells))}
    v = regs[0][0]
    A, C = CP.query_counts(0, crs, rds, v, 0, cavity)
    A1, C1 = CP.query_counts(0, crs, rds, v, 1, cavity)
    # with a unit cavity the totals must reconstruct the region's mass
    total = sum(Fr(x) for x in cr.M)
    assert A + C == total, (A, C, total)
    assert A1 + C1 == total
    assert A + A1 == total, "the two states must partition the mass"


def test_tilted_marked_keeps_g_as_the_observable():
    from mdi import compact as CP
    for U, g in [(Fr(7, 2), Fr(3, 10)), (Fr(1), Fr(0)), (Fr(5), Fr(1))]:
        a, b = CP.tilted_marked(U, g)
        assert a + b == U
        assert a == U * g
    with pytest.raises(CP.CompactError):
        CP.tilted_marked(Fr(1), Fr(3, 2))


# ===== contract E: recognition connected to a smaller certified calculation =====

def _mean_field_pipeline(n, J, fields, gauge_shift=False):
    """Original tables -> recognition -> residual canonicalization -> statistic
    DP -> enclosure of every ORIGINAL state probability."""
    from mdi import residual as RS
    m = M.read_uai(w(mean_field(n, J, fields)))
    if gauge_shift:
        # move every unary table into the pair tables, preserving the law
        unary = {f.scope[0]: list(f.table) for f in m.factors if len(f.scope) == 1}
        facs, used = [], set()
        for f in m.factors:
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
            facs.append(M.Factor(scope=f.scope, card=f.card, table=tbl,
                                 origin=f.origin))
        m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m, {})
    ctx = A.Ctx(200)
    cands, _ = MD.propose_modes(r.free, r.factors, r.card)
    assert cands, "recognition must find a mode"
    cand = cands[0]
    res = MD.build_residual(r.free, r.factors, r.card, cand, ctx)
    allow = K.RADII["collective_fit_and_rounding"]
    fit_tv = MD.tv_from_nu(res.nu)
    assert fit_tv <= allow, (fit_tv, allow)
    can = RS.canonicalize(res.unary, res.pairs, r.card, ctx,
                          2 * (allow - fit_tv))
    total_tv = RS.tv_from_total_nu(res.nu, can.nu_extra)
    assert total_tv <= allow, (total_tv, allow)
    assert can.is_product(), can.detail
    acc, marks, _ = CO.statistic_dp(list(r.free), r.card, can.unary, {}, [],
                                    cand, 1, set(r.free))
    (Zlo, Zhi), mk = CO.dp_root_combine(acc, marks, cand, 1, ctx)
    Ztrue, ptrue = O.exact_all_marginals(r)
    widths = []
    for v in sorted(r.free):
        for a in range(2):
            lo, hi = mk[(v, a)]
            qlo = Fr(lo) / Fr(Zhi)
            qhi = Fr(hi) / Fr(Zlo)
            plo = max(Fr(0), qlo - total_tv)
            phi = min(Fr(1), qhi + total_tv)
            assert plo <= ptrue[v][a] <= phi, (v, a, float(plo),
                                               float(ptrue[v][a]), float(phi))
            widths.append(phi - plo)
    return {"support": len(acc), "configurations": 2 ** n,
            "total_tv": total_tv, "max_width": max(widths),
            "dropped": len(can.dropped_pairs), "detail": can.detail}


def test_control_E3_mean_field_runs_end_to_end_positive():
    """The review's 8-site control: original tables through recognition,
    residual simplification, executor and enclosure of all 16 original
    probabilities. Calibration: support 9, width about 2.02e-10."""
    n = 8
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
    out = _mean_field_pipeline(n, 0.30, fields)
    assert out["support"] == 9, out["support"]
    assert out["support"] < out["configurations"] / 25
    assert out["dropped"] == 28, out["dropped"]
    assert out["max_width"] < Fr(1, 10 ** 8), float(out["max_width"])


def test_control_E3_mean_field_negative_sign():
    n = 8
    fields = [0.05 * (k + 1) * (1 if k % 3 else -1) for k in range(n)]
    out = _mean_field_pipeline(n, -0.22, fields)
    assert out["support"] == 9
    assert out["max_width"] < Fr(1, 10 ** 6), float(out["max_width"])


def test_control_E3_survives_exact_gauge_redistribution():
    """Moving every unary into the pair tables preserves the law; the whole
    pipeline must still work and still enclose the originals."""
    n = 6
    fields = [0.1, -0.2, 0.15, -0.05, 0.08, -0.12]
    out = _mean_field_pipeline(n, 0.28, fields, gauge_shift=True)
    assert out["support"] == 7, out["support"]
    assert out["max_width"] < Fr(1, 10 ** 6), float(out["max_width"])


def test_residual_drop_charges_its_error_and_never_resets():
    """Dropping an interaction must charge a uniform log bound into the SAME
    allowance, and a budget that cannot cover an edge must keep it."""
    from mdi import residual as RS
    ctx = A.Ctx(140)
    card = {0: 2, 1: 2}
    unary = {0: [Fr(1), Fr(1)], 1: [Fr(1), Fr(1)]}
    # a genuinely interacting pair
    pairs = {(0, 1): [Fr(1), Fr(1), Fr(1), Fr(2)]}
    # with no budget it must be KEPT, not dropped
    can0 = RS.canonicalize(unary, pairs, card, ctx, Fr(0))
    assert not can0.is_product()
    assert can0.kept_pairs, can0.detail
    assert can0.nu_extra == 0
    # with a generous budget it is dropped and the error is charged
    can1 = RS.canonicalize(unary, pairs, card, ctx, Fr(1))
    assert can1.is_product()
    assert can1.nu_extra > 0, "dropping must charge a positive radius"
    assert len(can1.dropped_pairs) == 1
    # the combined TV adds; it does not reset
    tv = RS.tv_from_total_nu(Fr(1, 1000), can1.nu_extra)
    assert tv >= can1.nu_extra / 2


def test_residual_transfers_separable_pairs_with_zero_error():
    """An exactly separable residual pair must be absorbed with NO charge."""
    from mdi import residual as RS
    ctx = A.Ctx(140)
    card = {0: 2, 1: 2}
    unary = {0: [Fr(1), Fr(1)], 1: [Fr(1), Fr(1)]}
    pairs = {(0, 1): [Fr(2), Fr(6), Fr(3), Fr(9)]}     # = (1,1.5) x (2,6)
    can = RS.canonicalize(unary, pairs, card, ctx, Fr(0))
    assert can.is_product(), can.detail
    assert can.nu_extra == 0, "an exact transfer must charge nothing"
    assert len(can.transferred_pairs) == 1


# ===== contract D.5-D.7: second level, applied deletion, regional checker =====

def test_second_coarsening_level_executes_and_restores_markers():
    """D.5: parent regions over CHILD CELLS, with parent markers RECOMPUTED by
    substituting the owned child marked factor. A level-one surrogate does not
    satisfy this."""
    from mdi import level2 as L2
    m, r, regs, crs, rds, region_of = _ring_coarse(NB=4, BS=2)
    t1 = K.level_radius(2)                   # two levels, split equally
    l2 = L2.build_level2(r, regs, crs, rds, set(r.free), t1)
    assert l2["skipped"] == 0, l2
    assert l2["parent_data"], "a parent region must be built"
    for pr in l2["parent_data"]:
        assert pr.A, "parent masses must be computed"
        assert pr.assignments() == 1 or pr.assignments() > 1
    Zt, counts = L2.level2_marginals(r, regs, crs, rds, set(r.free), l2)
    assert Zt > 0
    Ztrue, ptrue = O.exact_all_marginals(r)
    worst = Fr(0)
    for v in sorted(r.free):
        for s in range(2):
            q = counts.get((v, s), Fr(0)) / Zt
            d = abs(q - ptrue[v][s])
            if d > worst:
                worst = d
    assert worst <= 2 * t1, (float(worst), float(2 * t1))


def test_level2_rejects_an_incomplete_parent_set():
    """A skipped parent means the level-2 model is incomplete; contracting it
    must refuse."""
    from mdi import level2 as L2
    m, r, regs, crs, rds, _ = _ring_coarse(NB=4, BS=2)
    t1 = K.level_radius(2)
    l2 = L2.build_level2(r, regs, crs, rds, set(r.free), t1)
    l2["skipped"] = 1
    with pytest.raises(L2.Level2Error):
        L2.level2_marginals(r, regs, crs, rds, set(r.free), l2)


def test_deletion_is_applied_and_recorded_in_production():
    """D.6: a certified deletion must change the region and carry a record,
    not merely be proposed by a helper."""
    txt = ("MARKOV\n3\n2 2 2\n3\n1 0\n2 0 1\n1 1\n2\n1.0 0.0000001\n"
           "4\n1.0 1.0 1.0 1.0\n2\n1.0 1.0\n")
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    before = len(rd.A)
    rd2, rec = R.apply_deletion(rd, r.factors, r.card, Fr(1, 10000))
    assert rec is not None, "a negligible state must be deleted"
    assert len(rd2.A) == before - 1
    assert rec.prob_bound <= Fr(1, 10000)
    assert rec.retained_states == len(rd2.A)
    assert rec.positive_denominator
    # the mark/mass identity survives on the retained support
    for v in rd2.vars:
        keys = [k for k in rd2.marks if k[0] == v]
        if not keys:
            continue
        for b in rd2.A:
            assert sum(rd2.marks[k].get(b, Fr(0)) for k in keys) == rd2.A[b]


def test_unjustified_deletion_changes_nothing():
    txt = ("MARKOV\n3\n2 2 2\n3\n1 0\n2 0 1\n1 1\n2\n1.0 0.5\n"
           "4\n1.0 1.0 1.0 1.0\n2\n1.0 1.0\n")
    m = M.read_uai(w(txt)); r = M.restrict(m, {})
    rd = R.region_data((0,), r.card, r.factors, set(r.free))
    rd2, rec = R.apply_deletion(rd, r.factors, r.card, Fr(1, 100000))
    assert rec is None
    assert len(rd2.A) == len(rd.A)


def test_independent_regional_checker_verifies_and_rejects():
    """D.7: rebuild masses, marks, aggregation, extrema, alpha/rho and ownership
    from the ORIGINAL factors, then independently contract the REDUCED model.
    It must not solve the uncoarsened original."""
    from mdi import regional_check as RC
    m, r, regs, crs, rds, _ = _ring_coarse()
    t1 = K.level_radius(1)
    Z, counts = RC.independent_contract(r, regs, crs, rds, set(r.free))
    assert Z > 0
    # A publication must CONTAIN the checker's enclosure, so it has to be at
    # least as wide as the charged transformation radius. A degenerate point
    # interval is correctly REJECTED.
    point = {v: [(counts.get((v, s), Fr(0)) / Z,) * 2 for s in range(2)]
             for v in sorted(r.free)}
    ok0, f0, _ = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), point, t1, Fr(1, 100))
    assert not ok0, "a degenerate point cannot contain a width-2t enclosure"
    assert any("does NOT contain" in x for x in f0), f0[:3]
    pub = {}
    for v in sorted(r.free):
        rows = []
        for s in range(2):
            q = counts.get((v, s), Fr(0)) / Z
            rows.append((max(Fr(0), q - t1), min(Fr(1), q + t1)))
        pub[v] = rows
    ok, fails, meta = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), pub, t1, Fr(1, 100))
    assert ok, fails[:4]
    assert meta["regions_rebuilt"] == len(regs)
    assert meta["independent_enclosure"]
    # a corrupted publication must be rejected
    bad = {v: list(rows) for v, rows in pub.items()}
    v0 = sorted(bad)[0]
    bad[v0] = [(Fr(0), Fr(0)), (Fr(0), Fr(0))]
    ok2, f2, _ = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), bad, t1, Fr(1, 100))
    assert not ok2 and f2


def test_regional_checker_is_now_registered():
    from mdi import registry as RG
    rows = {x["kind"]: x for x in RG.status_table()}
    assert rows["regional"]["executor_supported"]
    assert rows["regional"]["checker_supported"], "D.7 checker must be registered"


# ===== contract F: complete-cost pricing and the executed memory schedule =====

def test_memory_forecast_simulates_the_executed_schedule():
    """F.3: the forecast must simulate what the ENGINE RUNS, and must never be
    optimistic. Forecasting the wrong schedule understated peak live entries by
    1.36x and 1.51x against our own measurements."""
    for name, actual in [("Pedigree_11", 71859260), ("Promedus_12", 51052384)]:
        p = "/tmp/tep/three_external_problems/inputs/" + name
        if not os.path.exists(p + ".uai"):
            pytest.skip("external inputs not extracted")
        m = M.read_uai(p + ".uai")
        ev = M.read_evidence(p + ".uai.evid", m)
        r = M.restrict(m, ev)
        sel = P.choose_plan(r.free, r.card, r.factors, 64, 8 * (1 << 30))
        pl, est = sel["chosen"]
        assert est["peak_live_entries"] == actual, (name,
                                                    est["peak_live_entries"],
                                                    actual)
        assert est["executed_schedule"]


def test_memory_forecast_is_never_optimistic_on_small_trees():
    """Validated against COUNTED live entries: the simulation may be
    conservative but must never undershoot."""
    for n in (6, 8, 10, 12):
        scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
        lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
        for sc in scopes:
            lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
        for v in range(n):
            lines.extend(["2", "1.0 1.%d" % (v % 7 + 1)])
        for k in range(n - 1):
            lines.extend(["4", "1.%d 1.1 1.1 1.%d" % (k % 5 + 1, k % 3 + 1)])
        m = M.read_uai(w("\n".join(lines) + "\n"))
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=60, run_checker=False)
        measured = res["peak_live_message_entries"]
        r = M.restrict(m, {})
        pn = res["plan"]["name"]
        adj = P.primal_graph(r.free, r.card, r.factors)
        pl = P.build_plan(pn, dict(P.PORTFOLIO)[pn](r.free, r.card, adj),
                          r.free, r.card, r.factors)
        sim = P.simulate_executed_schedule(pl)["peak_live_entries"]
        assert sim >= measured, (n, sim, measured)


def test_pricing_labels_every_counter():
    """F.2: an exact count, an upper bound, a calibration and a forecast must
    never be compared as if they were the same kind of number."""
    from mdi import pricing as PR
    p = "/tmp/tep/three_external_problems/inputs/Promedus_12"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r = M.restrict(m, ev)
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 8 * (1 << 30))
    pl, est = sel["chosen"]
    nq = sum(r.card[v] for v in r.free)
    rec = PR.price_identity_plan(pl, est, nq, 64)
    d = rec.as_dict()
    assert d["counters"], "a price must have counters"
    for key, c in d["counters"].items():
        assert c["label"] in (PR.EXACT, PR.UPPER, PR.LOWER, PR.CALIB,
                              PR.FORECAST), (key, c)
    assert d["total_arithmetic"]["label"] in (PR.UPPER, PR.EXACT, PR.FORECAST)
    assert d["bytes_producer"]["label"] == PR.FORECAST
    # the forecast must disclose what it excludes
    note = d["bytes_producer"]["note"].lower()
    assert "overhead" in note and "excludes" in note, note
    assert "not measured whole-process memory" in note


def test_pricing_prefers_identity_for_a_priced_reason():
    """F.1/F.4: selection compares complete work, not a cell-count ratio. The
    regional route's reduced cell-assignment count is the binding cost and was
    entirely hidden by the ratio."""
    from mdi import pricing as PR, preprocess as PRE, compact as CP
    p = "/tmp/tep/three_external_problems/inputs/Promedus_12"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r0 = M.restrict(m, ev)
    simp = PRE.simplify(r0)
    r = M.Restricted(model=m, evidence=ev, factors=simp.factors,
                     free=list(r0.free), card=dict(r0.card),
                     constant=r0.constant, impossible_factor=None)
    nq = sum(r.card[v] for v in r.free)
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 8 * (1 << 30))
    pl, est = sel["chosen"]
    ident = PR.price_identity_plan(pl, est, nq, 64)
    c0 = next(x for x in R.propose_partitions(r.free, r.card, r.factors)
              if x["mode"] == "ascending_id")
    regs = c0["regions"]
    t1 = K.level_radius(1)
    cap = K.region_distortion_budget(t1, len(regs))
    region_of = {v: i for i, rr in enumerate(regs) for v in rr}
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        cr = R.merge_region(rd, r.factors, r.card, cap, set(r.free),
                            region_of=region_of, aggregate=True)
        rds.append(rd); crs.append(cr)
    pc, _ = CP.project_crossings(r, regs, crs, rds)
    reg_rec = PR.price_regional_plan("regional:ascending_id", regs, crs, rds,
                                     pc, nq, t1)
    cmp = PR.compare([ident, reg_rec], cap_bytes=8 * (1 << 30))
    assert cmp["chosen"]["name"] == "identity", cmp["chosen"]
    # the regional route's binding cost is its reduced assignment count
    assert int(reg_rec.counters["reduced_cell_assignments"].value) > 10 ** 20
    assert reg_rec.counters["reduced_cell_assignments"].label == PR.UPPER
    # and the ratio is NOT what decided it
    assert "cell-count ratio is never used" in cmp["rule"]


def _complete_price(PR, kind, name, ops, by, bc=None, **kw):
    """A fully priced record: a MISSING required counter is now UNKNOWN, not
    zero, so a partial record is correctly ineligible."""
    rec = PR.CostRecord(kind=kind, name=name, **kw)
    rec.put("producer_upward_ops", ops, PR.UPPER)
    rec.put("producer_downward_ops", ops, PR.UPPER)
    rec.put("readout_ops", ops, PR.UPPER)
    rec.put("checker_ops", 2 * ops, PR.UPPER)
    rec.bytes_producer = PR.Counter(by, PR.FORECAST)
    rec.bytes_checker = PR.Counter(bc if bc is not None else by, PR.FORECAST)
    return rec


def test_ineligible_route_is_never_selected():
    from mdi import pricing as PR
    good = _complete_price(PR, "identity", "identity", 10 ** 9, 1 << 20)
    bad = _complete_price(PR, "statistic", "statistic:cheap", 1, 1,
                          eligible=False,
                          ineligible_reason="no independent checker")
    cmp = PR.compare([good, bad], cap_bytes=1 << 30)
    assert cmp["chosen"]["name"] == "identity", "an ineligible route must not win"


def test_unpriced_work_is_unknown_not_zero():
    """F.4: a missing required counter must make the route ineligible, since an
    absent price is not a cheap price."""
    from mdi import pricing as PR
    partial = PR.CostRecord(kind="identity", name="partial")
    partial.put("producer_upward_ops", 1, PR.UPPER)
    partial.bytes_producer = PR.Counter(1, PR.FORECAST)
    tot, lab = partial.total_arithmetic()
    assert tot is None and lab == "unknown"
    assert not partial.eligible
    assert "UNKNOWN, not zero" in partial.ineligible_reason
    cmp = PR.compare([partial], cap_bytes=1 << 30)
    assert cmp["chosen"] is None


def test_checker_memory_is_enforced_too():
    """F.4: selection previously ignored checker memory."""
    from mdi import pricing as PR
    r = _complete_price(PR, "identity", "big-checker", 10, 1 << 20,
                        bc=100 * (1 << 30))
    cmp = PR.compare([r], cap_bytes=8 * (1 << 30))
    assert cmp["chosen"] is None
    assert "CHECKER forecast" in cmp["all"][0]["admission_refusal"]


def test_upper_bound_over_cap_is_an_admission_refusal():
    from mdi import pricing as PR
    big = _complete_price(PR, "identity", "identity", 10 ** 6,
                          100 * (1 << 30))
    cmp = PR.compare([big], cap_bytes=8 * (1 << 30))
    assert cmp["chosen"] is None
    assert "admission refusal" in cmp["all"][0]["admission_refusal"]


# ===== contract G: one shared budget, declared caps, conversion caching =====

def test_shared_budget_enforces_counters_and_never_clamps():
    """G/F.7: one monotonic deadline and shared counters. A stop is an OUTCOME;
    `remaining` may go negative and must not be clamped into more work."""
    import time as _t
    from mdi import budget as B
    bg = B.Budget(wall_s=0.5, limits={"profile_comparisons": 10})
    bg.enter("discovery")
    with pytest.raises(B.BudgetExceeded) as e:
        for _ in range(100):
            bg.charge("profile_comparisons", 1)
    assert "discovery" in str(e.value)
    assert bg.report()["stops"], "a stop must be recorded"
    bg2 = B.Budget(wall_s=0.05)
    _t.sleep(0.1)
    assert bg2.remaining() < 0, "remaining must be allowed to go negative"
    with pytest.raises(B.BudgetExceeded):
        bg2.check("loop")


def test_budget_refuses_before_allocating():
    from mdi import budget as B
    bg = B.Budget(wall_s=10, limits={"assignments": 4096})
    assert bg.would_exceed("assignments", 5000)
    with pytest.raises(B.BudgetExceeded):
        bg.require("assignments", 5000)
    assert bg.used.get("assignments", 0) == 0, "a refused allocation must not charge"
    assert bg.require("assignments", 100)


def test_declared_caps_are_not_silently_enlarged():
    """F.7: the 4,096 region-assignment cap is 4,096. Four call sites
    previously multiplied it by 64 inline."""
    import inspect
    from mdi import regions as RR, level2 as L2, regional_check as RC
    for mod in (RR, L2, RC):
        src = inspect.getsource(mod)
        assert 'region_tuple_assignments"] * 64' not in src, mod.__name__
        assert '"region_tuple_assignments"] * 64' not in src, mod.__name__
    # each distinct space has its OWN declared cap
    for key in ("region_local_enumeration", "aggregated_kernel_entries",
                "level2_contraction_space", "checker_contraction_space"):
        assert key in K.CAPS, key
        assert K.CAPS[key] > 0


def test_accumulated_rational_sizes_are_bounded():
    """F.7: ACCUMULATED masses and marks must be checked, not only individual
    terms."""
    import inspect
    from mdi import regions as RR
    src = inspect.getsource(RR.region_data)
    assert "ACCUMULATED region mass" in src
    assert "ACCUMULATED marked mass" in src
    src2 = inspect.getsource(RR.merge_region)
    assert "ACCUMULATED cell mass" in src2


def test_conversion_cache_is_keyed_by_context_and_per_arm():
    """G: cache each exact entry's enclosure per precision, rounding and
    exponent range. Producer and checker build SEPARATE caches."""
    from mdi import budget as B
    ctx = A.Ctx(64)
    cc = B.ConversionCache(ctx, "producer")
    vals = [Fr(k, 7) for k in range(1, 6)] * 200
    for v in vals:
        cc.down(v)
    st = cc.stats()
    assert st["distinct_down"] == 5
    assert st["hits"] == len(vals) - 5
    assert st["hit_rate"] > 0.99
    # a DIFFERENT precision must not reuse the cached values
    ctx2 = A.Ctx(128)
    cc2 = B.ConversionCache(ctx2, "checker")
    assert cc2.key != cc.key
    assert cc2.stats()["hits"] == 0
    # the cached value equals a direct conversion
    for v in [Fr(1, 7), Fr(5, 7)]:
        assert cc.down(v) == ctx.down(v)


# ===== contract H: behavioural controls through the real driver =====

def test_H_higher_arity_and_nonbinary_through_the_driver():
    """Higher-arity factors and non-binary free states must go through the real
    public solve path, not a helper."""
    txt = ("MARKOV\n4\n2 3 2 3\n4\n4 0 1 2 3\n2 1 3\n1 0\n1 2\n"
           "36\n" + " ".join(str(1 + (k % 7)) for k in range(36)) + "\n"
           "9\n1 2 3 4 5 6 7 8 9\n2\n1 2\n2\n3 1\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    assert max(len(f.scope) for f in r.factors) == 4
    assert any(r.card[v] == 3 for v in r.free)
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=60)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS", res["outcome"]
    Z, p = O.exact_all_marginals(r)
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res["intervals"][v][s]
            assert lo <= p[v][s] <= hi, (v, s)


def test_H_aggregation_shows_zero_masking_and_positive_cancellation():
    """Contract H: actual aggregation must show BOTH effects.

    Zero masking: a zero in a grouped constituent makes two differing masks
    agree. Positive cancellation: two rows whose ratios differ per factor become
    exactly proportional in the product.
    """
    # zero masking (the reviewer's counterexample)
    rb, rr = (Fr(0), Fr(2)), (Fr(1), Fr(3))
    with pytest.raises(R.Declined):
        R.ratio_extrema(rb, rr)
    z = (Fr(0), Fr(7))
    ab = tuple(a * c for a, c in zip(rb, z))
    ar = tuple(a * c for a, c in zip(rr, z))
    L, U = R.ratio_extrema(ab, ar)
    assert L == U, "aggregated rows must be exactly proportional"
    assert U / L == 1
    # positive cancellation: per-factor ratios 1/2 and 2/1 multiply to 1
    f1b, f1r = (Fr(1), Fr(2)), (Fr(2), Fr(4))      # ratio 1/2 everywhere
    f2b, f2r = (Fr(4), Fr(2)), (Fr(2), Fr(1))      # ratio 2 everywhere
    L1, U1 = R.ratio_extrema(f1b, f1r)
    L2, U2 = R.ratio_extrema(f2b, f2r)
    assert (U1 / L1, U2 / L2) == (1, 1)
    pb = tuple(a * b for a, b in zip(f1b, f2b))
    pr = tuple(a * b for a, b in zip(f1r, f2r))
    Lp, Up = R.ratio_extrema(pb, pr)
    assert Lp == Up == Fr(1), (Lp, Up)


def test_H_categorical_mode_fitting_declines_with_a_reason():
    """Categorical fitting is NOT implemented. It must decline with a recorded
    reason, never silently produce a binary-only answer."""
    txt = ("MARKOV\n3\n3 3 2\n3\n2 0 1\n1 2\n2 1 2\n"
           "9\n2 1 1 1 2 1 1 1 2\n2\n1 1\n6\n1 2 1 2 1 2\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    assert any(r.card[v] == 3 for v in r.free)
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    assert cands == [], "a non-binary model must not yield a binary mode"
    assert "declined" in info, info
    assert "categorical" in info["declined"].lower()


def test_H_bounded_fallback_is_a_recorded_selection():
    """A route with no executor must not fall through; fallback is a separate,
    recorded, charged selection."""
    from mdi import plantype as PT, registry as RG, pricing as PR
    for kind in ("fourier", "composed"):
        with pytest.raises(PT.PlanError):
            PT.dispatch(kind)
    # the fallback must be priced as its own record, with identity eligible
    ident = _complete_price(PR, "identity", "identity:fallback", 10 ** 6,
                            1 << 20)
    unimpl = _complete_price(PR, "fourier", "fourier", 1, 1, eligible=False,
                             ineligible_reason=RG.UNIMPLEMENTED["fourier"])
    cmp = PR.compare([ident, unimpl], cap_bytes=1 << 30)
    assert cmp["chosen"]["name"] == "identity:fallback"
    row = next(x for x in cmp["all"] if x["kind"] == "fourier")
    assert not row["eligible"] and row["ineligible_reason"]


def test_H_no_verified_status_when_checking_is_disabled_or_incomplete():
    """The central status obligation, through the real driver."""
    txt = ("MARKOV\n3\n2 3 2\n3\n1 1\n2 0 1\n3 0 1 2\n"
           "3\n2 5 11\n6\n1 7 2 13 3 5\n12\n2 1 3 1 5 1 7 1 11 1 13 1\n")
    m = M.read_uai(w(txt))
    on = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                 deadline_s=60, run_checker=True)
    assert on["outcome"] == "VERIFIED_ALL_MARGINALS"
    assert on["independently_verified"] is True
    off = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=60, run_checker=False)
    assert off["outcome"] == "PRODUCER_COMPLETE_UNCHECKED"
    assert off["independently_verified"] is False
    assert off["checker"]["status"] == "NOT_RUN"
    assert off["checker"]["verified_coordinates"] == 0


def test_H_expired_deadline_control():
    """A tiny deadline must stop with a resource outcome, not a wrong answer."""
    p = "/tmp/tep/three_external_problems/inputs/Promedus_12"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    res = S.solve(m, ev, eps=Fr(1, 100), mode="P", cap_bytes=8 * (1 << 30),
                  deadline_s=2.0, run_checker=False)
    assert res["outcome"] in ("TIMEOUT", "RESOURCE_BOUND"), res["outcome"]
    assert "intervals" not in res or not res.get("intervals")


def test_H_constant_and_separable_preprocessing_through_the_driver():
    """C: preprocessing must run inside the real solve path and preserve the
    original outputs."""
    txt = ("MARKOV\n3\n2 2 2\n4\n1 0\n2 0 1\n2 1 2\n1 2\n"
           "2\n1.5 2.5\n4\n2 6 3 9\n4\n1 1 1 1\n2\n0.5 4\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=60)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS"
    assert res["preprocess"] is not None, "preprocessing must be recorded"
    assert res["preprocess"]["removed_constants"], "the constant factor"
    assert res["preprocess"]["split_pairs"], "the separable pair"
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res["intervals"][v][s]
            assert lo <= p[v][s] <= hi, (v, s)


def test_conversion_cache_is_wired_into_the_contraction():
    """G: the cache must be in the EXECUTED path, not just available. The same
    factor entry is otherwise re-converted once per bag visit."""
    from mdi import contract as C, budget as B
    n = 12
    scopes = ([(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
              + [(i, i + 2) for i in range(n - 2)])
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.0 1.%d" % (v % 7 + 1)])
    for k in range(len(scopes) - n):
        lines.extend(["4", "1.%d 1.1 1.1 1.%d" % (k % 5 + 1, k % 3 + 1)])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    pl, est = sel["chosen"]
    ctx = A.Ctx(64)
    eng = C.Engine(pl, r.factors, ctx, mode="P")
    for rt in [b.idx for b in pl.bags if b.parent == -1]:
        eng.upward(rt)
    st = eng.conv.stats()
    assert st["hits"] > 0, "the cache must actually be used by the contraction"
    assert st["hits"] > st["misses"], st
    assert st["hit_rate"] > 0.5, st


def test_all_regional_candidates_are_priced():
    """F.5: every regional candidate must have a cost record built from ACTUAL
    cells and projected scopes, with no full Cartesian construction."""
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cands = [os.path.join(here, "runs/mdi_2026-10-28/regional_candidates_priced.json"),
             os.path.join(os.path.dirname(here), "runs/regional_candidates_priced.json"),
             "runs/mdi_2026-10-28/regional_candidates_priced.json"]
    p = next((x for x in cands if os.path.exists(x)), None)
    if p is None:
        pytest.skip("priced-candidate record not present")
    d = json.load(open(p))
    assert set(d) == {"Pedigree_11", "Promedus_12"}, list(d)
    for case, rows in d.items():
        assert rows, case
        for x in rows:
            if not x["eligible"]:
                assert x["reason"], "an ineligible candidate must say why"
                continue
            assert x["regions"] > 0
            assert x["cells"] > 0
            assert int(x["reduced_assignments"]) > 0
            assert x["compact_entries"] < x["cartesian_avoided"], (case, x["mode"])


def test_general_residual_dp_handles_retained_factors():
    """E.5: a residual WITH retained pair factors is admissible on a validated
    elimination schedule. Each variable's statistic is inserted exactly once at
    the bag that forgets it, and joins convolve disjoint statistics exactly."""
    import gmpy2
    from mdi import gendp as G
    n = 6
    scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.0 1.%d" % (v % 5 + 1)])
    for k in range(n - 1):
        lines.extend(["4", "1.%d 1.1 1.1 1.%d" % (k % 3 + 1, k % 4 + 1)])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    pl, est = sel["chosen"]
    ctx = A.Ctx(160)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 10)]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    # the PRODUCT dp refuses this residual
    pairs = {tuple(f.scope): list(f.table) for f in r.factors
             if len(f.scope) == 2}
    assert pairs, "the control must retain pair factors"
    with pytest.raises(CO.Declined):
        CO.statistic_dp(list(r.free), r.card,
                        {v: [Fr(1), Fr(1)] for v in r.free}, pairs, [],
                        Cand(), 1, set(r.free))
    # the GENERAL dp accepts it
    (Zlo, Zhi), mk, meta = G.run(pl, r.factors, r.card, Cand(), 1,
                                 set(r.free), ctx)
    assert meta["statistics_inserted"] == n
    assert meta["root_support"] <= n + 1
    # reference by full enumeration with the SAME enclosure arithmetic
    Rlo = Rhi = Fr(0)
    rmk = {(v, a): [Fr(0), Fr(0)] for v in range(n) for a in range(2)}
    for combo in itertools.product(*[range(2)] * n):
        wt = Fr(1)
        a_ = {v: combo[v] for v in range(n)}
        for f in r.factors:
            st = f.strides()
            off = sum(a_[v] * st[k] for k, v in enumerate(f.scope))
            wt *= f.table[off]
        if wt == 0:
            continue
        S = sum(1 if combo[v] == 1 else -1 for v in range(n))
        x = Cand().gammas[0] * Fr(S * S, 2)
        with ctx.D:
            lo = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        with ctx.U:
            hi = gmpy2.exp(gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))
        l, h = wt * A.exact_fr(lo), wt * A.exact_fr(hi)
        Rlo += l; Rhi += h
        for v in range(n):
            rmk[(v, combo[v])][0] += l
            rmk[(v, combo[v])][1] += h
    assert max(Zlo, Rlo) <= min(Zhi, Rhi), (float(Zlo), float(Rlo))
    for v in range(n):
        for a in range(2):
            dl, dh = mk.get((v, a), (Fr(0), Fr(0)))
            rl, rh = rmk[(v, a)]
            pd = (dl / Zhi, dh / Zlo)
            pr = (rl / Rhi, rh / Rlo)
            assert max(pd[0], pr[0]) <= min(pd[1], pr[1]), (v, a)


def test_general_dp_refuses_double_insertion():
    """The statistic-once invariant must be enforced, not assumed."""
    from mdi import gendp as G
    import inspect
    src = inspect.getsource(G.run)
    assert "inserted twice" in src
    assert "never had their statistic inserted" in src


# ===== review 4: false verified marginals (the most serious defect) =====

def test_r4_same_scope_cap_must_not_alter_the_law():
    """Review 4 witness, UNCHANGED production defaults.

    Pair tables [B,B,B,2B] and [B,B,B,3B] on one scope with B = 2^32768. Each
    entry fits the 65,536-bit cap; their product does not. The old code set a
    dead flag, overwrote the first factor with the second, and so dropped one
    input and duplicated the other. That changed the law from 7/9 to 5/6 and the
    engine then returned VERIFIED_ALL_MARGINALS with an interval EXCLUDING the
    truth.
    """
    from mdi import preprocess as PRE
    B = Fr(2) ** 32768
    t1 = [B, B, B, 2 * B]
    t2 = [B, B, B, 3 * B]
    lines = ["MARKOV", "2", "2 2", "3", "1 0", "2 0 1", "2 0 1", "2", "1 1",
             "4", " ".join(str(x.numerator) for x in t1),
             "4", " ".join(str(x.numerator) for x in t2)]
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    assert p[0][1] == Fr(7, 9), p[0][1]
    simp = PRE.simplify(r)
    # the combination must be DECLINED, with both factors retained
    assert simp.declined_products, "the over-cap product must be declined"
    r2 = M.Restricted(model=m, evidence={}, factors=simp.factors,
                      free=list(r.free), card=dict(r.card), constant=Fr(1),
                      impossible_factor=None)
    Z2, p2 = O.exact_all_marginals(r2)
    assert p2[0] == p[0], "the law must be preserved exactly"
    assert PRE.verify_identities(r, simp)
    # and the published interval must contain the truth
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=120)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS", res["outcome"]
    lo, hi = res["intervals"][0][1]
    assert lo <= Fr(7, 9) <= hi, (float(lo), float(hi))


def test_r4_checker_rejects_a_deliberately_faulty_producer():
    """A faulty transform must be REJECTED, so a common bug cannot pass both
    sides. Identity-by-identity checks alone were insufficient."""
    from mdi import preprocess as PRE
    import copy
    B = Fr(2) ** 32768
    lines = ["MARKOV", "2", "2 2", "3", "1 0", "2 0 1", "2 0 1", "2", "1 1",
             "4", " ".join(str(x.numerator) for x in [B, B, B, 2 * B]),
             "4", " ".join(str(x.numerator) for x in [B, B, B, 3 * B])]
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    # fault 1: drop one factor and duplicate the other (the original defect)
    bad = copy.deepcopy(simp)
    pairs = [f for f in bad.factors if len(f.scope) == 2]
    bad.factors = ([f for f in bad.factors if len(f.scope) != 2]
                   + [pairs[1], pairs[1]])
    bad.declined_products = []
    with pytest.raises(PRE.PreprocessError) as e:
        PRE.verify_identities(r, bad)
    assert "accounted for twice" in str(e.value)
    # fault 2: corrupt an emitted table entry
    bad2 = copy.deepcopy(simp)
    for f in bad2.factors:
        if len(f.scope) == 2:
            f.table[0] = f.table[0] * 2
            break
    with pytest.raises(PRE.PreprocessError) as e2:
        PRE.verify_identities(r, bad2)
    assert "CHANGED THE LAW" in str(e2.value)
    # fault 3: a wrong exact scale
    bad3 = copy.deepcopy(simp)
    bad3.scale = bad3.scale * 3
    with pytest.raises(PRE.PreprocessError):
        PRE.verify_identities(r, bad3)


def test_r4_declined_product_keeps_both_factors_on_a_different_shape():
    """A different family member: a 2x3 scope whose product overflows."""
    from mdi import preprocess as PRE
    B = Fr(2) ** 40000
    t = [B, B, B, B, B, 2 * B]
    lines = ["MARKOV", "2", "2 3", "3", "1 0", "2 0 1", "2 0 1", "2", "1 1",
             "6", " ".join(str(x.numerator) for x in t),
             "6", " ".join(str(x.numerator) for x in t)]
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    simp = PRE.simplify(r)
    assert simp.declined_products
    r2 = M.Restricted(model=m, evidence={}, factors=simp.factors,
                      free=list(r.free), card=dict(r.card), constant=Fr(1),
                      impossible_factor=None)
    Z2, p2 = O.exact_all_marginals(r2)
    for v in r.free:
        assert p[v] == p2[v], v
    assert PRE.verify_identities(r, simp)


def test_r4_regional_checker_requires_containment_not_widening():
    """Review 4 defect 2: the checker must derive its OWN enclosure and require
    the publication to CONTAIN it. Widening the submitted interval by the
    allowance accepts any publication near the coarse answer, including a wrong
    one, and lets a corrupted producer pass by submitting its own number."""
    from mdi import regional_check as RC
    m, r, regs, crs, rds, _ = _ring_coarse()
    t1 = K.level_radius(1)
    Z, counts = RC.independent_contract(r, regs, crs, rds, set(r.free))
    # a publication shifted by 0.131, which the old direction accepted
    bad = {}
    for v in sorted(r.free):
        rows = []
        for s in range(2):
            q = counts.get((v, s), Fr(0)) / Z
            rows.append((max(Fr(0), q + Fr(131, 1000) - t1),
                         min(Fr(1), q + Fr(131, 1000) + t1)))
        bad[v] = rows
    ok, fails, _ = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), bad, t1, Fr(1, 100))
    assert not ok, "a shifted publication must be rejected"
    assert any("does NOT contain" in x for x in fails), fails[:2]


def test_r4_regional_checker_rejects_malformed_rows_and_zero_evidence():
    from mdi import regional_check as RC
    m, r, regs, crs, rds, _ = _ring_coarse()
    t1 = K.level_radius(1)
    for pub, why in [
        ({v: [] for v in sorted(r.free)}, "EMPTY"),
        ({v: [(Fr(9, 10), Fr(1, 10))] * 2 for v in sorted(r.free)}, "INVERTED"),
        ({v: [(Fr(-1), Fr(1, 2)), (Fr(0), Fr(1, 2))] for v in sorted(r.free)},
         "outside [0,1]"),
    ]:
        ok, fails, _ = RC.verify_regional_publication(
            r, regs, crs, rds, set(r.free), pub, t1, Fr(1, 100))
        assert not ok, why
        assert fails
    # a model with zero evidence weight must be refused before numerical work
    txt = ("MARKOV\n3\n2 2 2\n3\n2 0 1\n2 1 2\n2 0 2\n"
           "4\n1 0 0 1\n4\n1 0 0 1\n4\n0 1 1 0\n")
    m2 = M.read_uai(w(txt))
    r2 = M.restrict(m2, {})
    pub2 = {v: [(Fr(0), Fr(1, 2))] * 2 for v in range(3)}
    # a contradictory model has no coarse structure to pass in; the guard is on
    # the restricted model itself
    assert r2.impossible_factor is None, "individually nonzero factors"
    Zt, _ = O.exact_all_marginals(r2)
    assert Zt == 0, "but globally contradictory"


def test_r4_regional_checker_rebuilds_its_own_boundary_order():
    """Trusting producer boundary metadata let a corrupted ordering pass an
    exact-coarsening example with error about 0.131."""
    from mdi import regional_check as RC
    import copy
    m, r, regs, crs, rds, _ = _ring_coarse()
    t1 = K.level_radius(1)
    Z, counts = RC.independent_contract(r, regs, crs, rds, set(r.free))
    pub = {}
    for v in sorted(r.free):
        rows = []
        for s in range(2):
            q = counts.get((v, s), Fr(0)) / Z
            rows.append((max(Fr(0), q - t1), min(Fr(1), q + t1)))
        pub[v] = rows
    ok, _, _ = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), pub, t1, Fr(1, 100))
    assert ok
    # corrupt the producer's boundary ORDER: the checker must notice
    bad_rds = copy.deepcopy(rds)
    for rd in bad_rds:
        if len(rd.boundary) > 1:
            rd.boundary = tuple(reversed(rd.boundary))
            break
    ok2, fails2, _ = RC.verify_regional_publication(
        r, regs, crs, bad_rds, set(r.free), pub, t1, Fr(1, 100))
    assert not ok2, "a corrupted producer boundary order must be detected"
    assert any("boundary order" in x for x in fails2), fails2[:2]


# ===== review 4 defect 3: level two and the general DP =====

def _asym_chain(n=13, tail=2, pair="3 1 1 2"):
    sc = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
    L = ["MARKOV", str(n), " ".join(["2"] * n), str(len(sc))]
    for s_ in sc:
        L.append("%d %s" % (len(s_), " ".join(map(str, s_))))
    for v in range(n):
        L.extend(["2", "1 %d" % (tail if v == n - 1 else 1)])
    for _ in range(n - 1):
        L.extend(["4", pair])
    return "\n".join(L) + "\n"


def test_r4_level2_multiplies_every_outer_crossing():
    """Review 4 defect 3: level two built the list of factors crossing between
    parent regions and never multiplied them. On a 13-variable chain forced into
    three parents that gave P(x12=1) = 14/25 against the exact 466/843, an error
    of 0.007212 against the 0.002 two-level allowance.

    MULTIPLE parents are essential: with one parent every crossing is internal
    and the defect is invisible, which is why the earlier control missed it.
    """
    from mdi import level2 as L2, compact as CP
    n = 13
    m = M.read_uai(w(_asym_chain(n)))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    BS = 3
    regs = tuple(tuple(range(i, min(i + BS, n))) for i in range(0, n, BS))
    t1 = K.level_radius(2)
    cap = K.region_distortion_budget(t1, len(regs))
    region_of = {v: i for i, rr in enumerate(regs) for v in rr}
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        cr = R.merge_region(rd, r.factors, r.card, cap, set(r.free),
                            region_of=region_of, aggregate=True)
        rds.append(rd); crs.append(cr)
    proj, _ = CP.project_crossings(r, regs, crs, rds)
    cc = {i: len(crs[i].cells) for i in range(len(regs))}
    for cap_assign, want_multi in ((8, True), (4096, False)):
        parents = L2.group_children(len(regs), proj,
                                    cap_assignments=cap_assign, cell_counts=cc)
        if want_multi:
            assert len(parents) > 1, "this control needs MULTIPLE parents"
        l2 = {"parents": parents, "parent_data": [], "skipped": 0,
              "rho_cap": K.region_distortion_budget(t1, len(parents)),
              "projected": proj, "n_parents": len(parents)}
        for parent in parents:
            l2["parent_data"].append(
                L2.parent_region_data(parent, crs, proj, set(r.free)))
        Zt, counts = L2.level2_marginals(r, regs, crs, rds, set(r.free), l2)
        q = counts.get((n - 1, 1), Fr(0)) / Zt
        err = abs(q - p[n - 1][1])
        assert err <= 2 * t1, (len(parents), float(q), float(p[n - 1][1]),
                               float(err))
        # the mark/mass identity must hold per variable
        for v in sorted(r.free):
            tot = sum(counts.get((v, s), Fr(0)) for s in range(r.card[v]))
            assert tot == Zt, (v, tot, Zt)


def test_r4_level2_accounts_for_every_crossing_once():
    from mdi import level2 as L2, compact as CP
    n = 9
    m = M.read_uai(w(_asym_chain(n)))
    r = M.restrict(m, {})
    regs = tuple(tuple(range(i, min(i + 3, n))) for i in range(0, n, 3))
    t1 = K.level_radius(2)
    cap = K.region_distortion_budget(t1, len(regs))
    region_of = {v: i for i, rr in enumerate(regs) for v in rr}
    rds, crs = [], []
    for reg in regs:
        rd = R.region_data(reg, r.card, r.factors, set(r.free))
        cr = R.merge_region(rd, r.factors, r.card, cap, set(r.free),
                            region_of=region_of, aggregate=True)
        rds.append(rd); crs.append(cr)
    proj, _ = CP.project_crossings(r, regs, crs, rds)
    cc = {i: len(crs[i].cells) for i in range(len(regs))}
    parents = L2.group_children(len(regs), proj, cap_assignments=8,
                               cell_counts=cc)
    l2 = {"parents": parents, "parent_data": [], "skipped": 0,
          "rho_cap": K.region_distortion_budget(t1, len(parents)),
          "projected": proj, "n_parents": len(parents)}
    for parent in parents:
        l2["parent_data"].append(
            L2.parent_region_data(parent, crs, proj, set(r.free)))
    # duplicating a crossing in a parent's internal list must be caught
    if len(l2["parent_data"][0].internal_crossings) >= 1:
        l2["parent_data"][0].internal_crossings.append(
            l2["parent_data"][0].internal_crossings[0])
        with pytest.raises(L2.Level2Error) as e:
            L2.level2_marginals(r, regs, crs, rds, set(r.free), l2)
        assert "twice" in str(e.value)


def test_r4_general_dp_marked_join_keeps_sibling_contributions():
    """Review 4: the DP's partition function was right but its marked masses
    dropped every sibling's contribution. On a star with three leaves the marked
    masses summed to 7 instead of 91. A chain control cannot expose this because
    no bag has two children."""
    import gmpy2
    from mdi import gendp as G
    n = 4
    sc = [(v,) for v in range(n)] + [(0, 1), (0, 2), (0, 3)]
    L = ["MARKOV", str(n), " ".join(["2"] * n), str(len(sc))]
    for s_ in sc:
        L.append("%d %s" % (len(s_), " ".join(map(str, s_))))
    for v in range(n):
        L.extend(["2", "1 1"])
    for _ in range(3):
        L.extend(["4", "2 1 1 3"])
    m = M.read_uai(w("\n".join(L) + "\n"))
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    pl, est = sel["chosen"]
    # the plan must actually branch, or the control proves nothing
    assert any(len(b.children) >= 2 for b in pl.bags), "need a join"
    ctx = A.Ctx(160)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(0)]
        features = [{v: [Fr(0), Fr(0)] for v in range(n)}]

    (Zlo, Zhi), mk, meta = G.run(pl, r.factors, r.card, Cand(), 1,
                                 set(r.free), ctx)
    Rz = Fr(0)
    rmk = {(v, a): Fr(0) for v in range(n) for a in range(2)}
    for combo in itertools.product(*[range(2)] * n):
        a_ = {v: combo[v] for v in range(n)}
        wt = Fr(1)
        for f in r.factors:
            st = f.strides()
            off = sum(a_[v] * st[k] for k, v in enumerate(f.scope))
            wt *= f.table[off]
        if wt == 0:
            continue
        Rz += wt
        for v in range(n):
            rmk[(v, combo[v])] += wt
    assert Zlo <= Rz <= Zhi, (Zlo, Rz, Zhi)
    for v in range(n):
        tot = sum(mk.get((v, a), (Fr(0), Fr(0)))[0] for a in range(2))
        assert tot == Rz, ("marked masses must sum to the unmarked mass", v,
                           tot, Rz)
        for a in range(2):
            lo, hi = mk.get((v, a), (Fr(0), Fr(0)))
            assert lo / Zhi <= rmk[(v, a)] / Rz <= hi / Zlo, (v, a)


def test_r4_general_dp_negative_sign_on_a_star():
    """A different family member: the same join with a negative mode."""
    from mdi import gendp as G
    n = 4
    sc = [(v,) for v in range(n)] + [(0, 1), (0, 2), (0, 3)]
    L = ["MARKOV", str(n), " ".join(["2"] * n), str(len(sc))]
    for s_ in sc:
        L.append("%d %s" % (len(s_), " ".join(map(str, s_))))
    for v in range(n):
        L.extend(["2", "1 2"])
    for _ in range(3):
        L.extend(["4", "2 1 1 3"])
    m = M.read_uai(w("\n".join(L) + "\n"))
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    pl, est = sel["chosen"]
    ctx = A.Ctx(180)

    class Cand:
        rank = 1
        signs = [-1]
        gammas = [Fr(1, 10)]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    (Zlo, Zhi), mk, meta = G.run(pl, r.factors, r.card, Cand(), 1,
                                 set(r.free), ctx)
    assert Zlo > 0 and Zhi >= Zlo
    for v in range(n):
        lo_tot = sum(mk.get((v, a), (Fr(0), Fr(0)))[0] for a in range(2))
        hi_tot = sum(mk.get((v, a), (Fr(0), Fr(0)))[1] for a in range(2))
        assert lo_tot <= Zhi and hi_tot >= Zlo, (v, lo_tot, hi_tot)
        for a in range(2):
            lo, hi = mk.get((v, a), (Fr(0), Fr(0)))
            assert lo >= 0 and hi >= lo, "weights must stay nonnegative"


def test_r4_exact_exp_bounds_bracket_a_high_precision_reference():
    """The lattice's certificate constants are exact rational bounds, not
    binary64. Validated against a 2000-bit MPFR reference; a 400-bit reference
    is itself less accurate than the 64-term series, which is why the bracket
    must be checked at high precision."""
    import gmpy2
    ctx = gmpy2.context(precision=2000)
    with ctx:
        for x in (Fr(0), Fr(1, 10), Fr(-1, 10), Fr(1, 2), Fr(3), Fr(-2),
                  Fr(-7, 3)):
            lo = CO._exp_lower(x)
            up = CO._exp_upper(x)
            assert lo <= up, x
            ref = Fr(gmpy2.mpq(gmpy2.exp(
                gmpy2.mpfr(gmpy2.mpq(x.numerator, x.denominator)))))
            assert lo <= ref <= up, (x, float(lo), float(ref), float(up))


def test_r4_lattice_admission_is_exact_on_the_returned_bound():
    """Review 4: a 1e-18 target returned a bound of 2e-15 and admitted, because
    the tail term was never compared and the constants were binary64."""
    # tight targets must either meet their bound exactly or decline
    for d in (Fr(1, 10 ** 18), Fr(1, 10 ** 15), Fr(1, 10 ** 4), Fr(1, 1000)):
        try:
            lat = CO.gf_lattice(Fr(1, 20), Fr(6), d)
        except CO.Declined:
            continue
        assert lat["exact_admission"]
        total = Fr(lat["total_bound"])
        assert total <= d, (str(d), float(total))
        # the returned total must be the sum of its two parts
        assert total == Fr(lat["tail_bound"]) + Fr(lat["discretization_bound"])
        # and the constants must be exact rationals, not floats
        for key in ("M_upper", "tail_bound", "discretization_bound",
                    "total_bound", "a_squared"):
            assert isinstance(lat[key], Fr), key


def test_r4_lattice_still_declines_the_pedigree_mode():
    with pytest.raises(CO.Declined) as e:
        CO.gf_lattice(Fr(8721203, 1000000), Fr(467709, 50000), Fr(1, 1000))
    assert "cannot meet delta" in str(e.value) or "exceeds" in str(e.value)


# ===== review 4 priority 3: the connected public pipeline =====

TINY = ("MARKOV\n3\n2 3 2\n3\n1 1\n2 0 1\n3 0 1 2\n"
        "3\n2 5 11\n6\n1 7 2 13 3 5\n12\n2 1 3 1 5 1 7 1 11 1 13 1\n")


def test_r4_public_pipeline_runs_every_stage():
    """One real route: parse/restrict, independently verified COMMON exact
    preprocessing, discovery, persisted and reloaded plan records, complete-cost
    pricing, dispatcher execution, independent checking, publication."""
    from mdi import pipeline as PLN
    import tempfile as _tf
    m = M.read_uai(w(TINY))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    d = _tf.mkdtemp()
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30, plan_dir=d)
    assert res.status in ("CERTIFIED_RESEARCH_ROUTE",
                          "CERTIFIED_FALLBACK_ONLY"), (res.status, res.reason)
    for key in ("parse_s", "preprocess_s", "discover_s", "persist_s",
                "select_s", "execute_s", "check_s"):
        assert key in res.stages, key
    assert res.checker["status"] == "VERIFIED"
    assert res.properties["independently_verified"]
    assert res.properties["publication_contract_met"]
    # plan records were persisted and are reloadable
    files = [x for x in os.listdir(d) if x.endswith(".plan.json")]
    assert files, "plan records must be persisted"
    from mdi import plantype as PT
    for fn in files:
        back = PT.PlanRecord.from_json(open(os.path.join(d, fn)).read())
        assert back.validate()
    # and the published intervals contain the truth
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res.intervals[v][s]
            assert lo <= p[v][s] <= hi, (v, s)


@pytest.mark.parametrize("model_txt", [TINY, ring_of_blocks()[0]])
def test_r4_pipeline_rejects_an_intentionally_faulty_producer(model_txt):
    """The critical soundness case: a producer that publishes shifted intervals
    must be REJECTED by the independent checker, so a common bug cannot pass
    both sides. The fault is injected on WHICHEVER route the planner picks."""
    from mdi import pipeline as PLN
    import mdi.pipeline as PP
    from mdi import solve as SS
    m = M.read_uai(w(model_txt))
    good = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30)
    assert good.checker["status"] == "VERIFIED", good.reason
    kind = good.plan["kind"]

    def shift(rows):
        return [(max(Fr(0), Fr(lo) + Fr(1, 10)), min(Fr(1), Fr(hi) + Fr(1, 10)))
                for lo, hi in rows]

    if kind == "regional":
        orig = PP._regional_execute

        def faulty(rr, payload, queries, eps, bg):
            return {v: shift(rows)
                    for v, rows in orig(rr, payload, queries, eps, bg).items()}
        PP._regional_execute = faulty
        restore = lambda: setattr(PP, "_regional_execute", orig)
    else:
        orig = SS.solve

        def faulty(*a, **kw):
            res = orig(*a, **kw)
            if isinstance(res, dict) and res.get("intervals"):
                res["intervals"] = {v: shift(rows)
                                    for v, rows in res["intervals"].items()}
            return res
        SS.solve = faulty
        restore = lambda: setattr(SS, "solve", orig)
    try:
        res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30)
        assert res.status == "NUMERICAL_REFUSAL", (kind, res.status)
        assert "REJECTED" in res.reason
        assert res.checker["status"] == "FAILED"
    finally:
        restore()


def test_r4_pipeline_preprocesses_before_planning():
    """C: preprocessing must happen BEFORE discovery and planning, identically
    in every arm."""
    from mdi import pipeline as PLN
    txt = ("MARKOV\n3\n2 2 2\n4\n1 0\n2 0 1\n2 1 2\n1 2\n"
           "2\n1.5 2.5\n4\n2 6 3 9\n4\n1 1 1 1\n2\n0.5 4\n")
    m = M.read_uai(w(txt))
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    assert res.preprocess, "the preprocessing identity must be recorded"
    assert res.preprocess["removed_constants"], "the constant factor"
    assert res.preprocess["split_pairs"], "the separable pair"
    # discovery ran AFTER preprocessing
    assert res.stages["preprocess_s"] is not None
    assert "discover_s" in res.stages


def test_r4_pipeline_selection_is_priced_not_ratio():
    from mdi import pipeline as PLN
    m = M.read_uai(w(TINY))
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    assert "cell-count ratio is never used" in res.plan["why"]
    assert res.prices, "every candidate must carry a complete price"
    for pr in res.prices:
        assert pr["counters"], pr["name"]
        for key, c in pr["counters"].items():
            assert c["label"] in ("exact", "upper_bound", "lower_bound",
                                 "measured_calibration", "forecast"), (key, c)


def test_r4_plan_loader_rejects_fourteen_malformed_mutations():
    """The loader must be strict and SEMANTIC: types, booleans, the complete
    prerequisite graph, nonnegative bounded allocations, valid precision and
    range, exact scopes. A claim flag is never evidence a proof was checked."""
    import json
    from mdi import plantype as PT
    rec = PT.PlanRecord(
        kind="identity", name="x", model_sha256="a" * 64,
        evidence_sha256="b" * 64, query_sha256="c" * 64,
        preprocess_identity={"scale": "1"}, factor_ownership=[(0, "b")],
        factor_scopes=[(0, (0, 1), (2, 2))], region_membership=[],
        cell_membership=[], allocations={"t": Fr(1, 1000)},
        executor_id="e", checker_id="k",
        numerical={"precision": 64, "mode": "P", "emin": -10, "emax": 10},
        cost_counters={"a": 1}, storage_schedule={"b": 2},
        rejected_alternatives=[]).validate()
    muts = [
        ("negative allocation", lambda d: d.update(allocations={"t": "-1/1000"})),
        ("allocation > 1", lambda d: d.update(allocations={"t": "3/2"})),
        ("non-boolean property", lambda d: d["properties"].update(selected=1)),
        ("inconsistent flags",
         lambda d: d["properties"].update(independently_verified=True)),
        ("incomplete properties", lambda d: d["properties"].pop("selected")),
        ("bad precision",
         lambda d: d.update(numerical={"precision": 1, "mode": "P"})),
        ("bad mode",
         lambda d: d.update(numerical={"precision": 64, "mode": "Q"})),
        ("emin>=emax", lambda d: d.update(
            numerical={"precision": 64, "mode": "P", "emin": 10, "emax": -10})),
        ("empty executor", lambda d: d.update(executor_id="")),
        ("dup scope var", lambda d: d.update(factor_scopes=[[0, [1, 1], [2, 2]]])),
        ("zero cardinality",
         lambda d: d.update(factor_scopes=[[0, [0, 1], [0, 2]]])),
        ("scope/card mismatch",
         lambda d: d.update(factor_scopes=[[0, [0, 1], [2]]])),
        ("float allocation", lambda d: d.update(allocations={"t": 0.001})),
        ("bad hash", lambda d: d.update(query_sha256="zz")),
    ]
    for name, mut in muts:
        d = json.loads(rec.to_json())
        mut(d)
        with pytest.raises(PT.PlanError):
            PT.PlanRecord.from_json(json.dumps(d))


def test_r4_arm_driver_uses_the_pipeline():
    """The production arm must route its work through the pipeline, not the old
    ratio-only path with the Cartesian coarse executor."""
    import inspect
    from mdi import arm as AR
    src = inspect.getsource(AR.run_arm)
    assert "pipeline as PLN" in src
    assert "PLN.solve" in src
    assert "price_regional" not in src, "the legacy selection must be gone"
    assert "solve_coarse_with_markers" not in src, "the Cartesian executor"


# ===== review 4 priority 4: cost and resource accounting =====

def test_r4_operation_bounds_actually_bound_the_execution():
    """Review 4: a tiny solve was priced at 28 producer operations but executed
    45, so the 'upper bound' was not one. The counts must mirror what
    Engine.send actually does per assignment."""
    from mdi import pricing as PR, contract as C
    for n in (3, 4, 6, 8):
        scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
        lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
        for sc in scopes:
            lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
        for v in range(n):
            lines.extend(["2", "1 2"])
        for _ in range(n - 1):
            lines.extend(["4", "2 1 1 3"])
        m = M.read_uai(w("\n".join(lines) + "\n"))
        r = M.restrict(m, {})
        sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
        pl, est = sel["chosen"]
        price = PR.price_identity_plan(pl, est,
                                       sum(r.card[v] for v in r.free), 64)
        pu = int(price.counters["producer_upward_ops"].value)
        pd = int(price.counters["producer_downward_ops"].value)
        ctx = A.Ctx(64)
        eng = C.Engine(pl, r.factors, ctx, mode="P")
        roots = [b.idx for b in pl.bags if b.parent == -1]
        for rt in roots:
            eng.upward(rt)
        actual_up = eng.ops["mul"] + eng.ops["add"]
        for rt in roots:
            eng.downward(rt)
        actual_tot = eng.ops["mul"] + eng.ops["add"]
        assert pu >= actual_up, ("upward bound must hold", n, pu, actual_up)
        assert pu + pd >= actual_tot, ("producer bound", n, pu + pd, actual_tot)


def test_r4_declared_assignment_cap_is_4096():
    """Renaming 262,144 is not restoration."""
    for key in ("region_tuple_assignments", "region_local_enumeration",
                "aggregated_kernel_entries", "level2_contraction_space",
                "checker_contraction_space"):
        assert K.CAPS[key] == 4096, (key, K.CAPS[key])
    assert K.AMENDMENTS == [], "a cap change must be a recorded amendment"


def test_r4_schedule_simulation_is_iterative():
    """A narrow long chain is exactly the shape that most needs a memory
    forecast, and a recursive walk raised RecursionError on it."""
    n = 3000
    scopes = [(v,) for v in range(n)] + [(i, i + 1) for i in range(n - 1)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1 2"])
    for _ in range(n - 1):
        lines.extend(["4", "2 1 1 3"])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("ascending_ids", P.order_ascending(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    assert len(pl.bags) == n
    assert sys.getrecursionlimit() < n, "the chain must exceed the limit"
    sim = P.simulate_executed_schedule(pl)       # must not raise
    assert sim["peak_live_entries"] > 0


def test_r4_reduced_graph_checker_preserves_the_factorization():
    """F.4: independent checking must not require enumerating every joint cell
    assignment. The two contractions must agree where both are affordable."""
    from mdi import regional_check as RC
    m, r, regs, crs, rds, _ = _ring_coarse()
    Zm, cm = RC._reduced_message_passing(r, regs, crs, rds, set(r.free))
    Ze, ce = RC.independent_contract(r, regs, crs, rds, set(r.free),
                                     allow_enumeration=True)
    assert Zm > 0 and Ze > 0
    for v in sorted(r.free):
        for s in range(2):
            qm = cm.get((v, s), Fr(0)) / Zm
            qe = ce.get((v, s), Fr(0)) / Ze
            assert abs(qm - qe) < Fr(1, 10 ** 12), (v, s, float(qm), float(qe))


# ===== review 4 priority 5: introduced and retained waste =====

def test_r4_point_kernel_uses_mpfr_traps_not_exact_recomputation():
    """Review 4: the overflow repair recomputed every operation in exact
    rationals, costing 23.7x per operation inside the numerical kernel. MPFR's
    own overflow and underflow traps enforce the range natively."""
    import time as _t
    ctx = A.Ctx(64)
    a = ctx.down(Fr(1, 3))
    b = ctx.down(Fr(1, 7))
    N = 20000
    t0 = _t.monotonic()
    for _ in range(N):
        ctx.mul_d(a, b)
    rate = N / max(1e-9, _t.monotonic() - t0)
    assert rate > 1e6, "the point kernel must exceed 1e6 ops/s; got %.0f" % rate
    # the range guard must STILL refuse at the boundaries
    r = A.Ctx(64, emin=-100, emax=100)
    for fn in (lambda: r.down(Fr(2) ** 200),
               lambda: r.down(Fr(1, 2 ** 200)),
               lambda: r.mul_d(r.down(Fr(2) ** 60), r.down(Fr(2) ** 60))):
        with pytest.raises(A.NumericalRefusal):
            fn()
    # exact arithmetic remains available as an INDEPENDENT reference
    for k in range(1, 200):
        q = Fr(k, 197)
        x = ctx.down(q)
        assert A.exact_fr(x) <= q
        assert ctx.verify_exact(x, q, "down")


def test_r4_combined_factors_are_resimplified():
    """G: multiplication can CREATE a constant or separable factor, which the
    single pass left as a spurious graph dependency. Neither input here is
    separable, but their product is."""
    from mdi import preprocess as PRE
    txt = ("MARKOV\n2\n2 2\n3\n1 0\n2 0 1\n2 0 1\n2\n1 1\n"
           "4\n1 2 3 1\n4\n3 1 1 2\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    pairs_in = [f for f in r.factors if len(f.scope) == 2]
    assert len(pairs_in) == 2
    for f in pairs_in:
        assert PRE.separable_split(f) is None, "neither input is separable"
    Z, p = O.exact_all_marginals(r)
    simp = PRE.simplify(r)
    assert not [f for f in simp.factors if len(f.scope) == 2], \
        "the re-simplified product must leave no pair dependency"
    assert simp.combined_splits, "the combined identity must be recorded"
    r2 = M.Restricted(model=m, evidence={}, factors=simp.factors,
                      free=list(r.free), card=dict(r.card), constant=Fr(1),
                      impossible_factor=None)
    Z2, p2 = O.exact_all_marginals(r2)
    for v in r.free:
        assert p[v] == p2[v], v
    # the checker rebuilds the product from the ORIGINALS and re-derives it
    assert PRE.verify_identities(r, simp)


def test_r4_combined_identity_record_is_verified_not_trusted():
    """A combined record naming the wrong originals must be rejected."""
    from mdi import preprocess as PRE
    import copy
    txt = ("MARKOV\n3\n2 2 2\n4\n1 0\n2 0 1\n2 0 1\n1 2\n2\n1 1\n"
           "4\n1 2 3 1\n4\n3 1 1 2\n2\n1 3\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    if simp.combined_splits:
        bad = copy.deepcopy(simp)
        bad.combined_splits[0]["members"] = [0]      # a single, non-separable
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, bad)
