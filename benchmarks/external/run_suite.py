#!/usr/bin/env python3
"""Frozen external suite for the public pgm API with an EXECUTED pinned accepted reference, an executed pinned experimental
reference, and independent artifact checks (STEP2_AMENDMENT_1, 27 Nov 2026).

Arms (one outer contract: 20 s end to end, 3 GiB sampled process-tree RSS, epsilon 1/200, delta 1e-6, two fresh-process
repeats, serial execution under the strict zero-grace supervisor):
  PGM_REFERENCE         the accepted standalone engine of pinned commit 7f28259 (detached checkout; historical invocation;
                        PYTHONPATH = <reference>/code only -- never the new package)
  PGM_ACCEPTED          the new public API, --policy accepted   (default policy)
  PGM_EXPERIMENTAL      the new public API, --policy experimental (the frozen structural-portfolio-1)
  PGM_EXPERIMENTAL_REF  the scored public implementation of pinned commit 3283cfd (detached checkout; its own single policy)
  LIBDAI_JT / LIBDAI_BP the qualified libDAI 0.3.2 comparator
Native resources are resolved from each arm's OWNING implementation (the new layout through pgm.runtime.resources, including
PGM_NATIVE_CACHE, which is pinned at freeze and passed to every cell explicitly); the artifacts actually loaded are hashed.
Compilation happens only in `setup`, never inside a scored cell.  Actions: setup | freeze | primary | eval.
"""
from __future__ import annotations
import argparse, hashlib, json, math, os, platform, shutil, subprocess, sys, time
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("PGM_BENCH_RUN_DIR", REPO / "benchmark_runs" / "step2-preservation-v1")).expanduser().resolve()
PY = Path(os.environ.get("PGM_BENCH_PY", sys.executable)).expanduser().absolute()
LIBDAI = Path(os.environ.get("PGM_LIBDAI", REPO / "code/bench/libdai/libdai_mar")).expanduser().resolve()
REFERENCE = HERE / "reference/previous_accepted_cells.json"
REFERENCE_ROOT = Path(os.environ.get("PGM_BENCH_REFERENCE_ROOT", "")).expanduser()
REFERENCE_COMMIT = "7f28259a4869a2c684d506b51072b04bb0ce4783"
EXPERIMENTAL_REF_ROOT = Path(os.environ.get("PGM_BENCH_EXPERIMENTAL_REF_ROOT", "")).expanduser()
EXPERIMENTAL_REF_COMMIT = "3283cfde40fe277e218987954b01b3ed94f4a712"
NATIVE_CACHE = os.environ.get("PGM_NATIVE_CACHE")          # pinned at freeze (value or null); every cell receives exactly that setting
EPS = F(1, 200)
BUDGET_S = 20; PGM_ALLOWANCE_S = 19.5; MEMORY_MIB = 3072
ARMS = ["PGM_REFERENCE", "PGM_ACCEPTED", "PGM_EXPERIMENTAL", "PGM_EXPERIMENTAL_REF", "LIBDAI_JT", "LIBDAI_BP"]
RESULT_ARMS = ("PGM_REFERENCE", "PGM_ACCEPTED", "PGM_EXPERIMENTAL", "PGM_EXPERIMENTAL_REF")
PGM_ARMS = {"PGM_ACCEPTED": "accepted", "PGM_EXPERIMENTAL": "experimental"}       # the new public package arms (explicit --policy)
PAIRS = {  # EXPLICIT comparison pairs (candidate, comparator); never positional
    "same_round_accepted": ("PGM_ACCEPTED", "PGM_REFERENCE"),
    "same_round_experimental": ("PGM_EXPERIMENTAL", "PGM_EXPERIMENTAL_REF"),
    "accepted_vs_experimental": ("PGM_ACCEPTED", "PGM_EXPERIMENTAL"),
    "jt_vs_reference": ("PGM_REFERENCE", "LIBDAI_JT"), "jt_vs_accepted": ("PGM_ACCEPTED", "LIBDAI_JT"),
    "jt_vs_experimental": ("PGM_EXPERIMENTAL", "LIBDAI_JT"), "jt_vs_experimental_ref": ("PGM_EXPERIMENTAL_REF", "LIBDAI_JT"),
}
CONTRACTS = {  # frozen expectations checked on every result (never inferred from the result)
    "PGM_REFERENCE": dict(reader="legacy", argv_required=["--budget", "19.5", "--epsilon", "1/200", "--delta", "1/1000000", "--schedule", "targeted", "--route", "auto", "--proposal", "mb"],
                          recorded=dict(schedule="targeted", route_requested="auto", proposal="mb", epsilon="1/200", delta="1/1000000"), internal_usable_bytes=2560 << 20, internal_headroom_bytes=160 << 20,
                          note="internal memory policy of the accepted engine recorded, not rewritten; the outer 3 GiB contract is shared"),
    "PGM_ACCEPTED": dict(reader="public", policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", backends_allowed=["block"], risk_shares={"block": "1"},
                         configuration=dict(schedule="targeted", proposal="mb", table_cap=262144, enum_cap=65536, mb_cap=16777216, batch=1024, crosscheck=True), epsilon="1/200", delta="1/1000000"),
    "PGM_EXPERIMENTAL": dict(reader="public", policy="experimental", policy_version="structural-portfolio-1", backends_allowed=["structural", "block", "quotient", "response"],
                             risk_shares={"structural": "0", "block": "1/2", "quotient": "1/4", "response": "1/4"}, epsilon="1/200", delta="1/1000000"),
    "PGM_EXPERIMENTAL_REF": dict(reader="public_legacy", policy="structural-portfolio-1", backends_allowed=["structural", "block", "quotient", "response"], epsilon="1/200", delta="1/1000000",
                                 note="the 3283cfd result records its single policy under the key `policy`; it has no policy_version / risk_allocations fields"),
}
GENERATED_PREFIXES = ("src/pgm/algorithms/structural/", "src/pgm/algorithms/response/")   # host build targets / records / caches allowed to differ from the committed tree
HARNESS = ["run_suite.py", "strict_supervisor.py", "analyze_suite.py", "PROTOCOL.md", "README.md", "STEP2_PLAN.md", "STEP2_PLAN.json", "STEP2_AMENDMENT_1.md"]
ROW_LABELS = ("EXACT", "DETERMINISTIC", "DETERMINISTIC_RESIDUAL", "PAC", "PAC_EB", "PAC_MARKOV", "PAC_MARKOV_RESPONSE")


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def dump(p, v):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(v, indent=2, default=str) + "\n")


def is_pgm(arm): return arm in RESULT_ARMS
def is_public(arm): return arm in PGM_ARMS


# ---------------------------------------------------------------------------------------------------- native resources
def arm_env(arm, frozen=None):
    """the child environment of an arm: its OWN import root only; compilers and thread pins from the freeze; the pinned cache setting"""
    base = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PGM_NATIVE_CACHE")}
    compilers = (frozen or {}).get("compilers") or resolve_compilers()
    base.update(CC=compilers["CC"], CXX=compilers["CXX"], OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONHASHSEED="0")
    cache = (frozen or {}).get("native_cache", NATIVE_CACHE) if frozen is not None else NATIVE_CACHE
    if cache: base["PGM_NATIVE_CACHE"] = cache
    if arm == "PGM_REFERENCE": base["PYTHONPATH"] = str(root_of(arm, frozen) / "code")
    elif arm == "PGM_EXPERIMENTAL_REF": base["PYTHONPATH"] = str(root_of(arm, frozen) / "src") + os.pathsep + str(root_of(arm, frozen) / "code")
    else: base["PYTHONPATH"] = str(REPO / "src") + os.pathsep + str(REPO / "code")
    return base


def root_of(arm, frozen=None):
    if arm == "PGM_REFERENCE": return Path((frozen or {}).get("roots", {}).get("PGM_REFERENCE", {}).get("path") or REFERENCE_ROOT)
    if arm == "PGM_EXPERIMENTAL_REF": return Path((frozen or {}).get("roots", {}).get("PGM_EXPERIMENTAL_REF", {}).get("path") or EXPERIMENTAL_REF_ROOT)
    return REPO


NEW_LAYOUT_PROBE = r'''
import json, os
import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.algorithms.response.heatbath_native as HN, pgm.runtime.resources as R
print(json.dumps(dict(layout="pgm", cex=dict(src=str(CX.SRC), record=str(CX.RECORD), lib=str(CX.LIB), cache=R.native_cache_dir(os.path.dirname(CX.__file__)), prefix="cex_", suffix=".dylib"),
                      stream=dict(src=str(SF.BASE / "stream_kernel.cpp"), record=str(SF.BASE / "stream_build.json") if os.access(SF.BASE, os.W_OK) and not os.environ.get("PGM_NATIVE_CACHE") else os.path.join(R.writable_home(SF.BASE), "stream_build.json"), lib=str(SF.LIB), cache=R.native_cache_dir(os.path.dirname(SF.__file__)), prefix="stream_", suffix=".so"),
                      heat=dict(src=HN.SRC, record=HN.RECORD, cache=R.native_cache_dir(HN.HERE)))))
'''
LEGACY_LAYOUT_PROBE = r'''
import json, os, sys
import cex_executor as CX, stream_float as SF
out = dict(layout="legacy", cex=dict(src=str(CX.SRC), record=str(CX.RECORD), lib=str(CX.LIB), cache=str(CX.BASE / "native_cache"), prefix="cex_", suffix=".dylib"),
           stream=dict(src=str(SF.BASE / "stream_kernel.cpp"), record=str(SF.BASE / "stream_build.json"), lib=str(SF.LIB), cache=str(SF.BASE / "native_cache"), prefix="stream_", suffix=".so"))
try:
    import heatbath_native as HN; out["heat"] = dict(src=HN.SRC, record=HN.RECORD, cache=os.path.join(HN.HERE, "native_cache"))
except Exception as e:
    out["heat"] = None; out["heat_note"] = repr(e)[:120]
print(json.dumps(out))
'''


def native_probe(arm, frozen=None, want_heat=True):
    """ask the arm's OWN implementation where its native sources / records / binaries / caches are, then verify every active artifact"""
    env = arm_env(arm, frozen); root = root_of(arm, frozen)
    if arm == "PGM_REFERENCE":
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("code/cex/newarm", "code/cex/blockres", "code/cex/hp", "code")); code = LEGACY_LAYOUT_PROBE; want_heat = False
    elif arm == "PGM_EXPERIMENTAL_REF":
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("code/cex/newarm", "code/cex/blockres", "code/cex/hp", "code", "src")); code = LEGACY_LAYOUT_PROBE
    else:
        code = NEW_LAYOUT_PROBE
    p = subprocess.run([str(PY), "-c", code], capture_output=True, text=True, env=env, cwd=str(root), timeout=300)
    if p.returncode != 0:
        raise RuntimeError("native probe failed for %s: %s" % (arm, p.stderr[-800:]))
    loc = json.loads(p.stdout.strip().splitlines()[-1])
    active = []
    for kind in ("cex", "stream"):
        d = loc[kind]
        for key in ("src", "record", "lib"):
            if not Path(d[key]).is_file(): raise RuntimeError("%s: %s %s missing: %s (run setup)" % (arm, kind, key, d[key]))
        rec = json.loads(Path(d["record"]).read_text())
        if rec.get("source_sha256") != sha(d["src"]): raise RuntimeError("%s: %s build record is stale against its source" % (arm, kind))
        if rec.get("binary_sha256") != sha(d["lib"]): raise RuntimeError("%s: %s build target does not match its record" % (arm, kind))
        cached = Path(d["cache"]) / (d["prefix"] + rec["binary_sha256"] + d["suffix"])
        if not cached.is_file() or sha(cached) != rec["binary_sha256"]: raise RuntimeError("%s: %s content-addressed cache not warm: %s (run setup)" % (arm, kind, cached))
        active += [dict(role=kind + "_source", path=d["src"]), dict(role=kind + "_record", path=d["record"]), dict(role=kind + "_build_target", path=d["lib"]), dict(role=kind + "_loaded_binary", path=str(cached))]
        active[-3]["record"] = rec
    if want_heat:
        d = loc.get("heat")
        if not d: raise RuntimeError("%s: heat-bath implementation not found" % arm)
        if not Path(d["record"]).is_file(): raise RuntimeError("%s: heat-bath build record missing: %s (run setup)" % (arm, d["record"]))
        rec = json.loads(Path(d["record"]).read_text())
        if rec.get("source_sha256") != sha(d["src"]): raise RuntimeError("%s: heat-bath build record is stale" % arm)
        lib = Path(d["cache"]) / rec["library"]
        if Path(rec["library"]).name != rec["library"] or not lib.is_file() or sha(lib) != rec["binary_sha256"]: raise RuntimeError("%s: heat-bath binary identity mismatch or missing: %s" % (arm, lib))
        active += [dict(role="heat_source", path=d["src"]), dict(role="heat_record", path=d["record"], record=rec), dict(role="heat_loaded_binary", path=str(lib))]
    for a in active: a["sha256"] = sha(a["path"])
    caches = sorted({str(loc[k]["cache"]) for k in ("cex", "stream")} | ({str(loc["heat"]["cache"])} if want_heat and loc.get("heat") else set()))
    inventory = {c: sorted(os.listdir(c)) if os.path.isdir(c) else [] for c in caches}
    used = {Path(a["path"]).name for a in active if a["role"].endswith("loaded_binary")}
    stale = {c: [f for f in files if f not in used and not f.endswith(".json")] for c, files in inventory.items()}
    return dict(layout=loc["layout"], root=str(root), native_cache=env.get("PGM_NATIVE_CACHE"), active=active, cache_inventory=inventory, stale_cache_files_not_used=stale)


def host_files():
    """active native artifacts of the NEW layout (main repository), as paths relative to the repo when inside it, else absolute"""
    probe = native_probe("PGM_ACCEPTED")
    out = []
    for a in probe["active"]:
        p = Path(a["path"]).resolve()
        out.append(str(p.relative_to(REPO)) if p.is_relative_to(REPO) else str(p))
    return out


def identity():
    files = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True).splitlines()
    paths = sorted(set(files + host_files()))
    return {p: sha(REPO / p if not Path(p).is_absolute() else p) for p in paths if (REPO / p if not Path(p).is_absolute() else Path(p)).is_file()}


def resolve_compilers():
    cc = os.environ.get("CC"); cxx = os.environ.get("CXX")
    assert cc and cxx, "Set CC and CXX explicitly to the qualified native compilers used at setup"
    cc_abs = shutil.which(cc) or cc; cxx_abs = shutil.which(cxx) or cxx
    assert os.path.isabs(cc_abs) and os.path.isabs(cxx_abs) and os.path.exists(cc_abs) and os.path.exists(cxx_abs), "CC/CXX must resolve to existing executables"
    ver = lambda c: subprocess.run([c, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    return dict(CC=cc_abs, CXX=cxx_abs, CC_version=ver(cc_abs), CXX_version=ver(cxx_abs), CC_sha256=sha(cc_abs), CXX_sha256=sha(cxx_abs), machine=platform.machine(), platform=platform.platform())


def root_identity(arm):
    """a pinned detached checkout: exact commit, clean tree (generated host artifacts excepted), source closure hashes, active natives"""
    root = root_of(arm); pinned = REFERENCE_COMMIT if arm == "PGM_REFERENCE" else EXPERIMENTAL_REF_COMMIT
    assert root.is_dir(), "Set %s to the detached checkout of %s" % ("PGM_BENCH_REFERENCE_ROOT" if arm == "PGM_REFERENCE" else "PGM_BENCH_EXPERIMENTAL_REF_ROOT", pinned)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    assert head == pinned, "%s checkout is at %s, not the pinned %s" % (arm, head, pinned)
    dirty = [l for l in subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True).splitlines()
             if not any(seg in l for seg in ("native_cache/", "_build.json", ".dylib", ".so", "__pycache__", ".pyc"))]
    assert not dirty, "%s checkout has source changes: %r" % (arm, dirty)
    closure_dirs = ["code/cex/newarm", "code/cex/blockres"] if arm == "PGM_REFERENCE" else ["src/pgm", "code/cex/newarm", "code/cex/blockres", "code/cex/hp", "code/gbidi"]
    tracked = subprocess.check_output(["git", "ls-files", *closure_dirs], cwd=root, text=True).splitlines()
    closure = {p: sha(root / p) for p in tracked if (root / p).is_file() and not p.endswith((".pyc",))}
    return dict(path=str(root), commit=head, closure_files=len(closure), closure_sha256=closure, natives=native_probe(arm, want_heat=(arm != "PGM_REFERENCE")))


# ---------------------------------------------------------------------------------------------------- result readers
def metadata(task):
    with open(task["model"]) as f:
        t = (s for line in f for s in line.split())
        next(t)
        n = int(next(t))
        cards = [int(next(t)) for _ in range(n)]
    ev = list(map(int, Path(task["evidence"]).read_text().split()))
    assert len(ev) == 1 + 2 * ev[0]
    evidence = dict(zip(ev[1::2], ev[2::2]))
    assert len(evidence) == ev[0]
    return cards, evidence


def check_pgm(path, task, contract=None, budget_s=BUDGET_S):
    """independent check of a result record: original inventory, exact rational geometry, labels, witness, simplex, binding --
    plus the ARM CONTRACT (policy / version / configuration / allowed backends / risk shares / epsilon / delta / deadline / terminal attempts)"""
    d = json.loads(Path(path).read_text())
    cards, ev = metadata(task)
    expected = {(v, a) for v, k in enumerate(cards) if v not in ev for a in range(k)}
    seen = set(); pubs = {}; labels = {}; faults = []; maxradius = F(0); maxwidth = F(0)
    for row in d.get("answers", []):
        key = (row.get("variable", row.get("var")), row.get("state"))
        if any(type(x) is not int for x in key): faults.append("noninteger coordinate identifier")
        if key in seen: faults.append("duplicate coordinate")
        seen.add(key)
        if key not in expected: faults.append("unexpected coordinate")
        if row.get("guarantee") in ("NOT_PUBLISHED", "NONE"): continue
        if row.get("guarantee") is None and all(row.get(k) is None for k in ("point", "lo", "hi")): continue
        if row.get("guarantee") not in ROW_LABELS: faults.append("unknown row guarantee")
        try:
            lo, hi, point = (F(str(row[k])) for k in ("lo", "hi", "point")); radius = max(point - lo, hi - point)
            if not 0 <= lo <= point <= hi <= 1 or radius > EPS: faults.append("invalid probability geometry")
            if row.get("guarantee") == "EXACT" and not lo == point == hi: faults.append("nonpoint exact row")
            pubs[key] = (lo, hi, point); labels[key] = row.get("guarantee"); maxradius = max(maxradius, radius); maxwidth = max(maxwidth, hi - lo)
        except Exception as e:
            faults.append("invalid rational: " + repr(e))
    if seen != expected: faults.append("query inventory mismatch")
    if d.get("K") != len(expected) or d.get("published") != len(pubs): faults.append("reported counts mismatch")
    if pubs and d.get("positive_mass_witness") is not True: faults.append("missing positive mass witness")
    if len(pubs) == len(expected) and d.get("guarantee") not in ("EXACT", "DETERMINISTIC", "PAC"): faults.append("unknown aggregate guarantee")
    if pubs and d.get("guarantee") == "EXACT" and any(l != "EXACT" for l in labels.values()): faults.append("aggregate EXACT over non-exact rows")
    if pubs and d.get("guarantee") == "DETERMINISTIC" and any(l.startswith("PAC") for l in labels.values()): faults.append("aggregate DETERMINISTIC over PAC rows")
    binding = d.get("binding") or {}
    if binding.get("model_sha256") != task["model_sha256"] or binding.get("evidence_sha256") != task["evidence_sha256"]: faults.append("input binding mismatch")
    for v, k in enumerate(cards):
        if v in ev or not all((v, a) in pubs for a in range(k)): continue
        if not sum(pubs[v, a][0] for a in range(k)) <= 1 <= sum(pubs[v, a][1] for a in range(k)): faults.append("simplex enclosure mismatch")
    contract_faults = []
    if contract:
        if contract["reader"] == "legacy":
            argv = d.get("argv") or []
            for i in range(0, len(contract["argv_required"]), 2):
                flag, val = contract["argv_required"][i], contract["argv_required"][i + 1]
                if flag not in argv or argv[argv.index(flag) + 1] != val: contract_faults.append("argv %s" % flag)
            for k, v in contract["recorded"].items():
                if str(d.get(k)) != v: contract_faults.append("recorded %s=%r" % (k, d.get(k)))
            # STEP2_AMENDMENT_2: the legacy engine's own contract is the outer 20 s receipt plus its 19.5 s budget; at DEADLINE it keeps the partial
            # rows computed before the deadline and its internal wall includes the deadline handling / serialization.  A partial publication
            # with an internal wall past 19.5 s is recorded as a DIAGNOSTIC (never a completion), not as a contract fault; the new public
            # arms are held to `hard_deadline_respected` instead.
            late_partial = bool(d.get("wall_s") is not None and d["wall_s"] > PGM_ALLOWANCE_S)
            if d.get("wall_s") is None: contract_faults.append("internal wall missing")
        else:
            if d.get("policy") != contract["policy"]: contract_faults.append("policy %r" % d.get("policy"))
            if "policy_version" in contract and d.get("policy_version") != contract["policy_version"]: contract_faults.append("policy_version %r" % d.get("policy_version"))
            if str(d.get("epsilon")) != contract["epsilon"] or str(d.get("delta")) != contract["delta"]: contract_faults.append("epsilon/delta %r/%r" % (d.get("epsilon"), d.get("delta")))
            if d.get("hard_deadline_respected") is not True: contract_faults.append("hard deadline not respected")
            used = [a.get("backend") for a in d.get("attempts") or []]
            if any(b not in contract["backends_allowed"] for b in used): contract_faults.append("backend outside the policy: %r" % used)
            if "risk_shares" in contract:
                expected_alloc = {k: str(F(v) * F(contract["delta"])) for k, v in contract["risk_shares"].items()}      # the result records ABSOLUTE prospective allocations = share x requested delta
                if (d.get("risk_allocations") or {}) != expected_alloc: contract_faults.append("risk allocations %r (expected %r)" % (d.get("risk_allocations"), expected_alloc))
            if "configuration" in contract:
                for a in d.get("attempts") or []:
                    cfg = a.get("configuration") or {}
                    for k, v in contract["configuration"].items():
                        if cfg.get(k) != v: contract_faults.append("attempt configuration %s=%r" % (k, cfg.get(k)))
            if any(a.get("outcome") == "NOT_STARTED" for a in d.get("attempts") or []): contract_faults.append("unresolved attempt")
            total = sum((F(x) for x in (d.get("risk_allocations") or {}).values()), F(0))
            if (d.get("risk_allocations") is not None) and total > F(contract["delta"]): contract_faults.append("prospective risk exceeds delta")
            if pubs and any(l.startswith("PAC") for l in labels.values()) and d.get("mode", "auto") != "auto": contract_faults.append("PAC rows under a non-PAC mode")
    return dict(output_valid=not faults, validation_faults=sorted(set(faults)), contract_valid=not contract_faults, contract_faults=sorted(set(contract_faults)), legacy_internal_wall_past_allowance=(late_partial if contract and contract["reader"] == "legacy" else None),
                solver_outcome=d.get("outcome"), guarantee=d.get("guarantee"), published=len(pubs), K=len(expected),
                all_queries_returned=not faults and len(pubs) == len(expected) and d.get("outcome") in ("COMPLETE", "EXACT"),
                max_published_radius=float(maxradius), max_published_width=float(maxwidth), backend=d.get("backend"),
                policy=d.get("policy"), policy_version=d.get("policy_version"), risk_allocations=d.get("risk_allocations"),
                attempts=[dict(backend=a.get("backend"), outcome=a.get("outcome"), wall_s=a.get("wall_s")) for a in (d.get("attempts") or [])] or None,
                route=((d.get("mechanism") or {}).get("route") if isinstance(d.get("mechanism"), dict) else None), solver_wall_s=d.get("wall_s"),
                published_rows={"%d:%d" % k: dict(lo=str(v[0]), hi=str(v[1]), point=str(v[2]), label=labels[k]) for k, v in pubs.items()})


def read_mar(path, task):
    cards, ev = metadata(task)
    t = iter(Path(path).read_text().split())
    if next(t) != "MAR" or int(next(t)) != len(cards): raise ValueError("MAR header")
    points = {}
    for v, k in enumerate(cards):
        if int(next(t)) != k: raise ValueError("MAR cardinality")
        row = [float(next(t)) for _ in range(k)]
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in row) or abs(sum(row) - 1) > 1e-7: raise ValueError("MAR probability row")
        if v in ev and any(abs(x - int(a == ev[v])) > 1e-10 for a, x in enumerate(row)): raise ValueError("evidence mismatch")
        points.update({(v, a): x for a, x in enumerate(row)})
    if next(t, None) is not None: raise ValueError("MAR trailing data")
    return points


def check_libdai(folder, task):
    side = json.loads((folder / "side.json").read_text()) if (folder / "side.json").exists() else {}
    points = read_mar(folder / "output.MAR", task)
    return dict(output_valid=True, validation_faults=[], contract_valid=True, contract_faults=[], solver_outcome="COMPLETE" if side.get("converged") else "COMPLETE_UNCONVERGED", guarantee="POINT_ONLY",
                all_queries_returned=True, converged=side.get("converged"), iterations=side.get("iterations"), maxdiff=side.get("maxdiff"), output_coordinates=len(points), solver_wall_s=(side.get("phases_s") or {}).get("total"))


def tasks_from_manifest(path, key="tasks"):
    d = json.loads(Path(path).read_text()); out = []
    for r in d[key]:
        t = dict(r)
        for k in ("model", "evidence"):
            t[k] = str((HERE / t[k]).resolve()); t[k + "_relative"] = str(Path(t[k]).relative_to(REPO)); assert sha(t[k]) == t[k + "_sha256"]
        out.append(t)
    return out


def relocate_frozen_tasks(frozen):
    for task in frozen["tasks"]:
        for key in ("model", "evidence"):
            relative = task.get(key + "_relative")
            if relative is not None:
                path = (REPO / relative).resolve()
                if not path.is_relative_to(REPO): raise ValueError("Frozen input path escapes repository")
                task[key] = str(path)
    return frozen


def receipts(path):
    if not Path(path).exists(): return []
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("kind") == "RECEIPT": out.append(r)
    return out


# ---------------------------------------------------------------------------------------------------- commands
def arm_command(arm, task, folder, rep, frozen):
    budget = frozen["budget_s"]
    if arm == "PGM_REFERENCE":
        root = root_of(arm, frozen)
        return [str(PY), str(root / "code/cex/blockres/integrated.py"), "--input", task["model"], "--output", str(folder / "result.json"), "--budget", str(PGM_ALLOWANCE_S), "--seed", str(rep),
                "--epsilon", "1/200", "--delta", "1/1000000", "--schedule", "targeted", "--route", "auto", "--proposal", "mb"]
    if arm == "PGM_EXPERIMENTAL_REF":
        return [str(PY), "-m", "pgm", "--input", task["model"], "--output", str(folder / "result.json"), "--budget", str(PGM_ALLOWANCE_S), "--memory-mib", str(MEMORY_MIB), "--seed", str(rep), "--epsilon", "1/200", "--delta", "1/1000000"]
    if is_public(arm):
        return [str(PY), "-m", "pgm", "--input", task["model"], "--output", str(folder / "result.json"), "--budget", str(PGM_ALLOWANCE_S), "--memory-mib", str(MEMORY_MIB), "--seed", str(rep),
                "--epsilon", "1/200", "--delta", "1/1000000", "--policy", frozen["pgm_policies"][arm]]
    alg = "JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]" if arm == "LIBDAI_JT" else f"BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime={budget-1.0}]"
    return [str(LIBDAI), task["model"], task["evidence"], str(folder / "output.MAR"), str(folder / "side.json"), alg]


def supervised(cmd, env, ledger, scope, job, folder, budget):
    """launch under the strict zero-grace supervisor of THIS repository (the supervisor's own import root is the main checkout;
    the child gets the arm's environment through --env)"""
    sup_env = dict(env, PYTHONPATH=str(REPO / "src") + os.pathsep + str(REPO / "code"))
    sup = [str(PY), str(HERE / "strict_supervisor.py"), "--ledger", str(ledger), "--scope", scope, "--job", job, "--timeout", str(budget), "--mem-gib", "3", "--interval", "0.01",
           "--cwd", str(REPO), "--stdout", str(folder / "stdout.log"), "--stderr", str(folder / "stderr.log"), "--env", "PYTHONPATH=" + env["PYTHONPATH"]]
    if "PGM_NATIVE_CACHE" in env: sup += ["--env", "PGM_NATIVE_CACHE=" + env["PGM_NATIVE_CACHE"]]
    return sup + ["--"] + cmd, sup_env


def run_cell(task, arm, rep, frozen):
    budget = frozen["budget_s"]; job = f'{task["split"]}__{task["name"]}__{arm}__r{rep}'; folder = ROOT / "runs" / job; ledger = ROOT / "RECEIPTS.jsonl"
    assert identity() == frozen["engine_files"], "Source/build changed before cell"
    for k in ("model", "evidence"): assert sha(task[k]) == task[k + "_sha256"]
    assert sha(LIBDAI) == frozen["libdai_sha256"]
    prior = [r for r in receipts(ledger) if r["job"] == job]
    assert len(prior) <= 1, "Duplicate terminal receipt"
    if not prior:
        folder.mkdir(parents=True, exist_ok=False)
        cmd = arm_command(arm, task, folder, rep, frozen); env = arm_env(arm, frozen)
        sup, sup_env = supervised(cmd, env, ledger, task["split"], job, folder, budget)
        dump(folder / "launch.json", {"command": cmd, "supervisor": sup, "task": task, "arm": arm, "replicate": rep, "environment_overrides": {k: env.get(k) for k in ("PYTHONPATH", "CC", "CXX", "PGM_NATIVE_CACHE", "OMP_NUM_THREADS", "PYTHONHASHSEED")},
                                     "launch_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "engine_commit": frozen["engine_commit"]})
        with (folder / "supervisor.log").open("ab") as log:
            subprocess.run(sup, cwd=REPO, env=sup_env, stdout=log, stderr=log)
    receipt = [r for r in receipts(ledger) if r["job"] == job][-1]
    row = {"job": job, "task": task["name"], "arm": arm, "replicate": rep, "split": task["split"], "historical_group": task.get("historical_group"), "exposure_status": task.get("exposure_status"), "historical_cohort": task["historical_cohort"],
           "model_sha256": task["model_sha256"], "evidence_sha256": task["evidence_sha256"], "wall_s": receipt["wall_s"], "budget_s": budget, "receipt_outcome": receipt["outcome"], "returncode": receipt["returncode"],
           "peak_rss_bytes": receipt["peak_tree_rss_bytes"], "cleanup_unresolved": receipt.get("cleanup_unresolved"), "identity_ok": identity() == frozen["engine_files"] and sha(LIBDAI) == frozen["libdai_sha256"]}
    try:
        row.update(check_pgm(folder / "result.json", task, frozen["contracts"].get(arm), budget) if is_pgm(arm) else check_libdai(folder, task))
    except Exception as e:
        row.update(output_valid=False, contract_valid=False, all_queries_returned=False, validation_error=repr(e))
    row["complete_within_contract"] = bool(row["identity_ok"] and row.get("all_queries_returned") and row.get("contract_valid", True) and receipt["outcome"] == "COMPLETED" and receipt["wall_s"] <= budget and receipt.get("cleanup_unresolved") is not True)
    row["converged_within_contract"] = row["complete_within_contract"] and (arm != "LIBDAI_BP" or row.get("converged", False))
    dump(folder / "cell.json", row)
    with (ROOT / "CELLS.jsonl").open("a") as f: f.write(json.dumps(row, default=str) + "\n")
    print(json.dumps({k: row.get(k) for k in ("job", "complete_within_contract", "solver_outcome", "wall_s", "guarantee", "validation_error", "contract_faults")}), flush=True)
    assert row["identity_ok"], "Source/build changed after cell"
    return row


# ---------------------------------------------------------------------------------------------------- setup / freeze / run
def _build_root(arm):
    """compile + warm every kernel of the arm's root OUTSIDE any timed cell"""
    env = arm_env(arm); root = root_of(arm)
    if arm == "PGM_REFERENCE":
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("code/cex/newarm", "code/cex/blockres", "code"))
        code = "import cex_executor as CX, stream_float as SF; p=CX.build(); CX.load(p); s=SF.build(); SF._load_verified(s); print('built', p['binary_sha256'][:12], s['binary_sha256'][:12])"
    elif arm == "PGM_EXPERIMENTAL_REF":
        env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("code/cex/newarm", "code/cex/blockres", "code/cex/hp", "code", "src"))
        code = "import cex_executor as CX, stream_float as SF, heatbath_native as HN; p=CX.build(); CX.load(p); s=SF.build(); SF._load_verified(s); HN.build(); print('built', p['binary_sha256'][:12], s['binary_sha256'][:12])"
    else:
        code = "import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.algorithms.response.heatbath_native as HN; p=CX.build(); CX.load(p); s=SF.build(); SF._load_verified(s); HN.build(); print('built', p['binary_sha256'][:12], s['binary_sha256'][:12])"
    p = subprocess.run([str(PY), "-c", code], capture_output=True, text=True, env=env, cwd=str(root), timeout=1800)
    if p.returncode: raise RuntimeError("build failed for %s: %s" % (arm, p.stderr[-1200:]))
    return p.stdout.strip()


def setup():
    """build/warm all kernels; smoke every arm on the committed tiny fixture under the supervisor; retain everything under ROOT/setup"""
    ROOT.mkdir(parents=True, exist_ok=True); S = ROOT / "setup"; S.mkdir(exist_ok=True)
    rec = dict(started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), compilers=resolve_compilers(), native_cache=NATIVE_CACHE, builds={}, natives={}, roots={}, smoke={})
    for arm in ("PGM_ACCEPTED", "PGM_REFERENCE", "PGM_EXPERIMENTAL_REF"):
        rec["builds"][arm] = _build_root(arm)
    for arm in RESULT_ARMS:
        rec["natives"][arm] = native_probe(arm, want_heat=(arm != "PGM_REFERENCE"))
    for arm in ("PGM_REFERENCE", "PGM_EXPERIMENTAL_REF"): rec["roots"][arm] = root_identity(arm)
    # the committed tiny fixture is STAGED under the run directory (never written into the source tree); no evidence = the explicit empty evidence file
    staged = S / "fixture"; staged.mkdir(exist_ok=True); fixture = staged / "asym2.uai"; shutil.copy(REPO / "tests/parity/fixtures/asym2.uai", fixture); (staged / "asym2.uai.evid").write_text("0\n")
    task = dict(name="setup_asym2", split="setup", model=str(fixture), evidence=str(staged / "asym2.uai.evid"), model_sha256=sha(fixture), evidence_sha256=sha(staged / "asym2.uai.evid"), historical_cohort="setup", source_fixture="tests/parity/fixtures/asym2.uai")
    pseudo = dict(budget_s=BUDGET_S, pgm_policies=PGM_ARMS, compilers=rec["compilers"], native_cache=NATIVE_CACHE, contracts=CONTRACTS, roots={a: rec["roots"][a] for a in rec["roots"]})
    for arm in ARMS:
        folder = S / arm; folder.mkdir(exist_ok=True)
        cmd = arm_command(arm, task, folder, 1, pseudo); env = arm_env(arm, pseudo)
        sup, sup_env = supervised(cmd, env, S / "SETUP_RECEIPTS.jsonl", "setup", "setup__" + arm, folder, BUDGET_S)
        dump(folder / "launch.json", dict(command=cmd, supervisor=sup, environment_overrides={k: env.get(k) for k in ("PYTHONPATH", "CC", "CXX", "PGM_NATIVE_CACHE")}))
        with (folder / "supervisor.log").open("ab") as log: subprocess.run(sup, cwd=REPO, env=sup_env, stdout=log, stderr=log)
        receipt = [r for r in receipts(S / "SETUP_RECEIPTS.jsonl") if r["job"] == "setup__" + arm][-1]
        try:
            check = check_pgm(folder / "result.json", task, CONTRACTS.get(arm)) if is_pgm(arm) else check_libdai(folder, task)
        except Exception as e:
            check = dict(output_valid=False, contract_valid=False, all_queries_returned=False, validation_error=repr(e))
        rec["smoke"][arm] = dict(receipt_outcome=receipt["outcome"], wall_s=receipt["wall_s"], returncode=receipt["returncode"], output_valid=check.get("output_valid"), contract_valid=check.get("contract_valid"), all_queries_returned=check.get("all_queries_returned"),
                                 solver_outcome=check.get("solver_outcome"), guarantee=check.get("guarantee"), faults=(check.get("validation_faults") or []) + (check.get("contract_faults") or []), validation_error=check.get("validation_error"))
        print(json.dumps(dict(arm=arm, **rec["smoke"][arm])), flush=True)
    rec["smoke_all_valid"] = all(v["receipt_outcome"] == "COMPLETED" and v["output_valid"] and v["contract_valid"] and v["all_queries_returned"] for v in rec["smoke"].values())
    rec["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dump(S / "SETUP.json", rec)
    print(json.dumps(dict(setup_complete=rec["smoke_all_valid"], builds=rec["builds"])))
    return rec


def freeze():
    ROOT.mkdir(parents=True, exist_ok=True)
    assert not (ROOT / "FREEZE.json").exists(), "Freeze already exists; do not overwrite"
    setup_rec = json.loads((ROOT / "setup/SETUP.json").read_text()); assert setup_rec["smoke_all_valid"], "Setup smoke did not pass for every arm"
    assert LIBDAI.is_file() and os.access(LIBDAI, os.X_OK), "Set PGM_LIBDAI to the qualified comparator executable"
    compilers = resolve_compilers()
    changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO, text=True).splitlines()
    assert all(row[3:].startswith(GENERATED_PREFIXES) and ("native_cache/" in row[3:] or row[3:].endswith(("_build.json", ".dylib", ".so"))) for row in changes), "Commit source changes before freezing: " + repr(changes)
    natives = {arm: native_probe(arm, want_heat=(arm != "PGM_REFERENCE")) for arm in RESULT_ARMS}
    roots = {arm: root_identity(arm) for arm in ("PGM_REFERENCE", "PGM_EXPERIMENTAL_REF")}
    for arm, (rec, root) in [("PGM_REFERENCE", (natives["PGM_REFERENCE"], REFERENCE_ROOT))]:
        src = (Path(root) / "code/cex/blockres/integrated.py").read_text()
        assert "USABLE_BYTES = 2560 << 20" in src and "PROCESS_HEADROOM_BYTES = 160 << 20" in src, "reference internal memory policy differs from the recorded contract"
    exposed = tasks_from_manifest(HERE / "INPUT_MANIFEST.json"); former = tasks_from_manifest(HERE / "HOLDOUT_FREEZE.json")
    assert len(exposed) == 55 and all(t["split"] == "exposed_regression" for t in exposed) and len(former) == 6
    assert not {t["model_sha256"] for t in exposed} & {t["model_sha256"] for t in former}
    for t in exposed: t.update(historical_group="old55", exposure_status="exposed_regression")
    for t in former: t.update(historical_group="former_eval6", exposure_status="exposed_regression")
    tasks = exposed + former
    plan = json.loads((HERE / "STEP2_PLAN.json").read_text())
    frozen = {
        "schema": "CONSOLIDATION_EXTERNAL_V3", "amendment": "STEP2_AMENDMENT_1", "frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(), "engine_files": identity(),
        "harness_files": {n: sha(HERE / n) for n in HARNESS}, "input_manifests": {n: sha(HERE / n) for n in ("INPUT_MANIFEST.json", "HOLDOUT_FREEZE.json", "EXPOSURE_HISTORY.json")},
        "libdai_sha256": sha(LIBDAI), "libdai_binary": str(LIBDAI), "libdai_qualification": {n: sha(HERE / "provenance" / n) for n in ("LIBDAI_QUALIFICATION_HOST_2026-11-27.json",)},
        "runtime_python": str(PY), "compilers": compilers, "native_cache": NATIVE_CACHE, "natives": natives, "roots": roots,
        "tasks": tasks, "replicates": [1, 2], "arms": ARMS, "pgm_policies": dict(PGM_ARMS), "contracts": CONTRACTS, "pairs": PAIRS,
        "pgm_version": subprocess.check_output([str(PY), "-c", "import pgm; print(pgm.__version__)"], text=True, env=arm_env("PGM_ACCEPTED")).strip(),
        "budget_s": BUDGET_S, "pgm_allowance_s": PGM_ALLOWANCE_S, "memory_mib": MEMORY_MIB, "epsilon": "1/200", "delta": "1/1000000",
        "expected_cells": len(tasks) * len(ARMS) * 2, "scored_ceiling_s": plan["contract"]["scored_ceiling_s"], "gates": plan["acceptance"], "cost_criterion": plan["cost_criterion"],
        "python": subprocess.check_output([str(PY), "-c", "import sys; print(sys.version)"], text=True).strip(), "platform": platform.platform(), "machine": platform.machine(),
        "dependencies": subprocess.check_output([str(PY), "-m", "pip", "freeze"], text=True).splitlines(),
        "old_reference_engine": REFERENCE_COMMIT, "prior_reference_sha256": sha(REFERENCE), "prior_experimental_extract": plan.get("prior_experimental_extract"),
        "setup_sha256": sha(ROOT / "setup/SETUP.json"),
        "notes": ["All 61 inputs are exposed regression inputs; old55 / former_eval6 are historical groups only.", "One frozen implementation per arm; no per-task tuning or hindsight selection.",
                  "Same 20 s outer contract; pgm allowance 19.5 s; process-tree RSS sampled 10 ms, grace 0.", "Compilation happened in setup only; the artifacts actually loaded are hashed above.",
                  "The scored ceiling is the declared maximum charge of the full matrix; exhaustion returns INCOMPLETE."],
    }
    assert frozen["scored_ceiling_s"] >= frozen["expected_cells"] * BUDGET_S or plan["contract"].get("ceiling_below_maximum_acknowledged"), "declare a ceiling covering the full matrix or acknowledge the shortfall in the plan"
    dump(ROOT / "FREEZE.json", frozen)
    print(json.dumps({"frozen": True, "engine_commit": frozen["engine_commit"], "cells": frozen["expected_cells"], "ceiling_s": frozen["scored_ceiling_s"], "arms": ARMS}))


def run(phase):
    frozen = json.loads((ROOT / "FREEZE.json").read_text())
    assert str(PY) == frozen["runtime_python"], "Use the frozen runtime interpreter or declare a new experiment"
    assert str(LIBDAI) == frozen["libdai_binary"], "Use the frozen comparator path or declare a new experiment"
    assert sha(REFERENCE) == frozen["prior_reference_sha256"], "Historical reference changed"
    assert (os.environ.get("PGM_NATIVE_CACHE") or None) == frozen["native_cache"], "PGM_NATIVE_CACHE differs from the frozen setting"
    split = "exposed_regression" if phase == "primary" else "prospective_external_eval"
    tasks = [t for t in frozen["tasks"] if t["split"] == split]
    done = {json.loads(line)["job"] for line in (ROOT / "CELLS.jsonl").read_text().splitlines()} if (ROOT / "CELLS.jsonl").exists() else set()
    jobs = [(t, a, r) for r in frozen["replicates"] for i, t in enumerate(tasks) for a in (frozen["arms"] if (i + r) % 2 else list(reversed(frozen["arms"])))]
    for task, arm, rep in jobs:
        for n, h in frozen["harness_files"].items(): assert sha(HERE / n) == h, "Harness changed after freeze: " + n
        for n, h in frozen["input_manifests"].items(): assert sha(HERE / n) == h, "Input manifest changed after freeze: " + n
        job = f'{split}__{task["name"]}__{arm}__r{rep}'
        if job in done: continue
        charge = sum(r["wall_s"] for r in receipts(ROOT / "RECEIPTS.jsonl"))
        if charge + frozen["budget_s"] + 1 > frozen["scored_ceiling_s"]:
            dump(ROOT / "BUDGET_STOP.json", {"charged_s": charge, "next": job, "status": "INCOMPLETE: scored ceiling exhausted; remaining cells NOT run"}); return
        run_cell(task, arm, rep, frozen)
    dump(ROOT / (phase.upper() + "_RETURN.json"), {"phase": phase, "planned_cells": len(jobs), "completed_cells": sum(1 for p in (ROOT / "runs").glob("*/cell.json") if json.loads(p.read_text())["split"] == split),
                                                   "charged_s": sum(r["wall_s"] for r in receipts(ROOT / "RECEIPTS.jsonl"))})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("action", choices=["setup", "freeze", "primary", "eval"]); a = ap.parse_args()
    {"setup": setup, "freeze": freeze}.get(a.action, lambda: run(a.action))()
