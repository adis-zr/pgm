"""The six-cell launcher for the fixed three-problem comparison (post-r26).

A THIN wrapper over two existing components -- `mdi.arm.run_arm` (one cell:
baseline or research-enabled, durable record + receipt) and
`ext.supervise.run` (the outer supervisor: deadline, whole-tree RSS sampling,
kills descendants). It adds only orchestration:

  * restores the six `.uai` / `.uai.evid` inputs SELECTIVELY from the packet
    zip into the arm's input directory (reference `.MAR` files are never
    extracted and their presence in that directory refuses the run);
  * validates every binding BEFORE any child is spawned -- pinned source
    hashes (BUILD_PIN), frozen configuration, input hashes, resolved runtime --
    and writes EXECUTION_MANIFEST.json; a mismatch is a refusal, never a run;
  * runs the six frozen cells in order through the supervisor with the declared
    limits and thread environment, each attempt in its own directory;
  * keeps LEDGER.json: STARTED and terminal records per attempt, cumulative
    charged work, preparation and closeout charged separately; on restart a
    consumed or uncertain STARTED cell is never silently run again;
  * the ONE repair consumes only unused time inside the six-cell allowance
    after 600 s is reserved for every unstarted initial cell; initial cells are
    never shortened; a repair that does not fit is refused and the failed
    outcome stands; a cell that cannot start under the session cap is marked
    NOT_RUN_CUMULATIVE_STOP explicitly.

    python -m mdi.launch RUNDIR [--bindings B.json] [--pin BUILD_PIN.json]
                                [--packet PACKET.zip] [--input-dir DIR]
                                [--prepare-only] [--repair LABEL]
                                [--closeout] [--charge WHAT SECONDS]
    python -m mdi.launch --cell PROBLEM baseline|research|support ATTEMPT_DIR WALL_S   (the child)
"""
from __future__ import annotations
import sys, os, json, time, hashlib, zipfile, subprocess, shutil
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(HERE, "runs", "mdi_2026-10-28")
DEFAULT_BINDINGS = os.path.join(RUNS, "COMPARISON_BINDINGS.json")
DEFAULT_INPUT_DIR = "/tmp/tep/three_external_problems/inputs"          # the pinned arm's PKT
PACKET_MEMBER_PREFIX = "three_external_problems/inputs/"
THREAD_ENV = {"OMP_NUM_THREADS": "6", "MKL_NUM_THREADS": "6", "OPENBLAS_NUM_THREADS": "6",
              "VECLIB_MAXIMUM_THREADS": "6", "NUMEXPR_NUM_THREADS": "6"}
CLASSES = {"CERTIFIED_RESEARCH_ROUTE": "certified_research_route", "CERTIFIED_FALLBACK_ONLY": "certified_fallback",
           "ZERO_EVIDENCE_PROVED": "zero_evidence_proved", "RESOURCE_STOP": "resource_refusal",
           "PRICE_REFUSAL": "resource_refusal", "NUMERICAL_REFUSAL": "certificate_rejection",
           "IMPLEMENTATION_INCOMPLETE": "implementation_failure", "GUARD_VIOLATION": "implementation_failure"}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _jdump(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Refused(Exception):
    """A binding refusal BEFORE any child is spawned."""


# ------------------------------------------------------------- inputs

def restore_inputs(packet_zip, dest, expected):
    """Extract ONLY the expected input members (name -> sha256) from the packet
    into `dest`, verifying each hash; refuse if a reference file is present in
    `dest` or any extracted byte string hashes differently. Nothing else is
    extracted; the packet's `.MAR` members are never opened."""
    os.makedirs(dest, exist_ok=True)
    present_refs = [f for f in os.listdir(dest) if f.lower().endswith(".mar")]
    if present_refs:
        raise Refused("reference files present in the solver input directory %s: %s" % (dest, present_refs))
    got = {}
    with zipfile.ZipFile(packet_zip) as z:
        names = set(z.namelist())
        for name, want in expected.items():
            member = PACKET_MEMBER_PREFIX + name
            if member not in names:
                raise Refused("packet lacks input member %s" % member)
            if name.lower().endswith(".mar"):
                raise Refused("a reference file is listed as an input: %s" % name)
            data = z.read(member)
            h = hashlib.sha256(data).hexdigest()
            if h != want:
                raise Refused("input %s hashes %s, expected %s" % (name, h[:16], want[:16]))
            with open(os.path.join(dest, name), "wb") as fh:
                fh.write(data)
            got[name] = h
    return got


# ------------------------------------------------------------- bindings

def resolved_runtime(python=None):
    py = python or sys.executable
    code = ("import sys, json, platform\n"
            "try:\n    import gmpy2; g = [gmpy2.version(), gmpy2.mpfr_version()]\nexcept Exception as e:\n    g = ['missing: %s' % e, None]\n"
            "print(json.dumps({'executable': sys.executable, 'version': sys.version.split()[0], 'version_info': list(sys.version_info[:3]),"
            " 'gmpy2': g[0], 'mpfr': g[1], 'platform': platform.platform()}))")
    out = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise Refused("the interpreter %s could not report its runtime: %s" % (py, out.stderr[-300:]))
    rt = json.loads(out.stdout)
    rt["executable_realpath"] = os.path.realpath(rt["executable"])
    return rt


def validate_bindings(bindings, pin, root, input_dir, python=None):
    """Every binding is checked here, in one place, BEFORE any child exists.
    Returns the resolved record; raises Refused with the first problems."""
    problems = []
    # 1. pinned source tree (the accepted engine build)
    if pin.get("commit") != bindings.get("engine_commit"):
        problems.append("BUILD_PIN commit %s differs from the bindings' engine commit %s" % (pin.get("commit"), bindings.get("engine_commit")))
    tree = pin.get("code_tree_sha256") or {}
    if not tree:
        problems.append("BUILD_PIN carries no source hashes")
    mism = []
    for rel, want in tree.items():
        p = os.path.join(root, rel[len("code/"):] if rel.startswith("code/") else rel)
        if not os.path.exists(p):
            mism.append("%s: missing" % rel)
        elif sha256_file(p) != want:
            mism.append("%s: hash differs" % rel)
    if mism:
        problems.append("pinned source files differ from the tree under test: %s" % mism[:6])
    # 2. frozen configuration of the engine under test (imported from `root`)
    sys.path.insert(0, root)
    try:
        from mdi import config as K, budget as B
    finally:
        sys.path.pop(0)
    lim = bindings["engine_limits"]
    cfg = {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]),
           "threads": int(K.RESOURCES["threads"]), "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)}
    want = {"arm_wall_s": float(lim["arm_wall_s"]), "arm_rss_bytes": int(lim["arm_rss_bytes"]), "threads": int(lim["threads"]),
            "max_width": str(Fr(lim["max_width"])), "phase_limits": {k: float(v) for k, v in lim["phase_limits"].items()}}
    if cfg != want:
        problems.append("frozen configuration differs: engine %s, bindings %s" % (cfg, want))
    if not bindings.get("synthetic_control") and float(bindings["cell_wall_s"]) != float(K.RESOURCES["arm_wall_s"]):
        problems.append("cell wall %s differs from the frozen arm wall %s" % (bindings["cell_wall_s"], K.RESOURCES["arm_wall_s"]))
    # 3. inputs in the arm's input directory
    inputs = {}
    for name, want_h in bindings["inputs"].items():
        p = os.path.join(input_dir, name)
        if not os.path.exists(p):
            problems.append("input %s is missing from %s" % (name, input_dir))
            continue
        h = sha256_file(p)
        inputs[name] = h
        if h != want_h:
            problems.append("input %s hashes %s, bindings expect %s" % (name, h[:16], want_h[:16]))
    refs = [f for f in os.listdir(input_dir)] if os.path.isdir(input_dir) else []
    if any(f.lower().endswith(".mar") for f in refs):
        problems.append("reference files are present in the solver input directory")
    # 4. resolved runtime (recorded; refused only below the required floor)
    rt = resolved_runtime(python)
    if tuple(rt["version_info"][:2]) < (3, 12) or str(rt["gmpy2"]).startswith("missing"):
        problems.append("runtime below the contract: %s" % rt)
    if problems:
        raise Refused("; ".join(problems))
    return {"pin_commit": pin["commit"], "pinned_files_verified": len(tree), "configuration": cfg,
            "inputs": inputs, "runtime": rt}


# ------------------------------------------------------------- ledger

def _empty_ledger(bindings):
    return {"allowance_s": float(bindings["allowance_s"]), "cell_wall_s": float(bindings["cell_wall_s"]),
            "session_cap_s": float(bindings["session_cap_s"]),
            "previous_expenditure_s": dict(bindings.get("previous_expenditure_s") or {}),
            "preparation_s": 0.0, "closeout_s": 0.0, "charges": [],
            "cells": [{"label": "%s_%s" % (p, a), "problem": p, "arm": a, "status": "PENDING", "attempts": []}
                      for p, a in bindings["order"]],
            "repair": {"used": False},
            "note": "charged_s is the supervisor-measured wall of every attempt (initial and repair), spawn to exit; "
                    "preparation, closeout and other charges are accounted separately and never reset"}


def load_ledger(rundir, bindings):
    p = os.path.join(rundir, "LEDGER.json")
    if os.path.exists(p):
        return json.load(open(p))
    led = _empty_ledger(bindings)
    _jdump(led, p)
    return led


def charged_cells_s(led):
    return sum(float(a.get("charged_s") or 0.0) for c in led["cells"] for a in c["attempts"])


def other_charges_s(led):
    return float(led.get("preparation_s") or 0) + float(led.get("closeout_s") or 0) + sum(float(c["seconds"]) for c in led.get("charges") or [])


def session_remaining_s(led):
    return led["session_cap_s"] - sum(float(v) for v in led["previous_expenditure_s"].values()) - charged_cells_s(led) - other_charges_s(led)


def repair_balance_s(led, label):
    """Unused time inside the six-cell allowance after 600 s is reserved for
    every UNSTARTED initial cell (never the cell being repaired)."""
    unstarted = sum(1 for c in led["cells"] if not c["attempts"] and c["label"] != label and c["status"] not in ("NOT_RUN_CUMULATIVE_STOP",))
    return led["allowance_s"] - charged_cells_s(led) - led["cell_wall_s"] * unstarted


def _classify(sup, arm_rec, receipt, wall):
    so = sup.get("outcome")
    if so == "TIMEOUT":
        return "resource_refusal", "killed by the supervisor at its deadline (wall %.1f s plus the declared durable-write grace)" % wall
    if so == "MEMORY_STOP":
        return "resource_refusal", "supervisor memory limit"
    if so in ("LAUNCH_FAILURE", "NONZERO_EXIT") and not arm_rec:
        return "implementation_failure", "child %s rc=%s without a durable record" % (so, sup.get("returncode"))
    if not arm_rec:
        return "implementation_failure", "no durable arm record"
    out = arm_rec.get("outcome")
    cls = CLASSES.get(out, "implementation_failure")
    if out in ("CERTIFIED_RESEARCH_ROUTE", "CERTIFIED_FALLBACK_ONLY", "ZERO_EVIDENCE_PROVED"):
        if not (receipt and receipt.get("within_wall")) or float(sup.get("elapsed_s") or 0) > wall:
            return "resource_refusal", "%s completed but not within the %.1f s wall (receipt within_wall=%s, supervisor %.3f s)" % (
                out, wall, (receipt or {}).get("within_wall"), float(sup.get("elapsed_s") or 0))
    return cls, str(arm_rec.get("reason") or "")[:200]


# ------------------------------------------------------------- the run

def default_cmd_factory(python):
    def f(problem, arm, attempt_dir, wall):
        return [python, "-m", "mdi.launch", "--cell", problem, arm, attempt_dir, "%.3f" % wall]
    return f


def write_manifest(rundir, bindings, pin, resolved, argv, launcher_path, bindings_path, pin_path, input_dir, extra=None):
    from ext import supervise as SV
    man = {"written": time.strftime("%Y-%m-%d %H:%M:%S %z"),
           "launcher": {"path": os.path.relpath(launcher_path, HERE), "sha256": sha256_file(launcher_path),
                        "exact_command": list(argv), "cwd": os.getcwd(),
                        "cell_command_template": "<python> -m mdi.launch --cell <problem> <baseline|research> <attempt_dir> <wall_s>"},
           "launcher_commit": _git_head(),
           "engine": {"commit": pin["commit"], "build_pin": {"path": os.path.relpath(pin_path, HERE) if pin_path.startswith(HERE) else pin_path,
                                                             "sha256": sha256_file(pin_path)},
                      "pinned_files_verified": resolved["pinned_files_verified"]},
           "supervisor": {"path": "ext/supervise.py", "sha256": sha256_file(SV.__file__)},
           "arm": {"path": "mdi/arm.py", "sha256": sha256_file(os.path.join(HERE, "mdi", "arm.py"))},
           "bindings": {"path": os.path.relpath(bindings_path, HERE) if bindings_path.startswith(HERE) else bindings_path,
                        "sha256": sha256_file(bindings_path)},
           "contract": {"path": bindings.get("contract", {}).get("path"),
                        "sha256": (sha256_file(os.path.join(HERE, bindings["contract"]["path"])) if bindings.get("contract", {}).get("path")
                                   and os.path.exists(os.path.join(HERE, bindings["contract"]["path"])) else None),
                        "pinned_sha256": bindings.get("contract", {}).get("sha256")},
           "configuration": resolved["configuration"], "runtime": resolved["runtime"], "thread_env": dict(THREAD_ENV),
           "input_dir": input_dir, "inputs": resolved["inputs"], "order": [list(x) for x in bindings["order"]],
           "limits": {"cell_wall_s": bindings["cell_wall_s"], "cap_bytes": bindings["engine_limits"]["arm_rss_bytes"],
                      "allowance_s": bindings["allowance_s"], "session_cap_s": bindings["session_cap_s"],
                      "durable_grace_s": bindings.get("durable_grace_s", 0.0),
                      "note": "the supervisor kills at wall + durable_grace_s; certification requires the arm's receipt within the wall AND supervisor elapsed <= wall; every measured second is charged"},
           "synthetic_control": bool(bindings.get("synthetic_control")),
           "reference_files_opened": False}
    if man["contract"]["pinned_sha256"] and man["contract"]["sha256"] and man["contract"]["pinned_sha256"] != man["contract"]["sha256"]:
        raise Refused("the run contract's hash %s differs from the bindings' pinned %s" % (man["contract"]["sha256"][:16], man["contract"]["pinned_sha256"][:16]))
    if extra:
        man.update(extra)
    mp = os.path.join(rundir, "EXECUTION_MANIFEST.json")
    if os.path.exists(mp):
        prev = json.load(open(mp))
        same = {"launcher": prev["launcher"]["sha256"] == man["launcher"]["sha256"],
                "build_pin": prev["engine"]["build_pin"]["sha256"] == man["engine"]["build_pin"]["sha256"],
                "bindings": prev["bindings"]["sha256"] == man["bindings"]["sha256"],
                "contract": prev["contract"]["sha256"] == man["contract"]["sha256"],
                "supervisor": prev["supervisor"]["sha256"] == man["supervisor"]["sha256"],
                "arm": prev["arm"]["sha256"] == man["arm"]["sha256"],
                "inputs": prev["inputs"] == man["inputs"], "order": prev["order"] == man["order"],
                "configuration": prev["configuration"] == man["configuration"]}
        if not all(same.values()):
            raise Refused("the run directory was prepared under different bindings: %s" % [k for k, v in same.items() if not v])
        prev.setdefault("revalidations", []).append({"at": man["written"], "runtime": man["runtime"], "exact_command": man["launcher"]["exact_command"],
                                                      "launcher_commit": man["launcher_commit"]})
        _jdump(prev, mp)
        return prev
    _jdump(man, mp)
    return man


def _git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def prepare(rundir, bindings, pin, bindings_path, pin_path, packet=None, input_dir=None, python=None, argv=None):
    """Restore inputs, validate every binding, write the manifest; the time is
    charged to `preparation_s`. Raises Refused before any child could exist."""
    t0 = time.time()
    os.makedirs(rundir, exist_ok=True)
    led = load_ledger(rundir, bindings)
    input_dir = input_dir or bindings.get("input_dir") or DEFAULT_INPUT_DIR
    try:
        if packet:
            restore_inputs(packet, input_dir, bindings["inputs"])
        resolved = validate_bindings(bindings, pin, HERE, input_dir, python)
        man = write_manifest(rundir, bindings, pin, resolved, argv or sys.argv, os.path.abspath(__file__), bindings_path, pin_path, input_dir)
    except Refused as e:
        _jdump({"refused": str(e), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "no_child_spawned": True},
               os.path.join(rundir, "REFUSED_%d.json" % int(time.time())))
        led["preparation_s"] = float(led["preparation_s"]) + (time.time() - t0)
        _jdump(led, os.path.join(rundir, "LEDGER.json"))
        raise
    led["preparation_s"] = float(led["preparation_s"]) + (time.time() - t0)
    _jdump(led, os.path.join(rundir, "LEDGER.json"))
    return man, input_dir


def run_cells(rundir, bindings, repair=None, cmd_factory=None, python=None, supervisor=None, manifest_required=True):
    """Run the frozen cells in order. A consumed cell is never rerun; an
    uncertain STARTED cell is marked INTERRUPTED and never silently rerun; the
    ONE repair (`repair=label`) runs only inside the balance; a cell that
    cannot start under the session cap is marked NOT_RUN_CUMULATIVE_STOP."""
    from ext import supervise as SV
    sup_run = supervisor or SV.run
    python = python or sys.executable
    cmd_factory = cmd_factory or default_cmd_factory(python)
    man_path = os.path.join(rundir, "EXECUTION_MANIFEST.json")
    if manifest_required and not os.path.exists(man_path):
        raise Refused("no EXECUTION_MANIFEST.json in %s: prepare (validate bindings) before running" % rundir)
    led = load_ledger(rundir, bindings)
    want = ["%s_%s" % (p, a) for p, a in bindings["order"]]
    if [c["label"] for c in led["cells"]] != want:
        raise Refused("LEDGER.json carries cells %s, the bindings' frozen order is %s: the run directory belongs to another order"
                      % ([c["label"] for c in led["cells"]], want))
    cap_bytes = int(bindings["engine_limits"]["arm_rss_bytes"])
    env = dict(THREAD_ENV)
    env["PYTHONPATH"] = HERE
    lp = os.path.join(rundir, "LEDGER.json")
    # a STARTED attempt without a terminal is UNCERTAIN: mark, never rerun silently
    for c in led["cells"]:
        for a in c["attempts"]:
            if a.get("status") == "STARTED":
                a["status"] = "INTERRUPTED"
                a["interrupted_noted"] = time.strftime("%Y-%m-%d %H:%M:%S")
                c["status"] = "INTERRUPTED"
    _jdump(led, lp)
    for c in led["cells"]:
        label = c["label"]
        is_repair = (repair == label)
        if c["status"] == "CONSUMED" and not is_repair:
            print("  [launch] %-24s consumed (attempts %d): not rerun" % (label, len(c["attempts"])), flush=True)
            continue
        if c["status"] == "INTERRUPTED" and not is_repair:
            print("  [launch] %-24s INTERRUPTED earlier: not rerun without an explicit --repair" % label, flush=True)
            continue
        if c["status"] == "NOT_RUN_CUMULATIVE_STOP" and not is_repair:
            print("  [launch] %-24s not run (cumulative stop recorded earlier)" % label, flush=True)
            continue
        if is_repair:
            if not c["attempts"]:
                print("  [launch] %-24s --repair names a cell that never ran: it runs as its initial cell" % label, flush=True)
                is_repair = False
            elif led["repair"].get("used"):
                c.setdefault("repair_refused", []).append({"reason": "the one repair was already used on %s" % led["repair"].get("label"),
                                                           "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                _jdump(led, lp)
                print("  [launch] %-24s repair REFUSED: the one repair is already used" % label, flush=True)
                continue
        if is_repair:
            balance = repair_balance_s(led, label)
            wall = min(led["cell_wall_s"], balance)
            if wall <= 0:
                c.setdefault("repair_refused", []).append({"reason": "no unused time inside the allowance after reserving %.0f s per unstarted cell (balance %.3f s)"
                                                                     % (led["cell_wall_s"], balance), "balance_s": balance, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                led["repair"] = {"used": False, "refused_for": label, "balance_s": balance}
                _jdump(led, lp)
                print("  [launch] %-24s repair REFUSED: balance %.3f s; the failed outcome stands" % (label, balance), flush=True)
                continue
        else:
            wall = led["cell_wall_s"]                       # an initial cell is NEVER shortened
        if session_remaining_s(led) < wall:
            c["status"] = "NOT_RUN_CUMULATIVE_STOP"
            c["cumulative_stop"] = {"session_remaining_s": session_remaining_s(led), "needed_s": wall, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            _jdump(led, lp)
            print("  [launch] %-24s NOT RUN: cumulative session cap (remaining %.1f s < %.1f s)" % (label, session_remaining_s(led), wall), flush=True)
            continue
        n = len(c["attempts"]) + 1
        adir = os.path.join(rundir, "cells", label, "attempt_%d" % n)
        if os.path.exists(adir):
            raise Refused("attempt directory %s already exists but the ledger does not know it: the run directory is inconsistent" % adir)
        os.makedirs(adir)
        cmd = cmd_factory(c["problem"], c["arm"], adir, wall)
        att = {"n": n, "kind": "repair" if is_repair else "initial", "dir": os.path.relpath(adir, rundir), "wall_granted_s": wall,
               "supervisor_kill_deadline_s": wall + float(bindings.get("durable_grace_s", 0.0)),
               "command": cmd, "status": "STARTED", "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        c["attempts"].append(att)
        c["status"] = "STARTED"
        if is_repair:
            led["repair"] = {"used": True, "label": label, "balance_s": repair_balance_s(led, label), "wall_granted_s": wall}
        _jdump(led, lp)                                      # durable STARTED before the spawn
        print("  [launch] %-24s %s attempt %d wall %.1f s ..." % (label, att["kind"], n, wall), flush=True)
        # the supervisor's kill deadline is the wall plus a DECLARED durable-write grace
        # (process start-up and the arm's own terminal record); classification and
        # the receipt stay strict at the wall, and the whole measured time is charged
        grace = float(bindings.get("durable_grace_s", 0.0))
        sup = sup_run(cmd, cwd=HERE, log_path=os.path.join(adir, "supervisor.log"), deadline_s=wall + grace,
                      mem_limit_kib=cap_bytes // 1024, env=env, label=label)
        arm_rec = receipt = None
        pa, pr = os.path.join(adir, "arm_%s.json" % label), os.path.join(adir, "arm_%s.receipt.json" % label)
        if os.path.exists(pa):
            try:
                arm_rec = json.load(open(pa))
            except ValueError:
                arm_rec = None
        if os.path.exists(pr):
            try:
                receipt = json.load(open(pr))
            except ValueError:
                receipt = None
        cls, why = _classify(sup, arm_rec, receipt, wall)
        att.update({"status": "TERMINAL", "ended": time.strftime("%Y-%m-%d %H:%M:%S"), "charged_s": float(sup.get("elapsed_s") or 0.0),
                    "supervisor": {k: sup.get(k) for k in ("outcome", "returncode", "elapsed_s", "peak_tree_rss_kib", "peak_tree_procs", "mem_samples", "mem_limitation")},
                    "arm_outcome": (arm_rec or {}).get("outcome"), "arm_reason": str((arm_rec or {}).get("reason") or "")[:300],
                    "arm_elapsed_s": (arm_rec or {}).get("elapsed_s"), "final_max_width": (arm_rec or {}).get("final_max_width"),
                    "receipt": receipt, "class": cls, "class_reason": why})
        c["status"] = "CONSUMED"
        _jdump(led, lp)
        print("  [launch] %-24s %s: %s (%s) charged %.1f s; cumulative %.1f of %.0f s" % (
            label, att["kind"], cls, (arm_rec or {}).get("outcome") or sup.get("outcome"), att["charged_s"], charged_cells_s(led), led["allowance_s"]), flush=True)
    _jdump(led, lp)
    return led


def closeout(rundir, bindings):
    t0 = time.time()
    led = load_ledger(rundir, bindings)
    rows = []
    for c in led["cells"]:
        last = c["attempts"][-1] if c["attempts"] else None
        rows.append({"label": c["label"], "status": c["status"], "attempts": len(c["attempts"]),
                     "class": (last or {}).get("class"), "arm_outcome": (last or {}).get("arm_outcome"),
                     "charged_s": sum(float(a.get("charged_s") or 0) for a in c["attempts"]),
                     "final_max_width": (last or {}).get("final_max_width")})
    led["closeout_s"] = float(led["closeout_s"]) + (time.time() - t0)
    summary = {"cells": rows, "charged_cells_s": charged_cells_s(led), "allowance_s": led["allowance_s"],
               "preparation_s": led["preparation_s"], "closeout_s": led["closeout_s"], "charges": led["charges"],
               "previous_expenditure_s": led["previous_expenditure_s"], "session_remaining_s": session_remaining_s(led),
               "repair": led["repair"], "built": time.strftime("%Y-%m-%d %H:%M:%S")}
    _jdump(led, os.path.join(rundir, "LEDGER.json"))
    _jdump(summary, os.path.join(rundir, "SUMMARY.json"))
    return summary


def charge(rundir, bindings, what, seconds):
    led = load_ledger(rundir, bindings)
    led["charges"].append({"what": what, "seconds": float(seconds), "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    _jdump(led, os.path.join(rundir, "LEDGER.json"))
    return led


# ------------------------------------------------------------- CLI

def _cell_main(argv):
    """The child: ONE arm in this process (the supervisor spawned us)."""
    sys.path.insert(0, HERE)
    from mdi import arm as ARM
    import mdi.registry            # noqa: F401
    problem, arm, adir, wall = argv[0], argv[1], os.path.abspath(argv[2]), float(argv[3])
    rec = ARM.run_arm(problem, arm == "research", adir, wall=wall, support=(arm == "support"))
    print(json.dumps({k: rec.get(k) for k in ("problem", "arm", "outcome", "reason", "elapsed_s", "final_max_width")}, default=str))
    return 0


def main(argv):
    if argv and argv[0] == "--cell":
        return _cell_main(argv[1:])
    if not argv:
        print(__doc__)
        return 2
    rundir = os.path.abspath(argv[0])
    opts = {"--bindings": DEFAULT_BINDINGS, "--pin": None, "--packet": None, "--input-dir": None, "--repair": None}
    flags = set()
    charge_args = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in opts and i + 1 < len(argv):
            opts[a] = argv[i + 1]; i += 2
        elif a in ("--prepare-only", "--closeout"):
            flags.add(a); i += 1
        elif a == "--charge" and i + 2 < len(argv):
            charge_args = (argv[i + 1], float(argv[i + 2])); i += 3
        else:
            raise SystemExit("unknown or incomplete option %s" % a)
    bindings_path = os.path.abspath(opts["--bindings"])
    bindings = json.load(open(bindings_path))
    if charge_args:
        charge(rundir, bindings, *charge_args)
        print("charged %s: %.3f s" % charge_args)
        return 0
    if "--closeout" in flags:
        s = closeout(rundir, bindings)
        print(json.dumps(s, indent=1, default=str))
        return 0
    cmdline = [sys.executable, "-m", "mdi.launch"] + list(argv)           # the exact command, module form
    pin_path = os.path.abspath(opts["--pin"] or os.path.join(HERE, bindings["build_pin"]["path"]))
    pin = json.load(open(pin_path))
    if bindings.get("build_pin", {}).get("sha256") and sha256_file(pin_path) != bindings["build_pin"]["sha256"]:
        raise SystemExit("BUILD_PIN %s does not hash to the bindings' pinned value" % pin_path)
    try:
        man, input_dir = prepare(rundir, bindings, pin, bindings_path, pin_path, packet=opts["--packet"],
                                 input_dir=opts["--input-dir"], argv=cmdline)
    except Refused as e:
        print("REFUSED before any child was spawned: %s" % e)
        return 3
    print("manifest written: engine %s, launcher %s, %d pinned files verified, runtime %s %s" % (
        man["engine"]["commit"][:12], man["launcher"]["sha256"][:12], man["engine"]["pinned_files_verified"],
        man["runtime"]["version"], man["runtime"]["gmpy2"]))
    if "--prepare-only" in flags:
        return 0
    led = run_cells(rundir, bindings, repair=opts["--repair"])
    print(json.dumps({"charged_cells_s": charged_cells_s(led), "allowance_s": led["allowance_s"],
                      "cells": {c["label"]: c["status"] for c in led["cells"]}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
