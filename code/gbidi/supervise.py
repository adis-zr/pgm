"""Charging SUPERVISOR for the GENERAL_BIDI_V2 round (review R2-08 / H1 repair of adp/census/supervise.py, which stays unchanged as the pinned
census harness). Identical START / SPAWNED / RECEIPT protocol, deferred cancellation, kill-and-reap before the charged wall; PLUS: completion means
the OWNED PROCESS GROUP is empty, not merely that the leader exited. After the leader exits (or after a kill) the supervisor enumerates the live
processes whose process group is the recorded pgid; survivors are killed (SIGKILL to the group) and reaped by polling until the group is empty or
a bounded wait expires; the receipt records `descendants_after_leader_exit` and `group_empty_at_receipt`; a group that cannot be emptied is
CLEANUP_UNRESOLVED (charged at max permitted by the ledger tool). Only processes in the RECORDED group are ever signalled.

    python -m gbidi.supervise --ledger L.jsonl --scope S --job NAME [--timeout S] [--mem-gib G] [--cwd DIR] [--stdout F] [--stderr F] [--env K=V]... -- cmd..."""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, signal
import psutil

GRACE_S = 4.0; GROUP_WAIT_S = 10.0


def tree_rss(p):
    try:
        return sum((q.memory_info().rss for q in [p] + p.children(recursive=True) if q.is_running()), 0)
    except psutil.Error:
        return 0


def group_members(pgid, exclude_pid=None):
    """live, non-zombie processes whose process group is pgid (the recorded group only)"""
    out = []
    for pid in psutil.pids():
        if pid == exclude_pid:
            continue
        try:
            if os.getpgid(pid) == pgid:
                pr = psutil.Process(pid)
                if pr.status() != psutil.STATUS_ZOMBIE:
                    out.append(pid)
        except (ProcessLookupError, PermissionError, psutil.Error):
            continue
    return out


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
    proc = None; pgid = None; launching = False; pending_signal = None; cleanup_unresolved = False; error = None
    peak = 0; overshoot = 0; outcome = "COMPLETED"; samples = 0; rc = None; survivors = 0; group_empty = None
    def killgroup():
        nonlocal pgid
        if pgid is None and proc is not None:
            pgid = proc.pid
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    def stop(reason):
        nonlocal outcome
        outcome = reason; killgroup()
    def on_term(signum, frame):
        nonlocal pending_signal
        pending_signal = signum
        if launching:
            return
        stop("SUPERVISOR_SIGNAL_%d" % signum); raise KeyboardInterrupt()
    launching = True
    signal.signal(signal.SIGTERM, on_term); signal.signal(signal.SIGINT, on_term)
    append(a.ledger, {"kind": "START", "jid": jid, "scope": a.scope, "job": a.job, "cmd": cmd, "cwd": a.cwd or os.getcwd(), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "supervisor_pid": os.getpid(), "timeout_s": a.timeout, "mem_cap_gib": a.mem_gib, "max_permitted_charge_s": maxcharge, "supervisor": "gbidi.supervise v2 (group-empty completion)"})
    try:
        if pending_signal is not None:
            launching = False; on_term(pending_signal, None)
        try:
            try:
                proc = subprocess.Popen(cmd, cwd=a.cwd, stdout=so or sys.stdout, stderr=se or sys.stderr, env=env, start_new_session=True)
            except (OSError, ValueError) as ex:
                outcome = "LAUNCH_FAILED"; error = "%s: %s" % (type(ex).__name__, ex); raise
            pgid = proc.pid
            append(a.ledger, {"kind": "SPAWNED", "jid": jid, "job": a.job, "pid": proc.pid, "pgid": pgid, "spawn_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        finally:
            launching = False
        if pending_signal is not None:
            on_term(pending_signal, None)
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
    except (OSError, ValueError) as ex:
        rc = None
        if outcome == "COMPLETED":
            outcome = "SUPERVISOR_ERROR_AFTER_LAUNCH"; error = "%s: %s" % (type(ex).__name__, ex)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN); signal.signal(signal.SIGINT, signal.SIG_IGN)
        if proc is not None and proc.poll() is None:
            stop(outcome if outcome != "COMPLETED" else "SUPERVISOR_EXIT_WITH_LIVE_CHILD")
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
            rc = proc.returncode
        leader_alive = proc is not None and proc.poll() is None
        # the OWNED GROUP must be empty: the leader's exit is not the job's end (review R2-08)
        if pgid is not None:
            rest = group_members(pgid, exclude_pid=None); survivors = len(rest)
            if rest:
                if outcome == "COMPLETED":
                    outcome = "COMPLETED_LEADER_EXIT_SURVIVORS_KILLED"
                killgroup(); t_end = time.monotonic() + GROUP_WAIT_S
                while time.monotonic() < t_end and group_members(pgid):
                    time.sleep(0.02)
            group_empty = not group_members(pgid)
        cleanup_unresolved = leader_alive or (group_empty is False)
        outcome_before_cleanup = outcome
        if cleanup_unresolved:
            outcome = "CLEANUP_UNRESOLVED"
        wall = time.monotonic() - m0
        append(a.ledger, {"kind": "RECEIPT", "jid": jid, "scope": a.scope, "job": a.job, "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "wall_s": wall, "returncode": rc, "outcome": outcome, "outcome_before_cleanup": outcome_before_cleanup, "cleanup_unresolved": cleanup_unresolved, "descendants_after_leader_exit": survivors, "group_empty_at_receipt": group_empty, "launch_error": (error if outcome_before_cleanup == "LAUNCH_FAILED" else None), "error": error, "pending_signal": pending_signal,
                           "peak_tree_rss_bytes": peak, "rss_samples": samples, "sampling_interval_s": a.interval, "mem_cap_gib": a.mem_gib, "mem_overshoot_bytes": overshoot, "timeout_s": a.timeout, "pid": (proc.pid if proc is not None else None), "pgid": pgid,
                           "enforcement": "sampled process-tree RSS (best effort, not an allocator cap); SIGKILL of the RECORDED process group on threshold, deadline + grace, supervisor signal or survivors after the leader's exit; cancellation deferred across the launch boundary; completion = recorded group empty; wall measured after cleanup"})
        print(json.dumps({"job": a.job, "wall_s": round(wall, 3), "rc": rc, "outcome": outcome, "peak_MB": round(peak / 1e6, 1), "survivors": survivors}), file=sys.stderr)
    sys.exit(0 if outcome == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
