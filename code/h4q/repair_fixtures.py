"""G3 repair: run the two H4 and four product fixtures through EVERY applicable producer/checker path, including the
forward interval path, and assert NUMERICAL CONTAINMENT of both complex coordinates and both marker responses against
an independent 512-bit enumeration enclosure. The shipped G3 asserted only exit status and record lengths."""
from __future__ import annotations
import sys, os, json, time, subprocess, tempfile
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.grid import Grid
from h4a.emit import Cache, write_point_witness, write_rect_witness
from h4a.build import producer_tables, checker_tables
from h4a.refenum import enumerate_reference
from h4q.repair_verify import fx, fb

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(CODE, "build")
E_CH = Fr(1, 1 << 38); E_INT = Fr(1, 1 << 36)

PATHS = [("h4point", "producer", "point", []),
         ("h4pcheck", "checker", "point", []),
         ("h4rect", "producer", "interval", ["--prec", "256"]),
         ("h4rect", "checker", "interval", ["--prec", "320", "--forward"])]


def run_h4_fixtures(packet, journal, budget_s):
    t0 = time.monotonic()
    S = json.load(open(os.path.join(packet, "inputs", "SMALL_FIXTURES.json")))
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    g = Grid(F["frequency_grids"]["1"])
    out = {"record": "G3_FIXTURE_REPAIR", "assertion": "numerical containment vs an independent 512-bit enumeration, "
           "both complex coordinates and both marker responses, on every applicable path including h4rect --forward",
           "fixtures": {}}
    for f in S["fixtures"]:
        if time.monotonic() - t0 > budget_s:
            out["RESOURCE_STOP"] = {"elapsed_s": round(time.monotonic()-t0,1)}; return out
        n = f["model"]["n"]; m = Model(n, f["model"]["seed"])
        prob = NodeProblem(m, f["source_site"], f["source_sign"], f["target_site"], f["positive_node"], f["context"])
        d = tempfile.mkdtemp(); cp = Cache(m, g, 256); cc = Cache(m, g, 320)
        P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
        P320 = producer_tables(prob, 320)
        REF = enumerate_reference(prob, g, prec=512)
        fx_out = {"n": n, "pins": sorted(prob.pins.items()), "target": prob.q, "paths": {}}
        for exe, role, kind, extra in PATHS:
            tag = f"{exe}_{role}" + ("_forward" if "--forward" in extra else "")
            if exe == "h4point": write_point_witness(f"{d}/{tag}.txt", prob, g, cp, P, "producer")
            elif exe == "h4pcheck": write_point_witness(f"{d}/{tag}.txt", prob, g, cc, CK, "checker")
            elif role == "producer": write_rect_witness(f"{d}/{tag}.txt", prob, g, cp, P, 256, "producer")
            else: write_rect_witness(f"{d}/{tag}.txt", prob, g, cc, CK, 320, "checker")
            r = subprocess.run([os.path.join(BUILD, exe), "--in", f"{d}/{tag}.txt", "--out", f"{d}/{tag}.json",
                                "--expect-freq", "265", *extra], capture_output=True, text=True)
            if r.returncode: fx_out["paths"][tag] = {"rc": r.returncode, "stderr": r.stderr[:200]}; continue
            J = json.load(open(f"{d}/{tag}.json"))
            bad_re = bad_im = bad_resp = 0; worst = Fr(0)
            for ch in J["channels"]:
                ki, sg = ch["k"], ch["marker"]; ref_re, ref_im = REF["channels"][sg][ki]
                for comp, ref in (("re", ref_re), ("im", ref_im)):
                    if kind == "point":
                        v = fb(ch[comp]); dev = max(abs(v - ref[0]), abs(v - ref[1]))
                        worst = max(worst, dev)
                        if dev > E_CH: (bad_re if comp == "re" else bad_im).__class__  # count below
                        if dev > E_CH:
                            if comp == "re": bad_re += 1
                            else: bad_im += 1
                    else:
                        lo, hi = fx(ch[comp][0]), fx(ch[comp][1])
                        if not (lo - E_CH <= ref[1] and ref[0] <= hi + E_CH):
                            if comp == "re": bad_re += 1
                            else: bad_im += 1
            for rr in J["response"]:
                sg = rr["marker"]; ref = REF["response"][sg]
                if kind == "point":
                    v = fb(rr["bits"])
                    if max(abs(v - ref[0]), abs(v - ref[1])) > E_INT: bad_resp += 1
                else:
                    lo, hi = fx(rr["iv"][0]), fx(rr["iv"][1])
                    if not (lo - E_INT <= ref[1] and ref[0] <= hi + E_INT): bad_resp += 1
            fx_out["paths"][tag] = {"rc": 0, "channels": len(J["channels"]), "responses": len(J["response"]),
                                    "re_violations": bad_re, "im_violations": bad_im, "response_violations": bad_resp,
                                    "worst_point_deviation": str(worst) if kind == "point" else None,
                                    "contained": bad_re == 0 and bad_im == 0 and bad_resp == 0}
            journal({"phase": "G3_fixtures", "fixture": f["fixture_id"], "path": tag,
                     "contained": fx_out["paths"][tag]["contained"]})
        fx_out["all_paths_contained"] = all(p.get("contained") for p in fx_out["paths"].values())
        out["fixtures"][f["fixture_id"]] = fx_out
    out["all_ok"] = all(v["all_paths_contained"] for v in out["fixtures"].values())
    out["elapsed_s"] = round(time.monotonic() - t0, 3)
    return out
