"""Trusted reduced-source snapshot (brief §5): a deep frozen copy of the shared common reductions' result taken BEFORE planning, cross-checked by an
INDEPENDENT replay of the recorded reduction steps from the caller's snapshot bytes (adp.checker.SourceReplay: its own parser, tables and code), and
insulated from planner mutation (`unchanged` re-hashes the live object). The planner receives a separate proposal VIEW (plain tuples / Fractions);
the executor consumes only gbidi3.validate.Validated, whose tables, scale and decoder come from THIS object."""
from __future__ import annotations
import hashlib, time, json
from fractions import Fraction as Fr
from gbidi3.memory import fraction_bytes


class Invalid(Exception):
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


def _prod(xs):
    p = 1
    for x in xs:
        p *= x
    return p


class TFactor:
    __slots__ = ("fid", "scope", "card", "table", "origin", "_rows")

    def __init__(self, fid, scope, card, table, origin):
        self.fid = int(fid); self.scope = tuple(int(v) for v in scope); self.card = tuple(int(c) for c in card); self.table = tuple(Fr(x) for x in table); self.origin = str(origin); self._rows = {}
        if len(self.table) != _prod(self.card) or len(self.scope) != len(self.card) or any(x < 0 for x in self.table) or len(set(self.scope)) != len(self.scope):
            raise Invalid("trusted factor %d malformed" % self.fid)

    def rows_along(self, k):
        """rows_along(k)[a] = tuple of the entries with axis k at position a, in the flat order of the other axes"""
        r = self._rows.get(k)
        if r is None:
            card = self.card; st = [1] * len(card); acc = 1
            for j in range(len(card) - 1, -1, -1):
                st[j] = acc; acc *= card[j]
            out = []
            for a in range(card[k]):
                row = []
                for i in range(len(self.table)):
                    if (i // st[k]) % card[k] == a:
                        row.append(self.table[i])
                out.append(tuple(row))
            r = out; self._rows[k] = r
        return r


class TrustedReduced:
    """frozen copy of adp.source.Reduced: the only source of tables / scale / decoder for validation and execution"""
    @staticmethod
    def bytes_bound(R):
        """host bytes of the frozen snapshot (tuples of exact rationals, decoder entries, steps) computed from the LIVE reduced object before any copy is made"""
        b = 512 + 64 * len(R.steps) + 160 * int(R.nvars) + 80 * len(R.dom) + 8 * sum(len(d) for d in R.dom.values())
        for f in R.factors:
            b += 200 + 8 * len(f.table) + 16 * len(f.scope) + sum(fraction_bytes(q) for q in f.table)
        for es in R.dec.values():
            b += 80 * len(es)
        return b

    def __init__(self, R, ledger=None):
        if ledger is not None:
            ledger.reserve("source_ir_maps_output", TrustedReduced.bytes_bound(R), "trusted reduced snapshot (reserved BEFORE the frozen copies are built)")
        self.nvars = int(R.nvars); self.orig_card = tuple(int(c) for c in R.orig_card); self.ev = {int(v): int(s) for v, s in R.ev.items()}
        self.dom = {int(v): tuple(int(s) for s in d) for v, d in R.dom.items()}
        self.factors = tuple(sorted((TFactor(f.fid, f.scope, f.card, f.table, f.origin) for f in R.factors), key=lambda f: f.fid)); self.scale = Fr(R.scale); self.zero_proof = R.zero_proof
        self.steps = tuple(tuple(s) for s in R.steps)
        self.dec = {int(v): tuple((("C", Fr(e[1])) if e[0] == "C" else ("V", int(e[1]), int(e[2]), Fr(e[3]))) for e in es) for v, es in R.dec.items()}
        for v, es in self.dec.items():
            if len(es) != self.orig_card[v]:
                raise Invalid("decoder of variable %d has %d entries" % (v, len(es)))
            for e in es:
                if e[0] == "V" and (e[1] not in self.dom or e[2] not in self.dom[e[1]]):
                    raise Invalid("decoder of variable %d references a non-reduced state" % v)
        for f in self.factors:
            for v, c in zip(f.scope, f.card):
                if v not in self.dom or len(self.dom[v]) != c:
                    raise Invalid("trusted factor %d axis %d does not match the reduced domain" % (f.fid, v))
        self.reduced_vars = tuple(sorted(self.dom)); self.nvars_reduced = len(self.reduced_vars); self.var_pos = {v: i for i, v in enumerate(self.reduced_vars)}
        self.by_fid = {f.fid: f for f in self.factors}
        self.content_hash = self._hash()

    def dom_of(self, v):
        return self.dom[v]

    def _hash(self):
        h = hashlib.sha256()
        for v in sorted(self.dom):
            h.update(("D%d:%s;" % (v, ",".join(map(str, self.dom[v])))).encode())
        for f in self.factors:
            h.update(("F%d:%s:%s:%s:%s;" % (f.fid, f.origin, ",".join(map(str, f.scope)), ",".join(map(str, f.card)), ",".join("%d/%d" % (x.numerator, x.denominator) for x in f.table))).encode())
        h.update(("S%d/%d;" % (self.scale.numerator, self.scale.denominator)).encode())
        for v in sorted(self.dec):
            h.update(("X%d:%s;" % (v, "|".join(":".join(map(str, e)) for e in self.dec[v]))).encode())
        return h.hexdigest()

    def unchanged(self, R):
        try:
            return TrustedReduced(R).content_hash == self.content_hash
        except Exception:
            return False

    def proposal_view(self):
        """what the planner sees: plain data, no reference to this object"""
        return {"dom": {v: tuple(d) for v, d in self.dom.items()}, "factors": [(f.fid, f.scope, f.card, tuple(f.table), f.origin) for f in self.factors], "scale": Fr(self.scale), "zero_proof": self.zero_proof}

    def independent_replay(self, model_path, evid_path, record, deadline=None):
        """re-derive the recorded reduction steps from the caller's files with the PINNED independent checker's SourceReplay (own parser / tables / code)
        and compare its reduced hash with the record's; returns the replay record or raises Invalid"""
        from adp import checker as CK
        src = {"raw_model_sha256": CK._raw_hash(model_path), "raw_evidence_sha256": CK._raw_hash(evid_path), "canonical_model_sha256": CK._canon_hash(model_path), "canonical_evidence_sha256": CK._canon_hash(evid_path)}
        steps = json.loads(json.dumps(record["steps"]))
        cert = {"source": src, "reduced": {"nvars": record["nvars"], "orig_card": record["orig_card"], "evidence": record["evidence"], "steps": steps}}
        t0 = time.monotonic()
        try:
            CK.validate_steps(steps); SR = CK.SourceReplay(cert, model_path, evid_path, deadline); SR.replay(steps); rh = SR.reduced_hash()
        except CK.Reject as ex:
            raise Invalid("independent source replay rejected the recorded reductions: %s" % ex)
        if rh != record["reduced_hash"]:
            raise Invalid("independent source replay produced a different reduced model (%s != %s)" % (rh[:16], record["reduced_hash"][:16]))
        return {"status": "REPLAYED", "reduced_hash": rh, "steps": len(record["steps"]), "seconds": time.monotonic() - t0}
