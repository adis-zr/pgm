"""The IMMUTABLE original law, request and program boundary (r21 / r22).

Ownership is defined ONCE at the public boundary. `OriginalLaw.freeze` turns
the caller's model into a canonical, RECURSIVELY READ-ONLY copy: every factor
OCCURRENCE becomes a `FrozenFactor` (tuple scope, tuple cardinalities, tuple
table of exact rationals, occurrence identity, scale) whose attributes cannot
be replaced or deleted through ordinary operations; the `FrozenModel` holds a
tuple of those factors and a tuple of cardinalities and is likewise read-only;
`OriginalLaw` is a frozen dataclass whose evidence is a read-only mapping and
whose requested set is a frozenset. Occurrence identities are assigned by
position when the caller supplied none or duplicates -- WITHOUT mutating any
caller object -- so a list holding the same Factor object twice is two
occurrences, exactly as two separately allocated equal factors are, and a
caller's tuple-table storage is never taken as proof of canonicalization
(only an actual FrozenModel is reused).

Every construction / execution phase then OWNS its mutable working
representation: `restriction()` derives a FRESH restricted model from the
frozen law on every call, with mutable list tables that belong to the caller
alone. Discovery, the binder, the producer and the checker each call it; none
of them can reach another's working tables, and the canonical authority they
all reference cannot be changed through supported operations. The checker's
reference is therefore always the original law.

Threat model: ordinary producer / construction mistakes through supported
object operations (item assignment, attribute replacement, list mutation).
No defence against arbitrary Python introspection is claimed.

Mutable RUNTIME counters (how many owners derived a restriction) live on a
separate `LawMeter` object, never on the law data.

Cost: one restriction and preprocessing per owner (charged inside the owner's
phase; the pipeline reports them in `stages`), no per-node table copies;
`verify_authority` re-hashes the frozen bytes (linear in the input) and is
charged to the phase that calls it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from fractions import Fraction as Fr
from types import MappingProxyType
import hashlib

from mdi import model as M


class FrozenError(TypeError):
    pass


class FrozenFactor(M.Factor):
    """A factor occurrence of the canonical law: every attribute is read-only
    after construction (attribute replacement and deletion raise)."""

    def __init__(self, scope, card, table, origin, scale=Fr(1)):
        object.__setattr__(self, "scope", tuple(int(v) for v in scope))
        object.__setattr__(self, "card", tuple(int(c) for c in card))
        object.__setattr__(self, "table", tuple(Fr(x) for x in table))
        object.__setattr__(self, "origin", int(origin))
        object.__setattr__(self, "scale", Fr(scale))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        raise FrozenError("the canonical law is read-only: FrozenFactor.%s cannot be replaced" % name)

    def __delattr__(self, name):
        raise FrozenError("the canonical law is read-only: FrozenFactor.%s cannot be deleted" % name)

    def __reduce__(self):
        return (FrozenFactor, (self.scope, self.card, self.table, self.origin, self.scale))


class FrozenModel(M.Model):
    """The canonical model: a tuple of FrozenFactors, a tuple of
    cardinalities, read-only provenance; attributes cannot be replaced."""

    def __init__(self, nvars, card, factors, net_type="MARKOV", provenance=None):
        object.__setattr__(self, "nvars", int(nvars))
        object.__setattr__(self, "card", tuple(int(c) for c in card))
        object.__setattr__(self, "factors", tuple(factors))
        object.__setattr__(self, "net_type", str(net_type))
        object.__setattr__(self, "provenance", MappingProxyType(dict(provenance or {})))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        raise FrozenError("the canonical law is read-only: FrozenModel.%s cannot be replaced" % name)

    def __delattr__(self, name):
        raise FrozenError("the canonical law is read-only: FrozenModel.%s cannot be deleted" % name)

    def __reduce__(self):
        return (FrozenModel, (self.nvars, self.card, self.factors, self.net_type, dict(self.provenance)))


def _occurrence_ids(factors):
    """Original occurrence identities: the caller's ids when they are all
    non-negative and distinct, otherwise the position in the input list."""
    ids = [int(getattr(f, "origin", -1)) for f in factors]
    if ids and all(i >= 0 for i in ids) and len(set(ids)) == len(ids):
        return ids
    return list(range(len(factors)))


def freeze_model(model):
    """A canonical read-only copy of `model`. The caller's objects are
    untouched; an actual FrozenModel is returned as is."""
    if isinstance(model, FrozenModel):
        return model
    ids = _occurrence_ids(model.factors)
    facs = [FrozenFactor(f.scope, f.card, f.table, oid, getattr(f, "scale", Fr(1)))
            for f, oid in zip(model.factors, ids)]
    out = FrozenModel(int(model.nvars), model.card, facs, getattr(model, "net_type", "MARKOV"),
                      getattr(model, "provenance", None) or {})
    out.validate()
    return out


def is_frozen(model):
    return isinstance(model, FrozenModel)


def law_hash(model):
    mh = hashlib.sha256()
    mh.update(("%s;%d;" % (model.net_type, model.nvars)).encode())
    mh.update((",".join(str(c) for c in model.card) + ";").encode())
    for f in model.factors:
        mh.update(("%s|%s|%d|" % (f.scope, [str(x) for x in f.table], int(f.origin))).encode())
    return mh.hexdigest()


class LawMeter:
    """Mutable RUNTIME counters, separate from the immutable law data."""

    def __init__(self):
        self.derivations = 0
        self.authority_checks = 0


@dataclass
class Restriction:
    """One owner's mutable working representation, derived from the law."""
    r0: object                     # the restriction at the evidence (fresh lists)
    simp: object                   # the exact preprocessing (fresh factors)
    r: object                      # the preprocessed Restricted the owner works on


@dataclass(frozen=True)
class OriginalLaw:
    model: object                  # FrozenModel
    evidence: object               # read-only mapping
    queries: frozenset
    model_sha256: str
    evidence_sha256: str
    query_sha256: str
    meter: object = field(default_factory=LawMeter, compare=False, repr=False)

    @staticmethod
    def freeze(model, evidence, queries):
        from mdi import plantype as PT
        fm = freeze_model(model)
        ev = {int(v): int(s) for v, s in dict(evidence or {}).items()}
        q = frozenset(int(v) for v in queries)
        eh = hashlib.sha256((",".join("%d:%d" % (v, s) for v, s in sorted(ev.items()))).encode())
        qh = PT.query_hash(fm.nvars, fm.card, ev, q)
        return OriginalLaw(model=fm, evidence=MappingProxyType(ev), queries=q, model_sha256=law_hash(fm),
                           evidence_sha256=eh.hexdigest(), query_sha256=qh)

    @property
    def hashes(self):
        return self.model_sha256, self.evidence_sha256, self.query_sha256

    def verify_authority(self):
        """Tamper evidence: the frozen model's bytes still hash to the law's
        recorded identity. Returns a reason or None."""
        self.meter.authority_checks += 1
        if not isinstance(self.model, FrozenModel) or not all(isinstance(f, FrozenFactor) for f in self.model.factors):
            return "the canonical model is not the read-only type"
        h = law_hash(self.model)
        if h != self.model_sha256:
            return "the canonical law's bytes no longer hash to its identity (%s != %s)" % (h[:16], self.model_sha256[:16])
        return None

    def restrict_only(self):
        """A fresh restriction at the evidence (no preprocessing)."""
        return M.restrict(self.model, dict(self.evidence))

    def restriction(self, verify=True):
        """A FRESH working restriction for one owner: restriction, exact
        preprocessing and (by default) its independent identity verification.
        Never shares list tables with any earlier derivation."""
        from mdi import preprocess as PRE
        r0 = M.restrict(self.model, dict(self.evidence))
        simp = PRE.simplify(r0)
        if verify:
            PRE.verify_identities(r0, simp)
        r = M.Restricted(model=self.model, evidence=dict(self.evidence), factors=simp.factors,
                         free=list(simp.free), card=dict(simp.card), constant=r0.constant,
                         impossible_factor=simp.impossible)
        self.meter.derivations += 1
        return Restriction(r0=r0, simp=simp, r=r)

    def equal_law(self, other):
        return self.hashes == other.hashes
