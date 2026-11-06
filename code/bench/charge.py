"""Charged-job wrapper: runs ONE top-level job, records start/end/wall/rc/peak process-tree RSS into a ledger (append-only JSON lines).
usage: python bench/charge.py --ledger LEDGER.jsonl --scope SCOPE --job NAME [--timeout S] [--mem-gib G] -- cmd args...
Every charged campaign job (download, build, smoke check, cell, reference, diagnostic) goes through here or through bench/supervise.py
(which records in the same format). Wall = spawn-to-reap of the whole process tree. Nothing is double counted: a job that itself runs
children is charged once here."""
import argparse, json, os, subprocess, sys, time, signal
import psutil

def tree_rss(p):
    try:
        procs = [p] + p.children(recursive=True)
        return sum((q.memory_info().rss for q in procs if q.is_running()), 0)
    except psutil.Error:
        return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True); ap.add_argument("--scope", required=True); ap.add_argument("--job", required=True)
    ap.add_argument("--timeout", type=float, default=None); ap.add_argument("--mem-gib", type=float, default=None)
    ap.add_argument("--interval", type=float, default=0.05); ap.add_argument("--cwd", default=None); ap.add_argument("--stdout", default=None); ap.add_argument("--stderr", default=None)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(); cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    so = open(a.stdout, "wb") if a.stdout else None; se = open(a.stderr, "wb") if a.stderr else None
    t0 = time.time(); m0 = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=a.cwd, stdout=so or sys.stdout, stderr=se or sys.stderr, start_new_session=True)
    p = psutil.Process(proc.pid); peak = 0; outcome = "COMPLETED"; overshoot = 0; samples = 0
    while True:
        rc = proc.poll()
        if rc is not None: break
        r = tree_rss(p); samples += 1; peak = max(peak, r)
        el = time.monotonic() - m0
        if a.mem_gib is not None and r > a.mem_gib * 2**30:
            outcome = "MEMORY_KILL"; overshoot = r - a.mem_gib * 2**30; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        if a.timeout is not None and el > a.timeout:
            outcome = "TIMEOUT_KILL"; os.killpg(proc.pid, signal.SIGKILL); proc.wait(); break
        time.sleep(a.interval)
    wall = time.monotonic() - m0; rc = proc.returncode
    if outcome == "COMPLETED" and rc != 0: outcome = "NONZERO_EXIT"
    rec = {"scope": a.scope, "job": a.job, "cmd": cmd, "cwd": a.cwd or os.getcwd(), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)),
           "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "wall_s": wall, "returncode": rc, "outcome": outcome,
           "peak_tree_rss_bytes": peak, "rss_samples": samples, "sampling_interval_s": a.interval, "mem_cap_gib": a.mem_gib, "mem_overshoot_bytes": overshoot,
           "timeout_s": a.timeout, "enforcement": "sampled process-tree RSS (best effort, not an allocator cap); SIGKILL of the process group on threshold or deadline"}
    with open(a.ledger, "a") as f: f.write(json.dumps(rec) + "\n")
    print(json.dumps({"job": a.job, "wall_s": round(wall, 3), "rc": rc, "outcome": outcome, "peak_MB": round(peak / 1e6, 1)}), file=sys.stderr)
    sys.exit(0 if outcome == "COMPLETED" else 1)

if __name__ == "__main__":
    main()
