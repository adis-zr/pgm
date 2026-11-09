"""Synthetic scale / integration controls for the general executor (not benchmark inputs; disclosed): (a) a seeded random positive K_{14,14} binary
bipartite model, (b) a 4x4 binary grid, (c) a random 10-variable mixed-cardinality higher-arity model with zeros, each run as a
complete cell (both new arms) with a 60 s budget; exact brute-force truth only where the joint fits (b, c); (a) is scale/integration only.
Records to D/synthetic/SYNTHETIC_SCALE.json.    python -m gbidi.synthetic_scale D"""
from __future__ import annotations
import os, sys, json, random, subprocess, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE, OMP_NUM_THREADS="1")


def write(path, card, facs):
    lines = ["MARKOV", str(len(card)), " ".join(map(str, card)), str(len(facs))] + ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in facs] + ["%d %s" % (len(t), " ".join("%d.%06d" % (x.numerator * (10 ** 6 // x.denominator) // 10 ** 6, x.numerator * (10 ** 6 // x.denominator) % 10 ** 6) for x in t)) for _, t in facs]
    open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("0\n"); return path, path + ".evid"


def rnd(r, sc, card, zeros=0.0):
    n = 1
    for v in sc:
        n *= card[v]
    return (tuple(sc), [Fr(0) if r.random() < zeros else Fr(r.randint(1, 999), 1000) for _ in range(n)])


def main(D):
    S = os.path.join(D, "synthetic"); os.makedirs(S, exist_ok=True); r = random.Random(2026); out = {}
    m = n = 14; card = [2] * (m + n); facs = [rnd(r, (v,), card) for v in range(m + n)] + [rnd(r, (a, m + b), card) for a in range(m) for b in range(n)]; A = write(os.path.join(S, "K14x14.uai"), card, facs)
    card = [2] * 16; facs = [rnd(r, (v,), card) for v in range(16)] + [rnd(r, (i * 4 + j, i * 4 + j + 1), card) for i in range(4) for j in range(3)] + [rnd(r, (i * 4 + j, (i + 1) * 4 + j), card) for i in range(3) for j in range(4)]; B = write(os.path.join(S, "grid4x4.uai"), card, facs)   # 2^16 joint: brute force feasible
    card = [2, 3, 2, 4, 2, 3, 2, 2, 3, 2]; facs = [rnd(r, (0, 1, 2), card, 0.1), rnd(r, (2, 3, 4), card), rnd(r, (4, 5, 6, 7), card, 0.2), rnd(r, (7, 8, 9), card), rnd(r, (0, 9), card), rnd(r, (1, 8), card), rnd(r, (3, 6), card)]; C = write(os.path.join(S, "mixed10.uai"), card, facs)
    from bidi import oracle as OR
    from ext import uai as U
    for name, (mp, ep) in (("K14x14", A), ("grid4x4", B), ("mixed10", C)):
        truth = None
        if name != "K14x14":
            mdl = U.read_model(mp); Z, N = OR.brute(mdl, {}); truth = (Z, N, mdl)
        for arm in ("GENERAL_BIDI_V1", "NATIVE_PLAIN_V1"):
            o = os.path.join(S, "%s_%s" % (name, arm)); t = time.monotonic(); subprocess.run([PY, "-m", "gbidi.cell", arm, mp, ep, o, "60", "{}"], cwd=HERE, env=ENV, capture_output=True, timeout=200); wall = time.monotonic() - t
            rec = json.load(open(os.path.join(o, "cell.json"))); row = {"status": rec["status"], "complete_response_s": rec.get("complete_response_s"), "outer_wall_s": wall, "route": rec.get("route"), "precision": rec.get("precision"), "max_width": rec.get("max_width"), "phases_s": rec.get("phases_s"), "plan_totals": (rec.get("plan") or {}).get("totals"), "mechanisms": rec.get("mechanisms"), "counters": (rec.get("attempts") or [{}])[-1].get("counters"), "maxrss_self_bytes": rec.get("maxrss_self_bytes"), "reason": rec.get("reason")}
            if truth is not None and rec["status"] == "CERTIFIED":
                Z, N, mdl = truth; rows, _ = U.read_mar(os.path.join(o, "output.MAR")); row["max_abs_error_vs_exact"] = float(max(abs(Fr(rows[v][s]) - N[v][s] / Z) for v in range(mdl.nvars) for s in range(mdl.card[v])))
            out["%s_%s" % (name, arm)] = row; print(name, arm, row["status"], row["complete_response_s"], row["route"], row.get("max_abs_error_vs_exact"), flush=True)
    json.dump(out, open(os.path.join(S, "SYNTHETIC_SCALE.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
