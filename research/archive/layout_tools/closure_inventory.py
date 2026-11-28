"""Production dependency closure from the four roots (brief section 3): transitive bare / qualified imports resolved
against the retained implementation directories, native kernels, JSON resources and build / load paths.
usage: closure_inventory.py [--root CODE_DIR] [--out INVENTORY.json]"""
import argparse, ast, json, os, re, sys
from pathlib import Path

ROOTS = {"structural": "cex/newarm/core.py", "block": "cex/blockres/integrated.py", "quotient": "cex/hp/unified_pac_planner.py", "response": "cex/hp/spectral_heatbath_run.py"}
SEARCH = ["cex/newarm", "cex/blockres", "cex/hp", "gbidi", ""]
STDLIB = set(sys.stdlib_module_names) | {"numpy", "scipy", "gmpy2", "psutil", "mpmath"}
RESOURCE_RE = re.compile(r"""['"]([A-Za-z0-9_./-]+\.(?:json|c|cpp|h|hpp|so|dylib|txt))['"]""")


def imports_of(path):
    tree = ast.parse(path.read_text())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: out.append((a.name.split(".")[0], node.lineno, "import", a.asname))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module.split(".")[0], node.lineno, "from", [a.name for a in node.names]))
    return out


def resolve(code, name, origin_dir):
    for d in [origin_dir] + [code / s for s in SEARCH]:
        cand = d / (name + ".py")
        if cand.is_file(): return cand
        pkg = d / name / "__init__.py"
        if pkg.is_file(): return pkg
    return None


def closure(code, root_rel):
    root = code / root_rel; seen = {}; todo = [root]
    while todo:
        f = todo.pop()
        rel = str(f.relative_to(code))
        if rel in seen: continue
        text = f.read_text(); entry = dict(lines=text.count("\n") + 1, imports=[], external=[], unresolved=[], resources=sorted(set(RESOURCE_RE.findall(text))), sys_path_lines=[i + 1 for i, l in enumerate(text.splitlines()) if "sys.path" in l and not l.strip().startswith("#")], file_relative_lookups=[i + 1 for i, l in enumerate(text.splitlines()) if "__file__" in l])
        for name, line, kind, extra in imports_of(f):
            if name in STDLIB: entry["external"].append(name); continue
            target = resolve(code, name, f.parent)
            if target is None: entry["unresolved"].append(dict(name=name, line=line)); continue
            trel = str(target.relative_to(code)); entry["imports"].append(dict(name=name, line=line, kind=kind, target=trel))
            if trel not in seen: todo.append(target)
        entry["external"] = sorted(set(entry["external"])); seen[rel] = entry
    return seen


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", default=str(Path(__file__).resolve().parents[4] / "code")); ap.add_argument("--out", default=None); a = ap.parse_args()
    code = Path(a.root).resolve(); per_root = {k: closure(code, v) for k, v in ROOTS.items()}
    union = {}
    for k, files in per_root.items():
        for rel, e in files.items(): union.setdefault(rel, dict(e, roots=[]))["roots"].append(k)
    native = {}
    for rel in union:
        d = (code / rel).parent
        for f in sorted(d.iterdir()):
            if f.suffix in (".c", ".cpp", ".h", ".hpp", ".so", ".dylib") or f.name.endswith("_build.json"):
                native.setdefault(str(d.relative_to(code)), []).append(f.name)
    inv = dict(roots=ROOTS, per_root={k: sorted(v) for k, v in per_root.items()}, union_files=len(union), union_lines=sum(e["lines"] for e in union.values()), files=dict(sorted(union.items())), native_and_build_records=native,
               external_dependencies=sorted({x for e in union.values() for x in e["external"]}))
    text = json.dumps(inv, indent=1)
    if a.out: Path(a.out).write_text(text + "\n")
    print("closure: %d files, %d lines" % (inv["union_files"], inv["union_lines"]))
    for k, v in per_root.items(): print("  %-10s %2d files %6d lines" % (k, len(v), sum(e["lines"] for e in v.values())))
    for rel, e in sorted(union.items()):
        print("  %-45s %5d  roots=%s  imports=%s%s" % (rel, e["lines"], ",".join(e["roots"]), ",".join(sorted({i["name"] for i in e["imports"]})), ("  UNRESOLVED=" + ",".join(u["name"] for u in e["unresolved"])) if e["unresolved"] else ""))
    print("native/build:", json.dumps(native)); print("external:", inv["external_dependencies"])


if __name__ == "__main__": main()
