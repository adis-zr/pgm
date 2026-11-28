"""Build the machine-readable MIGRATION_MANIFEST.json + CAPABILITY_MATRIX.json (brief sections 3, 4, 10).

AFTER closure: transitive qualified-import closure of the installed package from pgm.api (ast over src/pgm; `pgm.*`
imports resolved to files; lazy imports included).  BEFORE closure: CLOSURE_BEFORE.json.  Path map / shims:
PATH_MAP.json.  Blocked controls: BLOCKED_CONTROLS.json (when present).  Classification: research/CLASSIFICATION.json.
"""
import ast, json, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]; SRC = REPO / "src"; STEP = REPO / "documentation/consolidation/step1"
STDLIB = set(sys.stdlib_module_names) | {"numpy", "scipy", "gmpy2", "psutil"}


def resolve(modname):
    parts = modname.split(".")
    p = SRC.joinpath(*parts)
    if (p.with_suffix(".py")).is_file(): return p.with_suffix(".py")
    if (p / "__init__.py").is_file(): return p / "__init__.py"
    return None


def imports(path, modname):
    tree = ast.parse(path.read_text()); out = set()
    pkg = modname.rsplit(".", 1)[0] if not path.name == "__init__.py" else modname
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split("."); base_parts = up[: len(up) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            out.add(base)
            for a in node.names: out.add(base + "." + a.name)
    return out


ROOTS_AFTER = ("pgm.api", "pgm.__main__", "pgm.backends.worker", "pgm.supervision", "pgm.build")      # the process entrypoints (the worker and the supervisor run as subprocesses)


def closure(roots=ROOTS_AFTER):
    seen = {}; todo = list(roots)
    while todo:
        m = todo.pop()
        if m in seen or m.split(".")[0] in STDLIB: continue
        f = resolve(m)
        if f is None: continue
        rel = str(f.relative_to(REPO)); text = f.read_text()
        seen[m] = dict(path=rel, lines=text.count("\n") + 1)
        for dep in imports(f, m):
            if dep.startswith("pgm") and dep not in seen: todo.append(dep)
    return seen


def main():
    after = closure(); before = json.loads((STEP / "CLOSURE_BEFORE.json").read_text()); path_map = json.loads((STEP / "PATH_MAP.json").read_text())
    blocked = json.loads((STEP / "BLOCKED_CONTROLS.json").read_text()) if (STEP / "BLOCKED_CONTROLS.json").exists() else None
    classification = json.loads((REPO / "research/CLASSIFICATION.json").read_text())
    sys.path.insert(0, str(SRC)); from pgm.registry import CAPABILITIES; from pgm import policies
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    specialists_touch = sorted(m for m in after if m.startswith("pgm.specialists"))
    campaign_touch = sorted(m for m, v in after.items() if "/code/" in v["path"])
    manifest = dict(
        schema="PGM_STEP1_MIGRATION_MANIFEST_V1", source_commit="f8197e6b1e90286b8554a3088a0594b9178a3595", head_commit=head,
        roots_before=before["roots"], closure_before=dict(files=before["union_files"], lines=before["union_lines"], per_root={k: len(v) for k, v in before["per_root"].items()}, inventory="documentation/consolidation/step1/CLOSURE_BEFORE.json"),
        closure_after=dict(roots=list(ROOTS_AFTER), modules=len(after), lines=sum(v["lines"] for v in after.values()), imports_specialists=specialists_touch, imports_code_tree=campaign_touch, modules_detail=after),
        path_map=path_map["modules"], resources=path_map["resources"], shims=path_map["shims"], untracked_moves=path_map["untracked_moves"],
        deletions=[dict(path="src/pgm/runtime/legacy_paths.py", commit="eb71a50", reason="the legacy sys.path bridge is unnecessary once the closures import fully qualified names"),
                   dict(path="src/pgm/planning.py", commit="302ee54", reason="became the package pgm.planning (features.py)"),
                   dict(path="src/pgm/supervision.py / src/pgm/build.py", commit="302ee54", reason="kept as thin compatibility entries over pgm.runtime.{supervision,build}")],
        duplicates_removed="none: no second live copy of any relocated module existed outside the frozen snapshots (which are pinned historical evidence, never imported by production)",
        compatibility_entrypoints=dict(python_modules=["pgm.supervision", "pgm.build", "pgm.backends.worker.{normalize_result,read_inventory,write_result,AdapterRefused}", "pgm.switchboard.{run_attempt,candidate_plan,POLICY_VERSION,NATIVE_ROWS_PER_SECOND,RISK_SHARES}"], historical_paths="every path in `shims` (import by bare name or run as a script)"),
        unfinished=CAPABILITIES["unfinished"]["items"],
        policies={name: dict(version=mod.VERSION, backends=list(getattr(mod, "BACKENDS", ("structural", "block", "quotient", "response"))), risk_shares={k: str(v) for k, v in mod.RISK_SHARES.items()}, needs_forecast=mod.NEEDS_FORECAST) for name, mod in policies.POLICIES.items()},
        default_policy=policies.DEFAULT_POLICY,
        classification_counts=classification["counts"],
        blocked_controls=(dict(counts=blocked["counts"], records_root_is_empty=blocked["records_root_is_empty"], file="documentation/consolidation/step1/BLOCKED_CONTROLS.json") if blocked else "not yet run"),
        qualification="documentation/consolidation/step1/qualification/",
    )
    (STEP / "MIGRATION_MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    matrix = []
    for name, cap in CAPABILITIES.items():
        if name == "unfinished": continue
        matrix.append(dict(capability=name, status=cap["status"], method=cap.get("methods") or cap.get("representation"), representation=cap.get("representation"), entrypoint=cap.get("entrypoint"), adapter=cap.get("adapter"),
                           guarantees=cap.get("guarantees"), admission=cap.get("admission") or cap.get("reason"), canonical_owner=cap.get("owner"), policies=cap.get("policies"), evidence=cap.get("evidence"),
                           mode={"selectable": "automatic (policy-scheduled)", "specialist": "specialist (explicit API)", "reference": "reference-only", "historical": "reference-only (pinned snapshot)"}[cap["status"]]))
    (STEP / "CAPABILITY_MATRIX.json").write_text(json.dumps(matrix, indent=1) + "\n")
    print("manifest: after closure %d modules / %d lines; specialists in production closure: %s; code-tree modules in production closure: %s" % (manifest["closure_after"]["modules"], manifest["closure_after"]["lines"], specialists_touch, campaign_touch))


if __name__ == "__main__": main()
