"""Structural-refusal aggregation with representative witnesses (spec section 9): for every CBI_NATIVE UNSUPPORTED_REPRESENTATION cell,
classify the adapter's precise reason, count per family, and keep ONE small witness per blocker class (the smallest offending factor, its scope,
cardinalities and table excerpt) re-derived from the raw model so a reader can see the obstruction. Also tabulates MDI engine refusals by typed
reason. Writes BLOCKERS.json.    python bench/blockers.py SWEEP_DIR"""
import os, sys, json, re, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from ext import uai as U

CLASSES = ["nonbinary domains", "remaining high arity", "incompatible zero pattern", "non-product interaction", "nonsquare rational cross-ratio", "inconsistent sign gauges", "unsupported number representation", "adapter work limit", "other"]


def classify(reason):
    for c in CLASSES:
        if reason.startswith(c):
            return c
    return "other"


def witness(S, case, inv, reason, cls):
    row = inv[case]; m = U.read_model(os.path.join(S, row.get("committed_model_path", row["model_path"]))); ev = U.read_evidence(os.path.join(S, row.get("committed_evidence_path", row["evidence_path"])))
    if cls == "nonbinary domains":
        mm = re.search(r"variable (\d+) has (\d+) states", reason)
        v = int(mm.group(1)) if mm else next(v for v in range(m.nvars) if m.card[v] != 2 and v not in ev)
        return {"variable": v, "states": m.card[v], "domain_histogram": row["structure"]["domain_histogram"]}
    if cls == "remaining high arity":
        mm = re.search(r"factor (\d+) keeps (\d+) free", reason); fi = int(mm.group(1)); f = m.factors[fi]
        return {"factor": fi, "scope": list(f.scope), "cards": list(f.card), "free_after_slicing": [v for v in f.scope if v not in ev], "table_excerpt": [str(x) for x in f.table[:8]], "table_entries": f.size()}
    if cls in ("nonsquare rational cross-ratio", "inconsistent sign gauges", "incompatible zero pattern"):
        mm = re.search(r"\((\d+),(\d+)\)", reason); u, v = (int(mm.group(1)), int(mm.group(2))) if mm else (None, None)
        fs = [f for f in m.factors if set(f.scope) == {u, v}] if u is not None else []
        out = {"pair": [u, v], "factors": [{"index": f.index, "scope": list(f.scope), "table": [str(x) for x in f.table]} for f in fs[:2]]}
        if cls == "nonsquare rational cross-ratio" and fs and len(fs[0].table) == 4:
            a, b, c, d = fs[0].table; out["cross_ratio"] = str((a * d) / (b * c))
        if cls == "inconsistent sign gauges":
            out["note"] = "pairwise cross-ratios > 1 (attractive) and < 1 (repulsive) around a cycle with odd repulsive count: no global state relabelling makes every table attractive-form, so the single-sign product kernel K_r cannot represent the model exactly"
            pairs = [f for f in m.factors if len(f.scope) == 2 and f.card == (2, 2) and all(x > 0 for x in f.table)]
            att = sum(1 for f in pairs if (f.table[0] * f.table[3]) > (f.table[1] * f.table[2])); rep = sum(1 for f in pairs if (f.table[0] * f.table[3]) < (f.table[1] * f.table[2]))
            out["attractive_pairs"] = att; out["repulsive_pairs"] = rep; out["separable_pairs"] = len(pairs) - att - rep
        return out
    return {"reason": reason[:300]}


def main(S):
    rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]; inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    out = {"cbi_native": {"by_class": collections.Counter(), "by_family_class": collections.defaultdict(collections.Counter), "witnesses": {}, "cases": {}}, "mdi_existing": {"by_typed_reason": collections.Counter(), "by_family": collections.defaultdict(collections.Counter), "examples": {}}}
    for r in rows:
        if r.get("label") is not None or r["stage"] != "breadth":
            continue
        cj = os.path.join(S, r.get("out_dir") or "", "cell.json"); d = json.load(open(cj)) if os.path.exists(cj) else {}
        if r["arm"] == "CBI_NATIVE" and r["status"] == "UNSUPPORTED_REPRESENTATION":
            reason = str(d.get("reason") or r.get("reason") or ""); cls = classify(reason)
            out["cbi_native"]["by_class"][cls] += 1; out["cbi_native"]["by_family_class"][r["family"]][cls] += 1; out["cbi_native"]["cases"][r["case"]] = {"class": cls, "reason": reason[:240]}
            if cls not in out["cbi_native"]["witnesses"]:
                try:
                    out["cbi_native"]["witnesses"][cls] = {"case": r["case"], "family": r["family"], **witness(S, r["case"], inv, reason, cls)}
                except Exception as ex:
                    out["cbi_native"]["witnesses"][cls] = {"case": r["case"], "error": str(ex)[:120]}
        if r["arm"] == "MDI_EXISTING" and r["status"] not in ("CERTIFIED", "VALID_BUT_TOO_WIDE"):
            reason = str(d.get("reason") or r.get("reason") or ""); typed = d.get("mdi_outcome") or r["status"]
            key = re.search(r"(CHECKER_[A-Z_]+|no generic ordering fits the byte cap|REFUSED|ZERO|PRICE|RESOURCE)", reason); key = (typed + ": " + (key.group(1) if key else reason[:60]))
            out["mdi_existing"]["by_typed_reason"][key] += 1; out["mdi_existing"]["by_family"][r["family"]][key] += 1
            out["mdi_existing"]["examples"].setdefault(key, {"case": r["case"], "reason": reason[:400]})
    for k in ("by_class",):
        out["cbi_native"][k] = dict(out["cbi_native"][k])
    out["cbi_native"]["by_family_class"] = {f: dict(c) for f, c in out["cbi_native"]["by_family_class"].items()}
    out["mdi_existing"]["by_typed_reason"] = dict(out["mdi_existing"]["by_typed_reason"]); out["mdi_existing"]["by_family"] = {f: dict(c) for f, c in out["mdi_existing"]["by_family"].items()}
    json.dump(out, open(os.path.join(S, "BLOCKERS.json"), "w"), indent=1, default=str)
    print("CBI blockers:", out["cbi_native"]["by_class"]); print("MDI refusals:", out["mdi_existing"]["by_typed_reason"])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
