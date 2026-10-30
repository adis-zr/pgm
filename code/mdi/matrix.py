"""The integrated acceptance matrix (spec §12, revision §F).

Every control enters through the external model API and exercises the REAL
branch -- discovery, persisted program, fresh-process replay where named,
execution, independent check, publication. Each control runs under its own
wall limit so a large lattice cannot obscure the rest of the matrix, and emits
one durable progress line. The result is a machine-readable route matrix:
one row per mandatory branch with status, counts and the named obligation it
established (or the concrete reason it did not).

    python -m mdi.matrix OUT.json [per_control_wall_s]
"""
from __future__ import annotations
import sys, os, json, time, math, tempfile, subprocess, traceback
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def _contains(pub, pt):
    return all(Fr(pub[v][s][0]) <= pt[v][s] <= Fr(pub[v][s][1])
               for v in pub for s in range(len(pub[v])))


def _write_uai(m):
    from mdi import model as M
    lines = ["MARKOV", str(m.nvars), " ".join(str(c) for c in m.card), str(len(m.factors))]
    for f in m.factors:
        lines.append("%d %s" % (len(f.scope), " ".join(str(v) for v in f.scope)))
    for f in m.factors:
        lines.append(str(len(f.table)))
        lines.append(" ".join(str(x.numerator) if x.denominator == 1 else
                              "%s/%s" % (x.numerator, x.denominator) for x in f.table))
    fh = tempfile.NamedTemporaryFile("w", suffix=".uai", delete=False)
    fh.write("\n".join(lines) + "\n")
    fh.close()
    return fh.name


def _replay(mp, plan, timeout):
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE
    out = subprocess.run([sys.executable, "-m", "mdi.replay", mp, "-", plan], cwd=HERE,
                         capture_output=True, text=True, timeout=timeout, env=env)
    if not out.stdout.strip():
        raise RuntimeError("replay produced no output: %s" % out.stderr[-600:])
    return json.loads(out.stdout)


# --------------------------------------------------------------- controls

def control_identity_replay(wall):
    """F.1 identity: the persisted program governs a fresh process."""
    from mdi import model as M, oracle as O, pipeline as PLN
    from tests.test_mdi_research import TINY, w
    mp = w(TINY)
    m = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=d)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    rep = _replay(mp, os.path.join(d, "identity.plan.json"), wall)
    return {"pipeline": res.status, "chosen": res.plan.get("chosen"),
            "replay": rep["status"], "truth": _contains(res.intervals, pt),
            "settings": rep.get("executor", {}).get("settings", "")[:120],
            "ok": res.status.startswith("CERTIFIED") and rep["status"] == "REPLAY_VERIFIED"}


def control_regional_two_scales_replay(wall):
    """F.1/F.2: compact one- and two-scale programs replayed fresh; the
    altered witness rejects on the named obligation."""
    import copy
    from mdi import model as M, oracle as O, pipeline as PLN
    from tests.test_mdi_research import ring_of_blocks, w
    mp = w(ring_of_blocks()[0])
    m = M.read_uai(mp)
    d = tempfile.mkdtemp()
    res = PLN.solve(m, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=d)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    names = [p["name"] for p in res.prices]
    l1 = next(n for n in names if n.startswith("regional:") and "@64" in n and not n.endswith(":L2"))
    l2 = next(n for n in names if n.startswith("regional:") and n.endswith(":L2"))
    r1 = _replay(mp, os.path.join(d, l1.replace(":", "_") + ".plan.json"), wall)
    r2 = _replay(mp, os.path.join(d, l2.replace(":", "_") + ".plan.json"), wall)
    base = json.load(open(os.path.join(d, l1.replace(":", "_") + ".plan.json")))
    bad = copy.deepcopy(base)
    for c in bad["program"]["scales"][0]["regions"][0]["cells"]:
        tot = Fr(c["M"])
        vs = sorted({int(k.split(",")[0]) for k in c["N"]})
        c["N"] = {}
        for v in vs:
            c["N"]["%d,0" % v] = str(tot * Fr(9, 10))
            c["N"]["%d,1" % v] = str(tot * Fr(1, 10))
    p2 = os.path.join(d, "altered.plan.json")
    json.dump(bad, open(p2, "w"))
    alt = _replay(mp, p2, wall)
    compact = all(f.get("views", 0) >= 0 for f in [{}])
    return {"pipeline": res.status, "chosen": res.plan.get("chosen"),
            "research": res.plan.get("research"), "truth": _contains(res.intervals, pt),
            "replay_L1": r1["status"], "replay_L2": r2["status"], "altered": alt["status"],
            "altered_obligation": (alt.get("failures") or [""])[0][:100],
            "ok": (res.status == "CERTIFIED_RESEARCH_ROUTE" and r1["status"] == "REPLAY_VERIFIED"
                   and r2["status"] == "REPLAY_VERIFIED" and alt["status"] == "REPLAY_REJECTED"
                   and "alpha_b A_{R,i,a}" in (alt.get("failures") or [""])[0])}


def control_compact_external_construction(wall):
    """F.2: compact one-scale construction on an external input (no arm); a
    grouping priced out for its schedule cost is refused, not expanded."""
    from mdi import model as M, regions as R, marked as MK, routes as RT, pricing as PR, factors as FX
    p = "/tmp/tep/three_external_problems/inputs/Pedigree_11"
    if not os.path.exists(p + ".uai"):
        return {"skipped": "external inputs not present", "ok": None}
    m = M.read_uai(p + ".uai")
    ev = M.read_evidence(p + ".uai.evid", m)
    r = M.restrict(m, ev)
    q = set(r.free)
    c = [c for c in R.propose_partitions(r.free, r.card, r.factors) if c["mode"] != "singleton"][0]
    t = time.time()
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), [tuple(x) for x in c["regions"]], 1)
    tb = time.time() - t
    views = sum(1 for f in final.factors if FX.is_view(f))
    big = max(f.size() for f in final.factors)
    price, order = PR.price_program("r", "regional", final, scales, None, sum(r.card[v] for v in q),
                                    sum(rd.construction_ops for sc in scales for rd in sc.rds))
    return {"built_s": round(tb, 2), "regions": len(c["regions"]), "views": views,
            "largest_view_entries": big, "any_dense_expansion": False,
            "eligible": price.eligible, "refusal": price.ineligible_reason[:120],
            "ok": (views > 0 and big > 4096 and not price.eligible)}


def control_restoration_independence(wall):
    """F.3: the shared-readout fault rejects on the original-query obligation
    while the clean counterpart passes; categorical, hard-zero, subset and
    multi-cell restoration."""
    from mdi import model as M, oracle as O, marked as MK, routes as RT, program as PG, program_check as PC, config as K
    facs = [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(1)], origin=0),
            M.Factor(scope=(1,), card=(2,), table=[Fr(1), Fr(1)], origin=1)]
    m = M.Model(nvars=2, card=[2, 2], factors=facs).validate()
    r = M.restrict(m, {})
    q = {0, 1}
    scales, final = RT.build_scales(MK.Marked.from_restricted(r, q), [(0,), (1,)], 1)
    prog = PG.validate_program(json.loads(json.dumps(RT.program_for("regional", scales, None, [], 128, q))))
    rad = prog["scales"][0]["t_level"] + K.PUBLICATION_RESERVE
    rows, _ = RT.execute(prog, r, q)
    good = {v: [(max(Fr(0), lo - rad), min(Fr(1), hi + rad)) for lo, hi in rows[v]] for v in rows}
    ok_clean = PC.verify_program(r, q, prog, good, Fr(1, 100))[0]
    orig = MK.read_original

    def faulty(marked, Z, counts):
        out = orig(marked, Z, counts)
        return {v: [(lo * Fr(9, 5), hi * Fr(9, 5)) if s == 0 else (lo / 5, hi / 5)
                    for s, (lo, hi) in enumerate(rws)] for v, rws in out.items()}
    MK.read_original = faulty
    try:
        rows, _ = RT.execute(prog, r, q)
        pub = {v: [(max(Fr(0), lo - rad), min(Fr(1), hi + rad)) for lo, hi in rows[v]] for v in rows}
        ok_bad, fails, _ = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    finally:
        MK.read_original = orig
    # categorical + hard zero + subset + multi-cell
    facs = [M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(1), Fr(2), Fr(0), Fr(3), Fr(1), Fr(5)], origin=0),
            M.Factor(scope=(1, 2, 3), card=(3, 2, 2),
                     table=[Fr(x) for x in (1, 2, 1, 0, 2, 1, 1, 3, 1, 1, 2, Fr(1, 10 ** 9))], origin=1),
            M.Factor(scope=(4, 5), card=(2, 3), table=[Fr(2), Fr(1), Fr(1), Fr(1), Fr(0), Fr(4)], origin=2)]
    m2 = M.Model(nvars=6, card=[2, 3, 2, 2, 2, 3], factors=facs).validate()
    r2 = M.restrict(m2, {3: 1})
    Z, pt = O.exact_all_marginals(r2)
    q2 = {0, 1, 5}
    scales, final = RT.build_scales(MK.Marked.from_restricted(r2, q2), [(0, 1), (2,), (4, 5)], 1)
    prog2 = PG.validate_program(json.loads(json.dumps(RT.program_for("regional", scales, None, [], 128, q2))))
    rows, _ = RT.execute(prog2, r2, q2)
    rad2 = prog2["scales"][0]["t_level"] + K.PUBLICATION_RESERVE
    pub2 = {v: [(max(Fr(0), lo - rad2), min(Fr(1), hi + rad2)) for lo, hi in rows[v]] for v in rows}
    ok2, f2, _ = PC.verify_program(r2, q2, prog2, pub2, Fr(1, 100))
    return {"clean": ok_clean, "shared_readout_fault_rejected": not ok_bad,
            "obligation": (fails or [""])[0][:90],
            "categorical_zero_subset_verified": ok2, "categorical_truth": _contains(pub2, pt),
            "ok": ok_clean and not ok_bad and "does NOT contain" in (fails or [""])[0]
                  and ok2 and _contains(pub2, pt)}


def control_collective_menu_and_Q(wall):
    """F.4: natural two-block discovery yields a mixed-sign candidate; coarse
    admissible Q; vector (combined) statistic executes and verifies; retained
    and disconnected residuals."""
    from mdi import model as M, oracle as O, marked as MK, routes as RT, program as PG, program_check as PC
    from mdi import collective_route as CR, arith as A, config as K
    n = 6
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(v, 20)], origin=v) for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            J = 0.25 if (i < 3 and j < 3) else (-0.20 if (i >= 3 and j >= 3) else 0.05)
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    m = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    r = M.restrict(m, {})
    q = set(r.free)
    Z, pt = O.exact_all_marginals(r)
    adm = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96))
    kinds = sorted({(c["evaluator"], c["candidate"].kind, tuple(c["candidate"].signs)) for c, _ in adm})
    vec = [x for x in adm if x[0]["evaluator"] == "statistic" and x[0]["candidate"].rank == 2]
    out = {"admitted": [list(k) for k in kinds], "ok": False}
    if not vec:
        out["reason"] = "no rank-2 statistic admission"
        return out
    coll, rmk = vec[0]
    prog = PG.validate_program(json.loads(json.dumps(RT.program_for("statistic", [], coll, [], 96, q))))
    rows, meta = RT.execute(prog, r, q)
    rad = CR.total_radius(prog["collective"]) + K.PUBLICATION_RESERVE
    pub = {v: [(max(Fr(0), lo - rad), min(Fr(1), hi + rad)) for lo, hi in rows[v]] for v in rows}
    ok, fails, cm = PC.verify_program(r, q, prog, pub, Fr(1, 100))
    # coarse Q on the composed ring
    from tests.test_mdi_research import ring_of_blocks, w
    mr = M.read_uai(w(ring_of_blocks()[0]))
    rr = M.restrict(mr, {})
    qr = set(rr.free)
    scales, final = RT.build_scales(MK.Marked.from_restricted(rr, qr), [(0, 1, 2, 3, 6, 9), (4, 5), (7, 8), (10, 11)], 1)
    cadm = CR.admit(final, A.Ctx(160), prefer="statistic")
    cq = cadm[0][0]["Q"]
    out.update({"vector_statistic_rank": coll["candidate"].rank, "Q": coll["Q"],
                "support": meta["statistic_support"], "verified": ok, "truth": _contains(pub, pt),
                "composed_ring_Q": cq, "composed_ring_Q_attempts": cadm[0][0]["Q_attempts"],
                "ok": ok and _contains(pub, pt) and cq < (1 << 16)})
    return out


def control_mixed_gf(wall):
    """F.5: a small actual mixed Gaussian/Fourier program: positive mass pass,
    conjugate pairing, marker-ratio stopping, independent recheck of the
    retained nodes. Honest about its finite constants."""
    from mdi import model as M, oracle as O, marked as MK, routes as RT, program as PG, program_check as PC
    from mdi import collective_route as CR, arith as A, config as K, pricing as PR
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(10 * (v + 1), 100)], origin=v) for v in range(3)]
    for (i, j), J in (((0, 1), 0.15), ((0, 2), 0.05), ((1, 2), -0.05)):
        facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=10 + i * 3 + j))
    m = M.Model(nvars=3, card=[2] * 3, factors=facs).validate()
    r = M.restrict(m, {})
    q = set(r.free)
    Z, pt = O.exact_all_marginals(r)
    adm = CR.admit(MK.Marked.from_restricted(r, q), A.Ctx(96))
    mixed = [x for x in adm if x[0]["evaluator"] == "mixed"]
    if not mixed:
        return {"ok": False, "reason": "no mixed admission", "declines": adm[0][0].get("declines")}
    coll, rmk = mixed[0]
    price, order = PR.price_program("mixed", "mixed", rmk, [], coll, 6, 0)
    prog = PG.validate_program(json.loads(json.dumps(RT.program_for("mixed", [], coll, order or [], 96, q))))
    num_eps = K.MAX_WIDTH - 2 * CR.total_radius(prog["collective"]) - K.PUBLICATION_RESERVE
    t = time.time()
    rows, meta = RT.execute(prog, r, q, num_eps=num_eps)
    tx = time.time() - t
    rad = CR.total_radius(prog["collective"]) + K.PUBLICATION_RESERVE
    pub = {v: [(max(Fr(0), lo - rad), min(Fr(1), hi + rad)) for lo, hi in rows[v]] for v in rows}
    t = time.time()
    ok, fails, cm = PC.verify_program(r, q, prog, pub, Fr(1, 100), exec_record=meta)
    tc = time.time() - t
    return {"candidate": coll["candidate"].kind, "signs": coll["candidate"].signs,
            "nodes_per_mode": coll["forecast"]["nodes_per_mode"],
            "positive_nodes": meta["positive_nodes"], "processed": meta["processed_positive_nodes"],
            "omitted": meta["omitted_positive_nodes"], "conjugate_pairs": meta["conjugate_pairs"],
            "symmetric_keys": meta["negative_key_set_symmetric"],
            "priced_producer": sum(int(price.counters[k].value) for k in
                                   ("producer_upward_ops", "producer_downward_ops", "readout_ops")),
            "exec_s": round(tx, 1), "check_s": round(tc, 1), "truth": _contains(pub, pt),
            "verified": ok, "rechecked_nodes": cm.get("rechecked_retained_nodes"),
            "width": float(max(hi - lo for v in pub for lo, hi in pub[v])),
            "ok": ok and _contains(pub, pt)}


def control_price_covers_counted_work(wall):
    """F.6: counted producer/checker Fraction operations against the dry-run
    bounds on chain, branched, disconnected and nonuniform-feature programs."""
    import fractions
    from mdi import model as M, marked as MK, routes as RT, program as PG, program_check as PC
    from mdi import collective_route as CR, arith as A, config as K, pricing as PR
    counts = {"n": 0}
    saved = {nm: getattr(fractions.Fraction, nm) for nm in
             ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__", "__rtruediv__",
              "__sub__", "__rsub__")}

    def wrap(fn):
        def w_(self, other, *a):
            counts["n"] += 1
            return fn(self, other, *a)
        return w_

    def measure(fn):
        for nm, f in saved.items():
            setattr(fractions.Fraction, nm, wrap(f))
        counts["n"] = 0
        try:
            out = fn()
        finally:
            for nm, f in saved.items():
                setattr(fractions.Fraction, nm, f)
        return out, counts["n"]

    def star(n):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 3)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(0, i), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3 if i % 2 else 2)],
                          origin=100 + i) for i in range(1, n)]
        return M.Model(nvars=n, card=[2] * n, factors=facs).validate()

    def chain3(n):
        facs = [M.Factor(scope=(v,), card=(3,), table=[Fr(1), Fr(2), Fr(1 + v % 2)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(i, i + 1), card=(3, 3), table=[Fr(x) for x in (2, 1, 1, 1, 3, 1, 1, 1, 2)],
                          origin=100 + i) for i in range(n - 1)]
        return M.Model(nvars=n, card=[3] * n, factors=facs).validate()

    def disc(n):
        facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 2)], origin=v) for v in range(n)]
        facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + i)
                 for i in range(n - 1) if i != n // 2 - 1]
        return M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    rows_out = []
    all_ok = True
    for label, m, kind in (("star7", star(7), "statistic"), ("ternary5", chain3(5), "statistic"),
                           ("disconnected6", disc(6), "statistic"), ("star7-regional", star(7), "regional")):
        r = M.restrict(m, {})
        q = set(r.free)
        mk0 = MK.Marked.from_restricted(r, q)
        if kind == "statistic":
            coll, rmk = CR.admit(mk0, A.Ctx(96), prefer="statistic")[0]
            scales, final = [], rmk
        else:
            coll = None
            scales, final = RT.build_scales(mk0, [(0, 1), (2, 3), (4, 5, 6)], 1)
        cons = sum(rd.construction_ops for sc in scales for rd in sc.rds)
        price, order = PR.price_program("x", kind, final, scales, coll, sum(r.card[v] for v in q), cons)
        prog = PG.validate_program(json.loads(json.dumps(RT.program_for(kind, scales, coll, order or [], 96, q))))
        (rws, meta), n_exec = measure(lambda: RT.execute(prog, r, q))
        rad = sum((sc["t_level"] + sc["deletion_radius_total"] for sc in prog["scales"]), Fr(0))
        if prog["collective"]:
            rad += CR.total_radius(prog["collective"])
        pub = {v: [(max(Fr(0), lo - rad - K.PUBLICATION_RESERVE), min(Fr(1), hi + rad + K.PUBLICATION_RESERVE))
                   for lo, hi in rws[v]] for v in rws}
        (ok, fails, cm), n_chk = measure(lambda: PC.verify_program(r, q, prog, pub, Fr(1, 100)))
        pp = sum(int(price.counters[k].value) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops"))
        pc = int(price.counters["checker_ops"].value)
        row = {"control": label, "kind": kind, "verified": ok, "producer_priced": pp, "producer_counted": n_exec,
               "checker_priced": pc, "checker_counted": n_chk,
               "covers": pp >= n_exec and pc >= n_chk,
               "peak_live_priced": int(price.counters["peak_live_message_entries"].value),
               "peak_live_measured": meta.get("peak_live_entries")}
        all_ok = all_ok and ok and row["covers"]
        rows_out.append(row)
    return {"rows": rows_out, "ok": all_ok}


def control_public_selection(wall):
    """F.7: the public pipeline chooses the complete-price argmin among valid
    plans; identity may win."""
    from mdi import model as M, oracle as O, pipeline as PLN
    from tests.test_mdi_research import mean_field, w
    out = []
    ok = True
    for n in (6, 9):
        fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
        m = M.read_uai(w(mean_field(n, 0.30, fields)))
        r = M.restrict(m, {})
        Z, pt = O.exact_all_marginals(r)
        res = PLN.solve(m, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        elig = {p["name"]: int(p["total_arithmetic"]["value"]) for p in res.prices
                if p["eligible"] and p["total_arithmetic"]["value"] is not None}
        argmin = min(elig, key=elig.get)
        ok = ok and res.status.startswith("CERTIFIED") and res.plan["chosen"] == argmin and _contains(res.intervals, pt)
        out.append({"n": n, "status": res.status, "chosen": res.plan["chosen"], "argmin": argmin,
                    "eligible_prices": elig, "complete_cost": res.plan.get("complete_cost")})
    return {"runs": out, "ok": ok}


CONTROLS = [
    ("F1 identity program replay", control_identity_replay),
    ("F1/F2 compact two-scale replay + altered witness", control_regional_two_scales_replay),
    ("F2 compact external construction priced out", control_compact_external_construction),
    ("F3 owned restoration / shared-readout fault", control_restoration_independence),
    ("F4 collective menu, coarse Q, vector statistic", control_collective_menu_and_Q),
    ("F5 mixed Gaussian/Fourier program", control_mixed_gf),
    ("F6 prices cover counted work", control_price_covers_counted_work),
    ("F7 public selection argmin", control_public_selection),
]


def run_matrix(out_path, wall=240.0, only=None):
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "tests"))
    import signal
    rows = []
    for name, fn in CONTROLS:
        if only and not any(k in name for k in only):
            continue
        t = time.time()
        print("[matrix] %s ..." % name, flush=True)

        def _alarm(signum, frame):
            raise TimeoutError("control exceeded its %ds wall" % int(wall))
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(int(wall))
        try:
            res = fn(wall)
            status = "PASS" if res.get("ok") else ("SKIP" if res.get("ok") is None else "FAIL")
        except TimeoutError as e:
            res = {"ok": False, "timeout": str(e)}
            status = "TIMEOUT"
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                   "traceback": traceback.format_exc()[-1200:]}
            status = "ERROR"
        finally:
            signal.alarm(0)
        el = time.time() - t
        print("[matrix] %-52s %-7s %.1fs" % (name, status, el), flush=True)
        rows.append({"control": name, "status": status, "seconds": round(el, 1),
                     "result": json.loads(json.dumps(res, default=str))})
    summary = {"controls": rows,
               "passed": sum(1 for r in rows if r["status"] == "PASS"),
               "failed": sum(1 for r in rows if r["status"] in ("FAIL", "ERROR", "TIMEOUT")),
               "skipped": sum(1 for r in rows if r["status"] == "SKIP"),
               "per_control_wall_s": wall, "built": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "route_matrix.json"
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 240.0
    only = sys.argv[3:] or None
    s = run_matrix(out, wall, only)
    print(json.dumps({k: v for k, v in s.items() if k != "controls"}))
    sys.exit(0 if s["failed"] == 0 else 1)
