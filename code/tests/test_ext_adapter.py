"""Adapter fixtures for the external comparison: factor-table ordering, evidence,
nonbinary states, and zeros. Exact Fraction arithmetic -- no numerical tolerance
is needed for the conversion identities, so none is granted."""
import os, sys, itertools, tempfile
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import uai


def _w(txt):
    fh = tempfile.NamedTemporaryFile("w", suffix=".uai", delete=False)
    fh.write(txt); fh.close(); return fh.name


# ---- Fixture A: ordering. 2x3 factor, distinct entries, last var fastest. ----
A_MODEL = """MARKOV
2
2 3
1
2 0 1
6
1 2 3 4 5 6
"""

def test_table_order_last_var_fastest():
    m = uai.read_model(_w(A_MODEL))
    f = m.factors[0]
    assert f.scope == (0, 1) and f.card == (2, 3)
    assert f.strides() == (3, 1), "UAI order: last variable in scope varies fastest"
    # entry for (x0,x1) must be 1 + 3*x0 + x1
    for x0 in range(2):
        for x1 in range(3):
            assert f.at({0: x0, 1: x1}) == Fr(1 + 3 * x0 + x1), (x0, x1)


def test_table_order_is_not_first_var_fastest():
    """Guard against the transposed convention silently passing."""
    m = uai.read_model(_w(A_MODEL))
    f = m.factors[0]
    assert f.at({0: 0, 1: 2}) == Fr(3)   # column-major would give 5
    assert f.at({0: 1, 1: 0}) == Fr(4)   # column-major would give 2


# ---- Fixture B: nonbinary states + zeros, 3 vars with cards 2,3,2 ----
B_MODEL = """MARKOV
3
2 3 2
2
2 0 1
2 1 2
6
0.5 0 0.25 0.125 0 1
6
0 1 0.5 0.25 0 2
"""

def test_nonbinary_and_zeros_read_exactly():
    m = uai.read_model(_w(B_MODEL))
    f0, f1 = m.factors
    assert f0.card == (2, 3) and f1.card == (3, 2)
    assert f0.table == [Fr(1,2), Fr(0), Fr(1,4), Fr(1,8), Fr(0), Fr(1)]
    assert f1.table == [Fr(0), Fr(1), Fr(1,2), Fr(1,4), Fr(0), Fr(2)]
    assert f0.table.count(Fr(0)) == 2 and f1.table.count(Fr(0)) == 2, "zeros preserved, not softened"


def _joint_weight(card, factors, assign):
    w = Fr(1)
    for f in factors:
        w *= f.at(assign)
    return w


def _enumerate(card, factors, free_vars, fixed):
    out = {}
    for combo in itertools.product(*[range(card[v]) for v in free_vars]):
        a = dict(fixed); a.update(dict(zip(free_vars, combo)))
        out[combo] = _joint_weight(card, factors, a)
    return out


def test_evidence_restriction_preserves_every_weight_exactly():
    """Original vs converted weights must agree EXACTLY on the fixture."""
    m = uai.read_model(_w(B_MODEL))
    for ev in ({1: 0}, {1: 1}, {1: 2}, {0: 1}, {0: 0, 2: 1}, {1: 2, 2: 0}):
        rf = uai.restrict_evidence(m, ev)
        free = [v for v in range(m.nvars) if v not in ev]
        orig = _enumerate(m.card, m.factors, free, ev)
        conv = _enumerate(m.card, rf, free, {})
        assert set(orig) == set(conv)
        for k in orig:
            assert orig[k] == conv[k], ("weight changed by restriction", ev, k, orig[k], conv[k])


def test_evidence_restriction_preserves_normalized_marginals_exactly():
    m = uai.read_model(_w(B_MODEL))
    ev = {1: 2}
    rf = uai.restrict_evidence(m, ev)
    free = [v for v in range(m.nvars) if v not in ev]
    for src in (("orig", m.factors, ev), ("conv", rf, {})):
        name, facs, fixed = src
        tot = Fr(0); per = {v: [Fr(0)] * m.card[v] for v in free}
        for combo in itertools.product(*[range(m.card[v]) for v in free]):
            a = dict(fixed); a.update(dict(zip(free, combo)))
            w = _joint_weight(m.card, facs, a)
            tot += w
            for v, s in zip(free, combo):
                per[v][s] += w
        if name == "orig":
            o_tot, o_per = tot, per
        else:
            assert tot == o_tot, "partition function changed"
            for v in free:
                assert [x / tot for x in per[v]] == [x / o_tot for x in o_per[v]], v


# ---- Fixture C: a zero that makes a whole state impossible ----
C_MODEL = """MARKOV
2
3 2
2
1 0
2 0 1
3
1 1 0
6
1 1 1 1 1 1
"""

def test_hard_zero_yields_exact_zero_marginal():
    m = uai.read_model(_w(C_MODEL))
    tot = Fr(0); mar = [Fr(0)] * 3
    for x0 in range(3):
        for x1 in range(2):
            w = _joint_weight(m.card, m.factors, {0: x0, 1: x1})
            tot += w; mar[x0] += w
    probs = [x / tot for x in mar]
    assert probs == [Fr(1,2), Fr(1,2), Fr(0)], probs
    assert probs[2] == 0, "a hard zero must stay exactly zero through the adapter"


# ---- Fixture D: MAR round trip including observed point masses ----
def test_mar_round_trip_with_observed_point_masses():
    rows = [[0.25, 0.75], [1.0, 0.0, 0.0], [0.5, 0.5]]
    p = tempfile.NamedTemporaryFile("w", suffix=".MAR", delete=False).name
    uai.write_mar(p, rows)
    back, raw = uai.read_mar(p)
    assert [len(r) for r in back] == [2, 3, 2]
    assert back[1] == [Fr(1), Fr(0), Fr(0)], "observed variable kept as a point mass"
    for r, b in zip(rows, back):
        for x, y in zip(r, b):
            assert abs(float(y) - x) <= 5e-7


def test_mar_reader_handles_leading_pr_block():
    p = tempfile.NamedTemporaryFile("w", suffix=".MAR", delete=False).name
    open(p, "w").write("PR\n-10.4 (2.79e-05)\nMAR\n2 2 0.5 0.5 2 1.0 0.0\n")
    back, _ = uai.read_mar(p)
    assert back == [[Fr(1,2), Fr(1,2)], [Fr(1), Fr(0)]]


def test_model_check_rejects_wrong_table_length():
    bad = "MARKOV\n2\n2 2\n1\n2 0 1\n3\n1 2 3\n"
    try:
        uai.read_model(_w(bad))
    except AssertionError:
        return
    raise AssertionError("adapter accepted a malformed factor table")
