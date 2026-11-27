"""Run the inherited D1-D90 control suite (code/cex/hp/check_dgp.py) ONE CONTROL PER SUBPROCESS with a timeout, classifying
every control honestly (repair R4: static references are DIAGNOSTIC METADATA, never a sufficient reason for BLOCKED):

  PORTABLE  -- passed,
  BLOCKED   -- failed AND a declared private dependency of that control is ABSENT on this host (dependency PREFLIGHT, evaluated
               from the suite's own records-rooted constants / concatenations) OR the control's output names a missing path /
               `missing` / `present: false` record whose path is actually absent (VALIDATED evidence),
  FAILED    -- failed with its declared dependencies present (a RuntimeError / assertion with available inputs stays FAILED),
  TIMEOUT   -- exceeded the per-control timeout.

The records root is the single parameter PGM_RECORDS_ROOT (default: an EMPTY temporary directory).  Exit status is 1 when
any control is FAILED or TIMEOUT unless --allow-failures is given.  Nothing in the suite is weakened or relabelled.
usage: run_inherited_controls.py OUT.json [--timeout 600] [--records-root PATH] [--only D1,D2] [--allow-failures]
"""
import argparse, ast, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SUITE = REPO / "code/cex/hp/check_dgp.py"
MISSING_RE = re.compile(r"(?:No such file or directory|FileNotFoundError|NotADirectoryError)[^'\"]*['\"]([^'\"]+)['\"]")


def control_names():
    return [m.group(1) for m in re.finditer(r"^def (D\d+)_", SUITE.read_text(), re.M)]


def module_constants(root):
    """the suite's module-level string constants rooted at the records root, evaluated by importing the suite with PGM_RECORDS_ROOT=root"""
    code = ("import json, sys, os; sys.argv=['check_dgp']; import importlib.util as u; spec=u.spec_from_file_location('check_dgp_probe', %r); m=u.module_from_spec(spec); spec.loader.exec_module(m);"
            "print(json.dumps({k: v for k, v in vars(m).items() if isinstance(v, str) and v.startswith(%r)}))") % (str(SUITE), root)
    env = dict(os.environ, PGM_RECORDS_ROOT=root, PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO / "code"))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(SUITE.parent), timeout=300)
    if p.returncode != 0:
        raise RuntimeError("could not import the suite for the dependency preflight: " + p.stderr[-800:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def declared_dependencies(root, constants):
    """per control: the records-rooted paths it references -- module constants (evaluated) and in-function `RECORDS + '<literal>'`
    concatenations (evaluated), transitively through helper functions called by name"""
    text = SUITE.read_text(); tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    def paths_in(fn, seen):
        if fn in seen or fn not in funcs: return set()
        seen.add(fn); out = set()
        for n in ast.walk(funcs[fn]):
            if isinstance(n, ast.Name) and n.id in constants: out.add(constants[n.id])
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) and isinstance(n.left, ast.Name) and n.left.id == "RECORDS" and isinstance(n.right, ast.Constant) and isinstance(n.right.value, str):
                out.add(root + n.right.value)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs: out |= paths_in(n.func.id, seen)
        return out
    return {name: sorted(paths_in(name, set())) for name in funcs if re.match(r"D\d+_", name)}


def missing_evidence(control, stdout, stderr, root):
    """VALIDATED missing-dependency evidence: paths named by the control's record / output that are actually absent"""
    named = set()
    blob = json.dumps(control, default=str) + stdout + stderr
    named |= set(MISSING_RE.findall(blob))
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("missing", "path", "packet", "file") and isinstance(v, str): named.add(v)
                if k == "present" and v is False and isinstance(o.get("path"), str): named.add(o["path"])
                walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(control)
    return sorted(p for p in named if (p.startswith(root) or "/code/runs/" in p or "pgm-records" in p) and not os.path.exists(p))


def classify(ok, timeout, preflight_missing, evidence_missing):
    if timeout: return "TIMEOUT"
    if ok: return "PORTABLE"
    if preflight_missing or evidence_missing: return "BLOCKED"
    return "FAILED"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--timeout", type=float, default=600.0); ap.add_argument("--records-root", default=None); ap.add_argument("--only", default=None); ap.add_argument("--allow-failures", action="store_true")
    a = ap.parse_args(argv)
    root = a.records_root or tempfile.mkdtemp(prefix="pgm-no-records-")
    names = control_names(); only = set(a.only.split(",")) if a.only else None
    constants = module_constants(root); deps = declared_dependencies(root, constants); deps_by_prefix = {k.split("_")[0]: v for k, v in deps.items()}
    results = {}; t_all = time.time()
    for name in names:
        if only and name not in only: continue
        declared = deps_by_prefix.get(name, []); preflight_missing = [p for p in declared if not os.path.exists(p)]
        with tempfile.TemporaryDirectory(prefix="ctl-") as td:
            out = Path(td) / "res.json"
            env = dict(os.environ, PGM_RECORDS_ROOT=root, PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO / "code"))
            t0 = time.time(); timeout = False; rc = None; stdout = stderr = ""
            try:
                p = subprocess.run([sys.executable, str(SUITE), str(out), "--only", name], capture_output=True, text=True, timeout=a.timeout, env=env, cwd=str(SUITE.parent))
                rc, stdout, stderr = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired as e:
                timeout = True; stdout = (e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")); stderr = (e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
            secs = round(time.time() - t0, 2)
            rec = None
            if out.exists():
                try: rec = json.loads(out.read_text())
                except ValueError: rec = None
            control = (rec or {}).get("controls", [{}])[0] if rec and rec.get("controls") else {}
            ok = bool(control.get("ok")) if control else False
            evidence = missing_evidence(control, stdout, stderr, root) if not ok else []
            status = classify(ok, timeout, preflight_missing, evidence)
            basis = ("passed" if status == "PORTABLE" else "timeout" if status == "TIMEOUT" else
                     ("declared dependency absent (preflight)" if preflight_missing else "validated missing-path evidence") if status == "BLOCKED" else
                     "failed with declared dependencies present" if declared else "failed; no private dependency declared")
            results[name] = dict(status=status, classification_basis=basis, seconds=secs, returncode=rc, declared_private_dependencies=declared, preflight_missing=preflight_missing,
                                 validated_missing_evidence=evidence, error_tail=((control.get("error") or control.get("tb") or stderr)[-600:] if status != "PORTABLE" else None), control_record=control)
            print("%-5s %-8s %7.1fs %s" % (name, status, secs, ("; ".join(preflight_missing or evidence)[:150] if status == "BLOCKED" else (results[name]["error_tail"] or "")[-120:].replace("\n", " ") if status not in ("PORTABLE",) else "")), flush=True)
    counts = {}
    for r in results.values(): counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = dict(suite=str(SUITE.relative_to(REPO)), records_root=root, records_root_is_empty=(a.records_root is None), timeout_s=a.timeout, counts=counts, n=len(results), wall_s=round(time.time() - t_all, 1),
                   classification="PORTABLE = passed; BLOCKED = failed with a declared private dependency absent (preflight) or validated missing-path evidence; FAILED = failed with dependencies present; TIMEOUT",
                   python=sys.version.split()[0], commit=subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), controls=results)
    Path(a.out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    bad = counts.get("FAILED", 0) + counts.get("TIMEOUT", 0)
    print("inherited controls:", json.dumps(counts), "wall %.0fs" % summary["wall_s"], "" if not bad else "-- %d UNEXPECTED (FAILED/TIMEOUT)" % bad)
    return 0 if (bad == 0 or a.allow_failures) else 1


if __name__ == "__main__": sys.exit(main())
