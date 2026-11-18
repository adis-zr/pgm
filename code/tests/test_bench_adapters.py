"""Controls for the external-sweep adapters that remain in the working library (18 Nov 2026 cleanup: the BIF conversion and harness-identity controls went with bench/bif.py and bench/campaign.py; they stay in the git history): native-CBI adapter + independent checker,
cell runner output validation. Source-order / state-order permutations, evidence indexing, zero factors, impossible evidence, disconnected
models, reference-pointer tampering."""
import os, sys, json, itertools, copy, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from ext import uai as U
from bench import cbi_adapter as AD
from cbi import api


def write_uai(path, card, factors, ev):
    """factors: list of (scope, table) with UAI last-variable-fastest tables."""
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(factors))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in factors] + [""]
    for _, t in factors:
        lines += [str(len(t)), " ".join(str(x) for x in t), ""]
    open(path, "w").write("\n".join(lines)); open(path + ".evid", "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % kv for kv in ev.items())))


def brute(path):
    m = U.read_model(path); ev = U.read_evidence(path + ".evid"); Z = Fr(0); num = {v: [Fr(0)] * m.card[v] for v in range(m.nvars)}
    for a in itertools.product(*[range(c) for c in m.card]):
        if any(a[v] != s for v, s in ev.items()):
            continue
        w = Fr(1)
        for f in m.factors:
            w *= f.at({v: a[v] for v in f.scope})
        Z += w
        for v in range(m.nvars):
            num[v][a[v]] += w
    return (Z, {v: [x / Z for x in num[v]] for v in num}) if Z else (Z, None)


# attractive (0,1); REPULSIVE (1,2) and (0,2) (consistent flips: f0 = f1 = 0, f2 = 1); equality (2,3); attractive (3,4) with unequal gauges
ADMISSIBLE = ([2, 2, 2, 2, 2],
              [((0,), ["0.3", "0.7"]), ((0, 1), ["2", "1", "1", "2"]), ((1, 2), ["3", "24", "1", "2"]), ((0, 2), ["1", "2", "2", "1"]), ((2, 3), ["5", "0", "0", "7"]), ((3, 4), ["0.5", "0.125", "1", "1"]), ((4,), ["1", "3"])],
              {4: 1})


def _contract(path):
    """the invocation contract of the primary task: every unobserved original variable"""
    mm = U.read_model(path); e = U.read_evidence(path + ".evid"); return [v for v in range(mm.nvars) if v not in e]


def solve_native(path, width="1/100"):
    m = U.read_model(path); ev = U.read_evidence(path + ".evid"); out = AD.adapt(m, ev)
    assert out[0] != "INFEASIBLE", out
    native, cert = out; res = api.solve(native, "all", width, {}); assert res["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE"), res.get("reason")
    assert api.verify(native, res)["accepted"]; AD.check_adapter(path, path + ".evid", native, cert, res, expected_queries=_contract(path))
    return m, ev, native, cert, res, AD.map_intervals(m, ev, cert, res)


def test_adapter_admits_mixed_binary_model_and_intervals_contain_brute_force(tmp_path):
    p = str(tmp_path / "m.uai"); write_uai(p, *ADMISSIBLE); m, ev, native, cert, res, rows = solve_native(p)
    Z, tr = brute(p); kinds = sorted(i["kind"] for i in cert["identities"])
    assert kinds == ["coupling", "coupling", "coupling", "equality"] and cert["flip"]["2"] != cert["flip"]["0"] and cert["flip"]["2"] == cert["flip"]["3"]   # (3,4) is sliced by the evidence
    for v in range(m.nvars):
        for s in range(2):
            lo, hi = rows[v][s]; assert lo <= tr[v][s] <= hi, (v, s, float(lo), float(tr[v][s]), float(hi))
    assert all(rows[v][s] == [Fr(1 if s == ev[v] else 0)] * 2 for v in ev for s in range(2))


def test_source_order_and_state_order_permutations_give_identical_marginals(tmp_path):
    card, facs, ev = ADMISSIBLE; p = str(tmp_path / "a.uai"); write_uai(p, card, facs, ev); _, _, _, _, _, rows = solve_native(p)
    # factor order reversed, scopes written in the other orientation (table transposed accordingly)
    facs2 = []
    for sc, t in reversed(facs):
        if len(sc) == 2:
            facs2.append(((sc[1], sc[0]), [t[0], t[2], t[1], t[3]]))
        else:
            facs2.append((sc, t))
    q = str(tmp_path / "b.uai"); write_uai(q, card, facs2, ev); _, _, _, _, _, rows2 = solve_native(q)
    assert rows2 == rows
    # state order of variable 1 flipped in the source (tables and evidence relabelled): marginal of variable 1 flips, others unchanged
    def flip_var(sc, t, v):
        if v not in sc:
            return sc, t
        k = sc.index(v); out = list(t)
        for conf in itertools.product(range(2), repeat=len(sc)):
            c2 = list(conf); c2[k] ^= 1; idx = lambda c: sum(c[i] * (2 ** (len(sc) - 1 - i)) for i in range(len(sc)))
            out[idx(conf)] = t[idx(c2)]
        return sc, out
    facs3 = [flip_var(sc, t, 1) for sc, t in facs]; r = str(tmp_path / "c.uai"); write_uai(r, card, facs3, ev); _, _, _, _, _, rows3 = solve_native(r)
    assert rows3[1] == rows[1][::-1] and all(rows3[v] == rows[v] for v in range(5) if v != 1)


def test_evidence_indexing_zero_factors_impossible_evidence_and_disconnected(tmp_path):
    card, facs, _ = ADMISSIBLE
    # evidence on a middle variable; a zero in a unary fixes a variable; an impossible evidence
    p = str(tmp_path / "e.uai"); write_uai(p, card, facs + [((1,), ["0", "1"])], {2: 0}); m, ev, native, cert, res, rows = solve_native(p); Z, tr = brute(p)
    assert cert["fixed"] == {"2": 0, "1": 1, "3": 0} and all(rows[v][s][0] <= tr[v][s] <= rows[v][s][1] for v in range(5) for s in range(2))
    q = str(tmp_path / "z.uai"); write_uai(q, card, facs, {2: 1, 3: 0})            # equality factor diag(5,7) forbids 2 != 3
    m = U.read_model(q); out = AD.adapt(m, U.read_evidence(q + ".evid")); assert out[0] == "INFEASIBLE" and "zero" in out[1]["reason"]
    # disconnected: an isolated variable with only a unary, plus a separate pair; all queried
    d = str(tmp_path / "d.uai"); write_uai(d, [2, 2, 2], [((0,), ["1", "3"]), ((1, 2), ["2", "1", "1", "2"]), ((2,), ["0.25", "0.75"])], {}); m, ev, native, cert, res, rows = solve_native(d); Z, tr = brute(d)
    assert all(rows[v][s][0] <= tr[v][s] <= rows[v][s][1] for v in range(3) for s in range(2))
    assert rows[0][1][0] <= Fr(3, 4) <= rows[0][1][1] and rows[0][1][1] - rows[0][1][0] <= Fr(1, 1 << 78)        # isolated variable: exact up to publication slack


def test_adapter_refusals_are_precise(tmp_path):
    # frustrated triangle: two attractive edges and one repulsive
    p = str(tmp_path / "f.uai"); write_uai(p, [2, 2, 2], [((0, 1), ["2", "1", "1", "2"]), ((1, 2), ["2", "1", "1", "2"]), ((0, 2), ["1", "2", "2", "1"])], {})
    with pytest.raises(AD.Unsupported, match="inconsistent sign gauges"):
        AD.adapt(U.read_model(p), {})
    # nonsquare cross-ratio
    q = str(tmp_path / "n.uai"); write_uai(q, [2, 2], [((0, 1), ["3", "1", "1", "1"])], {})
    with pytest.raises(AD.Unsupported, match="nonsquare rational cross-ratio"):
        AD.adapt(U.read_model(q), {})
    # zero pattern other than diagonal
    z = str(tmp_path / "zp.uai"); write_uai(z, [2, 2], [((0, 1), ["1", "0", "1", "1"])], {})
    with pytest.raises(AD.Unsupported, match="incompatible zero pattern"):
        AD.adapt(U.read_model(z), {})
    # nonbinary and arity 3
    t = str(tmp_path / "t.uai"); write_uai(t, [2, 3], [((0, 1), ["1", "1", "1", "1", "1", "1"])], {})
    with pytest.raises(AD.Unsupported, match="nonbinary"):
        AD.adapt(U.read_model(t), {})
    a = str(tmp_path / "a3.uai"); write_uai(a, [2, 2, 2], [((0, 1, 2), ["1"] * 8)], {})
    with pytest.raises(AD.Unsupported, match="high arity"):
        AD.adapt(U.read_model(a), {})
    # ... but the same arity-3 factor sliced by evidence to a pair IS admitted
    b = str(tmp_path / "a3e.uai"); write_uai(b, [2, 2, 2], [((0, 1, 2), ["2", "1", "1", "2", "1", "2", "2", "1"])], {2: 0}); solve_native(b)


def test_reference_pointer_and_certificate_tampering_rejected(tmp_path):
    p = str(tmp_path / "m.uai"); write_uai(p, *ADMISSIBLE); m, ev, native, cert, res, rows = solve_native(p)
    bad = copy.deepcopy(cert); bad["identities"][0]["factors"] = [bad["identities"][0]["factors"][0]] + [99]           # points at a nonexistent factor
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", native, bad, res, expected_queries=_contract(p))
    bad = copy.deepcopy(cert); bad["flip"] = {k: 1 - v for k, v in bad["flip"].items()}                              # wrong bijection
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", native, bad, res, expected_queries=_contract(p))
    bad = copy.deepcopy(native); bad["blocks"][0]["weights"] = [7, 1]                                                  # weights not the gauge product
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", bad, cert, res, expected_queries=_contract(p))
    bad = copy.deepcopy(native); bad["edges"][0]["r"] = str(Fr(bad["edges"][0]["r"]) + Fr(1, 1000))                    # coupling changed
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", bad, cert, res, expected_queries=_contract(p))
    # a different model file behind the same certificate (reference-pointer swap)
    q = str(tmp_path / "other.uai"); card, facs, e = ADMISSIBLE; write_uai(q, card, [facs[0]] + [((0, 1), ["3", "1", "1", "3"])] + facs[2:], e)
    with pytest.raises(AssertionError):
        AD.check_adapter(q, q + ".evid", native, cert, res, expected_queries=_contract(q))


def test_cell_runner_output_validation_rejects_bad_vectors(tmp_path):
    from bench import cells as CE
    p = str(tmp_path / "x.MAR"); open(p, "w").write("MAR\n2 2 0.3 0.7 3 0.2 0.2 0.2\n")
    rows, faults = CE.validate_mar(p, [2, 3], {}); assert rows is None and any("row sum" in f for f in faults)
    open(p, "w").write("MAR\n2 2 0.3 0.7 3 0.2 0.3 0.5\n"); rows, faults = CE.validate_mar(p, [2, 3], {1: 2}); assert rows is None and any("point mass" in f for f in faults)
    rows, faults = CE.validate_mar(p, [2, 3], {}); assert rows is not None and faults == []


# ------------------------------------------------------------- review of the external sweep (7 Nov 2026): adapter checker must PROVE, not trust
def _xy(tmp_path, ev=None, unaries=(("1", "3"), ("1", "3"))):
    p = str(tmp_path / "xy.uai"); write_uai(p, [2, 2], [((0,), list(unaries[0])), ((1,), list(unaries[1]))], ev or {}); return p


def test_checker_rejects_added_native_edge_and_invented_fixation(tmp_path):
    """The reviewer's two witnesses: X, Y independent, unaries [1,3], P = 3/4."""
    p = _xy(tmp_path); m = U.read_model(p); ev = {}; native, cert = AD.adapt(m, ev)
    bad = copy.deepcopy(native); bad["edges"].append({"u": 0, "v": 1, "r": "1/2"}); res = api.solve(bad, "all", "1/100", {})
    with pytest.raises(AssertionError, match="native edge set"):
        AD.check_adapter(p, p + ".evid", bad, cert, res, expected_queries=_contract(p))
    cert2 = copy.deepcopy(cert); cert2["fixed"] = {"0": 0}; cert2["free"] = [1]; cert2["flip"] = {"1": 0}; cert2["consumed"] = [c for c in cert2["consumed"] if c.get("var") != 0] + [{"factor": 0, "role": "constant", "value": "1", "fixed_at": {"0": 0}}]
    nat2 = {"d": 1, "bit_convention": native["bit_convention"], "blocks": [b for b in native["blocks"] if b["id"] == 1], "edges": [], "meta": native["meta"]}; res2 = api.solve(nat2, "all", "1/100", {})
    with pytest.raises(AssertionError, match="independently proved fixed set"):
        AD.check_adapter(p, p + ".evid", nat2, cert2, res2, expected_queries=_contract(p))
    # the honest conversion still passes, and the published intervals contain 3/4
    AD.check_adapter(p, p + ".evid", native, cert, api.solve(native, "all", "1/100", {}), expected_queries=_contract(p)); rows = AD.map_intervals(m, ev, cert, api.solve(native, "all", "1/100", {}))
    assert rows[0][1][0] <= Fr(3, 4) <= rows[0][1][1]


def test_checker_structural_rejections(tmp_path):
    p = str(tmp_path / "m.uai"); write_uai(p, *ADMISSIBLE); m = U.read_model(p); ev = U.read_evidence(p + ".evid"); native, cert = AD.adapt(m, ev); res = api.solve(native, "all", "1/100", {})
    def bad(mut, match):
        n2, c2 = copy.deepcopy(native), copy.deepcopy(cert); mut(n2, c2)
        with pytest.raises(AssertionError, match=match):
            AD.check_adapter(p, p + ".evid", n2, c2, res, expected_queries=_contract(p))
    bad(lambda n, c: n["edges"].append(dict(n["edges"][0])), "duplicate native edge")                                   # duplicate edge occurrence
    bad(lambda n, c: n["edges"].append({"u": n["edges"][0]["u"], "v": n["edges"][0]["u"], "r": "1/3"}), "invalid endpoints")   # self-loop
    bad(lambda n, c: n["blocks"].append(dict(n["blocks"][0])), "duplicates or mismatch")                                  # duplicate block
    bad(lambda n, c: n["blocks"][0].__setitem__("rows", [0, 2]), "rows")                                                   # state out of {0,1}
    bad(lambda n, c: c["flip"].__setitem__(str(c["free"][0]), 2), "flip of variable|flip map")                                              # flip not a bit
    bad(lambda n, c: n["edges"].pop(), "native edge set")                                                                  # missing interaction
    bad(lambda n, c: c["identities"].append(dict(c["identities"][0])), "covered exactly once|distinct ordered pairs")      # duplicated identity (caught by occurrence count or scope uniqueness)
    bad(lambda n, c: c["identities"][0]["factors"].append(c["identities"][0]["factors"][0]), "covered exactly once")        # duplicated factor occurrence
    bad(lambda n, c: c["fixed"].__setitem__("0", 1), "independently proved fixed set")                                    # invented fixation on a free var
    # result binding: a result for a different query set is rejected
    res2 = api.solve(native, [native["blocks"][0]["id"]], "1/100", {})
    with pytest.raises(AssertionError, match="requested set"):
        AD.check_adapter(p, p + ".evid", native, cert, res2, expected_queries=_contract(p))


def test_checker_honest_controls_evidence_forced_separable_duplicates_signed_ids(tmp_path):
    """Honest conversions that MUST pass: evidence; a truly forced state (unary zero); a separable pair; duplicate source factor occurrences on
    one scope; a correctly transformed (flipped) query; and the checker's own forced-state proof agrees with brute force."""
    card, facs, _ = ADMISSIBLE
    # evidence + a forced state + duplicate occurrences of the same scope
    p = str(tmp_path / "h.uai"); write_uai(p, card, facs + [((1,), ["0", "1"]), ((0, 1), ["1", "1", "1", "1"])], {2: 0})
    m = U.read_model(p); ev = U.read_evidence(p + ".evid"); native, cert = AD.adapt(m, ev); res = api.solve(native, "all", "1/100", {})
    chk = AD.check_adapter(p, p + ".evid", native, cert, res, expected_queries=_contract(p)); assert chk["forced_states_proved"] >= 1 and chk["query_map_checked"]
    proved, zw = AD.prove_forced(m, ev); assert zw is None and proved == {int(k): v for k, v in cert["fixed"].items()}
    Z, tr = brute(p); rows = AD.map_intervals(m, ev, cert, res); assert all(rows[v][s][0] <= tr[v][s] <= rows[v][s][1] for v in range(5) for s in range(2))
    # separable pair (cross-ratio 1) absorbed as unaries; no edge
    q = str(tmp_path / "s.uai"); write_uai(q, [2, 2], [((0, 1), ["1", "2", "3", "6"]), ((1,), ["1", "1"])], {}); m = U.read_model(q); native, cert = AD.adapt(m, {}); res = api.solve(native, "all", "1/100", {})
    assert native["edges"] == [] and cert["identities"][0]["kind"] == "separable"; AD.check_adapter(q, q + ".evid", native, cert, res, expected_queries=_contract(q))
    # impossible evidence is proved as Z = 0 by the checker's own replay
    z = str(tmp_path / "z.uai"); write_uai(z, [2, 2], [((0,), ["1", "0"]), ((1,), ["1", "1"])], {0: 1}); m = U.read_model(z)
    out = AD.adapt(m, U.read_evidence(z + ".evid")); assert out[0] == "INFEASIBLE"; _, zw = AD.prove_forced(m, U.read_evidence(z + ".evid")); assert zw is not None


def test_rooted_proof_valid_for_aliased_queries_after_equality_contraction():
    """Reviewer's false rejection: two d = 1 blocks [0,1] with weights [1,1] and [1,3], equality edge; both original queries map to one reduced
    node and both marginals are 3/4; the rooted CERTIFIED result must be ACCEPTED; a request for two DISTINCT reduced nodes must still be rejected."""
    obj = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 1], "weights": [1, 3]}], "edges": [{"u": 0, "v": 1, "r": "1"}]}
    res = api.solve(obj, "all", "1/100", {}); assert res["status"] == "CERTIFIED"
    for q in ("0", "1"):
        c = res["intervals"][q]["coordinates"][0]; assert Fr(int(c["lo"]), 1 << 80) <= Fr(3, 4) <= Fr(int(c["hi"]), 1 << 80)
    ver = api.verify(obj, res); assert ver["accepted"], ver["reasons"][-2:]
    assert res["proofs"][res["certificate"]["0"]["proof"]]["kind"] in ("forest_rooted", "forest_batched")
    # distinct reduced nodes under one rooted proof: rejected
    obj2 = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 1]}, {"id": 1, "rows": [0, 1], "weights": [1, 3]}, {"id": 2, "rows": [0, 1], "weights": [2, 1]}], "edges": [{"u": 0, "v": 1, "r": "1"}, {"u": 1, "v": 2, "r": "1/3"}]}
    r1 = api.solve(obj2, [0], "1/100", {}); assert r1["proofs"][r1["certificate"]["0"]["proof"]]["kind"] == "forest_rooted" and api.verify(obj2, r1)["accepted"]
    tam = json.loads(json.dumps(r1, default=str)); tam["requested_queries"] = [0, 2]; tam["statuses_per_query"]["2"] = "CERTIFIED"; tam["intervals"]["2"] = tam["intervals"]["0"]; tam["certificate"]["2"] = dict(tam["certificate"]["0"], node=2)
    assert not api.verify(obj2, tam)["accepted"]


def test_paid_attempt_preserved_when_timeout_follows_a_paid_candidate():
    """Deterministic: a too-wide degree-0 approximate candidate is paid, then the deadline fires during the exact candidate. Both attempts
    must remain in the record (the approximate one with its paid_s), followed by the terminal resource row."""
    from cbi import plan as PL, generators as G
    obj = G.chain(4, 12, 64, [Fr(1, 2)], 5, "c4"); orig_op = PL.prospective_op; orig_dl = PL.Planner.deadline; state = {"n": 0}
    PL.prospective_op = lambda e, mu, mv, eps_edge, limits, surrogate_allowed=False: (("fourier", 0), {})
    def dl(self):
        # polls during the approximate candidate pass; the first poll AFTER the approximate attempt has been recorded (start of the exact
        # candidate) times out
        if any(a.get("candidate") == "approximate" and "met" in a for at in self.partial_attempts.values() for a in at):
            raise PL.TimeLimit("injected timeout")
    PL.Planner.deadline = dl
    try:
        res = api.solve(obj, "all", "1/1000000", {"degrees": [0]})
    finally:
        PL.prospective_op = orig_op; PL.Planner.deadline = orig_dl
    att = res["plan"]["queries"]["0"]["trials"][0]["attempts"]; cands = [a for a in att if a.get("candidate")]
    assert cands and cands[0]["candidate"] == "approximate" and cands[0]["met"] is False and cands[0]["paid_s"] > 0
    assert any(a.get("candidate") == "exact" and a.get("status") == "RESOURCE_LIMIT" for a in cands) or att[-1]["status"] == "RESOURCE_LIMIT"
    assert res["statuses_per_query"]["0"] == "RESOURCE_LIMIT"


def test_libdai_driver_zero_evidence_witness():
    """Observed X = 1 with unary [1,0] and a free Y: the sliced constant is ZERO (Z = 0); the driver must refuse (exit 5) instead of printing an
    ordinary Y marginal; positive sliced constants still pass."""
    import subprocess
    drv = os.path.join(HERE, "bench", "libdai", "libdai_mar"); C = os.path.join(HERE, "bench", "controls")
    if not os.path.exists(drv):
        pytest.skip("libDAI driver not built")
    r = subprocess.run([drv, os.path.join(C, "impossible_evidence.uai"), os.path.join(C, "impossible_evidence.uai.evid"), "/tmp/_ie.MAR", "/tmp/_ie.json", "JTREE[inference=SUMPROD,updates=HUGIN]"], capture_output=True, text=True)
    assert r.returncode == 5 and json.load(open("/tmp/_ie.json"))["status"] == "ZERO_PARTITION"
    r2 = subprocess.run([drv, os.path.join(C, "tiny_asym.uai"), os.path.join(C, "tiny_asym.uai.evid"), "/tmp/_ta.MAR", "/tmp/_ta.json", "JTREE[inference=SUMPROD,updates=HUGIN]"], capture_output=True, text=True)
    assert r2.returncode == 0 and open("/tmp/_ta.MAR").read().startswith("MAR")


# ------------------------------------------------------------- review of the r2 package (7 Nov 2026): canonical fixed states, contract binding, harness identity
def test_fixed_state_value_variants_one_interpretation(tmp_path):
    """X with unary [0,1] is FORCED to state 1 (P(X=1) = 1); Y [1,3]. The honest integer certificate passes; string / float / fraction / bool /
    out-of-range / wrong-state variants are rejected by the checker AND refused by the publication mapper (one canonical interpretation)."""
    p = str(tmp_path / "f.uai"); write_uai(p, [2, 2], [((0,), ["0", "1"]), ((1,), ["1", "3"])], {})
    m = U.read_model(p); native, cert = AD.adapt(m, {}); res = api.solve(native, "all", "1/100", {}); contract = [0, 1]
    assert cert["fixed"] == {"0": 1}
    AD.check_adapter(p, p + ".evid", native, cert, res, expected_queries=contract); rows = AD.map_intervals(m, {}, cert, res); assert rows[0] == [[Fr(0), Fr(0)], [Fr(1), Fr(1)]]
    for bad in ("1", 1.0, "1/1", True, 2, -1, "0", 0):
        c2 = copy.deepcopy(cert); c2["fixed"]["0"] = bad
        with pytest.raises(AssertionError):
            AD.check_adapter(p, p + ".evid", native, c2, res, expected_queries=contract)
        if bad != 0:
            with pytest.raises(AD.BadCertificate):
                AD.map_intervals(m, {}, c2, res)
    # the two original exploits still rejected under the contract interface
    q = str(tmp_path / "xy.uai"); write_uai(q, [2, 2], [((0,), ["1", "3"]), ((1,), ["1", "3"])], {}); m2 = U.read_model(q); n2, c2 = AD.adapt(m2, {})
    bad = copy.deepcopy(n2); bad["edges"].append({"u": 0, "v": 1, "r": "1/2"})
    with pytest.raises(AssertionError, match="native edge set"):
        AD.check_adapter(q, q + ".evid", bad, c2, api.solve(bad, "all", "1/100", {}), expected_queries=[0, 1])
    c3 = copy.deepcopy(c2); c3["fixed"] = {"0": 0}; c3["free"] = [1]; c3["flip"] = {"1": 0}; c3["consumed"] = [c for c in c3["consumed"] if c.get("var") != 0] + [{"factor": 0, "role": "constant", "value": "1", "fixed_at": {"0": 0}}]
    n3 = {"d": 1, "bit_convention": n2["bit_convention"], "blocks": [b for b in n2["blocks"] if b["id"] == 1], "edges": [], "meta": n2["meta"]}
    with pytest.raises(AssertionError, match="proved fixed set"):
        AD.check_adapter(q, q + ".evid", n3, c3, api.solve(n3, "all", "1/100", {}), expected_queries=[0, 1])


def test_contract_binding_subset_and_mismatch(tmp_path):
    """The caller binds the expected query set: a prescribed single query is accepted when the native result was requested for exactly it; a
    native result for a different set (producer choosing the task) is rejected; a contract naming a proved-fixed variable validates its point row."""
    p = str(tmp_path / "m.uai"); write_uai(p, *ADMISSIBLE); m = U.read_model(p); ev = U.read_evidence(p + ".evid"); native, cert = AD.adapt(m, ev)
    free = list(cert["free"]); v = free[1]
    r1 = api.solve(native, [v], "1/100", {}); AD.check_adapter(p, p + ".evid", native, cert, r1, expected_queries=[v])
    with pytest.raises(AssertionError, match="requested set"):
        AD.check_adapter(p, p + ".evid", native, cert, r1, expected_queries=free)                 # contract = all, result = one
    rall = api.solve(native, "all", "1/100", {})
    with pytest.raises(AssertionError, match="requested set"):
        AD.check_adapter(p, p + ".evid", native, cert, rall, expected_queries=[v])                # contract = one, result = all
    with pytest.raises(AssertionError, match="caller must supply"):
        AD.check_adapter(p, p + ".evid", native, cert, rall)
    # a forced variable in the contract: its published row must be the point mass at the PROVED state
    q = str(tmp_path / "f.uai"); write_uai(q, [2, 2], [((0,), ["0", "1"]), ((1,), ["1", "3"])], {}); m2 = U.read_model(q); n2, c2 = AD.adapt(m2, {}); r2 = api.solve(n2, "all", "1/100", {})
    out = AD.check_adapter(q, q + ".evid", n2, c2, r2, expected_queries=[0, 1]); assert out["contract_queries"] == 2 and out["contract_queries_native"] == 1

