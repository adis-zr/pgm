"""Replay runner for REPLAY_MANIFEST.json: fresh process per case into replay/, prompt-wait outer walls, its own ledger (REPLAY_LEDGER.json);
truth files are the FROZEN run's truth_ve records (exact VE is unchanged by the repair)."""
import sys, os, json, time, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
E = os.path.join(HERE, "runs/mdi_2026-10-28/CBI_LIBRARY_2026-11-06"); PY = sys.executable; CAP_S = 120.0
TAG = os.environ.get("CBI_REPLAY_TAG", "")                      # "" -> REPLAY_MANIFEST.json / replay/ ; "2" -> REPLAY2_MANIFEST.json / replay2/
man = json.load(open(os.path.join(E, "REPLAY%s_MANIFEST.json" % TAG))); frozen = json.load(open(os.path.join(E, "MANIFEST.json")))
lp = os.path.join(E, "REPLAY%s_LEDGER.json" % TAG); led = json.load(open(lp)) if os.path.exists(lp) else {"charges": [], "commit": man["commit"]}
os.makedirs(os.path.join(E, "replay%s" % TAG), exist_ok=True); done = {c["id"] for c in led["charges"]}
for c in man["cases"]:
    if c["id"] in done:
        continue
    out = os.path.join(E, "replay%s" % TAG, "%03d_%s_%s_%s_q%s_rep%d.json" % (c["id"], c["instance"], c["mode"], c["width"].replace("/", "_"), c["queries"], c["rep"]))
    truth = ""
    if c["truth"]:
        t = next((x for x in frozen["cases"] if x["instance"] == c["instance"] and x["mode"] == "truth_ve"), None)
        if t:
            truth = os.path.join(E, "cases", "%03d_%s_truth_ve_1_100_rep0.json" % (t["id"], c["instance"]))
    cmd = [PY, os.path.join(HERE, "cbi/run_case.py"), os.path.join(E, "inputs", c["instance"] + ".json"), c["queries"], c["width"], c["mode"], "{}", out] + ([truth] if truth else [])
    t0 = time.monotonic(); row = {**c, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=CAP_S, env={**os.environ, "PYTHONPATH": HERE, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
        row.update({"outer_wall_s": time.monotonic() - t0, "returncode": r.returncode, "outcome": "COMPLETED" if r.returncode == 0 else "NONZERO_EXIT", "stderr_tail": r.stderr[-300:]})
    except subprocess.TimeoutExpired:
        row.update({"outer_wall_s": time.monotonic() - t0, "returncode": None, "outcome": "TIMEOUT"})
    if os.path.exists(out):
        rec = json.load(open(out)); row["status"] = rec.get("status"); row["verify_accepted"] = rec.get("verify_accepted"); row["rss_bytes"] = rec.get("child_high_water_rss_bytes"); row["containment"] = rec.get("truth_containment")
    led["charges"].append(row); json.dump(led, open(lp, "w"), indent=1)
    print("%3d %-28s %-16s %-6s q=%-4s rep%d %-10s %-20s verify=%s contained=%s outer %.2fs" % (c["id"], c["instance"], c["mode"], c["width"], c["queries"], c["rep"], row["outcome"], row.get("status"), row.get("verify_accepted"), (row.get("containment") or {}).get("failures", "-"), row["outer_wall_s"]), flush=True)
print("replay total outer walls: %.1f s" % sum(x["outer_wall_s"] for x in led["charges"]))
