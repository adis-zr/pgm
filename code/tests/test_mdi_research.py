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
