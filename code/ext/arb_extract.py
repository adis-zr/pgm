"""Extract ARB's final marginals from its trace file.

The released grample writes no MAR file; with --experiment it JSON-encodes each
model.Variable (including its Marginal array) into the trace under the
'// EVIDENCE' and '// VARS (ESTIMATED)' section markers. We read those records
rather than modifying the baseline. Read-only extraction: no repair, no tuning.
"""
from __future__ import annotations
import json, re


def extract(trace_path, nvars, card, ev):
    """Return (rows, meta). rows[v] is the normalized marginal for variable v,
    with observed variables written as point masses per original-task fidelity."""
    text = open(trace_path, "r", errors="replace").read()
    # Sections appear in order; VARS SORTED BY DIST may repeat variables, so we
    # take only the EVIDENCE and VARS (ESTIMATED) blocks and stop at the next marker.
    def block(start_marker):
        i = text.find(start_marker)
        if i < 0:
            return ""
        i += len(start_marker)
        j = len(text)
        for m in ("// VARS (ESTIMATED)", "// VARS SORTED BY DIST FROM HELLINGER",
                  "// OPERATING PARAMS", "// ENTIRE MODEL", "// MERLIN SCORES"):
            k = text.find(m, i)
            if k >= 0:
                j = min(j, k)
        return text[i:j]

    rows = [None] * nvars
    seen_ev, seen_est = 0, 0
    dec = json.JSONDecoder()
    for marker, tag in (("// EVIDENCE", "ev"), ("// VARS (ESTIMATED)", "est")):
        seg = block(marker)
        pos = 0
        while True:
            k = seg.find("{", pos)
            if k < 0:
                break
            try:
                obj, end = dec.raw_decode(seg[k:])
            except ValueError:
                pos = k + 1
                continue
            pos = k + end
            if not isinstance(obj, dict) or "ID" not in obj:
                continue
            vid = obj["ID"]
            if not (0 <= vid < nvars):
                continue
            mar = obj.get("Marginal")
            if mar is None:
                continue
            if rows[vid] is None:
                rows[vid] = [float(x) for x in mar]
                if tag == "ev":
                    seen_ev += 1
                else:
                    seen_est += 1
    meta = {"trace": trace_path, "evidence_records": seen_ev,
            "estimated_records": seen_est,
            "missing": [v for v in range(nvars) if rows[v] is None]}
    # Normalize counts, and write observed variables as exact point masses.
    for v in range(nvars):
        if rows[v] is None:
            continue
        if len(rows[v]) != card[v]:
            meta.setdefault("card_mismatch", []).append(
                {"var": v, "got": len(rows[v]), "want": card[v]})
            continue
        s = sum(rows[v])
        if s > 0:
            rows[v] = [x / s for x in rows[v]]
        meta.setdefault("normalized_sums", []).append(s) if False else None
    for v, st in ev.items():
        pm = [0.0] * card[v]
        pm[st] = 1.0
        if rows[v] is not None:
            # record what ARB itself reported for the observed variable
            meta.setdefault("observed_reported", {})[str(v)] = rows[v]
        rows[v] = pm
    meta["observed_written_as_point_mass"] = sorted(ev)
    return rows, meta
