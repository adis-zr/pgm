
# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, time, random, json
None; sys.set_int_max_str_digits(0)
from fractions import Fraction as F
import pgm.algorithms.structural.core as core, pgm.algorithms.structural.cex_executor as X, pgm.algorithms.structural.support as support
rng = random.Random(7); out = []
for trial in range(40):
    n = rng.randint(2, 7); cards = [rng.randint(2, 4) for _ in range(n)]; nf = rng.randint(1, n + 3); factors = []
    for _ in range(nf):
        k = rng.randint(1, min(3, n)); sc = tuple(rng.sample(range(n), k)); vol = 1
        for v in sc: vol *= cards[v]
        zp = rng.choice([0.0, 0.2, 0.5, 0.8]); factors.append(dict(scope=sc, values=[F(0) if rng.random() < zp else F(rng.randint(1, 9), rng.randint(1, 9)) for _ in range(vol)]))
    ev = {rng.randrange(n): 0} if rng.random() < 0.4 else {}
    m = dict(cards=cards, factors=factors, evidence=ev)
    try: truth = core.brute_force(m); zero = False
    except ValueError: truth = None; zero = True
    order = [v for v in range(n) if v not in ev]; rng.shuffle(order)
    t = time.monotonic()
    try:
        thr = rng.choice([0.25, 1.01, 0.0]); r = X.execute(m, order, deadline=time.monotonic() + 30, cap_bytes=256 * 1024 ** 2, dense_fill_threshold=thr); st = r['status']
    except X.Stop as e: r = None; st = 'STOP:' + e.kind + ':' + e.reason[:60]
    ok = None
    if r and r['status'] == 'CERTIFIED':
        ok = all(lo <= p <= hi for row, ps in zip(r['intervals'], truth) for (lo, hi), p in zip(row, ps)); core.verify_output(r['intervals'], r['points'])
        ref = support.solve(m, deadline=time.monotonic() + 30, order=order); ok = ok and all(lo <= p <= hi for row, ps in zip(r['intervals'], ref['points']) for (lo, hi), p in zip(row, ps))
    elif r and r['status'] == 'ZERO_EVIDENCE': ok = zero
    thr = locals().get('thr')
    out.append(dict(trial=trial, n=n, cards=cards, nf=nf, ev=ev, zero_truth=zero, status=st, contained=ok, maxw=(r['stats'].get('max_width_float') if r else None), K=(r['stats'].get('max_label_K') if r else None), thr=thr, counters={k: r['stats']['counters'][k] for k in ('forward_rows', 'reverse_rows', 'buckets_dense', 'buckets_sparse', 'peak_logical_bytes')} if r and 'counters' in r['stats'] else None, wall=round(time.monotonic() - t, 3)))
    print(json.dumps(out[-1], default=str))
print('ALL_CONTAINED', all(o['contained'] for o in out), 'sparse_buckets_total', sum((o['counters'] or {}).get('buckets_sparse', 0) for o in out), 'certified', sum(1 for o in out if o['status']=='CERTIFIED'), 'zero', sum(1 for o in out if o['status']=='ZERO_EVIDENCE'), 'stops', [o['status'] for o in out if o['status'].startswith('STOP')])
