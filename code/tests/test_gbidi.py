"""Qualification controls for GENERAL_BIDI_V1 / NATIVE_PLAIN_V1 (tests run against the ACTUAL entry points: gbidi.executor.execute / publish, the
native kernel, the cell process). Every numerical check compares all original singleton numerators (through the published intervals) with the
brute-force exact oracle (bidi.oracle, exhaustive joint enumeration with Fractions; shares ext.uai parsing, not traversal). Covers the brief's
fixtures A-P where they apply to this V1, the two pending pilot defects (F1 range premise for every binary64-returning route; F2 empty dimensions),
the mandatory shared-node early-flush control (Z=20, N=(5,15) under split deltas with eviction), nonbinary / higher-arity / nonbipartite / zeros /
evidence / duplicates / scalars / isolated / disconnected / empty cases, all five arms, binary64 and MPFR routes, mechanism witnesses with
materialization-count reductions versus the same-backend disabled control, and the exact integer reference stream."""
from __future__ import annotations
import sys, os, json, time, random, subprocess, shutil
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from gbidi import executor as EX, plan as PL
from bidi import oracle as OR
from ext import uai as U

PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE)


def dec(q):
    q = Fr(q); assert (10 ** 6) % q.denominator == 0; n = q.numerator * (10 ** 6 // q.denominator); return "%d.%06d" % (n // 10 ** 6, n % 10 ** 6)


def write_uai(path, card, factors, ev=None, exact_tokens=None):
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(factors))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in factors]
    for i, (_, tab) in enumerate(factors):
        lines.append("%d %s" % (len(tab), " ".join((exact_tokens[i] if exact_tokens and exact_tokens[i] else [dec(x) for x in tab]))))
    open(path, "w").write("\n".join(lines) + "\n"); ev = ev or {}
    open(path + ".evid", "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in ev.items()))); return path, path + ".evid"


def rnd_model(seed, card, scopes, zeros=0.0, lo=1, hi=99):
    r = random.Random(seed); facs = []
    for sc in scopes:
        n = 1
        for v in sc:
            n *= card[v]
        facs.append((tuple(sc), [Fr(0) if r.random() < zeros else Fr(r.randint(lo, hi), 100) for _ in range(n)]))
    return facs


def run(arm, mp, ep, out, b64=True, budget=60, hooks=None, rules=None):
    cfg = {"budget_s": budget, "allow_binary64": b64, "reference_fallback": True}
    if rules is not None:
        cfg["rules"] = rules                                                                            # qualification only: keep variables the shared reductions would fold, to exercise the kernel path
    return EX.execute(arm, mp, ep, out, time.monotonic() + budget, cfg, test_hooks=hooks)


def truth_inside(rec, model, ev):
    Z, N = OR.brute(model, ev)
    if Z == 0:
        return rec["status"] == "ZERO_EVIDENCE_PROVED"
    assert rec["status"] == "INTERVALS_OK", rec.get("status")
    for v in range(model.nvars):
        row = rec["certified_intervals"][str(v)]; assert len(row) == model.card[v]
        for s, (a, b) in enumerate(row):
            if not (Fr(a) <= N[v][s] / Z <= Fr(b)):
                return False
    return True


ARMS = list(EX.ARMS)

# ------------------------------------------------------------------------------------------------------------ generality: every class of input, every arm, both routes
CASES = {  # name: (card, scopes, zeros, evidence)
    "nonbinary_chain": ([3, 2, 4, 3], [(0, 1), (1, 2), (2, 3), (3,)], 0.0, {}),
    "high_arity": ([2, 3, 2, 2], [(0, 1, 2), (1, 2, 3), (0, 3)], 0.0, {}),
    "odd_cycle_nonbinary": ([3, 3, 3], [(0, 1), (1, 2), (2, 0), (0,)], 0.0, {}),
    "zeros_cycle": ([2, 3, 2, 2], [(0, 1), (1, 2), (2, 3), (3, 0), (1, 3)], 0.3, {}),
    "evidence_high_arity": ([2, 2, 3, 2, 2], [(0, 1, 2), (2, 3, 4), (0, 4), (1,)], 0.1, {1: 1, 4: 0}),
    "disconnected_isolated": ([2, 3, 2, 2, 3], [(0, 1), (2, 3), (2,)], 0.0, {}),                          # variable 4 isolated (no factor)
    "duplicate_occurrences": ([2, 2], [(0,), (0,), (0, 1), (0, 1)], 0.0, {}),
    "scalar_and_unary_only": ([2, 3], [(), (0,), (1,), ()], 0.0, {}),
    "dense_grid_like": ([2] * 6, [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)], 0.0, {}),
    "kite_evidence_zero": ([2, 2, 2, 2], [(0, 1), (0, 2), (1, 2), (2, 3), (3,)], 0.4, {3: 0}),
}


@pytest.mark.parametrize("name", list(CASES))
@pytest.mark.parametrize("arm", ARMS)
def test_every_arm_encloses_exact_truth_on_every_input_class(tmp_path, name, arm):
    card, scopes, zeros, ev = CASES[name]; facs = rnd_model(hash(name) % 1000, card, scopes, zeros)
    mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs, ev); model = U.read_model(mp)
    for b64 in (True, False):
        rec = run(arm, mp, ep, str(tmp_path / ("%s_%d" % (arm, b64))), b64=b64)
        assert truth_inside(rec, model, ev), (name, arm, b64, rec.get("status"), rec.get("reason"))
        if rec["status"] == "INTERVALS_OK" and rec.get("precision") != "exact":                       # 'exact': every variable was reduced away (decoder constants)
            assert rec["route"] == ("binary64" if (b64 and rec["binary64_admission"]["checks"][-1].endswith("OK")) else "mpfr")
            cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / ("%s_%d" % (arm, b64))), mp, ep, rec, cell, time.monotonic() + 30) == "CERTIFIED" and cell["point_check"]["status"] == "POINT_VERIFIED"


# ------------------------------------------------------------------------------------------------------------ brief fixtures with stated exact answers
def _exact_check(rec, Z, N, card):
    assert rec["status"] == "INTERVALS_OK"
    for v in range(len(card)):
        for s in range(card[v]):
            a, b = rec["certified_intervals"][str(v)][s]; assert Fr(a) <= Fr(N[v][s], Z) <= Fr(b), (v, s, a, b, N[v][s], Z)


def test_F_arbitrary_arity_cardinality_exact_answers(tmp_path):
    mp, ep = write_uai(str(tmp_path / "t.uai"), [2, 2, 2], [((0, 1, 2), [Fr(i) for i in range(1, 9)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "t"))
    _exact_check(rec, 36, [[10, 26], [14, 22], [16, 20]], [2, 2, 2])
    mp, ep = write_uai(str(tmp_path / "u.uai"), [2, 3], [((0, 1), [Fr(i) for i in range(1, 7)])]); rec = run("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "u"))
    _exact_check(rec, 21, [[6, 15], [5, 7, 9]], [2, 3])


def test_G_zeros_and_inconsistency(tmp_path):
    mp, ep = write_uai(str(tmp_path / "eq.uai"), [2, 2], [((0, 1), [Fr(1), Fr(0), Fr(0), Fr(1)])], {0: 0, 1: 1}); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "eq"))
    assert rec["status"] == "ZERO_EVIDENCE_PROVED" and "certified_intervals" not in rec
    mp, ep = write_uai(str(tmp_path / "z.uai"), [2], [((0,), [Fr(0), Fr(2)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "z")); _exact_check(rec, 2, [[0, 2]], [2])
    mp, ep = write_uai(str(tmp_path / "z2.uai"), [2, 2], [((0,), [Fr(0), Fr(2)]), ((0, 1), [Fr(1), Fr(1), Fr(3), Fr(0)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "z2"), b64=False); _exact_check(rec, 6, [[0, 6], [6, 0]], [2, 2])


def test_J_duplicate_factor_occurrences_keep_multiplicity(tmp_path):
    mp, ep = write_uai(str(tmp_path / "d.uai"), [2], [((0,), [Fr(1), Fr(2)]), ((0,), [Fr(1), Fr(2)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "d")); _exact_check(rec, 5, [[1, 4]], [2])


def test_I_independent_unaries_and_shared_m_lambda_fixture(tmp_path):
    mp, ep = write_uai(str(tmp_path / "i.uai"), [2, 2], [((0,), [Fr(1), Fr(2)]), ((1,), [Fr(3), Fr(4)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "i")); _exact_check(rec, 21, [[7, 14], [9, 12]], [2, 2])
    # the mandatory shared-node control: m = lambda_0 + 3 lambda_1 (unary [1,3]), F = 2m + 3m realised as the root weight 5 split into deltas 2 and 3,
    # delivered separately with eviction + recomputation of every materialized value in between (gb_test_split_root) -> Z = 20, N = (5, 15)
    mp, ep = write_uai(str(tmp_path / "m.uai"), [2], [((0,), [Fr(1), Fr(3)]), ((), [Fr(5)])])
    rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "m"), b64=False, hooks={"split_root": ("2/5", "3/5", True)}, rules=[])
    assert rec["route"] == "mpfr" and rec["attempts"][-1]["counters"]["deltas_drained"] >= 2 and rec["attempts"][-1]["counters"]["recomputations"] >= 0
    _exact_check(rec, 20, [[5, 15]], [2]); a, b = rec["certified_intervals"]["0"][0]; assert Fr(a) <= Fr(1, 4) <= Fr(b) and Fr(b) - Fr(a) < Fr(1, 10 ** 15)
    rec2 = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "m2"), b64=False, rules=[]); _exact_check(rec2, 20, [[5, 15]], [2])         # coalesced single root delta
    # the wrong behaviours the control must distinguish: dropping the late delta would give N = (2, 6) (P = 1/4 still) -> detected by Z? no: Z is the
    # forward value; the derivative sum must equal Z: the executor's intervals come from N/Z, so N = (2,6) would give (1/10, 3/10), outside the exact (1/4, 3/4)
    assert not (Fr(a) <= Fr(1, 10) <= Fr(b))


def test_K_extreme_source_range_is_a_typed_route_limit_never_false_inconsistency(tmp_path):
    tok = ["0." + "0" * 399 + "1", "0." + "0" * 399 + "2"]; mp, ep = write_uai(str(tmp_path / "k.uai"), [2], [((0,), [Fr(1, 10 ** 400), Fr(2, 10 ** 400)])], exact_tokens=[tok])
    rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "k")); assert rec["status"] == "INTERVALS_OK"; _exact_check(rec, 3, [[1, 2]], [2])   # shared quotient rule: exact decoder result
    rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "k2"), rules=[])                           # kernel path: binary64 refused by the range envelope -> MPFR (huge exponent range) -> exact enclosure
    assert rec["status"] == "INTERVALS_OK" and rec["route"] == "mpfr" and "range envelope" in " ".join(rec["binary64_admission"]["checks"]); _exact_check(rec, 3, [[1, 2]], [2])
    # F1 (pilot): the frozen MPFR bridge narrowed to binary64; here MPFR endpoints are carried EXACTLY (dyadic) into the enclosure -> no narrowing at all
    mp2, ep2 = write_uai(str(tmp_path / "f1.uai"), [2], [((), [Fr(1, 10 ** 200)]), ((0,), [Fr(3, 10 ** 124), Fr(7, 10 ** 124)])], exact_tokens=[["1e-200"], ["3e-124", "7e-124"]])
    for rules in (None, []):
        rec = run("GENERAL_BIDI_V1", mp2, ep2, str(tmp_path / ("f1_%d" % (rules is None))), rules=rules); assert rec["status"] == "INTERVALS_OK"; _exact_check(rec, 10, [[3, 7]], [2])
        if rules == []:
            assert rec["route"] == "mpfr"
    mp3, ep3 = write_uai(str(tmp_path / "f1b.uai"), [2, 2], [((0,), [Fr(1, 10 ** 200)] * 2), ((1,), [Fr(1, 10 ** 200)] * 2)], exact_tokens=[["1e-200", "1e-200"], ["1e-200", "1e-200"]])
    for rules in (None, []):
        rec = run("GENERAL_BIDI_V1", mp3, ep3, str(tmp_path / ("f1b_%d" % (rules is None))), rules=rules); assert rec["status"] == "INTERVALS_OK"; _exact_check(rec, 4, [[2, 2], [2, 2]], [2, 2])


def test_L_normalized_leaf_with_requested_child(tmp_path):
    mp, ep = write_uai(str(tmp_path / "l.uai"), [2, 2], [((0,), [Fr(1, 2), Fr(1, 2)]), ((0, 1), [Fr(1), Fr(0), Fr(0), Fr(1)])], {0: 1}); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "l"))
    assert rec["status"] == "INTERVALS_OK" and rec["certified_intervals"]["1"] == [["0", "0"], ["1", "1"]] and rec["certified_intervals"]["0"] == [["0", "0"], ["1", "1"]]


def test_C_D_multiple_consumers_and_live_class_with_dead_representative(tmp_path):
    # D: f(A,S)=[[1,1],[2,2]], h(S)=(0,1): Z=3, N_A=(1,2), N_S=(0,3); S's rows of f are proportional (one class) but S=0 is dead under h
    mp, ep = write_uai(str(tmp_path / "d.uai"), [2, 2], [((0, 1), [Fr(1), Fr(1), Fr(2), Fr(2)]), ((1,), [Fr(0), Fr(1)])])
    for arm in ("GENERAL_BIDI_V1", "A1_NO_DEMAND_MASKS", "A3_NO_RESPONSE_VIEWS"):
        rec = run(arm, mp, ep, str(tmp_path / arm)); _exact_check(rec, 3, [[1, 2], [0, 3]], [2, 2])
    # C: child m = (1,2) consumed through h1=(1,0) and h2=(0,1) additively = unary (1,2) x unary (1,1): Z = 3, N = (1, 2)
    mp, ep = write_uai(str(tmp_path / "c.uai"), [2], [((0,), [Fr(1), Fr(2)]), ((0,), [Fr(1), Fr(1)])]); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "c")); _exact_check(rec, 3, [[1, 2]], [2])


def test_E_crossing_block_partitions_exact(tmp_path):
    # a=b, c=d, a=c, b=d: Z = 2 (0000 and 1111); every state numerator 1
    eq = [Fr(1), Fr(0), Fr(0), Fr(1)]; mp, ep = write_uai(str(tmp_path / "x.uai"), [2] * 4, [((0, 1), eq), ((2, 3), eq), ((0, 2), eq), ((1, 3), eq)])
    for arm in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
        rec = run(arm, mp, ep, str(tmp_path / arm)); _exact_check(rec, 2, [[1, 1]] * 4, [2] * 4)


def test_H_cache_context_includes_the_full_separator(tmp_path):
    eq = [Fr(1), Fr(0), Fr(0), Fr(1)]; mp, ep = write_uai(str(tmp_path / "h.uai"), [2] * 3, [((0, 2), eq), ((1, 2), eq)])
    for arm in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
        rec = run(arm, mp, ep, str(tmp_path / arm)); _exact_check(rec, 2, [[1, 1]] * 3, [2] * 3)


# ------------------------------------------------------------------------------------------------------------ mechanism witnesses: exact answers AND fewer materialized entries than the same-backend disabled control
def _materialized(rec):
    return rec["attempts"][-1]["counters"]["entries_materialized"], rec["plan"]["totals"]["materialized_entries"], rec["attempts"][-1]["counters"]["rows"]


def test_mechanism_response_views_reduce_materialization_on_a_nonbipartite_nonbinary_model(tmp_path):
    # chain 0-1-2-3, card [3, 2, 4, 2]: f(1,2)'s columns for states 0 and 1 of variable 2 are proportional ((1,2) and (2,4)) while columns 2, 3 are not
    # ((1,3), (2,1)): along axis 2 the response view has 3 classes for 4 raw states; the table is NOT rank-1 (no 'separate'), and f(2,3) is not proportional
    # along 2 (no 'quotient'), so no shared reduction absorbs it: the bucket eliminating 1 stores 3 core entries instead of 4
    tab12 = [Fr(1), Fr(2), Fr(1), Fr(2), Fr(2), Fr(4), Fr(3), Fr(1)]                                       # b-major: b=0: (c0..c3) = 1,2,1,2 ; b=1: 2,4,3,1
    facs = [((0, 1), rnd_model(3, [3, 2], [(0, 1)])[0][1]), ((1, 2), tab12), ((2, 3), [Fr(1), Fr(2), Fr(3), Fr(1), Fr(2), Fr(5), Fr(1), Fr(7)]), ((3,), [Fr(1), Fr(2)])]
    mp, ep = write_uai(str(tmp_path / "v.uai"), [3, 2, 4, 2], facs); model = U.read_model(mp)
    on = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "on")); off = run("A3_NO_RESPONSE_VIEWS", mp, ep, str(tmp_path / "off"))
    assert truth_inside(on, model, {}) and truth_inside(off, model, {})
    assert on["mechanisms"]["views"]["compressed_axes"] >= 1 and off["mechanisms"]["views"]["state"] == "DISABLED"
    assert on["plan"]["totals"]["planned_core_entries"] < off["plan"]["totals"]["planned_core_entries"]


def test_mechanism_demand_masks_reduce_materialization_with_zero_siblings(tmp_path):
    # consumer factor f(1,2) has scattered zeros (no whole zero row/column, so the shared exclude rule does not fire): rows (b,c) in {(0,0),(2,1)} of the
    # child bucket (eliminating 0, scope (1,2)) are never demanded by the consumer's support
    facs = [((0, 1), [Fr(1), Fr(2), Fr(3), Fr(4), Fr(5), Fr(6)]), ((1, 2), [Fr(0), Fr(1), Fr(2), Fr(3), Fr(4), Fr(0)]), ((0, 2), [Fr(1), Fr(2), Fr(3), Fr(1)]), ((2,), [Fr(1), Fr(3)])]
    mp, ep = write_uai(str(tmp_path / "dm.uai"), [2, 3, 2], facs); model = U.read_model(mp)
    on = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "on")); off = run("A1_NO_DEMAND_MASKS", mp, ep, str(tmp_path / "off"))
    assert truth_inside(on, model, {}) and truth_inside(off, model, {})
    assert on["mechanisms"]["demand"]["entries_skipped_by_demand"] >= 1 and off["mechanisms"]["demand"]["state"] == "DISABLED"
    assert on["plan"]["totals"]["demanded_entries_all_nodes"] < off["plan"]["totals"]["demanded_entries_all_nodes"]        # fewer entries are ever requested (fusion decisions may differ: recorded policy effect)


def test_mechanism_fusion_avoids_storing_an_intermediate_and_records_recomputation(tmp_path):
    card = [2, 3, 2, 3, 2]; facs = rnd_model(77, card, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]); mp, ep = write_uai(str(tmp_path / "f.uai"), card, facs); model = U.read_model(mp)
    on = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "on"), b64=False); off = run("A2_NO_FUSION", mp, ep, str(tmp_path / "off"), b64=False)
    assert truth_inside(on, model, {}) and truth_inside(off, model, {})
    assert off["mechanisms"]["fusion"]["state"] == "DISABLED" and off["plan"]["totals"]["fused"] == 0
    if on["plan"]["totals"]["fused"] > 0:
        assert on["plan"]["totals"]["materialized_entries"] < off["plan"]["totals"]["materialized_entries"] and on["attempts"][-1]["counters"]["fused_reevals"] > 0
    else:
        assert on["mechanisms"]["fusion"]["edges_offered"] > 0                                           # a declined fusion is a recorded no-op, not an absent mechanism


# ------------------------------------------------------------------------------------------------------------ reference stream, memory caps, deadline, empty / degenerate
def test_reference_stream_exact_on_tiny_models_and_used_on_memory_stop(tmp_path, monkeypatch):
    card = [3, 2, 2]; facs = rnd_model(5, card, [(0, 1), (1, 2), (0, 2)], zeros=0.2); mp, ep = write_uai(str(tmp_path / "r.uai"), card, facs); model = U.read_model(mp)
    from adp import source as SRC
    m, ev = SRC.load(mp, ep); R = SRC.Reduced(m, ev); R.reduce([], deadline=time.monotonic() + 1)
    fb = EX.reference_stream(R, time.monotonic() + 10); Z, N = OR.brute(model, {}); assert fb["status"] == "COMPLETE"
    # the reduced model equals the original here (no rules enabled); the integer scale cancels in ratios
    for v in range(3):
        for s in range(card[v]):
            assert fb["N"][v][s] / fb["Z"] == N[v][s] / Z
    # memory stop -> fallback: shrink the value cap so the plan cannot allocate
    monkeypatch.setattr(PL, "CAPS", dict(PL.CAPS, value_cache=1, reverse_pinned=1 << 30))
    rec = run("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "mem"), b64=False); assert rec.get("reference_fallback", {}).get("status") == "COMPLETE" and rec["precision"] == "exact_integer_reference" and truth_inside(rec, model, {})


def test_deadline_inside_the_native_stream_is_a_typed_resource_stop(tmp_path):
    n = 18; card = [2] * n; facs = rnd_model(9, card, [(i, j) for i in range(n) for j in range(i + 1, n)]); mp, ep = write_uai(str(tmp_path / "dl.uai"), card, facs)   # one bucket of 2^17 entries x 2 rows x 153 inputs
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.05, {"budget_s": 0.05, "allow_binary64": False, "reference_fallback": True, "rules": []})
    assert e.value.kind == "RESOURCE_STOP" and "DEADLINE" in e.value.reason


def test_empty_model_zero_variables_and_unary_only(tmp_path):
    mp = str(tmp_path / "e.uai"); open(mp, "w").write("MARKOV\n0\n\n1\n0\n1 2.5\n"); open(mp + ".evid", "w").write("0\n")
    rec = run("GENERAL_BIDI_V1", mp, mp + ".evid", str(tmp_path / "e")); assert rec["status"] == "INTERVALS_OK" and rec["certified_intervals"] == {} and Fr(rec["Z_exact"]) == Fr(5, 2)
    cell = {"phases_s": {}}; assert EX.publish(str(tmp_path / "e"), mp, mp + ".evid", rec, cell, time.monotonic() + 10) == "CERTIFIED"
    open(mp, "w").write("MARKOV\n0\n\n1\n0\n1 0\n"); rec = run("GENERAL_BIDI_V1", mp, mp + ".evid", str(tmp_path / "e0")); assert rec["status"] == "ZERO_EVIDENCE_PROVED"
    mp2, ep2 = write_uai(str(tmp_path / "u.uai"), [3, 2], [((0,), [Fr(1), Fr(2), Fr(3)]), ((1,), [Fr(1), Fr(1)])]); rec = run("NATIVE_PLAIN_V1", mp2, ep2, str(tmp_path / "u")); _exact_check(rec, 12, [[2, 4, 6], [6, 6]], [3, 2])


# ------------------------------------------------------------------------------------------------------------ cells, binding, publication (O)
def _cell(arm, mp, ep, out, budget="60"):
    subprocess.run([PY, "-m", "gbidi.cell", arm, mp, ep, out, budget, "{}"], cwd=HERE, env=ENV, capture_output=True, timeout=300); return json.load(open(os.path.join(out, "cell.json")))


@pytest.mark.parametrize("arm", ARMS)
def test_cell_process_certifies_and_binds_every_arm(tmp_path, arm):
    card = [2, 3, 2]; facs = rnd_model(12, card, [(0, 1), (1, 2), (0, 2)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs, {2: 1}); model = U.read_model(mp); Z, N = OR.brute(model, {2: 1}); assert Z > 0
    out = str(tmp_path / arm); r = _cell(arm, mp, ep, out); assert r["status"] == "CERTIFIED", (arm, r.get("reason"), r.get("stop"))
    rows, _ = U.read_mar(os.path.join(out, "output.MAR")); assert all(sum(Fr(x) for x in rows[v]) == 1 and all(abs(Fr(rows[v][s]) - N[v][s] / Z) < Fr(1, 200) for s in range(card[v])) for v in range(3)) and rows[2] == [Fr(0), Fr(1)]
    assert r["task"]["raw_evidence_sha256"] == EX.sha_file(ep) and r["point_check"]["status"] == "POINT_VERIFIED" and r["reductions"]["free_reduced"] == 2
    assert r["mechanisms"]["views"]["state"].startswith("DISABLED" if arm in ("NATIVE_PLAIN_V1", "A3_NO_RESPONSE_VIEWS") else "APPLIED") and "complete_response_from_launch_s" not in r   # (the launcher's timestamp is only set by the stage runner)


def test_O_binding_and_publication_rejections(tmp_path):
    card = [2, 2]; facs = rnd_model(13, card, [(0, 1), (0,)]); mp, ep0 = write_uai(str(tmp_path / "m.uai"), card, facs, {0: 0}); ep1 = str(tmp_path / "m1.evid"); open(ep1, "w").write("1 0 1\n")
    o0 = str(tmp_path / "o0"); r0 = _cell("GENERAL_BIDI_V1", mp, ep0, o0); assert r0["status"] == "CERTIFIED"; rec0 = json.load(open(os.path.join(o0, "checked_record.json")))
    cell = {"phases_s": {}}; o2 = str(tmp_path / "o2"); os.makedirs(o2); assert EX.publish(o2, mp, ep1, rec0, cell, time.monotonic() + 10) == "CHECK_FAILED" and not os.path.exists(os.path.join(o2, "output.MAR"))
    op = str(tmp_path / "pc.json"); subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o0, "checked_record.json"), os.path.join(o0, "output.MAR"), mp, ep1, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"
    for mut in ("status", "missing_row", "extra_row", "short_row"):
        bad = json.loads(json.dumps(rec0)); d = str(tmp_path / ("b_" + mut)); os.makedirs(d)
        if mut == "status":
            bad["status"] = "REJECTED"
        elif mut == "missing_row":
            del bad["certified_intervals"]["1"]
        elif mut == "extra_row":
            bad["certified_intervals"]["5"] = [["0", "1"], ["0", "1"]]
        else:
            bad["certified_intervals"]["1"] = bad["certified_intervals"]["1"][:1]
        cell = {"phases_s": {}}; assert EX.publish(d, mp, ep0, bad, cell, time.monotonic() + 10) == "CHECK_FAILED"
    o3 = str(tmp_path / "o3"); os.makedirs(o3); shutil.copy(os.path.join(o0, "checked_record.json"), o3); shutil.copy(os.path.join(o0, "output.MAR"), o3)
    r3 = _cell("GENERAL_BIDI_V1", mp, ep1, o3); assert r3["status"] == "CERTIFIED" and U.read_mar(os.path.join(o3, "output.MAR"))[0][0] == [Fr(0), Fr(1)]
    mar = os.path.join(o0, "output.MAR"); toks = open(mar).read().split(); i = next(k for k, t in enumerate(toks) if "." in t); toks[i] = "0.5x"; alt = str(tmp_path / "alt.MAR"); open(alt, "w").write(" ".join(toks) + "\n")
    subprocess.run([PY, "-m", "adp.checker", "--verify-point", os.path.join(o0, "checked_record.json"), alt, mp, ep0, op], cwd=HERE, env=ENV, capture_output=True); assert json.load(open(op))["status"] == "POINT_REJECTED"


def test_P_forged_completion_counters_do_not_hide_a_wrong_enumeration(tmp_path):
    """the executor checks every row's two/many numerators sum to Z within the certified error? Here: the kernel's counters are diagnostics only; the
    PROOF is the enclosure of the exact truth. A mutant kernel is not loadable (binary hash bound); instead check that an altered RESULT (one
    numerator scaled) is caught by the row-sum consistency of the enclosures against Z (every row must sum to Z within the width)."""
    card = [2, 3]; facs = rnd_model(21, card, [(0, 1), (1,)]); mp, ep = write_uai(str(tmp_path / "p.uai"), card, facs); rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "p"), b64=False)
    for v in range(2):
        row = rec["certified_intervals"][str(v)]; lo = sum(Fr(a) for a, _ in row); hi = sum(Fr(b) for _, b in row); assert lo <= 1 <= hi


def test_shared_reductions_have_a_valid_marked_interpretation(tmp_path):
    """every common rule fires on this fixture (exclude via a zero row, alias via a bijective pair factor, quotient via proportional rows, separate via
    a rank-1 table, constants); the ORIGINAL model's exact marginals must lie inside the decoded enclosures (the decoder is the marker program)."""
    eq = [Fr(1), Fr(0), Fr(0), Fr(1)]; r1 = [Fr(1), Fr(2), Fr(3), Fr(2), Fr(4), Fr(6)]                      # (0,1) alias; (2,3) rank-1 separable
    facs = [((0, 1), eq), ((2, 3), r1), ((1, 4), [Fr(1), Fr(2), Fr(1), Fr(2), Fr(3), Fr(6)]), ((4,), [Fr(0), Fr(1), Fr(1)]), ((3, 5), [Fr(1), Fr(1), Fr(2), Fr(2), Fr(3), Fr(3)]), ((5,), [Fr(2), Fr(3)]), ((), [Fr(1, 2)])]
    card = [2, 2, 2, 3, 3, 2]; mp, ep = write_uai(str(tmp_path / "s.uai"), card, facs); model = U.read_model(mp)
    for arm in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
        rec = run(arm, mp, ep, str(tmp_path / arm)); assert truth_inside(rec, model, {}), (arm, rec["reductions"]["steps"])
        assert set(rec["reductions"]["steps"]) >= {"alias", "quotient", "exclude"} or rec["reductions"]["free_reduced"] < 6


def test_kernel_deadline_is_relative_and_a_generous_budget_completes_a_medium_model(tmp_path):
    """Regression (found in qualification): the kernel received an ABSOLUTE Python time.monotonic() deadline; on macOS that clock (mach_absolute_time)
    differs from the kernel's CLOCK_MONOTONIC by ~10^6 s, so every native stream stopped at its first poll. Deadlines are now passed as REMAINING seconds.
    A 2^13-entry bucket with a 60 s budget must complete; the same model with a 0.001 s budget must stop with DEADLINE."""
    n = 14; card = [2] * n; facs = rnd_model(4, card, [(i, j) for i in range(n) for j in range(i + 1, n)]); mp, ep = write_uai(str(tmp_path / "k.uai"), card, facs)
    rec = EX.execute("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "ok"), time.monotonic() + 60, {"budget_s": 60, "allow_binary64": False, "reference_fallback": False, "rules": []})
    assert rec["status"] == "INTERVALS_OK" and rec["attempts"][-1]["counters"]["polls"] >= 1
    with pytest.raises(EX.Refuse) as e:
        EX.execute("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "dl"), time.monotonic() + 0.001, {"budget_s": 0.001, "allow_binary64": False, "reference_fallback": False, "rules": []})
    assert "DEADLINE" in e.value.reason


def test_fusion_policy_prices_the_fused_subtree_and_declines_many_reads(tmp_path):
    """A child read bijectively by its single consumer is fused (equal work, no storage); a child whose consumer has many more rows than the child has
    entries is NOT fused (re-evaluation would multiply work); the recorded cold-work proxy of a fused chain equals the materialized one."""
    from adp import source as SRC
    # chain 0-1-2-3 (card 2): bucket of 0 (scope {1}, 2 entries) is read once per row of bucket 1 (2 entries x 2) -> fused; same down the chain
    card = [2] * 4; facs = rnd_model(1, card, [(0, 1), (1, 2), (2, 3)]); mp, ep = write_uai(str(tmp_path / "c.uai"), card, facs)
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None)
    P, table = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V1"], bytes_per_entry=96)); assert P.totals()["fused"] >= 1
    # star: variable 0 has a unary only (bucket of 0 has 1 entry, scope {}) -> it is a root, never fused; variable 5 connected to 1..4 with a 5-ary factor:
    # bucket of 1 (eliminates 1; scope {2,3,4,5}: 16 entries, read once each by bucket 2) fused; the pricing never multiplies work: cold proxy == ideal
    card = [2] * 6; facs = [((0,), [Fr(1), Fr(2)]), ((1, 2, 3, 4, 5), [Fr(i % 7 + 1) for i in range(32)]), ((5,), [Fr(1), Fr(3)])]; mp, ep = write_uai(str(tmp_path / "s.uai"), card, facs)
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V1"], bytes_per_entry=96)); t = P.totals()
    assert t["cold_work_proxy"] <= 2 * t["ideal_reuse_lower"] + 64, t
    # many-reads: child bucket of 0 (scope {1}, 2 entries) consumed by bucket 1 whose scope is {2,3,4,5,6,7,8} (128 entries x 2 rows): fusion would re-evaluate
    # the child 256 times for 2 entries -> declined
    card = [2] * 9; facs = [((0, 1), [Fr(1), Fr(2), Fr(3), Fr(4)]), ((1, 2, 3, 4, 5, 6, 7, 8), [Fr(i % 5 + 1) for i in range(256)])]; mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs)
    m = U.read_model(mp); R = SRC.Reduced(EX._ModelAdapter(m), {}); R.reduce([], deadline=None); P, _ = PL.plan(R, dict(EX.ARMS["GENERAL_BIDI_V1"], bytes_per_entry=96))
    n0 = next(nd for nd in P.nodes if nd.x == 0); assert not n0.fused and P.mechanisms["fusion"]["edges_offered"] >= 1


def test_binary64_enclosures_are_consistent_with_rigorous_mpfr_and_bracket_the_simplex_on_a_medium_model(tmp_path):
    """Regression (attempt 1 of the broad round, BARLEY cell 010): the binary64 depth label omitted the sequential accumulation counts; the
    enclosure was unsound (disjoint from the MPFR intervals at 6 coordinates) and only the infeasible simplex point exposed it. Controls: (a) on a
    model with > 10^5 accumulated rows, every binary64 interval must INTERSECT the rigorous MPFR interval and every row must bracket 1; (b) on a
    2^16-joint grid the binary64 enclosure contains the exact truth; (c) the executor refuses an enclosure that fails the bracket (mutant)."""
    card = [4] * 10; facs = rnd_model(31, card, [(0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 8), (8, 9, 0), (1, 5, 9), (3, 7)]); mp, ep = write_uai(str(tmp_path / "m.uai"), card, facs)   # 4^10 joint; buckets up to 4^5 x 4 rows
    for arm in ("NATIVE_PLAIN_V1", "GENERAL_BIDI_V1"):
        b = run(arm, mp, ep, str(tmp_path / (arm + "_b")), b64=True, rules=[]); m = run(arm, mp, ep, str(tmp_path / (arm + "_m")), b64=False, rules=[])
        assert b["route"] == "binary64" and m["route"] == "mpfr" and b["attempts"][-1]["counters"]["rows"] > 10 ** 3, b["attempts"][-1]["counters"]["rows"]   # thousands of accumulated rows (the planner picks a cheap order)
        for v, row in b["certified_intervals"].items():
            assert sum(Fr(a) for a, _ in row) <= 1 <= sum(Fr(x) for _, x in row)
            for s, (a, x) in enumerate(row):
                ma, mb = [Fr(t) for t in m["certified_intervals"][v][s]]; assert not (Fr(x) < ma or Fr(a) > mb), (arm, v, s)
    card = [2] * 16; facs = rnd_model(32, card, [(i, i + 1) for i in range(15)] + [(i, i + 4) for i in range(12)] + [(v,) for v in range(16)]); mp, ep = write_uai(str(tmp_path / "g.uai"), card, facs); model = U.read_model(mp)
    rec = run("GENERAL_BIDI_V1", mp, ep, str(tmp_path / "g"), b64=True, rules=[]); assert rec["route"] == "binary64" and truth_inside(rec, model, {})
    # (c) mutant: shrink delta to zero by monkeypatching the admission -> the executor's bracket check must refuse before publication
    import gbidi.executor as EXm
    orig = EXm.binary64_admission
    def tight(P):
        ok, a = orig(P); a["delta_fr"] = Fr(0); return ok, a
    EXm.binary64_admission = tight
    try:
        card = [4] * 10; facs = rnd_model(31, card, [(0, 1, 2), (2, 3, 4), (4, 5, 6), (6, 7, 8), (8, 9, 0), (1, 5, 9), (3, 7)]); mp, ep = write_uai(str(tmp_path / "t.uai"), card, facs)
        rec = run("NATIVE_PLAIN_V1", mp, ep, str(tmp_path / "t"), b64=True, rules=[])
        assert rec["route"] == "mpfr" and any(str(a.get("outcome", "")).startswith("ENCLOSURE_UNSOUND") or a.get("refused") for a in rec["attempts"]), [a.get("outcome") for a in rec["attempts"]]
    finally:
        EXm.binary64_admission = orig
