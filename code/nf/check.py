"""Independent checker side (Python aggregation of the nfcheck kernel record + binding checks). Rejects: changed generator hash, wrong
query/event binding, altered residual threshold, falsely narrowed M bound, malformed interval/NaN, omitted/changed evidence pin,
center outside the domain, missing/inconsistent frozen constants. Every check is listed by name in the verdict."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from .ivpy import fx
from . import certs

RESIDUAL_SQ_FROZEN = Fr(1, 256)           # (1/16)^2
CENTER_NORM_SQ_MAX = Fr(257) ** 2
GRID = 1 << 64

def parse_iv(pair):
    if not (isinstance(pair, (list, tuple)) and len(pair) == 2): raise ValueError("interval must be a 2-list")
    lo, hi = fx(pair[0]), fx(pair[1])
    if not lo <= hi: raise ValueError("interval endpoints out of order")
    return lo, hi

def verify_stage_b(lock: dict, witness: dict, checker_kernel: dict, generator_hash_checker: str, pins_expected: list | None = None):
    """witness: producer-side published witness; checker_kernel: nfcheck JSON at the SAME stored center (fresh evaluation)."""
    L = lock["frozen"]; checks = {}; detail = {}
    def chk(name, ok, **d):
        checks[name] = bool(ok); detail.update({f"{name}.{k}": v for k, v in d.items()})
    try:
        # --- bindings
        chk("generator_hash_matches_lock", generator_hash_checker == lock["input"]["canonical_sha256"], lock=lock["input"]["canonical_sha256"], checker=generator_hash_checker)
        chk("producer_dump_hash_matches_lock", witness.get("producer_generator_hash") == lock["input"]["canonical_sha256"])
        chk("case_id_bound", witness.get("case_id") == lock["input"]["case_id"] == checker_kernel.get("case_id"))
        chk("query_index_bound", witness.get("query_index") == lock["input"]["query_index"] == checker_kernel.get("query_index"), lock=lock["input"]["query_index"], witness=witness.get("query_index"), checker=checker_kernel.get("query_index"))
        chk("event_bound", witness.get("requested_event") == lock["input"]["requested_event"] == "X[query_index] == +1")
        chk("n_rank_bound", (witness.get("n"), witness.get("rank")) == (lock["input"]["n"], lock["input"]["rank"]) == (checker_kernel.get("n"), checker_kernel.get("rank")))
        chk("precision_bound", witness.get("producer_prec") == L["producer_prec"] and checker_kernel.get("prec") == L["checker_prec"], producer=witness.get("producer_prec"), checker=checker_kernel.get("prec"))
        chk("residual_threshold_frozen", Fr(L["residual_sq_max"]) == RESIDUAL_SQ_FROZEN and Fr(witness.get("residual_sq_threshold", "0")) == RESIDUAL_SQ_FROZEN, lock=L["residual_sq_max"], witness=witness.get("residual_sq_threshold"))
        chk("pads_frozen", Fr(L["delta_num"]) == certs.DELTA_NUM and Fr(L["delta_pub"]) == certs.DELTA_PUB and Fr(L["width_target"]) == certs.WIDTH_TARGET)
        pins_w = witness.get("pins", []); pins_l = lock["input"].get("pins", [])
        chk("evidence_pins_bound", pins_w == pins_l == (pins_expected if pins_expected is not None else pins_l), witness=pins_w, lock=pins_l)
        chk("kernel_flags_clean", checker_kernel.get("flags_clean") is True and witness.get("producer_flags_clean") is True)
        # --- center (exact grid, domain, same in both)
        c = [Fr(x) for x in witness["center"]]; cc = [Fr(x) for x in checker_kernel["center"]]
        chk("center_identical_in_checker_run", c == cc)
        chk("center_on_2^-64_grid", all((x * GRID).denominator == 1 for x in c))
        chk("center_norm_le_257", sum(x * x for x in c) <= CENTER_NORM_SQ_MAX, norm_sq=str(sum(x * x for x in c)))
        # --- checker's own residual and query
        g = [parse_iv(p) for p in checker_kernel["gradient"]]; rsq = certs.residual_sq_upper(g)
        chk("checker_residual_sq_le_1/256", rsq <= RESIDUAL_SQ_FROZEN, residual_sq_upper=str(rsq))
        qlo, qhi = parse_iv(checker_kernel["q_query"]); chk("checker_q_width_le_1/8000", qhi - qlo <= certs.Q_WIDTH_MAX, width=str(qhi - qlo))
        chk("checker_q_in_[0,1]", 0 <= qlo <= qhi <= 1)
        pqlo, pqhi = parse_iv(witness["q_query"]); chk("producer_q_width_le_1/8000", pqhi - pqlo <= certs.Q_WIDTH_MAX, width=str(pqhi - pqlo))
        chk("producer_checker_q_overlap", max(qlo, pqlo) <= min(qhi, pqhi))
        qhat = Fr(witness["qhat"]); chk("qhat_is_exact_producer_midpoint", qhat == (pqlo + pqhi) / 2)
        # --- s and alpha
        slo, shi = parse_iv(checker_kernel["s_query"]); alo, ahi = parse_iv(checker_kernel["alpha_query"])
        chk("s_alpha_nonnegative_finite", slo >= 0 and alo >= 0)
        # --- M_uniform = V + r^2 reconstructed from frozen V (verified from the regenerated geometry by the caller) and the CHECKER's residual
        V = Fr(lock["constants"]["V"]); M_unif_chk = V + rsq
        M_unif_prod = Fr(witness["M_uniform"]); chk("producer_M_uniform_not_narrower_than_V+r_prod^2", M_unif_prod >= V + Fr(witness["residual_sq_upper"]), producer=str(M_unif_prod))
        chk("producer_M_uniform_ge_V", M_unif_prod >= V)
        # --- recompute both response bounds with CHECKER quantities (its own residual, q, s, alpha) and require containment of the mathematical enclosure
        R_old_chk = certs.R_old_range(qlo, qhi, slo, shi, M_unif_chk, M_unif_chk)[1]
        R_new_chk = certs.R_new_range(alo, ahi, M_unif_chk, M_unif_chk)[1]
        out = {}
        for name, Rc in (("old", R_old_chk), ("new", R_new_chk)):
            pub = witness["publication"][name]; ulo, uhi = Fr(pub["unclipped"][0]), Fr(pub["unclipped"][1])
            enc_lo, enc_hi = qlo - Rc, qhi + Rc
            chk(f"{name}_checker_enclosure_contained_in_unclipped_publication", ulo <= enc_lo and enc_hi <= uhi, checker_enclosure=(str(enc_lo), str(enc_hi)), publication=(str(ulo), str(uhi)))
            chk(f"{name}_publication_width_consistent", uhi - ulo == Fr(pub["unclipped_width"]))
            out[name] = {"R_checker_upper": str(Rc), "checker_enclosure": (str(enc_lo), str(enc_hi))}
        detail["checker_recomputed"] = {"M_uniform": str(M_unif_chk), "residual_sq_upper": str(rsq), "q": (str(qlo), str(qhi)), "s": (str(slo), str(shi)), "alpha": (str(alo), str(ahi)), **out}
    except Exception as e:   # malformed interval / NaN / missing field → explicit rejection, not a crash
        checks["record_well_formed"] = False; detail["record_error"] = f"{type(e).__name__}: {e}"
    verdict = "VERIFIED" if checks and all(checks.values()) else "REJECTED"
    return {"verdict": verdict, "failed_checks": [k for k, v in checks.items() if not v], "checks": checks, "detail": detail}

def verify_stage_c(lock, producer_M: dict, checker_M: dict):
    """producer_M: {"raw": [lo,hi] strings-dyadic}; checker_M: {"M": [lo,hi]} from nfcheck. Width gate 1e-6 each; guard 1e-8; containment."""
    L = lock["frozen"]; checks = {}; detail = {}
    try:
        plo, phi = parse_iv(producer_M["raw"]); clo, chi = parse_iv(checker_M["M"])
        guard = Fr(L["moment_guard"]); wmax = Fr(L["moment_width_max"])
        checks["producer_M_finite_ordered"] = plo <= phi; checks["checker_M_finite_ordered"] = clo <= chi
        checks["producer_M_width_le_1e-6"] = (phi - plo) <= wmax; checks["checker_M_width_le_1e-6"] = (chi - clo) <= wmax
        glo, ghi = max(Fr(0), plo - guard), phi + guard
        checks["checker_M_contained_in_guarded_producer_M"] = glo <= clo and chi <= ghi
        checks["intervals_compatible_nonempty_intersection"] = max(plo, clo) <= min(phi, chi)
        detail = {"producer_raw": (str(plo), str(phi)), "producer_guarded": (str(glo), str(ghi)), "checker_raw": (str(clo), str(chi)), "producer_width": str(phi - plo), "checker_width": str(chi - clo)}
    except Exception as e:
        checks["record_well_formed"] = False; detail["record_error"] = f"{type(e).__name__}: {e}"
    precision_miss = checks.get("producer_M_finite_ordered", False) and checks.get("checker_M_finite_ordered", False) and not (checks.get("producer_M_width_le_1e-6") and checks.get("checker_M_width_le_1e-6"))
    verdict = "VERIFIED" if all(checks.values()) else ("PRECISION_INCONCLUSIVE" if precision_miss and checks.get("checker_M_contained_in_guarded_producer_M", True) else "CHECKING_FAILURE")
    return {"verdict": verdict, "failed_checks": [k for k, v in checks.items() if not v], "checks": checks, "detail": detail}
