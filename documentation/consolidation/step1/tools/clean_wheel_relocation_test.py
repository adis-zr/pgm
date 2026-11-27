"""Clean-wheel relocation test (brief section 7; repair R3: the gate ENFORCES its claims).

Install the built wheel into a FRESH virtualenv outside the repository and exercise the installed package with `python -I`
from a working directory holding only copied fixtures.  Every required probe must succeed with the expected output / route:
module origins (all pgm modules from site-packages), capabilities, the public CLI under BOTH policies (COMPLETE, full
original inventory, expected guarantee and backend), all FOUR adapters through the worker (COMPLETE with the expected
route; the bipartite STREAM kernel is forced on bip4 and must report native execution), tiny CBI and SF solve-and-check
round trips through pgm.specialists, h4a availability report, cqr typed UNAVAILABLE, and an actual native build + load
under PGM_NATIVE_CACHE with the loaded binary's location and identity verified.  `verdict(receipt)` is a pure function
(unit-tested with negative controls in tests/test_qualification_tools.py); the process exits 1 on FAIL.
usage: clean_wheel_relocation_test.py WHEEL OUT_DIR
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
from fractions import Fraction as F
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "tests/parity/fixtures"
REQUIRED = ("venv", "pip_install", "module_origins", "capabilities", "cli_accepted", "cli_experimental", "worker_structural", "worker_stream", "worker_block",
            "worker_quotient", "worker_response", "specialists", "native_cache_override", "native_build_locations")
EXPECT = {
    "cli_accepted": dict(outcome="COMPLETE", K=8, policy="accepted", policy_version="accepted-engine-v2.13.2-targeted/1", backends=["block"], guarantee_in=("EXACT", "DETERMINISTIC")),
    "cli_experimental": dict(outcome="COMPLETE", K=8, policy="experimental", policy_version="structural-portfolio-1", backends=["structural"], guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_structural": dict(outcome="COMPLETE", K=4, route="structural", guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_stream": dict(outcome="COMPLETE", K=8, route="structural", component_route="stream", solver="certified_binary64_product_tree_stream", guarantee_in=("DETERMINISTIC",)),
    "worker_block": dict(outcome="COMPLETE", K=8, guarantee_in=("EXACT", "DETERMINISTIC")),
    "worker_quotient": dict(outcome="COMPLETE", K=8, guarantee_in=("DETERMINISTIC", "EXACT")),
    "worker_response": dict(outcome="COMPLETE", K=8, route="spectral_heatbath_response", guarantee_in=("PAC",)),
}


def run(cmd, env, cwd, timeout=600):
    t0 = time.monotonic(); p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(cwd), timeout=timeout)
    return dict(cmd=[str(c) for c in cmd], returncode=p.returncode, seconds=round(time.monotonic() - t0, 3), stdout_tail=p.stdout[-3000:], stderr_tail=p.stderr[-1500:], stdout_full=p.stdout)


def _rows_ok(res):
    """every original coordinate published with valid rational geometry, EXACT rows pointlike, the box inside the simplex per variable"""
    rows = res.get("answers") or []
    if len(rows) != res.get("K") or any(r.get("guarantee") in (None, "NOT_PUBLISHED") for r in rows): return False
    by_var = {}
    for r in rows:
        lo, hi, pt = F(r["lo"]), F(r["hi"]), F(r["point"])
        if not 0 <= lo <= pt <= hi <= 1 or max(pt - lo, hi - pt) > F(1, 200): return False
        if r["guarantee"] == "EXACT" and lo != hi: return False
        by_var.setdefault(r.get("variable", r.get("var")), []).append((lo, hi))
    return all(sum(l for l, _ in g) <= 1 <= sum(h for _, h in g) for g in by_var.values()) and res.get("positive_mass_witness") is True


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
        if res.get("outcome") != exp["outcome"]: failures.append("%s: outcome %s" % (name, res.get("outcome")))
        if res.get("K") != exp["K"] or res.get("published") != exp["K"]: failures.append("%s: inventory %s/%s" % (name, res.get("published"), res.get("K")))
        if res.get("guarantee") not in exp["guarantee_in"]: failures.append("%s: guarantee %s" % (name, res.get("guarantee")))
        if not _rows_ok(res): failures.append(name + ": published geometry invalid")
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
        if not isinstance((sp.get("h4a") or {}).get("available"), bool): failures.append("specialists: h4a report")
        if (sp.get("cqr") or {}).get("kind") != "UNAVAILABLE": failures.append("specialists: cqr must be typed UNAVAILABLE from the wheel")
        if any("site-packages" not in (sp.get(k) or {}).get("origin", "") for k in ("cbi", "sf")): failures.append("specialists: origin not site-packages")
    nc = steps.get("native_cache_override", {}).get("result")
    if not isinstance(nc, dict) or not nc.get("under_override") or not nc.get("identity_ok") or not nc.get("stream_under_override"): failures.append("native_cache_override: build/load under PGM_NATIVE_CACHE not verified")
    nb = steps.get("native_build_locations", {}).get("result")
    if not isinstance(nb, dict) or not all(nb.get(k) for k in ("cex_lib_exists", "stream_lib_exists", "heat_record_exists")) or not all("site-packages" in nb.get(k, "") for k in ("cex_lib", "stream_lib", "heat_record")): failures.append("native_build_locations: kernels not built inside the installation")
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
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PGM_NATIVE_CACHE")}; env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    S["pip_install"] = run([str(py), "-m", "pip", "install", "-q", str(wheel)], env, work, timeout=1200)
    S["module_origins"] = run([str(py), "-I", "-c", "import json, sys, pgm, pgm.api, pgm.switchboard, pgm.backends.worker, pgm.algorithms.structural.core, pgm.algorithms.block.integrated, pgm.algorithms.quotient.unified_pac_planner, pgm.algorithms.response.spectral_heatbath_run, pgm.runtime.supervise;"
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
from pgm.specialists import cbi, sf, h4a, cqr, _bridge
out = {}
api, model = cbi.modules(); from cbi import generators as G
obj = G.mesh(2, 2, 4, 6, Fr(1, 64), 3); res = api.solve(obj, "all", "1/100"); ver = api.verify(obj, res)
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
out["h4a"] = h4a.available()
try:
    cqr.load_task("fixtures/asym2.uai"); out["cqr"] = dict(kind="LOADED")
except _bridge.SpecialistUnavailable as e:
    out["cqr"] = dict(kind=e.kind, reason=str(e))
out["bridge_code_root"] = str(_bridge.code_root()); print(json.dumps(out))
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
    r = run([str(py), "-I", "-c", "import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.algorithms.response.heatbath_native as HN, json, os; print(json.dumps(dict(cex_lib=str(CX.LIB), cex_lib_exists=os.path.exists(CX.LIB), cex_record=str(CX.RECORD), stream_lib=str(SF.LIB), stream_lib_exists=os.path.exists(SF.LIB), heat_record=str(HN.RECORD), heat_record_exists=os.path.exists(HN.RECORD))))"], env, work)
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
