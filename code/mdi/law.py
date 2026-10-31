"""The IMMUTABLE original law, request and program boundary (r21).

Ownership is defined ONCE at the public boundary. `OriginalLaw.freeze` turns
the caller's model into a canonical immutable copy: every factor OCCURRENCE
becomes its own `Factor` with a tuple scope, tuple cardinalities and a TUPLE
table of exact rationals (immutable values may be shared freely), carrying an
original occurrence identity assigned by position when the caller supplied
none or duplicates -- WITHOUT mutating any caller object, so a list that holds
the same Factor object twice is two occurrences, exactly as two separately
allocated equal factors are. The evidence and the requested set are frozen
with it, and the three hashes are computed from the frozen bytes.

Every construction / execution phase then OWNS its mutable working
representation: `restriction()` derives a FRESH restricted model (restriction
at the evidence, the exact preprocessing and its independent identity
verification) from the frozen law on every call, with mutable list tables that
belong to the caller alone. Discovery, the producer and the checker each call
it; none of them can reach another's working tables, and none can reach the
frozen original (tuple tables refuse item assignment). The checker's reference
is therefore always derived from the original law, never inherited.

Cost: one restriction and preprocessing per owner (charged inside the owner's
phase; the pipeline reports them in `stages`), no per-node table copies.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from fractions import Fraction as Fr
import hashlib

from mdi import model as M


def _occurrence_ids(factors):
    """Original occurrence identities: the caller's ids when they are all
    non-negative and distinct, otherwise the position in the input list."""
    ids = [int(getattr(f, "origin", -1)) for f in factors]
    if ids and all(i >= 0 for i in ids) and len(set(ids)) == len(ids):
        return ids
    return list(range(len(factors)))


def freeze_model(model):
    """A canonical immutable copy of `model` (new Factor objects, tuple
    tables of exact rationals, occurrence ids). The caller's objects are
    untouched."""
    ids = _occurrence_ids(model.factors)
    facs = []
    for f, oid in zip(model.factors, ids):
        tab = tuple(Fr(x) for x in f.table)
        facs.append(M.Factor(scope=tuple(int(v) for v in f.scope), card=tuple(int(c) for c in f.card),
                             table=tab, origin=int(oid), scale=Fr(getattr(f, "scale", 1))))
    out = M.Model(nvars=int(model.nvars), card=[int(c) for c in model.card], factors=facs,
                  net_type=str(getattr(model, "net_type", "MARKOV")),
                  provenance=dict(getattr(model, "provenance", {}) or {}))
    out.validate()
    return out


def is_frozen(model):
    return all(isinstance(f.table, tuple) and isinstance(f.scope, tuple) for f in model.factors)


@dataclass
class Restriction:
    """One owner's mutable working representation, derived from the law."""
    r0: object                     # the restriction at the evidence (fresh lists)
    simp: object                   # the exact preprocessing (fresh factors)
    r: object                      # the preprocessed Restricted the owner works on


@dataclass
class OriginalLaw:
    model: object                  # the frozen model
    evidence: dict
    queries: frozenset
    model_sha256: str
    evidence_sha256: str
    query_sha256: str
    derivations: int = 0           # how many owners derived a working restriction

    @staticmethod
    def freeze(model, evidence, queries):
        from mdi import plantype as PT
        fm = model if is_frozen(model) and isinstance(model.card, list) else freeze_model(model)
        ev = {int(v): int(s) for v, s in dict(evidence or {}).items()}
        q = frozenset(int(v) for v in queries)
        mh = hashlib.sha256()
        mh.update(("%s;%d;" % (fm.net_type, fm.nvars)).encode())
        mh.update((",".join(str(c) for c in fm.card) + ";").encode())
        for f in fm.factors:
            mh.update(("%s|%s|" % (f.scope, [str(x) for x in f.table])).encode())
        eh = hashlib.sha256((",".join("%d:%d" % (v, s) for v, s in sorted(ev.items()))).encode())
        qh = PT.query_hash(fm.nvars, fm.card, ev, q)
        return OriginalLaw(model=fm, evidence=ev, queries=q, model_sha256=mh.hexdigest(),
                           evidence_sha256=eh.hexdigest(), query_sha256=qh)

    @property
    def hashes(self):
        return self.model_sha256, self.evidence_sha256, self.query_sha256

    def restrict_only(self):
        """A fresh restriction at the evidence (no preprocessing)."""
        return M.restrict(self.model, dict(self.evidence))

    def restriction(self, verify=True):
        """A FRESH working restriction for one owner: restriction, exact
        preprocessing and (by default) its independent identity verification.
        Raises PreprocessError / InvalidModel; never shares list tables with
        any earlier derivation."""
        from mdi import preprocess as PRE
        r0 = M.restrict(self.model, dict(self.evidence))
        simp = PRE.simplify(r0)
        if verify:
            PRE.verify_identities(r0, simp)
        r = M.Restricted(model=self.model, evidence=dict(self.evidence), factors=simp.factors,
                         free=list(simp.free), card=dict(simp.card), constant=r0.constant,
                         impossible_factor=simp.impossible)
        self.derivations += 1
        return Restriction(r0=r0, simp=simp, r=r)

    def equal_law(self, other):
        """Two laws are the same exact law when their frozen bytes agree."""
        return self.hashes == other.hashes
