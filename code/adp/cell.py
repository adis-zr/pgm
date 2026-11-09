"""One AGGREGATE_DP_V1 cell in a FRESH process:
    python -m adp.cell MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG.json
Timer starts before imports (T_START at module import); phases are non-overlapping: startup_imports, parse, source_reductions,
plan, forward, backward, enclose (producer N1 enclosures + provisional point), certificate_write, checker (separate process,
own outward replay; its wall and RSS are part of the cell), publish (robust-center point on the exact grid against the
CHECKER's intervals, serialization, exact re-verification). Publication happens ONLY after the checker completed.
Precision ladder: 64 -> 128 -> 256 -> ... only when a COMPLETED structural computation fails the numeric publication predicate
(the structure is retained; values, adjoints and accumulators are invalidated; every attempt is charged).
Ablations (config): A1 rules=[] ; A2 views=False ; A3 sparse=False ; A4 memo=False (lazy with no result cache, no adjoint
coalescing) ; A5 batched=False (scalar entry evaluation). Status vocabulary is recorded in cell.json["status"]."""
from __future__ import annotations
import os, sys, json, time, subprocess, hashlib, resource
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr
from adp import source as SRC, engine as EN, publish as PB
from mdi import arith as A

ARM = "AGGREGATE_DP_V1"


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def run_cell(mp, ep, out, deadline, cfg, rec):
    T_DL = T_START + deadline
    rec["phases_s"]["startup_imports"] = now(); t = now()
    m, ev = SRC.load(mp, ep); rec["phases_s"]["parse"] = now() - t
    rec["source"] = SRC.canonical_source_hashes(mp, ep); rec["n_vars"] = m.nvars; rec["n_evidence"] = len(ev); rec["requested_coordinates"] = sum(m.card); rec["task"] = task_of(rec, m)
    expected = list(range(m.nvars))                                        # the CALLER's contract: every original variable
    rec["expected_queries"] = "all %d original variables (observed as point masses)" % m.nvars
    # ---- exact source reductions (bounded: wall fraction of the cell + work cap)
    t = now(); R = SRC.Reduced(m, ev); red_deadline = time.monotonic() + cfg["source_reduction_wall_fraction"] * (T_DL - time.monotonic())
    rrec = R.reduce(cfg["rules"], deadline=red_deadline); rec["phases_s"]["source_reductions"] = now() - t
    kinds = {}
    for s in R.steps:
        kinds[s[0]] = kinds.get(s[0], 0) + 1
    rec["reductions"] = {"free_original": m.nvars - len(ev), "free_reduced": len(R.dom), "steps": kinds, "recognition": rrec, "reduced_states": sum(len(d) for d in R.dom.values()), "scale": str(R.scale)}
    reduced_record = R.record(); rec["reduced_hash"] = reduced_record["reduced_hash"]
    if R.zero_proof is not None:
        cert = {"arm": ARM, "model_path": os.path.abspath(mp), "evidence_path": os.path.abspath(ep), "source": rec["source"], "expected_queries": expected, "reduced": reduced_record, "plan": None, "precision": None, "published_points": None}
        atomic_write(os.path.join(out, "certificate.json"), json.dumps(cert, default=str)); rec["certificate_bytes"] = os.path.getsize(os.path.join(out, "certificate.json"))
        chk = run_checker(out, T_DL - time.monotonic(), rec); rec["checker"] = chk
        rec["status"] = "INCONSISTENT_EVIDENCE_CERTIFIED" if chk.get("status") == "ZERO_EVIDENCE_PROVED" else ("CHECK_FAILED" if chk.get("status") == "REJECTED" else "INCONSISTENT_EVIDENCE_UNCHECKED"); rec["reason"] = chk.get("reason"); return
    # ---- plan
    t = now()
    try:
        P = EN.Program(R, cfg, deadline=T_DL)
    except EN.Stop as ex:
        rec["phases_s"]["plan"] = now() - t; rec["status"] = "RESOURCE_STOP"; rec["stop"] = {"phase": "plan", "kind": ex.kind, "detail": ex.detail}; return
    rec["phases_s"]["plan"] = now() - t
    fmts = {}
    for nd in P.nodes:
        fmts[nd.fmt] = fmts.get(nd.fmt, 0) + 1
    rec["program"] = {"nodes": len(P.nodes), "components": len(P.components), "order_capped_at": P.order_info["capped_at"], "order_work": P.order_info["work"], "formats_planned": fmts,
                      "core_entries_total": sum(nd.size for nd in P.nodes), "bag_rows_total": sum(nd.bag for nd in P.nodes), "largest_core": max((nd.size for nd in P.nodes), default=0), "largest_bag": max((nd.bag for nd in P.nodes), default=0),
                      "views_nontrivial_axes": sum(1 for nd in P.nodes for w in nd.scope if len(nd.views[w].reps) < len(P.dom[w])), "structure_hash": P.structure_hash()}
    plan_record = P.plan_record()
    # ---- numeric ladder
    attempts = []; published = None; checker_rec = None; final_status = None
    for p in cfg["precision_ladder"]:
        if time.monotonic() > T_DL:
            final_status = "RESOURCE_STOP"; rec["stop"] = {"phase": "ladder", "kind": "DEADLINE", "detail": "before precision %d" % p}; break
        att = {"precision": p, "phases_s": {}}; counters = {}
        try:
            t = now(); X = EN.Executor(P, p, cfg, deadline=T_DL, counters=counters); X.forward(); att["phases_s"]["forward"] = now() - t
            t = now(); X.backward(); att["phases_s"]["backward"] = now() - t
            t = now(); enc, roots, Emax = X.enclosures(); att["phases_s"]["enclose"] = now() - t; att["E_max"] = Emax
            att["roots_producer_down"] = {str(r): str(A.exact_fr(z)) for r, (z, E) in roots.items()}
        except EN.Stop as ex:
            att["stop"] = {"kind": ex.kind, "detail": ex.detail}; att["counters"] = counters; att["phases_s"]["total"] = now() - t; attempts.append(att)
            final_status = "RESOURCE_STOP"; rec["stop"] = {"phase": "numeric", "kind": ex.kind, "detail": ex.detail, "precision": p}; break
        except A.NumericalRefusal as ex:
            att["numeric_refusal"] = str(ex); att["counters"] = counters; attempts.append(att); continue              # typed numeric outcome -> next precision
        att["counters"] = counters; att["formats_executed"] = fmt_counts(X)
        if any(A.exact_fr(z) == 0 for z, _ in roots.values()):
            attempts.append(att); final_status = "ZERO_EVIDENCE_NUMERIC_UNRESOLVED"; break            # a downward zero is not a proof; the checker decides
        # producer's provisional original rows (diagnostic only; the checker's intervals govern publication)
        t = now(); orig = decode_rows(R, enc); att["phases_s"]["provisional_enclose"] = now() - t
        att["producer_max_width"] = str(max((U - L) for row in orig.values() for L, U in row)); pts = None
        # certificate: structure + precision + the provisional point (the checker validates the point against ITS intervals)
        t = now()
        cert = {"arm": ARM, "model_path": os.path.abspath(mp), "evidence_path": os.path.abspath(ep), "source": rec["source"], "expected_queries": expected, "reduced": reduced_record, "plan": plan_record, "precision": p,
                "published_points": None, "checker_caps": {"dense_core_cap_entries": cfg["dense_core_cap_entries"], "dense_bag_cap_entries": cfg["dense_bag_cap_entries"], "sparse_rows_cap": cfg["sparse_rows_cap"], "lazy_cache_entries": cfg["lazy_cache_entries"], "value_bytes_cap": cfg["checker_value_bytes_cap"]}}
        atomic_write(os.path.join(out, "certificate.json"), json.dumps(cert, default=str)); att["phases_s"]["certificate_write"] = now() - t; rec["certificate_bytes"] = os.path.getsize(os.path.join(out, "certificate.json"))
        del X, enc, roots; import gc; gc.collect()
        t = now(); checker_rec = run_checker(out, T_DL - time.monotonic(), rec, suffix="_p%d" % p); att["phases_s"]["checker"] = now() - t; att["checker_status"] = checker_rec.get("status")
        attempts.append(att)
        st = checker_rec.get("status")
        if st == "INTERVALS_OK":
            t = now(); final_status = publish(out, m, checker_rec, rec, "_p%d" % p); rec["phases_s"]["publish"] = rec["phases_s"].get("publish", 0.0) + (now() - t)
            if final_status == "CERTIFIED":
                break
            if time.monotonic() > T_DL - 0.5 or p == cfg["precision_ladder"][-1]:
                break
            continue                                                                               # too wide / point infeasible: escalate precision (structure retained)
        if st == "NUMERIC_UNRESOLVED_POSITIVITY":
            final_status = "NUMERIC_RESOURCE_STOP"
            if time.monotonic() > T_DL - 0.5:
                break
            continue
        if st == "ZERO_EVIDENCE_PROVED":
            final_status = "INCONSISTENT_EVIDENCE_CERTIFIED"; break
        if st == "CHECKER_INCOMPLETE":
            final_status = "SOLVER_COMPLETE_CHECKER_INCOMPLETE"; break
        if st == "REJECTED":
            final_status = "CHECK_FAILED"; rec["reason"] = checker_rec.get("reason"); break
        if st == "CHECKER_NUMERIC_REFUSAL":
            final_status = "NUMERIC_RESOURCE_STOP"; rec["reason"] = checker_rec.get("reason"); continue
        if st == "CHECKER_FAULT":
            final_status = "FAULT"; rec["reason"] = "checker fault: %s" % checker_rec.get("reason"); break
        final_status = "FAULT"; rec["reason"] = "unknown checker status %r" % st; break
    else:
        if final_status is None:
            final_status = "NUMERIC_RESOURCE_STOP"; rec["stop"] = {"phase": "ladder", "kind": "PRECISION_LADDER_EXHAUSTED"}
    rec["attempts"] = attempts; rec["checker"] = checker_rec; rec["status"] = final_status or "FAULT"


def fmt_counts(X):
    out = {}
    for nid, core in X.cores.items():
        if isinstance(nid, int):
            out[core.fmt] = out.get(core.fmt, 0) + 1
    return out


def decode_rows(R, enc):
    orig = {}
    for v in range(R.nvars):
        row = []
        for e in R.dec[v]:
            if e[0] == "C":
                row.append((e[1], e[1]))
            else:
                y, s, eta = e[1], e[2], e[3]; iv = enc[y][R.dom[y].index(s)]
                if iv is None:
                    row.append((Fr(0), Fr(1)))
                else:
                    row.append((eta * iv[0], eta * iv[1]))
        orig[v] = row
    return orig


def task_of(rec, m):
    """The caller's task identity, from the caller's own model / evidence files and the campaign query contract (every original variable)."""
    src = rec["source"]; queries = list(range(m.nvars))
    return {**{k: src[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256")}, "nvars": m.nvars, "orig_card": list(m.card), "queries": queries,
            "queries_sha256": hashlib.sha256(json.dumps(queries).encode()).hexdigest()}


def bound_to_task(chk, task):
    """A checker record is usable only if its task binding equals the caller's task in every field."""
    got = chk.get("task") or {}
    return all(got.get(k) == task[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "nvars", "orig_card", "queries_sha256"))


def run_checker(out, remaining, rec, suffix=""):
    """Separate process; its wall is part of the cell; its RSS is part of the supervised tree. The caller passes ITS model, evidence and
    query contract on the command line; the checker binds the certificate to them. A stale record file is removed before launch and the
    returned record is accepted only if its task binding equals the caller's."""
    outp = os.path.join(out, "checker%s.json" % suffix); remaining = max(0.05, remaining)
    if os.path.exists(outp):
        os.remove(outp)
    cmd = [sys.executable, "-m", "adp.checker", os.path.join(out, "certificate.json"), outp, "%.3f" % remaining, os.path.abspath(rec["model"]), os.path.abspath(rec["evidence"]), "ALL"]
    env = dict(os.environ); env["PYTHONPATH"] = HERE
    with open(os.path.join(out, "checker%s.log" % suffix), "ab") as log:
        try:
            p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE, timeout=remaining + 2.0)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = None
    if os.path.exists(outp):
        r = json.load(open(outp)); r["returncode"] = rc
        if r.get("status") not in ("REJECTED", "CHECKER_INCOMPLETE", "CHECKER_NUMERIC_REFUSAL", "CHECKER_FAULT") and not bound_to_task(r, rec["task"]):
            return {"status": "REJECTED", "reason": "checker record is not bound to the caller's task (model / evidence / query contract)", "returncode": rc}
        return r
    return {"status": "CHECKER_INCOMPLETE", "reason": "checker produced no record (rc=%s)" % rc, "returncode": rc}


def publish(out, m, chk, rec, suffix):
    """Point from the CHECKER's intervals (authoritative) on the exact grid; delivered decimals re-verified exactly here AND by a
    separate checker process that re-parses the MAR file. REFUSES any record not bound to the caller's task."""
    if chk.get("status") != "INTERVALS_OK" or not bound_to_task(chk, rec.get("task") or task_of(rec, m)):
        rec["reason"] = "publication refused: checker record is not an INTERVALS_OK record bound to the caller's task (model, evidence, query contract)"; return "CHECK_FAILED"
    if sorted(int(v) for v in chk["certified_intervals"]) != list(range(m.nvars)) or any(len(chk["certified_intervals"][str(v)]) != m.card[v] for v in range(m.nvars)):
        rec["reason"] = "publication refused: interval rows do not match the caller's variables / cardinalities"; return "CHECK_FAILED"
    ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in chk["certified_intervals"].items()}
    pts, prep = PB.publish_rows(ivs, m.card); rec["publication"] = {k: prep[k] for k in ("grid_bits", "eps", "max_width", "max_width_observed", "width_met", "point_feasible_all_rows", "status")}
    rec["certified"] = {"max_width": prep["max_width_observed"], "max_width_float": float(Fr(prep["max_width_observed"])), "width_met": prep["width_met"], "point_target_met": False, "precision": chk.get("precision")}
    json.dump({"intervals": [{"var": v, "intervals": [[str(a), str(b)] for a, b in prep["widened_intervals"][v]]} for v in range(m.nvars)], "grid": "checker enclosures widened outward to 2^-%d" % prep["grid_bits"], "eps": "1/200"}, open(os.path.join(out, "intervals%s.json" % suffix), "w"))
    if pts is None:
        return prep["status"]
    tmp = os.path.join(out, "output%s.MAR" % suffix); PB.write_mar(tmp, pts, m.card)
    vp = os.path.join(out, "point_check%s.json" % suffix)
    cmd = [sys.executable, "-m", "adp.checker", "--verify-point", os.path.join(out, "checker%s.json" % suffix), tmp, os.path.abspath(rec["model"]), os.path.abspath(rec["evidence"]), vp]
    env = dict(os.environ); env["PYTHONPATH"] = HERE
    with open(os.path.join(out, "point_check%s.log" % suffix), "ab") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=HERE, timeout=600)
    v = json.load(open(vp)) if os.path.exists(vp) else {"status": "POINT_REJECTED", "reason": "no record"}
    rec["point_check"] = v
    if v.get("status") != "POINT_VERIFIED":
        rec["reason"] = "independent point verification: %s" % v.get("reason"); return "CHECK_FAILED"
    import shutil; shutil.copyfile(tmp, os.path.join(out, "output.MAR")); shutil.copyfile(os.path.join(out, "intervals%s.json" % suffix), os.path.join(out, "intervals.json"))
    rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now(); rec["certified"]["point_target_met"] = True
    return "CERTIFIED"


def main():
    mp, ep, out, deadline_s, cfgp = sys.argv[1:6]; deadline = float(deadline_s); os.makedirs(out, exist_ok=True)
    cfg = dict(EN.DEFAULTS); cfg.update(json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp))
    rec = {"arm": ARM, "model": mp, "evidence": ep, "deadline_s": deadline, "config": cfg, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        run_cell(mp, ep, out, deadline, cfg, rec)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-2500:]
    rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline
    if rec["status"] in ("CERTIFIED", "CERTIFIED_TOO_WIDE", "CERTIFIED_WIDTH_ONLY_POINT_INFEASIBLE", "INCONSISTENT_EVIDENCE_CERTIFIED") and not rec["within_deadline"]:
        rec["censored"] = True; rec["status_before_deadline_check"] = rec["status"]; rec["status"] = "LATE_OUTPUT"
    rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str))
    print(json.dumps({"arm": ARM, "status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3)}))


if __name__ == "__main__":
    main()
