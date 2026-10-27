"""One cold six-node bundle for one arm (C, PI or PP). Run as a subprocess so the supervisor can enforce caps and the
numerical caches are genuinely cold. Phase timings are written durably; heartbeats every <5 s via the progress file."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib, resource, argparse, struct
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.grid import Grid
from h4a.emit import Cache, write_point_witness, write_rect_witness, f64_value
from h4a.build import producer_tables, checker_tables
from h4a.tables import MESH, EPS_P, EPS_PHI, EPS_LAM
from h4a.masses import (marker_masses, publish_relative, node_weight, accepted_count, verify_masses,
                        weighted_count, replay_counts, verify_counts)
from h4a import certs

BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build")

def hb(path, **kw):
    f = open(path, "a"); f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mono": time.monotonic(), **kw}) + "\n"); f.flush(); os.fsync(f.fileno()); f.close()

def run_kernel(exe, args, hbpath, phase):
    t0 = time.monotonic(); r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    p = subprocess.Popen([os.path.join(BUILD, exe), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last = time.monotonic()
    while p.poll() is None:
        time.sleep(0.05)
        if time.monotonic() - last >= 3.0: last = time.monotonic(); hb(hbpath, phase=phase, kernel=exe, state="running", elapsed_s=round(time.monotonic()-t0,3))
    out, err = p.communicate()
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {"exe": exe, "rc": p.returncode, "wall_s": time.monotonic()-t0, "cpu_s": (r1.ru_utime-r0.ru_utime)+(r1.ru_stime-r0.ru_stime),
            "peak_rss_bytes": r1.ru_maxrss, "stderr": err.decode()[:400]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["C", "PI", "PP"]); ap.add_argument("--rep", type=int, required=True)
    ap.add_argument("--out-dir", required=True); ap.add_argument("--packet", required=True)
    a = ap.parse_args()
    OUT = os.path.abspath(a.out_dir); os.makedirs(OUT, exist_ok=True)
    HB = os.path.join(OUT, "progress.jsonl")
    T0 = time.monotonic()
    F = json.load(open(os.path.join(a.packet, "inputs", "FROZEN_NODES.json")))
    rec = {"arm": a.arm, "repetition": a.rep, "phases": [], "nodes": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    hb(HB, phase="start", arm=a.arm, rep=a.rep)
    # ---- model + grid (charged input reconstruction)
    t = time.monotonic(); m = Model(128, 1)
    assert m.canonical_sha256() == F["model_hash"], "canonical model hash mismatch"
    grids = {int(s): Grid(F["frequency_grids"][s]) for s in ("1", "-1")}
    rec["phases"].append({"phase": "input_reconstruction", "wall_s": time.monotonic()-t})
    hb(HB, phase="input_reconstruction", done=True)
    # ---- source-independent caches: one producer (256) + one checker (320), reused across BOTH signs
    t = time.monotonic(); cprod = Cache(m, grids[1], 256); tp = time.monotonic()-t
    rec["phases"].append({"phase": "producer_cache", "wall_s": tp, "prec": 256, "identity": cprod.identity, "checks": cprod.checks})
    hb(HB, phase="producer_cache", wall_s=round(tp,2))
    t = time.monotonic(); cchk = Cache(m, grids[1], 320); tc = time.monotonic()-t
    rec["phases"].append({"phase": "checker_cache", "wall_s": tc, "prec": 320, "identity": cchk.identity, "checks": cchk.checks})
    hb(HB, phase="checker_cache", wall_s=round(tc,2))
    assert cprod.identity != cchk.identity, "producer and checker caches must be separately constructed objects"
    # the two signs share the same mathematical grid here; assert that explicitly before reusing the cache
    assert [str(x) for x in grids[1].h] == [str(x) for x in grids[-1].h] and grids[1].J == grids[-1].J and grids[1].reps == grids[-1].reps, \
        "the two source signs do not share the frozen grid; cache reuse across signs is not permitted"
    prod_wall = tp; chk_wall = tc
    # ---- six nodes, source+ then source-, increasing rank
    nodes = sorted(F["nodes"], key=lambda d: (0 if d["source_sign"] == 1 else 1, d["processed_ordinal_1based"]))
    for nd in nodes:
        sgn = nd["source_sign"]; key = f"s{'p' if sgn==1 else 'm'}_r{nd['processed_ordinal_1based']}"
        nd_dir = os.path.join(OUT, key); os.makedirs(nd_dir, exist_ok=True)
        prob = NodeProblem(m, F["source_site"], sgn, F["target_site"], nd["positive_node"], "E0")
        nrec = {"key": key, "source_sign": sgn, "ordinal": nd["processed_ordinal_1based"], "node": nd["positive_node"], "phases": []}
        hb(HB, phase="node_start", node=key)
        # producer: sign-specific tables (always rebuilt) + witness + kernel
        t = time.monotonic(); P = producer_tables(prob, 256); t_tab = time.monotonic()-t
        worst_row = max([P["terminal"][1]] + [l1 for pc in P["rows"] for (_, l1, _e) in pc.values()])
        assert worst_row <= EPS_P, f"producer row L1 {worst_row} exceeds 2^-48"
        if a.arm == "C":
            t = time.monotonic(); write_rect_witness(f"{nd_dir}/prod.txt", prob, grids[sgn], cprod, P, 256, "producer"); t_w = time.monotonic()-t
            k = run_kernel("h4rect", ["--in", f"{nd_dir}/prod.txt", "--out", f"{nd_dir}/prod.json", "--prec", "256", "--expect-freq", "265", "--progress", HB], HB, f"{key}:producer")
        else:
            t = time.monotonic(); write_point_witness(f"{nd_dir}/prod.txt", prob, grids[sgn], cprod, P, "producer"); t_w = time.monotonic()-t
            k = run_kernel("h4point", ["--in", f"{nd_dir}/prod.txt", "--out", f"{nd_dir}/prod.json", "--expect-freq", "265", "--progress", HB], HB, f"{key}:producer")
        assert k["rc"] == 0, f"producer kernel failed: {k['stderr']}"
        nrec["phases"] += [{"phase": "producer_tables", "wall_s": t_tab, "worst_row_L1": str(worst_row)},
                           {"phase": "producer_witness", "wall_s": t_w}, {"phase": "producer_kernel", **k}]
        prod_wall += t_tab + t_w + k["wall_s"]
        # checker: own tables at 320 + own witness + own kernel
        if a.arm == "PP":
            t = time.monotonic(); CK = checker_tables(prob, 320); t_ctab = time.monotonic()-t
            worst_c = max([CK["initial"][1]] + [l1 for pc in CK["rows"].values() for (_, l1, _e) in pc.values()])
            assert worst_c <= EPS_P, f"checker row L1 {worst_c} exceeds 2^-48"
            t = time.monotonic(); write_point_witness(f"{nd_dir}/chk.txt", prob, grids[sgn], cchk, CK, "checker"); t_cw = time.monotonic()-t
            kc = run_kernel("h4pcheck", ["--in", f"{nd_dir}/chk.txt", "--out", f"{nd_dir}/chk.json", "--expect-freq", "265", "--progress", HB], HB, f"{key}:checker")
        else:
            # review finding 1b: the C/PI interval checker is the INDEPENDENT opposite-direction construction run
            # through the rectangular kernel, not the producer routine at higher precision.
            t = time.monotonic(); CKi = checker_tables(prob, 320); t_ctab = time.monotonic()-t
            worst_c = max([CKi["initial"][1]] + [l1 for pc in CKi["rows"].values() for (_, l1, _e) in pc.values()])
            assert worst_c <= EPS_P, f"checker row L1 {worst_c} exceeds 2^-48"
            t = time.monotonic(); write_rect_witness(f"{nd_dir}/chk.txt", prob, grids[sgn], cchk, CKi, 320, "checker"); t_cw = time.monotonic()-t
            kc = run_kernel("h4rect", ["--in", f"{nd_dir}/chk.txt", "--out", f"{nd_dir}/chk.json", "--prec", "320", "--forward", "--expect-freq", "265", "--progress", HB], HB, f"{key}:checker")
        assert kc["rc"] == 0, f"checker kernel failed: {kc['stderr']}"
        nrec["phases"] += [{"phase": "checker_tables", "wall_s": t_ctab, "worst_row_L1": str(worst_c)},
                           {"phase": "checker_witness", "wall_s": t_cw}, {"phase": "checker_kernel", **kc}]
        chk_wall += t_ctab + t_cw + kc["wall_s"]
        # ---- §5 positive marker masses, Gaussian node weight, accepted counts (required of every arm, charged)
        t = time.monotonic(); Zp, ep = marker_masses(prob, 256); t_mass_p = time.monotonic()-t
        t = time.monotonic(); Zc, ec = marker_masses(prob, 320, reverse=True); t_mass_c = time.monotonic()-t
        t = time.monotonic()
        pubm = {sg: publish_relative(Zp[sg]) for sg in (-1, 1)}
        total_raw = (Zp[-1][0] + Zp[1][0], Zp[-1][1] + Zp[1][1]); pubt = publish_relative(total_raw)
        wv, wexp = node_weight(prob.node, 256); wc, _ = node_weight(prob.node, 320)
        pubw = {**publish_relative(wv), "exponent": wexp}
        mprod = {"markers": pubm, "total": pubt, "node_weight": pubw}
        mchk = {"markers": Zc, "node_weight": wc, "node_weight_exponent": wexp}
        mverdict = verify_masses(mprod, mchk)
        delta = Fr(json.load(open(os.path.join(a.packet, "inputs", "FROZEN_NODES.json")))["analytic_delta_comp_exact"])
        Ipub = certs.response_publication(f"{nd_dir}/prod.json", a.arm)
        counts = {sg: {"accepted": accepted_count(pubt["pub"], Ipub[sg], pubm[sg]["pub"][1], delta)} for sg in (-1, 1)}
        for sg in (-1, 1): counts[sg]["weighted"] = weighted_count(counts[sg]["accepted"], pubw["pub"])
        t_agg = time.monotonic()-t
        # INDEPENDENT count replay from the checker's own quantities, inside the timed path (review item 1)
        t = time.monotonic()
        Ichk = certs.response_inner(f"{nd_dir}/chk.json", a.arm)
        Tchk = (Zc[-1][0] + Zc[1][0], Zc[-1][1] + Zc[1][1])
        creplay = {sg: replay_counts(Tchk, Ichk[sg], Zc[sg][1], delta, wc) for sg in (-1, 1)}
        cverdict = verify_counts(counts, creplay)
        t_creplay = time.monotonic()-t
        mverdict = {**mverdict, **cverdict}
        json.dump({"marker_masses_published": {str(sg): [str(x) for x in pubm[sg]["pub"]] for sg in (-1, 1)},
                   "marker_masses_midpoint": {str(sg): str(pubm[sg]["midpoint"]) for sg in (-1, 1)},
                   "checker_unpadded": {str(sg): [str(x) for x in Zc[sg]] for sg in (-1, 1)},
                   "total_published": [str(x) for x in pubt["pub"]],
                   "node_weight_published": [str(x) for x in pubw["pub"]], "node_weight_exponent": str(wexp),
                   "node_weight_checker_unpadded": [str(x) for x in wc],
                   "accepted_counts": {str(sg): [str(x) for x in counts[sg]["accepted"]] for sg in (-1, 1)},
                   "weighted_counts": {str(sg): [str(x) for x in counts[sg]["weighted"]] for sg in (-1, 1)},
                   "checker_replayed_accepted": {str(sg): [str(x) for x in creplay[sg]["accepted"]] for sg in (-1, 1)},
                   "checker_replayed_weighted": {str(sg): [str(x) for x in creplay[sg]["weighted"]] for sg in (-1, 1)},
                   "delta_comp": str(delta), "scale_exponents": {"producer": ep, "checker": ec},
                   "verdict": mverdict, "all_ok": all(mverdict.values())},
                  open(f"{nd_dir}/masses.json", "w"), indent=1, default=str)
        nrec["phases"] += [{"phase": "producer_masses", "wall_s": t_mass_p}, {"phase": "checker_masses", "wall_s": t_mass_c},
                           {"phase": "mass_publication_and_counts", "wall_s": t_agg},
                           {"phase": "checker_count_replay", "wall_s": t_creplay, "all_ok": all(mverdict.values())}]
        prod_wall += t_mass_p + t_agg; chk_wall += t_mass_c + t_creplay
        if not all(mverdict.values()):
            nrec["verdict"] = "REJECTED"; nrec["mass_failed"] = [k for k, v in mverdict.items() if not v]
            rec["nodes"].append(nrec); rec["stop"] = {"code": "VALIDITY_FAILURE", "node": key, "failed": nrec["mass_failed"]}
            break
        # ---- publication + containment verdict (charged)
        t = time.monotonic()
        v = certs.verify_node(a.arm, f"{nd_dir}/prod.json", f"{nd_dir}/chk.json", cprod, cchk, grids[sgn], prob)
        t_v = time.monotonic()-t
        json.dump(v, open(f"{nd_dir}/verdict.json", "w"), indent=1, default=str)
        nrec["phases"].append({"phase": "verification", "wall_s": t_v, "verdict": v["verdict"], "failed": v["failed_checks"]})
        chk_wall += t_v
        nrec["verdict"] = v["verdict"]
        rec["nodes"].append(nrec)
        hb(HB, phase="node_done", node=key, verdict=v["verdict"])
        if v["verdict"] != "VERIFIED":
            rec["stop"] = {"code": "VALIDITY_FAILURE", "node": key, "failed": v["failed_checks"]}
            break
    ru = resource.getrusage(resource.RUSAGE_CHILDREN); rs = resource.getrusage(resource.RUSAGE_SELF)
    rec["complete_wall_s"] = time.monotonic()-T0
    rec["producer_phase_wall_s"] = prod_wall; rec["checker_phase_wall_s"] = chk_wall
    rec["children_cpu_s"] = ru.ru_utime+ru.ru_stime; rec["self_cpu_s"] = rs.ru_utime+rs.ru_stime
    rec["peak_rss_bytes"] = max(ru.ru_maxrss, rs.ru_maxrss)
    rec["all_verified"] = all(n.get("verdict") == "VERIFIED" for n in rec["nodes"]) and len(rec["nodes"]) == 6
    rec["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    f = open(os.path.join(OUT, "bundle.json"), "w"); json.dump(rec, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close()
    hb(HB, phase="bundle_done", arm=a.arm, rep=a.rep, complete_wall_s=round(rec["complete_wall_s"],3), all_verified=rec["all_verified"])
    print(json.dumps({"arm": a.arm, "rep": a.rep, "complete_wall_s": rec["complete_wall_s"], "producer_wall_s": prod_wall, "checker_wall_s": chk_wall, "all_verified": rec["all_verified"]}))

if __name__ == "__main__": main()
