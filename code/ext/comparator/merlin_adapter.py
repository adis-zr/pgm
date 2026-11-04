"""Thin input / output / supervision glue for the pinned Merlin build (comparator qualification pass, 4 November 2026).

NOT a solver, numerical kernel or certificate system: it (1) runs the pinned `merlin` binary in a FRESH process under
`ext.supervise.run` (deadline, process-tree RSS, thread environment) with the UAI model and evidence files UNCHANGED,
(2) parses Merlin's UAI-format MAR output (PR / STATUS / MAR blocks), (3) validates the OUTPUT'S SHAPE -- one row per
original variable in file order, each row's length equal to the variable's cardinality, every unobserved row summing to
one within a stated rounding tolerance, observed rows exact point masses, the STATUS line consistent with the rows --
and (4) writes a durable JSON record with the supervisor measurements. Merlin's guarantee is stated, not improved:
binary64 arithmetic, normalized beliefs printed to six decimals; no enclosure, no independent check.

    python -m ext.comparator.merlin_adapter MODEL.uai EVID.uai.evid OUT_DIR LABEL WALL_S [MEM_GIB]
"""
from __future__ import annotations
import os, sys, json, time, hashlib
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)

PIN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MERLIN_PIN.json")
ROW_SUM_TOL = 1e-5                       # six-decimal rounding of k printed states (TOLERANCE_FROZEN.md)
THREAD_ENV = {"OMP_NUM_THREADS": "6", "MKL_NUM_THREADS": "6", "OPENBLAS_NUM_THREADS": "6", "VECLIB_MAXIMUM_THREADS": "6", "NUMEXPR_NUM_THREADS": "6"}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_pin():
    return json.load(open(PIN_PATH))


def merlin_command(binary, model, evid, out_prefix, algorithm="cte"):
    """The frozen command: exact clique-tree elimination, MAR, UAI output (the only task / algorithm / format used)."""
    return [binary, "--input-file", model, "--evidence-file", evid, "--task", "MAR", "--algorithm", algorithm,
            "--output-format", "uai", "--output-file", out_prefix]


def read_uai_header(model_path):
    toks = open(model_path).read().split()
    n = int(toks[1])
    card = [int(x) for x in toks[2:2 + n]]
    return n, card


def read_evidence(evid_path):
    toks = open(evid_path).read().split()
    if not toks:
        return {}
    k = int(toks[0])
    rest = toks[1:]
    assert len(rest) == 2 * k, "evidence token count"
    return {int(rest[2 * i]): int(rest[2 * i + 1]) for i in range(k)}


def parse_mar(path):
    """Merlin's UAI output: PR / <logZ> (<Z>) / STATUS / <line> / MAR / <nvars> {<k> <k values>}..."""
    txt = open(path).read()
    toks = txt.split()
    out = {"raw": txt}
    if "PR" in toks:
        i = toks.index("PR")
        out["log_pr"] = toks[i + 1]
    if "STATUS" in toks:
        i = toks.index("STATUS")
        j = toks.index("MAR") if "MAR" in toks else len(toks)
        out["status"] = " ".join(toks[i + 1:j])
    if "MAR" not in toks:
        out["rows"] = None
        return out
    k = toks.index("MAR") + 1
    n = int(toks[k]); pos = k + 1
    rows = []
    for _ in range(n):
        c = int(toks[pos]); pos += 1
        rows.append(toks[pos:pos + c]); pos += c
    if pos != len(toks):
        out["trailing_tokens"] = len(toks) - pos
    out["rows"] = rows
    return out


def validate_output(parsed, n, card, evidence):
    """Shape validation only (ordering, completeness, normalization, point masses, status consistency)."""
    issues = []
    rows = parsed.get("rows")
    status = parsed.get("status", "")
    consistent = status.startswith("true")
    if rows is None:
        issues.append("no MAR block")
        return {"ok": False, "issues": issues, "consistent_evidence": consistent}
    if len(rows) != n:
        issues.append("row count %d != %d variables" % (len(rows), n))
    for v, row in enumerate(rows[:n]):
        if len(row) != card[v]:
            issues.append("variable %d: %d values, cardinality %d" % (v, len(row), card[v]))
            continue
        try:
            vals = [Fr(x) for x in row]
        except ValueError:
            issues.append("variable %d: non-decimal token" % v)
            continue
        if any(x < 0 for x in vals):
            issues.append("variable %d: negative value" % v)
        if v in evidence:
            want = [Fr(1) if s == evidence[v] else Fr(0) for s in range(card[v])]
            if vals != want:
                issues.append("observed variable %d is not the exact point mass at %d" % (v, evidence[v]))
        elif consistent and abs(sum(vals) - 1) > Fr(ROW_SUM_TOL).limit_denominator(10 ** 9):
            issues.append("variable %d: row sums to %s" % (v, float(sum(vals))))
    if parsed.get("trailing_tokens"):
        issues.append("%d trailing tokens after the MAR rows" % parsed["trailing_tokens"])
    return {"ok": not issues, "issues": issues, "consistent_evidence": consistent}


def run_cell(model, evid, out_dir, label, wall_s, mem_gib=8.0, binary=None, algorithm="cte"):
    """ONE fresh-process Merlin invocation: conversion (none -- UAI is Merlin's native input), per-instance
    preprocessing, exact CTE compilation, all-variable readout and the write of its MAR file all happen inside the
    supervised child; this wrapper's own parsing / validation / record write follow and are timed separately."""
    from ext import supervise as SV
    os.makedirs(out_dir, exist_ok=True)
    pin = load_pin()
    binary = binary or os.path.expanduser(pin["binary"]["path"])
    rec = {"label": label, "comparator": "merlin", "pin": {"commit": pin["source"]["commit"], "binary_sha256": pin["binary"]["sha256"]},
           "binary_sha256_at_run": sha256_file(binary), "model": model, "evidence": evid,
           "input_sha256": {"model": sha256_file(model), "evidence": sha256_file(evid)},
           "wall_s": float(wall_s), "mem_limit_gib": float(mem_gib), "algorithm": algorithm, "task": "MAR", "output_format": "uai",
           "guarantee": pin["guarantee"], "started": time.strftime("%Y-%m-%d %H:%M:%S"), "outcome": "STARTED"}
    if rec["binary_sha256_at_run"] != pin["binary"]["sha256"]:
        rec.update({"outcome": "PIN_MISMATCH", "reason": "the binary does not hash to the pinned value"})
        json.dump(rec, open(os.path.join(out_dir, "comparator_%s.json" % label), "w"), indent=1)
        return rec
    out_prefix = os.path.join(out_dir, "merlin_%s" % label)
    cmd = merlin_command(binary, os.path.abspath(model), os.path.abspath(evid), out_prefix, algorithm)
    rec["command"] = cmd
    json.dump(rec, open(os.path.join(out_dir, "comparator_%s.json" % label), "w"), indent=1)        # durable STARTED record
    sup = SV.run(cmd, cwd=out_dir, log_path=os.path.join(out_dir, "merlin_%s.log" % label), deadline_s=float(wall_s),
                 mem_limit_kib=int(mem_gib * 2 ** 20), env=dict(THREAD_ENV), label=label)
    rec["supervisor"] = {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "peak_tree_procs", "mem_samples")}
    t1 = time.time()
    mar = out_prefix + ".MAR"
    if sup.get("outcome") != "COMPLETED" or not os.path.exists(mar):
        rec.update({"outcome": "COMPARATOR_" + str(sup.get("outcome")), "reason": "no MAR output (supervisor %s, rc %s)" % (sup.get("outcome"), sup.get("returncode"))})
    else:
        n, card = read_uai_header(model)
        ev = read_evidence(evid)
        parsed = parse_mar(mar)
        val = validate_output(parsed, n, card, ev)
        rec["mar_file"] = mar
        rec["mar_sha256"] = sha256_file(mar)
        rec["log_pr"] = parsed.get("log_pr")
        rec["status_line"] = parsed.get("status")
        rec["validation"] = val
        rec["rows"] = parsed.get("rows")
        if not val["ok"]:
            rec.update({"outcome": "COMPARATOR_OUTPUT_INVALID", "reason": "; ".join(val["issues"])[:300]})
        elif not val["consistent_evidence"]:
            rec.update({"outcome": "COMPARATOR_ZERO_EVIDENCE_REPORTED", "reason": parsed.get("status")})
        else:
            rec.update({"outcome": "COMPARATOR_COMPLETED", "reason": "all %d rows present, normalized within %g; binary64 beliefs printed to 6 decimals; NOT a certificate" % (n, ROW_SUM_TOL)})
    rec["adapter_parse_validate_s"] = time.time() - t1
    rec["elapsed_s_including_durable_write"] = None
    json.dump(rec, open(os.path.join(out_dir, "comparator_%s.json" % label), "w"), indent=1)
    rec["elapsed_s_including_durable_write"] = rec["supervisor"]["elapsed_s"] + rec["adapter_parse_validate_s"]
    json.dump(rec, open(os.path.join(out_dir, "comparator_%s.json" % label), "w"), indent=1)
    return rec


if __name__ == "__main__":
    a = sys.argv[1:]
    r = run_cell(a[0], a[1], a[2], a[3], float(a[4]), float(a[5]) if len(a) > 5 else 8.0)
    print(json.dumps({k: r.get(k) for k in ("label", "outcome", "reason", "supervisor")}, default=str))
    sys.exit(0 if r["outcome"].startswith("COMPARATOR_COMPLETED") or r["outcome"] == "COMPARATOR_ZERO_EVIDENCE_REPORTED" else 1)
