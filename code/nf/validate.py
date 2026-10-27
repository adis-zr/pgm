"""Stage A validation: fixed tiny fixtures against 256-bit enumeration, and the required rejection tests (CLAUDE_CODE_SPEC.md §6 Stage A).
Called by tests/test_nf_small.py (the one-command tiny validation) and recorded by the driver."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import os, json, subprocess, time, copy, hashlib
from fractions import Fraction as Fr
from .model import fixture_signed, fixture_zero_loading, fixture_unbalanced, FIXTURE_CENTERS, Model
from .reference import enumerate_laws
from .ivpy import fx
from . import certs
from .check import verify_stage_b, verify_stage_c

FIXTURES = {"FIX_SIGNED": lambda: fixture_signed(False), "FIX_SIGNED_EVIDENCE": lambda: fixture_signed(True), "FIX_ZERO_LOADING": fixture_zero_loading, "FIX_UNBALANCED": fixture_unbalanced}

def run_kernel(binary, args, cwd):
    t0 = time.monotonic(); r = subprocess.run([os.path.abspath(binary), *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "OMP_NUM_THREADS": "1"}); return r, time.monotonic() - t0

def block_diameters_pairs(M: Model):
    """D_b for strong-pair blocks {2d, 2d+1} of the alternating chain (free states only); D = 2 max(||a_i+a_j||, ||a_i-a_j||) over allowed sign pairs (upper bounds via sqrt_upper)"""
    out = []
    for d in range(M.n // 2):
        i, j = 2 * d, 2 * d + 1; ai = [M.A[l][i] if not M.pin[i] else Fr(0) for l in range(M.r)]; aj = [M.A[l][j] if not M.pin[j] else Fr(0) for l in range(M.r)]
        states = [(si, sj) for si in ((M.pin[i],) if M.pin[i] else (-1, 1)) for sj in ((M.pin[j],) if M.pin[j] else (-1, 1))]
        best = Fr(0)
        for s in states:
            for t in states:
                z2 = sum(((ai[l] * (s[0] - t[0]) + aj[l] * (s[1] - t[1])) ** 2 for l in range(M.r)), Fr(0)); best = max(best, z2)
        out.append(certs.sqrt_upper(best))
    return out

def run_fixture(name, build_dir, out_dir, prec_prod=128, prec_chk=192, prec_ref=256):
    M = FIXTURES[name](); c = FIXTURE_CENTERS[name]; os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "input.txt"); sha, nbytes = M.write(path); res = {"fixture": name, "n": M.n, "rank": M.r, "query": M.query, "pins": [(i, M.pin[i]) for i in range(M.n) if M.pin[i]], "center": [str(x) for x in c], "input_sha256": sha, "input_bytes": nbytes, "checks": {}, "timing_s": {}}
    t0 = time.monotonic(); ref = enumerate_laws(M, c, prec_ref); res["timing_s"]["enumeration_256"] = time.monotonic() - t0; res["enumerated_states"] = ref["states"]; res["energy_constant_dropped_in_enumeration"] = ref["energy_constant_dropped"]
    K = {}
    for k, prec in (("nfchain", prec_prod), ("nfcheck", prec_chk)):
        o = os.path.join(out_dir, f"{k}.json"); r, dt = run_kernel(os.path.join(build_dir, k), ["--prec", str(prec), "--file", path, "--center", ",".join(str(x) for x in c), "--out", o, "--moments", "--all-marginals"], out_dir)
        res["timing_s"][k] = dt
        if r.returncode != 0: res["checks"][f"{k}_ran"] = False; res[f"{k}_stderr"] = r.stderr; continue
        res["checks"][f"{k}_ran"] = True; K[k] = json.load(open(o))
    qr = [x.frac() for x in ref["q"]]; pr = [x.frac() for x in ref["p"]]; Mr = ref["M"].frac(); gr = [x.frac() for x in ref["gradient"]]
    res["reference"] = {"q_query": [str(v) for v in qr[M.query]], "p_query_target": [str(v) for v in pr[M.query]], "M": [str(v) for v in Mr], "gradient": [[str(a), str(b)] for a, b in gr]}
    for k, J in K.items():
        allq = [(fx(a), fx(b)) for a, b in J["all_marginals"]]
        res["checks"][f"{k}_query_index_bound"] = J["query_index"] == M.query
        res["checks"][f"{k}_all_singletons_contain_reference"] = len(allq) == M.n and all(allq[i][0] <= qr[i][0] and qr[i][1] <= allq[i][1] for i in range(M.n))
        res["checks"][f"{k}_pinned_sites_exact"] = all((allq[i] == (Fr(1), Fr(1))) if M.pin[i] > 0 else (allq[i] == (Fr(0), Fr(0))) if M.pin[i] < 0 else True for i in range(M.n))
        ql, qh = fx(J["q_query"][0]), fx(J["q_query"][1]); res["checks"][f"{k}_q_query_equals_marginal_at_query"] = (ql, qh) == allq[M.query]
        g = [(fx(a), fx(b)) for a, b in J["gradient"]]; res["checks"][f"{k}_gradient_contains_reference"] = all(g[l][0] <= gr[l][0] and gr[l][1] <= g[l][1] for l in range(M.r))
        Mi = J["M_actual"] if k == "nfchain" else J["M_actual"]["M"]; Ml, Mh = fx(Mi[0]), fx(Mi[1]); res["checks"][f"{k}_M_contains_reference"] = Ml <= Mr[0] and Mr[1] <= Mh
        res[f"{k}_M"] = [str(Ml), str(Mh)]; res[f"{k}_M_width"] = str(Mh - Ml); res[f"{k}_q_width"] = str(qh - ql); res[f"{k}_counts"] = J["counts"]
        if name == "FIX_ZERO_LOADING": res["checks"][f"{k}_M_exactly_zero"] = (Ml, Mh) == (Fr(0), Fr(0)); res["checks"][f"{k}_s_query_zero"] = fx(J["s_query"][1]) == 0
    if name == "FIX_ZERO_LOADING":
        res["checks"]["target_equals_residual_all_singletons"] = all(max(qr[i][0], pr[i][0]) <= min(qr[i][1], pr[i][1]) and (qr[i][1] - qr[i][0]) < Fr(1, 2 ** 200) and (pr[i][1] - pr[i][0]) < Fr(1, 2 ** 200) for i in range(M.n))
        res["checks"]["requested_query_is_3"] = M.query == 3
    if name in ("FIX_SIGNED", "FIX_SIGNED_EVIDENCE") and "nfchain" in K:
        # hypotheses: alternating 9 / 11/9 chain → weak cross-ratio 1/10, strong pairs as blocks, row sum <= 1/5, resolvent <= 5/4 (theorem T-NF-01/02 form with the ACTUAL pair diameter D_b)
        J = K["nfchain"]; ql, qh = fx(J["q_query"][0]), fx(J["q_query"][1]); Mi = J["M_actual"]; Ml, Mh = fx(Mi[0]), fx(Mi[1]); Db = block_diameters_pairs(M)[M.query // 2]
        R_new = Fr(5, 4) * (Db * certs.sqrt_upper(Mh) / 4 + Db * Db / 8)
        slo, shi = fx(J["s_query"][0]), fx(J["s_query"][1]); R_old = certs.R_old_range(ql, qh, slo, shi, Ml, Mh)[1]
        for nm, R in (("new_block", R_new), ("old_q1q", R_old)):
            pub = certs.publication((ql + qh) / 2, R); lo, hi = pub["unclipped"]; res[f"{nm}_R"] = str(R); res[f"{nm}_publication_unclipped"] = [str(lo), str(hi)]
            res["checks"][f"{nm}_publication_contains_enumerated_target"] = lo <= pr[M.query][0] and pr[M.query][1] <= hi
        res["block_diameter_query"] = str(Db); res["note"] = "fixture certificate check uses the general block form (5/4)(D_b sqrt(M)/4 + D_b^2/8) with the fixture's actual pair diameter and actual M; the rank-five constants are NOT applied"
    if name == "FIX_UNBALANCED":
        res["note"] = "arithmetic/adversarial fixture: residual q, target p and actual energy checked against enumeration; c=1/200 is NOT claimed to be the exact center; no certificate claim; enumeration dropped the spin-independent energy constant ||s_E||^2/2 (= 0 here, no pins)"
        res["checks"]["target_p_enumerated_finite"] = pr[M.query][0] <= pr[M.query][1]
    res["all_ok"] = all(res["checks"].values()); return res

def _fixture_lock_and_witness(fix_res, M: Model, J_prod, J_chk):
    """small lock/witness/checker records from a fixture run for the rejection suite (frozen constants as MAIN; V replaced by the fixture's own exact V = K tr(AA^T))"""
    K = Fr(99, 46); V = K * sum(sum(M.A[l][i] ** 2 for i in range(M.n) if not M.pin[i]) for l in range(M.r))
    lock = {"input": {"case_id": M.case_id, "n": M.n, "rank": M.r, "query_index": M.query, "requested_event": "X[query_index] == +1", "canonical_sha256": M.sha256(), "pins": [[i, M.pin[i]] for i in range(M.n) if M.pin[i]]},
            "frozen": {"producer_prec": 128, "checker_prec": 192, "residual_sq_max": "1/256", "delta_num": "1/16000", "delta_pub": "1/16000", "width_target": "1/100", "moment_guard": "1/100000000", "moment_width_max": "1/1000000"},
            "constants": {"V": str(V)}}
    g = [(fx(a), fx(b)) for a, b in J_prod["gradient"]]; rsq = certs.residual_sq_upper(g); ql, qh = fx(J_prod["q_query"][0]), fx(J_prod["q_query"][1]); qhat = (ql + qh) / 2
    slo, shi = fx(J_prod["s_query"][0]), fx(J_prod["s_query"][1]); alo, ahi = fx(J_prod["alpha_query"][0]), fx(J_prod["alpha_query"][1]); Mu = V + rsq
    pubs = {}
    for nm, R in (("old", certs.R_old_range(ql, qh, slo, shi, V, Mu)[1]), ("new", certs.R_new_range(alo, ahi, Mu, Mu)[1])):
        p = certs.publication(qhat, R); pubs[nm] = {"unclipped": [str(p["unclipped"][0]), str(p["unclipped"][1])], "unclipped_width": str(p["unclipped_width"])}
    wit = {"case_id": M.case_id, "n": M.n, "rank": M.r, "query_index": M.query, "requested_event": "X[query_index] == +1", "producer_prec": 128, "producer_generator_hash": M.sha256(), "pins": lock["input"]["pins"], "producer_flags_clean": True,
           "center": J_prod["center"], "q_query": J_prod["q_query"], "qhat": str(qhat), "residual_sq_upper": str(rsq), "residual_sq_threshold": "1/256", "M_uniform": str(Mu), "publication": pubs}
    return lock, wit

def round_grid(x: Fr, bits=64) -> Fr:
    """nearest point of 2^-bits Z; FROZEN tie rule: ties round toward +infinity"""
    g = 1 << bits; return Fr((x * g + Fr(1, 2)).numerator // (x * g + Fr(1, 2)).denominator, g)

STEP = Fr(368, 467)

def center_by_enumeration(M: Model, max_updates=6, prec=256):
    """frozen center policy executed with the 256-bit enumerator (fixtures only): c0 = 0; stop when Σ max|g|^2 <= 1/256; at most 6 updates"""
    c = [Fr(0)] * M.r; hist = []
    for k in range(max_updates + 1):
        ref = enumerate_laws(M, c, prec); g = [x.frac() for x in ref["gradient"]]; rsq = certs.residual_sq_upper(g); hist.append({"update": k, "center": [str(x) for x in c], "residual_sq_upper": str(rsq)})
        if rsq <= Fr(1, 256) or k == max_updates: return c, rsq <= Fr(1, 256), hist
        c = [round_grid(c[l] - STEP * (g[l][0] + g[l][1]) / 2) for l in range(M.r)]
    return c, False, hist

def rejection_suite(build_dir, out_dir):
    """six required rejections, each verified for the intended reason, plus a positive control (unmutated → VERIFIED) at a GENUINE center"""
    M = fixture_signed(True); c, ok_c, hist = center_by_enumeration(M); assert ok_c, hist; FIXTURE_CENTERS[M.case_id + "@center"] = c; os.makedirs(out_dir, exist_ok=True); path = os.path.join(out_dir, "input.txt"); M.write(path)
    recs = {}
    for k, prec in (("nfchain", 128), ("nfcheck", 192)):
        o = os.path.join(out_dir, f"{k}.json"); r, _ = run_kernel(os.path.join(build_dir, k), ["--prec", str(prec), "--file", path, "--center", ",".join(str(x) for x in c), "--out", o], out_dir); assert r.returncode == 0, r.stderr; recs[k] = json.load(open(o))
    fix = {}; lock, wit = _fixture_lock_and_witness(fix, M, recs["nfchain"], recs["nfcheck"]); chk = recs["nfcheck"]; gh = M.sha256()
    results = {"positive_control": verify_stage_b(lock, wit, chk, gh), "center_used": [str(x) for x in c], "center_history": hist}
    cases = {}
    L2 = copy.deepcopy(lock); L2["input"]["canonical_sha256"] = hashlib.sha256(b"tampered").hexdigest(); cases["changed_generator_hash"] = (L2, wit, chk, gh, ["generator_hash_matches_lock", "producer_dump_hash_matches_lock"])
    W2 = copy.deepcopy(wit); W2["query_index"] = 4; cases["wrong_query_binding"] = (lock, W2, chk, gh, ["query_index_bound"])
    W3 = copy.deepcopy(wit); W3["requested_event"] = "X[query_index] == -1"; cases["wrong_event_binding"] = (lock, W3, chk, gh, ["event_bound"])
    L4 = copy.deepcopy(lock); L4["frozen"]["residual_sq_max"] = "1/4"; W4 = copy.deepcopy(wit); W4["residual_sq_threshold"] = "1/4"; cases["altered_residual_threshold"] = (L4, W4, chk, gh, ["residual_threshold_frozen"])
    W5 = copy.deepcopy(wit); W5["M_uniform"] = str(Fr(lock["constants"]["V"]) / 2); cases["falsely_narrowed_M_bound"] = (lock, W5, chk, gh, ["producer_M_uniform_not_narrower_than_V+r_prod^2", "producer_M_uniform_ge_V"])
    C6 = copy.deepcopy(chk); C6["q_query"] = ["nan", "1*2^-1"]; cases["malformed_interval_nan"] = (lock, wit, C6, gh, ["record_well_formed"])
    C6b = copy.deepcopy(chk); C6b["gradient"][0] = [C6b["gradient"][0][1], C6b["gradient"][0][0]]; cases["malformed_interval_reversed_endpoints"] = (lock, wit, C6b, gh, ["record_well_formed"])
    W7 = copy.deepcopy(wit); W7["pins"] = [[0, 1], [11, 1]]; cases["omitted_evidence_pin"] = (lock, W7, chk, gh, ["evidence_pins_bound"])
    W8 = copy.deepcopy(wit); W8["pins"] = [[0, 1], [7, 1], [11, 1]]; cases["changed_evidence_pin"] = (lock, W8, chk, gh, ["evidence_pins_bound"])
    W9 = copy.deepcopy(wit); W9["center"] = [str(Fr(300)), "0", "0"]; cases["center_outside_domain"] = (lock, W9, chk, gh, ["center_norm_le_257", "center_identical_in_checker_run"])
    for name, (l, w, ck, g, expected) in cases.items():
        v = verify_stage_b(l, w, ck, g); results[name] = {"verdict": v["verdict"], "failed_checks": v["failed_checks"], "expected_reason_present": any(e in v["failed_checks"] for e in expected), "expected": expected}
    # Stage C checker: positive control + width miss + containment failure
    Mp = recs["nfchain"]; Mc = recs["nfcheck"]
    # re-run with --moments for the records
    for k, prec in (("nfchain", 128), ("nfcheck", 192)):
        o = os.path.join(out_dir, f"{k}_m.json"); r, _ = run_kernel(os.path.join(build_dir, k), ["--prec", str(prec), "--file", path, "--center", ",".join(str(x) for x in c), "--out", o, "--moments"], out_dir); assert r.returncode == 0; recs[k + "_m"] = json.load(open(o))
    pm = {"raw": recs["nfchain_m"]["M_actual"]}; cm = recs["nfcheck_m"]["M_actual"]
    results["stage_c_positive_control"] = verify_stage_c(lock, pm, cm)["verdict"]
    wide = {"raw": [pm["raw"][0], "1*2^0"]}; results["stage_c_width_miss_is_precision_inconclusive"] = verify_stage_c(lock, wide, cm)["verdict"]
    shifted = {"M": [str(fx(cm["M"][0]) + Fr(1, 1000)).replace("/", "x") if False else cm["M"][0], cm["M"][1]]}
    shifted = {"M": [f"{int((fx(cm['M'][0]) + Fr(1, 1000)) * 2**200)}*2^-200", f"{int((fx(cm['M'][1]) + Fr(1, 1000)) * 2**200) + 1}*2^-200"]}
    results["stage_c_containment_failure_is_checking_failure"] = verify_stage_c(lock, pm, shifted)["verdict"]
    results["all_ok"] = (results["positive_control"]["verdict"] == "VERIFIED" and all(results[n]["verdict"] == "REJECTED" and results[n]["expected_reason_present"] and results[n]["failed_checks"] == [e for e in results[n]["failed_checks"] if e in results[n]["expected"]] for n in cases)
                         and results["stage_c_positive_control"] == "VERIFIED" and results["stage_c_width_miss_is_precision_inconclusive"] == "PRECISION_INCONCLUSIVE" and results["stage_c_containment_failure_is_checking_failure"] == "CHECKING_FAILURE")
    results["positive_control"] = {"verdict": results["positive_control"]["verdict"], "failed_checks": results["positive_control"]["failed_checks"]}
    return results
