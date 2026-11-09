"""NARROW follow-up package for the second-review closeout: the supervisor repair (source, before-copy, diff), the ledger tool, the census
controls, the whole review_2026-11-08/ directory (corrected records, report, before/after lifecycle receipts, unchanged-hash verifications,
correction ledger), AMENDMENTS.json, HANDOFF.md and the E-MDI-39 excerpt. Not a regenerated full archive (the cells are byte-identical to the
r2_correction package, whose sha256 is named in the lineage). The archive's integrity record is written OUTSIDE the archive; the supervisory job
receipt of this packaging job lives in CORRECTION_LEDGER.jsonl (appended after this process exits) and is copied as a sidecar by the caller.
    python -m adp.census_closeout.package_followup D OUT.zip"""
import os, sys, json, hashlib, zipfile, subprocess, time, zlib
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(D, out):
    src = ["adp/census/supervise.py", "adp/census/run.py", "tests/test_adp_census.py", "tests/test_adp_census_correction.py", "adp/census_closeout/correct.py", "adp/census_closeout/report_corrected.py", "adp/census_closeout/package.py", "adp/census_closeout/package_followup.py"]
    prior = json.load(open(os.path.join(D, "PACKAGE_RECORD.json")))
    lineage = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src},
               "full_archive_with_identical_cells": {"zip": os.path.basename(prior["zip"]), "sha256": prior["sha256"], "bytes": prior["bytes"]}, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "scope": "narrow follow-up (second review): supervisor repair + controls + review directory; cells unchanged (see review_2026-11-08/UNCHANGED_VERIFICATION_after_boundary.json)"}
    json.dump(lineage, open(os.path.join(D, "review_2026-11-08", "FOLLOWUP_LINEAGE.json"), "w"), indent=1)
    members = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src:
            z.write(os.path.join(HERE, f), "code/" + f); members += 1
        for f in ("AMENDMENTS.json", "HANDOFF.md", "CENSUS_MANIFEST.json"):
            z.write(os.path.join(D, f), "AGGREGATE_DP_CENSUS_2026-11-08/" + f); members += 1
        R = os.path.join(D, "review_2026-11-08")
        for root, dirs, files in os.walk(R):
            for fn in files:
                if fn.endswith(".tmp") or fn.endswith(".pyc"):
                    continue
                p = os.path.join(root, fn); z.write(p, "AGGREGATE_DP_CENSUS_2026-11-08/review_2026-11-08/" + os.path.relpath(p, R)); members += 1
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); crcs = {i.filename: i.CRC for i in z.infolist()}
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": members, "testzip_first_bad": bad, "crc32_of_member_crc_table": "%08x" % (zlib.crc32(json.dumps(sorted(crcs.items())).encode()) & 0xffffffff), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "note": "archive INTEGRITY record written OUTSIDE the archive (it would otherwise purport to hash itself); it is NOT the supervisory job receipt -- that is in CORRECTION_LEDGER.jsonl and in the sidecar <zip>.PACKAGE_JOB_RECEIPT.json"}
    json.dump(rec, open(os.path.join(D, "review_2026-11-08", "FOLLOWUP_PACKAGE_RECORD.json"), "w"), indent=1); json.dump(rec, open(out + ".PACKAGE_RECORD.json", "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
