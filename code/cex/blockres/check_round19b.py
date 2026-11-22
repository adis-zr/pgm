"""Round-19b controls (integrated v2.11.1): bounded execution of the signed evidence-expansion route, testing REAL work (not injected exceptions). B1 few findings / many gates (the
reviewer's 3,000-gate model): the revised estimate covers the traced incremental peak of execute() + row building, and a budget below the estimate is refused BEFORE materialisation (no
exponential state allocated: traced peak small); B2 actual expiration inside a long prefix walk (3,000 gates, 1 ms deadline): DeadlineRefused, no masses; B3 actual expiration inside dense
recognition (1,000 roots x 1,000 direct terminals, the reviewer's model, 100 ms allowance): RecognitionRefused, no plan; B4 RSS units: rusage_to_bytes converts KiB on Linux and bytes on
macOS, rss_bytes_now returns bytes consistent with the process, and the dispatcher grants at most min(256 MiB, USABLE - rss) (injected USABLE just above the current RSS -> a refusal
whose state is released; injected USABLE below RSS -> budget 0 -> refusal); B5 end to end on the supplied fixtures and the T2 scalar fixture: rows unchanged, zero evidence no rows,
closure decoder / scalar not applied twice; B6 a deadline inside solve's output stage returns the established DEADLINE outcome with nothing published."""
import sys, os, json, time, math, gc, tracemalloc, itertools
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import integrated as IG, signed_evidence as SE, core
assert IG.EVIDENCE_EXPANSION_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); rows = []
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
def long_chain(g):
    fs = [dict(scope=[r], values=[F(1, 2), F(1, 2)]) for r in range(2)]; prev = 1
    for j in range(g):
        z = [F(1), F(1, 2) if j == 0 else F(0), F(1, 2), F(1, 4) if j == 0 else F(0)]; fs.append(dict(scope=[j + 2, 0, prev], values=z + [1 - x for x in z])); prev = j + 2
    fs.append(dict(scope=[g + 2, prev], values=[F(1), F(0), F(0), F(1)])); return dict(cards=[2] * (g + 3), factors=fs, evidence={g + 2: 1})
def queries(model): return [(v, s) for v in range(len(model['cards'])) if v not in model['evidence'] for s in (0, 1)]
# ---- B1
model = long_chain(3000); qs = queries(model); plan = SE.recognize(model, qs, {}, math.inf); est = SE.estimate(plan, len(qs)); gc.collect(); tracemalloc.start()
masses = SE.execute(plan, math.inf, est['retained_bytes_estimate'], len(qs)); rws = SE.dyadic_rows(masses, qs); cur, peak = tracemalloc.get_traced_memory(); tracemalloc.stop(); del masses, rws; gc.collect()
tracemalloc.start(); refused = None
try: SE.execute(plan, math.inf, est['retained_bytes_estimate'] // 2, len(qs))
except SE.ResourceRefused as e: refused = str(e)[:50]
_, peak_refused = tracemalloc.get_traced_memory(); tracemalloc.stop()
say(dict(control='B1_few_findings_many_gates_estimate_covers_peak_and_refuses_below', gates=3000, roots=2, findings=1, estimate_bytes=est['retained_bytes_estimate'], phase_exp=est['phase_exponential_bytes'], phase_out=est['phase_output_bytes'], traced_peak_bytes=peak, ratio=round(est['retained_bytes_estimate'] / peak, 2), refused_at_half=refused, traced_peak_when_refused=peak_refused, ok=(peak <= est['retained_bytes_estimate'] and refused is not None and peak_refused < 64 << 10)))
# ---- B2: real expiration inside the prefix walk
t0 = time.monotonic(); status = None
try: SE.execute(plan, t0 + 0.001, 256 << 20, len(qs)); status = 'RETURNED_MASSES'
except SE.DeadlineRefused as e: status = 'DEADLINE_REFUSED: ' + str(e)[:60]
el = time.monotonic() - t0
say(dict(control='B2_real_expiration_inside_prefix_walk', allowance_s=0.001, elapsed_s=round(el, 4), status=status, ok=(status.startswith('DEADLINE_REFUSED') and el < 0.5)))
# ---- B3: real expiration inside dense recognition (the reviewer's 1,000 x 1,000 model); also the structural non-candidate guard
n = 1000; fs = [dict(scope=[r], values=[F(1, 2), F(1, 2)]) for r in range(n)] + [dict(scope=[n + r, r], values=[F(1), F(1, 2), F(0), F(1, 2)]) for r in range(n)]
many = dict(cards=[2] * (2 * n), factors=fs, evidence={n + r: 1 for r in range(n)}); t0 = time.monotonic(); status = None
try: SE.recognize(many, queries(many), {}, t0 + 0.1); status = 'RECOGNIZED'
except SE.RecognitionRefused as e: status = 'RECOGNITION_REFUSED: ' + str(e)[:50]
except SE.NotApplicable as e: status = 'NOT_APPLICABLE: ' + str(e)[:60]
el = time.monotonic() - t0
say(dict(control='B3_dense_recognition_bounded_or_structural_refusal', roots=n, findings=n, allowance_s=0.1, elapsed_s=round(el, 4), status=status, ok=((status.startswith('RECOGNITION_REFUSED') and el < 0.3) or status.startswith('NOT_APPLICABLE'))))
# ---- B4: RSS units and headroom admission
import resource
raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; conv_linux = SE.rusage_to_bytes(1024, 'linux'); conv_mac = SE.rusage_to_bytes(1024, 'darwin'); now = SE.rss_bytes_now(); peak_conv = SE.rusage_to_bytes(raw, sys.platform)
p = os.path.join(TMP, 'tiny_noisy_or_0.uai'); saved = IG.USABLE_BYTES
IG.USABLE_BYTES = now + 4096                                                              # headroom of 4 KiB: the plan's estimate (>= 64 KiB fixed) cannot fit -> RESOURCE_REFUSED, then the existing route completes
try: r_tight = IG.solve(p, 6.0, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False)
finally: IG.USABLE_BYTES = saved
IG.USABLE_BYTES = max(1, now // 2)                                                         # usable below the current RSS -> budget 0
try: r_zero = IG.solve(p, 6.0, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False)
finally: IG.USABLE_BYTES = saved
e_t = (r_tight['mechanism'].get('evidence_expansion') or {}); e_z = (r_zero['mechanism'].get('evidence_expansion') or {})
say(dict(control='B4_rss_units_and_headroom_admission', linux_1024_kib_to_bytes=conv_linux, darwin_1024_to_bytes=conv_mac, rss_now_bytes=now, peak_rusage_bytes=peak_conv, now_le_peak=(now <= peak_conv * 1.05), tight=dict(status=str(e_t.get('status'))[:40], budget=e_t.get('workspace_budget_bytes'), outcome=r_tight['outcome'], published=r_tight['published'], K=r_tight['K']), zero=dict(status=str(e_z.get('status'))[:40], budget=e_z.get('workspace_budget_bytes'), outcome=r_zero['outcome']), ok=(conv_linux == 1024 * 1024 and conv_mac == 1024 and now <= peak_conv * 1.05 and str(e_t.get('status', '')).startswith('RESOURCE_REFUSED') and (e_t.get('workspace_budget_bytes') or 0) <= 4096 and r_tight['published'] == r_tight['K'] and str(e_z.get('status', '')).startswith('RESOURCE_REFUSED') and e_z.get('workspace_budget_bytes') == 0 and r_zero['published'] == r_zero['K'])))
# ---- B5: end-to-end rows unchanged vs the R19 production oracle outputs; zero evidence no rows; T2 scalar fixture once
def brute(p):
    model, _ = core.read_uai(p); cards = model['cards']; n = len(cards); ev = model['evidence']; z = F(0); num = {}
    for xs in itertools.product(*(range(c) for c in cards)):
        if any(xs[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in model['factors']:
            ix = 0
            for v in f['scope']: ix = ix * cards[v] + xs[v]
            w *= f['values'][ix]
        if w == 0: continue
        z += w
        for v in range(n):
            if v not in ev: num[(v, xs[v])] = num.get((v, xs[v]), F(0)) + w
    return z, {k: v / z for k, v in num.items()} if z else None
ok5 = True; det = []
for k in range(3):
    p = os.path.join(TMP, 'tiny_noisy_or_%d.uai' % k); r = IG.solve(p, 6.0, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False); z, tv = brute(p)
    good = r['published'] == r['K'] and F(r['Z']) == z and all(F(a['lo']) <= tv.get((a['var'], a['state']), F(0)) <= F(a['hi']) for a in r['answers']) and (r['mechanism'].get('evidence_expansion') or {}).get('status') == 'APPLIED'; ok5 &= good; det.append(good)
pz = os.path.join(TMP, 'r19_t3_zero.uai'); rz = IG.solve(pz, 6.0, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False, support_closure=False)
p2 = os.path.join(TMP, 'r19_t2_scalar.uai'); r2 = IG.solve(p2, 6.0, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False); z2, tv2 = brute(p2); seen = [(a['var'], a['state']) for a in r2['answers']]
good2 = F(r2['Z']) == z2 and len(seen) == len(set(seen)) == r2['K'] == r2['published'] and all(F(a['lo']) <= tv2.get((a['var'], a['state']), F(0)) <= F(a['hi']) for a in r2['answers'])
say(dict(control='B5_end_to_end_rows_unchanged_zero_no_rows_scalar_once', fixtures_ok=det, zero=dict(outcome=rz['outcome'], published=rz['published']), scalar_fixture_ok=good2, ok=(ok5 and rz['outcome'] == 'ZERO_EVIDENCE' and rz['published'] == 0 and good2)))
# ---- B6: the output stage is bounded by the REAL guards in dyadic_rows (per-512 poll + final guard): (a) an expired deadline at the call builds no row; (b) inside a real solve on the
#      3,000-gate model, the clock is advanced past the deadline right after execute() returns (time injection only; the guard code and the DEADLINE outcome path are the production ones):
#      nothing is published and the established DEADLINE outcome is returned, with no fallback work
lines = ['MARKOV', str(len(model['cards'])), ' '.join('2' for _ in model['cards']), str(len(model['factors']))]
for f in model['factors']: lines.append('%d %s' % (len(f['scope']), ' '.join(map(str, f['scope']))))
for f in model['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(v) for v in f['values']))
p6 = os.path.join(TMP, 'r19b_chain3000.uai'); open(p6, 'w').write('\n'.join(lines) + '\n'); open(p6 + '.evid', 'w').write('1 %d 1\n' % (len(model['cards']) - 1))
m6 = SE.execute(plan, math.inf, 256 << 20, len(qs)); raised = None
try: SE.dyadic_rows(m6, qs, deadline=-math.inf)
except SE.DeadlineRefused as e: raised = str(e)[:50]
r_full = IG.solve(p6, 19.5, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted')
orig_x = SE.execute; orig_t = SE.tnow; state = dict(done=False)
def exec_then_expire(*a, **k):
    out = orig_x(*a, **k); state['done'] = True; return out
def clock():
    return orig_t() + (1000.0 if state['done'] else 0.0)
SE.execute = exec_then_expire; SE.tnow = clock; IG_tnow = IG.tnow; IG.tnow = clock
try: r6 = IG.solve(p6, 19.5, table_cap=1 << 18, enum_cap=1 << 16, mb_cap=1 << 24, route='auto', schedule='targeted')
finally: SE.execute = orig_x; SE.tnow = orig_t; IG.tnow = IG_tnow
e6 = r6['mechanism'].get('evidence_expansion') or {}
say(dict(control='B6_output_stage_guarded_deadline_outcome_nothing_published', direct_expired_call=raised, full=dict(outcome=r_full['outcome'], published=r_full['published'], K=r_full['K'], phases={k: round(v, 3) for k, v in r_full['phases_s'].items() if v > 0.001}), expired_after_evaluation=dict(outcome=r6['outcome'], published=r6['published'], expansion=str(e6.get('status'))[:60], deadline_phase=r6.get('deadline_phase'), phases_after=[k for k in r6['phases_s'] if k in ('integerize', 'contract', 'mb_construct')]), ok=(raised is not None and r_full['outcome'] == 'COMPLETE' and r_full['published'] == r_full['K'] and r6['published'] == 0 and r6['outcome'] == 'DEADLINE' and str(e6.get('status', '')).startswith('DEADLINE_REFUSED') and not any(k in r6['phases_s'] for k in ('integerize', 'contract', 'mb_construct')))))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
