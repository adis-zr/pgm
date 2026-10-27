"""Saved-record replay for a diagnostic run directory.
  python -m nf.replay <run_dir>                 → hash/record replay: rebind input hash, re-run verify_stage_b on the SAVED kernel records (no arithmetic)
  python -m nf.replay <run_dir> --arithmetic    → additionally re-executes the CHECKER kernel at the saved center (fresh arithmetic; charged; never reruns center search)
Prints a JSON verdict; exit 0 iff everything binds."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import os, json, hashlib, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nf.check import verify_stage_b, verify_stage_c
from nf.model import main_walsh5

def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def replay(run_dir, arithmetic=False, build_dir=None):
    R = os.path.abspath(run_dir); L = json.load(open(os.path.join(R, "lock.json"))); W = json.load(open(os.path.join(R, "stage_b", "witness.json"))); CK = json.load(open(os.path.join(R, "stage_b", "checker_kernel.json")))
    out = {"run_dir": R, "kind": "arithmetic_replay" if arithmetic else "hash_record_replay"}
    inp = os.path.join(R, "input_main.txt"); out["input_main_sha256_matches_lock"] = os.path.exists(inp) and sha(inp) == L["input"]["canonical_sha256"]
    t0 = time.monotonic(); out["python_regeneration_sha256_matches_lock"] = main_walsh5().sha256() == L["input"]["canonical_sha256"]; out["python_regeneration_s"] = time.monotonic() - t0
    out["saved_checker_kernel_center_equals_witness_center"] = CK["center"] == W["center"]
    v = verify_stage_b(L, W, CK, L["input"]["canonical_sha256"], pins_expected=[]); out["saved_record_verdict"] = v["verdict"]; out["saved_record_failed_checks"] = v["failed_checks"]; out["checks_evaluated"] = len(v["checks"])
    if arithmetic:
        BUILD = build_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "build"); tmp = os.path.join(R, "replay_tmp"); os.makedirs(tmp, exist_ok=True); o = os.path.join(tmp, "checker_kernel_replay.json"); dp = os.path.join(tmp, "dump.txt")
        t0 = time.monotonic(); r = subprocess.run([os.path.join(BUILD, "nfcheck"), "--prec", str(L["frozen"]["checker_prec"]), "--gen", L["input"]["case_id"], "--n", str(L["input"]["n"]), "--query", str(L["input"]["query_index"]), "--center", ",".join(W["center"]), "--out", o, "--dump", dp], capture_output=True, text=True); out["checker_rerun_wall_s"] = time.monotonic() - t0; out["checker_rerun_exit"] = r.returncode
        if r.returncode == 0:
            CK2 = json.load(open(o)); gh = sha(dp); os.remove(dp); v2 = verify_stage_b(L, W, CK2, gh, pins_expected=[]); out["fresh_arithmetic_verdict"] = v2["verdict"]; out["fresh_arithmetic_failed_checks"] = v2["failed_checks"]
            out["fresh_kernel_identical_to_saved"] = {k: CK2[k] == CK[k] for k in ("q_query", "gradient", "s_query", "alpha_query")}
        else: out["fresh_arithmetic_verdict"] = "KERNEL_FAILED"; out["stderr"] = r.stderr[-500:]
    ok = out["input_main_sha256_matches_lock"] and out["python_regeneration_sha256_matches_lock"] and out["saved_checker_kernel_center_equals_witness_center"] and out["saved_record_verdict"] == "VERIFIED" and (not arithmetic or out.get("fresh_arithmetic_verdict") == "VERIFIED")
    out["all_bound"] = ok; return out

if __name__ == "__main__":
    res = replay(sys.argv[1], "--arithmetic" in sys.argv); print(json.dumps(res, indent=1, default=str)); sys.exit(0 if res["all_bound"] else 1)
