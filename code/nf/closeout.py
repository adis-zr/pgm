"""Append-only closeout receipt. Every post-run action (report generation, replay, archive build/validation) appends one record with its
wall/CPU and the sha256 of the frozen numerical records it read, so reproducing the report never mutates its own inputs.
  python -m nf.closeout report <run_dir>          → regenerate REPORT.md/tables.json and append a receipt record
  python -m nf.closeout note   <run_dir> <phase> <json>  → append an arbitrary charged record (archive, validation, implementation wall)"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import os, json, time, hashlib, resource
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nf.report import write_report

FROZEN_RECORDS = ["events.jsonl", "state.json", "lock.json", "stage_b/witness.json", "stage_b/checker_kernel.json", "stage_b/checker_verdict.json", "control/control_gate.json", "input_main.txt"]

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def frozen_hashes(R): return {f: sha(os.path.join(R, f)) for f in FROZEN_RECORDS if os.path.exists(os.path.join(R, f))}
def append(R, rec):
    f = open(os.path.join(R, "CLOSEOUT_RECEIPT.jsonl"), "a"); f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **rec}, default=str) + "\n"); f.flush(); os.fsync(f.fileno()); f.close()

def report(R):
    R = os.path.abspath(R); before = frozen_hashes(R); t0 = time.monotonic(); r0 = resource.getrusage(resource.RUSAGE_SELF); outcome = write_report(R); r1 = resource.getrusage(resource.RUSAGE_SELF); after = frozen_hashes(R)
    rec = {"phase": "report_generation", "outcome": outcome, "wall_s": time.monotonic() - t0, "cpu_s": (r1.ru_utime + r1.ru_stime) - (r0.ru_utime + r0.ru_stime), "frozen_inputs_sha256": before, "frozen_inputs_unchanged": before == after, "report_sha256": sha(os.path.join(R, "REPORT.md")), "tables_sha256": sha(os.path.join(R, "tables.json"))}
    append(R, rec); return rec

if __name__ == "__main__":
    if sys.argv[1] == "report": print(json.dumps(report(sys.argv[2]), indent=1, default=str))
    elif sys.argv[1] == "note": append(os.path.abspath(sys.argv[2]), {"phase": sys.argv[3], **json.loads(sys.argv[4])}); print("appended")
