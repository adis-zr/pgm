"""Regression tests for the second review's four items (27 Oct 2026). Each asserts the specific defect is closed."""
import os, sys, json, copy, subprocess, struct, pathlib, tempfile
HERE = pathlib.Path(__file__).resolve().parents[2]
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
import pytest
from pgm.algorithms.h4.tables import MP, fr
from pgm.algorithms.h4.masses import marker_masses, publish_relative, node_weight, accepted_count, weighted_count, replay_counts, verify_counts, verify_masses
from pgm.algorithms.h4.model import Model, NodeProblem
from pgm.algorithms.h4.grid import Grid
from pgm.algorithms.h4.emit import Cache, write_point_witness, write_rect_witness
from pgm.algorithms.h4.build import producer_tables, checker_tables
from pgm.algorithms.h4 import certs

# consolidation repair R5: the H4 arithmetic packet is a PRIVATE record dependency (pgm-records: docs/h4-arithmetic-contract-2026-10-27);
# override its location with H4A_PACKET=/path/to/h4-arithmetic-contract-2026-10-27.  When absent, the dependent tests are BLOCKED (skipped
# with that reason) instead of erroring; the assertions are unchanged.
from research.paths import records_root, runs_root
PACKET = str(pathlib.Path(os.environ["H4A_PACKET"]).expanduser()) if "H4A_PACKET" in os.environ else str((records_root() or runs_root().parent) / "docs/h4-arithmetic-contract-2026-10-27")
from pgm.algorithms.h4.kernels import kernel_path


def _packet_file(*parts):
    path = os.path.join(PACKET, *parts)
    if not os.path.exists(path):
        pytest.skip("BLOCKED: private H4 packet file absent: %s (set H4A_PACKET)" % path)
    return path

def _frozen():
    return json.load(open(_packet_file("inputs", "FROZEN_NODES.json")))

# ---- item 3: uninitialised message slots (small fixtures trigger it; HARD E0 does not)
@pytest.mark.parametrize("fixture_ix", [0, 1])
def test_small_fixtures_through_all_four_kernel_paths(fixture_ix):
    S = json.load(open(_packet_file("inputs", "SMALL_FIXTURES.json")))
    F = _frozen(); g = Grid(F["frequency_grids"]["1"])
    f = S["fixtures"][fixture_ix]; m = Model(f["model"]["n"], f["model"]["seed"])
    prob = NodeProblem(m, f["source_site"], f["source_sign"], f["target_site"], f["positive_node"], f["context"])
    d = tempfile.mkdtemp(); c256 = Cache(m, g, 256); c320 = Cache(m, g, 320)
    P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
    write_point_witness(f"{d}/p.txt", prob, g, c256, P, "producer")
    write_point_witness(f"{d}/c.txt", prob, g, c320, CK, "checker")
    write_rect_witness(f"{d}/r256.txt", prob, g, c256, P, 256, "producer")
    write_rect_witness(f"{d}/r320f.txt", prob, g, c320, CK, 320, "checker")
    for exe, inp, outp, extra in (("h4point", "p.txt", "p.json", []), ("h4pcheck", "c.txt", "c.json", []),
                                  ("h4rect", "r256.txt", "r256.json", ["--prec", "256"]),
                                  ("h4rect", "r320f.txt", "r320f.json", ["--prec", "320", "--forward"])):
        r = subprocess.run([str(kernel_path(exe)), "--in", f"{d}/{inp}", "--out", f"{d}/{outp}", "--expect-freq", "265", *extra],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{exe} {extra}: {r.stderr[:300]}"
        J = json.load(open(f"{d}/{outp}"))
        assert len(J["channels"]) == 530 and len(J["response"]) == 2

# ---- item 2: verifier gaps
def _node_records():
    F = _frozen(); g = Grid(F["frequency_grids"]["1"]); m = Model(128, 1)
    prob = NodeProblem(m, F["source_site"], 1, F["target_site"], F["nodes"][0]["positive_node"], "E0")
    cp = Cache(m, g, 256); cc = Cache(m, g, 320)
    d = tempfile.mkdtemp(); P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
    write_point_witness(f"{d}/prod.txt", prob, g, cp, P, "producer")
    write_point_witness(f"{d}/chk.txt", prob, g, cc, CK, "checker")
    for inp, outp, exe in (("prod.txt", "prod.json", "h4point"), ("chk.txt", "chk.json", "h4pcheck")):
        r = subprocess.run([str(kernel_path(exe)), "--in", f"{d}/{inp}", "--out", f"{d}/{outp}", "--expect-freq", "265"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:300]
    return d, cp, cc, g, prob

def test_verifier_rejects_duplicate_response_and_false_probe_and_empty_certificates():
    d, cp, cc, g, prob = _node_records()
    assert certs.verify_node("PP", f"{d}/prod.json", f"{d}/chk.json", cp, cc, g, prob)["verdict"] == "VERIFIED"
    P = json.load(open(f"{d}/prod.json")); C = json.load(open(f"{d}/chk.json"))
    def run(p2=None, c2=None, cpm=None, ccm=None):
        t = tempfile.mkdtemp()
        json.dump(p2 or P, open(f"{t}/prod.json", "w")); json.dump(c2 or C, open(f"{t}/chk.json", "w"))
        return certs.verify_node("PP", f"{t}/prod.json", f"{t}/chk.json", cpm or cp, ccm or cc, g, prob)
    dp = copy.deepcopy(P); dp["response"] = dp["response"] + [dp["response"][0]]
    assert "no_duplicate_response_records" in run(p2=dp)["failed_checks"]
    dc = copy.deepcopy(C); dc["response"] = dc["response"] + [dc["response"][0]]
    assert "no_duplicate_response_records" in run(c2=dc)["failed_checks"]
    fp = copy.deepcopy(P); fp["probes_ok"] = False
    assert "producer_probe_flag_not_false" in run(p2=fp)["failed_checks"]
    class Empty: identity = "e" * 64; checks = {}
    assert "producer_cache_certificates_present" in run(cpm=Empty())["failed_checks"]
    class NoBool: identity = "n" * 64; checks = {"representatives": 265}
    assert "producer_cache_certificates" in run(cpm=NoBool())["failed_checks"]

# ---- item 1: independent count replay and weighted counts
def test_accepted_and_weighted_counts_replay_independently():
    S = json.load(open(_packet_file("inputs", "SMALL_FIXTURES.json")))
    F = _frozen(); f = S["fixtures"][0]; m = Model(f["model"]["n"], f["model"]["seed"])
    prob = NodeProblem(m, f["source_site"], f["source_sign"], f["target_site"], f["positive_node"], f["context"])
    Zp, _ = marker_masses(prob, 256); Zc, _ = marker_masses(prob, 320, reverse=True)
    pubm = {sg: publish_relative(Zp[sg]) for sg in (-1, 1)}
    pubt = publish_relative((Zp[-1][0] + Zp[1][0], Zp[-1][1] + Zp[1][1]))
    wv, wexp = node_weight(prob.node, 256); wc, _ = node_weight(prob.node, 320)
    pubw = {**publish_relative(wv), "exponent": wexp}
    delta = Fr(F["analytic_delta_comp_exact"])
    I = {sg: (Fr(-1, 1000), Fr(1, 1000)) for sg in (-1, 1)}
    prod = {sg: {"accepted": accepted_count(pubt["pub"], I[sg], pubm[sg]["pub"][1], delta)} for sg in (-1, 1)}
    for sg in (-1, 1): prod[sg]["weighted"] = weighted_count(prod[sg]["accepted"], pubw["pub"])
    Tchk = (Zc[-1][0] + Zc[1][0], Zc[-1][1] + Zc[1][1])
    rep = {sg: replay_counts(Tchk, I[sg], Zc[sg][1], delta, wc) for sg in (-1, 1)}
    v = verify_counts(prod, rep)
    assert all(v.values()), v
    mv = verify_masses({"markers": pubm, "total": pubt, "node_weight": pubw},
                       {"markers": Zc, "node_weight": wc, "node_weight_exponent": wexp})
    assert all(mv.values()), mv

# ---- earlier repairs stay closed
def test_signed_division_encloses_truth():
    M = MP(64)
    a = M.q(Fr(-1)); b = (M.q(Fr(29, 10))[0], M.q(Fr(31, 10))[1])
    lo, hi = M.div_pos(a, b); lo, hi = fr(lo), fr(hi)
    assert lo <= hi and lo <= Fr(-1, 3) <= hi

def test_power_of_two_scaling_preserves_width():
    M = MP(64); a = M.q(Fr(1, 3)); w0 = fr(a[1]) - fr(a[0])
    for e in (0, 3, -3, 40, -40, 200, -200):
        b = M.scale2(a, e)
        assert fr(b[1]) - fr(b[0]) == w0 * (Fr(2) ** e)
        assert fr(b[0]) <= Fr(1, 3) * (Fr(2) ** e) <= fr(b[1])

def test_rect_arm_consumes_true_enclosures_not_quantized_points():
    """arm C's emitted row/phase/weight intervals must be non-degenerate (lo < hi) for at least some entries"""
    F = _frozen(); g = Grid(F["frequency_grids"]["1"]); m = Model(8, 0)
    prob = NodeProblem(m, 0, 1, 4, [0, 0], "E0")
    c = Cache(m, g, 256); P = producer_tables(prob, 256)
    d = tempfile.mkdtemp(); write_rect_witness(f"{d}/r.txt", prob, g, c, P, 256, "producer")
    nondeg = 0
    for line in open(f"{d}/r.txt"):
        if line.startswith(("ROW", "PH ", "LAM")):
            parts = line.split()
            vals = [p for p in parts if "*2^" in p]
            for i in range(0, len(vals) - 1, 2):
                lo = Fr(int(vals[i].split("*2^")[0]), 1) * Fr(2) ** int(vals[i].split("*2^")[1])
                hi = Fr(int(vals[i+1].split("*2^")[0]), 1) * Fr(2) ** int(vals[i+1].split("*2^")[1])
                if lo < hi: nondeg += 1
    assert nondeg > 0, "every emitted interval is degenerate: arm C is consuming a rounded surrogate"
