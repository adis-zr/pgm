"""Reference jobs (spec section 8): after all primary cells are terminal. Order: tiny ASIA / conversion controls first, then the smallest
selected case in each UAI family lacking a qualified (R0/R1) reference, in the spec's family order; each job capped at 300 s and charged to the
reference scope; unfinished -> quality UNKNOWN. Writes references/<case>.R0.json and REFERENCE_LEDGER.jsonl.
    python bench/references.py SWEEP_DIR [ALLOWANCE_S]"""
import os, sys, json, time, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
PY = os.path.join(HERE, ".venv", "bin", "python"); FAMILIES = ["GridBN", "Grids", "Pedigree", "Promedus", "CSP", "DBN", "ObjectDetection", "Segmentation", "Protein"]
CAP_S = 300.0


def main(S, allowance):
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    rows = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]
    have_r1 = {r["case"] for r in rows if r["arm"] == "EXACT" and r["status"] == "COMPLETE" and not r.get("censored")}
    os.makedirs(os.path.join(S, "references"), exist_ok=True); lp = os.path.join(S, "REFERENCE_LEDGER.jsonl"); spent = sum(json.loads(l)["wall_s"] for l in open(lp)) if os.path.exists(lp) else 0.0
    plan = [("control", "ASIA")]
    cases = {c["case"]: c for c in man["cells"]}
    for fam in FAMILIES:
        cand = sorted([c for c in inv.values() if c["family"] == fam and c["case"] in cases and c["case"] not in have_r1], key=lambda c: c["structure"]["table_entries_total"])
        if cand:
            plan.append(("family_smallest_missing", cand[0]["case"]))
    for kind, case in plan:
        outp = os.path.join(S, "references", case + ".R0.json")
        if os.path.exists(outp):
            continue
        if spent + CAP_S > allowance:
            open(lp, "a").write(json.dumps({"case": case, "kind": kind, "outcome": "NOT_RUN_BUDGET", "wall_s": 0.0}) + "\n"); continue
        row = inv[case]; mp = os.path.join(S, row.get("committed_model_path", row["model_path"])); ep = os.path.join(S, row.get("committed_evidence_path", row["evidence_path"]))
        cmd = [PY, os.path.join(HERE, "bench", "charge.py"), "--ledger", lp, "--scope", "reference", "--job", "ref_R0_" + case, "--timeout", str(CAP_S), "--mem-gib", "8", "--", PY, os.path.join(HERE, "bench", "ref_exact.py"), mp, ep, outp, str(1 << 22)]
        t0 = time.monotonic(); subprocess.run(cmd, cwd=HERE); w = time.monotonic() - t0; spent += w
        st = json.load(open(outp))["status"] if os.path.exists(outp) else "TIMEOUT_OR_KILLED"
        print("%-24s %-26s %-18s %6.1fs" % (case, kind, st, w), flush=True)
    print("reference jobs done; spent %.1f of %.1f s" % (spent, allowance))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 2400.0)
