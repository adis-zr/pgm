"""Pilot campaign driver (CLAUDE_CODE_SPEC.md "Stages, time limits, and stop rules").

    python -m dq.campaign --run-dir runs/dq_pilot_<tag> [--skip-timed]

Stage 1: tiny validation (pytest tests/test_dq_small.py, <= 60 s) and input-only gates (MAIN must admit, CONTROL must decline).
Stage 2: one MAIN pair D then F (complete checked arms, 90 s each); D must verify within 30 s (absolute screen).
Stage 3: two more MAIN pairs in orders F,D and D,F.
Stage 4: three CONTROL pairs: plain F vs gate-then-F (automatic fallback), orders F,auto / auto,F / F,auto.
Total post-build cap 1,200 s (incl. reporting <= 60 s); 4 GiB RSS per worker tree; one worker at a time.
Eligibility per cell: no foreign process >= 50 % of a core for 5 consecutive seconds; numerical-phase (native subcall) CPU/wall >= 0.90.
Durable: events.jsonl, resources.jsonl (heartbeats), attempts.jsonl, per-arm result/witness JSON, environment lock, source hashes."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

sys.set_int_max_str_digits(0)
import psutil

from dq.supervisor import Journal, ContentionMonitor, now_iso
from dq.arms import run_arm
from dq.model import Model
from dq.gate import response_gate, weighted_count_state_estimate, log_weight_perturbation_bound

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TOTAL_CAP_S = 1200.0; ARM_CAP_S = 90.0; D_SCREEN_S = 30.0; RSS_CAP = 4 << 30; N = 32768
ANALYTIC = {"main_query_range": ["0.5216", "0.7733"], "residual_only_minus_full_lower": "0.0236", "source": "docs/direct-query-theory-pass-2026-10-26/witness_response.md section 5 (analytical; not re-evaluated here)"}


def sha_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def environment():
    import gmpy2
    return {"at": now_iso(), "host": platform.node(), "platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count(), "mem_total": psutil.virtual_memory().total,
            "python": sys.version, "gmpy2": gmpy2.version(), "mpfr": gmpy2.mpfr_version(), "gmp": gmpy2.mp_version(), "psutil": psutil.__version__,
            "compiler": subprocess.run(["c++", "--version"], capture_output=True, text=True).stdout.splitlines()[0], "load_avg": os.getloadavg(),
            "git_head": subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(), "git_dirty": bool(subprocess.run(["git", "-C", ROOT, "status", "--porcelain"], capture_output=True, text=True).stdout.strip())}


def source_hashes():
    out = {}
    for g in ("dq/*.py", "native/*.cpp", "native/*.hpp", "tests/*.py", "build/dqchain", "build/dqcheck"):
        for p in sorted(glob.glob(os.path.join(ROOT, g))):
            out[os.path.relpath(p, ROOT)] = sha_file(p)
    return out


class Campaign:
    def __init__(self, run_dir):
        self.run_dir = run_dir; os.makedirs(run_dir, exist_ok=True)
        self.events = Journal(os.path.join(run_dir, "events.jsonl")); self.resources = Journal(os.path.join(run_dir, "resources.jsonl")); self.attempts = Journal(os.path.join(run_dir, "attempts.jsonl"))
        self.t0 = time.monotonic(); self.state = {"stages": {}, "cells": [], "stops": []}
    def elapsed(self): return time.monotonic() - self.t0
    def remaining(self): return TOTAL_CAP_S - self.elapsed()
    def save(self):
        p = os.path.join(self.run_dir, "campaign_state.json"); tmp = p + ".tmp"
        with open(tmp, "w") as f: json.dump(self.state, f, indent=1, default=str); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)
    def stop(self, reason, **k):
        self.state["stops"].append({"reason": reason, "elapsed_s": self.elapsed(), **k}); self.events.write({"kind": "stop", "reason": reason, **k}); self.save()

    def cell(self, tag: str, arm: str, case: str, order_idx: int, pair: str, mode: str = "standalone"):
        """One timed cell = one standalone arm (fresh process-level accounting inside run_arm) under contention monitoring."""
        if self.remaining() < 5: self.stop("TOTAL_CAP_REACHED_BEFORE_CELL", cell=tag); return None
        cdir = os.path.join(self.run_dir, "cells", tag); os.makedirs(cdir, exist_ok=True)
        mon = ContentionMonitor(self.resources); mon.start(); time.sleep(1.2)
        load0 = os.getloadavg()
        self.events.write({"kind": "cell_start", "cell": tag, "arm": arm, "case": case, "pair": pair, "order_idx": order_idx, "load_avg": load0})
        R = run_arm(arm, case, N, cdir, deadline_s=min(ARM_CAP_S, max(1.0, self.remaining() - 65.0)), rss_cap=RSS_CAP, monitor=mon, pair_tag=pair)
        c = mon.finish()
        # numerical-phase CPU/wall over the native subcalls (producer + checker kernels)
        num = [a for a in R["attempts"] if a.get("kind") == "producer"] + [a["kernel"] for a in R["attempts"] if a.get("kind") == "checker" and a.get("kernel")]
        cpu = sum(a.get("cpu_s") or 0 for a in num); wall = sum(a.get("wall_s") or 0 for a in num)
        ratio = cpu / wall if wall > 0 else None
        elig = {"foreign_cpu_violations": c["violations"], "contention_samples": c["samples"], "numerical_phase_cpu_s": cpu, "numerical_phase_wall_s": wall, "numerical_phase_cpu_over_wall": ratio,
                "eligible": (not c["violations"]) and (ratio is not None and ratio >= 0.90), "reasons": ([f"foreign process >=50% CPU for 5 s: {[v['name'] for v in c['violations']]}"] if c["violations"] else []) + ([f"numerical-phase CPU/wall {ratio:.3f} < 0.90"] if (ratio is None or ratio < 0.90) else [])}
        row = {"cell": tag, "arm": arm, "case": case, "pair": pair, "order_idx": order_idx, "mode": mode, "status": R["status"], "guarantee": R.get("guarantee"), "width": R.get("width"), "width_ok": R.get("width_ok"), "published": R.get("published"),
               "complete_wall_s": R["complete_wall_s"], "phases": R["phases"], "attempts": R["attempts"], "residual_overhead_s": R["residual_overhead_s"], "peak_rss_bytes": max([a.get("peak_rss_bytes") or 0 for a in R["attempts"] if a.get("kind") == "producer"] + [(a.get("kernel") or {}).get("peak_rss_bytes") or 0 for a in R["attempts"] if a.get("kind") == "checker"] + [0]),
               "eligibility": elig, "load_before": load0, "load_after": os.getloadavg(), "result_path": os.path.relpath(os.path.join(cdir, "result.json"), self.run_dir), "declined_reason": R.get("declined_reason")}
        self.state["cells"].append(row); self.attempts.write({"kind": "cell", **{k: v for k, v in row.items() if k not in ("phases", "attempts", "published")}}); self.save()
        self.events.write({"kind": "cell_end", "cell": tag, "status": R["status"], "complete_wall_s": R["complete_wall_s"], "eligible": elig["eligible"]})
        print(f"  {tag}: {R['status']} width={R.get('width') and float(__import__('fractions').Fraction(R['width'])):} complete={R['complete_wall_s']:.2f}s eligible={elig['eligible']} {elig['reasons']}", flush=True)
        return row

    def auto_cell(self, tag, order_idx, pair):
        """CONTROL automatic arm: gate (declines) then fallback F, charged together as one complete cell; fallback reuses the gate's input bytes."""
        if self.remaining() < 5: self.stop("TOTAL_CAP_REACHED_BEFORE_CELL", cell=tag); return None
        cdir = os.path.join(self.run_dir, "cells", tag); os.makedirs(cdir, exist_ok=True)
        mon = ContentionMonitor(self.resources); mon.start(); time.sleep(1.2); load0 = os.getloadavg(); t0 = time.monotonic()
        self.events.write({"kind": "cell_start", "cell": tag, "arm": "AUTO", "case": "CONTROL", "pair": pair, "order_idx": order_idx})
        RD = run_arm("D", "CONTROL", N, os.path.join(cdir, "gate"), deadline_s=min(ARM_CAP_S, max(1.0, self.remaining() - 65.0)), rss_cap=RSS_CAP, monitor=mon, pair_tag=pair)
        gate_wall = RD["complete_wall_s"]
        if RD["status"] != "CERTIFICATE_DECLINED":
            c = mon.finish(); row = {"cell": tag, "arm": "AUTO", "case": "CONTROL", "pair": pair, "order_idx": order_idx, "status": "GATE_DID_NOT_DECLINE:" + RD["status"], "complete_wall_s": time.monotonic() - t0, "eligibility": {"eligible": False, "reasons": ["gate mismatch"]}}
            self.state["cells"].append(row); self.save(); self.stop("CONTROL_GATE_DID_NOT_DECLINE"); return row
        remaining_arm = max(1.0, min(ARM_CAP_S - gate_wall, self.remaining() - 65.0))
        RF = run_arm("F", "CONTROL", N, os.path.join(cdir, "fallback"), deadline_s=remaining_arm, rss_cap=RSS_CAP, monitor=mon, pair_tag=pair, reuse_input=os.path.join(cdir, "gate", "input.txt"))
        c = mon.finish(); total = time.monotonic() - t0
        num = [a for a in RF["attempts"] if a.get("kind") == "producer"] + [a["kernel"] for a in RF["attempts"] if a.get("kind") == "checker" and a.get("kernel")]
        cpu = sum(a.get("cpu_s") or 0 for a in num); wall = sum(a.get("wall_s") or 0 for a in num); ratio = cpu / wall if wall > 0 else None
        elig = {"foreign_cpu_violations": c["violations"], "contention_samples": c["samples"], "numerical_phase_cpu_s": cpu, "numerical_phase_wall_s": wall, "numerical_phase_cpu_over_wall": ratio, "eligible": (not c["violations"]) and (ratio is not None and ratio >= 0.90),
                "reasons": ([f"foreign process >=50% CPU for 5 s: {[v['name'] for v in c['violations']]}"] if c["violations"] else []) + ([f"numerical-phase CPU/wall {ratio:.3f} < 0.90"] if (ratio is None or ratio < 0.90) else [])}
        row = {"cell": tag, "arm": "AUTO", "case": "CONTROL", "pair": pair, "order_idx": order_idx, "mode": "gate_then_fallback", "status": RF["status"], "guarantee": RF.get("guarantee"), "width": RF.get("width"), "width_ok": RF.get("width_ok"), "published": RF.get("published"),
               "gate_wall_s": gate_wall, "gate_phases": RD["phases"], "gate_declined_reason": RD.get("declined_reason"), "fallback_wall_s": RF["complete_wall_s"], "fallback_phases": RF["phases"], "fallback_attempts": RF["attempts"], "fallback_reused_input": True,
               "complete_wall_s": total, "residual_overhead_s": total - gate_wall - RF["complete_wall_s"], "attempts": RF["attempts"], "phases": RD["phases"] + RF["phases"],
               "peak_rss_bytes": max([a.get("peak_rss_bytes") or 0 for a in RF["attempts"] if a.get("kind") == "producer"] + [0]), "eligibility": elig, "load_before": load0, "load_after": os.getloadavg(), "result_path": os.path.relpath(cdir, self.run_dir)}
        self.state["cells"].append(row); self.attempts.write({"kind": "cell", **{k: v for k, v in row.items() if k not in ("phases", "attempts", "published", "gate_phases", "fallback_phases", "fallback_attempts")}}); self.save()
        print(f"  {tag}: gate {RD['status']} in {gate_wall:.2f}s -> fallback {RF['status']} width={RF.get('width') and float(__import__('fractions').Fraction(RF['width']))} complete={total:.2f}s eligible={elig['eligible']} {elig['reasons']}", flush=True)
        return row


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", required=True); ap.add_argument("--skip-timed", action="store_true"); a = ap.parse_args(argv)
    C = Campaign(a.run_dir); rd = a.run_dir
    env = environment(); src = source_hashes()
    json.dump({"environment": env, "sources": src, "frozen": {"n": N, "arm_cap_s": ARM_CAP_S, "d_screen_s": D_SCREEN_S, "total_cap_s": TOTAL_CAP_S, "rss_cap_bytes": RSS_CAP, "steps": 17, "step": "2/5", "grid_MAIN": {"h": "1", "J": 3, "delta": "113/100000"}, "grid_CONTROL": {"h": "3/4", "J": 4, "delta": "1/1400"}, "fbits_ladder": [80, 128], "check_ladder": [128, 192]},
               "spec_sha256": {"CLAUDE_CODE_SPEC.md": sha_file(os.path.join(ROOT, "..", "docs", "direct-query-theory-pass-2026-10-26", "CLAUDE_CODE_SPEC.md")), "AUDIT.md": sha_file(os.path.join(ROOT, "..", "docs", "direct-query-theory-pass-2026-10-26", "AUDIT.md"))}, "analytic_facts_recorded": ANALYTIC},
              open(os.path.join(rd, "lock.json"), "w"), indent=1, default=str)
    C.events.write({"kind": "campaign_start", "git_head": env["git_head"], "git_dirty": env["git_dirty"], "load_avg": env["load_avg"]})
    # ---------------- Stage 1: tiny validation + input-only gates
    t = time.monotonic()
    r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(ROOT, "tests", "test_dq_small.py")], cwd=ROOT, capture_output=True, text=True, timeout=120)
    val = {"returncode": r.returncode, "wall_s": time.monotonic() - t, "summary": [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l][-1:], "output_path": "validation_pytest.txt"}
    open(os.path.join(rd, "validation_pytest.txt"), "w").write(r.stdout + r.stderr)
    C.state["stages"]["1_validation"] = val; C.events.write({"kind": "stage", "stage": "1_validation", **val})
    print("stage 1 validation:", val["summary"], f"{val['wall_s']:.1f}s", flush=True)
    if r.returncode != 0 or val["wall_s"] > 60: C.stop("CERTIFICATE_OR_CHECKER_FAILURE", detail="tiny validation failed or exceeded 60 s"); return finish(C, rd)
    gates = {}
    for case in ("MAIN", "CONTROL"):
        t = time.monotonic(); m = Model(N, case); G = response_gate(m, 128); G["input_sha256"] = m.sha256(); G["wall_s"] = time.monotonic() - t
        G["weighted_count_estimate"] = weighted_count_state_estimate(m); G["log_weight_perturbation"] = log_weight_perturbation_bound(m); gates[case] = G
        print(f"stage 1 gate {case}: {G['decision']} E0_prescribed={G['E0_prescribed_float']:.6f} K_exact={G['K_exact_alternating_closed_form']} L={G['declared']['L']} ({G['wall_s']:.2f}s)", flush=True)
    C.state["stages"]["1_gates"] = gates; C.save()
    if gates["MAIN"]["decision"] != "ADMITTED" or gates["CONTROL"]["decision"] != "CERTIFICATE_DECLINED":
        C.stop("PROOF_IMPLEMENTATION_MISMATCH", detail={k: v["decision"] for k, v in gates.items()}); return finish(C, rd)
    if a.skip_timed: return finish(C, rd)
    # ---------------- Stage 2: MAIN pair D then F
    rows = []
    d1 = C.cell("MAIN_pair1_D", "D", "MAIN", 1, "pair1"); f1 = C.cell("MAIN_pair1_F", "F", "MAIN", 2, "pair1")
    if d1 is None or f1 is None: return finish(C, rd)
    ok = d1["status"] == "VERIFIED" and f1["status"] == "VERIFIED"
    if not ok: C.stop("CERTIFICATE_OR_CHECKER_FAILURE", detail={"D": d1["status"], "F": f1["status"]}); return finish(C, rd)
    if d1["eligibility"]["eligible"] and d1["complete_wall_s"] > D_SCREEN_S: C.stop("NO_GO_ABSOLUTE_COST", detail={"D_complete_s": d1["complete_wall_s"]}); return finish(C, rd)
    if not d1["eligibility"]["eligible"] and d1["complete_wall_s"] > D_SCREEN_S: C.stop("INCONCLUSIVE", detail="ineligible D observation exceeded 30 s"); return finish(C, rd)
    # ---------------- Stage 3: two more MAIN pairs F,D then D,F
    C.cell("MAIN_pair2_F", "F", "MAIN", 3, "pair2"); C.cell("MAIN_pair2_D", "D", "MAIN", 4, "pair2")
    C.cell("MAIN_pair3_D", "D", "MAIN", 5, "pair3"); C.cell("MAIN_pair3_F", "F", "MAIN", 6, "pair3")
    # ---------------- Stage 4: CONTROL pairs F vs automatic (gate-then-F): F,auto / auto,F / F,auto
    C.cell("CONTROL_pair1_F", "F", "CONTROL", 7, "cpair1"); C.auto_cell("CONTROL_pair1_AUTO", 8, "cpair1")
    C.auto_cell("CONTROL_pair2_AUTO", 9, "cpair2"); C.cell("CONTROL_pair2_F", "F", "CONTROL", 10, "cpair2")
    C.cell("CONTROL_pair3_F", "F", "CONTROL", 11, "cpair3"); C.auto_cell("CONTROL_pair3_AUTO", 12, "cpair3")
    return finish(C, rd)


def finish(C, rd):
    C.state["elapsed_total_s"] = C.elapsed(); C.state["within_total_cap"] = C.elapsed() <= TOTAL_CAP_S; C.save()
    t = time.monotonic()
    from dq.report import write_report
    try:
        write_report(rd)
    except Exception as e:  # noqa: BLE001
        import traceback; C.events.write({"kind": "report_error", "error": repr(e), "tb": traceback.format_exc()[-2000:]})
    C.state["report_wall_s"] = time.monotonic() - t; C.state["elapsed_total_s"] = C.elapsed(); C.save(); C.events.write({"kind": "campaign_end", "elapsed_s": C.elapsed(), "report_wall_s": C.state["report_wall_s"]})
    print(f"campaign finished in {C.elapsed():.1f}s (report {C.state['report_wall_s']:.1f}s); stops: {[s['reason'] for s in C.state['stops']]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
