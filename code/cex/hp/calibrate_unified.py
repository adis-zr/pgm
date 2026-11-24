"""Fixed phase-rate calibration for the unified planner (brief section 5): at most eight tiny, separately seeded development controls (cardinalities 2 / 4 / 6; a cycle and a small grid; exact /
perturbed / generic tables; NOT the scored inputs) measured once under a 20 s supervised allocation. For every host phase: declared work count, measured per-unit time; the rate = the MAXIMUM
observed per-unit time x a fixed 1.5 safety multiplier; the kernel rate stays 20e6 rows/s unless the development evidence is slower. Writes PHASE_RATES.json (frozen; its sha256 is recorded by the
planner in every result). Counts: canon_per_entry = source entries; exact_profile_per_axis_entry = sum over factors of arity x entries (the per-axis normalized slices); check_per_entry = entries +
states of a check_candidate scan (rational bit size enters through the measured time, not the count); fast_profile_per_axis_entry = arity x entries of the log slices; distance_per_unit =
sum_v card_v^2 x profile length (pairwise L-infinity distances); order_per_unit = n^2 + sum arity (arity - 1); lowering_per_entry = physical source entries; enclosure_per_state = coarse states;
recovery_per_row / publish_per_row = original rows. usage: calibrate_unified.py OUT_JSON [--write-rates PATH]"""
import sys, os, json, time, random, hashlib, argparse, math
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'cex', 'newarm'))
import coarse_envelope as CE, unified_planner as UP, hp_gen as G
from coarse_envelope import tnow

def dev_model(seed, n, card, topo, fam):
    rng = random.Random(seed); E = [(i, (i + 1) % n) for i in range(n)] if topo == 'cycle' else [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)]; facs = []; lat = [a * 2 // card for a in range(card)]
    for (u, v) in E:
        if fam == 'generic': facs.append(((u, v), [F(rng.randrange(1, 32), 16) for _ in range(card * card)])); continue
        while True:
            T = [rng.randrange(1, 10) for _ in range(4)]
            if T[0] * T[3] - T[1] * T[2] != 0: break
        su = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; sv = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; vals = []
        for a in range(card):
            for b in range(card):
                x = F(T[2 * lat[a] + lat[b]]) * su[a] * sv[b]
                if fam == 'perturbed': x *= 1 + F(rng.choice((-1, 1)), 16384)
                vals.append(x)
        facs.append(((u, v), vals))
    for v in range(n): facs.append(((v,), [F(rng.randrange(1, 10), 8) for _ in range(card)]))
    m = dict(cards=[card] * n, factors=[dict(scope=sc, values=vals) for sc, vals in facs], evidence={}); m, _ = G.permute('UNIFIED-CALIBRATION-DEV-%d' % seed, topo, card, fam, m); return m

CONTROLS = [(11, 6, 2, 'cycle', 'exact'), (12, 6, 4, 'cycle', 'perturbed'), (13, 6, 6, 'cycle', 'generic'), (14, 6, 4, 'grid', 'exact'), (15, 6, 6, 'grid', 'perturbed'), (16, 6, 2, 'grid', 'generic'), (17, 8, 6, 'cycle', 'exact'), (18, 6, 6, 'grid', 'generic')]

def measure(m):
    """one pass of every phase on the model; returns per-phase (count, seconds)"""
    r = {}; clock = CE.Clock(tnow() + 10, {}); bud = CE.Budget(CE.CONSTRUCTOR_BYTES)
    t = tnow(); M = CE.canonicalize(m, clock, bud); entries = sum(len(v) for _, v in M.factors) + sum(M.cards); r['canon_per_entry'] = (entries, tnow() - t)
    t = tnow(); cl1 = CE.exact_profile_classes(M, clock, bud); axis_entries = sum(len(sc) * len(vals) for sc, vals in M.factors); r['exact_profile_per_axis_entry'] = (axis_entries, tnow() - t)
    sc1 = CE.exact_scales(M, cl1, clock); t = tnow(); Cz1 = CE.check_candidate(M, cl1, sc1, clock, bud); r['check_per_entry'] = (sum(len(v) for _, v in M.factors) + sum(M.cards), tnow() - t)
    M1 = CE.stage_model(M, Cz1); t = tnow(); prof, why = CE.slice_profiles(M1, clock, bud); r['fast_profile_per_axis_entry'] = (sum(len(sc) * len(vals) for sc, vals in M1.factors), tnow() - t)
    proflen = [0] * len(M1.cards)
    for sc, vals in M1.factors:
        for ax, v in enumerate(sc): proflen[v] += len(vals) // M1.cards[v]
    t = tnow(); classes2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v])), clock), M1.cards[v]) if M1.cards[v] > 1 else [0] for v in range(len(M1.cards))]; r['distance_per_unit'] = (sum(M1.cards[v] ** 2 * proflen[v] for v in range(len(M1.cards))), tnow() - t)
    n = len(M.cards); scopes = [sc for sc, _ in M.factors]; t = tnow(); order, vols = CE.elimination_order(M.cards, scopes, clock, bud); r['order_per_unit'] = (n * n + sum(len(sc) * (len(sc) - 1) for sc in scopes), tnow() - t)
    # native identity solve: lowering / kernel / enclosure measured by the adapter's own stats; recovery + publish measured here
    model = UP.identity_model(M); S = CE.run_executor(model, order, M.scalar, tnow() + 10, {}, 'calib'); st = S.stats; vol = UP.physical_volume(M.cards, scopes, order)
    r['lowering_per_entry'] = (vol['source_entries'], st.get('lowering_s', 0.0)); r['kernel_per_row'] = (2 * vol['sum_product'], st.get('kernel_s', 0.0)); r['enclosure_per_state'] = (sum(M.cards), st.get('enclosure_s', 0.0)); r['build_load_s'] = (1, st.get('build_s', 0.0))
    t = tnow(); acc = UP.rows_identity(M, S); K = sum(M.cards); r['recovery_per_row'] = (K, tnow() - t); t = tnow(); rows = CE.publish(M, acc, F(1, 200), clock); r['publish_per_row'] = (K, tnow() - t)
    return r

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('out'); ap.add_argument('--write-rates', default=None); a = ap.parse_args(); t_all = tnow(); per = []; agg = {}
    for seed, n, card, topo, fam in CONTROLS:
        m = dev_model(seed, n, card, topo, fam); r = measure(m); per.append(dict(seed=seed, n=n, card=card, topology=topo, family=fam, phases={k: dict(count=c, seconds=s, per_unit=(s / c if c else None)) for k, (c, s) in r.items()}))
        for k, (c, s) in r.items():
            if c: agg.setdefault(k, []).append(s / c)
    rates = dict(frozen=True, calibrated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), rule='max observed per-unit time over the 8 dev controls x 1.5; kernel rate 20e6 rows/s unless slower observed; build_load_s = max observed', controls=[dict(seed=s, n=n, card=c, topology=t, family=f) for s, n, c, t, f in CONTROLS], safety=1.5)
    for k, xs in agg.items():
        if k == 'build_load_s': rates[k] = max(xs)
        elif k == 'kernel_per_row': rates[k] = max(1.0 / UP.KERNEL_ROWS_PER_S, 1.5 * max(xs)); rates['kernel_rate_note'] = 'max observed %.3g s/row vs frozen 1/20e6 = %.3g; the slower wins' % (max(xs), 1.0 / UP.KERNEL_ROWS_PER_S)
        else: rates[k] = 1.5 * max(xs)
    rates['finalize_reserve_s'] = UP.FINALIZE_RESERVE_S; rates['setup_s'] = 0.0
    body = json.dumps({k: v for k, v in rates.items() if k != 'sha256'}, sort_keys=True); rates['sha256'] = hashlib.sha256(body.encode()).hexdigest()
    json.dump(dict(rates=rates, per_control=per, wall_s=tnow() - t_all), open(a.out, 'w'), indent=1, default=str)
    if a.write_rates: json.dump(rates, open(a.write_rates, 'w'), indent=1)
    print(json.dumps({k: (round(v, 9) if isinstance(v, float) else v) for k, v in rates.items() if k not in ('controls',)}, indent=0)[:1500]); print('wall', round(tnow() - t_all, 3))

if __name__ == '__main__': main()
