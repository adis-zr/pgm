"""Stage A entry point (run as a supervised subprocess)."""
import sys, os, json, time, argparse
from research.campaigns.h4.stagea import h4_fixtures, product_fixtures, negative_controls

ap = argparse.ArgumentParser(); ap.add_argument("--packet", required=True); ap.add_argument("--out", required=True)
a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
res = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
t = time.monotonic(); res["product_fixtures"] = product_fixtures(os.path.join(a.out, "product")); res["product_s"] = time.monotonic() - t
t = time.monotonic(); res["negative_controls"] = negative_controls(a.packet, os.path.join(a.out, "negative")); res["negative_s"] = time.monotonic() - t
t = time.monotonic(); res["h4_fixtures"] = h4_fixtures(a.packet, os.path.join(a.out, "h4")); res["h4_s"] = time.monotonic() - t
res["all_ok"] = (all(x["all_ok"] for x in res["product_fixtures"]) and res["negative_controls"]["all_ok"] and all(x["all_ok"] for x in res["h4_fixtures"]))
res["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
f = open(os.path.join(a.out, "stage_a.json"), "w"); json.dump(res, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close()
print(json.dumps({"all_ok": res["all_ok"], "product": [x["all_ok"] for x in res["product_fixtures"]],
                  "negative": res["negative_controls"]["all_ok"], "h4": [x["all_ok"] for x in res["h4_fixtures"]]}))
sys.exit(0 if res["all_ok"] else 1)
