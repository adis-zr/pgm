"""Small correctness validation (CLAUDE_CODE_SPEC.md "Small correctness validation"): three n=8 cases against an independently enclosed
exhaustive original-model reference (<= 256 assignments), plus two tamper tests (corrupted stored centre residual bound; corrupted stored
Fourier analytic-error bound) that the checker must reject.  These tiny models are implementation checks; they may fail the 0.01
response-admission gate (recorded, not an affordability result).  Whole file must run within the 60 s validation cap."""
import json
import os
import shutil
import subprocess
import sys
import time
from fractions import Fraction as Fr

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from dq.model import Model, parse_canonical  # noqa: E402
from dq.reference import enumerate_reference  # noqa: E402
from dq.gate import response_gate  # noqa: E402
from dq.publish import fx, publish_direct, marker_ratio  # noqa: E402
from dq.constants import alias_upper, truncation_upper  # noqa: E402
from dq.arms import run_arm  # noqa: E402
from dq.checker import check_arm  # noqa: E402
from dq.supervisor import Journal  # noqa: E402

CASES = [("MAIN", None), ("CONTROL", None), ("MAIN", {3: 1, 6: -1})]
T_START = time.monotonic()


def ov(a, b): return a[0] <= b[1] and b[0] <= a[1]
def within(inner, outer): return outer[0] <= inner[0] and inner[1] <= outer[1]


@pytest.mark.parametrize("case,ev", CASES)
def test_tiny_against_exhaustive_reference(case, ev, tmp_path):
    m = Model(8, case, ev); inp = str(tmp_path / "in.txt"); m.write(inp); parse_canonical(inp)
    assert m.a == [Fr(3, 8) * t for t in m.t]                        # a_i = (3/4) sqrt(2/8) t_i = 3 t_i / 8
    ref0 = enumerate_reference(m, Fr(0))
    # producer in F mode (D is a subset of its work) with the frozen policy and the MAIN grid (h=1, J=3): small models use it as an implementation check
    out = str(tmp_path / "p.json")
    subprocess.run([os.path.join(ROOT, "build", "dqchain"), inp, out, "--mode", "F", "--fbits", "80", "--steps", "17", "--step", "2/5", "--freq-h", "1", "--J", "3"], check=True)
    P = json.load(open(out)); c = fx(P["center"]["c"])
    ref = enumerate_reference(m, c, freqs=[1, 2, 3])
    # (a) transfer: q0 at the centre and the residual-only q0 at c=0 enclose the reference
    q = (fx(P["final"]["q0"][0]), fx(P["final"]["q0"][1])); assert ov(q, ref["q0"]) and (q[1] - q[0]) < Fr(1, 10 ** 15)
    q00 = (fx(P["q0_residual_only_c0"][0]), fx(P["q0_residual_only_c0"][1])); assert ov(q00, ref0["q0"])
    # (b) centre identity: residual = c - E_Q AX encloses the reference value
    r = (fx(P["final"]["residual"][0]), fx(P["final"]["residual"][1])); refr = (c - ref["E_Q_AX"][1], c - ref["E_Q_AX"][0]); assert ov(r, refr)
    # (c) evidence cross terms: the exhaustive reference keeps pinned sites in AX with the original n; the producer's tilted law must agree (q0, phi)
    for fk in P["fourier"]["frequencies"]:
        k = str(fk["k"]); rp = ref["phi"][k][1]; rm = ref["phi"][k][-1]
        for s, rr in (("phi_plus", rp), ("phi_minus", rm)):
            assert ov((fx(fk[s]["re"][0]), fx(fk[s]["re"][1])), rr["re"]) and ov((fx(fk[s]["im"][0]), fx(fk[s]["im"][1])), rr["im"])
    # (d) fixed-node response enclosure: |p0 - q0| <= E0 computed from the input (the exact original p0 lies within q0 +- E0)
    G = response_gate(m, bits=128); E0 = Fr(G["E0_upper"])
    assert ref["p0"][0] >= q[0] - E0 and ref["p0"][1] <= q[1] + E0
    # (e) Fourier error enclosure: the finite estimate Ghat is within delta (input-derived alias+trunc) of the true counts N+, N- = G - N+
    V = Fr(G["V_bar"]); delta = alias_upper(Fr(1), Fr(1, 8), V) + truncation_upper(Fr(1), 3)
    GP = (fx(P["fourier"]["Ghat_plus"][0]), fx(P["fourier"]["Ghat_plus"][1])); GM = (fx(P["fourier"]["Ghat_minus"][0]), fx(P["fourier"]["Ghat_minus"][1]))
    Nm = (ref["G"][0] - ref["N_plus"][1], ref["G"][1] - ref["N_plus"][0])
    assert GP[0] - delta <= ref["N_plus"][1] and ref["N_plus"][0] <= GP[1] + delta
    assert GM[0] - delta <= Nm[1] and Nm[0] <= GM[1] + delta
    # (f) final interval algebra: both publication rules contain the exhaustive original p0
    pubD = publish_direct(q[0], q[1], E0, Fr(1, 16000)); assert Fr(pubD["lo"]) <= ref["p0"][0] and ref["p0"][1] <= Fr(pubD["hi"])
    pubF = marker_ratio(GP[0], GP[1], GM[0], GM[1], delta + Fr(1, 100000)); assert Fr(pubF["lo"]) <= ref["p0"][0] and ref["p0"][1] <= Fr(pubF["hi"])
    # record the expected distinction: tiny models need not pass the admission gate
    print(f"[{case} ev={ev}] gate={G['decision']} E0={float(E0):.4f} p0={float(ref['p0'][0]):.6f} q0={float(q[0]):.6f} widthD={pubD['width_float']:.4f} widthF={pubF['width_float']:.4f}")


def test_tamper_center_residual_and_fourier_radius(tmp_path):
    """Full arm on the tiny MAIN model, then corrupt (i) the stored residual witness / residual enclosure and (ii) the stored analytic radius."""
    d = str(tmp_path / "F"); R = run_arm("F", "MAIN", 8, d, deadline_s=60)
    assert R["status"] in ("VERIFIED", "CERTIFICATE_OR_CHECKER_FAILURE")                 # n=8 may miss the 1/100 width; the checker still runs
    W = json.load(open(R["witness_path"]))
    def recheck(Wt, tag):
        cdir = str(tmp_path / tag); os.makedirs(cdir); J = Journal(os.path.join(cdir, "events.jsonl"))
        V = check_arm("F", os.path.join(d, "input.txt"), Wt, cdir, J, 60, 4 << 30, 128); J.close(); return V
    V0 = recheck(W, "clean"); assert "residual_strictly_below_witness" not in (V0.get("failed_checks") or [])
    # (i) corrupt the stored centre residual: claim a residual enclosure far below the checker's (shift it) and a tiny witness
    W1 = json.loads(json.dumps(W)); W1["final"]["residual"] = [str(fx(W["final"]["residual"][0]) - Fr(1, 2)), str(fx(W["final"]["residual"][1]) - Fr(1, 2))]
    W1["final"]["residual"] = ["%d*2^0" % 0, "%d*2^0" % 0]; W1["final"]["residual_abs"] = ["0*2^0", "0*2^0"]
    V1 = recheck(W1, "t1"); assert V1["verdict"] == "REJECTED" and "residual_enclosures_overlap" in V1["failed_checks"]
    W1b = json.loads(json.dumps(W)); W1b["final"]["residual_witness"] = str(Fr(1, 10 ** 30))
    V1b = recheck(W1b, "t1b"); assert V1b["verdict"] == "REJECTED" and "residual_strictly_below_witness" in V1b["failed_checks"]
    # (ii) corrupt the stored Fourier analytic-error bound: declare a radius smaller than the recomputed alias+truncation
    W2 = json.loads(json.dumps(W)); W2["fourier"]["delta_declared"] = str(Fr(1, 10 ** 6))
    V2 = recheck(W2, "t2"); assert V2["verdict"] == "REJECTED" and ("declared_analytic_radius_dominates_recomputed" in V2["failed_checks"] or "grid_is_frozen" in V2["failed_checks"])
    # (iii) over-narrow publication: shrink the published interval so the checker's independent enclosure is no longer contained
    W3 = json.loads(json.dumps(W)); lo, hi = Fr(W["published"]["lo"]), Fr(W["published"]["hi"]); mid = (lo + hi) / 2
    W3["published"]["lo"] = str(mid - Fr(1, 10 ** 6)); W3["published"]["hi"] = str(mid + Fr(1, 10 ** 6))
    V3 = recheck(W3, "t3"); assert V3["verdict"] == "REJECTED" and "independent_enclosure_contained_in_publication" in V3["failed_checks"]


def test_validation_within_cap():
    assert time.monotonic() - T_START < 60, "small validation exceeded the 60 s cap"
