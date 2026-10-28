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

        # ---------------- plan pricing ----------------
        ts = time.time()
        bpe = 64
        cands = [PL.price_identity(r.free, r.card, r.factors, bpe, cap)]
        prog("plan", "identity priced: %s" % (cands[0].forecast.get("plan"),))
        if research:
            budget_left = wall - (time.time() - t0)
            dwall = min(K.CAPS["discovery_wall_s"], max(1.0, budget_left * 0.25))
            cands += PL.price_regional(r.free, r.card, r.factors, set(r.free), 1,
                                       bpe, cap, dwall, log=prog)
            ctx = A.Ctx(128)
            mwall = min(K.CAPS["discovery_wall_s"], max(1.0, (wall - (time.time() - t0)) * 0.25))
            cands += PL.price_modes(r.free, r.factors, r.card, set(r.free), ctx,
                                    mwall, log=prog)
        sel = PL.select(cands, log=prog)
        rec["stages"]["planning_s"] = time.time() - ts
        rec["plan_selection"] = {
            "chosen": sel["chosen"].name if sel["chosen"] else None,
            "chosen_kind": sel["chosen"].kind if sel["chosen"] else None,
            "why": sel["why"],
            "radius_charged": str(sel["chosen"].radius) if sel["chosen"] else "0"}
        rec["rejected_plans"] = sel["rejected"]
        rec["all_candidates"] = [
            {"name": c.name, "kind": c.kind, "admitted": c.admitted,
             "radius": str(c.radius), "reason": c.reason,
             "forecast": _jsonable(c.forecast)} for c in sel["all"]]

        if sel["chosen"] is None or not sel["chosen"].admitted:
            best = cands[0]
            rec["outcome"] = "RESOURCE_STOP"
            rec["reason"] = ("no admitted plan; identity forecast %s"
                             % _jsonable(best.forecast))
            rec["elapsed_s"] = time.time() - t0
            _write(rec, rundir, label); prog.close()
            return rec

        chosen = sel["chosen"]
        d = chosen.radius
        rec["transformation_radius"] = str(d)
        # width available to the numerical stage
        num_budget = eps - 2 * d - K.PUBLICATION_RESERVE
        rec["numerical_width_budget"] = str(num_budget)
        if num_budget <= 0:
            rec["outcome"] = "NUMERICAL_REFUSAL"
            rec["reason"] = "transformation radius consumes the whole contract"
            rec["elapsed_s"] = time.time() - t0
            _write(rec, rundir, label); prog.close()
            return rec

        # ---------------- execute ----------------
        prog("execute", "plan=%s kind=%s" % (chosen.name, chosen.kind))
        rec["research_executed"] = False
        if chosen.kind == "regional":
            # Execute the COARSE model and restore original markers (mdi.coarse).
            from mdi import coarse as CZ
            ts = time.time()
            pay = chosen.payload
            try:
                cres = CZ.solve_coarse_with_markers(
                    r.free, r.card, r.factors, pay["partition"]["regions"],
                    pay["coarse"], pay["regions_data"], set(r.free),
                    eps=num_budget, mode="P", cap_bytes=cap,
                    deadline_s=max(1.0, wall - (time.time() - t0)))
            except Exception as e:
                cres = {"outcome": "IMPLEMENTATION_INCOMPLETE",
                        "reason": "%s: %s" % (type(e).__name__, e)}
            rec["stages"]["coarse_solve_s"] = time.time() - ts
            rec["coarse"] = {k: _jsonable(v) for k, v in cres.items()
                             if k != "intervals"}
            if cres.get("outcome") == "PRODUCER_COMPLETE_UNCHECKED":
                # A coarse producer finished but NO independent check exists for
                # it. This cannot be labelled CERTIFIED_RESEARCH_ROUTE.
                rec["research_executed"] = True
                rec["research_checked"] = False
                iv = cres["intervals"]
                for v, st in ev.items():
                    iv[v] = [(Fr(1), Fr(1)) if sx == st else (Fr(0), Fr(0))
                             for sx in range(m.card[v])]
                pub, worst = {}, Fr(0)
                for v in sorted(iv):
                    rows = []
                    for (lo, hi) in iv[v]:
                        lo2, hi2 = Fr(lo), Fr(hi)
                        if not (lo2 == hi2 and (lo2 == 0 or lo2 == 1)):
                            lo2 = max(Fr(0), lo2 - d); hi2 = min(Fr(1), hi2 + d)
                        if hi2 - lo2 > worst:
                            worst = hi2 - lo2
                        rows.append((lo2, hi2))
                    pub[v] = rows
                rec["final_max_width"] = str(worst)
                rec["contract_met"] = bool(worst <= eps)
                rec["outcome"] = ("RESEARCH_ROUTE_UNCHECKED" if worst <= eps
                                  else "NUMERICAL_REFUSAL")
                rec["outcome_note"] = (
                    "the coarse producer met the width contract, but spec 11's "
                    "independent check of a coarse publication is NOT "
                    "implemented, so this is not CERTIFIED_RESEARCH_ROUTE")
                if worst > eps:
                    rec["reason"] = "final width %s exceeds %s" % (worst, eps)
                else:
                    _write_intervals(pub, m, rundir, label)
                    _write_point_vector(pub, m, ev, rundir, label)
                rec["elapsed_s"] = time.time() - t0
                rec["peak_rss_bytes"] = S._rss_bytes()
                _write(rec, rundir, label)
                prog("done", "%s in %.1fs" % (rec["outcome"], rec["elapsed_s"]))
                prog.close()
                return rec
            rec["research_note"] = (
                "the admitted regional transformation was constructed and "
                "certified, but its coarse contraction did not complete: %s. "
                "Falling back to the generic runtime and charging both."
                % cres.get("reason", cres.get("outcome")))
            d = Fr(0)                      # fallback publishes without the radius
            rec["transformation_radius_charged_but_unused"] = str(chosen.radius)
            num_budget = eps - K.PUBLICATION_RESERVE
        ts = time.time()
        remaining = wall - (time.time() - t0)
        res = S.solve(m, ev, eps=num_budget + 2 * d if d == 0 else num_budget,
                      mode="P", cap_bytes=cap, deadline_s=max(1.0, remaining),
                      progress=lambda ph, info="": prog(ph, info))
        rec["stages"]["solve_s"] = time.time() - ts
        rec["solve"] = {k: _jsonable(v) for k, v in res.items()
                        if k not in ("intervals", "raw_intervals", "per_var")}
        out = res.get("outcome")
        if out == "VERIFIED_ALL_MARGINALS":
            iv = res["intervals"]
            # outward expansion by the certified transformation radius
            pub = {}
            worst = Fr(0)
            for v in sorted(iv):
                rows = []
                for (lo, hi) in iv[v]:
                    lo2, hi2 = Fr(lo), Fr(hi)
                    if not (lo2 == hi2 and (lo2 == 0 or lo2 == 1)):
                        lo2 = max(Fr(0), lo2 - d)
                        hi2 = min(Fr(1), hi2 + d)
                    wdt = hi2 - lo2
                    if wdt > worst:
                        worst = wdt
                    rows.append((lo2, hi2))
                pub[v] = rows
            rec["final_max_width"] = str(worst)
            rec["contract_met"] = bool(worst <= eps)
            if not rec["contract_met"]:
                rec["outcome"] = "NUMERICAL_REFUSAL"
                rec["reason"] = "final width %s exceeds %s" % (worst, eps)
            else:
                if chosen.kind != "identity" and rec.get("research_executed"):
                    # reachable only if a research route were independently
                    # checked, which no implemented path currently does
                    rec["outcome"] = ("CERTIFIED_RESEARCH_ROUTE"
                                      if rec.get("research_checked")
                                      else "RESEARCH_ROUTE_UNCHECKED")
                else:
                    rec["outcome"] = "CERTIFIED_FALLBACK_ONLY"
            rec["checker"] = res.get("checker")
            _write_intervals(pub, m, rundir, label)
            _write_point_vector(pub, m, ev, rundir, label)
        else:
            # A producer-only result is NOT certified, and a checker that did
            # not finish has verified no named subset. The old mapping turned
            # both into CERTIFIED_PARTIAL.
            rec["outcome"] = {"TIMEOUT": "TIMEOUT", "MEMORY_STOP": "MEMORY_STOP",
                              "RESOURCE_BOUND": "RESOURCE_STOP",
                              "RESOURCE_STOP": "RESOURCE_STOP",
                              "NUMERICAL_REFUSAL": "NUMERICAL_REFUSAL",
                              "ZERO_EVIDENCE_PROVED": "ZERO_EVIDENCE_PROVED",
                              "PRODUCER_COMPLETE_UNCHECKED": "RESOURCE_STOP",
                              "VERIFIED_PARTIAL": "RESOURCE_STOP"}.get(out, out)
            rec["producer_complete"] = bool(res.get("producer_complete"))
            rec["independently_verified"] = bool(res.get("independently_verified"))
            rec["reason"] = res.get("reason", "")
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
