"""Trusted numerical EXECUTOR of GENERAL_BIDI_COMPLETE_V3 (brief §5, §13-§15): one authoritative numerical pass per successful attempt on the
VALIDATED program, through the native kernel (gbidi3/kernel3.cpp). Pipeline of one cell:
  snapshot (bytes read once) -> common reductions (pinned adp.source, shared rule list) -> TrustedReduced (frozen BEFORE planning) + INDEPENDENT replay of
  the recorded steps with the pinned checker's SourceReplay -> planner on the proposal view -> validate -> Validated (the only payload the kernel sees) ->
  routes: optional binary64 (exact leaf conversion check + leaf range predicate, runtime labels and range guard in the kernel, delta < 1/2) then outward
  MPFR 64/128/256/512 on the SAME deadline -> normalization (Z_L > 0; Z_U == 0 proves inconsistency; Z_L == 0 < Z_U unresolved -> next precision) ->
  original rows through the trusted decoder -> publication (adp.publish grid scheme; DELIVERED grid width <= 1/100) -> separate task-bound verifier process
  (gbidi3.verify) -> atomic delivery. MEMORY stops of the optimized route fall back to the exact integer fallback over the original evidence-restricted
  factors on the remaining clock; every other stop is typed. Every attempt is recorded (counters, labels, stops); the diagnostic record survives every stop."""
from __future__ import annotations
import os, sys, json, time, math, ctypes, hashlib, subprocess, resource
from fractions import Fraction as Fr
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from gbidi3 import source as GS, ir as IR, planner as PL, validate as GV, memory as GM, clock as GC, identity as ID, demand as DM
from gbidi3.trusted import TrustedReduced, Invalid
from adp import source as SRC, publish as PB

U53 = Fr(1, 1 << 53); DBL_MIN = Fr(2) ** -1022; DBL_MAX = Fr((2 ** 53 - 1) * 2 ** 971)
LIB = os.path.join(HERE, "gbidi3", "libgbidi3_kernel.dylib"); BUILD_RECORD = os.path.join(HERE, "gbidi3", "BUILD_RECORD.json")
PRECISIONS = (64, 128, 256, 512)
ARMS = PL.ARMS
STOP_NAMES = {0: "OK", 1: "DEADLINE", 2: "MEMORY", 3: "OVERFLOW", 4: "RANGE", 5: "BADPROG", 6: "FAULT", 7: "FPENV", 8: "LABEL"}
COUNTER_NAMES = ("value_frames", "pullback_frames", "frames_combined", "max_frame_depth", "polls", "mults", "adds", "lookups", "zero_skips", "source_reads", "marker_updates", "gather_visits", "add_visits", "mul_rows", "reduce_terms", "stream_reevals", "reads_outside_demand", "regenerated_values", "dense_blocks", "entries_materialized", "entries_stored_planned", "sparse_rows_joined", "sparse_output_rows", "sparse_join_discarded", "cache_hits", "cache_misses", "cache_evictions", "cache_inserts", "adjoint_adds", "slots_drained", "early_flushes", "late_increments", "pending_peak_bytes", "downgrades", "root_ops", "numerator_adds", "used_values_bytes", "used_index_bytes", "used_reverse_bytes", "used_pending_bytes", "used_scratch_bytes", "peak_scratch_bytes", "cache_bytes", "reverse_tuples", "sparse_reverse_rows", "sparse_reverse_generic", "reverse_value_frames", "reverse_pullback_frames", "reverse_combined_frames", "sparse_reverse_immediate", "immediate_pullback_frames", "reverse_value_terms", "combined_terms", "reverse_mul_rows")
COUNTER_DEFINITIONS = {"units": "exact event counts of the implemented schedule (one logical interval operation = two MPFR endpoint operations); *_bytes are reserved capacities (not RSS)", "status": "EXACT (kernel counters) unless the record says otherwise", "source": "gbidi3/kernel3.cpp Counters + reservation manager",
                       "reduce_terms": "eliminated tuples SUMMED by a VALUE accumulation (stream evaluation, sparse join, AND the backward-phase value reconstruction / combined frames); the forward part alone is counters_after_forward.reduce_terms; the reverse-phase parts are reverse_value_terms (pure VALUE reconstruction) + combined_terms (combined VALUE+PULLBACK frames)",
                       "reverse_value_terms": "eliminated tuples summed in pure VALUE frames pushed DURING THE REVERSE PHASE = reconstruction of streamed operand values that a product pullback needs (the depth-dependent reverse work omitted by the pre-repair cost model)", "combined_terms": "eliminated tuples summed in combined VALUE+PULLBACK frames (the last streamed operand of a product row in a pullback)", "reverse_mul_rows": "MUL rows evaluated during the reverse phase (any frame mode)", "reverse_tuples": "REVERSE work: eliminated tuples visited by the GENERIC REDUCE pullback (never counted in reduce_terms)", "reverse_value_frames": "VALUE frames pushed during the reverse phase = reconstruction of streamed values that a pullback needs (prefix/suffix weights of earlier streamed siblings); forward-phase value frames = value_frames_after_forward", "reverse_pullback_frames": "pure PULLBACK frames pushed during the reverse phase", "reverse_combined_frames": "combined VALUE+PULLBACK frames pushed during the reverse phase (the last streamed operand of a product row)", "sparse_reverse_immediate": "support-indexed sparse deliveries made immediately because the pending array could not be allocated (same operation as the queued drain)", "immediate_pullback_frames": "generic PULLBACK frames pushed immediately because a pending slot could not be allocated (dense / non-sparse storage)", "sparse_reverse_rows": "support-indexed reverse deliveries (retained join rows) of SPARSE nodes", "sparse_reverse_generic": "SPARSE nodes whose reverse ran through the generic tuple loop (labelled fallback; not a completed sparse reverse)", "source_reads": "source table loads in VALUE / PULLBACK / join (forward and reverse)"}
LIVE = {"handle": None, "lib": None}


class Refuse(Exception):
    def __init__(self, kind, reason, rec=None):
        super().__init__("%s: %s" % (kind, reason)); self.kind = kind; self.reason = reason; self.rec = rec


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


class _FactorAdapter:
    __slots__ = ("scope", "card", "table", "origin", "index")

    def __init__(self, f):
        self.scope = tuple(f.scope); self.card = tuple(f.card); self.table = list(f.table); self.origin = f.index; self.index = f.index

    def strides(self):
        st = [1] * len(self.card); acc = 1
        for k in range(len(self.card) - 1, -1, -1):
            st[k] = acc; acc *= self.card[k]
        return tuple(st)


class _ModelAdapter:
    def __init__(self, m):
        self.nvars = m.nvars; self.card = list(m.card); self.factors = [_FactorAdapter(f) for f in m.factors]


class Lib:
    _lib = None; _build = None

    @classmethod
    def get(cls):
        if cls._lib is None:
            b = json.load(open(BUILD_RECORD))
            if not os.path.exists(LIB) or sha_file(LIB) != b["binary_sha256"] or sha_file(os.path.join(HERE, b["source"])) != b["source_sha256"]:
                raise Refuse("FP_ENV", "kernel binary / source do not match BUILD_RECORD.json")
            L = ctypes.CDLL(LIB); P = ctypes.POINTER
            L.gb3_schedule_id.restype = ctypes.c_char_p; L.gb3_fp_env_ok.restype = ctypes.c_int
            L.gb3_create.restype = ctypes.c_void_p; L.gb3_create.argtypes = [ctypes.c_int, ctypes.c_int, P(ctypes.c_int64), ctypes.c_int64, P(ctypes.c_char_p), P(ctypes.c_double), ctypes.c_int64, ctypes.c_int64, ctypes.c_int64, P(ctypes.c_uint64), ctypes.c_double, P(ctypes.c_int)]
            L.gb3_destroy.argtypes = [ctypes.c_void_p]; L.gb3_forward.argtypes = [ctypes.c_void_p]; L.gb3_forward.restype = ctypes.c_int; L.gb3_reverse.argtypes = [ctypes.c_void_p]; L.gb3_reverse.restype = ctypes.c_int
            L.gb3_mpfr_flags.argtypes = [ctypes.c_void_p]; L.gb3_mpfr_flags.restype = ctypes.c_int; L.gb3_counters.argtypes = [ctypes.c_void_p, P(ctypes.c_uint64)]; L.gb3_snapshot.argtypes = [ctypes.c_void_p, P(ctypes.c_uint64)]
            L.gb3_results_size.argtypes = [ctypes.c_void_p]; L.gb3_results_size.restype = ctypes.c_int64; L.gb3_results_hex.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int64]; L.gb3_results_hex.restype = ctypes.c_int
            L.gb3_test_split_root.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]; L.gb3_test_split_root.restype = ctypes.c_int
            L.gb3_test_exponent_range.argtypes = [ctypes.c_long, ctypes.c_long]; L.gb3_test_inject_bad_alloc.argtypes = [ctypes.c_int]; L.gb3_test_leaf_label.argtypes = [ctypes.c_ulonglong]; L.gb3_test_branch_fault.argtypes = [ctypes.c_int]; L.gb3_test_ref_fault.argtypes = [ctypes.c_int]
            L.gb3_ref_create.restype = ctypes.c_void_p; L.gb3_ref_create.argtypes = [P(ctypes.c_int64), ctypes.c_int64, P(ctypes.c_char_p), ctypes.c_double, P(ctypes.c_uint64), P(ctypes.c_int)]
            L.gb3_ref_run.argtypes = [ctypes.c_void_p]; L.gb3_ref_run.restype = ctypes.c_int; L.gb3_ref_results_size.argtypes = [ctypes.c_void_p]; L.gb3_ref_results_size.restype = ctypes.c_int64; L.gb3_ref_results.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int64]; L.gb3_ref_results.restype = ctypes.c_int
            L.gb3_ref_visited.argtypes = [ctypes.c_void_p]; L.gb3_ref_visited.restype = ctypes.c_uint64; L.gb3_ref_used_values.argtypes = [ctypes.c_void_p]; L.gb3_ref_used_values.restype = ctypes.c_uint64; L.gb3_ref_used_scratch.argtypes = [ctypes.c_void_p]; L.gb3_ref_used_scratch.restype = ctypes.c_uint64; L.gb3_ref_destroy.argtypes = [ctypes.c_void_p]
            L.gb3_mpfr_version.restype = ctypes.c_char_p; L.gb3_gmp_version.restype = ctypes.c_char_p; L.gb3_mpfr_emin.restype = ctypes.c_long; L.gb3_mpfr_emax.restype = ctypes.c_long; L.gb3_mpfr_emin_min.restype = ctypes.c_long; L.gb3_mpfr_emax_max.restype = ctypes.c_long
            L.gb3_bytes_per_entry.argtypes = [ctypes.c_int, ctypes.c_int]; L.gb3_bytes_per_entry.restype = ctypes.c_int64; L.gb3_block_entries.restype = ctypes.c_int64
            cls._lib = L; cls._build = b
            if L.gb3_schedule_id().decode() != "GENERAL_BIDI_COMPLETE_V3/indexed-ir-frames-blocks-sparse-lru-deltas/v3.3-sparse-pull-frames":
                raise Refuse("FP_ENV", "kernel schedule id differs")
        return cls._lib


def backend_record():
    L = Lib.get(); b = Lib._build
    return {"kernel": "gbidi3/kernel3.cpp", "schedule_id": L.gb3_schedule_id().decode(), "build": {k: b.get(k) for k in ("compiler_executable_sha256", "compiler_version", "flags", "source_sha256", "binary_sha256", "linked_libraries_sha256", "platform", "utc")}, "mpfr": L.gb3_mpfr_version().decode(), "gmp": L.gb3_gmp_version().decode(), "mpfr_emin_min": L.gb3_mpfr_emin_min(), "mpfr_emax_max": L.gb3_mpfr_emax_max(), "fp_env_ok": bool(L.gb3_fp_env_ok()), "python": sys.version.split()[0]}


# ------------------------------------------------------------------------------------------------------------ binary64 admission (leaf conversion + range predicate)
def to_double_checked(q):
    """nearest binary64 of the exact rational q, verified by EXACT comparison: (1-u) q <= qhat <= (1+u) q, qhat in [2*DBL_MIN, DBL_MAX/2]; zero -> 0.0"""
    q = Fr(q)
    if q == 0:
        return 0.0, True
    try:
        d = q.numerator / q.denominator if q.denominator < (1 << 1000) and q.numerator < (1 << 1000) else float(q)
    except OverflowError:
        return None, False
    if not math.isfinite(d) or d <= 0:
        return None, False
    fd = Fr(d)
    if not ((1 - U53) * q <= fd <= (1 + U53) * q):
        return None, False
    if not (2 * DBL_MIN <= fd <= DBL_MAX / 2):
        return None, False
    return d, True


def binary64_admission(qs, deadline=None):
    """convert every value string the kernel will load; the route is admitted only when EVERY positive leaf passes; polls the ONE deadline every 4,096 leaves"""
    out = []; failed = 0; first = None
    for i, s in enumerate(qs):
        if deadline is not None and i % 4096 == 4095 and time.monotonic() > deadline:
            raise TimeoutError("DEADLINE during binary64 admission after %d leaves" % (i + 1))
        q = Fr(s); d, ok = to_double_checked(q)
        if not ok:
            failed += 1
            if first is None:
                first = s[:60]
            out.append(0.0)
        else:
            out.append(d)
    return out, {"leaves": len(qs), "failed": failed, "first_failure": first, "admitted": failed == 0}


def mpfr_hex_to_fr(tok):
    if tok == "0":
        return Fr(0)
    mant, e = tok.split("@"); neg = mant.startswith("-"); mant = mant.lstrip("-"); digits = mant.replace(".", ""); e = int(e)
    v = Fr(int(digits, 16), 16 ** len(digits)) * (Fr(16) ** e)
    return -v if neg else v


def dbl_hex_to_fr(tok):
    v, e = tok.split("@"); return Fr(float.fromhex(v)), int(e)


# ------------------------------------------------------------------------------------------------------------ live snapshot
def live_snapshot():
    h = LIVE["handle"]; L = LIVE["lib"]
    if h is None or L is None:
        return None
    buf = (ctypes.c_uint64 * 8)(); L.gb3_snapshot(ctypes.c_void_p(h), buf); v = list(buf)
    return {"value_frames": v[0], "pullback_frames": v[1], "mul_rows": v[2], "reduce_terms": v[3], "frame_depth": v[4], "active_node": v[5], "reserved_bytes": v[6], "phase": v[7]}


def _counters(L, h):
    buf = (ctypes.c_uint64 * 56)(); L.gb3_counters(ctypes.c_void_p(h), buf); v = list(buf)
    return {n: v[i] for i, n in enumerate(COUNTER_NAMES)}


# ------------------------------------------------------------------------------------------------------------ the executor
def execute(arm, model_path, evid_path, out, deadline_mono, cfg, phases=None, record_prefix="checked_record", test_hooks=None, snapshot=None, ledger=None):
    """returns the checked record (dict, also written to out/<record_prefix>.json) or raises Refuse (typed stop with the diagnostic record attached)"""
    hooks = test_hooks or {}; phases = phases if phases is not None else {}; t_start = time.monotonic(); led = ledger or GM.Ledger(); cfgA = dict(ARMS[arm]); os.makedirs(out, exist_ok=True)
    for p in (os.path.join(out, record_prefix + ".json"), os.path.join(out, "output.MAR"), os.path.join(out, "output.MAR.tmp"), os.path.join(out, "intervals.json"), os.path.join(out, "point_check.json"), os.path.join(out, "diagnostic_record.json")):
        if os.path.exists(p):
            os.remove(p)
    rec = {"arm": arm, "schedule": "GENERAL_BIDI_COMPLETE_V3", "status": None, "model_path": os.path.abspath(model_path), "evidence_path": os.path.abspath(evid_path), "config": cfg, "mechanisms_enabled": {k: cfgA[k] for k in ("views", "demand_masks", "fusion", "general_planner", "two_axis")}, "attempts": [], "phases_s": phases, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    budget_s = float(cfg.get("budget_s", max(0.0, deadline_mono - t_start)))
    def bind_execution(route, attempt_id):
        """execution identity of the route that produced this record (native routes bind the kernel; python exact routes bind their implementation files)"""
        rec["execution"] = ID.execution_identity(arm, budget_s, cfg, route, attempt_id, build_record=(Lib._build if route in ID.NATIVE_ROUTES else None))
    def diag(stage):
        rec["diagnostic_stage"] = stage; rec["live"] = live_snapshot(); rec["memory_ledger"] = led.report()
        tmp = os.path.join(out, "diagnostic_record.json.tmp")
        with open(tmp, "w") as f:
            json.dump(dict(rec, NOTE="NONCERTIFYING diagnostic record"), f, default=str); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, os.path.join(out, "diagnostic_record.json"))
    def refuse(kind, reason):
        rec["status"] = kind; rec["reason"] = reason; rec["stop"] = {"kind": kind, "reason": reason, "cause": rec.get("stop")}; diag("typed_stop"); raise Refuse(kind, reason, rec)
    def remaining():
        return deadline_mono - time.monotonic()
    def check_deadline(where):
        if remaining() <= 0:
            refuse("RESOURCE_STOP", "DEADLINE at %s" % where)
    # ---------------- 1. snapshot (parsed under the ledger and the ONE deadline: every table is reserved BEFORE its rationals are built)
    t = time.monotonic()
    try:
        if snapshot is not None:
            S = snapshot
            if getattr(S, "ledger_ref", None) is not led:
                led.reserve("source_ir_maps_output", GM.model_bytes_estimate(S.model, len(S.model_bytes) + len(S.evid_bytes)), "caller snapshot handed in by the caller (built outside this ledger; charged on entry)")
        else:
            S = GS.Snapshot(model_path, evid_path, ledger=led, deadline=deadline_mono)
    except GS.InvalidInput as ex:
        rec["status"] = "INVALID_INPUT"; rec["reason"] = ex.reason; diag("invalid_input"); raise Refuse("INVALID_INPUT", ex.reason, rec)
    except GS.ParseStop as ex:
        rec["memory_ledger"] = led.report(); refuse("RESOURCE_STOP", "%s during snapshot parsing: %s" % (ex.kind, ex.reason))
    except GM.MemoryStop as ex:
        refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
    rec["task"] = dict(S.task)
    phases["snapshot"] = time.monotonic() - t; check_deadline("snapshot")
    if S.model.nvars == 0:
        Z = Fr(1)
        for f in S.model.factors:
            Z *= f.table[0]
        rec["reductions"] = {"steps": 0, "note": "zero-variable task: Z is the product of the scalar factors"}
        bind_execution("exact_scalar", "exact_scalar|0")
        if Z == 0:
            rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["reason"] = "zero model mass (zero scalar factor)"; rec["Z"] = "0"; rec["route"] = "exact_scalar"; return _write(out, record_prefix, rec)
        rec["status"] = "INTERVALS_OK"; rec["certified_intervals"] = {}; rec["max_width"] = "0"; rec["route"] = "exact_scalar"; rec["precision"] = "exact"; rec["Z"] = str(Z); return _write(out, record_prefix, rec)
    # ---------------- 2. common reductions (shared rule list; the optional allowance bounds their wall)
    t = time.monotonic(); rules = tuple(cfg.get("rules", PL.COMMON_RULES)); clock = GC.Clock(deadline_mono, budget_s)
    if "_optional_allowance_s" in cfg:
        clock.optional_allowance_s = float(cfg["_optional_allowance_s"])                   # qualification only (C23): an expired / zero optional clock
    if "_row_cap" in cfg:
        clock.row_cap = int(cfg["_row_cap"])                                               # qualification only (C13): interrupted optional discovery
    clock.begin_optional()
    try:
        led.reserve("source_ir_maps_output", 2 * GM.model_bytes_estimate(S.model, 0) + 4096, "reduced model (adapter copy + reduced tables, bounded by twice the source)")   # the pinned reducer copies every table once; reductions never grow a table
    except GM.MemoryStop as ex:
        refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
    R = SRC.Reduced(_ModelAdapter(S.model), dict(S.ev)); red = R.reduce(rules, deadline=min(clock.optional_deadline, deadline_mono))
    rec["reductions"] = dict(red, rules=list(rules), free_reduced=len(R.dom), scale=str(R.scale)); phases["reductions"] = time.monotonic() - t; check_deadline("reductions")
    # ---------------- 3. trusted snapshot + independent replay of the recorded steps (ALSO before a zero-evidence proof is accepted: the proof is a reduction record and is replayed independently like any other step)
    t = time.monotonic()
    try:
        T = TrustedReduced(R, ledger=led)
    except GM.MemoryStop as ex:
        refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
    except Invalid as ex:
        refuse("REJECTED", "trusted snapshot: %s" % ex.reason)
    try:
        led.reserve("source_ir_maps_output", 2 * GM.model_bytes_estimate(S.model, len(S.model_bytes) + len(S.evid_bytes)) + 4096, "independent replay (pinned checker's own parse + tables; bounded wrapper reserved BEFORE the call)")
    except GM.MemoryStop as ex:
        refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
    try:
        rec["source_replay"] = T.independent_replay(model_path, evid_path, R.record(), deadline=deadline_mono)
    except Invalid as ex:
        refuse("REJECTED", ex.reason)
    except TimeoutError:
        refuse("RESOURCE_STOP", "DEADLINE during the independent source replay")
    phases["trusted_snapshot"] = time.monotonic() - t
    if R.zero_proof is not None:
        bind_execution("exact_decoder", "exact_decoder|0"); rec["route"] = "exact_decoder"
        rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["reason"] = "the common reductions proved Z = 0 (independently replayed): %s" % json.dumps(R.zero_proof); rec["zero_proof"] = R.zero_proof; return _write(out, record_prefix, rec)
    L = Lib.get(); rec["backend"] = backend_record(); bpe_mpfr = {p: L.gb3_bytes_per_entry(0, p) for p in PRECISIONS}; bpe_dbl = L.gb3_bytes_per_entry(1, 53)
    if not T.dom:
        # every variable fixed / aliased away: the posterior is the decoder (constants) once Z = scale > 0
        bind_execution("exact_decoder", "exact_decoder|0")
        if T.scale == 0:
            rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["reason"] = "scale is zero"; rec["route"] = "exact_decoder"; return _write(out, record_prefix, rec)
        ivs = {}
        for v in range(T.nvars):
            ivs[str(v)] = [[str(e[1]), str(e[1])] for e in T.dec[v]]
        rec.update(status="INTERVALS_OK", certified_intervals=ivs, max_width="0", route="exact_decoder", precision="exact", Z=str(T.scale)); return _write(out, record_prefix, rec)
    # ---------------- 4. plan (untrusted) on the proposal view, under the cell clock + optional allowance
    t = time.monotonic(); view = T.proposal_view()
    try:
        plan, cands = PL.plan(view, cfgA, clock, bpe_mpfr[64], caps=led.caps, ledger=led)
    except GM.MemoryStop as ex:
        rec["clock"] = clock.record(); refuse("RESOURCE_STOP", "MEMORY_CATEGORY during planning: %s" % ex)
    except GC.PlanStop as ex:
        rec["plan_candidates"] = []; rec["clock"] = clock.record()
        if ex.kind == "CELL_DEADLINE":
            refuse("RESOURCE_STOP", "DEADLINE during planning")
        plan = None; rec["plan_stop"] = {"kind": ex.kind, "reason": ex.reason}
    rec["plan_candidates"] = cands if plan is not None else rec.get("plan_candidates"); rec["clock"] = clock.record(); phases["plan"] = time.monotonic() - t
    if hooks.get("force_stream") and plan is not None:
        for n in plan.program.nodes:
            if n.nid not in plan.program.roots and n.storage in (IR.DENSE, IR.SPARSE):
                n.storage = IR.STREAM; n.demand = "FULL"
    if hooks.get("mutate_program") and plan is not None:
        hooks["mutate_program"](plan.program)
    if hooks.get("mutate_reduced"):
        hooks["mutate_reduced"](R)                                                            # qualification (C20): a planner that mutates the LIVE reduced object
    # ---------------- 4b. SHARED programs (a node with several consumer use edges): the all-consumer demand compiler restricts DENSE storage only to the UNION of
    # every consumer's reads (review F3); tree programs (the production planner's) are complete under the bucket-level pass and are left untouched
    if plan is not None and any(len(u) > 1 for u in plan.program.consumers().values()):
        t = time.monotonic(); cap = clock.remaining_rows()                                  # ONE aggregate optional budget shared with the planner's discovery (rows + optional wall)
        try:
            rec["demand_all_consumers"] = DM.compile_demand(plan.program, row_cap=cap, tables={f.fid: f.table for f in T.factors}, clock=clock, ledger=led, optional=bool(cfgA["demand_masks"]))
        except GC.PlanStop as ex:
            if ex.kind == "CELL_DEADLINE":
                refuse("RESOURCE_STOP", "DEADLINE during all-consumer demand compilation")
            rec["demand_all_consumers"] = {"status": "SKIPPED_" + ex.kind}
        rec["demand_all_consumers"]["phase_s"] = time.monotonic() - t; phases["demand_all_consumers"] = rec["demand_all_consumers"]["phase_s"]
    # ---------------- 5. validate -> the executable representation
    V = None
    if plan is not None:
        t = time.monotonic()
        try:
            same = T.unchanged(R, ledger=led, deadline=deadline_mono)
        except GM.MemoryStop as ex:
            refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
        except TimeoutError:
            refuse("RESOURCE_STOP", "DEADLINE during the trusted-snapshot identity check")
        if not same:
            refuse("REJECTED", "the live reduced object was mutated during planning")
        try:
            led.reserve("source_ir_maps_output", IR.program_bytes_bound(plan.program) + 64 * len(plan.program.nodes) + 4096, "validated executable copy + validator tables (reserved BEFORE validation)")
        except GM.MemoryStop as ex:
            refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
        try:
            V = GV.validate(plan.program, T, deadline=deadline_mono)
        except Invalid as ex:
            if "DEADLINE" in ex.reason:
                refuse("RESOURCE_STOP", ex.reason)
            rec["plan_validation"] = {"status": "REJECTED", "reason": ex.reason}; refuse("REJECTED", "plan validation: %s" % ex.reason)
        rec["plan_validation"] = V.record; rec["plan"] = _plan_record(plan, V); rec["mechanisms"] = plan.mechanisms; phases["validate"] = time.monotonic() - t
        if hooks.get("after_validate"):
            hooks["after_validate"](plan.program)                                             # qualification (C20): the planner payload changes AFTER validation; execution uses the validated copy
        del plan
    diag("planned"); check_deadline("validation")
    # ---------------- 6. numerical routes
    result = None
    if V is not None:
        t = time.monotonic()
        try:
            led.reserve("source_ir_maps_output", IR.flatten_bytes_bound(V), "flat program + value strings + ctypes arrays (bound computed BEFORE flattening)")
        except GM.MemoryStop as ex:
            refuse("RESOURCE_STOP", "MEMORY_CATEGORY: %s" % ex)
        try:
            prog, qs, nfac, nratio, nconst = IR.flatten(V, deadline=deadline_mono)
        except IR.IRError as ex:
            if "DEADLINE" in ex.reason:
                refuse("RESOURCE_STOP", ex.reason)
            refuse("REJECTED", "flatten: %s" % ex.reason)
        phases["flatten"] = time.monotonic() - t
        routes = []
        if cfg.get("allow_binary64", True) and not hooks.get("no_binary64"):
            try:
                dvals, adm = binary64_admission(qs, deadline=deadline_mono); rec["binary64_admission"] = adm
            except TimeoutError as ex:
                refuse("RESOURCE_STOP", str(ex))
            if adm["admitted"]:
                routes.append(("binary64", 53, dvals))
        routes += [("mpfr", p, None) for p in PRECISIONS]
        for route, prec, dvals in routes:
            if remaining() <= 0:
                rec["stop"] = {"kind": "DEADLINE", "phase": "before attempt"}; break
            att = {"route": route, "precision": prec, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "attempt_id": "%s|%d|%d" % (route, prec, len(rec["attempts"]))}; rec["attempts"].append(att); t0 = time.monotonic()
            caps5 = (ctypes.c_uint64 * 5)(*led.kernel_caps()); prog_arr = (ctypes.c_int64 * len(prog))(*prog); qs_arr = (ctypes.c_char_p * len(qs))(*[s.encode() for s in qs]); err = ctypes.c_int(0)
            darr = (ctypes.c_double * len(dvals))(*dvals) if dvals is not None else None
            if hooks.get("leaf_label"):
                L.gb3_test_leaf_label(int(hooks["leaf_label"]))
            L.gb3_test_branch_fault(int(hooks.get("branch_fault", 0)))
            h = L.gb3_create(1 if route == "binary64" else 0, prec, prog_arr, len(prog), qs_arr, darr, nfac, nratio, nconst, caps5, max(0.0, remaining()), ctypes.byref(err))
            if hooks.get("leaf_label"):
                L.gb3_test_leaf_label(1)
            att["create_s"] = time.monotonic() - t0
            if not h:
                att["outcome"] = "CREATE_" + STOP_NAMES.get(err.value, str(err.value)); att["stop"] = STOP_NAMES.get(err.value)
                if err.value in (1, 2):
                    rec["stop"] = {"kind": STOP_NAMES[err.value], "phase": "create"}; break
                if err.value == 7:
                    att["outcome"] = "FP_ENV_REFUSED"; continue
                refuse("REJECTED", "kernel refused the program at create: %s" % STOP_NAMES.get(err.value))
            LIVE["handle"] = h; LIVE["lib"] = L
            try:
                t1 = time.monotonic(); st = L.gb3_forward(ctypes.c_void_p(h)); att["forward_s"] = time.monotonic() - t1; att["counters_after_forward"] = _counters(L, h)
                if st != 0:
                    att["outcome"] = "FORWARD_" + STOP_NAMES.get(st, str(st)); att["stop"] = STOP_NAMES.get(st); att["stop_phase"] = "forward"
                    if st in (1, 2):
                        rec["stop"] = {"kind": STOP_NAMES[st], "phase": "forward"}; break
                    if st == 4 and route == "mpfr":
                        att["outcome"] = "MPFR_EXPONENT_RANGE_FAULT"; att["mpfr_flags"] = L.gb3_mpfr_flags(ctypes.c_void_p(h)); rec["stop"] = {"kind": "RANGE", "phase": "forward", "route": "mpfr"}; break      # mantissa precision does not cure exponent-range exhaustion: no ladder
                    if st in (4, 7, 8):
                        att["outcome"] = "ROUTE_FAULT_" + STOP_NAMES[st]; continue
                    refuse("REJECTED", "kernel fault in forward: %s" % STOP_NAMES.get(st))
                t1 = time.monotonic()
                if hooks.get("split_root") and route == "mpfr":
                    w1, w2, evict = hooks["split_root"]; st = L.gb3_test_split_root(ctypes.c_void_p(h), str(w1).encode(), str(w2).encode(), 1 if evict else 0)
                else:
                    st = L.gb3_reverse(ctypes.c_void_p(h))
                att["reverse_s"] = time.monotonic() - t1; att["counters"] = _counters(L, h); att["mpfr_flags"] = L.gb3_mpfr_flags(ctypes.c_void_p(h)) if route == "mpfr" else None
                if st != 0:
                    att["outcome"] = "REVERSE_" + STOP_NAMES.get(st, str(st)); att["stop"] = STOP_NAMES.get(st); att["stop_phase"] = "reverse"
                    if st in (1, 2):
                        rec["stop"] = {"kind": STOP_NAMES[st], "phase": "reverse"}; break
                    if st == 4 and route == "mpfr":
                        att["outcome"] = "MPFR_EXPONENT_RANGE_FAULT"; rec["stop"] = {"kind": "RANGE", "phase": "reverse", "route": "mpfr"}; break
                    if st in (4, 7, 8):
                        att["outcome"] = "ROUTE_FAULT_" + STOP_NAMES[st]; continue
                    refuse("REJECTED", "kernel fault in reverse: %s" % STOP_NAMES.get(st))
                need = L.gb3_results_size(ctypes.c_void_p(h))
                if need < 0:
                    att["outcome"] = "ROUTE_FAULT_RANGE_AT_EXPORT"; continue
                try:
                    led.reserve("frames_scratch_pub", need + 64, "export buffer (attempt %s)" % att["attempt_id"])
                except GM.MemoryStop as ex:
                    rec["stop"] = {"kind": "MEMORY", "phase": "export", "detail": str(ex)}; break
                buf = ctypes.create_string_buffer(int(need) + 64); n = L.gb3_results_hex(ctypes.c_void_p(h), buf, int(need) + 64); led.release("frames_scratch_pub", need + 64)
                if n < 0:
                    att["outcome"] = "ROUTE_FAULT_EXPORT_%d" % n; continue
                toks = buf.value.decode().split(";")[:-1]; att["export_bytes"] = n
            finally:
                LIVE["handle"] = None; L.gb3_destroy(ctypes.c_void_p(h)); L.gb3_test_branch_fault(0)
            # ---- enclosure
            nvr = T.nvars_reduced; vcards = [len(T.dom[v]) for v in T.reduced_vars]
            if route == "binary64":
                Zv, EZ = dbl_hex_to_fr(toks[0]); i = 2; red = {}; E_N_max = 0
                for vi, v in enumerate(T.reduced_vars):
                    row = []
                    for a in range(vcards[vi]):
                        nv, e = dbl_hex_to_fr(toks[i]); i += 2; row.append((nv, e)); E_N_max = max(E_N_max, e)
                    red[v] = row
                att["labels"] = {"E_Z": EZ, "E_N_max": E_N_max}
                if Zv == 0:
                    att["outcome"] = "Z_ZERO_IN_BINARY64_UNRESOLVED"; continue          # a binary64 zero is not a proof: MPFR decides
                dmax = (E_N_max + EZ) * U53; att["delta_max"] = float(dmax)
                if dmax >= Fr(1, 2):
                    att["outcome"] = "LABEL_DELTA_TOO_LARGE"; continue
                encl = {v: [(((1 - dmax) * nv / Zv), ((nv / Zv) / (1 - dmax))) for nv, _ in red[v]] for v in T.reduced_vars}
                ZL, ZU = (1 - dmax) * Zv, Zv / (1 - dmax)
            else:
                ZL = mpfr_hex_to_fr(toks[0]); ZU = mpfr_hex_to_fr(toks[1]); i = 2; red = {}
                for vi, v in enumerate(T.reduced_vars):
                    row = []
                    for a in range(vcards[vi]):
                        row.append((mpfr_hex_to_fr(toks[i]), mpfr_hex_to_fr(toks[i + 1]))); i += 2
                    red[v] = row
                if ZU == 0:
                    att["outcome"] = "Z_UPPER_ZERO_PROVED"; rec["Z"] = ["0", "0"]; rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["reason"] = "complete outward execution proved Z = 0 (Z_U = 0)"; rec["route"] = route; rec["precision"] = prec; bind_execution(route, att["attempt_id"]); return _write(out, record_prefix, rec)
                if ZL == 0:
                    att["outcome"] = "POSITIVITY_UNRESOLVED"; continue
                encl = {v: [(nlo / ZU, nhi / ZL) for nlo, nhi in red[v]] for v in T.reduced_vars}
            # ---- original rows through the trusted decoder
            ivs = {}; wmax = Fr(0); bad = None
            for v in range(T.nvars):
                row = []
                for e in T.dec[v]:
                    if e[0] == "C":
                        row.append((Fr(e[1]), Fr(e[1])))
                    else:
                        y, s, eta = e[1], e[2], Fr(e[3]); lo, hi = encl[y][T.dom[y].index(s)]; row.append((max(Fr(0), min(Fr(1), eta * lo)), max(Fr(0), min(Fr(1), eta * hi))))
                sl = sum(a for a, _ in row); su = sum(b for _, b in row)
                if sl > 1 or su < 1:
                    bad = v; break
                ivs[v] = row; wmax = max(wmax, max(b - a for a, b in row))
            if bad is not None:
                att["outcome"] = "UNSOUND_ROUTE_SIMPLEX_INCONSISTENT"; rec["unsound_witness"] = {"variable": bad, "route": route, "precision": prec}; continue
            att["max_width"] = str(wmax); att["wall_s"] = time.monotonic() - t0
            if wmax > PB.MAX_WIDTH:
                att["outcome"] = "TOO_WIDE"; continue
            att["outcome"] = "INTERVALS"; result = (route, prec, ivs, wmax, ZL, ZU, att["attempt_id"]); break
    # ---------------- 7. exact fallback over the ORIGINAL evidence-restricted factors (memory stop / not representable only; same clock)
    if hooks.get("force_fallback"):
        result = None; rec["stop"] = {"kind": "MEMORY", "phase": "forced_by_qualification_hook"}
    if result is None and cfg.get("reference_fallback", True) and (rec.get("stop", {}).get("kind") == "MEMORY" or rec.get("plan_stop")):
        t = time.monotonic(); fb = exact_fallback(S, deadline_mono, led, test_hooks=hooks); rec["exact_fallback"] = {k: fb[k] for k in fb if k not in ("Z", "N")}; phases["fallback"] = time.monotonic() - t
        if fb["status"] == "COMPLETE":
            Z = fb["Z"]
            if Z == 0:
                rec["status"] = "ZERO_EVIDENCE_PROVED"; rec["reason"] = "exact fallback: Z = 0"; rec["route"] = "exact_fallback"; bind_execution("exact_fallback", "exact_fallback|0"); return _write(out, record_prefix, rec)
            ivs = {v: [(q, q) for q in [fb["N"][v][a] / Z for a in range(S.model.card[v])]] for v in range(S.model.nvars)}
            result = ("exact_fallback", "exact_integer", ivs, Fr(0), Z, Z, "exact_fallback|0")
    if result is None:
        st = rec.get("stop") or {}
        if st.get("kind") == "DEADLINE":
            refuse("RESOURCE_STOP", "DEADLINE in phase %s" % st.get("phase"))
        if st.get("kind") == "MEMORY":
            refuse("RESOURCE_STOP", "MEMORY_CATEGORY in phase %s (fallback: %s)" % (st.get("phase"), (rec.get("exact_fallback") or {}).get("status")))
        if st.get("kind") == "RANGE":
            refuse("NUMERIC_RANGE", "MPFR exponent-range fault in phase %s (flags %s); no precision ladder cures exponent exhaustion" % (st.get("phase"), rec["attempts"][-1].get("mpfr_flags")))
        if rec.get("plan_stop"):
            refuse("ROUTE_LIMITATION", "plan: %s; fallback: %s" % (rec["plan_stop"], (rec.get("exact_fallback") or {}).get("status")))
        outs = [a.get("outcome") for a in rec["attempts"]]
        if any(o == "POSITIVITY_UNRESOLVED" for o in outs):
            refuse("NUMERIC_UNRESOLVED", "Z_L = 0 < Z_U at every precision of the ladder")
        if any(o == "TOO_WIDE" for o in outs):
            refuse("NUMERIC_UNRESOLVED", "WIDTH_UNRESOLVED at every precision of the ladder")
        if any(o and o.startswith("ROUTE_FAULT") for o in outs):
            refuse("NUMERIC_RANGE", "every route faulted: %s" % outs)
        refuse("NUMERIC_UNRESOLVED", "no route produced an enclosure: %s" % outs)
    route, prec, ivs, wmax, ZL, ZU, attempt_id = result; bind_execution(route, attempt_id)
    rec.update(status="INTERVALS_OK", route=route, precision=prec, max_width=str(wmax), Z=[str(ZL), str(ZU)], certified_intervals={str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in ivs}, certifying="one authoritative numerical pass of the qualified executor on the validated program; binary64 labels / outward MPFR enclose the exact value; publication and separate task-bound verification follow")
    rec["memory_ledger"] = led.report(); return _write(out, record_prefix, rec)


def plan_only(arm, model_path, evid_path, budget_s, cfg=None, hard_deadline=None):
    """read-only inspection with PRODUCTION policy entry points and the SAME clock semantics as a cell: one hard deadline (launch-relative: now + budget
    unless given), one optional allowance min(1 s, 0.05 budget) started at the reductions; snapshot -> reductions -> trusted snapshot -> plan -> validate ->
    flatten; NO numerics, NO kernel attempt. Returns a dict with typed statuses and capped / unknown states."""
    t0 = time.monotonic(); dl = hard_deadline if hard_deadline is not None else t0 + float(budget_s); cfg = dict(cfg or {}); cfgA = dict(ARMS[arm]); led = GM.Ledger(); out = {"arm": arm, "status": None, "phases_s": {}}
    try:
        S = GS.Snapshot(model_path, evid_path)
    except GS.InvalidInput as ex:
        out.update(status="INVALID_INPUT", reason=ex.reason); return out
    out["task"] = {k: S.task[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "nvars", "factor_occurrences")}; out["source_stats"] = {"nvars": S.model.nvars, "max_card": max(S.model.card) if S.model.card else 0, "factors": len(S.model.factors), "max_arity": max((len(f.scope) for f in S.model.factors), default=0), "table_entries": sum(len(f.table) for f in S.model.factors), "zero_entries": sum(1 for f in S.model.factors for x in f.table if x == 0), "evidence": len(S.ev)}
    out["phases_s"]["snapshot"] = time.monotonic() - t0
    if S.model.nvars == 0:
        out.update(status="SCALAR_TASK"); return out
    t = time.monotonic(); clock = GC.Clock(dl, float(budget_s)); clock.begin_optional()
    R = SRC.Reduced(_ModelAdapter(S.model), dict(S.ev)); red = R.reduce(tuple(cfg.get("rules", PL.COMMON_RULES)), deadline=clock.optional_deadline)
    out["reductions"] = dict(red, free_reduced=len(R.dom), scale=str(R.scale), reduced_domains_max=max((len(d) for d in R.dom.values()), default=0), reduced_factors=len(R.factors), reduced_entries=sum(len(f.table) for f in R.factors)); out["phases_s"]["reductions"] = time.monotonic() - t
    if R.zero_proof is not None:
        out.update(status="ZERO_EVIDENCE_PROVED"); return out
    if time.monotonic() > dl:
        out.update(status="RESOURCE_STOP", reason="DEADLINE after reductions"); return out
    try:
        T = TrustedReduced(R, ledger=led)
    except (GM.MemoryStop, Invalid) as ex:
        out.update(status="RESOURCE_STOP" if isinstance(ex, GM.MemoryStop) else "REJECTED", reason=str(ex)); return out
    if not T.dom:
        out.update(status="EXACT_DECODER"); return out
    t = time.monotonic()
    try:
        plan, cands = PL.plan(T.proposal_view(), cfgA, clock, Lib.get().gb3_bytes_per_entry(0, 64), caps=led.caps)
    except GC.PlanStop as ex:
        out.update(status="RESOURCE_STOP" if ex.kind == "CELL_DEADLINE" else "PLAN_STOP", plan_stop={"kind": ex.kind, "reason": ex.reason}, clock=clock.record()); out["phases_s"]["plan"] = time.monotonic() - t; return out
    out["phases_s"]["plan"] = time.monotonic() - t; out["plan_candidates"] = cands; out["clock"] = clock.record()
    t = time.monotonic()
    try:
        V = GV.validate(plan.program, T, deadline=dl)
    except Invalid as ex:
        out.update(status="RESOURCE_STOP" if "DEADLINE" in ex.reason else "PLAN_REJECTED", reason=ex.reason); return out
    out["plan_validation"] = V.record; out["plan"] = _plan_record(plan, V); out["mechanisms"] = plan.mechanisms; out["phases_s"]["validate"] = time.monotonic() - t
    try:
        prog, qs, nfac, nratio, nconst = IR.flatten(V); out["flat_program_words"] = len(prog); out["value_strings"] = len(qs)
        dvals, adm = binary64_admission(qs); out["binary64_admission"] = adm
    except IR.IRError as ex:
        out.update(status="PLAN_REJECTED", reason=ex.reason); return out
    out["memory_ledger"] = led.report(); out["status"] = "PLANNED"; out["phases_s"]["total"] = time.monotonic() - t0; return out


def _plan_record(plan, V, table_cap=4000):
    P = V.P; rows = [{"nid": n.nid, "kind": n.kind, "axes": list(n.axes), "card": list(n.card), "storage": n.storage, "demand": ("FULL" if n.demand == "FULL" else ("EMPTY" if n.demand == "EMPTY" else len(n.demand))), "children": list(n.children), "prov": {k: (v if isinstance(v, (str, int, bool, list)) else str(v)) for k, v in (n.prov or {}).items()}} for n in P.nodes]
    summary = {"kinds": {k: sum(1 for n in P.nodes if n.kind == k) for k in IR.KIND_CODE}, "storage": {k: sum(1 for n in P.nodes if n.kind == IR.REDUCE and n.storage == k) for k in IR.STORAGE_CODE}, "demand_restricted": sum(1 for n in P.nodes if n.demand not in ("FULL", "EMPTY")), "compressed_axes": sum(1 for n in P.nodes if n.kind == IR.REDUCE and any(r is not None for r in n.reps))}
    return {"order": plan.order_name, "nodes": len(P.nodes), "roots": list(P.roots), "totals": plan.totals, "discovery_stop": plan.discovery_stop, "summary": summary,
            "node_table": rows if len(rows) <= table_cap else rows[:table_cap], "node_table_truncated": len(rows) > table_cap}


def _write(out, prefix, rec):
    tmp = os.path.join(out, prefix + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(rec, f, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, os.path.join(out, prefix + ".json")); return rec


# ------------------------------------------------------------------------------------------------------------ exact integer fallback (brief §11)
def exact_fallback(S, deadline_mono, led, test_hooks=None):
    """mixed-radix enumeration of every evidence-compatible assignment of the ORIGINAL variables; every original factor occurrence multiplied once
    after per-factor denominator clearing (D_f = lcm of the restricted table's denominators); Z_int = (prod D_f) Z, N_int likewise; restored exactly."""
    L = Lib.get(); m = S.model; ev = S.ev; free = [v for v in range(m.nvars) if v not in ev]; pos = {v: i for i, v in enumerate(free)}
    total_entries = sum(len(f.table) for f in m.factors); charged = 0; work = [0]
    def tick(n=1):
        """ONE cumulative work counter over every preparation loop (slicing, lcm, clearing, string conversion), polled every 4,096 units"""
        before = work[0]; work[0] += n
        if work[0] // 4096 != before // 4096 and time.monotonic() > deadline_mono:
            raise TimeoutError
    def reserve(nbytes, what):
        nonlocal charged
        led.reserve("frames_scratch_pub", nbytes, what); charged += nbytes
    try:
        reserve(64 * len(m.factors) + 8 * len(free) + 4096, "fallback preparation: descriptors")
        prog = [len(free)] + [m.card[v] for v in free]; vals = []; fdesc = []; scale = Fr(1); zero_scalar = False
        from itertools import product as iproduct
        for f in m.factors:
            st = f.strides(); keep = [k for k in range(len(f.scope)) if f.scope[k] not in ev]; base = sum(ev[v] * st[k] for k, v in enumerate(f.scope) if v in ev); tick(len(f.scope) + 1)
            if not keep:
                val = f.table[base]; scale *= val
                if val == 0:
                    zero_scalar = True
                continue
            card = [f.card[k] for k in keep]; n = IR.prod(card)
            # BIT-LENGTH BOUNDS computed from the SOURCE rationals BEFORE anything is built (review E1): (1) the per-factor lcm D has at most sum(bitlen(den))
            # bits -> the lcm accumulation (two live integers of that size) is reserved first; (2) D is computed (polled); (3) every cleared integer
            # num * (D / den) has at most bitlen(num) + bitlen(D) bits and is held THREE times at once (Python int, decimal string ~0.302 bits per char + 49,
            # encoded bytes copy for ctypes) next to the sliced Fraction list -> reserved with the ACTUAL bitlen(D) before the first cleared integer exists
            den_bits = 0; num_bits_max = 0
            for idx in iproduct(*[range(c) for c in card]):
                q = f.table[base + sum(idx[j] * st[keep[j]] for j in range(len(keep)))]; den_bits += q.denominator.bit_length(); num_bits_max = max(num_bits_max, q.numerator.bit_length()); tick()
            lcm_bytes = 3 * (28 + 4 * ((den_bits + 1) // 30 + 1)); reserve(lcm_bytes + n * GM.RATIONAL_BYTES_FALLBACK + 256, "fallback preparation of factor %d: sliced table (%d rationals) + lcm accumulation of <= %d bits" % (f.index, n, den_bits + 1))
            tab = []
            for idx in iproduct(*[range(c) for c in card]):
                tab.append(f.table[base + sum(idx[j] * st[keep[j]] for j in range(len(keep)))]); tick()
            D = 1
            for q in tab:
                D = D * q.denominator // math.gcd(D, q.denominator); tick()
            int_bits = num_bits_max + D.bit_length(); int_bytes = 28 + 4 * (int_bits // 30 + 1); str_bytes = 49 + int_bits * 302 // 1000 + 2; enc_bytes = 33 + int_bits * 302 // 1000 + 2
            reserve(n * (int_bytes + str_bytes + enc_bytes + 24) + 256, "fallback preparation of factor %d: %d cleared integers of <= %d bits (actual lcm %d bits) held as int + decimal string + encoded copy" % (f.index, n, int_bits, D.bit_length()))
            scale /= D; ints = []
            for q in tab:
                ints.append(q.numerator * (D // q.denominator)); tick()
            fdesc.append(([pos[f.scope[k]] for k in keep], card, len(ints)))
            for x in ints:
                vals.append(str(x)); tick()
            del tab, ints
    except GM.MemoryStop as ex:
        return {"status": "MEMORY", "reason": str(ex), "phase": "preparation", "allocated_before_stop": charged, "work_units": work[0]}
    except TimeoutError:
        return {"status": "DEADLINE", "reason": "deadline during fallback preparation after %d work units" % work[0], "phase": "preparation", "visited": 0}
    if zero_scalar:
        return {"status": "COMPLETE", "Z": Fr(0), "N": None, "visited": 0, "note": "zero scalar factor"}
    prog.append(len(fdesc))
    for sc, card, ent in fdesc:
        prog += [len(sc)] + sc + card + [ent]
    try:
        reserve(8 * len(prog) + 8 * max(1, len(vals)) + 256, "fallback program + pointer arrays")
    except GM.MemoryStop as ex:
        return {"status": "MEMORY", "reason": str(ex), "phase": "preparation", "allocated_before_stop": charged}
    caps5 = (ctypes.c_uint64 * 5)(*led.kernel_caps()); parr = (ctypes.c_int64 * len(prog))(*prog); enc = []
    for s_ in vals:
        enc.append(s_.encode()); tick()
    varr = (ctypes.c_char_p * max(1, len(vals)))(*(enc or [b"1"])); err = ctypes.c_int(0)
    L.gb3_test_ref_fault(int((test_hooks or {}).get("ref_fault", 0)))
    Sref = L.gb3_ref_create(parr, len(prog), varr, max(0.0, deadline_mono - time.monotonic()), caps5, ctypes.byref(err))
    if not Sref:
        return {"status": STOP_NAMES.get(err.value, "FAULT"), "reason": "fallback create: %s" % STOP_NAMES.get(err.value)}
    try:
        st = L.gb3_ref_run(ctypes.c_void_p(Sref)); visited = L.gb3_ref_visited(ctypes.c_void_p(Sref)); total = IR.prod(m.card[v] for v in free)
        if st != 0:
            return {"status": STOP_NAMES.get(st, "FAULT"), "visited": visited, "total": total, "used_values": L.gb3_ref_used_values(ctypes.c_void_p(Sref)), "used_scratch": L.gb3_ref_used_scratch(ctypes.c_void_p(Sref))}
        need = L.gb3_ref_results_size(ctypes.c_void_p(Sref))
        try:
            led.reserve("frames_scratch_pub", need + 64, "fallback export")
        except GM.MemoryStop as ex:
            return {"status": "MEMORY", "reason": str(ex)}
        buf = ctypes.create_string_buffer(int(need) + 64); n = L.gb3_ref_results(ctypes.c_void_p(Sref), buf, int(need) + 64); led.release("frames_scratch_pub", need + 64)
        if n < 0:
            return {"status": "FAULT", "reason": "fallback export %d" % n}
        toks = buf.value.decode().split(";")[:-1]; Zint = int(toks[0]); i = 1; N = {}
        for v in free:
            N[v] = [Fr(int(toks[i + a])) * scale for a in range(m.card[v])]; i += m.card[v]
        Z = Fr(Zint) * scale
        for v in ev:
            N[v] = [Z if a == ev[v] else Fr(0) for a in range(m.card[v])]
        return {"status": "COMPLETE", "Z": Z, "N": N, "visited": visited, "total": total, "scale_restored": str(scale), "used_values": L.gb3_ref_used_values(ctypes.c_void_p(Sref)), "used_scratch": L.gb3_ref_used_scratch(ctypes.c_void_p(Sref))}
    finally:
        L.gb3_ref_destroy(ctypes.c_void_p(Sref)); L.gb3_test_ref_fault(0)


# ------------------------------------------------------------------------------------------------------------ publication (brief §15)
def publish(out, model_path, evid_path, rec, cell_rec, deadline_mono, record_prefix="checked_record", snapshot=None, arm=None, cfg=None, ledger=None):
    """FAIL-CLOSED publication (review R2 / B): (1) the record must be INTERVALS_OK, bound to the caller's task on every binding field, and carry an
    execution identity equal to the one the CALLER recomputes (arm, budget, full config, route, attempt, actual implementation files / kernel build);
    (2) every stale verifier output is removed before launch; the verifier gets a unique attempt-specific output path, the expected task AND expected
    execution identity, and the SAME absolute deadline; (3) the verifier must exit 0 AND leave a fresh receipt whose status is POINT_VERIFIED, whose
    task / execution bindings equal the expectations and whose mar_sha256 equals the sha256 of the exact temporary bytes; (4) only those bytes are
    atomically renamed to output.MAR. On ANY failure the temporary output and every verifier output are removed: no stale success can survive."""
    def fail(status, reason):
        for p in (os.path.join(out, "output.MAR.tmp"), os.path.join(out, "output.MAR"), os.path.join(out, "intervals.json")) + tuple(os.path.join(out, f) for f in os.listdir(out) if f.startswith("point_check") or f.startswith("expected_identity")):   # fail-closed: no deliverable survives a refused publication
            try:
                os.remove(p)
            except OSError:
                pass
        cell_rec.setdefault("publication", {})["status"] = "NOT_PUBLISHED"; cell_rec["publication"]["reason"] = reason; return status
    try:
        S = snapshot or GS.Snapshot(model_path, evid_path)
    except GS.InvalidInput as ex:
        return fail("CHECK_FAILED", "the caller's files are not a valid task at publication: %s" % ex.reason)
    if snapshot is not None and not S.path_still_matches():
        return fail("CHECK_FAILED", "the caller's files changed after the snapshot")
    card = list(S.model.card)
    if rec.get("status") != "INTERVALS_OK":
        return fail("CHECK_FAILED", "record status %r" % rec.get("status"))
    if not GS.bound_to_task(rec.get("task"), S.task):
        return fail("CHECK_FAILED", "record not bound to the caller's task")
    exe = rec.get("execution")
    if not isinstance(exe, dict) or arm is None or cfg is None:
        return fail("CHECK_FAILED", "record carries no execution identity or the caller supplied no arm / configuration to bind it")
    budget_s = float(cfg.get("budget_s", 0.0)); route = exe.get("route")
    try:
        expected_exec = ID.execution_identity(arm, budget_s, cfg, route, exe.get("attempt_id"), build_record=(Lib._build or json.load(open(BUILD_RECORD))) if route in ID.NATIVE_ROUTES else None)
    except Exception as ex:
        return fail("CHECK_FAILED", "expected execution identity could not be computed: %s" % ex)
    bad = ID.check_execution(exe, expected_exec)
    if bad:
        return fail("CHECK_FAILED", "record execution identity differs from the caller's expectation: %s" % bad[:3])
    ivs = {}
    for v in range(S.model.nvars):
        row = rec["certified_intervals"].get(str(v))
        if row is None or len(row) != card[v]:
            return fail("CHECK_FAILED", "row %d missing or of wrong length" % v)
        ivs[v] = [(Fr(a), Fr(b)) for a, b in row]
    for p in [os.path.join(out, "output.MAR.tmp"), os.path.join(out, "output.MAR"), os.path.join(out, "intervals.json")] + [os.path.join(out, f) for f in os.listdir(out) if f.startswith("point_check") or f.startswith("expected_identity")]:
        try:
            os.remove(p)                                                                      # a retry never inherits a stale success: every earlier delivery / receipt is removed BEFORE this attempt publishes
        except OSError:
            pass
    tmp = os.path.join(out, "output.MAR.tmp")
    if S.model.nvars == 0:
        with open(tmp, "w") as f:
            f.write("MAR\n0\n"); f.flush(); os.fsync(f.fileno())
        prep = {"status": "CERTIFIED", "grid_bits": None, "max_width_observed": "0", "delivered_max_width": "0", "rows": {}}
    else:
        if ledger is not None:
            try:
                ledger.reserve("frames_scratch_pub", 400 * sum(card) + 4096, "publication rows + decimal strings")
            except GM.MemoryStop as ex:
                return fail("RESOURCE_STOP", "MEMORY_CATEGORY at publication: %s" % ex)
        points, prep = PB.publish_rows(ivs, card)
        prep["delivered_max_width"] = prep.get("max_width_published_grid"); prep["delivered_width_met"] = Fr(prep["delivered_max_width"]) <= PB.MAX_WIDTH
        if points is None or not prep["delivered_width_met"]:
            cell_rec["publication"] = {k: v for k, v in prep.items() if k != "widened_intervals"}; return prep["status"] if points is None else "CERTIFIED_TOO_WIDE_DELIVERED"
        PB.write_mar(tmp, points, card)
        with open(tmp, "rb+") as f:
            f.flush(); os.fsync(f.fileno())
        json.dump({str(v): [[str(a), str(b)] for a, b in prep["widened_intervals"][v]] for v in prep["widened_intervals"]}, open(os.path.join(out, "intervals.json"), "w"))
    cell_rec["publication"] = {k: v for k, v in prep.items() if k != "widened_intervals"}
    if not S.path_still_matches():
        return fail("CHECK_FAILED", "the caller's files changed before verification")
    tmp_sha = sha_file(tmp); attempt_tag = hashlib.sha256((str(exe.get("attempt_id")) + "|" + tmp_sha).encode()).hexdigest()[:12]; pc = os.path.join(out, "point_check.%s.json" % attempt_tag); exp_path = os.path.join(out, "expected_identity.%s.json" % attempt_tag)
    json.dump({"task": S.task, "execution": expected_exec, "mar_sha256": tmp_sha}, open(exp_path, "w"))
    rem = deadline_mono - time.monotonic()
    if rem <= 0:
        return fail("RESOURCE_STOP", "DEADLINE before the separate verification")
    try:
        r = subprocess.run([sys.executable, "-m", "gbidi3.verify", os.path.join(out, record_prefix + ".json"), tmp, model_path, evid_path, pc, exp_path, "%.6f" % rem], cwd=HERE, env=dict(os.environ, PYTHONPATH=HERE), timeout=rem, capture_output=True)
    except subprocess.TimeoutExpired:
        return fail("RESOURCE_STOP", "the separate verifier did not finish before the cell deadline")
    if r.returncode != 0:
        return fail("CHECK_FAILED", "the separate verifier exited %d: %s" % (r.returncode, (r.stderr or b"")[-300:].decode(errors="replace")))
    if not os.path.exists(pc):
        return fail("CHECK_FAILED", "the separate verifier left no receipt")
    try:
        ver = json.load(open(pc))
    except Exception as ex:
        return fail("CHECK_FAILED", "unreadable verifier receipt: %s" % ex)
    cell_rec["point_verification"] = ver
    if ver.get("status") != "POINT_VERIFIED" or ver.get("mar_sha256") != tmp_sha or not GS.bound_to_task(ver.get("task"), S.task) or ID.check_execution(ver.get("execution"), expected_exec) or ver.get("expected_identity_sha256") != sha_file(exp_path):
        return fail("CHECK_FAILED", "verifier receipt is not a fresh POINT_VERIFIED receipt for exactly these bytes, this task and this execution")
    if sha_file(tmp) != tmp_sha or not S.path_still_matches():
        return fail("CHECK_FAILED", "the delivered bytes or the caller's files changed during verification")
    os.replace(tmp, os.path.join(out, "output.MAR")); cell_rec["certified"] = {"output_sha256": tmp_sha, "delivered_max_width": prep.get("delivered_max_width"), "pre_grid_max_width": prep.get("max_width_observed"), "point_target_met": True, "verifier_receipt": os.path.basename(pc), "execution": exe}
    return "CERTIFIED"
