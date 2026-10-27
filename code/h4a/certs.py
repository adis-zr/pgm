"""Publication and independent-containment predicates (NUMERICAL_THEOREM.md §8, IMPLEMENTATION_CONTRACT.md §4).

C  : producer raw 256-bit interval, radius <= 2^-36 about its exact midpoint -> publish mid +- 2^-30;
     checker raw 320-bit interval must have width <= 2^-35 and be CONTAINED in that publication.
PI : point producer publishes point +- 2^-30; the same 320-bit interval checker's raw interval must be contained.
PP : point producer publishes point +- 2^-30; the opposite-direction point checker's INNER interval
     (channel radius 2^-38, response radius 2^-36) must be contained. Overlap is insufficient."""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import json, struct
from fractions import Fraction as Fr

E_CH = Fr(1, 1 << 38); E_INT = Fr(1, 1 << 36); E_PUB = Fr(1, 1 << 30)
W_GATE_PROD = Fr(1, 1 << 36)      # C's raw radius gate
W_GATE_REF = Fr(1, 1 << 35)       # interval checker's raw width gate

def fb(h: str) -> Fr: return Fr(struct.unpack(">d", bytes.fromhex(h))[0])
def fx(s: str) -> Fr:
    m, e = s.split("*2^"); return Fr(int(m)) * (Fr(2) ** int(e))

def verify_node(arm, prod_path, chk_path, cprod, cchk, grid, prob):
    P = json.load(open(prod_path)); C = json.load(open(chk_path))
    checks = {}; detail = {}
    nrep = len(grid.reps)
    def ck(name, ok, **kw):
        checks[name] = bool(ok); detail.update({f"{name}.{k}": v for k, v in kw.items()})
    try:
        ck("frequency_count_exact", P["nfreq"] == nrep and C["nfreq"] == nrep, got=(P["nfreq"], C["nfreq"]), want=nrep)
        ck("n_and_query_bound", P["n"] == C["n"] == prob.m.n and P["q"] == C["q"] == prob.q)
        # --- collect producer publications and checker inner intervals
        if arm == "C":
            pch = {(d["k"], d["marker"]): ((fx(d["re"][0]), fx(d["re"][1])), (fx(d["im"][0]), fx(d["im"][1]))) for d in P["channels"]}
            pres = {d["marker"]: (fx(d["iv"][0]), fx(d["iv"][1])) for d in P["response"]}
            # raw radius gate, then publication = exact midpoint +- 2^-30
            worst_r = Fr(0)
            pub_ch = {}; 
            for k, (re, im) in pch.items():
                for comp, iv in (("re", re), ("im", im)):
                    r = (iv[1] - iv[0]) / 2; worst_r = max(worst_r, r)
                    mid = (iv[0] + iv[1]) / 2; pub_ch[(k, comp)] = (mid - E_PUB, mid + E_PUB)
            pub_res = {}
            worst_rr = Fr(0)
            for mk, iv in pres.items():
                r = (iv[1] - iv[0]) / 2; worst_rr = max(worst_rr, r); mid = (iv[0] + iv[1]) / 2
                pub_res[mk] = (mid - E_PUB, mid + E_PUB)
            ck("C_producer_raw_radius_le_2^-36", worst_r <= W_GATE_PROD and worst_rr <= W_GATE_PROD, worst_channel_radius=str(worst_r), worst_response_radius=str(worst_rr))
        else:
            pch = {(d["k"], d["marker"]): (fb(d["re"]), fb(d["im"])) for d in P["channels"]}
            pres = {d["marker"]: fb(d["bits"]) for d in P["response"]}
            pub_ch = {}; 
            for k, (re, im) in pch.items():
                pub_ch[(k, "re")] = (re - E_PUB, re + E_PUB); pub_ch[(k, "im")] = (im - E_PUB, im + E_PUB)
            pub_res = {mk: (v - E_PUB, v + E_PUB) for mk, v in pres.items()}
            ck("point_publication_is_value_pm_2^-30", True)
        # --- checker side
        if arm in ("C", "PI"):
            cch = {(d["k"], d["marker"]): ((fx(d["re"][0]), fx(d["re"][1])), (fx(d["im"][0]), fx(d["im"][1]))) for d in C["channels"]}
            cres = {d["marker"]: (fx(d["iv"][0]), fx(d["iv"][1])) for d in C["response"]}
            worst_w = max([iv[1] - iv[0] for re, im in cch.values() for iv in (re, im)] + [iv[1] - iv[0] for iv in cres.values()])
            ck("interval_checker_raw_width_le_2^-35", worst_w <= W_GATE_REF, worst_width=str(worst_w))
            inner_ch = {(k, comp): iv for (k, mk), (re, im) in cch.items() for comp, iv in (("re", re), ("im", im)) for kk in [0] if (k, mk)}
            inner_ch = {}
            for (k, mk), (re, im) in cch.items():
                inner_ch[((k, mk), "re")] = re; inner_ch[((k, mk), "im")] = im
            inner_res = cres
        else:
            cch = {(d["k"], d["marker"]): (fb(d["re"]), fb(d["im"])) for d in C["channels"]}
            cres = {d["marker"]: fb(d["bits"]) for d in C["response"]}
            inner_ch = {}
            for (k, mk), (re, im) in cch.items():
                inner_ch[((k, mk), "re")] = (re - E_CH, re + E_CH); inner_ch[((k, mk), "im")] = (im - E_CH, im + E_CH)
            inner_res = {mk: (v - E_INT, v + E_INT) for mk, v in cres.items()}
            ck("point_checker_inner_radii_frozen", True, channel_radius="2^-38", response_radius="2^-36")
        # --- containment (not overlap)
        bad = []
        for ((k, mk), comp), iv in inner_ch.items():
            pub = pub_ch[((k, mk), comp)] if arm != "C" else pub_ch[((k, mk), comp)]
            if not (pub[0] <= iv[0] and iv[1] <= pub[1]): bad.append((k, mk, comp))
        ck("every_channel_inner_contained_in_publication", not bad, violations=len(bad), first=bad[:4], channels_checked=len(inner_ch))
        badr = [mk for mk, iv in inner_res.items() if not (pub_res[mk][0] <= iv[0] and iv[1] <= pub_res[mk][1])]
        ck("both_responses_contained_in_publication", not badr, violations=badr)
        # --- zero-frequency sanity: markers sum to one within the arithmetic allowance
        z = None
        if arm == "C":
            z = sum(((pch[(0, mk)][0][0] + pch[(0, mk)][0][1]) / 2 for mk in (-1, 1)), Fr(0))
        else:
            z = sum((pch[(0, mk)][0] for mk in (-1, 1)), Fr(0))
        ck("zero_frequency_markers_sum_to_one", abs(z - 1) <= 2 * E_CH, sum=str(z))
        # --- cache identities differ (producer vs checker objects) and weight/phase certificates pass
        ck("caches_separately_constructed", cprod.identity != cchk.identity)
        ck("producer_cache_certificates", all(v is True for k, v in cprod.checks.items() if isinstance(v, bool)))
        ck("checker_cache_certificates", all(v is True for k, v in cchk.checks.items() if isinstance(v, bool)))
        detail["publication_radius"] = "2^-30"
    except Exception as e:
        checks["record_well_formed"] = False; detail["error"] = f"{type(e).__name__}: {e}"
    return {"arm": arm, "verdict": "VERIFIED" if checks and all(checks.values()) else "REJECTED",
            "failed_checks": [k for k, v in checks.items() if not v], "checks": checks, "detail": detail}
