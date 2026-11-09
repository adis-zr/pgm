"""GENERAL_BIDI_V1 review archive: implementation + qualification source at the frozen pin (gbidi/, tests, closeout tools, the imports closure:
adp/, mdi/, ext/, bench/cells.py + charge.py, bidi/oracle.py, the exact frozen ADP config, the libDAI binary), the run directory (manifest(s),
configs, ledgers, every cell directory, qualification receipts, synthetic cells, panel inspection, attempt-1 aborted cells, amendments, report,
handoff), the four theory/brief packet files, raw inputs. Integrity record OUTSIDE the archive; the packaging job's supervisory RECEIPT lives in
GB_LEDGER.jsonl and is copied as a sidecar by the caller.    python -m gbidi_closeout.package D OUT.zip"""
from __future__ import annotations
import os, sys, json, hashlib, zipfile, subprocess, time, zlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(D, out):
    man = json.load(open(os.path.join(D, "GB_MANIFEST.json")))
    src = set(man["source_files_sha256"]) | {"gbidi/BUILD_RECORD.json", man["kernel_binary"]} | {"gbidi_closeout/" + f for f in os.listdir(os.path.join(HERE, "gbidi_closeout")) if f.endswith(".py")} | {"tests/test_adp_v1.py", "tests/test_adp_census.py", "tests/test_adp_census_correction.py", "tests/test_bidi_pilot.py"}
    for d in ("adp", "adp/census", "adp/census_closeout", "adp/closeout", "mdi", "bidi", "bidi_closeout", "ext", "gbidi"):
        src |= {d + "/" + f for f in os.listdir(os.path.join(HERE, d)) if f.endswith((".py", ".cpp"))}
    src |= {"bench/cells.py", "bench/charge.py", "bench/libdai/libdai_mar", man["config_adp_repaired_path"]}
    src = sorted(f for f in src if os.path.exists(os.path.join(HERE, f)))
    changed = sorted(f for f, h in man["source_files_sha256"].items() if sha(os.path.join(HERE, f)) != h)
    lineage = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "frozen_commit": man["commit"], "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}, "frozen_files_changed_since_freeze": changed,
               "kernel_binary_sha256": sha(os.path.join(HERE, man["kernel_binary"])), "kernel_binary_equals_frozen": sha(os.path.join(HERE, man["kernel_binary"])) == man["kernel_binary_sha256"], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "dependencies": {"python": sys.version.split()[0], "compiler": man["kernel_build"]["compiler_version"].split("\n")[0], "compiler_executable_sha256": man["kernel_build"].get("compiler_executable_sha256"), "flags": man["kernel_build"]["flags"], "linked_libraries_sha256": man["kernel_build"].get("linked_libraries_sha256")}}
    try:
        import gmpy2, numpy, psutil
        lineage["dependencies"].update({"gmpy2": gmpy2.version(), "mpfr_python": gmpy2.mpfr_version(), "numpy": numpy.__version__, "psutil": psutil.__version__})
    except Exception:
        pass
    json.dump(lineage, open(os.path.join(D, "SOURCE_LINEAGE.json"), "w"), indent=1)
    members = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src:
            z.write(os.path.join(HERE, f), "code/" + f); members += 1
        for root, dirs, files in os.walk(D):
            for fn in files:
                p = os.path.join(root, fn)
                if fn.endswith(".tmp") or fn.startswith("PACKAGE_RECORD"):
                    continue
                z.write(p, "GENERAL_BIDI_V1_2026-11-09/" + os.path.relpath(p, D)); members += 1
        for c in man["cases"].values():
            for key in ("model_path", "evidence_path"):
                z.write(os.path.join(HERE, c[key]), "inputs/" + os.path.basename(c[key])); members += 1
        ref = os.path.expanduser("~/Workspace/pgm_ref/GENERAL_BIDIRECTIONAL_THEORY_AND_CLAUDE_BRIEF_2026-11-09/GENERAL_BIDIRECTIONAL_THEORY_AND_CLAUDE_BRIEF_2026-11-09")
        for fn in ("CLAUDE_IMPLEMENTATION_AND_BROAD_TEST_PROMPT.txt", "PROVEN_STATEMENTS_AND_BOUNDARIES.txt", "planner_execution.txt", "numerics_and_validation.txt", "empirical_plan.txt", "MANIFEST.json"):
            if os.path.exists(os.path.join(ref, fn)):
                z.write(os.path.join(ref, fn), "brief_packet/" + fn); members += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); crcs = {i.filename: i.CRC for i in z.infolist()}
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": members, "testzip_first_bad": bad, "crc32_of_member_crc_table": "%08x" % (zlib.crc32(json.dumps(sorted(crcs.items())).encode()) & 0xffffffff), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": "archive INTEGRITY record written OUTSIDE the archive; NOT the supervisory job receipt (that is in GB_LEDGER.jsonl and the sidecar <zip>.PACKAGE_JOB_RECEIPT.json)"}
    json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD_%s.json" % os.path.basename(out).replace(".zip", "")), "w"), indent=1); json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
