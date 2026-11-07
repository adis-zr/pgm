"""Reviewer's two adapter witnesses (review of MDI_EXTERNAL_SWEEP_2026-11-06.zip): X, Y independent binary, unaries [1,3], no evidence,
true P(X=1) = P(Y=1) = 3/4, Z = 16.  (A) honest certificate + an ADDED native edge r = 1/2 -> native P(X=1) = 5/6.  (B) INVENTED fixed X = 0
-> published [0,0] for P(X=1).  Prints whether cbi.verify and bench.cbi_adapter.check_adapter accept each. usage: python adapter_false_accepts.py OUT.json"""
import sys, os, json, copy
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from ext import uai as U
from bench import cbi_adapter as AD
from cbi import api

def write(path):
    open(path, "w").write("MARKOV\n2\n2 2\n2\n1 0\n1 1\n\n2\n 1 3\n2\n 1 3\n"); open(path + ".evid", "w").write("0\n")

def run(path):
    m = U.read_model(path); ev = U.read_evidence(path + ".evid"); native, cert = AD.adapt(m, ev); out = {}
    # ---- A: added edge
    bad = copy.deepcopy(native); bad["edges"].append({"u": 0, "v": 1, "r": "1/2"})
    res = api.solve(bad, "all", "1/100", {}); ver = api.verify(bad, res)
    try:
        AD.check_adapter(path, path + ".evid", bad, cert, res); chk = "ACCEPTED"
    except AssertionError as ex:
        chk = "REJECTED: " + str(ex)[:120]
    rows = AD.map_intervals(m, ev, cert, res); px1 = [float(x) for x in rows[0][1]]
    out["A_added_edge"] = {"native_status": res["status"], "native_verifier": ver["accepted"], "adapter_checker": chk, "published_P_X1": px1, "true_P_X1": 0.75, "false_enclosure": not (px1[0] <= 0.75 <= px1[1])}
    # ---- B: invented fixation X = 0
    cert2 = copy.deepcopy(cert); cert2["fixed"] = {"0": 0}; cert2["free"] = [1]; cert2["flip"] = {"1": 0}; cert2["consumed"] = [c for c in cert2["consumed"] if c.get("var") != 0] + [{"factor": 0, "role": "constant", "value": "1", "fixed_at": {"0": 0}}]
    nat2 = {"d": 1, "bit_convention": native["bit_convention"], "blocks": [b for b in native["blocks"] if b["id"] == 1], "edges": [], "meta": native["meta"]}
    res2 = api.solve(nat2, "all", "1/100", {}); ver2 = api.verify(nat2, res2)
    try:
        AD.check_adapter(path, path + ".evid", nat2, cert2, res2); chk2 = "ACCEPTED"
    except AssertionError as ex:
        chk2 = "REJECTED: " + str(ex)[:120]
    rows2 = AD.map_intervals(m, ev, cert2, res2); px1b = [float(x) for x in rows2[0][1]]
    out["B_invented_fixation"] = {"native_status": res2["status"], "native_verifier": ver2["accepted"], "adapter_checker": chk2, "published_P_X1": px1b, "true_P_X1": 0.75, "false_enclosure": not (px1b[0] <= 0.75 <= px1b[1])}
    return out

if __name__ == "__main__":
    p = "/tmp/xy_indep.uai"; write(p); out = run(p); json.dump(out, open(sys.argv[1], "w"), indent=1); print(json.dumps(out, indent=1))
