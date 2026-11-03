"""Post-publication diagnostics for a six-cell comparison run (contract SS6): run ONLY after every
cell has finished. Extracts the packet's `.MAR` references into a directory OUTSIDE the solver input
directory and, for every attempt that published, reports (a) containment of each rounded reference
value in the published enclosure and (b) the Hellinger discrepancy of the declared point vector
(`point_<label>.MAR`, chosen without reference answers). Neither grants nor revokes certification.

    python -m ext.score_cells RUNDIR PACKET.zip [REFDIR]
"""
from __future__ import annotations
import os, sys, json, zipfile, glob
from fractions import Fraction as Fr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import uai, score

PROBLEMS = ("Grids_11", "Pedigree_11", "Promedus_12")


def extract_refs(packet, refdir):
    os.makedirs(refdir, exist_ok=True)
    out = {}
    with zipfile.ZipFile(packet) as z:
        for p in PROBLEMS:
            member = "three_external_problems/inputs/%s.uai.MAR" % p
            dest = os.path.join(refdir, "%s.uai.MAR" % p)
            with z.open(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            out[p] = dest
    return out


def containment(intervals_rows, ref_rows, ev, dec=None):
    """Every published (var, state) with the reference value inside [lo, hi]; the reference
    is a rounded decimal, so a second count admits a half-unit-in-the-last-place slack."""
    inside = outside = inside_slack = total = 0
    worst = None
    for row in intervals_rows:
        v = row["var"]
        if v in ev:
            continue
        for a, (lo, hi) in enumerate(row["intervals"]):
            lo, hi = Fr(lo), Fr(hi)
            q = ref_rows[v][a]
            total += 1
            if lo <= q <= hi:
                inside += 1; inside_slack += 1
                continue
            outside += 1
            d = max(lo - q, q - hi)
            s = str(q)
            places = len(s.split(".")[1]) if "." in s else 0
            if d <= Fr(1, 2 * 10 ** places):
                inside_slack += 1
            if worst is None or d > worst[0]:
                worst = (d, v, a, str(lo), str(hi), str(q))
    return {"coordinates": total, "inside": inside, "outside": outside, "inside_with_half_ulp_slack": inside_slack,
            "worst_excursion": (None if worst is None else {"distance": str(worst[0]), "var": worst[1], "state": worst[2],
                                                            "interval": [worst[3], worst[4]], "reference": worst[5]})}


def score_run(rundir, packet, refdir=None, input_dir="/tmp/tep/three_external_problems/inputs"):
    refdir = refdir or os.path.join(rundir, "references_read_after_all_cells")
    assert os.path.realpath(refdir) != os.path.realpath(input_dir), "references must not enter the solver input directory"
    led = json.load(open(os.path.join(rundir, "LEDGER.json")))
    pending = [c["label"] for c in led["cells"] if c["status"] not in ("CONSUMED", "NOT_RUN_CUMULATIVE_STOP")]
    assert not pending, "cells still pending: %s -- the scorer runs only after every invocation" % pending
    refs = extract_refs(packet, refdir)
    out = {"note": "post-publication empirical diagnostics (contract SS6); references read AFTER every cell finished, from %s; "
                   "they neither grant nor revoke certification" % refdir, "cells": {}}
    for c in led["cells"]:
        label, problem = c["label"], c["problem"]
        rows = {"status": c["status"], "attempts": []}
        for i, att in enumerate(c["attempts"], 1):
            adir = os.path.join(rundir, "cells", label, "attempt_%d" % i)
            rec = {"attempt": i, "class": att.get("class"), "arm_outcome": att.get("arm_outcome"), "charged_s": att.get("charged_s")}
            pm = os.path.join(adir, "point_%s.MAR" % label)
            iv = os.path.join(adir, "intervals_%s.json" % label)
            if not (os.path.exists(pm) and os.path.exists(iv)):
                rec["diagnostics"] = "not applicable: nothing published"
                rows["attempts"].append(rec); continue
            m = uai.read_model(os.path.join(input_dir, problem + ".uai"))
            ev = uai.read_evidence(os.path.join(input_dir, problem + ".uai.evid"))
            ref, _raw = uai.read_mar(refs[problem])
            pts, _ = uai.read_mar(pm)
            iss = score.validate_output(pts, m, ev, "point vector")
            s = score.score(pts, ref, m, ev)
            s.pop("per_var")
            rec["point_vector"] = {"file": pm, "validation_issues": iss, **s}
            rec["containment"] = containment(json.load(open(iv)), ref, ev)
            rec["reference_rounding_worst_row_sum_defect"] = str(score.ref_rounding_report(ref))
            rows["attempts"].append(rec)
        out["cells"][label] = rows
    json.dump(out, open(os.path.join(rundir, "SCORES.json"), "w"), indent=1, default=str)
    return out


if __name__ == "__main__":
    rd, pk = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    rf = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else None
    r = score_run(rd, pk, rf)
    for lab, c in r["cells"].items():
        for a in c["attempts"]:
            if "point_vector" in a:
                print("%-24s attempt %d %-22s maxH %.6f meanH %.6f | containment %d/%d inside (%d with half-ulp slack)" % (
                    lab, a["attempt"], a["arm_outcome"], a["point_vector"]["max_hellinger"], a["point_vector"]["mean_hellinger"],
                    a["containment"]["inside"], a["containment"]["coordinates"], a["containment"]["inside_with_half_ulp_slack"]))
            else:
                print("%-24s attempt %d %-22s %s" % (lab, a["attempt"], a["arm_outcome"], a["diagnostics"]))
