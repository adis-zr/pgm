"""Thin CLI: python -m cbi.cli solve MODEL.json [--queries all|0,3,5] [--width 1/100] [--out RESULT.json] [--limits '{"max_entries": 1048576}']
              python -m cbi.cli verify MODEL.json RESULT.json"""
import sys, os, json, argparse, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from cbi import model as M, api


def main(argv):
    p = argparse.ArgumentParser(prog="cbi"); sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("solve"); s.add_argument("model"); s.add_argument("--queries", default="all"); s.add_argument("--width", default="1/100"); s.add_argument("--out"); s.add_argument("--limits", default="{}")
    v = sub.add_parser("verify"); v.add_argument("model"); v.add_argument("result")
    a = p.parse_args(argv)
    m = M.Model.load(a.model)
    if a.cmd == "solve":
        qs = "all" if a.queries == "all" else [int(x) for x in a.queries.split(",")]
        t0 = time.monotonic(); res = api.solve(m, qs, a.width, json.loads(a.limits)); el = time.monotonic() - t0
        res["cli_wall_s"] = el
        if a.out:
            json.dump(res, open(a.out, "w"), indent=1, default=str)
        print(json.dumps({"status": res["status"], "per_query": res.get("statuses_per_query"), "max_widths": {q: v["max_width_float"] for q, v in res.get("intervals", {}).items()}, "modes": {q: c["mode"] for q, c in res.get("certificate", {}).items()} if isinstance(res.get("certificate"), dict) and res["status"] not in ("INFEASIBLE",) else res.get("certificate"), "total_solve_s": res["timings"].get("total_solve")}, default=str))
        return 0 if res["status"] == "CERTIFIED" else 1
    res = json.load(open(a.result)); t0 = time.monotonic(); out = api.verify(m, res); out["verify_wall_s"] = time.monotonic() - t0
    print(json.dumps(out, default=str)); return 0 if out["accepted"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
