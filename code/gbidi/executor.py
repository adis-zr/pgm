"""GENERAL_BIDI_V2 / NATIVE_PLAIN_V2 certifying executor (ONE authoritative numerical pass; repair of 9-10 Nov 2026 after two adversarial reviews).

Pipeline per cell: SNAPSHOT (gbidi.source: model + evidence bytes read ONCE; strict grammar; hashes and parse from the same bytes) -> shared qualified
source reductions (adp.source; recorded) -> plan (gbidi.plan: UNTRUSTED proposals; cheap representable baseline first; one shared discovery allowance)
-> VALIDATE the chosen proposal against the reduced model (gbidi.validate: ownership, scopes, consumers, every view identity entrywise) -> flatten
-> numerical routes (binary64 only when the leaves convert exactly-checked and the range envelope passes; the KERNEL tracks an exact error label on
every value through every performed operation and range-checks every rounded result, so the enclosure (E_N + E_Z) u is the whole-execution proof;
else outward MPFR at p in 64,128,256,512 with the widest exponent range configured and the flags checked) -> exact enclosures per ORIGINAL (variable,
state) through the reduction decoder -> publication (adp.publish dyadic grid; the snapshot path is re-checked before and after) -> ONE separate
task-bound point verifier process (gbidi.verify: re-hashes the caller's paths, re-parses the delivered decimals; for nonempty tasks it also runs the
pinned adp.checker --verify-point and both must agree).  Fallback: exact integer reference stream (GB-07; mixed-radix odometer, resumable, growable
export) on the reduced model within the remaining deadline after a MEMORY stop.
DIAGNOSTICS (review F5): `diagnostic_record.json` (NONCERTIFYING) is written after planning, before and after every attempt and on every typed stop;
it carries the task, reductions, plan + candidate table, validation, mechanisms with provenance, every attempt with its counters, and the live kernel
snapshot; the cell's progress thread reads `live_snapshot()` while the kernel runs. A typed stop raises Refuse WITH the record attached.

Trust boundary (stated plainly): this module, gbidi.source, adp.source's reductions + decoder, gbidi.validate, the native kernel (+ MPFR/GMP),
adp.publish, gbidi.verify and adp.checker's point mode are the TRUSTED / QUALIFIED components; the planner is UNTRUSTED (validated here); there is
no second independent numerical implementation per benchmark cell. NOT_IMPLEMENTED mechanisms are listed in gbidi.plan.NOT_IMPLEMENTED."""
from __future__ import annotations
import os, sys, json, time, math, hashlib, ctypes, subprocess, threading
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from adp import source as SRC, publish as PB
from gbidi import plan as PL, source as GS, validate as GV

U53 = Fr(1, 2 ** 53); DBL_MIN = Fr(2) ** -1022; DBL_MAX = Fr(2 ** 1024 - 2 ** 971)
LIB = os.path.join(HERE, "gbidi", "libgbidi_kernel." + ("dylib" if sys.platform == "darwin" else "so")); BUILD_RECORD = os.path.join(HERE, "gbidi", "BUILD_RECORD.json")
SCHEDULE_ID = "GENERAL_BIDI_V2/bucket-core-views-storage-hint-explicit-frames-localreverse/v2"; PRECISIONS = (64, 128, 256, 512)
ARMS = {"GENERAL_BIDI_V2": {"views": True, "demand_masks": True, "fusion": True, "orders": ["original", "min_fill", "min_volume"]},
        "NATIVE_PLAIN_V2": {"views": False, "demand_masks": False, "fusion": False, "orders": ["min_volume"]},
        "A1_NO_DEMAND_MASKS": {"views": True, "demand_masks": False, "fusion": True, "orders": ["original", "min_fill", "min_volume"]},
        "A2_NO_FUSION": {"views": True, "demand_masks": True, "fusion": False, "orders": ["original", "min_fill", "min_volume"]},
        "A3_NO_RESPONSE_VIEWS": {"views": False, "demand_masks": True, "fusion": True, "orders": ["original", "min_fill", "min_volume"]}}
STOP_NAMES = {0: "OK", 1: "DEADLINE", 2: "MEMORY", 3: "OVERFLOW", 4: "RANGE", 5: "BADPROG", 6: "FAULT", 7: "FPENV"}
COUNTER_NAMES = ["primal_rows", "reverse_rows", "rows_skipped_zero", "mults", "adds", "lookups", "value_frames", "pullback_frames", "stream_reevals", "reads_outside_demand", "entries_materialized", "entries_stored_planned", "numerator_adds", "adjoint_adds", "slots_drained", "polls", "max_frame_depth", "root_ops", "used_values_bytes", "used_index_bytes", "used_reverse_bytes", "used_pending_bytes", "used_scratch_bytes", "peak_scratch_bytes"]
COUNTER_DEFINITIONS = {"primal_rows": "row products formed in VALUE frames (first evaluations AND regenerations; combined frames count once)", "reverse_rows": "row products formed in PULLBACK frames", "rows_skipped_zero": "rows skipped in either pass because an input was exactly zero",
                       "mults": "logical multiplications performed (one interval multiplication = two MPFR endpoint operations)", "adds": "logical additions performed", "lookups": "source table loads + stored slot loads", "value_frames": "VALUE frames pushed (entry evaluations requested)", "pullback_frames": "PULLBACK frames pushed",
                       "stream_reevals": "VALUE frames pushed for a non-stored entry (streamed node or read outside the stored set)", "reads_outside_demand": "reads of a stored node's entry that was not stored (served by streaming)", "entries_materialized": "stored entries whose evaluation completed", "entries_stored_planned": "stored slots allocated",
                       "numerator_adds": "additions into an original-marker numerator", "adjoint_adds": "additions into a stored adjoint slot (pending delta)", "slots_drained": "nonzero stored adjoint slots drained", "polls": "deadline polls (every 4096 charged primitive units)", "max_frame_depth": "deepest explicit frame stack", "root_ops": "root prefix/suffix/Z multiplications (also in mults)",
                       "used_*_bytes": "reserved bytes per category (values / index maps / numerators+root scratch / pending adjoints / frames+scratch+source values); exact for native pools, an estimate for unordered_map nodes; process RSS is sampled separately"}
LIVE = {"lock": threading.Lock(), "handle": None, "lib": None, "attempt": None, "stage": "idle"}


class Refuse(Exception):
    def __init__(self, kind, reason, rec=None):
        super().__init__(reason); self.kind = kind; self.reason = reason; self.rec = rec


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


class _FactorAdapter:
    __slots__ = ("scope", "card", "table", "origin", "_f")

    def __init__(self, f):
        self.scope = tuple(f.scope); self.card = tuple(f.card); self.table = list(f.table); self.origin = f.index; self._f = f

    def strides(self):
        return self._f.strides()


class _ModelAdapter:
    def __init__(self, m):
        self.nvars = m.nvars; self.card = list(m.card); self.factors = [_FactorAdapter(f) for f in m.factors]


# ----------------------------------------------------------------------------------------------------------------------- native bridge
class Lib:
    _lib = None

    @classmethod
    def get(cls):
        if cls._lib is None:
            br = json.load(open(BUILD_RECORD))
            if sha_file(LIB) != br["binary_sha256"] or sha_file(os.path.join(HERE, "gbidi", "kernel.cpp")) != br["source_sha256"]:
                raise Refuse("FP_ENV", "kernel binary / source differ from the frozen BUILD_RECORD")
            L = ctypes.CDLL(LIB); c = ctypes
            L.gb_schedule_id.restype = c.c_char_p; L.gb_mpfr_version.restype = c.c_char_p; L.gb_gmp_version.restype = c.c_char_p
            for f in ("gb_mpfr_emin", "gb_mpfr_emax", "gb_mpfr_emin_min", "gb_mpfr_emax_max"):
                getattr(L, f).restype = c.c_long
            L.gb_test_exponent_range.argtypes = [c.c_long, c.c_long]; L.gb_test_inject_bad_alloc.argtypes = [c.c_int]; L.gb_bytes_per_entry.argtypes = [c.c_int, c.c_int]; L.gb_bytes_per_entry.restype = c.c_int64
            L.gb_fp_env_ok.restype = c.c_int
            L.gb_create.restype = c.c_void_p; L.gb_create.argtypes = [c.c_int, c.c_int, c.POINTER(c.c_int64), c.c_int64, c.POINTER(c.c_char_p), c.POINTER(c.c_double), c.c_int64, c.c_int64, c.POINTER(c.c_uint64), c.c_double, c.POINTER(c.c_int)]
            L.gb_destroy.argtypes = [c.c_void_p]; L.gb_forward.argtypes = [c.c_void_p]; L.gb_forward.restype = c.c_int; L.gb_reverse.argtypes = [c.c_void_p]; L.gb_reverse.restype = c.c_int; L.gb_mpfr_flags.argtypes = [c.c_void_p]; L.gb_mpfr_flags.restype = c.c_int
            L.gb_counters.argtypes = [c.c_void_p, c.POINTER(c.c_uint64)]; L.gb_snapshot.argtypes = [c.c_void_p, c.POINTER(c.c_uint64)]; L.gb_results_hex.argtypes = [c.c_void_p, c.c_char_p, c.c_int64]; L.gb_results_hex.restype = c.c_int
            L.gb_test_split_root.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int]; L.gb_test_split_root.restype = c.c_int
            L.gb_ref_create.restype = c.c_void_p; L.gb_ref_create.argtypes = [c.POINTER(c.c_int64), c.c_int64, c.POINTER(c.c_char_p), c.c_double, c.POINTER(c.c_int)]; L.gb_ref_run.argtypes = [c.c_void_p]; L.gb_ref_run.restype = c.c_int
            L.gb_ref_visited.argtypes = [c.c_void_p]; L.gb_ref_visited.restype = c.c_uint64; L.gb_ref_results.argtypes = [c.c_void_p, c.c_char_p, c.c_int64]; L.gb_ref_results.restype = c.c_int; L.gb_ref_destroy.argtypes = [c.c_void_p]
            if L.gb_schedule_id().decode() != SCHEDULE_ID:
                raise Refuse("FP_ENV", "kernel schedule id mismatch")
            cls._lib = L; cls.build = br
        return cls._lib


def flatten_program(P):
    """Flat int64 program + rational value strings. Every index is checked against int64 (the planner's representability check makes this a
    consistency assertion, never the first point of failure). demand_kind: 0 FULL, 1 LIST, 2 EMPTY (distinct serialization: review P5)."""
    R = P.R; prog = []; qs = []; fid_pos = {}; facs = sorted(P.fac.values(), key=lambda f: f.fid)
    prog.append(len(facs))
    for f in facs:
        fid_pos[f.fid] = len(fid_pos); prog += [len(f.scope)] + list(f.scope) + list(f.card) + [len(f.table), len(qs)]; qs += ["%d/%d" % (x.numerator, x.denominator) for x in f.table]
    nfac = len(qs); prog.append(len(P.nodes))
    for nd in P.nodes:
        prog += [nd.x, nd.x_card, len(nd.inputs)]
        for kind, ref in nd.inputs:
            prog += [0 if kind == "F" else 1, fid_pos[ref] if kind == "F" else ref]
        prog += [len(nd.scope)] + list(nd.scope)
        for w in nd.scope:
            v = nd.views[w]; prog += [len(v.cls)] + list(v.cls) + [len(v.reps)] + list(v.reps) + [len(qs) - nfac]; qs += ["%d/%d" % (r.numerator, r.denominator) for r in v.ratio]
        if nd.demand == "FULL":
            dk, dem = 0, []
        elif len(nd.demand) == 0:
            dk, dem = 2, []
        else:
            dk, dem = 1, list(nd.demand)
        prog += [nd.core_entries, -1 if nd.consumer is None else nd.consumer, 1 if nd.materialize else 0, dk, len(dem)] + dem
    prog += [len(P.roots)] + list(P.roots); qs.append("%d/%d" % (R.scale.numerator, R.scale.denominator)); nratio = len(qs) - nfac - 1
    for x in prog:
        if not (-(2 ** 63) <= x < 2 ** 63):
            raise Refuse("REJECTED", "program index exceeds int64 (planner representability check failed to catch it)")
    return prog, qs, nfac, nratio


# ----------------------------------------------------------------------------------------------------------------------- binary64 admission (range envelope only; the kernel proves the labels)
def binary64_admission(P):
    """Cheap PRE-check: every leaf converts within (1 +- u) (exact comparison) and a conservative range envelope of all positive intermediates lies
    inside normal binary64. The error labels are NOT forecast here: the kernel tracks the exact label of every value through every performed
    operation and range-checks every rounded result; the enclosure uses those labels (whole-execution proof, review F1)."""
    R = P.R; rec = {"route": "binary64", "checks": []}
    try:
        lo = Fr(1); hi = Fr(1)
        for f in P.fac.values():
            pos = [x for x in f.table if x > 0]
            if not pos:
                rec["checks"].append("all-zero factor"); return False, rec
            lo *= min(Fr(1), min(pos)); hi *= max(Fr(1), max(f.table))
        for nd in P.nodes:
            for w in nd.scope:
                for r in nd.views[w].ratio:
                    if r > 0:
                        lo *= min(Fr(1), r); hi *= max(Fr(1), r)
        if R.scale > 0:
            lo *= min(Fr(1), R.scale); hi *= max(Fr(1), R.scale)
        logK = sum(math.ceil(math.log2(len(d))) for d in R.dom.values())
        rec.update({"log2_lo": math.log2(lo.numerator) - math.log2(lo.denominator), "log2_hi": math.log2(hi.numerator) - math.log2(hi.denominator) + logK, "labels": "tracked exactly by the kernel per value (sum max+1, product sum+1, leaf 1); each rounded result range-checked"})
        if lo / 2 < DBL_MIN or (hi * (2 ** logK)) * 2 > DBL_MAX:
            rec["checks"].append("range envelope outside normal binary64"); return False, rec
        rec["checks"].append("range envelope OK; labels decided by the kernel"); return True, rec
    except Exception as ex:
        rec["checks"].append("analysis error: %s" % ex); return False, rec


def to_double_checked(q, where):
    q = Fr(q)
    if q == 0:
        return 0.0
    try:
        x = float(q)
    except OverflowError:
        raise Refuse("RANGE", "conversion overflow at %s" % where)
    if not math.isfinite(x) or x <= 0 or not ((1 - U53) * q <= Fr(x) <= (1 + U53) * q):
        raise Refuse("RANGE", "conversion of %s at %s outside the (1+-u) bound" % (q, where))
    return x


def mpfr_hex_to_fr(s):
    if s == "0":
        return Fr(0)
    mant, e = s.split("@"); neg = mant.startswith("-"); mant = mant.lstrip("-"); e = int(e); val = Fr(int(mant, 16), 16 ** len(mant)) * (Fr(16) ** e)
    return -val if neg else val


def dbl_hex_to_fr(s):
    v, e = s.split("@"); return Fr(float.fromhex(v)), int(e)


def live_snapshot():
    """live kernel counters while an attempt runs (read by the cell's progress thread); None when idle"""
    with LIVE["lock"]:
        H, L = LIVE["handle"], LIVE["lib"]
        if H is None:
            return {"stage": LIVE["stage"], "attempt": LIVE["attempt"]}
        s = (ctypes.c_uint64 * 8)(); L.gb_snapshot(H, s); s = list(s)
        return {"stage": LIVE["stage"], "attempt": LIVE["attempt"], "primal_rows": s[0], "reverse_rows": s[1], "value_frames": s[2], "pullback_frames": s[3], "frame_depth": s[4], "active_node": s[5], "used_scratch_bytes": s[6], "phase": {0: "created", 1: "forward", 2: "reverse"}.get(s[7], s[7])}


def _set_live(H, L, attempt, stage):
    with LIVE["lock"]:
        LIVE["handle"] = H; LIVE["lib"] = L; LIVE["attempt"] = attempt; LIVE["stage"] = stage


def _counters(L, H):
    cnt = (ctypes.c_uint64 * 32)(); L.gb_counters(H, cnt); return {COUNTER_NAMES[i]: int(cnt[i]) for i in range(len(COUNTER_NAMES))}


# ----------------------------------------------------------------------------------------------------------------------- the executor
def execute(arm, model_path, evid_path, out, deadline_mono, cfg, phases=None, record_prefix="checked_record", test_hooks=None, snapshot=None):
    ph = phases if phases is not None else {}; t0 = [time.monotonic()]
    def mark(name):
        t = time.monotonic(); ph[name] = ph.get(name, 0.0) + (t - t0[0]); t0[0] = t
    os.makedirs(out, exist_ok=True)
    for stale in (record_prefix + ".json", "output.MAR", "intervals.json", "diagnostic_record.json"):
        if os.path.exists(os.path.join(out, stale)):
            os.remove(os.path.join(out, stale))
    rec = {"executor": "gbidi.executor v2", "arm": arm, "schedule_id": SCHEDULE_ID, "status": None, "model_path": os.path.abspath(model_path), "evidence_path": os.path.abspath(evid_path), "mechanisms": {}, "attempts": [], "certifying": False}
    def diag(stage):
        rec["diagnostic_stage"] = stage; rec["diagnostic_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()); rec["live"] = live_snapshot(); _write(out, "diagnostic_record", dict(rec, NOTE="NONCERTIFYING diagnostic snapshot; the certificate is checked_record.json"))
    def refuse(kind, reason):
        _set_live(None, None, None, "stopped"); rec["status"] = kind; rec["reason"] = reason; diag("typed_stop"); raise Refuse(kind, reason, rec)
    # ---- immutable task snapshot (bytes read once; strict grammar)
    try:
        S = snapshot or GS.Snapshot(model_path, evid_path)
    except GS.InvalidInput as ex:
        rec["status"] = "INVALID_INPUT"; rec["reason"] = ex.reason; diag("invalid_input"); raise Refuse("INVALID_INPUT", ex.reason, rec)
    m = S.model; ev = S.ev; rec["task"] = dict(S.task); mark("parse_bind"); _set_live(None, None, None, "reductions")
    if m.nvars == 0:
        Z = Fr(1)
        for f in m.factors:
            Z *= f.table[0]
        rec.update({"status": "ZERO_EVIDENCE_PROVED" if Z == 0 else "INTERVALS_OK", "certified_intervals": {}, "Z_exact": str(Z), "precision": "exact", "reason": "no variables: Z is the scalar product; empty query result", "certifying": Z != 0}); _write(out, record_prefix, rec); return rec
    # ---- shared qualified reductions
    R = SRC.Reduced(_ModelAdapter(m), dict(ev)); disc_wall = min(1.0, 0.05 * cfg["budget_s"]); disc_deadline = time.monotonic() + disc_wall; rules = list(cfg.get("rules", PL.COMMON_RULES))
    rrec = R.reduce(rules, deadline=disc_deadline); rec["reductions"] = {"rules": rules, "steps": {k: sum(1 for s in R.steps if s[0] == k) for k in set(s[0] for s in R.steps)}, "recognition": rrec, "free_reduced": len(R.dom), "scale": str(R.scale), "zero_proof": R.zero_proof, "reduced_hash": R.reduced_hash(), "note": PL.COMMON_RULES_NOTE[:160] + "..."}
    mark("source_reductions")
    if R.zero_proof is not None:
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "structural zero: %s" % json.dumps(R.zero_proof), "certifying": True}); _write(out, record_prefix, rec); return rec
    L0 = Lib.get(); acfg = dict(ARMS[arm]); acfg["bytes_per_entry"] = int(L0.gb_bytes_per_entry(0, PRECISIONS[0])); rec["bytes_per_entry_planned"] = {"mpfr_p64": acfg["bytes_per_entry"], "binary64": int(L0.gb_bytes_per_entry(1, 53)), "note": "the planner sizes stored tables with the first MPFR route's per-entry bytes (the kernel charges exactly these); higher precisions may hit a category cap -> typed MEMORY stop -> fallback"}
    if not R.dom:
        Z = R.scale; ivs = {v: [(Fr(e[1]), Fr(e[1])) if e[0] == "C" else (Fr(0), Fr(1)) for e in R.dec[v]] for v in range(m.nvars)}
        rec.update({"status": "INTERVALS_OK", "certified_intervals": {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}, "Z_exact": str(Z), "precision": "exact", "plan": {"nodes": 0}, "certifying": True}); _write(out, record_prefix, rec); return rec
    # ---- plan (untrusted; baseline first; ONE shared allowance continues from the reductions' clock)
    _set_live(None, None, None, "plan")
    try:
        P, table = PL.plan(R, acfg, deadline=disc_deadline)
    except PL.PlanStop as ex:
        rec["plan_candidates_error"] = {"kind": ex.kind, "reason": ex.reason}; refuse("ROUTE_LIMITATION" if ex.kind == "NOT_REPRESENTABLE" else "RESOURCE_STOP", "planner: %s: %s" % (ex.kind, ex.reason))
    rec["plan"] = P.record(); rec["plan_candidates"] = table; rec["mechanisms"] = P.mechanisms; rec["not_implemented"] = PL.NOT_IMPLEMENTED; mark("plan")
    # ---- independent validation of the untrusted proposal
    try:
        rec["plan_validation"] = GV.validate(P, R, deadline=deadline_mono)
    except GV.Invalid as ex:
        rec["plan_validation"] = {"status": "INVALID", "reason": ex.reason}; refuse("REJECTED", "untrusted plan rejected by validation: %s" % ex.reason)
    mark("validate")
    prog, qs, nfac, nratio = flatten_program(P); mark("flatten"); diag("planned")
    # ---- numerical policy
    L = Lib.get(); rec["backend"] = {"build": {k: Lib.build[k] for k in ("binary_sha256", "source_sha256", "compiler_version", "flags", "linked_libraries_sha256")}, "mpfr": L.gb_mpfr_version().decode(), "gmp": L.gb_gmp_version().decode(), "emin_default": L.gb_mpfr_emin(), "emax_default": L.gb_mpfr_emax(), "emin_min": L.gb_mpfr_emin_min(), "emax_max": L.gb_mpfr_emax_max(), "fp_env_nearest_no_ftz": bool(L.gb_fp_env_ok())}
    caps = (ctypes.c_uint64 * 5)(PL.CAPS["value_cache"], PL.CAPS["source_ir_maps_output"], PL.CAPS["reverse_pinned"], PL.CAPS["pending_adjoints"], PL.CAPS["frames_scratch_publication"])
    ok64, a64 = binary64_admission(P) if cfg.get("allow_binary64", True) else (False, {"route": "binary64", "checks": ["disabled by config"]}); rec["binary64_admission"] = a64; mark("numeric_policy")
    attempts = rec["attempts"]; result = None; routes = ([("binary64", 53)] if ok64 else []) + [("mpfr", p) for p in PRECISIONS]
    prog_arr = (ctypes.c_int64 * len(prog))(*prog); qs_arr = (ctypes.c_char_p * len(qs))(*[q.encode() for q in qs])
    for route, prec in routes:
        if time.monotonic() > deadline_mono:
            rec["stop"] = {"kind": "DEADLINE", "detail": "before attempt %s/%d" % (route, prec)}; break
        att = {"route": route, "precision": prec, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}; attempts.append(att); t = time.monotonic(); H = None
        try:
            dbl = None
            if route == "binary64":
                dbl = (ctypes.c_double * len(qs))(*[to_double_checked(Fr(q), i) for i, q in enumerate(qs)])
            err = ctypes.c_int(0); att["create_s"] = None; _set_live(None, L, att, "create")
            H = L.gb_create(1 if route == "binary64" else 0, prec, prog_arr, len(prog), qs_arr, dbl, nfac, nratio, caps, max(0.0, deadline_mono - time.monotonic()), ctypes.byref(err)); att["create_s"] = time.monotonic() - t
            if not H:
                st = err.value; att["stop"] = STOP_NAMES.get(st, st); att["stop_phase"] = "create"
                if st == 2:
                    rec["stop"] = {"kind": "MEMORY", "phase": "create"}; break
                if st == 7:
                    raise Refuse("FP_ENV", "ambient floating-point environment is not nearest / no-FTZ")
                if st == 1:
                    rec["stop"] = {"kind": "DEADLINE", "phase": "create"}; break
                raise Refuse("REJECTED", "kernel refused the program (%s)" % att["stop"])
            _set_live(H, L, att, "forward"); diag("attempt_started")
            try:
                t1 = time.monotonic(); st = L.gb_forward(H); att["forward_s"] = time.monotonic() - t1; att["counters_after_forward"] = _counters(L, H)
                if st != 0:
                    att["stop"] = STOP_NAMES.get(st, st); att["stop_phase"] = "forward"; att["counters"] = att["counters_after_forward"]
                    if st == 1:
                        rec["stop"] = {"kind": "DEADLINE", "phase": "forward", "detail": "native forward stream"}; break
                    if st == 2:
                        rec["stop"] = {"kind": "MEMORY", "phase": "forward"}; break
                    if st in (4, 7):
                        raise Refuse("RANGE" if st == 4 else "FP_ENV", "typed numerical-range / environment failure in forward (%s)" % att["stop"])
                    raise Refuse("REJECTED", "kernel forward stop %s" % att["stop"])
                _set_live(H, L, att, "reverse"); t2 = time.monotonic()
                if test_hooks and "split_root" in test_hooks:
                    w1, w2, ev_ = test_hooks["split_root"]; st = L.gb_test_split_root(H, w1.encode(), w2.encode(), 1 if ev_ else 0)
                else:
                    st = L.gb_reverse(H)
                att["reverse_s"] = time.monotonic() - t2; att["counters"] = _counters(L, H)
                if route == "mpfr":
                    att["mpfr_flags"] = L.gb_mpfr_flags(H)
                if st != 0:
                    att["stop"] = STOP_NAMES.get(st, st); att["stop_phase"] = "reverse"
                    if st == 1:
                        rec["stop"] = {"kind": "DEADLINE", "phase": "reverse"}; break
                    if st == 2:
                        rec["stop"] = {"kind": "MEMORY", "phase": "reverse"}; break
                    if st in (4, 7):
                        raise Refuse("RANGE" if st == 4 else "FP_ENV", "typed numerical-range / environment failure in reverse (%s)" % att["stop"])
                    raise Refuse("REJECTED", "kernel reverse stop %s" % att["stop"])
                size = 1 << 20; toks = None
                while True:
                    buf = ctypes.create_string_buffer(size); n = L.gb_results_hex(H, buf, size)
                    if n >= 0:
                        toks = buf.value.decode().split(";")[:-1]; break
                    if n == -1 and size < (1 << 31):
                        size *= 4; continue
                    att["stop_phase"] = "export"; raise Refuse("RANGE", "an exported endpoint is not a finite nonnegative number (typed range failure)" if n == -2 else "result export failed (%d)" % n)
                if route == "binary64":
                    ZL, EZ = dbl_hex_to_fr(toks[0]); ZU = ZL; k = 2; Nn = {}
                    for nd in P.nodes:
                        Nn[nd.x] = []
                        for a in range(nd.x_card):
                            v, e = dbl_hex_to_fr(toks[k]); Nn[nd.x].append((v, v, e)); k += 2
                else:
                    ZL, ZU = mpfr_hex_to_fr(toks[0]), mpfr_hex_to_fr(toks[1]); k = 2; Nn = {}
                    for nd in P.nodes:
                        Nn[nd.x] = []
                        for a in range(nd.x_card):
                            Nn[nd.x].append((mpfr_hex_to_fr(toks[k]), mpfr_hex_to_fr(toks[k + 1]), None)); k += 2
            finally:
                _set_live(None, L, att, "destroy"); L.gb_destroy(H); H = None
            if route == "binary64":
                att["labels"] = {"E_Z": EZ, "E_N_max": max([e for row in Nn.values() for _, _, e in row] + [0])}
                if ZU == 0:
                    att["outcome"] = "Z_ZERO_PROVED"; result = ("ZERO", None, att); break
                dmax = Fr(att["labels"]["E_N_max"] + EZ) * U53; att["delta_max"] = float(dmax)
                if dmax >= Fr(1, 2):
                    raise Refuse("UNSOUND_ROUTE", "binary64 whole-execution label (E_N + E_Z) u >= 1/2: enclosure void; next route")
                def encl(nlo, nhi, e):
                    d = Fr(e + EZ) * U53; return (max(Fr(0), (1 - d) * (nlo / ZU)), min(Fr(1), (nhi / ZU) / (1 - d)))
            else:
                if ZU == 0:
                    att["outcome"] = "Z_UPPER_ZERO_PROVED"; result = ("ZERO", None, att); break
                if ZL == 0:
                    att["outcome"] = "POSITIVITY_UNRESOLVED"; continue
                def encl(nlo, nhi, e):
                    return (max(Fr(0), nlo / ZU), min(Fr(1), nhi / ZL))
            red = {x: [encl(lo, hi, e) for lo, hi, e in row] for x, row in Nn.items()}; ivs = {}
            for v in range(m.nvars):
                row = []
                for e in R.dec[v]:
                    if e[0] == "C":
                        row.append((Fr(e[1]), Fr(e[1])))
                    else:
                        y, s, eta = e[1], e[2], e[3]; iv = red[y][R.dom[y].index(s)]; row.append((min(Fr(1), eta * iv[0]), min(Fr(1), eta * iv[1])))
                ivs[v] = row
            for v, row in ivs.items():                                                                 # consistency check only (necessary, not sufficient): an unsound route is caught by the labels, not here
                if sum(a for a, _ in row) > 1 or sum(b for _, b in row) < 1:
                    att["outcome"] = "ENCLOSURE_INCONSISTENT_ROW_%d" % v; raise Refuse("UNSOUND_ROUTE", "enclosure of variable %d does not bracket a simplex row (route %s/%s): arithmetic premise violated; route abandoned" % (v, route, prec))
            w = max((b - a) for row in ivs.values() for a, b in row); att["max_width"] = str(w); att["outcome"] = "INTERVALS" if w <= PB.MAX_WIDTH else "TOO_WIDE"; rec["values_hex"] = {"Z": [toks[0], toks[1]]}
            if w <= PB.MAX_WIDTH:
                result = ("OK", ivs, att); break
        except Refuse as ex:
            att["refused"] = {"kind": ex.kind, "reason": ex.reason}
            if ex.kind == "RANGE" and route == "mpfr":                                                 # an exponent-range obstruction: more mantissa bits cannot cure it (review R2-N2)
                rec["stop"] = {"kind": "NUMERIC_RANGE", "phase": att.get("stop_phase", "export"), "detail": ex.reason, "mpfr_flags": att.get("mpfr_flags")}; break
            if ex.kind in ("RANGE", "UNSOUND_ROUTE", "FP_ENV"):
                continue
            refuse(ex.kind, ex.reason)
        finally:
            att["wall_s"] = time.monotonic() - t; diag("attempt_finished")
    _set_live(None, None, None, "after_attempts"); mark("numerics")
    if result is None:
        if "stop" in rec and rec["stop"]["kind"] == "MEMORY" and cfg.get("reference_fallback", True) and time.monotonic() < deadline_mono:
            fb = reference_stream(R, deadline_mono); rec["reference_fallback"] = {k: (str(v) if k in ("Z",) else v) for k, v in fb.items() if k != "N"}; mark("reference_fallback")
            if fb["status"] == "COMPLETE":
                Z = fb["Z"]; ivs = {}
                for v in range(m.nvars):
                    row = []
                    for e in R.dec[v]:
                        if e[0] == "C":
                            row.append((Fr(e[1]), Fr(e[1])))
                        else:
                            q = Fr(e[3]) * fb["N"][e[1]][R.dom[e[1]].index(e[2])] / Z if Z > 0 else Fr(0); row.append((q, q))
                    ivs[v] = row
                if Z == 0:
                    rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "exact reference stream: Z = 0", "certifying": True}); _write(out, record_prefix, rec); return rec
                rec.update({"status": "INTERVALS_OK", "certified_intervals": {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}, "max_width": "0", "precision": "exact_integer_reference", "route": "exact_integer_reference", "certifying": True}); _write(out, record_prefix, rec); return rec
            rec["stop"] = {"kind": fb["status"] if fb["status"] in ("DEADLINE", "ROUTE_LIMITATION", "MEMORY") else "NUMERIC_UNRESOLVED", "phase": "reference_fallback", "detail": "visited %s assignments of %s" % (fb.get("visited"), fb.get("total")), "reason": fb.get("reason")}
        kind = (rec.get("stop") or {}).get("kind", "NUMERIC_UNRESOLVED")
        refuse("RESOURCE_STOP" if kind in ("DEADLINE", "MEMORY") else ("ROUTE_LIMITATION" if kind == "ROUTE_LIMITATION" else "NUMERIC_RANGE" if kind == "NUMERIC_RANGE" else "NUMERIC_UNRESOLVED"), json.dumps(rec.get("stop") or {"attempts": [a.get("outcome") or a.get("refused") for a in attempts]}))
    if result[0] == "ZERO":
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": result[2]["outcome"], "certifying": True}); _write(out, record_prefix, rec); return rec
    ivs = result[1]; rec.update({"certified_intervals": {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}, "max_width": result[2]["max_width"], "precision": result[2]["precision"], "route": result[2]["route"], "status": "INTERVALS_OK", "certifying": True}); mark("enclose")
    _write(out, record_prefix, rec); return rec


def reference_stream(R, deadline_mono):
    """exact integer reference over the REDUCED model (GB-07): mixed-radix odometer (no assignment-count gate; resumable); per-factor denominator
    clearing; growable export. Returns COMPLETE / DEADLINE / MEMORY / ROUTE_LIMITATION."""
    L = Lib.get(); facs = sorted(R.factors, key=lambda f: f.fid); vars_ = sorted(R.dom); pos = {v: i for i, v in enumerate(vars_)}
    prog = [len(vars_)] + [len(R.dom[v]) for v in vars_] + [len(facs)]; ints = []
    for f in facs:
        den = 1
        for x in f.table:
            den = den * x.denominator // math.gcd(den, x.denominator)
        prog += [len(f.scope)] + [pos[v] for v in f.scope] + list(f.card) + [len(f.table)]; ints += [str(int(x * den)) for x in f.table]
    total = 1
    for v in vars_:
        total *= len(R.dom[v])
    arr = (ctypes.c_int64 * len(prog))(*prog); sarr = (ctypes.c_char_p * max(1, len(ints)))(*[s.encode() for s in ints]); err = ctypes.c_int(0)
    S = L.gb_ref_create(arr, len(prog), sarr, max(0.0, deadline_mono - time.monotonic()), ctypes.byref(err))
    if not S:
        return {"status": "MEMORY" if err.value == 2 else "ROUTE_LIMITATION", "reason": "reference stream could not be created (%s)" % STOP_NAMES.get(err.value, err.value), "total": str(total)}
    st = L.gb_ref_run(S); vis = L.gb_ref_visited(S)
    if st != 0:
        L.gb_ref_destroy(S); return {"status": STOP_NAMES.get(st, "FAULT") if st in (1, 2) else "ROUTE_LIMITATION", "visited": vis, "total": str(total), "reason": "stream stop %s" % STOP_NAMES.get(st, st)}
    size = 1 << 22
    while True:
        buf = ctypes.create_string_buffer(size); n = L.gb_ref_results(S, buf, size)
        if n >= 0:
            break
        if n == -1 and size < (1 << 31):
            size *= 4; continue
        L.gb_ref_destroy(S); return {"status": "ROUTE_LIMITATION", "reason": "reference export failed (%d)" % n, "visited": vis, "total": str(total)}
    L.gb_ref_destroy(S); toks = buf.value.decode().split(";")[:-1]; Z = Fr(int(toks[0])); N = {}; k = 1
    for v in vars_:
        N[v] = []
        for a in range(len(R.dom[v])):
            N[v].append(Fr(int(toks[k]))); k += 1
    return {"status": "COMPLETE", "Z": Z, "N": N, "visited": vis, "total": str(total)}


def _write(out, prefix, rec):
    p = os.path.join(out, prefix + ".json"); tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


def bound_to_task(rec, task):
    got = rec.get("task") or {}
    return all(got.get(k) == task[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "nvars", "orig_card", "queries_sha256"))


def publish(out, model_path, evid_path, rec, cell_rec, deadline_mono, record_prefix="checked_record", snapshot=None):
    """dyadic-grid publication + ONE separate task-bound verifier process (gbidi.verify). The snapshot's bytes must still be at the caller's paths
    before the verifier runs and after it returns (a concurrent replacement is CHECK_FAILED, never a certificate for the new bytes)."""
    try:
        S = snapshot or GS.Snapshot(model_path, evid_path)
    except GS.InvalidInput as ex:
        cell_rec["reason"] = "publication refused: %s" % ex.reason; return "CHECK_FAILED"
    m = S.model; task = S.task
    if rec.get("status") != "INTERVALS_OK" or not bound_to_task(rec, task):
        cell_rec["reason"] = "publication refused: record is not an INTERVALS_OK record bound to the caller's task"; return "CHECK_FAILED"
    if m.nvars > 0 and (sorted(int(v) for v in rec["certified_intervals"]) != list(range(m.nvars)) or any(len(rec["certified_intervals"][str(v)]) != m.card[v] for v in range(m.nvars))):
        cell_rec["reason"] = "publication refused: interval rows do not match the caller's variables / cardinalities"; return "CHECK_FAILED"
    tmp = os.path.join(out, "output.MAR.tmp")
    if m.nvars == 0:
        open(tmp, "w").write("MAR\n0\n"); cell_rec["publication"] = {"rows": 0, "note": "empty query result (no variables); verified by the common separate protocol"}; cell_rec["certified"] = {"max_width": "0", "max_width_float": 0.0, "delivered_max_width": "0", "width_met": True, "point_target_met": False, "precision": rec.get("precision"), "route": rec.get("route")}
        json.dump({"intervals": [], "eps": "1/200"}, open(os.path.join(out, "intervals.json"), "w"))
    else:
        ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in rec["certified_intervals"].items()}; pts, prep = PB.publish_rows(ivs, m.card)
        cell_rec["publication"] = {k: prep[k] for k in ("grid_bits", "eps", "max_width", "max_width_observed", "max_width_published_grid", "width_met", "point_feasible_all_rows", "status")}
        cell_rec["certified"] = {"max_width": prep["max_width_observed"], "max_width_float": float(Fr(prep["max_width_observed"])), "delivered_max_width": prep["max_width_published_grid"], "delivered_max_width_float": float(Fr(prep["max_width_published_grid"])), "width_met": prep["width_met"], "point_target_met": False, "precision": rec.get("precision"), "route": rec.get("route")}
        json.dump({"intervals": [{"var": v, "intervals": [[str(a), str(b)] for a, b in prep["widened_intervals"][v]]} for v in range(m.nvars)], "eps": "1/200"}, open(os.path.join(out, "intervals.json"), "w"))
        if pts is None:
            return prep["status"]
        PB.write_mar(tmp, pts, m.card)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    if not S.path_still_matches():
        cell_rec["reason"] = "the caller's files changed after the snapshot was taken (before verification)"; return "CHECK_FAILED"
    vp = os.path.join(out, "point_check.json")
    if os.path.exists(vp):
        os.remove(vp)
    remaining = max(0.2, deadline_mono - time.monotonic())
    cmd = [sys.executable, "-m", "gbidi.verify", os.path.join(out, record_prefix + ".json"), tmp, os.path.abspath(model_path), os.path.abspath(evid_path), vp]
    try:
        with open(os.path.join(out, "point_check.log"), "ab") as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONPATH=HERE), cwd=HERE, timeout=remaining + 1.0)
    except subprocess.TimeoutExpired:
        cell_rec["reason"] = "point verifier exceeded the remaining deadline"; return "RESOURCE_STOP"
    v = json.load(open(vp)) if os.path.exists(vp) else {"status": "POINT_REJECTED", "reason": "no record"}; cell_rec["point_check"] = v
    if v.get("status") != "POINT_VERIFIED":
        cell_rec["reason"] = "independent point verification: %s" % v.get("reason"); return "CHECK_FAILED"
    if not S.path_still_matches() or v.get("task", {}).get("raw_model_sha256") != task["raw_model_sha256"]:
        cell_rec["reason"] = "the caller's files changed during verification"; return "CHECK_FAILED"
    os.replace(tmp, os.path.join(out, "output.MAR")); cell_rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); cell_rec["certified"]["point_target_met"] = True
    return "CERTIFIED"
