"""Clean-wheel relocation test (brief section 7; repair R3: the gate ENFORCES its claims).

Install the built wheel into a FRESH virtualenv outside the repository and exercise the installed package with `python -I`
from a working directory holding only copied fixtures.  Every required probe must succeed with the expected output / route:
module origins (all pgm modules from site-packages), capabilities, the public CLI under BOTH policies (COMPLETE, full
original inventory, expected guarantee and backend), all FOUR adapters through the worker (COMPLETE with the expected
route; the bipartite STREAM kernel is forced on bip4 and must report native execution), tiny CBI and SF solve-and-check
round trips through pgm.specialists, H4 native witnesses, checked CQR queries and normalizer, and an actual native build + load
under PGM_NATIVE_CACHE with the loaded binary's location and identity verified.  `verdict(receipt)` is a pure function
(unit-tested with negative controls in tests/test_qualification_tools.py); the process exits 1 on FAIL.
usage: clean_wheel_relocation_test.py WHEEL OUT_DIR
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
from fractions import Fraction as F
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests/parity/fixtures"
sys.path.insert(0, str(REPO / "src"))
from pgm.model.uai import read_uai as _read_uai                                          # the checkout's exact reader fixes the EXPECTED inventory of each fixture (never reconstructed from returned rows)


def expected_inventory(fixture_name):
    """the exact original nonobserved coordinate set and cardinalities of a committed fixture"""
    model, _ = _read_uai(FIXTURES / fixture_name)
    ev = model["evidence"]
    return {(v, a) for v, k in enumerate(model["cards"]) if v not in ev for a in range(k)}, model["cards"]
REQUIRED = ("venv", "pip_install", "module_origins", "capabilities", "cli_accepted", "cli_experimental", "worker_structural", "worker_stream", "worker_block",
            "worker_quotient", "worker_response", "specialists", "native_cache_override", "native_build_locations")
EXPECT = {
    "cli_accepted": dict(fixture="pos4.uai", outcome="COMPLETE", policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", backends=["block"], guarantee_in=("EXACT", "DETERMINISTIC")),
    "cli_experimental": dict(fixture="pos4.uai", outcome="COMPLETE", policy="experimental", policy_version="structural-portfolio-1", backends=["structural"], guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_structural": dict(fixture="asym2.uai", outcome="COMPLETE", route="structural", guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_stream": dict(fixture="bip4.uai", outcome="COMPLETE", route="structural", component_route="stream", solver="certified_binary64_product_tree_stream", guarantee_in=("DETERMINISTIC",)),
    "worker_block": dict(fixture="cyc3_card3.uai", outcome="COMPLETE", guarantee_in=("EXACT", "DETERMINISTIC")),
    "worker_quotient": dict(fixture="cyc3_card3.uai", outcome="COMPLETE", guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_response": dict(fixture="pos4.uai", outcome="COMPLETE", route="spectral_heatbath_response", guarantee_in=("PAC",)),
}


def run(cmd, env, cwd, timeout=600):
    t0 = time.monotonic(); p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(cwd), timeout=timeout)
    return dict(cmd=[str(c) for c in cmd], returncode=p.returncode, seconds=round(time.monotonic() - t0, 3), stdout_tail=p.stdout[-3000:], stderr_tail=p.stderr[-1500:], stdout_full=p.stdout)


def _rows_ok(res, expected_keys, cards):
    """EXACTLY the fixture's original coordinate set, each key once, every row published with valid rational geometry, EXACT rows
    pointlike, the per-variable box inside the simplex, positive mass witnessed"""
    rows = res.get("answers") or []
    keys = [(r.get("variable", r.get("var")), r.get("state")) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != set(expected_keys) or res.get("K") != len(expected_keys) or res.get("published") != len(expected_keys): return False
    if any(r.get("guarantee") in (None, "NOT_PUBLISHED") for r in rows): return False
    by_var = {}
    try:
        for r in rows:
            lo, hi, pt = F(r["lo"]), F(r["hi"]), F(r["point"])
            if not 0 <= lo <= pt <= hi <= 1 or max(pt - lo, hi - pt) > F(1, 200): return False
            if r["guarantee"] == "EXACT" and lo != hi: return False
            by_var.setdefault(r.get("variable", r.get("var")), []).append((lo, hi))
    except (KeyError, ValueError, ZeroDivisionError, TypeError):
        return False
    return all(len(g) == cards[v] and sum(l for l, _ in g) <= 1 <= sum(h for _, h in g) for v, g in by_var.items()) and res.get("positive_mass_witness") is True


def verdict(receipt):
    """-> (verdict, failures): FAIL unless every required step exited 0 with the expected result"""
    failures = []; steps = receipt.get("steps", {})
    for name in REQUIRED:
        s = steps.get(name)
        if not s: failures.append(name + ": missing"); continue
        if s.get("returncode") != 0: failures.append("%s: exit %s" % (name, s.get("returncode")))
    try:
        if '"all_from_site_packages": true' not in steps.get("module_origins", {}).get("stdout_tail", ""): failures.append("module_origins: a pgm module does not come from site-packages")
        caps = json.loads(steps.get("capabilities", {}).get("stdout_full", steps.get("capabilities", {}).get("stdout_tail", "null")) or "null")
        if not isinstance(caps, dict) or {k for k, v in caps.items() if v.get("status") == "selectable"} != {"structural", "block", "quotient", "response"}: failures.append("capabilities: selectable set wrong")
    except ValueError: failures.append("capabilities: unparsable")
    for name, exp in EXPECT.items():
        res = steps.get(name, {}).get("result")
        if not isinstance(res, dict) or "answers" not in res: failures.append(name + ": no result record"); continue
        expected_keys, cards = expected_inventory(exp["fixture"])
        if res.get("outcome") != exp["outcome"]: failures.append("%s: outcome %s" % (name, res.get("outcome")))
        if res.get("K") != len(expected_keys) or res.get("published") != len(expected_keys): failures.append("%s: inventory %s/%s (expected %d)" % (name, res.get("published"), res.get("K"), len(expected_keys)))
        if res.get("guarantee") not in exp["guarantee_in"]: failures.append("%s: guarantee %s" % (name, res.get("guarantee")))
        if not _rows_ok(res, expected_keys, cards): failures.append(name + ": published coordinate set / geometry invalid (exact original inventory, unique keys, rational geometry, simplex, witness)")
        if "policy" in exp and (res.get("policy") != exp["policy"] or res.get("policy_version") != exp["policy_version"]): failures.append(name + ": policy record")
        if "backends" in exp and [a["backend"] for a in res.get("attempts", []) if a.get("outcome") == "COMPLETE"] != exp["backends"]: failures.append(name + ": backend sequence")
        if "route" in exp and (res.get("mechanism") or {}).get("route") != exp["route"]: failures.append("%s: route %s" % (name, (res.get("mechanism") or {}).get("route")))
        if "component_route" in exp:
            comps = ((res.get("mechanism") or {}).get("stats") or {}).get("components") or []
            if not comps or any(c.get("route") != exp["component_route"] for c in comps) or any((c.get("stats") or {}).get("solver") != exp["solver"] for c in comps) or any("native_event_counter_bound" not in (c.get("stats") or {}) for c in comps):
                failures.append(name + ": the native stream kernel did not execute")
    sp = steps.get("specialists", {}).get("result")
    if not isinstance(sp, dict): failures.append("specialists: no record")
    else:
        if (sp.get("cbi") or {}).get("status") != "CERTIFIED" or (sp.get("cbi") or {}).get("verified") is not True: failures.append("specialists: CBI round trip")
        if (sp.get("sf") or {}).get("route_status") != "OK" or (sp.get("sf") or {}).get("checker") != "VERIFIED": failures.append("specialists: SF round trip")
        h4 = sp.get("h4a") or {}
        if h4.get("available") is not True or h4.get("witness") != {"all_ok": True, "roles": 4, "verdicts": {"C": "VERIFIED", "PI": "VERIFIED", "PP": "VERIFIED"}} or h4.get("source_unchanged") is not True: failures.append("specialists: H4 installed native witnesses and independent checks")
        cqr = sp.get("cqr") or {}
        if cqr.get("kind") != "VERIFIED" or "site-packages" not in str(cqr.get("origin", "")) or cqr.get("cases") != {"queries": {"verified": True, "points": ["2/5", "1/2", "3/4"]}, "normalizer": {"verified": True, "points": ["10"]}}: failures.append("specialists: CQR exact queries and normalizer must solve and independently verify from the wheel")
        registry = sp.get("method_registry") or {}
        if set(registry) != {"cbi", "sf", "cqr", "h4"} or any(not item.get("module", "").startswith("pgm.") or item.get("status") != {"cbi": "specialist", "sf": "specialist", "cqr": "specialist", "h4": "reference"}.get(name) for name, item in registry.items()): failures.append("specialists: public method registry")
        if any("site-packages" not in (sp.get(k) or {}).get("origin", "") for k in ("cbi", "sf")): failures.append("specialists: origin not site-packages")
    nc = steps.get("native_cache_override", {}).get("result")
    if not isinstance(nc, dict) or not nc.get("under_override") or not nc.get("identity_ok") or not nc.get("stream_under_override"): failures.append("native_cache_override: build/load under PGM_NATIVE_CACHE not verified")
    nb = steps.get("native_build_locations", {}).get("result")
    if not isinstance(nb, dict) or not all(nb.get(k) is True for k in ("cex_lib_exists", "stream_lib_exists", "heat_record_exists", "outside_package", "under_declared_cache", "source_unchanged")): failures.append("native_build_locations: native artifacts must exist under declared external caches without changing installed package files")
    return ("PASS" if not failures else "FAIL"), failures


def _result(path):
    try:
        res = json.loads(Path(path).read_text())
        return dict(outcome=res.get("outcome"), guarantee=res.get("guarantee"), published=res.get("published"), K=res.get("K"), policy=res.get("policy"), policy_version=res.get("policy_version"),
                    attempts=[dict(backend=a.get("backend"), outcome=a.get("outcome")) for a in res.get("attempts", [])], mechanism=res.get("mechanism"), answers=res.get("answers"), positive_mass_witness=res.get("positive_mass_witness"))
    except Exception as e:
        return dict(error=repr(e))


def main():
    wheel = Path(sys.argv[1]).resolve(); out_dir = Path(sys.argv[2]).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pgm-relocation-", dir=str(out_dir))); venv = work / "venv"; fx = work / "fixtures"; fx.mkdir()
    for f in FIXTURES.iterdir(): shutil.copy(f, fx / f.name)
    receipt = dict(wheel=str(wheel), wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), work_dir=str(work), python=sys.executable, steps={})
    S = receipt["steps"]
    S["venv"] = run([sys.executable, "-m", "venv", str(venv)], dict(os.environ), work)
    py = venv / "bin" / "python"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PGM_NATIVE_CACHE")}; env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", ""); env["XDG_CACHE_HOME"] = str(work / "default_cache")
    S["pip_install"] = run([str(py), "-m", "pip", "install", "-q", str(wheel)], env, work, timeout=1200)
    S["module_origins"] = run([str(py), "-I", "-c", "import json, sys, pgm, pgm.api, pgm.switchboard, pgm.backends.worker, pgm.algorithms.structural.core, pgm.algorithms.block.integrated, pgm.algorithms.quotient.unified_pac_planner, pgm.algorithms.response.spectral_heatbath_run, pgm.runtime.supervise;"
                              "from pathlib import Path; import hashlib; package=Path(pgm.__file__).parent; "
                              "snapshot={str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob('*') if p.is_file() and '__pycache__' not in p.parts}; Path('installed_snapshot.json').write_text(json.dumps(snapshot)); "
                              "mods={m: (getattr(sys.modules[m], '__file__', None) or '') for m in sys.modules if m.startswith('pgm')};"
                              "print(json.dumps(dict(version=pgm.__version__, all_from_site_packages=all('site-packages' in f for f in mods.values() if f), n=len(mods), outside=[f for f in mods.values() if f and 'site-packages' not in f])))"], env, work)
    S["capabilities"] = run([str(py), "-I", "-m", "pgm", "--capabilities"], env, work)
    for pol in ("accepted", "experimental"):
        r = run([str(py), "-I", "-m", "pgm", "--input", "fixtures/pos4.uai", "--output", "out_%s.json" % pol, "--budget", "30", "--memory-mib", "2048", "--seed", "1", "--epsilon", "1/200", "--delta", "1/1000000", "--policy", pol], env, work, timeout=200)
        r["result"] = _result(work / ("out_%s.json" % pol)); S["cli_" + pol] = r
    for name, backend, model, extra in [("worker_structural", "structural", "asym2.uai", []), ("worker_stream", "structural", "bip4.uai", ["--structural-route", "stream"]), ("worker_block", "block", "cyc3_card3.uai", []),
                                        ("worker_quotient", "quotient", "cyc3_card3.uai", ["--mode", "deterministic", "--delta", "0"]), ("worker_response", "response", "pos4.uai", [])]:
        out = work / (name + ".json")
        deadline = run([str(py), "-I", "-c", "import time; print(repr(time.monotonic()+25))"], env, work)["stdout_tail"].strip()
        r = run([str(py), "-I", "-m", "pgm.backends.worker", "--backend", backend, "--input", "fixtures/" + model, "--output", str(out), "--deadline", deadline, "--memory-mib", "1024", *extra], env, work, timeout=120)
        r["result"] = _result(out); S[name] = r
    spec = r'''
import json, time
from fractions import Fraction as Fr
from pgm.specialists import cbi, sf, h4a, cqr
out = {}
api, model = cbi.modules()
obj = {"d": 1, "blocks": [{"id": 0, "rows": [0, 1], "weights": [1, 2]}, {"id": 1, "rows": [0, 1], "weights": [3, 1]}], "edges": [{"u": 0, "v": 1, "r": "1/2"}]}
res = api.solve(obj, "all", "1/100"); ver = api.verify(obj, res)
out["cbi"] = dict(status=res["status"], verified=bool(ver["accepted"]), queries=sorted(res["intervals"]), origin=api.__file__)
core, routes, check = sf.modules()
law = core.Law(3, [(1, 1), (2, 2)], [(4, 1), (3, 1)]); sym, how = law.antipodal(); Pint, _ = law.overlap_int(); r = Fr(1, 2); eps = Fr(1, 100)
t_end = time.monotonic() + 60
def dl():
    if time.monotonic() > t_end: raise RuntimeError("cooperative deadline")
route, params, dec = core.select(law, r, eps, sym, Pint); rr = routes.run_route(law, r, route, params, sym, deadline=dl)
rr["published"] = [core.publish(lo, hi) for lo, hi in rr["intervals"]]          # the checker reads the published grid enclosures (as sf.invoke does)
try:
    chk = check.check(core.Law(3, [(1, 1), (2, 2)], [(4, 1), (3, 1)]), r, rr, sym); status = "VERIFIED"
except check.CheckFailure as e:
    status = "FAILED: " + str(e)
out["sf"] = dict(route=route, route_status=rr["status"], checker=status, intervals=[(str(a), str(b)) for a, b in rr.get("intervals", [])], origin=core.__file__)
from pathlib import Path
import hashlib, os, subprocess
from fractions import Fraction as F
from pgm.algorithms.h4 import kernels
os.environ["PGM_NATIVE_CACHE"] = str(Path("h4_native_cache").resolve())
source = Path(kernels.__file__).parent
before = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
kernels.build_all()
def run_tiny_witness(directory):
    """Exercise all native roles and their containment checks without a private packet."""
    from pgm.algorithms.h4.model import Model, NodeProblem
    from pgm.algorithms.h4.grid import Grid
    from pgm.algorithms.h4.emit import Cache, write_point_witness, write_rect_witness
    from pgm.algorithms.h4.build import producer_tables, checker_tables
    from pgm.algorithms.h4 import certs

    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    model = Model(4, 0)
    problem = NodeProblem(model, 0, 1, 2, [0, 0])
    grid = Grid([dict(h="1/2", J=0, a=2, R_tot=1, c_max=1, s=1, t=1)] * 2,
                representatives_expected=1)
    producer, checker = producer_tables(problem, 256), checker_tables(problem, 320)
    pc, cc = Cache(model, grid, 256), Cache(model, grid, 320)
    write_point_witness(directory / "p.txt", problem, grid, pc, producer, "producer")
    write_point_witness(directory / "c.txt", problem, grid, cc, checker, "checker")
    write_rect_witness(directory / "rp.txt", problem, grid, pc, producer, 256, "producer")
    write_rect_witness(directory / "rc.txt", problem, grid, cc, checker, 320, "checker")
    for name, stem, extra in [("h4point", "p", []), ("h4pcheck", "c", []),
                              ("h4rect", "rp", ["--prec", "256"]),
                              ("h4rect", "rc", ["--prec", "320", "--forward"])]:
        result = subprocess.run([str(kernels.kernel_path(name)), "--in", str(directory / (stem + ".txt")),
                                 "--out", str(directory / (stem + ".json")), "--expect-freq", "1", *extra],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    checks = {}
    for arm, prod, chk in [("C", "rp", "rc"), ("PI", "p", "rc"), ("PP", "p", "c")]:
        checks[arm] = certs.verify_node(arm, directory / (prod + ".json"),
                                       directory / (chk + ".json"), pc, cc, grid, problem)
        assert checks[arm]["verdict"] == "VERIFIED", checks[arm]
    # At zero frequency the marker masses form a probability distribution.
    point = json.loads((directory / "p.json").read_text())
    assert abs(sum((certs.fb(row["re"]) for row in point["channels"]), F(0)) - 1) <= 2 * certs.E_CH
    return dict(all_ok=True, roles=4, verdicts={arm: result["verdict"] for arm, result in checks.items()})
witness = run_tiny_witness("h4_witness")
after = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
out["h4a"] = dict(h4a.available(), witness=witness, source_unchanged=before == after)

from pathlib import Path
from pgm.algorithms.cqr import task as task_module, checker
model_path = Path("cqr_exact.uai")
model_path.write_text("MARKOV\n2\n2 2\n1\n2 0 1\n4\n1 2 3 4\n")
checks = {}
for label, queries, normalizer, expected in (
    ("queries", [dict(kind="joint", assign={"0": 1, "1": 1}), dict(kind="parity", variables=[0, 1], bit=1), dict(kind="conditional", event={"0": 1}, given={"1": 0})], False, [Fr(2, 5), Fr(1, 2), Fr(3, 4)]),
    ("normalizer", [], True, [Fr(10)]),
):
    Path(str(model_path) + ".query.json").write_text(json.dumps(dict(mode="EXACT_RATIONAL", epsilon="1/200", delta="0", queries=queries, normalizer_task=normalizer)))
    task = cqr.load_task(model_path); arm = "N1_NO_STRUCTURAL"
    result = cqr.solve(task, time.monotonic() + 5, arm, "wheel")
    assert result["outcome"] == "PUBLISHED", result
    pub = result["publication"]; names = ["Z"] if normalizer else [q.name for q in task["queries"]]
    worker = dict(result, status="COMPLETED", arm=arm, binding=task["binding"], task_identity=task_module.task_identity(task), mode=task["mode"], epsilon=str(task["epsilon"]), delta=str(task["delta"]), route=pub["route"], exact=bool(pub.get("exact")), answers=[dict(query=name, lo=str(lo), hi=str(hi), point=str(point), status="OK") for name, (lo, hi), point in zip(names, pub["bounds"], pub["point"])])
    failures, _ = checker.check_worker_output(str(model_path), json.loads(json.dumps(worker, default=str)), arm=arm, deadline=time.monotonic() + 5)
    assert failures == [], failures
    assert list(pub["point"]) == expected and list(pub["bounds"]) == [(v, v) for v in expected]
    checks[label] = dict(verified=True, points=[str(v) for v in pub["point"]])
out["cqr"] = dict(kind="VERIFIED", origin=task_module.__file__, cases=checks)
import pgm
out["method_registry"] = {name: dict(module=pgm.method(name).api.__name__, status=pgm.method(name).metadata["status"]) for name in ("cbi", "sf", "cqr", "h4")}
print(json.dumps(out))
'''
    r = run([str(py), "-I", "-c", spec], env, work, timeout=300)
    try: r["result"] = json.loads(r["stdout_full"].strip().splitlines()[-1])
    except Exception as e: r["result"] = dict(error=repr(e))
    S["specialists"] = r
    cache = work / "alt_cache"
    probe = r'''
import hashlib, json, os
import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.runtime.resources as R
prov = CX.build(); CX.load(prov); path = prov["loaded_binary_path"]
sp = SF.build(); SF._load_verified(sp); spath = os.path.join(R.native_cache_dir(os.path.dirname(SF.__file__)), "stream_" + sp["binary_sha256"] + ".so")
print(json.dumps(dict(cache_dir=R.native_cache_dir(os.path.dirname(CX.__file__)), loaded=path, under_override=path.startswith(os.environ["PGM_NATIVE_CACHE"]),
      identity_ok=(hashlib.sha256(open(path, "rb").read()).hexdigest() == prov["binary_sha256"]), stream_loaded=spath, stream_under_override=(os.path.exists(spath) and spath.startswith(os.environ["PGM_NATIVE_CACHE"])), record=str(CX.RECORD))))
'''
    r = run([str(py), "-I", "-c", probe], dict(env, PGM_NATIVE_CACHE=str(cache)), work, timeout=600)
    try: r["result"] = json.loads(r["stdout_full"].strip().splitlines()[-1])
    except Exception as e: r["result"] = dict(error=repr(e))
    S["native_cache_override"] = r
    locations = r'''
from pathlib import Path
import hashlib, json, pgm
import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.algorithms.response.heatbath_native as HN
from pgm.runtime.resources import native_cache_dir
package = Path(pgm.__file__).parent.resolve()
paths = {"cex_lib": Path(CX.LIB), "stream_lib": Path(SF.LIB), "heat_record": Path(HN.RECORD)}
owners = {"cex_lib": CX.BASE, "stream_lib": SF.BASE, "heat_record": HN.HERE}
snapshot = {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in package.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
print(json.dumps(dict(**{name: str(path) for name, path in paths.items()}, **{name + "_exists": path.is_file() for name, path in paths.items()},
    declared_caches={name: native_cache_dir(owners[name]) for name in paths},
    outside_package=all(not path.resolve().is_relative_to(package) for path in paths.values()),
    under_declared_cache=all(path.resolve().is_relative_to(Path(native_cache_dir(owners[name])).resolve()) for name, path in paths.items()),
    source_unchanged=snapshot == json.loads(Path("installed_snapshot.json").read_text()))))
'''
    r = run([str(py), "-I", "-c", locations], env, work)
    try: r["result"] = json.loads(r["stdout_full"].strip().splitlines()[-1])
    except Exception as e: r["result"] = dict(error=repr(e))
    S["native_build_locations"] = r
    receipt["verdict"], receipt["failures"] = verdict(receipt)
    (out_dir / "clean_wheel_relocation.json").write_text(json.dumps(receipt, indent=1, default=str) + "\n")
    print("clean wheel relocation:", receipt["verdict"], receipt["failures"])
    print(json.dumps({k: ((v.get("result") or {}).get("outcome") if isinstance(v.get("result"), dict) else v["returncode"]) for k, v in S.items()}, default=str))
    shutil.rmtree(venv, ignore_errors=True)
    sys.exit(0 if receipt["verdict"] == "PASS" else 1)


if __name__ == "__main__": main()
