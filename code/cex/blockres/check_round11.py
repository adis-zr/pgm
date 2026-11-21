"""Round-11 controls (integrated v2.6): the demonstrated publication defect, bounded root allowances, shared-vs-dense responses, shared recovery under a tiny budget, low proposal
memory, deadline / resource refusal without invalid publication, interleaved executions. Independent oracle = cex/cqr/oracle (enumeration / bucket elimination over the original model)."""
import sys, os, json, random, time, math, itertools
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, oracle, task as T
IG.SUPPORT_CLOSURE_DEFAULT = False          # (round 18) this suite exercises the FROZEN comparator path (v2.9.4 behaviour); the closure has its own suite, check_round18.py
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); EPS = F(1, 200); rows = []; rng = random.Random(1120)
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
# ---- F1: the wide valid envelope, below / at / above rho_Z = 1, zero numerators, zero global mass
p = write_uai('wide_root', [2, 2], [((0, 1), [1, 3, 2, 6])]); orig = IG.MBFloat.__init__
for rz, label in ((F(3, 4), 'above_1_after_comb'), (F(1, 2), 'half'), (F(1, 100), 'small')):
    def enl(self, *a, **k): orig(self, *a, **k); self.scalars[0].rho = rz
    IG.MBFloat.__init__ = enl; r = IG.solve(p, 3.0, table_cap=0, enum_cap=0, force_approx=True, mb_cap=4, route='exact', crosscheck=False); IG.MBFloat.__init__ = orig
    t, _, tv = truth(p); n, miss = contained(r, tv); er = r['mechanism'].get('exact_route') or {}
    say(dict(control='F1_wide_envelope_' + label, root_rho=str(rz), outcome=r['outcome'], published=n, misses=len(miss), status=str(er.get('status'))[:90], note='partial publication of valid intervals is correct when the enlarged envelope makes some ratios wider than 2 eps', ok=(not miss)))
# zero numerator with positive mass (hard zero state) and zero global mass
p = write_uai('zero_num', [2, 2], [((0, 1), [0, 3, 0, 6])]); t, _, tv = truth(p); r = IG.solve(p, 3.0, table_cap=0, enum_cap=0, force_approx=True, mb_cap=4, route='exact', crosscheck=False); n, miss = contained(r, tv)
say(dict(control='F1_zero_numerator_exact_zero_published', outcome=r['outcome'], published=n, misses=len(miss), zero_rows=[a['point'] for a in r['answers'] if a['guarantee'] != 'NOT_PUBLISHED' and F(a['point']) == 0], ok=(not miss and n == r['K'])))
p = write_uai('zero_mass', [2, 2], [((0, 1), [0, 0, 0, 0])]); r = IG.solve(p, 3.0, table_cap=0, enum_cap=0, force_approx=True, mb_cap=4, route='exact', crosscheck=False)
say(dict(control='F1_zero_global_mass_is_ZERO_EVIDENCE_not_publication', outcome=r['outcome'], published=sum(1 for a in r['answers'] if a['guarantee'] != 'NOT_PUBLISHED'), ok=(r['outcome'] == 'ZERO_EVIDENCE')))
# compaction validation: an interval whose compaction would widen past 2 eps must be withheld (synthetic check of compact_outward + valid_publication)
lo, hi = F(1, 3) - EPS + F(1, 10 ** 20), F(1, 3) + EPS - F(1, 10 ** 20); L, H = IG.compact_outward(lo, hi)                      # width 2 eps - 2e-20: compaction (< 4.4e-16 widening) pushes it past 2 eps -> must be REJECTED on revalidation
lo2, hi2 = F(1, 3) - EPS + F(1, 10 ** 10), F(1, 3) + EPS - F(1, 10 ** 10); L2, H2 = IG.compact_outward(lo2, hi2)                 # width 2 eps - 2e-10: stays valid after compaction
say(dict(control='F1_compaction_is_outward_and_revalidated', outward=(L <= lo and H >= hi and L2 <= lo2 and H2 >= hi2), borderline_rejected=(not IG.valid_publication(L, H, EPS)), comfortable_accepted=IG.valid_publication(L2, H2, EPS), ok=(L <= lo and H >= hi and L2 <= lo2 and H2 >= hi2 and not IG.valid_publication(L, H, EPS) and IG.valid_publication(L2, H2, EPS))))
# ---- F2: root allowance size on 40 / 200 / 400 roots
for n in (40, 200, 400):
    p = write_uai('f2_%d' % n, [2] * n, [((i,), [1, 3]) for i in range(n)]); model, _ = BR.core.read_uai(p); cards = model['cards']; fns, c, sc, m, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
    live = [f for f in BR.contract(fns, cards, 0, time.monotonic() + 10, st, tr, od) if f.scope]; blocks = [IG.ft_from_int(f, cards) for f in live]; mbp = IG.MBFloat(blocks, cards, 4, time.monotonic() + 10)
    say(dict(control='F2_root_allowance_bits_%d' % n, roots=len(mbp.scalars), rhoU=float(mbp.rhoU), denominator_bits=mbp.rhoU.denominator.bit_length(), ok=(mbp.rhoU.denominator.bit_length() <= 201 and mbp.rhoU > 0)))
# ---- shared vs dense responses on the same model and FIXED separator assignments; equivalence on supported assignments
nS = 6; cards = [2] * nS + [3] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(4, zeros=0.15)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.1))); facs.append(((y0, y1), rnd(9)))
p = write_uai('shared_vs_dense', cards, facs, evidence={nS + 3: 1}); model, _ = BR.core.read_uai(p); cards = model['cards']; fns, c, sc, m, fl = BR.integerize(model); tr = []; od = []; st = dict(elim_work=0, eliminations=0, query_work=0)
live = [f for f in BR.contract(fns, cards, 1 << 3, time.monotonic() + 10, st, tr, od) if f.scope]; step_of = {v: i for i, (v, _) in enumerate(tr)}; cache = {}
def conv(f):
    if id(f) not in cache: cache[id(f)] = IG.ft_from_int(f, cards)
    return cache[id(f)]
blocks = [conv(f) for f in live]; trace_var = {i: v for i, (v, _) in enumerate(tr)}; trace_ft = [[conv(f) for f in snap] for v, snap in tr]; S = sorted({v for b in blocks for v in b.scope}); pos = {v: i for i, v in enumerate(S)}
Sb = np.array(list(itertools.product(*(range(cards[v]) for v in S))), dtype=np.int64); worst = 0.0; cmp_ = 0; unsupported_mismatch = 0
for i, b in enumerate(blocks):
    if not live[i].interior: continue
    sb = IG.SharedBlock(live[i], [conv(f) for f in fns if f.facs <= live[i].facs], [trace_var[st] for st in sorted(step_of[u] for u in live[i].interior)], cards, pos); fsh, root, Er = sb.responses(Sb)
    idx = np.zeros(Sb.shape[0], dtype=np.int64); s_ = 1
    for u in reversed(b.scope): idx += Sb[:, pos[u]] * s_; s_ *= cards[u]
    g = b.M.reshape(-1)[idx]
    for ci, (x, a) in enumerate(sb.cols):
        r = IG.recover_query_table_float(b, x, cards, trace_ft, trace_var, step_of, time.monotonic() + 10, st); dense = np.where(g > 0, r.M[..., a].reshape(-1)[idx] * math.ldexp(1.0, r.e - b.e) / np.where(g > 0, g, 1.0), 0.0)
        sup = g > 0; cmp_ += int(sup.sum()); worst = max(worst, float(np.abs(fsh[sup, ci] - dense[sup]).max()) if sup.any() else 0.0)
        if (~sup).any() and float(np.abs(fsh[~sup, ci]).max()) > 0: unsupported_mismatch += 1
say(dict(control='shared_vs_dense_responses_fixed_assignments', assignments=int(Sb.shape[0]), compared=cmp_, worst_abs_difference=worst, declared_rho_f=float(blocks and IG.SharedBlock(live[0], [conv(f) for f in fns if f.facs <= live[0].facs], [trace_var[st] for st in sorted(step_of[u] for u in live[0].interior)], cards, pos).rho_f), ok=(worst <= 1e-12 and cmp_ > 0)))
# ---- shared recovery under an artificially tiny query budget: every query recovered, containment vs oracle (PAC route), and with budget large (dense) for the matched pair
t, _, tv = truth(p); saved = IG.RECOVERY_BYTE_BUDGET
IG.RECOVERY_BYTE_BUDGET = 64; r_sh = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); IG.RECOVERY_BYTE_BUDGET = saved
n, miss = contained(r_sh, tv); m = r_sh['mechanism']
say(dict(control='shared_recovery_tiny_budget_all_queries_contained', outcome=r_sh['outcome'], representation=m.get('response_representation'), shared_blocks=m.get('shared_blocks'), Kq=m.get('Kq'), K=r_sh['K'], published=n, misses=len(miss), draws=m.get('draws'), batch_used=m.get('batch_used'), ok=(not miss and m.get('Kq') == r_sh['K'] and n > 0 and m.get('shared_blocks', 0) > 0)))
r_de = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); n2, miss2 = contained(r_de, tv); m2 = r_de['mechanism']
say(dict(control='dense_recovery_same_model_contained', outcome=r_de['outcome'], representation=m2.get('response_representation'), published=n2, misses=len(miss2), draws=m2.get('draws'), X_mean=m2.get('X_mean'), X_mean_shared=m.get('X_mean'), ok=(not miss2 and n2 > 0)))
# ---- low proposal-memory control: the memory policy must choose a smaller cap, validate support and cap exhaustively (via the solver's own assertion), and reach the sampler
saved_usable = None
p2 = write_uai('low_mem', [2] * 10, [((i, j), rnd(4)) for i in range(10) for j in range(i + 1, 10)])
t2, _, tv2 = truth(p2); r_lm = IG.solve(p2, 8.0, force_approx=True, table_cap=0, enum_cap=0, mb_cap=1 << 24, route='pac', schedule='targeted'); mp = r_lm['mechanism'].get('memory_policy') or {}
n3, miss3 = contained(r_lm, tv2)
say(dict(control='memory_policy_cap_ladder_reaches_sampler', outcome=r_lm['outcome'], cap_requested=mp.get('cap_requested'), cap_used=mp.get('cap_used'), planned_forward_MiB=round((mp.get('planned_forward_bytes') or 0) / 2 ** 20, 1), published=n3, misses=len(miss3), draws=r_lm['mechanism'].get('draws'), ok=(not miss3 and (r_lm['mechanism'].get('draws') or 0) > 0)))
# ---- early deadline: a 0.3 s budget on the shared_vs_dense model must not publish anything invalid
r_dl = IG.solve(p, 0.3, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac'); n4, miss4 = contained(r_dl, tv)
say(dict(control='early_deadline_no_invalid_publication', outcome=r_dl['outcome'], published=n4, misses=len(miss4), ok=(not miss4)))
# ---- interleaved executions: two different models solved alternately in the same process must reproduce their standalone answers
pA = os.path.join(TMP, 'c7_complete_sep.uai'); pB = p; tA, _, tvA = truth(pA); kw = dict(force_approx=True, table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 14, route='auto', crosscheck=False)
rA1 = IG.solve(pA, 6.0, **kw); rB1 = IG.solve(pB, 6.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='auto', crosscheck=False); rA2 = IG.solve(pA, 6.0, **kw)
same = [a['lo'] for a in rA1['answers']] == [a['lo'] for a in rA2['answers']] and [a['hi'] for a in rA1['answers']] == [a['hi'] for a in rA2['answers']]; nA, mA = contained(rA2, tvA); nB, mB = contained(rB1, tv)
say(dict(control='interleaved_executions_no_shared_state', A_route=rA1['mechanism'].get('route'), A_identical_after_interleave=same, A_misses=len(mA), B_misses=len(mB), ok=(same and not mA and not mB)))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
