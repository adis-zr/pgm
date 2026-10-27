"""ONE separately charged deterministic reconstruction of the all-grid mass/weight evidence the pilot never persisted.

Uses the bound code at 68a8325: MPFR256 producer (forward) and the independent reverse MPFR320 checker, exactly as the
pilot did. These inputs are common across arms and repetitions, so this single reconstruction is reused for all
retrospective checking. THAT REUSE IS NOT EVIDENCE THAT COSTS WERE SHARED during the original cold invocations: each
invocation paid for its own mass pass, as its phase-2 timing records.

Everything produced here is NEW WORK, labelled reconstruction, never execution-time evidence."""
from __future__ import annotations
import sys, os, json, time
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.masses import marker_masses, publish_relative, node_weight

GRID = [(j0, j1) for j0 in range(-19, 20) for j1 in range(-16, 17)]


def reconstruct(packet, out_path, journal, budget_s, row_l1_check=True):
    """returns {sign: {node: {...}}} and writes it; stops durably if the budget runs out"""
    t0 = time.monotonic()
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    m = Model(128, 1)
    if m.canonical_sha256() != F["model_hash"]: raise RuntimeError("model hash mismatch")
    data = {"record": "MASS_WEIGHT_RECONSTRUCTION", "label": "NEW WORK, not execution-time evidence",
            "model_hash": F["model_hash"], "grid_nodes_per_sign": len(GRID), "signs": {}, "row_l1": {}}
    wcache = {}
    done = 0; last = t0
    for sign in (1, -1):
        sd = {}
        for nd in GRID:
            if time.monotonic() - t0 > budget_s:
                data["RESOURCE_STOP"] = {"after_node_laws": done, "sign": sign, "node": list(nd),
                                         "elapsed_s": round(time.monotonic() - t0, 1)}
                data["signs"][str(sign)] = sd
                json.dump(data, open(out_path, "w"), indent=1, default=str)
                journal({"phase": "mass_reconstruction", "event": "RESOURCE_STOP", "node_laws": done})
                return data
            prob = NodeProblem(m, F["source_site"], sign, F["target_site"], nd, "E0")
            Zp, ep = marker_masses(prob, 256)
            Zc, ec = marker_masses(prob, 320, reverse=True)
            if nd not in wcache:
                wv, wexp = node_weight(nd, 256); wc, wexp_c = node_weight(nd, 320)
                wcache[nd] = {"pub": publish_relative(wv)["pub"], "checker_unpadded": wc,
                              "exponent_producer": str(wexp), "exponent_checker": str(wexp_c),
                              "exponents_equal": str(wexp) == str(wexp_c)}
            pub = {sg: publish_relative(Zp[sg])["pub"] for sg in (1, -1)}
            for sg in (1, -1):
                if not (pub[sg][0] <= Zc[sg][0] and Zc[sg][1] <= pub[sg][1]):
                    raise RuntimeError(f"checker mass not contained at sign {sign} node {nd} marker {sg}")
            w = wcache[nd]
            if not (w["pub"][0] <= w["checker_unpadded"][0] and w["checker_unpadded"][1] <= w["pub"][1]):
                raise RuntimeError(f"checker weight not contained at {nd}")
            sd[f"{nd[0]},{nd[1]}"] = {
                "Zpub_plus": [str(x) for x in pub[1]], "Zpub_minus": [str(x) for x in pub[-1]],
                "Zchk_plus": [str(x) for x in Zc[1]], "Zchk_minus": [str(x) for x in Zc[-1]],
                "w_pub": [str(x) for x in w["pub"]], "w_chk": [str(x) for x in w["checker_unpadded"]],
                "w_exponent": w["exponent_producer"], "w_exponents_equal": w["exponents_equal"],
                "scale_exponents": {"producer": ep, "checker": ec}}
            done += 1
            if time.monotonic() - last >= 4.0:
                last = time.monotonic()
                journal({"phase": "mass_reconstruction", "node_laws_done": done, "of": 2 * len(GRID),
                         "elapsed_s": round(last - t0, 1), "next": f"sign {sign} after {nd}"})
        data["signs"][str(sign)] = sd
    data["node_laws_reconstructed"] = done
    data["node_weight_evaluations"] = len(wcache)
    data["elapsed_s"] = round(time.monotonic() - t0, 3)
    json.dump(data, open(out_path, "w"), indent=1, default=str)
    journal({"phase": "mass_reconstruction", "event": "complete", "node_laws": done,
             "elapsed_s": data["elapsed_s"]})
    return data


def row_l1_certificates(packet, nodes_by_sign, journal, budget_s):
    """Restore the PP probability-row L1 <= 2^-48 predicate, including boundary rows, for the DISTINCT retained
    node-laws. The inherited uniform proof supports these rows, but an omitted runtime check is not an executed one."""
    from h4a.build import producer_tables, checker_tables
    from h4a.tables import EPS_P
    t0 = time.monotonic()
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    m = Model(128, 1)
    out = {"record": "ROW_L1_CERTIFICATES", "label": "NEW WORK: the runtime predicate the pilot omitted for PP",
           "bound": "2^-48", "signs": {}}
    worst_overall = Fr(0); checked = 0
    for sign, nodes in nodes_by_sign.items():
        sd = {}
        for nd in nodes:
            if time.monotonic() - t0 > budget_s:
                out["RESOURCE_STOP"] = {"checked": checked, "elapsed_s": round(time.monotonic()-t0,1)}
                out["signs"][str(sign)] = sd; return out, worst_overall
            prob = NodeProblem(m, F["source_site"], int(sign), F["target_site"], tuple(nd), "E0")
            P = producer_tables(prob, 256); C = checker_tables(prob, 320)
            wp = max([P["terminal"][1]] + [l1 for pc in P["rows"] for (_, l1, _e) in pc.values()])
            wc = max([C["initial"][1]] + [l1 for pc in C["rows"].values() for (_, l1, _e) in pc.values()])
            nrows_p = 1 + sum(len(pc) for pc in P["rows"]); nrows_c = 1 + sum(len(pc) for pc in C["rows"].values())
            if wp > EPS_P or wc > EPS_P:
                raise RuntimeError(f"row L1 exceeds 2^-48 at sign {sign} node {nd}: producer {wp}, checker {wc}")
            sd[f"{nd[0]},{nd[1]}"] = {"producer_worst_row_L1": str(wp), "checker_worst_row_L1": str(wc),
                                      "producer_rows_incl_boundary": nrows_p, "checker_rows_incl_boundary": nrows_c}
            worst_overall = max(worst_overall, wp, wc); checked += 1
            if checked % 20 == 0:
                journal({"phase": "row_l1", "nodes_checked": checked, "elapsed_s": round(time.monotonic()-t0,1),
                         "worst_so_far": str(worst_overall)})
        out["signs"][str(sign)] = sd
    out["nodes_checked"] = checked; out["worst_row_L1_overall"] = str(worst_overall)
    out["elapsed_s"] = round(time.monotonic() - t0, 3)
    return out, worst_overall
