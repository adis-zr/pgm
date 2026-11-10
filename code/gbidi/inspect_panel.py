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
    """every row through gbidi.executor.plan_only: EXACTLY the cell policy (snapshot, shared reductions + planning allowance min(1 s, 0.05 x 20 s),
    kernel bytes per entry, trusted snapshot, validation); read-only; the record says what was skipped / capped per node"""
    man = json.load(open(os.path.join(PI.CENSUS_D, "CENSUS_MANIFEST.json"))); cases = {c["case"]: c for c in man["cases"]}; rows = []
    for case in PI.inventory():
        c = cases[case]; mp = os.path.join(HERE, c["model_path"]); ep = os.path.join(HERE, c["evidence_path"]); row = {"case": case, "family": c["family"], "accessible": True, "raw_model_sha256_matches": EX.sha_file(mp) == c["raw_model_sha256"], "raw_evidence_sha256_matches": EX.sha_file(ep) == c["raw_evidence_sha256"]}
        t = time.monotonic()
        for arm in ("GENERAL_BIDI_V2", "NATIVE_PLAIN_V2"):
            try:
                r = EX.plan_only(arm, mp, ep, 20.0); row.setdefault("reductions", r.get("reductions"))
                if r.get("plan") == "NONE_NEEDED" or isinstance(r.get("plan"), str):
                    row[arm] = {"plan": r.get("plan")}; continue
                if isinstance(r.get("plan"), dict) and "state" in r["plan"]:
                    row[arm] = r["plan"]; continue
                P = r["plan"]; tot = P["totals"]; row[arm] = {"order": P["order"]["name"], "candidates": [{k: x.get(k) for k in ("order", "state", "baseline", "chosen", "mandatory_representable", "mandatory_not_representable_reason", "discovery_stop")} for x in r["plan_candidates"]], "totals": tot, "mechanisms": r["mechanisms"], "validation": r.get("plan_validation"), "binary64": (r.get("binary64_admission") or {}).get("checks"), "plan_s": r.get("plan_s"),
                            "largest_core_entries": max(nd["core_entries"] for nd in P["nodes"]), "nodes_streamed": sum(1 for nd in P["nodes"] if nd["fused"]), "support_prov": dict(__import__("collections").Counter(nd["support_prov"] for nd in P["nodes"])), "view_prov": dict(__import__("collections").Counter(p for nd in P["nodes"] for p in nd["view_prov"].values())), "discovery_stop": P.get("discovery_stop")}
            except Exception as ex:
                row[arm] = {"error": "%s: %s" % (type(ex).__name__, str(ex)[:200])}
        row["inspection_s"] = time.monotonic() - t; rows.append(row); print(case, (row.get("GENERAL_BIDI_V2") or {}).get("order"), (row.get("GENERAL_BIDI_V2") or {}).get("discovery_stop"), (row.get("NATIVE_PLAIN_V2") or {}).get("order"), flush=True)
    for case, fam in PI.UNAVAILABLE:
        rows.append({"case": case, "family": fam, "accessible": False, "status": "INPUT_UNAVAILABLE"})
    json.dump({"rule": "read-only; gbidi.executor.plan_only = the cell's own policy entry point (shared reductions + planning allowance, kernel bytes per entry, trusted snapshot, validation); no numerics; per-node provenance says what was skipped", "rows": rows}, open(os.path.join(D, "PANEL_INSPECTION.json"), "w"), indent=1, default=str)
    print(json.dumps({"rows": len(rows), "hash_mismatches": [r["case"] for r in rows if r.get("accessible") and not (r["raw_model_sha256_matches"] and r["raw_evidence_sha256_matches"])]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
