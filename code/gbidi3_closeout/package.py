"""Package the GENERAL_BIDI_COMPLETE_V3 READY_FOR_REVIEW deliverable: one self-contained archive (source of gbidi3 / gbidi3_closeout / the V3 test suite /
the unchanged supervisor / the pinned modules the implementation imports, the kernel source AND the platform binary with its BUILD_RECORD, the complete
run directory incl. ledger, qualification outputs, repairs, inspection, proposed manifest, the received brief), an integrity record written OUTSIDE the
archive (sha256, bytes, member count, central-directory and member tests), and -- because the packaging job's own receipt lands after the archive is
built -- a supervisory receipt sidecar written by the caller (gbidi.supervise) next to the zip.
    python -m gbidi3_closeout.package RUN_DIR OUT.zip"""
from __future__ import annotations
import os, sys, json, time, hashlib, zipfile
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_TREES = ["gbidi3", "gbidi3_closeout"]
SRC_FILES = ["tests/test_gbidi3_complete.py", "gbidi/supervise.py", "adp/source.py", "adp/publish.py", "adp/checker.py", "adp/cell.py", "adp/census/run.py", "adp/census/supervise.py", "ext/uai.py", "bench/cells.py", "README.md"]


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
        for f in SRC_FILES:
            p = os.path.join(HERE, f)
            if os.path.exists(p):
                add(p, "code/" + f)
        for root, _, files in os.walk(D):
            if "__pycache__" in root:
                continue
            for f in sorted(files):
                p = os.path.join(root, f); add(p, "code/" + os.path.relpath(p, HERE))
        z.writestr("PACKAGE_MANIFEST.json", json.dumps({"members": manifest, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=1)); n += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); names = z.namelist()
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": n, "namelist": len(names), "testzip_first_bad": bad, "central_directory_readable": True, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": "integrity record written OUTSIDE the archive; the packaging job's supervisory receipt is a separate sidecar (<zip>.PACKAGE_JOB_RECEIPT.json)"}
    json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD.json"), "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
