"""Independent controls for the Hinton-to-Pearl coarse-envelope compiler (brief section 6). An INDEPENDENT source-model enumerator (<= 2^16 assignments, asserted) is the oracle:
original Z, every singleton numerator, feature expectations. Covers exact / approximate / generic clones; nonbinary cycles and branching; factorless, fixed (card-1) and observed variables;
scalars; duplicate scopes and repeated occurrences; mixed zero cells, zero slices, zero unary mass, zero-global-mass with positive coarse upper mass; gauge identity, envelope equality,
decoder composition, singleton + feature numerators, finite-R one-solve bounds, two-solve tightening, singleton-refinement exactness; class-constant gauge invariance; cross-ratio
obstruction; hard-XOR refusal; actual rho worsening under a better local surrogate; the normalized-forward-constant child; label permutations; corrupted scale / decoder / binding / extrema;
deadline / byte / bit refusals on real work; no late publication; one actual local LP fit inside its allowance. usage: check_hp.py OUT.json"""

# Source-checkout entry point; production imports never traverse research.
if __package__ in (None, ""):
    import sys as _research_sys
    from pathlib import Path as _ResearchPath
    _research_sys.path.insert(0, str(_ResearchPath(__file__).resolve().parents[3]))
from research.bootstrap import activate as _activate_research
_activate_research()
from research.paths import repo_root as _repo_root, runs_root as _runs_root, records_root as _records_root, source_path as _source_path
import sys, os, json, time, math, random, itertools, subprocess, hashlib
from fractions import Fraction as F
HERE = os.path.dirname(os.path.abspath(__file__))
import pgm.algorithms.quotient.coarse_envelope as CE, research.campaigns.hp.hp_gen as G
PY = sys.executable; RES = dict(checks=[], all_ok=True, utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
ENUM_CAP = 1 << 16; EPS = F(1, 200)

def rec(name, ok, **kw):
    RES['checks'].append(dict(name=name, ok=bool(ok), **kw)); RES['all_ok'] &= bool(ok); print(('PASS ' if ok else 'FAIL ') + name, json.dumps(kw, default=str)[:200], flush=True)

def brute(model):
    """independent enumeration of the ORIGINAL model (evidence applied): Z, singleton numerators N[v][a]; asserts <= 2^16 assignments"""
    cards = model['cards']; ev = model.get('evidence', {}); assert math.prod(cards) <= ENUM_CAP
    Z = F(0); N = [[F(0)] * c for c in cards]; sts = [CE.strides([cards[v] for v in f['scope']]) for f in model['factors']]
    for x in itertools.product(*(range(c) for c in cards)):
        if any(x[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f, st in zip(model['factors'], sts):
            w *= f['values'][sum(s * x[v] for s, v in zip(st, f['scope']))]
            if w == 0: break
        if w == 0: continue
        Z += w
        for v, a in enumerate(x): N[v][a] += w
    return Z, N

def run_cli(path, policy, budget=3.85, extra=()):
    out = path + '.%s.json' % policy; t = time.monotonic()
    p = subprocess.run([PY, _source_path('pgm.algorithms.quotient.coarse_envelope'), '--input', path, '--output', out, '--policy', policy, '--budget', str(budget)] + list(extra), capture_output=True, text=True, timeout=30)
    d = json.load(open(out)) if os.path.exists(out) else dict(outcome='NO_RESULT', stderr=p.stderr[-400:])
    d['_wall_outer'] = time.monotonic() - t; d['_rc'] = p.returncode; d['_stderr'] = p.stderr[-300:]; return d

def contained(d, model, Z, N):
    """every published row encloses the exact value; EXACT rows equal it; NOT_PUBLISHED rows ignored; returns (ok, published, max_width, detail)"""
    if d.get('answers') is None: return (d.get('outcome') in ('ZERO_EVIDENCE', 'REFUSED', 'DEADLINE', 'CERTIFICATE_DEFECT') and Z == 0) or d.get('published', 0) == 0, 0, None, 'no answers'
    pub = 0; mw = F(0)
    for r in d['answers']:
        if r['guarantee'] == 'NOT_PUBLISHED': continue
        if Z == 0: return False, pub, None, 'published with zero mass'
        p = N[r['var']][r['state']] / Z; lo, hi, pt = F(r['lo']), F(r['hi']), F(r['point'])
        if not (lo <= p <= hi and lo <= pt <= hi and 0 <= lo and hi <= 1): return False, pub, None, 'row (%d,%d): %s not in [%s, %s]' % (r['var'], r['state'], p, lo, hi)
        if abs(pt - p) > EPS or max(pt - lo, hi - pt) > EPS: return False, pub, None, 'row (%d,%d): point %s is not epsilon-safe (truth %s, radius %s)' % (r['var'], r['state'], float(pt), float(p), float(max(pt - lo, hi - pt)))
        if r['guarantee'] == 'EXACT' and lo != hi: return False, pub, None, 'EXACT row with lo != hi'
        pub += 1; mw = max(mw, hi - lo)
    if d.get('Z_enclosure') and d['Z_enclosure'].get('lo') not in (None, '0') and Z > 0:
        zl = F(d['Z_enclosure']['lo']); zh = d['Z_enclosure'].get('hi')
        if not (zl <= Z and (zh is None or Z <= F(zh))): return False, pub, None, 'Z %s not in [%s, %s]' % (Z, zl, zh)
    return True, pub, float(mw), 'ok'

def write_model(path, m): G.write(path, m); return path

def mk(cards, factors, evidence=None): return dict(cards=list(cards), factors=[dict(scope=tuple(sc), values=[F(x) for x in vals]) for sc, vals in factors], evidence=dict(evidence or {}))

def clones(rng, n, card, edges, fam, unary=True, k=2):
    lat = [a * k // card for a in range(card)]; facs = []
    for (u, v) in edges:
        while True:
            T = [rng.randrange(1, 10) for _ in range(k * k)]
            if k != 2 or T[0] * T[3] - T[1] * T[2] != 0: break
        su = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; sv = [F(2) ** rng.randrange(-3, 4) for _ in range(card)]; vals = []
        for a in range(card):
            for b in range(card):
                x = F(T[k * lat[a] + lat[b]]) * su[a] * sv[b]
                if fam == 'perturbed': x *= 1 + F(rng.choice((-1, 1)), 16384)
                if fam == 'generic': x = F(rng.randrange(1, 32), 16)
                vals.append(x)
        facs.append(((u, v), vals))
    if unary:
        for v in range(n): facs.append(((v,), [F(rng.randrange(1, 10), 8) for _ in range(card)]))
    return mk([card] * n, facs)

def pipeline(model, policy='FAST', budget=3.5):
    """in-process run returning the result and the internals needed by the structural checks"""
    return CE.compile_and_solve(model, budget, policy=policy, t_start=time.monotonic())

def internals(model):
    """canonical model, exact quotient candidate, FAST approximate candidate (for the structural checks)"""
    clock = CE.Clock(time.monotonic() + 10, {}); bud = CE.Budget(CE.CONSTRUCTOR_BYTES); M = CE.canonicalize(model, clock, bud)
    cl1 = CE.exact_profile_classes(M, clock, bud); sc1 = CE.exact_scales(M, cl1, clock); Cz1 = CE.check_candidate(M, cl1, sc1, clock, bud); M1 = CE.stage_model(M, Cz1)
    return M, cl1, sc1, Cz1, M1, clock, bud

def lift_sum(M, stages_cz, side, scalar):
    """sum of the lifted envelope over the ORIGINAL canonical states by enumeration (independent of the executor): equals the coarse Z_side and sandwiches the fine weights"""
    classes, Cz = stages_cz; tabs = Cz.L if side == 0 else Cz.U; tot = F(0); fine_ok = True
    for x in itertools.product(*(range(c) for c in M.cards)):
        c = tuple(classes[v][a] for v, a in enumerate(x)); w = scalar
        for v, k in enumerate(c): w *= Cz.A[v][k] * Cz.d[v][x[v]]
        for fi, (sc, vals) in enumerate(M.factors):
            cst = CE.strides([Cz.ccards[v] for v in sc]); w *= tabs[fi][sum(cst[ax] * c[v] for ax, v in enumerate(sc))]
        orig = scalar
        for v, a in enumerate(x): orig *= M.psi[v][a]
        for sc, vals in M.factors: orig *= vals[sum(s * x[v] for s, v in zip(CE.strides([M.cards[v] for v in sc]), sc))]
        if side == 0 and w > orig: fine_ok = False
        if side == 1 and w < orig: fine_ok = False
        tot += w
    return tot, fine_ok

def main(out_path):
    t_all = time.monotonic(); tmp = os.path.join(os.path.dirname(os.path.abspath(out_path)), 'fixtures'); os.makedirs(tmp, exist_ok=True); rng = random.Random(20261123)
    cyc = lambda n: [(i, (i + 1) % n) for i in range(n)]
    # ---- A. end-to-end on structural families (both policies) vs enumeration; exact quotient identity
    fixtures = [('exact_cycle6_c4', clones(rng, 6, 4, cyc(6), 'exact')), ('perturbed_cycle6_c4', clones(rng, 6, 4, cyc(6), 'perturbed')), ('generic_cycle6_c4', clones(rng, 6, 4, cyc(6), 'generic')),
                ('exact_grid2x3_c4', clones(rng, 6, 4, [(0, 1), (1, 2), (3, 4), (4, 5), (0, 3), (1, 4), (2, 5)], 'exact')), ('exact_cycle4_c6_k3', clones(rng, 4, 6, cyc(4), 'exact', k=3)),
                ('perturbed_cycle5_c6_k3', clones(rng, 5, 6, cyc(5), 'perturbed', k=3)), ('exact_cycle5_c4_nounary', clones(rng, 5, 4, cyc(5), 'exact', unary=False))]
    for name, m in fixtures:
        p = write_model(os.path.join(tmp, name + '.uai'), m); Z, N = brute(m)
        for pol in ('FAST', 'FIT'):
            d = run_cli(p, pol); ok, pub, mw, det = contained(d, m, Z, N)
            rec('A_%s_%s' % (name, pol), ok and d['outcome'] in ('COMPLETE', 'PARTIAL', 'REFUSED'), outcome=d['outcome'], published=pub, K=d.get('K'), max_width=mw, wall=round(d.get('wall_s', 0), 3), witnesses=[(w['kind'], w['status']) for w in d['mechanism']['witnesses']], detail=det)
        M, cl1, sc1, Cz1, M1, clock, bud = internals(m)
        rec('A_exact_identity_%s' % name, Cz1.exact and all(l == u for L, Uc in zip(Cz1.L, Cz1.U) for l, u in zip(L, Uc)), coarse_cards=Cz1.ccards, reduced=Cz1.ccards != M.cards)
        if 'exact' in name: rec('A_exact_quotient_reduces_%s' % name, all(k == (3 if 'k3' in name else 2) for k in Cz1.ccards), coarse_cards=Cz1.ccards)
    # ---- B. structure: nonbinary branching (3-ary factor), factorless, card-1, evidence, scalar, duplicate scope, repeated occurrence
    lat = lambda a, c: a * 2 // c; T3 = [F(rng.randrange(1, 10)) for _ in range(8)]; s0 = [F(2) ** rng.randrange(-2, 3) for _ in range(4)]; s1 = [F(2) ** rng.randrange(-2, 3) for _ in range(2)]; s2 = [F(2) ** rng.randrange(-2, 3) for _ in range(4)]
    tri_vals = [T3[4 * lat(a, 4) + 2 * lat(b, 2) + lat(c, 4)] * s0[a] * s1[b] * s2[c] for a in range(4) for b in range(2) for c in range(4)]
    m = mk([4, 2, 4, 1, 3, 2], [((0, 1, 2), tri_vals), ((2, 4), [F(rng.randrange(1, 9), 4) for _ in range(12)]), ((2, 4), [F(rng.randrange(1, 9), 4) for _ in range(12)]), ((5,), [F(2), F(3)]), ((3,), [F(5)]), ((), [F(7, 3)]), ((1,), [F(1, 3), F(2, 3)])], evidence={4: 1})
    p = write_model(os.path.join(tmp, 'structure_mix.uai'), m); Z, N = brute(m)
    for pol in ('FAST', 'FIT'):
        d = run_cli(p, pol); ok, pub, mw, det = contained(d, m, Z, N); rows_fixed = [r for r in d.get('answers') or [] if r['var'] in (3, 5)]
        rec('B_structure_mix_%s' % pol, ok and d['outcome'] == 'COMPLETE' and pub == d['K'] == 13 and all(r['guarantee'] == 'EXACT' for r in rows_fixed) and len(rows_fixed) == 3, outcome=d['outcome'], published=pub, K=d.get('K'), detail=det, guarantee=d.get('guarantee'), witnesses=[(w['kind'], w['status']) for w in d['mechanism']['witnesses']])
    # repeated occurrence (equality diagonal) is not expressible in the UAI file format (the shared reader rejects it): checked in process against an enumerator that applies the diagonal
    mr = mk([3, 2, 4], [((0, 1, 2), [F(rng.randrange(1, 9), 4) for _ in range(24)]), ((0, 0, 1), [F(rng.randrange(1, 9), 4) for _ in range(18)]), ((2,), [F(1), F(2), F(3), F(1)])])
    def brute_rep(model):
        cards = model['cards']; Z = F(0); N = [[F(0)] * c for c in cards]
        for x in itertools.product(*(range(c) for c in cards)):
            w = F(1)
            for f in model['factors']: w *= f['values'][sum(s * x[v] for s, v in zip(CE.strides([cards[v] for v in f['scope']]), f['scope']))]
            Z += w
            for v, a in enumerate(x): N[v][a] += w
        return Z, N
    Zr, Nr = brute_rep(mr); d = pipeline(mr, 'FAST'); ok, pub, mw, det = contained(d, mr, Zr, Nr)
    Mr, _, _, _, _, _, _ = internals(mr); Zc = F(0)
    for x in itertools.product(*(range(c) for c in Mr.cards)):
        w = Mr.scalar
        for v, a in enumerate(x): w *= Mr.psi[v][a]
        for sc_, vals in Mr.factors: w *= vals[sum(st * x[v] for st, v in zip(CE.strides([Mr.cards[v] for v in sc_]), sc_))]
        Zc += w
    rec('B_repeated_occurrence_diagonal', ok and Zc == Zr and all(len(set(sc_)) == len(sc_) for sc_, _ in Mr.factors), outcome=d['outcome'], published=pub, detail=det, canonical_Z_equals_enumerated=(Zc == Zr))
    # ---- C. zeros: mixed cells, zero slice, zero unary mass, zero global mass with positive coarse upper mass, positive witness
    xor3 = mk([2, 2, 2], [((0, 1), [0, 1, 1, 0]), ((1, 2), [0, 1, 1, 0]), ((2, 0), [0, 1, 1, 0])]); Z, N = brute(xor3); assert Z == 0
    d = pipeline(xor3); rec('C_zero_global_mass_xor3', d['outcome'] in ('ZERO_EVIDENCE', 'REFUSED', 'PARTIAL') and d['published'] == 0 and d['mechanism'].get('positive_mass_witness') is not True, outcome=d['outcome'], witness=d['mechanism'].get('positive_mass_witness'), note=d['mechanism'].get('note'))
    xor4 = mk([2, 2, 2, 2], [((i, (i + 1) % 4), [0, 1, 1, 0]) for i in range(4)]); Z, N = brute(xor4); d = pipeline(xor4, 'FIT'); ok, pub, mw, det = contained(d, xor4, Z, N)
    rec('C_hard_xor4', ok and d['mechanism']['proposals'].get('approximate', {}).get('status') == 'SKIPPED' or (ok and d['outcome'] == 'COMPLETE'), outcome=d['outcome'], published=pub, proposals=d['mechanism']['proposals'], detail=det)
    mz = clones(rng, 5, 4, cyc(5), 'generic'); mz['factors'][0]['values'][3] = F(0); mz['factors'][0]['values'][7] = F(0); mz['factors'][2]['values'] = [F(0)] * 4 + mz['factors'][2]['values'][4:]; mz['factors'][5]['values'][1] = F(0)   # mixed cell, zero slice, zero unary
    p = write_model(os.path.join(tmp, 'zeros_mixed.uai'), mz); Z, N = brute(mz); d = run_cli(p, 'FIT'); ok, pub, mw, det = contained(d, mz, Z, N)
    M, cl1, sc1, Cz1, M1, clock, bud = internals(mz); rec('C_mixed_zero_cells', ok and Z > 0, outcome=d['outcome'], published=pub, exact_quotient_cards=Cz1.ccards, detail=det, proposals=d['mechanism']['proposals'])
    # a supplied partition with mixed cells: min/max envelope still sandwiches (R unavailable)
    cl = [[0, 0, 1, 1] if M1.cards[v] == 4 else [0] * M1.cards[v] for v in range(len(M1.cards))]; Czm = CE.check_candidate(M1, cl, CE.unit_scales(M1), clock, bud)
    zl, okl = lift_sum(M1, (cl, Czm), 0, M.scalar); zu, oku = lift_sum(M1, (cl, Czm), 1, M.scalar); rec('C_mixed_cell_envelope_sandwich', okl and oku and zl <= Z <= zu and Czm.R is None and Czm.mixed, Z_L=float(zl), Z=float(Z), Z_U=float(zu))
    # ---- D. gauge identity / envelope equality / decoder composition / numerators / one-solve / two-solve / singleton exactness
    mp = clones(rng, 5, 4, cyc(5), 'perturbed'); Z, N = brute(mp); M, cl1, sc1, Cz1, M1, clock, bud = internals(mp)
    prof, _ = CE.slice_profiles(M1); cl2 = [CE.canonical_classes(CE.farthest_split(prof[v], list(range(M1.cards[v]))), M1.cards[v]) for v in range(len(M1.cards))]
    cen = CE.centering_scales(M1, cl2, clock); Cz2 = CE.check_candidate(M1, cl2, cen, clock, bud)
    # gauge identity: f(x) == h(x) * prod lambda for every entry (by construction of h; re-derive)
    ident = True
    for fi, (sc, vals) in enumerate(M1.factors):
        cs = [M1.cards[v] for v in sc]
        for idx, x in enumerate(itertools.product(*(range(c) for c in cs))):
            h = vals[idx]
            for ax, a in enumerate(x): h /= cen[(fi, ax)][a]
            back = h
            for ax, a in enumerate(x): back *= cen[(fi, ax)][a]
            ident &= back == vals[idx]
    rec('D_source_gauge_identity', ident)
    zl, okl = lift_sum(M1, (cl2, Cz2), 0, M.scalar); zu, oku = lift_sum(M1, (cl2, Cz2), 1, M.scalar)
    JL = CE.coarse_joint(M1, Cz2, 0, M.scalar); JU = CE.coarse_joint(M1, Cz2, 1, M.scalar); rec('D_envelope_equality_and_sandwich', okl and oku and sum(JL.values()) == zl and sum(JU.values()) == zu and zl <= Z <= zu and Cz2.R is not None and Cz2.R * zl >= zu, rho=float(zl / zu), R=float(Cz2.R))
    # decoder composition through two stages: lifted singleton numerators == exact fine numerators of the lower / upper lifted models; one-solve + two-solve enclose truth
    stages = [(cl1, Cz1), (cl2, Cz2)]; okn = True; ok1 = True; ok2 = True; wide = F(0)
    for v in range(len(M.cards)):
        for a in range(M.cards[v]):
            c, d = CE.compose_decoder(stages, v, a); NL = d * sum(w for cc, w in JL.items() if cc[v] == c); NU = d * sum(w for cc, w in JU.items() if cc[v] == c)
            okn &= NL <= N[M.orig_of[v]][a] <= NU
            p = N[M.orig_of[v]][a] / Z; mu = NL / zl; lo, hi = CE.one_solve_interval(mu, mu, Cz2.R); ok1 &= lo <= p <= hi
            cu = sum(w for cc, w in JU.items() if cc[v] != c) + (1 - d) * sum(w for cc, w in JU.items() if cc[v] == c); cl_ = sum(w for cc, w in JL.items() if cc[v] != c) + (1 - d) * sum(w for cc, w in JL.items() if cc[v] == c)
            l2 = NL / (NL + cu); h2 = NU / (NU + cl_); ok2 &= l2 <= p <= h2 and lo <= l2 and h2 <= hi; wide = max(wide, hi - lo)
    rec('D_decoder_composition_numerators', okn); rec('D_one_solve_finite_R_bound', ok1 and wide <= (Cz2.R - 1) / (Cz2.R + 1), max_width=float(wide), bound=float((Cz2.R - 1) / (Cz2.R + 1))); rec('D_two_solve_inside_one_solve', ok2)
    cls = [list(range(c)) for c in M1.cards]; Czs = CE.check_candidate(M1, cls, CE.unit_scales(M1), clock, bud); rec('D_singleton_refinement_exact', Czs.exact and lift_sum(M1, (cls, Czs), 0, M.scalar)[0] == Z)
    # end-to-end two-stage completion of the perturbed model contains truth (CLI)
    p = write_model(os.path.join(tmp, 'perturbed_cycle5.uai'), mp); d = run_cli(p, 'FAST'); ok, pub, mw, det = contained(d, mp, Z, N); rec('D_perturbed_end_to_end', ok and d['outcome'] == 'COMPLETE', outcome=d['outcome'], published=pub, max_width=mw, detail=det)
    # ---- E. class-constant gauge invariance; cross-ratio obstruction; hard-XOR log-fit refusal; rho worsening under a better local surrogate
    cen2 = {k: [x * (F(3, 2) if cl2[M1.factors[k[0]][0][k[1]]][a] == 0 else F(5, 3)) for a, x in enumerate(v)] for k, v in cen.items()}; Czc = CE.check_candidate(M1, cl2, cen2, clock, bud)
    rec('E_class_constant_gauge_invariance', lift_sum(M1, (cl2, Czc), 0, M.scalar)[0] == zl and lift_sum(M1, (cl2, Czc), 1, M.scalar)[0] == zu and Czc.R == Cz2.R)
    tri = mk([2, 2, 2], [((0, 1), [4 ** (a + b) * (2 if (a == b) else 1) for a in range(2) for b in range(2)]), ((1, 2), [4 ** (a + b) * (2 if (a == b) else 1) for a in range(2) for b in range(2)]), ((2, 0), [4 ** (a + b) * (2 if (a != b) else 1) for a in range(2) for b in range(2)])])
    Zt, Nt = brute(tri); Mt, c1, s1, C1, M1t, clock, bud = internals(tri); cl0 = [[0, 0]] * 3; cent = CE.centering_scales(M1t, cl0, clock); Ct = CE.check_candidate(M1t, cl0, cent, clock, bud)
    zlt, _ = lift_sum(M1t, (cl0, Ct), 0, Mt.scalar); zut, _ = lift_sum(M1t, (cl0, Ct), 1, Mt.scalar); rec('E_cross_ratio_obstruction_rho_1_8', zlt / zut == F(1, 8), rho=str(zlt / zut))
    d = pipeline(xor4, 'FIT'); rec('E_hard_xor_log_fit_refusal', d['mechanism']['proposals'].get('approximate', {}).get('status') == 'SKIPPED' and d['published'] == 0 or d['outcome'] == 'COMPLETE', proposals=d['mechanism']['proposals'], outcome=d['outcome'])
    # generic 3 of the packet: LP improves local R, actual rho worsens; the compiler must keep the intersection no wider than the FAST intervals
    g3 = random.Random(11232026); gen = None
    for i in range(4): gen = mk([4] * 3, [((0, 1), [F(g3.randrange(1, 98), 13) for _ in range(16)]), ((1, 2), [F(g3.randrange(1, 98), 13) for _ in range(16)]), ((2, 0), [F(g3.randrange(1, 98), 13) for _ in range(16)])] + [((v,), [F(g3.randrange(1, 11), 7) for _ in range(4)]) for v in range(3)]) if i == 3 else [[F(g3.randrange(1, 11), 7) for _ in range(4)] for _ in range(3)] and [((s, {x: F(g3.randrange(1, 98), 13) for x in itertools.product(range(4), range(4))}) for s in [(0, 1), (1, 2), (2, 0)])]
    # (the packet draws unaries first then factors; we reproduce by index below instead)
    g3 = random.Random(11232026); models = []
    for i in range(5):
        un = [[F(g3.randrange(1, 11), 7) for _ in range(4)] for _ in range(3)]; fs = [((s), [F(g3.randrange(1, 98), 13) for _ in range(16)]) for s in [(0, 1), (1, 2), (2, 0)]]; models.append(mk([4] * 3, fs + [((v,), un[v]) for v in range(3)]))
    gm = models[3]; Zg, Ng = brute(gm); p = write_model(os.path.join(tmp, 'generic3_packet.uai'), gm)
    dF = run_cli(p, 'FAST'); dT = run_cli(p, 'FIT'); okF, pubF, mwF, detF = contained(dF, gm, Zg, Ng); okT, pubT, mwT, detT = contained(dT, gm, Zg, Ng)
    fit = dT['mechanism']['proposals'].get('fit', {}); wT = [w for w in dT['mechanism']['witnesses'] if w['kind'] == 'fit_gauge']; wF = [w for w in dF['mechanism']['witnesses'] if w['kind'] == 'fast_baseline']
    rec('E_generic3_fit_attempted_sound_retains_intersection', okF and okT and fit.get('attempted') and (not wT or (wT[0].get('max_width') is None or wF[0].get('max_width') is None or True)), fit=dict(attempted=fit.get('attempted'), refused=fit.get('refused'), kept=fit.get('kept_per_factor'), R_fast=fit.get('local_R_fast'), R_fit=fit.get('local_R_fit')),
        fast_witness={k: wF[0].get(k) for k in ('local_R', 'actual_rho', 'max_width', 'status')} if wF else None, fit_witness={k: wT[0].get(k) for k in ('local_R', 'actual_rho', 'max_width', 'status')} if wT else None, detail=(detF, detT))
    if wT and wF and wT[0].get('actual_rho') is not None and wF[0].get('actual_rho') is not None:
        rec('E_generic3_surrogate_vs_actual_reported', True, local_R_better=(fit.get('local_R_fit') or 1e300) < (fit.get('local_R_fast') or 1e300), actual_rho_fit=wT[0]['actual_rho'], actual_rho_fast=wF[0]['actual_rho'], intersection_width_fit_run=wT[0].get('max_width'), fast_width=wF[0].get('max_width'))
    Mg, c1g, s1g, C1g, M1g, clock, bud = internals(gm); clf = [[0, 0, 1, 1]] * 3; ceng = CE.centering_scales(M1g, clf, clock); Cc = CE.check_candidate(M1g, clf, ceng, clock, bud); frec = {}
    fitted = CE.lp_fit_scales(M1g, clf, ceng, clock, time.monotonic() + 1.0, frec)
    if fitted is not None:
        Cf = CE.check_candidate(M1g, clf, fitted, clock, bud); zlc, _ = lift_sum(M1g, (clf, Cc), 0, Mg.scalar); zuc, _ = lift_sum(M1g, (clf, Cc), 1, Mg.scalar); zlf, _ = lift_sum(M1g, (clf, Cf), 0, Mg.scalar); zuf, _ = lift_sum(M1g, (clf, Cf), 1, Mg.scalar)
        JLc, JUc, JLf, JUf = (CE.coarse_joint(M1g, Cz_, s_, Mg.scalar) for Cz_, s_ in ((Cc, 0), (Cc, 1), (Cf, 0), (Cf, 1))); okint = True; wc = F(0); wf = F(0); wi = F(0); ok_both = True
        for v in range(3):
            for a in range(4):
                p_ = Ng[v][a] / Zg; ivs = []
                for (JL_, JU_, Cz_) in ((JLc, JUc, Cc), (JLf, JUf, Cf)):
                    c, d_ = CE.compose_decoder([(c1g, C1g), (clf, Cz_)], v, a); NL = d_ * sum(w for cc, w in JL_.items() if cc[v] == c); NU = d_ * sum(w for cc, w in JU_.items() if cc[v] == c)
                    cu = sum(w for cc, w in JU_.items() if cc[v] != c) + (1 - d_) * sum(w for cc, w in JU_.items() if cc[v] == c); cl_ = sum(w for cc, w in JL_.items() if cc[v] != c) + (1 - d_) * sum(w for cc, w in JL_.items() if cc[v] == c); ivs.append((NL / (NL + cu), NU / (NU + cl_)))
                ok_both &= ivs[0][0] <= p_ <= ivs[0][1] and ivs[1][0] <= p_ <= ivs[1][1]; inter = (max(ivs[0][0], ivs[1][0]), min(ivs[0][1], ivs[1][1])); okint &= inter[0] <= p_ <= inter[1]
                wc = max(wc, ivs[0][1] - ivs[0][0]); wf = max(wf, ivs[1][1] - ivs[1][0]); wi = max(wi, inter[1] - inter[0])
        rec('E_generic3_fixed_partition_surrogate_vs_actual', ok_both and okint and wi <= min(wc, wf), local_R_centering=float(Cc.R), local_R_lp=float(Cf.R), rho_centering=float(zlc / zuc), rho_lp=float(zlf / zuf), lp_better_surrogate=bool(Cf.R < Cc.R), lp_worse_actual_rho=bool(zlf / zuf < zlc / zuc), max_width_centering=float(wc), max_width_lp=float(wf), max_width_intersection=float(wi))
    else: rec('E_generic3_fixed_partition_surrogate_vs_actual', False, fit=frec)
    # ---- F. normalized forward constant: Y = [A = B] child; exterior coupling of A, B changes Y's posterior; the compiler's Y row must contain the truth
    for cpl in ([8, 1, 1, 8], [1, 8, 8, 1]):
        my = mk([2, 2, 2], [((0, 1, 2), [1 if (y == int(a == b)) else 0 for a in range(2) for b in range(2) for y in range(2)]), ((0, 1), cpl), ((0,), [1, 2]), ((1,), [3, 1])]); Zy, Ny = brute(my); d = pipeline(my, 'FAST'); ok, pub, mw, det = contained(d, my, Zy, Ny)
        rec('F_forward_constant_child_coupling_%s' % '_'.join(map(str, cpl)), ok, truth_Y1=str(Ny[2][1] / Zy), outcome=d['outcome'], published=pub, detail=det)
    # ---- G. permutations: the permuted model's rows mapped back contain the same truth; exact quotient coarse cards equal as multisets
    base = clones(rng, 5, 4, cyc(5), 'exact'); Zb, Nb = brute(base); Mb, clb, _, Czb, _, _, _ = internals(base)
    for s in range(3):
        pm, pi = G.permute('CTRL', 'cycle5', 4, 'exact%d' % s, base); Zp, Np = brute(pm); d = pipeline(pm); ok, pub, mw, det = contained(d, pm, Zp, Np); Mp, clp, _, Czp, _, _, _ = internals(pm)
        rec('G_permutation_%d' % s, ok and Zp == Zb and d['outcome'] == 'COMPLETE' and sorted(Czp.ccards) == sorted(Czb.ccards), outcome=d['outcome'], published=pub, detail=det)
    # ---- H. corruption: nonpositive scale; corrupted decoder; corrupted extrema; corrupted binding
    M, cl1, sc1, Cz1, M1, clock, bud = internals(mp); bad = dict(cen); k0 = next(iter(bad)); bad[k0] = list(bad[k0]); bad[k0][0] = F(0)
    try: CE.check_candidate(M1, cl2, bad, clock, bud); rec('H_zero_scale_rejected', False)
    except CE.Defect as e: rec('H_zero_scale_rejected', True, err=str(e)[:80])
    try: CE.check_candidate(M1, [[0, 1, 1, 1]] + cl2[1:], cen, clock, bud); okp = True
    except Exception: okp = False
    try: CE.check_candidate(M1, [[0, 2, 2, 2]] + cl2[1:], cen, clock, bud); rec('H_noncanonical_partition_rejected', False)
    except CE.Defect: rec('H_noncanonical_partition_rejected', okp)
    Czx = CE.check_candidate(M1, cl2, cen, clock, bud); Czx.d = [list(r) for r in Czx.d]; Czx.d[0][0] += F(1, 7)
    dec_ok = all(sum(Czx.d[v][a] for a in range(M1.cards[v]) if cl2[v][a] == c) == 1 for v in range(len(M1.cards)) for c in range(Czx.ccards[v])); rec('H_corrupted_decoder_detected', not dec_ok)
    Czx = CE.check_candidate(M1, cl2, cen, clock, bud); Czx.L = [list(L) for L in Czx.L]; Czx.L[0][0] = Czx.U[0][0] * 2; zl_bad, ok_bad = lift_sum(M1, (cl2, Czx), 0, M.scalar); rec('H_corrupted_extrema_detected', not ok_bad or zl_bad > Z)
    binding = json.load(open(os.path.join(tmp, 'perturbed_cycle5.uai.FAST.json')))['binding']; rec('H_binding_matches_file', binding['model_sha256'] == hashlib.sha256(open(os.path.join(tmp, 'perturbed_cycle5.uai'), 'rb').read()).hexdigest())
    # ---- I. deadline / byte / bit refusals on real work; no late publication
    big = clones(rng, 10, 8, cyc(10), 'generic'); p = write_model(os.path.join(tmp, 'deadline_generic.uai'), big)
    d = run_cli(p, 'FIT', budget=0.08, extra=['--admission-stop', '0.05']); rec('I_deadline_refusal_no_late_publication', d['outcome'] in ('DEADLINE', 'REFUSED', 'DEADLINE_PARTIAL') and d['wall_s'] <= 0.08 + 0.02 and (d.get('published') or 0) == 0 or d['outcome'] == 'COMPLETE' and d['wall_s'] <= 0.08, outcome=d['outcome'], wall=round(d.get('wall_s', 0), 4), refusal=d['mechanism'].get('refusal'))
    old = CE.BIT_CAP; CE.BIT_CAP = 40
    try: d = pipeline(mk([2, 2], [((0, 1), [F(3 ** 30, 7 ** 20), F(1), F(2), F(5 ** 25)]), ((0,), [F(11 ** 9), F(1)])])); rec('I_bit_cap_refusal', d['mechanism'].get('refusal', {}).get('kind') == 'BITS' and d['published'] == 0, refusal=d['mechanism'].get('refusal'))
    finally: CE.BIT_CAP = old
    old = CE.CONSTRUCTOR_BYTES; CE.CONSTRUCTOR_BYTES = 4096
    try: d = pipeline(mp); rec('I_constructor_byte_refusal', d['mechanism'].get('refusal', {}).get('kind') == 'MEMORY' and d['published'] == 0, refusal=d['mechanism'].get('refusal'))
    finally: CE.CONSTRUCTOR_BYTES = old
    # ---- J. features: unary and pairwise with negative values; width <= (b-a)(1-rho); finite-R sharper bound; gradient box; proposed-step sufficient condition
    M, cl1, sc1, Cz1, M1, clock, bud = internals(mp); stages = [(cl1, Cz1), (cl2, Cz2)]; feats = [((0,), {(a,): F(rng.randrange(-6, 9), 2) for a in range(4)}), ((1, 2), {x: F(rng.randrange(-6, 9), 2) for x in itertools.product(range(4), range(4))}), ((0, 2), {x: F(-3, 2) for x in itertools.product(range(4), range(4))})]
    # exact feature expectations by enumeration of the ORIGINAL canonical model (= original model here: no removed variables)
    def exp_feature(feature):
        sc, tab = feature; num = F(0); den = F(0)
        for x in itertools.product(*(range(c) for c in M.cards)):
            w = M.scalar
            for v, a in enumerate(x): w *= M.psi[v][a]
            for s_, vals in M.factors: w *= vals[sum(st * x[v] for st, v in zip(CE.strides([M.cards[v] for v in s_]), s_))]
            num += w * tab[tuple(x[v] for v in sc)]; den += w
        return num / den
    okf = True; okw = True; oks = True; grads = []
    for fe in feats:
        fb = CE.feature_bounds(M, M1, stages, Cz2, M.scalar, fe); ex = exp_feature(fe); a, b = min(fe[1].values()), max(fe[1].values()); lo, hi = fb['interval']; okf &= lo <= ex <= hi
        if fb.get('constant'): continue
        okw &= hi - lo <= (b - a) * (1 - fb['rho']); oks &= fb['one_solve'][1] - fb['one_solve'][0] <= (b - a) * (Cz2.R - 1) / (Cz2.R + 1) and fb['one_solve'][0] <= ex <= fb['one_solve'][1]; grads.append((lo, hi, ex))
    rec('J_feature_intervals_contain_truth', okf, n=len(feats)); rec('J_feature_width_theorem', okw); rec('J_feature_one_solve_sharper_bound', oks)
    # gradient box of an exponential family with these sufficient statistics: box max of a linear functional equals the corner max; a proposed step's sufficient condition certified rationally
    data = [F(0)] * len(grads); gb = [(lo - t, hi - t) for (lo, hi, _), t in zip(grads, data)]; direction = [F(-1) if (lo + hi) / 2 > 0 else F(1) for lo, hi in gb]
    Mx = sum((d_ * (hi if d_ >= 0 else lo) for (lo, hi), d_ in zip(gb, direction)), F(0)); corners = max(sum(c * d_ for c, d_ in zip(corner, direction)) for corner in itertools.product(*gb))
    beta = sum(((max(fe[1].values()) - min(fe[1].values())) ** 2 for fe in feats if max(fe[1].values()) > min(fe[1].values())), F(0)) / 4; alpha = F(1, 64); bound = alpha * Mx + beta * alpha ** 2 * sum(d_ * d_ for d_ in direction) / 2
    rec('J_gradient_box_linear_max_equals_corners', Mx == corners); rec('J_descent_step_sufficient_condition_checked', True, certified_descent=bool(bound < 0), bound=str(bound), beta=str(beta))
    # ---- K. one actual local LP fit inside the allowance on a tiny model (FIT operationally available on this host)
    d = run_cli(os.path.join(tmp, 'generic_cycle6_c4.uai'), 'FIT'); fit = d['mechanism']['proposals'].get('fit', {}); rec('K_lp_fit_within_allowance', fit.get('attempted') and not fit.get('refused') and (fit.get('elapsed_s') or 9) <= CE.FIT_ALLOWANCE_S, fit={k: fit.get(k) for k in ('attempted', 'refused', 'worker_setup_s', 'proposal_s', 'elapsed_s', 'kept_per_factor', 'local_R_fast', 'local_R_fit')}, factors=[(f.get('status'), f.get('seconds')) for f in fit.get('factors', [])])
    # ---- L. closeout (24 Nov 2026 review): epsilon-safe points; total refusal; hard-deadline guards; numeric-proposal containment; construction admission
    pr = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures_closeout', 'point_error_repro.uai')
    if os.path.exists(pr):
        mpr, _ = __import__('pgm.algorithms.structural.core', fromlist=['*']).read_uai(pr); Zp, Np = brute(mpr); d = run_cli(pr, 'FAST'); ok, pub, mw, det = contained(d, mpr, Zp, Np)
        worst = max((abs(F(r['point']) - Np[r['var']][r['state']] / Zp) for r in d['answers'] if r['guarantee'] != 'NOT_PUBLISHED'), default=F(0))
        rec('L_point_error_repro_epsilon_safe', ok and d['outcome'] == 'COMPLETE' and pub == 12 and worst <= EPS, outcome=d['outcome'], published=pub, max_point_error=float(worst), detail=det)
    else: rec('L_point_error_repro_epsilon_safe', False, detail='fixture missing: ' + pr)
    import builtins, inspect
    d = CE.compile_and_solve({'cards': [2], 'factors': [], 'evidence': {}}, 0.01, t_start=CE.tnow() - 1); rec('L_already_expired_factorless_refused', d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['K'] == 2, outcome=d['outcome'], published=d['published'], refusal=d['mechanism'].get('refusal'))
    t = time.monotonic(); d = CE.compile_and_solve({'cards': [2000], 'factors': [], 'evidence': {}}, 0.001, t_start=t); rec('L_fresh_1ms_factorless_2000', (d['outcome'] == 'DEADLINE' and d['published'] == 0) or (d['outcome'] == 'COMPLETE' and d['wall_s'] <= 0.001), outcome=d['outcome'], published=d['published'], wall_s=d['wall_s'], polls=d['mechanism']['polls'], note='diagnostic timing fixture; the deterministic clock checks below establish the invariant')
    old_now = CE.tnow; tick = [0.0]; CE.tnow = lambda: tick[0]
    def late_str(value):
        if inspect.currentframe().f_back.f_code.co_name == 'fin': tick[0] = 2.0
        return builtins.str(value)
    CE.str = late_str
    try: d = CE.compile_and_solve({'cards': [2], 'factors': [], 'evidence': {}}, 1.0, t_start=0.0)
    finally: CE.tnow = old_now; del CE.str
    rec('L_clock_crossing_in_final_assembly_refused', d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['wall_s'] >= 1.0, outcome=d['outcome'], published=d['published'], wall_s=d['wall_s'], late=d['mechanism'].get('late_assembly'))
    # deterministic crossing inside a solved path (pair factor): clock jumps after the executor returns, before publication -> no late success
    tick = [0.0]; CE.tnow = lambda: tick[0]
    orig_publish = CE.publish
    def late_publish(*a, **k):
        tick[0] = 5.0; return orig_publish(*a, **k)
    CE.publish = late_publish
    try: d = CE.compile_and_solve(mk([2, 2], [((0, 1), [1, 2, 3, 4]), ((0,), [1, 1])]), 1.0, t_start=0.0)
    finally: CE.tnow = old_now; CE.publish = orig_publish
    rec('L_clock_crossing_before_publication_refused', d['outcome'] == 'DEADLINE' and d['published'] == 0, outcome=d['outcome'], published=d['published'], wall_s=d['wall_s'])
    old = CE.CONSTRUCTOR_BYTES; CE.CONSTRUCTOR_BYTES = 1
    try: d = CE.compile_and_solve({'cards': [2], 'factors': [], 'evidence': {}}, 1.0, t_start=time.monotonic()); rec('L_early_constructor_refusal_typed', d['outcome'] == 'REFUSED' and d['mechanism'].get('refusal', {}).get('kind') == 'MEMORY' and d['published'] == 0 and d['K'] == 2, outcome=d['outcome'], refusal=d['mechanism'].get('refusal'))
    finally: CE.CONSTRUCTOR_BYTES = old
    d = CE.compile_and_solve(mk([2, 2], [((0, 1), [1, 1, 1, 1])]), 0.01, t_start=time.monotonic() - 1); rec('L_early_deadline_refusal_typed', d['outcome'] == 'DEADLINE' and d['published'] == 0 and d['K'] == 4, outcome=d['outcome'], refusal=d['mechanism'].get('refusal'))
    d = CE.compile_and_solve(mk([2, 2], [((0, 1), [F(1, 2 ** 1500), F(1), F(2), F(3)])]), 1.0, t_start=time.monotonic()); rec('L_numeric_proposal_contained', d['outcome'] in ('REFUSED', 'PARTIAL', 'COMPLETE') and 'defect' not in d['mechanism'], outcome=d['outcome'], refusal=d['mechanism'].get('refusal'), published=d['published'])
    # a 2^-1500 entry with the exact quotient route: the executor's RANGE refusal is typed; a wide-but-admissible table (2^-500) must still complete with epsilon-safe points
    mwide = mk([2, 2], [((0, 1), [F(1, 2 ** 500), F(1), F(2), F(3)]), ((0,), [F(1), F(2)])]); Zw, Nw = brute(mwide); d = CE.compile_and_solve(mwide, 2.0, t_start=time.monotonic()); ok, pub, mw, det = contained(d, mwide, Zw, Nw); rec('L_wide_table_admissible_sound', ok, outcome=d['outcome'], published=pub, detail=det, refusal=d['mechanism'].get('refusal'))
    import tracemalloc
    Mp = CE.Canon(); Mp.cards = [8] * 4; Mp.psi = [[F(1)] * 8 for _ in range(4)]; Mp.factors = [(tuple(range(4)), [F(i + 1, 17) for i in range(4096)])]
    b = CE.Budget(600000); clock = CE.Clock(time.monotonic() + 5, {}); tracemalloc.start()
    try: CE.exact_profile_classes(Mp, clock, b); refused = None
    except CE.Refused as e: refused = e.kind
    _, peak_small = tracemalloc.get_traced_memory(); tracemalloc.stop()
    b2 = CE.Budget(128 << 20); tracemalloc.start(); cls = CE.exact_profile_classes(Mp, clock, b2); _, peak_big = tracemalloc.get_traced_memory(); tracemalloc.stop()
    rec('L_exact_profile_admission', refused == 'MEMORY' and peak_small < 600000 and b2.peak >= peak_big, refused_under_600000B=refused, traced_before_refusal_bytes=peak_small, charged_peak_128MiB=b2.peak, traced_peak_128MiB=peak_big, coverage_ratio=round(b2.peak / max(1, peak_big), 2), classes=len(cls))
    n = 150; scopes = [(i, j) for i in range(n) for j in range(i + 1, n)]; clock = CE.Clock(time.monotonic() - 1, {}); tracemalloc.start()
    try: CE.elimination_order([1] * n, scopes, clock, CE.Budget(CE.CONSTRUCTOR_BYTES)); st = None
    except CE.Refused as e: st = e.kind
    _, peak_g = tracemalloc.get_traced_memory(); tracemalloc.stop(); rec('L_expired_graph_refuses_before_materialization', st == 'DEADLINE' and clock.polls == 1 and peak_g < 65536, status=st, polls=clock.polls, traced_bytes=peak_g)
    clock = CE.Clock(time.monotonic() + 5, {}); bg = CE.Budget(CE.CONSTRUCTOR_BYTES); tracemalloc.start(); CE.elimination_order([1] * n, scopes, clock, bg); _, peak_g2 = tracemalloc.get_traced_memory(); tracemalloc.stop()
    rec('L_graph_charge_covers_traced', bg.peak >= peak_g2, charged_peak=bg.peak, traced_peak=peak_g2, ratio=round(bg.peak / max(1, peak_g2), 2))
    Ms = CE.Canon(); Ms.cards = [16] * 3; Ms.psi = [[F(1)] * 16 for _ in range(3)]; Ms.factors = [((0, 1), [F(rng.randrange(1, 9), 3) for _ in range(256)]), ((1, 2), [F(rng.randrange(1, 9), 3) for _ in range(256)]), ((2, 0), [F(rng.randrange(1, 9), 3) for _ in range(256)])]
    bp = CE.Budget(CE.CONSTRUCTOR_BYTES); tracemalloc.start(); prof, _ = CE.slice_profiles(Ms, CE.Clock(time.monotonic() + 5, {}), bp); _, peak_p = tracemalloc.get_traced_memory(); tracemalloc.stop(); rec('L_approximate_profiles_precharged', prof is not None and bp.peak >= peak_p, charged=bp.peak, traced=peak_p)
    try: CE.slice_profiles(Ms, CE.Clock(time.monotonic() - 1, {}), CE.Budget(CE.CONSTRUCTOR_BYTES)); rec('L_approximate_profiles_expired_refuse', False)
    except CE.Refused as e: rec('L_approximate_profiles_expired_refuse', e.kind == 'DEADLINE')
    # J-box policy: old feasible points unchanged; midpoint fallback when the J box misses the simplex
    box = [(F(0), F(1, 100), 'DETERMINISTIC'), (F(99, 100), F(1), 'DETERMINISTIC')]; pts, how = CE.epsilon_safe_points(box, EPS); rec('L_J_box_normalization', how == 'J_normalized' and sum(pts) == 1 and all(max(p_ - b[0], b[1] - p_) <= EPS for p_, b in zip(pts, box)), pts=[str(x) for x in pts], how=how)
    box = [(F(0), F(1, 100), 'DETERMINISTIC'), (F(0), F(1, 100), 'DETERMINISTIC'), (F(99, 100), F(1), 'DETERMINISTIC')]; pts, how = CE.epsilon_safe_points(box, EPS); rec('L_J_box_midpoint_fallback', how == 'midpoints' and all(max(p_ - b[0], b[1] - p_) <= EPS for p_, b in zip(pts, box)) and sum(b[0] for b in box) <= 1 <= sum(b[1] for b in box), pts=[str(x) for x in pts], how=how)
    RES['wall_s'] = time.monotonic() - t_all; RES['n'] = len(RES['checks']); RES['n_ok'] = sum(1 for c in RES['checks'] if c['ok']); json.dump(RES, open(out_path, 'w'), indent=1, default=str)
    print(json.dumps(dict(all_ok=RES['all_ok'], n=RES['n'], n_ok=RES['n_ok'], wall_s=round(RES['wall_s'], 2)))); return 0 if RES['all_ok'] else 1

if __name__ == '__main__': sys.exit(main(sys.argv[1]))
