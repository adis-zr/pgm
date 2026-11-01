"""r20: ONE connected acceptance matrix for the whole numerical library.

Every row runs through the PUBLIC entry points (`pipeline.solve`,
`mdi.replay` in a fresh process, `arm.run_arm`, `planning.run_pass`) and
re-derives its own obligations: the expected key set and cardinalities come
from the record's REQUEST object, every endpoint string is parsed as an exact
rational, 0 <= lower <= upper <= 1, the width is RECOMPUTED from the
endpoints, truth containment is the exact rational test against the
independent enumeration; empty rows, missing keys and a disguised [0, 1] row
fail. Raw replay rows (intervals as endpoint strings, request, budget, stage
counts, ledger) are persisted with every row.

    python -m mdi.acceptance OUT.json [per-row wall seconds] [row filter ...]

Rows: P1 proof boundary on the original triangle; P2 proof boundary on the
original F6 chain (GF1-GF3); P3 pure-sign rank-2 Gaussian / Fourier; P4 the
statistic family (categorical, higher-arity / non-binary, hard zero,
disconnected); P5 regional both levels, deletion, composed; P6 saved-program
authority (strict witnesses, identity tuples, request object, collision,
schema); P7 execution / resource contract (pre-admission applicability,
shared meter, deadline, MPFR counts, priced work, invocation ledger); P8
lifecycle controls with an injected clock; P9 the independent truth predicate
itself. No external input is opened by any row.
"""
from __future__ import annotations
import sys, os, json, time, copy, tempfile, collections, math
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

from mdi import matrix as MX                                     # noqa: E402
from mdi.matrix import (EPS, _row_ok, _solve, _plan, _price, _replay_fresh, _replay_here, _write_uai,
                        _contains, _width, _resource, _measure_ops, _chain3, _two_equal_blocks,
                        _deletion_chain, _categorical_pairwise, _mean_field_path, _f3_bipartite)  # noqa: E402


def K_RESERVE():
    from mdi import config as K
    return K.PUBLICATION_RESERVE


def _raw(rep):
    """The persisted raw row: everything a reviewer needs, nothing derived."""
    keep = ("status", "pipeline_status", "kind", "name", "identity", "intervals", "requested", "observed",
            "request_width", "request", "model_card", "max_width", "radius", "reason", "failures", "ledger",
            "stages", "elapsed_s")
    out = {k: rep.get(k) for k in keep if k in rep}
    bud = rep.get("budget") or {}
    out["budget_used"] = bud.get("used")
    out["budget_stops"] = bud.get("stops")
    out["budget_phases"] = bud.get("phases")
    cc = rep.get("complete_cost") or {}
    out["measured"] = cc.get("measured")
    ex = rep.get("executor") or {}
    out["executor"] = {k: ex.get(k) for k in ("transcendental_calls", "transcendental_by_kind", "peak_live_entries",
                                               "positive_nodes", "processed_positive_nodes", "omitted_positive_nodes",
                                               "conjugate_pairs", "statistic_support", "ops") if k in ex}
    ck = rep.get("checker") or {}
    out["checker"] = {k: ck.get(k) for k in ("status", "trusted_base", "checker_derived", "positive_denominators",
                                              "coordinates_checked", "method") if k in ck}
    coll = ck.get("collective") if isinstance(ck.get("collective"), dict) else None
    if coll:
        out["checker"]["collective"] = {k: coll.get(k) for k in ("transcendental_calls", "transcendental_by_kind",
                                                                 "processed", "own_quadrature_tv", "method") if k in coll}
    return out


def _fault_pair(mp, plan, pt, q, target, attr, faulty, obligation_words):
    """Run the same saved file clean and under an injected SHARED fault; the
    fault must be REJECTED on a named obligation and the clean row must pass."""
    clean = _replay_here(mp, plan)
    orig = getattr(target, attr)
    setattr(target, attr, faulty(orig))
    try:
        bad = _replay_here(mp, plan)
    finally:
        setattr(target, attr, orig)
    txt = str(bad.get("reason")) + " " + " ".join(bad.get("failures") or [])
    row = _row_ok(clean, pt, q)
    ok = row["ok"] and bad["status"] == "REPLAY_REJECTED" and any(w in txt for w in obligation_words)
    return {"clean": row, "fault_status": bad["status"], "fault_obligation": txt[:200], "ok": ok,
            "raw": {"clean": _raw(clean), "fault": _raw(bad)}}


# ------------------------------------------------------------------ P1

def row_p1_triangle(wall):
    """P1: the exact original triangle. The checker's trusted base is the
    original factor bytes; the clean verifier record verifies all six exact
    probabilities in a fresh process; the SHARED initial-marker swap, the
    output residual swap and the in-place residual swap are each rejected on a
    named obligation; the checker reports what it derived itself."""
    from mdi import model as M, marked as MK, collective_route as CR, oracle as O, pipeline as PLN
    vdir = os.path.join(HERE, "verifier")
    mp = os.path.join(vdir, "r17_triangle.uai")
    tr = json.load(open(os.path.join(vdir, "r17_triangle_truth.json")))
    pt = {int(v): [Fr(x) for x in row] for v, row in tr.items()}
    q = sorted(pt)
    out, oks = {}, []
    for fn in ("r17_triangle_lowrank_combined.plan.json", "r17_triangle_block_combined.plan.json"):
        plan = os.path.join(vdir, fn)
        rep = _replay_fresh(mp, plan, wall)
        row = _row_ok(rep, pt, q)
        row["six_rows"] = sum(len(v) for v in (rep.get("intervals") or {}).values())
        row["trusted_base"] = (rep.get("checker") or {}).get("trusted_base")
        row["checker_derived"] = (rep.get("checker") or {}).get("checker_derived")
        row["ok"] = row["ok"] and row["six_rows"] == 6 and bool(row["trusted_base"]) and bool(row["checker_derived"])
        row["raw"] = _raw(rep)
        out[fn] = row
        oks.append(row["ok"])
    plan = os.path.join(vdir, "r17_triangle_lowrank_combined.plan.json")

    def swap_initial(orig):
        def swapped(r_, qq, *a, **k):
            mk = orig(r_, qq, *a, **k)
            for v in list(mk.queries()):
                if mk.orig_card[v] == 2:
                    mk.marks[(v, 0)], mk.marks[(v, 1)] = mk.marks[(v, 1)], mk.marks[(v, 0)]
            return mk
        return swapped
    out["shared_initial_marker_swap"] = _fault_pair(mp, plan, pt, q, MK.Marked, "from_restricted", swap_initial,
                                                    ("observable", "marker"))
    oks.append(out["shared_initial_marker_swap"]["ok"])

    def output_swap(orig):
        def f(marked, res, can, kept):
            rmk = orig(marked, res, can, kept)
            vs = sorted(rmk.queries())
            rmk.owner[vs[0]], rmk.owner[vs[1]] = rmk.owner[vs[1]], rmk.owner[vs[0]]
            return rmk
        return f

    def inplace_swap(orig):
        def f(marked, res, can, kept):
            vs = sorted(marked.queries())
            a = vs[0]
            marked.marks[(a, 0)], marked.marks[(a, 1)] = marked.marks[(a, 1)], marked.marks[(a, 0)]
            return orig(marked, res, can, kept)
        return f
    out["output_residual_swap"] = _fault_pair(mp, plan, pt, q, CR, "_residual_marked", output_swap, ("residual binding",))
    out["in_place_residual_swap"] = _fault_pair(mp, plan, pt, q, CR, "_residual_marked", inplace_swap,
                                                ("residual binding", "observable"))
    oks += [out["output_residual_swap"]["ok"], out["in_place_residual_swap"]["ok"]]
    # ---- the WORKING-INPUT ALIAS (r20 review, blocking finding): a fault confined
    # to producer execution rewrites the producer's working unary tables after
    # binding; the original input bytes and the saved program are unchanged
    from mdi import routes as RT, law as LAW
    import hashlib
    res_t, d_t, _, _ = _solve(M.read_uai(mp), wall)
    plan_t = _plan(res_t, d_t, "statistic:lowrank_combined")
    h_before = (hashlib.sha256(open(mp, "rb").read()).hexdigest(), hashlib.sha256(open(plan_t, "rb").read()).hexdigest())
    clean_t = _replay_here(mp, plan_t)
    orig_exec = RT.execute

    def producer_mutates_working_tables(prog, r, queries, **kw):
        for f in r.factors:
            if len(f.scope) == 1:
                for i in range(len(f.table)):
                    f.table[i] = Fr(1)
        return orig_exec(prog, r, queries, **kw)

    def producer_wrong_on_isolated_copy(prog, r, queries, **kw):
        r2 = copy.deepcopy(r)
        for f in r2.factors:
            if len(f.scope) == 1:
                for i in range(len(f.table)):
                    f.table[i] = Fr(1)
        return orig_exec(prog, r2, queries, **kw)

    def producer_mutates_frozen_law(prog, r, queries, **kw):
        r.model.factors[0].table[0] = Fr(9)          # must raise: the frozen law is immutable
        return orig_exec(prog, r, queries, **kw)

    def producer_replaces_canonical_tables(prog, r, queries, **kw):
        # the r21 review's fault: ordinary ATTRIBUTE replacement on the canonical
        # model reachable through the producer's Restricted, then a working
        # restriction derived from the changed model
        from mdi import preprocess as PRE
        for f in r.model.factors:
            if len(f.scope) == 1:
                f.table = tuple(Fr(1) for _ in f.table)
        r0 = M.restrict(r.model, r.evidence)
        simp = PRE.simplify(r0)
        return orig_exec(prog, M.Restricted(model=r.model, evidence=r.evidence, factors=simp.factors, free=list(simp.free),
                                            card=dict(simp.card), constant=r0.constant, impossible_factor=None), queries, **kw)

    def producer_replaces_model_factors(prog, r, queries, **kw):
        r.model.factors = tuple(f for f in r.model.factors if len(f.scope) != 1)
        return orig_exec(prog, r, queries, **kw)

    def producer_replaces_cards(prog, r, queries, **kw):
        r.model.card = tuple(3 for _ in r.model.card)
        return orig_exec(prog, r, queries, **kw)
    rows_alias = {}
    for label, fn in (("producer_mutates_its_working_tables", producer_mutates_working_tables),
                      ("same_wrong_calculation_on_isolated_copy", producer_wrong_on_isolated_copy),
                      ("producer_tries_to_mutate_frozen_law", producer_mutates_frozen_law),
                      ("producer_replaces_canonical_factor_tables", producer_replaces_canonical_tables),
                      ("producer_replaces_canonical_factor_list", producer_replaces_model_factors),
                      ("producer_replaces_canonical_cardinalities", producer_replaces_cards)):
        RT.execute = fn
        try:
            bad = _replay_here(mp, plan_t)
        finally:
            RT.execute = orig_exec
        txt = str(bad.get("reason")) + " " + " ".join(bad.get("failures") or [])
        misses = sum(1 for v, rws in (bad.get("intervals") or {}).items() for st, (lo, hi) in enumerate(rws)
                     if not (Fr(lo) <= pt[int(v)][st] <= Fr(hi)))
        rows_alias[label] = {"status": bad["status"], "obligation": txt[:200], "original_probabilities_excluded": misses,
                             "ok": bad["status"] == "REPLAY_REJECTED" and misses == 0
                                   and ("does NOT contain" in txt or "tuple" in txt or "read-only" in txt), "raw": _raw(bad)}
    h_after = (hashlib.sha256(open(mp, "rb").read()).hexdigest(), hashlib.sha256(open(plan_t, "rb").read()).hexdigest())
    rowc = _row_ok(clean_t, pt, q)
    rowc["raw"] = _raw(clean_t)
    after = _replay_here(mp, plan_t)             # the healthy pipeline still verifies after every fault
    out["working_input_alias"] = {"clean": rowc, "faults": rows_alias, "input_and_plan_hashes_unchanged": h_before == h_after,
                                  "clean_after_faults": after["status"],
                                  "checker_restriction_derived_separately": (clean_t.get("stages") or {}).get("checker_restriction_s") is not None,
                                  "authority_verified_before_check": (clean_t.get("stages") or {}).get("checker_authority_verify_s") is not None,
                                  "ok": rowc["ok"] and all(r["ok"] for r in rows_alias.values()) and h_before == h_after
                                        and after["status"] == "REPLAY_VERIFIED"
                                        and (clean_t.get("stages") or {}).get("checker_restriction_s") is not None
                                        and (clean_t.get("stages") or {}).get("checker_authority_verify_s") is not None}
    oks.append(out["working_input_alias"]["ok"])
    # ---- the RETAINED REQUEST governs after producer execution (r22 review): a
    # producer-only mutation of its evidence argument (pipeline.solve) and a
    # producer-only narrowing of its query set and working program (replay)
    from mdi import plantype as PT
    import mdi.registry as RG
    m2 = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(3), Fr(1), Fr(1), Fr(3)], origin=0)]).validate()
    ev2 = {0: 0}
    Z2, pt2 = O.exact_all_marginals(M.restrict(m2, ev2))
    clean2 = PLN.solve(m2, dict(ev2), queries={1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    orig_ex = PT._PIPELINE_EXECUTORS["identity"]

    def ev_fault(ctx):
        ctx["evidence"][0] = 1                      # the producer changes ITS evidence argument
        return orig_ex(ctx)
    PT._PIPELINE_EXECUTORS["identity"] = ev_fault
    setattr(RG, orig_ex.__name__, ev_fault)
    try:
        bad2 = PLN.solve(m2, dict(ev2), queries={1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        PT._PIPELINE_EXECUTORS["identity"] = orig_ex
        setattr(RG, orig_ex.__name__, orig_ex)
    truth2 = bool(clean2.intervals) and Fr(clean2.intervals[1][0][0]) <= Fr(3, 4) <= Fr(clean2.intervals[1][0][1]) \
        and clean2.intervals[0] == [(Fr(1), Fr(1)), (Fr(0), Fr(0))]
    out["evidence_alias_pipeline"] = {"clean": {"status": clean2.status, "x1_row": [[str(a), str(b)] for a, b in clean2.intervals.get(1, [])],
                                                "truth_3_4_enclosed": truth2},
                                      "producer_mutates_evidence_argument": {"status": bad2.status, "reason": str(bad2.reason)[:160],
                                                                             "published": bool(bad2.intervals)},
                                      "caller_evidence_unchanged": ev2 == {0: 0},
                                      "ok": clean2.status.startswith("CERTIFIED") and truth2 and not bad2.status.startswith("CERTIFIED")
                                            and not bad2.intervals and ev2 == {0: 0}}
    oks.append(out["evidence_alias_pipeline"]["ok"])
    orig_rt = RT.execute

    def q_fault(prog, r, queries, **kw):
        queries.intersection_update({1})            # the producer narrows ITS query set
        prog["queries"] = [1]                       # and ITS working program
        return orig_rt(prog, r, queries, **kw)
    RT.execute = q_fault
    try:
        badq = _replay_here(mp, plan_t)
    finally:
        RT.execute = orig_rt
    saved_req = json.load(open(plan_t))["request"]["queries"]
    out["query_alias_replay"] = {"saved_request_queries": saved_req, "status": badq["status"], "reason": str(badq.get("reason"))[:160],
                                 "published_keys": sorted(badq.get("intervals") or {}),
                                 "ok": badq["status"] == "REPLAY_REJECTED" and not badq.get("intervals") and saved_req == [0, 1, 2]
                                       and "requested variables" in str(badq.get("reason"))}
    oks.append(out["query_alias_replay"]["ok"])
    # the canonical types refuse every supported mutation path directly
    law_t = LAW.OriginalLaw.freeze(M.read_uai(mp), {}, set(q))
    fm = law_t.model
    refusals = {}
    for label, fn in (("factor.table = ...", lambda: setattr(fm.factors[0], "table", (Fr(9),) * len(fm.factors[0].table))),
                      ("factor.table[0] = ...", lambda: fm.factors[0].table.__setitem__(0, Fr(9))),
                      ("factor.origin = ...", lambda: setattr(fm.factors[0], "origin", 99)),
                      ("factor.scope = ...", lambda: setattr(fm.factors[0], "scope", (1,))),
                      ("del factor.table", lambda: delattr(fm.factors[0], "table")),
                      ("model.factors = ...", lambda: setattr(fm, "factors", ())),
                      ("model.factors[0] = ...", lambda: fm.factors.__setitem__(0, None)),
                      ("model.card = ...", lambda: setattr(fm, "card", (3,) * len(fm.card))),
                      ("law.model = ...", lambda: setattr(law_t, "model", None)),
                      ("law.evidence[0] = 1", lambda: law_t.evidence.__setitem__(0, 1)),
                      ("law.queries.add(9)", lambda: law_t.queries.add(9))):
        try:
            fn()
            refusals[label] = "MUTATED"
        except (TypeError, AttributeError) as e:
            refusals[label] = type(e).__name__
    out["canonical_types_read_only"] = {"refusals": refusals, "authority": law_t.verify_authority(),
                                        "ok": all(v != "MUTATED" for v in refusals.values()) and law_t.verify_authority() is None}
    oks.append(out["canonical_types_read_only"]["ok"])
    # ---- occurrence identities: the SAME Factor object listed twice, two separate
    # equal copies and their exact product are the same exact law and publish correctly
    f = M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)])
    u = M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)])
    m_twice = M.Model(nvars=2, card=[2, 2], factors=[u, f, f]).validate()
    m_copies = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)]),
                                                     M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)]),
                                                     M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)])]).validate()
    m_prod = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)]),
                                                   M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(4), Fr(1), Fr(1), Fr(9)])]).validate()
    Zp, ptp = O.exact_all_marginals(M.restrict(m_prod, {}))
    # tuple-table caller factors with default duplicate ids (the r21 safe-refusal edge),
    # and explicit distinct ids, must represent the SAME law as the list-table inputs
    ft = M.Factor(scope=(0, 1), card=(2, 2), table=(Fr(2), Fr(1), Fr(1), Fr(3)))
    m_tuple = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=(Fr(1), Fr(3))), ft, ft]).validate()
    m_ids = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)], origin=7),
                                                  M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=11),
                                                  M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=13)]).validate()
    rows_occ = {}
    for label, mm in (("same_object_twice", m_twice), ("two_equal_copies", m_copies), ("exact_product", m_prod),
                      ("tuple_tables_default_ids", m_tuple), ("explicit_distinct_ids", m_ids)):
        law = LAW.OriginalLaw.freeze(mm, {}, {0, 1})
        rr = PLN.solve(mm, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        rows_occ[label] = {"status": rr.status, "occurrence_ids": [x.origin for x in law.model.factors],
                           "truth_vs_exact_product": _contains(rr.intervals, ptp) if rr.intervals else False,
                           "caller_objects_untouched": (f.origin == -1 and isinstance(f.table, list)),
                           "law_hash": law.model_sha256[:16]}
    same_law = (rows_occ["same_object_twice"]["law_hash"] == rows_occ["two_equal_copies"]["law_hash"]
                == rows_occ["tuple_tables_default_ids"]["law_hash"])
    out["repeated_factor_occurrences"] = {"rows": rows_occ, "same_object_twice_equals_two_copies_equals_tuple_tables": same_law,
                                          "tuple_caller_untouched": isinstance(ft.table, tuple) and ft.origin == -1,
                                          "ok": same_law and all(r["status"].startswith("CERTIFIED") and r["truth_vs_exact_product"]
                                                                 and r["caller_objects_untouched"] for r in rows_occ.values())}
    oks.append(out["repeated_factor_occurrences"]["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P2

def row_p2_chain(wall):
    """P2: the exact original F6 chain (-0.05, -0.05). Clean: 15 positive
    nodes, 25 signed frequencies, 13 representatives, 5 processed, six
    probabilities within the width, fresh process. The SHARED gf2 constructor
    returning one frequency with consistent counters is rejected by the
    checker's own grid proof; the healthy constructor refuses the same saved
    file. A shared GF3 constructor fault (quarter transfer radius) is rejected
    by the checker's own GF3 inequality; a conservative (enlarged) saved GF3
    radius verifies. The verifier/ chain records and the load-time rejections
    are carried from the r19 gate unchanged."""
    from mdi import model as M, oracle as O, collective as CO, gates as G
    m = _chain3()
    mp = _write_uai(m)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    out, oks = {}, []
    res, d, _, _ = _solve(M.read_uai(mp), wall)
    plan = _plan(res, d, "mixed:lowrank_combined")
    rep = _replay_fresh(mp, plan, wall)
    row = _row_ok(rep, pt, q)
    ex = rep.get("executor") or {}
    ck = (rep.get("checker") or {}).get("collective") or {}
    prog = json.load(open(plan))["program"]["collective"]
    row.update({"positive_nodes": ex.get("positive_nodes"), "processed": ex.get("processed_positive_nodes"),
                "omitted": ex.get("omitted_positive_nodes"), "conjugate_pairs": ex.get("conjugate_pairs"),
                "checker_processed": ck.get("processed"), "nodes_from_loaded_grids": [g["nodes"] for g in prog["grids"]],
                "signed_frequencies": [g["signed_frequencies"] for g in prog["grids"]],
                "representatives": [g["representatives"] for g in prog["grids"]], "raw": _raw(rep)})
    row["ok"] = (row["ok"] and str(row["positive_nodes"]) == "15" and str(row["conjugate_pairs"]) == "13"
                 and str(row["processed"]) == "5" and ck.get("processed") == 5 and sorted(row["nodes_from_loaded_grids"]) == [15, 25])
    out["clean_chain"] = row
    oks.append(row["ok"])
    # shared gf2 one-frequency fault with CONSISTENT counters
    orig2 = CO.gf2_grid

    def one_freq(a, R, e):
        g = orig2(a, R, e)
        g.update(T=0, J=0, nodes=1, signed_frequencies=1, representatives=1)
        return g
    CO.gf2_grid = one_freq
    try:
        resf, df, _, _ = _solve(M.read_uai(mp), wall)
        planf = _plan(resf, df, "mixed:lowrank_combined")
        badf = _replay_here(mp, planf)
    finally:
        CO.gf2_grid = orig2
    healthy = _replay_here(mp, planf)
    txt = str(badf.get("reason")) + " " + " ".join(badf.get("failures") or [])
    out["shared_gf2_one_frequency_fault"] = {
        "under_fault": badf["status"], "obligation": txt[:200], "healthy_constructor_same_file": healthy["status"],
        "healthy_reason": (str(healthy.get("reason")) + " " + " ".join(healthy.get("failures") or []))[:200],
        "ok": badf["status"] == "REPLAY_REJECTED" and ("2t" in txt or "reach" in txt or "grid" in txt)
              and healthy["status"] != "REPLAY_VERIFIED",
        "raw": {"under_fault": _raw(badf), "healthy": _raw(healthy)}}
    oks.append(out["shared_gf2_one_frequency_fault"]["ok"])
    # shared GF3 constructor fault
    orig3 = CO.gf3_eta
    CO.gf3_eta = lambda ds: orig3(ds) / 4
    try:
        res3, d3, _, _ = _solve(M.read_uai(mp), wall)
        plan3 = _plan(res3, d3, "mixed:lowrank_combined")
        bad3 = _replay_here(mp, plan3)
    finally:
        CO.gf3_eta = orig3
    healthy3 = _replay_here(mp, plan3)
    txt3 = str(bad3.get("reason")) + " " + " ".join(bad3.get("failures") or [])
    out["shared_gf3_altered_bound_fault"] = {
        "under_fault": bad3["status"], "obligation": txt3[:200], "healthy_constructor_same_file": healthy3["status"],
        "ok": bad3["status"] == "REPLAY_REJECTED" and "GF3" in txt3 and healthy3["status"] != "REPLAY_VERIFIED",
        "raw": {"under_fault": _raw(bad3), "healthy": _raw(healthy3)}}
    oks.append(out["shared_gf3_altered_bound_fault"]["ok"])
    # conservative GF3 witness: the saved radius enlarged by 2 % (within the frozen cap), coherent counters
    base = json.load(open(plan))
    good = copy.deepcopy(base)
    coll = good["program"]["collective"]
    coll["quadrature_tv"] = str(Fr(coll["quadrature_tv"]) * Fr(51, 50))
    good["allocations"]["gaussian_quadrature"] = str(Fr(good["allocations"]["gaussian_quadrature"]) * Fr(51, 50))
    good = G._reprice_coherent(good, M.read_uai(mp), "mixed")
    pg = os.path.join(d, "gf3_conservative.plan.json")
    json.dump(good, open(pg, "w"))
    repg = _replay_fresh(mp, pg, wall)
    rowg = _row_ok(repg, pt, q)
    rowg["raw"] = _raw(repg)
    out["conservative_gf3_witness"] = rowg
    oks.append(rowg["ok"])
    # the r19 grid gate carried unchanged (verifier records, load rejections, tail fault)
    gb = G.gate_b_grids(wall)
    out["r19_grid_gate_unchanged"] = {"ok": gb["ok"], "load_rejections": gb.get("load_rejections"),
                                      "tail_fault": gb.get("tail_fault_coherent_counters"),
                                      "verifier_records": {k: v.get("ok") for k, v in (gb.get("verifier_records") or {}).items()}}
    oks.append(gb["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P3

def row_p3_pure_sign_rank2(wall):
    """P3: pure-sign rank-2 Gaussian (two equal positive blocks) and Fourier
    (two equal negative blocks) through the public pipeline and a fresh
    replay; the saved grids carry two modes of one sign."""
    from mdi import model as M, oracle as O
    out, oks = {}, []
    for J, fam in ((0.25, "gaussian"), (-0.20, "fourier")):
        m = _two_equal_blocks(J=J)
        mp = _write_uai(m)
        Z, pt = O.exact_all_marginals(M.restrict(m, {}))
        q = sorted(M.restrict(m, {}).free)
        res, d, _, _ = _solve(M.read_uai(mp), wall)
        rows = {}
        rank2 = None
        for p in res.prices:
            if not (p["name"].startswith(fam + ":") and p["eligible"]):
                continue
            prog = json.load(open(_plan(res, d, p["name"])))["program"]["collective"]
            if len(prog["grids"]) == 2 and rank2 is None:
                rank2 = p["name"]
            if p["name"] in (fam + ":constant_rows", rank2):
                rep = _replay_fresh(mp, _plan(res, d, p["name"]), wall)
                row = _row_ok(rep, pt, q)
                row["signs"] = [g["sign"] for g in prog["grids"]]
                row["rank"] = len(prog["grids"])
                row["raw"] = _raw(rep)
                rows[p["name"]] = row
        ok = (res.status.startswith("CERTIFIED") and rank2 is not None and all(r["ok"] for r in rows.values())
              and rows[rank2]["rank"] == 2 and len(set(rows[rank2]["signs"])) == 1
              and rows[rank2]["signs"][0] == (1 if fam == "gaussian" else -1))
        out[fam] = {"pipeline": res.status, "chosen": res.plan.get("chosen"), "rank2_program": rank2, "rows": rows, "ok": ok}
        oks.append(ok)
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P4

def row_p4_statistic_family(wall):
    """P4: the statistic family: categorical (3-state) pairwise; higher-arity
    with a non-binary variable through the public pipeline; the natural
    hard-zero control (a zero pair retained with its ownership; the
    impossible state published as exactly zero); a disconnected model."""
    from mdi import model as M, oracle as O
    out, oks = {}, []

    def run(label, m, want_prefix, evidence=None, queries=None):
        mp = _write_uai(m)
        ev = dict(evidence or {})
        evp = None
        if ev:
            evp = mp + ".evid"
            open(evp, "w").write("%d %s\n" % (len(ev), " ".join("%d %d" % (v, s) for v, s in sorted(ev.items()))))
        res, d, _, _ = _solve(M.read_uai(mp), wall, evidence=ev or None, queries=queries)
        Z, pt = O.exact_all_marginals(M.restrict(m, ev))
        q = sorted(queries) if queries else sorted(M.restrict(m, ev).free)
        row = {"pipeline": res.status, "chosen": res.plan.get("chosen"),
               "truth": _contains({v: res.intervals[v] for v in q if v in res.intervals}, pt) if res.intervals else False,
               "offering": [p["name"] for p in res.prices if p["eligible"]][:12]}
        names = [p["name"] for p in res.prices if p["name"].startswith(want_prefix) and p["eligible"]]
        row["programs"] = {}
        for nm in names[:2]:
            rep = _replay_fresh(mp, _plan(res, d, nm), wall, evid=(evp or "-"))
            rr = _row_ok(rep, pt, q, evidence=ev)
            rr["raw"] = _raw(rep)
            row["programs"][nm] = rr
        row["ok"] = res.status.startswith("CERTIFIED") and row["truth"] and bool(names) and all(r["ok"] for r in row["programs"].values())
        out[label] = row
        oks.append(row["ok"])
        return res, d, mp, pt, q

    run("categorical_pairwise_statistic", _categorical_pairwise(), "statistic:")
    # higher arity, non-binary: a 4-scope factor, cards 2 3 2 3; only the identity can own a 4-scope kernel
    txt = ("MARKOV\n4\n2 3 2 3\n4\n4 0 1 2 3\n2 1 3\n1 0\n1 2\n"
           "36\n" + " ".join(str(1 + (k % 7)) for k in range(36)) + "\n"
           "9\n1 2 3 4 5 6 7 8 9\n2\n1 2\n2\n3 1\n")
    from tests.test_mdi_research import w
    mh = M.read_uai(w(txt))
    run("higher_arity_nonbinary", mh, "identity")
    # natural hard zero: four binary variables, six positive pairs, pair [0,0,1,1] forcing X0 = 1
    facs = []
    for i in range(4):
        for j in range(i + 1, 4):
            facs.append(M.Factor(scope=(i, j), card=(2, 2), table=[Fr(3), Fr(2), Fr(2), Fr(3)], origin=len(facs)))
    facs.append(M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(0), Fr(0), Fr(1), Fr(1)], origin=len(facs)))
    mz = M.Model(nvars=4, card=[2] * 4, factors=facs).validate()
    resz, dz, mpz, ptz, qz = run("natural_hard_zero_statistic", mz, "statistic:")
    hz = out["natural_hard_zero_statistic"]
    hz["x0_state0_truth_is_zero"] = ptz[0][0] == 0
    hz["x0_state0_published"] = [str(x) for x in resz.intervals[0][0]] if resz.intervals else None
    hz["ok"] = hz["ok"] and ptz[0][0] == 0 and Fr(resz.intervals[0][0][0]) == 0
    oks[-1] = hz["ok"]
    # the hard zero is RETAINED in the residual the saved program rebuilds
    # (the zero-bearing pair is never gauge-transferred or dropped): read from
    # the saved record through the same reconstruction the executor uses
    from mdi import plantype as PT, collective_route as CR, marked as MK, arith as A, preprocess as PRE
    mz0 = M.read_uai(mpz)
    r00 = M.restrict(mz0, {})
    simp = PRE.simplify(r00)
    rz0 = M.Restricted(model=mz0, evidence={}, factors=simp.factors, free=list(simp.free), card=dict(simp.card),
                       constant=r00.constant, impossible_factor=None)
    for nm, rr in hz["programs"].items():
        rec = PT.PlanRecord.from_json(open(_plan(resz, dz, nm)).read())
        coll = rec.parsed_program["collective"]
        rmk, _r, _c = CR.rebuild_residual(MK.Marked.from_restricted(rz0, set(rec.parsed_program["queries"])), coll,
                                          A.Ctx(int(coll["precision"])))
        # exact preprocessing splits the separable pair [0,0,1,1] into the
        # unary [0,1] on X0 (identity recorded as split_pairs); the hard zero
        # must survive INTO the residual on variable 0, unary or pair, with
        # its ownership (never gauge-transferred or dropped)
        zero_facs = [(tuple(int(x) for x in f.scope), [str(x) for x in f.table], f.origin) for f in rmk.factors
                     if any(Fr(x) == 0 for x in f.table)]
        rr["zero_bearing_residual_factors"] = zero_facs
        rr["zero_retained_on_x0"] = any(0 in sc for sc, _t, _o in zero_facs)
        rr["preprocess_split_pairs"] = rec.preprocess_identity.get("split_pairs")
        hz["ok"] = hz["ok"] and rr["zero_retained_on_x0"]
    oks[-1] = hz["ok"]
    # disconnected: two components
    n = 6
    facs = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1 + v % 2)], origin=v) for v in range(n)]
    facs += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(3)], origin=100 + i)
             for i in range(n - 1) if i != n // 2 - 1]
    md = M.Model(nvars=n, card=[2] * n, factors=facs).validate()
    run("disconnected_statistic", md, "statistic:")
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P5

def row_p5_regional_deletion_composed(wall):
    """P5: the ring: regional level 1 and level 2, composed statistic and
    composed Gaussian, each through a fresh replay; the deletion chain's
    nonzero deletion program; keys and cards from the request."""
    from mdi import model as M, oracle as O
    from tests.test_mdi_research import ring_of_blocks, w
    out, oks = {}, []
    mp = w(ring_of_blocks()[0])
    m = M.read_uai(mp)
    res, d, _, _ = _solve(m, wall)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    picks = {"regional_L1": lambda n: n.startswith("regional:") and "@64" in n and not n.endswith(":L2"),
             "regional_L2": lambda n: n.startswith("regional:") and n.endswith(":L2"),
             "composed_statistic": lambda n: n.startswith("composed:") and ":statistic:" in n,
             "composed_gaussian": lambda n: n.startswith("composed:") and ":gaussian:" in n}
    led = res.plan.get("invocation_ledger") or {}
    out["selection"] = {"status": res.status, "chosen": res.plan.get("chosen"),
                        "admitted_during_discovery": led.get("candidates_admitted_during_discovery"),
                        "phase_timeouts": led.get("candidates_phase_timeout"),
                        "note": "selection follows the complete price under this invocation's budget; the identity may win"}
    # BRANCH CAPABILITY through the explicit fallback relation (matrix._ring_program):
    # a program admitted in this invocation, else one persisted on disk by it,
    # else the shipped fixture -- the source is recorded; whether the CURRENT
    # timed discovery reached each branch is a separate coverage diagnostic
    out["current_discovery_coverage"] = {}
    for label in picks:
        plan_path, nm, _pr, how = MX._ring_program(res, d, label)
        out["current_discovery_coverage"][label] = {"admitted_in_this_invocation": how.startswith("admitted"),
                                                    "persisted_in_this_invocation": "persisted on disk" in how, "source": how}
        if plan_path is None:
            out[label] = {"ok": False, "reason": how, "offering": [p["name"] for p in res.prices]}
            oks.append(False)
            continue
        rep = _replay_fresh(mp, plan_path, wall) if not plan_path.startswith(os.path.join(HERE, "verifier")) \
            else _replay_fresh(os.path.join(HERE, "verifier", "ring_model.uai"), plan_path, wall)
        pt_use, q_use = (pt, q)
        if plan_path.startswith(os.path.join(HERE, "verifier")):
            trf0 = json.load(open(os.path.join(HERE, "verifier", "ring_model_truth.json")))
            pt_use = {int(v): [Fr(x) for x in row] for v, row in trf0.items()}
            q_use = sorted(pt_use)
        row = _row_ok(rep, pt_use, q_use)
        row["program"] = nm
        row["how"] = how
        row["research"] = rep.get("research")
        row["raw"] = _raw(rep)
        out[label] = row
        oks.append(row["ok"])
    # the shipped ring fixtures (verifier/ring_*.plan.json, produced by the public
    # pipeline on the build host) are bound, executed and checked afresh on THIS
    # host regardless of how far its time-bounded discovery got
    vdir = os.path.join(HERE, "verifier")
    mpf = os.path.join(vdir, "ring_model.uai")
    trf = json.load(open(os.path.join(vdir, "ring_model_truth.json")))
    ptf = {int(v): [Fr(x) for x in row] for v, row in trf.items()}
    qf = sorted(ptf)
    fx_rows = {}
    for label, fn in MX.RING_FIXTURES.items():
        pth = os.path.join(vdir, fn)
        if not os.path.exists(pth):
            fx_rows[label] = {"ok": False, "reason": "fixture absent"}
            continue
        repf = _replay_fresh(mpf, pth, wall)
        rowf = _row_ok(repf, ptf, qf)
        rowf["program"] = json.load(open(pth))["name"]
        rowf["raw"] = _raw(repf)
        fx_rows[label] = rowf
    out["ring_fixtures_fresh_replay"] = {"rows": fx_rows, "ok": bool(fx_rows) and all(r["ok"] for r in fx_rows.values())}
    oks.append(out["ring_fixtures_fresh_replay"]["ok"])
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
        out["nonzero_deletion"] = {"ok": False, "reason": "no regional record with a deleted state"}
        oks.append(False)
    else:
        rd = _replay_fresh(mpd, _plan(resd, dd, delrec), wall)
        rowd = _row_ok(rd, ptd, qd)
        rowd.update({"program": delrec, "research": rd.get("research"), "raw": _raw(rd)})
        rowd["ok"] = rowd["ok"] and (rd.get("research") or {}).get("deleted_states", 0) >= 1 \
            and Fr(((rd.get("ledger") or {}).get("verified") or {}).get("deletion_level1", "0")) > 0
        out["nonzero_deletion"] = rowd
        oks.append(rowd["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P6

def row_p6_saved_program_authority(wall):
    """P6: the two four-variable strict witnesses persisted, executed and
    checked without forcing selection, with factor-size versus elimination-bag
    diagnostics from the saved schedule; per-mode identity tuples (rounding
    tie distinct, whole-mode permutation deduplicates, swapped strengths
    distinct); the request object governs (deleted identity, no request,
    8192 precision, a different width all refused; the record's own width
    replays); a different executable never overwrites a completed program
    (collision); unknown query and schema violations are typed."""
    from mdi import model as M, replay as RP, pipeline as PLN, collective_route as CR, modes as MO, plantype as PT, budget as B
    from portfolio import independent_strict_witness as SW
    out, oks = {}, []
    sw = SW.run(wall=wall)
    out["strict_witnesses"] = {"ok": sw["ok"], "label": sw["note"],
                               "rows": [{"witness": r["witness"], "status": r["status"], "selected": r["selected"],
                                         "programs": {k: {kk: vv for kk, vv in v.items() if kk != "saved_order"}
                                                      for k, v in r["programs"].items()}} for r in sw["rows"]]}
    oks.append(sw["ok"])
    Q = 4
    f = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(-3, 8), Fr(3, 8)]}
    g = {0: [Fr(-1, 8), Fr(1, 8)], 1: [Fr(1, 4), Fr(-1, 4)]}
    base = {"evaluator": "statistic", "Q": Q, "deltas": None, "kept_factors": [], "dropped_pairs": []}
    exe = {"order": [0, 1], "precision": 96, "arithmetic": {"mode": "E"}, "checker": {"strategy": "dense_min_fill"}}
    cA = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[f], kind="lowrank_rank1")
    cB = MO.ModeCandidate(signs=[1], gammas=[Fr(1, 2)], features=[{v: [-x for x in row] for v, row in f.items()}], kind="lowrank_rank1")
    idA, kA = CR.canonical_identity(dict(base, candidate=cA), (), executable=exe)
    idB, kB = CR.canonical_identity(dict(base, candidate=cB), (), executable=exe)
    cP = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 2), Fr(1, 3)], features=[f, g], kind="lowrank_combined")
    cPp = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[g, f], kind="lowrank_combined")
    cSw = MO.ModeCandidate(signs=[1, 1], gammas=[Fr(1, 3), Fr(1, 2)], features=[f, g], kind="lowrank_combined")
    idP = CR.canonical_identity(dict(base, candidate=cP), (), executable=exe)[0]
    idPp = CR.canonical_identity(dict(base, candidate=cPp), (), executable=exe)[0]
    idSw = CR.canonical_identity(dict(base, candidate=cSw), (), executable=exe)[0]
    out["per_mode_identity_tuples"] = {"rounding_tie_same_features": [mm[:3] for mm in kA["modes"]] == [mm[:3] for mm in kB["modes"]],
                                       "rounding_tie_statistics": [[mm[3] for mm in kA["modes"]], [mm[3] for mm in kB["modes"]]],
                                       "rounding_tie_distinct": idA != idB, "whole_mode_permutation_same": idP == idPp,
                                       "swapped_strengths_distinct": idP != idSw,
                                       "ok": idA != idB and idP == idPp and idP != idSw}
    oks.append(out["per_mode_identity_tuples"]["ok"])
    # the one-variable half-rounding control through the pipeline: both laws persist as distinct files
    mp = _mean_field_path(4, 0.30)
    res, d, _, _ = _solve(M.read_uai(mp), wall, max_width=Fr(1, 10000)) if "max_width" in _solve.__code__.co_varnames else (None, None, None, None)
    if res is None:
        d = tempfile.mkdtemp()
        res = PLN.solve(M.read_uai(mp), {}, max_width=Fr(1, 10000), wall_s=wall, cap_bytes=1 << 30, plan_dir=d)
    plan = _plan(res, d, res.plan["chosen"])
    base_rec = json.load(open(plan))
    req = {}
    noid = copy.deepcopy(base_rec); noid["storage_schedule"].pop("identity", None)
    p1 = os.path.join(d, "noid.plan.json"); json.dump(noid, open(p1, "w"))
    r1 = RP.replay(mp, "-", p1)
    req["deleted_identity"] = {"status": r1["status"], "reason": str(r1.get("reason"))[:140], "ok": r1["status"] == "REPLAY_REFUSED" and "identity" in str(r1.get("reason"))}
    noreq = copy.deepcopy(base_rec); noreq.pop("request", None)
    p2 = os.path.join(d, "noreq.plan.json"); json.dump(noreq, open(p2, "w"))
    r2 = RP.replay(mp, "-", p2)
    req["deleted_request"] = {"status": r2["status"], "reason": str(r2.get("reason"))[:140], "ok": r2["status"] == "REPLAY_REFUSED" and "request" in str(r2.get("reason"))}
    hi = copy.deepcopy(base_rec); hi["numerical"]["precision"] = 8192; hi["request"]["precision"] = 8192
    if hi.get("program"):
        hi["program"]["precision"] = 8192
    p3 = os.path.join(d, "prec8192.plan.json"); json.dump(hi, open(p3, "w"))
    r3 = RP.replay(mp, "-", p3)
    req["precision_8192"] = {"status": r3["status"], "reason": str(r3.get("reason"))[:140], "ok": r3["status"] == "REPLAY_REFUSED" and "4096" in str(r3.get("reason"))}
    r4 = _replay_fresh(mp, plan, wall, eps=Fr(1, 100))
    req["other_width_1_100"] = {"status": r4["status"], "reason": str(r4.get("reason"))[:140], "ok": r4["status"] == "REPLAY_REFUSED"}
    r5 = _replay_fresh(mp, plan, wall)
    req["record_width_replayed"] = {"status": r5["status"], "request_width": r5.get("request_width"),
                                    "ok": r5["status"] == "REPLAY_VERIFIED" and r5.get("request_width") == "1/10000"
                                          and (r5.get("request") or {}).get("width") == "1/10000", "raw": _raw(r5)}
    mal = copy.deepcopy(base_rec); mal["request"]["width"] = "abc"
    p6 = os.path.join(d, "malreq.plan.json"); json.dump(mal, open(p6, "w"))
    r6 = RP.replay(mp, "-", p6)
    req["malformed_request_width"] = {"status": r6["status"], "reason": str(r6.get("reason"))[:140], "ok": r6["status"] == "REPLAY_REFUSED"}
    # ---- the EFFECTIVE request (r21): actual caller limits are recorded; saved
    # entry-one / zero-wall / byte-one / null-limits / fake-mode / inconsistent
    # exponents are handled by the documented rule BEFORE execution; a replay
    # tightens its budget to the record's effective limits, never loosens
    d20 = tempfile.mkdtemp()
    r20 = PLN.solve(M.read_uai(mp), {}, wall_s=20, cap_bytes=1 << 30, plan_dir=d20, research_enabled=False)
    plan20 = _plan(r20, d20, "identity")
    rec20 = json.load(open(plan20))
    eff = rec20["request"]["limits"]["effective"]
    clean20 = RP.replay(mp, "-", plan20)
    effrows = {"recorded_effective": eff, "recorded_frozen": rec20["request"]["limits"]["frozen"],
               "effective_matches_caller": eff.get("wall_s") == 20.0 and eff.get("rss_bytes") == (1 << 30),
               "replay_tightened_to_record": (clean20.get("budget") or {}).get("tightened"),
               "clean_replay": clean20["status"]}

    def mut20(label, fn, want_status, want_words):
        b = copy.deepcopy(rec20); fn(b)
        pth = os.path.join(d20, label + ".plan.json"); json.dump(b, open(pth, "w"))
        rr = RP.replay(mp, "-", pth)
        txt = str(rr.get("reason"))
        effrows[label] = {"status": rr["status"], "reason": txt[:160], "used": (rr.get("budget") or {}).get("used"),
                          "ok": rr["status"] == want_status and any(w_ in txt for w_ in want_words)}
    mut20("saved_entry_limit_one", lambda b: b["request"]["limits"]["effective"].__setitem__("local_mass_entries", 1),
          "REPLAY_REFUSED", ("REMAINING shared meter", "forecast metered"))
    mut20("saved_zero_wall", lambda b: b["request"]["limits"]["effective"].__setitem__("wall_s", 0),
          "REPLAY_REFUSED", ("not in (0,",))
    mut20("saved_byte_limit_one", lambda b: b["request"]["limits"]["effective"].__setitem__("rss_bytes", 1),
          "REPLAY_RESOURCE_STOP", ("rss",))
    mut20("saved_null_limits", lambda b: b["request"].__setitem__("limits", None), "REPLAY_REFUSED", ("limits",))
    mut20("saved_fake_mode", lambda b: b["request"].__setitem__("arithmetic_mode", "Q"), "REPLAY_REFUSED", ("arithmetic mode",))
    mut20("saved_inconsistent_exponents", lambda b: (b["request"].__setitem__("emin", 0), b["request"].__setitem__("emax", 0)),
          "REPLAY_REFUSED", ("emin", "emax", "exponent"))
    mut20("saved_effective_above_frozen", lambda b: b["request"]["limits"]["effective"].__setitem__("wall_s", 601),
          "REPLAY_REFUSED", ("not in (0,",))
    effrows["ok"] = (effrows["effective_matches_caller"] and clean20["status"] == "REPLAY_VERIFIED"
                     and bool(effrows["replay_tightened_to_record"])
                     and all(v["ok"] for k, v in effrows.items() if isinstance(v, dict) and "ok" in v))
    req["effective_request"] = effrows
    req["ok"] = all(v["ok"] for v in req.values() if isinstance(v, dict))
    out["request_object_governs"] = req
    oks.append(req["ok"])
    # collision: a differing file already occupies the identity path
    d2 = tempfile.mkdtemp()
    ident = next(p["identity"] for p in res.prices if p["name"] == res.plan["chosen"])
    occupied = os.path.join(d2, ident + ".plan.json")
    open(occupied, "w").write('{"foreign": true}')
    res2 = PLN.solve(M.read_uai(mp), {}, max_width=Fr(1, 10000), wall_s=wall, cap_bytes=1 << 30, plan_dir=d2)
    coll = [x for x in res2.rejected if "never overwrites" in str(x.get("reason")) or x.get("typed") == "COLLISION"]
    out["collision_never_overwrites"] = {"status": res2.status, "refusals": [str(x.get("reason"))[:120] for x in coll][:2],
                                         "file_unchanged": open(occupied).read() == '{"foreign": true}',
                                         "ok": bool(coll) and open(occupied).read() == '{"foreign": true}'}
    oks.append(out["collision_never_overwrites"]["ok"])
    ru = PLN.solve(M.read_uai(mp), {}, queries={99}, wall_s=30, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    neg = M.Model(nvars=1, card=[2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(-1)], origin=0)])
    rn = PLN.solve(neg, {}, wall_s=30, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    out["typed_schema_outcomes"] = {"unknown_query": (ru.status, str(ru.reason)[:80]), "negative_entry": (rn.status, str(rn.reason)[:80]),
                                    "ok": ru.status == "INVALID_INPUT" and rn.status == "INVALID_INPUT"}
    oks.append(out["typed_schema_outcomes"]["ok"])
    # ---- the public request is normalized ONCE: every finite iterable of ints
    # is the same request; malformed queries / widths / limits are typed refusals
    mu = M.Model(nvars=1, card=[2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(3)], origin=0)]).validate()
    forms = {"set": {0}, "list": [0], "tuple": (0,), "generator": (v for v in [0]), "iterator": iter([0])}
    rows_q = {}
    for label, qf in forms.items():
        rq = PLN.solve(mu, {}, queries=qf, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        rows_q[label] = {"status": rq.status, "keys": sorted(rq.intervals),
                         "encloses_1_4_and_3_4": bool(rq.intervals) and Fr(rq.intervals[0][0][0]) <= Fr(1, 4) <= Fr(rq.intervals[0][0][1])
                                                 and Fr(rq.intervals[0][1][0]) <= Fr(3, 4) <= Fr(rq.intervals[0][1][1])}
    refusals = {}
    for label, kw in (("string_queries", dict(queries="0")), ("bool_query_element", dict(queries=[True])),
                      ("cap_bytes_zero", dict(cap_bytes=0)), ("wall_nan", dict(wall_s=float("nan"))), ("wall_inf", dict(wall_s=float("inf"))),
                      ("wall_negative", dict(wall_s=-1)), ("float_width", dict(max_width=0.01)), ("bool_cap", dict(cap_bytes=True)),
                      ("width_above_one", dict(max_width=Fr(3, 2)))):
        base = dict(wall_s=wall, cap_bytes=1 << 30)
        base.update(kw)
        rr = PLN.solve(mu, {0: 1}, plan_dir=tempfile.mkdtemp(), research_enabled=False, **base)
        refusals[label] = {"status": rr.status, "reason": str(rr.reason)[:100]}
    rdef = PLN.solve(mu, {0: 1}, wall_s=None, cap_bytes=None, max_width=None, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    rstr = PLN.solve(mu, {}, max_width="1/200", wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    dec_rows = {}
    for label, facs in (("decimal_strings", [M.Factor((0,), (2,), ['0.1', '0.3'], 0)]), ("rational_strings", [M.Factor((0,), (2,), ['1/10', '3/10'], 0)]),
                        ("fractions", [M.Factor((0,), (2,), [Fr(1, 10), Fr(3, 10)], 0)])):
        mdl = M.Model(1, [2], facs)
        before = list(facs[0].table)
        rr = PLN.solve(mdl, {}, research_enabled=False, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        dec_rows[label] = {"status": rr.status, "encloses_1_4_and_3_4": bool(rr.intervals) and Fr(rr.intervals[0][0][0]) <= Fr(1, 4) <= Fr(rr.intervals[0][0][1])
                                                             and Fr(rr.intervals[0][1][0]) <= Fr(3, 4) <= Fr(rr.intervals[0][1][1]),
                           "caller_table_untouched": facs[0].table == before}
    bad_rows = {}
    for label, mdl in (("none_entry", M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), None], 0)])), ("text_entry", M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), 'oops'], 0)])),
                       ("float_entry", M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), 0.3], 0)])), ("model_none", None), ("model_dict", {"nvars": 1}),
                       ("factor_not_a_factor", M.Model(1, [2], ["x"]))):
        rr = PLN.solve(mdl, {}, research_enabled=False, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        bad_rows[label] = {"status": rr.status, "reason": str(rr.reason)[:90]}
    r_frac_bad = PLN.solve(mu, {}, wall_s=wall, cap_bytes=Fr(2147483649, 2), plan_dir=tempfile.mkdtemp(), research_enabled=False)
    r_frac_ok = PLN.solve(mu, {}, wall_s=wall, cap_bytes=Fr(1 << 30), plan_dir=tempfile.mkdtemp(), research_enabled=False)
    # r26: an enormous FINITE wall is a legal request for the frozen maximum (clamped exactly, never an overflow)
    r_huge = PLN.solve(mu, {}, wall_s=10 ** 400, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    huge_ok = r_huge.status.startswith("CERTIFIED") and (r_huge.budget or {}).get("effective_limits", {}).get("wall_s") == 600.0 \
        and str((r_huge.budget or {}).get("requested_by_caller", {}).get("wall_s", "")).startswith("1" + "0" * 20)
    mpe = _write_uai(mu)
    de = tempfile.mkdtemp()
    r_empty = PLN.solve(M.read_uai(mpe), {}, queries=[], wall_s=wall, cap_bytes=1 << 30, plan_dir=de, research_enabled=False)
    rep_empty = _replay_fresh(mpe, _plan(r_empty, de, "identity"), wall)
    rep_cap = _replay_fresh(mpe, _plan(r_empty, de, "identity"), wall) if False else RP.replay(mpe, "-", _plan(r_empty, de, "identity"), cap_bytes=Fr(3, 2))
    struct_rows = {}
    for label, mdl in (("nvars_3_2", M.Model(Fr(3, 2), [2], [M.Factor((0,), (2,), [Fr(1), Fr(3)], 0)])),
                       ("card_5_2", M.Model(1, [Fr(5, 2)], [M.Factor((0,), (Fr(5, 2),), [Fr(1), Fr(3)], 0)])),
                       ("card_2_5_float", M.Model(1, [2.5], [M.Factor((0,), (2.5,), [Fr(1), Fr(3)], 0)])),
                       ("scope_1_2", M.Model(1, [2], [M.Factor((Fr(1, 2),), (2,), [Fr(1), Fr(3)], 0)])),
                       ("nvars_inf", M.Model(float("inf"), [2], [M.Factor((0,), (2,), [Fr(1), Fr(3)], 0)])),
                       ("origin_float", M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), Fr(3)], 1.0)])),
                       ("provenance_not_mapping", M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), Fr(3)], 0)], provenance=3))):
        rr = PLN.solve(mdl, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        struct_rows[label] = {"status": rr.status, "reason": str(rr.reason)[:80]}
    out["structural_validity_before_coercion"] = {"rows": struct_rows,
                                                  "ok": all(r["status"] == "INVALID_INPUT" for r in struct_rows.values())}
    oks.append(out["structural_validity_before_coercion"]["ok"])
    # the budget starts at ENTRY: an injected 1 s normalization against a 0.1 s wall
    # is a RESOURCE_STOP with the work recorded (deterministic); the real large
    # decimal encoding is reported as an OBSERVATION of actual elapsed time
    class _Clk:
        t = 1000.0

        def __call__(self):
            return _Clk.t
    saved_clk = B.DEFAULT_CLOCK[0]
    orig_nm = PLN.normalize_model

    def slow_nm(model, bg=None):
        _Clk.t += 1.0
        return orig_nm(model, bg=bg)
    B.DEFAULT_CLOCK[0] = _Clk()
    PLN.normalize_model = slow_nm
    try:
        rnorm = PLN.solve(M.Model(1, [2], [M.Factor((0,), (2,), [Fr(1), Fr(3)], 0)]), {0: 0}, wall_s=0.1, cap_bytes=1 << 30,
                          plan_dir=tempfile.mkdtemp(), research_enabled=False)
    finally:
        PLN.normalize_model = orig_nm
        B.DEFAULT_CLOCK[0] = saved_clk
    t_big = time.monotonic()
    rbig = PLN.solve(M.Model(1, [2], [M.Factor((0,), (2,), ['1.' + '0' * 1_000_000, '3'], 0)]), {0: 0}, wall_s=0.1, cap_bytes=1 << 30,
                     plan_dir=tempfile.mkdtemp(), research_enabled=False)
    el_big = time.monotonic() - t_big
    out["normalization_inside_the_budget"] = {
        "injected_1s_under_0_1s": {"status": rnorm.status, "elapsed_s": (rnorm.budget or {}).get("elapsed_s"), "reason": str(rnorm.reason)[:80]},
        "observed_1MB_decimal_under_0_1s": {"status": rbig.status, "outer_elapsed_s": round(el_big, 3), "reported_elapsed_s": (rbig.budget or {}).get("elapsed_s"),
                                            "note": "an observation of this host's actual normalization time; not a speed benchmark"},
        "ok": rnorm.status == "RESOURCE_STOP" and not rnorm.intervals and float((rnorm.budget or {}).get("elapsed_s") or 0) >= 1.0
              and (rbig.status != "CERTIFIED_FALLBACK_ONLY" or el_big <= 0.1 + 0.05)
              and abs(float((rbig.budget or {}).get("elapsed_s") or 0) - el_big) < 0.1}
    oks.append(out["normalization_inside_the_budget"]["ok"])
    out["declared_input_contract"] = {
        "exact_scalar_forms": dec_rows, "malformed_inputs": bad_rows,
        "nonintegral_fraction_cap": {"status": r_frac_bad.status, "reason": str(r_frac_bad.reason)[:90]},
        "integral_fraction_cap": {"status": r_frac_ok.status, "effective_rss": (r_frac_ok.budget or {}).get("effective_limits", {}).get("rss_bytes")},
        "empty_request": {"solve": r_empty.status, "solve_intervals": r_empty.intervals, "replay": rep_empty["status"], "replay_intervals": rep_empty.get("intervals")},
        "replay_nonintegral_cap": rep_cap["status"],
        "enormous_finite_wall": {"status": r_huge.status, "effective_wall_s": (r_huge.budget or {}).get("effective_limits", {}).get("wall_s"),
                                 "requested_digits": len(str((r_huge.budget or {}).get("requested_by_caller", {}).get("wall_s", ""))), "ok": huge_ok},
        "ok": huge_ok and all(r["status"].startswith("CERTIFIED") and r["encloses_1_4_and_3_4"] and r["caller_table_untouched"] for r in dec_rows.values())
              and all(r["status"] == "INVALID_INPUT" for r in bad_rows.values())
              and r_frac_bad.status == "INVALID_INPUT" and r_frac_ok.status.startswith("CERTIFIED")
              and (r_frac_ok.budget or {}).get("effective_limits", {}).get("rss_bytes") == (1 << 30)
              and r_empty.status.startswith("CERTIFIED") and r_empty.intervals == {} and rep_empty["status"] == "REPLAY_VERIFIED"
              and rep_empty.get("intervals") == {} and rep_cap["status"] == "REPLAY_INVALID_INPUT"}
    oks.append(out["declared_input_contract"]["ok"])
    out["public_request_normalization"] = {
        "query_forms": rows_q, "refusals": refusals,
        "none_means_frozen_defaults": {"status": rdef.status, "effective": (rdef.budget or {}).get("effective_limits")},
        "string_width": {"status": rstr.status, "width": str((rstr.budget or {}) and rstr.plan.get("request_width", "")) or None},
        "ok": all(r["status"].startswith("CERTIFIED") and r["keys"] == [0] and r["encloses_1_4_and_3_4"] for r in rows_q.values())
              and all(r["status"] == "INVALID_INPUT" for r in refusals.values())
              and rdef.status.startswith("CERTIFIED") and (rdef.budget or {}).get("effective_limits", {}).get("wall_s") == 600.0
              and rstr.status.startswith("CERTIFIED")}
    oks.append(out["public_request_normalization"]["ok"])
    # zero-support replay terminal states the plan was NOT verified
    m4 = M.read_uai(mp)
    z = M.Model(nvars=m4.nvars, card=list(m4.card), factors=list(m4.factors) + [M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=999)]).validate()
    mpz = _write_uai(z)
    evz = mpz + ".evid"
    open(evz, "w").write("1 0 1\n")
    rz = _replay_fresh(mpz, plan, wall, evid=evz)
    out["zero_support_terminal"] = {"status": rz["status"], "supplied_program_verified": rz.get("supplied_program_verified"),
                                    "note": rz.get("note"), "reason": str(rz.get("reason"))[:120],
                                    "ok": rz["status"] in ("REPLAY_ZERO_EVIDENCE_PROVED", "REPLAY_REFUSED")
                                          and (rz["status"] != "REPLAY_ZERO_EVIDENCE_PROVED" or rz.get("supplied_program_verified") is False)}
    oks.append(out["zero_support_terminal"]["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P7

def row_p7_execution_contract(wall):
    """P7: the independent checker's applicability is decided BEFORE admission
    (13-variable positive complete graph: bag 8,192 > 4,096, CHECKER_CAP_PROVED,
    a truthful typed refusal in seconds; a hard-zero variant is UNKNOWN after
    a charged bounded probe; the 13-variable chain still verifies 26
    coordinates); identity runs under the shared entry meter; an exhausted
    deadline is never renewed; raw gmpy2 transcendental calls equal the
    monotone per-stage counts and per-engine forecasts bound them; every
    Fraction operation of the ring's statistic programs is bounded by the
    price; the invocation ledger records discovery work in its own units."""
    from mdi import model as M, oracle as O, pipeline as PLN, replay as RP, budget as B, solve as S, pricing as PR, plan as P
    from tests.test_mdi_research import ring_of_blocks, w, TINY
    import gmpy2
    out, oks = {}, []
    n = 13
    un = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 5, 10)], origin=v) for v in range(n)]
    comp = un + [M.Factor(scope=(i, j), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + (i + j) % 3)], origin=100 + 13 * i + j)
                 for i in range(n) for j in range(i + 1, n)]
    mg = M.Model(nvars=n, card=[2] * n, factors=comp).validate()
    t = time.time()
    rg = PLN.solve(mg, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    el = time.time() - t
    out["complete_graph_13_pre_admission"] = {"status": rg.status, "seconds": round(el, 2), "reason": str(rg.reason)[:220],
                                              "feasibility": next((x.get("feasibility") for x in rg.rejected if x.get("name") == "identity"), None),
                                              "ok": rg.status == "PRICE_REFUSAL" and "CHECKER_CAP_PROVED" in str(rg.reason) and "8192" in str(rg.reason)
                                                    and not rg.intervals and el < 60}
    oks.append(out["complete_graph_13_pre_admission"]["ok"])
    compz = un + [M.Factor(scope=(i, j), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(0) if (i, j) == (0, 1) else Fr(2 + (i + j) % 3)], origin=100 + 13 * i + j)
                  for i in range(n) for j in range(i + 1, n)]
    mz = M.Model(nvars=n, card=[2] * n, factors=compz).validate()
    rz = M.restrict(mz, {})
    sel = P.choose_plan(rz.free, rz.card, rz.factors, 64, 1 << 30)
    bgp = B.Budget(60, limits={"pricing_entries": 10 ** 6})
    feas = PR.identity_checker_feasibility(sel["chosen"][0], rz, bgp)
    out["hard_zero_13_feasibility_unknown"] = {"feasibility": feas, "charged": dict(bgp.used),
                                               "ok": feas["checker"] == "CHECKER_FEASIBILITY_UNKNOWN" and bgp.used.get("pricing_entries", 0) > 0}
    oks.append(out["hard_zero_13_feasibility_unknown"]["ok"])
    chain = un + [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + i % 3)], origin=100 + i) for i in range(n - 1)]
    m13 = M.Model(nvars=n, card=[2] * n, factors=chain).validate()
    Z, pt13 = O.exact_all_marginals(M.restrict(m13, {}))
    r13 = PLN.solve(m13, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    out["chain_13_identity_checker"] = {"status": r13.status, "coordinates_checked": (r13.checker or {}).get("coordinates_checked"),
                                        "truth": _contains(r13.intervals, pt13), "width": str(_width(r13.intervals)),
                                        "ok": r13.status.startswith("CERTIFIED") and (r13.checker or {}).get("coordinates_checked") == 26
                                              and _contains(r13.intervals, pt13) and _width(r13.intervals) <= EPS}
    oks.append(out["chain_13_identity_checker"]["ok"])
    # the affordable 16-variable chain still verifies all 32 probabilities
    n16 = 16
    ch16 = [M.Factor(scope=(v,), card=(2,), table=[Fr(1), Fr(1) + Fr(1 + v % 5, 10)], origin=v) for v in range(n16)]
    ch16 += [M.Factor(scope=(i, i + 1), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2 + i % 3)], origin=100 + i) for i in range(n16 - 1)]
    m16 = M.Model(nvars=n16, card=[2] * n16, factors=ch16).validate()
    Z, pt16 = O.exact_all_marginals(M.restrict(m16, {}))
    r16 = PLN.solve(m16, {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    out["chain_16_identity_checker"] = {"status": r16.status, "coordinates_checked": (r16.checker or {}).get("coordinates_checked"),
                                        "truth": _contains(r16.intervals, pt16), "width": str(_width(r16.intervals)),
                                        "ok": r16.status.startswith("CERTIFIED") and (r16.checker or {}).get("coordinates_checked") == 32
                                              and _contains(r16.intervals, pt16) and _width(r16.intervals) <= EPS}
    oks.append(out["chain_16_identity_checker"]["ok"])
    # the identity's PRODUCER and CHECKER on the same shared meter (conditional
    # solve): the meter splits by source; below the forecast the pipeline refuses
    # before work (same unit as the actual producer + checker schedule); through
    # the registered roles under a cap between producer and producer + checker
    # the CHECKER stops with the producer's entries charged; normal cap succeeds
    m4 = M.read_uai(_mean_field_path(4, 0.30))
    Z, pt4c = O.exact_all_marginals(M.restrict(m4, {3: 1}))
    rn = PLN.solve(m4, {3: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
    src = rn.budget.get("used_by_source") or {}
    prod = sum(v for k, v in src.items() if "producer" in k)
    chk = sum(v for k, v in src.items() if "checker" in k)
    fc = next((int(p["counters"]["metered_entries_forecast"]["value"]) for p in rn.prices if p["name"] == "identity"), None)
    meter = {"normal_cap": {"status": rn.status, "truth": _contains({v: rn.intervals[v] for v in (0, 1, 2)}, pt4c),
                            "producer_entries": prod, "checker_entries": chk, "forecast_metered_entries": fc,
                            "forecast_covers_actual": fc is not None and fc >= prod + chk}}
    orig_init = B.Budget.__init__
    for label, cap in (("cap_one", 1), ("cap_producer_only", prod), ("cap_below_producer_plus_checker", prod + chk - 1)):
        def patched(self, wall_s, limits=None, rss_fn=None, rss_limit=None, _cap=cap, **kw):
            lim = dict(limits or {}); lim["local_mass_entries"] = _cap
            orig_init(self, wall_s, limits=lim, rss_fn=rss_fn, rss_limit=rss_limit, **kw)
        B.Budget.__init__ = patched
        try:
            rr = PLN.solve(m4, {3: 1}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp(), research_enabled=False)
        finally:
            B.Budget.__init__ = orig_init
        meter[label] = {"status": rr.status, "reason": str(rr.reason)[:120], "used": rr.budget.get("used"),
                        "published": bool(rr.intervals),
                        "ok": rr.status in ("RESOURCE_STOP", "PRICE_REFUSAL") and not rr.intervals}
    # the registered roles under a budget whose cap admits production but not checking
    from mdi import registry as RG, law as LAW
    law4 = LAW.OriginalLaw.freeze(m4, {3: 1}, {0, 1, 2})
    for label, cap in (("roles_cap_one", 1), ("roles_cap_between", prod + chk - 1), ("roles_cap_normal", 10 ** 6)):
        bgr = B.Budget(60, limits={"local_mass_entries": cap})
        own = law4.restriction()
        ctx = {"model": law4.model, "evidence": dict(law4.evidence), "eps": EPS - K_RESERVE(), "cap_bytes": 1 << 30,
               "remaining": bgr.remaining, "restricted": own.r, "queries": {0, 1, 2}, "budget": bgr, "program": None,
               "progress": lambda *a, **k: None}
        stage = None
        try:
            stage = "producer"
            iv = RG.pipeline_identity_executor(ctx)
            stage = "checker"
            ok, fails, meta = RG.pipeline_identity_checker(law4.model, dict(law4.evidence), iv, EPS, deadline_s=60, cap_bytes=1 << 30,
                                                           charge=lambda n: bgr.charge("local_mass_entries", n, "identity checker entries"))
            meter[label] = {"stopped_in": None, "verified": bool(ok), "used": dict(bgr.used), "by_source": dict(bgr.used_by_source),
                            "ok": (cap >= prod + chk) and bool(ok)}
        except B.BudgetExceeded as e:
            meter[label] = {"stopped_in": stage, "reason": str(e)[:120], "used": dict(bgr.used), "by_source": dict(bgr.used_by_source),
                            "ok": (stage == "producer" and cap == 1) or (stage == "checker" and 1 < cap < prod + chk and bgr.used.get("local_mass_entries", 0) > prod)}
        except Exception as e:
            meter[label] = {"stopped_in": stage, "error": "%s: %s" % (type(e).__name__, str(e)[:100]), "ok": False}
    meter["ok"] = (rn.status.startswith("CERTIFIED") and meter["normal_cap"]["truth"] and prod > 0 and chk > 0
                   and meter["normal_cap"]["forecast_covers_actual"]
                   and all(v["ok"] for k, v in meter.items() if isinstance(v, dict) and "ok" in v))
    out["identity_producer_and_checker_on_one_meter"] = meter
    oks.append(meter["ok"])
    s0 = S.solve(M.read_uai(w(TINY)), {}, eps=EPS, mode="P", cap_bytes=1 << 30, deadline_s=0.0)
    s1 = S.solve(M.read_uai(w(TINY)), {}, eps=EPS, mode="P", cap_bytes=1 << 30, deadline_s=-2.0)
    out["exhausted_deadline_never_renewed"] = {"zero": s0["outcome"], "negative": s1["outcome"],
                                               "ok": s0["outcome"] == "RESOURCE_STOP" and s1["outcome"] == "RESOURCE_STOP"}
    oks.append(out["exhausted_deadline_never_renewed"]["ok"])
    # raw gmpy2 calls versus the monotone per-stage counts and the per-engine forecasts
    m = _chain3()
    mp = _write_uai(m)
    res, d, _, _ = _solve(M.read_uai(mp), wall)
    raw = collections.Counter()
    orig = {nm: getattr(gmpy2, nm) for nm in ("exp", "log", "sqrt", "sin", "cos", "const_pi")}
    for nm, fn in orig.items():
        setattr(gmpy2, nm, (lambda fn, nm: (lambda *a, **k: (raw.__setitem__(nm, raw[nm] + 1), fn(*a, **k))[1]))(fn, nm))
    counts = {}
    try:
        for name in ("mixed:lowrank_combined", "gaussian:lowrank_rank1", "fourier:lowrank_rank1", "statistic:lowrank_combined"):
            p = next((x for x in res.prices if x["name"] == name), None)
            if p is None:
                counts[name] = {"ok": False, "reason": "absent"}
                continue
            raw.clear()
            rep = RP.replay(mp, "-", _plan(res, d, name))
            st = ((rep.get("complete_cost") or {}).get("measured") or {}).get("stage_transcendental_calls") or {}
            tot = sum(v.get("total", 0) for v in st.values())
            ex = rep.get("executor") or {}
            ck = (rep.get("checker") or {}).get("collective") or {}
            fp = (p["counters"].get("transcendental_producer_forecast") or {}).get("value")
            fc = (p["counters"].get("transcendental_checker_forecast") or {}).get("value")
            te, tc = ex.get("transcendental_calls"), ck.get("transcendental_calls")
            counts[name] = {"status": rep["status"], "raw_gmpy2": dict(raw), "raw_total": sum(raw.values()),
                            "stage_totals": {k: v.get("total") for k, v in st.items()}, "stage_sum": tot,
                            "executor_measured": te, "producer_forecast": fp, "checker_measured": tc, "checker_forecast": fc,
                            "executor_by_kind": ex.get("transcendental_by_kind"), "checker_by_kind": ck.get("transcendental_by_kind"),
                            "ok": rep["status"] == "REPLAY_VERIFIED" and tot == sum(raw.values()) and None not in (te, tc, fp, fc)
                                  and int(fp) >= int(te) and int(fc) >= int(tc)}
    finally:
        for nm, fn in orig.items():
            setattr(gmpy2, nm, fn)
    out["mpfr_counts"] = {"rows": counts, "ok": all(v.get("ok") for v in counts.values())}
    oks.append(out["mpfr_counts"]["ok"])
    # EVERY Fraction operation of the 12-variable ring's statistic programs is bounded by the price
    mpr = w(ring_of_blocks()[0])
    mr = M.read_uai(mpr)
    resr, dr, _, _ = _solve(mr, wall)
    Z, ptr = O.exact_all_marginals(M.restrict(mr, {}))
    qr = sorted(M.restrict(mr, {}).free)
    rows = {}
    for p in resr.prices:
        if "statistic" not in p["name"] or not p["eligible"]:
            continue
        wrap, cnt = _measure_ops()
        rep = _replay_here(mpr, _plan(resr, dr, p["name"]), wrap=wrap)
        c = p["counters"]
        pp = sum(int(c[k]["value"]) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops")) \
            + int((c.get("producer_comparison_ops") or {}).get("value") or 0)
        pc = int(c["checker_ops"]["value"]) + int((c.get("checker_comparison_ops") or {}).get("value") or 0)
        row = _row_ok(rep, ptr, qr)
        row.update({"priced_producer": pp, "counted_producer_all_ops": cnt.get("execute"), "priced_checker": pc,
                    "counted_checker_all_ops": cnt.get("check"), "key_ops_priced": (c.get("statistic_key_ops") or {}).get("value"),
                    "restoration_ops_priced": (c.get("statistic_restoration_ops") or {}).get("value"), "raw": _raw(rep)})
        row["ok"] = row["ok"] and cnt.get("execute") is not None and cnt.get("check") is not None and pp >= cnt["execute"] and pc >= cnt["check"]
        rows[p["name"]] = row
    out["ring_statistic_priced_work"] = {"programs": len(rows), "rows": rows, "ok": bool(rows) and all(r["ok"] for r in rows.values())}
    oks.append(out["ring_statistic_priced_work"]["ok"])
    # the NATURAL discovery history of this (timed) invocation: an INTEGRITY
    # obligation on what actually happened -- closed attempts and events,
    # recorded elapsed work, honest unknowns, totals that agree -- and an
    # OBSERVATION of how far it got (never a requirement on how far; r26)
    natural = MX.natural_history_integrity(resr)
    led_n = resr.plan.get("invocation_ledger") or {}
    natural["observation"] = {"construction_events": len(led_n.get("construction_events") or []),
                              "events_completed": sum(1 for e in (led_n.get("construction_events") or []) if e.get("status") == "completed"),
                              "candidates_admitted_during_discovery": led_n.get("candidates_admitted_during_discovery"),
                              "note": "what this host's timed discovery reached; not the accounting obligation"}
    out["natural_discovery_history"] = natural
    oks.append(natural["ok"])
    # the CAPABILITY obligations -- recognizer coverage with measured work,
    # construction EVENTS counted once and reused -- run on a DETERMINISTIC
    # history: the input-law recognizer declines once so regional construction
    # executes and the composed candidates are offered on its cells and reuse
    # its event (the review's 1,096 x 3 = 3,288 over-count is gone)
    resd_, dd_, _, _ = MX.with_input_law_recognizer_declined(lambda: _solve(mr, wall))
    led = resd_.plan.get("invocation_ledger") or {}
    cc = resd_.plan.get("complete_cost") or {}
    atts = led.get("attempts") or []
    recog = [a for a in atts if a.get("kind") == "recognizer"]
    out["invocation_ledger"] = {"history": "deterministic (input-law recognizer declined once)",
                                "attempts_recorded": len(atts), "recognizer_attempts": len(recog),
                                "recognizer_statuses": sorted({a.get("status") for a in recog}),
                                "composed_recognizer_attempted": any(str(a.get("name", "")).startswith("composed:") for a in recog),
                                "every_recognizer_attempt_has_elapsed_and_mpfr": all("elapsed_s" in a and "transcendental_calls" in a for a in recog),
                                "fit_ops_labelled_unknown": all(a.get("fit_ops") == "unknown" for a in recog) and led.get("recognizer_fit_ops") == "unknown",
                                "construction_ops_measured": led.get("construction_ops_measured"),
                                "recognizer_seconds": led.get("recognizer_seconds"), "recognizer_transcendental_calls": led.get("recognizer_transcendental_calls"),
                                "units": led.get("units"), "complete_cost_discovery": cc.get("discovery_all_candidates_ops"),
                                "ok": len(recog) >= 2 and any(str(a.get("name", "")).startswith("composed:") for a in recog)
                                      and all("elapsed_s" in a and "transcendental_calls" in a for a in recog)
                                      and all(a.get("status") in ("admitted", "declined", "failed", "budget") for a in recog)
                                      and led.get("recognizer_fit_ops") == "unknown" and int(led.get("construction_ops_measured", 0)) > 0
                                      and isinstance(cc.get("discovery_all_candidates_ops"), dict)
                                      and cc["discovery_all_candidates_ops"].get("recognizer_fit_ops") == "unknown"}
    oks.append(out["invocation_ledger"]["ok"])
    evs = led.get("construction_events") or []
    done = [e for e in evs if e.get("status") != "running"]
    multi = [e for e in done if len(e.get("referenced_by") or []) > 1 and e.get("construction_ops_measured")]
    uniq = sum(int(e.get("construction_ops_measured") or 0) for e in done)
    naive = sum(int(e.get("construction_ops_measured") or 0) * max(1, len(e.get("referenced_by") or [])) for e in done)
    cands_ref = [a for a in atts if a.get("kind") == "candidate"]
    out["construction_event_ledger"] = {
        "history": "deterministic (input-law recognizer declined once)",
        "events": [{k: e.get(k) for k in ("id", "name", "status", "construction_ops_measured", "elapsed_s", "transcendental_calls")}
                   | {"referenced_by": len(e.get("referenced_by") or [])} for e in evs],
        "unique_event_total": uniq, "naive_per_candidate_total": naive,
        "an_event_is_reused_by_several_candidates": bool(multi),
        "every_event_closed": all(e.get("status") != "running" for e in evs),
        "every_candidate_references_its_event": all(a.get("construction_event") is not None for a in cands_ref if a["name"].startswith(("regional", "composed"))),
        "ledger_total_equals_unique_events": int(led.get("construction_ops_measured", -1)) == uniq,
        "ok": bool(evs) and all(e.get("status") != "running" for e in evs) and bool(multi) and uniq < naive
              and int(led.get("construction_ops_measured", -1)) == uniq
              and all(a.get("construction_event") is not None for a in cands_ref if a["name"].startswith(("regional", "composed")))}
    oks.append(out["construction_event_ledger"]["ok"])
    # the ledger already assembled survives a GLOBAL stop during discovery (no new work)
    orig_init2 = B.Budget.__init__

    def patched2(self, wall_s, limits=None, rss_fn=None, rss_limit=None, **kw):
        lim = dict(limits or {}); lim["pricing_entries"] = 2000
        orig_init2(self, wall_s, limits=lim, rss_fn=rss_fn, rss_limit=rss_limit, **kw)
    B.Budget.__init__ = patched2
    try:
        rs = PLN.solve(M.read_uai(mpr), {}, wall_s=wall, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        B.Budget.__init__ = orig_init2
    leds = (rs.plan or {}).get("invocation_ledger") or {}
    out["ledger_on_global_stop"] = {"status": rs.status, "reason": str(rs.reason)[:100], "ledger_present": bool(leds),
                                    "attempts": len(leds.get("attempts") or []), "events": len(leds.get("construction_events") or []),
                                    "every_event_closed": all(e.get("status") != "running" for e in (leds.get("construction_events") or [])),
                                    "ok": rs.status == "RESOURCE_STOP" and bool(leds) and len(leds.get("attempts") or []) > 0
                                          and all(e.get("status") != "running" for e in (leds.get("construction_events") or []))}
    oks.append(out["ledger_on_global_stop"]["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P8

def row_p8_lifecycle(wall):
    """P8: lifecycle controls under an INJECTED clock: parse delay (the budget
    exists before parsing), a 31 s local proof inside the 30 s allowance, a
    global reference contraction past the whole-arm wall, a durable terminal
    write completing after the wall, the RSS cap, a malformed request; the F6
    entry flush and probe charging; memory unavailable is reported as such,
    never zero; the F3 construction fallback is carried from the r19 gate."""
    from mdi import model as M, oracle as O, pipeline as PLN, replay as RP, budget as B, arm as ARM, solve as S, planning as PLAN
    from mdi import program_check as PC, collective_route as CR
    out, oks = {}, []
    mp = _mean_field_path(4, 0.30)
    res, d, _, _ = _solve(M.read_uai(mp), wall)
    stat = next(p["name"] for p in res.prices if p["name"].startswith("statistic:") and p["eligible"])
    plan = _plan(res, d, stat)

    class Clock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t
    clk = Clock()
    evz_ok = mp + ".e0"
    open(evz_ok, "w").write("0\n")
    saved_clock = B.DEFAULT_CLOCK[0]
    B.DEFAULT_CLOCK[0] = clk
    try:
        orig_read = M.read_uai

        def slow_read(p):
            clk.t += 700.0
            return orig_read(p)
        M.read_uai = slow_read
        try:
            rp = RP.replay(mp, "-", plan, wall_s=600)
        finally:
            M.read_uai = orig_read
        out["parse_delay"] = {"status": rp["status"], "reason": str(rp.get("reason"))[:120], "phases": (rp.get("budget") or {}).get("phases"),
                              "ok": rp["status"] == "REPLAY_RESOURCE_STOP" and "pars" in str(rp.get("reason"))}
        oks.append(out["parse_delay"]["ok"])
        orig_bind = PC._own_bind_residual

        def slow_bind(*a, **k):
            clk.t += 31.0
            return orig_bind(*a, **k)
        PC._own_bind_residual = slow_bind
        try:
            rl = RP.replay(mp, "-", plan, wall_s=600)
        finally:
            PC._own_bind_residual = orig_bind
        stops = [(s.get("kind"), s.get("where")) for s in (rl.get("budget") or {}).get("stops", [])]
        out["local_proof_timeout_31s"] = {"status": rl["status"], "reason": str(rl.get("reason"))[:140], "stops": stops[:2],
                                          "ok": rl["status"] == "REPLAY_RESOURCE_STOP" and any(k == "phase:check_local" for k, _w in stops)}
        oks.append(out["local_proof_timeout_31s"]["ok"])
        orig_ref = PC.own_statistic_reference

        def slow_ref(*a, **k):
            clk.t += 601.0
            return orig_ref(*a, **k)
        PC.own_statistic_reference = slow_ref
        try:
            rn = RP.replay(mp, "-", plan, wall_s=600)
        finally:
            PC.own_statistic_reference = orig_ref
        stops = [(s.get("kind"), s.get("where")) for s in (rn.get("budget") or {}).get("stops", [])]
        out["global_check_timeout_601s"] = {"status": rn["status"], "reason": str(rn.get("reason"))[:140], "stops": stops[:2],
                                            "phases": (rn.get("budget") or {}).get("phases"),
                                            "checker_status": (rn.get("checker") or {}).get("status"),
                                            "intervals_published": bool(rn.get("intervals")),
                                            "unverified_rows_as_partial_evidence": bool(((rn.get("partial_evidence") or {}).get("unverified_producer_rows"))),
                                            "ok": rn["status"] == "REPLAY_RESOURCE_STOP" and any(k == "wall" for k, _w in stops)
                                                  and (rn.get("checker") or {}).get("status") == "VERIFICATION_INCOMPLETE"
                                                  and not rn.get("intervals")
                                                  and bool(((rn.get("partial_evidence") or {}).get("unverified_producer_rows")))}
        oks.append(out["global_check_timeout_601s"]["ok"])
        evz = mp + ".e0"
        open(evz, "w").write("0\n")
        rd = tempfile.mkdtemp()
        orig_write = ARM._write

        def slow_write(rec, rundir, label):
            if str(rec.get("outcome", "")).startswith("CERTIFIED"):
                clk.t += 100.0
            return orig_write(rec, rundir, label)
        ARM._write = slow_write
        try:
            ar = ARM.run_arm("mf4", False, rd, wall=60, model_path=mp, evid_path=evz)
        finally:
            ARM._write = orig_write
        out["terminal_write_delay"] = {"outcome": ar["outcome"], "reason": str(ar.get("reason"))[:140],
                                       "receipt": ar.get("receipt"),
                                       "started_record_first": ar.get("started") is not None,
                                       "ok": ar["outcome"] == "RESOURCE_STOP" and "durable" in str(ar.get("reason"))
                                             and (ar.get("receipt") or {}).get("within_wall") is False}
        oks.append(out["terminal_write_delay"]["ok"])
        calls = {"n": 0}
        orig_rss = S._rss_bytes

        def rss_late():
            calls["n"] += 1
            return (3 << 40) if calls["n"] > 3 else orig_rss()
        S._rss_bytes = rss_late
        try:
            rr = RP.replay(mp, "-", plan, wall_s=600, cap_bytes=1 << 30)
        finally:
            S._rss_bytes = orig_rss
        out["rss_cap"] = {"status": rr["status"], "reason": str(rr.get("reason"))[:120],
                          "ok": rr["status"] == "REPLAY_RESOURCE_STOP" and "rss" in str(rr.get("reason"))}
        oks.append(out["rss_cap"]["ok"])
    finally:
        B.DEFAULT_CLOCK[0] = saved_clock
    # genuine zero-evidence and fully pinned proofs advanced PAST the wall are
    # resource outcomes with the proof kept as partial evidence, never published
    saved_clock = B.DEFAULT_CLOCK[0]
    B.DEFAULT_CLOCK[0] = clk
    try:
        z = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0,), card=(2,), table=[Fr(1), Fr(0)], origin=0),
                                                   M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(1), Fr(2), Fr(3), Fr(4)], origin=1)]).validate()
        orig_zp = PLN.zero_evidence_proof

        def slow_zp(*a, **k):
            clk.t += 0.150
            return orig_zp(*a, **k)
        PLN.zero_evidence_proof = slow_zp
        try:
            rz = PLN.solve(z, {0: 1}, wall_s=0.050, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        finally:
            PLN.zero_evidence_proof = orig_zp
        orig_pp = PLN.positive_evidence_proof

        def slow_pp(*a, **k):
            clk.t += 0.150
            return orig_pp(*a, **k)
        PLN.positive_evidence_proof = slow_pp
        try:
            rpin = PLN.solve(M.read_uai(mp), {0: 0, 1: 1, 2: 0, 3: 1}, wall_s=0.050, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        finally:
            PLN.positive_evidence_proof = orig_pp
        out["early_proofs_past_the_wall"] = {
            "zero_evidence": {"status": rz.status, "partial": (rz.partial_evidence or {}).get("status_before_limit_check"),
                              "remaining_s": (rz.budget or {}).get("remaining_s")},
            "fully_pinned": {"status": rpin.status, "partial": (rpin.partial_evidence or {}).get("status_before_limit_check"),
                             "intervals_withheld": not rpin.intervals},
            "ok": rz.status == "RESOURCE_STOP" and (rz.partial_evidence or {}).get("status_before_limit_check") == "ZERO_EVIDENCE_PROVED"
                  and rpin.status == "RESOURCE_STOP" and (rpin.partial_evidence or {}).get("status_before_limit_check") == "CERTIFIED_FALLBACK_ONLY"
                  and not rpin.intervals}
        oks.append(out["early_proofs_past_the_wall"]["ok"])
        # the ordinary zero-evidence ARM: plausible elapsed on the one clock; saved record and
        # returned result agree; the durable-write receipt is separate and points back
        mpz = _write_uai(z)
        evz = mpz + ".evid"
        open(evz, "w").write("1 0 1\n")
        rdz = tempfile.mkdtemp()
        az = ARM.run_arm("zero", False, rdz, wall=30, model_path=mpz, evid_path=evz)
        savedz = json.load(open(os.path.join(rdz, "arm_zero_baseline.json")))
        recz = json.load(open(os.path.join(rdz, "arm_zero_baseline.receipt.json")))
        out["arm_zero_evidence_timing"] = {"outcome": az["outcome"], "elapsed_s": az["elapsed_s"], "saved_elapsed_s": savedz["elapsed_s"],
                                           "receipt": recz, "saved_points_to_receipt": savedz.get("receipt_path"),
                                           "ok": az["outcome"] == "ZERO_EVIDENCE_PROVED" and 0 <= az["elapsed_s"] < 30
                                                 and savedz["elapsed_s"] == az["elapsed_s"] and recz["within_wall"] is True
                                                 and "elapsed_s_including_durable_write" not in savedz}
        oks.append(out["arm_zero_evidence_timing"]["ok"])
    finally:
        B.DEFAULT_CLOCK[0] = saved_clock
    # a successful arm under the real clock: saved record == returned result on every timing field
    rds = tempfile.mkdtemp()
    asu = ARM.run_arm("mf4", False, rds, wall=60, model_path=mp, evid_path=evz_ok)
    saveds = json.load(open(os.path.join(rds, "arm_mf4_baseline.json")))
    recs = json.load(open(os.path.join(rds, "arm_mf4_baseline.receipt.json")))
    out["arm_success_timing_consistent"] = {"outcome": asu["outcome"], "saved_elapsed_equals_returned": saveds["elapsed_s"] == asu["elapsed_s"],
                                            "receipt_within_wall": recs["within_wall"], "semantics": saveds.get("timing_semantics"),
                                            "ok": asu["outcome"].startswith("CERTIFIED") and saveds["elapsed_s"] == asu["elapsed_s"]
                                                  and recs["within_wall"] is True and saveds.get("timing_semantics") is not None
                                                  and "elapsed_s_including_durable_write" not in saveds}
    oks.append(out["arm_success_timing_consistent"]["ok"])
    # the ONE output policy at the publish-time stop (solve and replay): no
    # intervals, rows as unverified partial evidence; every replay result is
    # JSON-serializable (ordinary rows, partial evidence, diagnostics)
    saved_clock2 = B.DEFAULT_CLOCK[0]
    B.DEFAULT_CLOCK[0] = clk
    orig_check = B.Budget.check

    def late_publish(self, where=""):
        if where == "publish":
            clk.t += 700.0
        return orig_check(self, where)
    B.Budget.check = late_publish
    try:
        rpub = RP.replay(mp, "-", plan, wall_s=600)
        spub = PLN.solve(M.read_uai(mp), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        B.Budget.check = orig_check
        B.DEFAULT_CLOCK[0] = saved_clock2
    ser_ok = True
    for rr_ in (rpub, rn, RP.replay(mp, "-", plan)):
        try:
            json.dumps(rr_)
        except TypeError:
            ser_ok = False
    out["terminal_output_policy"] = {"solve_publish_stop": {"status": spub.status, "intervals": bool(spub.intervals),
                                                            "unverified_rows": bool((spub.partial_evidence or {}).get("unverified_producer_rows"))},
                                     "replay_publish_stop": {"status": rpub["status"], "intervals": bool(rpub.get("intervals")),
                                                             "unverified_rows": bool((rpub.get("partial_evidence") or {}).get("unverified_producer_rows"))},
                                     "replay_results_json_serializable": ser_ok,
                                     "ok": spub.status == "RESOURCE_STOP" and not spub.intervals and bool((spub.partial_evidence or {}).get("unverified_producer_rows"))
                                           and rpub["status"] == "REPLAY_RESOURCE_STOP" and not rpub.get("intervals")
                                           and bool((rpub.get("partial_evidence") or {}).get("unverified_producer_rows")) and ser_ok}
    oks.append(out["terminal_output_policy"]["ok"])
    # r26 (R25 review, S1): ordinary SEQUENTIAL calls never inherit another
    # invocation's law or ledger -- fresh invalid; certified A; A -> invalid;
    # A -> B stopped during normalization (injected clock); A -> clean B;
    # A -> B stopped at publication; A's output unchanged throughout
    def _own(o):
        led_ = (o.plan or {}).get("invocation_ledger") if o.plan else None
        return {"nvars": None if o.law is None else o.law.model.nvars,
                "hashes": None if o.law is None else [h[:12] for h in o.law.hashes],
                "attempts": None if not led_ else len(led_.get("attempts") or []),
                "events": None if not led_ else len(led_.get("construction_events") or []),
                "work": None if not led_ else led_.get("construction_ops_measured")}
    mA = M.Model(nvars=2, card=[2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(3), Fr(1), Fr(1), Fr(3)], origin=0)]).validate()
    mB = M.Model(nvars=3, card=[2, 2, 2], factors=[M.Factor(scope=(0, 1), card=(2, 2), table=[Fr(3), Fr(1), Fr(1), Fr(3)], origin=0),
                                                   M.Factor(scope=(1, 2), card=(2, 2), table=[Fr(2), Fr(1), Fr(1), Fr(2)], origin=1)]).validate()
    empty = {"nvars": None, "hashes": None, "attempts": None, "events": None, "work": None}
    fresh = PLN.solve(None)
    rA = PLN.solve(mA, {}, [0, 1], max_width=EPS, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    ownA = _own(rA)
    rowsA = json.dumps(rA.intervals, default=str)
    rInv = PLN.solve(None)
    tick = [0.0]

    def one_second_clock():
        tick[0] += 1.0
        return tick[0]
    B.DEFAULT_CLOCK[0] = one_second_clock
    try:
        rBn = PLN.solve(mB, {}, [0, 1, 2], max_width=EPS, wall_s=0.1, cap_bytes=1 << 30)
    finally:
        B.DEFAULT_CLOCK[0] = saved_clock
    rBc = PLN.solve(mB, {}, [0, 1, 2], max_width=EPS, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    rA2 = PLN.solve(mA, {}, [0, 1], max_width=EPS, wall_s=60, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    clk.t = 1000.0
    orig_check = B.Budget.check

    def late_publish(self, where=""):
        if where == "publish":
            clk.t += 700.0
        return orig_check(self, where)
    B.DEFAULT_CLOCK[0] = clk
    B.Budget.check = late_publish
    try:
        rBl = PLN.solve(mB, {}, [0, 1, 2], max_width=EPS, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        B.Budget.check = orig_check
        B.DEFAULT_CLOCK[0] = saved_clock
    own = {"fresh_invalid": _own(fresh), "A": ownA, "A_then_invalid": _own(rInv), "A_then_B_normalization_stop": _own(rBn),
           "A_then_B_clean": _own(rBc), "A_then_B_publish_stop": _own(rBl)}
    out["invocation_isolation"] = {
        "statuses": {"fresh_invalid": fresh.status, "A": rA.status, "A_then_invalid": rInv.status, "A_then_B_normalization_stop": rBn.status,
                     "A_then_B_clean": rBc.status, "A_then_B_publish_stop": rBl.status},
        "ownership": own,
        "normalization_stop_elapsed_s": (rBn.budget or {}).get("elapsed_s"),
        "A_output_unchanged": json.dumps(rA.intervals, default=str) == rowsA and _own(rA) == ownA,
        "ok": fresh.status == "INVALID_INPUT" and own["fresh_invalid"] == empty
              and rA.status.startswith("CERTIFIED") and ownA["nvars"] == 2 and ownA["attempts"]
              and rInv.status == "INVALID_INPUT" and not rInv.intervals and own["A_then_invalid"] == empty and rInv.law is not rA.law
              and rBn.status == "RESOURCE_STOP" and not rBn.intervals and own["A_then_B_normalization_stop"] == empty
              and float((rBn.budget or {}).get("elapsed_s") or 0) >= 1.0 and rBn.law is not rA.law
              and rBc.status.startswith("CERTIFIED") and own["A_then_B_clean"]["nvars"] == 3 and own["A_then_B_clean"]["hashes"] != ownA["hashes"]
              and rBc.plan["invocation_ledger"] is not rA.plan["invocation_ledger"]
              and rBl.status == "RESOURCE_STOP" and not rBl.intervals and bool((rBl.partial_evidence or {}).get("unverified_producer_rows"))
              and own["A_then_B_publish_stop"]["nvars"] == 3 and own["A_then_B_publish_stop"]["hashes"] == own["A_then_B_clean"]["hashes"]
              and own["A_then_B_publish_stop"]["attempts"] and rBl.law is not rA2.law
              and rBl.plan["invocation_ledger"] is not rA2.plan["invocation_ledger"]
              and json.dumps(rA.intervals, default=str) == rowsA}
    oks.append(out["invocation_isolation"]["ok"])
    # r26: a stop at the FINAL terminal check keeps the computed rows as partial evidence (solve and replay)
    clk.t = 1000.0

    def late_terminal(self, where=""):
        if where == "terminal":
            clk.t += 700.0
        return orig_check(self, where)
    B.DEFAULT_CLOCK[0] = clk
    B.Budget.check = late_terminal
    try:
        sT = PLN.solve(M.read_uai(mp), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
        rT = RP.replay(mp, "-", plan, wall_s=600)
    finally:
        B.Budget.check = orig_check
        B.DEFAULT_CLOCK[0] = saved_clock
    out["late_terminal_rows_retained"] = {"solve": {"status": sT.status, "intervals": bool(sT.intervals), "withheld": (sT.partial_evidence or {}).get("intervals_withheld"),
                                                    "unverified_rows": bool((sT.partial_evidence or {}).get("unverified_producer_rows"))},
                                          "replay": {"status": rT["status"], "intervals": bool(rT.get("intervals")), "withheld": (rT.get("partial_evidence") or {}).get("intervals_withheld"),
                                                     "unverified_rows": bool((rT.get("partial_evidence") or {}).get("unverified_producer_rows"))},
                                          "ok": sT.status == "RESOURCE_STOP" and not sT.intervals and (sT.partial_evidence or {}).get("intervals_withheld") is True
                                                and bool((sT.partial_evidence or {}).get("unverified_producer_rows"))
                                                and rT["status"] == "REPLAY_RESOURCE_STOP" and not rT.get("intervals")
                                                and (rT.get("partial_evidence") or {}).get("intervals_withheld") is True
                                                and bool((rT.get("partial_evidence") or {}).get("unverified_producer_rows"))}
    oks.append(out["late_terminal_rows_retained"]["ok"])
    bad = json.load(open(plan)); bad["request"]["card"] = {"0": 3}
    pb = os.path.join(d, "badcard.plan.json"); json.dump(bad, open(pb, "w"))
    rb = RP.replay(mp, "-", pb)
    bad2 = json.load(open(plan)); bad2["request"].pop("limits")
    pb2 = os.path.join(d, "badkeys.plan.json"); json.dump(bad2, open(pb2, "w"))
    rb2 = RP.replay(mp, "-", pb2)
    out["malformed_request"] = {"wrong_card": (rb["status"], str(rb.get("reason"))[:100]), "missing_key": (rb2["status"], str(rb2.get("reason"))[:100]),
                                "ok": rb["status"] == "REPLAY_REFUSED" and rb2["status"] == "REPLAY_REFUSED"}
    oks.append(out["malformed_request"]["ok"])
    # F6 entry flush and probe charging
    mc = _chain3()
    mpc = _write_uai(mc)
    resc, dc, _, _ = _solve(M.read_uai(mpc), wall)
    repc = _replay_fresh(mpc, _plan(resc, dc, "mixed:lowrank_combined"), wall)
    used = ((repc.get("budget") or {}).get("used") or {})
    led = resc.plan.get("invocation_ledger") or {}
    out["f6_entry_flush_and_probe_charging"] = {"metered_entries_measured": used.get("local_mass_entries"),
                                                "pricing_probe_entries_charged": led.get("pricing_probe_entries"),
                                                "ok": int(used.get("local_mass_entries") or 0) > 0 and int(led.get("pricing_probe_entries") or 0) > 0}
    oks.append(out["f6_entry_flush_and_probe_charging"]["ok"])
    out["memory_unavailable_not_zero"] = {"sampler_on_unknown_pid": PLAN._tree_rss_bytes(2 ** 22 + 12345),
                                          "ok": PLAN._tree_rss_bytes(2 ** 22 + 12345) is None}
    oks.append(out["memory_unavailable_not_zero"]["ok"])
    m3 = _f3_bipartite()
    Z, pt3 = O.exact_all_marginals(M.restrict(m3, {}))
    res3, d3, el3, _ = _solve(m3, wall)
    typed = dict(collections.Counter(x.get("typed") for x in res3.rejected))
    # INCUMBENT RETENTION under an injected clock: early research programs are
    # persisted, bound and priced; a LATER construction exhausts the local
    # allowance -- the early programs stay eligible and selection proceeds;
    # the paired GLOBAL exhaustion is a RESOURCE_STOP
    from mdi import routes as RT
    from tests.test_mdi_research import ring_of_blocks, w as _w
    mpr = _w(ring_of_blocks()[0])
    saved_clock = B.DEFAULT_CLOCK[0]
    B.DEFAULT_CLOCK[0] = clk
    orig_bs = RT.build_scales
    fired = {"n": 0}

    def late_slow_build(*a, **k):
        fired["n"] += 1
        if fired["n"] == 1:
            clk.t += 31.0                          # the FIRST regional build spends the whole local allowance
        return orig_bs(*a, **k)
    RT.build_scales = late_slow_build
    try:
        ri = PLN.solve(M.read_uai(mpr), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        RT.build_scales = orig_bs
        B.DEFAULT_CLOCK[0] = saved_clock
    ledi = ri.plan.get("invocation_ledger") or {}
    elig_research = [p["name"] for p in ri.prices if p["eligible"] and p["name"] != "identity"]
    out["incumbent_retained_after_local_stop"] = {
        "status": ri.status, "chosen": ri.plan.get("chosen"), "discovery_complete": ri.plan.get("discovery_complete"),
        "admitted_during_discovery": ledi.get("candidates_admitted_during_discovery"), "eligible_research_records": len(elig_research),
        "phase_stops": [s_ for s_ in (ri.budget or {}).get("stops", []) if str(s_.get("kind", "")).startswith("phase:")][:1],
        "arm_stops": [s_ for s_ in (ri.budget or {}).get("stops", []) if not str(s_.get("kind", "")).startswith("phase:")],
        "ok": ri.status.startswith("CERTIFIED") and ri.plan.get("discovery_complete") is False
              and int(ledi.get("candidates_admitted_during_discovery") or 0) >= 1 and len(elig_research) >= 1
              and not [s_ for s_ in (ri.budget or {}).get("stops", []) if not str(s_.get("kind", "")).startswith("phase:")]}
    oks.append(out["incumbent_retained_after_local_stop"]["ok"])
    B.DEFAULT_CLOCK[0] = clk
    fired["n"] = 0

    def late_global_build(*a, **k):
        fired["n"] += 1
        if fired["n"] == 1:
            clk.t += 700.0                         # past the whole-arm WALL
        return orig_bs(*a, **k)
    RT.build_scales = late_global_build
    try:
        rg_ = PLN.solve(M.read_uai(mpr), {}, wall_s=600, cap_bytes=1 << 30, plan_dir=tempfile.mkdtemp())
    finally:
        RT.build_scales = orig_bs
        B.DEFAULT_CLOCK[0] = saved_clock
    out["global_exhaustion_still_stops"] = {"status": rg_.status, "reason": str(rg_.reason)[:120],
                                            "stops": [(s_.get("kind"), s_.get("where")) for s_ in (rg_.budget or {}).get("stops", [])][:2],
                                            "ok": rg_.status == "RESOURCE_STOP" and not rg_.intervals}
    oks.append(out["global_exhaustion_still_stops"]["ok"])
    out["construction_fallback_f3"] = {"status": res3.status, "chosen": res3.plan.get("chosen"), "seconds": round(el3, 1),
                                       "discovery_complete": res3.plan.get("discovery_complete"), "typed_refusals": {str(k): v for k, v in typed.items()},
                                       "phase_used_s": res3.budget.get("phase_used_s"), "truth": _contains(res3.intervals, pt3),
                                       "ok": res3.status.startswith("CERTIFIED") and res3.plan.get("discovery_complete") is False
                                             and _contains(res3.intervals, pt3) and _width(res3.intervals) <= EPS
                                             and (res3.budget.get("phase_used_s") or {}).get("construction", 0) <= 31.0}
    oks.append(out["construction_fallback_f3"]["ok"])
    out["ok"] = all(oks)
    return out


# ------------------------------------------------------------------ P9

def row_p9_truth_predicate(wall):
    """P9: the independent truth predicate FAILS on empty rows, a disguised
    [0, 1] row, a wrong cardinality, a missing request, a key outside the
    request and a reported width that disagrees with the endpoints; it passes
    only the genuine verified row."""
    from mdi import model as M, oracle as O
    mp = _mean_field_path(4, 0.30)
    m = M.read_uai(mp)
    Z, pt = O.exact_all_marginals(M.restrict(m, {}))
    q = sorted(M.restrict(m, {}).free)
    res, d, _, _ = _solve(m, wall)
    rep = _replay_fresh(mp, _plan(res, d, res.plan["chosen"]), wall)
    good = _row_ok(rep, pt, q)
    cases = {}
    r1 = copy.deepcopy(rep); r1["intervals"] = {}
    cases["empty_rows"] = _row_ok(r1, pt, q)["ok"]
    r2 = copy.deepcopy(rep); r2["intervals"]["0"] = [["0", "1"], ["0", "1"]]
    cases["disguised_0_1_row"] = _row_ok(r2, pt, q)["ok"]
    r3 = copy.deepcopy(rep); r3["intervals"]["0"] = r3["intervals"]["0"][:1]
    cases["wrong_cardinality"] = _row_ok(r3, pt, q)["ok"]
    r4 = copy.deepcopy(rep); r4.pop("request")
    cases["missing_request"] = _row_ok(r4, pt, q)["ok"]
    r5 = copy.deepcopy(rep); r5["intervals"]["7"] = [["0", "1"], ["0", "1"]]
    cases["key_outside_request"] = _row_ok(r5, pt, q)["ok"]
    r6 = copy.deepcopy(rep); r6["max_width"] = "1/1000000"
    cases["reported_width_disagrees"] = _row_ok(r6, pt, q)["ok"]
    r7 = copy.deepcopy(rep); r7["intervals"]["0"] = [["1/2", "1/3"], r7["intervals"]["0"][1]]
    cases["inverted_endpoints"] = _row_ok(r7, pt, q)["ok"]
    r8 = copy.deepcopy(rep); r8["intervals"]["1"] = [["0.45", "0.46"], ["0.54", "0.55"]]
    cases["rows_missing_truth"] = _row_ok(r8, pt, q)["ok"]
    return {"genuine_row": good, "mutations_fail": cases, "raw": _raw(rep),
            "ok": good["ok"] and not any(cases.values())}


ROWS = [
    ("P1 proof boundary: exact original triangle (clean 6; marker/residual swaps; working-input alias; read-only types; retained request; occurrences)", row_p1_triangle),
    ("P2 proof boundary: exact original F6 chain (15/25/13/5; shared gf2 and gf3 faults; conservative witness; r19 grid gate)", row_p2_chain),
    ("P3 pure-sign rank-2 Gaussian and Fourier", row_p3_pure_sign_rank2),
    ("P4 statistic family: categorical, higher-arity/non-binary, hard zero, disconnected", row_p4_statistic_family),
    ("P5 regional L1/L2, composed statistic/gaussian (branch capability via the saved program; current-discovery coverage separate), nonzero deletion", row_p5_regional_deletion_composed),
    ("P6 saved-program authority: strict witnesses, identity tuples, effective request v3, collision, schema, input contract, structural validity, budget start", row_p6_saved_program_authority),
    ("P7 execution contract: pre-admission applicability, one meter for producer+checker, deadline, MPFR, priced work, truthful ledger", row_p7_execution_contract),
    ("P8 lifecycle: injected clock, early proofs past the wall, one terminal path and output policy, arm timing, incumbent retention vs global stop, F3", row_p8_lifecycle),
    ("P9 the independent truth predicate fails every disguise", row_p9_truth_predicate),
]


def run(out_path, wall=900.0, only=None):
    import signal, traceback
    rows = []
    for name, fn in ROWS:
        if only and not any(k in name for k in only):
            continue
        t = time.time()
        print("[acceptance] %s ..." % name[:90], flush=True)

        def _alarm(signum, frame):
            raise TimeoutError("row exceeded its %ds wall" % int(wall))
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(int(wall))
        try:
            res = fn(wall)
            status = "PASS" if res.get("ok") else "FAIL"
        except TimeoutError as e:
            res = {"ok": False, "timeout": str(e)}
            status = "TIMEOUT"
        except Exception as e:
            res = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "traceback": traceback.format_exc()[-1500:]}
            status = "ERROR"
        finally:
            signal.alarm(0)
        el = time.time() - t
        print("[acceptance] %-96s %-7s %.1fs" % (name[:96], status, el), flush=True)
        rows.append({"row": name, "status": status, "seconds": round(el, 1), "result": json.loads(json.dumps(res, default=str))})
    summary = {"rows": rows, "passed": sum(1 for r in rows if r["status"] == "PASS"),
               "failed": sum(1 for r in rows if r["status"] != "PASS"), "per_row_wall_s": wall,
               "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "acceptance": "expected keys and cardinalities derived from the record's request object; endpoint strings parsed "
                             "as exact rationals; 0 <= lower <= upper <= 1; width recomputed from the endpoints and compared "
                             "with the reported one; exact rational truth containment against the independent enumeration; "
                             "empty rows, disguised [0,1] rows and missing requests fail; raw replay rows persisted per row; "
                             "no external input opened; BLOCKED/SKIP never satisfy"}
    with open(out_path, "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "acceptance_matrix.json"
    wall = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0
    only = sys.argv[3:] or None
    s = run(out, wall, only)
    print(json.dumps({k: v for k, v in s.items() if k != "rows"}))
    sys.exit(0 if s["failed"] == 0 else 1)
