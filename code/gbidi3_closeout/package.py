"""Package the GENERAL_BIDI_COMPLETE_V3 READY_FOR_REVIEW deliverable: one self-contained archive (source of gbidi3 / gbidi3_closeout / the V3 test suite /
the unchanged supervisor / the pinned modules the implementation imports, the kernel source AND the platform binary with its BUILD_RECORD, the complete
run directory incl. ledger, qualification outputs, repairs, inspection, proposed manifest, the received brief), an integrity record written OUTSIDE the
archive (sha256, bytes, member count, central-directory and member tests), and -- because the packaging job's own receipt lands after the archive is
built -- a supervisory receipt sidecar written by the caller (gbidi.supervise) next to the zip.
    python -m gbidi3_closeout.package RUN_DIR OUT.zip"""
from __future__ import annotations
import os, sys, json, time, hashlib, zipfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_TREES = ["gbidi3", "gbidi3_closeout"]
# the COMPLETE import closure of the production entry points (gbidi3.cell / pilot / arm_adapter / verify / reconcile / inspect_panel / closeout), the comparator
# producers (adp.cell, bench.cells -> bench/libdai/libdai_mar), and of EVERY test module run in qualification (V3 controls, repair controls, the 236 regressions),
# with the pinned binaries, build records and frozen configurations they read (review G1). Computed by `closure()` in a fresh interpreter, never by hand.
ENTRY_MODULES = ["gbidi3.cell", "gbidi3.pilot", "gbidi3.arm_adapter", "gbidi3.verify", "gbidi3.reconcile", "gbidi3.inspect_panel", "gbidi3.demand", "gbidi3.identity", "gbidi3.requirements", "gbidi3.build", "gbidi3_closeout.ready_for_review", "gbidi3_closeout.report", "gbidi3_closeout.package", "gbidi.supervise", "adp.cell", "bench.cells", "adp.census.run", "adp.census.supervise"]
TEST_FILES = ["tests/test_gbidi3_complete.py", "tests/test_gbidi3_repair_2026_11_10.py", "tests/test_adp_v1.py", "tests/test_adp_census.py", "tests/test_adp_census_correction.py", "tests/test_bidi_pilot.py", "tests/test_gbidi_v2.py"]
BINARIES_AND_RECORDS = ["gbidi3/libgbidi3_kernel.dylib", "gbidi3/BUILD_RECORD.json", "gbidi/libgbidi_kernel.dylib", "gbidi/BUILD_RECORD.json", "bidi/libbidi_kernel.dylib", "bidi/BUILD_RECORD.json", "bench/libdai/libdai_mar", "bench/libdai/libdai_mar.cpp",
                        "runs/mdi_2026-10-28/AGGREGATE_DP_CENSUS_2026-11-08/CONFIG_new_arm.json", "runs/mdi_2026-10-28/AGGREGATE_DP_CENSUS_2026-11-08/CENSUS_MANIFEST.json", "runs/mdi_2026-10-28/AGGREGATE_DP_2026-11-07/SCORES.json", "README.md"]
SRC_FILES = TEST_FILES + BINARIES_AND_RECORDS


def closure():
    """every repository .py file imported when the entry modules and the test modules are imported in a FRESH interpreter AND the dynamic / provenance
    dependencies reached at run time (second review G1): adp.census.run.frozen_set_hash() -> adp.campaign.code_hash() and EVERY file that hash covers
    (adp/*.py, bench/cells.py, libdai, ext/uai.py, ext/supervise.py, mdi/*.py), plus gbidi3.pilot.source_set() (the lineage set)"""
    code = ("import sys, os, importlib, json; HERE=%r; sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'tests')); sys.set_int_max_str_digits(0)\n"
            "for m in %r + [os.path.splitext(os.path.basename(t))[0] for t in %r]:\n    importlib.import_module(m)\n"
            "from adp.census import run as CR; from gbidi3 import pilot as PI; h, per = CR.frozen_set_hash(); extra = [f for f in per if f != 'merlin'] + PI.source_set()\n"
            "print(json.dumps(sorted(set(os.path.relpath(m.__file__, HERE) for m in list(sys.modules.values()) if getattr(m, '__file__', None) and m.__file__.startswith(HERE + os.sep) and '.venv' not in m.__file__) | set(extra))))") % (HERE, ENTRY_MODULES, TEST_FILES)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), timeout=600)
    if r.returncode != 0:
        raise SystemExit("import closure failed: " + r.stderr[-2000:])
    return [f for f in json.loads(r.stdout.strip().splitlines()[-1]) if not f.startswith("tests/")]


def extraction_smoke(zip_path, tmp):
    """clean-extraction smoke (review G2): unzip to a fresh directory; import the entry modules and `pytest --collect-only` every packaged test file from the EXTRACTED tree (PYTHONPATH = extracted code)"""
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    code_dir = os.path.join(tmp, "code"); env = dict(os.environ, PYTHONPATH=code_dir)
    imp = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); sys.set_int_max_str_digits(0)\n" % code_dir + "\n".join("import %s" % m for m in ENTRY_MODULES) + "\nfrom gbidi3 import executor as EX; L = EX.Lib.get(); print('kernel', L.gb3_schedule_id().decode())\nfrom adp.census import run as CR; print('frozen_set_hash', CR.frozen_set_hash()[0])"], capture_output=True, text=True, cwd=code_dir, env=env, timeout=600)
    from adp.census import run as CR0; here_hash = CR0.frozen_set_hash()[0]; ext_hash = (imp.stdout.strip().splitlines()[-1].split()[-1] if imp.returncode == 0 and "frozen_set_hash" in imp.stdout else None)
    col = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"] + TEST_FILES, capture_output=True, text=True, cwd=code_dir, env=env, timeout=600)
    n = sum(1 for l in col.stdout.splitlines() if "::" in l)
    return {"extracted_to": tmp, "imports_ok": imp.returncode == 0, "imports_stdout": imp.stdout.strip()[-300:], "imports_stderr": imp.stderr.strip()[-600:], "collect_ok": col.returncode == 0, "collected": n, "collect_tail": col.stdout.strip().splitlines()[-1] if col.stdout.strip() else None, "collect_stderr": col.stderr.strip()[-600:], "frozen_set_hash_on_extract": ext_hash, "frozen_set_hash_in_repo": here_hash, "frozen_set_hash_matches": ext_hash == here_hash}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(D, out):
    D = os.path.abspath(D); out = os.path.abspath(out); n = 0; manifest = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        def add(path, arc):
            nonlocal n
            z.write(path, arc); manifest.append({"path": arc, "sha256": sha(path), "bytes": os.path.getsize(path)}); n += 1
        for t in SRC_TREES:
            for root, _, files in os.walk(os.path.join(HERE, t)):
                if "__pycache__" in root:
                    continue
                for f in sorted(files):
                    p = os.path.join(root, f); add(p, "code/" + os.path.relpath(p, HERE))
        clo = closure(); seen = set()
        for f in sorted(set(SRC_FILES) | set(clo)):
            p = os.path.join(HERE, f); arc = "code/" + f
            if os.path.exists(p) and arc not in {m["path"] for m in manifest} and arc not in seen:
                add(p, arc); seen.add(arc)
        review = os.path.join(os.path.dirname(HERE), "docs", "review-received-2026-11-10-general-bidi-complete-v3")
        if os.path.isdir(review):
            for root, _, files in os.walk(review):
                for f in sorted(files):
                    pth = os.path.join(root, f); add(pth, "docs/review-received-2026-11-10-general-bidi-complete-v3/" + os.path.relpath(pth, review))
        for root, _, files in os.walk(D):
            if "__pycache__" in root:
                continue
            for f in sorted(files):
                p = os.path.join(root, f); add(p, "code/" + os.path.relpath(p, HERE))
        z.writestr("PACKAGE_MANIFEST.json", json.dumps({"members": manifest, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1)); n += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); names = z.namelist()
    import tempfile
    smoke = extraction_smoke(out, tempfile.mkdtemp(prefix="gbidi3_pkg_smoke_"))
    prov = {"bench/libdai/libdai_mar": {"sha256": sha(os.path.join(HERE, "bench/libdai/libdai_mar")), "pinned_in": "runs/mdi_2026-10-28/AGGREGATE_DP_CENSUS_2026-11-08/CENSUS_MANIFEST.json", "pin_matches": sha(os.path.join(HERE, "bench/libdai/libdai_mar")) in open(os.path.join(HERE, "runs/mdi_2026-10-28/AGGREGATE_DP_CENSUS_2026-11-08/CENSUS_MANIFEST.json")).read(), "source": "bench/libdai/libdai_mar.cpp (libDAI JTREE MAR driver; third-party libDAI linked at build time, not vendored)"}}
    # lineage comparison AT PACKAGING (second review G2): every file named by CODE_LINEAGE must be in the archive with the SAME hash it had at closeout
    lin = json.load(open(os.path.join(D, "CODE_LINEAGE.json"))) if os.path.exists(os.path.join(D, "CODE_LINEAGE.json")) else {"files_sha256": {}}
    by_arc = {m["path"]: m["sha256"] for m in manifest}; lineage_check = {"missing_from_archive": [f for f in lin["files_sha256"] if "code/" + f not in by_arc], "hash_differs_since_closeout": [f for f in lin["files_sha256"] if "code/" + f in by_arc and by_arc["code/" + f] != lin["files_sha256"][f]]}
    lineage_check["consistent"] = not lineage_check["missing_from_archive"] and not lineage_check["hash_differs_since_closeout"]
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": n, "namelist": len(names), "testzip_first_bad": bad, "central_directory_readable": True, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "import_closure_files": clo, "clean_extraction_smoke": smoke, "binary_provenance": prov, "lineage_check": lineage_check, "note": "integrity record written OUTSIDE the archive; the packaging job's supervisory receipt is a separate sidecar (<zip>.PACKAGE_JOB_RECEIPT.json)"}
    json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD.json"), "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
