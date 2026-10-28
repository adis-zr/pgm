"""Complete-cost pricing (contract §F).

Prices IMPLEMENTED work, not a cell-count ratio. Every counter carries a LABEL
saying what kind of number it is, because an upper bound and a measured
calibration must never be compared as if they were the same thing.
"""
from __future__ import annotations
import sys
sys.set_int_max_str_digits(0)
from fractions import Fraction as Fr
from dataclasses import dataclass, field

# contract F.2: label every quantity
EXACT = "exact"                 # a counted quantity, no estimation
UPPER = "upper_bound"           # conservative; exceeding a cap is an admission refusal
LOWER = "lower_bound"
CALIB = "measured_calibration"  # observed on this machine, not a guarantee
FORECAST = "forecast"           # a derived prediction


@dataclass
class Counter:
    value: int | Fr
    label: str
    note: str = ""

    def as_dict(self):
        return {"value": str(self.value) if isinstance(self.value, Fr)
                else self.value, "label": self.label, "note": self.note}


@dataclass
class CostRecord:
    """A complete price for one candidate route."""
    kind: str
    name: str
    counters: dict = field(default_factory=dict)
    bytes_producer: Counter | None = None
    bytes_checker: Counter | None = None
    eligible: bool = True
    ineligible_reason: str = ""

    def put(self, key, value, label, note=""):
        self.counters[key] = Counter(value, label, note)
        return self

    def total_arithmetic(self):
        """Sum the arithmetic counters only; conversions are reported apart."""
        keys = ("producer_upward_ops", "producer_downward_ops", "readout_ops",
                "checker_ops", "construction_ops", "statistic_join_ops",
                "grid_ops")
        tot = 0
        labels = set()
        for k in keys:
            c = self.counters.get(k)
            if c is None:
                continue
            tot += int(c.value)
            labels.add(c.label)
        label = UPPER if UPPER in labels else (EXACT if labels == {EXACT} else FORECAST)
        return tot, label

    def as_dict(self):
        d = {"kind": self.kind, "name": self.name, "eligible": self.eligible,
             "ineligible_reason": self.ineligible_reason,
             "counters": {k: c.as_dict() for k, c in self.counters.items()}}
        tot, lab = self.total_arithmetic()
        d["total_arithmetic"] = {"value": tot, "label": lab}
        if self.bytes_producer:
            d["bytes_producer"] = self.bytes_producer.as_dict()
        if self.bytes_checker:
            d["bytes_checker"] = self.bytes_checker.as_dict()
        return d


def price_identity_plan(plan, est, n_requested, precision, preprocess_counts=None):
    """Price the identity route from its compiled schedule."""
    rec = CostRecord(kind="identity", name="identity")
    up = down = ro = 0
    conv = 0
    weighted_bag = weighted_sep = 0
    for b in plan.bags:
        dom = b.domain(plan.card)
        sd = b.sep_domain(plan.card)
        nin = (1 if b.parent >= 0 else 0) + len(b.children)
        own = len(b.factors)
        weighted_bag += dom * (own + nin)
        weighted_sep += sd
        conv += dom * own                    # one factor-entry conversion per visit
        if b.parent >= 0:
            up += dom * (own + max(0, nin - 1))
        if b.children:
            down += dom * (own + nin) * len(b.children)
        ro += dom * (own + nin)
    rec.put("weighted_bag_visits", weighted_bag, UPPER,
            "bag domain times owned factors plus incoming messages")
    rec.put("weighted_separator_entries", weighted_sep, EXACT)
    rec.put("producer_upward_ops", up, UPPER)
    rec.put("producer_downward_ops", down, UPPER)
    rec.put("readout_ops", ro, UPPER)
    rec.put("checker_ops", 2 * (up + down + ro), UPPER,
            "interval mode carries two endpoints")
    rec.put("factor_entry_conversions", conv, UPPER,
            "reduced by the per-entry conversion cache; see G")
    rec.put("requested_markers", n_requested, EXACT)
    rec.put("precision_bits", precision, EXACT)
    rec.put("largest_bag_entries", plan.largest_bag_entries, EXACT)
    rec.put("induced_width", plan.induced_width, EXACT)
    if preprocess_counts:
        rec.put("preprocess_constants_removed",
                preprocess_counts.get("constants", 0), EXACT)
        rec.put("preprocess_pairs_split",
                preprocess_counts.get("splits", 0), EXACT)
    rec.bytes_producer = Counter(est["estimate_bytes"], FORECAST,
                                 "executed-schedule simulation; entry counts "
                                 "only, object and precision overhead excluded")
    rec.bytes_checker = Counter(est["peak_live_entries"] * 128 +
                                est["largest_sep_entries"] * 128, FORECAST,
                                "interval mode, two endpoints per entry")
    return rec


def price_regional_plan(name, regions, coarse, rds, projected, n_requested,
                        radius, discovery_s=None, construction_ops=None):
    """Price the regional route from ACTUAL cells and projected scopes."""
    from mdi import compact as CP
    rec = CostRecord(kind="regional", name=name)
    ncell = [len(c.cells) for c in coarse]
    boundary_states = sum(len(rd.A) for rd in rds)
    cells = sum(ncell)
    rec.put("regions", len(regions), EXACT)
    rec.put("boundary_states", boundary_states, EXACT)
    rec.put("cells", cells, EXACT)
    rec.put("max_cell_cardinality", max(ncell) if ncell else 0, EXACT)
    # the reduced model's own contraction: cell assignments times factors
    total_assign = 1
    for k in ncell:
        total_assign *= k
    rec.put("reduced_cell_assignments", total_assign, UPPER,
            "product over cell cardinalities; the binding structural cost")
    comp = CP.compact_entries(projected)
    rec.put("compact_storage_entries", comp["total"], EXACT,
            "original tables plus offset maps, no Cartesian expansion")
    rec.put("cartesian_entries_avoided",
            CP.cartesian_entries_avoided(projected, coarse), EXACT)
    rec.put("crossing_factors", len(projected), EXACT)
    rec.put("construction_ops", construction_ops or 0,
            CALIB if construction_ops else UPPER,
            "local masses, marks and profile comparisons")
    rec.put("requested_markers", n_requested, EXACT)
    rec.put("radius_charged", Fr(radius), EXACT)
    if discovery_s is not None:
        rec.put("discovery_seconds", Fr(round(discovery_s * 1000), 1000), CALIB)
    # the independent checker repeats the reduced contraction
    rec.put("checker_ops", 2 * total_assign * max(1, len(projected)), UPPER,
            "independent reduced-model contraction, interval mode")
    return rec


def compare(records, cap_bytes=None):
    """Rank eligible routes by total arithmetic, then by bytes.

    An UPPER bound above a cap is an ADMISSION REFUSAL, not a claim about actual
    cost. An ineligible route (no executor or no checker) is never selected
    regardless of attractive algebra.
    """
    rows = []
    for r in records:
        tot, lab = r.total_arithmetic()
        by = int(r.bytes_producer.value) if r.bytes_producer else 0
        refused = None
        if cap_bytes and by > cap_bytes:
            refused = ("conservative admission refusal: forecast %d bytes "
                       "exceeds the %d cap" % (by, cap_bytes))
        rows.append({"name": r.name, "kind": r.kind, "eligible": r.eligible,
                     "ineligible_reason": r.ineligible_reason,
                     "total_arithmetic": tot, "arithmetic_label": lab,
                     "bytes_producer": by, "admission_refusal": refused,
                     "record": r})
    usable = [x for x in rows
              if x["eligible"] and x["admission_refusal"] is None]
    usable.sort(key=lambda x: (x["total_arithmetic"], x["bytes_producer"]))
    return {"ranked": usable, "all": rows,
            "chosen": usable[0] if usable else None,
            "rule": "lowest total arithmetic among ELIGIBLE routes whose "
                    "forecast fits the byte cap; a cell-count ratio is never "
                    "used as the selection criterion"}
