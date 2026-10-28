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

    REQUIRED = ("producer_upward_ops", "producer_downward_ops", "readout_ops",
                "checker_ops")

    def total_arithmetic(self):
        """Sum the arithmetic counters. A MISSING required counter makes the
        total UNKNOWN, never zero: an absent price is not a cheap price."""
        keys = self.REQUIRED + ("construction_ops", "statistic_join_ops",
                                "grid_ops")
        missing = [k for k in self.REQUIRED if k not in self.counters]
        if missing:
            self.eligible = False
            if not self.ineligible_reason:
                self.ineligible_reason = ("unpriced work %s: missing cost is "
                                          "UNKNOWN, not zero" % missing)
            return None, "unknown"
        tot = 0
        labels = set()
        for k in keys:
            c = self.counters.get(k)
            if c is None:
                continue
            tot += int(c.value)
            labels.add(c.label)
        label = UPPER if UPPER in labels else (
            EXACT if labels == {EXACT} else FORECAST)
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
    """Price the identity route from its compiled schedule.

    The counts mirror what `Engine.send` ACTUALLY executes per assignment:
    one multiplication per owned factor and per incoming message, plus at most
    one addition per assignment beyond the first that lands in a given
    separator slot. The previous formula used (own + max(0, nin - 1))
    multiplications and no additions, which UNDERSHOT: a 3-variable solve was
    priced at 20 upward operations but executed 24, so the figure was not an
    upper bound at all.
    """
    rec = CostRecord(kind="identity", name="identity")
    up = down = ro = 0
    conv = 0
    weighted_bag = weighted_sep = 0
    for b in plan.bags:
        dom = b.domain(plan.card)
        sd = b.sep_domain(plan.card)
        own = len(b.factors)
        n_children = len(b.children)
        n_parent = 1 if b.parent >= 0 else 0
        weighted_bag += dom * (own + n_children + n_parent)
        weighted_sep += sd
        conv += dom * own
        if b.parent >= 0:
            # upward: owned factors plus the children's messages
            up += dom * (own + n_children) + max(0, dom - sd)
        if b.children:
            # downward: one message per child, each a full bag sweep over the
            # owned factors plus every incoming message except that child
            nin = n_children + n_parent
            per = dom * (own + max(0, nin - 1)) + max(0, dom - sd)
            down += per * n_children
        # readout: one full sweep over the calibrated bag
        nin_all = n_children + n_parent
        ro += dom * (own + nin_all) + dom
    rec.put("weighted_bag_visits", weighted_bag, UPPER,
            "bag domain times owned factors plus every incident message")
    rec.put("weighted_separator_entries", weighted_sep, EXACT)
    rec.put("producer_upward_ops", up, UPPER,
            "per assignment: one multiply per owned factor and per child "
            "message, plus at most one add per assignment past the first in a "
            "separator slot")
    rec.put("producer_downward_ops", down, UPPER)
    rec.put("readout_ops", ro, UPPER)
    rec.put("checker_ops", 2 * (up + down + ro), UPPER,
            "interval mode carries two endpoints")
    rec.put("factor_entry_conversions", conv, UPPER,
            "reduced by the per-entry conversion cache")
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
                                 "executed-schedule simulation; ENTRY COUNTS "
                                 "only. Excludes MPFR object and limb overhead, "
                                 "allocator overhead, input tables and output "
                                 "buffers. NOT measured whole-process memory.")
    rec.bytes_checker = Counter(est["peak_live_entries"] * 128 +
                                est["largest_sep_entries"] * 128, FORECAST,
                                "interval mode, two endpoints per entry; same "
                                "exclusions as the producer figure")
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
        bc = int(r.bytes_checker.value) if r.bytes_checker else 0
        refused = None
        if tot is None:
            refused = r.ineligible_reason or "unpriced work"
        elif cap_bytes and by > cap_bytes:
            refused = ("conservative admission refusal: PRODUCER forecast %d "
                       "bytes exceeds the %d cap" % (by, cap_bytes))
        elif cap_bytes and bc > cap_bytes:
            # producer and checker run sequentially, so the binding constraint
            # is the larger of the two, and the checker was previously ignored
            refused = ("conservative admission refusal: CHECKER forecast %d "
                       "bytes exceeds the %d cap" % (bc, cap_bytes))
        rows.append({"name": r.name, "kind": r.kind, "eligible": r.eligible,
                     "ineligible_reason": r.ineligible_reason,
                     "total_arithmetic": tot, "arithmetic_label": lab,
                     "bytes_producer": by, "bytes_checker": bc,
                     "admission_refusal": refused, "record": r})
    usable = [x for x in rows
              if x["eligible"] and x["admission_refusal"] is None]
    usable.sort(key=lambda x: (x["total_arithmetic"],
                               max(x["bytes_producer"], x["bytes_checker"])))
    return {"ranked": usable, "all": rows,
            "chosen": usable[0] if usable else None,
            "rule": "lowest total arithmetic among ELIGIBLE routes whose "
                    "forecast fits the byte cap; a cell-count ratio is never "
                    "used as the selection criterion"}
