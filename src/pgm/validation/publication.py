"""Common result geometry and the final publication boundary (worker side and controller side).

Worker side (``normalize_result`` / ``suppressed`` / ``write_result``): a backend's raw rows are validated against
the original inventory and binding, never strengthened (a legacy fixed-tolerance row wider than the request's
epsilon is withheld, not promoted), labels are mapped to EXACT / DETERMINISTIC / PAC, EXACT requires zero width,
published rows require a positive-mass witness, and the per-variable interval box must admit the simplex.  Both
payloads (intended and late-suppressed) are encoded BEFORE the authoritative pre-commit sample; a late sample
commits the suppression payload.

Controller side (``accepted_row`` / ``assemble``): the request's guarantee mode filters rows (never weakened),
enclosures of the same coordinate from different attempts must intersect (else CERTIFICATE_DEFECT), the best
label / narrowest row wins, observed coordinates are exact 0/1 once positive mass is witnessed, and the assembled
per-variable box (missing states at [0, 1]) must meet the simplex.  Coordinatewise safe points are not promised
to form a normalized vector; the interval box is simplex-feasible.
"""
from __future__ import annotations

from fractions import Fraction as F
import json
from pathlib import Path
import time

WALL_TOKEN = '"__PGM_WORKER_WALL__"'
DETERMINISTIC_LABELS = {"EXACT", "DETERMINISTIC", "DETERMINISTIC_RESIDUAL"}
PAC_LABELS = {"PAC", "PAC_EB", "PAC_MARKOV", "PAC_MARKOV_RESPONSE"}
RANK = {"EXACT": 0, "DETERMINISTIC": 1, "PAC": 2}


class AdapterRefused(Exception):
    def __init__(self, kind: str, reason: str):
        self.kind, self.reason = kind, reason
        super().__init__(reason)


def empty_rows(inventory):
    return [{"var": v, "variable": v, "state": a, "guarantee": "NOT_PUBLISHED"} for v, a in inventory]


def normalize_result(result: dict, inventory, binding, epsilon: F) -> dict:
    """Validate and normalize a backend result without strengthening its claim."""
    if result.get("binding") and result["binding"] != binding:
        raise AdapterRefused("CERTIFICATE_DEFECT", "backend binding differs from original input")
    expected = set(inventory)
    got = {}
    valid = []
    for raw in result.get("answers") or []:
        key = (raw.get("variable", raw.get("var")), raw.get("state"))
        if key not in expected or key in got:
            raise AdapterRefused("CERTIFICATE_DEFECT", "backend returned unexpected or duplicate coordinate")
        got[key] = raw
    for v, a in inventory:
        raw = got.get((v, a), {})
        label = raw.get("guarantee", "NOT_PUBLISHED")
        row = {"var": v, "variable": v, "state": a, "guarantee": label}
        if label != "NOT_PUBLISHED":
            if label not in DETERMINISTIC_LABELS | PAC_LABELS:
                raise AdapterRefused("CERTIFICATE_DEFECT", f"unrecognized guarantee {label}")
            try:
                lo, hi, point = F(raw["lo"]), F(raw["hi"]), F(raw["point"])
            except (KeyError, ValueError, ZeroDivisionError) as e:
                raise AdapterRefused("CERTIFICATE_DEFECT", "malformed probability enclosure") from e
            if not (0 <= lo <= point <= hi <= 1):
                raise AdapterRefused("CERTIFICATE_DEFECT", "invalid probability enclosure")
            if label == "EXACT" and not lo == hi == point:
                raise AdapterRefused("CERTIFICATE_DEFECT", "EXACT label has nonzero enclosure width")
            if max(point - lo, hi - point) > epsilon:
                # A legacy backend has a fixed tolerance.  Its truthful wider
                # enclosure cannot be promoted to this request's answer.
                row = {"var": v, "variable": v, "state": a, "guarantee": "NOT_PUBLISHED"}
            else:
                row.update(lo=str(lo), hi=str(hi), point=str(point))
                if label in PAC_LABELS:
                    row["guarantee"] = "PAC"
                elif label != "EXACT":
                    row["guarantee"] = "DETERMINISTIC"
        valid.append(row)
    # Coordinatewise points need not sum to one in the inherited contract,
    # but the delivered interval box must admit a probability simplex.
    groups = {}
    for row in valid:
        groups.setdefault(row["var"], []).append(row)
    for rows in groups.values():
        lower = sum((F(r["lo"]) for r in rows if r["guarantee"] != "NOT_PUBLISHED"), F(0))
        upper = sum((F(r["hi"]) if r["guarantee"] != "NOT_PUBLISHED" else F(1) for r in rows), F(0))
        if not lower <= 1 <= upper:
            raise AdapterRefused("CERTIFICATE_DEFECT", "probability interval box misses the simplex")
    mechanism = result.get("mechanism") or {}
    witness = result.get("positive_mass_witness", mechanism.get("positive_mass_witness"))
    published = sum(r["guarantee"] != "NOT_PUBLISHED" for r in valid)
    if published and witness is not True:
        raise AdapterRefused("CERTIFICATE_DEFECT", "published rows lack a positive-mass witness")
    labels = {r["guarantee"] for r in valid if r["guarantee"] != "NOT_PUBLISHED"}
    if published < len(inventory):
        guarantee = "PARTIAL" if published else "NONE"
    elif "PAC" in labels:
        guarantee = "PAC"
    elif "DETERMINISTIC" in labels:
        guarantee = "DETERMINISTIC"
    else:
        guarantee = "EXACT" if witness is True else "NONE"
    outcome = result.get("outcome", "REFUSED")
    if published == len(inventory) and witness is True:
        outcome = "COMPLETE"
    elif outcome in {"COMPLETE", "EXACT"}:
        outcome = "PARTIAL" if published else "REFUSED"
    out = dict(result)
    out.update(answers=valid, K=len(inventory), published=published, outcome=outcome,
               guarantee=guarantee, binding=binding, positive_mass_witness=witness)
    return out


def suppressed(result: dict, inventory, kind="DEADLINE", reason="absolute attempt deadline reached") -> dict:
    out = dict(result)
    out.update(answers=empty_rows(inventory), enclosures=[], published=0,
               K=len(inventory), guarantee="NONE", outcome=kind,
               hard_deadline_respected=False if kind == "DEADLINE" else True)
    out["mechanism"] = dict(result.get("mechanism") or {}, adapter_refusal={"kind": kind, "reason": reason},
                            suppressed_rows=result.get("published", 0))
    for name in ("max_width", "max_radius", "max_published_width", "max_published_radius"):
        if name in out:
            out[name] = None
    return out


def write_result(path: Path, result: dict, inventory, deadline: float, started: float) -> dict:
    """Stage both payloads before the authoritative pre-commit deadline sample."""
    result = dict(result, wall_s="__PGM_WORKER_WALL__", hard_deadline_respected=True)
    late_result = suppressed(result, inventory)
    normal = json.dumps(result, default=str, separators=(",", ":"))
    late = json.dumps(late_result, default=str, separators=(",", ":"))
    if normal.count(WALL_TOKEN) != 1 or late.count(WALL_TOKEN) != 1:
        raise ValueError("ambiguous worker timestamp placeholder")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.monotonic()
    selected = result if now <= deadline else late_result
    payload = (normal if now <= deadline else late).replace(WALL_TOKEN, "%.9e" % (now - started), 1)
    # The parent additionally requires worker termination before the hard
    # request deadline; a write finishing late cannot become a public success.
    with path.open("w") as stream:
        stream.write(payload)
    return selected


# ---------------------------------------------------------------- controller side
def accepted_row(raw, mode, epsilon):
    """the request's guarantee filter: never weakened; geometry re-checked in exact rationals"""
    label = raw.get("guarantee", "NOT_PUBLISHED")
    if label == "NOT_PUBLISHED" or (mode == "exact" and label != "EXACT") or (mode == "deterministic" and label == "PAC"):
        return None
    if label not in RANK:
        raise ValueError("unrecognized published guarantee")
    lo, hi, point = (F(raw[k]) for k in ("lo", "hi", "point"))
    if not 0 <= lo <= point <= hi <= 1 or max(point-lo, hi-point) > epsilon:
        raise ValueError("invalid published enclosure")
    if label == "EXACT" and lo != hi:
        raise ValueError("inexact EXACT publication")
    return dict(raw, lo=str(lo), hi=str(hi), point=str(point))


def merge_row(chosen, key, row):
    """keep the better-labelled / narrower certified enclosure; conflicting enclosures are a defect"""
    prior = chosen.get(key)
    if prior is not None and max(F(prior["lo"]), F(row["lo"])) > min(F(prior["hi"]), F(row["hi"])):
        raise ValueError("conflicting certified coordinate enclosures")
    score = (RANK[row["guarantee"]], F(row["hi"])-F(row["lo"]))
    if prior is None or score < (RANK[prior["guarantee"]], F(prior["hi"])-F(prior["lo"])):
        chosen[key] = row


def assemble(inventory, chosen, cards, witness, outcome):
    """-> (rows, outcome, guarantee, published, error) with the assembled per-variable box checked against the simplex"""
    rows = [chosen.get((v, a), dict(variable=v, var=v, state=a, guarantee="NOT_PUBLISHED")) for v, a in inventory]
    error = None
    # Different individually sound partial boxes must still form a feasible
    # delivered box. Missing/unrequested states retain [0,1], never zero mass.
    if cards:
        by_variable = {}
        for row in rows:
            if row["guarantee"] != "NOT_PUBLISHED":
                by_variable.setdefault(row["variable"], []).append(row)
        for variable, group in by_variable.items():
            lower = sum((F(r["lo"]) for r in group), F(0))
            upper = sum((F(r["hi"]) for r in group), F(0)) + cards[variable]-len(group)
            if not lower <= 1 <= upper:
                outcome = "CERTIFICATE_DEFECT"; error = "combined coordinate box misses the simplex"
                rows = empty_rows(inventory); chosen.clear(); break
    labels = {r["guarantee"] for r in rows if r["guarantee"] != "NOT_PUBLISHED"}
    published = sum(r["guarantee"] != "NOT_PUBLISHED" for r in rows)
    if witness and published == len(inventory) and outcome not in {"CERTIFICATE_DEFECT", "INVALID_TASK", "ZERO_EVIDENCE"}:
        outcome = "COMPLETE"
    elif published:
        outcome = "PARTIAL"
    elif outcome == "COMPLETE":
        outcome = "REFUSED"
    guarantee = ("EXACT" if labels <= {"EXACT"} else "DETERMINISTIC" if labels <= {"EXACT", "DETERMINISTIC"} else "PAC") if outcome == "COMPLETE" else "PARTIAL" if published else "NONE"
    return rows, outcome, guarantee, published, error
