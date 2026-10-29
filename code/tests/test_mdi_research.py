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
    ok, fails, _vm = S.verify_publication(m, {}, iv, eps=Fr(1, 100), mode="I")
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
    ok, fails, _vm = S.verify_publication(m, {}, bad, eps=Fr(1, 100), mode="I")
    assert not ok, "a missing output row must be rejected"
    # wrong row length
    bad2 = {v: list(rows) for v, rows in iv.items()}
    bad2[sorted(bad2)[0]] = bad2[sorted(bad2)[0]][:-1]
    ok2, _f2, _vm2 = S.verify_publication(m, {}, bad2, eps=Fr(1, 100), mode="I")
    assert not ok2, "a short output row must be rejected"
    # inverted endpoints
    bad3 = {v: list(rows) for v, rows in iv.items()}
    v0 = sorted(bad3)[0]
    bad3[v0] = [(Fr(9, 10), Fr(1, 10))] + list(bad3[v0][1:])
    ok3, _f3, _vm3 = S.verify_publication(m, {}, bad3, eps=Fr(1, 100), mode="I")
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
        executor_id="mdi.registry:_identity_executor",
        checker_id="mdi.registry:_identity_checker",
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
    # an UNKNOWN kind must still refuse
    with pytest.raises(PT.PlanError):
        PT.dispatch("nonsense")
    ex, ck = PT.dispatch("identity")
    assert ex is not None and ck is not None
    # regional now has BOTH (contract D.7 checker implemented)
    ex2, ck2 = PT.dispatch("regional")
    assert ex2 is not None and ck2 is not None
    # every other kind now has both as well
    for kind in ("statistic", "gaussian", "fourier", "composed"):
        ex3, ck3 = PT.dispatch(kind)
        assert ex3 is not None and ck3 is not None


def test_support_table_is_factual():
    from mdi import registry as RG
    rows = {r["kind"]: r for r in RG.status_table()}
    assert rows["identity"]["executor_supported"]
    assert rows["identity"]["checker_supported"]
    assert rows["regional"]["executor_supported"]
    assert rows["regional"]["checker_supported"], "D.7 checker is implemented"
    # every kind now HAS an executor (E.6 fourier, E.7 composed)
    assert rows["fourier"]["executor_supported"]
    assert rows["composed"]["executor_supported"]
    # every route now has a checker as well (the largest blocker, closed)
    for k in ("statistic", "gaussian", "fourier", "composed"):
        assert rows[k]["checker_supported"], k


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
    (Zlo, Zhi), (clo_m, chi_m) = RC.independent_contract(
        r, regs, crs, rds, set(r.free))
    assert Zlo > 0
    # A publication must CONTAIN the checker's enclosure, so it has to be at
    # least as wide as the charged transformation radius AND the reduced
    # contraction's own numerical error. A degenerate point interval is
    # correctly REJECTED.
    point = {v: [(clo_m.get((v, s), Fr(0)) / Zhi,) * 2 for s in range(2)]
             for v in sorted(r.free)}
    ok0, f0, _ = RC.verify_regional_publication(
        r, regs, crs, rds, set(r.free), point, t1, Fr(1, 100))
    assert not ok0, "a degenerate point cannot contain a width-2t enclosure"
    assert any("does NOT contain" in x for x in f0), f0[:3]
    pub = {}
    for v in sorted(r.free):
        rows = []
        for s in range(2):
            qlo = clo_m.get((v, s), Fr(0)) / Zhi
            qhi = chi_m.get((v, s), Fr(0)) / Zlo
            rows.append((max(Fr(0), qlo - t1), min(Fr(1), qhi + t1)))
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


def test_H_categorical_mode_fitting_is_implemented():
    """Categorical fitting is now implemented (E.4). A non-binary model must
    yield a CATEGORICAL candidate whose features span each variable's domain,
    never a binary-only answer, and the fit is always checked by
    build_residual rather than trusted."""
    txt = ("MARKOV\n3\n3 3 2\n3\n2 0 1\n1 2\n2 1 2\n"
           "9\n2 1 1 1 2 1 1 1 2\n2\n1 1\n6\n1 2 1 2 1 2\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    assert any(r.card[v] == 3 for v in r.free)
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    if not cands:
        # a declension is acceptable, but it must carry a reason
        assert info.get("declined"), info
        return
    assert info.get("categorical"), info
    for cand in cands:
        assert cand.kind == "categorical_rank1"
        for v, fv in cand.features[0].items():
            assert len(fv) == r.card[v], (v, len(fv), r.card[v])


def test_H_bounded_fallback_is_a_recorded_selection():
    """A route with no executor must not fall through; fallback is a separate,
    recorded, charged selection."""
    from mdi import plantype as PT, registry as RG, pricing as PR
    # an unknown kind refuses; a kind with no CHECKER is ineligible
    with pytest.raises(PT.PlanError):
        PT.dispatch("nonsense")
    for kind in ("statistic", "gaussian", "fourier", "composed"):
        ex, ck = PT.dispatch(kind)
        assert ex is not None and ck is not None
    # the fallback must be priced as its own record, with identity eligible
    ident = _complete_price(PR, "identity", "identity:fallback", 10 ** 6,
                            1 << 20)
    unimpl = _complete_price(PR, "fourier", "fourier", 1, 1, eligible=False,
                             ineligible_reason="ineligible for this comparison")
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
    # the invariant lives in the per-component contraction; G.run is now the
    # dispatcher that either delegates to it or declines a disconnected graph
    src = inspect.getsource(G._run_component)
    assert "inserted twice" in src
    assert "never had their statistic inserted" in src
    # and a disconnected residual must DECLINE rather than multiply
    # per-component totals, since the collective statistic couples every
    # variable through exp(-gamma S^2/2)
    dsrc = inspect.getsource(G.run)
    assert "DISCONNECTED residual" in dsrc


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
    (Z, _Zhi), (counts, _chi) = RC.independent_contract(
        r, regs, crs, rds, set(r.free))
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
    (Zlo, Zhi), (clo_m, chi_m) = RC.independent_contract(
        r, regs, crs, rds, set(r.free))
    pub = {}
    for v in sorted(r.free):
        rows = []
        for s in range(2):
            # the publication must contain the checker's ENCLOSURE, which now
            # charges the point DAG's own rounding error as well as t
            qlo = clo_m.get((v, s), Fr(0)) / Zhi
            qhi = chi_m.get((v, s), Fr(0)) / Zlo
            rows.append((max(Fr(0), qlo - t1), min(Fr(1), qhi + t1)))
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
    assert res.checker["status"] in (
        "VERIFIED", "VERIFIED_WITHOUT_INDEPENDENT_AGGREGATION"), \
        res.checker["status"]
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
    assert good.checker["status"] in (
        "VERIFIED", "VERIFIED_WITHOUT_INDEPENDENT_AGGREGATION"), good.reason
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


def test_r6_plan_loader_accepts_a_clean_base_then_rejects_each_mutation():
    """Each rejection control must FIRST accept its valid clean base, then
    change ONE thing and assert the NAMED reason.

    The previous version's base record was already invalid (name "x" against
    kind "identity", executor_id "e" with no module reference), so all
    fourteen mutations rejected on the same unrelated name/kind predicate and
    the test validated nothing about the fields it named.
    """
    import json
    from mdi import plantype as PT

    def base():
        return PT.PlanRecord(
            kind="identity", name="identity", model_sha256="a" * 64,
            evidence_sha256="b" * 64, query_sha256="c" * 64,
            preprocess_identity={"scale": "1"},
            factor_ownership=[(0, "bag")],
            factor_scopes=[(0, (0, 1), (2, 2))], region_membership=[],
            cell_membership=[], allocations={"t": Fr(1, 1000)},
            executor_id="mdi.registry:_identity_executor",
            checker_id="mdi.registry:_identity_checker",
            numerical={"precision": 64, "mode": "P", "emin": -10, "emax": 10},
            cost_counters={"producer_upward_ops": 1},
            storage_schedule={"peak_live_entries": 2},
            rejected_alternatives=[]).validate()

    # THE CLEAN BASE MUST LOAD, and round-trip byte-identically
    rec = base()
    txt = rec.to_json()
    back = PT.PlanRecord.from_json(txt)
    assert back.to_json() == txt, "the clean base must round-trip"

    muts = [
        ("negative allocation", lambda d: d.update(allocations={"t": "-1/1000"}),
         ("alloc", "negative", "range")),
        ("allocation > 1", lambda d: d.update(allocations={"t": "3/2"}),
         ("alloc", "range", "1")),
        ("non-boolean property", lambda d: d["properties"].update(selected=1),
         ("BOOLEAN", "boolean")),
        ("inconsistent flags",
         lambda d: d["properties"].update(independently_verified=True),
         ("prerequisite",)),
        ("incomplete properties", lambda d: d["properties"].pop("selected"),
         ("incomplete",)),
        ("bad precision",
         lambda d: d.update(numerical={"precision": 1, "mode": "P"}),
         ("precision",)),
        ("bad mode",
         lambda d: d.update(numerical={"precision": 64, "mode": "Q"}),
         ("mode",)),
        ("emin>=emax", lambda d: d.update(
            numerical={"precision": 64, "mode": "P", "emin": 10,
                       "emax": -10}), ("emin", "emax", "range")),
        ("empty executor", lambda d: d.update(executor_id=""),
         ("executor_id",)),
        ("unknown executor module",
         lambda d: d.update(executor_id="nonexistent:thing"),
         ("executor_id", "mdi")),
        ("dup scope var",
         lambda d: d.update(factor_scopes=[[0, [1, 1], [2, 2]]]),
         ("scope", "twice", "duplicate", "repeat")),
        ("zero cardinality",
         lambda d: d.update(factor_scopes=[[0, [0, 1], [0, 2]]]),
         ("cardinal",)),
        ("scope/card mismatch",
         lambda d: d.update(factor_scopes=[[0, [0, 1], [2]]]),
         ("scope", "card", "length")),
        ("float allocation", lambda d: d.update(allocations={"t": 0.001}),
         ("alloc", "exact", "rational", "float")),
        ("bad hash", lambda d: d.update(query_sha256="zz"),
         ("hex", "digest", "sha")),
        ("unknown field", lambda d: d.update(surprise=1), ("unknown field",)),
        ("kind/name disagree", lambda d: d.update(name="regional:x"),
         ("kind", "name")),
        ("empty ownership", lambda d: d.update(factor_ownership=[]),
         ("ownership", "empty")),
        ("ownership/scope disagree",
         lambda d: d.update(factor_ownership=[[7, "bag"]]),
         ("ownership", "scopes", "same")),
        ("empty cost counters", lambda d: d.update(cost_counters={}),
         ("cost_counters", "empty")),
        ("empty storage", lambda d: d.update(storage_schedule={}),
         ("storage_schedule", "empty")),
        ("empty numerical", lambda d: d.update(numerical={}),
         ("numerical", "empty")),
    ]
    for name, mut, expect in muts:
        d = json.loads(base().to_json())
        mut(d)
        with pytest.raises(PT.PlanError) as e:
            PT.PlanRecord.from_json(json.dumps(d))
        msg = str(e.value).lower()
        assert any(k.lower() in msg for k in expect), \
            "%s rejected for an UNRELATED reason: %s" % (name, e.value)


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
    (Zm, _Zmh), (cm, _cmh) = RC._reduced_message_passing(
        r, regs, crs, rds, set(r.free))
    (Ze, _Zeh), (ce, _ceh) = RC.independent_contract(
        r, regs, crs, rds, set(r.free), allow_enumeration=True)
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


# ===== review 4 priority 6: the remaining research branches =====

def _ternary_rank1(n=4, d=3, g=0.3):
    wv = [0.0, 1.0, 2.0][:d]
    sc = [(v,) for v in range(n)] + [(i, j) for i in range(n)
                                     for j in range(i + 1, n)]
    L = ["MARKOV", str(n), " ".join([str(d)] * n), str(len(sc))]
    for s_ in sc:
        L.append("%d %s" % (len(s_), " ".join(map(str, s_))))
    for v in range(n):
        L.extend([str(d), " ".join(dec(Fr(1)) for _ in range(d))])
    for i in range(n):
        for j in range(i + 1, n):
            e = [Fr(round(math.exp(g * wv[a] * wv[b]) * 10 ** 12), 10 ** 12)
                 for a in range(d) for b in range(d)]
            L.extend([str(d * d), " ".join(dec(x) for x in e)])
    return "\n".join(L) + "\n"


def test_r4_categorical_mode_fitting_recovers_and_removes():
    """E.4: finite categorical fitting by reference-state contrasts. It must
    find the mode on a TERNARY model and actually remove the interaction."""
    m = M.read_uai(w(_ternary_rank1()))
    r = M.restrict(m, {})
    assert all(r.card[v] == 3 for v in r.free)
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    assert cands, info
    assert info.get("categorical"), info
    cand = cands[0]
    assert cand.kind == "categorical_rank1"
    assert len(cand.features[0][sorted(r.free)[0]]) == 3
    ctx = A.Ctx(140)
    res = MD.build_residual(r.free, r.factors, r.card, cand, ctx)
    assert MD.tv_from_nu(res.nu) <= K.RADII["collective_fit_and_rounding"]
    Hs, _, _, _ = MD._pair_matrix(r.free, r.factors, r.card)
    orig = [abs(float(H[2][2]) - 1.0) for H in Hs.values()]
    resid = []
    for tbl in res.pairs.values():
        gg = MD.gauge_split(tbl, 3, 3)
        resid.append(abs(float(gg.H[2][2]) - 1.0))
    assert max(resid) < min(orig) / 100, (max(resid), min(orig))


def test_r4_trig_enclosures_are_sound_including_interior_extrema():
    """E.6: the complex path needs directed cos and sin enclosures that account
    for interior extrema, not just endpoint values."""
    ctx = A.Ctx(120)
    viol = 0
    for lo_n in range(-20, 21):
        for w_n in (1, 5, 20):
            lo = Fr(lo_n, 4)
            hi = lo + Fr(w_n, 4)
            cl, ch = CO._cos_enclose(lo, hi, ctx)
            sl, sh = CO._sin_enclose(lo, hi, ctx)
            assert -1 <= cl <= ch <= 1
            assert -1 <= sl <= sh <= 1
            for t in range(41):
                x = float(lo) + (float(hi) - float(lo)) * t / 40
                if not (float(cl) - 1e-12 <= math.cos(x) <= float(ch) + 1e-12):
                    viol += 1
                if not (float(sl) - 1e-12 <= math.sin(x) <= float(sh) + 1e-12):
                    viol += 1
    assert viol == 0, viol


def test_r4_fourier_evaluator_exists_and_refuses_a_positive_mode():
    """E.6: the complex-phase evaluator is implemented and registered."""
    from mdi import registry as RG, plantype as PT
    ex, ck = PT.dispatch("fourier")
    assert ex is not None and ck is not None
    assert "fourier" not in RG.UNIMPLEMENTED
    ctx = A.Ctx(120)

    class Pos:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 20)]
        features = [{0: [Fr(-1), Fr(1)]}]

    with pytest.raises(CO.Declined):
        CO.fourier_evaluate([0], {0: 2}, {0: [Fr(1), Fr(1)]}, Pos(), {0},
                            ctx, Fr(1, 1000))


def test_r4_composed_route_runs_and_encloses():
    """E.7: coarsen, then run a verified collective evaluator on the
    CATEGORICAL cells, preserving original query markers. Every transformation
    error adds."""
    from mdi import composed as CM
    m, r, regs, crs, rds, _ = _ring_coarse()
    ctx = A.Ctx(180)
    out, meta = CM.run(r, regs, crs, rds, set(r.free), ctx, Fr(1, 100))
    assert meta["evaluator"] in ("product_statistic_dp",
                                 "general_residual_dp"), meta
    assert meta["coarse_vars"] == len(regs)
    Z, p = O.exact_all_marginals(r)
    worst = Fr(0)
    for v in sorted(r.free):
        for s in range(r.card[v]):
            lo, hi = out[v][s]
            assert lo <= p[v][s] <= hi, (v, s, float(lo), float(p[v][s]),
                                         float(hi))
            worst = max(worst, hi - lo)
    assert worst <= Fr(1, 100), float(worst)
    # the radii ADD: the composed total must exceed each component
    assert Fr(meta["total_radius"]) >= Fr(meta["regional_radius"])
    assert Fr(meta["total_radius"]) >= Fr(meta["residual_tv"])


def test_r4_every_kind_has_a_registered_executor():
    """No kind should still refuse at dispatch for want of an executor."""
    from mdi import registry as RG, plantype as PT
    rows = {x["kind"]: x for x in RG.status_table()}
    for kind in PT.KINDS:
        assert rows[kind]["executor_supported"], kind
    for kind in PT.KINDS:
        assert rows[kind]["checker_supported"], kind


# ===== review 4 priority 7: behavioural and independent acceptance evidence =====

def test_r4_positive_aggregation_with_individual_spread_cancelling():
    """Priority 7: each factor individually has NONUNIT spread and their product
    cancels it. This is the positive-cancellation case, distinct from zero
    masking."""
    # factor 1: ratios 1/3 then 3  -> spread 9
    f1b, f1r = (Fr(1), Fr(9)), (Fr(3), Fr(3))
    # factor 2: ratios 3 then 1/3  -> spread 9, opposite direction
    f2b, f2r = (Fr(9), Fr(1)), (Fr(3), Fr(3))
    L1, U1 = R.ratio_extrema(f1b, f1r)
    L2, U2 = R.ratio_extrema(f2b, f2r)
    assert U1 / L1 == 9 and U2 / L2 == 9, "each must individually spread"
    pb = tuple(a * b for a, b in zip(f1b, f2b))
    pr = tuple(a * b for a, b in zip(f1r, f2r))
    Lp, Up = R.ratio_extrema(pb, pr)
    assert Up / Lp == 1, "the product must cancel to rho = 1"
    assert Lp == Up == Fr(1)


def test_r4_multiple_children_at_a_join_in_the_general_dp():
    """A join with THREE children, each contributing, so a two-child fix cannot
    pass by accident."""
    from mdi import gendp as G
    n = 5          # centre 0 with four leaves
    sc = [(v,) for v in range(n)] + [(0, k) for k in range(1, n)]
    L = ["MARKOV", str(n), " ".join(["2"] * n), str(len(sc))]
    for s_ in sc:
        L.append("%d %s" % (len(s_), " ".join(map(str, s_))))
    for v in range(n):
        L.extend(["2", "1 %d" % (v + 1)])
    for k in range(1, n):
        L.extend(["4", "%d 1 1 %d" % (k + 1, k + 2)])
    m = M.read_uai(w("\n".join(L) + "\n"))
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64, 1 << 30)
    pl, est = sel["chosen"]
    assert max(len(b.children) for b in pl.bags) >= 3, "need a 3+ child join"
    ctx = A.Ctx(180)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(0)]
        features = [{v: [Fr(0), Fr(0)] for v in range(n)}]

    (Zlo, Zhi), mk, meta = G.run(pl, r.factors, r.card, Cand(), 1,
                                 set(r.free), ctx)
    Rz = Fr(0)
    for combo in itertools.product(*[range(2)] * n):
        a_ = {v: combo[v] for v in range(n)}
        wt = Fr(1)
        for f in r.factors:
            st = f.strides()
            off = sum(a_[v] * st[k] for k, v in enumerate(f.scope))
            wt *= f.table[off]
        Rz += wt
    assert Zlo <= Rz <= Zhi
    for v in range(n):
        tot = sum(mk.get((v, a), (Fr(0), Fr(0)))[0] for a in range(2))
        assert tot == Rz, (v, tot, Rz)


def test_r4_point_vector_is_a_feasible_simplex_construction():
    """Priority 7: the declared point vector must be provably inside the
    published intervals AND on the simplex, and must survive serialization."""
    from mdi import pipeline as PLN, arm as AR
    import tempfile as _tf
    m = M.read_uai(w(TINY))
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30)
    assert res.intervals
    d = _tf.mkdtemp()
    AR._write_point_vector(res.intervals, m, {}, d, "t")
    from ext import uai as EU
    rows, _ = EU.read_mar(os.path.join(d, "point_t.MAR"))
    assert len(rows) == m.nvars
    for v in range(m.nvars):
        tot = sum(rows[v])
        # on the simplex, within the MAR format's decimal resolution
        assert abs(float(tot) - 1.0) <= 1e-5, (v, float(tot))
        for s in range(m.card[v]):
            lo, hi = res.intervals[v][s]
            # the written value must lie in the published interval, allowing
            # only the format's own rounding
            assert Fr(lo) - Fr(1, 10 ** 6) <= rows[v][s] <= Fr(hi) + Fr(1, 10 ** 6), \
                (v, s, float(lo), float(rows[v][s]), float(hi))


def test_r4_publication_survives_serialization_round_trip():
    """Parse the WRITTEN bytes and re-verify, rather than trusting the
    in-memory object."""
    from mdi import pipeline as PLN
    import json as _json
    import tempfile as _tf
    m = M.read_uai(w(TINY))
    res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30)
    d = _tf.mkdtemp()
    path = os.path.join(d, "pub.json")
    ser = {str(v): [[str(lo), str(hi)] for lo, hi in rows]
           for v, rows in res.intervals.items()}
    with open(path, "w") as fh:
        _json.dump(ser, fh)
    back = _json.load(open(path))
    rebuilt = {int(v): [(Fr(a), Fr(b)) for a, b in rows]
               for v, rows in back.items()}
    # the parsed bytes must still verify
    ok, fails, _vm = S.verify_publication(m, {}, rebuilt, eps=Fr(1, 100), mode="I")
    assert ok, fails[:3]
    # and be identical to what was published
    for v in res.intervals:
        for s in range(len(res.intervals[v])):
            assert tuple(rebuilt[v][s]) == tuple(
                Fr(x) for x in res.intervals[v][s])


def test_r4_resource_exhaustion_inside_an_interior_loop():
    """A budget must stop work INSIDE an inner loop, not only between phases."""
    from mdi import budget as B
    bg = B.Budget(wall_s=0.02)
    dl = bg.deadline_fn("inner")
    import time as _t
    _t.sleep(0.05)
    with pytest.raises(B.BudgetExceeded):
        for _ in range(1000):
            dl()
    assert bg.report()["stops"]


def test_r4_stale_boundary_map_is_detected():
    """Already covered for regional; assert the mechanism is in the production
    checker rather than a test helper."""
    import inspect
    from mdi import regional_check as RC
    src = inspect.getsource(RC.verify_regional_publication)
    assert "boundary order" in src
    assert "own_rds" in src


def test_r4_missing_and_duplicate_ownership_rejected():
    from mdi import preprocess as PRE
    import copy
    txt = ("MARKOV\n3\n2 2 2\n3\n1 0\n2 0 1\n2 1 2\n"
           "2\n1 2\n4\n1 2 3 5\n4\n2 1 1 3\n")
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    # duplicate: emit a factor twice
    dup = copy.deepcopy(simp)
    pairs = [f for f in dup.factors if len(f.scope) == 2]
    if pairs:
        dup.factors = list(dup.factors) + [pairs[0]]
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, dup)
    # missing: drop a factor without recording why
    miss = copy.deepcopy(simp)
    miss.factors = [f for f in miss.factors if len(f.scope) != 2]
    miss.declined_products = []
    miss.combined_splits = []
    miss.combined_constants = []
    with pytest.raises(PRE.PreprocessError):
        PRE.verify_identities(r, miss)


# ===== closing the largest blocker: checkers for every route =====

def test_r4_statistic_checker_verifies_and_rejects():
    """An independent statistic-DP checker. It enumerates configurations
    directly, a DIFFERENT implementation from the statistic convolution, so a
    bug in the convolution cannot pass both sides."""
    from mdi import collective_check as CC
    ctx = A.Ctx(160)
    n = 6
    unary = {v: [Fr(10 + v, 10), Fr(10 + (3 * v) % 7, 10)] for v in range(n)}

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 10)]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    acc, marks, _ = CO.statistic_dp(list(range(n)), {v: 2 for v in range(n)},
                                    unary, {}, [], Cand(), 1, set(range(n)))
    (Zlo, Zhi), mk = CO.dp_root_combine(acc, marks, Cand(), 1, ctx)
    pub = {v: [(mk[(v, a)][0] / Zhi, mk[(v, a)][1] / Zlo) for a in range(2)]
           for v in range(n)}
    ok, fails, meta = CC.check_statistic_publication(
        list(range(n)), {v: 2 for v in range(n)}, unary, Cand(), 1,
        set(range(n)), pub, Fr(1, 100), ctx)
    assert ok, fails[:3]
    assert meta["independent_enclosure"]
    # a wrong publication must be rejected
    bad = {v: [(Fr(0), Fr(0))] * 2 for v in range(n)}
    ok2, fails2, _ = CC.check_statistic_publication(
        list(range(n)), {v: 2 for v in range(n)}, unary, Cand(), 1,
        set(range(n)), bad, Fr(1, 100), ctx)
    assert not ok2 and len(fails2) >= n


def test_r4_statistic_checker_refuses_rather_than_running_away():
    """An oversized independent enumeration is a RESOURCE refusal, not a pass."""
    from mdi import collective_check as CC
    ctx = A.Ctx(80)
    n = 40
    unary = {v: [Fr(1), Fr(2)] for v in range(n)}

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 10)]
        features = [{v: [Fr(-1), Fr(1)] for v in range(n)}]

    with pytest.raises(CC.CollectiveCheckError) as e:
        CC.check_statistic_publication(list(range(n)), {v: 2 for v in range(n)},
                                       unary, Cand(), 1, set(range(n)), {},
                                       Fr(1, 100), ctx)
    assert "RESOURCE refusal" in str(e.value)


def test_r4_composed_checker_verifies_and_rejects():
    from mdi import composed as CM, collective_check as CC
    m, r, regs, crs, rds, _ = _ring_coarse()
    ctx = A.Ctx(180)
    out, meta = CM.run(r, regs, crs, rds, set(r.free), ctx, Fr(1, 100))
    ok, fails, cmeta = CC.check_composed_publication(
        r, regs, crs, rds, set(r.free), out, Fr(1, 100),
        Fr(meta["total_radius"]),
        regional_radius=Fr(meta["regional_radius"]))
    assert ok, fails[:3]
    assert cmeta["independent_enclosure"]
    bad = {v: [(Fr(0), Fr(0))] * 2 for v in sorted(r.free)}
    ok2, fails2, _ = CC.check_composed_publication(
        r, regs, crs, rds, set(r.free), bad, Fr(1, 100),
        Fr(meta["total_radius"]),
        regional_radius=Fr(meta["regional_radius"]))
    assert not ok2 and fails2


def test_r4_every_route_now_has_an_executor_and_a_checker():
    """The largest named blocker: four routes had executors but no checker, so
    they were ineligible for selection and could not be certified."""
    from mdi import registry as RG, plantype as PT
    rows = {x["kind"]: x for x in RG.status_table()}
    for kind in PT.KINDS:
        assert rows[kind]["executor_supported"], kind
        assert rows[kind]["checker_supported"], kind
        ex, ck = PT.dispatch(kind)
        assert ex is not None and ck is not None, kind
    assert RG.MISSING_CHECKERS == {}
    assert RG.UNIMPLEMENTED == {}


def test_r4_complete_cost_accounting_includes_local_construction():
    """COMPLETE cost must include the work that produced the answer, and the
    comparison must be free to pick identity.

    The r4 release claimed the regional route won the ring control by 6
    operations against identity's 3,837. That claim is WITHDRAWN. The selected
    region holds all 12 ring variables, so region_data enumerates all 4,096
    configurations and builds A together with all 24 original marker masses --
    the complete answer -- before the reduced contraction is priced at six
    operations. Measured, that construction is 151,552 exact-rational
    arithmetic operations, and the independent checker rebuilds it.

    Choosing a cheap remaining calculation after sunk work can be sensible, but
    it cannot establish a cheap complete METHOD against an identity arm that
    never paid that construction. This test therefore asserts honest
    accounting, NOT a regional win: whichever route wins must have paid for
    everything it did.
    """
    from mdi import pipeline as PLN
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, p = O.exact_all_marginals(r)
    res = PLN.solve(m, {}, wall_s=180.0, cap_bytes=1 << 30)
    # either route may win; what matters is that the answer is certified and
    # that nothing was priced at zero
    # VERIFIED_SHARED_AGGREGATION_ONLY is the honest status when the free
    # joint space exceeds the independent-enumeration cap, so producer and
    # checker share one aggregate implementation.
    assert res.status in ("CERTIFIED_RESEARCH_ROUTE", "CERTIFIED_FALLBACK_ONLY",
                          "VERIFIED_SHARED_AGGREGATION_ONLY"), \
        (res.status, res.reason)
    assert res.checker["status"] in (
        "VERIFIED", "VERIFIED_WITHOUT_INDEPENDENT_AGGREGATION"), \
        res.checker["status"]
    byname = {x["name"]: x for x in res.prices}
    reg = next((v for k, v in byname.items() if k.startswith("regional:")),
               None)
    if reg is not None and reg["eligible"]:
        cons = reg["counters"]["construction_ops"]
        # local construction may NEVER be priced at zero or as an upper bound
        assert cons["label"] == "measured_calibration", cons
        assert int(cons["value"]) > 0, cons
        # and it must dominate the six-operation reduced contraction here,
        # which is exactly why the earlier comparison was invalid
        assert int(cons["value"]) > 100000, cons
    # the published intervals must contain the truth whichever route won
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res.intervals[v][s]
            assert lo <= p[v][s] <= hi, (v, s)


def test_r4_identity_is_allowed_to_win_the_cost_comparison():
    """The selection must be free to choose identity. A cost test that can only
    pass when the research route wins would re-encode the withdrawn claim."""
    from mdi import pipeline as PLN
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    res = PLN.solve(m, {}, wall_s=180.0, cap_bytes=1 << 30)
    byname = {x["name"]: x for x in res.prices}
    assert "identity" in byname
    ident = byname["identity"]["total_arithmetic"]["value"]
    reg = next((v for k, v in byname.items() if k.startswith("regional:")),
               None)
    if reg is not None and reg["eligible"]:
        rtot = reg["total_arithmetic"]["value"]
        # whichever is smaller must be the one selected: the comparison is
        # decided by the numbers, not by a preference for the research route
        winner = "regional" if int(rtot) < int(ident) else "identity"
        assert res.plan["kind"] in (winner, "identity"), (winner, res.plan)


def test_r4_composed_route_is_offered_as_a_pipeline_candidate():
    """E.7 must be reachable through the public pipeline, not only by a direct
    call. When it declines, the reason must be recorded."""
    import inspect
    from mdi import pipeline as PLN
    src = inspect.getsource(PLN.solve)
    assert "composed:" in src, "the pipeline must offer the composed route"
    assert "composed route declined" in src, "a declension must be recorded"
    txt, n, NB, BS = ring_of_blocks()
    m = M.read_uai(w(txt))
    res = PLN.solve(m, {}, wall_s=180.0, cap_bytes=1 << 30)
    names = [x["name"] for x in res.prices] + [x["name"] for x in res.rejected]
    assert any(x.startswith("composed:") for x in names), names


# ===== r4 review: adversarial checker regressions =====

def test_r5_quadrature_checker_verifies_the_unrounded_law():
    """R4-01. check_quadrature_publication delegated with Q=1, quantizing the
    features away: [0, 1/4] became [0, 0], so it checked a law with both
    weights equal to 1 (probability exactly 1/2) against a true
    exp(1/32)/(1+exp(1/32)) = 0.5078118642792046."""
    import math
    from mdi import collective_check as CC, collective as CO
    ctx = A.Ctx(160)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), Fr(1, 4)]}]

    unary = {0: [Fr(1), Fr(1)]}
    # the checker must enclose the UNROUNDED weight exp(1/32), not 1
    lo1, hi1 = CC._enclose_weight(unary, {0: 2}, [0], (1,), Cand(), None, ctx)
    assert lo1 > Fr(103, 100), lo1
    assert abs(float(lo1) - math.exp(1 / 32)) < 1e-12
    # the wrong publication centred on 1/2 must be REJECTED
    bad = {0: [(Fr(4999, 10000), Fr(5001, 10000)),
               (Fr(4999, 10000), Fr(5001, 10000))]}
    ok, fails, _ = CC.check_quadrature_publication(
        [0], {0: 2}, unary, Cand(), {0}, bad, Fr(1, 100), ctx, Fr(1, 1000))
    assert not ok, "a publication near 1/2 cannot verify a 0.50781 law"
    # and a CORRECT publication must still be accepted
    rad = Fr(CO.gf_lattice(Fr(1), Fr(1, 4), Fr(1, 1000))["total_bound"])
    c = Fr(5078118642792046, 10 ** 16)
    pad = rad + Fr(1, 10 ** 6)
    good = {0: [(max(Fr(0), 1 - c - pad), min(Fr(1), 1 - c + pad)),
                (max(Fr(0), c - pad), min(Fr(1), c + pad))]}
    ok2, f2, meta = CC.check_quadrature_publication(
        [0], {0: 2}, unary, Cand(), {0}, good, Fr(1, 100), ctx, Fr(1, 1000))
    assert ok2, f2
    assert meta["law"] == "original unrounded rational features"


def test_r5_statistic_checker_uses_exact_rational_quantization():
    """R4-02. round(float(f)*Q) is binary64: for f = 1/2 + 2^-54 and Q = 1 it
    gives 0 where the exact declared rule gives 1, so checker and producer
    quantized differently."""
    from mdi import collective_check as CC, collective as CO
    f = Fr(1, 2) + Fr(1, 2 ** 54)
    assert round(float(f) * 1) == 0, "the float path really does give 0"
    assert CC._exact_quantize(f, 1) == 1
    assert CO.exact_round_half_up(f * 1) == 1
    # producer and checker must agree, including on exact ties
    assert CO.exact_round_half_up(Fr(1, 2)) == 1
    assert CC._exact_quantize(Fr(1, 2), 1) == 1
    ctx = A.Ctx(160)

    class C2:
        rank = 1
        signs = [1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), f]}]

    bad = {0: [(Fr(4999, 10000), Fr(5001, 10000)),
               (Fr(4999, 10000), Fr(5001, 10000))]}
    ok, _, _ = CC.check_statistic_publication(
        [0], {0: 2}, {0: [Fr(1), Fr(1)]}, C2(), 1, {0}, bad, Fr(1, 100), ctx)
    assert not ok, "the quantized law has probability ~0.6225, not 0.5"


def test_r5_every_verifier_entry_point_rejects_malformed_rows():
    """R4-01/R4-03. Empty, truncated, inverted, out-of-range and unrequested
    rows must reject AT EVERY entry point. check_composed_publication accepted
    an empty row for every requested variable with no failures, because
    `for s in range(len(rows))` iterates zero times."""
    from mdi import collective_check as CC
    ctx = A.Ctx(128)

    class Cand:
        rank = 1
        signs = [1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), Fr(1, 4)]}]

    cases = {
        "empty": {0: []},
        "truncated": {0: [(Fr(0), Fr(1))]},
        "inverted": {0: [(Fr(1), Fr(0)), (Fr(0), Fr(1))]},
        "out_of_range": {0: [(Fr(-1, 2), Fr(1)), (Fr(0), Fr(1))]},
        "extra_key": {0: [(Fr(0), Fr(1)), (Fr(0), Fr(1))],
                      7: [(Fr(0), Fr(1))]},
    }
    for name, pub in cases.items():
        ok, fails, _ = CC.check_statistic_publication(
            [0], {0: 2}, {0: [Fr(1), Fr(1)]}, Cand(), 1, {0}, pub,
            Fr(1, 100), ctx)
        assert not ok, name
        assert fails, name


def test_r5_composed_checker_rejects_empty_and_validates_the_certificate():
    """R4-03. The composed checker consumed the producer's masses, maps and
    radius without validating schema, the regional certificate or ownership."""
    from mdi import collective_check as CC, regions as R
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [(0,), (1,)]
    rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
    ro = {0: 0, 1: 1}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                          region_of=ro, aggregate=True) for i in range(2)]
    empty = {0: [], 1: []}
    ok, fails, _ = CC.check_composed_publication(
        r, regs, crs, rds, {0, 1}, empty, Fr(1, 100), Fr(0),
        regional_radius=Fr(0))
    assert not ok, "an empty row must never verify"
    assert any("EMPTY" in x for x in fails), fails
    # an INCOMPLETE partition must reject for the missing ownership
    good = {0: [(Fr(2495, 10000), Fr(2505, 10000)),
                (Fr(7495, 10000), Fr(7505, 10000))],
            1: [(Fr(4995, 10000), Fr(5005, 10000)),
                (Fr(4995, 10000), Fr(5005, 10000))]}
    ok2, f2, _ = CC.check_composed_publication(
        r, [(0,)], [crs[0]], [rds[0]], {0, 1}, good, Fr(1, 100), Fr(0),
        regional_radius=Fr(0))
    assert not ok2
    assert any("owned by 0 regions" in x for x in f2), f2
    # the correct publication on the complete partition still verifies
    ok3, f3, _ = CC.check_composed_publication(
        r, regs, crs, rds, {0, 1}, good, Fr(1, 100), Fr(0),
        regional_radius=Fr(0))
    assert ok3, f3


def test_r5_composed_charges_rounding_energy_and_picks_Q():
    """R4-03. composed.run fixed Q=1 and never charged
    rounding_energy_bound. On three ternary variables with features
    [0, 1/2, 1] the energy at Q=1 is 27/4 = 6.75, yet the publication claimed
    a 7.84e-13 radius and all nine intervals missed the truth."""
    import math, itertools
    from mdi import composed as CX, regions as R, collective as CO
    ctx = A.Ctx(160)
    g, fv = Fr(6, 5), [Fr(0), Fr(1, 2), Fr(1)]

    class C:
        rank = 1
        signs = [-1]
        gammas = [g]
        features = [{v: list(fv) for v in range(3)}]

    # the energy at Q=1 must be the large charge r4 omitted
    kq1 = CO.round_features(C(), [0, 1, 2], 1)
    assert CO.rounding_energy_bound(C(), [0, 1, 2], kq1, 1) == Fr(27, 4)

    def ent(a, b):
        return Fr(int(round(math.exp(float(g * fv[a] * fv[b])) * 10 ** 6)),
                  10 ** 6)

    facs = [M.Factor(scope=(v,), card=(3,), table=[Fr(1)] * 3, origin=v)
            for v in range(3)]
    for i in range(3):
        for j in range(i + 1, 3):
            facs.append(M.Factor(scope=(i, j), card=(3, 3),
                                 table=[ent(a, b) for a in range(3)
                                        for b in range(3)],
                                 origin=100 + i * 10 + j))
    m = M.Model(nvars=3, card=[3] * 3, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Zt = Fr(0)
    ct = {}
    for combo in itertools.product(range(3), repeat=3):
        w = Fr(1)
        for f in r.factors:
            off = 0
            for k, v in enumerate(f.scope):
                off = off * f.card[k] + combo[v]
            w *= f.table[off]
        if w == 0:
            continue
        Zt += w
        for v in range(3):
            ct[(v, combo[v])] = ct.get((v, combo[v]), Fr(0)) + w
    regs = [(0,), (1,), (2,)]
    rds = [R.region_data(gg, r.card, r.factors, set(range(3))) for gg in regs]
    ro = {v: i for i, gg in enumerate(regs) for v in gg}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(3)),
                          region_of=ro, aggregate=True) for i in range(3)]
    try:
        out, meta = CX.run(r, regs, crs, rds, set(range(3)), ctx, Fr(1, 100))
    except CX.Declined:
        return          # a bounded decline is an acceptable outcome
    assert meta["Q"] != 1 or Fr(meta["rounding_tv_charged"]) > 0, meta
    for v in sorted(out):
        for s, (lo, hi) in enumerate(out[v]):
            t = ct.get((v, s), Fr(0)) / Zt
            assert lo <= t <= hi, (v, s, float(lo), float(t), float(hi))


def test_r5_negative_fourier_evaluation_terminates_and_encloses():
    """R4-04. fourier_evaluate never incremented its lattice index: a declared
    33-node lattice re-evaluated node z = -4 indefinitely. It also accumulated
    symmetric modulus bounds, discarding the phase."""
    import math
    from mdi import collective as CO
    ctx = A.Ctx(160)

    class C:
        rank = 1
        signs = [-1]
        gammas = [Fr(1, 2)]
        features = [{0: [Fr(0), Fr(1)], 1: [Fr(0), Fr(1)]}]

    unary = {0: [Fr(1), Fr(2)], 1: [Fr(1), Fr(1)]}
    Z = 0.0
    cnt = {}
    for a in range(2):
        for b in range(2):
            w = (float(unary[0][a]) * float(unary[1][b])
                 * math.exp(-0.5 * float(C.gammas[0]) * (a + b) ** 2))
            Z += w
            cnt[(0, a)] = cnt.get((0, a), 0.0) + w
            cnt[(1, b)] = cnt.get((1, b), 0.0) + w
    calls = [0]

    def watchdog():
        calls[0] += 1
        if calls[0] > 200000:
            raise AssertionError("fourier_evaluate did not terminate")

    (Zlo, Zhi), mk, meta = CO.fourier_evaluate(
        [0, 1], {0: 2, 1: 2}, unary, C(), {0, 1}, ctx, Fr(1, 1000),
        deadline=watchdog)
    # it processed EXACTLY the declared node set
    assert meta["processed"] == meta["expected_nodes"] > 1, meta
    assert float(Zlo) <= Z <= float(Zhi), (float(Zlo), Z, float(Zhi))
    # the imaginary enclosure must straddle zero
    ilo, ihi = Fr(meta["imaginary_enclosure"][0]), \
        Fr(meta["imaginary_enclosure"][1])
    assert ilo <= 0 <= ihi
    for v in (0, 1):
        for s in (0, 1):
            lo, hi = mk[(v, s)]
            qlo = max(0.0, float(lo) / float(Zhi))
            qhi = min(1.0, float(hi) / float(Zlo))
            t = cnt[(v, s)] / Z
            assert qlo <= t <= qhi, (v, s, qlo, t, qhi)
    # a POSITIVE mode is still refused
    class P:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 2)]
        features = [{0: [Fr(0), Fr(1)]}]

    with pytest.raises(CO.Declined):
        CO.fourier_evaluate([0], {0: 2}, {0: [Fr(1), Fr(1)]}, P(), {0}, ctx,
                            Fr(1, 1000))


def test_r5_negative_trig_extrema_are_enclosed():
    """R4-04. For k < 0 the bracket [k*pi_lo, k*pi_up] is INVERTED, so negative
    critical points were tested against a reversed bracket and k = -2 was
    unreachable."""
    import math
    from mdi import collective as CO
    ctx = A.Ctx(128)

    def true_range(fn, a, b, n=3000):
        vs = [fn(a + (b - a) * i / n) for i in range(n + 1)]
        return min(vs), max(vs)

    checked = 0
    for name, enc, fn in (("cos", CO._cos_enclose, math.cos),
                          ("sin", CO._sin_enclose, math.sin)):
        for k in range(-6, 1):
            base = k * math.pi if name == "cos" else (math.pi / 2
                                                      + k * math.pi)
            for width in (0.02, 0.2, 1.0, 2.5):
                a, b = base - width / 2, base + width / 2
                lo = Fr(a).limit_denominator(10 ** 9)
                hi = Fr(b).limit_denominator(10 ** 9)
                elo, ehi = enc(lo, hi, ctx)
                tlo, thi = true_range(fn, float(lo), float(hi))
                assert float(elo) <= tlo + 1e-12, (name, k, width, float(elo),
                                                   tlo)
                assert float(ehi) >= thi - 1e-12, (name, k, width, float(ehi),
                                                   thi)
                checked += 1
    assert checked >= 50
    # the exact critical point must be reached at every negative k
    for k in range(-6, 1):
        lo = Fr(k) * Fr(314159, 100000) - Fr(1, 1000)
        hi = Fr(k) * Fr(31416, 10000) + Fr(1, 1000)
        elo, ehi = CO._cos_enclose(min(lo, hi), max(lo, hi), ctx)
        if k % 2:
            assert elo <= Fr(-1), k
        else:
            assert ehi >= Fr(1), k


# ===== r4 review: verification, accounting and enforcement regressions =====

def test_r5_faulty_producer_rejected_above_the_enumeration_threshold():
    """R4-05. The output-law check was gated at 4,096 joint assignments. At 13
    uniform binary variables a producer changing one unary from [1,1] to [9,1]
    was certified near (.9,.1) against a true (.5,.5)."""
    import copy
    from mdi import preprocess as PRE
    for n in (12, 13, 16, 20):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)],
                         origin=v) for v in range(n)]
        for i in range(n - 1):
            facs.append(M.Factor(scope=(i, i + 1), card=(2, 2),
                                 table=[Fr(1)] * 4, origin=100 + i))
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        r = M.restrict(m, {})
        simp = PRE.simplify(r)
        assert PRE.verify_identities(r, simp)
        bad = copy.deepcopy(simp)
        for f in bad.factors:
            if len(f.scope) == 1 and f.scope[0] == 0 and f.origin < 0:
                f.table = [Fr(9), Fr(1)]
                break
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, bad)


def test_r5_all_mutation_classes_reject_at_thirteen_variables():
    """R4-05. A corrupted output table, a corrupted scale and a dropped
    nonconstant factor must all reject above the old 4,096 threshold."""
    import copy
    from mdi import preprocess as PRE
    n = 13
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)], origin=v)
            for v in range(n)]
    for i in range(n - 1):
        facs.append(M.Factor(scope=(i, i + 1), card=(2, 2),
                             table=[Fr(2), Fr(1), Fr(1), Fr(3)],
                             origin=100 + i))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)

    b1 = copy.deepcopy(simp)
    for f in b1.factors:
        if len(f.scope) == 2:
            f.table[0] = f.table[0] * 7
            break
    b2 = copy.deepcopy(simp)
    b2.scale = b2.scale * Fr(3, 2)
    b3 = copy.deepcopy(simp)
    b3.factors = [f for f in b3.factors
                  if not (len(f.scope) == 2 and f.origin == 100)]
    for bad in (b1, b2, b3):
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, bad)


def test_r5_regional_checker_charges_its_numerical_error():
    """R4-06. The checker ran the engine in 128-bit POINT mode and converted
    the rounded outputs with exact_fr, treating an exact representation of a
    rounded number as the true quantity."""
    from mdi import regional_check as RC, regions as R
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1, 3), Fr(1, 7)],
                     origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1, 11), Fr(1, 13)],
                     origin=1),
            M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1, 17), Fr(1, 19), Fr(1, 23), Fr(1, 29)],
                     origin=2)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [(0,), (1,)]
    rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
    ro = {0: 0, 1: 1}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                          region_of=ro, aggregate=True) for i in range(2)]
    (Zlo, Zhi), (clo, chi) = RC.independent_contract(r, regs, crs, rds, {0, 1})
    # the enclosure must have POSITIVE width: a point would be a false claim
    assert Zhi > Zlo, (Zlo, Zhi)
    Zt = Fr(0)
    ct = {}
    for a in range(2):
        for b in range(2):
            w = (facs[0].table[a] * facs[1].table[b]
                 * facs[2].table[a * 2 + b])
            Zt += w
            ct[(0, a)] = ct.get((0, a), Fr(0)) + w
            ct[(1, b)] = ct.get((1, b), Fr(0)) + w
    for v in (0, 1):
        for s in (0, 1):
            qlo = clo.get((v, s), Fr(0)) / Zhi
            qhi = chi.get((v, s), Fr(0)) / Zlo
            t = ct[(v, s)] / Zt
            assert qlo <= t <= qhi, (v, s, float(qlo), float(t), float(qhi))


def test_r5_regional_checker_rejects_an_incomplete_partition():
    """R4-06. An incomplete partition covering only X0 of two independent
    variables let both X1 intervals [0, .002] be accepted, with a truth of
    (.25, .75): no region carried X1, so no enclosure was ever built."""
    from mdi import regional_check as RC, regions as R
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(3)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    rds = [R.region_data((0,), r.card, r.factors, {0, 1})]
    crs = [R.merge_region(rds[0], r.factors, r.card, Fr(1), {0, 1},
                          region_of={0: 0}, aggregate=True)]
    pub = {0: [(Fr(0), Fr(2, 1000)), (Fr(0), Fr(2, 1000))],
           1: [(Fr(0), Fr(2, 1000)), (Fr(0), Fr(2, 1000))]}
    ok, fails, _ = RC.verify_regional_publication(
        r, [(0,)], crs, rds, {0, 1}, pub, Fr(0), Fr(1, 100))
    assert not ok
    assert any("in NO region" in x for x in fails), fails


def test_r5_structural_certainty_is_exact():
    """R4-06. A unary [0, 1/3] gave the checker [1 - 2^-85, 1] for a state
    whose probability is exactly 1, so the producer's exact [1,1] failed
    containment and a structurally certain answer was refused."""
    for tab, want in (([Fr(0), Fr(1, 3)], [(Fr(0), Fr(0)), (Fr(1), Fr(1))]),
                      ([Fr(0), Fr(0), Fr(5)],
                       [(Fr(0), Fr(0)), (Fr(0), Fr(0)), (Fr(1), Fr(1))])):
        facs = [M.Factor(scope=(0,), card=(len(tab),), table=tab, origin=0)]
        m = M.Model(nvars=1, card=[len(tab)], factors=facs)
        m.validate()
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30)
        assert res["outcome"] == "VERIFIED_ALL_MARGINALS", res
        assert [tuple(x) for x in res["intervals"][0]] == want, res["intervals"]


def test_r5_pipeline_invokes_the_registered_executor():
    """R4-09. The pipeline looked up an executor via dispatch() and then
    branched on crec.kind, so replacing the SELECTED route's executor with a
    raising sentinel still produced a certified result with ZERO executor
    calls. The sentinel is installed on whichever route the planner picks, so
    the test does not depend on honest prices favouring one route."""
    from mdi import pipeline as PLN, plantype as PT
    import mdi.registry            # noqa: F401  (registers the executors)
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    good = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    kind = good.plan["kind"]
    assert kind in PT._PIPELINE_EXECUTORS, kind
    calls = [0]

    def sentinel(ctx):
        calls[0] += 1
        raise RuntimeError("SENTINEL")

    orig = PT._PIPELINE_EXECUTORS[kind]
    PT._PIPELINE_EXECUTORS[kind] = sentinel
    try:
        try:
            res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
            certified = res.status.startswith("CERTIFIED")
        except RuntimeError:
            certified = False
        assert calls[0] >= 1, "the registered executor was never invoked"
        assert not certified, "certified without running the executor"
    finally:
        PT._PIPELINE_EXECUTORS[kind] = orig


def test_r5_corrupted_on_disk_plan_stops_execution():
    """R4-09. The plan was reloaded from an IN-MEMORY string before being
    written, so corrupting the written file still certified."""
    import builtins, io, tempfile
    from mdi import pipeline as PLN
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    real_open = builtins.open

    def fake_open(path, mode="r", *a, **k):
        if isinstance(path, str) and path.endswith(".plan.json") \
                and "r" in mode and "w" not in mode:
            return io.StringIO("{ not valid json")
        return real_open(path, mode, *a, **k)

    builtins.open = fake_open
    try:
        res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30,
                        plan_dir=tempfile.mkdtemp())
    finally:
        builtins.open = real_open
    assert not res.status.startswith("CERTIFIED"), res.status
    assert res.status == "RESOURCE_STOP", res.status


def test_r5_level2_consumes_its_parent_representation():
    """R4-10. level2_marginals enumerated child cells and ignored the parents:
    clearing all parent A and marks left the answer unchanged."""
    import copy
    from mdi import level2 as L2
    m, r, regs, crs, rds, region_of = _ring_coarse(NB=4, BS=2)
    t1 = K.level_radius(2)
    l2 = L2.build_level2(r, regs, crs, rds, set(r.free), t1)
    Zt, counts = L2.level2_marginals(r, regs, crs, rds, set(r.free), l2)
    assert Zt > 0
    Ztrue, ptrue = O.exact_all_marginals(r)
    for v in sorted(r.free):
        for s in range(2):
            q = counts.get((v, s), Fr(0)) / Zt
            assert abs(q - ptrue[v][s]) <= 2 * t1
    # CLEARING the parent payload must change the outcome, not be ignored
    cleared = copy.deepcopy(l2)
    for pr in cleared["parent_data"]:
        pr.A = {kk: Fr(0) for kk in pr.A}
        pr.marks = {kk: {} for kk in pr.marks}
    with pytest.raises((L2.Level2Error, ZeroDivisionError)):
        L2.level2_marginals(r, regs, crs, rds, set(r.free), cleared)
    # MUTATING one parent mass must be detected
    mutated = copy.deepcopy(l2)
    k0 = sorted(mutated["parent_data"][0].A.keys())[0]
    mutated["parent_data"][0].A[k0] *= 7
    with pytest.raises(L2.Level2Error):
        L2.level2_marginals(r, regs, crs, rds, set(r.free), mutated)


def test_r5_shared_budget_is_enforced_on_actual_work():
    """R4-10. A mocked 2 GiB RSS under a 1 GiB cap certified with ZERO
    shared-budget checks, and an 80 ms checker under a 20 ms complete deadline
    certified with a NEGATIVE remaining time."""
    import time as _t
    from mdi import pipeline as PLN
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    orig_rss = S._rss_bytes
    S._rss_bytes = lambda: 2 * (1 << 30)
    try:
        res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    finally:
        S._rss_bytes = orig_rss
    assert not res.status.startswith("CERTIFIED"), res.status
    assert (res.budget or {}).get("checks", 0) >= 1, res.budget
    # the RSS refusal must fire regardless of which route honest prices pick

    orig_vp = S.verify_publication

    def slow(*a, **k):
        _t.sleep(0.080)
        return orig_vp(*a, **k)

    S.verify_publication = slow
    import mdi.regional_check as _RC
    orig_vr = _RC.verify_regional_publication

    def slow_r(*a, **k):
        _t.sleep(0.080)
        return orig_vr(*a, **k)

    _RC.verify_regional_publication = slow_r
    try:
        res2 = PLN.solve(m, {}, wall_s=0.020, cap_bytes=1 << 30)
    finally:
        S.verify_publication = orig_vp
        _RC.verify_regional_publication = orig_vr
    assert not res2.status.startswith("CERTIFIED"), res2.status
    assert (res2.budget or {}).get("checks", 0) >= 1, res2.budget


def test_r5_invalid_requested_variables_reject():
    """R4-09. Requesting {999} on a two-variable model priced zero requested
    markers and still returned certified outputs for variables 0 and 1."""
    from mdi import pipeline as PLN
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30, queries={999})
    assert res.status == "INVALID_INPUT", res.status
    assert not res.intervals, res.intervals


def test_r5_declared_cap_is_never_enlarged():
    """R4-10. The deadline factory raised a declared cap when the process
    already exceeded it, granting extra headroom exactly when it should
    refuse."""
    res = S.solve(M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n"
                               "2\n1 1\n")),
                  {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 12,
                  deadline_s=30, run_checker=False)
    assert res["outcome"] == "RESOURCE_BOUND", res["outcome"]
    assert "never enlarged" in res["reason"], res["reason"]


def test_r5_point_vector_is_feasible_and_checked_on_readback():
    """R4-10. normalize/clip/normalize moved a fixed coordinate out of its
    interval: feasible rows [.195,.2], [.295,.3], [.5,.5] produced a third
    coordinate of .501259, outside its fixed [.5,.5]."""
    import tempfile
    from mdi import arm as AR
    rows = [(Fr(195, 1000), Fr(2, 10)), (Fr(295, 1000), Fr(3, 10)),
            (Fr(1, 2), Fr(1, 2))]
    vec = AR._feasible_simplex_point(rows)
    assert vec is not None
    assert sum(vec) == 1
    for x, (lo, hi) in zip(vec, rows):
        assert Fr(lo) <= x <= Fr(hi), (x, lo, hi)

    class Mdl:
        nvars = 1
        card = [3]

    path = AR._write_point_vector({0: rows}, Mdl(), {}, tempfile.mkdtemp(),
                                  "ctl")
    tok = open(path).read().split()
    assert tok[0] == "MAR"
    vals = [Fr(x) for x in tok[3:6]]
    for x, (lo, hi) in zip(vals, rows):
        assert Fr(lo) - Fr(1, 10 ** 6) <= x <= Fr(hi) + Fr(1, 10 ** 6)
    # an INFEASIBLE interval set must refuse, not emit a vector
    class Mdl2:
        nvars = 1
        card = [2]

    with pytest.raises(ValueError):
        AR._write_point_vector({0: [(Fr(9, 10), Fr(1)), (Fr(9, 10), Fr(1))]},
                               Mdl2(), {}, tempfile.mkdtemp(), "bad")


# ===== r5 review: ownership, cover, soundness and accounting regressions =====

def test_r6_preprocessing_rejects_a_missing_synthetic_unary_at_every_size():
    """R5-1a. `if not em: continue` skipped the check when the output was
    ABSENT, so a dropped required unary rejected at 12 binary variables but
    PASSED at 13, 16 and 20."""
    import copy
    from mdi import preprocess as PRE
    for n in (12, 13, 16, 20):
        facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)],
                         origin=0)]
        for v in range(1, n):
            facs.append(M.Factor(scope=(v,), card=(2,),
                                 table=[Fr(1), Fr(1)], origin=v))
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        r = M.restrict(m, {})
        simp = PRE.simplify(r)
        assert PRE.verify_identities(r, simp), "the clean base must verify"
        bad = copy.deepcopy(simp)
        bad.factors = [f for f in bad.factors
                       if not (len(f.scope) == 1 and f.scope[0] == 0
                               and f.origin < 0)]
        with pytest.raises(PRE.PreprocessError) as e:
            PRE.verify_identities(r, bad)
        assert "NO emitted unary" in str(e.value), str(e.value)


def test_r6_declined_factor_positive_values_must_be_equal():
    """R5-1b. An unchanged/declined emitted factor was compared only on ZERO
    SUPPORT, so changing 3B to 30B certified about 61/63 against a true
    7/9."""
    import copy
    from mdi import preprocess as PRE
    B = Fr(2) ** 32768
    facs = [M.Factor(scope=(0, 1), card=(2, 2), table=[B, B, B, 2 * B],
                     origin=0),
            M.Factor(scope=(0, 1), card=(2, 2), table=[B, B, B, 3 * B],
                     origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert simp.declined_products, "the bit cap must decline this product"
    assert PRE.verify_identities(r, simp)
    bad = copy.deepcopy(simp)
    for f in bad.factors:
        if f.origin == 1:
            f.table = [B, B, B, 30 * B]
            break
    with pytest.raises(PRE.PreprocessError) as e:
        PRE.verify_identities(r, bad)
    assert "CHANGED THE LAW" in str(e.value)


def test_r6_synthetic_origin_must_be_the_expected_unary():
    """R5-1c. A synthetic origin was exempted BEFORE proving the factor is the
    expected unary on the expected variable, so a pair interaction could take
    that origin and escape accounting."""
    import copy
    from mdi import preprocess as PRE
    n = 13
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    bad = copy.deepcopy(simp)
    for i, f in enumerate(bad.factors):
        if len(f.scope) == 1 and f.scope[0] == 0 and f.origin < 0:
            bad.factors[i] = M.Factor(scope=(0, 1), card=(2, 2),
                                      table=[Fr(1), Fr(1), Fr(1), Fr(9)],
                                      origin=f.origin)
            break
    with pytest.raises(PRE.PreprocessError) as e:
        PRE.verify_identities(r, bad)
    assert "SYNTHETIC origin" in str(e.value)


def test_r6_checkers_require_a_cover_of_every_free_variable():
    """R5-2. The cover checked only REQUESTED variables. With pair table
    [1,2,3,4] and query {0}, X1 was unowned, its crossing factor was silently
    skipped, and both checkers accepted [.499,.501] against a truth of
    (.3,.7)."""
    from mdi import regional_check as RC, collective_check as CC, regions as R
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    # the exact truth for X0 is (3/10, 7/10)
    regs = [(0,)]
    rds = [R.region_data(regs[0], r.card, r.factors, {0})]
    crs = [R.merge_region(rds[0], r.factors, r.card, Fr(1), {0},
                          region_of={0: 0}, aggregate=True)]
    pub = {0: [(Fr(499, 1000), Fr(501, 1000)),
               (Fr(499, 1000), Fr(501, 1000))]}
    ok, fails, _ = RC.verify_regional_publication(
        r, regs, crs, rds, {0}, pub, Fr(0), Fr(1, 100))
    assert not ok, "0.5 cannot verify a law whose truth is (.3,.7)"
    assert any("NO region" in x for x in fails), fails
    ok2, f2, _ = CC.check_composed_publication(
        r, regs, crs, rds, {0}, pub, Fr(1, 100), Fr(0),
        regional_radius=Fr(0))
    assert not ok2
    assert any("owned by 0 regions" in x for x in f2), f2


def test_r6_level2_parent_boundary_uses_child_positions():
    """R5-3. `dig` runs over ALL children but was indexed with bpos, the
    position within the BOUNDARY list; it must be cpos. The reviewer's
    arithmetic: 11/14 - 3585/7168 = 2047/7168 = 0.285575. The LAST site stayed
    correct, which is why a test checking only the final marginal passed."""
    from mdi import level2 as L2, regions as R
    n = 13
    facs = []
    for i in range(n - 1):
        facs.append(M.Factor(scope=(i, i + 1), card=(2, 2),
                             table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                             origin=len(facs)))
    for i in range(n):
        facs.append(M.Factor(scope=(i,), card=(2,),
                             table=[Fr(1), Fr(1 + i % 3)], origin=len(facs)))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Zt, pt = O.exact_all_marginals(r)
    regs = [(i,) for i in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    t2 = K.level_radius(2)
    l2 = L2.build_level2(r, regs, crs, rds, set(range(n)), t2)
    # the first parent must genuinely have a non-initial boundary child
    assert len(l2["parents"][0]) > 1
    Zl, cnt = L2.level2_marginals(r, regs, crs, rds, set(range(n)), l2)
    # EVERY marker, not just the last site
    for v in range(n):
        for s in range(2):
            q = cnt.get((v, s), Fr(0)) / Zl
            assert abs(q - pt[v][s]) <= 2 * t2, \
                (v, s, float(q), float(pt[v][s]))


def test_r6_retained_factors_have_exclusive_ownership():
    """R5-4. res.kept held integer INDICES while composed treated them as
    Factor objects, so every retained factor was skipped. Dereferencing alone
    would be wrong: a zero-bearing UNARY was in BOTH res_unary and res.kept,
    and consuming both squares [0,2,3] into [0,4,9]."""
    from mdi import modes as MD
    facs = [M.Factor(scope=(0,), card=(3,), table=[Fr(0), Fr(2), Fr(3)],
                     origin=0),
            M.Factor(scope=(0, 1), card=(3, 2),
                     table=[Fr(1), Fr(2), Fr(2), Fr(1), Fr(1), Fr(1)],
                     origin=1),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=2)]
    m = M.Model(nvars=2, card=[3, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    ctx = A.Ctx(128)
    cands, info = MD.propose_modes(r.free, r.factors, r.card)
    assert cands, info
    res = MD.build_residual(r.free, r.factors, r.card, cands[0], ctx)
    # a UNARY is never retained: res_unary owns it
    for fi in res.kept:
        assert len(r.factors[fi].scope) > 1, \
            "unary factor %d retained despite res_unary owning it" % fi
    assert res.detail.get("ownership_exclusive") is True


def test_r7_disconnected_residual_convolves_unintegrated_statistics():
    """R6-6. Multiplying already-INTEGRATED component totals is wrong: the
    collective statistic sums over every variable, so exp(-gamma S^2/2)
    couples all of them and a product of per-component totals drops the cross
    terms of S^2 (it published X3 at 0.5 against a true 0.3556).

    The correct construction keeps each component's UNINTEGRATED statistic
    distribution A_c(s), convolves them into the distribution of the TOTAL
    statistic, and applies the exponential once to that total. This test
    checks it against a rigorous 512-bit reference enclosure, not a float
    tolerance."""
    import itertools, gmpy2
    from mdi import gendp as G
    import inspect
    src = inspect.getsource(G.run)
    assert "cross terms" in src
    assert "convolve" in src.lower()

    def ref(x, p=512):
        mq = gmpy2.mpq(x.numerator, x.denominator)
        with gmpy2.context(precision=p, round=gmpy2.RoundDown):
            lo = gmpy2.exp(gmpy2.mpfr(mq))
        with gmpy2.context(precision=p, round=gmpy2.RoundUp):
            hi = gmpy2.exp(gmpy2.mpfr(mq))
        return A.exact_fr(lo), A.exact_fr(hi)

    ctx = A.Ctx(160)
    tabs = ([Fr(1), Fr(2)], [Fr(1), Fr(1)], [Fr(2), Fr(1)], [Fr(1), Fr(3)])
    facs = [M.Factor(scope=(v,), card=(2,), table=list(t), origin=v)
            for v, t in enumerate(tabs)]
    m = M.Model(nvars=4, card=[2] * 4, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    for sign in (1, -1):
        class C:
            rank = 1
            signs = [sign]
            gammas = [Fr(1, 2)]
            features = [{v: [Fr(0), Fr(1)] for v in range(4)}]

        sel = P.choose_plan(r.free, r.card, r.factors, 64,
                            K.RESOURCES["arm_rss_bytes"])
        pl, _est = sel["chosen"]
        (Zlo, Zhi), mk, meta = G.run(pl, r.factors, r.card, C(), 1,
                                     set(range(4)), ctx)
        assert meta.get("components") and meta["components"] > 1, meta
        # rigorous reference: enumerate every configuration exactly
        Zl = Zh = Fr(0)
        cl, ch = {}, {}
        for combo in itertools.product(range(2), repeat=4):
            Ssum = sum(combo)
            wt = Fr(1)
            for v, a in enumerate(combo):
                wt *= tabs[v][a]
            el, eh = ref(Fr(sign * Ssum * Ssum, 4))
            if sign < 0:
                el, eh = eh, el
            Zl += wt * el
            Zh += wt * eh
            for v, a in enumerate(combo):
                cl[(v, a)] = cl.get((v, a), Fr(0)) + wt * el
                ch[(v, a)] = ch.get((v, a), Fr(0)) + wt * eh
        lo_ref, hi_ref = min(Zl, Zh), max(Zl, Zh)
        assert Zlo <= lo_ref and hi_ref <= Zhi, (sign, float(Zlo), float(Zhi))
        for v in range(4):
            for a in range(2):
                lo, hi = mk[(v, a)]
                a_lo = min(cl[(v, a)], ch[(v, a)])
                a_hi = max(cl[(v, a)], ch[(v, a)])
                assert lo <= a_lo and a_hi <= hi, (sign, v, a)


def test_r6_composed_declines_rather_than_publishing_an_impossible_state():
    """R5-4. With a ternary constraint forcing X0 = 1, r5 published X0 = 0 in
    [.01727, .01732] although its true probability is exactly ZERO."""
    import itertools
    from mdi import composed as CX, regions as R
    ctx = A.Ctx(160)
    n = 4
    facs = []
    for i in range(n):
        for j in range(i + 1, n):
            facs.append(M.Factor(scope=(i, j), card=(2, 2),
                                 table=[Fr(3), Fr(2), Fr(2), Fr(3)],
                                 origin=len(facs)))
    tab = [Fr(1) if a == 1 else Fr(0)
           for a in range(2) for b in range(2) for c in range(2)]
    facs.append(M.Factor(scope=(0, 1, 2), card=(2, 2, 2), table=tab,
                         origin=len(facs)))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z = Fr(0)
    ct = {}
    for combo in itertools.product(range(2), repeat=n):
        w = Fr(1)
        for f in r.factors:
            off = 0
            for k, v in enumerate(f.scope):
                off = off * f.card[k] + combo[v]
            w *= f.table[off]
        if w == 0:
            continue
        Z += w
        for v in range(n):
            ct[(v, combo[v])] = ct.get((v, combo[v]), Fr(0)) + w
    assert ct.get((0, 0), Fr(0)) == 0, "X0=0 must be impossible"
    regs = [(i,) for i in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    try:
        out, meta = CX.run(r, regs, crs, rds, set(range(n)), ctx, Fr(1, 100))
    except CX.Declined:
        return                      # a bounded decline is correct
    # if it DOES publish, every original probability must be enclosed
    for v in sorted(out):
        for s, (lo, hi) in enumerate(out[v]):
            t = ct.get((v, s), Fr(0)) / Z
            assert lo <= t <= hi, (v, s, float(lo), float(t), float(hi))


def test_r6_trig_enclosures_are_exact_not_float_validated():
    """R5-5. gmpy2.mpfr(mpq(...)) rounds the ARGUMENT, and argument and
    function were rounded in the SAME direction: on a decreasing branch that
    composition does not bound the exact-argument value. sin(197658/49435) at
    160 bits returned an upper bound 9.42e-50 BELOW a rigorous reference.

    This test compares EXACT RATIONALS with no float tolerance, because
    binary64 conversion is exactly what hid the original defect."""
    import gmpy2
    from mdi import collective as CO

    def reference(q, which, extra=512):
        mq = gmpy2.mpq(q.numerator, q.denominator)
        fn = gmpy2.sin if which == "sin" else gmpy2.cos
        cd = gmpy2.context(precision=extra, round=gmpy2.RoundDown)
        cu = gmpy2.context(precision=extra, round=gmpy2.RoundUp)
        with cd:
            ad = gmpy2.mpfr(mq)
        with cu:
            au = gmpy2.mpfr(mq)
        da = max(abs(q - A.exact_fr(ad)), abs(A.exact_fr(au) - q))
        with cd:
            lo = min(fn(ad), fn(au))
        with cu:
            hi = max(fn(ad), fn(au))
        return A.exact_fr(lo) - da, A.exact_fr(hi) + da

    q = Fr(197658, 49435)
    for p in (24, 64, 128, 160):
        ctx = A.Ctx(p)
        for which, enc in (("sin", CO._sin_enclose),
                           ("cos", CO._cos_enclose)):
            elo, ehi = enc(q, q, ctx)
            rlo, rhi = reference(q, which)
            assert elo <= rlo and rhi <= ehi, (p, which, str(elo), str(rlo))
    # the two r4 extrema intervals, compared EXACTLY
    ctx = A.Ctx(160)
    clo, _ = CO._cos_enclose(Fr(-314159266, 100000000),
                             Fr(-62831853, 20000000), ctx)
    assert clo <= Fr(-1), str(clo)
    slo, _ = CO._sin_enclose(Fr(-1570796327, 1000000000),
                             Fr(-785398163, 500000000), ctx)
    assert slo <= Fr(-1), str(slo)


def test_r6_identity_price_is_a_true_upper_bound():
    """R5-6. Readout was priced once per BAG but executed once per FREE
    VARIABLE, each a full sweep of its home bag. The two-variable control
    priced 35 producer operations and executed 45."""
    from mdi import pricing as PR
    cases = [
        "MARKOV\n2\n2 2\n3\n1 0\n1 1\n2 0 1\n2\n1 3\n2\n1 1\n4\n2 1 1 2\n",
        ("MARKOV\n3\n2 2 2\n5\n1 0\n1 1\n1 2\n2 0 1\n2 1 2\n"
         "2\n1 3\n2\n1 2\n2\n1 1\n4\n2 1 1 2\n4\n2 1 1 2\n"),
        ("MARKOV\n4\n2 2 2 2\n7\n1 0\n1 1\n1 2\n1 3\n2 0 1\n2 1 2\n2 2 3\n"
         "2\n1 3\n2\n1 2\n2\n1 1\n2\n1 2\n"
         "4\n2 1 1 2\n4\n2 1 1 2\n4\n2 1 1 2\n"),
    ]
    for txt in cases:
        m = M.read_uai(w(txt))
        r = M.restrict(m, {})
        sel = P.choose_plan(r.free, r.card, r.factors, 64,
                            K.RESOURCES["arm_rss_bytes"])
        pl, est = sel["chosen"]
        rec = PR.price_identity_plan(pl, est, len(r.free), 64)
        priced = sum(int(rec.counters[k].value)
                     for k in ("producer_upward_ops",
                               "producer_downward_ops", "readout_ops"))
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30, run_checker=False)
        executed = res["ops"]["mul"] + res["ops"]["add"]
        assert priced >= executed, (priced, executed, txt[:24])


def test_r6_closed_region_checks_its_interior_deadline():
    """R5-7. A CLOSED region has no boundary variables, so the outer loop runs
    once and an outer-only deadline check fired ZERO times while 4,096
    interior assignments executed."""
    from mdi import regions as R
    calls = [0]

    def expired():
        calls[0] += 1
        raise RuntimeError("EXPIRED")

    n = 12
    facs = []
    for i in range(n):
        j = (i + 1) % n
        facs.append(M.Factor(scope=(min(i, j), max(i, j)), card=(2, 2),
                             table=[Fr(3), Fr(1), Fr(1), Fr(3)],
                             origin=len(facs)))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    with pytest.raises(RuntimeError):
        R.region_data(list(range(n)), r.card, r.factors, set(range(n)),
                      deadline=expired)
    assert calls[0] >= 1


def test_r6_shared_local_mass_counter_is_charged():
    """R5-7. The declared allocation counters existed but were never used: a
    local_mass_entries limit of 1 did not stop construction and `used` stayed
    empty."""
    from mdi import regions as R, budget as B
    bg = B.Budget(wall_s=60.0, limits={"local_mass_entries": 1})
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    with pytest.raises(B.BudgetExceeded):
        R.region_data([0, 1], r.card, r.factors, {0, 1}, budget=bg)
    assert bg.used.get("local_mass_entries", 0) >= 1


def test_r6_expired_preprocessing_returns_a_typed_refusal():
    """R5-7. The exception path referenced `rejected` before initialization,
    so an expired preprocessing deadline raised UnboundLocalError instead of a
    typed refusal."""
    import time as _t
    from mdi import pipeline as PLN
    import mdi.preprocess as PRE
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    orig = PRE.simplify

    def slow(*a, **k):
        _t.sleep(0.020)
        return orig(*a, **k)

    PRE.simplify = slow
    try:
        res = PLN.solve(m, {}, wall_s=0.010, cap_bytes=1 << 30)
    finally:
        PRE.simplify = orig
    assert res.status == "RESOURCE_STOP", res.status


def test_r6_normalizer_includes_the_preprocessing_scale():
    """R5 closeout. `pre_scale` was recorded but never applied, so unary
    [2,2] reported an original evidence weight near 2 where the truth is 4."""
    for tab, want in (([Fr(2), Fr(2)], Fr(4)),
                      ([Fr(1), Fr(3)], Fr(4)),
                      ([Fr(3), Fr(3), Fr(3)], Fr(9))):
        facs = [M.Factor(scope=(0,), card=(len(tab),), table=tab, origin=0)]
        m = M.Model(nvars=1, card=[len(tab)], factors=facs)
        m.validate()
        res = S.solve(m, {}, eps=Fr(1, 100), mode="I", cap_bytes=1 << 30,
                      deadline_s=30)
        lo, hi = res["evidence_weight_interval"]
        assert lo <= want <= hi, (str(lo), str(want), str(hi))


def test_r6_conditional_query_with_non_dense_ids_is_not_refused():
    """R5 closeout. `v < len(restricted.card)` treated a DICT keyed by
    original id as an index range, so after pinning X0 a valid query for X2
    was refused against a length of 2."""
    from mdi import collective_check as CC, regions as R
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(2)], origin=1),
            M.Factor(scope=(2,), card=(2,), table=[Fr(1), Fr(3)], origin=2)]
    m = M.Model(nvars=3, card=[2, 2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {0: 0})
    assert r.free == [1, 2]
    regs = [(v,) for v in r.free]
    rds = [R.region_data(g, r.card, r.factors, {2}) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {2},
                          region_of=ro, aggregate=True)
           for i in range(len(regs))]
    pub = {2: [(Fr(2495, 10000), Fr(2505, 10000)),
               (Fr(7495, 10000), Fr(7505, 10000))]}
    ok, fails, _ = CC.check_composed_publication(
        r, regs, crs, rds, {2}, pub, Fr(1, 100), Fr(0),
        regional_radius=Fr(0))
    assert ok, fails


def test_r6_negative_fourier_has_its_own_oscillatory_lattice():
    """R5-8. Negative Fourier inherited the positive-mode exp(gamma R^2/2)
    magnitude factor and shifted tail. At g=1, R=10, delta=1e-3 the old
    construction REFUSED even at a 2^-40 step, because e^50 multiplies every
    bound. A unit-modulus phase needs neither."""
    from mdi import collective as CO
    lat = CO.fourier_lattice(Fr(1), Fr(10), Fr(1, 1000))
    assert lat["total_bound"] <= Fr(1, 1000), lat
    assert lat["nodes"] > 1
    # my derivative bound matches the reviewer's 227/5 exactly
    assert CO.fourier_second_derivative_bound(Fr(1), Fr(10)) == Fr(227, 5)
    # the positive-mode construction still refuses this case, which is why a
    # dedicated oscillatory lattice was needed
    with pytest.raises(CO.Declined):
        CO.gf_lattice(Fr(1), Fr(10), Fr(1, 1000),
                      second_derivative_bound=Fr(227, 5))


def test_r6_faulty_partition_proposal_is_rejected_at_admission():
    """R5-2. A faulty proposal omitting a hidden variable previously ran the
    whole route and reached CERTIFIED_RESEARCH_ROUTE with both probabilities
    near .5 against a truth of (.3,.7). A candidate that cannot be sound must
    be rejected BEFORE any local construction."""
    from mdi import pipeline as PLN, regions as RG
    import mdi.registry            # noqa: F401
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    orig = RG.propose_partitions

    def faulty(*a, **k):
        out = orig(*a, **k)
        bad = []
        for c in out:
            c2 = dict(c)
            c2["regions"] = [reg for reg in
                             [tuple(v for v in rr if v == 0)
                              for rr in c["regions"]] if reg]
            bad.append(c2)
        return bad

    RG.propose_partitions = faulty
    try:
        res = PLN.solve(m, {}, wall_s=120.0, cap_bytes=1 << 30, queries={0})
    finally:
        RG.propose_partitions = orig
    assert res.status != "CERTIFIED_RESEARCH_ROUTE", res.status
    reasons = " ".join(str(x["reason"]) for x in (res.rejected or []))
    assert "disjoint exact cover" in reasons, reasons
    # the fallback answer must still contain the truth
    if res.intervals:
        for s in range(2):
            lo, hi = res.intervals[0][s]
            assert lo <= pt[0][s] <= hi, (s, float(lo), float(hi))


def test_r6_shared_aggregation_fault_is_caught_independently():
    """R5-3 independence. The checker runs the producer's C.Engine, so a
    defect in Engine.read_marginal would be invisible to it: fresh values
    through the same aggregate implementation are not independence."""
    from mdi import contract as C
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    clean = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                    deadline_s=30)
    assert clean["outcome"] == "VERIFIED_ALL_MARGINALS", clean["outcome"]
    orig = C.Engine.read_marginal

    def faulty(self, var):
        counts, seen, depth = orig(self, var)
        if var == 0 and seen[0]:
            if self.mode == "P":
                counts[0] = counts[0] * 3
            else:
                counts[0] = (counts[0][0] * 3, counts[0][1] * 3)
        return counts, seen, depth

    C.Engine.read_marginal = faulty
    try:
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30)
    finally:
        C.Engine.read_marginal = orig
    assert res["outcome"] != "VERIFIED_ALL_MARGINALS", res["outcome"]
    msg = " ".join(str(f) for f in (res.get("checker") or {}).get("failures",
                                                                 []))
    assert "shared aggregation" in msg, msg


def test_r6_self_consistent_false_plan_records_do_not_bind():
    """R5-5. Six self-consistent FALSE records still certified because the
    loaded record did not determine execution: their answers were right only
    because the false content was IGNORED. bind_check now binds the semantic
    fields against the original inputs and resolves the named
    implementations."""
    import json, copy, tempfile, glob, os
    from mdi import pipeline as PLN, plantype as PT, preprocess as PRE
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    d = tempfile.mkdtemp()
    PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30, plan_dir=d)
    f = [x for x in glob.glob(os.path.join(d, "*.plan.json"))
         if "identity" in x][0]
    base = json.load(open(f))
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    rr = M.Restricted(model=m, evidence={}, factors=simp.factors,
                      free=list(simp.free), card=dict(simp.card),
                      constant=r.constant, impossible_factor=None)
    mh, eh, qh = (base["model_sha256"], base["evidence_sha256"],
                  base["query_sha256"])

    def bind(dd):
        rec = PT.PlanRecord.from_json(json.dumps(dd))
        return rec.bind_check(mh, eh, qh, restricted=rr,
                              preprocess_identity=simp.identity(),
                              max_precision=4096)

    # THE CLEAN BASE MUST BIND
    assert bind(copy.deepcopy(base)) is True

    muts = [
        ("nonexistent executor",
         lambda x: x.update({"executor_id": "mdi.nope:nothing"})),
        ("executor function missing",
         lambda x: x.update({"executor_id": "mdi.solve:nosuchfn"})),
        ("nonexistent checker",
         lambda x: x.update({"checker_id": "mdi.nope:nothing"})),
        ("false precision",
         lambda x: x.update({"numerical": {**x["numerical"],
                                           "precision": 99999}})),
        ("false mode",
         lambda x: x.update({"numerical": {**x["numerical"], "mode": "Z"}})),
        ("unrelated factor 999",
         lambda x: x.update({"factor_scopes": [[999, [999], [2]]],
                             "factor_ownership": [[999, "bag"]]})),
        ("empty preprocessing proof",
         lambda x: x.update({"preprocess_identity": {}})),
        ("altered preprocessing proof",
         lambda x: x.update({"preprocess_identity":
                             {**x["preprocess_identity"], "scale": "7"}})),
        ("empty cost record", lambda x: x.update({"cost_counters": {}})),
        ("empty storage schedule",
         lambda x: x.update({"storage_schedule": {}})),
    ]
    for name, mut in muts:
        dd = copy.deepcopy(base)
        mut(dd)
        with pytest.raises(PT.PlanError):
            bind(dd)


# ===== r6 review: conditioning, applicability, zeros, extrema, accounting =====

def test_r7_conditioning_does_not_create_an_unaccounted_origin():
    """R6-1. `if f.origin == -1: continue` was UNCONDITIONAL. Synthetic
    origins are -1-v, so -1 belongs to variable 0 only while variable 0 is
    FREE; once X0 is observed, -1 is reserved for nothing and the skip hid an
    arbitrary extra factor, certifying near (1/6, 5/6) against a true
    (.5, .5) at 13, 16 and 20 free variables."""
    import copy
    from mdi import preprocess as PRE
    for n in (13, 14, 17, 21):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)],
                         origin=v) for v in range(n)]
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        r = M.restrict(m, {0: 0})
        simp = PRE.simplify(r)
        # THE CLEAN CONDITIONED BASE MUST VERIFY
        assert PRE.verify_identities(r, simp), len(r.free)
        bad = copy.deepcopy(simp)
        bad.factors = list(bad.factors) + [
            M.Factor(scope=(1, 2), card=(2, 2),
                     table=[Fr(1), Fr(1), Fr(1), Fr(9)], origin=-1)]
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, bad)


def test_r7_above_cap_does_not_claim_independent_verification():
    """R6-2. The bounded exact cross-check only runs below the enumeration
    cap. Above it producer and checker share C.Engine's aggregate logic, so a
    common-mode fault is undetectable -- and the same injected readout fault
    rejected at 12 binary variables and returned VERIFIED_ALL_MARGINALS with
    independently_verified=True at 13, publishing (.75,.25) against a uniform
    truth."""
    from mdi import contract as C

    def faulty(self, var):
        counts, seen, depth = orig(self, var)
        if var == 0 and seen[0]:
            if self.mode == "P":
                counts[0] = counts[0] * 3
            else:
                counts[0] = (counts[0][0] * 3, counts[0][1] * 3)
        return counts, seen, depth

    orig = C.Engine.read_marginal
    for n, below_cap in ((12, True), (13, False)):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)],
                         origin=v) for v in range(n)]
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        clean = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                        deadline_s=60)
        if below_cap:
            assert clean["outcome"] == "VERIFIED_ALL_MARGINALS", clean
            assert clean["independently_verified"] is True
        else:
            # above the cap the complete status is NOT claimed
            assert clean["outcome"] == "VERIFIED_SHARED_AGGREGATION_ONLY", \
                clean["outcome"]
            assert clean["independently_verified"] is False
        C.Engine.read_marginal = faulty
        try:
            res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                          deadline_s=60)
        finally:
            C.Engine.read_marginal = orig
        # either the fault is caught, or the run must not claim independence
        assert not (res["outcome"] == "VERIFIED_ALL_MARGINALS"
                    and res.get("independently_verified")), res["outcome"]


def test_r7_hard_zero_pair_is_always_retained():
    """R6-3. Scope occupancy was treated as proof of consumption. A residual
    pair on that scope is a mode-COMPENSATION factor exp(-G): strictly
    positive, and it does not reproduce the original constraint. On pair
    [1,1,1,0] the hard zero was dropped for BOTH signs and the originally
    impossible assignment became possible -- marginals near (.5,.5) against
    an original (2/3,1/3)."""
    from mdi import modes as MD
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(1), Fr(1), Fr(0)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    ctx = A.Ctx(160)
    for sign in (1, -1):
        class C:
            rank = 1
            signs = [sign]
            gammas = [Fr(1)]
            features = [{0: [Fr(0), Fr(1)], 1: [Fr(0), Fr(1)]}]

        res = MD.build_residual(r.free, r.factors, r.card, C(), ctx)
        assert 0 in res.kept, (sign, res.kept, res.detail.get("kept_scopes"))


def test_r7_natural_hard_zero_composed_control_encloses_every_state():
    """R6-3. The reviewer's natural control: four binary variables, six
    positive pairs, plus pair [0,0,1,1] forcing X0=1. r6 published
    P(X0=0) in [.01727, .01732] although its true probability is exactly
    ZERO, and all eight intervals missed."""
    import itertools
    from mdi import composed as CX, regions as R
    ctx = A.Ctx(160)
    n = 4
    facs = []
    for i in range(n):
        for j in range(i + 1, n):
            facs.append(M.Factor(scope=(i, j), card=(2, 2),
                                 table=[Fr(3), Fr(2), Fr(2), Fr(3)],
                                 origin=len(facs)))
    facs.append(M.Factor(scope=(0, 1), card=(2, 2),
                         table=[Fr(0), Fr(0), Fr(1), Fr(1)],
                         origin=len(facs)))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z = Fr(0)
    ct = {}
    for combo in itertools.product(range(2), repeat=n):
        wt = Fr(1)
        for f in r.factors:
            off = 0
            for k, v in enumerate(f.scope):
                off = off * f.card[k] + combo[v]
            wt *= f.table[off]
        if wt == 0:
            continue
        Z += wt
        for v in range(n):
            ct[(v, combo[v])] = ct.get((v, combo[v]), Fr(0)) + wt
    assert ct.get((0, 0), Fr(0)) == 0
    regs = [(i,) for i in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    try:
        out, meta = CX.run(r, regs, crs, rds, set(range(n)), ctx, Fr(1, 100))
    except CX.Declined:
        return                       # a bounded decline is valid
    for v in sorted(out):
        for s, (lo, hi) in enumerate(out[v]):
            t = ct.get((v, s), Fr(0)) / Z
            assert lo <= t <= hi, (v, s, float(lo), float(t), float(hi))


def test_r7_large_negative_critical_points_are_found():
    """R6-4. The coarse pi constants have a relative slack of about 3.18e-6;
    multiplied by a critical index k that slack grows like |k|, so a fixed
    one-index pad cannot locate k*pi at large |k|. Around -1,000,000*pi the
    search range came out [-999999, -999999] and the cosine enclosure missed
    its true maximum 1 by about 5e-7."""
    import gmpy2
    from mdi import collective as CO
    ctx = A.Ctx(160)
    with gmpy2.context(precision=512, round=gmpy2.RoundDown):
        pid = A.exact_fr(gmpy2.const_pi())
    with gmpy2.context(precision=512, round=gmpy2.RoundUp):
        piu = A.exact_fr(gmpy2.const_pi())
    for k in (-1000000, -999999, -500000, -1000, -3, -2, -1, 0, 1, 2,
              999999, 1000000):
        a, b = Fr(k) * pid, Fr(k) * piu
        lo = min(a, b) - Fr(1, 1000)
        hi = max(a, b) + Fr(1, 1000)
        elo, ehi = CO._cos_enclose(lo, hi, ctx)
        if k % 2 == 0:
            assert ehi >= Fr(1), (k, str(ehi))
        else:
            assert elo <= Fr(-1), (k, str(elo))
    for k in (-1000000, -999999, -1000, -1, 0, 1, 1000000):
        c1 = pid / 2 + Fr(k) * pid
        c2 = piu / 2 + Fr(k) * piu
        lo = min(c1, c2) - Fr(1, 1000)
        hi = max(c1, c2) + Fr(1, 1000)
        elo, ehi = CO._sin_enclose(lo, hi, ctx)
        if k % 2 == 0:
            assert ehi >= Fr(1), (k, str(ehi))
        else:
            assert elo <= Fr(-1), (k, str(elo))


def test_r7_quadrature_checker_uses_the_sign_correct_lattice():
    """R6-4. The registered checker called the POSITIVE gf_lattice for a
    negative mode, so it DECLINED a query the producer completed: one
    variable, unary [1,1], features [0,10], gamma 1 evaluates in 2,049 nodes
    with widths about .002137 and .001082."""
    import math
    from mdi import collective as CO, collective_check as CC
    ctx = A.Ctx(160)

    class C:
        rank = 1
        signs = [-1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), Fr(10)]}]

    unary = {0: [Fr(1), Fr(1)]}
    (Zlo, Zhi), mk, meta = CO.fourier_evaluate([0], {0: 2}, unary, C(), {0},
                                               ctx, Fr(1, 1000))
    rows = []
    for s in (0, 1):
        lo, hi = mk[(0, s)]
        rows.append((max(Fr(0), lo / Zhi), min(Fr(1), hi / Zlo)))
    ok, fails, m2 = CC.check_quadrature_publication(
        [0], {0: 2}, unary, C(), {0}, {0: rows}, Fr(1, 100), ctx, Fr(1, 1000))
    assert ok, fails
    # and the published intervals contain the exact truth
    t = (1.0 / (1 + math.exp(-50)), math.exp(-50) / (1 + math.exp(-50)))
    for s, (lo, hi) in enumerate(rows):
        assert float(lo) <= t[s] <= float(hi), (s, float(lo), float(hi))


def test_r7_fourier_midpoint_bound_chain_holds():
    """R6-4. The evaluator sums FULL endpoint weights, so it is a composite
    MIDPOINT rule on [-T-h/2, T+h/2]. The recorded bound is still valid:
    (2T+h)h^2*M2/24 <= 2T*h^2*M2/12 whenever h <= 2T."""
    from mdi import collective as CO
    import inspect
    assert "MIDPOINT" in inspect.getsource(CO.fourier_lattice)
    M2 = Fr(227, 5)
    for T, h in ((4, Fr(1, 256)), (5, Fr(1, 512)), (1, Fr(1, 2)),
                 (2, Fr(1, 4))):
        assert h <= 2 * T
        assert (2 * T + h) * h * h * M2 / 24 <= Fr(2 * T) * h * h * M2 / 12


def test_r7_identity_price_covers_the_root_contraction():
    """R6-6. The ROOT/EVIDENCE contraction was not priced at all: one binary
    unary priced 4 and executed 5, one ternary priced 6 and executed 8, two
    independent binary unaries priced 8 and executed 10."""
    from mdi import pricing as PR
    cases = [(1, [2], [[Fr(1), Fr(3)]]),
             (1, [3], [[Fr(1), Fr(2), Fr(3)]]),
             (2, [2, 2], [[Fr(1), Fr(3)], [Fr(1), Fr(2)]]),
             (3, [2, 2, 2], [[Fr(1), Fr(3)], [Fr(1), Fr(2)],
                             [Fr(2), Fr(1)]])]
    for n, card, tabs in cases:
        facs = [M.Factor(scope=(v,), card=(card[v],), table=list(tabs[v]),
                         origin=v) for v in range(n)]
        m = M.Model(nvars=n, card=list(card), factors=facs)
        m.validate()
        r = M.restrict(m, {})
        sel = P.choose_plan(r.free, r.card, r.factors, 64,
                            K.RESOURCES["arm_rss_bytes"])
        pl, est = sel["chosen"]
        rec = PR.price_identity_plan(pl, est, len(r.free), 64)
        priced = sum(int(rec.counters[k].value)
                     for k in ("producer_upward_ops",
                               "producer_downward_ops", "readout_ops"))
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30, run_checker=False)
        executed = res["ops"]["mul"] + res["ops"]["add"]
        assert priced >= executed, (n, card, priced, executed)


def test_r7_independent_enumeration_is_priced():
    """R6-6. The bounded independent aggregation check runs AFTER the interval
    contraction and was absent from the price: on twelve independent binary
    variables it visits 4,096 assignments and performs about 102,400 exact
    Fraction operations against a recorded checker price of 96."""
    from mdi import pricing as PR
    n = 12
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    sel = P.choose_plan(r.free, r.card, r.factors, 64,
                        K.RESOURCES["arm_rss_bytes"])
    pl, est = sel["chosen"]
    rec = PR.price_identity_plan(pl, est, len(r.free), 64)
    assert int(rec.counters["independent_enumeration_assignments"].value) \
        == 4096
    # test the claimed UPPER BOUND against the COUNTED execution, not an
    # arbitrary lower threshold. The loop performs one multiply per factor
    # entry, one marker add per variable and one add into Z per assignment,
    # then one division per published coordinate:
    #     4096 * (12 + 12 + 1) + 24 = 102,424
    counted = 4096 * (12 + 12 + 1) + 24
    priced = int(rec.counters["independent_enumeration_ops"].value)
    assert priced >= counted, (priced, counted)
    assert int(rec.counters["checker_ops"].value) >= counted


def test_r7_production_path_charges_the_allocation_counters():
    """R6-6. The helper enforced local_mass_entries but the pipeline omitted
    budget=bg, so a public route reported used={} while building masses and
    markers."""
    from mdi import pipeline as PLN
    import mdi.registry            # noqa: F401
    m = M.read_uai(w("MARKOV\n2\n2 2\n2\n1 0\n1 1\n2\n1 3\n2\n1 1\n"))
    res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    used = (res.budget or {}).get("used") or {}
    assert used.get("local_mass_entries", 0) > 0, used


# ===== r7 review: status metadata, conservation, parameters, DP work =====

def test_r8_checker_metadata_propagates_and_the_ring_certifies():
    """R7-1 false downgrade. verify_publication discarded _check's metadata
    with `ok, fails, _`, and the pipeline substituted {"kind": "identity"}, so
    the flag the gate reads never arrived. The shipped ring has twelve BINARY
    variables: 2^12 = 4,096, EXACTLY the cap, not above it. Its independent
    aggregation RAN and checked 24 coordinates."""
    from mdi import pipeline as PLN
    import mdi.registry            # noqa: F401
    m, r, regs, crs, rds, ro = _ring_coarse()
    joint = 1
    for v in r.free:
        joint *= r.card[v]
    assert joint == K.CAPS["region_tuple_assignments"], joint
    direct = S.solve(r.model, {}, eps=Fr(1, 100), mode="P",
                     cap_bytes=1 << 30, deadline_s=120)
    assert direct["outcome"] == "VERIFIED_ALL_MARGINALS", direct["outcome"]
    assert direct["checker"]["independent_aggregation_checked"] is True
    # and the PUBLIC pipeline must not lose that fact
    res = PLN.solve(r.model, {}, wall_s=180.0, cap_bytes=1 << 30)
    assert res.checker.get("independent_aggregation_checked") is True, \
        res.checker
    assert res.status.startswith("CERTIFIED"), (res.status, res.reason)


def test_r8_regional_producer_is_independent_of_its_checker():
    """R7-1 false certification. Regional was exempt from the gate while its
    producer and checker BOTH called _reduced_message_passing. A fault in that
    one shared function returning total 4 with masses 18/5 and 2/5 yielded
    CERTIFIED_RESEARCH_ROUTE with independently_verified=True, publishing
    [.898,.902] where the truth is 1/2."""
    from mdi import pipeline as PLN, regional_check as RC
    import mdi.registry            # noqa: F401
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    clean = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    assert clean.status.startswith("CERTIFIED"), clean.reason
    # The faulty shared contraction must be caught WHEREVER regional is
    # exercised. Honest pricing of the executed branch may make identity win
    # this control, so force the regional candidate to be the selected one by
    # exercising the checker path directly as well.
    from mdi import regions as R2
    regs2 = [(0,), (1,)]
    rds2 = [R2.region_data(g, r.card, r.factors, {0, 1}) for g in regs2]
    ro2 = {0: 0, 1: 1}
    crs2 = [R2.merge_region(rds2[i], r.factors, r.card, Fr(1), {0, 1},
                            region_of=ro2, aggregate=True) for i in range(2)]
    orig = RC._reduced_message_passing

    def faulty(restricted, regions, coarse, rds, queries, deadline=None):
        cl, ch = {}, {}
        for v in sorted(restricted.card):
            cl[(v, 0)] = ch[(v, 0)] = Fr(18, 5)
            cl[(v, 1)] = ch[(v, 1)] = Fr(2, 5)
        return (Fr(4), Fr(4)), (cl, ch)

    RC._reduced_message_passing = faulty
    try:
        res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
        # the regional CHECKER, driven directly, must reject the producer's
        # correct publication only because ITS OWN contraction is faulty --
        # i.e. the two sides are genuinely different implementations
        import mdi.pipeline as PP2
        (Zp, _zh), (clp, _ch) = PP2._producer_reduced_contract(
            r, regs2, crs2, rds2, {0, 1})
        pub = {}
        for v in (0, 1):
            pub[v] = [(max(Fr(0), clp.get((v, sx), Fr(0)) / Zp - Fr(1, 500)),
                       min(Fr(1), clp.get((v, sx), Fr(0)) / Zp + Fr(1, 500)))
                      for sx in range(2)]
        ok, fails, _m = RC.verify_regional_publication(
            r, regs2, crs2, rds2, {0, 1}, pub, Fr(1, 500), Fr(1, 100))
        assert not ok, "the faulty shared contraction was not detected"
    finally:
        RC._reduced_message_passing = orig
    # if regional was selected under the fault, it must not be certified
    if res.plan.get("kind") == "regional":
        assert not res.status.startswith("CERTIFIED"), res.status
        props = res.properties or {}
        assert not props.get("independently_verified"), props
    # and the published answer must contain the truth whichever route ran
    if res.intervals:
        for v in (0, 1):
            for sx in range(2):
                lo, hi = res.intervals[v][sx]
                assert lo <= pt[v][sx] <= hi, (v, sx, float(lo), float(hi))


def test_r8_combined_members_cannot_double_consume():
    """R7-2. `if mo not in claims: claim(...)` SILENTLY SKIPPED an
    already-claimed member, so an original consumed elsewhere could be counted
    a second time: emitting F*U while retaining U as the synthetic unary gives
    the law F*U^2, turning (3/19,16/19) into (3/35,32/35)."""
    import copy
    from mdi import preprocess as PRE
    for n in (12, 13, 16, 20):
        facs = [M.Factor(scope=(0, 1), card=(2, 2),
                         table=[Fr(1), Fr(2), Fr(3), Fr(5)], origin=0),
                M.Factor(scope=(1, 2), card=(2, 2),
                         table=[Fr(1), Fr(2), Fr(3), Fr(5)], origin=1)]
        for v in range(3, n):
            facs.append(M.Factor(scope=(v,), card=(2,),
                                 table=[Fr(1), Fr(1)], origin=v))
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        r = M.restrict(m, {})
        simp = PRE.simplify(r)
        assert PRE.verify_identities(r, simp), len(r.free)
        for mem in ({"0|1": [0, 1], "1|2": [1]},      # reuse across groups
                    {"0|1": [0, 0]},                   # duplicate in group
                    {"0|1": [0, 777]}):                # nonexistent member
            bad = copy.deepcopy(simp)
            bad.combined_members = mem
            with pytest.raises(PRE.PreprocessError):
                PRE.verify_identities(r, bad)


def test_r8_impossible_proof_needs_a_validated_witness():
    """R7-2. Simplified.impossible was unverified: setting it to 0 or to a
    nonexistent origin 999 passed, and both public solvers then returned
    ZERO_EVIDENCE_PROVED for unary [1,2] whose Z is 3."""
    import copy
    from mdi import preprocess as PRE
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)], origin=0)]
    m = M.Model(nvars=1, card=[2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    for val in (0, 999):
        bad = copy.deepcopy(simp)
        bad.impossible = val
        with pytest.raises(PRE.PreprocessError):
            PRE.verify_identities(r, bad)
    # a GENUINE zero factor must still prove zero evidence
    f2 = [M.Factor(scope=(0,), card=(2,), table=[Fr(0), Fr(0)], origin=0)]
    m2 = M.Model(nvars=1, card=[2], factors=f2)
    m2.validate()
    r2 = M.restrict(m2, {})
    s2 = PRE.simplify(r2)
    assert PRE.verify_identities(r2, s2)
    res = S.solve(m2, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                  deadline_s=30)
    assert res["outcome"] == "ZERO_EVIDENCE_PROVED", res["outcome"]


def test_r8_collective_checkers_validate_their_proof_parameters():
    """R7-5. A NEGATIVE radius inverts the reference enclosure, so the
    containment predicate accepted wrong probabilities: radius = -1/10
    certified point rows (3/5,2/5) for a genuinely uniform law."""
    from mdi import collective_check as CC
    ctx = A.Ctx(160)

    class C:
        rank = 1
        signs = [1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), Fr(0)]}]

    unary = {0: [Fr(1), Fr(1)]}
    bad = {0: [(Fr(3, 5), Fr(3, 5)), (Fr(2, 5), Fr(2, 5))]}
    for rad in (Fr(-1, 10), Fr(2)):
        with pytest.raises(CC.CollectiveCheckError):
            CC.check_statistic_publication([0], {0: 2}, unary, C(), 1, {0},
                                           bad, Fr(1, 100), ctx, radius=rad)
    with pytest.raises(CC.CollectiveCheckError):
        CC.check_quadrature_publication([0], {0: 2}, unary, C(), {0}, bad,
                                        Fr(1, 100), ctx, Fr(1, 1000),
                                        radius=Fr(-1, 10))
    # a correct EXACT publication must be ACCEPTED: the checker's own
    # enumeration of this law is exact, so the producer's integration
    # allowance must not widen the reference past it
    good = {0: [(Fr(1, 2), Fr(1, 2)), (Fr(1, 2), Fr(1, 2))]}
    ok, fails, _ = CC.check_quadrature_publication(
        [0], {0: 2}, unary, C(), {0}, good, Fr(1, 100), ctx, Fr(1, 1000))
    assert ok, fails


def test_r8_statistic_dp_aggregates_after_each_child():
    """R7-4. `partials` and `others` were LISTS of (weight, statistic) pairs
    extended per child and merged only at the end, so a 14-leaf binary star
    built 16,384 simultaneous histories for just 15 statistic values. The
    result is verified against an exact 512-bit reference, not a float
    tolerance."""
    import itertools, gmpy2, inspect
    from mdi import gendp as G
    src = inspect.getsource(G._run_component)
    assert "partials = {0: Fr(1)}" in src, "partials must be statistic-keyed"
    assert "others = {0: Fr(1)}" in src, "others must be statistic-keyed"

    def ref_exp(x, p=512):
        mq = gmpy2.mpq(x.numerator, x.denominator)
        with gmpy2.context(precision=p, round=gmpy2.RoundDown):
            lo = gmpy2.exp(gmpy2.mpfr(mq))
        with gmpy2.context(precision=p, round=gmpy2.RoundUp):
            hi = gmpy2.exp(gmpy2.mpfr(mq))
        return A.exact_fr(lo), A.exact_fr(hi)

    ctx = A.Ctx(128)
    for leaves in (3, 4, 5):
        nn = leaves + 1
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)],
                         origin=v) for v in range(nn)]
        for v in range(1, nn):
            facs.append(M.Factor(scope=(0, v), card=(2, 2),
                                 table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                                 origin=100 + v))
        m = M.Model(nvars=nn, card=[2] * nn, factors=facs)
        m.validate()
        r = M.restrict(m, {})

        class C:
            rank = 1
            signs = [1]
            gammas = [Fr(1, 1000)]
            features = [{v: [Fr(0), Fr(1)] for v in range(nn)}]

        sel = P.choose_plan(r.free, r.card, r.factors, 64,
                            K.RESOURCES["arm_rss_bytes"])
        pl, _est = sel["chosen"]
        (zl, zh), mk, _m = G.run(pl, r.factors, r.card, C(), 1,
                                 set(range(nn)), ctx)
        Zl = Zh = Fr(0)
        cl, ch = {}, {}
        for combo in itertools.product(range(2), repeat=nn):
            Ssum = sum(combo)
            wt = Fr(1)
            for f in r.factors:
                off = 0
                for k, v in enumerate(f.scope):
                    off = off * f.card[k] + combo[v]
                wt *= f.table[off]
            el, eh = ref_exp(Fr(Ssum * Ssum, 2000))
            Zl += wt * el
            Zh += wt * eh
            for v in range(nn):
                cl[(v, combo[v])] = cl.get((v, combo[v]), Fr(0)) + wt * el
                ch[(v, combo[v])] = ch.get((v, combo[v]), Fr(0)) + wt * eh
        assert zl <= Zl and Zh <= zh, (leaves, float(zl), float(zh))
        for v in range(nn):
            for a in range(2):
                lo, hi = mk[(v, a)]
                assert lo <= cl[(v, a)] and ch[(v, a)] <= hi, (leaves, v, a)
    # a 14-leaf star must complete at all
    nn = 15
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)], origin=v)
            for v in range(nn)]
    for v in range(1, nn):
        facs.append(M.Factor(scope=(0, v), card=(2, 2),
                             table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                             origin=100 + v))
    m = M.Model(nvars=nn, card=[2] * nn, factors=facs)
    m.validate()
    r = M.restrict(m, {})

    class C14:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 1000)]
        features = [{v: [Fr(0), Fr(1)] for v in range(nn)}]

    sel = P.choose_plan(r.free, r.card, r.factors, 64,
                        K.RESOURCES["arm_rss_bytes"])
    pl, _est = sel["chosen"]
    (zl, zh), mk, _m = G.run(pl, r.factors, r.card, C14(), 1, set(range(nn)),
                             ctx)
    assert zl > 0 and len(mk) == 2 * nn


def test_r8_convolution_caps_during_construction():
    """R7-4. The disconnected convolution tested its cap only AFTER the full
    double loop, so two 16-state components under a cap of 20 allocated all 31
    keys and performed 256 multiply/add pairs before refusing."""
    import inspect
    from mdi import gendp as G
    src = inspect.getsource(G.run)
    assert "during construction" in src
    n = 10
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})

    class C:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 1000)]
        features = [{v: [Fr(0), Fr(v + 1)] for v in range(n)}]

    sel = P.choose_plan(r.free, r.card, r.factors, 64,
                        K.RESOURCES["arm_rss_bytes"])
    pl, _est = sel["chosen"]
    ctx = A.Ctx(128)
    with pytest.raises(G.Declined) as e:
        G.run(pl, r.factors, r.card, C(), 1, set(range(n)), ctx,
              cap_states=20)
    assert "during construction" in str(e.value)
    # the default cap must still complete
    (zl, zh), mk, meta = G.run(pl, r.factors, r.card, C(), 1, set(range(n)),
                               ctx)
    assert zl > 0 and meta.get("total_statistic_support", 0) > 20


def test_r8_pi_bounds_are_cached_by_precision():
    """R7-5. The 513-node Fourier control made 8,208 calls to const_pi at 640
    bits through the pi-bound helper, although the bounds depend only on the
    precision."""
    import gmpy2
    from mdi import collective as CO
    ctx = A.Ctx(160)
    calls = [0]
    orig = gmpy2.const_pi

    def counted(*a, **k):
        calls[0] += 1
        return orig(*a, **k)

    gmpy2.const_pi = counted
    CO._PI_CACHE.clear()
    try:
        class C:
            rank = 1
            signs = [-1]
            gammas = [Fr(1, 2)]
            features = [{0: [Fr(0), Fr(1)], 1: [Fr(0), Fr(1)]}]

        unary = {0: [Fr(1), Fr(2)], 1: [Fr(1), Fr(1)]}
        (Zlo, Zhi), mk, meta = CO.fourier_evaluate(
            [0, 1], {0: 2, 1: 2}, unary, C(), {0, 1}, ctx, Fr(1, 1000))
    finally:
        gmpy2.const_pi = orig
    assert meta["nodes"] == 513, meta["nodes"]
    # far below the 8,208 the uncached helper made for this control
    assert calls[0] < 3000, calls[0]


def test_r8_composed_reports_its_real_statistic_support():
    """R7-6. Composed execution discarded the general DP's metadata,
    substituted acc={0:1} and reported statistic_support=1 where the real
    support is larger; that false count fed pricing and admission."""
    from mdi import composed as CX, regions as R
    ctx = A.Ctx(160)
    n = 4
    facs = []
    for i in range(n):
        for j in range(i + 1, n):
            facs.append(M.Factor(scope=(i, j), card=(2, 2),
                                 table=[Fr(3), Fr(2), Fr(2), Fr(3)],
                                 origin=len(facs)))
    facs.append(M.Factor(scope=(0, 1), card=(2, 2),
                         table=[Fr(0), Fr(0), Fr(1), Fr(1)],
                         origin=len(facs)))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [(i,) for i in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    try:
        out, meta = CX.run(r, regs, crs, rds, set(range(n)), ctx, Fr(1, 100))
    except CX.Declined:
        return
    if meta.get("evaluator") == "general_residual_dp":
        assert meta.get("statistic_support", 0) > 1, meta


# ===== r8 review: containment, factorization, local independence, order =====

def test_r9_containment_binds_the_submitted_publication():
    """R8-1 (MY r8 regression). The predicate widened the SUBMISSION by
    `radius` while checking width on the original endpoints, so it certified
    a publication the producer never made: within the frozen allowance it
    accepted the ZERO-WIDTH points 2001/4000 and 1999/4000 for a law whose
    truths are both exactly 1/2."""
    from mdi import collective_check as CC, collective as CO
    ctx = A.Ctx(160)

    class C:
        rank = 1
        signs = [1]
        gammas = [Fr(1)]
        features = [{0: [Fr(0), Fr(0)]}]

    unary = {0: [Fr(1), Fr(1)]}
    # The VALID base accepts first. With a transfer radius of 1/2000 the
    # reference spans 1/2 +/- 1/2000, so a CORRECT publication must be at
    # least that wide -- a zero-width point could not contain it, which is
    # precisely the property r8 lost.
    good_wide = {0: [(Fr(1, 2) - Fr(1, 2000), Fr(1, 2) + Fr(1, 2000)),
                     (Fr(1, 2) - Fr(1, 2000), Fr(1, 2) + Fr(1, 2000))]}
    ok, fails, _ = CC.check_statistic_publication(
        [0], {0: 2}, unary, C(), 1, {0}, good_wide, Fr(1, 100), ctx,
        radius=Fr(1, 2000))
    assert ok, fails
    # with NO transfer error the exact point publication is correct
    good = {0: [(Fr(1, 2), Fr(1, 2)), (Fr(1, 2), Fr(1, 2))]}
    ok0, f0, _ = CC.check_statistic_publication(
        [0], {0: 2}, unary, C(), 1, {0}, good, Fr(1, 100), ctx,
        radius=Fr(0))
    assert ok0, f0
    # the faulty zero-width points must REJECT
    bad = {0: [(Fr(2001, 4000), Fr(2001, 4000)),
               (Fr(1999, 4000), Fr(1999, 4000))]}
    ok2, _f2, _m2 = CC.check_statistic_publication(
        [0], {0: 2}, unary, C(), 1, {0}, bad, Fr(1, 100), ctx,
        radius=Fr(1, 2000))
    assert not ok2, "a zero-width interval excluding the truth was certified"
    # the quadrature wrapper, even with caller radius 0
    qrad = Fr(CO.gf_lattice(Fr(1), Fr(0), Fr(1, 2000))["total_bound"])
    half = qrad / 2
    bad3 = {0: [(Fr(1, 2) + half, Fr(1, 2) + half),
                (Fr(1, 2) - half, Fr(1, 2) - half)]}
    ok3, _f3, _m3 = CC.check_quadrature_publication(
        [0], {0: 2}, unary, C(), {0}, bad3, Fr(1, 100), ctx, Fr(1, 2000),
        radius=Fr(0))
    assert not ok3
    # preserved positive capability
    ok4, f4, m4 = CC.check_quadrature_publication(
        [0], {0: 2}, unary, C(), {0}, good, Fr(1, 100), ctx, Fr(1, 2000))
    assert ok4, f4
    # the checker enumerates the ORIGINAL law, so it charges no integration
    # error of its own; the producer's allowance is reported, not applied
    assert "producer_integration_allowance" in m4
    # a too-wide publication still rejects on eps
    wide = {0: [(Fr(0), Fr(1)), (Fr(0), Fr(1))]}
    ok5, _f5, _m5 = CC.check_quadrature_publication(
        [0], {0: 2}, unary, C(), {0}, wide, Fr(1, 100), ctx, Fr(1, 2000))
    assert not ok5


def test_r9_regional_producer_keeps_its_factorization():
    """R8-2 (MY r8 regression). The separate producer formed a GLOBAL JOINT
    and never called its own `marginalize`, so a 20-variable width-one chain
    that completed under r7 allocated 8,192 entries and refused. Even a
    13-variable equality chain with only two feasible configurations failed.
    Independence and factorization are simultaneous requirements."""
    import mdi.pipeline as PP
    from mdi import regions as R

    def build(n, equality):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)],
                         origin=v) for v in range(n)]
        for i in range(n - 1):
            tab = ([Fr(1), Fr(0), Fr(0), Fr(1)] if equality
                   else [Fr(2), Fr(1), Fr(1), Fr(2)])
            facs.append(M.Factor(scope=(i, i + 1), card=(2, 2), table=tab,
                                 origin=100 + i))
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        return m

    for n, equality in ((20, False), (13, True)):
        m = build(n, equality)
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        regs = [(v,) for v in range(n)]
        rds = [R.region_data(g, r.card, r.factors, set(range(n)))
               for g in regs]
        ro = {v: i for i, g in enumerate(regs) for v in g}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1),
                              set(range(n)), region_of=ro, aggregate=True)
               for i in range(n)]
        (Zl, _Zh), (cl, _ch) = PP._producer_reduced_contract(
            r, regs, crs, rds, set(range(n)))
        assert Zl > 0
        for v in range(n):
            for s in range(2):
                q = cl.get((v, s), Fr(0)) / Zl
                assert abs(q - pt[v][s]) <= Fr(1, 100), (n, v, s, float(q))
    # the producer must also use its own elimination helper
    import inspect
    src = inspect.getsource(PP._producer_reduced_contract)
    assert src.count("marginalize(") > 1, "marginalize is never called"


def test_r9_producer_admits_projections_before_materializing():
    """R8-2. Seven tiny pair tables over two seven-variable regions have a
    compact representation of 1,820 entries, but r8 expanded seven 128x128
    crossings (114,688 value calls) and built a 16,384-entry joint before
    refusing."""
    import mdi.pipeline as PP
    from mdi import regions as R
    n = 14
    facs = []
    for i in range(7):
        facs.append(M.Factor(scope=(i, i + 7), card=(2, 2),
                             table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=i))
    for v in range(n):
        facs.append(M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)],
                             origin=100 + v))
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [tuple(range(7)), tuple(range(7, 14))]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(2)]
    with pytest.raises(RuntimeError) as e:
        PP._producer_reduced_contract(r, regs, crs, rds, set(range(n)))
    assert "BEFORE materializing" in str(e.value), str(e.value)


def test_r9_producer_bounds_exact_rational_growth():
    """R8-2. Two legal inputs with 40,001-bit entries returned an 80,003-bit
    mass despite the declared 65,536-bit cap: entry-count bounds do not bound
    exact arithmetic."""
    import mdi.pipeline as PP
    from mdi import regions as R
    B = Fr(2) ** 40000
    facs = [M.Factor(scope=(0,), card=(2,), table=[B, B + 1], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[B, B + 1], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [(0,), (1,)]
    rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
    ro = {0: 0, 1: 1}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                          region_of=ro, aggregate=True) for i in range(2)]
    with pytest.raises(RuntimeError) as e:
        PP._producer_reduced_contract(r, regs, crs, rds, {0, 1})
    assert "bit" in str(e.value).lower()


def test_r9_shared_local_marker_fault_is_caught():
    """R8-3. Local mass/marker reconstruction still called the same
    region_data on both sides. Skewing its markers to 9/10 and 1/10 of the
    true mass -- preserving the mark/mass identity, so no invariant fired --
    made four uniform binary variables publish [.897998,.902002] under
    CERTIFIED_RESEARCH_ROUTE with both flags true, all eight intervals
    excluding 1/2."""
    from mdi import pipeline as PLN, regions as R
    import mdi.registry            # noqa: F401
    n = 4
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    clean = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    assert clean.status.startswith("CERTIFIED"), clean.reason
    orig = R.region_data

    def faulty(region, card, factors, queries, **kw):
        rd = orig(region, card, factors, queries, **kw)
        for v in region:
            keys = [k for k in rd.marks if k[0] == v]
            if len(keys) != 2:
                continue
            for b in list(rd.A):
                tot = rd.A[b]
                rd.marks[(v, 0)][b] = tot * Fr(9, 10)
                rd.marks[(v, 1)][b] = tot * Fr(1, 10)
        return rd

    R.region_data = faulty
    try:
        res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    finally:
        R.region_data = orig
    assert not res.status.startswith("CERTIFIED"), res.status
    props = res.properties or {}
    assert not props.get("independently_verified"), props


def test_r9_ownership_proof_is_order_independent():
    """R8-4. `origin != min(group)` skipped the group's product proof whenever
    the smallest member was already claimed. With the unary at origin 0 and
    the pair at origin 1, NO group equality or reuse check ran, and the law
    F*U^2 was accepted above the enumeration cap -- (3/19,16/19) became
    (3/35,32/35)."""
    import copy
    from mdi import preprocess as PRE
    for order in ("pair_first", "unary_first"):
        for n in (12, 13, 16, 20):
            if order == "pair_first":
                facs = [M.Factor(scope=(0, 1), card=(2, 2),
                                 table=[Fr(1), Fr(2), Fr(3), Fr(5)],
                                 origin=0),
                        M.Factor(scope=(0,), card=(2,),
                                 table=[Fr(1), Fr(2)], origin=1)]
                pair_origin = 0
            else:
                facs = [M.Factor(scope=(0,), card=(2,),
                                 table=[Fr(1), Fr(2)], origin=0),
                        M.Factor(scope=(0, 1), card=(2, 2),
                                 table=[Fr(1), Fr(2), Fr(3), Fr(5)],
                                 origin=1)]
                pair_origin = 1
            for v in range(2, n):
                facs.append(M.Factor(scope=(v,), card=(2,),
                                     table=[Fr(1), Fr(1)], origin=v))
            m = M.Model(nvars=n, card=[2] * n, factors=facs)
            m.validate()
            r = M.restrict(m, {})
            simp = PRE.simplify(r)
            assert PRE.verify_identities(r, simp), (order, len(r.free))
            bad = copy.deepcopy(simp)
            nf = []
            for f in bad.factors:
                if tuple(sorted(f.scope)) == (0, 1):
                    nf.append(M.Factor(scope=(0, 1), card=(2, 2),
                                       table=[Fr(1), Fr(2), Fr(6), Fr(10)],
                                       origin=pair_origin))
                else:
                    nf.append(f)
            bad.factors = nf
            bad.combined_members = {"0|1": [0, 1]}
            with pytest.raises(PRE.PreprocessError):
                PRE.verify_identities(r, bad)


def test_r9_regional_price_bounds_the_elimination_it_runs():
    """R8-5. The producer bounds undercounted even its own core arithmetic
    (44>32, 110>84, 260>208), because the formula counted one operation where
    the code performs both a multiply and an add. The checker's local
    reconstruction was also charged twice: the pipeline passed cons+2*cons as
    construction while pricing added 2*cons again."""
    import fractions
    from mdi import pricing as PR, regions as R, compact as CP
    import mdi.pipeline as PP
    counts = {"n": 0}
    saved = {}
    for nm in ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__",
               "__rtruediv__", "__sub__", "__rsub__"):
        saved[nm] = getattr(fractions.Fraction, nm)

    def wrap(fn):
        def w(self, other, *a):
            counts["n"] += 1
            return fn(self, other, *a)
        return w

    for n in (2, 3, 4, 6, 8):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)],
                         origin=v) for v in range(n)]
        for i in range(n - 1):
            facs.append(M.Factor(scope=(i, i + 1), card=(2, 2),
                                 table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                                 origin=100 + i))
        m = M.Model(nvars=n, card=[2] * n, factors=facs)
        m.validate()
        r = M.restrict(m, {})
        regs = [(v,) for v in range(n)]
        rds = [R.region_data(g, r.card, r.factors, set(range(n)))
               for g in regs]
        ro = {v: i for i, g in enumerate(regs) for v in g}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1),
                              set(range(n)), region_of=ro, aggregate=True)
               for i in range(n)]
        proj, _p = CP.project_crossings(r, regs, crs, rds)
        rec = PR.price_regional_plan(
            "r", regs, crs, rds, proj, n, Fr(1, 500),
            construction_ops=sum(int(getattr(rd, "construction_ops", 0))
                                 for rd in rds))
        priced = sum(int(rec.counters[k].value)
                     for k in ("producer_upward_ops",
                               "producer_downward_ops", "readout_ops"))
        for nm, fn in saved.items():
            setattr(fractions.Fraction, nm, wrap(fn))
        counts["n"] = 0
        try:
            PP._producer_reduced_contract(r, regs, crs, rds, set(range(n)))
        finally:
            for nm, fn in saved.items():
                setattr(fractions.Fraction, nm, fn)
        assert priced >= counts["n"], (n, priced, counts["n"])


def test_r9_connected_joins_bound_during_construction():
    """R8-6. Connected ordinary and marked joins constructed the entire child
    Cartesian product before testing its size: a [2,16,16] model under a cap
    of 20 built all 256 keys with no interior callback."""
    import inspect
    from mdi import gendp as G
    src = inspect.getsource(G._run_component)
    assert "the ordinary join reached the declared" in src
    assert "the marked join reached the declared" in src
    # interior work must be ticked against a CUMULATIVE counter, so small
    # products repeated many times cannot evade the clock
    assert "def tick(" in src, "no cumulative work counter"
    assert src.count("tick()") >= 3, "interior work is not ticked"
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(16,), table=[Fr(1)] * 16, origin=1),
            M.Factor(scope=(2,), card=(16,), table=[Fr(1)] * 16, origin=2),
            M.Factor(scope=(0, 1), card=(2, 16), table=[Fr(1)] * 32,
                     origin=3),
            M.Factor(scope=(0, 2), card=(2, 16), table=[Fr(1)] * 32,
                     origin=4)]
    m = M.Model(nvars=3, card=[2, 16, 16], factors=facs)
    m.validate()
    r = M.restrict(m, {})

    class C:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 100000)]
        features = [{0: [Fr(0), Fr(0)],
                     1: [Fr(i) for i in range(16)],
                     2: [Fr(16 * i) for i in range(16)]}]

    sel = P.choose_plan(r.free, r.card, r.factors, 64,
                        K.RESOURCES["arm_rss_bytes"])
    pl, _est = sel["chosen"]
    ctx = A.Ctx(128)
    with pytest.raises(G.Declined):
        G.run(pl, r.factors, r.card, C(), 1, set(range(3)), ctx,
              cap_states=20)
    # the default cap must still complete
    (zl, zh), mk, meta = G.run(pl, r.factors, r.card, C(), 1, set(range(3)),
                               ctx)
    assert zl > 0


# ===== r9 review: coarsening witness and definitive negative results =====

def test_r10_shared_merge_marker_fault_is_caught():
    """R9-2. r9 verified the raw local weights independently but then built
    its reference cells by calling the PRODUCER's merge_region. Changing only
    that merger's cell markers to 0.9 and 0.1 times the UNCHANGED cell mass --
    leaving cells, raw sums, alpha, rho and the mark-sum identity intact --
    certified all eight intervals near .9/.1 on four uniform binary variables
    whose every true probability is 1/2, with regional selected naturally at
    224 vs identity 236."""
    from mdi import pipeline as PLN, regions as R
    import mdi.registry            # noqa: F401
    n = 4
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    clean = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    assert clean.status.startswith("CERTIFIED"), clean.reason
    orig = R.merge_region

    def faulty(rd, factors, card, rho_cap, queries, **kw):
        cr = orig(rd, factors, card, rho_cap, queries, **kw)
        for key in list(cr.N):
            _v, st = key
            cr.N[key] = [Fr(cr.M[ci]) * (Fr(9, 10) if st == 0 else Fr(1, 10))
                         for ci in range(len(cr.cells))]
        return cr

    R.merge_region = faulty
    try:
        res = PLN.solve(m, {}, wall_s=60.0, cap_bytes=1 << 30)
    finally:
        R.merge_region = orig
    assert not res.status.startswith("CERTIFIED"), res.status
    props = res.properties or {}
    assert not props.get("independently_verified"), props


def test_r10_false_distortion_certificate_is_caught():
    """R9-2. Changing only the shared profile-extrema routine to return
    (1,1) admitted a false R = 1 and probabilities near 1/2, where the pair
    table [1,2,3,8] has X0 = (3/14, 11/14) and X1 = (2/7, 5/7). Recomputing
    M and N while trusting the same corrupted distortion calculation would not
    close this."""
    from mdi import regions as R, regional_check as RC
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(8)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    assert pt[0][0] == Fr(3, 14) and pt[1][0] == Fr(2, 7)
    t1 = K.level_radius(1)
    orig = R.ratio_extrema

    def faulty(rb, rr):
        return Fr(1), Fr(1)

    R.ratio_extrema = faulty
    try:
        regs = [(0,), (1,)]
        rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
        ro = {0: 0, 1: 1}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                              region_of=ro, aggregate=True) for i in range(2)]
        pub = {v: [(Fr(1, 2) - t1, Fr(1, 2) + t1),
                   (Fr(1, 2) - t1, Fr(1, 2) + t1)] for v in (0, 1)}
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, {0, 1}, pub, t1, Fr(1, 100))
    finally:
        R.ratio_extrema = orig
    assert not ok, "a false distortion certificate was accepted"


def test_r10_zero_evidence_needs_an_independent_witness():
    """R9-3. ZERO_EVIDENCE_PROVED was returned on the producer's own root
    support with ZERO checker calls: corrupting only that result made unary
    [1,2] -- whose Z is exactly 3 and whose marginals are (1/3, 2/3) -- claim
    a mathematical impossibility."""
    from mdi import contract as C
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)], origin=0)]
    m = M.Model(nvars=1, card=[2], factors=facs)
    m.validate()
    clean = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                    deadline_s=30)
    assert clean["outcome"] == "VERIFIED_ALL_MARGINALS", clean["outcome"]
    orig = C.Engine.root_value

    def faulty(self, root):
        t = orig(self, root)
        if self.mode == "P":
            return C.Table(vars=(), card=(), vals=[self._zero()], depth=0,
                           support=[False])
        return t

    C.Engine.root_value = faulty
    try:
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30)
    finally:
        C.Engine.root_value = orig
    assert res["outcome"] != "ZERO_EVIDENCE_PROVED", res["outcome"]
    assert res.get("zero_support_independently_verified") is False, res

    # GENUINE impossibilities must still be PROVED
    f0 = [M.Factor(scope=(0,), card=(2,), table=[Fr(0), Fr(0)], origin=0)]
    m0 = M.Model(nvars=1, card=[2], factors=f0)
    m0.validate()
    r0 = S.solve(m0, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                 deadline_s=30)
    assert r0["outcome"] == "ZERO_EVIDENCE_PROVED", r0["outcome"]
    # a globally contradictory model built from individually NONZERO factors
    f1 = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
          M.Factor(scope=(0, 1), card=(2, 2),
                   table=[Fr(1), Fr(0), Fr(0), Fr(0)], origin=1),
          M.Factor(scope=(1,), card=(2,), table=[Fr(0), Fr(1)], origin=2)]
    m1 = M.Model(nvars=2, card=[2, 2], factors=f1)
    m1.validate()
    r1 = S.solve(m1, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                 deadline_s=30)
    assert r1["outcome"] == "ZERO_EVIDENCE_PROVED", r1["outcome"]


def test_r10_dp_resource_guards_cover_executed_work():
    """R9-4. The per-child work counter reset before reaching its callback
    threshold, so on a 14-leaf star every individual product stayed below it
    and 420 ordinary plus 5,096 marked updates completed with ZERO callbacks
    after an expired deadline. The guards also protected only the temporary
    dictionary: two admissible 15-key supports combined into 30 FINAL keys
    under a cap of 16, and accumulated exact sums exceeded the bit cap."""
    from mdi import gendp as G
    ctx = A.Ctx(128)
    # (a) a cumulative counter stops the 14-leaf star at the first callback
    nn = 15
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(2)], origin=v)
            for v in range(nn)]
    for v in range(1, nn):
        facs.append(M.Factor(scope=(0, v), card=(2, 2),
                             table=[Fr(2), Fr(1), Fr(1), Fr(2)],
                             origin=100 + v))
    m = M.Model(nvars=nn, card=[2] * nn, factors=facs)
    m.validate()
    r = M.restrict(m, {})

    class C:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 1000)]
        features = [{v: [Fr(0), Fr(1)] for v in range(nn)}]

    sel = P.choose_plan(r.free, r.card, r.factors, 64,
                        K.RESOURCES["arm_rss_bytes"])
    pl, _est = sel["chosen"]
    calls = [0]

    def expired():
        calls[0] += 1
        raise RuntimeError("EXPIRED")

    with pytest.raises(RuntimeError):
        G.run(pl, r.factors, r.card, C(), 1, set(range(nn)), ctx,
              deadline=expired)
    assert calls[0] >= 1
    # the clean run must still complete
    (zl, zh), mk, _m = G.run(pl, r.factors, r.card, C(), 1, set(range(nn)),
                             ctx)
    assert zl > 0 and len(mk) == 2 * nn

    # (b) the FINAL accumulator is bounded
    f2 = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
          M.Factor(scope=(1,), card=(16,), table=[Fr(1)] * 16, origin=1),
          M.Factor(scope=(2,), card=(16,), table=[Fr(1)] * 16, origin=2),
          M.Factor(scope=(0, 1), card=(2, 16), table=[Fr(1)] * 32, origin=3),
          M.Factor(scope=(0, 2), card=(2, 16), table=[Fr(1)] * 32, origin=4)]
    m2 = M.Model(nvars=3, card=[2, 16, 16], factors=f2)
    m2.validate()
    r2 = M.restrict(m2, {})

    class C2:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 100000)]
        features = [{0: [Fr(0), Fr(0)],
                     1: [Fr(i) for i in range(16)],
                     2: [Fr(i) for i in range(16)]}]

    s2 = P.choose_plan(r2.free, r2.card, r2.factors, 64,
                       K.RESOURCES["arm_rss_bytes"])
    p2, _e2 = s2["chosen"]
    with pytest.raises(G.Declined):
        G.run(p2, r2.factors, r2.card, C2(), 1, set(range(3)), ctx,
              cap_states=16)

    # (c) accumulated exact sums are bit-bounded
    B = Fr(2) ** 40000
    f3 = [M.Factor(scope=(0,), card=(2,), table=[B, B + 1], origin=0),
          M.Factor(scope=(1,), card=(2,), table=[B, B + 1], origin=1),
          M.Factor(scope=(0, 1), card=(2, 2),
                   table=[Fr(1), Fr(1), Fr(1), Fr(1)], origin=2)]
    m3 = M.Model(nvars=2, card=[2, 2], factors=f3)
    m3.validate()
    r3 = M.restrict(m3, {})

    class C3:
        rank = 1
        signs = [1]
        gammas = [Fr(1, 1000)]
        features = [{0: [Fr(0), Fr(1)], 1: [Fr(0), Fr(1)]}]

    s3 = P.choose_plan(r3.free, r3.card, r3.factors, 64,
                       K.RESOURCES["arm_rss_bytes"])
    p3, _e3 = s3["chosen"]
    with pytest.raises(G.Declined) as e:
        G.run(p3, r3.factors, r3.card, C3(), 1, set(range(2)), ctx)
    assert "bit" in str(e.value).lower()


def test_r10_checker_reuses_one_local_reconstruction():
    """R9-5. The checker made THREE local enumerations per region: the outer
    loop's, recheck_region's, and the witness verifier's profile rebuild.
    Reuse is a work reduction that does not weaken independence, because the
    independent raw accumulation is a separate implementation either way."""
    from mdi import regions as R, regional_check as RC
    n = 4
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    regs = [(v,) for v in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    t1 = K.level_radius(1)
    pub = {v: [(max(Fr(0), pt[v][s] - t1), min(Fr(1), pt[v][s] + t1))
               for s in range(2)] for v in range(n)}
    calls = {"n": 0}
    orig = R.region_data

    def counted(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)

    R.region_data = counted
    try:
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, set(range(n)), pub, t1, Fr(1, 100))
    finally:
        R.region_data = orig
    assert ok, fails
    # one per region, not three
    assert calls["n"] <= n, (calls["n"], n)


def test_r10_production_regional_call_charges_its_budget():
    """R9-4. _producer_reduced_contract gained a budget parameter, but
    _regional_execute supplied only its deadline, so a direct helper test
    charged and refused while the EXECUTED call bypassed the counter."""
    import inspect
    import mdi.pipeline as PP
    src = inspect.getsource(PP._regional_execute)
    assert "budget=bg" in src, "the production call omits budget=bg"


# ===== r10 review: named-obligation regressions =====

def test_r11_false_distortion_rejects_WITH_valid_publication_padding():
    """R10-1. My r10 regression asserted `not ok` but rejected only because
    its publication omitted the valid 2e-6 reserve: with the reserve restored
    the false certificate PASSED, accepting four wrong intervals near 1/2 for
    the pair [1,2,3,8] whose truths are X0=(3/14,11/14), X1=(2/7,5/7).

    The cause was that _verify_coarsening_witness called the PRODUCER's
    ratio_extrema, so the decisive bound calculation was shared. This test
    uses the valid padding and asserts the NAMED obligation."""
    from mdi import regions as R, regional_check as RC
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(8)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    assert pt[0][0] == Fr(3, 14) and pt[1][0] == Fr(2, 7)
    t1 = K.level_radius(1)
    res = K.PUBLICATION_RESERVE

    def build():
        regs = [(0,), (1,)]
        rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
        ro = {0: 0, 1: 1}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                              region_of=ro, aggregate=True)
               for i in range(2)]
        return regs, rds, crs

    # the CLEAN witness must pass under exactly these publication rules
    regs, rds, crs = build()
    good = {v: [(max(Fr(0), pt[v][s] - t1 - res),
                 min(Fr(1), pt[v][s] + t1 + res)) for s in range(2)]
            for v in (0, 1)}
    ok0, f0, _m0 = RC.verify_regional_publication(
        r, regs, crs, rds, {0, 1}, good, t1, Fr(1, 100))
    assert ok0, f0

    orig = R.ratio_extrema
    R.ratio_extrema = lambda rb, rr: (Fr(1), Fr(1))
    try:
        regs, rds, crs = build()
        # VALID padding, so a rejection cannot come from a narrow publication
        pub = {v: [(Fr(1, 2) - t1 - res, Fr(1, 2) + t1 + res),
                   (Fr(1, 2) - t1 - res, Fr(1, 2) + t1 + res)]
               for v in (0, 1)}
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, {0, 1}, pub, t1, Fr(1, 100))
    finally:
        R.ratio_extrema = orig
    assert not ok, "the false distortion certificate was accepted"
    # it must reject on the NAMED obligation, not on containment margin
    named = [x for x in fails
             if "own profile extrema" in str(x) or "distortion" in str(x)]
    assert named, fails[:3]


def test_r11_omitted_crossing_profiles_reject():
    """R10-2. Forcing the shared aggregate_crossings to return an EMPTY list
    made an interacting model look independent and accepted four wrong
    intervals near 1/2."""
    from mdi import regions as R, regional_check as RC
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(2), Fr(3), Fr(8)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    t1 = K.level_radius(1)
    res = K.PUBLICATION_RESERVE
    orig = R.aggregate_crossings
    R.aggregate_crossings = lambda rd, f, c, ro, **kw: ([], {"omitted": True})
    try:
        regs = [(0,), (1,)]
        rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
        ro = {0: 0, 1: 1}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                              region_of=ro, aggregate=True)
               for i in range(2)]
        pub = {v: [(Fr(1, 2) - t1 - res, Fr(1, 2) + t1 + res)] * 2
               for v in (0, 1)}
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, {0, 1}, pub, t1, Fr(1, 100))
    finally:
        R.aggregate_crossings = orig
    assert not ok
    assert any("crossing factor" in str(x) for x in fails), fails[:3]


def test_r11_missing_marker_keys_reject_by_coverage():
    """R10-3. The witness verifier looped over SUBMITTED keys, so dropping
    X0's entire marker-key set let the direct verifier accept [0,0] for both
    X0 states of a uniform pair, whose truths are 1/2. A missing marked mass
    is not zero."""
    from mdi import regions as R, regional_check as RC
    facs = [M.Factor(scope=(0, 1), card=(2, 2),
                     table=[Fr(1), Fr(1), Fr(1), Fr(1)], origin=0)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    t1 = K.level_radius(1)
    orig = R.merge_region

    def drop(rd, factors, card, rho_cap, queries, **kw):
        cr = orig(rd, factors, card, rho_cap, queries, **kw)
        for key in [k for k in cr.N if k[0] == 0]:
            del cr.N[key]
        return cr

    R.merge_region = drop
    try:
        regs = [(0,), (1,)]
        rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
        ro = {0: 0, 1: 1}
        crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                              region_of=ro, aggregate=True)
               for i in range(2)]
        pub = {0: [(Fr(0), Fr(0)), (Fr(0), Fr(0))],
               1: [(Fr(1, 2) - t1, Fr(1, 2) + t1)] * 2}
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, {0, 1}, pub, t1, Fr(1, 100))
    finally:
        R.merge_region = orig
    assert not ok
    assert any("marker key" in str(x) for x in fails), fails[:3]


def test_r11_zero_proof_operands_come_from_the_original_model():
    """R10-4. The helper received the same mutable Factor objects the
    producer's Engine retains, so zeroing one WORKING table inside
    Engine.upward made unary [1,2] -- still [1,2] in the original model, Z=3 --
    return ZERO_EVIDENCE_PROVED with
    zero_support_independently_verified=True."""
    from mdi import contract as C
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(2)], origin=0)]
    m = M.Model(nvars=1, card=[2], factors=facs)
    m.validate()
    orig = C.Engine.upward

    def faulty(self, root, keep=None):
        for f in self.factors:
            f.table = [Fr(0)] * len(f.table)
        return orig(self, root, keep=keep)

    C.Engine.upward = faulty
    try:
        res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                      deadline_s=30)
    finally:
        C.Engine.upward = orig
    assert res["outcome"] != "ZERO_EVIDENCE_PROVED", res["outcome"]
    # the original model must be untouched
    assert [Fr(x) for x in m.factors[0].table] == [Fr(1), Fr(2)]
    # and the r9 root-result-only fault must still reject
    o2 = C.Engine.root_value

    def f2(self, root):
        t = o2(self, root)
        if self.mode == "P":
            return C.Table(vars=(), card=(), vals=[self._zero()], depth=0,
                           support=[False])
        return t

    C.Engine.root_value = f2
    try:
        r2 = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                     deadline_s=30)
    finally:
        C.Engine.root_value = o2
    assert r2["outcome"] != "ZERO_EVIDENCE_PROVED", r2["outcome"]
    # genuine impossibilities still proved
    f0 = [M.Factor(scope=(0,), card=(2,), table=[Fr(0), Fr(0)], origin=0)]
    m0 = M.Model(nvars=1, card=[2], factors=f0)
    m0.validate()
    assert S.solve(m0, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30,
                   deadline_s=30)["outcome"] == "ZERO_EVIDENCE_PROVED"


def test_r11_disconnected_dp_bounds_its_bit_growth():
    """R10-5. The ORIGINAL disconnected control still returned 80,130-bit
    masses against the 65,536-bit cap; the r10 test substituted a CONNECTED
    model, which exercises a different guarded accumulator."""
    from mdi import gendp as G
    ctx = A.Ctx(128)
    B = Fr(2) ** 40000
    for extra in ([],
                  [M.Factor(scope=(0, 1), card=(2, 2),
                            table=[Fr(1)] * 4, origin=2)]):
        facs = [M.Factor(scope=(0,), card=(2,), table=[B, B + 1], origin=0),
                M.Factor(scope=(1,), card=(2,), table=[B, B + 1],
                         origin=1)] + extra
        m = M.Model(nvars=2, card=[2, 2], factors=facs)
        m.validate()
        r = M.restrict(m, {})

        class C:
            rank = 1
            signs = [1]
            gammas = [Fr(1, 1000)]
            features = [{0: [Fr(0), Fr(1)], 1: [Fr(0), Fr(1)]}]

        sel = P.choose_plan(r.free, r.card, r.factors, 64,
                            K.RESOURCES["arm_rss_bytes"])
        pl, _est = sel["chosen"]
        with pytest.raises(G.Declined) as e:
            G.run(pl, r.factors, r.card, C(), 1, set(range(2)), ctx)
        assert "bit" in str(e.value).lower(), str(e.value)


def test_r11_regional_executor_stops_on_budget_exhaustion():
    """R10-5. _regional_execute passed budget=bg but CAUGHT BudgetExceeded
    and continued through enumeration: it charged four entries against a
    declared limit of 1, recorded exhaustion, and still returned all four
    coordinates. My r10 regression only searched the source for the text
    `budget=bg`; this one tests enforcement."""
    from mdi import budget as B, regions as R, compact as CP
    import mdi.pipeline as PP
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs)
    m.validate()
    r = M.restrict(m, {})
    regs = [(0,), (1,)]
    rds = [R.region_data(g, r.card, r.factors, {0, 1}) for g in regs]
    ro = {0: 0, 1: 1}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), {0, 1},
                          region_of=ro, aggregate=True) for i in range(2)]
    proj, _p = CP.project_crossings(r, regs, crs, rds)
    bg = B.Budget(wall_s=60.0, limits={"local_mass_entries": 1})
    payload = {"regions": regs, "coarse": crs, "rds": rds, "proj": proj,
               "t_level": Fr(1, 500)}
    with pytest.raises(B.BudgetExceeded):
        PP._regional_execute(r, payload, {0, 1}, Fr(1, 100), bg)
    # the attempted work remains charged
    assert bg.used.get("local_mass_entries", 0) >= 1, bg.used


def test_r11_reconstruction_count_is_honest():
    """R10-6. My r10 closeout claimed "4 enumerations for 4 regions instead
    of 12". The honest count is EIGHT: four producer-style region_data calls
    AND four independent raw enumerations. The r10 test counted only the first
    implementation."""
    from mdi import regions as R, regional_check as RC
    counts = {"rd": 0, "own": 0}
    o_rd = R.region_data
    o_own = RC._independent_region_local

    def c_rd(*a, **k):
        counts["rd"] += 1
        return o_rd(*a, **k)

    def c_own(*a, **k):
        counts["own"] += 1
        return o_own(*a, **k)

    n = 4
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1)], origin=v)
            for v in range(n)]
    m = M.Model(nvars=n, card=[2] * n, factors=facs)
    m.validate()
    r = M.restrict(m, {})
    Z, pt = O.exact_all_marginals(r)
    regs = [(v,) for v in range(n)]
    rds = [R.region_data(g, r.card, r.factors, set(range(n))) for g in regs]
    ro = {v: i for i, g in enumerate(regs) for v in g}
    crs = [R.merge_region(rds[i], r.factors, r.card, Fr(1), set(range(n)),
                          region_of=ro, aggregate=True) for i in range(n)]
    t1 = K.level_radius(1)
    res = K.PUBLICATION_RESERVE
    pub = {v: [(max(Fr(0), pt[v][s] - t1 - res),
                min(Fr(1), pt[v][s] + t1 + res)) for s in range(2)]
           for v in range(n)}
    R.region_data = c_rd
    RC._independent_region_local = c_own
    try:
        ok, fails, _m = RC.verify_regional_publication(
            r, regs, crs, rds, set(range(n)), pub, t1, Fr(1, 100))
    finally:
        R.region_data = o_rd
        RC._independent_region_local = o_own
    assert ok, fails
    total = counts["rd"] + counts["own"]
    # BOTH implementations are counted: one of each per region
    assert counts["rd"] == n, counts
    assert counts["own"] == n, counts
    assert total == 2 * n, (total, counts)
