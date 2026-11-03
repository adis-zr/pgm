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

KINDS = ("identity", "regional", "statistic", "gaussian", "fourier", "mixed",
         "composed")


DECLARED_KINDS = ("identity", "regional", "composed", "statistic",
                  "general_statistic", "gaussian", "fourier", "mixed", "deletion",
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
    # The PROGRAM the executor runs and the checker verifies (program.py):
    # every coarsening scale's witness, the collective record, the final
    # elimination order and precision. None for the identity route, whose
    # program is the validated generic schedule itself.
    program: dict | None = None
    # the MANDATORY versioned request/settings object (r20): binds the original
    # model, evidence and query/state schema, the requested width, the
    # numerical settings, the saved order, the checking strategy and the
    # resource limits wherever they define execution. Missing or inconsistent
    # fields refuse at load, before any numerical work.
    request: dict | None = None

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
        if mode is not None and mode not in ("P", "I", "E"):
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
        if self.program is not None:
            d["program"] = self.program
        if self.request is not None:
            d["request"] = self.request
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
                               "rejected_alternatives", "program", "request"}
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
            properties=props, version=d["version"],
            program=d.get("program"), request=d.get("request"))
        rec.request = validate_request(rec.request, rec)
        if rec.program is not None:
            # the program block is parsed STRICTLY: exact strings, known
            # fields, a kind that agrees with the record
            from mdi import program as _PG
            try:
                parsed = _PG.validate_program(rec.program)
            except _PG.ProgramError as e:
                raise PlanError("the plan's program block is invalid: %s" % e)
            if parsed["kind"] != rec.kind:
                raise PlanError("the program names kind %r but the record is %r"
                                % (parsed["kind"], rec.kind))
            rec.parsed_program = parsed
        else:
            raise PlanError("a %s plan carries no program block, so nothing "
                            "describes what its executor would run" % rec.kind)
        return rec.validate()

    def bind_check(self, model_sha, evidence_sha, query_sha,
                   restricted=None, preprocess_identity=None,
                   max_precision=None):
        """Reject a plan bound to different inputs BEFORE expensive work.

        Also binds the record's SEMANTIC fields against the original inputs
        and the registry. Previously only the three hashes and field SYNTAX
        were checked, so six self-consistent FALSE records still certified --
        their answers were right only because the false content was ignored:
        a nonexistent executor reference, a false precision, an unrelated
        factor 999 over variable 999, an empty preprocessing proof, a zero
        cost and a zero storage schedule.
        """
        if (self.model_sha256 != model_sha or
                self.evidence_sha256 != evidence_sha or
                self.query_sha256 != query_sha):
            raise PlanError(
                "plan record is bound to different inputs: record "
                "(%s/%s/%s) vs current (%s/%s/%s)"
                % (self.model_sha256[:8], self.evidence_sha256[:8],
                   self.query_sha256[:8], model_sha[:8], evidence_sha[:8],
                   query_sha[:8]))

        # A PERSISTED plan is a program, not a certificate. Completion flags
        # are established by the run that executes and checks it; a record
        # that arrives claiming them is forged or stale and must not bind.
        claimed = [p_ for p_ in ("selected", "producer_complete",
                                 "independently_verified",
                                 "publication_contract_met")
                   if getattr(self.properties, p_)]
        if claimed:
            raise PlanError("the persisted plan claims completion flags %s; a "
                            "saved program carries no verification state"
                            % claimed)

        # the named implementations must RESOLVE, not merely look like mdi
        # module paths
        import importlib
        for idk, idv in (("executor_id", self.executor_id),
                         ("checker_id", self.checker_id)):
            mod, _, fn = idv.partition(":")
            try:
                mm = importlib.import_module(mod)
            except ImportError as e:
                raise PlanError("%s %r names a module that does not exist: %s"
                                % (idk, idv, e))
            if not hasattr(mm, fn):
                raise PlanError("%s %r names %r, which does not exist in %s"
                                % (idk, idv, fn, mod))
            if not callable(getattr(mm, fn)):
                raise PlanError("%s %r is not callable" % (idk, idv))

        # numerical settings must be usable
        prec = self.numerical.get("precision")
        if not isinstance(prec, int) or prec < 8:
            raise PlanError("numerical precision %r is not a usable bit width"
                            % (prec,))
        if max_precision is not None and prec > max_precision:
            raise PlanError(
                "numerical precision %d exceeds the declared maximum %d, so "
                "the record does not describe a runnable program"
                % (prec, max_precision))

        # the preprocessing proof must be present and must MATCH the one the
        # current inputs produce
        if not self.preprocess_identity:
            raise PlanError("the preprocessing proof is EMPTY, so nothing "
                            "binds the emitted law to the original model")
        if preprocess_identity is not None:
            # compare through JSON so a round-tripped record (tuples become
            # lists, Fractions become strings) matches a freshly built proof
            if json.loads(json.dumps(self.preprocess_identity,
                                     sort_keys=True, default=str)) != \
                    json.loads(json.dumps(preprocess_identity,
                                          sort_keys=True, default=str)):
                raise PlanError(
                    "the recorded preprocessing proof does not match the one "
                    "the current inputs produce")

        # factor scopes and ownership must name the ACTUAL restricted factors
        if restricted is not None:
            want = {}
            for f in restricted.factors:
                want[f.origin] = (tuple(f.scope), tuple(f.card))
            got = {o: (tuple(sc), tuple(cd))
                   for o, sc, cd in self.factor_scopes}
            if set(got) != set(want):
                extra = sorted(set(got) - set(want))
                miss = sorted(set(want) - set(got))
                raise PlanError(
                    "factor_scopes names origins that are not in the "
                    "restricted model (extra %s, missing %s)"
                    % (extra[:4], miss[:4]))
            for o, (sc, cd) in sorted(got.items()):
                if (sc, cd) != want[o]:
                    raise PlanError(
                        "factor %d is recorded with scope %s card %s but the "
                        "model has scope %s card %s"
                        % (o, sc, cd, want[o][0], want[o][1]))
            for v in sorted(restricted.card):
                if not any(v in sc for sc, _cd in got.values()):
                    raise PlanError(
                        "free variable %d appears in no recorded factor scope"
                        % v)

        # a cost record of zero work, or a zero storage schedule, does not
        # describe a program that actually ran
        # An ABSENT cost record is rejected. A record whose counters are all
        # zero is rejected only when the plan also claims arithmetic work:
        # some legitimate small plans genuinely perform none.
        if not self.cost_counters:
            raise PlanError("the cost record is empty, so no work is priced")
        _opk = [k for k in self.cost_counters if "ops" in k]
        if _opk:
            _vals = []
            for k in _opk:
                v = self.cost_counters[k]
                val = v.get("value") if isinstance(v, dict) else v
                if isinstance(val, (int, float)):
                    _vals.append(val)
            if _vals and max(_vals) <= 0 and len(_opk) >= 3:
                raise PlanError(
                    "every one of the %d recorded arithmetic counters is "
                    "zero, so the cost record does not describe the work this "
                    "plan performs" % len(_opk))
        # A zero storage schedule is NOT itself a fault: a single-bag model
        # genuinely holds no live message, so peak_live_entries = 0 is the
        # correct record. What must be rejected is an ABSENT schedule.
        if not self.storage_schedule:
            raise PlanError("the storage schedule is empty, so the record "
                            "describes no storage behaviour at all")
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


REQUEST_VERSION = 4          # 2026-11-02: the physical capacity policy is named; r21 frozen maxima + effective limits kept
REQUEST_KEYS = ("version", "model_sha256", "evidence_sha256", "query_sha256", "queries", "observed",
                "card", "width", "precision", "max_precision", "emin", "emax", "arithmetic_mode",
                "order", "checker_strategy", "checker_precision", "collective_precision", "limits", "capacity")
MAX_PRECISION = 4096
# the FROZEN algorithm maxima (never exceeded by any invocation) and the
# EFFECTIVE per-invocation limits (what the caller actually ran under; a later
# replay runs under the minimum of these and its own caller's limits)
FROZEN_LIMIT_KEYS = ("local_mass_entries", "profile_comparisons", "arm_wall_s", "arm_rss_bytes")
EFFECTIVE_LIMIT_KEYS = ("wall_s", "rss_bytes", "local_mass_entries", "profile_comparisons")


def frozen_limits():
    from mdi import config as K
    return {"local_mass_entries": int(K.CAPS["local_mass_entries"]),
            "profile_comparisons": int(K.CAPS["profile_entry_comparisons"]),
            "arm_wall_s": float(K.RESOURCES["arm_wall_s"]),
            "arm_rss_bytes": int(K.RESOURCES["arm_rss_bytes"])}


def effective_limits_from(effective=None):
    """The effective limits object: the caller's actual limits (from the
    invocation budget) or, when none are given, the frozen maxima."""
    fz = frozen_limits()
    eff = dict(effective or {})
    return {"wall_s": float(eff.get("wall_s", fz["arm_wall_s"])),
            "rss_bytes": int(eff.get("rss_bytes") or fz["arm_rss_bytes"]),
            "local_mass_entries": int(eff.get("local_mass_entries", fz["local_mass_entries"])),
            "profile_comparisons": int(eff.get("profile_comparisons", fz["profile_comparisons"]))}


def make_request(model_sha, evidence_sha, query_sha, queries, evidence, card, width, numerical,
                 order, checker, limits, collective=None):
    """The one request/settings object every stage consumes."""
    return {"collective_precision": int((collective or {}).get("precision", 0)),"version": REQUEST_VERSION, "model_sha256": model_sha, "evidence_sha256": evidence_sha,
            "query_sha256": query_sha, "queries": sorted(int(v) for v in queries),
            "observed": {str(int(v)): int(s) for v, s in sorted(evidence.items())},
            "card": {str(int(v)): int(card[v]) for v in sorted(queries)},
            "width": str(Fr(width)), "precision": int(numerical.get("precision", 0)),
            "max_precision": MAX_PRECISION,
            "emin": (None if numerical.get("emin") is None else int(numerical["emin"])),
            "emax": (None if numerical.get("emax") is None else int(numerical["emax"])),
            "arithmetic_mode": str(numerical.get("mode", "")),
            "order": [int(x) for x in (order or [])],
            "checker_strategy": str((checker or {}).get("strategy", "")),
            "checker_precision": int((checker or {}).get("precision", 0)),
            "limits": {"frozen": frozen_limits(), "effective": effective_limits_from(limits)},
            "capacity": capacity_policy()}


def capacity_policy():
    """The admission policy and calibration a record was priced under (request v4,
    2 November 2026): admission against the physical budget from calibrated forecasts
    of the executing schedules (mdi.capacity), in the layout that executes. The
    calibration version is bound to the layout, so a host taking the scalar
    fallback never inherits the vectorized rates (and vice versa)."""
    from mdi import capacity as CAP
    cal = CAP.calibration_for_layout()
    return {"policy": "physical-2026-11-02", "calibration": cal["version"], "layout": cal["layout"]}


def validate_request(req, rec):
    """Strict parse of the request object and consistency with the record it
    governs: hashes, requested set, width, EVERY precision the execution
    consumes (outer numerical, program, collective, checker) at or below the
    declared maximum, order and checking strategy. Missing -> PlanError."""
    if req is None:
        raise PlanError("the plan record carries no request object; a program is an executable "
                        "FOR one request and must bind it (missing 'request')")
    if not isinstance(req, dict):
        raise PlanError("request must be a mapping")
    miss = [k for k in REQUEST_KEYS if k not in req]
    extra = sorted(set(req) - set(REQUEST_KEYS))
    if miss or extra:
        raise PlanError("request object missing %s / unknown %s" % (miss, extra))
    if req["version"] != REQUEST_VERSION:
        raise PlanError("stale request version %r" % req["version"])
    for k in ("model_sha256", "evidence_sha256", "query_sha256"):
        if req[k] != getattr(rec, k):
            raise PlanError("request %s differs from the record's" % k)
    try:
        w = Fr(req["width"])
    except (ValueError, TypeError, ZeroDivisionError):
        raise PlanError("request width %r is not an exact rational" % (req["width"],))
    if not (0 < w <= 1):
        raise PlanError("request width %s is not in (0, 1]" % w)
    if int(req["max_precision"]) != MAX_PRECISION:
        raise PlanError("request declares maximum precision %s, the contract fixes %d"
                        % (req["max_precision"], MAX_PRECISION))
    precs = {"request.precision": int(req["precision"]), "request.checker_precision": int(req["checker_precision"]),
             "numerical.precision": int((rec.numerical or {}).get("precision", 0))}
    if int(req["collective_precision"]) > MAX_PRECISION:
        raise PlanError("request.collective_precision = %d exceeds the declared maximum %d"
                        % (int(req["collective_precision"]), MAX_PRECISION))
    prog = rec.program or {}
    if prog:
        precs["program.precision"] = int(prog.get("precision", 0))
        if prog.get("checker"):
            precs["program.checker.precision"] = int(prog["checker"].get("precision", 0))
        if prog.get("collective"):
            precs["program.collective.precision"] = int(prog["collective"].get("precision", 0))
    for k, v in precs.items():
        if v > MAX_PRECISION:
            raise PlanError("%s = %d exceeds the declared maximum %d" % (k, v, MAX_PRECISION))
        if v < 1:
            raise PlanError("%s = %d is not a positive precision" % (k, v))
    if precs["request.precision"] != precs["numerical.precision"]:
        raise PlanError("request precision %d and the record's numerical precision %d disagree"
                        % (precs["request.precision"], precs["numerical.precision"]))
    if prog:
        if precs["request.precision"] != precs.get("program.precision", precs["request.precision"]):
            raise PlanError("request precision %d and the program precision %d disagree"
                            % (precs["request.precision"], precs["program.precision"]))
        if prog.get("checker") and precs["request.checker_precision"] != precs["program.checker.precision"]:
            raise PlanError("request checker precision %d and the program's %d disagree"
                            % (precs["request.checker_precision"], precs["program.checker.precision"]))
        if prog.get("collective") and int(prog["collective"].get("precision", 0)) != int(req["collective_precision"]):
            raise PlanError("the collective record's precision %s differs from the request's declared "
                            "collective precision %s" % (prog["collective"].get("precision"), req["collective_precision"]))
        if [int(x) for x in (prog.get("order") or [])] != list(req["order"]):
            raise PlanError("request order differs from the program order")
        # the ARITHMETIC settings the execution consumes are bound, not metadata
        arith = prog.get("arithmetic") or {}
        if str(req["arithmetic_mode"]) not in ("P", "E"):
            raise PlanError("request arithmetic mode %r is not P or E" % (req["arithmetic_mode"],))
        if str(req["arithmetic_mode"]) != str(arith.get("mode")):
            raise PlanError("request arithmetic mode %r differs from the program's %r"
                            % (req["arithmetic_mode"], arith.get("mode")))
        if (rec.kind == "identity") != (req["arithmetic_mode"] == "P"):
            raise PlanError("arithmetic mode %r is not the mode of a %s program" % (req["arithmetic_mode"], rec.kind))
        if req["arithmetic_mode"] == "P":
            for k in ("emin", "emax"):
                if not isinstance(req[k], int) or isinstance(req[k], bool):
                    raise PlanError("request %s must be an integer for the MPFR point kernel" % k)
                if req[k] != arith.get(k):
                    raise PlanError("request %s = %s differs from the program's %s" % (k, req[k], arith.get(k)))
            if not (req["emin"] < 0 < req["emax"]):
                raise PlanError("request exponent range [%s, %s] is not a usable range" % (req["emin"], req["emax"]))
        else:
            # exact arithmetic has NO exponent range: the defined empty value is null
            for k in ("emin", "emax"):
                if req[k] is not None or arith.get(k) is not None:
                    raise PlanError("request %s must be null for exact arithmetic (got %r / program %r)"
                                    % (k, req[k], arith.get(k)))
        if (prog.get("collective") is not None) != (int(req["collective_precision"]) > 0):
            raise PlanError("request collective precision %s does not match the presence of a collective record"
                            % req["collective_precision"])
        if prog.get("checker") and int(prog["checker"].get("precision", 0)) != int(req["checker_precision"]):
            raise PlanError("request checker precision differs from the program's")
    # the LIMITS: frozen maxima must be the contract's; effective limits are
    # positive and never above the frozen maxima; nothing is optional or null
    lim = req["limits"]
    if not isinstance(lim, dict) or set(lim) != {"frozen", "effective"}:
        raise PlanError("request limits must carry exactly 'frozen' and 'effective'")
    fz = frozen_limits()
    if not isinstance(lim["frozen"], dict) or set(lim["frozen"]) != set(FROZEN_LIMIT_KEYS):
        raise PlanError("request frozen limits must carry %s" % list(FROZEN_LIMIT_KEYS))
    for k in FROZEN_LIMIT_KEYS:
        if float(lim["frozen"][k]) != float(fz[k]):
            raise PlanError("request frozen limit %s = %s differs from the contract's %s" % (k, lim["frozen"][k], fz[k]))
    # the CAPACITY policy (v4): the admission policy and calibration this record was priced under
    cap = req.get("capacity")
    if not isinstance(cap, dict) or set(cap) != {"policy", "calibration", "layout"}:
        raise PlanError("request capacity must carry exactly policy, calibration and layout")
    want = capacity_policy()
    if cap["policy"] != want["policy"] or cap["calibration"] != want["calibration"]:
        raise PlanError("request capacity policy %s / calibration %s differ from the contract's %s / %s"
                        % (cap["policy"], cap["calibration"], want["policy"], want["calibration"]))
    eff = lim["effective"]
    if not isinstance(eff, dict) or set(eff) != set(EFFECTIVE_LIMIT_KEYS):
        raise PlanError("request effective limits must carry %s" % list(EFFECTIVE_LIMIT_KEYS))
    bound = {"wall_s": fz["arm_wall_s"], "rss_bytes": fz["arm_rss_bytes"],
             "local_mass_entries": fz["local_mass_entries"], "profile_comparisons": fz["profile_comparisons"]}
    for k in EFFECTIVE_LIMIT_KEYS:
        v = eff[k]
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PlanError("request effective limit %s = %r is not a number" % (k, v))
        if not (0 < float(v) <= float(bound[k])):
            raise PlanError("request effective limit %s = %s is not in (0, %s]" % (k, v, bound[k]))
    if prog:
        if prog.get("checker") and str(prog["checker"].get("strategy", "")) != req["checker_strategy"]:
            raise PlanError("request checking strategy differs from the program's")
        if sorted(int(v) for v in (prog.get("queries") or [])) != list(req["queries"]):
            raise PlanError("request queries differ from the program's requested set")
    return req


def query_hash(nvars, card, evidence, queries) -> str:
    h = hashlib.sha256()
    h.update(("nvars=%d;" % nvars).encode())
    h.update((",".join(str(c) for c in card) + ";").encode())
    h.update((",".join("%d:%d" % (v, s) for v, s in sorted(evidence.items())) + ";").encode())
    h.update((",".join(str(v) for v in sorted(queries))).encode())
    return h.hexdigest()
