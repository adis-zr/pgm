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
from mdi import config as K

# contract F.2: label every quantity
EXACT = "exact"                 # a counted quantity, no estimation
UPPER = "upper_bound"           # conservative; exceeding a cap is an admission refusal
LOWER = "lower_bound"
CALIB = "measured_calibration"  # observed on this machine, not a guarantee
FORECAST = "forecast"           # a derived prediction
UNKNOWN = "unknown"             # not measured; makes the total UNKNOWN, never 0


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
            if c.value is None or c.label == UNKNOWN:
                # an UNMEASURED component makes the whole total unknown. It may
                # never be read as zero: that is precisely how local
                # construction vanished from the ring comparison.
                self.eligible = False
                if not self.ineligible_reason:
                    self.ineligible_reason = (
                        "%s is UNKNOWN (not measured), so the complete cost of "
                        "this route is unknown and it cannot be compared" % k)
                return None, "unknown"
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
        # Readout: `solve` calls read_marginal once per FREE VARIABLE, and
        # each call is a FULL sweep of that variable's home bag. Charging one
        # sweep per BAG undercounted every bag that is home to more than one
        # variable: the two-variable control priced 35 producer operations and
        # executed 45.
        nin_all = n_children + n_parent
        n_home = sum(1 for v, h in plan.var_home.items() if h == b.idx)
        ro += n_home * (dom * (own + nin_all) + dom)
        # The ROOT/EVIDENCE contraction is a further full sweep of each
        # component root, which `solve` performs via root_value() to establish
        # the evidence weight. It was not priced at all, so small models
        # undercounted: one binary unary priced 4 and executed 5, one ternary
        # priced 6 and executed 8, two independent binary unaries priced 8 and
        # executed 10. Some chains had enough slack elsewhere to hide it.
        if b.parent < 0:
            up += dom * (own + n_children) + max(0, dom - 1)
    rec.put("weighted_bag_visits", weighted_bag, UPPER,
            "bag domain times owned factors plus every incident message")
    rec.put("weighted_separator_entries", weighted_sep, EXACT)
    rec.put("producer_upward_ops", up, UPPER,
            "per assignment: one multiply per owned factor and per child "
            "message, plus at most one add per assignment past the first in a "
            "separator slot")
    rec.put("producer_downward_ops", down, UPPER)
    rec.put("readout_ops", ro, UPPER)
    # The checker's INTERVAL message passing, two endpoints per entry...
    chk = 2 * (up + down + ro)
    # ...PLUS the independent AGGREGATION enumeration, which runs after the
    # interval contraction when the free joint space is within the declared
    # cap. It was absent from the price entirely: on twelve independent binary
    # variables it visits 4,096 assignments and performs about 102,400 exact
    # Fraction operations against a recorded 96. Fraction and MPFR calls are
    # not equal-time units; what was wrong is the omission of a whole
    # algorithm, not any asserted hardware ratio.
    joint = 1
    nvars = 0
    for v in sorted(plan.card):
        joint *= plan.card[v]
        nvars += 1
        if joint > K.CAPS["region_tuple_assignments"]:
            joint = None
            break
    if joint is not None:
        # per assignment: one multiply per factor entry plus one add per
        # variable marker, plus the normalizing division per coordinate
        n_fac = sum(len(b.factors) for b in plan.bags)
        rec.put("independent_enumeration_assignments", joint, EXACT,
                "the bounded independent aggregation check actually runs")
        # Per assignment: one multiply per factor entry, one add per variable
        # marker, AND one add accumulating the weight into Z. Then one
        # division per (variable, state) coordinate to normalize. The previous
        # joint*(n_fac+nvars) omitted the Z addition and the divisions: 12
        # positive binary unaries perform 102,400 multiply/add calls plus 24
        # marginal divisions, where the record said 98,304.
        ncoord = sum(plan.card[v] for v in sorted(plan.card))
        enum_ops = joint * (n_fac + nvars + 1) + ncoord
        rec.put("independent_enumeration_ops", enum_ops, UPPER,
                "per assignment: one multiply per factor entry, one add per "
                "variable marker and one add into Z; plus one division per "
                "published coordinate")
        chk += enum_ops
    else:
        rec.put("independent_enumeration_assignments", 0, EXACT,
                "above the declared cap, so the independent aggregation "
                "check does NOT run and the complete certified status is not "
                "claimed")
    rec.put("checker_ops", chk, UPPER,
            "interval mode carries two endpoints, plus the bounded "
            "independent aggregation enumeration where it runs")
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


def _proj_entries(pc, coarse):
    n = 1
    for i in pc.regions:
        n *= len(coarse[i].cells)
    return n


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
    # Local construction is REAL, PAID work and may not default to zero. On
    # the 12-variable ring control the selected region holds all 12 variables,
    # so region_data enumerates all 4,096 configurations and builds A and all
    # 24 original marker masses -- the complete answer -- before the reduced
    # contraction is priced at six operations. Instrumented, that construction
    # is 151,576 exact-rational arithmetic calls, and the checker reconstructs
    # it twice (303,152). Recording `construction_ops or 0` as an UPPER bound
    # made the headline "6 versus 3,837" comparison omit the work that
    # produced its answer.
    if construction_ops is None:
        # a MEASURED count is required; an unmeasured one is UNKNOWN, which
        # makes the total unknown and the candidate ineligible for a cost win
        rec.put("construction_ops", None, UNKNOWN,
                "local mass/marker construction was not instrumented, so the "
                "complete cost of this route is UNKNOWN")
    else:
        rec.put("construction_ops", int(construction_ops), CALIB,
                "measured exact-rational arithmetic calls in local mass, "
                "marker and profile construction")
    rec.put("requested_markers", n_requested, EXACT)
    rec.put("radius_charged", Fr(radius), EXACT)
    if discovery_s is not None:
        rec.put("discovery_seconds", Fr(round(discovery_s * 1000), 1000), CALIB)
    # The reduced model's own producer cost: the checker now uses a
    # message-passing contraction over the reduced graph, so pricing it as a
    # full joint enumeration (which gave ~1e78 on the external cases) overstates
    # it by the factorization. Price both from the reduced graph's elimination
    # where it is available, and fall back to the enumeration bound otherwise.
    reduced_ops = None
    try:
        from mdi import model as MM, plan as PP, compact as CPX
        facs = []
        for i in range(len(regions)):
            facs.append(MM.Factor(scope=(i,), card=(ncell[i],),
                                  table=[Fr(x) for x in coarse[i].M],
                                  origin=-(i + 1)))
        for pc in projected:
            rs = tuple(pc.regions)
            cards = tuple(ncell[i] for i in rs)
            n = 1
            for cc2 in cards:
                n *= cc2
            if n > 4096:
                raise ValueError("kernel too large to price exactly")
            facs.append(MM.Factor(scope=rs, card=cards,
                                  table=[Fr(1)] * n, origin=-1000))
        cmdl = MM.Model(nvars=len(regions), card=list(ncell), factors=facs)
        cmdl.validate()
        rcm = MM.restrict(cmdl, {})
        sel2 = PP.choose_plan(rcm.free, rcm.card, rcm.factors, 64, 1 << 40)
        if sel2["chosen"] is not None:
            rpl, rest = sel2["chosen"]
            sub = price_identity_plan(rpl, rest, n_requested, 64)
            reduced_ops = {
                "up": int(sub.counters["producer_upward_ops"].value),
                "down": int(sub.counters["producer_downward_ops"].value),
                "ro": int(sub.counters["readout_ops"].value),
                "width": rpl.induced_width,
                "largest_bag": rpl.largest_bag_entries}
    except Exception:
        reduced_ops = None
    if reduced_ops is not None:
        # The PRODUCER forms the joint product over the compact projected
        # crossings and marginalizes (its own contraction, independent of the
        # checker). Pricing it as reduced-graph elimination described a
        # DIFFERENT program: on a two-unary control the price said 54 while
        # the executed producer plus checker performed 110 exact Fraction
        # operations after discovery. Price the branch that RUNS.
        #
        # Joint-product cost: each table multiplied into a running joint of at
        # most `total_assign` entries, one multiply and one add per pair, plus
        # a marginalization sweep per region and the marker division per
        # requested state.
        # The producer runs ELIMINATION over the reduced cell graph, once per
        # queried region. Each elimination step multiplies the tables touching
        # a variable and sums it out; the binding size is the largest
        # intermediate scope, which the reduced plan's largest bag bounds.
        #
        # Count BOTH the multiply and the add at every step: the previous
        # formula counted one operation where the code performs two, so the
        # bound failed at small sizes (44 > 32, 110 > 84, 260 > 208).
        n_tables = len(regions) + len(projected)
        bag = max(1, reduced_ops["largest_bag"])
        nq_regions = max(1, sum(
            1 for i in range(len(regions))
            if any(k[0] in range(10 ** 9) for k in coarse[i].N)))
        # per elimination: at most n_tables combines, each over `bag` entries,
        # with one multiply AND one add per entry, plus the marginalizing add
        per_elim = 2 * n_tables * bag + bag
        prod_pairs = 2 * nq_regions * per_elim
        # projected crossings are materialized once, one value call each
        build = sum(max(1, _proj_entries(pc, coarse)) for pc in projected) \
            if projected else 0
        marg = 2 * nq_regions * bag
        readout = 2 * nq_regions * bag + 4 * n_requested
        rec.put("producer_upward_ops", prod_pairs + build, UPPER,
                "reduced-graph ELIMINATION once per queried region: one "
                "multiply AND one add per intermediate entry per combine, "
                "plus the projected-crossing construction")
        rec.put("producer_downward_ops", marg, UPPER,
                "marginalizing sums over the surviving scope")
        rec.put("readout_ops", readout, UPPER,
                "per-cell marker accumulation and the normalizing division "
                "per requested state, both multiply and divide counted")
        # the CHECKER runs its own reduced-graph message passing in interval
        # mode AND rebuilds every region's local data; both are charged
        chk_mp = 2 * (reduced_ops["up"] + reduced_ops["down"] +
                      reduced_ops["ro"])
        chk_local = 2 * sum(int(getattr(rd, "construction_ops", 0))
                            for rd in rds)
        rec.put("checker_ops", chk_mp + chk_local + marg, UPPER,
                "independent reduced-graph message passing in interval mode, "
                "PLUS the checker's own local region reconstruction and its "
                "containment sweep")
        rec.put("reduced_induced_width", reduced_ops["width"], EXACT)
        rec.put("reduced_largest_bag", reduced_ops["largest_bag"], EXACT)
        rec.bytes_producer = Counter(reduced_ops["largest_bag"] * 64, FORECAST,
                                     "reduced-graph entry counts; excludes "
                                     "object and allocator overhead")
        rec.bytes_checker = Counter(reduced_ops["largest_bag"] * 128, FORECAST,
                                    "interval mode on the reduced graph")
    else:
        rec.put("producer_upward_ops", total_assign, UPPER,
                "joint enumeration fallback: the reduced graph could not be "
                "priced by elimination")
        rec.put("producer_downward_ops", total_assign, UPPER)
        rec.put("readout_ops", total_assign, UPPER)
        rec.put("checker_ops", 2 * total_assign * max(1, len(projected)), UPPER,
                "joint-enumeration fallback bound")
        rec.bytes_producer = Counter(total_assign * 64, FORECAST,
                                     "joint-enumeration fallback")
        rec.bytes_checker = Counter(total_assign * 128, FORECAST,
                                    "joint-enumeration fallback")
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
