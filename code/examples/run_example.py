"""Usage example from outside the experiment harness: solve all singleton marginals of a supplied model file, verify, print."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cbi import model as M, api

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "example_model.json")
m = M.Model.load(path)
res = api.solve(m, queries="all", requested_width="1/100")
chk = api.verify(m, res)
print("status:", res["status"], "| verifier:", "accepted" if chk["accepted"] else "REJECTED")
for q, iv in sorted(res["intervals"].items(), key=lambda kv: int(kv[0])):
    c = res["certificate"][q]
    print("block %s  mode %-18s max width %.3g  region %s" % (q, c["mode"], iv["max_width_float"], c["H"]))
    row = iv["coordinates"][0]; print("   coordinate 0: P(x_0 = +1) in [%.6f, %.6f]" % (int(row["lo"]) / 2 ** 80, int(row["hi"]) / 2 ** 80))
