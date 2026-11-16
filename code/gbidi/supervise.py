"""Charging SUPERVISOR for the GENERAL_BIDI_V2 round (the pinned adp/census/supervise.py is unchanged). START / SPAWNED / RECEIPT protocol, deferred
cancellation, kill-and-reap before the charged wall, completion = the OWNED WORK is gone:
  * the immediate child runs in its own session / process group (start_new_session); after the leader exits (or after a kill) every live process of
    that RECORDED group is killed and reaped;
  * NESTED OWNERSHIP (third review H3): the ROOT supervisor creates an ownership directory `<ledger>.owned/<jid>/` and passes it to the child's
    environment (GBIDI_OWNER_DIR) together with its own attempt id (GBIDI_PARENT_JID). Every nested gbidi.supervise appends {jid, parent_jid, ledger,
    pid, pgid} to `<dir>/groups.jsonl` right after its SPAWNED record and forwards the SAME directory to its own child, so the whole tree registers in
    one place. At finalisation EVERY supervisor reconciles ITS OWN SUBTREE (the registrations whose parent chain leads to its jid): it kills + reaps
    every registered group of the subtree that is still alive, writes a RECEIPT stamped written_by_parent into the nested ledger for any registered
    attempt whose own receipt is missing (outcome PARENT_CLEANUP_KILL), and records nested_groups_registered / killed / live_at_receipt; any owned
    process that cannot be shown gone makes the attempt CLEANUP_UNRESOLVED.
  * parent_jid is recorded in START and RECEIPT so the closeout accounts each outer attempt with ITS OWN children (H4).
Survivor DIAGNOSTICS (16 Nov 2026, after admission_v6 / v9 of the CQR candidate): every process found alive in the owned group after the leader's exit is
described (pid, ppid, name, cmdline, status, age, relation to the leader) in the receipt's survivor_details BEFORE it is killed; the outcome, the kill and the
gate's refusal of any non-COMPLETED outcome are unchanged.
Only processes whose recorded group ids were registered by this job's tree are ever signalled; a recycled pid is never killed by pid alone (group
membership is re-checked with os.getpgid immediately before the signal).

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


def append(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n"); f.flush(); os.fsync(f.fileno())


def describe_members(pids, leader_pid=None):
    """retained diagnostics for processes found alive in the owned group after the leader's exit (pid, ppid, name, cmdline, status, age, relation to the leader);
    best effort: a process that disappears while being described is recorded as GONE_WHILE_DESCRIBING. Recorded BEFORE the kill; the policy itself is unchanged"""
    out = []
    for pid in pids:
        d = {"pid": pid}
        try:
            pr = psutil.Process(pid)
            with pr.oneshot():
                d.update({"ppid": pr.ppid(), "name": pr.name(), "status": pr.status(), "create_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(pr.create_time())),
                          "age_s": round(time.time() - pr.create_time(), 3), "cmdline": " ".join(pr.cmdline())[:300], "parent_name": (pr.parent().name() if pr.parent() is not None else None),
                          "relation": ("LEADER_STILL_LISTED" if pid == leader_pid else ("CHILD_OF_LEADER" if leader_pid is not None and pr.ppid() == leader_pid else "ORPHANED_OR_DEEPER"))})
        except (ProcessLookupError, psutil.NoSuchProcess):
            d["status"] = "GONE_WHILE_DESCRIBING"
        except (PermissionError, psutil.Error) as ex:
            d["status"] = "UNDESCRIBABLE: %s" % type(ex).__name__
        out.append(d)
    return out


def kill_group_and_wait(pgid, wait_s=GROUP_WAIT_S):
    """SIGKILL every live member of the recorded group (membership re-checked at signal time), reap by polling; returns the survivors"""
    for pid in group_members(pgid):
        try:
            if os.getpgid(pid) == pgid:
                os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    t_end = time.monotonic() + wait_s
    while time.monotonic() < t_end and group_members(pgid):
        for pid in group_members(pgid):
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        time.sleep(0.02)
    return group_members(pgid)


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
    parent_jid = os.environ.get("GBIDI_PARENT_JID"); root_owner_dir = os.environ.get("GBIDI_OWNER_DIR")
    own_dir = root_owner_dir or (a.ledger + ".owned/" + jid.replace("|", "_").replace(":", "_").replace("/", "_")); os.makedirs(own_dir, exist_ok=True)
    groups_file = os.path.join(own_dir, "groups.jsonl"); env["GBIDI_OWNER_DIR"] = own_dir; env["GBIDI_PARENT_JID"] = jid
    maxcharge = (a.timeout + GRACE_S) if a.timeout is not None else None
    proc = None; pgid = None; launching = False; pending_signal = None; error = None
    peak = 0; overshoot = 0; outcome = "COMPLETED"; samples = 0; rc = None; survivors = 0; survivor_details = None; survivor_detect_utc = None; survivor_leader_rc = None; survivor_leader_exit_to_detect_s = None; group_empty = None; nested = {"registered": 0, "killed": 0, "live_at_receipt": 0, "receipts_written_by_parent": 0}
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
    append(a.ledger, {"kind": "START", "jid": jid, "scope": a.scope, "job": a.job, "cmd": cmd, "cwd": a.cwd or os.getcwd(), "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "supervisor_pid": os.getpid(), "timeout_s": a.timeout, "mem_cap_gib": a.mem_gib, "max_permitted_charge_s": maxcharge, "parent_jid": parent_jid, "owner_dir": own_dir, "supervisor": "gbidi.supervise v3 (owned-tree completion)"})
    try:
        if pending_signal is not None:
            launching = False; on_term(pending_signal, None)
        try:
            try:
                proc = subprocess.Popen(cmd, cwd=a.cwd, stdout=so or sys.stdout, stderr=se or sys.stderr, env=env, start_new_session=True)
            except (OSError, ValueError) as ex:
                outcome = "LAUNCH_FAILED"; error = "%s: %s" % (type(ex).__name__, ex); raise
            pgid = proc.pid
            append(a.ledger, {"kind": "SPAWNED", "jid": jid, "job": a.job, "pid": proc.pid, "pgid": pgid, "spawn_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "parent_jid": parent_jid})
            append(groups_file, {"jid": jid, "parent_jid": parent_jid, "ledger": os.path.abspath(a.ledger), "job": a.job, "pid": proc.pid, "pgid": pgid, "supervisor_pid": os.getpid(), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})      # register in the tree's ownership file
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
        if pgid is not None:
            rest = group_members(pgid); survivors = len(rest)
            if rest:
                survivor_details = describe_members(rest, leader_pid=(proc.pid if proc is not None else None)); survivor_detect_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                survivor_leader_rc = rc; survivor_leader_exit_to_detect_s = round(time.monotonic() - m0, 3)
                if outcome == "COMPLETED":
                    outcome = "COMPLETED_LEADER_EXIT_SURVIVORS_KILLED"
                kill_group_and_wait(pgid)
            group_empty = not group_members(pgid)
        # ---- nested ownership: EVERY supervisor reconciles its own subtree (registrations whose parent chain leads to this jid)
        nested_live = []
        if os.path.exists(groups_file):
            allregs = [json.loads(l) for l in open(groups_file)]; parent_of = {g["jid"]: g.get("parent_jid") for g in allregs}
            def in_subtree(j):
                seen = set()
                while j is not None and j not in seen:
                    seen.add(j); j = parent_of.get(j)
                    if j == jid:
                        return True
                return False
            regs = [g for g in allregs if g["jid"] != jid and in_subtree(g["jid"])]; nested["registered"] = len(regs)
            for g in regs:
                members = group_members(g["pgid"])
                if members:
                    nested["killed"] += 1; kill_group_and_wait(g["pgid"])
                    if outcome == "COMPLETED":
                        outcome = "COMPLETED_NESTED_SURVIVORS_KILLED"
                    still = group_members(g["pgid"])
                    if still:
                        nested_live.append({"jid": g["jid"], "pgid": g["pgid"], "pids": still})
                try:
                    led = g["ledger"]; have = any(json.loads(l).get("kind") == "RECEIPT" and json.loads(l).get("jid") == g["jid"] for l in open(led)) if os.path.exists(led) else False
                    if not have:
                        append(led, {"kind": "RECEIPT", "jid": g["jid"], "scope": "nested", "job": g["job"], "start_utc": g["utc"], "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "wall_s": None, "returncode": None, "outcome": "PARENT_CLEANUP_KILL", "outcome_before_cleanup": None, "cleanup_unresolved": bool(group_members(g["pgid"])), "written_by_parent": jid, "parent_jid": jid, "pgid": g["pgid"], "pid": g["pid"], "note": "the nested supervisor left no receipt; its registered group was killed and reaped by the root owner; wall UNKNOWN -> charged at max permitted by the ledger tool"})
                        nested["receipts_written_by_parent"] += 1
                except OSError:
                    pass
            nested["live_at_receipt"] = len(nested_live)
        cleanup_unresolved = leader_alive or (group_empty is False) or bool(nested_live)
        outcome_before_cleanup = outcome
        if cleanup_unresolved:
            outcome = "CLEANUP_UNRESOLVED"
        wall = time.monotonic() - m0
        append(a.ledger, {"kind": "RECEIPT", "jid": jid, "scope": a.scope, "job": a.job, "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0)), "end_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "parent_jid": parent_jid,
                           "wall_s": wall, "returncode": rc, "outcome": outcome, "outcome_before_cleanup": outcome_before_cleanup, "cleanup_unresolved": cleanup_unresolved, "descendants_after_leader_exit": survivors, "survivor_details": survivor_details, "survivor_detect_utc": survivor_detect_utc, "survivor_leader_returncode": survivor_leader_rc, "survivor_detect_wall_s": survivor_leader_exit_to_detect_s, "group_empty_at_receipt": group_empty, "nested_groups_registered": nested["registered"], "nested_groups_killed": nested["killed"], "nested_groups_live_at_receipt": nested["live_at_receipt"], "nested_receipts_written_by_parent": nested["receipts_written_by_parent"], "nested_live": nested_live, "owner_dir": own_dir, "launch_error": (error if outcome_before_cleanup == "LAUNCH_FAILED" else None), "error": error, "pending_signal": pending_signal,
                           "peak_tree_rss_bytes": peak, "rss_samples": samples, "sampling_interval_s": a.interval, "mem_cap_gib": a.mem_gib, "mem_overshoot_bytes": overshoot, "timeout_s": a.timeout, "pid": (proc.pid if proc is not None else None), "pgid": pgid,
                           "enforcement": "sampled process-tree RSS (best effort, not an allocator cap); SIGKILL of RECORDED groups only (membership re-checked at signal time) on threshold, deadline + grace, supervisor signal, survivors after the leader's exit or registered nested groups still alive; cancellation deferred across the launch boundary; completion = every owned group empty; wall measured after cleanup"})
        print(json.dumps({"job": a.job, "wall_s": round(wall, 3), "rc": rc, "outcome": outcome, "peak_MB": round(peak / 1e6, 1), "survivors": survivors, "survivor_details": survivor_details, "nested": nested}), file=sys.stderr)
    sys.exit(0 if outcome == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
