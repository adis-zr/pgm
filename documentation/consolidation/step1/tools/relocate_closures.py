"""Step-1 relocation of the four production closures into src/pgm/algorithms/* (brief sections 4-6).

Mechanics (reproducible; the committed path map is written to documentation/consolidation/step1/PATH_MAP.json):
  * git mv every closure module and its owned resources (native sources, build records, host binaries, rate files);
  * rewrite ONLY import statements to fully qualified names (same local aliases; module-level stays module-level,
    lazy stays lazy); remove the sys.path manipulations; nothing else in the modules changes;
  * write alias shims at the historical paths (research / campaign code keeps importing by bare name and receives the
    canonical module object; running a shim as a script re-executes the canonical module as __main__).
usage: relocate_closures.py [--apply]  (without --apply: print the plan only)
"""
import argparse, json, os, re, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PKG = {
    "structural": ("code/cex/newarm", ["cex_executor", "core", "dag", "forest", "geometry", "planning", "reduction", "stream", "stream_float", "support"],
                   ["cex_kernel.cpp", "cex_build.json", "libcex_kernel.dylib", "stream_kernel.cpp", "stream_build.json", "libstream_kernel.so"]),
    "block": ("code/cex/blockres", ["integrated", "blockres", "support_closure", "signed_evidence", "layered_contraction", "ancestral_response"], []),
    "quotient": ("code/cex/hp", ["unified_pac_planner", "unified_planner", "pac_actions", "coarse_envelope", "cost_model", "global_circuit", "global_optimize", "global_stream", "grouped_envelope",
                                 "joint_optimize", "joint_proposal", "joint_stream", "joint_witness", "lifted_decoder", "check_global", "check_joint", "check_residual", "residual_bank", "residual_local",
                                 "residual_max_envelope", "residual_stream", "reservation", "lp_worker"], ["PHASE_RATES.json", "PHASE_RATES_R1.json"]),
    "response": ("code/cex/hp", ["spectral_heatbath_run", "spectral_witness", "heatbath_exact", "heatbath_native", "markov_certificate", "response_certificate", "checked_tilt"], ["heatbath_native.c"]),
}
RUNTIME = {"supervise": ("code/gbidi", "src/pgm/runtime")}
HOME = {name: "pgm.algorithms." + pkg for pkg, (_, names, _) in PKG.items() for name in names}
STDLIB = set(sys.stdlib_module_names)
IMPORT_RE = re.compile(r"(?P<lead>^\s*|;\s*)import (?P<names>[A-Za-z_][\w]*(?:\s+as\s+\w+)?(?:\s*,\s*[A-Za-z_][\w]*(?:\s+as\s+\w+)?)*)(?=\s*(?:;|#|$))", re.M)
FROM_RE = re.compile(r"(?P<lead>^\s*|;\s*)from (?P<mod>[A-Za-z_]\w*) import ", re.M)
SYS_PATH_DROP = [  # exact statements that only served the bare-import layout
    "if HERE not in sys.path: sys.path.insert(0, HERE)\n",
    "    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))\n",
    "for p in (os.path.join(CODE, 'cex', 'newarm'), os.path.join(CODE, 'cex', 'cqr')):\n    if p not in sys.path: sys.path.insert(0, p)\n",
    "for p in (os.path.join(CODE, 'cex', 'newarm'),):\n    if p not in sys.path: sys.path.insert(0, p)\n",
    "for p in (HERE, BR_DIR):\n    if p not in sys.path: sys.path.insert(0, p)\n",
    "if NEWARM not in sys.path: sys.path.insert(0, NEWARM)\n",
]
SYS_PATH_INLINE = [
    ("HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)\n", "HERE = os.path.dirname(os.path.abspath(__file__))\n"),
    ("HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'blockres'))\n", "HERE = os.path.dirname(os.path.abspath(__file__))\n"),
    ("    sys.path.insert(0, os.path.join(CODE, 'cex', 'newarm')); import core as CORE\n", "    from pgm.algorithms.structural import core as CORE\n"),
    ("    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm')); import core as CORE\n", "    from pgm.algorithms.structural import core as CORE\n"),
]


def rewrite_imports(text):
    def imp(m):
        parts = [p.strip() for p in m.group("names").split(",")]
        keep, moved = [], {}
        for p in parts:
            name = p.split()[0]
            if name in HOME: moved.setdefault(HOME[name], []).append(p)
            else: keep.append(p)
        if not moved: return m.group(0)
        stmts = (["import " + ", ".join(keep)] if keep else []) + ["from %s import %s" % (pkg, ", ".join(ps)) for pkg, ps in moved.items()]
        return m.group("lead") + "; ".join(stmts)
    text = IMPORT_RE.sub(imp, text)
    text = FROM_RE.sub(lambda m: m.group(0) if m.group("mod") not in HOME else m.group("lead") + "from %s.%s import " % (HOME[m.group("mod")], m.group("mod")), text)
    return text


def strip_sys_path(text):
    for s in SYS_PATH_DROP: text = text.replace(s, "")
    for a, b in SYS_PATH_INLINE: text = text.replace(a, b)
    return text


def shim(qualified, depth):
    up = "/".join([".."] * depth)
    return ('"""COMPATIBILITY SHIM (consolidation step 1, 27 Nov 2026). The canonical module is `%s`; this historical path re-exports\n'
            'that one module object (patches through the bare name reach the single implementation). Running this file as a script re-executes the\n'
            'canonical module as __main__ with the same argv. Production code must import the canonical name."""\n'
            "import importlib as _il, os as _os, sys as _sys\n"
            "try:\n    import pgm as _pgm\nexcept ImportError:\n    _sys.path.insert(0, _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '%s', 'src')))\n"
            "if __name__ == '__main__':\n    import runpy as _rp; _rp.run_module('%s', run_name='__main__', alter_sys=True)\n"
            "else:\n    _sys.modules[__name__] = _il.import_module('%s')\n") % (qualified, up, qualified, qualified)


def git(*args): subprocess.run(["git", "-C", str(REPO), *args], check=True)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    path_map = dict(generated_by="documentation/consolidation/step1/tools/relocate_closures.py", modules={}, resources={}, shims={}, untracked_moves={})
    plan = []
    for pkg, (src_dir, names, resources) in PKG.items():
        dst = "src/pgm/algorithms/" + pkg
        for n in names:
            path_map["modules"][f"{src_dir}/{n}.py"] = dict(canonical=f"{dst}/{n}.py", module=f"pgm.algorithms.{pkg}.{n}", shim=f"{src_dir}/{n}.py"); plan.append((f"{src_dir}/{n}.py", f"{dst}/{n}.py", f"pgm.algorithms.{pkg}.{n}", 3))
        for r in resources: path_map["resources"][f"{src_dir}/{r}"] = f"{dst}/{r}"
    path_map["modules"]["code/gbidi/supervise.py"] = dict(canonical="src/pgm/runtime/supervise.py", module="pgm.runtime.supervise", shim="code/gbidi/supervise.py"); plan.append(("code/gbidi/supervise.py", "src/pgm/runtime/supervise.py", "pgm.runtime.supervise", 2))
    path_map["untracked_moves"] = {"code/cex/hp/heatbath_build.json": "src/pgm/algorithms/response/heatbath_build.json", "code/cex/hp/native_cache/": "src/pgm/algorithms/response/native_cache/", "code/cex/newarm/native_cache/": "src/pgm/algorithms/structural/native_cache/"}
    if not a.apply:
        print(json.dumps(path_map, indent=1)); return
    for pkg in PKG: (REPO / "src/pgm/algorithms" / pkg).mkdir(parents=True, exist_ok=True)
    for old, new, qualified, depth in plan:
        git("mv", old, new)
        p = REPO / new; text = p.read_text(); text2 = strip_sys_path(rewrite_imports(text))
        p.write_text(text2)
        (REPO / old).write_text(shim(qualified, depth)); git("add", old); path_map["shims"][old] = qualified
    for old, new in path_map["resources"].items(): git("mv", old, new)
    for old, new in path_map["untracked_moves"].items():
        src = REPO / old; dst = REPO / new
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                dst.mkdir(exist_ok=True)
                for f in src.iterdir(): f.rename(dst / f.name)
                src.rmdir()
            else: src.rename(dst)
    (REPO / "documentation/consolidation/step1/PATH_MAP.json").write_text(json.dumps(path_map, indent=1, sort_keys=True) + "\n")
    print("relocated %d modules, %d resources" % (len(plan), len(path_map["resources"])))


if __name__ == "__main__": main()
