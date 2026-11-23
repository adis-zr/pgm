"""Round-12 controls (integrated v2.8): the reviewer's forced-shared UNDERFLOW adversary as a publication test (must REFUSE, never publish a false interval), a milder range case that
must compute and contain the exact truth, shared conditional responses vs an INDEPENDENT exact-rational computation on supported rows (not two float paths), zero-mass boundary rows,
the live-workspace bound of the shared path (tracemalloc peak <= the trace-simulated bound) incl. the reviewer's 15 / 40-step chains, a REAL ladder descent under an injected
usable-memory limit with exhaustive support / cap validation of the chosen proposal, a deadline inside one shared block, active-row + unique-boundary evaluation vs the full
evaluation on identical draws (chunked, identical certificate state), and a valid completed prefix preserved under a mid-stream range refusal.
Independent oracle = cex/cqr/oracle (enumeration / bucket elimination over the original model)."""
import sys, os, json, random, time, math, itertools, tracemalloc, tempfile
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
IG.EVIDENCE_EXPANSION_DEFAULT = False       # (round 19) this suite exercises its own mechanism; the evidence-expansion operator has its own suite, check_round19.py
IG.LAYERED_CONTRACTION_DEFAULT = False      # (round 20) this suite exercises its own mechanism; the layered-contraction constructor has its own suite, check_round20.py
IG.ANCESTRAL_RESPONSE_DEFAULT = False       # (round 22) this suite exercises its own mechanism; the ancestral-response constructor has its own suite, check_round22.py
IG.SUPPORT_CLOSURE_DEFAULT = False          # (round 18) this suite exercises the FROZEN comparator path (v2.9.4 behaviour); the closure has its own suite, check_round18.py
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); EPS = F(1, 200); rows = []; rng = random.Random(1201)
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def rnd(n, zeros=0.0, lo=1, hi=9): return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(n)]
def truth(p):
    t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); return t, r, {(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])}
def contained(res, tv):
    n = 0; miss = []
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi = F(a['lo']), F(a['hi'])
        if not (F(0) <= lo <= hi <= 1) or not (lo <= tr <= hi): miss.append((a['var'], a['state'], str(lo), str(hi), str(tr)))
    return n, miss
def shared_solve(p, budget, **kw):
    saved = IG.RECOVERY_BYTE_BUDGET; IG.RECOVERY_BYTE_BUDGET = 0
    try: return IG.solve(p, budget, **kw)
    finally: IG.RECOVERY_BYTE_BUDGET = saved
# ---- U1: the reviewer's underflow adversary (H = 2^600 twice: the four-factor product is 2^-1200 on both states of x); truth 1/2 everywhere; forced shared path
H = 1 << 600; fac = [((0, 1), [1, 1, H, H]), ((0, 1), [H, H, 1, 1])] * 2 + [((a, b), [1, 1, 1, 1]) for a, b in [(1, 2), (1, 3), (2, 3)]]
p = write_uai('u1_underflow', [2, 2, 2, 2], fac); r = shared_solve(p, 5.0, table_cap=2, enum_cap=0, mb_cap=64, force_approx=True, route='pac', schedule='targeted', crosscheck=False)
bad = [a for a in r['answers'] if a['guarantee'] != 'NOT_PUBLISHED' and not F(a['lo']) <= F(1, 2) <= F(a['hi'])]
say(dict(control='U1_forced_shared_underflow_adversary_refused_not_published', outcome=r['outcome'], published=r['published'], false_publications=len(bad), refusal=str(r.get('refusal'))[:160], representation=r['mechanism'].get('response_representation'), ok=(len(bad) == 0 and r['outcome'] == 'NUMERIC_RANGE_REFUSED')))
# ---- U2: the same structure with H = 2^200 (four-factor product 2^-400 >= 2^-1000): must compute on the shared path and contain the exact truth (oracle)
H2 = 1 << 200; fac2 = [((0, 1), [1, 2, H2, 3 * H2]), ((0, 1), [H2, H2, 1, 2])] * 2 + [((a, b), rnd(4)) for a, b in [(1, 2), (1, 3), (2, 3)]]
p2 = write_uai('u2_milder_range', [2, 2, 2, 2], fac2); t2, _, tv2 = truth(p2); r2 = shared_solve(p2, 8.0, table_cap=2, enum_cap=0, mb_cap=64, force_approx=True, route='pac', schedule='targeted', crosscheck=False); n2, miss2 = contained(r2, tv2)
say(dict(control='U2_milder_range_computes_on_shared_path_and_contains', outcome=r2['outcome'], published=n2, K=r2['K'], misses=len(miss2), representation=r2['mechanism'].get('response_representation'), draws=r2['mechanism'].get('draws'), ok=(not miss2 and n2 == r2['K'] and r2['mechanism'].get('response_representation') == 'shared')))
# ---- U3: shared conditional responses vs an INDEPENDENT exact-rational computation (Fractions over the original integer factors) on every supported boundary row; zero-mass rows
nS = 5; cards = [2] * nS + [3] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(4, zeros=0.15)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.1))); facs.append(((y0, y1), rnd(9, zeros=0.1)))
p3 = write_uai('u3_shared_vs_exact', cards, facs, evidence={nS + 3: 1}); model, _ = BR.core.read_uai(p3); cards = model['cards']; fns, c, sc, m, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards, 1 << 3, time.monotonic() + 10, st, tr, od) if f.scope]; step_of = {v: i for i, (v, _) in enumerate(tr)}; trace_var = {i: v for i, (v, _) in enumerate(tr)}; cache = {}
def conv(f):
    if id(f) not in cache: cache[id(f)] = IG.ft_from_int(f, cards)
    return cache[id(f)]
blocks = [conv(f) for f in live]; S = sorted({v for b in blocks for v in b.scope}); pos = {v: i for i, v in enumerate(S)}
Sb = np.array(list(itertools.product(*(range(cards[v]) for v in S))), dtype=np.int64); worst = F(0); cmp_ = 0; zero_rows = 0; zero_rows_ok = True; cols_checked = 0
for i, b in enumerate(live):
    if not b.interior: continue
    bf = [f for f in fns if f.facs <= b.facs]; sb = IG.SharedBlock(b, [conv(f) for f in bf], [trace_var[s_] for s_ in sorted(step_of[u] for u in b.interior)], cards, pos); fsh, root, Er = sb.responses(Sb)
    ivars = sorted(set().union(*(set(f.scope) for f in bf)) - set(b.scope))
    for ri, srow in enumerate(Sb.tolist()):
        fixed = {v: srow[pos[v]] for v in b.scope}; num = {}; Z = 0
        for ass in itertools.product(*(range(cards[v]) for v in ivars)):
            full = dict(fixed); full.update(zip(ivars, ass)); w = 1
            for f in bf: w *= int(np.asarray(f.arr, dtype=object)[tuple(full[u] for u in f.scope)])
            Z += w
            for v in b.interior: num[(v, full[v])] = num.get((v, full[v]), 0) + w
        if Z == 0:
            zero_rows += 1
            if root[ri] != 0: zero_rows_ok = False
            continue
        for ci, (v, a) in enumerate(sb.cols):
            ex = F(num.get((v, a), 0), Z); got = F(float(fsh[ri, ci])); worst = max(worst, abs(got - ex)); cmp_ += 1
            if abs(got - ex) > sb.rho_f + F(1, 1 << 40): cols_checked += 0
    cols_checked += len(sb.cols)
say(dict(control='U3_shared_responses_vs_independent_exact_rational', boundary_rows=int(Sb.shape[0]), compared=cmp_, worst_abs_difference=float(worst), declared_rho_f=float(sb.rho_f), zero_mass_rows=zero_rows, zero_rows_root_zero=zero_rows_ok, ok=(cmp_ > 0 and worst <= sb.rho_f + F(1, 1 << 40) and zero_rows_ok)))
# ---- M1: live-workspace bound: the reviewer's chains (15 / 40 steps, width 10, B = 128) and a random block; tracemalloc peak of responses() <= B x bytes_per_sample
for steps_ in (15, 40):
    width, B = 10, 128; n = steps_ + width - 1; cards_ = [2] * n; boundary = tuple(range(steps_, n))
    factors = [IG.FT(tuple(range(i, i + width)), np.ones([2] * width), 0, F(0)) for i in range(steps_)]
    block = BR.Fn(boundary, np.full([2] * len(boundary), 1 << steps_, dtype=object), range(steps_), range(steps_)); pos_ = {v: i for i, v in enumerate(boundary)}
    sb_ = IG.SharedBlock(block, factors, range(steps_), cards_, pos_); S_ = np.zeros((B, len(boundary)), dtype=np.int64)
    tracemalloc.start(); f_, _, _ = sb_.responses(S_); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
    say(dict(control='M1_live_workspace_bound_chain_%d_steps' % steps_, B=B, bound_MiB=round(B * sb_.bytes_per_sample / 2 ** 20, 2), measured_peak_MiB=round(peak / 2 ** 20, 2), old_formula_MiB=round(B * 8 * 3 * sb_.max_union / 2 ** 20, 2), response_error=float(np.abs(f_ - 0.5).max()), ok=(peak <= B * sb_.bytes_per_sample and float(np.abs(f_ - 0.5).max()) == 0.0)))
tracemalloc.start(); fsh2, _, _ = sb.responses(Sb[:64]); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
say(dict(control='M1_live_workspace_bound_random_block', B=64, bound_MiB=round(64 * sb.bytes_per_sample / 2 ** 20, 3), measured_peak_MiB=round(peak / 2 ** 20, 3), ok=(peak <= 64 * sb.bytes_per_sample)))
# ---- M2: a REAL ladder descent: 16 binary variables (exhaustively checkable); the dense budget, batch budget and headroom are injected small and the usable limit is set from the
#      planner itself so that cap 2^16 (unsplit) does NOT fit while a lower cap does; the chosen cap must drop, the run must reach the sampler and publish contained intervals, and the
#      chosen proposal must pass an EXHAUSTIVE support / cap validation (every separator assignment with z > 0 has q > 0 and z / (q U_cap) <= 1 + 2 rho_X)
p4 = write_uai('m2_ladder', [2] * 16, [((i, j), rnd(4)) for i in range(16) for j in range(i + 1, 16) if (i * 7 + j) % 3 != 0]); t4, _, tv4 = truth(p4)
model4, _ = BR.core.read_uai(p4); cards4 = model4['cards']; fns4, c4, sc4, m4, fl4 = BR.integerize(model4); tr4 = []; od4 = []; st4 = dict(elim_work=0, eliminations=0, query_work=0)
live4 = [f for f in BR.contract(fns4, cards4, 0, time.monotonic() + 10, st4, tr4, od4) if f.scope]; blocks4 = [IG.ft_from_int(f, cards4) for f in live4]
saved = (IG.USABLE_BYTES, IG.RECOVERY_BYTE_BUDGET, IG.BATCH_BUDGET, IG.PROCESS_HEADROOM_BYTES, IG.RESPONSE_CACHE_BUDGET); IG.RECOVERY_BYTE_BUDGET = 0; IG.BATCH_BUDGET = 256 << 10; IG.PROCESS_HEADROOM_BYTES = 0; IG.RESPONSE_CACHE_BUDGET = 0   # (round 16: the response cache is a PAC-peak term too)
base4 = sum(b.M.nbytes for b in blocks4) + sum(f.arr.size * 48 for f in fns4)
plans = {cap: IG.mb_plan([b.scope for b in blocks4], cards4, cap) for cap in (1 << 12, 1 << 10)}
need = {cap: max(base4 + pl['forward_bytes'] + pl['peak_step_bytes'], base4 + pl['log_bytes'] + IG.BATCH_BUDGET) for cap, pl in plans.items()}
assert need[1 << 10] < need[1 << 12], need
IG.USABLE_BYTES = (need[1 << 12] + need[1 << 10]) // 2                                                              # between the two: every cap >= 2^12 (same unsplit plan) must fail, 2^10 (5 splits) must fit
try: r4 = IG.solve(p4, 8.0, force_approx=True, table_cap=0, enum_cap=0, mb_cap=1 << 24, route='pac', schedule='targeted')
finally: IG.USABLE_BYTES, IG.RECOVERY_BYTE_BUDGET, IG.BATCH_BUDGET, IG.PROCESS_HEADROOM_BYTES, IG.RESPONSE_CACHE_BUDGET = saved
mp = r4['mechanism'].get('memory_policy') or {}; n4, miss4 = contained(r4, tv4)
mbp4 = IG.MBFloat(blocks4, cards4, mp.get('cap_used') or 1, time.monotonic() + 20); mbp4.prepare_sampler(release_forward=False); S4 = sorted({v for b in blocks4 for v in b.scope}); pos4 = {v: i for i, v in enumerate(S4)}
E_tot4 = sum(b.e for b in blocks4) - mbp4.E_U; wid4 = IG.numerical_widening(blocks4, mbp4, [], len(S4), max(cards4), E_tot4); rho_X4 = IG.fup(wid4['rho_X']); rho_cap4 = IG.fup(wid4['rho_cap']); logU_capf4 = IG.up(mbp4.logU_f + IG.up(math.log2(1.0 + rho_cap4)) + 2 ** -40)
Sall4 = np.array(list(itertools.product(*(range(cards4[v]) for v in S4))), dtype=np.int64); logq4, _ = mbp4.logq_given(Sall4, pos4)
logz4 = np.zeros(Sall4.shape[0])
for b in blocks4:
    idx = np.zeros(Sall4.shape[0], dtype=np.int64); s_ = 1
    for u in reversed(b.scope): idx += Sall4[:, pos4[u]] * s_; s_ *= cards4[u]
    with np.errstate(divide='ignore'): logz4 += np.where(b.M.reshape(-1)[idx] > 0, np.log2(np.maximum(b.M.reshape(-1)[idx], 1e-300)), -np.inf)
posm = np.isfinite(logz4); bad_support = int((posm & ~np.isfinite(logq4)).sum()); okm = posm & np.isfinite(logq4); worst_X = float(np.exp2((logz4[okm] - logq4[okm] - logU_capf4) + float(E_tot4)).max()) if okm.any() else -1.0
say(dict(control='M2_injected_usable_limit_forces_ladder_descent_exhaustive_cap', outcome=r4['outcome'], cap_requested=mp.get('cap_requested'), cap_used=mp.get('cap_used'), usable_MiB=round((mp.get('usable_bytes') or 0) / 2 ** 20, 2), ladder=[(t_['cap'], t_['fits']) for t_ in (mp.get('ladder_tried') or [])], published=n4, K=r4['K'], misses=len(miss4), draws=r4['mechanism'].get('draws'), splits=r4['mechanism'].get('mb_splits'), positive_assignments=int(posm.sum()), support_violations=bad_support, max_X_analysed=worst_X, cap_tol=1 + 2 * rho_X4, ok=(mp.get('cap_used') == (1 << 10) and len(mp.get('ladder_tried') or []) == 8 and not miss4 and (r4['mechanism'].get('draws') or 0) > 0 and bad_support == 0 and worst_X <= 1 + 2 * rho_X4)))
# ---- D1: a deadline INSIDE one shared block: responses(S, deadline) must raise Deadline promptly (no full-block overrun) on a block whose evaluation takes >> the remaining time
t_ = time.monotonic(); raised = None
try: sb_.responses(np.zeros((2048, len(boundary)), dtype=np.int64), time.monotonic() + 0.005)
except IG.Deadline as e: raised = str(e)
dt = time.monotonic() - t_
t_full = time.monotonic(); sb_.responses(np.zeros((2048, len(boundary)), dtype=np.int64)); t_full = time.monotonic() - t_full
say(dict(control='D1_deadline_polled_inside_shared_block', raised=raised, returned_after_s=round(dt, 4), full_evaluation_s=round(t_full, 4), ok=(raised is not None and dt < max(0.25, 0.5 * t_full))))
# ---- A1: active-row + unique-boundary evaluation vs the full evaluation on IDENTICAL draws: the response matrix must agree exactly on active rows (chunked in 3 microbatches)
rng_np = np.random.default_rng(7); Sb_r = Sb[rng_np.integers(0, Sb.shape[0], size=300)]; X_r = rng_np.random(300); X_r[rng_np.random(300) < 0.4] = 0.0
f_full, root_r, _ = sb.responses(Sb_r); act = np.nonzero(X_r > 0)[0]; bcols = [pos[u] for u in sb.bvars]; uniq, inv = np.unique(Sb_r[act][:, bcols], axis=0, return_inverse=True)
Su = np.zeros((uniq.shape[0], Sb_r.shape[1]), dtype=np.int64); Su[:, bcols] = uniq; fu = np.zeros((uniq.shape[0], len(sb.cols))); chunk = max(1, uniq.shape[0] // 3 + 1)
for c0 in range(0, uniq.shape[0], chunk): fu[c0:c0 + chunk] = sb.responses(Su[c0:c0 + chunk])[0]
f_act = np.zeros_like(f_full); f_act[act] = fu[inv.reshape(-1)]
diff_active = float(np.abs(f_act[act] - f_full[act]).max()) if act.size else 0.0
# certificate contributions: X f and X^2 f identical with the zero response on inactive rows
c1 = IG.Certificate(len(sb.cols), 1e-6, 2 ** -30, 1 / 200, 'targeted'); c2 = IG.Certificate(len(sb.cols), 1e-6, 2 ** -30, 1 / 200, 'targeted'); c1.update_batch(X_r, f_full); c2.update_batch(X_r, f_act)
same_cert = all(np.array_equal(getattr(c1, k), getattr(c2, k)) if isinstance(getattr(c1, k), np.ndarray) else getattr(c1, k) == getattr(c2, k) for k in ('SA', 'SB', 'SXX', 'SXXf', 'SXXff', 'A', 'B', 'Lam', 'Psi', 'P', 'Q', 'Qabs', 'R', 't'))
say(dict(control='A1_active_unique_chunked_equals_full_evaluation_and_certificate', draws=300, active=int(act.size), unique_active=int(uniq.shape[0]), chunks=int(math.ceil(uniq.shape[0] / chunk)), max_response_difference_active=diff_active, certificate_state_identical=same_cert, ok=(diff_active == 0.0 and same_cert)))
# ---- P1: a valid completed prefix is preserved under a mid-stream refusal: run the U3 model shared with a tiny budget to completion, then force a RangeRefused on the 3rd batch
t3, _, tv3 = truth(p3); orig = IG.evaluate_shared; calls = [0]
def flaky(*a, **k):                                                     # (round 16) injected at the shared-evaluation call (one per shared block per batch; 5 shared blocks): the 12th call is inside the 3rd batch
    calls[0] += 1
    if calls[0] == 12: raise IG.RangeRefused('injected range refusal')
    return orig(*a, **k)
IG.evaluate_shared = flaky
try: r5 = shared_solve(p3, 10.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted', check_s=0.05)
finally: IG.evaluate_shared = orig
n5, miss5 = contained(r5, tv3)
say(dict(control='P1_mid_stream_refusal_preserves_valid_completed_prefix', outcome=r5['outcome'], refusal=str(r5.get('refusal'))[:80], published=n5, K=r5['K'], misses=len(miss5), draws=r5['mechanism'].get('draws'), abandoned=r5['mechanism'].get('abandoned_batches'), ok=(r5['outcome'] == 'NUMERIC_RANGE_REFUSED' and not miss5 and (r5['mechanism'].get('draws') or 0) > 0)))
# ---- P2: the same model, no injection: shared path complete and contained; shared_rows accounting consistent (unique <= active <= draws)
r6 = shared_solve(p3, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); n6, miss6 = contained(r6, tv3); sr = r6['mechanism'].get('shared_rows') or {}
say(dict(control='P2_shared_complete_contained_with_active_unique_accounting', outcome=r6['outcome'], published=n6, K=r6['K'], misses=len(miss6), shared_rows=sr, chunk=r6['mechanism'].get('shared_chunk'), bytes_per_sample_max=r6['mechanism'].get('shared_bytes_per_sample_max'), ok=(not miss6 and n6 == r6['K'] and sr.get('unique', 1) <= sr.get('active', 0) <= sr.get('draws', 0))))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
