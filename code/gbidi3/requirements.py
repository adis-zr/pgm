"""REQUIREMENTS matrix of GENERAL_BIDI_COMPLETE_V3 (section 18 of the operative brief, revision COMPLETE-1, sha256 af2e29bf...).

Written BEFORE the implementation; every mandatory row starts ABSENT and is advanced to IMPLEMENTED_UNQUALIFIED / QUALIFIED only by
`gbidi3.requirements.update(...)` calls made from the qualification driver with the evidence paths of the controls that fired.
NOT_IMPLEMENTED is a status only the OPTIONAL rows may carry. The readable matrix (REQUIREMENTS.md) and the JSON are regenerated together.

    python -m gbidi3.requirements RUN_DIR            # writes RUN_DIR/REQUIREMENTS.json + REQUIREMENTS.md from the current table
"""
from __future__ import annotations
import os, sys, json, time

STATUSES = ("ABSENT", "IMPLEMENTED_UNQUALIFIED", "QUALIFIED", "BLOCKED_WITH_REASON", "NOT_IMPLEMENTED")

# requirement id -> row; `entry` names the production code; `invariant` the semantic contract; `activating` / `rejecting` the controls that
# must FIRE (branch-activation evidence), `oracle` the independent truth, `counter` the measured work counter. Status fields are filled by update().
MANDATORY = [
 ("M01", "All source classes and original queries", "§2", "gbidi3.source (strict grammar, exact rationals, occurrence ids, scalars, duplicates); gbidi3.executor original rows via decoder",
  "every original variable publishes every original state through the validated decoder; malformed input is typed INVALID_INPUT; Z=0 / zero numerator / zero lower normalizer / underflow distinguished",
  "C06 arity/cardinality, C07 zero safety, C10 duplicate factors, C12 requested normalized leaf, C21 zero-variable + inconsistent scalar tasks", "parser rejection suite (duplicate scope variable, duplicate evidence, truncated/extra table, trailing tokens, bool/float/string states)", "gbidi3.oracle brute force on ORIGINAL factors", "source_entries_read"),
 ("M02", "Trusted snapshot / returned executable boundary", "§5", "gbidi3.source.Snapshot (one byte snapshot, raw + canonical v2 hashes); gbidi3.trusted.TrustedReduced; gbidi3.validate.validate -> Validated; gbidi3.executor consumes ONLY Validated",
  "validation re-derives every proposed claim from the trusted snapshot; execution never reads planner payloads; live-source mutation and forged identities rejected before numerics",
  "C20 planner/validator attack (omitted factor, forged view, dropped consumer edge, mutation after validation, file change after snapshot)", "C20 rejections typed REJECTED / TASK_MISMATCH", "oracle truth on every accepted plan", "validation_entries_checked"),
 ("M03", "Metadata-only candidate orders", "§12", "gbidi3.planner.orders (original_id, min_volume, min_fill; shared 3,000,000-update cap; cell clock for mandatory orders)",
  "no nominal table is allocated by ordering; incomplete candidates discarded; deterministic original-id ties through the reduction representative map",
  "C23 65/80/600-star cases reach min-volume with an expired optional clock", "cap exhaustion leaves original-order baseline", "n/a (metadata)", "order_metadata_updates"),
 ("M04", "All-consumer backward demand before materialization", "§7", "gbidi3.demand (descriptor per node: producer id, every USE edge, output requirement, marker obligations, support cover); applied in gbidi3.planner before representation commit",
  "UNION over all consumers; REDUCE lifts lazily; GATHER lifts whole classes; UNKNOWN is live; empty demand must be proved; <= 3 monotone passes",
  "C03 every consumer, C04 dead representative / live class, C13 interrupted discovery", "capped pass preserves previous conservative cover", "oracle", "demand_entries_restricted"),
 ("M05", "Independently switchable D1 / D2 / D3 / V", "§7, §19", "gbidi3.planner.Switches (demand_masks, fusion, response_views); arms A1/A2/A3 map to exactly one switch each",
  "disabling a switch never changes semantics; semantically required support / maps stay enabled in every arm", "qualification runs every control with each switch off and asserts identical truth", "arm table shared-vs-different", "oracle", "mechanism_activations"),
 ("M06", "Joint response refinement (R3 / R4 views)", "§6", "gbidi3.views (exact per-axis class map + scale, validated entrywise); gbidi3.planner joint key = common REFINEMENT of all operand partitions",
  "f(raw,t) = s(raw) * core(pi(raw),t) for EVERY entry incl. zeros; original markers stay outside compressed storage; no merge from numeric equality",
  "C01 equal scalar / different marked response (merge rejected), C04, C05 joint refinement with no single finest input", "C01 rejection; hash/floating candidate only", "oracle", "view_raw_requests / view_core_evaluations"),
 ("M07", "Bounded dense blocks", "§8", "kernel3 DENSE storage: blocks of <= 1,024 OUTPUT entries, joint reservation (values + reverse + labels + scratch) before allocation, chunked long reductions with polling",
  "a small output does not bound elimination work: scratch and polling are per primitive unit", "C17 >1,024 outputs through several blocks; scalar output with huge reduction chunks/polls", "reservation failure -> typed MEMORY_CATEGORY or precompiled stream downgrade (once per region per attempt)", "oracle", "dense_blocks_materialized / block_entries"),
 ("M08", "Real sparse contraction", "§8", "kernel3 SPARSE storage: support-indexed rows, bounded partial join (smallest support x remaining axes), duplicate aggregation, sparse reverse scatter, sparse-to-stream transition",
  "empty support is exact zero; a capped join is discarded or falls back; omitted tuples are never certified zero without proof", "C07 empty-support node, C17 real support joins + duplicate aggregation", "capped join -> fallback", "oracle", "sparse_rows_joined / sparse_output_rows"),
 ("M09", "Generic indexed stream", "§8", "kernel3 STREAM evaluation with explicit frames (no host recursion), mixed-radix eliminated tuples, high arity / nonbinary axes",
  "every recomputation is charged; lack of materialization does not imply small work", "C18 50,000-frame chain under the default stack + shallow lookalike; C06 arity/cardinality", "n/a", "oracle", "stream_frames / regenerated_values"),
 ("M10", "Arbitrary-boundary conditioning and residual components", "§10", "gbidi3.planner.regions (REGION templates, topology compiled once per region) + kernel3 REGION VALUE/PULLBACK (branch sums, prefix/suffix, owned markers, external-input adjoints)",
  "R(b;lambda) = sum_d alpha(d,b) prod_v lambda prod_c R_c(d,b); every factor / scalar / marker has one branch owner; a hyperedge crossing children forbids the split",
  "C16 nonbinary cutset, >= 2 components, isolated variable, boundary-dependent factors, external adjoints; C25 omitted / duplicated branch detected by the oracle", "C16 crossing hyperedge rejected", "oracle", "region_branches / region_contexts_evaluated"),
 ("M11", "One- / two-axis candidate policy", "§10", "gbidi3.planner.regions.choose_cutset (next variable; next TWO when joint domain <= 4,096; compare cold work + memory; tie toward one)",
  "bounded local choice, not cutset search", "C16 forces one-axis and eligible two-axis; > 4,096 two-axis domain declined while one-axis retained", "C16 decline", "oracle", "cutset_candidates_compared"),
 ("M12", "Shared DAG local reverse", "§9", "kernel3 PULLBACK: ADD / REDUCE / GATHER / MUL (prefix-suffix, zero-safe) / LINEAR / REGION / MARKER; every use edge contributes; aliasing operands counted per use",
  "root adjoint one; a scalar cache hit never satisfies an uncomputed derivative", "C03 every consumer, C09 cache semantic types, C15 late deltas", "n/a", "oracle", "reverse_visits / marker_updates"),
 ("M13", "Bounded production cache and late-delta scheduler", "§9", "kernel3 LRU (byte-capped, typed keys: task/attempt/node/context/version/precision/backend), pinned frames; pending-delta store with PENDING / ACTIVE / DRAINED, byte cap, coalescing, early flush, late increments propagate",
  "J^T(h1+h2) = J^T h1 + J^T h2; evicted pure VALUE regenerates; evicting a pending delta or suppressing a late one is a fault", "C09 eviction + regeneration, C15 flush 2 / evict / flush 3 == coalesced 5 (dropped -> (2,6), reflushed -> (7,21) both FAIL), C18 bounded reuse removes repeated visits", "zero-cache mode is a control only", "oracle", "cache_hits / cache_misses / evictions / deltas_coalesced / early_flushes"),
 ("M14", "Original-source complete fallback", "§11", "kernel3 exact fallback: mixed-radix enumeration of evidence-compatible ORIGINAL assignments, per-factor denominator clearing, GMP integer Z_int / N_int, recorded scale",
  "partial enumeration is never an answer; the clock is never reset; nonunit scalar and extreme-range sources handled", "C11 extreme range / bridge, C25 omitted / duplicated branch with forged count", "deadline -> typed stop with the limiting operation", "oracle (shares only the parser)", "fallback_assignments_visited / fallback_bits"),
 ("M15", "Native outward MPFR", "§13", "kernel3 MPFR interval layer: down/up conversion of every exact rational, outward add / mul everywhere (values, coefficients, sparse accumulation, prefix/suffix, adjoints, branches, summaries, markers); ladder 64/128/256/512; exponent range + flags",
  "enclosure by monotonicity and induction; underflowed zero is never a support proof; endpoints retained through normalization", "C11 extreme range, C19 MPFR exponent faults", "flag -> NUMERIC_RANGE", "oracle", "mpfr_ops"),
 ("M16", "Optional binary64 with runtime labels (if enabled)", "§14", "kernel3 Dbl backend: exact conversion check (1-u)f <= fhat <= (1+u)f, leaf range [2*DBL_MIN, DBL_MAX/2], labels E(a+b)=max+1, E(a*b)=sum+1, every rounded positive result range-checked, labels <= 2^52, delta < 1/2",
  "(1-u)^E v <= vhat <= (1+u)^E v for ACTUAL executed operations incl. reverse and regeneration; a rounded-to-zero positive op is a sticky RANGE fault", "C19 22-variable streamed chain (old forecast certificate invalidated), label cap, delta >= 1/2, underflow, rounding-mode change, shared operands used twice, copied / cached labels", "fault -> MPFR route or typed stop", "oracle + exact label replay", "b64_ops / max_label"),
 ("M17", "Exact publication and task binding", "§15", "gbidi3.executor.publish (adp.publish grid scheme reused; DELIVERED grid width <= 1/100 checked in addition to the pre-grid width; atomic staging; byte hashes) + gbidi3.verify (separate process, strict grammar, pinned adp.checker agreement)",
  "p_i in [U_i-eps, L_i+eps] cap [L_i, U_i] cap [0,1], exact simplex sum on the 2^-G grid; wrong-task / stale / REJECTED / short rows reject; absence of a binding field is rejection", "C21 incl. x=0 receipt staged for x=1, near-1/100 boundary fixture", "C21 rejections", "exact reparse", "n/a"),
 ("M18", "Complete memory categories incl. host storage", "§16", "gbidi3.memory.Ledger (five categories, 6 GiB total, Python-side reservations with documented proxies) + kernel3 reservation manager (same categories, remaining capacity handed over; every allocation assigned to exactly one category)",
  "no silent borrowing; pending charged through ACTIVE; pinned values charged; a one-byte cap is not bypassed by another path", "C22 every category cap incl. Python storage, pending-to-active, fallback, export temporaries, vector growth, partial allocation failure", "typed MEMORY_CATEGORY stops; external RSS kill distinguished", "n/a", "reserved_bytes_peak per category"),
 ("M19", "Strict clocks and polling", "§12, §16", "one launch-relative absolute deadline through every layer; ONE optional allowance min(1 s, 0.05 * budget) never renewed; kernel3 polls every <= 4,096 primitive units incl. planning / parsing / validation loops",
  "no fresh deadline at validation / fallback / inspection; indivisible GMP/MPFR primitive disclosed", "C23 clock policy, C22 3,000-unary first poll through actual primitive work", "DEADLINE typed stop with active operation", "n/a", "polls / primitive_units"),
 ("M20", "Supervisor tree cleanup", "§17", "gbidi.supervise (unchanged v3: START/SPAWNED/RECEIPT, deferred cancellation, owned groups, nested registry, kill + reap before the charged wall, PARENT_CLEANUP_KILL receipts)",
  "no live child hidden by a clean parent exit; CLEANUP_UNRESOLVED stays explicit", "C24 real signal controls (launch boundary, prelaunch termination, SPAWNED write failure, nested groups, 18-not-9 witness)", "n/a", "n/a", "receipts"),
 ("M21", "Adapters and strict reconciliation", "§17", "gbidi3.arm_adapter (PRODUCER map ADP_REPAIRED->AGGREGATE_DP_V1, EXACT_LIBDAI->EXACT; planned vs producer arm fields) + gbidi3.reconcile (ONE strict reconciler for resume / closeout / summary)",
  "a usable primary row needs complete task/cell/config/build binding, bound producer record, output hashes, exactly one compatible terminal receipt", "C24 all seven arms through the real outer supervisor, stale 120 s -> 20 s rejection, duplicate receipts, missing config / build", "NOT_ACCEPTED with reasons", "n/a", "n/a"),
 ("M22", "Full-panel manifest and diagnostics", "§19-§21", "gbidi3.pilot.freeze_proposal (46 + 2 inventory, 414 cells, random.Random(20261109) procedure) + gbidi3.inspect_panel (uniform read-only inspection, production entry points, one clock) + counter definitions",
  "exactly 184 + 92 + 138 cells in the specified order; inspection fields fixed before outcomes; every counter has units and exact / upper-bound / sample status", "manifest count/order verified independently", "n/a", "n/a", "n/a"),
 ("M23", "Deterministic whole-path cost model", "§12", "gbidi3.planner.cost (lexicographic: cold complete-work bound, peak reserved bytes, stable id; zero memo hits outside retained regions; ideal-reuse counts reported separately; UNKNOWN on cap)",
  "ranking proxies only; no forecast rejects the whole model", "qualification compares predicted vs counted work on fixtures", "cap -> UNKNOWN + declared safe tie policy", "n/a", "cost_evaluations"),
 ("M24", "Finite rewrite and witness language R0-R8", "§6", "gbidi3.planner rewrites with finite witnesses; gbidi3.validate checks each accepted witness completely",
  "every rewrite preserves P as a POLYNOMIAL; occurrence multiplicity; no branch deletion without inspection; FULL/UNKNOWN support live", "C01, C02 marker duplication, C05 crossing partitions, C10 omission / duplication, C14 fusion derivatives", "invalid proposal -> REJECTED with reason; lawful absence -> baseline intact", "oracle", "rewrites_accepted / rewrites_rejected"),
 ("M25", "Inconsistency and zero distinctions", "§2, §15", "gbidi3.executor.normalize: Z_U = 0 under COMPLETE execution -> inconsistent; Z_L = 0 < Z_U -> POSITIVITY_UNRESOLVED (next precision on the same deadline); certified zero numerator; zero-variable tasks",
  "an inconsistent task publishes no invented posterior; zero variables with positive scalar have a valid empty result", "C07, C11, C21", "typed statuses", "oracle", "n/a"),
]

OPTIONAL = [
 ("O01", "Specialized bipartite kernel (repaired bidi kernel)", "§10, §19", "not integrated into V3 (optional); if ever enabled C26 applies", "NOT_IMPLEMENTED"),
 ("O02", "General compatible-block meeting search", "§6", "deferred by the brief", "NOT_IMPLEMENTED"),
 ("O03", "Derived syntactic-program merging / congruence search", "§6", "deferred by the brief", "NOT_IMPLEMENTED"),
 ("O04", "Arbitrary separable-term / rank discovery", "§6", "deferred by the brief (optional exact splitting only by a supplied finite witness)", "NOT_IMPLEMENTED"),
 ("O05", "Query-block jets (QUERY_BLOCK_JET cache type)", "§9", "not implemented; SCALAR / FULL_SUMMARY / DEMAND_CONTRACTION types are distinct in the cache key space", "NOT_IMPLEMENTED"),
 ("O06", "Uniform schema-label optimization for binary64", "§14", "unnecessary for this milestone; scalar labels are authoritative", "NOT_IMPLEMENTED"),
]

CONTROL_GROUPS = ["C%02d" % i for i in range(1, 27)]

_STATE_FILE = "REQUIREMENTS_STATE.json"


def _load_state(D):
    p = os.path.join(D, _STATE_FILE)
    return json.load(open(p)) if os.path.exists(p) else {}


def update(D, rid, status, evidence=None, note=None):
    """advance one mandatory row; evidence = list of paths (receipts / pytest outputs / fixture files)"""
    assert status in STATUSES, status
    assert rid in {r[0] for r in MANDATORY}, rid
    assert status != "NOT_IMPLEMENTED", "NOT_IMPLEMENTED is reserved for optional rows"
    st = _load_state(D); row = st.get(rid, {"status": "ABSENT", "evidence": [], "history": []})
    row["history"].append({"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "from": row["status"], "to": status, "note": note})
    row["status"] = status
    for e in (evidence or []):
        if e not in row["evidence"]:
            row["evidence"].append(e)
    st[rid] = row
    json.dump(st, open(os.path.join(D, _STATE_FILE), "w"), indent=1); write(D)


def table(D):
    st = _load_state(D); rows = []
    for rid, name, section, entry, invariant, activating, rejecting, oracle, counter in MANDATORY:
        s = st.get(rid, {"status": "ABSENT", "evidence": [], "history": []})
        rows.append({"id": rid, "kind": "MANDATORY", "requirement": name, "brief_section": section, "production_entry_points": entry, "semantic_invariant_or_witness": invariant, "activating_control": activating, "rejection_noop_resource_control": rejecting, "independent_oracle": oracle, "measured_work_counter": counter, "status": s["status"], "evidence_paths": s["evidence"], "history": s["history"]})
    for rid, name, section, note, status in OPTIONAL:
        rows.append({"id": rid, "kind": "OPTIONAL", "requirement": name, "brief_section": section, "note": note, "status": status})
    return rows


def write(D):
    rows = table(D); os.makedirs(D, exist_ok=True)
    mand = [r for r in rows if r["kind"] == "MANDATORY"]; counts = {s: sum(1 for r in mand if r["status"] == s) for s in STATUSES}
    overall = "READY_FOR_REVIEW_CANDIDATE" if all(r["status"] == "QUALIFIED" for r in mand) else "QUALIFICATION_INCOMPLETE"
    doc = {"brief": "GENERAL_BIDI_COMPLETE_IMPLEMENTATION_SPEC.txt revision COMPLETE-1", "brief_sha256": "af2e29bf13c2527bb9db55e9b321ad7aaf73766827b8177d0aa26ba12d12ef20", "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "status_vocabulary": STATUSES, "mandatory_counts": counts, "overall": overall, "rows": rows}
    json.dump(doc, open(os.path.join(D, "REQUIREMENTS.json"), "w"), indent=1)
    L = ["# REQUIREMENTS matrix — GENERAL_BIDI_COMPLETE_V3", "", "Brief: revision COMPLETE-1 (sha256 af2e29bf…). Generated %s. Overall: **%s** (%s)." % (doc["generated_utc"], overall, ", ".join("%s %d" % (k, v) for k, v in counts.items() if v)), "",
         "| id | requirement | § | production entry points | invariant / witness | activating control | rejection / no-op / resource control | oracle | counter | status | evidence |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in mand:
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | **%s** | %s |" % (r["id"], r["requirement"], r["brief_section"], r["production_entry_points"], r["semantic_invariant_or_witness"], r["activating_control"], r["rejection_noop_resource_control"], r["independent_oracle"], r["measured_work_counter"], r["status"], "<br>".join(r["evidence_paths"]) or "—"))
    L += ["", "## Optional / deferred (NOT_IMPLEMENTED is permitted only here)", "", "| id | feature | § | note | status |", "|---|---|---|---|---|"]
    for r in rows:
        if r["kind"] == "OPTIONAL":
            L.append("| %s | %s | %s | %s | %s |" % (r["id"], r["requirement"], r["brief_section"], r["note"], r["status"]))
    open(os.path.join(D, "REQUIREMENTS.md"), "w").write("\n".join(L) + "\n")
    return doc


if __name__ == "__main__":
    d = write(sys.argv[1]); print(json.dumps({"overall": d["overall"], "counts": d["mandatory_counts"]}))
