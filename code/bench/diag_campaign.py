"""DIAGNOSTIC CAMPAIGN (spec of 7 Nov 2026): freeze -> run families A..E -> ledgers. Separate from the primary campaign: its own manifest
(DIAG_MANIFEST.json), its own cell ledger (DIAG_CELLS_LEDGER.jsonl), unique directories under diag_2026-11-07/cells/<family>/, links to the
historical counterpart rows, NOT_RUN_BUDGET rows at a global stop. Every top-level job is a receipt in DIAG_LEDGER.jsonl (bench/charge.py) or a
supervised cell row (this runner is the receipt boundary for the cells it runs; the runner's own wall is NOT added again).
    python bench/diag_campaign.py freeze SWEEP_DIR
    python bench/diag_campaign.py run    SWEEP_DIR FAMILY        (A | B | C | D | E)
    python bench/diag_campaign.py status SWEEP_DIR"""
from __future__ import annotations
import os, sys, json, time, hashlib, subprocess, signal
import psutil
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bench import campaign as C
PY = C.PY; RUNNABLE = ["CBI_NATIVE", "MDI_EXISTING", "LBP", "WMB", "IJGP", "EXACT", "PGMAX_SUMPRODUCT_BP"]
CAPS = {"A": 6440.0, "B": 2760.0, "C": 6440.0, "D": 2280.0, "E": 240.0}
CELL_CAP = {"A": 20.0, "B": 30.0, "C": 20.0, "D": 120.0, "E": 120.0}
GRACE_S = 4.0; MEM_GIB = 8.0; INTERVAL = 0.05


def D(S):
    return os.path.join(S, "diag_2026-11-07")


def diag_code_hash():
    """the primary code hash extended by the diagnostic runners themselves (frozen and checked at every run)"""
    base, files = C.code_hash(); h = hashlib.sha256(base.encode())
    extra = ["bench/transform_probe.py", "bench/local_certificate_diag.py", "bench/diag_campaign.py", "bench/census.py"]
    for f in extra:
        h.update(f.encode()); h.update(C.sha_file(os.path.join(HERE, f)).encode())
    return h.hexdigest(), files + extra


def rows(S):
    p = os.path.join(D(S), "DIAG_CELLS_LEDGER.jsonl"); return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def freeze(S):
    man0 = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    sel = json.load(open(os.path.join(S, "PANEL_SELECTION.json"))); sc = json.load(open(os.path.join(S, "SCORES.json"))); hist = [json.loads(l) for l in open(os.path.join(S, "CELLS_LEDGER.jsonl"))]
    ch, files = diag_code_hash(); cfg = dict(man0["config"]); cfg_hash = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
    cases = sorted({c["case"] for c in man0["cells"]}, key=lambda x: (inv[x]["family"], x))
    from ext import uai as U
    def qvar(case):
        """the frozen single-query rule: unobserved original variable minimizing SHA256(case-content-hash | variable-id)"""
        r = inv[case]; m = U.read_model(os.path.join(S, r.get("committed_model_path", r["model_path"]))); ev = U.read_evidence(os.path.join(S, r.get("committed_evidence_path", r["evidence_path"])))
        free = [v for v in range(m.nvars) if v not in ev]
        return (min(free, key=lambda v: hashlib.sha256(("%s|%d" % (r["canonical_model_sha256"], v)).encode()).hexdigest()) if free else None), len(free), m.card
    lacking_r01 = sorted(c for c, v in sc["reference_classes"].items() if v["class"] not in ("R0", "R1"))
    admitted = sorted({r["case"] for r in hist if r["arm"] == "CBI_NATIVE" and r["status"] in ("VALID_BUT_TOO_WIDE", "CERTIFIED") and r.get("label") is None})
    man = {"frozen_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "commit": C.git_head(), "code_hash": ch, "config": cfg, "config_hash": cfg_hash, "primary_manifest_code_hash": man0["code_hash"],
           "population": {"intended_slots": 48, "accessible_cases": len(cases), "inaccessible": sel["shortfalls"], "runnable_arms": RUNNABLE, "unavailable_arms": ["SAMPLESEARCH"]},
           "eligibility": {"A": "every accessible case x every runnable arm", "B": "every accessible case x {quotient, support} (a no-op / inapplicable result is a recorded row)", "C": "every accessible case with >= 1 unobserved variable x every runnable arm; the variable by the SHA256 rule; CBI / MDI native single-query interface, other arms complete-MAR + extraction (labelled)",
                           "D": "every accessible case lacking an R0/R1 reference at freeze (%d cases: %s), EXACT arm at 120 s; a new success is R1, never R0" % (len(lacking_r01), lacking_r01), "E": "every case admitted by the verified CBI representation at freeze (%s): extraction from saved artifacts + bounded deterministic boundary contrasts (frozen: outside states all-0 / all-1 in native coordinates vs the saved modal state) at 120 s" % admitted},
           "caps_s": {"family": CAPS, "cell": CELL_CAP, "memory_gib": MEM_GIB, "grace_s": GRACE_S, "diagnostic_total_ceiling": 22000.0, "aggregate_ceiling_incl_campaign_and_repairs": 28800.0, "closeout_reserve": 1200.0, "static_per_case": 10.0},
           "order": "family-balanced rounds over the declared families (GridBN, Grids, Pedigree, Promedus, CSP, DBN, ObjectDetection, Segmentation, Protein, bnlearn); within a case the arm order rotates by SHA256(model|evidence) as in the primary campaign; A and C are paired per (case, arm, settings) and interleaved A-then-C per case",
           "seeds": {"PGMax": "deterministic BP (no RNG)", "libDAI": "SEQMAX schedule (deterministic)", "Merlin": "no seed option used; deterministic for wmb / ijgp", "MDI": "deterministic", "CBI": "deterministic"},
           "instrumentation": "bench/cells.py progress.json flush every 0.5 s; MDI native single query through mdi.pipeline.solve; transform probe bench/transform_probe.py; overhead measured on fixed controls (controls/INSTRUMENTATION_OVERHEAD.json)",
           "fresh_process_conditions": "one new Python process per cell (JAX / numba / numpy import and compile state NOT carried over; PGMax recompiles per process); filesystem caches warm (same machine, inputs read many times); dependency state reused (no reinstall); no system cache purge",
           "schedule_worst_case_s": {}, "cells": []}
    fams = {}
    for case in cases:
        fams.setdefault(inv[case]["family"], []).append(case)
    order = []
    while any(fams.values()):
        for fam in list(fams):
            if fams[fam]:
                order.append(fams[fam].pop(0))
    def hist_row(case, arm, stage):
        return next((r["cell_id"] for r in hist if r["case"] == case and r["arm"] == arm and r["stage"] == stage and r.get("label") is None), None)
    for case in order:
        row = inv[case]; mp = row.get("committed_model_path", row["model_path"]); ep = row.get("committed_evidence_path", row["evidence_path"])
        rot = int(hashlib.sha256((row["canonical_model_sha256"] + row["canonical_evidence_sha256"]).encode()).hexdigest(), 16) % len(RUNNABLE); arms = RUNNABLE[rot:] + RUNNABLE[:rot]
        v, nfree, card = qvar(case)
        base = {"case": case, "family": row["family"], "anchor": any(c.get("anchor") for c in man0["cells"] if c["case"] == case), "model_path": mp, "evidence_path": ep, "raw_model_sha256": row["raw_model_sha256"], "raw_evidence_sha256": row["raw_evidence_sha256"], "canonical_model_sha256": row["canonical_model_sha256"], "canonical_evidence_sha256": row["canonical_evidence_sha256"]}
        for arm in arms:
            for fam in ("A", "C"):
                if fam == "C" and v is None:
                    man["cells"].append({**base, "family_code": "C", "arm": arm, "cap_s": CELL_CAP["C"], "cell_id": None, "status_frozen": "NOT_APPLICABLE", "reason": "no unobserved variable"}); continue
                task = {"model": row["canonical_model_sha256"], "evidence": row["canonical_evidence_sha256"], "queries": ("all_unobserved" if fam == "A" else "var:%d" % v), "config": cfg_hash, "arm": arm, "budget_s": CELL_CAP[fam], "memory_gib": MEM_GIB, "grace_s": GRACE_S}
                tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch).encode()).hexdigest()[:16]
                man["cells"].append({**base, "family_code": fam, "arm": arm, "cap_s": CELL_CAP[fam], "task_id": tid, "cell_id": cid, "task": task, "single_query_var": (v if fam == "C" else None), "single_query_var_card": (card[v] if fam == "C" else None),
                                     "historical_counterpart": {"breadth": hist_row(case, arm, "breadth"), "depth": hist_row(case, arm, "depth")}, "pair": ("A|C|%s|%s" % (case, arm))})
        for mech in ("quotient", "support"):
            task = {"model": row["canonical_model_sha256"], "evidence": row["canonical_evidence_sha256"], "mechanism": mech, "cap_s": CELL_CAP["B"], "memory_gib": MEM_GIB, "config": cfg_hash}
            tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch).encode()).hexdigest()[:16]
            man["cells"].append({**base, "family_code": "B", "arm": "MDI_EXISTING", "mechanism": mech, "cap_s": CELL_CAP["B"], "task_id": tid, "cell_id": cid, "task": task, "historical_counterpart": {"breadth": hist_row(case, "MDI_EXISTING", "breadth"), "depth": hist_row(case, "MDI_EXISTING", "depth")}})
        if case in lacking_r01:
            task = {"model": row["canonical_model_sha256"], "evidence": row["canonical_evidence_sha256"], "queries": "all_unobserved", "config": cfg_hash, "arm": "EXACT", "budget_s": CELL_CAP["D"], "memory_gib": MEM_GIB, "grace_s": GRACE_S}
            tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch).encode()).hexdigest()[:16]
            man["cells"].append({**base, "family_code": "D", "arm": "EXACT", "cap_s": CELL_CAP["D"], "task_id": tid, "cell_id": cid, "task": task, "reference_class_at_freeze": sc["reference_classes"][case]["class"], "historical_counterpart": {"breadth": hist_row(case, "EXACT", "breadth"), "depth": hist_row(case, "EXACT", "depth")}})
        if case in admitted:
            task = {"model": row["canonical_model_sha256"], "evidence": row["canonical_evidence_sha256"], "diagnostic": "local_certificate_extraction_and_boundary_contrasts", "cap_s": CELL_CAP["E"], "config": cfg_hash}
            tid = hashlib.sha256(json.dumps(task, sort_keys=True).encode()).hexdigest()[:16]; cid = hashlib.sha256((tid + "|" + ch).encode()).hexdigest()[:16]
            man["cells"].append({**base, "family_code": "E", "arm": "CBI_NATIVE", "cap_s": CELL_CAP["E"], "task_id": tid, "cell_id": cid, "task": task, "historical_counterpart": {"breadth": hist_row(case, "CBI_NATIVE", "breadth"), "depth": hist_row(case, "CBI_NATIVE", "depth")}})
    for fam in CAPS:
        n = sum(1 for c in man["cells"] if c["family_code"] == fam and c.get("cell_id"))
        man["schedule_worst_case_s"][fam] = {"cells": n, "worst_case_s": n * (CELL_CAP[fam] + GRACE_S), "cap_s": CAPS[fam], "feasible_at_cap": n * (CELL_CAP[fam] + GRACE_S) <= CAPS[fam] or fam in ("A", "C", "B")}
    man["counts"] = {f: sum(1 for c in man["cells"] if c["family_code"] == f) for f in CAPS}
    mp = os.path.join(D(S), "DIAG_MANIFEST.json"); os.makedirs(D(S), exist_ok=True)
    assert not os.path.exists(mp), "DIAG_MANIFEST already frozen; refusing to overwrite"
    json.dump(man, open(mp, "w"), indent=1); print("diagnostic manifest frozen:", man["counts"], "worst case:", {f: round(v["worst_case_s"]) for f, v in man["schedule_worst_case_s"].items()}, "code", ch[:12])


def spent(S, fam):
    return sum(r["supervisor_wall_s"] for r in rows(S) if r["family_code"] == fam and r.get("outcome") not in ("NOT_RUN_BUDGET", "NOT_APPLICABLE"))


def run_one(S, cell, cfgp):
    fam = cell["family_code"]; out = os.path.join(D(S), "cells", fam, "%s__%s__%s%s" % (cell["case"], cell["arm"], cell.get("mechanism") or "", cell["cell_id"])); os.makedirs(out, exist_ok=True)
    mp, ep = os.path.join(S, cell["model_path"]), os.path.join(S, cell["evidence_path"])
    assert C.sha_file(mp) == cell["raw_model_sha256"] and C.sha_file(ep) == cell["raw_evidence_sha256"], "live input differs from the frozen binding"
    if fam == "B":
        cmd = [PY, os.path.join(HERE, "bench", "transform_probe.py"), cell["mechanism"], mp, ep, out, "%.1f" % cell["cap_s"]]
    elif fam == "E":
        cmd = [PY, os.path.join(HERE, "bench", "local_certificate_diag.py"), mp, ep, out, "%.1f" % cell["cap_s"], S]
    else:
        cmd = [PY, os.path.join(HERE, "bench", "cells.py"), cell["arm"], mp, ep, out, "%.1f" % cell["cap_s"], cfgp]
    env = dict(os.environ); env.update(C.THREAD_ENV); env["PYTHONPATH"] = HERE
    log = open(os.path.join(out, "supervisor.log"), "ab"); t0 = time.time(); m0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE, start_new_session=True); p = psutil.Process(proc.pid); peak = 0; outcome = "COMPLETED"; over = 0; samples = 0; cpu = None
    while proc.poll() is None:
        try:
            r_ = C.tree_rss(p); peak = max(peak, r_); samples += 1
            try:
                ct = p.cpu_times(); cpu = ct.user + ct.system + sum((c.cpu_times().user + c.cpu_times().system) for c in p.children(recursive=True))
            except psutil.Error:
                pass
        except psutil.Error:
            break
        if r_ > MEM_GIB * 2 ** 30:
            outcome = "MEMORY_KILL"; over = r_ - MEM_GIB * 2 ** 30; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        if time.monotonic() - m0 > cell["cap_s"] + GRACE_S:
            outcome = "TIMEOUT_KILL"; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        time.sleep(INTERVAL)
    wall = time.monotonic() - m0; log.close()
    recp = os.path.join(out, "cell.json" if fam not in ("B", "E") else ("probe.json" if fam == "B" else "local_diag.json")); rec = json.load(open(recp)) if os.path.exists(recp) else {}
    prog = json.load(open(os.path.join(out, "progress.json"))) if (not rec and os.path.exists(os.path.join(out, "progress.json"))) else None
    if outcome == "COMPLETED" and proc.returncode != 0:
        outcome = "NONZERO_EXIT"
    row = {**{k: cell.get(k) for k in ("cell_id", "task_id", "family_code", "case", "family", "arm", "mechanism", "cap_s", "anchor", "single_query_var", "historical_counterpart", "pair")}, "out_dir": os.path.relpath(out, S), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
           "supervisor_wall_s": wall, "cpu_s_sampled": cpu, "returncode": proc.returncode, "outcome": outcome, "peak_tree_rss_bytes": peak, "rss_samples": samples, "mem_overshoot_bytes": over, "code_hash": diag_code_hash()[0],
           "status": rec.get("status") if rec else ("KILLED_" + outcome if outcome in ("MEMORY_KILL", "TIMEOUT_KILL") else "NO_RECORD"), "complete_response_s": rec.get("complete_response_s"), "censored": bool(rec.get("censored")) or outcome in ("MEMORY_KILL", "TIMEOUT_KILL"),
           "last_progress_before_kill": prog, "phases_s": rec.get("phases_s"), "reason": (str(rec.get("reason"))[:300] if rec.get("reason") is not None else None), "output_bytes": rec.get("output_bytes"), "t_first_complete_output_s": rec.get("t_first_complete_output_s")}
    with open(os.path.join(D(S), "DIAG_CELLS_LEDGER.jsonl"), "a") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row


def run(S, fam):
    man = json.load(open(os.path.join(D(S), "DIAG_MANIFEST.json"))); ch, _ = diag_code_hash(); assert ch == man["code_hash"], "code hash differs from the frozen diagnostic manifest"
    cfgp = os.path.join(D(S), "CONFIG_diag.json"); json.dump(man["config"], open(cfgp, "w"))
    done = {r["cell_id"] for r in rows(S) if r.get("cell_id")}; n = 0
    fams = ("A", "C") if fam == "AC" else (fam,)
    cells = [c for c in man["cells"] if c["family_code"] in fams]
    for c in cells:
        fam = c["family_code"]
        if c.get("status_frozen") == "NOT_APPLICABLE":
            if not any(r.get("case") == c["case"] and r.get("arm") == c["arm"] and r.get("family_code") == fam for r in rows(S)):
                open(os.path.join(D(S), "DIAG_CELLS_LEDGER.jsonl"), "a").write(json.dumps({**{k: c.get(k) for k in ("family_code", "case", "family", "arm", "cap_s")}, "cell_id": None, "outcome": "NOT_APPLICABLE", "status": "NOT_APPLICABLE", "supervisor_wall_s": 0.0, "reason": c["reason"]}) + "\n")
            continue
        if c["cell_id"] in done:
            continue
        if spent(S, fam) + c["cap_s"] + GRACE_S + 1.0 > CAPS[fam]:
            open(os.path.join(D(S), "DIAG_CELLS_LEDGER.jsonl"), "a").write(json.dumps({**{k: c.get(k) for k in ("cell_id", "task_id", "family_code", "case", "family", "arm", "mechanism", "cap_s")}, "outcome": "NOT_RUN_BUDGET", "status": "NOT_RUN_BUDGET", "supervisor_wall_s": 0.0, "reason": "family cap %.0f s reached (%.1f s spent)" % (CAPS[fam], spent(S, fam))}) + "\n"); continue
        cfg_cell = cfgp
        if fam == "C":
            cfg_cell = os.path.join(D(S), "CONFIG_diag_single_%s.json" % c["case"]); json.dump({**man["config"], "single_query_var": c["single_query_var"]}, open(cfg_cell, "w"))
        r = run_one(S, c, cfg_cell); n += 1
        print("%s %-20s %-20s %-9s %-28s %6.2fs peak %5.0fMB %s" % (fam, c["case"], c["arm"] + (("/" + c["mechanism"]) if c.get("mechanism") else ""), c.get("family", "")[:9], str(r["status"])[:28], r["supervisor_wall_s"], r["peak_tree_rss_bytes"] / 1e6, r["outcome"] if r["outcome"] != "COMPLETED" else ""), flush=True)
    for f_ in fams:
        print("family %s: ran %d cells total in this call; spent %.1f of %.0f s" % (f_, n, spent(S, f_), CAPS[f_]))


def status(S):
    import collections
    rs = rows(S)
    for fam in CAPS:
        f = [r for r in rs if r.get("family_code") == fam]; print(fam, len(f), "rows; spent %.1f s;" % spent(S, fam), dict(collections.Counter(str(r.get("status")) for r in f)))


if __name__ == "__main__":
    cmd, S = sys.argv[1], os.path.abspath(sys.argv[2])
    {"freeze": lambda: freeze(S), "run": lambda: run(S, sys.argv[3]), "status": lambda: status(S)}[cmd]()
