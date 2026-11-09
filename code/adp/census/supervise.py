"""Charging SUPERVISOR for the census pass (every executed process job goes through here; absence of a wrapper is a missing charge).

    python -m adp.census.supervise --ledger L.jsonl --scope S --job NAME [--timeout S] [--mem-gib G] [--cwd DIR] [--stdout F] [--stderr F] -- cmd...

Differences from bench/charge.py (which lost receipts when it was killed together with its child):
  * the attempt START (job, cmd, start time, timeout, mem cap, max permitted charge) is appended and fsynced BEFORE the launch; the launch runs
    INSIDE the receipt-producing try/finally, so a failed Popen (absent executable) yields a RECEIPT with outcome LAUNCH_FAILED
    (review of 8 Nov 2026: the previous version called Popen before START and before try/finally and left no record on a failed launch);
  * a SPAWNED record (pid, pgid) is appended after a successful spawn; the RECEIPT is written in a `finally` path (also on KeyboardInterrupt /
    SIGTERM of the supervisor) and never while a live child could remain unaccounted (it is killed by its recorded pgid first);
  * the child runs in its own process group and is stopped by os.killpg on its RECORDED pgid (never by a process-name pattern);
  * a START without a matching RECEIPT is reconciled as UNRESOLVED with charge = max permitted (timeout + grace) by the ledger tool.
Wall = spawn-to-reap of the whole tree; peak = sampled process-tree RSS (50 ms; best effort, not an allocator cap)."""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, signal
import psutil

GRACE_S = 4.0


def tree_rss(p):
    try:
        return sum((q.memory_info().rss for q in [p] + p.children(recursive=True) if q.is_running()), 0)
    except psutil.Error:
        return 0


def append(ledger, rec):
    with open(ledger, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n"); f.flush(); os.fsync(f.fileno())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True); ap.add_argument("--scope", required=True); ap.add_argument("--job", required=True)
    ap.add_argument("--timeout", type=float, default=None); ap.add_argument("--mem-gib", type=float, default=None); ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--cwd", default=None); ap.add_argument("--stdout", default=None); ap.add_argument("--stderr", default=None); ap.add_argument("--env", action="append", default=[])
    ap.add_argument("cmd", nargs=argparse.REMAINDER); a = ap.parse_args(); cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    env = dict(os.environ)
    for kv in a.env:
        k, v = kv.split("=", 1); env[k] = v
    so = open(a.stdout, "ab") if a.stdout else None; se = open(a.stderr, "ab") if a.stderr else None
    jid = "%s|%s|%d" % (a.job, time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()); t0 = time.time(); m0 = time.monotonic()
    maxcharge = (a.timeout + GRACE_S) if a.timeout is not None else None
    # 1. the attempt START is written and fsynced BEFORE any launch (a failed Popen can no longer leave an unaccounted attempt)
    append(a.ledger, {"kind": "START", "jid": jid, "scope": a.scope, "job": a.job, "cmd": cmd, "cwd": a.cwd or os.getcwd(), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "supervisor_pid": os.getpid(), "timeout_s": a.timeout, "mem_cap_gib": a.mem_gib, "max_permitted_charge_s": maxcharge})
    proc = None; pgid = None
    peak = 0; overshoot = 0; outcome = "COMPLETED"; samples = 0; rc = None
    def stop(reason):
        nonlocal outcome
        outcome = reason
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    def on_term(signum, frame):
        stop("SUPERVISOR_SIGNAL_%d" % signum); raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, on_term); signal.signal(signal.SIGINT, on_term)
    try:
        # 2. the launch itself is INSIDE the receipt-producing path: a failed launch yields a RECEIPT with outcome LAUNCH_FAILED
        try:
            proc = subprocess.Popen(cmd, cwd=a.cwd, stdout=so or sys.stdout, stderr=se or sys.stderr, env=env, start_new_session=True)
        except (OSError, ValueError) as ex:
            outcome = "LAUNCH_FAILED"; launch_error = "%s: %s" % (type(ex).__name__, ex); raise
        pgid = os.getpgid(proc.pid)
        # 3. the spawned child identity is recorded separately after a successful spawn
        append(a.ledger, {"kind": "SPAWNED", "jid": jid, "job": a.job, "pid": proc.pid, "pgid": pgid, "spawn_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        p = psutil.Process(proc.pid)
        while proc.poll() is None:
            r = tree_rss(p); samples += 1; peak = max(peak, r); el = time.monotonic() - m0
            if a.mem_gib is not None and r > a.mem_gib * 2 ** 30:
                overshoot = r - a.mem_gib * 2 ** 30; stop("MEMORY_KILL"); proc.wait(); break
            if a.timeout is not None and el > a.timeout + GRACE_S:
                stop("TIMEOUT_KILL"); proc.wait(); break
            time.sleep(a.interval)
        rc = proc.returncode
        if outcome == "COMPLETED" and rc != 0:
            outcome = "NONZERO_EXIT"
    except KeyboardInterrupt:
        if proc is not None:
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            rc = proc.returncode
    except (OSError, ValueError):
        rc = None                                                            # launch failed: no child exists; receipt below records LAUNCH_FAILED
    finally:
        wall = time.monotonic() - m0
        if proc is not None and proc.poll() is None:                         # a receipt is never written while a live child could survive unaccounted
            stop(outcome if outcome != "COMPLETED" else "SUPERVISOR_EXIT_WITH_LIVE_CHILD")
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            rc = proc.returncode
        append(a.ledger, {"kind": "RECEIPT", "jid": jid, "scope": a.scope, "job": a.job, "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "wall_s": wall, "returncode": rc, "outcome": outcome, "launch_error": locals().get("launch_error"), "peak_tree_rss_bytes": peak, "rss_samples": samples, "sampling_interval_s": a.interval, "mem_cap_gib": a.mem_gib, "mem_overshoot_bytes": overshoot, "timeout_s": a.timeout, "pid": (proc.pid if proc is not None else None), "pgid": pgid,
                           "enforcement": "sampled process-tree RSS (best effort, not an allocator cap); SIGKILL of the RECORDED process group on threshold, deadline + grace, or supervisor signal"})
        print(json.dumps({"job": a.job, "wall_s": round(wall, 3), "rc": rc, "outcome": outcome, "peak_MB": round(peak / 1e6, 1)}), file=sys.stderr)
    sys.exit(0 if outcome == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
