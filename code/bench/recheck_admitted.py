"""Fresh, independent recheck (review item: 'independently recheck the two distinct admitted external source/native mappings and three primary
native certificates') with the REPAIRED adapter checker and the current native verifier, on the SAVED artifacts (no re-solve)."""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bench import cbi_adapter as AD
from cbi import api
from ext import uai as U


def main(S, outp):
    rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]; out = []
    for r in rows:
        if r["arm"] != "CBI_NATIVE" or r.get("status") not in ("VALID_BUT_TOO_WIDE", "CERTIFIED") or not r.get("out_dir"):
            continue
        od = os.path.join(S, r["out_dir"])
        if not os.path.exists(os.path.join(od, "cbi_result.json")):
            continue
        native = json.load(open(os.path.join(od, "native_model.json"))); cert = json.load(open(os.path.join(od, "adapter_certificate.json"))); res = json.load(open(os.path.join(od, "cbi_result.json")))
        mp = json.load(open(os.path.join(od, "cell.json")))["model"]; ep = json.load(open(os.path.join(od, "cell.json")))["evidence"]
        rec = {"case": r["case"], "stage": r["stage"], "label": r.get("label"), "primary": r.get("label") is None, "out_dir": r["out_dir"]}
        try:
            rec["adapter_check_repaired"] = AD.check_adapter(mp, ep, native, cert, res if res.get("requested_queries") else None); rec["adapter_accepted"] = True
        except AssertionError as ex:
            rec["adapter_accepted"] = False; rec["adapter_reason"] = str(ex)[:200]
        ver = api.verify(native, res); rec["native_verifier_accepted"] = bool(ver["accepted"]); rec["native_verifier_tail"] = ver["reasons"][-1:]
        rec["proofs"] = len(res.get("proofs") or {}); rec["status_saved"] = res["status"]
        out.append(rec); print(r["case"], r["stage"], r.get("label") or "primary", "adapter", rec["adapter_accepted"], "verifier", rec["native_verifier_accepted"])
    json.dump({"note": "saved artifacts rechecked with the repaired adapter checker (prove_forced, exact edge correspondence, structural checks, query binding) and the current native verifier", "results": out}, open(outp, "w"), indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), sys.argv[2])
