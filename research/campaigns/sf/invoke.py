"""ONE invocation in a fresh supervised child. Modes:
  select  PANEL.json r_num r_den eps_num eps_den OUT.json DEADLINE_S   -- the online selector: parse, validate, recognize symmetry,
          overlap scan, scouts, choose, execute the chosen route AND its independent checker, publish (complete cold cost)
  route   PANEL.json r_num r_den ROUTE OUT.json DEADLINE_S             -- a predeclared diagnostic / reference route + its checker
The child never reads any other artifact. Cooperative deadline: long loops poll and stop with status TIMEOUT_COOPERATIVE."""
import sys, os, json, time, resource, hashlib
T_START = time.monotonic()
from fractions import Fraction as Fr
from pgm.algorithms.sf import core as C, routes as RT, check as CK


class Cooperative(Exception):
    pass


def main(argv):
    mode = argv[0]; panel = argv[1]; r = Fr(int(argv[2]), int(argv[3]))
    if mode == "select":
        eps = Fr(int(argv[4]), int(argv[5])); route_arg = None; out = argv[6]; deadline_s = float(argv[7])
    else:
        eps = None; route_arg = argv[4]; out = argv[5]; deadline_s = float(argv[6])
    t_end = T_START + deadline_s
    def dl():
        if time.monotonic() > t_end:
            raise Cooperative("cooperative deadline %.1f s reached" % deadline_s)
    rec = {"mode": mode, "panel": os.path.basename(panel), "r": str(r), "r_label": C.r_label(r), "eps": (str(eps) if eps else None), "requested_route": route_arg, "status": "STARTED",
           "phases_s": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        t0 = time.monotonic()
        law = C.Law.load(panel)
        rec["input_sha256"] = law.sha256; rec["n"] = law.n; rec["mA"] = law.mA; rec["mB"] = law.mB; rec["A0"] = law.A0; rec["B0"] = law.B0
        rec["phases_s"]["parse_validate"] = time.monotonic() - t0
        t0 = time.monotonic(); sym, how = law.antipodal(); rec["symmetry"] = {"antipodal_A": sym, "how": how}; rec["phases_s"]["recognition"] = time.monotonic() - t0
        t0 = time.monotonic(); Pint, ninter = law.overlap_int(); rec["overlap"] = {"P0": str(Fr(Pint, law.A0 * law.B0)), "P0_float": float(Fr(Pint, law.A0 * law.B0)), "intersection_rows": ninter}; rec["phases_s"]["overlap_scan"] = time.monotonic() - t0
        pi_num = law.pi_plus_int(); rec["pi_plus"] = [str(Fr(x, law.A0)) for x in pi_num]
        if mode == "select":
            t0 = time.monotonic(); route, params, dec = C.select(law, r, eps, sym, Pint); rec["selection"] = dec; rec["phases_s"]["selection"] = time.monotonic() - t0
        else:
            route = route_arg; params = {}
            if route == "E" or route == "W" or route == "PI" or route[0] in "SF":
                pass
            rec["selection"] = None
        rec["route"] = route; rec["params"] = params
        if route == "REJECT":
            rec["status"] = "REJECT"; rec["reason"] = rec["selection"]["reason"]; raise SystemExit(0)
        if route[0] == "S" and r == 1 and Pint <= 0:
            rec["status"] = "REJECT"; rec["reason"] = "r = 1 with empty intersection: undefined law"; raise SystemExit(0)
        if route == "W":
            ok, info = C.W_admitted(law.n, law.mA); rec["W_admission"] = {"admitted": ok, **info}
            if not ok:
                rec["status"] = "NOT_ADMITTED"; rec["reason"] = "W not admitted by its frozen resource rule"; raise SystemExit(0)
        t0 = time.monotonic(); res = RT.run_route(law, r, route, params, sym, deadline=dl); rec["phases_s"]["route_total"] = time.monotonic() - t0
        rec["route_walls_s"] = res.get("wall"); rec["max_bits"] = res.get("max_bits")
        if res["status"] != "OK":
            rec["status"] = res["status"]; rec["reason"] = res.get("reason"); rec["route_record"] = {k: v for k, v in res.items() if k not in ("intervals", "N_int", "Mk_int", "beta_int", "wall")}; raise SystemExit(0)
        # publication
        t0 = time.monotonic()
        pub = [C.publish(lo, hi) for lo, hi in res["intervals"]]
        res["published"] = pub
        widths = [C.width_of(lg, hg) for lg, hg in pub]
        rec["published"] = [[str(lg), str(hg)] for lg, hg in pub]; rec["intervals_exact"] = [[str(lo), str(hi)] for lo, hi in res["intervals"]]
        rec["max_width"] = str(max(widths)); rec["max_width_float"] = float(max(widths))
        rec["width_met"] = {str(e): bool(max(widths) <= e) for e in C.WIDTHS}
        rec["phases_s"]["publication"] = time.monotonic() - t0
        # route data for the checker and the report
        keep = {k: (str(v) if isinstance(v, (int, Fr)) and not isinstance(v, bool) else v) for k, v in res.items() if k not in ("intervals", "published", "wall", "beta_int")}
        for k in ("N_int", "Mk_int"):
            if k in res:
                keep[k] = [str(x) for x in res[k]]
        rec["route_record"] = keep
        # independent checker (separate code; raw input re-read)
        t0 = time.monotonic()
        law2 = C.Law.load(panel)
        try:
            chk = CK.check(law2, r, res, sym); rec["checker"] = {"status": "VERIFIED", **chk}
        except CK.CheckFailure as e:
            rec["checker"] = {"status": "FAILED", "reason": str(e)}
        rec["phases_s"]["checker"] = time.monotonic() - t0
        # movement diagnostic vs the ignore-bridge marginals (from the exact intervals' midpoints when exact; else the interval)
        mv = []
        for i, (lo, hi) in enumerate(res["intervals"]):
            p0 = Fr(pi_num[i], law.A0)
            mv.append(float(max(abs(Fr(lo) - p0), abs(Fr(hi) - p0))))
        rec["max_movement_bound_from_pi"] = max(mv)
        rec["status"] = "OK" if rec["checker"]["status"] == "VERIFIED" else "CHECK_FAILED"
    except SystemExit:
        pass
    except Cooperative as e:
        rec["status"] = "TIMEOUT_COOPERATIVE"; rec["reason"] = str(e)
    except Exception as e:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(e).__name__, e); rec["traceback"] = traceback.format_exc()[-2500:]
    rec["child_wall_s"] = time.monotonic() - T_START
    rec["producer_only_s"] = rec["child_wall_s"] - rec["phases_s"].get("checker", 0.0)
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["child_high_water_rss_bytes"] = int(ru) if sys.platform == "darwin" else int(ru) * 1024
    rec["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(rec, fh, indent=1, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, out)
    print(json.dumps({k: rec.get(k) for k in ("panel", "r_label", "eps", "route", "status", "max_width_float", "child_wall_s")}, default=str))
    return 0 if rec["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
