"""Fresh, independent recheck of every DISTINCT saved native artifact directory (review of the r2 package: count directories, not ledger rows)
with the repaired adapter checker bound to each directory's own invocation contract (complete MAR = all unobserved variables; a diagnostic
single-query directory = its prescribed variable) and the current native verifier. No re-solve."""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bench import cbi_adapter as AD
from cbi import api
from ext import uai as U


def main(S, outp):
    rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]; dirs = {}
    for r in rows:
        if r["arm"] != "CBI_NATIVE" or not r.get("out_dir"):
            continue
        od = os.path.join(S, r["out_dir"])
        if os.path.exists(os.path.join(od, "cbi_result.json")):
            dirs.setdefault(r["out_dir"], []).append({"cell_id": r["cell_id"], "stage": r["stage"], "label": r.get("label"), "status": r.get("status")})
    out = []
    for od_rel, ledger_rows in sorted(dirs.items()):
        od = os.path.join(S, od_rel); cell = json.load(open(os.path.join(od, "cell.json")))
        native = json.load(open(os.path.join(od, "native_model.json"))); cert = json.load(open(os.path.join(od, "adapter_certificate.json"))); res = json.load(open(os.path.join(od, "cbi_result.json")))
        mp, ep = cell["model"], cell["evidence"]; m = U.read_model(mp); ev = U.read_evidence(ep)
        contract = [cell["single_query_var"]] if cell.get("single_query_var") is not None else [v for v in range(m.nvars) if v not in ev]
        rec = {"out_dir": od_rel, "case": cell.get("model", "").split("/")[-1].replace(".uai", ""), "ledger_rows": ledger_rows, "ledger_row_count": len(ledger_rows), "contract": ("single query var %d" % contract[0]) if len(contract) == 1 else "complete MAR (%d unobserved)" % len(contract),
               "overwritten_history": len(ledger_rows) > 1}
        try:
            rec["adapter_check"] = AD.check_adapter(mp, ep, native, cert, res, expected_queries=contract); rec["adapter_accepted"] = True
        except (AssertionError, AD.BadCertificate) as ex:
            rec["adapter_accepted"] = False; rec["adapter_reason"] = str(ex)[:200]
        ver = api.verify(native, res); rec["native_verifier_accepted"] = bool(ver["accepted"]); rec["native_verifier_tail"] = ver["reasons"][-1:]
        rec["saved_status"] = res["status"]; rec["proofs"] = len(res.get("proofs") or {})
        out.append(rec); print("%-95s rows=%d adapter=%s verifier=%s %s" % (od_rel[-95:], len(ledger_rows), rec["adapter_accepted"], rec["native_verifier_accepted"], rec["contract"]))
    json.dump({"note": "every DISTINCT saved native artifact directory (ledger rows per directory listed; the overwritten first-pass diagnostic directory carries several rows whose original artifacts are LOST)", "distinct_directories": len(out), "ledger_rows_total": sum(len(d) for d in dirs.values()),
               "all_adapter_accepted": all(r["adapter_accepted"] for r in out), "all_verifier_accepted": all(r["native_verifier_accepted"] for r in out), "results": out}, open(outp, "w"), indent=1)
    print("distinct directories", len(out), "| ledger rows", sum(len(d) for d in dirs.values()))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), sys.argv[2])
