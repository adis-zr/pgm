"""AFTER controls for the third review (same fixtures as gbidi_review.repro_r3; independent truths) on the closed-out V2 source.    python -m gbidi_review.after_r3 OUT"""
from __future__ import annotations
import os, sys, json, time, traceback
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from gbidi_review import repro_r3 as RR
from gbidi import executor as EX


def main(out):
    RR.OUT = out; os.makedirs(out, exist_ok=True); rep = {"purpose": "AFTER controls, third review, on the closed-out V2 source", "git_head": os.popen("git -C %s rev-parse HEAD" % HERE).read().strip(), "kernel": EX.sha_file(EX.LIB), "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for name, fn in (("V2_V1_source_substitution", RR.v1_substitution), ("V2_V2_crossed_zero_rows", RR.v2_crossed_zero), ("V2_P1_mandatory_clock", RR.p1_clock), ("H1_H2_H4_harness", RR.h1_h2_h4_harness), ("H3_nested_supervisor", RR.h3_nested), ("RT_caps_poll", RR.rt_caps_poll)):
        t = time.monotonic()
        try:
            rep[name] = fn()
        except Exception:
            rep[name] = {"SCRIPT_ERROR": traceback.format_exc()[-2500:]}
        rep[name + "_s"] = time.monotonic() - t; print(name, "%.2fs" % rep[name + "_s"], flush=True)
    json.dump(rep, open(os.path.join(out, "AFTER_R3_RESULTS.json"), "w"), indent=1, default=str); print(json.dumps({k: v for k, v in rep.items() if not k.endswith("_s")}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))
