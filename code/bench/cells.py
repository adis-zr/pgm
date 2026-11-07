"""One benchmark CELL = one arm on one case in a FRESH process (campaign spec sections 5-6).
    python bench/cells.py ARM MODEL.uai EVID.uai.evid OUT_DIR DEADLINE_S CONFIG.json
Writes OUT_DIR/cell.json (the machine-readable row), OUT_DIR/output.MAR (point vector, UAI MAR layout) when a complete output exists,
OUT_DIR/intervals.json for certified arms, snapshot_<t>s.MAR copies of the latest COMPLETE output at the checkpoints, and logs.
Primary response time = from process start (before imports / parsing) to the complete serialized response incl. verification. Phases are
non-overlapping: startup_imports, parse, convert, plan, solve, verify, serialize. The cell's own deadline is cooperative; the outer supervisor
(bench/campaign.py) enforces the hard wall and the memory budget on the process tree."""
from __future__ import annotations
import os, sys, json, time, shutil, subprocess, threading, hashlib, math, signal
T_START = time.monotonic()
sys.set_int_max_str_digits(0)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from fractions import Fraction as Fr

CHECKPOINTS = {20.0: [1.0, 5.0, 20.0], 120.0: [1.0, 5.0, 20.0, 60.0, 120.0]}
LIBDAI = os.path.join(HERE, "bench", "libdai", "libdai_mar")
MERLIN = "/Users/adis/Workspace/comparators/merlin/build/merlin"
PGMAX_PY = os.path.join(HERE, ".venv-pgmax", "bin", "python")


def now():
    return time.monotonic() - T_START


def atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


class Snapshots:
    """At each checkpoint, copy the latest COMPLETE output (if any) to snapshot_<t>s.MAR and note whether one existed."""
    def __init__(self, out_dir, checkpoints):
        self.out = out_dir; self.cps = checkpoints; self.latest = None; self.latest_t = None; self.log = []; self.lock = threading.Lock(); self.stop = False
        self.th = threading.Thread(target=self.run, daemon=True); self.th.start()
    def publish(self, path):
        with self.lock:
            self.latest = path; self.latest_t = now()
    def run(self):
        for cp in self.cps:
            while now() < cp and not self.stop:
                time.sleep(0.01)
            with self.lock:
                if self.latest and os.path.exists(self.latest):
                    shutil.copyfile(self.latest, os.path.join(self.out, "snapshot_%ds.MAR" % int(cp))); self.log.append({"checkpoint_s": cp, "complete_output": True, "from_t_s": self.latest_t})
                else:
                    self.log.append({"checkpoint_s": cp, "complete_output": False})
    def finish(self):
        self.stop = True


def write_mar_points(path, rows):
    """rows: list over ORIGINAL variables of lists of probabilities (floats or Fractions)."""
    parts = ["MAR", "%d" % len(rows) + " " + " ".join("%d %s" % (len(r), " ".join("%.12g" % float(x) for x in r)) for r in rows)]
    atomic_write(path, "\n".join(parts) + "\n")


def validate_mar(path, card, ev):
    """Shape and normalization validation of a MAR point file (no clipping, no renormalization): returns (rows | None, faults)."""
    from ext import uai as U
    try:
        rows, raw = U.read_mar(path)
    except Exception as ex:
        return None, ["unparseable MAR: %s" % ex]
    faults = []
    if len(rows) != len(card):
        faults.append("row count %d != %d variables" % (len(rows), len(card)))
    for v, r in enumerate(rows[:len(card)]):
        if len(r) != card[v]:
            faults.append("variable %d: %d states != %d" % (v, len(r), card[v])); continue
        if any(x < 0 or x > 1 for x in r):
            faults.append("variable %d: a probability outside [0,1]" % v)
        s = sum(r)
        if abs(float(s) - 1.0) > 1e-5 * max(1, card[v]):
            faults.append("variable %d: row sum %.8f" % (v, float(s)))
        if v in ev and (float(r[ev[v]]) < 1 - 1e-6):
            faults.append("variable %d: observed state %d not a point mass (%.6f)" % (v, ev[v], float(r[ev[v]])))
    return (rows if not faults else None), faults


# ------------------------------------------------------------------ CBI_NATIVE
def cell_cbi(mp, ep, out, deadline, cfg, rec, snaps):
    from ext import uai as U
    from bench import cbi_adapter as AD
    from cbi import api, model as CM
    rec["phases_s"]["startup_imports"] = now(); t = now()
    m = U.read_model(mp); ev = U.read_evidence(ep); rec["phases_s"]["parse"] = now() - t; t = now()
    rec["n_vars"] = m.nvars; rec["n_evidence"] = len(ev); rec["requested_coordinates"] = sum(m.card[v] for v in range(m.nvars) if v not in ev)
    try:
        res = AD.adapt(m, ev)
    except AD.Unsupported as ex:
        rec["phases_s"]["convert"] = now() - t; rec["status"] = "UNSUPPORTED_REPRESENTATION"; rec["reason"] = str(ex); rec["failure_primary"] = "representation: " + str(ex).split(":")[0]; return
    rec["phases_s"]["convert"] = now() - t
    if res[0] == "INFEASIBLE":
        rec["status"] = "INFEASIBLE_ADAPTER"; rec["reason"] = res[1]["reason"]; rec["zero_partition_proof"] = res[1]; rec["output_bytes"] = 0; return
    native, cert = res; rec["adapter"] = {"stats": cert["stats"], "certificate_bytes": len(json.dumps(cert))}
    json.dump(native, open(os.path.join(out, "native_model.json"), "w")); json.dump(cert, open(os.path.join(out, "adapter_certificate.json"), "w"))
    t = now(); remaining = max(0.05, deadline - now() - 0.5)
    limits = dict(cfg.get("cbi_limits") or {}); limits["max_time_s"] = min(limits.get("max_time_s", 120.0), remaining)
    rec["effective_limits"] = {"cbi": limits, "requested_width": cfg.get("width", "1/100")}
    sq = cfg.get("single_query_var")                                   # DIAGNOSTIC probe only (spec section 9): one original variable
    if sq is not None:
        sq = int(sq)
        if str(sq) in cert["fixed"]:
            rec["status"] = "SINGLE_QUERY_VARIABLE_FIXED"; rec["reason"] = "probe variable %d is fixed by evidence / propagation: point mass, no solve" % sq; rec["phases_s"]["solve"] = 0.0; return
        rec["single_query_var"] = sq
    result = api.solve(native, ("all" if sq is None else [sq]), cfg.get("width", "1/100"), limits)
    tot = now() - t; tm = result["timings"]; plan = sum(tm.get(k, 0.0) for k in ("validate", "reduce_hard", "coarsen_propose", "build_systems"))
    rec["phases_s"]["plan"] = plan; rec["phases_s"]["solve"] = tot - plan                      # non-overlapping: plan = validation + reductions + systems; solve = dispatch + numerics + publication
    rec["solve_phases_s"] = tm; rec["cbi_status"] = result["status"]; rec["reason"] = result.get("reason")
    rec["statuses_per_block"] = dict(sorted(collections_counter(result.get("statuses_per_query", {}).values()).items()))
    if result["status"] in ("UNSUPPORTED_INPUT",):
        rec["status"] = "UNSUPPORTED_REPRESENTATION"; rec["failure_primary"] = "native library refused the adapted model: " + str(result.get("reason")); return
    if result["status"] == "INFEASIBLE":
        rec["status"] = "INFEASIBLE_CERTIFIED"; return
    t = now(); ver = api.verify(native, result); rec["phases_s"]["verify"] = now() - t; rec["verify_accepted"] = bool(ver["accepted"]); rec["verify_reasons_tail"] = ver["reasons"][-2:]
    t = now()
    contract = [sq] if sq is not None else [v for v in range(m.nvars) if v not in ev]        # the invocation contract, independent of the producer
    try:
        chk = AD.check_adapter(mp, ep, native, cert, result, expected_queries=contract); rec["adapter_check"] = chk; rec["adapter_check_accepted"] = True
    except (AssertionError, AD.BadCertificate) as ex:
        rec["adapter_check"] = {"error": str(ex)}; rec["adapter_check_accepted"] = False
    try:
        rows = AD.map_intervals(m, ev, cert, result)
    except AD.BadCertificate as ex:
        rec["status"] = "CHECK_FAILED"; rec["reason"] = "publication refused: %s" % ex; rec["phases_s"]["serialize"] = 0.0; return
    iv_out = []; pts = []; wmax = Fr(0); covered = 0
    for v in range(m.nvars):
        r = rows[v]
        if r is None:
            iv_out.append({"var": v, "intervals": None}); pts.append(None); continue
        iv_out.append({"var": v, "intervals": [[str(lo), str(hi)] for lo, hi in r]}); covered += (1 if v not in ev and str(v) not in cert["fixed"] else 0)
        if v in ev or str(v) in cert["fixed"]:
            pts.append([float(lo) for lo, _ in r]); continue
        wmax = max(wmax, max(hi - lo for lo, hi in r))
        mid1 = (r[1][0] + r[1][1]) / 2; pts.append([float(1 - mid1), float(mid1)])      # declared point: midpoint of P(state 1) and its complement
    rec["certified"] = {"max_width": str(wmax), "max_width_float": float(wmax), "width_met": bool(wmax <= Fr(cfg.get("width", "1/100"))), "free_vars_covered": covered, "free_vars_total": len(cert["free"]),
                        "proofs": len(result.get("proofs") or {}), "proof_bytes": len(json.dumps(result.get("proofs") or {}, default=str)), "certificate_pointer_bytes": len(json.dumps(result.get("certificate") or {}, default=str))}
    json.dump({"intervals": iv_out, "grid": "exact rationals; CBI grid 2^-%d" % result["grid_bits"]}, open(os.path.join(out, "intervals.json"), "w"))
    json.dump(result, open(os.path.join(out, "cbi_result.json"), "w"), default=str)
    rec["phases_s"]["serialize_pre"] = now() - t
    if sq is not None:
        pr = result["proofs"].get(result["certificate"].get(str(sq), {}).get("proof"), {}) if result.get("certificate") else {}
        rec["single_query"] = {"var": sq, "status": result["statuses_per_query"].get(str(sq)), "interval_state1": [str(x) for x in rows[sq][1]] if rows.get(sq) else None, "proof_kind": pr.get("kind"), "schedule": pr.get("schedule"), "directed_transfers": pr.get("directed_transfers"), "H": pr.get("H")}
        rec["phases_s"]["serialize"] = rec["phases_s"].pop("serialize_pre"); rec["status"] = (result["statuses_per_query"].get(str(sq)) or result["status"]) + "_SINGLE_QUERY"
        rec["coverage"] = {"variables_covered": 1, "variables_free": len(cert["free"])}; return
    if all(p is not None for p in pts) and rec["verify_accepted"] and rec["adapter_check_accepted"]:
        t = now(); write_mar_points(os.path.join(out, "output.MAR"), pts); snaps.publish(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now()
        rec["phases_s"]["serialize"] = rec["phases_s"].pop("serialize_pre") + (now() - t)
        rec["status"] = "CERTIFIED" if (result["status"] == "CERTIFIED" and rec["certified"]["width_met"]) else ("VALID_BUT_TOO_WIDE" if result["status"] == "VALID_BUT_TOO_WIDE" else "PARTIAL_" + result["status"])
        rec["t_first_verified_width_met_s"] = now() if rec["status"] == "CERTIFIED" else None
        rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR"))
    else:
        rec["phases_s"]["serialize"] = rec["phases_s"].pop("serialize_pre"); rec["status"] = "RESOURCE_LIMIT" if result["status"] == "RESOURCE_LIMIT" else ("CHECK_FAILED" if not (rec["verify_accepted"] and rec["adapter_check_accepted"]) else "PARTIAL")
        rec["coverage"] = {"blocks_with_intervals": len(result.get("intervals") or {}), "blocks_requested": len(result.get("requested_queries") or [])}


def collections_counter(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return out


# ------------------------------------------------------------------ MDI_EXISTING (pinned accepted engine; selector policy)
def cell_mdi_single(mp, ep, out, deadline, cfg, rec, snaps, var):
    """GENUINE native single-query interface of the engine: mdi.pipeline.solve(queries={var}) with the selector policy (the arm wrapper
    mdi.arm.run_arm fixes queries = all free variables, so this diagnostic calls the pipeline directly and records that difference)."""
    from mdi import model as MM, pipeline as PLN, config as K
    rec["phases_s"]["startup_imports"] = now(); t = now()
    m = MM.read_uai(mp); ev = MM.read_evidence(ep, m); r = MM.restrict(m, ev); rec["phases_s"]["parse"] = now() - t
    rec["single_query_var"] = var; rec["query_interface"] = "native: mdi.pipeline.solve(queries={var}); wrapper differs from run_arm (no arm record / receipt files)"
    if var in ev:
        rec["status"] = "SINGLE_QUERY_VARIABLE_OBSERVED"; rec["reason"] = "probe variable is observed"; return
    wall = max(0.1, deadline - now() - 0.3); t = now()
    res = PLN.solve(m, ev, queries={var}, max_width=Fr(cfg.get("width", "1/100")), wall_s=wall, cap_bytes=8 * (1 << 30), research_enabled=False, route_policy="selector", plan_dir=os.path.join(out, "plans_single"))
    rec["phases_s"]["solve"] = now() - t; rec["mdi_outcome"] = res.status; rec["reason"] = res.reason; rec["mdi_stages"] = res.stages
    pl = res.plan if isinstance(res.plan, dict) else {}; rec["route"] = {"chosen": pl.get("chosen"), "executed_kind": pl.get("executed_kind"), "selector_executed_route": ((pl.get("selector") or {}).get("executed_route") if isinstance(pl.get("selector"), dict) else None)}
    rec["effective_limits"] = {"wall_s": wall, "cap_bytes": 8 * (1 << 30), "width": str(Fr(cfg.get("width", "1/100")))}
    if res.status in ("CERTIFIED_RESEARCH_ROUTE", "CERTIFIED_FALLBACK_ONLY") and res.intervals and var in res.intervals:
        t = now(); rows = res.intervals[var]; w = max(Fr(hi) - Fr(lo) for lo, hi in rows)
        rec["single_query"] = {"var": var, "intervals": [[str(lo), str(hi)] for lo, hi in rows], "max_width": str(w), "width_met": bool(w <= Fr(cfg.get("width", "1/100"))), "independently_verified": bool(res.properties.get("independently_verified"))}
        json.dump({"var": var, "intervals": [[str(lo), str(hi)] for lo, hi in rows]}, open(os.path.join(out, "single_query_intervals.json"), "w"))
        rec["status"] = ("CERTIFIED" if rec["single_query"]["width_met"] else "VALID_BUT_TOO_WIDE") + "_SINGLE_QUERY"; rec["t_first_verified_width_met_s"] = now() if rec["single_query"]["width_met"] else None; rec["phases_s"]["serialize"] = now() - t
    elif res.status == "ZERO_EVIDENCE_PROVED":
        rec["status"] = "INFEASIBLE_CERTIFIED"
    else:
        rec["status"] = {"RESOURCE_STOP": "RESOURCE_LIMIT", "PRICE_REFUSAL": "RESOURCE_LIMIT", "NUMERICAL_REFUSAL": "ENGINE_REFUSED_PREPROCESSING"}.get(res.status, "UNSUPPORTED_" + str(res.status)); rec["failure_primary"] = str(res.status) + ": " + str(res.reason)[:200]


def cell_mdi(mp, ep, out, deadline, cfg, rec, snaps):
    if cfg.get("single_query_var") is not None:
        return cell_mdi_single(mp, ep, out, deadline, cfg, rec, snaps, int(cfg["single_query_var"]))
    from mdi import arm as ARM, config as K
    rec["phases_s"]["startup_imports"] = now()
    wall = max(0.1, deadline - now() - 0.3); label = "case"
    rr = ARM.run_arm(label, False, out, eps=Fr(cfg.get("width", "1/100")), wall=wall, cap=8 * (1 << 30), model_path=mp, evid_path=ep, selector=True)
    st = rr.get("stages") or {}
    rec["phases_s"]["parse"] = st.get("parse_s"); rec["phases_s"]["solve"] = st.get("pipeline_s"); rec["mdi_outcome"] = rr.get("outcome"); rec["reason"] = rr.get("reason")
    rec["route"] = ((rr.get("pipeline") or {}).get("plan") or {}).get("selected") if isinstance((rr.get("pipeline") or {}).get("plan"), dict) else (rr.get("pipeline") or {}).get("plan")
    rec["effective_limits"] = {"wall_s": wall, "cap_bytes": 8 * (1 << 30), "engine_frozen_resources": dict(K.RESOURCES), "width": str(Fr(cfg.get("width", "1/100")))}
    rec["independently_verified"] = rr.get("independently_verified"); rec["producer_complete"] = rr.get("producer_complete")
    rec["mdi_record"] = "arm_%s_selector.json" % label
    ivp = os.path.join(out, "intervals_%s_selector.json" % label); ptp = os.path.join(out, "points_%s_selector.json" % label)
    if rr.get("outcome") in ("CERTIFIED_RESEARCH_ROUTE", "CERTIFIED_FALLBACK_ONLY") and os.path.exists(ivp):
        t = now(); iv = json.load(open(ivp)); shutil.copyfile(ivp, os.path.join(out, "intervals.json"))
        wmax = max(Fr(hi) - Fr(lo) for row in iv for lo, hi in row["intervals"]); rec["certified"] = {"max_width": str(wmax), "max_width_float": float(wmax), "width_met": bool(rr.get("contract_met"))}
        pts = None; pm = os.path.join(out, "point_%s_selector.MAR" % label)
        if os.path.exists(pm):                                   # the arm's own declared, re-verified coherent point vector (UAI MAR layout)
            from ext import uai as U2
            pts = [[float(x) for x in r] for r in U2.read_mar(pm)[0]]
        for cand in (() if pts else (ptp, os.path.join(out, "point_%s_selector.json" % label))):
            if os.path.exists(cand):
                pj = json.load(open(cand)); pts = pj.get("rows") or pj.get("points") or pj; break
        if pts is None:                                   # declared feasible point from the arm's own helper
            pts = []
            for row in iv:
                fp = ARM._feasible_simplex_point([(Fr(lo), Fr(hi)) for lo, hi in row["intervals"]]); pts.append([float(x) for x in fp] if fp else None)
        if isinstance(pts, dict):
            pts = [pts[str(v)] if str(v) in pts else pts[v] for v in range(len(iv))]
        if isinstance(pts, list) and pts and isinstance(pts[0], dict):
            pts = [p.get("point") or p.get("probabilities") or p.get("row") for p in pts]
        if pts and all(p is not None for p in pts):
            write_mar_points(os.path.join(out, "output.MAR"), pts); snaps.publish(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now()
            rec["t_first_verified_width_met_s"] = now() if rr.get("contract_met") else None; rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR"))
            rec["status"] = "CERTIFIED" if rr.get("contract_met") else "VALID_BUT_TOO_WIDE"
        else:
            rec["status"] = "CHECK_FAILED"; rec["reason"] = "no coherent point vector inside the certified intervals"
        rec["phases_s"]["serialize"] = now() - t
    elif rr.get("outcome") == "ZERO_EVIDENCE_PROVED":
        rec["status"] = "INFEASIBLE_CERTIFIED"
    elif rr.get("outcome") in ("RESOURCE_STOP",):
        rec["status"] = "RESOURCE_LIMIT"; rec["failure_primary"] = "engine admission / resource stop: " + str(rr.get("reason"))[:200]
    else:
        rec["status"] = {"PRICE_REFUSAL": "RESOURCE_LIMIT", "NUMERICAL_REFUSAL": "CHECK_FAILED", "IMPLEMENTATION_INCOMPLETE": "FAULT", "GUARD_VIOLATION": "FAULT"}.get(rr.get("outcome"), "UNSUPPORTED_" + str(rr.get("outcome")))
        rec["failure_primary"] = str(rr.get("outcome")) + ": " + str(rr.get("reason"))[:200]
    rec["peak_rss_bytes_arm"] = rr.get("peak_rss_bytes")


# ------------------------------------------------------------------ external arms
def extract_single(out, rec, cfg, card):
    """FAMILY C for arms without a native single-variable interface: the complete MAR output is produced by the same algorithm and the
    requested variable's row is extracted afterwards; the ENTIRE cost is the cell's; labelled as such."""
    var = cfg.get("single_query_var")
    if var is None or not os.path.exists(os.path.join(out, "output.MAR")):
        return
    from ext import uai as U
    t = now(); rows, _ = U.read_mar(os.path.join(out, "output.MAR")); var = int(var)
    rec["single_query_var"] = var; rec["query_interface"] = "complete MAR followed by extraction (no native single-query path in this arm's interface); entire cost charged"
    rec["single_query"] = {"var": var, "row": [str(x) for x in rows[var]] if var < len(rows) else None}; rec["phases_s"]["extract_single"] = now() - t
    json.dump(rec["single_query"], open(os.path.join(out, "single_query_row.json"), "w"))


def _run(cmd, out, name, timeout, env=None):
    t = now(); log = open(os.path.join(out, name + ".log"), "ab")
    e = dict(os.environ); e.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"}); e.update(env or {})
    try:
        p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=max(0.05, timeout), env=e, cwd=out)
        rc = p.returncode; to = False
    except subprocess.TimeoutExpired:
        rc = None; to = True
    log.close()
    return {"cmd": cmd, "returncode": rc, "timed_out": to, "wall_s": now() - t, "started_at_s": t}


def cell_libdai(mp, ep, out, deadline, cfg, rec, snaps, alg_template):
    from ext import uai as U
    rec["phases_s"]["startup_imports"] = now(); card = U.read_model(mp).card; ev = U.read_evidence(ep)
    remaining = deadline - now() - 0.3
    alg = alg_template.replace("{maxtime}", "%.3f" % max(0.1, remaining - 0.5))
    rec["effective_limits"] = {"algorithm": alg, "cooperative_maxtime_s": (max(0.1, remaining - 0.5) if "{maxtime}" in alg_template else None), "maxmem_bytes": (8 << 30) if "maxmem" in alg else None}
    rec["progress_hooks"] = "none: the libDAI driver writes its output once at the end (BP maxtime makes a timeout return the current beliefs, flagged unconverged); a kill before that leaves no partial output -- recorded as not instrumented"
    r = _run([LIBDAI, mp, ep, os.path.join(out, "output.MAR.tmp"), os.path.join(out, "side.json"), alg], out, "libdai", remaining)
    rec["runs"] = [r]
    if r["returncode"] == 0 and os.path.exists(os.path.join(out, "output.MAR.tmp")):
        os.replace(os.path.join(out, "output.MAR.tmp"), os.path.join(out, "output.MAR")); snaps.publish(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now()
        side = json.load(open(os.path.join(out, "side.json"))); rec["solver_side"] = side; rec["phases_s"].update({"parse": side["phases_s"]["parse"], "convert": side["phases_s"]["clamp_build"], "plan": side["phases_s"]["construct"], "solve": side["phases_s"]["run"], "serialize": side["phases_s"]["serialize"]})
        rows, faults = validate_mar(os.path.join(out, "output.MAR"), card, ev); rec["output_faults"] = faults; rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR"))
        rec["status"] = ("COMPLETE" if side.get("converged", True) else "COMPLETE_UNCONVERGED") if rows is not None else "INVALID_OUTPUT"
        extract_single(out, rec, cfg, card)
        if "JTREE" in alg:
            rec["reference_class_candidate"] = "R1 (exact algorithm, binary64)"
    elif r["timed_out"]:
        rec["status"] = "TIMEOUT"; rec["censored"] = True
    elif r["returncode"] == 5:
        rec["status"] = "INFEASIBLE_EVIDENCE"; rec["reason"] = (json.load(open(os.path.join(out, "side.json"))).get("reason") if os.path.exists(os.path.join(out, "side.json")) else "zero partition"); rec["output_bytes"] = 0
    else:
        tail = open(os.path.join(out, "libdai.log"), errors="replace").read()[-600:]; rec["status"] = "FAILED"; rec["reason"] = tail
        if "maxmem" in tail.lower() or "exceed" in tail.lower() or "memory" in tail.lower():
            rec["status"] = "ADMISSION_REFUSED"; rec["failure_primary"] = "libDAI junction tree exceeds the maxmem admission (internal forecast, not actual exhaustion)"


def cell_merlin_ladder(mp, ep, out, deadline, cfg, rec, snaps, algorithm, ladder, iterations):
    """Predeclared increasing-capacity ladder of i-bounds (Merlin i-bound = number of VARIABLES in a mini-bucket); each step a fresh
    restart charged in full; the latest COMPLETE valid output is retained; a step is admitted only if the remaining time is >= 1 s."""
    from ext import uai as U
    rec["phases_s"]["startup_imports"] = now(); card = U.read_model(mp).card; ev = U.read_evidence(ep); rec["runs"] = []; last = None
    rec["effective_limits"] = {"algorithm": algorithm, "ibound_ladder": ladder, "ibound_counts": "variables per mini-bucket", "iterations": iterations, "time_per_step": "remaining cell allowance"}
    for ib in ladder:
        remaining = deadline - now() - 0.3
        if remaining < 1.0:
            rec["runs"].append({"ibound": ib, "status": "NOT_STARTED_INSUFFICIENT_TIME", "remaining_s": remaining}); break
        pref = os.path.join(out, "step_i%d" % ib)
        cmd = [MERLIN, "--input-file", mp, "--evidence-file", ep, "--task", "MAR", "--algorithm", algorithm, "--ibound", str(ib), "--iterations", str(iterations), "--output-format", "uai", "--output-file", pref]
        r = _run(cmd, out, "merlin_i%d" % ib, remaining); r["ibound"] = ib
        produced = [f for f in os.listdir(out) if f.startswith("step_i%d" % ib) and f.endswith(".MAR")]
        if r["returncode"] == 0 and produced:
            rows, faults = validate_mar(os.path.join(out, produced[0]), card, ev); r["output_faults"] = faults
            log = open(os.path.join(out, "merlin_i%d.log" % ib), errors="replace").read(); r["exact_by_ibound"] = ("exact inference  : Yes" in log)
            if rows is not None:
                shutil.copyfile(os.path.join(out, produced[0]), os.path.join(out, "output.MAR")); snaps.publish(os.path.join(out, "output.MAR")); last = ib
                rec.setdefault("t_first_complete_output_s", now()); r["status"] = "COMPLETE"
            else:
                r["status"] = "INVALID_OUTPUT"
        elif r["timed_out"]:
            r["status"] = "TIMEOUT"
        else:
            r["status"] = "FAILED"
        rec["runs"].append(r)
        if r["status"] in ("TIMEOUT", "FAILED"):
            break
        if r.get("exact_by_ibound"):
            break                                                    # the ladder is exhausted once the bound makes inference exact
    if last is not None:
        rec["status"] = "COMPLETE"; rec["final_ibound"] = last; rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); extract_single(out, rec, cfg, card)
        rec["exact_by_ibound"] = any(r.get("exact_by_ibound") for r in rec["runs"] if r.get("ibound") == last)
        if rec["exact_by_ibound"]:
            rec["reference_class_candidate"] = "R1 (mini-bucket bound >= induced width: exact elimination, binary64)"
    elif any(r.get("status") == "TIMEOUT" for r in rec["runs"]):
        rec["status"] = "TIMEOUT"; rec["censored"] = True
    else:
        rec["status"] = "FAILED"; rec["reason"] = open(os.path.join(out, "merlin_i%d.log" % ladder[0]), errors="replace").read()[-500:] if os.path.exists(os.path.join(out, "merlin_i%d.log" % ladder[0])) else "no step ran"


def cell_merlin_single(mp, ep, out, deadline, cfg, rec, snaps, algorithm, extra):
    from ext import uai as U
    rec["phases_s"]["startup_imports"] = now(); card = U.read_model(mp).card; ev = U.read_evidence(ep); remaining = deadline - now() - 0.3
    pref = os.path.join(out, "merlin_" + algorithm)
    cmd = [MERLIN, "--input-file", mp, "--evidence-file", ep, "--task", "MAR", "--algorithm", algorithm, "--output-format", "uai", "--output-file", pref] + extra
    rec["effective_limits"] = {"algorithm": algorithm, "extra": extra}
    r = _run(cmd, out, "merlin_" + algorithm, remaining); rec["runs"] = [r]
    produced = [f for f in os.listdir(out) if f.startswith("merlin_" + algorithm) and f.endswith(".MAR")]
    if r["returncode"] == 0 and produced:
        rows, faults = validate_mar(os.path.join(out, produced[0]), card, ev); rec["output_faults"] = faults
        if rows is not None:
            shutil.copyfile(os.path.join(out, produced[0]), os.path.join(out, "output.MAR")); snaps.publish(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now(); rec["status"] = "COMPLETE"; rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR"))
        else:
            rec["status"] = "INVALID_OUTPUT"
    elif r["timed_out"]:
        rec["status"] = "TIMEOUT"; rec["censored"] = True
    else:
        rec["status"] = "FAILED"; rec["reason"] = open(os.path.join(out, "merlin_%s.log" % algorithm), errors="replace").read()[-500:]


def cell_pgmax(mp, ep, out, deadline, cfg, rec, snaps):
    from ext import uai as U
    rec["phases_s"]["startup_imports"] = now(); card = U.read_model(mp).card; ev = U.read_evidence(ep); remaining = deadline - now() - 0.3
    rec["effective_limits"] = {"temperature": 1.0, "num_iters": cfg.get("pgmax_iters", 200), "damping": cfg.get("pgmax_damping", 0.5), "device": "cpu", "dtype": "float32 (JAX default; x64 disabled)", "threads": "XLA intra-op 1 (best effort)"}
    cmd = [PGMAX_PY, os.path.join(HERE, "bench", "pgmax_mar.py"), mp, ep, os.path.join(out, "output.MAR.tmp"), os.path.join(out, "side.json"), str(cfg.get("pgmax_iters", 200)), str(cfg.get("pgmax_damping", 0.5))]
    r = _run(cmd, out, "pgmax", remaining, env={"XLA_FLAGS": "--xla_cpu_multi_thread_eigen=false intra_op_parallelism_threads=1", "JAX_PLATFORMS": "cpu", "TF_CPP_MIN_LOG_LEVEL": "3"}); rec["runs"] = [r]
    if r["returncode"] == 0 and os.path.exists(os.path.join(out, "output.MAR.tmp")):
        os.replace(os.path.join(out, "output.MAR.tmp"), os.path.join(out, "output.MAR")); snaps.publish(os.path.join(out, "output.MAR")); rec["t_first_complete_output_s"] = now()
        side = json.load(open(os.path.join(out, "side.json"))); rec["solver_side"] = side; rec["phases_s"].update(side.get("phases_s", {}))
        rows, faults = validate_mar(os.path.join(out, "output.MAR"), card, ev); rec["output_faults"] = faults; rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR"))
        rec["status"] = "COMPLETE" if rows is not None else "INVALID_OUTPUT"; extract_single(out, rec, cfg, card)
    elif r["timed_out"]:
        rec["status"] = "TIMEOUT"; rec["censored"] = True
    else:
        tail = open(os.path.join(out, "pgmax.log"), errors="replace").read()[-800:]; rec["status"] = "FAILED"; rec["reason"] = tail
        if "unsupported" in tail.lower():
            rec["status"] = "UNSUPPORTED_REPRESENTATION"


ARMS = {
    "CBI_NATIVE": cell_cbi,
    "MDI_EXISTING": cell_mdi,
    "LBP": lambda *a: cell_libdai(*a, alg_template="BP[inference=SUMPROD,updates=SEQMAX,logdomain=0,tol=1e-9,maxiter=10000,damping=0.0,maxtime={maxtime}]"),
    "EXACT": lambda *a: cell_libdai(*a, alg_template="JTREE[inference=SUMPROD,updates=HUGIN,maxmem=8589934592]"),
    "WMB": lambda *a: cell_merlin_ladder(*a, algorithm="wmb", ladder=[2, 4, 6, 8, 10, 12, 16, 20], iterations=100),
    "IJGP": lambda *a: cell_merlin_ladder(*a, algorithm="ijgp", ladder=[2, 4, 6, 8, 10, 12, 16, 20], iterations=100),
    "SAMPLESEARCH": None,                                   # UNAVAILABLE (see AVAILABILITY.json); never launched
    "PGMAX_SUMPRODUCT_BP": cell_pgmax,
}


def main():
    arm, mp, ep, out, deadline_s, cfgp = sys.argv[1:7]; deadline = float(deadline_s); cfg = json.load(open(cfgp)) if os.path.exists(cfgp) else json.loads(cfgp)
    os.makedirs(out, exist_ok=True)
    rec = {"arm": arm, "model": mp, "evidence": ep, "deadline_s": deadline, "phases_s": {}, "status": None, "pid": os.getpid(), "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    snaps = Snapshots(out, CHECKPOINTS.get(deadline, [1.0, 5.0, deadline]))
    # PROGRESS HOOK (diagnostic campaign, 7 Nov 2026): every 0.5 s the partial record is flushed atomically to progress.json so a supervisor kill
    # leaves the last known phase; numerical algorithms, settings and stopping rules are untouched (overhead measured on the fixed controls)
    def _flush():
        while not snaps.stop:
            try:
                atomic_write(os.path.join(out, "progress.json"), json.dumps({"t_s": now(), "phases_s": rec.get("phases_s"), "status": rec.get("status"), "runs": len(rec.get("runs") or [])}, default=str))
            except Exception:
                pass
            time.sleep(0.5)
    threading.Thread(target=_flush, daemon=True).start()
    try:
        fn = ARMS.get(arm)
        if fn is None:
            rec["status"] = "UNAVAILABLE"; rec["reason"] = "arm has no runnable implementation in this campaign"
        else:
            fn(mp, ep, out, deadline, cfg, rec, snaps)
    except Exception as ex:
        import traceback
        rec["status"] = "FAULT"; rec["reason"] = "%s: %s" % (type(ex).__name__, ex); rec["traceback"] = traceback.format_exc()[-1500:]
    snaps.finish(); time.sleep(0.02)
    rec["snapshots"] = snaps.log; rec["complete_response_s"] = now(); rec["within_deadline"] = rec["complete_response_s"] <= deadline
    if rec["status"] in ("CERTIFIED", "VALID_BUT_TOO_WIDE", "COMPLETE", "COMPLETE_UNCONVERGED") and not rec["within_deadline"]:
        rec["censored"] = True; rec["status_before_deadline_check"] = rec["status"]; rec["status"] = "LATE_OUTPUT"
    try:
        import resource; rec["maxrss_self_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; rec["maxrss_children_bytes"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    except Exception:
        pass
    atomic_write(os.path.join(out, "cell.json"), json.dumps(rec, indent=1, default=str))
    print(json.dumps({"arm": arm, "status": rec["status"], "complete_response_s": round(rec["complete_response_s"], 3)}))


if __name__ == "__main__":
    main()
