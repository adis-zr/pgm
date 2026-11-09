"""Lane-count calibration on SYNTHETIC full-kernel workloads (not benchmark inputs): at most three candidates k in {0, 2, 3} (1, 4, 8 lanes),
one run each of the complete native kernel (init + stream + finish) on a seeded random positive K_{20,20}; selector = fastest wall per
configuration. Records every candidate. Total allowance 300 s (charged inside the aggregate budget).
    python -m bidi.calibrate_lanes D"""
from __future__ import annotations
import os, sys, json, time, random
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
from bidi import executor as EX

CANDIDATES = [0, 2, 3]; M = N = 20; SEED = 7


def main(D):
    r = random.Random(SEED); phi = [r.uniform(0.2, 2.0) for _ in range(2 * M)]; rho = [r.uniform(0.2, 2.0) for _ in range(2 * N)]; psi = [r.uniform(0.2, 2.0) for _ in range(M * N * 4)]
    rows = []; t_all = time.monotonic()
    for k in CANDIDATES:
        K = EX.NativeKernel(); t = time.monotonic(); K.create(M, N, k, phi, rho, psi, 1.0); t_init = time.monotonic() - t
        t = time.monotonic()
        while not K.done():
            K.step(4096)
        t_stream = time.monotonic() - t; Z, NX, NY, c, ok = K.finish(); K.destroy(); wall = t_init + t_stream
        rows.append({"lanes_k": k, "lanes": 1 << k, "wall_s": wall, "init_s": t_init, "stream_s": t_stream, "configs": c["configs"], "ns_per_config": 1e9 * wall / c["configs"], "mults": c["mults"], "adds": c["adds"], "ops_per_config": (c["mults"] + c["adds"]) / c["configs"], "Gops_per_s": (c["mults"] + c["adds"]) / wall / 1e9, "complete": ok, "Z_hex": float(Z).hex()})
        print(json.dumps(rows[-1]), flush=True)
    best = min(rows, key=lambda x: x["wall_s"])
    rec = {"workload": "synthetic positive K_{%d,%d}, seed %d, entries U(0.2, 2.0) as binary64" % (M, N, SEED), "candidates": rows, "frozen_lanes_k": best["lanes_k"], "selector": "fastest wall per configuration on the synthetic workload (single run each)", "total_wall_s": time.monotonic() - t_all,
           "note": "all candidates produce the same exact-arithmetic result up to the certified error; Z differs bitwise between lane counts because the accumulation order differs (expected, covered by the depth labels)"}
    json.dump(rec, open(os.path.join(D, "LANE_CALIBRATION.json"), "w"), indent=1); print(json.dumps({"frozen_lanes_k": best["lanes_k"], "ns_per_config": {x["lanes_k"]: round(x["ns_per_config"], 1) for x in rows}}))


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
