"""Trusted source boundary of GENERAL_BIDI_COMPLETE_V3 (brief §2, §5): ONE owned byte snapshot per caller input, strict frozen grammar, raw and
canonical hashes derived from THOSE bytes, stable factor OCCURRENCE ids, and the caller-derived task identity.

Grammar (UAI text, whitespace separated; frozen): `MARKOV|BAYES  nvars  card...  nfactors  (arity scope...)*  (entries table...)*`; a table's entries are
exact nonnegative rationals (`a/b` or terminating decimal); the LAST scope variable varies fastest (UAI convention; the internal orientation is the same
row-major order). Strictly rejected (typed INVALID_INPUT): unknown network type, non-integer / negative counts, zero cardinality, a variable repeated inside
one scope, variable ids >= nvars, table length != product of cardinalities, truncated / extra tokens, negative / malformed / non-finite entries, evidence
variable or state out of range, DUPLICATE evidence entries (even with the same value), trailing tokens. Distinct occurrences with identical scopes and
tables are VALID (occurrence id = position). Arity-0 (scalar) factors are VALID and participate in the model. Integer state fields are integers: a
token such as `1.0`, `True`, `"1"` is not an integer state (text grammar: only [0-9]+ tokens are integers).

Hashes: raw sha256 of the bytes; `canonical_v2` = sha256 of a finite TYPED serialization (network type, nvars, cardinalities, ordered factor occurrences
with scope and exact reduced numerator/denominator pairs, canonical evidence); `canonical_legacy` = the historical whitespace-normalized text hash of
gbidi.source (kept under its own name; never compared with v2)."""
from __future__ import annotations
import hashlib, json, re, time, os
from fractions import Fraction as Fr
from ext import uai as U

CANONICAL_VERSION = "gbidi3-canonical-v2"
_INT = re.compile(r"^[0-9]+$")


class InvalidInput(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


class ParseStop(Exception):
    """typed resource stop raised INSIDE parsing (deadline or host-memory category) before the forbidden payload is built"""
    def __init__(self, kind, reason):
        super().__init__("%s: %s" % (kind, reason)); self.kind = kind; self.reason = reason


POLL_TOKENS = 4096
TOKEN_BYTES = 72          # documented proxy per token string (49 B + chars) + list slot
RATIONAL_BYTES = 128      # documented proxy per parsed Fraction (small numerator / denominator)


class _Guard:
    """reserve-before-build + deadline polling for the parser: every `n` tokens / rationals are charged to the host ledger BEFORE they are materialized"""
    __slots__ = ("ledger", "deadline", "count", "charged")

    def __init__(self, ledger=None, deadline=None):
        self.ledger = ledger; self.deadline = deadline; self.count = 0; self.charged = 0

    def reserve(self, nbytes, what):
        if self.ledger is not None:
            from gbidi3 import memory as GM
            try:
                self.ledger.reserve("source_ir_maps_output", nbytes, what); self.charged += nbytes
            except GM.MemoryStop as ex:
                raise ParseStop("MEMORY_CATEGORY", str(ex))

    def tick(self, n=1):
        """ONE cumulative work counter across every parsing / hashing loop: the deadline is polled whenever the counter crosses a multiple of POLL_TOKENS
        (never reset per factor, review E4) or when n == 0 (an explicit check)"""
        before = self.count; self.count += n
        if self.deadline is not None and (n == 0 or self.count // POLL_TOKENS != before // POLL_TOKENS) and time.monotonic() > self.deadline:
            raise ParseStop("DEADLINE", "deadline during source parsing after %d work units" % self.count)


def _int_token(it, what, lo=0):
    try:
        t = next(it)
    except StopIteration:
        raise InvalidInput("truncated input: expected %s" % what)
    if not _INT.match(t):
        raise InvalidInput("%s is not an integer token: %r" % (what, t[:40]))
    v = int(t)
    if v < lo:
        raise InvalidInput("%s must be >= %d, got %d" % (what, lo, v))
    return v


_NUMERAL = re.compile(r"^[+-]?(?:(?P<ip>[0-9]*)(?:\.(?P<fp>[0-9]*))?(?:[eE](?P<ex>[+-]?[0-9]+))?|(?P<num>[0-9]+)/(?P<den>[0-9]+))$")


def numeral_bits_bound(t):
    """upper bound on the bit length of the NUMERATOR and DENOMINATOR that Fraction(t) will build, computed from the TOKEN TEXT before any big integer exists
    (review R-D2): decimal digits contribute 3.33 bits each; a decimal exponent e contributes e * 3.33 bits to the numerator (e > 0) or to the denominator
    (e < 0, plus the fractional digits); a/b contributes its digit counts. Returns (num_bits, den_bits) or None when the token is not a grammar numeral."""
    m = _NUMERAL.match(t)
    if not m:
        return None
    if m.group("num") is not None:
        return (len(m.group("num")) * 3322 // 1000 + 2, len(m.group("den")) * 3322 // 1000 + 2)
    ip = m.group("ip") or ""; fp = m.group("fp") or ""; digits = len(ip) + len(fp); exs = (m.group("ex") or "0")
    sig = exs.lstrip("+-").lstrip("0")
    if len(sig) > 12:
        return (1 << 62, 1 << 62)                                                               # an exponent with more than 12 significant digits is beyond any admissible value: bounded as "enormous" BEFORE any int() conversion (direct-API typed error, no ValueError under the interpreter's digit limit)
    ex = int(exs)
    shift = ex - len(fp)                                                                       # value = int(ip + fp) * 10^shift
    num_bits = digits * 3322 // 1000 + 2 + (shift * 3322 // 1000 + 2 if shift > 0 else 0); den_bits = 2 + ((-shift) * 3322 // 1000 + 2 if shift < 0 else 0)
    return (num_bits, den_bits)


def _rational_token(t, what, guard=None):
    if t.lower() in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity"):
        raise InvalidInput("%s is not finite: %r" % (what, t))
    bb = numeral_bits_bound(t)
    if bb is None:
        raise InvalidInput("%s is not an exact rational numeral of the grammar: %r" % (what, t[:40]))
    if guard is not None:
        nb, db = bb; extra = (nb + db) // 8 * 3 + 2 * len(t)                                  # numerator + denominator limbs, the gcd / normalization temporaries (x3) and the token copies, charged BEFORE Fraction(t)
        if extra > RATIONAL_BYTES:
            guard.reserve(extra - RATIONAL_BYTES, "exact numeral %r...: %d + %d bits of numerator / denominator (beyond the %d-byte proxy already reserved for the table entry)" % (t[:16], nb, db, RATIONAL_BYTES))
        if nb + db > 8 * POLL_TOKENS:
            guard.tick(0)                                                                     # a long conversion is a composite operation: the deadline is checked BEFORE it starts
        guard.tick(1 + (nb + db) // 4096)                                                     # the conversion work of a long numeral is charged as units of 4,096 bits
    try:
        q = Fr(t)
    except (ValueError, ZeroDivisionError):
        raise InvalidInput("%s is not an exact rational: %r" % (what, t[:40]))
    if q < 0:
        raise InvalidInput("%s is negative" % what)
    return q


def parse_model_bytes(data: bytes, guard=None) -> U.Model:
    g = guard or _Guard(); g.tick(0)                                                             # an already-expired deadline stops BEFORE decoding / tokenization
    g.reserve(2 * len(data) + 64, "model bytes + decoded text")                                 # the decoded text and the token list are the first allocations: reserved first
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise InvalidInput("model is not UTF-8: %s" % ex)
    g.reserve(TOKEN_BYTES * (len(data) // 2 + 1), "token list (upper bound: one token per two bytes)")
    toks = text.split(); it = iter(toks); g.tick(len(toks))
    try:
        net = next(it)
    except StopIteration:
        raise InvalidInput("empty model file")
    if net not in ("MARKOV", "BAYES"):
        raise InvalidInput("unknown network type %r" % net[:20])
    nvars = _int_token(it, "variable count"); card = []
    for v in range(nvars):
        card.append(_int_token(it, "cardinality of variable %d" % v, lo=1)); g.tick()
    nfac = _int_token(it, "factor count"); scopes = []
    for i in range(nfac):
        k = _int_token(it, "arity of factor %d" % i); sc = tuple(_int_token(it, "scope variable of factor %d" % i) for _ in range(k)); g.tick(k + 1)
        for v in sc:
            if v >= nvars:
                raise InvalidInput("factor %d names variable %d >= %d" % (i, v, nvars))
        if len(set(sc)) != len(sc):
            raise InvalidInput("factor %d repeats a variable in its scope %s" % (i, sc))
        scopes.append(sc)
    factors = []
    for i, sc in enumerate(scopes):
        n = _int_token(it, "table length of factor %d" % i); cd = tuple(card[v] for v in sc); exp = 1
        for c in cd:
            exp *= c
        if n != exp:
            raise InvalidInput("factor %d declares %d entries, scope product is %d" % (i, n, exp))
        g.reserve(RATIONAL_BYTES * n + 8 * n + 256, "factor %d table (%d exact rationals)" % (i, n))        # the table is reserved BEFORE one rational is parsed
        tab = []
        for j in range(n):
            try:
                t = next(it)
            except StopIteration:
                raise InvalidInput("truncated table of factor %d" % i)
            tab.append(_rational_token(t, "factor %d entry %d" % (i, j), g)); g.tick()                # one unit per rational, cumulative across factors; big numerals reserved before expansion
        factors.append(U.Factor(scope=sc, card=cd, table=tab, index=i)); g.tick()
    rest = list(it)
    if rest:
        raise InvalidInput("trailing tokens in the model file: %r" % rest[:5])
    m = U.Model(net_type=net, nvars=nvars, card=card, factors=factors); m.check(); return m


def parse_evidence_bytes(data: bytes, m: U.Model, guard=None) -> dict:
    g = guard or _Guard(); g.reserve(2 * len(data) + TOKEN_BYTES * (len(data) // 2 + 1) + 64, "evidence bytes + tokens")
    try:
        toks = data.decode("utf-8").split()
    except UnicodeDecodeError as ex:
        raise InvalidInput("evidence is not UTF-8: %s" % ex)
    g.tick(len(toks))
    if not toks:
        return {}
    it = iter(toks); n = _int_token(it, "evidence count"); ev = {}
    for i in range(n):
        v = _int_token(it, "evidence variable %d" % i); s = _int_token(it, "evidence state %d" % i); g.tick(2)
        if v >= m.nvars:
            raise InvalidInput("evidence names variable %d >= %d" % (v, m.nvars))
        if s >= m.card[v]:
            raise InvalidInput("evidence state %d of variable %d >= cardinality %d" % (s, v, m.card[v]))
        if v in ev:
            raise InvalidInput("duplicate evidence variable %d" % v)
        ev[v] = s
    rest = list(it)
    if rest:
        raise InvalidInput("trailing tokens in the evidence file: %r" % rest[:5])
    return ev


def canonical_legacy(data: bytes) -> str:
    return hashlib.sha256((" ".join(data.decode("utf-8", "replace").split())).encode()).hexdigest()


def canonical_v2_model(m: U.Model, guard=None) -> str:
    g = guard or _Guard(); h = hashlib.sha256(); h.update(("%s|%s|%d|" % (CANONICAL_VERSION, m.net_type, m.nvars)).encode()); h.update((",".join(str(c) for c in m.card) + "|").encode())
    for f in m.factors:
        h.update(("F%d:%s:" % (f.index, ",".join(str(v) for v in f.scope))).encode())
        for q in f.table:
            nb = q.numerator.bit_length() + q.denominator.bit_length()
            if nb > 4096:
                g.reserve(nb * 302 // 1000 + 64, "canonical serialization of a %d-bit rational" % nb); g.tick(nb // 4096)   # the decimal text of a big rational is a live temporary: reserved before it is formatted
            h.update(("%d/%d," % (q.numerator, q.denominator)).encode()); g.tick()          # canonical hashing: one cumulative unit per entry (review E4 / E5)
        h.update(b";"); g.tick()
    return h.hexdigest()


def canonical_v2_evidence(ev: dict) -> str:
    return hashlib.sha256((CANONICAL_VERSION + "|E|" + ",".join("%d=%d" % (v, s) for v, s in sorted(ev.items()))).encode()).hexdigest()


class Snapshot:
    """bytes read ONCE; hashes + parsed structures derived from the same bytes; the task identity is the CALLER's (model, evidence, every original variable)"""
    __slots__ = ("model_path", "evid_path", "model_bytes", "evid_bytes", "model", "ev", "task", "ledger_charged", "ledger_ref")

    def __init__(self, model_path, evid_path, ledger=None, deadline=None):
        self.model_path = model_path; self.evid_path = evid_path; g = _Guard(ledger, deadline); g.tick(0)   # an already-expired deadline stops before one byte is read
        g.reserve(os.path.getsize(model_path) + os.path.getsize(evid_path) + 128, "raw caller bytes")      # file sizes known before reading: reserved BEFORE the read
        with open(model_path, "rb") as f:
            self.model_bytes = f.read()
        with open(evid_path, "rb") as f:
            self.evid_bytes = f.read()
        self.model = parse_model_bytes(self.model_bytes, g); self.ev = parse_evidence_bytes(self.evid_bytes, self.model, g); q = list(range(self.model.nvars))
        g.reserve(8 * self.model.nvars + 1024, "task identity + query list"); self.ledger_charged = g.charged; self.ledger_ref = ledger
        self.task = {"raw_model_sha256": hashlib.sha256(self.model_bytes).hexdigest(), "raw_evidence_sha256": hashlib.sha256(self.evid_bytes).hexdigest(),
                     "canonical_model_sha256": canonical_legacy(self.model_bytes), "canonical_evidence_sha256": canonical_legacy(self.evid_bytes),      # LEGACY whitespace-normalized text hash (historical field name kept)
                     "canonical_v2_model_sha256": canonical_v2_model(self.model, g), "canonical_v2_evidence_sha256": canonical_v2_evidence(self.ev), "canonical_version": CANONICAL_VERSION,
                     "nvars": self.model.nvars, "orig_card": list(self.model.card), "queries": q, "queries_sha256": hashlib.sha256(json.dumps(q).encode()).hexdigest(), "eps": "1/200", "max_width": "1/100",
                     "model_bytes": len(self.model_bytes), "evidence_bytes": len(self.evid_bytes), "factor_occurrences": len(self.model.factors)}

    def path_still_matches(self):
        try:
            with open(self.model_path, "rb") as f:
                hm = hashlib.sha256(f.read()).hexdigest()
            with open(self.evid_path, "rb") as f:
                he = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return False
        return hm == self.task["raw_model_sha256"] and he == self.task["raw_evidence_sha256"]


TASK_BINDING_FIELDS = ("raw_model_sha256", "raw_evidence_sha256", "canonical_model_sha256", "canonical_evidence_sha256", "canonical_v2_model_sha256", "canonical_v2_evidence_sha256", "canonical_version", "nvars", "orig_card", "queries_sha256", "eps", "max_width")


def bound_to_task(rec_task, task):
    """positive equality on EVERY binding field; a missing field is a mismatch, never permission"""
    if not isinstance(rec_task, dict):
        return False
    return all(k in rec_task and rec_task[k] == task[k] for k in TASK_BINDING_FIELDS)
