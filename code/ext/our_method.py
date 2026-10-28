"""Attempt the external problems with our existing certified method.

This module performs the ADMISSION CHECK only. Our method's model is generated
internally from (n, seed, b); there is no path that accepts external factor
tables. Per the brief we must NOT load arbitrary factors into the H4 runner
while retaining H4 validity claims, and must NOT bypass domain checks to create
an invalid certified mode.

So this records, per problem, the concrete blocking reason in the brief's four
categories and returns an UNSUPPORTED_MODEL outcome with its evidence. It
deliberately runs no numerical work: the brief says to retain unsupported
outcomes without expensive numerical work when applicable.
"""
from __future__ import annotations
import os, sys, json, time, inspect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ext import uai

PKT = "/tmp/tep/three_external_problems/inputs"


def admission_check(problem):
    """Structural admission against the H4 contract. Read-only; no solver call."""
    t0 = time.time()
    p = os.path.join(PKT, problem)
    m = uai.read_model(p + ".uai")
    ev = uai.read_evidence(p + ".uai.evid")
    t_parse = time.time() - t0

    # Verified facts about our own method, read from source at run time so the
    # record cannot drift from the code.
    from h4a.model import Model as H4Model
    sig = inspect.signature(H4Model.__init__)
    ctor_params = [x for x in sig.parameters if x != "self"]
    h4_src = inspect.getsource(H4Model)

    blockers = []

    # (a) absent input adapter -- the constructor admits no external factors
    if set(ctor_params) <= {"n", "seed", "b"}:
        blockers.append({
            "category": "a_absent_input_adapter",
            "detail": "h4a.model.Model.__init__ takes only %s; every factor is generated "
                      "internally via SHA-256 from the seed. No constructor argument, "
                      "setter or reader anywhere in h4a/ or h4q/ accepts external factor "
                      "tables." % ctor_params,
            "blocking": True})

    # (b) unimplemented mathematical components
    cards = sorted(set(m.card))
    if any(c != 2 for c in cards):
        nb = sum(1 for c in m.card if c != 2)
        blockers.append({
            "category": "b_unimplemented_component",
            "detail": "%d of %d variables are non-binary (cardinalities %s). Our model, "
                      "recurrence and all three native kernels are binary +/-1 spin "
                      "throughout (Model.allowed is ((pin,) if pinned else (-1,1))). "
                      "Multi-state support is a mathematical extension, not plumbing."
                      % (nb, m.nvars, cards),
            "blocking": True})

    arities = sorted(set(len(f.scope) for f in m.factors))
    hi = [a for a in arities if a > 2]
    if hi:
        nhi = sum(1 for f in m.factors if len(f.scope) > 2)
        blockers.append({
            "category": "b_unimplemented_component",
            "detail": "%d of %d factors have arity > 2 (arities present: %s). Our residual "
                      "handles only pairwise factors at spans 1 and 2."
                      % (nhi, len(m.factors), arities),
            "blocking": True})

    pairs = [tuple(sorted(f.scope)) for f in m.factors if len(f.scope) == 2]
    spans = sorted(set(abs(b - a) for a, b in pairs))
    offchain = [s for s in spans if s not in (1, 2)]
    if offchain:
        blockers.append({
            "category": "b_unimplemented_component",
            "detail": "pairwise factor spans |i-j| include %s, outside the chain spans "
                      "{1,2}. The H4 recurrence, bag structure [[i,i+1,i+2]] and FFBS "
                      "factorization all assume a 1-D chain with a width-2 residual. A "
                      "general-treewidth backend (or a proved chain embedding with "
                      "accounted error) is a new inference backend."
                      % (offchain[:8] + (["..."] if len(offchain) > 8 else [])),
            "blocking": True})

    zeros = sum(1 for f in m.factors for t in f.table if t == 0)
    if zeros:
        blockers.append({
            "category": "b_unimplemented_component",
            "detail": "%d hard zero factor entries. Our certified interval arithmetic was "
                      "never proved against a deterministic-zero model, and the brief "
                      "forbids softening zeros (which is exactly what the ARB baseline "
                      "does at model/function.go:131)." % zeros,
            "blocking": True})

    # The H4 family also fixes factor VALUES; arbitrary tables are outside it.
    distinct = set()
    for f in m.factors:
        if len(f.scope) == 2:
            distinct.add(tuple(str(x) for x in f.table))
    if len(distinct) > 2:
        blockers.append({
            "category": "b_unimplemented_component",
            "detail": "%d distinct pairwise tables. The H4 family admits only the 9/1 "
                      "(adjacent) and 3/1 (distance-two) sign-rule patterns; factor values "
                      "are not free parameters." % len(distinct),
            "blocking": True})

    # (c) proved domain -- stated explicitly as NOT the binding constraint
    domain = {
        "category": "c_outside_proved_domain",
        "detail": "Not evaluable and NOT the binding constraint. The proved bound is "
                  "|a_i| < 10 on the H4 internal integer fields (h4q/pilot.py:50-51). "
                  "An external UAI model has no a_i, so the bound is neither met nor "
                  "violated. Recorded so it is not confused with a domain refusal.",
        "blocking": False}

    # (d) resource failure -- explicitly none
    resource = {
        "category": "d_resource_failure",
        "detail": "None. No solver process was launched for this cell, so no timeout and "
                  "no memory stop occurred. The outcome is a model-support finding, not a "
                  "resource finding, and is not evidence of inference hardness: both "
                  "baselines run on this instance.",
        "blocking": False}

    return {
        "problem": problem,
        "method": "ours (H4 certified pipeline)",
        "outcome": "UNSUPPORTED_MODEL",
        "nvars": m.nvars,
        "nfactors": len(m.factors),
        "evidence_vars": len(ev),
        "cardinalities_present": cards,
        "arities_present": arities,
        "pairwise_spans": spans[:12],
        "hard_zeros": zeros,
        "distinct_pairwise_tables": len(distinct),
        "h4_constructor_params": ctor_params,
        "blockers": blockers,
        "non_blockers": [domain, resource],
        "numerical_work_performed": "none (brief: retain unsupported outcomes without "
                                    "expensive numerical work when applicable)",
        "certificate": {
            "coverage_of_requested_coordinates": 0.0,
            "requested_coordinates": sum(m.card[v] for v in range(m.nvars) if v not in ev),
            "covered_coordinates": 0,
            "max_interval_width": None,
            "independent_checker_status": "NOT_RUN (no admissible model to check)",
            "guarantee_class": "NONE -- the instance is outside the proved contract. No "
                               "certified or heuristic output is claimed.",
            "target_width_requested": 0.01},
        "stages": {"input_parse_s": t_parse, "admission_check_s": None},
        "cost_s": None}


if __name__ == "__main__":
    problem, rundir = sys.argv[1], os.path.abspath(sys.argv[2])
    os.makedirs(rundir, exist_ok=True)
    t0 = time.time()
    rec = admission_check(problem)
    el = time.time() - t0
    rec["stages"]["admission_check_s"] = el - rec["stages"]["input_parse_s"]
    rec["cost_s"] = el
    rec["elapsed_s"] = el
    rec["peak_tree_rss_kib"] = None
    out = os.path.join(rundir, "ours_%s_record.json" % problem)
    json.dump(rec, open(out, "w"), indent=2)
    print("%s: %s in %.3fs, %d blocking reasons" % (problem, rec["outcome"], el, len(rec["blockers"])))
    for b in rec["blockers"]:
        print("   [%s] %s" % (b["category"], b["detail"][:110]))
