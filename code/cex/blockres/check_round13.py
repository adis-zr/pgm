"""Round-13 controls (integrated v2.9): the TILED reverse step equals the untiled computation (random buckets; k up to 6; tiny tile budgets that force many tiles, incl. tiles that split a
member's scope); the exact route with release + rebuild publishes the same intervals as without release and the PAC fallback still works after a released exact route that is refused /
fails its cross-check; the memory plan's exact-route estimate vs the measured tracemalloc peak of the reverse pass; the shared path's fixed-overhead term at B = 1 (reviewer's cases);
an already-expired deadline permits NO factor gather; the exponent conversion is checked (no clamp). Independent oracle = cex/cqr/oracle."""
import sys, os, json, random, time, math, itertools, tracemalloc
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); EPS = F(1, 200); rows = []; rng = random.Random(1301); nrng = np.random.default_rng(1301)
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
# ---- T1: tiled reverse step == untiled, random buckets (mixed cardinalities, zeros), tile budgets forcing 1 .. many tiles; the untiled reference is computed directly
worst = 0.0; trials = 0; tiles_seen = set()
for trial in range(40):
    nu = rng.randint(2, 6); cards_u = [rng.choice([2, 2, 3, 4]) for _ in range(nu)]; union = tuple(range(nu)); k = rng.randint(1, 6)
    scopes = [tuple(sorted(rng.sample(union, rng.randint(1, nu)))) for _ in range(k)]
    As = [np.where(nrng.random([cards_u[u] if u in sc else 1 for u in union]) < 0.15, 0.0, nrng.random([cards_u[u] if u in sc else 1 for u in union]) + 0.1) for sc in scopes]
    dsc = tuple(sorted(rng.sample(union, rng.randint(0, nu)))); DRa = nrng.random([cards_u[u] if u in dsc else 1 for u in union]) + 0.05
    full = [cards_u[u] for u in union]; ref = {}
    for i in range(k):
        P = DRa.copy()
        for j in range(k):
            if j != i: P = P * As[j]
        P = np.broadcast_to(P, full); axes = tuple(a for a in range(nu) if union[a] not in scopes[i]); ref[i] = P.sum(axis=axes) if axes else np.array(P)
    for tb in (8 * (2 * k + 3) * 1, 8 * (2 * k + 3) * 7, 8 * (2 * k + 3) * 64, 1 << 20):
        outs = IG.tiled_member_derivatives(DRa, As, union, cards_u, scopes, list(range(k)), tb, math.inf)
        tile_entries = max(1, tb // ((2 * k + 3) * 8)); m = 0; rest = int(np.prod(full))
        while m < nu and rest > tile_entries: rest //= full[m]; m += 1
        tiles_seen.add(int(np.prod(full[:m])) if m else 1)
        for i in range(k): worst = max(worst, float(np.abs(np.asarray(outs[i]).reshape(-1) - np.asarray(ref[i]).reshape(-1)).max() / max(1e-300, float(np.abs(ref[i]).max())))); trials += 1
say(dict(control='T1_tiled_reverse_step_equals_untiled', trials=trials, distinct_tile_counts=sorted(tiles_seen)[:12], worst_relative_difference=worst, ok=(worst <= 1e-13)))
# ---- T2: exact route with release + rebuild: same publications as the untiled / unreleased v2.8 computation (identical intervals), contained (oracle), on c7_complete_sep and a1_three_components
for name in ('c7_complete_sep', 'a1_three_components', 'a1_constants_factorless'):
    p = os.path.join(TMP, name + '.uai'); t, _, tv = truth(p); kw = dict(force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 14, route='exact', crosscheck=False)
    r_rel = IG.solve(p, 10.0, **kw)
    orig = IG.backward_derivatives
    def norel(mbp, cards, deadline, release=False, tile_budget=None): return orig(mbp, cards, deadline, release=False, tile_budget=1 << 40)
    IG.backward_derivatives = norel
    try: r_ref = IG.solve(p, 10.0, **kw)
    finally: IG.backward_derivatives = orig
    same = [(a['lo'], a['hi']) for a in r_rel['answers']] == [(a['lo'], a['hi']) for a in r_ref['answers']]; n, miss = contained(r_rel, tv)
    say(dict(control='T2_release_tiled_exact_route_identical_and_contained_' + name, outcome=r_rel['outcome'], published=n, K=r_rel['K'], misses=len(miss), identical_to_unreleased_untiled=same, ok=(same and not miss and n == r_rel['K'])))
# ---- T3: PAC fallback after a RELEASED exact route that fails its cross-check (E6-style corruption) must rebuild the construction and complete, contained
p = os.path.join(TMP, 'c7_complete_sep.uai'); t, _, tv = truth(p); orig = IG.backward_derivatives
def corrupt(mbp, cards, deadline, **kw):
    D = orig(mbp, cards, deadline, **kw)
    for fi in mbp.inputs: D[id(fi)] = IG.FT(D[id(fi)].scope, D[id(fi)].M * 1.5, D[id(fi)].e, D[id(fi)].rho)
    return D
IG.backward_derivatives = corrupt
try: r3 = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 14, route='auto', schedule='targeted')
finally: IG.backward_derivatives = orig
n3, miss3 = contained(r3, tv); m3 = r3['mechanism']
say(dict(control='T3_pac_fallback_rebuilds_after_released_exact_route_crosscheck_failure', outcome=r3['outcome'], route=m3.get('route'), exact_status=str((m3.get('exact_route') or {}).get('status'))[:60], rebuilt=m3.get('mb_rebuilt_for_pac'), rebuild_s=r3['phases_s'].get('mb_rebuild_for_pac'), published=n3, K=r3['K'], misses=len(miss3), ok=(m3.get('route') == 'pac' and m3.get('mb_rebuilt_for_pac') is True and not miss3 and n3 == r3['K'])))
# ---- T4: memory plan vs measured: on c7_complete_sep at a cap that gives large unions, the tracemalloc peak of (forward kept) backward pass with release <= planned forward + tile budget + block tables + headroom
model, _ = BR.core.read_uai(p); cards = model['cards']; fns, c, sc, mlt, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards, 1 << 6, time.monotonic() + 10, st, tr, od) if f.scope]; blocks = [IG.ft_from_int(f, cards) for f in live]; plan = IG.mb_plan([b.scope for b in blocks], cards, 1 << 14)
mbp = IG.MBFloat(blocks, cards, 1 << 14, time.monotonic() + 20); fwd_actual = sum(R.M.nbytes for _, _, R in mbp.fwd)                   # every message incl. the 8-byte scalar roots (as the plan counts them since v2.9.1)
tracemalloc.start(); D = IG.backward_derivatives(mbp, cards, time.monotonic() + 20, release=True, tile_budget=64 << 10); _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
released = sum(1 for _, _, R in mbp.fwd if R.M is None); bound = plan['reverse_live_bytes'] + (64 << 10) + sum(b.M.nbytes for b in blocks) + (1 << 20)
say(dict(control='T4_reverse_pass_peak_within_plan', planned_forward_KiB=round(plan['forward_bytes'] / 1024, 1), actual_forward_KiB=round(fwd_actual / 1024, 1), reverse_live_KiB=round(plan['reverse_live_bytes'] / 1024, 1), measured_peak_KiB=round(peak / 1024, 1), bound_KiB=round(bound / 1024, 1), messages_released=released, of=len(mbp.fwd), ok=(peak <= bound and plan['forward_bytes'] == fwd_actual and released == sum(1 for _, _, R in mbp.fwd if R not in mbp.inputs and R.scope))))   # v2.9.1 releases at the CONSUMER step: every scoped message is a bucket member once; the scalar roots are consumed by the root product, not a bucket
# ---- S1: shared path fixed overhead at B = 1: the reviewer's one-variable block and the 40-step chain; traced peak <= fixed + B x payload
block = BR.Fn((1,), np.array([2, 2], dtype=object), [0], [0]); factor = IG.FT((0, 1), np.ones((2, 2)), 0, F(0)); sb = IG.SharedBlock(block, [factor], [0], [2, 2], {1: 0}); S = np.zeros((1, 1), dtype=np.int64)
tracemalloc.start(); sb.responses(S); _, pk1 = tracemalloc.get_traced_memory(); tracemalloc.stop()
steps_, width, B = 40, 10, 1; n = steps_ + width - 1; cards_ = [2] * n; boundary = tuple(range(steps_, n)); factors = [IG.FT(tuple(range(i, i + width)), np.ones([2] * width), 0, F(0)) for i in range(steps_)]
blk = BR.Fn(boundary, np.full([2] * len(boundary), 1 << steps_, dtype=object), range(steps_), range(steps_)); sb2 = IG.SharedBlock(blk, factors, range(steps_), cards_, {v: i for i, v in enumerate(boundary)}); S2 = np.zeros((B, len(boundary)), dtype=np.int64)
tracemalloc.start(); sb2.responses(S2); _, pk2 = tracemalloc.get_traced_memory(); tracemalloc.stop()
S3 = np.zeros((128, len(boundary)), dtype=np.int64); tracemalloc.start(); sb2.responses(S3); _, pk3 = tracemalloc.get_traced_memory(); tracemalloc.stop()
say(dict(control='S1_fixed_overhead_plus_payload_bounds_traced_peak_B1_and_B128', one_var=(sb.fixed_workspace_bytes + sb.bytes_per_sample, pk1), chain40_B1=(sb2.fixed_workspace_bytes + sb2.bytes_per_sample, pk2), chain40_B128=(sb2.fixed_workspace_bytes + 128 * sb2.bytes_per_sample, pk3), ok=(pk1 <= sb.fixed_workspace_bytes + sb.bytes_per_sample and pk2 <= sb2.fixed_workspace_bytes + sb2.bytes_per_sample and pk3 <= sb2.fixed_workspace_bytes + 128 * sb2.bytes_per_sample)))
# ---- S2: an already-expired deadline permits NO factor gather
calls = []; original = sb2._restricted
def counted(f, s): calls.append(1); return original(f, s)
sb2._restricted = counted; raised = None
try: sb2.responses(S2, deadline=-math.inf)
except IG.Deadline as e: raised = str(e)
sb2._restricted = original
say(dict(control='S2_expired_deadline_no_gather', raised=raised, gathers_before_refusal=len(calls), ok=(raised == 'shared_entry' and len(calls) == 0)))
# ---- S3: the exponent conversion is checked: an injected absurd exponent must raise RangeRefused (typed), never clamp
orig_resc = IG.SharedBlock._rescale
def huge(A, E):
    out, E2, R = orig_resc(A, E); return out, E2 + 2.0 ** 31, R
IG.SharedBlock._rescale = staticmethod(huge); raised = None
try: sb.responses(S)
except IG.RangeRefused as e: raised = str(e)[:60]
except AssertionError as e: raised = 'ASSERT: ' + str(e)[:60]
finally: IG.SharedBlock._rescale = staticmethod(orig_resc)
say(dict(control='S3_exponent_conversion_checked_not_clamped', raised=raised, ok=(raised is not None)))
# ---- (round 14) T5: per-step LIVENESS of the reverse pass vs the plan's simulation, counting what is actually alive: message mantissas not released, message derivatives in D, the
#      derivative outputs being created (member sizes) and the rescale copy; on the reviewer's star, a long chain (consumers far from creators) and c7_complete_sep; with release=True the
#      largest simultaneous payload must be <= reverse_live_bytes at EVERY step; and the v2.9 coexistence (mantissa + derivative of the same message) must not occur
def liveness(blocks_, cards_, cap):
    plan_ = IG.mb_plan([b.scope for b in blocks_], cards_, cap); mb_ = IG.MBFloat(blocks_, cards_, cap, math.inf); assert mb_.splits == 0
    orig_t = IG.tiled_member_derivatives; rows_ = []; coexist = [0]
    def observe(DRa, As, union, cards__, scopes, want, tile_budget, deadline, phase='backward_tile'):
        fr = sys._getframe(1); D_ = fr.f_locals['D']; mids = {id(r) for _, _, r in mb_.fwd}
        fwd_ = sum(r.M.nbytes for _, _, r in mb_.fwd if r.M is not None); der_ = sum(d.M.nbytes for mid, d in D_.items() if mid in mids)
        coexist[0] += sum(1 for _, _, r in mb_.fwd if r.M is not None and id(r) in D_ and r.scope)
        outs_ = sum(8 * int(np.prod([cards__[u] for u in sc])) for sc in scopes); rows_.append((fwd_, der_, outs_, fwd_ + der_ + outs_ + max([8 * int(np.prod([cards__[u] for u in sc])) for sc in scopes] + [0])))
        return orig_t(DRa, As, union, cards__, scopes, want, tile_budget, deadline, phase)
    IG.tiled_member_derivatives = observe
    try: IG.backward_derivatives(mb_, cards_, math.inf, release=True)
    finally: IG.tiled_member_derivatives = orig_t
    worst_ = max(rows_, key=lambda r: r[3]) if rows_ else (0, 0, 0, 0)
    return plan_['reverse_live_bytes'], worst_, coexist[0], len(rows_)
star_cards = [2] * 12 + [8]; star_blocks = [IG.FT((i, 12), np.ones((2, 8)), 0, F(0)) for i in range(12)]
chain_n = 14; chain_cards = [2] * chain_n; chain_blocks = [IG.FT((i, i + 1), nrng.random((2, 2)) + 0.1, 0, F(0)) for i in range(chain_n - 1)] + [IG.FT((0, chain_n - 1), nrng.random((2, 2)) + 0.1, 0, F(0))]
c7 = os.path.join(TMP, 'c7_complete_sep.uai'); model7, _ = BR.core.read_uai(c7); cards7 = model7['cards']; fns7, _, _, _, _ = BR.integerize(model7); tr7 = []; od7 = []; st7 = dict(elim_work=0, eliminations=0, query_work=0)
live7 = [f for f in BR.contract(fns7, cards7, 1 << 6, time.monotonic() + 10, st7, tr7, od7) if f.scope]; blocks7 = [IG.ft_from_int(f, cards7) for f in live7]
allok = True
for nm, bl, cd, cap in (('reviewer_star', star_blocks, star_cards, 1 << 14), ('ring_chain_14', chain_blocks, chain_cards, 1 << 14), ('c7_complete_sep', blocks7, cards7, 1 << 14)):
    planned, worst, coexist, nsteps = liveness(bl, cd, cap); ok_ = (worst[3] <= planned and coexist == 0); allok &= ok_
    say(dict(control='T5_reverse_liveness_within_plan_' + nm, steps=nsteps, planned_bytes=planned, worst_simultaneous=dict(forward=worst[0], derivatives=worst[1], outputs=worst[2], total_with_rescale=worst[3]), mantissa_derivative_coexistence=coexist, ok=ok_))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows), '(with T5)')
