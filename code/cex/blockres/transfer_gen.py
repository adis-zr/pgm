"""Round-21 transfer-trial generator (TRANSFER_PROTOCOL.md of the R20 theory packet, accepted with the R20 review's clarifications). Deterministic from ONE committed seed. Writes the
eight generated inputs: four 'eligible / plausible' pedigree-style layered models (G1 easy .. G4 near-budget; the parameter sets are DECLARED here, only tables / wiring are random) and four
BOUNDARY cases (B1 channel graph not a matching, B2 residual spanning a large interior interval, B3 broken bulk phase symmetry, B4 ordinary cyclic positive factor graph). Pedigree model:
T loci; per locus every individual has a paternal and a maternal allele (cardinality c_t); founders carry unary priors (optionally with support zeros); each non-founder inherits each allele
from the selected parental allele through a BOOLEAN 4-axis constraint (child, parent_pat, parent_mat, selector); selectors are binary with a [1/2, 1/2] prior at locus 0 and persist across
loci through symmetric channels [theta, 1-theta; 1-theta, theta]; soft genotype (penetrance) factors sit on the LAST locus; one terminal anchor couples an individual's alleles across the
last `span` loci. No model name, hash or constructor output is consulted; the constructor is NOT run here."""
import sys, os, json, random, hashlib
from fractions import Fraction as F
SEED = 20261123
CLASSES = [  # name, kind, declared parameters
    ('G1_easy_c2_theta3-4_zeros', 'pedigree', dict(T=6, N=3, Fo=4, cards=[2], theta=F(3, 4), zeros=True, span=2)),
    ('G2_medium_c3_theta4-5_disconnected', 'pedigree', dict(T=10, N=6, Fo=5, cards=[3], theta=F(4, 5), zeros=False, span=2, extra=dict(T=4, N=1, Fo=2, cards=[2], theta=F(2, 3), zeros=False, span=2))),
    ('G3_near_c23_theta7-10_zeros', 'pedigree', dict(T=16, N=9, Fo=6, cards=[2, 3], theta=F(7, 10), zeros=True, span=2)),
    ('G4_near_c3_theta17-20_span3', 'pedigree', dict(T=18, N=10, Fo=6, cards=[3], theta=F(17, 20), zeros=False, span=3)),
    ('B1_boundary_channel_not_matching', 'pedigree', dict(T=8, N=5, Fo=4, cards=[2], theta=F(3, 5), zeros=False, span=2, branch=True)),
    ('B2_boundary_interior_residual', 'pedigree', dict(T=12, N=5, Fo=4, cards=[2], theta=F(3, 4), zeros=False, span=2, interior=(2, 9))),
    ('B3_boundary_broken_bulk_symmetry', 'pedigree', dict(T=8, N=5, Fo=4, cards=[2], theta=F(3, 4), zeros=False, span=2, asym_locus=4)),
    ('B4_boundary_cyclic_positive_grid', 'grid', dict(rows=5, cols=6)),
]
def pedigree(rng, P, base, cards_out, facs):
    T, N, Fo, span = P['T'], P['N'], P['Fo'], P['span']; cs = [P['cards'][t % len(P['cards'])] for t in range(T)]; theta = P['theta']; n_ind = Fo + N
    a = [[[None, None] for _ in range(n_ind)] for _ in range(T)]; s = [[[None, None] for _ in range(N)] for _ in range(T)]
    for t in range(T):
        for i in range(n_ind):
            for k in (0, 1): a[t][i][k] = len(cards_out); cards_out.append(cs[t])                      # variable ids = positions in the shared card list (a second component continues the numbering)
        for j in range(N):
            for k in (0, 1): s[t][j][k] = len(cards_out); cards_out.append(2)
    parents = []
    for j in range(N):                                                                             # father / mother among founders and EARLIER non-founders, distinct
        pool = list(range(Fo + j)); fa = rng.choice(pool); mo = rng.choice([x for x in pool if x != fa]); parents.append((fa, mo))
    def prior(c, zeros):
        w = [F(rng.randrange(1, 10), 10) for _ in range(c)]
        if zeros and c > 1 and rng.random() < 0.5: w[rng.randrange(c)] = F(0)
        return w
    for t in range(T):
        c = cs[t]
        for f in range(Fo):
            for k in (0, 1): facs.append(((a[t][f][k],), prior(c, P.get('zeros', False))))
        for j in range(N):
            fa, mo = parents[j]; ch = Fo + j
            for k, par in ((0, fa), (1, mo)):
                sel = s[t][j][k]; vals = []
                asym = (P.get('asym_locus') == t and j == 0 and k == 0)
                for x in range(c):
                    for pp in range(c):
                        for pm in range(c):
                            for sv in (0, 1):
                                src = pp if sv == 0 else pm
                                if asym: vals.append(F(9, 10) if x == src else F(1, 10 * (c - 1)) if sv == 0 else (F(7, 10) if x == src else F(3, 10 * (c - 1))))   # soft, selector-dependent mutation: NOT the swap-symmetric pattern
                                else: vals.append(F(1) if x == src else F(0))
                facs.append(((a[t][ch][k], a[t][par][0], a[t][par][1], sel), vals))
                if t == 0: facs.append(((sel,), [F(1, 2), F(1, 2)]))
                if t + 1 < T: facs.append(((sel, s[t + 1][j][k]), [theta, 1 - theta, 1 - theta, theta]))
    if P.get('branch'): j = 0; t = 3; facs.append(((s[t][j][0], s[t + 1][j][1]), [theta, 1 - theta, 1 - theta, theta]))      # a selector feeding TWO channels into the next locus
    for i in range(n_ind):                                                                        # soft genotype factors on the last locus (penetrance)
        c = cs[T - 1]; facs.append(((a[T - 1][i][0], a[T - 1][i][1]), [F(rng.randrange(1, 10), 10) for _ in range(c * c)]))
    i = rng.randrange(n_ind); sc = tuple(a[t][i][0] for t in range(T - span, T)); facs.append((sc, [F(rng.randrange(1, 10), 10) for _ in range(len(sc) and __import__('math').prod(cs[t] for t in range(T - span, T)))]))   # terminal anchor across `span` loci
    if P.get('interior'):
        t1, t2 = P['interior']; i = rng.randrange(n_ind); facs.append(((a[t1][i][0], a[t2][i][0]), [F(rng.randrange(1, 10), 10) for _ in range(cs[t1] * cs[t2])]))
    return len(cards_out)
def grid(rng, P, cards_out, facs):
    R, C = P['rows'], P['cols']; idx = lambda r, c: r * C + c
    for _ in range(R * C): cards_out.append(2)
    for r in range(R):
        for c in range(C):
            facs.append(((idx(r, c),), [F(rng.randrange(1, 10), 10), F(rng.randrange(1, 10), 10)]))
            for dr, dc in ((0, 1), (1, 0)):
                if r + dr < R and c + dc < C: facs.append(((idx(r, c), idx(r + dr, c + dc)), [F(rng.randrange(1, 10), 10) for _ in range(4)]))     # positive, NOT of the channel form in general
def write(path, cards, facs):
    lines = ['MARKOV', str(len(cards)), ' '.join(map(str, cards)), str(len(facs))]
    for sc, _ in facs: lines.append('%d %s' % (len(sc), ' '.join(map(str, sc))))
    for sc, vals in facs: lines.append(str(len(vals))); lines.append(' '.join(str(v) for v in vals))
    open(path, 'w').write('\n'.join(lines) + '\n'); open(path + '.evid', 'w').write('0\n')
def generate(outdir, seed=SEED):
    os.makedirs(outdir, exist_ok=True); rng = random.Random(seed); man = []
    for name, kind, P in CLASSES:
        cards = []; facs = []
        if kind == 'pedigree':
            nv = pedigree(rng, P, 0, cards, facs)
            if P.get('extra'): pedigree(rng, P['extra'], nv, cards, facs)
        else: grid(rng, P, cards, facs)
        p = os.path.join(outdir, name + '.uai'); write(p, cards, facs)
        man.append(dict(name=name, kind=kind, params={k: (str(v) if isinstance(v, F) else v) for k, v in P.items() if k != 'extra'}, extra=({k: (str(v) if isinstance(v, F) else v) for k, v in P['extra'].items()} if P.get('extra') else None), nvars=len(cards), nfactors=len(facs), entries=sum(len(v) for _, v in facs), maxcard=max(cards), model=os.path.abspath(p), evidence=os.path.abspath(p + '.evid'), model_sha256=hashlib.sha256(open(p, 'rb').read()).hexdigest(), evid_sha256=hashlib.sha256(open(p + '.evid', 'rb').read()).hexdigest()))
    return man
if __name__ == '__main__':
    out = sys.argv[1]; man = generate(out, int(sys.argv[2]) if len(sys.argv) > 2 else SEED); json.dump(dict(seed=SEED, generator_sha256=hashlib.sha256(open(__file__, 'rb').read()).hexdigest(), inputs=man), open(os.path.join(out, 'GENERATED_MANIFEST.json'), 'w'), indent=1)
    for m in man: print(m['name'], m['nvars'], 'vars', m['nfactors'], 'factors', m['entries'], 'entries', m['model_sha256'][:12])
