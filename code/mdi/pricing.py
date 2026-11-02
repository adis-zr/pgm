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
    # feasibility at the checking standard actually promised: per engine,
    # FEASIBLE / *_CAP_PROVED (full positive support proves the cap excess) /
    # *_FEASIBILITY_UNKNOWN (hard zeros leave the sparse occupancy unknown)
    feasibility: dict = field(default_factory=lambda: {"producer": "FEASIBLE", "checker": "FEASIBLE"})

    def put(self, key, value, label, note=""):
        self.counters[key] = Counter(value, label, note)
        return self

    REQUIRED = ("producer_upward_ops", "producer_downward_ops", "readout_ops",
                "checker_ops")

    SUNK = ("construction_ops", "mode_fit_ops")

    def total_arithmetic(self):
        """The REMAINING cost: producer execution and independent checking of
        the loaded program. This is the selection quantity. Already-paid
        discovery work (construction, mode fitting) is accounted separately in
        `sunk_arithmetic` and in the complete invocation cost; it is not
        charged again against a candidate at selection. A MISSING required
        counter makes the total UNKNOWN, never zero."""
        keys = self.REQUIRED + ("statistic_join_ops", "grid_ops", "producer_comparison_ops", "checker_comparison_ops")
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

    def sunk_arithmetic(self):
        """Discovery work already paid for this candidate (measured or forecast)."""
        tot = 0
        labels = set()
        for k in self.SUNK:
            c = self.counters.get(k)
            if c is None or c.value is None or c.label == UNKNOWN:
                continue
            tot += int(c.value)
            labels.add(c.label)
        return tot, ("forecast" if FORECAST in labels or CALIB in labels else EXACT)

    def as_dict(self):
        d = {"kind": self.kind, "name": self.name, "eligible": self.eligible,
             "ineligible_reason": self.ineligible_reason,
             "counters": {k: c.as_dict() for k, c in self.counters.items()}}
        tot, lab = self.total_arithmetic()
        d["total_arithmetic"] = {"value": tot, "label": lab,
                                 "convention": "REMAINING execution + checking of the "
                                               "loaded program; sunk discovery separate"}
        st, sl = self.sunk_arithmetic()
        d["sunk_arithmetic"] = {"value": st, "label": sl}
        d["feasibility"] = dict(self.feasibility)
        d["labels"] = {"exact_structural_counts": sorted(k for k, c in self.counters.items() if c.label == EXACT),
                       "safe_bounds": sorted(k for k, c in self.counters.items() if c.label == UPPER),
                       "heuristic_prices": sorted(k for k, c in self.counters.items() if c.label == FORECAST),
                       "work_already_spent": sorted(k for k, c in self.counters.items() if c.label == CALIB)}
        if self.bytes_producer:
            d["bytes_producer"] = self.bytes_producer.as_dict()
        if self.bytes_checker:
            d["bytes_checker"] = self.bytes_checker.as_dict()
        return d


def identity_checker_feasibility(plan, r, budget=None, wall_remaining_s=None, rss_cap_bytes=None,
                                 rss_now_bytes=0, checker_plan=None):
    """Applicability of the identity route's INDEPENDENT checker and exact
    aggregation, decided before any producer work -- against the PHYSICAL budget
    (2 November 2026, config.AMENDMENTS[0]): the producer's saved order and the
    checker's OWN min-fill plan (the schedule `solve._check` actually builds)
    are forecast at the calibrated rates of the layout that executes
    (mdi.capacity). `checker` is FEASIBLE when producer + interval checker fit
    the remaining wall and the RSS cap; `aggregation` says whether the exact
    aggregation also fits (when it does not, the route still runs and ends as
    VERIFIED_SHARED_AGGREGATION_ONLY, never a certificate). A refusal names the
    stage and the figures; it is a forecast at this calibration, never a proof
    about other hardware."""
    from mdi import capacity as CAP, config as K
    chk = checker_plan if checker_plan is not None else CAP.checker_plan(r)
    fc = CAP.forecast_identity(plan, chk, r.factors, r.card, r.free)
    wall = float(wall_remaining_s) if wall_remaining_s is not None else float(K.RESOURCES["arm_wall_s"])
    cap = int(rss_cap_bytes) if rss_cap_bytes is not None else int(K.RESOURCES["arm_rss_bytes"])
    ad = CAP.admit(fc, wall, cap, rss_now_bytes or 0)
    out = {"producer": "FEASIBLE", "largest_bag": int(plan.largest_bag_entries),
           "checker_largest_bag": int(chk.largest_bag_entries), "checker_order": chk.name,
           "policy": "physical-2026-11-02", "calibration": fc["calibration"],
           "forecast_seconds": fc["seconds"], "forecast_bytes": fc["bytes"], "exact_root_bits_bound": fc["exact_root_bits_bound"],
           "admission": ad}
    if ad["route"] == "FEASIBLE":
        out["checker"] = "FEASIBLE"
        out["checker_reason"] = ad["route_reason"]
    else:
        out["checker"] = "CHECKER_" + ad["route"]
        out["checker_reason"] = ad["route_reason"]
    out["aggregation"] = ad["aggregation"]
    out["aggregation_reason"] = ad["aggregation_reason"]
    return out




def _comparison_bound(rec):
    """Every exact-rational COMPARISON and sign test the engines perform is
    priced by name, per engine, from the arithmetic bounds already on the
    record: the interval hull of k products takes at most 2(k-1) < 2k
    comparisons (min and max), an interval add takes none, and every produced
    entry (at least one multiply each) is tested for sign / zero / absolute
    value at most three times -- so comparisons + sign tests <= 3 x arithmetic
    operations. The matrix counts EVERY Fraction operation (arithmetic,
    comparison, negation, absolute value, power) and compares the sum with
    arithmetic + this bound, per engine."""
    def _val(k):
        c = rec.counters.get(k)
        return None if (c is None or c.value is None) else int(c.value)
    prod = [_val(k) for k in ("producer_upward_ops", "producer_downward_ops", "readout_ops")]
    chk = _val("checker_ops")
    if None not in prod:
        rec.put("producer_comparison_ops", 3 * sum(prod), UPPER,
                "comparisons and sign tests of the producer: <= 3 x its arithmetic bound (hull 2(k-1) per k products; "
                "<= 3 per-entry tests, >= 1 multiply per entry)")
    if chk is not None:
        rec.put("checker_comparison_ops", 3 * chk, UPPER,
                "comparisons and sign tests of the checker: <= 3 x its arithmetic bound")
    return rec


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
                "above the declared enumeration cap")
        # ABOVE the enumeration cap the checker runs the STRUCTURAL second
        # implementation (sparse exact junction tree) when its bags fit the
        # declared contraction-space cap. Forecast that applicability BEFORE
        # execution, so a run whose complete status cannot be claimed is
        # known to be shared-aggregation-only up front.
        # ABOVE the enumeration cap the checker runs the STRUCTURAL second
        # implementation (the exact integer aggregation, vectorized) when the
        # PHYSICAL budget admits it (mdi.capacity; config.AMENDMENTS[0]). The
        # forecast here records the aggregation's work on the checker's own
        # min-fill schedule; whether it fits the wall and the RSS cap is decided
        # by `identity_checker_feasibility`, recorded on the price's feasibility.
        rec.put("independent_aggregation_forecast", 1, FORECAST,
                "the exact integer aggregation runs on the checker's min-fill schedule when the physical "
                "budget admits it (capacity forecast on the record's feasibility); otherwise the complete "
                "certified status is not claimed")
        sj = sum(2 * b.domain(plan.card) * (len(b.factors) + len(b.children) + 2)
                 for b in plan.bags)
        rec.put("independent_sparse_ops", sj, UPPER,
                "exact aggregation over the bag domains (two operations per entry per table)")
        chk += sj
    rec.put("checker_ops", chk, UPPER,
            "interval mode carries two endpoints, plus the bounded "
            "independent aggregation enumeration where it runs")
    # the SHARED ENTRY METER, in the unit the engines charge: the producer's
    # messages (one separator table per upward and per downward message), the
    # checker's interval messages (the same schedule), its enumeration
    # assignments (when within the cap) and the exact aggregation's visited
    # entries (at most one per bag-domain entry). The meter's cap is its
    # physical backstop (AMENDMENTS[0]); admission is by `identity_checker_feasibility`.
    msg_entries = 2 * sum(b.sep_domain(plan.card) for b in plan.bags if b.parent >= 0)
    p_entries = msg_entries
    c_entries = msg_entries + (joint or 0) + sum(b.domain(plan.card) for b in plan.bags)
    rec.put("producer_metered_entries", p_entries, UPPER, "identity producer message entries on the shared meter")
    rec.put("checker_metered_entries", c_entries, UPPER,
            "identity checker: interval messages + enumeration assignments + exact aggregation entries")
    rec.put("metered_entries_forecast", p_entries + c_entries, UPPER,
            "producer + checker visits against the cumulative local_mass_entries meter (same unit as the meter)")
    if p_entries + c_entries > K.CAPS["local_mass_entries"] and rec.eligible:
        rec.eligible = False
        rec.ineligible_reason = ("the identity's forecast metered entries %d exceed the shared meter's physical backstop %d"
                                 % (p_entries + c_entries, K.CAPS["local_mass_entries"]))
    rec.put("factor_entry_conversions", conv, UPPER,
            "reduced by the per-entry conversion cache")
    rec.put("requested_markers", n_requested, EXACT)
    _comparison_bound(rec)
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
                        radius, discovery_s=None, construction_ops=None,
                        restricted=None):
    """Price the regional route from ACTUAL cells and projected scopes.

    `restricted` lets the checker's profile-proof term be priced from the real
    factor scopes and domains; without it that term falls back to the coarse
    per-occurrence cap bound."""
    restricted_factors = restricted.factors if restricted is not None else None
    card_of = dict(restricted.card) if restricted is not None else {}
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
        # The checker's PROFILE-PRODUCT proof is additional exact construction,
        # not free verification: for every crossing-factor group it recomputes
        # the response kernel from the original factors (one multiply per
        # constituent factor per kernel entry) and compares every entry. r12
        # added this work without pricing it; an unchanged padded bound may or
        # may not have covered it, and that is a relation to prove, not to
        # assume from source unchangedness.
        # Price the groups and layouts the checker ACTUALLY verifies, from
        # scopes and domains alone -- no numerical inference is needed to know
        # a kernel's entry count. With k constituent factors and N kernel
        # entries the proof performs at most (k+1)N operations: one multiply
        # per factor per entry plus one exact comparison per entry. The
        # previous term charged 2*4096 per crossing occurrence regardless of
        # size: 16,384 priced for 16 observed operations on a binary pair,
        # 1,024x the counted work, loose enough to reverse an internal ranking
        # between manually supplied candidates.
        chk_profile = 0
        for i, rd in enumerate(rds):
            rset = set(regions[i])
            cross = list(getattr(rd, "crossing_factors", []) or [])
            # mirror the aggregator's grouping by incident-region scope so the
            # priced representation is the one that executes
            grp = {}
            for fi in cross:
                f = restricted_factors[fi] if restricted_factors else None
                if f is None:
                    grp.setdefault(("_", fi), []).append(fi)
                    continue
                key = tuple(sorted(v for v in f.scope if v not in rset))
                grp.setdefault(key, []).append(fi)
            for key, fis in grp.items():
                if restricted_factors is None:
                    chk_profile += 2 * K.CAPS["aggregated_kernel_entries"]
                    continue
                scope = sorted({v for fi in fis
                                for v in restricted_factors[fi].scope})
                n_ent = 1
                for v in scope:
                    n_ent *= card_of[v]
                if len(fis) > 1 and n_ent <= K.CAPS["aggregated_kernel_entries"]:
                    chk_profile += (len(fis) + 1) * n_ent      # one aggregate
                else:
                    for fi in fis:                              # fallback
                        ne = 1
                        for v in restricted_factors[fi].scope:
                            ne *= card_of[v]
                        chk_profile += 2 * ne
        rec.put("checker_profile_proof_ops", chk_profile, UPPER,
                "sum over the ACTUAL emitted representation of (k+1)*N per "
                "profile: one exact multiply per constituent factor per kernel "
                "entry plus one exact comparison per entry, from scopes and "
                "domains alone")
        rec.put("checker_ops", chk_mp + chk_local + chk_profile + marg, UPPER,
                "independent reduced-graph message passing in interval mode, "
                "PLUS the checker's own local region reconstruction, PLUS its "
                "profile-product proof, PLUS its containment sweep")
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
    _comparison_bound(rec)
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
            "rule": "lowest REMAINING arithmetic (execution + independent "
                    "checking of the loaded program) among ELIGIBLE routes whose "
                    "forecast fits the byte cap; already-paid discovery and "
                    "construction are reported separately and never compared as "
                    "remaining cost; a cell-count ratio is never used"}


# ======================= program routes (the executed schedule) =======================

def _stat_span(kq, rank, vars_, card, cap):
    """Upper bound on the statistic support over a variable set: the lattice
    span per mode, the product of distinct per-variable values, the cap."""
    span = 1
    for k in range(rank):
        lo = hi = 0
        for v in vars_:
            row = kq[k][v]
            lo += min(row)
            hi += max(row)
        span *= (hi - lo + 1)
    distinct = 1
    for v in vars_:
        distinct *= len({tuple(kq[k][v][a] for k in range(rank))
                         for a in range(card[v])})
    return max(1, min(span, distinct, cap))


ALGEBRA_COST = {
    # Fraction operations per algebra primitive, counted from the code:
    #   rational: one multiply / one add
    #   interval: two endpoints each
    #   complex rectangle: 16 corner products + 4 sums/differences; 4 adds
    "rational": (1, 1), "interval": (2, 2), "complex": (20, 4)}


_PRIM = {}


def primitive_call_counts():
    """MPFR calls per enclosure primitive of EACH engine, measured once by
    running the primitives through the counting proxy (wide trigonometric
    intervals exercise the interior-extremum branches). The transcendental
    forecast is built from these measured constants, per engine."""
    if _PRIM:
        return _PRIM
    from mdi import collective as CO, program_check as PC, arith as A
    ctx = A.Ctx(64)

    def count(fn):
        snap = A.transcendental_snapshot()      # the counter is monotone: measure by difference
        fn()
        return A.transcendental_since(snap)["total"]
    wide = [(Fr(0), Fr(7)), (Fr(-1), Fr(1)), (Fr(1, 3), Fr(1, 2)), (Fr(3), Fr(10))]
    _PRIM.update({
        "p_weight": count(lambda: CO._normal_weight(Fr(1, 2), Fr(1), ctx)),
        "p_tilt": count(lambda: CO._exp_enclose(Fr(1, 3), Fr(1, 2), Fr(2, 3), ctx)),
        "p_sqrt": count(lambda: CO._sqrt_enclose(Fr(2), ctx)),
        "p_phase": max(count(lambda: (CO._cos_enclose(a, b, ctx), CO._sin_enclose(a, b, ctx))) for a, b in wide),
        "c_weight": count(lambda: PC._own_normal_weight(Fr(1, 2), Fr(1), ctx)),
        "c_tilt": count(lambda: (PC._own_exp_pair(Fr(1, 3), ctx), PC._own_exp_pair(Fr(1, 2), ctx))),
        "c_sqrt": count(lambda: PC._own_sqrt_pair(Fr(2), ctx)),
        "c_phase": max(count(lambda: (PC._own_trig(a, b, ctx, "cos"), PC._own_trig(a, b, ctx, "sin"))) for a, b in wide),
        "stat_root": count(lambda: __import__("mdi.collective_jt", fromlist=["x"])._exp_pair(Fr(1, 3), ctx)),
        "stat_root_checker": count(lambda: PC._own_exp_pair(Fr(1, 3), ctx)),
    })
    return _PRIM


def dry_run_sparse(tabs, card, real, order, stat_insert=None, rank=1,
                   support_cap=None, entry_cap=None, only=None, deadline=None,
                   charge=None):
    """Run the PRODUCER's sparse engine on the loaded program's tables with the
    cost-metering algebra: the same control flow (product order, messages,
    readout) with every real primitive charged and every statistic support
    carried as an exact key set. Returns (ops, peak_live, largest, supports)."""
    from mdi import sparse_jt as SJ
    meter = SJ.CostMeter(real, rank=rank, support_cap=support_cap)
    lifted = []
    for t in tabs:
        if isinstance(t, SJ.Lazy):
            # a compact factor's support is unknown without evaluating it:
            # the dry run treats every entry as nonzero (an upper bound)
            lifted.append(SJ.Lazy(t.scope, t.card, lambda key, m=meter: m.one()))
        else:
            lifted.append(SJ.Table(t.scope, {k: meter.one() for k in t.entries}))
    jt = SJ.SparseJT(lifted, card, meter, entry_cap=entry_cap, order=order,
                     deadline=deadline, charge=charge).run(stat_insert=stat_insert)
    for v in (sorted(only) if only is not None else jt.free):
        jt.marginal(v)
    sizes = {}
    for key, m in jt.msg.items():
        sizes[key] = sum(meter.size(x) for x in m.entries.values())
    return meter.ops, jt.peak_live_entries, jt.largest_bag, sizes, jt


def dry_run_dense(tables, card, real, stat_insert=None, rank=1, support_cap=None,
                  entry_cap=None, only=None, deadline=None, charge=None, readouts=None):
    """The CHECKER's dense engine on the same tables with the metering algebra.
    `readouts` lists the owner read per REQUESTED variable (owners repeat: the
    checker's own event-count readout sums the home belief once per requested
    variable), so the visited-entry count matches the checker's control flow."""
    from mdi import sparse_jt as SJ, dense_be as DB, factors as FX
    meter = SJ.CostMeter(real, rank=rank, support_cap=support_cap)
    lifted = []
    for sc, tab in tables:
        if hasattr(tab, "at_digits"):
            lifted.append((sc, FX.LazyTable(tab.card, tab.offsets, tab.base,
                                            lift=lambda x, m=meter: m.one())))
        else:
            lifted.append((sc, [meter.one() if not _is_zero_entry(x) else meter_zero(meter)
                                for x in tab]))
    jt = DB.DenseJT(lifted, card, meter, entry_cap=entry_cap, stat_insert=stat_insert,
                    deadline=deadline, charge=charge)
    meter.zero = frozenset() if real == "statistic" else False
    jt.run()
    for v in (list(readouts) if readouts is not None
              else (sorted(only) if only is not None else jt.plan.free)):
        jt.marginal(v)
    return meter.ops, jt.peak_live_entries, jt.plan.largest_bag_entries, jt


def _is_zero_entry(x):
    if isinstance(x, tuple):
        return all(q == 0 for q in x)
    if isinstance(x, dict):
        return not x
    return x == 0


def meter_zero(meter):
    return frozenset() if meter.real == "statistic" else False


def _dense_tables_for_meter(final_marked, card, meter_one):
    """The final law as dense-engine tables whose nonzero entries are the
    meter's `one` (support only; values are irrelevant to a dry run)."""
    from mdi import factors as FX
    zero_like = frozenset() if isinstance(meter_one, frozenset) else False
    out = []
    for f in final_marked.law_factors():
        if FX.is_view(f):
            out.append((tuple(f.scope), FX.LazyTable(f.card, [f.offsets[v] for v in f.scope],
                                                    f.base.table,
                                                    lift=lambda x, o=meter_one: o)))
        else:
            out.append((tuple(f.scope), [meter_one if Fr(x) != 0 else zero_like
                                         for x in f.table]))
    touched = {v for f in final_marked.factors for v in f.scope}
    for v in final_marked.free():
        if v not in touched and not any(x != 1 for x in final_marked.mass[v]):
            out.append(((v,), [meter_one] * card[v]))
    return out


def price_program(name, kind, final_marked, scales, coll, n_requested,
                  construction_ops, fit_ops=None, order=None, deadline=None,
                  budget=None):
    """Price a PROGRAM route from the schedule it will actually run, by DRY
    RUNNING both engines on the loaded program's tables with a metering
    algebra (sparse_jt.CostMeter).

    The producer dry run follows the sparse engine's exact control flow --
    product order, messages in both directions, calibrated readout -- and
    charges every real primitive; statistic supports are carried as exact key
    sets, so joins and readouts are priced on their OCCUPIED supports, not on
    a box. The checker dry run does the same on the dense engine over the
    validated min-fill tree. Everything else the executor and checker do
    (lifting from the record, residual rebuild, per-node enclosures, marker
    accumulation, payload readout, the checker's own enumeration and proofs)
    is added as counted upper bounds.
    """
    from mdi import sparse_jt as SJ, plan as PP, model as MM, collective as CO
    from mdi import factors as FX, dense_be as DB
    rec = CostRecord(kind=kind, name=name)
    card = dict(final_marked.card)
    law = final_marked.law_factors()
    touched = {v for f in final_marked.factors for v in f.scope}
    tabs = [SJ.lazy_from_factor(f) if FX.is_view(f) else SJ.table_from_factor(f)
            for f in law]
    for v in final_marked.free():
        if v not in touched and not any(x != 1 for x in final_marked.mass[v]):
            tabs.append(SJ.Table((v,), {(c,): Fr(1) for c in range(card[v])}))

    def dom(vs):
        n = 1
        for v in vs:
            n *= card[v]
        return n
    # ---- algebra, lattice nodes, statistic insertion
    real = "rational"
    stat_insert = None
    rank = 1
    nodes = 1
    per_node_extra = 0
    trans = 0                   # transcendental (MPFR) evaluations, counted separately
    n_cells = sum(card[final_marked.owner[v]] * final_marked.orig_card[v]
                  for v in final_marked.queries())
    n_states = sum(card[v] for v in final_marked.free())
    if coll is not None:
        cand = coll["candidate"]
        rank = cand.rank
        if coll["evaluator"] == "statistic":
            real = "statistic"
            kq = CO.round_features(cand, final_marked.free(), coll["Q"])
            if rank == 1:
                stat_insert = {v: [kq[0][v][a] for a in range(card[v])]
                               for v in final_marked.free()}
            else:
                stat_insert = {v: [tuple(kq[k][v][a] for k in range(rank))
                                   for a in range(card[v])] for v in final_marked.free()}
            tot_sup = _stat_span(kq, rank, final_marked.free(), card,
                                 K.CAPS["local_mass_entries"])
            rec.put("statistic_support_bound", tot_sup, UPPER,
                    "min(span of the rounded total statistic, product of "
                    "distinct per-variable rounded values, cap); the dry run "
                    "below carries the EXACT occupied supports")
        else:
            # Gaussian / Fourier / mixed: the FULL positive marker-mass pass
            # (interval algebra, one contraction per positive node) and, per
            # positive node, one complex contraction per conjugate pair of
            # negative nodes. Node counts from the record's lattices.
            # node counts from the ACTUAL loaded grids (Chapter 05 GF1/GF2);
            # the grid-construction work (exact integer comparisons and the
            # finite point set) is counted too
            grids = coll.get("grids") or []
            if len(grids) != cand.rank:
                raise ValueError("a quadrature record needs one GF grid per mode")
            pos_nodes = neg_nodes = 1
            grid_ops = 0
            for k in range(cand.rank):
                g = grids[k]
                if cand.signs[k] > 0:
                    pos_nodes *= int(g["nodes"])
                else:
                    neg_nodes *= int(g["nodes"])
                grid_ops += int(g["t"]) + int(g["m"]) + int(g["T"]) + int(g["b"]) + int(g["nodes"])
            rec.put("grid_construction_ops", grid_ops, EXACT,
                    "GF1/GF2 integer comparisons plus the finite point sets")
            has_neg = any(sg < 0 for sg in cand.signs)
            neg_pairs = (neg_nodes + 1) // 2 if has_neg else 0
            rec.put("positive_grid_nodes", pos_nodes, EXACT)
            rec.put("negative_conjugate_pairs_per_positive_node", neg_pairs, EXACT)
            real = "complex" if has_neg else "interval"
            # the interval pass runs at EVERY positive node; the complex pass
            # at every (positive node, conjugate pair)
            nodes = pos_nodes * neg_pairs if has_neg else pos_nodes
            rec.put("quadrature_nodes", nodes, EXACT,
                    "positive nodes times conjugate pairs (complex contractions)"
                    if has_neg else "positive nodes (interval contractions)")
            cm, ca = ALGEBRA_COST[real]
            n_pos = sum(1 for sg in cand.signs if sg > 0)
            n_neg = sum(1 for sg in cand.signs if sg < 0)
            # Per node, counted from gf_evaluate's code paths:
            #  * normal weight: 8 Fraction ops per mode;
            #  * positive tilt per variable state per positive mode: the
            #    exp-enclosure argument products (4) and the running product
            #    (2) -> 6;
            #  * phase per variable state per negative mode: angle (5),
            #    _cos_enclose (24 at zero width + 2 per critical index, at
            #    most 3 indices for the sqrt-enclosure widths that occur -> 30,
            #    bounded by 48), _sin_enclose (72 + 8 per index -> 96, bounded
            #    by 128), tilt x phase rectangle (8) -> 189, bounded by 200;
            #  * per owner cell per state: up to two algebra multiplies, one
            #    add, the payload division, two weight scalings (8), the
            #    delta clipping (6) and two accumulations -> 2cm + ca + 17.
            # the phase enclosures are computed once per NEGATIVE node and
            # reused across positive nodes; per pair only the tilt x phase
            # rectangle (8 per state) remains
            phase = 6 * n_pos + 8 * n_neg
            per_node_extra = (8 * cand.rank + n_states * phase + 16
                              + n_cells * (2 * cm + ca + 17))
            if has_neg:
                phase_once = neg_pairs * (8 * n_neg + n_states * 200 * n_neg)
                per_node_extra += (phase_once + nodes - 1) // max(1, nodes)
            trans = nodes * (2 * cand.rank + n_states * 2 * n_pos) + \
                (neg_pairs * n_states * 4 * n_neg if has_neg else 0)
            # transcendental forecasts PER ENGINE from the probed per-primitive
            # call counts (weights per node, tilts per state per positive mode,
            # phases per state per negative mode, sqrt per mode)
            pr = primitive_call_counts()
            trans_p = (pos_nodes * (n_pos * pr["p_weight"] + n_states * n_pos * pr["p_tilt"])
                       + (neg_pairs * (n_neg * pr["p_weight"] + n_states * n_neg * pr["p_phase"]) if has_neg else 0)
                       + cand.rank * pr["p_sqrt"])
            trans_c = (pos_nodes * (n_pos * pr["c_weight"] + n_states * n_pos * pr["c_tilt"])
                       + (neg_pairs * (n_neg * pr["c_weight"] + n_states * n_neg * pr["c_phase"]) if has_neg else 0)
                       + cand.rank * pr["c_sqrt"] + 64)
            trans = max(trans_p, trans_c)
            rec.put("transcendental_producer_forecast", trans_p, FORECAST,
                    "MPFR calls of the producer's enclosures (probed per-primitive counts)")
            rec.put("transcendental_checker_forecast", trans_c, FORECAST,
                    "MPFR calls of the checker's own enclosures (probed per-primitive counts)")
            retained = pos_nodes * (2 + 2 * n_states + 2 * n_cells + 2)
            phases = (neg_pairs * (2 + 4 * n_states)) if has_neg else 0
            rec.put("retained_positive_node_entries", retained, EXACT,
                    "weights, tilt rows, event masses and totals kept per positive node")
            rec.put("precomputed_phase_entries", phases, EXACT,
                    "negative-node weights and per-state phase rectangles kept across positive nodes")
            rec.put("event_staging_entries", nodes * n_states * (4 if has_neg else 2), UPPER,
                    "per-node unary tilt / tilt x phase tables staged for the contraction")
    # ---- the two dry runs, on the SAVED order when one is given; guarded by
    # the shared deadline and by a PER-CANDIDATE meter with the same entry cap
    # the program itself must respect (a probe that exceeds it proves the
    # program unaffordable and refuses the candidate, without consuming the
    # plan's execution meter for every other candidate). The probe's work is
    # then charged to the shared `pricing_entries` counter (complete cost).
    probe_used = {"n": 0}
    # the per-candidate probe bound is PHYSICAL and DETERMINISTIC (AMENDMENTS[0]): a
    # program must be PRICED inside the frozen construction allowance
    # (CAPS["discovery_wall_s"], 30 s), so its dry run may visit at most the entries
    # that allowance buys at the calibrated scalar rate (capacity.entries_affordable:
    # 666,666). A candidate whose probe exceeds that cannot be priced within its
    # allowance and is refused, typed; discovery continues to the next candidate.
    # The bound is the same whenever the price is derived (discovery, binding,
    # replay). The program's EXECUTION affordability against the remaining wall is
    # decided at binding by `pipeline.loaded_admission`.
    from mdi import capacity as CAP
    _probe_wall = float(K.CAPS["discovery_wall_s"])
    cap_entries = CAP.entries_affordable(_probe_wall, "scalar_sparse")

    def charge(n):
        probe_used["n"] += n
        if probe_used["n"] > cap_entries:
            raise SJ.SparseError("the pricing probe for this candidate reached %d metered entries, above the "
                                 "%d entries the frozen %.0f s construction allowance buys at the calibrated scalar "
                                 "rate: the program cannot be priced within its allowance and is refused"
                                 % (probe_used["n"], cap_entries, _probe_wall))
        if budget is not None:
            budget.charge("pricing_entries", n, "pricing probe")
    if coll is not None and coll["evaluator"] != "statistic":
        # one per-variable tilt (positive) / tilt x phase (negative) unary
        # table joins the law at every lattice node in both engines
        tabs = tabs + [SJ.Table((v,), {(c,): Fr(1) for c in range(card[v])})
                       for v in final_marked.free()]
        _node_unaries = [((v,), [True] * card[v]) for v in final_marked.free()]
    else:
        _node_unaries = []
    probe_exact = True
    if real == "statistic":
        # inexpensive bound first: probe exact supports only when the span
        # bound is small enough for the probe itself to be cheap
        if int(rec.counters["statistic_support_bound"].value) > 4096:
            probe_exact = False
    try:
        owners = set(final_marked.owner.values())
        readouts = [final_marked.owner[v] for v in final_marked.queries()]
        if probe_exact:
            p_ops, p_live, p_largest, p_sizes, sjt = dry_run_sparse(
                tabs, card, real, order, stat_insert=stat_insert, rank=rank,
                support_cap=K.CAPS["local_mass_entries"],
                entry_cap=K.CAPS["local_mass_entries"], only=owners,
                deadline=deadline, charge=charge)
        else:
            # bound-only pricing: run the rational dry run (entries) and scale
            # every primitive by the support bound (an UPPER bound)
            p_ops, p_live, p_largest, p_sizes, sjt = dry_run_sparse(
                tabs, card, "rational", order, only=owners, deadline=deadline,
                charge=charge)
            sb = int(rec.counters["statistic_support_bound"].value)
            p_ops *= 2 * sb * sb
            p_live *= sb
            rec.put("support_probe", 0, EXACT, "exact support probe skipped: the "
                    "span bound %d exceeds the probe threshold; the price scales "
                    "every primitive by the bound" % sb)
        order = list(sjt.order)
        nroots = len(sjt.roots)
    except (SJ.SparseError, DB.DenseError) as e:
        rec.put("producer_upward_ops", None, UNKNOWN, "schedule refused: %s" % e)
        rec.put("pricing_probe_entries", probe_used["n"], CALIB,
                "metered entries visited by the failed probe (charged)")
        rec.eligible = False
        rec.ineligible_reason = ("the producer's schedule exceeds a declared cap "
                                 "on this program: %s" % e)
        has_zero = any((not FX.is_view(f)) and any(Fr(x) == 0 for x in f.table) for f in law)
        rec.feasibility["producer"] = ("PRODUCER_FEASIBILITY_UNKNOWN" if has_zero else "PRODUCER_CAP_PROVED")
        rec.feasibility["producer_reason"] = str(e)[:160]
        rec.feasibility["checker"] = "NOT_EVALUATED"
        return rec, None
    extra_pos = 0
    extra_pos_c = 0
    ent_sparse = int(sjt.ops.get("entries_built", 0))
    ent_pos_sparse = ent_pos_dense = 0
    if coll is not None and real == "complex":
        # the positive marker-mass pass in the INTERVAL algebra, once per
        # positive node, on both engines
        try:
            pi_ops, _l, _lg, _sz, _j = dry_run_sparse(
                tabs, card, "interval", order, entry_cap=K.CAPS["local_mass_entries"],
                only=set(final_marked.owner.values()), deadline=deadline, charge=charge)
            extra_pos = pi_ops * pos_nodes + pos_nodes * (8 + n_states * 4 + n_cells * 6)
            ent_pos_sparse = int(_j.ops.get("entries_built", 0))
            ci_ops, _l2, _lg2, _j2 = dry_run_dense(
                _dense_tables_for_meter(final_marked, card, True) + _node_unaries, card, "interval",
                entry_cap=K.CAPS["local_mass_entries"],
                only=set(final_marked.owner.values()), deadline=deadline, charge=charge,
                readouts=[final_marked.owner[v] for v in final_marked.queries()])
            extra_pos_c = ci_ops * pos_nodes + pos_nodes * (8 + n_states * 4 + n_cells * 6)
            ent_pos_dense = int(_j2._visited)
        except Exception as e:
            rec.put("positive_pass_note", 0, EXACT, "interval dry run refused: %s" % e)
    meter_one = frozenset([(0,) * rank if rank > 1 else 0]) if real == "statistic" else True
    try:
        if probe_exact:
            c_ops, c_live, c_largest, djt = dry_run_dense(
                _dense_tables_for_meter(final_marked, card, meter_one)
                + ([((v,), [meter_one] * card[v]) for v in final_marked.free()]
                   if _node_unaries else []), card, real,
                stat_insert=stat_insert, rank=rank,
                support_cap=K.CAPS["local_mass_entries"],
                entry_cap=K.CAPS["local_mass_entries"], only=owners,
                deadline=deadline, charge=charge, readouts=readouts)
        else:
            c_ops, c_live, c_largest, djt = dry_run_dense(
                _dense_tables_for_meter(final_marked, card, True), card, "rational",
                only=owners, deadline=deadline, charge=charge, readouts=readouts)
            sb = int(rec.counters["statistic_support_bound"].value)
            c_ops *= 2 * sb * sb
            c_live *= sb
        ent_dense = int(djt._visited)
    except Exception as e:
        c_ops = None
        c_live = c_largest = 0
        ent_dense = None
        rec.put("checker_schedule_note", 0, EXACT, "dense schedule refused: %s" % e)
        # FEASIBILITY at the checking standard: the dense dry run shaped every
        # table as FULLY supported. If the law has no hard zero, that shape IS
        # the checker's table and the cap excess is PROVED; with hard zeros the
        # sparse occupancy is unknown and the refusal is a bound, not a proof
        has_zero = any((not FX.is_view(f)) and any(Fr(x) == 0 for x in f.table) for f in law)
        rec.feasibility["checker"] = ("CHECKER_FEASIBILITY_UNKNOWN" if has_zero else "CHECKER_CAP_PROVED")
        rec.feasibility["checker_reason"] = str(e)[:160]
    rec.put("pricing_probe_entries", probe_used["n"], CALIB,
            "metered entries visited by this candidate's pricing probes (charged "
            "to the shared pricing counter, not the execution meter)")
    # ---- the executor's OTHER work
    lift = 0
    maps = 0
    for sc in scales:
        ncell = [len(cr.cells) for cr in sc.coarse]
        for pc in sc.projected:
            # composing offset maps: one add per state per scope variable
            maps += sum(len(o) for o in pc.offsets.values()) if hasattr(pc, "offsets") else 0
            lift += 2 * (sum(len(o) for o in pc.offsets.values()) if hasattr(pc, "offsets") else 0)
        for cr in sc.coarse:
            lift += 2 * len(cr.cells) * (len(cr.N) + 1)
            lift += 4 * len(cr.cells) * max(1, len(cr.N))
    readout = 0
    for v in final_marked.queries():
        o = final_marked.owner[v]
        readout += 8 * card[o] * final_marked.orig_card[v] + 6 * final_marked.orig_card[v]
    fit = 0
    if coll is not None:
        n_pairs = sum(1 for f in law if len(f.scope) == 2)
        n_coupled = max(n_pairs, len(card) * (len(card) - 1) // 2)
        cmax = max(card.values()) if card else 1
        fit = 64 * n_coupled * cmax * cmax + 48 * sum(card.values())
        if real == "statistic":
            # root integration of the total and of every owner cell per state,
            # 2 ops per support point; with several components each cell
            # distribution is convolved with the others' totals first
            tot_sup = int(rec.counters["statistic_support_bound"].value)
            conv_others = (2 * tot_sup * tot_sup) if nroots > 1 else 0
            # EVERY exact-rational operation of the statistic readout is
            # priced by name: key construction (rank products per support
            # point per cell), the root-weight pairs and their accumulation,
            # the convolution with the other components, the restoration of
            # the original-variable payload (ratio, sign, clamp) and the
            # comparisons of the enclosure endpoints
            keys = 2 * rank * tot_sup * (1 + n_cells)
            restore = 6 * tot_sup * (1 + n_cells) + 4 * tot_sup
            per_node_extra = (2 * tot_sup * (1 + n_cells) + 4 * n_cells
                              + n_cells * conv_others + 3 * nroots * conv_others
                              + keys + restore)
            rec.put("statistic_key_ops", keys, UPPER, "statistic key construction per support point and cell")
            rec.put("statistic_restoration_ops", restore, UPPER,
                    "root-weight accumulation, payload restoration and endpoint comparisons")
            pr = primitive_call_counts()
            trans_p = tot_sup * (1 + n_cells) * pr["stat_root"]
            trans_c = tot_sup * (1 + n_cells) * pr["stat_root_checker"]
            trans = max(trans_p, trans_c)
            rec.put("transcendental_producer_forecast", trans_p, FORECAST,
                    "root exponential per support point (producer)")
            rec.put("transcendental_checker_forecast", trans_c, FORECAST,
                    "root exponential per support point (checker)")
    # quadratic-energy construction (the rounding bound per Q attempt), root
    # integration, normalization (the sharp ratio per state) and structural
    # map composition are priced explicitly
    energy = 0
    if coll is not None and real == "statistic":
        # the rounding bound is evaluated once per dyadic rung up to the saved
        # Q (derivable from the record: bit_length(Q) rungs)
        energy = 4 * sum(card.values()) * rank * max(1, int(coll["Q"]).bit_length())
    norm = 8 * sum(final_marked.orig_card[v] for v in final_marked.queries())
    rec.put("energy_bound_ops", energy, UPPER, "rounding-energy bound per Q attempt")
    rec.put("normalization_ops", norm, UPPER, "sharp marker ratio per requested state")
    rec.put("structural_map_ops", maps, EXACT, "offset-map composition entries across scales")
    rec.put("producer_schedule_ops", p_ops, UPPER,
            "dry run of the sparse engine on the loaded program with the "
            "metering algebra: both passes and the calibrated readout, exact "
            "occupied statistic supports")
    rec.put("producer_upward_ops", p_ops * nodes + extra_pos + lift + fit, UPPER,
            "schedule dry run times the lattice node count (plus the positive "
            "marker-mass pass for Fourier/mixed), plus lifting from the record "
            "and the residual certificate")
    rec.put("producer_downward_ops", 0, EXACT,
            "both passes are inside producer_schedule_ops")
    rec.put("readout_ops", per_node_extra * nodes + readout + norm + energy, UPPER,
            "per-node enclosures, marker accumulation and integration, the "
            "original-variable payload readout, normalization and the energy "
            "bound")
    rec.put("transcendental_evaluations", trans, FORECAST,
            "MPFR exp/log/trig/sqrt/pi evaluations per engine, from measured "
            "per-primitive call counts; NOT a Fraction count and not summed into "
            "total_arithmetic; each engine REPORTS its measured count")
    if fit_ops is not None:
        rec.put("mode_fit_ops", int(fit_ops), FORECAST,
                "mode recognition during discovery (paid once, recorded)")
    # ---- the checker
    if c_ops is None:
        rec.put("checker_ops", None, UNKNOWN, "no dense schedule")
        if rec.eligible:
            rec.eligible = False
            rec.ineligible_reason = ("the independent checker's schedule is not feasible at the "
                                     "promised checking standard (%s): an interval-only or "
                                     "unchecked route cannot win a fully checked comparison"
                                     % rec.feasibility.get("checker"))
    else:
        chk_local = 0
        for sc in scales:
            for ri, (rd, cr) in enumerate(zip(sc.rds, sc.coarse)):
                joint = 1
                for v in rd.vars:
                    joint *= _card_of(sc, v)
                nfac = len(rd.internal_factors) + 1
                chk_local += joint * (nfac + 1 + 2 * len(rd.marks))
                # the checker enumerates EVERY supported boundary state, the
                # deleted ones included (it re-proves the deletion from them)
                dl = sc.deletions[ri] if ri < len(sc.deletions) else None
                n_bd = len(rd.A) + (len(dl.deleted) if dl else 0)
                chk_local += n_bd * (4 + 2 * len(rd.crossing_factors)) * 2
                chk_local += sum(len(c.members) for c in cr.cells) * 8
                chk_local += len(cr.cells) * (2 + 2 * len(cr.N))
            chk_local += len(sc.regions) * K.CAPS["aggregated_kernel_entries"]
            chk_local += 2 * maps
        chk_fit = 2 * fit if coll is not None else 0
        rec.put("checker_schedule_ops", c_ops, UPPER,
                "dry run of the dense engine on the validated min-fill tree")
        rec.put("checker_ops",
                c_ops * nodes + extra_pos_c + per_node_extra * nodes + chk_local
                + chk_fit + readout + norm + energy,
                UPPER,
                "dense dry run times nodes, plus the checker's own region "
                "enumeration, witness proof, deletion bounds, lifted maps, fit "
                "certificate and payload readout")
    # ---- the SHARED entry meter the program will actually run under: every
    # entry either engine visits is charged to local_mass_entries (producer
    # and checker share one cumulative cap for the whole plan), so a program
    # whose forecast visits exceed the cap cannot complete and is refused by
    # price BEFORE it is executed -- a real resource stop is never passed off
    # as completion, and the executor never starts work the price knows it
    # cannot finish. The forecast is an UPPER bound: engines charge in blocks
    # of 64 visited entries, the forecast counts every entry.
    lift_entries = 0
    for sc in scales:
        lift_entries += sum(max(1, len(cr.cells)) for cr in sc.coarse)
        for pc in sc.projected:
            lift_entries += sum(len(o) for o in pc.offsets.values()) if hasattr(pc, "offsets") else 0
    chk_struct = 0
    for sc in scales:
        for ri, rd in enumerate(sc.rds):
            dl = sc.deletions[ri] if ri < len(sc.deletions) else None
            chk_struct += max(1, len(rd.A) + (len(dl.deleted) if dl else 0))
        # the checker's own profile product per crossing group is charged by
        # its kernel size, which the checker refuses above the kernel cap
        for cr in sc.coarse:
            chk_struct += len(cr.aggregation or []) * K.CAPS["aggregated_kernel_entries"]
    p_entries = lift_entries + ent_sparse * nodes + ent_pos_sparse * (pos_nodes if real == "complex" else 0)
    if real == "complex":
        p_entries += neg_nodes          # the conjugate key set, checked once, linear and charged
    rec.put("producer_metered_entries", p_entries, UPPER,
            "entries the producer's engine visits (dry run times nodes, plus the "
            "positive pass and lifting), each charged to the shared meter")
    if ent_dense is None:
        rec.put("checker_metered_entries", None, UNKNOWN, "no dense schedule")
        rec.put("metered_entries_forecast", None, UNKNOWN, "no dense schedule")
    else:
        c_entries = chk_struct + ent_dense * nodes + ent_pos_dense * (pos_nodes if real == "complex" else 0)
        rec.put("checker_metered_entries", c_entries, UPPER,
                "entries the checker's dense engine visits (dry run times nodes, plus "
                "the positive pass and its own region masses), charged to the SAME meter")
        rec.put("metered_entries_forecast", p_entries + c_entries, UPPER,
                "producer + checker visits against the cumulative local_mass_entries cap")
        if p_entries + c_entries > K.CAPS["local_mass_entries"] and rec.eligible:
            rec.eligible = False
            rec.ineligible_reason = (
                "the forecast metered entry visits %d (producer %d + checker %d) "
                "exceed the shared local_mass_entries cap %d: the program would "
                "stop on the budget it runs under, so it is refused by price"
                % (p_entries + c_entries, p_entries, c_entries,
                   K.CAPS["local_mass_entries"]))
    if construction_ops is None:
        rec.put("construction_ops", None, UNKNOWN, "local construction was not measured")
    else:
        rec.put("construction_ops", int(construction_ops), CALIB,
                "measured exact-rational arithmetic in local mass, marker and "
                "profile construction across every scale")
    rec.put("requested_markers", n_requested, EXACT)
    rec.put("final_variables", len(card), EXACT)
    rec.put("final_largest_bag", p_largest, EXACT)
    rec.put("regions", sum(len(sc.regions) for sc in scales), EXACT)
    rec.put("cells", sum(len(cr.cells) for sc in scales for cr in sc.coarse), EXACT)
    rec.put("levels", len(scales), EXACT)
    rec.put("radius_charged", sum((Fr(sc.t_level) + Fr(sc.deletion_radius_total)
                                   for sc in scales), Fr(0))
            + (Fr(coll["fit_tv"]) + Fr(coll["rounding_tv"]) + Fr(coll["quadrature_tv"])
               if coll else Fr(0)), EXACT)
    # ---- liveness: messages (with statistic supports) + the largest working
    # table + the inputs (dense tables, offset maps, marker payloads)
    width = {"rational": 1, "interval": 2, "complex": 4, "statistic": 1}[real]
    inputs = sum((len(f.table) if not FX.is_view(f) else f.map_entries()) for f in law)
    markers = sum(len(col) for col in final_marked.marks.values()) + \
        sum(len(final_marked.mass[v]) for v in final_marked.free())
    rec.put("peak_live_message_entries", p_live, UPPER,
            "sparse dry run: peak simultaneously live message entries, "
            "statistic supports counted per entry")
    rec.put("input_entries_retained", inputs + markers, EXACT,
            "dense input tables plus offset maps plus marker payloads")
    extra_live = 0
    if coll is not None and coll["evaluator"] != "statistic":
        extra_live = int(rec.counters["retained_positive_node_entries"].value) + \
            int(rec.counters["precomputed_phase_entries"].value)
    rec.bytes_producer = Counter((p_live + p_largest) * width * 64 + (inputs + markers) * 64
                                 + extra_live * 2 * 64,
                                 FORECAST,
                                 "peak live messages plus one largest working table, "
                                 "times the algebra width, plus retained inputs; "
                                 "ENTRY COUNTS at 64 bytes each, excludes object "
                                 "overhead; NOT measured whole-process memory")
    rec.bytes_checker = Counter((c_live + 2 * c_largest) * width * 64 + (inputs + markers) * 64
                                + extra_live * 2 * 64,
                                FORECAST, "dense dry run liveness plus retained inputs plus the "
                                          "retained node data and precomputed phases")
    _comparison_bound(rec)
    return rec, order


def _card_of(sc, v):
    """Cardinality of input variable v of a scale."""
    return int(sc.input_card.get(v, 2))
