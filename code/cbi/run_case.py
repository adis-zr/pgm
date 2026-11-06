"""ONE experiment case in a fresh process: load the model file, run solve + verify in-process (cold: incl. parse, reductions,
recognition, planning, solving, certificate, verification, publication), then two repeated-query solves on the loaded model; optionally
the exact comparator (force_exact: exact operators / dense elimination on the whole component, priced BEFORE launch) or a
brute-force / exact-VE truth file for containment and movement. Writes one JSON.
usage: run_case.py MODEL.json QUERIES WIDTH MODE LIMITS_JSON OUT.json [TRUTH.json]
MODE in {library, comparator_exact, truth_ve}"""
import sys, os, json, time, resource
T_START = time.monotonic()
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from cbi import model as M, api, exact as EX, arith as A

MAX_REF_ENTRIES = 1 << 23


def rss():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r) if sys.platform == "darwin" else int(r) * 1024


def main(argv):
    mp, qarg, width, mode, limits, out = argv[:6]; truth_p = argv[6] if len(argv) > 6 else None
    limits = json.loads(limits); qs = "all" if qarg == "all" else [int(x) for x in qarg.split(",")]
    rec = {"model": os.path.basename(mp), "mode": mode, "width": width, "queries": qarg, "status": "STARTED", "timings": {}}
    t0 = time.monotonic(); m = M.Model.load(mp); rec["timings"]["load_model_s"] = time.monotonic() - t0
    rec["model_sha256"] = m.meta["sha256"]; rec["blocks"] = len(m.blocks); rec["edges"] = len(m.edges); rec["d"] = m.d
    qlist = sorted(m.blocks) if qs == "all" else qs
    pi = {q: [Fr(sum(w for x, w in zip(m.blocks[q].rows, m.blocks[q].w) if (x >> j) & 1), sum(m.blocks[q].w)) for j in range(m.d)] for q in qlist}
    try:
        if mode == "truth_ve":
            red = M.reduce_model(m); rec["reduced_blocks"] = len(red.blocks)
            if red.infeasible:
                rec["status"] = "INFEASIBLE"; rec["truth"] = None
            else:
                worst = max(EX.price(red.blocks, red.edges, red.orig_to_red[q])[0] for q in qlist); rec["price_entries"] = worst
                if worst > MAX_REF_ENTRIES:
                    rec["status"] = "RESOURCE_LIMIT"; rec["reason"] = "exact VE needs %d entries > %d: not launched" % (worst, MAX_REF_ENTRIES)
                else:
                    t0 = time.monotonic(); tr = {}
                    for q in qlist:
                        rq = red.orig_to_red[q]; marg, _ = EX.marginal(red.blocks, red.edges, rq, max_entries=MAX_REF_ENTRIES); Z = sum(marg)
                        tr[str(q)] = [str(Fr(sum(w for x, w in zip(red.blocks[rq].rows, marg) if (x >> j) & 1), Z)) for j in range(m.d)]
                    rec["timings"]["truth_ve_s"] = time.monotonic() - t0; rec["truth"] = tr; rec["status"] = "OK"
        else:
            lim = dict(limits)
            if mode == "comparator_exact":
                lim.update({"force_exact": True, "no_coarsening": True, "exact_direct_entries": MAX_REF_ENTRIES, "max_entries": MAX_REF_ENTRIES})
                red = M.reduce_model(m)
                if red.infeasible is None:
                    worst = max(EX.price(red.blocks, red.edges, red.orig_to_red[q])[0] for q in qlist); rec["price_entries"] = worst
                    if worst > MAX_REF_ENTRIES:
                        rec["status"] = "RESOURCE_LIMIT"; rec["reason"] = "exact comparator needs %d dense entries > %d: not launched" % (worst, MAX_REF_ENTRIES)
                        json.dump(rec, open(out, "w"), indent=1, default=str); print(json.dumps({k: rec.get(k) for k in ("model", "mode", "status", "reason")})); return 0
            t0 = time.monotonic(); res = api.solve(m, qs, width, lim); t1 = time.monotonic(); ver = api.verify(m, res); t2 = time.monotonic()
            rec["timings"].update({"solve_s": t1 - t0, "verify_s": t2 - t1, "cold_solve_plus_verify_s": t2 - t0, "solve_phases_s": res["timings"]})
            rec["status"] = res["status"]; rec["verify_accepted"] = ver["accepted"]; rec["verify_reasons"] = ver["reasons"][-3:]
            rec["per_query"] = {}
            for q in qlist:
                iv = res["intervals"].get(str(q)); c = res["certificate"].get(str(q)) if isinstance(res["certificate"], dict) else None
                row = {"status": res["statuses_per_query"].get(str(q)), "max_width": (iv or {}).get("max_width_float"), "width_met": (iv or {}).get("width_met"), "mode": (c or {}).get("mode"),
                       "region": (c or {}).get("H"), "z": (c or {}).get("z_query"), "ops": (c or {}).get("inside_ops"), "transport": (c or {}).get("transport"), "iterations": (c or {}).get("iterations"),
                       "attempts": [{k: a.get(k) for k in ("mode", "status", "width_float", "escalation", "radius")} for a in res["plan"]["queries"][str(q)]["attempts"]] if "queries" in res.get("plan", {}) and str(q) in res["plan"]["queries"] else None}
                if iv:
                    mv = max(max(abs(Fr(r_["exact"][0]) - pi[q][j]), abs(Fr(r_["exact"][1]) - pi[q][j])) for j, r_ in enumerate(iv["coordinates"]))
                    row["max_movement_bound_from_pi"] = float(mv)
                rec["per_query"][str(q)] = row
            rec["clusters"] = res.get("plan", {}).get("clusters"); rec["reductions"] = res.get("plan", {}).get("reductions")
            if truth_p and os.path.exists(truth_p):
                tr = json.load(open(truth_p)).get("truth")
                if tr:
                    fails = 0; n = 0; mvs = []
                    for q in qlist:
                        iv = res["intervals"].get(str(q))
                        if not iv:
                            continue
                        for j, r_ in enumerate(iv["coordinates"]):
                            t = Fr(tr[str(q)][j]); n += 1
                            if not (Fr(int(r_["lo"]), 1 << A.GRID_BITS) <= t <= Fr(int(r_["hi"]), 1 << A.GRID_BITS)):
                                fails += 1
                            mvs.append(abs(t - pi[q][j]))
                    rec["truth_containment"] = {"coordinates": n, "failures": fails}; rec["true_max_movement_from_pi"] = float(max(mvs)) if mvs else None
                    rec["coordinates_moved_more_than_half_width"] = sum(1 for v in mvs if v > Fr(width) / 2)
            # repeated-query costs on the loaded model (same reuse for every mode)
            reps = []
            for _ in range(2):
                t0 = time.monotonic(); r2 = api.solve(m, qs, width, lim); t1 = time.monotonic(); api.verify(m, r2); reps.append({"solve_s": t1 - t0, "solve_plus_verify_s": time.monotonic() - t0})
            rec["timings"]["repeated_query"] = reps
            res_path = out[:-5] + ".result.json"; json.dump(res, open(res_path, "w"), indent=1, default=str); rec["result_file"] = os.path.basename(res_path)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2000:]
    rec["timings"]["child_total_s"] = time.monotonic() - T_START; rec["child_high_water_rss_bytes"] = rss()
    json.dump(rec, open(out, "w"), indent=1, default=str)
    print(json.dumps({k: rec.get(k) for k in ("model", "mode", "width", "status", "verify_accepted")}, default=str), {k: round(v, 3) for k, v in rec["timings"].items() if isinstance(v, float)})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
