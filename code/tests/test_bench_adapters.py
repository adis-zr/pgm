"""Controls for the external-sweep adapters (campaign spec section 2, last paragraph): native-CBI adapter + independent checker, BIF->UAI,
cell runner output validation. Source-order / state-order permutations, evidence indexing, zero factors, impossible evidence, disconnected
models, reference-pointer tampering."""
import os, sys, json, itertools, copy, tempfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
import pytest
from ext import uai as U
from bench import cbi_adapter as AD, bif as BIF
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


def solve_native(path, width="1/100"):
    m = U.read_model(path); ev = U.read_evidence(path + ".evid"); out = AD.adapt(m, ev)
    assert out[0] != "INFEASIBLE", out
    native, cert = out; res = api.solve(native, "all", width, {}); assert res["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE"), res.get("reason")
    assert api.verify(native, res)["accepted"]; AD.check_adapter(path, path + ".evid", native, cert, res)
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
        AD.check_adapter(p, p + ".evid", native, bad, res)
    bad = copy.deepcopy(cert); bad["flip"] = {k: 1 - v for k, v in bad["flip"].items()}                              # wrong bijection
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", native, bad, res)
    bad = copy.deepcopy(native); bad["blocks"][0]["weights"] = [7, 1]                                                  # weights not the gauge product
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", bad, cert, res)
    bad = copy.deepcopy(native); bad["edges"][0]["r"] = str(Fr(bad["edges"][0]["r"]) + Fr(1, 1000))                    # coupling changed
    with pytest.raises(AssertionError):
        AD.check_adapter(p, p + ".evid", bad, cert, res)
    # a different model file behind the same certificate (reference-pointer swap)
    q = str(tmp_path / "other.uai"); card, facs, e = ADMISSIBLE; write_uai(q, card, [facs[0]] + [((0, 1), ["3", "1", "1", "3"])] + facs[2:], e)
    with pytest.raises(AssertionError):
        AD.check_adapter(q, q + ".evid", native, cert, res)


def test_bif_conversion_roundtrip_and_verification_detects_axis_swap(tmp_path):
    bif = tmp_path / "t.bif"; bif.write_text("""network t {}
variable A { type discrete [ 2 ] { a0, a1 }; }
variable B { type discrete [ 3 ] { b0, b1, b2 }; }
variable C { type discrete [ 2 ] { c0, c1 }; }
probability ( A ) { table 0.2, 0.8; }
probability ( B | A ) { (a0) 0.1, 0.2, 0.7; (a1) 0.5, 0.25, 0.25; }
probability ( C | B, A ) { (b0, a0) 0.9, 0.1; (b1, a0) 0.8, 0.2; (b2, a0) 0.7, 0.3; (b0, a1) 0.6, 0.4; (b1, a1) 0.5, 0.5; (b2, a1) 0.4, 0.6; }
""")
    text, rec = BIF.bif_to_uai(str(bif)); chk = BIF.verify_bif_uai(str(bif), text); assert chk["entries_checked"] == 2 + 6 + 12 and rec["row_sum_defects"] == []
    m = U.read_model.__wrapped__(text) if hasattr(U.read_model, "__wrapped__") else None
    p = tmp_path / "t.uai"; p.write_text(text); m = U.read_model(str(p)); f = m.factors[2]; assert f.scope == (1, 0, 2) and f.at({1: 2, 0: 1, 2: 0}) == Fr("0.4")
    # swapping the two parent axes in the written table must be caught by the independent verifier
    toks = text.split(); i = toks.index("12"); vals = toks[i + 1:i + 13]
    # table order (B,A,C) -> reorder as (A,B,C): detectably different
    sw = [vals[(b * 2 + a) * 2 + c] for a in range(2) for b in range(3) for c in range(2)]; toks[i + 1:i + 13] = sw
    with pytest.raises(AssertionError):
        BIF.verify_bif_uai(str(bif), " ".join(toks))
    # exact decimals survive: 0.7 stays 0.7 (no binary float)
    assert "0.7" in text and "0.69999" not in text


def test_cell_runner_output_validation_rejects_bad_vectors(tmp_path):
    from bench import cells as CE
    p = str(tmp_path / "x.MAR"); open(p, "w").write("MAR\n2 2 0.3 0.7 3 0.2 0.2 0.2\n")
    rows, faults = CE.validate_mar(p, [2, 3], {}); assert rows is None and any("row sum" in f for f in faults)
    open(p, "w").write("MAR\n2 2 0.3 0.7 3 0.2 0.3 0.5\n"); rows, faults = CE.validate_mar(p, [2, 3], {1: 2}); assert rows is None and any("point mass" in f for f in faults)
    rows, faults = CE.validate_mar(p, [2, 3], {}); assert rows is not None and faults == []
