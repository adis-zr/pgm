"""Frozen experiment: manifest (instances, queries, widths, modes, caps), runner (fresh process per case; outer wall measured with a
prompt wait; one allowance ledger of accumulated child walls incl. the recorded development invocations), scoring tables.
usage: experiment.py manifest | run | score"""
import sys, os, json, time, hashlib, subprocess, resource
from research.paths import repo_root, runs_root, subprocess_env
HERE = str(repo_root())
from fractions import Fraction as Fr
from . import generators as G

E = str(runs_root() / "mdi_2026-10-28" / "CBI_LIBRARY_2026-11-06")
PY = sys.executable
ALLOWANCE_S = 3600.0; CASE_CAP_S = 120.0; MEM_CAP = 8 * (1 << 30)
R24 = Fr(1) - Fr(1, 2 ** 24); R12 = Fr(1) - Fr(1, 2 ** 12)


def instances():
    I = {}
    # ---- correctness layer (exact references feasible): d = 6, 6 rows
    I["c_two_blocks"] = G.chain(2, 6, 6, [Fr(1, 3)], 0, "c_two_blocks")
    I["c_chain5"] = G.chain(5, 6, 6, [Fr(1, 3), Fr(7, 8), Fr(1, 16), Fr(1, 2)], 0, "c_chain5")
    I["c_spoke"] = G.tree(5, 6, 6, [Fr(1, 3), Fr(1, 2), Fr(9, 10), Fr(1, 50)], 0, "c_spoke")
    for b in I["c_spoke"]["edges"]:
        b["u"] = 0
    I["c_tree7"] = G.tree(7, 6, 6, [Fr(1, 5), Fr(1, 2), Fr(9, 10), Fr(1, 40), Fr(1, 3), Fr(1, 8)], 1, "c_tree7")
    I["c_four_cycle"] = G.cycle(4, 6, 6, Fr(1, 32), 2, "c_four_cycle")
    I["c_ladder_2x3"] = G.mesh(2, 3, 6, 6, Fr(1, 40), 9, "c_ladder_2x3")
    I["c_mesh3x3"] = G.mesh(3, 3, 6, 8, Fr(1, 16), 21, "c_mesh3x3")
    I["c_torus3x3"] = G.mesh(3, 3, 5, 5, Fr(1, 64), 4, "c_torus3x3", periodic=True)
    I["c_island4x4"] = G.island_mesh(2, 2, 6, 6, 3, R12, Fr(1, 64), 0, "c_island4x4")
    I["c_hard_cycle_leaves"] = G.cycle(4, 6, 6, R24, 5, "c_hard_cycle_leaves", leaves=2, r_leaf=Fr(1, 64))
    # ---- performance layer (<= 12 base instances; d = 24)
    I["p_chain8_s0"] = G.chain(8, 24, 512, [Fr(1, 64), Fr(1, 2), R12, Fr(1, 1024), Fr(1, 8)], 0, "p_chain8")
    I["p_chain8_s1"] = G.chain(8, 24, 512, [Fr(1, 64), Fr(1, 2), R12, Fr(1, 1024), Fr(1, 8)], 1, "p_chain8")
    I["p_tree15_s0"] = G.tree(15, 24, 512, [Fr(1, 64), Fr(1, 2), R12, Fr(1, 1024), Fr(1, 8), Fr(1, 4096)], 0, "p_tree15")
    I["p_nearhard_cycle"] = G.cycle(4, 24, 128, R24, 0, "p_nearhard_cycle", leaves=2, r_leaf=Fr(1, 64))
    for b in I["p_nearhard_cycle"]["blocks"][:4]:                         # >= 32 common rows on the cycle (drawn per family)
        pass
    cs = G.Stream("p_nearhard_cycle|common|0"); common = set()
    while len(common) < 32:
        common.add(cs.bits(24))
    for b in I["p_nearhard_cycle"]["blocks"][:4]:
        rows = sorted(set(b["rows"]) | common); b["rows"] = rows; b["weights"] = (b["weights"] + [1] * len(rows))[:len(rows)]
    I["p_weak_mesh_4x4"] = G.mesh(4, 4, 24, 4096, Fr(1, 4096), 0, "p_weak_mesh")
    I["p_weak_mesh_6x6"] = G.mesh(6, 6, 24, 4096, Fr(1, 4096), 0, "p_weak_mesh")
    I["p_weak_mesh_8x8"] = G.mesh(8, 8, 24, 4096, Fr(1, 4096), 0, "p_weak_mesh")
    I["p_island_mesh_4x4"] = G.island_mesh(2, 2, 24, 4096, 512, R24, Fr(1, 4096), 0, "p_island_mesh")
    I["p_island_mesh_6x6"] = G.island_mesh(3, 3, 24, 4096, 512, R24, Fr(1, 4096), 0, "p_island_mesh")
    I["p_island_mesh_8x8"] = G.island_mesh(4, 4, 24, 4096, 512, R24, Fr(1, 4096), 0, "p_island_mesh")
    I["p_challenge_island_seam_1_64"] = G.island_mesh(2, 2, 24, 4096, 512, R24, Fr(1, 64), 0, "p_challenge_island")
    return I


def build_manifest():
    I = instances(); os.makedirs(os.path.join(E, "inputs"), exist_ok=True); man = {"instances": {}, "cases": []}
    for name, obj in I.items():
        obj["bit_convention"] = "coordinate j (0-based) <-> bit j; bit set <-> +1"
        data = json.dumps(obj, separators=(",", ":"), default=str).encode(); p = os.path.join(E, "inputs", name + ".json"); open(p, "wb").write(data)
        man["instances"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "blocks": len(obj["blocks"]), "edges": len(obj["edges"]), "d": obj["d"], "layer": "correctness" if name.startswith("c_") else "performance", "meta": {k: v for k, v in obj.get("meta", {}).items() if k != "cluster_hints"}}
    def add(inst, mode, width="1/100", queries="all", rep=0, truth=None):
        man["cases"].append({"id": len(man["cases"]), "instance": inst, "mode": mode, "width": width, "queries": queries, "rep": rep, "truth": truth})
    for name in I:
        if name.startswith("c_"):
            add(name, "truth_ve"); add(name, "library", "1/100", truth="truth_ve"); add(name, "library", "1/20", truth="truth_ve"); add(name, "comparator_exact", "1/100", truth="truth_ve")
    principal = {"p_chain8_s0", "p_tree15_s0", "p_island_mesh_4x4"}
    for name in I:
        if not name.startswith("p_"):
            continue
        reps = 3 if name in principal else 1
        for rep in range(reps):
            add(name, "library", "1/100", rep=rep); add(name, "comparator_exact", "1/100", rep=rep)
        if name.startswith("p_island_mesh"):
            add(name, "library", "1/200"); add(name, "library", "1/500")
        if name in ("p_chain8_s0", "p_tree15_s0", "p_nearhard_cycle"):
            add(name, "truth_ve"); add(name, "library", "1/20")
    man.update({"allowance_s": ALLOWANCE_S, "case_cap_s": CASE_CAP_S, "mem_cap_bytes": MEM_CAP, "built": time.strftime("%Y-%m-%d %H:%M:%S %z"), "widths": ["1/100 (primary)", "1/20", "1/200 and 1/500 on island meshes"],
                "timing": "child in-process cold solve+verify (incl. load, reductions, recognition, planning, certificate, verification, publication) + two repeated solves on the loaded model; outer wall = parent subprocess.run spawn-to-exit with a prompt wait; peak memory = child ru_maxrss",
                "comparator": "comparator_exact = the library forced to exact operators / dense elimination on the reduced model with coarsening disabled (bounded-width VE / exact tree sum-product), priced before launch (<= 2^23 dense entries)",
                "principal_repeats": sorted(principal)})
    json.dump(man, open(os.path.join(E, "MANIFEST.json"), "w"), indent=1); print("manifest:", len(man["cases"]), "cases;", len(I), "instances")


def run():
    man = json.load(open(os.path.join(E, "MANIFEST.json"))); lp = os.path.join(E, "ALLOWANCE_LEDGER.json")
    led = json.load(open(lp)) if os.path.exists(lp) else {"allowance_s": ALLOWANCE_S, "development_invocations": json.load(open(os.path.join(E, "DEV_RUNS.json"))), "charges": [], "unattempted": []}
    charged = lambda: sum(c["outer_wall_s"] for c in led["charges"]) + sum(float(x["seconds"]) for x in led["development_invocations"]["entries"])
    os.makedirs(os.path.join(E, "cases"), exist_ok=True); st_p = os.path.join(E, "STATE.json"); state = json.load(open(st_p)) if os.path.exists(st_p) else {"done": []}
    for c in man["cases"]:
        if c["id"] in state["done"]:
            continue
        rem = led["allowance_s"] - charged()
        if rem < 10:
            led["unattempted"].append({**c, "reason": "allowance exhausted (remaining %.1f s)" % rem}); json.dump(led, open(lp, "w"), indent=1); continue
        out = os.path.join(E, "cases", "%03d_%s_%s_%s_rep%d.json" % (c["id"], c["instance"], c["mode"], c["width"].replace("/", "_"), c["rep"]))
        truth = os.path.join(E, "cases", next((("%03d_%s_truth_ve_1_100_rep0.json" % (x["id"], x["instance"])) for x in man["cases"] if x["instance"] == c["instance"] and x["mode"] == "truth_ve"), "none")) if c["truth"] else ""
        cmd = [PY, "-m", "research.campaigns.cbi.run_case", os.path.join(E, "inputs", c["instance"] + ".json"), c["queries"], c["width"], c["mode"], "{}", out] + ([truth] if truth else [])
        t0 = time.monotonic(); row = {**c, "command": cmd, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=min(CASE_CAP_S, rem), env=subprocess_env({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}))
            row.update({"outer_wall_s": time.monotonic() - t0, "returncode": r.returncode, "stdout_tail": r.stdout[-400:], "stderr_tail": r.stderr[-400:], "outcome": "COMPLETED" if r.returncode == 0 else "NONZERO_EXIT"})
        except subprocess.TimeoutExpired:
            row.update({"outer_wall_s": time.monotonic() - t0, "returncode": None, "outcome": "TIMEOUT", "note": "work limit, not a mathematical statement"})
        if os.path.exists(out):
            rec = json.load(open(out)); row["status"] = rec.get("status"); row["verify_accepted"] = rec.get("verify_accepted"); row["child_high_water_rss_bytes"] = rec.get("child_high_water_rss_bytes")
            if (rec.get("child_high_water_rss_bytes") or 0) > MEM_CAP:
                row["outcome"] = "MEMORY_CAP_EXCEEDED_AT_EXIT"; row["note"] = "ru_maxrss above the 8 GiB cap (RLIMIT_AS is best-effort on this platform)"
        led["charges"].append(row); json.dump(led, open(lp, "w"), indent=1); state["done"].append(c["id"]); json.dump(state, open(st_p, "w"))
        print("%3d %-28s %-16s %-6s rep%d  %-10s %-20s verify=%s  outer %.2fs  remaining %.0fs" % (c["id"], c["instance"], c["mode"], c["width"], c["rep"], row["outcome"], row.get("status"), row.get("verify_accepted"), row["outer_wall_s"], led["allowance_s"] - charged()), flush=True)


if __name__ == "__main__":
    {"manifest": build_manifest, "run": run}[sys.argv[1]]()
