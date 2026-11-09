"""BIDI pilot review archive: implementation + qualification source at the frozen pin (bidi/, tests/test_bidi_pilot.py, the closeout tools,
and the reused adp/ext/mdi/bench sources the cells ran), the run directory (manifest, configs, ledgers, every cell directory with logs and
outputs, qualification receipts, synthetic cells, proofs, report, handoff), the theory addendum excerpt and the E-MDI-40 ledger excerpt.
The archive's INTEGRITY record (bytes, sha256, CRC table) is written OUTSIDE the archive; the packaging job's supervisory RECEIPT lives in
PILOT_LEDGER.jsonl and is copied as a sidecar <zip>.PACKAGE_JOB_RECEIPT.json by the caller.
    python -m bidi_closeout.package D OUT.zip"""
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
    man = json.load(open(os.path.join(D, "PILOT_MANIFEST.json")))
    # review of 9 Nov 2026: include every module the shipped tests / closeout tools import (adp/oracle.py, adp/campaign.py, the whole adp/ and mdi/ packages),
    # the exact frozen ADP configuration, and the census extractors referenced by the regression suite
    extra = sorted("adp/" + f for f in os.listdir(os.path.join(HERE, "adp")) if f.endswith(".py")) + sorted("adp/census/" + f for f in os.listdir(os.path.join(HERE, "adp", "census")) if f.endswith(".py")) + sorted("adp/census_closeout/" + f for f in os.listdir(os.path.join(HERE, "adp", "census_closeout")) if f.endswith(".py")) + sorted("adp/closeout/" + f for f in os.listdir(os.path.join(HERE, "adp", "closeout")) if f.endswith(".py")) + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py")) + [man["config_adp_repaired_path"], "bench/charge.py", "ext/supervise.py", "ext/__init__.py", "bidi/__init__.py", "bidi_closeout/__init__.py"]
    src = sorted(set(list(man["source_files_sha256"]) + ["bidi/BUILD_RECORD.json", man["kernel_binary"]] + sorted("bidi_closeout/" + f for f in os.listdir(os.path.join(HERE, "bidi_closeout")) if f.endswith(".py")) + ["tests/test_adp_v1.py", "tests/test_adp_census.py", "tests/test_adp_census_correction.py"] + extra))
    src = [f for f in src if os.path.exists(os.path.join(HERE, f))]
    changed = sorted(f for f, h in man["source_files_sha256"].items() if sha(os.path.join(HERE, f)) != h)
    lineage = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "frozen_commit": man["commit"], "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src},
               "frozen_files_identical_to_manifest": not changed, "frozen_files_changed_since_freeze": changed, "note_on_changes": "the review REPAIR (commit af5c1485, amendment_1) changed these files AFTER the frozen matrix; the matrix was run on the frozen commit / frozen binary (preserved in review_2026-11-09/before/); the repaired binary's performance is UNMEASURED",
               "config_adp_repaired_sha256_matches_manifest": sha(os.path.join(HERE, man["config_adp_repaired_path"])) == man["config_adp_repaired_sha256"],
               "kernel_binary_sha256_now_repaired": sha(os.path.join(HERE, man["kernel_binary"])), "kernel_binary_sha256_frozen": man["kernel_binary_sha256"], "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "dependencies": {"python": sys.version.split()[0], "compiler": man["kernel_build"]["compiler_version"].split("\n")[0], "flags": man["kernel_build"]["flags"]}}
    try:
        import gmpy2, numpy, psutil
        lineage["dependencies"].update({"gmpy2": gmpy2.version(), "mpfr": gmpy2.mpfr_version(), "numpy": numpy.__version__, "psutil": psutil.__version__})
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
                z.write(p, "BIDI_NATIVE_PILOT_2026-11-09/" + os.path.relpath(p, D)); members += 1
        for c in man["cases"].values():
            for key in ("model_path", "evidence_path"):
                z.write(os.path.join(HERE, c[key]), "inputs/" + os.path.basename(c[key])); members += 1
        ref = os.path.expanduser("~/Workspace/pgm_ref/BIDIRECTIONAL_INFERENCE_THEORY_2026-11-09/BIDIRECTIONAL_INFERENCE_THEORY_2026-11-09")
        for fn in ("01_PROVEN_STATEMENTS_LEDGER.txt", "03_COMPLETE_DBN_SCHEDULE_AND_COST.txt", "05_INDEPENDENT_VALIDATION_AND_PRECISION.txt", "09_PRECISION_CROSSCHECK.txt", "PACKAGE_MANIFEST.txt"):
            if os.path.exists(os.path.join(ref, fn)):
                z.write(os.path.join(ref, fn), "theory_packet_excerpt/" + fn); members += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); crcs = {i.filename: i.CRC for i in z.infolist()}
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": members, "testzip_first_bad": bad, "crc32_of_member_crc_table": "%08x" % (zlib.crc32(json.dumps(sorted(crcs.items())).encode()) & 0xffffffff), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": "archive INTEGRITY record written OUTSIDE the archive; NOT the supervisory job receipt (that is in PILOT_LEDGER.jsonl and the sidecar <zip>.PACKAGE_JOB_RECEIPT.json)"}
    tag = os.path.basename(out).replace(".zip", ""); json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD_%s.json" % tag), "w"), indent=1); json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
