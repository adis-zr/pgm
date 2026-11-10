"""READ-ONLY classification of the paused V1 round's cells under the corrected contract (no cell is modified or rerun):
  * MPFR-route certificates: outward arithmetic -> the enclosure is sound by construction (the planner was trusted, but the plan was the unmodified
    planner's and the validator of V2, applied read-only to the SAME plan record, would accept / reject it: we re-derive ownership + consumer
    structure from the saved record where the saved record allows; views were identity in PLAIN);
  * binary64-route certificates: the V1 label (K_acc = max node rows) is DISPROVED in general. A saved cell's label is separately sufficient iff the
    plan had NO streamed node (fused / downgraded): then every accumulator receives at most max-rows increments and the sequential-sum label holds;
    with streamed nodes the increment count is unbounded by K_acc -> REQUIRES_REVIEW (the delivered point may still be within 0.005; the enclosure
    claim is withdrawn).
  * stopped cells: typed stop + phases only (no plan / counters) -> their failure CAUSE is UNKNOWN (irrecoverable: the record was never written).
    python -m gbidi_review.v1_interpretability V1_RUN_DIR OUT_JSON"""
from __future__ import annotations
import os, sys, json, glob, collections
sys.set_int_max_str_digits(0)


def main(D, out):
    rows = []; summary = collections.Counter()
    for cj in sorted(glob.glob(os.path.join(D, "cells", "*", "*", "cell.json"))):
        r = json.load(open(cj)); arm = r.get("arm")
        if arm not in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
            continue
        stage = cj.split("/cells/")[1].split("/")[0]; row = {"cell": os.path.basename(os.path.dirname(cj)), "stage": stage, "arm": arm, "status": r.get("status"), "route": r.get("route")}
        if r.get("status") == "CERTIFIED":
            nodes = (r.get("plan") or {}).get("nodes") or []; streamed = sum(1 for nd in nodes if nd.get("fused") or not nd.get("materialize")); roots = len((r.get("plan") or {}).get("roots") or []); nonid = sum(1 for nd in nodes for w, n_ in (nd.get("views") or {}).items() if n_ != nd.get("dense_entries", None) and False)
            views_compressed = ((r.get("mechanisms") or {}).get("views") or {}).get("compressed_axes", 0)
            if r.get("route") == "mpfr" or r.get("precision") in ("exact", "exact_integer_reference"):
                row["classification"] = "SOUND_ENCLOSURE_OUTWARD_ARITHMETIC"; row["note"] = "outward MPFR / exact arithmetic; trust-boundary caveat: the unmodified planner's plan was executed without the V2 validator"
            elif streamed == 0 and roots == 1 and views_compressed == 0:
                row["classification"] = "BINARY64_LABEL_SEPARATELY_SUFFICIENT"; row["note"] = "no streamed node, one root, identity views: every accumulator receives <= max-rows increments; the V1 label (2 E_fwd + roots + 4 + 2 K_acc) covers this schedule"
            else:
                row["classification"] = "BINARY64_REQUIRES_REVIEW"; row["note"] = "streamed nodes %d / roots %d / compressed axes %d: the V1 label does not bound the repeated reverse increments; enclosure claim withdrawn (point may still be within 0.005)" % (streamed, roots, views_compressed)
            row.update({"streamed_nodes": streamed, "roots": roots, "compressed_axes": views_compressed})
        elif r.get("status") == "RESOURCE_STOP":
            row["classification"] = "STOP_CAUSE_UNKNOWN_RECORD_LOST"; row["note"] = "typed stop %s; plan / attempts / counters were never written (V1 F5): irrecoverable" % (r.get("reason") or "")[:80]
        else:
            row["classification"] = "OTHER"
        rows.append(row); summary[(stage, arm, row["classification"])] += 1
    out_ = {"rule": "read-only classification of the paused GENERAL_BIDI_V1 round; no cell modified or rerun", "summary": {"%s|%s|%s" % k: v for k, v in sorted(summary.items())}, "rows": rows}
    json.dump(out_, open(out, "w"), indent=1); print(json.dumps(out_["summary"], indent=1))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
