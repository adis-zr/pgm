"""Evidence package of the AGGREGATE_DP_2026-11-07 campaign: a reproducible zip with the implementation and checker source at the
exact pin, the frozen manifest and configs, every ledger, scores, records, report, per-cell artifacts (cell.json, certificate.json,
checker*.json, intervals.json, output.MAR, point_check*.json, logs), the qualification receipts and the packet-control replays.
Excluded (hash-listed in EXCLUDED_FROM_PACKAGE.json): nothing of evidential value; large duplicated plan JSONs of the MDI arm's
own records are kept. The archive is tested after writing (every member re-read; sha256 of the zip recorded).
    python adp/closeout/package.py D OUT.zip"""
import os, sys, json, hashlib, zipfile, subprocess, time
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(D, out):
    man = json.load(open(os.path.join(D, "CAMPAIGN_MANIFEST.json")))
    src = sorted(os.path.join("adp", f) for f in os.listdir(os.path.join(HERE, "adp")) if f.endswith(".py")) + sorted(os.path.join("adp", "closeout", f) for f in os.listdir(os.path.join(HERE, "adp", "closeout")) if f.endswith(".py")) + ["tests/test_adp_v1.py", "bench/cells.py", "bench/charge.py", "bench/libdai/libdai_mar.cpp", "ext/uai.py", "ext/supervise.py"] + sorted("mdi/" + f for f in os.listdir(os.path.join(HERE, "mdi")) if f.endswith(".py"))
    lineage = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE).decode().strip(), "branch": subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=HERE).decode().strip(), "manifest_commit": man["commit"], "code_hash": man["code_hash"], "source_files_sha256": {f: sha(os.path.join(HERE, f)) for f in src}}
    json.dump(lineage, open(os.path.join(D, "SOURCE_LINEAGE.json"), "w"), indent=1)
    excluded = []; included = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in src:
            z.write(os.path.join(HERE, f), "code/" + f); included.append("code/" + f)
        for root, dirs, files in os.walk(D):
            for fn in files:
                p = os.path.join(root, fn); rel = os.path.relpath(p, D)
                if fn.endswith(".tmp") or fn == os.path.basename(out):
                    continue
                if os.path.getsize(p) > 64 * (1 << 20):
                    excluded.append({"path": rel, "bytes": os.path.getsize(p), "sha256": sha(p), "reason": "over 64 MiB"}); continue
                z.write(p, "AGGREGATE_DP_2026-11-07/" + rel); included.append("AGGREGATE_DP_2026-11-07/" + rel)
    json.dump({"excluded": excluded, "included_count": len(included)}, open(os.path.join(D, "EXCLUDED_FROM_PACKAGE.json"), "w"), indent=1)
    # archive test: every member readable, CRC ok
    with zipfile.ZipFile(out) as z:
        bad = z.testzip(); n = len(z.namelist())
    rec = {"zip": out, "bytes": os.path.getsize(out), "sha256": sha(out), "members": n, "testzip_first_bad": bad, "excluded": len(excluded), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    json.dump(rec, open(os.path.join(D, "PACKAGE_RECORD.json"), "w"), indent=1); print(json.dumps(rec))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
