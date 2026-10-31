"""The integrated acceptance matrix (spec §12, revision r18).

Every control enters through the public entry point (`pipeline.solve`) and,
where a persisted program is exercised, through the ONE loaded-object
boundary (`mdi.replay`: a fresh interpreter, or in-process with the same
validator, admission rule, dispatcher and limits). Nothing here runs an
executor or checker outside the shared budget.

Every applicable row checks: the exact query key set, truth containment,
positive denominators, published widths, resource stops (none) and the fresh
replay status. Offering, admission, execution and verification are reported
separately per branch. Measurements stay measurements (a missing one is
reported as missing and cannot pass a coverage assertion); proven bounds and
forecasts are separate fields. A remaining gap is labelled explicitly.

    python -m mdi.matrix OUT.json [per_control_wall_s] [only ...]
"""
from __future__ import annotations
import sys, os, json, time, math, tempfile, subprocess, traceback, copy
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EPS = Fr(1, 100)


# ------------------------------------------------------------------ helpers

def _pair(J):
    e = math.exp(J)
    D = 10 ** 6
    return [Fr(round(e * D), D), Fr(round(D / e), D), Fr(round(D / e), D), Fr(round(e * D), D)]


def _dec(x):
    x = Fr(x)
    k = 0
    while (x * 10 ** k).denominator != 1:
        k += 1
    n = (x * 10 ** k).numerator
    return str(n) if k == 0 else "%d.%0*d" % (n // 10 ** k, k, n % 10 ** k)


def _write_uai(m):
    lines = ["MARKOV", str(m.nvars), " ".join(str(c) for c in m.card), str(len(m.factors))]
    for f in m.factors:
        lines.append("%d %s" % (len(f.scope), " ".join(str(v) for v in f.scope)))
    for f in m.factors:
        lines.append(str(len(f.table)))
        lines.append(" ".join(_dec(x) for x in f.table))
    fh = tempfile.NamedTemporaryFile("w", suffix=".uai", delete=False)
    fh.write("\n".join(lines) + "\n")
    fh.close()
    return fh.name


def _contains(pub, pt):
    return all(Fr(pub[v][s][0]) <= pt[v][s] <= Fr(pub[v][s][1])
               for v in pub for s in range(len(pub[v])))


def _contains_rep(rep, pt):
    """Truth containment on the requested rows; an OBSERVED coordinate (which
    replay publishes as an exact point mass) must be exactly that point mass."""
    iv = rep.get("intervals") or {}
    obs = {int(k): int(v) for k, v in (rep.get("observed") or {}).items()}
    if not iv:
        return False
    for v, rows in iv.items():
        v = int(v)
        if v in obs:
            if any((Fr(lo), Fr(hi)) != ((Fr(1), Fr(1)) if s == obs[v] else (Fr(0), Fr(0)))
                   for s, (lo, hi) in enumerate(rows)):
                return False
            continue
        if v not in pt:
            return False
        if any(not (Fr(lo) <= pt[v][s] <= Fr(hi)) for s, (lo, hi) in enumerate(rows)):
            return False
    return True


def _keys_rep(rep, want):
    """Exact query key set: the requested variables plus the observed
    coordinates the public API returns, nothing else."""
    iv = rep.get("intervals") or {}
    obs = {int(k) for k in (rep.get("observed") or {})}
    return sorted(int(v) for v in iv) == sorted(set(int(v) for v in want) | obs)


def _width(pub):
    return max((Fr(hi) - Fr(lo) for v in pub for lo, hi in pub[v]), default=Fr(0))


def _resource(bud):
    """Resource obligations: a budget report exists, no whole-arm stop (wall,
    RSS, shared counter) occurred, every meter is within its limit. A PHASE
    allowance stop (the 30 s construction / local-check allowance) is reported
    separately: it ends discovery and preserves completed plans; it is not a
    resource violation of the arm."""
    bud = bud or {}
    used = bud.get("used") or {}
    lim = bud.get("limits") or {}
    within = all(used.get(k, 0) <= lim[k] for k in lim)
    stops = list(bud.get("stops") or [])
    arm_stops = [x for x in stops if not str(x.get("kind", "")).startswith("phase:")]
    phase_stops = [x for x in stops if str(x.get("kind", "")).startswith("phase:")]
    return {"present": bool(bud), "stops": arm_stops, "phase_stops": phase_stops, "used": used,
            "limits": lim, "phases": bud.get("phases"), "phase_used_s": bud.get("phase_used_s"),
            "ok": bool(bud) and not arm_stops and within}


def _row_ok(rep, pt, queries, need_ledger=True, eps=None, evidence=None):
    """The predicates every applicable replay row must carry, each re-derived
    by the matrix itself: the expected key set and cardinalities come from the
    record's REQUEST object (and must agree with the control's own requested
    set), every endpoint string is parsed as an exact rational, 0 <= lo <= hi
    <= 1 holds, the width is RECOMPUTED from the endpoints (the reported
    max_width is checked against it, never trusted), truth containment is the
    exact rational test against the independent enumeration, observed
    coordinates are exact point masses. Empty rows, missing keys, a wrong
    cardinality, a disguised [0, 1] row (its recomputed width is 1) and a
    missing budget all FAIL."""
    # the obligations come from the INDEPENDENTLY RETAINED request of the
    # control (its requested width `eps`, its evidence, its requested set and
    # its own exact truth), never from the report: the report's request and
    # observed map must AGREE with them
    eps = Fr(eps) if eps is not None else EPS
    evidence = {int(k): int(v) for k, v in (evidence or {}).items()}
    ck = rep.get("checker") or {}
    pd = ck.get("positive_denominators")
    req = rep.get("request") or {}
    iv = rep.get("intervals") or {}
    obs_rep = {int(k): int(v) for k, v in (rep.get("observed") or {}).items()}
    obs = evidence
    req_q = sorted(int(v) for v in (req.get("queries") or []))
    want_q = sorted(int(v) for v in queries)
    expect_keys = sorted(set(want_q) | set(obs))
    got_keys = sorted(int(v) for v in iv)
    req_width_ok = bool(req) and Fr(req.get("width", "0") or 0) == eps
    req_obs_ok = {int(k): int(v) for k, v in (req.get("observed") or {}).items()} == obs and obs_rep == obs
    exact_keys = bool(req) and req_q == want_q and got_keys == expect_keys and bool(got_keys) and req_obs_ok
    cards_ok = bool(iv)
    parsed = {}
    endpoints_ok = True
    for v, rows in iv.items():
        v = int(v)
        if not rows:
            cards_ok = False
            continue
        # a requested variable's cardinality comes from the request; an observed
        # coordinate's from the model cardinalities the replay publishes
        if v in req_q:
            want_card = int((req.get("card") or {}).get(str(v), 0))
        elif v in obs and rep.get("model_card") is not None and v < len(rep["model_card"]):
            want_card = int(rep["model_card"][v])
        else:
            want_card = None
        if want_card is None or len(rows) != want_card:
            cards_ok = False
        prow = []
        for lo, hi in rows:
            try:
                lo, hi = Fr(lo), Fr(hi)
            except (ValueError, TypeError, ZeroDivisionError):
                endpoints_ok = False
                continue
            if not (0 <= lo <= hi <= 1):
                endpoints_ok = False
            prow.append((lo, hi))
        parsed[v] = prow
    recomputed = max((hi - lo for rows in parsed.values() for lo, hi in rows), default=None)
    reported = Fr(rep["max_width"]) if rep.get("max_width") not in (None, "") else None
    width_ok = (recomputed is not None and recomputed <= eps and reported is not None and reported == recomputed
                and req_width_ok)
    truth = bool(parsed) and cards_ok
    if truth:
        for v, rows in parsed.items():
            if v in obs:
                if any((lo, hi) != ((Fr(1), Fr(1)) if s == obs[v] else (Fr(0), Fr(0))) for s, (lo, hi) in enumerate(rows)):
                    truth = False
                continue
            if v not in pt or len(pt[v]) != len(rows) or any(not (lo <= pt[v][s] <= hi) for s, (lo, hi) in enumerate(rows)):
                truth = False
    res = _resource(rep.get("budget"))
    return {"replay": rep["status"], "exact_keys": exact_keys, "cards": cards_ok, "endpoints_valid": endpoints_ok,
            "request_width": str(eps), "request_width_matches_report": req_width_ok,
            "evidence_matches_report": req_obs_ok,
            "truth": truth, "positive_denominators": pd,
            "width": (str(recomputed) if recomputed is not None else None), "width_reported": rep.get("max_width"),
            "width_ok": width_ok, "resources": res, "ledger": rep.get("ledger"),
            "ok": (rep["status"] == "REPLAY_VERIFIED" and exact_keys and cards_ok and endpoints_ok and truth
                   and pd is True and width_ok and res["ok"] and (rep.get("ledger") is not None or not need_ledger))}


def _solve(m, wall, evidence=None, queries=None):
    from mdi import pipeline as PLN, factors as FX
    d = tempfile.mkdtemp()
    FX.reset_expansion_counter()
    t = time.time()
    res = PLN.solve(m, evidence or {}, queries=queries, wall_s=wall, cap_bytes=1 << 30, plan_dir=d)
    el = time.time() - t
    return res, d, el, dict(FX.EXPANSIONS)


def _plan(res, d, name):
    p = next(x for x in res.prices if x["name"] == name)
    return os.path.join(d, p["identity"] + ".plan.json")


def _price(res, name):
    return next(x for x in res.prices if x["name"] == name)


def _replay_fresh(mp, plan, timeout, evid="-", eps=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE
    cmd = [sys.executable, "-m", "mdi.replay", mp, evid, plan]
    if eps is not None:
        cmd += ["--eps", str(eps)]
    out = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout, env=env)
    if not out.stdout.strip():
        raise RuntimeError("replay produced no output: %s" % out.stderr[-600:])
    return json.loads(out.stdout)


def _replay_here(mp, plan, wrap=None, evid="-"):
    from mdi import replay as RP
    return RP.replay(mp, evid, plan, wrap=wrap)


def _offering(res):
    off = [p["name"] for p in res.prices]
    adm = [p["name"] for p in res.prices if p["eligible"]]
    typed = {}
    for x in res.rejected:
        t = x.get("typed") or ("duplicate" if "duplicate" in x["reason"] else "other")
        typed[t] = typed.get(t, 0) + 1
    ids = [p["identity"] for p in res.prices]
    return {"offered": off, "admitted": adm, "refused_by_price": [p["name"] for p in res.prices if not p["eligible"]],
            "typed_refusals": typed, "distinct_identities": len(set(ids)), "records": len(ids),
            "unique_ok": len(ids) == len(set(ids))}


# EVERY Fraction operation the engines can perform is counted: the four
# arithmetic operations, power, negation, absolute value and the comparisons
ALL_FRACTION_OPS = ("__mul__", "__rmul__", "__add__", "__radd__", "__truediv__", "__rtruediv__",
                    "__sub__", "__rsub__", "__pow__", "__neg__", "__abs__", "__lt__", "__le__",
                    "__gt__", "__ge__", "__eq__", "__floordiv__", "__mod__")


def _measure_ops():
    import fractions
    counts = {}
    saved = {nm: getattr(fractions.Fraction, nm) for nm in ALL_FRACTION_OPS}
    box = {"n": 0}

    def mk(fn):
        def w_(self, *a):
            box["n"] += 1
            return fn(self, *a)
        return w_

    def wrap(stage, fn):
        for nm, f in saved.items():
            setattr(fractions.Fraction, nm, mk(f))
        box["n"] = 0
        try:
            return fn()
        finally:
            for nm, f in saved.items():
                setattr(fractions.Fraction, nm, f)
            counts[stage] = box["n"]
    return wrap, counts


# ----------------------------------------------------------------- fixtures

def _two_block_signed():
    from mdi import model as M
    n = 6
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(v, 20)], origin=v) for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            J = 0.25 if (i < 3 and j < 3) else (-0.20 if (i >= 3 and j >= 3) else 0.05)
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _two_equal_blocks(J=0.25, nb=2, bs=3):
    from mdi import model as M
    n = nb * bs
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(5 + 5 * (v % 2), 100)], origin=v)
            for v in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if i // bs == j // bs:
                facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=100 + 10 * i + j))
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _chain3(a=-0.05, c=-0.05, fields=(0.1, 0.2, 0.3)):
    """The FIXED chain for mixed acceptance: couplings (-0.05, -0.05)."""
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(int(fields[v] * 100), 100)], origin=v)
            for v in range(3)]
    for (i, j), J in (((0, 1), a), ((1, 2), c)):
        facs.append(M.Factor(scope=(i, j), card=(2, 2), table=_pair(J), origin=10 + i * 3 + j))
    return M.Model(nvars=3, card=[2] * 3, factors=facs).validate()


def _f3_bipartite(k=7):
    """The unchanged 14-variable F3 synthetic model (k=7); smaller k gives the
    same family with a discovery that completes inside the allowance."""
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 7, 20)], origin=v)
            for v in range(2 * k)]
    for i in range(k):
        for j in range(k):
            facs.append(M.Factor(scope=(i, k + j), card=(2, 2),
                                 table=_pair(0.05 * (1 + ((i + j) % 3)) / 2), origin=100 + 10 * i + j))
    return M.Model(nvars=2 * k, card=[2] * (2 * k), factors=facs).validate()


def _deletion_chain(n=8):
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1, 10 ** 7) if v == 5 else Fr(1 + v % 2)],
                     origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + i)
             for i in range(n - 1)]
    return M.Model(nvars=n, card=[2] * n, factors=facs).validate()


def _categorical_pairwise():
    from mdi import model as M
    facs = [M.Factor(scope=(v,), card=(3,), table=[Fr(1), Fr(1) + Fr(v + 1, 10), Fr(1) - Fr(v + 1, 20)],
                     origin=v) for v in range(4)]
    for i in range(4):
        for j in range(i + 1, 4):
            tab = [Fr(1) + Fr(((a + b) % 3) - 1, 10) * Fr(1, 1 + ((i + j) % 2))
                   for a in range(3) for b in range(3)]
            facs.append(M.Factor(scope=(i, j), card=(3, 3), table=tab, origin=10 + 4 * i + j))
    return M.Model(nvars=4, card=[3] * 4, factors=facs).validate()


def _mean_field_path(n, J):
    from tests.test_mdi_research import mean_field, w
    fields = [0.1 * (k + 1) * (1 if k % 2 == 0 else -1) for k in range(n)]
    return w(mean_field(n, J, fields))


# ---------------------------------------------------------------- controls

def control_identity_and_f3_fallback(wall):
    """R1: the identity program governs the public run and a fresh process;
    the public pipeline COMPLETES on the unchanged 14-variable F3 model where
    integration and most statistic candidates are refused by TYPED price
    refusals and the identity-only control verifies all 28 coordinates."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import TINY, w
    mp = w(TINY)
    m = M.read_uai(mp)
    res, d, el, _ = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    rep = _replay_fresh(mp, _plan(res, d, "identity"), wall)
    q = sorted(M.restrict(m, {}).free)
    row = _row_ok(rep, pt, q, need_ledger=False)
    row["ok"] = (rep["status"] == "REPLAY_VERIFIED" and row["exact_keys"] and row["truth"]
                 and row["width_ok"] and row["resources"]["ok"])
    out = {"tiny": {"pipeline": res.status, "chosen": res.plan.get("chosen"), "offering": _offering(res),
                    "truth": _contains(res.intervals, pt), "width": str(_width(res.intervals)),
                    "resources": _resource(res.budget), "identity_replay_row": row}}
    ok = (res.status.startswith("CERTIFIED") and _contains(res.intervals, pt) and _width(res.intervals) <= EPS
          and _resource(res.budget)["ok"] and row["ok"])
    m3 = _f3_bipartite()
    mp3 = _write_uai(m3)
    res3, d3, el3, exp3 = _solve(M.read_uai(mp3), wall)
    Z, pt3 = O.exact_all_marginals(M.restrict(m3, {}))
    offs = _offering(res3)
    ncoord = sum(len(r) for r in res3.intervals.values())
    out["f3_14_variables"] = {"pipeline": res3.status, "chosen": res3.plan.get("chosen"), "seconds": round(el3, 1),
                              "coordinates_published": ncoord,
                              "coordinates_checked": res3.checker.get("coordinates_checked"),
                              "truth": _contains(res3.intervals, pt3), "width": str(_width(res3.intervals)),
                              "offering": offs, "resources": _resource(res3.budget),
                              "measured_expansions": exp3, "complete_cost": res3.plan.get("complete_cost")}
    ok = ok and (res3.status.startswith("CERTIFIED") and ncoord == 28 and _contains(res3.intervals, pt3)
                 and _width(res3.intervals) <= EPS and _resource(res3.budget)["ok"]
                 and offs["typed_refusals"].get("PRICE_REFUSAL", 0) >= 1 and offs["unique_ok"]
                 and res3.checker.get("coordinates_checked") == 28)
    out["ok"] = bool(ok)
    return out


def control_valid_proof_record(wall):
    """R2: a verified publication follows from a VALID proof record: the
    supplied checker/radius fixtures through the public fresh-process replay
    (clean encloses all six exact probabilities; the negative allowance is
    refused as an invalid proof budget); ledger faults on the same record are
    refused with the clean record preserved; an inverted row is refused
    before containment; the shared residual-label fault rejects while the
    clean record verifies; zero-evidence terminals carry the original-model
    proof (a true claim is proved, a false one is not)."""
    from mdi import model as M, oracle as O, collective_route as CR, pipeline as PLN
    from mdi import program_check as PC, program as PG
    out = {}
    oks = []
    cdir = os.path.join(HERE, "checker")
    mp = os.path.join(cdir, "radius_model.uai")
    m = M.read_uai(mp)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    clean = _replay_fresh(mp, os.path.join(cdir, "radius_clean.plan.json"), wall)
    neg = _replay_fresh(mp, os.path.join(cdir, "radius_negative.plan.json"), wall)
    crow = _row_ok(clean, pt, q)
    crow["six_probabilities_enclosed"] = _contains_rep(clean, pt) and \
        sum(len(r) for r in clean.get("intervals", {}).values()) == 6
    crow["ok"] = crow["ok"] and crow["six_probabilities_enclosed"]
    out["radius_clean"] = crow
    out["radius_negative"] = {"status": neg["status"], "reason": str(neg.get("reason"))[:160],
                              "ok": neg["status"] == "REPLAY_REFUSED" and "NEGATIVE" in str(neg.get("reason"))}
    oks += [crow["ok"], out["radius_negative"]["ok"]]
    base = json.load(open(os.path.join(cdir, "radius_clean.plan.json")))
    d = tempfile.mkdtemp()
    muts = {}
    b1 = copy.deepcopy(base)
    b1["allocations"]["regional_level1"] = str(Fr(b1["allocations"]["regional_level1"]) / 1000)
    b1["program"]["scales"][0]["t_level"] = b1["allocations"]["regional_level1"]
    muts["saved_below_verified_component"] = b1
    b2 = copy.deepcopy(base)
    b2["allocations"]["gaussian_quadrature"] = "1/100000"
    muts["non_applicable_component_nonzero"] = b2
    b3 = copy.deepcopy(base)
    b3["allocations"]["regional_level1"] = "1/10"
    b3["program"]["scales"][0]["t_level"] = "1/10"
    muts["saved_allowance_above_frozen_cap"] = b3
    for label, bad in muts.items():
        p2 = os.path.join(d, label + ".plan.json")
        json.dump(bad, open(p2, "w"))
        r2 = _replay_fresh(mp, p2, wall)
        txt = str(r2.get("reason")) + " ".join(r2.get("failures") or [])
        okm = r2["status"] in ("REPLAY_REFUSED", "REPLAY_REJECTED") and any(
            k in txt for k in ("proof budget", "allocation", "allowance", "radius", "witness", "alpha", "rho"))
        out[label] = {"status": r2["status"], "reason": str(r2.get("reason"))[:160],
                      "failure": (r2.get("failures") or [""])[0][:120], "ok": okm}
        oks.append(okm)
    prog = PG.validate_program(json.loads(json.dumps(base["program"])))
    r = M.restrict(m, {})
    inv = {v: [(Fr(6, 10), Fr(4, 10)) if s == 0 else (Fr(4, 10), Fr(6, 10)) for s in range(2)] for v in q}
    okI, fI, mI = PC.verify_program(r, set(q), prog, inv, EPS)
    out["inverted_row_before_containment"] = {
        "ok": (not okI) and any("INVERTED" in x for x in fI) and bool((mI or {}).get("schema_rejected")),
        "failure": (fI or [""])[0][:100]}
    oks.append(out["inverted_row_before_containment"]["ok"])
    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, _, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    q4 = sorted(M.restrict(m4, {}).free)
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])
    plan4 = _plan(res4, d4, stat)
    clean4 = _replay_here(mp4, plan4)
    orig = CR._residual_marked

    def faulty(marked, res, can, kept):
        rmk = orig(marked, res, can, kept)
        vs = sorted(rmk.queries())
        if len(vs) >= 2:
            a, b = vs[0], vs[1]
            rmk.owner[a], rmk.owner[b] = rmk.owner[b], rmk.owner[a]
        return rmk
    CR._residual_marked = faulty
    try:
        bad4 = _replay_here(mp4, plan4)
    finally:
        CR._residual_marked = orig
    row4 = _row_ok(clean4, pt4, q4)
    txt4 = str(bad4.get("reason")) + " ".join(bad4.get("failures") or [])
    out["residual_label_fault"] = {"clean": row4, "fault": bad4["status"], "fault_reason": txt4[:160],
                                   "ok": row4["ok"] and bad4["status"] == "REPLAY_REJECTED"
                                         and "residual binding" in txt4}
    oks.append(out["residual_label_fault"]["ok"])
    z = M.Model(nvars=2, card=[2, 2], factors=[
        M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=0),
        M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=1)]).validate()
    rz = PLN.solve(z, {0: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    fake = PLN.zero_evidence_proof(z, {}, M.restrict(z, {}), named=1)
    out["zero_evidence_terminal"] = {"true_claim": rz.status, "witness": (rz.checker or {}).get("witness_factor"),
                                     "false_claim_proved": fake.get("proved"),
                                     "false_claim_reason": fake["reason"][:120],
                                     "ok": rz.status == "ZERO_EVIDENCE_PROVED"
                                           and (rz.checker or {}).get("witness_factor") == 0
                                           and fake.get("proved") is False}
    oks.append(out["zero_evidence_terminal"]["ok"])
    out["ok"] = all(oks)
    return out


def control_frozen_integration(wall):
    """R3: the frozen GF1-GF3 algorithm on the fixed chain (-0.05, -0.05),
    public-preprocessed, discovered mixed representation. Chapter 05 integers
    (15 positive nodes, 25 signed frequencies, 13 representatives; 5 processed
    / 10 omitted in review) are DIAGNOSTICS; acceptance is exact truth, width,
    identical retained keys and the shared limits. Pure signs at rank two
    execute and verify; saved-grid mutations refuse binding; price, producer
    and checker agree on the representatives."""
    from mdi import model as M, oracle as O, collective as CO
    m = _chain3()
    mp = _write_uai(m)
    res, d, el, _ = _solve(M.read_uai(mp), wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    out = {"fixture": "chain J=(-0.05,-0.05) fields (0.1,0.2,0.3)", "pipeline": res.status,
           "chosen": res.plan.get("chosen"), "offering": _offering(res), "proof_rule": CO.GF_RULE,
           "proof_version": CO.GF_RULE_VERSION}
    oks = [res.status.startswith("CERTIFIED") and _contains(res.intervals, pt) and _resource(res.budget)["ok"]]
    rows = {}
    for p in [p for p in res.prices if p["name"].startswith("mixed:")]:
        prog = json.load(open(_plan(res, d, p["name"])))["program"]["collective"]
        rep = _replay_fresh(mp, _plan(res, d, p["name"]), wall)
        row = _row_ok(rep, pt, q)
        ex = rep.get("executor") or {}
        ck = (rep.get("checker") or {}).get("collective") or {}
        rx = ex.get("retained_positive_node_indices")
        ret_exec = sorted(int(x) for x in str(rx).strip("[]").split(",") if x.strip()) if rx is not None else []
        ret_chk = sorted(ck.get("retained_positive_node_indices") or [])
        row.update({"grids": [{k: g[k] for k in g if k in ("sign", "tol", "m", "h", "nodes", "signed_frequencies",
                                                            "representatives", "K", "J", "t", "T", "b")}
                              for g in prog["grids"]],
                    "tolerances": prog["deltas"], "gf3_eta_recorded": prog["quadrature_tv"],
                    "positive_nodes": ex.get("positive_nodes"), "processed": ex.get("processed_positive_nodes"),
                    "omitted": ex.get("omitted_positive_nodes"), "conjugate_pairs": ex.get("conjugate_pairs"),
                    "checker_processed": ck.get("processed"), "checker_pairs": ck.get("conjugate_pairs"),
                    "retained_keys_identical": ret_exec == ret_chk and bool(ret_chk),
                    "executor_transcendental_calls": ex.get("transcendental_calls"),
                    "checker_transcendental_calls": ck.get("transcendental_calls"),
                    "priced_pairs": p["counters"]["negative_conjugate_pairs_per_positive_node"]["value"],
                    "eligible": p["eligible"]})
        row["ok"] = (row["ok"] and row["retained_keys_identical"] and p["eligible"]
                     and str(row["priced_pairs"]) == str(row["conjugate_pairs"]) == str(row["checker_pairs"])
                     and ex.get("transcendental_calls") is not None and ck.get("transcendental_calls") is not None)
        rows[p["name"]] = row
        oks.append(row["ok"])
    out["mixed_programs"] = rows
    lr = rows.get("mixed:lowrank_combined") or {}
    out["chapter05_diagnostics"] = {
        "expected": {"positive_nodes": 15, "signed_frequencies": 25, "conjugate_representatives": 13,
                     "review_processed": 5, "review_omitted": 10},
        "observed": {"positive_nodes": lr.get("positive_nodes"), "processed": lr.get("processed"),
                     "omitted": lr.get("omitted"), "conjugate_pairs": lr.get("conjugate_pairs"),
                     "grids": lr.get("grids")},
        "note": "diagnostics, not acceptance conditions"}
    try:
        lat = CO.gf_lattice(Fr(48818, 100000), Fr(328056, 1000000), Fr(1, 4000))
        latn = CO.fourier_lattice(Fr(90903, 100000), Fr(700684, 1000000), Fr(2, 1000))
        out["archived_derivative_grid"] = {
            "positive_nodes": lat["nodes"], "negative_nodes": latn["nodes"],
            "scope": "the SUPERSEDED tail+discretization lattices of r16/r17 (not the Chapter 05 grids): their "
                     "769 x 257 tensor exceeded the shared 1,000,000-entry meter, was refused by price and "
                     "stopped at 1,000,001 entries (ROUTE_MATRIX_r17.json F6). The identities and error "
                     "estimates were never at fault; the construction was. Preserved, not used."}
    except Exception as e:
        out["archived_derivative_grid"] = {"error": str(e)[:120]}
    pq = _price(res, "mixed:lowrank_combined")["counters"] if lr else {}
    out["full_grid_price_vs_adaptive_stop"] = {
        "priced_full_grid_contractions": (pq.get("quadrature_nodes") or {}).get("value"),
        "measured_processed_positive_nodes": lr.get("processed"), "measured_omitted": lr.get("omitted"),
        "stopping_tolerance": "the production numerical allowance eps - 2 radius - reserve in execution, "
                              "verification (identical retained keys) and this control",
        "note": "a conservative full-grid price bound is distinguished from the measured adaptive stop; "
                "no pre-node pruning is claimed"}
    pure = {}
    for J, ev in ((0.25, "gaussian"), (-0.15, "fourier")):
        m2 = _two_equal_blocks(J, 2, 3 if J > 0 else 2)
        mp2 = _write_uai(m2)
        res2, d2, _, _ = _solve(M.read_uai(mp2), wall)
        Z, pt2 = O.exact_all_marginals(M.restrict(m2, {}))
        q2 = sorted(M.restrict(m2, {}).free)
        name = next((p["name"] for p in res2.prices if p["name"] == ev + ":block_combined"), None)
        if name is None:
            pure[ev] = {"ok": False, "reason": "no rank-2 %s record offered" % ev, "offering": _offering(res2)}
            oks.append(False)
            continue
        prog2 = json.load(open(_plan(res2, d2, name)))["program"]["collective"]
        rep2 = _replay_fresh(mp2, _plan(res2, d2, name), wall)
        row2 = _row_ok(rep2, pt2, q2)
        row2.update({"signs": prog2["candidate"]["signs"], "grid_nodes": [g["nodes"] for g in prog2["grids"]],
                     "eligible": _price(res2, name)["eligible"], "offering": _offering(res2)})
        row2["ok"] = row2["ok"] and len(prog2["candidate"]["signs"]) == 2 and len(set(prog2["candidate"]["signs"])) == 1
        pure[ev] = row2
        oks.append(row2["ok"])
    out["pure_sign_rank2"] = pure
    mpf = _mean_field_path(4, -0.22)
    mf = M.read_uai(mpf)
    resf, df, _, _ = _solve(mf, wall)
    fname = next(p["name"] for p in resf.prices if p["name"].startswith("fourier:") and p["eligible"])
    base = json.load(open(_plan(resf, df, fname)))
    g = base["program"]["collective"]["grids"][0]
    muts = {}
    if g["m"] > 1:
        m1 = g["m"] - 1
        muts["coarser_spacing"] = dict(g, m=m1, h=str(Fr(1, m1)), J=m1 * g["T"], nodes=2 * m1 * g["T"] + 1,
                                       signed_frequencies=2 * m1 * g["T"] + 1, representatives=m1 * g["T"] + 1)
    mm = g["m"] + 1
    muts["finer_spacing"] = dict(g, m=mm, h=str(Fr(1, mm)), J=mm * g["T"], nodes=2 * mm * g["T"] + 1,
                                 signed_frequencies=2 * mm * g["T"] + 1, representatives=mm * g["T"] + 1)
    muts["shorter_reach"] = dict(g, J=g["J"] - 1, nodes=2 * (g["J"] - 1) + 1,
                                 signed_frequencies=2 * (g["J"] - 1) + 1, representatives=g["J"])
    gm = {}
    for label, gg in muts.items():
        bad = copy.deepcopy(base)
        bad["program"]["collective"]["grids"][0] = gg
        p2 = os.path.join(df, "grid_%s.plan.json" % label)
        json.dump(bad, open(p2, "w"))
        r2 = _replay_fresh(mpf, p2, wall)
        gm[label] = {"status": r2["status"], "reason": str(r2.get("reason"))[:140],
                     "ok": r2["status"] in ("REPLAY_REFUSED", "REPLAY_REJECTED")}
        oks.append(gm[label]["ok"])
    out["saved_grid_mutations"] = gm
    pf = _price(resf, fname)
    repf = _replay_fresh(mpf, _plan(resf, df, fname), wall)
    exf = repf.get("executor") or {}
    ckf = (repf.get("checker") or {}).get("collective") or {}
    pp = str(pf["counters"]["negative_conjugate_pairs_per_positive_node"]["value"])
    out["representative_symmetry"] = {"priced_pairs": pp, "producer_pairs": exf.get("conjugate_pairs"),
                                      "checker_pairs": ckf.get("conjugate_pairs"),
                                      "grid_representatives": g["representatives"],
                                      "grid_signed_frequencies": g["signed_frequencies"],
                                      "ok": pp == str(exf.get("conjugate_pairs")) == str(ckf.get("conjugate_pairs"))
                                            == str(g["representatives"])}
    oks.append(out["representative_symmetry"]["ok"])
    out["ok"] = all(oks)
    return out


def control_independent_representation_and_readout(wall):
    """R4: compose, shared-readout, statistic state-count and Fourier payload
    faults REJECT through the same boundary that VERIFIES their clean
    records; categorical / hard-zero / subset with evidence, and a nonzero
    DELETION program, verify and replay."""
    from mdi import model as M, oracle as O, factors as FX, marked as MK, collective_jt as CJ
    from tests.test_mdi_research import ring_of_blocks, w
    out = {}
    oks = []

    def pair_(label, mp, plan, pt, q, target, attr, faulty, obligation="does NOT contain"):
        clean = _replay_here(mp, plan)
        orig = getattr(target, attr)
        setattr(target, attr, faulty(orig))
        try:
            bad = _replay_here(mp, plan)
        finally:
            setattr(target, attr, orig)
        fail0 = (bad.get("failures") or [""])[0]
        row = _row_ok(clean, pt, q)
        ok = row["ok"] and bad["status"] == "REPLAY_REJECTED" and obligation in fail0
        out[label] = {"clean": row, "fault": bad["status"], "fault_obligation": fail0[:110], "ok": ok}
        oks.append(ok)

    mp = w(ring_of_blocks()[0])
    m = M.read_uai(mp)
    res, d, _, _ = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    l1 = next(p["name"] for p in res.prices if p["name"].startswith("regional:") and "@64" in p["name"]
              and not p["name"].endswith(":L2"))
    plan = _plan(res, d, l1)

    def compose_fault(orig):
        def faulty(self, region_of, reps, bpos, ncell):
            v = orig(self, region_of, reps, bpos, ncell)
            i = min(v.offsets)
            if len(v.offsets[i]) >= 2:
                v.offsets[i] = list(reversed(v.offsets[i]))
            return FX.ProjectedFactor(scope=v.scope, card=v.card, offsets=v.offsets, base=v.base,
                                      origin=v.origin, scale=v.scale)
        return faulty
    pair_("compact_compose_fault", mp, plan, pt, q, FX.ProjectedFactor, "compose", compose_fault)

    def readout_fault(orig):
        def faulty(marked, Z, counts):
            o = orig(marked, Z, counts)
            return {v: [(lo * Fr(9, 5), hi * Fr(9, 5)) if s == 0 else (lo / 5, hi / 5)
                        for s, (lo, hi) in enumerate(rws)] for v, rws in o.items()}
        return faulty
    pair_("shared_readout_fault", mp, plan, pt, q, MK, "read_original", readout_fault)
    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, _, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    q4 = sorted(M.restrict(m4, {}).free)
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])

    def stat_fault(orig):
        def faulty(marked, cand, Q, ctx, *a, **k):
            Zr, counts, meta = orig(marked, cand, Q, ctx, *a, **k)
            counts = {v: [(lo * 3, hi * 3) if s == 0 else (lo, hi) for s, (lo, hi) in enumerate(rows)]
                      for v, rows in counts.items()}
            return Zr, counts, meta
        return faulty
    pair_("statistic_state_count_fault", mp4, _plan(res4, d4, stat), pt4, q4, CJ, "statistic_evaluate", stat_fault)
    mpf = _mean_field_path(4, -0.22)
    mf = M.read_uai(mpf)
    resf, df, _, _ = _solve(mf, wall)
    Z, ptf = O.exact_all_marginals(M.restrict(mf, {}))
    qf = sorted(M.restrict(mf, {}).free)
    four = next(p["name"] for p in resf.prices if p["name"].startswith("fourier:") and p["eligible"])

    def payload_fault(orig):
        def faulty(marked, marg, others, alg):
            o = orig(marked, marg, others, alg)
            for v in o:
                o[v][0] = alg.mul(o[v][0], (Fr(3), Fr(3), Fr(0), Fr(0)) if alg.name == "complex" else (Fr(3), Fr(3)))
            return o
        return faulty
    pair_("fourier_payload_fault", mpf, _plan(resf, df, four), ptf, qf, CJ, "_own_mass_contribution", payload_fault)
    facs = [M.Factor(scope=(0, 1), card=(2, 3), table=[Fr(1), Fr(2), Fr(0), Fr(3), Fr(1), Fr(5)], origin=0),
            M.Factor(scope=(1, 2, 3), card=(3, 2, 2),
                     table=[Fr(x) for x in (1, 2, 1, 0, 2, 1, 1, 3, 1, 1, 2, Fr(1, 10 ** 9))], origin=1),
            M.Factor(scope=(4, 5), card=(2, 3), table=[Fr(2), Fr(1), Fr(1), Fr(1), Fr(0), Fr(4)], origin=2)]
    mc = M.Model(nvars=6, card=[2, 3, 2, 2, 2, 3], factors=facs).validate()
    mpc = _write_uai(mc)
    evp = mpc + ".evid"
    open(evp, "w").write("1 3 1\n")
    resc, dc, _, _ = _solve(M.read_uai(mpc), wall, evidence={3: 1}, queries={0, 1, 5})
    Z, ptc = O.exact_all_marginals(M.restrict(mc, {3: 1}))
    reg = next((p["name"] for p in resc.prices if p["name"].startswith("regional:") and p["eligible"]), None)
    cat = {"pipeline": resc.status, "chosen": resc.plan.get("chosen"), "response_keys": sorted(resc.intervals),
           "truth": _contains({v: resc.intervals[v] for v in (0, 1, 5)}, ptc), "resources": _resource(resc.budget)}
    okc = resc.status.startswith("CERTIFIED") and cat["truth"] and sorted(resc.intervals) == [0, 1, 3, 5] \
        and cat["resources"]["ok"]
    if reg:
        rc = _replay_fresh(mpc, _plan(resc, dc, reg), wall, evid=evp)
        rowc = _row_ok(rc, ptc, [0, 1, 5], evidence={3: 1})
        cat["regional_replay"] = rowc
        okc = okc and rowc["ok"]
    cat["ok"] = okc
    out["categorical_zero_subset_evidence"] = cat
    oks.append(okc)
    md = _deletion_chain()
    mpd = _write_uai(md)
    resd, dd, _, _ = _solve(M.read_uai(mpd), wall)
    Z, ptd = O.exact_all_marginals(M.restrict(md, {}))
    qd = sorted(M.restrict(md, {}).free)
    delrec = None
    for p in resd.prices:
        if p["name"].startswith("regional:"):
            prog = json.load(open(_plan(resd, dd, p["name"])))["program"]
            if sum(len(rg["deleted"]) for sc in prog["scales"] for rg in sc["regions"]) > 0:
                delrec = p["name"]
                break
    if delrec is None:
        out["nonzero_deletion"] = {"ok": False, "reason": "no regional record with a deleted state was offered",
                                   "offering": _offering(resd)}
        oks.append(False)
    else:
        rd = _replay_fresh(mpd, _plan(resd, dd, delrec), wall)
        rowd = _row_ok(rd, ptd, qd)
        rowd.update({"program": delrec, "research": rd.get("research"),
                     "eligible": _price(resd, delrec)["eligible"], "offering": _offering(resd)})
        rowd["ok"] = rowd["ok"] and (rd.get("research") or {}).get("deleted_states", 0) >= 1 \
            and Fr(((rd.get("ledger") or {}).get("verified") or {}).get("deletion_level1", "0")) > 0
        out["nonzero_deletion"] = rowd
        oks.append(rowd["ok"])
    out["ok"] = all(oks)
    return out


def control_portfolio_and_identity(wall):
    """R5: the 12-versus-8 control (every certified candidate persisted with a
    distinct executable identity despite shared generator names), the
    feature-sign rounding tie, block repairs, masks carried into the residual
    actually built and priced, the categorical menu, coarse Q."""
    from mdi import model as M, oracle as O, modes as MO, collective_route as CR, marked as MK, arith as A
    from tests.test_mdi_research import ring_of_blocks, w
    out = {}
    oks = []
    m = _two_block_signed()
    mp = _write_uai(m)
    res, d, _, _ = _solve(M.read_uai(mp), wall)
    q = sorted(M.restrict(m, {}).free)
    offs = _offering(res)
    r0 = M.restrict(m, {})
    adm = CR.admit(MK.Marked.from_restricted(r0, set(q)), A.Ctx(96))
    shared = {}
    for p in res.prices:
        shared.setdefault(p["name"].split("#")[0], []).append(p["identity"])
    cands, info = MO.propose_modes(list(r0.free), r0.factors, r0.card)
    bm = info.get("block_matrix")
    out["twelve_versus_eight"] = {"admitted_by_recognizer": len(adm), "records_persisted": offs["records"],
                                  "distinct_identities": offs["distinct_identities"],
                                  "generator_names_shared_by_distinct_records":
                                      {k: len(v) for k, v in shared.items() if len(v) > 1},
                                  "duplicates_rejected": offs["typed_refusals"].get("duplicate", 0),
                                  "block_matrix": bm, "offering": offs}
    n_coll = sum(1 for n in offs["offered"] if n.split(":")[0] in ("statistic", "gaussian", "fourier", "mixed"))
    out["twelve_versus_eight"]["collective_records_persisted"] = n_coll
    ok12 = (n_coll == len(adm) and offs["unique_ok"] and bm is not None
            and all(abs(bm[i][i]) > 0 for i in range(len(bm))) and any(len(v) > 1 for v in shared.values()))
    oks.append(ok12)
    Q = 4
    f = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(-3, 8), Fr(3, 8)]}
    cA = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[f], kind="lowrank_rank1")
    cB = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[{v: [-x for x in row] for v, row in f.items()}],
                          kind="lowrank_rank1")
    base = {"evaluator": "statistic", "Q": Q, "deltas": None, "kept_factors": [], "dropped_pairs": []}
    exe = {"order": [0, 1], "precision": 96, "arithmetic": {"mode": "E"}, "checker": {"strategy": "dense_min_fill"}}
    idA, kA = CR.canonical_identity(dict(base, candidate=cA), (), executable=exe)
    idB, kB = CR.canonical_identity(dict(base, candidate=cB), (), executable=exe)
    # per-mode tuple: [sign, strength, canonical features, rounded integer statistic, grid]
    featA, featB = [m[:3] for m in kA["modes"]], [m[:3] for m in kB["modes"]]
    statA, statB = [m[3] for m in kA["modes"]], [m[3] for m in kB["modes"]]
    out["feature_sign_rounding_tie"] = {"Q": Q, "canonical_features_equal": featA == featB,
                                        "integer_statistics_A": statA, "integer_statistics_B": statB,
                                        "statistics_distinct": statA != statB,
                                        "identities_distinct": idA != idB,
                                        "ok": featA == featB and statA != statB and idA != idB}
    # a genuine permutation of WHOLE modes (strength stays with its statistic) deduplicates;
    # swapping the strengths between two modes with different statistics does not
    g2 = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(1, 4), Fr(-1, 4)]}
    cP = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 2), Fr(1, 3)], features=[f, g2], kind="lowrank_combined")
    cPp = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[g2, f], kind="lowrank_combined")
    cSw = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[f, g2], kind="lowrank_combined")
    idP, _ = CR.canonical_identity(dict(base, candidate=cP), (), executable=exe)
    idPp, _ = CR.canonical_identity(dict(base, candidate=cPp), (), executable=exe)
    idSw, _ = CR.canonical_identity(dict(base, candidate=cSw), (), executable=exe)
    out["mode_permutation"] = {"permuted_modes_same_identity": idP == idPp,
                               "swapped_strengths_distinct_identity": idP != idSw,
                               "ok": idP == idPp and idP != idSw}
    oks.append(out["mode_permutation"]["ok"])
    oks.append(out["feature_sign_rounding_tie"]["ok"])
    masked_rows = []
    for c, rmk in adm:
        cd = c["candidate"]
        if cd.masked:
            kept = {tuple(fct.scope) for fct in rmk.factors if len(fct.scope) == 2}
            masked_rows.append({"kind": cd.kind, "masked_pairs": len(cd.masked),
                                "all_retained_in_built_residual": all(tuple(pr) in kept for pr in cd.masked)})
    out["masks_in_built_residual"] = {"rows": masked_rows[:6],
                                      "ok": bool(masked_rows) and all(r["all_retained_in_built_residual"] for r in masked_rows)}
    oks.append(out["masks_in_built_residual"]["ok"])
    m2 = _two_equal_blocks()
    r2 = M.restrict(m2, {})
    c2, i2 = MO.propose_modes(list(r2.free), r2.factors, r2.card)
    bc = [c for c in c2 if c.kind == "block_combined"]
    out["two_equal_blocks"] = {"block_matrix": i2.get("block_matrix"), "block_combined_signs": [c.signs for c in bc],
                               "ok": bool(bc) and all(len(c.signs) == 2 for c in bc)}
    oks.append(out["two_equal_blocks"]["ok"])
    mc = _categorical_pairwise()
    mpc = _write_uai(mc)
    resc, dc, _, _ = _solve(M.read_uai(mpc), wall)
    Z, ptc = O.exact_all_marginals(M.restrict(mc, {}))
    qc = sorted(M.restrict(mc, {}).free)
    catn = sorted({p["name"] for p in resc.prices if "categorical" in p["name"]})
    cstat = next((k for k in catn if k.startswith("statistic:categorical_rank1") and _price(resc, k)["eligible"]), None)
    cat = {"records": catn, "pipeline": resc.status, "offering": _offering(resc)}
    okc = any("categorical_rank1" in k for k in catn) and any("categorical_combined" in k for k in catn) \
        and any("_forest" in k for k in catn) and resc.status.startswith("CERTIFIED")
    if cstat:
        rcs = _replay_fresh(mpc, _plan(resc, dc, cstat), wall)
        cat["statistic_categorical_replay"] = _row_ok(rcs, ptc, qc)
        okc = okc and cat["statistic_categorical_replay"]["ok"]
    cat["ok"] = okc
    out["categorical_menu"] = cat
    oks.append(okc)
    mr = w(ring_of_blocks()[0])
    resr, dr, _, _ = _solve(M.read_uai(mr), wall)
    comp = [p for p in resr.prices if p["name"].startswith("composed:") and ":statistic:" in p["name"]]
    qs = {p["name"]: json.load(open(_plan(resr, dr, p["name"])))["program"]["collective"]["Q"] for p in comp}
    out["composed_ring_coarse_Q"] = {"Q_by_record": qs, "ok": bool(qs) and all(v < (1 << 16) for v in qs.values())}
    oks.append(out["composed_ring_coarse_Q"]["ok"])
    out["ok"] = all(oks)
    return out


def control_work_and_memory(wall):
    """R6: priced bounds cover the COUNTED operations, measured metered
    entries, measured transcendental calls of both engines, measured retained
    node data and precomputed phases, and liveness, on statistic (default
    order), Gaussian (small storage), Fourier, mixed, regional and composed
    programs; measurement / proven bound / forecast are separate fields;
    stage elapsed times are complete; a missing measurement cannot pass
    coverage; a cost-changing reordered plan is refused at binding."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import ring_of_blocks, w
    rows = []
    all_ok = True

    def coverage(c, counts, rep, name):
        """The coverage predicate on MEASURED values; None never passes."""
        ex = rep.get("executor") or {}
        ck = (rep.get("checker") or {}).get("collective") or {}
        # the arithmetic bound PLUS the named comparison / sign-test bound, per
        # engine, against EVERY counted Fraction operation of that engine
        pp = sum(int(c[k]["value"]) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops")) \
            + int((c.get("producer_comparison_ops") or {}).get("value") or 0)
        pc = int(c["checker_ops"]["value"]) + int((c.get("checker_comparison_ops") or {}).get("value") or 0)
        bud = rep.get("budget") or {}
        used = bud["used"].get("local_mass_entries", 0) if "used" in bud else None
        fc = (c.get("metered_entries_forecast") or {}).get("value")
        live_m = ex.get("peak_live_entries")
        live_p = int(c["peak_live_message_entries"]["value"]) + int(c["final_largest_bag"]["value"])
        tr_fp = (c.get("transcendental_producer_forecast") or {}).get("value")
        tr_fc = (c.get("transcendental_checker_forecast") or {}).get("value")
        tr_e, tr_c = ex.get("transcendental_calls"), ck.get("transcendental_calls")
        ret_f = (c.get("retained_positive_node_entries") or {}).get("value")
        ret_m = ex.get("retained_positive_node_entries")
        ph_f = (c.get("precomputed_phase_entries") or {}).get("value")
        ph_m = ex.get("precomputed_phase_entries")
        st = rep.get("stages") or {}
        st_tr = ((rep.get("complete_cost") or {}).get("measured") or {}).get("stage_transcendental_calls") or {}
        full_exec = (st_tr.get("execute") or {}).get("total")
        full_check = (st_tr.get("check") or {}).get("total")
        measured = {"producer_ops": counts.get("execute"), "checker_ops": counts.get("check"),
                    "counted_operations": "every Fraction operation: arithmetic, comparison, negation, absolute value, power",
                    # SCOPES stated: the transcendental FORECASTS cover the evaluator's
                    # enclosures only; the full-stage counts (setup, rebuild, grids, fit
                    # proof included) are MEASURED and reported, not forecast
                    "forecast_scope": "evaluator enclosures (producer_transcendental / checker_transcendental)",
                    "full_stage_transcendental_execute": full_exec, "full_stage_transcendental_check": full_check,
                    "unforecast_setup_calls_execute": (None if (full_exec is None or tr_e is None) else int(full_exec) - int(tr_e)),
                    "unforecast_setup_calls_check": (None if (full_check is None or tr_c is None) else int(full_check) - int(tr_c)),
                    "metered_entries": used, "peak_live": live_m, "producer_transcendental": tr_e,
                    "checker_transcendental": tr_c, "retained_positive_node_entries": ret_m,
                    "precomputed_phase_entries": ph_m, "stage_seconds": st}
        bounds = {"producer_ops": pp, "checker_ops": pc, "metered_entries": fc, "peak_live": live_p,
                  "event_staging_entries": (c.get("event_staging_entries") or {}).get("value")}
        forecasts = {"transcendental_producer": tr_fp, "transcendental_checker": tr_fc,
                     "retained_positive_node_entries": ret_f, "precomputed_phase_entries": ph_f}
        kind = name.split(":")[0]
        is_gf = kind in ("gaussian", "fourier", "mixed") or any(":%s:" % k in name for k in ("gaussian", "fourier", "mixed"))
        is_stat = kind == "statistic" or ":statistic:" in name
        cov = (measured["producer_ops"] is not None and measured["checker_ops"] is not None
               and pp >= measured["producer_ops"] and pc >= measured["checker_ops"]
               and fc is not None and used is not None and int(fc) >= int(used)
               and live_m is not None and int(live_m) <= live_p
               and st.get("execute_s") is not None and st.get("check_s") is not None)
        if is_gf:
            # matching scopes: evaluator forecast vs evaluator measurement; the
            # full-stage measurement must be at least the evaluator's (consistency)
            cov = cov and None not in (tr_e, tr_c, tr_fp, tr_fc, ret_m, ret_f, ph_m, ph_f, full_exec, full_check) \
                and int(tr_fp) >= int(tr_e) and int(tr_fc) >= int(tr_c) \
                and int(full_exec) >= int(tr_e) and int(full_check) >= int(tr_c) \
                and int(ret_f) >= int(ret_m) and int(ph_f) >= int(ph_m)
        elif is_stat:
            cov = cov and None not in (tr_e, tr_c, tr_fp, tr_fc) \
                and int(tr_fp) >= int(tr_e) and int(tr_fc) >= int(tr_c)
        return bool(cov), measured, bounds, forecasts

    def check(label, mp, res, d, name, pt, q):
        wrap, counts = _measure_ops()
        rep = _replay_here(mp, _plan(res, d, name), wrap=wrap)
        p = _price(res, name)
        cov, measured, bounds, forecasts = coverage(p["counters"], counts, rep, name)
        row = {"control": label, "program": name, "row": _row_ok(rep, pt, q), "measured": measured,
               "proven_bounds": bounds, "forecasts": dict(forecasts, bytes_producer=p.get("bytes_producer"),
                                                          bytes_checker=p.get("bytes_checker")),
               "covers": cov}
        row["ok"] = row["row"]["ok"] and cov
        rows.append(row)
        # the missing-measurement rule, demonstrated on THIS row: strip one
        # measurement and the predicate must fail
        stripped = dict(rep)
        stripped["executor"] = dict(rep.get("executor") or {})
        stripped["executor"]["peak_live_entries"] = None
        cov2, _m, _b, _f = coverage(p["counters"], counts, stripped, name)
        row["missing_measurement_fails_coverage"] = (not cov2)
        row["ok"] = row["ok"] and not cov2
        return row["ok"]

    mp4 = _mean_field_path(4, 0.30)
    m4 = M.read_uai(mp4)
    res4, d4, _, _ = _solve(m4, wall)
    Z, pt4 = O.exact_all_marginals(M.restrict(m4, {}))
    q4 = sorted(M.restrict(m4, {}).free)
    stat = next(p["name"] for p in res4.prices if p["name"].startswith("statistic:") and p["eligible"])
    all_ok &= check("mean-field-4 statistic (default order)", mp4, res4, d4, stat, pt4, q4)
    gau = next(p["name"] for p in res4.prices if p["name"].startswith("gaussian:") and p["eligible"])
    all_ok &= check("mean-field-4 gaussian (small storage)", mp4, res4, d4, gau, pt4, q4)
    mpf = _mean_field_path(4, -0.22)
    mf = M.read_uai(mpf)
    resf, df, _, _ = _solve(mf, wall)
    Z, ptf = O.exact_all_marginals(M.restrict(mf, {}))
    qf = sorted(M.restrict(mf, {}).free)
    four = next(p["name"] for p in resf.prices if p["name"].startswith("fourier:") and p["eligible"])
    all_ok &= check("mean-field-4 fourier", mpf, resf, df, four, ptf, qf)
    mc = _chain3()
    mpc = _write_uai(mc)
    resc, dc, _, _ = _solve(M.read_uai(mpc), wall)
    Z, ptc = O.exact_all_marginals(M.restrict(mc, {}))
    qc = sorted(M.restrict(mc, {}).free)
    if any(p["name"] == "mixed:lowrank_combined" and p["eligible"] for p in resc.prices):
        all_ok &= check("chain mixed", mpc, resc, dc, "mixed:lowrank_combined", ptc, qc)
    else:
        all_ok = False
        rows.append({"control": "chain mixed", "ok": False, "reason": "mixed:lowrank_combined not eligible"})
    mpr = w(ring_of_blocks()[0])
    mr = M.read_uai(mpr)
    resr, dr, _, _ = _solve(mr, wall)
    Z, ptr = O.exact_all_marginals(M.restrict(mr, {}))
    qr = sorted(M.restrict(mr, {}).free)
    l1 = next(p["name"] for p in resr.prices if p["name"].startswith("regional:") and "@64" in p["name"]
              and not p["name"].endswith(":L2"))
    all_ok &= check("ring regional L1", mpr, resr, dr, l1, ptr, qr)
    comp = next((p["name"] for p in resr.prices if p["name"].startswith("composed:") and ":statistic:" in p["name"]
                 and p["eligible"]), None)
    if comp:
        all_ok &= check("ring composed statistic", mpr, resr, dr, comp, ptr, qr)
    saved = {"refused": 0, "cost_identical_bound": 0, "first_refusal": None}
    for p in resr.prices:
        if not (p["name"].startswith("regional:") or p["name"].startswith("composed:")):
            continue
        b0 = json.load(open(_plan(resr, dr, p["name"])))
        o = list(b0["program"]["order"])
        for k in range(1, len(o)):
            bad = copy.deepcopy(b0)
            bad["program"]["order"] = o[k:] + o[:k]
            p2 = os.path.join(dr, "reordered.plan.json")
            json.dump(bad, open(p2, "w"))
            rep = _replay_here(mpr, p2)
            # r20: the request object binds the order too, so a rotated program
            # is refused at LOAD (request order differs) before saved-order repricing
            if rep["status"] == "REPLAY_REFUSED" and ("SAVED order" in str(rep.get("reason"))
                                                       or "request order differs" in str(rep.get("reason"))):
                saved["refused"] += 1
                if saved["first_refusal"] is None:
                    saved["first_refusal"] = {"program": p["name"], "rotation": k, "reason": str(rep.get("reason"))[:160]}
            elif rep["status"] == "REPLAY_VERIFIED":
                saved["cost_identical_bound"] += 1
        if saved["refused"]:
            break
    saved["ok"] = saved["refused"] >= 1
    all_ok &= saved["ok"]
    return {"rows": rows, "saved_order_witness": saved, "ok": bool(all_ok)}


def control_public_selection_and_admission(wall):
    """R7: one admission decision for pipeline and replay (byte forecasts,
    remaining shared counters, terminal handling); budget accounting starts
    before preprocessing (phases recorded) in both; the response schema is
    bound to the original request including observed coordinates; selection
    is the remaining-cost argmin and identity may win."""
    from mdi import model as M, oracle as O, replay as RP, pipeline as PLN
    out = []
    ok = True
    for n in (6, 9):
        mp = _mean_field_path(n, 0.30)
        m = M.read_uai(mp)
        Z, pt = O.exact_all_marginals(M.restrict(m, {}))
        res, d, el, _ = _solve(m, wall)
        elig = {p["name"]: int(p["total_arithmetic"]["value"]) for p in res.prices
                if p["eligible"] and p["total_arithmetic"]["value"] is not None}
        argmin = min(elig, key=elig.get)
        rs = _resource(res.budget)
        phases = rs.get("phases") or []
        row = {"n": n, "status": res.status, "chosen": res.plan["chosen"], "argmin": argmin,
               "offering": _offering(res), "phases": phases,
               "budget_before_preprocessing": bool(phases) and phases[0] == "parse" and "preprocess" in phases,
               "complete_cost": res.plan.get("complete_cost"), "truth": _contains(res.intervals, pt),
               "width": str(_width(res.intervals)), "resources": rs, "seconds": round(el, 2)}
        ok = ok and res.status.startswith("CERTIFIED") and res.plan["chosen"] == argmin and row["truth"] \
            and Fr(row["width"]) <= EPS and rs["ok"] and row["budget_before_preprocessing"] \
            and res.plan.get("complete_cost") is not None
        out.append(row)
    # an ineligible BOUND record (forecast metered entries above the shared cap)
    # exists on the 10-variable bipartite model, whose discovery completes
    # inside the construction allowance
    mp6 = _write_uai(_f3_bipartite(5))
    res6, d6, _, _ = _solve(M.read_uai(mp6), wall)
    inel = next((p for p in res6.prices if not p["eligible"]), None)
    adm = {"ineligible_record_present": inel is not None, "fixture": "bipartite 5+5 (F3 family, k=5)"}
    if inel:
        # the same cap the pipeline ran under (1 GiB in this matrix)
        rep = RP.replay(mp6, "-", os.path.join(d6, inel["identity"] + ".plan.json"), cap_bytes=1 << 30)
        adm.update({"name": inel["name"], "pipeline_reason": inel["ineligible_reason"][:120],
                    "replay": rep["status"], "replay_reason": str(rep.get("reason"))[:120],
                    "replay_phases": (rep.get("budget") or {}).get("phases"),
                    "same_decision": rep["status"] == "REPLAY_REFUSED"
                                     and inel["ineligible_reason"][:80] in str(rep.get("reason"))})
        ok = ok and adm["same_decision"] and bool(adm["replay_phases"]) and adm["replay_phases"][0] == "parse"
    else:
        ok = False
    mc = M.read_uai(_mean_field_path(4, 0.30))
    rc = PLN.solve(mc, {1: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    resp = {"status": rc.status, "keys": sorted(rc.intervals),
            "observed_row": [[str(a), str(b)] for a, b in rc.intervals.get(1, [])],
            "ok": rc.status.startswith("CERTIFIED") and sorted(rc.intervals) == [0, 1, 2, 3]
                  and rc.intervals[1] == [(Fr(0), Fr(0)), (Fr(1), Fr(1))]}
    ok = ok and resp["ok"]
    return {"runs": out, "replay_admission": adm, "response_schema": resp, "ok": bool(ok)}


CONTROLS = [
    ("R1 identity program and the F3 public fallback", control_identity_and_f3_fallback),
    ("R2 verified publication from a valid proof record", control_valid_proof_record),
    ("R3 frozen GF1-GF3 integration on the fixed chain", control_frozen_integration),
    ("R4 independent representation and readout; deletion", control_independent_representation_and_readout),
    ("R5 portfolio, executable identity, masks, categorical, Q", control_portfolio_and_identity),
    ("R6 work and memory claims reviewable", control_work_and_memory),
    ("R7 one admission, budget before preprocessing, response schema", control_public_selection_and_admission),
]


def run_matrix(out_path, wall=600.0, only=None):
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
            if res.get("ok") is None:
                status = "SKIP"
            elif res.get("ok") and res.get("blocked"):
                status = "BLOCKED"
            elif res.get("ok"):
                status = "PASS"
            else:
                status = "FAIL"
        except TimeoutError as e:
            res = {"ok": False, "timeout": str(e)}
            status = "TIMEOUT"
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e),
                   "traceback": traceback.format_exc()[-1500:]}
            status = "ERROR"
        finally:
            signal.alarm(0)
        el = time.time() - t
        print("[matrix] %-66s %-7s %.1fs" % (name, status, el), flush=True)
        rows.append({"control": name, "status": status, "seconds": round(el, 1),
                     "result": json.loads(json.dumps(res, default=str))})
    summary = {"controls": rows,
               "passed": sum(1 for r in rows if r["status"] == "PASS"),
               "blocked": sum(1 for r in rows if r["status"] == "BLOCKED"),
               "failed": sum(1 for r in rows if r["status"] in ("FAIL", "ERROR", "TIMEOUT")),
               "skipped": sum(1 for r in rows if r["status"] == "SKIP"),
               "per_control_wall_s": wall, "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "note": "every applicable row carries exact query keys, truth containment, positive denominators, "
                       "width, resource stops and the fresh replay status; measurements, proven bounds and "
                       "forecasts are separate fields; a missing measurement is reported as missing"}
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "route_matrix.json"
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    only = sys.argv[3:] or None
    s = run_matrix(out, wall, only)
    print(json.dumps({k: v for k, v in s.items() if k != "controls"}))
    sys.exit(0 if s["failed"] == 0 else 1)
