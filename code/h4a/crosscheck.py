"""Post-repetition cross-check: compare the saved C/PI/PP node-marker-frequency enclosures and responses using exact
saved endpoints, and require the saved 320-bit C-checker interval to be contained in each point publication."""
import sys, os, json, argparse
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.certs import fb, fx, E_PUB, E_CH, E_INT

ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
RUN = a.run_dir; res = {"repetitions": []}
for rep in (1, 2, 3):
    rr = {"repetition": rep, "nodes": []}
    for nd in sorted(os.listdir(os.path.join(RUN, "bundles", f"rep{rep}_C"))):
        p = os.path.join(RUN, "bundles", f"rep{rep}_C", nd)
        if not os.path.isdir(p): continue
        C = json.load(open(os.path.join(p, "prod.json")))          # 256-bit rect producer
        Cc = json.load(open(os.path.join(p, "chk.json")))          # 320-bit rect checker
        PI = json.load(open(os.path.join(RUN, "bundles", f"rep{rep}_PI", nd, "prod.json")))
        PP = json.load(open(os.path.join(RUN, "bundles", f"rep{rep}_PP", nd, "prod.json")))
        PPc = json.load(open(os.path.join(RUN, "bundles", f"rep{rep}_PP", nd, "chk.json")))
        cint = {(d["k"], d["marker"]): ((fx(d["re"][0]), fx(d["re"][1])), (fx(d["im"][0]), fx(d["im"][1]))) for d in Cc["channels"]}
        pub = {}
        for d in C["channels"]:
            re = (fx(d["re"][0]), fx(d["re"][1])); im = (fx(d["im"][0]), fx(d["im"][1]))
            pub[(d["k"], d["marker"], "re")] = ((re[0] + re[1]) / 2 - E_PUB, (re[0] + re[1]) / 2 + E_PUB)
            pub[(d["k"], d["marker"], "im")] = ((im[0] + im[1]) / 2 - E_PUB, (im[0] + im[1]) / 2 + E_PUB)
        for J, nm in ((PI, "PI"), (PP, "PP")):
            for d in J["channels"]:
                pub[(d["k"], d["marker"], "re", nm)] = (fb(d["re"]) - E_PUB, fb(d["re"]) + E_PUB)
                pub[(d["k"], d["marker"], "im", nm)] = (fb(d["im"]) - E_PUB, fb(d["im"]) + E_PUB)
        bad = {"C": 0, "PI": 0, "PP": 0}
        for (k, mk), (re, im) in cint.items():
            for comp, iv in (("re", re), ("im", im)):
                if not (pub[(k, mk, comp)][0] <= iv[0] and iv[1] <= pub[(k, mk, comp)][1]): bad["C"] += 1
                for nm in ("PI", "PP"):
                    q = pub[(k, mk, comp, nm)]
                    if not (q[0] <= iv[0] and iv[1] <= q[1]): bad[nm] += 1
        # agreement of the three producers' values within the channel ceiling
        cmid = {(d["k"], d["marker"]): (fx(d["re"][0]) + fx(d["re"][1])) / 2 for d in C["channels"]}
        pim = {(d["k"], d["marker"]): fb(d["re"]) for d in PI["channels"]}
        ppm = {(d["k"], d["marker"]): fb(d["re"]) for d in PP["channels"]}
        worst = max(max(abs(cmid[k] - pim[k]), abs(cmid[k] - ppm[k]), abs(pim[k] - ppm[k])) for k in cmid)
        rr["nodes"].append({"node": nd, "C_checker_in_C_pub_violations": bad["C"], "C_checker_in_PI_pub_violations": bad["PI"],
                            "C_checker_in_PP_pub_violations": bad["PP"], "channels": len(cint) * 2,
                            "worst_cross_arm_channel_gap": str(worst), "within_2E_ch": worst <= 2 * E_CH,
                            "PI_equals_PP_bitwise": all(pim[k] == ppm[k] for k in pim)})
    rr["all_ok"] = all(n["C_checker_in_C_pub_violations"] == 0 and n["C_checker_in_PI_pub_violations"] == 0
                       and n["C_checker_in_PP_pub_violations"] == 0 and n["within_2E_ch"] and n["PI_equals_PP_bitwise"] for n in rr["nodes"]) and len(rr["nodes"]) == 6
    res["repetitions"].append(rr)
res["all_ok"] = all(r["all_ok"] for r in res["repetitions"])
f = open(os.path.join(a.out, "crosscheck.json"), "w"); json.dump(res, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close()
print(json.dumps({"all_ok": res["all_ok"], "per_rep": [r["all_ok"] for r in res["repetitions"]]}))
sys.exit(0 if res["all_ok"] else 1)
