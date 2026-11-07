"""COMMON MODEL CENSUS (diagnostic spec): uniform, bounded static characterization of every accessible case at the ORIGINAL and EVIDENCE-SLICED
stages, plus complete CBI obstruction profiles (every predicate evaluated independently, never stopping at the first refusal), bounded
forced-state / relation discovery with existing procedures, and primal-graph structure with a min-fill ordering estimate. Exact rationals
throughout; no thresholding of small values; no exponential enumeration. Each expensive sub-procedure has a fixed subcap and records
coverage. Writes CENSUS.jsonl (one record per case) and CENSUS_SCHEMA.json.   python bench/census.py SWEEP_DIR [PER_CASE_CAP_S]"""
from __future__ import annotations
import os, sys, json, time, math, collections, itertools, hashlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U

EXTRACTOR_VERSION = "census-2026-11-07-v1"
SUBCAP = {"minfill_s": 3.0, "recognize_s": 5.0, "prove_forced_s": 3.0, "gauge_s": 2.0}


def q(xs):
    """quantiles + extremes of a numeric list (floats), or None."""
    if not xs:
        return None
    xs = sorted(xs); n = len(xs)
    pick = lambda f: xs[min(n - 1, max(0, int(round(f * (n - 1)))))]
    return {"n": n, "min": xs[0], "q25": pick(0.25), "median": pick(0.5), "q75": pick(0.75), "max": xs[-1], "mean": sum(xs) / n}


def deadline_from(t0, cap):
    def d():
        if time.monotonic() - t0 > cap:
            raise TimeoutError("subcap %.1f s" % cap)
    return d


def stage_stats(factors, card, nvars, fixed):
    """statistics of a factor set at one stage; `fixed` = variables sliced out (evidence + proved forced), tables are the sliced tables."""
    tabs = []                                                     # (scope tuple of remaining vars, dict conf -> Fr)
    tot = 0; largest = 0; zeros = 0; posmin = None; posmax = None; numbits = []; denbits = []; dup = collections.Counter(); arity = collections.Counter()
    unary = 0; scalar = 0; zero_const = 0; sep = 0; sep_tested = 0; nonsep_pair = 0
    for f in factors:
        sc = tuple(v for v in f.scope if v not in fixed); fixed_part = {v: fixed[v] for v in f.scope if v in fixed}
        n = 1
        for v in sc:
            n *= card[v]
        tot += n; largest = max(largest, n); arity[len(sc)] += 1; dup[tuple(sorted(sc))] += 1
        vals = []
        for conf in itertools.product(*[range(card[v]) for v in sc]):
            a = dict(zip(sc, conf)); a.update(fixed_part); vals.append(f.at(a))
        for x in vals:
            if x == 0:
                zeros += 1
            else:
                posmin = x if posmin is None or x < posmin else posmin; posmax = x if posmax is None or x > posmax else posmax
                numbits.append(x.numerator.bit_length()); denbits.append(x.denominator.bit_length())
        if len(sc) == 0:
            scalar += 1; zero_const += (1 if vals[0] == 0 else 0)
        elif len(sc) == 1:
            unary += 1
        elif len(sc) == 2:
            # separability (rank one) of a pairwise table, exact: all 2x2 minors vanish on the positive support; tested only when all entries positive
            cu, cv = card[sc[0]], card[sc[1]]
            if all(x > 0 for x in vals):
                sep_tested += 1; M = [[vals[i * cv + j] for j in range(cv)] for i in range(cu)]
                rank1 = all(M[i][j] * M[0][0] == M[i][0] * M[0][j] for i in range(cu) for j in range(cv))
                sep += 1 if rank1 else 0; nonsep_pair += 0 if rank1 else 1
    return {"factor_occurrences": len(factors), "arity_histogram": {str(k): v for k, v in sorted(arity.items())}, "max_arity": max(arity) if arity else 0,
            "duplicate_scopes": sum(1 for k, v in dup.items() if v > 1 and len(k) > 0), "duplicate_scope_occurrences": sum(v for k, v in dup.items() if v > 1 and len(k) > 0),
            "table_entries_total": tot, "table_entries_largest": largest, "table_bytes_binary64_equivalent": 8 * tot, "exact_zeros": zeros, "support_density": (1 - zeros / tot) if tot else None,
            "scalar_factors": scalar, "zero_constants": zero_const, "unary_factors": unary, "pairwise_positive_tested_for_separability": sep_tested, "pairwise_separable_rank_one": sep, "pairwise_positive_non_separable": nonsep_pair,
            "positive_log10_dynamic_range": (math.log10(float(posmax / posmin)) if posmin else None), "numerator_bits": q(numbits), "denominator_bits": q(denbits)}


def graph_stats(scopes, nvars, card, free, cap_s):
    """PRIMAL graph over the FREE variables: components, degrees, leaves, isolates, cycle rank, min-fill ordering estimate (induced width,
    peak intermediate table entries, domain-weighted), log2 state space. Named: primal graph of the sliced factor scopes."""
    adj = {v: set() for v in free}
    for sc in scopes:
        sc = [v for v in sc if v in adj]
        for a in sc:
            for b in sc:
                if a != b:
                    adj[a].add(b)
    seen = set(); comps = []
    for v in free:
        if v in seen:
            continue
        st = [v]; comp = []
        while st:
            x = st.pop()
            if x in seen:
                continue
            seen.add(x); comp.append(x); st.extend(adj[x])
        comps.append(len(comp))
    deg = [len(adj[v]) for v in free]; E = sum(deg) // 2; V = len(free); C = len(comps)
    out = {"graph": "primal graph of the evidence-sliced factor scopes over free variables", "vertices": V, "edges": E, "components": C, "component_sizes": q([float(c) for c in comps]), "largest_component": max(comps) if comps else 0,
           "degree": q([float(d) for d in deg]), "leaves": sum(1 for d in deg if d == 1), "isolates": sum(1 for d in deg if d == 0), "cycle_rank": E - V + C,
           "log2_state_space": sum(math.log2(card[v]) for v in free)}
    # min-fill ordering (bounded): induced width and domain-weighted peak table
    t0 = time.monotonic(); dl = deadline_from(t0, cap_s); alive = set(free); A = {v: set(adj[v]) for v in free}; width = 0; peak_log2 = 0.0; done = 0
    try:
        while alive:
            dl(); best = None
            for v in alive:
                nb = A[v]; fill = 0
                for a in nb:
                    for b in nb:
                        if a < b and b not in A[a]:
                            fill += 1
                key = (fill, len(nb), v)
                if best is None or key < best:
                    best = key
            v = best[2]; nb = A[v]; width = max(width, len(nb)); peak_log2 = max(peak_log2, math.log2(card[v]) + sum(math.log2(card[u]) for u in nb))
            for a in nb:
                for b in nb:
                    if a != b:
                        A[a].add(b)
                A[a].discard(v)
            alive.discard(v); done += 1
        out["minfill"] = {"status": "complete", "induced_width_estimate": width, "peak_table_log2_entries_estimate": peak_log2, "seconds": time.monotonic() - t0, "note": "an ordering estimate, not optimal treewidth"}
    except TimeoutError:
        out["minfill"] = {"status": "partial", "eliminated": done, "of": V, "induced_width_so_far": width, "peak_table_log2_so_far": peak_log2, "seconds": time.monotonic() - t0}
    return out


def cbi_obstruction_profile(m, ev, fixed):
    """EVERY CBI predicate evaluated independently on the sliced model (no early stop): nonbinary free variables, remaining arity, zero patterns of
    binary pairwise tables, separability, rational-square cross-ratios, GLOBAL gauge consistency (parity union-find on the attractive / repulsive
    binary pairs with square cross-ratios) -- local obstructions vs the global contradiction, with compact witness indexes."""
    from bench.cbi_adapter import _sqrt_rational
    free = [v for v in range(m.nvars) if v not in fixed]
    nonbin = [v for v in free if m.card[v] != 2]
    arity_hist = collections.Counter(); hi_witness = []; pair_tabs = {}
    for f in m.factors:
        sc = tuple(v for v in f.scope if v not in fixed); arity_hist[len(sc)] += 1
        if len(sc) >= 3 and len(hi_witness) < 5:
            hi_witness.append({"factor": f.index, "remaining_scope": list(sc)})
        if len(sc) == 2 and m.card[sc[0]] == 2 and m.card[sc[1]] == 2:
            u, v = sc; key = (min(u, v), max(u, v)); fx = {w: fixed[w] for w in f.scope if w in fixed}
            t = []
            for x in range(2):
                for y in range(2):
                    a = {key[0]: x, key[1]: y}; a.update(fx); t.append(f.at(a))
            pair_tabs.setdefault(key, [Fr(1)] * 4); pair_tabs[key] = [p * s for p, s in zip(pair_tabs[key], t)]
    zero_pat = collections.Counter(); sep = 0; nonsquare = 0; square_att = 0; square_rep = 0; witnesses = {"nonsquare": [], "zero_pattern": [], "nonbinary": nonbin[:5], "high_arity": hi_witness}
    parent = {}; par = {}
    def find(x):
        p = 0
        while parent.get(x, x) != x:
            p ^= par[x]; x = parent[x]
        return x, p
    def union(a, b, want):
        ra, pa = find(a); rb, pb = find(b)
        if ra == rb:
            return (pa ^ pb) == want
        parent[ra] = rb; par[ra] = pa ^ pb ^ want; return True
    frustrated = 0; frust_witness = []
    for (u, v), t in pair_tabs.items():
        a, b, c, d = t
        if all(x > 0 for x in t):
            C = (a * d) / (b * c)
            if C == 1:
                sep += 1; continue
            if _sqrt_rational(C if C >= 1 else 1 / C) is None:
                nonsquare += 1
                if len(witnesses["nonsquare"]) < 3:
                    witnesses["nonsquare"].append({"pair": [u, v], "cross_ratio": str(C)})
                continue
            if C >= 1:
                square_att += 1
            else:
                square_rep += 1
            if not union(u, v, 0 if C >= 1 else 1):
                frustrated += 1
                if len(frust_witness) < 3:
                    frust_witness.append([u, v])
        else:
            pat = "".join("1" if x > 0 else "0" for x in t); zero_pat[pat] += 1
            if pat != "1001" and len(witnesses["zero_pattern"]) < 3:
                witnesses["zero_pattern"].append({"pair": [u, v], "pattern": pat})
    binary_pairs = len(pair_tabs); equality = zero_pat.get("1001", 0); other_zero = sum(v for k, v in zero_pat.items() if k != "1001")
    preds = {"nonbinary_free_variables": len(nonbin), "free_variables": len(free), "remaining_arity_histogram": {str(k): v for k, v in sorted(arity_hist.items())}, "factors_arity_ge3_after_slicing": sum(v for k, v in arity_hist.items() if k >= 3),
             "binary_pairwise_merged_scopes": binary_pairs, "separable_cross_ratio_1": sep, "equality_diagonal_only": equality, "other_zero_patterns": other_zero, "zero_pattern_histogram": dict(zero_pat),
             "nonsquare_cross_ratio": nonsquare, "square_cross_ratio_attractive": square_att, "square_cross_ratio_repulsive": square_rep, "gauge_parity_contradictions": frustrated,
             "gauge_note": "parity union-find over the square-cross-ratio pairs; a contradiction is a GLOBAL obstruction (odd repulsive cycle) distinct from the local ones"}
    blockers = {"nonbinary domains": len(nonbin) > 0, "remaining high arity": preds["factors_arity_ge3_after_slicing"] > 0, "incompatible zero pattern": other_zero > 0, "nonsquare rational cross-ratio": nonsquare > 0, "inconsistent sign gauges": frustrated > 0}
    return {"predicates": preds, "blockers_active": [k for k, v in blockers.items() if v], "blocker_count": sum(blockers.values()), "all_predicates_pass_for_current_adapter": not any(blockers.values()), "witnesses": {**witnesses, "frustrated_pairs": frust_witness}}


def main(S, per_case_cap):
    from bench import cbi_adapter as AD
    man = json.load(open(os.path.join(S, "CAMPAIGN_MANIFEST.json"))); inv = {c["case"]: c for c in json.load(open(os.path.join(S, "INVENTORY.json")))["cases"]}
    cases = sorted({c["case"] for c in man["cells"]}, key=lambda x: (inv[x]["family"], x)); out_p = os.path.join(S, "diag_2026-11-07", "CENSUS.jsonl"); os.makedirs(os.path.dirname(out_p), exist_ok=True)
    # inaccessible intended slots are recorded too
    sel = json.load(open(os.path.join(S, "PANEL_SELECTION.json")))
    with open(out_p, "w") as fo:
        for fam, sh in sel["shortfalls"].items():
            for k in range(sh["available"], sh["target"]):
                fo.write(json.dumps({"case": "%s_slot_%d_INACCESSIBLE" % (fam, k + 1), "family": fam, "accessible": False, "reason": "no further distinct case in the official archives", "extractor_version": EXTRACTOR_VERSION}) + "\n")
        for case in cases:
            t_case = time.monotonic(); row = inv[case]; mp = os.path.join(S, row.get("committed_model_path", row["model_path"])); ep = os.path.join(S, row.get("committed_evidence_path", row["evidence_path"]))
            m = U.read_model(mp); ev = U.read_evidence(ep); rec = {"case": case, "family": row["family"], "accessible": True, "anchor": any(c.get("anchor") for c in man["cells"] if c["case"] == case), "extractor_version": EXTRACTOR_VERSION,
                                                                 "model_sha256": row["canonical_model_sha256"], "evidence_sha256": row["canonical_evidence_sha256"], "net_type": m.net_type, "variables": m.nvars, "evidence_count": len(ev),
                                                                 "domain_histogram": {str(k): v for k, v in sorted(collections.Counter(m.card).items())}, "queries_complete_mar_coordinates": sum(m.card[v] for v in range(m.nvars) if v not in ev), "unobserved_variables": m.nvars - len(ev), "costs_s": {}}
            t = time.monotonic(); rec["original"] = stage_stats(m.factors, m.card, m.nvars, {}); rec["costs_s"]["original_stats"] = time.monotonic() - t
            t = time.monotonic(); rec["sliced"] = stage_stats(m.factors, m.card, m.nvars, dict(ev)); rec["costs_s"]["sliced_stats"] = time.monotonic() - t
            # forced states by the adapter's bounded zero-exclusion replay (existing procedure), capped
            t = time.monotonic()
            try:
                proved, zw = AD.prove_forced(m, ev); rec["forced_states"] = {"procedure": "bench.cbi_adapter.prove_forced (unary-slice zero exclusion, fixpoint)", "beyond_evidence": len(proved) - len(ev), "zero_partition_witness": zw, "fixed_total": len(proved), "status": "complete"}
            except Exception as ex:
                proved = dict(ev); rec["forced_states"] = {"status": "error", "error": str(ex)[:120]}
            rec["costs_s"]["prove_forced"] = time.monotonic() - t
            # existing MDI quotient recognition (forced + equality / complement), with its own 5 s wall cap, on the evidence-restricted model
            t = time.monotonic()
            try:
                from mdi import model as MM, quotient as QT
                mm = MM.read_uai(mp); mev = MM.read_evidence(ep, mm); r = MM.restrict(mm, mev)
                decl = QT.recognize(r.factors, r.free, r.card, wall_cap_s=SUBCAP["recognize_s"])
                rec["relations_mdi_quotient"] = {"procedure": "mdi.quotient.recognize (exact-zero fixpoint; %.0f s cap)" % SUBCAP["recognize_s"], "fixed": len(decl["fixed"]), "merged": len(decl["merged"]), "free_after": decl.get("n_free"), "free_before": len(r.free), "recognition": decl.get("recognition"), "status": "complete"}
            except Exception as ex:
                rec["relations_mdi_quotient"] = {"status": type(ex).__name__, "detail": str(ex)[:160]}
            rec["costs_s"]["mdi_recognize"] = time.monotonic() - t
            # transformed stage (evidence + proved forced states) statistics
            t = time.monotonic(); rec["sliced_plus_forced"] = stage_stats(m.factors, m.card, m.nvars, proved) if len(proved) > len(ev) else "same as sliced (no forced state beyond evidence)"; rec["costs_s"]["forced_stage_stats"] = time.monotonic() - t
            # graph
            t = time.monotonic(); free = [v for v in range(m.nvars) if v not in proved]; rec["graph_sliced_plus_forced"] = graph_stats([f.scope for f in m.factors], m.nvars, m.card, free, SUBCAP["minfill_s"]); rec["costs_s"]["graph"] = time.monotonic() - t
            # CBI obstruction profile (all predicates)
            t = time.monotonic(); rec["cbi_obstructions"] = cbi_obstruction_profile(m, ev, proved); rec["costs_s"]["cbi_obstructions"] = time.monotonic() - t
            rec["costs_s"]["total"] = time.monotonic() - t_case; rec["within_per_case_cap"] = rec["costs_s"]["total"] <= per_case_cap
            fo.write(json.dumps(rec, default=str) + "\n"); fo.flush()
            print("%-22s %-16s vars %4d ev %3d | forced+%d | q-rel fixed %s merged %s | width~%s | blockers %s | %.1fs" % (case, row["family"], m.nvars, len(ev), rec["forced_states"].get("beyond_evidence", -1), rec["relations_mdi_quotient"].get("fixed"), rec["relations_mdi_quotient"].get("merged"), rec["graph_sliced_plus_forced"]["minfill"].get("induced_width_estimate", rec["graph_sliced_plus_forced"]["minfill"].get("induced_width_so_far")), rec["cbi_obstructions"]["blockers_active"], rec["costs_s"]["total"]), flush=True)
    schema = {"extractor_version": EXTRACTOR_VERSION, "record": "one JSON per case (plus one per inaccessible intended slot)", "stages": {"original": "raw factors", "sliced": "evidence applied", "sliced_plus_forced": "evidence + states proved forced by prove_forced"},
              "fields": {"stage_stats": ["factor_occurrences", "arity_histogram", "duplicate_scopes", "table_entries_total/largest", "table_bytes_binary64_equivalent", "exact_zeros", "support_density", "scalar/zero_constants/unary", "pairwise separability (exact rank-one, positive tables only)", "positive_log10_dynamic_range", "numerator/denominator bit-length quantiles"],
                         "graph": "primal graph of sliced+forced scopes: components, degrees, leaves, isolates, cycle rank, min-fill estimate (induced width, peak table log2, 3 s subcap), log2 state space",
                         "forced_states": "bench.cbi_adapter.prove_forced", "relations_mdi_quotient": "mdi.quotient.recognize (5 s cap)", "cbi_obstructions": "all predicates independently + witnesses + gauge parity contradictions"},
              "typed_missing": ["status partial/error with detail", "None = not applicable", "not instrumented is never written as 0"], "per_case_cap_s": per_case_cap, "subcaps_s": SUBCAP}
    json.dump(schema, open(os.path.join(S, "diag_2026-11-07", "CENSUS_SCHEMA.json"), "w"), indent=1)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 10.0)
