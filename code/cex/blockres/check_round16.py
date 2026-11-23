"""Round-16 controls (integrated v2.9.3): cross-batch reuse of shared-block responses. (C1) on a FIXED draw sequence (recorded batches replayed twice), the response matrix of every
batch with the cache is bit-identical to the cache-free evaluation, and the Certificate state after the whole sequence is bit-identical; (C2) a budget of 0 bytes disables the cache
(no hits, identical responses); (C3) a refusal inside a cache miss leaves the cache unchanged (failures are never cached); (C4) an expired deadline on a miss raises before any
evaluation; (C5) end-to-end: the shared model of round 12 solved with the cache, complete and contained (oracle), hits > 0, cache bytes <= budget; (R1) the corrected transient
observer on the reviewer's star equals the plan. Independent oracle = cex/cqr/oracle."""
import sys, os, json, random, time, math, copy
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
IG.EVIDENCE_EXPANSION_DEFAULT = False       # (round 19) this suite exercises its own mechanism; the evidence-expansion operator has its own suite, check_round19.py
IG.LAYERED_CONTRACTION_DEFAULT = False      # (round 20) this suite exercises its own mechanism; the layered-contraction constructor has its own suite, check_round20.py
IG.SUPPORT_CLOSURE_DEFAULT = False          # (round 18) this suite exercises the FROZEN comparator path (v2.9.4 behaviour); the closure has its own suite, check_round18.py
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []; rng = random.Random(1601); nrng = np.random.default_rng(1601)
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
# ---- build the round-12 shared model's blocks (few distinct boundaries, hard zeros) and a FIXED draw sequence of 12 batches x 64 rows with random weights
nS = 5; cards = [2] * nS + [3] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(4, zeros=0.15)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.1))); facs.append(((y0, y1), rnd(9, zeros=0.1)))
p = write_uai('c16_reuse', cards, facs, evidence={nS + 3: 1}); model, _ = BR.core.read_uai(p); cards = model['cards']; fns, c, sc, m, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards, 1 << 3, time.monotonic() + 10, st, tr, od) if f.scope]; step_of = {v: i for i, (v, _) in enumerate(tr)}; trace_var = {i: v for i, (v, _) in enumerate(tr)}; cache_ft = {}
def conv(f):
    if id(f) not in cache_ft: cache_ft[id(f)] = IG.ft_from_int(f, cards)
    return cache_ft[id(f)]
blocks = [conv(f) for f in live]; S = sorted({v for b in blocks for v in b.scope}); pos = {v: i for i, v in enumerate(S)}
sbs = [IG.SharedBlock(b, [conv(f) for f in fns if f.facs <= b.facs], [trace_var[s_] for s_ in sorted(step_of[u] for u in b.interior)], cards, pos) for b in live if b.interior]
Kb_all = sum(len(sb.cols) for sb in sbs); seq = []
for t_ in range(12):
    Sb = np.stack([nrng.integers(0, cards[v], size=64) for v in S], axis=1).astype(np.int64); X = nrng.random(64); X[nrng.random(64) < 0.35] = 0.0; seq.append((Sb, X))
def run_sequence(budget, chunk=7):
    cache = dict(entries={}, bytes=0, budget=budget) if budget is not None else None; cert = IG.Certificate(Kb_all, 1e-6, 2 ** -30, 1 / 200, 'targeted'); mats = []; hits = 0; misses = 0
    for Sb, X in seq:
        act = np.nonzero(X > 0)[0]; f = np.zeros((64, Kb_all)); col = 0
        for sb in sbs:
            fb, stt = IG.evaluate_shared(sb, Sb, act, chunk, math.inf, cache); f[:, col:col + len(sb.cols)] = fb; col += len(sb.cols); hits += stt['hits']; misses += stt['misses']
        cert.update_batch(X, f); mats.append(f.copy())
    return mats, cert, hits, misses, (cache['bytes'] if cache else 0), (sum(len(e) for e in cache['entries'].values()) if cache else 0)
m0, c0, h0, mi0, b0, e0 = run_sequence(None); m1, c1, h1, mi1, b1, e1 = run_sequence(64 << 20)
same_mats = all(np.array_equal(a, b) for a, b in zip(m0, m1))
keys = ('SA', 'SB', 'SXX', 'SXXf', 'SXXff', 'A', 'B', 'Lam', 'Psi', 'P', 'Q', 'Qabs', 'R', 't')
same_cert = all(np.array_equal(getattr(c0, k), getattr(c1, k)) if isinstance(getattr(c0, k), np.ndarray) else getattr(c0, k) == getattr(c1, k) for k in keys)
say(dict(control='C1_cache_identical_responses_and_certificate_on_fixed_sequence', batches=len(seq), blocks=len(sbs), K=Kb_all, response_matrices_identical=same_mats, certificate_state_identical=same_cert, hits=h1, misses=mi1, cache_entries=e1, cache_bytes=b1, ok=(same_mats and same_cert and h1 > 0 and mi1 == e1)))
m2, c2, h2, mi2, b2, e2 = run_sequence(0)
say(dict(control='C2_zero_budget_disables_cache_identical', hits=h2, entries=e2, identical=all(np.array_equal(a, b) for a, b in zip(m0, m2)), ok=(h2 == 0 and e2 == 0 and all(np.array_equal(a, b) for a, b in zip(m0, m2)))))
# C3: failures are never cached: an EMPTY cache, chunk 1, refusal injected on the SECOND chunk of the first evaluation (the first chunk succeeded) -> no entry and no bytes stored
Sb = np.concatenate([s_[0] for s_ in seq], axis=0); act = np.arange(Sb.shape[0])                         # all 768 rows active: many distinct boundaries for every block
sb3 = max(sbs, key=lambda sb_: np.unique(Sb[:, [sb_.pos[u] for u in sb_.bvars]], axis=0).shape[0]); cache3 = dict(entries={}, bytes=0, budget=64 << 20); orig = IG.SharedBlock.responses; ncall = [0]
def boom(self, S_, deadline=math.inf):
    ncall[0] += 1
    if ncall[0] == 2: raise IG.RangeRefused('injected')
    return orig(self, S_, deadline)
IG.SharedBlock.responses = boom; raised = None
try: IG.evaluate_shared(sb3, Sb, act, 1, math.inf, cache3)                       # chunk 1: every distinct boundary is its own chunk; the second chunk is the injected failure
except IG.RangeRefused as e: raised = str(e)
finally: IG.SharedBlock.responses = orig
_, stt_probe = IG.evaluate_shared(sb3, Sb, act, 1, math.inf, dict(entries={}, bytes=0, budget=64 << 20))
say(dict(control='C3_refusal_on_miss_caches_nothing', raised=raised, chunks_needed=stt_probe['chunks'], first_chunk_succeeded=(ncall[0] >= 2), entries=sum(len(e) for e in cache3['entries'].values()), bytes=cache3['bytes'], ok=(raised == 'injected' and stt_probe['chunks'] >= 2 and sum(len(e) for e in cache3['entries'].values()) == 0 and cache3['bytes'] == 0)))
# C4: expired deadline on a miss raises before any evaluation
calls = [0]
def counted(self, S_, deadline=math.inf): calls[0] += 1; return orig(self, S_, deadline)
IG.SharedBlock.responses = counted; raised = None; t_entry = IG.tnow
def late_clock():                                                       # (round 17) the deadline is live at ENTRY and expires before the miss check: the miss path must still refuse before any evaluation
    late_clock.n += 1; return t_entry() + (0.0 if late_clock.n <= 1 else 10.0)
late_clock.n = 0; IG.tnow = late_clock
try: IG.evaluate_shared(sbs[1], seq[2][0], np.nonzero(seq[2][1] > 0)[0], 7, t_entry() + 1.0, dict(entries={}, bytes=0, budget=1 << 20))
except IG.Deadline as e: raised = str(e)
finally: IG.SharedBlock.responses = orig; IG.tnow = t_entry
say(dict(control='C4_expired_deadline_on_miss_no_evaluation', raised=raised, evaluations=calls[0], ok=(raised == 'shared_cache_miss' and calls[0] == 0)))
# C5: end-to-end on the shared path (tiny dense budget), complete and contained, hits > 0, bytes within budget
t, _, tv = truth(p); saved = IG.RECOVERY_BYTE_BUDGET; IG.RECOVERY_BYTE_BUDGET = 0
try: r5 = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted')
finally: IG.RECOVERY_BYTE_BUDGET = saved
n5, miss5 = contained(r5, tv); sr = r5['mechanism'].get('shared_rows') or {}
say(dict(control='C5_end_to_end_shared_with_cache_complete_contained', outcome=r5['outcome'], published=n5, K=r5['K'], misses=len(miss5), shared_rows=sr, ok=(not miss5 and n5 == r5['K'] and sr.get('cache_hits', 0) > 0 and sr.get('cache_bytes', 0) <= IG.RESPONSE_CACHE_BUDGET)))
# R1: corrected observer on the reviewer's star (includes the array being rescaled)
cards_s = [2] * 12 + [8]; blocks_s = [IG.FT((i, 12), np.ones((2, 8)), 0, F(0)) for i in range(12)]; plan = IG.mb_plan([b.scope for b in blocks_s], cards_s, 1 << 14); mb = IG.MBFloat(blocks_s, cards_s, 1 << 14, math.inf); mids = {id(r) for _, _, r in mb.fwd}
orig_r = IG._rescale; peaks = []
def observe(P, e):
    fr = sys._getframe(1); res = orig_r(P, e)
    if fr.f_code.co_name == 'backward_derivatives':
        loc = fr.f_locals; arrays = [r.M for _, _, r in mb.fwd if r.M is not None] + [d.M for mid, d in loc['D'].items() if mid in mids] + list(loc['outs'].values()) + [P, res[0]]; backing = {}
        for a in arrays:
            while isinstance(a.base, np.ndarray): a = a.base
            backing[id(a)] = a
        peaks.append(sum(a.nbytes for a in backing.values()))
    return res
IG._rescale = observe
try: IG.backward_derivatives(mb, cards_s, math.inf, release=True)
finally: IG._rescale = orig_r
say(dict(control='R1_corrected_observer_star_equals_plan', planned=plan['reverse_live_bytes'], observed_peak=max(peaks), ok=(max(peaks) == plan['reverse_live_bytes'])))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
