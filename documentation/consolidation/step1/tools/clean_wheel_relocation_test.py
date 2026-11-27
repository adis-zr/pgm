"""Clean-wheel relocation test (brief section 7): install the built wheel into a FRESH virtualenv outside the repository and
exercise the installed package with `python -I` (isolated: no PYTHONPATH, no user site) from a working directory that
contains only copied fixtures -- the checkout and the private records are never on any import path.

Exercised: `python -m pgm --capabilities`; the public CLI under BOTH policies; all FOUR adapters through the worker; the
specialist entrypoints (cbi / sf installed; h4a reports its host kernels missing; cqr typed UNAVAILABLE); module origins
(every pgm module must come from site-packages); native kernels built on first use inside the installation; the
PGM_NATIVE_CACHE override.  Writes a JSON receipt.
usage: clean_wheel_relocation_test.py WHEEL OUT_DIR
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "tests/parity/fixtures"


def run(cmd, env, cwd, timeout=600):
    t0 = time.monotonic(); p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(cwd), timeout=timeout)
    return dict(cmd=[str(c) for c in cmd], returncode=p.returncode, seconds=round(time.monotonic() - t0, 3), stdout_tail=p.stdout[-1500:], stderr_tail=p.stderr[-1500:])


def main():
    wheel = Path(sys.argv[1]).resolve(); out_dir = Path(sys.argv[2]).resolve(); out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pgm-relocation-", dir=str(out_dir)))
    venv = work / "venv"; fx = work / "fixtures"; fx.mkdir()
    for f in FIXTURES.iterdir(): shutil.copy(f, fx / f.name)
    receipt = dict(wheel=str(wheel), wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(), work_dir=str(work), python=sys.executable, steps={})
    base_python = sys.executable
    receipt["steps"]["venv"] = run([base_python, "-m", "venv", str(venv)], dict(os.environ), work)
    py = venv / "bin" / "python"
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PGM_NATIVE_CACHE")}
    env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    receipt["steps"]["pip_install"] = run([str(py), "-m", "pip", "install", "-q", str(wheel)], env, work, timeout=1200)
    probe = ("import json, sys, pgm, pgm.api, pgm.switchboard, pgm.backends.worker, pgm.algorithms.structural.core, pgm.algorithms.block.integrated, pgm.algorithms.quotient.unified_pac_planner, pgm.algorithms.response.spectral_heatbath_run, pgm.runtime.supervise;"
             "mods={m: (getattr(sys.modules[m], '__file__', None) or '') for m in sys.modules if m.startswith('pgm')};"
             "print(json.dumps(dict(version=pgm.__version__, all_from_site_packages=all('site-packages' in f for f in mods.values() if f), n=len(mods), outside=[f for f in mods.values() if f and 'site-packages' not in f], sys_path=sys.path)))")
    receipt["steps"]["module_origins"] = run([str(py), "-I", "-c", probe], env, work)
    receipt["steps"]["capabilities"] = run([str(py), "-I", "-m", "pgm", "--capabilities"], env, work)
    for pol in ("accepted", "experimental"):
        r = run([str(py), "-I", "-m", "pgm", "--input", "fixtures/pos4.uai", "--output", "out_%s.json" % pol, "--budget", "30", "--memory-mib", "2048", "--seed", "1", "--epsilon", "1/200", "--delta", "1/1000000", "--policy", pol], env, work, timeout=200)
        try:
            res = json.loads((work / ("out_%s.json" % pol)).read_text()); r["result"] = dict(outcome=res["outcome"], guarantee=res["guarantee"], published=res["published"], K=res["K"], policy=res["policy"], policy_version=res["policy_version"], attempts=[(a["backend"], a["outcome"]) for a in res["attempts"]])
        except Exception as e: r["result"] = repr(e)
        receipt["steps"]["cli_" + pol] = r
    worker_cases = [("structural", "asym2.uai", []), ("block", "cyc3_card3.uai", []), ("quotient", "cyc3_card3.uai", ["--mode", "deterministic", "--delta", "0"]), ("response", "pos4.uai", [])]
    for backend, model, extra in worker_cases:
        out = work / ("w_%s.json" % backend)
        r = run([str(py), "-I", "-c", "import time; print(repr(time.monotonic()+25))"], env, work)
        deadline = r["stdout_tail"].strip()
        r = run([str(py), "-I", "-m", "pgm.backends.worker", "--backend", backend, "--input", "fixtures/" + model, "--output", str(out), "--deadline", deadline, "--memory-mib", "1024", *extra], env, work, timeout=120)
        try:
            res = json.loads(out.read_text()); r["result"] = dict(outcome=res["outcome"], guarantee=res["guarantee"], published=res["published"], K=res["K"], route=(res.get("mechanism") or {}).get("route"))
        except Exception as e: r["result"] = repr(e)
        receipt["steps"]["worker_" + backend] = r
    spec = ("import json; from pgm.specialists import cbi, sf, h4a, cqr, _bridge; out={};"
            "api, model = cbi.modules(); out['cbi']=dict(solve=callable(api.solve), verify=callable(api.verify), origin=api.__file__);"
            "core, routes, check = sf.modules(); out['sf']=dict(law=hasattr(core,'Law'), origin=core.__file__);"
            "out['h4a']=h4a.available();"
            "\ntry:\n    cqr.load_task('fixtures/asym2.uai'); out['cqr']='LOADED'\nexcept _bridge.SpecialistUnavailable as e:\n    out['cqr']=dict(kind=e.kind, reason=str(e))\n"
            "out['bridge_code_root']=str(_bridge.code_root()); print(json.dumps(out))")
    receipt["steps"]["specialists"] = run([str(py), "-I", "-c", spec], env, work)
    cache = work / "alt_cache"
    r = run([str(py), "-I", "-c", "import os, pgm.runtime.resources as R, pgm.algorithms.structural.cex_executor as CX; print(R.native_cache_dir(os.path.dirname(CX.__file__)))"], dict(env, PGM_NATIVE_CACHE=str(cache)), work)
    receipt["steps"]["native_cache_override"] = r
    site = run([str(py), "-I", "-c", "import pgm.algorithms.structural.cex_executor as CX, pgm.algorithms.structural.stream_float as SF, pgm.algorithms.response.heatbath_native as HN, json, os; print(json.dumps(dict(cex_lib=str(CX.LIB), cex_lib_exists=os.path.exists(CX.LIB), cex_record=str(CX.RECORD), stream_lib=str(SF.LIB), stream_lib_exists=os.path.exists(SF.LIB), heat_record=str(HN.RECORD), heat_record_exists=os.path.exists(HN.RECORD))))"], env, work)
    receipt["steps"]["native_build_locations"] = site
    ok = (receipt["steps"]["pip_install"]["returncode"] == 0 and receipt["steps"]["module_origins"]["returncode"] == 0 and '"all_from_site_packages": true' in receipt["steps"]["module_origins"]["stdout_tail"]
          and all(receipt["steps"]["cli_" + p]["returncode"] == 0 and isinstance(receipt["steps"]["cli_" + p]["result"], dict) and receipt["steps"]["cli_" + p]["result"]["outcome"] == "COMPLETE" for p in ("accepted", "experimental"))
          and all(isinstance(receipt["steps"]["worker_" + b]["result"], dict) for b, _, _ in worker_cases) and receipt["steps"]["specialists"]["returncode"] == 0)
    receipt["verdict"] = "PASS" if ok else "FAIL"
    (out_dir / "clean_wheel_relocation.json").write_text(json.dumps(receipt, indent=1) + "\n")
    print("clean wheel relocation:", receipt["verdict"]); print(json.dumps({k: (v.get("result") or v["returncode"]) for k, v in receipt["steps"].items()}, default=str)[:1500])
    shutil.rmtree(venv, ignore_errors=True)


if __name__ == "__main__": main()
