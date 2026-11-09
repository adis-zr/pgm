"""Qualification at full size on a SYNTHETIC input (not a benchmark model): a seeded random positive K_{22,22} written as a UAI file, run as a
complete BIDI_NATIVE_CERT cell (recognize -> executor -> publish -> point verifier) with a 60 s budget, then checked against a brute-force
oracle? No -- 2^44 assignments are out of reach; instead the exact-oracle check is on a K_{10,10} slice run both natively and through the
MPFR-53 reference, and the K_{22,22} run exercises deadline polling, publication and timing at the pilot's size. Records to D/synthetic/.
    python -m bidi.synthetic_fullsize D"""
from __future__ import annotations
import os, sys, json, random, subprocess, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
PY = sys.executable; ENV = dict(os.environ, PYTHONPATH=HERE, OMP_NUM_THREADS="1")


def write_k(path, m, n, seed):
    r = random.Random(seed); nv = m + n; lines = ["MARKOV", str(nv), " ".join(["2"] * nv)]; facs = []
    for v in range(nv):
        facs.append(((v,), ["%d.%06d" % (r.randint(0, 3), r.randint(1, 999999)) for _ in range(2)]))
    for a in range(m):
        for b in range(n):
            sc = (a, m + b) if r.random() < 0.5 else (m + b, a); facs.append((sc, ["%d.%06d" % (r.randint(0, 3), r.randint(1, 999999)) for _ in range(4)]))
    lines.append(str(len(facs))); lines += ["%d %s" % (len(sc), " ".join(map(str, sc))) for sc, _ in facs]; lines += ["%d %s" % (len(t), " ".join(t)) for _, t in facs]
    open(path, "w").write("\n".join(lines) + "\n"); open(path + ".evid", "w").write("0\n"); return path, path + ".evid"


def main(D):
    S = os.path.join(D, "synthetic"); os.makedirs(S, exist_ok=True); out = {}
    mp, ep = write_k(os.path.join(S, "K22x22.uai"), 22, 22, 2026)
    for arm, budget in (("BIDI_NATIVE_CERT", "60"),):
        o = os.path.join(S, arm + "_K22x22"); t = time.monotonic(); subprocess.run([PY, "-m", "bidi.cell", arm, mp, ep, o, budget, json.dumps({"lanes_k": 3, "block_steps": 4096})], cwd=HERE, env=ENV, capture_output=True, timeout=200); wall = time.monotonic() - t
        r = json.load(open(os.path.join(o, "cell.json"))); out[arm + "_K22x22"] = {"status": r["status"], "complete_response_s": r["complete_response_s"], "outer_wall_s": wall, "phases_s": r["phases_s"], "max_width": r.get("max_width"), "kernel": {k: r["kernel"][k] for k in ("configs_visited", "complete", "lanes")} if r.get("kernel") else None, "counters": (r.get("kernel") or {}).get("counters"), "maxrss_self_bytes": r.get("maxrss_self_bytes"), "depth": {k: r["depth"][k] for k in ("E_term", "E_N", "e", "delta_float")} if r.get("depth") else None, "range_proof": r.get("range_proof")}
    mp2, ep2 = write_k(os.path.join(S, "K12x12.uai"), 12, 12, 2027)
    for arm in ("BIDI_NATIVE_CERT", "BIDI_MPFR53_CERT"):
        o = os.path.join(S, arm + "_K12x12"); t = time.monotonic(); subprocess.run([PY, "-m", "bidi.cell", arm, mp2, ep2, o, "120", json.dumps({"lanes_k": 3, "block_steps": 4096})], cwd=HERE, env=ENV, capture_output=True, timeout=300); wall = time.monotonic() - t
        r = json.load(open(os.path.join(o, "cell.json"))); out[arm + "_K12x12"] = {"status": r["status"], "complete_response_s": r["complete_response_s"], "outer_wall_s": wall, "Z_hex": (r.get("values_hex") or {}).get("Z"), "kernel_stream_s": r["phases_s"].get("kernel_stream")}
    out["native_vs_mpfr53_bitwise_K12x12"] = out["BIDI_NATIVE_CERT_K12x12"]["Z_hex"] == out["BIDI_MPFR53_CERT_K12x12"]["Z_hex"]
    json.dump(out, open(os.path.join(S, "SYNTHETIC_FULLSIZE.json"), "w"), indent=1, default=str); print(json.dumps({k: (v if not isinstance(v, dict) else {kk: v[kk] for kk in v if kk in ("status", "complete_response_s", "outer_wall_s", "kernel_stream_s", "max_width")}) for k, v in out.items()}, default=str))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
