"""Thin orchestrator for the EXTERNAL COMPARISON experiment (comparator qualification pass, 4 November 2026): cells of two
kinds in ONE frozen order -- MDI arms (`baseline` / `selector`), run as the pinned launcher's own child command
(`python -m mdi.launch --cell PROBLEM ARM ATTEMPT_DIR WALL_S INPUT_DIR`), and the comparator arm (`merlin`), run through
`ext.comparator.merlin_adapter`. Every cell runs in a fresh process under `ext.supervise.run` with the same limits and the
same ledger rules as `mdi.launch` (whose functions are imported, not copied, wherever they are arm-independent). The MDI
engine, its pin and `mdi.launch` are UNCHANGED: `mdi.launch.validate_bindings` refuses the unknown arm name, so this module
validates the MDI part through it (the bindings with the comparator cells filtered out) and checks the comparator's own pin
itself. Nothing here solves, prices or certifies anything.

    python -m ext.comparator.comparison_launch RUNDIR --bindings B.json --packet P.zip [--prepare-only] [--closeout]
"""
from __future__ import annotations
import os, sys, json, time, hashlib
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
from mdi import launch as L
from ext.comparator import merlin_adapter as MA

COMPARATOR_ARMS = ("merlin",)


def _jdump(o, p):
    tmp = p + ".tmp"
    json.dump(o, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, p)


def mdi_view(bindings):
    """The bindings with the comparator cells removed: what `mdi.launch.validate_bindings` can judge."""
    v = dict(bindings)
    v["order"] = [list(x) for x in bindings["order"] if x[1] not in COMPARATOR_ARMS]
    return v


def validate_comparator(bindings):
    pin = MA.load_pin()
    want = bindings["comparator"]
    problems = []
    if pin["binary"]["sha256"] != want["binary_sha256"]:
        problems.append("comparator pin binary hash %s differs from the bindings' %s" % (pin["binary"]["sha256"][:16], want["binary_sha256"][:16]))
    bp = os.path.expanduser(pin["binary"]["path"])
    if not os.path.exists(bp):
        problems.append("comparator binary missing: %s" % bp)
    elif MA.sha256_file(bp) != want["binary_sha256"]:
        problems.append("comparator binary on disk does not hash to the pinned value")
    if pin["source"]["commit"] != want["source_commit"]:
        problems.append("comparator source commit differs from the bindings'")
    if MA.sha256_file(MA.PIN_PATH) != want["pin_file_sha256"]:
        problems.append("the comparator pin file does not hash to the bindings' value")
    if problems:
        raise L.Refused("; ".join(problems))
    return {"binary_sha256": want["binary_sha256"], "source_commit": want["source_commit"], "pin_file_sha256": want["pin_file_sha256"],
            "command": pin["command"], "guarantee": pin["guarantee"], "structural_mechanism": pin["structural_mechanism"]}


def prepare(rundir, bindings, pin, bindings_path, pin_path, packet, argv=None):
    """Restore inputs, validate every binding (MDI part through the pinned launcher; comparator part here; the packet's
    whole-file hash), write the manifest and the FULL-order ledger. Charged to preparation_s."""
    t0 = time.time()
    os.makedirs(rundir, exist_ok=True)
    lp = os.path.join(rundir, "LEDGER.json")
    led = json.load(open(lp)) if os.path.exists(lp) else L._empty_ledger(bindings)
    input_dir = bindings["input_dir"]
    try:
        pinned_pk = bindings["packet"]["sha256"]
        ph = L.sha256_file(packet)
        if ph != pinned_pk:
            raise L.Refused("the packet %s hashes %s, the bindings pin %s" % (os.path.basename(packet), ph[:16], pinned_pk[:16]))
        L.restore_inputs(packet, input_dir, bindings["inputs"])
        view = mdi_view(bindings)
        resolved = L.validate_bindings(view, pin, L.HERE, input_dir, None)
        cmp_res = validate_comparator(bindings)
        man = L.write_manifest(rundir, view, pin, resolved, argv or sys.argv, os.path.abspath(__file__), bindings_path, pin_path, input_dir,
                               extra={"orchestrator": {"path": "ext/comparator/comparison_launch.py", "sha256": L.sha256_file(os.path.abspath(__file__))},
                                      "adapter": {"path": "ext/comparator/merlin_adapter.py", "sha256": L.sha256_file(os.path.abspath(MA.__file__))},
                                      "comparator": cmp_res, "full_order": [list(x) for x in bindings["order"]],
                                      "packet": {"path": os.path.abspath(packet), "sha256": ph, "pinned_sha256": pinned_pk, "whole_file_verified": True},
                                      "mdi_cells_validated_through": "mdi.launch.validate_bindings on the bindings with the comparator cells filtered out (the pinned launcher refuses unknown arm names)"})
    except L.Refused as e:
        _jdump({"refused": str(e), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "no_child_spawned": True}, os.path.join(rundir, "REFUSED_%d.json" % int(time.time())))
        led["preparation_s"] = float(led["preparation_s"]) + (time.time() - t0)
        _jdump(led, lp)
        raise
    led["preparation_s"] = float(led["preparation_s"]) + (time.time() - t0)
    _jdump(led, lp)
    return man, input_dir


def _classify_comparator(sup, rec, wall):
    so = sup.get("outcome")
    if so == "TIMEOUT":
        return "comparator_timeout", "killed by the supervisor at its deadline (wall %.1f s plus the declared grace)" % wall
    if so == "MEMORY_STOP":
        return "comparator_memory_stop", "supervisor memory limit"
    if not rec:
        return "comparator_failure", "no durable comparator record (%s rc=%s)" % (so, sup.get("returncode"))
    out = rec.get("outcome")
    if out == "COMPARATOR_COMPLETED":
        inner = (rec.get("supervisor") or {}).get("elapsed_s") or 0.0
        if float(sup.get("elapsed_s") or 0) > wall or inner > wall:
            return "comparator_timeout", "completed but not within the %.1f s wall" % wall
        return "comparator_completed_native", "all marginals written and shape-validated; binary64, six decimals; NOT certified"
    if out == "COMPARATOR_ZERO_EVIDENCE_REPORTED":
        return "comparator_zero_evidence_reported", str(rec.get("reason"))[:200]
    return "comparator_failure", "%s: %s" % (out, str(rec.get("reason"))[:200])


def run_cells(rundir, bindings, python=None):
    from ext import supervise as SV
    python = python or sys.executable
    man_path = os.path.join(rundir, "EXECUTION_MANIFEST.json")
    if not os.path.exists(man_path):
        raise L.Refused("no EXECUTION_MANIFEST.json in %s: prepare before running" % rundir)
    lp = os.path.join(rundir, "LEDGER.json")
    led = json.load(open(lp))
    want = ["%s_%s" % (p, a) for p, a in bindings["order"]]
    if [c["label"] for c in led["cells"]] != want:
        raise L.Refused("LEDGER.json carries cells %s, the bindings' frozen order is %s" % ([c["label"] for c in led["cells"]], want))
    cap_bytes = int(bindings["engine_limits"]["arm_rss_bytes"])
    input_dir = bindings["input_dir"]
    mdi_cmd = L.default_cmd_factory(python, input_dir)
    env = dict(L.THREAD_ENV); env["PYTHONPATH"] = L.HERE
    grace = float(bindings.get("durable_grace_s", 0.0))
    for c in led["cells"]:
        for a in c["attempts"]:
            if a.get("status") == "STARTED":
                a["status"] = "INTERRUPTED"; c["status"] = "INTERRUPTED"
    _jdump(led, lp)
    for c in led["cells"]:
        label, arm = c["label"], c["arm"]
        if c["status"] in ("CONSUMED", "INTERRUPTED", "NOT_RUN_CUMULATIVE_STOP", "NOT_RUN_ALLOWANCE_STOP"):
            print("  [compare] %-24s %s: not rerun" % (label, c["status"]), flush=True); continue
        wall = led["cell_wall_s"]
        if L.session_remaining_s(led) < wall:
            c["status"] = "NOT_RUN_CUMULATIVE_STOP"; c["cumulative_stop"] = {"session_remaining_s": L.session_remaining_s(led), "needed_s": wall}
            _jdump(led, lp); print("  [compare] %-24s NOT RUN: cumulative session cap" % label, flush=True); continue
        if L.allowance_remaining_s(led) < wall + grace:
            c["status"] = "NOT_RUN_ALLOWANCE_STOP"; c["allowance_stop"] = {"allowance_remaining_s": L.allowance_remaining_s(led), "needed_s": wall + grace}
            _jdump(led, lp); print("  [compare] %-24s NOT RUN: the run's allowance" % label, flush=True); continue
        n = len(c["attempts"]) + 1
        adir = os.path.join(rundir, "cells", label, "attempt_%d" % n)
        if os.path.exists(adir):
            raise L.Refused("attempt directory %s already exists but the ledger does not know it" % adir)
        os.makedirs(adir)
        if arm in COMPARATOR_ARMS:
            cmd = [python, "-m", "ext.comparator.merlin_adapter", os.path.join(input_dir, c["problem"] + ".uai"), os.path.join(input_dir, c["problem"] + ".uai.evid"),
                   adir, label, "%.3f" % wall, "%.6f" % (cap_bytes / 2 ** 30)]
        else:
            cmd = mdi_cmd(c["problem"], arm, adir, wall)
        att = {"n": n, "kind": "initial", "dir": os.path.relpath(adir, rundir), "wall_granted_s": wall, "supervisor_kill_deadline_s": wall + grace,
               "command": cmd, "status": "STARTED", "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        c["attempts"].append(att); c["status"] = "STARTED"; _jdump(led, lp)
        print("  [compare] %-24s initial attempt %d wall %.1f s ..." % (label, n, wall), flush=True)
        sup = SV.run(cmd, cwd=L.HERE, log_path=os.path.join(adir, "supervisor.log"), deadline_s=wall + grace, mem_limit_kib=cap_bytes // 1024, env=env, label=label)
        rec = receipt = None
        if arm in COMPARATOR_ARMS:
            p = os.path.join(adir, "comparator_%s.json" % label)
            rec = json.load(open(p)) if os.path.exists(p) else None
            cls, why = _classify_comparator(sup, rec, wall)
            outcome = (rec or {}).get("outcome")
            width = None
        else:
            pa, pr = os.path.join(adir, "arm_%s.json" % label), os.path.join(adir, "arm_%s.receipt.json" % label)
            rec = json.load(open(pa)) if os.path.exists(pa) else None
            receipt = json.load(open(pr)) if os.path.exists(pr) else None
            cls, why = L._classify(sup, rec, receipt, wall)
            outcome = (rec or {}).get("outcome"); width = (rec or {}).get("final_max_width")
        att.update({"status": "TERMINAL", "ended": time.strftime("%Y-%m-%d %H:%M:%S"), "charged_s": float(sup.get("elapsed_s") or 0.0),
                    "supervisor": {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "peak_tree_procs", "mem_samples", "mem_limitation")},
                    "arm_outcome": outcome, "arm_reason": str((rec or {}).get("reason") or "")[:300],
                    "arm_elapsed_s": (rec or {}).get("elapsed_s") if arm not in COMPARATOR_ARMS else ((rec or {}).get("supervisor") or {}).get("elapsed_s"),
                    "final_max_width": width, "receipt": receipt, "class": cls, "class_reason": why, "kind_of_result": ("native_uncertified" if arm in COMPARATOR_ARMS else "certified_mdi")})
        c["status"] = "CONSUMED"; _jdump(led, lp)
        print("  [compare] %-24s initial: %s (%s) charged %.1f s; cumulative %.1f of %.0f s" % (label, cls, outcome, att["charged_s"], L.charged_cells_s(led), led["allowance_s"]), flush=True)
    return led


def main(argv):
    rundir = os.path.abspath(argv[0])
    opts = {"--bindings": None, "--packet": None}
    flags = set(); i = 1
    while i < len(argv):
        if argv[i] in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]; i += 2
        elif argv[i] in ("--prepare-only", "--closeout"):
            flags.add(argv[i]); i += 1
        else:
            raise SystemExit("unknown option %s" % argv[i])
    bindings_path = os.path.abspath(opts["--bindings"]); bindings = json.load(open(bindings_path))
    if "--closeout" in flags:
        print(json.dumps(L.closeout(rundir, bindings), indent=1, default=str)); return 0
    pin_path = os.path.join(L.HERE, bindings["build_pin"]["path"]); pin = json.load(open(pin_path))
    if L.sha256_file(pin_path) != bindings["build_pin"]["sha256"]:
        raise SystemExit("BUILD_PIN does not hash to the bindings' pinned value")
    cmdline = [sys.executable, "-m", "ext.comparator.comparison_launch"] + list(argv)
    try:
        man, input_dir = prepare(rundir, bindings, pin, bindings_path, pin_path, opts["--packet"], argv=cmdline)
    except L.Refused as e:
        print("REFUSED before any child was spawned: %s" % e); return 3
    print("manifest written: engine %s, %d pinned files verified, comparator binary %s, orchestrator %s" % (
        man["engine"]["commit"][:12], man["engine"]["pinned_files_verified"], man["comparator"]["binary_sha256"][:12], man["orchestrator"]["sha256"][:12]))
    if "--prepare-only" in flags:
        return 0
    led = run_cells(rundir, bindings)
    print(json.dumps({"charged_cells_s": L.charged_cells_s(led), "allowance_s": led["allowance_s"], "cells": {c["label"]: c["status"] for c in led["cells"]}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
