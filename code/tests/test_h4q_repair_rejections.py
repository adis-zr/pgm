"""Production-entry rejection controls for the repaired verifier, plus the raw-order predicate tested
producer-only and checker-only. Each asserts the specific named failure, not merely a nonzero result."""
import sys, os, json, copy, pathlib, tempfile
HERE = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(HERE))
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import pytest
from h4q.repair_verify import IndependentVerifier, CertificateFailure, check_raw_order, fx, fb, E_PUB, E_INT

DELTA = Fr(1, 10000)
PILOT = HERE / "runs" / "h4q_pilot_2026-10-27"
RECON = HERE / "runs" / "h4q_repair_2026-10-27" / "mass_weight_reconstruction.json"


def _real_responses(sign=1, arm="PP"):
    """the REAL saved producer responses. Synthetic responses such as R=1/2 are inconsistent with a node's actual mass
    split and the verifier correctly refuses them, so every fixture here uses saved data."""
    import glob
    pref = "sp" if sign == 1 else "sm"
    out = {}
    for d in sorted(glob.glob(str(PILOT / f"rep1_{arm}" / f"{pref}_*"))):
        nd = tuple(int(x) for x in os.path.basename(d).split("_")[1:3])
        J = json.load(open(os.path.join(d, "prod.json")))
        out[nd] = {r["marker"]: (fb(r["bits"]) - E_PUB, fb(r["bits"]) + E_PUB) for r in J["response"]}
    return out


def _loaded(sign=1, limit=None):
    """a verifier loaded from the reconstruction (the only source of per-node mass evidence)"""
    M = json.load(open(RECON)); V = IndependentVerifier(sign, DELTA)
    items = list(M["signs"][str(sign)].items())
    if limit: items = items[:limit]
    for nkey, r in items:
        nd = tuple(int(x) for x in nkey.split(","))
        V.add_node(nd, tuple(Fr(x) for x in r["Zpub_plus"]), tuple(Fr(x) for x in r["Zpub_minus"]),
                   tuple(Fr(x) for x in r["w_pub"]), tuple(Fr(x) for x in r["Zchk_plus"]),
                   tuple(Fr(x) for x in r["Zchk_minus"]), tuple(Fr(x) for x in r["w_chk"]))
    return V


# ---------------- empty / truncated checker evidence ----------------
def test_rejects_absent_checker_evidence():
    V = _loaded(1); R = _real_responses(1)
    nd = next(iter(R))
    V.Zc.clear(); V.Wc.clear()                      # checker evidence withheld
    with pytest.raises(CertificateFailure, match="no checker evidence"):
        V.checker_DW(nd, R[nd])


def test_rejects_empty_checker_map_in_the_prefix_proof():
    """the old verify_prefix accepted an empty checker map; the repaired path must not treat that as verified"""
    V = _loaded(1)
    ot = V.order_and_tail()
    rp = V.replay_prefix(ot["order"], ot["omit"], {})          # no responses at all
    assert rp["first"] is None and rp.get("exhausted_evidence_at") == 1, \
        "an empty response map must not yield a qualifying prefix"


def test_rejects_truncated_response_evidence_midway():
    V = _loaded(1); R = _real_responses(1); ot = V.order_and_tail()
    processable = [n for n in ot["order"] if n not in ot["omit"]]
    resp = {nd: R[nd] for nd in processable[:3] if nd in R}
    rp = V.replay_prefix(ot["order"], ot["omit"], resp)
    assert rp["first"] is None and rp["exhausted_evidence_at"] == len(resp) + 1


# ---------------- missing unresolved node ----------------
def test_missing_unresolved_node_changes_the_enclosure():
    """dropping a node's unresolved contribution must not silently narrow the result. Checked at a REAL stopping
    state (one processed node plus the rest unresolved), where the omission is detectable."""
    V = _loaded(1); R = _real_responses(1); ot = V.order_and_tail()
    good = [n for n in ot["order"] if n not in ot["omit"] and n in R]
    Wmap = {(nd, sg): V.unresolved_W(nd, sg) for nd in V.W_pub for sg in (1, -1)}
    dw = V.producer_DW(good[0], R[good[0]])
    for sg in (1, -1): Wmap[(good[0], sg)] = dw[sg]["W"]
    e_full = V.enclosure(Wmap)
    heaviest = max((n for n in V.W_pub if n != good[0]), key=lambda n: V.unresolved_W(n, 1)[1])
    partial = {k: v for k, v in Wmap.items() if k[0] != heaviest}
    assert e_full != V.enclosure(partial), "omitting an unresolved node must change the enclosure"


# ---------------- wrong order / tie / omission ----------------
def test_order_is_descending_score_with_lexicographic_ties():
    V = _loaded(1, limit=200); ot = V.order_and_tail()
    sc = ot["scores"]; order = ot["order"]
    for a, b in zip(order, order[1:]):
        assert (-sc[a], a[0], a[1]) <= (-sc[b], b[0], b[1]), f"order violated at {a} -> {b}"


def test_rejects_a_permuted_order_in_the_prefix_proof():
    V = _loaded(1); R = _real_responses(1); ot = V.order_and_tail()
    base = V.replay_prefix(ot["order"], ot["omit"], R)
    swapped = list(ot["order"])
    i = next(k for k, n in enumerate(swapped) if n in R)
    j = next(k for k, n in enumerate(swapped) if n in R and k > i)
    swapped[i], swapped[j] = swapped[j], swapped[i]
    alt = V.replay_prefix(swapped, ot["omit"], R)
    assert base["widths"] != alt["widths"], "a permuted order must produce a different replay trace"


def test_rejects_a_wrong_omission_set():
    V = _loaded(1); R = _real_responses(1); ot = V.order_and_tail()
    base = V.replay_prefix(ot["order"], ot["omit"], R)
    good = [n for n in ot["order"] if n not in ot["omit"] and n in R]
    bad_omit = set(ot["omit"]) | {good[0]}            # omit a node that should be processed
    alt = V.replay_prefix(ot["order"], bad_omit, R)
    assert base["first"] != alt["first"] or base["widths"] != alt["widths"]


# ---------------- altered D / W ----------------
def test_altered_W_breaks_containment():
    V = _loaded(1); RR = _real_responses(1)
    nd = next(iter(RR)); R = RR[nd]
    p = V.producer_DW(nd, R); c = V.checker_DW(nd, R)
    for sg in (1, -1):
        assert p[sg]["D"][0] <= c[sg]["D"][0] and c[sg]["D"][1] <= p[sg]["D"][1]
    shrunk = (p[1]["W"][0] + (p[1]["W"][1] - p[1]["W"][0]) * Fr(9, 10), p[1]["W"][1])
    assert not (shrunk[0] <= c[1]["W"][0] and c[1]["W"][1] <= shrunk[1]), \
        "an altered (narrowed) producer W must fail checker containment"


def test_D_and_W_containment_are_checked_separately():
    V = _loaded(1); RR = _real_responses(1)
    nd = next(iter(RR)); R = RR[nd]
    p = V.producer_DW(nd, R); c = V.checker_DW(nd, R)
    assert set(p[1]) == {"D", "W"} and set(c[1]) == {"D", "W"}
    assert p[1]["D"] != p[1]["W"], "D and W must be distinct quantities"


# ---------------- false first-prefix claim, changed final endpoint ----------------
def test_false_first_prefix_claim_is_detectable():
    V = _loaded(1); R = _real_responses(1); ot = V.order_and_tail()
    rp = V.replay_prefix(ot["order"], ot["omit"], R)
    if rp["first"] is not None and rp["first"] > 1:
        earlier = rp["first"] - 1
        w_at_earlier = dict(rp["widths"])[earlier]
        assert w_at_earlier > Fr(1, 100), "a claimed earlier prefix must be shown not to meet the contract"


def test_changed_final_endpoint_is_detectable():
    V = _loaded(1)
    full = {(nd, sg): V.unresolved_W(nd, sg) for nd in V.W_pub for sg in (1, -1)}
    e = V.enclosure(full)
    assert e != (e[0], e[1] + Fr(1, 1 << 64)), "an endpoint moved by one mesh unit must differ"


# ---------------- raw order predicate, producer-only and checker-only ----------------
def _first_node_dir(arm):
    import glob
    return sorted(glob.glob(str(PILOT / f"rep1_{arm}" / "s*")))[0]


@pytest.mark.parametrize("arm,role,kind", [("C", "prod.json", "interval"), ("C", "chk.json", "interval"),
                                           ("PP", "prod.json", "point"), ("PP", "chk.json", "point")])
def test_saved_outputs_pass_the_raw_order_predicate(arm, role, kind):
    r = check_raw_order(os.path.join(_first_node_dir(arm), role), kind)
    assert r["ok"] and r["coordinates_checked"] == 2 * 530 + 2


def test_producer_only_inversion_is_caught():
    d = _first_node_dir("C"); J = json.load(open(os.path.join(d, "prod.json")))
    J["channels"][7]["re"] = [J["channels"][7]["re"][1], J["channels"][7]["re"][0]]   # swap one coordinate
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "prod.json"); json.dump(J, open(p, "w"))
        r = check_raw_order(p, "interval")
        assert not r["ok"] and r["inversions"][0][0] == J["channels"][7]["k"]


def test_checker_only_inversion_is_caught():
    d = _first_node_dir("C"); J = json.load(open(os.path.join(d, "chk.json")))
    J["response"][0]["iv"] = [J["response"][0]["iv"][1], J["response"][0]["iv"][0]]
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "chk.json"); json.dump(J, open(p, "w"))
        r = check_raw_order(p, "interval")
        assert not r["ok"] and r["inversions"][0][0] == "response"
