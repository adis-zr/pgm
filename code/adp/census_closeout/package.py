"""Census evidence package: source at the ACTUAL final pin (adp/, adp/census/, adp/census_closeout/, tests, bench/cells.py, ext, mdi) plus the run
directory. The archive's own SHA256 / CRC receipt is written OUTSIDE the archive (PACKAGE_RECORD.json next to the zip and in the run
directory), never inside it.
    python -m adp.census_closeout.package D OUT.zip"""
import os, sys, json, hashlib, zipfile, subprocess, time, zlib
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(D, out):
    src = sorted(os.path.join("adp", f) for f in os.listdir(os.path.join(HERE, "adp")) if f.endswith(".py")) + sorted(os.path.join("adp", "census", f) for f in os.listdir(os.path.join(HERE, "adp", "census")) if f.endswith(".py")) + sorted(os.path.join("adp", "census_closeout", f) for f in os.listdir(os.path.join(HERE, "adp", "census_closeout")) if f.endswith(".py")) + sorted(os.path.join("adp", "closeout", f) for f in os.listdir(os.path.join(HERE, "adp", "closeout")) if f.endswith(".py")) + ["tests/test_adp_v1.py", "tests/test_adp_census.py", "tests/test_adp_census_correction.py", "bench/cells.py", "bench/charge.py", "ext/uai.py", "ext/supervise.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    lineage = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(lineage, open(os.path.join(D, "SOURCE_LINEAGE.json"), "w"), indent=1)
    members = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src:
            z.write(os.path.join(HERE, f), "code/" + f); members += 1
        for root, dirs, files in os.walk(D):
            for fn in files:
                p = os.path.join(root, fn)
                if fn.endswith(".tmp") or fn == "PACKAGE_RECORD.json":
                    continue
                z.write(p, "AGGREGATE_DP_CENSUS_2026-11-08/" + os.path.relpath(p, D)); members += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); crcs = {i.filename: i.CRC for i in z.infolist()}
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": members, "testzip_first_bad": bad, "crc32_of_member_crc_table": "%08x" % (zlib.crc32(json.dumps(sorted(crcs.items())).encode()) & 0xffffffff), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": "this record is written OUTSIDE the archive (it would otherwise purport to hash itself)"}
    json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD.json"), "w"), indent=1); json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
