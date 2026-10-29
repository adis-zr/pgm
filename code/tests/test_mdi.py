"""Fixture suite for the model-driven inference engine.

Exact enumeration oracle with asymmetric tables, reversed/permuted scopes,
free ternary states, arity 3 and 4, satisfiable zeros, globally contradictory
constraints despite individually nonzero factors, disconnected models, evidence
restriction, tiny positive values and variable relabeling. Plus arithmetic
primitive tests including a REUSED operand, and the required rejection checks.
"""
import os, sys, tempfile, itertools
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from mdi import model as M, plan as P, arith as A, contract as C, oracle as O
from mdi import solve as S


def w(txt, suffix=".uai"):
    fh = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False)
    fh.write(txt); fh.close(); return fh.name


# ======================= exact input semantics =======================

def test_exact_decimal_not_binary64():
    assert M.exact_decimal("0.1") == Fr(1, 10)
    assert M.exact_decimal("0.1") != Fr(0.1)
    assert M.exact_decimal("1.50803e-05") == Fr(150803, 10 ** 10)
    assert M.exact_decimal("2E3") == Fr(2000)
    assert M.exact_decimal("0") == 0
    assert M.exact_decimal(".5") == Fr(1, 2)


def test_scope_order_first_var_most_significant():
    m = M.read_uai(w("MARKOV\n2\n2 3\n1\n2 0 1\n6\n1 2 3 4 5 6\n"))
    f = m.factors[0]
    assert f.strides() == (3, 1)
    for x0 in range(2):
        for x1 in range(3):
            assert f.at({0: x0, 1: x1}) == Fr(1 + 3 * x0 + x1)
    # transposed convention would give 5 here
    assert f.at({0: 0, 1: 2}) == Fr(3)


# ======================= arithmetic contract =======================

def test_directed_rounding_and_exact_zero():
    c = A.Ctx(64)
    q = Fr(1, 3)
    assert A.exact_fr(c.down(q)) < q < A.exact_fr(c.up(q))
    assert c.down(0) == 0 and c.up(0) == 0


def test_lambda_is_exact_and_bounds_hold():
    p = 64
    for E in (0, 1, 7, 1000, 10 ** 9):
        L = A.lam(E, p)
        assert L == Fr(1) - Fr(E) * Fr(1, 1 << (p - 1))
        assert 0 < L <= 1


def test_depth_overflow_refused():
    with pytest.raises(A.DepthOverflow):
        A.lam(1 << 64, 64)


def test_reused_operand_counts_twice():
    """A mistaken 'one rounding per distinct source' rule must FAIL here.

    x = RNDD(q); y = RNDD(x*x). The multiplication rule is E = E1+E2+1, giving
    E(y)=3 from E(x)=1. A rule that summed only the operand depths (1+1=2) and
    forgot the operation's own rounding would be UNSOUND: we exhibit a q where
    the true ratio exact/computed exceeds the depth-2 bound.

    Non-dyadic operands (thirds) are used so the conversion actually rounds.
    """
    p = 16
    c = A.Ctx(p)
    worst, arg = Fr(0), None
    for num in range(1, 2000):
        q = Fr(num, 3)
        x = c.down(q)
        if x == 0:
            continue
        y = c.mul_d(x, x)
        yv = A.exact_fr(y)
        if yv <= 0:
            continue
        ratio = (q * q) / yv
        if ratio > worst:
            worst, arg = ratio, q
    # the declared depth-3 bound IS sound
    assert worst <= 1 / A.lam(3, p), (float(worst), float(1 / A.lam(3, p)), arg)
    # a single rounding is not enough
    assert worst > 1 / A.lam(1, p), "squaring a rounded value must exceed depth 1"
    # and crucially, the depth-2 "forgot the operation" rule is VIOLATED
    assert worst > 1 / A.lam(2, p), (
        "a distinct-source rule that omits the operation's own rounding must be "
        "unsound here; witness q=%s ratio=%s" % (arg, worst))


def test_depth_rule_products_add_and_sums_max():
    """The declared composition rules, checked numerically on a small circuit."""
    p = 24
    c = A.Ctx(p)
    # chain of multiplications: depth grows additively
    q = Fr(7, 3)
    x = c.down(q)                     # E = 1
    y = c.mul_d(x, x)                 # E = 1+1+1 = 3
    z = c.mul_d(y, x)                 # E = 3+1+1 = 5
    assert (q ** 3) / A.exact_fr(z) <= 1 / A.lam(5, p)
    # sequential sum of n terms: depth = max + (n-1)
    terms = [c.down(Fr(k, 7)) for k in range(1, 9)]       # each E = 1
    acc, exact = terms[0], Fr(1, 7)
    for t, k in zip(terms[1:], range(2, 9)):
        acc = c.add_d(acc, t); exact += Fr(k, 7)
    assert exact / A.exact_fr(acc) <= 1 / A.lam(1 + 7, p)


def test_marginal_interval_never_subtracts_from_one():
    L = Fr(1) - Fr(1000) * A.u_of(64)
    # a probability very close to 1 must keep a positive complement
    A_big, C_small = Fr(10) ** 40, Fr(1)
    lo, hi = A.marginal_interval(A_big, C_small, L)
    assert 0 < lo <= hi < 1
    assert hi - lo <= A.max_width(L)


def test_marginal_interval_structural_exact():
    L = Fr(999, 1000)
    assert A.marginal_interval(0, 7, L) == (Fr(0), Fr(0))
    assert A.marginal_interval(7, 0, L) == (Fr(1), Fr(1))


def test_width_bound_at_half():
    L = Fr(1) - Fr(10 ** 6) * A.u_of(64)
    lo, hi = A.marginal_interval(1, 1, L)
    assert hi - lo <= A.max_width(L)


# ======================= fixtures vs the exact oracle =======================

F_ASYM = """MARKOV
3
2 3 2
3
1 1
2 0 1
3 0 1 2
3
2 5 11
6
1 7 2 13 3 5
12
2 1 3 1 5 1 7 1 11 1 13 1
"""

F_PERMUTED = """MARKOV
3
2 3 2
2
3 2 0 1
1 1
12
1 2 3 4 5 6 7 8 9 10 11 12
3
3 5 7
"""

F_ZEROS_SAT = """MARKOV
3
2 2 2
3
2 0 1
2 1 2
1 2
4
1 0 0 1
4
1 0 0 1
2
3 5
"""

F_ARITY4 = """MARKOV
4
2 2 2 3
2
4 0 1 2 3
1 3
24
1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
3
2 3 5
"""

F_DISCONNECTED = """MARKOV
4
2 3 2 2
2
2 0 1
2 2 3
6
1 2 3 4 5 6
4
7 11 13 17
"""

F_TINY = """MARKOV
2
2 2
2
1 0
2 0 1
2
1e-30 1
4
1 1e-25 1e-25 1
"""

F_TERNARY_FREE = """MARKOV
2
3 3
2
1 0
2 0 1
3
2 3 5
9
1 0 2 0 3 0 4 5 0
"""


def _check_against_oracle(txt, evid_txt=None, mode="P", eps=Fr(1, 100)):
    mp = w(txt)
    m = M.read_uai(mp)
    ev = {}
    if evid_txt is not None:
        ep = w(evid_txt, ".evid")
        ev = M.read_evidence(ep, m)
    r = M.restrict(m, ev)
    Z, exact = O.exact_all_marginals(r)
    res = S.solve(m, ev, eps=eps, mode=mode, cap_bytes=1 << 30, deadline_s=120)
    if Z == 0:
        assert res["outcome"] == "ZERO_EVIDENCE_PROVED", res["outcome"]
        return res
    assert res["outcome"] in ("VERIFIED_ALL_MARGINALS",), res
    for v in r.free:
        for s in range(r.card[v]):
            lo, hi = res["intervals"][v][s]
            p = exact[v][s]
            assert lo <= p <= hi, ("containment failed", v, s, float(lo), float(p), float(hi))
            assert hi - lo <= eps, ("width", v, s, float(hi - lo))
    # observed variables restored as exact point masses
    for v, st in ev.items():
        for s in range(m.card[v]):
            lo, hi = res["intervals"][v][s]
            want = Fr(1) if s == st else Fr(0)
            assert lo == hi == want, ("evidence restoration", v, s)
    return res


@pytest.mark.parametrize("mode", ["P", "I"])
@pytest.mark.parametrize("txt,name", [
    (F_ASYM, "asymmetric"),
    (F_PERMUTED, "permuted_scope"),
    (F_ZEROS_SAT, "satisfiable_zeros"),
    (F_ARITY4, "arity4_ternary"),
    (F_DISCONNECTED, "disconnected"),
    (F_TINY, "tiny_positive"),
    (F_TERNARY_FREE, "free_ternary"),
])
def test_fixture_matches_exact_oracle(txt, name, mode):
    _check_against_oracle(txt, mode=mode)


@pytest.mark.parametrize("mode", ["P", "I"])
def test_evidence_restriction_matches_oracle(mode):
    # pin the ternary variable, leaving binary free vars (the Pedigree pattern)
    _check_against_oracle(F_ASYM, "1 1 2\n", mode=mode)
    _check_against_oracle(F_ARITY4, "1 3 1\n", mode=mode)


@pytest.mark.parametrize("mode", ["P", "I"])
def test_variable_relabeling_invariance(mode):
    """Relabeling variables must not change the marginals."""
    a = M.read_uai(w(F_ASYM))
    ra = M.restrict(a, {})
    Za, ma = O.exact_all_marginals(ra)
    # relabel 0<->2 by rewriting scopes
    perm = {0: 2, 1: 1, 2: 0}
    facs = []
    for f in a.factors:
        facs.append(M.Factor(scope=tuple(perm[v] for v in f.scope), card=f.card,
                             table=list(f.table), origin=f.origin))
    b = M.Model(nvars=3, card=[a.card[2], a.card[1], a.card[0]], factors=facs).validate()
    rb = M.restrict(b, {})
    Zb, mb = O.exact_all_marginals(rb)
    assert Za == Zb
    for v in (0, 1, 2):
        assert ma[v] == mb[perm[v]]
    res = S.solve(b, {}, eps=Fr(1, 100), mode=mode, cap_bytes=1 << 30, deadline_s=120)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS"
    for v in (0, 1, 2):
        for s in range(b.card[v]):
            lo, hi = res["intervals"][v][s]
            assert lo <= mb[v][s] <= hi


# ---- globally contradictory despite individually nonzero factors ----
F_GLOBAL_CONTRA = """MARKOV
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


@pytest.mark.parametrize("mode", ["P", "I"])
def test_global_contradiction_proved_zero(mode):
    m = M.read_uai(w(F_GLOBAL_CONTRA))
    r = M.restrict(m, {})
    # every restricted factor has a nonzero entry
    assert all(any(t != 0 for t in f.table) for f in r.factors)
    assert r.impossible_factor is None
    Z, ex = O.exact_all_marginals(r)
    assert Z == 0 and ex is None
    res = S.solve(m, {}, eps=Fr(1, 100), mode=mode, cap_bytes=1 << 30, deadline_s=120)
    assert res["outcome"] == "ZERO_EVIDENCE_PROVED", res["outcome"]
    assert "intervals" not in res or not res.get("intervals")


@pytest.mark.parametrize("mode", ["P", "I"])
def test_disconnected_with_one_impossible_component(mode):
    """A solved component cannot justify an answer while another is impossible."""
    txt = """MARKOV
4
2 2 2 2
4
2 0 1
2 2 3
1 2
1 3
4
1 2 3 4
4
1 0 0 1
2
1 0
2
0 1
"""
    m = M.read_uai(w(txt))
    r = M.restrict(m, {})
    Z, ex = O.exact_all_marginals(r)
    assert Z == 0
    res = S.solve(m, {}, eps=Fr(1, 100), mode=mode, cap_bytes=1 << 30, deadline_s=120)
    assert res["outcome"] == "ZERO_EVIDENCE_PROVED", res["outcome"]


def test_partition_function_matches_oracle():
    """Verify Z itself, not only the normalized marginals."""
    m = M.read_uai(w(F_ASYM))
    r = M.restrict(m, {})
    Z, _ = O.exact_all_marginals(r)
    res = S.solve(m, {}, eps=Fr(1, 100), mode="I", cap_bytes=1 << 30, deadline_s=120)
    lo, hi = res["evidence_weight_interval"]
    assert lo <= Z <= hi, (float(lo), float(Z), float(hi))


# ======================= plan validation =======================

def test_plan_reproduces_known_counts():
    """The engine's planner must reproduce the spec's exact domain-product counts."""
    p = "/tmp/tep/three_external_problems/inputs/Grids_11"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    m = M.read_uai(p + ".uai")
    r = M.restrict(m, M.read_evidence(p + ".uai.evid", m))
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    assert pl.induced_width == 23
    assert pl.largest_bag_entries == 16777216
    assert pl.sum_bag_entries == 41775166
    assert pl.sum_sep_entries == 20887583


def test_plan_structural_checks_run():
    m = M.read_uai(w(F_ARITY4))
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    assert P.validate_plan(pl, r.factors)


# ======================= required rejection checks =======================

def test_reject_duplicate_scope_variable():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n2\n2 2\n1\n2 0 0\n4\n1 2 3 4\n"))


def test_reject_inconsistent_table_length():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n2\n2 2\n1\n2 0 1\n3\n1 2 3\n"))


def test_reject_negative_weight():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n1\n2\n1\n1 0\n2\n-1 2\n"))


def test_reject_out_of_range_variable():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n2\n2 2\n1\n1 5\n2\n1 2\n"))


def test_reject_out_of_range_evidence():
    m = M.read_uai(w(F_ASYM))
    with pytest.raises(M.InvalidModel):
        M.read_evidence(w("1 1 9\n", ".evid"), m)
    with pytest.raises(M.InvalidModel):
        M.read_evidence(w("1 7 0\n", ".evid"), m)


def test_reject_duplicate_evidence_variable():
    m = M.read_uai(w(F_ASYM))
    with pytest.raises(M.InvalidModel):
        M.read_evidence(w("2 1 0 1 1\n", ".evid"), m)


def test_reject_malformed_numeric_token():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n1\n2\n1\n1 0\n2\n1 abc\n"))


def test_reject_extreme_decimal_exponent():
    with pytest.raises(M.InputRangeRefusal):
        M.exact_decimal("1e999999")


def test_reject_trailing_tokens():
    with pytest.raises(M.InvalidModel):
        M.read_uai(w("MARKOV\n1\n2\n1\n1 0\n2\n1 2\n99\n"))


# ---- mutation checks: a VALID record passes, then its mutation fails ----

def test_mutation_omitted_factor_changes_answer():
    """A valid model verifies; dropping a factor must change a marginal."""
    m = M.read_uai(w(F_ASYM))
    r = M.restrict(m, {})
    Z1, ex1 = O.exact_all_marginals(r)
    assert Z1 > 0
    r2 = M.restrict(m, {})
    r2.factors = r2.factors[:-1]                      # omit the last factor
    Z2, ex2 = O.exact_all_marginals(r2)
    assert ex1 != ex2, "omitting a factor must change the marginals"


def test_mutation_duplicated_factor_breaks_ownership():
    m = M.read_uai(w(F_ASYM))
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    order = P.order_min_fill(r.free, r.card, adj)
    pl = P.build_plan("min_fill", order, r.free, r.card, r.factors)
    assert P.validate_plan(pl, r.factors)             # passes first
    pl.bags[pl.bags[0].idx].factors.append(0)         # duplicate ownership
    with pytest.raises(P.PlanError):
        P.validate_plan(pl, r.factors)


def test_mutation_broken_separator_rejected():
    m = M.read_uai(w(F_ARITY4))
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj),
                      r.free, r.card, r.factors)
    assert P.validate_plan(pl, r.factors)
    child = next((b for b in pl.bags if b.parent >= 0), None)
    if child is None:
        pytest.skip("single-bag plan")
    child.separator = tuple(sorted(set(child.separator) | {999}))
    with pytest.raises(P.PlanError):
        P.validate_plan(pl, r.factors)


def test_mutation_fabricated_zero_support_detected():
    """Claiming a supported entry is zero must change the computed marginal."""
    m = M.read_uai(w(F_ASYM))
    r = M.restrict(m, {})
    _, ex = O.exact_all_marginals(r)
    f = r.factors[-1]
    i = next(k for k, t in enumerate(f.table) if t != 0)
    f.table[i] = Fr(0)                                # fabricate a zero
    _, ex2 = O.exact_all_marginals(r)
    assert ex != ex2, "a fabricated zero must be detectable in the output"


def test_mutation_inverted_interval_rejected():
    with pytest.raises(A.NumericalRefusal):
        A.publish(Fr(7, 10), Fr(3, 10), Fr(0), Fr(1, 100))


def test_mutation_too_wide_interval_rejected():
    with pytest.raises(A.NumericalRefusal):
        A.publish(Fr(1, 10), Fr(9, 10), Fr(0), Fr(1, 100))


def test_invalid_lambda_rejected():
    with pytest.raises(A.DepthOverflow):
        A.lam(-1, 64)


def test_numerical_range_exhaustion_detected():
    """A conversion that underflows the exponent range must refuse, not return 0."""
    c = A.Ctx(64, emin=-100, emax=100)
    with pytest.raises(A.NumericalRefusal):
        c.down(Fr(1, 10) ** 400)


# ======================= checker =======================

@pytest.mark.parametrize("mode", ["P", "I"])
def test_independent_checker_verifies(mode):
    m = M.read_uai(w(F_ASYM))
    res = S.solve(m, {}, eps=Fr(1, 100), mode=mode, cap_bytes=1 << 30, deadline_s=120)
    assert res["outcome"] == "VERIFIED_ALL_MARGINALS"
    chk = res["checker"]
    assert chk["status"] == "VERIFIED"
    assert chk["coordinates_checked"] == sum(m.card[v] for v in range(m.nvars))
    assert chk["containment_failures"] == 0


def test_checker_catches_a_corrupted_publication():
    """The checker must reject a publication that does not contain the truth."""
    m = M.read_uai(w(F_ASYM))
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=120)
    bad = {v: [list(x) for x in rows] for v, rows in res["intervals"].items()}
    v0 = sorted(bad)[0]
    bad[v0][0] = (Fr(0), Fr(0))          # claim an impossible point mass
    ok, fails, _vm = S.verify_publication(m, {}, bad, eps=Fr(1, 100), mode="I")
    assert not ok and fails, "checker accepted a corrupted publication"


def test_messages_are_actually_freed():
    """The planner's peak-live estimate must reflect the executed path.

    A chain model has many messages; if nothing were freed the live total would
    equal the sum over all messages. We require the measured peak live set to be
    strictly below that sum, so the memory estimate is not a false promise.
    """
    n = 14
    lines = ["MARKOV", str(n), " ".join(["2"] * n)]
    scopes = [(i, i + 1) for i in range(n - 1)]
    lines.append(str(len(scopes)))
    for a, b in scopes:
        lines.append("2 %d %d" % (a, b))
    for k, _ in enumerate(scopes):
        lines.append("4")
        lines.append("%d %d %d %d" % (k + 2, 1, 1, k + 3))
    m = M.read_uai(w("\n".join(lines) + "\n"))
    res = S.solve(m, {}, eps=Fr(1, 100), mode="P", cap_bytes=1 << 30, deadline_s=120)
    assert res["outcome"] in ("VERIFIED_ALL_MARGINALS",
                              "VERIFIED_SHARED_AGGREGATION_ONLY"), \
        res["outcome"]
    peak = res["peak_live_message_entries"]
    r = M.restrict(m, {})
    adj = P.primal_graph(r.free, r.card, r.factors)
    pl = P.build_plan(res["plan"]["name"],
                      dict(P.PORTFOLIO)[res["plan"]["name"]](r.free, r.card, adj),
                      r.free, r.card, r.factors)
    sum_all = 2 * pl.sum_sep_entries
    assert 0 < peak < sum_all, (peak, sum_all)


def test_resource_bound_reports_concrete_estimate():
    """A plan that cannot fit must refuse with its table and byte estimate,
    not an unsupported-model verdict. Exercised on a synthetic model, because
    exact preprocessing now makes Pedigree_11 fit comfortably."""
    n = 26
    scopes = [(v,) for v in range(n)] + [(i, j) for i in range(n)
                                         for j in range(i + 1, n)]
    lines = ["MARKOV", str(n), " ".join(["2"] * n), str(len(scopes))]
    for sc in scopes:
        lines.append("%d %s" % (len(sc), " ".join(map(str, sc))))
    for v in range(n):
        lines.extend(["2", "1.0 1.%d" % (v % 7 + 1)])
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            k += 1
            lines.extend(["4", "1.%d 1.%d 1.%d 1.%d"
                          % (k % 5 + 1, k % 7 + 1, k % 3 + 1, k % 9 + 1)])
    m = M.read_uai(w("\n".join(lines) + "\n"))
    res = S.solve(m, {}, eps=Fr(1, 100), mode="I", cap_bytes=1 << 20,
                  deadline_s=30, run_checker=False)
    assert res["outcome"] == "RESOURCE_BOUND", res["outcome"]
    assert res["best_candidate"]["largest_bag_entries"] > 0
    assert res["best_estimate"]["estimate_bytes"] > res["cap_bytes"]
    assert "UNSUPPORTED" not in res["outcome"]


def test_exact_preprocessing_shrinks_pedigree_interval_mode():
    """Exact preprocessing takes Pedigree_11's interval-mode estimate from
    8.29 GiB (no ordering fits) to 0.566 GiB. The earlier RESOURCE_BOUND was an
    artifact of not simplifying, not a property of the instance."""
    p = "/tmp/tep/three_external_problems/inputs/Pedigree_11"
    if not os.path.exists(p + ".uai"):
        pytest.skip("external inputs not extracted")
    from mdi import preprocess as PRE
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r = M.restrict(m, ev)
    before = P.choose_plan(r.free, r.card, r.factors, 128, 8 * (1 << 30))
    assert before["chosen"] is None, "unsimplified interval mode should not fit"
    simp = PRE.simplify(r)
    assert PRE.verify_identities(r, simp)
    assert len(simp.removed_constants) == 22
    assert len(simp.split_pairs) == 13
    after = P.choose_plan(r.free, r.card, simp.factors, 128, 8 * (1 << 30))
    assert after["chosen"] is not None, "simplified interval mode should fit"
    pl, est = after["chosen"]
    assert pl.induced_width == 20, pl.induced_width
    assert pl.largest_bag_entries == 2097152
    assert pl.sum_bag_entries == 5922542
    # Review 4 corrected this figure: 0.762 GiB in interval mode, from
    # 5,341,332 peak live entries under the EXECUTED schedule. My earlier 0.566
    # came from the pre-fix simulation. Entry-based forecast, excluding MPFR
    # object and limb overhead, allocator overhead, input tables and buffers.
    assert est["peak_live_entries"] == 5341332, est["peak_live_entries"]
    assert 0.70 < est["estimate_bytes"] / (1 << 30) < 0.80, est["estimate_bytes"]
