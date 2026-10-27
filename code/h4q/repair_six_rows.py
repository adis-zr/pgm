"""Six-row verification summary: every original invocation replayed against ITS OWN response records.

Instruction 1: one row per original invocation, 566 D and 566 W containment checks each (283 processed nodes x 2
markers), independent ranking/omission/first-prefix verification, and exact agreement with THAT invocation's final
endpoints and difference. Across six invocations: 3,396 D and 3,396 W.

Reusing the reconstructed masses is legitimate (they are arm- and repetition-independent inputs). Substituting one
invocation's responses for another's is NOT: each row reads only its own rep{N}_{ARM}/ directories, and the loader
asserts the directory it read from."""
from __future__ import annotations
import sys, os, json, time, glob
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4q.repair_verify import IndependentVerifier, CertificateFailure, fx, fb, E_PUB, E_INT, WIDTH

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOT = os.path.join(CODE, "runs", "h4q_pilot_2026-10-27")


def _load_verifier(recon, sign, delta):
    V = IndependentVerifier(sign, delta)
    for nkey, r in recon["signs"][str(sign)].items():
        nd = tuple(int(x) for x in nkey.split(","))
        V.add_node(nd, tuple(Fr(x) for x in r["Zpub_plus"]), tuple(Fr(x) for x in r["Zpub_minus"]),
                   tuple(Fr(x) for x in r["w_pub"]), tuple(Fr(x) for x in r["Zchk_plus"]),
                   tuple(Fr(x) for x in r["Zchk_minus"]), tuple(Fr(x) for x in r["w_chk"]))
    return V


def _own_responses(key, arm, sign):
    """responses read ONLY from this invocation's own directories, with provenance recorded per node"""
    pref = "sp" if sign == 1 else "sm"
    pub, inner, src = {}, {}, {}
    for d in sorted(glob.glob(os.path.join(PILOT, key, f"{pref}_*"))):
        nd = tuple(int(x) for x in os.path.basename(d).split("_")[1:3])
        pj = json.load(open(os.path.join(d, "prod.json"))); cj = json.load(open(os.path.join(d, "chk.json")))
        assert os.path.basename(os.path.dirname(d)) == key, "response read from the wrong invocation"
        if arm == "C":
            pub[nd] = {r["marker"]: ((fx(r["iv"][0]) + fx(r["iv"][1])) / 2 - E_PUB,
                                     (fx(r["iv"][0]) + fx(r["iv"][1])) / 2 + E_PUB) for r in pj["response"]}
            inner[nd] = {r["marker"]: (fx(r["iv"][0]), fx(r["iv"][1])) for r in cj["response"]}
        else:
            pub[nd] = {r["marker"]: (fb(r["bits"]) - E_PUB, fb(r["bits"]) + E_PUB) for r in pj["response"]}
            inner[nd] = {r["marker"]: (fb(r["bits"]) - E_INT, fb(r["bits"]) + E_INT) for r in cj["response"]}
        src[f"{nd[0]},{nd[1]}"] = os.path.relpath(d, PILOT)
    return pub, inner, src


def run(packet, out_path, journal, budget_s, skip=()):
    t0 = time.monotonic()
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    delta = Fr(F["analytic_delta_comp_exact"])
    recon = json.load(open(os.path.join(CODE, "runs", "h4q_repair_2026-10-27", "mass_weight_reconstruction.json")))
    S = json.load(open(os.path.join(PILOT, "pilot_state.json")))
    inv = {i["key"]: i for i in S["invocations"]}
    rows = {}
    order = ["rep1_C", "rep1_PP", "rep2_PP", "rep2_C", "rep3_C", "rep3_PP"]
    for key in order:
        if time.monotonic() - t0 > budget_s:
            journal({"phase": "six_rows", "event": "RESOURCE_STOP", "completed": list(rows)})
            break
        arm = key.split("_")[1]; e = inv[key]
        row = {"invocation": key, "arm": arm, "repetition": e["rep"],
               "original_response_records": {}, "signs": {}, "D_checks": 0, "W_checks": 0}
        for sign in (1, -1):
            V = _load_verifier(recon, sign, delta)
            pub, inner, src = _own_responses(key, arm, sign)
            row["original_response_records"][str(sign)] = {"count": len(src), "directory_prefix": f"{key}/{'sp' if sign==1 else 'sm'}_*",
                                                           "example": sorted(src.values())[0] if src else None}
            ot = V.order_and_tail()
            saved = e["signs"][str(sign)]
            rp = V.replay_prefix(ot["order"], ot["omit"], pub)
            # D and W containment, separately, for every processed node and marker
            dc = wc = 0; dv = []; wv = []
            for nd in pub:
                p = V.producer_DW(nd, pub[nd]); c = V.checker_DW(nd, inner[nd])
                for sg in (1, -1):
                    if p[sg]["D"][0] <= c[sg]["D"][0] and c[sg]["D"][1] <= p[sg]["D"][1]: dc += 1
                    else: dv.append([list(nd), sg])
                    if p[sg]["W"][0] <= c[sg]["W"][0] and c[sg]["W"][1] <= p[sg]["W"][1]: wc += 1
                    else: wv.append([list(nd), sg])
            widths = dict(rp["widths"])
            claimed = int(saved["first_qualifying_prefix"])
            earlier = [i for i, w in rp["widths"] if w <= WIDTH and i < claimed]
            processable = [n for n in ot["order"] if n not in ot["omit"]]
            row["signs"][str(sign)] = {
                "ranking_denominator_matches": ot["denominator"] == Fr(saved["ranking"]["denominator"]),
                "omission_count_matches": len(ot["omit"]) == int(saved["ranking"]["designated_omissions"]),
                "accumulated_tail_score_matches": ot["accumulated"] == Fr(saved["ranking"]["accumulated_score"]),
                "omissions": len(ot["omit"]), "processable": len(processable),
                "first_prefix_reconstructed": rp["first"], "first_prefix_claimed": claimed,
                "first_prefix_matches": rp["first"] == claimed,
                "no_earlier_prefix_qualifies": not earlier,
                "width_at_prefix_minus_1": str(widths.get(claimed - 1)) if claimed - 1 in widths else None,
                "width_at_prefix": str(widths.get(claimed)) if claimed in widths else None,
                "selected_set_matches_own_directories": (set(processable[:rp["first"]]) == set(pub)) if rp["first"] else False,
                "D_containments": dc, "D_violations": dv[:5],
                "W_containments": wc, "W_violations": wv[:5],
                "endpoints_match_this_invocation": ([str(x) for x in rp["enclosure"]] == saved["enclosure"]) if rp.get("enclosure") else False,
                "reconstructed_enclosure": [str(x) for x in rp["enclosure"]] if rp.get("enclosure") else None,
                "saved_enclosure": saved["enclosure"]}
            row["D_checks"] += dc; row["W_checks"] += wc
            journal({"phase": "six_rows", "invocation": key, "sign": sign, "D": dc, "W": wc,
                     "prefix": rp["first"], "endpoints_match": row["signs"][str(sign)]["endpoints_match_this_invocation"],
                     "elapsed_s": round(time.monotonic() - t0, 1)})
        ep = row["signs"]["1"]["reconstructed_enclosure"]; em = row["signs"]["-1"]["reconstructed_enclosure"]
        if ep and em:
            a = tuple(Fr(x) for x in ep); b = tuple(Fr(x) for x in em)
            dd = [str(a[0] - b[1]), str(a[1] - b[0])]
            row["reconstructed_difference"] = dd
            row["difference_matches_this_invocation"] = dd == e["difference"]
            row["saved_difference"] = e["difference"]
        row["all_checks_pass"] = (row["D_checks"] == 566 and row["W_checks"] == 566
            and all(s["ranking_denominator_matches"] and s["omission_count_matches"] and s["accumulated_tail_score_matches"]
                    and s["first_prefix_matches"] and s["no_earlier_prefix_qualifies"] and s["selected_set_matches_own_directories"]
                    and s["endpoints_match_this_invocation"] and not s["D_violations"] and not s["W_violations"]
                    for s in row["signs"].values())
            and row.get("difference_matches_this_invocation", False))
        rows[key] = row
    out = {"record": "SIX_ROW_VERIFICATION_SUMMARY",
           "basis": "each invocation replayed against ITS OWN response records; the reconstructed masses are shared "
                    "because they are arm- and repetition-independent inputs, but no invocation's responses were "
                    "substituted for another's (each row asserts the directory it read)",
           "rows": rows,
           "totals": {"invocations": len(rows), "D_checks": sum(r["D_checks"] for r in rows.values()),
                      "W_checks": sum(r["W_checks"] for r in rows.values())},
           "elapsed_s": round(time.monotonic() - t0, 3)}
    out["all_rows_pass"] = len(rows) == 6 and all(r["all_checks_pass"] for r in rows.values())
    json.dump(out, open(out_path, "w"), indent=1, default=str)
    return out
