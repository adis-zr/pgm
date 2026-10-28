"""One external arm: baseline (research disabled) or research-enabled.

Spec section 13: 600 s complete wall, 8 GiB tree RSS, 6 declared threads,
progress about every 30 s, timing ends after durable records are written.
"""
from __future__ import annotations
import sys, os, json, time, hashlib
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import (config as K, model as M, plan as P, arith as A, solve as S,
                 regions as R, modes as MD, collective as CO, planner as PL)

PKT = "/tmp/tep/three_external_problems/inputs"
HEARTBEAT_S = 30.0


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Progress:
    def __init__(self, label, rundir, deadline, budget_s):
        self.label = label
        self.path = os.path.join(rundir, "progress_%s.log" % label)
        self.t0 = time.time()
        self.next = self.t0
        self.deadline = deadline
        self.budget = budget_s
        self.fh = open(self.path, "a", buffering=1)
        self.state = {"phase": "init", "status": "starting"}

    def __call__(self, phase, info=""):
        now = time.time()
        self.state = {"phase": phase, "status": str(info)}
        if now >= self.next:
            el = now - self.t0
            line = ("[%s] t=%.1fs remaining=%.1fs phase=%s %s"
                    % (time.strftime("%H:%M:%S"), el, max(0.0, self.budget - el),
                       phase, info))
            self.fh.write(line + "\n")
            print("  " + line, flush=True)
            self.next = now + HEARTBEAT_S

    def close(self):
        try:
            self.fh.close()
        except Exception:
            pass


def run_arm(problem, research, rundir, eps=None, wall=None, cap=None):
    """Run one arm and write a durable record. Returns the record."""
    eps = eps or K.MAX_WIDTH
    wall = wall or K.RESOURCES["arm_wall_s"]
    cap = cap or K.RESOURCES["arm_rss_bytes"]
    os.makedirs(rundir, exist_ok=True)
    label = "%s_%s" % (problem, "research" if research else "baseline")
    prog = Progress(label, rundir, time.time() + wall, wall)
    t0 = time.time()
    rec = {"problem": problem, "arm": "research" if research else "baseline",
           "label": label, "eps": str(eps), "wall_s": wall, "cap_bytes": cap,
           "threads_declared": K.RESOURCES["threads"],
           "spec_sha256": K.SPEC_SHA256, "stages": {}, "rejected_plans": []}
    mp, ep = os.path.join(PKT, problem + ".uai"), os.path.join(PKT, problem + ".uai.evid")
    rec["input_sha256"] = {"model": sha256_file(mp), "evidence": sha256_file(ep)}

    try:
        prog("parse", problem)
        ts = time.time()
        m = M.read_uai(mp)
        ev = M.read_evidence(ep, m)
        r = M.restrict(m, ev)
        rec["stages"]["parse_s"] = time.time() - ts
        rec["free_vars"] = len(r.free)
        rec["restricted_zeros"] = sum(1 for f in r.factors for t in f.table if t == 0)
        rec["queries"] = sum(m.card[v] for v in range(m.nvars) if v not in ev)
        prog("parse", "%d free vars, %d requested coordinates"
             % (len(r.free), rec["queries"]))

        if r.impossible_factor is not None or r.constant == 0:
            rec["outcome"] = "ZERO_EVIDENCE_PROVED"
            rec["reason"] = ("restricted factor %s is identically zero"
                             % r.impossible_factor)
            rec["elapsed_s"] = time.time() - t0
            _write(rec, rundir, label); prog.close()
            return rec

        # ---------------- the CONNECTED public pipeline ----------------
        # Everything from here runs through mdi.pipeline: independently
        # verified common exact preprocessing, candidate discovery, persisted
        # and reloaded plan records, complete-cost pricing, dispatcher-based
        # execution with compact crossings and direct readout, and independent
        # checking. The old ratio-only selection and the Cartesian coarse
        # executor are gone.
        from mdi import pipeline as PLN
        ts = time.time()
        res = PLN.solve(m, ev, queries=set(r.free), max_width=eps,
                        wall_s=max(1.0, wall - (time.time() - t0)),
                        cap_bytes=cap, research_enabled=research,
                        plan_dir=os.path.join(rundir, "plans_%s" % label),
                        progress=lambda ph, info="": prog(ph, info))
        rec["stages"]["pipeline_s"] = time.time() - ts
        rec["pipeline"] = {
            "status": res.status, "reason": res.reason, "plan": res.plan,
            "preprocess": res.preprocess, "checker": res.checker,
            "properties": res.properties, "stages": res.stages,
            "budget": res.budget, "rejected": res.rejected,
            "prices": res.prices}
        rec["outcome"] = res.status
        rec["reason"] = res.reason
        rec["producer_complete"] = bool(res.properties.get("producer_complete"))
        rec["independently_verified"] = bool(
            res.properties.get("independently_verified"))
        if res.intervals:
            worst = max((Fr(hi) - Fr(lo)) for rows in res.intervals.values()
                        for lo, hi in rows)
            rec["final_max_width"] = str(worst)
            rec["contract_met"] = bool(worst <= eps)
            _write_intervals(res.intervals, m, rundir, label)
            _write_point_vector(res.intervals, m, ev, rundir, label)
    except Exception as e:
        import traceback
        rec["outcome"] = "IMPLEMENTATION_INCOMPLETE"
        rec["reason"] = "%s: %s" % (type(e).__name__, e)
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["elapsed_s"] = time.time() - t0
    rec["peak_rss_bytes"] = S._rss_bytes()
    _write(rec, rundir, label)
    prog("done", "%s in %.1fs" % (rec["outcome"], rec["elapsed_s"]))
    prog.close()
    return rec


def _jsonable(x):
    if isinstance(x, Fr):
        return str(x)
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def _write(rec, rundir, label):
    with open(os.path.join(rundir, "arm_%s.json" % label), "w") as fh:
        json.dump(_jsonable(rec), fh, indent=2)


def _write_intervals(pub, m, rundir, label):
    """Exact dyadic/rational endpoints are authoritative."""
    rows = []
    for v in sorted(pub):
        rows.append({"var": v, "card": m.card[v],
                     "intervals": [[str(lo), str(hi)] for lo, hi in pub[v]]})
    with open(os.path.join(rundir, "intervals_%s.json" % label), "w") as fh:
        json.dump(rows, fh)


def _write_point_vector(pub, m, ev, rundir, label):
    """A declared coherent probability vector for MAR scoring, chosen WITHOUT
    reference answers and lying inside the reported intervals.

    Rule: take each interval's midpoint, then renormalize per variable. The
    midpoint of a valid enclosure lies inside it; renormalizing a vector of
    midpoints can leave the interval only if an interval is extremely narrow
    relative to the renormalization shift, so the result is clipped back into
    the interval and renormalized once more.
    """
    from mdi import model as MM
    out = []
    for v in range(m.nvars):
        rows = pub.get(v)
        if rows is None:
            out.append([1.0 / m.card[v]] * m.card[v]); continue
        mid = [(Fr(lo) + Fr(hi)) / 2 for lo, hi in rows]
        tot = sum(mid)
        if tot <= 0:
            vec = [Fr(1, len(rows))] * len(rows)
        else:
            vec = [x / tot for x in mid]
            vec = [min(max(x, Fr(lo)), Fr(hi)) for x, (lo, hi) in zip(vec, rows)]
            t2 = sum(vec)
            if t2 > 0:
                vec = [x / t2 for x in vec]
        out.append([float(x) for x in vec])
    with open(os.path.join(rundir, "point_%s.MAR" % label), "w") as fh:
        body = [str(len(out))]
        for rr in out:
            body.append(str(len(rr)))
            for x in rr:
                body.append("%.6f" % x)
        fh.write("MAR\n" + " ".join(body) + "\n")


if __name__ == "__main__":
    problem = sys.argv[1]
    research = sys.argv[2] == "research"
    rundir = os.path.abspath(sys.argv[3])
    rec = run_arm(problem, research, rundir)
    print(json.dumps({k: v for k, v in _jsonable(rec).items()
                      if k in ("problem", "arm", "outcome", "reason", "elapsed_s",
                               "final_max_width", "plan_selection")}, indent=2))
