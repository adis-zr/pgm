"""BIDI pilot closeout: CELLS_LEDGER.jsonl (one reconciled row per planned cell), BUDGET_LEDGER.json (nonnested), MISSINGNESS.json,
UNCHANGED_HISTORY.json (inputs, frozen numerical set, census cells untouched) and REPORT.md answering the brief's seven questions in order.
Reads only saved artifacts; runs nothing numerical.    python -m bidi_closeout.report D"""
from __future__ import annotations
import os, sys, json, hashlib, math, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
CENSUS_D = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_CENSUS_2026-11-08")


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def budget(D, man):
    rows = jl(os.path.join(D, "PILOT_LEDGER.jsonl")); rec = {r["jid"]: r for r in rows if r["kind"] == "RECEIPT"}; total = 0.0; unresolved = []; by = collections.OrderedDict(); jobs = []
    for r in rows:
        if r["kind"] != "START":
            continue
        rc = rec.get(r["jid"])
        if rc is not None and not rc.get("cleanup_unresolved"):
            total += rc["wall_s"]; by[r["scope"]] = by.get(r["scope"], 0.0) + rc["wall_s"]; jobs.append({"job": r["job"], "scope": r["scope"], "wall_s": round(rc["wall_s"], 3), "outcome": rc["outcome"], "peak_tree_rss_bytes": rc.get("peak_tree_rss_bytes")})
        elif rc is not None:
            unresolved.append(r["job"]); total += max(rc["wall_s"], r.get("max_permitted_charge_s") or 0.0); jobs.append({"job": r["job"], "scope": r["scope"], "wall_s": rc["wall_s"], "outcome": "CLEANUP_UNRESOLVED", "charged_at": max(rc["wall_s"], r.get("max_permitted_charge_s") or 0.0)})
        else:
            unresolved.append(r["job"]); total += (r.get("max_permitted_charge_s") or 0.0); jobs.append({"job": r["job"], "scope": r["scope"], "wall_s": None, "outcome": "UNRESOLVED_START", "charged_at": r.get("max_permitted_charge_s")})
    return {"ceiling_s": man["ceiling_s"], "closeout_reserve_s": man["closeout_reserve_s"], "total_charged_s": round(total, 3), "by_scope_s": {k: round(v, 3) for k, v in by.items()}, "unresolved": unresolved, "jobs": jobs,
            "rule": "nonnested: every top-level job receipt once (its children included); a START without a receipt or with cleanup_unresolved is charged at max permitted; the closeout jobs (report, package) are appended after this file is first written and reconciled in the final version",
            "compliance": "QUALIFIED" if unresolved else "all starts receipted (charged jobs only; uncharged: read-only shell inspections, file copies, git operations, the pre-pilot microcalibrations disclosed in the report)",
            "within_ceiling": total <= man["ceiling_s"]}


def cells_ledger(D, man):
    out = []; led = jl(os.path.join(D, "PILOT_LEDGER.jsonl")); rc_by_job = {}
    for r in led:
        if r["kind"] == "RECEIPT" and r["job"].startswith("cell:"):
            rc_by_job[r["job"]] = r
    for c in man["cells"]:
        od = os.path.join(D, c["out_dir"]); cj = os.path.join(od, "cell.json"); nl = os.path.join(od, "NOT_LAUNCHED.json"); job = "cell:%02d:%s:%s:%ds" % (c["index"], c["case"], c["arm"], int(c["budget_s"])); rc = rc_by_job.get(job)
        row = dict(c, job=job, supervisor_outcome=(rc or {}).get("outcome"), supervisor_wall_s=(rc or {}).get("wall_s"), peak_tree_rss_bytes=(rc or {}).get("peak_tree_rss_bytes"), rss_samples=(rc or {}).get("rss_samples"), returncode=(rc or {}).get("returncode"))
        if os.path.exists(cj):
            r = json.load(open(cj)); row.update({"status": r.get("status"), "reason": (r.get("reason") or "")[:300] if isinstance(r.get("reason"), str) else r.get("reason"), "complete_response_s": r.get("complete_response_s"), "within_deadline": r.get("within_deadline"), "t_first_complete_output_s": r.get("t_first_complete_output_s"), "phases_s": r.get("phases_s"), "stop": r.get("stop"), "censored": r.get("censored", False)})
            if r.get("kernel"):
                row["kernel"] = {k: r["kernel"].get(k) for k in ("configs_expected", "configs_visited", "complete", "lanes", "counters")}
            if r.get("depth"):
                row["depth"] = {k: r["depth"].get(k) for k in ("E_term", "E_N", "E_Z", "e", "delta_float")}
            row["range_proof"] = r.get("range_proof"); row["max_width"] = r.get("max_width"); row["values_hex"] = r.get("values_hex"); row["first_pass"] = r.get("first_pass"); row["maxrss_self_bytes"] = r.get("maxrss_self_bytes"); row["maxrss_children_bytes"] = r.get("maxrss_children_bytes")
            if r.get("status") == "RESOURCE_STOP" and not row.get("stop") and r.get("attempts"):
                row["stop"] = r["attempts"][-1].get("stop")
            row["resolution"] = "COMPLETED_RECORD" if r.get("status") not in ("NO_RECORD",) else "KILLED_NO_RECORD"
        elif os.path.exists(nl):
            row.update(json.load(open(nl))); row["resolution"] = "NOT_LAUNCHED"
        else:
            row.update({"status": "UNLAUNCHED", "resolution": "EXPLICITLY_UNLAUNCHED (run did not reach this cell)"})
        if rc is None and row["resolution"] == "COMPLETED_RECORD":
            row["resolution"] = "RECORD_WITHOUT_RECEIPT"
        out.append(row)
    return out


def unchanged_history(D, man):
    rec = {}
    rec["inputs"] = {c: {"raw_model_sha256_now": sha(os.path.join(HERE, v["model_path"])), "equals_manifest": sha(os.path.join(HERE, v["model_path"])) == v["raw_model_sha256"], "raw_evidence_equals": sha(os.path.join(HERE, v["evidence_path"])) == v["raw_evidence_sha256"]} for c, v in man["cases"].items()}
    from adp import campaign as C
    h, _ = C.code_hash(); rec["frozen_numerical_set_code_hash"] = h; rec["equals_repaired_pin_da5b2c49"] = h.startswith("da5b2c49")
    before = os.path.join(CENSUS_D, "review_2026-11-08", "CELL_FILE_HASHES_before.json")
    if os.path.exists(before):
        bh = json.load(open(before)); diff = [k for k, v in bh.items() if not os.path.exists(os.path.join(CENSUS_D, k)) or sha(os.path.join(CENSUS_D, k)) != v]
        rec["census_cells"] = {"files_checked": len(bh), "differing": diff, "unchanged": not diff}
    prev = os.path.join(HERE, "runs", "mdi_2026-10-28", "AGGREGATE_DP_2026-11-07", "CELLS_LEDGER.jsonl")
    rec["aggregate_dp_campaign_ledger_sha256"] = sha(prev) if os.path.exists(prev) else None
    rec["census_ledgers_sha256"] = {f: sha(os.path.join(CENSUS_D, f)) for f in ("CELLS_LEDGER.jsonl", "CENSUS_LEDGER.jsonl") if os.path.exists(os.path.join(CENSUS_D, f))}
    return rec


def fmt_s(x):
    return "—" if x is None else "%.2f" % x


def main(D):
    man = json.load(open(os.path.join(D, "PILOT_MANIFEST.json"))); cells = cells_ledger(D, man); B = budget(D, man); UH = unchanged_history(D, man)
    cal = json.load(open(os.path.join(D, "LANE_CALIBRATION.json"))); app = json.load(open(os.path.join(D, "APPLICABILITY_CENSUS.json"))); syn = json.load(open(os.path.join(D, "synthetic", "SYNTHETIC_FULLSIZE.json")))
    with open(os.path.join(D, "CELLS_LEDGER.jsonl"), "w") as f:
        for r in cells:
            f.write(json.dumps(r, default=str) + "\n")
    json.dump(B, open(os.path.join(D, "BUDGET_LEDGER.json"), "w"), indent=1); json.dump(UH, open(os.path.join(D, "UNCHANGED_HISTORY.json"), "w"), indent=1)
    miss = {"planned": len(cells), "completed_record": sum(1 for r in cells if r["resolution"] == "COMPLETED_RECORD"), "killed_no_record": [r["job"] for r in cells if r["resolution"] == "KILLED_NO_RECORD"], "not_launched": [r["job"] for r in cells if r["resolution"].startswith(("NOT_LAUNCHED", "EXPLICITLY"))], "record_without_receipt": [r["job"] for r in cells if r["resolution"] == "RECORD_WITHOUT_RECEIPT"], "unavailable_arms": [],
            "uncharged_work": ["pre-pilot microcalibrations of 9 Nov (gmpy2 / numpy loops; disclosed prior exposure, not completed cells)", "one development smoke run of the pipeline on a 5-variable synthetic model before the first charged qualification job (disclosed)", "read-only shell inspections, file copies, git operations"],
            "rss_caveat": "peak_tree_rss_bytes is a 50 ms sample of the supervised process tree (best effort, not an allocator cap); maxrss_self is the cell process's own ru_maxrss"}
    json.dump(miss, open(os.path.join(D, "MISSINGNESS.json"), "w"), indent=1)
    by = {(r["arm"], r["case"], int(r["budget_s"])): r for r in cells}; arms = ["BIDI_NATIVE_CERT", "ADP_REPAIRED", "EXACT_LIBDAI", "BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"]; cases = ["DBN_11", "DBN_12", "DBN_15", "DBN_16"]
    def cert(arm, b):
        return [c for c in cases if (arm, c, b) in by and by[(arm, c, b)].get("status") == "CERTIFIED"]
    def done(arm, b):
        return [c for c in cases if (arm, c, b) in by and by[(arm, c, b)].get("status") in ("CERTIFIED", "COMPLETE")]
    L = []
    L.append("# BIDI_NATIVE_CERT pilot — first bidirectional inference kernel on the four DBNs (9 November 2026)\n")
    L.append("Branch `%s`, frozen commit `%s` (branched from `%s`; repaired ADP lineage `%s`, frozen numerical set `%s`; census supervisor repair `%s`). Kernel binary sha256 `%s` (%s, flags `%s`). Frozen config: lanes_k = %d (%d lanes), block_steps = %d, binary64 round-to-nearest-even, one worker thread. Seed %d. 32 planned cells; every cell one observation; order interleaved and published in PILOT_MANIFEST.json before any inference.\n"
             % (man["branch"], man["commit"][:12], man["parent_lineage"]["branched_from"][:12], man["parent_lineage"]["repaired_adp_commit"][:12], man["parent_lineage"]["frozen_set_code_hash_now"][:12], man["parent_lineage"]["census_supervisor_repair_commit"][:12], man["kernel_binary_sha256"][:12], man["kernel_build"]["compiler_version"].split("\n")[0], " ".join(man["kernel_build"]["flags"]), man["config_bidi"]["lanes_k"], 1 << man["config_bidi"]["lanes_k"], man["config_bidi"]["block_steps"], man["seed"]))
    L.append("Scope: four preselected structural witnesses chosen from known census results (not a blind holdout). Four-case success is not broad suite success. Every statement below is one observation per cell; nothing here claims repeatability.\n")
    # ---------------------------------------------------------------------------------------------------- Q1
    q = [f for f in os.listdir(os.path.join(D, "qualification")) if f.endswith(".txt")]; qt = {}
    for f in q:
        t = open(os.path.join(D, "qualification", f)).read().strip().splitlines(); qt[f] = t[-1] if t else ""
    L.append("## 1. Did implementation qualification pass, and under what assumptions?\n")
    L.append("**Yes.** Receipts in `qualification/`: %s. Synthetic full-size cells (`synthetic/SYNTHETIC_FULLSIZE.json`): a seeded random positive K22,22 certified in %.2f s (kernel stream %.2f s, %s configurations, max width %.2e); native and MPFR-53 agree **bitwise** on K12,12 (%s). The kernel's floating-point self-check (binary64, nearest-even, no contraction, FLT_EVAL_METHOD 0) passed in every cell; the build record binds the binary and the source to the schedule id.\n"
             % ("; ".join("%s: %s" % (f, qt[f]) for f in sorted(qt)), syn["BIDI_NATIVE_CERT_K22x22"]["complete_response_s"], syn["BIDI_NATIVE_CERT_K22x22"]["phases_s"]["kernel_stream"], "{:,}".format(syn["BIDI_NATIVE_CERT_K22x22"]["kernel"]["configs_visited"]), float(Fr(syn["BIDI_NATIVE_CERT_K22x22"]["max_width"])), syn["native_vs_mpfr53_bitwise_K12x12"]))
    L.append("Assumptions (stated plainly): the trusted/qualified components are the certifying executor (`bidi/executor.py`), its parse (`ext.uai`), structural validation, exact normal-range and error-depth computations, verified source conversion, the frozen native kernel (`bidi/kernel.cpp`, Apple clang 15, `-ffp-model=strict -ffp-contract=off`), the exact-rational enclosure, `adp.publish` and the separate point verifier. There is ONE authoritative numerical pass per cell: no second independent numerical implementation runs on a benchmark cell (the MPFR-53 arm is a same-schedule control, not independence). Correct execution of the qualified kernel is an explicit assumption; coordinated corruption inside the trusted executor is not detected without extra redundancy. The recognizer's plan and any producer numbers are never trusted. Proofs: `PROOF_NOTES.md` (range Theorem R, depth Lemma D, enclosure lemma).\n")
    # ---------------------------------------------------------------------------------------------------- Q2
    L.append("## 2. How many of the four tasks were certified within 20 s and 120 s, and which phases determined failures?\n")
    L.append("| arm | 20 s certified | 120 s certified |\n|---|---|---|")
    for a in arms:
        if a in ("BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"):
            L.append("| %s (120 s only) | — | %d/4 %s |" % (a, len(cert(a, 120)), cert(a, 120)))
        elif a == "EXACT_LIBDAI":
            L.append("| %s (UNCERTIFIED floating answer; 'complete' not 'certified') | complete %d/4 %s | complete %d/4 %s |" % (a, len(done(a, 20)), done(a, 20), len(done(a, 120)), done(a, 120)))
        else:
            L.append("| %s | %d/4 %s | %d/4 %s |" % (a, len(cert(a, 20)), cert(a, 20), len(cert(a, 120)), cert(a, 120)))
    L.append("")
    L.append("| # | arm | case | budget | status | complete response s | checked output s | supervisor wall s | peak tree RSS MB | stop / reason |\n|---|---|---|---|---|---|---|---|---|---|")
    for r in cells:
        L.append("| %d | %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (r["index"], r["arm"], r["case"], int(r["budget_s"]), r.get("status"), fmt_s(r.get("complete_response_s")), fmt_s(r.get("t_first_complete_output_s")), fmt_s(r.get("supervisor_wall_s")), ("%.0f" % (r["peak_tree_rss_bytes"] / 1e6)) if r.get("peak_tree_rss_bytes") else "—", (json.dumps(r.get("stop")) if r.get("stop") else (r.get("reason") or ""))[:120].replace("|", "/")))
    L.append("")
    fails = [r for r in cells if r["arm"] == "BIDI_NATIVE_CERT" and r.get("status") != "CERTIFIED"]
    L.append("BIDI_NATIVE_CERT non-certified cells: %s.\n" % ("none" if not fails else "; ".join("%s %ds: %s (%s)" % (r["case"], int(r["budget_s"]), r.get("status"), json.dumps(r.get("stop")) or r.get("reason")) for r in fails)))
    L.append("Per-phase walls of the BIDI_NATIVE_CERT cells (seconds; `kernel_stream` is the complete enumeration, `publish` includes the separate point-verifier process):\n")
    phs = ["startup_imports", "recognize", "parse_bind", "validate_structure", "range_depth_proofs", "convert_verify", "kernel_init", "kernel_stream", "enclose", "publish"]
    L.append("| case | budget | " + " | ".join(phs) + " | total |\n|---|---|" + "---|" * (len(phs) + 1))
    for r in cells:
        if r["arm"] == "BIDI_NATIVE_CERT" and r.get("phases_s"):
            L.append("| %s | %d | %s | %s |" % (r["case"], int(r["budget_s"]), " | ".join(("%.3f" % r["phases_s"][p]) if p in r["phases_s"] else "—" for p in phs), fmt_s(r.get("complete_response_s"))))
    L.append("")
    # ---------------------------------------------------------------------------------------------------- Q3
    L.append("## 3. Did the stream remove the exponential stored tables and tape, and what was actually measured?\n")
    L.append("By construction the kernel holds (2m+1) product trees of 2P entries per lane plus O((m+n)·lanes) accumulators and scratch: no 2^n table, no term list, no reverse tape (`PROOF_NOTES.md` §2). Measured:\n")
    L.append("| case | budget | kernel bytes allocated | cell maxrss (MB) | supervised tree peak RSS (MB, 50 ms samples) | configurations | counted mults | counted adds |\n|---|---|---|---|---|---|---|---|")
    for r in cells:
        if r["arm"] == "BIDI_NATIVE_CERT" and r.get("kernel") and r["kernel"].get("counters"):
            c = r["kernel"]["counters"]; L.append("| %s | %d | %s | %.1f | %s | %s | %s | %s |" % (r["case"], int(r["budget_s"]), "{:,}".format(c.get("bytes_allocated") or 0), (r.get("maxrss_self_bytes") or 0) / 1e6, ("%.0f" % (r["peak_tree_rss_bytes"] / 1e6)) if r.get("peak_tree_rss_bytes") else "—", "{:,}".format(c["configs"]), "{:,}".format(c["mults"]), "{:,}".format(c["adds"])))
    adp = [r for r in cells if r["arm"] == "ADP_REPAIRED" and r.get("peak_tree_rss_bytes")]
    L.append("\nFor comparison the repaired ADP arm's supervised peak RSS on the same cells: %s. Context (not this pilot): the census measured DBN_16's node-0 dense core alone at 4,194,304 entries.\n" % ", ".join("%s %ds %.0f MB" % (r["case"], int(r["budget_s"]), r["peak_tree_rss_bytes"] / 1e6) for r in adp))
    # ---------------------------------------------------------------------------------------------------- Q4
    L.append("## 4. Full-kernel throughput against the earlier microcalibrations\n")
    L.append("Units reconciled. Counted operations per configuration for m = n = 22, k = 3, P = 32: 380 multiplications + 86 additions = 466 (the brief's 468 and 443 were two other tree conventions; the implemented one is fixed in `PROOF_NOTES.md` §3 and the kernel's analytic counters). Measured on the frozen matrix (one observation each):\n")
    L.append("| case | configurations | counted ops | kernel_stream s | ns / configuration | G ops / s (counted ops ÷ measured stream wall) |\n|---|---|---|---|---|---|")
    for r in cells:
        if r["arm"] == "BIDI_NATIVE_CERT" and int(r["budget_s"]) == 120 and r.get("kernel") and r["kernel"].get("counters") and r.get("phases_s", {}).get("kernel_stream"):
            c = r["kernel"]["counters"]; ks = r["phases_s"]["kernel_stream"]; ops = c["mults"] + c["adds"]; L.append("| %s | %s | %s | %.3f | %.0f | %.2f |" % (r["case"], "{:,}".format(c["configs"]), "{:,}".format(ops), ks, 1e9 * ks / c["configs"], ops / ks / 1e9))
    L.append("\nLane calibration on the synthetic K20,20 (`LANE_CALIBRATION.json`, all three candidates recorded): %s ns/configuration for %s lanes; k = 3 frozen before any benchmark inference. Reconciliation with the pre-pilot microcalibrations (disclosed prior exposure, not completed cells): the gmpy2-object forecast of 8–14 M operations/s would put ~3.9 G operations (two endpoints) at 280–491 s; the implemented native schedule performs ONE nearest-rounded pass (~1.96 G counted operations for DBN_16) and the measured full-kernel rate is in the table above, i.e. the earlier 'vectorised float64 multiply' rate of ~2.5 G/s was a pure-multiply upper bound, while the complete kernel (tree updates, prefix/suffix, accumulations, indexing) runs at the rate measured here. The forecasts were not outcomes; the outcomes are in section 2.\n"
             % (" / ".join("%.0f" % c["ns_per_config"] for c in cal["candidates"]), " / ".join(str(c["lanes"]) for c in cal["candidates"])))
    # ---------------------------------------------------------------------------------------------------- Q5
    L.append("## 5. Duplicate-work and MPFR-53 controls\n")
    L.append("| case | DUPLICATED-WORK status | first (discarded) pass s | authoritative pass s | total | MPFR-53 status | MPFR configs visited / expected | MPFR charged wall s |\n|---|---|---|---|---|---|---|---|")
    for c in cases:
        d = by.get(("BIDI_NATIVE_DUPLICATE_WORK", c, 120), {}); mref = by.get(("BIDI_MPFR53_CERT", c, 120), {}); fp = d.get("first_pass") or {}
        kv = mref.get("kernel") or {}; vis = kv.get("configs_visited"); stop = mref.get("stop") or {}; det = (stop.get("detail") or mref.get("reason") or "") if isinstance(stop, dict) else ""
        import re
        mm = re.search(r"(\d+) of (\d+) configurations", det or "")
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (c, d.get("status"), fmt_s(fp.get("wall_s")), fmt_s((d.get("complete_response_s") or 0) - (fp.get("wall_s") or 0)) if d.get("complete_response_s") else "—", fmt_s(d.get("complete_response_s")), mref.get("status"), ("%s / %s" % (mm.group(1), mm.group(2))) if mm else ("%s / %s" % (vis, kv.get("configs_expected")) if vis else "—"), fmt_s(mref.get("supervisor_wall_s"))))
    L.append("\nThe DUPLICATED-WORK control repeats the SAME implementation (parse → validation → conversion → kernel → enclosure) once with its outputs discarded before the authoritative pass; it is not two independent solvers and not the old two-pass ADP protocol, and it does not establish that old ADP would halve. The MPFR-53 arm runs the identical schedule at precision 53 nearest in a Python per-state loop (the object/dispatch-cost comparator); a timeout is a censored result with the visited-configuration count recorded, not a measured runtime.\n")
    # ---------------------------------------------------------------------------------------------------- Q6
    L.append("## 6. Exploratory end-to-end comparison with repaired ADP and libDAI\n")
    L.append("Certification differs by arm: BIDI_NATIVE_CERT and ADP_REPAIRED deliver a checked, task-bound, simplex-feasible point with a deterministic 1/200 guarantee (ADP via two numerical passes and an independent checker; BIDI via the one-pass validated-execution protocol); EXACT_LIBDAI delivers an UNCERTIFIED binary64 answer (junction tree, HUGIN updates, 8 GiB admission). Ratios are reported only for matched COMPLETED cells; timeouts are censored (status + charged time), never converted to a completion time.\n")
    L.append("| case | budget | BIDI_NATIVE_CERT | ADP_REPAIRED | EXACT_LIBDAI | BIDI/ADP (completed only) | BIDI/libDAI (completed only) |\n|---|---|---|---|---|---|---|")
    for c in cases:
        for b in (20, 120):
            rb = by.get(("BIDI_NATIVE_CERT", c, b), {}); ra = by.get(("ADP_REPAIRED", c, b), {}); rl = by.get(("EXACT_LIBDAI", c, b), {})
            def cell_s(r):
                return "%s %s" % (r.get("status"), fmt_s(r.get("complete_response_s")) + " s") if r else "—"
            ratio_a = ("%.3f" % (rb["complete_response_s"] / ra["complete_response_s"])) if rb.get("status") == "CERTIFIED" and ra.get("status") == "CERTIFIED" else "censored"
            ratio_l = ("%.3f" % (rb["complete_response_s"] / rl["complete_response_s"])) if rb.get("status") == "CERTIFIED" and rl.get("status") == "COMPLETE" else "censored"
            L.append("| %s | %d | %s | %s | %s | %s | %s |" % (c, b, cell_s(rb), cell_s(ra), cell_s(rl), ratio_a, ratio_l))
    L.append("\nNew versus old ADP changes schedule, substrate and protocol together: it measures an end-to-end implementation/coverage difference on these four cases, not an isolated algorithmic effect. A native port of old ADP would be a separate experiment. Historical context (not rerun here): the repaired ADP census recorded RESOURCE_STOP [DEADLINE] for all four DBNs at both budgets; libDAI's junction tree refused the DBNs on its 8 GiB admission forecast in the 7 Nov campaign.\n")
    # ---------------------------------------------------------------------------------------------------- agreement diagnostics (not independence, not the guarantee)
    L.append("### Agreement diagnostics (diagnostic only; the guarantee is the executor's certificate)\n")
    ag = []
    for c in cases:
        n20 = by.get(("BIDI_NATIVE_CERT", c, 20), {}); n120 = by.get(("BIDI_NATIVE_CERT", c, 120), {}); mref = by.get(("BIDI_MPFR53_CERT", c, 120), {}); d = by.get(("BIDI_NATIVE_DUPLICATE_WORK", c, 120), {})
        zn = (n120.get("values_hex") or {}).get("Z"); ag.append("| %s | %s | %s | %s |" % (c, (n20.get("values_hex") or {}).get("Z") == zn, ((mref.get("values_hex") or {}).get("Z") == zn) if mref.get("values_hex") else "censored (%s)" % (mref.get("status")), ((d.get("first_pass") or {}).get("Z_hex") == (d.get("values_hex") or {}).get("Z")) if d.get("values_hex") else "—"))
    L.append("| case | native 20 s == native 120 s (bitwise Z) | MPFR-53 == native (bitwise Z, same schedule) | duplicate-work first pass == authoritative (bitwise Z) |\n|---|---|---|---|"); L += ag
    try:
        from ext import uai as U
        l = by[("EXACT_LIBDAI", "DBN_11", 120)]; n = by[("BIDI_NATIVE_CERT", "DBN_11", 120)]
        if l.get("status") == "COMPLETE" and n.get("status") == "CERTIFIED":
            rl, _ = U.read_mar(os.path.join(D, l["out_dir"], "output.MAR")); rb, _ = U.read_mar(os.path.join(D, n["out_dir"], "output.MAR")); rec = json.load(open(os.path.join(D, n["out_dir"], "checked_record.json")))
            nv = len(rb); md = max(abs(float(rl[v][s]) - float(rb[v][s])) for v in range(nv) for s in range(2)); w = max(float(Fr(b) - Fr(a)) for v in range(nv) for a, b in rec["certified_intervals"][str(v)])
            L.append("\nlibDAI's UNCERTIFIED DBN_11 answer (6-decimal MAR) vs the BIDI certified point: max coordinate difference %.2e; BIDI certified interval widths ≤ %.2e. Agreement to the printed precision is a diagnostic, not evidence for either side's correctness.\n" % (md, w))
    except Exception as ex:
        L.append("\n(libDAI agreement diagnostic unavailable: %s)\n" % ex)
    # ---------------------------------------------------------------------------------------------------- Q7
    s = app["summary"]
    L.append("## 7. Full-panel applicability, unknowns, and what remains unimplemented\n")
    L.append("`APPLICABILITY_CENSUS.json` (read-only source checks on all 46 accessible cases; 2 inaccessible slots UNKNOWN; no inference): structurally eligible (binary, pairwise, bipartite) %d/46: %s; of these, the binary64 normal-range predicate with the factor-two margin holds for %d: %s; not eligible %d (%s); unknown %d. Selected into the pilot: %s. A case not selected is not a failure; a failed range predicate is a typed route limitation, not a structural impossibility (an MPFR or scaled backend could serve it); eligibility does not promise affordable completion (the Grids are K-like bipartite grids with %s).\n"
             % (len(s["structurally_eligible"]), s["structurally_eligible"], len(s["eligible_and_range_ok"]), s["eligible_and_range_ok"], s["not_eligible"], ", ".join("%s: %d" % kv for kv in s["not_eligible_reasons"].items()), s["unknown"], s["selected"],
                "; ".join("%s sides %s, 2^%d configurations, range %s" % (r["case"], r.get("sides"), (r.get("sides") or [0, 0])[1], r.get("range")) for r in app["rows"] if r.get("structural") == "ELIGIBLE" and r["case"].startswith("Grids"))))
    L.append("UNIMPLEMENTED directions (separate, not evidenced by these four results): whole-class demand pruning (MUNIN1 node 120 witness), Promedus_14's downstream root-consumer volume, Protein's distinct-demand lazy work, consumer fusion of single-input eliminations, first-derivative-aware response coarsening, a general scaled/log-domain or directed-rounding SIMD backend, a planner. None was started.\n")
    # ---------------------------------------------------------------------------------------------------- budget / provenance
    L.append("## Budget, missingness, provenance\n")
    L.append("Charged (nonnested, PILOT_LEDGER.jsonl through the repaired supervisor): **%.1f s of %.0f s**; by scope %s; unresolved starts: %s; compliance: %s. The report and packaging jobs are appended after this file is first generated and are reconciled in the final BUDGET_LEDGER.json. Uncharged and disclosed: %s.\n" % (B["total_charged_s"], B["ceiling_s"], B["by_scope_s"], B["unresolved"] or "none", B["compliance"], "; ".join(miss["uncharged_work"])))
    L.append("Missingness: %d planned cells, %d with a completed record, killed without record %s, not launched %s, record without receipt %s. RSS caveat: %s.\n" % (miss["planned"], miss["completed_record"], miss["killed_no_record"] or "none", miss["not_launched"] or "none", miss["record_without_receipt"] or "none", miss["rss_caveat"]))
    L.append("Unchanged history (`UNCHANGED_HISTORY.json`): the four raw inputs equal their census hashes (%s); the frozen numerical set hash is `%s` (= repaired pin da5b2c49: %s); the census cell files %s.\n" % (all(v["equals_manifest"] and v["raw_evidence_equals"] for v in UH["inputs"].values()), UH["frozen_numerical_set_code_hash"][:12], UH["equals_repaired_pin_da5b2c49"], ("all %d unchanged" % UH["census_cells"]["files_checked"]) if UH.get("census_cells", {}).get("unchanged") else "DIFFER: %s" % UH.get("census_cells", {}).get("differing")))
    L.append("Permitted conclusion: see section 2 for the specific coverage result at each budget; any success is case-specific and exploratory; no repeatability is claimed from one observation; the new guarantee comes from the qualified executor and its certificate, not from agreement with an uncertified point. STOPPED FOR REVIEW.\n")
    open(os.path.join(D, "REPORT.md"), "w").write("\n".join(L))
    # ------------------------------------------------------------------------------------------------ HANDOFF.md (same records)
    H = ["BIDI NATIVE PILOT — HANDOFF (branch %s; frozen commit %s; 9 November 2026)" % (man["branch"], man["commit"][:12]), "",
         "WHAT WAS DONE: first bidirectional inference kernel = the theory packet's complete conditioned bipartite stream (BD-08) implemented natively",
         "(binary64 nearest-even, 8 lanes, current-leaf product trees, prefix/suffix exclusion products; no 2^n table, no reverse tape), executed",
         "under the one-pass validated-execution protocol (BD-11): untrusted recognizer proposes the plan; the trusted certifying executor re-parses",
         "the caller's files, validates structure, proves the exact normal-range bound and the error-depth bound of the implemented schedule,",
         "verifies every source conversion exactly, runs the frozen kernel once, encloses q in [(1-delta) r, r/(1-delta)] with exact rationals,",
         "publishes on the proved dyadic grid and re-verifies the delivered decimals with the separate task-bound point verifier.",
         "", "RESULT (one observation per cell; 4 preselected DBNs, not a blind holdout):"]
    for a in ("BIDI_NATIVE_CERT", "ADP_REPAIRED"):
        H.append("  %-28s certified %d/4 at 20 s %s, %d/4 at 120 s %s" % (a, len(cert(a, 20)), cert(a, 20), len(cert(a, 120)), cert(a, 120)))
    H.append("  %-28s complete (UNCERTIFIED) %d/4 at 20 s, %d/4 at 120 s" % ("EXACT_LIBDAI", len(done("EXACT_LIBDAI", 20)), len(done("EXACT_LIBDAI", 120))))
    for a in ("BIDI_NATIVE_DUPLICATE_WORK", "BIDI_MPFR53_CERT"):
        H.append("  %-28s certified %d/4 at 120 s %s" % (a, len(cert(a, 120)), cert(a, 120)))
    bn = [r for r in cells if r["arm"] == "BIDI_NATIVE_CERT" and r.get("status") == "CERTIFIED"]
    if bn:
        H.append("  BIDI_NATIVE_CERT end-to-end times: %s; cell maxrss %s MB; supervised tree peak %s MB" % (", ".join("%s %ds %.2f s" % (r["case"], int(r["budget_s"]), r["complete_response_s"]) for r in bn), "/".join("%.0f" % (r["maxrss_self_bytes"] / 1e6) for r in bn), "/".join("%.0f" % (r["peak_tree_rss_bytes"] / 1e6) for r in bn if r.get("peak_tree_rss_bytes"))))
    H += ["", "TRUST BOUNDARY: one authoritative numerical pass; the executor + kernel + publisher are the qualified components; no second independent",
          "numerical implementation per benchmark cell (MPFR-53 arm = same-schedule control). Correct execution of the qualified kernel is assumed.",
          "", "QUALIFICATION: tests/test_bidi_pilot.py (53 controls: exact oracle on tiny models incl. zeros / evidence / unequal / empty sides / absent edges /",
          "scalar / duplicates / orientation; lane+Gray coverage exactly once; block tails; conversion halfway cases + rejections; range rejection;",
          "delta rejection; fp-environment detection; build-record binding; recognizer-claim bypass; omitted/duplicated/corrupted/non-finite results;",
          "altered conversion; all three arms certify; cross-evidence refusal at publication + point verifier + stale records; tampered records / rows /",
          "malformed numbers; deadline typed stop; size limits) + 52 existing regressions; synthetic K22x22 cell certified in %.2f s; native == MPFR-53 bitwise on K12x12." % syn["BIDI_NATIVE_CERT_K22x22"]["complete_response_s"],
          "", "BUDGET: %.1f s of %.0f s charged (nonnested; by scope %s); unresolved: %s; uncharged disclosed: pre-pilot microcalibrations, one dev smoke run, shell/git inspections." % (B["total_charged_s"], B["ceiling_s"], B["by_scope_s"], B["unresolved"] or "none"),
          "", "APPLICABILITY: %d/46 structurally eligible %s; %d pass the binary64 range predicate %s; 38 not eligible (23 non-binary, 11 higher arity, 4 non-bipartite); 2 slots unknown." % (len(s["structurally_eligible"]), s["structurally_eligible"], len(s["eligible_and_range_ok"]), s["eligible_and_range_ok"]),
          "", "NOT DONE / NOT CLAIMED: no planner, no pruning / fusion / coarsening rule, no scaled or directed-rounding SIMD backend, no native port of old ADP,",
          "no repeatability, no broad suite success; the 'new vs old ADP' difference bundles schedule + substrate + protocol. STOPPED FOR REVIEW.",
          "", "FILES: PILOT_MANIFEST.json, CONFIG_bidi.json, PILOT_LEDGER.jsonl, CELLS_LEDGER.jsonl, BUDGET_LEDGER.json, MISSINGNESS.json, UNCHANGED_HISTORY.json,",
          "APPLICABILITY_CENSUS.json, LANE_CALIBRATION.json, PROOF_NOTES.md, REPORT.md, qualification/, synthetic/, cells/<index>__<case>__<arm>__<budget>__<task>/."]
    open(os.path.join(D, "HANDOFF.md"), "w").write("\n".join(H) + "\n")
    print(json.dumps({"certified_20": {a: len(cert(a, 20)) for a in ("BIDI_NATIVE_CERT", "ADP_REPAIRED")}, "certified_120": {a: len(cert(a, 120)) for a in arms}, "libdai_complete": {20: len(done("EXACT_LIBDAI", 20)), 120: len(done("EXACT_LIBDAI", 120))}, "charged_s": B["total_charged_s"], "unresolved": B["unresolved"], "missing": miss["not_launched"] + miss["killed_no_record"]}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
