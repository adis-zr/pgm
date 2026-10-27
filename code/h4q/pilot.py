"""Frozen complete-query pilot driver. Implements ONLY the timed-stage rules sealed in
runs/h4q_preflight_2026-10-27/SEALED_EXECUTION_PACKET.json. No tuning knob, no cap override, no retry-on-slow.

One invocation = one arm, both source signs, cold caches, full positive grid:
  phase 1  cold reconstruction + certification (producer and checker separately) + domain assertion
  phase 2  ALL-node marker masses (both markers per transfer) and node weights, published, checker-contained
  phase 3  exact per-sign ranking and the frozen 1/10000 designated tail
  phase 4  selected-node responses in descending mass order, counts, weighted counts, independent replay,
           and the first-qualifying-prefix test after every node
  phase 5  aggregation over ALL node-laws (called by the width test), final publication, difference

The per-invocation deadline is enforced externally by the supervisor and internally before each node, so a cap is
reached as RESOURCE_STOP with valid partial evidence rather than by being killed mid-write."""
from __future__ import annotations
import sys, os, json, time, subprocess, hashlib, resource, argparse, signal
sys.set_int_max_str_digits(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fractions import Fraction as Fr
from h4a.model import Model, NodeProblem
from h4a.grid import Grid
from h4a.emit import Cache, write_point_witness, write_rect_witness
from h4a.build import producer_tables, checker_tables
from h4a.masses import marker_masses, publish_relative, node_weight
from h4a import certs
from h4q.aggregate import SignState, NumericalRefusal, interval_product, difference, WIDTH_TARGET, DIFF_WIDTH_TARGET

CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(CODE, "build")
CAPS = {"C": 2400.0, "PP": 600.0}
GRID_J0 = range(-19, 20); GRID_J1 = range(-16, 17)
FIELD_BOUND = Fr(10)
Q_SQRT3 = Fr(11031521092846173, 72057594037927936)


class ResourceStop(Exception): pass
class WidthFailure(Exception): pass


def _run_kernel(exe, args, hb):
    t = time.monotonic()
    p = subprocess.Popen([os.path.join(BUILD, exe), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    last = t
    while p.poll() is None:
        time.sleep(0.02)
        if time.monotonic() - last >= 4.0: last = time.monotonic(); hb({"kernel": exe, "state": "running", "elapsed_s": round(last - t, 2)})
    out, err = p.communicate()
    return p.returncode, err.decode()[:400], time.monotonic() - t


def domain_assert(model, prob):
    """assert |a_i| < 10 (the H4 contract bound); NEVER |theta_i| < 2, which belongs to another experiment"""
    worst = Fr(0)
    for i in range(model.n):
        if i in prob.pins: continue
        f = abs(prob.field[i])
        for (beta, j, u) in prob.node_coef[i]:
            s = Q_SQRT3 if beta == 3 else Fr(1, 8)
            f += s * abs(j) * abs(u)
        worst = max(worst, f)
    if worst >= FIELD_BOUND: raise NumericalRefusal(f"field bound {worst} >= 10: outside the admitted domain")
    return worst


def run_invocation(arm, rep, packet, out_dir, journal, budget_left):
    os.makedirs(out_dir, exist_ok=True)
    T0 = time.monotonic(); deadline = min(CAPS[arm], budget_left)
    def remaining(): return deadline - (time.monotonic() - T0)
    def hb(rec): journal({"arm": arm, "rep": rep, "elapsed_s": round(time.monotonic() - T0, 2),
                          "remaining_s": round(remaining(), 1), **rec})
    F = json.load(open(os.path.join(packet, "inputs", "FROZEN_NODES.json")))
    delta = Fr(F["analytic_delta_comp_exact"])
    rec = {"arm": arm, "repetition": rep, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "deadline_s": deadline, "phases": {}, "signs": {}, "stop": None}
    # ---- phase 1
    t = time.monotonic(); m = Model(128, 1)
    if m.canonical_sha256() != F["model_hash"]: raise NumericalRefusal("canonical model hash mismatch")
    g = Grid(F["frequency_grids"]["1"])
    if len(g.reps) != 265: raise NumericalRefusal("representative count")
    cp = Cache(m, g, 256); cc = Cache(m, g, 320)
    if cp.identity == cc.identity: raise NumericalRefusal("producer and checker caches not separately constructed")
    rec["phases"]["phase1_reconstruction_and_caches"] = time.monotonic() - t
    rec["cache_identities"] = {"producer": cp.identity, "checker": cc.identity}
    hb({"phase": "phase1_done", "wall_s": round(rec["phases"]["phase1_reconstruction_and_caches"], 2)})
    nodes = [(j0, j1) for j0 in GRID_J0 for j1 in GRID_J1]
    rec["grid_nodes_per_sign"] = len(nodes)
    states = {}
    # ---- phase 2: ALL-node masses and weights
    t = time.monotonic(); wcache = {}; wccache = {}; field_max = Fr(0); done = 0
    for sign in (1, -1):
        st = SignState(sign, delta); states[sign] = st
        for nd in nodes:
            if remaining() <= 1.0: raise ResourceStop(f"phase 2 at sign {sign} node {nd} ({done} node-laws done)")
            prob = NodeProblem(m, F["source_site"], sign, F["target_site"], nd, "E0")
            field_max = max(field_max, domain_assert(m, prob))
            Zp, _ = marker_masses(prob, 256); Zc, _ = marker_masses(prob, 320, reverse=True)
            if nd not in wcache:
                wv, wexp = node_weight(nd, 256); wc_, wexp_c = node_weight(nd, 320)
                if str(wexp) != str(wexp_c): raise NumericalRefusal(f"node-weight exponent differs at {nd}")
                wcache[nd] = publish_relative(wv); wccache[nd] = wc_
            pw = wcache[nd]
            for sg in (1, -1):
                pub = publish_relative(Zp[sg])["pub"]
                if not (pub[0] <= Zc[sg][0] and Zc[sg][1] <= pub[1]):
                    raise NumericalRefusal(f"checker mass not contained at {nd} marker {sg}")
            if not (pw["pub"][0] <= wccache[nd][0] and wccache[nd][1] <= pw["pub"][1]):
                raise NumericalRefusal(f"checker node weight not contained at {nd}")
            st.set_node(nd, publish_relative(Zp[1])["pub"], publish_relative(Zp[-1])["pub"], pw["pub"])
            done += 1
            if done % 100 == 0: hb({"phase": "phase2_masses", "node_laws_done": done, "of": 2 * len(nodes)})
    rec["phases"]["phase2_all_node_masses"] = time.monotonic() - t
    rec["node_laws_massed"] = done; rec["observed_field_max"] = str(field_max)
    rec["node_weight_evaluations_per_role"] = len(wcache)
    hb({"phase": "phase2_done", "wall_s": round(rec["phases"]["phase2_all_node_masses"], 2), "node_laws": done})
    # ---- phase 3: ranking and designated tail
    t = time.monotonic()
    for sign in (1, -1): rec["signs"].setdefault(str(sign), {})["ranking"] = {k: str(v) for k, v in states[sign].rank_and_designate_tail().items()}
    rec["phases"]["phase3_ranking"] = time.monotonic() - t
    # ---- phase 4: selected-node responses
    t = time.monotonic(); processed_total = 0
    for sign in (1, -1):
        st = states[sign]; sd = rec["signs"][str(sign)]; sd["processed"] = 0; sd["first_qualifying_prefix"] = None
        order = [n for n in st.order if n not in st.omit]
        for idx, nd in enumerate(order, start=1):
            if remaining() <= 15.0: raise ResourceStop(f"phase 4 at sign {sign} prefix {idx} ({processed_total} nodes processed)")
            prob = NodeProblem(m, F["source_site"], sign, F["target_site"], nd, "E0")   # reconstructed per node
            nd_dir = os.path.join(out_dir, f"s{'p' if sign==1 else 'm'}_{nd[0]}_{nd[1]}")
            os.makedirs(nd_dir, exist_ok=True)
            P = producer_tables(prob, 256)
            if arm == "C":
                write_rect_witness(f"{nd_dir}/prod.txt", prob, g, cp, P, 256, "producer")
                rc, err, dt = _run_kernel("h4rect", ["--in", f"{nd_dir}/prod.txt", "--out", f"{nd_dir}/prod.json", "--prec", "256", "--expect-freq", "265"], hb)
            else:
                write_point_witness(f"{nd_dir}/prod.txt", prob, g, cp, P, "producer")
                rc, err, dt = _run_kernel("h4point", ["--in", f"{nd_dir}/prod.txt", "--out", f"{nd_dir}/prod.json", "--expect-freq", "265"], hb)
            if rc: raise NumericalRefusal(f"producer kernel failed at {nd}: {err}")
            CK = checker_tables(prob, 320)
            if arm == "PP":
                write_point_witness(f"{nd_dir}/chk.txt", prob, g, cc, CK, "checker")
                rc, err, dt2 = _run_kernel("h4pcheck", ["--in", f"{nd_dir}/chk.txt", "--out", f"{nd_dir}/chk.json", "--expect-freq", "265"], hb)
            else:
                write_rect_witness(f"{nd_dir}/chk.txt", prob, g, cc, CK, 320, "checker")
                rc, err, dt2 = _run_kernel("h4rect", ["--in", f"{nd_dir}/chk.txt", "--out", f"{nd_dir}/chk.json", "--prec", "320", "--forward", "--expect-freq", "265"], hb)
            if rc: raise NumericalRefusal(f"checker kernel failed at {nd}: {err}")
            v = certs.verify_node(arm, f"{nd_dir}/prod.json", f"{nd_dir}/chk.json", cp, cc, g, prob)
            if v["verdict"] != "VERIFIED": raise NumericalRefusal(f"node verdict {v['verdict']} at {nd}: {v['failed_checks'][:3]}")
            Rpub = certs.response_publication(f"{nd_dir}/prod.json", arm)
            Rinner = certs.response_inner(f"{nd_dir}/chk.json", arm)
            st.process_node(nd, Rpub)
            # independent replay of D and W from the checker's own quantities
            Zc_hi = {sg: st.Zpub[(nd, sg)][1] for sg in (1, -1)}
            Tchk = st.Tpub[nd]
            for sg in (1, -1):
                prod = interval_product(Tchk, Rinner[sg]); allow = delta * Zc_hi[sg]
                lo, hi = max(Fr(0), prod[0] - allow), min(Zc_hi[sg], prod[1] + allow)
                Wc = interval_product((lo, hi), wccache[nd])
                if not (st.W[(nd, sg)][0] <= Wc[0] and Wc[1] <= st.W[(nd, sg)][1]):
                    raise NumericalRefusal(f"checker weighted count not contained at {nd} marker {sg}")
            processed_total += 1; sd["processed"] = idx
            # os.remove the bulky kernel inputs: hashes are recorded, bodies regenerate from the lock
            for fn in ("prod.txt", "chk.txt"):
                fp = os.path.join(nd_dir, fn)
                if os.path.exists(fp): os.remove(fp)
            if st.qualifies():
                sd["first_qualifying_prefix"] = idx
                e = st.prefix_enclosure()["enclosure"]
                sd["enclosure"] = [str(e[0]), str(e[1])]; sd["width"] = str(e[1] - e[0])
                hb({"phase": "qualified", "sign": sign, "prefix": idx})
                break
            if idx % 25 == 0: hb({"phase": "phase4", "sign": sign, "prefix": idx, "of": len(order),
                                  "width": float(st.width())})
        if sd["first_qualifying_prefix"] is None:
            e = st.prefix_enclosure()["enclosure"]
            sd["enclosure"] = [str(e[0]), str(e[1])]; sd["width"] = str(e[1] - e[0])
            raise WidthFailure(f"sign {sign}: all {len(order)} allowed nodes processed without reaching width 1/100 "
                               f"(final width {float(e[1]-e[0]):.6f})")
    rec["phases"]["phase4_responses"] = time.monotonic() - t
    rec["nodes_processed_total"] = processed_total
    # ---- phase 5: final publication
    ep = tuple(Fr(x) for x in rec["signs"]["1"]["enclosure"]); em = tuple(Fr(x) for x in rec["signs"]["-1"]["enclosure"])
    d = difference(ep, em)
    rec["p_plus"] = [str(x) for x in ep]; rec["p_minus"] = [str(x) for x in em]
    rec["difference"] = [str(x) for x in d]; rec["difference_width"] = str(d[1] - d[0])
    rec["width_contract_met"] = (ep[1] - ep[0] <= WIDTH_TARGET and em[1] - em[0] <= WIDTH_TARGET
                                 and d[1] - d[0] <= DIFF_WIDTH_TARGET)
    rec["stop"] = "COMPLETED"
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True); ap.add_argument("--packet", required=True)
    a = ap.parse_args()
    RUN = os.path.abspath(a.run_dir); PK = os.path.abspath(a.packet); os.makedirs(RUN, exist_ok=True)
    jf = open(os.path.join(RUN, "pilot_journal.jsonl"), "a")
    t0 = time.monotonic()
    def journal(r):
        r = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mono": round(time.monotonic() - t0, 3), **r}
        jf.write(json.dumps(r, default=str) + "\n"); jf.flush(); os.fsync(jf.fileno())
    SEAL = json.load(open(os.path.join(CODE, "runs", "h4q_preflight_2026-10-27", "SEALED_EXECUTION_PACKET.json")))
    CUM_CAP = SEAL["cumulative_accounting"]["cap_s"]; RESERVE = SEAL["cumulative_accounting"]["closeout_reserve_s"]
    spent = SEAL["cumulative_accounting"]["preflight_charged_s"]
    st = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seal": SEAL["status"],
          "schedule": [["C", "PP"], ["PP", "C"], ["C", "PP"]], "invocations": [],
          "cumulative": {"cap_s": CUM_CAP, "reserve_s": RESERVE, "preflight_charged_s": spent, "timed_charged_s": 0.0}}
    def save():
        p = os.path.join(RUN, "pilot_state.json"); f = open(p + ".tmp", "w")
        json.dump(st, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close(); os.replace(p + ".tmp", p)
    journal({"event": "pilot_start", "cumulative_cap_s": CUM_CAP, "already_charged_s": spent})
    for rep, pair in enumerate(st["schedule"], start=1):
        for arm in pair:
            key = f"rep{rep}_{arm}"; od = os.path.join(RUN, key)
            left = CUM_CAP - spent - RESERVE
            if left <= 60:
                st["invocations"].append({"key": key, "arm": arm, "rep": rep, "stop": "RESOURCE_STOP",
                                          "reason": f"cumulative budget exhausted before launch (left {left:.1f} s of the non-reserve budget)"})
                journal({"event": "skipped", "key": key, "reason": "cumulative budget"}); save(); continue
            journal({"event": "invocation_start", "key": key, "budget_left_s": round(left, 1)})
            t = time.monotonic(); r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
            entry = {"key": key, "arm": arm, "rep": rep}
            try:
                res = run_invocation(arm, rep, PK, od, journal, left)
                entry.update(res)
            except ResourceStop as e:
                entry.update({"stop": "RESOURCE_STOP", "reason": str(e)})
            except WidthFailure as e:
                entry.update({"stop": "WIDTH_FAILURE", "reason": str(e)})
            except NumericalRefusal as e:
                entry.update({"stop": "NUMERICAL_REFUSAL", "reason": str(e)})
            except Exception as e:
                entry.update({"stop": "VALIDITY_FAILURE", "reason": f"{type(e).__name__}: {e}"})
            wall = time.monotonic() - t; r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
            entry["complete_wall_s"] = wall
            entry["children_cpu_s"] = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
            entry["peak_rss_bytes"] = r1.ru_maxrss
            spent += wall; st["cumulative"]["timed_charged_s"] = round(spent - SEAL["cumulative_accounting"]["preflight_charged_s"], 3)
            st["cumulative"]["total_charged_s"] = round(spent, 3)
            st["invocations"].append(entry)
            f = open(os.path.join(od, "invocation.json"), "w") if os.path.isdir(od) else None
            if f: json.dump(entry, f, indent=1, default=str); f.flush(); os.fsync(f.fileno()); f.close()
            journal({"event": "invocation_end", "key": key, "stop": entry["stop"], "wall_s": round(wall, 2),
                     "cumulative_total_s": round(spent, 1)}); save()
    # ---- decision, strictly by the frozen rules
    pairs = {}
    for rep in (1, 2, 3):
        c = next((i for i in st["invocations"] if i["rep"] == rep and i["arm"] == "C"), None)
        p = next((i for i in st["invocations"] if i["rep"] == rep and i["arm"] == "PP"), None)
        if c and p and c.get("stop") == "COMPLETED" and p.get("stop") == "COMPLETED":
            pairs[rep] = Fr(p["complete_wall_s"]).limit_denominator(10**9) / Fr(c["complete_wall_s"]).limit_denominator(10**9)
    st["ratios"] = {str(k): {"exact": str(v), "float": float(v)} for k, v in pairs.items()}
    st["complete_valid_pairs"] = len(pairs)
    firsts = [i.get("stop") for i in st["invocations"] if i.get("stop") not in (None, "COMPLETED")]
    if len(pairs) < 3:
        st["decision"] = "INCOMPLETE_COMPARISON"
        st["decision_reason"] = (f"{len(pairs)} complete valid pairs of 3; no comparative success decision. "
                                 f"First applicable stops preserved: {firsts}")
    else:
        vals = sorted(pairs.values()); med = vals[1]
        st["median_ratio"] = {"exact": str(med), "float": float(med)}
        st["ratio_range"] = {"min": float(vals[0]), "max": float(vals[-1])}
        st["decision"] = "GO" if med <= Fr(1, 4) else "NO_GO_FOR_THIS_KERNEL_AT_QUERY_SCALE"
        if vals[0] <= Fr(1, 4) <= vals[-1]: st["qualification"] = "SENSITIVE_TO_RUN_VARIATION"
    st["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save(); jf.close()
    print(json.dumps({"decision": st["decision"], "pairs": st["complete_valid_pairs"],
                      "ratios": st["ratios"], "median": st.get("median_ratio"),
                      "qualification": st.get("qualification"),
                      "total_charged_s": st["cumulative"]["total_charged_s"]}, default=str))


if __name__ == "__main__": main()
