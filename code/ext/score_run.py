"""Score one completed baseline invocation. Separate from solver execution."""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import uai, score, arb_extract

PKT = "/tmp/tep/three_external_problems/inputs"


def score_merlin_run(problem, rundir):
    p = os.path.join(PKT, problem)
    m = uai.read_model(p + ".uai"); ev = uai.read_evidence(p + ".uai.evid")
    ref, _ = uai.read_mar(p + ".uai.MAR")
    out = os.path.join(rundir, "merlin_work", problem + ".ijgp.MAR")
    if not os.path.exists(out):
        return {"error": "no output file at %s" % out}
    rows, _ = uai.read_mar(out)
    iss = score.validate_output(rows, m, ev, "ijgp")
    s = score.score(rows, ref, m, ev)
    s.pop("per_var")
    return {"output_file": out, "validation_issues": iss, "n_validation_issues": len(iss),
            "point_output": "solver's own MAR probabilities, unmodified", **s}


def score_arb_run(problem, rundir):
    p = os.path.join(PKT, problem)
    m = uai.read_model(p + ".uai"); ev = uai.read_evidence(p + ".uai.evid")
    ref, _ = uai.read_mar(p + ".uai.MAR")
    trace = os.path.join(rundir, "arb_work", problem + ".trace")
    if not os.path.exists(trace):
        return {"error": "no trace at %s" % trace}
    rows, meta = arb_extract.extract(trace, m.nvars, m.card, ev)
    if meta["missing"]:
        return {"error": "marginals missing for %d vars" % len(meta["missing"]),
                "extract_meta": meta}
    iss = score.validate_output(rows, m, ev, "arb")
    s = score.score(rows, ref, m, ev)
    s.pop("per_var")
    # also write a standard MAR so the output is durable and re-checkable
    marout = os.path.join(rundir, "arb_work", problem + ".arb.MAR")
    uai.write_mar(marout, rows)
    return {"trace": trace, "written_mar": marout, "extract_meta":
            {k: v for k, v in meta.items() if k != "observed_reported"},
            "observed_reported_by_arb": meta.get("observed_reported", {}),
            "validation_issues": iss, "n_validation_issues": len(iss),
            "point_output": "ARB chain-merged normalized marginals from its trace JSON, "
                            "renormalized per variable by their own sum (ARB reports "
                            "normalized marginals; residual drift only). Observed "
                            "variables written as exact point masses per original-task "
                            "fidelity.", **s}


if __name__ == "__main__":
    which, problem, rundir = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
    fn = {"arb": score_arb_run, "merlin": score_merlin_run}[which]
    r = fn(problem, rundir)
    json.dump(r, open(os.path.join(rundir, "%s_%s_score.json" % (which, problem)), "w"), indent=2)
    if "error" in r:
        print("ERROR:", r["error"])
    else:
        print("%s %s: issues=%d maxH=%.6f meanH=%.6f maxAbs=%.6f -log2=%.3f scored=%d" % (
            which, problem, r["n_validation_issues"], r["max_hellinger"], r["mean_hellinger"],
            r["max_coord_abs_error"], r["neg_log2_max_hellinger"], r["unobserved_scored"]))
