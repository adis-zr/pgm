"""Treatment-arm SHIM and pair orchestrator for the fixed synthetic failed-discovery pair (4 November 2026).

Limited glue over the pinned launcher: `mdi.launch.prepare` (binding validation, manifest), `mdi.launch.run_cells`
(ledger, attempts, the unchanged supervisor, classification) and `mdi.launch.closeout` are REUSED; the ONLY addition is
the child command of the treatment arm, which runs this file so that `mdi.selector_pilot.enable()` installs the opt-in
hooks in THAT process alone before the pinned cell entry `mdi.launch._cell_main` runs. The baseline cell keeps the pinned
`python -m mdi.launch --cell PROBLEM baseline ...` command: no shim, hooks disabled (the default). The shim's hash and the
exact cell commands are recorded in EXECUTION_MANIFEST.json under `pilot_glue`.

    pilot_pair_launch.py RUNDIR --bindings B.json [--pin PIN.json] [--input-dir DIR] [--prepare-only] [--closeout]
                                [--charge WHAT SECONDS]
    pilot_pair_launch.py --cell PROBLEM selector ATTEMPT_DIR WALL_S INPUT_DIR        (the treatment child)
    pilot_pair_launch.py --tiny-control OUTDIR [certified|censored]
            (glue control: a two-variable [1,1,1,0] pair, tiny synthetic pin / bindings, no external input; run it under the
             10 s / 1 GiB / no-grace supervisor; `censored` gives the baseline a 0.05 s wall so the frozen stop rule is exercised)
"""
from __future__ import annotations
import sys, os, json, time, hashlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # code/
sys.path.insert(0, HERE)
from mdi import launch as L

SHIM = os.path.abspath(__file__)


def cmd_factory(python, input_dir, rundir=None):
    """The pinned default command for every arm except the treatment, whose child is this shim. With `rundir`, the frozen
    stop rule: the treatment's command is REFUSED (the launcher asks for the command before it records a STARTED attempt and
    before any spawn) when the same problem's baseline attempt is not a within-wall certification."""
    base = L.default_cmd_factory(python, input_dir)

    def f(problem, arm, adir, wall):
        if arm == "selector":
            if rundir is not None:
                led = json.load(open(os.path.join(rundir, "LEDGER.json")))
                bl = [c for c in led["cells"] if c["problem"] == problem and c["arm"] == "baseline"]
                last = bl[0]["attempts"][-1] if bl and bl[0]["attempts"] else None
                if last is None or last.get("status") != "TERMINAL" or last.get("class") != "certified_fallback" or not str(last.get("arm_outcome") or "").startswith("CERTIFIED"):
                    raise BaselineNotCertified(problem, last)
            return [python, SHIM, "--cell", problem, "selector", adir, "%.3f" % wall, input_dir]
        return base(problem, arm, adir, wall)
    return f


class BaselineNotCertified(L.Refused):
    """The frozen stop rule: a censored or invalid baseline stops the pair before the treatment is spawned."""

    def __init__(self, problem, last):
        self.problem, self.last = problem, last
        L.Refused.__init__(self, "baseline of %s is not a within-wall certification (%s): the treatment cell is NOT run" % (
            problem, None if last is None else {k: last.get(k) for k in ("class", "arm_outcome", "class_reason", "charged_s")}))


def _cell(argv):
    """The treatment child: enable the opt-in pilot in this process, then the pinned cell entry."""
    if len(argv) < 5 or argv[1] != "selector":
        raise SystemExit("the shim runs ONLY the treatment (selector) arm with an explicit INPUT_DIR; the baseline uses the pinned mdi.launch command")
    from mdi import selector_pilot as SPL, pipeline as PLN
    SPL.enable()
    if PLN._select_route.__module__ != "mdi.selector_pilot" or len(PLN._PILOT_HOOKS) != 7:
        raise SystemExit("the pilot did not install (selector %s, %d hooks)" % (PLN._select_route.__module__, len(PLN._PILOT_HOOKS)))
    return L._cell_main(argv)


def _glue_block(bindings, input_dir, python):
    fac = cmd_factory(python, input_dir)
    return {"shim": {"path": os.path.relpath(SHIM, HERE), "sha256": L.sha256_file(SHIM)},
            "generator": bindings.get("generator"),
            "cell_commands": {"%s_%s" % (p, a): fac(p, a, "<attempt_dir>", float(bindings["cell_wall_s"])) for p, a in bindings["order"]},
            "baseline": "pinned `python -m mdi.launch --cell PROBLEM baseline ATTEMPT_DIR WALL_S INPUT_DIR`; mdi.pipeline._PILOT_HOOKS stays empty (hooks disabled)",
            "treatment": "this shim: mdi.selector_pilot.enable() in the child process, then mdi.launch._cell_main(PROBLEM selector ...)",
            "launcher_reused": ["mdi.launch.prepare (validate_bindings, write_manifest)", "mdi.launch.run_cells (ledger, supervisor, _classify)", "mdi.launch.closeout", "mdi.launch.charge"]}


def _orchestrate(argv):
    rundir = os.path.abspath(argv[0])
    opts = {"--bindings": None, "--pin": None, "--input-dir": None}
    flags = set(); charge_args = None
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
    if not opts["--bindings"]:
        raise SystemExit("--bindings is required")
    bindings_path = os.path.abspath(opts["--bindings"])
    bindings = json.load(open(bindings_path))
    if charge_args:
        L.charge(rundir, bindings, *charge_args)
        print("charged %s: %.3f s" % charge_args)
        return 0
    if "--closeout" in flags:
        s = L.closeout(rundir, bindings)
        print(json.dumps(s, indent=1, default=str))
        return 0
    cmdline = [sys.executable, SHIM] + list(argv)
    pin_path = os.path.abspath(opts["--pin"] or os.path.join(HERE, bindings["build_pin"]["path"]))
    pin = json.load(open(pin_path))
    if bindings.get("build_pin", {}).get("sha256") and L.sha256_file(pin_path) != bindings["build_pin"]["sha256"]:
        raise SystemExit("BUILD_PIN %s does not hash to the bindings' pinned value" % pin_path)
    try:
        man, input_dir = L.prepare(rundir, bindings, pin, bindings_path, pin_path, packet=None, input_dir=opts["--input-dir"], argv=cmdline)
    except L.Refused as e:
        print("REFUSED before any child was spawned: %s" % e)
        return 3
    # the glue block: the shim's hash and the exact cell commands (verified unchanged on every later invocation)
    glue = _glue_block(bindings, input_dir, sys.executable)
    mp = os.path.join(rundir, "EXECUTION_MANIFEST.json")
    man = json.load(open(mp))
    if "pilot_glue" in man:
        if man["pilot_glue"]["shim"]["sha256"] != glue["shim"]["sha256"] or man["pilot_glue"]["cell_commands"] != glue["cell_commands"]:
            print("REFUSED before any child was spawned: the shim or the cell commands differ from the prepared manifest")
            return 3
    else:
        man["pilot_glue"] = glue
        L._jdump(man, mp)
    print("manifest written: engine %s, launcher %s, shim %s, %d pinned files verified, runtime %s %s" % (
        man["engine"]["commit"][:12], man["launcher"]["sha256"][:12], glue["shim"]["sha256"][:12], man["engine"]["pinned_files_verified"],
        man["runtime"]["version"], man["runtime"]["gmpy2"]))
    if "--prepare-only" in flags:
        led = L.load_ledger(rundir, bindings)
        print(json.dumps({"cells": {c["label"]: {"status": c["status"], "attempts": len(c["attempts"])} for c in led["cells"]}, "preparation_s": led["preparation_s"]}))
        return 0
    try:
        led = L.run_cells(rundir, bindings, cmd_factory=cmd_factory(sys.executable, input_dir, rundir=rundir))
    except BaselineNotCertified as e:
        # the launcher created the treatment's attempt directory and then asked for its command; nothing was spawned and no
        # attempt was recorded. The cell is marked explicitly (the launcher's own convention for not-run cells); the stop is kept.
        lp = os.path.join(rundir, "LEDGER.json"); led = json.load(open(lp))
        for c in led["cells"]:
            if c["arm"] == "selector" and c["problem"] == e.problem and not c["attempts"]:
                c["status"] = "NOT_RUN_BASELINE_NOT_CERTIFIED"
                c["baseline_stop"] = {"reason": str(e), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                      "note": "no process was spawned for this cell; its empty attempt_1 directory was created by the launcher before the command was requested"}
        L._jdump(led, lp)
        L._jdump({"stop": "BASELINE_NOT_CERTIFIED", "reason": str(e), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "treatment_spawned": False},
                 os.path.join(rundir, "STOP_BASELINE_NOT_CERTIFIED.json"))
        print("STOP: %s" % e)
        return 4
    print(json.dumps({"charged_cells_s": L.charged_cells_s(led), "allowance_s": led["allowance_s"],
                      "cells": {c["label"]: c["status"] for c in led["cells"]}}, indent=1))
    return 0


def _tiny_control(outdir, mode="certified"):
    """Glue control (no external input): a two-variable [1,1,1,0] model (4 assignments; the natural rejection) as a baseline /
    selector pair through prepare-only, run and closeout with a tiny synthetic pin and bindings. Asserts: baseline record has
    a NULL selector block (hooks disabled, dense); treatment record carries the pilot's selector block, both probes started and
    were rejected (NOT_ADMITTED), and the dense route ran;
    both CERTIFIED; manifest records the shim hash and the exact commands; every charge is a finite number."""
    os.makedirs(outdir, exist_ok=False)
    idir = os.path.join(outdir, "inputs"); os.makedirs(idir)
    inputs = {"Tiny_nat2.uai": b"MARKOV\n2\n2 2\n1\n2 0 1\n\n4\n 1 1 1 0\n", "Tiny_nat2.uai.evid": b"0\n"}
    for n, d in inputs.items():
        open(os.path.join(idir, n), "wb").write(d)
    pinned = ["code/mdi/launch.py", "code/ext/supervise.py", "code/mdi/pipeline.py", "code/mdi/selector_pilot.py", "code/ext/pilot_pair_launch.py"]
    pin = {"commit": "tiny-glue-control", "code_tree_sha256": {rel: L.sha256_file(os.path.join(HERE, rel[5:])) for rel in pinned}}
    pp = os.path.join(outdir, "TINY_PIN.json"); json.dump(pin, open(pp, "w"), indent=1)
    from mdi import config as K, budget as B
    order = [["Tiny_nat2", "baseline"], ["Tiny_nat2", "selector"]]
    b = {"engine_commit": "tiny-glue-control", "build_pin": {"path": pp, "sha256": L.sha256_file(pp)}, "input_dir": idir,
         "inputs": {n: hashlib.sha256(d).hexdigest() for n, d in inputs.items()},
         "engine_limits": {"arm_wall_s": float(K.RESOURCES["arm_wall_s"]), "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"]),
                           "threads": int(K.RESOURCES["threads"]), "max_width": str(K.MAX_WIDTH), "phase_limits": dict(B.Budget.PHASE_LIMITS)},
         "cell_wall_s": (60.0 if mode == "certified" else 0.05), "durable_grace_s": 0.0, "allowance_s": 120.0, "session_cap_s": 200.0, "previous_expenditure_s": {},
         "mode": mode, "censored_mode_note": ("a 0.05 s cell wall censors the baseline (supervisor TIMEOUT); the frozen stop rule must then refuse the treatment before any spawn" if mode != "certified" else None),
         "cell_wall_note": "the ENGINE's budget per tiny cell (the frozen selector precondition needs remaining wall >= 20 s window + dense forecast + 30 s margin, so a 10 s budget would skip the probes); the control itself runs under the OUTER 10 s / 1 GiB / no-grace supervisor, which is the binding limit",
         "order": order, "synthetic_control": True, "name": "tiny glue control: the shim's treatment child and the pinned baseline child"}
    bp = os.path.join(outdir, "TINY_BINDINGS.json"); json.dump(b, open(bp, "w"), indent=1)
    rd = os.path.join(outdir, "run")
    rc = _orchestrate([rd, "--bindings", bp, "--prepare-only"]); assert rc == 0, rc
    led = L.load_ledger(rd, b)
    assert [c["status"] for c in led["cells"]] == ["PENDING", "PENDING"] and all(not c["attempts"] for c in led["cells"])
    rc = _orchestrate([rd, "--bindings", bp])
    s = L.closeout(rd, b)
    led = L.load_ledger(rd, b); man = json.load(open(os.path.join(rd, "EXECUTION_MANIFEST.json")))
    res = {"mode": mode, "cells": {}, "manifest_shim_sha256": man["pilot_glue"]["shim"]["sha256"], "shim_sha256_now": L.sha256_file(SHIM), "summary": s}
    import math
    if mode != "certified":
        assert rc == 4, rc
        base, trt = led["cells"]
        a = base["attempts"][0]
        res["cells"] = {base["label"]: {"status": base["status"], "class": a["class"], "supervisor": a["supervisor"]["outcome"], "charged_s": a["charged_s"], "arm_outcome": a.get("arm_outcome")},
                        trt["label"]: {"status": trt["status"], "attempts": len(trt["attempts"]), "baseline_stop": trt.get("baseline_stop")}}
        # censored either by the supervisor (TIMEOUT) or by the arm's own wall (RESOURCE_STOP past 0.05 s): both are the launcher's resource_refusal
        assert base["status"] == "CONSUMED" and a["class"] == "resource_refusal" and (a["supervisor"]["outcome"] == "TIMEOUT" or a.get("arm_outcome") == "RESOURCE_STOP")
        assert isinstance(a["charged_s"], (int, float)) and math.isfinite(a["charged_s"]) and a["charged_s"] >= 0
        assert trt["status"] == "NOT_RUN_BASELINE_NOT_CERTIFIED" and not trt["attempts"] and os.path.exists(os.path.join(rd, "STOP_BASELINE_NOT_CERTIFIED.json"))
        assert not os.listdir(os.path.join(rd, "cells", trt["label"], "attempt_1"))        # created by the launcher, never used: no spawn
        assert res["manifest_shim_sha256"] == res["shim_sha256_now"]
        res["ok"] = True
        json.dump(res, open(os.path.join(outdir, "RESULT.json"), "w"), indent=1, default=str)
        print(json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1, default=str))
        return 0
    assert rc == 0, rc
    for c in led["cells"]:
        a = c["attempts"][0]
        arm = json.load(open(os.path.join(rd, a["dir"], "arm_%s.json" % c["label"])))
        plan = (arm.get("pipeline") or {}).get("plan") or {}
        res["cells"][c["label"]] = {"status": c["status"], "class": a["class"], "outcome": arm["outcome"], "supervisor": a["supervisor"]["outcome"], "charged_s": a["charged_s"],
                                   "command": a["command"], "route_policy": plan.get("route_policy"), "has_selector_block": plan.get("selector") is not None,
                                   "pilot": (plan.get("selector") or {}).get("pilot"), "executed_route": (plan.get("selector") or {}).get("executed_route"),
                                   "attempt_verdicts": [(x["mechanism"], x["verdict"]) for x in (plan.get("selector") or {}).get("attempts", [])],
                                   "planning_envelope_wall_s": (plan.get("selector") or {}).get("planning_envelope_wall_s")}
        assert isinstance(a["charged_s"], (int, float)) and math.isfinite(a["charged_s"]) and a["charged_s"] >= 0
        assert c["status"] == "CONSUMED" and a["class"] == "certified_fallback" and arm["outcome"] == "CERTIFIED_FALLBACK_ONLY" and a["supervisor"]["outcome"] == "COMPLETED"
        tmpl = [os.path.join(rd, a["dir"]) if x == "<attempt_dir>" else x for x in man["pilot_glue"]["cell_commands"][c["label"]]]
        assert a["command"] == tmpl, (a["command"], tmpl)
    base, trt = res["cells"]["Tiny_nat2_baseline"], res["cells"]["Tiny_nat2_selector"]
    assert base["route_policy"] == "dense" and not base["has_selector_block"] and base["command"][1:4] == ["-m", "mdi.launch", "--cell"]
    assert trt["route_policy"] == "selector" and str(trt["pilot"]).startswith("selector_pilot") and trt["executed_route"] == "dense" and trt["command"][1] == SHIM
    assert [tuple(x) for x in trt["attempt_verdicts"]] == [("quotient", "NOT_ADMITTED"), ("support", "NOT_ADMITTED")], trt["attempt_verdicts"]      # both probes genuinely started and were rejected
    assert trt["planning_envelope_wall_s"] is not None and trt["planning_envelope_wall_s"] > 0
    assert res["manifest_shim_sha256"] == res["shim_sha256_now"]
    res["ok"] = True
    json.dump(res, open(os.path.join(outdir, "RESULT.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in res.items() if k != "summary"}, indent=1, default=str))
    return 0


def main(argv):
    if argv and argv[0] == "--cell":
        return _cell(argv[1:])
    if argv and argv[0] == "--tiny-control":
        return _tiny_control(os.path.abspath(argv[1]), mode=(argv[2] if len(argv) > 2 else "certified"))
    if not argv:
        print(__doc__); return 2
    return _orchestrate(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
