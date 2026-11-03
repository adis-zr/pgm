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
    # the version names the CONSTANTS and the FORECAST RULES that priced a record: 2026-11-03b (integrated
    # pass) keeps every constant of 2026-11-03 but forecasts the exact aggregation on its actual tiles and
    # retained messages, prices the checker on the checker's own schedule and counts the occupancy probe,
    # so a record priced under the earlier rules is refused at replay as priced under another calibration
    "version": "2026-11-03b-pinhost",
    "safety_factor": 1.5,
    "measured_us_per_work_entry": {"vec_P": {"Pedigree_11": 0.048, "Promedus_12": 0.047, "Grids_11": 0.051},
                                   "vec_I": {"Pedigree_11": 0.093, "Promedus_12": 0.088, "Grids_11": 0.100},
                                   "vec_X": {"Pedigree_11": 0.023, "Promedus_12": 0.017, "Grids_11": 0.187},
                                   "scalar_dense_P_per_bag_entry": {"Pedigree_11": 34.8, "Promedus_12": 29.4, "Grids_11": 95.0},
                                   "scalar_sparse_exact_per_built_entry": {"Pedigree_11_fraction": 17.9, "Pedigree_11_mpz": 15.6, "Promedus_12_mpz": 28.5}},
    "us_per_entry": {"vec_P": 0.08, "vec_I": 0.15, "vec_X": 0.30, "scalar_dense": 150.0, "scalar_sparse": 45.0},
    # resident bytes per entry of the two-pass live set (`peak_entries`: every upward separator message,
    # the largest bag product, one downward message), measured as peak process RSS over that set on the
    # three external schedules: vec_P 56-109 (mpfr64 object + pointer), vec_I 114-140 (two endpoints);
    # vec_X: limbs of the per-message exact bit bound (`exact_message_bits`) plus the mpz object header.
    # The admission constants are the MEASURED MAXIMA (not a multiplier): the forecast is the best
    # estimate following the live allocations; the RSS cap is ENFORCED by the engines' polls regardless
    "measured_bytes_per_two_pass_entry": {"vec_P": {"Pedigree_11": 109, "Promedus_12": 56, "Grids_11": 60},
                                          "vec_I": {"Pedigree_11": 114, "Promedus_12": 124, "Grids_11": 140}},
    # isolated exact aggregation: [measured RSS growth, forecast exact_X]; the 3 November integrated forecast counts
    # EVERY retained upward message plus the actual tile (Grids_11's 19.87 GiB was measured on the 2 November engine,
    # which retained the same messages; its forecast then read 13.06 GiB, now 20.31)
    "measured_exact_peak_GiB_vs_forecast": {"Pedigree_11": [1.31, 1.62], "Promedus_12": [3.57, 7.08], "Grids_11": [19.87, 20.31]},
    "bytes_per_entry": {"vec_P": 112, "vec_I": 144, "mpz_header": 64, "mpz_zero": 48, "scalar_fraction": 580, "scalar_mpz": 360, "scalar_interval": 300},
    # what a finished engine stage leaves resident that the next stage does not reuse, as a FRACTION of the
    # stage's live set (P then I in one process: Promedus_12 whole 6.46 vs isolated I 5.73 GiB = 12.7 %;
    # Grids_11 6.81 vs 6.10 = 11.6 %); admission adds this fraction of the largest stage forecast
    "stage_handover_residue_fraction": 0.13,
    "stage_handover_residue_max_bytes": 805306368,
    "measured_stage_handover_residue_GiB": {"Promedus_12_P_then_I": 0.73, "Grids_11_P_then_I": 0.71},
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


def exact_tile_entries(bag, card, chunk=None):
    """The product-tile size the exact engine ACTUALLY allocates for `bag`: the
    engine iterates axes -- summed first, then kept -- until the remaining
    sub-bag is at most `chunk` (vec_engine.VecExact._reduce), so the tile is the
    first sub-bag not above the chunk (the whole domain when it fits; never above
    the chunk unless a single axis exceeds it). SCOPE: this is the tile of the
    UPWARD reduction (kept axes = the separator to the parent). The downward and
    readout reductions keep different axes (a child separator; one variable) and
    the engine tiles them with the same rule, so their tiles are also at most the
    chunk, but their kept-axis order differs from the one simulated here; the
    forecast therefore bounds the tile SIZE (<= chunk) without naming the exact
    sub-bag of every reduction. Operand views and staging copies are outside the
    tile term (see VecExact._reduce)."""
    chunk = chunk or (1 << 20)
    dom = bag.domain(card)
    if dom <= chunk:
        return dom
    sep = set(bag.separator)
    order = [v for v in bag.vars if v not in sep] + [v for v in bag.vars if v in sep]
    sub = dom
    for v in order:
        if sub <= chunk:
            break
        sub //= card[v]
    return sub


def exact_peak_bytes(plan, factors, header=None, occupancy=None):
    """Peak resident bytes of the vectorized exact aggregation on ITS ACTUAL
    allocation schedule (3 November 2026): EVERY upward message is RETAINED
    through the downward pass (`VecExact.run()` keeps `msg` for `counts()`), so
    the live set at the peak is the sum of ALL upward messages at their own bit
    bounds (never a parent-frees-child simulation), plus the largest product
    TILE the engine allocates (`exact_tile_entries`, from the tiling the engine
    performs), plus one downward message at the root's bits. `occupancy`
    ({bag: nonzero fraction of its upward message}) scales the RETAINED message
    bytes: an exact zero entry costs the object header only. WHAT IS NOT COVERED
    (third review): the operand views the checker's layout helper builds per
    reduction (offset arrays and gathered copies the size of each operand's
    placement), numpy's staging copies inside object-array sums, the converted
    factor tables, and the interpreter; measured on Pedigree_11 the forecast
    stayed above the RSS growth (1.62 vs 1.31 GiB) through the message bit
    bounds, not through these terms. The figure is an admission ESTIMATE; the
    RSS cap is enforced by the engines' polls and, in the comparison, by the
    launcher's process-tree supervision."""
    header = CALIBRATION["bytes_per_entry"]["mpz_header"] if header is None else header
    zero_bytes = CALIBRATION["bytes_per_entry"].get("mpz_zero", 48)
    bits = exact_message_bits(plan, factors)
    root_bits = max(bits.values()) if bits else 1
    per_entry = lambda bt: bt // 8 + header
    card = plan.card
    largest = max((exact_tile_entries(b, card) * per_entry(bits[b.idx]) for b in plan.bags), default=0)

    def msg_bytes(x, n):
        occ = 1.0 if occupancy is None else float(occupancy.get(x, 1.0))
        return int(n * (occ * per_entry(bits[x]) + (1.0 - occ) * zero_bytes))
    retained = sum(msg_bytes(b.idx, b.sep_domain(card)) for b in plan.bags if b.parent >= 0)
    down = max((b.sep_domain(card) for b in plan.bags if b.parent >= 0), default=0) * per_entry(root_bits)
    return largest + retained + down, root_bits


def occupancy_probe(plan, factors, card, deadline=None, charge=None):
    """A BOUNDED, CHARGED Boolean occupancy pass over the checker plan in the
    vectorized layout: the nonzero fraction of every upward message of the exact
    aggregation (hard zeros prune). Costs a Boolean product per bag (measured
    0.3-1.9 s on the external schedules), charged to the shared meter like any
    other visited entries, and REUSED: one probe per (plan, factor list) per
    INVOCATION -- the admission at discovery, the repricing at binding and the
    checker's own admission all read the same result. The cache key is the
    plan's order and the factor tables' CONTENT (scope, cardinalities, zero
    mask -- the only inputs the occupancy depends on), never object identity:
    the three stages each restrict and simplify their own factor lists, so an
    identity key missed every time and the probe ran three times per invocation
    (Pedigree_11: 3 x 5.9 M entries) while the record said once. The pipeline
    clears the cache at its entry boundary, so each invocation is charged
    exactly one probe. Returns ({bag: fraction}, entries_visited)."""
    import numpy as np
    if deadline is not None:
        deadline()                            # the budget is polled BEFORE the key is built and before a cache hit returns
    key = (tuple(plan.order), tuple((tuple(f.scope), tuple(int(c) for c in f.card),
                                    bytes(1 if Fr(x) == 0 else 0 for x in f.table)) for f in factors))
    hit = _OCCUPANCY_CACHE.get(key)
    if hit is not None:
        return hit[0], 0                      # reused: nothing new is visited or charged
    bags = plan.bags
    fac = {fi: np.array([1 if Fr(x) != 0 else 0 for x in f.table], dtype=object).reshape(tuple(int(c) for c in f.card))
           for fi, f in enumerate(factors)}
    from mdi.vec_engine import _bag_view
    msgs = {}
    occ = {}
    visited = 0
    seq, stack = [], [b.idx for b in bags if b.parent == -1]
    while stack:
        x = stack.pop(); seq.append(x); stack.extend(bags[x].children)
    for x in reversed(seq):
        b = bags[x]
        if b.parent < 0:
            continue
        bvars = tuple(b.vars)
        shape = tuple(card[v] for v in bvars)
        parts = [_bag_view(fac[fi], tuple(factors[fi].scope), bvars) for fi in b.factors]
        parts += [_bag_view(msgs[c][1], msgs[c][0], bvars) for c in b.children]
        if deadline is not None:
            deadline()
        acc = np.ones(shape, dtype=object) if not parts else np.array(np.broadcast_to(parts[0], shape), dtype=object)
        for q in parts[1:]:
            np.multiply(acc, q, out=acc)
        visited += int(acc.size)
        if charge is not None:
            charge(int(acc.size))
        sep = tuple(sorted(set(b.vars) & set(bags[b.parent].vars)))
        axes = tuple(k for k, v in enumerate(bvars) if v not in sep)
        out = np.asarray(acc.sum(axis=axes), dtype=object) if axes else acc
        out = np.where(out != 0, 1, 0).astype(object)
        msgs[x] = (sep, out)
        occ[x] = float(np.count_nonzero(out)) / max(1, out.size)
    _OCCUPANCY_CACHE[key] = (occ, visited)
    if len(_OCCUPANCY_CACHE) > 8:
        _OCCUPANCY_CACHE.pop(next(iter(_OCCUPANCY_CACHE)))
    return occ, visited


_OCCUPANCY_CACHE = {}
INVOCATION_BASELINE = [None]      # the resident set at THIS invocation's entry (set by the public entry points, reset per invocation)


def invocation_baseline_bytes():
    """The resident set at the invocation's entry when one is recorded, else the
    current resident set (a standalone call outside the public entry points)."""
    return INVOCATION_BASELINE[0] if INVOCATION_BASELINE[0] is not None else rss_current_bytes()


def rss_current_bytes():
    """The process's CURRENT resident set (what a new allocation competes with),
    not the high-water mark: the forecast's 'already resident' term must not
    count a transient that has been released (the occupancy probe's arrays, a
    previous engine's messages). Falls back to the high-water mark when the
    current figure is unavailable."""
    import os, subprocess, resource
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            return int(out) * 1024
    except Exception:
        pass
    from mdi.solve import _rss_bytes
    return _rss_bytes()


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


def forecast_identity(prod_plan, chk_plan, factors, card, free, cal=None, occupancy=None):
    """Seconds and bytes of the complete identity route on the schedules that execute:
    producer (saved order), interval checker and the independent exact aggregation
    (both on the checker's min-fill plan), at the rates of the layout that EXECUTES
    on this host (`calibration_for_layout`)."""
    cal = cal or calibration_for_layout()
    rates, bpe = cal["us_per_entry"], cal["bytes_per_entry"]
    wp, wi = schedule_work(prod_plan), schedule_work(chk_plan)
    x_bytes, zbits = exact_peak_bytes(chk_plan, factors, occupancy=occupancy)
    sec = {"producer_P": wp * rates["vec_P"] * 1e-6, "checker_I": wi * rates["vec_I"] * 1e-6, "exact_X": wi * rates["vec_X"] * 1e-6}
    # RETAINED state that overlaps with a stage's live set (3 November 2026): the
    # converted factor tables of the running engine (one mpfr per entry per endpoint)
    # and the producer's published rows kept while the checker runs plus the checker's
    # own readout rows (exact rationals, ~200 B each). The interpreter, the parsed
    # model and anything else already resident are counted by the admission's
    # `rss_now_bytes` term (the CURRENT resident set), never twice.
    table_entries = sum(len(f.table) for f in factors)
    n_coords = sum(card[v] for v in free)
    retained = {"converted_factor_tables": table_entries * (bpe["vec_P"] + bpe["vec_I"]),
                "published_and_readout_rows": n_coords * 4 * 200}
    ret = sum(retained.values())
    byt = {"producer_P": peak_entries(prod_plan) * bpe["vec_P"] + ret, "checker_I": peak_entries(chk_plan) * bpe["vec_I"] + ret, "exact_X": x_bytes + ret}
    return {"calibration": cal["version"], "layout": cal.get("layout", executing_layout()),
            "schedules": {"producer": {"order": prod_plan.name, "largest_bag": prod_plan.largest_bag_entries, "sum_bag_entries": prod_plan.sum_bag_entries,
                                       "peak_live_entries": P.peak_live_upward(prod_plan), "work_entries": wp},
                          "checker": {"order": chk_plan.name, "largest_bag": chk_plan.largest_bag_entries, "sum_bag_entries": chk_plan.sum_bag_entries,
                                      "peak_live_entries": P.peak_live_upward(chk_plan), "work_entries": wi}},
            "exact_root_bits_bound": zbits, "retained_bytes": retained, "occupancy_used": occupancy is not None,
            # admission uses the UNROUNDED seconds (a sub-centisecond forecast is still a forecast)
            "seconds": {**sec, "producer_and_checker": sec["producer_P"] + sec["checker_I"], "total": sum(sec.values())},
            "bytes": {**{k: int(v) for k, v in byt.items()}, "peak_producer_and_checker": int(max(byt["producer_P"], byt["checker_I"])), "peak": int(max(byt.values()))}}


def admit(fc, wall_remaining_s, rss_cap_bytes, rss_now_bytes=0, rss_baseline_bytes=None, cal=None, remaining_only=False):
    """The admission decision against the PHYSICAL budget, per stage. Memory is
    judged as the stage's forecast live set plus the INVOCATION BASELINE (the
    resident set at the invocation's entry: interpreter, parsed model, tables)
    plus the measured stage-handover residue (what a finished engine stage
    leaves behind in the allocator that the next stage cannot reuse: 0.70-0.73
    GiB measured, P then I in one process on Promedus_12 and Grids_11). The
    CURRENT resident set is recorded beside it but is not the term: a finished
    engine's freed arenas are reused by the next stage (whole-invocation peaks
    6.46 / 6.81 GiB against isolated stage peaks 5.73 / 6.10), so counting them
    as live would refuse stages that fit. `route`: producer + interval checker;
    `aggregation`: the exact aggregation; `certificate`: every stage.
    `remaining_only=True` is the LATER admission (producer and interval checker
    already finished): only the aggregation's own remaining work is reserved
    against the remaining wall, never the finished stages' forecasts again."""
    cal = cal or CALIBRATION
    now = int(rss_now_bytes or 0)
    base = int(rss_baseline_bytes) if rss_baseline_bytes is not None else now
    # the handover residue is what a finished engine leaves resident that the next stage
    # cannot reuse: measured 0.71-0.73 GiB after the 5.7-6.1 GiB producer stages of
    # Promedus_12 / Grids_11 (11.6-12.7 % of the preceding stage). Taken as that fraction
    # of the PRECEDING stage's forecast, capped at the measured maximum (a flat charge
    # would refuse small models under small caps; a fraction without a cap would charge
    # a residue no stage was ever measured to leave).
    frac = float(cal.get("stage_handover_residue_fraction", 0.13))
    cap_res = int(cal.get("stage_handover_residue_max_bytes", 0.75 * 2 ** 30))
    residue_i = min(cap_res, int(frac * fc["bytes"]["producer_P"]))      # what the producer leaves for the checker
    residue_x = min(cap_res, int(frac * fc["bytes"]["checker_I"]))       # what the checker leaves for the aggregation
    resident = base + residue_i
    residue = residue_i
    wall = float(wall_remaining_s)
    cap = int(rss_cap_bytes) if rss_cap_bytes is not None else None
    out = {"wall_remaining_s": round(wall, 1), "rss_cap_bytes": cap, "rss_now_bytes": now, "rss_baseline_bytes": base,
           "stage_handover_residue_bytes": residue, "resident_term_bytes": resident}
    pc_s = fc["seconds"]["producer_and_checker"]
    pc_b = fc["bytes"]["peak_producer_and_checker"] + resident
    if pc_s > wall:
        out["route"] = "WALL_FORECAST_EXCEEDS"
        out["route_reason"] = ("producer %.1f s + interval checker %.1f s at the calibrated vectorized rates forecast %.1f s "
                               "against %.1f s remaining" % (fc["seconds"]["producer_P"], fc["seconds"]["checker_I"], pc_s, wall))
    elif cap is not None and pc_b > cap:
        out["route"] = "RSS_FORECAST_EXCEEDS"
        out["route_reason"] = ("the producer / interval checker forecast %.2f GiB resident (two-pass live set at %d / %d bytes per "
                               "entry plus retained state) plus %.2f GiB (invocation baseline %.2f + handover residue %.2f), against the %.2f GiB cap"
                               % (fc["bytes"]["peak_producer_and_checker"] / 2 ** 30, cal["bytes_per_entry"]["vec_P"],
                                  cal["bytes_per_entry"]["vec_I"], resident / 2 ** 30, base / 2 ** 30, residue / 2 ** 30, cap / 2 ** 30))
    else:
        out["route"] = "FEASIBLE"
        out["route_reason"] = "producer + interval checker forecast %.1f s and %.2f GiB (+%.2f GiB resident) fit %.1f s and the %.2f GiB cap" % (
            pc_s, fc["bytes"]["peak_producer_and_checker"] / 2 ** 30, resident / 2 ** 30, wall, (cap or 0) / 2 ** 30)
    tot_s = fc["seconds"]["exact_X"] if remaining_only else fc["seconds"]["total"]
    x_b = fc["bytes"]["exact_X"] + base + residue_x
    if tot_s > wall:
        out["aggregation"] = "WALL_FORECAST_EXCEEDS"
        out["aggregation_reason"] = (("the exact aggregation's remaining work (%.1f s) exceeds %.1f s remaining" % (fc["seconds"]["exact_X"], wall))
                                     if remaining_only else
                                     ("adding the exact aggregation (%.1f s) forecasts %.1f s against %.1f s remaining"
                                      % (fc["seconds"]["exact_X"], tot_s, wall)))
    elif cap is not None and x_b > cap:
        out["aggregation"] = "RSS_FORECAST_EXCEEDS"
        out["aggregation_reason"] = ("the exact integer aggregation forecasts %.2f GiB resident (per-message bit bounds up to %d bits) "
                                     "against the %.2f GiB cap" % (fc["bytes"]["exact_X"] / 2 ** 30, fc["exact_root_bits_bound"], cap / 2 ** 30))
    else:
        out["aggregation"] = "FEASIBLE"
        out["aggregation_reason"] = "the exact aggregation adds %.1f s and %.2f GiB within the budget" % (fc["seconds"]["exact_X"], fc["bytes"]["exact_X"] / 2 ** 30)
    # the CERTIFICATE decision (3 November 2026): a certified publication needs the
    # complete required checking path -- producer, interval checker AND the exact
    # aggregation -- so a route whose aggregation is already refused cannot
    # satisfy the requested certificate; it is admitted for the certified
    # comparison only when every stage fits. Shared-aggregation-only execution
    # remains available as an explicitly selected diagnostic (`diagnostic_shared_only`).
    out["certificate"] = "FEASIBLE" if (out["route"] == "FEASIBLE" and out["aggregation"] == "FEASIBLE") else (
        out["route"] if out["route"] != "FEASIBLE" else "AGGREGATION_" + out["aggregation"])
    out["certificate_reason"] = (out["route_reason"] if out["route"] != "FEASIBLE" else
                                 ("the complete certified path fits" if out["aggregation"] == "FEASIBLE" else
                                  "producer + interval checker fit but the required exact aggregation does not: %s; the route cannot "
                                  "satisfy the certificate and is not admitted for the certified comparison (shared-aggregation-only "
                                  "execution is an explicit diagnostic, never a certificate)" % out["aggregation_reason"]))
    return out


def executing_layout():
    """The dense-engine layout this interpreter actually executes ('vectorized' when
    numpy is importable, else 'scalar'); the calibration's rates are bound to it."""
    try:
        from mdi import vec_engine as V
        return "vectorized" if V.AVAILABLE else "scalar"
    except Exception:
        return "scalar"


def calibration_for_layout(layout=None, cal=None):
    """The admission rates for the layout that executes: a host without numpy takes
    the scalar fallback and must NOT inherit the vectorized rates. The calibration
    version then names the layout so a record priced under one is refused under
    the other."""
    cal = dict(cal or CALIBRATION)
    layout = layout or executing_layout()
    if layout == "scalar":
        rates = dict(cal["us_per_entry"])
        rates["vec_P"], rates["vec_I"], rates["vec_X"] = rates["scalar_dense"], rates["scalar_dense"], rates["scalar_sparse"]
        bpe = dict(cal["bytes_per_entry"])
        bpe["vec_P"], bpe["vec_I"] = 160, cal["bytes_per_entry"]["scalar_interval"]
        cal = dict(cal, us_per_entry=rates, bytes_per_entry=bpe, version=cal["version"] + "-scalar", layout="scalar")
    else:
        cal = dict(cal, layout="vectorized")
    return cal


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
