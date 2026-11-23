"""Round-23 frozen coverage-trial generator (CLAUDE_R23_FROZEN_COVERAGE_TRIAL_2026-11-23.md). Deterministic: per-case seed = the first eight SHA-256 bytes (unsigned big-endian) of the UTF-8
string 'BLOCKRES-R23-AR-TRANSFER-v1-2026-11-23|<case_id>'; substreams '|parents', '|tables', '|anchor', '|perm', '|components' are derived the same way with the suffix appended.
Families: pedigree (A1, A2, B1, B2: the transfer_gen semantics -- founders / nonfounders per locus, two allele copies per individual, exact multiplexers, binary selector paths with a uniform
endpoint prior, strictly positive founder weights from {1..9}/10, terminal genotype likelihoods on every individual, the anchor's individual chosen among NONFOUNDERS, optional interior
couplings / likelihoods / evidence); shared-selector multiplexer circuits (C1, C2) exactly as the brief defines them; four tiny boundary cases (D1-D4). After construction every case is
permuted (variable ids, factor order, axes) with its permutation substream; the generative map is kept as a record only. No constructor is run here."""
import sys, os, json, hashlib, random, math, itertools
from fractions import Fraction as F
TAG = 'BLOCKRES-R23-AR-TRANSFER-v1-2026-11-23'
def seed_of(case_id, suffix=''): return int.from_bytes(hashlib.sha256((TAG + '|' + case_id + suffix).encode()).digest()[:8], 'big')
def rng_of(case_id, suffix=''): return random.Random(seed_of(case_id, suffix))
def pos(rng): return F(rng.randrange(1, 10), 10)
def mux_table(c, soft=None):
    """exact multiplexer over (child, p0, p1, sel): child = p0 if sel == 0 else p1; soft: probability on the selected value, the rest uniform over the other child states"""
    vals = []
    for x, a, b, s in itertools.product(range(c), range(c), range(c), range(2)):
        src = a if s == 0 else b
        if soft is None: vals.append(F(int(x == src)))
        else: vals.append(soft if x == src else (1 - soft) / (c - 1))
    return vals
def chan(theta): return [theta, 1 - theta, 1 - theta, theta]

def pedigree(case_id, T, N, Fo, cards, theta, span, interior=(), likelihoods=(), observe=()):
    rp, rt, ra = rng_of(case_id, '|parents'), rng_of(case_id, '|tables'), rng_of(case_id, '|anchor')
    cs = [cards[t % len(cards)] for t in range(T)]; n_ind = Fo + N; cards_out = []; a = [[[None, None] for _ in range(n_ind)] for _ in range(T)]; s = [[[None, None] for _ in range(N)] for _ in range(T)]
    for t in range(T):
        for i in range(n_ind):
            for k in (0, 1): a[t][i][k] = len(cards_out); cards_out.append(cs[t])
        for j in range(N):
            for k in (0, 1): s[t][j][k] = len(cards_out); cards_out.append(2)
    parents = []
    for j in range(N):
        pool = list(range(Fo + j)); fa = rp.choice(pool); mo = rp.choice([x for x in pool if x != fa]); parents.append((fa, mo))
    facs = []; roles = {}
    for t in range(T):
        c = cs[t]
        for f in range(Fo):
            for k in (0, 1): facs.append(((a[t][f][k],), [pos(rt) for _ in range(c)])); roles[len(facs) - 1] = 'founder_unary'
        for j in range(N):
            fa, mo = parents[j]; ch = Fo + j
            for k, par in ((0, fa), (1, mo)):
                sel = s[t][j][k]; facs.append(((a[t][ch][k], a[t][par][0], a[t][par][1], sel), mux_table(c))); roles[len(facs) - 1] = 'multiplexer'
                if t == 0: facs.append(((sel,), [F(1, 2), F(1, 2)])); roles[len(facs) - 1] = 'selector_prior'
                if t + 1 < T: facs.append(((sel, s[t + 1][j][k]), chan(theta))); roles[len(facs) - 1] = 'channel'
    for i in range(n_ind):
        c = cs[T - 1]; facs.append(((a[T - 1][i][0], a[T - 1][i][1]), [pos(rt) for _ in range(c * c)])); roles[len(facs) - 1] = 'terminal_likelihood'
    anchor_ind = Fo + ra.randrange(N); sc = tuple(a[t][anchor_ind][0] for t in range(T - span, T)); facs.append((sc, [pos(rt) for _ in range(math.prod(cs[t] for t in range(T - span, T)))])); roles[len(facs) - 1] = 'terminal_anchor'
    rec = dict(T=T, N=N, Fo=Fo, cards_by_locus=cs, theta=str(theta), span=span, parents=[list(p) for p in parents], anchor_individual=anchor_ind, interior=[], likelihoods=[], observed=[])
    inds = []
    for (ind_k, t1, t2) in interior:                                                                   # paternal alleles of the ind_k-th chosen nonfounder at loci t1, t2
        while len(inds) <= ind_k:
            cand = Fo + ra.randrange(N)
            if cand not in inds: inds.append(cand)
        ind = inds[ind_k]; facs.append(((a[t1][ind][0], a[t2][ind][0]), [pos(rt) for _ in range(cs[t1] * cs[t2])])); roles[len(facs) - 1] = 'interior_coupling'; rec['interior'].append(dict(individual=ind, loci=[t1, t2]))
    for (ind_k, t, weights) in likelihoods:
        ind = inds[ind_k]; facs.append(((a[t][ind][1],), [F(w) for w in weights])); roles[len(facs) - 1] = 'interior_likelihood'; rec['likelihoods'].append(dict(individual=ind, locus=t, weights=[str(F(w)) for w in weights]))
    ev = {}
    for (ind_k, t, state) in observe:
        ind = inds[ind_k]; ev[a[t][ind][1]] = state; rec['observed'].append(dict(individual=ind, locus=t, maternal_allele=a[t][ind][1], state=state))
    return dict(cards=cards_out, factors=[dict(scope=sc, values=v) for sc, v in facs], evidence=ev), roles, rec

def circuit(case_id, R, c, D, L, q, thetas, b_unary):
    rc, rt = rng_of(case_id, '|components'), rng_of(case_id, '|tables'); cards = []; facs = []; roles = {}; A = []; B = []; S = []; X = []
    for r in range(R):
        A.append(len(cards)); cards.append(c); B.append(len(cards)); cards.append(c); S.append([]); X.append([])
        for j in range(L): S[r].append(len(cards)); cards.append(2)
        for j in range(D): X[r].append(len(cards)); cards.append(c)
    for r in range(R):
        facs.append(((A[r],), [pos(rt) for _ in range(c)])); roles[len(facs) - 1] = 'founder_unary_A'
        if b_unary == 'one' or (b_unary == 'parity' and r % 2 == 1):
            for _ in range(1 if b_unary == 'one' else 2): facs.append(((B[r],), [pos(rt) for _ in range(c)])); roles[len(facs) - 1] = 'founder_unary_B'
        facs.append(((S[r][0],), [F(1, 2), F(1, 2)])); roles[len(facs) - 1] = 'selector_prior'
        for j in range(L - 1): facs.append(((S[r][j], S[r][j + 1]), chan(thetas[j % len(thetas)]))); roles[len(facs) - 1] = 'channel'
        prev = A[r]
        for j in range(D): facs.append(((X[r][j], prev, B[r], S[r][j % q]), mux_table(c))); roles[len(facs) - 1] = 'multiplexer'; prev = X[r][j]
        facs.append(((A[r], S[r][L - 1]), [pos(rt) for _ in range(c * 2)])); roles[len(facs) - 1] = 'root_selector_coupling'
        if r + 1 < R: facs.append(((A[r], A[r + 1]), [pos(rt) for _ in range(c * c)])); roles[len(facs) - 1] = 'root_pair'
    return dict(cards=cards, factors=[dict(scope=sc, values=v) for sc, v in facs], evidence={}), roles, dict(R=R, c=c, D=D, L=L, q=q, thetas=[str(t) for t in thetas], b_unary=b_unary, A=A, B=B)

def boundary(case_id):
    rt = rng_of(case_id, '|tables')
    if case_id == 'D1':   # nonuniform selector endpoint prior [1/3, 2/3]; founders A, B (binary), C = mux(A, B, s0), E = mux(C, A, s1); chain s0 - s1 (theta 3/4); likelihood on E
        cards = [2, 2, 2, 2, 2, 2]; A, B, C, E, s0, s1 = range(6)
        fs = [((A,), [pos(rt), pos(rt)]), ((B,), [pos(rt), pos(rt)]), ((C, A, B, s0), mux_table(2)), ((E, C, A, s1), mux_table(2)), ((s0,), [F(1, 3), F(2, 3)]), ((s0, s1), chan(F(3, 4))), ((E,), [pos(rt), pos(rt)])]
        rec = 'nonuniform selector endpoint prior [1/3, 2/3] on s0; exact multiplexers C, E; likelihood on E'
    elif case_id == 'D2':  # branching selector graph: s0 - s1, s0 - s2, s0 - s3; children C_i = mux(A, B, s_i); 10 variables
        cards = [2] * 10; A, B = 0, 1; sel = [2, 3, 4, 5]; ch = [6, 7, 8, 9]
        fs = [((A,), [pos(rt), pos(rt)]), ((B,), [pos(rt), pos(rt)]), ((sel[0],), [F(1, 2), F(1, 2)])] + [((sel[0], sel[i]), chan(F(3, 4))) for i in (1, 2, 3)] + [((ch[i], A, B, sel[i]), mux_table(2)) for i in range(4)] + [((ch[3],), [pos(rt), pos(rt)])]
        rec = 'branching selector graph (s0 feeds s1, s2, s3); every selector drives an exact multiplexer; likelihood on the last child'
    elif case_id == 'D3':  # likelihood AND evidence on multiplexer children: C = mux(A, B, s0) with a likelihood; Dv = mux(A, B, s1) observed = 0
        cards = [3, 3, 3, 3, 2, 2]; A, B, C, Dv, s0, s1 = range(6)
        fs = [((A,), [pos(rt) for _ in range(3)]), ((B,), [pos(rt) for _ in range(3)]), ((C, A, B, s0), mux_table(3)), ((Dv, A, B, s1), mux_table(3)), ((s0,), [F(1, 2), F(1, 2)]), ((s0, s1), chan(F(4, 5))), ((C,), [F(1, 4), F(1, 2), F(1, 4)])]
        return dict(cards=cards, factors=[dict(scope=sc, values=v) for sc, v in fs], evidence={Dv: 0}), 'likelihood on multiplexer child C; evidence Dv = 0 on multiplexer child Dv'
    elif case_id == 'D4':  # one softened multiplexer (9/10 on the selected value) alongside an exact one
        cards = [3, 3, 3, 3, 2, 2]; A, B, C, Dv, s0, s1 = range(6)
        fs = [((A,), [pos(rt) for _ in range(3)]), ((B,), [pos(rt) for _ in range(3)]), ((C, A, B, s0), mux_table(3)), ((Dv, A, B, s1), mux_table(3, soft=F(9, 10))), ((s0,), [F(1, 2), F(1, 2)]), ((s0, s1), chan(F(3, 4))), ((Dv,), [pos(rt) for _ in range(3)])]
        rec = 'exact multiplexer C alongside a normalized softened multiplexer Dv (9/10 on the selected value, 1/20 on each other state); likelihood on Dv'
    return dict(cards=cards, factors=[dict(scope=sc, values=v) for sc, v in fs], evidence={}), rec

def permute(case_id, m):
    """variable ids, factor order and axes permuted with the '|perm' substream; returns (model, map old var -> new var)"""
    rng = rng_of(case_id, '|perm'); n = len(m['cards']); pi = list(range(n)); rng.shuffle(pi); cards = [0] * n
    for v, p in enumerate(pi): cards[p] = m['cards'][v]
    fs = []
    for f in m['factors']:
        old = list(f['scope']); ps = list(range(len(old))); rng.shuffle(ps); neworder = [old[i] for i in ps]; vals = []
        for xs in itertools.product(*(range(m['cards'][v]) for v in neworder)):
            env = dict(zip(neworder, xs)); ix = 0
            for v in old: ix = ix * m['cards'][v] + env[v]
            vals.append(f['values'][ix])
        fs.append(dict(scope=tuple(pi[v] for v in neworder), values=vals))
    rng.shuffle(fs)
    return dict(cards=cards, factors=fs, evidence={pi[v]: a for v, a in m['evidence'].items()}), pi

def write(path, m):
    lines = ['MARKOV', str(len(m['cards'])), ' '.join(map(str, m['cards'])), str(len(m['factors']))]
    for f in m['factors']: lines.append('%d %s' % (len(f['scope']), ' '.join(map(str, f['scope']))))
    for f in m['factors']: lines.append(str(len(f['values']))); lines.append(' '.join(str(v) for v in f['values']))
    open(path, 'w').write('\n'.join(lines) + '\n'); ev = m['evidence']; open(path + '.evid', 'w').write(('%d ' % len(ev)) + ' '.join('%d %d' % kv for kv in ev.items()) + '\n')

def validate(m):
    """syntax, table lengths, nonnegativity, declared local normalisation identities (multiplexers / softened multiplexers sum to 1 over the child for every (p0, p1, sel); channel rows sum to 1; selector priors sum to 1)"""
    cards = m['cards']; issues = []
    for i, f in enumerate(m['factors']):
        sc = f['scope']; vals = f['values']
        if len(vals) != math.prod(cards[v] for v in sc): issues.append('factor %d length' % i)
        if any(v < 0 for v in vals): issues.append('factor %d negative' % i)
    return issues

MAX_ENUM = 4096
def enumerate_exact(m):
    """independent exact enumeration (visits every assignment incl. observed states; bounded by MAX_ENUM): returns Z and per-coordinate marginals of the unobserved variables"""
    cards = m['cards']; total = math.prod(cards)
    if total > MAX_ENUM: raise AssertionError('enumeration of %d assignments exceeds the admission limit %d' % (total, MAX_ENUM))
    ev = m['evidence']; z = F(0); num = {}
    for xs in itertools.product(*(range(c) for c in cards)):
        if any(xs[v] != a for v, a in ev.items()): continue
        w = F(1)
        for f in m['factors']:
            ix = 0
            for v in f['scope']: ix = ix * cards[v] + xs[v]
            w *= f['values'][ix]
            if not w: break
        if not w: continue
        z += w
        for v in range(len(cards)):
            if v not in ev: num[(v, xs[v])] = num.get((v, xs[v]), F(0)) + w
    return z, ({k: v / z for k, v in num.items()} if z else None)

CASES = [
    ('A1', 'pedigree', dict(T=20, N=8, Fo=5, cards=[2], theta=F(3, 4), span=4)),
    ('A2', 'pedigree', dict(T=24, N=10, Fo=6, cards=[2, 3], theta=F(1, 5), span=5)),
    ('B1', 'pedigree', dict(T=18, N=8, Fo=5, cards=[2], theta=F(4, 5), span=3, interior=[(0, 3, 10)], observe=[(0, 9, 0)])),
    ('B2', 'pedigree', dict(T=20, N=10, Fo=6, cards=[3], theta=F(7, 10), span=3, interior=[(0, 2, 8), (1, 8, 14)], likelihoods=[(0, 5, [F(1, 4), F(1, 2), F(3, 4)])], observe=[(1, 9, 1)])),
    ('C1', 'circuit', dict(R=8, c=3, D=18, L=12, q=4, thetas=[F(3, 4)], b_unary='one')),
    ('C2', 'circuit', dict(R=12, c=3, D=24, L=18, q=6, thetas=[F(1, 5), F(1, 2), F(4, 5)], b_unary='parity')),
    ('D1', 'boundary', {}), ('D2', 'boundary', {}), ('D3', 'boundary', {}), ('D4', 'boundary', {}),
]
def generate(outdir):
    os.makedirs(outdir, exist_ok=True); man = []
    for cid, kind, P in CASES:
        if kind == 'pedigree': m0, roles, rec = pedigree(cid, **P)
        elif kind == 'circuit': m0, roles, rec = circuit(cid, **P)
        else: m0, rec = boundary(cid); roles = {}
        m, pi = permute(cid, m0); issues = validate(m) + validate(m0); p = os.path.join(outdir, cid + '.uai'); write(p, m)
        gm = dict(case=cid, kind=kind, generator_tag=TAG, seeds={k: seed_of(cid, k) for k in ('', '|parents', '|tables', '|anchor', '|perm', '|components')}, params=json.loads(json.dumps(P, default=str)), generative_record=rec, roles_by_original_factor_index=roles, variable_map_old_to_new=pi)
        json.dump(gm, open(os.path.join(outdir, cid + '.generative_map.json'), 'w'), indent=1, default=str)
        man.append(dict(name=cid, kind=kind, params=json.loads(json.dumps(P, default=str)), nvars=len(m['cards']), nfactors=len(m['factors']), entries=sum(len(f['values']) for f in m['factors']), maxcard=max(m['cards']), evidence=len(m['evidence']), K=sum(c for v, c in enumerate(m['cards']) if v not in m['evidence']), validation_issues=issues, model=os.path.abspath(p), evidence_file=os.path.abspath(p + '.evid'), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), evid_sha256=hashlib.sha256(open(p + '.evid', 'rb').read()).hexdigest()))
    json.dump(dict(tag=TAG, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), inputs=man), open(os.path.join(outdir, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    return man
if __name__ == '__main__':
    for m in generate(sys.argv[1]): print(m['name'], m['nvars'], 'vars', m['nfactors'], 'factors', m['entries'], 'entries', 'K', m['K'], 'evid', m['evidence'], m['model_sha256'][:12], 'issues', m['validation_issues'])
