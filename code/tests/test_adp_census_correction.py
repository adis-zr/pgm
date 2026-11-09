"""Small controls for the OFFLINE extractor logic of the bounded census correction (adp/census_closeout/correct.py): the predicates that
produced the corrected derived records are exercised on toy inputs with known answers. Nothing numerical; no cell is read."""
from __future__ import annotations
import sys, os
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from adp.census_closeout import correct as X


def test_refines_is_class_inclusion_not_class_count():
    assert X.refines([0, 1, 2, 3], [0, 0, 1, 1])                 # finer -> coarser
    assert not X.refines([0, 0, 1, 1], [0, 1, 2, 3])
    assert not X.refines([0, 0, 1, 1], [0, 1, 0, 1])             # same count, crossing: neither refines the other
    assert not X.refines([0, 1, 0, 1], [0, 0, 1, 1])
    assert X.refines([0, -1, 1, 1], [0, 5, 1, 1])                # zero states (-1) are skipped on either side


def test_common_refinement_witness_distinguishes_discrete_input_from_joint_refinement():
    # two crossing 2-class partitions of 4 states: neither is discrete, their common refinement is -> 'joint' with both inputs needed
    kind, need = X.common_refinement_witness(4, [[0, 0, 1, 1], [0, 1, 0, 1]])
    assert kind == "joint" and need == [0, 1]
    # one discrete input is sufficient (not necessary): reported as 'discrete_input' naming it
    kind, idx = X.common_refinement_witness(4, [[0, 0, 1, 1], [0, 1, 2, 3]])
    assert kind == "discrete_input" and idx == [1]
    # three inputs where only a specific pair is needed: the minimal subset is that pair, not all three
    kind, need = X.common_refinement_witness(4, [[0, 0, 0, 0], [0, 0, 1, 1], [0, 1, 0, 1]])
    assert kind == "joint" and need == [1, 2]
    # inputs whose common refinement is NOT discrete
    kind, need = X.common_refinement_witness(4, [[0, 0, 1, 1], [0, 0, 1, 1]])
    assert kind == "not_full" and need is None
    # the MUNIN1 node 55 / axis 80 shape (4 and 3 classes jointly refining 5 states): joint, and the larger-count input does NOT refine the other
    a = [0, 1, 2, 3, 3]; b = [0, 0, 1, 2, 1]
    assert X.common_refinement_witness(5, [a, b]) == ("joint", [0, 1]) and not X.refines(a, b)


def test_single_input_split_counts_source_factor_message_and_root_message_nodes():
    plan = {"nodes": [
        {"nid": 0, "inputs": [["F", 3]], "parent": 1, "size": 7},                 # source-factor single input
        {"nid": 1, "inputs": [["M", 0]], "parent": 2, "size": 5},                 # message single input (non-root)
        {"nid": 2, "inputs": [["M", 1], ["F", 4]], "parent": 3, "size": 9},       # two inputs: not single-input
        {"nid": 3, "inputs": [["M", 2]], "parent": None, "size": 1}]}              # root with a single message input
    assert X.single_input_split(plan) == (1, 1, 1, 5)


def test_direct_two_term_payload_counts_coefficients_plus_boundary_vectors():
    # |D_x| = 2, 22 binary pair factors of 4 entries: 2 x (1 + 22 x 2) = 90 (the DBN_16 node-0 figure); the saved proxy would be 2 x (2 + 22 x 4) = 180
    assert X.direct_two_term_payload(2, [4] * 22) == 90
    assert 2 * (2 + 22 * 4) == 180
    # ternary eliminated variable, two pair factors with 3x2 and 3x4 entries: 3 x (1 + 2 + 4) = 21
    assert X.direct_two_term_payload(3, [6, 12]) == 21
