"""Run the bounded preflight gates and the single-node smoke, then seal the proposed execution packet.

This entry point deliberately CANNOT start the six timed invocations: no timed-schedule code path exists here.
Per the addendum, the automatic transition from preflight into the timed schedule is suspended."""
from __future__ import annotations
import sys, os, json, time, hashlib, argparse, resource, platform, subprocess
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.grid import Grid
from h4a.emit import Cache
from h4a.build import producer_tables, checker_tables
from h4q import preflight, smoke

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True); ap.add_argument("--packet", required=True)
    a = ap.parse_args()
    OUT = os.path.abspath(a.out_dir); PK = os.path.abspath(a.packet); os.makedirs(OUT, exist_ok=True)
    jf = open(os.path.join(OUT, "preflight_journal.jsonl"), "a")
    t0 = time.monotonic()
    def journal(rec):
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "elapsed_s": round(time.monotonic() - t0, 3), **rec}
        jf.write(json.dumps(rec, default=str) + "\n"); jf.flush(); os.fsync(jf.fileno())
    st = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "stage": "IMPLEMENTATION_AND_PREFLIGHT",
          "timed_invocations_started": False,
          "scope": "bounded correctness controls and a single-node smoke only; the six full-query timed invocations "
                   "are NOT started under this instruction and no timed-schedule code path exists in this entry point",
          "gates": {}, "smoke": {}}
    def save():
        p = os.path.join(OUT, "preflight_state.json"); f = open(p + ".tmp", "w")
        json.dump(st, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(p + ".tmp", p)
    journal({"stage": "start", "code_revision": subprocess.run(["git", "-C", CODE, "rev-parse", "HEAD"],
             capture_output=True, text=True).stdout.strip()})
    # ---- G1
    st["gates"]["G1"] = preflight.g1_build_and_probes(journal); save()
    if not st["gates"]["G1"]["all_ok"]: st["blocked_at"] = "G1"; save(); return finish(st, OUT, jf, t0)
    # ---- G2
    st["gates"]["G2"] = preflight.g2_domain_check(journal); save()
    if not st["gates"]["G2"]["all_ok"]: st["blocked_at"] = "G2"; save(); return finish(st, OUT, jf, t0)
    # ---- G3
    st["gates"]["G3"] = preflight.g3_small_fixture_coverage(journal, PK); save()
    if not st["gates"]["G3"]["all_ok"]: st["blocked_at"] = "G3"; save(); return finish(st, OUT, jf, t0)
    # ---- G4 needs one real node's records; build them once on the first frozen diagnostic node
    F = json.load(open(os.path.join(PK, "inputs", "FROZEN_NODES.json")))
    m = Model(128, 1); g = Grid(F["frequency_grids"]["1"])
    nd = F["nodes"][0]
    prob = NodeProblem(m, F["source_site"], nd["source_sign"], F["target_site"], nd["positive_node"], "E0")
    g4dir = os.path.join(OUT, "g4_records"); os.makedirs(g4dir, exist_ok=True)
    cp = Cache(m, g, 256); cc = Cache(m, g, 320)
    from h4a.emit import write_point_witness
    P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
    write_point_witness(f"{g4dir}/prod.txt", prob, g, cp, P, "producer")
    write_point_witness(f"{g4dir}/chk.txt", prob, g, cc, CK, "checker")
    for exe, i, o in (("h4point", "prod.txt", "prod.json"), ("h4pcheck", "chk.txt", "chk.json")):
        r = subprocess.run([os.path.join(CODE, "build", exe), "--in", f"{g4dir}/{i}", "--out", f"{g4dir}/{o}",
                            "--expect-freq", "265"], capture_output=True, text=True)
        assert r.returncode == 0, f"{exe}: {r.stderr[:300]}"
    st["gates"]["G4"] = preflight.g4_malformed_rejections(journal, f"{g4dir}/prod.json", f"{g4dir}/chk.json",
                                                          cp, cc, g, prob, arm="PP"); save()
    if not st["gates"]["G4"]["all_ok"]: st["blocked_at"] = "G4"; save(); return finish(st, OUT, jf, t0)
    # ---- G5, G6
    st["gates"]["G5"] = preflight.g5_cache_conformance(journal); save()
    if not st["gates"]["G5"]["all_ok"]: st["blocked_at"] = "G5"; save(); return finish(st, OUT, jf, t0)
    st["gates"]["G6"] = preflight.g6_aggregation_controls(journal); save()
    if not st["gates"]["G6"]["all_ok"]: st["blocked_at"] = "G6"; save(); return finish(st, OUT, jf, t0)
    # ---- single-node smoke, both arms
    for arm in ("C", "PP"):
        st["smoke"][arm] = smoke.smoke_one_node(arm, PK, os.path.join(OUT, f"smoke_{arm}"), journal=journal); save()
        if not st["smoke"][arm]["all_ok"]: st["blocked_at"] = f"smoke_{arm}"; save(); return finish(st, OUT, jf, t0)
    st["all_gates_passed"] = True
    save(); return finish(st, OUT, jf, t0)


def finish(st, OUT, jf, t0):
    ru = resource.getrusage(resource.RUSAGE_CHILDREN); rs = resource.getrusage(resource.RUSAGE_SELF)
    st["accounting"] = {"preflight_elapsed_s": round(time.monotonic() - t0, 3),
                        "children_cpu_s": round(ru.ru_utime + ru.ru_stime, 3),
                        "self_cpu_s": round(rs.ru_utime + rs.ru_stime, 3),
                        "peak_rss_bytes": max(ru.ru_maxrss, rs.ru_maxrss),
                        "note": "charged to the persistent cumulative budget; the timed stage has spent nothing"}
    st["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    st["result"] = "IMPLEMENTATION_READY_FOR_PILOT_REVIEW" if st.get("all_gates_passed") else f"BLOCKED_AT_{st.get('blocked_at')}"
    p = os.path.join(OUT, "preflight_state.json"); f = open(p, "w")
    json.dump(st, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close()
    jf.close()
    print(json.dumps({"result": st["result"], "gates": {k: v.get("all_ok") for k, v in st["gates"].items()},
                      "smoke": {k: v.get("all_ok") for k, v in st["smoke"].items()},
                      "elapsed_s": st["accounting"]["preflight_elapsed_s"],
                      "timed_invocations_started": st["timed_invocations_started"]}, default=str))


if __name__ == "__main__": main()
