"""Bounded preflight controls for the complete-query pilot (REPAIR_AND_VALIDATION.md as amended).

Gates, in order; each blocks the next:
  G1 build + floating-point probes
  G2 full-grid domain check (exact rational, addendum §2)
  G3 small-fixture coverage: both H4 fixtures and all four product fixtures through ALL FOUR kernel paths
     including h4rect --forward, against the 512-bit reference; count replay; returned checker exponent;
     both complex coordinates; both responses
  G4 all SEVEN malformed-record rejection paths
  G5 cache round-trip and rejection conformance
  G6 synthetic aggregation wrapper controls
Nothing here evaluates an H4 grid node or runs a timed invocation."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model
from h4q.aggregate import SignState

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(CODE, "build")
Q_SQRT3_128 = Fr(11031521092846173, 72057594037927936)      # addendum: q^2 > 3/128, independently checked


def g1_build_and_probes(journal):
    INC = ["-I/opt/homebrew/opt/gmp/include", "-I/opt/homebrew/opt/mpfr/include"]
    LIB = ["-L/opt/homebrew/opt/gmp/lib", "-L/opt/homebrew/opt/mpfr/lib", "-lmpfr", "-lgmp"]
    FLAGS = ["-O2", "-std=c++17", "-fno-fast-math", "-ffp-contract=off"]
    out = {"gate": "G1", "builds": {}, "probes": {}}
    for k in ("h4point", "h4pcheck", "h4rect"):
        cmd = ["c++", *FLAGS, *(INC if k == "h4rect" else []), os.path.join(CODE, "native", f"{k}.cpp"),
               "-o", os.path.join(BUILD, k), *(LIB if k == "h4rect" else [])]
        t = time.monotonic(); r = subprocess.run(cmd, capture_output=True, text=True); dt = time.monotonic() - t
        out["builds"][k] = {"rc": r.returncode, "wall_s": dt, "stderr": r.stderr[:300],
                            "binary_sha256": hashlib.sha256(open(os.path.join(BUILD, k), "rb").read()).hexdigest() if r.returncode == 0 else None}
        journal({"gate": "G1", "step": f"build_{k}", "rc": r.returncode, "wall_s": round(dt, 3)})
    for k in ("h4point", "h4pcheck"):
        r = subprocess.run([os.path.join(BUILD, k), "--probes-only"], capture_output=True, text=True)
        out["probes"][k] = json.loads(r.stdout) if r.returncode == 0 else {"rc": r.returncode}
    out["all_ok"] = (all(b["rc"] == 0 for b in out["builds"].values())
                     and all(all(p["ok"] for p in v["probes"]) for v in out["probes"].values()))
    return out


def g2_domain_check(journal):
    """exact full-grid field bound; the addendum's formula and value"""
    m = Model(128, 1); q = Q_SQRT3_128
    assert q * q > Fr(3, 128), "the rational upper bound for sqrt(3/128) must satisfy q^2 > 3/128"
    best = Fr(0); arg = None
    for s in (1, -1):
        for i in range(1, m.n):                      # site 0 is the pinned source
            u00, u01 = m.u[0][0], m.u[0][1]; ui0, ui1 = m.u[i][0], m.u[i][1]
            core = m.h[i] + (3 * s * u00 * ui0 + 2 * s * u01 * ui1) / 128
            v = abs(core) + 19 * q * abs(ui0) + 2 * abs(ui1)
            if v > best: best, arg = v, (s, i)
    expected = Fr(362946080770569546580187, 75557863725914323419136)
    out = {"gate": "G2", "q": str(q), "q_squared_exceeds_3_over_128": q * q > Fr(3, 128),
           "exact_max": str(best), "as_float": float(best), "attained_at": {"sign": arg[0], "site": arg[1]},
           "matches_addendum_value": best == expected, "below_10": best < 10,
           "prefix_sum_exponent_bound": "2^2688 (the proved 2^(21n) bound from TABLES_AND_DOMAIN; the design's 2^1539 omitted the path count)",
           "inside_mpfr_exponent_range": 2688 < 16384,
           "theta_lt_2_is_NOT_the_H4_bound": "that bound belongs to the normalization-free direct-query contract"}
    out["all_ok"] = out["matches_addendum_value"] and out["below_10"] and out["inside_mpfr_exponent_range"]
    journal({"gate": "G2", "exact_max": str(best), "all_ok": out["all_ok"]})
    return out


def g3_small_fixture_coverage(journal, packet):
    """both H4 fixtures and all four product fixtures through all four kernel paths; delegates to the existing
    validated Stage A machinery plus the review-2 regression suite, which already covers count replay, the returned
    checker exponent, state initialisation, both coordinates and both responses, and the forward branch."""
    t = time.monotonic()
    env = {**os.environ, "H4A_PACKET": packet, "PYTHONPATH": CODE}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join(CODE, "tests", "test_h4a_review2.py")],
                       capture_output=True, text=True, cwd=CODE, env=env)
    dt = time.monotonic() - t
    out = {"gate": "G3", "rc": r.returncode, "wall_s": dt, "tail": r.stdout.strip().split("\n")[-1]}
    out["all_ok"] = r.returncode == 0
    journal({"gate": "G3", "rc": r.returncode, "wall_s": round(dt, 2), "tail": out["tail"]})
    return out


def g4_malformed_rejections(journal, prod_json, chk_json, cprod, cchk, grid, prob, arm="PP"):
    """all SEVEN previously identified malformed-record cases must reject through the production verifier"""
    import copy, tempfile
    from h4a import certs
    base = certs.verify_node(arm, prod_json, chk_json, cprod, cchk, grid, prob)
    P = certs.load_strict(prod_json); C = certs.load_strict(chk_json)
    def run(p2=None, c2=None, cpm=None, ccm=None, raw_prod=None):
        d = tempfile.mkdtemp()
        if raw_prod is not None: open(f"{d}/prod.json", "w").write(raw_prod)
        else: json.dump(p2 or P, open(f"{d}/prod.json", "w"))
        json.dump(c2 or C, open(f"{d}/chk.json", "w"))
        try:
            return certs.verify_node(arm, f"{d}/prod.json", f"{d}/chk.json", cpm or cprod, ccm or cchk, grid, prob)
        except ValueError as e:
            return {"verdict": "REJECTED", "failed_checks": [f"parser: {e}"]}
    cases = {}
    d1 = copy.deepcopy(C); d1["response"] = d1["response"] + [d1["response"][0]]
    cases["duplicate_checker_response"] = (run(c2=d1), "no_duplicate_response_records")
    p1 = copy.deepcopy(P); p1["channels"] = [p1["channels"][1], p1["channels"][0]] + p1["channels"][2:]
    cases["permuted_producer_channels"] = (run(p2=p1), "producer_channel_order_is_frozen")
    c1 = copy.deepcopy(C); c1["channels"] = [c1["channels"][1], c1["channels"][0]] + c1["channels"][2:]
    cases["permuted_checker_channels"] = (run(c2=c1), "checker_channel_order_is_frozen")
    p2_ = copy.deepcopy(P); p2_["probes_ok"] = False
    cases["false_probe_flag"] = (run(p2=p2_), "producer_probe_flag_not_false")
    p3 = copy.deepcopy(P); p3["kernel"] = "h4rect"
    cases["wrong_kernel_identity"] = (run(p2=p3), "producer_kernel_identity")
    raw = json.dumps(P); raw = raw.replace('{"kernel"', '{"kernel": "x", "kernel"', 1)
    cases["duplicate_json_key"] = (run(raw_prod=raw), "parser")
    class Empty: identity = "e" * 64; checks = {}
    cases["empty_cache_certificates"] = (run(cpm=Empty()), "producer_cache_certificates_present")
    out = {"gate": "G4", "baseline_verdict": base["verdict"], "cases": {}}
    for name, (res, expect) in cases.items():
        hit = any(expect in f for f in res["failed_checks"])
        out["cases"][name] = {"verdict": res["verdict"], "expected_check": expect, "named_check_fired": hit,
                              "failed": res["failed_checks"][:3]}
        journal({"gate": "G4", "case": name, "verdict": res["verdict"], "named_check_fired": hit})
    out["all_ok"] = base["verdict"] == "VERIFIED" and all(c["verdict"] == "REJECTED" and c["named_check_fired"]
                                                          for c in out["cases"].values())
    return out


def g5_cache_conformance(journal):
    t = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join(CODE, "tests", "test_h4q_cache.py")], capture_output=True, text=True, cwd=CODE,
                       env={**os.environ, "PYTHONPATH": CODE})
    out = {"gate": "G5", "rc": r.returncode, "wall_s": time.monotonic() - t, "tail": r.stdout.strip().split("\n")[-1]}
    out["all_ok"] = r.returncode == 0
    journal({"gate": "G5", "rc": r.returncode, "tail": out["tail"]})
    return out


def g6_aggregation_controls(journal):
    t = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        os.path.join(CODE, "tests", "test_h4q_aggregate.py")], capture_output=True, text=True, cwd=CODE,
                       env={**os.environ, "PYTHONPATH": CODE})
    out = {"gate": "G6", "rc": r.returncode, "wall_s": time.monotonic() - t, "tail": r.stdout.strip().split("\n")[-1]}
    out["all_ok"] = r.returncode == 0
    journal({"gate": "G6", "rc": r.returncode, "tail": out["tail"]})
    return out
