"""AMENDMENT 1 (prospective, recorded before any rerun): PGMax wrapper compatibility fix -- PGMax refuses two EnumFactors on the same
variable set ("already exists. Please merge the corresponding factors"); the wrapper now multiplies identical-scope sliced tables entrywise
in exact rationals before forming log-potentials (an exact operation; no algorithm choice). Scope: PGMAX_SUMPRODUCT_BP cells only. Procedure:
record the amendment with the list of affected FAILED breadth cells (reason text matched), patch bench/pgmax_mar.py, re-freeze the manifest's
code hash (same cells, same ids except the code-hash component), rerun ONLY the affected cells with label "amendment_1_rerun"; the original
rows stay in the ledger and the report shows both.
    python bench/amend_pgmax.py SWEEP_DIR record|rerun"""
import os, sys, json, time, hashlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bench import campaign as C

NEEDLE = "already exists. Please merge the corresponding factors"


def affected(S):
    rows = C.ledger_rows(S); out = []
    for r in rows:
        if r["arm"] != "PGMAX_SUMPRODUCT_BP" or r.get("label") is not None or r.get("status") != "FAILED":
            continue
        log = os.path.join(S, r["out_dir"], "pgmax.log")
        if os.path.exists(log) and NEEDLE in open(log, errors="replace").read():
            out.append(r)
    return out


def main(S, mode):
    ap = os.path.join(S, "AMENDMENTS.json"); A = json.load(open(ap)) if os.path.exists(ap) else {}
    if mode == "record":
        aff = affected(S)
        A["amendment_1"] = {"when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "wrapper compatibility (PGMax arm only)",
                            "what": "bench/pgmax_mar.py merges identical-scope factors entrywise (exact rationals) before building EnumFactorGroups; PGMax rejects duplicate factor scopes. No algorithm, temperature, iteration count, damping or input change.",
                            "exposed_before_amendment": [{"cell_id": r["cell_id"], "case": r["case"], "stage": r["stage"], "status": r["status"]} for r in aff],
                            "action": "affected cells rerun ONCE with label amendment_1_rerun under the same budgets; original rows retained; depth stage runs with the amended wrapper (no depth outcome existed when recorded)",
                            "code_hash_before": json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json")))["code_hash"]}
        json.dump(A, open(ap, "w"), indent=1); print("recorded amendment_1 with %d affected cells" % len(aff))
    elif mode == "rerun":
        man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); cfgp = os.path.join(S, "CONFIG.json")
        ch, _ = C.code_hash(); assert ch == man["code_hash"], "manifest not re-frozen after the patch"
        A["amendment_1"]["code_hash_after"] = ch; A["amendment_1"]["reruns"] = []
        for e in A["amendment_1"]["exposed_before_amendment"]:
            cell = next(c for c in man["cells"] if c["case"] == e["case"] and c["arm"] == "PGMAX_SUMPRODUCT_BP" and c["stage"] == e["stage"])
            r = C.run_cell(S, cell, cfgp, cell["stage"], label_extra="amendment_1_rerun")
            A["amendment_1"]["reruns"].append({k: r.get(k) for k in ("cell_id", "case", "stage", "status", "supervisor_wall_s", "out_dir")}); print(e["case"], r["status"], round(r["supervisor_wall_s"], 2))
        json.dump(A, open(ap, "w"), indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), sys.argv[2])
