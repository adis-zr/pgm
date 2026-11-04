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
import os, sys, json, time, hashlib, math, signal, subprocess
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


STATUS_TRUE = "true: Consistent evidence"
STATUS_FALSE = "false: Inconsistent evidence or underflow"          # Merlin's ONE line for exact zero evidence AND underflow (ambiguous)
_DECIMAL = None


def _is_decimal_token(tok):
    """A plain decimal (optionally signed, optional fraction / exponent); rejects nan / inf / anything else."""
    import re
    return re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", tok) is not None


def parse_mar(path):
    """Merlin's UAI output: PR / <logZ> (<Z>) / STATUS / <line> / MAR / <nvars> {<k> <k values>}... Every structural
    fault is recorded in `faults` (never raised): missing / unrecognized STATUS, missing MAR, non-integer counts,
    truncated rows, trailing tokens."""
    txt = open(path, errors="replace").read()
    toks = txt.split()
    out = {"raw": txt[:4000], "faults": [], "rows": None, "status": None, "log_pr": None}
    if "PR" in toks:
        i = toks.index("PR")
        out["log_pr"] = toks[i + 1] if i + 1 < len(toks) else None
    if "STATUS" not in toks:
        out["faults"].append("missing STATUS line")
    else:
        i = toks.index("STATUS")
        j = toks.index("MAR") if "MAR" in toks else len(toks)
        st = " ".join(toks[i + 1:j])
        out["status"] = st
        if st not in (STATUS_TRUE, STATUS_FALSE):
            out["faults"].append("unrecognized STATUS %r (expected %r or %r)" % (st[:80], STATUS_TRUE, STATUS_FALSE))
    if "MAR" not in toks:
        out["faults"].append("missing MAR block")
        return out
    k = toks.index("MAR") + 1
    try:
        n = int(toks[k]); pos = k + 1
        rows = []
        for _ in range(n):
            c = int(toks[pos]); pos += 1
            if c < 1 or pos + c > len(toks):
                out["faults"].append("truncated or malformed MAR row (count %d at token %d of %d)" % (c, pos, len(toks)))
                rows = None
                break
            rows.append(toks[pos:pos + c]); pos += c
        if rows is not None and pos != len(toks):
            out["faults"].append("%d trailing tokens after the MAR rows" % (len(toks) - pos))
        out["rows"] = rows
    except (ValueError, IndexError) as e:
        out["faults"].append("malformed MAR block: %s: %s" % (type(e).__name__, e))
        out["rows"] = None
    return out


def validate_output(parsed, n, card, evidence):
    """Shape and range validation only: a recognized STATUS; one row per variable in order; row lengths = cardinalities;
    every value a finite decimal in [0, 1]; observed rows exact point masses; unobserved rows normalized within
    ROW_SUM_TOL when STATUS is true. STATUS false is reported as zero-evidence-OR-underflow (Merlin does not
    distinguish) and its rows are not judged for normalization. Never raises."""
    issues = list(parsed.get("faults") or [])
    rows = parsed.get("rows")
    status = parsed.get("status")
    consistent = (status == STATUS_TRUE)
    zero_or_underflow = (status == STATUS_FALSE)
    if rows is None:
        if "missing MAR block" not in issues and not any("malformed" in x or "truncated" in x for x in issues):
            issues.append("no MAR rows")
        return {"ok": False, "issues": issues, "consistent_evidence": consistent, "zero_evidence_or_underflow": zero_or_underflow}
    if len(rows) != n:
        issues.append("row count %d != %d variables" % (len(rows), n))
    for v, row in enumerate(rows[:n]):
        if len(row) != card[v]:
            issues.append("variable %d: %d values, cardinality %d" % (v, len(row), card[v]))
            continue
        if not all(_is_decimal_token(x) for x in row):
            issues.append("variable %d: non-decimal or non-finite token %r" % (v, [x for x in row if not _is_decimal_token(x)][:3]))
            continue
        vals = [Fr(x) for x in row]
        if any(x < 0 or x > 1 for x in vals):
            issues.append("variable %d: value outside [0, 1]" % v)
        if v in evidence:
            want = [Fr(1) if s == evidence[v] else Fr(0) for s in range(card[v])]
            if vals != want:
                issues.append("observed variable %d is not the exact point mass at %d" % (v, evidence[v]))
        elif consistent and abs(sum(vals) - 1) > Fr(ROW_SUM_TOL).limit_denominator(10 ** 9):
            issues.append("variable %d: row sums to %s" % (v, float(sum(vals))))
    return {"ok": not issues, "issues": issues, "consistent_evidence": consistent, "zero_evidence_or_underflow": zero_or_underflow}


def _descendants(pid):
    """Every descendant pid of `pid` (BFS over ps's pid/ppid table)."""
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    kids = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                kids.setdefault(int(parts[1]), []).append(int(parts[0]))
            except ValueError:
                pass
    seen, stack = [], [pid]
    while stack:
        q = stack.pop()
        for c in kids.get(q, []):
            if c not in seen:
                seen.append(c); stack.append(c)
    return seen


def run_child_same_group(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=None):
    """Run the comparator binary as a child in the ADAPTER'S OWN process group (no new session): the outer supervisor's
    `killpg` on the adapter therefore reaches the binary and every descendant, so an
    outer timeout or RSS stop signals all members of that group (repair of 4 Nov 2026).
    The outer supervisor waits for its direct adapter child; it does not individually reap grandchildren. The adapter's own deadline / tree-RSS polling reuses the pinned
    supervisor's sampler and kills the child AND its descendants itself when its inner limits are breached."""
    from ext import supervise as SV
    rec = {"cmd": cmd, "cwd": cwd, "deadline_s": deadline_s, "mem_limit_kib": mem_limit_kib, "same_process_group_as_adapter": True}
    t0 = time.time()
    e = dict(os.environ); e.update(env or {})
    lf = open(log_path, "w", buffering=1)
    lf.write("# cmd: %s\n# cwd: %s\n# started: %s\n# NOTE: same process group as the adapter (outer killpg signals this process group)\n" % (" ".join(cmd), cwd, time.strftime("%Y-%m-%dT%H:%M:%S%z")))
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, env=e)
    except OSError as ex:
        lf.write("\n# WRAPPER: launch failure %s\n" % ex); lf.close()
        rec.update({"outcome": "LAUNCH_FAILURE", "returncode": None, "elapsed_s": time.time() - t0, "peak_tree_rss_kib": 0, "peak_tree_procs": 0, "mem_samples": 0, "log": log_path})
        return rec

    def _kill_tree(reason):
        lf.write("\n# WRAPPER: %s; killing the child and its descendants\n" % reason)
        for p_ in [proc.pid] + _descendants(proc.pid):
            try:
                os.kill(p_, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=30)
        except Exception:
            pass
    peak_kib, peak_procs, samples = 0, 0, 0
    outcome = "COMPLETED"
    while proc.poll() is None:
        el = time.time() - t0
        if el > deadline_s:
            outcome = "TIMEOUT"; _kill_tree("inner deadline %.1fs exceeded at %.1fs" % (deadline_s, el)); break
        k, np_ = SV._tree_rss_kib(proc.pid)
        samples += 1
        if k is not None:
            if k > peak_kib:
                peak_kib, peak_procs = k, np_
            if mem_limit_kib and k > mem_limit_kib:
                outcome = "MEMORY_STOP"; _kill_tree("tree RSS %d KiB exceeded %d KiB" % (k, mem_limit_kib)); break
        time.sleep(SV.MEM_SAMPLE_S)
    rc = proc.returncode
    el = time.time() - t0
    if outcome == "COMPLETED" and rc != 0:
        outcome = "LAUNCH_FAILURE" if rc in (126, 127) else "NONZERO_EXIT"
    lf.write("\n# WRAPPER: rc=%s elapsed=%.3fs peak_tree_rss=%d KiB outcome=%s\n" % (rc, el, peak_kib, outcome)); lf.close()
    rec.update({"outcome": outcome, "returncode": rc, "elapsed_s": el, "peak_tree_rss_kib": peak_kib, "peak_tree_procs": peak_procs, "mem_samples": samples,
                "mem_sampling_interval_s": SV.MEM_SAMPLE_S, "log": log_path, "descendants_after_exit": _descendants(proc.pid)})
    return rec


def run_cell(model, evid, out_dir, label, wall_s, mem_gib=8.0, binary=None, algorithm="cte"):
    """ONE fresh-process Merlin invocation: conversion (none -- UAI is Merlin's native input), per-instance
    preprocessing, exact CTE compilation, all-variable readout and the write of its MAR file all happen inside the
    child (same process group as this adapter). The child's measured outcome and wall are PERSISTED before any output is
    parsed; parsing / validation faults are recorded durably, never raised. Timing fields: `merlin_process_elapsed_s` is
    the child's wall (a COMPONENT of the outer cell charge measured by the orchestrator's supervisor, never to be added to
    it); `adapter_parse_validate_s` is this wrapper's own post-processing."""
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
    rp = os.path.join(out_dir, "comparator_%s.json" % label)
    _dump(rec, rp)                                                                                  # durable STARTED record
    sup = run_child_same_group(cmd, cwd=out_dir, log_path=os.path.join(out_dir, "merlin_%s.log" % label), deadline_s=float(wall_s),
                               mem_limit_kib=int(mem_gib * 2 ** 20), env=dict(THREAD_ENV))
    # the child's MEASURED outcome and wall are persisted BEFORE any artifact is parsed (a parse fault can never erase them)
    rec["child"] = {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "peak_tree_procs", "mem_samples", "same_process_group_as_adapter", "descendants_after_exit")}
    rec["merlin_process_elapsed_s"] = sup.get("elapsed_s")
    rec["timing_note"] = ("merlin_process_elapsed_s is the child's wall, a COMPONENT of the outer cell charge measured by the orchestrator's "
                          "supervisor (spawn of this adapter to its exit); never add the two")
    rec["outcome"] = "CHILD_" + str(sup.get("outcome"))                                                  # provisional, truthful
    _dump(rec, rp)
    t1 = time.time()
    mar = out_prefix + ".MAR"
    try:
        if sup.get("outcome") != "COMPLETED":
            # a stop or a non-zero exit can NEVER become a completion, whatever the MAR file says
            rec.update({"outcome": "COMPARATOR_" + str(sup.get("outcome")), "reason": "child %s (rc %s); output not accepted" % (sup.get("outcome"), sup.get("returncode"))})
        elif not os.path.exists(mar):
            rec.update({"outcome": "COMPARATOR_NO_OUTPUT", "reason": "the child completed (rc 0) but wrote no MAR file"})
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
            elif val["zero_evidence_or_underflow"]:
                rec.update({"outcome": "COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW", "reason": "STATUS %r: Merlin does not distinguish exact zero evidence from floating-point underflow" % parsed.get("status")})
            else:
                rec.update({"outcome": "COMPARATOR_COMPLETED", "reason": "all %d rows present, in [0, 1], normalized within %g; binary64 beliefs printed to 6 decimals; NOT a certificate" % (n, ROW_SUM_TOL)})
    except Exception as e:                                                                               # a parsing fault is recorded, never raised
        rec.update({"outcome": "COMPARATOR_OUTPUT_INVALID", "reason": "parsing failure: %s: %s" % (type(e).__name__, str(e)[:200])})
    rec["adapter_parse_validate_s"] = time.time() - t1
    rec["ended"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _dump(rec, rp)
    return rec


def _dump(rec, path):
    tmp = path + ".tmp"
    json.dump(rec, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, path)


if __name__ == "__main__":
    a = sys.argv[1:]
    r = run_cell(a[0], a[1], a[2], a[3], float(a[4]), float(a[5]) if len(a) > 5 else 8.0)
    print(json.dumps({k: r.get(k) for k in ("label", "outcome", "reason", "supervisor")}, default=str))
    sys.exit(0 if r["outcome"] in ("COMPARATOR_COMPLETED", "COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW") else 1)
