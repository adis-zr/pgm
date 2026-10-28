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


DECLARED_KINDS = ("identity", "regional", "composed", "statistic",
                  "general_statistic", "gaussian", "fourier", "deletion",
                  "level2")


class PlanError(ValueError):
    pass


def _exact_allocations(raw):
    """Parse allocations as EXACT rationals, raising PlanError (not a bare
    ValueError) so a caller catching plan errors cannot miss a malformed one."""
    if not isinstance(raw, dict):
        raise PlanError("allocations must be a mapping, got %s" % type(raw))
    out = {}
    for k, v in raw.items():
        if isinstance(v, float):
            raise PlanError("allocation %r is a float; allocations must be "
                            "exact rationals, never inferred binary64" % k)
        try:
            out[k] = Fr(v)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            raise PlanError("allocation %r is not an exact rational: %r (%s)"
                            % (k, v, e))
    return out


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
        _exact_allocations({k: v for k, v in self.allocations.items()})
        if not isinstance(self.executor_id, str) or not self.executor_id:
            raise PlanError("plan must name its executor")
        if not isinstance(self.checker_id, str) or not self.checker_id:
            raise PlanError("plan must name its checker")
        for k, v in self.allocations.items():
            q = Fr(v)
            if q < 0:
                raise PlanError("allocation %r is NEGATIVE (%s)" % (k, q))
            if q > 1:
                raise PlanError("allocation %r exceeds 1 (%s): a radius larger "
                                "than the whole probability range" % (k, q))
        num = self.numerical
        if not isinstance(num, dict):
            raise PlanError("numerical block must be a mapping")
        prec = num.get("precision")
        if prec is not None:
            if not isinstance(prec, int) or prec < 2 or prec > 1 << 20:
                raise PlanError("invalid precision %r" % (prec,))
        for key in ("emin", "emax"):
            if key in num and not isinstance(num[key], int):
                raise PlanError("numerical %s must be an integer" % key)
        if "emin" in num and "emax" in num and num["emin"] >= num["emax"]:
            raise PlanError("numerical emin >= emax")
        mode = num.get("mode")
        if mode is not None and mode not in ("P", "I"):
            raise PlanError("invalid arithmetic mode %r" % (mode,))
        for origin, scope, cardt in self.factor_scopes:
            if len(scope) != len(cardt):
                raise PlanError("factor %s scope/card length mismatch" % (origin,))
            if len(set(scope)) != len(scope):
                raise PlanError("factor %s has a duplicate scope variable"
                                % (origin,))
            for c in cardt:
                if not isinstance(c, int) or c < 1:
                    raise PlanError("factor %s has cardinality %r"
                                    % (origin, c))
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
        # ---- EXACT field set. An unknown field is a different record format,
        # not a compatible superset: seven of the original fourteen malformed
        # mutations loaded because only the REQUIRED keys were examined.
        allowed = set(need) | {"region_membership", "cell_membership",
                               "rejected_alternatives"}
        extra = sorted(set(d) - allowed)
        if extra:
            raise PlanError("plan record carries unknown fields %s" % extra)
        if d["version"] != 1:
            raise PlanError("stale plan record version %r" % d["version"])
        # ---- kind and name
        # The kind must be one the contract declares. Registration is checked
        # where it binds (dispatch), since the registry may not be imported in
        # a pure record round trip.
        if d["kind"] not in DECLARED_KINDS:
            raise PlanError("unknown plan kind %r" % (d["kind"],))
        if not isinstance(d["name"], str) or not d["name"].strip():
            raise PlanError("plan record has an empty name")
        if not d["name"].split(":")[0] == d["kind"]:
            raise PlanError("plan name %r does not begin with its kind %r"
                            % (d["name"], d["kind"]))
        # ---- hash syntax: 64 lowercase hex digits
        import re as _re
        for hk in ("model_sha256", "evidence_sha256", "query_sha256"):
            hv = d[hk]
            if not isinstance(hv, str) or not _re.fullmatch(r"[0-9a-f]{64}",
                                                            hv):
                raise PlanError("%s is not a 64-digit lowercase hex digest: %r"
                                % (hk, hv))
        # ---- executor and checker must name REGISTERED implementations
        for idk, what in (("executor_id", "executor"),
                          ("checker_id", "checker")):
            idv = d[idk]
            if not isinstance(idv, str) or not idv.strip():
                raise PlanError("%s is empty" % idk)
            if ":" not in idv:
                raise PlanError("%s %r is not a module:function reference"
                                % (idk, idv))
            mod, _, fn = idv.partition(":")
            if not mod.startswith("mdi.") or not fn:
                raise PlanError("%s %r does not reference an mdi "
                                "implementation" % (idk, idv))
        # ---- ownership, scopes and the non-empty blocks
        for bk in ("factor_ownership", "factor_scopes"):
            if not isinstance(d[bk], list) or not d[bk]:
                raise PlanError("%s is empty: a plan with no factor record "
                                "cannot be bound to a model" % bk)
        for bk in ("numerical", "cost_counters", "storage_schedule"):
            if not isinstance(d[bk], dict) or not d[bk]:
                raise PlanError("%s is empty: the record would carry no %s"
                                % (bk, bk.replace("_", " ")))
        own = [int(o) for o, _w in d["factor_ownership"]]
        scp = [int(o) for o, _sc, _cd in d["factor_scopes"]]
        if sorted(own) != sorted(set(own)):
            raise PlanError("factor_ownership lists an origin twice")
        if sorted(own) != sorted(scp):
            raise PlanError(
                "factor_ownership covers origins %s but factor_scopes covers "
                "%s; ownership and scopes must name the same factors"
                % (sorted(own)[:6], sorted(scp)[:6]))
        props = PlanProperties()
        raw_props = d["properties"]
        if not isinstance(raw_props, dict):
            raise PlanError("properties must be a mapping")
        missing = [p for p in PROPERTIES if p not in raw_props]
        if missing:
            raise PlanError("properties block is incomplete: missing %s" % missing)
        for k, v in raw_props.items():
            if k not in PROPERTIES:
                raise PlanError("unknown property %r in record" % k)
            if not isinstance(v, bool):
                raise PlanError("property %r must be a BOOLEAN, got %r"
                                % (k, type(v).__name__))
            setattr(props, k, v)
        # the prerequisite graph must be satisfied by the loaded flags: a claim
        # flag is never evidence that a proof was checked
        for name in PROPERTIES:
            if getattr(props, name):
                unmet = [q for q in PREREQS[name] if not getattr(props, q)]
                if unmet:
                    raise PlanError(
                        "property %s is set but its prerequisites %s are not: "
                        "an inconsistent verification flag" % (name, unmet))
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
            allocations=_exact_allocations(d["allocations"]),
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


class ExecutorRefusal(Exception):
    """An executor declining with a status and a reason."""

    def __init__(self, status, reason=""):
        super().__init__("%s: %s" % (status, reason))
        self.status = status
        self.reason = reason


_PIPELINE_EXECUTORS = {}


def register_pipeline_executor(kind, fn):
    _PIPELINE_EXECUTORS[kind] = fn


def dispatch_pipeline(kind):
    """The executor the PUBLIC PIPELINE must invoke for this plan kind."""
    fn = _PIPELINE_EXECUTORS.get(kind)
    if fn is None:
        raise PlanError(
            "no pipeline executor is registered for kind %r, so this plan "
            "cannot be executed through the public path" % (kind,))
    return fn


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
