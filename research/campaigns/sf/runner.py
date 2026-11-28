"""Manifest builder and executor. ONE allowance ledger (3,600 s of measured experiment wall: every supervised child's complete
spawn-to-exit wall, charged once; unknown charges recorded as unknown). Each invocation: deadline = min(120 s, remaining); a launch that
does not fit is marked UNATTEMPTED_ALLOWANCE. Candidate artifacts of a cell are SEALED (hashed) before that cell's references run.
Diagnostic routes already executed on a cell (by the selector or an earlier diagnostic) are reused without a new invocation."""
import sys, os, json, time, math, hashlib, subprocess
from research.paths import repo_root, runs_root, subprocess_env
HERE = str(repo_root())
from fractions import Fraction as Fr
from research.comparators.legacy_ext import supervise as SV
from pgm.algorithms.sf import core as C

E = str(runs_root() / "mdi_2026-10-28" / "SF_BRIDGE_2026-11-06")
PY = sys.executable
ALLOWANCE_S = 3600.0; CAP_S = 120.0; MEM = 8 * (1 << 30)
PANEL_ORDER = ["small_control", "primary_A", "primary_B", "ordinary_control"]
INTERIOR = [r for r in C.R_PRIORITY if 0 < r < 1]


def _j(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def cell_dir(panel, r):
    return os.path.join(E, "cells", panel, C.r_label(r).replace("/", "_").replace("^", "p"))


def build_manifest():
    """The frozen invocation list (Part B schedule), expanded before any outcome."""
    inv = []
    def add(stage, panel, r, kind, route=None, eps=None, rep=0):
        inv.append({"id": len(inv), "stage": stage, "panel": panel, "r": str(r), "kind": kind, "route": route, "eps": (str(eps) if eps else None), "rep": rep})
    for r in C.R_PRIORITY:
        for p in PANEL_ORDER:
            for eps in C.WIDTHS:
                add("core", p, r, "select", eps=eps)
            if 0 < r < 1:
                add("core", p, r, "diag", route="F0")
            if r in (Fr(1, 64), Fr(1, 128), Fr(1, 256)):
                for k in (1, 2, 3):
                    add("core", p, r, "diag", route="F%d" % k)
            if r in (Fr(1) - Fr(1, 2 ** 24), Fr(1) - Fr(1, 2 ** 12)):
                for h in (0, 1):
                    add("core", p, r, "diag", route="S%d" % h)
            add("core", p, r, "seal")
            add("core", p, r, "reference", route="E")
            if p == "small_control":
                add("core", p, r, "reference", route="W")
    for rep in (1, 2):
        for p in ("primary_A", "primary_B"):
            add("repeat", p, Fr(1, 64), "select", eps=Fr(1, 100), rep=rep)
            add("repeat", p, Fr(1, 64), "reference", route="E", rep=rep)
    for p in ("primary_A", "primary_B", "ordinary_control"):
        add("optional_W", p, Fr(1, 64), "reference", route="W")
    return inv


def load_ledger(lp):
    if os.path.exists(lp):
        return json.load(open(lp))
    return {"allowance_s": ALLOWANCE_S, "cap_per_invocation_s": CAP_S, "mem_cap_bytes": MEM, "charges": [], "unknown_charges": [], "unattempted": [], "reused": []}


def charged(led):
    return sum(float(c["charged_s"]) for c in led["charges"] if c.get("status") == "TERMINAL")


def launch(led, lp, item, cmd, out_json, log):
    remaining = led["allowance_s"] - charged(led)
    deadline = min(CAP_S, remaining)
    if deadline < 5.0:
        led["unattempted"].append({**item, "reason": "allowance exhausted (remaining %.3f s)" % remaining}); _j(led, lp); return None
    led["charges"].append({**item, "status": "STARTED", "deadline_s": deadline, "command": cmd, "artifact": out_json, "charged_s": None, "started": time.strftime("%Y-%m-%d %H:%M:%S")}); _j(led, lp)
    sup = SV.run(cmd, cwd=HERE, log_path=log, deadline_s=deadline, mem_limit_kib=MEM // 1024, env=subprocess_env({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"}), label="sf:%s" % item["id"])
    row = led["charges"][-1]
    el = sup.get("elapsed_s")
    if not isinstance(el, (int, float)) or not math.isfinite(el) or el < 0:
        row["status"] = "UNKNOWN_CHARGE"; led["unknown_charges"].append(item["id"]); _j(led, lp); return sup
    row.update({"status": "TERMINAL", "charged_s": el, "supervisor": {k: sup.get(k) for k in ("outcome", "returncode", "peak_tree_rss_kib", "mem_samples")}, "ended": time.strftime("%Y-%m-%d %H:%M:%S")})
    _j(led, lp)
    return sup


def run(stages):
    lp = os.path.join(E, "ALLOWANCE_LEDGER.json"); led = load_ledger(lp)
    man = json.load(open(os.path.join(E, "INVOCATION_MANIFEST.json")))
    state_p = os.path.join(E, "EXECUTION_STATE.json"); state = json.load(open(state_p)) if os.path.exists(state_p) else {"done": {}, "executed_routes": {}}
    for item in man["invocations"]:
        if item["stage"] not in stages or str(item["id"]) in state["done"]:
            continue
        p, r = item["panel"], Fr(item["r"]); cd = cell_dir(p, r); os.makedirs(cd, exist_ok=True)
        panel_path = os.path.join(E, "inputs", p + ".json"); key = "%s|%s" % (p, item["r"])
        exec_routes = state["executed_routes"].setdefault(key, {})
        if item["kind"] == "seal":
            rows = {}
            for f in sorted(os.listdir(cd)):
                if f.endswith(".json") and not f.startswith("reference_") and not f.startswith("SEAL"):
                    rows[f] = hashlib.sha256(open(os.path.join(cd, f), "rb").read()).hexdigest()
            _j({"sealed": time.strftime("%Y-%m-%d %H:%M:%S %z"), "files": rows}, os.path.join(cd, "SEAL_%s.json" % item["id"]))
            state["done"][str(item["id"])] = {"kind": "seal", "files": len(rows)}; _j(state, state_p); print("sealed", key, len(rows)); continue
        if item["kind"] == "select":
            eps = Fr(item["eps"]); out = os.path.join(cd, "select_eps%s_rep%d.json" % (item["eps"].replace("/", "_"), item["rep"]))
            cmd = [PY, "-m", "research.campaigns.sf.invoke", "select", panel_path, str(r.numerator), str(r.denominator), str(eps.numerator), str(eps.denominator), out, "%.1f" % min(CAP_S, led["allowance_s"] - charged(led))]
        else:
            route = item["route"]; out = os.path.join(cd, "%s_%s_rep%d.json" % (item["kind"], route, item["rep"]))
            if item["kind"] == "diag" and route in exec_routes:
                state["done"][str(item["id"])] = {"kind": "diag", "reused_from": exec_routes[route]}; led["reused"].append({**item, "reused_from": exec_routes[route]}); _j(led, lp); _j(state, state_p)
                print("reused", key, route, "<-", os.path.basename(exec_routes[route])); continue
            cmd = [PY, "-m", "research.campaigns.sf.invoke", "route", panel_path, str(r.numerator), str(r.denominator), route, out, "%.1f" % min(CAP_S, led["allowance_s"] - charged(led))]
        sup = launch(led, lp, item, cmd, out, out[:-5] + ".supervisor.log")
        if sup is None:
            state["done"][str(item["id"])] = {"kind": item["kind"], "unattempted": True}; _j(state, state_p); print("UNATTEMPTED", key, item["kind"], item.get("route")); continue
        rec = json.load(open(out)) if os.path.exists(out) else {}
        state["done"][str(item["id"])] = {"kind": item["kind"], "artifact": out, "status": rec.get("status"), "route": rec.get("route"), "charged_s": sup.get("elapsed_s"), "outcome": sup.get("outcome")}
        if item["kind"] in ("select", "diag") and rec.get("status") == "OK" and item["rep"] == 0 and rec.get("route") not in exec_routes:
            exec_routes[rec["route"]] = out
        _j(state, state_p)
        print("%-34s %-7s %-4s %-14s %.3f s  %s" % (key, item["kind"], item.get("route") or item["eps"], rec.get("status"), sup.get("elapsed_s") or -1, rec.get("route")), flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "manifest":
        man = {"built": time.strftime("%Y-%m-%d %H:%M:%S %z"), "allowance_s": ALLOWANCE_S, "cap_per_invocation_s": CAP_S, "mem_cap_bytes": MEM,
               "r_priority": [str(r) for r in C.R_PRIORITY], "panels": PANEL_ORDER, "widths": [str(w) for w in C.WIDTHS], "invocations": build_manifest()}
        _j(man, os.path.join(E, "INVOCATION_MANIFEST.json")); print("manifest:", len(man["invocations"]), "invocations")
    else:
        run(set(sys.argv[1:]))
