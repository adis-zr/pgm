"""Synthetic wrapper controls for the complete-query aggregation (addendum §1).

Covers: different sign-specific rankings, unresolved nodes, a zero marker lower bound, a known first qualifying prefix,
the valid [0,1] pre-processing state, D-vs-W separation, and the checker's refusal to substitute its own prefix.
No numerical construction, no kernel, no model: the inputs are exact synthetic intervals."""
import sys, pathlib
HERE = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(HERE))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import pytest
from h4q.aggregate import (SignState, NumericalRefusal, interval_product, endpoint_sum, difference,
                           verify_prefix, WIDTH_TARGET, POSITIVE_ALLOWANCE, floor_mesh, ceil_mesh)

DELTA = Fr(1, 10000)


def _state(sign, nodes):
    """nodes: {node: (Zplus, Zminus, w)}"""
    st = SignState(sign, DELTA)
    for node, (zp, zm, w) in nodes.items(): st.set_node(node, zp, zm, w)
    return st


def test_pre_processing_state_is_valid_zero_one():
    """With nothing processed every W has lower endpoint 0, so L_plus = L_minus = 0 and the sharp ratio
    [L+/(L++U-), U+/(U++L-)] already evaluates to exactly [0,1]. Either branch must yield that VALID enclosure and
    must not be treated as a failure. (The explicit 'no positive lower information' branch is the fallback for the
    degenerate case where both denominators vanish.)"""
    st = _state(1, {(0, 0): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))})
    e = st.prefix_enclosure()
    assert e["L_plus"] == 0 and e["L_minus"] == 0
    assert e["enclosure"] == (Fr(0), Fr(1)), "the pre-processing enclosure must be exactly [0,1]"
    assert not st.qualifies()          # width 1 > 1/100: valid but not yet qualifying
    # and the degenerate all-zero case takes the explicit fallback branch
    z = SignState(1, DELTA); z.W[((9, 9), 1)] = (Fr(0), Fr(0)); z.W[((9, 9), -1)] = (Fr(0), Fr(0))
    ez = z.prefix_enclosure()
    assert ez["enclosure"] == (Fr(0), Fr(1)) and ez["basis"] == "no positive lower information yet"


def test_unresolved_nodes_contribute_to_W_not_D():
    """R_sigma is the JOINT marker response normalised by the TOTAL positive mass, so a consistent fixture needs
    R_sigma ~ Z_sigma/T. Z+=2, Z-=3 gives R_+ = 2/5, R_- = 3/5."""
    st = _state(1, {(0, 0): ((Fr(2), Fr(2)), (Fr(3), Fr(3)), (Fr(1), Fr(1))),
                    (1, 0): ((Fr(5), Fr(5)), (Fr(7), Fr(7)), (Fr(1), Fr(1)))})
    assert st.D == {}
    assert st.W[((0, 0), 1)] == (Fr(0), Fr(2)) and st.W[((1, 0), -1)] == (Fr(0), Fr(7))
    st.rank_and_designate_tail()
    st.process_node((0, 0), {1: (Fr(2, 5), Fr(2, 5)), -1: (Fr(3, 5), Fr(3, 5))})
    assert ((0, 0), 1) in st.D                      # processed -> D populated
    assert ((1, 0), 1) not in st.D                  # unresolved -> still only in W
    assert st.W[((1, 0), 1)] == (Fr(0), Fr(5))


def test_per_sign_state_is_independent():
    """different rankings per sign must not interfere"""
    a = _state(1, {(0, 0): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(10), Fr(10))),
                   (1, 0): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))})
    b = _state(-1, {(0, 0): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1))),
                    (1, 0): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(10), Fr(10)))})
    ra = a.rank_and_designate_tail(); rb = b.rank_and_designate_tail()
    assert a.order[0] == (0, 0) and b.order[0] == (1, 0)          # opposite rankings
    assert a.denom == b.denom                                      # same total, different order
    assert a.processed == set() and b.processed == set()


def test_tie_break_is_lexicographic():
    st = _state(1, {(1, 5): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1))),
                    (1, -5): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1))),
                    (0, 9): ((Fr(1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))})
    st.rank_and_designate_tail()
    assert st.order == [(0, 9), (1, -5), (1, 5)]                   # equal scores -> lexicographic ascending


def test_zero_marker_lower_bound_is_refused_as_unsupported():
    st = SignState(1, DELTA)
    with pytest.raises(NumericalRefusal, match="not strictly positive"):
        st.set_node((0, 0), (Fr(0), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))


def test_inverted_and_negative_intervals_are_refused():
    st = SignState(1, DELTA)
    with pytest.raises(NumericalRefusal, match="inverted"):
        st.set_node((0, 0), (Fr(2), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))
    with pytest.raises(NumericalRefusal, match="negative"):
        st.set_node((1, 0), (Fr(-1), Fr(1)), (Fr(1), Fr(1)), (Fr(1), Fr(1)))


def test_known_first_qualifying_prefix():
    """equal-mass nodes with a symmetric marker split: each processed node converts a [0,Zhi] bound into a tight
    contribution, so the enclosure narrows monotonically until it qualifies."""
    eq = (Fr(10), Fr(10))
    nodes = {(j, 0): (eq, eq, (Fr(1), Fr(1))) for j in range(6)}
    st = _state(1, nodes); st.rank_and_designate_tail()
    widths = []
    first = None
    for idx, node in enumerate([n for n in st.order if n not in st.omit], start=1):
        st.process_node(node, {1: (Fr(1, 2), Fr(1, 2)), -1: (Fr(1, 2), Fr(1, 2))})
        widths.append(st.width())
        if first is None and st.qualifies(): first = idx
    assert widths[0] > widths[-1]                      # the enclosure tightens monotonically
    assert first is not None, f"never qualified; widths {[float(w) for w in widths]}"
    v = verify_prefix(st, first, {k: st.W[k] for k in st.W})
    assert v["matches_claimed"] and v["all_checker_contributions_contained"]
    assert v["checker_does_not_select_a_replacement_prefix"]


def test_checker_with_tighter_bounds_does_not_move_the_prefix():
    """the checker's contributions are strictly tighter; the recomputed prefix must still be the producer's"""
    nodes = {(j, 0): ((Fr(10), Fr(10)), (Fr(10), Fr(10)), (Fr(1), Fr(1))) for j in range(4)}
    st = _state(1, nodes); st.rank_and_designate_tail()
    first = None
    for idx, node in enumerate([n for n in st.order if n not in st.omit], start=1):
        st.process_node(node, {1: (Fr(1, 2), Fr(1, 2)), -1: (Fr(1, 2), Fr(1, 2))})
        if first is None and st.qualifies(): first = idx
    tighter = {}
    for k, iv in st.W.items():
        mid = (iv[0] + iv[1]) / 2
        tighter[k] = (mid - (mid - iv[0]) / 2, mid + (iv[1] - mid) / 2)   # strictly inside
    v = verify_prefix(st, first, tighter)
    assert v["all_checker_contributions_contained"]
    assert v["matches_claimed"], "the checker must not move the prefix using its own tighter bounds"


def test_difference_and_outward_mesh():
    ep = (Fr(6, 10), Fr(61, 100)); em = (Fr(2, 10), Fr(21, 100))
    d = difference(ep, em)
    assert d == (ep[0] - em[1], ep[1] - em[0])
    assert floor_mesh(Fr(1, 3)) <= Fr(1, 3) <= ceil_mesh(Fr(1, 3))
    assert (floor_mesh(Fr(1, 3)) * (1 << 64)).denominator == 1


def test_interval_product_is_full_outward():
    assert interval_product((Fr(-2), Fr(3)), (Fr(-5), Fr(7))) == (Fr(-15), Fr(21))
    assert endpoint_sum((Fr(1), Fr(2)), (Fr(3), Fr(4))) == (Fr(4), Fr(6))
