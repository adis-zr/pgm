"""Compact review package for the external sweep: manifest, inventory, selection, availability, ledgers, scores, report, every cell row and
cell.json, every produced output.MAR / intervals.json / adapter certificate / cbi_result.json (numerical evidence), reference files, the
46 inputs, source code of bench/ + cbi/ + tests, exclusion manifest with hashes for everything left out (raw archives, third-party software,
logs above 1 MB, MDI plan directories).    python bench/package.py SWEEP_DIR OUT.zip"""
import os, sys, json, hashlib, zipfile, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); R = os.path.dirname(HERE)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def main(S, Z):
    inc = []; exc = {}
    for root, dirs, files in os.walk(S):
        rel = os.path.relpath(root, S)
        if rel.startswith("sources") or rel.startswith("setup/emul"):
            for f in files:
                p = os.path.join(root, f); exc[os.path.relpath(p, R)] = {"sha256": sha(p), "bytes": os.path.getsize(p), "why": "raw archive / third-party software / scratch (hashes in SOURCES_HASHES.json)"}
            continue
        for f in files:
            p = os.path.join(root, f); size = os.path.getsize(p)
            if "plans_" in p or f.endswith(".tmp") or f == "core" or (f.endswith(".log") and size > 1_000_000) or f.endswith(".pdf"):
                exc[os.path.relpath(p, R)] = {"sha256": sha(p), "bytes": size, "why": "engine plan directory / oversized log / scratch / pdf"}; continue
            inc.append(p)
    code = subprocess.check_output(["git", "ls-files", "code/bench", "code/cbi", "code/tests/test_cbi_conformance.py", "code/tests/test_bench_adapters.py", "code/ext/uai.py"], cwd=R).decode().split()
    man = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=R).decode().strip(), "excluded": exc, "included_files": len(inc) + len(code)}
    json.dump(man, open(os.path.join(S, "EXCLUDED_FROM_REVIEW_PACKAGE.json"), "w"), indent=1); inc.append(os.path.join(S, "EXCLUDED_FROM_REVIEW_PACKAGE.json"))
    with zipfile.ZipFile(Z, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(set(inc)):
            z.write(p, os.path.relpath(p, R))
        for p in code:
            z.write(os.path.join(R, p), p)
        z.writestr("PACKAGE_INDEX.json", json.dumps({"start_here": ["code/runs/mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06/REPORT.md", ".../SCORES.json", ".../CELLS_LEDGER.jsonl", ".../BUDGET_LEDGER.json", ".../CAMPAIGN_MANIFEST.json", ".../AVAILABILITY.json"], "commit": man["commit"]}, indent=1))
    print("package", Z, "%.1f MB" % (os.path.getsize(Z) / 1e6), "files", len(set(inc)) + len(code) + 1, "excluded", len(exc), "sha256", sha(Z))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]))
