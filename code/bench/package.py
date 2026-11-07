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
    KEEP_SOURCES = ("sources/uai14/sol/", "sources/bnlearn/", "sources/bnlearn_uai/")          # official reference vectors, original BIF sources, conversion reports
    for root, dirs, files in os.walk(S):
        rel = os.path.relpath(root, S)
        if (rel.startswith("sources") and not any((rel + "/").startswith(k) for k in KEEP_SOURCES)) or rel.startswith("setup/emul"):
            for f in files:
                p = os.path.join(root, f); exc[os.path.relpath(p, R)] = {"sha256": sha(p), "bytes": os.path.getsize(p), "why": "raw archive / third-party software / scratch (hashes in SOURCES_HASHES.json)"}
            continue
        for f in files:
            p = os.path.join(root, f); size = os.path.getsize(p)
            if f.endswith(".tmp") or f == "core" or (f.endswith(".log") and size > 1_000_000) or f.endswith(".pdf"):
                exc[os.path.relpath(p, R)] = {"sha256": sha(p), "bytes": size, "why": "oversized log / scratch / pdf"}; continue
            inc.append(p)                                                      # MDI plan JSON directories are INCLUDED (review item 3)
    code = subprocess.check_output(["git", "ls-files", "code/bench", "code/cbi", "code/mdi", "code/tests/test_cbi_conformance.py", "code/tests/test_bench_adapters.py", "code/tests/test_mdi_selector_pilot.py", "code/tests/_pilot_control_child.py", "code/ext/uai.py", "code/ext/supervise.py",
                                    "code/runs/mdi_2026-10-28/GENERALIZATION_2026-11-03/COMPARISON_2026-11-04/pilot/PILOT_BUILD_PIN_676d090.json", "code/runs/mdi_2026-10-28/BUILD_PIN_6ce6977.json",
                                    "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY3_MANIFEST.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY3_LEDGER.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY3_SCORES.json",
                                    "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY4_MANIFEST.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY4_LEDGER.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY4_vs_REPLAY3.json",
                                    "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY5_MANIFEST.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY5_LEDGER.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/REPLAY5_vs_REPLAY4.json",
                                    "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/replay3", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/replay4", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/replay5",
                                    "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/repair_2026-11-06/counterexamples.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/MANIFEST.json", "code/runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06/inputs"], cwd=R).decode().split()
    code += ["code/bench/libdai/libdai_mar"] if os.path.exists(os.path.join(R, "code/bench/libdai/libdai_mar")) else []
    man = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=R).decode().strip(), "excluded": exc, "included_files": len(inc) + len(code),
           "included_code_and_pins_sha256": {p: sha(os.path.join(R, p)) for p in code if os.path.isfile(os.path.join(R, p))}}
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
