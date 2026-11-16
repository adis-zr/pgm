"""Pass orchestrator: `candidates` (the <= 8 evaluations in frozen order; a second mask identical to the first on an input
is NOT recomputed and the fact is recorded), `seal` (hashes of every candidate artifact BEFORE any reference), `references`
(<= 4 dense exact-reference cells, one per lambda, through the pinned mdi.launch --cell baseline child; 600 s / 8 GiB each),
`score` (exact D = Z - R in original units after scale reconciliation; U/D; true delta vs rho; containment of the true
marginals in the published intervals). Every launch goes through nd/supervised.py (one allowance ledger)."""
import sys, os, json, time, hashlib, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
E = os.path.join(HERE, "runs/mdi_2026-10-28/ND_CERTIFICATE_2026-11-05")
PY = sys.executable
LAMBDAS = ["1e-6", "1e-4", "1e-2", "1"]
GAPS = ["G100", "G10000"]
CAND_DEADLINE_S = 200.0; CAND_RETAINED_WALL_S = 180.0; REF_DEADLINE_S = 600.0; MEM = 8 * (1 << 30)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def sup(kind, label, deadline, receipt, log, cmd):
    r = subprocess.run([PY, os.path.join(HERE, "nd/supervised.py"), os.path.join(E, "ALLOWANCE_LEDGER.json"), kind, label, "%.1f" % deadline, str(MEM), receipt, log, "--"] + cmd, cwd=HERE, capture_output=True, text=True)
    print(r.stdout.strip()); sys.stdout.flush()
    return r.returncode, r.stdout


def candidates():
    from fractions import Fraction as Fr
    from mdi import model as M
    from nd import masks as MK
    out = {"order": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    for lam in LAMBDAS:
        mp = os.path.join(E, "inputs/Promedus_12_L%s.uai" % lam); ep = mp + ".evid"
        m = M.read_uai(mp); ev = M.read_evidence(ep, m); occ, sc = MK.restricted_occurrences(m, ev)
        digests = {g: MK.mask_digest(MK.apply_masks(occ, MK.GAPS[g])) for g in GAPS}
        for g in GAPS:
            label = "L%s_%s" % (lam, g); d = os.path.join(E, "candidates", label); os.makedirs(d, exist_ok=False)
            row = {"label": label, "lambda": lam, "gap": g, "mask_digest": digests[g]}
            prior = [x for x in out["order"] if x["lambda"] == lam and x.get("mask_digest") == digests[g] and x.get("launched")]
            if prior:
                row.update({"launched": False, "identical_mask_to": prior[0]["label"], "note": "both masks identical on this input: computed once"})
                json.dump(row, open(os.path.join(d, "IDENTICAL_MASK.json"), "w"), indent=1)
            else:
                rc, so = sup("candidate", label, CAND_DEADLINE_S, os.path.join(d, "supervisor_receipt.json"), os.path.join(d, "supervisor.log"),
                             [PY, os.path.join(HERE, "nd/run_candidate.py"), mp, ep, g, d, "%.1f" % CAND_RETAINED_WALL_S, str(MEM)])
                row.update({"launched": True, "launcher_rc": rc})
            out["order"].append(row)
            json.dump(out, open(os.path.join(E, "CANDIDATES_RUN.json"), "w"), indent=1)
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S"); json.dump(out, open(os.path.join(E, "CANDIDATES_RUN.json"), "w"), indent=1)


def seal():
    rows = {}
    for root, _, files in os.walk(os.path.join(E, "candidates")):
        for f in sorted(files):
            p = os.path.join(root, f); rows[os.path.relpath(p, E)] = sha(p)
    rows["CANDIDATES_RUN.json"] = sha(os.path.join(E, "CANDIDATES_RUN.json"))
    seal_ = {"sealed": time.strftime("%Y-%m-%d %H:%M:%S %z"), "files": len(rows), "sha256": rows, "note": "every candidate artifact hashed BEFORE any dense reference cell was launched; references may explain, never tune"}
    json.dump(seal_, open(os.path.join(E, "CANDIDATES_SEAL.json"), "w"), indent=1)
    print("sealed", len(rows), "files")


def references():
    out = {"order": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    for lam in LAMBDAS:
        prob = "Promedus_12_L%s" % lam; d = os.path.join(E, "references", prob, "attempt_1"); os.makedirs(d, exist_ok=False)
        rc, so = sup("reference", "ref_" + prob, REF_DEADLINE_S, os.path.join(E, "references", prob, "supervisor_receipt.json"), os.path.join(d, "supervisor.log"),
                     [PY, "-m", "mdi.launch", "--cell", prob, "baseline", d, "%.3f" % REF_DEADLINE_S, os.path.join(E, "inputs")])
        out["order"].append({"problem": prob, "launcher_rc": rc, "attempt_dir": os.path.relpath(d, E)})
        json.dump(out, open(os.path.join(E, "REFERENCES_RUN.json"), "w"), indent=1)
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S"); json.dump(out, open(os.path.join(E, "REFERENCES_RUN.json"), "w"), indent=1)


if __name__ == "__main__":
    {"candidates": candidates, "seal": seal, "references": references}[sys.argv[1]]()
