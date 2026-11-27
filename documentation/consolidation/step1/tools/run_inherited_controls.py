"""Run the inherited D1-D90 control suite (code/cex/hp/check_dgp.py) ONE CONTROL PER SUBPROCESS with a timeout and the private
records root pointed at an EMPTY directory, so every control is classified honestly as

  PORTABLE  -- passed with no private input,
  BLOCKED   -- failed / errored because a private record input is absent (the missing path is recorded verbatim),
  FAILED    -- failed for another reason (recorded; nothing is relabeled),
  TIMEOUT   -- exceeded the per-control timeout.

Nothing in the suite is weakened: the control functions run unchanged; only their records root is a parameter
(PGM_RECORDS_ROOT).  Output: BLOCKED_CONTROLS.json (per control: status, seconds, missing dependency, error tail, the
control's own record) + a summary line.
usage: run_inherited_controls.py OUT.json [--timeout 600] [--records-root PATH] [--only D1,D2]
"""
import argparse, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SUITE = REPO / "code/cex/hp/check_dgp.py"
MISSING_RE = re.compile(r"(?:No such file or directory|FileNotFoundError|NotADirectoryError)[^'\"]*['\"]([^'\"]+)['\"]")


def control_names():
    text = SUITE.read_text()
    return [m.group(1) for m in re.finditer(r"^def (D\d+)_", text, re.M)]


def private_dependencies():
    """STATIC analysis of the suite: module-level constants rooted at the private records root (RECORDS, DGP_ROOTS, the packet
    paths) and, transitively through helper calls, every control function that references one of them."""
    import ast
    tree = ast.parse(SUITE.read_text()); rooted = set(); funcs = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            src = ast.get_source_segment(SUITE.read_text(), node) or ""
            if "RECORDS" in src or "/code/runs/" in src or "DGP_ROOTS" in src:
                for t in node.targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name): rooted.add(n.id)
        elif isinstance(node, ast.FunctionDef): funcs[node.name] = node
    rooted.add("RECORDS")
    def refs(fn, seen):
        if fn in seen or fn not in funcs: return set()
        seen.add(fn); out = set(); body = funcs[fn]
        for n in ast.walk(body):
            if isinstance(n, ast.Name) and n.id in rooted: out.add(n.id)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and ("/code/runs/" in n.value or "DGP_ROOTS" in n.value): out.add(repr(n.value)[:80])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs: out |= refs(n.func.id, seen)
        return out
    return {name: sorted(refs(name, set())) for name in funcs if re.match(r"D\d+_", name)}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--timeout", type=float, default=600.0); ap.add_argument("--records-root", default=None); ap.add_argument("--only", default=None)
    a = ap.parse_args()
    empty = tempfile.mkdtemp(prefix="pgm-no-records-")
    root = a.records_root or empty
    names = control_names(); only = set(a.only.split(",")) if a.only else None
    deps = private_dependencies(); deps_by_prefix = {k.split("_")[0]: v for k, v in deps.items()}
    results = {}; t_all = time.time()
    for name in names:
        if only and name not in only: continue
        with tempfile.TemporaryDirectory(prefix="ctl-") as td:
            out = Path(td) / "res.json"
            env = dict(os.environ, PGM_RECORDS_ROOT=root, PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO / "code"))
            t0 = time.time()
            try:
                p = subprocess.run([sys.executable, str(SUITE), str(out), "--only", name], capture_output=True, text=True, timeout=a.timeout, env=env, cwd=str(REPO / "code/cex/hp"))
                rc, stdout, stderr = p.returncode, p.stdout, p.stderr; timeout = False
            except subprocess.TimeoutExpired as e:
                rc, stdout, stderr, timeout = None, (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""), True
            secs = round(time.time() - t0, 2)
            rec = None
            if out.exists():
                try: rec = json.loads(out.read_text())
                except ValueError: rec = None
            control = (rec or {}).get("controls", [{}])[0] if rec and rec.get("controls") else {}
            ok = bool(control.get("ok")) if control else False
            blob = json.dumps(control, default=str) + stdout + stderr
            missing = sorted({m for m in MISSING_RE.findall(blob) if root in m or "pgm-records" in m or "/runs/" in m or "DGP" in m})
            other_missing = sorted({m for m in MISSING_RE.findall(blob)} - set(missing))
            static = deps_by_prefix.get(name, [])
            if timeout: status = "TIMEOUT"
            elif ok: status = "PORTABLE"
            elif missing or static: status = "BLOCKED"          # failed while a private record input it references is absent
            else: status = "FAILED"
            results[name] = dict(status=status, seconds=secs, returncode=rc, missing_private_dependency=missing, private_record_constants_referenced=static, other_missing_paths=other_missing,
                                 error_tail=(control.get("error") or control.get("traceback") or stderr)[-600:] if status != "PORTABLE" else None, control_record=control)
            print("%-5s %-8s %7.1fs %s" % (name, status, secs, ("; ".join(missing or static)[:150] if (missing or static) else (results[name]["error_tail"] or "")[-120:].replace("\n", " ") if status != "PORTABLE" else "")), flush=True)
    counts = {}
    for r in results.values(): counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = dict(suite=str(SUITE.relative_to(REPO)), records_root=root, records_root_is_empty=(a.records_root is None), timeout_s=a.timeout, counts=counts, n=len(results), wall_s=round(time.time() - t_all, 1),
                   python=sys.version.split()[0], commit=subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), controls=results)
    Path(a.out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    print("inherited controls:", json.dumps(counts), "wall %.0fs" % summary["wall_s"])


if __name__ == "__main__": main()
