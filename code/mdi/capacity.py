"""Physical capacity policy (2 November 2026): admission describes the schedules that
EXECUTE and is measured against the physical budget -- the invocation's remaining wall
and its process RSS cap -- instead of the two implementation guards it replaces (the
4,096-entry checker bag cap and the 1,000,000-entry cumulative meter), which were not
requirements of the width-1/100 guarantee.

Three engines run the identity route; each is forecast from the ACTUAL schedule it
runs on, at a rate measured on this host for its layout:

  * producer: `vec_engine.VecEngine` mode P on the PRODUCER's saved order;
  * interval checker: `vec_engine.VecEngine` mode I on the CHECKER's own min-fill plan
    of the simplified model (`solve._check` builds that plan, not the producer's);
  * independent exact aggregation: `vec_engine.VecExact` (integers, numpy object
    arrays of mpz) on the same checker plan; its bytes per live entry grow with the
    exact bit size, bounded here from the factor scales and the joint domain.

The calibration is recorded on every record (`capacity_calibration`) so a replay
on another host can see what the admission assumed; the measured run time is the
truth and is charged whatever the forecast said. Forecast rates carry a declared
safety factor over the measured medians; they are admission estimates, never
guarantees."""
from __future__ import annotations
from fractions import Fraction as Fr
import math
from mdi import plan as P

# measured on the pin host (Apple silicon laptop, Python 3.12.15, gmpy2 2.3.2, numpy 2.3.3)
# on the simplified Pedigree_11 / Promedus_12 / Grids_11 min-fill schedules, 2 November 2026
# (runs/mdi_2026-10-28/CAPACITY_2026-11-02/*.json). Unit: a WORK ENTRY is one bag-domain
# entry visited by one operand (sum over bags of domain x operands, upward + downward +
# readout: `schedule_work`). The admission rate is the measured maximum x safety factor.
CALIBRATION = {
    "version": "2026-11-02-pinhost",
    "safety_factor": 1.5,
    "measured_us_per_work_entry": {"vec_P": {"Pedigree_11": 0.048, "Promedus_12": 0.047, "Grids_11": 0.051},
                                   "vec_I": {"Pedigree_11": 0.093, "Promedus_12": 0.088, "Grids_11": 0.100},
                                   "vec_X": {"Pedigree_11": 0.023, "Promedus_12": 0.017, "Grids_11": 0.187},
                                   "scalar_dense_P_per_bag_entry": {"Pedigree_11": 34.8, "Promedus_12": 29.4, "Grids_11": 95.0},
                                   "scalar_sparse_exact_per_built_entry": {"Pedigree_11_fraction": 17.9, "Pedigree_11_mpz": 15.6, "Promedus_12_mpz": 28.5}},
    "us_per_entry": {"vec_P": 0.08, "vec_I": 0.15, "vec_X": 0.30, "scalar_dense": 150.0, "scalar_sparse": 45.0},
    # resident bytes per entry of the two-pass live set (`peak_entries`: every upward separator message,
    # the largest bag product, one downward message), measured as peak process RSS over that set:
    # vec_P 56-109 (mpfr64 object + pointer), vec_I 114-140 (two endpoints); vec_X: limbs of the
    # per-message exact bit bound (`exact_message_bits`) plus the mpz object header
    "measured_bytes_per_two_pass_entry": {"vec_P": {"Pedigree_11": 109, "Promedus_12": 56, "Grids_11": 60},
                                          "vec_I": {"Pedigree_11": 114, "Promedus_12": 124, "Grids_11": 140}},
    "measured_exact_peak_GiB_vs_forecast": {"Pedigree_11": [1.21, 1.4], "Promedus_12": [3.57, 13.1], "Grids_11": [19.87, 20.8]},
    "bytes_per_entry": {"vec_P": 120, "vec_I": 160, "mpz_header": 64, "scalar_fraction": 580, "scalar_mpz": 360, "scalar_interval": 300},
    "note": "seconds = work entries x admission rate; peak bytes = (largest bag product + peak live messages) x bytes per entry, the "
            "exact aggregation's bytes from its per-message bit bounds; the measured run is charged whatever the forecast said; "
            "the forecast is an admission estimate at this calibration, never a guarantee",
}


def exact_bits_bound(factors, card, free):
    """log2 bound of the exact integer total: every factor scaled to integers by the LCM of
    its denominators, product of the per-factor maxima times the joint domain."""
    bits = 0.0
    for f in factors:
        L = 1
        for q in f.table:
            d = Fr(q).denominator
            L = L * d // math.gcd(L, d)
        mx = max(int(Fr(q) * L) for q in f.table)
        bits += math.log2(max(1, mx))
    for v in free:
        bits += math.log2(card[v])
    return int(bits) + 1


def _factor_max_bits(f):
    L = 1
    for q in f.table:
        d = Fr(q).denominator
        L = L * d // math.gcd(L, d)
    mx = max(int(Fr(q) * L) for q in f.table)
    return max(1, mx).bit_length()


def exact_message_bits(plan, factors):
    """Per-bag bit bound of the exact integer product/sum: bits(bag) = sum of the
    owned factors' scaled maxima bits + sum of the children's message bits +
    log2(interior domain) for the sum. Returns {bag: bits}, the bound of the
    message that bag sends upward (the downward messages are bounded by the
    root's total)."""
    fb = {}
    for b in plan.bags:
        fb[b.idx] = sum(_factor_max_bits(factors[fi]) for fi in b.factors)
    bits = {}
    post, stack = [], [b.idx for b in plan.bags if b.parent == -1]
    seq = []
    while stack:
        x = stack.pop(); seq.append(x); stack.extend(plan.bags[x].children)
    for x in reversed(seq):
        b = plan.bags[x]
        interior = max(1, b.domain(plan.card) // max(1, b.sep_domain(plan.card))) if b.parent >= 0 else b.domain(plan.card)
        bits[x] = fb[x] + sum(bits[c] for c in b.children) + math.ceil(math.log2(max(1, interior)))
    return bits


def exact_peak_bytes(plan, factors, header=None):
    """Peak resident bytes of the vectorized exact aggregation: the largest bag
    product at ITS bit bound plus the planner's live upward messages at theirs."""
    header = CALIBRATION["bytes_per_entry"]["mpz_header"] if header is None else header
    bits = exact_message_bits(plan, factors)
    root_bits = max(bits.values()) if bits else 1
    per_entry = lambda bt: bt // 8 + header
    chunk = 1 << 20                                   # vec_engine.VecExact.CHUNK_ENTRIES
    largest = max((min(b.domain(plan.card), chunk) * per_entry(bits[b.idx]) for b in plan.bags), default=0)
    # live upward messages, simulated as in plan.peak_live_upward but weighted by bytes
    card = plan.card
    seq, stack = [], [b.idx for b in plan.bags if b.parent == -1]
    while stack:
        x = stack.pop(); seq.append(x); stack.extend(plan.bags[x].children)
    live, peak, cur = {}, 0, 0
    for x in reversed(seq):
        b = plan.bags[x]
        for c in b.children:
            if c in live:
                cur -= live.pop(c)
        if b.parent >= 0:
            e = b.sep_domain(card) * per_entry(bits[x])
            live[x] = e
            cur += e
        peak = max(peak, cur)
    # downward messages carry at most the root's bits
    down = max((b.sep_domain(card) for b in plan.bags if b.parent >= 0), default=0) * per_entry(root_bits)
    return largest + peak + down, root_bits


def schedule_work(plan):
    """Entries VISITED by one pass structure on `plan`: every bag domain times its operand
    count (owned factors + incoming messages), upward and downward, plus readout -- the
    unit the vectorized engines are measured in (sum of bag entries x operands)."""
    tot = 0
    for b in plan.bags:
        dom = b.domain(plan.card)
        own = len(b.factors)
        nin = len(b.children) + (1 if b.parent >= 0 else 0)
        # upward: one product per bag (own + children operands); downward: one product per child
        # message; readout: one product per home variable
        n_home = sum(1 for v, h in plan.var_home.items() if h == b.idx)
        tot += dom * (own + len(b.children)) + len(b.children) * dom * (own + nin) + n_home * dom * (own + nin)
    return tot


def peak_entries(plan):
    """Resident entries of the two-pass engines at their peak: EVERY upward
    separator message (all are retained for the downward pass), the largest bag
    product transient, and one downward message (measured: 56-140 B per entry
    of this set on the three external schedules)."""
    lsep = max((b.sep_domain(plan.card) for b in plan.bags if b.parent >= 0), default=0)
    return plan.sum_sep_entries + plan.largest_bag_entries + lsep


def forecast_identity(prod_plan, chk_plan, factors, card, free, cal=None):
    """Seconds and bytes of the complete identity route on the schedules that execute:
    producer (vectorized P, saved order), interval checker (vectorized I, the checker's
    min-fill plan) and the independent exact aggregation (vectorized X, same plan)."""
    cal = cal or CALIBRATION
    rates, bpe = cal["us_per_entry"], cal["bytes_per_entry"]
    wp, wi = schedule_work(prod_plan), schedule_work(chk_plan)
    x_bytes, zbits = exact_peak_bytes(chk_plan, factors)
    sec = {"producer_P": wp * rates["vec_P"] * 1e-6, "checker_I": wi * rates["vec_I"] * 1e-6, "exact_X": wi * rates["vec_X"] * 1e-6}
    byt = {"producer_P": peak_entries(prod_plan) * bpe["vec_P"], "checker_I": peak_entries(chk_plan) * bpe["vec_I"], "exact_X": x_bytes}
    return {"calibration": cal["version"], "layout": "vectorized",
            "schedules": {"producer": {"order": prod_plan.name, "largest_bag": prod_plan.largest_bag_entries, "sum_bag_entries": prod_plan.sum_bag_entries,
                                       "peak_live_entries": P.peak_live_upward(prod_plan), "work_entries": wp},
                          "checker": {"order": chk_plan.name, "largest_bag": chk_plan.largest_bag_entries, "sum_bag_entries": chk_plan.sum_bag_entries,
                                      "peak_live_entries": P.peak_live_upward(chk_plan), "work_entries": wi}},
            "exact_root_bits_bound": zbits,
            # admission uses the UNROUNDED seconds (a sub-centisecond forecast is still a forecast)
            "seconds": {**sec, "producer_and_checker": sec["producer_P"] + sec["checker_I"], "total": sum(sec.values())},
            "bytes": {**{k: int(v) for k, v in byt.items()}, "peak_producer_and_checker": int(max(byt["producer_P"], byt["checker_I"])), "peak": int(max(byt.values()))}}


def admit(fc, wall_remaining_s, rss_cap_bytes, rss_now_bytes=0):
    """The admission decision against the PHYSICAL budget, per stage. The route is
    admissible when the producer and the interval checker fit the remaining wall and
    the RSS cap; the independent exact aggregation is admitted separately (when it
    does not fit, the route runs and its terminal is the contract's
    VERIFIED_SHARED_AGGREGATION_ONLY, never a certificate). Returns a dict with
    `route` in FEASIBLE / WALL_FORECAST_EXCEEDS / RSS_FORECAST_EXCEEDS, `aggregation`
    in FEASIBLE / WALL_FORECAST_EXCEEDS / RSS_FORECAST_EXCEEDS, and reasons."""
    now = int(rss_now_bytes or 0)
    wall = float(wall_remaining_s)
    cap = int(rss_cap_bytes) if rss_cap_bytes is not None else None
    out = {"wall_remaining_s": round(wall, 1), "rss_cap_bytes": cap, "rss_now_bytes": now}
    pc_s = fc["seconds"]["producer_and_checker"]
    pc_b = fc["bytes"]["peak_producer_and_checker"] + now
    if pc_s > wall:
        out["route"] = "WALL_FORECAST_EXCEEDS"
        out["route_reason"] = ("producer %.1f s + interval checker %.1f s at the calibrated vectorized rates forecast %.1f s "
                               "against %.1f s remaining" % (fc["seconds"]["producer_P"], fc["seconds"]["checker_I"], pc_s, wall))
    elif cap is not None and pc_b > cap:
        out["route"] = "RSS_FORECAST_EXCEEDS"
        out["route_reason"] = ("the producer / interval checker forecast %.2f GiB resident (largest bag product plus live messages at "
                               "%d / %d bytes per entry) plus %.2f GiB already resident, against the %.2f GiB cap"
                               % (fc["bytes"]["peak_producer_and_checker"] / 2 ** 30, CALIBRATION["bytes_per_entry"]["vec_P"],
                                  CALIBRATION["bytes_per_entry"]["vec_I"], now / 2 ** 30, cap / 2 ** 30))
    else:
        out["route"] = "FEASIBLE"
        out["route_reason"] = "producer + interval checker forecast %.1f s and %.2f GiB fit %.1f s and the %.2f GiB cap" % (
            pc_s, fc["bytes"]["peak_producer_and_checker"] / 2 ** 30, wall, (cap or 0) / 2 ** 30)
    tot_s = fc["seconds"]["total"]
    x_b = fc["bytes"]["exact_X"] + now
    if tot_s > wall:
        out["aggregation"] = "WALL_FORECAST_EXCEEDS"
        out["aggregation_reason"] = ("adding the exact aggregation (%.1f s) forecasts %.1f s against %.1f s remaining"
                                     % (fc["seconds"]["exact_X"], tot_s, wall))
    elif cap is not None and x_b > cap:
        out["aggregation"] = "RSS_FORECAST_EXCEEDS"
        out["aggregation_reason"] = ("the exact integer aggregation forecasts %.2f GiB resident (per-message bit bounds up to %d bits) "
                                     "against the %.2f GiB cap" % (fc["bytes"]["exact_X"] / 2 ** 30, fc["exact_root_bits_bound"], cap / 2 ** 30))
    else:
        out["aggregation"] = "FEASIBLE"
        out["aggregation_reason"] = "the exact aggregation adds %.1f s and %.2f GiB within the budget" % (fc["seconds"]["exact_X"], fc["bytes"]["exact_X"] / 2 ** 30)
    return out


def entries_affordable(wall_remaining_s, rate_key="scalar_sparse", cal=None):
    """How many metered entries the remaining wall buys at a calibrated SCALAR engine
    rate: the physical replacement of the fixed per-program meter cap used by the
    research routes' pricing probes (their engines are the scalar layouts)."""
    cal = cal or CALIBRATION
    return max(1, int(float(wall_remaining_s) / (cal["us_per_entry"][rate_key] * 1e-6)))


def meter_backstop(wall_s, cal=None):
    """The shared meter's physical backstop: no calibrated engine visits more than
    1e8 entries per second on the pin host, so a cumulative meter of wall x 1e8 cannot
    bind before the wall does; the meter remains the shared ACCOUNTING unit."""
    return int(float(wall_s) * 1e8)


def checker_plan(r):
    """The plan `solve._check` actually builds for the interval checker and the exact aggregation."""
    adj = P.primal_graph(r.free, r.card, r.factors)
    return P.build_plan("min_fill", P.order_min_fill(r.free, r.card, adj), r.free, r.card, r.factors)
