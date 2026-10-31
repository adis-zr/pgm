"""The two four-variable STRICT masked witnesses (r19 review, finding 2).

The review named two four-variable strict witnesses whose fit + rounding
certificates are below the 0.0005 allowance and whose largest elimination bag
falls from 8 (the dense compensating residual) to 4 (the strict forest). The
packet file of that name was not available on this machine; the two models
below are the build's own stand-ins, labelled as such: a complete graph on four
binary variables whose star at variable 0 carries the stronger coupling
(+0.30 / +0.20 and -0.30 / -0.20 in log-odds, exact rational tables), with the
fixed four local fields of the mean-field controls. On each, the recognizer's
`lowrank_rank1_forest_strict` candidate is constructed EXPLICITLY
(`residual.strict_residual`): the three off-star positive pairs are removed
after their exact unary gauge transfer and the whole representation is proved
by the gauge-invariant fit certificate on the original law; the dense
`lowrank_rank1_augmented` alternative keeps five pairs (largest bag 8).

The module runs both models through the PUBLIC pipeline (every candidate is
persisted under its executable identity and priced on its saved order; the
strict witness is never forced to be selected) and replays the strict
program's saved file through `mdi.replay` in this process; it reports, from
the SAVED schedule, the largest factor and the largest elimination bag of the
strict and the dense programs, the certificates, the independent truth and
the replay status.

    python -m portfolio.independent_strict_witness [OUT.json]
"""
from __future__ import annotations
import sys, os, json, math, tempfile
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

LABEL = ("build's own stand-in for the packet's two four-variable strict witnesses; the review's "
         "exact certificate values (0.000417250174, 0.000496865712) were not reproducible from the "
         "fixtures present here")
FIELDS = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(4)]
WITNESSES = (("strict witness A (positive star)", [0.30, 0.30, 0.30, 0.20, 0.20, 0.20]),
             ("strict witness B (negative star)", [-0.30, -0.30, -0.30, -0.20, -0.20, -0.20]))


def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def model(Js, fields=FIELDS):
    from mdi import model as M
    n = 4
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(round(math.exp(fields[v]) * 10 ** 6), 10 ** 6)],
                     origin=v) for v in range(n)]
    k = 0
    for i in range(n):
        for j in range(i + 1, n):
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(Js[k]), origin=100 + k))
            k += 1
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _dec(x):
    x = Fr(x)
    k = 0
    while (x * 10 ** k).denominator != 1:
        k += 1
    n = (x * 10 ** k).numerator
    return str(n) if k == 0 else "%d.%0*d" % (n // 10 ** k, k, n % 10 ** k)


def write_uai(m):
    lines = ["MARKOV", str(m.nvars), " ".join(str(c) for c in m.card), str(len(m.factors))]
    for f in m.factors:
        lines.append("%d %s" % (len(f.scope), " ".join(str(v) for v in f.scope)))
    for f in m.factors:
        lines.append(str(len(f.table)))
        lines.append(" ".join(_dec(x) for x in f.table))
    fd, path = tempfile.mkstemp(suffix=".uai")
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def schedule_diagnostics(plan_path, r):
    """Largest factor and largest elimination bag read from the SAVED program
    (its residual scopes and its saved order), not from a live object."""
    from mdi import plantype as PT, plan as P, routes as RT
    rec = PT.PlanRecord.from_json(open(plan_path).read())
    prog = rec.parsed_program
    coll = prog.get("collective")
    out = {"kind": rec.kind, "name": rec.name, "identity": rec.storage_schedule.get("identity"),
           "saved_order": list(prog.get("order") or [])}
    if coll is not None:
        from mdi import collective_route as CR, marked as MK, arith as A
        marked = MK.Marked.from_restricted(r, set(prog["queries"]))
        rmk, _res, _can = CR.rebuild_residual(marked, coll, A.Ctx(int(coll.get("precision", 96))))
        facs = list(rmk.factors)
        out["residual_pair_scopes"] = sorted([int(x) for x in f.scope] for f in facs if len(f.scope) == 2)
        out["largest_factor_entries"] = max((math.prod(f.card) for f in facs), default=1)
        pl = P.build_plan("saved", [int(x) for x in prog["order"]], rmk.free(), rmk.card, facs)
        out["largest_elimination_bag_entries"] = int(pl.largest_bag_entries)
        out["fit_tv"] = str(coll.get("fit_tv"))
        out["rounding_tv"] = str(coll.get("rounding_tv"))
        out["fit_plus_rounding"] = str(Fr(coll["fit_tv"]) + Fr(coll["rounding_tv"]))
        cand = coll.get("candidate")
        out["strict"] = bool(getattr(cand, "strict", False))
        out["masked"] = [list(p) for p in (getattr(cand, "masked", None) or [])]
    return out


def run(out_path=None, wall=300.0):
    from mdi import model as M, oracle as O, pipeline as PLN, replay as RP, pricing as PR
    rows = []
    for label, Js in WITNESSES:
        m = model(Js)
        mp = write_uai(m)
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        d = tempfile.mkdtemp(prefix="strict_witness_")
        res = PLN.solve(M.read_uai(mp), {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=d)
        row = {"witness": label, "couplings_log_odds": Js, "fields": FIELDS, "status": res.status,
               "selected": res.plan.get("chosen"), "label": LABEL, "programs": {}}
        strict_name = next((p["name"] for p in res.prices if p["name"] == "statistic:lowrank_rank1_forest_strict"), None)
        dense_name = next((p["name"] for p in res.prices if p["name"] == "statistic:lowrank_rank1_augmented"), None)
        for nm in (strict_name, dense_name):
            if nm is None:
                continue
            p = next(x for x in res.prices if x["name"] == nm)
            plan = os.path.join(d, p["identity"] + ".plan.json")
            diag = schedule_diagnostics(plan, r)
            rep = RP.replay(mp, "-", plan)
            iv = rep.get("intervals") or {}
            truth = bool(iv) and all(Fr(lo) <= pt[int(v)][s] <= Fr(hi) for v, rws in iv.items() for s, (lo, hi) in enumerate(rws))
            diag.update({"priced_final_largest_bag": (p["counters"].get("final_largest_bag") or {}).get("value"),
                         "eligible": p["eligible"], "replay": rep["status"], "truth": truth,
                         "max_width": rep.get("max_width"), "ledger": rep.get("ledger"),
                         "under_0.0005": Fr(diag.get("fit_plus_rounding", "1")) < Fr(5, 10000)})
            row["programs"][nm] = diag
        s = row["programs"].get(strict_name or "", {})
        dn = row["programs"].get(dense_name or "", {})
        row["ok"] = bool(s) and bool(dn) and s.get("replay") == "REPLAY_VERIFIED" and s.get("truth") is True \
            and s.get("under_0.0005") is True and s.get("strict") is True \
            and s.get("largest_elimination_bag_entries") == 4 and dn.get("largest_elimination_bag_entries") == 8 \
            and res.status.startswith("CERTIFIED")
        rows.append(row)
    out = {"rows": rows, "ok": all(r["ok"] for r in rows), "note": LABEL}
    if out_path:
        with open(out_path, "w") as fh:
            json.dump(out, fh, indent=1, default=str)
    return out


if __name__ == "__main__":
    res = run(sys.argv[1] if len(sys.argv) > 1 else None)
    for row in res["rows"]:
        print("==", row["witness"], row["status"], "selected", row["selected"], "ok", row["ok"])
        for nm, dgn in row["programs"].items():
            print("   %-40s strict=%-5s fit+rounding=%s (<0.0005 %s) largest factor=%s elimination bag=%s (priced %s) replay=%s truth=%s"
                  % (nm, dgn.get("strict"), str(dgn.get("fit_plus_rounding"))[:14], dgn.get("under_0.0005"),
                     dgn.get("largest_factor_entries"), dgn.get("largest_elimination_bag_entries"),
                     dgn.get("priced_final_largest_bag"), dgn.get("replay"), dgn.get("truth")))
    sys.exit(0 if res["ok"] else 1)
