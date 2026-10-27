"""Independent supervisor for native subprocesses + contention monitor (CLAUDE_CODE_SPEC.md "Durable progress and complete accounting").

run_native: starts the child in its own process group, polls RSS/CPU every 0.1 s, writes a heartbeat record at least every 1 s (spec: 5 s)
to resources.jsonl with phase/pass/iteration/frequency/last-bound parsed from the child's progress file, kills the tree on the deadline
(SIGTERM, then SIGKILL after 2 s) or the RSS cap, and returns a terminal record with wall, worker-tree CPU (rusage of reaped children), peak RSS.

ContentionMonitor: samples every process on the host once per second; a foreign process (not in the worker tree, not this supervisor) at
>= 50 % of one core for 5 consecutive samples marks the cell INELIGIBLE (samples logged)."""
from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import threading
import time

import psutil

POLL_S = 0.1
HB_S = 1.0


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Journal:
    def __init__(self, path):
        self.path = path; self.fh = open(path, "a"); self.seq = 0
    def write(self, rec: dict):
        self.seq += 1; rec = {"seq": self.seq, "at": now_iso(), "mono": time.monotonic(), **rec}
        self.fh.write(json.dumps(rec, default=str) + "\n"); self.fh.flush(); os.fsync(self.fh.fileno())
    def close(self):
        self.fh.close()


def _tree(root):
    try:
        return [root] + root.children(recursive=True)
    except psutil.Error:
        return []


def _sample(root):
    rss = 0; cpu = 0.0; alive = False
    for p in _tree(root):
        try:
            with p.oneshot():
                rss += p.memory_info().rss; t = p.cpu_times(); cpu += t.user + t.system; alive = True
        except psutil.Error:
            pass
    return rss, cpu, alive


def _last_progress(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 400)); tail = f.read().decode(errors="replace").strip().split("\n")
        return tail[-1] if tail else None
    except OSError:
        return None


class ContentionMonitor:
    """Background sampler of foreign CPU use.  foreign = any pid not in `own` (the supervisor and the worker trees it launched)."""
    def __init__(self, journal: Journal, threshold_pct=50.0, consecutive=5):
        self.j = journal; self.thr = threshold_pct; self.k = consecutive; self.own = {os.getpid()}; self.lock = threading.Lock()
        self.streak = {}; self.violations = []; self.samples = 0; self.stop = threading.Event(); self.thread = None
    def add_tree(self, root_pid):
        with self.lock:
            try:
                for p in _tree(psutil.Process(root_pid)): self.own.add(p.pid)
            except psutil.Error:
                pass
    def _run(self):
        for p in psutil.process_iter(["pid"]):
            try: p.cpu_percent(None)
            except psutil.Error: pass
        while not self.stop.wait(1.0):
            busy = []
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    c = p.cpu_percent(None)
                except psutil.Error:
                    continue
                with self.lock:
                    own = p.pid in self.own
                if not own and c >= self.thr:
                    busy.append((p.pid, p.info["name"], round(c, 1)))
            self.samples += 1
            seen = set()
            for pid, name, c in busy:
                seen.add(pid); self.streak[pid] = self.streak.get(pid, 0) + 1
                if self.streak[pid] == self.k:
                    v = {"pid": pid, "name": name, "cpu_percent": c, "consecutive_s": self.k, "at": now_iso()}; self.violations.append(v)
                    self.j.write({"kind": "contention_violation", **v})
            for pid in list(self.streak):
                if pid not in seen: del self.streak[pid]
            if busy:
                self.j.write({"kind": "contention_sample", "busy": busy})
    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True); self.thread.start()
    def finish(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=3)
        return {"samples": self.samples, "violations": self.violations, "eligible_by_foreign_cpu": not self.violations}


def run_native(cmd, cwd, journal: Journal, deadline_s: float, rss_cap_bytes: int, meta: dict, progress_path=None, monitor: ContentionMonitor | None = None, env=None):
    t0 = time.monotonic(); ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    journal.write({"kind": "subcall_start", "cmd": cmd, "deadline_s": deadline_s, "rss_cap_bytes": rss_cap_bytes, **meta})
    stderr_path = os.path.join(cwd, f"{meta.get('phase', 'native')}_stderr.txt")
    with open(stderr_path, "ab") as se:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=se, stderr=se, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    root = psutil.Process(proc.pid)
    if monitor: monitor.add_tree(proc.pid)
    peak = 0; last_hb = t0; kill_reason = None; term_at = None
    while True:
        rc = proc.poll(); now = time.monotonic()
        if rc is None:
            rss, cpu, alive = _sample(root); peak = max(peak, rss)
            if rss > rss_cap_bytes and kill_reason is None:
                kill_reason = "memory"; journal.write({"kind": "cap_crossed", "cap": "rss", "observed": rss, **meta})
                os.killpg(proc.pid, signal.SIGKILL)
            if now - t0 > deadline_s and kill_reason is None:
                kill_reason = "deadline"; term_at = now; journal.write({"kind": "deadline_sigterm", "elapsed_s": now - t0, **meta}); os.killpg(proc.pid, signal.SIGTERM)
            if kill_reason == "deadline" and term_at and now - term_at > 2.0:
                os.killpg(proc.pid, signal.SIGKILL)
            if now - last_hb >= HB_S:
                last_hb = now
                journal.write({"kind": "heartbeat", "elapsed_s": round(now - t0, 3), "tree_cpu_s": round(cpu, 3), "tree_rss_bytes": rss, "progress": _last_progress(progress_path), **meta})
            time.sleep(POLL_S)
        else:
            break
    wall = time.monotonic() - t0; ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_children = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
    rec = {"kind": "subcall_terminal", "exit_code": proc.returncode, "kill_reason": kill_reason, "wall_s": wall, "cpu_s": cpu_children, "cpu_over_wall": cpu_children / wall if wall > 0 else None, "peak_rss_bytes": peak, "progress_last": _last_progress(progress_path), "stderr_path": stderr_path, **meta}
    journal.write(rec)
    return rec


class PhaseClock:
    """Charged Python phases (gate, verification, serialisation): wall + this process's CPU delta."""
    def __init__(self, name):
        self.name = name; self.w0 = time.monotonic(); r = resource.getrusage(resource.RUSAGE_SELF); self.c0 = r.ru_utime + r.ru_stime
    def stop(self):
        r = resource.getrusage(resource.RUSAGE_SELF); return {"phase": self.name, "wall_s": time.monotonic() - self.w0, "cpu_s": (r.ru_utime + r.ru_stime) - self.c0}
