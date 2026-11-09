"""TRUSTED certifying executor of the BIDI pilot (the ONE authoritative numerical pass).

It re-parses the caller's model / evidence ITSELF with ext.uai (the recognizer also uses ext.uai: this is a trusted-executor boundary
against the untrusted PLAN, not parser-implementation diversity), validates the untrusted recognizer's structural plan against its own parse (binary variables, pairwise factors, bipartite sides, exact single consumption of every factor occurrence, orientation),
absorbs evidence as exact indicator unaries, proves the exact normal-range bound and the error-depth bound for the ACTUAL schedule,
converts every source rational to binary64 and VERIFIES each conversion by exact rational comparison, runs the frozen native kernel (or
the MPFR-53 reference) in bounded blocks with deadline polling, checks completion/finiteness/positivity, forms the rigorous enclosure
  q in [(1-delta) r, r/(1-delta)] intersect [0,1],  r = Nhat/Zhat exact,  delta = e*u,  e >= E_N + E_Z,  u = 2^-53
with exact rationals, publishes through the proved outward dyadic-grid construction (adp.publish) and re-verifies the delivered decimals
with the separate task-bound point verifier (adp.checker --verify-point). The record it writes is the certifier's output, bound to the
caller's task; the recognizer's claims never enter the numbers.

Trust boundary (stated plainly): this executor, its kernel, parsing, indexing, arithmetic, range/depth checks and publication are the
TRUSTED/QUALIFIED components. There is no second independent numerical implementation per benchmark cell."""
from __future__ import annotations
import os, sys, json, time, math, hashlib, ctypes, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE)
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from ext import uai as U
from adp import publish as PB

U53 = Fr(1, 2 ** 53)                                   # unit roundoff of binary64 round-to-nearest (and of MPFR precision 53 nearest)
DBL_MIN = Fr(2) ** -1022; DBL_MAX = Fr(2 ** 1024 - 2 ** 971)
SCHEDULE_ID = "BIDI_NATIVE_CERT/gray-lanes-currentleaf-tree-prefixsuffix/v1"
LIB = os.path.join(HERE, "bidi", "libbidi_kernel." + ("dylib" if sys.platform == "darwin" else "so"))
BUILD_RECORD = os.path.join(HERE, "bidi", "BUILD_RECORD.json")


class Refuse(Exception):
    """typed refusal: (kind, reason); kinds: ROUTE_LIMITATION (structure / range outside the kernel's contract), REJECTED (an integrity
    check failed), RESOURCE_STOP (deadline), FP_ENV (floating-point environment / build contract)"""
    def __init__(self, kind, reason):
        super().__init__(reason); self.kind = kind; self.reason = reason


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def task_binding(model_path, evid_path, m):
    canon = lambda p: hashlib.sha256((" ".join(open(p).read().split())).encode()).hexdigest()
    q = list(range(m.nvars))
    return {"raw_model_sha256": sha_file(model_path), "raw_evidence_sha256": sha_file(evid_path), "canonical_model_sha256": canon(model_path), "canonical_evidence_sha256": canon(evid_path),
            "nvars": m.nvars, "orig_card": list(m.card), "queries": q, "queries_sha256": hashlib.sha256(json.dumps(q).encode()).hexdigest()}


# ----------------------------------------------------------------------------------------------------------------------- structure
def validate_structure(m, ev, plan):
    """From the executor's OWN parse: binary domains; only scalar / unary / pair factors; the plan's sides partition the variables and every
    pair factor crosses them; evidence absorbed as exact indicator unaries. Returns the kernel's exact tables with occurrence accounting."""
    if any(c != 2 for c in m.card):
        raise Refuse("ROUTE_LIMITATION", "non-binary variable")
    X = list(plan.get("x_side", [])); Y = list(plan.get("y_side", []))
    if sorted(X + Y) != list(range(m.nvars)) or len(set(X + Y)) != m.nvars:
        raise Refuse("REJECTED", "plan sides do not partition the variables")
    xi = {v: i for i, v in enumerate(X)}; yj = {v: j for j, v in enumerate(Y)}
    mm, nn = len(X), len(Y)
    phi = [[Fr(1), Fr(1)] for _ in range(mm)]; rho = [[Fr(1), Fr(1)] for _ in range(nn)]; kappa = Fr(1)
    psi = {}                                                                     # (i,j) -> [[a0b0,a0b1],[a1b0,a1b1]]
    owned = {"scalar": 0, "unary": 0, "pair": 0, "merged_duplicate_pairs": 0, "merged_duplicate_unaries": 0}
    for f in m.factors:
        if len(f.scope) == 0:
            kappa *= f.table[0]; owned["scalar"] += 1
        elif len(f.scope) == 1:
            v = f.scope[0]
            tgt = phi[xi[v]] if v in xi else rho[yj[v]]
            if tgt != [Fr(1), Fr(1)]:
                owned["merged_duplicate_unaries"] += 1
            tgt[0] *= f.table[0]; tgt[1] *= f.table[1]; owned["unary"] += 1
        elif len(f.scope) == 2:
            a, b = f.scope
            if a == b:
                raise Refuse("ROUTE_LIMITATION", "self-pair factor")
            if (a in xi) == (b in xi):
                raise Refuse("ROUTE_LIMITATION", "pair factor inside one side (not bipartite under the proposed sides)")
            if a in xi:
                i, j = xi[a], yj[b]; tab = [[f.table[0], f.table[1]], [f.table[2], f.table[3]]]              # table order: last scope variable fastest
            else:
                i, j = xi[b], yj[a]; tab = [[f.table[0], f.table[2]], [f.table[1], f.table[3]]]              # scope (y, x): entry index = y*2 + x
            if (i, j) in psi:
                owned["merged_duplicate_pairs"] += 1; old = psi[(i, j)]; tab = [[old[0][0] * tab[0][0], old[0][1] * tab[0][1]], [old[1][0] * tab[1][0], old[1][1] * tab[1][1]]]
            psi[(i, j)] = tab; owned["pair"] += 1
        else:
            raise Refuse("ROUTE_LIMITATION", "factor of arity %d" % len(f.scope))
    if owned["scalar"] + owned["unary"] + owned["pair"] != len(m.factors):
        raise Refuse("REJECTED", "factor occurrence accounting mismatch")
    for v, s in ev.items():
        if not (0 <= s < 2):
            raise Refuse("REJECTED", "evidence state out of domain")
        tgt = phi[xi[v]] if v in xi else rho[yj[v]]
        tgt[1 - s] = Fr(0)                                                       # exact indicator: forbidden state gets weight 0
    return {"m": mm, "n": nn, "X": X, "Y": Y, "phi": phi, "rho": rho, "psi": psi, "kappa": kappa, "owned": owned}


# ----------------------------------------------------------------------------------------------------------------------- range proof
def range_bounds(S):
    """Exact: every positive monomial of distinct factor occurrences lies in [L, U]; every positive exact intermediate of the schedule
    (a sum of at most 2^v monomials, v = m + n) lies in [L, 2^v U]. Factor tables with NO positive entry prove Z = 0 structurally."""
    L = Fr(1); Uu = Fr(1); all_zero = False
    def upd(tab):
        nonlocal L, Uu, all_zero
        pos = [x for x in tab if x > 0]
        if not pos:
            all_zero = True; return
        L *= min(Fr(1), min(pos)); Uu *= max(Fr(1), max(tab))
    for t in S["phi"]:
        upd(t)
    for t in S["rho"]:
        upd(t)
    for tab in S["psi"].values():
        upd([x for r in tab for x in r])
    if S["kappa"] == 0:
        all_zero = True
    elif S["kappa"] > 0:
        L *= min(Fr(1), S["kappa"]); Uu *= max(Fr(1), S["kappa"])
    v = S["m"] + S["n"]
    return {"L": L, "U": Uu, "upper_2v_U": (Fr(2) ** v) * Uu, "v": v, "all_zero_factor": all_zero}


def log2_fr(q):
    """log2 of a positive Fraction without float under/overflow (integer logs)."""
    q = Fr(q); return math.log2(q.numerator) - math.log2(q.denominator)


def check_binary64_range(rb):
    """Normal binary64 with a factor-two margin on both ends (the margin absorbs the rounding factors (1+-u)^E <= 2 for delta <= 1/2).
    Comparisons are exact rational comparisons; the logs are reporting only."""
    lo = rb["L"] / 2; hi = rb["upper_2v_U"] * 2
    if lo < DBL_MIN:
        raise Refuse("ROUTE_LIMITATION", "RANGE: positive intermediates may reach 2^%.1f (with margin) < DBL_MIN = 2^-1022 (log2 L = %.1f)" % (log2_fr(lo), log2_fr(rb["L"])))
    if hi > DBL_MAX:
        raise Refuse("ROUTE_LIMITATION", "RANGE: positive intermediates may reach 2^%.1f (with margin) > DBL_MAX" % log2_fr(hi))
    return {"log2_L": log2_fr(rb["L"]), "log2_2v_U": log2_fr(rb["upper_2v_U"]), "log2_margin_low": log2_fr(lo), "log2_margin_high": log2_fr(hi), "v": rb["v"]}


# ----------------------------------------------------------------------------------------------------------------------- conversion
def to_binary64(q):
    """Nearest binary64 of an exact nonnegative rational (CPython Fraction.__float__: correctly rounded integer division, ties-to-even).
    UNVERIFIED by itself; verify_binary64 below checks every value independently of how it was produced."""
    try:
        return float(Fr(q))
    except OverflowError:
        return math.inf


def verify_binary64(q, x, where):
    """EXACT verification of a converted value: zero <-> 0.0; otherwise finite, positive and (1-u) q <= x <= (1+u) q as rationals."""
    q = Fr(q)
    if q < 0:
        raise Refuse("REJECTED", "negative source entry at %s" % where)
    if q == 0:
        if x != 0.0:
            raise Refuse("REJECTED", "zero source entry at %s did not convert to exact 0.0" % where)
        return 0.0
    if not isinstance(x, float) or not math.isfinite(x) or x <= 0.0:
        raise Refuse("ROUTE_LIMITATION", "conversion of %s at %s is not a finite positive binary64 (exponent range)" % (q, where))
    xf = Fr(x)
    if not ((1 - U53) * q <= xf <= (1 + U53) * q):
        raise Refuse("REJECTED", "conversion of %s at %s violates the (1+-u) bound" % (q, where))
    return x


def to_binary64_checked(q, where):
    return verify_binary64(q, to_binary64(q), where)


def convert_tables(S, conv=to_binary64):
    """Converts with `conv` (replaceable for fault injection) and VERIFIES every converted entry exactly, independently of `conv`."""
    m, n = S["m"], S["n"]
    cv = lambda q, where: verify_binary64(q, conv(q), where)
    phi = [cv(S["phi"][i][a], "phi[%d][%d]" % (i, a)) for i in range(m) for a in range(2)]
    rho = [cv(S["rho"][j][b], "rho[%d][%d]" % (j, b)) for j in range(n) for b in range(2)]
    psi = [0.0] * (m * n * 4); present = 0
    for i in range(m):
        for j in range(n):
            tab = S["psi"].get((i, j))
            for a in range(2):
                for b in range(2):
                    psi[((i * n) + j) * 4 + a * 2 + b] = cv(tab[a][b], "psi[%d][%d][%d][%d]" % (i, j, a, b)) if tab is not None else 1.0
            present += tab is not None
    kappa = cv(S["kappa"], "kappa") if S["kappa"] != 1 else 1.0
    return phi, rho, psi, kappa, present


# ----------------------------------------------------------------------------------------------------------------------- depth proof
def tree_depth(leaf_E, P):
    """E label of the root of the kernel's product tree with P leaves whose labels are leaf_E (padding leaves exact 1.0: label 0), every
    internal node a binary product (E = E_l + E_r + 1), padding products counted like any other multiplication (conservative)."""
    lv = list(leaf_E) + [0] * (P - len(leaf_E))
    while len(lv) > 1:
        lv = [lv[2 * t] + lv[2 * t + 1] + 1 for t in range(len(lv) // 2)]
    return lv[0]


def depth_labels(m, n, k, P, kappa_exact_one):
    """Error-depth labels of the implemented schedule (kernel.cpp / mpfr_ref.py), every binary +/* counted (+1), source leaves E=1."""
    E_A = tree_depth([1] * (n + 1), P)                                           # phi leaf + n psi leaves (absent edges hold exact 1.0 but are labelled 1: conservative)
    E_B = tree_depth([0 if kappa_exact_one else 1] + [1] * n, P)
    E_H = E_A + 1
    E_pre_m = m * (E_H + 1)                                                      # pre[0] exact; pre[i+1] = pre[i] * H_i
    E_T = E_B + E_pre_m + 1
    E_NX_term = E_B + ((m - 1) * (E_H + 1) + 1 if m >= 1 else 0) + 1 + E_A + 1     # bc = B * (pre[i] * suf[i+1]); term = bc * A_i(a)
    E_term = max(E_T, E_NX_term)
    lanes = 1 << k; per_lane_adds = 1 << (n - k)                                 # sequential accumulation in a lane (first add into exact 0 counted)
    E_acc = E_term + per_lane_adds + lanes                                       # + sequential lane reduction (lanes adds, conservative)
    return {"P": P, "E_A": E_A, "E_B": E_B, "E_H": E_H, "E_T": E_T, "E_NX_term": E_NX_term, "E_term": E_term, "lanes": lanes, "per_lane_adds": per_lane_adds, "E_N": E_acc, "E_Z": E_acc, "e": 2 * E_acc}


def certificate_delta(e, u=U53):
    delta = Fr(e) * u
    if delta >= Fr(1, 2):
        raise Refuse("ROUTE_LIMITATION", "PRECISION: delta = e*u = %s >= 1/2 (depth e = %d); the enclosure lemma and the factor-two range margin require delta <= 1/2" % (float(delta), e))
    return delta


def enclose(Nhat, Zhat, delta):
    """Exact-rational enclosure of q = N/Z from the computed binary64 values: q in [(1-delta) r, r/(1-delta)] cap [0,1]; exact zero numerator -> [0,0]."""
    if Nhat == 0.0:
        return (Fr(0), Fr(0))
    r = Fr(Nhat) / Fr(Zhat)
    return (max(Fr(0), (1 - delta) * r), min(Fr(1), r / (1 - delta)))


# ----------------------------------------------------------------------------------------------------------------------- kernels
class NativeKernel:
    """ctypes bridge to the frozen native kernel; verifies the binary against the build record and the floating-point environment."""
    def __init__(self):
        br = json.load(open(BUILD_RECORD))
        if sha_file(LIB) != br["binary_sha256"]:
            raise Refuse("FP_ENV", "kernel binary sha256 differs from the frozen BUILD_RECORD")
        if sha_file(os.path.join(HERE, "bidi", "kernel.cpp")) != br["source_sha256"]:
            raise Refuse("FP_ENV", "kernel source sha256 differs from the frozen BUILD_RECORD (schedule altered?)")
        self.build = br; lib = ctypes.CDLL(LIB); self.lib = lib
        lib.bidi_schedule_id.restype = ctypes.c_char_p; lib.bidi_fp_env_check.restype = ctypes.c_uint32
        lib.bidi_create.restype = ctypes.c_void_p; lib.bidi_create.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.c_double]
        lib.bidi_destroy.argtypes = [ctypes.c_void_p]; lib.bidi_step.restype = ctypes.c_uint64; lib.bidi_step.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.bidi_done.restype = ctypes.c_int; lib.bidi_done.argtypes = [ctypes.c_void_p]
        lib.bidi_finish.restype = ctypes.c_int; lib.bidi_finish.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_uint64)]
        lib.bidi_configs_visited.restype = ctypes.c_uint64; lib.bidi_configs_visited.argtypes = [ctypes.c_void_p]
        lib.bidi_bytes_allocated.restype = ctypes.c_uint64; lib.bidi_bytes_allocated.argtypes = [ctypes.c_void_p]
        lib.bidi_current_ylow.restype = ctypes.c_uint64; lib.bidi_current_ylow.argtypes = [ctypes.c_void_p]
        lib.bidi_tree_leaves.restype = ctypes.c_uint32; lib.bidi_tree_leaves.argtypes = [ctypes.c_void_p]
        sid = lib.bidi_schedule_id().decode()
        if sid != SCHEDULE_ID:
            raise Refuse("FP_ENV", "kernel schedule id %r != expected %r" % (sid, SCHEDULE_ID))
        self.fp_mask = int(lib.bidi_fp_env_check())
        if self.fp_mask != 0:
            raise Refuse("FP_ENV", "floating-point environment check failed (mask %d): binary64 / nearest-even / no contraction contract violated" % self.fp_mask)
        self.S = None

    def create(self, m, n, k, phi, rho, psi, kappa):
        A = lambda xs: (ctypes.c_double * max(1, len(xs)))(*xs)
        self._arrs = (A(phi), A(rho), A(psi))
        self.S = self.lib.bidi_create(m, n, k, self._arrs[0], self._arrs[1], self._arrs[2], ctypes.c_double(kappa))
        if not self.S:
            raise Refuse("ROUTE_LIMITATION", "kernel refused sizes m=%d n=%d k=%d (limits m,n<=60, k<=min(n,12)) or allocation failed" % (m, n, k))
        self.m, self.n, self.k = m, n, k

    def step(self, nsteps):
        return int(self.lib.bidi_step(self.S, nsteps))

    def done(self):
        return bool(self.lib.bidi_done(self.S))

    def visited(self):
        return int(self.lib.bidi_configs_visited(self.S))

    def finish(self):
        Z = ctypes.c_double(); NX = (ctypes.c_double * max(1, 2 * self.m))(); NY = (ctypes.c_double * max(1, 2 * self.n))(); C = (ctypes.c_uint64 * 5)()
        ok = self.lib.bidi_finish(self.S, ctypes.byref(Z), NX, NY, C)
        return Z.value, list(NX)[:2 * self.m], list(NY)[:2 * self.n], {"configs": int(C[0]), "mults": int(C[1]), "adds": int(C[2]), "leaf_updates": int(C[3]), "lanes": int(C[4]), "bytes_allocated": int(self.lib.bidi_bytes_allocated(self.S)), "tree_leaves": int(self.lib.bidi_tree_leaves(self.S))}, bool(ok)

    def destroy(self):
        if self.S:
            self.lib.bidi_destroy(self.S); self.S = None


class MpfrKernel:
    """BIDI_MPFR53_CERT backend: bidi.mpfr_ref.Ref (same schedule, precision 53, nearest)."""
    def __init__(self):
        from bidi import mpfr_ref as MR
        self.MR = MR; self.build = {"backend": "gmpy2 MPFR precision 53 round-to-nearest (bidi/mpfr_ref.py)", "source_sha256": sha_file(os.path.join(HERE, "bidi", "mpfr_ref.py"))}; self.fp_mask = 0

    def create(self, m, n, k, phi, rho, psi, kappa):
        self.m, self.n = m, n; self.R = self.MR.Ref(m, n, k, phi, rho, psi, kappa, precision=53)

    def step(self, nsteps):
        return self.R.step_n(nsteps)

    def done(self):
        return self.R.done()

    def visited(self):
        return self.R.configs_visited

    def finish(self):
        Z, NX, NY, c, complete = self.R.finish()
        return float(Z), [float(x) for x in NX], [float(x) for x in NY], {"configs": c["configs"], "lanes": c["lanes"], "mults": c["mults"], "adds": c["adds"], "leaf_updates": None, "bytes_allocated": None, "tree_leaves": self.R.P}, complete

    def destroy(self):
        self.R = None


# ----------------------------------------------------------------------------------------------------------------------- the executor
def execute(model_path, evid_path, plan, out, deadline_mono, cfg, kernel_factory=NativeKernel, record_prefix="checked_record", conv=to_binary64, phases=None):
    """Runs the complete certifying pipeline. Returns the record dict (also written to out/<record_prefix>.json). Raises Refuse (typed)."""
    ph = phases if phases is not None else {}; t0 = time.monotonic()
    def mark(name):
        nonlocal t0
        t = time.monotonic(); ph[name] = ph.get(name, 0.0) + (t - t0); t0 = t
    rec = {"executor": "bidi.executor", "schedule_id": SCHEDULE_ID, "status": None, "model_path": os.path.abspath(model_path), "evidence_path": os.path.abspath(evid_path)}
    for stale in (os.path.join(out, record_prefix + ".json"), os.path.join(out, "output.MAR"), os.path.join(out, "intervals.json")):
        if os.path.exists(stale):
            os.remove(stale)                                                                                        # a stale record never becomes this task's output
    m = U.read_model(model_path); m.check(); ev = U.read_evidence(evid_path)
    for v, s in ev.items():
        if not (0 <= v < m.nvars and 0 <= s < m.card[v]):
            raise Refuse("REJECTED", "evidence outside the model")
    rec["task"] = task_binding(model_path, evid_path, m); mark("parse_bind")
    if m.nvars == 0:
        raise Refuse("ROUTE_LIMITATION", "model has no variables: no singleton row to publish (Z would be the scalar product)")
    if not isinstance(plan, dict) or plan.get("kind") != "BINARY_BIPARTITE_PAIRWISE_CONDITIONED_STREAM":
        raise Refuse("ROUTE_LIMITATION", "recognizer proposed no bipartite stream plan: %s" % (plan.get("reason") if isinstance(plan, dict) else plan))
    S = validate_structure(m, ev, plan); rec["structure"] = {"m": S["m"], "n": S["n"], "x_side": S["X"], "y_side": S["Y"], "owned": S["owned"], "pair_factors_present": len(S["psi"]), "n_evidence": len(ev)}; mark("validate_structure")
    rb = range_bounds(S)
    if rb["all_zero_factor"]:
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "a factor occurrence (after evidence) has no positive entry: every assignment weight is exactly zero"}); _write(out, record_prefix, rec); return rec
    # Review of 9 Nov 2026 (F1): EVERY backend returns binary64 Z / N to the enclosure, so the exact normal-range predicate is a premise of the
    # certificate for every backend. For the MPFR-53 reference the proof is: under the range theorem every exact intermediate is a normal binary64
    # magnitude, MPFR precision-53 nearest rounding of a normal-range value coincides with binary64 nearest rounding, so the MPFR computation is
    # bitwise the binary64 computation and the final float() conversion is exact. Outside the range the conversion can lose bits (subnormals) or
    # positive mass (zero): the frozen code skipped the predicate for MPFR and published a wrong marginal / a false inconsistency.
    rec["range_proof"] = check_binary64_range(rb)
    if kernel_factory is MpfrKernel:
        rec["range_proof"]["backend_note"] = "MPFR-53 nearest == binary64 nearest on normal-range values; the final binary64 narrowing is therefore exact under this predicate"
    k = int(cfg["lanes_k"]); k = min(k, S["n"])
    P = 1
    while P < S["n"] + 1:
        P <<= 1
    dl = depth_labels(S["m"], S["n"], k, P, S["kappa"] == 1); delta = certificate_delta(dl["e"]); rec["depth"] = dict(dl, delta=str(delta), delta_float=float(delta), u="2^-53"); mark("range_depth_proofs")
    phi, rho, psi, kappa, present = convert_tables(S, conv); rec["conversion"] = {"checked_entries": len(phi) + len(rho) + 4 * present + (0 if S["kappa"] == 1 else 1), "rule": "(1-u) f <= fhat <= (1+u) f verified exactly per entry; zero -> 0.0; absent edges exact 1.0"}; mark("convert_verify")
    K = kernel_factory(); rec["backend"] = {"build": K.build, "fp_env_mask": K.fp_mask}
    K.create(S["m"], S["n"], k, phi, rho, psi, kappa); mark("kernel_init")
    block = int(cfg.get("block_steps", 4096)); total = 1 << (S["n"] - k)
    while not K.done():
        if time.monotonic() > deadline_mono:
            v = K.visited(); K.destroy(); mark("kernel_stream")
            raise Refuse("RESOURCE_STOP", "DEADLINE during the stream: %d of %d configurations visited" % (v, 1 << S["n"]))
        K.step(block)
    Z, NX, NY, counters, complete = K.finish(); K.destroy(); mark("kernel_stream")
    rec["kernel"] = {"configs_expected": 1 << S["n"], "configs_visited": counters["configs"], "complete": complete, "lanes": counters["lanes"], "lanes_k": k, "block_steps": block, "counters": counters, "steps_per_lane": total}
    if not complete or counters["configs"] != (1 << S["n"]):
        raise Refuse("REJECTED", "enumeration incomplete or miscounted: %s" % rec["kernel"])
    vals = [Z] + NX + NY
    if any((not math.isfinite(x)) or x < 0.0 for x in vals):
        raise Refuse("REJECTED", "non-finite or negative computed value")
    rec["values_hex"] = {"Z": Z.hex(), "NX": [x.hex() for x in NX], "NY": [x.hex() for x in NY]}
    if Z == 0.0:
        rec.update({"status": "ZERO_EVIDENCE_PROVED", "reason": "computed Z is exactly 0; under the range proof a positive exact Z cannot round to 0, hence Z = 0 exactly"}); _write(out, record_prefix, rec); return rec
    # internal consistency (fault detector, not independence): every row's two numerators sum to Z within the certified relative error
    two = 2 * delta
    for lbl, row in [("x", NX), ("y", NY)]:
        for t in range(len(row) // 2):
            s = Fr(row[2 * t]) + Fr(row[2 * t + 1])
            if abs(s - Fr(Z)) > two * Fr(Z) * 2:
                raise Refuse("REJECTED", "numerator row %s%d does not sum to Z within the certified error (corrupted value?)" % (lbl, t))
    # enclosures per ORIGINAL variable (x_side / y_side give the original indices; evidence rows become exact [0,0]/[q,q])
    ivs = {}
    for i, v in enumerate(S["X"]):
        ivs[v] = [enclose(NX[2 * i + a], Z, delta) for a in range(2)]
    for j, v in enumerate(S["Y"]):
        ivs[v] = [enclose(NY[2 * j + b], Z, delta) for b in range(2)]
    rec["certified_intervals"] = {str(v): [[str(a), str(b)] for a, b in ivs[v]] for v in range(m.nvars)}
    rec["max_width"] = str(max(b - a for row in ivs.values() for a, b in row)); rec["precision"] = 53; rec["status"] = "INTERVALS_OK"; mark("enclose")
    _write(out, record_prefix, rec)
    return rec


def _write(out, prefix, rec):
    p = os.path.join(out, prefix + ".json"); tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rec, f, default=str); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, p)


def bound_to_task(rec, task):
    got = rec.get("task") or {}
    return all(got.get(k) == task[k] for k in ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "nvars", "orig_card", "queries_sha256"))


def publish(out, model_path, evid_path, rec, cell_rec, record_prefix="checked_record"):
    """Publication from the executor's record: exact grid construction (adp.publish), MAR written, then the SEPARATE task-bound point
    verifier re-parses the delivered decimals against the record on disk. Refuses a record not bound to the caller's task."""
    m = U.read_model(model_path); task = task_binding(model_path, evid_path, m)
    if rec.get("status") != "INTERVALS_OK" or not bound_to_task(rec, task):
        cell_rec["reason"] = "publication refused: record is not an INTERVALS_OK record bound to the caller's task"; return "CHECK_FAILED"
    if sorted(int(v) for v in rec["certified_intervals"]) != list(range(m.nvars)) or any(len(rec["certified_intervals"][str(v)]) != m.card[v] for v in range(m.nvars)):
        cell_rec["reason"] = "publication refused: interval rows do not match the caller's variables / cardinalities"; return "CHECK_FAILED"
    ivs = {int(v): [(Fr(a), Fr(b)) for a, b in row] for v, row in rec["certified_intervals"].items()}
    pts, prep = PB.publish_rows(ivs, m.card); cell_rec["publication"] = {k: prep[k] for k in ("grid_bits", "eps", "max_width", "max_width_observed", "width_met", "point_feasible_all_rows", "status")}
    cell_rec["certified"] = {"max_width": prep["max_width_observed"], "max_width_float": float(Fr(prep["max_width_observed"])), "width_met": prep["width_met"], "point_target_met": False, "precision": rec.get("precision")}
    json.dump({"intervals": [{"var": v, "intervals": [[str(a), str(b)] for a, b in prep["widened_intervals"][v]]} for v in range(m.nvars)], "grid": "executor enclosures widened outward to 2^-%d" % prep["grid_bits"], "eps": "1/200"}, open(os.path.join(out, "intervals.json"), "w"))
    if pts is None:
        return prep["status"]
    tmp = os.path.join(out, "output.MAR.tmp"); PB.write_mar(tmp, pts, m.card)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())                                                                       # review: the delivered MAR is fsynced before the rename (checked_record / cell.json already were)
    vp = os.path.join(out, "point_check.json")
    if os.path.exists(vp):
        os.remove(vp)
    cmd = [sys.executable, "-m", "adp.checker", "--verify-point", os.path.join(out, record_prefix + ".json"), tmp, os.path.abspath(model_path), os.path.abspath(evid_path), vp]
    with open(os.path.join(out, "point_check.log"), "ab") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, PYTHONPATH=HERE), cwd=HERE, timeout=600)
    v = json.load(open(vp)) if os.path.exists(vp) else {"status": "POINT_REJECTED", "reason": "no record"}
    cell_rec["point_check"] = v
    if v.get("status") != "POINT_VERIFIED":
        cell_rec["reason"] = "independent point verification: %s" % v.get("reason"); return "CHECK_FAILED"
    os.replace(tmp, os.path.join(out, "output.MAR")); cell_rec["output_bytes"] = os.path.getsize(os.path.join(out, "output.MAR")); cell_rec["certified"]["point_target_met"] = True
    return "CERTIFIED"
