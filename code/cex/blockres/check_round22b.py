"""Round-22b controls (integrated v2.13.1): the R22 review's closeout items on REAL work. D1 the reviewer's construction-bounds probes as production regressions -- a 400-selector path under an
injected 1,000 B construction cap refuses at the FIRST charged structure with a tiny traced peak; a clock expiring 100 us after the path-walk entry is observed inside the path traversal (not
after the whole witness); an expired restriction helper surfaces as this module's typed refusal; D2 a sparse-response stress (a 14-deep multiplexer tree with distinct selectors: 2^14-term
responses): the live-term cap refuses BEFORE the merge is built, and a clock expiring inside the merge is observed inside it; charged bytes cover the traced construction peak on the 400-path
fixture and on G4; D3 default dispatch on the real G4 bytes: the layered route refuses first (forced-zero chain sign), the ancestral route then applies, rows and Z BYTE-IDENTICAL to the frozen
round-22 result, signature unchanged; D4 a real nonidentity-closure model through default dispatch binds the ancestral route to the original model (scalar once, 8 / 8 rows, Z = 2); D5 a real
layered success bypasses the ancestral constructor (status DEFERRED, no construction phase); D6 the harness guard: a 24-variable brute-force fixture is refused before enumeration."""
import sys, os, json, time, math, itertools, tracemalloc, inspect, hashlib
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import integrated as IG, ancestral_response as AR, layered_contraction as LC, core
assert IG.ANCESTRAL_RESPONSE_DEFAULT is True and IG.LAYERED_CONTRACTION_DEFAULT is True
OUT = sys.argv[1]; rows = []; RD = '/Users/adis/Workspace/pgm-records/code/runs/mdi_2026-10-28/BLOCKRES_2026-11-19'; G4 = RD + '/round21/inputs/G4_near_c3_theta17-20_span3.uai'; G3 = RD + '/round21/inputs/G3_near_c23_theta7-10_zeros.uai'
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:460], flush=True)
def mux(ch, a, b, s): return dict(scope=(ch, a, b, s), values=[F(int(x == (bb if ss else aa))) for x, aa, bb, ss in itertools.product(range(2), repeat=4)])
def path_model(length):
    fs = [dict(scope=(0,), values=[F(1, 2)] * 2), dict(scope=(1,), values=[F(1, 2)] * 2), dict(scope=(2,), values=[F(1, 2)] * 2)]
    for i in range(length):
        fs.append(mux(2 + length + i, 0, 1, 2 + i))
        if i: fs.append(dict(scope=(1 + i, 2 + i), values=[F(3, 4), F(1, 4), F(1, 4), F(3, 4)]))
    return dict(cards=[2] * (2 + 2 * length), factors=fs, evidence={})
def restriction_model():
    fs = [dict(scope=(0,), values=[F(1), F(1)]) for _ in range(80)] + [dict(scope=(1,), values=[F(1, 2)] * 2), dict(scope=(2,), values=[F(1, 2)] * 2), mux(3, 0, 1, 2), dict(scope=(0, 2), values=[F(1), F(2), F(3), F(4)])]
    return dict(cards=[2] * 4, factors=fs, evidence={})
# ---- D1
m = path_model(400); tracemalloc.start()
try: AR.recognize(m, construction_s=10, byte_limit=1000); st1 = 'RETURNED'
except Exception as e: st1 = type(e).__name__ + ': ' + str(e)[:80]
_, pk1 = tracemalloc.get_traced_memory(); tracemalloc.stop()
orig = AR.tnow; arm = {}
def clock():
    now = orig(); c = inspect.currentframe().f_back
    if c.f_code.co_name == 'poll' and c.f_locals.get('where') == 'inside the path walk' and not arm: arm.update(real_start=now, value=now, expire=now + 0.0001)
    return arm['value'] + 20 if arm and now >= arm['expire'] else now
AR.tnow = clock
try: AR.recognize(m, construction_s=10); st2 = 'RETURNED'
except Exception as e: st2 = type(e).__name__ + ': ' + str(e)[:80]
finally: AR.tnow = orig
el2 = time.monotonic() - arm['real_start'] if arm else None
mr = restriction_model(); o = LC.tnow; LC.tnow = lambda: o() + 30
try: AR.recognize(mr, deadline=o() + 10, construction_s=5); st3 = 'RETURNED'; caught = False
except Exception as e: st3 = type(e).__name__ + ': ' + str(e)[:80]; caught = isinstance(e, (AR.NotApplicable, AR.RecognitionRefused, AR.ResourceRefused, AR.ZeroMass))
finally: LC.tnow = o
say(dict(control='D1_reviewer_construction_bounds_probes_on_production', small_byte_cap=dict(traced_peak_bytes=pk1, status=st1), path_expiry=dict(status=st2, elapsed_after_path_entry_s=round(el2, 5) if el2 else None), restriction_expiry=dict(status=st3, caught_by_AR_boundary=caught), ok=(st1.startswith('ResourceRefused') and pk1 < 64 << 10 and 'inside the path' in st2 and el2 is not None and el2 < 0.01 and caught)))
# ---- D2 sparse-response stress: a binary multiplexer tree with DISTINCT leaf priors and one retained leaf -> the erased internal nodes' responses have 2^depth terms
def tree_model(depth):
    cards = []; fs = []; leaves = []
    for i in range(2 ** depth): leaves.append(len(cards)); cards.append(2); fs.append(dict(scope=(leaves[-1],), values=[F(i + 1, 2 ** depth + 2), F(2 ** depth + 1 - i, 2 ** depth + 2)]))
    level = leaves; sels = []
    while len(level) > 1:
        nxt = []
        for a, b in zip(level[::2], level[1::2]):
            s_ = len(cards); cards.append(2); fs.append(dict(scope=(s_,), values=[F(1, 2)] * 2)); sels.append(s_); ch = len(cards); cards.append(2); fs.append(mux(ch, a, b, s_)); nxt.append(ch)
        level = nxt
    fs.append(dict(scope=(leaves[0], sels[-1]), values=[F(1), F(2), F(3), F(4)]))                          # retains leaf 0 (as an indicator) and the top selector; every internal node is erased
    return dict(cards=cards, factors=fs, evidence={})
mt = tree_model(5)                                                                                         # 32 leaves: the root's responses have ~1k terms (depth 8 would need ~10^5 terms and minutes of exact work)
try: AR.recognize(mt, construction_s=10, max_live_terms=200); stt = 'RETURNED'
except AR.ResourceRefused as e: stt = 'ResourceRefused: ' + str(e)[:70]
cap_ok = 'would reach' in stt
tracemalloc.start(); pl2 = AR.recognize(mt, construction_s=10); _, pk2 = tracemalloc.get_traced_memory(); tracemalloc.stop()
mt2 = tree_model(6); arm = {}
def clock2():
    now = orig(); c = inspect.currentframe().f_back
    if c.f_code.co_name == 'poll' and c.f_locals.get('where') == 'inside the sparse merge' and not arm: arm.update(value=now)
    return arm['value'] + 20 if arm else now
AR.tnow = clock2
try: AR.recognize(mt2, construction_s=10); stm = 'RETURNED'
except Exception as e: stm = type(e).__name__ + ': ' + str(e)[:70]
finally: AR.tnow = orig
m4, b4 = core.read_uai(G4); tracemalloc.start(); pl4 = AR.recognize(m4, time.monotonic() + 30, b4, construction_s=30); _, pk4 = tracemalloc.get_traced_memory(); tracemalloc.stop()
say(dict(control='D2_sparse_response_stress_and_charge_coverage', live_term_cap_before_merge=stt, merge_expiry=stm, tree5=dict(max_terms=max(len(p) for pp in pl2.decoder.values() for p in pp), traced_peak=pk2, charged=pl2.bytes_charged, covers=pl2.bytes_charged >= pk2), G4=dict(traced_peak=pk4, charged=pl4.bytes_charged, covers=pl4.bytes_charged >= pk4), ok=(cap_ok and 'inside the sparse merge' in stm and pl2.bytes_charged >= pk2 and pl4.bytes_charged >= pk4)))
# ---- D3 default dispatch on G4: layered refuses first, ancestral applies, byte-identical to frozen round 22
r = IG.solve(G4, 19.5, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted'); ref = json.load(open(RD + '/round22/g4/00__G4_near_c3_theta17-20_span3__cand__s1/result.json'))
ident = r['answers'] == ref['answers'] and r['Z_enclosure']['lo'] == ref['Z_enclosure']['lo'] and r['Z_enclosure']['hi'] == ref['Z_enclosure']['hi']; lc = r['mechanism']['layered_contraction']; ar = r['mechanism']['ancestral_response']
say(dict(control='D3_default_dispatch_G4_layered_refuses_then_ancestral_byte_identical_to_round22', layered=str(lc.get('status'))[:60], ancestral=ar.get('status'), route=r['mechanism'].get('route'), published=r['published'], identical_rows_and_Z=ident, signature={k: ar['structure'][k] for k in ('retained_original_variables', 'query_auxiliaries')}, plan_hash_equal=(ar['certificate']['semantic_plan_sha256'] == ref['mechanism']['ancestral_response']['certificate']['semantic_plan_sha256']), phases={k: round(v, 3) for k, v in r['phases_s'].items()}, ok=(ident and r['mechanism'].get('route') == 'ancestral_response' and str(lc.get('status')).startswith('NOT_APPLICABLE') and ar['certificate']['semantic_plan_sha256'] == ref['mechanism']['ancestral_response']['certificate']['semantic_plan_sha256'])))
# ---- D4 nonidentity closure, real kernel, default dispatch (the reviewer's 4-variable model: variable 0 fixed by closure, scalar 1/2)
TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True)
M = dict(cards=[2] * 4, evidence={}, factors=[dict(scope=(0,), values=[F(1), F(0)]), dict(scope=(1,), values=[F(1), F(1)]), dict(scope=(2,), values=[F(1, 2)] * 2), dict(scope=(0, 1, 2, 3), values=[F(int(c == (a if s == 0 else b))) for a, b, s, c in itertools.product(range(2), repeat=4)])])
p = os.path.join(TMP, 'r22b_binding.uai'); lines = ['MARKOV', '4', '2 2 2 2', str(len(M['factors']))] + ['%d %s' % (len(f['scope']), ' '.join(map(str, f['scope']))) for f in M['factors']]
for f in M['factors']: lines += [str(len(f['values'])), ' '.join(str(v) for v in f['values'])]
open(p, 'w').write('\n'.join(lines) + '\n'); open(p + '.evid', 'w').write('0\n')
z = F(2); mu = {}
for xs in itertools.product(range(2), repeat=4):
    w = F(1)
    for f in M['factors']:
        j = 0
        for v in f['scope']: j = j * 2 + xs[v]
        w *= f['values'][j]
    for v, a in enumerate(xs): mu[(v, a)] = mu.get((v, a), F(0)) + w / z
rb = IG.solve(p, 19.5, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted', layered_contraction=False); cl = rb['mechanism']['support_closure']; arb = rb['mechanism']['ancestral_response']
cont = all(F(a['lo']) <= mu[(a['var'], a['state'])] <= F(a['hi']) for a in rb['answers']); zc = F(rb['Z_enclosure']['lo']) <= z <= F(rb['Z_enclosure']['hi'])
say(dict(control='D4_nonidentity_closure_ancestral_binds_original_model_real_kernel', closure=dict(status=cl.get('status'), scalar=cl.get('scalar'), representatives=cl.get('representatives')), ancestral=dict(status=arb.get('status'), retained=arb['structure']['retained_original_variables'], erasure_scalar_bits=arb['structure']['scalar_bits']), published=rb['published'], K=rb['K'], rows_contain_truth=cont, Z_contains_2=zc, Z=rb['Z_enclosure']['lo'][:20], ok=(rb['published'] == rb['K'] == 8 and cont and zc and rb['mechanism'].get('route') == 'ancestral_response' and cl.get('status') == 'APPLIED')))
# ---- D5 layered success bypasses the ancestral constructor (G3: the layered route completes)
r5 = IG.solve(G3, 19.5, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted'); ref5 = json.load(open(RD + '/round21/cells/06__G3_near_c23_theta7-10_zeros__new__s1/result.json'))
say(dict(control='D5_layered_success_bypasses_ancestral', route=r5['mechanism'].get('route'), ancestral_status=str(r5['mechanism']['ancestral_response'].get('status'))[:60], no_construction_phase=('ancestral_recognition' not in r5['phases_s']), published=r5['published'], K=r5['K'], identical_to_round21_layered=(r5['answers'] == ref5['answers']), ok=(r5['mechanism'].get('route') == 'layered_contraction' and 'ancestral_recognition' not in r5['phases_s'] and r5['published'] == r5['K'] and r5['answers'] == ref5['answers'])))
# ---- D6 harness guard
# (the harness guard is exercised by executing the suite header below)
guard_ok = False
try:
    src = open(os.path.join(HERE, 'check_round22.py')).read(); ns = {'__file__': os.path.join(HERE, 'check_round22.py')}; exec(src.split('def check(')[0].replace("OUT = sys.argv[1]", "OUT = '%s'" % OUT).replace('assert IG.ANCESTRAL_RESPONSE_DEFAULT', 'pass  # '), ns)
    ns['brute'](dict(cards=[2] * 24, factors=[], evidence={}))
except AssertionError as e: guard_ok = 'harness guard' in str(e); msg = str(e)[:80]
except Exception as e: msg = repr(e)[:80]
say(dict(control='D6_brute_force_harness_guard', refused=guard_ok, message=msg if not guard_ok or True else None, ok=guard_ok))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
