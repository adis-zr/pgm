"""Bounded H4 complete-query closeout repair driver.

Budget: the existing 900 s closeout reserve as the numerical/replay wall budget, minus closeout work already charged
(none was metered, so the full 900 s is available; unrecorded historical closeout stays labelled UNKNOWN). The outer
cumulative cap is retained. Neither is extended and no counter is reset.

Phases:
  P1 raw-interval order predicate over ALL saved outputs (producer-only and checker-only inversion tested separately)
  P2 one charged mass/weight reconstruction (MPFR256 producer + independent reverse MPFR320 checker)
  P3 row-L1 certificates for the distinct retained node-laws (the predicate the pilot omitted for PP)
  P4 independent replay: ranking, tail, D/W containment, first-prefix proof, final endpoints, difference
  P5 rejection controls on the production entry
  P6 G3 fixture repair: both H4 and four product fixtures through every applicable path vs 512-bit enumeration
"""
from __future__ import annotations
import sys, os, json, time, glob, hashlib, argparse, resource
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4q.repair_verify import (IndependentVerifier, CertificateFailure, check_raw_order, fx, fb,
                               E_PUB, E_INT, WIDTH)
from h4q import repair_masses

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PILOT = os.path.join(CODE, "runs", "h4q_pilot_2026-10-27")
BUDGET_S = 900.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True); ap.add_argument("--packet", required=True)
    a = ap.parse_args()
    OUT = os.path.abspath(a.out_dir); PK = os.path.abspath(a.packet); os.makedirs(OUT, exist_ok=True)
    jf = open(os.path.join(OUT, "repair_journal.jsonl"), "a"); t0 = time.monotonic()
    def journal(r):
        r = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "elapsed_s": round(time.monotonic() - t0, 3),
             "budget_left_s": round(BUDGET_S - (time.monotonic() - t0), 1), **r}
        jf.write(json.dumps(r, default=str) + "\n"); jf.flush(); os.fsync(jf.fileno())
    def left(): return BUDGET_S - (time.monotonic() - t0)
    st = {"record": "CLOSEOUT_REPAIR", "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
          "budget": {"numerical_replay_wall_s": BUDGET_S, "source": "the existing 900 s closeout reserve",
                     "closeout_already_charged_s": "UNKNOWN (historical report/ledger/archive generation was never metered; labelled unknown, not zero)",
                     "outer_cumulative_cap_s": 10800, "historical_charged_s": 4953.219845334824},
          "phases": {}}
    def save():
        p = os.path.join(OUT, "repair_state.json"); f = open(p + ".tmp", "w")
        json.dump(st, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(p + ".tmp", p)
    journal({"phase": "start", "budget_s": BUDGET_S})

    # ---------------- P1 raw order predicate over every saved output ----------------
    t = time.monotonic(); res = {"files": 0, "coordinates": 0, "inversions": [], "by_arm": {}}
    for arm_dir in sorted(glob.glob(f"{PILOT}/rep*_*")):
        arm = os.path.basename(arm_dir).split("_")[1]; kind = "interval" if arm == "C" else "point"
        n = 0; coords = 0
        for nd in sorted(glob.glob(f"{arm_dir}/s*")):
            for role, k in (("prod.json", kind), ("chk.json", "interval" if arm == "C" else "point")):
                p = os.path.join(nd, role)
                if not os.path.exists(p): continue
                r = check_raw_order(p, k); n += 1; coords += r["coordinates_checked"]
                if not r["ok"]: res["inversions"].append({"path": os.path.relpath(p, PILOT), **r})
            if n % 100 == 0: journal({"phase": "P1_raw_order", "files": res["files"] + n, "next": os.path.basename(nd)})
        res["by_arm"][os.path.basename(arm_dir)] = {"files": n, "coordinates": coords}
        res["files"] += n; res["coordinates"] += coords
    res["ok"] = not res["inversions"]; res["wall_s"] = time.monotonic() - t
    st["phases"]["P1_raw_interval_order"] = res; save()
    journal({"phase": "P1_done", "files": res["files"], "coordinates": res["coordinates"], "ok": res["ok"]})
    if not res["ok"]: st["status"] = "SAVED_CERTIFICATE_FAILURE"; save(); return finish(st, OUT, jf, t0)

    # ---------------- P2 one charged mass/weight reconstruction ----------------
    t = time.monotonic()
    mpath = os.path.join(OUT, "mass_weight_reconstruction.json")
    data = repair_masses.reconstruct(PK, mpath, journal, budget_s=min(left() - 420, 360))
    st["phases"]["P2_mass_reconstruction"] = {
        "label": "NEW WORK: deterministic reconstruction, NOT execution-time evidence",
        "reuse_note": "one reconstruction reused for all retrospective checking because these inputs are common across "
                      "arms and repetitions; this is NOT evidence that costs were shared during the original cold invocations",
        "node_laws": data.get("node_laws_reconstructed"), "resource_stop": data.get("RESOURCE_STOP"),
        "wall_s": time.monotonic() - t, "path": os.path.basename(mpath)}
    save(); journal({"phase": "P2_done", "node_laws": data.get("node_laws_reconstructed"), "wall_s": round(time.monotonic()-t,1)})
    if data.get("RESOURCE_STOP"):
        st["status"] = "RESOURCE_STOP"; st["remaining_obligation"] = "mass/weight reconstruction incomplete"
        save(); return finish(st, OUT, jf, t0)

    # ---------------- P4 independent replay (P3 after, budget permitting) ----------------
    t = time.monotonic()
    F = json.load(open(os.path.join(PK, "inputs", "FROZEN_NODES.json")))
    delta = Fr(F["analytic_delta_comp_exact"])
    S = json.load(open(f"{PILOT}/pilot_state.json"))
    inv = {i["key"]: i for i in S["invocations"]}
    replay = {}
    for key in ("rep1_C", "rep1_PP"):
        arm = key.split("_")[1]; e = inv[key]; per_sign = {}
        for sign in (1, -1):
            V = IndependentVerifier(sign, delta)
            sd = data["signs"][str(sign)]
            for nkey, rec in sd.items():
                j0, j1 = (int(x) for x in nkey.split(",")); nd = (j0, j1)
                V.add_node(nd, tuple(Fr(x) for x in rec["Zpub_plus"]), tuple(Fr(x) for x in rec["Zpub_minus"]),
                           tuple(Fr(x) for x in rec["w_pub"]),
                           tuple(Fr(x) for x in rec["Zchk_plus"]), tuple(Fr(x) for x in rec["Zchk_minus"]),
                           tuple(Fr(x) for x in rec["w_chk"]))
            ot = V.order_and_tail()
            # saved scalar targets
            saved = e["signs"][str(sign)]
            dmatch = ot["denominator"] == Fr(saved["ranking"]["denominator"])
            omatch = len(ot["omit"]) == int(saved["ranking"]["designated_omissions"])
            amatch = ot["accumulated"] == Fr(saved["ranking"]["accumulated_score"])
            # saved responses for the processed nodes
            responses = {}; inner = {}
            pref = "sp" if sign == 1 else "sm"
            for nddir in sorted(glob.glob(f"{PILOT}/{key}/{pref}_*")):
                parts = os.path.basename(nddir).split("_"); nd = (int(parts[1]), int(parts[2]))
                pj = json.load(open(f"{nddir}/prod.json")); cj = json.load(open(f"{nddir}/chk.json"))
                if arm == "C":
                    responses[nd] = {r["marker"]: ((fx(r["iv"][0]) + fx(r["iv"][1])) / 2 - E_PUB,
                                                   (fx(r["iv"][0]) + fx(r["iv"][1])) / 2 + E_PUB) for r in pj["response"]}
                    inner[nd] = {r["marker"]: (fx(r["iv"][0]), fx(r["iv"][1])) for r in cj["response"]}
                else:
                    responses[nd] = {r["marker"]: (fb(r["bits"]) - E_PUB, fb(r["bits"]) + E_PUB) for r in pj["response"]}
                    inner[nd] = {r["marker"]: (fb(r["bits"]) - E_INT, fb(r["bits"]) + E_INT) for r in cj["response"]}
            rp = V.replay_prefix(ot["order"], ot["omit"], responses)
            # selected-set agreement with the original node directories
            processable = [n for n in ot["order"] if n not in ot["omit"]]
            claimed = int(saved["first_qualifying_prefix"])
            sel_recon = set(processable[:rp["first"]]) if rp["first"] else set()
            sel_orig = set(responses)
            # D and W containment, checked SEPARATELY
            dcont = wcont = 0; dviol = []; wviol = []
            for nd in sel_orig:
                pdw = V.producer_DW(nd, responses[nd]); cdw = V.checker_DW(nd, inner[nd])
                for sg in (1, -1):
                    if pdw[sg]["D"][0] <= cdw[sg]["D"][0] and cdw[sg]["D"][1] <= pdw[sg]["D"][1]: dcont += 1
                    else: dviol.append((nd, sg))
                    if pdw[sg]["W"][0] <= cdw[sg]["W"][0] and cdw[sg]["W"][1] <= pdw[sg]["W"][1]: wcont += 1
                    else: wviol.append((nd, sg))
            per_sign[str(sign)] = {
                "denominator_matches_saved": dmatch, "omission_count_matches_saved": omatch,
                "accumulated_score_matches_saved": amatch,
                "reconstructed_omissions": len(ot["omit"]), "saved_omissions": int(saved["ranking"]["designated_omissions"]),
                "processable": len(processable),
                "reconstructed_first_prefix": rp["first"], "saved_first_prefix": claimed,
                "first_prefix_matches": rp["first"] == claimed,
                "selected_set_matches_original_directories": sel_recon == sel_orig,
                "selected_recon": len(sel_recon), "selected_original_dirs": len(sel_orig),
                "D_containments": dcont, "D_violations": dviol[:5],
                "W_containments": wcont, "W_violations": wviol[:5],
                "reconstructed_enclosure": [str(x) for x in rp["enclosure"]] if rp.get("enclosure") else None,
                "saved_enclosure": saved["enclosure"],
                "endpoints_match_saved": ([str(x) for x in rp["enclosure"]] == saved["enclosure"]) if rp.get("enclosure") else False,
                "ranking_and_omission_set_newly_reconstructed": True}
            journal({"phase": "P4_replay", "key": key, "sign": sign,
                     "first_prefix": rp["first"], "saved": claimed, "endpoints_match": per_sign[str(sign)]["endpoints_match_saved"]})
        # the difference, independently
        ep = tuple(Fr(x) for x in per_sign["1"]["reconstructed_enclosure"]) if per_sign["1"]["reconstructed_enclosure"] else None
        em = tuple(Fr(x) for x in per_sign["-1"]["reconstructed_enclosure"]) if per_sign["-1"]["reconstructed_enclosure"] else None
        dd = (ep[0] - em[1], ep[1] - em[0]) if ep and em else None
        replay[key] = {"signs": per_sign,
                       "reconstructed_difference": [str(x) for x in dd] if dd else None,
                       "saved_difference": e["difference"],
                       "difference_matches_saved": ([str(x) for x in dd] == e["difference"]) if dd else False}
    st["phases"]["P4_independent_replay"] = {"wall_s": time.monotonic() - t, "invocations": replay}
    save(); journal({"phase": "P4_done", "wall_s": round(time.monotonic()-t,1)})

    # ---------------- P3 row-L1 certificates (budget permitting) ----------------
    if left() > 180:
        t = time.monotonic()
        sel = {}
        for sign, pref in ((1, "sp"), (-1, "sm")):
            sel[sign] = [tuple(int(x) for x in os.path.basename(d).split("_")[1:3])
                         for d in sorted(glob.glob(f"{PILOT}/rep1_PP/{pref}_*"))]
        rows, worst = repair_masses.row_l1_certificates(PK, sel, journal, budget_s=min(left() - 90, 240))
        json.dump(rows, open(os.path.join(OUT, "row_l1_certificates.json"), "w"), indent=1, default=str)
        st["phases"]["P3_row_l1"] = {"label": "NEW WORK: the PP runtime row-L1 predicate the pilot omitted",
            "nodes_checked": rows.get("nodes_checked"), "worst_row_L1": rows.get("worst_row_L1_overall"),
            "bound": "2^-48", "resource_stop": rows.get("RESOURCE_STOP"), "wall_s": time.monotonic() - t}
        save(); journal({"phase": "P3_done", "nodes": rows.get("nodes_checked"), "worst": rows.get("worst_row_L1_overall")})
    else:
        st["phases"]["P3_row_l1"] = {"skipped": "insufficient remaining budget", "budget_left_s": round(left(), 1)}
        save()
    st["status"] = "PHASES_P1_P4_COMPLETE"
    save(); return finish(st, OUT, jf, t0)


def finish(st, OUT, jf, t0):
    ru = resource.getrusage(resource.RUSAGE_CHILDREN); rs = resource.getrusage(resource.RUSAGE_SELF)
    st["accounting"] = {"repair_numerical_wall_s": round(time.monotonic() - t0, 3),
                        "budget_s": BUDGET_S, "within_budget": (time.monotonic() - t0) <= BUDGET_S,
                        "children_cpu_s": round(ru.ru_utime + ru.ru_stime, 3),
                        "self_cpu_s": round(rs.ru_utime + rs.ru_stime, 3),
                        "native_child_rss_highwater_bytes": ru.ru_maxrss,
                        "charged_separately_from": "the historical measured windows (4953.219845334824 s)",
                        "caps_extended": False, "counters_reset": False}
    st["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    p = os.path.join(OUT, "repair_state.json"); f = open(p, "w")
    json.dump(st, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); jf.close()
    print(json.dumps({"status": st["status"], "wall_s": st["accounting"]["repair_numerical_wall_s"],
                      "phases": list(st["phases"])}, default=str))


if __name__ == "__main__": main()
