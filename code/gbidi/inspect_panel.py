"""Read-only source / plan inspection over all 46 accessible cases + 2 unavailable slots for GENERAL_BIDI_V2 (charged; no numerics). Per case: raw
hashes equal the frozen census; shared reductions (the same rules the cells apply) with their step counts; the three candidate orders' completeness
and metadata updates; the chosen plan's totals for GENERAL_BIDI_V2 and NATIVE_PLAIN_V2 (planned dense entries, core entries after views, demanded,
materialized, fused nodes, downgrades, cold-work proxy, peak reserved bytes); mechanism offered/applied counts; the binary64 admission verdict.
Caps identical to the cells (discovery wall = 1 s per arm). A cap reached is UNKNOWN for the remainder.    python -m gbidi.inspect_panel D"""
from __future__ import annotations
import os, sys, json, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from ext import uai as U
from adp import source as SRC
from gbidi import plan as PL, executor as EX, pilot as PI


def main(D):
    man = json.load(open(os.path.join(PI.CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man["cases"]}; rows = []
    for case in PI.inventory():
        c = cases[case]; mp = os.path.join(HERE, c["model_path"]); ep = os.path.join(HERE, c["evidence_path"]); row = {"case": case, "family": c["family"], "accessible": True, "raw_model_sha256_matches": EX.sha_file(mp) == c["raw_model_sha256"], "raw_evidence_sha256_matches": EX.sha_file(ep) == c["raw_evidence_sha256"]}
        t = time.monotonic()
        try:
            m = U.read_model(mp); m.check(); ev = U.read_evidence(ep); row.update({"variables": m.nvars, "factors": len(m.factors), "max_card": max(m.card), "max_arity": max(len(f.scope) for f in m.factors), "evidence": len(ev)})
            R = SRC.Reduced(EX._ModelAdapter(m), dict(ev)); rr = R.reduce(list(PL.COMMON_RULES), deadline=time.monotonic() + 1.0)
            row["reductions"] = {"steps": {k: sum(1 for s in R.steps if s[0] == k) for k in set(s[0] for s in R.steps)}, "recognition": rr, "free_reduced": len(R.dom), "zero_proof": R.zero_proof}
            if R.zero_proof is not None or not R.dom:
                row["plan"] = "NONE_NEEDED"; rows.append(row); continue
            for arm in ("GENERAL_BIDI_V2", "NATIVE_PLAIN_V2"):
                acfg = dict(EX.ARMS[arm]); acfg["bytes_per_entry"] = 2 * (32 + 16); t1 = time.monotonic()
                try:
                    P, table = PL.plan(R, acfg, deadline=time.monotonic() + 1.0); tot = P.totals(); ok64, a64 = EX.binary64_admission(P)
                    row[arm] = {"order": P.order_info["name"], "candidates": [{k: v for k, v in x.items() if k != "totals"} | ({"cold_work": x["totals"]["cold_work_proxy"], "peak_bytes": x["totals"]["peak_reserved_bytes"]} if "totals" in x else {}) for x in table], "totals": tot, "mechanisms": P.mechanisms, "binary64": ok64, "binary64_checks": a64["checks"], "plan_s": time.monotonic() - t1,
                                "largest_core_entries": max(nd.core_entries for nd in P.nodes), "largest_dense_entries": max(nd.dense_entries for nd in P.nodes), "nodes_over_cap_streamed": sum(1 for nd in P.nodes if nd.downgrade), "representable": P.representable() is None}
                except PL.PlanStop as ex:
                    row[arm] = {"state": "PLAN_STOP_" + ex.kind, "reason": ex.reason}
        except Exception as ex:
            row["error"] = "%s: %s" % (type(ex).__name__, str(ex)[:200])
        row["inspection_s"] = time.monotonic() - t; rows.append(row); print(case, row.get("GENERAL_BIDI_V2", {}).get("totals", {}).get("stored_entries"), row.get("NATIVE_PLAIN_V2", {}).get("totals", {}).get("stored_entries"), flush=True)
    for case, fam in PI.UNAVAILABLE:
        rows.append({"case": case, "family": fam, "accessible": False, "status": "INPUT_UNAVAILABLE"})
    json.dump({"rule": "read-only; same caps as the cells; UNKNOWN where capped; this is a plan inspection, not an execution", "rows": rows}, open(os.path.join(D, "PANEL_INSPECTION.json"), "w"), indent=1, default=str)
    print(json.dumps({"rows": len(rows), "hash_mismatches": [r["case"] for r in rows if r.get("accessible") and not (r["raw_model_sha256_matches"] and r["raw_evidence_sha256_matches"])]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
