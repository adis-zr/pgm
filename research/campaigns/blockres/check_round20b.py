"""Round-20b controls (integrated v2.12.1): the R20 review's two admission defects of the layered constructor, tested on REAL work. A1 the reviewer's constant-clique fixtures: the
PHYSICAL volume certificate equals the executor's actual lowered-scope volumes on the 12-variable probe (4,096 / 2,048 / 8,190 / 4,095; 16,380 rows), the 28-variable fixture is
refused BEFORE the executor under the normal 19.5 s contract and the incumbent publishes 56 / 56 EXACT (every row 1/2, Z = 2^27), the 24-variable fixture at the reviewer's 1.8 s budget
is refused on time and the incumbent publishes 48 / 48 EXACT; A2 the reviewer's Boolean-clique recognition fixtures (161 / 221 variables, one channel + a pairwise Boolean clique):
typed refusal within the allowance + 0.25 s (real computation, no injected clock); A3 storage admission: an over-limit sign system refuses before any dense Fraction allocation (traced
peak small) and a real model with 725 two-variable chains joined by one core refuses by the dimension guard in milliseconds; A4 the reviewer's 80-model exact enumeration (their generator,
production kernel on this host) + the extreme-scale checks: every coordinate and Z enclosed, zero mass typed, excessive range RANGE; A5 linkage_13: the order is IDENTICAL to the frozen
round-20 scored cell (the executor's semantic plan hash of model + order equals the stored certificate's), the physical certificate covers the stored kernel counters, the forecast admits;
A6 the recognition-graph volumes remain available as diagnostics and equal the round-20 values."""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, itertools, random, tracemalloc, gc
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = str(_repo_root())
import pgm.algorithms.block.integrated as IG, pgm.algorithms.block.layered_contraction as LC, pgm.algorithms.structural.core as core, pgm.algorithms.structural.cex_executor as CX
IG.ANCESTRAL_RESPONSE_DEFAULT = False       # (round 22) this suite exercises the layered route; the ancestral-response constructor (which runs first) has its own suite, check_round22.py
assert IG.LAYERED_CONTRACTION_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []
RD = str(_runs_root() / 'mdi_2026-10-28/BLOCKRES_2026-11-19'); PK = os.path.join(RD, 'round20b/REVIEW_PACKET/r20_independent')
LINK = str(_runs_root() / 'mdi_2026-10-28/EXTERNAL_SWEEP_2026-11-06/sources/uai14/prob/linkage_13.uai')
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:460], flush=True)
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def actual_vol(model, order):
    """the reviewer's exact lowered-scope simulation (probe_structure.py)"""
    cards = model['cards']; ev = model.get('evidence', {}); adj = {v: set() for v in range(len(cards)) if v not in ev}
    for f in model['factors']:
        sc = set(f['scope']) - set(ev)
        for v in sc: adj[v] |= sc - {v}
    mp = mo = sp = so = 0
    for v in order:
        nb = adj[v]; p = cards[v] * math.prod(cards[w] for w in nb); mp = max(mp, p); mo = max(mo, p // cards[v]); sp += p; so += p // cards[v]
        for w in nb: adj[w] = (adj[w] | nb) - {w, v}
        del adj[v]
    return dict(max_product_entries=mp, max_output_entries=mo, sum_product_entries=sp, sum_output_entries=so)
def solve(p, budget, **kw): return IG.solve(p, budget, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted', evidence_expansion=False, **kw)
def lc(r): return r['mechanism'].get('layered_contraction') or {}
CX.load(CX.build())                                                                                 # warm the unchanged executor's build before any timed arm
# ---- A1: the reviewer's constant-clique fixtures
m12 = {'cards': [2] * 12, 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [F(9, 10), F(1, 10), F(1, 10), F(9, 10)]}, {'scope': (0,), 'values': [F(1, 3), F(2, 3)]}]}
for a in range(12):
    for b in range(a + 1, 12): m12['factors'].append({'scope': (a, b), 'values': [F(1)] * 4})
p12 = LC.recognize(m12, time.monotonic() + 5); av = actual_vol(m12, p12.order); pv = {k: p12.volume[k] for k in av}; fc12 = LC.forecast(p12, 19)
p28 = os.path.join(PK, 'math/normal_contract/constant_clique28.uai'); p24 = os.path.join(PK, 'math/constant_clique24.uai')
m28, _ = core.read_uai(p28); pl28 = LC.recognize(m28, time.monotonic() + 5); fc28 = LC.forecast(pl28, 19.4)
t0 = time.monotonic(); r28 = solve(p28, 19.5); w28 = time.monotonic() - t0
m24, _ = core.read_uai(p24); pl24 = LC.recognize(m24, time.monotonic() + 5); fc24 = LC.forecast(pl24, 1.78)
t0 = time.monotonic(); r24 = solve(p24, 1.8); w24 = time.monotonic() - t0
def half_exact(r, n): return r['published'] == r['K'] == 2 * n and all(F(a['lo']) == F(a['hi']) == F(a['point']) == F(1, 2) for a in r['answers']) and F(r['Z']) == 2 ** (n - 1)
a1 = dict(probe12=dict(physical=pv, reviewer_actual=av, equal=(pv == av), forecast_rows=fc12['forecast_rows']),
          clique28=dict(physical={k: pl28.volume[k] for k in ('max_product_entries', 'sum_product_entries', 'sum_output_entries')}, forecast_MiB=fc28['forecast_bytes'] >> 20, forecast_s=round(fc28['forecast_kernel_s'], 2), status=str(lc(r28).get('status'))[:90], outcome=r28['outcome'], published=r28['published'], K=r28['K'], Z=r28.get('Z'), wall_s=round(w28, 3), phases=sorted(r28['phases_s']), half_exact=half_exact(r28, 28), before_executor=('executor' not in lc(r28))),
          clique24_at_1p8s=dict(physical={k: pl24.volume[k] for k in ('max_product_entries', 'sum_product_entries')}, forecast_MiB=fc24['forecast_bytes'] >> 20, forecast_s=round(fc24['forecast_kernel_s'], 2), status=str(lc(r24).get('status'))[:90], outcome=r24['outcome'], published=r24['published'], wall_s=round(w24, 3), half_exact=half_exact(r24, 24), before_executor=('executor' not in lc(r24))))
say(dict(control='A1_physical_certificate_refuses_constant_cliques_before_execution_incumbent_exact', **a1, ok=(pv == av and fc12['forecast_rows'] == 2 * av['sum_product_entries'] and str(lc(r28).get('status')).startswith('RESOURCE_REFUSED') and a1['clique28']['before_executor'] and a1['clique28']['half_exact'] and w28 < 2.0 and str(lc(r24).get('status')).startswith('RESOURCE_REFUSED') and a1['clique24_at_1p8s']['before_executor'] and a1['clique24_at_1p8s']['half_exact'])))
# ---- A2: the reviewer's Boolean-clique recognition fixtures (real work)
def clique(n):
    m = {'cards': [2] * (n + 1), 'evidence': {}, 'factors': [{'scope': (0, n), 'values': [F(9, 10), F(1, 10), F(1, 10), F(9, 10)]}]}
    for a in range(n):
        for b in range(a + 1, n): m['factors'].append({'scope': (a, b), 'values': [F(1), F(1), F(1), F(0)]})
    return m
a2 = {}
for n, allow in ((70, 0.05), (160, 0.2), (220, 0.5)):
    m = clique(n); t0 = time.monotonic()
    try: LC.recognize(m, t0 + allow); oc = 'RETURNED'
    except (LC.NotApplicable, LC.RecognitionRefused) as e: oc = type(e).__name__ + ': ' + str(e)[:110]
    el = time.monotonic() - t0; a2['clique_%d' % n] = dict(allowance_s=allow, elapsed_s=round(el, 3), outcome=oc, factors=len(m['factors']), ok=(oc != 'RETURNED' and el <= allow + 0.25))
say(dict(control='A2_boolean_clique_recognition_refuses_near_allowance_real_work', cases=a2, ok=all(v['ok'] for v in a2.values())))
# ---- A3: storage admission before dense exact structures
gc.collect(); tracemalloc.start(); t0 = time.monotonic()
try: LC._rref_nullspace([[0] * 600] * 1000, 600); r3a = 'RETURNED'
except LC.NotApplicable as e: r3a = str(e)[:90]
_, pk3 = tracemalloc.get_traced_memory(); tracemalloc.stop(); el3a = time.monotonic() - t0
nch = 725; cards = [2] * (2 * nch); fs = []
for c in range(nch): fs.append(((2 * c, 2 * c + 1), [F(9, 10), F(1, 10), F(1, 10), F(9, 10)]))
fs.append((tuple(2 * c for c in range(nch))[:0] or (0,), [F(1, 2), F(1, 2)]))
core_vals = None
# one Boolean core joining the first variable of every chain: a parity-free all-ones table would be constant; use a 2-variable Boolean factor chain (0 -- 2 -- 4 ...) which joins all cores
for c in range(nch - 1): fs.append(((2 * c, 2 * c + 2), [F(1), F(1), F(1), F(0)]))
m3 = dict(cards=cards, evidence={}, factors=[dict(scope=sc, values=v) for sc, v in fs]); t0 = time.monotonic()
try: LC.recognize(m3, t0 + 2.0); r3b = 'RETURNED'
except (LC.NotApplicable, LC.RecognitionRefused) as e: r3b = type(e).__name__ + ': ' + str(e)[:110]
el3b = time.monotonic() - t0
say(dict(control='A3_storage_admission_before_dense_exact_structures', direct_rref=dict(outcome=r3a, elapsed_s=round(el3a, 4), traced_peak_bytes=pk3), model_725_chains=dict(outcome=r3b, elapsed_s=round(el3b, 3), chains=nch, factors=len(fs)), ok=('storage admission' in r3a and pk3 < 1 << 20 and 'storage admission' in r3b and el3b < 1.0)))
# ---- A4: the reviewer's exact enumeration (their generator and assertions; the production kernel on this host)
def brute(m):
    z = F(0); nums = [[F(0)] * c for c in m['cards']]
    for xs in itertools.product(*(range(c) for c in m['cards'])):
        if any(xs[v] != a for v, a in m['evidence'].items()): continue
        w = F(1)
        for f in m['factors']:
            k = 0
            for v in f['scope']: k = k * m['cards'][v] + xs[v]
            w *= f['values'][k]
        z += w
        for v, a in enumerate(xs): nums[v][a] += w
    return z, nums
rng = random.Random(20201123); res4 = []; checked = 0; t0 = time.monotonic()
for i in range(80):
    cs = [2, 2, 3, 2, 1, 3]; a = F(rng.randrange(1, 9), 10); fs = [{'scope': (0, 1), 'values': [a, 1 - a, 1 - a, a]}]
    for sc in [(0, 2), (1, 3), (0,), (2, 3)]: fs.append({'scope': sc, 'values': [F(rng.randrange(0, 11), rng.randrange(1, 12)) for _ in range(math.prod(cs[v] for v in sc))]})
    fs.append({'scope': (4,), 'values': [F(2, 3)]}); fs.append({'scope': (), 'values': [F(2) ** ((i % 5 - 2) * 1000)]})
    if i % 4 == 0: fs.append({'scope': (0, 1, 2), 'values': [F(7, 13)] * 12})
    if i % 7 == 0: fs.append(dict(fs[1]))
    ev = {v: rng.randrange(cs[v]) for v in (2, 3, 4, 5) if rng.random() < .5}
    if i % 13 == 0: fs.append({'scope': tuple(ev), 'values': [F(0)] * math.prod(cs[v] for v in ev)})
    m = {'cards': cs, 'factors': fs, 'evidence': ev}; z, nums = brute(m)
    try: p = LC.recognize(m, time.monotonic() + 2)
    except LC.NotApplicable as e: res4.append('NOT_APPLICABLE'); continue
    try: r = LC.execute(p, m, time.monotonic() + 3, 256 << 20, 0)
    except LC.ZeroEvidence:
        assert z == 0, (i, 'false zero'); res4.append('ZERO_CORRECT'); continue
    assert z > 0 and r.Z_lo <= z <= r.Z_hi, (i, 'Z')
    for v in range(len(cs)):
        assert sum(r.points[v]) == 1
        for s_ in range(cs[v]):
            q = nums[v][s_] / z; lo, hi = r.intervals[v][s_]; assert lo <= q <= hi and lo <= r.points[v][s_] <= hi, (i, v, s_); checked += 1
    res4.append('PASS')
ext = []
for exponent in (-4000, 4000):
    s_ = F(2) ** exponent; m = {'cards': [2, 2, 3, 3], 'evidence': {3: 2}, 'factors': [{'scope': (0, 1), 'values': [F(2, 3), F(1, 3), F(1, 3), F(2, 3)]}, {'scope': (0, 2), 'values': [s_ * F(v, 7) for v in [1, 2, 0, 3, 4, 5]]}, {'scope': (1,), 'values': [F(2, 9), F(7, 9)]}, {'scope': (3,), 'values': [F(1, 11), F(2, 11), F(7, 11)]}, {'scope': (), 'values': [F(13, 17)]}, {'scope': (), 'values': [F(19, 23)]}]}
    p = LC.recognize(m, time.monotonic() + 2); r = LC.execute(p, m, time.monotonic() + 3, 256 << 20, 0); z, num = brute(m); assert r.Z_lo <= z <= r.Z_hi
    for v, c in enumerate(m['cards']):
        for s2 in range(c): assert r.intervals[v][s2][0] <= num[v][s2] / z <= r.intervals[v][s2][1]
    ext.append(exponent)
m = {'cards': [2, 2], 'evidence': {}, 'factors': [{'scope': (0, 1), 'values': [F(2, 3), F(1, 3), F(1, 3), F(2, 3)]}, {'scope': (0,), 'values': [F(1), F(2) ** -2000]}]}; p = LC.recognize(m, time.monotonic() + 2); rng_kind = None
try: LC.execute(p, m, time.monotonic() + 3, 256 << 20, 0)
except LC.ExecutorRefused as e: rng_kind = e.kind
from collections import Counter
say(dict(control='A4_reviewer_exact_enumeration_on_this_host', cases=dict(Counter(res4)), coordinates_checked=checked, extreme_scales_ok=ext, excessive_range=rng_kind, elapsed_s=round(time.monotonic() - t0, 2), ok=(Counter(res4)['PASS'] == 62 and Counter(res4)['ZERO_CORRECT'] == 10 and Counter(res4)['NOT_APPLICABLE'] == 8 and checked == 806 and len(ext) == 2 and rng_kind == 'RANGE')))
# ---- A5 / A6: linkage_13 order identity with the frozen round-20 cell + physical coverage + diagnostics
m, b = core.read_uai(LINK); t0 = time.monotonic(); pl = LC.recognize(m, time.monotonic() + IG.LAYERED_RECOGNITION_S, b); rec_s = time.monotonic() - t0
d20 = json.load(open(os.path.join(RD, 'round20/linkage/00__linkage_13__cand__s1/result.json'))); l20 = d20['mechanism']['layered_contraction']; ex20 = l20['executor']
words, vals, meta = CX.lower(m, pl.order, 0.25, time.monotonic() + 10, budget=CX.HostBudget(1 << 62, {})); del words, vals
same_plan = meta['semantic_plan_sha256'] == l20['certificate']['semantic_plan_sha256']; fc = LC.forecast(pl, 19.1); rss = IG.SE.rss_bytes_now(); budget_b = min(IG.LAYERED_BYTE_CAP, IG.USABLE_BYTES - rss)
say(dict(control='A5_linkage_order_identical_to_frozen_round20_physical_covers_kernel_forecast_admits', recognition_s=round(rec_s, 3), semantic_plan_sha256_equal=same_plan, physical=pl.volume, kernel_round20=dict(forward_rows=ex20['forward_rows'], max_live_message_entries=ex20['max_live_message_entries'], peak_logical_MiB=ex20['kernel_peak_logical_bytes'] >> 20), covers=dict(rows=pl.volume['sum_product_entries'] >= ex20['forward_rows'], messages=pl.volume['sum_output_entries'] >= ex20['max_live_message_entries'], bytes=fc['forecast_bytes'] >= ex20['kernel_peak_logical_bytes']), forecast=fc, admitted=(fc['forecast_bytes'] <= budget_b and fc['forecast_kernel_s'] <= fc['remaining_s']), ok=(same_plan and rec_s < IG.LAYERED_RECOGNITION_S and pl.volume['sum_product_entries'] >= ex20['forward_rows'] and pl.volume['sum_output_entries'] >= ex20['max_live_message_entries'] and fc['forecast_bytes'] >= ex20['kernel_peak_logical_bytes'] and fc['forecast_bytes'] <= budget_b and fc['forecast_kernel_s'] <= fc['remaining_s'] and pl.volume['max_product_entries'] == 1 << 21)))
v20 = l20['volume']; same_diag = all(pl.volume_recognition[k] == v20[k] for k in ('max_product_entries', 'max_output_entries', 'sum_product_entries', 'sum_output_entries', 'active_variables'))
say(dict(control='A6_recognition_graph_volumes_remain_as_diagnostics_equal_round20', recognition_graph=pl.volume_recognition, round20_volume=v20, ok=same_diag))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
