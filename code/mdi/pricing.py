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
                                "grid_ops", "mode_fit_ops")
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
                "above the declared enumeration cap")
        # ABOVE the enumeration cap the checker runs the STRUCTURAL second
        # implementation (sparse exact junction tree) when its bags fit the
        # declared contraction-space cap. Forecast that applicability BEFORE
        # execution, so a run whose complete status cannot be claimed is
        # known to be shared-aggregation-only up front.
        fits = plan.largest_bag_entries <= K.CAPS["checker_contraction_space"]
        rec.put("independent_aggregation_forecast", 1 if fits else 0, FORECAST,
                ("the sparse exact junction tree fits the %d-entry cap, so the "
                 "independent aggregation check is expected to run"
                 if fits else
                 "the largest bag %d exceeds the %d-entry checker cap, so the "
                 "independent aggregation check will NOT run and the complete "
                 "certified status will not be claimed")
                % ((K.CAPS["checker_contraction_space"],) if fits
                   else (plan.largest_bag_entries, K.CAPS["checker_contraction_space"])))
        if fits:
            # sparse elimination: one multiply and one add per bag entry per
            # table, over the same bag tree
            sj = sum(2 * b.domain(plan.card) * (len(b.factors) + len(b.children) + 2)
                     for b in plan.bags)
            rec.put("independent_sparse_ops", sj, UPPER,
                    "sparse exact junction tree over the bag domains")
            chk += sj
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


def _schedule_cost(bags, card, alg, stat=None):
    """Weighted Fraction-operation bound of both passes and the readout over a
    bag tree. `bags` is a list of dicts {vars, elim, children, own, home}.

    For the statistic algebra the cost of a product is 2*|a|*|b| and of an add
    |b|, with |.| the support bound of the operand: own tables carry delta
    distributions (support 1) and a child's message carries the statistic of
    the variables eliminated in its subtree.
    """
    def dom(vs):
        n = 1
        for v in vs:
            n *= card[v]
        return n
    idx = {b["idx"]: b for b in bags}
    sub = {}

    def subtree_elim(bi):
        if bi in sub:
            return sub[bi]
        out = {idx[bi]["elim"]}
        for c in idx[bi]["children"]:
            out |= subtree_elim(c)
        sub[bi] = out
        return out
    if stat is None:
        cm, ca = ALGEBRA_COST[alg]

        def prod_cost(d, n_tables, incoming):
            return d * n_tables * cm

        def sum_cost(d, support):
            return d * ca
        sup_of = lambda bi: 1
    else:
        kq, rank, cap = stat

        def sup_of(bi):
            return _stat_span(kq, rank, subtree_elim(bi), card, cap)

        def prod_cost(d, n_tables, incoming):
            # own delta tables first (2 ops each), then the children in turn
            # with the running support growing to the union span
            cost = 2 * d * max(0, n_tables - len(incoming))
            run = 1
            run_vars = set()
            for c in incoming:
                s_c = sup_of(c)
                cost += 2 * d * run * s_c
                run_vars |= subtree_elim(c)
                run = _stat_span(kq, rank, run_vars, card, cap)
            return cost, run

        def sum_cost(d, support):
            return d * support
    up = down = ro = 0
    for b in bags:
        d = dom(b["vars"])
        own = b["own"]
        kids = list(b["children"])
        npar = 1 if b["parent"] >= 0 else 0
        if stat is None:
            up += prod_cost(d, own + len(kids), kids) + sum_cost(d, 1)
            for c in kids:
                down += prod_cost(d, own + npar + len(kids) - 1, []) + sum_cost(d, 1)
            ro += b["home"] * (prod_cost(d, own + len(kids) + npar, []) + sum_cost(d, 1))
        else:
            c, run = prod_cost(d, own + len(kids), kids)
            up += c + sum_cost(d, run) + d * run          # + the shift
            for ch in kids:
                others = [x for x in kids if x != ch]
                c2, run2 = prod_cost(d, own + npar + len(others), others)
                # the parent message carries everything outside this subtree
                c2 += 2 * d * run2 * sup_of(b["idx"]) if npar else 0
                down += c2 + sum_cost(d, run2) + d * run2
            c3, run3 = prod_cost(d, own + len(kids), kids)
            ro += b["home"] * (c3 + sum_cost(d, run3) + d * run3 + 2 * run3 * d)
    return up, down, ro


def price_program(name, kind, final_marked, scales, coll, n_requested,
                  construction_ops, fit_ops=None):
    """Price a PROGRAM route from the schedule it will actually run.

    The producer contracts the final marked model with the sparse junction
    tree along the order it persists; the checker contracts the same model
    with its dense engine on the validated min-fill tree, re-enumerates every
    region and re-proves every profile and the fit certificate. Both are
    priced from bag domains, which bound the sparse run from above (a sparse
    table never has more entries than its domain), weighted by each algebra's
    primitive cost. Collective evaluators multiply the per-node work by the
    lattice node count (quadrature) or carry per-subtree statistic supports
    (statistic DP).
    """
    from mdi import sparse_jt as SJ, plan as PP, model as MM, collective as CO
    rec = CostRecord(kind=kind, name=name)
    card = dict(final_marked.card)
    law = final_marked.law_factors()
    touched = {v for f in final_marked.factors for v in f.scope}
    tabs = [SJ.table_from_factor(f) for f in law]
    for v in final_marked.free():
        if v not in touched and not any(x != 1 for x in final_marked.mass[v]):
            tabs.append(SJ.Table((v,), {(c,): Fr(1) for c in range(card[v])}))
    try:
        jt = SJ.SparseJT(tabs, card, SJ.Rational)
    except SJ.SparseError as e:
        rec.put("producer_upward_ops", None, UNKNOWN, "schedule refused: %s" % e)
        rec.eligible = False
        rec.ineligible_reason = "the final model admits no elimination schedule: %s" % e
        return rec, None

    def dom(vs):
        n = 1
        for v in vs:
            n *= card[v]
        return n
    nq = len(final_marked.queries())
    # ---- the two bag trees, as uniform dicts
    sp_bags = []
    for b in jt.bags:
        sp_bags.append({"idx": b["idx"], "vars": b["vars"], "elim": b["elim"],
                        "children": list(b["children"]), "parent": b["parent"],
                        "own": len(b["tables"]),
                        "home": sum(1 for v, h in jt.home.items() if h == b["idx"])})
    largest = max((dom(b["vars"]) for b in sp_bags), default=1)
    sum_sep = sum(dom(b["sep"]) for b in jt.bags)
    shells = [MM.Factor(scope=tuple(t.scope), card=tuple(card[v] for v in t.scope),
                        table=[Fr(1)] * dom(t.scope), origin=i)
              for i, t in enumerate(tabs)]
    adj = PP.primal_graph(sorted(card), card, shells)
    try:
        dpl = PP.build_plan("min_fill", PP.order_min_fill(sorted(card), card, adj),
                            sorted(card), card, shells)
        dn_bags = []
        for b in dpl.bags:
            dn_bags.append({"idx": b.idx, "vars": b.vars, "elim": b.eliminated,
                            "children": list(b.children), "parent": b.parent,
                            "own": len(b.factors),
                            "home": sum(1 for v, h in dpl.var_home.items()
                                        if h == b.idx)})
        dense_largest = dpl.largest_bag_entries
    except Exception:
        dn_bags = None
        dense_largest = largest
    # ---- algebra, lattice and per-node overheads
    alg = "rational"
    stat = None
    nodes = 1
    per_node_extra = 0           # tilt/phase enclosures and marker accumulation
    if coll is not None:
        cand = coll["candidate"]
        if coll["evaluator"] == "statistic":
            kq = CO.round_features(cand, final_marked.free(), coll["Q"])
            stat = (kq, cand.rank, K.CAPS["local_mass_entries"])
            tot_sup = _stat_span(kq, cand.rank, final_marked.free(), card,
                                 K.CAPS["local_mass_entries"])
            rec.put("statistic_support_bound", tot_sup, UPPER,
                    "min(span of the rounded total statistic, product of "
                    "distinct per-variable rounded values, cap)")
            # root integration and marker integration: 2 ops per support point
            # per integrated distribution (total + every owner cell per state)
            n_cells = sum(card[final_marked.owner[v]] * final_marked.orig_card[v]
                          for v in final_marked.queries())
            nroots = len(set(jt.component_of(v) for v in card))
            # root integration (2 ops per support point) of the total and of
            # every owner cell per state; with several components each cell
            # distribution is first convolved with the others' totals
            # (prefix/suffix: 3 convolutions per root, each <= 2*sup^2)
            conv_others = (2 * tot_sup * tot_sup) if nroots > 1 else 0
            per_node_extra = (2 * tot_sup * (1 + n_cells) + 4 * n_cells
                              + n_cells * conv_others + 3 * nroots * conv_others)
        else:
            nodes = int(coll.get("nodes") or 0)
            if not nodes:
                Rk = sum((max(abs(Fr(x)) for x in f)
                          for f in cand.features[0].values()), Fr(0))
                lat = (CO.gf_lattice(cand.gammas[0], Rk, coll["delta"])
                       if coll["evaluator"] == "gaussian"
                       else CO.fourier_lattice(cand.gammas[0], Rk, coll["delta"]))
                nodes = lat["nodes"]
            rec.put("quadrature_nodes", nodes, EXACT)
            alg = "interval" if coll["evaluator"] == "gaussian" else "complex"
            n_states = sum(card[v] for v in final_marked.free())
            n_cells = sum(card[final_marked.owner[v]] * final_marked.orig_card[v]
                          for v in final_marked.queries())
            cm, ca = ALGEBRA_COST[alg]
            nroots = len(set(jt.component_of(v) for v in card))
            # per node, counted from the code: the normal weight (8), one
            # tilt enclosure per variable state (interval: 4) or one cos+sin
            # enclosure pair (complex: 24 + 72 at zero width plus 2 per
            # critical index examined, at most 8 for the sqrt-enclosure
            # widths that occur; 128 bounds it), the Z/Im scaling (8), the
            # prefix/suffix products of the component totals (3*nroots
            # multiplies), and per owner cell per state: up to two algebra
            # multiplies (others' totals, payload), one add, the payload
            # division and the weight scaling (4), plus the two accumulations
            phase = 4 if alg == "interval" else 128
            per_node_extra = (8 + n_states * phase + 8 + 3 * nroots * cm
                              + n_cells * (2 * cm + ca + 1 + 4 + 2))
    up, down, ro = _schedule_cost(sp_bags, card, alg, stat)
    # the product of component totals, per node
    _nroots = len(set(jt.component_of(v) for v in card))
    _cm = ALGEBRA_COST.get(alg, (1, 1))[0]
    if stat is not None:
        _cm = 2 * _stat_span(stat[0], stat[1], final_marked.free(), card, stat[2]) ** 2
    up += max(0, _nroots - 1) * _cm
    # ---- the executor's OTHER work: rebuilding the lifted models from the
    # record and the original-variable readout
    lift = 0
    for sc in scales:
        ncell = [len(cr.cells) for cr in sc.coarse]
        for pc in sc.projected:
            n = 1
            for i in pc.regions:
                n *= ncell[i]
            lift += n * (2 * len(pc.scope) + 2)
        for cr in sc.coarse:
            lift += 2 * len(cr.cells) * (len(cr.N) + 1)
            lift += 4 * len(cr.cells) * max(1, len(cr.N))
    readout = 0
    for v in final_marked.queries():
        o = final_marked.owner[v]
        readout += 6 * card[o] * final_marked.orig_card[v] + 4 * final_marked.orig_card[v]
    conv = sum(dom(t.scope) for t in tabs)
    # the residual rebuild (mode fit certificate) runs in the executor too
    fit = 0
    if coll is not None:
        # the residual rebuild and its certificate, counted from the code:
        # per coupled state pair at most 20 (build_residual: mode term,
        # target bounds, grid rounding, error) + 12 (canonicalize, amortized
        # gauge split and log radius) + 24 (fit_certificate: fixed table,
        # interaction part, leftovers) + 8 slack = 64; per variable state at
        # most 48 across the three.
        n_pairs = sum(1 for f in law if len(f.scope) == 2)
        n_coupled = max(n_pairs, len(card) * (len(card) - 1) // 2)
        cmax = max(card.values()) if card else 1
        fit = 64 * n_coupled * cmax * cmax + 48 * sum(card.values())
    rec.put("producer_upward_ops", (up + conv) * nodes + lift + fit, UPPER,
            "per bag: algebra-weighted products and sums over the bag domain, "
            "times the lattice node count; plus table conversion, the "
            "rebuilding of every lifted model and the residual certificate")
    rec.put("producer_downward_ops", down * nodes, UPPER)
    rec.put("readout_ops", ro * nodes + per_node_extra * nodes + readout, UPPER,
            "calibrated readout plus per-node enclosures and marker "
            "accumulation, plus the original-variable payload readout")
    if fit_ops is not None:
        rec.put("mode_fit_ops", int(fit_ops), FORECAST,
                "mode recognition during discovery (paid once, recorded)")
    # ---- the checker
    if dn_bags is None:
        rec.put("checker_ops", None, UNKNOWN, "no dense schedule")
    else:
        cu, cd, cr_ = _schedule_cost(dn_bags, card, alg, stat)
        cu += max(0, _nroots - 1) * _cm
        chk_local = 0
        for sc in scales:
            for rd, cr in zip(sc.rds, sc.coarse):
                joint = 1
                for v in rd.vars:
                    joint *= _card_of(sc, v)
                nfac = len(rd.internal_factors) + 1
                chk_local += joint * (nfac + 1 + 2 * len(rd.marks))
                # own deletion bound, witness partition, alpha/rho per member
                chk_local += len(rd.A) * (4 + 2 * len(rd.crossing_factors)) * 2
                chk_local += sum(len(c.members) for c in cr.cells) * 8
                chk_local += len(cr.cells) * (2 + 2 * len(cr.N))
            chk_local += len(sc.regions) * K.CAPS["aggregated_kernel_entries"]
            ncell = [len(cr.cells) for cr in sc.coarse]
            for pc in sc.projected:
                n = 1
                for i in pc.regions:
                    n *= ncell[i]
                chk_local += n * (len(pc.scope) + 1)
        chk_fit = 2 * fit if coll is not None else 0
        rec.put("checker_ops",
                (cu + cd + cr_ + conv) * nodes + per_node_extra * nodes
                + chk_local + chk_fit + readout, UPPER,
                "dense exact junction tree on the validated min-fill tree with "
                "the same algebra weights, plus the checker's own region "
                "enumeration, witness proof, deletion bounds, lifted tables "
                "and fit certificate")
    if construction_ops is None:
        rec.put("construction_ops", None, UNKNOWN,
                "local construction was not measured")
    else:
        rec.put("construction_ops", int(construction_ops), CALIB,
                "measured exact-rational arithmetic in local mass, marker and "
                "profile construction across every scale")
    rec.put("requested_markers", n_requested, EXACT)
    rec.put("final_variables", len(card), EXACT)
    rec.put("final_largest_bag", largest, EXACT)
    rec.put("regions", sum(len(sc.regions) for sc in scales), EXACT)
    rec.put("cells", sum(len(cr.cells) for sc in scales for cr in sc.coarse), EXACT)
    rec.put("levels", len(scales), EXACT)
    rec.put("radius_charged", sum((Fr(sc.t_level) + Fr(sc.deletion_radius_total)
                                   for sc in scales), Fr(0))
            + (Fr(coll["fit_tv"]) + Fr(coll["rounding_tv"]) + Fr(coll["quadrature_tv"])
               if coll else Fr(0)), EXACT)
    width = {"rational": 1, "interval": 2, "complex": 4}[alg]
    if stat is not None:
        width = _stat_span(stat[0], stat[1], final_marked.free(), card, stat[2])
    rec.bytes_producer = Counter((sum_sep + largest) * 64 * width, FORECAST,
                                 "separator entries plus one largest-bag working "
                                 "table, times the algebra width; ENTRY COUNTS "
                                 "only, excludes object overhead; NOT measured "
                                 "whole-process memory")
    rec.bytes_checker = Counter((dense_largest * 2 + sum_sep) * 64 * width, FORECAST,
                                "dense bag table plus message tables, times the "
                                "algebra width")
    return rec, jt.order


def _card_of(sc, v):
    """Cardinality of input variable v of a scale."""
    return int(sc.input_card.get(v, 2))
