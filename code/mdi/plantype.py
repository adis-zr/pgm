"""Truthful plan properties and persisted plan records (contract §A).

Eight properties are represented SEPARATELY. None implies another, and a plan
may not execute as a certified route unless every prerequisite is present.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
import json, hashlib
from fractions import Fraction as Fr
from dataclasses import dataclass, field, asdict

# the eight properties, in dependency order
PROPERTIES = ("mathematically_certified", "executor_supported",
              "checker_supported", "complete_cost_priced", "selected",
              "producer_complete", "independently_verified",
              "publication_contract_met")

# what each property REQUIRES before it may be set. A property with an unmet
# prerequisite is a contract violation, not a judgement call.
PREREQS = {
    "mathematically_certified": (),
    "executor_supported": (),
    "checker_supported": (),
    "complete_cost_priced": (),
    "selected": ("mathematically_certified", "executor_supported",
                 "complete_cost_priced"),
    "producer_complete": ("selected", "executor_supported"),
    "independently_verified": ("producer_complete", "checker_supported"),
    "publication_contract_met": ("independently_verified",),
}

KINDS = ("identity", "regional", "statistic", "gaussian", "fourier", "composed")


class PlanError(ValueError):
    pass


@dataclass
class PlanProperties:
    mathematically_certified: bool = False
    executor_supported: bool = False
    checker_supported: bool = False
    complete_cost_priced: bool = False
    selected: bool = False
    producer_complete: bool = False
    independently_verified: bool = False
    publication_contract_met: bool = False

    def set(self, name: str, value: bool = True):
        if name not in PROPERTIES:
            raise PlanError("unknown property %r" % name)
        if value:
            missing = [p for p in PREREQS[name] if not getattr(self, p)]
            if missing:
                raise PlanError("cannot set %s: unmet prerequisites %s"
                                % (name, missing))
        setattr(self, name, bool(value))
        return self

    def may_execute_as_certified_route(self):
        """A certified ROUTE needs all of: certified mathematics, an executor, a
        checker, a complete price, and selection."""
        need = ("mathematically_certified", "executor_supported",
                "checker_supported", "complete_cost_priced", "selected")
        return [p for p in need if not getattr(self, p)]

    def as_dict(self):
        return {p: getattr(self, p) for p in PROPERTIES}


@dataclass
class PlanRecord:
    """Everything contract §A requires a persisted plan to bind."""
    kind: str
    name: str
    model_sha256: str
    evidence_sha256: str
    query_sha256: str
    preprocess_identity: dict            # the exact preprocessing proof
    factor_ownership: list               # [(factor_origin, owner_bag_or_region)]
    factor_scopes: list                  # [(origin, scope, card)]
    region_membership: list              # [(region_index, vars)] or []
    cell_membership: list                # [(region, cell, members)] or []
    allocations: dict                    # every approximation radius charged
    executor_id: str
    checker_id: str
    numerical: dict                      # precision, exponent range, mode
    cost_counters: dict                  # symbolic counts, labelled by kind
    storage_schedule: dict               # lifetimes and peak live entries
    rejected_alternatives: list
    properties: PlanProperties = field(default_factory=PlanProperties)
    version: int = 1

    def validate(self):
        if self.kind not in KINDS:
            raise PlanError("unknown plan kind %r" % self.kind)
        for h in (self.model_sha256, self.evidence_sha256, self.query_sha256):
            if not isinstance(h, str) or len(h) != 64:
                raise PlanError("plan must bind 64-hex input hashes; got %r" % (h,))
        if not isinstance(self.allocations, dict):
            raise PlanError("allocations must be a mapping")
        for k, v in self.allocations.items():
            Fr(v)                       # must parse exactly; no float bounds
        if not self.executor_id or not self.checker_id:
            raise PlanError("plan must name its executor and checker")
        if self.properties.selected:
            miss = self.properties.may_execute_as_certified_route()
            if "selected" in miss:
                raise PlanError("inconsistent properties")
        own = [o for o, _ in self.factor_ownership]
        if len(own) != len(set(own)):
            raise PlanError("a factor is owned more than once")
        return self

    def to_json(self) -> str:
        d = {"kind": self.kind, "name": self.name,
             "model_sha256": self.model_sha256,
             "evidence_sha256": self.evidence_sha256,
             "query_sha256": self.query_sha256,
             "preprocess_identity": self.preprocess_identity,
             "factor_ownership": [[int(o), w] for o, w in self.factor_ownership],
             "factor_scopes": [[int(o), list(sc), list(cd)]
                               for o, sc, cd in self.factor_scopes],
             "region_membership": [[int(i), list(vs)]
                                   for i, vs in self.region_membership],
             "cell_membership": [[int(r), int(c), [list(x) for x in mem]]
                                 for r, c, mem in self.cell_membership],
             "allocations": {k: str(Fr(v)) for k, v in self.allocations.items()},
             "executor_id": self.executor_id, "checker_id": self.checker_id,
             "numerical": self.numerical, "cost_counters": self.cost_counters,
             "storage_schedule": self.storage_schedule,
             "rejected_alternatives": self.rejected_alternatives,
             "properties": self.properties.as_dict(),
             "version": self.version}
        return json.dumps(d, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(txt: str) -> "PlanRecord":
        try:
            d = json.loads(txt)
        except Exception as e:
            raise PlanError("plan record is not valid JSON: %s" % e)
        need = ("kind", "name", "model_sha256", "evidence_sha256",
                "query_sha256", "preprocess_identity", "factor_ownership",
                "factor_scopes", "allocations", "executor_id", "checker_id",
                "numerical", "cost_counters", "storage_schedule", "properties",
                "version")
        miss = [k for k in need if k not in d]
        if miss:
            raise PlanError("plan record is truncated: missing %s" % miss)
        if d["version"] != 1:
            raise PlanError("stale plan record version %r" % d["version"])
        props = PlanProperties()
        for k, v in d["properties"].items():
            if k not in PROPERTIES:
                raise PlanError("unknown property %r in record" % k)
            setattr(props, k, bool(v))
        rec = PlanRecord(
            kind=d["kind"], name=d["name"], model_sha256=d["model_sha256"],
            evidence_sha256=d["evidence_sha256"], query_sha256=d["query_sha256"],
            preprocess_identity=d["preprocess_identity"],
            factor_ownership=[(int(o), w) for o, w in d["factor_ownership"]],
            factor_scopes=[(int(o), tuple(sc), tuple(cd))
                           for o, sc, cd in d["factor_scopes"]],
            region_membership=[(int(i), tuple(vs))
                               for i, vs in d.get("region_membership", [])],
            cell_membership=[(int(r), int(c), [tuple(x) for x in mem])
                             for r, c, mem in d.get("cell_membership", [])],
            allocations={k: Fr(v) for k, v in d["allocations"].items()},
            executor_id=d["executor_id"], checker_id=d["checker_id"],
            numerical=d["numerical"], cost_counters=d["cost_counters"],
            storage_schedule=d["storage_schedule"],
            rejected_alternatives=d.get("rejected_alternatives", []),
            properties=props, version=d["version"])
        return rec.validate()

    def bind_check(self, model_sha, evidence_sha, query_sha):
        """Reject a plan bound to different inputs BEFORE expensive work."""
        if (self.model_sha256 != model_sha or
                self.evidence_sha256 != evidence_sha or
                self.query_sha256 != query_sha):
            raise PlanError(
                "plan record is bound to different inputs: record "
                "(%s/%s/%s) vs current (%s/%s/%s)"
                % (self.model_sha256[:8], self.evidence_sha256[:8],
                   self.query_sha256[:8], model_sha[:8], evidence_sha[:8],
                   query_sha[:8]))
        return True


def round_trip(rec: PlanRecord) -> PlanRecord:
    """Byte-identity and semantic round trip (contract §A)."""
    txt = rec.to_json()
    back = PlanRecord.from_json(txt)
    if back.to_json() != txt:
        raise PlanError("plan record is not byte-identical after a round trip")
    for k, v in rec.allocations.items():
        if Fr(back.allocations[k]) != Fr(v):
            raise PlanError("allocation %s changed across serialization" % k)
    return back


# ---------------- the explicit dispatcher (contract §A) ----------------

EXECUTORS = {}          # kind -> callable or None when unimplemented
CHECKERS = {}


def register_executor(kind, fn):
    if kind not in KINDS:
        raise PlanError("unknown kind %r" % kind)
    EXECUTORS[kind] = fn


def register_checker(kind, fn):
    if kind not in KINDS:
        raise PlanError("unknown kind %r" % kind)
    CHECKERS[kind] = fn


def dispatch(kind):
    """Return (executor, checker) for a kind, or raise.

    A recognized-but-unimplemented kind must NEVER be routed silently into the
    original-model solver; fallback is a separate, recorded, charged selection.
    """
    if kind not in KINDS:
        raise PlanError("unknown plan kind %r" % kind)
    ex = EXECUTORS.get(kind)
    ck = CHECKERS.get(kind)
    if ex is None:
        raise PlanError("no executor is implemented for kind %r; fallback must "
                        "be a separate recorded selection, not a silent "
                        "substitution" % kind)
    return ex, ck


def supported(kind):
    return {"executor_supported": EXECUTORS.get(kind) is not None,
            "checker_supported": CHECKERS.get(kind) is not None}


def query_hash(nvars, card, evidence, queries) -> str:
    h = hashlib.sha256()
    h.update(("nvars=%d;" % nvars).encode())
    h.update((",".join(str(c) for c in card) + ";").encode())
    h.update((",".join("%d:%d" % (v, s) for v, s in sorted(evidence.items())) + ";").encode())
    h.update((",".join(str(v) for v in sorted(queries))).encode())
    return h.hexdigest()
