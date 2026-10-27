"""Single-node smoke: the complete pipeline on ONE positive node, both arms, with a DECLARED SYNTHETIC REMAINDER.

Addendum §1: "The single-node smoke validates its components with a declared synthetic remainder or a tiny fixture;
it must not claim to certify the full H4 query from one node." Accordingly this module:
  * runs the real producer and independent checker on one real H4 node law, both markers, all 265 representatives;
  * forms the real published masses, node weight, D and W and replays them from the checker;
  * supplies the other 2,573 node-laws as an explicitly SYNTHETIC remainder at their valid [0, w_hi*Z_hi] bounds,
    computed from real published masses so the aggregation path is exercised end to end;
  * reports the resulting enclosure as a SMOKE ARTIFACT, never as a query answer.
It evaluates exactly one node's responses. It is not a pilot invocation and produces no timing decision."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.grid import Grid
from h4a.emit import Cache, write_point_witness, write_rect_witness
from h4a.build import producer_tables, checker_tables
from h4a.masses import marker_masses, publish_relative, node_weight
from h4a import certs
from h4q.aggregate import SignState, NumericalRefusal, interval_product

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(CODE, "build")


def _run(exe, args):
    t = time.monotonic(); r = subprocess.run([os.path.join(BUILD, exe), *args], capture_output=True, text=True)
    return r, time.monotonic() - t


def smoke_one_node(arm, packet, out_dir, node=(0, 0), sign=1, journal=lambda r: None):
    os.makedirs(out_dir, exist_ok=True)
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    delta = Fr(F["analytic_delta_comp_exact"])
    m = Model(128, 1)
    assert m.canonical_sha256() == F["model_hash"], "canonical model hash mismatch"
    g = Grid(F["frequency_grids"]["1"])
    prob = NodeProblem(m, F["source_site"], sign, F["target_site"], node, "E0")
    phases = {}
    t = time.monotonic(); cp = Cache(m, g, 256); phases["producer_cache"] = time.monotonic() - t
    t = time.monotonic(); cc = Cache(m, g, 320); phases["checker_cache"] = time.monotonic() - t
    journal({"step": "caches", "arm": arm, **{k: round(v, 3) for k, v in phases.items()}})
    # --- real masses and node weight for THIS node
    t = time.monotonic(); Zp, ep = marker_masses(prob, 256); phases["producer_masses"] = time.monotonic() - t
    t = time.monotonic(); Zc, ec = marker_masses(prob, 320, reverse=True); phases["checker_masses"] = time.monotonic() - t
    pubm = {sg: publish_relative(Zp[sg]) for sg in (-1, 1)}
    wv, wexp = node_weight(node, 256); wc, wexp_c = node_weight(node, 320)
    pubw = publish_relative(wv)
    # --- real responses, both markers, all 265 representatives
    t = time.monotonic(); P = producer_tables(prob, 256); phases["producer_tables"] = time.monotonic() - t
    t = time.monotonic(); CK = checker_tables(prob, 320); phases["checker_tables"] = time.monotonic() - t
    if arm == "C":
        write_rect_witness(f"{out_dir}/prod.txt", prob, g, cp, P, 256, "producer")
        r, dt = _run("h4rect", ["--in", f"{out_dir}/prod.txt", "--out", f"{out_dir}/prod.json", "--prec", "256", "--expect-freq", "265"])
    else:
        write_point_witness(f"{out_dir}/prod.txt", prob, g, cp, P, "producer")
        r, dt = _run("h4point", ["--in", f"{out_dir}/prod.txt", "--out", f"{out_dir}/prod.json", "--expect-freq", "265"])
    assert r.returncode == 0, r.stderr[:300]
    phases["producer_kernel"] = dt
    if arm == "PP":
        write_point_witness(f"{out_dir}/chk.txt", prob, g, cc, CK, "checker")
        r, dt = _run("h4pcheck", ["--in", f"{out_dir}/chk.txt", "--out", f"{out_dir}/chk.json", "--expect-freq", "265"])
    else:
        write_rect_witness(f"{out_dir}/chk.txt", prob, g, cc, CK, 320, "checker")
        r, dt = _run("h4rect", ["--in", f"{out_dir}/chk.txt", "--out", f"{out_dir}/chk.json", "--prec", "320", "--forward", "--expect-freq", "265"])
    assert r.returncode == 0, r.stderr[:300]
    phases["checker_kernel"] = dt
    # --- verification and published responses
    t = time.monotonic()
    verdict = certs.verify_node(arm, f"{out_dir}/prod.json", f"{out_dir}/chk.json", cp, cc, g, prob)
    Rpub = certs.response_publication(f"{out_dir}/prod.json", arm)
    Rinner = certs.response_inner(f"{out_dir}/chk.json", arm)
    phases["verification"] = time.monotonic() - t
    # --- aggregation with a DECLARED SYNTHETIC remainder
    t = time.monotonic()
    st = SignState(sign, delta)
    st.set_node(node, pubm[1]["pub"], pubm[-1]["pub"], pubw["pub"])
    synthetic = []
    for j0 in range(-19, 20):
        for j1 in range(-16, 17):
            if (j0, j1) == tuple(node): continue
            synthetic.append((j0, j1))
    # synthetic remainder: reuse THIS node's published mass and weight for every other node, declared as synthetic
    for nd in synthetic:
        st.set_node(nd, pubm[1]["pub"], pubm[-1]["pub"], pubw["pub"])
    rank = st.rank_and_designate_tail()
    before = st.prefix_enclosure()
    st.process_node(tuple(node), Rpub)
    after = st.prefix_enclosure()
    Dchk = {}
    for sg in (1, -1):
        Zhi = Zc[sg][1]; T = (Zc[-1][0] + Zc[1][0], Zc[-1][1] + Zc[1][1])
        prod = interval_product(T, Rinner[sg]); allow = delta * Zhi
        lo, hi = max(Fr(0), prod[0] - allow), min(Zhi, prod[1] + allow)
        Dchk[sg] = (lo, hi)
    Wchk = {(tuple(node), sg): interval_product(Dchk[sg], wc) for sg in (1, -1)}
    contained = all(st.W[(tuple(node), sg)][0] <= Wchk[(tuple(node), sg)][0]
                    and Wchk[(tuple(node), sg)][1] <= st.W[(tuple(node), sg)][1] for sg in (1, -1))
    phases["aggregation_and_replay"] = time.monotonic() - t
    rec = {"arm": arm, "node": list(node), "source_sign": sign,
           "SCOPE": "SMOKE ARTIFACT: one real node plus a DECLARED SYNTHETIC remainder of 2573 node-laws at their "
                    "valid [0, w_hi*Z_hi] bounds. This is NOT a query answer and certifies nothing about the full H4 query.",
           "node_verdict": verdict["verdict"], "node_failed_checks": verdict["failed_checks"],
           "checker_exponent_retained_and_equal": str(wexp) == str(wexp_c),
           "checker_W_contained_in_producer_W": contained,
           "masses": {"Z_plus_published": [str(x) for x in pubm[1]["pub"]], "Z_minus_published": [str(x) for x in pubm[-1]["pub"]],
                      "checker_unpadded_plus": [str(x) for x in Zc[1]], "node_weight_published": [str(x) for x in pubw["pub"]],
                      "scale_exponents": {"producer": ep, "checker": ec}},
           "ranking": {k: str(v) for k, v in rank.items()},
           "enclosure_before_processing": [str(x) for x in before["enclosure"]],
           "enclosure_after_one_node": [str(x) for x in after["enclosure"]],
           "width_after_one_node": str(after["enclosure"][1] - after["enclosure"][0]),
           "qualifies_after_one_node": st.qualifies(),
           "phases_s": {k: round(v, 4) for k, v in phases.items()},
           "complete_wall_s": round(sum(phases.values()), 4)}
    rec["all_ok"] = (verdict["verdict"] == "VERIFIED" and contained and rec["checker_exponent_retained_and_equal"]
                     and before["enclosure"] == (Fr(0), Fr(1)))
    f = open(os.path.join(out_dir, "smoke.json"), "w"); json.dump(rec, f, indent=1, default=str)
    f.flush(); os.fsync(f.fileno()); f.close()
    journal({"step": "smoke_done", "arm": arm, "all_ok": rec["all_ok"], "verdict": verdict["verdict"]})
    return rec
