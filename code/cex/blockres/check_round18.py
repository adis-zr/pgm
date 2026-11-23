"""Round-18 controls (integrated v2.10, exact support closure ON): the integration-specific controls of the brief, every one against the independent oracle (cex/cqr/oracle, enumeration
over the ORIGINAL model) and over the ORIGINAL query denominator. S1 weighted nonbinary bijection; S2 inconsistent cycle = ZERO_EVIDENCE with nothing published; S3 partly consistent
permutation cycle (representative states removed, all original coordinates exact and contained); S4 fixed evidence + removed states + proven-zero states (EXACT 0 rows); S5 multiple
aliases in one factor + duplicate factor occurrences (weights kept, not deduplicated); S6 positive scalar tracking (Z equals the oracle's exactly); S7 factorless multiplicity through the
closure; S8 zero global mass with separately fixed variables (no publication, incl. the fixed ones); S9 interrupted construction (injected allowance) -> typed SKIP -> original route,
contained; S10 all-original query expansion (K = original, every coordinate exactly once, alias rows identical to their representative); S11 PAC guarantee preserved when the reduced
model still needs sampling (force_approx), contained, and the comparator path (closure OFF) agrees; S12 the closure-ON run of every frozen-path suite model shows 0 containment misses
(read from the CONTROLS_R18DEV_* result files written by this round's development runs)."""
import sys, os, json, random, time, math, glob
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__)); CODE = os.path.dirname(os.path.dirname(HERE))
for p in (HERE, os.path.join(CODE, 'cex', 'cqr'), os.path.join(CODE, 'cex', 'newarm')):
    if p not in sys.path: sys.path.insert(0, p)
import numpy as np
import integrated as IG, blockres as BR, support_closure as SC, oracle, task as T
IG.EVIDENCE_EXPANSION_DEFAULT = False       # (round 19) this suite exercises its own mechanism; the evidence-expansion operator has its own suite, check_round19.py
IG.LAYERED_CONTRACTION_DEFAULT = False      # (round 20) this suite exercises its own mechanism; the layered-contraction constructor has its own suite, check_round20.py
assert IG.SUPPORT_CLOSURE_DEFAULT is True
OUT = sys.argv[1]; TMP = os.path.join(os.path.dirname(OUT), 'ctl_models'); os.makedirs(TMP, exist_ok=True); rows = []; rng = random.Random(1801)
def say(r): r['ok'] = bool(r['ok']); rows.append(r); print(json.dumps(r, default=str)[:420])
def write_uai(name, cards, factors, evidence=None):
    p = os.path.join(TMP, name + '.uai'); lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(factors))]
    for sc, _ in factors: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in factors: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(p, 'w').write('\n'.join(lines) + '\n'); ev = evidence or {}; open(p + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n'); return p
def truth(p):
    t = T.load_task(p); r = oracle.truth(t['model'], t['queries'], max_assignments=1 << 20, max_table=1 << 20); return t, r, ({(q.output['variable'], q.output['state']): a for q, a in zip(t['queries'], r['answers'])} if r['answers'] and r['answers'][0] != 'ZERO_EVIDENCE' else None), r
def contained(res, tv):
    n = 0; miss = []
    for a in res['answers']:
        if a['guarantee'] == 'NOT_PUBLISHED': continue
        n += 1; tr = tv[(a['var'], a['state'])]; lo, hi = F(a['lo']), F(a['hi'])
        if not (F(0) <= lo <= hi <= 1) or not (lo <= tr <= hi): miss.append((a['var'], a['state'], str(lo), str(hi), str(tr)))
    return n, miss
def cl(res): return (res['mechanism'] or {}).get('support_closure') or {}
def rnd(n, zeros=0.0, lo=1, hi=9): return [0 if rng.random() < zeros else rng.randint(lo, hi) for _ in range(n)]
KW = dict(table_cap=1 << 6, enum_cap=1 << 4, mb_cap=1 << 12, route='auto', schedule='targeted', crosscheck=False)
# S1 weighted nonbinary bijection: x1 = pi(x0) with weights (1/3, 2/5, 7/11) on a 3-state pair, plus an independent pair factor on (x1, x2)
p = write_uai('s1_weighted_bij', [3, 3, 3], [((0, 1), ['1/3', 0, 0, 0, 0, '2/5', 0, '7/11', 0]), ((1, 2), ['1/2', 1, 2, 3, '1/5', 1, 2, 2, '3/7'])]); t, _, tv, _ = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
say(dict(control='S1_weighted_nonbinary_bijection', outcome=r['outcome'], closure=c.get('status'), relations=c.get('bijection_relations'), representatives=c.get('representatives'), published=n, K=r['K'], misses=len(miss), ok=(c.get('status') == 'APPLIED' and c.get('bijection_relations', 0) >= 1 and not miss and n == r['K'] == 9)))
# S2 inconsistent binary cycle = exact zero evidence
eq = ((0, 1), [1, 0, 0, 1]); p = write_uai('s2_inconsistent_cycle', [2, 2, 2], [eq, ((1, 2), [1, 0, 0, 1]), ((0, 2), [0, 1, 1, 0])]); t, _, tv, orc = truth(p); r = IG.solve(p, 6.0, **KW)
say(dict(control='S2_inconsistent_cycle_is_ZERO_EVIDENCE_nothing_published', outcome=r['outcome'], closure=str(cl(r).get('status'))[:60], published=r['published'], oracle_zero=(tv is None), ok=(r['outcome'] == 'ZERO_EVIDENCE' and r['published'] == 0 and tv is None)))
# S3 partly consistent permutation cycle on 3-state variables: two of three representative states survive
p = write_uai('s3_partial_cycle', [3, 3, 3], [((0, 1), [1, 0, 0, 0, 2, 0, 0, 0, 3]), ((1, 2), [1, 0, 0, 0, 1, 0, 0, 0, 1]), ((0, 2), [5, 0, 0, 0, 0, 7, 0, 11, 0])]); t, _, tv, _ = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
zeros = sum(1 for a in r['answers'] if a['guarantee'] == 'EXACT' and F(a['lo']) == 0)
say(dict(control='S3_partly_consistent_cycle_removes_states_all_exact_contained', outcome=r['outcome'], closure=c.get('status'), cycle_removed=c.get('cycle_removed_states'), representatives=c.get('representatives'), published=n, K=r['K'], exact_zero_rows=zeros, misses=len(miss), ok=(c.get('cycle_removed_states', 0) >= 1 and not miss and n == r['K'] == 9 and zeros >= 2)))
# S4 fixed evidence propagating: ev x0 = 1; factor (x0, x1) forbids x1 = 1 when x0 = 1; factor (x1, x2) forces x2 = x1 OR x0 ... (x1 fixed 0 -> x2 forced via (x0,x1,x2) OR table)
p = write_uai('s4_evidence_propagation', [2, 2, 2, 2], [((0, 1), ['1/2', '1/2', 1, 0]), ((0, 1, 2), [1, 0, 0, 1, 0, 1, 0, 1]), ((2, 3), rnd(4))], evidence={0: 1}); t, _, tv, _ = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
fixed_rows = [(a['var'], a['state'], a['lo']) for a in r['answers'] if a['var'] in (1, 2)]
say(dict(control='S4_evidence_propagation_fixes_and_proven_zero_states', outcome=r['outcome'], closure=c.get('status'), deleted=c.get('deleted_states'), fixed_nonobserved=c.get('fixed_nonobserved_variables'), rows_x1_x2=fixed_rows, published=n, K=r['K'], misses=len(miss), ok=(c.get('fixed_nonobserved_variables', 0) >= 2 and not miss and n == r['K'] == 6)))
# S5 multiple aliases in one factor (x1 = x0, x2 = x0 via one ternary factor) + a DUPLICATE occurrence of a weighted pair factor (weights must multiply, not dedupe)
tern = [0] * 8; tern[0] = 1; tern[7] = 1; w = ((0, 3), ['1/2', 2, 3, '1/5'])
p = write_uai('s5_aliases_duplicates', [2, 2, 2, 2], [((0, 1, 2), tern), w, w, ((2, 3), rnd(4))]); t, _, tv, _ = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
say(dict(control='S5_multiple_aliases_one_factor_and_duplicate_occurrences', outcome=r['outcome'], closure=c.get('status'), relations=c.get('bijection_relations'), representatives=c.get('representatives'), published=n, K=r['K'], misses=len(miss), ok=(c.get('status') == 'APPLIED' and not miss and n == r['K'] == 8)))
# S6 positive scalar tracking: constant factors + a bijection whose weights become a constant after substitution; the exact Z must equal the oracle's
p = write_uai('s6_scalar', [2, 2, 3], [((), ['7/3']), ((0, 1), ['2/5', 0, 0, '2/5']), ((1, 2), [1, 2, 3, 4, 5, 6])]); t, _, tv, orc = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
Zok = ('Z' in r and F(r['Z']) == F(orc['Z']))
say(dict(control='S6_positive_scalar_tracked_Z_exact', outcome=r['outcome'], closure=c.get('status'), scalar=str(c.get('scalar')), Z=str(r.get('Z'))[:30], oracle_Z=str(orc['Z'])[:30], Z_equal=Zok, misses=len(miss), published=n, K=r['K'], ok=(Zok and not miss and n == r['K'] and F(c.get('scalar', '1')) != 1)))
# S7 factorless multiplicity through the closure: variable 3 touches no factor; uniform marginals; Z includes its multiplicity
p = write_uai('s7_factorless', [2, 2, 3, 4], [((0, 1), [1, 0, 0, 1]), ((1, 2), rnd(6))]); t, _, tv, orc = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv)
unif = all(F(a['lo']) == F(1, 4) for a in r['answers'] if a['var'] == 3)
say(dict(control='S7_factorless_multiplicity_uniform_and_Z', outcome=r['outcome'], closure=cl(r).get('status'), x3_uniform=unif, Z_equal=('Z' in r and F(r['Z']) == F(orc['Z'])), published=n, K=r['K'], misses=len(miss), ok=(unif and not miss and n == r['K'] and 'Z' in r and F(r['Z']) == F(orc['Z']))))
# S8 zero global mass with separately fixed variables: x0 fixed by evidence, x1 forced by a factor, and an unrelated all-zero factor on (x2, x3) -> ZERO_EVIDENCE, no row published (not even the fixed ones)
p = write_uai('s8_zero_mass_fixed', [2, 2, 2, 2], [((0, 1), [1, 0, 0, 1]), ((2, 3), [0, 0, 0, 0])], evidence={0: 1}); r = IG.solve(p, 6.0, **KW)
say(dict(control='S8_zero_global_mass_publishes_no_fixed_variable', outcome=r['outcome'], published=r['published'], closure=str(cl(r).get('status'))[:40], ok=(r['outcome'] == 'ZERO_EVIDENCE' and r['published'] == 0)))
# S9 interrupted construction: an injected allowance of 1 microsecond makes the closure refuse; the original route must run and be contained; the refusal is typed and charged
nS = 5; cards = [2] * nS + [3] * (2 * nS); facs = []
for i in range(nS):
    for j in range(i + 1, nS): facs.append(((i, j), rnd(4, zeros=0.15)))
    y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs.append(((i, y0), rnd(6, zeros=0.1))); facs.append(((y0, y1), rnd(9)))
p9 = write_uai('s9_interrupt', cards, facs, evidence={nS + 3: 1}); t, _, tv9, _ = truth(p9); saved = IG.SUPPORT_CLOSURE_SHARE_S; IG.SUPPORT_CLOSURE_SHARE_S = 1e-6
try: r = IG.solve(p9, 10.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted')
finally: IG.SUPPORT_CLOSURE_SHARE_S = saved
n, miss = contained(r, tv9); c = cl(r)
say(dict(control='S9_interrupted_closure_typed_skip_original_route_contained', outcome=r['outcome'], closure=str(c.get('status'))[:70], charged_s=round(r['phases_s'].get('support_closure', 0), 5), route=r['mechanism'].get('route'), published=n, K=r['K'], misses=len(miss), ok=(str(c.get('status', '')).startswith('SKIPPED') and r['mechanism'].get('route') == 'pac' and not miss and n == r['K'])))
# S10 all-original query expansion: a model where the closure aliases many variables; K = original; every coordinate exactly once; alias rows identical to the representative's
chain = [((i, i + 1), [3, 0, 0, 5]) for i in range(7)] + [((7, 8), rnd(4)), ((8, 9), rnd(6))]
p = write_uai('s10_expansion', [2] * 9 + [3], chain); t, _, tv, _ = truth(p); r = IG.solve(p, 6.0, **KW); n, miss = contained(r, tv); c = cl(r)
seen = [(a['var'], a['state']) for a in r['answers']]; once = (len(seen) == len(set(seen)) == 21)
rows0 = {a['state']: (a['lo'], a['hi']) for a in r['answers'] if a['var'] == 0}; alias_same = all({a['state']: (a['lo'], a['hi']) for a in r['answers'] if a['var'] == v} == rows0 for v in range(1, 8))
say(dict(control='S10_all_original_queries_expanded_once_aliases_identical', outcome=r['outcome'], closure=c.get('status'), representatives=c.get('representatives'), K=r['K'], effective_K=r.get('effective_K'), published=n, each_once=once, alias_rows_identical=alias_same, misses=len(miss), ok=(once and alias_same and not miss and n == r['K'] == 21 and (r.get('effective_K') or 99) < 21)))
# S11 PAC guarantee preserved: the reduced model still needs sampling; contained; the comparator path agrees
facs11 = [((a, b), rnd(4)) for a in range(nS) for b in range(a + 1, nS)]                                   # all-positive x clique: no bijection can be recognised inside it, so at table_cap 2^3 it stays uncontractible -> PAC
for i in range(nS): y0, y1 = nS + 2 * i, nS + 2 * i + 1; facs11 += [((i, y0), rnd(6)), ((y0, y1), ['1/3', 0, 0, 0, 0, '2/5', 0, '7/11', 0])]   # every y pair is a weighted 3-state bijection -> the closure APPLIES
p = write_uai('s11_pac', cards, facs11, evidence={nS + 3: 1}); t, _, tv11, _ = truth(p)
r_on = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted'); n1, miss1 = contained(r_on, tv11)
r_off = IG.solve(p, 12.0, force_approx=True, table_cap=1 << 3, enum_cap=1 << 4, mb_cap=1 << 10, route='pac', schedule='targeted', support_closure=False); n2, miss2 = contained(r_off, tv11)
say(dict(control='S11_pac_route_on_reduced_model_contained_and_comparator_agrees', on=dict(outcome=r_on['outcome'], closure=cl(r_on).get('status'), route=r_on['mechanism'].get('route'), draws=r_on['mechanism'].get('draws'), published=n1, K=r_on['K'], misses=len(miss1), effective_K=r_on.get('effective_K')), off=dict(outcome=r_off['outcome'], published=n2, misses=len(miss2)), ok=(cl(r_on).get('status') == 'APPLIED' and r_on['mechanism'].get('route') == 'pac' and not miss1 and n1 == r_on['K'] and not miss2 and n2 == r_off['K'] and r_on['K'] == r_off['K'])))
# S12 the development runs of the nine frozen-path suites with the closure ON: zero containment misses anywhere (path-expectation failures are expected and listed)
dev = sorted(glob.glob(os.path.join(os.path.dirname(OUT), 'CONTROLS_R18DEV_*.json'))); tot = 0; miss_tot = 0; path_fail = []
for f in dev:
    s_ = json.load(open(f))
    for row in s_['rows']:
        tot += 1; m_ = row.get('misses', 0)
        if isinstance(m_, int) and 'published' in row and 'hits' not in row and 'cache_entries' not in row: miss_tot += m_      # containment rows only (cache controls report cache misses under the same key)
        if not row['ok']: path_fail.append(row['control'][:40])
say(dict(control='S12_frozen_suites_with_closure_on_zero_containment_misses', suites=len(dev), controls=tot, containment_misses=miss_tot, path_expectation_failures=len(path_fail), examples=path_fail[:6], ok=(len(dev) >= 9 and miss_tot == 0)))
summary = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), version=IG.VERSION, all_ok=all(r['ok'] for r in rows), rows=rows); json.dump(summary, open(OUT, 'w'), indent=1, default=str)
print('ALL_OK' if summary['all_ok'] else 'FAILURES', sum(1 for r in rows if not r['ok']), 'of', len(rows))
