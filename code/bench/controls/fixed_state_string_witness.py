"""Reviewer's third witness (review of the r2 package): X with unary weights [0,1] (forced to state 1, P(X=1) = 1), Y with [1,3], no evidence.
Honest adapter output; then change ONLY cert['fixed']['0'] from JSON integer 1 to JSON string "1". Reports what the checker and the query
restoration do, for several value variants. usage: python fixed_state_string_witness.py OUT.json"""
import sys, os, json, copy
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from ext import uai as U
from bench import cbi_adapter as AD
from cbi import api

p = "/tmp/xy_forced.uai"; open(p, "w").write("MARKOV\n2\n2 2\n2\n1 0\n1 1\n\n2\n 0 1\n2\n 1 3\n"); open(p + ".evid", "w").write("0\n")
m = U.read_model(p); ev = {}; native, cert = AD.adapt(m, ev); res = api.solve(native, "all", "1/100", {}); out = {"honest_fixed": cert["fixed"]}
for label, val in (("int_1", 1), ("str_1", "1"), ("float_1.0", 1.0), ("fraction_str", "1/1"), ("bool_True", True), ("out_of_range_2", 2), ("negative", -1), ("str_0", "0")):
    c2 = copy.deepcopy(cert); c2["fixed"]["0"] = val
    try:
        AD.check_adapter(p, p + ".evid", native, c2, res); chk = "ACCEPTED"
    except Exception as ex:
        chk = "REJECTED: %s: %s" % (type(ex).__name__, str(ex)[:100])
    try:
        rows = AD.map_intervals(m, ev, c2, res); px = [[float(x) for x in rows[0][s]] for s in range(2)]
    except Exception as ex:
        px = "map_intervals raised %s" % type(ex).__name__
    out[label] = {"checker": chk, "published_P_X": px, "true_P_X": [0.0, 1.0], "false_enclosure": (isinstance(px, list) and not (px[1][0] <= 1.0 <= px[1][1]))}
json.dump(out, open(sys.argv[1], "w"), indent=1, default=str); print(json.dumps(out, indent=1, default=str))
