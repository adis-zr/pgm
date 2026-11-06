"""Supervised launcher with the pass's ONE allowance ledger (3,600 s of supervised computation, everything included:
controls, candidates + checkers, references, scoring, failed attempts). Each launch: refuse when the remaining allowance
cannot cover the requested deadline; run under the UNCHANGED ext.supervise.run (process-tree RSS cap, kill at the deadline,
no grace); persist the supervisor's record (the known charge) BEFORE any child artifact is parsed; charge the complete
spawn-to-exit wall once. Nested work (a child's own sub-processes) is inside the tree and counted once.
usage: supervised.py LEDGER.json KIND LABEL DEADLINE_S MEM_CAP_BYTES RECEIPT.json LOG -- CMD..."""
import sys, os, json, math, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from ext import supervise as SV

ALLOWANCE_S = 3600.0


def _jdump(obj, path):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, default=str); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)


def load(lp):
    if os.path.exists(lp):
        return json.load(open(lp))
    return {"allowance_s": ALLOWANCE_S, "charges": [], "unknown_charges": [], "note": "every supervised child's complete spawn-to-exit wall, charged once; refusals (not launched) recorded with zero charge"}


def charged(led):
    return sum(float(c["charged_s"]) for c in led["charges"])


def main(argv):
    lp, kind, label, deadline, mem, receipt, log = argv[0], argv[1], argv[2], float(argv[3]), int(argv[4]), argv[5], argv[6]
    assert argv[7] == "--"; cmd = argv[8:]
    led = load(lp)
    remaining = led["allowance_s"] - charged(led)
    if remaining < deadline:
        led.setdefault("refused_launches", []).append({"kind": kind, "label": label, "requested_deadline_s": deadline, "remaining_s": remaining, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        _jdump(led, lp); print(json.dumps({"label": label, "outcome": "NOT_LAUNCHED_ALLOWANCE", "remaining_s": remaining})); return 5
    entry = {"kind": kind, "label": label, "deadline_s": deadline, "mem_cap_bytes": mem, "command": cmd, "status": "STARTED", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "receipt": receipt}
    led["charges"].append(dict(entry, charged_s=deadline, provisional=True))      # the deadline is RESERVED (never a charge) until the exit is known
    _jdump(led, lp)
    sup = SV.run(cmd, cwd=HERE, log_path=log, deadline_s=deadline, mem_limit_kib=mem // 1024, env={"PYTHONPATH": HERE, "OMP_NUM_THREADS": "6", "MKL_NUM_THREADS": "6", "OPENBLAS_NUM_THREADS": "6", "VECLIB_MAXIMUM_THREADS": "6", "NUMEXPR_NUM_THREADS": "6"}, label=label)
    sup["limits"] = {"deadline_s": deadline, "mem_cap_bytes": mem, "grace_s": 0.0}
    _jdump(sup, receipt)                                          # the known charge is durable before anything else is read
    el = sup.get("elapsed_s")
    led = load(lp)
    row = next(c for c in reversed(led["charges"]) if c.get("provisional") and c["label"] == label)
    if not isinstance(el, (int, float)) or not math.isfinite(el) or el < 0:
        row.update({"status": "UNKNOWN_CHARGE", "charged_s": None}); led["unknown_charges"].append(label); _jdump(led, lp)
        print(json.dumps({"label": label, "outcome": "UNKNOWN_CHARGE"})); return 3
    row.update({"status": "TERMINAL", "charged_s": el, "provisional": False, "outcome": sup["outcome"], "returncode": sup["returncode"], "peak_tree_rss_kib": sup["peak_tree_rss_kib"], "ended": time.strftime("%Y-%m-%d %H:%M:%S")})
    _jdump(led, lp)
    print(json.dumps({"label": label, "outcome": sup["outcome"], "returncode": sup["returncode"], "elapsed_s": el, "peak_tree_rss_kib": sup["peak_tree_rss_kib"], "allowance_remaining_s": led["allowance_s"] - charged(led)}))
    return 0 if sup["outcome"] == "COMPLETED" and sup["returncode"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
