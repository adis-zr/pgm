"""Immutable task snapshot + strict UAI grammar for the GENERAL_BIDI_V2 arms (review R2-01 / R2-07).

The caller's model and evidence files are read ONCE into bytes; their raw / canonical hashes and the parsed structures are derived from THOSE bytes
(never from a second open of the path). Every stage downstream binds to the snapshot's hashes; a later change of the file is detected by the
separate task-bound verifier (which re-hashes the path) and by gbidi.executor.publish (which compares the path against the snapshot before and
after verification). The grammar is validated explicitly (negative counts / arities, out-of-range or duplicate scope variables, zero cardinality,
table length, nonnegative rationals, trailing tokens, evidence range / duplicates); malformed input is a typed INVALID_INPUT refusal, never a
reinterpretation. Explicit arity-0 (scalar) factors are VALID. ext.uai is pinned by the accepted ADP comparator and is not modified: the dataclasses
it exposes (Model, Factor) are constructed here from the validated tokens, so the shared reductions / publisher / verifier see the same object types."""
from __future__ import annotations
import hashlib, json
from fractions import Fraction as Fr
from ext import uai as U


class InvalidInput(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


def _int_token(it, what, lo=0):
    try:
        t = next(it)
    except StopIteration:
        raise InvalidInput("truncated model: expected %s" % what)
    try:
        v = int(t)
    except ValueError:
        raise InvalidInput("%s is not an integer: %r" % (what, t[:40]))
    if v < lo:
        raise InvalidInput("%s must be >= %d, got %d" % (what, lo, v))
    return v


def parse_model_bytes(data: bytes) -> U.Model:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as ex:
        raise InvalidInput("model is not UTF-8: %s" % ex)
    it = iter(text.split())
    try:
        net = next(it)
    except StopIteration:
        raise InvalidInput("empty model file")
    if net not in ("MARKOV", "BAYES"):
        raise InvalidInput("unknown network type %r" % net[:20])
    nvars = _int_token(it, "variable count"); card = [_int_token(it, "cardinality of variable %d" % v, lo=1) for v in range(nvars)]
    nfac = _int_token(it, "factor count"); scopes = []
    for i in range(nfac):
        k = _int_token(it, "arity of factor %d" % i); sc = tuple(_int_token(it, "scope variable of factor %d" % i) for _ in range(k))
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
        tab = []
        for j in range(n):
            try:
                t = next(it)
            except StopIteration:
                raise InvalidInput("truncated table of factor %d" % i)
            try:
                q = Fr(t)
            except (ValueError, ZeroDivisionError):
                raise InvalidInput("factor %d entry %d is not a rational: %r" % (i, j, t[:40]))
            if q < 0:
                raise InvalidInput("factor %d entry %d is negative" % (i, j))
            tab.append(q)
        factors.append(U.Factor(scope=sc, card=cd, table=tab, index=i))
    rest = list(it)
    if rest:
        raise InvalidInput("trailing tokens in the model file: %r" % rest[:5])
    m = U.Model(net_type=net, nvars=nvars, card=card, factors=factors); m.check(); return m


def parse_evidence_bytes(data: bytes, m: U.Model) -> dict:
    try:
        toks = data.decode("utf-8").split()
    except UnicodeDecodeError as ex:
        raise InvalidInput("evidence is not UTF-8: %s" % ex)
    if not toks:
        return {}
    it = iter(toks); n = _int_token(it, "evidence count"); ev = {}
    for i in range(n):
        v = _int_token(it, "evidence variable %d" % i); s = _int_token(it, "evidence state %d" % i)
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


def _canon(data: bytes) -> str:
    return hashlib.sha256((" ".join(data.decode("utf-8", "replace").split())).encode()).hexdigest()


class Snapshot:
    """bytes read once; hashes + parsed structures derived from the same bytes"""
    __slots__ = ("model_path", "evid_path", "model_bytes", "evid_bytes", "model", "ev", "task")

    def __init__(self, model_path, evid_path):
        self.model_path = model_path; self.evid_path = evid_path
        with open(model_path, "rb") as f:
            self.model_bytes = f.read()
        with open(evid_path, "rb") as f:
            self.evid_bytes = f.read()
        self.model = parse_model_bytes(self.model_bytes); self.ev = parse_evidence_bytes(self.evid_bytes, self.model); q = list(range(self.model.nvars))
        self.task = {"raw_model_sha256": hashlib.sha256(self.model_bytes).hexdigest(), "raw_evidence_sha256": hashlib.sha256(self.evid_bytes).hexdigest(), "canonical_model_sha256": _canon(self.model_bytes), "canonical_evidence_sha256": _canon(self.evid_bytes),
                     "nvars": self.model.nvars, "orig_card": list(self.model.card), "queries": q, "queries_sha256": hashlib.sha256(json.dumps(q).encode()).hexdigest(), "eps": "1/200", "max_width": "1/100", "model_bytes": len(self.model_bytes), "evidence_bytes": len(self.evid_bytes)}

    def path_still_matches(self):
        """the named paths currently hold the snapshot bytes (hash of the path NOW == hash of the bytes parsed)"""
        try:
            with open(self.model_path, "rb") as f:
                hm = hashlib.sha256(f.read()).hexdigest()
            with open(self.evid_path, "rb") as f:
                he = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return False
        return hm == self.task["raw_model_sha256"] and he == self.task["raw_evidence_sha256"]
