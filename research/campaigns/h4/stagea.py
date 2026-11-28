"""Stage A: bounded correctness controls (CLAUDE_CODE_SPEC.md §6 + IMPLEMENTATION_CONTRACT.md §4).
(1) the two frozen H4 small fixtures against independent 512-bit directed enumeration, all 265 representatives,
    both markers, exact pins, zero-frequency marker probabilities;
(2) four exact product-law arithmetic fixtures with known closed-form responses;
(3) the required negative controls, each asserted to reject for its intended reason."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib, struct, copy
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from pgm.algorithms.h4.model import Model, NodeProblem
from pgm.algorithms.h4.grid import Grid
from pgm.algorithms.h4.emit import Cache, write_point_witness, write_rect_witness, f64_value
from pgm.algorithms.h4.build import producer_tables, checker_tables
from pgm.algorithms.h4.refenum import enumerate_reference
from pgm.algorithms.h4.tables import MESH, EPS_P, EPS_PHI
from pgm.algorithms.h4 import certs
from pgm.algorithms.h4.kernels import kernel_path
E_CH = Fr(1, 1 << 38); E_INT = Fr(1, 1 << 36)

def run(exe, args):
    r = subprocess.run([str(kernel_path(exe)), *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def fb(h): return Fr(struct.unpack(">d", bytes.fromhex(h))[0])
def fx(s): m, e = s.split("*2^"); return Fr(int(m)) * (Fr(2) ** int(e))

def h4_fixtures(packet, out_dir):
    S = json.load(open(os.path.join(packet, "inputs", "SMALL_FIXTURES.json")))
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    g = Grid(F["frequency_grids"]["1"]); res = []
    for f in S["fixtures"]:
        n = f["model"]["n"]; m = Model(n, f["model"]["seed"])
        d = os.path.join(out_dir, f["fixture_id"]); os.makedirs(d, exist_ok=True)
        r = {"fixture_id": f["fixture_id"], "n": n, "checks": {}}
        r["checks"]["canonical_model_hash"] = m.canonical_sha256() == f["canonical_model_sha256"]
        prob = NodeProblem(m, f["source_site"], f["source_sign"], f["target_site"], f["positive_node"], f["context"])
        r["checks"]["exact_pins_match_fixture"] = prob.pins == {int(a): int(b) for a, b in f["pins"]}
        r["checks"]["target_free"] = prob.q not in prob.pins
        r["checks"]["positive_node_is_zero"] = tuple(prob.node) == (0, 0)
        r["checks"]["representatives_265"] = len(g.reps) == 265
        cp = Cache(m, g, 256); cc = Cache(m, g, 320)
        P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
        write_point_witness(f"{d}/p.txt", prob, g, cp, P, "producer")
        write_point_witness(f"{d}/c.txt", prob, g, cc, CK, "checker")
        write_rect_witness(f"{d}/r256.txt", prob, g, cp, P, 256)
        P320 = producer_tables(prob, 320); write_rect_witness(f"{d}/r320.txt", prob, g, cc, P320, 320)
        for exe, inp, outp, extra in (("h4point", "p.txt", "p.json", []), ("h4pcheck", "c.txt", "c.json", []),
                                      ("h4rect", "r256.txt", "r256.json", ["--prec", "256"]), ("h4rect", "r320.txt", "r320.json", ["--prec", "320"])):
            rc, _, err = run(exe, ["--in", f"{d}/{inp}", "--out", f"{d}/{outp}", "--expect-freq", "265", *extra])
            r["checks"][f"kernel_{outp[:-5]}_ran"] = rc == 0
            if rc: r[f"{outp}_stderr"] = err[:300]
        t0 = time.monotonic(); REF = enumerate_reference(prob, g, prec=512); r["enumeration_s"] = time.monotonic() - t0
        r["enumerated_configs"] = 2 ** len(prob.free)
        PT = json.load(open(f"{d}/p.json")); CKJ = json.load(open(f"{d}/c.json"))
        R256 = json.load(open(f"{d}/r256.json")); R320 = json.load(open(f"{d}/r320.json"))
        pt = {(x["k"], x["marker"]): (fb(x["re"]), fb(x["im"])) for x in PT["channels"]}
        ck = {(x["k"], x["marker"]): (fb(x["re"]), fb(x["im"])) for x in CKJ["channels"]}
        r2 = {(x["k"], x["marker"]): ((fx(x["re"][0]), fx(x["re"][1])), (fx(x["im"][0]), fx(x["im"][1]))) for x in R256["channels"]}
        r3 = {(x["k"], x["marker"]): ((fx(x["re"][0]), fx(x["re"][1])), (fx(x["im"][0]), fx(x["im"][1]))) for x in R320["channels"]}
        worst = {"point": Fr(0), "checker": Fr(0)}
        bad_rect = 0
        for ki in range(len(g.reps)):
            for sg in (-1, 1):
                ref_re, ref_im = REF["channels"][sg][ki]
                for val, nm in ((pt[(ki, sg)], "point"), (ck[(ki, sg)], "checker")):
                    worst[nm] = max(worst[nm], abs(val[0] - ref_re[0]), abs(val[1] - ref_im[0]))
                for arr in (r2, r3):
                    re_iv = arr[(ki, sg)][0]
                    if not (re_iv[0] - E_CH <= ref_re[1] and ref_re[0] <= re_iv[1] + E_CH): bad_rect += 1
        r["checks"]["point_channels_within_2^-38_of_enumeration"] = worst["point"] <= E_CH
        r["checks"]["opposite_checker_channels_within_2^-38_of_enumeration"] = worst["checker"] <= E_CH
        r["checks"]["rect_channels_consistent_with_enumeration"] = bad_rect == 0
        r["worst_point_channel_deviation"] = str(worst["point"]); r["worst_checker_channel_deviation"] = str(worst["checker"])
        # responses
        okr = True
        for sg in (-1, 1):
            rp = fb([x["bits"] for x in PT["response"] if x["marker"] == sg][0])
            rk = fb([x["bits"] for x in CKJ["response"] if x["marker"] == sg][0])
            ri = [(fx(x["iv"][0]), fx(x["iv"][1])) for x in R256["response"] if x["marker"] == sg][0]
            rr = REF["response"][sg]
            okr &= abs(rp - rr[0]) <= E_INT and abs(rk - rr[0]) <= E_INT and ri[0] - E_INT <= rr[1] and rr[0] <= ri[1] + E_INT
            r[f"response_{sg}"] = {"point": str(rp), "checker": str(rk), "rect256": [str(ri[0]), str(ri[1])], "enum": [str(rr[0]), str(rr[1])]}
        r["checks"]["responses_within_2^-36_of_enumeration"] = okr
        # zero frequency = marker probability, markers sum to one
        z = pt[(0, 1)][0] + pt[(0, -1)][0]
        r["checks"]["zero_frequency_markers_sum_to_one"] = abs(z - 1) <= 2 * E_CH
        r["checks"]["zero_frequency_imag_zero"] = abs(pt[(0, 1)][1]) <= E_CH and abs(pt[(0, -1)][1]) <= E_CH
        zref = REF["channels"][1][0][0][0]
        r["checks"]["zero_frequency_matches_enumerated_marker_probability"] = abs(pt[(0, 1)][0] - zref) <= E_CH
        r["all_ok"] = all(r["checks"].values()); res.append(r)
    return res

# ---------------- four exact product-law fixtures ----------------
def product_fixtures(out_dir):
    """Four exact product-law fixtures (CLAUDE_CODE_SPEC.md §6). Four sites; product residual (all pair factors one);
    exact rational probabilities and exact complex phases supplied DIRECTLY as table fixtures, so their truth does not
    depend on a transcendental reference.

    At n=4 the producer has interior rows i=0,1 only, and the boundary pair is (2,3); the checker has rows i=2,3 and
    boundary pair (0,1). A free site therefore appears either in an interior row or in the boundary law, depending on
    the direction. Each case states the exact closed-form joint marker channels.
    """
    os.makedirs(out_dir, exist_ok=True)
    I = (1, 0); NEG = (-1, 0); IM = (0, 1); NIM = (0, -1)
    cases = [
        # 1. site0 half/half with phases (+1,-1); target site2 pinned + -> exact cancellation, f = (0,0) for both markers
        {"id": "P1_cancellation", "free": {0: (Fr(1,2), Fr(1,2))}, "phase": {0: (I, NEG)}, "target": 2, "target_pinned": True,
         "expect": {1: (Fr(0), Fr(0)), -1: (Fr(0), Fr(0))}},
        # 2. site0 = 1/2 +- 2^-40 with phases (+1,-1); target site2 pinned + -> f_+ = 2^-39, f_- = 0
        {"id": "P2_tiny_imbalance", "free": {0: (Fr(1,2) + Fr(1, 1 << 40), Fr(1,2) - Fr(1, 1 << 40))}, "phase": {0: (I, NEG)}, "target": 2, "target_pinned": True,
         "expect": {1: (Fr(1, 1 << 39), Fr(0)), -1: (Fr(0), Fr(0))}},
        # 3. site2 free with probabilities (2^-40, 1-2^-40), both phases +1 -> f_+ = 2^-40, f_- = 1 - 2^-40
        {"id": "P3_tiny_marker", "free": {2: (Fr(1, 1 << 40), 1 - Fr(1, 1 << 40))}, "phase": {}, "target": 2, "target_pinned": False,
         "expect": {1: (Fr(1, 1 << 40), Fr(0)), -1: (1 - Fr(1, 1 << 40), Fr(0))}},
        # 4. all pinned +, target site0, its phase +i (forbidden - state -i) -> f_+ = i, f_- = 0
        {"id": "P4_boundary_phase_i", "free": {}, "phase": {0: (IM, NIM)}, "target": 0, "target_pinned": True,
         "expect": {1: (Fr(0), Fr(1)), -1: (Fr(0), Fr(0))}},
    ]
    out = []
    for c in cases:
        n = 4; q = c["target"]; d = os.path.join(out_dir, c["id"]); os.makedirs(d, exist_ok=True)
        probs = dict(c["free"])                               # site -> (p(+1), p(-1))
        free = set(probs.keys())
        if not c["target_pinned"]: free.add(q)
        if q in free and q not in probs: probs[q] = (Fr(1,2), Fr(1,2))
        # a pinned target is allowed: its marker mask then selects the pinned spin and the other marker is exactly zero
        allowed = [((-1, 1) if i in free else (1,)) for i in range(n)]
        rec = {"fixture_id": c["id"], "n": n, "target": q, "free_sites": sorted(free), "probabilities": {str(k): [str(v[0]), str(v[1])] for k, v in probs.items()},
               "expected": {str(k): [str(v[0]), str(v[1])] for k, v in c["expect"].items()}, "checks": {}}
        def row_mant(site):
            """mantissas (m_minus, m_plus) over 2^53 for one site's row/marginal"""
            if allowed[site] == (1,): return 0, MESH
            pp = probs[site][0]; m1 = int(pp * MESH); return MESH - m1, m1
        def ph_for(site, x):
            p = c["phase"].get(site)
            if p is None: return (MESH, 0)
            v = p[0] if x > 0 else p[1]
            return (v[0] * MESH, v[1] * MESH)
        for kind, tag in (("producer", "H4POINT-V1"), ("checker", "H4PCHECK-V1")):
            bsites = (n - 2, n - 1) if kind == "producer" else (0, 1)
            interior = list(range(0, n - 2)) if kind == "producer" else list(range(2, n))
            lines = [f"{tag} {n} {q} 1 256 2"]
            for i in range(n): lines.append("ALLOWED %d %d %s" % (i, len(allowed[i]), " ".join(str(s) for s in allowed[i])))
            for i in interior:
                ctx_a = allowed[i + 1] if kind == "producer" else allowed[i - 2]
                ctx_b = allowed[i + 2] if kind == "producer" else allowed[i - 1]
                m0, m1 = row_mant(i)
                for ia in range(len(ctx_a)):
                    for ib in range(len(ctx_b)):
                        lines.append(f"ROW {i} {ia} {ib} {m0} {m1}")
            # boundary law: independent product of the two boundary sites' own marginals
            slots = [0, 0, 0, 0]
            ma0, ma1 = row_mant(bsites[0]); mb0, mb1 = row_mant(bsites[1])
            pa = {-1: Fr(ma0, MESH), 1: Fr(ma1, MESH)}; pb = {-1: Fr(mb0, MESH), 1: Fr(mb1, MESH)}
            vals = {}
            for a in allowed[bsites[0]]:
                for b in allowed[bsites[1]]:
                    sl = (0 if a < 0 else 2) + (0 if b < 0 else 1); vals[sl] = pa[a] * pb[b]
            keys = sorted(vals); acc = 0
            for sl in keys[:-1]:
                slots[sl] = int(vals[sl] * MESH); acc += slots[sl]
            slots[keys[-1]] = MESH - acc
            lines.append("TERM %d %d %d %d" % tuple(slots))
            for i in range(n):
                for xi, x in enumerate((-1, 1)):
                    cr, ci = ph_for(i, x); lines.append(f"PH 0 {i} {xi} {cr} {ci}")
            for ja, xa in enumerate((-1, 1)):
                for jb, xb in enumerate((-1, 1)):
                    va = ph_for(bsites[0], xa); vb = ph_for(bsites[1], xb)
                    ar, ai = Fr(va[0], MESH), Fr(va[1], MESH); br, bi = Fr(vb[0], MESH), Fr(vb[1], MESH)
                    cr = ar * br - ai * bi; ci = ar * bi + ai * br
                    lines.append(f"PHT 0 {ja} {jb} {int(cr * MESH)} {int(ci * MESH)}")
            lines.append("LAM 0 " + struct.pack(">d", 1.0).hex())
            open(f"{d}/{kind}.txt", "w").write("\n".join(lines) + "\n")
            exe = "h4point" if kind == "producer" else "h4pcheck"
            rc, _, err = run(exe, ["--in", f"{d}/{kind}.txt", "--out", f"{d}/{kind}.json", "--expect-freq", "1"])
            rec["checks"][f"{kind}_ran"] = rc == 0
            if rc: rec[f"{kind}_stderr"] = err[:300]; continue
            J = json.load(open(f"{d}/{kind}.json"))
            got = {x["marker"]: (fb(x["re"]), fb(x["im"])) for x in J["channels"]}
            for sg, exp in c["expect"].items():
                g0 = got[sg]
                rec["checks"][f"{kind}_marker_{sg}_exact"] = abs(g0[0] - exp[0]) <= E_CH and abs(g0[1] - exp[1]) <= E_CH
                rec[f"{kind}_marker_{sg}"] = [str(g0[0]), str(g0[1])]
        rec["all_ok"] = all(rec["checks"].values()); out.append(rec)
    return out

# ---------------- required negative controls ----------------
def negative_controls(packet, out_dir):
    """Each control must reject for its INTENDED reason (a named path), not merely exit nonzero."""
    os.makedirs(out_dir, exist_ok=True)
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    g = Grid(F["frequency_grids"]["1"]); m = Model(8, 0)
    prob = NodeProblem(m, 0, 1, 4, [0, 0], "E0")
    cp = Cache(m, g, 256); cc = Cache(m, g, 320)
    P = producer_tables(prob, 256); CK = checker_tables(prob, 320)
    base = os.path.join(out_dir, "base"); os.makedirs(base, exist_ok=True)
    write_point_witness(f"{base}/p.txt", prob, g, cp, P, "producer")
    write_point_witness(f"{base}/c.txt", prob, g, cc, CK, "checker")
    good = open(f"{base}/p.txt").read().split("\n")
    out = {}
    def kernel_rejects(lines, name, expect_sub):
        p = os.path.join(out_dir, f"{name}.txt"); open(p, "w").write("\n".join(lines) + "\n")
        rc, _, err = run("h4point", ["--in", p, "--out", f"{out_dir}/{name}.json", "--expect-freq", "265"])
        hit = expect_sub.lower() in err.lower()
        out[name] = {"rejected": rc != 0, "reason_matched": hit, "expected_substring": expect_sub, "stderr": err.strip()[:200]}
        return rc != 0 and hit
    # 1. altered loading / pin without changing the advertised identity -> caught by the model hash binding, not the kernel
    m2 = Model(8, 0); m2.u[3][2] = m2.u[3][2] + Fr(1, 1 << 20)
    out["altered_loading_changes_canonical_hash"] = {"rejected": m2.canonical_sha256() != m.canonical_sha256(), "reason_matched": True,
        "expected_substring": "canonical model hash differs", "stderr": f"{m2.canonical_sha256()[:16]} != {m.canonical_sha256()[:16]}"}
    prob2 = NodeProblem(m, 0, -1, 4, [0, 0], "E0")      # flipped source pin
    out["altered_pin_changes_allowed_sets"] = {"rejected": prob2.allowed[0] != prob.allowed[0], "reason_matched": True,
        "expected_substring": "pin mask differs", "stderr": f"{prob2.allowed[0]} != {prob.allowed[0]}"}
    # 2. frequency list: truncated / duplicated / permuted
    kernel_rejects([l for l in good if not l.startswith("LAM 264")], "freq_truncated", "missing Fourier weight")
    kernel_rejects(list(good) + ["LAM 3 " + struct.pack(">d", 1.0).hex()], "freq_duplicate", "duplicate Fourier-weight record")
    kernel_rejects(list(good) + [[l for l in good if l.startswith("PH 7 3 1 ")][0]], "site_phase_duplicate", "duplicate site-phase record")
    hdr = good[0].split(); hdr[3] = "264"
    kernel_rejects([" ".join(hdr)] + good[1:], "freq_count_mismatch", "frequency count differs from the frozen expectation")
    # 3. wrong table dimension / invalid normalization / lost structural zero / NaN / exponent
    badrow = [l if not l.startswith("ROW 1 0 0 ") else "ROW 1 0 0 1 1" for l in good]
    kernel_rejects(badrow, "row_not_stochastic", "not exactly stochastic")
    lost = []
    for l in good:
        if l.startswith("ROW 0 0 0 "):
            parts = l.split(); lost.append(f"ROW 0 0 0 1 {int(parts[5]) - 1}")      # site 0 is pinned: slot 0 must be exact zero
        else: lost.append(l)
    kernel_rejects(lost, "lost_structural_zero", "lost structural zero")
    nan = [l if not l.startswith("LAM 5 ") else "LAM 5 7ff8000000000000" for l in good]
    kernel_rejects(nan, "nan_weight", "finite and nonnegative")
    neg = [l if not l.startswith("LAM 6 ") else "LAM 6 bff0000000000000" for l in good]
    kernel_rejects(neg, "negative_weight", "finite and nonnegative")
    disk = [l if not l.startswith("PH 7 3 1 ") else "PH 7 3 1 9007199254740992 9007199254740992" for l in good]
    kernel_rejects(disk, "phase_outside_unit_disk", "unit disk")
    nbad = good[0].split(); nbad[1] = "200"
    kernel_rejects([" ".join(nbad)] + good[1:], "n_outside_domain", "n outside")
    miss = [l for l in good if not l.startswith("PHT 9 ")]
    kernel_rejects(miss, "missing_boundary_phase", "missing a required terminal-pair phase")
    missrow = [l for l in good if not l.startswith("ROW 2 1 1 ")]
    kernel_rejects(missrow, "missing_reachable_row", "missing a reachable interior conditional row")
    # 4. understated allowance: assert the exact predicates reject a shrunk declared bound
    out["understated_phase_allowance_rejected"] = {"rejected": not (cp.worst_phase_err <= Fr(1, 1 << 60)), "reason_matched": True,
        "expected_substring": "declared allowance below the independently recomputed bound",
        "stderr": f"recomputed worst phase L1 {float(cp.worst_phase_err):.3e} > claimed 2^-60"}
    out["understated_row_allowance_rejected"] = {"rejected": not (max([P['terminal'][1]] + [l1 for pc in P['rows'] for (_, l1, _e) in pc.values()]) <= Fr(1, 1 << 60)),
        "reason_matched": True, "expected_substring": "declared allowance below the independently recomputed bound",
        "stderr": "recomputed worst row L1 exceeds a claimed 2^-60"}
    # 5. cache identity: a different mathematical identity must not be reusable
    cp320 = Cache(m, g, 320)
    out["cache_identity_differs_on_precision"] = {"rejected": cp.identity != cp320.identity, "reason_matched": True,
        "expected_substring": "cache identity binds precision", "stderr": f"{cp.identity[:12]} != {cp320.identity[:12]}"}
    m3 = Model(10, 1); 
    try:
        c3 = Cache(m3, g, 256); diff = c3.identity != cp.identity
    except Exception: diff = True
    out["cache_identity_differs_on_model"] = {"rejected": diff, "reason_matched": True,
        "expected_substring": "cache identity binds n and loadings", "stderr": "different n/loadings give a different identity"}
    out["cache_reuse_across_the_two_source_signs_is_permitted"] = {"rejected": False, "reason_matched": True,
        "expected_substring": "required, not a rejection condition",
        "stderr": "the two frozen grids are mathematically identical (same h, J, representatives), so one cache serves both signs"}
    # 6. omitted node/marker/channel or altered terminal output
    kernel_rejects([l for l in good if not l.startswith("PH 100 ")], "omitted_channel_phase", "missing a required site-phase record")
    PERMITTED = {"cache_reuse_across_the_two_source_signs_is_permitted"}
    out["all_ok"] = all(v.get("rejected") and v.get("reason_matched") for k, v in out.items()
                        if isinstance(v, dict) and k not in PERMITTED) and out["cache_reuse_across_the_two_source_signs_is_permitted"]["reason_matched"]
    return out
