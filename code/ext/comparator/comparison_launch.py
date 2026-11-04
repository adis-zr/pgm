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
import os, sys, json, time, hashlib, math
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


def glue_hashes():
    return {"orchestrator_sha256": L.sha256_file(os.path.abspath(__file__)), "adapter_sha256": L.sha256_file(os.path.abspath(MA.__file__)),
            "merlin_pin_sha256": L.sha256_file(MA.PIN_PATH)}


def validate_glue(bindings):
    """The orchestrator, the adapter and the comparator pin file must hash to the bindings' `glue` values (enforced on
    preparation AND before every run / revalidation; repair of 4 Nov 2026)."""
    want = bindings.get("glue") or {}
    have = glue_hashes()
    bad = [k for k in ("orchestrator_sha256", "adapter_sha256", "merlin_pin_sha256") if want.get(k) != have[k]]
    if bad:
        raise L.Refused("glue hash mismatch against the bindings: %s (have %s)" % (bad, {k: have[k][:12] for k in bad}))
    return have


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
        glue = validate_glue(bindings)
        cmp_res = validate_comparator(bindings)
        man = L.write_manifest(rundir, view, pin, resolved, argv or sys.argv, os.path.abspath(__file__), bindings_path, pin_path, input_dir,
                               extra={"orchestrator": {"path": "ext/comparator/comparison_launch.py", "sha256": glue["orchestrator_sha256"], "verified_against_bindings": True},
                                      "adapter": {"path": "ext/comparator/merlin_adapter.py", "sha256": glue["adapter_sha256"], "verified_against_bindings": True},
                                      "merlin_pin_file_sha256": glue["merlin_pin_sha256"],
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
    """Outer resource stops take precedence. A recorded inner resource stop retains its
    class even when the adapter exits 1, as it is specified to do for that stop.
    Native completion requires mutually consistent successful outer/inner outcomes."""
    so = sup.get("outcome")
    if so == "TIMEOUT":
        return "comparator_timeout", "killed by the supervisor at its deadline (wall %.1f s plus the declared grace)" % wall
    if so == "MEMORY_STOP":
        return "comparator_memory_stop", "supervisor memory limit"
    rec = rec if isinstance(rec, dict) else {}
    child = rec.get("child") or rec.get("supervisor")
    child = child if isinstance(child, dict) else {}
    child_out = child.get("outcome")
    if so in ("COMPLETED", "NONZERO_EXIT") and child_out in ("TIMEOUT", "MEMORY_STOP"):
        return ("comparator_timeout" if child_out == "TIMEOUT" else "comparator_memory_stop"), "inner %s; outer process %s (rc=%s); no completion accepted" % (child_out, so, sup.get("returncode"))
    if so != "COMPLETED" or sup.get("returncode") != 0:
        return "comparator_failure", "outer process %s (rc=%s); the child record (%s) is not accepted as a completion" % (so, sup.get("returncode"), rec.get("outcome"))
    if not rec:
        return "comparator_failure", "no durable / readable comparator record after a completed outer process"
    out = rec.get("outcome")
    if out in ("COMPARATOR_COMPLETED", "COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW"):
        val = rec.get("validation")
        if child_out != "COMPLETED" or child.get("returncode") != 0:
            return "comparator_failure", "incomplete or inconsistent successful child outcome"
        if not isinstance(val, dict) or val.get("ok") is not True:
            return "comparator_failure", "missing or unsuccessful output validation"
        required = "consistent_evidence" if out == "COMPARATOR_COMPLETED" else "zero_evidence_or_underflow"
        if val.get(required) is not True:
            return "comparator_failure", "output validation does not support %s" % out
        if float(sup.get("elapsed_s") or 0) > wall:
            return "comparator_timeout", "completed but not within the %.1f s wall (outer %.3f s)" % (wall, float(sup.get("elapsed_s") or 0))
    if out == "COMPARATOR_COMPLETED":
        return "comparator_completed_native", "all marginals written and shape-validated; binary64, six decimals; NOT certified"
    if out == "COMPARATOR_ZERO_EVIDENCE_OR_UNDERFLOW":
        return "comparator_zero_evidence_or_underflow", str(rec.get("reason"))[:200]
    return "comparator_failure", "%s: %s" % (out, str(rec.get("reason"))[:200])


def _measured_charge(value):
    """A missing/invalid measurement remains unknown; a deadline is not a measurement."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def unknown_expenditure(led):
    unknown = []
    for c in led["cells"]:
        for a in c["attempts"]:
            if _measured_charge(a.get("charged_s")) is None:
                unknown.append({"label": c["label"], "attempt": a.get("n"), "dir": a.get("dir")})
    return unknown


def conservative_charged_s(led):
    """Compatibility name: sum known charges, refusing an unresolved total.
    The supervisor's kill deadline is not a bound on elapsed time after interruption."""
    if unknown_expenditure(led):
        raise L.Refused("unresolved expenditure: total and remaining allowance are unavailable")
    return sum(float(a["charged_s"]) for c in led["cells"] for a in c["attempts"])


def _accounting_state(led):
    led.pop("unknown_expenditure_bound_s", None)
    for c in led["cells"]:
        for a in c["attempts"]:
            a.pop("charge_unknown_bounded_by_s", None)
    unknown = unknown_expenditure(led)
    led["unknown_expenditure_attempts"] = unknown
    led["accounting_status"] = "UNRESOLVED" if unknown else "COMPLETE"
    led["carry_forward_available"] = not unknown
    return unknown


def _persist_accounting_or_stop(led, path):
    unknown = _accounting_state(led)
    _jdump(led, path)
    if unknown:
        raise L.Refused("unresolved expenditure for %s: no further cell may start; recover measured costs and confirm process termination before resuming" % unknown)


def _allowance_remaining_conservative(led):
    return float(led["allowance_s"]) - conservative_charged_s(led)


def _session_remaining_conservative(led):
    return led["session_cap_s"] - sum(float(v) for v in led["previous_expenditure_s"].values()) - conservative_charged_s(led) - L.other_charges_s(led)


def run_cells(rundir, bindings, python=None):
    from ext import supervise as SV
    python = python or sys.executable
    man_path = os.path.join(rundir, "EXECUTION_MANIFEST.json")
    if not os.path.exists(man_path):
        raise L.Refused("no EXECUTION_MANIFEST.json in %s: prepare before running" % rundir)
    validate_glue(bindings)                                  # REVALIDATION before every run: the glue must still hash to the bindings
    validate_comparator(bindings)
    lp = os.path.join(rundir, "LEDGER.json")
    led = json.load(open(lp))
    want = ["%s_%s" % (p, a) for p, a in bindings["order"]]
    if [c["label"] for c in led["cells"]] != want:
        raise L.Refused("LEDGER.json carries cells %s, the bindings' frozen order is %s" % ([c["label"] for c in led["cells"]], want))
    cap_bytes = int(bindings["engine_limits"]["arm_rss_bytes"])
    if bindings.get("synthetic_control") and bindings.get("synthetic_control_mem_cap_bytes"):
        cap_bytes = min(cap_bytes, int(bindings["synthetic_control_mem_cap_bytes"]))        # tiny controls: the configured 1 GiB cap
    input_dir = bindings["input_dir"]
    mdi_cmd = L.default_cmd_factory(python, input_dir)
    env = dict(L.THREAD_ENV); env["PYTHONPATH"] = L.HERE
    grace = float(bindings.get("durable_grace_s", 0.0))
    for c in led["cells"]:
        for a in c["attempts"]:
            if a.get("status") in ("STARTED", "TERMINAL_UNCLASSIFIED"):
                # An unclassified attempt is never rerun. Unknown expenditure stops
                # the campaign; a deadline cannot supply a missing measurement.
                a["status"] = "INTERRUPTED"; c["status"] = "INTERRUPTED"
    _persist_accounting_or_stop(led, lp)
    for c in led["cells"]:
        label, arm = c["label"], c["arm"]
        if c["status"] in ("CONSUMED", "INTERRUPTED", "NOT_RUN_CUMULATIVE_STOP", "NOT_RUN_ALLOWANCE_STOP"):
            print("  [compare] %-24s %s: not rerun" % (label, c["status"]), flush=True); continue
        wall = led["cell_wall_s"]
        if _session_remaining_conservative(led) < wall:
            c["status"] = "NOT_RUN_CUMULATIVE_STOP"; c["cumulative_stop"] = {"session_remaining_conservative_s": _session_remaining_conservative(led), "needed_s": wall}
            _jdump(led, lp); print("  [compare] %-24s NOT RUN: cumulative session cap" % label, flush=True); continue
        if _allowance_remaining_conservative(led) < wall + grace:
            c["status"] = "NOT_RUN_ALLOWANCE_STOP"; c["allowance_stop"] = {"allowance_remaining_conservative_s": _allowance_remaining_conservative(led), "needed_s": wall + grace}
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
        # the MEASURED outcome and charge are persisted FIRST (repair of 4 Nov 2026): a missing or truncated child
        # record can no longer erase the cost; classification follows in a second durable step
        att.update({"status": "TERMINAL_UNCLASSIFIED", "ended": time.strftime("%Y-%m-%d %H:%M:%S"), "charged_s": _measured_charge(sup.get("elapsed_s")),
                    "supervisor": {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "peak_tree_procs", "mem_samples", "mem_limitation")}})
        _persist_accounting_or_stop(led, lp)
        rec = receipt = None
        read_faults = []

        def _load(path):
            if not os.path.exists(path):
                return None
            try:
                obj = json.load(open(path))
                if not isinstance(obj, dict):
                    read_faults.append("%s: expected a JSON object, got %s" % (os.path.basename(path), type(obj).__name__))
                    return None
                return obj
            except (ValueError, OSError) as e:
                read_faults.append("%s: %s: %s" % (os.path.basename(path), type(e).__name__, str(e)[:120])); return None
        if arm in COMPARATOR_ARMS:
            rec = _load(os.path.join(adir, "comparator_%s.json" % label))
            cls, why = _classify_comparator(sup, rec, wall)
            outcome = (rec or {}).get("outcome"); width = None
            inner = (rec or {}).get("merlin_process_elapsed_s")
        else:
            rec = _load(os.path.join(adir, "arm_%s.json" % label)); receipt = _load(os.path.join(adir, "arm_%s.receipt.json" % label))
            cls, why = L._classify(sup, rec, receipt, wall)
            outcome = (rec or {}).get("outcome"); width = (rec or {}).get("final_max_width"); inner = (rec or {}).get("elapsed_s")
        if read_faults:
            why = "%s; record read faults: %s" % (why, "; ".join(read_faults))[:400]
        att.update({"status": "TERMINAL", "arm_outcome": outcome, "arm_reason": str((rec or {}).get("reason") or "")[:300],
                    "component_elapsed_s": inner, "component_elapsed_note": "the child's own wall as it recorded it: a COMPONENT of charged_s (the outer spawn-to-exit wall), never added to it",
                    "final_max_width": width, "receipt": receipt, "record_read_faults": read_faults or None, "class": cls, "class_reason": why,
                    "kind_of_result": ("native_uncertified" if arm in COMPARATOR_ARMS else "certified_mdi")})
        c["status"] = "CONSUMED"; _jdump(led, lp)
        print("  [compare] %-24s initial: %s (%s) charged %.1f s; cumulative %.1f of %.0f s" % (label, cls, outcome, att["charged_s"], L.charged_cells_s(led), led["allowance_s"]), flush=True)
    return led


def closeout(rundir, bindings):
    """Keep missing expenditure explicit in the published summary and carry-forward.
    The pinned closeout is used unchanged only when all attempt charges are known."""
    t0 = time.time()
    led = L.load_ledger(rundir, bindings)
    unknown = _accounting_state(led)
    _jdump(led, os.path.join(rundir, "LEDGER.json"))
    if not unknown:
        return L.closeout(rundir, bindings)
    rows = []
    known_total = 0.0
    for c in led["cells"]:
        known = sum(v for a in c["attempts"] if (v := _measured_charge(a.get("charged_s"))) is not None)
        missing = sum(_measured_charge(a.get("charged_s")) is None for a in c["attempts"])
        known_total += known
        last = c["attempts"][-1] if c["attempts"] else {}
        rows.append({"label": c["label"], "status": c["status"], "attempts": len(c["attempts"]),
                     "class": last.get("class"), "arm_outcome": last.get("arm_outcome"),
                     "charged_s": None if missing else known, "known_charged_s": known,
                     "unknown_charge_attempts": missing, "final_max_width": last.get("final_max_width")})
    led["closeout_s"] = float(led["closeout_s"]) + (time.time() - t0)
    summary = {"cells": rows, "charged_cells_s": None, "known_charged_cells_s": known_total,
               "accounting_status": "UNRESOLVED", "unknown_expenditure_attempts": unknown,
               "carry_forward_available": False, "session_remaining_s": None, "allowance_remaining_s": None,
               "allowance_s": led["allowance_s"], "preparation_s": led["preparation_s"],
               "closeout_s": led["closeout_s"], "charges": led["charges"],
               "previous_expenditure_s": led["previous_expenditure_s"], "repair": led["repair"],
               "note": "Known costs are retained; the unknown total is not bounded by a kill deadline. No further launch or carry-forward until resolved.",
               "built": time.strftime("%Y-%m-%d %H:%M:%S")}
    _jdump(led, os.path.join(rundir, "LEDGER.json"))
    _jdump(summary, os.path.join(rundir, "SUMMARY.json"))
    return summary


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
        print(json.dumps(closeout(rundir, bindings), indent=1, default=str)); return 0
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
