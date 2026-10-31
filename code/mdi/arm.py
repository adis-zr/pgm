"""One external arm: baseline (research disabled) or research-enabled.

Spec section 13: 600 s complete wall, 8 GiB tree RSS, 6 declared threads,
progress about every 30 s, timing ends after durable records are written.
"""
from __future__ import annotations
import sys, os, json, time, hashlib
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from mdi import budget as B
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


def run_arm(problem, research, rundir, eps=None, wall=None, cap=None, model_path=None, evid_path=None):
    """Run one arm and write a durable record. Returns the record."""
    eps = eps or K.MAX_WIDTH
    wall = wall or K.RESOURCES["arm_wall_s"]
    cap = cap or K.RESOURCES["arm_rss_bytes"]
    os.makedirs(rundir, exist_ok=True)
    label = "%s_%s" % (problem, "research" if research else "baseline")
    # ONE absolute deadline for the whole invocation, from before any parsing
    t0 = B.DEFAULT_CLOCK[0]()
    t_end = t0 + wall
    prog = Progress(label, rundir, time.time() + wall, wall)
    rec = {"problem": problem, "arm": "research" if research else "baseline",
           "label": label, "eps": str(eps), "wall_s": wall, "cap_bytes": cap,
           "threads_declared": K.RESOURCES["threads"], "outcome": "STARTED",
           "spec_sha256": K.SPEC_SHA256, "stages": {}, "rejected_plans": [],
           "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write(rec, rundir, label)          # durable STARTED record
    mp = model_path or os.path.join(PKT, problem + ".uai")
    ep = evid_path or os.path.join(PKT, problem + ".uai.evid")
    rec["input_sha256"] = {"model": sha256_file(mp), "evidence": sha256_file(ep)}

    try:
        prog("parse", problem)
        ts = time.time()
        m = M.read_uai(mp)
        ev = M.read_evidence(ep, m)
        r = M.restrict(m, ev)
        rec["stages"]["parse_s"] = time.time() - ts
        if B.DEFAULT_CLOCK[0]() > t_end:
            rec["outcome"] = "RESOURCE_STOP"
            rec["reason"] = "the complete wall of %.3f s was exhausted during parsing" % wall
            rec["elapsed_s"] = B.DEFAULT_CLOCK[0]() - t0
            _write(rec, rundir, label); prog.close()
            return rec
        rec["free_vars"] = len(r.free)
        rec["restricted_zeros"] = sum(1 for f in r.factors for t in f.table if t == 0)
        rec["queries"] = sum(m.card[v] for v in range(m.nvars) if v not in ev)
        prog("parse", "%d free vars, %d requested coordinates"
             % (len(r.free), rec["queries"]))

        if r.impossible_factor is not None or r.constant == 0:
            # the terminal passes through the SAME original-model proof as the
            # pipeline's: the witness is re-derived from the original tables
            from mdi import pipeline as _PLN
            proof = _PLN.zero_evidence_proof(m, ev, r)
            rec["outcome"] = "ZERO_EVIDENCE_PROVED" if proof.get("proved") else "NUMERICAL_REFUSAL"
            rec["reason"] = proof["reason"]
            rec["checker"] = proof
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
        remaining = t_end - B.DEFAULT_CLOCK[0]()
        if remaining <= 0:
            raise _Exhausted("the complete wall of %.3f s was exhausted before planning" % wall)
        res = PLN.solve(m, ev, queries=set(r.free), max_width=eps,
                        wall_s=remaining,                    # NEVER renewed
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
    except _Exhausted as e:
        rec["outcome"] = "RESOURCE_STOP"
        rec["reason"] = str(e)
    except Exception as e:
        import traceback
        rec["outcome"] = "IMPLEMENTATION_INCOMPLETE"
        rec["reason"] = "%s: %s" % (type(e).__name__, e)
        rec["traceback"] = traceback.format_exc()[-2000:]
    rec["peak_rss_bytes"] = S._rss_bytes()
    rec["elapsed_s"] = B.DEFAULT_CLOCK[0]() - t0
    _write(rec, rundir, label)
    # the DURABLE output is part of the contract: if it completed after the
    # deadline the result was not delivered within the wall
    rec["elapsed_s_including_durable_write"] = B.DEFAULT_CLOCK[0]() - t0
    if rec["elapsed_s_including_durable_write"] > wall and rec["outcome"].startswith("CERTIFIED"):
        rec["outcome_before_deadline_check"] = rec["outcome"]
        rec["outcome"] = "RESOURCE_STOP"
        rec["reason"] = ("the durable output completed %.3f s after the start, past the %.3f s wall"
                         % (rec["elapsed_s_including_durable_write"], wall))
        _write(rec, rundir, label)
    prog("done", "%s in %.1fs" % (rec["outcome"], rec["elapsed_s_including_durable_write"]))
    prog.close()
    return rec


class _Exhausted(Exception):
    pass


def _jsonable(x):
    if isinstance(x, Fr):
        return str(x)
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def _write(rec, rundir, label):
    """Atomic durable write: temp file then rename."""
    path = os.path.join(rundir, "arm_%s.json" % label)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(_jsonable(rec), fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _write_intervals(pub, m, rundir, label):
    """Exact dyadic/rational endpoints are authoritative."""
    rows = []
    for v in sorted(pub):
        rows.append({"var": v, "card": m.card[v],
                     "intervals": [[str(lo), str(hi)] for lo, hi in pub[v]]})
    with open(os.path.join(rundir, "intervals_%s.json" % label), "w") as fh:
        json.dump(rows, fh)


def _feasible_simplex_point(rows):
    """A point inside EVERY interval that also sums to exactly 1, or None.

    The old rule took midpoints, renormalized, CLIPPED back into the intervals
    and then renormalized AGAIN. That second renormalization can move a
    coordinate out of its interval: on the feasible rows [.195,.2], [.295,.3],
    [.5,.5] it produced a third coordinate of .501259, outside its fixed
    [.5,.5]. A clip followed by a rescale is not a projection onto the
    intersection of the box and the simplex.

    This instead solves the problem exactly in rationals. Writing
    x_i = lo_i + s_i with 0 <= s_i <= hi_i - lo_i, feasibility requires
    sum(lo) <= 1 <= sum(hi), and then the slack 1 - sum(lo) is distributed
    greedily within each coordinate's own width. Every x_i stays in its
    interval BY CONSTRUCTION and the sum is exactly 1.
    """
    los = [Fr(lo) for lo, _ in rows]
    his = [Fr(hi) for _, hi in rows]
    slo, shi = sum(los), sum(his)
    if slo > 1 or shi < 1:
        return None                      # the rows admit no coherent vector
    need = Fr(1) - slo
    vec = list(los)
    for i in range(len(rows)):
        if need <= 0:
            break
        room = his[i] - los[i]
        take = room if room < need else need
        vec[i] += take
        need -= take
    if need != 0:
        return None
    for x, lo, hi in zip(vec, los, his):
        if not (lo <= x <= hi):
            return None
    if sum(vec) != 1:
        return None
    return vec


def _write_point_vector(pub, m, ev, rundir, label):
    """A declared coherent probability vector for MAR scoring, chosen WITHOUT
    reference answers and PROVED to lie inside the reported intervals.

    The serialized bytes are read back and re-checked, so the published file
    is what was verified, not merely what was computed.
    """
    from mdi import model as MM
    DEC = 6
    out, problems = [], []
    for v in range(m.nvars):
        rows = pub.get(v)
        if rows is None:
            k = m.card[v]
            out.append([Fr(1, k)] * k)
            continue
        vec = _feasible_simplex_point(rows)
        if vec is None:
            problems.append(
                "variable %d: the published intervals admit NO coherent "
                "probability vector (sum of lower bounds %s, of upper bounds "
                "%s), so no point can be declared"
                % (v, sum(Fr(lo) for lo, _ in rows),
                   sum(Fr(hi) for _, hi in rows)))
            out.append(None)
            continue
        out.append(vec)
    if problems:
        raise ValueError("; ".join(problems[:4]))

    # ---- serialize at DEC decimals, then verify the ROUNDED values ----
    # Rounding to six decimals can itself leave an interval or break the sum,
    # so the rounded vector is repaired within the intervals and re-checked.
    ser = []
    for v, vec in enumerate(out):
        q = Fr(10) ** DEC
        rows = pub.get(v)
        if rows is None:
            ser.append([Fr(round(float(x) * 10 ** DEC)), ] for x in vec)
            ser[-1] = [Fr(int(x * q)) / q for x in vec]
            continue
        # Truncate, then pull each coordinate back INTO its own interval at
        # the grid. An interval can be narrower than one decimal step, in
        # which case no grid point lies inside it and the serialization cannot
        # represent a feasible vector at this precision; that is reported, not
        # papered over.
        r = []
        for a, x in enumerate(vec):
            lo, hi = Fr(rows[a][0]), Fr(rows[a][1])
            g = Fr(int(x * q)) / q
            if g < lo:
                g = Fr(-(-(lo * q) // 1)) / q        # ceil onto the grid
            if g > hi:
                g = Fr(hi * q // 1) / q              # floor onto the grid
            if not (lo <= g <= hi):
                raise ValueError(
                    "variable %d state %d: the published interval [%s, %s] is "
                    "narrower than one %d-decimal step, so NO serialized value "
                    "can lie inside it" % (v, a, lo, hi, DEC))
            r.append(g)
        # restore the unit sum using slack that stays inside each interval
        resid = Fr(1) - sum(r)
        step = Fr(1) / q
        i = 0
        guard = 0
        while resid != 0 and guard < 10 * len(r) + 64:
            guard += 1
            lo, hi = Fr(rows[i][0]), Fr(rows[i][1])
            if resid > 0 and r[i] + step <= hi:
                r[i] += step
                resid -= step
            elif resid < 0 and r[i] - step >= lo:
                r[i] -= step
                resid += step
            i = (i + 1) % len(r)
        if resid != 0:
            raise ValueError(
                "variable %d: a %d-decimal serialization cannot be made "
                "coherent inside the published intervals" % (v, DEC))
        for a, (x, (lo, hi)) in enumerate(zip(r, rows)):
            if not (Fr(lo) <= x <= Fr(hi)):
                raise ValueError(
                    "variable %d state %d: the serialized value %s lies "
                    "OUTSIDE its published interval [%s, %s]"
                    % (v, a, x, lo, hi))
        ser.append(r)

    path = os.path.join(rundir, "point_%s.MAR" % label)
    body = [str(len(ser))]
    for rr in ser:
        body.append(str(len(rr)))
        for x in rr:
            body.append(("%." + str(DEC) + "f") % float(x))
    with open(path, "w") as fh:
        fh.write("MAR\n" + " ".join(body) + "\n")

    # ---- read the written bytes back and CHECK them ----
    with open(path, "r") as fh:
        tok = fh.read().split()
    if not tok or tok[0] != "MAR":
        raise ValueError("the written point vector is not a MAR file")
    idx, nv = 1, int(tok[1])
    idx = 2
    for v in range(nv):
        k = int(tok[idx]); idx += 1
        vals = [Fr(tok[idx + a]) for a in range(k)]
        idx += k
        rows = pub.get(v)
        if rows is None:
            continue
        tot = sum(vals)
        if abs(tot - 1) > Fr(k, 10 ** DEC):
            raise ValueError(
                "variable %d: the PARSED point vector sums to %s, not 1"
                % (v, tot))
        for a, x in enumerate(vals):
            lo, hi = Fr(rows[a][0]), Fr(rows[a][1])
            tolr = Fr(1, 10 ** DEC)
            if not (lo - tolr <= x <= hi + tolr):
                raise ValueError(
                    "variable %d state %d: the PARSED value %s lies outside "
                    "its published interval [%s, %s]" % (v, a, x, lo, hi))
    return path


if __name__ == "__main__":
    problem = sys.argv[1]
    research = sys.argv[2] == "research"
    rundir = os.path.abspath(sys.argv[3])
    rec = run_arm(problem, research, rundir)
    print(json.dumps({k: v for k, v in _jsonable(rec).items()
                      if k in ("problem", "arm", "outcome", "reason", "elapsed_s",
                               "final_max_width", "plan_selection")}, indent=2))
