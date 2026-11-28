"""Supervised runner: outer deadline, process-TREE memory sampling, heartbeat.

The wrapper reports elapsed time even while the child is quiet. Timing ends only
after durable result/checker files have been written.
"""
from __future__ import annotations
import subprocess, time, os, sys, json, threading, signal

HEARTBEAT_S = 30.0
MEM_SAMPLE_S = 0.5


def _tree_rss_kib(root_pid):
    """Whole-tree RSS via ps over the descendant set. Sampled, not continuous:
    a short spike between samples can be missed. Stated as a limitation."""
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,rss="], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return None, 0
    kids, rss = {}, {}
    for line in out.splitlines():
        f = line.split()
        if len(f) != 3:
            continue
        try:
            pid, ppid, r = int(f[0]), int(f[1]), int(f[2])
        except ValueError:
            continue
        kids.setdefault(ppid, []).append(pid)
        rss[pid] = r
    seen, stack, tot = set(), [root_pid], 0
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        tot += rss.get(p, 0)
        stack.extend(kids.get(p, []))
    return tot, len(seen)


def run(cmd, cwd, log_path, deadline_s, mem_limit_kib, env=None, label=""):
    """Returns a record. Kills the tree on deadline or memory breach."""
    rec = {"label": label, "cmd": cmd, "cwd": cwd, "deadline_s": deadline_s,
           "mem_limit_kib": mem_limit_kib}
    t0 = time.time()
    e = dict(os.environ)
    if env:
        e.update(env)
    lf = open(log_path, "w", buffering=1)
    lf.write("# cmd: %s\n# cwd: %s\n# started: %s\n"
             % (" ".join(cmd), cwd, time.strftime("%Y-%m-%dT%H:%M:%S%z")))
    lf.flush()
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT,
                            env=e, start_new_session=True)
    peak_kib, peak_procs, samples = 0, 0, 0
    outcome = "COMPLETED"
    next_hb = t0 + HEARTBEAT_S
    try:
        while True:
            if proc.poll() is not None:
                break
            now = time.time()
            el = now - t0
            if el > deadline_s:
                outcome = "TIMEOUT"
                lf.write("\n# WRAPPER: outer deadline %.1fs exceeded at %.1fs; killing tree\n"
                         % (deadline_s, el)); lf.flush()
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
                proc.wait(timeout=30)
                break
            k, np_ = _tree_rss_kib(proc.pid)
            samples += 1
            if k is not None:
                if k > peak_kib:
                    peak_kib, peak_procs = k, np_
                if mem_limit_kib and k > mem_limit_kib:
                    outcome = "MEMORY_STOP"
                    lf.write("\n# WRAPPER: tree RSS %d KiB exceeded limit %d KiB at %.1fs; killing tree\n"
                             % (k, mem_limit_kib, el)); lf.flush()
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()
                    proc.wait(timeout=30)
                    break
            if now >= next_hb:
                lf.write("# WRAPPER HEARTBEAT t=%.1fs tree_rss=%s KiB procs=%s\n"
                         % (el, k, np_)); lf.flush()
                print("  [heartbeat] %s t=%.1fs tree_rss=%s KiB" % (label, el, k), flush=True)
                next_hb = now + HEARTBEAT_S
            time.sleep(MEM_SAMPLE_S)
    finally:
        pass
    rc = proc.returncode
    el = time.time() - t0
    lf.write("\n# WRAPPER: rc=%s elapsed=%.3fs peak_tree_rss=%d KiB outcome=%s\n"
             % (rc, el, peak_kib, outcome)); lf.flush(); lf.close()
    if outcome == "COMPLETED" and rc != 0:
        outcome = "LAUNCH_FAILURE" if rc in (126, 127) else "NONZERO_EXIT"
    rec.update({"returncode": rc, "elapsed_s": el, "peak_tree_rss_kib": peak_kib,
                "peak_tree_procs": peak_procs, "mem_samples": samples,
                "mem_sampling_interval_s": MEM_SAMPLE_S,
                "mem_limitation": "ps-based whole-tree sampling every %.1fs; sub-interval spikes can be missed. This IS whole-tree (root plus all descendants), not a native-child high-water mark." % MEM_SAMPLE_S,
                "outcome": outcome, "log": log_path})
    return rec
