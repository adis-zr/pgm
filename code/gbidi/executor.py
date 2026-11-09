"""GENERAL_BIDI_V1 / NATIVE_PLAIN_V1 certifying executor (ONE authoritative numerical pass; trusted component).

Pipeline per cell: bind task (ext.uai parse of the caller's files) -> shared qualified source reductions (adp.source; recorded) -> plan (gbidi.plan,
untrusted proposals re-derived here from the reduced model: the planner's structures are rebuilt from R, never from the recognizer's numbers) ->
numerical policy (binary64 admitted only if the ACTUAL plan's range/depth proof succeeds; else MPFR outward at p in 64,128,256,512) -> native
execution (gbidi/kernel.cpp: values, local reverse, counters, category caps, deadline polling) -> exact enclosures per ORIGINAL (variable, state)
through the reduction decoder -> publication (adp.publish dyadic grid) -> separate task-bound point verifier (adp.checker --verify-point).
Fallback: the exact integer reference stream (GB-07) on the reduced model within the remaining deadline when the planned route stops for memory.

Trust boundary (stated plainly): this module, ext.uai, adp.source's reductions, the planner, the native kernel (+ MPFR/GMP), adp.publish and the
point verifier are the TRUSTED/QUALIFIED components; there is no second independent numerical implementation per benchmark cell."""
from __future__ import annotations
import os, sys, json, time, math, hashlib, ctypes, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U
from adp import source as SRC, publish as PB
from gbidi import plan as PL

U53 = Fr(1, 2 ** 53); DBL_MIN = Fr(2) ** -1022; DBL_MAX = Fr(2 ** 1024 - 2 ** 971)
LIB = os.path.join(HERE, "gbidi", "libgbidi_kernel." + ("dylib" if sys.platform == "darwin" else "so")); BUILD_RECORD = os.path.join(HERE, "gbidi", "BUILD_RECORD.json")
SCHEDULE_ID = "GENERAL_BIDI_V1/bucket-core-views-demand-fused-localreverse/v1"; PRECISIONS = (64, 128, 256, 512)
ARMS = {"GENERAL_BIDI_V1": {"views": True, "demand_masks": True, "fusion": True, "orders": ["original", "min_fill", "min_volume"]},
        "NATIVE_PLAIN_V1": {"views": False, "demand_masks": False, "fusion": False, "orders": ["min_volume"]},
        "A1_NO_DEMAND_MASKS": {"views": True, "demand_masks": False, "fusion": True, "orders": ["original", "min_fill", "min_volume"]},
        "A2_NO_FUSION": {"views": True, "demand_masks": True, "fusion": False, "orders": ["original", "min_fill", "min_volume"]},
        "A3_NO_RESPONSE_VIEWS": {"views": False, "demand_masks": True, "fusion": True, "orders": ["original", "min_fill", "min_volume"]}}
STOP_NAMES = {0: "OK", 1: "DEADLINE", 2: "MEMORY", 3: "OVERFLOW", 4: "RANGE", 5: "BADPROG"}


class Refuse(Exception):
    def __init__(self, kind, reason):
        super().__init__(reason); self.kind = kind; self.reason = reason


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def task_binding(model_path, evid_path, m):
    canon = lambda p: hashlib.sha256((" ".join(open(p).read().split())).encode()).hexdigest(); q = list(range(m.nvars))
    return {"raw_model_sha256": sha_file(model_path), "raw_evidence_sha256": sha_file(evid_path), "canonical_model_sha256": canon(model_path), "canonical_evidence_sha256": canon(evid_path), "nvars": m.nvars, "orig_card": list(m.card), "queries": q, "queries_sha256": hashlib.sha256(json.dumps(q).encode()).hexdigest(), "eps": "1/200", "max_width": "1/100"}


class _FactorAdapter:
    """ext.uai Factor -> the attribute set adp.source.Reduced reads (scope, card, table, origin, strides()); arity-0 factors admitted."""
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
            L.gb_schedule_id.restype = c.c_char_p; L.gb_mpfr_version.restype = c.c_char_p; L.gb_gmp_version.restype = c.c_char_p; L.gb_mpfr_emin.restype = c.c_long; L.gb_mpfr_emax.restype = c.c_long
            L.gb_create.restype = c.c_void_p; L.gb_create.argtypes = [c.c_int, c.c_int, c.POINTER(c.c_int64), c.c_int64, c.POINTER(c.c_char_p), c.POINTER(c.c_double), c.c_int64, c.c_int64, c.POINTER(c.c_uint64), c.c_double]
            L.gb_destroy.argtypes = [c.c_void_p]; L.gb_forward.argtypes = [c.c_void_p]; L.gb_forward.restype = c.c_int; L.gb_reverse.argtypes = [c.c_void_p]; L.gb_reverse.restype = c.c_int
            L.gb_counters.argtypes = [c.c_void_p, c.POINTER(c.c_uint64)]; L.gb_results_hex.argtypes = [c.c_void_p, c.c_char_p, c.c_int64]; L.gb_results_hex.restype = c.c_int
            L.gb_test_split_root.argtypes = [c.c_void_p, c.c_char_p, c.c_char_p, c.c_int]; L.gb_test_split_root.restype = c.c_int
            L.gb_ref_create.restype = c.c_void_p; L.gb_ref_create.argtypes = [c.POINTER(c.c_int64), c.c_int64, c.POINTER(c.c_char_p), c.c_double]; L.gb_ref_run.argtypes = [c.c_void_p]; L.gb_ref_run.restype = c.c_int
            L.gb_ref_visited.argtypes = [c.c_void_p]; L.gb_ref_visited.restype = c.c_uint64; L.gb_ref_results.argtypes = [c.c_void_p, c.c_char_p, c.c_int64]; L.gb_ref_results.restype = c.c_int; L.gb_ref_destroy.argtypes = [c.c_void_p]
            if L.gb_schedule_id().decode() != SCHEDULE_ID:
                raise Refuse("FP_ENV", "kernel schedule id mismatch")
            cls._lib = L; cls.build = br
        return cls._lib


def flatten_program(P):
    """Flat int64 program + rational value strings (factor entries, then view ratios, then the reduced scale). Index arithmetic in Python ints,
    checked against int64 before conversion."""
    R = P.R; prog = []; qs = []; fid_pos = {}
    facs = sorted(P.fac.values(), key=lambda f: f.fid)
    prog.append(len(facs))
    for f in facs:
        fid_pos[f.fid] = len(fid_pos); prog += [len(f.scope)] + list(f.scope) + list(f.card) + [len(f.table), len(qs)]
        qs += ["%d/%d" % (x.numerator, x.denominator) for x in f.table]
    nfac = len(qs)
    prog.append(len(P.nodes))
    for nd in P.nodes:
        prog += [nd.x, nd.x_card, len(nd.inputs)]
        for kind, ref in nd.inputs:
            prog += [0 if kind == "F" else 1, fid_pos[ref] if kind == "F" else ref]
        prog += [len(nd.scope)] + list(nd.scope)
        for w in nd.scope:
            v = nd.views[w]; prog += [len(v.cls)] + list(v.cls) + [len(v.reps)] + list(v.reps) + [len(qs) - nfac]
            qs += ["%d/%d" % (r.numerator, r.denominator) for r in v.ratio]
        prog += [nd.core_entries, -1 if nd.consumer is None else nd.consumer, 1 if nd.materialize else 0]
        dem = [] if nd.demand == "FULL" else list(nd.demand); prog += [len(dem)] + dem
    prog += [len(P.roots)] + list(P.roots)
    qs.append("%d/%d" % (R.scale.numerator, R.scale.denominator)); nratio = len(qs) - nfac - 1
    for x in prog:
        if not (-(2 ** 63) <= x < 2 ** 63):
            raise Refuse("REJECTED", "program index exceeds int64")
    return prog, qs, nfac, nratio


# ----------------------------------------------------------------------------------------------------------------------- binary64 admission (GB-09) for the ACTUAL plan
def binary64_admission(P):
    """Conservative family bounds and depth labels of the planned schedule (forward values + local reverse). Every positive exact intermediate of
    node n is a sum of at most rows(n) monomials over distinct factor occurrences times view scales; exponent bounds propagate as in
    numerics_and_validation.txt §5 (products add exponents; a K-term sum adds ceil(log2 K)); depth: leaf 1, sum max+1, product sum+1 with the
    row product depth = sum of input depths + k, the entry sum depth = row depth + xc, the reverse adds the sibling products and the adjoint.
    Returns (ok, record). ok requires every bound inside [2^-1022 * 2, DBL_MAX / 2] with delta = E_max*u <= 1/2 and all leaves convertible."""
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
                        lo *= min(Fr(1), r); hi *= max(Fr(1), r)                                   # view scales are extra multiplicative leaves on a monomial
        if R.scale > 0:
            lo *= min(Fr(1), R.scale); hi *= max(Fr(1), R.scale)
        v = sum(len(d) for d in R.dom.values()); logK = sum(math.ceil(math.log2(len(d))) for d in R.dom.values())
        # depth: per node E_entry = E_rowprod + xc ; E_rowprod = sum over inputs E_in + k ; messages recursively; reverse doubles it conservatively
        E = {}
        for nd in P.nodes:
            e = 0
            for kind, ref in nd.inputs:
                e += (1 if kind == "F" else E[ref] + 2)                                              # child core value (+1 scale multiply +1)
            e += len(nd.inputs) + nd.x_card; E[nd.nid] = e
        E_fwd = max(E.values()) if E else 1; E_rev = 2 * E_fwd + len(P.roots) + 4
        e_total = 2 * (E_rev + 2); delta = Fr(e_total) * U53
        rec.update({"log2_lo": PL.math.log2(lo.numerator) - PL.math.log2(lo.denominator), "log2_hi": PL.math.log2(hi.numerator) - PL.math.log2(hi.denominator) + logK, "E_fwd": E_fwd, "E_rev": E_rev, "e": e_total, "delta": float(delta)})
        if delta > Fr(1, 2):
            rec["checks"].append("delta > 1/2"); return False, rec
        if lo / 2 < DBL_MIN or (hi * (2 ** logK)) * 2 > DBL_MAX:
            rec["checks"].append("range envelope outside normal binary64"); return False, rec
        rec["checks"].append("range + depth OK"); return True, dict(rec, delta_fr=delta)
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


# ----------------------------------------------------------------------------------------------------------------------- MPFR hex parsing
def mpfr_hex_to_fr(s):
    """'mantissa@exp' from mpfr_get_str base 16 (mantissa digits d_1 d_2 ... represent 0.d_1d_2... * 16^exp)"""
    if s == "0":
        return Fr(0)
    mant, e = s.split("@"); neg = mant.startswith("-"); mant = mant.lstrip("-"); e = int(e)
    val = Fr(int(mant, 16), 16 ** len(mant)) * (Fr(16) ** e)
    return -val if neg else val


def dbl_hex_to_fr(s):
    return Fr(float.fromhex(s))


# ----------------------------------------------------------------------------------------------------------------------- the executor
def execute(arm, model_path, evid_path, out, deadline_mono, cfg, phases=None, record_prefix="checked_record", test_hooks=None):
    ph = phases if phases is not None else {}; t0 = [time.monotonic()]
    def mark(name):
        t = time.monotonic(); ph[name] = ph.get(name, 0.0) + (t - t0[0]); t0[0] = t
    os.makedirs(out, exist_ok=True)
    for stale in (os.path.join(out, record_prefix + ".json"), os.path.join(out, "output.MAR"), os.path.join(out, "intervals.json")):
        if os.path.exists(stale):
            os.remove(stale)
    rec = {"executor": "gbidi.executor", "arm": arm, "schedule_id": SCHEDULE_ID, "status": None, "model_path": os.path.abspath(model_path), "evidence_path": os.path.abspath(evid_path), "mechanisms": {}}
    m = U.read_model(model_path); m.check(); ev = U.read_evidence(evid_path)
    for v, s in ev.items():
        if not (0 <= v < m.nvars and 0 <= s < m.card[v]):
            raise Refuse("REJECTED", "evidence outside the model")
    rec["task"] = task_binding(model_path, evid_path, m); mark("parse_bind")
    if m.nvars == 0:
        Z = Fr(1)
        for f in m.factors:
            Z *= f.table[0]
        rec.update({"status": "ZERO_EVIDENCE_PROVED" if Z == 0 else "INTERVALS_OK", "certified_intervals": {}, "Z_exact": str(Z), "reason": "no variables: Z is the scalar product; empty query result"}); _write(out, record_prefix, rec); return rec
    # ---- shared qualified reductions (common to every new arm; recorded)
    R = SRC.Reduced(_ModelAdapter(m), dict(ev)); disc_wall = min(1.0, 0.05 * cfg["budget_s"]); rules = list(cfg.get("rules", PL.COMMON_RULES))
    rrec = R.reduce(rules, deadline=time.monotonic() + disc_wall); rec["reductions"] = {"rules": rules, "steps": {k: sum(1 for s in R.steps if s[0] == k) for k in set(s[0] for s in R.steps)}, "recognition": rrec, "free_reduced": len(R.dom), "scale": str(R.scale), "zero_proof": R.zero_proof, "reduced_hash": R.reduced_hash(), "note": PL.COMMON_RULES_NOTE[:200] + "..."}
    mark("source_reductions")
    if R.zero_proof is not None:
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "structural zero: %s" % json.dumps(R.zero_proof)}); _write(out, record_prefix, rec); return rec
    # ---- plan (optional discovery shares the wall allowance)
    acfg = dict(ARMS[arm]); acfg["bytes_per_entry"] = 2 * (32 + 8 * 2)
    if not R.dom:
        Z = R.scale
        ivs = {v: [(Fr(e[1]), Fr(e[1])) if e[0] == "C" else (Fr(0), Fr(1)) for e in R.dec[v]] for v in range(m.nvars)}
        rec.update({"status": "INTERVALS_OK", "certified_intervals": {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}, "Z_exact": str(Z), "precision": "exact", "plan": {"nodes": 0}}); _write(out, record_prefix, rec); return rec
    P, table = PL.plan(R, acfg, deadline=time.monotonic() + disc_wall); rec["plan"] = P.record(); rec["plan_candidates"] = table; rec["mechanisms"] = P.mechanisms; mark("plan")
    prog, qs, nfac, nratio = flatten_program(P); mark("flatten")
    # ---- numerical policy
    L = Lib.get(); rec["backend"] = {"build": {k: Lib.build[k] for k in ("binary_sha256", "source_sha256", "compiler_version", "flags", "linked_libraries_sha256")}, "mpfr": L.gb_mpfr_version().decode(), "gmp": L.gb_gmp_version().decode(), "emin": L.gb_mpfr_emin(), "emax": L.gb_mpfr_emax()}
    caps = (ctypes.c_uint64 * 5)(PL.CAPS["value_cache"], PL.CAPS["source_ir_maps_output"], PL.CAPS["reverse_pinned"], PL.CAPS["pending_adjoints"], PL.CAPS["frames_scratch_publication"])
    ok64, a64 = binary64_admission(P) if cfg.get("allow_binary64", True) else (False, {"route": "binary64", "checks": ["disabled by config"]}); rec["binary64_admission"] = a64; mark("numeric_policy")
    attempts = []; result = None
    routes = ([("binary64", 53)] if ok64 else []) + [("mpfr", p) for p in PRECISIONS]
    prog_arr = (ctypes.c_int64 * len(prog))(*prog); qs_arr = (ctypes.c_char_p * len(qs))(*[q.encode() for q in qs])
    for route, prec in routes:
        if time.monotonic() > deadline_mono:
            rec["stop"] = {"kind": "DEADLINE", "detail": "before attempt %s/%d" % (route, prec)}; break
        att = {"route": route, "precision": prec}; t = time.monotonic()
        try:
            dbl = None
            if route == "binary64":
                dbl = (ctypes.c_double * len(qs))(*[to_double_checked(Fr(q), i) for i, q in enumerate(qs)])
            H = L.gb_create(1 if route == "binary64" else 0, prec, prog_arr, len(prog), qs_arr, dbl, nfac, nratio, caps, max(0.0, deadline_mono - time.monotonic()))   # REMAINING seconds: the kernel uses its own clock (macOS: Python monotonic != CLOCK_MONOTONIC)
            if not H:
                raise Refuse("REJECTED", "kernel refused the program")
            try:
                st = L.gb_forward(H); att["forward_s"] = time.monotonic() - t; cnt = (ctypes.c_uint64 * 16)(); L.gb_counters(H, cnt); att["counters_after_forward"] = list(cnt)[:11]
                if st != 0:
                    att["stop"] = STOP_NAMES.get(st, st); attempts.append(att); L.gb_counters(H, cnt); att["counters"] = _counters(cnt)
                    if st == 1:
                        rec["stop"] = {"kind": "DEADLINE", "phase": "forward", "detail": "native forward stream"}; break
                    if st == 2:
                        rec["stop"] = {"kind": "MEMORY", "phase": "forward"}; break
                    raise Refuse("REJECTED", "kernel forward stop %s" % att["stop"])
                t2 = time.monotonic()
                if test_hooks and "split_root" in test_hooks:
                    w1, w2, ev_ = test_hooks["split_root"]; st = L.gb_test_split_root(H, w1.encode(), w2.encode(), 1 if ev_ else 0)
                else:
                    st = L.gb_reverse(H)
                att["reverse_s"] = time.monotonic() - t2; L.gb_counters(H, cnt); att["counters"] = _counters(cnt)
                if st != 0:
                    att["stop"] = STOP_NAMES.get(st, st); attempts.append(att)
                    if st == 1:
                        rec["stop"] = {"kind": "DEADLINE", "phase": "reverse"}; break
                    if st == 2:
                        rec["stop"] = {"kind": "MEMORY", "phase": "reverse"}; break
                    raise Refuse("REJECTED", "kernel reverse stop %s" % att["stop"])
                buf = ctypes.create_string_buffer(1 << 24); n = L.gb_results_hex(H, buf, 1 << 24)
                if n < 0:
                    raise Refuse("REJECTED", "result buffer too small")
                toks = buf.value.decode().split(";")[:-1]; conv = dbl_hex_to_fr if route == "binary64" else mpfr_hex_to_fr
                ZL, ZU = conv(toks[0]), conv(toks[1]); k = 2; Nn = {}
                for nd in P.nodes:
                    Nn[nd.x] = []
                    for a in range(nd.x_card):
                        Nn[nd.x].append((conv(toks[k]), conv(toks[k + 1]))); k += 2
            finally:
                L.gb_destroy(H)
            if route == "binary64":
                delta = a64["delta_fr"]; ZL = ZU = ZL
                if ZU == 0:
                    att["outcome"] = "Z_ZERO_PROVED"; attempts.append(att); result = ("ZERO", None, att); break
                encl = lambda nlo, nhi: (max(Fr(0), (1 - delta) * (nlo / ZU)), min(Fr(1), (nhi / ZU) / (1 - delta)))
            else:
                if ZU == 0:
                    att["outcome"] = "Z_UPPER_ZERO_PROVED"; attempts.append(att); result = ("ZERO", None, att); break
                if ZL == 0:
                    att["outcome"] = "POSITIVITY_UNRESOLVED"; attempts.append(att); continue
                encl = lambda nlo, nhi: (max(Fr(0), nlo / ZU), min(Fr(1), nhi / ZL))
            red = {}
            for x, row in Nn.items():
                red[x] = [encl(lo, hi) for lo, hi in row]
            ivs = {}
            for v in range(m.nvars):
                row = []
                for e in R.dec[v]:
                    if e[0] == "C":
                        row.append((Fr(e[1]), Fr(e[1])))
                    else:
                        y, s, eta = e[1], e[2], e[3]; iv = red[y][R.dom[y].index(s)]; row.append((min(Fr(1), eta * iv[0]), min(Fr(1), eta * iv[1])))
                ivs[v] = row
            w = max((b - a) for row in ivs.values() for a, b in row); att["max_width"] = str(w); att["outcome"] = "INTERVALS" if w <= PB.MAX_WIDTH else "TOO_WIDE"; attempts.append(att)
            rec["values_hex"] = {"Z": [toks[0], toks[1]]}
            if w <= PB.MAX_WIDTH:
                result = ("OK", ivs, att); break
        except Refuse as ex:
            att["refused"] = {"kind": ex.kind, "reason": ex.reason}; attempts.append(att)
            if ex.kind == "RANGE":
                continue
            raise
    rec["attempts"] = attempts; mark("numerics")
    if result is None:
        if "stop" in rec and rec["stop"]["kind"] == "MEMORY" and cfg.get("reference_fallback", True) and time.monotonic() < deadline_mono:
            fb = reference_stream(R, deadline_mono); rec["reference_fallback"] = fb; mark("reference_fallback")
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
                    rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "exact reference stream: Z = 0"}); _write(out, record_prefix, rec); return rec
                rec.update({"status": "INTERVALS_OK", "certified_intervals": {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}, "max_width": "0", "precision": "exact_integer_reference"}); _write(out, record_prefix, rec); return rec
            rec["stop"] = {"kind": "DEADLINE", "phase": "reference_fallback", "detail": "visited %s of %s" % (fb.get("visited"), fb.get("total"))}
        kind = (rec.get("stop") or {}).get("kind", "NUMERIC_UNRESOLVED"); raise Refuse("RESOURCE_STOP" if kind in ("DEADLINE", "MEMORY") else "NUMERIC_UNRESOLVED", json.dumps(rec.get("stop") or {"attempts": [a.get("outcome") for a in attempts]}))
    if result[0] == "ZERO":
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": result[2]["outcome"]}); _write(out, record_prefix, rec); return rec
    ivs = result[1]; rec["certified_intervals"] = {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}; rec["max_width"] = result[2]["max_width"]; rec["precision"] = result[2]["precision"]; rec["route"] = result[2]["route"]; rec["status"] = "INTERVALS_OK"; mark("enclose")
    _write(out, record_prefix, rec); return rec


def _counters(cnt):
    k = ["rows", "mults", "adds", "lookups", "fused_reevals", "entries_materialized", "entries_demanded", "adj_increments", "deltas_drained", "recomputations", "polls", "used_values_bytes", "used_index_bytes", "used_reverse_bytes", "used_scratch_bytes"]
    return {k[i]: int(cnt[i]) for i in range(len(k))}


def reference_stream(R, deadline_mono):
    """exact integer reference over the REDUCED model (GB-07): per-factor denominator clearing, one common scale cancels in N/Z"""
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
    if total >= 2 ** 63:
        return {"status": "ROUTE_LIMITATION", "reason": "assignment count exceeds uint64", "total": str(total)}
    arr = (ctypes.c_int64 * len(prog))(*prog); sarr = (ctypes.c_char_p * max(1, len(ints)))(*[s.encode() for s in ints])
    S = L.gb_ref_create(arr, len(prog), sarr, max(0.0, deadline_mono - time.monotonic())); st = L.gb_ref_run(S); vis = L.gb_ref_visited(S)
    if st != 0:
        L.gb_ref_destroy(S); return {"status": "DEADLINE", "visited": vis, "total": total}
    buf = ctypes.create_string_buffer(1 << 22); n = L.gb_ref_results(S, buf, 1 << 22); L.gb_ref_destroy(S)
    toks = buf.value.decode().split(";")[:-1]; Z = Fr(int(toks[0])); N = {}; k = 1
    for v in vars_:
        N[v] = []
        for a in range(len(R.dom[v])):
            N[v].append(Fr(int(toks[k]))); k += 1
    return {"status": "COMPLETE", "Z": Z, "N": N, "visited": vis, "total": total}


def _write(out, prefix, rec):
    p = os.path.join(out, prefix + ".json"); tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


def bound_to_task(rec, task):
    got = rec.get("task") or {}
    return all(got.get(k) == task[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "nvars", "orig_card", "queries_sha256"))


def publish(out, model_path, evid_path, rec, cell_rec, deadline_mono, record_prefix="checked_record"):
    m = U.read_model(model_path); task = task_binding(model_path, evid_path, m)
    if rec.get("status") != "INTERVALS_OK" or not bound_to_task(rec, task):
        cell_rec["reason"] = "publication refused: record is not an INTERVALS_OK record bound to the caller's task"; return "CHECK_FAILED"
    if m.nvars == 0:
        cell_rec["publication"] = {"rows": 0, "note": "empty query result (no variables)"}; open(os.path.join(out, "output.MAR"), "w").write("MAR\n0\n"); cell_rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); return "CERTIFIED"
    if sorted(int(v) for v in rec["certified_intervals"]) != list(range(m.nvars)) or any(len(rec["certified_intervals"][str(v)]) != m.card[v] for v in range(m.nvars)):
        cell_rec["reason"] = "publication refused: interval rows do not match the caller's variables / cardinalities"; return "CHECK_FAILED"
    ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in rec["certified_intervals"].items()}
    pts, prep = PB.publish_rows(ivs, m.card); cell_rec["publication"] = {k: prep[k] for k in ("grid_bits", "eps", "max_width", "max_width_observed", "width_met", "point_feasible_all_rows", "status")}
    cell_rec["certified"] = {"max_width": prep["max_width_observed"], "max_width_float": float(Fr(prep["max_width_observed"])), "width_met": prep["width_met"], "point_target_met": False, "precision": rec.get("precision"), "route": rec.get("route")}
    json.dump({"intervals": [{"var": v, "intervals": [[str(a), str(b)] for a, b in prep["widened_intervals"][v]]} for v in range(m.nvars)], "eps": "1/200"}, open(os.path.join(out, "intervals.json"), "w"))
    if pts is None:
        return prep["status"]
    tmp = os.path.join(out, "output.MAR.tmp"); PB.write_mar(tmp, pts, m.card)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    vp = os.path.join(out, "point_check.json")
    if os.path.exists(vp):
        os.remove(vp)
    remaining = max(0.2, deadline_mono - time.monotonic())
    cmd = [sys.executable, "-m", "adp.checker", "--verify-point", os.path.join(out, record_prefix + ".json"), tmp, os.path.abspath(model_path), os.path.abspath(evid_path), vp]
    try:
        with open(os.path.join(out, "point_check.log"), "ab") as log:
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONPATH=HERE), cwd=HERE, timeout=remaining + 1.0)
    except subprocess.TimeoutExpired:
        cell_rec["reason"] = "point verifier exceeded the remaining deadline"; return "RESOURCE_STOP"
    v = json.load(open(vp)) if os.path.exists(vp) else {"status": "POINT_REJECTED", "reason": "no record"}; cell_rec["point_check"] = v
    if v.get("status") != "POINT_VERIFIED":
        cell_rec["reason"] = "independent point verification: %s" % v.get("reason"); return "CHECK_FAILED"
    os.replace(tmp, os.path.join(out, "output.MAR")); cell_rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); cell_rec["certified"]["point_target_met"] = True
    return "CERTIFIED"
